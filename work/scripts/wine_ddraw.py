"""Wine / Proton: keep GOG's DDrawCompat ddraw.dll from loading, and crashing the game, under Wine.

GOG's Planetary Pack ships DDrawCompat (github.com/narzoul/DDrawCompat) as ddraw.dll beside the exe. On Windows it
loads instead of the system ddraw and fixes old-DirectDraw problems. Wine normally ignores it and uses its own
builtin ddraw. But when a DLL override makes Wine load it (`WINEDLLOVERRIDES=ddraw=n,b`, GE-Proton's
PROTON_USE_D7VK, winetricks cnc_ddraw / dgvoodoo2 left in the prefix), DDrawCompat v0.5.4 hooks ddraw's
SetAppCompatData export, which Wine's ddraw does not have, reads through the null pointer and the process dies
during DLL loading -- before the exe, PRACX or uimod.dll run any code (measured 2026-11-10, GE-Proton11-12).
DDrawCompat builds after v0.4.0 do not run under Wine (Wine bug 57455; v0.4.0 and older reportedly do), so under
Wine such a build is never useful: set it aside and Wine uses its own ddraw whatever the override says.

    set_aside(game_dir)  every install and update run. Under Wine: a DDrawCompat ddraw.dll newer than v0.4.0 is
                         moved to ddraw.dll.longevity.bak. Anything else (another wrapper, an older DDrawCompat
                         that works under Wine) is left alone and said so. On Windows (certainly not Wine): a
                         backup of ours with no live ddraw.dll goes back (a folder shared with a Linux install
                         keeps DDrawCompat on Windows). When the platform is unclear: nothing.
    restore(game_dir)    --uninstall, on any platform: the backup goes back.

Never raises; every outcome is a (status, line) pair. Python 3.8 compatible (the Windows 7 runtime runs it too).
"""
import os
import pathlib
import re
import sys

NAME = "ddraw.dll"
BAK_SUFFIX = ".longevity.bak"

#: set_aside / restore statuses.
NOT_WINE, ABSENT, FOREIGN, MOVED, ALREADY, RESTORED, NOTHING, DROPPED, KEPT, FAILED = (
    "not-wine", "absent", "foreign", "moved", "already", "restored", "nothing", "dropped", "kept", "failed")

#: platform() answers.
WINE, WINDOWS, UNKNOWN = "wine", "windows", "unknown"

#: TEST AFFORDANCE ONLY: the installer's end-to-end tests run on Windows and set this to "wine" to drive the Wine
#: path through the real installer. A player never has it.
ASSUME_ENV = "LONGEVITY_TEST_ASSUME_PLATFORM"

#: DDrawCompat builds up to this one reportedly run under Wine (Wine bug 57455); only newer ones are moved.
LAST_WINE_SAFE = (0, 4, 0)

_PRODUCT_KEY = "ProductName".encode("utf-16le") + b"\0\0"
_VERSION_KEY = "ProductVersion".encode("utf-16le") + b"\0\0"
_PRODUCT = "DDrawCompat"


def _wine_registry_key() -> bool:
    """Every Wine prefix has HKLM\\Software\\Wine (seen 2026-11-14 in GE-Proton11-12 and Wine 9.0 prefixes); a real
    Windows has none, and an unprivileged program cannot create one there. Still present when a staging build hides
    wine_get_version (HideWineExports). HKCU is NOT consulted: any Windows program can write HKCU\\Software\\Wine."""
    try:
        import winreg
    except ImportError:
        return False
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\Wine"))
        return True
    except OSError:
        return False


def _wine_export() -> bool:
    """Wine's ntdll exports wine_get_version (unless hidden); Windows' never does."""
    try:
        import ctypes
        ntdll = ctypes.WinDLL("ntdll")
        return hasattr(ntdll, "wine_get_version") or hasattr(ntdll, "wine_get_host_version")
    except Exception:  # noqa: BLE001
        return False


def platform() -> str:
    """WINE, WINDOWS, or UNKNOWN (not a Windows Python at all, e.g. a native Linux interpreter)."""
    forced = os.environ.get(ASSUME_ENV, "").strip().lower()
    if forced in (WINE, WINDOWS):
        return forced
    if sys.platform != "win32":
        return UNKNOWN
    try:
        return WINE if (_wine_export() or _wine_registry_key()) else WINDOWS
    except Exception:  # noqa: BLE001
        return UNKNOWN


def running_under_wine() -> bool:
    return platform() == WINE


def _string_values(data: bytes, key: bytes) -> list:
    """Every value following a VS_VERSIONINFO String key (UTF-16LE, NUL-padded to a 4-byte boundary). The same
    wide string can also sit in .rdata (a literal path like \\StringFileInfo\\...\\ProductName); trying every hit
    keeps such a literal from hiding the real resource."""
    out = []
    i = data.find(key)
    while i >= 0 and len(out) < 64:
        j = i + len(key)
        end = min(len(data), j + 16)
        while j + 1 < end and data[j:j + 2] == b"\0\0":
            j += 2
        k = j
        while k + 1 < len(data) and data[k:k + 2] != b"\0\0" and k - j < 256:
            k += 2
        try:
            out.append(data[j:k].decode("utf-16le"))
        except UnicodeDecodeError:
            pass
        i = data.find(key, i + 2)
    return out


def ddrawcompat_version(path) -> str:
    """'v0.5.4' for a DDrawCompat ddraw.dll ('?' when it names no version); '' for anything else or unreadable."""
    try:
        data = pathlib.Path(path).read_bytes()
    except OSError:
        return ""
    if not data.startswith(b"MZ") or _PRODUCT not in _string_values(data, _PRODUCT_KEY):
        return ""
    versions = [v for v in _string_values(data, _VERSION_KEY) if re.match(r"v?\d+\.\d+", v)]
    return versions[0] if versions else "?"


def _crashes_under_wine(version: str) -> bool:
    """True for a DDrawCompat build newer than LAST_WINE_SAFE; False for older or unparseable ones (left alone)."""
    m = re.match(r"v?(\d+)\.(\d+)(?:\.(\d+))?", version or "")
    if not m:
        return False
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) > LAST_WINE_SAFE


def backup_of(game_dir) -> pathlib.Path:
    return pathlib.Path(game_dir) / (NAME + BAK_SUFFIX)


def _same_bytes(a: pathlib.Path, b: pathlib.Path) -> bool:
    try:
        return _same_bytes_or_raise(a, b)
    except OSError:
        return False


def _same_bytes_or_raise(a: pathlib.Path, b: pathlib.Path) -> bool:
    return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()


def _readable(path: pathlib.Path) -> None:
    """Raises OSError when `path` cannot be read: ddrawcompat_version() answers '' for an unreadable file too, and
    the restore must not call GOG's backup "not DDrawCompat" because another program held it (audit 2026-11-16)."""
    with open(path, "rb"):
        pass


def set_aside(game_dir, where=None) -> tuple:
    """Install / update step. `where` None = detect (platform()). Returns (status, line); line '' = nothing to say."""
    game_dir = pathlib.Path(game_dir)
    where = where or platform()
    if where == WINDOWS:
        status, line = restore(game_dir, only_if_absent=True)
        return (status, line) if status in (RESTORED, DROPPED, FAILED) else (NOT_WINE, "")
    if where != WINE:
        return NOT_WINE, ""
    live, bak = game_dir / NAME, backup_of(game_dir)
    try:
        if not live.exists():
            if bak.exists():
                return ALREADY, f"GOG's DDrawCompat is already set aside ({bak.name})."
            return ABSENT, ""
        version = ddrawcompat_version(live)
        if not version:
            return FOREIGN, (f"{NAME} here is not GOG's DDrawCompat (another DirectDraw wrapper?), so it is left alone. "
                             "If the game crashes at start under Wine, try moving it out of the game folder.")
        if not _crashes_under_wine(version):
            return FOREIGN, (f"{NAME} here is DDrawCompat {version}, an older build that works under Wine, so it is "
                             "left alone.")
        os.replace(str(live), str(bak))   # a newer DDrawCompat (restored by a file check) replaces an older backup
        return MOVED, (f"moved GOG's DDrawCompat ({NAME} {version}) to {bak.name}: it does not work under Wine and "
                       "crashes the game at start whenever a ddraw override loads it. Wine uses its own ddraw "
                       "instead, as it already did. --uninstall puts it back.")
    except OSError as e:
        return FAILED, (f"could not set GOG's DDrawCompat aside ({e}). The game still runs under Wine unless a ddraw "
                        "override loads it.")


def restore_plan(game_dir) -> list:
    """What restore(game_dir) would read and change, without changing it: [(path, modes)] (preflight.PROBE_MODES
    joined by "+"). The uninstall probes these before its first change. Mirrors restore's branches; keep the two
    together. A live ddraw.dll is never written: the backup is moved back onto a free name, or deleted when the same
    file is back. The backup is always read (is it DDrawCompat?), and the live file with it when both are there."""
    game_dir = pathlib.Path(game_dir)
    live, bak = game_dir / NAME, backup_of(game_dir)
    try:
        if not bak.exists():
            return []
        reads = [(bak, "read")]
        if not ddrawcompat_version(bak):        # '' for an unreadable one too: listed for reading all the same
            return reads
        if not live.exists():
            return reads + [(bak, "rename")]
        reads.append((live, "read"))
        return reads + ([(bak, "delete")] if _same_bytes_or_raise(live, bak) else [])
    except OSError:
        return [(p, "read") for p in (bak, live) if p.exists()]


def restore(game_dir, only_if_absent=False) -> tuple:
    """--uninstall: put the backup back. Returns (status, line).

    A live ddraw.dll that appeared since (a GOG / Heroic file check) is never overwritten: an identical one makes
    the backup redundant (DROPPED: the backup is deleted, nothing is lost), a different one keeps both and says so.
    `only_if_absent` (the Windows install step) does the plain move back and drops a redundant backup, and leaves a
    different live file and its backup alone without a word."""
    game_dir = pathlib.Path(game_dir)
    live, bak = game_dir / NAME, backup_of(game_dir)
    try:
        if not bak.exists():
            return NOTHING, ""
        if not only_if_absent:
            # --uninstall: an unreadable backup is a failure, not "not DDrawCompat" (audit 2026-11-16). The install
            # step stays quiet about it as before: it only tidies up, and its warning would advise a wrong rename.
            _readable(bak)
        if not ddrawcompat_version(bak):
            return KEPT, f"{bak.name} is not GOG's DDrawCompat, so it is left alone."
        if not live.exists():
            os.replace(str(bak), str(live))
            return RESTORED, f"put GOG's DDrawCompat back ({bak.name} -> {NAME})."
        if (_same_bytes(live, bak) if only_if_absent else _same_bytes_or_raise(live, bak)):
            bak.unlink()
            return DROPPED, f"removed {bak.name}: the same {NAME} is already back in place."
        if only_if_absent:
            return NOTHING, ""
        return KEPT, f"{NAME} was replaced since it was set aside; {bak.name} kept beside it. Delete either yourself."
    except OSError as e:
        if live.exists():               # renaming the backup onto a ddraw.dll that is there is not the advice
            return FAILED, (f"could not finish with {bak.name} ({e}): it and {NAME} are left as they are. Close any "
                            "program using them and run --uninstall again.")
        return FAILED, f"could not put {NAME} back from {bak.name} ({e}). Rename it to {NAME} yourself."


def main() -> int:
    import config
    game = pathlib.Path(config.game_dir())
    args = sys.argv[1:]
    if "--restore" in args:
        status, line = restore(game)
    elif "--check" in args:
        print(f"platform: {platform()}  {NAME}: {ddrawcompat_version(game / NAME) or 'not DDrawCompat/absent'}"
              f"  backup: {backup_of(game).exists()}")
        return 0
    else:
        status, line = set_aside(game)
    print(f"{status}: {line}" if line else status)
    return 1 if status == FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
