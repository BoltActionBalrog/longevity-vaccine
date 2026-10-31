"""Real text ink in the real-image emulator (image_emu.py): a host-GDI TextOutA that draws the string, non-antialiased
(the game draws into an 8-bit DIB), into the emulated 8-bit DIB the DC has selected, honouring the selected clip region
and text alignment; every call is logged (string, x, y, ink rows) so a test can read where a label's ink lands.

Ported from the W8T audit's textemu.py (2026-10-27), which was calibrated against six of the user's real shots.  Used
as a context manager so the patch never leaks into another test of the same worker (image_emu's TextOutA is a no-op
for every other module):

    with text_rendering() as log:
        hh = ornate_popup_emu.H(...)
    log -> [(text[:40], x, y, ink_top, ink_bottom_exclusive, dib_height), ...] in call order
"""
from __future__ import annotations

import contextlib
import ctypes
import struct

import numpy as np

import image_emu as E

_g = ctypes.WinDLL("gdi32")
_g.CreateCompatibleDC.restype = ctypes.c_void_p
_g.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
_g.CreateFontIndirectA.restype = ctypes.c_void_p
_g.CreateFontIndirectA.argtypes = [ctypes.c_char_p]
_g.SelectObject.restype = ctypes.c_void_p
_g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_g.CreateDIBSection.restype = ctypes.c_void_p
_g.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p),
                                ctypes.c_void_p, ctypes.c_uint]
_g.TextOutA.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
_g.SetTextAlign.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_g.SetBkMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
_g.SetTextColor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_g.DeleteObject.argtypes = [ctypes.c_void_p]
_DC = None
_NAA = {}


def _s32(v):
    return struct.unpack("<i", struct.pack("<I", v & 0xFFFFFFFF))[0]


def _install(log):
    global _DC
    if _DC is None:
        _DC = _g.CreateCompatibleDC(None)
    orig_cf = E.Emu.api_CreateFontIndirectA

    def api_CreateFontIndirectA(self):
        lf = bytes(self.uc.mem_read(self.arg(0), 60))
        h = orig_cf(self)
        self.__dict__.setdefault("_lf", {})[h] = lf
        return h

    def api_SetTextAlign(self):
        self.__dict__.setdefault("_ta", {})[self.arg(0)] = self.arg(1)
        return 0

    def api_SetTextColor(self):
        self.__dict__.setdefault("_tc", {})[self.arg(0)] = self.arg(1)
        return 0

    def api_CreateRectRgnIndirect(self):
        r = struct.unpack("<4i", bytes(self.uc.mem_read(self.arg(0), 16)))
        h = self.new_handle(None, "rgn")
        self.__dict__.setdefault("_rgn", {})[h] = r
        return h

    def api_SelectClipRgn(self):
        rg = self.arg(1)
        self.__dict__.setdefault("_clip", {})[self.arg(0)] = self.__dict__.get("_rgn", {}).get(rg) if rg else None
        return 1

    def api_TextOutA(self):
        dc, x, y, s, n = (self.arg(i) for i in range(5))
        x, y, n = _s32(x), _s32(y), _s32(n)
        dib = getattr(self, "dc_dib", {}).get(dc)
        lf = self.__dict__.get("_lf", {}).get(self.dc_font.get(dc))
        if not dib or n <= 0 or lf is None:
            return 1
        w, h, bpp, bits = self.dibs[dib]
        if bpp != 8:
            return 1
        W, H = abs(w), abs(h)
        txt = bytes(self.uc.mem_read(s, n))
        if lf not in _NAA:
            b = bytearray(lf)
            b[26] = 3                                 # NONANTIALIASED_QUALITY: an 8-bit DIB never antialiases
            _NAA[lf] = _g.CreateFontIndirectA(bytes(b))
        bmi = struct.pack("<IiiHHIIiiII", 40, W, -H, 1, 32, 0, 0, 0, 0, 0, 0)
        pv = ctypes.c_void_p()
        hb = _g.CreateDIBSection(_DC, bmi, 0, ctypes.byref(pv), None, 0)
        old = _g.SelectObject(_DC, hb)
        _g.SelectObject(_DC, _NAA[lf])
        _g.SetBkMode(_DC, 1)
        _g.SetTextColor(_DC, 0x00FFFFFF)
        _g.SetTextAlign(_DC, self.__dict__.get("_ta", {}).get(dc, 0))
        _g.TextOutA(_DC, x, y, txt, n)
        buf = ctypes.string_at(pv, W * H * 4)
        _g.SelectObject(_DC, old)
        _g.DeleteObject(hb)
        a = np.frombuffer(buf, np.uint8).reshape(H, W, 4)[:, :, 0] > 127
        clip = self.__dict__.get("_clip", {}).get(dc)
        if clip:
            m = np.zeros_like(a)
            m[max(0, clip[1]):max(0, clip[3]), max(0, clip[0]):max(0, clip[2])] = True
            a &= m
        ys, xs = np.nonzero(a)
        if len(ys) == 0:
            return 1
        col = self.__dict__.get("_tc", {}).get(dc, 0) & 0xFF
        stride = (W + 3) & ~3
        for yy in np.unique(ys):
            row_y = yy if h < 0 else H - 1 - yy
            base = bits + row_y * stride
            for xx in xs[ys == yy]:
                self.uc.mem_write(base + int(xx), bytes([col]))
        log.append((txt[:40], x, y, int(ys.min()), int(ys.max()) + 1, h))
        return 1

    new = {"api_CreateFontIndirectA": api_CreateFontIndirectA, "api_SetTextAlign": api_SetTextAlign,
           "api_SetTextColor": api_SetTextColor, "api_CreateRectRgnIndirect": api_CreateRectRgnIndirect,
           "api_SelectClipRgn": api_SelectClipRgn, "api_TextOutA": api_TextOutA}
    saved = {k: E.Emu.__dict__.get(k) for k in new}
    for k, v in new.items():
        setattr(E.Emu, k, v)
    return saved


@contextlib.contextmanager
def text_rendering():
    log: list = []
    saved = _install(log)
    try:
        yield log
    finally:
        for k, v in saved.items():
            if v is None:
                delattr(E.Emu, k)
            else:
                setattr(E.Emu, k, v)
