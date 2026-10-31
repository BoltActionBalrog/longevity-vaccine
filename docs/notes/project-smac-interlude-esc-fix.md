---
name: project-smac-interlude-esc-fix
description: Story-interlude Esc flashed the game menu and needed a second press (base-game bug, user-confirmed on the unmodded exe) -- mechanism (WM_KEYDOWN closes the modal InterludeWin, the same keystroke's WM_CHAR reaches the Console) and the uimod.dll fix (interludekey.cpp WH_GETMESSAGE swallow), status
type: project
---

**Bug (user 2026-10-30, reproduced on PRACX+ours and on the un-PRACX'd exe = vanilla's):** during a story interlude the
first Esc does not close it; the game menu flashes over it; the second Esc closes both.

**Mechanism (trace work\scripts\hook_interlude_esc.js + the audit's disassembly, 2026-10-30):** the interlude
(interlude 0x5230E0 -> load_credits_b 0x45F2E0) is a modal GraphicWin of the InterludeWin class (vtable 0x66C708, a
STACK object in interlude()). WM_KEYDOWN -> vtbl+0x138 Win_on_key 0x5F5D10 -> Win_key_dispatch 0x5EEB90: a
char-producing key skips Win_key_default and calls the raw on_keydown vtbl+0x68 = InterludeWin_on_keydown 0x45F6F0
(`Win_release_modal; return 1` -- ANY key closes it, a click too via +0x50). Win_on_key's tail then calls
Win_drain_chars 0x5FCFE0: PeekMessage(WM_CHAR) + Dispatch INSIDE the key-down's dispatch -> Win_get_active_target()
is now the Console -> Win_key_default 0x5EEA90 -> Console_on_key_click(0x1B) -> pop_9 -> the game menu, modal, over the
interlude; the interlude's modal loop (Win_set_modal, pump 0x5FC700) ends only when that menu closes. Every byte on the
path is pristine in our build; PRACX and Thinker do not touch it. Because the CHAR is drained synchronously, the
KEYDOWN/CHAR pair can never be split by another message -- which is what makes the hook's pairing airtight.

**Fix (uimod.dll `src\uimod\src\interludekey.cpp`, built 2026-10-30, workspace DLL 213a0db4, USER-VERIFIED
2026-10-30 "fix landed correctly"; CHANGELOG line under Fixes):** a thread-local WH_GETMESSAGE hook (same shape as wheel.cpp's): a WM_KEYDOWN delivered while g_modal_top
(0x9B7AE0) is an InterludeWin arms the watch; the following WM_CHAR becomes WM_NULL when that interlude is no longer
the modal top. Class-pinned (ctor vtable store 0x45F2C0 + the stub slots), both exes. CHANGELOG line (base-game bug)
goes in after the verify. Symbols recorded in terranx.h (Win_on_char, Win_key_default, InterludeWin_vtbl).

**Lesson:** a modal window that closes on KEYDOWN leaves the keystroke's WM_CHAR for whoever is active next; when a
"menu flashes" after a key closes something, look for the second delivery of the same keystroke, not for a key eater.
Related: [[project-smac-credits-interlude]], [[project-smac-thinker-compat]].
