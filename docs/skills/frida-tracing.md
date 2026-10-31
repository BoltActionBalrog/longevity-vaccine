---
name: frida-tracing
description: Use when building or running a Frida trace of terranx.exe to read ground-truth runtime values (field offsets, rects, call args, struct layouts) during SMACX patcher work.
---

# Frida tracing the SMACX UI

Runtime ground truth beats static reasoning. Decompiler output and hand-decode have
repeatedly disagreed on this binary (what `[popup+0x30d0]` is, whether a draw site is dead,
whether a thunk fires), and pixel forensics on screenshots has produced false readings.
When a layout/geometry/scale question has a numeric answer, **trace it** rather than argue it.

## Front-load discovery — confirm the WHOLE chain live BEFORE building anything

The expensive failures on this project all came from acting on an **unverified static assumption** and
finding out three game-runs later it was wrong. One such fix was built on a *decompile-audited* "portrait
draws via `Sprite_blit_scaled_core` @131×157" claim — but the hook never
fired, because (a) the source was a `Sprite` struct, not a `Buffer`, so the dims gate read garbage, and
(b) `Sprite_draw_2` was `thiscall` with arg2=key, not the C sig's `spriteId`. Both were knowable in ONE
census run. **The rule: before you write a fix (especially asm), prove the entire chain live — which
function fires, its real ABI/calling convention, the source struct layout, the gate values, the scale —
in as few runs as possible.** A run that returns "the hook never fired" is the most expensive outcome;
design the trace so even a negative result is informative.

Three reusable discovery patterns (each is one run; prefer them over a narrow "I bet it's X" probe):

- **Census** (`hook_*_census`): when you don't *know* which primitive does the work, hook ALL plausible
  candidates at once (e.g. `Sprite_draw_2`, `Sprite_blit_scaled_core`, `Buffer_draw_2`, `Buffer_copy_3`)
  and log the **first occurrence of each distinct `(fn, dims, scale)` tuple** with a `Set` dedup, plus a
  periodic running total via `setInterval` so you can see the screen is live. This reveals the real path,
  dims, scale, dest, and key — instead of one assumed gate that silently never matches.
  **THE STATE-CENSUS RULE (mandatory — this class has burned every menu we've touched, see
  [[feedback-draw-state-multiplicity]]):** an element is never ONE draw. The census run must DRIVE
  every variant — hover it, PRESS-AND-HOLD it (release off-element), open/close it, select/refresh,
  let it animate/flash — and the dedup key must include a CONTENT signature (a sampled row/bytes),
  never dims/site alone: same-size different-art states alias under a dims key (the pressed
  MENU/COMMLINK sprite hid behind the idle capture exactly this way). State sprites live in ARRAYS
  (stride +0x2C for FlatButton bands) — when you find one, probe its neighbors. A fix designed from
  one state's data covers one state.
- **Struct dump** (`hook_*_dump`): once you know the function, dump the candidate struct
  (`dumpStruct(base,0x40)`) AND **probe every pointer-looking field** (`isHeapPtr` → read 256 bytes,
  count distinct values: a pixel plane shows ~29 distinct, a binary mask shows 2). That's how the Sprite
  layout (`data@+0x4`, `stride@+0x10`, `w@+0x18`, `h@+0x1c`, `mask@+0x30`) fell out in one run.
- **Confirm the ABI from the dump, not the header.** Print `ecx` + the first 6 stack dwords and read them
  against known values (a dest you recognise like `0x940824`, a key you expect like `9`): if the "Buffer"
  on the stack is actually the dest and the source is in `ecx`, it's `thiscall` — regardless of what
  terranx.h says. Fix terranx.h immediately ([[feedback_terranx_h_symbol_format]]).

Then **prototype the fix itself in Frida** (compute it in JS, write over the dest in `onLeave`) and SEE it
in-game before writing a single byte of machine code. The faction-portrait averaging fix was validated
this way at both resolutions before any thunk existed.

## Trace the RENDER, not just the inputs — rects can read symmetric while pixels aren't

A trace of a draw's input **rects** can look perfectly correct while the on-screen result is wrong, because
the defect lives **downstream in the render** (e.g. the frame-enlarge floor-quantizes its output below the
rect height, so a concentric pair of rects still renders an asymmetric stroke channel — see
[[scaling-frames]] §5). Two faction-title "fixes" addressed the rect layer and didn't move the pixels. When
a geometry question is about what's *drawn*, measure the **dest buffer**, not the args:
- Hook a point where the dest buffer is known (e.g. the box-draw dispatcher gives you `ecx`=dest), then in
  `onLeave` read it: `data@+0x54`, `stride@+0x4a8`, `w@+0x80`, `h@+0x84` (h is **negative** = top-down).
  Dump a **pixel column/row** across the feature and run-length it.
- **Palette-resolve indices to RGB** before classifying. Frame strokes are green (`0x1f`,`0x22`) over a
  **near-black** backdrop (`0xc6`≈(12,12,16)); a raw luminance threshold mislabels them — classify by
  green-dominance. Palette = `PALETTEENTRY colors[256]` at `0x94c590`, 4 bytes each (r,g,b,flags).
- A screenshot is an equally valid "render trace": scan its columns with the same palette logic. Keep
  distinct measurements distinct — stroke **thickness** ≠ the **channel gap** between two strokes.

## Hook hosts: function ENTRIES only, and prove each host's bytes first

Every probe crash in this project came from WHERE a hook sat, not from what it logged (the full hazard
catalogue is [[feedback-frida-attach-branch-target]]). The 2026-09-13 recurrence: a probe attached
mid-function right after a painter's `call [ebx+0x2c]` — where `[esp]` holds the caller's saved edi —
ran fine at 4K and AV'd on the first paint at 1600 (the island pointer came back through `pop edi`).
Rules that make a probe safe by construction:

- **Attach at function entries only.** Never after a call, never at a resume address, never inside a
  loop. If you need "what happened after the callback returned", read it at the NEXT entry you hook
  (or from `this.returnAddress` at a callee's entry: it names the call site for free).
- **Print the host's first 8 bytes before attaching** (`py scripts\_disasm_live.py A A+8`): a
  `68 xx xx xx xx C3` (push/ret) or `E9` = a baked detour site, a leading `E8` into the cave = a baked
  call-helper — none of these are hosts (Sprite_draw_2 0x5E4B4A, Sprite_blit_scaled_core 0x5E4B9A,
  base_draw 0x55AF20, Buffer_box_sprite 0x5E2DD3 are all detoured today). Hook the plain-E8-called
  helper around them instead (e.g. `thunk_checkbox_scale`, `MapWin_draw_base_tile`).
- **Cross-check cave thunk addresses against the ledger** at the moment you write the probe: thunks
  MOVE on a bake (t_rwk_blink went 0x24F70 → 0x6E30 and a different helper took its old slot; a stale
  constant would have logged the wrong function without an error).
- **One log file per run, named with a timestamp** (`frida_<name>_<UTC>.log`): the shared
  `LOG_APPEND` pre-script silently lost a 4K run once; never rely on append to keep two runs apart.
- **Keep hot primitives out** (`Buffer_put_pixel`, per-pixel lines): an Interceptor on a per-pixel call
  stalls the game before the screen you need is reachable. Rect-level primitives with an early
  `ecx`/dest gate are fine.
- "It ran at 4K" proves nothing about a poisoned slot — the fault fires wherever that slot is consumed.

## The harness (already built — don't reinvent)

- `work\run-frida.bat <hook.js>` — self-elevates via UAC, spawns the game (`-f`) under Frida,
  loads `scripts\frida_common.js` then your hook. Resolves the game dir/exe from `game-path.bat`.
- `work\scripts\frida_common.js` — shared helpers published on `globalThis`. Load order is handled
  for you. Helpers:
  - `VA(staticVA)` — translate a static `0x4xxxxx` VA through the real load base. Works on **both**
    `terranx.exe` and `terranx_PRACX.exe` (uses the main module), so hooks attach by **address** and
    run on patched or pristine binaries identically.
  - `log(msg)` — append a line to `LOG_PATH` (also echoes to console). File opens lazily on first call.
  - `requireBase()` — guard at the top of the hook; returns false (and logs) if the module isn't found.
  - `u32(v)`, `arg(esp,n)`/`argS(esp,n)` (1-based: `arg(esp,1)`==`[esp+4]`), `bufWH(addr)` (Buffer W@+0x80
    H@+0x84), `installAVHandler(label)` (snapshot EIP/ESP on access-violation, then let the OS kill).

## Writing a hook (`work\scripts\hook_<name>.js`)

```js
"use strict";
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_<name>.log";  // set BEFORE first log()
log("=== hook_<name>.js started ===");
installAVHandler("<name>");          // optional; only if the trace may crash
if (requireBase()) {
  const fn = VA(0x00607210);         // static VA -> runtime addr
  Interceptor.attach(fn, {
    onEnter() {
      const sp = this.context.esp;   // thiscall: this=ECX; stack args at [esp+4],[esp+8],...
      log("x=" + sp.add(0x0c).readS32() + " y=" + sp.add(0x10).readS32());
    }
  });
}
```

- Read fields off a struct pointer with `p.add(0xOFF).readS32()`. Globals via `VA(0xADDR).readS32()`.
- Verify global addresses against a known patch (e.g. ScreenWidth is `0x9b7b1c` — the boxw thunk's
  `cmp [0x9b7b1c],0x3ff`), not by guessing; a wrong address silently logs garbage.
- Keep one trace answering one question; dump every field that feeds the formula you're testing so the
  log is self-contained (e.g. for a layout: the box rect, the margins, the band, the content-bottom).

## Running — ALWAYS wire 4K **and** non-4K shortcuts

Every UI fix must be verified at 4K + at least one non-4K res (the popup-scale `g` differs per
resolution — 1920×1080 g=22 scales *less* than 1600×1200 g=25). So a trace is useless if it can only
launch at the desktop's 4K. **`run-frida-at-res.bat <hook.js> <W> <H> [pre.js]` is the canonical
runner** — it sets the resolution (crash-safe ini set/restore) then injects Frida, and self-elevates
via UAC. 4K is `3840 2160` (a harmless no-op set/restore). Do NOT hand-write per-hook wrapper bats;
point every shortcut at this one tool.

1. **ALWAYS repoint ALL the desktop trace shortcuts to the newest hook** — pass the hook `.js`, not a
   bat. This rewrites three shortcuts in one shot — 4K (`SMACX Frida Trace`), `SMACX Frida Trace
   1920x1080`, and `SMACX Frida Trace 1600x1200` — each targeting `run-frida-at-res.bat` with the
   right `<W> <H>`:
   ```
   pwsh -File D:\SmacxUi\work\repoint-trace-shortcut.ps1 hook_<name>.js
   ```
   (Add `-Pre frida_log_append.js` to append rather than overwrite the log across runs.) Do this every
   time you build or switch traces — providing the non-4K shortcuts is part of finishing a trace, not
   optional. The resolution list lives in the `$variants` table in that script if you need to add one.
2. Tell the user to run **both** the 4K shortcut and a non-4K one (e.g. `SMACX Frida Trace 1600x1200`),
   typing `%resume` at the Frida prompt, navigating to the screen, then `quit`/Ctrl+D. Then `Read` the
   `LOG_PATH` file (use `-Pre frida_log_append.js` to keep both resolutions' lines in one log).

## Notes

- A new `hook_*.js` starts as a throwaway analysis artifact: reuse and overwrite freely rather than
  accumulating near-duplicates. The ones worth keeping are tracked and listed in
  `work\scripts\PROBES.md` (observer or writer); leave those as they are and copy one to start a new
  probe. You no longer need per-hook `run-frida-<name>.bat` wrappers —
  `run-frida-at-res.bat <hook.js> <W> <H>` runs any hook at any resolution directly.
