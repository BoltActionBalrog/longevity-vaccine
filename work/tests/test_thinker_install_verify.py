"""The independent verification of 7b53fbb (2026-11-15): one regression per confirmed finding, each written to fail
first. Its harness drove the real entry points with fault injection; these pin each defect in-process."""
from __future__ import annotations

import email.message
import hashlib
import io
import shutil
import sys
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
import version as ver               # noqa: E402
from test_thinker_flow import _dll  # noqa: E402
from test_thinker_install_review import _args, _fake_thinker_step, _first_install_plan, _raise  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")

#: The real module_catalogue, taken before any test replaces it (_fake_thinker_step fakes it).
REAL_CATALOGUE = inst.module_catalogue


def _console_no_prompt(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    ix.set_player_no_prompt(True)


def _doc(*, fatal_sha=None, modules=None):
    doc = {"protocol": 1, "manual_install_required": False, "unsupported_versions": [], "unsupported_targets": [],
           "latest": ver.VERSION, "yanked": [], "issued": 1, "modules": modules or {},
           "thinker": tf.manifest_section(ver.VERSION)}
    if fatal_sha:
        doc["thinker"]["fatal"][ver.VERSION] = [fatal_sha]
    return doc


def _serve(monkeypatch, doc):
    import manifest as mf
    fetched = []
    monkeypatch.setattr(inst, "fetch_manifest", lambda *a, **k: fetched.append(1) or (b"", ""))
    monkeypatch.setattr(mf, "load_verified", lambda *a, **k: doc)
    return fetched


# ---------------------------------------------------------------- 1 / 2: --no-prompt in a console reads the manifest

def test_no_prompt_in_a_console_still_lists_and_installs_the_modules_on_offer(tmp_path, monkeypatch):
    """--no-prompt "installs every optional module on offer": that needs the manifest a console run reads."""
    # No local pack: in the main checkout payload_root is the repo, whose dist\ packs would be listed too (audit-n).
    empty = tmp_path / "no-local-pack"
    empty.mkdir()
    monkeypatch.setattr(inst, "default_pack", lambda: empty)
    monkeypatch.setattr(inst, "default_portrait_pack", lambda: empty)
    _console_no_prompt(monkeypatch)
    fetched = _serve(monkeypatch, _doc(modules={"movies-hd": {"size": 1 << 20, "url": "https://x/m.zip"}}))
    args = _args(no_prompt=True, ai="ask", with_thinker=False)
    catalogue, manifest = inst.module_catalogue(tmp_path, args)
    assert fetched and "movies-hd" in catalogue and manifest is not None
    assert inst.pick_modules(catalogue, args, tmp_path)[0] == ["movies-hd"]


def test_no_prompt_keep_thinker_is_still_refused_for_a_fatal_build(tmp_path, bak_path, monkeypatch):
    """75245c5 refused it; 7b53fbb installed it (no manifest, so fatal stayed False)."""
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx.exe")
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod v5.4"))
    _s, dll = st.classify(g, "0" * 64)
    _fake_thinker_step(monkeypatch, g)
    monkeypatch.setattr(inst, "module_catalogue", REAL_CATALOGUE)
    _console_no_prompt(monkeypatch)
    _serve(monkeypatch, _doc(fatal_sha=dll.sha256))
    with pytest.raises(ix.InstallerError) as e:
        inst._install(g, _args(no_prompt=True, keep_thinker=True, with_thinker=False, ai="ask"))
    assert "does not start with your Thinker Mod 5.4, so it was not installed on its own" in e.value.message
    assert not (g / "uimod.dll").exists()


def test_the_no_prompt_refusal_never_offers_keep_thinker_for_a_fatal_build(tmp_path, bak_path, monkeypatch):
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx.exe")
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod v5.4"))
    _s, dll = st.classify(g, "0" * 64)
    _fake_thinker_step(monkeypatch, g)
    monkeypatch.setattr(inst, "module_catalogue", REAL_CATALOGUE)
    _console_no_prompt(monkeypatch)
    _serve(monkeypatch, _doc(fatal_sha=dll.sha256))
    with pytest.raises(ix.InstallerError) as e:
        inst._install(g, _args(no_prompt=True, keep_thinker=False, with_thinker=False, ai="ask"))
    assert "--with-thinker" in e.value.remedy and "--keep-thinker" not in e.value.remedy


# ---------------------------------------------------------------- 3: a resumed .part with a bad prefix

def test_a_resumed_part_that_fails_the_hash_restarts_clean_once(tmp_path, monkeypatch):
    """The verifier's repro (unit/resume_mismatch.py): a stale corrupted .part is resumed, the whole fails the hash;
    the next attempt starts clean and succeeds (MismatchError gave up at once)."""
    body = bytes(range(256)) * 400
    sha = hashlib.sha256(body).hexdigest()
    calls = []

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

    class Op:
        def open(self, req, timeout=None):
            r = req.get_header("Range")
            calls.append(r)
            if r:
                start = int(r.split("=")[1].rstrip("-"))
                return Resp(body[start:], 206, start)
            return Resp(body, 200, 0)

    monkeypatch.setattr(fetch, "_opener", lambda allow_file=False: Op())
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    dest = tmp_path / "x.zip"
    (tmp_path / "x.zip.part").write_bytes(b"\xff" * 1000)
    fetch.download("https://example.invalid/x.zip", dest, sha256=sha, size=len(body), label="x")
    assert dest.read_bytes() == body and calls == ["bytes=1000-", None]


def test_a_fresh_download_that_fails_the_hash_is_still_not_retried(tmp_path, monkeypatch):
    calls = []

    class Resp(io.BytesIO):
        status = 200
        headers = email.message.Message()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    monkeypatch.setattr(fetch, "_opener", lambda allow_file=False: types.SimpleNamespace(
        open=lambda req, timeout=None: calls.append(1) or Resp(b"x" * 100)))
    monkeypatch.setattr(fetch.time, "sleep", lambda s: None)
    with pytest.raises(fetch.MismatchError):
        fetch.download("https://example.invalid/y.zip", tmp_path / "y.zip", sha256="0" * 64, size=100, label="y")
    assert calls == [1]


def test_the_bootstrap_says_a_mismatched_installer_did_not_match(tmp_path, monkeypatch):
    import bootstrap as bs
    monkeypatch.setattr(fetch, "download", _raise(fetch.MismatchError("sha256 mismatch")))
    monkeypatch.setattr(bs, "fetchmod", fetch, raising=False)
    base = {"url": "https://longevitymods.com/x.zip", "sha256": "0" * 64, "size": 10}
    with pytest.raises(ix.InstallerError) as e:
        bs._download_new_payload(tmp_path, base, "9.9.9", types.SimpleNamespace(manifest=None))
    assert "did not match" in e.value.message and "connection" not in (e.value.remedy or "")


# ---------------------------------------------------------------- 4: a Thinker folder whose only PRACX copy is a .bak

def test_a_thinker_folder_with_only_the_pracx_bak_is_not_refused(tmp_path, bak_path, pristine_bytes):
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    (g / "terranx.exe").write_bytes(pristine_bytes)
    shutil.copy2(bak_path, g / "terranx_PRACX.exe.bak")
    (g / "thinker.dll").write_bytes(b"dll")
    (g / "thinker.exe").write_bytes(b"exe")
    assert inst.check_game_folder(g)[0] == inst.FOLDER_OK
    assert inst.plan_thinker_setup(g, _args())["action"] == "setup"      # the set-up starts from that .bak


# ---------------------------------------------------------------- 5: Ctrl-C inside the set-up

@pytest.fixture
def b_folder(tmp_path, bak_path, pristine_bytes):
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    (g / "terranx.exe").write_bytes(pristine_bytes)
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    (g / "thinker.dll").write_bytes(b"dll")
    (g / "thinker.exe").write_bytes(b"exe")
    return g


def _tree(g):
    return {str(p.relative_to(g)): hashlib.md5(p.read_bytes()).hexdigest() for p in g.rglob("*") if p.is_file()}


@pytest.mark.parametrize("where", ["_write_setup", "second_replace"])
def test_ctrl_c_inside_the_set_up_rolls_it_back(b_folder, monkeypatch, where):
    """Between the two renames (no terranx.exe, a 4 MB .longevity-tmp left) or at the record: rolled back, then the
    run stops as Ctrl-C stops it."""
    g = b_folder
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    plan = inst.plan_thinker_setup(g, _args())
    before = _tree(g)
    if where == "_write_setup":
        monkeypatch.setattr(inst, "_write_setup", _raise(KeyboardInterrupt()))
    else:
        real = inst.os.replace
        n = []

        def replace(a, b):
            if Path(a).name.endswith(inst._SETUP_TMP):
                n.append(1)
                raise KeyboardInterrupt
            return real(a, b)
        monkeypatch.setattr(inst.os, "replace", replace)
    with pytest.raises(KeyboardInterrupt):
        inst.apply_thinker_setup(plan)
    assert _tree(g) == before and not plan.get("applied")


def test_a_left_set_up_temp_file_is_cleared_by_the_next_run(b_folder):
    g = b_folder
    (g / ("terranx.exe" + inst._SETUP_TMP)).write_bytes(b"x" * 100)
    inst._clear_setup_tmps(g)
    assert not (g / ("terranx.exe" + inst._SETUP_TMP)).exists()


def test_ctrl_c_after_a_first_thinker_installs_set_up_keeps_thinker(tmp_path, bak_path, monkeypatch, capsys):
    """The set-up is in place (terranx.exe the PRACX copy) when Ctrl-C lands after it: Thinker stays with it (undoing
    Thinker there left a set-up with no Thinker), and the console says so."""
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    calls = _fake_thinker_step(monkeypatch, g)
    real = inst.apply_thinker_setup

    def apply(plan):
        r = real(plan)
        raise KeyboardInterrupt                     # after the swap: the copy-back / the say that follows it
    monkeypatch.setattr(inst, "apply_thinker_setup", apply)
    with pytest.raises(KeyboardInterrupt):
        inst._install(g, _args())
    assert ("undo",) not in calls and ("finish",) in calls
    assert "Thinker Mod 5.5 was installed and stays in the game folder" in capsys.readouterr().out


def test_the_copy_back_is_atomic(b_folder, monkeypatch):
    """terranx_PRACX.exe, an older build of ours, is put back to clean through a temporary file: a Ctrl-C mid-copy
    leaves it whole."""
    import inspect
    src = inspect.getsource(inst.apply_thinker_setup)
    assert "shutil.copy2(src, other)" not in src and "os.replace(tmp_other, other)" in src


# ---------------------------------------------------------------- 6: recovery tidies what it finished or undid

@pytest.mark.parametrize("finished", [True, False], ids=["finished", "undone"])
def test_recovery_removes_the_empty_set_and_the_download(tmp_path, finished):
    game, prep = _first_install_plan(tmp_path, {"terranx.exe": b"MZ"})
    stg = game / "LongevityMods" / "staging" / "thinker"
    stg.mkdir(parents=True)
    (stg / "thinker-5.5.0.zip").write_bytes(b"zip")
    tf.commit(prep, route="fresh")                   # the journal stays: interrupted before finish
    if not finished:
        for a in tu.read_journal(game)["actions"]:   # roll the new files back by hand: "old" is in place
            p = game.joinpath(*a["rel"].split("/"))
            if not a["old"] and p.exists():
                p.unlink()
    assert tf.recover_at_entry(game) == (tu.FINISHED if finished else tu.UNDONE)
    assert not prep.report.backup_dir.exists() and tu.older_backups(game) == []
    assert not stg.exists()


# ---------------------------------------------------------------- 7: no change, nothing of the run left

def test_a_no_change_failure_in_an_existing_longevitymods_leaves_no_download(tmp_path, bak_path, monkeypatch):
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    (g / "LongevityMods" / "backups").mkdir(parents=True)
    _fake_thinker_step(monkeypatch, g)

    def download_step(gd, step):
        (gd / "LongevityMods" / "staging" / "thinker").mkdir(parents=True)
        (gd / "LongevityMods" / "staging" / "thinker" / "thinker-5.5.0.zip").write_bytes(b"zip")
        raise ix.InstallerError("could not be downloaded", changed=False)
    monkeypatch.setattr(tf, "download_step", download_step)
    with pytest.raises(ix.InstallerError):
        inst._install(g, _args())
    assert not (g / "LongevityMods" / "staging" / "thinker").exists() and (g / "LongevityMods" / "backups").is_dir()


def test_ctrl_c_during_the_thinker_download_is_a_stop_with_nothing_left(tmp_path, bak_path, monkeypatch):
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    _fake_thinker_step(monkeypatch, g)

    def download_step(gd, step):
        (gd / "LongevityMods" / "staging" / "thinker").mkdir(parents=True)
        raise KeyboardInterrupt
    monkeypatch.setattr(tf, "download_step", download_step)
    try:
        with pytest.raises(ix.InstallerError) as e:
            inst._install(g, _args())
    except KeyboardInterrupt:
        pytest.fail("Ctrl-C during the Thinker download escaped as KeyboardInterrupt (INSTALLATION CANCELLED)")
    assert (e.value.code, e.value.title) == (ix.EXIT_ABORTED, "NOTHING WAS CHANGED")
    assert not (g / "LongevityMods").exists()


# ---------------------------------------------------------------- 8: the folder list's Ctrl-C says it once

def test_no_folder_chosen_says_nothing_was_installed_once():
    assert inst._no_folder_chosen(False).disk_note is False
    assert inst._no_folder_chosen(True).disk_note is None       # "No game folder was chosen." keeps the disk line


# ---------------------------------------------------------------- the re-run of audit-c against 5f88a5c

def test_the_setup_no_prompt_refusal_says_nothing_was_installed_once(tmp_path, monkeypatch):
    g = tmp_path / "game"
    g.mkdir()
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod v5.4"))
    _console_no_prompt(monkeypatch)
    monkeypatch.setattr(tf, "take_for_worker", lambda *a: None)
    with pytest.raises(ix.InstallerError) as e:
        tf.update_preflight(g, types.SimpleNamespace(no_prompt=True), None, fresh=True, lv="1.0.0", persist_issued=False)
    assert e.value.message.endswith("so nothing was installed.") and e.value.disk_note is False


def test_a_failed_preflight_leaves_no_download_on_any_route(tmp_path, monkeypatch):
    """--fix-thinker and --update after a bad download kept staging\thinker (the setup run cleared it itself)."""
    g = tmp_path / "game"
    stg = g / "LongevityMods" / "staging" / "thinker"
    stg.mkdir(parents=True)
    (stg / "thinker-5.5.0.zip").write_bytes(b"a stale, wrong zip")
    monkeypatch.setattr(fetch, "download", _raise(fetch.MismatchError("sha256 mismatch")))
    with pytest.raises(ix.InstallerError):
        tf.prepare(g, tf.compiled_pin(), tf.compiled_meta(), "1.0.0", route="R", lv_have="1.0.0")
    assert not stg.exists()


def test_ctrl_c_after_thinker_is_undone_and_a_later_success_leave_no_download(tmp_path, bak_path, monkeypatch):
    """A Ctrl-C that undid Thinker's change kept its download, and the next run (Only install) never removed it."""
    inst._load_modules()
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    stg = g / "LongevityMods" / "staging" / "thinker"
    _fake_thinker_step(monkeypatch, g)
    real_commit = tf.commit

    def commit(p, route, exe=None):
        stg.mkdir(parents=True, exist_ok=True)
        (stg / "thinker-5.5.0.zip").write_bytes(b"zip")
        return real_commit(p, route=route, exe=exe)
    monkeypatch.setattr(tf, "commit", commit)
    monkeypatch.setattr(inst, "apply_backup_plan", _raise(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        inst._install(g, _args())
    assert not stg.exists()
    stg.mkdir(parents=True)                                     # a leftover from some earlier run
    (stg / "thinker-5.5.0.zip").write_bytes(b"zip")
    monkeypatch.setattr(inst, "apply_backup_plan", lambda plan: [])
    assert inst._install(g, _args(with_thinker=False, keep_thinker=True)) == 0
    assert not stg.exists()
