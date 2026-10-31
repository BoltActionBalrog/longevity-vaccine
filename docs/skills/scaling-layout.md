---
name: scaling-layout
description: Use when scaling any repeated stride, multi-cell span, or chrome-around-content geometry in the SMACX patcher — list rows, button bars, tab strips, grids, frame bands, or a border/rect that wraps content.
---

# Scaling repeated strides & chrome-around-content

Two laws. Both are enforced by `work\tests\test_scaling_laws.py` (5,200+ assertions,
no game launch, <25s). The reference implementation is `work\scripts\scaling_laws.py`
— **it is the source of truth**; the Frida hooks and the baked asm thunks are *ports*
of it. If a port disagrees with the module, the port has the bug.

Run the sweep before you run the game:

    cd work\tests && py -m pytest test_scaling_laws.py -q

---

## LAW A — Remainder distribution

> `n * floor(scale*v)` is **not** `floor(n * scale * v)`.

Every per-cell floor is discarded, and the loss **accumulates to the far end of the
run**. It is invisible at 4K (ratios land on clean halves) and glaring at 1600×1200
and 1920×1080.

Confirmed sightings, all one bug:

| Where | Symptom the user reported |
|---|---|
| Faction list rows | pitch floors `19×1.5625 = 29.69 → 29`; 7 rows lose 4.8px → "too much empty space below the Peacekeepers button" |
| 9-slice corner band | cell widths came out `2,1,2,1…` at g=25 and `1,2,…` at g=22 → "corners too small at 1600" / "too large at 1920" |
| NetWin lobby | native additive constants (`slack −10`, `gap +3`) |

**The primitive** (`scaling_laws.cum` / `.distribute`):

```python
half_down(a, b) = (2*a + b - 1) // (2*b)      # round(a/b), exact .5 -> DOWN
cum(i, total, n) = half_down(i*total, n)      # boundary of cell i
distribute(total, n) = [cum(i+1)-cum(i) for i in range(n)]
```

`sum(distribute(t, n)) == t` exactly, no cell is off the ideal by more than 1px, and
`cum(0)=0 / cum(n)=total` pin both ends. Half-**down**, not half-up: `g/16 = 2.5` at
4K and the approved stroke there is 2px.

For a repeated stride use `row_positions(top, native_pitch, count, g)` — it lands row
`i` at its faithful rounded position instead of `top + i*floor(pitch)`.

### Pin the chrome cells first (`band_widths`)

When some cells are **chrome** (a stroke, a bevel diagonal) and the rest are **inert**
(interior fill, padding), the chrome cells take the canonical stroke width `K` and the
remainder spreads over the inert cells *only*. Distributing uniformly across all cells
makes the stroke wobble — that is the disease, not the cure.

    K = stroke_width(g) = half_down(g, 16)

**`K` comes from the LEVER, never from an element's own dst/src ratio.** They differ at
exact-half boundaries, and the ratio is *span-dependent* — so two frames on the same
screen end up with different stroke widths. Deriving `K` per-element tipped the 4K
stroke 2→3 for some spans and not others. The band's *depth* `B` may derive from the
frame's own `dst/src` (so it meets the stretched middle seamlessly); the *stroke* may not.

---

## LAW B — Chrome follows content

> Derive a chrome rect's edge from the quantities the **content** uses.
> Never independently scale the chrome rect.

The faction picker's list ring is built natively as `(L−3, T−3, R+21, B+3)`, and
natively `T + rows×pitch == B + 3`: the ring's bottom **is** where the rows end, flush
by construction. Scaling the ring rect on its own breaks the identity, because the
rows' pitch floors and the ring's does not — leaving a void that grows with `g`.

```python
ring_bottom = rows_top + rows * pitch        # not su * (nativeB + 3)
```

The payoff is not tidiness. At `g = 16` the expression collapses to vanilla's own
arithmetic (`131 + 3 + 7×19 = 267 = nativeB + 3`), so **the native no-op becomes
algebraic — a proof, not a test you hope passes.** Whenever you can express a scaled
edge as a function of content quantities, do it; you get 1024×768 correctness for free.

This is the defensible, narrow form of "anchors and margins": don't re-architect the
layout, just stop scaling chrome and content down two independent paths.

Corollary: pulling a chrome edge **in** is safe; pushing it **out** can overrun the dest
buffer. Assert the direction.

---

## Working method (this is what actually saved time)

1. **Measure vanilla first.** Pristine `.bak` or the reference shots in
   `refs\pristine\`. Never eyeball a magnitude. ([[feedback-proportionate-scaling]])
2. **State the law in `scaling_laws.py`, then sweep it** over `g ∈ [16,40]` × plausible
   spans *before* touching the game. This caught the `K`-tipping bug pre-flight and
   would have caught the bevel widths a round earlier.
3. **Assert the g=16 identity** as a test. It outranks every other property.
4. Only then run the Frida prototype at **4K + 1600×1200 + 1920×1080**. A fix confirmed
   at one resolution is not confirmed. ([[feedback-smac-all-resolutions]])
5. Freeze the numbers: `py work\scripts\gen_scaling_vectors.py --write` and commit
   `tests\golden_scaling_vectors.json`. The baked asm is later verified against *those
   integers*, not against the JS prototype.

## Reading engine fields (gotcha that cost three rounds)

The faction picker's row pitch is **not** at a fixed window offset. Virtual inheritance:

```
0x48924b  mov eax,[ebx]        ; ebx = W+0x86bc  -> the Dialog's VPTR
0x48924d  mov ecx,[eax+8]      ; ecx = VIRTUAL-BASE ADJUSTOR
0x489250  mov [ecx+esi+0x8704],0x13
```

So `pitchAddr = W + [[W+0x86bc]+8] + 0x8704`. Reading `W+0x8704` raw yields a pointer.
When a yaml comment says `[esi+0xNNNN]`, **check whether the store has a second index
register** before treating it as a window offset. Generalize: `vbase_field(W, vptrOff,
fieldOff) = W + [[W+vptrOff]+8] + fieldOff`.

## Shared fields have ONE scaler (the Datalinks tech-page regression, 2026-09-19)

Before baking an init-time lever that leaves a shared struct field in DEVICE space, census
every older thunk that read-scale-restores the same field (`grep "0xOFF"` across
`assemble_*.py`) — each one now double-scales. `rw_scale_shared` made `RW+0x5980` (textB) /
`RW+0xE268` (lineH) device at ReportWin init; `t_dl_techwrap` still multiplied them, so the
Datalinks side buttons sat +225 px low at 1600x1200 but only +26 at 4K.

- **Never gate a bracket on a magnitude guard** (`cmp eax,800`): it is resolution-dependent,
  so 4K passes by accident (the clean-4K-proves-nothing class). Discriminate native vs device
  by a vanilla IDENTITY between fields (`textB == win_h - 0x35`; law `dl_tech_inputs`).
- A bracket thunk's parity test must sweep BOTH entry states (native and already-device) at
  g = 16/22/25/40 — a test seeded only with native values cannot see the double scale.
- Vanilla tech-page law (measured on pristine): the centre box's centre is fixed; the
  prereq/leads-to groups centre a constant 8 native ABOVE it, independent of box height.
