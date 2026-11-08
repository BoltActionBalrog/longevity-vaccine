r"""The installer's patch log (LongevityMods\logs\patch-<stamp>.log) is a RECORD, not a transcript, and it is pruned.

Audit 2026-11-07: the update path captured the patcher's full developer transcript -- 4,200 lines, 850 KB -- into a
new file on every update, and nothing ever deleted one. It was the mod's only file that grew without bound. The
patcher already had a one-line-per-phase `summary` mode built for the end-user installer (the fresh-install path
used it); the transactional path simply never passed it. Now:

- transact.stage_one / apply_transactional take `summary` and hand it to apply_patches, which then prints no
  per-site narration at all (a failing site still arrives through the sink WITH its bytes);
- install.run_patch_logged writes a header (installer version, run time, each binary's target id and hashes),
  the phase lines, the stage / commit lines -- and prunes older patch logs to PATCH_LOGS_KEPT, success or not.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent.parent
sys.path.insert(0, str(_REPO / "work" / "scripts"))

import apply_patches as ap    # noqa: E402
import install as inst        # noqa: E402
import transact as tx         # noqa: E402
import version as ver         # noqa: E402

inst._load_modules()          # install.py binds ap / ver / config lazily; a module run alone must not rely on a
                              # sibling test module having done it (audit 2026-11-07)

PATCHES = _REPO / "work" / "patches" / "patches.yaml"


def _logs(game: Path) -> Path:
    d = game / "LongevityMods" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------- transact: summary mode

def test_summary_mode_patches_for_real_without_a_transcript(tmp_path, bak_path, capsys):
    """One real transactional patch of the pristine exe: the sink gets the phase lines, stdout gets NOTHING."""
    game = tmp_path / "game"
    game.mkdir()
    live = game / "terranx_PRACX.exe"
    shutil.copy2(bak_path, live)
    spec = ap.load_targets(PATCHES)["pracx"]
    phases, said = [], []
    out = tx.apply_transactional(live, PATCHES, spec, tmp_path / "work", say=said.append,
                                 summary=lambda s, t: phases.append((s, t)))
    assert out["terranx_PRACX.exe"] == spec.patched_md5
    assert hashlib.md5(live.read_bytes()).hexdigest() == spec.patched_md5
    assert capsys.readouterr().out == "", "summary mode must print no per-site transcript"
    text = "\n".join(t for _, t in phases)
    assert len(phases) < 12, text
    assert "Patching: SUCCESS (" in text and "Patch sites: SUCCESS (" in text
    assert all(s in ("ok", "skip", "info") for s, _ in phases), phases
    assert any(l == f"  patching terranx_PRACX.exe: target 'pracx', from terranx_PRACX.exe (MD5 {spec.base_md5})"
               for l in said), said                     # which file it was patched FROM, measured
    backup = [t for s, t in phases if s == "info" and t.startswith("Backup: ")]
    assert backup and backup[0].endswith(".bak is not touched)"), phases   # the staged copy's, not the player's
    assert any(l.startswith("  staged terranx_PRACX.exe: ") for l in said)
    assert any(l == "  installed terranx_PRACX.exe" for l in said)


def test_stage_one_hands_the_sink_to_the_patcher(tmp_path, bak_path, monkeypatch):
    """The plumbing, pinned without a patch run: whatever sink stage_one gets, apply_patches gets."""
    live = tmp_path / "terranx_PRACX.exe"
    shutil.copy2(bak_path, live)
    spec = ap.load_targets(PATCHES)["pracx"]
    seen = {}

    def fake_apply(cand, patches, do_apply, **kw):
        seen.update(kw)
        return 7          # a non-zero code: stage_one must raise, never report a stage

    monkeypatch.setattr(tx.ap, "apply_patches", fake_apply)
    got = []
    with pytest.raises(tx.CommitError):
        tx.stage_one(live, PATCHES, spec, tmp_path / "work", say=lambda *_: None,
                     summary=lambda s, t: got.append((s, t)))
    fwd = seen.get("summary")
    assert callable(fwd) and seen.get("do_apply", True) is True
    fwd("ok", "Patch sites: SUCCESS (1/1 verified, 0 skipped)")       # forwarded unchanged ...
    fwd("info", "Backup: terranx_PRACX.exe.bak")                        # ... except the staged copy's backup note
    assert got[0] == ("ok", "Patch sites: SUCCESS (1/1 verified, 0 skipped)")
    assert got[1][0] == "info"
    assert got[1][1].startswith("Backup: terranx_PRACX.exe.bak (") and got[1][1].endswith(".bak is not touched)")
    # and no sink at all stays no sink: the developer CLI keeps its transcript
    seen.clear()
    with pytest.raises(tx.CommitError):
        tx.stage_one(live, PATCHES, spec, tmp_path / "work", say=lambda *_: None)
    assert seen.get("summary") is None


# ---------------------------------------------------------------- install: the log file

def _fake_transactional(calls):
    def fake(target, patches, spec, work, companions=None, say=print, summary=None):
        calls.append(summary)
        say(f"  patching {Path(target).name}: target {spec.id!r}, clean base {spec.base_md5}")
        summary("ok", "Code caves: SUCCESS (2/2 ready)")
        summary("ok", "Patch sites: SUCCESS (1425/1464 verified, 30 skipped)")
        summary("skip", "  skipped: uimod_native.stub, uimod_native.tableptr")
        summary("ok", "Patching: SUCCESS (1425/1455 sites patched, 30 skipped, 2 code cave(s) written)")
        say(f"  staged {Path(target).name}: {spec.patched_md5}")
        say(f"  installed {Path(target).name}")
        return {Path(target).name: spec.patched_md5}
    return fake


def test_the_patch_log_is_a_record_not_a_transcript(tmp_path, monkeypatch, capsys):
    import transact as _tx
    calls = []
    monkeypatch.setattr(_tx, "apply_transactional", _fake_transactional(calls))
    game = tmp_path / "game"
    _logs(game)
    spec = ap.load_targets(PATCHES)["pracx"]
    log = inst._log_path(game, "patch")
    inst.run_patch_logged(log, game, game / "terranx_PRACX.exe", spec, game / "work", companions=[])
    assert calls == [inst._log_summary], "the patcher's sink is the log's own line writer"
    text = log.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0].startswith(f"Longevity Vaccine {ver.VERSION} -- update patch run 20")
    assert lines[1] == inst.ix.redact_profile(f"game folder: {game}")      # the account name is redacted
    assert lines[2] == (f"terranx_PRACX.exe: target 'pracx' ({spec.label}), clean base {spec.base_md5}, "
                        f"expected result {spec.patched_md5}")
    assert "[ok] Patching: SUCCESS (1425/1455 sites patched, 30 skipped, 2 code cave(s) written)" in lines
    assert "[skip]   skipped: uimod_native.stub, uimod_native.tableptr" in lines
    assert f"  staged terranx_PRACX.exe: {spec.patched_md5}" in lines
    assert lines[-1] == "done"
    assert len(lines) < 20 and len(text) < 2048, text          # a record, not 850 KB
    assert capsys.readouterr().out == "", "nothing of it reaches the console"


def test_the_header_names_every_companion(tmp_path, monkeypatch):
    import transact as _tx
    monkeypatch.setattr(_tx, "apply_transactional", _fake_transactional([]))
    game = tmp_path / "game"
    _logs(game)
    table = ap.load_targets(PATCHES)
    spec = table["pracx"]
    cspec = ap.TargetSpec("pracx:prax.dll", {"label": "PRACX companion prax.dll", "exe": "prax.dll",
                                             "base_md5": "a" * 32, "base_size": 1, "patches": "x.yaml"})
    log = inst._log_path(game, "patch")
    inst.run_patch_logged(log, game, game / "terranx_PRACX.exe", spec, game / "work",
                          companions=[(game / "prax.dll", Path("x.yaml"), cspec)])
    lines = log.read_text(encoding="utf-8").splitlines()
    assert lines[3].startswith("prax.dll: target 'pracx:prax.dll' (PRACX companion prax.dll), clean base " + "a" * 32)
    assert lines[3].endswith("expected result (unrecorded)")


def test_a_failed_run_keeps_its_log_and_still_prunes(tmp_path, monkeypatch):
    import transact as _tx

    def boom(*a, **kw):
        kw["say"]("  patching terranx_PRACX.exe: target 'pracx', clean base 0")
        kw["summary"]("error", "Patch sites: ERROR (1/1464 failed, 30 skipped)")
        kw["summary"]("error", "  site_x @ VA 0x00401000: expected 90, got 91")
        raise _tx.CommitError("patching the staged copy of terranx_PRACX.exe failed (code 3)")

    monkeypatch.setattr(_tx, "apply_transactional", boom)
    game = tmp_path / "game"
    d = _logs(game)
    for i in range(5):
        (d / f"patch-2026010{i}-000000.log").write_text("old", encoding="utf-8")
    spec = ap.load_targets(PATCHES)["pracx"]
    log = d / "patch-20261107-120000.log"
    with pytest.raises(_tx.CommitError):
        inst.run_patch_logged(log, game, game / "terranx_PRACX.exe", spec, game / "work", companions=[])
    text = log.read_text(encoding="utf-8")
    assert "[error] Patch sites: ERROR (1/1464 failed, 30 skipped)" in text
    assert "expected 90, got 91" in text, "a FAILING site keeps its bytes in the record"
    assert "done" not in text.splitlines()
    kept = sorted(p.name for p in d.glob("patch-*.log"))
    assert kept == ["patch-20260103-000000.log", "patch-20260104-000000.log", "patch-20261107-120000.log"]


def test_a_log_in_the_temp_fallback_is_pruned_where_it_landed(tmp_path, monkeypatch):
    """_log_path falls back to %TEMP% when LongevityMods\\logs cannot be made; the prune follows the log."""
    import transact as _tx
    monkeypatch.setattr(_tx, "apply_transactional", _fake_transactional([]))
    elsewhere = tmp_path / "temp"
    elsewhere.mkdir()
    for i in range(4):
        (elsewhere / f"patch-2026010{i}-000000.log").write_text("old", encoding="utf-8")
    game = tmp_path / "game"          # no LongevityMods\logs at all
    game.mkdir()
    spec = ap.load_targets(PATCHES)["pracx"]
    log = elsewhere / "patch-20261107-120000.log"
    inst.run_patch_logged(log, game, game / "terranx_PRACX.exe", spec, game / "work", companions=[])
    assert sorted(p.name for p in elsewhere.glob("patch-*.log")) == [
        "patch-20260102-000000.log", "patch-20260103-000000.log", "patch-20261107-120000.log"]
    assert not (game / "LongevityMods").exists()


def test_the_log_path_falls_back_to_temp_without_crashing(tmp_path, monkeypatch):
    """Pre-existing hole the audit found: the fallback referenced `tempfile` without importing it."""
    import tempfile
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "T"))
    (tmp_path / "T").mkdir()
    blocked = tmp_path / "game"
    blocked.mkdir()
    (blocked / "LongevityMods").write_text("a file where the folder should be", encoding="utf-8")
    p = inst._log_path(blocked, "patch")
    assert p.parent == tmp_path / "T" and p.name.startswith("patch-20")


def test_a_real_commit_error_is_recorded_not_just_raised(tmp_path, monkeypatch):
    """The clean-base refusal, the lock mismatch and a rolled-back swap raise WITHOUT a summary line: the
    record must still say what went wrong, since the console tells the player to look there."""
    import transact as _tx

    def refuse(*a, **kw):
        raise _tx.CommitError("neither terranx_PRACX.exe (MD5 " + "b" * 32 + ") nor its .bak (absent) is the clean base")

    monkeypatch.setattr(_tx, "apply_transactional", refuse)
    game = tmp_path / "game"
    d = _logs(game)
    spec = ap.load_targets(PATCHES)["pracx"]
    log = d / "patch-20261107-120000.log"
    with pytest.raises(_tx.CommitError):
        inst.run_patch_logged(log, game, game / "terranx_PRACX.exe", spec, game / "work", companions=[],
                              notes=["prax.dll: left alone (MD5 " + "c" * 32 + ": not a build this patch set knows, no clean .bak)"])
    lines = log.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith(f"Longevity Vaccine {ver.VERSION} -- update patch run ")
    assert lines[3].startswith("prax.dll: left alone (MD5 ccc")           # the decision taken before the run
    assert lines[-1] == "[error] neither terranx_PRACX.exe (MD5 " + "b" * 32 + ") nor its .bak (absent) is the clean base"


def test_the_clean_base_refusal_measures_both_files(tmp_path, bak_path):
    spec = ap.load_targets(PATCHES)["pracx"]
    live = tmp_path / "terranx_PRACX.exe"
    data = bytearray(bak_path.read_bytes())
    data[0x1000] ^= 0xFF
    live.write_bytes(bytes(data))
    with pytest.raises(tx.CommitError) as e:
        tx._clean_base(live, spec)
    assert f"(MD5 {hashlib.md5(bytes(data)).hexdigest()})" in str(e.value) and "(absent)" in str(e.value)
    bak = tmp_path / "terranx_PRACX.exe.bak"
    bak.write_bytes(b"not the base either")
    with pytest.raises(tx.CommitError) as e:
        tx._clean_base(live, spec)
    assert f"(MD5 {hashlib.md5(b'not the base either').hexdigest()})" in str(e.value)
    shutil.copy2(bak_path, bak)
    assert tx._clean_base(live, spec) == bak            # a clean .bak wins over a modified live file


# ---------------------------------------------------------------- the fresh-install record

def test_a_fresh_install_writes_the_same_record(tmp_path, bak_path):
    """One real patch_target run under fresh_patch_log: header, the measured base, the phase lines, done."""
    game = tmp_path / "game"
    d = _logs(game)
    live = game / "terranx_PRACX.exe"
    shutil.copy2(bak_path, live)
    spec = ap.load_targets(PATCHES)["pracx"]
    with inst.fresh_patch_log(game) as path:
        assert inst.patch_target(live, force=False) == "patched"
    assert path.parent == d
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith(f"Longevity Vaccine {ver.VERSION} -- install patch run 20")
    assert lines[1] == inst.ix.redact_profile(f"game folder: {game}")      # the account name is redacted
    assert lines[2] == (f"terranx_PRACX.exe: target 'pracx' ({spec.label}), clean base {spec.base_md5}, "
                        f"expected result {spec.patched_md5}")
    assert any(l.startswith("[ok] Patching: SUCCESS (") for l in lines), lines
    assert any(l.startswith("[skip]   skipped: ") for l in lines), lines
    assert lines[-1] == "done" and len(lines) < 20
    assert hashlib.md5(live.read_bytes()).hexdigest() == spec.patched_md5
    assert inst._PATCH_LOG is None, "the tee is closed after the block"
    # a second run over the patched folder records the already-patched decision
    with inst.fresh_patch_log(game) as path2:
        assert inst.patch_target(live, force=False) == "already-patched"
    assert any(l.startswith("terranx_PRACX.exe: already patched (MD5 ") for l in path2.read_text(encoding="utf-8").splitlines())


def test_the_fresh_record_keeps_a_failure_and_prunes(tmp_path):
    game = tmp_path / "game"
    d = _logs(game)
    for i in range(4):
        (d / f"patch-2026010{i}-000000.log").write_text("old", encoding="utf-8")
    with pytest.raises(RuntimeError):
        with inst.fresh_patch_log(game) as path:
            inst._patch_summary("error", "Patch sites: ERROR (1/1464 failed, 30 skipped)")
            raise RuntimeError("A patch step failed, so the installer stopped before deploying anything.")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert "[error] Patch sites: ERROR (1/1464 failed, 30 skipped)" in lines
    assert lines[-1] == "[error] A patch step failed, so the installer stopped before deploying anything."
    assert inst._PATCH_LOG is None
    assert len(list(d.glob("patch-*.log"))) == inst.PATCH_LOGS_KEPT and path.exists()


def test_the_summary_tee_is_inert_outside_the_block(capsys):
    assert inst._PATCH_LOG is None
    inst._patch_summary("ok", "Patching: SUCCESS (1/1 sites patched)")
    inst._patch_log_line("never written anywhere")
    assert "Patching: SUCCESS" in capsys.readouterr().out


# ---------------------------------------------------------------- the crash log's folder

def test_the_crash_log_follows_the_game_folder(tmp_path, monkeypatch):
    import installer_exit as ix
    assert inst.crash_log_dir() is None                  # before main knows the folder: beside the script
    monkeypatch.setattr(inst, "_CRASH_LOG_GAME_DIR", tmp_path / "game")
    assert inst.crash_log_dir() == tmp_path / "game" / "LongevityMods" / "logs"
    p = ix.write_crash_log(RuntimeError("boom"), log_dir=inst.crash_log_dir)
    assert p is not None and p.parent == tmp_path / "game" / "LongevityMods" / "logs"
    assert p.name.startswith("install-crash-") and "RuntimeError: boom" in p.read_text(encoding="utf-8")
    # a callable that raises must not cost the crash report its folder choice: it falls back
    seen = []
    monkeypatch.setattr(ix.Path, "mkdir", lambda self, *a, **k: seen.append(self) or None)
    monkeypatch.setattr(ix.Path, "open", lambda self, *a, **k: (_ for _ in ()).throw(OSError("no")))
    assert ix.write_crash_log(RuntimeError("x"), log_dir=lambda: (_ for _ in ()).throw(ValueError())) is None
    assert seen and seen[0] == ix.Path(ix.__file__).resolve().parent


def test_both_entry_points_route_the_crash_log(tmp_path):
    src = (_REPO / "work" / "scripts" / "install.py").read_text(encoding="utf-8")
    assert "log_dir=crash_log_dir))" in src
    boot = (_REPO / "work" / "scripts" / "bootstrap.py").read_text(encoding="utf-8")
    assert "log_dir=_crash_log_dir," in boot and "inst._CRASH_LOG_GAME_DIR = game_dir" in boot


# ---------------------------------------------------------------- pruning

def test_prune_keeps_the_newest_by_name_and_nothing_else(tmp_path):
    game = tmp_path / "game"
    d = _logs(game)
    names = [f"patch-2026110{i}-10000{i}.log" for i in range(1, 6)]
    for n in names:
        (d / n).write_text("x", encoding="utf-8")
    (d / "check.log").write_text("health", encoding="utf-8")
    (d / "patch-notes.txt").write_text("not a log", encoding="utf-8")
    (d / "patch-notes.log").write_text("matches the glob, sorts after every stamp: must neither count nor go",
                                       encoding="utf-8")
    (d / "patch-2026110x-100000.log").write_text("a malformed stamp: ditto", encoding="utf-8")
    (d / "other-20261101-000000.log").write_text("another kind", encoding="utf-8")
    # an OLD stamp with a NEWER mtime must still go: the stamp decides, not the clock
    import os, time
    os.utime(d / names[0], (time.time() + 3600, time.time() + 3600))
    assert inst.prune_logs(d, "patch") == 2
    import re
    real = sorted(p.name for p in d.glob("patch-*.log") if re.fullmatch(r"patch-\d{8}-\d{6}\.log", p.name))
    assert real == names[2:]
    assert (d / "check.log").exists() and (d / "patch-notes.txt").exists()
    assert (d / "patch-notes.log").exists() and (d / "patch-2026110x-100000.log").exists()
    assert (d / "other-20261101-000000.log").exists()


def test_prune_is_harmless_where_there_is_nothing(tmp_path):
    assert inst.prune_logs(tmp_path / "nowhere", "patch") == 0
    d = _logs(tmp_path / "game")
    assert inst.prune_logs(d, "patch") == 0
    (d / "patch-20261107-000000.log").write_text("x", encoding="utf-8")
    assert inst.prune_logs(d, "patch", keep=0) == 1 and not list(d.glob("patch-*.log"))


def test_the_kept_count_is_small_and_the_update_path_uses_the_helper():
    assert 1 <= inst.PATCH_LOGS_KEPT <= 5
    src = (_REPO / "work" / "scripts" / "install.py").read_text(encoding="utf-8")
    a = src.index("def do_update(")
    b = src.index("\ndef ", a + 1)
    body = src[a:b]
    assert "run_patch_logged(patch_log, game_dir, target, spec, work, companions, notes=left_alone)" in body
    assert "tx.apply_transactional(" not in body, "the update path never calls the patcher unlogged"
    assert "(log: {patch_log})" in body, "a failed commit names the log"


# ---------------------------------------------------------------- redaction (logs go into public bug reports)

def test_both_patch_logs_redact_the_profile_folder(tmp_path, monkeypatch):
    """A game folder under the player's profile reaches neither patch log with the account name in it."""
    import transact as _tx
    profile = str(tmp_path / "Users" / "Ann")
    monkeypatch.setenv("USERPROFILE", profile)
    game = Path(profile) / "Games" / "SMAC"
    _logs(game)
    monkeypatch.setattr(_tx, "apply_transactional", _fake_transactional([]))
    spec = ap.load_targets(PATCHES)["pracx"]
    log = inst._log_path(game, "patch")
    inst.run_patch_logged(log, game, game / "terranx_PRACX.exe", spec, game / "work", companions=[])
    text = log.read_text(encoding="utf-8")
    assert r"game folder: %USERPROFILE%\Games\SMAC" in text and profile not in text
    with inst.fresh_patch_log(game) as path:
        inst._patch_log_line(f"measured base at {game}")
    text = Path(path).read_text(encoding="utf-8")
    assert "%USERPROFILE%" in text and profile.lower() not in text.lower()
