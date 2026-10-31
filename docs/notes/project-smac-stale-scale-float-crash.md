---
name: project-smac-stale-scale-float-crash
description: ESC-quit AV root cause (VANILLA bug): blit-core stores scale float 0x9B6624 BEFORE the 4.0-limit check — a rejected >4x blit poisons it; next cached-ratio blit over-reads its source 2.2x. FIXED + USER-VERIFIED 2026-07-18 (76bb1956, scale_ratio_uncache, 8 reject sites -> cache_num=-1). Supersedes the bandmap-overrun theory (DISPROVEN)
type: project
---

**FIX APPLIED 2026-07-18b, live exe 76bb1956 — USER-VERIFIED 2026-07-18 ("the crash has
indeed gone away"; 4K base view → ESC → quit-confirm appears). CLOSED.** Replaces
[[project-smac-bandmap-overrun-crash]]'s theory, which is DISPROVEN (see below).

## Root cause — GENUINE VANILLA ENGINE BUG (fully measured from both dumps)

All **8 sprite-blit-core copies** (fstp sites 0x5E3F2F, 0x5E4C75, 0x5E5899, 0x5E6708,
0x5E7482, 0x5E8222, 0x5E905B, 0x5E9DAA) share one scale-rebuild block:
`fild num; fidiv den; fstp [0x9B6624]; fld; fcomp qword [0x66FDC8]=4.0; test ah,0x41;
jne accept; push 1; mov ecx,[ebp+8]; call Buffer_free_data; ...` — the float is stored
**before** the limit check. A REJECTED >4.0× blit therefore leaves `g_sprite_scale_float`
poisoned while the master run table (0x9B3AD8, Sprite_fill_scaling_table) and the ratio
cache (0x696D20/24) keep the old ratio. The next fractional blit at the *cached* ratio skips
the whole rebuild → dest rect = w×STALE_float (fmul) but the clipped-table builders
(0x5EAB0F/0x5EABBF) walk the FRESH run table until that span is consumed — their source
count is derived purely from dest-span/run-table, **never bounded by the sprite dims** — so
the blit consumes (stale/fresh)× the source on BOTH axes and reads far past the buffer.

Crash instance: base view at 4K → vanilla map-tile blits at 74/16 (4.625) and 88/16 (5.5)
rejected (>4.0) → float poisoned → ESC → quit popup draws a PCX-**name**-backed art sprite
via our thunk_sprite_draw at 40/16 → core reload branch (`*sprite==name` → Buffer_load_pcx
into global Buffer 0x9B6080, RESIZED to the pcx dims 200×120 → Buffer_draw_2 at
SCALE_NUM/DEN 40/16) → tables built for 200·5.5=1100 dest / 440 src cols / 264 src rows →
read overrun ~2.2×, AV at the next unmapped page (fault = data+122·200+176 exactly). Both
dumps agree (29948: float 4.625; 44756 Frida-free: float 5.5; cache 40/16 both).
Latent in vanilla forever: vanilla UI blits are 1/1 (num==den path never touches the float);
only our g/16 popup draws + the base-view >4× zoom rejections combine to trigger it.

## The fix (group `scale_ratio_uncache`, yaml)

Restore the engine's own invariant (float==table==cache): the 8 reject-path
`call Buffer_free_data` E8s (0x5E3F4D, 0x5E4C93, 0x5E58B7, 0x5E6726, 0x5E74A0, 0x5E8240,
0x5E9079, 0x5E9DC8) retarget to `thunk_scale_reject_uncache` @pcave2 0xB430
(`mov [0x696D20],-1; push Buffer_free_data; ret`) → a rejected blit invalidates the cache →
the next fractional blit rebuilds float+table+cache atomically. Byte-neutral for accepted
blits; rejected blits still reject (their tiles were never drawn). No scaling arithmetic →
no scaling_laws law. Full suite green; CHANGELOG'd as a base-game fix.

## Why the bandmap theory was wrong (lessons)

- The "crash frame" 0xA0F14F was a **stale dword inside Buffer_draw_2's uninitialized
  locals** (its frame = 0x18 locals + 4 saved regs → caller ret at +0x44, which held
  0x5E4C06 = core's PCX-reload branch). LESSON: validate a stack-walk frame by laying out
  the callee's exact prologue from disassembly before trusting a code-address dword —
  popup draw loops leave many plausible stale rets in reused stack regions.
- thunk_bandmap_blit CANNOT overrun: bm_axis clamps the middle phase and mirrors bands
  in-range; the fallback thunk_keyed_stretch_blit resolves to Buffer_copy_3 = GDI
  StretchBlt (clips, bounds-safe) — the original static "grown dstW maps to srcW" claim
  never checked WHICH code consumes the grown span.
- Diagnostic keys that cracked it: dump the engine's blit globals (fake sprite 0x9B3A50,
  table meta 0x9B475C/0x9B3AD4/0x9B6074/0x9B53E8, float 0x9B6624 vs cache 0x696D20) and
  check them for MUTUAL consistency — the mixed state (dest spans ×5.5, run consumption
  ×2.5, pitch fresh) named the exact defect.
- `scripts/parse_minidump.py`'s pcave2 tag range ended at 0xA12000 (pre-growth) — extend
  tags when caves grow, or a cave ret goes unlabeled in walks.

## Deferred hardening (unscheduled)

The clipped-table builders trust dest-span/run-table consistency absolutely; any FUTURE
inconsistency would overrun again. If ever needed: bound the builders' source count by the
sprite dims (site-level clamp). Not done now — the reject path was the only writer that
could break the invariant, and it is fixed.

Related: [[project-smac-base-screen]] (the base visit that surfaced it),
[[feedback-sprite-expand-drops-last-row]] (different, dest-side rounding class),
[[project-smac-namebase-popup]] (the popup family whose art draw crashed).
