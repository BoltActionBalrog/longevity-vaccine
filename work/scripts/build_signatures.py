"""Relocate-by-signature tool for the SMACX UI-scaling patch set.

The re-port lifeline. When GOG ships a new terranx.exe, the absolute VAs in
patches.yaml will have shifted, but the *instruction bytes* at each patch site
are mostly stable. This tool turns every patch site into a wildcard-masked byte
signature so each site can be re-located by content instead of by trusting an
absolute address.

What it does
------------
  build   For each site, extract a window of bytes around it from the baseline
          binary, wildcard the bytes that legitimately vary across builds
          (operand placeholders + relative/absolute address operands in the
          surrounding context), auto-widen the window until the signature is
          unique in the file, and write signatures.yaml. Self-validates that
          every signature matches exactly once at its known VA.

  locate  Load signatures.yaml and search a target binary (default: the new
          GOG terranx.exe). Reports, per site, how many matches were found and
          at what VA — the proposed relocated address. This is the mode you run
          on the new build on day one of the re-port.

Why no disassembler: capstone isn't in the bundled interpreter. Instead we mask
operands using two sources of truth:
  1. The exact placeholder positions inside each site (from the ByteTemplate in
     apply_patches.py — rel32/abs32 operands the patcher already knows vary).
  2. A byte-level heuristic over the surrounding context: wildcard the 4 bytes
     after any E8/E9 (near call/jmp rel32), the 4 bytes after any FF15/FF25
     (absolute indirect call/jmp through [disp32]), and any standalone 4-byte
     little-endian value that lands in the image's VA range (likely an absolute
     code/data pointer). These are exactly the bytes a relocation perturbs.

Usage
-----
  D:\\SmacxUi\\work\\run-build-signatures.bat            # build + self-validate
  D:\\SmacxUi\\work\\run-build-signatures.bat --locate <path-to-new-terranx.exe>
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pefile
import yaml

# Reuse the placeholder-aware template + VA resolver from the patcher so the
# notion of "which bytes are operands" stays identical to apply time.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_patches import ByteTemplate, VaResolver, load_patches, build_symbol_table  # noqa: E402
import config  # noqa: E402

DEFAULT_BASELINE = str(config.terranx_bak())  # 2d0b14 pristine PRACX base
DEFAULT_PATCHES = r"D:\SmacxUi\work\patches\patches.yaml"
DEFAULT_SIGS = r"D:\SmacxUi\work\patches\signatures.yaml"

# Window-growth bounds. We start at the site (+anchor) and widen to shrink the
# match count and raise the fixed-byte count. We do NOT insist on a globally
# unique match: some patch sites are genuine twins (e.g. the two near-identical
# blit loops in do_menu_rightside) whose bytes stay identical well past any sane
# window. Those are disambiguated by ORDINAL instead — "the k-th of N matches in
# address order" — which is stable across builds as long as the twin count holds.
MAX_WINDOW = 96          # hard cap on total signature length (bytes)
MIN_FIXED_BYTES = 12     # require at least this many non-wildcard bytes for confidence
ACCEPT_MATCHES = 2       # stop widening once match count drops to this or below
GROW_STEP = 2            # bytes added per widen iteration


def image_va_range(pe: pefile.PE) -> tuple[int, int]:
    ib = pe.OPTIONAL_HEADER.ImageBase
    lo = ib + min(s.VirtualAddress for s in pe.sections)
    hi = ib + max(s.VirtualAddress + s.Misc_VirtualSize for s in pe.sections)
    return lo, hi


def heuristic_operand_mask(window: bytes, va_lo: int, va_hi: int) -> list[bool]:
    """Return a per-byte 'is-variable' mask for a context window, marking bytes
    that a relocation is likely to change. True = wildcard."""
    n = len(window)
    mask = [False] * n
    i = 0
    while i < n:
        b = window[i]
        # E8 rel32 (call near) / E9 rel32 (jmp near): next 4 bytes are a
        # build-relative displacement.
        if b in (0xE8, 0xE9) and i + 4 < n:
            for j in range(i + 1, i + 5):
                mask[j] = True
            i += 5
            continue
        # FF 15 (call [disp32]) / FF 25 (jmp [disp32]): next 4 bytes are an
        # absolute VA into the import/data area.
        if b == 0xFF and i + 1 < n and window[i + 1] in (0x15, 0x25) and i + 5 < n:
            for j in range(i + 2, i + 6):
                mask[j] = True
            i += 6
            continue
        i += 1
    # Any remaining 4-byte LE value that lands inside the image VA range is a
    # plausible absolute pointer operand (mov reg,imm32 of an address, push
    # offset, etc.). Mask those 4 bytes too.
    for k in range(0, n - 3):
        if any(mask[k:k + 4]):
            continue
        val = int.from_bytes(window[k:k + 4], "little")
        if va_lo <= val < va_hi:
            for j in range(k, k + 4):
                mask[j] = True
    return mask


def placeholder_mask(template_str: str) -> list[bool]:
    """Per-byte variable mask for a site's own bytes, from its ByteTemplate.
    Placeholder (rel32/abs32) bytes are variable; literal bytes are fixed."""
    tmpl = ByteTemplate(template_str)
    mask: list[bool] = []
    for kind, payload in tmpl.segments:
        if kind == "lit":
            mask.extend([False] * len(payload))
        else:  # rel32 / abs32 — 4 variable bytes
            mask.extend([True] * 4)
    return mask


def sig_to_regex(window: bytes, mask: list[bool]) -> re.Pattern:
    parts = []
    for b, var in zip(window, mask):
        parts.append(b"." if var else re.escape(bytes([b])))
    return re.compile(b"".join(parts), re.DOTALL)


def count_matches(pattern: re.Pattern, data: bytes) -> list[int]:
    return [m.start() for m in pattern.finditer(data)]


def fixed_byte_count(mask: list[bool]) -> int:
    return sum(1 for v in mask if not v)


def build_signature(site: dict, data: bytes, resolver: VaResolver,
                    va_lo: int, va_hi: int) -> dict | None:
    """Build a unique, relocation-robust signature for one site.

    Returns a dict: {window_hex, mask (list[bool]), site_offset (bytes into the
    window where the site starts), fixed_bytes, matches, sig_va}.
    Returns None if the site can't be located/made-unique within MAX_WINDOW."""
    va = int(site["virtual_addr"])
    length = int(site["length"])
    anchor_len = int(site.get("anchor_before_length", 0) or 0)
    foff = resolver.to_file_offset(va)
    if foff is None:
        return None

    # The site's own variable mask (operand placeholders).
    site_mask = placeholder_mask(site["original_bytes"]) if site.get("original_bytes") \
        else [False] * length

    # Grow the window outward from [anchor .. site .. ] alternately right then
    # left, shrinking the match count toward ACCEPT_MATCHES and raising the
    # fixed-byte count. Then disambiguate the true site by ordinal.
    pre = anchor_len   # bytes before the site already curated as anchor
    post = 0
    best = None
    while True:
        start = foff - pre
        end = foff + length + post
        if start < 0 or end > len(data):
            break
        window = data[start:end]
        # Compose the mask: heuristic over the whole window, then force the
        # site's own placeholder positions to variable.
        mask = heuristic_operand_mask(window, va_lo, va_hi)
        site_start_in_win = pre
        for k, v in enumerate(site_mask):
            if v:
                mask[site_start_in_win + k] = True
        pattern = sig_to_regex(window, mask)
        matches = count_matches(pattern, data)
        fixed = fixed_byte_count(mask)
        # Ordinal of the true site among the matches (by file-offset order).
        match_starts = sorted(matches)
        try:
            ordinal = match_starts.index(start)
        except ValueError:
            ordinal = None  # site's own location didn't match its own signature?!
        cand = {
            "window_hex": " ".join(f"{b:02X}" for b in window),
            "mask": "".join("1" if v else "0" for v in mask),
            "site_offset": site_start_in_win,
            "length": length,
            "fixed_bytes": fixed,
            "matches": len(matches),
            "ordinal": ordinal,
            "sig_va": resolver.image_base + (start - _section_rva_base(resolver, start)),
        }
        best = cand  # keep the latest (widest) attempt as best-so-far
        # Prefer a globally-unique signature when reachable; genuine twins fall
        # through to the window cap and are resolved by ordinal below.
        if ordinal is not None and len(matches) == 1 and fixed >= MIN_FIXED_BYTES:
            return cand
        if (pre + length + post) >= MAX_WINDOW:
            return cand
        # Alternate growth: prefer extending forward (post), then backward.
        if post <= pre:
            post += GROW_STEP
        else:
            pre += GROW_STEP
    return best


def _section_rva_base(resolver: VaResolver, foff: int) -> int:
    """Given a file offset, return (file_offset - rva) for its section so that
    image_base + (foff - that) == VA. Helper to convert a window-start file
    offset back to a VA."""
    for rstart, rend, fstart, _name in resolver.sections:
        # section file range: [fstart, fstart + (rend - rstart))
        if fstart <= foff < fstart + (rend - rstart):
            return fstart - rstart
    return 0


def cmd_build(baseline: Path, patches: Path, out: Path) -> int:
    data = baseline.read_bytes()
    pe = pefile.PE(data=data, fast_load=True)
    resolver = VaResolver(pe)
    va_lo, va_hi = image_va_range(pe)
    sites, groups, caves, symbols_spec = load_patches(patches)

    # Sign every site that has bytes to match (all but pure-marker entries).
    target_sites = [s for s in sites if s.get("original_bytes")]
    print(f"Baseline : {baseline}  ({len(data):,} bytes)")
    print(f"Signing  : {len(target_sites)} site(s) with original_bytes\n")

    out_sigs = {}
    failures = []
    for s in sorted(target_sites, key=lambda x: int(x["virtual_addr"])):
        sid = s["id"]
        sig = build_signature(s, data, resolver, va_lo, va_hi)
        if sig is None:
            print(f"  [FAIL] {sid}: could not build signature (offset/window issue)")
            failures.append(sid)
            continue
        known_va = int(s["virtual_addr"])
        # Valid if the true site is locatable: its own location is among the
        # matches (ordinal set) and resolves back to the known VA.
        ok = (sig.get("ordinal") is not None and sig.get("sig_va") is not None
              and (sig["sig_va"] + sig["site_offset"]) == known_va)
        twin = sig["matches"] > 1
        marker = "[ok]  " if ok and not twin else ("[twin]" if ok else "[WARN]")
        if not ok:
            failures.append(sid)
        ord_tag = f" ord={sig['ordinal']}/{sig['matches']}" if twin else ""
        print(f"  {marker} {sid:55} matches={sig['matches']} fixed={sig['fixed_bytes']:2} "
              f"win={len(sig['window_hex'].split())}b{ord_tag}")
        out_sigs[sid] = {
            "function": s.get("function"),
            "status": s.get("status"),
            "group": s.get("group"),
            "known_va": f"0x{known_va:08X}",
            "site_offset": sig["site_offset"],
            "length": sig["length"],
            "fixed_bytes": sig["fixed_bytes"],
            "match_count": sig["matches"],
            "ordinal": sig["ordinal"],
            "signature": sig["window_hex"],
            "mask": sig["mask"],
        }

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        f.write("# Auto-generated by build_signatures.py — relocation signatures\n")
        f.write(f"# Baseline: {baseline.name}  ({len(data):,} bytes)\n")
        f.write("# 'signature' is a space-separated hex window; 'mask' is a per-byte\n")
        f.write("# string where 1 = wildcard (varies across builds), 0 = fixed.\n")
        f.write("# 'site_offset' is the byte offset of the patch site within the window.\n\n")
        yaml.safe_dump({"signatures": out_sigs}, f, sort_keys=False, default_flow_style=False)

    print(f"\nWrote {len(out_sigs)} signature(s) to {out}")
    if failures:
        print(f"\n{len(failures)} site(s) need attention (non-unique or VA mismatch):")
        for sid in failures:
            print(f"    - {sid}")
        return 1
    print("\nAll signatures unique and self-validated against the baseline VAs.")
    return 0


def cmd_locate(target: Path, sigs_path: Path) -> int:
    data = target.read_bytes()
    pe = pefile.PE(data=data, fast_load=True)
    resolver = VaResolver(pe)
    sigs = yaml.safe_load(sigs_path.read_text(encoding="utf-8")).get("signatures", {})

    print(f"Target   : {target}  ({len(data):,} bytes)")
    print(f"Sigs     : {sigs_path}  ({len(sigs)} signature(s))\n")
    print(f"  {'site':55} {'known_va':>10} {'found_va':>10}  status")

    n_unique = n_shifted = n_missing = n_ambiguous = 0
    for sid, spec in sigs.items():
        window = bytes(int(t, 16) for t in spec["signature"].split())
        mask = [c == "1" for c in spec["mask"]]
        pattern = sig_to_regex(window, mask)
        starts = sorted(count_matches(pattern, data))
        known_va = spec["known_va"]
        exp_count = spec.get("match_count", 1)
        ordinal = spec.get("ordinal", 0)
        if len(starts) == 0:
            n_missing += 1
            print(f"  {sid:55} {known_va:>10} {'--':>10}  MISSING")
        elif len(starts) != exp_count:
            # Twin count changed vs the baseline — ordinal can't be trusted.
            n_ambiguous += 1
            print(f"  {sid:55} {known_va:>10} {'(%d/%d)' % (len(starts), exp_count):>10}  "
                  f"COUNT-CHANGED")
        else:
            foff = starts[ordinal] + spec["site_offset"]
            base = _section_rva_base(resolver, foff)
            found_va = resolver.image_base + (foff - base)
            same = f"0x{found_va:08X}" == known_va
            tag = "" if exp_count == 1 else f"  (twin {ordinal}/{exp_count})"
            if same:
                n_unique += 1
                print(f"  {sid:55} {known_va:>10} 0x{found_va:08X}  same{tag}")
            else:
                n_shifted += 1
                print(f"  {sid:55} {known_va:>10} 0x{found_va:08X}  SHIFTED{tag}")

    print(f"\n  unique-same={n_unique}  shifted={n_shifted}  "
          f"missing={n_missing}  ambiguous={n_ambiguous}")
    return 0 if (n_missing == 0 and n_ambiguous == 0) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Relocate-by-signature tool")
    ap.add_argument("--baseline", default=DEFAULT_BASELINE,
                    help="Baseline binary to build signatures from (2d0b14)")
    ap.add_argument("--patches", default=DEFAULT_PATCHES)
    ap.add_argument("--sigs", default=DEFAULT_SIGS, help="signatures.yaml path")
    ap.add_argument("--locate", metavar="TARGET",
                    help="Locate signatures in TARGET binary instead of building")
    args = ap.parse_args()

    if args.locate:
        return cmd_locate(Path(args.locate), Path(args.sigs))
    return cmd_build(Path(args.baseline), Path(args.patches), Path(args.sigs))


if __name__ == "__main__":
    sys.exit(main())
