"""sprite_scale_cap: the 8 reject sites and every engine fact t_zc_* relies on, against the pristine exe."""
from __future__ import annotations

import pathlib
import re
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pefile  # noqa: E402
from apply_patches import _yaml_load  # noqa: E402  (the production loader)

import assemble_zoom_cap as A  # noqa: E402
import config  # noqa: E402

FREE_DATA = 0x5E34A3


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(config.terranx_bak(required=True)))


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def rel(pe, va):
    return (va + 5 + struct.unpack("<i", rd(pe, va + 1, 4))[0]) & 0xFFFFFFFF


@pytest.mark.parametrize("core,this_off,site,epi", A.CORES)
def test_reject_block_is_only_reached_over_the_cap(pe, core, this_off, site, epi):
    """f stored to 0x9B6624, compared with qword 4.0, `test ah,0x41; jne accept` (accept below AND equal), then the
    17-byte reject: push 1; mov ecx,[ebp+8]; call Buffer_free_data; xor eax,eax; jmp epilogue."""
    assert rd(pe, site - 0x1A, 0x15) == bytes.fromhex(
        "9B 00 D9 05 24 66 9B 00 DC 1D C8 FD 66 00 DF E0 F6 C4 41 75 11")
    assert rd(pe, site - 5, 5) == bytes.fromhex("6A 01 8B 4D 08")
    assert rd(pe, site, 1) == b"\xE8" and rel(pe, site) == FREE_DATA
    assert rd(pe, site + 5, 3) == bytes.fromhex("33 C0 E9") and rel(pe, site + 7) == epi
    assert struct.unpack("<d", rd(pe, 0x66FDC8, 8))[0] == 4.0


@pytest.mark.parametrize("core,this_off,site,epi", A.CORES)
def test_the_return_address_names_the_core(pe, core, this_off, site, epi):
    """t_zc_reject decodes the core from the reject call's return address: ret - 0x89 for the six cores whose Sprite
    lives at [ebp-0x5C]; ret - 0x102 (mono) and the keyed core (ret >= 0x5E4B9A) for the two at [ebp-0x64]."""
    ret = site + 5
    assert rd(pe, core, 9) == bytes.fromhex("55 8B EC 83 EC") + bytes([this_off]) + bytes.fromhex("53 56 57")[:3]\
        or rd(pe, core, 6) == bytes.fromhex("55 8B EC 83 EC") + bytes([this_off])
    assert rd(pe, core + 9, 3) == bytes.fromhex("89 4D") + bytes([0x100 - this_off])           # mov [ebp-off], ecx
    if this_off == 0x5C:
        assert ret >= A.DEST_CORE and ret - 0x89 == core
    elif core == A.KEYED_CORE:
        assert A.KEYED_CORE <= ret < A.DEST_CORE
    else:
        assert ret < A.KEYED_CORE and ret - 0x102 == core
    # the epilogue is the core's own: pop edi/esi/ebx; mov esp,ebp; pop ebp; ret N
    assert rd(pe, epi, 6)[:3] == bytes.fromhex("5F 5E 5B")


def test_core_returns(pe):
    """RET imm per core (the 1:1 composite pushes 5 args and t_zc_rows resets esp from the row buffer, so a 4-arg
    core's RET 0x10 is fine)."""
    want = {0x5E3E50: 0x14, 0x5E4B9A: 0x10, 0x5E5833: 0x14, 0x5E66A2: 0x10, 0x5E741C: 0x14, 0x5E81BC: 0x14,
            0x5E8FF5: 0x14, 0x5E9D44: 0x14}
    for core, _, _, epi in A.CORES:
        tail = rd(pe, epi, 0x10)
        i = tail.find(b"\xC2")
        assert i >= 0 and struct.unpack("<H", tail[i + 1:i + 3])[0] == want[core], hex(core)


def test_keyed_core_prologue_replay(pe):
    """t_zc_sbc_native replays the keyed core's 6-byte prologue (the bytes the commlink_wrap detour displaces) and
    resumes at +6."""
    assert rd(pe, A.KEYED_CORE, 6) == bytes.fromhex("55 8B EC 83 EC 64")
    assert A.KEYED_BODY == A.KEYED_CORE + 6
    stub = A.assemble("t_zc_sbc_native")
    assert stub[:6] == bytes.fromhex("55 8B EC 83 EC 64") and stub[6] == 0xE9
    assert (A.va("t_zc_sbc_native") + 11 + struct.unpack("<i", stub[7:11])[0]) & 0xFFFFFFFF == A.KEYED_BODY


def test_rect_arithmetic_is_shared_by_every_core(pe):
    """Every core sizes its scaled rect the same way (H' = ftol(h*f), W' = ftol(w*f), T0 = ftol(y + offy*f),
    L0 = ftol(x + offx*f), f = float32 0x9B6624) -- the arithmetic t_zc_reject repeats."""
    from capstone import CS_ARCH_X86, CS_MODE_32, Cs
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    starts = [c[0] for c in A.CORES] + [0x5EAAFF]
    for k, (core, off, _, _) in enumerate(A.CORES):
        ins = list(md.disasm(rd(pe, core, starts[k + 1] - core), core))
        fields = []
        for i, x in enumerate(ins):
            if x.mnemonic == "fmul" and x.op_str == "dword ptr [0x9b6624]":
                fields.append(int(re.search(r"\+ (0x[0-9a-f]+)\]", ins[i - 1].op_str).group(1), 16))
                assert ins[i - 2].op_str.endswith(f"dword ptr [ebp - {off:#x}]")
        assert fields[:4] == [0x14, 0x10, 0x24, 0x20], hex(core)


@pytest.mark.parametrize("core", [c for c in (0x5E3E50, 0x5E4B9A, 0x5E5833, 0x5E741C, 0x5E8FF5)])
def test_drawing_cores_read_only_the_stack_sprite_fields(pe, core):
    """The composite Sprite carries +0 (no file name), +4, +0xC, +0x10, +0x14, +0x20, +0x24 -- every field a core
    reads from its Sprite (the other reads are calls in the scaled path only)."""
    from capstone import CS_ARCH_X86, CS_MODE_32, Cs
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    off = next(c[1] for c in A.CORES if c[0] == core)
    end = min(c[0] for c in A.CORES + [(0x5EAAFF, 0, 0, 0)] if c[0] > core)
    ins = list(md.disasm(rd(pe, core, end - core), core))
    seen = set()
    for i, x in enumerate(ins):
        if x.mnemonic == "mov" and x.op_str.endswith(f"dword ptr [ebp - {off:#x}]") and not x.op_str.startswith("dword"):
            reg = x.op_str.split(",")[0]
            for y in ins[i + 1:i + 4]:
                m = re.search(r"\[" + reg + r"(?: \+ (0x[0-9a-f]+|\d+))?\]", y.op_str)
                if m:
                    seen.add(int(m.group(1), 16) if m.group(1) and m.group(1).startswith("0x") else int(m.group(1) or 0))
                    break
                if y.mnemonic == "call":
                    break
    assert seen <= {0, 4, 0xC, 0x10, 0x14, 0x20, 0x24}


def test_lock_helpers(pe):
    """Buffer_get_data (thiscall, plain RET: software path sets +0x50 = +0x54 and counts +0x6C) and Buffer_free_data
    (RET 4: count -= n, <= 0 clears +0x50 / +0x6C) nest, so t_zc_tail's own lock spans the core's."""
    assert rd(pe, 0x5E3373, 0x1F) == bytes.fromhex(
        "83 EC 6C 56 8B F1 8B 4E 58 85 C9 75 16 8B 46 54 85 C0 89 46 50 74 5B 8B 4E 6C 41 89 4E 6C 5E")
    assert rd(pe, 0x5E3391, 5) == bytes.fromhex("5E 83 C4 6C C3")
    assert rd(pe, 0x5E34B0, 0x1D) == bytes.fromhex(
        "8B 44 24 0C 8B 4E 6C 2B C8 8B C1 89 4E 6C 3B C7 7F 34 89 7E 50 89 7E 6C 5F 5E C2 04 00")


def test_map_sprite_scale_setters(pe):
    """veh_draw, base_draw and MapWin_gen_terrain_poly set SCALE_NUM_G/DEN_G = (g_map_zoom_num, _den) when the
    num > 0, else (size + 16, 16) -- scaling_laws.map_sprite_scale."""
    assert rd(pe, 0x55971F, 0x2E) == bytes.fromhex(
        "A1 6C 1E 69 00 85 C0 7E 13 8B 0D 70 1E 69 00 A3 18 6D 69 00 89 0D 1C 6D 69 00 EB 13 83 C3 10 C7 05 1C 6D "
        "69 00 10 00 00 00 89 1D 18 6D 69")
    assert rd(pe, 0x55B15C, 0x2D) == bytes.fromhex(
        "A1 6C 1E 69 00 85 C0 7E 11 A3 18 6D 69 00 A1 70 1E 69 00 A3 1C 6D 69 00 EB 13 83 C1 10 C7 05 1C 6D 69 00 "
        "10 00 00 00 89 0D 18 6D 69 00")
    assert rd(pe, 0x464D38, 0x35) == bytes.fromhex(
        "A1 6C 1E 69 00 85 C0 89 4D 28 89 55 2C 7E 11 A3 18 6D 69 00 A1 70 1E 69 00 A3 1C 6D 69 00 EB 15 8B 45 10 "
        "C7 05 1C 6D 69 00 10 00 00 00 83 C0 10 A3 18 6D 69 00")


def test_yaml_wiring():
    doc = _yaml_load((ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8"))
    sites = {}
    for s in doc["sites"]:
        v = s["virtual_addr"]; v = int(v, 16) if isinstance(v, str) else v
        sites[v] = s
    for _, _, site, _ in A.CORES:
        s = sites[site]
        assert s["new_bytes"] == "E8 {rel32:t_zc_reject}" and s["group"] == "scale_ratio_uncache"
    # no other patch lands in a core's prologue except the keyed core's commlink_wrap (bypassed by the stub)
    for v, s in sites.items():
        for core, *_ in A.CORES:
            if core <= v < core + 6:
                assert core == A.KEYED_CORE and s["id"] == "Sprite_blit_scaled_core.commlink_wrap"
    cave = next(c for c in doc["code_caves"] if c["id"] == "pcave2")
    ids = {c["id"]: c for c in cave["contents"]}
    for n, _ in A.THUNKS:
        off = ids[n]["offset"]; off = int(off, 16) if isinstance(off, str) else off
        assert off == A.OFFS[n]
    A.spans()                                                  # inside the three reserved windows, no overlap
    assert A.WINDOWS == [(0x439A, 0x44B0), (0x4C17, 0x4D00), (0xC50B, 0xC600)]
