r"""gen_thinker_sites.py -- the run-time patch table uimod.dll applies under Thinker, generated from patches.yaml.

WHY: Thinker (thinker.dll, injected by thinker.exe) patches terranx.exe in memory before the game's first
instruction and verifies each of its own writes against the bytes it expects; a failed guard is exit_fail and the
game never starts. Four sites of ours would fail those guards, so the `pracx_thinker` target leaves them clean on
disk (`exclude_sites`) and uimod.dll writes them AFTER Thinker has run. Two more Thinker merely clobbers (its
write_call replaces our E8) and the user decided ours wins at one and BOTH at two others (our thunk chained into
Thinker's function). Every one of those is a recorded user decision (ACTION_ITEMS "THINKER", 2026-10-28).

This script reads the yaml (the one source of each site's bytes), Thinker's source (where inside each span
Thinker writes, and what), and the baked cave (the exact bytes of the two base-screen thunks and the cores they
jump to, found by disassembly), and emits `src\uimod\src\thinker_sites.h`. A test regenerates the header and
fails when the checked-in one is stale, so the DLL can never carry a private, drifting copy of the yaml.

    py work\scripts\gen_thinker_sites.py            # rewrite the header
    py work\scripts\gen_thinker_sites.py --check    # exit 1 if the header on disk differs
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import shutil
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_patches as ap  # noqa: E402
import config  # noqa: E402
import thinker_overlap as T  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "src" / "uimod" / "src" / "thinker_sites.h"
TARGET_ID = "pracx_thinker"

#: Sites Thinker CLOBBERS (our E8 passes its guard, its call then replaces ours in memory) where the decision is
#: OURS: the DLL writes our bytes back after Thinker. (decision 2, 2026-10-28)
RESTORE_SITES = ["SetupWin_draw_item.decoration_blit_redirect"]

#: Sites Thinker clobbers where the decision is BOTH: our call-redirect thunk runs first and then enters Thinker's
#: function instead of the engine's. site id -> the engine function the thunk chain finally enters (its "native",
#: the one call the trampoline re-points at Thinker's function). (decision 4, 2026-10-28)
CHAIN_SITES = {
    "bw2.setfont_40f8f8": "Buffer_set_font",
    "bw2.l3_415ad8": "Buffer_write_l_3",
}
#: Engine entry points the chain cores end in (assemble_basewin.py SET_FONT / WRITE_L_3).
NATIVE_VA = {"Buffer_set_font": 0x5DAC70, "Buffer_write_l_3": 0x5DCEA0}

WIN_CALL, WIN_SCIENT = 1, 2


def _quiet_load(path: Path):
    with contextlib.redirect_stdout(io.StringIO()):
        return ap.load_patches(path)


def _resolve(site: dict, key: str, s2v: dict) -> bytes:
    return ap.ByteTemplate(site[key]).resolve(int(site["virtual_addr"]), s2v)


def _thinker_windows(site: dict, thinker: dict, base: T.Image) -> list[dict]:
    """Where Thinker writes inside this site's span, in its order: (offset, length, kind, expected new byte)."""
    va, ln = int(site["virtual_addr"]), int(site["length"])
    known = T.forced_options(thinker.get("assigns", []), True)
    out = []
    for w in thinker["writes"]:
        if w.gating(True, known)[0] == "never":
            continue
        fp = T.footprint(w, base)
        if w.addr < va + ln and va < w.addr + fp:
            if w.kind == "write_call":
                kind, new = WIN_CALL, 0
            elif w.kind == "scient":
                kind, new = WIN_SCIENT, w.new[0]
            else:
                raise SystemExit(f"{site['id']}: Thinker write kind {w.kind!r} at {w.addr:#x} is not modelled; "
                                 f"extend gen_thinker_sites.py and thinkercompat.cpp together")
            text = w.text.strip() or f"Scient triple {w.old[0]:02X}->{w.new[0]:02X} (patchdata.h)"
            out.append({"off": w.addr - va, "len": fp, "kind": kind, "new": new, "text": text})
    return out


def _bake(bak: Path, yaml_path: Path, workdir: Path) -> bytes:
    """The PRACX bake (every group, the cave content these thunks live in). Same bytes in both targets."""
    dst = workdir / "terranx_bake.exe"
    shutil.copy2(bak, dst)
    spec = ap.load_targets(yaml_path)["pracx"]
    with contextlib.redirect_stdout(io.StringIO()):
        rc = ap.apply_patches(dst, yaml_path, do_apply=True, spec=spec)
    if rc != 0:
        raise SystemExit(f"apply_patches --apply on a copy of {bak} failed (rc {rc})")
    return dst.read_bytes()


def _disasm_extent(img: T.Image, va: int) -> tuple[int, list[dict]]:
    """Linear sweep from `va` to the first unconditional jmp/ret past every forward branch seen so far.
    Returns (length, rel32 fixups [{off, target, is_jmp}]) -- rel32 CALL/JMP/Jcc only; rel8 branches stay valid
    inside a contiguous copy and are not listed."""
    import capstone
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    cs.detail = True
    code = img.rd(va, 0x200)
    fix, far, pos = [], va, 0
    for ins in cs.disasm(code, va):
        pos = ins.address + ins.size - va
        uncond = ins.mnemonic in ("jmp", "ret")
        if ins.mnemonic in ("call", "jmp") or ins.mnemonic.startswith("j"):
            op = ins.operands[0] if ins.operands else None
            if op is not None and op.type == capstone.x86.X86_OP_IMM:
                tgt = op.imm
                if ins.size in (5, 6) and ins.bytes[0] in (0xE8, 0xE9, 0x0F):
                    fix.append({"off": ins.address + ins.size - 4 - va, "target": tgt, "is_jmp": ins.mnemonic != "call"})
                if ins.mnemonic != "call" and va <= tgt < va + 0x200:
                    far = max(far, tgt)
        if uncond and ins.address >= far:
            break
    else:
        raise SystemExit(f"no terminating jmp/ret within 0x200 bytes of {va:#x}")
    return pos, fix


def _chain(site: dict, native: str, s2v: dict, bake: T.Image) -> dict:
    """The call-redirect thunk at the site (`call core; jmp ext` or `mov edx,imm; jmp core`) and the core it jumps
    to, as one contiguous trampoline image: thunk minus its final jmp, then the core. Every rel32 keeps its
    absolute target except the ONE that enters the native engine function -- the DLL re-points that at Thinker's."""
    new_t = ap.ByteTemplate(site["new_bytes"])
    names = [p for k, p in new_t.segments if k == "rel32"]
    if len(names) != 1:
        raise SystemExit(f"{site['id']}: expected one rel32 thunk in new_bytes, got {names}")
    thunk_va = s2v[names[0]]
    t_len, t_fix = _disasm_extent(bake, thunk_va)
    if not t_fix or not t_fix[-1]["is_jmp"] or t_fix[-1]["off"] != t_len - 4:
        raise SystemExit(f"{site['id']}: thunk {names[0]} at {thunk_va:#x} does not end in `jmp core`")
    core_va = t_fix[-1]["target"]
    prelude_len = t_len - 5
    c_len, c_fix = _disasm_extent(bake, core_va)
    nat = NATIVE_VA[native]
    tails = [f for f in c_fix if f["target"] == nat]
    if len(tails) != 1:
        raise SystemExit(f"{site['id']}: core at {core_va:#x} must enter {native} exactly once, found {len(tails)}")
    # A rel32 that lands INSIDE the copied bytes would keep its absolute target and jump back into the original
    # cave, whose tail enters the ENGINE function -- Thinker's would be skipped on that path. Both cores branch
    # internally with rel8 only today; refuse the day one grows a rel32.
    for f in t_fix[:-1]:
        if thunk_va <= f["target"] < thunk_va + t_len:
            raise SystemExit(f"{site['id']}: thunk at {thunk_va:#x} branches inside itself with a rel32 at +{f['off']:#x}")
    for f in c_fix:
        if core_va <= f["target"] < core_va + c_len:
            raise SystemExit(f"{site['id']}: core at {core_va:#x} branches inside itself with a rel32 at +{f['off']:#x}")
    fixups = [{"off": f["off"], "target": f["target"]} for f in t_fix[:-1]]
    fixups += [{"off": prelude_len + f["off"], "target": f["target"]} for f in c_fix]
    return {"id": site["id"], "site_va": int(site["virtual_addr"]), "thunk": names[0], "thunk_va": thunk_va,
            "thunk_bytes": bake.rd(thunk_va, t_len), "prelude_len": prelude_len,
            "core_va": core_va, "core_bytes": bake.rd(core_va, c_len),
            "fixups": fixups, "tail_off": prelude_len + tails[0]["off"], "native": native, "native_va": nat}


def build(yaml_path: Path, bak: Path, thinker_src: Path) -> str:
    sites, groups, caves, symbols = _quiet_load(yaml_path)
    s2v = ap.build_symbol_table(symbols, caves)
    by_id = {s["id"]: s for s in sites}
    spec = ap.load_targets(yaml_path)[TARGET_ID]
    thinker = T.load_thinker(thinker_src)
    base = T.Image(bak)
    with tempfile.TemporaryDirectory(prefix="thinker_sites_") as td:
        raw = _bake(bak, yaml_path, Path(td))
        bake = T.Image(Path(td) / "terranx_bake.exe", raw)
        bake_md5 = hashlib.md5(raw).hexdigest()

    excluded = [by_id[i] for i in sorted(spec.exclude_sites)]
    restore = [by_id[i] for i in RESTORE_SITES]
    entries = []
    for mode, group in (("EXCLUDED", excluded), ("RESTORE", restore)):
        for s in group:
            wins = _thinker_windows(s, thinker, base)
            if not wins:
                raise SystemExit(f"{s['id']}: Thinker writes nothing inside it; it should not be in this table")
            entries.append({"id": s["id"], "mode": mode, "va": int(s["virtual_addr"]), "len": int(s["length"]),
                            "clean": _resolve(s, "original_bytes", s2v), "ours": _resolve(s, "new_bytes", s2v),
                            "windows": wins})
    chains = [_chain(by_id[i], n, s2v, bake) for i, n in CHAIN_SITES.items()]
    return render(entries, chains, spec, bake_md5, thinker)


def _hex(b: bytes, per_line: int = 16, indent: str = "    ") -> str:
    lines = []
    for i in range(0, len(b), per_line):
        lines.append(indent + ", ".join(f"0x{x:02X}" for x in b[i:i + per_line]) + ",")
    return "\n".join(lines)


def _cname(sid: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in sid)


def render(entries: list, chains: list, spec, bake_md5: str, thinker: dict) -> str:
    o = []
    w = o.append
    w("// thinker_sites.h -- GENERATED by work\\scripts\\gen_thinker_sites.py from work\\patches\\patches.yaml")
    w(f"// (target {spec.id}, pracx bake {bake_md5}, Thinker write surface: {thinker['counts'].get('write_call')} write_call /")
    w(f"// {thinker['counts'].get('scient')} Scient triples). DO NOT EDIT: tests/test_thinker_sites_header.py regenerates it")
    w("// and fails when this file differs. The decisions behind every entry: ACTION_ITEMS.md \"THINKER\" (user, 2026-10-28).")
    w("#pragma once")
    w("#include <cstdint>")
    w("")
    w("namespace thinker_sites {")
    w("")
    w("// Where Thinker writes inside a site's span. kCall: a write_call -> E8 + rel32 whose target lies inside")
    w("// thinker.dll. kScient: one of Scient's byte triples -> the byte is either the clean value or `scient_new`.")
    w("enum WindowKind : uint8_t { kCall = 1, kScient = 2 };")
    w("struct Window { uint32_t off; uint32_t len; WindowKind kind; uint8_t scient_new; };")
    w("")
    w("// kExcluded: left CLEAN on disk by the patcher under Thinker (Thinker's guard would reject our bytes); every byte")
    w("//   outside the windows must still read as the clean base, then the DLL writes `ours`. Also applied when Thinker is")
    w("//   NOT loaded (terranx.exe started directly in a Thinker folder): the rest of the group is on disk and assumes it.")
    w("// kRestore: OUR bytes are on disk; Thinker's write_call replaces our E8's rel32; the DLL writes `ours` back.")
    w("enum SiteMode : uint8_t { kExcluded = 1, kRestore = 2 };")
    w("struct Site {")
    w("    const char* id;")
    w("    uint32_t va;")
    w("    uint32_t len;")
    w("    const uint8_t* clean;     // the clean base's bytes (resolved original_bytes)")
    w("    const uint8_t* ours;      // what the patcher would have written (resolved new_bytes)")
    w("    const Window* windows;")
    w("    uint32_t nwindows;")
    w("    SiteMode mode;")
    w("};")
    w("")
    w("// A call-redirect site where the decision is BOTH ours and Thinker's: our thunk (`thunk_bytes` at thunk_va, a")
    w("// `call core; jmp ext` / `mov edx,imm; jmp core` stub) and the core it jumps to are copied into one trampoline")
    w("// (thunk minus its final jmp, then the core); every rel32 keeps its absolute target except the one at `tail_off`,")
    w("// which entered the engine function `native_va` and now enters Thinker's function (read from the E8 Thinker left")
    w("// at the site). The site's E8 is then re-pointed at the trampoline.")
    w("struct Fixup { uint32_t off; uint32_t target; };")
    w("struct Chain {")
    w("    const char* id;")
    w("    uint32_t site_va;")
    w("    uint32_t thunk_va;")
    w("    const uint8_t* thunk_bytes;")
    w("    uint32_t thunk_len;")
    w("    uint32_t prelude_len;     // thunk bytes copied (all but its final 5-byte jmp)")
    w("    uint32_t core_va;")
    w("    const uint8_t* core_bytes;")
    w("    uint32_t core_len;")
    w("    const Fixup* fixups;      // offsets into the trampoline image (prelude + core)")
    w("    uint32_t nfixups;")
    w("    uint32_t tail_off;        // the fixup that enters native_va -> Thinker's function")
    w("    uint32_t native_va;")
    w("};")
    w("")
    for e in entries:
        n = _cname(e["id"])
        w(f"// {e['id']} @ {e['va']:#010x} ({e['len']} bytes, {e['mode'].lower()}); Thinker writes:")
        for win in e["windows"]:
            w(f"//   +{win['off']:#x} len {win['len']}: {win['text']}")
        w(f"static const uint8_t k_{n}_clean[{e['len']}] = {{")
        w(_hex(e["clean"]))
        w("};")
        w(f"static const uint8_t k_{n}_ours[{e['len']}] = {{")
        w(_hex(e["ours"]))
        w("};")
        w(f"static const Window k_{n}_win[{len(e['windows'])}] = {{")
        for win in e["windows"]:
            kind = "kCall" if win["kind"] == WIN_CALL else "kScient"
            w(f"    {{ {win['off']:#x}, {win['len']}, {kind}, 0x{win['new']:02X} }},")
        w("};")
        w("")
    w(f"static const Site kSites[{len(entries)}] = {{")
    for e in entries:
        n = _cname(e["id"])
        mode = "kExcluded" if e["mode"] == "EXCLUDED" else "kRestore"
        w(f"    {{ \"{e['id']}\", {e['va']:#010x}, {e['len']}, k_{n}_clean, k_{n}_ours, k_{n}_win, {len(e['windows'])}, {mode} }},")
    w("};")
    w(f"static const uint32_t kNumSites = {len(entries)};")
    w("")
    for c in chains:
        n = _cname(c["id"])
        w(f"// {c['id']} @ {c['site_va']:#010x}: {c['thunk']} @ {c['thunk_va']:#010x} -> core @ {c['core_va']:#010x} -> {c['native']} @ {c['native_va']:#010x}")
        w(f"static const uint8_t k_{n}_thunk[{len(c['thunk_bytes'])}] = {{")
        w(_hex(c["thunk_bytes"]))
        w("};")
        w(f"static const uint8_t k_{n}_core[{len(c['core_bytes'])}] = {{")
        w(_hex(c["core_bytes"]))
        w("};")
        w(f"static const Fixup k_{n}_fix[{len(c['fixups'])}] = {{")
        for f in c["fixups"]:
            w(f"    {{ {f['off']:#x}, {f['target']:#010x} }},")
        w("};")
        w("")
    w(f"static const Chain kChains[{len(chains)}] = {{")
    for c in chains:
        n = _cname(c["id"])
        w(f"    {{ \"{c['id']}\", {c['site_va']:#010x}, {c['thunk_va']:#010x}, k_{n}_thunk, {len(c['thunk_bytes'])}, {c['prelude_len']}, "
          f"{c['core_va']:#010x}, k_{n}_core, {len(c['core_bytes'])}, k_{n}_fix, {len(c['fixups'])}, {c['tail_off']:#x}, {c['native_va']:#010x} }},")
    w("};")
    w(f"static const uint32_t kNumChains = {len(chains)};")
    w("")
    w("} // namespace thinker_sites")
    return "\n".join(o) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--yaml", type=Path, default=Path(ap.DEFAULT_PATCHES))
    p.add_argument("--bak", type=Path, default=None, help="the clean PRACX base (default: the configured .bak)")
    p.add_argument("--thinker-src", type=Path, default=T.THINKER_SRC)
    p.add_argument("--out", type=Path, default=HEADER)
    p.add_argument("--check", action="store_true", help="compare with --out instead of writing; exit 1 on drift")
    a = p.parse_args(argv)
    bak = a.bak or config.terranx_bak()
    text = build(a.yaml, bak, a.thinker_src)
    if a.check:
        cur = a.out.read_text(encoding="utf-8") if a.out.exists() else ""
        if cur != text:
            print(f"{a.out} is STALE: regenerate with  py {Path(__file__).name}")
            return 1
        print(f"{a.out} is current")
        return 0
    a.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {a.out} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
