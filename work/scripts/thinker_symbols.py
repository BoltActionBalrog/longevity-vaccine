r"""Thinker symbol map WITHOUT symbols: recover `function name -> thinker.dll offset` for every Thinker function
that Thinker itself installs over the exe.

thinker.dll's patch_setup (refs\thinker\src\patch.cpp) calls write_call / write_jump / write_offset(site, func)
for ~800 sites. MinGW -O2 cdecl compiles each call as
    mov dword [esp+4], <func VA>      C7 44 24 04 imm32
    mov dword [esp],   <site VA>      C7 04 24    imm32
    call write_x
so the DLL's .text holds every (site, func) pair as literal immediates, and patch.cpp names the function at each
site. Joining the two gives the map; the live Frida trace of 2026-10-29 confirmed mod_enemy_turn +0xAEEB0,
mod_enemy_move +0xAECE0 and mod_battle_fight_2 +0xA7350 exactly (decision 5, option 2: pinned detours).

Usage:
  thinker_symbols.py [--dll <thinker.dll>] [--src <refs\thinker\src\patch.cpp>] [--out map.json] [--check]
Prints the map (name -> offset, hex) and the join statistics; --check verifies the three trace-confirmed offsets.
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DLL = Path(r"D:\SmacxThinker\game\thinker.dll")
DEFAULT_SRC = ROOT / "refs" / "thinker" / "src" / "patch.cpp"
CONFIRMED = {"mod_enemy_turn": 0xAEEB0, "mod_enemy_move": 0xAECE0, "mod_battle_fight_2": 0xA7350}   # v5.5, MD5 5af21362


def pairs_in_dll(dll: Path) -> dict[int, int]:
    """site VA -> function offset (within the DLL image), from patch_setup's argument stores."""
    import pefile
    p = pefile.PE(str(dll))
    base, size = p.OPTIONAL_HEADER.ImageBase, p.OPTIONAL_HEADER.SizeOfImage
    img = bytes(p.get_memory_mapped_image())
    text = next(s for s in p.sections if s.Name.startswith(b".text"))
    lo, hi = text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize
    out: dict[int, int] = {}
    for m in re.finditer(rb"\xc7\x04\x24(....)", img[lo:hi]):
        site = struct.unpack("<I", m.group(1))[0]
        if not 0x400000 <= site < 0x6B0000:
            continue
        off = lo + m.start()
        f = re.search(rb"\xc7\x44\x24\x04(....)", img[off - 16:off + 16])
        if not f:
            continue
        func = struct.unpack("<I", f.group(1))[0]
        if base <= func < base + size:
            out[site] = func - base
    return out


def names_in_source(src: Path) -> dict[int, tuple[str, str]]:
    """site VA -> (kind, function name) from patch.cpp's write_call / write_jump / write_offset lines."""
    text = src.read_text(encoding="utf-8", errors="replace")
    out: dict[int, tuple[str, str]] = {}
    for m in re.finditer(r"write_(call|jump|offset)\((0x[0-9A-Fa-f]+),\s*\((?:int|void\*)\)\s*([A-Za-z_][A-Za-z_0-9]*)", text):
        out[int(m.group(2), 16)] = (m.group(1), m.group(3))
    return out


def build(dll: Path = DEFAULT_DLL, src: Path = DEFAULT_SRC) -> tuple[dict[str, int], dict]:
    pairs = pairs_in_dll(dll)
    names = names_in_source(src)
    sym: dict[str, set[int]] = {}
    for site, off in pairs.items():
        if site in names:
            sym.setdefault(names[site][1], set()).add(off)
    ambiguous = {k: sorted(v) for k, v in sym.items() if len(v) > 1}
    flat = {k: sorted(v)[0] for k, v in sym.items() if len(v) == 1}
    stats = {"pairs_in_dll": len(pairs), "named_sites": len(names), "functions": len(flat), "ambiguous": ambiguous}
    return flat, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dll", default=str(DEFAULT_DLL))
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--out", default=None)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    flat, stats = build(Path(a.dll), Path(a.src))
    print(json.dumps({k: f"0x{v:X}" for k, v in sorted(flat.items())}, indent=1))
    print(json.dumps({k: v for k, v in stats.items() if k != "ambiguous"}), file=sys.stderr)
    if stats["ambiguous"]:
        print("ambiguous:", stats["ambiguous"], file=sys.stderr)
    if a.out:
        Path(a.out).write_text(json.dumps(flat, indent=0, sort_keys=True), encoding="utf-8")
    if a.check:
        bad = {k: (flat.get(k), v) for k, v in CONFIRMED.items() if flat.get(k) != v}
        if bad:
            print("CHECK FAILED:", {k: (hex(x) if x else None, hex(y)) for k, (x, y) in bad.items()}, file=sys.stderr)
            return 1
        print("check: the trace-confirmed offsets match", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
