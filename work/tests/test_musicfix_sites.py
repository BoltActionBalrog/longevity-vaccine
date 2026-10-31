"""uimod's music fixes (src/uimod/src/musicfix.cpp, movie.cpp GameSoundHold) against the pristine exe.

musicfix: desktop_close's first call (`call DesignWin_reset` at 0x58EFF5) is redirected to a stub that
destroys g_music the way load_music does.  GameSoundHold: the in-process movie player brackets playback
with the calls the native player (set_video_mode 0x4BEA50) makes on the sound manager.
The addresses and bytes in the sources must be the ones the pristine exe carries.
"""
from __future__ import annotations

import pathlib
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pefile  # noqa: E402

import config  # noqa: E402

BAK = config.terranx_bak(required=False)
pytestmark = pytest.mark.skipif(not BAK or not pathlib.Path(BAK).exists(), reason="pristine exe not available")

SRC_DIR = ROOT.parent / "src" / "uimod" / "src"
FIX = (SRC_DIR / "musicfix.cpp").read_text(encoding="utf-8")
MOVIE = (SRC_DIR / "movie.cpp").read_text(encoding="utf-8")
INIT = (SRC_DIR / "init.cpp").read_text(encoding="utf-8")

DESKTOP_CLOSE, RESET_CALL, DESIGN_RESET, MUSIC = 0x58EFF0, 0x58EFF5, 0x43C1A0, 0x74DAA0
SOUND_MGR, SUSPEND, RESUME, PAUSE, UNPAUSE, PREFS_GET2 = 0x90D978, 0x4C4FC0, 0x4C4FD0, 0x4C51D0, 0x4C51C0, 0x59DB40


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(BAK), fast_load=True)


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def call_target(pe, va):
    b = rd(pe, va, 5)
    assert b[0] == 0xE8, f"no call at {va:#x}"
    return va + 5 + struct.unpack("<i", b[1:])[0]


def test_port_carries_the_sites_and_bytes():
    assert "kVA_ResetCall     = 0x58EFF5" in FIX and "kVA_DesignReset   = 0x43C1A0" in FIX
    assert "kVA_Music         = 0x74DAA0" in FIX and "{ 0xE8, 0xA6, 0xD1, 0xEA, 0xFF }" in FIX
    assert "kVA_SoundMgr     = 0x0090D978" in MOVIE and "kVA_PrefsGet2    = 0x0059DB40" in MOVIE
    assert "kVA_SndSuspend   = 0x004C4FC0" in MOVIE and "kVA_SndResume    = 0x004C4FD0" in MOVIE
    assert "kVA_SndPause     = 0x004C51D0" in MOVIE and "kVA_SndUnpause   = 0x004C51C0" in MOVIE
    assert "InstallMusicFix();" in INIT


def test_desktop_close_site_is_the_designwin_reset_call(pe):
    assert rd(pe, DESKTOP_CLOSE, 5) == bytes.fromhex("B9B0F27100")          # mov ecx, DesignWin
    assert rd(pe, RESET_CALL, 5) == bytes.fromhex("E8A6D1EAFF")
    assert call_target(pe, RESET_CALL) == DESIGN_RESET


def test_stub_destroys_the_music_as_load_music_does(pe):
    # load_music 0x445811: mov ecx,[g_music]; ...; mov eax,[ecx]; push 1; call [eax+8]; mov [g_music],ebx(0)
    assert rd(pe, 0x445811, 6) == bytes.fromhex("8B0D") + struct.pack("<I", MUSIC)
    assert rd(pe, 0x44581E, 7) == bytes.fromhex("8B016A01FF5008")
    assert rd(pe, 0x445825, 6) == bytes.fromhex("891D") + struct.pack("<I", MUSIC)
    assert "[2];   // vtbl+8" in FIX and "dtor(music, 1);" in FIX and "*slot = nullptr;" in FIX


def test_every_music_class_shares_the_one_arg_destructor(pe):
    # the six vtables load_music installs: vtbl+8 = the scalar deleting destructor 0x448390, RET 4
    for vtbl in (0x66B888, 0x66BF90, 0x66BE28, 0x66BCC0, 0x66BB58, 0x66B9F0):
        assert struct.unpack("<I", rd(pe, vtbl + 8, 4))[0] == 0x448390, hex(vtbl)
    assert rd(pe, 0x448390, 0x21).endswith(bytes.fromhex("C20400"))


def test_native_movie_brackets_the_sound_manager(pe):
    # set_video_mode: prefs_get_2("8BitMovieSound",0,0); mov ecx, mgr; ==0 -> suspend else pause
    assert call_target(pe, 0x4BEAC8) == PREFS_GET2
    name = struct.unpack("<I", rd(pe, 0x4BEABE, 4))[0]
    assert rd(pe, name, 15) == b"8BitMovieSound\0"
    assert rd(pe, 0x4BEAD0, 5) == b"\xB9" + struct.pack("<I", SOUND_MGR)
    assert rd(pe, 0x4BEAD5, 4) == bytes.fromhex("85C07507")
    assert call_target(pe, 0x4BEAD9) == SUSPEND and call_target(pe, 0x4BEAE0) == PAUSE
    # exit: ==0 -> resume else unpause
    assert rd(pe, 0x4BED8C, 5) == b"\xB9" + struct.pack("<I", SOUND_MGR)
    assert rd(pe, 0x4BED91, 4) == bytes.fromhex("85C07510")
    assert call_target(pe, 0x4BED95) == RESUME and call_target(pe, 0x4BEDA5) == UNPAUSE
    assert '"8BitMovieSound", 0, 0) != 0' in MOVIE
    assert "Call(paused ? kVA_SndPause : kVA_SndSuspend);" in MOVIE
    assert "Call(paused ? kVA_SndUnpause : kVA_SndResume);" in MOVIE


def test_sound_manager_calls_take_only_this(pe):
    # each is: mov ecx,[ecx+0x14]; test ecx,ecx; jz; mov eax,[ecx]; jmp/call [eax+N] -- no stack args
    for va, slot in ((SUSPEND, 0x48), (RESUME, 0x4C)):
        assert rd(pe, va, 12) == bytes.fromhex("8B491485C974058B01FF60") + bytes([slot])
    for va, slot in ((PAUSE, 0x64), (UNPAUSE, 0x60)):
        assert rd(pe, va, 14) == bytes.fromhex("8B491485C974058B01FF50") + bytes([slot]) + bytes.fromhex("33C0")


def test_sound_is_held_before_flips_are_blocked():
    hold, flip = MOVIE.index("GameSoundHold noGameSound;"), MOVIE.index("FlipBlock noGameFlips;")
    assert hold < flip and MOVIE.count("GameSoundHold noGameSound;") == 1
