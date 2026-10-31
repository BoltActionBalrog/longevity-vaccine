"""The MULTIPLAYER SETUP lobby on the real image (image_emu.py): NetWin_setup_lobby 0x482490 in the engine's own order
up to its first modal point, then the real FlatButton_content_draw of its buttons in any draw state.

Lineage: the inv-lobby harness (scratch, which reproduced the user's 1920x1080 lobby shot 20261024-124117
pixel-exact: LAUNCH GAME face 27 of 28 rows).  Shared by test_scaling_netwin_btnpair.py (fix 27) and
test_scaling_btn_corner_states.py (F33, the lobby buttons are the real default-art 9-slice FlatButtons).

ONE boot per Lobby (~2 s); `build(g)` re-runs the builder at any g on the same boot (~0.2 s): the builder writes its
rect table natively and scales it on every run (thunk_nw_rectscale), BaseButton_init re-allocates the button
canvases, and the screen (3840x2160 by default) holds the lobby window at every g <= 40.  g is forced the way
thunk_ensure_scale sets it from the user's resolution: g_popup_scale_num AND, with it, g_stripe_period =
stripe_period(g) (the only other value that thunk derives; a 4K boot left at period 4 would stripe T = 2 below g = 22).
Anything else the boot computed from the boot's g (the config_popups font pool) keeps the boot resolution's value: a
check of label text or of anything config_popups sized must boot at the real resolution instead.  The network / session side of the builder (not UI) is
stubbed to 0: 0x481FD0, 0x632070, 0x630080.  The pristine image has no g (no patches): build() is then the vanilla
lobby, whatever g.
"""
import image_emu as IE
import scaling_laws as SL
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESP

NETWIN = 0x80A6F8
LAUNCH, CANCEL = 0x80F674, 0x8101C0
SETUP_LOBBY = 0x482490
MODAL_POINT = 0x482C8D           # after both BaseButton_init + font + 0x607360, before the modal vtbl+0xE4 @0x482CA6
BASEBUTTON_INIT = 0x607210
CONTENT_DRAW = 0x607E50
G_VA = 0x668740
G_STRIPE_PERIOD = 0x66879C       # thunk_ensure_scale writes it with g (menu_strip_thunks 0x59C)
G_NETWIN_ACTIVE = 0xA10800       # pcave2 0x4800 (thunk_netwin_bracket's flag; the builder runs inside it in game)
B_LITERAL = 0x482876             # `mov ecx,0xE8` (B = 232) of the LAUNCH / CANCEL rows (0x482875 B9 E8 00 00 00)
BOX_SETS = (0x78D960, 0x78D988, 0x78D9B0)    # the BoxSpriteParams the HUD TOOLBAR wears (MainWin_build @0x45AAB0)
KEY = 9


class Lobby:
    def __init__(self, exe, w=3840, h=2160):
        e = self.e = IE.boot(exe, w, h)
        IE.Files(e)
        e.call(0x455610, count=0)
        e.call(0x6168F0, ecx=0x9B90D8, args=(0x40000,))
        e.call(0x616A00, count=50_000_000)
        self.patched = bytes(e.uc.mem_read(0x58DBDA, 1)) == b"\xE8" and (e.s32(0x58DBDB) + 0x58DBDF) & 0xFFFFFFFF != SETUP_LOBBY
        self.inits = []
        e.observe(BASEBUTTON_INIT, self._bb)
        e.observe(MODAL_POINT, lambda e: e.uc.emu_stop())
        for va in (0x481FD0, 0x632070, 0x630080):
            e.stub_fn(va, lambda e: 0)
        self.b_literal = bytes(e.uc.mem_read(B_LITERAL, 1))

    def patch(self, va, data):
        """Write code bytes and drop Unicorn's translation of them (a block already run would keep the old code)."""
        self.e.uc.mem_write(va, bytes(data))
        self.e.uc.ctl_remove_cache(va & ~0xFFF, (va + len(data) + 0xFFF) & ~0xFFF)

    def _bb(self, e):
        esp = e.reg(UC_X86_REG_ESP)
        self.inits.append((e.reg(UC_X86_REG_ECX), [e.s32(esp + 4 + 4 * i) for i in range(8)]))

    def build(self, g, native_h=20):
        """Run the builder at g; native_h re-dresses the LAUNCH / CANCEL rows (vanilla 20) -- 22 makes them the
        22-native class (the faction picker's text buttons, Load/Save OK / CANCEL).  Returns {obj: (x, y, w, h)}."""
        e = self.e
        self.inits.clear()
        if self.patched:
            e.w32(G_VA, g)
            e.w32(G_STRIPE_PERIOD, SL.stripe_period(g))
            e.w32(G_NETWIN_ACTIVE, 1)
        self.patch(B_LITERAL, bytes([212 + native_h]))
        e.w32(0x9B2068, 0)
        e.w32(0x93E8C0, 0)
        e.w32(NETWIN + 0x772C, 1)
        try:
            e.call(SETUP_LOBBY, ecx=NETWIN, count=300_000_000)
        finally:
            self.patch(B_LITERAL, self.b_literal)
        assert e.reg(UC_X86_REG_EIP) == MODAL_POINT, hex(e.reg(UC_X86_REG_EIP))
        return {o: tuple(a[2:6]) for o, a in self.inits}

    def draw(self, obj, state, box=False):
        """FlatButton_content_draw of obj in draw state 0 / 1 / 2 (FlatButton +0xAB8); box=True re-dresses it as a
        box-sprite face (the HUD TOOLBAR's BoxSpriteParams set) instead of the default 9-slice.  -> the canvas."""
        e = self.e
        for i, p in enumerate(BOX_SETS):
            e.w32(obj + 0xAC8 + 4 * i, p if box else 0)
        e.w32(obj + 0xAB8, state)
        e.call(CONTENT_DRAW, ecx=obj, count=20_000_000)
        return IE.canvas_of(e, obj)

    def g(self):
        return self.e.r32(G_VA)


def corner_notches(p, key=KEY):
    """(w, h) of the key run at each corner TL, TR, BL, BR -- the bottom pair on the canvas's last row that carries
    art (a 22-native button keeps a key gap below its 20-row art)."""
    H, W = p.shape
    rows = [y for y in range(H) if (p[y] != key).any()]
    bot = rows[-1] if rows else H - 1
    out = []
    for y0, dy, x0, dx in ((0, 1, 0, 1), (0, 1, W - 1, -1), (bot, -1, 0, 1), (bot, -1, W - 1, -1)):
        w = 0
        while w < W and p[y0, x0 + dx * w] == key:
            w += 1
        h = 0
        while 0 <= y0 + dy * h < H and p[y0 + dy * h, x0] == key:
            h += 1
        out.append((w, h))
    return out


def face_rows(p, key=KEY):
    """The rows that carry any art."""
    return [y for y in range(p.shape[0]) if (p[y] != key).any()]
