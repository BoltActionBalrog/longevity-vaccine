"""The `--check` run's two health lines (install.py mod_files_line / mod_loaded_line): whether the DLLs
beside the exe are the installer's, and whether the game last started WITH the mod. They go to stderr =
the game's check.log, never to the stdout pipe (the DLL's parser refuses a key it does not know), so a
bug report's log answers "is the mod even loaded?" without a word from the player.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_SCRIPTS = _TESTS.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import install as inst        # noqa: E402
import receipt as rc          # noqa: E402

CODECS = ("avutil-60.dll", "swresample-6.dll", "swscale-9.dll", "avcodec-62.dll", "avformat-62.dll")


@pytest.fixture
def payload(tmp_path, monkeypatch):
    """A fake resident installer: uimod.dll + five codec DLLs with distinct bytes."""
    p = tmp_path / "payload"
    (p / "ffmpeg").mkdir(parents=True)
    (p / "uimod.dll").write_bytes(b"MZuimod" * 100)
    for n in CODECS:
        (p / "ffmpeg" / n).write_bytes(("MZ" + n).encode() * 100)
    monkeypatch.setattr(inst, "uimod_dll", lambda: p / "uimod.dll")
    monkeypatch.setattr(inst, "ffmpeg_bin", lambda: p / "ffmpeg")
    return p


@pytest.fixture
def game(tmp_path, payload):
    g = tmp_path / "game"
    g.mkdir()
    for src in [payload / "uimod.dll"] + [payload / "ffmpeg" / n for n in CODECS]:
        (g / src.name).write_bytes(src.read_bytes())
    return g


def _receipt(game: Path, installed_at: int) -> None:
    (game / rc.JSON_NAME).write_text(json.dumps({"schema": 1, "installed_at": installed_at, "modules": {}}),
                                     encoding="utf-8")


def _log(game: Path, *lines: str) -> None:
    (game / "uimod.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _init(stamp: str, version: str = "0.2.0") -> str:
    return f"{stamp}.123 [4242] [uimod] Init: v{version}"


# ---- files -----------------------------------------------------------------------------------

def test_files_ok_when_every_dll_matches(game):
    assert inst.mod_files_line(game) == "Mod files: OK (6 DLLs match the installer's)"


def test_a_missing_codec_is_named(game):
    (game / "avcodec-62.dll").unlink()
    line = inst.mod_files_line(game)
    assert line.startswith("Mod files: missing: avcodec-62.dll") and "--repair" in line


def test_an_altered_dll_is_named_even_at_the_same_size(game):
    data = bytearray((game / "swscale-9.dll").read_bytes())
    data[10] ^= 0xFF
    (game / "swscale-9.dll").write_bytes(bytes(data))
    (game / "uimod.dll").unlink()
    line = inst.mod_files_line(game)
    assert "missing: uimod.dll" in line and "altered: swscale-9.dll" in line


def test_files_without_a_payload_to_compare_say_so(game, monkeypatch, tmp_path):
    monkeypatch.setattr(inst, "uimod_dll", lambda: tmp_path / "nowhere" / "uimod.dll")
    monkeypatch.setattr(inst, "ffmpeg_bin", lambda: tmp_path / "nowhere")
    assert inst.mod_files_line(game).startswith("Mod files: cannot compare")


# ---- loaded ----------------------------------------------------------------------------------

def test_no_log_means_never(game):
    assert inst.mod_loaded_line(game).startswith("Mod loaded: never -- no uimod.log")


def test_an_init_after_the_install_is_yes_with_time_and_version(game):
    _receipt(game, int(time.mktime(time.strptime("2026-10-31 09:00:00", "%Y-%m-%d %H:%M:%S"))))
    _log(game, _init("2026-10-30 20:00:00", "0.1.0"), _init("2026-10-31 09:12:05"))
    assert inst.mod_loaded_line(game) == "Mod loaded: yes, last at 2026-10-31 09:12:05 (v0.2.0)"


def test_an_init_older_than_the_install_is_not_since_this_install(game):
    _receipt(game, int(time.mktime(time.strptime("2026-10-31 09:00:00", "%Y-%m-%d %H:%M:%S"))))
    _log(game, _init("2026-10-30 20:00:00", "0.1.0"))
    assert inst.mod_loaded_line(game) == "Mod loaded: not since this install (last seen 2026-10-30 20:00:00, v0.1.0)"


def test_the_newest_start_carries_its_codec_and_audio_verdicts(game):
    _log(game,
         _init("2026-10-30 20:00:00"),
         "2026-10-30 20:00:00.200 [1] [uimod] codecs: avformat-62.dll is missing (Windows error 126)",
         _init("2026-10-31 09:12:05"),
         "2026-10-31 09:12:05.300 [2] [uimod] codecs: avcodec-62.dll is missing (Windows error 126)",
         "2026-10-31 09:12:05.400 [2] [uimod] movie audio: waveOut -- C:\\Windows\\system32\\xaudio2_9.dll failed to load (error 126; normal on Windows 7/8.1)")
    line = inst.mod_loaded_line(game)
    assert line.startswith("Mod loaded: yes, last at 2026-10-31 09:12:05 (v0.2.0)")
    assert "cinematics OFF: avcodec-62.dll is missing (Windows error 126)" in line
    assert "avformat" not in line, "an earlier start's problem must not be reported as current"
    assert "movie audio: waveOut" in line


def test_a_clean_start_reports_no_codec_problem(game):
    _log(game, _init("2026-10-31 09:12:05"),
         "2026-10-31 09:12:05.300 [2] [uimod] codecs: all 5 DLLs present and the shipped builds (D:\\game)",
         "2026-10-31 09:12:05.400 [2] [uimod] movie audio: XAudio2 (C:\\Windows\\system32\\xaudio2_9.dll)")
    line = inst.mod_loaded_line(game)
    assert "cinematics OFF" not in line and line.endswith("-- movie audio: XAudio2 (C:\\Windows\\system32\\xaudio2_9.dll)")


# ---- the wiring ------------------------------------------------------------------------------

def test_health_lines_go_to_stderr_on_both_paths_and_never_to_stdout():
    src = (_SCRIPTS / "install.py").read_text(encoding="utf-8", errors="replace")
    body = src[src.index("def check_main("):]
    assert body.count("_log_health(health_dir)") == 2, "after a good check AND on the could-not-check path"
    assert body.index("do_check(game_dir, args)") < body.index("_log_health(health_dir)"), \
        "the hashes run after the fetch, outside its deadline accounting"
    helper = src[src.index("def _log_health("):src.index("def check_main(")]
    assert "file=sys.stderr" in helper and "except Exception" in helper
    assert "mod_health" not in src[src.index("def check_report("):src.index("def do_check(")], \
        "check_report is the pipe's grammar; the DLL parser refuses unknown keys"


def test_health_never_fails_a_check(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(inst, "mod_health", lambda g: (_ for _ in ()).throw(RuntimeError("disk")))
    inst._log_health(tmp_path)
    assert "mod health could not be determined (RuntimeError: disk)" in capsys.readouterr().err
    inst._log_health(None)
