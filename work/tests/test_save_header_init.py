"""Group save_header_init: game_data (0x5A6AC0) must save a zeroed header with version 12, and a SAVE must never
take the legacy-load branch, whatever the stack held.

The engine's own prologue bytes are emulated (Unicorn) from both base exes with the group's site + thunk applied
exactly as patches.yaml states them; fwrite / fread are stubbed at their call targets.  The unpatched control
reproduces the original bug (stack residue 0 in the version slot -> a save runs the legacy branch)."""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest
import yaml
from apply_patches import _yaml_load  # the production loader (libyaml)

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config  # noqa: E402

from keystone import KS_ARCH_X86, KS_MODE_32, Ks  # noqa: E402
from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_EDI, UC_X86_REG_EFLAGS,  # noqa: E402
                               UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

GAME_DATA = 0x5A6AC0
SITE = 0x5A6AEB
FWRITE, FREAD = 0x64603F, 0x646178
MODERN, LEGACY = 0x5A6C11, 0x5A6B21          # `cmp dword [ebp-0x70], 0xB; jge` taken / fallen through
FAIL = 0x5A79EF                              # the header fwrite / fread returned 0
HDR = 0x31C
VERSION_OFS = 0x304
STACK_TOP = 0x1AB000
RET_SENTINEL = 0x00700000
FP = 0x02EC0000
BASES = ["terranx_PRACX.exe.bak", "terranx_vanilla.exe.bak"]   # the two bases the group is applied to

ASM = """
    pop edx
    pushfd
    push edi
    cld
    lea edi, [ebp - 0x374]
    mov ecx, 0xC7
    xor eax, eax
    rep stosd
    pop edi
    mov dword ptr [ebp - 0x70], 0xC
    popfd
    push 0x31C
    jmp edx
"""


@pytest.fixture(scope="module")
def spec():
    doc = _yaml_load((ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8"))
    cave = next(c for c in doc["code_caves"] if c["id"] == "menu_strip_thunks")
    thunk = next(t for t in cave["contents"] if t["id"] == "thunk_save_header_init")
    site = next(p for p in doc["sites"] if p["id"] == "game_data.header_init")
    sym = doc["symbols"]["thunk_save_header_init"]
    group = next(g for g in doc["groups"] if g["id"] == "save_header_init")
    return {"cave": cave, "thunk": thunk, "site": site, "sym": sym, "group": group, "doc": doc}


@pytest.fixture(params=BASES)
def base(request):
    return request.param


def thunk_va(spec):
    return spec["cave"]["virtual_addr"] + spec["thunk"]["offset"]


def test_yaml_is_consistent(spec):
    assert spec["sym"] == {"cave": "menu_strip_thunks", "offset": spec["thunk"]["offset"]}
    assert spec["group"]["members"] == ["game_data.header_init"] and not spec["group"].get("skippable")
    s = spec["site"]
    assert s["virtual_addr"] == SITE and s["length"] == 5 and s["original_bytes"] == "68 1C 03 00 00"
    assert s["new_bytes"] == "E8 {rel32:thunk_save_header_init}" and s["group"] == "save_header_init"
    assert "save_header_init" in spec["doc"]["targets"]["vanilla"]["groups"]
    import apply_patches
    assert "save_header_init" in apply_patches.PRISTINE_GROUPS


def test_thunk_bytes_are_the_assembled_source(spec):
    enc, _ = Ks(KS_ARCH_X86, KS_MODE_32).asm(ASM, thunk_va(spec))
    assert bytes(enc) == bytes.fromhex(spec["thunk"]["bytes"].replace(" ", ""))
    assert len(enc) == 35


def test_thunk_does_not_overlap_its_neighbours(spec):
    lo, hi = spec["thunk"]["offset"], spec["thunk"]["offset"] + 35
    assert hi <= spec["cave"]["length"]
    for t in spec["cave"]["contents"]:
        if t["id"] == "thunk_save_header_init":
            continue
        n = sum(4 if tok.startswith("{") else 1 for tok in t["bytes"].split())   # {rel32:x} / {abs32:x} = 4 bytes
        assert t["offset"] + n <= lo or t["offset"] >= hi, t["id"]


def exe_bytes(base):
    game = config.game_dir(required=False)
    if not game or not (game / base).exists():
        pytest.skip(f"{base} not available")
    exe = (game / base).read_bytes()
    if exe[SITE - 0x400000:SITE - 0x400000 + 5] != bytes.fromhex("681C030000"):
        pytest.skip(f"{base} is not an unpatched base")
    return exe


def test_the_cave_slot_is_padding_in_the_base(spec, base):
    exe = exe_bytes(base)
    off = thunk_va(spec) - 0x400000                                # _SELFMOD: raw offset == RVA in both bases
    assert set(exe[off:off + 35]) <= set(spec["cave"]["expected_padding"])


def run(spec, base, patched: bool, write: bool, residue_version: int, file_header: bytes = b"", io_ok: bool = True,
        df: int = 0):
    """Emulate game_data from its entry to the branch after `cmp [ebp-0x70], 0xB` (or to its failure exit).
    Returns what happened, incl. a snapshot of the live stack outside the header and of the globals page."""
    exe = exe_bytes(base)
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    uc.mem_map(0x5A6000, 0x2000)
    uc.mem_write(0x5A6000, exe[0x1A6000:0x1A8000])                 # .text: file offset = VA - 0x400000
    uc.mem_map(0x646000, 0x1000)
    uc.mem_write(0x646000, b"\x90" * 0x1000)
    uc.mem_map(0x668000, 0x1000)
    uc.mem_map(0x945000, 0x1000)                                   # the three globals the prologue stores
    uc.mem_map(RET_SENTINEL, 0x1000)
    uc.mem_map(STACK_TOP - 0x10000, 0x10000)
    if patched:
        va = thunk_va(spec)
        uc.mem_write(va, bytes.fromhex(spec["thunk"]["bytes"].replace(" ", "")))
        uc.mem_write(SITE, b"\xE8" + struct.pack("<i", va - (SITE + 5)))
    esp = STACK_TOP - 0x400
    ebp = esp - 4                                                  # after push ebp; mov ebp, esp
    local = ebp - 0x374
    # recognisable residue over the whole frame and well beyond it on both sides
    junk = b"".join(struct.pack("<I", 0x774C0000 + i) for i in range(0x800 // 4))
    uc.mem_write(local - 0x200, junk)
    uc.mem_write(local + VERSION_OFS, struct.pack("<i", residue_version))
    uc.mem_write(esp, struct.pack("<3I", RET_SENTINEL, FP, 1 if write else 0))
    for r, v in ((UC_X86_REG_ESP, esp), (UC_X86_REG_EBP, 0x1AAAD0), (UC_X86_REG_EBX, 0x11111111),
                 (UC_X86_REG_ESI, 0x22222222), (UC_X86_REG_EDI, 0x33333333), (UC_X86_REG_EFLAGS, 0x202 | (df << 10))):
        uc.reg_write(r, v)
    out = {"local": local, "calls": []}

    def hook(uc_, addr, size, _):
        if addr in (FWRITE, FREAD):
            sp = uc_.reg_read(UC_X86_REG_ESP)
            ret, buf, sz, cnt, fp = struct.unpack("<5I", uc_.mem_read(sp, 20))
            rec = {"fn": "fwrite" if addr == FWRITE else "fread", "buf": buf, "size": sz, "count": cnt, "fp": fp,
                   "ebx": uc_.reg_read(UC_X86_REG_EBX), "esi": uc_.reg_read(UC_X86_REG_ESI),
                   "edi": uc_.reg_read(UC_X86_REG_EDI), "esp": sp}
            if addr == FWRITE:
                rec["data"] = bytes(uc_.mem_read(buf, sz))
            elif io_ok:
                uc_.mem_write(buf, file_header)
            out["calls"].append(rec)
            uc_.reg_write(UC_X86_REG_EAX, 1 if io_ok else 0)       # fread / fwrite(size, 1): 1 or 0, never partial
            uc_.reg_write(UC_X86_REG_ESP, sp + 4)
            uc_.reg_write(UC_X86_REG_EIP, ret)
        elif addr in (MODERN, LEGACY, FAIL):
            out["branch"] = {MODERN: "modern", LEGACY: "legacy", FAIL: "fail"}[addr]
            out["esp_at_branch"] = uc_.reg_read(UC_X86_REG_ESP)
            out["edi_at_branch"] = uc_.reg_read(UC_X86_REG_EDI)
            out["df"] = (uc_.reg_read(UC_X86_REG_EFLAGS) >> 10) & 1
            uc_.emu_stop()

    uc.hook_add(UC_HOOK_CODE, hook)
    uc.emu_start(GAME_DATA, 0, count=3000)
    out["header_local"] = bytes(uc.mem_read(local, HDR))
    out["esp_expected"] = esp - 4 - 0x374 - 12                     # ebp, the local, ebx / esi / edi
    # everything still LIVE on the stack (at or above the final esp) outside the header, and the globals page
    lo = out["esp_at_branch"]
    out["live_outside"] = bytes(uc.mem_read(lo, local - lo)) + bytes(uc.mem_read(local + HDR, STACK_TOP - (local + HDR)))
    out["globals"] = bytes(uc.mem_read(0x945000, 0x1000))
    return out


@pytest.mark.parametrize("residue", [0, -1, 10, 7, 11, 0x02FE0000, -0x7FF00000])
def test_a_save_writes_a_clean_header_and_stays_on_the_modern_path(spec, base, residue):
    r = run(spec, base, patched=True, write=True, residue_version=residue)
    (call,) = r["calls"]
    assert call["fn"] == "fwrite" and (call["buf"], call["size"], call["count"], call["fp"]) == (r["local"], HDR, 1, FP)
    want = bytearray(HDR)
    want[VERSION_OFS:VERSION_OFS + 4] = struct.pack("<i", 12)
    assert call["data"] == bytes(want)                             # no stack residue reaches the file
    assert r["branch"] == "modern"
    assert (call["ebx"], call["esi"], call["edi"]) == (FP, 1, 0)   # the prologue's own values, untouched
    assert r["esp_at_branch"] == r["esp_expected"] and r["edi_at_branch"] == 0 and r["df"] == 0


@pytest.mark.parametrize("file_version,branch", [(12, "modern"), (11, "modern"), (10, "legacy"), (6, "legacy"), (0, "legacy")])
@pytest.mark.parametrize("residue", [0, 12, -1])
def test_a_load_still_follows_the_files_version(spec, base, file_version, branch, residue):
    """Shipped scenarios are versions 6..10: the read path must keep taking the legacy branch for them."""
    header = bytearray(b"\x5A" * HDR)
    header[VERSION_OFS:VERSION_OFS + 4] = struct.pack("<i", file_version)
    r = run(spec, base, patched=True, write=False, residue_version=residue, file_header=bytes(header))
    (call,) = r["calls"]
    assert call["fn"] == "fread" and (call["buf"], call["size"], call["count"], call["fp"]) == (r["local"], HDR, 1, FP)
    assert r["header_local"] == bytes(header) and r["branch"] == branch
    assert r["esp_at_branch"] == r["esp_expected"]


@pytest.mark.parametrize("write", [True, False])
@pytest.mark.parametrize("df", [0, 1])
def test_patched_and_original_agree_except_for_the_header(spec, base, write, df):
    """Same calls, same stack depth, same registers at the call, same direction flag, and not one live byte
    outside the 0x31C header differs: saved registers, the other locals, the caller's frame, the globals."""
    header = bytes(HDR)[:VERSION_OFS] + struct.pack("<i", 12) + bytes(HDR - VERSION_OFS - 4)
    a = run(spec, base, patched=False, write=write, residue_version=0x02FE0000, file_header=header, df=df)
    b = run(spec, base, patched=True, write=write, residue_version=0x02FE0000, file_header=header, df=df)
    keys = ("fn", "buf", "size", "count", "fp", "ebx", "esi", "edi", "esp")
    assert [{k: c[k] for k in keys} for c in a["calls"]] == [{k: c[k] for k in keys} for c in b["calls"]]
    assert a["branch"] == b["branch"] == "modern" and a["esp_at_branch"] == b["esp_at_branch"]
    assert a["df"] == b["df"] == df
    assert a["live_outside"] == b["live_outside"] and a["globals"] == b["globals"]


@pytest.mark.parametrize("write", [True, False])
def test_a_failed_header_io_still_fails(spec, base, write):
    """fwrite / fread of the header returning 0 leaves through the failure exit, as before."""
    a = run(spec, base, patched=False, write=write, residue_version=0, io_ok=False)
    b = run(spec, base, patched=True, write=write, residue_version=0, io_ok=False)
    assert a["branch"] == b["branch"] == "fail" and a["esp_at_branch"] == b["esp_at_branch"]
    assert a["live_outside"] == b["live_outside"] and a["globals"] == b["globals"]


def test_the_original_code_has_the_bug(spec, base):
    """Control: unpatched, residue 0 on the version slot (the 2026-10-03 crash) -> the SAVE runs the legacy branch
    and the file gets the stack residue."""
    r = run(spec, base, patched=False, write=True, residue_version=0)
    (call,) = r["calls"]
    assert r["branch"] == "legacy" and call["data"][:4] != bytes(4)
