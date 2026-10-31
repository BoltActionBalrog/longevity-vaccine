"""Differential: the force-path content-key PRESCAN of thunk_fe_pair_remap v9 and thunk_s54_restripe v3 stays
inside the dest buffer (law scaling_laws.force_prescan_bounds), under Unicorn, against the pinned pre-fix-7 bytes.

WHY.  Both thunks key their dither family on the first <= 8 rows of the staged rect (g_fe_x/y/w/h).  Up to fe v8 /
s54 v2 that block was read UNCLAMPED from (max(x,0), max(y,0)), w columns by min(h,8) rows.  devfill stages its
caller's rect inclusively (R-L+1 / B-T+1), and devfill callers do pass half-open rects (census: (0,0,3765,2112) on
a 3765x2112 buffer), so a short frame flush with the buffer bottom, a frame hanging below it, or one wholly below
it read rows >= H -- an access violation whenever the DIB ends on a page (the plane here ends exactly at the end of
its mapping, as a CreateDIBSection buffer can).  The walk itself was always clamped (remap_clip_bounds).

What is pinned:
  * the LIVE bytes' prescan reads exactly the law block force_prescan_bounds(...) -- every case, in-bounds or not
    (the read instruction is hooked, so the set of pixels it touches is the measurement);
  * the OLD bytes (fe v8 / s54 v2, pinned below) read outside the buffer / fault on the out-of-bounds cases -- the
    test can see the defect it guards against (run the law test on the old bytes and it fails);
  * the LIVE family flags equal the law (count over the block > (x1 - x0) // 2, per family);
  * for every frame whose old block was in bounds (g 16..60, the devfill FRAMES at their real scaled sizes, pure
    masks and mixed content near the thresholds) the LIVE and OLD bytes leave byte-identical planes and flags;
  * for the out-of-bounds frames (x, y >= 0) the LIVE result equals the OLD bytes run on the rect pre-clamped to
    the buffer -- the clamp is the only behaviour change.

Skips (does not fail) if unicorn / capstone are absent.
"""
from __future__ import annotations

import pathlib
import random
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scaling_laws as SL  # noqa: E402

unicorn = pytest.importorskip("unicorn", reason="unicorn absent")
capstone = pytest.importorskip("capstone", reason="capstone absent")

from unicorn import (UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_MEM_READ_UNMAPPED, UC_MODE_32,  # noqa: E402
                     Uc, UcError)
from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP  # noqa: E402

import apply_patches as ap  # noqa: E402

PCAVE2, CAVE_LEN = 0xA0C000, 0x31000
G_CELL, P_CELL = 0x668740, 0x66879C          # g_popup_scale_num / g_stripe_period (menu_strip_thunks)
STACK = 0x00200000
MARKER = 0x00DEAD00
BUFOBJ = 0x01000000
PL_MAP = 0x03000000
F_CLIP, F_DATA, F_W, F_H, F_STRIDE = 0x20, 0x54, 0x80, 0x84, 0x4A8

# ---- the pre-fix-7 bytes (patches.yaml before 2026-10-17n): thunk_fe_pair_remap v8 938B, thunk_s54_restripe v2 356B
OLD_FE = (
    "83 3D {abs32:g_popup_scale_num} 10 0F 8E 9C 03 00 00 53 56 57 55 C6 05 {abs32:g_rm_navy} 00 C6 05 "
    "{abs32:g_rm_bd} 00 C7 05 {abs32:g_rm_c5} 00 00 00 00 C7 05 {abs32:g_rm_bf} 00 00 00 00 31 C0 87 05 "
    "{abs32:g_rm_f0ovr} A3 {abs32:g_rm_f0} 83 3D {abs32:g_rm_force} 00 0F 84 E9 00 00 00 C7 05 {abs32:g_rm_force} "
    "00 00 00 00 A1 {abs32:g_fe_dst} 85 C0 0F 84 31 01 00 00 8B 70 54 85 F6 0F 84 26 01 00 00 8B 90 A8 04 00 00 "
    "8B 0D {abs32:g_fe_y} 85 C9 7D 02 31 C9 89 C8 0F AF C2 01 C6 A1 {abs32:g_fe_x} 85 C0 7D 02 31 C0 01 C6 8B 3D "
    "{abs32:g_fe_w} 85 FF 0F 8E F2 00 00 00 8B 0D {abs32:g_fe_h} 85 C9 0F 8E E4 00 00 00 83 F9 08 7E 05 B9 08 00 "
    "00 00 31 DB 31 ED 49 78 36 51 56 89 F9 49 78 29 8A 04 0E 3C C4 75 03 43 EB F3 3C C6 75 03 45 EB EC 3C C5 75 "
    "08 FF 05 {abs32:g_rm_c5} EB E0 3C BF 75 DC FF 05 {abs32:g_rm_bf} EB D4 5E 59 01 D6 EB C7 89 F8 D1 E8 39 C3 "
    "7E 07 C6 05 {abs32:g_rm_navy} 01 39 C5 7E 07 C6 05 {abs32:g_rm_bd} 01 31 D2 39 05 {abs32:g_rm_c5} 7E 01 42 "
    "89 15 {abs32:g_rm_c5} 31 D2 39 05 {abs32:g_rm_bf} 7E 01 42 89 15 {abs32:g_rm_bf} EB 5F A1 {abs32:g_fe_src} "
    "85 C0 74 56 8B 70 54 85 F6 74 4F 8B 88 84 00 00 00 F7 D9 7E 45 83 F9 08 7E 05 B9 08 00 00 00 8B B8 80 00 00 "
    "00 85 FF 7E 31 8B 90 A8 04 00 00 31 DB 49 78 17 89 F5 51 89 F9 49 78 0A 80 7C 0D 00 C4 75 F6 43 EB F3 59 01 "
    "D6 EB E6 89 F8 D1 E8 39 C3 7E 07 C6 05 {abs32:g_rm_navy} 01 8B 35 {abs32:g_fe_dst} 8B 86 80 00 00 00 8B 8E "
    "84 00 00 00 F7 D9 8B 15 {abs32:g_fe_x} 03 15 {abs32:g_fe_w} 39 C2 7E 02 89 C2 3B 56 28 7E 03 8B 56 28 89 15 "
    "{abs32:g_rm_xend} 8B 15 {abs32:g_fe_y} 03 15 {abs32:g_fe_h} 39 CA 7E 02 89 CA 3B 56 2C 7E 03 8B 56 2C 89 15 "
    "{abs32:g_rm_yend} A1 {abs32:g_rm_povr} 85 C0 74 0C C7 05 {abs32:g_rm_povr} 00 00 00 00 EB 0B A1 "
    "{abs32:g_popup_scale_num} A1 9C 87 66 00 90 89 C3 8D 48 01 D1 E9 89 0D {abs32:g_rm_hn} 8B 3D {abs32:g_fe_y} "
    "85 FF 7D 02 31 FF 3B 7E 24 7D 03 8B 7E 24 3B 3D {abs32:g_rm_yend} 0F 8D 6F 01 00 00 89 F8 03 05 "
    "{abs32:g_rm_yph} 31 D2 F7 F3 3B 15 {abs32:g_rm_hn} 66 BA C4 E0 7C 29 66 BA 41 E1 C6 05 {abs32:g_rm_col} EE "
    "C6 05 {abs32:g_rm_bdcol} 41 C6 05 {abs32:g_rm_c5col} 41 C6 05 {abs32:g_rm_bfcol} 53 C6 05 {abs32:g_rm_f0col} "
    "B9 EB 23 C6 05 {abs32:g_rm_col} AE C6 05 {abs32:g_rm_bdcol} C6 C6 05 {abs32:g_rm_c5col} C5 C6 05 "
    "{abs32:g_rm_bfcol} BF C6 05 {abs32:g_rm_f0col} F0 8B 86 A8 04 00 00 0F AF C7 03 46 54 8B 0D {abs32:g_fe_x} "
    "85 C9 7D 02 31 C9 3B 4E 20 7D 03 8B 4E 20 8D 2C 08 3B 0D {abs32:g_rm_xend} 0F 8D D6 00 00 00 8A 45 00 3C E0 "
    "0F 84 C1 00 00 00 3C E1 0F 84 B9 00 00 00 3C AE 0F 84 A7 00 00 00 3C EE 0F 84 9F 00 00 00 3C 41 74 70 3C C4 "
    "0F 84 85 00 00 00 3C C5 74 2B 3C BF 74 3A 3C 53 74 36 3C F0 74 45 3C B9 74 41 3C C6 0F 85 84 00 00 00 80 3D "
    "{abs32:g_rm_bd} 00 74 7B A0 {abs32:g_rm_bdcol} 88 45 00 EB 71 80 3D {abs32:g_rm_c5} 00 74 68 A0 "
    "{abs32:g_rm_c5col} 88 45 00 EB 5E 80 3D {abs32:g_rm_bf} 00 74 55 A0 {abs32:g_rm_bfcol} 88 45 00 EB 4B 83 3D "
    "{abs32:g_rm_f0} 00 74 42 A0 {abs32:g_rm_f0col} 88 45 00 EB 38 80 3D {abs32:g_rm_navy} 00 75 1D 80 3D "
    "{abs32:g_rm_bd} 00 75 AB 80 3D {abs32:g_rm_c5} 00 75 B5 EB 1B 80 3D {abs32:g_rm_navy} 00 74 12 88 55 00 EB "
    "0D A0 {abs32:g_rm_col} 88 45 00 EB 03 88 75 00 45 41 E9 1E FF FF FF 47 E9 85 FE FF FF 5D 5F 5E 5B C3 ")
OLD_S54 = (
    "E8 {rel32:thunk_fe_pair_remap} 83 3D {abs32:g_popup_scale_num} 10 0F 8E 51 01 00 00 53 56 57 55 83 EC 08 C7 "
    "04 24 00 00 00 00 A1 {abs32:g_fe_dst} 85 C0 0F 84 2F 01 00 00 8B 70 54 85 F6 0F 84 24 01 00 00 8B 90 A8 04 "
    "00 00 8B 0D {abs32:g_fe_y} 85 C9 7D 02 31 C9 89 C8 0F AF C2 01 C6 A1 {abs32:g_fe_x} 85 C0 7D 02 31 C0 01 C6 "
    "8B 3D {abs32:g_fe_w} 85 FF 0F 8E F0 00 00 00 8B 0D {abs32:g_fe_h} 85 C9 0F 8E E2 00 00 00 83 F9 08 7E 05 B9 "
    "08 00 00 00 31 DB 31 ED 49 78 28 51 56 89 F9 49 78 1B 8A 04 0E 3C 54 75 03 43 EB F3 3C 41 75 03 45 EB EC 3C "
    "C2 75 E8 FF 44 24 08 EB E2 5E 59 01 D6 EB D5 89 F8 D1 E8 39 C5 0F 8E 9D 00 00 00 C6 44 24 04 54 39 C3 7F 0E "
    "C6 44 24 04 C2 39 04 24 0F 8E 86 00 00 00 8B 35 {abs32:g_fe_dst} A1 {abs32:g_popup_scale_num} A1 9C 87 66 00 "
    "90 89 C3 8B 3D {abs32:g_fe_y} 85 FF 7D 02 31 FF 3B 7E 24 7D 03 8B 7E 24 3B 3D {abs32:g_rm_yend} 7D 57 89 F8 "
    "31 D2 F7 F3 8D 4B 01 D1 E9 39 CA 8A 54 24 04 7C 02 B2 41 8B 86 A8 04 00 00 0F AF C7 03 46 54 8B 0D "
    "{abs32:g_fe_x} 85 C9 7D 02 31 C9 3B 4E 20 7D 03 8B 4E 20 8D 2C 08 3B 0D {abs32:g_rm_xend} 7D 14 8A 45 00 3A "
    "44 24 04 74 04 3C 41 75 03 88 55 00 45 41 EB E4 47 EB A1 83 C4 08 5D 5F 5E 5B C3 ")


def _load():
    _s, _g, caves, symbols = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    symtab = dict(ap.build_symbol_table(symbols, caves))
    cave = next(c for c in caves if c["id"] == "pcave2")
    ent = {c["id"]: c for c in cave["contents"]}
    return symtab, ent


SYMTAB, _ENT = _load()
FE_VA = PCAVE2 + int(_ENT["thunk_fe_pair_remap"]["offset"])
S54_VA = PCAVE2 + int(_ENT["thunk_s54_restripe"]["offset"])


def _resolve(tpl: str, va: int) -> bytes:
    return bytes(ap.ByteTemplate(" ".join(str(tpl).split())).resolve(va, SYMTAB))


LIVE = {"fe": _resolve(_ENT["thunk_fe_pair_remap"]["bytes"], FE_VA),
        "s54": _resolve(_ENT["thunk_s54_restripe"]["bytes"], S54_VA)}
OLD = {"fe": _resolve(OLD_FE, FE_VA), "s54": _resolve(OLD_S54, S54_VA)}
FLAGS = ("g_rm_navy", "g_rm_bd", "g_rm_c5", "g_rm_bf")
FAMILY_OF = {"g_rm_navy": 0xC4, "g_rm_bd": 0xC6, "g_rm_c5": 0xC5, "g_rm_bf": 0xBF}


def _prescan_read_va(code: bytes, va: int) -> int:
    """The prescan's pixel load: the FIRST `mov al, byte ptr [esi + ecx]` of the thunk (both versions)."""
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    for ins in md.disasm(code, va):
        if ins.mnemonic == "mov" and ins.op_str == "al, byte ptr [esi + ecx]":
            return ins.address
    raise AssertionError("prescan load not found")


READ_VA = {(ver, n): _prescan_read_va(b[n], FE_VA if n == "fe" else S54_VA)
           for ver, b in (("live", LIVE), ("old", OLD)) for n in ("fe", "s54")}


def _r32(u, a):
    return struct.unpack("<I", bytes(u.mem_read(a, 4)))[0]


def run(ver, entry, *, g, bw, bh, stage, plane, clip=None):
    """One force-path call (g_rm_force = 1, devfill's STEP3 staging) on a bw x bh buffer whose plane ENDS at the end
    of its mapping.  Returns dict(plane, flags, reads={'fe': set, 's54': set} of (x, y) the prescan loads touched,
    fault=None | (eip, addr))."""
    code = LIVE if ver == "live" else OLD
    u = Uc(UC_ARCH_X86, UC_MODE_32)
    u.mem_map(PCAVE2, CAVE_LEN)
    u.mem_write(FE_VA, code["fe"])
    u.mem_write(S54_VA, code["s54"])
    u.mem_map(G_CELL & ~0xFFF, 0x1000)
    u.mem_write(G_CELL, struct.pack("<i", g))
    u.mem_write(P_CELL, struct.pack("<i", SL.stripe_period(g)))
    u.mem_map(STACK - 0x10000, 0x20000)
    u.mem_map(MARKER & ~0xFFF, 0x1000)
    u.mem_map(BUFOBJ, 0x1000)
    stride = (bw + 3) & ~3
    size = stride * bh
    span = (size + 0xFFF) & ~0xFFF or 0x1000
    u.mem_map(PL_MAP, span)
    base = PL_MAP + span - size                      # the plane ends exactly where the mapping ends
    u.mem_write(base, bytes(plane))
    u.mem_write(BUFOBJ + F_CLIP, struct.pack("<4i", *(clip or (0, 0, bw, bh))))
    u.mem_write(BUFOBJ + F_DATA, struct.pack("<I", base))
    u.mem_write(BUFOBJ + F_W, struct.pack("<2i", bw, -bh))
    u.mem_write(BUFOBJ + F_STRIDE, struct.pack("<i", stride))
    x, y, w, h = stage
    for n, v in (("g_fe_dst", BUFOBJ + 0x0), ("g_fe_x", x), ("g_fe_y", y), ("g_fe_w", w), ("g_fe_h", h),
                 ("g_rm_force", 1), ("g_fe_src", 0), ("g_rm_povr", 0), ("g_rm_f0ovr", 0), ("g_rm_yph", 0)):
        u.mem_write(SYMTAB[n], struct.pack("<i", v))
    reads = {"fe": set(), "s54": set()}

    x0 = max(x, 0)

    def on_load(m, addr, _size, who):                   # esi = row start + x0, ecx = column within the block
        row_off = m.reg_read(UC_X86_REG_ESI) - base - x0
        assert row_off % stride == 0
        reads[who].add((x0 + m.reg_read(UC_X86_REG_ECX), row_off // stride))
    for n in ("fe", "s54"):
        va = READ_VA[(ver, n)]
        u.hook_add(UC_HOOK_CODE, on_load, n, va, va)
    bad = []

    def on_bad(m, _access, addr, _size, _value, _ud):
        bad.append((m.reg_read(UC_X86_REG_EIP), addr))
        return False
    u.hook_add(UC_HOOK_MEM_READ_UNMAPPED, on_bad)
    u.mem_write(STACK, struct.pack("<I", MARKER))
    u.reg_write(UC_X86_REG_ESP, STACK)
    fault = None
    try:
        u.emu_start(entry, MARKER, count=100_000_000)
    except UcError:
        fault = bad[0] if bad else (u.reg_read(UC_X86_REG_EIP), None)
    if fault is None:
        assert u.reg_read(UC_X86_REG_EIP) == MARKER and u.reg_read(UC_X86_REG_ESP) == STACK + 4
        assert _r32(u, SYMTAB["g_rm_force"]) == (0 if g > 16 else 1)   # consumed at g > 16; g <= 16 never arms it
    return {"plane": bytes(u.mem_read(base, size)),
            "flags": {f: u.mem_read(SYMTAB[f], 1)[0] for f in FLAGS},
            "reads": reads, "fault": fault, "stride": stride}


def law_block(stage, bw, bh):
    x, y, w, h = stage
    x0, x1, y0, y1 = SL.force_prescan_bounds(x, y, w, h, bw, bh)
    return {(c, r) for r in range(y0, y1) for c in range(x0, x1)}, (x0, x1, y0, y1)


def old_block(stage):
    x, y, w, h = stage
    x0, y0 = max(x, 0), max(y, 0)
    if w <= 0 or h <= 0:
        return set()
    return {(c, r) for r in range(y0, y0 + min(h, 8)) for c in range(x0, x0 + w)}


def in_buffer(block, bw, bh):
    return all(0 <= c < bw and 0 <= r < bh for c, r in block)


def _mask(bw, bh, top, mate):
    stride = (bw + 3) & ~3
    out = bytearray(stride * bh)
    for r in range(bh):
        out[r * stride:r * stride + bw] = bytes([top if r % 2 == 0 else mate]) * bw
    return out


ENTRIES = {"fe": FE_VA, "s54": S54_VA}

# ---- (1) the probe's out-of-bounds frames: a 1000 x 60 buffer, devfill-staged (x, y, R-L+1, B-T+1) ----------------
OOB = [((0, 54, 1000 - 0 + 1, 60 - 54 + 1), "half-open rect (R,B = W,H), 7 rows staged"),
       ((0, 0, 1001, 61), "full-window half-open rect (0,0,W,H)"),
       ((0, 56, 1000, 25), "frame hanging below the buffer, top 4 rows above the bottom"),
       ((0, 70, 1000, 21), "frame wholly below the buffer"),
       ((990, 10, 40, 6), "frame running off the right edge"),
       ((1200, 5, 20, 5), "frame wholly right of the buffer")]
IN = [((0, 54, 1000, 6), "inclusive frame flush with the bottom"),
      ((-20, 10, 1000, 21), "frame starting left of the buffer (L < 0)"),
      ((3, -4, 200, 12), "frame starting above the buffer (T < 0)")]
BW, BH = 1000, 60


@pytest.mark.parametrize("who", ("fe", "s54"))
@pytest.mark.parametrize("g", (17, 22, 25, 40, 60))
@pytest.mark.parametrize("stage,label", OOB + IN, ids=[c[1] for c in OOB + IN])
def test_live_prescan_reads_exactly_the_law_block(who, g, stage, label):
    res = run("live", ENTRIES[who], g=g, bw=BW, bh=BH, stage=stage, plane=_mask(BW, BH, 0xC6, 0x41))
    assert res["fault"] is None, (label, res["fault"])
    want, _ = law_block(stage, BW, BH)
    assert res["reads"]["fe"] == want, label
    if who == "s54":
        assert res["reads"]["s54"] == want, label
    assert in_buffer(res["reads"]["fe"] | res["reads"]["s54"], BW, BH)


@pytest.mark.parametrize("who", ("fe", "s54"))
@pytest.mark.parametrize("g", (22, 25, 40))
@pytest.mark.parametrize("stage,label", OOB, ids=[c[1] for c in OOB])
def test_old_prescan_reads_past_the_buffer(who, g, stage, label):
    """The defect, measured: the pre-fix-7 bytes read outside the W x H pixel area on every OOB frame, and fault
    (READ_UNMAPPED, the plane ends on its mapping) on the three the investigator's probe found."""
    res = run("old", ENTRIES[who], g=g, bw=BW, bh=BH, stage=stage, plane=_mask(BW, BH, 0xC6, 0x41))
    touched = res["reads"]["fe"] | res["reads"]["s54"]
    assert res["fault"] is not None or not in_buffer(touched, BW, BH), label
    if stage[1] + min(stage[3], 8) > BH:                     # rows >= H: past the end of the mapping
        assert res["fault"] is not None and FE_VA <= res["fault"][0] < FE_VA + len(OLD["fe"]), (label, res["fault"])


@pytest.mark.parametrize("who", ("fe", "s54"))
@pytest.mark.parametrize("stage,label", [c for c in OOB if c[0][0] >= 0 and c[0][1] >= 0],
                         ids=[c[1] for c in OOB if c[0][0] >= 0 and c[0][1] >= 0])
@pytest.mark.parametrize("g", (17, 22, 25, 40, 60))
def test_live_oob_equals_old_on_the_clamped_rect(who, g, stage, label):
    """The clamp is the only behaviour change: LIVE on the raw rect == OLD on the rect pre-clamped to the buffer
    (x, y >= 0: the walk's own bounds are unchanged by the pre-clamp)."""
    x, y, w, h = stage
    pre = (x, y, max(0, min(x + w, BW) - x), max(0, min(y + h, BH) - y))
    rng = random.Random(g * 7 + len(label))
    plane = _mixed(rng, BW, BH)
    a = run("live", ENTRIES[who], g=g, bw=BW, bh=BH, stage=stage, plane=plane)
    b = run("old", ENTRIES[who], g=g, bw=BW, bh=BH, stage=pre, plane=plane)
    assert a["fault"] is None and b["fault"] is None
    assert a["plane"] == b["plane"] and a["flags"] == b["flags"], label


# ---- (2) the law of the flags ----------------------------------------------------------------------------------------
def _mixed(rng, bw, bh, density=None):
    """Pair members + bystanders, each family's top at a density that lands its 8-row count NEAR (x1-x0)//2."""
    stride = (bw + 3) & ~3
    out = bytearray(stride * bh)
    pool = [0xC4, 0xC6, 0xC5, 0xBF, 0x54, 0xC2]
    d = density if density is not None else rng.choice((0.04, 0.06, 0.0625, 0.07, 0.5))
    for r in range(bh):
        for c in range(bw):
            v = rng.random()
            out[r * stride + c] = (rng.choice(pool) if v < d else
                                   rng.choice((0x41, 0x41, 0x53, 0xE0, 0xE1, 0xAE, 0xEE, 0x1D, 0x00)))
    return out


@pytest.mark.parametrize("g", (17, 25, 40))
@pytest.mark.parametrize("seed", range(6))
def test_live_flags_are_the_law(g, seed):
    rng = random.Random(1000 + seed)
    bw, bh = 37 + 13 * seed, 9 + seed
    plane = _mixed(rng, bw, bh)
    for stage in ((0, 0, bw, bh), (2, 1, bw - 4, 5), (0, bh - 3, bw + 1, 4), (5, bh + 2, 10, 3), (-3, -2, bw, bh)):
        res = run("live", FE_VA, g=g, bw=bw, bh=bh, stage=stage, plane=plane)
        _, (x0, x1, y0, y1) = law_block(stage, bw, bh)
        stride = res["stride"]
        counts = {}
        for r in range(y0, y1):
            for c in range(x0, x1):
                v = plane[r * stride + c]
                counts[v] = counts.get(v, 0) + 1
        thr = (x1 - x0) // 2 if x1 > x0 and y1 > y0 else None
        for f, fam in FAMILY_OF.items():
            want = int(thr is not None and counts.get(fam, 0) > thr)
            assert res["flags"][f] == want, (stage, f, counts.get(fam, 0), thr)


# ---- (3) in-bounds frames: byte-identical to the old bytes, g 16..60 at the real devfill sizes --------------------
FRAMES = [((5, 4), (300, 20), 0xC2, 0x41), ((3, 7), (120, 60), 0xC6, 0x41), ((9, 2), (80, 30), 0xC4, 0x41),
          ((1, 1), (40, 12), 0x54, 0x41), ((2, 2), (16, 6), 0xC2, 0x41), ((0, 0), (24, 5), 0xC5, 0x41),
          ((4, 3), (24, 24), 0xBF, 0x53)]


@pytest.mark.parametrize("g", tuple(range(16, 61)))
def test_in_bounds_frames_unchanged_from_old_bytes(g):
    rng = random.Random(g)
    for (l, t), (nw, nh), top, mate in FRAMES:
        w, h = max(1, (nw * g) // 16), max(1, (nh * g) // 16)
        bw, bh = l + w + 6, t + h + 6
        stage = (l, t, w, h)                                     # devfill's inclusive staging of (l,t,l+w-1,t+h-1)
        assert in_buffer(old_block(stage), bw, bh)
        for plane in (_mask(bw, bh, top, mate), _mixed(rng, bw, bh)):
            for who in ("fe", "s54"):
                a = run("live", ENTRIES[who], g=g, bw=bw, bh=bh, stage=stage, plane=plane)
                b = run("old", ENTRIES[who], g=g, bw=bw, bh=bh, stage=stage, plane=plane)
                assert a["fault"] is None and b["fault"] is None
                assert a["plane"] == b["plane"] and a["flags"] == b["flags"], (g, top, who)
                assert a["reads"] == b["reads"]


def test_law_matches_the_old_block_whenever_that_was_in_bounds():
    rng = random.Random(5)
    for _ in range(4000):
        bw, bh = rng.randint(1, 60), rng.randint(1, 40)
        stage = (rng.randint(-10, 70), rng.randint(-10, 50), rng.randint(-3, 80), rng.randint(-3, 20))
        old = old_block(stage)
        law, (x0, x1, y0, y1) = law_block(stage, bw, bh)
        assert in_buffer(law, bw, bh)
        if in_buffer(old, bw, bh):
            assert law == old, (stage, bw, bh)
        assert (x1 <= x0 or y1 <= y0) == (not law)


def test_pinned_old_bytes_are_the_pre_fix_shapes():
    assert len(OLD["fe"]) == 938 and len(OLD["s54"]) == 356
    assert len(LIVE["fe"]) <= 0x103B0 - 0x10000                  # g_rr_src follows fe
    assert len(LIVE["s54"]) <= 0x13D20 - 0x13BA0                 # thunk_hud_baseargs follows s54
    assert LIVE["fe"] != OLD["fe"] and LIVE["s54"] != OLD["s54"]
