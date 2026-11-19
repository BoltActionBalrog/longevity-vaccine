"""Keyboard-focus probe for the game window (issue longevity-vaccine #6: PRACX Preferences -> mouse options lost).

PRACXWinProc gates map wheel zoom, wheel list-scrolling and right-drag scroll on
`GetFocus() == game hwnd` (refs/pracx/shared/pracx.cpp:1139). This script reads, and on request clears,
the game thread's keyboard focus from OUTSIDE the process -- no Frida, no memory writes:

  py focus_probe.py watch            log every focus/active change of the game thread (Ctrl+C to stop)
  py focus_probe.py drop [--delay N] after N s (default 8), set the game thread's focus to NULL --
                                     the state Wine is suspected to leave after the Preferences panel closes
  py focus_probe.py restore          give focus back to the game window

`--pid` targets a process by id instead of the configured game exe (self-test). If the game runs elevated
(RunAs shortcut), run this elevated too: AttachThreadInput across integrity levels fails with access denied.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as w
import sys
import time

u = ctypes.WinDLL("user32", use_last_error=True)
k = ctypes.WinDLL("kernel32", use_last_error=True)


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("flags", w.DWORD), ("hwndActive", w.HWND), ("hwndFocus", w.HWND),
                ("hwndCapture", w.HWND), ("hwndMenuOwner", w.HWND), ("hwndMoveSize", w.HWND),
                ("hwndCaret", w.HWND), ("rcCaret", w.RECT)]


u.GetWindowThreadProcessId.restype = w.DWORD
u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
u.GetGUIThreadInfo.argtypes = [w.DWORD, ctypes.POINTER(GUITHREADINFO)]
u.AttachThreadInput.argtypes = [w.DWORD, w.DWORD, w.BOOL]
u.SetFocus.restype = w.HWND
u.SetFocus.argtypes = [w.HWND]
u.GetClassNameA.argtypes = [w.HWND, ctypes.c_char_p, ctypes.c_int]
u.GetParent.restype = w.HWND
u.GetParent.argtypes = [w.HWND]
WNDENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
k.OpenProcess.restype = w.HANDLE
k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, ctypes.c_wchar_p, ctypes.POINTER(w.DWORD)]


def exe_of(pid: int) -> str:
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = w.DWORD(len(buf))
        return buf.value if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally:
        k.CloseHandle(h)


def find_window(pid: int | None, exe: str) -> tuple[int, int, int]:
    """(hwnd, thread id, pid) of the largest visible top-level window of the target process."""
    best: list = []

    def cb(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        p = w.DWORD()
        tid = u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if (pid is not None and p.value == pid) or (pid is None and exe_of(p.value).lower().endswith("\\" + exe.lower())):
            r = w.RECT()
            u.GetWindowRect(hwnd, ctypes.byref(r))
            best.append(((r.right - r.left) * (r.bottom - r.top), hwnd, tid, p.value))
        return True

    u.EnumWindows(WNDENUMPROC(cb), 0)
    if not best:
        sys.exit(f"no visible window for {'pid %d' % pid if pid is not None else exe}")
    _, hwnd, tid, p = max(best)
    return hwnd, tid, p


def describe(hwnd, game) -> str:
    if not hwnd:
        return "NULL"
    if hwnd == game:
        return "GAME WINDOW"
    cls = ctypes.create_string_buffer(64)
    u.GetClassNameA(hwnd, cls, 64)
    parent = u.GetParent(hwnd)
    return f"{hwnd:#x} class={cls.value.decode(errors='replace')} parent={'game' if parent == game else hex(parent or 0)}"


def thread_info(tid: int) -> GUITHREADINFO:
    gi = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    if not u.GetGUIThreadInfo(tid, ctypes.byref(gi)):
        err = ctypes.get_last_error()
        sys.exit("game thread gone (the game exited)" if err == 87 else f"GetGUIThreadInfo failed: {err}")
    return gi


def with_attached(tid: int, fn):
    msg = w.MSG()
    u.PeekMessageA(ctypes.byref(msg), None, 0, 0, 0)  # give this thread a message queue
    me = k.GetCurrentThreadId()
    if not u.AttachThreadInput(me, tid, True):
        sys.exit(f"AttachThreadInput failed: error {ctypes.get_last_error()} "
                 "(5 = access denied: run this elevated if the game runs as administrator)")
    try:
        return fn()
    finally:
        u.AttachThreadInput(me, tid, False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["watch", "drop", "restore"])
    ap.add_argument("--pid", type=int, help="target process id (default: the configured game exe)")
    ap.add_argument("--delay", type=float, default=8.0, help="drop: seconds before clearing focus")
    a = ap.parse_args()

    exe = ""
    if a.pid is None:
        from config import exe_name
        exe = exe_name()
    game, tid, pid = find_window(a.pid, exe)
    print(f"target pid {pid}, game window {game:#x}, thread {tid}")

    if a.mode == "watch":
        last = None
        try:
            while True:
                gi = thread_info(tid)
                cur = (gi.hwndFocus, gi.hwndActive)
                if cur != last:
                    print(f"{time.strftime('%H:%M:%S')}  focus={describe(gi.hwndFocus, game)}  "
                          f"active={describe(gi.hwndActive, game)}", flush=True)
                    last = cur
                time.sleep(0.1)
        except KeyboardInterrupt:
            return
    elif a.mode == "drop":
        for s in range(int(a.delay), 0, -1):
            print(f"clearing focus in {s} s -- bring the game to the front and leave it there", flush=True)
            time.sleep(1)
        with_attached(tid, lambda: u.SetFocus(None))
        gi = thread_info(tid)
        print(f"after drop: focus={describe(gi.hwndFocus, game)} active={describe(gi.hwndActive, game)}")
    else:
        with_attached(tid, lambda: u.SetFocus(game))
        gi = thread_info(tid)
        print(f"after restore: focus={describe(gi.hwndFocus, game)}")


if __name__ == "__main__":
    main()
