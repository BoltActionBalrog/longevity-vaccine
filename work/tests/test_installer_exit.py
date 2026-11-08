"""The installer exit guarantee.

HARD REQUIREMENT (user, 2026-09-21): no flow may ever end with the window closing and no
message. Success, expected failure, preflight abort, Ctrl-C, unhandled exception, bad arguments --
each must print a verdict AND wait for a keypress.

These tests assert that as a PROPERTY over every outcome, rather than checking a few happy paths:
for each way main_fn can end, the guard must (a) print something, (b) call the wait exactly once,
and (c) return a code in our reserved range so run-install.bat's crash threshold still works.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import installer_exit as ix  # noqa: E402


@pytest.fixture
def waits(monkeypatch):
    """Replace the blocking wait with a counter so we can assert it always happens."""
    calls = []
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(ix, "offer_relaunch", lambda *a, **k: False)
    return calls


# Every way main_fn can end: (label, callable, expected_code)
def _ok():
    return 0


def _nonzero():
    return 7


def _fail_clean():
    raise ix.InstallerError("disk was untouched", changed=False)


def _fail_dirty():
    raise ix.InstallerError("partway through", changed=True)


def _abort():
    raise ix.InstallerError("preflight refused", code=ix.EXIT_ABORTED)


def _unsupported():
    raise ix.InstallerError("bad base", code=ix.EXIT_UNSUPPORTED)


def _no_game():
    raise ix.InstallerError("no game dir", code=ix.EXIT_NO_GAME)


def _interrupt():
    raise KeyboardInterrupt


def _boom():
    raise RuntimeError("unexpected")


def _boom_baseexception():
    raise MemoryError("nasty")


def _argparse_help():
    raise SystemExit(0)


def _argparse_usage():
    raise SystemExit(2)


def _returns_none():
    return None


def _returns_huge():
    return 3221225477   # an NTSTATUS-shaped code; must not escape into the batch contract


ALL_OUTCOMES = [
    ("ok", _ok, ix.EXIT_OK),
    ("nonzero", _nonzero, 7),
    ("fail_clean", _fail_clean, ix.EXIT_ERROR),
    ("fail_dirty", _fail_dirty, ix.EXIT_ERROR),
    ("abort", _abort, ix.EXIT_ABORTED),
    ("unsupported", _unsupported, ix.EXIT_UNSUPPORTED),
    ("no_game", _no_game, ix.EXIT_NO_GAME),
    ("interrupt", _interrupt, ix.EXIT_INTERRUPTED),
    ("boom", _boom, ix.EXIT_CRASH),
    ("boom_base", _boom_baseexception, ix.EXIT_CRASH),
    ("argparse_help", _argparse_help, ix.EXIT_OK),
    ("argparse_usage", _argparse_usage, ix.EXIT_ERROR),
    ("returns_none", _returns_none, ix.EXIT_OK),
    ("returns_huge", _returns_huge, ix.EXIT_CRASH),
]


# ------------------------------------------------- the three universal properties

@pytest.mark.parametrize("label,fn,_code", ALL_OUTCOMES, ids=[o[0] for o in ALL_OUTCOMES])
def test_every_outcome_waits_exactly_once(label, fn, _code, waits, capsys, tmp_path):
    ix.run_guarded(fn, log_dir=tmp_path)
    assert waits == [1], f"{label}: the wait must happen exactly once, got {len(waits)}"


@pytest.mark.parametrize("label,fn,_code", ALL_OUTCOMES, ids=[o[0] for o in ALL_OUTCOMES])
def test_every_outcome_prints_something(label, fn, _code, waits, capsys, tmp_path):
    """The core requirement: a silent exit is a defect, whatever happened."""
    ix.run_guarded(fn, log_dir=tmp_path)
    out = capsys.readouterr().out
    assert out.strip(), f"{label}: produced no output at all"


@pytest.mark.parametrize("label,fn,expected", ALL_OUTCOMES, ids=[o[0] for o in ALL_OUTCOMES])
def test_codes_stay_inside_the_reserved_range(label, fn, expected, waits, capsys, tmp_path):
    code = ix.run_guarded(fn, log_dir=tmp_path)
    assert code == expected, f"{label}: expected {expected}, got {code}"
    assert 0 <= code <= ix.MAX_OWN_CODE


@pytest.mark.parametrize("label,fn,_code", ALL_OUTCOMES, ids=[o[0] for o in ALL_OUTCOMES])
def test_every_outcome_writes_the_guard_marker(label, fn, _code, waits, capsys,
                                               tmp_path, monkeypatch):
    """The marker is how run-install.bat knows the guard ran at all.

    If it is missing the batch prints its own verdict and pauses, so a marker that is written on
    some paths but not others would make the batch double-report. It must be written on ALL.
    """
    marker = tmp_path / "guard.ok"
    monkeypatch.setenv(ix.MARKER_ENV, str(marker))
    ix.run_guarded(fn, log_dir=tmp_path)
    assert marker.exists(), f"{label}: no guard marker -- the batch would report a second time"


@pytest.mark.parametrize("label,fn,expected", ALL_OUTCOMES, ids=[o[0] for o in ALL_OUTCOMES])
def test_every_failure_states_disk_status(label, fn, expected, waits, capsys, tmp_path):
    """Requirement (2), asserted over every outcome rather than a couple of hand-picked ones.

    The crash branch and the non-zero-return branch both used to omit this entirely.
    """
    ix.run_guarded(fn, log_dir=tmp_path)
    out = capsys.readouterr().out
    if expected == ix.EXIT_OK:
        return  # success (incl. --help): nothing failed, so there is no disk doubt to resolve
    assert ("Nothing on disk was changed" in out
            or "partway through" in out
            or "Re-running the installer is safe" in out), \
        f"{label}: said nothing about whether disk was changed"


# ------------------------------------------------- per-outcome wording

def test_success_says_so(waits, capsys, tmp_path):
    assert ix.run_guarded(_ok, log_dir=tmp_path) == 0
    assert "INSTALLATION SUCCESSFUL" in capsys.readouterr().out


def test_clean_failure_promises_nothing_changed(waits, capsys, tmp_path):
    ix.run_guarded(_fail_clean, log_dir=tmp_path)
    out = capsys.readouterr().out
    assert "INSTALLATION FAILED" in out
    assert "Nothing on disk was changed" in out


def test_dirty_failure_does_not_promise_nothing_changed(waits, capsys, tmp_path):
    """Claiming a clean abort after a partial write would send the user down the wrong path."""
    ix.run_guarded(_fail_dirty, log_dir=tmp_path)
    out = capsys.readouterr().out
    assert "Nothing on disk was changed" not in out
    assert "partway through" in out


def test_abort_is_worded_as_nothing_changed_not_failed_or_cancelled(waits, capsys, tmp_path):
    """The installer refused; the player cancelled nothing. The one certain property of an
    EXIT_ABORTED outcome is the title."""
    ix.run_guarded(_abort, log_dir=tmp_path)
    out = capsys.readouterr().out
    assert "NOTHING WAS CHANGED" in out
    assert "CANCELLED" not in out and "FAILED" not in out


def test_a_worker_still_prints_the_reason_disk_statement_and_remedy(waits, capsys, tmp_path,
                                                                     monkeypatch):
    """The parent owns the banner; the CHILD owns the reason. Muting all of it left the player
    with an orphaned detail line and a parent verdict guessing the game might be damaged."""
    monkeypatch.setenv(ix.WORKER_ENV, "1")

    def refuse():
        raise ix.InstallerError("The pack could not be downloaded.", code=ix.EXIT_ABORTED,
                                changed=False, detail="  - why", remedy="try again later")
    ix.run_guarded(refuse, log_dir=tmp_path)
    out = capsys.readouterr().out
    assert "The pack could not be downloaded." in out
    assert "Nothing on disk was changed" in out
    assert "What to do: try again later" in out
    assert "NOTHING WAS CHANGED" not in out, "the banner is the parent's"


def test_a_custom_title_and_disk_note_are_honoured(waits, capsys, tmp_path):
    def partly():
        raise ix.InstallerError("The core is in; the pack is not.", code=ix.EXIT_ERROR,
                                changed=True, title="UPDATE PARTLY COMPLETE",
                                disk_note="The game is patched; only the pack is missing.")
    ix.run_guarded(partly, log_dir=tmp_path)
    out = capsys.readouterr().out
    assert "UPDATE PARTLY COMPLETE" in out and "only the pack is missing" in out
    assert "partway through" not in out and "INSTALLATION FAILED" not in out


def test_interrupt_is_not_reported_as_a_bug(waits, capsys, tmp_path):
    ix.run_guarded(_interrupt, log_dir=tmp_path)
    out = capsys.readouterr().out
    assert "CANCELLED" in out
    assert "INSTALLER ERROR" not in out


def test_unexpected_exception_is_owned_as_our_bug_and_logged(waits, capsys, tmp_path):
    ix.run_guarded(_boom, log_dir=tmp_path)
    out = capsys.readouterr().out
    assert "INSTALLER ERROR" in out
    assert "RuntimeError" in out
    logs = list(tmp_path.glob("install-crash-*.log"))
    assert len(logs) == 1, "a crash must leave a report the user can send"
    body = logs[0].read_text(encoding="utf-8")
    assert "RuntimeError" in body and "Traceback" in body


def test_help_is_not_dressed_up_as_a_failure(waits, capsys, tmp_path):
    """--help exits 0 through SystemExit; it must still hold the window but not alarm anyone."""
    ix.run_guarded(_argparse_help, log_dir=tmp_path)
    out = capsys.readouterr().out
    assert "FAILED" not in out and "INSTALLER ERROR" not in out


def test_bad_arguments_are_explained(waits, capsys, tmp_path):
    ix.run_guarded(_argparse_usage, log_dir=tmp_path)
    out = capsys.readouterr().out
    assert "DID NOT START" in out
    assert "Nothing on disk was changed" in out


def test_detail_and_remedy_are_surfaced(waits, capsys, tmp_path):
    def fn():
        raise ix.InstallerError("top line", detail="the detail", remedy="do the thing")
    ix.run_guarded(fn, log_dir=tmp_path)
    out = capsys.readouterr().out
    for s in ("top line", "the detail", "do the thing"):
        assert s in out


# ------------------------------------------------- relaunch + waiting mechanics

def test_relaunch_is_resolved_after_main_runs(monkeypatch, capsys, tmp_path):
    """The game dir is only known once main() is underway, so a Path passed up front would be
    None. The guard must accept a callable and resolve it late."""
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)
    seen = []
    monkeypatch.setattr(ix, "offer_relaunch", lambda exe: seen.append(exe) or False)
    box = {"exe": None}

    def fn():
        box["exe"] = Path("some") / "terranx.exe"
        return 0

    ix.run_guarded(fn, relaunch_exe=lambda: box["exe"], log_dir=tmp_path)
    assert seen == [Path("some") / "terranx.exe"]


def test_relaunch_is_not_offered_on_failure(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)
    seen = []
    monkeypatch.setattr(ix, "offer_relaunch", lambda exe: seen.append(exe) or False)
    ix.run_guarded(_fail_clean, relaunch_exe=lambda: Path("x.exe"), log_dir=tmp_path)
    assert seen == []


def test_no_wait_env_var_suppresses_only_the_wait(monkeypatch, capsys):
    """Scripted runs must not block -- but must still print the outcome."""
    monkeypatch.setenv("LONGEVITY_NO_WAIT", "1")
    assert ix.interactive() is False
    ix.wait_for_key()
    assert "not waiting" in capsys.readouterr().out


def test_no_wait_is_honoured_even_when_argparse_fails(monkeypatch, capsys):
    """--no-wait is consumed by argparse, but argparse is what fails on a bad flag. A scripted
    run that mistyped something must not sit waiting for a key that nobody will press."""
    monkeypatch.delenv("LONGEVITY_NO_WAIT", raising=False)
    monkeypatch.setattr(ix.sys, "argv", ["install.py", "--bogus", "--no-wait"])
    assert ix.interactive() is False


def test_an_any_key_wait_reads_one_console_key_and_falls_back_to_a_line(monkeypatch, capsys):
    """The foreign-backup refusal (user 2026-11-05) holds the window on ANY key: one keypress
    through the console's own reader, the prompt said through say() under one blank line; with
    no console reader, a line (Enter) ends it instead."""
    monkeypatch.setattr(ix, "interactive", lambda: True)
    monkeypatch.setattr(ix, "_last_blank", False)
    pressed = []
    monkeypatch.setitem(ix.sys.modules, "msvcrt", types.SimpleNamespace(getwch=lambda: pressed.append("x") or "x"))
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("the console reader must be used"))
    ix.wait_for_key("Press any key to close this window...", any_key=True)
    assert pressed == ["x"]
    assert capsys.readouterr().out == "\nPress any key to close this window...\n"

    class _NoReader:
        def getwch(self):
            raise OSError("no console")
    monkeypatch.setitem(ix.sys.modules, "msvcrt", _NoReader())
    lines = []
    monkeypatch.setattr("builtins.input", lambda *a: lines.append(a) or "")
    ix.wait_for_key("Press any key to close this window...", any_key=True)
    assert lines == [()]


def test_non_tty_stdin_does_not_raise(monkeypatch, capsys):
    """A redirected stdin makes input() raise instantly; that must degrade, not crash."""
    class _NoTty:
        def isatty(self):
            return False
    monkeypatch.delenv("LONGEVITY_NO_WAIT", raising=False)
    monkeypatch.setattr(ix.sys, "stdin", _NoTty())
    assert ix.interactive() is False
    ix.wait_for_key()          # must not raise


def test_no_wait_accepts_the_equals_form(monkeypatch):
    """--no-wait=1 is a normal way to write it; a false negative here means a scripted run --
    including the in-game updater's spawn -- hangs forever on a key nobody presses."""
    monkeypatch.delenv("LONGEVITY_NO_WAIT", raising=False)
    for argv in (["i.py", "--no-wait"], ["i.py", "--no-wait=1"], ["i.py", "--no-wait", "--force"]):
        monkeypatch.setattr(ix.sys, "argv", argv)
        assert ix.interactive() is False, argv


def test_a_path_argument_containing_the_flag_is_not_a_false_positive(monkeypatch):
    monkeypatch.delenv("LONGEVITY_NO_WAIT", raising=False)
    monkeypatch.setattr(ix.sys, "argv", ["i.py", "--game-dir", r"C:\--no-wait\games"])
    monkeypatch.setattr(ix.sys, "stdin", None)
    assert ix.interactive() is False   # (False here only because stdin is None, not the path)


def test_say_survives_a_missing_stdout(monkeypatch):
    """Under pythonw.exe sys.stdout is None. print() would raise; say() must not, because it
    runs inside the finally that owns the guarantee."""
    monkeypatch.setattr(ix.sys, "stdout", None)
    ix.say("still recorded")
    assert "still recorded" in ix._transcript
    assert ix.console_available() is False


def test_relaunch_failure_cannot_undo_a_successful_install(monkeypatch, capsys, tmp_path):
    """The install already succeeded; a broken relaunch must not turn the verdict into a crash."""
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)

    def boom(_exe):
        raise OSError("no such executable")
    monkeypatch.setattr(ix, "offer_relaunch", boom)
    code = ix.run_guarded(_ok, relaunch_exe=lambda: Path("x.exe"), log_dir=tmp_path)
    out = capsys.readouterr().out
    assert code == ix.EXIT_OK
    assert "INSTALLATION SUCCESSFUL" in out
    assert "INSTALLER ERROR" not in out


def test_wait_for_key_never_raises_on_a_broken_stdout(monkeypatch):
    class _Broken:
        def isatty(self):
            return True
    monkeypatch.delenv("LONGEVITY_NO_WAIT", raising=False)
    monkeypatch.setattr(ix.sys, "argv", ["i.py"])
    monkeypatch.setattr(ix.sys, "stdin", _Broken())

    def boom(*_a, **_k):
        raise OSError("stdin is gone")
    monkeypatch.setattr("builtins.input", boom)
    ix.wait_for_key()          # must not raise


# ------------------------------------------------- end-to-end (real subprocess)

_REPO = Path(__file__).resolve().parent.parent.parent
_PY = _REPO / "tools" / "python" / "python.exe"
_INSTALL = _REPO / "work" / "scripts" / "install.py"
_BAT = _REPO / "work" / "run-install.bat"


@pytest.mark.skipif(not _PY.exists(), reason="bundled interpreter not present")
def test_a_missing_dependency_still_produces_a_verdict(tmp_path):
    """THE regression test for the worst silent-exit path.

    install.py used to import config / apply_patches / version at module scope, i.e. BEFORE
    run_guarded was entered. A missing pyyaml or pefile therefore exited 1 with no verdict, no
    disk statement and no wait -- the window just vanished. That is not hypothetical: the
    payload-trim task swaps in the embeddable CPython, and the first mistrimmed package lands
    exactly here.
    """
    import os
    import subprocess

    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "yaml.py").write_text('raise ImportError("simulated missing package")\n',
                                  encoding="ascii")
    marker = tmp_path / "guard.ok"

    env = dict(os.environ)
    env["PYTHONPATH"] = str(shim)
    env[ix.MARKER_ENV] = str(marker)
    env["LONGEVITY_NO_WAIT"] = "1"

    p = subprocess.run([str(_PY), str(_INSTALL)], capture_output=True, text=True,
                       env=env, timeout=120)
    out = p.stdout + p.stderr
    assert "INSTALLATION FAILED" in out, f"silent exit on a missing dependency:\n{out}"
    assert "Nothing on disk was changed" in out
    assert "ImportError" in out
    assert marker.exists(), "the guard must still mark itself, or the batch reports twice"


def test_run_install_bat_is_crlf():
    """cmd's parser desyncs on LF-only batch files -- it printed a bogus
    `'M' is not recognized as an internal or external command` as the first line a player saw,
    and multi-line if(...) blocks (where the layer-2 guarantee lives) are what break."""
    b = _BAT.read_bytes()
    assert b.count(b"\r\n") == b.count(b"\n"), "run-install.bat must be CRLF throughout"


def test_run_install_bat_uses_the_marker_not_an_exit_code_threshold():
    """A numeric threshold cannot work: an uncaught ImportError exits 1 (indistinguishable from
    a handled failure) and a Windows fatal status reaches cmd as a NEGATIVE errorlevel, so
    `GEQ 100` never fires for the crash case it was written for."""
    text = _BAT.read_text(encoding="ascii")
    assert "LONGEVITY_GUARD_MARKER" in text
    # Ignore REM lines: the file explains WHY the threshold is unsound, so the literal string
    # legitimately appears in a comment.
    code = "\n".join(ln for ln in text.splitlines()
                     if not ln.strip().lower().startswith("rem"))
    assert "GEQ 100" not in code, "the exit-code threshold is unsound; use the marker handshake"
    # endlocal discards RC, so `endlocal` and `exit /b %RC%` must be on one line to expand first.
    assert "endlocal & exit /b" in text


# ------------------------------------------------- run-install.bat, executed for real
#
# The previous fix round left two live defects in this file precisely because every batch test
# was a text grep. These execute it.

def _run_bat(*args, env_extra=None, timeout=120):
    import os
    import subprocess
    env = dict(os.environ)
    env.pop("LONGEVITY_GUARD_MARKER", None)
    env.update(env_extra or {})
    return subprocess.run(["cmd", "/c", str(_BAT), *args],
                          capture_output=True, text=True, env=env,
                          stdin=subprocess.DEVNULL, timeout=timeout)


_SAFE = ("--no-wait", "--game-dir", r"Z:\nope-not-a-real-game-dir")


def _beside_bat_lock():
    """Held by every test that makes the batch put its marker BESIDE itself (an unwritable %TEMP%), and by the check
    that none is left there. That folder is shared by every run of this checkout -- the other xdist workers and any
    concurrent suite -- so without it the leak check saw another run's marker in flight and called it a leak."""
    import hashlib
    import tempfile
    from cpp_harness import file_lock
    key = hashlib.sha1(str(_BAT.parent.resolve()).lower().encode()).hexdigest()[:16]
    return file_lock(Path(tempfile.gettempdir()) / f"smacx-bat-beside-{key}.lock", 300)


@pytest.mark.skipif(not _BAT.exists(), reason="batch not present")
def test_bat_healthy_run_reports_once_and_does_not_hang():
    p = _run_bat(*_SAFE)
    out = p.stdout + p.stderr
    assert "INSTALLATION FAILED" in out, out          # no game dir -> layer 1 verdict
    assert "INSTALLER ERROR" not in out, "layer 2 fired on a run layer 1 already reported"


@pytest.mark.skipif(not _BAT.exists(), reason="batch not present")
def test_bat_reports_when_the_interpreter_dies_before_any_handler(need_local):
    """A broken runtime cannot reach run_guarded, so layer 2 must speak."""
    need_local(_PY, "the bundled interpreter (tools/python)")   # without it the .bat reports a missing package instead
    p = _run_bat(*_SAFE, env_extra={"PYTHONHOME": r"Z:\nope-home"})
    out = p.stdout + p.stderr
    assert "INSTALLER ERROR" in out, f"silent exit on a dead interpreter:\n{out}"
    assert "not certain how far the install got" in out


@pytest.mark.skipif(not _BAT.exists(), reason="batch not present")
def test_bat_concurrent_runs_never_exit_silently():
    """REGRESSION: the marker name used to come from %RANDOM%, which is clock-seeded at about
    one-second granularity -- two installers started in the same second drew the SAME name, and
    the second saw the first's marker and closed with no verdict at all. The marker is now an
    atomically-created directory, so identical %RANDOM% values cannot collide.

    Every process must produce exactly one verdict: a layer-1 one, or a layer-2 one, never
    neither (silent exit) and never both (contradictory double report).
    """
    import os
    import subprocess
    env = dict(os.environ)
    env.pop("LONGEVITY_GUARD_MARKER", None)
    broken = dict(env, PYTHONHOME=r"Z:\nope-home")

    procs = []
    for i in range(6):
        procs.append(subprocess.Popen(
            ["cmd", "/c", str(_BAT), *_SAFE], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=(broken if i % 2 else env), stdin=subprocess.DEVNULL))
    for i, pr in enumerate(procs):
        out = pr.communicate(timeout=180)[0] or ""
        layer1 = "INSTALLATION FAILED" in out
        layer2 = "INSTALLER ERROR" in out
        assert layer1 or layer2, f"process {i} exited SILENTLY:\n{out}"
        assert not (layer1 and layer2), f"process {i} got contradictory verdicts:\n{out}"


@pytest.mark.skipif(not _BAT.exists(), reason="batch not present")
def test_bat_survives_an_unwritable_temp_without_contradicting_itself():
    """REGRESSION: an unwritable %TEMP% meant the marker could not be written, which the batch
    read as 'the guard never ran' -- so a run that correctly said "Nothing on disk was changed"
    was immediately followed by "it is not certain how far the install got ... your original exe
    is backed up", telling the user both things in one window."""
    with _beside_bat_lock():               # the marker falls back to beside the batch: see _beside_bat_lock
        p = _run_bat(*_SAFE, env_extra={"TEMP": r"Z:\nope-temp", "TMP": r"Z:\nope-temp"})
        leaked = list(_BAT.parent.glob("longevity-guard-*"))
    out = p.stdout + p.stderr
    assert "INSTALLATION FAILED" in out
    assert "INSTALLER ERROR" not in out, f"contradictory double report:\n{out}"
    assert not leaked, f"leaked a marker beside the batch: {leaked}"


@pytest.mark.skipif(not _BAT.exists(), reason="batch not present")
def test_bat_leaves_no_marker_directories_behind(tmp_path):
    """A private %TEMP%: the machine's own is shared with every other run (other workers, other suites, other
    checkouts all run this batch), and a marker of theirs in flight between the two listings read as our leak."""
    temp = tmp_path / "temp"
    temp.mkdir()
    p = _run_bat(*_SAFE, env_extra={"TEMP": str(temp), "TMP": str(temp)})
    assert "INSTALLATION FAILED" in p.stdout + p.stderr        # the run did reach the marker handshake
    leaked = sorted(temp.glob("longevity-guard-*"))
    assert not leaked, f"leaked marker dirs: {leaked}"
    with _beside_bat_lock():
        assert not list(_BAT.parent.glob("longevity-guard-*")), "leaked a marker beside the batch"


# ------------------------------------------------- exit-code normalisation

@pytest.mark.parametrize("raw,expected", [
    (None, ix.EXIT_OK), (0, ix.EXIT_OK), (1, ix.EXIT_ERROR), (99, 99),
    (100, ix.EXIT_CRASH), (-5, ix.EXIT_CRASH), (3221225477, ix.EXIT_CRASH),
    ("abc", ix.EXIT_CRASH), ([], ix.EXIT_CRASH), (object(), ix.EXIT_CRASH),
    (2.9, ix.EXIT_CRASH),
    # A bool is NOT an exit code: int(False or EXIT_OK) == 0 would have rendered a failing
    # main() that returns a success flag as "INSTALLATION SUCCESSFUL".
    (True, ix.EXIT_OK), (False, ix.EXIT_ERROR),
])
def test_normalise_code(raw, expected):
    assert ix._normalise_code(raw) == expected


def test_the_code_reported_is_the_code_returned(waits, capsys, tmp_path):
    """The message used to print the RAW value while the finally clamped the real exit status,
    so 'report the exit code above' named a number the caller never saw."""
    code = ix.run_guarded(lambda: 100, log_dir=tmp_path)
    out = capsys.readouterr().out
    assert code == ix.EXIT_CRASH
    assert "code 100" not in out


def test_marker_is_written_before_the_wait(monkeypatch, tmp_path, capsys):
    """A death during the wait must not look like a silent exit."""
    marker = tmp_path / "guard.ok"
    monkeypatch.setenv(ix.MARKER_ENV, str(marker))
    seen = {}
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: seen.update(at_wait=marker.exists()))
    ix.run_guarded(_ok, log_dir=tmp_path)
    assert seen.get("at_wait") is True, "the marker must already exist when the wait begins"


def test_say_degrades_rather_than_dropping_unencodable_text(monkeypatch, capsys):
    """A Cyrillic/CJK game path used to raise UnicodeEncodeError out of a raw print() and land in
    the crash handler, telling the user their path was an installer bug."""
    class _Ascii:
        encoding = "ascii"

        def write(self, s):
            s.encode("ascii")      # raises on non-ASCII, like a cp1252 console would
            return len(s)

        def flush(self):
            pass
    monkeypatch.setattr(ix.sys, "stdout", _Ascii())
    ix.say("Game dir: Z:\\Игры\\Alpha")     # must not raise
    assert any("Alpha" in line for line in ix._transcript)


def test_crash_log_failure_never_masks_the_original_error(monkeypatch, capsys, tmp_path):
    """If we cannot even write the log, the user still gets the real error and a traceback."""
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)
    monkeypatch.setattr(ix, "write_crash_log", lambda *a, **k: None)
    ix.run_guarded(_boom, log_dir=tmp_path)
    out = capsys.readouterr().out
    assert "RuntimeError" in out


# ---------------------------------------------------------------- settable verdict

def test_the_success_verdict_can_be_replaced(monkeypatch, capsys):
    """Not every successful run is an INSTALL. An uninstall that printed "INSTALLATION
    SUCCESSFUL" told the player the exact opposite of what had just happened."""
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)
    ix.run_guarded(lambda: 0, success_title="UNINSTALL COMPLETE",
                   success_body="The game is unmodified again.")
    out = capsys.readouterr().out
    assert "UNINSTALL COMPLETE" in out
    assert "INSTALLATION SUCCESSFUL" not in out
    assert "The game is unmodified again." in out


def test_a_verdict_callable_is_resolved_after_the_run(monkeypatch, capsys):
    """The caller usually only knows which verdict applies once main() has run."""
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)
    box = {}

    def main():
        box["title"] = "REPAIR COMPLETE"
        return 0
    ix.run_guarded(main, success_title=lambda: box.get("title"))
    assert "REPAIR COMPLETE" in capsys.readouterr().out


def test_a_broken_verdict_callable_falls_back_instead_of_failing(monkeypatch, capsys):
    """A cosmetic problem must never turn a successful install into a crash, or into no verdict
    at all -- the guarantee is that SOMETHING is always printed."""
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)

    def boom():
        raise RuntimeError("no verdict for you")
    code = ix.run_guarded(lambda: 0, success_title=boom, success_body=lambda: None)
    out = capsys.readouterr().out
    assert code == ix.EXIT_OK
    assert "INSTALLATION SUCCESSFUL" in out
    assert "The Longevity Vaccine is installed." in out


def test_a_blank_verdict_falls_back(monkeypatch, capsys):
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)
    ix.run_guarded(lambda: 0, success_title="   ", success_body=42)
    out = capsys.readouterr().out
    assert "INSTALLATION SUCCESSFUL" in out


# ---------------------------------------------------------------- worker mode

def test_a_worker_child_prints_no_verdict_and_does_not_wait(monkeypatch, capsys):
    """A parent installer spawns the worker and owns the single verdict. Without this the
    bootstrap's in-place update printed two banners and asked for Enter twice -- and on a failure
    the two contradicted each other."""
    monkeypatch.setenv(ix.WORKER_ENV, "1")
    waited = []
    monkeypatch.setattr(ix, "input", lambda *a: waited.append(1), raising=False)
    code = ix.run_guarded(lambda: 0)
    out = capsys.readouterr().out
    assert code == ix.EXIT_OK
    assert "INSTALLATION SUCCESSFUL" not in out
    assert "=" * 60 not in out
    assert not waited, "a worker must not block on a keypress"
    assert not ix.interactive()


def test_a_worker_child_still_prints_detail_and_writes_the_marker(monkeypatch, capsys, tmp_path):
    """Suppressing the VERDICT must not suppress the diagnosis, and the batch's layer-2
    handshake must be unaffected."""
    marker = tmp_path / "ok"
    monkeypatch.setenv(ix.WORKER_ENV, "1")
    monkeypatch.setenv(ix.MARKER_ENV, str(marker))

    def main():
        ix.say("  staged terranx_PRACX.exe: abc123")
        raise ix.InstallerError("nope", detail="  the reason")
    code = ix.run_guarded(main)
    out = capsys.readouterr().out
    assert code == ix.EXIT_ERROR
    assert "staged terranx_PRACX.exe" in out
    assert "the reason" in out, "detail is diagnosis, not verdict -- it must survive"
    assert "INSTALLATION FAILED" not in out
    assert marker.is_file(), "the guard marker is the batch handshake and must still be written"


# ---- log redaction: LongevityMods\logs goes into public bug reports ---------------------------------

_P = r"C:\Users\Ann"


@pytest.mark.parametrize("text,want", [
    (r"game folder: C:\Users\Ann\Games\SMAC", r"game folder: %USERPROFILE%\Games\SMAC"),
    (r"c:\users\ann\Downloads\LV\scripts\install.py", r"%USERPROFILE%\Downloads\LV\scripts\install.py"),
    (r"C:/Users/Ann/x and C:\Users\Ann\y", r"%USERPROFILE%/x and %USERPROFILE%\y"),
    (r'File "C:\Users\Ann\AppData\Local\Temp\x.py", line 3', r'File "%USERPROFILE%\AppData\Local\Temp\x.py", line 3'),
    (r"C:\Users\Ann end", r"%USERPROFILE% end"),
    (r"No such file: 'C:\\Users\\Ann\\SMAC\\x.exe'", r"No such file: '%USERPROFILE%\\SMAC\\x.exe'"),   # a repr()
    (r"['C:\\\\Users\\\\Ann\\\\f']", r"['%USERPROFILE%\\\\f']"),                                       # repr of a repr
    (r"C:/Users//Ann/x", r"%USERPROFILE%/x"),
    (r"C:\Users\Anna\Games", r"C:\Users\Anna\Games"),            # another account sharing the prefix
    (r"C:\Users\Ann.old\x", r"C:\Users\Ann.old\x"),
    (r"D:\GOG Games\SMAC", r"D:\GOG Games\SMAC"),
    ("", ""),
])
def test_redact_profile(text, want):
    assert ix.redact_profile(text, _P) == want


def test_redact_profile_edges(monkeypatch):
    assert ix.redact_profile(r"C:\Users\Ann\x", _P + "/") == r"%USERPROFILE%\x"      # trailing separator
    for unusable in ("", "C:", "C:\\"):
        assert ix.redact_profile(r"C:\Users\Ann\x", unusable) == r"C:\Users\Ann\x"
    assert ix.redact_profile(b"bytes", _P) == b"bytes" and ix.redact_profile(None, _P) is None
    assert ix.redact_profile(r"C:\Users\Zoë (2)\x", r"C:\Users\Zoë (2)") == r"%USERPROFILE%\x"  # regex-special, non-ASCII
    monkeypatch.setenv("USERPROFILE", _P)
    assert ix.redact_profile(r"C:\Users\Ann\x") == r"%USERPROFILE%\x"                    # default = %USERPROFILE%


def test_text_that_cannot_be_redacted_is_withheld_not_written(monkeypatch):
    import re

    def boom(*a, **k):
        raise MemoryError
    monkeypatch.setattr(re, "sub", boom)
    assert ix.redact_profile(r"C:\Users\Ann\x", _P) == "[line withheld: could not redact]\n"


def test_redacting_writer_delegates_everything_else(tmp_path):
    raw = (tmp_path / "x.log").open("w", encoding="utf-8")
    w = ix.RedactingWriter(raw, _P)
    w.write(r"at C:\Users\Ann\Games" + "\n")
    w.writelines([r"C:\Users\Ann\a" + "\n", "plain\n"])
    w.flush()
    assert w.encoding == raw.encoding
    w.close()
    assert raw.closed
    assert (tmp_path / "x.log").read_text(encoding="utf-8").splitlines() == [
        r"at %USERPROFILE%\Games", r"%USERPROFILE%\a", "plain"]


def test_crash_log_redacts_argv_and_the_traceback(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", _P)
    monkeypatch.setattr(sys, "argv", [r"C:\Users\Ann\Downloads\LV\scripts\install.py", "--game-dir", r"C:\Users\Ann\SMAC"])
    try:
        raise RuntimeError(r"cannot write C:\Users\Ann\SMAC\terranx.exe")
    except RuntimeError as e:
        p = ix.write_crash_log(e, tmp_path)
    text = p.read_text(encoding="utf-8")
    assert "Ann" not in text.replace("%USERPROFILE%", "")
    assert r"%USERPROFILE%\SMAC\terranx.exe" in text
    argv_line = next(ln for ln in text.splitlines() if ln.startswith("argv"))
    assert r"%USERPROFILE%\\Downloads" in argv_line and r"%USERPROFILE%\\SMAC" in argv_line     # argv is a repr()
