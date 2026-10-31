"""The LOAD / SAVE file picker's OK / CANCEL windows on the real image (image_emu.py): FileDlg_ctor 0x407350 +
FileDlg_layout 0x407410 on a heap FileDlg, run to the edit field's CreateWindowExA (after FileDlg_build_widgets'
two BaseButton_init calls), at any g, on either layout path.

Lineage: the W2D scratch harness (2026-10-25, fd_emu.py), which reproduced the user's 1600x1200 in-game LOAD shot
20261025-000837: OK 228 | CANCEL 230 x 35 (the in-game path).

The path is FileDlg_layout's own test of the map window (the 0x5F7E90 call @0x407453 on 0x9156B0): forced at its
return (@0x407458) to 0 (Path A, the main-menu LOAD) or to the window (Path B, in game).  ONE boot per FileDlgEmu;
layout(g) forces g (+ g_stripe_period) and runs on a fresh heap object (~2 s at g 40: the layout draws the backdrop).
"""
import image_emu as IE
import scaling_laws as SL
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_ESP

FILEDLG_CTOR, FILEDLG_LAYOUT = 0x407350, 0x407410
PATH_TEST_RET = 0x407458        # after `call 0x5F7E90` (eax = the map window or 0)
MAP_WIN = 0x9156B0
OK_INIT, CANCEL_INIT = 0x613AAC, 0x613ADF     # FileDlg_build_widgets' BaseButton_init calls
G_VA, G_STRIPE_PERIOD = 0x668740, 0x66879C
FILEDLG_SIZE = 0x8000


class FileDlgEmu:
    def __init__(self, exe, w=3840, h=2160, skip_draws=()):
        """skip_draws: (va, stdcall arg bytes) of pure DRAW thunks the layout calls on its way to the buttons, stubbed to
        return 1 -- e.g. thunk_bilinear_blit (RET 0x2C), whose per-pixel palette search is ~10 s of Unicorn at g 40
        and writes pixels only (the rects never read them)."""
        e = self.e = IE.boot(exe, w, h)
        IE.Files(e)
        e.call(0x455610, count=0)
        e.call(0x6168F0, ecx=0x9B90D8, args=(0x40000,))
        e.call(0x616A00, count=50_000_000)
        self.patched = bytes(e.uc.mem_read(0x668760, 4)) != bytes(4)
        self.inits, self.force = [], 0
        for va, nm in ((OK_INIT, "OK"), (CANCEL_INIT, "CANCEL")):
            e.observe(va, lambda e, nm=nm: self.inits.append(
                (nm, [e.s32(e.reg(UC_X86_REG_ESP) + 4 * i) for i in range(8)], e.reg(UC_X86_REG_ECX))))
        e.observe(PATH_TEST_RET, lambda e: e.uc.reg_write(UC_X86_REG_EAX, self.force))
        for va, nbytes in skip_draws:
            e.stub_fn(va, lambda e: 1, nbytes)

    def layout(self, g, ingame):
        """-> {'OK': (L, T, R, B), 'CANCEL': ...} window-local, as BaseButton_init receives them, and {name: button
        object}."""
        e = self.e
        if self.patched:
            e.w32(G_VA, g)
            e.w32(G_STRIPE_PERIOD, SL.stripe_period(g))
        self.inits, self.force = [], (MAP_WIN if ingame else 0)
        obj = e.alloc(FILEDLG_SIZE)
        e.call(FILEDLG_CTOR, ecx=obj, count=50_000_000)
        try:
            e.call(FILEDLG_LAYOUT, ecx=obj, count=0)
        except RuntimeError as x:          # the edit field's CreateWindowExA: past both buttons
            assert "CreateWindowExA" in str(x), x
        rects = {nm: (a[2], a[3], a[2] + a[4], a[3] + a[5]) for nm, a, _o in self.inits}
        objs = {nm: o for nm, _a, o in self.inits}
        assert set(rects) == {"OK", "CANCEL"}, rects
        return rects, objs
