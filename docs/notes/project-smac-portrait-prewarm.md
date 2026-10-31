---
name: project-smac-portrait-prewarm
description: Background pre-bake of the HD leader portraits (uimod prewarm.cpp): DONE, all fixes landed and user-confirmed 2026-10-15 (branch feat/portrait-prewarm 36319c5, merged into master as commit diffs). Measured facts about the picker, the palette timing and the sheet model live here.
type: project
---

Brief: work/briefs/portrait-prewarm-brief.md (user decision 2026-10-14: option 1, pre-bake on a worker at startup).
Branch feat/portrait-prewarm (worktree in the scratch files; DLL-only, no exe bytes, no patches.yaml). The DLL built
from it is uimod.dll ef3fda71 (lacks the master tree's UNCOMMITTED changes, e.g. modernctl.cpp: rebuild after merging).

**Measured (do not re-derive):**
- The faction picker draws the DIPLOMACY slot (131x157) at g/16 through thunk_art_reblit (dest y=30 at 4K); Datalinks the
  datalink slot; the council the two council slots. All leader-slot draws pass num = g_popup_scale_num, den = 16.
- g_main_palette is NOT loaded at Init; it is loaded before the first load_faction_art and identical at every later load and
  draw (every portrait dest table == it). So the snapshot is taken at the first hook call.
- Engine loads the 7 ini factions at startup (read_factions, caller 0x5871ae) and again at game start (0x5aaef1); the other
  SMACX factions load on the picker's roster change. Vanilla slot sprites = <faction>.pcx rect (load_faction_art literals:
  small council 0x58,0x1C9 96x115; big 0xB9,0x1C9 118x144; diplomacy 0x130,0x1C9 131x157; datalink 0x213,1 164x198) with
  every index (raw + 10) & 0xFF (Buffer_load_pcx; key 9 = raw 255) -- verified bit-exact on all 28 Phase-0 sprite hashes.
- Cost split (HIVE.png, live palette, /O2): decode 36 ms; native bake = resample ~25 + dither 13..39 ms per slot; enlarge
  diplomacy 4K 34 + 150 ms, datalink 41 + 237 ms (1600x1200: ~40 + 58..92; 1080: ~28 + 45..72).

**How to apply:** the cache is keyed on every FromRgb input (image id, crop, size, palette, scan mode, bright, ratio, phase,
rows) -- a change is a miss, never stale. The toggle of Add Scanlines (Brighten removed 2026-10-30: MEAN always) must NOT invalidate (the mode is in the key;
native bakes of the current mode AND the other reachable one (off <-> MEAN) are pre-baked; the overlay mode is unreachable since Brighten Scanlines went, 2026-10-30, and is no longer baked). A leader-slot draw at another num/den relaunches with that scale (display-mode change).
Worker never logs through the ring except its own lines; portrait_files' decode lines come from whichever thread decodes.
Audit 2026-10-15 (independent pass): no crash/hang/wrong-picture path; its three functional findings were fixed (re-key
rebuilds a finished slot + restarts the worker; no scan-mode invalidate; null/edited image = drop not failure) plus
priority bump while waiting, try-lock in fault paths, leaked files cache, name cap = cache size (14).

**2026-10-15 user test:** the first deployed build (built from the master tree) pre-baked fine (log: 288 then 392 results, 31-60 s at 4K, 30.5 MB = near the 32 MB cap); user portraits were instant, but switching the HD pack on brought the delay back (another image set). User decision: relaunch the worker on EVERY portrait settings change (user portraits, HD pack, scanlines) -> commit c8acfe9: PortraitRebake -> prewarm::Restart(snapshot), generation-counted worker, keep still-valid results, revive dropped entries. Handed to the other checkout 2026-10-15. The other checkout's second audit (restart hand-off) found a palette race (job dithering while Restart swapped the snapshot palette -> fixed: palette copied per job), an orphaned-running-job path (fixed: ReapThread via the thread handle), lock-orphaned-by-SEH (fixed: bounded try-locks on every game-thread entry), restart storms (10 s rate limit), duplicate builds (every miss marks sTaken), cache thrash (20 slots), cap churn (drop before compute): commit 2b2af36, stress harness (concurrent restarts + palette + bad_alloc) 0 mismatches. Handed back 2026-10-15; the other checkout merged 2b2af36 into the master tree (portrait tests green there). DEPLOYED 2026-10-15 by the other checkout: uimod.dll 6a8111c0 (backup uimod.dll.cf5aac8a.bak). User test: still a short wait on the FIRST picker click: the log showed a 59 s run, 0 failed, no re-key, 1 result taken by the game thread = that click; the picker's enlarges came after all natives in all modes. Commit 6719145: picker-first tiers (loaded factions, current-mode natives, enlarges, other-mode natives last) + the draw phase per slot persisted in [UIMod] PortraitPrewarmPhases (read into the Snapshot at Start/Restart) + the other checkout's before-release items (event wait with bounded re-take, remembered dead state checked against the thread handle, reaper before waits, persistent failure count, exception-safe resample cache, Prereduce under SEH, bounded files lock with uncached fallback; sehfault + orphan tests). 6719145 DEPLOYED as uimod.dll d93b1fbf (backup uimod.dll.6a8111c0.bak); user to run the two-launch test (phase learned on launch 1). Third re-audit items -> commit 9b626ff (files lock latches only for a DEAD holder, owner tid recorded + boosted while waited; wait loop checks dead + reaps per slice; HotPhases lock-free via a dirty flag; no respawn after the failure stop; ini phase parse/format pure helpers; thunkfault/diewait/fileslock/phases tests). 9b626ff merged (not deployed). Fourth re-audit blockers -> commit 36881d0 (a files lock whose owner is the calling thread latches at once: an SEH-caught fault skips ~Locked; OwnerGone checks the owner's process (tid reuse); GetFit reads the worker handle only under the lock). 36881d0 merged and RELEASE-READY per the other checkout's re-audit (no blockers); the optional WorkerAlive handle race closed in 4b243f0 (merged, release-ready) and the recorded-id one-liner in 36319c5 (handed over). The DLL with the final code is built on master; the other checkout offers the deploy.

**2026-10-15 close:** the maintainer confirmed all portrait fixes landed. The branch's commits are the only committed history until master commits the merged diffs: keep feat/portrait-prewarm (and its scratch worktree) until then.

**Was open (user check list):** user check at 4K + one lower res: picker rows instant; portraits identical; diplomacy/Datalinks/council
identical; quit at the menu while pre-baking; Add Scanlines toggle then picker (natives hit, enlarges re-run once, ~0.2 s);
uimod.log "prewarm started/done" lines, DebugLog=1 shows hit/miss per lookup. After a settings change the enlarges for the
new mode / image set are rebuilt in the background (a few seconds at 4K); a click before that is a one-off sync bake. Pre-existing: test_apply_md5 fails at a clean master HEAD (the master tree's uncommitted patch work).
