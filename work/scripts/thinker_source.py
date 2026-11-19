"""Download the pinned Thinker Mod release from its author's own link and unpack it to staging.

Design sections 8 (addresses) and 9 (manifest and trust); user rulings 2026-11-13/14:
* the bytes come from the author's GitHub release asset; a development-build pin (which exists
  only when the author sends that build's own link) comes from that one Dropbox zip;
* the URL is BUILT from a compiled prefix plus a grammar-checked tag/asset or Dropbox path, never
  read whole from the manifest;
* the whole zip is checked against its size and sha256 BEFORE zipfile opens it;
* only the pinned release's own file list is extracted, each file checked against its compiled
  sha256, each path checked against the allowlist (no zip-slip, no bomb: sizes are known);
* nothing is hosted or mirrored by us.
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import fetch

THINKER_REPO_URL = "https://github.com/induktio/thinker"
#: What Thinker Mod is, for a player who does not have it yet: the new-install screen's "Learn more here" (user
#: 2026-11-16, after talking with the author). publish.thinker_urls checks it before a release.
THINKER_DETAILS_URL = THINKER_REPO_URL + "/blob/master/Details.md"
THINKER_AUTHOR = "Induktio"              # the author's byline in Thinker's own files ("SMACX Thinker Mod by Induktio")
GITHUB_DOWNLOAD_PREFIX = THINKER_REPO_URL + "/releases/download/"
RELEASE_PAGE_PREFIX = THINKER_REPO_URL + "/releases/tag/"
DROPBOX_PREFIX = "https://www.dropbox.com/"
CHANGELOG_URL = THINKER_REPO_URL + "/blob/master/Changelog.md"
# publish.shown_urls verifies the repository page, the pinned build's page, its download and the changelog
# before every release; the prefixes above are completed with the compiled pin (test_publish pins this).

TAG_RE = re.compile(r"v[0-9]{1,3}(\.[0-9]{1,3}){1,2}")
ASSET_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}\.zip")
DROPBOX_RE = re.compile(r"scl/fo/[A-Za-z0-9_-]{8,40}/[A-Za-z0-9_-]{8,40}(/[A-Za-z0-9_.-]{1,64}){1,3}\.zip"
                        r"|scl/fi/[A-Za-z0-9_-]{8,40}/[A-Za-z0-9_.-]{1,64}\.zip")
RLKEY_RE = re.compile(r"[a-z0-9]{10,40}")

ALLOWED_DIRS = ("", "german", "smac_mod", "basenames")
PART_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
NEVER = {"uimod.dll", "terranx.exe", "terranx_pracx.exe", "longevitymods"}


class SourceError(ValueError):
    """A pin entry or a downloaded file that fails its grammar or its hash."""


@dataclass(frozen=True)
class Pin:
    """Everything needed to fetch one pinned build. From the compiled data, or a manifest entry that
    passed `pin_from_manifest`."""
    pin_id: str                   # "5.5.0" or "dev-20251109"
    tag: str = ""                 # GitHub release tag, e.g. "v5.5"
    asset: str = ""               # GitHub asset name
    dropbox: str = ""             # Dropbox path (development-build pin)
    rlkey: str = ""
    zip_size: int = 0
    zip_sha256: str = ""
    files: tuple = ()             # ((path, sha256), ...)

    @property
    def is_dev(self) -> bool:
        return bool(self.dropbox)


def check_path(path: str) -> str:
    """The allowlist (design section 9): a relative path of at most two parts, under the root or one
    of Thinker's own folders, plain characters, no Windows device names, never our own files."""
    p = PurePosixPath(path)
    parts = p.parts
    if p.is_absolute() or not parts or len(parts) > 2 or any(x in ("", ".", "..") for x in parts):
        raise SourceError(f"path not allowed: {path!r}")
    if (parts[0] if len(parts) == 2 else "") not in ALLOWED_DIRS:
        raise SourceError(f"folder not allowed: {path!r}")
    for x in parts:
        if not PART_RE.fullmatch(x) or x.split(".")[0].lower() in _RESERVED or x.endswith((".", " ")):
            raise SourceError(f"name not allowed: {path!r}")
    if parts[-1].lower() in NEVER or parts[0].lower() in NEVER:
        raise SourceError(f"never replaced: {path!r}")
    return "/".join(parts)


def download_url(pin: Pin) -> str:
    if pin.dropbox:
        if not DROPBOX_RE.fullmatch(pin.dropbox) or (pin.rlkey and not RLKEY_RE.fullmatch(pin.rlkey)):
            raise SourceError("development-build link fails its grammar")
        q = (f"rlkey={pin.rlkey}&" if pin.rlkey else "") + "dl=1"
        return f"{DROPBOX_PREFIX}{pin.dropbox}?{q}"
    if not TAG_RE.fullmatch(pin.tag) or not ASSET_RE.fullmatch(pin.asset):
        raise SourceError("release tag or asset name fails its grammar")
    return f"{GITHUB_DOWNLOAD_PREFIX}{pin.tag}/{pin.asset}"


def page_url(pin: Pin) -> str:
    """The page players are pointed to (section 8): the release page, or that build's own Dropbox page."""
    if pin.dropbox:
        return download_url(pin)[:-len("dl=1")] + "dl=0"
    if not TAG_RE.fullmatch(pin.tag):
        raise SourceError("release tag fails its grammar")
    return RELEASE_PAGE_PREFIX + pin.tag


def compiled_pin(data) -> Pin:
    """The pin compiled into this installer (thinker_data)."""
    return Pin(pin_id=data.PIN_VERSION, tag=data.PIN_TAG, asset=data.PIN_ASSET,
               dropbox=getattr(data, "PIN_DROPBOX", ""), rlkey=getattr(data, "PIN_RLKEY", ""),
               zip_size=data.PIN_ZIP_SIZE, zip_sha256=data.PIN_ZIP_SHA256,
               files=tuple(sorted(data.PIN_FILES.items())))


def fetch_zip(pin: Pin, staging: Path, *, label: str = None, url: str = None, root: Path = None) -> Path:
    """Download the pin's zip into `staging`, verified (size and sha256) before anything opens it. `url`, when
    given, is the caller's own `download_url(pin)` (the one it showed the player); it must be that."""
    if not pin.zip_sha256 or not pin.zip_size:
        raise SourceError("the pin has no recorded zip hash")
    want = download_url(pin)
    if url is not None and url != want:
        raise SourceError("the shown URL is not the pin's download URL")
    dest = Path(staging) / f"thinker-{pin.pin_id}.zip"
    # The retry line names GitHub (user 2026-11-15) -- only when the pin's zip is on GitHub: a development pin's
    # Dropbox link keeps the shared wording.
    from urllib.parse import urlparse
    host = (urlparse(want).hostname or "").lower()
    source = "GitHub" if host == "github.com" or host.endswith(".github.com") else "the update server"
    return fetch.download(want, dest, sha256=pin.zip_sha256, size=pin.zip_size,
                          max_bytes=pin.zip_size, label=label or f"Thinker Mod {pin.pin_id}", source=source,
                          root=root)


def extract(pin: Pin, zip_path: Path, out_dir: Path) -> dict:
    """Unpack exactly the pin's files from an already-verified zip into `out_dir`; returns
    {path: Path}. Each member is read by its exact name, capped at its known size and checked
    against its compiled sha256. Members not in the list are ignored."""
    zip_path = Path(zip_path)
    h = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    if h != pin.zip_sha256.lower():
        raise SourceError("the Thinker Mod download does not match the release")
    out = {}
    with zipfile.ZipFile(zip_path) as z:
        names = {i.filename: i for i in z.infolist() if not i.is_dir()}
        for path, sha in pin.files:
            rel = check_path(path)
            info = names.get(rel)
            if info is None:
                raise SourceError(f"the download lacks {rel}")
            if info.file_size > 64 << 20:
                raise SourceError(f"{rel} is too large")
            data = z.read(info)
            if hashlib.sha256(data).hexdigest() != sha.lower():
                raise SourceError(f"{rel} does not match the release")
            dest = Path(out_dir).joinpath(*rel.split("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.is_symlink() or (dest.exists() and not dest.is_file()):
                raise SourceError(f"staging holds a link at {rel}")
            try:
                dest.unlink()
            except FileNotFoundError:
                pass
            with open(dest, "xb") as f:
                f.write(data)
            out[rel] = dest
    return out
