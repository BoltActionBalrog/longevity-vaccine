"""Datalinks topic list on the DatalinkWin stripe grid: Unicorn parity for the t_dl_tile_ph fix (2026-10-06).

The defect: DatalinkWin_list_bg_fill 0x42A100 / _list_row_bg 0x42A150 tile the ListBox's OWN canvas (Win +0x444,
`lea ecx,[win+0x444]` at 0x42A13A / 0x42A192), and our Buffer_tile wrappers t_dl_tile_bg / t_dl_tile_row restripe
that canvas with t_dl_restripe on its own rows (phase 0), while the ring around the list is restriped on the
DatalinkWin canvas's rows (t_dl_build_leave, phase 0 there).  The list canvas sits at parent row
top = rRect1.top + rRect2.top (Win +0x140 + Win +0x150, the sum Win_flip_rect_2 0x5ECFE0 uses) = floor(32 g / 16)
= 2 g, so whenever 2 g mod P != 0 (P = 4 above 1080 px: every ODD g >= 23) the list's first / last T rows carry
the member the parent grid puts on the other side of the seam -> a 2T-row band (1600x1200, g = 25: C4 x 4 at
screen rows 95..98 and 761..764).

The fix (proposed edits to scripts/assemble_dl.py, embedded below as EDITS and applied in memory when the file does
not carry them yet):
  * new cell g_dl_rs_phi (pcave2 0x27ED0, FREE per cave_map);
  * t_dl_restripe adds the cell to its row index before `div P` (the 6 B come from the dead `mov eax,[g]` + nop
    the stripe-rule patch left in front of `mov eax,[g_stripe_period]`: 591 B -> 591 B, nothing else moves);
  * ONE new wrapper t_dl_tile_ph (pinned in the free gap pcave2 0x23AC0) serves both sites: it stores the
    list's parent-local top in the cell, tiles, restripes, clears the cell (so the whole-canvas callers keep
    phase 0).  t_dl_tile_bg / t_dl_tile_row stay as dead bytes so the auto-layout does not move.

Everything runs as the patcher will write it: the WHOLE live pcave2 image (every patches.yaml content entry
resolved by the patcher's own ByteTemplate) with the two edited entries overlaid, into the ENGINE's own
Buffer_tile bytes (0x5DA860, pristine base); only IntersectRect, Buffer_set_clip and Buffer_copy_4 are stubbed
(the stub paints the 1-row native tile into real pixel memory the restripe then reads and rewrites).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import pathlib
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

pytest.importorskip("keystone", reason="keystone absent")
pytest.importorskip("unicorn", reason="unicorn absent")
pytest.importorskip("pefile", reason="pefile absent")

from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

import apply_patches as ap  # noqa: E402
import assemble_se as SE  # noqa: E402

# ---- placement (cave_map.py is the arbiter) --------------------------------------------------------------------
PCAVE2, CAVE_LEN = 0x00A0C000, 0x40000      # >= pcave2 length in patches.yaml (grown 0x30000 -> 0x31000 2026-10-10, caviar_dirty_rect)
TILE_PH_OFF, TILE_PH_LIMIT = 0x23AC0, 0x23C20   # --at 0x23AC0: FREE; prev t_rw_init_leave ends 0x23ABF, next t_rw_restripe 0x23C20
PHI_OFF, PHI_LIMIT = 0x27ED0, 0x27F00           # --at 0x27ED0: FREE; prev g_dl_mono ends 0x27ED0, next t_fdicon_checker 0x27F00
RESTRIPE_OFF, RESTRIPE_LEN = 0x222F0, 591       # t_dl_restripe's live slot; t_dl_cu starts 0x22540 (zero slack)

# ---- the proposed source edits (exact old -> new text, each old occurs once) -------------------------------------
EDITS = [
    # (i) the cell
    ('    ("g_dl_mono", 0x27EC0, 16),   # +0 best +4 x +8 y +C num\n',
     '    ("g_dl_mono", 0x27EC0, 16),   # +0 best +4 x +8 y +C num\n'
     '    ("g_dl_rs_phi", 0x27ED0, 4),  # t_dl_tile_ph: the list\'s parent-local top (Win +0x140 + +0x150); t_dl_restripe adds it to its row\n'),
    ('IMMG, FSCR = CELL["g_dl_immg"], CELL["g_dl_fscr"]\n',
     'IMMG, FSCR = CELL["g_dl_immg"], CELL["g_dl_fscr"]\n'
     'PHI = CELL["g_dl_rs_phi"]\n'),
    # (ii) t_dl_restripe: drop the dead `mov eax,[g]` + nop, add the phase to the row index (591 B -> 591 B)
    ('    ; P law\n'
     '    mov     eax, dword ptr [{G:#x}]\n'
     '    mov eax, dword ptr [0x66879c]\n'
     '    nop\n'
     '    mov     dword ptr [{RS[\'P\']:#x}], eax\n',
     '    ; P law: the period cell thunk_ensure_scale writes with g (2 under 1080 px, 4 above)\n'
     '    mov     eax, dword ptr [0x66879c]\n'
     '    mov     dword ptr [{RS[\'P\']:#x}], eax\n'),
    ('    mov     eax, edi\n'
     '    xor     edx, edx\n'
     '    div     dword ptr [{RS[\'P\']:#x}]\n',
     '    mov     eax, edi\n'
     '    add     eax, dword ptr [{PHI:#x}]\n'
     '    xor     edx, edx\n'
     '    div     dword ptr [{RS[\'P\']:#x}]\n'),
    # (iii) the new wrapper
    ('def asm_dl_tile_row() -> str:\n'
     '    return _tile_wrap()\n',
     'def asm_dl_tile_row() -> str:\n'
     '    return _tile_wrap()\n'
     '\n'
     '\n'
     'def asm_dl_tile_ph() -> str:\n'
     '    # 2026-10-06: ONE Buffer_tile drop-in for both list sites (bg fill 0x42A140, row bg 0x42A1F7);\n'
     '    # thiscall(ecx = the list canvas = Win+0x444)(sprite,srcX,srcY,dstX,dstY,w,h) RET 0x1C.\n'
     '    # Phase = Win.rRect1.top + Win.rRect2.top (+0x140 / +0x150 = [ecx-0x304] / [ecx-0x2F4]), the sum\n'
     '    # Win_flip_rect_2 0x5ECFE0 maps local rows to the parent with -- so the list restripes on the\n'
     '    # DatalinkWin canvas grid the ring is on.  Stored raw: t_dl_restripe reduces (row + phase) by the\n'
     '    # real period itself (`div P`).  Cleared after the call: the whole-canvas callers\n'
     '    # (t_dl_build_leave, t_dl_cu) keep phase 0.  g <= 16: untouched tail-jump to Buffer_tile.\n'
     '    return f"""\n'
     '    cmp     dword ptr [{G:#x}], 16\n'
     '    jle     native\n'
     '    mov     eax, dword ptr [esp+0x10]\n'
     '    mov     dword ptr [{RS[\'X0\']:#x}], eax\n'
     '    mov     edx, dword ptr [esp+0x18]\n'
     '    add     edx, eax\n'
     '    mov     dword ptr [{RS[\'X1\']:#x}], edx\n'
     '    mov     eax, dword ptr [esp+0x14]\n'
     '    mov     dword ptr [{RS[\'Y0\']:#x}], eax\n'
     '    mov     edx, dword ptr [esp+0x1C]\n'
     '    add     edx, eax\n'
     '    mov     dword ptr [{RS[\'Y1\']:#x}], edx\n'
     '    mov     dword ptr [{RS[\'BUF\']:#x}], ecx\n'
     '    mov     eax, dword ptr [ecx-0x304]\n'
     '    add     eax, dword ptr [ecx-0x2F4]\n'
     '    mov     dword ptr [{PHI:#x}], eax\n'
     '    push    dword ptr [esp+0x1C]\n'
     '    push    dword ptr [esp+0x1C]\n'
     '    push    dword ptr [esp+0x1C]\n'
     '    push    dword ptr [esp+0x1C]\n'
     '    push    dword ptr [esp+0x1C]\n'
     '    push    dword ptr [esp+0x1C]\n'
     '    push    dword ptr [esp+0x1C]\n'
     '    call    {BUFFER_TILE:#x}\n'
     '    call    t_dl_restripe\n'
     '    and     dword ptr [{PHI:#x}], 0\n'
     '    ret     0x1C\n'
     'native:\n'
     '    jmp     {BUFFER_TILE:#x}\n'
     '"""\n'),
    # (iv) layout: appended LAST and pinned in the free gap, so no existing thunk moves
    ('    ("t_ts_flowdraw", asm_ts_flowdraw, "dl_scale"),\n'
     ']\n',
     '    ("t_ts_flowdraw", asm_ts_flowdraw, "dl_scale"),\n'
     '    ("t_dl_tile_ph", asm_dl_tile_ph, "dl_scale"),\n'
     ']\n'),
    ('PINNED = {"t_dl_wheel_down": WHEEL_DOWN_OFF, "t_dl_wheel_up": 0x23210}\n',
     'PINNED = {"t_dl_wheel_down": WHEEL_DOWN_OFF, "t_dl_wheel_up": 0x23210, "t_dl_tile_ph": TILE_PH_OFF}\n'),
    ('WHEEL_DOWN_OFF = 0x13DB0       # relocated v2 head slot (592 B free after thunk_hud_baseargs; the old 0x230B0 slot is 352 B)\n',
     'WHEEL_DOWN_OFF = 0x13DB0       # relocated v2 head slot (592 B free after thunk_hud_baseargs; the old 0x230B0 slot is 352 B)\n'
     'TILE_PH_OFF = 0x23AC0          # t_dl_tile_ph (2026-10-06): free gap t_rw_init_leave..t_rw_restripe (0x23ABF..0x23C20, cave_map)\n'),
    # (v) the two sites
    ('    redirect("list_bg.tile", "DatalinkWin_list_bg_fill", 0x42A140, BUFFER_TILE, "t_dl_tile_bg", "tile + P-law restripe")\n'
     '    redirect("list_row.tile", "DatalinkWin_list_row_bg", 0x42A1F7, BUFFER_TILE, "t_dl_tile_row", "row tile + restripe (canonical pair order)")\n',
     '    redirect("list_bg.tile", "DatalinkWin_list_bg_fill", 0x42A140, BUFFER_TILE, "t_dl_tile_ph", "tile + P-law restripe on the parent grid (phase = list top in DatalinkWin)")\n'
     '    redirect("list_row.tile", "DatalinkWin_list_row_bg", 0x42A1F7, BUFFER_TILE, "t_dl_tile_ph", "row tile + restripe on the parent grid (canonical pair order)")\n'),
    # (vi) docstring
    ('  t_dl_tile_bg/row   Buffer_tile wrappers @0x42A140/0x42A1F7: tile, then restripe the dest rect.\n',
     '  t_dl_tile_bg/row   Buffer_tile wrappers @0x42A140/0x42A1F7: tile, then restripe the dest rect.\n'
     '                     SUPERSEDED 2026-10-06 by t_dl_tile_ph (dead bytes kept: layout anchors).\n'
     '  t_dl_tile_ph       2026-10-06, pinned in the free gap pcave2 0x23AC0, both list sites: stages the\n'
     '                     rect, stores the list\'s parent-local top ([Win+0x140] + [Win+0x150], canvas =\n'
     '                     Win+0x444) in g_dl_rs_phi, tiles, restripes (t_dl_restripe adds the cell to its\n'
     '                     row index: the list stripes on the DatalinkWin grid the ring is on), clears it.\n'),
]

ASSEMBLE_DL = ROOT / "scripts" / "assemble_dl.py"
PATCHES = pathlib.Path(ap.DEFAULT_PATCHES)


def patched_source() -> str:
    text = ASSEMBLE_DL.read_text(encoding="utf-8")
    if "g_dl_rs_phi" in text:          # the edits are applied in the tree: use the file as it is
        return text
    for old, new in EDITS:
        assert text.count(old) == 1, old[:60]
        text = text.replace(old, new)
    return text


def load_patched_module():
    d = tempfile.mkdtemp(prefix="dlphase_")
    p = pathlib.Path(d) / "assemble_dl_dlphase.py"
    p.write_text(patched_source(), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("assemble_dl_dlphase", p)
    mod = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(mod)
    return mod


AD = load_patched_module()
LAYOUT, _END, NAMES = AD.assemble_all()
_SITES, _GROUPS, CAVES, SYMBOLS = ap.load_patches(PATCHES)
SYMTAB = ap.build_symbol_table(SYMBOLS, CAVES)
PCAVE2_CAVE = next(c for c in CAVES if c["id"] == "pcave2")
assert PCAVE2_CAVE["virtual_addr"] == PCAVE2 == AD.PCAVE2 == SE.PCAVE2
NEW_SYMS = {"g_dl_rs_phi": PCAVE2 + PHI_OFF, "t_dl_tile_ph": PCAVE2 + TILE_PH_OFF}
SYMTAB2 = dict(SYMTAB, **NEW_SYMS)


def live_entries() -> dict[str, tuple[int, bytes]]:
    """Every pcave2 content entry of patches.yaml, resolved by the patcher's ByteTemplate (= what it writes)."""
    out = {}
    for e in PCAVE2_CAVE["contents"]:
        off = int(e["offset"])
        out[e["id"]] = (off, bytes(ap.ByteTemplate(e["bytes"]).resolve(PCAVE2 + off, SYMTAB)))
    return out


def live_template(name: str) -> str:
    return next(e["bytes"] for e in PCAVE2_CAVE["contents"] if e["id"] == name)


LIVE = live_entries()


def live_image() -> bytearray:
    img = bytearray(CAVE_LEN)
    for _name, (off, b) in LIVE.items():
        img[off:off + len(b)] = b
    return img


def new_image() -> bytearray:
    img = live_image()
    for name in ("t_dl_restripe", "t_dl_tile_ph"):
        off, b = LAYOUT[name]
        img[off:off + len(b)] = b
    return img


def templates() -> dict[str, str]:
    """{entry: patches.yaml byte template} for the two entries that change, from the patched assembler."""
    out = {}
    for name in ("t_dl_restripe", "t_dl_tile_ph"):
        off, b = LAYOUT[name]
        tpl = AD.templatize(b, PCAVE2 + off, NAMES)
        assert bytes(ap.ByteTemplate(tpl).resolve(PCAVE2 + off, SYMTAB2)) == b, name
        out[name] = tpl
    return out


# ---- static parity: nothing but the two entries changes ----------------------------------------------------------
def test_layout_is_the_live_layout_except_the_two_entries():
    assert LAYOUT["t_dl_restripe"][0] == RESTRIPE_OFF == LIVE["t_dl_restripe"][0]
    assert len(LAYOUT["t_dl_restripe"][1]) == RESTRIPE_LEN == len(LIVE["t_dl_restripe"][1])
    assert LAYOUT["t_dl_tile_ph"][0] == TILE_PH_OFF
    for name, (off, b) in LAYOUT.items():
        if name in ("t_dl_restripe", "t_dl_tile_ph"):
            continue
        assert name in LIVE, name
        assert LIVE[name] == (off, b), f"{name} moved or changed"
    assert NAMES["t_dl_tile_ph"] == NEW_SYMS["t_dl_tile_ph"]
    assert AD.CELL["g_dl_rs_phi"] == NEW_SYMS["g_dl_rs_phi"]
    assert AD.CELLS_BY["g_dl_rs_phi"] == (PHI_OFF, 4)


def test_applied_live_yaml_is_the_assembler_output():
    """Once applied: the live t_dl_restripe / t_dl_tile_ph templates ARE the edited assembler's, the cell and the
    thunk occupy exactly their reserved slots, and both list sites call t_dl_tile_ph."""
    t = templates()
    assert live_template("t_dl_restripe") == t["t_dl_restripe"]
    assert live_template("t_dl_tile_ph") == t["t_dl_tile_ph"]
    off, b = LAYOUT["t_dl_tile_ph"]
    assert LIVE["t_dl_tile_ph"][0] == off == TILE_PH_OFF and off + len(b) <= TILE_PH_LIMIT
    assert int(SYMBOLS["g_dl_rs_phi"]["offset"]) == PHI_OFF and int(SYMBOLS["g_dl_rs_phi"]["size"]) == 4
    ranges = [(o, o + len(x), n) for n, (o, x) in LIVE.items() if n != "t_dl_tile_ph"]
    for name, spec in SYMBOLS.items():
        if spec.get("cave") == "pcave2" and "size" in spec and name != "g_dl_rs_phi":
            ranges.append((int(spec["offset"]), int(spec["offset"]) + int(spec["size"]), name))
    for lo, hi in ((off, off + len(b)), (PHI_OFF, PHI_OFF + 4)):
        assert [n for o0, o1, n in ranges if o0 < hi and o1 > lo] == []
    live = {s["id"]: s for s in _SITES if s.get("group") == "dl_scale"}
    for sid, s in {s["id"]: s for s in AD.site_list(NAMES)}.items():
        assert live[sid]["new_bytes"] == s["new"], sid
    assert AD.verify_live(AD.site_list(NAMES)) == []


# ---- harness ---------------------------------------------------------------------------------------------------
STACK = 0x00200000
DATA = 0x00300000
MARKER = 0x00DEAD00
WIN = DATA + 0x2000                        # the ListBox GraphicWin part (DatalinkWin +0xF670 in the game)
CANVAS = WIN + 0x444
PIXELS = DATA + 0x20000
NAVY_TILE, HOVER_TILE, BACK_TILE = DATA + 0x8000, DATA + 0x9000, DATA + 0xA000   # 24x24 native 1-row dithers
PAIRS = {NAVY_TILE: (0xC4, 0x41), HOVER_TILE: (0xAE, 0xEE), BACK_TILE: (0x41, 0xC6)}
F_CLIP, F_DATA, F_DATA2, F_W, F_H, F_PITCH = 0x20, 0x54, 0x58, 0x80, 0x84, 0x4A8
RRECT1_LEFT, RRECT1_TOP, RRECT2_TOP = 0x13C, 0x140, 0x150
BUFFER_TILE, BUFFER_TILE_LEN = 0x005DA860, 0x18C
BUFFER_SET_CLIP = 0x005D8000               # Buffer_tile: call 0x5d8000 (0x5DA8F9 / 0x5DA9DB)
BUFFER_COPY_4 = 0x005DFF00                 # Buffer_tile: call 0x5dff00 (0x5DA9AB)
IAT_INTERSECTRECT = 0x00669338             # Buffer_tile: call dword ptr [0x669338]
IR_STUB = 0x005D8100
G_VA, P_VA = 0x00668740, 0x0066879C
UNDRAWN = 0x09
REGS = {UC_X86_REG_EBX: 0x0B0B0B0B, UC_X86_REG_ESI: 0x51515151, UC_X86_REG_EDI: 0xD1D1D1D1,
        UC_X86_REG_EBP: 0xB9B9B9B9, UC_X86_REG_EAX: 0x0EA0EA0E, UC_X86_REG_EDX: 0x0ED0ED0E}
SCALED = tuple(range(17, 41))


def _w32(mu, addr, val):
    mu.mem_write(addr, int(val & 0xFFFFFFFF).to_bytes(4, "little"))


def _r32(mu, addr):
    return int.from_bytes(mu.mem_read(addr, 4), "little")


def _s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


def win_rects(top: int, client_area: bool) -> tuple[int, int]:
    """(rRect1.top, rRect2.top) as Win_init 0x5EBD80 leaves them for a window at parent row `top` with no chrome
    above its client area: a client-area window ([+0x9C]&2) keeps the position in rRect2, a plain one in rRect1.
    The DL ListBox is attached with flags 0x1000020 (@0x429C04) -- whether ListBox_attach adds a bar bit is not
    read, so both layouts are tested; the sum is right for either."""
    return (0, top) if client_area else (top, 0)


class Emu:
    def __init__(self, image: bytearray, symtab: dict[str, int]):
        self.symtab = symtab
        mu = self.mu = Uc(UC_ARCH_X86, UC_MODE_32)
        mu.mem_map(PCAVE2, max(CAVE_LEN, (len(image) + 0xFFF) & ~0xFFF))   # the live pcave2 length (0x44000 since 2026-11-07)
        for page in sorted({BUFFER_TILE & ~0xFFF, BUFFER_SET_CLIP & ~0xFFF, BUFFER_COPY_4 & ~0xFFF,
                            IAT_INTERSECTRECT & ~0xFFF, G_VA & ~0xFFF, MARKER & ~0xFFF}):
            mu.mem_map(page, 0x1000)
        mu.mem_map(STACK, 0x10000)
        mu.mem_map(DATA, 0x40000)
        mu.mem_write(PCAVE2, bytes(image))
        tile = SE.base_exe_bytes(BUFFER_TILE, BUFFER_TILE_LEN)
        assert tile[:3] == b"\x83\xEC\x24" and tile[-3:] == b"\xC2\x1C\x00", "Buffer_tile is not where it was"
        assert tile[0x99:0x9E] == b"\xE8\x02\xD7\xFF\xFF" and tile[0x14B:0x150] == b"\xE8\x50\x55\x00\x00"
        mu.mem_write(BUFFER_TILE, tile)
        mu.mem_write(BUFFER_SET_CLIP, b"\xC2\x04\x00")
        mu.mem_write(BUFFER_COPY_4, b"\xC2\x1C\x00")
        mu.mem_write(IR_STUB, b"\xC2\x0C\x00")
        _w32(mu, IAT_INTERSECTRECT, IR_STUB)
        for t in PAIRS:
            _w32(mu, t + F_DATA, t + 0x100)
            _w32(mu, t + F_W, 24)
            _w32(mu, t + F_H, -24)
        self.calls = []
        self.w = self.h = 0
        for name, va in (("Buffer_tile", BUFFER_TILE), ("t_dl_restripe", symtab["t_dl_restripe"]),
                         ("Buffer_copy_4", BUFFER_COPY_4), ("Buffer_set_clip", BUFFER_SET_CLIP),
                         ("IntersectRect", IR_STUB)):
            mu.hook_add(UC_HOOK_CODE, self._hook, user_data=name, begin=va, end=va)

    def _rect(self, p):
        return [_s32(_r32(self.mu, p + 4 * i)) for i in range(4)]

    def _hook(self, mu, address, size, name):
        esp = mu.reg_read(UC_X86_REG_ESP)
        ecx = mu.reg_read(UC_X86_REG_ECX)
        args = [_r32(mu, esp + 4 + 4 * i) for i in range(7)]
        if name in ("Buffer_tile", "t_dl_restripe"):
            self.calls.append({"fn": name, "esp": esp, "ret": _r32(mu, esp), "ecx": ecx, "args": args,
                               "phi": _r32(mu, self.symtab.get("g_dl_rs_phi", PCAVE2 + PHI_OFF))})
        elif name == "IntersectRect":                 # BOOL IntersectRect(out, a, b), stdcall
            a, b = self._rect(args[1]), self._rect(args[2])
            r = [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]
            ok = r[0] < r[2] and r[1] < r[3]
            for i in range(4):
                _w32(mu, args[0] + 4 * i, r[i] if ok else 0)
            mu.reg_write(UC_X86_REG_EAX, 1 if ok else 0)
        elif name == "Buffer_set_clip":               # thiscall(buffer, RECT*): the clip lives at +0x20
            mu.mem_write(ecx + F_CLIP, bytes(mu.mem_read(args[0], 16)))
        elif name == "Buffer_copy_4":                 # thiscall(src; dst, sx, sy, dx, dy, w, h): 1:1, dest-clipped
            assert ecx in PAIRS, hex(ecx)
            dst, _sx, sy, dx, dy, w, h = (_s32(a) for a in args)
            assert dst == CANVAS and (w, h) == (24, 24), "Buffer_tile blits whole tiles"
            clip = self._rect(dst + F_CLIP)
            data, pitch = _r32(mu, dst + F_DATA), _r32(mu, dst + F_PITCH)
            top, mate = PAIRS[ecx]
            for y in range(max(dy, clip[1]), min(dy + h, clip[3])):
                v = top if ((sy + y - dy) & 1) == 0 else mate       # the native tile: a 1-row dither
                x0, x1 = max(dx, clip[0]), min(dx + w, clip[2])
                if x1 > x0:
                    mu.mem_write(data + y * pitch + x0, bytes([v]) * (x1 - x0))
            mu.reg_write(UC_X86_REG_EAX, 0)

    def setup(self, g, top, client_area, w, h, period=None, phi_sentinel=0):
        mu = self.mu
        self.w, self.h = w, h
        _w32(mu, G_VA, g)
        _w32(mu, P_VA, period or SL.stripe_period(g))
        _w32(mu, self.symtab.get("g_dl_rs_phi", PCAVE2 + PHI_OFF), phi_sentinel)
        mu.mem_write(WIN, b"\x00" * 0x1000)
        r1, r2 = win_rects(top, client_area)
        _w32(mu, WIN + RRECT1_TOP, r1)
        _w32(mu, WIN + RRECT2_TOP, r2)
        _w32(mu, CANVAS + F_DATA, PIXELS)
        _w32(mu, CANVAS + F_W, w)
        _w32(mu, CANVAS + F_H, -h)
        _w32(mu, CANVAS + F_PITCH, w)
        for i, v in enumerate((0, 0, w, h)):
            _w32(mu, CANVAS + F_CLIP + 4 * i, v)
        mu.mem_write(PIXELS, bytes([UNDRAWN]) * (w * h))

    def run(self, which, ecx, args):
        mu = self.mu
        self.calls.clear()
        sp = STACK + 0x8000
        mu.mem_write(sp - 0x400, b"\xA5" * 0x800)
        _w32(mu, sp, MARKER)
        for i, a in enumerate(args):
            _w32(mu, sp + 4 + 4 * i, a)
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.reg_write(UC_X86_REG_ECX, ecx)
        for r, v in REGS.items():
            mu.reg_write(r, v)
        mu.emu_start(self.symtab[which], MARKER, count=20_000_000)
        assert mu.reg_read(UC_X86_REG_EIP) == MARKER
        assert mu.reg_read(UC_X86_REG_ESP) == sp + 4 + 0x1C, "stack imbalance (RET 0x1C contract)"
        for r in (UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP):
            assert mu.reg_read(r) == REGS[r]
        assert bytes(mu.mem_read(sp + 0x20, 0x100)) == b"\xA5" * 0x100, "caller frame written"
        assert self._rect(CANVAS + F_CLIP) == [0, 0, self.w, self.h], "Buffer_tile restores the canvas clip"
        return list(self.calls), sp

    def pixels(self):
        return bytes(self.mu.mem_read(PIXELS, self.w * self.h))

    def column(self, x=5):
        px = self.pixels()
        return [px[y * self.w + x] for y in range(self.h)]

    def engine_args(self, top, client_area, tile, x0, y0, w, h):
        """The seven Buffer_tile args as 0x42A100 / 0x42A150 build them: srcOff = rRect1.LT + dest."""
        r1t, _r2t = win_rects(top, client_area)
        return [tile, 0 + x0, r1t + y0, x0, y0, w, h]

    def paint_list(self, which, g, top, client_area, w, h, rows=()):
        """bg fill over the whole list canvas, then one row tile per (y, rh, tile)."""
        self.run(which, CANVAS, self.engine_args(top, client_area, NAVY_TILE, 0, 0, w, h))
        tops = {}
        for y, rh, tile in rows:
            self.run(which, CANVAS, self.engine_args(top, client_area, tile, 0, y, w, rh))
            for r in range(y, y + rh):
                tops[r] = PAIRS[tile]
        return tops


@pytest.fixture(scope="module")
def emu():
    return Emu(new_image(), SYMTAB2)


@pytest.fixture(scope="module")
def shipped():
    return Emu(live_image(), SYMTAB)


def _law(top, r, pair, g, period=None):
    P = period or SL.stripe_period(g)
    return pair[0] if ((top + r) % P) < ((P + 1) >> 1) else pair[1]


def _composite(column, top, g, margin=24):
    """Parent column through ring / list / ring; the ring is on the DatalinkWin grid (t_dl_build_leave, phase 0)."""
    out = []
    for py in range(top - margin, top + len(column) + margin):
        if top <= py < top + len(column):
            out.append((py, column[py - top]))
        else:
            out.append((py, 0xC4 if SL.stripe_top(py, g) else 0x41))
    return out


def _runs(col):
    out = []
    for py, v in col:
        if out and out[-1][0] == v and out[-1][2] == py - 1:
            out[-1][2] = py
        else:
            out.append([v, py, py])
    return [tuple(r) for r in out]


def dl_list_top(g):
    """The topic list's parent-local top: native 32 (the measured 50 at g = 25 is floor(32 * 25 / 16), the only
    native value that scales to it)."""
    return SL.popup_scale_floor(32, g)


LIST_W = 40
ROWS_PITCH = 23


def _rows(h, hover=2, back=5):
    out = []
    k = 0
    while (k + 1) * ROWS_PITCH <= h:
        out.append((k * ROWS_PITCH, ROWS_PITCH, HOVER_TILE if k == hover else BACK_TILE if k == back else NAVY_TILE))
        k += 1
    return out


# ---- the law, every g, both Win layouts -------------------------------------------------------------------------
@pytest.mark.parametrize("g", SCALED)
@pytest.mark.parametrize("client_area", [True, False])
def test_bg_and_rows_sit_on_the_parent_grid(emu, g, client_area):
    top, h = dl_list_top(g), 8 * ROWS_PITCH + 7
    emu.setup(g, top, client_area, LIST_W, h)
    row_pairs = emu.paint_list("t_dl_tile_ph", g, top, client_area, LIST_W, h, _rows(h))
    px = emu.pixels()
    for r in range(h):
        want = _law(top, r, row_pairs.get(r, PAIRS[NAVY_TILE]), g)
        assert px[r * LIST_W:(r + 1) * LIST_W] == bytes([want]) * LIST_W, (g, client_area, r)
    assert _r32(emu.mu, NEW_SYMS["g_dl_rs_phi"]) == 0, "the cell is cleared after every call"


@pytest.mark.parametrize("g", SCALED)
def test_no_band_where_the_list_meets_the_ring(emu, g):
    top, h = dl_list_top(g), 666 if g == 25 else 8 * ROWS_PITCH + 7
    emu.setup(g, top, True, LIST_W, h)
    emu.paint_list("t_dl_tile_ph", g, top, True, LIST_W, h, [(y, rh, NAVY_TILE) for y, rh, _t in _rows(h)])
    runs = _runs(_composite(emu.column(), top, g))[1:-1]
    assert {b - a + 1 for _v, a, b in runs} == {SL.stripe_rows(g)}, (g, runs[:4], runs[-4:])


@pytest.mark.parametrize("top", list(range(0, 14)) + [50, 57, 65, 105, 1001])
@pytest.mark.parametrize("period", [2, 4, 6, 8])
@pytest.mark.parametrize("client_area", [True, False])
def test_any_top_any_period(emu, top, period, client_area):
    """The phase is reduced by t_dl_restripe's own `div P`: right for every period, 6 included."""
    h = 61
    emu.setup(25, top, client_area, LIST_W, h, period=period)
    emu.paint_list("t_dl_tile_ph", 25, top, client_area, LIST_W, h)
    assert emu.column() == [_law(top, r, PAIRS[NAVY_TILE], 25, period) for r in range(h)]
    y, rh = 17, 23
    emu.run("t_dl_tile_ph", CANVAS, emu.engine_args(top, client_area, HOVER_TILE, 3, y, LIST_W - 3, rh))
    col5, col_last, col1 = emu.column(5), emu.column(LIST_W - 1), emu.column(1)
    for r in range(h):
        pair = PAIRS[HOVER_TILE] if y <= r < y + rh else PAIRS[NAVY_TILE]
        assert col5[r] == col_last[r] == _law(top, r, pair, 25, period), (top, period, r)
    assert col1[y] == _law(top, y, PAIRS[NAVY_TILE], 25, period), "x < 3 is outside the row rect"


# ---- call contract ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("g", (18, 22, 25, 40))
@pytest.mark.parametrize("client_area", [True, False])
def test_scaled_path_passes_the_args_through_and_phases_the_restripe(emu, g, client_area):
    top = dl_list_top(g)
    emu.setup(g, top, client_area, LIST_W, 100)
    args = emu.engine_args(top, client_area, NAVY_TILE, 4, 46, 30, 23)
    calls, sp = emu.run("t_dl_tile_ph", CANVAS, args)
    assert [c["fn"] for c in calls] == ["Buffer_tile", "t_dl_restripe"]
    bt, rs = calls
    assert bt["ecx"] == CANVAS and bt["args"] == args and bt["esp"] == sp - 0x20
    assert PCAVE2 + TILE_PH_OFF < bt["ret"] < PCAVE2 + TILE_PH_LIMIT, "Buffer_tile returns into the wrapper"
    assert rs["phi"] == top and bt["phi"] == top, "the cell holds rRect1.top + rRect2.top during the call"
    assert _r32(emu.mu, NEW_SYMS["g_dl_rs_phi"]) == 0
    assert [_r32(emu.mu, AD.RS[k]) for k in ("BUF", "X0", "Y0", "X1", "Y1")] == [CANVAS, 4, 46, 34, 69]


@pytest.mark.parametrize("g", (16, 12, 1))
@pytest.mark.parametrize("client_area", [True, False])
def test_native_gate_is_a_bare_tail_jump(emu, g, client_area):
    emu.setup(g, 50, client_area, LIST_W, 100, phi_sentinel=0x5A5A5A5A)
    for i, k in enumerate(("BUF", "X0", "Y0", "X1", "Y1")):
        _w32(emu.mu, AD.RS[k], 0x11111111 * (i + 1))
    args = emu.engine_args(50, client_area, NAVY_TILE, 0, 0, LIST_W, 100)
    calls, sp = emu.run("t_dl_tile_ph", CANVAS, args)
    assert [c["fn"] for c in calls] == ["Buffer_tile"]
    c = calls[0]
    assert c["esp"] == sp and c["ret"] == MARKER and c["ecx"] == CANVAS and c["args"] == args
    assert _r32(emu.mu, NEW_SYMS["g_dl_rs_phi"]) == 0x5A5A5A5A, "the cell is not touched at g <= 16"
    assert [_r32(emu.mu, AD.RS[k]) for k in ("BUF", "X0", "Y0", "X1", "Y1")] == [0x11111111 * (i + 1) for i in range(5)]
    # the engine's own tiling, untouched: a 1-row dither phased by srcOffY mod 24 (0x5DA957)
    r1t, _ = win_rects(50, client_area)
    col = emu.column()
    assert col == [0xC4 if ((r + (r1t % 24)) & 1) == 0 else 0x41 for r in range(100)]


def test_g16_bytes_native_path_is_the_shipped_wrappers_native_path():
    """Gate + native tail of the new wrapper are byte-identical to t_dl_tile_bg / t_dl_tile_row's."""
    new = LAYOUT["t_dl_tile_ph"][1]
    old = LIVE["t_dl_tile_bg"][1]
    assert new[:7] == old[:7] == b"\x83\x3D" + SYMTAB["g_popup_scale_num"].to_bytes(4, "little") + b"\x10"
    assert new[7] == old[7] == 0x7E                       # jle native
    assert new[-5] == old[-5] == 0xE9                     # jmp Buffer_tile
    for b, off in ((new, TILE_PH_OFF), (old, LIVE["t_dl_tile_bg"][0])):
        tail = PCAVE2 + off + len(b)
        assert tail + _s32(int.from_bytes(b[-4:], "little")) == BUFFER_TILE
        assert PCAVE2 + off + 9 + b[8] == tail - 5         # the jle lands on the jmp


@pytest.mark.parametrize("g", (18, 25, 40))
def test_null_dest_draws_nothing_and_clears_the_cell(emu, g):
    """Buffer_tile returns 7 when the dest has no plane ([+0x54] == [+0x58] == 0); t_dl_restripe bails on it too."""
    emu.setup(g, 50, True, LIST_W, 100)
    _w32(emu.mu, CANVAS + F_DATA, 0)
    _w32(emu.mu, CANVAS + F_DATA2, 0)
    args = emu.engine_args(50, True, NAVY_TILE, 0, 0, LIST_W, 100)
    calls, _sp = emu.run("t_dl_tile_ph", CANVAS, args)
    assert [c["fn"] for c in calls] == ["Buffer_tile", "t_dl_restripe"]
    assert calls[0]["args"] == args
    assert emu.mu.reg_read(UC_X86_REG_EAX) == 7
    assert emu.column() == [UNDRAWN] * 100
    assert _r32(emu.mu, NEW_SYMS["g_dl_rs_phi"]) == 0


# t_dl_restripe is a plain CALL helper (ret, no args): run it through a tiny driver so run()'s RET 0x1C contract
# still holds.
DRIVER_OFF = 0x304C0                       # scratch inside the emulated cave image (not part of any patch; 0x2FFE0 is thunk_se_stripe_px_ph since 2026-10-11, 0x2EE0 t_orn_rmargin and 0x2DF60 t_orn_oc since 2026-10-24)


def _install_driver(e: Emu):
    """`call t_dl_restripe / ret 0x1C` at a scratch VA; registered under the name t_dl_restripe_as_call."""
    if "t_dl_restripe_as_call" in e.symtab:
        return
    va = PCAVE2 + DRIVER_OFF
    assert all(not (o < DRIVER_OFF + 16 and o + len(b) > DRIVER_OFF) for o, b in LIVE.values())
    b = SE.assemble(f"call {e.symtab['t_dl_restripe']:#x}\n ret 0x1C", va)
    e.mu.mem_write(va, b)
    e.symtab = dict(e.symtab, t_dl_restripe_as_call=va)


@pytest.mark.parametrize("g", (22, 25, 40))
@pytest.mark.parametrize("phase", (0, 1, 2, 3, 50, 1001))
@pytest.mark.parametrize("pair", list(PAIRS.values()))
def test_restripe_alone_adds_the_cell_to_its_row(emu, g, phase, pair):
    """t_dl_restripe's other callers (t_dl_build_leave, t_dl_cu) run it with the cell at 0 = the shipped law."""
    _install_driver(emu)
    w, h = 40, 32
    emu.setup(g, 0, True, w, h, phi_sentinel=phase)
    plane = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            plane[y * w + x] = pair[0] if (x + y) % 3 == 0 else (pair[1] if (x + y) % 3 == 1 else 0x77)
    emu.mu.mem_write(PIXELS, bytes(plane))
    for k, v in (("BUF", CANVAS), ("X0", 2), ("Y0", 1), ("X1", w - 3), ("Y1", h - 2)):
        _w32(emu.mu, AD.RS[k], v)
    emu.run("t_dl_restripe_as_call", 0, [0] * 7)
    out = emu.pixels()
    for y in range(h):
        for x in range(w):
            o, n = plane[y * w + x], out[y * w + x]
            if 2 <= x < w - 3 and 1 <= y < h - 2 and o in pair:
                assert n == _law(phase, y, pair, g), (x, y, hex(o), hex(n))
            else:
                assert n == o, (x, y, hex(o), hex(n))
    assert _r32(emu.mu, NEW_SYMS["g_dl_rs_phi"]) == phase, "the restripe itself never writes the cell"


# ---- the measured defect, shipped vs new ------------------------------------------------------------------------
# scanlines_after2_20261004\1600x1200\...221714.png, g = 25: DatalinkWin top = screen row 47 (frame rows 47..48),
# list = screen rows 97..762 (parent rows 50..715, 666 rows), C4 x 4 at screen 95..98 and 761..764 = parent 48..51
# and 714..717.
MEASURED_G25 = [(0xC4, 48, 51), (0xC4, 714, 717)]


@pytest.mark.parametrize("which,client_area", [("t_dl_tile_bg", True), ("t_dl_tile_row", True),
                                               ("t_dl_tile_bg", False)])
def test_shipped_wrappers_reproduce_the_1600x1200_band(shipped, which, client_area):
    top, h = 50, 666
    shipped.setup(25, top, client_area, LIST_W, h)
    shipped.paint_list(which, 25, top, client_area, LIST_W, h, [(y, rh, NAVY_TILE) for y, rh, _t in _rows(h)])
    runs = _runs(_composite(shipped.column(), top, 25))
    assert [r for r in runs if r[2] - r[1] + 1 != 2] == MEASURED_G25


def test_new_wrapper_clears_the_1600x1200_band(emu):
    top, h = 50, 666
    emu.setup(25, top, True, LIST_W, h)
    emu.paint_list("t_dl_tile_ph", 25, top, True, LIST_W, h, [(y, rh, NAVY_TILE) for y, rh, _t in _rows(h)])
    runs = _runs(_composite(emu.column(), top, 25))[1:-1]
    assert [r for r in runs if r[2] - r[1] + 1 != 2] == []


@pytest.mark.parametrize("g", SCALED)
def test_which_g_show_the_band_today(shipped, emu, g):
    """Shipped: the top seam is off by (2g mod P) rows -> a 2T band at every odd g >= 23 (P = 4), clean at even g
    and under 1080 px (P = 2 divides 2g).  New: clean everywhere."""
    top, h = dl_list_top(g), 8 * ROWS_PITCH + 7
    T = SL.stripe_rows(g)
    for e, which, want_band in ((shipped, "t_dl_tile_bg", (top % SL.stripe_period(g)) != 0), (emu, "t_dl_tile_ph", False)):
        e.setup(g, top, True, LIST_W, h)
        e.paint_list(which, g, top, True, LIST_W, h)
        runs = _runs(_composite(e.column(), top, g))
        seam = [r for r in runs if r[1] <= top <= r[2] or r[1] <= top - 1 <= r[2]]
        assert any(r[2] - r[1] + 1 != T for r in seam) == want_band, (g, which, seam)
    assert ((top % SL.stripe_period(g)) != 0) == (g >= 23 and g % 2 == 1)


# ---- fragments for the brief -----------------------------------------------------------------------------------
def fragments() -> str:
    t = templates()
    sites = {s["id"]: s for s in AD.site_list(NAMES)}
    lines = ["# symbols:",
             f"  g_dl_rs_phi:                   {{ cave: pcave2, offset: {PHI_OFF:#x}, size: 4 }}",
             f"  t_dl_tile_ph:                  {{ cave: pcave2, offset: {TILE_PH_OFF:#x} }}   # dl_scale ({len(LAYOUT['t_dl_tile_ph'][1])}B)",
             "# code_caves pcave2 contents: REPLACE t_dl_restripe's bytes line with",
             f"        bytes: \"{t['t_dl_restripe']}\"",
             "# code_caves pcave2 contents: NEW entry",
             f"      - id: t_dl_tile_ph\n        offset: {TILE_PH_OFF:#x}\n        bytes: \"{t['t_dl_tile_ph']}\"",
             "# sites: new_bytes of list_bg.tile / list_row.tile"]
    for sid in ("list_bg.tile", "list_row.tile"):
        lines.append(f"  {sid}: new_bytes: \"{sites[sid]['new']}\"   # {sites[sid]['note']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(fragments())
