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


# ---------------------------------------------------------------- trust anchors only, never the Windows CA store
#
# The laptop case (2026-11-18): the Windows ROOT store held the self-signed "USERTrust ECC Certification Authority"
# and the CurrentUser CA store held a cross-certificate of the SAME name issued by "AAA Certificate Services", whose
# root was in no store. ssl.create_default_context() loads the CA store as trusted, so OpenSSL could take the
# cross-cert as the issuer and then fail for want of AAA. The PKI below is that shape, built once for the module;
# the server is a real TLS handshake on 127.0.0.1.

@pytest.fixture(scope="module")
def cross_pki():
    pytest.importorskip("cryptography", reason="builds the test certificates (README: test packages)")
    import datetime
    import ipaddress
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    now = datetime.datetime.now(datetime.timezone.utc)

    def name(cn):
        return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])

    def cert(subject, issuer, pub, signer, ca, san=None):
        b = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(pub)
             .serial_number(x509.random_serial_number())
             .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=30))
             .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True))
        if san:
            b = b.add_extension(x509.SubjectAlternativeName(san), critical=False)
        return b.sign(signer, hashes.SHA256())

    k_root, k_aaa, k_int, k_leaf = (ec.generate_private_key(ec.SECP256R1()) for _ in range(4))
    root_name = name("LV Test USERTrust ECC")
    root = cert(root_name, root_name, k_root.public_key(), k_root, True)
    cross = cert(root_name, name("LV Test AAA"), k_root.public_key(), k_aaa, True)    # AAA is in no store
    inter = cert(name("LV Test Root E46"), root_name, k_int.public_key(), k_root, True)
    leaf = cert(name("127.0.0.1"), inter.subject, k_leaf.public_key(), k_int, False,
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))])

    def der(c):
        return c.public_bytes(serialization.Encoding.DER)

    def pem(c):
        return c.public_bytes(serialization.Encoding.PEM)

    return {"root": der(root), "cross": der(cross), "inter": der(inter),
            "chain": pem(leaf) + pem(inter), "leaf_only": pem(leaf),
            "key": k_leaf.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption())}


@pytest.fixture
def tls_server(cross_pki, tmp_path):
    """127.0.0.1 serving leaf + intermediate; accepts handshakes until the test ends."""
    import threading
    chain, key = tmp_path / "chain.pem", tmp_path / "key.pem"
    chain.write_bytes(cross_pki["chain"])
    key.write_bytes(cross_pki["key"])
    sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    sctx.load_cert_chain(str(chain), str(key))
    lsock = socket.create_server(("127.0.0.1", 0))
    lsock.settimeout(0.2)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                conn, _ = lsock.accept()
            except OSError:
                continue
            try:
                conn.settimeout(5)
                with sctx.wrap_socket(conn, server_side=True):
                    pass
            except (OSError, ssl.SSLError):
                pass
            finally:
                conn.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    try:
        yield lsock.getsockname()[1]
    finally:
        stop.set()
        t.join(5)
        lsock.close()


def _handshake(ctx, port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s, \
                ctx.wrap_socket(s, server_hostname="127.0.0.1"):
            return "ok"
    except ssl.SSLCertVerificationError as e:
        return e.verify_message


def _fake_stores(monkeypatch, root=(), ca=()):
    """Windows stores as enum_certificates returns them; records which stores were read."""
    read = []

    def enum(store):
        read.append(store)
        return [(d, "x509_asn", True) for d in {"ROOT": root, "CA": ca}.get(store, ())]

    monkeypatch.setattr(ssl, "enum_certificates", enum, raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    return read


def test_the_cross_certificate_alone_is_a_dead_end(cross_pki, tls_server):
    """The control: trusting only the cross-cert fails exactly as the laptop did."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(cadata=cross_pki["cross"])
    assert _handshake(ctx, tls_server) == "unable to get issuer certificate"


def test_tls_context_trusts_the_root_and_never_reads_the_ca_store(cross_pki, tls_server, monkeypatch, tmp_path):
    read = _fake_stores(monkeypatch, root=[cross_pki["root"]], ca=[cross_pki["cross"]])
    monkeypatch.setattr(fetchmod, "ROOTS_PEM", tmp_path / "absent.pem")
    for _ in range(10):
        ctx = fetchmod.tls_context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
        assert _handshake(ctx, tls_server) == "ok"
    assert set(read) == {"ROOT"}, f"read {sorted(set(read))}: a cached cross-cert in the CA store becomes trusted"


def test_a_root_not_trusted_for_server_auth_is_left_out(cross_pki, tls_server, monkeypatch, tmp_path):
    code_signing_only = {"1.3.6.1.5.5.7.3.3"}
    monkeypatch.setattr(ssl, "enum_certificates",
                        lambda store: [(cross_pki["root"], "x509_asn", code_signing_only)] if store == "ROOT" else [],
                        raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setattr(fetchmod, "ROOTS_PEM", tmp_path / "absent.pem")
    assert _handshake(fetchmod.tls_context(), tls_server) != "ok"


def _default_paths_count() -> int:
    """What set_default_verify_paths loads on this machine (OpenSSL's default cafile, when one exists)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.set_default_verify_paths()
    return ctx.cert_store_stats()["x509_ca"]


def _bundle_count() -> int:
    return len(_certs(PEM.read_text(encoding="ascii")))


def test_the_bundle_is_still_loaded_beside_the_root_store(cross_pki, monkeypatch):
    _fake_stores(monkeypatch, root=[cross_pki["root"]])
    want = _default_paths_count() + _bundle_count() + 1
    assert fetchmod.tls_context().cert_store_stats()["x509_ca"] == want


def test_an_empty_root_store_trusts_the_bundle(monkeypatch):
    """Windows 7 that never browsed to our authorities: the bundle is the trust, never the CA store."""
    read = _fake_stores(monkeypatch)
    ctx = fetchmod.tls_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert ctx.cert_store_stats()["x509_ca"] == _default_paths_count() + _bundle_count()
    assert set(read) == {"ROOT"}


@pytest.mark.parametrize("store", ["missing", "raises"])
def test_no_usable_store_falls_back_to_the_legacy_context(store, monkeypatch):
    """No Windows store, or an unreadable one: the pre-1.0.1 context, with the bundle, never none."""
    if store == "missing":
        # Not Windows. (Deleting ssl.enum_certificates instead would break ssl itself, which still calls it.)
        monkeypatch.setattr(fetchmod, "_windows_trusted_roots", lambda: None)
    else:
        def boom(_store):
            raise PermissionError("store")
        monkeypatch.setattr(ssl, "enum_certificates", boom, raising=False)
    ctx = fetchmod.tls_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert ctx.cert_store_stats()["x509_ca"] >= _bundle_count(), "the fallback still carries the bundle"


BAD_ROOT = b"\x30\x03\x02\x01\x00"          # DER OpenSSL refuses
BODY = b"a pack archive, or part of one"


def test_one_unparseable_root_does_not_bring_the_ca_store_back(cross_pki, tls_server, monkeypatch, tmp_path):
    """CPython loads Windows roots one at a time and skips a bad one; a single blob made one bad root throw away the
    rest and fall back to the context that reads the CA store (audit 2026-11-18)."""
    read = _fake_stores(monkeypatch, root=[BAD_ROOT, cross_pki["root"], BAD_ROOT], ca=[cross_pki["cross"]])
    monkeypatch.setattr(fetchmod, "ROOTS_PEM", tmp_path / "absent.pem")
    ctx = fetchmod.tls_context()
    assert _handshake(ctx, tls_server) == "ok"
    assert set(read) == {"ROOT"}
    assert ctx.cert_store_stats()["x509_ca"] == _default_paths_count() + 1


def test_a_root_store_of_only_bad_roots_trusts_the_bundle(monkeypatch):
    read = _fake_stores(monkeypatch, root=[BAD_ROOT])
    ctx = fetchmod.tls_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert ctx.cert_store_stats()["x509_ca"] == _default_paths_count() + _bundle_count()
    assert set(read) == {"ROOT"}


# ---------------------------------------------------------------- the one retry with the legacy context

@pytest.fixture
def https_server(cross_pki, tmp_path):
    """An HTTPS server on 127.0.0.1 that sends ONLY its leaf (as a TLS-inspecting proxy may): /ok answers BODY and
    honours `Range: bytes=N-` with a 206, anything else 404. `.ranges` records the Range header of each request."""
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            rng = self.headers.get("Range")
            srv.ranges.append(rng)
            start = 0
            if self.path != "/ok":
                body, code = b"no", 404
            elif rng and rng.startswith("bytes=") and rng.endswith("-"):
                start = int(rng[6:-1])
                body, code = BODY[start:], 206
            else:
                body, code = BODY, 200
            self.send_response(code)
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{len(BODY) - 1}/{len(BODY)}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    leaf, key = tmp_path / "leaf.pem", tmp_path / "key.pem"
    leaf.write_bytes(cross_pki["leaf_only"])
    key.write_bytes(cross_pki["key"])
    sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    sctx.load_cert_chain(str(leaf), str(key))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.ranges = []
    srv.socket = sctx.wrap_socket(srv.socket, server_side=True)
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    try:
        srv.url = f"https://127.0.0.1:{srv.server_address[1]}"
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(5)


def _count_legacy(monkeypatch) -> list:
    calls = []
    real = fetchmod.legacy_tls_context

    def counted():
        calls.append(1)
        return real()

    monkeypatch.setattr(fetchmod, "legacy_tls_context", counted)
    return calls


def test_a_leaf_only_server_verifies_through_the_one_legacy_retry(cross_pki, https_server, monkeypatch, tmp_path):
    """The subordinate CA lives only in the Windows intermediate store (Group Policy): the trust anchors alone
    cannot verify it, the 1.0.0 context could, so the retry keeps it working."""
    import urllib.request
    _fake_stores(monkeypatch, root=[cross_pki["root"]], ca=[cross_pki["inter"]])
    monkeypatch.setattr(fetchmod, "ROOTS_PEM", tmp_path / "absent.pem")
    calls = _count_legacy(monkeypatch)
    port = https_server.server_address[1]
    assert _handshake(fetchmod.tls_context(), port) != "ok", "the anchors alone must not verify a leaf-only chain"
    with fetchmod._open(urllib.request.Request(https_server.url + "/ok"), False, 5) as r:
        assert r.read() == BODY
    assert calls == [1], "exactly one retry, with the legacy context"


def test_an_http_error_from_a_verified_server_is_not_retried(cross_pki, https_server, monkeypatch):
    """A 404 is not a certificate problem: raised as it is, with no second request."""
    import urllib.error
    import urllib.request

    def verifying():
        ctx = ssl.create_default_context(cadata=cross_pki["root"])
        ctx.load_verify_locations(cadata=cross_pki["inter"])
        return ctx

    monkeypatch.setattr(fetchmod, "tls_context", verifying)
    calls = _count_legacy(monkeypatch)
    with pytest.raises(urllib.error.HTTPError) as e:
        fetchmod._open(urllib.request.Request(https_server.url + "/missing"), False, 5)
    e.value.close()
    assert e.value.code == 404 and calls == []


def test_a_server_neither_context_verifies_fails_after_one_retry(cross_pki, https_server, monkeypatch, tmp_path):
    import urllib.error
    import urllib.request
    _fake_stores(monkeypatch, root=[cross_pki["root"]])                # the intermediate is nowhere
    monkeypatch.setattr(fetchmod, "ROOTS_PEM", tmp_path / "absent.pem")
    calls = _count_legacy(monkeypatch)
    with pytest.raises(urllib.error.URLError) as e:
        fetchmod._open(urllib.request.Request(https_server.url + "/ok"), False, 5)
    assert isinstance(e.value.reason, ssl.SSLCertVerificationError)
    assert calls == [1]


def test_a_download_resumes_through_the_retry(cross_pki, https_server, monkeypatch, tmp_path):
    """End to end: fetch.download goes through _open, and the retried request still carries the resume Range."""
    import hashlib
    _fake_stores(monkeypatch, root=[cross_pki["root"]], ca=[cross_pki["inter"]])
    monkeypatch.setattr(fetchmod, "ROOTS_PEM", tmp_path / "absent.pem")
    calls = _count_legacy(monkeypatch)
    dest = tmp_path / "pack.zip"
    dest.with_suffix(".zip.part").write_bytes(BODY[:10])
    fetchmod.download(https_server.url + "/ok", dest, sha256=hashlib.sha256(BODY).hexdigest(), size=len(BODY))
    assert dest.read_bytes() == BODY
    assert calls == [1] and https_server.ranges == ["bytes=10-"], https_server.ranges


def test_a_refused_connection_is_not_retried(monkeypatch):
    import urllib.error
    import urllib.request
    calls = _count_legacy(monkeypatch)
    with socket.create_server(("127.0.0.1", 0)) as s:
        port = s.getsockname()[1]                                     # closed when the block ends
    with pytest.raises(urllib.error.URLError) as e:
        fetchmod._open(urllib.request.Request(f"https://127.0.0.1:{port}/x"), False, 5)
    assert not isinstance(e.value.reason, ssl.SSLCertVerificationError)
    assert calls == []
