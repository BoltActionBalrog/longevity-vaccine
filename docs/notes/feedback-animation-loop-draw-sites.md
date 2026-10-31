---
name: feedback-animation-loop-draw-sites
description: Scaling gotchas from the filedlg rails PART 3 — animation loops have their own duplicate draw sites; scale_nn ignores the engine clip rect; stack-object identity gates need an end-of-life disarm
type: feedback
---

Member of the [[feedback-draw-state-multiplicity]] class (one element, many draw variants — read that first).

Three reusable lessons from the Load/Save dialog slide-animation rail fix (build ae8f92e5, 2026-07-03):

1. **An engine ANIMATION loop draws the same element through its OWN call sites.** slide_show draws the
   rail strips from 4 settled sites (into the window buffer, window coords) AND 4 mid-animation sites
   (onto the SCREEN buffer, screen coords) — and slide_hide (the close animation) has 4 more. Patching
   only the settled sites left the element wrong during the animation, "snapping" correct at settle.
   **Why:** per-frame draws usually target a different dest (screen vs window buffer) with different
   coordinate spaces and gates, so build-time thunks and dest-identity gates silently miss them.
   **How to apply:** when scaling an element, census EVERY xref to its sprite/draw primitive — settled
   draws, animation/slide loops, AND the hide/close symmetric function — before declaring the sites
   covered. Sibling of [[feedback-scaling-inline-rebuild-paths]] (inline rebuilds) — same class: a
   second draw path the primary hook misses. Diagnose which path is live before patching (here the
   recorded "double-scaled y at the settled sites" hypothesis was wrong; the settled sites never ran
   mid-slide).

2. **thunk_sprite_scale_nn clips ONLY to dest buffer bounds (0..w, 0..h) — it IGNORES the Buffer's
   engine clip rect (Buffer_set_clip 0x5D8000).** Vanilla draw paths often RELY on the clip rect
   (slide_show/hide clip everything to the window's settled rect so the fixed 529px strips trim at the
   window bottom). Routing such a draw through scale_nn spills outside the rect, and the spill can be
   PERMANENT (the surrounding restores are engine-clipped and never repaint it).
   **How to apply:** before tailing a draw into scale_nn, check whether the dest had a clip rect set;
   if so the thunk must self-clip: CEIL the pre-scale x/y anchors so floor(v'·g/16) ≥ the rect edge
   (never paints left/above), and clamp the bottom/right by temporarily shrinking the sprite blit dims
   (save [ecx+0x14], set the clamped value, CALL scale_nn on re-pushed arg copies, restore, ret 0x18).

3. **An identity gate keyed on an object POINTER needs a DISARM at the object's end-of-life.** The
   FileDlg is a STACK object ([ebp-0x6884] in its callers), so the stashed g_fd_winbuf goes stale after
   the modal ends and a later stack dialog at the same address would false-positive the gate (same class
   as [[feedback-frida-dedup-popup-reuse]]'s heap-ptr reuse). Fix = a tiny exit detour that zeroes the
   stash when the matching object finishes (slide_hide common exit @0x45DE5A — chosen because ALL exit
   paths cross it, incl. animation-disabled early-outs). A fresh re-stash at setup alone is NOT enough:
   the stale window between teardown and the next setup is where the false positive lives.

Bonus decode fact (recorded in terranx.h): in slide_show the window ptr is [ebp+8] and esi is the slide
Y; in slide_hide esi is the window and [ebp+8] is reused as the step counter — a shared helper can gate
on `(stash-0x444 == [ebp+8] || == esi)` because the non-pointer register is always a small int.

4. **Slide-rail arm criteria (2026-09-26, base screen / Council / Datalinks fixed).** A window that calls slide_show/slide_hide DIRECTLY needs its two E8s routed through thunk_popup_railshow/railhide ONLY IF our patches ENLARGE it: the defect is native strips at native offsets from a scaled edge. A native-size window (multiplayer DiploWin 0x73ACD8, literal w=832) already has correct rails and wrapping would CREATE the bug. A NULL-window slide (combat console slide_show(0,2)) draws no rails at all, and the wrapper would arm g_fd_winbuf=0x444 which railslide false-matches against win 0 -- never wrap it. Census = every E8 to 0x45D440/0x45D970 in the BUILT exe.
**How to apply:** before wrapping, prove the window is enlarged at runtime; capture the slide in slow motion by raising g_anim_frame_ms (exe VA 0x691AF8, default 20) under a debugger or Frida (the `[UIMod] DebugAnimFrameMs` ini key was removed 2026-10-11).
