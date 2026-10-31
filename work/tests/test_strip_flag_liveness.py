"""Flag-liveness guard for the strip-content cuts (slice 2a).

THE LAW (discovered via the draw_queue.listx5 regression): vanilla code keeps
EFLAGS live across flag-neutral instructions — draw_queue's `MOV EAX,5` sits
between `CMP ScreenWidth,EBX` and its `JNZ`.  A cut thunk whose ORIGINAL
bytes are flag-neutral must therefore be flag-TRANSPARENT (pushfd/popfd), and
a cut whose original ENDS with a live comparison must REPRODUCE that final
flag-writer as its own last flag-writing instruction.

Three checks per cut:
  1. forward liveness scan of the pristine stream: no PRESERVE-class cut may
     use a flag-clobbering thunk without pushfd/popfd;
  2. neutral-original cuts: thunk contains pushfd+popfd and writes no flags
     after the last popfd;
  3. flag-writing originals whose flags reach a consumer: thunk's last
     flag-writer == original's last flag-writer (mnemonic + operands).

Skips (with a visible reason) if the pristine disasm dump is absent.
"""
import os
import re
import sys

import pytest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, SCRIPTS)

from assemble_strip_content import CUTS, assemble_all, PCAVE2_VA  # noqa: E402

from capstone import Cs, CS_ARCH_X86, CS_MODE_32  # noqa: E402

DISASM = os.path.join(os.path.dirname(__file__), "..",
                      "_tmp_disasm_strip_fns.txt")
# slice-2b chevron cuts live in BaseWin_init — its dump joins the stream so
# the forward-liveness scan actually covers them
DISASM_INIT = os.path.join(os.path.dirname(__file__), "..",
                           "_tmp_disasm_basewin_init.txt")

CONSUMER_PREFIX = ("set", "cmov")
CONSUMERS = {"ja", "jae", "jb", "jbe", "jc", "je", "jz", "jg", "jge", "jl",
             "jle", "jna", "jnae", "jnb", "jnbe", "jnc", "jne", "jng",
             "jnge", "jnl", "jnle", "jno", "jnp", "jns", "jnz", "jo", "jp",
             "jpe", "jpo", "js", "adc", "sbb", "rcl", "rcr", "cmc",
             "lahf", "pushf", "pushfd"}
NEUTRAL = {"mov", "lea", "push", "pop", "movzx", "movsx", "nop", "cdq",
           "jmp", "call", "ret", "xchg", "not", "cbw", "cwde",
           "pushfd", "popfd"}
WRITERS = {"add", "sub", "and", "or", "xor", "cmp", "test", "inc", "dec",
           "neg", "imul", "mul", "idiv", "div", "sar", "shr", "shl", "sal",
           "rol", "ror", "shld", "shrd", "bt", "bts", "btr", "btc", "bsf",
           "bsr", "sahf", "stc", "clc", "xadd"}


def classify(mn):
    mn = mn.lower()
    if mn.startswith(CONSUMER_PREFIX) or mn in CONSUMERS:
        return "consumer"
    if mn == "popfd":
        return "restore"
    if mn in WRITERS:
        return "writer"
    if mn in NEUTRAL:
        return "neutral"
    return "unknown"


@pytest.fixture(scope="module")
def stream():
    if not os.path.exists(DISASM):
        pytest.skip("pristine disasm dump _tmp_disasm_strip_fns.txt missing")
    insns = []
    for path in (DISASM, DISASM_INIT):
        if not os.path.exists(path):
            continue
        for ln in open(path, encoding="utf-8", errors="replace"):
            m = re.match(r"\s+([0-9a-f]{8})\s+([0-9A-F ]+?)\s{2,}(\S.*)", ln)
            if m:
                insns.append((int(m.group(1), 16),
                              bytes.fromhex(m.group(2).replace(" ", ""))))
    insns.sort(key=lambda t: t[0])
    return insns, {va: i for i, (va, b) in enumerate(insns)}


@pytest.fixture(scope="module")
def md():
    d = Cs(CS_ARCH_X86, CS_MODE_32)
    d.detail = False
    return d


@pytest.fixture(scope="module")
def layout():
    lay, _end = assemble_all()
    return lay


def last_flag_writer(md, code, va):
    last = None
    for i in md.disasm(bytes(code), va):
        if classify(i.mnemonic) == "writer":
            last = (i.mnemonic.lower(), i.op_str.replace(" ", ""))
    return last


def original_is_neutral(md, code, va):
    return last_flag_writer(md, code, va) is None


def forward_consumer(md, stream, start_va):
    """Scan forward from start_va: returns mnemonic if a flag consumer is
    reached before any flag writer, else None."""
    insns, idx = stream
    i = idx.get(start_va)
    steps = 0
    while i is not None and steps < 40:
        va, b = insns[i]
        dec = next(md.disasm(bytes(b), va), None)
        if dec is None:
            return None
        mn = dec.mnemonic.lower()
        c = classify(mn)
        if c == "consumer":
            return f"{mn} @{va:#x}"
        if c in ("writer", "restore") or mn in ("ret", "call"):
            return None
        if mn == "jmp":
            try:
                i = idx.get(int(dec.op_str, 16))
                steps += 1
                continue
            except ValueError:
                return None
        i += 1
        steps += 1
    return None


def thunk_is_flag_transparent(md, blob, va):
    """pushfd present, popfd present, and no flag writer after the LAST
    popfd (only neutral/push/ret/jmp allowed on the exit path)."""
    ins = list(md.disasm(bytes(blob), va))
    mns = [i.mnemonic.lower() for i in ins]
    if "pushfd" not in mns or "popfd" not in mns:
        return False
    last_pop = max(i for i, m in enumerate(mns) if m == "popfd")
    for i in ins[last_pop + 1:]:
        if classify(i.mnemonic) == "writer":
            return False
    return True


def test_neutral_original_cuts_have_transparent_thunks(stream, md, layout):
    bad = []
    for sid, va, ln_, orig_hex, thunk in CUTS:
        orig = bytes.fromhex(orig_hex.replace(" ", ""))
        if not original_is_neutral(md, orig, va):
            continue
        off, blob = layout[thunk]
        if not thunk_is_flag_transparent(md, blob, PCAVE2_VA + off):
            bad.append(f"{sid} ({thunk}): neutral original but thunk "
                       f"clobbers flags")
    assert not bad, "\n".join(bad)


def test_no_preserve_class_cut_left_uncovered(stream, md, layout):
    """The listx5 regression shape: neutral original + live consumer after
    the cut. Requires the thunk to be flag-transparent."""
    bad = []
    for sid, va, ln_, orig_hex, thunk in CUTS:
        orig = bytes.fromhex(orig_hex.replace(" ", ""))
        if not original_is_neutral(md, orig, va):
            continue
        consumer = forward_consumer(md, stream, va + ln_)
        if consumer is None:
            continue
        off, blob = layout[thunk]
        if not thunk_is_flag_transparent(md, blob, PCAVE2_VA + off):
            bad.append(f"{sid} ({thunk}): flags live into consumer "
                       f"{consumer} but thunk is not flag-transparent")
    assert not bad, "\n".join(bad)


def test_reproduce_class_cuts_end_with_same_flag_writer(stream, md, layout):
    """A cut whose original's final flags feed a consumer must have a thunk
    whose LAST flag-writer is the identical instruction."""
    bad = []
    for sid, va, ln_, orig_hex, thunk in CUTS:
        orig = bytes.fromhex(orig_hex.replace(" ", ""))
        ow = last_flag_writer(md, orig, va)
        if ow is None:
            continue
        consumer = forward_consumer(md, stream, va + ln_)
        if consumer is None:
            continue
        off, blob = layout[thunk]
        tw = last_flag_writer(md, blob, PCAVE2_VA + off)
        if tw != ow:
            bad.append(f"{sid} ({thunk}): original ends flags with "
                       f"{ow} (consumer {consumer}) but thunk ends with {tw}")
    assert not bad, "\n".join(bad)
