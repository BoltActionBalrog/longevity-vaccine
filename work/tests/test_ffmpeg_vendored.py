"""The slim ffmpeg in src\\uimod\\third_party\\ffmpeg is TRACKED (2026-11-14): the DLL compiles against its headers,
links its import libraries and ships its five DLLs (release.py's base module), and the in-game movie player decodes
every movie -- the original .wve and the HD .mp4 -- through it.

Pinned here so a change to it is a reviewed change, never a silent one:
  * the five DLLs, byte for byte (a rebuild must update these hashes on purpose);
  * the build that ships keeps ffmpeg's assembly (a `--disable-asm` build cannot decode the HD clips in time);
  * the licence the DLLs declare (LGPL 2.1 or later) ships beside them, with FFmpeg's LICENSE.md;
  * every import library and header the project uses is present.
Cheap: reads ~7 MB once; no build, no game."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_FF = _REPO / "src" / "uimod" / "third_party" / "ffmpeg"

#: sha256 of the shipped DLLs (FFmpeg 8.1, tools/build_ffmpeg_slim.sh, MSVC x86). Rebuild -> update here, in the
#: same commit as the new DLLs.
DLLS = {
    "avcodec-62.dll": "ccbf7b36812cbca4cd1ac83eddec2528672ea78adeea4e431b110d1d95fc6b8d",
    "avformat-62.dll": "5c71dcde23052af9dca15f0622608141f3df1232a7c058572f1f66fa5bca263e",
    "avutil-60.dll": "40267961414e35b272bdad1ab48f3f6d59f088316703c10541867b6d9e1110e2",
    "swresample-6.dll": "3006583cb771aed89177c1e7a9e603b9a882ea7bfa1daae4ed916798d7004856",
    "swscale-9.dll": "11839a48ffe9c7104752d6b4d687413c426e28ae28107420a8b432495c68542f",
}
IMPORT_LIBS = ("avcodec", "avformat", "avutil", "swresample", "swscale")


@pytest.fixture(scope="module")
def avutil() -> bytes:
    return (_FF / "bin" / "avutil-60.dll").read_bytes()


@pytest.mark.parametrize("name", sorted(DLLS))
def test_the_shipped_dll_is_the_pinned_build(name):
    p = _FF / "bin" / name
    assert p.is_file(), f"{p} is missing: the folder is tracked, so `git checkout -- src/uimod/third_party` restores it"
    assert hashlib.sha256(p.read_bytes()).hexdigest() == DLLS[name], \
        f"{name} changed: a rebuilt ffmpeg must update DLLS here, in the same commit"


def test_only_the_five_dlls_ship():
    assert sorted(p.name for p in (_FF / "bin").glob("*.dll")) == sorted(DLLS)


def test_the_build_keeps_its_assembly(avutil):
    """avutil embeds its configure line. A pure-C (`--disable-asm`) build is too slow for the HD clips."""
    m = re.search(rb"--toolchain=msvc[\x20-\x7e]+", avutil)
    assert m, "no configure line in avutil-60.dll"
    flags = m.group().decode()
    assert "--disable-asm" not in flags and "--disable-x86asm" not in flags, flags
    for must in ("--arch=x86", "--enable-shared", "--enable-decoder='eatqi,h264,adpcm_ea,aac'",
                 "--enable-demuxer='ea,mov'"):
        assert must in flags, (must, flags)


def test_the_declared_licence_ships_beside_it(avutil):
    assert b"LGPL version 2.1 or later" in avutil
    text = (_FF / "COPYING.LGPLv2.1").read_text(encoding="utf-8", errors="replace")
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text and "Version 2.1" in text
    assert (_FF / "LICENSE.md").is_file()


@pytest.mark.parametrize("lib", IMPORT_LIBS)
def test_the_import_library_is_present(lib):
    assert (_FF / "lib" / f"{lib}.lib").is_file()


def test_the_headers_the_player_includes_are_present():
    for h in ("libavcodec/avcodec.h", "libavformat/avformat.h", "libavutil/avutil.h",
              "libswresample/swresample.h", "libswscale/swscale.h"):
        assert (_FF / "include" / h).is_file(), h


def test_the_project_and_the_release_use_this_folder():
    proj = (_REPO / "src" / "uimod" / "uimod.vcxproj").read_text(encoding="utf-8")
    assert r"third_party\ffmpeg\include" in proj and r"third_party\ffmpeg\lib" in proj
    rel = (_REPO / "work" / "scripts" / "release.py").read_text(encoding="utf-8")
    assert '("src/uimod/third_party/ffmpeg/bin", "*.dll"' in rel
