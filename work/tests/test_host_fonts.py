"""host_fonts: the emulators' host HFONTs are one per distinct LOGFONT per process, never one per call (the GDI
handle leak that put ~2,200 handles in every xdist worker and ~31,000 in the desktop session)."""
import ctypes
import struct
import sys

import pytest

if sys.platform != "win32":
    pytest.skip("host GDI fonts need Windows", allow_module_level=True)

import host_fonts  # noqa: E402


def _lf(size: int, weight: int = 400, face: bytes = b"Arial") -> bytes:
    lf = bytearray(60)
    struct.pack_into("<iiiii", lf, 0, -size, 0, 0, 0, weight)
    lf[28:28 + len(face)] = face
    return bytes(lf)


def _gdi_count() -> int:
    k, u = ctypes.WinDLL("kernel32"), ctypes.WinDLL("user32")
    k.GetCurrentProcess.restype = ctypes.c_void_p
    u.GetGuiResources.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    return u.GetGuiResources(k.GetCurrentProcess(), 0)          # GR_GDIOBJECTS


def test_one_host_font_per_logfont():
    a, b = host_fonts.host_font(_lf(97)), host_fonts.host_font(_lf(97))
    assert a and a == b
    assert host_fonts.host_font(_lf(97, 700)) != a
    assert host_fonts.host_font(_lf(97, face=b"Arial Narrow")) != a, "the face name is part of the key"


def test_repeated_creates_do_not_grow_the_gdi_handle_count():
    fonts = [_lf(s, w) for s in range(60, 70) for w in (400, 700)]
    for lf in fonts:
        host_fonts.host_font(lf)
    before = _gdi_count()
    for _ in range(50):
        for lf in fonts:
            host_fonts.host_font(lf)
    assert _gdi_count() == before
