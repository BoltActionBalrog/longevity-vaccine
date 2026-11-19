"""Audit-t (2026-11-17, the whole-lifecycle audit of 41f2cb6): fixes by root cause, each test written to fail first
(sequence tests from the audit's minimal repros where possible).

ROOT 1: "installed" means a readable pack-manifest.json, for the HD Cinematics as for the portraits; files without a
        list are the player's and never count. UpscaledVideos follows explicit choices only (a tick or an install sets
        it, an untick or --ai off clears it -- even over an installed pack), never the files.
ROOT 2: the list's answers are recorded when it is answered, before the patch: declines, pending marks, ends.
ROOT 3: an installed pack's pending update -- unticking clears its mark; an interrupted update is locked; an update
        that drops a clip removes the old one when it is provably ours.
ROOT 4: a pack that lands is in the receipt at once, so a later Ctrl-C does not make --check offer it again."""
from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import install as inst              # noqa: E402
import installer_exit as ix         # noqa: E402
import receipt as rc                # noqa: E402
from test_audit_n import _game, _setup_rest  # noqa: E402
from test_audit_p import PARTIAL, _archive, _manifest_bytes, _rerun_game  # noqa: E402
from test_audit_r import _declined, _pick  # noqa: E402
from test_setup_pack_rerun import CLIPS, PORTRAITS, _pack  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")

C07 = b"PLAYER c07 other size" * 333


def _player_clip(game: Path) -> Path:
    d = game / "movies" / "hd"
    d.mkdir(parents=True, exist_ok=True)
    (d / "c07.mp4").write_bytes(C07)
    return d / "c07.mp4"


# ---------------------------------------------------------------- ROOT 1: installed = a readable manifest

def test_files_without_a_list_are_not_the_cinematics(tmp_path):
    game = _game(tmp_path)
    _player_clip(game)
    assert inst.pack_on_disk(game, "movies-hd") is False
    _pack(game, "movies-hd", CLIPS)                                      # the pack's own list: now it is
    assert inst.pack_on_disk(game, "movies-hd") is True


@pytest.mark.parametrize("how", ["no-prompt", "interactive"])
def test_a_declined_cinematics_is_never_reinstalled_over_the_players_clips(tmp_path, monkeypatch, how):
    """H1: the Cinematics declined, the player's own c07.mp4 in movies\\hd."""
    game = _rerun_game(tmp_path)
    clip = _player_clip(game)
    rc.decline(game, inst.NEW_PACK_PREFIX + "movies-hd", rc.DECLINE_ANY)
    inst.set_ini_flag(game, False)
    chosen, down, ticked = _pick(game, monkeypatch, tmp_path, how, "down", "down", "enter")
    assert "movies-hd" not in chosen
    cat = {"movies-hd": {"size": 1, "source": "manifest", "version": "1.0.0", "on_disk": False, "locked": False,
                         "release_manifest": None, "release_provenance": None}}
    assert _setup_rest(game, monkeypatch, cat, chosen, ticked) == []
    assert clip.read_bytes() == C07 and _declined(game, "movies-hd")
    assert inst.ini_flag_state(game, "UpscaledVideos") is False


def test_upscaled_videos_is_never_inferred_from_files(tmp_path):
    """M1: a file in movies\\hd no longer forces the flag on, before or after --ai off."""
    game = _game(tmp_path)
    _player_clip(game)
    assert inst.cinematics_flag([], game, types.SimpleNamespace(ai="off"), offered=["movies-hd"]) is False
    inst.set_ini_flag(game, False)
    assert inst.cinematics_flag([], game, types.SimpleNamespace(ai="ask"), offered=[]) is False


def test_ai_off_over_an_installed_cinematics_switches_it_off(tmp_path):
    """L4: --ai off means "don't play HD movies", even with the pack installed; installed, it is never declined."""
    game = _rerun_game(tmp_path)
    _pack(game, "movies-hd", CLIPS)
    chosen, down, _t = inst.pick_modules({}, types.SimpleNamespace(modules=None, ai="off", no_prompt=False), game)
    assert down == []
    assert inst.cinematics_flag(chosen, game, types.SimpleNamespace(ai="off"), offered=down) is False


def _questions_then_ctrl_c(game, monkeypatch, tmp_path, *keys):
    """The real setup run up to the Thinker question, which is answered with Ctrl-C (a later question)."""
    from test_audit_q import _args, _signed, _unattended
    import thinker_flow
    _unattended(monkeypatch)
    _signed(tmp_path, monkeypatch, {"movies-hd": "1.0.0", "portraits-hd": "1.0.0"})
    monkeypatch.setattr(ix, "has_console", lambda: True)
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    from test_setup_pack_rerun import _keys
    _keys(monkeypatch, *keys)

    def ctrl_c(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(thinker_flow, "update_preflight", ctrl_c)
    with pytest.raises((KeyboardInterrupt, ix.InstallerError)):
        inst._install_from_questions(game, _args(), None, None, None)


# ---------------------------------------------------------------- ROOT 2: the answers are recorded when given

def test_the_lists_answers_are_recorded_before_a_later_question(tmp_path, monkeypatch):
    """L2: a re-run; the player ticks the portraits (a re-run starts them unticked), unticks nothing else, then stops
    at the Thinker question: the yes is recorded -- the portraits are pending, so the next run completes them."""
    game = _rerun_game(tmp_path)
    rc.decline(game, inst.NEW_PACK_PREFIX + "movies-hd", rc.DECLINE_ANY)
    _questions_then_ctrl_c(game, monkeypatch, tmp_path, "down", "enter", "down", "enter")
    assert _declined(game, "movies-hd") and not _declined(game, "portraits-hd")
    assert inst.pending_packs(game) == {"portraits-hd"}


def test_a_first_install_stopped_before_the_patch_changes_nothing(tmp_path, monkeypatch):
    """A first install records nothing early: stopped at the Thinker question, the folder is as it was (its verdict
    says "nothing was changed"), and the next run asks the same list from the same defaults."""
    game = _game(tmp_path)
    ini = (game / "Alpha Centauri.ini").read_bytes() if (game / "Alpha Centauri.ini").exists() else None
    _questions_then_ctrl_c(game, monkeypatch, tmp_path, "enter", "down", "down", "enter")
    assert not _declined(game, "movies-hd") and inst.pending_packs(game) == set()
    assert ((game / "Alpha Centauri.ini").read_bytes() if (game / "Alpha Centauri.ini").exists() else None) == ini
    assert not (game / "LongevityMods").exists()


def test_a_tick_erases_an_old_decline_at_once(tmp_path, monkeypatch):
    """M6/TK: an old decline on the portraits; the player ticks them, and the extract is killed. The next run must
    complete them, not end them for the stale decline."""
    game = _rerun_game(tmp_path)
    rc.decline(game, inst.NEW_PACK_PREFIX + "portraits-hd", rc.DECLINE_ANY)
    _questions_then_ctrl_c(game, monkeypatch, tmp_path, "down", "enter", "down", "enter")      # tick the portraits
    assert not _declined(game, "portraits-hd") and "portraits-hd" in inst.pending_packs(game)
    root = game / "portraits" / "hd"
    root.mkdir(parents=True)
    (root / PARTIAL).write_bytes(_manifest_bytes("portraits-hd", PORTRAITS))   # ... the extract was killed
    chosen, _d, _t = _pick(game, monkeypatch, tmp_path, "unattended")
    assert "portraits-hd" in chosen and (root / PARTIAL).is_file()


# ---------------------------------------------------------------- ROOT 3: an installed pack's pending update

def _installed_portraits_with_update(game) -> Path:
    root = _pack(game, "portraits-hd", PORTRAITS)
    rc.write(game, target_id="pracx", modules={"base": {"version": "1.0.0"}, "portraits-hd": {"version": "0.9.0"}})
    return root


def test_unticking_an_installed_pack_ends_its_pending_update(tmp_path, monkeypatch):
    """M2: the update download failed (the mark names the pack), then the player unticks the installed pack: no
    decline, no file change, nothing pending; an unattended run then leaves it at its old version."""
    game = _rerun_game(tmp_path)
    root = _installed_portraits_with_update(game)
    inst._mark_pending(game, ["portraits-hd"], True)
    _questions_then_ctrl_c(game, monkeypatch, tmp_path, "down", "enter", "down", "enter")      # untick the portraits
    assert "portraits-hd" not in inst.pending_packs(game) and not _declined(game, "portraits-hd")
    assert sorted(p.name for p in root.iterdir()) == sorted([*PORTRAITS, "pack-manifest.json"])
    assert "portraits-hd" not in _pick(game, monkeypatch, tmp_path, "unattended")[0]


def test_an_interrupted_update_is_locked_and_completed(tmp_path, monkeypatch):
    """M3: the older pack's manifest beside a newer .partial: completing it is the only consistent state -- locked
    ticked, never ended by a decline, completed unattended."""
    from test_audit_q import _args
    game = _rerun_game(tmp_path)
    root = _installed_portraits_with_update(game)
    (root / PARTIAL).write_bytes(_manifest_bytes("portraits-hd", {**PORTRAITS, "new.png": b"n" * 7}))
    rc.decline(game, inst.NEW_PACK_PREFIX + "portraits-hd", rc.DECLINE_ANY)
    chosen, _d, _t = _pick(game, monkeypatch, tmp_path, "unattended")
    assert "portraits-hd" in chosen and (root / PARTIAL).is_file()
    cat, _m = inst.module_catalogue(game, _args())
    assert cat["portraits-hd"]["locked"] is True


def _movies_archive(tmp_path, files: dict) -> Path:
    import zipfile
    p = tmp_path / "movies-new.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("movies/hd/pack-manifest.json", _manifest_bytes("movies-hd", files))
        for n, d in files.items():
            z.writestr(f"movies/hd/{n}", d)
    return p


@pytest.mark.parametrize("player_replaced", [False, True])
def test_a_cinematics_update_removes_a_clip_it_dropped_only_when_ours(tmp_path, player_replaced):
    """M4: the new release drops intro.mp4. It goes when it is still the old release's file (size + sha256 against
    the old manifest); one the player replaced stays."""
    game = _game(tmp_path)
    root = _pack(game, "movies-hd", CLIPS)                               # the old release: angels + intro
    if player_replaced:
        (root / "intro.mp4").write_bytes(b"the player's own intro")
    inst.install_modules(game, {"movies-hd": _movies_archive(tmp_path, {"angels.mp4": CLIPS["angels.mp4"]})},
                         {"movies-hd": "2.0.0"})
    assert (root / "intro.mp4").exists() is player_replaced
    assert (root / "angels.mp4").is_file()


# ---------------------------------------------------------------- ROOT 4: a landed pack is recorded at once

def test_a_landed_pack_is_in_the_receipt_before_any_later_question(tmp_path, monkeypatch):
    """M5b: packs land, then Ctrl-C at the shortcut question (the receipt used to be written only at the end): the
    next --check must not offer them as new."""
    from test_audit_q import _args, _remote_cat
    from test_check import _doc
    game = _game(tmp_path)

    def download(game_dir, args, names, manifest, target_id, target):
        got = inst.install_modules(game_dir, {"portraits-hd": _archive(tmp_path, "portraits-hd", PORTRAITS)},
                                   {"portraits-hd": "1.0.0"})
        return got, {n: "ok" for n in names}
    monkeypatch.setattr(inst, "install_packs_from_manifest", download)
    inst.place_packs(game, _args(), ["portraits-hd"], _remote_cat(game), ("r", "s", {}), "pracx",
                     game / "terranx.exe", {})
    # ... the run is stopped here, before _install_rest writes the receipt
    state = rc.read(game)
    assert rc.module_version(state, "portraits-hd") == "1.0.0" and rc.module_version(state, "base") == inst.ver.VERSION
    lines = inst.check_report(_doc(base=inst.ver.VERSION, **{"portraits-hd": "1.0.0"}), state, rc.declined(game))[1]
    assert not any(ln.startswith("new=portraits-hd") for ln in lines)


# ---------------------------------------------------------------- the fuzz regression (audit-t sequences on 832d278)

def test_a_first_install_records_its_answers_once_the_exe_is_patched(tmp_path, monkeypatch):
    """F002/F024: a first install, the Cinematics unticked, killed while placing the portraits: the no must survive.
    A first install records nothing before it patches (its stop still changes nothing), and everything the moment the
    exe is patched -- where the update-check answer is written, for the same reason."""
    from test_audit_q import _args
    import inspect
    game = _game(tmp_path)
    cat = {n: {"size": 1, "source": "manifest", "version": "1.0.0", "on_disk": False, "installed": False,
               "locked": False, "release_manifest": None, "release_provenance": None}
           for n in ("movies-hd", "portraits-hd")}
    monkeypatch.setattr(inst, "_UNTICKED", ["movies-hd"])
    inst.record_choices_now(game, _args(), cat, ["portraits-hd"], ["movies-hd"], ["portraits-hd"])
    assert not _declined(game, "movies-hd") and inst.pending_packs(game) == set()      # nothing before the patch
    inst.apply_pending_choices(game)                                                     # ... the exe is patched
    assert _declined(game, "movies-hd") and inst.pending_packs(game) == {"portraits-hd"}
    assert inst.ini_flag_state(game, "UpscaledVideos") is False
    src = inspect.getsource(inst._install_patch_pass)
    assert src.index("write_update_check(game_dir, _PENDING_UPDATE_CHECKS)") \
        < src.index("apply_pending_choices(game_dir)")


def test_the_flag_is_recorded_with_the_answer(tmp_path, monkeypatch):
    """F008/F010: --ai on (or a tick) is recorded at once, so the run that later completes the pack changes nothing."""
    from test_audit_q import _args
    game = _rerun_game(tmp_path)
    inst.set_ini_flag(game, False)
    inst.record_choices_now(game, _args(ai="on"), {}, ["movies-hd"], [], [])
    assert inst.ini_flag_state(game, "UpscaledVideos") is True


def test_a_pack_that_merely_lands_never_switches_the_cinematics_back_on(tmp_path, monkeypatch):
    """fB F003: the player unticked the installed Cinematics (flag off), then --no-prompt updated it: HD movies must
    stay off -- only an explicit choice changes the flag."""
    game = _rerun_game(tmp_path)
    inst.set_ini_flag(game, False)
    cat = {"movies-hd": {"size": 1, "source": "manifest", "version": "1.0.0", "on_disk": False, "locked": False,
                         "release_manifest": None, "release_provenance": None}}
    assert _setup_rest(game, monkeypatch, cat, ["movies-hd"], []) == [["movies-hd"]]
    assert inst.ini_flag_state(game, "UpscaledVideos") is False


def test_a_dropped_clip_goes_before_the_new_manifest_lands(tmp_path, monkeypatch):
    """F006: an update killed after its new manifest landed lost the proof (the old manifest) for the clip it dropped,
    which stayed orphaned for good. The proven prune now runs before the manifest is written."""
    game = _game(tmp_path)
    root = _pack(game, "movies-hd", CLIPS)
    real = inst.shutil.copyfileobj

    def stop_at_manifest(src, dst, *a):
        if "pack-manifest.json.tmp-" in str(getattr(dst, "name", "")):
            raise KeyboardInterrupt
        return real(src, dst, *a)
    monkeypatch.setattr(inst.shutil, "copyfileobj", stop_at_manifest)
    with pytest.raises(KeyboardInterrupt):
        inst.install_modules(game, {"movies-hd": _movies_archive(tmp_path, {"angels.mp4": CLIPS["angels.mp4"]})},
                             {"movies-hd": "2.0.0"})
    assert not (root / "intro.mp4").exists()


def test_an_untick_of_the_installed_cinematics_switches_it_off(tmp_path, monkeypatch):
    """An installed Cinematics with an update on offer is not locked: unticking it is "don't play HD movies"."""
    game = _rerun_game(tmp_path)
    inst.set_ini_flag(game, True)
    _pack(game, "movies-hd", CLIPS)
    rc.write(game, target_id="pracx", modules={"base": {"version": "1.0.0"}, "movies-hd": {"version": "0.9.0"}})
    chosen, down, ticked = _pick(game, monkeypatch, tmp_path, "interactive", "enter", "down", "down", "enter")
    assert "movies-hd" not in chosen and down == [] and "movies-hd" in inst.unticked_packs()
    cat = {"movies-hd": {"size": 1, "source": "manifest", "version": "1.0.0", "on_disk": True, "locked": False,
                         "release_manifest": None, "release_provenance": None}}
    _setup_rest(game, monkeypatch, cat, chosen, ticked)
    assert inst.ini_flag_state(game, "UpscaledVideos") is False and not _declined(game, "movies-hd")
