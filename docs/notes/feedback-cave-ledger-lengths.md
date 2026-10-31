---
name: feedback-cave-ledger-lengths
description: Never trust yaml-ledger thunk lengths when growing a cave thunk in place — measure the content entry; code laid over a symbol-only data slot crashes at runtime and only the new overlap test catches it
type: feedback
---

Growing `thunk_popup_railhide` in place by a 10-byte prepend crashed the game on the first popup close
(build ffb6dd8d, 2026-07-04): the ledger comment said 100B but the real thunk was 110B (an earlier
prepend was never reflected), so the grown tail landed under `g_popup_railsave` — a **runtime data slot**
whose pointer store zeroed the tail bytes → branch into garbage → AV @0xa0f631.

**Why:** ledger/comment lengths in patches.yaml drift; and data globals have no content entry, so
content-vs-content overlap checks can't see code laid over them.

**How to apply:**
- Before growing any cave thunk in place, MEASURE it: `ap.ByteTemplate(entry["bytes"]).total_length`
  (or count the hex), and check the gap to the next occupied offset — content entries AND symbols.
- Prefer relocation to fresh cave space over in-place growth when flush against anything; callers via
  `{abs32:}/{rel32:}` placeholders retarget automatically.
- The guard is baked in: pytest `test_cave_contents_do_not_overlap` (work\tests\test_patch_integrity.py)
  checks content-vs-content AND models symbol-only offsets as 4-byte spans. Keep it passing; don't
  weaken it to silence a layout conflict — move the thunk instead.

## Second escape (2026-07-11): file-zero scans are NOT a free-space map — runtime SCRATCH REGIONS

Allocating the tutwin thunks at pcave2+0x7000 crashed Quick Start (build 2ec360f5): the region is
zero in the FILE but is `g_bm_fx` — the bandmap blit's u16[4096] dest→src map, REBUILT IN-PROCESS on
every frame draw. The thunks were overwritten with map data and the gate executed u16 values
(AV @0xa13175, bytes@eip = incrementing-with-dups map pattern). The ledger DECLARED the region two
lines above the new entries; the mistake was deriving "free" from a zero-byte scan of the exe.

**How to apply:**
- Free space = (no content entry) AND (no ledger symbol span) — never "zeros in the file".
- Large scratch symbols now declare `size:` in patches.yaml (g_bm_fx 0x2000, g_bm_fy 0x1000,
  fwdx/fwdy 0x100); `test_cave_contents_do_not_overlap` uses it (default 4B). Declare `size:` when
  adding any multi-dword scratch.
- The old guard had a blind spot: it deduped symbol-vs-content by OFFSET, so a thunk allocated at
  exactly a scratch symbol's start HID the symbol. Now deduped by NAME. Don't regress this.

## Third escape (2026-08-03): an ASSEMBLER's own slot assert is necessary, not sufficient

Growing `thunk_basewin_btnzoom` v4→v5 (66→83B) for the ProdPicker arc ran it 0xB3F0..0xB443 straight
through `thunk_scale_reject_uncache` @pcave2+0xB430 — a thunk from a LATER, unrelated arc
(`scale_ratio_uncache`). `assemble_basewin.py`'s assert passed, because that script bounds each slot
only against the next thunk **it itself emits** (0xB450 `thunk_bw_rect_core`) and has no idea another
group allocated inside that gap. The apply was refused by the patcher's cave-overlap verifier — the
guard from the first escape did its job and nothing was written.

**How to apply:** a per-assembler slot assert proves only "I don't collide with my own group." Before
growing any thunk, read the pcave2 occupancy out of **patches.yaml** (all groups). When a squatter is
in the way, relocating IT can be the cheaper fix — but only after proving it is position-independent
(no rel32/abs32 self-references) and that every caller reaches it through a `{rel32:}`/`{abs32:}`
symbol placeholder that retargets automatically. Verify the relocation in the BUILT exe by scanning
every section for rel32 AND abs32 references to both the new and old addresses: the new address must
have exactly the expected site count and the old address must have **zero** (done here: 8 sites moved
to 0xA17300, 0 stale). A comment warning now sits at that assert in `assemble_basewin.py`.

## Fourth escape (2026-08-06): a symbols+content occupancy SCAN is still not the ledger

Relocating `thunk_fe_pair_remap` v6 to pcave2+0xE380 hard-crashed the game (build 854fc1e8): the
"2300B gap" my scripted scan found (all yaml content entries + all symbol entries + live-exe zeros)
was `g_staple_scratch` — thunk_staple_coverage's 48×48 runtime capture block (0xE360..0xEC60,
`mov edi,0xa1a360` + 0x30×0xC dword copy per SUPPORT staple-face draw). Its symbol entry carried
NO size, so the scan modeled 4B; the region is zero on disk. The TRUE allocation record was the
pcave2 `length:` ledger comment — "0xE360-0xEC5F g_staple_scratch 2304B BSS" — which I did not read.
Root-caused by disassembling the neighbor thunk and finding the write loop; fixed by growing pcave2
0x10000→0x11000 and placing v6 at +0x10000 (build e828237a).

**How to apply:**
- ALLOCATE FROM THE LEDGER (the pcave2 `length:` comment) — it is the one place every arc records
  its true spans, including runtime BSS. A regex scan of symbols+contents is a cross-check, not an
  allocator. A suspiciously LARGE gap in a packed cave usually IS someone's scratch region.
- When taking a slot next to a `*_coverage`/`*_scratch` neighbor, disassemble the neighbor and
  census its data references first (the write loop names its own bounds).
- All three coverage scratch regions now declare `size:` (staple 0x900, chev 0x190, arrow 0x1F8 —
  arrow had NO symbol at all before this); the overlap guard sees the true spans. Declare `size:`
  on every new BSS symbol at creation time, and add the symbol entry even for ledger-documented
  regions.

Related: [[feedback-yaml-thunk-content-desync]], [[project-smac-popup-interior-stripes]],
[[project-smac-codecave-section]], [[project-smac-prodpicker]].

## Escapes 5+6 (2026-08-14, EDITORWHO bake) + the ARBITER TOOL

The q16 slot comment said 109B, the entry measured 139B (5B slack — v4 could not fit in place);
the ledger's "0x4127-0x429F free" was thunk_basewin_gwinit (272B @0x4130). Both caught pre-bake
by measuring; neither was visible in prose. The arbiter is now a tool:
`py work\scripts\cave_map.py` (occupancy from ByteTemplate lengths + symbol `size:`),
`--at 0xOFF` (owner/neighbours), `--fit 0xN` (smallest free gap that fits). Run it BEFORE
allocating or growing, and again after the yaml edit. Its caveat = escapes 2/4: undeclared
runtime scratch is invisible to it too, so declare `size:` on every multi-dword scratch symbol.
