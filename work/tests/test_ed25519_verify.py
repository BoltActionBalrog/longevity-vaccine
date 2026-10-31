"""Ed25519 verification, checked against RFC 8032's official test vectors.

This is the gate on every update a player will ever install, so it is tested against the
specification's own vectors rather than against our own signer -- a self-consistent bug (sign and
verify wrong in the same way) would pass a round-trip test and still accept forgeries.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import ed25519_verify as ed  # noqa: E402

# RFC 8032 section 7.1, TEST 1 / TEST 2 / TEST 3 / TEST 1024 / TEST SHA(abc).
# (secret key, public key, message, signature) -- all hex.
RFC8032 = [
    (  # TEST 1 -- empty message
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (  # TEST 2 -- one byte
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
        "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
    (  # TEST 3 -- two bytes
        "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "af82",
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
        "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
    ),
    (  # TEST SHA(abc) -- 64-byte message
        "833fe62409237b9d62ec77587520911e9a759cec1d19755b7da901b96dca3d42",
        "ec172b93ad5e563bf4932c70e1245034c35467ef2efd4d64ebf819683467e2bf",
        "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
        "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f",
        "dc2a4459e7369633a52b1bf277839a00201009a3efbf3ecb69bea2186c26b589"
        "09351fc9ac90b3ecfdfbc7c66431e0303dca179c138ac17ad9bef1177331a704",
    ),
]


@pytest.mark.parametrize("sk,pk,msg,sig", RFC8032,
                         ids=["empty", "1byte", "2bytes", "sha-abc"])
def test_rfc8032_vectors_verify(sk, pk, msg, sig):
    assert ed.verify(bytes.fromhex(pk), bytes.fromhex(sig), bytes.fromhex(msg)) is True


@pytest.mark.parametrize("sk,pk,msg,sig", RFC8032,
                         ids=["empty", "1byte", "2bytes", "sha-abc"])
def test_a_flipped_message_bit_is_rejected(sk, pk, msg, sig):
    m = bytearray(bytes.fromhex(msg) or b"\x00")
    m[0] ^= 0x01
    assert ed.verify(bytes.fromhex(pk), bytes.fromhex(sig), bytes(m)) is False


@pytest.mark.parametrize("sk,pk,msg,sig", RFC8032,
                         ids=["empty", "1byte", "2bytes", "sha-abc"])
def test_a_flipped_signature_bit_is_rejected(sk, pk, msg, sig):
    for pos in (0, 31, 32, 63):
        s = bytearray(bytes.fromhex(sig))
        s[pos] ^= 0x01
        assert ed.verify(bytes.fromhex(pk), bytes(s), bytes.fromhex(msg)) is False, pos


@pytest.mark.parametrize("sk,pk,msg,sig", RFC8032,
                         ids=["empty", "1byte", "2bytes", "sha-abc"])
def test_a_different_public_key_is_rejected(sk, pk, msg, sig):
    other = RFC8032[(RFC8032.index((sk, pk, msg, sig)) + 1) % len(RFC8032)][1]
    assert ed.verify(bytes.fromhex(other), bytes.fromhex(sig), bytes.fromhex(msg)) is False


def test_non_canonical_S_is_rejected():
    """S >= L must be refused, or signatures are malleable: a third party could derive a
    different 64-byte string that still verifies for the same message."""
    sk, pk, msg, sig = RFC8032[1]
    raw = bytes.fromhex(sig)
    s = int.from_bytes(raw[32:], "little")
    mauled = raw[:32] + ((s + ed.L) % (1 << 256)).to_bytes(32, "little")
    assert ed.verify(bytes.fromhex(pk), mauled, bytes.fromhex(msg)) is False


def test_an_off_curve_point_is_actually_rejected_by_the_curve_check():
    """The previous version of this test used y = p-1, which IS a valid (order-2) point -- it
    passed only because the signature did not match that key, so the _on_curve branch was never
    exercised at all. y = 2 is genuinely off the curve."""
    off = None
    for y in range(2, 40):
        if ed._decode_point(y.to_bytes(32, "little")) is None:
            off = y
            break
    assert off is not None, "expected some small y to be off-curve"
    # Prove it is the curve check that rejects it, not a length or range check.
    xx = (off * off - 1) * pow(ed._D * off * off + 1, ed.P - 2, ed.P) % ed.P
    assert pow(xx, (ed.P - 1) // 2, ed.P) != 1, "y should have no square root -> off curve"
    sk, pk, msg, sig = RFC8032[1]
    assert ed.verify(off.to_bytes(32, "little"), bytes.fromhex(sig), bytes.fromhex(msg)) is False


def test_non_canonical_y_encoding_is_actually_rejected():
    """y >= p encodes the same point two ways and must be refused.

    The previous version added P to y, which sets bit 255 -- so the masked y came back as y-19,
    a DIFFERENT valid point, and the `y >= P` branch was never taken. A real non-canonical
    encoding needs the masked value itself in [P, 2**255-1].
    """
    for n in (ed.P, ed.P + 1, (1 << 255) - 1):
        assert ed._decode_point(n.to_bytes(32, "little")) is None, hex(n)
    sk, pk, msg, sig = RFC8032[1]
    assert ed.verify(ed.P.to_bytes(32, "little"), bytes.fromhex(sig),
                     bytes.fromhex(msg)) is False


def test_x_zero_with_the_sign_bit_set_is_rejected():
    """RFC 8032 section 5.1.3 says decoding MUST fail when x == 0 and x_0 == 1. Otherwise
    `x = P - x` yields an unreduced P and two byte strings decode to one point."""
    for y in (1, ed.P - 1):                      # the identity and the order-2 point
        assert ed._decode_point((y | (1 << 255)).to_bytes(32, "little")) is None, y


def test_small_order_public_keys_are_rejected():
    """A = identity makes [S]B == R + [h]A collapse to [S]B == R, so ANY message can be signed
    without a secret key. OpenSSL accepts these; we must not."""
    import sign_manifest as sm
    identity = (1).to_bytes(32, "little")
    s = 12345678901234567890 % ed.L
    forged = sm._encode_point(ed._scalarmult(ed._B, s)) + s.to_bytes(32, "little")
    assert ed.verify(identity, forged, b"an evil manifest") is False, \
        "a universal forgery was accepted"
    # The order-2 point too.
    assert ed.verify((ed.P - 1).to_bytes(32, "little"), forged, b"x") is False


def test_bytes_hex_is_refused_rather_than_raising():
    """bytes.fromhex(b"aa") raises TypeError, not ValueError. A caller that read the .sig with
    read_bytes() used to get a traceback out of a function documented never to raise -- which
    bypassed every `except ManifestError` handler and crashed the installer."""
    sk, pk, msg, sig = RFC8032[1]
    assert ed.verify_detached(pk.encode(), sig, bytes.fromhex(msg)) is False
    assert ed.verify_detached(pk, sig.encode(), bytes.fromhex(msg)) is False
    assert ed.verify_detached(bytearray(pk.encode()), sig, b"") is False


def test_hex_input_is_case_and_whitespace_tolerant():
    sk, pk, msg, sig = RFC8032[2]
    assert ed.verify_detached(pk.upper(), sig, bytes.fromhex(msg)) is True
    assert ed.verify_detached(pk + "\n", " " + sig + " ", bytes.fromhex(msg)) is True


@pytest.mark.parametrize("sk,pk,msg,sig", RFC8032,
                         ids=["empty", "1byte", "2bytes", "sha-abc"])
def test_our_signer_matches_the_rfc_vectors_byte_for_byte(sk, pk, msg, sig):
    """Pins the SIGNER against the specification, not against our own verifier.

    The `sk` column was previously unused, so sign_manifest had no external pin at all -- its only
    check was a round-trip through the verifier it shares arithmetic with, meaning a common bug in
    `_add`/`_scalarmult`/`_B` would have passed both.
    """
    import sign_manifest as sm
    seed = bytes.fromhex(sk)
    assert sm.public_key(seed).hex() == pk
    assert sm.sign(seed, bytes.fromhex(msg)).hex() == sig
    assert sm.sign(seed, bytes.fromhex(msg)) == sm.sign(seed, bytes.fromhex(msg)), "not deterministic"


@pytest.mark.parametrize("pk,sig,msg", [
    (b"", b"\x00" * 64, b"m"),
    (b"\x00" * 31, b"\x00" * 64, b"m"),
    (b"\x00" * 33, b"\x00" * 64, b"m"),
    (b"\x00" * 32, b"\x00" * 63, b"m"),
    (b"\x00" * 32, b"\x00" * 65, b"m"),
    (None, b"\x00" * 64, b"m"),
    (b"\x00" * 32, None, b"m"),
    (b"\x00" * 32, b"\x00" * 64, None),
    ("not bytes", b"\x00" * 64, b"m"),
    (b"\x00" * 32, "not bytes", b"m"),
])
def test_malformed_input_returns_false_and_never_raises(pk, sig, msg):
    assert ed.verify(pk, sig, msg) is False


def test_all_zero_signature_is_rejected():
    sk, pk, msg, sig = RFC8032[1]
    assert ed.verify(bytes.fromhex(pk), b"\x00" * 64, bytes.fromhex(msg)) is False


def test_verify_detached_hex_wrapper():
    sk, pk, msg, sig = RFC8032[2]
    assert ed.verify_detached(pk, sig, bytes.fromhex(msg)) is True
    assert ed.verify_detached(pk, sig, b"different") is False
    assert ed.verify_detached("not hex", sig, bytes.fromhex(msg)) is False
    assert ed.verify_detached(pk, "zz" * 64, bytes.fromhex(msg)) is False
    assert ed.verify_detached(None, sig, b"") is False


def test_base_point_matches_the_rfc():
    """A wrong base point would make every one of our own signatures verify against each other
    while rejecting the RFC vectors -- so pin the constant itself."""
    bx, by = ed._to_affine(ed._B)
    assert by == (4 * pow(5, ed.P - 2, ed.P)) % ed.P
    assert ed._on_curve(bx, by)
    # Order: [L]B must be the neutral element (0, 1).
    assert ed._to_affine(ed._scalarmult(ed._B, ed.L)) == (0, 1)


def test_curve_constants():
    assert ed.P == 2 ** 255 - 19
    assert ed.L == 2 ** 252 + 27742317777372353535851937790883648493
    assert hashlib.sha512  # the hash the spec mandates
