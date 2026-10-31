---
name: feedback-resize-sync-repaint-scratch
description: GraphicWin_resize(a4=1) repaints synchronously -- a cave cell carried across it must not be scratch for any painter-reachable thunk
type: feedback
---

GraphicWin_resize 0x5D5540 with a4=1 runs the window's vtbl+0x30 painter BEFORE returning. A thunk that stores a value in a cave cell, calls the resize, then reads the cell back is only safe if no thunk the painter can reach writes that cell.

Case (2026-09-24, fixed in exe c6202c3a, user-verified): t_rw_init_leave kept the ReportWin origin in g_rw_rect across the resize; t_rw_techpage (reached when g_reportwin_kind was still 2 = F2 last viewed at a game load) used g_rw_rect as restripe scratch -> every HQ report drawn at the F2 header rect origin, (-868,-124) at 4K, correctly sized, until the next load. Fix = a dedicated g_rw_tech_rect cell (carved from unused g_rw_fontscratch, layout-neutral) + test_rw_rect_owned_by_init_leave_only.

Second case (2026-10-17, fix pending verification): the same resize PAINTS THE PAGE of the persisted g_reportwin_kind (0x885F40, never reset at load). F3 last viewed + a load -> ReportWin_draw_energy built and SHOWED the energy ListBox on the hidden ReportWin; F4's teardown never closed it, so F3 rows sat over F4/F5/F7/F2. Fix = t_rw_init_leave brackets the resize with kind := -1 (painter's unsigned `ja` -> default case) and restores it. Lesson: never carry ANY state across the resize, including the page kind.
Related trap: RW+0xA14..+0xA20 is page scratch (ReportWin_tech_reset rewrites it on every paint); window H lives in RW+0x5990 (frame bottom). The F5/F7 rowdiv caves read +0xA20 and showed one row short.

**Why:** the clobber depends on persistent engine state (last report kind), so it looks like a random, non-reproducible placement bug.
**How to apply:** give every thunk its own scratch cell; when a wrong window position has the right size, check for a cell shared across a synchronous repaint before suspecting screen metrics. Related: [[project-smac-report-screens]], [[feedback-shared-field-one-owner]].
