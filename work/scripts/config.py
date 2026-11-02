"""Single source of truth for the SMACX game-install path and target exe.

The game directory is resolved in priority order:
  1. $SMACX_GAME_DIR        environment variable (highest priority)
  2. work/game-path.txt     one line holding the game directory
  3. auto-detected known GOG install locations

The target executable name (the binary the patcher/Frida act on) is resolved:
  1. $SMACX_EXE_NAME        environment variable
  2. work/game-exe.txt      one line holding the exe filename
  3. "terranx.exe"          default

On a stock PRACX GOG install the un-PRACX'd base is terranx.exe and the
PRACX-patched base (the patcher's MD5 2d0b1438 target) is terranx_PRACX.exe, so
this install sets game-exe.txt = terranx_PRACX.exe.

Machine-specific values belong in game-path.txt / game-exe.txt (both gitignored)
or the env vars, never hardcoded in a script. The batch counterpart is
work/game-path.bat (it exports %GAME_DIR% and %GAME_EXE%).
"""
from __future__ import annotations

import os
from pathlib import Path

# Reliable marker for locating a SMACX install dir (always present on GOG).
_DIR_MARKER = "terranx.exe"
DEFAULT_EXE = "terranx.exe"

_WORK = Path(__file__).resolve().parent.parent  # ...\work


def payload_root_from(script_dir: Path) -> Path:
    """The root of the installer payload that `script_dir` belongs to.

    ONE rule -- walk up until the bundled interpreter is in sight -- rather than a fixed number
    of `.parent` hops, because the payload is flat (`<root>/scripts`) while a checkout is not
    (`<root>/work/scripts`). Counting hops is right for exactly one of those and silently
    resolves to a real-but-wrong directory for the other, so nothing raises: the installer just
    looks for uimod.dll and ffmpeg where they are not, and reports them missing.
    """
    d = Path(script_dir).resolve()
    for cand in (d, *d.parents):
        if (cand / "tools" / "python").is_dir():
            return cand
    return d.parent.parent
_PATH_FILE = _WORK / "game-path.txt"
_EXE_FILE = _WORK / "game-exe.txt"

# Fallback install locations, most-likely first. Only used if neither the env
# var nor game-path.txt resolves.
_CANDIDATES = [
    r"D:\GOG Galaxy\Games\Sid Meier's Alpha Centauri Planetary Pack",
    r"C:\GOG Galaxy\Games\Sid Meier's Alpha Centauri Planetary Pack",
    r"C:\Program Files (x86)\GOG Galaxy\Games\Sid Meier's Alpha Centauri Planetary Pack",
    r"C:\GOG Games\Sid Meier's Alpha Centauri Planetary Pack",
    r"D:\GOGGalaxy\Games\Alpha Centauri",
]


def _read_line(p: Path) -> str | None:
    if p.exists():
        line = p.read_text(encoding="utf-8").strip().strip('"')
        if line:
            return line
    return None


def _from_env_dir() -> Path | None:
    v = os.environ.get("SMACX_GAME_DIR", "").strip().strip('"')
    return Path(v) if v else None


def _from_file_dir() -> Path | None:
    line = _read_line(_PATH_FILE)
    return Path(line) if line else None


def _from_autodetect() -> Path | None:
    for c in _CANDIDATES:
        if (Path(c) / _DIR_MARKER).exists():
            return Path(c)
    return None


#: Replaces EVERY machine source of candidate_game_dirs() (the env var, game-path.txt, the fixed
#: locations, the GOG registry) with this list, "|"-separated -- empty means none. The test suite
#: sets it so no installer a test spawns can ever find the real game.
CANDIDATES_ENV = "LONGEVITY_GAME_CANDIDATES"
#: Where the folders the installer installed into are remembered (one per line). Default:
#: %LOCALAPPDATA%\LongevityVaccine\installs.txt.
INSTALLS_ENV = "LONGEVITY_INSTALLS_FILE"


def _gog_registry_dirs() -> list:
    """Every GOG-installed game folder (GOG Galaxy and the offline installers both record one
    under HKLM\\SOFTWARE\\[WOW6432Node\\]GOG.com\\Games\\<id>, value `path`), wherever the
    player put the library. Read-only; any failure is just "none"."""
    try:
        import winreg
    except ImportError:
        return []
    out = []
    for root in (r"SOFTWARE\WOW6432Node\GOG.com\Games", r"SOFTWARE\GOG.com\Games"):
        try:
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root)
        except OSError:
            continue
        with k:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(k, sub) as g:
                        v, _ = winreg.QueryValueEx(g, "path")
                except OSError:
                    continue
                if isinstance(v, str) and v.strip():
                    out.append(Path(v.strip().strip('"')))
    return out


def _dedup_dirs(dirs) -> list:
    out, seen = [], set()
    for d in dirs:
        try:
            key = _dir_key(d)
        except (OSError, ValueError):
            continue
        if key and key not in seen:
            seen.add(key)
            out.append(Path(d))
    return out


def candidate_game_dirs() -> list:
    """Folders that may hold the game, most likely first: the configured one (env var,
    game-path.txt), then every known location that has the game's marker file in it -- the fixed
    GOG paths and every folder the GOG registry names. Only existing folders; no validation of
    WHICH game build is there (the installer does that)."""
    if CANDIDATES_ENV in os.environ:
        raw = [p.strip().strip('"') for p in os.environ[CANDIDATES_ENV].split("|")]
        found = [Path(p) for p in raw if p]
    else:
        found = [d for d in (_from_env_dir(), _from_file_dir()) if d is not None]
        found += [d for d in [Path(c) for c in _CANDIDATES] + _gog_registry_dirs()
                  if (d / _DIR_MARKER).exists()]
    return [d for d in _dedup_dirs(found) if _safe_is_dir(d)]


def _safe_is_dir(d: Path) -> bool:
    """is_dir() that reads an unreadable folder as "not a candidate" instead of raising."""
    try:
        return d.is_dir()
    except (OSError, ValueError):
        return False


def installs_file() -> Path:
    v = os.environ.get(INSTALLS_ENV, "").strip().strip('"')
    if v:
        return Path(v)
    import tempfile
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "LongevityVaccine" / "installs.txt"


def remembered_game_dirs() -> list:
    """The folders the installer installed into on this PC (still existing), newest first."""
    try:
        lines = installs_file().read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    return [d for d in _dedup_dirs(Path(s.strip()) for s in lines if s.strip()) if _safe_is_dir(d)]


def _write_remembered(dirs) -> bool:
    f = installs_file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")    # two installers never share one
        tmp.write_text("".join(f"{d}\n" for d in dirs), encoding="utf-8")
        os.replace(tmp, f)
        return True
    except OSError:
        try:
            tmp.unlink()
        except (OSError, NameError):
            pass
        return False


def _dir_key(p) -> str:
    """One key per folder ON DISK: its volume serial + file index when it can be read, so a
    junction, a subst drive or an 8.3 name of the same folder is one folder, not two installs."""
    try:
        st = os.stat(str(p))
        if st.st_ino:
            return f"id:{st.st_dev}:{st.st_ino}"
    except (OSError, ValueError):
        pass
    return os.path.normcase(os.path.abspath(str(p))).rstrip("\\/")


def _same_dir(a, b) -> bool:
    return _dir_key(a) == _dir_key(b)


def remember_game_dir(d: Path) -> bool:
    """Record `d` (absolute) as an install, newest first. Best effort: a failure only means the
    next run has to be pointed at the folder again."""
    d = Path(os.path.abspath(str(d)))
    keep = [x for x in remembered_game_dirs() if not _same_dir(x, d)]
    return _write_remembered([d] + keep)


def forget_game_dir(d: Path) -> bool:
    keep = [x for x in remembered_game_dirs() if not _same_dir(x, d)]
    return _write_remembered(keep)


def resident_game_dir(script_dir: Path) -> Path | None:
    """The game directory a RESIDENT updater belongs to, from its own location
    (`<game>\\LongevityMods\\updater\\scripts`), else None.

    A resident copy must never act on a different install than the one it lives in:
    without this, the game's own update hand-off (which passes no --game-dir) and a test
    driving a throwaway install's updater both fell through to autodetection and wrote to
    the real GOG install (2026-09-27).
    """
    d = Path(script_dir).resolve()
    if d.name == "scripts" and d.parent.name == "updater" and d.parent.parent.name == "LongevityMods":
        return d.parent.parent.parent
    return None


def game_dir(required: bool = True) -> Path:
    """Resolve the game install directory.

    With required=False, returns a best-guess path even if it does not exist
    (useful for argparse defaults and --help text); the caller's own file/MD5
    checks then produce the actionable error.
    """
    resident = resident_game_dir(Path(__file__).parent)
    if resident is not None:
        return resident
    for src in (_from_env_dir, _from_file_dir, _from_autodetect):
        d = src()
        if d is not None:
            return d
    if required:
        raise FileNotFoundError(
            "Could not locate the SMACX game directory. Set the SMACX_GAME_DIR "
            f"environment variable, write the path into {_PATH_FILE}, or "
            "install the game to a known GOG location. See game-path.txt.example."
        )
    return Path(_CANDIDATES[0])


def exe_name() -> str:
    """Resolve the target executable filename (patcher/Frida target)."""
    v = os.environ.get("SMACX_EXE_NAME", "").strip().strip('"')
    if v:
        return v
    line = _read_line(_EXE_FILE)
    return line if line else DEFAULT_EXE


def terranx(required: bool = True) -> Path:
    """Full path to the target executable."""
    return game_dir(required=required) / exe_name()


def terranx_bak(required: bool = False) -> Path:
    """Full path to the pristine backup (target exe + .bak)."""
    return game_dir(required=required) / (exe_name() + ".bak")


if __name__ == "__main__":
    print(f"game_dir : {game_dir(required=False)}")
    print(f"exe_name : {exe_name()}")
    print(f"terranx  : {terranx(required=False)}")
    print(f"exists   : {terranx(required=False).exists()}")
