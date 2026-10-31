"""The download layer.

Served from a real local HTTP server rather than mocked, so the Range/resume handling and the
"server ignores Range" path are exercised against actual HTTP semantics rather than against my
assumptions about them.
"""
from __future__ import annotations

import hashlib
import http.server
import sys
import threading
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import fetch  # noqa: E402

BODY = bytes(range(256)) * 400          # 102,400 bytes
DIGEST = hashlib.sha256(BODY).hexdigest()


class _Handler(http.server.BaseHTTPRequestHandler):
    """Serves BODY. Query flags: ?norange=1 ignores Range; ?short=1 truncates; ?long=1 pads."""

    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        path, _, query = self.path.partition("?")
        flags = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        body = BODY
        if flags.get("short"):
            body = BODY[:len(BODY) // 2]
        elif flags.get("long"):
            body = BODY + b"\x00" * (4 << 20)
        elif flags.get("wrong"):
            body = bytes(len(BODY))

        rng = self.headers.get("Range")
        self.server.ranges.append(rng)
        if flags.get("always416"):
            self.send_response(416)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if flags.get("chunked"):
            # A valid chunked body that ALSO carries a huge, meaningless Content-Length.
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Content-Length", "999999999999")
            self.end_headers()
            for i in range(0, len(body), 8192):
                piece = body[i:i + 8192]
                self.wfile.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
            return
        if rng and not flags.get("norange"):
            start = int(rng.split("=", 1)[1].split("-")[0])
            if start >= len(body):
                # What a real server answers for a range past the end (RFC 9110 s15.5.17).
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{len(body)}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if "rangestart" in flags:          # a 206 for a range nobody asked for
                start = int(flags["rangestart"])
            chunk = body[start:]
            self.send_response(206)
            # ?fullcl=1: a proxy that answers a range with the WHOLE file's length.
            self.send_header("Content-Length",
                             str(len(body) if flags.get("fullcl") else len(chunk)))
            self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
            self.end_headers()
            try:
                self.wfile.write(chunk)
            except ConnectionError:
                pass            # the client restarted without reading this body -- by design
            return
        self.send_response(200)
        self.send_header("Content-Length", flags.get("cl", str(len(body))))
        self.end_headers()
        try:
            self.wfile.write(body)
        except ConnectionError:
            pass                # the client refused the body after the headers -- by design


@pytest.fixture(scope="module")
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.ranges = []                         # the Range header of every request, in order
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    _SERVERS[url] = srv
    yield url
    srv.shutdown()


_SERVERS = {}


def _ranges(server_url) -> list:
    """The Range headers the server saw since the last call (and forget them)."""
    srv = _SERVERS[server_url]
    out, srv.ranges[:] = list(srv.ranges), []
    return out


@pytest.fixture
def allow_http(monkeypatch):
    """The module only permits https (and file:// on request). For tests, widen it to http on
    loopback -- the scheme guard itself is covered by its own tests below."""
    real = fetch.urllib.parse.urlparse

    def patched(u, *a, **k):
        r = real(u, *a, **k)
        if r.scheme == "http" and r.hostname == "127.0.0.1":
            return r._replace(scheme="https")
        return r
    monkeypatch.setattr(fetch.urllib.parse, "urlparse", patched)
    monkeypatch.setattr(fetch, "_opener", lambda allow_file=False:
                        fetch.urllib.request.build_opener())


# ---------------------------------------------------------------- happy paths

def test_downloads_and_verifies(server, allow_http, tmp_path):
    out = fetch.download(f"{server}/pack.zip", tmp_path / "pack.zip",
                         sha256=DIGEST, size=len(BODY))
    assert out.read_bytes() == BODY
    assert not list(tmp_path.glob("*.part")), "the .part file must be renamed, not left behind"


def test_an_already_correct_file_is_not_refetched(server, allow_http, tmp_path):
    dest = tmp_path / "pack.zip"
    dest.write_bytes(BODY)
    out = fetch.download(f"{server}/pack.zip", dest, sha256=DIGEST, size=len(BODY))
    assert out == dest
    assert out.read_bytes() == BODY


def test_a_wrong_existing_file_is_replaced(server, allow_http, tmp_path):
    dest = tmp_path / "pack.zip"
    dest.write_bytes(b"stale contents")
    fetch.download(f"{server}/pack.zip", dest, sha256=DIGEST, size=len(BODY))
    assert dest.read_bytes() == BODY


# ---------------------------------------------------------------- resume

def test_resumes_from_a_partial_file(server, allow_http, tmp_path):
    dest = tmp_path / "pack.zip"
    part = dest.with_suffix(".zip.part")
    part.write_bytes(BODY[:1000])              # pretend a previous run got this far
    fetch.download(f"{server}/pack.zip", dest, sha256=DIGEST, size=len(BODY))
    assert dest.read_bytes() == BODY, "resume produced the wrong bytes"


def test_a_server_that_ignores_range_restarts_instead_of_concatenating(server, allow_http, tmp_path):
    """Appending a full 200 response onto an existing partial is how you silently corrupt a
    download -- the length may even look plausible."""
    dest = tmp_path / "pack.zip"
    dest.with_suffix(".zip.part").write_bytes(BODY[:1000])
    fetch.download(f"{server}/pack.zip?norange=1", dest, sha256=DIGEST, size=len(BODY))
    assert dest.read_bytes() == BODY


def test_a_partial_longer_than_the_target_is_discarded(server, allow_http, tmp_path):
    dest = tmp_path / "pack.zip"
    dest.with_suffix(".zip.part").write_bytes(BODY + b"extra junk")
    fetch.download(f"{server}/pack.zip", dest, sha256=DIGEST, size=len(BODY))
    assert dest.read_bytes() == BODY


def test_a_complete_partial_is_verified_without_asking_the_server(allow_http, tmp_path):
    """Stopped between the last byte and the rename: the `.part` IS the file. A Range request for
    it can only be refused (416), so it is verified in place -- the URL here has nothing
    listening, so any request at all would fail the test."""
    dest = tmp_path / "pack.zip"
    dest.with_suffix(".zip.part").write_bytes(BODY)
    fetch.download("http://127.0.0.1:1/pack.zip", dest, sha256=DIGEST, size=len(BODY),
                   max_attempts=1)
    assert dest.read_bytes() == BODY


@pytest.mark.parametrize("partial", [BODY, BODY + b"stale tail"],
                         ids=["complete", "longer"])
def test_a_416_restarts_from_zero(server, allow_http, tmp_path, partial):
    """No size declared, so the partial cannot be judged locally and the server answers its
    Range with 416. That used to be a FetchError on every attempt AND every later run -- the
    stuck `.part` was never removed, so the download could never succeed again."""
    dest = tmp_path / "pack.zip"
    dest.with_suffix(".zip.part").write_bytes(partial)
    fetch.download(f"{server}/pack.zip", dest, sha256=DIGEST, max_attempts=1)
    assert dest.read_bytes() == BODY


def test_a_206_for_the_wrong_range_restarts_instead_of_splicing(server, allow_http, tmp_path):
    dest = tmp_path / "pack.zip"
    dest.with_suffix(".zip.part").write_bytes(BODY[:1000])
    _ranges(server)
    fetch.download(f"{server}/pack.zip?rangestart=0", dest, sha256=DIGEST, size=len(BODY),
                   max_attempts=1)
    assert dest.read_bytes() == BODY
    assert _ranges(server) == ["bytes=1000-", None], "the restart must ask for no Range"


def test_a_resume_answered_with_the_whole_files_length_restarts_not_sticks(server, allow_http,
                                                                           tmp_path):
    """Refusing it kept the partial, so every attempt and every later run sent the same Range
    and met the same refusal: the download could never finish on that host."""
    dest = tmp_path / "pack.zip"
    dest.with_suffix(".zip.part").write_bytes(BODY[:1000])
    _ranges(server)
    # max_bytes pins the cap just above the file, so 1000 + the whole length overflows it.
    fetch.download(f"{server}/pack.zip?fullcl=1", dest, size=len(BODY), sha256=DIGEST,
                   max_bytes=len(BODY) + 10, max_attempts=1)
    assert dest.read_bytes() == BODY
    assert _ranges(server) == ["bytes=1000-", None]


def test_a_server_that_answers_every_request_416_fails_cleanly_and_bounded(server, allow_http,
                                                                          tmp_path):
    dest = tmp_path / "pack.zip"
    dest.with_suffix(".zip.part").write_bytes(BODY[:1000])
    _ranges(server)
    with pytest.raises(fetch.FetchError):
        fetch.download(f"{server}/pack.zip?always416=1", dest, sha256=DIGEST, max_attempts=3)
    seen = _ranges(server)
    assert seen == ["bytes=1000-", None, None, None], seen
    assert not dest.with_suffix(".zip.part").exists(), "the stuck partial must be gone"


def test_a_chunked_body_with_a_stray_content_length_is_not_refused(server, allow_http, tmp_path):
    fetch.download(f"{server}/pack.zip?chunked=1", tmp_path / "p.zip", sha256=DIGEST,
                   size=len(BODY), max_attempts=1)
    assert (tmp_path / "p.zip").read_bytes() == BODY


def test_a_local_file_failure_is_a_fetch_error_not_a_crash(allow_http, tmp_path):
    """The bootstrap and the preflight catch only FetchError. A directory where the archive
    belongs (or a locked partial) made the self-update land in the crash handler."""
    dest = tmp_path / "pack.zip"
    dest.with_suffix(".zip.part").write_bytes(BODY)     # complete: verified, then renamed ...
    dest.mkdir()                                        # ... onto a directory
    (dest / "x").write_bytes(b"x")
    with pytest.raises(fetch.FetchError):
        fetch.download("http://127.0.0.1:1/pack.zip", dest, sha256=DIGEST, size=len(BODY),
                       max_attempts=1)


@pytest.mark.parametrize("kw", [{"size": len(BODY)}, {"max_bytes": 4096}],
                         ids=["over-manifest-size", "over-max_bytes"])
def test_an_oversized_content_length_is_refused_before_a_byte_is_written(server, allow_http,
                                                                         tmp_path, kw):
    cl = str(len(BODY) + (8 << 20)) if "size" in kw else str(len(BODY))
    dest = tmp_path / "p.zip"
    with pytest.raises(fetch.FetchError, match="abandoned before downloading"):
        fetch.download(f"{server}/pack.zip?cl={cl}", dest, sha256=DIGEST, max_attempts=1, **kw)
    assert not dest.with_suffix(".zip.part").exists(), "it streamed before refusing"


@pytest.mark.parametrize("raw, want", [
    ("102400", 102400), (" 7 ", 7), ("0", 0), (None, None), ("", None), ("-5", None),
    ("1e9", None), ("²", None), ("٣", None), ("9" * 21, None), ("12, 12", None),
])
def test_a_hostile_content_length_parses_to_none_not_a_crash(raw, want):
    assert fetch._content_length({"Content-Length": raw}) == want


@pytest.mark.parametrize("raw, want", [
    ("bytes 1000-102399/102400", 1000), ("BYTES 0-9/10", 0), ("bytes */102400", None),
    ("items 1-2/3", None), (None, None), ("bytes ١-2/3", None),
])
def test_content_range_start(raw, want):
    assert fetch._range_start({"Content-Range": raw}) == want


# ---------------------------------------------------------------- integrity

def test_a_wrong_body_is_rejected_and_the_partial_deleted(server, allow_http, tmp_path):
    dest = tmp_path / "pack.zip"
    with pytest.raises(fetch.FetchError, match="sha256 mismatch"):
        fetch.download(f"{server}/pack.zip?wrong=1", dest, sha256=DIGEST, size=len(BODY),
                       max_attempts=1)
    assert not dest.exists()
    assert not list(tmp_path.glob("*.part")), \
        "a wrong body must not be left as a partial for the next run to resume into"


def test_a_truncated_body_is_rejected(server, allow_http, tmp_path):
    with pytest.raises(fetch.FetchError):
        fetch.download(f"{server}/pack.zip?short=1", tmp_path / "p.zip",
                       sha256=DIGEST, size=len(BODY), max_attempts=1)


def test_an_oversized_body_is_abandoned_rather_than_filling_the_disk(server, allow_http, tmp_path):
    with pytest.raises(fetch.FetchError, match="exceeds the (declared|expected) size"):
        fetch.download(f"{server}/pack.zip?long=1", tmp_path / "p.zip",
                       sha256=DIGEST, size=len(BODY), max_attempts=1)


def test_sha256_beats_a_plausible_content_length(server, allow_http, tmp_path):
    """The digest comes from a signed manifest; the length comes from the server."""
    wrong_digest = "0" * 64
    with pytest.raises(fetch.FetchError, match="sha256 mismatch"):
        fetch.download(f"{server}/pack.zip", tmp_path / "p.zip",
                       sha256=wrong_digest, size=len(BODY), max_attempts=1)


# ---------------------------------------------------------------- scheme + mirror

@pytest.mark.parametrize("url", [
    "http://example.com/x.zip", "ftp://example.com/x.zip", "file:///C:/x.zip", "x.zip", "",
])
def test_non_https_urls_are_refused(url, tmp_path):
    with pytest.raises(fetch.FetchError, match="could not download"):
        fetch.download(url, tmp_path / "x.zip", max_attempts=1)


def test_a_file_url_works_only_when_explicitly_allowed(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(BODY)
    url = src.as_uri()
    with pytest.raises(fetch.FetchError):
        fetch.download(url, tmp_path / "a.bin", sha256=DIGEST, max_attempts=1)
    out = fetch.download(url, tmp_path / "b.bin", sha256=DIGEST, allow_file=True, max_attempts=1)
    assert out.read_bytes() == BODY


def test_the_mirror_is_used_when_the_primary_fails(server, allow_http, tmp_path):
    out = fetch.download(f"{server}/nope.zip?wrong=1", tmp_path / "p.zip",
                         sha256=DIGEST, size=len(BODY),
                         mirror=f"{server}/pack.zip", max_attempts=1)
    assert out.read_bytes() == BODY


def test_https_only_redirect_handler_rejects_a_downgrade():
    h = fetch._HttpsOnlyRedirect()
    with pytest.raises(fetch.FetchError, match="non-HTTPS"):
        h.redirect_request(None, None, 302, "Found", {}, "http://evil.example/x.zip")


# ---------------------------------------------------------------- staging helpers

def test_staging_lives_under_the_game_dir(tmp_path):
    """It must share the target volume, or a free-space check measures the wrong drive."""
    d = fetch.staging_dir(tmp_path)
    assert d.is_dir()
    assert d.parent.parent == tmp_path
    (d / "junk").write_bytes(b"x")
    fetch.clear_staging(tmp_path)
    assert not d.exists()


def test_free_space_walks_up_to_an_existing_parent(tmp_path):
    assert fetch.free_space(tmp_path / "does" / "not" / "exist" / "yet") > 0
