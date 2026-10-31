"""Thinker's `[Alpha Centauri] MoviePlayerPath` under the mod (user decision 2026-10-28, movie ownership A2).

thinker.dll reads the key on every launch: absent / `<DEFAULT>` -> VLC auto-detect, else a Yes/No prompt;
a path -> that external player; BLANK -> Thinker's own "default video player" = amovie_project_2 = the mod's
in-process player, and Thinker writes nothing back. The game and PRACX never read the key.

The installer therefore writes the blank on every install and update run (silently, Thinker present or
not), and on --uninstall deletes the key when it is still that blank, so Thinker re-detects from "absent"
exactly like a fresh Thinker install. A value the player changed since is left alone. These are the unit
tests of the two helpers over every prior state; test_install_e2e drives the real installer.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import install as inst        # noqa: E402

SECTION, KEY = inst.THINKER_MOVIE_SECTION, inst.THINKER_MOVIE_KEY
VLC = r"C:\Program Files\VideoLAN\VLC\vlc.exe"
ARGS = "--fullscreen --video-on-top --play-and-exit --no-repeat --swscale-mode=2"


def _write(game: Path, body: str) -> None:
    (game / "Alpha Centauri.ini").write_text(body, encoding="ascii")


def _key(game: Path):
    return inst.read_ini_str(game, SECTION, KEY, inst._INI_ABSENT)


@pytest.fixture
def game(tmp_path) -> Path:
    g = tmp_path / "game"
    g.mkdir()
    return g


def test_section_and_key_match_thinkers_source():
    assert SECTION == "Alpha Centauri" and KEY == "MoviePlayerPath"


@pytest.mark.parametrize("before", [
    None,                 # (i) never ran Thinker, or Thinker's "No" was never given
    "<DEFAULT>",          # (i) Thinker's own "No" at the prompt (movies skipped, prompt again)
    "",                   # (ii) already blank
    VLC,                  # (iii) Thinker's auto-detect wrote the VLC path
    r"C:\Tools\mpv.exe",  # (iv) hand-configured external player
], ids=["absent", "default", "blank", "vlc-auto", "custom"])
def test_install_blanks_every_prior_state_and_keeps_the_other_keys(game, before):
    body = "[Alpha Centauri]\n"
    if before is not None:
        body += f"MoviePlayerPath={before}\n"
    body += f"MoviePlayerArgs={ARGS}\nMovieExtension=mp4\n[UIMod]\nDpiAware=1\n"
    _write(game, body)
    inst.ensure_in_process_movies(game)
    assert _key(game) == ""
    assert inst.read_ini_str(game, SECTION, "MoviePlayerArgs", inst._INI_ABSENT) == ARGS
    assert inst.read_ini_str(game, SECTION, "MovieExtension", inst._INI_ABSENT) == "mp4"
    assert inst.read_ini_str(game, "UIMod", "DpiAware", inst._INI_ABSENT) == "1"
    inst.ensure_in_process_movies(game)                 # idempotent
    assert _key(game) == ""


def test_install_creates_the_section_when_the_ini_has_none(game):
    _write(game, "[UIMod]\n")
    inst.ensure_in_process_movies(game)
    assert _key(game) == ""
    text = (game / "Alpha Centauri.ini").read_text(encoding="utf-8", errors="replace")
    assert "[Alpha Centauri]" in text and "[UIMod]" in text


def test_uninstall_deletes_a_blank_and_keeps_a_changed_value(game):
    _write(game, f"[Alpha Centauri]\nMoviePlayerPath=\nMoviePlayerArgs={ARGS}\n")
    inst.release_in_process_movies(game)
    assert _key(game) == inst._INI_ABSENT, "absent, not blank: Thinker re-detects only from absent"
    assert inst.read_ini_str(game, SECTION, "MoviePlayerArgs", inst._INI_ABSENT) == ARGS
    inst.release_in_process_movies(game)                # a second run has nothing to do and does not fail
    assert _key(game) == inst._INI_ABSENT

    for changed in (VLC, "<DEFAULT>", r"C:\Tools\mpv.exe"):
        _write(game, f"[Alpha Centauri]\nMoviePlayerPath={changed}\n")
        inst.release_in_process_movies(game)
        assert _key(game) == changed, changed


def test_install_then_uninstall_round_trips_to_absent_from_every_state(game):
    for before in (None, "<DEFAULT>", VLC, r"C:\Tools\mpv.exe"):
        _write(game, "[Alpha Centauri]\n" + (f"MoviePlayerPath={before}\n" if before is not None else ""))
        inst.ensure_in_process_movies(game)
        assert _key(game) == ""
        inst.release_in_process_movies(game)
        assert _key(game) == inst._INI_ABSENT, before


def test_delete_ini_key_removes_only_that_key(game):
    _write(game, "[Alpha Centauri]\nA=1\nB=2\n")
    assert inst.delete_ini_key(game, SECTION, "A")
    assert inst.read_ini_str(game, SECTION, "A", inst._INI_ABSENT) == inst._INI_ABSENT
    assert inst.read_ini_str(game, SECTION, "B", inst._INI_ABSENT) == "2"
