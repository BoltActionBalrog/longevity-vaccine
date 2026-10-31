---
name: feedback-modal-builder-hook-before-set-modal
description: A screen builder whose tail calls Win_set_modal (vtbl+0xE4, pop_wait) does not return until the screen CLOSES — a fit/repaint placed "after the build call" runs after the maintainer has left; hook the builder's own Win_set_modal call site instead (SE label fit v1/v2 → v3, 2026-09-17)
type: feedback
---

**Lesson (2026-09-17, SE label fit):** `SocialWin_build` looked like "layout + show, then return", so the label
fit v1/v2 ret-swapped the two `call SocialWin_build` sites (t_se_enter2) to run "after the build". The build's
TAIL is `push MainWin / push pop_wait / push 0 / call [vtbl+0xE4]` = **Win_set_modal**, which pumps the modal loop
and returns only when the maintainer closes the screen. The fit therefore ran after the screen was gone: two user
screenshots (1920) still ellipsised, AND the after-close repaint of 35 buttons of a closed window broke the SE
hotkey. The callers' own shape gave it away: `call build; call SocialWin_close; call social_set(...)` — a caller
that CLOSES/APPLIES right after a "build" is calling a modal.

**Why:** report_* wrappers, DatalinkWin and every screen that "waits for OK" pass `pop_wait` (0x5398E0) to
`Win_set_modal` from INSIDE the builder. A post-call hook is a post-CLOSE hook for all of them.

**How to apply:**
- Before placing anything "after `X_build` returns", disassemble X_build's tail: a `call [vtbl+0xE4]` (Win_set_modal
  0x5EE190, RET 0xC) or any pop_wait push means the function is modal. Also check the caller: close/apply calls
  right after the build are the tell.
- Hook the builder's Win_set_modal call SITE instead (`FF 90 E4 00 00 00` → `E8 thunk 90`): E8-entered with ecx =
  the window and the 3 args intact; do the work; `mov eax,[ecx]; jmp [eax+0xE4]` so the modal's RET 0xC still
  balances the caller. Parity-test the contract (entered once, this/args intact, callee-saved regs).
- Repaint before the modal through vtbl+0xF8 (GraphicWin_redraw), the builder's own post-BaseButton_init idiom.
- Never ret-swap a caller's return address into a global for this (single global = re-entrancy hazard as well).

Related: [[project-smac-social-engineering]], [[feedback-bake-port-fidelity]], [[feedback-thunk-call-vs-detour]].
