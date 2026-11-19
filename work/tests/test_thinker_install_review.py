"""The code review of feat/thinker-install (2026-11-15), one regression per finding, each written to fail first.

The findings: a set-up folder released and then given Thinker again patched the wrong exe (#2); a failure after a
first Thinker install's set-up left a set-up with no Thinker (#3); a first install over old settings files hid
what it replaced (#4); an undone change left its backup set and record behind (#5); --with-thinker's help (#6);
Ctrl-C meant two different outcomes in one setup run (#7). Plus the review's blind spots: the arrow-key fakes
must take exactly the real _arrow_menu's arguments, and the Thinker questions also run through the real one.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import shutil
import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import apply_patches as ap          # noqa: E402
import install as inst              # noqa: E402
import installer_exit as ix         # noqa: E402
import thinker_flow as tf           # noqa: E402
import thinker_state as st          # noqa: E402
import thinker_update as tu         # noqa: E402
from test_thinker_flow import World, _dll  # noqa: E402
from test_thinker_install_choices import Menu  # noqa: E402
from test_thinker_update import KNOWN, NEW, _folder  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")

#: The real arrow-key list, taken before any test replaces it.
REAL_MENU = inst._arrow_menu


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _args(**kw):
    return types.SimpleNamespace(**{"no_prompt": False, "ai": "off", "modules": None, "force": False,
                                    "manifest": None, "offline": False, "pack": None, "portrait_pack": None,
                                    "with_thinker": True, "keep_thinker": False, **kw})


def _fake_thinker_step(monkeypatch, g: Path, *, new: bool = True, dll=None, direction=st.OTHER) -> list:
    """Thinker's download and swap, faked (the swap writes thinker.dll / thinker.exe); everything else is real."""
    calls = []
    prep = types.SimpleNamespace(new=new, ts="5.5", committed=False, dll=dll, direction=direction)
    monkeypatch.setattr(tf, "prepare", lambda *a, **k: calls.append(("prepare",)) or prep)

    def commit(p, route, exe=None):
        calls.append(("commit", route))
        (g / "thinker.dll").write_bytes(b"not a real dll")
        (g / "thinker.exe").write_bytes(b"MZ")
        p.committed = True

    def undo(p):
        calls.append(("undo",))
        p.committed = False
    monkeypatch.setattr(tf, "commit", commit)
    monkeypatch.setattr(tf, "undo", undo)
    monkeypatch.setattr(tf, "finish", lambda p: calls.append(("finish",)))
    monkeypatch.setattr(tf, "summary_lines", lambda p: [])
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setattr(inst, "module_catalogue", lambda gd, a: ([], None))
    monkeypatch.setattr(inst, "pick_modules", lambda c, a, gd: ([], [], []))
    monkeypatch.setattr(inst, "_deploy_resident", lambda gd: None)
    monkeypatch.setattr(inst, "deploy_runtime", lambda gd, quiet=False: True)
    return calls


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


# ---------------------------------------------------------------- #2: a released set-up given Thinker again

def test_thinker_installed_into_a_released_set_up_patches_only_the_exe_thinker_starts(tmp_path, bak_path,
                                                                                     pristine_bytes, monkeypatch,
                                                                                     capsys):
    """A folder set up for Thinker, then Thinker removed (the plan says "release"), then "Also install": every
    choice made while Thinker was absent is made again. The pass patches terranx.exe only -- never
    terranx_PRACX.exe, which the set-up leaves alone -- and the console never says "installed for PRACX
    without Thinker" before installing Thinker."""
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    (g / "terranx.exe").write_bytes(pristine_bytes)
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    (g / "thinker.dll").write_bytes(b"dll")
    (g / "thinker.exe").write_bytes(b"exe")
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    assert inst.apply_thinker_setup(inst.plan_thinker_setup(g, _args()))
    (g / "thinker.dll").unlink()
    (g / "thinker.exe").unlink()
    assert inst.plan_thinker_setup(g, _args())["action"] == "release"
    capsys.readouterr()
    calls = _fake_thinker_step(monkeypatch, g)
    assert inst._install(g, _args()) == 0
    out = capsys.readouterr().out
    table = ap.load_targets(ap.DEFAULT_PATCHES)
    assert _md5(g / "terranx_PRACX.exe") == table["pracx_thinker"].base_md5, "terranx_PRACX.exe was patched"
    assert _md5(g / "terranx.exe") == table["pracx_thinker"].patched_md5
    assert "no longer in this folder" not in out
    assert ("undo",) not in calls and inst._VERDICT[1].endswith("Thinker Mod 5.5 was installed.")


# ---------------------------------------------------------------- #3: a failure after a first Thinker install

@pytest.fixture
def b_folder(tmp_path, bak_path):
    """A folder with no Thinker Mod: the clean PRACX build under its own name, nothing else."""
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    return g


@pytest.mark.parametrize("exc", [ix.InstallerError("A patch step failed.", changed=False), KeyboardInterrupt()],
                         ids=["patch-error", "ctrl-c"])
def test_a_first_thinker_install_stays_when_the_patch_pass_fails(b_folder, monkeypatch, capsys, exc):
    """By the pass the folder is set up for Thinker (terranx.exe the PRACX copy its launcher starts): taking
    Thinker out then would leave a set-up with no Thinker. It stays, the change is finished (no journal), the
    console says so, and the verdict never says nothing on disk was changed."""
    g = b_folder
    calls = _fake_thinker_step(monkeypatch, g)
    monkeypatch.setattr(inst, "_install_patch_pass", _raise(exc))
    with pytest.raises(type(exc)) as e:
        inst._install(g, _args())
    assert ("undo",) not in calls and ("finish",) in calls
    assert (g / "thinker.dll").is_file() and (g / "terranx.exe").is_file()
    assert inst._read_setup(g), "the set-up stays with Thinker"
    out = capsys.readouterr().out
    assert ("Thinker Mod 5.5 was installed and stays in the game folder. Run the installer again to finish "
            "installing Longevity Vaccine.") in out
    assert "put back as it was" not in out
    if isinstance(exc, ix.InstallerError):
        assert e.value.changed is True


def test_a_first_thinker_install_is_undone_when_the_set_up_cannot_start(b_folder, monkeypatch, capsys):
    """Before the set-up is applied nothing but Thinker's own swap happened: it goes back, and the folder is as
    the run found it."""
    g = b_folder
    calls = _fake_thinker_step(monkeypatch, g)
    monkeypatch.setattr(inst, "apply_thinker_setup", _raise(ix.InstallerError("locked", changed=False)))
    with pytest.raises(ix.InstallerError):
        inst._install(g, _args())
    assert ("undo",) in calls and ("finish",) not in calls
    assert "Thinker Mod was put back as it was." in capsys.readouterr().out


def test_an_update_of_an_existing_thinker_is_still_undone_when_the_pass_fails(b_folder, monkeypatch, capsys):
    """Not a first install (Thinker Mod 5.4 was there): the pass failing puts 5.4 back, as before."""
    g = b_folder
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod v5.4"))
    (g / "thinker.exe").write_bytes(b"MZ")
    _s, dll = st.classify(g, "0" * 64)
    calls = _fake_thinker_step(monkeypatch, g, new=False, dll=dll, direction=st.UP)
    monkeypatch.setattr(inst, "_install_patch_pass", _raise(ix.InstallerError("A patch step failed.")))
    with pytest.raises(ix.InstallerError):
        inst._install(g, _args())
    assert ("undo",) in calls and ("finish",) not in calls
    assert "Thinker Mod was put back as it was." in capsys.readouterr().out


# ---------------------------------------------------------------- #4 / #5: a first install's summary and undo

def _first_install_plan(tmp_path, game_files: dict):
    game = _folder(tmp_path / "game", game_files)
    staged_dir = _folder(tmp_path / "staged", {**NEW, "Changelog.md": b"what's new"})
    staged = {rel: staged_dir.joinpath(*rel.split("/")) for rel in (*NEW, "Changelog.md")}
    p = tu.plan(game, "5.5.0", staged, known=KNOWN, old_stock=None, ts="5.5", from_label=st.Label())
    return game, tf.Prepared(game, tf.compiled_pin(), tf.compiled_meta(), None, p, "5.5", st.OTHER, new=True)


def test_a_first_install_over_old_settings_files_says_what_it_replaced(tmp_path):
    """No thinker.dll, but an old thinker.ini: it is merged and backed up, and the summary says so."""
    game, prep = _first_install_plan(tmp_path, {"thinker.ini": b"[thinker]\r\nvideo_mode=2\r\nretired=1\r\n"})
    tf.commit(prep, route="fresh")
    r = prep.report
    lines = tf.summary_lines(prep)
    assert r.replaced >= 1
    assert lines[0] == f"  Thinker Mod 5.5: installed ({r.added} files added, {r.replaced} replaced)"
    assert f"  The files it replaced are saved in LongevityMods\\backups\\{r.backup_dir.name}" in lines
    assert "  thinker.ini: Thinker Mod 5.5's settings file was installed with your values carried over." in lines
    assert any(line.startswith("  Settings Thinker Mod 5.5 does not use were kept") and "retired" in line
               for line in lines)


def test_a_first_install_with_nothing_to_replace_says_only_what_it_added(tmp_path):
    game, prep = _first_install_plan(tmp_path, {"terranx.exe": b"MZ"})
    tf.commit(prep, route="fresh")
    assert tf.summary_lines(prep) == [f"  Thinker Mod 5.5: installed ({prep.report.added} files added)"]


def test_undo_after_a_first_install_leaves_nothing_of_it(tmp_path):
    """The backup set (empty: nothing was replaced), the record and the changelog copy all go: older_backups,
    uninstall_lines and the changelog offer never see a change that did not happen."""
    game, prep = _first_install_plan(tmp_path, {"terranx.exe": b"MZ"})
    tf.commit(prep, route="fresh")
    assert prep.report.backup_dir.is_dir() and (game / tf.RECORD_FILE).is_file()
    assert list((game / "LongevityMods").glob(tf.CHANGELOG_GLOB))
    assert tf.undo(prep) == tu.UNDONE
    assert not prep.report.backup_dir.exists() and tu.older_backups(game) == []
    assert not (game / tf.RECORD_FILE).exists()
    assert not list((game / "LongevityMods").glob(tf.CHANGELOG_GLOB))
    assert not (game / "thinker.dll").exists() and tf.uninstall_lines(game) == tf.uninstall_lines(tmp_path / "none")


def test_undo_puts_an_earlier_record_and_changelog_back(tmp_path):
    """A folder that already had a record and a changelog copy from an earlier change: undo restores both."""
    game, prep = _first_install_plan(tmp_path, {"terranx.exe": b"MZ"})
    rec = game / tf.RECORD_FILE
    rec.parent.mkdir(parents=True, exist_ok=True)
    earlier = json.dumps({"from": "Thinker Mod 5.3", "to": "5.4.0", "at": 1, "changelog_offered": True})
    rec.write_text(earlier, encoding="utf-8")
    old_cl = game / "LongevityMods" / "thinker-changelog-5.4.txt"
    old_cl.write_bytes(b"5.4 notes")
    tf.commit(prep, route="fresh")
    assert rec.read_text(encoding="utf-8") != earlier and not old_cl.exists()
    tf.undo(prep)
    assert rec.read_text(encoding="utf-8") == earlier and old_cl.read_bytes() == b"5.4 notes"
    assert sorted(p.name for p in (game / "LongevityMods").glob(tf.CHANGELOG_GLOB)) == [old_cl.name]


# ---------------------------------------------------------------- #6: --with-thinker's help

def test_with_thinker_help_says_it_installs_thinker_too():
    tree = ast.parse((_SCRIPTS / "install.py").read_text(encoding="utf-8"))
    helps = [kw.value.value if isinstance(kw.value, ast.Constant) else ast.literal_eval(kw.value)
             for n in ast.walk(tree) if isinstance(n, ast.Call) and n.args
             and isinstance(n.args[0], ast.Constant) and n.args[0].value == "--with-thinker"
             for kw in n.keywords if kw.arg == "help"]
    assert helps == ["Install Thinker Mod, or change it to the version this release needs, without asking "
                     "(for scripted runs)."]


# ---------------------------------------------------------------- #7: Ctrl-C at every question of a setup run

def _outcome(fn):
    try:
        with pytest.raises(ix.InstallerError) as e:
            fn()
    except KeyboardInterrupt:              # escaped: run_guarded's INSTALLATION CANCELLED (and pytest's own stop)
        pytest.fail("Ctrl-C escaped the question as KeyboardInterrupt")
    return e.value.code, e.value.title, e.value.message, e.value.changed


STOPPED = (ix.EXIT_ABORTED, "NOTHING WAS CHANGED", "You stopped the installer, so nothing was changed.", False)


def _ctrl_c_keys(monkeypatch):
    monkeypatch.setattr(inst, "_drop_typed_ahead", lambda: None)
    monkeypatch.setattr(inst, "_read_key", _raise(KeyboardInterrupt()))


def test_ctrl_c_at_the_thinker_question_through_the_real_list(monkeypatch, capsys):
    _ctrl_c_keys(monkeypatch)
    assert _outcome(lambda: tf.choose("Thinker Mod", ["a note"], ["first", "second"])) == STOPPED
    assert " -> first" in capsys.readouterr().out          # the real list was drawn


def test_ctrl_c_at_the_optional_modules_is_the_same_outcome(b_folder, monkeypatch):
    _fake_thinker_step(monkeypatch, b_folder)
    monkeypatch.setattr(inst, "pick_modules", _raise(KeyboardInterrupt()))
    assert _outcome(lambda: inst._install(b_folder, _args(with_thinker=False, keep_thinker=True))) == STOPPED
    assert not (b_folder / "terranx.exe").exists() and not (b_folder / "thinker.dll").exists()


def test_ctrl_c_at_automatic_updates_through_the_real_list_is_the_same_outcome(b_folder, monkeypatch, capsys):
    calls = _fake_thinker_step(monkeypatch, b_folder)
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _ctrl_c_keys(monkeypatch)
    assert _outcome(lambda: inst._install(b_folder, _args(with_thinker=False, keep_thinker=True))) == STOPPED
    assert inst.UPDATE_CHECK_YES in capsys.readouterr().out    # the real AUTOMATIC UPDATES list was drawn
    assert not calls and not (b_folder / "terranx.exe").exists()


# ---------------------------------------------------------------- the review's blind spots

def test_every_arrow_key_fake_takes_exactly_the_real_lists_arguments():
    """A fake that accepts an argument the real _arrow_menu does not (it once took `highlight`) hides a caller
    that would crash for real."""
    real = list(inspect.signature(REAL_MENU).parameters)
    assert list(inspect.signature(World._menu).parameters)[1:] == real
    assert list(inspect.signature(Menu.__call__).parameters)[1:] == real


def test_the_update_now_questions_through_the_real_list(tmp_path, monkeypatch, capsys):
    """Q-T through the real _arrow_menu (every other journey-R test fakes it): drawn with the marker on the
    first option; Enter takes it."""
    w = World(tmp_path, monkeypatch)
    monkeypatch.setattr(inst, "_arrow_menu", REAL_MENU)
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)
    monkeypatch.setattr(inst, "_drop_typed_ahead", lambda: None)
    keys = iter(["down", "up", "enter"])
    monkeypatch.setattr(inst, "_read_key", lambda: next(keys))
    assert w.run() == ix.EXIT_OK
    out = capsys.readouterr().out
    assert " -> Update Thinker Mod to 5.5\n    Keep Thinker Mod 5.4\n" in out
    assert "Open Thinker.ini" not in out                # asked in the closing lines, before the changelog (user 2026-11-16)
    assert w.committed == [{"route": "thinker"}]


def test_q1_through_the_real_list(tmp_path, monkeypatch, capsys):
    """Q1 (a setup run over Thinker Mod 5.4) through the real _arrow_menu: Down, Enter = Only install."""
    g = tmp_path / "game"
    g.mkdir()
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod v5.4"))
    monkeypatch.setattr(tf, "_asks", lambda a: True)
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)
    monkeypatch.setattr(inst, "_drop_typed_ahead", lambda: None)
    keys = iter(["down", "enter"])
    monkeypatch.setattr(inst, "_read_key", lambda: next(keys))
    r = tf.update_preflight(g, types.SimpleNamespace(), None, fresh=True, lv="1.0.0", persist_issued=False,
                            defer=True)
    out = capsys.readouterr().out
    assert " -> Also update Thinker Mod to 5.5\n    Only install Longevity Vaccine\n" in out
    assert r.todo is None and r.prep is None and r.keep


# ---------------------------------------------------------------- unproven in the review: a folder LV cannot patch

def test_a_folder_this_mod_cannot_patch_is_refused_before_any_question_or_download(tmp_path, monkeypatch):
    """A Steam / vanilla folder (no PRACX), given by --game-dir: the folder list would not offer it, and the patch
    pass refuses it -- but only after every question, and after "Also install" had downloaded and committed
    Thinker Mod. Now the pass's refusal comes first: no question, no download, nothing written."""
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    (g / "terranx.exe").write_bytes(b"MZ" + bytes(range(256)) * 16)        # an exe no target knows
    asked = []
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setattr(inst, "module_catalogue", lambda gd, a: asked.append("modules") or ([], None))
    monkeypatch.setattr(tf, "prepare", lambda *a, **k: asked.append("download"))
    with pytest.raises(ix.InstallerError) as e:
        inst._install(g, _args())
    assert e.value.code == ix.EXIT_UNSUPPORTED and e.value.changed is False
    assert e.value.message == "No game executable this mod can patch was found in the game folder."
    assert asked == [] and sorted(p.name for p in g.iterdir()) == ["terranx.exe"]


# ---------------------------------------------------------------- unproven in the review: keys in a spawned console

_CHILD = r'''
import ctypes, json, sys
sys.path.insert(0, sys.argv[2])
import install as inst
k = ctypes.WinDLL("kernel32", use_last_error=True)
k.GetStdHandle.restype = ctypes.c_void_p
k.WriteConsoleInputW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
h = k.GetStdHandle(ctypes.c_ulong(-10 & 0xFFFFFFFF))


def key(vk, ch, down=True):
    r = inst._InputRecord()
    r.EventType = 1
    e = r.Event.KeyEvent
    e.bKeyDown, e.wRepeatCount, e.wVirtualKeyCode, e.uChar = int(down), 1, vk, ch
    return r


recs = [key(0x28, "\0"), key(0x28, "\0", False),           # Down (press, release)
        key(0x26, "\0"), key(0x0D, "\r"),                   # Up, Enter
        key(0, "\x1b"), key(0, "["), key(0, "B"),           # Down as a virtual-terminal sequence
        key(0x41, "a")]                                     # any other key
arr = (inst._InputRecord * len(recs))(*recs)
n = ctypes.c_ulong()
ok = k.WriteConsoleInputW(h, arr, len(recs), ctypes.byref(n))
out = {"isatty": sys.stdin.isatty(), "written": n.value if ok else -1, "keys": [inst._read_key() for _ in range(5)]}
open(sys.argv[1], "w", encoding="utf-8").write(json.dumps(out))
'''


@pytest.mark.skipif(sys.platform != "win32", reason="a Windows console")
def test_arrow_keys_are_read_in_a_console_spawned_like_the_games_update_window(tmp_path):
    """The game starts the updater with CREATE_NEW_CONSOLE (update.cpp; thinker_flow's hand-over and the bootstrap
    likewise): a fresh console, no redirection. The real _read_key, in such a child, reads the keys put in that
    console's input buffer -- arrows as key records and as a virtual-terminal sequence, Enter, any other key.
    (Under Wine this stays unverified: no Wine here.)"""
    import subprocess
    child = tmp_path / "child.py"
    child.write_text(_CHILD, encoding="utf-8")
    result = tmp_path / "result.json"
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0                                          # SW_HIDE: no window flashes during the suite
    p = subprocess.run([sys.executable, "-I", str(child), str(result), str(_SCRIPTS)],
                       creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=si, timeout=60)
    assert p.returncode == 0 and result.is_file()
    got = json.loads(result.read_text(encoding="utf-8"))
    assert got == {"isatty": True, "written": 8, "keys": ["down", "up", "enter", "down", ""]}
