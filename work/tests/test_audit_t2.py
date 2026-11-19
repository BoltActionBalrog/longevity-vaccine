"""The parent's decisions after audit-t's fuzz re-run (2026-11-17). Each test written to fail first.

1. --check offers a pending pack (a .partial or a marker entry) that is not declined, so the game's prompt can
   complete it. A pending pack the receipt does not know was already offered (new=); one the receipt records at an
   older version was already offered (stale=); the silent case -- the receipt records it at the version on offer --
   is now offered with the game's own new-pack line (a stale= line must go up a version: the DLL refuses have >=
   offered). A declined pack is never added.
2. F018: only an EXPLICIT untick records a decline, on a first install too: a pack that starts unticked (the
   Cinematics with UpscaledVideos=0, kept across an uninstall) and is left untouched records nothing."""
from __future__ import annotations

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
from test_audit_n import _game      # noqa: E402
from test_audit_p import PARTIAL, _manifest_bytes  # noqa: E402
from test_audit_r import _declined, _pick  # noqa: E402
from test_setup_pack_rerun import CLIPS, _pack  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")

NEW_MOVIES = "new=movies-hd|Z2k Retro's HD Cinematics|1.0.0|"


def _check(game, monkeypatch, tmp_path) -> list:
    """The game's query, as the DLL runs it: do_check over a signed manifest (the network stubbed)."""
    from test_audit_q import _args, _signed
    _signed(tmp_path, monkeypatch, {"movies-hd": "1.0.0", "portraits-hd": "1.0.0"})
    return inst.do_check(game, types.SimpleNamespace(**vars(_args()), accept=[]))[1]


def _recorded_movies(tmp_path) -> Path:
    """The Cinematics recorded in the receipt at the version on offer, as a run that landed them left it."""
    game = _game(tmp_path)
    rc.write(game, target_id="pracx", modules={"base": {"version": inst.ver.VERSION},
                                               "movies-hd": {"version": "1.0.0"}})
    return game


@pytest.mark.parametrize("pending", ["partial", "marker"])
def test_check_offers_a_pending_pack_the_receipt_already_records(tmp_path, monkeypatch, pending):
    """A repair (or the same release placed again) killed part-way: the receipt is current, so nothing was offered."""
    game = _recorded_movies(tmp_path)
    root = _pack(game, "movies-hd", CLIPS)
    if pending == "partial":
        (root / PARTIAL).write_bytes(_manifest_bytes("movies-hd", CLIPS))
    else:
        inst._mark_pending(game, ["movies-hd"], True)
    lines = _check(game, monkeypatch, tmp_path)
    assert any(ln.startswith(NEW_MOVIES) for ln in lines), lines


def test_check_never_offers_a_declined_pending_pack(tmp_path, monkeypatch):
    game = _recorded_movies(tmp_path)
    _pack(game, "movies-hd", CLIPS)
    inst._mark_pending(game, ["movies-hd"], True)
    rc.decline(game, inst.NEW_PACK_PREFIX + "movies-hd", rc.DECLINE_ANY)
    assert not any(ln.startswith("new=movies-hd") for ln in _check(game, monkeypatch, tmp_path))


def test_check_stays_quiet_about_a_complete_recorded_pack(tmp_path, monkeypatch):
    game = _recorded_movies(tmp_path)
    _pack(game, "movies-hd", CLIPS)
    assert not any("movies-hd" in ln for ln in _check(game, monkeypatch, tmp_path))


def test_the_offer_is_a_line_the_game_accepts(tmp_path, monkeypatch):
    """No duplicate id (the DLL refuses one), new= after every stale=."""
    game = _recorded_movies(tmp_path)
    _pack(game, "movies-hd", CLIPS)
    inst._mark_pending(game, ["movies-hd"], True)
    lines = _check(game, monkeypatch, tmp_path)
    ids = [ln.split("=", 1)[1].split("|", 1)[0] for ln in lines if ln.startswith(("stale=", "new="))]
    assert len(ids) == len(set(ids))
    kinds = [ln.split("=", 1)[0] for ln in lines if ln.startswith(("stale=", "new="))]
    assert kinds == sorted(kinds, key=lambda k: k != "stale")


# ---------------------------------------------------------------- F018: only an explicit untick declines

@pytest.mark.parametrize("how", ["interactive", "no-prompt", "unattended"])
def test_a_first_install_left_untouched_records_no_decline(tmp_path, monkeypatch, how):
    """UpscaledVideos=0 (kept across an uninstall, as [UIMod] preferences are): the Cinematics start unticked on a fresh
    install; Continue without touching them is not a no."""
    from test_audit_n import _setup_rest
    game = _game(tmp_path)
    inst.set_ini_flag(game, False)
    chosen, down, ticked = _pick(game, monkeypatch, tmp_path, how, "down", "down", "enter")
    assert "movies-hd" not in chosen and "movies-hd" not in down
    inst.record_module_choice(game, ticked, down)
    assert not _declined(game, "movies-hd")


def test_a_first_install_explicit_untick_still_declines(tmp_path, monkeypatch):
    game = _game(tmp_path)
    chosen, down, ticked = _pick(game, monkeypatch, tmp_path, "interactive", "enter", "down", "down", "enter")
    assert down == ["movies-hd"]
