"""Real-image in-game MENU dropdown harness (W9C F55, 2026-10-27; tests/test_scaling_menu_dropdown_lines.py).

The MENU button's dropdown is the sprite-based widget g_console_menu_win 0x9380DC (NOT the universal Menu control):
load_menu 0x402F40 cuts menu2.pcx into a title strip (139 x 6) and three row strips (139 x 18) and inits its window;
MenuWidget_layout_show 0x4032A0 sizes and places it (the bake's thunk_menu_layout); the painter 0x403340 draws the
title and one row strip per item through Sprite_draw_2 -- on the bake thunk_hudmenu_sd2 -> (post-blit) t_mc_synth ->
hm_synth_core.  This harness runs exactly that on the REAL terranx_PRACX image (image_emu.py; every engine function
and cave thunk for real), with the game's own menu2.pcx through the engine's own loader, and returns the widget's
canvas.  The item entries (+0xA3C text / +0xA40 flags, stride 0x14; count +0xA18; hot index +0xA24) are written the
way the HUD's builder leaves them (flags 0: the text pass is not part of the strips).  Ported from the W9C F55
investigation rig (scratch f55\\menu_rig.py).  The pristine image has no g: everything is the vanilla draw.
"""
from __future__ import annotations

import gc
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import image_emu as E  # noqa: E402

MW = 0x9380DC
LOAD_MENU, LAYOUT_SHOW, PAINT = 0x402F40, 0x4032A0, 0x403340
ITEMS = ["GAME", "HQ", "NETWORK", "MAP", "ACTION", "TERRAFORM", "SCENARIO", "EDIT MAP", "HELP", "PRACX"]
LINE, EDGE, KEY = 191, 233, 9          # canvas indices: the 0x0E2243 side line, the brown edge column, the key
RES = {16: (1024, 768), 17: (1088, 816), 18: (1600, 900), 20: (1280, 1024), 22: (1920, 1080), 25: (1600, 1200),
       30: (2560, 1440), 40: (3840, 2160)}


def render(exe: str, W: int, H: int, nitems: int = 10, hot: int = -1) -> dict:
    """dict(g, canvas, top (the first row strip's y), pitch (the row pitch))."""
    e = E.boot(exe, W, H)
    E.Files(e)
    g = e.r32(E.GSCALE)
    e.w32(0x7AE820 + 0x9C, e.r32(0x7AE820 + 0x9C) | 1)                 # MainWin visible
    e.w32(0x7AF59C, (213 * g) >> 4 if g > 16 else 213)                  # g_console_strip_height (patched)
    e.call(LOAD_MENU, ecx=MW, args=(1,), count=300_000_000)
    e.w32(MW + 0xA18, nitems)
    for i in range(nitems):
        e.w32(MW + 0xA3C + 0x14 * i, e.cstr(ITEMS[i % len(ITEMS)]))
        e.w32(MW + 0xA40 + 0x14 * i, 0)
    e.w32(MW + 0xA24, hot & 0xFFFFFFFF)
    e.call(LAYOUT_SHOW, ecx=MW, count=50_000_000)
    e.call(PAINT, ecx=MW, count=300_000_000)
    out = dict(g=g, canvas=np.array(E.canvas_of(e, MW)), top=e.s32(MW + 0x1108), pitch=e.s32(MW + 0x1134))
    e.uc = None                                                       # free the emulator now (xdist memory)
    del e
    gc.collect()
    return out


def runs(row, v):
    out, s = [], None
    for i, x in enumerate(list(row) + [-1]):
        if x == v and s is None:
            s = i
        if x != v and s is not None:
            out.append((s, i - s))
            s = None
    return out


def row_signatures(r: dict):
    """{(line runs, edge runs, key runs)} over every row-strip row of the canvas."""
    c = r["canvas"]
    return {(tuple(runs(c[y], LINE)), tuple(runs(c[y], EDGE)), tuple(runs(c[y], KEY)))
            for y in range(r["top"], c.shape[0])}
