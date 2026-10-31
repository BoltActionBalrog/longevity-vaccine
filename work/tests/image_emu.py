"""Shared real-image emulator for end-to-end UI tests: the REAL terranx_PRACX image under Unicorn.

The low-level layer only -- Emu (memory map, import stubs with host GDI for fonts and text metrics, the CRT
allocators, observers, `call`), boot() (the engine's own startup chain up to the point a popup can open: text
buffers, C++ static ctors, g_popup_scale_num, the popup factory, the engine library subsystems, config_popups),
Files (read-only CRT FILE* service for the game's text files) and canvas_of (a window's 8-bit canvas).  Every engine
function and cave thunk runs for real; only OS imports and the CRT allocators are served by Python.

Lineage: the audit18..20 harnesses (scratch, which reproduced the user's ornate-popup shots stroke for
stroke), first carried in tests as fix 26's ornate_popup_emu.py.  Split out here by fix 29
(popup_listbox_emu.py) so a guard does not depend on another arc's module.  NOTE: fix 26's ornate_popup_emu.py should
import this module instead of carrying its own copy of the layer (one harness, one place to fix it).

No state is shared between Emu instances: every boot() maps a fresh image, so items are independent (xdist-safe).
The host font resource (the game's arialn.ttf, FR_PRIVATE) and the host DC are loaded once per process.
"""
import ctypes
import functools
import os
import struct
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import config  # noqa: E402
import pefile
from unicorn import (Uc, UcError, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED, UC_HOOK_MEM_WRITE,
                     UC_PROT_ALL)
from unicorn.x86_const import *  # noqa: F401,F403

GAME = str(config.game_dir(required=False))

STACK, STACK_SZ = 0x10000000, 0x200000
HEAP, HEAP_SZ = 0x20000000, 0x4000000
STUB, STUB_SZ = 0x0BEE0000, 0x10000
SENT = 0x0BEEF000                 # return sentinel (inside STUB page block)
GDT, TEB = 0x00030000, 0x00031000

SW, SH, GSCALE = 0x9B7B1C, 0x9B7B20, 0x668740

# stdcall arg counts of the imports we serve (unknown -> stop with a message)
NARGS = dict(
    SetDIBits=7, CreateDCA=4, RemoveFontResourceA=1, MoveToEx=4, CreatePenIndirect=1, SetSystemPaletteUse=2,
    BitBlt=9, DeleteObject=1, DeleteDC=1, SelectObject=2, SetTextAlign=2, SetBkMode=2, CreateDIBSection=6,
    CreateCompatibleDC=1, SelectClipRgn=2, CreateRectRgnIndirect=1, StretchBlt=11, GetDeviceCaps=2, GdiFlush=0,
    GetTextExtentPoint32A=4, CreateScalableFontResourceA=4, AddFontResourceA=1, CreateFontIndirectA=1,
    GetTextMetricsA=2, RealizePalette=1, GetPaletteEntries=4, CreatePalette=1, AnimatePalette=4,
    GetSystemPaletteEntries=4, SetTextColor=2, SetDIBColorTable=4, SelectPalette=3, TextOutA=5, GetStockObject=1,
    LineTo=3, SetArcDirection=2, CreateSolidBrush=1, Pie=9, SetStretchBltMode=2, Ellipse=5,
    SetRect=5, ValidateRect=2, GetDC=1, ReleaseDC=2, GetCursorPos=1, SetCursor=1, FillRect=3, GetWindowRect=2,
    EqualRect=2, PtInRect=3, ClientToScreen=2, ScreenToClient=2, InvalidateRect=3, UnionRect=3, IntersectRect=3,
    IsRectEmpty=1, GetSystemMetrics=1, GetKeyState=1, GetAsyncKeyState=1, ShowCursor=1, IsZoomed=1, GetFocus=0,
    PeekMessageA=5, SendMessageA=4, PostMessageA=4, SetTimer=4, KillTimer=2, MessageBeep=1, CharUpperA=1,
    CharLowerA=1, GetWindowLongA=2, SetWindowLongA=3, IsWindow=1, GetParent=1, MoveWindow=6, ShowWindow=2,
    GetTickCount=0, HeapAlloc=3, HeapFree=3, HeapReAlloc=4, HeapSize=3, VirtualAlloc=4, VirtualFree=3,
    InterlockedIncrement=1, InterlockedDecrement=1, InterlockedExchange=2, EnterCriticalSection=1,
    LeaveCriticalSection=1, InitializeCriticalSection=1, GetLastError=0, SetLastError=1, Sleep=1,
    GetCurrentThreadId=0, TlsGetValue=1, TlsSetValue=2, OutputDebugStringA=1, GetPrivateProfileIntA=4,
    GetPrivateProfileStringA=6, WritePrivateProfileStringA=4, MultiByteToWideChar=6, WideCharToMultiByte=8,
    GetStringTypeA=5, LCMapStringA=6, GetACP=0, GetCPInfo=2, IsBadReadPtr=2, IsBadWritePtr=2, timeGetTime=0,
    FindFirstFileA=2, FindNextFileA=2, FindClose=1, LoadCursorA=2, CreateIconIndirect=1, DestroyCursor=1,
    CreateFileA=7, ReadFile=5, SetFilePointer=4, GetFileSize=2, CloseHandle=1, CreateFileMappingA=6,
    MapViewOfFile=5, UnmapViewOfFile=1, WriteFile=5, GetFileType=1,
    EnumThreadWindows=3, GetCurrentProcess=0, GetModuleHandleA=1, ReleaseCapture=0, SetCursorPos=2, IsChild=2, GetParent_=1,
    GetProcAddress=2, GetGlyphOutlineA=7,
)

# ---------------------------------------------------------------- host GDI (fonts / text metrics only)
_g = ctypes.WinDLL("gdi32")
_g.CreateCompatibleDC.restype = ctypes.c_void_p
_g.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
_g.CreateFontIndirectA.restype = ctypes.c_void_p
_g.CreateFontIndirectA.argtypes = [ctypes.c_char_p]
_g.SelectObject.restype = ctypes.c_void_p
_g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_g.GetTextExtentPoint32A.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p]
_g.GetTextMetricsA.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_g.GetTextFaceA.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p]
_g.AddFontResourceExA.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_void_p]
_g.GetGlyphOutlineA.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
                                ctypes.c_void_p, ctypes.c_void_p]
_g.GetGlyphOutlineA.restype = ctypes.c_uint32
GDI32_HMODULE = 0x77E10000        # what GetModuleHandleA("gdi32.dll") answers (any other module: 0, as before)
PROC_STUB = 0x7F00                # STUB + this: the stub GetProcAddress hands out for a served function
_FR_PRIVATE = 0x10
HOSTDC = None


def _host_init():
    """The game's own arialn.ttf, private to this process (the engine's label font), and one host DC."""
    global HOSTDC
    if HOSTDC is None:
        added = _g.AddFontResourceExA(os.path.join(GAME, "arialn.ttf").encode(), _FR_PRIVATE, None)
        assert added, "arialn.ttf did not load"
        HOSTDC = _g.CreateCompatibleDC(None)


@functools.lru_cache(maxsize=4)
def _parse(exe, mtime_ns, size):
    pe = pefile.PE(exe)
    img = pe.get_memory_mapped_image()
    imports = []
    for e in pe.DIRECTORY_ENTRY_IMPORT:
        for imp in e.imports:
            imports.append((imp.name.decode() if imp.name else f"{e.dll.decode()}#{imp.ordinal}", imp.address))
    out = (pe.OPTIONAL_HEADER.ImageBase, img,
           (max(len(img), pe.OPTIONAL_HEADER.SizeOfImage) + 0xFFF) & ~0xFFF, tuple(imports))
    pe.close()
    return out


def _image(exe):
    """(image base, mapped image bytes, mapped size, ((import name, IAT va), ...)) -- parsed once per process per
    file version (keyed on path + mtime + size), so a module's items boot without re-parsing the PE."""
    st = os.stat(exe)
    return _parse(os.path.abspath(exe), st.st_mtime_ns, st.st_size)


class Emu:
    def __init__(self, exe, w, h, trace_calls=False):
        _host_init()
        self.exe = exe
        self.ib, img, size, imports = _image(exe)
        self.image_end = self.ib + size     # SizeOfImage: the last section (pcave2) ends here, whatever its length
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(self.ib, size, UC_PROT_ALL)
        uc.mem_write(self.ib, img)
        uc.mem_map(STACK, STACK_SZ)
        uc.mem_map(HEAP, HEAP_SZ)
        uc.mem_map(STUB, STUB_SZ)
        uc.mem_write(STUB, b"\xC3" * STUB_SZ)
        self.heap = HEAP + 0x1000
        self._gdt()
        # imports -> stubs
        self.imp = {}
        for i, (name, iat) in enumerate(imports):
            a = STUB + 0x100 + i * 4
            self.imp[a] = name
            uc.mem_write(iat, struct.pack("<I", a))
        self.fn_stub = {}          # va -> (handler, nargs_popped_bytes)
        self.log = []
        self.calls = defaultdict(int)
        self.handles = {}          # emu handle -> host handle
        self.next_handle = 0x7000
        self.dc_font = {}          # emu dc -> emu font handle
        uc.hook_add(UC_HOOK_CODE, self._stub_hook, begin=STUB, end=STUB + STUB_SZ - 1)
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._unmapped)
        self.w32(SW, w)
        self.w32(SH, h)
        self.watch = []            # (lo, hi, label) memory-write watch ranges
        self.writes = []
        self.hooks_at = {}         # va -> callback(emu) (observer, code continues)

    # ---------------------------------------------------------------- basics
    def _gdt(self):
        uc = self.uc
        uc.mem_map(GDT, 0x2000)

        def ent(base, limit, access, flags):
            e = limit & 0xFFFF
            e |= (base & 0xFFFFFF) << 16
            e |= (access & 0xFF) << 40
            e |= ((limit >> 16) & 0xF) << 48
            e |= (flags & 0xF) << 52
            e |= ((base >> 24) & 0xFF) << 56
            return struct.pack("<Q", e)
        g = [b"\0" * 8, ent(0, 0xFFFFF, 0x9A, 0xC), ent(0, 0xFFFFF, 0x92, 0xC), ent(TEB, 0xFFF, 0x92, 0x4)]
        uc.mem_write(GDT, b"".join(g))
        uc.reg_write(UC_X86_REG_GDTR, (0, GDT, len(g) * 8 - 1, 0))
        uc.reg_write(UC_X86_REG_FS, 3 << 3)
        uc.reg_write(UC_X86_REG_SS, 2 << 3)
        uc.reg_write(UC_X86_REG_DS, 2 << 3)
        uc.reg_write(UC_X86_REG_ES, 2 << 3)
        uc.mem_write(TEB, struct.pack("<I", 0xFFFFFFFF))
        uc.mem_write(TEB + 0x18, struct.pack("<I", TEB))

    def r32(self, a):
        return struct.unpack("<I", bytes(self.uc.mem_read(a, 4)))[0]

    def s32(self, a):
        return struct.unpack("<i", bytes(self.uc.mem_read(a, 4)))[0]

    def w32(self, a, v):
        self.uc.mem_write(a, struct.pack("<I", v & 0xFFFFFFFF))

    def rstr(self, a, n=512):
        b = bytes(self.uc.mem_read(a, n))
        return b.split(b"\0")[0]

    def alloc(self, n, zero=True):
        a = (self.heap + 15) & ~15
        self.heap = a + max(n, 1)
        assert self.heap < HEAP + HEAP_SZ, "emu heap exhausted"
        if zero:
            self.uc.mem_write(a, b"\0" * max(n, 1))
        return a

    def cstr(self, s):
        b = s.encode("latin-1") + b"\0"
        a = self.alloc(len(b))
        self.uc.mem_write(a, b)
        return a

    def reg(self, r):
        return self.uc.reg_read(r)

    def _unmapped(self, uc, access, addr, size, value, ud):
        eip = uc.reg_read(UC_X86_REG_EIP)
        self.log.append(("unmapped", access, addr, size, eip))
        return False

    # ---------------------------------------------------------------- stubs
    def _ret(self, nbytes, eax=None):
        uc = self.uc
        esp = uc.reg_read(UC_X86_REG_ESP)
        ret = self.r32(esp)
        if eax is not None:
            uc.reg_write(UC_X86_REG_EAX, eax & 0xFFFFFFFF)
        uc.reg_write(UC_X86_REG_ESP, esp + 4 + nbytes)
        uc.reg_write(UC_X86_REG_EIP, ret)

    def arg(self, i):
        return self.r32(self.uc.reg_read(UC_X86_REG_ESP) + 4 + 4 * i)

    def _stub_hook(self, uc, addr, size, ud):
        if addr == SENT:
            uc.emu_stop()
            return
        if addr in self.imp:
            name = self.imp[addr]
            self.calls[name] += 1
            h = getattr(self, "api_" + name, None)
            if name not in NARGS:
                self.log.append(("unhandled-import", name, self.r32(uc.reg_read(UC_X86_REG_ESP))))
                uc.emu_stop()
                self.fault = name
                return
            rv = h() if h else 0
            if not h:
                self.log.append(("import-default0", name, self.r32(uc.reg_read(UC_X86_REG_ESP))))
            self._ret(4 * NARGS[name], 0 if rv is None else rv)
            return
        if addr in self.fn_stub:
            fn, nb = self.fn_stub[addr]
            rv = fn(self)
            self._ret(nb, rv)
            return

    def stub_fn(self, va, fn, popbytes=0):
        """Redirect engine function va to a python stub (va's first bytes become a jmp to a stub slot)."""
        slot = STUB + 0x8000 + len(self.fn_stub) * 8
        self.fn_stub[slot] = (fn, popbytes)
        rel = slot - (va + 5)
        self.uc.mem_write(va, b"\xE9" + struct.pack("<i", rel))
        self.stubbed = getattr(self, "stubbed", {})
        self.stubbed[va] = fn.__name__ if hasattr(fn, "__name__") else str(fn)

    def observe(self, va, cb):
        self.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: cb(self), begin=va, end=va)

    # ---------------------------------------------------------------- calling
    def call(self, va, args=(), ecx=None, regs=None, count=0, timeout=0):
        uc = self.uc
        esp = STACK + STACK_SZ - 0x1000 if not hasattr(self, "_esp_base") else self._esp_base
        esp -= 4 * len(args)
        for i, a in enumerate(args):
            self.w32(esp + 4 * i, a)
        esp -= 4
        self.w32(esp, SENT)
        uc.reg_write(UC_X86_REG_ESP, esp)
        uc.reg_write(UC_X86_REG_EBP, 0)
        if ecx is not None:
            uc.reg_write(UC_X86_REG_ECX, ecx)
        for r, v in (regs or {}).items():
            uc.reg_write(r, v)
        self.fault = None
        try:
            uc.emu_start(va, SENT, timeout=timeout, count=count)
        except UcError as e:
            eip = uc.reg_read(UC_X86_REG_EIP)
            raise RuntimeError(f"emu error {e} at eip {eip:#x} bt {self.bt()}") from e
        if self.fault:
            raise RuntimeError(f"stopped: {self.fault}")
        return uc.reg_read(UC_X86_REG_EAX)

    def bt(self, n=24):
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        out = []
        for k in range(0, 0x800, 4):
            v = self.r32(esp + k)
            if 0x401000 <= v < 0x664000 or 0xA0C000 <= v < self.image_end or 0x668000 <= v < 0x669000:
                b = bytes(self.uc.mem_read(v - 5, 5))
                b6 = bytes(self.uc.mem_read(v - 6, 6))
                b3 = bytes(self.uc.mem_read(v - 3, 3))
                b2 = bytes(self.uc.mem_read(v - 2, 2))
                if b[0] == 0xE8 or b6[0] == 0xFF or b3[0] == 0xFF or b2[0] == 0xFF:
                    out.append(hex(v))
            if len(out) >= n:
                break
        return " ".join(out)

    # ---------------------------------------------------------------- handle table
    def new_handle(self, host=None, kind=""):
        h = self.next_handle
        self.next_handle += 4
        self.handles[h] = (host, kind)
        return h

    # ---------------------------------------------------------------- imports (host GDI where metrics matter)
    def api_FindFirstFileA(self):
        return 0xFFFFFFFF

    def api_GetTickCount(self):
        return 100000

    def api_timeGetTime(self):
        return 100000

    def api_HeapAlloc(self):
        return self.alloc(self.arg(2))

    def api_HeapReAlloc(self):
        old, n = self.arg(2), self.arg(3)
        a = self.alloc(n)
        if old:
            self.uc.mem_write(a, bytes(self.uc.mem_read(old, n)))
        return a

    def api_HeapFree(self):
        return 1

    def api_HeapSize(self):
        return 0x100000

    def api_VirtualAlloc(self):
        return self.alloc(self.arg(1))

    def api_InterlockedIncrement(self):
        a = self.arg(0)
        v = self.r32(a) + 1
        self.w32(a, v)
        return v

    def api_InterlockedDecrement(self):
        a = self.arg(0)
        v = self.r32(a) - 1
        self.w32(a, v)
        return v

    def api_GetSystemMetrics(self):
        i = self.s32(self.uc.reg_read(UC_X86_REG_ESP) + 4)
        return {0: self.r32(SW), 1: self.r32(SH)}.get(i, 0)

    def _rect(self, a):
        return list(struct.unpack("<iiii", bytes(self.uc.mem_read(a, 16))))

    def _wrect(self, a, r):
        self.uc.mem_write(a, struct.pack("<iiii", *r))

    def api_SetRect(self):
        a = self.arg(0)
        self._wrect(a, [struct.unpack("<i", struct.pack("<I", self.arg(i)))[0] for i in (1, 2, 3, 4)])
        return 1

    def api_UnionRect(self):
        d, a, b = self.arg(0), self.arg(1), self.arg(2)
        ra, rb = self._rect(a), self._rect(b)
        ea = ra[0] >= ra[2] or ra[1] >= ra[3]
        eb = rb[0] >= rb[2] or rb[1] >= rb[3]
        if ea and eb:
            r = [0, 0, 0, 0]
        elif ea:
            r = rb
        elif eb:
            r = ra
        else:
            r = [min(ra[0], rb[0]), min(ra[1], rb[1]), max(ra[2], rb[2]), max(ra[3], rb[3])]
        self._wrect(d, r)
        return 0 if r == [0, 0, 0, 0] else 1

    def api_IntersectRect(self):
        d, a, b = self.arg(0), self.arg(1), self.arg(2)
        ra, rb = self._rect(a), self._rect(b)
        r = [max(ra[0], rb[0]), max(ra[1], rb[1]), min(ra[2], rb[2]), min(ra[3], rb[3])]
        if r[0] >= r[2] or r[1] >= r[3]:
            r = [0, 0, 0, 0]
        self._wrect(d, r)
        return 0 if r == [0, 0, 0, 0] else 1

    def api_IsRectEmpty(self):
        r = self._rect(self.arg(0))
        return 1 if r[0] >= r[2] or r[1] >= r[3] else 0

    def api_EqualRect(self):
        return 1 if self._rect(self.arg(0)) == self._rect(self.arg(1)) else 0

    def api_PtInRect(self):
        r = self._rect(self.arg(0))
        x, y = struct.unpack("<ii", struct.pack("<II", self.arg(1), self.arg(2)))
        return 1 if r[0] <= x < r[2] and r[1] <= y < r[3] else 0

    def api_CreateCompatibleDC(self):
        return self.new_handle(None, "dc")

    def api_GetDC(self):
        return self.new_handle(None, "dc")

    def api_CreateDCA(self):
        return self.new_handle(None, "dc")

    def api_GetStockObject(self):
        return self.new_handle(None, "stock")

    def api_CreateFontIndirectA(self):
        lf = bytes(self.uc.mem_read(self.arg(0), 60))
        host = _g.CreateFontIndirectA(lf)
        h = self.new_handle(host, "font")
        height, width, esc, orient, weight = struct.unpack_from("<iiiii", lf, 0)
        self.log.append(("font", h, lf[28:60].split(b"\0")[0].decode("latin-1"), height, weight, lf[20]))
        return h

    def api_SelectObject(self):
        dc, obj = self.arg(0), self.arg(1)
        if self.handles.get(obj, (None, ""))[1] == "dib":
            self.dc_dib = getattr(self, "dc_dib", {})
            old = self.dc_dib.get(dc, 0)
            self.dc_dib[dc] = obj
            return old or self.new_handle(None, "oldbmp")
        prev = self.dc_font.get(dc, 0)
        if self.handles.get(obj, (None, ""))[1] == "font":
            self.dc_font[dc] = obj
            return prev or self.new_handle(None, "oldfont")
        return self.new_handle(None, "old")

    def _host_sel(self, dc):
        f = self.dc_font.get(dc)
        host = self.handles.get(f, (None,))[0]
        assert host, f"no host font selected on emu dc {dc:#x}"
        _g.SelectObject(HOSTDC, host)

    def api_GetTextMetricsA(self):
        dc, out = self.arg(0), self.arg(1)
        self._host_sel(dc)
        tm = ctypes.create_string_buffer(64)
        _g.GetTextMetricsA(HOSTDC, tm)
        face = ctypes.create_string_buffer(64)
        _g.GetTextFaceA(HOSTDC, 64, face)
        self.log.append(("face", face.value))
        self.uc.mem_write(out, tm.raw[:56])
        return 1

    def api_GetTextExtentPoint32A(self):
        dc, s, n, out = self.arg(0), self.arg(1), self.arg(2), self.arg(3)
        self._host_sel(dc)
        txt = bytes(self.uc.mem_read(s, n)) if n > 0 else b""
        sz = (ctypes.c_long * 2)()
        _g.GetTextExtentPoint32A(HOSTDC, txt, n, sz)
        self.uc.mem_write(out, struct.pack("<ii", sz[0], sz[1]))
        return 1

    def api_GetDeviceCaps(self):
        return {90: 96, 88: 96, 12: 8, 104: 8}.get(self.arg(1), 0)

    def api_CreateDIBSection(self):
        bmi, ppv = self.arg(1), self.arg(3)          # audit19: ppvBits is the 4th arg (index 3)
        w, h = struct.unpack("<ii", bytes(self.uc.mem_read(bmi + 4, 8)))
        bpp = struct.unpack("<H", bytes(self.uc.mem_read(bmi + 14, 2)))[0]
        n = ((abs(w) * max(1, bpp // 8) + 3) & ~3) * abs(h) + 64
        bits = self.alloc(n)
        if ppv:
            self.w32(ppv, bits)
        h_ = self.new_handle(None, "dib")
        self.dibs = getattr(self, "dibs", {})
        self.dibs[h_] = (w, h, bpp, bits)
        self.log.append(("dib", h_, w, h, bpp, bits))
        return h_

    def api_StretchBlt(self):
        # audit19: the engine stretch = GDI StretchBlt (COLORONCOLOR, SRCCOPY) on 8-bit DIBs; modelled as the
        # MEASURED centre-aligned NN (CLAUDE.md 'measure the engine': the shipped stretch blit is centre-aligned NN)
        a = [struct.unpack('<i', struct.pack('<I', self.arg(i)))[0] for i in range(11)]
        hd, xd, yd, wd, hd_, hs, xs, ys, ws, hs_, rop = a
        dd, ds = self.dc_dib.get(hd & 0xFFFFFFFF), self.dc_dib.get(hs & 0xFFFFFFFF)
        self.sblt = getattr(self, "sblt", [])
        self.sblt.append((xd, yd, wd, hd_, xs, ys, ws, hs_, hex(rop & 0xFFFFFFFF), dd, ds))
        if not dd or not ds or wd <= 0 or hd_ <= 0 or ws <= 0 or hs_ <= 0:
            return 0
        (dw, dh, dbpp, dbits), (sw, sh, sbpp, sbits) = self.dibs[dd], self.dibs[ds]
        assert dbpp == 8 and sbpp == 8
        dst_stride, src_stride = (abs(dw) + 3) & ~3, (abs(sw) + 3) & ~3
        src = bytes(self.uc.mem_read(sbits, src_stride * abs(sh)))
        for j in range(hd_):
            y = yd + j
            if not 0 <= y < abs(dh):
                continue
            sy = ys + min(((2 * j + 1) * hs_) // (2 * hd_), hs_ - 1)
            row = bytearray()
            for i in range(wd):
                sx = xs + min(((2 * i + 1) * ws) // (2 * wd), ws - 1)
                row.append(src[sy * src_stride + sx])
            x0 = max(xd, 0); x1 = min(xd + wd, abs(dw))
            if x1 > x0:
                self.uc.mem_write(dbits + y * dst_stride + x0, bytes(row[x0 - xd:x1 - xd]))
        return 1

    def api_GetModuleHandleA(self):
        """gdi32 only (W8T t1c_pdesc resolves GetGlyphOutlineA through it); every other module 0, as before."""
        name = self.rstr(self.arg(0), 64).lower() if self.arg(0) else b""
        return GDI32_HMODULE if name in (b"gdi32.dll", b"gdi32") else 0

    def api_GetProcAddress(self):
        """GetGlyphOutlineA from gdi32 -> a stub served by api_GetGlyphOutlineA; anything else 0 (not found)."""
        if self.arg(0) != GDI32_HMODULE or self.rstr(self.arg(1), 64) != b"GetGlyphOutlineA":
            return 0
        a = STUB + PROC_STUB
        self.imp[a] = "GetGlyphOutlineA"
        return a

    def api_GetGlyphOutlineA(self):
        """Host GDI on the emu DC's selected font: the GLYPHMETRICS (GGO_METRICS with a MAT2) the real call returns."""
        dc, ch, fmt, gm, cb, buf, mat = (self.arg(i) for i in range(7))
        self._host_sel(dc)
        out = ctypes.create_string_buffer(20)
        m = ctypes.create_string_buffer(bytes(self.uc.mem_read(mat, 16)), 16)
        r = _g.GetGlyphOutlineA(HOSTDC, ch & 0xFF, fmt, out, 0, None, m)
        self.uc.mem_write(gm, out.raw[:20])
        return r

    def api_GetTextFaceA(self):
        return 0

    # ---------------------------------------------------------------- ini (host, read-only, the real game ini)
    def _ini(self, a):
        p = self.rstr(a).decode("latin-1") if a else ""
        if not os.path.isabs(p):
            p = os.path.join(GAME, p.lstrip("./" + chr(92)))
        return p

    def api_GetPrivateProfileStringA(self):
        app, key, dflt, buf, n, f = (self.arg(i) for i in range(6))
        k32 = ctypes.WinDLL("kernel32")
        out = ctypes.create_string_buffer(max(n, 1))
        r = k32.GetPrivateProfileStringA(self.rstr(app) if app else None, self.rstr(key) if key else None,
                                         self.rstr(dflt) if dflt else b"", out, n, self._ini(f).encode())
        self.uc.mem_write(buf, out.raw[:max(r + 1, 1)])
        self.log.append(("ini", self.rstr(app) if app else None, self.rstr(key) if key else None, out.value))
        return r

    def api_GetPrivateProfileIntA(self):
        app, key, dflt, f = (self.arg(i) for i in range(4))
        k32 = ctypes.WinDLL("kernel32")
        r = k32.GetPrivateProfileIntA(self.rstr(app), self.rstr(key), dflt, self._ini(f).encode())
        self.log.append(("ini", self.rstr(app), self.rstr(key), r))
        return r

    # ---------------------------------------------------------------- read-only Win32 files (the game dir)
    def api_CreateFileA(self):
        name = self.rstr(self.arg(0)).decode("latin-1")
        access, disp = self.arg(1), self.arg(4)
        p = name if os.path.isabs(name) else os.path.join(GAME, name)
        self.log.append(("CreateFileA", name, hex(access), disp))
        if access & 0x40000000 or not os.path.isfile(p):          # GENERIC_WRITE or missing -> fail
            return 0xFFFFFFFF
        h = self.new_handle(None, "file")
        self.files = getattr(self, "files", {})
        self.files[h] = [open(p, "rb").read(), 0]
        return h

    def api_ReadFile(self):
        h, buf, n, pread = self.arg(0), self.arg(1), self.arg(2), self.arg(3)
        data, pos = self.files[h]
        chunk = data[pos:pos + n]
        self.uc.mem_write(buf, chunk)
        self.files[h][1] = pos + len(chunk)
        if pread:
            self.w32(pread, len(chunk))
        return 1

    def api_SetFilePointer(self):
        h, off, hi, wh = self.arg(0), self.s32(self.uc.reg_read(UC_X86_REG_ESP) + 8), self.arg(2), self.arg(3)
        data, pos = self.files[h]
        self.files[h][1] = {0: off, 1: pos + off, 2: len(data) + off}[wh]
        return self.files[h][1]

    def api_GetFileSize(self):
        h = self.arg(0)
        if self.arg(1):
            self.w32(self.arg(1), 0)
        return len(self.files[h][0])

    def api_CloseHandle(self):
        return 1

    def api_CreateFileMappingA(self):
        h = self.arg(0)
        m = self.new_handle(None, "mapping")
        self.maps = getattr(self, "maps", {})
        self.maps[m] = h
        return m

    def api_MapViewOfFile(self):
        m = self.arg(0)
        data = self.files[self.maps[m]][0]
        a = self.alloc(len(data) + 16)
        self.uc.mem_write(a, data)
        return a

    def api_UnmapViewOfFile(self):
        return 1


# ================================================================ boot
def crt_stubs(e):
    def malloc(e):
        return e.alloc(e.arg(0))
    def free(e):
        return 0
    def atexit(e):
        return 0
    def calloc(e):
        return e.alloc(e.arg(0) * e.arg(1))
    for va in (0x6470A6, 0x64558A):
        e.stub_fn(va, malloc)
    for va in (0x644EF2, 0x64557F):
        e.stub_fn(va, free)
    e.stub_fn(0x645398, atexit)


SKIP_CTORS = {0x668160, 0x625F20}   # _SELFMOD loader (LoadLibrary: PRACX/uimod DLLs, not emulated), a save-dir scan


def boot(exe, w, h, popups=True, verbose=False):
    e = Emu(exe, w, h)
    crt_stubs(e)
    e.w32(0x9B7B28, 0x00012340)       # the main HWND (FUN_0060e800 refuses to attach without one)
    e.call(0x5FD400)                  # text_init
    e.call(0x5FD4C0)
    e.call(0x5FD4D0)
    for a in range(0x682000, 0x6826CC, 4):          # C++ static constructors (__xc table, CRT _initterm 0x644DEC)
        f = e.r32(a)
        if f and f not in SKIP_CTORS:
            e.call(f, count=2000000)
    if bytes(e.uc.mem_read(0x668760, 4)) != bytes(4):
        e.call(0x668760)              # g_popup_scale_num (patched lazy init; absent from the pristine image)
    if popups:
        e.w32(0x696ECC, 0x404FB0)     # WinMain 0x45F996: the popup factory = Popup_alloc (Popup objects, vtbl 0x6695C8)
        # the engine library init 0x62D3A0's subsystem chain (0x62D43A..0x62D4AD) with the default Font 0x7D3948
        for va, args in ((0x5DF570, ()), (0x60FC60, ()), (0x6339A0, ()), (0x60E4D0, ()),
                         (0x6074B0, (0x7D3948, 0, 0)), (0x6195B0, (0x7D3948,)), (0x604590, ()), (0x614D90, ()),
                         (0x63CE20, ())):
            try:
                r = e.call(va, args=args, count=5000000)
            except RuntimeError as x:
                r = None
                e.init_failed = getattr(e, "init_failed", []) + [(hex(va), str(x)[:160])]
        e.w32(0x9B7AF4, e.r32(0x9BB484))
        e.call(0x63B940)
        e.call(0x63B910)
        # startup re-inits the default label Font "Arial" 12 regular (probe hook_btnfont_probe.js)
        e.call(0x618F40, ecx=0x7D3948, args=(e.cstr("Arial"), 12, 0))
        e.call(0x588AA0)              # config_popups (font pool, popup default fonts; calls popups_normal)
    return e


class Files:
    """CRT FILE* level read-only file service: fopen 0x645646 (and the path wrapper 0x634BB0), fgets 0x64726A,
    fclose 0x645598, rewind 0x6472CC, fseek 0x647330, ftell?  The engine's text parser above it runs for real."""
    def __init__(self, e):
        self.e, self.f = e, {}
        e.stub_fn(0x634BB0, self.fopen)
        e.stub_fn(0x645646, self.fopen)
        e.stub_fn(0x64726A, self.fgets)
        e.stub_fn(0x645598, self.fclose)
        e.stub_fn(0x6472CC, self.rewind)
        e.stub_fn(0x647330, self.fseek)
        self.opened = []

    def fopen(self, e):
        name = e.rstr(e.arg(0)).decode("latin-1")
        mode = e.rstr(e.arg(1)).decode("latin-1")
        p = os.path.join(GAME, name)
        self.opened.append((name, mode))
        if "w" in mode or "a" in mode or "+" in mode or not os.path.isfile(p):
            return 0
        fp = e.alloc(0x40)
        data = open(p, "rb").read()
        if "b" not in mode:
            data = data.replace(bytes([13, 10]), bytes([10]))          # CRT text mode
        self.f[fp] = [data, 0]
        return fp

    def fgets(self, e):
        buf, n, fp = e.arg(0), e.arg(1), e.arg(2)
        data, pos = self.f[fp]
        if pos >= len(data):
            e.w32(fp + 0xC, e.r32(fp + 0xC) | 0x10)
            return 0
        j = data.find(b"\n", pos)
        j = len(data) if j < 0 else j + 1
        j = min(j, pos + n - 1)
        e.uc.mem_write(buf, data[pos:j] + b"\0")
        self.f[fp][1] = j
        return buf

    def fclose(self, e):
        self.f.pop(e.arg(0), None)
        return 0

    def rewind(self, e):
        fp = e.arg(0)
        self.f[fp][1] = 0
        e.w32(fp + 0xC, e.r32(fp + 0xC) & ~0x10)
        return 0

    def fseek(self, e):
        fp, off, wh = e.arg(0), e.s32(e.uc.reg_read(UC_X86_REG_ESP) + 8), e.arg(2)
        data, pos = self.f[fp]
        self.f[fp][1] = {0: off, 1: pos + off, 2: len(data) + off}[wh]
        e.w32(fp + 0xC, e.r32(fp + 0xC) & ~0x10)
        return 0


# ================================================================ canvases
PDS = 0x6A721C


def canvas_of(e, win):
    bits = e.r32(win + 0x498)
    w = e.s32(win + 0x444 + 0x38)
    h = abs(e.s32(win + 0x444 + 0x3C))
    if not bits or w <= 0 or h <= 0 or w > 8000 or h > 8000:
        return None
    st = (w + 3) & ~3
    return np.frombuffer(bytes(e.uc.mem_read(bits, st * h)), np.uint8).reshape(h, st)[:, :w].copy()
