"""Build the player's download from this checkout and unpack it the way a player would.

Developer tool for testing the FIRST-INSTALL path end to end: the archive a player downloads
(`LongevityVaccine_<version>.zip`, laid out by release.py's MODULE_SPEC with the synthesised
INSTALL.bat at its root), extracted into a stand-in Downloads folder exactly as Explorer's
"Extract All" does (a folder named after the zip, INSTALL.bat at its top). The tester then
double-clicks that INSTALL.bat with no arguments, so game-folder autodetection, the console
text, the resolution check and the desktop shortcut offer are all the real thing.

    py work\\scripts\\dev_player_zip.py [--out DIR] [--no-python] [--no-extract]

This is NOT a release: nothing is signed, no manifest is written, nothing leaves this machine,
and the output lives under work\\build\\lvtest\\player by default. Releases go only through
work\\run-release.bat. The archive layout is byte-identical to a release build because the
same two release.py functions (collect + write_zip) produce it; a private copy of that layout
here would drift from what ships (the earlier test archive lacked INSTALL.bat for exactly
that reason).

Writes `<out>\\extracted.txt` holding the extracted folder's path, for the batch script that
drives the live reinstall test (Desktop\\LongevityTests\\reinstall-live-from-zip.bat).
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import release as rel   # noqa: E402
import version as ver   # noqa: E402

DEFAULT_OUT = _SCRIPTS.parent / "build" / "lvtest" / "player"


def build(out: Path, include_python: bool = True) -> Path:
    """The player's base archive at the checkout's real version. Returns the zip path."""
    entries = rel.collect("base", include_python)
    dest = out / rel.archive_name("base", ver.VERSION)
    rel.write_zip(entries, dest)
    return dest


def extract_like_explorer(archive: Path, downloads: Path) -> Path:
    """Explorer's "Extract All" default: a folder named after the zip, contents at its top."""
    target = downloads / archive.stem
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        # The archive is ours (just written), so extractall's path handling is not a concern.
        z.extractall(target)
    return target


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="where the zip, the Downloads stand-in and extracted.txt go")
    ap.add_argument("--no-python", action="store_true",
                    help="leave the bundled interpreter out (fast; the result cannot be run)")
    ap.add_argument("--no-extract", action="store_true", help="build the zip only")
    a = ap.parse_args(argv)
    # Absolute, so extracted.txt is usable from any working directory.
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    archive = build(out, include_python=not a.no_python)
    print(f"zip={archive}")
    print(f"size={archive.stat().st_size}")
    if a.no_extract:
        return 0
    folder = extract_like_explorer(archive, out / "Downloads")
    (out / "extracted.txt").write_text(str(folder) + "\n", encoding="utf-8")
    print(f"extracted={folder}")
    print(f"install={folder / 'INSTALL.bat'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
