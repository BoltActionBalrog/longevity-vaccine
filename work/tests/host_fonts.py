"""One host HFONT per distinct LOGFONTA, per process: the font cache every GDI-backed test emulator shares.

The emulators serve the game's CreateFontIndirectA with a real host font (for text metrics / glyphs) and never free
it -- the engine's DeleteObject is a no-op stub, and a host font is immutable, so sharing one between emulated
handles is safe.  Creating one per CALL leaked ~2,200 GDI handles per xdist worker and ~31,000 in the desktop session
(of its 65,536-entry table) over a 64-worker run; keyed on the LOGFONT bytes the count is bounded by the handful of
fonts the game builds.
"""
import ctypes

_g = ctypes.WinDLL("gdi32", use_last_error=True)
_g.CreateFontIndirectA.restype = ctypes.c_void_p
_g.CreateFontIndirectA.argtypes = [ctypes.c_char_p]
_FONTS = {}


def host_font(lf: bytes) -> int:
    """The process's host HFONT for the 60-byte LOGFONTA `lf` (created on first use, never deleted)."""
    lf = bytes(lf[:60]).ljust(60, b"\0")
    h = _FONTS.get(lf)
    if h is None:
        h = _g.CreateFontIndirectA(lf)
        assert h, f"CreateFontIndirectA failed ({ctypes.get_last_error()})"
        _FONTS[lf] = h
    return h


def count() -> int:
    """How many distinct host fonts this process holds."""
    return len(_FONTS)
