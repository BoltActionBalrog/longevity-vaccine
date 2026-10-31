"""Structural validation of every hand-assembled code thunk.

Resolves each cave content with the *production* ByteTemplate resolver and
disassembles it (the same bytes the patcher writes). A code thunk must:
  - fully decode (capstone consumes every byte — no truncated/garbage tail), and
  - end in a control-transfer (ret/jmp/call/jcc) so it can't fall through into
    the next thunk's bytes.

Byte-exact correctness of the final output is locked separately by
test_apply_md5; this layer adds well-formedness + readable per-thunk failures.

Data globals are not code and are excluded from disassembly — they're already
fit/overlap-checked by verify_cave. A content is treated as data if its id starts
with `g_`, is `filelock_var`, or it carries an explicit `data: true` flag (used for
the calibration-loop scratch buffers / string that don't follow the `g_` naming).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

import apply_patches as ap

_MD = Cs(CS_ARCH_X86, CS_MODE_32)


def _is_data(content_id: str) -> bool:
    return content_id.startswith("g_") or content_id == "filelock_var"


def _is_control_transfer(mnemonic: str) -> bool:
    if mnemonic in ("ret", "retf", "retn", "iret", "iretd"):
        return True
    if mnemonic.startswith(("jmp", "call", "loop")):
        return True
    # conditional jumps: je, jne, jz, jnz, jg, jle, ja, jbe, js, jecxz, ...
    return mnemonic.startswith("j") and len(mnemonic) <= 5


def _collect_code_contents():
    """(cave_id, content_id, va, template) for every code thunk, at import time
    so each becomes its own parametrized test case."""
    try:
        _s, _g, caves, syms = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    except FileNotFoundError:
        return []
    s2v = ap.build_symbol_table(syms, caves)
    out = []
    for c in caves:
        va = int(c["virtual_addr"])
        for ct in c.get("contents", []) or []:
            if ct.get("data") or _is_data(ct["id"]):
                continue
            out.append(pytest.param(c["id"], ct["id"], va + int(ct["offset"]),
                                    ct["bytes"], s2v,
                                    id=f"{c['id']}/{ct['id']}"))
    return out


_CODE_CONTENTS = _collect_code_contents()


def test_thunks_were_found():
    if not _CODE_CONTENTS:
        pytest.skip("patches.yaml not found / no cave contents")
    assert len(_CODE_CONTENTS) > 0


@pytest.mark.parametrize("cave_id,cid,va,template,s2v", _CODE_CONTENTS)
def test_thunk_well_formed(cave_id, cid, va, template, s2v):
    resolved = ap.ByteTemplate(template).resolve(va, s2v)
    ins = list(_MD.disasm(bytes(resolved), va))
    assert ins, f"{cave_id}/{cid}: no instructions decoded"
    consumed = sum(i.size for i in ins)
    assert consumed == len(resolved), (
        f"{cave_id}/{cid}: capstone consumed {consumed}/{len(resolved)} bytes "
        f"— truncated instruction or garbage tail")
    last = ins[-1].mnemonic
    assert _is_control_transfer(last), (
        f"{cave_id}/{cid}: ends in {last!r}, not a control transfer "
        f"— thunk would fall through into the next cave content")
