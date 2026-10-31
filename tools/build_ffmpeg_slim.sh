#!/usr/bin/env bash
# Build a minimal x86 shared ffmpeg with MSVC (cl), for uimod.dll.
# Run from an x86 vcvars (cl/link/lib on PATH) with MSYS2_PATH_TYPE=inherit.
# Only the codecs uimod needs: eatqi (.wve video), adpcm_ea (.wve audio), h264 + aac (AI mp4).
set -e

# MSYS coreutils ships /usr/bin/link.exe which shadows MSVC's link.exe -> rename it once.
if [ -f /usr/bin/link.exe ]; then mv -f /usr/bin/link.exe /usr/bin/link-coreutils.exe; fi

cd /d/SmacxUi/tools/ffmpeg-8.1
echo "=== toolchain ==="; which cl link lib nasm || true

# Config changed (asm re-enabled) -> force a clean reconfigure.
make distclean >/dev/null 2>&1 || true

# NOTE: asm (nasm SIMD) is REQUIRED for performance -- a --disable-asm build decodes the
# 4x-upscaled H.264 pack far below 15fps (pure-C h264 + swscale). Needs nasm on PATH.
./configure \
  --toolchain=msvc --target-os=win32 --arch=x86 \
  --enable-shared --disable-static \
  --disable-programs --disable-doc --disable-avdevice --disable-avfilter \
  --disable-network --disable-everything \
  --enable-decoder=eatqi,h264,adpcm_ea,aac \
  --enable-demuxer=ea,mov \
  --enable-parser=h264,aac \
  --enable-protocol=file \
  --prefix=/d/SmacxUi/tools/ffmpeg-slim

echo "=== configure OK, building ==="
make -j8
make install
echo "=== BUILD COMPLETE ==="
ls -la /d/SmacxUi/tools/ffmpeg-slim/bin/*.dll
