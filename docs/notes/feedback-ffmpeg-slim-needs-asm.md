---
name: feedback-ffmpeg-slim-needs-asm
description: slim runtime ffmpeg MUST be built with asm (nasm SIMD) + player must use threaded decode, else HD H.264 clips play far below 15fps
type: feedback
---

The slim runtime ffmpeg for uimod.dll was originally built `--disable-asm` (pure-C): fine for
320×240 .wve (eatqi) but the 4×-upscaled H.264 pack (1280×960–2368×1152) dropped far below 15fps
at 4K. Two-part fix (2026-07-01, user-confirmed smooth):

**Why:** pure-C h264 + swscale with a single decode thread can't hold 15fps on multi-megapixel
frames; the .wve path masked it because the sources are tiny.

**How to apply:**
- Build ffmpeg-slim WITHOUT `--disable-asm` (needs nasm — installed in bundled msys64 via pacman).
  Driver: `tools\run-build-ffmpeg-slim.bat` (vcvars32 + MSYS2_PATH_TYPE=inherit → build_ffmpeg_slim.sh,
  which now does `make distclean` + has a comment forbidding --disable-asm).
- movie.cpp sets `ctx->thread_count = 0; ctx->thread_type = FF_THREAD_FRAME|FF_THREAD_SLICE` before
  avcodec_open2.
- After any ffmpeg-slim rebuild, copy `tools\ffmpeg-slim\bin\*.dll` into
  `src\uimod\third_party\ffmpeg\bin\` (the installer's deploy source) or end users keep getting the
  old DLLs — this exact miss caused a "re-ran installer, no dice" round-trip.
- Verify a build's flags by extracting the embedded configure string from avutil-60.dll.

See [[project-smac-movie-impl-progress]].
