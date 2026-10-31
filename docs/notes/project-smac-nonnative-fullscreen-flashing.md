---
name: project-smac-nonnative-fullscreen-flashing
description: Screen flashing / pixel jumps at 1600x1200 Fullscreen (2026-10-11) was the GPU driver outputting a 2560x1440@240 timing the test monitor runs badly; NOT our code; fixed by driver-side GPU scaling; player-side fix = no mode switch at non-native res
type: project
---

**Diagnosis (closed 2026-10-11).** Fullscreen at 1600x1200 flashed black and jumped pixels
continuously; 1920x1080 and 1024x768 were clean; Borderless ([UIMod] VideoMode=1) was clean.
The PRISTINE PRACX base (terranx_PRACX.exe.bak 2d0b1438, no uimod.dll) flashed identically,
so neither our exe patches nor the DLL were involved. G-Sync off changed nothing.

**Cause.** PRACX's SetVideoMode asks ChangeDisplaySettings for width x height only. The
The test monitor (4K, 240 Hz) lists no 1600x1200 timing, so with the GPU driver control panel
"Perform scaling on: Display" the driver scaled the 1600x1200 desktop into a
**2560x1440 @ 239.97 Hz** output timing (CCD target mode, scaling=aspect) and the monitor
upscaled that to 4K. That timing is what the monitor/link runs badly. 1920x1080@240 is a
timing the monitor lists directly, hence clean. Windows held the mode stable throughout
(no retrain logged), so the fault is inside the monitor/link at that timing.

**Fix on the test machine.** GPU driver control panel > Adjust desktop size and position > Perform scaling
on: **GPU** + **Override the scaling mode set by games and programs**. Cable then stays at
3840x2160@240 for any game resolution (verified 1600x1200 and 1920x1080). G-Sync can go back on.

**Tooling.** A scratch PowerShell script (not kept, not in the repo) polled QueryDisplayConfig
(CCD API: path target mode = the physical signal, active/total size, vsync rational, pixel clock,
scaling enum) + EnumDisplaySettings twice a second and logged every change. Recreate from this
description when a display-timing question comes up again.

**Player-facing fix on master (5086521 + audit fixes 319b935), uimod.dll 805ccf06 DEPLOYED 2026-10-11; USER-VERIFIED at 1600x1200 2026-10-11 (whole list clean, no flashing).** Follow-up found at the 4K check: in PRACX's own native-size Fullscreen the pointer walked onto the second monitor (PRACX never calls ClipCursor; pre-existing) -> SyncClip keys on `FullscreenRunning()` (m_fWindowed=0 or the scaled popup) and VidModePoll applies it at a native boot; then (user request) the Preferences "Large F4 Base Indicators" row was removed (ring always big; ini-only `[UIMod] BigF4Indicators=0` turns it off) and its place under the display-mode cells is "Constrain Mouse to Window" (`[UIMod] ConstrainMouse`, default 1, id 0x78; live, saved with OK, dimmed + inert outside Fullscreen in either form). PRACX has no pointer-confinement option of its own (checked). uimod.dll **ea621acb** DEPLOYED 2026-10-11 with the maintainer's approval (backup uimod.dll.805ccf06.bak = the only uimod backup left in the game folder after the 2026-10-11 clean-up; verify-bak ini deleted), built on branch `fix/fullscreen-no-modeswitch` (worktree `fullscreen-nomodeswitch`, commits ffed9fa + 6650b63, cherry-pick cleanly onto master); **USER-VERIFIED 2026-10-11 in full** (4K pointer/Prefs list, 1600x1200 scaled Fullscreen row, dev shortcut = real 1600x1200 + ini restored); both CHANGELOG lines APPLIED (CHANGELOG.md + website mirror, branch commit after a137cc4). Branch still needs cherry-picking onto master (integrated on master later). Capture note: `screenshot.py` grabs the window's desktop pixels, so only the dev shortcut (legacy switch) yields a shot at the game's own pixels; the ini route at a non-native size yields a 4K shot of the scaled picture. Audit fixes: SC_MAXIMIZE swallowed whenever m_fWindowed=1 (PRACX menu toggle ping-pong), SyncClip on every placement/activation change (clip lost after Alt+Tab), Init restore only when PRACX really switched; CHANGELOG line HELD until verified. Test `work\tests\test_prax_cds_binding.py` pins the prax.dll slot / prologues / 2 call sites. DPI: BUILT 2026-10-11 (integrated build: uimod.dll d04712a9 + exe cf920e8f from branch `integrate/fullscreen-no-modeswitch` 89e538f = master dcac16d + the bootstrap commit; the earlier branch-only builds de45f342 / f28250bf are superseded; NOT deployed -- live per the other checkout 2026-10-11: exe 5c239c65 + uimod.dll a1e98165) -- Init/PreInit call SetProcessDPIAware (run-time resolved; `[UIMod] DpiAware=0` opts out) before any window exists, the same thing the HIGHDPIAWARE compat flag did (the game folder's AppCompatFlags\Layers entries (HIGHDPIAWARE) were removed, the DLL owning DPI awareness; the game folder now has NO AppCompatFlags\Layers entries at all. Live after the other checkout's combined deploy: exe d4ff74d6 + uimod.dll cf7e2be5 (= my 89e538f + the other checkout's uncommitted SE stripes; backup uimod.dll.a1e98165.bak). USER-VERIFIED 2026-10-11 in full: 4K native Fullscreen with the flags gone + log "process set system-DPI-aware"; 1600x1200 ini boot with no monitor blank; dev shortcut's real switch intact. CHANGELOG: "no display switch ... at startup" + a DPI line. ALL COMMITTED + PUSHED by the other checkout as master 714c4df (verified: my files identical, site 0x668187, thunk_uimod_preload @0xD490, lock 276d8603 = the live exe; uimod.dll cf7e2be5 unchanged). Branches fix/fullscreen-no-modeswitch + integrate/fullscreen-no-modeswitch are fully contained in master: never cherry-pick them again; delete when convenient). Boot blank: BUILT 2026-10-11 (same DLL + exe bake f28250bf from the branch yaml, NOT deployed) -- two-phase bootstrap: group uimod_bootstrap now hooks the PRACX stub's `call eax; ret` at 0x668187 with thunk_uimod_preload (pcave2 0xD490; keystone src scripts\assemble_uimod_preload.py, Unicorn test tests\test_uimod_preload_thunk.py): LoadLibraryA("uimod") -> PreInit(hPrax) [export ordinal 2: VidModePreInit redirects prax's ChangeDisplaySettingsA slot BEFORE PRACXHook's SetVideoMode] -> PRACXHook -> Init. All degraded pairings (old DLL / old exe) fall back to one-phase. The shipping exe must be baked on MASTER after the cherry-pick (the branch yaml is behind master; patched_md5 re-lock). Intro-movie race CLOSED on reading: the movie loop pumps PeekMessage, so VidModePoll fires within its first frames and the present path re-stretches. Keystone gotcha: `;` is an instruction separator, not a comment (a `;`-commented source hangs it).
Default: at a non-native `[PRACX] ScreenWidth x ScreenHeight` Fullscreen is the scaled popup (m_fWindowed=1,
WS_POPUP, TOPMOST, cursor clipped, minimise on WM_ACTIVATEAPP(0)); prax.dll's ChangeDisplaySettingsA IAT
slot (+0x341BC) is redirected to a no-op; Init restores the desktop PRACXHook switched before we loaded.
`[UIMod] FullscreenModeSwitch=1` = PRACX's real switch (legacy path untouched); `run-at-resolution.ps1`
forces VideoMode=0 + FullscreenModeSwitch=1 per run so dev captures stay at the game's own pixels
(tests `work\tests\test_run_at_resolution.py`). Native-size Fullscreen stays PRACX's path. The one
possible blank at a non-native boot (PRACXHook's switch + our immediate restore) is fixed by the two-phase
bootstrap above once the exe is baked + deployed. Details and the verify lists: the maintainer's work log
(Display modes), [[project-smac-video-mode]].

**Test machine's GPU driver:** GPU scaling + override left ON (does not affect captures: the desktop mode is still the
game's; only the cable signal is native).
