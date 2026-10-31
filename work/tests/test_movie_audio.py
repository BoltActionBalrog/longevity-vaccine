"""The movie player's sound backend (src\\uimod\\src\\movieaudio.h), driven offline through
movie_audio\\audio_harness.cpp -- the same header the DLL compiles.

What Windows 7 changes: it has no xaudio2_9.dll, so the SDK's inline XAudio2Create failed there
and every movie played silent. The backend now loads the system DLL by full path and, when it is
not there, plays through winmm waveOut. This machine has XAudio2, so the Windows 7 path is walked
by pointing the loader at a file that does not exist (`no-xaudio2`): the forced-path test the
fix was asked for. Each test is one short harness run; the exe is built once per run.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cpp_harness  # noqa: E402

HARNESS = HERE / "movie_audio" / "audio_harness.cpp"
HEADER = HERE.parent.parent / "src" / "uimod" / "src" / "movieaudio.h"

pytestmark = pytest.mark.skipif(not cpp_harness.have_toolchain(), reason="VS 2022 x86 toolchain not installed")


@pytest.fixture(scope="module")
def exe() -> pathlib.Path:
    return cpp_harness.build(HARNESS, "movie-audio-", "/std:c++17 /EHsc /O1 winmm.lib ole32.lib")


def _run(exe: pathlib.Path, *args: str) -> dict:
    p = subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, f"{args}: exit {p.returncode}\n{p.stdout}{p.stderr}"
    out = p.stdout.strip()
    if out == "nodevice":
        pytest.skip("no waveOut device on this machine")
    fields = {}
    for tok in out.split(" ", 4):
        k, _, v = tok.partition("=")
        fields[k] = v
    # `why=` / `line=` may hold spaces: everything after the key is the value
    for key in ("why", "line"):
        if f" {key}=" in out:
            fields[key] = out.split(f" {key}=", 1)[1]
    return fields


# ---- the ini word ------------------------------------------------------------------------------

@pytest.mark.parametrize("word, mode", [
    ("auto", "auto"), ("AUTO", "auto"), ("xaudio2", "xaudio2"), ("XAudio2", "xaudio2"),
    ("waveout", "waveout"), ("WaveOut", "waveout"), ("off", "off"), ("0", "off"), ("none", "off"),
    ("", "auto"), ("typo", "auto"),      # an unknown word never silences the movies
])
def test_mode_word(exe, word, mode):
    assert _run(exe, "parse", word)["mode"] == mode


def test_mode_from_ini_defaults_to_auto_and_reads_the_key(exe, tmp_path):
    ini = tmp_path / "Alpha Centauri.ini"
    ini.write_text("[UIMod]\nDebugLog=0\n", encoding="ascii")
    assert _run(exe, "ini", str(ini))["mode"] == "auto"
    ini.write_text("[UIMod]\nMovieAudio=waveout\n", encoding="ascii")
    assert _run(exe, "ini", str(ini))["mode"] == "waveout"
    assert _run(exe, "ini", str(tmp_path / "missing.ini"))["mode"] == "auto"


# ---- the probe at Init -------------------------------------------------------------------------

def test_probe_finds_the_system_xaudio2_here(exe):
    r = _run(exe, "probe")
    assert r["probe"] == "XAudio2", r
    assert "xaudio2_9.dll" in r["line"].lower() and r["line"].startswith("movie audio: XAudio2")


def test_probe_without_xaudio2_names_the_dll_and_falls_to_waveout(exe):
    """The Windows 7 line: which DLL failed, the error, and what the movies will use instead."""
    r = _run(exe, "probe", "no-xaudio2")
    assert r["probe"] == "waveOut", r
    assert r["line"].startswith("movie audio: waveOut -- ") and "xaudio2_9.dll failed to load (error 126" in r["line"], r


# ---- playing through each backend --------------------------------------------------------------

def test_auto_plays_through_xaudio2_here(exe):
    r = _run(exe, "play", "auto", "300")
    assert r["backend"] == "XAudio2" and int(r["submitted"]) >= 6, r


def test_auto_without_xaudio2_plays_through_waveout(exe):
    """The Windows 7 path end to end: open WAVE_MAPPER, queue the decoder-sized buffers, stop."""
    r = _run(exe, "play", "auto", "300", "no-xaudio2")
    assert r["backend"] == "waveOut" and int(r["submitted"]) >= 6, r
    assert r["why"].startswith("waveOut (XAudio2 unavailable:") and "xaudio2_9.dll" in r["why"]


def test_forced_waveout_plays_through_waveout_with_xaudio2_present(exe):
    r = _run(exe, "play", "waveout", "300")
    assert r["backend"] == "waveOut" and int(r["submitted"]) >= 6, r
    assert "MovieAudio=waveout" in r["why"]


def test_forced_xaudio2_without_xaudio2_is_silent_and_says_why(exe):
    r = _run(exe, "play", "xaudio2", "100", "no-xaudio2")
    assert r["backend"] == "none" and r["submitted"] == "0", r
    assert "MovieAudio=xaudio2" in r["why"] and "failed" in r["why"]


def test_off_is_silent(exe):
    r = _run(exe, "play", "off", "100")
    assert r["backend"] == "none" and r["submitted"] == "0" and "MovieAudio=off" in r["why"], r


# ---- the skip path: Stop() with the queue still full, then the buffers freed -----------------------

@pytest.mark.parametrize("extra, backend", [((), "XAudio2"), (("no-xaudio2",), "waveOut")])
def test_stop_with_a_full_queue_then_free_is_safe(exe, extra, backend):
    """Esc during a movie: 2.7 s queued at once (58 buffers: XAudio2 refuses the 65th, XAUDIO2_MAX_QUEUED_BUFFERS;
    the player paces by video frames and never nears that), Stop() after 100 ms, every buffer freed and
    scribbled right after (a driver still reading one would play junk or fault). The harness exiting 0 with
    nothing dropped is the assertion; a use-after-free here is a crash, not a wrong field."""
    r = _run(exe, "play", "auto", "2700", "stop-after=100", *extra)
    assert r["backend"] == backend and int(r["submitted"]) >= 55 and r["dropped"] == "0", r


@pytest.mark.parametrize("com", ["com=sta", "com=mta"])
@pytest.mark.parametrize("extra, backend", [((), "XAudio2"), (("no-xaudio2",), "waveOut")])
def test_a_thread_that_already_has_com_keeps_its_apartment(exe, com, extra, backend):
    """The game thread has COM from elsewhere (the old code never initialised it and played). STA: XAudio2
    must still open (RPC_E_CHANGED_MODE on our MTA ask, left alone); MTA: our S_FALSE is balanced at once.
    Either way Stop() leaves the apartment exactly as found -- `com=kept`."""
    r = _run(exe, "play", "auto", "300", com, *extra)
    assert r["backend"] == backend and r["com"] == "kept", r


def test_xaudio2_queue_limit_is_counted_not_silent(exe):
    """Over-queue on purpose (3 s = 65 buffers): the 64-buffer limit refuses the last one and Dropped() says
    so -- movie.cpp logs that count at the end of a movie instead of a silent dropout."""
    r = _run(exe, "play", "xaudio2", "3000", "stop-after=100")
    assert r["backend"] == "XAudio2" and int(r["submitted"]) == 64 and int(r["dropped"]) >= 1, r


@pytest.mark.parametrize("extra, backend", [((), "XAudio2"), (("no-xaudio2",), "waveOut")])
def test_abuse_sequences_do_not_crash(exe, extra, backend):
    """Stop twice, Submit after Stop (refused and counted), delete without Stop (the destructor stops)."""
    r = _run(exe, "abuse", "auto", *extra)
    assert r["abuse"] == "ok", r


# ---- the DLL carries no private copy -----------------------------------------------------------

def test_movie_cpp_uses_the_header_and_no_inline_xaudio2create():
    src = (HEADER.parent / "movie.cpp").read_text(encoding="utf-8", errors="replace")
    assert '#include "movieaudio.h"' in src
    assert "XAudio2Create(" not in src, "the SDK inline loader is the Windows 7 bug; load through movieaudio.h"
    assert "#include <xaudio2.h>" not in src
    hdr = HEADER.read_text(encoding="utf-8", errors="replace")
    code = "\n".join(line.split("//", 1)[0] for line in hdr.splitlines())      # the prose may name the bug
    assert "LOAD_LIBRARY_SEARCH_SYSTEM32" not in code, "that flag needs KB2533623 on Windows 7"
    assert "GetSystemDirectoryW" in code and "FreeLibrary" not in code, "full path in, kept loaded for the process"
    assert "CoInitializeEx" in code, "XAudio2 2.9 returns CO_E_NOTINITIALIZED on a thread without COM"
