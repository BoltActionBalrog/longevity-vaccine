"""The independent audit of 356c8f8 (the merge of master into feat/thinker-install, 2026-11-17): one regression per
finding, each written to fail first. H1 (the Thinker question cleared the record before the up-front check), L3 (the
link refusal names the link), L5 (dll / exe probed only for a valid record), M2 / L4 (the pending marker, our desktop
shortcut and the consent key in the check), M3 (a refusal's detail through a junctioned game folder), L1 (the
"Nothing to uninstall" disk note), L2 (a help text changed between the Thinker plan and its commit)."""
from __future__ import annotations

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
import thinker_flow as tf           # noqa: E402
from test_uninstall_thinker_packs import _console, _installed_thinker, installed_with_thinker  # noqa: E402,F401

pytestmark = pytest.mark.usefixtures("install_globals", "synthetic_pin")
windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing modes and junctions")


def _record(g: Path) -> dict:
    return json.loads((g / tf.INSTALL_RECORD).read_text(encoding="utf-8"))


def _tree(g: Path) -> dict:
    return {p.relative_to(g).as_posix(): p.read_bytes() for p in g.rglob("*") if p.is_file()}


class _Held:
    """`p` held open by another program with no sharing at all."""

    def __init__(self, p: Path):
        self.p = p

    def __enter__(self):
        import _winapi
        self.h = _winapi.CreateFile(str(self.p), 0x80000000, 0, 0, 3, 0, 0)
        return self

    def __exit__(self, *a):
        import _winapi
        _winapi.CloseHandle(self.h)
        return False


# ---------------------------------------------------------------- H1: nothing changes before the up-front check

@windows
def test_a_refused_uninstall_keeps_a_marked_record_over_the_players_own_thinker(installed_with_thinker, monkeypatch):
    """The audit's repro: a marked record, the player's own thinker.dll in place, uimod.dll held -- refused, and the
    record is still there ("The uninstall itself changed nothing")."""
    g = installed_with_thinker
    rec = _record(g)
    rec["remove"] = True
    (g / tf.INSTALL_RECORD).write_text(json.dumps(rec), encoding="utf-8")
    (g / "thinker.dll").write_bytes(b"the player's own build")
    (g / "uimod.dll").write_bytes(b"MZ ours")
    monkeypatch.setattr(ix, "stdin_is_console", lambda: False)
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    before = _tree(g)
    with _Held(g / "uimod.dll"):
        with pytest.raises(ix.InstallerError) as e:
            inst.do_uninstall(g, types.SimpleNamespace(no_prompt=True, force=False))
    assert e.value.title == "UNINSTALL NOT STARTED"
    assert "changed nothing" in (e.value.disk_note or "")
    assert _tree(g) == before


def test_the_unrefused_run_still_drops_that_record_and_keeps_the_players_thinker(installed_with_thinker, monkeypatch,
                                                                                capsys):
    """audit-g LOW-4 still holds once the question no longer clears it: the run past the check does."""
    g = installed_with_thinker
    rec = _record(g)
    rec["remove"] = True
    (g / tf.INSTALL_RECORD).write_text(json.dumps(rec), encoding="utf-8")
    (g / "thinker.dll").write_bytes(b"the player's own build")
    monkeypatch.setattr(ix, "stdin_is_console", lambda: False)
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    inst.do_uninstall(g, types.SimpleNamespace(no_prompt=True, force=False))
    assert not (g / tf.INSTALL_RECORD).exists()
    assert (g / "thinker.dll").read_bytes() == b"the player's own build"
    assert inst._VERDICT[0] == "UNINSTALL COMPLETE", inst._VERDICT


# ---------------------------------------------------------------- L3: the link refusal names the link itself

def _junction(g: Path, name: str) -> None:
    import _winapi
    inside = g / (name + "-elsewhere")
    (g / name).rename(inside)
    _winapi.CreateJunction(str(inside), str(g / name))


@windows
def test_the_link_refusal_names_each_link_once_not_the_files_behind_it(installed_with_thinker, monkeypatch):
    """User-approved 2026-11-17: one detail line per distinct link, "<rel of the link>: a link to another folder"."""
    g = installed_with_thinker
    _junction(g, "smac_mod")
    _junction(g, "basenames")
    _console(monkeypatch, ["down", "enter"])
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    before = _tree(g)
    with pytest.raises(ix.InstallerError) as e:
        inst.do_uninstall(g, types.SimpleNamespace(no_prompt=False, force=False))
    assert e.value.title == "UNINSTALL NOT STARTED"
    assert e.value.detail.splitlines() == ["  basenames: a link to another folder", "  smac_mod: a link to another folder"]
    assert e.value.remedy == "replace the link named above with an ordinary folder, then run the uninstall again."
    assert _tree(g) == before


# ---------------------------------------------------------------- L5: an inert record never makes thinker.dll block

def _targets(g: Path) -> dict:
    return {p.relative_to(g).as_posix(): m for p, m in inst.uninstall_targets(g, list(inst._exe_names()), set())}


@windows
def test_an_invalid_record_does_not_make_a_held_thinker_dll_block_the_uninstall(installed_with_thinker, monkeypatch):
    """A record read_install_record rejects (another release's pin) is never acted on: thinker.dll and thinker.exe are
    not probed for it, so a held thinker.dll does not refuse the uninstall -- and the inert record still goes."""
    g = installed_with_thinker
    rec = _record(g)
    rec["pin"] = "not-this-installers-pin"
    (g / tf.INSTALL_RECORD).write_text(json.dumps(rec), encoding="utf-8")
    assert tf.read_install_record(g) is None
    t = _targets(g)
    assert "thinker.dll" not in t and "thinker.exe" not in t and t[tf.INSTALL_RECORD] == "delete+entitled+read"
    (g / "uimod.dll").write_bytes(b"MZ ours")
    monkeypatch.setattr(ix, "stdin_is_console", lambda: False)
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    dll = (g / "thinker.dll").read_bytes()
    with _Held(g / "thinker.dll"):
        inst.do_uninstall(g, types.SimpleNamespace(no_prompt=True, force=False))
    assert inst._VERDICT[0] == "UNINSTALL COMPLETE", inst._VERDICT
    assert not (g / tf.INSTALL_RECORD).exists() and (g / "thinker.dll").read_bytes() == dll


def test_a_valid_record_still_probes_both(installed_with_thinker):
    t = _targets(installed_with_thinker)
    assert t["thinker.dll"] == "read" and t["thinker.exe"] == "read"


# ---------------------------------------------------------------- M3: a refusal through a junctioned game folder

@windows
def test_a_refusal_names_its_files_when_the_game_folder_is_reached_through_a_junction(tmp_path):
    """The audit's repro: the game folder opened through a junction, a read-only Alpha Centauri.ini holding a receipt
    key -- the ini path is resolved, the folder is not: the detail must still say the name, never crash."""
    import _winapi
    import stat
    real = tmp_path / "real"
    real.mkdir()
    (real / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    rc.ini_set(real, rc.KEY_TARGET, "pracx")
    (real / "uimod.dll").write_bytes(b"MZ ours")
    _winapi.CreateJunction(str(real), str(tmp_path / "via"))
    g = Path(__import__("os").path.abspath(tmp_path / "via"))
    (real / "Alpha Centauri.ini").chmod(stat.S_IREAD)
    try:
        with pytest.raises(ix.InstallerError) as e:
            inst.do_uninstall(g, types.SimpleNamespace(no_prompt=True, force=False))
    finally:
        (real / "Alpha Centauri.ini").chmod(stat.S_IREAD | stat.S_IWRITE)
    assert e.value.title == "UNINSTALL NOT STARTED"
    assert "  Alpha Centauri.ini: the file is read-only" in e.value.detail.splitlines(), e.value.detail


def test_shown_names_a_file_outside_the_folder_in_full(tmp_path):
    g = tmp_path / "game"
    assert inst._shown_rel(g / "a" / "b.txt", g) == "a" + chr(92) + "b.txt"
    assert inst._shown_rel(tmp_path / "Desktop" / "x.lnk", g) == str(tmp_path / "Desktop" / "x.lnk")


# ---------------------------------------------------------------- M2: the marker, our shortcut, the consent key

def test_the_consent_key_alone_lists_the_ini_for_the_profile_api(tmp_path):
    g = tmp_path / "game"
    g.mkdir()
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    assert "Alpha Centauri.ini" not in _targets(g)
    rc.ini_set(g, tf.CONSENT_KEY, "1")
    assert rc.receipt_keys_present(g) == []
    assert _targets(g)["Alpha Centauri.ini"].split("+")[0] == "profile"


def test_the_pending_marker_is_listed_for_its_delete(tmp_path):
    g = tmp_path / "game"
    (g / "LongevityMods").mkdir(parents=True)
    inst._pending_path(g).write_text(json.dumps({"packs": ["movies-hd"]}), encoding="utf-8")
    assert _targets(g)["LongevityMods/" + inst.PENDING_PACKS] == "delete+entitled+read"


@windows
def test_our_read_only_shortcut_is_removed_and_listed(tmp_path, monkeypatch):
    import stat
    g = tmp_path / "game"
    g.mkdir()
    desk = tmp_path / "desktop"
    desk.mkdir()
    lnk = desk / (inst.MOD_SHORTCUT_NAME + ".lnk")
    lnk.write_text(str(g / "thinker.exe"), encoding="utf-8")
    lnk.chmod(stat.S_IREAD)
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [desk])
    monkeypatch.setattr(inst, "_shortcut_target", lambda p: Path(p).read_text(encoding="utf-8"))
    assert {str(p): m for p, m in inst.uninstall_targets(g, [], set())}[str(lnk)] == "delete+entitled+read"
    assert inst.remove_our_shortcut(g) == 1 and not lnk.exists()


# ---------------------------------------------------------------- L1: "Nothing to uninstall" names all it removed

def test_nothing_to_uninstall_names_every_leftover_it_removed(tmp_path, bak_path, monkeypatch):
    """Only bookkeeping left: the receipt and its key, the what's-new file, the pending marker, an inert Thinker install
    record, and the [Longevity] section that empties. The disk note names each, in its existing format."""
    import shutil
    g = tmp_path / "game"
    (g / "LongevityMods").mkdir(parents=True)
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    (g / "Alpha Centauri.ini").write_text("[Alpha Centauri]\r\nFoo=1\r\n", encoding="ascii")
    rc.ini_set(g, rc.KEY_TARGET, "pracx")
    (g / rc.JSON_NAME).write_text("{}", encoding="utf-8")
    inst._whats_new_path(g).write_text("1.0.0", encoding="utf-8")
    inst._pending_path(g).write_text(json.dumps({"packs": ["movies-hd"]}), encoding="utf-8")
    (g / tf.INSTALL_RECORD).write_text(json.dumps({"schema": 1, "pin": "not-ours", "files": {}}), encoding="utf-8")
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    with pytest.raises(ix.InstallerError) as e:
        inst.do_uninstall(g, types.SimpleNamespace(no_prompt=True, force=False))
    assert e.value.title == "NOTHING TO UNINSTALL", e.value.message
    note = e.value.disk_note
    for item in (f"{rc.JSON_NAME} and any of its keys in Alpha Centauri.ini",
                 "LongevityMods" + chr(92) + inst.WHATS_NEW_FILE, "LongevityMods" + chr(92) + inst.PENDING_PACKS,
                 tf.INSTALL_RECORD, "the empty [Longevity] section in Alpha Centauri.ini"):
        assert item in note, (item, note)
    assert note.startswith("Only Longevity Vaccine's leftover bookkeeping was removed (")
    assert not inst._whats_new_path(g).exists() and not inst._pending_path(g).exists()
    assert not (g / tf.INSTALL_RECORD).exists() and b"[Longevity]" not in (g / "Alpha Centauri.ini").read_bytes()


# ---------------------------------------------------------------- L2: a help text changed between plan and commit

def test_a_help_text_changed_after_the_plan_is_backed_up_as_it_is(tmp_path):
    """The plan saw our exact patch; before the commit the player edits our text (it no longer inverts). The commit
    must not escape with Refused (journal step 1, a part set, no rollback): the edited text is the player's now and
    goes into the set as it is."""
    import thinker_update as tu
    from test_audit_k import patched_help
    from test_audit_l import H, _set, _update, edited_help
    game, prep = _update(tmp_path, {H: patched_help()})
    assert prep.plan.datalinks_ours == [H]
    game.joinpath(*H.split("/")).write_bytes(edited_help())
    tf.commit(prep, route="thinker")
    assert _set(prep.report.backup_dir)[H] == edited_help()
    tf.finish(prep)
    assert tu.read_journal(game) is None


# ---------------------------------------------------------------- the link refusal: a link that is itself a file

FILE_LINK = "  thinker.dll: a link to another file"          # user-approved 2026-11-17


def _refusal(g: Path, monkeypatch) -> ix.InstallerError:
    _console(monkeypatch, ["down", "enter"])
    monkeypatch.setattr(inst, "_desktop_dirs", lambda: [])
    with pytest.raises(ix.InstallerError) as e:
        inst.do_uninstall(g, types.SimpleNamespace(no_prompt=False, force=False))
    return e.value


def test_a_file_that_is_a_link_is_named_as_a_link_to_another_file(installed_with_thinker, monkeypatch):
    """thinker.dll taken for a symlink (where this machine cannot make one, the link test below skips): refused up
    front, the detail line names the file as a link to another file."""
    import safe_fs
    g = installed_with_thinker
    real = safe_fs.is_link
    monkeypatch.setattr(safe_fs, "is_link", lambda p: Path(p) == g / "thinker.dll" or real(p))
    before = _tree(g)
    e = _refusal(g, monkeypatch)
    assert e.title == "UNINSTALL NOT STARTED" and e.detail.splitlines() == [FILE_LINK], e.detail
    assert _tree(g) == before


def test_a_real_file_symlink_is_refused_with_its_line(installed_with_thinker, monkeypatch):
    import os
    g = installed_with_thinker
    (g / "thinker.dll").rename(g / "thinker-real.dll")
    try:
        os.symlink(g / "thinker-real.dll", g / "thinker.dll")
    except (OSError, NotImplementedError) as err:
        pytest.skip(f"this machine cannot create a file symlink ({err})")
    e = _refusal(g, monkeypatch)
    assert e.title == "UNINSTALL NOT STARTED" and FILE_LINK in e.detail.splitlines(), e.detail
