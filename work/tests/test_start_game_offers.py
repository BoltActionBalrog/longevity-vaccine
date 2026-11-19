"""`Start the game ... now?` after every outcome (user 2026-11-14): [Y/n] after an outcome that changed
Thinker Mod and/or Longevity Vaccine, [y/N] after one that changed nothing, none while the game is
still running. The program offered is always install.mod_exe (thinker.exe for a Thinker target)."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import bootstrap as bs        # noqa: E402
import install as inst        # noqa: E402
import installer_exit as ix   # noqa: E402


@pytest.fixture
def offers(monkeypatch):
    asked = []
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)
    monkeypatch.setattr(ix, "offer_relaunch", lambda exe, default=True: asked.append((exe, default)) or False)
    return asked


# ---------------------------------------------------------------- run_guarded

def test_a_success_offers_yes_by_default(offers):
    assert ix.run_guarded(lambda: ix.EXIT_OK, relaunch_exe=Path("x.exe")) == ix.EXIT_OK
    assert offers == [(Path("x.exe"), True)]


def test_a_success_that_changed_nothing_offers_no_by_default(offers):
    ix.run_guarded(lambda: ix.EXIT_OK, relaunch_exe=Path("x.exe"), relaunch_default=lambda: False)
    assert offers == [(Path("x.exe"), False)]


@pytest.mark.parametrize("code", [ix.EXIT_DECLINED, ix.EXIT_ABORTED])
def test_a_worker_that_changed_nothing_offers_no_by_default(offers, code):
    assert ix.run_guarded(lambda: code, relaunch_exe=Path("x.exe")) == code
    assert offers == [(Path("x.exe"), False)]


def test_a_stopped_update_says_where_the_reason_is(offers, capsys):
    ix.run_guarded(lambda: ix.EXIT_ABORTED)
    out = capsys.readouterr().out
    assert "The update was stopped before anything was changed. The reason is shown above." in out.splitlines()   # user 2026-11-15


@pytest.mark.parametrize("code", [ix.EXIT_DECLINED, ix.EXIT_ABORTED])
def test_no_program_no_offer(offers, code):
    ix.run_guarded(lambda: code, relaunch_exe=lambda: None)
    assert offers == []


# ---------------------------------------------------------------- the updater (bootstrap)

@pytest.fixture
def boot(tmp_path, monkeypatch):
    exe = tmp_path / "thinker.exe"
    exe.write_bytes(b"MZ")
    import receipt as rc
    import preflight
    state = {"target_id": "thinker"}
    monkeypatch.setattr(rc, "read", lambda g: dict(state))
    monkeypatch.setattr(inst, "mod_exe", lambda gd, tid: exe if (gd, tid) == (tmp_path, "thinker") else None)
    alive = {"pid": False}
    monkeypatch.setattr(preflight, "_pid_alive", lambda pid: alive["pid"])
    for name, v in (("_NOTE_ARGS", None), ("_OFFER", None), ("_GAME_DIR", tmp_path), ("_WAIT_PID", None),
                    ("_VERDICT", None)):
        monkeypatch.setattr(bs, name, v)
    return types.SimpleNamespace(exe=exe, state=state, alive=alive, game=tmp_path)


def test_the_updater_arms_no_offer_after_nothing_changed(boot):
    assert bs._offer_start() and bs._relaunch_exe() == boot.exe


def test_no_offer_while_the_game_that_started_the_updater_runs(boot, monkeypatch):
    monkeypatch.setattr(bs, "_WAIT_PID", 4242)
    boot.alive["pid"] = True
    assert not bs._offer_start() and bs._relaunch_exe() is None
    boot.alive["pid"] = False
    assert bs._offer_start()


def test_no_offer_for_a_folder_without_longevity_vaccine(boot):
    boot.state.pop("target_id")
    assert not bs._offer_start() and bs._relaunch_exe() is None


def test_no_offer_before_the_game_folder_is_known(boot, monkeypatch):
    monkeypatch.setattr(bs, "_GAME_DIR", None)
    assert not bs._offer_start()


@pytest.mark.parametrize("code", [ix.EXIT_DECLINED, ix.EXIT_ABORTED])
def test_a_cancelled_or_stopped_update_offers_no_by_default(boot, monkeypatch, offers, code):
    monkeypatch.setattr(bs, "run", lambda: code)
    assert ix.run_guarded(bs.main, relaunch_exe=bs._relaunch_exe,
                          relaunch_default=lambda: bool(bs._NOTE_ARGS)) == code
    assert offers == [(boot.exe, False)]


def test_an_updater_refusal_that_changed_nothing_offers_no_by_default(boot, monkeypatch, offers):
    def refuse():
        raise ix.InstallerError("The update information could not be trusted, so nothing was changed.",
                                code=ix.EXIT_ABORTED, changed=False)
    monkeypatch.setattr(bs, "run", refuse)
    ix.run_guarded(bs.main, relaunch_exe=bs._relaunch_exe, log_dir=boot.game)
    assert offers == [(boot.exe, False)]


def test_an_updater_failure_that_may_have_changed_something_offers_nothing(boot, monkeypatch, offers):
    def fail():
        raise ix.InstallerError("The update did not complete.", code=ix.EXIT_ERROR, changed=None)
    monkeypatch.setattr(bs, "run", fail)
    ix.run_guarded(bs.main, relaunch_exe=bs._relaunch_exe, log_dir=boot.game)
    assert offers == []


def test_already_up_to_date_offers_no_and_a_completed_update_yes(boot, monkeypatch, offers):
    """The guard's default follows _NOTE_ARGS (set only by an update that completed here)."""
    src = (_SCRIPTS / "bootstrap.py").read_text(encoding="utf-8")
    assert "relaunch_default=lambda: bool(_NOTE_ARGS)" in src[src.index('if __name__ == "__main__":'):]
    up_to_date = src[src.index('_VERDICT = ("ALREADY UP TO DATE"'):]
    assert up_to_date.index("_offer_start()") < up_to_date.index("return ix.EXIT_OK")
    bs._offer_start()
    ix.run_guarded(lambda: ix.EXIT_OK, relaunch_exe=bs._relaunch_exe, relaunch_default=lambda: bool(bs._NOTE_ARGS))
    monkeypatch.setattr(bs, "_NOTE_ARGS", (boot.game, "thinker"))
    ix.run_guarded(lambda: ix.EXIT_OK, relaunch_exe=bs._relaunch_exe, relaunch_default=lambda: bool(bs._NOTE_ARGS))
    assert offers == [(boot.exe, False), (boot.exe, True)]


# ---------------------------------------------------------------- setup and repair (install.py)

def test_repair_offers_the_mod_program(tmp_path, monkeypatch):
    exe = tmp_path / "thinker.exe"
    exe.write_bytes(b"MZ")
    import receipt as rc
    import thinker_flow
    monkeypatch.setattr(rc, "read", lambda g: {"target_id": "thinker"})
    monkeypatch.setattr(inst, "mod_exe", lambda gd, tid: exe if tid == "thinker" else None)
    for name in ("reconcile", "deploy"):
        monkeypatch.setattr(bs, name, lambda *a, **k: None)
    monkeypatch.setattr(bs, "resident_version", lambda g: "1.0.0")
    monkeypatch.setattr(inst, "payload_root", lambda: tmp_path)
    import version
    monkeypatch.setattr(inst, "ver", version)             # loaded lazily by install's main()
    monkeypatch.setattr(thinker_flow, "clear_dont_ask", lambda g: None)
    monkeypatch.setattr(inst, "_LAUNCH_EXE", None)
    assert inst.do_repair(tmp_path) == ix.EXIT_OK
    assert inst._LAUNCH_EXE == exe and inst._VERDICT[0] == "REPAIR COMPLETE"


def test_a_partly_complete_install_offers_yes(monkeypatch):
    """The game is patched and ready to play: the launch target is set before the PARTLY COMPLETE
    refusal, and the refusal carries a [Y/n] offer."""
    src = (_SCRIPTS / "install.py").read_text(encoding="utf-8")
    body = src[src.index("def _install_rest("):]
    body = body[:body.index("\ndef ", 1)]
    raise_at = body.index('title="INSTALLATION PARTLY COMPLETE"')
    assert body.index("_LAUNCH_EXE = mod_exe(game_dir, target_id)") < raise_at
    tail = body[raise_at:raise_at + 400]
    assert "offer_play=True, offer_play_default=True" in tail
    assert 'f"Longevity Vaccine {ver.VERSION} is installed." + add' in body
