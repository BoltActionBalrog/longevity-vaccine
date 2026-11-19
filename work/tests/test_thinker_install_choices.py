"""The Thinker choices as arrow-key lists (user 2026-11-15, feat/thinker-install):

* B, the new screen: a setup run in a folder with no thinker.dll offers Thinker Mod ("Only install Longevity
  Vaccine" first, the marker on it; "Also install Thinker Mod 5.5" downloads, installs and sets the folder up);
* C, Q1 (setup and updater runs) and D, journey R: the recommended change first, the marker on it;
* the rows keep their own colours (the marker alone shows the choice); Ctrl-C still stops with nothing changed.

The Q1 / journey R wording itself is in test_thinker_flow.py; the modules list's Continue row in
test_install_console.py.
"""
from __future__ import annotations

import ast
import os
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
from test_thinker_flow import World, _dll, _game  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")     # install.py's run-wide globals reset per test

NEW_NOTES = [
    "Thinker Mod is a separate mod for Alpha Centauri that is compatible with Longevity Vaccine. It rewrites the "
    "computer players' AI, adds new game rules & options, changes map generation, and much more.",
    "",
    "Thinker Mod is only recommended for players who want a more challenging experience than vanilla Alpha Centauri.",
    "",
    "This installer can download Thinker Mod 5.5 and set it up for you.",
    "",
    "Thinker Mod is a project by Induktio and is not affiliated with Longevity Vaccine. Learn more here: "
    "https://github.com/induktio/thinker/blob/master/Details.md",          # for players new to Thinker (user 2026-11-16)
]


class Menu:
    """install._arrow_menu, faked: records every call, answers with the given option indexes (or raises)."""

    def __init__(self, monkeypatch, *answers):
        self.calls, self.answers = [], list(answers)
        monkeypatch.setattr(inst, "_arrow_menu", self)

    def __call__(self, title, items, before=(), at=0, notes=(), title_kind=None):
        self.calls.append(dict(title=title, options=[i[0] for i in items], notes=list(notes), at=at,
                               title_kind=title_kind))
        a = self.answers.pop(0)
        if isinstance(a, BaseException):
            raise a
        return a


@pytest.fixture
def prepared(monkeypatch):
    calls = []
    monkeypatch.setattr(tf, "prepare", lambda *a, **k: calls.append((a, k)) or types.SimpleNamespace(new=True))
    return calls


def _empty(tmp_path) -> Path:
    g = tmp_path / "game"
    g.mkdir()
    return g


# ---------------------------------------------------------------- B: the new screen

def test_the_new_screen_reads_as_ruled_and_starts_on_only_install(tmp_path, monkeypatch, prepared):
    monkeypatch.setattr(tf, "_asks", lambda a: True)
    m = Menu(monkeypatch, 0)
    r = tf.offer_thinker_install(_empty(tmp_path), types.SimpleNamespace(), "1.0.0")
    assert r.prep is None and not r.keep and not prepared
    c = m.calls[0]
    assert c["title"] == "Thinker Mod" and c["title_kind"] == "keys" and c["at"] == 0
    assert c["notes"] == NEW_NOTES
    assert c["options"] == ["Only install Longevity Vaccine", "Also install Thinker Mod 5.5"]


def test_also_install_downloads_and_plans_the_pinned_build(tmp_path, monkeypatch, prepared):
    monkeypatch.setattr(tf, "_asks", lambda a: True)
    Menu(monkeypatch, 1)
    g = _empty(tmp_path)
    r = tf.offer_thinker_install(g, types.SimpleNamespace(), "1.0.0")
    assert r.prep is not None and r.accepted == "above"
    (args, kw), = prepared
    assert args[0] == g and args[1].pin_id == tf.compiled_pin().pin_id and args[3] == "1.0.0"
    assert kw == {"route": "B", "fresh": True}


def test_with_thinker_chooses_also_install_without_asking(tmp_path, monkeypatch, prepared):
    m = Menu(monkeypatch)
    r = tf.offer_thinker_install(_empty(tmp_path), types.SimpleNamespace(with_thinker=True), "1.0.0")
    assert r.prep is not None and r.accepted == "flag" and not m.calls


@pytest.mark.parametrize("args,asks", [
    (types.SimpleNamespace(keep_thinker=True), True),
    (types.SimpleNamespace(no_prompt=True), True),            # _asks reads --no-prompt itself; faked False below
    (types.SimpleNamespace(), False),                         # unattended: no console
])
def test_unattended_or_keep_thinker_runs_choose_only_install(tmp_path, monkeypatch, prepared, args, asks):
    monkeypatch.setattr(ix, "can_ask", lambda: asks)
    monkeypatch.setattr(ix, "is_worker", lambda: False)
    m = Menu(monkeypatch)
    r = tf.offer_thinker_install(_empty(tmp_path), args, "1.0.0")
    assert r.prep is None and not m.calls and not prepared


def test_a_folder_with_thinker_never_sees_the_screen(tmp_path, monkeypatch, prepared):
    monkeypatch.setattr(tf, "_asks", lambda a: True)
    m = Menu(monkeypatch)
    assert tf.offer_thinker_install(_game(tmp_path), types.SimpleNamespace(with_thinker=True), "1.0.0").prep is None
    assert not m.calls and not prepared


def test_ctrl_c_on_the_new_screen_stops_with_nothing_changed(tmp_path, monkeypatch, prepared):
    monkeypatch.setattr(tf, "_asks", lambda a: True)
    Menu(monkeypatch, KeyboardInterrupt())
    with pytest.raises(ix.InstallerError) as e:
        tf.offer_thinker_install(_empty(tmp_path), types.SimpleNamespace(), "1.0.0")
    assert e.value.message == "You stopped the installer, so nothing was changed." and e.value.changed is False


def test_the_new_screen_colours(tmp_path, monkeypatch, prepared):
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    R, G, B, Y, X = ix._RED, ix._GREEN, ix._BLUE, ix._YELLOW, ix._RESET
    monkeypatch.setattr(tf, "_asks", lambda a: True)
    m = Menu(monkeypatch, 0)
    tf.offer_thinker_install(_empty(tmp_path), types.SimpleNamespace(), "1.0.0")
    c = m.calls[0]
    assert c["notes"][2] == (f"Thinker Mod is only recommended for players who want a {Y}more challenging{X} experience "
                             "than vanilla Alpha Centauri.")
    assert c["notes"][4] == f"This installer can download Thinker Mod {G}5.5{X} and set it up for you."
    assert c["notes"][6] == (f"Thinker Mod is a project by {B}Induktio{X} and is not affiliated with Longevity Vaccine. "
                             f"Learn more here: {B}https://github.com/induktio/thinker/blob/master/Details.md{X}")
    assert c["options"] == ["Only install Longevity Vaccine", f"Also install {B}Thinker Mod{X} {G}5.5{X}"]


def test_the_real_menu_draws_the_block_and_moves_the_marker(tmp_path, monkeypatch, capsys, prepared):
    """The real install._arrow_menu: the blue title, the keys hint, the notes, the marker on the first row and only
    the marker (no green); typed-ahead keys dropped before drawing; Down then Enter takes the second row."""
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)
    monkeypatch.setattr(tf, "_asks", lambda a: True)
    dropped = []
    monkeypatch.setattr(inst, "_drop_typed_ahead", lambda: dropped.append(True))
    keys = iter(["down", "enter"])
    monkeypatch.setattr(inst, "_read_key", lambda: next(keys))
    r = tf.offer_thinker_install(_empty(tmp_path), types.SimpleNamespace(), "1.0.0")
    out = capsys.readouterr().out
    assert dropped and r.prep is not None
    lines = out.split("\n")
    i = lines.index(" THINKER MOD")
    n = len(NEW_NOTES)
    assert lines[i - 1] == ix.RULE
    assert lines[i + 1:i + 1 + n] == [(" " + t) if t else " " for t in NEW_NOTES]
    # user 2026-11-15: the keys on their own line directly above the first option
    assert lines[i + 1 + n:i + 1 + n + 5] == [ix.RULE, " Up/Down: move   Enter: choose",
                                             " -> Only install Longevity Vaccine", "    Also install Thinker Mod 5.5",
                                             ix.RULE]
    assert out.count("Up/Down: move   Enter: choose") == 1      # a redraw rewrites the rows, never the keys line


# ---------------------------------------------------------------- B: a first Thinker install, end to end

def test_also_install_sets_the_folder_up_for_thinker_before_the_patch_pass(tmp_path, bak_path, monkeypatch):
    """Thinker Mod chosen for a folder without it is in place before the target is resolved and the exe patched:
    terranx.exe becomes the pracx_thinker build, thinker.exe starts the game, and the verdict says both."""
    import receipt as rc
    inst._load_modules()
    g = _empty(tmp_path)
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    calls = []
    prep = types.SimpleNamespace(new=True, ts="5.5", committed=False, dll=None, direction=st.OTHER)
    monkeypatch.setattr(tf, "prepare", lambda *a, **k: calls.append(("prepare", k)) or prep)

    def commit(p, route, exe=None):
        calls.append(("commit", route, (g / "terranx.exe").exists()))
        (g / "thinker.dll").write_bytes(b"not a real dll")
        (g / "thinker.exe").write_bytes(b"MZ")
        p.committed = True
    monkeypatch.setattr(tf, "commit", commit)
    monkeypatch.setattr(tf, "finish", lambda p: calls.append(("finish",)))
    monkeypatch.setattr(tf, "summary_lines", lambda p: ["  Thinker Mod 5.5: installed (28 files added)"])
    monkeypatch.setattr(tf, "undo", lambda p: pytest.fail("nothing failed, so nothing is undone"))
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setattr(inst, "module_catalogue", lambda gd, a: ([], None))
    monkeypatch.setattr(inst, "pick_modules", lambda c, a, gd: ([], [], []))
    monkeypatch.setattr(inst, "_deploy_resident", lambda gd: None)
    monkeypatch.setattr(inst, "deploy_runtime", lambda gd, quiet=False: True)
    args = types.SimpleNamespace(no_prompt=False, ai="off", modules=None, force=False, manifest=None, offline=False,
                                 pack=None, portrait_pack=None, with_thinker=True, keep_thinker=False)
    assert inst._install(g, args) == 0
    table = ap.load_targets(ap.DEFAULT_PATCHES)
    assert calls[0] == ("prepare", {"route": "B", "fresh": True})
    assert calls[1] == ("commit", "fresh", False)            # Thinker first, before the set-up made terranx.exe
    assert inst._md5_or_none(g / "terranx.exe") == table["pracx_thinker"].patched_md5
    assert rc.ini_get(g, rc.KEY_TARGET) == "pracx_thinker"
    assert inst._LAUNCH_EXE is not None and inst._LAUNCH_EXE.name == "thinker.exe"
    assert inst._VERDICT == ("INSTALLATION SUCCESSFUL",
                             f"Longevity Vaccine {inst.ver.VERSION} is installed. Thinker Mod 5.5 was installed.")
    # the play note: no "as before" for a Thinker Mod this run installed (user 2026-11-15: "Yes, change it")
    monkeypatch.setattr(inst, "find_shortcut_to", lambda exe: None)
    said = []
    monkeypatch.setattr(ix, "good", lambda t: said.append(t))
    monkeypatch.setattr(ix, "warn", lambda t: said.append(t))
    inst.print_play_note(g, "pracx_thinker")
    assert "To play with Longevity Vaccine, start thinker.exe." in said


@pytest.mark.parametrize("label,direction,verdict", [
    (b"Thinker Mod v5.4", st.UP, " Thinker Mod was updated to 5.5."),
    (b"Thinker Mod v5.8", st.DOWN, " Thinker Mod was downgraded to 5.5."),
    (b"Thinker Mod develop build", st.OTHER,
     " Thinker Mod 5.5 was installed in place of your development build of Thinker Mod."),
], ids=["up", "down", "other"])
def test_a_setup_that_changes_thinker_builds_its_verdict(tmp_path, bak_path, monkeypatch, label, direction, verdict):
    """Walkthrough Part 3 (2026-11-15): a first install over an existing Thinker Mod, "Also update" chosen, crashed
    AFTER every write with NameError: name 'thinker_flow' is not defined -- _install_rest named thinker_flow
    without importing it. No test reached that verdict: the e2e runs always add --keep-thinker (their thinker.dll is
    a stand-in) and the end-to-end test above takes the new-install branch. This runs the real _install, patch pass
    included (~4 s each, one per direction; they split across xdist workers), through to the verdict."""
    inst._load_modules()
    g = _game(tmp_path, label)
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    _s, dll = st.classify(g, "0" * 64)
    calls = []
    prep = types.SimpleNamespace(new=False, ts="5.5", committed=False, dll=dll, direction=direction)
    monkeypatch.setattr(tf, "prepare", lambda *a, **k: calls.append(("prepare", k)) or prep)

    def commit(p, route, exe=None):
        calls.append(("commit", route))
        p.committed = True
    monkeypatch.setattr(tf, "commit", commit)
    monkeypatch.setattr(tf, "finish", lambda p: calls.append(("finish",)))
    monkeypatch.setattr(tf, "summary_lines", lambda p: ["  Thinker Mod 5.5: updated"])
    monkeypatch.setattr(tf, "undo", lambda p: pytest.fail("nothing failed, so nothing is undone"))
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setattr(inst, "module_catalogue", lambda gd, a: ([], None))
    monkeypatch.setattr(inst, "pick_modules", lambda c, a, gd: ([], [], []))
    monkeypatch.setattr(inst, "_deploy_resident", lambda gd: None)
    monkeypatch.setattr(inst, "deploy_runtime", lambda gd, quiet=False: True)
    args = types.SimpleNamespace(no_prompt=False, ai="off", modules=None, force=False, manifest=None, offline=False,
                                 pack=None, portrait_pack=None, with_thinker=True, keep_thinker=False)
    assert inst._install(g, args) == 0
    assert ("commit", "fresh") in calls and ("finish",) in calls
    assert inst._VERDICT == ("INSTALLATION SUCCESSFUL", f"Longevity Vaccine {inst.ver.VERSION} is installed." + verdict)
    assert inst._THINKER_NEW is False


def test_no_function_uses_a_module_it_never_imports():
    """The class of the Part 3 crash: these modules import some modules inside functions only (to keep start-up and
    the bootstrap light). A function -- or a function nested in one -- that names such a module must import it in
    its own scope chain; a sibling's import does not count. Static, so it covers branches no run reaches."""
    bad = []
    for name in ("install.py", "bootstrap.py", "installer_exit.py", "thinker_flow.py", "thinker_state.py",
                 "fetch.py", "manifest.py", "preflight.py", "transact.py", "receipt.py", "patch_helptext.py"):
        path = Path(inst.__file__).parent / name
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bad += _unimported_uses(tree, name)
    assert not bad, "\n".join(bad)


_FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)


def _imported(node) -> set:
    return {(a.asname or a.name).split(".")[0] for a in node.names}


def _children(n) -> list:
    """A scope's own statements (a def's or class's body), else a node's children."""
    if isinstance(n, (*_FUNC, ast.ClassDef)):
        return list(n.body)
    return list(ast.iter_child_nodes(n))


def _scope_bindings(owner) -> set:
    """Names one scope binds (its parameters, imports, assignments, defs), not descending into nested functions,
    classes or lambdas -- those are scopes of their own."""
    out = {a.arg for a in ast.walk(owner.args) if isinstance(a, ast.arg)} if isinstance(owner, _FUNC) else set()
    todo = _children(owner)
    while todo:
        n = todo.pop()
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            out |= _imported(n)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, (*_FUNC, ast.ClassDef)):
            out.add(n.name)
            continue
        elif isinstance(n, ast.Lambda):
            continue
        todo.extend(ast.iter_child_nodes(n))
    return out


def _unimported_uses(tree, name: str) -> list:
    top = _scope_bindings(tree)
    local_only = {m for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                  for m in _imported(n)} - top
    bad = []

    def visit(fn, outer: set):
        here = outer | _scope_bindings(fn)
        todo = _children(fn)
        while todo:
            n = todo.pop()
            if isinstance(n, _FUNC):
                visit(n, here)                          # a closure sees its enclosing function's names
                continue
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in local_only and n.id not in here:
                bad.append(f"{name}:{n.lineno}: {fn.name} uses {n.id} without importing it")
            todo.extend(ast.iter_child_nodes(n))

    # every function not nested in another: module level (under if / try too) and class methods
    todo = list(tree.body)
    while todo:
        n = todo.pop()
        if isinstance(n, _FUNC):
            visit(n, set())
        elif not isinstance(n, ast.expr):
            todo.extend(_children(n))
    return sorted(set(bad))
    assert not any("as before" in t for t in said)


def test_a_folder_that_already_had_thinker_keeps_as_before(tmp_path, monkeypatch):
    """Only a Thinker Mod installed by this run drops "as before": a player who already starts thinker.exe keeps it."""
    inst._load_modules()
    g = _empty(tmp_path)
    (g / "thinker.exe").write_bytes(b"MZ")
    (g / "terranx.exe").write_bytes(b"MZ")
    monkeypatch.setattr(inst, "_THINKER_NEW", False)
    monkeypatch.setattr(inst, "find_shortcut_to", lambda exe: None)
    monkeypatch.setattr(tf, "offer_changelog", lambda g, t: None)
    said = []
    monkeypatch.setattr(ix, "good", lambda t: said.append(t))
    monkeypatch.setattr(ix, "warn", lambda t: said.append(t))
    inst.print_play_note(g, "pracx_thinker")
    assert "To play with Longevity Vaccine, start thinker.exe as before." in said


# ---------------------------------------------------------------- a first install's own lines

def test_a_first_install_says_installing_and_keeps_no_empty_backup(tmp_path, monkeypatch):
    import fetch
    said = []
    monkeypatch.setattr(ix, "say", lambda *p: said.append(" ".join(map(str, p))))

    def download(url, dest, **kw):
        raise fetch.FetchError("stop here")
    monkeypatch.setattr(fetch, "download", download)
    with pytest.raises(ix.InstallerError) as e:
        tf.prepare(_empty(tmp_path), tf.compiled_pin(), tf.compiled_meta(), "1.0.0", route="B", fresh=True)
    assert "  Installing Thinker Mod 5.5" in said and not any("->" in s for s in said)
    assert "so nothing was installed" in e.value.message
    # summary and finish of a first install
    bdir = tmp_path / "game" / "LongevityMods" / "backups" / "thinker-other-1"
    bdir.mkdir(parents=True)
    report = types.SimpleNamespace(added=28, replaced=0, kept_or_merged=1, backup_dir=bdir, older_backups=0)
    plan = types.SimpleNamespace(kept_alphax=True, ini=None, user_ini=None, actions=[])
    prep = tf.Prepared(tmp_path / "game", tf.compiled_pin(), tf.compiled_meta(), None, plan, "5.5", st.OTHER,
                       report=report, committed=True, new=True)
    assert tf.summary_lines(prep) == [
        "  Thinker Mod 5.5: installed (28 files added)",
        "  Kept as it is: alphax.txt (your rules file in the game folder; Thinker Mod's copy is optional)"]
    monkeypatch.setattr(tf.tu, "finish", lambda g: None)
    tf.finish(prep)
    assert not bdir.exists(), "a first install backs nothing up: no empty set is left"


# ---------------------------------------------------------------- D: journey R, the third form

def test_journey_r_other_form_and_its_cancel_line(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, label=b"Thinker Mod develop build", answers=["n"])
    with pytest.raises(ix.InstallerError) as e:
        w.run()
    options, notes = w.asked[0]
    assert options == ["Replace your development build of Thinker Mod with Thinker Mod 5.5",
                       "Keep your development build of Thinker Mod"]
    assert notes[-1] == tf.project_line()                  # no "If you choose 'Keep ...'" (user 2026-11-15)
    assert e.value.title == "UPDATE CANCELLED" and e.value.message.startswith(
        "You chose to keep your development build of Thinker Mod, so nothing was changed.")


def test_journey_r_options_are_coloured_by_the_prompt_line_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    R, G, B, X = ix._RED, ix._GREEN, ix._BLUE, ix._RESET
    w = World(tmp_path, monkeypatch, label=b"Thinker Mod v5.8", answers=["n"])
    with pytest.raises(ix.InstallerError):
        w.run()
    assert w.asked[0][0] == [f"Downgrade {B}Thinker Mod{X} from {R}5.8{X} to {G}5.5{X}", f"Keep {B}Thinker Mod{X} {R}5.8{X}"]
    w2 = World(tmp_path / "d", monkeypatch, label=b"Thinker Mod develop build", answers=["n"]) \
        if (tmp_path / "d").mkdir() is None else None
    with pytest.raises(ix.InstallerError):
        w2.run()
    assert w2.asked[0][0] == [f"Replace your {R}development build of Thinker Mod{X} with {B}Thinker Mod{X} {G}5.5{X}",
                              f"Keep your {R}development build of Thinker Mod{X}"]


# ---------------------------------------------------------------- C: Q1 ends at the project line

@pytest.mark.parametrize("label", [b"Thinker Mod v5.4", b"Thinker Mod v5.8", b"Thinker Mod develop build"],
                         ids=["up", "down", "other"])
@pytest.mark.parametrize("fresh,only", [(True, "Only install Longevity Vaccine"),
                                        (False, "Only update Longevity Vaccine")], ids=["setup", "update"])
def test_q1_has_no_if_you_choose_sentence(tmp_path, label, fresh, only):
    """User 2026-11-15: "Drop " If you choose 'Only install Longevity Vaccine', Longevity Vaccine 1.0.0 is installed
    on its own and your Thinker Mod 5.4 stays as it is; the game will then tell you the two do not match, and can
    change Thinker Mod for you later."" -- in both forms (setup / updater) and every direction: the notes end at the
    project line, with no blank line after it. The option itself keeps its name."""
    g = _game(tmp_path, label)
    _s, dll = st.classify(g, "0" * 64)
    _t, notes, options = tf.q1_texts(dll, "1.0.0", tf.compiled_pin(), tf.compiled_meta(), fresh=fresh, fatal=False)
    assert options[1] == only
    assert notes[-1] == tf.project_line() and notes[-2] == ""
    text = " ".join(notes)
    for gone in ("If you choose", "on its own", "do not match", "for you later", "stays as it is"):
        assert gone not in text, gone


def test_only_the_fatal_sentences_stay(tmp_path):
    """Q1's "If you choose 'Only ...'" and journey R's two "If you choose 'Keep ...'" sentences are gone (user
    2026-11-15); the fatal ones ("...so if you cancel, ..." / "...so if you keep it, ...") say something else and
    stay, after one blank line. Journey R's fatal form: test_fix_thinker_longevity_only_refused_for_fatal."""
    g = _game(tmp_path)
    _s, dll = st.classify(g, "0" * 64)
    _t, notes, _o = tf.q1_texts(dll, "1.0.0", tf.compiled_pin(), tf.compiled_meta(), fresh=True, fatal=True)
    assert notes[-3:] == [tf.project_line(), "", "Longevity Vaccine 1.0.0 does not start with your Thinker Mod 5.4, "
                                                 "so if you cancel, nothing is installed."]
    assert tf.thinker_block("first", ["can"], st.UP, "5.5")[-2:] == ["", tf.project_line()]


@pytest.mark.parametrize("label,answers", [(b"Thinker Mod v5.4", ["n"]), (b"Thinker Mod v5.8", ["n"]),
                                           (b"Thinker Mod develop build", ["n"])], ids=["up", "down", "other"])
def test_journey_r_q_t_ends_at_the_project_line(tmp_path, monkeypatch, label, answers):
    """User 2026-11-15 ("Yes, drop those two"): the Update now window's Thinker question has no "If you choose
    'Keep ...'" sentence in any direction; the block ends at the project line, no blank line after it."""
    w = World(tmp_path, monkeypatch, label=label, answers=answers)
    with pytest.raises(ix.InstallerError):
        w.run()
    notes = w.asked[0][1]
    assert notes[-1] == tf.project_line() and notes[-2] == ""
    assert "If you choose" not in " ".join(notes)


# ---------------------------------------------------------------- D: journey R's Longevity Vaccine question

def test_the_longevity_question_is_a_choice_too(tmp_path, monkeypatch):
    """User 2026-11-15 ("Yes to both"): "Update Longevity Vaccine to 9.9.9" / "Keep Longevity Vaccine 1.0.0", the first
    one first with the marker on it; its notes name the keep option; its title stays plain (no Thinker blue)."""
    w = World(tmp_path, monkeypatch, latest="9.9.9", answers=["n", "n"])
    v = tf._ver().VERSION
    with pytest.raises(ix.InstallerError):
        w.run()
    options, notes = w.asked[0]
    assert options == ["Update Longevity Vaccine to 9.9.9", f"Keep Longevity Vaccine {v}"]
    # the "If you choose 'Keep ...'" sentence was dropped (user 2026-11-17; test_ql_wording)
    assert notes[-1] == "This installer will offer to update Thinker for you."
    assert w.title_kinds[0] == ("Longevity Vaccine update", None)
    assert not any("answer" in n for n in notes)


def test_keeping_longevity_when_thinker_cannot_change_alone_is_cancelled(tmp_path, monkeypatch):
    """A Longevity Vaccine update was downloaded but not installed, and its Thinker pin differs: keeping Longevity
    Vaccine leaves nothing to do. UPDATE CANCELLED names what was kept, then why."""
    w = World(tmp_path, monkeypatch, installed="0.9.0", latest="9.9.9", answers=["n"])
    w.doc["thinker"]["release_pins"]["0.9.0"] = "5.7.0"
    with pytest.raises(ix.InstallerError) as e:
        w.run()
    assert e.value.title == "UPDATE CANCELLED" and e.value.code == ix.EXIT_DECLINED
    assert e.value.message.startswith(
        "You chose to keep Longevity Vaccine 0.9.0, so nothing was changed. A Longevity Vaccine update was downloaded "
        "but not installed, so Thinker Mod can only be changed together with that update.")


def test_the_updaters_own_cancel_line_names_no_answer(monkeypatch, capsys):
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)
    ix.run_guarded(lambda: ix.EXIT_DECLINED)
    out = capsys.readouterr().out
    assert "You cancelled the update, so your game files were not changed." in out and "answered no" not in out


def test_an_in_place_redraw_rewrites_the_rows_and_keeps_the_keys_line(monkeypatch, capsys):
    """User 2026-11-15: the keys line sits above the rows; a redraw moves the cursor up over the rows ONLY (two
    options and the closing rule: three lines), so it neither eats the keys line nor prints it twice."""
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)
    monkeypatch.setattr(ix, "can_redraw", lambda: True)
    monkeypatch.setattr(inst, "_drop_typed_ahead", lambda: None)
    keys = iter(["down", "enter"])
    monkeypatch.setattr(inst, "_read_key", lambda: next(keys))
    assert inst._arrow_menu("Pick", [["first"], ["second"]], notes=["a note"]) == 1
    out = capsys.readouterr().out
    head = f" PICK\n a note\n{ix.RULE}\n Up/Down: move   Enter: choose\n -> first\n    second\n{ix.RULE}\n"
    assert head in out
    assert out.endswith(f"\x1b[3F\x1b[J    first\n -> second\n{ix.RULE}\n")
    assert out.count("Up/Down: move") == 1


# ---------------------------------------------------------------- the order on a first install (user 2026-11-15)

@pytest.mark.parametrize("thinker", [None, b"Thinker Mod v5.4"], ids=["no-thinker", "thinker-5.4"])
def test_the_thinker_question_comes_before_automatic_updates_and_the_download_after(tmp_path, bak_path, monkeypatch,
                                                                                    thinker):
    """Folder, optional modules, then the Thinker question (the new screen, or Q1 when Thinker is there), then
    AUTOMATIC UPDATES; the Thinker download only after every question."""
    inst._load_modules()
    g = _empty(tmp_path)
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    if thinker:
        (g / "thinker.dll").write_bytes(_dll(thinker))
    events = []

    def menu(title, items, before=(), at=0, notes=(), title_kind=None):
        events.append(title)
        return 1 if title == "Thinker Mod" and not thinker else 0          # "Also install" / "Also update"
    monkeypatch.setattr(inst, "_arrow_menu", menu)

    class Stop(Exception):
        pass

    def prepare(*a, **k):
        events.append("download")
        raise Stop
    monkeypatch.setattr(tf, "prepare", prepare)
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    monkeypatch.setattr(ix, "is_worker", lambda: False)
    monkeypatch.setattr(inst, "_has_install", lambda gd: False)
    monkeypatch.setattr(inst, "module_catalogue", lambda gd, a: ([], None))
    monkeypatch.setattr(inst, "pick_modules", lambda c, a, gd: ([], [], []))
    args = types.SimpleNamespace(no_prompt=False, ai="off", modules=None, force=False, manifest=None, offline=False,
                                 pack=None, portrait_pack=None)
    with pytest.raises(Stop):
        inst._install(g, args)
    assert events == ["Thinker Mod", "Automatic updates", "download"]
    assert not (g / "Alpha Centauri.ini").exists() or "CheckForUpdates" not in (g / "Alpha Centauri.ini").read_text(
        encoding="mbcs"), "nothing is written before the download"


# ---------------------------------------------------------------- the "->" marker (user 2026-11-15)

def test_the_marker_is_an_arrow_pair_and_the_other_rows_line_up():
    assert ix.marked("Also install Thinker Mod 5.5", True) == " -> Also install Thinker Mod 5.5"
    assert ix.marked("Only install Longevity Vaccine", False) == "    Only install Longevity Vaccine"
    assert len(ix.MARK_ON) == len(ix.MARK_OFF)          # every row's text starts in the same column


def test_a_wrapped_row_with_its_closing_arrow_is_counted_by_the_lines_it_takes(monkeypatch, capsys):
    """A long row (a long game path) wraps: _screen_lines counts its visible length, the arrow included, so
    the redraw moves the cursor back over every line the old rows took -- no line left behind, none eaten."""
    import shutil as _sh
    monkeypatch.setattr(_sh, "get_terminal_size", lambda fallback=(80, 24): os.terminal_size((40, 24)))
    long = "D:\\" + "a" * 45                                  # 48 characters of text
    assert ix._screen_lines([ix.marked(long, True)]) == 2       # 4 + 48 = 52 -> two lines of 40
    assert ix._screen_lines([ix.marked(long, False)]) == 2      # 4 + 48 = 52 -> two lines
    assert ix._screen_lines([ix.marked("b" * 36, False)]) == 1  # exactly 40 -> one line
    assert ix._screen_lines([ix.marked("b" * 36, True)]) == 1   # exactly 40 with the arrow -> one line
    assert ix._screen_lines([ix.marked("b" * 37, True)]) == 2   # one more character wraps
    # the real menu: two rows, the first wraps; moving down rewrites 2 + 1 + 2 lines (the 60-column rule wraps too)
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)
    monkeypatch.setattr(ix, "can_redraw", lambda: True)
    monkeypatch.setattr(inst, "_drop_typed_ahead", lambda: None)
    keys = iter(["down", "enter"])
    monkeypatch.setattr(inst, "_read_key", lambda: next(keys))
    assert inst._arrow_menu("Pick", [[long], ["short"]]) == 1
    out = capsys.readouterr().out
    assert f"\x1b[5F\x1b[J    {long}\n -> short\n{ix.RULE}\n" in out


# ---------------------------------------------------------------- the selected row is green as a whole (user 2026-11-15)

def test_the_selected_row_is_one_green_run_and_the_others_keep_their_colours(monkeypatch):
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    R, G, B, X = ix._RED, ix._GREEN, ix._BLUE, ix._RESET
    row = f"Also update {B}Thinker Mod{X} from {R}5.4{X} to {G}5.5{X}"
    on = ix.marked(row, True)
    assert on == f"{G} -> Also update Thinker Mod from 5.4 to 5.5{X}"
    assert on.count("\x1b[") == 2                              # exactly one colour run: green, then the reset
    assert ix.marked(row, False) == "    " + row               # off the marker: its own colours, untouched


def test_without_colour_the_marker_is_plain(monkeypatch):
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)
    assert ix.marked("Only install Longevity Vaccine", True) == " -> Only install Longevity Vaccine"


def test_the_modules_list_keeps_its_tick_colours_under_a_plain_marker(monkeypatch):
    """The one exception to the whole-row green (user 2026-11-15: "Don't use the green highlighting for the
    "Choose optional modules" selection. Using it there makes it look like we've ticked a row that we didn't."):
    a selected pack row keeps its own colour -- red unticked, green ticked -- behind a plain " -> "."""
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    G, R, X = ix._GREEN, ix._RED, ix._RESET
    cat = {"movies-hd": {"size": 1 << 30}, "portraits-hd": {"size": 50 << 20}}
    ticks = {"movies-hd": False, "portraits-hd": True}
    on = inst._picker_rows(["movies-hd", "portraits-hd"], cat, ticks, 0)
    assert on[0].startswith(f" -> {R}[ ] ") and G not in on[0]  # selected, unticked: still red, the arrow plain
    assert on[1].startswith(f"    {G}[X] ")
    off = inst._picker_rows(["movies-hd", "portraits-hd"], cat, ticks, 1)
    assert off[0].startswith(f"    {R}[ ] ")
    assert off[1].startswith(f" -> {G}[X] ") and off[1].count("\x1b[") == 2   # ticked: its own green, one run
    assert ix.marked(f"{R}x{X}", True, whole_row=False) == f" -> {R}x{X}"


def test_the_modules_continue_row_is_still_green_as_a_whole(monkeypatch):
    """Only the pack rows are the exception: the "Continue" row keeps the whole-row green of every other list."""
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    G, X = ix._GREEN, ix._RESET
    cat = {"movies-hd": {"size": 1 << 30}}
    for ticks, last in (({"movies-hd": True}, inst.INSTALL_SELECTED), ({"movies-hd": False}, inst.SKIP_MODULES)):
        assert inst._picker_rows(["movies-hd"], cat, ticks, 1)[1] == f"{G} -> {last}{X}"
        assert inst._picker_rows(["movies-hd"], cat, ticks, 0)[1] == f"    {last}"


def test_the_real_menu_paints_the_selected_thinker_option_green_as_a_whole(monkeypatch, capsys):
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    monkeypatch.setattr(ix, "can_redraw", lambda: True)
    monkeypatch.setattr(inst, "_drop_typed_ahead", lambda: None)
    keys = iter(["down", "enter"])
    monkeypatch.setattr(inst, "_read_key", lambda: next(keys))
    G, B, X = ix._GREEN, ix._BLUE, ix._RESET
    opt = f"Also install {B}Thinker Mod{X} {G}5.5{X}"
    assert inst._arrow_menu("Thinker Mod", [["Only install Longevity Vaccine"], [opt]]) == 1
    out = capsys.readouterr().out
    first, redrawn = out.split("\x1b[J")
    assert f"{G} -> Only install Longevity Vaccine{X}\n    {opt}\n" in first      # first draw: option 1 selected
    assert redrawn.startswith(f"    Only install Longevity Vaccine\n{G} -> Also install Thinker Mod 5.5{X}\n")
