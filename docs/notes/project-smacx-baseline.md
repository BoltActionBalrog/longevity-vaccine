---
name: project-smacx-baseline
description: Baseline Ghidra analysis findings for terranx.exe — memory layout, function count, graphics API surface, UI asset string addresses
type: project
---

Baseline Ghidra auto-analysis of `terranx.exe` (2026-05-26). These are expensive to recompute (~152s for full analysis) and the anchor addresses guide every subsequent investigation.

**Binary:** `D:\GOGGalaxy\Games\Alpha Centauri\terranx.exe`, MD5 `2d0b1438eb73f98519134d7a4f6bc054`, 32-bit x86 PE, image base `0x00400000`, ~6 MB. This is the PRACX-patched binary (date stamp 2024-08-19 from GOG repack).

**Auto-analysis stats:** 10,137 functions, 709,254 instructions, 134,393 defined data items, 32,906 symbols.

**Compiler-spec caveat:** Ghidra heuristic applied `windows_vs12_32` (VS 2013) data type archive. SMAC is actually a 1999 build (VC5/VC6 era). Struct layouts for stdlib types should mostly still match, but be skeptical of compiler-specific things.

**Memory blocks:**
```
Headers      0x00400000-0x00400fff  (   4 KB) R--
.text        0x00401000-0x00663fff  (2444 KB) R-X
_SELFMOD     0x00664000-0x00668fff  (  20 KB) RWX   <-- non-standard, writable+executable
.rdata       0x00669000-0x00681fff  ( 100 KB) R--
.data        0x00682000-0x009c21f7  (3328 KB) RW-
SECTION.4    0x009c3000-0x009c4fff  (   8 KB) RW-
UVA_DATA     0x009c5000-0x009c9fff  (  20 KB) RW-
.rsrc        0x009ca000-0x009cffff  (  24 KB) R--
.reloc       0x009d0000-0x00a0bfff  ( 240 KB) R--
```
The `_SELFMOD` RWX section is non-standard and almost certainly PRACX's hook/patch zone. Any of our own patches that need executable code will need similar handling.

**Graphics API surface (GDI imports, with call-site counts):**
`SelectObject` 27, `GetDC` 12, `ReleaseDC` 11, `SetTextColor` 6, `BitBlt` 5, `TextOutA` 5, `GetTextExtentPoint32A` 5, `SetBkMode` 4, `CreateCompatibleDC` 3, `CreateDIBSection` 2, `CreateFontIndirectA` 2, `StretchBlt` 2, `SetStretchBltMode` 2.

**Zero DirectDraw imports.** DDRAW.DLL is linked, but `Blt`, `BltFast`, `Lock`, `Unlock`, `Flip`, `SetDisplayMode`, etc. are absent from the import table. They're called through COM vtables on `IDirectDrawSurface*` — see strategy note in [[project-smac-ui-scaling]].

**UI asset string anchors (all in `.data`):**

| Address | String | Refs |
|---|---|---|
| `0x00685170` | `iface.pcx` | 1 |
| `0x00682730` | `menu.pcx` | 1 |
| `0x00687274` | `report.pcx` | 1 |
| `0x006832b0` | `credits.pcx` | 2 |
| `0x00685380` | `credits.pcx` | 2 |
| `0x00685084` | `ICONS.PCX` | 1 |
| `0x00685064` | `NEWICONS.PCX` | 1 |
| `0x00685128` | `NEWICONS.PCX` | 1 |
| `0x0068458c` | `hoficons.pcx` | 1 |
| `0x006863e4` | `monicons.pcx` | 1 |

These are entry points: the xref from each string lands inside the function that loads that bitmap. `iface.pcx` is the main UI overlay, so its xref function is the natural anchor for tracing the UI render path.

**Tooling pattern:** drive Ghidra from standalone pyghidra Python scripts in `D:\SmacxUi\work\scripts\`, each paired with a `.bat` in `D:\SmacxUi\work\` that sets env vars and invokes it. `run-stats.bat` / `stats.py` is the first example. No GhidraScript .java boilerplate.

**Why:** These numbers and addresses are expensive to recompute (152s for analysis) and the anchor addresses guide every subsequent investigation.

**How to apply:** When the maintainer asks about call counts, memory layout, or "where does the game load X", cite these facts directly rather than re-running analysis. If the maintainer reanalyzes terranx.exe, treat these as stale until reverified.

Related: [[project-smac-ui-scaling]], [[reference-smac-modding]]
