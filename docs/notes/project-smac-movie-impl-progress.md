---
name: project-smac-movie-impl-progress
description: Live build progress for the unified in-app movie player (uimod.dll) — spikes done, what's next
type: project
---

Implementation of the in-process cinematic player plan
(unified in-process cinematic player for PRACX + pristine; see [[project-smac-movie-player]] for the
RE, [[feedback-no-external-movie-player]] for the hard in-process constraint). Started 2026-06-28.

**ALL 3 SPIKES DONE + verified:**
- SPIKE A (PRACX intercept + GDI present): in `src\uimod\src\movie.cpp` + wired from `init.cpp`.
  `InstallMovieHook(pracx)`: PRACX -> re-point rel32 @0x403BE1 to `uimod_PlayMovie`; native -> lay
  down E9+rel32 at 0x403BE0. `uimod_PlayMovie(const char*)` (__cdecl, matches PRACXShowMovie).
  Present = compose full-screen back buffer (black + aspect-fit StretchDIBits) once, single BitBlt
  per tick to GetDC(phWnd); fit rect = min(SW/sw,SH/sh) center from ScreenWidth*0x9B7B1C /
  ScreenHeight*0x9B7B20; phWnd*0x9B7B28. Pump+DISPATCH msgs (alt-tab/activation) but EAT
  WM_PAINT/WM_ERASEBKGND (else game repaints over us = flash) + consume skip keys. USER-VERIFIED
  in-game @4K: card correct, no flash, no res change, alt-tab OK, ESC/click skip.
- SPIKE B (pristine present): SAME GDI path works on pristine (terranx.exe, DirectDraw=1 1024x768,
  DDrawCompat) -> NO separate DDraw backend needed. DDrawCompat's GDI hook redirects our blit onto
  the game's 1024x768 surface then bilinear-upscales to desktop. Pristine is 4:3 so the movie fills
  the 4:3 region (pillarboxed by DDrawCompat) -> OWNER ACCEPTED "pristine is 4:3". No res change,
  skip+alt-tab OK. To get uimod into pristine WITHOUT patching, built `src\uimod\tools\inject_uimod.exe`
  (x86; CreateProcess(suspended terranx.exe) -> remote LoadLibrary(uimod) -> remote call Init -> resume).
- SPIKE C (x86 libav decode): `src\uimod\tools\spike_decode.cpp` (x86) decodes BOTH movies\*.wve
  (container `ea`, video `eatqi`, audio `adpcm_ea` 22050 st) AND an h264/aac mp4 to BGRA via swscale.
  Visually confirmed correct frames. So one libav path reads original + AI assets.

**ffmpeg dep (owner chose prebuilt now):** x86 LGPL-shared from defisym/FFmpeg-Builds-Win32
`ffmpeg-n8.1-latest-win32-lgpl-shared` (sha256-verified) extracted to `src\uimod\third_party\ffmpeg`
(bin/ DLLs avcodec-62/avformat-62/avutil-60/swscale-9/swresample-6, lib/ import .libs, include/).
GITIGNORED (`src/uimod/third_party/`). avcodec alone ~40MB -> SLIM via a custom-built decoder-only
ffmpeg before final ship (re-source provenance too). Build = VS2022 `build.bat`; tools built via
vcvars32+cl (note: vswhere-not-found warning is harmless).

**Deploy:** `uimod.dll` (Release) is manually copied to the game dir beside prax.dll. The CURRENTLY
deployed build still shows the SPIKE-A TEST CARD for movies (not real video yet) — will be replaced
when the real decoder lands. Safe revert if needed: delete game-dir uimod.dll.

**REAL PLAYER DONE + USER-VERIFIED in-game on PRACX (2026-06-28): video + audio.** All in
`src\uimod\src\movie.cpp` (`DecodeAndPlay`): libav opens movies\<name>.wve or movies\hd\<name>.mp4
(per [UIMod] UpscaledVideos in Alpha Centauri.ini, read via GetPrivateProfileInt off the exe dir);
video decode -> sws_scale BGRA into the aspect-fit sub-rect of a full-screen back buffer -> single
BitBlt/tick to GetDC(phWnd); 15fps wall-clock pacing (avg_frame_rate, fallback 15); audio decode ->
swr to S16 stereo -> XAudio2 source voice (submitted from the same packet loop, paced by the video
frame waits so A/V stays synced); ESC/click/Space/Enter skip; PostMessage WM_MOVIEOVER on PRACX.
BUILD wiring: uimod.vcxproj links third_party\ffmpeg import libs + xaudio2.lib, with
ImageHasSafeExceptionHandlers=false (mingw libs aren't SAFESEH). Deploy = uimod.dll + the 5 ffmpeg
DLLs in the game dir (XAudio2_9 is built into Win11). Opening cinematic confirmed perfect: real
video+sound, aspect-fit, NO desktop res change, no playuv15, skippable, alt-tab-safe.

**SLIM ffmpeg DONE 2026-06-28: ~73MB -> ~7MB** (avcodec 40->2.3MB). Custom x86 build via
`tools\build_ffmpeg_slim.sh`: MSYS2 (contained at `tools\msys64`, base sfx; `pacman -S make diffutils`)
as the build shell + ffmpeg 8.1 src at `tools\ffmpeg-8.1`, configured `--toolchain=msvc --arch=x86
--target-os=win32 --enable-shared --disable-static --disable-everything --disable-asm --disable-
programs/doc/avdevice/avfilter/network --enable-decoder=eatqi,h264,adpcm_ea,aac --enable-demuxer=ea,mov
--enable-parser=h264,aac --enable-protocol=file`, installed to `tools\ffmpeg-slim`. Run from x86 vcvars
with MSYS2_PATH_TYPE=inherit. GOTCHAS: (a) rename MSYS `/usr/bin/link.exe` so MSVC link wins (script
does it); (b) `--disable-postproc` is NOT a valid flag (postproc off by default); (c) MSVC `make install`
puts import .libs in **bin/** not lib/ (script/our copy moves *.lib bin->lib so the vcxproj lib path
holds); (d) --disable-asm => swscale uses C colorspace path ("no accelerated conversion" info, harmless);
(e) av_version_info() shows the SmacxUi git hash because built inside the repo tree (cosmetic). Slim DLLs
verified decode .wve+.mp4 via spike_decode. third_party\ffmpeg now holds the slim build (gitignored).
uimod.dll relinked + slim DLLs deployed. PENDING: user re-verify opening plays in-game with slim DLLs.

**PRISTINE PRESENT (#8 movie quality) DONE + USER-VERIFIED in-game 2026-06-28.** On pristine the
game's ddraw.dll is DDrawCompat, which hooks GDI process-wide and redirects EVERY screen BitBlt
(ours included) onto the game's emulated 8-bit paletted 1024x768 surface -> the GDI present path
gave salt-and-pepper dither + wrong colours, and UpdateLayeredWindow (bypasses the GDI hook, DWM
composite) was far too slow at 4K (atrocious frame rate). FIX = give the PRISTINE path its OWN
true-colour `IDirectDraw7` exclusive-fullscreen device (the game's blessed route), mirroring the
native movie player: `DDrawPresenter` in movie.cpp -> DirectDrawCreateEx(IID_IDirectDraw7) ->
SetCooperativeLevel(phWnd, DDSCL_EXCLUSIVE|DDSCL_FULLSCREEN) -> SetDisplayMode(gameW,gameH,32) ->
CreateSurface(PRIMARY); Present = Lock(WRITEONLY) + memcpy BGRA rows (handle SURFACELOST=Restore).
Decode stays SWS_BILINEAR at GAME res (DDrawCompat upscales to desktop). Present ONCE per frame
(an early bug presented ~6-7x/frame inside the wait loop = frozen). PRACX path UNCHANGED (still
GDI BitBlt -- PRACX presents via GDI, no DDrawCompat 8-bit trap there).
**TEARDOWN RECIPE (the load-bearing fix):** releasing our DDraw device is NOT enough -- the game
never re-sets its own mode after a movie, so the screen stayed tiny/black/desktop-showing. The
native teardown movie_ddraw_fs_teardown (0x4BF400) is: RestoreDisplayMode -> Release(surface) ->
Release(ddraw) -> **Win_set_display_mode(gameW,gameH,8,0)** (0x5F2C40, __cdecl, wraps
GraphicsMgr_set_mode 0x635510 on graphics mgr @0x9BE618). That final call RE-RUNS the game's
video-mode init and is MANDATORY. DDrawPresenter::End() mirrors it exactly. Symbols recorded in
terranx.h (movie_ddraw_fs_teardown / Win_set_display_mode / GraphicsMgr_set_mode).

**PRISTINE LOADER (#8) DONE + USER-VERIFIED 2026-06-28: built + applied + in-game confirmed.**
Pristine cc659f has no PRACX stub to chain off, so we install uimod's loader exactly the way PRACX
installs its own (diffed the PRACX base vs pristine = only 45 bytes: a "prax" loader stub @0x668160
+ a .data ptr @0x682000). The pristine binary's 0x682000 is the MSVC C++ initializer table
(_initterm pfbegin..pfend = 0x682000..0x6826cc; walker _initterm @0x644ED8 SKIPS null entries),
and entry[0] is NULL. So: (a) write the SAME 41-byte uimod loader (thunk_uimod_loader bytes, fully
position-independent) into the free RWX _SELFMOD slot @0x668160; (b) set table entry[0] @0x682000
= 0x668160. _initterm calls it at CRT startup -> LoadLibraryA("uimod")->Init; no PRACX -> Init takes
the native path (writes its OWN E9 movie hook @0x403BE0). NO code cave / section append needed (both
writes land in existing space). Implementation: patches.yaml group `uimod_bootstrap_native` (2 sites
+ symbol uimod_native_stub), both `skippable` so the default PRACX apply leaves them untouched (their
original_bytes don't match the PRACX base = calmly skipped; PRACX "Will write" stays 135 sites). New
opt-in `run-apply-patches --pristine` (apply_patches.py: swaps EXPECTED_MD5->cc659f, defaults target
to game-dir\terranx.exe, restricts to the native group). Applied: pristine terranx.exe cc659f ->
**56bc481b** (.bak backup written; terranx_pristine.exe is an untouched reference copy). Layer-1
tests green (added test_native_loader_sites_verify_pristine + pristine fixtures in conftest; base
test now excludes the native group). Symbols _initterm/uimod_native_stub added to terranx.h.
VERIFIED in-game on pristine: uimod.log "no PRACX -> standalone mode" + "movie hook installed", a
cinematic plays true-colour + smooth via the DDraw presenter, and the game returns to full screen
cleanly when it ends. #8 fully CLOSED.

**ASSET PIPELINE + INSTALLER (#10) DONE 2026-06-28: built + verified (real codec), pending in-game AI check.**
Decided WITH owner: ship the upscaled files; AI-upscale runs OFFLINE on
the dev box, users get only finished .mp4 (no upscaler/GPU dep). Upscaler = Real-ESRGAN ncnn-vulkan default
but SWAPPABLE via config (dev-only knob). Codec = H.264 (runtime decoder already supports -> zero runtime
change). Installer = CLI wizard.
- **Pipeline (dev-only):** `work\video-upscale\build_hd_pack.py` + `pipeline.ini` + `work\run-build-hd-pack.bat`
  + README. Per clip: ffmpeg decode .wve->PNG -> configured UpscaleCmd ({in}/{out}/{scale}/{model}) ->
  ffmpeg encode frames+orig audio -> `dist\movies-hd\<name>.mp4` (libx264 crf18 yuv420p + AAC, fps preserved,
  frame-count verified end-to-end). Idempotent (skip built unless --force). MIX MODELS via --only/--list
  subsets AND `[clip:<name>]` override sections (resolve clip-override -> [pipeline] default). Tools (full
  ffmpeg + realesrgan-ncnn-vulkan + models) are gitignored drop-ins in `work\video-upscale\tools\`. VERIFIED real
  end-to-end with the system's full ffmpeg (a full ffmpeg 8.1 build) + a passthrough "upscaler": logo 135/135 frames,
  gaians 111/111, h264+AAC22050 stereo, idempotent skip + selective --force all correct.
- **Installer:** `work\scripts\install.py` + `work\run-install.bat`. Detects exe(s) by MD5, patches via the
  apply_patches MODULE (PRACX full set / pristine native-loader group), handles ALREADY-PATCHED (skip; --force
  = restore .bak + re-patch), deploys uimod.dll + the 5 slim ffmpeg DLLs, prompts AI (--ai on/off/ask) ->
  copies dist\movies-hd -> game movies\hd + writes [UIMod] UpscaledVideos via Win32 WritePrivateProfileString
  (preserves the ini). VERIFIED against a throwaway game-dir copy: already-patched idempotency, --force restore
  +re-patch reproduced the live patched MD5s byte-identical (0b81d7a8 / 56bc481b), pack copy, ini write. Layer-1
  tests stay green (119 pass).
- **Upscaler installed + model CHOSEN 2026-06-28:** Real-ESRGAN ncnn-vulkan (xinntao/Real-ESRGAN v0.2.5.0
  20220424 windows build) extracted to `work\video-upscale\tools\realesrgan\` (exe + models: realesr-animevideov3,
  realesrgan-x4plus, realesrgan-x4plus-anime; NO realesrnet in this build). Full ffmpeg (8.1.1 static)
  copied to `tools\ffmpeg\bin\`. A Vulkan GPU is enough. GOTCHA: realesrgan finds models\ relative to CWD,
  so build_hd_pack runs the upscale step with cwd=exe dir (added). Added `--model`/`--out` CLI overrides (force one
  model across clips into its own folder) for A/B sweeps. SWEEP: 3 models x 4 clips (citizensDefense/cloningVats/
  dreamTwister/opening, all 400x192->1600x768 @ x4) all frame-count-exact; built a labeled side-by-side of `opening`
  (x4plus | animevideov3). **Owner picked realesrgan-x4plus across all clips (crispest)** -> now the [pipeline]
  default in pipeline.ini + code fallback. x4plus is x4-ONLY so Scale=4. x4plus produces the LARGEST files (most
  synthesized detail) -> watch full 61-clip pack size (HEVC/AV1 trigger). Eval outputs in dist\eval\ (gitignored; whole dist\ now ignored).
- **Full pack built + CRF settled 2026-06-28:** all 61 clips at x4plus/CRF18 = 1.8 GB, PRESERVED at
  `dist\movies-hd-crf18\`. CRF A/B (18|20|22 side-by-sides in dist\eval) → user picked **CRF 20** ("20 is free",
  ~−21% → ~1.4 GB). OPEN (see the maintainer's work log "pack QA — RESUME HERE"): (a) pick a non-x4plus model for
  `citizensDefense` + `xenoempathyDome` (animevideov3 vs x4plus-anime A/B — queued),
  (b) re-export full pack at CRF 20 with the per-clip overrides, (c) re-verify the other disliked clips
  (asceticVirtues/close_ct/close_us/commandNexus/longevityVaccine/networkBackbone/neuralAmplifier/selfAwareColony),
  (d) deploy + in-game check. pipeline.ini still says Crf=18 → set 20 or pass --crf 20.
- REMAINING (#10 final / Layer-3): finish the pack QA above, then run-install.bat,
  then the human in-game check (PRACX + pristine, 4K + non-4K, AI clip sharper + aspect-fit + no res change +
  skip + clean return; UpscaledVideos=0 fallback to .wve). Measure full 61-clip pack size (trigger for HEVC/AV1,
  which would need a slim-ffmpeg decoder rebuild). THEN add the player-facing CHANGELOG line.
**(11) CHANGELOG done for the PRACX+pristine player; symbols n/a for the pure tooling.**
NOTE: adpcm_ea has a quirky final packet the CLI warns on during transcode — our decode loop ignores
per-frame errors fine.

**PACK QA DONE + DEPLOYED 2026-06-29..07-01 (see [[project-smac-cinematics-packaging-map]] for the
ship-shape summary):** CRF 20 chosen; 11 clips overridden to realesr-animevideov3 (recorded as
[clip:] sections in pipeline.ini); final pack = 61 clips / 1.3 GB at dist\movies-hd (CRF-18 all-x4plus
alternate kept at dist\movies-hd-crf18). Eval + reference videos deleted (~3.4 GB). Installer rebranded
"Longevity Vaccine" (banner + double-click pause). User deployed + played: HD clips were CHOPPY →
root cause = slim ffmpeg's --disable-asm + single-threaded decode (see
[[feedback-ffmpeg-slim-needs-asm]]). FIXED (asm rebuild + movie.cpp thread_count=0/FRAME|SLICE,
commit 9d0b9c2) — user confirms smooth on PRACX @4K. Layer-3 COMPLETE 2026-07-01: user confirmed
PRACX + pristine, 4K + non-4K. **#10 CLOSED — the whole movie feature (player + pack + installer)
is DONE + user-verified. Nothing remaining.**
