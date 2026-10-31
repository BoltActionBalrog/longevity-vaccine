"""The Social Engineering modal on the real image (image_emu.py via mirror_pairs_emu.Rig), in the engine's order
(2026-10-25 wave-4 W4C v2, F42; driver after the audit-w4C harness aud_emu.py):

  screen(W, H)  the real MainWin_build at that screen (g recomputed by the image's own thunk_ensure_scale), the real
                SocialWin_build (through thunk_se_enter on a patched image: the imm table, thunk_se_transform ->
                thunk_se_btnrun -> t_se_layout -> model_reset, fonts, every BaseButton_init, the backdrop draw
                @0x4B3315) stopped at its modal Win_set_modal call @0x4B3C4A, then the real SocialWin_show_hide(1) --
                slide_show with the rail gate armed (the real slide RAILS, drawn over the canvas) and the master painter
                SocialWin_repaint (the OK-row union frame, the SOCIETY panel, the four bands with their title bands and
                option cells, the SPARTANS box).  stop='build' returns after the builder (the backdrop alone).
The band painter's availability test (0x5B4730, result read @0x4AF445) is forced per option column: columns 0..1
available (the lock_c effect cell), 2..3 locked (lock_a + lock_b), so every cell branch draws.
Every SE_HALFOPEN_FRAME_SITES call is observed at its E8 and at its return: the rect the engine hands the site, the
DRAWN footprint (the bounding box of the canvas pixels the call changed, read in a window around the rect) and the
caller's rect after the call.  Geometry is the engine's own: the SocialWin rect tables after the build and every
BaseButton_init's arguments.  census() measures the vanilla-mirrored / vanilla-aligned pairs of the modal (the
audit-w4C measure.py keys) on the composed canvas.
"""
import contextlib
import io
import struct
import sys
from pathlib import Path

import numpy as np

import image_emu as IE
import mirror_pairs_emu as MP

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import scaling_laws as SL  # noqa: E402
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBX  # noqa: E402

SEW = 0x8A6270                      # SocialWin (static)
CANVAS = SEW + 0x444
SE_BUILD, SE_SHOW_HIDE, SE_MODAL_CALL, AVAIL_RET = 0x4B2740, 0x4B2120, 0x4B3C4A, 0x4AF445
#: SocialWin_repaint after the SPARTANS box (0x4B1AB2) .. its FlatButton loop (0x4B1ADC): the console painters (centre
#: console, SOCIAL EFFECTS text, the three sliders, the hover panel -- all on MainWin's canvas, none on the modal's)
REPAINT_CONSOLE_FROM, REPAINT_CONSOLE_TO = 0x4B1AB2, 0x4B1ADC
BB_INIT, BOX_SPRITE, MODEL_RESET = 0x607210, 0x5E2DD3, 0x4AECE0
TABLES = (("society_outer", 0x1F060, 1), ("society_rows", 0x1F070, 10), ("bands", 0x1F110, 4), ("options", 0x1F150, 16),
          ("faction", 0x1F2A0, 1), ("btns", 0x1F2B0, 3))
symtab = MP.symtab


def screen_for(g):
    """The smallest 4:3 screen whose g_popup_scale_num is g (floor 16 * min(W / 1024, H / 768))."""
    return -(-1024 * g // 16), -(-768 * g // 16)


class Rig:
    def __init__(self, exe, sym):
        self.m = MP.Rig(exe, sym)
        self.e = self.m.e
        self.sym = sym
        self.rec = None
        self.bb = None
        self.pending = {}
        e = self.e
        e.observe(SE_MODAL_CALL, lambda e: e.uc.emu_stop())
        e.observe(BB_INIT, self._bb)
        e.observe(AVAIL_RET, self._avail)
        e.observe(REPAINT_CONSOLE_FROM, self._skip_console)
        self.skip_console = False
        for va in SL.SE_HALFOPEN_FRAME_SITES:
            e.observe(va, self._pre)
            e.observe(va + 5, self._post)

    @property
    def patched(self):
        return self.m.patched

    # ---------------------------------------------------------------- observers
    def _bb(self, e):
        if self.bb is not None:
            esp = e.reg(IE.UC_X86_REG_ESP)
            self.bb.append((e.reg(IE.UC_X86_REG_ECX), tuple(e.s32(esp + 4 + 4 * i) for i in range(8))))

    def _skip_console(self, e):
        if self.skip_console:
            e.uc.reg_write(IE.UC_X86_REG_EIP, REPAINT_CONSOLE_TO)

    def _avail(self, e):
        if self.rec is not None:
            e.uc.reg_write(UC_X86_REG_EAX, int(e.reg(UC_X86_REG_EBX) < 2))

    def _region(self, x0, y0, x1, y1):
        e = self.e
        bits, w, h = e.r32(CANVAS + 0x54), e.s32(CANVAS + 0x38), abs(e.s32(CANVAS + 0x3C))
        st = (w + 3) & ~3
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
        if x0 >= x1 or y0 >= y1:
            return (x0, y0), np.zeros((0, 0), np.uint8)
        raw = bytes(e.uc.mem_read(bits + y0 * st, (y1 - y0) * st))
        return (x0, y0), np.frombuffer(raw, np.uint8).reshape(y1 - y0, st)[:, x0:x1].copy()

    def _pre(self, e):
        if self.rec is None or e.reg(IE.UC_X86_REG_ECX) != CANVAS:
            return
        esp = e.reg(IE.UC_X86_REG_ESP)
        rp = e.r32(esp)
        rect = tuple(e.s32(rp + 4 * i) for i in range(4))
        win = (rect[0] - 2, rect[1] - 2, rect[2] + 3, rect[3] + 3)
        self.pending[e.reg(IE.UC_X86_REG_EIP)] = (rect, rp, win, self._region(*win))

    def _post(self, e):
        va = e.reg(IE.UC_X86_REG_EIP) - 5
        if self.rec is None or va not in self.pending:
            return
        rect, rp, win, (org, before) = self.pending.pop(va)
        _o, after = self._region(*win)
        ys, xs = np.nonzero(after != before)
        bbox = None
        if len(xs):
            bbox = (int(xs.min()) + org[0], int(ys.min()) + org[1], int(xs.max()) + org[0], int(ys.max()) + org[1])
        restored = tuple(e.s32(rp + 4 * i) for i in range(4))
        self.rec.setdefault(va, []).append({"rect": rect, "bbox": bbox, "restored": restored})

    # ---------------------------------------------------------------- the 'before' bake on this boot
    @contextlib.contextmanager
    def reverted(self, g):
        """The image with the W4C edits undone in the emulator's memory (translation cache flushed), restored on exit:
        the twelve sites back on the target they called before (the renderers; the union frame on Buffer_box_sprite)
        and thunk_se_btnrun's tail back on SocialWin_model_reset -- the deployed c8374772 bake on the same boot.  Since
        W5C the 17 painter immediates t_se_layout owns (SL.SE_LAYOUT_IMMS) left thunk_se_immfix's table, so they are
        pre-set to the value that bake's immfix wrote at g (s(A) - s(B) of assemble_se.LAYOUT_OWNED)."""
        e, saved = self.e, {}
        with contextlib.redirect_stdout(io.StringIO()):
            import assemble_se as AS
        for addr, off, w, a, b in AS.LAYOUT_OWNED:
            saved[addr + off] = bytes(e.uc.mem_read(addr + off, w))
            e.uc.mem_write(addr + off, struct.pack("<i", SL.se_imm(a, b, g))[:w])
        for va, (_sid, renderer) in SL.SE_HALFOPEN_FRAME_SITES.items():
            saved[va] = bytes(e.uc.mem_read(va, 5))
            assert saved[va][0] == 0xE8, hex(va)
            tgt = BOX_SPRITE if va == SL.SE_UNION_FRAME_SITE else self.sym[renderer]
            e.uc.mem_write(va, b"\xE8" + struct.pack("<i", tgt - (va + 5)))
        tail = self.btnrun_tail()
        saved[tail] = bytes(e.uc.mem_read(tail, 5))
        e.uc.mem_write(tail, b"\xE9" + struct.pack("<i", MODEL_RESET - (tail + 5)))
        e.uc.ctl_flush_tb()
        try:
            yield self
        finally:
            for va, b in saved.items():
                e.uc.mem_write(va, b)
            e.uc.ctl_flush_tb()

    def btnrun_tail(self):
        """The VA of thunk_se_btnrun's `jmp t_se_layout` (its last instruction)."""
        e, va = self.e, self.sym["thunk_se_btnrun"]
        code = bytes(e.uc.mem_read(va, 0x200))
        for i in range(len(code) - 5):
            if code[i] == 0xE9 and (va + i + 5 + struct.unpack("<i", code[i + 1:i + 5])[0]) & 0xFFFFFFFF == \
                    self.sym["t_se_layout"]:
                return va + i
        raise AssertionError("thunk_se_btnrun has no jmp t_se_layout")

    # ---------------------------------------------------------------- one screen
    def table(self, off, n):
        return [tuple(self.e.s32(SEW + off + 16 * i + 4 * k) for k in range(4)) for i in range(n)]

    def screen(self, w, h, stop="show", console=False):
        """-> {'g', 'rec': {site: [{'rect', 'bbox', 'restored'}, ...]}, 'bb': [(ecx, args8)], 'tables', 'build_p' (the
        canvas after the builder: the backdrop alone), 'p' (the composed canvas, rails included), 'wh'}.
        console=False skips the repaint's console painters (MainWin's canvas only; ~30 % of a 4K item)."""
        g = self.m.screen(w, h)
        e = self.e
        self.rec, self.bb = {}, []
        self.skip_console = not console
        out = {"g": g, "wh": (w, h)}
        try:
            e.call(self.sym["thunk_se_enter"] if self.patched else SE_BUILD, ecx=SEW, args=(0,), count=2_000_000_000)
            out["build_p"] = IE.canvas_of(e, SEW)
            if stop != "build":
                e.call(SE_SHOW_HIDE, ecx=SEW + 0xA14, args=(1,), count=2_000_000_000)
        finally:
            out["rec"], out["bb"] = self.rec, self.bb
            self.rec, self.bb = None, None
        out["tables"] = {name: self.table(off, n) for name, off, n in TABLES}
        out["p"] = IE.canvas_of(e, SEW)
        return out


# ==================================================================== measuring (the audit-w4C measure.py keys)
def run_of(line, x):
    """The run of pixels equal to line[x] through x: (first, last)."""
    v, a, b = line[x], x, x
    while a - 1 >= 0 and line[a - 1] == v:
        a -= 1
    while b + 1 < len(line) and line[b + 1] == v:
        b += 1
    return a, b


def backdrop_borders(res):
    """The backdrop's VISIBLE border widths, measured: on fill rows of the composed canvas, the columns of each border
    stroke (as the builder drew it, build_p) that still carry the stroke's colour after the slide rails painted over
    the window edges (p).  -> (left, right), the mode over the sampled rows."""
    (bd,) = res["rec"][0x4B3315]
    x0, y0, x1, y1 = bd["bbox"]
    bp, p = res["build_p"], res["p"]
    ls, rs = [], []
    for y in range(y0 + 3, y1 - 3, max(1, (y1 - y0) // 23)):
        a, b = run_of(bp[y], x0)
        ls.append(sum(1 for x in range(a, b + 1) if p[y, x] == bp[y, x0]))
        a, b = run_of(bp[y], x1)
        rs.append(sum(1 for x in range(a, b + 1) if p[y, x] == bp[y, x1]))
    return max(set(ls), key=ls.count), max(set(rs), key=rs.count)


def census(res):
    """The modal's pair measurements (device px): every frame by its drawn footprint, every FlatButton / row by the
    engine table, every channel read off the composed canvas (stroke runs)."""
    p, T = res["p"], res["tables"]
    C = res["rec"]
    soc, st = C[0x4AF226][0]["bbox"], C[0x4AF26F][0]["bbox"]
    bands, titles = [d["bbox"] for d in C[0x4AF35F]], [d["bbox"] for d in C[0x4AF3A8]]
    cells_b = [d["bbox"] for d in C.get(0x4AF4A7, []) + C.get(0x4AF4E9, [])]
    fac, f1, f2 = C[0x4AF904][0]["bbox"], C[0x4AF94A][0]["bbox"], C[0x4AFA13][0]["bbox"]
    un = C[SL.SE_UNION_FRAME_SITE][0]["bbox"]
    rows, opts, btns = T["society_rows"], T["options"], T["btns"]
    m = {"backdrop border L|R": backdrop_borders(res)}
    y = (rows[0][1] + rows[0][3]) // 2
    m["soc>rows L|R"] = (rows[0][0] - run_of(p[y], soc[0])[1] - 1, run_of(p[y], soc[2])[0] - rows[0][2])
    x = (rows[0][0] + rows[0][2]) // 2
    m["soc>rows T|B"] = (rows[0][1] - st[3] - 1, run_of(p[:, x], soc[3])[0] - rows[-1][3])
    y = (st[1] + st[3]) // 2
    m["soc>title L|R|T"] = (st[0] - run_of(p[y], soc[0])[1] - 1, run_of(p[y], soc[2])[0] - st[2] - 1,
                            st[1] - run_of(p[:, (st[0] + st[2]) // 2], soc[1])[1] - 1)
    m["soc title over rows L|R"] = (rows[0][0] - st[0], st[2] - (rows[0][2] - 1))
    # W5C: the panel's title-top inset vs its last row's bottom inset (vanilla 3 | 3), its row 4 centred (113 | 113)
    m["soc title T | rows B inset"] = (st[1] - soc[1], soc[3] - (rows[-1][3] - 1))
    m["soc row4 T|B"] = (rows[4][1] - soc[1], soc[3] - (rows[4][3] - 1))
    for i, (b, t) in enumerate(zip(bands, titles)):
        y = (t[1] + t[3]) // 2
        x = (t[0] + t[2]) // 2
        m[f"band{i}>title L|R|T"] = (t[0] - run_of(p[y], b[0])[1] - 1, run_of(p[y], b[2])[0] - t[2] - 1,
                                     t[1] - run_of(p[:, x], b[1])[1] - 1)
        o = opts[4 * i:4 * i + 4]
        y = (o[0][1] + o[0][3]) // 2
        m[f"band{i}>options L|R"] = (o[0][0] - run_of(p[y], b[0])[1] - 1, run_of(p[y], b[2])[0] - o[3][2])
        cells = sorted(c for c in cells_b if b[1] < c[1] < b[3])
        x = (cells[0][0] + cells[0][2]) // 2
        m[f"band{i} title>row T | cells>band B"] = (o[0][1] - t[3] - 1, run_of(p[:, x], b[3])[0] - max(c[3] for c in cells) - 1)
        # W5C relations (a) the title band's top inset vs the cell row's bottom inset (vanilla 3 | 3) and (b) the option
        # row centred in its band (vanilla 25 | 25), from the drawn footprints
        m[f"band{i} title T | cells B inset"] = (t[1] - b[1], b[3] - max(c[3] for c in cells))
        m[f"band{i} option row T|B"] = (o[0][1] - b[1], b[3] - (o[0][3] - 1))
        m[f"band{i} option seams"] = tuple(o[k + 1][0] - o[k][2] for k in range(3))
        m[f"band{i} cell seams"] = tuple(cells[k + 1][0] - cells[k][2] - 1 for k in range(3))
        m[f"band{i} cells on options L|R"] = tuple((c[0] - oo[0], c[2] - (oo[2] - 1)) for c, oo in zip(cells, o))
        m[f"band{i} title over options L|R"] = (o[0][0] - t[0], t[2] - (o[3][2] - 1))
    m["band gaps"] = tuple(bands[i + 1][1] - bands[i][3] - 1 for i in range(3))
    m["title bands band0 vs SOCIETY (T, B)"] = (titles[0][1] - st[1], titles[0][3] - st[3])
    m["frame tops band0 vs SOCIETY"] = bands[0][1] - soc[1]
    m["SPARTANS bands T|B"] = (f1[1] - fac[1], fac[3] - f2[3])
    m["SPARTANS bands L|R"] = (f1[0] - fac[0], fac[2] - f1[2])
    m["SPARTANS vs SOCIETY L,R"] = (fac[0] - soc[0], fac[2] - soc[2])
    ux0, ux1 = min(b[0] for b in btns), max(b[2] for b in btns) - 1
    y = (btns[0][1] + btns[0][3]) // 2
    x = (btns[1][0] + btns[1][2]) // 2
    m["union>buttons L|R|T|B"] = (ux0 - run_of(p[y], un[0])[1] - 1, run_of(p[y], un[2])[0] - ux1 - 1,
                                  btns[0][1] - run_of(p[:, x], un[1])[1] - 1, run_of(p[:, x], un[3])[0] - btns[0][3])
    # vanilla-unmirrored distances (vanilla x g/16 targets; the M3 three and the rail margin)
    m["~band R>SOCIETY L"] = soc[0] - bands[0][2] - 1
    m["~SPARTANS band gap"] = f2[1] - f1[3] - 1
    m["~band 3>union"] = un[1] - bands[3][3] - 1
    m["~SOCIETY>SPARTANS"] = fac[1] - soc[3] - 1
    m["~SPARTANS>union"] = un[1] - fac[3] - 1
    m["~SPARTANS B - band 3 B"] = fac[3] - bands[3][3]       # the audit L-D distance (vanilla 300 - 292)
    return m


def flat(v):
    out = []
    for x in (v if isinstance(v, tuple) else (v,)):
        out += flat(x) if isinstance(x, tuple) else [x]
    return out


def classify(vanilla):
    """{key: 'mirror' | 'align' | 'scalar'} from the pristine census: a tuple whose vanilla entries are all equal is a
    mirrored pair (equal channels / seams / insets), an alignment key (vanilla 0 / 0) an aligned pair, a '~' key a
    vanilla-unmirrored distance."""
    out = {}
    for k, v in vanilla.items():
        f = flat(v)
        if k.startswith("~"):
            out[k] = "scalar"
        elif any(w in k for w in (" on ", " over ", " vs ", "frame tops")):
            out[k] = "align"
        else:
            assert len(f) > 1 and len(set(f)) == 1, (k, v)
            out[k] = "mirror"
    return out


def violation(kind, v, vanilla):
    """0 when the pair keeps vanilla's relation: mirrored -> all entries equal; aligned -> vanilla's offsets exactly."""
    f, fv = flat(v), flat(vanilla)
    if kind == "mirror":
        return max(f) - min(f)
    if kind == "align":
        return max(abs(a - b) for a, b in zip(f, fv))
    return 0
