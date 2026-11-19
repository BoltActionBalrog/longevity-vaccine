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

import bisect
import hashlib
import io
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


class LinkError(FetchError):
    """A junction or symlink on the way into the game folder: nothing was downloaded. Not a connection problem, so
    a caller shows its message alone, uncut, with no "check your connection" (audit-g LOW-1)."""


class MismatchError(FetchError):
    """The whole file arrived and is not the one expected (its sha256 differs): not a network problem, so it is
    never retried as one, and a caller can say "did not match" instead of "check your connection" (execution
    audit 2026-11-15)."""


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme.lower() != "https":
            raise FetchError(f"refusing a redirect to a non-HTTPS URL: {clean(newurl)}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


#: Public roots our hosts chain to, loaded IN ADDITION to the Windows store (make_roots_pem.py says why: a
#: Windows 7 that never browsed to these authorities has them in no store Python can see).
ROOTS_PEM = Path(__file__).resolve().with_name("roots.pem")


def _windows_trusted_roots():
    """The DER of every certificate in the Windows ROOT store that is trusted for server authentication (the filter
    `ssl.load_default_certs` applies), one entry each. None where there is no Windows store (`ssl.enum_certificates`
    is Windows-only). Read-only: the stores are never written."""
    enum = getattr(ssl, "enum_certificates", None)
    if enum is None:
        return None
    oid = ssl.Purpose.SERVER_AUTH.oid
    return [der for der, encoding, trust in enum("ROOT")
            if encoding == "x509_asn" and (trust is True or oid in trust)]


def _context_from(ders):
    """A default client context trusting each certificate in `ders` that OpenSSL can parse, loaded ONE AT A TIME as
    CPython's own store loader does: a single root OpenSSL rejects must not discard the rest (it used to send the
    whole context back to the CA-store path below). None when none of them loads."""
    ctx = None
    for der in ders:
        try:
            if ctx is None:
                ctx = ssl.create_default_context(cadata=der)     # the default options, and no store read
            else:
                ctx.load_verify_locations(cadata=der)
        except ssl.SSLError:
            continue
    return ctx


def _with_bundle(ctx: ssl.SSLContext) -> ssl.SSLContext:
    if ROOTS_PEM.is_file():
        try:
            ctx.load_verify_locations(cafile=str(ROOTS_PEM))
        except (ssl.SSLError, OSError):
            pass                        # the Windows store alone, as before this bundle existed
    return ctx


def legacy_tls_context() -> ssl.SSLContext:
    """The pre-1.0.1 context: Python's default (the Windows ROOT and CA stores, both as trusted) plus roots.pem. Used
    only as the one retry after `tls_context` could not verify a server (`_open`)."""
    return _with_bundle(ssl.create_default_context())


def tls_context() -> ssl.SSLContext:
    """The context every download and check uses first: the Windows ROOT store's server-auth roots, OpenSSL's
    default paths (SSL_CERT_FILE / SSL_CERT_DIR) and roots.pem -- the trust anchors, and nothing from the Windows CA
    (intermediate) store.

    Why not `ssl.create_default_context()`: its `load_default_certs` loads the CA store as TRUSTED too, and Windows
    caches cross-certificates there. A laptop held both the self-signed "USERTrust ECC Certification Authority"
    (ROOT) and a cross-certificate of the same name issued by "AAA Certificate Services" (the CurrentUser CA
    store), with no AAA root anywhere. github.com's chain ends in a certificate issued by "USERTrust ECC", so OpenSSL had two
    issuers of that name to choose from, and which one it took changed from process to process: the cross-cert
    leads to AAA, which is missing ("unable to get issuer certificate"). The installer failed in 6 of 9 runs
    there, and the plain default context failed in the other 3 (2026-11-18); this context passed 42 of 42 there.
    Leaving the CA store out also means a server that sends only its leaf no longer borrows intermediates from the
    Windows cache (a TLS-inspecting proxy whose subordinate CA Group Policy put in that store): `_open` retries such
    a failure once with `legacy_tls_context`."""
    try:
        roots = _windows_trusted_roots()
    except (OSError, ssl.SSLError, TypeError, ValueError):
        roots = None                    # an unreadable store: the old path below
    if roots is not None:
        ctx = _context_from(roots)
        if ctx is not None:
            ctx.set_default_verify_paths()   # what load_default_certs adds besides the stores
            return _with_bundle(ctx)
        if ROOTS_PEM.is_file():
            # An empty ROOT store (a Windows 7 that never browsed to our authorities): the bundle is the trust.
            try:
                ctx = ssl.create_default_context(cafile=str(ROOTS_PEM))
                ctx.set_default_verify_paths()
                return ctx
            except (ssl.SSLError, OSError):
                pass
    return legacy_tls_context()


def _opener(allow_file: bool = False, legacy: bool = False):
    ctx = legacy_tls_context() if legacy else tls_context()
    handlers = [_HttpsOnlyRedirect(), urllib.request.HTTPSHandler(context=ctx)]
    if allow_file:
        handlers.append(urllib.request.FileHandler())
    return urllib.request.build_opener(*handlers)


def _open(req, allow_file: bool, timeout):
    """Open `req` with `tls_context`; when the server's certificate cannot be verified that way, once more with
    `legacy_tls_context` (the Windows intermediate store as well), which verified everything 1.0.0 did. Every other
    failure, an HTTP status or a refused connection included, is raised as it is, with no second attempt.

    This is for reliability, not a narrower trust: anyone who can present a bad certificate gets the retry, so the
    effective trust is still 1.0.0's. The bytes are pinned by the signed manifest's sha256 either way. When the
    retry fails too, the FIRST error is raised: the anchors-only diagnosis ("certificate has expired") is the true
    one, where the legacy path may stop earlier at a cross-certificate ("unable to get issuer certificate")."""
    try:
        return _opener(allow_file).open(req, timeout=timeout)
    except urllib.error.URLError as e:
        if not isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            raise
        first = e
    try:
        return _opener(allow_file, legacy=True).open(req, timeout=timeout)
    except urllib.error.URLError as e:
        if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            raise first from e
        raise


def sha256_file(p: Path, _buf: int = CHUNK) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(_buf), b""):
            h.update(chunk)
    return h.hexdigest()


#: True while a progress bar line (written with "\r", no newline) is the last thing on the console. Every other
#: line goes through _say, which ends that line first.
_LINE_OPEN = False


def _close_line() -> None:
    """End an open progress line with a newline. A no-op otherwise; never raises."""
    global _LINE_OPEN
    if not _LINE_OPEN:
        return
    _LINE_OPEN = False
    try:
        sys.stdout.write("\n")
        sys.stdout.flush()
    except (OSError, ValueError, AttributeError):
        pass


def _say(msg: str) -> None:
    _close_line()
    print(msg)


def _progress(done: int, total: int, started: float, label: str, since: int = 0) -> None:
    """`since`: the bytes of `done` that were already there when this transfer started (a split pack's earlier
    parts), left out of the rate."""
    global _LINE_OPEN
    try:
        if sys.stdout is None or not sys.stdout.isatty():
            return
    except (OSError, ValueError, AttributeError):
        return
    elapsed = max(time.monotonic() - started, 1e-6)
    rate = max(done - since, 0) / elapsed / (1 << 20)
    # The label column fits the longest pack name ("Turovetsky's HD Portrait Pack", 29) whole; the bar gave
    # up the room, so the line stays under 80 columns (audit 2026-11-06: the name was cut mid-word).
    name = label if len(label) <= 30 else label[:29] + "~"
    if total:
        pct = 100.0 * done / total
        bar_w = 20
        filled = int(bar_w * done / total)
        bar = "#" * filled + "-" * (bar_w - filled)
        line = f"\r  {name:<30} [{bar}] {pct:5.1f}%  {rate:5.1f} MB/s"
    else:
        line = f"\r  {name:<30} {done / (1 << 20):8.1f} MB  {rate:5.1f} MB/s"
    try:
        sys.stdout.write(line)
        sys.stdout.flush()
        _LINE_OPEN = True
    except (OSError, ValueError):
        pass


def human_size(n) -> str:
    """"1.3 GB" / "640 MB" / "12 KB" / "512 bytes", in the GAME's units: a port of the DLL's FormatBytes
    (src/uimod/src/update_core.h; user ruling 2026-11-17, "Match the game") -- binary units, GB/MB/KB labels, the unit
    picked by the ROUNDED value (1048575 is "1 MB", never "1024 KB"), integer arithmetic as there. "?" for a size that
    is not a number. One function for every size a player reads, so the notice's "1.3 GB download", the list's
    column, the preflight's free-space line and the game's own prompt all agree (test_human_size pins it to the
    compiled FormatBytes)."""
    try:
        b = int(n)
    except (TypeError, ValueError):
        return "?"
    if b < 0:
        return "?"
    mb, kb = (b + (1 << 19)) >> 20, (b + (1 << 9)) >> 10
    if b >= (1 << 30) or mb >= 1024:
        tenths = (b * 10 + (1 << 29)) >> 30                 # round to 0.1 GB
        return f"{tenths // 10}.{tenths % 10} GB"
    if b >= (1 << 20) or kb >= 1024:
        return f"{mb} MB"
    if b >= (1 << 10):
        return f"{kb} KB"
    return f"{b} bytes"


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
             max_bytes: int = None, deadline: float = None, source: str = "the update server",
             root: Path = None, span: tuple = None) -> Path:
    """Fetch `url` to `dest`, resuming and verifying. Raises FetchError on any failure.

    `dest` is the final path; bytes accumulate in `dest.part` first. `source` names the server in the retry line
    (the Thinker Mod download says "GitHub", user 2026-11-15). `span` = (offset, grand total): this file is one part
    of a split pack (download_parts), so the progress bar shows the WHOLE pack and no per-file line is printed.
    """
    dest = Path(dest)
    if root is not None:
        # In the game folder: nothing is written, resumed or deleted through a junction or symlink on the way to
        # dest (safe_fs; the user's rule 2026-11-15: nothing is ever deleted through a link). Checked first, so
        # none of the .part / dest removals below can act through one.
        import safe_fs
        if safe_fs.link_on_path(Path(root), dest.parent):
            link = safe_fs.first_link(Path(root), dest.parent) or dest.parent
            # User-approved wording (2026-11-15): the folder named is the link itself, in full -- a path in the
            # player's game folder, not a manifest value, so not clean()'s 120-character cut (which hid the name).
            raise LinkError(f"{link} is a link to another folder, so nothing was downloaded there.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    label = label or dest.name

    # Already present and correct? Then this is a no-op -- re-downloading 1.3 GB because a later
    # module failed would be its own defect.
    if dest.is_file() and sha256:
        if sha256_file(dest) == sha256.lower():
            if span is None:
                _say(f"  {label}: already present and verified")
            else:
                # A part an earlier run verified: the pack's bar moves past it, so it never stops short of 100%.
                _progress(span[0] + dest.stat().st_size, span[1], time.monotonic(), label,
                          since=span[0] + dest.stat().st_size)
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
                           max_bytes=max_bytes, deadline=deadline, span=span)
                return dest
            except MismatchError as e:
                last_error = e                   # the same URL serves the same wrong file: no retry (a mirror may not)
                break
            except FetchError as e:
                last_error = e
                if attempt < max_attempts:
                    # One plain line per retry. The technical reason (URLError / errno soup) is
                    # kept for the final error, not shown to the player three times over.
                    _say(f"  Could not reach {source}, trying again ({attempt + 1} of {max_attempts})...")
                    time.sleep(min(2 ** attempt, 8))
        if mirror and candidate != urls[-1]:
            _say("  Trying the backup server...")
    raise (MismatchError if isinstance(last_error, MismatchError) else FetchError)(
        f"could not download {label}: {last_error}")


def _fetch_one(url: str, dest: Path, sha256: str, size: int, allow_file: bool,
               label: str, timeout: int, max_bytes: int = None,
               deadline: float = None, span: tuple = None) -> None:
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
                         max_bytes=max_bytes, deadline=deadline, span=span)
    except FetchError:
        raise
    except Exception as e:  # noqa: BLE001 - see the docstring
        raise FetchError(clean(f"{type(e).__name__}: {e}"))


def _fetch_one_inner(url: str, dest: Path, sha256: str, size: int, allow_file: bool,
                     label: str, timeout: int, max_bytes: int = None,
                     deadline: float = None, span: tuple = None) -> None:
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
            if span is None:
                _say(f"  {label}: {size:,} bytes verified")
            return
        part.unlink()
        have = 0

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if have:
        req.add_header("Range", f"bytes={have}-")

    started = time.monotonic()
    try:
        try:
            resp = _open(req, allow_file, timeout)
        except urllib.error.HTTPError as e:
            if e.code != 416 or not have:
                raise
            # 416 Range Not Satisfiable: the partial is no prefix the server can continue (a
            # complete or stale `.part`, or a file republished shorter). Retrying the same Range
            # can only fail the same way on every attempt and every later run, so start over.
            e.close()
            return _restart(part, url, dest, sha256, size, allow_file, label, timeout,
                            max_bytes, deadline, span)
        with resp:
            status = getattr(resp, "status", 200) or 200
            if have and status != 206:
                # The server ignored Range. Concatenating would corrupt the file, so start over.
                _say(_restart_line(label, span))
                part.unlink(missing_ok=True)
                have = 0
            elif have and _range_start(resp.headers) != have:
                # A 206 for a DIFFERENT range than the one asked for: appending it would splice
                # the wrong bytes in. Start over without a Range (this socket closed first).
                resp.close()
                return _restart(part, url, dest, sha256, size, allow_file, label, timeout,
                                max_bytes, deadline, span)
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
                                    max_bytes, deadline, span)
                # Refused BEFORE a byte is written: streaming up to the cap first spent the
                # player's bandwidth and disk on a body already known to be the wrong one.
                raise FetchError(f"the server's Content-Length exceeds the expected size "
                                 f"({clean(cap)} bytes): abandoned before downloading")

            mode = "ab" if have else "wb"
            written = have
            with part.open(mode) as f:
                while True:
                    if deadline is not None and time.monotonic() > deadline:
                        raise FetchError("took too long: abandoned")
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    if cap and written + len(chunk) > cap:
                        raise FetchError(
                            f"body exceeds the expected size ({clean(cap)} bytes): abandoned")
                    f.write(chunk)
                    written += len(chunk)
                    if span is None:
                        _progress(written, total, started, label)
                    else:
                        _progress(span[0] + written, span[1], started, label, since=span[0] + have)
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
        # A split pack's parts share ONE bar: the line stays open between them, and whatever is printed next (_say)
        # or the end of download_parts closes it.
        if span is None:
            _close_line()

    if size and part.stat().st_size != size:
        raise FetchError(f"download incomplete ({part.stat().st_size:,} of {size:,} bytes)")
    if sha256:
        got = sha256_file(part)
        if got != sha256.lower():
            part.unlink(missing_ok=True)      # a wrong body must not be resumed into
            if have:
                # A RESUMED .part may have had a bad prefix: start over from byte zero, at once (verifications of
                # 7b53fbb / 9f2cb08: retried as a failed attempt it printed "Could not reach the update server", and
                # on the last attempt a tampered file read as a connection failure). The restart has no Range, so a
                # file that is still wrong is the MismatchError below.
                return _restart(part, url, dest, sha256, size, allow_file, label, timeout, max_bytes, deadline, span)
            raise MismatchError(f"sha256 mismatch (got {got[:16]}..., expected {clean(sha256[:16])}...)")

    part.replace(dest)
    if span is None:
        _say(f"  {label}: {dest.stat().st_size:,} bytes verified")


def _restart(part: Path, url: str, dest: Path, sha256: str, size: int, allow_file: bool,
             label: str, timeout: int, max_bytes: int, deadline: float, span: tuple = None) -> None:
    """Discard the partial and fetch from byte zero. Bounded: with no partial there is no Range,
    so the call it makes cannot come back here."""
    _say(_restart_line(label, span))
    part.unlink(missing_ok=True)
    _fetch_one(url, dest, sha256, size, allow_file, label, timeout,
               max_bytes=max_bytes, deadline=deadline, span=span)


def _restart_line(label: str, span) -> str:
    """What a restart says. For one part of a split pack only that part starts over, and the player never hears of
    parts: "from the beginning" would claim the whole pack is fetched again."""
    if span is None:
        return f"  {label}: restarting the download from the beginning"
    return f"  {label}: some of the download is being fetched again"


def download_parts(parts: list, dests: list, *, label: str, allow_file: bool = False, root: Path = None,
                   timeout: int = CONNECT_TIMEOUT, max_attempts: int = 3,
                   source: str = "the update server") -> list:
    """Fetch every part of a split pack, in order, each to its own file in `dests`. Raises FetchError for the first
    part that cannot be had; the parts already verified stay where they are, so the next run fetches only the rest.

    `parts` is manifest.module_parts' list ({"url", "sha256", "size", "mirror"}). Each part is an ordinary download:
    its own sha256 from the signed manifest, its own `.part` resume, its own mirror. The player sees ONE pack: one
    progress bar across every part and one "verified" line at the end, never a part number."""
    if len(parts) != len(dests):
        raise FetchError("internal error: one destination per part is needed")
    total = sum(p["size"] for p in parts)
    offset, out = 0, []
    try:
        for p, dest in zip(parts, dests):
            out.append(download(p["url"], dest, sha256=p["sha256"], size=p["size"], mirror=p.get("mirror"),
                                allow_file=allow_file, label=label, timeout=timeout, max_attempts=max_attempts,
                                source=source, root=root, span=(offset, total)))
            offset += p["size"]
    finally:
        _close_line()
    _say(f"  {label}: {total:,} bytes verified")
    return out


class ConcatReader(io.RawIOBase):
    """The files of a split pack, read as the ONE archive they were cut from: seekable and read-only.

    `zipfile.ZipFile(ConcatReader(parts))` reads the pack in place. Nothing is joined on disk (the staged parts plus
    the extracted pack take what one staged archive did), and the installer extracts exactly the zip that was built
    and tested. Closing it closes every part. ZipFile does not close a file object it is handed, so callers hold it
    in a `with`."""

    def __init__(self, paths):
        super().__init__()
        self._files, self._starts = [], []
        pos = 0
        try:
            for p in paths:
                f = open(p, "rb")
                self._files.append(f)
                self._starts.append(pos)
                pos += os.fstat(f.fileno()).st_size
        except BaseException:
            for f in self._files:
                f.close()
            raise
        self._size, self._pos = pos, 0
        self.name = str(paths[0]) if paths else ""

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        self._checkClosed()
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        self._checkClosed()
        if whence == io.SEEK_SET:
            pos = offset
        elif whence == io.SEEK_CUR:
            pos = self._pos + offset
        elif whence == io.SEEK_END:
            pos = self._size + offset
        else:
            raise ValueError(f"invalid whence {whence!r}")
        if pos < 0:
            raise OSError(22, "negative seek position")
        self._pos = pos
        return pos

    def readinto(self, b) -> int:
        """Fills `b` across part boundaries (a short read only at the end): zipfile reads its central directory with
        one read() and takes a short answer as a corrupt archive."""
        self._checkClosed()
        view = memoryview(b).cast("B")
        done = 0
        while done < len(view) and self._pos < self._size:
            i = bisect.bisect_right(self._starts, self._pos) - 1
            f = self._files[i]
            end = self._starts[i + 1] if i + 1 < len(self._starts) else self._size
            f.seek(self._pos - self._starts[i])
            # Never past this part's length as opened: a part that grew since must not stand in for the next one.
            n = f.readinto(view[done:done + (end - self._pos)])
            if not n:
                # A part shorter now than when it was opened: the archive is no longer whole.
                raise OSError(f"{f.name} changed while it was being read")
            self._pos += n
            done += n
        return done

    def close(self) -> None:
        if not self.closed:
            for f in self._files:
                try:
                    f.close()
                except OSError:
                    pass
        super().close()


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
    import safe_fs
    if safe_fs.link_on_path(Path(game_dir), d):
        return d          # never created through a link (audit-g): a download into it refuses (LinkError)
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
    import safe_fs
    if safe_fs.link_on_path(Path(game_dir), d):
        return                    # a junctioned LongevityMods or staging: never empty a folder elsewhere
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
