"""Download module archives into a staging directory. Stdlib only.

No `requests`, no `urllib3`: `urllib.request` + `ssl` are in the CPython embeddable distribution
the installer ships with (verified: OpenSSL 3.0.16), and the shipped dependency set has to stay at
pyyaml + pefile.

Guarantees this module provides, each of which exists because of a specific failure:

  * **Nothing lands in the game directory.** Everything downloads into a staging dir and is only
    moved by the caller after the preflight passes.
  * **Resume.** A 1.3 GB pack on a flaky connection must not restart from zero. Uses a Range
    request against the existing `.part` file, and copes with a server that ignores Range and
    replies 200 instead of 206 by starting over rather than concatenating garbage -- and the same
    for a 206 of the wrong range and a 416 (a partial the server cannot continue), which otherwise
    failed the same way on every retry and every later run.
  * **sha256 is the authority, not Content-Length.** The expected digest comes from a signed
    manifest, so a truncated, padded or substituted body is caught even if the length looks right.
  * **A size cap.** A response far larger than the manifest declares is abandoned rather than
    allowed to fill the disk -- before the first byte when its Content-Length already says so.
  * **No protocol downgrade.** Redirects to anything but https are refused. The sha256 already
    makes tampering moot, but there is no reason to follow a downgrade.
  * **Atomic publish.** Bytes accumulate in `<name>.part` and are renamed only after the digest
    matches, so a half-written file can never be mistaken for a complete one.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "LongevityVaccine-Installer"
CONNECT_TIMEOUT = 30
CHUNK = 1 << 18            # 256 KiB
#: How much larger than declared a body may be before we give up. Some servers pad slightly;
#: a wildly larger body is either the wrong file or an attempt to fill the disk.
SIZE_SLACK = 1 << 20
#: Absolute ceiling when neither the manifest nor the server declares a length. Larger than any
#: module we ship (the HD pack is ~1.3 GB) and small enough to stop a runaway body.
MAX_UNDECLARED = 4 << 30


class FetchError(Exception):
    """A download could not be completed or could not be trusted."""


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme.lower() != "https":
            raise FetchError(f"refusing a redirect to a non-HTTPS URL: {clean(newurl)}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener(allow_file: bool = False):
    handlers = [_HttpsOnlyRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())]
    if allow_file:
        handlers.append(urllib.request.FileHandler())
    return urllib.request.build_opener(*handlers)


def sha256_file(p: Path, _buf: int = CHUNK) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(_buf), b""):
            h.update(chunk)
    return h.hexdigest()


def _progress(done: int, total: int, started: float, label: str) -> None:
    try:
        if sys.stdout is None or not sys.stdout.isatty():
            return
    except (OSError, ValueError, AttributeError):
        return
    elapsed = max(time.monotonic() - started, 1e-6)
    rate = done / elapsed / (1 << 20)
    if total:
        pct = 100.0 * done / total
        bar_w = 28
        filled = int(bar_w * done / total)
        bar = "#" * filled + "-" * (bar_w - filled)
        line = f"\r  {label[:22]:<22} [{bar}] {pct:5.1f}%  {rate:5.1f} MB/s"
    else:
        line = f"\r  {label[:22]:<22} {done / (1 << 20):8.1f} MB  {rate:5.1f} MB/s"
    try:
        sys.stdout.write(line)
        sys.stdout.flush()
    except (OSError, ValueError):
        pass


def human_size(n) -> str:
    """1.3 GB / 512 MB / <1 MB, decimal units. One function for every size a player reads, so
    the notice's "1.3 GB download" and the preflight's free-space line agree."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    if n >= 10 ** 9:
        return f"{n / 10 ** 9:.1f} GB"
    if n >= 10 ** 6:
        return f"{n / 10 ** 6:.0f} MB"
    return "<1 MB"


def clean(value, limit: int = 120) -> str:
    """A manifest-derived value for a MESSAGE: printable ASCII only, bounded.

    FetchError text reaches the preflight report and the failure verdict. A signed manifest could
    put "\\r\\n  [ok  ] download https://evil.example/setup.exe" in a `url` or a `size` and have
    it printed as a line of our own report -- the same forgery manifest._safe exists to stop.
    """
    s = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(value))
    return s[:limit] + ("..." if len(s) > limit else "")


def download(url: str, dest: Path, *, sha256: str = None, size: int = None,
             mirror: str = None, allow_file: bool = False, label: str = None,
             timeout: int = CONNECT_TIMEOUT, max_attempts: int = 3,
             max_bytes: int = None, deadline: float = None) -> Path:
    """Fetch `url` to `dest`, resuming and verifying. Raises FetchError on any failure.

    `dest` is the final path; bytes accumulate in `dest.part` first.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    label = label or dest.name

    # Already present and correct? Then this is a no-op -- re-downloading 1.3 GB because a later
    # module failed would be its own defect.
    if dest.is_file() and sha256:
        if sha256_file(dest) == sha256.lower():
            print(f"  {label}: already present and verified")
            return dest
        dest.unlink()

    urls = [u for u in (url, mirror) if u]
    last_error = None
    for candidate in urls:
        scheme = urllib.parse.urlparse(candidate).scheme.lower()
        if scheme not in ("https", "file") or (scheme == "file" and not allow_file):
            last_error = FetchError(f"refusing to fetch a {clean(scheme) or 'schemeless'} URL: "
                                    f"{clean(candidate)}")
            continue
        for attempt in range(1, max_attempts + 1):
            try:
                _fetch_one(candidate, dest, sha256, size, allow_file, label, timeout,
                           max_bytes=max_bytes, deadline=deadline)
                return dest
            except FetchError as e:
                last_error = e
                if attempt < max_attempts:
                    # One plain line per retry. The technical reason (URLError / errno soup) is
                    # kept for the final error, not shown to the player three times over.
                    print(f"  Could not reach the update server, trying again ({attempt + 1} of {max_attempts})...")
                    time.sleep(min(2 ** attempt, 8))
        if mirror and candidate != urls[-1]:
            print("  Trying the backup server...")
    raise FetchError(f"could not download {label}: {last_error}")


def _fetch_one(url: str, dest: Path, sha256: str, size: int, allow_file: bool,
               label: str, timeout: int, max_bytes: int = None,
               deadline: float = None) -> None:
    """`max_bytes`: an absolute ceiling regardless of what the manifest or the server says (a
    manifest is a few KB; a server that sends more is not sending a manifest). `deadline`: a
    monotonic time after which the transfer is abandoned -- a socket timeout only bounds each
    read, so a server trickling one byte per 29 s held the game's hidden check open forever.

    Every failure leaves as a FetchError, the local file work around the transfer included: the
    bootstrap and the preflight catch nothing else, so a locked `.part` or a directory where the
    archive belongs sent the self-update to the crash handler instead of "could not be
    downloaded"."""
    try:
        _fetch_one_inner(url, dest, sha256, size, allow_file, label, timeout,
                         max_bytes=max_bytes, deadline=deadline)
    except FetchError:
        raise
    except Exception as e:  # noqa: BLE001 - see the docstring
        raise FetchError(clean(f"{type(e).__name__}: {e}"))


def _fetch_one_inner(url: str, dest: Path, sha256: str, size: int, allow_file: bool,
                     label: str, timeout: int, max_bytes: int = None,
                     deadline: float = None) -> None:
    if size is not None and not isinstance(size, int):
        # A signed manifest can still carry a wrong TYPE. Comparing int > str raises a TypeError
        # that escaped every handler and crashed the caller.
        raise FetchError(f"manifest declares a non-integer size {clean(repr(size))}")
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.is_file() else 0
    if size and have > size:            # a stale, longer partial cannot be a prefix of this file
        part.unlink()
        have = 0
    if sha256 and size and have == size:
        # A COMPLETE partial: the previous run was stopped between the last byte and the rename.
        # A Range request for it can only be answered 416, so verify what is already here.
        if sha256_file(part) == sha256.lower():
            part.replace(dest)
            print(f"  {label}: {size:,} bytes verified")
            return
        part.unlink()
        have = 0

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if have:
        req.add_header("Range", f"bytes={have}-")

    started = time.monotonic()
    try:
        try:
            resp = _opener(allow_file).open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code != 416 or not have:
                raise
            # 416 Range Not Satisfiable: the partial is no prefix the server can continue (a
            # complete or stale `.part`, or a file republished shorter). Retrying the same Range
            # can only fail the same way on every attempt and every later run, so start over.
            e.close()
            return _restart(part, url, dest, sha256, size, allow_file, label, timeout,
                            max_bytes, deadline)
        with resp:
            status = getattr(resp, "status", 200) or 200
            if have and status != 206:
                # The server ignored Range. Concatenating would corrupt the file, so start over.
                print(f"\n  {label}: restarting the download from the beginning")
                part.unlink(missing_ok=True)
                have = 0
            elif have and _range_start(resp.headers) != have:
                # A 206 for a DIFFERENT range than the one asked for: appending it would splice
                # the wrong bytes in. Start over without a Range (this socket closed first).
                resp.close()
                return _restart(part, url, dest, sha256, size, allow_file, label, timeout,
                                max_bytes, deadline)
            # A chunked body's length is the chunks', whatever a stray Content-Length says
            # (http.client ignores it too).
            declared = None if resp.headers.get("Transfer-Encoding") \
                else _content_length(resp.headers)
            total = (declared + have) if declared is not None else (size or 0)
            # Cap on the manifest's size when it declares one, else on what the server claims,
            # else on an absolute ceiling. Without a fallback there was NO cap at all whenever a
            # manifest omitted `size`, so "abandoned rather than allowed to fill the disk" did
            # not hold for exactly the manifests least likely to be well-formed.
            if size:
                cap = size + SIZE_SLACK
            elif total:
                cap = total + SIZE_SLACK
            else:
                cap = MAX_UNDECLARED
            if max_bytes:
                cap = min(cap, max_bytes)
            if declared is not None and declared + have > cap:
                if have:
                    # Too long for a continuation (a proxy that sends the whole length for a
                    # range): refusing would keep the partial and repeat this on every attempt
                    # and every run. Without a Range the check below judges a full response.
                    resp.close()
                    return _restart(part, url, dest, sha256, size, allow_file, label, timeout,
                                    max_bytes, deadline)
                # Refused BEFORE a byte is written: streaming up to the cap first spent the
                # player's bandwidth and disk on a body already known to be the wrong one.
                raise FetchError(f"the server's Content-Length exceeds the expected size "
                                 f"({clean(cap)} bytes) -- abandoned before downloading")

            mode = "ab" if have else "wb"
            written = have
            with part.open(mode) as f:
                while True:
                    if deadline is not None and time.monotonic() > deadline:
                        raise FetchError("took too long -- abandoned")
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    if cap and written + len(chunk) > cap:
                        raise FetchError(
                            f"body exceeds the expected size ({clean(cap)} bytes) -- abandoned")
                    f.write(chunk)
                    written += len(chunk)
                    _progress(written, total, started, label)
    except FetchError:
        raise
    except Exception as e:  # noqa: BLE001 - see below
        # EVERYTHING becomes a FetchError. The old tuple missed http.client.InvalidURL (an
        # HTTPException, not a ValueError or OSError), so a signed manifest URL with a space or
        # a CR/LF escaped download() entirely, blocked the whole update through the preflight's
        # catch-all, and printed the raw forged line -- and crashed the bootstrap for `base`.
        # The text is cleaned because URLError/HTTPError reasons quote the server and the URL.
        raise FetchError(clean(f"{type(e).__name__}: {e}"))
    finally:
        # The isatty() call itself must be inside the guard: on a closed stdout it raises
        # ValueError from the finally and destroys the real exception -- the caller saw
        # "I/O operation on closed file" where the actual cause was a connection failure.
        try:
            if sys.stdout is not None and sys.stdout.isatty():
                sys.stdout.write("\n")
                sys.stdout.flush()
        except (OSError, ValueError, AttributeError):
            pass

    if size and part.stat().st_size != size:
        raise FetchError(f"download incomplete ({part.stat().st_size:,} of {size:,} bytes)")
    if sha256:
        got = sha256_file(part)
        if got != sha256.lower():
            part.unlink(missing_ok=True)      # a wrong body must not be resumed into
            raise FetchError(f"sha256 mismatch (got {got[:16]}..., expected "
                             f"{clean(sha256[:16])}...)")

    part.replace(dest)
    print(f"  {label}: {dest.stat().st_size:,} bytes verified")


def _restart(part: Path, url: str, dest: Path, sha256: str, size: int, allow_file: bool,
             label: str, timeout: int, max_bytes: int, deadline: float) -> None:
    """Discard the partial and fetch from byte zero. Bounded: with no partial there is no Range,
    so the call it makes cannot come back here."""
    print(f"\n  {label}: restarting the download from the beginning")
    part.unlink(missing_ok=True)
    _fetch_one(url, dest, sha256, size, allow_file, label, timeout,
               max_bytes=max_bytes, deadline=deadline)


def _digits(s, limit: int = 20):
    """A non-negative decimal integer from a server-supplied header field, else None. ASCII only:
    str.isdigit() accepts "²" and other Unicode digits that int() then refuses."""
    s = s.strip() if isinstance(s, str) else ""
    return int(s) if s and len(s) <= limit and s.isascii() and s.isdigit() else None


def _content_length(headers):
    return _digits(headers.get("Content-Length"))


def _range_start(headers):
    """The first byte of a 206's `Content-Range: bytes START-END/TOTAL`, else None."""
    v = headers.get("Content-Range")
    if not isinstance(v, str) or not v.strip().lower().startswith("bytes "):
        return None
    return _digits(v.strip()[6:].split("-", 1)[0])


def free_space(path: Path) -> int:
    """Bytes free on the volume holding `path` (walks up to the nearest existing parent)."""
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(str(p)).free
    except OSError:
        return 0


def staging_dir(game_dir: Path) -> Path:
    """Where in-flight downloads live. Under the game dir so it shares the target volume -- a
    free-space check against a different drive would be meaningless."""
    d = Path(game_dir) / "LongevityMods" / "staging"
    d.mkdir(parents=True, exist_ok=True)
    return d


def assert_writable(d: Path) -> None:
    """Raise OSError unless a file can actually be created in `d` (a directory can exist and
    still be read-only to this process -- a Program Files install run unelevated)."""
    probe = Path(d) / f".probe-{os.getpid()}"
    probe.write_bytes(b"")
    probe.unlink()


def fallback_cache_dir(game_dir: Path) -> Path:
    """A per-user, per-install cache for the manifest when the game folder cannot be written.

    `--check` runs at every game launch; when LongevityMods\\staging could not be created it
    exited 12 every time and the player was never told about an update. This keeps the CHECK
    working. Applying an update to such an install still needs elevation, which --update's
    preflight says plainly.
    """
    base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    try:
        key = str(Path(game_dir).resolve()).lower()
    except OSError:
        key = str(game_dir).lower()
    d = base / "LongevityVaccine" / hashlib.sha1(key.encode("utf-8")).hexdigest()[:12] / "staging"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clear_staging(game_dir: Path) -> None:
    """Reclaim the staging space, EXCEPT anything the running process lives in.

    A generation-2 installer runs from `staging\\payload-<ver>\\`, so a blanket rmtree would try
    to delete the directory holding its own interpreter: on Windows that fails part-way and
    leaves debris behind rather than cleaning up. Whatever is still in use is skipped; the next
    run's `reconcile`/`clear_staging` collects it once nothing is executing from it.
    """
    d = Path(game_dir) / "LongevityMods" / "staging"
    if not d.is_dir():
        return
    try:
        here = Path(sys.executable).resolve()
    except (OSError, ValueError):
        here = None
    for child in d.iterdir():
        try:
            if here is not None and child.resolve() in here.parents:
                continue          # we are running out of this one
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        next(d.iterdir())
    except StopIteration:
        shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass
