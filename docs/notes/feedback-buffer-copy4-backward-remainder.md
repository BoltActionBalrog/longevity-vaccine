---
name: feedback-buffer-copy4-backward-remainder
description: Buffer_copy_4's overlapping (src==dst) backward copy reads one byte BEFORE the buffer when a row's byte count is not a multiple of 4 -- never call it for sub-tile / odd-width self-blits; memmove rows yourself
type: feedback
---

Buffer_copy_4 0x5DFF00's src==dst path (0x5E013D..) copies backwards (std; rep movsd then a rep movsb for
count & 3) and its byte-remainder loop reads from data - 1 on the first row (crash dump 2026-10-09: AV at
0x5E076D, esi = data - 1, with a 3833-byte row). Vanilla only self-blits whole-tile scroll deltas (multiples of 8
px at every zoom), so the remainder loop never runs there; the first sub-tile scroll step (dx = -7) crashed.

**Why:** an engine primitive that looks general is only exercised by vanilla on a lattice; the untested
remainder path is broken. **How to apply:** for any frame shift the engine does not itself perform (sub-tile
offsets, odd widths), do a row-wise memmove over data/stride in the right row order (bottom-up when the
content moves down); keep Buffer_copy_4 for whole-tile deltas only. Related: [[project-smac-drag-scroll-perf]].
