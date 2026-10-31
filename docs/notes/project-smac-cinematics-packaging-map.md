---
name: project-smac-cinematics-packaging-map
description: End-to-end map of the cinematic pipeline + exactly what a future end-user packager must bundle (and what stays dev-only)
type: project
---

Written 2026-07-01 for the upcoming END-USER PACKAGER. Two disjoint halves — the packager ships
only the second:

**DEV-ONLY (never shipped): the HD-pack producer.** `work\video-upscale\build_hd_pack.py` +
`pipeline.ini` (+ gitignored drop-ins `work\video-upscale\tools\`: full encode ffmpeg +
realesrgan-ncnn-vulkan + models; needs a Vulkan GPU). Per clip: decode .wve→PNG → Real-ESRGAN x4 →
re-encode H.264 CRF20 yuv420p + AAC, fps preserved, frame-count verified. Model choices are
RECORDED in pipeline.ini ([pipeline] default realesrgan-x4plus; 11 [clip:] overrides =
realesr-animevideov3), so a clean rebuild reproduces the shipped pack exactly. Output lands in
`dist\movies-hd\` (61 clips, 1.3 GB). Also dev-only: `tools\ffmpeg-8.1` source + `tools\msys64` +
`tools\build_ffmpeg_slim.sh` / `tools\run-build-ffmpeg-slim.bat` (produce the runtime DLLs below;
asm MUST stay enabled — [[feedback-ffmpeg-slim-needs-asm]]).

**SHIP SET (what the packager bundles).** The installer (`work\run-install.bat` →
`work\scripts\install.py`, branded "Longevity Vaccine") consumes these repo paths — a packager
either preserves this layout or rewrites the constants at the top of install.py:
- `work\scripts\` — install.py + apply_patches.py + config.py + `work\patches\patches.yaml`
  (install.py imports apply_patches/config as MODULES; patch sets keyed by exe MD5: PRACX
  2d0b1438→full set, pristine cc659f→uimod_bootstrap_native group; already-patched detected via
  .bak MD5; --force = restore+re-patch).
- `tools\python\` — the bundled Python that run-install.bat invokes (`%~dp0..\tools\python\`,
  repo-root-relative). NOTE: run-install.bat also sets JAVA_HOME (copied from the other run-*.bat
  wrappers) — the installer does NOT need Java; a packager can drop that.
- `src\uimod\build\Release\uimod.dll` — the in-process player (hooks amovie 0x403BE0).
- `src\uimod\third_party\ffmpeg\bin\*.dll` — the 5 slim x86 runtime DLLs (avcodec-62, avformat-62,
  avutil-60, swresample-6, swscale-9; ~7 MB total). MUST be the asm-enabled build (verify: extract
  the configure string embedded in avutil-60.dll — no `--disable-asm`). After any ffmpeg-slim
  rebuild these copies must be refreshed from `tools\ffmpeg-slim\bin\` by hand.
- `dist\movies-hd\*.mp4` — the HD pack (gitignored! lives only on the dev box / release artifact —
  a packager must take it from a build, not from git).
- `work\CHANGELOG.md` — ships with the release (player-facing, per project convention).

**Install-time actions** (what the packager's payload must be able to do = what install.py already
does): patch exe(s) by MD5 with .bak backup; copy uimod.dll + 5 DLLs beside the exe; copy pack →
`<game>\movies\hd\`; write `[UIMod] UpscaledVideos=1` in `Alpha Centauri.ini` (Win32
WritePrivateProfileStringA to preserve the file). Game dir resolves SMACX_GAME_DIR >
work\game-path.txt > autodetect (config.py).

**Runtime contract** (why those files suffice): uimod.dll's BuildSourcePath plays
`movies\hd\<name>.mp4` when the ini flag is on and the file exists, else falls back to
`movies\<name>.wve` (live-upscaled) — so a partial/missing pack degrades gracefully, and
UpscaledVideos=0 is the clean opt-out. XAudio2_9 is an OS component (Win10/11) — nothing to ship.

**NOT needed by end users:** Ghidra, JDK, msys64, ffmpeg-8.1 source, ffmpeg-slim build tree,
video-upscale tools/eval, Frida/tests, refs\. A release zip is roughly: installer scripts +
patches.yaml + bundled python + uimod.dll + 5 DLLs + movies-hd + CHANGELOG.
