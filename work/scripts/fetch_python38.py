"""Fetch the Windows 7 interpreter: CPython 3.8.10 (32-bit embeddable) + the app-local UCRT.

WHY A SECOND INTERPRETER. The installer and the resident updater run on the bundled CPython 3.12
(tools\\python). CPython dropped Windows 7 at 3.9, so on Windows 7 / 8 the 3.12 python.exe dies in
the loader (api-ms-win-core-path-l1-1-0.dll) before a line of ours runs: no install, no update
check, no message. 3.8.10 is the last CPython that starts there (and the last 3.8 with Windows
binaries; EOL October 2024 -- it runs the SAME scripts as 3.12, signature verification included,
and gets no fixes). It ships beside 3.12 as tools\\python38; run-install.bat, bootstrap.py and the
DLL's update check pick it on Windows older than 8.1 (6.3) and never touch it elsewhere.

WHAT THIS SCRIPT DOES. Deterministically, so a release is reproducible and reviewable:
  1. downloads python-3.8.10-embed-win32.zip (+ its .asc) from python.org into an empty folder,
  2. refuses it unless size, MD5 (python.org's published sum) and SHA256 (pinned here after the
     first verified download) all match -- and GPG-verifies the .asc when gpg and the release
     manager's key are available (`--gpg`),
  3. extracts it to tools\\python38 and adds the Universal C Runtime DLLs from the Windows SDK's
     redistributable folder (Redist\\<ver>\\ucrt\\DLLs\\x86): python38.dll imports the
     api-ms-win-crt-* set, which Windows 7 only has after update KB2999226, and a player who never
     took that update would again die in the loader. App-local UCRT is Microsoft's supported
     deployment for exactly this; on Windows 10+ the api-set schema ignores the local copies.
     NOT covered: KB2533623 (2011) -- CPython 3.8's own extension loader uses the LOAD_LIBRARY_SEARCH_*
     flags it adds, so without it every .pyd import fails. The floor is Windows 7 SP1 + KB2533623;
     run-install.bat probes `import ctypes` under 3.8 and names the update when it fails.
  4. writes PROVENANCE.txt (URLs, hashes, SDK version, date) next to the interpreter.

    py work\\scripts\\fetch_python38.py            # tools\\python38; verifies the OpenPGP signature when gpg is present
    py work\\scripts\\fetch_python38.py --no-gpg   # hashes only

build_runtime.py stages tools\\python38 as work\\build\\runtime38 and runs the installer under it.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_REPO = _SCRIPTS.parent.parent

VERSION = "3.8.10"
ZIP_NAME = f"python-{VERSION}-embed-win32.zip"
BASE_URL = f"https://www.python.org/ftp/python/{VERSION}/"
ZIP_URL = BASE_URL + ZIP_NAME
ASC_URL = ZIP_URL + ".asc"
#: python.org's release page (https://www.python.org/downloads/release/python-3810/) publishes the MD5
#: and size; the SHA256 is ours, pinned from the first download that matched both.
ZIP_SIZE = 7348969
ZIP_MD5 = "659adf421e90fba0f56a9631f79e70fb"
ZIP_SHA256 = "760dc79bcb434ee80b1001a30bb6f798287881851bac6d8137867894d40ef1fc"   # pinned 2026-10-31 (--pin)
#: Release manager of the 3.8 series (Lukasz Langa), fingerprint from https://www.python.org/downloads/;
#: the .asc is made by a signing subkey of it. python.org points at keybase for the key itself.
RM_FINGERPRINT = "E3FF2839C048B25C084DEBE9B26995E310250568"
RM_KEY_URL = "https://keybase.io/ambv/pgp_keys.asc"

DEST = _REPO / "tools" / "python38"
SDK_REDIST = Path(r"C:\Program Files (x86)\Windows Kits\10\Redist")

#: What an extracted embeddable must contain to be the one we expect. A truncated or foreign zip
#: that happened to match nothing above still fails here.
EXPECT_FILES = ("python.exe", "python38.dll", "python3.dll", "python38.zip", "python38._pth",
                "vcruntime140.dll", "_ssl.pyd", "_hashlib.pyd", "_ctypes.pyd", "libssl-1_1.dll",
                "libcrypto-1_1.dll", "libffi-7.dll", "LICENSE.txt")

#: The ._pth we write over the embeddable's: the interpreter sees ONLY its own stdlib zip and its
#: folder -- no PYTHONPATH, no registry, no user site (the same isolation build_runtime gives 3.12).
PTH_BODY = "python38.zip\n.\n"


class FetchError(Exception):
    pass


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, say=print) -> Path:
    say(f"  fetching {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "longevity-fetch-python38/1"})
    with urllib.request.urlopen(req, timeout=120) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f)
    return dest


def check_zip(zip_path: Path, pin_sha256: bool, say=print) -> str:
    """Size + MD5 + SHA256, or FetchError. Returns the SHA256."""
    size = zip_path.stat().st_size
    if size != ZIP_SIZE:
        raise FetchError(f"{zip_path.name}: size {size}, expected {ZIP_SIZE}")
    md5 = _md5(zip_path)
    if md5 != ZIP_MD5:
        raise FetchError(f"{zip_path.name}: MD5 {md5}, python.org publishes {ZIP_MD5}")
    sha = _sha256(zip_path)
    if not pin_sha256 and sha != ZIP_SHA256:
        raise FetchError(f"{zip_path.name}: SHA256 {sha}, pinned {ZIP_SHA256}")
    say(f"  {zip_path.name}: {size:,} bytes, md5 {md5}, sha256 {sha} -- ok")
    return sha


def gpg_verify(zip_path: Path, asc_path: Path, say=print) -> bool:
    gpg = shutil.which("gpg") or r"C:\Program Files\Git\usr\bin\gpg.exe"
    if not Path(gpg).is_file():
        say("  gpg not found -- signature not checked")
        return False
    def have_key() -> bool:
        return subprocess.run([gpg, "--list-keys", RM_FINGERPRINT], capture_output=True, text=True).returncode == 0
    if not have_key():
        say(f"  importing the release manager's key {RM_FINGERPRINT} from {RM_KEY_URL}")
        try:
            with tempfile.TemporaryDirectory(prefix="longevity-py38-key-") as kd:
                key = download(RM_KEY_URL, Path(kd) / "rm.asc", say=lambda *_: None)
                imp = subprocess.run([gpg, "--import", str(key)], capture_output=True, text=True, timeout=120)
        except OSError as e:
            say(f"  key download failed: {e} -- signature not checked")
            return False
        if imp.returncode != 0 or not have_key():
            say(f"  key import failed: {imp.stderr.strip()} -- signature not checked")
            return False
    v = subprocess.run([gpg, "--status-fd", "1", "--verify", str(asc_path), str(zip_path)],
                       capture_output=True, text=True, timeout=120)
    status = v.stdout.splitlines()
    if any(line.startswith("[GNUPG:] VALIDSIG ") and RM_FINGERPRINT in line for line in status):
        say(f"  OpenPGP signature valid ({RM_FINGERPRINT})")
        return True
    if any(line.startswith(("[GNUPG:] BADSIG", "[GNUPG:] EXPKEYSIG", "[GNUPG:] REVKEYSIG")) for line in status):
        raise FetchError(f"GPG: bad / expired-key / revoked-key signature on {zip_path.name}:\n{v.stdout}{v.stderr}")
    # NO_PUBKEY for the SIGNING SUBKEY: the 2021 .asc was made by a subkey (FC624643487034E5) that
    # the key's published copies (keys.openpgp.org, keybase) no longer carry. Not a bad signature --
    # an uncheckable one; size + MD5 (python.org's page) + the pinned SHA256 remain the gate.
    say("  OpenPGP signature could not be checked (signing subkey absent from the published key) -- "
        "relying on size + MD5 + pinned SHA256")
    return False


def ucrt_dir() -> Path:
    """The newest Windows SDK's x86 UCRT redistributables (ucrtbase.dll + the api-ms-win-crt-* forwarders)."""
    if not SDK_REDIST.is_dir():
        raise FetchError(f"no Windows SDK redist at {SDK_REDIST} (install the Windows 10/11 SDK with the UCRT component)")
    cands = sorted(p for p in SDK_REDIST.glob("10.0.*/ucrt/DLLs/x86") if (p / "ucrtbase.dll").is_file())
    if not cands:
        raise FetchError(f"no ucrt/DLLs/x86/ucrtbase.dll under {SDK_REDIST}")
    return cands[-1]


def install(zip_path: Path, dest: Path, sha256: str, gpg_ok: bool, say=print) -> int:
    """Extract + add the UCRT + write the ._pth and PROVENANCE.txt. Returns the file count."""
    if dest.exists():
        # Only a folder this script made (PROVENANCE.txt) or an empty one is replaced: `--dest` pointed
        # at the wrong place must not erase it.
        if any(dest.iterdir()) and not (dest / "PROVENANCE.txt").is_file():
            raise FetchError(f"{dest} exists, is not empty and is not a previous fetch (no PROVENANCE.txt): refusing to replace it")
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                raise FetchError(f"refusing zip entry {name!r}")
        z.extractall(dest)
    missing = [f for f in EXPECT_FILES if not (dest / f).is_file()]
    if missing:
        raise FetchError(f"the extracted embeddable lacks {missing}: not the package this script expects")
    (dest / "python38._pth").write_text(PTH_BODY, encoding="ascii")

    ucrt = ucrt_dir()
    n_ucrt = 0
    for p in sorted(ucrt.glob("*.dll")):
        shutil.copy2(p, dest / p.name.lower())
        n_ucrt += 1
    sdk_ver = ucrt.parents[2].name

    prov = (
        f"CPython {VERSION}, Windows embeddable package (32-bit), fetched {time.strftime('%Y-%m-%d')}\n"
        f"  {ZIP_URL}\n"
        f"  size {ZIP_SIZE}  md5 {ZIP_MD5}  sha256 {sha256}\n"
        f"  OpenPGP signature {ASC_URL}: "
        f"{'verified (' + RM_FINGERPRINT + ')' if gpg_ok else 'uncheckable (signing subkey absent from the published key)'}\n"
        f"  trust anchor: size + the MD5 python.org's release page publishes + this SHA256, pinned from the first\n"
        f"  download that matched both; no independent record of the SHA256 was found (web search 2026-10-31).\n"
        f"  The mod's own updates are trusted through the Ed25519 manifest, not through this interpreter.\n"
        f"  requirements: Windows 7 SP1 + KB2533623 (CPython 3.8's extension loader), or any later Windows\n"
        f"  licence: PSF-2.0 (LICENSE.txt beside this file)\n"
        f"Universal C Runtime, app-local deployment: {n_ucrt} DLLs from the Windows SDK {sdk_ver}\n"
        f"  {ucrt}\n"
        f"  licence: Microsoft Windows SDK redistributable (Redist\\ucrt)\n"
        f"Purpose: the installer / updater interpreter on Windows 7 and 8 (CPython 3.12 needs 8.1).\n"
    )
    (dest / "PROVENANCE.txt").write_text(prov, encoding="utf-8")
    total = sum(1 for p in dest.rglob("*") if p.is_file())
    say(f"  {dest}: {total} files ({n_ucrt} UCRT DLLs from SDK {sdk_ver})")
    return total


def main() -> int:
    apr = argparse.ArgumentParser(description="Fetch CPython 3.8.10 (Windows 7 interpreter) into tools\\python38.")
    apr.add_argument("--dest", default=str(DEST))
    apr.add_argument("--no-gpg", action="store_true", help="skip the OpenPGP signature check (default: on when gpg is present)")
    apr.add_argument("--pin", action="store_true",
                     help="first fetch: accept the SHA256 that goes with the published MD5 and print it to pin here")
    apr.add_argument("--from-zip", help="use an already downloaded zip instead of fetching (still verified)")
    args = apr.parse_args()

    # The download lands in a folder of its own, created empty: nothing is ever run from there.
    dl = Path(tempfile.mkdtemp(prefix="longevity-py38-dl-"))
    try:
        if args.from_zip:
            zip_path = dl / ZIP_NAME
            shutil.copy2(args.from_zip, zip_path)
        else:
            zip_path = download(ZIP_URL, dl / ZIP_NAME)
        asc_path = download(ASC_URL, dl / (ZIP_NAME + ".asc")) if not args.no_gpg else None
        sha = check_zip(zip_path, pin_sha256=args.pin)
        if args.pin:
            print(f"  pin this in fetch_python38.py: ZIP_SHA256 = \"{sha}\"")
        gpg_ok = gpg_verify(zip_path, asc_path) if asc_path else False
        install(zip_path, Path(args.dest), sha, gpg_ok)
        return 0
    except FetchError as e:
        print(f"ERROR: {e}")
        return 2
    finally:
        shutil.rmtree(dl, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
