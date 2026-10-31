"""Differential: thunk_ksb_v2 (keyed-stretch-blit body v2) retry+guard contract.

2026-07-26h: Buffer_copy_3 can bail with ret!=0 BEFORE its StretchBlt (HDC /
surface acquisition failure; its fail path runs the restore hook but never
retries), and v1 blindly copied the stale shared scratch to the dest — the
garrison-arrow first-hover garble.  v2 must:

  * success (ret 0)      -> exactly one copy_3 call, then the keyed copy-out
                            (v1-equivalent flow);
  * fail once then ok    -> a second copy_3 call with the SAME args, then the
                            copy-out;
  * fail twice           -> NO copy-out (dest keeps last-good pixels);
and in every case: RET 0x2C, esi/ebp callee-saved, resize called once first.

Also pins the frozen 0x668670 entry: the menu_strip content entry must be the
6-byte push+ret trampoline to thunk_ksb_v2 (bandstripe bakes 0x668670 raw).

Bytes come from patches.yaml resolved with the real symbol table (yaml/spec
desync fails here; on-disk drift fails test_apply_md5).
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_ECX, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_ESP,
)

import apply_patches as ap  # noqa: E402
import yaml  # noqa: E402

DOC = ap._yaml_load(pathlib.Path(ap.DEFAULT_PATCHES).read_text(encoding="utf-8"))
SYMTAB = ap.build_symbol_table(DOC["symbols"], DOC["code_caves"])


def _content(cid):
    for cave in DOC["code_caves"]:
        for c in cave.get("contents", []) or []:
            if c["id"] == cid:
                base = cave["virtual_addr"]
                base = int(base, 16) if isinstance(base, str) else base
                off = c["offset"]
                off = int(off, 16) if isinstance(off, str) else off
                va = base + off
                return va, ap.ByteTemplate(c["bytes"]).resolve(va, SYMTAB)
    raise AssertionError(f"{cid} content entry not found")


KSB_V2_VA, KSB_V2 = _content("thunk_ksb_v2")
TRAM_VA, TRAM = _content("thunk_keyed_stretch_blit")

ENSURE_SCRATCH = SYMTAB["thunk_ensure_scratch"]
BUFFER_RESIZE = SYMTAB["Buffer_resize"]
BUFFER_COPY3 = SYMTAB["Buffer_copy_3"]
DRAW2_CLIPKEY = SYMTAB["thunk_draw2_clipkey"]

SCRATCH = 0x06AF0000            # fake scratch Buffer*
CALLER_RET = 0x00668710         # sentinel return (mapped with the trampoline page)
STACK = 0x00200000

# scripted copy_3 results live here: [count][r0][r1]...
CTL = 0x00300000

ARGS = (0x00654321, 0x00654A00, 0, 0, 12, 42, 0, 0, 30, 105, 0xFFFFFFFF)
#       srcBuf      destBuf    sX sY sW  sH dX dY  dW  dH   key


def _stub(uc, va, ret_imm, record_slot, ret_eax=0, ret_from_ctl=False):
    """Tiny stub: inc call-counter at CTL+record_slot, set eax, ret imm."""
    code = bytearray()
    code += bytes.fromhex("FF05") + struct.pack("<I", CTL + record_slot)  # inc dword [ctr]
    if ret_from_ctl:
        # eax = results[ctr-1]: mov eax,[ctr]; mov eax,[CTL+0x40+eax*4-4]
        code += bytes.fromhex("A1") + struct.pack("<I", CTL + record_slot)
        code += bytes.fromhex("8B0485") + struct.pack("<I", CTL + 0x40 - 4)
    else:
        code += bytes.fromhex("B8") + struct.pack("<I", ret_eax & 0xFFFFFFFF)
    if ret_imm:
        code += bytes.fromhex("C2") + struct.pack("<H", ret_imm)
    else:
        code += b"\xC3"
    uc.mem_write(va, bytes(code))


def _run(copy3_results):
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    for page in {KSB_V2_VA, TRAM_VA, ENSURE_SCRATCH, BUFFER_RESIZE, BUFFER_COPY3,
                 DRAW2_CLIPKEY, CALLER_RET}:
        try:
            uc.mem_map(page & ~0xFFF, 0x2000)
        except unicorn.UcError:
            pass
    uc.mem_map(STACK, 0x10000)
    uc.mem_map(CTL, 0x1000)
    uc.mem_write(KSB_V2_VA, KSB_V2)
    uc.mem_write(TRAM_VA, TRAM)
    uc.mem_write(CALLER_RET, b"\xF4")
    # ensure_scratch: counter@0, returns SCRATCH, plain ret
    _stub(uc, ENSURE_SCRATCH, 0, 0x00, ret_eax=SCRATCH)
    # Buffer_resize: counter@4, thiscall RET 8
    _stub(uc, BUFFER_RESIZE, 8, 0x04)
    # Buffer_copy_3: counter@8, scripted eax, thiscall RET 0x24 (9 stack args)
    _stub(uc, BUFFER_COPY3, 0x24, 0x08, ret_from_ctl=True)
    for i, r in enumerate(copy3_results):
        uc.mem_write(CTL + 0x40 + 4 * i, struct.pack("<I", r & 0xFFFFFFFF))
    # draw2_clipkey: counter@12, thiscall RET 0x18
    _stub(uc, DRAW2_CLIPKEY, 0x18, 0x0C)

    esp = STACK + 0x8000
    frame = struct.pack("<I", CALLER_RET) + b"".join(struct.pack("<I", a) for a in ARGS)
    uc.mem_write(esp, frame)
    uc.reg_write(UC_X86_REG_ESP, esp)
    uc.reg_write(UC_X86_REG_ESI, 0x51515151)
    uc.reg_write(UC_X86_REG_EBP, 0x52525252)
    try:
        uc.emu_start(TRAM_VA, 0, count=200)
    except unicorn.UcError:
        pass
    counters = struct.unpack("<4I", uc.mem_read(CTL, 16))
    return uc, esp, counters


def _common_asserts(uc, esp):
    assert uc.reg_read(UC_X86_REG_EIP) in (CALLER_RET, CALLER_RET + 1)
    assert uc.reg_read(UC_X86_REG_ESP) == esp + 4 + 0x2C     # RET 0x2C
    assert uc.reg_read(UC_X86_REG_ESI) == 0x51515151         # callee-saved
    assert uc.reg_read(UC_X86_REG_EBP) == 0x52525252


def test_trampoline_shape():
    # 6 real bytes: push imm32 thunk_ksb_v2; ret — entry VA frozen for baked callers
    assert TRAM[:1] == b"\x68"
    assert struct.unpack("<I", TRAM[1:5])[0] == KSB_V2_VA
    assert TRAM[5:6] == b"\xC3"
    assert len(TRAM) == 83 and TRAM[6:] == b"\x90" * 76 + b"\xC3"


def test_success_single_stretch():
    uc, esp, (n_scr, n_rsz, n_cp3, n_out) = _run([0])
    _common_asserts(uc, esp)
    assert (n_scr, n_rsz, n_cp3, n_out) == (1, 1, 1, 1)


def test_fail_then_success_retries_and_copies_out():
    uc, esp, (n_scr, n_rsz, n_cp3, n_out) = _run([7, 0])
    _common_asserts(uc, esp)
    assert (n_scr, n_rsz, n_cp3, n_out) == (1, 1, 2, 1)


def test_double_fail_skips_copyout():
    uc, esp, (n_scr, n_rsz, n_cp3, n_out) = _run([7, 7])
    _common_asserts(uc, esp)
    assert (n_scr, n_rsz, n_cp3, n_out) == (1, 1, 2, 0)
