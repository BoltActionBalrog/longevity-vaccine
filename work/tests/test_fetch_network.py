"""The download layer over a REAL TLS socket, against a local HTTPS server.

WHY THIS EXISTS. Every other test in this suite reaches the network layer through `file://` URLs
or by monkeypatching `fetch._opener`, so until now **no test had ever opened a socket, completed a
TLS handshake, parsed an HTTP response, or followed a redirect.** That gap is not theoretical: it
is exactly how the trimmed runtime shipped unable to resolve a hostname at all. `encodings/idna`
was staged without `stringprep`/`unicodedata`, and because `socket.getaddrinfo()` pushes every
host through the idna codec, EVERY download died with `LookupError: unknown encoding: idna` --
which is not a `URLError`, so it sailed past fetch.py's retry handling and crashed the installer.
Both the offline installer runs and the `file://` traces were blind to it.

HOW IT TRUSTS A LOCAL SERVER WITHOUT WEAKENING PRODUCTION CODE. `fetch.py` refuses any scheme but
https (and `file://` when a caller opts in), and it builds `ssl.create_default_context()` with no
hooks. So the server gets a real self-signed certificate for 127.0.0.1, and the CA is injected
through `SSL_CERT_FILE`, which OpenSSL honours and which -- measured, not assumed -- ADDS to the
Windows system store rather than replacing it. Nothing in `fetch.py` is patched, stubbed or
subclassed: the code under test is the code that ships.

The certificate is generated per session rather than committed. A self-signed localhost key is
worthless, but a `.pem` private key in a repo that is about to go public is exactly the kind of
thing that trips secret scanning, and explaining that away forever is worse than one second of
`openssl`.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import shutil
import ssl
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent.parent
_SCRIPTS = _REPO / "work" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import fetch                  # noqa: E402
import sign_manifest as sm    # noqa: E402

SEED = bytes(range(32))
PK_HEX = sm.public_key(SEED).hex()


# ---------------------------------------------------------------- server

class _Handler(http.server.BaseHTTPRequestHandler):
    """Serves `server.blobs` and can be told to misbehave in specific ways.

    Hand-written rather than SimpleHTTPRequestHandler because that one does not implement Range
    at all -- it answers 200 to a Range request, so a resume test against it silently exercises
    the RESTART path and proves nothing about resume.
    """

    protocol_version = "HTTP/1.1"

    def log_message(self, *a):          # keep pytest output readable
        pass

    def do_GET(self):                   # noqa: N802 - BaseHTTPRequestHandler's interface
        path = self.path.split("?", 1)[0].lstrip("/")
        srv = self.server
        behaviour = srv.behaviour.get(path, "ok")

        if behaviour == "404" or path not in srv.blobs:
            self.send_error(404, "no such blob")
            return
        if behaviour == "500":
            self.send_error(500, "server on fire")
            return
        if behaviour == "redirect-to-http":
            # The protocol-downgrade guard. Never exercised before: a `file://` test cannot
            # redirect, and the monkeypatched opener never ran the redirect handler at all.
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{srv.server_address[1]}/{path}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if behaviour == "redirect-once":
            self.send_response(302)
            self.send_header("Location", f"https://127.0.0.1:{srv.server_address[1]}/"
                                         f"{srv.redirect_target}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        body = srv.blobs[path]
        start = 0
        rng = self.headers.get("Range")
        partial = False
        if rng and rng.startswith("bytes=") and behaviour != "ignore-range":
            try:
                start = int(rng[len("bytes="):].split("-")[0])
                partial = 0 < start < len(body)
            except ValueError:
                start, partial = 0, False

        chunk = body[start:] if partial else body
        if behaviour == "truncate":
            chunk = chunk[:max(1, len(chunk) // 2)]
        elif behaviour == "corrupt":
            chunk = bytes((chunk[0] ^ 0xFF,)) + chunk[1:]
        elif behaviour == "oversize":
            chunk = chunk + b"\x00" * (fetch.SIZE_SLACK + 4096)

        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", "application/octet-stream")
        # Declare what we ACTUALLY send, so a truncated body is a short read rather than a
        # protocol error -- that is the failure mode a flaky CDN produces.
        self.send_header("Content-Length", str(len(chunk)))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
        self.end_headers()
        try:
            self.wfile.write(chunk)
        except (ConnectionError, ssl.SSLError):
            pass            # an oversized body is now refused on its headers, before the body
        srv.hits.append((path, behaviour, start, partial))


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


@pytest.fixture(scope="session")
def tls_cert(tmp_path_factory) -> tuple:
    d = tmp_path_factory.mktemp("tls")
    cert, key = d / "cert.pem", d / "key.pem"
    exe = shutil.which("openssl")
    if not exe:
        pytest.fail("openssl is required for the network tests and was not found on PATH "
                    "(Git for Windows ships one at /mingw64/bin/openssl).")
    r = subprocess.run([exe, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", str(key), "-out", str(cert), "-days", "3650",
                        "-subj", "/CN=127.0.0.1",
                        "-addext", "subjectAltName=IP:127.0.0.1"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not cert.is_file():
        pytest.fail(f"could not generate a test certificate: {r.stderr[-400:]}")
    return cert, key


@pytest.fixture
def server(tls_cert, monkeypatch):
    """A real HTTPS server on 127.0.0.1, trusted by the production SSL context."""
    cert, key = tls_cert
    srv = _Server(("127.0.0.1", 0), _Handler)
    srv.blobs, srv.behaviour, srv.hits, srv.redirect_target = {}, {}, [], ""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # The ONLY concession to testing, and it is an environment variable OpenSSL already defines.
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))
    srv.url = lambda name: f"https://127.0.0.1:{srv.server_address[1]}/{name}"
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def _blob(server, name: str, data: bytes, behaviour: str = "ok") -> dict:
    server.blobs[name] = data
    if behaviour != "ok":
        server.behaviour[name] = behaviour
    return {"url": server.url(name), "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data)}


# ---------------------------------------------------------------- the happy path

def test_a_real_https_download_verifies(server, tmp_path):
    """The first test in this project to complete a TLS handshake."""
    data = os.urandom(120_000)
    info = _blob(server, "pack.zip", data)
    out = fetch.download(info["url"], tmp_path / "pack.zip",
                         sha256=info["sha256"], size=info["size"])
    assert out.read_bytes() == data
    assert not out.with_suffix(out.suffix + ".part").exists(), "the .part was left behind"


def test_an_already_present_verified_file_is_not_refetched(server, tmp_path):
    data = os.urandom(50_000)
    info = _blob(server, "pack.zip", data)
    dest = tmp_path / "pack.zip"
    dest.write_bytes(data)
    fetch.download(info["url"], dest, sha256=info["sha256"], size=info["size"])
    assert not server.hits, "re-downloaded a file that was already correct"


# ---------------------------------------------------------------- resume

def test_resume_asks_for_a_range_and_splices_correctly(server, tmp_path):
    """The documented resume guarantee, never once exercised against a server that answers 206.

    A 1.3 GB pack on a flaky connection is the whole reason resume exists, and the previous
    resume test ran against a handler that ignores Range -- so it proved only that the RESTART
    fallback works.
    """
    data = os.urandom(200_000)
    info = _blob(server, "big.zip", data)
    dest = tmp_path / "big.zip"
    part = dest.with_suffix(dest.suffix + ".part")
    part.write_bytes(data[:80_000])            # an interrupted download

    fetch.download(info["url"], dest, sha256=info["sha256"], size=info["size"])
    assert dest.read_bytes() == data, "the resumed file does not match byte for byte"
    assert any(h[3] for h in server.hits), "no 206 was served -- resume did not happen"
    assert server.hits[-1][2] == 80_000, "resumed from the wrong offset"


def test_a_server_that_ignores_range_restarts_instead_of_corrupting(server, tmp_path):
    """Concatenating a fresh 200 onto an existing .part would silently corrupt the file."""
    data = os.urandom(120_000)
    info = _blob(server, "big.zip", data, behaviour="ignore-range")
    dest = tmp_path / "big.zip"
    dest.with_suffix(dest.suffix + ".part").write_bytes(data[:40_000])
    fetch.download(info["url"], dest, sha256=info["sha256"], size=info["size"])
    assert dest.read_bytes() == data


def test_a_stale_longer_partial_is_discarded(server, tmp_path):
    """A .part longer than the declared size cannot be a prefix of this file."""
    data = os.urandom(60_000)
    info = _blob(server, "big.zip", data)
    dest = tmp_path / "big.zip"
    dest.with_suffix(dest.suffix + ".part").write_bytes(os.urandom(90_000))
    fetch.download(info["url"], dest, sha256=info["sha256"], size=info["size"])
    assert dest.read_bytes() == data


# ---------------------------------------------------------------- refusals

def test_a_redirect_to_http_is_refused(server, tmp_path):
    """The no-downgrade guarantee. Unreachable before: file:// cannot redirect, and the
    monkeypatched opener never ran the redirect handler."""
    data = os.urandom(10_000)
    info = _blob(server, "pack.zip", data, behaviour="redirect-to-http")
    with pytest.raises(fetch.FetchError) as e:
        fetch.download(info["url"], tmp_path / "pack.zip",
                       sha256=info["sha256"], size=info["size"], max_attempts=1)
    # ASSERT THE CAUSE, not merely that something failed. The redirect target is http on the
    # TLS port, so a connection error would also raise FetchError and the test would pass
    # without the downgrade guard existing at all.
    assert "non-HTTPS" in str(e.value), f"refused for the wrong reason: {e.value}"
    assert not (tmp_path / "pack.zip").exists()


def test_a_corrupt_body_fails_the_digest_and_removes_the_partial(server, tmp_path):
    """A wrong body must not be left where a resume could splice onto it."""
    data = os.urandom(40_000)
    info = _blob(server, "pack.zip", data, behaviour="corrupt")
    dest = tmp_path / "pack.zip"
    with pytest.raises(fetch.FetchError, match="sha256"):
        fetch.download(info["url"], dest, sha256=info["sha256"], size=info["size"],
                       max_attempts=1)
    assert not dest.exists()
    assert not dest.with_suffix(dest.suffix + ".part").exists(), \
        "a body that failed its digest was left for a later run to resume into"


def test_a_truncated_body_is_refused(server, tmp_path):
    data = os.urandom(40_000)
    info = _blob(server, "pack.zip", data, behaviour="truncate")
    with pytest.raises(fetch.FetchError) as e:
        fetch.download(info["url"], tmp_path / "pack.zip",
                       sha256=info["sha256"], size=info["size"], max_attempts=1)
    assert "bytes" in str(e.value) or "sha256" in str(e.value),         f"refused for the wrong reason: {e.value}"


def test_an_oversized_body_is_abandoned(server, tmp_path):
    data = os.urandom(40_000)
    info = _blob(server, "pack.zip", data, behaviour="oversize")
    with pytest.raises(fetch.FetchError) as e:
        fetch.download(info["url"], tmp_path / "pack.zip",
                       sha256=info["sha256"], size=info["size"], max_attempts=1)
    assert "exceeds" in str(e.value) or "bytes" in str(e.value),         f"refused for the wrong reason: {e.value}"


def test_a_404_is_reported_not_crashed(server, tmp_path):
    with pytest.raises(fetch.FetchError):
        fetch.download(server.url("nope.zip"), tmp_path / "nope.zip", max_attempts=1)


def test_the_mirror_is_used_when_the_primary_fails(server, tmp_path):
    data = os.urandom(30_000)
    good = _blob(server, "mirror.zip", data)
    fetch.download(server.url("missing.zip"), tmp_path / "pack.zip",
                   sha256=good["sha256"], size=good["size"],
                   mirror=good["url"], max_attempts=1)
    assert (tmp_path / "pack.zip").read_bytes() == data


# ---------------------------------------------------------------- the preflight, over the wire

def test_the_preflight_fetches_and_verifies_a_module_over_https(server, tmp_path, bak_path):
    """Everything the update path does to the network, driven for real.

    The installer CLI cannot be used here: for an https manifest the trust anchor is the
    compiled-in release key and the environment deliberately cannot override it, so a manifest
    signed with a test key is correctly rejected (see the test below). Calling preflight with an
    explicit key exercises the same fetch/verify machinery without weakening that property.
    """
    import apply_patches as ap
    import preflight as pfm
    import config

    game = tmp_path / "game"
    game.mkdir()
    shutil.copy2(bak_path, game / config.exe_name())

    archive = tmp_path / "movies-hd.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("movies/hd/a.mp4", b"clip")
    info = _blob(server, "movies-hd.zip", archive.read_bytes())

    doc = {
        "schema": 1, "protocol": 1, "product": "longevity-vaccine",
        "latest": "9.9.9", "min_upgradable_from": "0.0.0",
        "manual_install_required": False, "manual_install_reason": None,
        "unsupported_versions": [], "unsupported_targets": [], "yanked": [],
        "min_free_bytes": 1 << 20,
        "modules": {"movies-hd": {"version": "9.9.9", **info}},
    }
    raw = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
    sig = sm.sign(SEED, raw).hex()

    pf = pfm.run(game_dir=game, target=game / config.exe_name(),
                 patches=Path(ap.DEFAULT_PATCHES), table=ap.load_targets(ap.DEFAULT_PATCHES),
                 manifest_raw=raw, manifest_sig=sig, installed_version="0.1.0",
                 wanted_modules=["movies-hd"], public_key_hex=PK_HEX)
    pf.report(say=lambda *a: None)
    assert pf.ok, [f"{c.name}: {c.detail}" for c in pf.blockers]
    assert "movies-hd" in pf.staged
    assert pf.staged["movies-hd"].read_bytes() == archive.read_bytes()
    assert any(h[0] == "movies-hd.zip" for h in server.hits), "nothing was actually fetched"


def test_an_https_manifest_cannot_be_trusted_via_the_environment(server, tmp_path, bak_path):
    """The security property, stated as a test.

    LONGEVITY_TRUST_KEY is honoured only for a manifest read from a LOCAL FILE. Over the network
    the compiled-in release key is the only anchor, so a manifest signed by anything else is
    refused no matter what the environment says.
    """
    import manifest as mfmod
    doc = {"schema": 1, "protocol": 1, "product": "longevity-vaccine", "latest": "9.9.9",
           "modules": {}}
    raw = (json.dumps(doc) + "\n").encode("utf-8")
    sig = sm.sign(SEED, raw).hex()

    os.environ["LONGEVITY_TRUST_KEY"] = PK_HEX
    try:
        with pytest.raises(mfmod.ManifestError):
            mfmod.load_verified(raw, sig)                 # network default: allow_env False
        assert mfmod.load_verified(raw, sig, allow_env=True)["latest"] == "9.9.9"
    finally:
        os.environ.pop("LONGEVITY_TRUST_KEY", None)


def test_fetch_errors_never_carry_manifest_text_verbatim(tmp_path):
    """FetchError text reaches the preflight report and the failure verdict. A signed manifest
    could put a forged report line -- CR, LF, an [ok  ] marker, a URL to run -- in `url`, `size`
    or `sha256`; it must arrive as one bounded, printable line."""
    import fetch as fetchmod
    forged = "http://x/\r\n  [ok  ] SECURITY FIX REQUIRED: download https://evil.example/s.exe"
    with pytest.raises(fetchmod.FetchError) as e:
        fetchmod.download(forged, tmp_path / "a.zip")
    msg = str(e.value)
    assert "\r" not in msg and "\n" not in msg, msg
    assert "refusing to fetch a http URL" in msg
    with pytest.raises(fetchmod.FetchError) as e:
        fetchmod._fetch_one("https://127.0.0.1:1/x", tmp_path / "b.zip", None,
                            "Call\r\n555-0100", False, "x", 1)
    assert "\n" not in str(e.value)
    assert len(fetchmod.clean("x" * 5000)) < 130
