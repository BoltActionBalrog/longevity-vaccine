"""Build the Longevity Vaccine release artifacts: staged modules, deterministic zips, manifest.

Nothing in this repo built a distributable before this script. It produces, under `dist\\release`:

    <version>\\LongevityVaccine_<version>.zip   the mod + the installer + its Python runtime
    <version>\\manifest.json                    what the updater fetches; signed with --sign-key
    modules\\LV-movies-hd-<pack version>.zip     the 61 upscaled cinematics
    modules\\LV-movies-hd-<pack version>.zip.NNN  its parts: what is uploaded (over 2 GiB; split_archive)
    modules\\LV-portraits-hd-<pack version>.zip  (when the pack exists)

DESIGN NOTES

* Packs are versioned INDEPENDENTLY of the product (version.py MODULE_VERSIONS) and live under
  `modules\\` named for their own version, so a product release reuses them unchanged and a
  pack-only release (`--modules movies-hd`) reuses the product archive. The manifest always
  lists every module that has an artifact. Changing a pack's CONTENT means bumping its version:
  an archive name is immutable once published, and an unbumped pack is reused, not rebuilt.

* Archive layout is FLAT and is the one and only payload layout: a `scripts` folder for the
  code and its launcher, `patches` beside it, `CHANGELOG.txt` at the root. A checkout keeps the
  same files under `work`, because that folder also holds tests, screenshots and notes and is
  not a payload -- the mapping below is the only place the two are related, and nothing in the field
  ever sees the checkout shape.

* Zips are DETERMINISTIC: entries sorted, timestamps fixed, no host metadata. The same inputs
  must produce the same sha256, or the manifest hash changes on every rebuild and nobody can
  tell a real change from a repack.

* The manifest reads its target table straight out of patches.yaml, so the shipped
  base/patched MD5s cannot drift from what the patcher actually applies.

* It REFUSES to package when the L1 gate fails, and refuses when the bundled Python still
  carries developer-only packages (frida, pytest, numpy, ...). The latter is the single biggest
  release-payload defect and it is invisible in a working tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import version as ver  # noqa: E402
import bootstrap as bs  # noqa: E402  (the payload file list's one format: make_inventory / INVENTORY_REL)

_REPO = _SCRIPTS.parent.parent
_PATCHES = _REPO / "work" / "patches" / "patches.yaml"
_TESTS = _REPO / "work" / "tests"
_PY = _REPO / "tools" / "python" / "python.exe"

#: A fixed timestamp for every zip entry. 1980-01-01 is the earliest the zip format allows.
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

#: Packages that must NEVER ship. The installer needs exactly pyyaml + pefile; everything else
#: in tools\python\Lib\site-packages is developer tooling (Ghidra bridge, Frida, test harness,
#: image/pixel maths) and accounts for most of the 428 MB payload.
DEV_ONLY = {
    "PIL", "pillow", "capstone", "keystone", "frida", "frida_tools", "jpype", "_jpype",
    "numpy", "pyghidra", "pytest", "_pytest", "pygments", "prompt_toolkit", "wcwidth",
    "websockets", "colorama", "iniconfig", "pluggy", "packaging", "py.py", "org.jpype.jar",
    "xdist", "execnet", "pytest_xdist",
}

#: What goes in each module, as (source, archive path) pairs. `source` may be a file or a dir.
#: Archive paths are repo-relative so an extracted archive is a working tree for install.py.
MODULE_SPEC = {
    "base": {
        "required": True,
        "files": [
            ("work/run-install.bat", "scripts/run-install.bat"),
            # The installer's own runtime. Everything install.py imports at run time has to be
            # here: shipping install.py without ed25519_verify/manifest would leave an installed
            # copy unable to check a signature, i.e. unable to update at all.
            ("work/scripts/install.py", "scripts/install.py"),
            ("work/scripts/apply_patches.py", "scripts/apply_patches.py"),
            ("work/scripts/config.py", "scripts/config.py"),
            ("work/scripts/version.py", "scripts/version.py"),
            ("work/scripts/installer_exit.py", "scripts/installer_exit.py"),
            ("work/scripts/ed25519_verify.py", "scripts/ed25519_verify.py"),
            ("work/scripts/manifest.py", "scripts/manifest.py"),
            ("work/scripts/fetch.py", "scripts/fetch.py"),
            ("work/scripts/preflight.py", "scripts/preflight.py"),
            ("work/scripts/transact.py", "scripts/transact.py"),
            ("work/scripts/receipt.py", "scripts/receipt.py"),
            ("work/scripts/bootstrap.py", "scripts/bootstrap.py"),
            # The Datalinks text patch (helpx.txt / conceptsx.txt), applied by install.py on every run.
            ("work/scripts/patch_helptext.py", "scripts/patch_helptext.py"),
            # The Thinker Mod update (thinker-updater-design.md): detection, the verified download from the
            # author's own release, the settings merge, the backup / journal / swap, and the console flows.
            # thinker_data.py is compiled comparison data (setting names, stock values, hashes), not Thinker.
            ("work/scripts/thinker_flow.py", "scripts/thinker_flow.py"),
            ("work/scripts/thinker_state.py", "scripts/thinker_state.py"),
            ("work/scripts/thinker_source.py", "scripts/thinker_source.py"),
            ("work/scripts/thinker_update.py", "scripts/thinker_update.py"),
            ("work/scripts/thinker_ini.py", "scripts/thinker_ini.py"),
            ("work/scripts/thinker_data.py", "scripts/thinker_data.py"),
            # Removals under the game folder that never act through a junction or symlink.
            ("work/scripts/safe_fs.py", "scripts/safe_fs.py"),
            # The PRACX icon fix (Icons.pcx), applied by install.py on every run.
            ("work/scripts/patch_icons.py", "scripts/patch_icons.py"),
            # Wine / Proton: sets GOG's DDrawCompat ddraw.dll aside (it crashes the game under a ddraw override).
            ("work/scripts/wine_ddraw.py", "scripts/wine_ddraw.py"),
            # Public roots our hosts chain to, loaded by fetch.py beside the Windows store: a Windows 7 whose
            # store never met them cannot fetch anything otherwise (make_roots_pem.py).
            ("work/scripts/roots.pem", "scripts/roots.pem"),
            # NOT shipped, deliberately: sign_manifest.py (the private-key machinery),
            # release.py and hash_hd_pack.py (build tooling). test_release asserts their absence.
            ("work/patches/patches.yaml", "patches/patches.yaml"),
            ("work/patches/patches_prax.yaml", "patches/patches_prax.yaml"),
            ("work/CHANGELOG.md", "CHANGELOG.txt"),   # .txt: opens in Notepad on a stock Windows; .md opens in nothing
            ("src/uimod/build/Release/uimod.dll", "src/uimod/build/Release/uimod.dll"),
            # The update prompt's popup picture (200x120 8-bit PCX in the game's popup-art
            # format; generated by work/scripts/art/make_longevity_sm.py). Deployed beside the
            # exe by deploy_runtime; the DLL shows a text-only popup when it is absent.
            ("work/art/longevity_sm.pcx", "art/longevity_sm.pcx"),
            # PRACX 1.11's icon art only (CC0; work/art/pracx_icons_overlay-PROVENANCE.txt), for patch_icons.py.
            ("work/art/pracx_icons_overlay.pcx", "art/pracx_icons_overlay.pcx"),
            # The player's guide to replacement portraits; deploy_runtime places it in <game>\portraits\.
            ("work/art/portraits-README.txt", "portraits/LONGEVITY_PORTRAITS_README.txt"),
        ],
        "globs": [
            ("src/uimod/third_party/ffmpeg/bin", "*.dll",
             "src/uimod/third_party/ffmpeg/bin"),
        ],
        # NOT the raw tools/python tree. The shipped interpreter is the CURATED subset
        # staged by build_runtime.py -- see collect() -- which is 18 MB rather than 428.
        "trees": [],
    },
    "movies-hd": {
        "required": False,
        "files": [],
        # The provenance sidecar ships with the pack: it carries per-clip sha256 + size, which is
        # what lets the installer skip unchanged clips instead of recopying 1.3 GB every run.
        # Generate it with work\scripts\hash_hd_pack.py.
        # PROVENANCE.txt is the upscaler's credit and licence (a copy of work\art\movies-hd-PROVENANCE.txt):
        # _check_movie_pack refuses a pack without it, or with anything but the 61 clips beside it.
        "globs": [("dist/movies-hd", "*.mp4", "movies/hd"),
                  ("dist/movies-hd", "pack-manifest.json", "movies/hd"),
                  ("dist/movies-hd", "PROVENANCE.txt", "movies/hd")],
        "trees": [],
    },
    "portraits-hd": {
        "required": False,
        "files": [],
        # Built by work\scripts\art\build_portraits_hd.py.  It lands in portraits\hd ONLY: the player's own images
        # live in portraits\ (and fill in whatever the pack lacks), so the pack can never overwrite one.  Exactly the 14 leaders + the
        # manifest + the art's provenance/credit (_check_portrait_pack refuses anything else).
        "globs": [("dist/portraits-hd", "*.png", "portraits/hd"),
                  ("dist/portraits-hd", "pack-manifest.json", "portraits/hd"),
                  ("dist/portraits-hd", "PROVENANCE.txt", "portraits/hd")],
        "trees": [],
    },
}

def _root_launcher(name: str, purpose: str, failed: str, mode_args: str) -> str:
    """A launcher extracted at the archive root, so a player double-clicks one obvious thing.

    Kept CRLF, ASCII, and it guards its own target: a shim that silently does nothing when the
    payload is incomplete would defeat the installer's exit guarantee before Python is ever
    reached. The incomplete case jumps to a label instead of running inside a parenthesised
    block: the block's `endlocal ^& exit /b 9` made the `&` literal, so the exit never ran and
    the shim fell through to `call ""` (a stray "is not recognized" line and exit 1, not 9).

    `call` expands its line a second time, so a `%` or `^` in the extraction folder or in an
    argument was mangled ("100% done" -> path not found; `D:\\100% SMAC` -> `D:\\100 SMAC`). The
    call line therefore doubles its percent signs: the first pass leaves `%INNER%` / `%*` for
    call's own pass, which expands each exactly once. The incomplete branch honours --no-wait
    (and LONGEVITY_NO_WAIT) like run-install.bat does, so a scripted run never waits for a key.
    """
    return (
        "@echo off\r\n"
        f"REM Longevity Vaccine - {purpose} Extract the whole archive, then run this.\r\n"
        "setlocal\r\n"
        'set "INNER=%~dp0scripts\\run-install.bat"\r\n'
        'if not exist "%INNER%" goto :incomplete\r\n'
        f'call "%%INNER%%"{mode_args} %%*\r\n'
        "endlocal & exit /b %ERRORLEVEL%\r\n"
        ":incomplete\r\n"
        'set "NOWAIT="\r\n'
        'if defined LONGEVITY_NO_WAIT set "NOWAIT=1"\r\n'
        'echo %* | findstr /C:"--no-wait" >nul 2>&1 && set "NOWAIT=1"\r\n'
        "echo.\r\n"
        "echo  ============================================================\r\n"
        f"echo     {failed}\r\n"
        "echo  ============================================================\r\n"
        "echo  This archive is incomplete - scripts\\run-install.bat is missing.\r\n"
        "echo  Nothing on disk was changed.\r\n"
        "echo.\r\n"
        f"echo  What to do: extract the WHOLE archive before running {name} -- do not run it from inside the zip.\r\n"
        "echo.\r\n"
        "if not defined NOWAIT pause\r\n"
        "endlocal & exit /b 9\r\n"
    )


#: INSTALL.bat: the installer, exactly as run-install.bat with the player's own arguments.
_ROOT_LAUNCHER = _root_launcher("INSTALL.bat", "installer entry point.", "INSTALLATION FAILED", "")
#: UNINSTALL.bat: the same installer in its --uninstall mode (it asks for the game folder, like an install).
_ROOT_UNINSTALLER = _root_launcher("UNINSTALL.bat", "uninstaller entry point: removes the mod from a game folder.",
                                   "UNINSTALL FAILED", " --uninstall")
#: The files write_zip synthesises at the base archive's root (collect() lists them with no source).
_SYNTHESISED = {"INSTALL.bat": _ROOT_LAUNCHER, "UNINSTALL.bat": _ROOT_UNINSTALLER}


#: The file name a player actually downloads, per module.
#:
#: `base` IS the product, so it carries the product's name rather than an internal module id --
#: "base-0.1.0.zip" in a downloads folder tells the person who saved it nothing. The optional
#: packs keep their module id, which is what they are.
#:
#: One source of truth: the manifest URL, the staged file and every test all derive from
#: archive_name(). Nothing may spell a release file name out by hand -- except the website
#: (not in the public source), which can't import it; its own tests pin it to this table.
ARCHIVE_NAME = {
    "base": "LongevityVaccine_{version}.zip",
}
#: Optional packs carry an "LV-" prefix so they are identifiable in a downloads folder or
#: a releases list without being mistaken for the product itself -- "movies-hd-0.1.0.zip"
#: sitting next to somebody else's mod files says nothing about where it came from.
DEFAULT_ARCHIVE_NAME = "LV-{module}-{version}.zip"


def archive_name(module: str, version: str) -> str:
    return ARCHIVE_NAME.get(module, DEFAULT_ARCHIVE_NAME).format(
        module=module, version=version)


def sha256_file(p: Path, _buf: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(_buf), b""):
            h.update(chunk)
    return h.hexdigest()


#: The largest part of a split pack. GitHub refuses a release asset of 2 GiB or more (publish.GITHUB_ASSET_LIMIT);
#: 1 MiB under it. A pack archive larger than this is published as byte slices of itself (split_archive), listed
#: under the manifest entry's `parts` with no top-level `url` (manifest.module_parts says why). `base` is never split:
#: the 1.0.0 bootstrap fetches the new installer from `base.url` alone.
PART_MAX = 2 * 1024 ** 3 - (1 << 20)


#: The first release whose installer reads a split pack's `parts`. A 1.0.0 player reaches that code only while the
#: manifest's `latest` is newer than what they run: then generation 1 fetches the new installer first. At `latest`
#: 1.0.0 (a rollback), or with `latest` yanked, the 1.0.0 installer handles the pack itself and cannot read parts.
PARTS_SINCE = "1.0.1"


def parts_rollback_problem(doc: dict):
    """Why this manifest breaks the rollback rule (release-candidate skill), or None: it splits a pack while its
    `latest` is older than PARTS_SINCE or is yanked. release_all's verify step and publish.py both refuse it."""
    mods = doc.get("modules") if isinstance(doc, dict) else None
    split = sorted(n for n, i in (mods or {}).items() if isinstance(i, dict) and "parts" in i)
    if not split:
        return None
    latest = doc.get("latest")
    yanked = doc.get("yanked") if isinstance(doc.get("yanked"), list) else []
    norm = ver.normalise(latest) if isinstance(latest, str) and ver.is_valid(latest) else None
    if norm is None or not ver.at_least(norm, PARTS_SINCE):
        why = f"`latest` is {latest!r}, older than {PARTS_SINCE}"
    elif norm in [ver.normalise(v) for v in yanked if isinstance(v, str) and ver.is_valid(v)]:
        why = f"`latest` {norm} is yanked"
    else:
        return None
    return (f"the manifest splits {', '.join(split)} but {why}: a 1.0.0 player would then update in place with the "
            f"1.0.0 installer, which cannot read parts, and be offered the pack on every launch. What to do: keep "
            f"`latest` at {PARTS_SINCE} or later and not yanked, or roll the pack back to its last single-archive "
            f"release (the rollback rule in the release-candidate skill)")


def part_name(module: str, version: str, index: int) -> str:
    """The k-th (1-based) part of a split archive: `LV-movies-hd-2.0.0.zip.001`, 7-Zip's split-volume naming."""
    return f"{archive_name(module, version)}.{index:03d}"


def plan_slices(size: int, part_max: int = None) -> list:
    """The part lengths of a `size`-byte archive: [] when it fits one asset, else the fewest parts under `part_max`,
    of equal length but the last (which may be a few bytes shorter). A pure function of the size, so the same archive
    is always cut the same way."""
    part_max = PART_MAX if part_max is None else part_max
    if size <= part_max:
        return []
    n = -(-size // part_max)
    q = -(-size // n)
    return [q] * (n - 1) + [size - q * (n - 1)]


def hash_parts(paths) -> tuple:
    """(each part's sha256, the sha256 of the parts joined in order), in one read of every part."""
    whole, each = hashlib.sha256(), []
    for p in paths:
        h = hashlib.sha256()
        with Path(p).open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
                whole.update(chunk)
        each.append(h.hexdigest())
    return each, whole.hexdigest()


def _part_files(archive: Path) -> list:
    """Every `<archive>.NNN` beside `archive`, in no particular order."""
    return [p for p in archive.parent.glob(archive.name + ".*")
            if len(p.suffix) == 4 and p.suffix[1:].isdigit() and p.is_file()]


def _part_temps(archive: Path) -> list:
    """Every `<archive>.NNN.tmp` an interrupted split left beside `archive`."""
    return [p for p in archive.parent.glob(archive.name + ".*.tmp")
            if len(p.stem.rsplit(".", 1)[-1]) == 3 and p.stem.rsplit(".", 1)[-1].isdigit() and p.is_file()]


def check_base_fits(archive: Path) -> None:
    """The base archive is ONE release asset: the 1.0.0 bootstrap fetches the new installer from `base.url` alone."""
    size = Path(archive).stat().st_size
    if plan_slices(size):
        raise SystemExit(f"REFUSING: {Path(archive).name} is {size:,} bytes, over one release asset "
                         f"({PART_MAX:,} bytes), and the base can never be split: the 1.0.0 bootstrap fetches it from "
                         "one URL. What to do: find what grew the base archive (the runtime, a pack folder swept in) "
                         "and take it out.")


def split_archive(archive: Path, module: str, version: str, part_max: int = None) -> list:
    """Cut `archive` into its parts beside it (plan_slices; part_name), or remove stale parts when it fits one asset.
    Returns [{"path", "size", "sha256"}] in order ([] when not split).

    Deterministic: the archive is (write_zip), and the cut is a pure function of its size. A part already on disk with
    the right bytes is kept; a wrong one is rewritten through a temp file; a part beyond the current cut is deleted, so
    a dist never holds a stale `.004` from an earlier, larger archive."""
    archive = Path(archive)
    sizes = plan_slices(archive.stat().st_size, part_max)
    import manifest as mfmod
    if len(sizes) > mfmod.MAX_PARTS:
        raise SystemExit(f"REFUSING to split {archive.name}: it would take {len(sizes)} parts and a manifest may list "
                         f"at most {mfmod.MAX_PARTS} (manifest.MAX_PARTS). What to do: make the pack smaller, or "
                         "raise MAX_PARTS in a release whose clients all read the larger limit.")
    keep = {archive.with_name(part_name(module, version, i)).name for i in range(1, len(sizes) + 1)}
    for p in _part_files(archive):
        if p.name not in keep:
            p.unlink()
    for p in _part_temps(archive):
        p.unlink()                          # an interrupted split's leftover: never a part, often 1.6 GB
    out = []
    with archive.open("rb") as src:
        for i, n in enumerate(sizes, 1):
            dest = archive.with_name(part_name(module, version, i))
            h = hashlib.sha256()
            left = n
            while left:
                chunk = src.read(min(1 << 20, left))
                if not chunk:
                    raise SystemExit(f"{archive.name} changed while it was being split")
                h.update(chunk)
                left -= len(chunk)
            digest = h.hexdigest()
            if not (dest.is_file() and dest.stat().st_size == n and sha256_file(dest) == digest):
                # Gone BEFORE the rewrite: a run stopped mid-write must not leave the old bytes under the final name.
                dest.unlink(missing_ok=True)
                tmp = dest.with_name(dest.name + ".tmp")
                with archive.open("rb") as again, tmp.open("wb") as w:
                    again.seek(sum(sizes[:i - 1]))
                    left = n
                    while left:
                        chunk = again.read(min(1 << 20, left))
                        w.write(chunk)
                        left -= len(chunk)
                if sha256_file(tmp) != digest:
                    tmp.unlink()
                    raise SystemExit(f"{archive.name} changed while it was being split")
                tmp.replace(dest)
            out.append({"path": str(dest), "size": n, "sha256": digest})
    return out


#: Where build_runtime.py stages the shipped interpreter.
RUNTIME_DIR = _REPO / "work" / "build" / "runtime"
#: The Windows 7 / 8 interpreter (CPython 3.8.10 + app-local UCRT + the pure-Python pefile/yaml), staged by
#: the same build_runtime.py run and shipped as tools/python38 beside tools/python. The SAME scripts run on
#: it, so it is verified (probe + the whole installer flow under 3.8) and stale-checked exactly like 3.12.
RUNTIME38_DIR = _REPO / "work" / "build" / "runtime38"
#: (staged dir, where it lands in the payload) for both interpreters: everything that walks "the runtime"
#: walks this.
RUNTIMES = ((RUNTIME_DIR, "tools/python"), (RUNTIME38_DIR, "tools/python38"))


def runtime_root() -> Path:
    """The staged 3.12 runtime's root, or an explained refusal. Requires BOTH interpreters (a release
    without tools/python38 leaves every Windows 7 / 8 player with an installer that cannot start);
    callers that pack walk RUNTIMES, not the returned root.

    Deliberately NOT built on demand here: staging is driven by a measured import trace, and a
    release that silently regenerated that trace from whatever happened to be installed would be
    exactly the unreviewable step this whole approach exists to avoid. Build it explicitly, look
    at what changed, then package.
    """
    for root, dst in RUNTIMES:
        if not (root / "python.exe").is_file():
            raise FileNotFoundError(
                f"no staged runtime at {root} ({dst}). Build it first:\n"
                f"    py work\\scripts\\fetch_python38.py          (once per clone: tools\\python38)\n"
                f"    py work\\scripts\\trace_imports.py --out work\\build\\import-trace.json\n"
                f"    py work\\scripts\\build_runtime.py --out work\\build\\runtime --verify")
    problem = runtime_stale()
    if problem:
        print(f"  WARNING: {problem}\n"
              "  If an import moved, the trimmed interpreter may be missing a module. Re-run\n"
              "  trace_imports.py + build_runtime.py --verify to be sure.")
    return RUNTIME_DIR


def runtime_stale(root: Path = None) -> str:
    """Why the staged runtime cannot be trusted as-is, or "" when it can. A warning here in a
    developer's run; a REFUSAL in release_all.py (--skip-runtime, dist_stale). With no `root`,
    BOTH staged interpreters are checked and the first problem names its runtime."""
    if root is None:
        for r, dst in RUNTIMES:
            problem = runtime_stale(r)
            if problem:
                return f"{dst}: {problem}"
        return ""
    root = Path(root)
    # Only the SHIPPED .py files matter: "could an import have moved?" is the question, and a
    # .bat, a .yaml or release.py itself (which never runs on a player's machine) cannot move
    # one. A warning that fires when nothing is wrong is one people learn to ignore.
    newest, newest_name = 0.0, None
    for src, _dst in MODULE_SPEC["base"]["files"]:
        f = _REPO / src
        if f.suffix == ".py" and f.is_file() and f.stat().st_mtime > newest:
            newest, newest_name = f.stat().st_mtime, src
    # The build STAMP, not a file mtime: build_runtime stages with copy2, which preserves the
    # source timestamps, so python.exe carries tools\python's date.
    try:
        staged = float((root / ".staged-at").read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return "the staged runtime carries no .staged-at stamp"
    if newest > staged:
        return f"{newest_name} changed after the runtime was staged"
    # build_runtime --verify writes .verified-at AFTER the probes pass; a runtime that was
    # staged and then failed verification has the stamp but not the marker.
    try:
        verified = float((root / ".verified-at").read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return "the staged runtime was never verified (run build_runtime.py --verify)"
    if verified < staged:
        return "the staged runtime was re-staged after its last verification"
    return ""


def _check_portrait_pack(d: Path) -> None:
    """The portraits-hd folder is exactly what build_portraits_hd.py writes, unchanged since: the 14 leader images,
    pack-manifest.json and PROVENANCE.txt (the artist's credit), every image matching its manifest sha256/size.
    A stray file (Thumbs.db, a test image) or a hand-edited image would otherwise ship under the signed manifest."""
    import json
    sys.path.insert(0, str(_REPO / "work" / "scripts" / "art"))
    import build_portraits_hd as bph
    want = {f"{n}.png" for n in bph.LEADERS.values()} | {bph.MANIFEST, bph.PROVENANCE}
    have = {p.name for p in d.iterdir() if p.is_file()}
    if have != want:
        extra, missing = sorted(have - want), sorted(want - have)
        raise ValueError(f"portraits-hd: {d} is not the built pack"
                         + (f"; unexpected {extra}" if extra else "") + (f"; missing {missing}" if missing else "")
                         + " (rebuild it with work\\scripts\\art\\build_portraits_hd.py)")
    doc = json.loads((d / bph.MANIFEST).read_text(encoding="utf-8"))
    files = {f["name"]: f for f in doc.get("files", [])}
    if set(files) != {f"{n}.png" for n in bph.LEADERS.values()}:
        raise ValueError(f"portraits-hd: {bph.MANIFEST} does not list exactly the 14 leaders")
    for name, f in files.items():
        p = d / name
        if p.stat().st_size != f.get("size") or bph.sha256_file(p) != f.get("sha256"):
            raise ValueError(f"portraits-hd: {name} does not match {bph.MANIFEST} (edited after the build?)")
    _check_portrait_provenance((d / bph.PROVENANCE).read_bytes(), bph.PROVENANCE)


#: The tracked provenance every shipped pack must carry, word for word: the artist's credit and the licence as the
#: artist confirmed it (2026-11-06). A pack built from an older text (the provisional licence) never ships.
_PORTRAIT_PROVENANCE = _REPO / "work" / "art" / "portraits-hd-PROVENANCE.txt"


def _check_portrait_provenance(data: bytes, name: str) -> None:
    text = data.decode("utf-8", errors="replace")
    for must in ("Turovetsky", "https://www.youtube.com/@Turovetsky", "https://x.com/turovetsky"):
        if must not in text:
            raise ValueError(f"portraits-hd: {name} lacks the artist's required credit ({must})")
    want = _PORTRAIT_PROVENANCE.read_text(encoding="utf-8")
    if text.replace("\r\n", "\n") != want.replace("\r\n", "\n"):
        raise ValueError(f"portraits-hd: {name} is not work\\art\\portraits-hd-PROVENANCE.txt (built from an older "
                         "text? rebuild the pack: work\\scripts\\art\\build_portraits_hd.py --provenance "
                         "work\\art\\portraits-hd-PROVENANCE.txt)")


def _check_reused_portrait_pack(archive: Path, mver: str) -> None:
    """An existing LV-portraits-hd-<v>.zip is reused unbuilt.  If dist\\portraits-hd was rebuilt since (another crop,
    another image, an edited PROVENANCE) the old zip would silently ship under the signed manifest: refuse instead,
    member by member (CRC32 + size), unless the folder is absent (a machine without the pack source).  Whatever
    the folder holds, the archive's own PROVENANCE.txt must be the current tracked one (credit + confirmed licence)."""
    import zlib
    with zipfile.ZipFile(archive) as z:
        members = {Path(i.filename).name: (i.CRC, i.file_size) for i in z.infolist() if not i.is_dir()}
        prov = next((i for i in z.infolist() if Path(i.filename).name == "PROVENANCE.txt"), None)
        if prov is None:
            raise SystemExit(f"REFUSING to reuse {archive.name}: it carries no PROVENANCE.txt (the artist's credit)")
        try:
            _check_portrait_provenance(z.read(prov), f"{archive.name}:PROVENANCE.txt")
        except ValueError as e:
            raise SystemExit(f"REFUSING to reuse {archive.name}: {e}. Bump MODULE_VERSIONS['portraits-hd'] in "
                             f"version.py (a published archive name is immutable).")
    d = _REPO / "dist" / "portraits-hd"
    if not d.is_dir():
        return
    if "pack-manifest.json" not in members:
        return      # not an archive built from a pack folder (every real one carries the manifest): nothing to compare
    current = {}
    for p in sorted(d.iterdir()):
        if p.is_file():
            current[p.name] = (zlib.crc32(p.read_bytes()) & 0xFFFFFFFF, p.stat().st_size)
    if members != current:
        changed = sorted(set(members) ^ set(current) | {n for n in members if n in current and members[n] != current[n]})
        raise SystemExit(f"REFUSING to reuse {archive.name}: dist\\portraits-hd changed since v{mver} was built "
                         f"({', '.join(changed[:6])}{'...' if len(changed) > 6 else ''}). Bump MODULE_VERSIONS"
                         f"['portraits-hd'] in version.py (a published archive name is immutable).")


#: The tracked credit + licence every shipped cinematics pack carries as movies\hd\PROVENANCE.txt, word for word.
_MOVIE_PROVENANCE = _REPO / "work" / "art" / "movies-hd-PROVENANCE.txt"
_MOVIE_CREDIT = ("Z2k Retro", "https://www.youtube.com/@Z2KRetroGaming", "https://www.youtube.com/@Z2kRetroVideo")


def _check_movie_provenance(data: bytes, name: str) -> None:
    text = data.decode("utf-8", errors="replace")
    for must in _MOVIE_CREDIT:
        if must not in text:
            raise ValueError(f"movies-hd: {name} lacks the upscaler's required credit ({must})")
    want = _MOVIE_PROVENANCE.read_text(encoding="utf-8")
    if text.replace("\r\n", "\n") != want.replace("\r\n", "\n"):
        raise ValueError(f"movies-hd: {name} is not work\\art\\movies-hd-PROVENANCE.txt (copy the tracked file "
                         "into the pack folder)")


def _check_movie_pack(d: Path) -> None:
    """dist\\movies-hd is exactly a shippable pack: one <name>.mp4 per game movie (hash_hd_pack.MOVIE_CLIPS, exact
    case), the pack-manifest.json sidecar listing exactly those clips with matching size and sha256, and
    PROVENANCE.txt identical to the tracked credit + licence. The game looks clips up by name, so a misspelt or
    missing clip would silently play the original movie; a stray file (Thumbs.db, a test encode) would ship under
    the signed manifest."""
    import json
    import hash_hd_pack as hhp
    clips = {f"{n}.mp4" for n in hhp.MOVIE_CLIPS}
    want = clips | {hhp.SIDECAR_NAME, "PROVENANCE.txt"}
    have = {p.name for p in d.iterdir()}
    if have != want:
        extra, missing = sorted(have - want), sorted(want - have)
        raise ValueError(f"movies-hd: {d} is not a shippable pack"
                         + (f"; unexpected {extra[:8]}" if extra else "") + (f"; missing {missing[:8]}" if missing else "")
                         + " (one <movie>.mp4 per game movie, exact names, plus pack-manifest.json and PROVENANCE.txt)")
    doc = json.loads((d / hhp.SIDECAR_NAME).read_text(encoding="utf-8"))
    recorded = {c.get("name"): c for c in doc.get("clips", [])}
    if set(recorded) != clips or doc.get("clip_count") != len(clips):
        raise ValueError(f"movies-hd: {hhp.SIDECAR_NAME} does not list exactly the {len(clips)} clips "
                         "(re-run work\\scripts\\hash_hd_pack.py)")
    for name, c in sorted(recorded.items()):
        p = d / name
        if p.stat().st_size != c.get("size") or hhp.sha256_file(p) != c.get("sha256"):
            raise ValueError(f"movies-hd: {name} does not match {hhp.SIDECAR_NAME} (changed after it was hashed? "
                             "re-run work\\scripts\\hash_hd_pack.py)")
    _check_movie_provenance((d / "PROVENANCE.txt").read_bytes(), "PROVENANCE.txt")


def _check_reused_movie_pack(archive: Path, mver: str) -> None:
    """An existing LV-movies-hd-<v>.zip is reused unbuilt: it must carry the current tracked PROVENANCE.txt (the
    upscaler's credit + licence). An archive from before the credit -- the Real-ESRGAN pack -- never ships again
    under a new manifest; bump MODULE_VERSIONS['movies-hd'] to build the current pack."""
    with zipfile.ZipFile(archive) as z:
        prov = next((i for i in z.infolist() if Path(i.filename).name == "PROVENANCE.txt"), None)
        if prov is None:
            raise SystemExit(f"REFUSING to reuse {archive.name}: it carries no PROVENANCE.txt (the upscaler's credit). "
                             "Bump MODULE_VERSIONS['movies-hd'] in version.py (a published archive name is immutable).")
        try:
            _check_movie_provenance(z.read(prov), f"{archive.name}:PROVENANCE.txt")
        except ValueError as e:
            raise SystemExit(f"REFUSING to reuse {archive.name}: {e}. Bump MODULE_VERSIONS['movies-hd'] in "
                             f"version.py (a published archive name is immutable).")


def _check_pack_archive_compiled(archive: Path, name: str) -> None:
    """The pack archive about to go into the manifest -- built now or reused -- carries exactly the pack-manifest.json
    and PROVENANCE.txt whose sha256 the installer compiles in (version.PACK_MANIFEST_SHA256 /
    PACK_PROVENANCE_SHA256). Otherwise every player who has the pack would see it as another release: never adopted,
    and a kept copy repaired by downloading the whole archive again (audit-o 2026-11-17: a dist re-hash after the
    archive was built could leave the two apart)."""
    want = {"pack-manifest.json": ver.PACK_MANIFEST_SHA256.get(name),
            "PROVENANCE.txt": ver.PACK_PROVENANCE_SHA256.get(name)}
    # The exact archive paths the installer reads (audit-p LOW-2): movies/hd/... or portraits/hd/..., once each. A copy
    # anywhere else -- nested, at the archive root, under the other pack's folder -- or a second copy is refused.
    root = next(dst for _src, pat, dst in MODULE_SPEC[name]["globs"] if pat == "pack-manifest.json")
    # Windows ignores case and a trailing dot or space (audit-q L4): any such variant is the same name, so it must be
    # exactly the one path, once.
    canon = {k.lower(): k for k in want}
    got = {}
    with zipfile.ZipFile(archive) as z:
        for i in z.infolist():
            base = canon.get(i.filename.replace("\\", "/").rsplit("/", 1)[-1].rstrip(" .").lower())
            if base is None or i.is_dir():
                continue
            if i.filename != f"{root}/{base}" or base in got:
                raise SystemExit(f"REFUSING to ship {archive.name}: it carries {i.filename}"
                                 + (" twice" if base in got else f", not exactly {root}/{base}")
                                 + " (rebuild the archive from the pack folder).")
            got[base] = hashlib.sha256(z.read(i)).hexdigest()
    for base, sha in want.items():
        if not sha or got.get(base) != sha:
            raise SystemExit(
                f"REFUSING to ship {archive.name}: its {base} "
                + ("is missing" if base not in got else "is not the one version.py compiles in")
                + f" (version.{'PACK_MANIFEST_SHA256' if base == 'pack-manifest.json' else 'PACK_PROVENANCE_SHA256'}"
                f"[{name!r}]). Update version.py from dist\\{name}\\{base} (test_audit_n / test_audit_o pin it to "
                "dist), or rebuild the archive from the pack the installer was built for.")


def collect(module: str, include_python: bool) -> list[tuple[Path, str]]:
    """Resolve a module spec into concrete (source file, archive path) pairs."""
    spec = MODULE_SPEC[module]
    out: list[tuple[Path, str]] = []

    for src, dst in spec["files"]:
        p = _REPO / src
        if not p.is_file():
            raise FileNotFoundError(f"{module}: missing required file {p}")
        out.append((p, dst))

    for src_dir, pattern, dst_dir in spec["globs"]:
        d = _REPO / src_dir
        if not d.is_dir():
            if spec["required"]:
                raise FileNotFoundError(f"{module}: missing required dir {d}")
            continue
        for p in sorted(d.glob(pattern)):
            if p.is_file():
                out.append((p, f"{dst_dir}/{p.name}"))

    if module == "portraits-hd" and out:
        _check_portrait_pack(_REPO / "dist" / "portraits-hd")
    elif module == "movies-hd" and out:
        _check_movie_pack(_REPO / "dist" / "movies-hd")

    for src_dir, dst_dir in spec["trees"]:
        d = _REPO / src_dir
        if not d.is_dir():
            raise FileNotFoundError(f"{module}: missing required tree {d}")
        for p in sorted(d.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                out.append((p, f"{dst_dir}/{p.relative_to(d).as_posix()}"))

    if include_python and module == "base":
        # The SHIPPED interpreter is a curated subset, not the developer's tree.
        #
        # Shipping tools/python wholesale meant a 428 MB base module -- ~96% of it developer
        # tooling (frida, numpy, PIL, pip, pytest, capstone, ...) and parts of CPython the
        # installer never touches -- and, because the installer is resident, the player paid for
        # it twice. It also forced the DEVELOPER to uninstall their own tools before they could
        # cut a release, which is a hostile thing to require and an easy thing to forget.
        runtime_root()                     # both staged, or an explained refusal
        for runtime, dst_dir in RUNTIMES:  # tools/python (3.12) and tools/python38 (Windows 7 / 8)
            for p in sorted(runtime.rglob("*")):
                # .staged-at and .verified-at are BUILD stamps that change every time the runtime is
                # staged or verified, so packing them would make every rebuild produce a different
                # sha256 and destroy the reproducible-zip guarantee this module is built around.
                if p.is_file() and "__pycache__" not in p.parts \
                        and p.name not in (".staged-at", ".verified-at"):
                    out.append((p, f"{dst_dir}/{p.relative_to(runtime).as_posix()}"))

    if module == "base":
        out.extend((None, name) for name in _SYNTHESISED)   # synthesised, see write_zip
        # The payload's own file list (bootstrap.INVENTORY_REL), computed from the entries above by write_zip: the
        # list generation 2 completes a staged payload against, whatever list an older generation 1 copied with.
        out.append((None, bs.INVENTORY_REL))
    return out


def write_zip(entries: list[tuple[Path, str]], dest: Path) -> None:
    """Write a byte-for-byte reproducible zip.

    Sorted entries + a fixed timestamp + no external attrs: the same inputs must always hash the
    same, or every rebuild looks like a new release.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    # Level 9, not 6: ~45 KB smaller for nothing but build time, and the level is
    # deterministic so the reproducible-zip guarantee is unaffected. DEFLATE specifically --
    # the base archive is extracted by a human with Windows Explorer, which cannot read LZMA
    # or bzip2 zip entries and would fail or silently skip them.
    # The base carries its payload's file list (bootstrap.INVENTORY_REL). Its bytes are read ONCE and the list is
    # made from exactly the bytes written: a file that changed between a hashing pass and a writing pass (an
    # editor save, a rebuilt DLL) would ship a list its own archive contradicts -- and every update would refuse
    # it (audit 2026-11-19, M2). ~47 MB held for the base only; a pack streams one file at a time as before.
    listed = any(src is None and arc == bs.INVENTORY_REL for src, arc in entries)
    blobs = {arc: _entry_bytes(src, arc) for src, arc in entries if arc != bs.INVENTORY_REL} if listed else {}
    if listed:
        blobs[bs.INVENTORY_REL] = bs.make_inventory(blobs.items())
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for src, arc in sorted(entries, key=lambda e: e[1]):
            info = zipfile.ZipInfo(arc, date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 0
            z.writestr(info, blobs[arc] if listed else _entry_bytes(src, arc))
    tmp.replace(dest)
    if listed:
        problem = inventory_problem(dest)
        if problem:
            dest.unlink()
            raise SystemExit(f"REFUSING to ship {dest.name}: {problem}")


def _entry_bytes(src, arc: str) -> bytes:
    return _SYNTHESISED[arc].encode("ascii") if src is None else src.read_bytes()


def inventory_problem(archive: Path):
    """What is wrong with a base archive's payload file list, read back from the archive itself; None when it is
    exactly every member but the root launchers, each with its true hash and size, and no bytecode (swap_in
    never copies bytecode, so a listed .pyc could never be made resident)."""
    import hashlib
    with zipfile.ZipFile(archive) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        if bs.INVENTORY_REL not in names:
            return "it has no payload file list"
        try:
            inv = bs.parse_inventory(z.read(bs.INVENTORY_REL))
        except OSError as e:
            return str(e)
        want = {n for n in names if n not in bs.ROOT_ONLY and n != bs.INVENTORY_REL}
        if set(inv) != want:
            return (f"its file list and its members differ (listed only: {sorted(set(inv) - want)[:3]}, "
                    f"members only: {sorted(want - set(inv))[:3]})")
        for n in sorted(want):
            data = z.read(n)
            if inv[n] != (hashlib.sha256(data).hexdigest(), len(data)):
                return f"{n} does not match its entry in the file list"
        pyc = [n for n in want if bs._is_bytecode(n)]
        if pyc:
            return f"it ships Python bytecode ({', '.join(sorted(pyc)[:3])})"
    return None


def check_dev_only_packages(root: Path = None) -> list[str]:
    """Developer packages must never ship. Returns the offenders found.

    Checks the STAGED runtime by default, not the developer's interpreter. Pointing this at
    tools/python made the check a demand that the developer uninstall frida, numpy, pytest and
    the rest before cutting a release -- which is both hostile and beside the point, since what
    matters is only what ends up in the archive.
    """
    if root is None:                     # both staged interpreters ship: check both
        found = set()
        for r, _dst in RUNTIMES:
            found.update(check_dev_only_packages(r))
        return sorted(found)
    sp = Path(root) / "Lib" / "site-packages"
    if not sp.is_dir():
        return []
    found = set()
    for entry in sp.iterdir():
        name = entry.name
        if name.endswith(".dist-info") or name == "__pycache__":
            continue
        stem = name.split("-")[0]
        for dev in DEV_ONLY:
            if stem == dev or name == dev or stem.lower() == dev.lower():
                found.add(name)
    return sorted(found)


def run_gate() -> None:
    """Refuse to package unless the L1 locks and the new unit suites pass.

    .githooks\\pre-commit runs `-k scaling` only, which does NOT match test_apply_md5.py or
    test_patch_integrity.py -- so a patches.yaml change that moves the build MD5 can be committed
    with the lock unchecked. A release must not inherit that gap.
    """
    # The installer/updater suites too: a release_all.py run gates on the WHOLE suite and passes
    # --skip-gate here, but a direct release.py run used to package with none of the update
    # machinery tested at all.
    files = ["test_patch_integrity.py", "test_apply_md5.py", "test_targets.py",
             "test_version_sync.py", "test_installer_exit.py", "test_manifest.py",
             "test_bootstrap.py", "test_check.py", "test_preflight.py"]
    print("--- release gate ---")
    cmd = [str(_PY), "-m", "pytest", *files, "-q", "-p", "no:cacheprovider"]
    r = subprocess.run(cmd, cwd=str(_TESTS))
    if r.returncode != 0:
        raise SystemExit("release gate FAILED -- refusing to package. Fix the tests above.")
    print("  gate passed\n")


#: Where archives are published (`--base-url` / `--pack-url` defaults). The website (not in the
#: public source) hard-codes this prefix for its download button, so moving it means changing
#: the site too; the website's own tests fail until they agree.
BASE_URL = "https://github.com/BoltActionBalrog/longevity-vaccine/releases/download/v{version}"
PACK_URL = "https://github.com/BoltActionBalrog/longevity-vaccine/releases/download/{module}-v{version}"


def module_url(name: str, mver: str, base_url: str, pack_url: str) -> str:
    """Where a module's archive is published. `base` lives under the product's release tag; each
    pack version is its OWN release tag, uploaded once and immutable across product releases."""
    tmpl = base_url if name == "base" else pack_url
    return f"{tmpl.format(module=name, version=mver).rstrip('/')}/{archive_name(name, mver)}"


def part_url(name: str, mver: str, index: int, base_url: str, pack_url: str) -> str:
    """Where the `index`-th part of a split archive is published: beside where the whole one would be."""
    return module_url(name, mver, base_url, pack_url).rsplit("/", 1)[0] + "/" + part_name(name, mver, index)


def _issued() -> int:
    """The manifest's `issued`: the commit time of the tree being released, so a dry run and the real run build
    the same manifest (deterministic release scripts) while every later release, kill switch or rollback,
    built from a later commit, is newer."""
    import subprocess
    try:
        # The checkout these scripts run from (the release always runs from one); not _PATCHES, which a
        # packaging test points at a scratch tree outside git.
        out = subprocess.run(["git", "-C", str(Path(__file__).resolve().parent), "log", "-1", "--format=%ct"],
                             capture_output=True, text=True, timeout=30).stdout.strip()
        return int(out)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        # Never 0: a manifest dated 0 is refused by every client that has seen a later one.
        raise RuntimeError(f"cannot date the manifest from git ({e}); run the release from a checkout") from e


def _module_entry(name: str, info: dict, base_url: str, pack_url: str) -> dict:
    """One `modules` entry. A split archive (`info["parts"]`, split_archive) lists its parts and has NO top-level
    `url`: the 1.0.0 installer must not see a URL it would fetch whole (manifest.module_parts). Its `size` and
    `sha256` stay the whole archive's -- `size` is what every client's update offer and free-space check read."""
    entry = {"version": info["version"], "required": MODULE_SPEC[name]["required"]}
    parts = info.get("parts") or []
    if parts and name == "base":
        raise SystemExit("REFUSING to split the base archive: the 1.0.0 bootstrap fetches the new installer from "
                         "`base.url` alone, so a split base strands every 1.0.0 player.")
    if not parts:
        entry["url"] = module_url(name, info["version"], base_url, pack_url)
    entry["sha256"] = info["sha256"]
    entry["size"] = info["size"]
    if parts:
        entry["parts"] = [{"url": part_url(name, info["version"], i, base_url, pack_url),
                           "sha256": p["sha256"], "size": p["size"]} for i, p in enumerate(parts, 1)]
    return entry


def build_manifest(version: str, modules: dict, base_url: str,
                   pack_url: str = None) -> dict:
    """`modules` is name -> {version, sha256, size[, parts]} for EVERY module that has an artifact --
    built now or reused from a previous build. A manifest that omitted a module the player has
    installed would read as "dropped"; one that omitted `base` is rejected by the preflight."""
    import yaml
    # The C loader: same 9x on the same 1.78 MB file (see apply_patches._yaml_load).
    import apply_patches as _ap
    spec = _ap._yaml_load(_PATCHES.read_text(encoding="utf-8"))
    targets = {}
    for tid, t in (spec.get("targets") or {}).items():
        if not t.get("launch") or t.get("pending") or not t.get("base_md5"):
            continue
        entry = {"base_md5": t["base_md5"], "patched_md5": t.get("patched_md5")}
        if t.get("companion"):
            entry["companion"] = {
                k: {"base_md5": v.get("base_md5"), "patched_md5": v.get("patched_md5")}
                for k, v in t["companion"].items()}
        targets[tid] = entry

    return {
        "schema": 1,
        "protocol": 1,
        "product": "longevity-vaccine",
        "latest": version,
        # NOT `version`: that made every existing install "too old" on every release.
        "min_upgradable_from": ver.MIN_UPGRADABLE_FROM,
        "manual_install_required": False,
        "manual_install_reason": None,
        "unsupported_versions": [],
        "unsupported_targets": [],
        "targets": targets,
        "min_free_bytes": 3 * 1024 ** 3,
        "modules": {name: _module_entry(name, info, base_url, pack_url or base_url)
                    for name, info in modules.items()},
        "yanked": [],
        "notes_url": __import__("manifest").CHANGELOG_URL,
        # Monotonic across every build (thinker-updater-design.md section 9): a client refuses the Thinker
        # data of a manifest older than one it has seen. A rebuilt kill switch or rollback is newer.
        "issued": _issued(),
        "thinker": __import__("thinker_flow").manifest_section(version),
    }


def main() -> int:
    apr = argparse.ArgumentParser(description="Build the Longevity Vaccine release artifacts.")
    apr.add_argument("--version", default=ver.VERSION,
                     help=f"release version (default: version.py = {ver.VERSION})")
    apr.add_argument("--out", default=str(_REPO / "dist" / "release"))
    apr.add_argument("--modules", default="base",
                     help="Comma-separated modules to BUILD (default: base). A module not named "
                          "is reused from its existing archive when there is one, so `--modules "
                          "movies-hd` is a pack-only release and a bare run is a product release "
                          "that carries the packs along unchanged. Pack versions come from "
                          "version.py MODULE_VERSIONS; bump one there to release it.")
    apr.add_argument("--rebuild", action="store_true",
                     help="build the named modules even when their archive already exists -- "
                          "only for an UNPUBLISHED version; a published pack must get a new "
                          "version in version.py instead, its archive name is immutable")
    apr.add_argument("--no-python", action="store_true",
                     help="omit tools/python from the base module (fast dev builds only -- the "
                          "result is NOT installable)")
    apr.add_argument("--allow-untrimmed", action="store_true",
                     help="package even though developer-only packages are present")
    apr.add_argument("--skip-gate", action="store_true", help="skip the test gate (not for a real release)")
    apr.add_argument("--sign-key", default=None, metavar="PATH",
                     help="sign the manifest with this Ed25519 key (see sign_manifest.py "
                          "--keygen). Without it the manifest is UNSIGNED and unpublishable.")
    apr.add_argument("--base-url", default=BASE_URL,
                     help="where the product archive is published ({version} = product)")
    apr.add_argument("--pack-url", default=PACK_URL,
                     help="where a pack archive is published ({module}, {version} = the PACK's "
                          "version): one release tag per pack version, immutable")
    args = apr.parse_args()

    if not ver.is_valid(args.version):
        raise SystemExit(f"--version {args.version!r} is not MAJOR.MINOR.PATCH")
    if args.version != ver.VERSION:
        raise SystemExit(
            f"--version {args.version} disagrees with work/scripts/version.py ({ver.VERSION}). "
            "Bump version.py (and src/uimod/src/version.h) instead of overriding here.")

    for name, mver in ver.MODULE_VERSIONS.items():
        if not ver.is_valid(mver):
            raise SystemExit(f"version.py MODULE_VERSIONS[{name!r}] = {mver!r} is not "
                             "MAJOR.MINOR.PATCH")
    if not ver.is_valid(ver.MIN_UPGRADABLE_FROM):
        raise SystemExit("version.py MIN_UPGRADABLE_FROM is not MAJOR.MINOR.PATCH")
    packs = set(MODULE_SPEC) - {"base"}
    if set(ver.MODULE_VERSIONS) != packs:
        raise SystemExit(f"version.py MODULE_VERSIONS names {sorted(ver.MODULE_VERSIONS)} but "
                         f"release.py MODULE_SPEC packages {sorted(packs)}; make them agree")
    if args.no_python and args.sign_key:
        # Allowed (the signing tests need it) but never publishable: the .no-python marker
        # written beside the archive makes release_all.verify_output and publish.read_release
        # refuse it.
        print("WARNING: signing a --no-python build. It is NOT installable and cannot be "
              "published; the archive is marked so publish.py refuses it.\n")

    include_python = not args.no_python
    offenders = check_dev_only_packages()
    if offenders and include_python:
        where = ", ".join(str(r) for r, _d in RUNTIMES if check_dev_only_packages(r))
        msg = (f"developer-only packages are in the STAGED runtime ({where}):\n  "
               + ", ".join(offenders)
               + "\nThe shipped set is pyyaml + pefile only. Re-stage with build_runtime.py.")
        if not args.allow_untrimmed:
            raise SystemExit("REFUSING to package: " + msg)
        print("WARNING: " + msg + "\n")

    if not args.skip_gate:
        run_gate()

    out_dir = Path(args.out) / args.version          # the product archive + its manifest
    pack_dir = Path(args.out) / "modules"            # pack archives, named for THEIR version,
    out_dir.mkdir(parents=True, exist_ok=True)       # so they survive across product releases
    wanted = [m.strip() for m in args.modules.split(",") if m.strip()]
    for name in wanted:
        if name not in MODULE_SPEC:
            raise SystemExit(f"unknown module {name!r}")

    # Every module with an artifact goes in the manifest: the ones named are (re)built, the rest
    # are reused from the archive a previous run left. Reuse is safe because the zips are
    # deterministic -- a rebuild of unchanged inputs is byte-identical -- and it is what makes a
    # pack-only release possible without re-packing the product, or vice versa.
    built: dict[str, dict] = {}
    for name in MODULE_SPEC:
        mver = ver.module_version(name)
        dest = (out_dir if name == "base" else pack_dir) / archive_name(name, mver)
        if name in wanted and (args.rebuild or not dest.is_file() or name == "base"):
            try:
                entries = collect(name, include_python)
            except FileNotFoundError as e:
                if MODULE_SPEC[name]["required"]:
                    raise SystemExit(f"cannot build a release: {e}")
                print(f"  skipped {name}: {e}")
                continue
            payload = [e for e in entries if e[0] is not None or e[1] in _SYNTHESISED]
            if not payload:
                print(f"  skipped {name}: no files found")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            print(f"  packing {name} {mver}: {len(payload)} files -> {dest.name}")
            write_zip(entries, dest)
            if name != "base":
                _check_pack_archive_compiled(dest, name)      # audit-o: the shipped pack is the compiled one
            how = "built"
            # A --no-python base is NOT installable. Mark it, so a later pack-only run cannot
            # silently reuse it into a signed manifest.
            marker = dest.with_name(dest.name + ".no-python")
            if name == "base" and not include_python:
                marker.write_text("built with --no-python; not installable\n", encoding="ascii")
            else:
                marker.unlink(missing_ok=True)
        elif dest.is_file():
            marker = dest.with_name(dest.name + ".no-python")
            if name == "base" and marker.is_file() and include_python:
                raise SystemExit(
                    f"REFUSING to reuse {dest.name}: it was built with --no-python and is not "
                    "installable. Rebuild it (--modules base) before cutting a pack release.")
            how = "reused"
            if name == "portraits-hd":
                _check_reused_portrait_pack(dest, mver)
            elif name == "movies-hd":
                _check_reused_movie_pack(dest, mver)
            if name != "base":
                _check_pack_archive_compiled(dest, name)      # audit-o: the shipped pack is the compiled one
            if name in wanted:
                print(f"  {name} {mver} is already built; not rebuilt (pass --rebuild to force "
                      f"-- only for a version that has NOT been published)")
        else:
            if name != "base":
                print(f"  WARNING: {name} v{mver} has no archive and was not built; it is LEFT "
                      f"OUT of this manifest (add --modules {name} to build it). Players who "
                      f"have it installed will read that as 'dropped'.")
            continue
        built[name] = {"version": mver, "path": str(dest), "how": how,
                       "sha256": sha256_file(dest), "size": dest.stat().st_size}
        if name == "base":
            check_base_fits(dest)
        else:
            # Too big for one GitHub asset: published as byte slices of this archive (split_archive). Also run when
            # it fits, so parts left by an earlier, larger build are removed.
            n = len(plan_slices(built[name]["size"]))
            if n:
                print(f"  splitting {dest.name} into {n} parts (over one release asset; this reads and writes "
                      f"{built[name]['size'] / 1e9:.1f} GB)...")
            built[name]["parts"] = split_archive(dest, name, mver)
        print(f"  {name:<14} {mver:<8} {how:<8} {built[name]['size']:>14,} bytes  "
              f"sha256 {built[name]['sha256'][:16]}...")
        for i, p in enumerate(built[name].get("parts") or [], 1):
            print(f"    part {i}: {Path(p['path']).name}  {p['size']:>14,} bytes  sha256 {p['sha256'][:16]}...")

    if "base" not in built:
        raise SystemExit("the base module is required and was not built (name it in --modules, "
                         f"or build it first so {out_dir} holds its archive)")

    manifest = build_manifest(args.version, built, args.base_url, args.pack_url)
    mpath = out_dir / "manifest.json"
    mpath.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    signed = False
    if args.sign_key:
        import sign_manifest as sm
        import manifest as mfmod
        seed = sm.load_seed(Path(args.sign_key))
        pk_hex = sm.public_key(seed).hex()
        # Signing with a key the shipped client does not trust yields a manifest EVERY install
        # rejects -- a release that looks fine here and is inert in the field. Catch it now.
        # Compare BYTES, not strings: verify_detached() is case-insensitive and strips
        # whitespace, so an uppercase or newline-terminated PUBLIC_KEY_HEX would have made this
        # refuse the correct key -- a fail-closed bug that blocks a legitimate release.
        def _same_key(a: str, b: str) -> bool:
            try:
                return bytes.fromhex(a.strip()) == bytes.fromhex(b.strip())
            except (ValueError, AttributeError, TypeError):
                return False
        if mfmod.PUBLIC_KEY_HEX and not _same_key(mfmod.PUBLIC_KEY_HEX, pk_hex):
            raise SystemExit(
                f"REFUSING to sign: --sign-key is\n    {pk_hex}\n"
                f"but manifest.PUBLIC_KEY_HEX (what shipped clients trust) is\n"
                f"    {mfmod.PUBLIC_KEY_HEX}\n"
                "Nothing would accept this manifest. Use the release key, or -- only for the "
                "very first release -- update PUBLIC_KEY_HEX to match.")
        if not mfmod.PUBLIC_KEY_HEX:
            print(f"WARNING: manifest.PUBLIC_KEY_HEX is empty, so no client trusts anything yet.\n"
                  f"         Set it to {pk_hex} before cutting a real release.\n")
        sm.sign_file(seed, mpath)
        # Prove the pair the installer will actually read verifies, through the same code path.
        try:
            mfmod.load_verified_files(mpath, public_key_hex=pk_hex)
        except mfmod.ManifestError as e:
            raise SystemExit(f"the signed manifest does not verify: {e}")
        signed = True

    print(f"\n=== release {args.version} staged in {out_dir} ===")
    for name, info in built.items():
        print(f"  {name:<14} {info['version']:<8} {info['how']:<8} {info['size']:>14,} bytes"
              + (f"  (published as {len(info['parts'])} parts: .001-.{len(info['parts']):03d})"
                 if info.get("parts") else ""))
    print(f"  manifest.json  ({len(manifest['targets'])} target(s), "
          f"{len(manifest['modules'])} module(s))")
    if signed:
        print("  manifest.json.sig  (verified against its own public key)")
        print("\nNEXT: confirm manifest.PUBLIC_KEY_HEX is this key, then publish.")
    else:
        print("\nNEXT: sign it -- `sign_manifest.py --key <key> --manifest "
              f"{mpath}`. It is UNSIGNED and not publishable as-is.")
    if args.no_python:
        print(f"NOTE: --no-python was used; {archive_name('base', args.version)} is "
              "NOT installable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
