r"""Attach a Frida observer to a game that a LAUNCHER starts (Thinker: thinker.exe spawns terranx.exe, injects
thinker.dll, resumes it and exits).  `frida -f` cannot be used there: it would spawn the launcher, not the game.

What it does:
  1. starts the launcher in the game folder;
  2. finds the new game process (by name; the launcher is its parent) and waits until BOTH thinker.dll and
     uimod.dll are loaded in it -- Thinker's in-memory patch pass and our DLL's apply-after-Thinker pass are
     then complete, so a hook that resolves Thinker's functions from the rewritten call sites sees final bytes;
  3. attaches, loads scripts\frida_common.js + the hook (same prelude order as run-frida.bat; scaling_laws.js
     too, so no hook needs to re-inline it), with LOG_PATH preset to a timestamped file (one log per run);
  4. echoes the hook's console output, waits for the game to exit, asks the hook for its summary, detaches.

No engine calls, no input.  Observer hooks only (scripts\PROBES.md).  Attaching to a same-user process needs
no elevation; if Frida reports a permission error, run the console as administrator.

Usage:
  run_frida_thinker.py --game-dir <folder> --hook hook_<name>.js [--launcher thinker.exe] [--process terranx.exe]
                       [--log <path>] [--pre <extra.js>] [--timeout 90]
Exit code 0 when the hook ran to game exit, 1 on a failure to start/attach, 2 on a usage error.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as W
import datetime as dt
import subprocess
import sys
import time
from pathlib import Path

k32 = ctypes.windll.kernel32
TH32CS_SNAPMODULE = 0x8
TH32CS_SNAPPROCESS = 0x2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", W.DWORD),
                ("cntThreads", W.DWORD), ("th32ParentProcessID", W.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", W.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def processes() -> list[tuple[int, int, str]]:
    """(pid, parent pid, exe name) for every process (Toolhelp snapshot)."""
    out = []
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1:
        return out
    e = PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(e)
    ok = k32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out.append((e.th32ProcessID, e.th32ParentProcessID, e.szExeFile))
        ok = k32.Process32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return out


def exit_code(pid: int) -> int | None:
    """None while the process runs; its exit code once it is gone (or -1 if it cannot be opened)."""
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return -1
    code = W.DWORD()
    ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    if not ok:
        return -1
    return None if code.value == STILL_ACTIVE else int(code.value)
TH32CS_SNAPMODULE32 = 0x10
ERROR_BAD_LENGTH = 24
SCRIPTS = Path(__file__).resolve().parent
PRELUDES = ["frida_common.js", "scaling_laws.js"]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", W.DWORD), ("th32ModuleID", W.DWORD), ("th32ProcessID", W.DWORD),
                ("GlblcntUsage", W.DWORD), ("ProccntUsage", W.DWORD), ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
                ("modBaseSize", W.DWORD), ("hModule", W.HMODULE), ("szModule", ctypes.c_wchar * 256),
                ("szExePath", ctypes.c_wchar * 260)]


def modules_of(pid: int) -> set[str]:
    """Lower-cased module names loaded in `pid` (empty while the process is still initialising)."""
    for _ in range(5):
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
        if snap != -1:
            break
        if k32.GetLastError() != ERROR_BAD_LENGTH:
            return set()
        time.sleep(0.05)
    else:
        return set()
    out: set[str] = set()
    e = MODULEENTRY32W()
    e.dwSize = ctypes.sizeof(e)
    ok = k32.Module32FirstW(snap, ctypes.byref(e))
    while ok:
        out.add(e.szModule.lower())
        ok = k32.Module32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return out


def find_game(name: str, launcher_pid: int, before: set[int], deadline: float) -> int | None:
    """The pid of a `name` process that is new since `before`, preferring one whose parent is the launcher."""
    while time.time() < deadline:
        fresh = [(pid, ppid) for pid, ppid, exe in processes() if exe.lower() == name and pid not in before]
        if fresh:
            for pid, ppid in fresh:
                if ppid == launcher_pid:
                    return pid
            return fresh[0][0]
        if exit_code(launcher_pid) not in (None, -1) and not fresh:
            # the launcher is gone without a game: give the snapshot one more moment
            time.sleep(0.5)
            fresh = [pid for pid, _, exe in processes() if exe.lower() == name and pid not in before]
            return fresh[0] if fresh else None
        time.sleep(0.2)
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--game-dir", required=True)
    ap.add_argument("--hook", required=True, help="hook script under work\\scripts (or a path)")
    ap.add_argument("--launcher", default="thinker.exe")
    ap.add_argument("--process", default="terranx.exe")
    ap.add_argument("--log", default=None, help="log path (default work\\frida_<hook>_<UTC>.log)")
    ap.add_argument("--pre", default=None, help="an extra script loaded between the preludes and the hook")
    ap.add_argument("--wait-for", default="thinker.dll,uimod.dll", help="modules that must be loaded before attaching")
    ap.add_argument("--timeout", type=float, default=90.0)
    a = ap.parse_args(argv)

    game_dir = Path(a.game_dir)
    launcher = game_dir / a.launcher
    if not launcher.is_file():
        print(f"launcher not found: {launcher}")
        return 2
    hook = Path(a.hook) if Path(a.hook).is_file() else SCRIPTS / a.hook
    if not hook.is_file():
        print(f"hook not found: {hook}")
        return 2
    try:
        import frida  # noqa: WPS433  (the bundled Python has it)
    except ImportError:
        print("the frida Python module is not installed for this interpreter (py -m pip install frida)")
        return 1

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    log_path = Path(a.log) if a.log else SCRIPTS.parent / f"frida_{hook.stem.removeprefix('hook_')}_{stamp}.log"
    print(f"log: {log_path}")

    before = {pid for pid, _, exe in processes() if exe.lower() == a.process.lower()}
    print(f"starting {launcher.name} in {game_dir} ...")
    proc = subprocess.Popen([str(launcher)], cwd=str(game_dir))
    deadline = time.time() + a.timeout
    pid = find_game(a.process.lower(), proc.pid, before, deadline)
    if pid is None:
        print(f"no new {a.process} appeared within {a.timeout:.0f} s (launcher exit code {exit_code(proc.pid)})")
        return 1
    print(f"game process {a.process} pid {pid}; waiting for {a.wait_for} ...")
    wanted = {m.strip().lower() for m in a.wait_for.split(",") if m.strip()}
    while time.time() < deadline:
        if exit_code(pid) is not None:
            print("the game exited before the modules loaded (a Thinker/installer error box?)")
            return 1
        have = modules_of(pid)
        if wanted <= have:
            break
        time.sleep(0.2)
    else:
        missing = wanted - modules_of(pid)
        print(f"WARNING: {', '.join(sorted(missing))} not loaded after {a.timeout:.0f} s; attaching anyway")

    source = [f'globalThis.LOG_PATH = "{log_path.as_posix()}";']
    for name in PRELUDES:
        p = SCRIPTS / name
        if p.is_file():
            source.append(p.read_text(encoding="utf-8"))
    if a.pre:
        pre = Path(a.pre) if Path(a.pre).is_file() else SCRIPTS / a.pre
        source.append(pre.read_text(encoding="utf-8"))
    source.append(hook.read_text(encoding="utf-8"))

    try:
        session = frida.attach(pid)
    except Exception as e:  # noqa: BLE001
        print(f"frida.attach({pid}) failed: {e}")
        print("(a permission error here means: run this console as administrator)")
        return 1
    detached = []
    session.on("detached", lambda reason, *_: detached.append(reason))

    def on_message(msg, _data):
        if msg.get("type") == "error":
            print("[hook error]", msg.get("description"), msg.get("stack", ""))
        elif msg.get("type") == "send":
            print("[hook]", msg.get("payload"))

    script = session.create_script("\n".join(source))
    script.on("message", on_message)
    # console.log inside the agent is delivered as 'log' messages; frida-python prints them via this hook
    script.set_log_handler(lambda level, text: print(text))
    try:
        script.load()
    except Exception as e:  # noqa: BLE001
        print(f"hook failed to load: {e}")
        session.detach()
        return 1
    print("attached. Play (load a save with cloaked/DPH units in Thinker AI territory, end turns); close the game to finish.")
    try:
        while not detached and exit_code(pid) is None:
            time.sleep(0.5)
        if not detached:
            try:
                script.exports_sync.summary()
            except Exception:  # noqa: BLE001
                pass
    except KeyboardInterrupt:
        print("interrupted: writing the summary and detaching (the game keeps running)")
        try:
            script.exports_sync.summary()
        except Exception:  # noqa: BLE001
            pass
    try:
        session.detach()
    except Exception:  # noqa: BLE001
        pass
    print(f"done. Log: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
