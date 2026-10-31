"""The installer's console as a player reads it (user brief, 2026-09-27).

  * the optional modules are LISTED with sizes and the installer WAITS for a choice;
  * the patcher reports one coloured line per phase, names skipped sites without bytes and
    prints the bytes only for a failing site;
  * the summary is Success / Error / Skipped rows, with no row for an executable the mod does
    not touch and no "recorded" bookkeeping line;
  * saying yes to starting the game closes the window instead of waiting for a key.
"""
from __future__ import annotations

import shutil
import sys
import types
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent.parent
_SCRIPTS = _REPO / "work" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import apply_patches as ap    # noqa: E402
import install as inst        # noqa: E402
import installer_exit as ix   # noqa: E402

inst._load_modules()

CATALOGUE = {
    "movies-hd": {"size": 1395864371, "source": "manifest", "on_disk": False},
    "portraits-hd": {"size": 671088640, "source": "manifest", "on_disk": True},
}


def _args(**kw):
    # portrait_pack: never this checkout's real dist\portraits-hd (tests choose their packs explicitly)
    base = dict(modules=None, ai="ask", pack=None, portrait_pack=str(_SCRIPTS / "_no_portrait_pack"),
                manifest=None, offline=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _answers(monkeypatch, *answers):
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))


# ---------------------------------------------------------------- the module picker

def test_the_list_names_every_module_with_its_size(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _answers(monkeypatch, "all")
    inst.choose_modules(CATALOGUE, _args(), tmp_path)
    out = capsys.readouterr().out
    assert "1. HD cinematics" in out and "1.4 GB" in out
    assert "2. Longevity HD Portrait Pack" in out and "671 MB" in out
    assert "already on disk" in out.split("\n")[2]           # the portraits row, not the movies row
    assert "Selected: HD cinematics, Longevity HD Portrait Pack" in out


def test_enter_is_not_an_answer(monkeypatch, capsys, tmp_path):
    """The gate: a reflex Enter must not commit to gigabytes (audit 2026-09-27)."""
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _answers(monkeypatch, "", "", "none")
    assert inst.choose_modules(CATALOGUE, _args(), tmp_path) == []
    assert capsys.readouterr().out.count('Please type numbers between 1 and 2, "all", or "none".') == 2


def test_ctrl_c_at_the_picker_cancels_the_install(monkeypatch, tmp_path):
    """Ctrl-C is the universal abort, not consent: it must reach run_guarded, which cancels
    with nothing changed. Swallowing it as "none" went on to patch the game (audit)."""
    monkeypatch.setattr(ix, "can_ask", lambda: True)

    def interrupt(prompt=""):
        raise KeyboardInterrupt
    monkeypatch.setattr("builtins.input", interrupt)
    with pytest.raises(KeyboardInterrupt):
        inst.choose_modules(CATALOGUE, _args(), tmp_path)


def test_numbers_pick_and_an_invalid_answer_asks_again(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _answers(monkeypatch, "7", "x", "²", "①", "1" * 5000, "2")
    assert inst.choose_modules(CATALOGUE, _args(), tmp_path) == ["portraits-hd"]
    out = capsys.readouterr().out
    assert out.count("Please type numbers between 1 and 2") == 5
    assert "Selected: Longevity HD Portrait Pack" in out


def test_none_and_a_closed_stdin_select_nothing(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _answers(monkeypatch, "none")
    assert inst.choose_modules(CATALOGUE, _args(), tmp_path) == []

    def eof(prompt=""):
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    assert inst.choose_modules(CATALOGUE, _args(), tmp_path) == []
    assert capsys.readouterr().out.count("Selected: none") == 2


def test_flags_decide_without_asking(monkeypatch, tmp_path):
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not ask"))
    assert inst.choose_modules(CATALOGUE, _args(ai="off"), tmp_path) == []
    assert inst.choose_modules(CATALOGUE, _args(ai="on"), tmp_path) == ["movies-hd"]
    assert inst.choose_modules(CATALOGUE, _args(modules="portraits-hd,movies-hd"), tmp_path) \
        == ["portraits-hd", "movies-hd"]


def test_a_named_module_that_is_not_on_offer_is_refused_before_anything_happens(tmp_path):
    with pytest.raises(ix.InstallerError) as e:
        inst.choose_modules({"movies-hd": CATALOGUE["movies-hd"]}, _args(modules="portraits-hd"),
                            tmp_path)
    assert e.value.code == ix.EXIT_ABORTED and e.value.changed is False
    assert "Longevity HD Portrait Pack is not available" in e.value.message


def test_unattended_keeps_the_players_earlier_choice(monkeypatch, tmp_path):
    """No keyboard: a first install takes the headline pack; a re-run follows the ini."""
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("must not ask"))
    monkeypatch.setattr(inst, "ini_flag_state", lambda g, k: None)
    assert inst.choose_modules(CATALOGUE, _args(), tmp_path) == ["movies-hd"]
    monkeypatch.setattr(inst, "ini_flag_state", lambda g, k: False)
    assert inst.choose_modules(CATALOGUE, _args(), tmp_path) == []
    monkeypatch.setattr(inst, "ini_flag_state", lambda g, k: True)
    assert inst.choose_modules(CATALOGUE, _args(), tmp_path) == ["movies-hd"]


def test_ai_off_never_touches_the_network(monkeypatch, tmp_path):
    """The e2e suite runs `--ai off` fifty times; a manifest fetch there would hit the CDN."""
    def boom(*a, **k):
        pytest.fail("fetch_manifest must not be called for --ai off")
    monkeypatch.setattr(inst, "fetch_manifest", boom)
    cat, manifest = inst.module_catalogue(tmp_path, _args(ai="off", pack=str(tmp_path / "nope")))
    assert cat == {} and manifest is None
    # ...nor when nobody is at the keyboard and nothing was named
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    cat, manifest = inst.module_catalogue(tmp_path, _args(pack=str(tmp_path / "nope")))
    assert cat == {} and manifest is None


def test_an_unreachable_server_lists_nothing_and_says_so_once(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ix, "can_ask", lambda: True)

    def offline(*a, **k):
        assert k.get("quick"), "the listing must use the quick single-attempt profile"
        raise ix.InstallerError("Could not reach the update server.", code=ix.EXIT_ABORTED)
    monkeypatch.setattr(inst, "fetch_manifest", offline)
    cat, manifest = inst.module_catalogue(tmp_path, _args(pack=str(tmp_path / "nope")))
    assert cat == {} and manifest is None
    out = capsys.readouterr().out
    assert out.count("Optional modules could not be listed") == 1
    assert "update prompt" in out


def test_a_local_pack_is_listed_with_its_size_on_disk(tmp_path, monkeypatch):
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "a.mp4").write_bytes(b"x" * 1000)
    (pack / "b.mp4").write_bytes(b"y" * 500)
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    cat, _ = inst.module_catalogue(tmp_path, _args(ai="on", pack=str(pack)))
    assert cat["movies-hd"]["source"] == "local" and cat["movies-hd"]["size"] == 1500
    assert cat["movies-hd"]["on_disk"] is False


def test_cinematics_flag_rules(monkeypatch, tmp_path):
    monkeypatch.setattr(inst, "pack_on_disk", lambda g, n: False)
    monkeypatch.setattr(inst, "ini_flag_state", lambda g, k: None)
    flag = inst.cinematics_flag
    assert flag(["movies-hd"], tmp_path, _args(ai="off")) is True
    assert flag([], tmp_path, _args(ai="off")) is False
    assert flag([], tmp_path, _args(ai="on")) is True, "--ai on forces it (run-install.bat header)"
    assert flag([], tmp_path, _args(), offered=["movies-hd"]) is False, "shown the pack, said no"
    assert flag([], tmp_path, _args(), offered=[]) is True, "never listed (offline): first install on"
    assert flag(["portraits-hd"], tmp_path, _args(), offered=["portraits-hd"]) is True, \
        "only the portraits were on offer: nothing was declined"
    monkeypatch.setattr(inst, "ini_flag_state", lambda g, k: False)
    assert flag([], tmp_path, _args(), offered=[]) is False, "keeps the opt-out"
    monkeypatch.setattr(inst, "ini_flag_state", lambda g, k: True)
    assert flag([], tmp_path, _args(), offered=[]) is True, "keeps the opt-in"
    monkeypatch.setattr(inst, "pack_on_disk", lambda g, n: True)
    assert flag([], tmp_path, _args(ai="off")) is True, "clips already there"


# ---------------------------------------------------------------- the patcher's summary

def test_the_patcher_reports_one_line_per_phase(tmp_path, bak_path):
    exe = tmp_path / "t.exe"
    shutil.copy2(bak_path, exe)
    lines = []
    rc = ap.apply_patches(exe, Path(ap.DEFAULT_PATCHES), do_apply=True,
                          spec=ap.load_targets(ap.DEFAULT_PATCHES)["pracx"],
                          summary=lambda s, t: lines.append((s, t)))
    assert rc == 0
    text = "\n".join(t for _, t in lines)
    assert len(lines) < 12, text                          # a summary, not a transcript
    assert "Code caves: SUCCESS (2/2 ready)" in text
    assert "Patch sites: SUCCESS (" in text and "Patch groups: SUCCESS (" in text
    assert "Patching: SUCCESS (" in text and "Backup: t.exe.bak" in text
    # skipped sites are NAMED, never with their bytes; the note says skips are expected
    skips = [t for s, t in lines if s == "skip"]
    assert any("uimod_native.stub" in t for t in skips)
    assert not any("expected" in t or "got" in t for t in skips)
    assert any("Skipped sites are expected" in t for s, t in lines if s == "info")
    assert all(s in ("ok", "skip", "info") for s, _ in lines), "no error on a clean base"


def test_a_failing_site_is_reported_with_its_bytes(tmp_path, bak_path):
    """Corrupt one patch site's original bytes: the summary goes red and the bytes are shown."""
    import hashlib
    import pefile
    exe = tmp_path / "t.exe"
    data = bytearray(bak_path.read_bytes())
    sites, _g, _c, _s = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    site = next(s for s in sites if s.get("status") == "confirmed" and not s.get("group")
                and not s.get("skippable"))
    off = ap.VaResolver(pefile.PE(data=bytes(data), fast_load=True)) \
        .to_file_offset(int(site["virtual_addr"]))
    data[off] ^= 0xFF
    exe.write_bytes(bytes(data))
    lines = []
    # The legacy baseline arguments, so the run gets PAST the whole-file hash check and reaches
    # the per-site verification where the corrupted site fails.
    rc = ap.apply_patches(exe, Path(ap.DEFAULT_PATCHES), do_apply=False,
                          expected_md5=hashlib.md5(bytes(data)).hexdigest(),
                          expected_size=len(data),
                          summary=lambda s, t: lines.append((s, t)))
    assert rc == 3
    errors = [t for s, t in lines if s == "error"]
    assert any(t.startswith("Patch sites: ERROR (1/") for t in errors), errors
    detail = next(t for t in errors if site["id"] in t)
    assert "expected" in detail and "got" in detail, detail       # the bytes, for a FAILING site
    assert not any(site["id"] in t for s, t in lines if s == "skip")


def test_the_installer_colours_the_phase_lines(monkeypatch, capsys):
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    inst._patch_summary("ok", "Patching: SUCCESS (1/1 sites patched, 0 skipped, 0 code cave(s) written)")
    inst._patch_summary("error", "Patch sites: ERROR (1/2 failed, 0 skipped)")
    inst._patch_summary("skip", "  skipped: a")
    out = capsys.readouterr().out.split("\n")
    assert out[0].startswith("\x1b[32m") and out[1].startswith("\x1b[31m")
    assert "\x1b[" not in out[2]


# ---------------------------------------------------------------- summary rows + closing

def test_summary_rows_are_success_error_or_skipped(monkeypatch, capsys):
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    ix.status_line("terranx_PRACX.exe", "ok")
    ix.status_line("prax.dll", "skip")
    ix.status_line("HD cinematics", "error")
    rows = capsys.readouterr().out.rstrip("\n").split("\n")
    assert rows[0] == "  terranx_PRACX.exe      \x1b[32mSuccess\x1b[0m"
    assert rows[1] == "  prax.dll               Skipped"
    assert rows[2] == "  HD cinematics          \x1b[31mError\x1b[0m"
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)
    ix.status_line("x", "ok")
    assert capsys.readouterr().out == "  x                      Success\n"


def test_the_play_note_no_longer_explains_alien_crossfire(monkeypatch, capsys, tmp_path):
    (tmp_path / "terranx_PRACX.exe").write_bytes(b"MZ")
    monkeypatch.setattr(inst, "find_shortcut_to", lambda exe: None)
    inst.print_play_note(tmp_path, "pracx")
    out = capsys.readouterr().out
    assert "Alien Crossfire" not in out
    assert "The GOG Galaxy Play button" in out and inst.ENJOY_LINE in out


def test_the_resolution_refusal_is_a_yellow_stretched_warning(tmp_path, monkeypatch, capsys):
    ini = tmp_path / "Alpha Centauri.ini"
    ini.write_text("[PRACX]\r\nScreenWidth=1920\r\nScreenHeight=1080\r\n", encoding="ascii")
    monkeypatch.setattr(inst, "current_display_mode", lambda: (3840, 2160))
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    inst.check_display_resolution(tmp_path, "pracx")
    out = capsys.readouterr().out
    line = next(l for l in out.split("\n") if "Left your resolution as is" in l)
    assert line.startswith("\x1b[33m") and "stretched until you fix this!" in line


def test_saying_yes_to_starting_the_game_closes_the_window(monkeypatch, capsys):
    monkeypatch.setattr(ix, "offer_relaunch", lambda exe: True)
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: pytest.fail("must not wait"))
    assert ix.run_guarded(lambda: 0, relaunch_exe=Path("x.exe")) == ix.EXIT_OK


def test_declining_the_launch_still_holds_the_window(monkeypatch, capsys):
    monkeypatch.setattr(ix, "offer_relaunch", lambda exe: False)
    waited = []
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: waited.append(1))
    assert ix.run_guarded(lambda: 0, relaunch_exe=Path("x.exe")) == ix.EXIT_OK
    assert waited == [1]
