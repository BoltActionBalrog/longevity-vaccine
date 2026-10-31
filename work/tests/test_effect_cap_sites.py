"""effect_scale_cap: the two call sites in boom and every engine fact the thunks rely on, against the pristine exe."""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pefile  # noqa: E402
from apply_patches import _yaml_load  # noqa: E402  (the production loader)

import assemble_effect_cap as A  # noqa: E402
import config  # noqa: E402


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(config.terranx_bak(required=True)))


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def call_target(pe, va):
    assert rd(pe, va, 1) == b"\xE8"
    return (va + 5 + struct.unpack("<i", rd(pe, va + 1, 4))[0]) & 0xFFFFFFFF


def test_sites_and_their_arguments(pe):
    assert rd(pe, A.SITE_BUSTER, 5) == bytes.fromhex(A.ORIG_BUSTER) and call_target(pe, A.SITE_BUSTER) == A.BUFFER_DRAW_TABLE
    assert rd(pe, A.SITE_EXPL, 5) == bytes.fromhex(A.ORIG_EXPL) and call_target(pe, A.SITE_EXPL) == A.SPRITE_DRAW_TABLE
    # buster: num = (MapWin[+0x1DD98] + 16) * [ebp-0x10] (k14), den = [ebp-0xC] << 4 (k10*16), key 0xFF,
    # src = the buster.flc Buffer 0x915068, table 0x6F1B7C + idx<<12
    assert rd(pe, 0x50593E, 12) == bytes.fromhex("8B 80 98 DD 01 00 8D 14 5B 83 C0 10")
    assert rd(pe, 0x50594A, 4) == bytes.fromhex("0F AF 45 F0")
    assert rd(pe, 0x50596B, 6) == bytes.fromhex("8B 55 F4 C1 E2 04")
    assert rd(pe, 0x505964, 6) == bytes.fromhex("81 C2 7C 1B 6F 00")
    assert rd(pe, 0x50597D, 11) == bytes.fromhex("68 FF 00 00 00 51 B9 68 50 91 00")
    # the buster Buffer is a plain 300x248 GDI buffer (Buffer_init(0x12C, 0xF8, 0, 0)) fed by Flic 0x90EA68
    assert rd(pe, 0x504C1C, 21) == bytes.fromhex("51 51 68 F8 00 00 00 68 2C 01 00 00 B9 68 50 91 00 E8 3E 2A 0D")
    assert rd(pe, 0x50591A, 5) == bytes.fromhex("B9 68 EA 90 00")
    # k14 / k10 come from boom's stack tables indexed by g_pb_reactor 0x90F7D4: k14 = 2,3,4,5,5 at [ebp-0x88..],
    # k10 = 2 at [ebp-0x94..-0x88]
    assert rd(pe, 0x504C58, 19) == bytes.fromhex("A1 D4 F7 90 00 8B 8C 85 78 FF FF FF 8B 94 85 68 FF FF FF")
    assert rd(pe, 0x504BD1, 10) == bytes.fromhex("C7 85 7C FF FF FF 03 00 00 00")
    assert rd(pe, 0x504BDB, 7) == bytes.fromhex("C7 45 80 04 00 00 00")
    assert rd(pe, 0x504B8F, 5) == bytes.fromhex("B8 05 00 00 00")
    assert rd(pe, 0x504AF6, 5) == bytes.fromhex("BE 02 00 00 00")
    # the explosion's scale: SCALE_NUM_G = MapWin zoom + 16, SCALE_DEN_G = 16 (unless g_map_zoom_num > 0)
    assert rd(pe, 0x5058F0, 18) == bytes.fromhex("83 C0 10 C7 05 1C 6D 69 00 10 00 00 00 A3 18 6D 69 00")
    assert rd(pe, 0x505A44, 7) == bytes.fromhex("8D 0C 85 60 B4 7A 00")


def test_engine_cap_and_the_reject(pe):
    assert struct.unpack("<d", rd(pe, A.SCALE_MAX, 8))[0] == 4.0
    # Sprite_draw_table: f = (float)(num/den) stored, compared to 4.0, `test ah,0x41; jne accept`, else reject
    assert rd(pe, 0x5E904F, 0x2A) == bytes.fromhex(
        "DB 05 18 6D 69 00 DA 35 1C 6D 69 00 D9 1D 24 66 9B 00 D9 05 24 66 9B 00 DC 1D C8 FD 66 00 DF E0 F6 C4 41 "
        "75 11 6A 01 8B 4D 08")
    # num == den skips the test (1:1 path)
    assert rd(pe, 0x5E9026, 14) == bytes.fromhex("8B 0D 18 6D 69 00 3B 0D 1C 6D 69 00 74 71")
    # a null sprite returns 3 before anything
    assert rd(pe, 0x5E9004, 4) == bytes.fromhex("83 78 04 00")
    # the scaled path's dest rect: H' = ftol(h*f), W' = ftol(w*f), T0 = ftol(y + offy*f), L0 = ftol(x + offx*f)
    assert rd(pe, 0x5E92D7, 0x57) == bytes.fromhex(
        "8B 45 A4 DB 40 14 D8 0D 24 66 9B 00 E8 E0 C5 05 00 89 45 A8 8B 4D A4 DB 41 10 D8 0D 24 66 9B 00 E8 CC C5 "
        "05 00 89 45 AC DB 45 14 8B 55 A4 DB 42 24 D8 0D 24 66 9B 00 DE C1 E8 B3 C5 05 00 89 45 B0 DB 45 10 8B 45 "
        "A4 DB 40 20 D8 0D 24 66 9B 00 DE C1 E8 9A C5 05 00")
    # clip = IntersectRect(rect, dest+0x20)
    pe.parse_data_directories()
    names = {imp.address: imp.name for e in pe.DIRECTORY_ENTRY_IMPORT for imp in e.imports}
    assert names[0x669338] == b"IntersectRect"
    assert rd(pe, 0x5E9367, 0x15) == bytes.fromhex("8B 45 08 83 C0 20 50 8D 4D E4 51 8D 55 E4 52 FF 15 38 93 66 00")


def test_why_the_cap_exists_and_what_the_replica_follows(pe):
    """The enlarge path's ROW REPLAY knows run lengths 1, 2, 3 and "else 4" (0x5E97BE): a source row reaches at most 4
    dest rows -- the reason for the 4.0 cap.  Per source texel it does ONE table lookup against the dest pixel at the
    block's top-left (0x5E9801..0x5E980D) and stores that byte over the whole block (the run loop from [edx] then the
    row repeats), which the over-cap arm reproduces.  The runs come from Sprite_fill_scaling_table (0x5EB20F, 800
    entries @0x9B3AD8) walked by the clipped-table builders: a k-fold pre-stretch at den*k would run off the table."""
    assert rd(pe, 0x5E97BE, 0x18) == bytes.fromhex("3C 01 0F 84 6B 04 00 00 3C 02 0F 84 2C 03 00 00 3C 03 0F 84 B5 01 00 00")
    assert rd(pe, 0x5E9801, 0x1A) == bytes.fromhex("33 DB 8A 3E 8A 1F 03 1D C0 3A 9B 00 8A 03 8B 0A 88 07 47 49 75 FA 03 FD 2B 3A")
    assert rd(pe, 0x5E9935, 6) == bytes.fromhex("8D 3C 6F 8D 3C 2F")       # 4-row case: advance 3 more rows, not the run
    assert rd(pe, 0x5E9753, 8) == bytes.fromhex("8B 45 18 A3 C0 3A 9B 00")    # table = the table arg
    assert rd(pe, 0x5E9779, 3) == bytes.fromhex("8A 65 0C")                   # key = the low byte of the key arg
    assert rd(pe, 0x5E93DB, 2) == bytes.fromhex("0F 8D")                      # num >= den -> the enlarge path
    # the run generator: hi = max, lo = min; base, err = rem - 2lo; odd base -> err += hi; lo == 1 -> all hi
    assert rd(pe, 0x5EB22B, 0x44) == bytes.fromhex(
        "83 F9 01 7E 1B 8B C7 99 F7 F9 8B D8 8B C7 99 F7 F9 8B F2 8D 14 09 D1 E6 8B C6 D1 F8 2B C2 EB 08 33 F6 33 D2 "
        "8B DF 33 C0 F6 C3 01 74 02 03 C7 83 F9 01 75 12 B9 20 03 00 00 8B C3 BF D8 3A 9B 00 F3 AB 5F 5E")
    assert rd(pe, 0x5EB271, 0x1D) == bytes.fromhex(
        "B9 D8 3A 9B 00 03 C6 89 19 85 C0 7E 07 8D 7B 01 2B C2 89 39 83 C1 04 81 F9 58 47 9B 00")
    # the builders' entry walk / partial first run / truncated last run (x; y is the same code at 0x5EABBF)
    assert rd(pe, 0x5EAB41, 0x45) == bytes.fromhex(
        "BE D8 3A 9B 00 8B 3E 83 C6 04 2B C7 42 85 C0 7F F4 85 C0 8D 34 95 D8 3A 9B 00 7D 1C 8B 7C 24 14 F7 D8 2B C8 "
        "4A A3 EC 53 9B 00 89 17 B8 F0 53 9B 00 BF 01 00 00 00 EB 0D 8B 7C 24 14 B8 EC 53 9B 00 89 17 33 FF")
    assert rd(pe, 0x5EAB86, 0x21) == bytes.fromhex(
        "85 C9 7E 11 8B 16 83 C6 04 89 10 83 C0 04 2B CA 47 85 C9 7F EF 7D 0A 8B 50 FC 83 E8 04 03 D1 89 10")
    assert rd(pe, 0x5EAB41, 5) == rd(pe, 0x5EABF3, 5)
    # dest lock / unlock around the core (Buffer_get_data 0 -> return 3; Buffer_free_data(1) at the end)
    assert rd(pe, 0x5E9010, 0x16) == bytes.fromhex("8B 4D 08 E8 5B A3 FF FF 85 C0 75 0A B8 03 00 00 00 E9 15 0D 00 00")
    assert rd(pe, 0x5E9D2F, 0x0C) == bytes.fromhex("6A 01 8B 4D 08 E8 6A 97 FF FF 33 C0")
    assert rd(pe, 0x5E34CA, 3) == bytes.fromhex("C2 04 00")                   # Buffer_free_data RET 4


def test_sprite_fields_the_table_blit_reads(pe):
    """Sprite_draw_table reads only +4 / +0xC / +0x10 / +0x14 / +0x20 / +0x24 of its Sprite (the stack Sprites
    carry just those): every load of the Sprite pointer [ebp-0x5C] is followed by one of these reads or a call."""
    from capstone import CS_ARCH_X86, CS_MODE_32, Cs
    md = Cs(CS_ARCH_X86, CS_MODE_32); md.detail = True
    code = rd(pe, A.SPRITE_DRAW_TABLE, 0x5E9D44 - A.SPRITE_DRAW_TABLE)
    ins = list(md.disasm(code, A.SPRITE_DRAW_TABLE))
    seen = set()
    for i, x in enumerate(ins):
        if x.mnemonic == "mov" and x.op_str.endswith("dword ptr [ebp - 0x5c]") and not x.op_str.startswith("dword"):
            reg = x.op_str.split(",")[0]
            nxt = ins[i + 1]
            j = i + 1
            while f"[{reg}" not in nxt.op_str and nxt.mnemonic != "call":
                j += 1; nxt = ins[j]
            if nxt.mnemonic == "call":
                continue
            part = nxt.op_str.split(f"[{reg}")[1].split("]")[0].replace(" ", "")
            seen.add(int(part.lstrip("+"), 16) if part else 0)
    assert seen == {4, 0xC, 0x10, 0x14, 0x20, 0x24}


def test_callee_contracts(pe):
    assert rd(pe, 0x5E9D41, 3) == bytes.fromhex("C2 14 00")                                 # Sprite_draw_table RET 0x14
    assert rd(pe, 0x5E8FF2, 3) == bytes.fromhex("C2 1C 00")                                 # ..._scaled RET 0x1C
    # Sprite_draw_table_scaled saves SCALE_NUM_G/DEN_G, sets num/den, calls the core, restores
    assert rd(pe, A.SPRITE_DRAW_TABLE_SCALED, 0x20) == bytes.fromhex(
        "8B 44 24 14 8B 54 24 18 56 8B 35 18 6D 69 00 57 8B 3D 1C 6D 69 00 A3 18 6D 69 00 8B 44 24 24 89")
    assert call_target(pe, 0x5E8FDF) == A.SPRITE_DRAW_TABLE
    assert rd(pe, 0x5E8FE4, 12) == bytes.fromhex("89 3D 1C 6D 69 00 89 35 18 6D 69 00")
    # Buffer_draw_table: RET 0x1C; pushes the RAW key (push ebx @0x5D9590; the core masks it, and the -1 ->
    # g_ui_transparency_key swap only reaches Sprite+8, never read); data +0x54, pitch +0x4A8, w +0x80, h -[+0x84]
    assert rd(pe, 0x5D95A5, 3) == bytes.fromhex("C2 1C 00")
    assert rd(pe, 0x5D94C8, 13) == bytes.fromhex("83 FB FF 75 08 33 C9 8A 0D 14 6D 69 00")
    assert rd(pe, 0x5D9590, 1) == b"S" and rd(pe, 0x5E90A8, 5) == bytes.fromhex("25 FF 00 00 00")
    assert rd(pe, 0x5D94BB, 3) == bytes.fromhex("8B 46 58")                                 # surface gate
    assert rd(pe, 0x5D94E7, 6) == bytes.fromhex("8B 86 A8 04 00 00")
    assert rd(pe, 0x5D94FE, 8) == bytes.fromhex("8B 86 84 00 00 00 F7 D8")
    # _ftol (truncate) and the CRT allocator pair
    assert rd(pe, A.FTOL, 0x27)[:0x1B] == bytes.fromhex("55 8B EC 83 C4 F4 9B D9 7D FE 9B 66 8B 45 FE 80 CC 0C 66 89 45 FC D9 6D FC DF 7D")
    assert rd(pe, A.BUFFER_GET_DATA, 0x17) == bytes.fromhex("83 EC 6C 56 8B F1 8B 4E 58 85 C9 75 16 8B 46 54 85 C0 89 46 50 74 5B")


def test_yaml_wiring():
    doc = _yaml_load((ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8"))
    sites = {s["id"]: s for s in doc["sites"]}
    assert sites["boom.buster_draw"]["new_bytes"] == "E8 {rel32:t_pb_draw}"
    assert sites["boom.expl_draw"]["new_bytes"] == "E8 {rel32:t_tb_draw}"
    for sid, va, orig in (("boom.buster_draw", A.SITE_BUSTER, A.ORIG_BUSTER), ("boom.expl_draw", A.SITE_EXPL, A.ORIG_EXPL)):
        v = sites[sid]["virtual_addr"]; v = int(v, 16) if isinstance(v, str) else v
        assert v == va and sites[sid]["original_bytes"] == orig and sites[sid]["group"] == "effect_scale_cap"
    group = next(g for g in doc["groups"] if g["id"] == "effect_scale_cap")
    assert group["code_caves"] == ["pcave2"] and set(group["members"]) == {"boom.buster_draw", "boom.expl_draw"}
    cave = next(c for c in doc["code_caves"] if c["id"] == "pcave2")
    ids = {c["id"]: c for c in cave["contents"]}
    for n, _ in A.THUNKS:
        off = ids[n]["offset"]; off = int(off, 16) if isinstance(off, str) else off
        assert off == A.OFFS[n]
        assert off + len(A.assemble(n)) <= off + A.BUDGET[n]
    # the reserved windows: 0x30CB0-0x30DFF and 0x30E60-0x30FFF only
    for n in list(A.CELLS) + [n for n, _ in A.THUNKS]:
        off = A.CELLS.get(n) or A.OFFS[n]
        assert 0x30CB0 <= off < 0x30E00 or 0x30E60 <= off < 0x31000
