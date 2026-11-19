"""The third independent verification (of 9f2cb08, 2026-11-15): one regression per item, each written to fail first.
Its harness drove the real entry points; these pin each defect in-process, or in a real child process where the
defect is about the process itself (a NUL stdin)."""
from __future__ import annotations

import email.message
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch                        # noqa: E402
import install as inst              # noqa: E402
import installer_exit as ix         # noqa: E402
import thinker_flow as tf           # noqa: E402
import thinker_state as st          # noqa: E402
import thinker_update as tu         # noqa: E402
from test_thinker_flow import World, _dll  # noqa: E402
from test_thinker_install_review import _args, _fake_thinker_step, _first_install_plan, _raise  # noqa: E402
from test_thinker_install_verify import _doc, _serve  # noqa: E402
from test_thinker_update import KNOWN, NEW, OLD, V54, _folder  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")

REAL_CATALOGUE = inst.module_catalogue


def _t54_game(tmp_path, bak_path):
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx.exe")
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod v5.4"))
    return g


# ---------------------------------------------------------------- 1: the fatal refusal and the modules, no console

@pytest.mark.parametrize("how", ["no-console", "no-prompt-no-console", "no-wait-env"])
def test_keep_thinker_beside_a_fatal_build_is_refused_without_a_console(tmp_path, bak_path, monkeypatch, how):
    g = _t54_game(tmp_path, bak_path)
    _s, dll = st.classify(g, "0" * 64)
    _fake_thinker_step(monkeypatch, g)
    monkeypatch.setattr(inst, "module_catalogue", REAL_CATALOGUE)
    monkeypatch.setattr(ix, "stdin_is_console", lambda: how == "no-wait-env", raising=False)
    if how == "no-wait-env":
        monkeypatch.setenv("LONGEVITY_NO_WAIT", "1")
    if how == "no-prompt-no-console":
        ix.set_player_no_prompt(True)
    _serve(monkeypatch, _doc(fatal_sha=dll.sha256))
    with pytest.raises(ix.InstallerError) as e:
        inst._install(g, _args(no_prompt=how == "no-prompt-no-console", keep_thinker=True, with_thinker=False, ai="ask"))
    assert "does not start with your Thinker Mod 5.4, so it was not installed on its own" in e.value.message
    assert not (g / "uimod.dll").exists()


def test_no_prompt_without_a_console_installs_the_modules_on_offer(tmp_path, monkeypatch):
    # No local pack: in the main checkout payload_root is the repo, whose dist\ packs would be listed too (audit-n).
    empty = tmp_path / "no-local-pack"
    empty.mkdir()
    monkeypatch.setattr(inst, "default_pack", lambda: empty)
    monkeypatch.setattr(inst, "default_portrait_pack", lambda: empty)
    monkeypatch.setattr(ix, "stdin_is_console", lambda: False, raising=False)
    ix.set_player_no_prompt(True)
    fetched = _serve(monkeypatch, _doc(modules={"movies-hd": {"size": 1 << 20, "url": "https://x/m.zip"}}))
    args = _args(no_prompt=True, ai="ask", with_thinker=False)
    catalogue, _m = inst.module_catalogue(tmp_path, args)
    assert fetched and inst.pick_modules(catalogue, args, tmp_path)[0] == ["movies-hd"]


def test_an_off_pin_thinker_gets_its_manifest_without_flags_or_a_console(tmp_path, monkeypatch):
    (tmp_path / "thinker.dll").write_bytes(_dll(b"Thinker Mod v5.4"))
    monkeypatch.setattr(ix, "stdin_is_console", lambda: False, raising=False)
    fetched = _serve(monkeypatch, _doc())
    inst.module_catalogue(tmp_path, _args(ai="ask", with_thinker=False))
    assert fetched


# ---------------------------------------------------------------- 2: stdin from NUL is no console

_NUL_CHILD = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import installer_exit as ix
import install as inst
out = {"isatty": sys.stdin.isatty(), "console": ix.stdin_is_console(), "can_ask": ix.can_ask()}
try:
    inst._read_key()
    out["read_key"] = "returned"
except EOFError:
    out["read_key"] = "EOFError"
print(json.dumps(out))
'''


@pytest.mark.skipif(sys.platform != "win32", reason="a Windows console")
def test_stdin_from_nul_is_not_a_console_and_reading_a_key_does_not_hang(tmp_path):
    """`install.py < NUL` hung forever polling a console that does not exist: NUL passes isatty() on Windows."""
    child = tmp_path / "child.py"
    child.write_text(_NUL_CHILD, encoding="utf-8")
    p = subprocess.run([sys.executable, "-I", str(child), str(_SCRIPTS)], stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, timeout=60)
    got = json.loads(p.stdout.strip().splitlines()[-1])
    assert got == {"isatty": True, "console": False, "can_ask": False, "read_key": "EOFError"}, p.stderr


def test_a_failing_console_query_is_eof_never_an_endless_poll(monkeypatch):
    calls = []
    fake = types.SimpleNamespace(
        GetStdHandle=lambda h: 1,
        GetNumberOfConsoleInputEvents=lambda h, n: calls.append(1) or 0,     # the call fails
        ReadConsoleInputW=lambda *a: pytest.fail("nothing to read"))
    monkeypatch.setattr(inst, "_K32", fake)
    monkeypatch.setattr(ix, "stdin_is_console", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(inst.time, "sleep", lambda s: None)
    result = {}

    def go():
        try:
            inst._read_key()
            result["r"] = "returned"
        except EOFError:
            result["r"] = "EOFError"
    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(5)
    assert result.get("r") == "EOFError", f"still polling after {len(calls)} failed queries"


# ---------------------------------------------------------------- 3: an orphan .bak only in a Thinker folder

def test_a_plain_folder_with_only_the_pracx_bak_is_refused_before_any_question(tmp_path, bak_path, pristine_bytes):
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    (g / "terranx.exe").write_bytes(pristine_bytes)
    shutil.copy2(bak_path, g / "terranx_PRACX.exe.bak")
    assert inst.check_game_folder(g)[0] == "unsupported"
    (g / "thinker.dll").write_bytes(b"dll")
    (g / "thinker.exe").write_bytes(b"exe")
    assert inst.check_game_folder(g)[0] == inst.FOLDER_OK          # the Thinker set-up starts from that .bak


# ---------------------------------------------------------------- 4: --fix-thinker --no-prompt asks nothing

def test_fix_thinker_no_prompt_refuses_instead_of_asking(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, answers=[""])
    w.args.no_prompt = True
    with pytest.raises(ix.InstallerError) as e:
        w.run()
    assert w.asked == [] and w.committed == []
    assert "--no-prompt says not to ask, so nothing was updated" in e.value.message
    assert "--with-thinker" in e.value.remedy


@pytest.mark.parametrize("flag,committed", [("with_thinker", True), ("keep_thinker", False)])
def test_fix_thinker_takes_the_thinker_flags_without_asking(tmp_path, monkeypatch, flag, committed):
    w = World(tmp_path, monkeypatch, answers=[])
    w.args.no_prompt = True
    setattr(w.args, flag, True)
    try:
        w.run()
    except ix.InstallerError:
        pass
    assert w.asked == []
    assert (w.committed == [{"route": "thinker"}]) is committed


# ---------------------------------------------------------------- 5: finish removes the empty set before the journal

def test_finish_removes_the_empty_set_before_the_journal(tmp_path, monkeypatch):
    game, prep = _first_install_plan(tmp_path, {"terranx.exe": b"MZ"})
    tf.commit(prep, route="fresh")
    monkeypatch.setattr(tu, "finish", _raise(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        tf.finish(prep)
    assert not prep.report.backup_dir.exists()


# ---------------------------------------------------------------- 6: Ctrl-C inside Thinker's own commit

def _update_prep(tmp_path):
    game = _folder(tmp_path / "game", OLD)
    staged_dir = _folder(tmp_path / "staged", NEW)
    staged = {rel: staged_dir.joinpath(*rel.split("/")) for rel in NEW}
    p = tu.plan(game, "5.5.0", staged, known=KNOWN, old_stock=None, ts="5.5", from_label=V54)
    (game / "thinker.dll").write_bytes(b"old dll")
    dll = types.SimpleNamespace(label=V54)
    return game, tf.Prepared(game, tf.compiled_pin(), tf.compiled_meta(), dll, p, "5.5", st.UP)


def _tree(g):
    return {str(p.relative_to(g)): hashlib.md5(p.read_bytes()).hexdigest() for p in g.rglob("*") if p.is_file()}


@pytest.mark.parametrize("where", ["after_renames", "before_renames", "write_record"])
def test_ctrl_c_inside_the_commit_puts_thinker_back_and_says_so(tmp_path, monkeypatch, capsys, where):
    game, prep = _update_prep(tmp_path)
    before = _tree(game)
    older_backups = tu.older_backups                       # the real one, for the check below
    if where == "after_renames":
        monkeypatch.setattr(tu, "older_backups", _raise(KeyboardInterrupt()))
    elif where == "before_renames":
        real = tu._write_tmp
        n = []

        def write_tmp(dest, data):
            n.append(1)
            if len(n) == 2:
                raise KeyboardInterrupt
            return real(dest, data)
        monkeypatch.setattr(tu, "_write_tmp", write_tmp)
    else:
        monkeypatch.setattr(tf, "_write_record", _raise(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        tf.commit(prep, route="fresh")
    assert _tree(game) == before
    assert tu.read_journal(game) is None and older_backups(game) == []
    assert "Thinker Mod was put back as it was." in capsys.readouterr().out


def test_undo_takes_a_file_that_was_never_replaced_even_without_its_backup(tmp_path):
    """Stopped between the journal and the backups: the folder still holds the old files, so undo is complete."""
    g = tmp_path / "g"
    g.mkdir()
    (g / "thinker.dll").write_bytes(b"old")
    acts = [{"rel": "thinker.dll", "kind": "replace", "old": tu.sha256(g / "thinker.dll"), "new": "0" * 64}]
    assert tu._roll(g, acts, g / "no-such-set", False) == tu.UNDONE


# ---------------------------------------------------------------- 7: an uninstall with nothing to do writes nothing

def test_uninstall_with_nothing_installed_leaves_the_ini_untouched(tmp_path, bak_path, monkeypatch):
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    ini = g / "Alpha Centauri.ini"
    ini.write_bytes(b"[Alpha Centauri]\r\nFoo=1")
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    with pytest.raises(ix.InstallerError):
        inst.do_uninstall(g, types.SimpleNamespace(no_prompt=True, force=False))
    assert ini.read_bytes() == b"[Alpha Centauri]\r\nFoo=1"


# ---------------------------------------------------------------- 8: the cosmetic ones

def test_a_first_install_leaves_no_empty_backups_folder(tmp_path):
    game, prep = _first_install_plan(tmp_path, {"terranx.exe": b"MZ"})
    tf.commit(prep, route="fresh")
    tf.finish(prep)
    assert not (game / "LongevityMods" / "backups").exists()


def test_undone_first_install_leaves_no_empty_backups_folder(tmp_path):
    game, prep = _first_install_plan(tmp_path, {"terranx.exe": b"MZ"})
    tf.commit(prep, route="fresh")
    tf.undo(prep)
    assert not (game / "LongevityMods" / "backups").exists()


def test_the_installer_scripts_hold_no_tab_characters():
    bad = [f"{p.name}:{i}" for p in sorted(_SCRIPTS.glob("*.py")) if p.name in {
        "install.py", "thinker_flow.py", "installer_exit.py", "fetch.py", "bootstrap.py", "receipt.py",
        "thinker_update.py", "thinker_state.py", "thinker_source.py"}
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if "\t" in line]
    assert not bad, bad


def test_a_tampered_file_after_a_resumed_part_is_a_mismatch_not_a_connection_failure(tmp_path, monkeypatch, capsys):
    """The resumed part fails the hash, the clean restart fails it too (the server serves a tampered file): a
    MismatchError, with no "Could not reach the update server" line."""
    body = b"x" * 4000                                         # what the server serves: not the release
    sha = hashlib.sha256(b"y" * 4000).hexdigest()

    class Resp(io.BytesIO):
        def __init__(self, data, status, start):
            super().__init__(data)
            self.status = status
            h = email.message.Message()
            h["Content-Length"] = str(len(data))
            if status == 206:
                h["Content-Range"] = f"bytes {start}-{len(body) - 1}/{len(body)}"
            self.headers = h

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    def open_(req, timeout=None):
        r = req.get_header("Range")
        if r:
            start = int(r.split("=")[1].rstrip("-"))
            return Resp(body[start:], 206, start)
        return Resp(body, 200, 0)
    monkeypatch.setattr(fetch, "_opener", lambda allow_file=False: types.SimpleNamespace(open=open_))
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    (tmp_path / "z.zip.part").write_bytes(b"x" * 1000)
    with pytest.raises(fetch.MismatchError):
        fetch.download("https://example.invalid/z.zip", tmp_path / "z.zip", sha256=sha, size=len(body), label="z")
    assert "Could not reach the update server" not in capsys.readouterr().out
