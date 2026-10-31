"""t_wheel_stc for the asm wheel heads' Unicorn harnesses (t_rw / t_dl / t_bw / t_ntw _wheel_down).

Every head reads the cursor through the exe's GetCursorPos import and then calls t_wheel_stc
(assemble_rw.asm_wheel_stc: a ScreenToClient drop-in that goes through the cell g_wheel_stc when uimod.dll
filled it, else the IAT) instead of the API. A harness that emulates only its own bake's layout installs the
stub's REAL assembled bytes with install().

PRACX hooks that GetCursorPos import (pracx.cpp PRACXGetCursorPos): while m_fWindowed (Windowed / Borderless /
Fullscreen without the mode switch) it returns the cursor ALREADY in backbuffer coords (ScreenToClient +
ClientToBackbuffer); otherwise raw screen coords. uimod's WheelScreenToClient therefore returns the point
untouched when windowed and is the plain API otherwise. `with mode(...)` makes install() model one setup;
the harness' GetCursorPos stub then stands for PRACX's hooked return (the caller passes the right space):
  "windowed"      DLL loaded, m_fWindowed: cell -> an identity stand-in; the API (window origin ox, oy) unused
  "fullscreen"    DLL loaded, no m_fWindowed: cell -> the plain API, which subtracts the window origin
  "nodll"         no DLL: cell 0 -> the plain API (the pre-fix behaviour: subtracts the origin again)
"""
from __future__ import annotations

import contextlib
import io
import struct

from keystone import KS_ARCH_X86, KS_MODE_32, Ks

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_rw as AR  # noqa: E402
import assemble_se as SE  # noqa: E402

WHEEL_STC, G_WHEEL_STC = AR.WHEEL_STC, AR.G_WHEEL_STC
IAT_S2C = 0x006692D4
PAGE = 0x02F00000                 # the stand-ins' own page (outside every harness' mappings)
API_SUB, DLL_IDENTITY = PAGE, PAGE + 0x80
_KS = Ks(KS_ARCH_X86, KS_MODE_32)
_MODE = None

ORIGIN = (37, 23)          # a captioned window's client origin on the screen (non-zero on purpose)
MODES = [  # (mode, window origin, PRACX GetCursorPos space, the head hits?)
    ("windowed", ORIGIN, "backbuffer", True),     # Windowed: PRACX already mapped the point; uimod leaves it
    ("windowed", (0, 0), "backbuffer", True),     # Borderless / Fullscreen without the mode switch (stretched)
    ("fullscreen", ORIGIN, "screen", True),       # real mode switch: raw screen; the plain API subtracts the origin
    ("nodll", ORIGIN, "backbuffer", False),       # control: the pre-fix head subtracted the origin a second time
]


def pracx_cursor(b, origin, space):
    """PRACX's hooked GetCursorPos for the backbuffer point b: b itself while m_fWindowed, else screen coords."""
    return (b[0] + origin[0], b[1] + origin[1]) if space == "screen" else tuple(b)


def _map(uc, va, size=0x1000):
    lo = va & ~0xFFF
    try:
        uc.mem_read(lo, 1)
    except Exception:  # noqa: BLE001
        uc.mem_map(lo, (va + size - lo + 0xFFF) & ~0xFFF)


def _put(uc, va, src):
    enc, _ = _KS.asm(src, va)
    _map(uc, va, len(enc))
    uc.mem_write(va, bytes(enc))
    try:
        uc.ctl_remove_cache(va, va + len(enc))
    except Exception:  # noqa: BLE001
        pass


@contextlib.contextmanager
def mode(name: str, ox: int = 0, oy: int = 0):
    global _MODE
    assert name in ("windowed", "fullscreen", "nodll")
    _MODE = (name, ox, oy)
    try:
        yield
    finally:
        _MODE = None


def install(uc) -> bytes:
    """Write t_wheel_stc's real bytes; the cell is 0 (no uimod.dll) unless a mode() is active."""
    code = SE.assemble(AR.asm_wheel_stc(), WHEEL_STC, {})
    _map(uc, WHEEL_STC, 0x20)
    uc.mem_write(WHEEL_STC, code)
    try:
        uc.ctl_remove_cache(WHEEL_STC, WHEEL_STC + 0x20)
    except Exception:  # noqa: BLE001
        pass
    cell = 0
    if _MODE:
        name, ox, oy = _MODE
        # the real ScreenToClient: point -= the client origin on the screen
        _put(uc, API_SUB, f"""
            mov     eax, dword ptr [esp+8]
            sub     dword ptr [eax], {ox}
            sub     dword ptr [eax+4], {oy}
            mov     eax, 1
            ret     8""")
        _map(uc, IAT_S2C, 4)
        uc.mem_write(IAT_S2C, struct.pack("<I", API_SUB))
        # uimod WheelScreenToClient while m_fWindowed: TRUE, point untouched
        _put(uc, DLL_IDENTITY, "mov eax, 1\n ret 8")
        cell = {"windowed": DLL_IDENTITY, "fullscreen": API_SUB, "nodll": 0}[name]
    uc.mem_write(G_WHEEL_STC, struct.pack("<I", cell))
    return code
