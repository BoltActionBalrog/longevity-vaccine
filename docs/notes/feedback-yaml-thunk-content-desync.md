---
name: feedback-yaml-thunk-content-desync
description: A cave thunk's CONTENT bytes are a separate patches.yaml entry from its symbol/group/site — committing only the latter makes a clean apply CALL into a zero-filled cave
type: feedback
---

In `patches.yaml` a cave thunk has TWO independent parts: (a) the **symbol declaration** + its **group** + the **site** that calls it, and (b) the **content `bytes:`** entry under the cave's `contents:` list that actually writes the thunk body. They are easy to desync — committing (a) without (b) passes a dry-run (the symbol resolves to its address, the site verifies) but `--apply` leaves the cave region **zero-filled**, so the site's `CALL` jumps into zeros → crash.

Concrete case (found 2026-06-23): the working `9fc033ce` build had `thunk_faction_submenu`'s bytes poked directly into the live exe, but only its symbol/group/site were ever committed to `patches.yaml` — the content entry was missing. The live binary and a clean `--restore`/`--apply` had silently diverged; re-applying would have produced a broken submenu. Fixed by backfilling the content (verified byte-identical to the live exe at its cave VA).

**Why:** the canonical build path is `--restore` then `--apply` from `patches.yaml`. If yaml ≠ the live exe, the next rebuild regresses something that "worked," and the test MD5 lock won't catch it until you rebuild.

**How to apply:** after building, treat `patches.yaml` as the source of truth — confirm a clean apply reproduces the live exe's MD5 (the Layer-1 `test_apply_md5` does this). When adding a thunk, add BOTH the symbol AND a `contents:` `bytes:` entry. To check an existing thunk isn't a phantom, read the cave VA in the live exe (pefile: RVA→file offset on the appended section) and confirm non-zero bytes that match the resolved template. Distinct from the encoding gotcha in [[feedback-yaml-utf8-encoding]]; see also [[project-smac-codecave-section]].
