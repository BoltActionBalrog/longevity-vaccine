"""Static patch-integrity checks via the patcher's own verify seam.

These run against the pristine `.bak` and the live `patches.yaml`. They catch
the most likely self-inflicted regression: editing patches.yaml to add a new
modal fix and silently breaking an existing site anchor, cave packing, or
symbol reference. No game launch — pure byte/PE math, runs in well under a
second.
"""
from __future__ import annotations

import hashlib

import apply_patches as ap


def test_pristine_baseline(bak_bytes):
    """The .bak must be the exact binary patches.yaml is written against."""
    assert len(bak_bytes) == ap.EXPECTED_SIZE, "pristine .bak size mismatch"
    assert hashlib.md5(bak_bytes).hexdigest() == ap.EXPECTED_MD5, \
        "pristine .bak MD5 != expected base (2d0b1438) — wrong/altered backup"


def test_every_confirmed_site_verifies(loaded, pe_ctx):
    """Anchor + original_bytes of every confirmed site must match the PRACX base.

    The native DLL-loader group targets the pristine cc659f binary, not the
    PRACX base — its sites are verified separately (see test below)."""
    failures = []
    for s in loaded["sites"]:
        if s.get("status") != "confirmed":
            continue
        if s.get("group") == ap.NATIVE_LOADER_GROUP:
            continue
        ok, msg = ap.verify_site(s, pe_ctx["data"], pe_ctx["resolver"], loaded["s2v"])
        if not ok:
            failures.append(msg)
    assert not failures, "site verification failures:\n  " + "\n  ".join(failures)


def test_native_loader_sites_verify_pristine(loaded, pristine_pe_ctx):
    """The native DLL-loader group's sites must match the pristine cc659f binary
    (free _SELFMOD slot @0x668160, null _initterm slot @0x682000)."""
    failures = []
    for s in loaded["sites"]:
        if s.get("group") != ap.NATIVE_LOADER_GROUP or s.get("status") != "confirmed":
            continue
        ok, msg = ap.verify_site(s, pristine_pe_ctx["data"],
                                 pristine_pe_ctx["resolver"], loaded["s2v"])
        if not ok:
            failures.append(msg)
    assert not failures, "native loader site failures:\n  " + "\n  ".join(failures)


def test_every_cave_verifies(loaded, pe_ctx):
    """Each cave region is pure padding, contents resolve, fit, and don't overlap.

    (verify_cave also validates the _SELFMOD VirtualSize bump and the pcave2
    new-section append are possible.)
    """
    failures = []
    for c in loaded["caves"]:
        ok, msg = ap.verify_cave(c, pe_ctx["data"], pe_ctx["resolver"],
                                 pe_ctx["pe"], loaded["s2v"])
        if not ok:
            failures.append(msg)
    assert not failures, "cave verification failures:\n  " + "\n  ".join(failures)


def test_cave_contents_do_not_overlap(loaded):
    """Content entries within one cave must not overlap each other.

    Added 2026-07-04 after a real escape: thunk_popup_railhide's 10-byte prepend
    grew it past a stale ledger length into the g_popup_railsave content slot —
    the later zero-fill clobbered the thunk's tail and the game crashed on the
    first popup close (AV at pcave2+0x3631). Cave-vs-cave overlap was tested;
    content-vs-content within a cave was not.
    """
    failures = []
    for c in loaded["caves"]:
        spans = []
        content_ids = set()
        for ct in c.get("contents", []) or []:
            off = int(ct["offset"])
            ln = ap.ByteTemplate(ct["bytes"]).total_length
            spans.append((off, off + ln, ct["id"]))
            content_ids.add(ct["id"])
        # Symbol-only offsets are live DATA slots (globals/scratch written at
        # runtime); model them as spans — `size:` if the ledger declares one
        # (large scratch regions like g_bm_fx's 8KB map), else >=4 bytes — so
        # code can't be laid over them. A symbol is "the content entry itself"
        # only when the NAME matches a content id: the 2026-07-11 Quick Start
        # crash slipped through the old same-OFFSET dedup because a thunk was
        # allocated at exactly g_bm_fx's start, which hid the symbol entirely.
        for name, sym in loaded["symbols"].items():
            if not isinstance(sym, dict) or sym.get("cave") != c["id"]:
                continue
            off = sym.get("offset")
            if off is None or name in content_ids:
                continue
            size = int(sym.get("size", 4))
            spans.append((int(off), int(off) + size, f"sym:{name}"))
        spans.sort()
        for (a0, a1, an), (b0, b1, bn) in zip(spans, spans[1:]):
            if a1 > b0 and not (an.startswith("sym:") and bn.startswith("sym:")):
                failures.append(f"cave {c['id']}: {an} (0x{a0:x}-0x{a1:x}) overlaps "
                                f"{bn} (0x{b0:x}-0x{b1:x})")
        if spans and c.get("length") and spans[-1][1] > int(c["length"]):
            failures.append(f"cave {c['id']}: {spans[-1][2]} ends 0x{spans[-1][1]:x} "
                            f"past cave length 0x{int(c['length']):x}")
    assert not failures, "cave content overlaps:\n  " + "\n  ".join(failures)


def test_self_modifying_writes_land_on_an_operand(loaded):
    """A literal-address write from cave code INTO another cave thunk must hit a 4-byte imm/disp field.

    Added 2026-09-27 after a real escape: the Design Workshop picker bracket patched the rail gate's
    ProdPicker comparand at the literal `thunk_rail_gate+5`; rail_gate v4 moved that body and left a
    push/ret trampoline there, so the write landed on the trampoline's `ret` and every DW part picker
    crashed at g>16.  Content overlap cannot see this (a write target is not a span), so check each
    absolute-address memory write against the instruction boundaries of the thunk it lands in.
    Every content is code except the data hosts (`g_*`, `*_var`): the other self-modifying writers are
    `t_*` (t_dl_portrait / t_rwk_intel_portrait / t_dw_artL/R -> thunk_portrait_avg+5), and the same
    bug class already hit that field once (2026-08-31, assemble_dl.py PAVG_GATE_IMM)."""
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32, CS_AC_WRITE
    from capstone.x86 import X86_OP_MEM, X86_REG_INVALID
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    md.detail = True
    code = []   # (va0, va1, id, [insns])
    for c in loaded["caves"]:
        base = int(c["virtual_addr"])
        for ct in c.get("contents", []) or []:
            if ct["id"].startswith("g_") or ct["id"].endswith("_var"):
                continue
            va = base + int(ct["offset"])
            b = ap.ByteTemplate(ct["bytes"]).resolve(va, loaded["s2v"])
            code.append((va, va + len(b), ct["id"], list(md.disasm(b, va))))
    failures, n_checked = [], 0
    for _va0, _va1, wid, insns in code:
        for ins in insns:
            for op in ins.operands:
                if not (op.type == X86_OP_MEM and op.access & CS_AC_WRITE and op.mem.base == X86_REG_INVALID
                        and op.mem.index == X86_REG_INVALID):
                    continue
                tgt = op.mem.disp & 0xFFFFFFFF
                host = next((h for h in code if h[0] <= tgt < h[1]), None)
                if host is None:
                    continue
                n_checked += 1
                fields = set()
                for h in host[3]:
                    if h.imm_size == 4:
                        fields.add(h.address + h.imm_offset)
                    if h.disp_size == 4:
                        fields.add(h.address + h.disp_offset)
                if op.size != 4 or tgt not in fields:
                    failures.append(f"{wid} @0x{ins.address:x} `{ins.mnemonic} {ins.op_str}` writes into "
                                    f"{host[2]} at +0x{tgt - host[0]:x}, not onto a 4-byte operand field")
    assert not failures, "self-modifying writes off an operand:\n  " + "\n  ".join(failures)


def test_sized_data_cells_do_not_overlap(loaded):
    """No two SIZED data cells ({cave, offset, size} symbols) of one cave share a byte.

    test_cave_contents_do_not_overlap exempts symbol-vs-symbol pairs (aliases of one slot are legitimate when
    UNSIZED), so a cell that grew into its neighbour went unseen: the 2026-10-18 fix 9 split of g_rw_fontscratch
    (128 B) + g_rw_strip_rect (16 B at its old tail) survived a `size: 144` mutant.  A declared size is a claim
    of ownership; two claims on one byte are a bug whichever cell writes it."""
    cells: dict = {}
    for name, sym in loaded["symbols"].items():
        if isinstance(sym, dict) and sym.get("size") is not None and sym.get("offset") is not None:
            cells.setdefault(sym["cave"], []).append((int(sym["offset"]), int(sym["offset"]) + int(sym["size"]), name))
    assert sum(len(v) for v in cells.values()) >= 150, "the sized-cell census collapsed (parse change?)"
    failures = []
    for cave, spans in cells.items():
        spans.sort()
        end, owner = -1, None
        for a0, a1, an in spans:
            assert a1 > a0, f"cave {cave}: {an} has size <= 0"
            if a0 < end:
                failures.append(f"cave {cave}: {an} (0x{a0:x}-0x{a1:x}) overlaps {owner[0]} (..0x{owner[1]:x})")
            if a1 > end:
                end, owner = a1, (an, a1)
    assert not failures, "sized data cells overlap:\n  " + "\n  ".join(failures)


def test_caves_do_not_overlap(loaded):
    ranges = sorted((int(c["virtual_addr"]),
                     int(c["virtual_addr"]) + int(c["length"]),
                     c["id"]) for c in loaded["caves"])
    for (a0, a1, an), (b0, b1, bn) in zip(ranges, ranges[1:]):
        assert a1 <= b0, (f"caves {an} (0x{a0:x}-0x{a1:x}) and "
                          f"{bn} (0x{b0:x}-0x{b1:x}) overlap")


def test_ids_are_unique(loaded):
    """Site, group, cave and cave-content ids are unique.  The patcher keys sites by id
    (apply_patches site_by_id / site_ok dicts): a duplicate silently resolves a group
    member to whichever entry came LAST (Dialog_item.wrap_budget was two sites, a dead
    status-skip one and the live popup_type2_list_scale member, until fix 10)."""
    from collections import Counter
    for kind, ids in (("site", [s["id"] for s in loaded["sites"]]),
                      ("group", [g["id"] for g in loaded["groups"]]),
                      ("cave", [c["id"] for c in loaded["caves"]]),
                      ("cave content", [e["id"] for c in loaded["caves"]
                                        for e in (c.get("contents") or [])])):
        dup = sorted(k for k, n in Counter(ids).items() if n > 1)
        assert not dup, f"duplicate {kind} ids: {dup}"


def test_all_referenced_symbols_exist(loaded):
    """Every {rel32:NAME}/{abs32:NAME} placeholder resolves to a known symbol."""
    s2v = loaded["s2v"]
    missing = []
    for s in loaded["sites"]:
        for field in ("original_bytes", "new_bytes"):
            tmpl = s.get(field)
            if not tmpl:
                continue
            for name in ap.ByteTemplate(tmpl).referenced_symbols():
                if name not in s2v:
                    missing.append(f"site {s['id']}.{field} -> {name}")
    for c in loaded["caves"]:
        for ct in c.get("contents", []) or []:
            for name in ap.ByteTemplate(ct["bytes"]).referenced_symbols():
                if name not in s2v:
                    missing.append(f"cave {c['id']}/{ct['id']} -> {name}")
    assert not missing, "unknown symbols referenced:\n  " + "\n  ".join(missing)
