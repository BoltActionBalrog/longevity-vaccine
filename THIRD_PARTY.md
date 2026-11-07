# Third-party components

The Longevity Vaccine builds on, links, or takes names from the following. None of their code
is redistributed in this repository unless stated; the installer ships the binaries named below.

| Component | Use | Licence | Where |
|-----------|-----|---------|-------|
| **FFmpeg** (libavcodec, libavformat, libavutil, libswscale, libswresample) | The in-game movie player decodes the HD cinematics through a slim build of these libraries, loaded as separate DLLs beside `uimod.dll`. | LGPL-2.1-or-later. The libraries are dynamically linked and unmodified; `tools/build_ffmpeg_slim.sh` reproduces the exact build (configure flags included) from the FFmpeg 8.1 source with MSVC, MSYS2 and nasm. The README's build section gives the steps, so the libraries can be rebuilt and replaced. | https://ffmpeg.org |
| **Thinker** by Induktio | Function and global names for the game binary (`work/symbols/terranx.h` marks each entry's origin: `thinker`, `observed` or `guess`). No Thinker code is included. | GPL-2.0 | https://github.com/induktio/thinker |
| **PRACX** by Draz | The mod targets the PRACX-patched binary and patches one PRACX behaviour (`work/patches/patches_prax.yaml`); `work/symbols/prax.h` names its functions from the published source. | See the PRACX repository | https://github.com/DrazharLn/pracx |
| **Real-ESRGAN** (ncnn Vulkan build) | The HD cinematics pack is produced by upscaling the game's movies with it (`work/video-upscale/`). The tool is fetched, not committed; nothing of it ships to players. | BSD-3-Clause | https://github.com/xinntao/Real-ESRGAN |
| **Turovetsky's HD Portrait Pack** (art by Turovetsky) | The optional portraits-hd pack: the artist's 14 leader portraits, cropped to the game's portrait framing by `work/scripts/art/build_portraits_hd.py`. The images are not in this repository; the pack carries them with `PROVENANCE.txt`. | GPL-3.0-or-later, confirmed by the artist (2026-11-06). Credit required: Turovetsky, https://www.youtube.com/@Turovetsky, https://x.com/turovetsky | https://x.com/turovetsky |
| **Python** (CPython 3.12) | The installer ships a trimmed CPython runtime. Manifests are Ed25519-signed and verified with a pure-Python implementation (`work/scripts/ed25519_verify.py`, RFC 8032); no third-party crypto package is used on either side. The runtime carries CPython's own bundled components as shipped by python.org (OpenSSL for HTTPS via `_ssl`/`_hashlib`, libffi, zlib, bzip2, liblzma, SQLite); their notices are in the `LICENSE.txt` that ships with the runtime. | PSF-2.0 (+ the bundled components' own licences, in CPython's LICENSE.txt) | https://python.org |
| **Python** (CPython 3.8.10, Windows embeddable package, 32-bit) | A second, unmodified interpreter for Windows 7 and 8, where CPython 3.12 cannot start; it runs the same installer scripts. Fetched and hash-verified by `work/scripts/fetch_python38.py`; ships as `tools/python38`. | PSF-2.0 | https://www.python.org/downloads/release/python-3810/ |
| **Microsoft Universal C Runtime** (app-local, x86) | `ucrtbase.dll` and the `api-ms-win-crt-*` forwarders from the Windows SDK's `Redist\ucrt` folder, placed beside the 3.8 interpreter so it starts on a Windows 7 that never took update KB2999226. Ignored by Windows 10 and later. | Microsoft Windows SDK licence (redistributable component) | https://learn.microsoft.com/windows/win32/apiindex/windows-apisets |
| **Capstone**, **Keystone**, **Unicorn**, **pefile**, **PyYAML**, **Frida**, **Ghidra** | Development and test tooling only: disassembly, assembly, emulation parity tests, PE parsing, live tracing, decompilation. | BSD-3 / GPL-2 (Keystone) / GPL-2 (Unicorn) / MIT / MIT / wxWindows / Apache-2.0 | respective projects |
| **NumPy**, **SciPy**, **Pillow**, **pytest**, **pytest-xdist**, **pyghidra**, **Node.js**, **NASM**, **MSYS2** | Development and test tooling only: pixel measurement and emulation checks, the test runner, the Ghidra bridge, the JavaScript parity tests, the ffmpeg build. Nothing of them is redistributed. | BSD-3 / BSD-3 / MIT-CMU / MIT / MIT / Apache-2.0 / MIT / BSD-2 / BSD-3 (MSYS2 runtime: LGPL/GPL) | respective projects |

*Sid Meier's Alpha Centauri* and *Alien Crossfire* are © Firaxis Games / Electronic Arts. This
project modifies a copy the player already owns and redistributes none of the game's files. Three
small excerpts exist as anchors only: the byte patterns in `patches.yaml` that locate the patch
sites, the stock Datalinks lines `work/scripts/patch_helptext.py` asserts before it replaces them,
and the 256-colour palette of the game's popup art that our own logo `work/art/longevity_sm.pcx` is
quantised to so the game can draw it.
