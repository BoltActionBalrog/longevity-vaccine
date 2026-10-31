r"""Locate Thinker functions that carry no symbol by FINGERPRINT (decision 5, option 2: pinned detours in
thinker.dll 5.5 need combat_move, move_upkeep, non_ally_in_tile, stack_search, set_move_to, at_war, has_pact ...
none of which is a patch target, so thinker_symbols.py cannot name them).

Method: every E8 rel32 target inside .text is a function start (plus the symbol map's entries); a function's body
runs to the next start. Per function: size, callees (named where the symbol map knows them), immediates in the
exe's image range (engine globals / tables Thinker reads: Vehs/VehCount/Factions/...), `mov byte [reg+disp], imm8`
stores, and the std library calls it makes. Queries then match the source (refs\thinker\src\move.cpp, veh.cpp,
faction.cpp): e.g. set_move_to stores order 0x18 at VEH+0x11 and status_icon 'G' at VEH+0x2B; combat_move calls
mod_battle_fight (named) and set_move_to many times; at_war / has_pact touch Factions' diplo table
(0x96C9E0 + f*0x20CC + 0x18).

Usage:
  thinker_locate.py [--dll <thinker.dll>] [--map work\_thinker_symbols_5.5.json] [--dump <offset-hex>]
Prints the candidates per query; --dump prints a function's fingerprint.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import capstone
import pefile

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DLL = Path(r"D:\SmacxThinker\game\thinker.dll")
DEFAULT_MAP = ROOT / "work" / "_thinker_symbols_5.5.json"

ENGINE_LO, ENGINE_HI = 0x400000, 0xA00000
VEHS_DEF, VEHCOUNT, FACTIONS = 0x952828, 0x9A64C8, 0x96C9E0


class Fn:
    __slots__ = ("off", "end", "calls", "imms", "data", "stores", "insns", "name")

    def __init__(self, off):
        self.off, self.end, self.calls, self.imms, self.data, self.stores, self.insns, self.name = off, off, [], set(), set(), set(), 0, None

    @property
    def size(self):
        return self.end - self.off


def carve(dll: Path, symbols: dict[str, int]):
    p = pefile.PE(str(dll))
    base = p.OPTIONAL_HEADER.ImageBase
    img = bytes(p.get_memory_mapped_image())
    text = next(s for s in p.sections if s.Name.startswith(b".text"))
    lo, hi = text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    # pass 1: every E8 target in .text is a function start
    starts = set(symbols.values())
    for ins in md.disasm(img[lo:hi], base + lo):
        if ins.mnemonic == "call" and ins.operands and ins.operands[0].type == capstone.x86.X86_OP_IMM:
            t = ins.operands[0].imm - base
            if lo <= t < hi:
                starts.add(t)
    starts = sorted(starts)
    fns = {}
    for i, s in enumerate(starts):
        f = Fn(s)
        f.end = starts[i + 1] if i + 1 < len(starts) else hi
        fns[s] = f
    rev = {v: k for k, v in symbols.items()}
    size = p.OPTIONAL_HEADER.SizeOfImage
    dlo, dhi = base + hi, base + size            # everything after .text: .data/.rdata/.bss -- Thinker's own globals
    for f in fns.values():
        f.name = rev.get(f.off)
        for ins in md.disasm(img[f.off:f.end], base + f.off):
            f.insns += 1
            if ins.mnemonic == "call" and ins.operands and ins.operands[0].type == capstone.x86.X86_OP_IMM:
                f.calls.append(ins.operands[0].imm - base)
            for op in ins.operands:
                vals = []
                if op.type == capstone.x86.X86_OP_IMM:
                    vals.append(op.imm & 0xFFFFFFFF)
                if op.type == capstone.x86.X86_OP_MEM and op.mem.disp:
                    vals.append(op.mem.disp & 0xFFFFFFFF)
                for v in vals:
                    if ENGINE_LO <= v < ENGINE_HI:
                        f.imms.add(v)
                    elif dlo <= v < dhi:
                        f.data.add(v - base)             # a Thinker global (its Vehs / VehCount / Factions pointers, statics)
            if ins.mnemonic == "mov" and len(ins.operands) == 2 and ins.operands[0].type == capstone.x86.X86_OP_MEM \
               and ins.operands[0].size == 1 and ins.operands[1].type == capstone.x86.X86_OP_IMM:
                f.stores.add((ins.operands[0].mem.disp & 0xFF, ins.operands[1].imm & 0xFF))
            if ins.mnemonic == "ret" or (ins.mnemonic == "jmp" and False):
                pass
    return fns, rev, base


def callers_of(fns, target):
    return [f for f in fns.values() if target in f.calls]


def describe(f: Fn, rev):
    named = sorted({rev[c] for c in f.calls if c in rev})
    unnamed = sorted({c for c in f.calls if c not in rev})
    return (f"+{f.off:X}..+{f.end:X} ({f.size} B, {f.insns} insns){' = ' + f.name if f.name else ''}\n"
            f"    named calls: {', '.join(named) or '-'}\n"
            f"    unnamed calls: {', '.join(f'+{c:X}' for c in unnamed[:14])}{' ...' if len(unnamed) > 14 else ''}\n"
            f"    engine refs: {', '.join(f'0x{i:X}' for i in sorted(f.imms)[:12])}{' ...' if len(f.imms) > 12 else ''}\n"
            f"    thinker globals: {', '.join(f'+{i:X}' for i in sorted(f.data)[:16])}{' ...' if len(f.data) > 16 else ''}\n"
            f"    byte stores: {', '.join(f'[+0x{d:X}]=0x{v:X}' for d, v in sorted(f.stores)[:10])}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dll", default=str(DEFAULT_DLL))
    ap.add_argument("--map", default=str(DEFAULT_MAP))
    ap.add_argument("--dump", default=None, help="function offset (hex) to describe")
    a = ap.parse_args(argv)
    symbols = {k: int(v) for k, v in json.loads(Path(a.map).read_text(encoding="utf-8")).items()}
    fns, rev, base = carve(Path(a.dll), symbols)
    print(f"{len(fns)} functions carved from .text; {sum(1 for f in fns.values() if f.name)} named", file=sys.stderr)
    if a.dump:
        off = int(a.dump, 16)
        f = fns.get(off) or next((f for f in fns.values() if f.off <= off < f.end), None)
        print(describe(f, rev) if f else "no function there")
        return 0

    # set_move_to: stores order ORDER_MOVE_TO (0x18) at VEH+0x11 and status_icon 'G' (0x47) at VEH+0x2B
    smt = [f for f in fns.values() if (0x11, 0x18) in f.stores and (0x2B, 0x47) in f.stores]
    print("== set_move_to candidates (order 0x18 @+0x11 and 'G' @+0x2B):")
    for f in smt: print("  " + describe(f, rev).replace("\n", "\n  "))
    # combat_move: calls mod_battle_fight and set_move_to, large
    mbf = symbols.get("mod_battle_fight")
    print("== callers of mod_battle_fight (combat_move among them; mod_alien_move is named):")
    for f in callers_of(fns, mbf) if mbf else []:
        print("  " + describe(f, rev).replace("\n", "\n  "))
    # Thinker reaches engine globals through its OWN pointer variables (Vehs, VehCount, Factions ... in its .data),
    # so the engine addresses never appear in its code. Recover the variables from functions we know:
    #   set_move_to reads Vehs (and nothing else of that kind); mod_battle_fight loops VehCount over Vehs.
    mbf_fn = fns.get(mbf) if mbf else None
    vehs_var = vehcount_var = None
    if smt and mbf_fn:
        common = smt[0].data & mbf_fn.data
        print(f"== Thinker globals shared by set_move_to and mod_battle_fight (Vehs among them): {', '.join(f'+{i:X}' for i in sorted(common))}")
        print(f"   mod_battle_fight's others (VehCount among them): {', '.join(f'+{i:X}' for i in sorted(mbf_fn.data - smt[0].data))}")
    # the move.cpp helpers: small functions called from the combat_move candidate that read the same globals
    print("== callees of the largest mod_battle_fight caller (combat_move) that touch mod_battle_fight's globals,")
    print("   i.e. loop over Vehs (non_ally_in_tile / stack_search / allow_* candidates):")
    cms = sorted((callers_of(fns, mbf) if mbf else []), key=lambda f: -f.size)
    if cms and mbf_fn:
        cm = cms[0]
        seen = set()
        for c in cm.calls:
            f = fns.get(c)
            if f and c not in seen and f.size < 0x600 and (f.data & mbf_fn.data):
                seen.add(c)
                print("  " + describe(f, rev).replace("\n", "\n  "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
