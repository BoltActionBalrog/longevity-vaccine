"""Real-image COMMLINK panel (MultiWin 0x7FD648) for the commlink_mp_spots guard (tests/test_commlink_mp_spots.py).

Boots the REAL terranx_PRACX image under Unicorn with the shared harness image_emu.py, builds the panel the way the
game does (commlink_win_build 0x479F90, with MultiplayerActive [0x93F660] set FIRST so the box is sized for the
multiplayer strips) and repaints it (commlink_redraw 0x479330).  Layouts: COLLAPSED ([+0xA24] = 0: the time widget
and the strip under it at the panel bottom, no faction rows) and EXPANDED ([+0xA24] = 1: the strips on top, faction
rows 2..7 below -- commlink-acquired bits [0x9A64E8] and the end-game flag [0x9A64C0] & 0x80 make every row visible,
and byte 0 of [0x9A64E8] lights every row's mute LED).

Recorded: every Spot_add on the panel's spot list (+0x28AC) and every Sprite_blit_scaled_core / Sprite_draw_2 the
repaint makes on the panel buffer (+0x444), at their entries, plus the final canvas.  Only the LAST repaint's
records are returned (the build repaints too).
"""
from __future__ import annotations

import gc
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import image_emu as E  # noqa: E402
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESP  # noqa: E402

MW = 0x7FD648
SPOTS = MW + 0x28AC
BUF = MW + 0x444
SPOT_ADD, SPOT_CHECK, SBC, SD2 = 0x5FA960, 0x5FAB00, 0x5E4B9A, 0x5E4B4A
REDRAW, BUILD = 0x479330, 0x479F90


def res(g: int):
    return {16: (1024, 768), 22: (1920, 1080), 25: (1600, 1200), 40: (3840, 2160)}.get(g, (64 * g, 48 * g))


STRIP_COUNT = 0x0096EA34 + 0x20CC   # the player's (faction 1) count the strip under the time widget prints as '^'s
TEXT_RET = 0x004794F7               # commlink_redraw, right after the strip text (commlink_write_cent 0x47A720)


def panel(exe, g: int, expanded: int, mp: int = 1, pre=None, clicks=(), hooks=(), strip_text: int = 2):
    """-> dict(g, spots=[(ret, [idx, type, x, y, w, h])], blits=[(fn, sprite, [args...])], canvas, hits={xy: type})"""
    W, H = res(g)
    e = E.boot(Path(exe), W, H)
    E.Files(e)
    if pre:
        pre(e)                      # (before any code runs: Unicorn caches translated blocks)
    e.call(0x455610, count=0)
    e.call(0x6168F0, ecx=0x9B90D8, args=(0x40000,))
    e.call(0x616A00, count=50_000_000)
    rec = dict(spots=[], blits=[])

    def spot(e):
        if e.reg(UC_X86_REG_ECX) == SPOTS:
            esp = e.reg(UC_X86_REG_ESP)
            rec["spots"].append((e.r32(esp), [e.s32(esp + 4 + 4 * i) for i in range(6)]))

    def blit(fn):
        def cb(e):
            esp = e.reg(UC_X86_REG_ESP)
            if e.r32(esp + 4) == BUF:
                rec["blits"].append((fn, e.reg(UC_X86_REG_ECX), [e.s32(esp + 4 + 4 * i) for i in range(6)]))
        return cb
    e.observe(SPOT_ADD, spot)
    e.observe(SBC, blit("sbc"))
    e.observe(SD2, blit("sd2"))
    e.w32(0x93F660, mp)
    e.call(BUILD, ecx=MW, count=300_000_000)
    e.w32(0x939284, 1)
    e.w32(0x9A64E8, 0x0000FEFE)
    e.uc.mem_write(0x9A64C0, bytes([e.uc.mem_read(0x9A64C0, 1)[0] | 0x80]))
    e.w32(MW + 0xA24, expanded)
    e.w32(STRIP_COUNT, strip_text)  # > 0: the strip's text is written (0 skips commlink_write_cent entirely)
    e.w32(MW + 0x9C, e.r32(MW + 0x9C) | 1)
    rec["spots"].clear()
    rec["blits"].clear()
    for va, cb in hooks:            # only the last repaint's (the build's own repaints are before this)
        e.observe(va, cb)
    e.call(REDRAW, ecx=MW, args=(0,), count=400_000_000)
    hits = {}
    pos, typ = e.alloc(4), e.alloc(4)
    for x, y in clicks:
        e.w32(pos, 0xFFFFFFFF)
        e.w32(typ, 0xFFFFFFFF)
        r = e.call(SPOT_CHECK, ecx=SPOTS, args=(x, y, pos, typ), count=1_000_000)
        hits[(x, y)] = (e.s32(typ), e.s32(pos), r)
    out = dict(g=e.r32(E.GSCALE), canvas=E.canvas_of(e, MW), hits=hits, **rec)
    e.uc = None
    gc.collect()
    return out
