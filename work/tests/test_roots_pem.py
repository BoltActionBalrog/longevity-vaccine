"""scripts\\roots.pem: the public roots fetch.py trusts BESIDE the Windows store.

Python's OpenSSL takes its roots from the Windows ROOT store by enumeration, which never triggers
Windows 7's root auto-update; a Windows 7 that never browsed to our certificate authorities failed
every fetch (CERTIFICATE_VERIFY_FAILED, reproduced under the shipped 3.8 runtime with an empty store).
The bundle is generated from THIS machine's store by make_roots_pem.py and pinned here; with
LONGEVITY_NET_TESTS=1 the bundle ALONE must verify the real hosts (the suite stays offline otherwise).
"""
from __future__ import annotations

import os
import re
import socket
import ssl
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_SCRIPTS = _TESTS.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import fetch as fetchmod       # noqa: E402
import make_roots_pem as mrp   # noqa: E402
import release as rel          # noqa: E402

PEM = _SCRIPTS / "roots.pem"
HOSTS = ("longevitymods.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")


def _certs(text: str) -> list:
    return re.findall(r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", text, re.S)


def test_the_bundle_exists_and_holds_every_required_root():
    text = PEM.read_text(encoding="ascii")
    assert len(_certs(text)) >= len(mrp.REQUIRED)
    for cn in mrp.REQUIRED:
        assert f"\n# {cn}\n" in text, cn
    assert "\r" not in text, "LF only: the bundle is shipped and hashed into the manifest"


def test_every_certificate_is_a_self_signed_ca_that_openssl_accepts(tmp_path):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(cafile=str(PEM))           # a malformed entry raises here
    stats = ctx.cert_store_stats()
    assert stats["x509_ca"] == len(_certs(PEM.read_text(encoding="ascii"))), stats
    for pem in _certs(PEM.read_text(encoding="ascii")):
        info = mrp._decode(pem)
        assert dict(x[0] for x in info["subject"]) == dict(x[0] for x in info["issuer"]), "a root is self-signed"
        assert ssl.cert_time_to_seconds(info["notAfter"]) > 1_900_000_000, f"expires before 2030: {info['notAfter']}"


def test_fetch_loads_the_bundle_beside_the_windows_store():
    ctx = fetchmod.tls_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert fetchmod.ROOTS_PEM == PEM
    alone = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    alone.load_verify_locations(cafile=str(PEM))
    assert ctx.cert_store_stats()["x509_ca"] >= alone.cert_store_stats()["x509_ca"], "additive, never a replacement"


def test_the_bundle_ships_in_the_base_module():
    assert ("work/scripts/roots.pem", "scripts/roots.pem") in rel.MODULE_SPEC["base"]["files"]


def test_a_missing_bundle_falls_back_to_the_windows_store(monkeypatch, tmp_path):
    monkeypatch.setattr(fetchmod, "ROOTS_PEM", tmp_path / "absent.pem")
    assert fetchmod.tls_context().verify_mode == ssl.CERT_REQUIRED
    bad = tmp_path / "bad.pem"
    bad.write_text("not a certificate\n", encoding="ascii")
    monkeypatch.setattr(fetchmod, "ROOTS_PEM", bad)
    assert fetchmod.tls_context().verify_mode == ssl.CERT_REQUIRED, "a corrupt bundle must not break fetching"


@pytest.mark.skipif(not os.environ.get("LONGEVITY_NET_TESTS"), reason="live TLS check: set LONGEVITY_NET_TESTS=1")
@pytest.mark.parametrize("host", HOSTS)
def test_the_bundle_alone_verifies_the_download_hosts(host):
    """The Windows 7 case: NO Windows store, only the bundle. Fails when a host moves to a CA the bundle
    lacks -- then re-run make_roots_pem.py (and add the root to REQUIRED)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.check_hostname = True
    ctx.load_verify_locations(cafile=str(PEM))
    with socket.create_connection((host, 443), timeout=20) as s, ctx.wrap_socket(s, server_hostname=host) as t:
        assert t.getpeercert()
