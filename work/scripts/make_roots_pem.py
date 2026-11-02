"""Write scripts\\roots.pem: the public root certificates our download hosts chain to.

WHY. The installer verifies HTTPS with Python's OpenSSL, whose trust store is built by ENUMERATING the
Windows ROOT store (ssl.create_default_context -> load_default_certs -> enum_certificates). Windows 7's
store fills itself with modern roots only when CryptoAPI builds a chain (IE, Windows Update) -- never
from an enumeration -- so a Windows 7 that never browsed to our certificate authorities fails every
fetch with CERTIFICATE_VERIFY_FAILED: no update check, no HD packs, no self-update (audit 2026-11-01,
reproduced under the shipped 3.8 runtime with an empty store). fetch.py loads this bundle IN ADDITION
to the Windows store, so nothing changes on a Windows that already has the roots. Trust in what is
downloaded rests on the Ed25519 manifest signature anyway; these roots only let the connection happen.

HOW. The roots are taken from THIS machine's Windows ROOT store by subject name (Windows 11 keeps the
Microsoft Trusted Root Program's set), so nothing is typed in by hand. Hosts (2026-11-01): longevitymods.com
(CloudFront: Amazon RSA 2048 -> Amazon Root CA 1, cross-signed by Starfield Services Root CA G2);
github.com (Sectigo -> USERTrust ECC/RSA); release-assets/objects.githubusercontent.com (Let's Encrypt ->
ISRG Root X1). DigiCert's two roots are there for a CDN change. Re-run when a host moves to another CA;
test_roots_pem.py pins the set and (with LONGEVITY_NET_TESTS=1) proves the bundle alone verifies the hosts.

    py work\\scripts\\make_roots_pem.py
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import os
import ssl
import sys
import tempfile
from pathlib import Path

OUT = Path(__file__).resolve().with_name("roots.pem")

#: Must be present, or the bundle is not written (a host would be unreachable on Windows 7).
REQUIRED = (
    "Starfield Services Root Certificate Authority - G2",   # Amazon Root CA 1 is cross-signed by it
    "ISRG Root X1",
    "USERTrust ECC Certification Authority",
    "USERTrust RSA Certification Authority",
    "DigiCert Global Root G2",
    "DigiCert Global Root CA",
)
#: Included when this machine's store has them (self-signed copies; the chains above work without).
OPTIONAL = ("Amazon Root CA 1", "Amazon Root CA 2", "Amazon Root CA 3", "Amazon Root CA 4", "ISRG Root X2")


def _decode(pem: str) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
        f.write(pem)
        p = f.name
    try:
        return ssl._ssl._test_decode_cert(p)   # noqa: SLF001 - the stdlib's own certificate reader
    finally:
        os.unlink(p)


def collect() -> dict:
    """commonName -> (pem, notAfter, sha256) for every wanted root in the Windows ROOT store."""
    want = set(REQUIRED) | set(OPTIONAL)
    found = {}
    for der, _enc, _trust in ssl.enum_certificates("ROOT"):
        pem = ssl.DER_cert_to_PEM_cert(der)
        info = _decode(pem)
        subject = dict(x[0] for x in info["subject"])
        cn = subject.get("commonName")
        if cn in want and cn not in found and subject == dict(x[0] for x in info["issuer"]):   # self-signed only
            found[cn] = (pem, info["notAfter"], hashlib.sha256(der).hexdigest())
    return found


def write(out: Path = OUT) -> list:
    found = collect()
    missing = [cn for cn in REQUIRED if cn not in found]
    if missing:
        raise SystemExit(f"ERROR: this machine's ROOT store lacks {missing}; browse to the hosts once (IE/Edge fills "
                         "the store) or run on a machine that has them")
    lines = [f"# Public root certificates the Longevity Vaccine download hosts chain to (see make_roots_pem.py).",
             f"# Loaded by fetch.py IN ADDITION to the Windows certificate store. Generated {_dt.date.today().isoformat()}",
             f"# from the Windows ROOT store; {len(found)} roots."]
    for cn in list(REQUIRED) + [c for c in OPTIONAL if c in found]:
        pem, not_after, fp = found[cn]
        lines.append(f"\n# {cn}\n# sha256 {fp}\n# notAfter {not_after}\n{pem.strip()}")
    out.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    return sorted(found)


if __name__ == "__main__":
    got = write()
    print(f"  {OUT}: {len(got)} roots: {', '.join(got)}")
    print("  missing optional:", sorted(set(OPTIONAL) - set(got)) or "none")
    sys.exit(0)
