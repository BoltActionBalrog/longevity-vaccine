"""hook_tech_proto.js v2 hand-assembled stubs (STUBS-BEGIN..STUBS-END block) — the
byte builder is pure JS; this test runs it under node for several g and checks the
emitted bytes against a capstone decode of the INTENDED instruction list
and a capstone walk (every jne lands on an entry boundary, every jmp on its absolute
target).  A wrong encoding here is a crash the user would take in-game."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
HOOK = HERE.parent / "scripts" / "hook_tech_proto.js"
sys.path.insert(0, str(HERE.parent / "scripts"))
import scaling_laws as SL  # noqa: E402

capstone = pytest.importorskip("capstone")
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")

BASE = 0x10000000
CONSTS = dict(fontInit=0x618F40, findFont=0x5882F0, devfill=0xA0C000 + 0x42A0, rbRect=0x0A1B0010)
FI = [[14, 0, 33], [14, 1, 34], [14, 2, 33], [18, 1, 44], [10, 0, 24], [10, 1, 25], [10, 2, 24], [12, 1, 29]]
FF = [[20, 1, 0x0A1B2C30], [20, 2, 0x0A1B2C58], [18, 1, 0x0A1B2C80], [18, 2, 0x0A1B2CA8], [12, 1, 0x0A1B2CD0], [12, 2, 0x0A1B2CF8]]


def build_js(g):
    src = HOOK.read_text(encoding="utf-8")
    m = re.search(r"// STUBS-BEGIN.*?\n(.*?)// STUBS-END", src, re.S)
    assert m, "STUBS-BEGIN/END block missing in hook_tech_proto.js"
    c = dict(CONSTS, cRb=SL.tech_cell_inset_rb(g), cL=SL.scale_px(3, g), fi=FI, ff=FF)
    script = m.group(1) + "\nconst r = globalThis.TechStubs.build(%d, %s);\nconsole.log(JSON.stringify(r));\n" % (BASE, json.dumps(c))
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    r = json.loads(out.stdout.strip().splitlines()[-1])
    return bytes(b & 0xFF for b in r["bytes"]), r["off"], c


def expected_text(c):
    """The instruction text (capstone mnemonic + operands) each stub must decode to.
    Branch targets are checked structurally in test_stub_control_flow_walk."""
    h = lambda v: f"{v:#x}" if v >= 10 else str(v)  # noqa: E731  capstone prints >=10 as hex
    inset = [("sub", f"ebx, {h(c['cRb'])}"), ("sub", f"edx, {h(c['cRb'])}"), ("mov", f"eax, {h(c['cL'])}"),
             ("cmp", "ecx, eax"), ("ret", "")]
    n8 = [("mov", "esi, 0xa"), ("mov", "dword ptr [ebp + 8], 0xc"), ("ret", "")]
    fi = []
    for S, f, N in c["fi"]:
        fi += [("cmp", f"dword ptr [esp + 8], {h(S)}"), ("jne", None), ("cmp", f"dword ptr [esp + 0xc], {h(f)}"), ("jne", None),
               ("mov", f"dword ptr [esp + 8], {h(N)}"), ("jmp", h(c["fontInit"]))]
    fi.append(("jmp", h(c["fontInit"])))
    ff = []
    for S, v, p in c["ff"]:
        ff += [("cmp", f"dword ptr [esp + 4], {h(S)}"), ("jne", None), ("cmp", f"dword ptr [esp + 8], {h(v)}"), ("jne", None),
               ("mov", f"eax, {h(p)}"), ("ret", "")]
    ff.append(("jmp", h(c["findFont"])))
    r = c["rbRect"]
    exact = [("push", "eax"), ("push", "edx"), ("mov", "edx, dword ptr [esp + 0xc]"),
             ("mov", "eax, dword ptr [edx]"), ("mov", f"dword ptr [{h(r)}], eax"),
             ("mov", "eax, dword ptr [edx + 4]"), ("mov", f"dword ptr [{h(r + 4)}], eax"),
             ("mov", "eax, dword ptr [edx + 8]"), ("dec", "eax"), ("mov", f"dword ptr [{h(r + 8)}], eax"),
             ("mov", "eax, dword ptr [edx + 0xc]"), ("dec", "eax"), ("mov", f"dword ptr [{h(r + 12)}], eax"),
             ("mov", f"dword ptr [esp + 0xc], {h(r)}"), ("pop", "edx"), ("pop", "eax"), ("jmp", h(c["devfill"]))]
    return {"inset": inset, "n8": n8, "fi": fi, "ff": ff, "rb1": exact}


def decode(blob, addr):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return [i for i in md.disasm(blob, addr) if i.mnemonic != "int3"]


@pytest.mark.parametrize("g", [17, 22, 25, 30, 40])
def test_stub_bytes_decode_to_the_intended_instructions(g):
    blob, off, c = build_js(g)
    keys = ["inset", "n8", "fi", "ff", "rb1"]
    ends = {k: (off[keys[i + 1]] if i + 1 < len(keys) else len(blob)) for i, k in enumerate(keys)}
    want = expected_text(c)
    for k in keys:
        assert off[k] % 16 == 0
        seg = blob[off[k]:ends[k]].rstrip(b"\xCC")
        got = decode(seg, BASE + off[k])
        assert sum(i.size for i in got) == len(seg), f"stub_{k} @g={g}: undecodable tail"
        assert len(got) == len(want[k]), f"stub_{k} @g={g}: {len(got)} insns vs {len(want[k])}"
        for i, (mn, ops) in zip(got, want[k]):
            assert i.mnemonic == mn, f"stub_{k} @g={g} {i.address:#x}: {i.mnemonic} {i.op_str} != {mn} {ops}"
            if ops is not None:
                assert i.op_str == ops, f"stub_{k} @g={g} {i.address:#x}: {i.mnemonic} {i.op_str} != {mn} {ops}"


@pytest.mark.parametrize("g", [22, 40])
def test_stub_control_flow_walk(g):
    blob, off, c = build_js(g)
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    ins = decode(blob, BASE)
    by_addr = {i.address: i for i in ins}
    starts = set(by_addr)
    for i in ins:
        if i.mnemonic in ("jne", "jmp"):
            tgt = int(i.op_str, 16)
            if BASE <= tgt < BASE + len(blob):
                assert tgt in starts, f"{i.mnemonic} @{i.address:#x} lands mid-instruction {tgt:#x}"
            else:
                assert i.mnemonic == "jmp" and tgt in (c["fontInit"], c["findFont"], c["devfill"]), f"stray jmp to {tgt:#x}"
    # each fi/ff entry's two jne's land on the NEXT entry's cmp
    fi_ins = [i for i in ins if BASE + off["fi"] <= i.address < BASE + off["ff"]]
    jnes = [i for i in fi_ins if i.mnemonic == "jne"]
    cmps = [i.address for i in fi_ins if i.mnemonic == "cmp" and "esp + 8" in i.op_str]
    cmps.append([i for i in fi_ins if i.mnemonic == "jmp"][-1].address)   # default tail
    for k, j in enumerate(jnes):
        assert int(j.op_str, 16) == cmps[k // 2 + 1], f"fi jne #{k} target"
    # the inset stub ends in cmp ecx,eax ; ret (flags must reach the caller's jg)
    inset = [i for i in ins if BASE + off["inset"] <= i.address < BASE + off["n8"] and i.mnemonic != "int3"]
    assert [i.mnemonic for i in inset] == ["sub", "sub", "mov", "cmp", "ret"]
    h = lambda v: f"{v:#x}" if v >= 10 else str(v)  # noqa: E731
    assert inset[0].op_str == f"ebx, {h(SL.tech_cell_inset_rb(g))}" and inset[2].op_str == f"eax, {h(SL.scale_px(3, g))}"


def test_cut_sites_have_room_and_no_interior_branch_targets():
    """The two cut sites replace whole instructions; the disasm dumps must show no
    branch into the cut interiors (audited by hand 2026-08-28; pinned here)."""
    dumps = [HERE.parent / "_tech_dis_cell.txt", HERE.parent / "_tech_dis_exec.txt"]
    if not all(p.is_file() for p in dumps):
        # Disassembly dumps of the game binary: analysis scratch, regenerable with
        # run-disasm-range.bat, and not part of the public source export.
        pytest.skip("disassembly dumps work\\_tech_dis_*.txt not present (not in the public "
                    "source export); regenerate them with run-disasm-range.bat to run this check")
    d = (HERE.parent / "_tech_dis_cell.txt").read_text(encoding="utf-8", errors="replace")
    assert "0x0048646c: B8 03 00 00 00" in d and "0x00486471: 2B D8" in d and "0x00486473: 2B D0" in d \
        and "0x00486475: 3B C8" in d and "0x00486477:" in d
    assert not re.search(r"j\w+\s+0x48646[d-f]|j\w+\s+0x48647[0-6]", d)
    e = (HERE.parent / "_tech_dis_exec.txt").read_text(encoding="utf-8", errors="replace")
    assert "0x00487981: 8B F7" in e and "0x00487983: C7 45 08 0C 00 00 00" in e and "0x0048798a:" in e
    assert not re.search(r"j\w+\s+0x48798[2-9]", e)
