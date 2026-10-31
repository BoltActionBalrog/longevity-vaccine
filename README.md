# Longevity Vaccine — source

The Longevity Vaccine is a UI-scaling and HD-cinematics mod for *Sid Meier's Alpha Centauri /
Alien Crossfire* (the PRACX-patched GOG release). Players install it from
[longevitymods.com](https://longevitymods.com/vaccine/download); this repository is the source
it is built from, published for review and contribution.

Releases live under this repository's **Releases** tab. Each release tag (`v<version>`) points at
the exact source snapshot it was built from, and `SOURCE-MANIFEST.json` at the root lists every
file here with its SHA-256.

## What is here

| Path | What |
|------|------|
| `src/uimod/` | The in-process DLL (C++): high-resolution rendering hooks, display modes, the movie player, the update checker, preferences. `build.bat` builds it with Visual Studio 2022. |
| `work/patches/patches.yaml` | The binary patch set applied to `terranx.exe`: symbols, code-cave thunks, patch sites, grouped by screen or feature with the reasoning in each group's description. |
| `work/scripts/` | The patcher (`apply_patches.py`), the installer runtime that ships to players (`install.py` and its imports), the thunk assemblers (`assemble_*.py`), the scaling laws (`scaling_laws.py`, with a JavaScript port for live tracing), packaging (`release.py`, `sign_manifest.py`) and the reverse-engineering tools (Ghidra headless scripts and a curated subset of the Frida probes). |
| `work/tests/` | The regression suite: patch integrity, scaling-law sweeps, emulator parity of every thunk against the reference laws, installer end-to-end tests. |
| `work/symbols/terranx.h` | The confirmed symbol map of the game binary (addresses, signatures, struct fields). |
| `work/video-upscale/` | The pipeline that produces the HD cinematics pack. |
| `work/scripts/PROBES.md` | The catalogue of the Frida scripts: which only observe and which write to the game process. The writers are the runtime prototypes each fix was developed as before it was baked; read them, do not run them as they are. |
| `work/patches/_fragment_*.yaml`, `work/scripts/_hud_widgets_*.yaml` | The assemblers' committed output, so you can check that your run of an `assemble_*.py` reproduces the shipped bytes. |
| `docs/skills/` | Method notes on how the scaling work is done: measure vanilla, derive from the runtime scale, verify at several resolutions. Read `work/WHY.md` first. |
| `docs/notes/` | The engineering notes: the lesson behind each rule and the history of each screen, including what was tried and abandoned. A `[[name]]` link anywhere in this repository is the file `docs/notes/name.md` (an underscore in a link reads as a hyphen; `[[scaling-frames]]` and the other skill names are `docs/skills/`). Start at `docs/notes/README.md`. |
| `work/CHANGELOG.md` | The player-facing changelog that ships with the installer. |

### Not here, on purpose

Comments, tests and the skills cite these; they stay in the maintainer's private tree:

- **The release-publishing tooling** (`release_all.py`, `publish.py`, their launchers and tests):
  hosting layout and operator runbooks. `release.py` and `sign_manifest.py`, which build and sign
  the archives, are here; no key is.
- **Reference screenshots of the game** (`refs/pristine/...`, `_Problems/...`, "user shot ..."):
  Firaxis' art. The measurements taken from them are in the comments and the laws.
- **Analysis scratch**: most things named with a leading underscore (`work/_*_static_map.md`,
  `_*_dis_*.txt`, one-off `scripts/_verify_*.py`), disassembly and decompile dumps of the game,
  single-use probes that nothing cites, and the retired design briefs (`DLL_PORT_BRIEF.md`,
  `UPDATE_CHECKER_BRIEF.md`). A test that needs a dump skips and says so. The exceptions that
  ARE here: the assembler fragments, five small tools (`_disasm_live.py`, `_disasm_va.py`,
  `_callers.py`, `_whichfn.py`, `_cmb_dump_to_png.py`) and `work/_thinker_symbols_5.5.json`, the
  symbol map `thinker_locate.py` reads.
- **The maintainer's working files**: `CLAUDE.md` (the project's standing rules),
  `ACTION_ITEMS.md` (open work and build history), and the notes about publishing, hosting and
  the maintainer's own setup. The rules that matter to a contributor are the invariants below;
  the engineering notes are in `docs/notes/`.

### The invariants

1. Every change must look right and not crash at **any** resolution, not just 4K. Scale from the
   runtime value `g` (16 = native 1024x768 layout); at `g <= 16` the game must be byte-for-byte
   vanilla in behaviour.
2. Uniform scale only. The original 4:3 layout is never stretched per axis. The one exception
   is a sprite laid over a background the game itself already stretches.
3. Every scaled value is `vanilla × g/16`, measured from the unpatched game, never eyeballed and
   never scaled from an already-patched state.
4. `work/scripts/scaling_laws.py` is the source of truth; hooks and thunks are ports of it.
5. Dither and scanline patterns are regenerated at device density, never resampled.
6. Measure the engine; do not model it. Read the pixels or emulate the bytes.
7. No hardcoded game path or exe name: `work/scripts/config.py` resolves both.

## Building and testing

- **Clone to `D:\SmacxUi`.** The batch launchers under `work/` and the Frida probes carry
  that path; anywhere else works for the Python scripts called directly, not for the launchers.
- **Python** 3.12 with `capstone keystone-engine unicorn pefile pyyaml pillow numpy pytest
  pytest-xdist frida-tools pyghidra==3.1.0` (pyghidra only for the Ghidra scripts, and its version must match
  the Ghidra release). The launchers expect it at `tools/python/python.exe`, a full install, not
  a venv: install CPython 3.12 from python.org into `tools/python` (choose that location in the
  installer) or unpack the `python` NuGet package there, then `pip install` the list above.
  `work/run-frida.bat` runs `tools/python/Scripts/frida.exe`, which `frida-tools` provides. Ed25519 verification is pure Python (`work/scripts/ed25519_verify.py`); no crypto
  package is needed.
- **The game**: a PRACX-patched GOG install. Point the tools at it with `work/game-path.txt`
  (copy the `.example`). The patcher targets the binary with MD5 `2d0b1438` and keeps a `.bak`.
- **Ghidra 12.1 + JDK 21** under `tools/` as `tools/ghidra_12.1_PUBLIC` and `tools/jdk-21.0.11+10`
  (the launchers name those folders) for the decompilation scripts (optional; see
  `work/import-terranx.bat`).
- **References** (optional, for the analysis scripts and the skills that cite them):
  `git clone https://github.com/induktio/thinker refs/thinker` (symbol names, GPL-2) and
  `git clone https://github.com/DrazharLn/pracx refs/pracx`.
- **Node.js** for the two tests that check the JavaScript port of the scaling laws (they skip
  without it), and **PowerShell 7** (`pwsh`) for the resolution launchers `work/run-<WxH>.bat`.
- **The pre-commit hook**, once per clone: `git config core.hooksPath .githooks`. It runs the
  scaling-law guards on every commit and the full sweep when a scaling file is staged.
- **The DLL**: `src/uimod/build.bat Release` (Visual Studio 2022, Win32). `build.bat`,
  `tools/run-build-ffmpeg-slim.bat` and the C++ test harness `work/tests/cpp_harness.py` carry the
  Community edition's `vcvars32.bat` path; for Professional or Enterprise edit the two scripts and
  set `VCVARS32` to your `vcvars32.bat` for the harness, or every C++ harness test skips as
  "MSVC not installed".
  It links a slim LGPL ffmpeg that is built, not committed:
  1. Put the FFmpeg 8.1 source at `tools/ffmpeg-8.1`, MSYS2 at `tools/msys64`, and `nasm` on PATH
     (asm is required: a build without it decodes the HD pack far below full speed).
  2. Run `tools/run-build-ffmpeg-slim.bat`. It builds with MSVC and installs to
     `tools/ffmpeg-slim`.
  3. Copy `tools/ffmpeg-slim/include` to `src/uimod/third_party/ffmpeg/include`, and both
     `tools/ffmpeg-slim/lib/*` and the import libraries `tools/ffmpeg-slim/bin/*.lib` to
     `src/uimod/third_party/ffmpeg/lib`. The five DLLs in `tools/ffmpeg-slim/bin` go to
     `src/uimod/third_party/ffmpeg/bin`: the installer, `release.py` and the end-to-end tests read
     them there, and the installer deploys them beside `uimod.dll` in the game folder.

```
cd work\tests
py -m pytest -q          # ~2 min for the whole suite on 64 workers; -k scaling for the law sweep (~1.5 min)
```

The tests never launch the game and never write to a real install: installer tests use a
throwaway `--game-dir`.

### Building the installer payload

What a player downloads is the trimmed interpreter plus the scripts, patches, DLLs and art,
zipped and described by a signed manifest. From a checkout with the DLL built and the ffmpeg
DLLs in place:

```
py work\scripts\trace_imports.py            # runs the installer under tools\python and records what it imports
py work\scripts\build_runtime.py --verify    # stages the trimmed CPython 3.12 at work\build\runtime and proves it installs
py work\scripts\fetch_python38.py            # the Windows 7 / 8 interpreter at tools\python38 (python.org download, hash-pinned)
py work\scripts\release.py --out dist\release --sign-key <your key>   # packs and signs; see sign_manifest.py --keygen
```

`work/build/runtime` is also what the installer's end-to-end tests (`test_install_e2e`,
`test_release`, `test_dev_player_zip`, `test_runtime38`, parts of `test_bootstrap`) run against;
they skip until it exists. A manifest signed with your own key is accepted only by an installer
built with that key's public half in `work/scripts/manifest.py`; players' installs trust the
project's key alone.

## What the installer touches on a player's machine

The game folder (the patched exe with a `.bak` beside it, `uimod.dll`, the ffmpeg DLLs, the
`LongevityMods` folder holding the updater and its logs), the temp folder while it works, a
desktop shortcut only if the player says yes to the prompt, and
`%LOCALAPPDATA%\LongevityVaccine` as a download cache when the game folder is not writable.
Every download is HTTPS, every archive is checked against a SHA-256 from a manifest signed with
the key whose public half is in `work/scripts/manifest.py`, and the in-game DLL does no
networking of its own: it asks the installer.

## How the scaling works (the short version)

Every scaled value is `vanilla × (g/16)`, where `g` is the runtime popup scale derived from the
screen height, with a low-resolution gate that leaves the game untouched at native size. The
arithmetic lives in one place, `work/scripts/scaling_laws.py`; every hook and every code-cave
thunk is a port of it, and a test fails if a port disagrees with the module. `work/WHY.md`
records the approaches that were tried and rejected, so read it before proposing one of them.

## Contributing

Issues and pull requests are welcome here. Releases are built from a private working tree and
exported to this repository, so a merged change reaches players only after it is folded into
that tree and rebuilt; the maintainer will say when that happens. Please keep the invariants
above; `docs/skills/` shows how they are applied in practice.

## Licence

Copyright (C) 2026 Longevity Mods.

This program is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see
`LICENSE` for the full text (SPDX: `GPL-3.0-or-later`). Third-party components and their
licences are listed in `THIRD_PARTY.md`.

This project is not affiliated with Firaxis Games, Electronic Arts or GOG.
