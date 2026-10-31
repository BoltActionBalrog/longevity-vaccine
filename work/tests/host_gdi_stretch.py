"""The REAL host GDI StretchBlt for one image_emu.Emu (measure the engine, do not model it): the emulated call's
8-bit source / dest DIB sections are copied into host DIB sections, the host gdi32 StretchBlt runs with the engine's
own arguments (default stretch mode, the engine's ROP), and the dest bits come back.  image_emu's default models the
call as centre-aligned NN (audit19); the host call is the ground truth it was measured against -- it differs only on
an n -> n+1 stretch whose other axis is also nearly 1:1 (audit-w1B).  Windows only.

Lineage: audit-w1B's h_lobby.py / gdi_sb.py (scratch, 2026-10-24).  install(e) overrides THAT Emu's
api_StretchBlt only (an instance attribute), so other Emu objects in the worker keep the model.
"""
import ctypes
import struct
import sys
import types

_g = None


def available():
    return sys.platform == "win32"


def _gdi():
    global _g
    if _g is None:
        g = ctypes.WinDLL("gdi32")
        g.CreateCompatibleDC.restype = ctypes.c_void_p
        g.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        g.CreateDIBSection.restype = ctypes.c_void_p
        g.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p),
                                       ctypes.c_void_p, ctypes.c_uint]
        g.SelectObject.restype = ctypes.c_void_p
        g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        g.StretchBlt.argtypes = [ctypes.c_void_p] + [ctypes.c_int] * 4 + [ctypes.c_void_p] + [ctypes.c_int] * 4 + [
            ctypes.c_uint]
        g.DeleteObject.argtypes = [ctypes.c_void_p]
        g.DeleteDC.argtypes = [ctypes.c_void_p]
        g.GdiFlush.argtypes = []
        _g = g
    return _g


def _dib(w, h):
    g = _gdi()
    hdr = (ctypes.c_byte * (40 + 1024))()
    struct.pack_into("<IiiHHIIiiII", hdr, 0, 40, w, h, 1, 8, 0, 0, 0, 0, 256, 256)
    for i in range(256):                       # distinct colours per index: no palette merging
        struct.pack_into("<BBBB", hdr, 40 + 4 * i, i, (i * 7) & 255, (i * 13) & 255, 0)
    dc = g.CreateCompatibleDC(None)
    bits = ctypes.c_void_p()
    hb = g.CreateDIBSection(dc, hdr, 0, ctypes.byref(bits), None, 0)
    assert hb
    g.SelectObject(dc, hb)
    return dc, hb, bits.value


def _stretchblt(self):
    a = [struct.unpack("<i", struct.pack("<I", self.arg(i)))[0] for i in range(11)]
    hd, xd, yd, wd, hd_, hs, xs, ys, ws, hs_, rop = a
    dd, ds = self.dc_dib.get(hd & 0xFFFFFFFF), self.dc_dib.get(hs & 0xFFFFFFFF)
    self.sblt = getattr(self, "sblt", [])
    self.sblt.append((xd, yd, wd, hd_, xs, ys, ws, hs_, hex(rop & 0xFFFFFFFF), dd, ds))
    if not dd or not ds:
        return 0
    (dw, dh, dbpp, dbits), (sw, sh, sbpp, sbits) = self.dibs[dd], self.dibs[ds]
    assert dbpp == 8 and sbpp == 8
    g = _gdi()
    sdc, shb, sb = _dib(sw, sh)
    ddc, dhb, db = _dib(dw, dh)
    ss, dst_s = (abs(sw) + 3) & ~3, (abs(dw) + 3) & ~3
    ctypes.memmove(sb, bytes(self.uc.mem_read(sbits, ss * abs(sh))), ss * abs(sh))
    ctypes.memmove(db, bytes(self.uc.mem_read(dbits, dst_s * abs(dh))), dst_s * abs(dh))
    r = g.StretchBlt(ddc, xd, yd, wd, hd_, sdc, xs, ys, ws, hs_, rop & 0xFFFFFFFF)
    g.GdiFlush()
    self.uc.mem_write(dbits, ctypes.string_at(db, dst_s * abs(dh)))
    for x in (sdc, ddc):
        g.DeleteDC(x)
    for x in (shb, dhb):
        g.DeleteObject(x)
    return 1 if r else 0


def install(e):
    """Route this Emu's StretchBlt import to the host gdi32."""
    e.api_StretchBlt = types.MethodType(_stretchblt, e)
    return e
