"""The CHOOSE YOUR FACTIONS picker on the real image (image_emu.py): FactionPickWin_build 0x4887A0 + the name list's
population (config_game's own sequence: ListBox_item x 7, ListBox_attach, set selection) at any g, then the real draws
of its FlatButtons (the drop arrows) and its name rows.

Lineage: the W2D scratch harness (2026-10-25, fac_emu.py), which reproduced the user's 1600x1200 shot 20261025-000825
pixel-exact: the 25 x 25 drop arrows' corners TL 2x2 / TR 1x2 / BL 2x1 / BR 1x1 and the 1 x 1 name-row notches.

ONE boot per Picker (~2 s, 3840x2160 by default); `build(g)` forces g the way thunk_ensure_scale sets it (g_popup_scale_num
AND g_stripe_period = stripe_period(g)) and re-runs the builder + population on the same boot (~0.5..4 s: the builder
re-allocates every canvas).  g_faction_active is held at 1 (thunk_faction_show's bracket in game).  The pristine image
has no g: build() is then the vanilla picker at the boot resolution's 1024 layout.
"""
import image_emu as IE
import scaling_laws as SL
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_ESP

FPW = 0x822718                 # the FactionPickWin static (config_game 0x58A5FF)
BUILD, ROW_PAINTER = 0x4887A0, 0x48A840
BUILD_CB, PARENT = 0x5898A0, 0x945818      # config_game's build args: callback, [0x945818]
DROP_INIT_SITE = 0x488FEE      # the 7 drop-arrow BaseButton_init calls (thunk_faction_droppos in the bake)
CONTENT_DRAW = 0x607E50
G_VA, G_STRIPE_PERIOD = 0x668740, 0x66879C
G_FACTION_ACTIVE = 0xA0D2D0    # pcave2 0x12D0
LB = 0x82ADD4                  # FactionPickWin + 0x86BC: the name ListBox (GraphicWin part +0x48, Dialog part +0xA60)
DLG = LB + 0xA60
LIST_WIN = LB + 0x48
DLG_SELECTED, DLG_HOVER = 0xEC, 0xF0       # ListBox_draw_item's state law: selected -> 2, hovered -> 1, else 0
LISTBOX_ITEM, LISTBOX_ATTACH, LISTBOX_SELECT = 0x60C920, 0x60A670, 0x609FA0
DRAW_ITEM = 0x60B530
NAMES = ("Gaia's Stepdaughters", "Human Hive", "University of Planet", "Morgan Industries", "Spartan Federation",
         "The Lord's Believers", "Peacekeeping Forces")


class Picker:
    def __init__(self, exe, w=3840, h=2160):
        e = self.e = IE.boot(exe, w, h)
        IE.Files(e)
        e.call(0x455610, count=0)
        e.call(0x6168F0, ecx=0x9B90D8, args=(0x40000,))
        e.call(0x616A00, count=50_000_000)
        self.patched = bytes(e.uc.mem_read(0x668760, 4)) != bytes(4)
        self.drops = []
        e.observe(DROP_INIT_SITE, lambda e: self.drops.append(e.reg(UC_X86_REG_ECX)))
        self.item_draw = self._find_item_draw()

    def _find_item_draw(self):
        """t_lb_item_stripes (the baked draw_item drop-in) when the image has it: the call @0x60C577's target."""
        e = self.e
        if bytes(e.uc.mem_read(0x60C577, 1)) != b"\xE8":
            return DRAW_ITEM
        return (0x60C57C + e.s32(0x60C578)) & 0xFFFFFFFF

    def build(self, g, selected=3):
        e = self.e
        self.drops = []
        if self.patched:
            e.w32(G_VA, g)
            e.w32(G_STRIPE_PERIOD, SL.stripe_period(g))
            e.w32(G_FACTION_ACTIVE, 1)
        e.call(BUILD, ecx=FPW, args=(BUILD_CB, 0, e.r32(PARENT)), count=400_000_000)
        for i, n in enumerate(NAMES, 1):
            e.call(LISTBOX_ITEM, ecx=LB, args=(e.cstr(n), i), count=50_000_000)
        adj = e.r32(e.r32(LB) + 8)
        e.call(LISTBOX_ATTACH, ecx=DLG, args=(FPW, e.r32(LB + adj + 0x24), e.r32(LB + adj + 0x28), 0x80020),
               count=200_000_000)
        e.call(LISTBOX_SELECT, ecx=LB, args=(selected,), count=50_000_000)
        assert len(self.drops) == 7, self.drops
        return self.drops

    def draw_drop(self, k, state):
        """FlatButton_content_draw of drop arrow k in draw state 0 / 1 / 2 -> its canvas."""
        e = self.e
        obj = self.drops[k]
        e.w32(obj + 0xAB8, state)
        e.call(CONTENT_DRAW, ecx=obj, count=20_000_000)
        return IE.canvas_of(e, obj)

    def drop_art(self, k, state):
        """The native state sprite (+0xAD4 + 4*state) the arrow draws: rows of palette indices."""
        e = self.e
        spr = e.r32(self.drops[k] + 0xAD4 + 4 * state)
        w, h, pitch, data = e.s32(spr + 0x18), e.s32(spr + 0x1C), e.s32(spr + 0x10), e.r32(spr + 4)
        return [list(e.uc.mem_read(data + y * pitch, w)) for y in range(h)]

    def draw_row(self, item, hover=-1):
        """One name row through the image's own draw_item path (t_lb_item_stripes in the bake), item hovered or not ->
        the list canvas."""
        e = self.e
        e.w32(DLG + DLG_HOVER, hover)
        e.call(self.item_draw, ecx=LB, args=(item,), count=50_000_000)
        return IE.canvas_of(e, LIST_WIN)

    def row_rects(self):
        """Each item's row rect (L, T, R, B) as the painter receives it (one observed redraw of every item; the
        painter's 2nd arg is the item's list id, 1-based here, so the rect is keyed by the drawn index)."""
        e = self.e
        rects, last = {}, []

        def grab(uc, _a, _s, _u):
            esp = uc.reg_read(UC_X86_REG_ESP)
            rp = e.r32(esp + 0x10)
            last.append(tuple(e.s32(rp + 4 * i) for i in range(4)))
        h = e.uc.hook_add(UC_HOOK_CODE, grab, begin=ROW_PAINTER, end=ROW_PAINTER)
        try:
            for i in range(len(NAMES)):
                last.clear()
                self.draw_row(i)
                assert len(last) == 1, (i, last)
                rects[i] = last[0]
        finally:
            e.uc.hook_del(h)
        return rects
