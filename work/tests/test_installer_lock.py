"""One installer at a time per game folder (install.hold_installer_lock).

The lock is process-scoped -- a named mutex the OS releases when its holder dies -- so every case
that matters runs the holder and the contender as SEPARATE PROCESSES. Threads in one process would
prove nothing: the in-process re-entry is a no-op by design.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_SCRIPTS = _TESTS.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import install as inst          # noqa: E402
import installer_exit as ix     # noqa: E402

pytestmark = pytest.mark.skipif(os.name != "nt", reason="the lock is a Windows named mutex")

_HOLDER = textwrap.dedent("""
    import os, subprocess, sys
    sys.path.insert(0, sys.argv[1])
    import install as inst
    lock = inst.hold_installer_lock(sys.argv[2])
    print("held" if lock._handle else "not-held", flush=True)
    for line in sys.stdin:
        cmd = line.strip()
        if cmd == "release":
            lock.release()
            print("released", flush=True)
        elif cmd.startswith("child "):
            # Run a contender the way the bootstrap runs its worker: lent the lock, waited for.
            env = lock.child_env(os.environ)
            # "child <script>[|<extra arg>]": the script gets <scripts dir> <game> [extra].
            script, *extra = cmd[6:].split("|")
            r = subprocess.run([sys.executable, script, sys.argv[1], sys.argv[2], *extra],
                               env=env, capture_output=True, text=True, timeout=120)
            print("child:" + r.stdout.strip().replace("\\n", "|"), flush=True)
        elif cmd == "token":
            print("token:" + lock.child_env({}).get(inst.INSTALL_LOCK_ENV, ""), flush=True)
        else:
            break
""")

#: A contender: takes the lock and reports what it got, or the refusal's title.
_TRY = textwrap.dedent("""
    import sys
    sys.path.insert(0, sys.argv[1])
    import install as inst, installer_exit as ix
    try:
        lock = inst.hold_installer_lock(sys.argv[2])
    except ix.InstallerError as e:
        print("refused:" + str(e.title), flush=True)
    else:
        print("delegated" if lock.delegated else ("owned" if lock._handle else "none"), flush=True)
""")


class Holder:
    def __init__(self, game: Path):
        self.p = subprocess.Popen([sys.executable, "-c", _HOLDER, str(_SCRIPTS), str(game)],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        assert self.read() == "held"

    def read(self) -> str:
        return self.p.stdout.readline().strip()

    def ask(self, cmd: str) -> str:
        self.p.stdin.write(cmd + "\n")
        self.p.stdin.flush()
        return self.read()

    def stop(self):
        if self.p.poll() is None:
            try:
                self.p.stdin.write("exit\n")
                self.p.stdin.flush()
            except OSError:
                pass
            try:
                self.p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.p.kill()
        self.p.wait()


@pytest.fixture(autouse=True)
def _no_lock_outlives_a_test(monkeypatch):
    # main(--no-wait) exports LONGEVITY_NO_WAIT; keep it (and any lock taken in-process) local.
    monkeypatch.delenv("LONGEVITY_NO_WAIT", raising=False)
    yield
    for lock in list(inst._HELD_LOCKS.values()):
        lock.release()


@pytest.fixture
def game(tmp_path):
    g = tmp_path / "game"
    g.mkdir()
    return g


@pytest.fixture
def holder(game):
    h = Holder(game)
    yield h
    h.stop()


def _try(game, env=None) -> str:
    r = subprocess.run([sys.executable, "-c", _TRY, str(_SCRIPTS), str(game)],
                       capture_output=True, text=True, timeout=120, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _env(**extra):
    env = {k: v for k, v in os.environ.items()
           if k not in (inst.INSTALL_LOCK_ENV, ix.WORKER_ENV)}
    env["LONGEVITY_NO_WAIT"] = "1"
    env.update(extra)
    return env


# ---- the lock itself -----------------------------------------------------------------------------

def test_a_second_process_is_refused_while_the_first_holds_it(game, holder):
    assert _try(game, _env()) == "refused:INSTALLER ALREADY RUNNING"


def test_the_refusal_says_nothing_changed_and_what_to_do(game, holder):
    with pytest.raises(ix.InstallerError) as ei:
        inst.hold_installer_lock(game)
    e = ei.value
    assert e.code == ix.EXIT_ABORTED and e.changed is False
    assert "Another Longevity Vaccine installer" in e.message
    assert "let the other installer window finish" in e.remedy


def test_a_released_lock_lets_the_next_installer_in(game, holder):
    assert holder.ask("release") == "released"
    assert _try(game, _env()) == "owned"


def test_a_crashed_holder_leaves_no_stale_lock(game):
    h = Holder(game)
    h.p.kill()                    # TerminateProcess: no release, no cleanup of any kind
    h.p.wait()
    assert _try(game, _env()) == "owned"


def test_a_holder_that_exits_without_releasing_frees_it(game):
    h = Holder(game)
    h.stop()                      # a plain exit; release() never ran
    assert _try(game, _env()) == "owned"


def test_another_game_folder_is_not_blocked(tmp_path, holder):
    other = tmp_path / "other"
    other.mkdir()
    assert _try(other, _env()) == "owned"


def test_the_same_folder_by_another_spelling_is_the_same_lock(game, holder, tmp_path):
    import _winapi
    link = tmp_path / "junction"
    _winapi.CreateJunction(str(game), str(link))
    assert _try(link, _env()) == "refused:INSTALLER ALREADY RUNNING"
    assert _try(Path(str(game).upper()), _env()) == "refused:INSTALLER ALREADY RUNNING"
    assert inst.installer_lock_name(link) == inst.installer_lock_name(game)


def test_re_taking_it_in_the_holding_process_returns_a_view_that_does_not_release(game):
    first = inst.hold_installer_lock(game)
    try:
        view = inst.hold_installer_lock(game)
        assert view is not first
        view.release()
        assert _try(game, _env()) == "refused:INSTALLER ALREADY RUNNING"
    finally:
        first.release()
    assert _try(game, _env()) == "owned"


def test_a_contender_opens_the_held_lock_and_waits_not_access_denied(game, holder):
    # The descriptor grants SYNCHRONIZE|MODIFY_STATE only; asking for more (CreateMutexW's
    # MUTEX_ALL_ACCESS) gave every contender error 5 -- "held" by accident, and no wait ever ran.
    k32 = inst._lock_kernel32()
    h = inst._open_mutex(k32, inst.installer_lock_name(game))
    assert h, "the held lock could not be opened"
    try:
        assert k32.WaitForSingleObject(h, 0) == inst._WAIT_TIMEOUT
    finally:
        k32.CloseHandle(h)


def test_check_steps_aside_while_an_installer_runs(game, holder):
    assert inst.installer_running(game)
    r = subprocess.run([sys.executable, str(_SCRIPTS / "install.py"), "--check", "--game-dir",
                        str(game), "--offline"], capture_output=True, text=True, timeout=120,
                       env=_env(), stdin=subprocess.DEVNULL)
    assert r.returncode == ix.CHECK_FAILED and r.stdout == ""
    assert "an installer is working on this game" in r.stderr
    assert list(game.iterdir()) == []


def test_installer_running_is_false_for_a_free_folder_and_leaves_it_free(game):
    assert not inst.installer_running(game)
    assert _try(game, _env()) == "owned"


@pytest.mark.parametrize("failure", ["raises", "refused"])
def test_a_lock_that_cannot_be_lent_fails_open_and_leaks_nothing(game, monkeypatch, capsys,
                                                                 failure):
    # Held but not lendable, the bootstrap's own worker would be refused as "another installer".
    real = inst._create_mutex

    def no_lending(k32, name, keep_waiting=None):
        if "-lent-" in name:
            if failure == "raises":
                raise OSError(1450, "no resources")
            return None, False
        return real(k32, name, keep_waiting)
    monkeypatch.setattr(inst, "_create_mutex", no_lending)
    lock = inst.hold_installer_lock(game)
    assert lock._handle is None and lock._lent is None
    assert "continuing without it" in capsys.readouterr().out
    assert _try(game, _env()) == "owned"


def test_a_lock_failure_never_stops_an_install(game, monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError(1450, "no resources")
    monkeypatch.setattr(inst, "_create_mutex", boom)
    lock = inst.hold_installer_lock(game)
    assert lock._handle is None and not lock.delegated
    lock.release()
    assert "continuing without it" in capsys.readouterr().out


def test_the_lock_is_created_with_the_shared_security_descriptor():
    k32 = inst._lock_kernel32()
    sa, sd = inst._lock_attributes(k32)
    try:
        assert sa is not None and sd
    finally:
        if sd:
            k32.LocalFree(sd)


# ---- lending it to a waited-for child (the bootstrap's worker) ---------------------------------

@pytest.fixture
def try_script(tmp_path):
    p = tmp_path / "try_lock.py"
    p.write_text(_TRY, encoding="utf-8")
    return p


def test_a_child_the_holder_waits_for_is_lent_the_lock(holder, try_script):
    assert holder.ask(f"child {try_script}") == "child:delegated"


def test_the_lent_lock_does_not_pass_to_a_grandchild(holder, try_script, tmp_path):
    # The child consumes the token, so whatever IT starts is an ordinary contender.
    grand = tmp_path / "grand.py"
    grand.write_text(textwrap.dedent("""
        import os, subprocess, sys
        sys.path.insert(0, sys.argv[1])
        import install as inst
        lock = inst.hold_installer_lock(sys.argv[2])
        print("delegated" if lock.delegated else "?")
        r = subprocess.run([sys.executable, sys.argv[3], sys.argv[1], sys.argv[2]],
                           capture_output=True, text=True)
        print(r.stdout.strip())
    """), encoding="utf-8")
    assert holder.ask(f"child {grand}|{try_script}") == \
        "child:delegated|refused:INSTALLER ALREADY RUNNING"


def test_a_lent_child_inherits_the_lock_if_its_holder_is_killed(holder, game, tmp_path):
    # Task Manager on the bootstrap while its worker installs: the abandoned lock must pass to
    # the worker, not to the next installer the player starts.
    marker = tmp_path / "child.pid"
    child = tmp_path / "child.py"
    child.write_text(textwrap.dedent(f"""
        import os, sys, time
        sys.path.insert(0, sys.argv[1])
        import install as inst
        lock = inst.hold_installer_lock(sys.argv[2])
        assert lock.delegated
        open({str(marker)!r}, "w").write(str(os.getpid()))
        time.sleep(60)
    """), encoding="utf-8")
    holder.p.stdin.write(f"child {child}\n")
    holder.p.stdin.flush()
    deadline = time.monotonic() + 60
    while not (marker.is_file() and marker.read_text()) and time.monotonic() < deadline:
        time.sleep(0.05)
    pid = int(marker.read_text())
    holder.p.kill()
    holder.p.wait()
    try:
        time.sleep(1)                      # let the heir thread take the abandoned lock
        assert _try(game, _env()) == "refused:INSTALLER ALREADY RUNNING"
    finally:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    deadline = time.monotonic() + 10
    while _try(game, _env()) != "owned":
        assert time.monotonic() < deadline, "the lock outlived the child that inherited it"


def test_a_token_whose_holder_has_gone_lends_nothing(game):
    h = Holder(game)
    token = h.ask("token")[len("token:"):]
    assert len(token) == 32
    h.stop()
    # The lock is free now, so the contender simply owns it; the dead token played no part.
    assert _try(game, _env(**{inst.INSTALL_LOCK_ENV: token})) == "owned"


def test_a_forged_or_foreign_token_is_refused(game, holder, tmp_path):
    assert _try(game, _env(**{inst.INSTALL_LOCK_ENV: "0" * 32})) == \
        "refused:INSTALLER ALREADY RUNNING"
    assert _try(game, _env(**{inst.INSTALL_LOCK_ENV: "not a token"})) == \
        "refused:INSTALLER ALREADY RUNNING"
    # A live holder's token for ANOTHER game folder lends nothing here.
    other = tmp_path / "other"
    other.mkdir()
    h2 = Holder(other)
    try:
        token = h2.ask("token")[len("token:"):]
        assert _try(game, _env(**{inst.INSTALL_LOCK_ENV: token})) == \
            "refused:INSTALLER ALREADY RUNNING"
    finally:
        h2.stop()


# ---- generation 2 waits for generation 1, and for no one else ----------------------------------

_WAITER = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, sys.argv[1])
    import install as inst, installer_exit as ix
    t = time.monotonic()
    try:
        inst.hold_installer_lock(sys.argv[2], wait_for=int(sys.argv[3]), wait_s=int(sys.argv[4]))
    except ix.InstallerError as e:
        print("refused", round(time.monotonic() - t, 1), str(e.title).replace(" ", "_"),
              e.message.split(",")[0].replace(" ", "_"), flush=True)
    else:
        print("owned", round(time.monotonic() - t, 1), flush=True)
""")


def _waiter(game, pid, wait_s):
    return subprocess.Popen([sys.executable, "-c", _WAITER, str(_SCRIPTS), str(game), str(pid),
                             str(wait_s)], stdout=subprocess.PIPE, text=True, env=_env())


def test_generation_two_takes_the_lock_once_generation_one_exits(game):
    gen1 = Holder(game)
    w = _waiter(game, gen1.p.pid, 60)
    time.sleep(1.5)
    assert w.poll() is None, "gave up while generation 1 still ran"
    gen1.stop()
    out, _ = w.communicate(timeout=60)
    assert out.split()[0] == "owned"


def test_generation_two_refuses_a_lock_someone_else_holds(game, holder):
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
    w = _waiter(game, other.pid, 30)
    out, _ = w.communicate(timeout=60)
    other.wait()
    assert out.split()[0] == "refused" and float(out.split()[1]) < 20
    assert out.split()[2] == "INSTALLER_ALREADY_RUNNING"


def test_generation_two_says_so_when_generation_one_never_exits(game, holder):
    w = _waiter(game, holder.p.pid, 2)
    out, _ = w.communicate(timeout=60)
    assert out.split()[0] == "refused"
    assert out.split()[3] == "The_previous_installer_did_not_exit"


# ---- every entry point takes it ---------------------------------------------------------------

@pytest.mark.parametrize("script,args", [
    ("install.py", []),
    ("install.py", ["--repair"]),
    ("install.py", ["--update", "--offline"]),
    ("install.py", ["--uninstall"]),
    ("bootstrap.py", ["--update", "--offline"]),             # run-install.bat --update / the game
    ("bootstrap.py", ["--generation", "2", "--offline"]),
], ids=["install", "repair", "update", "uninstall", "updater", "generation-2"])
def test_every_entry_point_refuses_while_another_installer_runs(game, holder, script, args):
    (game / "marker.txt").write_text("untouched", encoding="ascii")
    before = sorted(p.relative_to(game) for p in game.rglob("*"))
    r = subprocess.run([sys.executable, str(_SCRIPTS / script), "--game-dir", str(game),
                        "--no-wait", *args], capture_output=True, text=True, timeout=300,
                       env=_env(), stdin=subprocess.DEVNULL)
    out = r.stdout + r.stderr
    assert r.returncode == ix.EXIT_ABORTED, out
    assert "INSTALLER ALREADY RUNNING" in out, out
    assert sorted(p.relative_to(game) for p in game.rglob("*")) == before


def test_install_releases_the_lock_before_it_returns(game, monkeypatch):
    seen = {}

    def fake_uninstall(g, args):
        seen["during"] = _try(game, _env())
        return ix.EXIT_OK
    monkeypatch.setattr(inst, "do_uninstall", fake_uninstall)
    monkeypatch.setattr(sys, "argv", ["install.py", "--game-dir", str(game), "--uninstall",
                                      "--no-wait"])
    assert inst.main() == ix.EXIT_OK
    assert seen["during"] == "refused:INSTALLER ALREADY RUNNING"
    assert _try(game, _env()) == "owned"


def test_the_bootstrap_lets_go_before_its_window_waits(game, monkeypatch):
    # The verdict screen ("UPDATE FAILED -- simply run it again", then Enter) must not hold it.
    import bootstrap as bs
    seen = {}

    def failing_fetch(*a, **k):
        seen["during"] = _try(game, _env())
        raise ix.InstallerError("offline", code=ix.EXIT_ABORTED, changed=False)
    monkeypatch.setattr(inst, "fetch_manifest", failing_fetch)
    monkeypatch.setattr(sys, "argv", ["bootstrap.py", "--game-dir", str(game), "--update",
                                      "--offline", "--no-wait"])
    with pytest.raises(ix.InstallerError):
        bs.main()
    assert seen["during"] == "refused:INSTALLER ALREADY RUNNING"
    assert _try(game, _env()) == "owned"


def test_the_bootstrap_lends_the_lock_to_the_worker_it_waits_for(game, monkeypatch):
    import bootstrap as bs
    got = {}

    def fake_call(cmd, cwd=None, env=None):
        got["env"] = env
        return 0
    monkeypatch.setattr(bs.subprocess, "call", fake_call)
    lock = inst.hold_installer_lock(game)
    try:
        args = type("A", (), dict(repair=False, manifest=None, modules=None, wait_pid=None,
                                  no_wait=True, offline=True))()
        bs._run_installer(_SCRIPTS, game, args)
        token = got["env"][inst.INSTALL_LOCK_ENV]
        assert token == lock.child_env({})[inst.INSTALL_LOCK_ENV]
        assert inst.INSTALL_LOCK_ENV not in os.environ
        # ...and that token really lets a child process through.
        assert _try(game, _env(**{inst.INSTALL_LOCK_ENV: token})) == "delegated"
    finally:
        lock.release()
