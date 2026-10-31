r"""Focus-free screenshot capture for the SMACX game window.

Why this exists: the built-in Windows capture paths are unusable for this
project — PrintScreen grabs ALL monitors into the clipboard, and Snipping Tool
steals focus, which makes the fullscreen game revert the display mode and
minimize (and it silently does nothing while a Frida probe is attached).

This tool captures from an external process via a screen BitBlt (PIL
ImageGrab), so it never touches the game's focus, works at any display
resolution, and is completely indifferent to Frida being attached.

Modes
  one-shot (default)   capture the game window right now and exit
  --hotkey             stay resident; Pause or Home captures the game window
                       (global hotkeys; --key overrides). PrintScreen is NOT
                       used: Windows swallows VK_SNAPSHOT below the hotkey
                       layer on this machine (confirmed for physical presses),
                       so it can never fire. NOTE: the listener must run at
                       the same (or higher) elevation as the game — UIPI
                       blocks hotkey delivery to a lower-integrity process
                       while an elevated window (e.g. a UAC'd Frida launch)
                       has focus; run-screenshot-hotkey.bat self-elevates.

Target selection
  default              the window of the configured target exe (config.py),
                       falling back to any terranx* process
  --exe NAME           match a different process image name
  --full               entire virtual desktop (all monitors)

Output: PNG under work\screenshots\ (path printed), and the same image is
placed on the clipboard unless --no-clipboard.
"""
from __future__ import annotations

import argparse
import ctypes
import datetime as _dt
import io
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

import config

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

# 64-bit safety: without explicit prototypes ctypes truncates handle/pointer
# returns to 32-bit int (GlobalLock came back as 0x20 → access violation).
_HANDLE = ctypes.c_void_p
kernel32.OpenProcess.restype = _HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [_HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [
    _HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.GlobalAlloc.restype = _HANDLE
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [_HANDLE]
kernel32.GlobalUnlock.argtypes = [_HANDLE]
kernel32.GlobalFree.argtypes = [_HANDLE]
user32.SetClipboardData.restype = _HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, _HANDLE]
user32.GetWindowDC.restype = _HANDLE
user32.GetWindowDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, _HANDLE]
user32.PrintWindow.argtypes = [wintypes.HWND, _HANDLE, wintypes.UINT]
gdi32.CreateCompatibleDC.restype = _HANDLE
gdi32.CreateCompatibleDC.argtypes = [_HANDLE]
gdi32.SelectObject.restype = _HANDLE
gdi32.SelectObject.argtypes = [_HANDLE, _HANDLE]
gdi32.DeleteObject.argtypes = [_HANDLE]
gdi32.DeleteDC.argtypes = [_HANDLE]
gdi32.CreateDIBSection.restype = _HANDLE

SHOTS_DIR = Path(__file__).resolve().parent.parent / "screenshots"

# ---------------------------------------------------------------- DPI setup

def _set_dpi_aware() -> None:
    """Per-monitor-v2 DPI awareness so window rects are physical pixels."""
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


# ---------------------------------------------------------- window location

def _process_image_name(pid: int) -> str:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(h)


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Physical-pixel bounds; DWM extended frame when available (no drop
    shadow), plain GetWindowRect otherwise."""
    r = wintypes.RECT()
    try:
        DWMWA_EXTENDED_FRAME_BOUNDS = 9
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(r), ctypes.sizeof(r),
        ) == 0:
            return (r.left, r.top, r.right, r.bottom)
    except (AttributeError, OSError):
        pass
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def find_target_window(exe_override: str | None) -> tuple[int, str] | None:
    """Largest visible top-level window whose process image matches.

    Match order: --exe override if given; else the configured target exe;
    else any terranx*.exe (covers pristine / _PRACX / renamed builds).
    Returns (hwnd, image_name) or None.
    """
    wanted = (exe_override or config.exe_name()).lower()
    hits: list[tuple[int, int, str]] = []  # (area, hwnd, image)
    iconic_only = False

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        nonlocal iconic_only
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        img = _process_image_name(pid.value).lower()
        if not img:
            return True
        if img == wanted or (exe_override is None and img.startswith("terranx")):
            if user32.IsIconic(hwnd):
                iconic_only = True  # a screen grab cannot see a minimized window
                return True
            l, t, r, b = _window_rect(hwnd)
            area = max(0, r - l) * max(0, b - t)
            if area > 0:
                # exact match on the configured exe outranks a terranx* catch
                hits.append((area + (1 << 40 if img == wanted else 0), hwnd, img))
        return True

    user32.EnumWindows(_cb, 0)
    if not hits:
        if iconic_only:
            raise RuntimeError(
                "the game window exists but is MINIMIZED — bring it on-screen "
                "first (screen-grab capture can only see rendered pixels)"
            )
        return None
    hits.sort(reverse=True)
    _, hwnd, img = hits[0]
    return hwnd, img


# ----------------------------------------------------------------- capture

def _virtual_screen() -> tuple[int, int, int, int]:
    SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
    SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return x, y, w, h


def _grab_screen_region(rect: tuple[int, int, int, int]):
    from PIL import ImageGrab
    vx, vy, vw, vh = _virtual_screen()
    img = ImageGrab.grab(all_screens=True)
    l, t, r, b = rect
    # clamp to the virtual desktop, then rebase to the grab's origin
    l, t = max(l, vx), max(t, vy)
    r, b = min(r, vx + vw), min(b, vy + vh)
    if r <= l or b <= t:
        return None
    return img.crop((l - vx, t - vy, r - vx, b - vy))


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _grab_printwindow(hwnd: int, w: int, h: int):
    """PrintWindow(PW_RENDERFULLCONTENT) fallback for surfaces the screen
    BitBlt can't see (e.g. the pristine exe's own DirectDraw primary)."""
    from PIL import Image
    PW_RENDERFULLCONTENT = 2
    hdc_win = user32.GetWindowDC(hwnd)
    if not hdc_win:
        return None
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    bmi = _BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h  # top-down rows
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc_win, ctypes.byref(bmi), 0,
                                  ctypes.byref(bits), None, 0)
    img = None
    if hbmp:
        old = gdi32.SelectObject(hdc_mem, hbmp)
        if user32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT):
            raw = ctypes.string_at(bits, w * h * 4)
            img = Image.frombuffer("RGB", (w, h), raw, "raw", "BGRX", 0, 1)
        gdi32.SelectObject(hdc_mem, old)
        gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(hwnd, hdc_win)
    return img


def _looks_blank(img) -> bool:
    ext = img.convert("L").getextrema()
    return ext[0] == ext[1]


def capture(exe_override: str | None, full: bool):
    """Returns (PIL.Image, label) or raises RuntimeError."""
    if full:
        vx, vy, vw, vh = _virtual_screen()
        img = _grab_screen_region((vx, vy, vx + vw, vy + vh))
        if img is None:
            raise RuntimeError("virtual-desktop grab failed")
        return img, "desktop"

    hit = find_target_window(exe_override)
    if hit is None:
        raise RuntimeError(
            f"no visible window for {exe_override or config.exe_name()} "
            "(or any terranx*) — is the game running? Use --full for the "
            "whole desktop."
        )
    hwnd, img_name = hit
    rect = _window_rect(hwnd)
    shot = _grab_screen_region(rect)
    if shot is None or _looks_blank(shot):
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        pw = _grab_printwindow(hwnd, w, h)
        if pw is not None and not _looks_blank(pw):
            shot = pw
    if shot is None:
        raise RuntimeError("capture produced no pixels")
    return shot, Path(img_name).stem


# ------------------------------------------------------------ save + notify

def copy_to_clipboard(img) -> bool:
    """Place the image on the clipboard as CF_DIB (paste keeps working)."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    data = buf.getvalue()[14:]  # drop BITMAPFILEHEADER

    GMEM_MOVEABLE = 0x0002
    CF_DIB = 8
    for _ in range(10):  # clipboard can be transiently locked by other apps
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return False
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            return False
        p = kernel32.GlobalLock(ctypes.c_void_p(h))
        ctypes.memmove(p, data, len(data))
        kernel32.GlobalUnlock(ctypes.c_void_p(h))
        if not user32.SetClipboardData(CF_DIB, ctypes.c_void_p(h)):
            kernel32.GlobalFree(ctypes.c_void_p(h))
            return False
        return True
    finally:
        user32.CloseClipboard()


def prune_old_shots(max_age_days: int = 7) -> None:
    """Delete captures older than max_age_days from work\\screenshots."""
    if not SHOTS_DIR.is_dir():
        return
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for p in SHOTS_DIR.glob("*.png"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            pass  # in use / already gone — never let cleanup block a capture
    if removed:
        print(f"pruned {removed} screenshot(s) older than {max_age_days} days")


def save_shot(img, label: str) -> Path:
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = SHOTS_DIR / f"{label}_{img.width}x{img.height}_{stamp}.png"
    img.save(path)
    return path


def _beep(ok: bool) -> None:
    user32.MessageBeep(0x40 if ok else 0x10)  # MB_ICONASTERISK / MB_ICONHAND


def do_capture(args) -> int:
    try:
        img, label = capture(args.exe, args.full)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        _beep(False)
        return 2
    path = save_shot(img, label)
    clip = "" if args.no_clipboard else (
        " [clipboard]" if copy_to_clipboard(img) else " [clipboard FAILED]")
    print(f"saved {path}{clip}")
    _beep(True)
    return 0


# -------------------------------------------------------------- hotkey mode

_MOD_ALT, _MOD_CONTROL, _MOD_SHIFT, _MOD_WIN = 0x1, 0x2, 0x4, 0x8
_MOD_NOREPEAT = 0x4000
_VK_NAMES = {
    "prtscr": 0x2C, "printscreen": 0x2C, "prtsc": 0x2C,
    "pause": 0x13, "break": 0x13,
    "scrolllock": 0x91, "numlock": 0x90, "insert": 0x2D,
    "home": 0x24, "end": 0x23, "pgup": 0x21, "pgdn": 0x22,
}


def _parse_key(spec: str) -> tuple[int, int, str]:
    """'ctrl+f12' -> (mods, vk, pretty-label). Raises ValueError."""
    mods, vk = 0, None
    for part in (p.strip() for p in spec.lower().split("+")):
        if part in ("ctrl", "control"):
            mods |= _MOD_CONTROL
        elif part == "alt":
            mods |= _MOD_ALT
        elif part == "shift":
            mods |= _MOD_SHIFT
        elif part in ("win", "windows"):
            mods |= _MOD_WIN
        elif part in _VK_NAMES:
            vk = _VK_NAMES[part]
        elif part[:1] == "f" and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            vk = 0x70 + int(part[1:]) - 1  # f1..f24
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        else:
            raise ValueError(f"unknown key part {part!r} in {spec!r}")
    if vk is None:
        raise ValueError(f"no key named in {spec!r}")
    return mods, vk, spec


def hotkey_loop(args) -> int:
    WM_HOTKEY = 0x0312
    PM_REMOVE = 0x0001

    # Default: Pause (unused by SMAC) or Home (laptop keyboards, e.g. over
    # Moonlight, often have no Pause key). Never PrintScreen — VK_SNAPSHOT is
    # swallowed below the hotkey layer on this machine and never fires.
    if args.key:
        try:
            wanted = [_parse_key(args.key)]
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 3
    else:
        wanted = [(0, 0x13, "Pause"), (0, 0x24, "Home")]

    registered = []
    for hk_id, (mods, vk, label) in enumerate(wanted, start=1):
        if user32.RegisterHotKey(None, hk_id, mods | _MOD_NOREPEAT, vk):
            registered.append((hk_id, label))
        else:
            print(f"note: could not register {label} (in use elsewhere)",
                  file=sys.stderr)
    if not registered:
        print("ERROR: no hotkey could be registered", file=sys.stderr)
        return 3

    keys = " or ".join(label for _, label in registered)
    print(f"resident: press {keys} to capture "
          f"({'full desktop' if args.full else args.exe or config.exe_name()})"
          " — Ctrl+C here to quit")
    msg = wintypes.MSG()
    try:
        while True:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_HOTKEY:
                    do_capture(args)
            time.sleep(0.03)
    except KeyboardInterrupt:
        return 0
    finally:
        for hk_id, _ in registered:
            user32.UnregisterHotKey(None, hk_id)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hotkey", action="store_true",
                    help="stay resident; Pause or Home triggers a capture")
    ap.add_argument("--key", metavar="SPEC",
                    help="hotkey to use instead of the Pause/Home defaults, "
                         "e.g. 'f9', 'ctrl+shift+s'")
    ap.add_argument("--exe", metavar="NAME",
                    help="process image name to capture (default: configured "
                         "target exe, then any terranx*)")
    ap.add_argument("--full", action="store_true",
                    help="capture the whole virtual desktop instead")
    ap.add_argument("--no-clipboard", action="store_true",
                    help="do not put the image on the clipboard")
    args = ap.parse_args()

    _set_dpi_aware()
    prune_old_shots()
    if args.hotkey:
        return hotkey_loop(args)
    return do_capture(args)


if __name__ == "__main__":
    sys.exit(main())
