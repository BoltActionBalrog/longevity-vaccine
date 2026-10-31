---
name: project-smac-video-mode
description: Fullscreen/Borderless/Windowed display-mode feature (uimod vidmode.cpp) — binds to PRACX's private SetWindowed/m_fWindowed by prax.dll offset; CLOSED 2026-09-19 user-verified 4K (DLL 7a66ea95), GPU scaler gpuscale.cpp
type: project
---

**State (2026-09-19): CLOSED, user-verified at 4K ("unable to find any issue whatsoever... fantastic"), DLL 7a66ea95;**
GPU path confirmed live in uimod.log, pristine exe logs "display modes disabled". Commits: 08350ce (first pass, CPU) + the GPU
commit after it. CHANGELOG has a "Display modes" section. Open follow-ups in the maintainer's work log (non-4K + letterboxed
Borderless + OBS not explicitly reported; pristine/Thinker support). prax.dll symbols: `work\symbols\prax.h`.
Motivation: content creators can't record the game (exclusive 8-bit DirectDraw; OBS Game Capture can't hook ddraw; no
built-in windowed mode). Diverges from pristine on purpose. User decisions: PRACX exe only in v1, default = Fullscreen,
live apply. Keep-PRACX decision: it still owns hi-res rendering, scrolling/zoom, overlays — we only replace narrow pieces.

**KEY LESSONS:** (1) PRACX windowed = whole-frame HALFTONE per flip; (2) the engine re-presents the FULL frame per mouse
move while a move path is drawn, so any CPU resample of a 4K frame (even 8 threads) is too slow -> GPU; (3) never
GDI-stretch per movie frame; (4) GetObject lies about DIB row order — ask the engine.

**Mechanism** (`src\uimod\src\vidmode.cpp`): PRACX already owns windowed mode but keeps it private + never persists it
(always boots fullscreen). We bind by offset to prax.dll (base 0x10000000), byte-checked (prologue `55 8B EC 6A FF`, the
`push 0x2CF0000` / `push 0x82000000` style immediates, and the relocated abs32 of m_fWindowed):
`SetWindowed(bool)` cdecl +0x9F60 · `m_fWindowed` BYTE +0x4809C · `m_fPlayingMovie` +0x4809E · `m_rWindowedRect` +0x480A0 ·
`m_pAC` +0x470E4 · `m_ptScreenSize.x` +0x48D80 · SetVideoMode +0x9ED0 · RestoreVideoMode +0x9940. Same in stock 89a0037b
and our patched 0f189a32.
- PRACX's StretchBlt present, ClientToBackbuffer mouse mapping and BeginPaint scaling are ALL gated on m_fWindowed — never
  restyle the window without that flag or you get a corner crop + offset mouse.
- Borderless = m_fWindowed=1 + WS_POPUP, not topmost, aspect-fit rect on the monitor + black backdrop window when
  letterboxed. SetWindowed(true) POSTS WM_USER+3 (SetWindowPlacement) — restyle only AFTER it (we subclass the WndProc and
  act right after forwarding WM_USER+3); inline restyle gets re-framed.
- PRACX saves the window placement into m_rWindowedRect whenever it leaves windowed — incl. our borderless rect →
  FixWindowedRect() restores the last good windowed rect (recognised by size) before any WM_USER+3.
- Detection = live (m_fWindowed + WS_CAPTION), never the ini; `[UIMod] VideoMode` 0/1/2 is boot-apply only, saved on OK as
  the DETECTED mode. Boot apply runs from the WH_GETMESSAGE hook (Init runs before the window exists).
- **Perf root cause (user: "very slow" in Windowed + Borderless, 2026-09-19):** PRACXWindowBitBlt (the E8 PRACX stamps at
  Win_flip_rect's display BitBlt 0x5F018B, `E8 rel32; nop`) IGNORES the dirty rect when m_fWindowed and HALFTONE-StretchBlts
  the WHOLE backbuffer on EVERY flip (4K 8bpp source = tens of ms per cursor move). v2 re-stamps that rel32 to our FlipBlt
  (we are last writer; gated on E8/90 + target inside prax.dll): 1:1 client -> plain BitBlt of the dirty rect; else stretch
  only the dirty rect (+1px source margin, dest = image of the source EDGES under the whole-frame map, <=0.5 px off).
- v4: dirty-rect HALFTONE was still a crawl while the MOVE-PATH LINE is drawn (engine flips the full frame per mouse
  move). ScaledFlip = our own resampler: reads the 8bpp backbuffer DIB (GetCurrentObject/GetObject DIBSECTION) + its colour
  table (GetDIBColorTable = what GDI blits with), separable area-average (shrink) / bilinear (enlarge) into a client-size
  32bpp DIB, per-axis WHOLE-FRAME tap tables (so dirty-rect output == full-frame output, no seams), RB/G packed 32-bit
  multiply-adds (x86-32: no 64-bit math), 16-slot horizontal row cache. GDI stretch only as fallback. Single-threaded; if
  still slow at 4K the next step is splitting rows across threads.
- v4b: GetObject(DIBSECTION).dsBmih.biHeight is POSITIVE for the engine's top-down screen DIB -> frame drew upside down;
  row order must come from the engine's screen Buffer height 0x9B7514 (negative = top-down).
- v5: resampler banded over a barrier-style Win32 thread pool (<=7 workers + game thread, per-thread row caches, only for
  updates >=200k px; pool created lazily, never under loader lock). User still found single-thread v4 'not good' on unit moves.
- v5 threads were STILL slow (user) -> v6 GPU scaler `src\uimod\src\gpuscale.cpp` (PRACX-agnostic; glue = ScaledFlip in
  vidmode.cpp). D3D11 via LoadLibrary (d3d11 + d3dcompiler_47, no static link), BLT-model DISCARD swap chain on the game
  hwnd (GDI BitBlt to the same window keeps working: movie player, 1:1 path; a flip-model chain would hide GDI), Present(0),
  MakeWindowAssociation NO_ALT_ENTER. R8 frame texture with dirty-box UpdateSubresource, 256x1 B8G8R8X8 palette (= RGBQUAD
  byte order) per flip, shader filters AFTER the palette lookup (area-average / bilinear = the CPU law). GpuInvalidate()
  whenever a flip bypasses the GPU (its frame texture goes stale). Any failure -> log line + CPU path for the session.
  Standalone smoke test `work\tests\gpuscale\run_smoke.bat`: PASS, exact palette colours, 1.4 ms per full 4K upload +
  present. Commit 08350ce = the pre-GPU checkpoint (pushed). v6 USER-VERIFIED in-game at 4K (no issues found; no
  DDrawCompat conflict observed).
- Persistence (user 2026-09-19: closed in Windowed, rebooted Borderless): save `[UIMod] VideoMode` on EVERY detected mode
  change (mode = window state), not only on Preferences OK. Supersedes the page's ESC = session-only rule for this row.
- Drag/size black flash = WM_ERASEBKGND before the (slow) repaint -> swallowed in the subclass while stretched.
- Live follow: subclass calls a prefs callback when the DETECTED mode changes (WM_USER+3 / WM_WINDOWPOSCHANGED /
  WM_STYLECHANGED); prefs redraws the cells only if PrefWin Win_is_visible (0x5F7E90) and our tab is active.
- Page order (user 2026-09-19): display-mode row FIRST, one blank row, then the option rows (kModeRow 0 / kOptRow0 2).
- Backbuffer (ScreenWidth/Height) never changes → g_popup_scale_num and all scaling untouched; resolution change stays
  restart-only ([PRACX] ScreenWidth/Height, PRACX's own dialog rewrites them).
- Our own code had to become stretch-aware: wheel.cpp hit-test (client→backbuffer); movie.cpp COMPOSES AT THE CLIENT SIZE when
  stretched (v3) so each frame is a plain BitBlt — a per-frame HALFTONE StretchBlt of a 4K 32bpp frame (even at 1:1) starved
  the single decode/audio loop: user saw very slow video + choppy audio in Borderless. Never GDI-stretch per movie frame.
- Prefs row: ids 0x66-0x68, three cells on one line, native x by `scaling_laws.pref_mode_cell_x` (cum). Tabs are on the LEFT
  (tabX=33); the page span is frameX=256, frameW=457 native. Exclusivity by hand — an engine ButtonGroup would overwrite
  PrefWin+0xA14 (current tab). See [[project-smac-prefwin-scaling]], skill prefwin-settings.

**INI facts:** `[Alpha Centauri] DirectDraw` + undocumented `Video Mode` are read in WinMain 0x45F9BB/CB and are a NO-OP
under PRACX (runtime stomp `xor esi,esi` @0x45F9D0; on disk it is still `mov esi,eax`). Vanilla's window is ALWAYS
WS_POPUP at GetSystemMetrics size — "fullscreen" is only whether Win_set_display_mode runs. Thinker's video_mode/
window_width are disabled when PRACX is present (reduced_mode). GOG `*_widescreen.bat` flips DirectDraw=0. DDrawCompat
(ddraw.dll, defaults) already turns pristine's exclusive mode into borderless+bilinear.

**Known/accepted:** boot into Borderless/Windowed with ScreenWidth != desktop flashes one mode switch (PRACXHook's
SetVideoMode precedes our Init). **Follow-up:** pristine/Thinker support needs our own windowed present path (ini-only).
Related: [[project-smac-movie-player]] (user hard req: no desktop res change), [[feedback-uimod-shared-dll-gate]],
[[project-smac-pracx-load-mechanism]].

**2026-10-11 Fullscreen without the display-mode switch (master 5086521 + audit fixes, uimod.dll 805ccf06 deployed 2026-10-11, NEEDS-GAME):** see
[[project-smac-nonnative-fullscreen-flashing]]. Detection gained a third live signal: m_fWindowed=1 + WS_POPUP +
WS_EX_TOPMOST = Fullscreen (scaled); `g_pendingPopup` (kVidBorderless / kVidFullscreen) replaces g_pendingBorderless and
stays set through ApplyPopup so the Prefs page never sees a transient Borderless. New prax.dll binding: ChangeDisplaySettingsA
IAT slot +0x341BC (RestoreVideoMode +0x9940 = `55 8B EC 6A 00 6A 00 FF 15 <slot>`, SetVideoMode +0x9ED0 =
`55 8B EC 81 EC 9C 00 00 00`). PRACX's toggles are intercepted in the subclass (Alt+Enter: WM_SYSKEYDOWN/WM_KEYDOWN
VK_RETURN with the Alt flag; SC_MAXIMIZE from Windowed); its menu item lands in m_fWindowed=0 and a posted kWM_Converge
(WM_APP+0x51) re-applies. Legacy exclusive path (`[UIMod] FullscreenModeSwitch=1`, or ScreenSize == monitor size) is
byte-for-byte the old behaviour, so the maintainer's 4K-on-4K daily config is unchanged.
