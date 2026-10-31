---
name: feedback-edit-script-slice-guard
description: Python edit scripts on the proto must assert every located slice is non-empty and ordered before str.replace — an empty old-string sprays the replacement between every character and the file is gone
type: feedback
---

When an edit script computes a block as `s[s.index(A):s.index(B)]`, assert `0 < start < end` (and a sane length) BEFORE `s.replace(block, new)`. If B occurs before A the slice is `""`, and `str.replace("", new)` inserts `new` between every character of the file.

**Why:** DW proto v14k (2026-08-29): the hook I wanted to replace had been inserted AFTER the anchor I used as its end marker, the slice came back empty, and `hook_dw_scale_proto.js` became 100 copies of the new block interleaved with its own source. Only the per-version backup (`_dw_crops/v3/hook_dw_scale_proto.v14j.backup.js`) made it a two-minute recovery. The earlier run of the same script had also aborted on a later assert AFTER the file was correct but BEFORE writing — so "OK" from `node --check` on the unchanged file plus a backup copy of it produced a misnamed backup.

**How to apply:** (1) locate the END of a block relative to its START (`s.index("\n  });\n", start)`), never by an independent anchor; (2) assert `start < end` and `end - start < expected_max`; (3) write the file only at the end of the script, and make the version-string rename tolerant (`re.sub(... count=1)`) so a failed assert cannot leave the file un-bumped; (4) back up BEFORE editing, name the backup by the version it holds. Related: (a private note), [[project-smac-design-workshop]].

**Recurrence 2026-08-30 (DL proto v12g):** a region replace `s[:a0] + new + s[a1:]` between two anchors silently deleted
two LATER-inserted blocks (v12c netwin re-assert, v12e native-rect fix) that had been inserted "before anchor a1"
(`let lbDrawN = 0;`) — a whole regression round-trip with the maintainer. **Rule:** before slicing, assert the region
`s[a0:a1]` contains ONLY the text you intend to delete (e.g. `assert 'Interceptor.attach' not in region` beyond the
expected count, or check for every known block marker), and prefer anchoring inserts on a UNIQUE comment line of
their own rather than a shared anchor that later edits also use.

**2026-08-30 (2nd recurrence, different shape):** a `const` inserted via anchor landed in a NESTED scope; `node --check` passed (syntax-only) but the hook threw `ReferenceError` at LOAD in-game — script died mid-file → no patches (vanilla screen) + every callback touching the binding errored. **After any structural hook edit, run `node work\tests\frida_shim_load.js` (minimal Frida-API shim; must print `LOAD COMPLETED WITHOUT THROW` + the final "attached:" log) — syntax check alone is not enough.** Cross-scope flags go on `globalThis`, never `const`.
