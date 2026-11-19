"""The retirement Holobook on the real image (image_emu.py): Holobook_gwinit (the baked image: through quayle's patched
call = t_hb_build) + Holobook_draw (vtbl+0x30) for a page and a tier, then the window's canvas.

quayle itself is not run (its modal exec would enter the message loop): the harness does what it does around the
two calls -- the builder through quayle's own call site's target, page/tier, then the paint.  The report-family fonts
the painter reads on the native path are seeded with vanilla's own find_font(S, v) (the ReportInfc init is not
part of the boot).  ONE boot per Book (~2 s); open() can be called repeatedly on the same boot.
"""
import image_emu as IE

HB = 0x872CB0
GWINIT, DRAW = 0x4951A0, 0x4956D0
QUAYLE_CALL = 0x4966C8            # quayle: call Holobook_gwinit (t_hb_build in the bake)
FIND_FONT = 0x5882F0
WRITE_CENT_L_5, WRITE_RAW_L, WRITE_CENT_L_7 = 0x5DD020, 0x5DCAE0, 0x5DD130
WIDE = 0x8A4168
G_DL_VPDONE = 0xA33E14        # assemble_dl.VPDONE (g_dl_vpdone)
FONT_TABLES = {0x8A40BC: (12, 0), 0x8A40E0: (11, 0), 0x8A40E4: (26, 0), 0x8A40E8: (18, 2), 0x8A40F0: (32, 0)}


def _s(e, i):
    v = e.arg(i)
    return v - (1 << 32) if v & 0x80000000 else v


class Book:
    def __init__(self, exe, w=3840, h=2160):
        e = self.e = IE.boot(exe, w, h)
        self.files = IE.Files(e)
        e.call(0x455610, count=0)
        e.call(0x6168F0, ecx=0x9B90D8, args=(0x40000,))
        e.call(0x616A00, count=50_000_000)
        e.w32(WIDE, 1)                # g_report_wide_flag: the report init sets it (0 only at 800x600)
        for tab, (s, v) in FONT_TABLES.items():
            e.w32(tab, e.call(FIND_FONT, args=(s, v), count=5_000_000))
        b = bytes(e.uc.mem_read(QUAYLE_CALL, 5))
        assert b[0] == 0xE8
        self.build_target = (QUAYLE_CALL + 5 + int.from_bytes(b[1:], "little", signed=True)) & 0xFFFFFFFF
        self.patched = self.build_target != GWINIT
        if self.patched:
            e.w32(G_DL_VPDONE, 1)     # t_dl_immfix's VirtualProtect: the emulated image is RWX already
        self.lines = []                # (writer, text, x, y, w) of every text write while open() paints
        e.observe(WRITE_CENT_L_5, lambda e: self.lines.append(
            ("cent", e.rstr(e.arg(0))[:e.arg(4)].decode("latin-1"), _s(e, 1), _s(e, 2), _s(e, 3))))
        e.observe(WRITE_RAW_L, lambda e: self.lines.append(
            ("raw", e.rstr(e.arg(0))[:e.arg(3)].decode("latin-1"), _s(e, 1), _s(e, 2), None)))
        e.observe(WRITE_CENT_L_7, lambda e: self.lines.append(
            ("rect", e.rstr(e.arg(0))[:e.arg(2)].decode("latin-1"), tuple(e.s32(e.arg(1) + 4 * k) for k in range(4)), None, None)))

    def open(self, page=-1, tier=2):
        e = self.e
        self.lines = []
        r = e.call(self.build_target, ecx=HB, count=0)
        assert r == 0, r
        e.w32(HB + 0x2144, page & 0xFFFFFFFF)
        e.w32(HB + 0x2148, tier & 0xFFFFFFFF)
        e.call(DRAW, ecx=HB, count=0)
        return IE.canvas_of(e, HB)

    def rect(self, off):
        return tuple(self.e.s32(HB + off + 4 * k) for k in range(4))
