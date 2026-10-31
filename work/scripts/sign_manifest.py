"""Generate the release signing key and sign a manifest. DEV-ONLY -- never shipped.

    py work\\scripts\\sign_manifest.py --keygen <KEYFILE>
    py work\\scripts\\sign_manifest.py --key <KEYFILE> --manifest <manifest.json>

THE KEY: the private half is never committed (this tool refuses a key path inside the
checkout), never put in CI and never printed. It is the one credential whose compromise means
arbitrary code execution on every player's machine -- and whose LOSS permanently strands every
installed copy, because those installs will only accept updates signed by the key they shipped
with. Whoever signs releases keeps it, and a backup of it, outside every repository.

The curve arithmetic is imported from ed25519_verify so there is exactly one implementation; that
module deliberately exposes no signing function, so signing capability does not ship.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import ed25519_verify as ed  # noqa: E402

_REPO = _SCRIPTS.parent.parent
SEED_SIZE = 32


def _secret_scalar(seed: bytes) -> tuple[int, bytes]:
    """RFC 8032 section 5.1.5: expand the 32-byte seed into the scalar and the prefix."""
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8      # clear the low 3 bits
    a |= (1 << 254)          # set bit 254
    return a, h[32:]


def _encode_point(pt) -> bytes:
    x, y = ed._to_affine(pt)
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def public_key(seed: bytes) -> bytes:
    a, _ = _secret_scalar(seed)
    return _encode_point(ed._scalarmult(ed._B, a))


def sign(seed: bytes, message: bytes) -> bytes:
    """Deterministic Ed25519 signature (RFC 8032 section 5.1.6)."""
    if not isinstance(seed, (bytes, bytearray)) or len(seed) != SEED_SIZE:
        raise ValueError(f"seed must be {SEED_SIZE} bytes")
    a, prefix = _secret_scalar(bytes(seed))
    pk = _encode_point(ed._scalarmult(ed._B, a))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % ed.L
    r_enc = _encode_point(ed._scalarmult(ed._B, r))
    k = int.from_bytes(hashlib.sha512(r_enc + pk + message).digest(), "little") % ed.L
    s = (r + k * a) % ed.L
    return r_enc + s.to_bytes(32, "little")


def keygen(path: Path) -> bytes:
    """Create a new signing key. Refuses to overwrite, and refuses to sit inside the repo."""
    path = Path(path)
    if path.exists():
        raise SystemExit(f"REFUSING: {path} already exists. A signing key is never regenerated "
                         "in place -- losing it strands every installed copy of the mod.")
    # Reject anything that is not a plain local drive path FIRST. `Path.resolve()` leaves
    # `\\?\D:\...`, `\\localhost\D$\...` and unexpanded 8.3 names alone, so `is_relative_to`
    # returned False for each of them and the key would have been written into the working tree
    # through an alias.
    raw = str(path)
    drive = Path(raw).drive
    if raw.startswith("\\\\") or drive.startswith("\\\\") or not drive.endswith(":"):
        raise SystemExit(
            f"REFUSING: {path} is not a plain local drive path (got drive {drive!r}). UNC, "
            "extended-length (\\\\?\\) and network paths are refused because they can alias into "
            "the repository, where a private key must never be written.")
    try:
        resolved = Path(os.path.realpath(str(path)))
        inside = os.path.normcase(str(resolved)).startswith(
            os.path.normcase(str(Path(os.path.realpath(str(_REPO))))) + os.sep)
    except (OSError, ValueError):
        inside = True          # cannot tell -> refuse; a key in the repo is unrecoverable
    if inside:
        raise SystemExit(f"REFUSING: {path} is inside the repository ({_REPO}). The private key "
                         "must not live anywhere it can be committed. Put it outside the repo, "
                         "on a path you back up offline.")

    seed = os.urandom(SEED_SIZE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(seed.hex() + "\n", encoding="ascii")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)     # best-effort on Windows
    except OSError:
        pass
    pk = public_key(seed)
    print(f"Private key written : {path}")
    print("  Back this up offline NOW, on separate media. If it is lost, every installed copy")
    print("  of the mod stops accepting updates permanently and the only fix is a reinstall.")
    print()
    print(f"Public key (hex)    : {pk.hex()}")
    print("  Embed this as PUBLIC_KEY_HEX in work\\scripts\\manifest.py.")
    return pk


def load_seed(path: Path) -> bytes:
    raw = Path(path).read_text(encoding="ascii").strip()
    try:
        seed = bytes.fromhex(raw)
    except ValueError:
        raise SystemExit(f"{path} does not contain a hex seed")
    if len(seed) != SEED_SIZE:
        raise SystemExit(f"{path} holds {len(seed)} bytes; expected {SEED_SIZE}")
    return seed


def sign_file(seed: bytes, manifest: Path) -> Path:
    """Sign the manifest's EXACT bytes and write <manifest>.sig beside it."""
    manifest = Path(manifest)
    raw = manifest.read_bytes()
    sig = sign(seed, raw)
    out = manifest.with_suffix(manifest.suffix + ".sig")
    out.write_text(sig.hex() + "\n", encoding="ascii")

    # Verify what we just wrote, through the same code the installer will use. A signer that
    # produces something its own verifier rejects must fail here, not on a player's machine.
    if not ed.verify(public_key(seed), sig, raw):
        out.unlink(missing_ok=True)
        raise SystemExit("INTERNAL ERROR: the signature we just produced does not verify. "
                         "Refusing to leave it on disk.")
    print(f"Signed {manifest.name} ({len(raw)} bytes) -> {out.name}")
    print(f"  public key: {public_key(seed).hex()}")
    return out


def main() -> int:
    apr = argparse.ArgumentParser(description="Generate the signing key / sign a manifest.")
    apr.add_argument("--keygen", metavar="PATH", help="create a new signing key at PATH")
    apr.add_argument("--key", metavar="PATH", help="signing key to use")
    apr.add_argument("--manifest", metavar="PATH", help="manifest.json to sign")
    apr.add_argument("--show-public", action="store_true",
                     help="print the public key for --key and exit")
    args = apr.parse_args()

    if args.keygen:
        keygen(Path(args.keygen))
        return 0
    if not args.key:
        apr.error("--key is required (or use --keygen)")
    seed = load_seed(Path(args.key))
    if args.show_public:
        print(public_key(seed).hex())
        return 0
    if not args.manifest:
        apr.error("--manifest is required")
    sign_file(seed, Path(args.manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
