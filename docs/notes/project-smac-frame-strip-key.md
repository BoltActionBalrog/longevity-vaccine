---
name: project-smac-frame-strip-key
description: Why scaled/thickened popup frames in the SMACX patcher show see-through strips, and the one-byte blit-key fix
type: project
---

When a 9-slice popup frame is thickened via the render-small-then-NN-blit thunk (thunk_box_thick / thunk_box_thick_hollow), the scratch buffer g_frame_buf is filled with a key, the frame strokes are drawn into it, then `Buffer_draw_2` (0x5d84c0) blits it scaled onto the dest. The **3rd arg = transparency key** decides what copies:

- key **-1** (`6A FF`) = COPY-ALL: every pixel of the scratch (including the interior fill) is written to the dest.
- key **9** (`6A 09`) = key-out-9: pixels equal to the engine transparent key 9 are skipped; only the strokes copy.

**The bug:** the HOLLOW (content-frame) variant fills its interior with key 9 (so the list composites through) but was cloned from the title thunk which blits with key **-1**. Copy-all then wrote the key-9 interior onto the dest, punching a TRANSPARENT hole over the opaque d690 backdrop. The rows cover the centre; the frame-inner-to-row margin stays key-9 → **see-through strips on all four sides** of the option box. Growing the box margins just widened those gaps and made them obvious.

**The fix (one byte):** in thunk_box_thick_hollow blit with key **9** (`6A FF` → `6A 09`). The title thunk thunk_box_thick keeps key -1 because its fill is OPAQUE (index 0x41, the brown title band) — copy-all is correct there.

**RULE for any future scaled frame:** hollow / transparent-interior frame → Buffer_draw_2 key **9**. Opaque-fill frame → key **-1**.

Diagnostics that nailed it: Frida frame-map (hook_frame_map.js) showed d690 fills its buffer EXACTLY (rect `[0,0,1457,1182]` == destbuf), proving the dark field was never "too small" — the strips were a draw-method artifact, not a sizing one. See (a private note), [[project-smac-modal-scaling]]; reusable technique in skill `scaling-frames`.
