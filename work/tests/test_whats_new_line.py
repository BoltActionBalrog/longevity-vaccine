"""The "See what's new" line (user-approved 2026-11-15): the last line of a success verdict whose run brought
Longevity Vaccine up from an older installed version -- an update, or an install over an older install. Never on a
fresh install, a same-version re-run, a repair, a pack-only update, a Thinker-only run or a failure. The end-to-end
runs are in test_install_e2e; these are the pieces, in-process."""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import install as inst              # noqa: E402
import installer_exit as ix         # noqa: E402
import manifest as mfmod            # noqa: E402
import receipt as rc                # noqa: E402
import version as ver               # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")

URL = "https://longevitymods.com/vaccine/changelog"
LINE = f"See what's new in Longevity Vaccine {ver.VERSION}: {URL}"


def test_one_constant_names_the_changelog_and_release_uses_it():
    assert mfmod.CHANGELOG_URL == URL
    hits = [p.name for p in _SCRIPTS.glob("*.py") if "longevitymods.com/vaccine/changelog" in p.read_text("utf-8")]
    assert hits == ["manifest.py"], hits          # release.py's notes_url reuses it, never a second literal
    assert re.search(r'"notes_url":[^\n]*\bCHANGELOG_URL\b', (_SCRIPTS / "release.py").read_text("utf-8"))


@pytest.mark.parametrize("before,now,armed", [
    ("0.9.0", ver.VERSION, True),
    (ver.VERSION, ver.VERSION, False),             # a same-version re-run
    ("9.9.9", ver.VERSION, False),                 # never "what's new" over a newer one
    (ver.UNKNOWN, ver.VERSION, False),             # no prior receipt: a fresh install
    ("", ver.VERSION, False),
    (None, ver.VERSION, False),
])
def test_the_line_is_armed_only_over_an_older_installed_version(before, now, armed):
    inst.note_whats_new(before, now)
    assert inst._WHATS_NEW == (ver.normalise(now) if armed else None)


def test_the_parenthetical_only_in_windows_terminal(monkeypatch):
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)
    monkeypatch.delenv("WT_SESSION", raising=False)
    assert inst.whats_new_line(ver.VERSION) == LINE
    monkeypatch.setenv("WT_SESSION", "0b0b0b0b-0000-4000-8000-000000000000")
    assert inst.whats_new_line(ver.VERSION) == LINE + " (Ctrl-click to open)"
    monkeypatch.setenv("WT_SESSION", "")
    assert inst.whats_new_line(ver.VERSION) == LINE


def test_the_url_is_blue_on_a_colour_console(monkeypatch):
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    monkeypatch.delenv("WT_SESSION", raising=False)
    assert inst.whats_new_line(ver.VERSION) == \
        f"See what's new in Longevity Vaccine {ver.VERSION}: \x1b[94m{URL}\x1b[0m"


def _play_note_world(monkeypatch, tmp_path, exe):
    import thinker_flow
    monkeypatch.setattr(thinker_flow, "offer_changelog", lambda *a: None)
    monkeypatch.setattr(inst, "mod_exe", lambda *a: exe)
    monkeypatch.setattr(inst, "_targets", lambda: {})          # a plain PRACX folder: no launcher
    monkeypatch.setattr(inst, "find_shortcut_to", lambda *a: None)
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)
    monkeypatch.delenv("WT_SESSION", raising=False)


@pytest.mark.parametrize("has_exe", [True, False], ids=["play-note", "no-exe"])
def test_the_line_closes_the_play_note_when_armed(monkeypatch, tmp_path, capsys, has_exe):
    _play_note_world(monkeypatch, tmp_path, tmp_path / "terranx_PRACX.exe" if has_exe else None)
    inst.note_whats_new("0.9.0", ver.VERSION)
    inst.print_play_note(tmp_path, "pracx")
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert lines[-2:] == [inst.ENJOY_LINE, LINE], lines


def test_no_line_when_not_armed(monkeypatch, tmp_path, capsys):
    _play_note_world(monkeypatch, tmp_path, tmp_path / "terranx_PRACX.exe")
    inst.print_play_note(tmp_path, "pracx")
    out = capsys.readouterr().out
    assert "See what's new" not in out and out.rstrip().endswith(inst.ENJOY_LINE)


# ---------------------------------------------------------------- the bootstrap: before and after its worker

def _bootstrap_world(monkeypatch, tmp_path, *, after: str, code: int):
    import bootstrap as bs
    g = tmp_path / "game"
    g.mkdir()
    rc.write(g, target_id="pracx", modules={"base": {"version": "0.9.0"}})
    monkeypatch.setattr(inst, "hold_installer_lock",
                        lambda d: types.SimpleNamespace(child_env=lambda env: dict(env)))

    def worker(cmd, **kw):
        rc.write(g, target_id="pracx", modules={"base": {"version": after}})
        return code
    monkeypatch.setattr(bs.subprocess, "call", worker)
    return bs, g


def _args(**kw):
    base = dict(repair=False, manifest=None, modules=None, only_listed=False, wait_pid=None, no_wait=True,
                offline=True, with_thinker=False, keep_thinker=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_the_bootstraps_update_arms_the_line_when_its_worker_moved_the_version(monkeypatch, tmp_path):
    bs, g = _bootstrap_world(monkeypatch, tmp_path, after=ver.VERSION, code=ix.EXIT_OK)
    assert bs._run_installer(_SCRIPTS, g, _args()) == ix.EXIT_OK
    assert inst._WHATS_NEW == ver.VERSION


@pytest.mark.parametrize("after,code,repair", [
    ("0.9.0", ix.EXIT_OK, False),                  # a pack-only update: the base did not move
    (ver.VERSION, ix.EXIT_ERROR, False),           # a failure
    (ver.VERSION, ix.EXIT_DECLINED, False),        # a cancellation
    (ver.VERSION, ix.EXIT_OK, True),               # --repair
], ids=["pack-only", "failed", "cancelled", "repair"])
def test_the_bootstrap_arms_nothing_otherwise(monkeypatch, tmp_path, after, code, repair):
    bs, g = _bootstrap_world(monkeypatch, tmp_path, after=after, code=code)
    bs._run_installer(_SCRIPTS, g, _args(repair=repair))
    assert inst._WHATS_NEW is None
