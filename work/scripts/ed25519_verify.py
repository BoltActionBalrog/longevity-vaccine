"""Ed25519 signature VERIFICATION, pure Python, no dependencies.

Why hand-rolled rather than `cryptography`: this ships inside the installer, and the payload-trim
task takes the bundled interpreter down to the embeddable CPython with exactly pyyaml + pefile.
`cryptography` would drag in a large compiled Rust wheel and fight that directly. The house style
already is "pure integer arithmetic with an exhaustive test sweep" (work\\scripts\\scaling_laws.py),
and verification is ~100 lines of modular arithmetic that RFC 8032 specifies exactly.

WHAT THIS IS FOR: an auto-updater is a remote-code-execution channel by design. HTTPS protects
transport, but a compromised bucket or build pipeline would push straight to players. The manifest
carries a detached signature made by a key that never leaves the dev machine, and the installer
refuses to act on a manifest that does not verify against the public key compiled into it.

SIGNING LIVES ELSEWHERE (work\\scripts\\sign_manifest.py, dev-only, never shipped). This module
deliberately exposes no signing function.

Implementation notes that matter for correctness:
  * Verification is the cofactorless form RFC 8032 section 5.1.7 gives: [S]B == R + [h]A.
  * A signature with S >= L is REJECTED. Accepting it would make signatures malleable -- a third
    party could produce a different byte string that still verifies for the same message.
  * Decoded points are checked to be ON the curve. Skipping that check is a known way to accept
    garbage.
  * No timing hardening: there is no secret here. We verify a public signature with a public key,
    and the only thing a timing channel could leak is the message, which is public.
"""

from __future__ import annotations

import hashlib

# Curve25519 / edwards25519 constants, RFC 8032 section 5.1.
P = 2 ** 255 - 19                                                     # field prime
L = 2 ** 252 + 27742317777372353535851937790883648493                 # group order
_D = (-121665 * pow(121666, P - 2, P)) % P                            # curve parameter d
_I = pow(2, (P - 1) // 4, P)                                          # sqrt(-1) mod p

SIGNATURE_SIZE = 64
PUBLIC_KEY_SIZE = 32


def _x_recover(y: int) -> int:
    """Recover x from y on edwards25519 (RFC 8032 section 5.1.3)."""
    xx = (y * y - 1) * pow(_D * y * y + 1, P - 2, P)
    x = pow(xx, (P + 3) // 8, P)
    if (x * x - xx) % P != 0:
        x = (x * _I) % P
    if x % 2 != 0:
        x = P - x
    return x


_BY = (4 * pow(5, P - 2, P)) % P
_B = (_x_recover(_BY) % P, _BY, 1, (_x_recover(_BY) * _BY) % P)        # base point, extended


def _add(pt1, pt2):
    """Extended-coordinate point addition (x, y, z, t)."""
    x1, y1, z1, t1 = pt1
    x2, y2, z2, t2 = pt2
    a = (y1 - x1) * (y2 - x2) % P
    b = (y1 + x1) * (y2 + x2) % P
    c = t1 * 2 * _D * t2 % P
    dd = z1 * 2 * z2 % P
    e, f, g, h = b - a, dd - c, dd + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _double(pt):
    return _add(pt, pt)


def _scalarmult(pt, e: int):
    """Montgomery-ladder-free double-and-add. Constant time is not required (no secrets)."""
    result = (0, 1, 1, 0)      # neutral element
    while e > 0:
        if e & 1:
            result = _add(result, pt)
        pt = _double(pt)
        e >>= 1
    return result


def _to_affine(pt):
    x, y, z, _t = pt
    zi = pow(z, P - 2, P)
    return (x * zi % P, y * zi % P)


def _on_curve(x: int, y: int) -> bool:
    """-x^2 + y^2 = 1 + d x^2 y^2  (mod p)."""
    xx, yy = x * x % P, y * y % P
    return (-xx + yy - 1 - _D * xx % P * yy) % P == 0


def _is_small_order(pt) -> bool:
    """True if `pt` has order dividing 8 (the identity or an 8-torsion point).

    Such a point as the PUBLIC KEY is a universal forgery: with A = identity,
    [S]B == R + [h]A reduces to [S]B == R for any h, so anyone can sign any message without
    knowing a secret. OpenSSL accepts these; libsodium rejects them, and so do we -- the moment a
    public key can come from a file, an env var or a flag (LONGEVITY_TRUST_KEY already can), this
    is the difference between a trust anchor and an open door.
    """
    return _to_affine(_scalarmult(pt, 8)) == (0, 1)


def _decode_point(raw: bytes, *, reject_small_order: bool = False):
    """Decode a 32-byte compressed point, or return None if it is not a valid curve point."""
    if len(raw) != 32:
        return None
    n = int.from_bytes(raw, "little")
    y = n & ((1 << 255) - 1)
    if y >= P:                       # non-canonical y encoding
        return None
    x = _x_recover(y)
    x_0 = (n >> 255) & 1
    if x == 0 and x_0 == 1:
        # RFC 8032 section 5.1.3: decoding MUST fail here. Otherwise `x = P - x` below yields an
        # unreduced P and two byte strings decode to the same point -- exactly the
        # non-canonicality this function exists to reject.
        return None
    if x & 1 != x_0:
        x = P - x
    if not _on_curve(x, y):
        return None
    pt = (x, y, 1, x * y % P)
    if reject_small_order and _is_small_order(pt):
        return None
    return pt


def _h_int(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little")


def verify(public_key: bytes, signature: bytes, message: bytes) -> bool:
    """True iff `signature` is a valid Ed25519 signature of `message` under `public_key`.

    Returns False for every malformed input rather than raising: callers use this as a gate on
    untrusted bytes, so it must not be the thing that throws.
    """
    try:
        if not isinstance(public_key, (bytes, bytearray)) or len(public_key) != PUBLIC_KEY_SIZE:
            return False
        if not isinstance(signature, (bytes, bytearray)) or len(signature) != SIGNATURE_SIZE:
            return False
        if not isinstance(message, (bytes, bytearray)):
            return False

        r_raw = bytes(signature[:32])
        s = int.from_bytes(signature[32:], "little")
        if s >= L:
            # Reject non-canonical S. Without this, signatures are malleable: a third party can
            # derive a different 64-byte string that still verifies for the same message.
            return False

        # The public key must be a full-order point (see _is_small_order). R is checked the same
        # way: a small-order R is not a forgery path on its own, but accepting it serves no
        # purpose and libsodium refuses it.
        a_pt = _decode_point(bytes(public_key), reject_small_order=True)
        r_pt = _decode_point(r_raw, reject_small_order=True)
        if a_pt is None or r_pt is None:
            return False

        h = _h_int(r_raw + bytes(public_key) + bytes(message)) % L
        lhs = _to_affine(_scalarmult(_B, s))
        rhs = _to_affine(_add(r_pt, _scalarmult(a_pt, h)))
        return lhs == rhs
    except Exception:  # noqa: BLE001 - a gate on untrusted bytes must never raise
        return False


def verify_detached(public_key_hex: str, signature_hex: str, message: bytes) -> bool:
    """Convenience wrapper for the hex forms stored in manifest.sig / embedded in the installer."""
    try:
        pk = bytes.fromhex(public_key_hex.strip())
        sig = bytes.fromhex(signature_hex.strip())
    except (ValueError, AttributeError, TypeError):
        # TypeError matters: bytes.fromhex(b"aabb") raises TypeError, not ValueError, so a caller
        # that read the .sig with read_bytes() instead of read_text() used to get a traceback out
        # of a function documented never to raise -- bypassing every `except ManifestError`
        # handler and crashing the installer instead of reporting an untrusted manifest.
        return False
    return verify(pk, sig, message)
