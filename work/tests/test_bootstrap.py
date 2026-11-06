"""The self-update bootstrap -- the one component a later update cannot fix.

Every installed copy runs the bootstrap it shipped with, forever, so a defect here is unreachable
by any future release and the only remedy is a manual reinstall by every affected player. That is
why each safeguard gets its own case, and why the crash-mid-swap states are enumerated rather than
sampled.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent.parent
_SCRIPTS = _REPO / "work" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import bootstrap as bs        # noqa: E402
import installer_exit as ix   # noqa: E402
import manifest as mf         # noqa: E402
import sign_manifest as sm    # noqa: E402
import version as ver         # noqa: E402

SEED = bytes(range(32))
PK_HEX = sm.public_key(SEED).hex()


@pytest.fixture(autouse=True)
def _release_installer_locks():
    # bs.run() takes the installer lock in-process and only main() lets go of it; a lock left
    # held for the worker's lifetime would refuse any later installer on the same folder.
    yield
    inst = sys.modules.get("install")
    for lock in list(getattr(inst, "_HELD_LOCKS", {}).values()):
        lock.release()


@pytest.fixture
def game(tmp_path):
    g = tmp_path / "game"
    g.mkdir()
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    return g


def _make_payload(p: Path) -> Path:
    """A minimal payload in the ONE shipped layout: flat, no `work` folder."""
    (p / "scripts").mkdir(parents=True, exist_ok=True)
    (p / "patches").mkdir(parents=True, exist_ok=True)
    (p / "tools" / "python").mkdir(parents=True, exist_ok=True)
    (p / "scripts" / "run-install.bat").write_bytes(b"@echo off\r\n")
    (p / "scripts" / "install.py").write_text("x = 1\n", encoding="ascii")
    (p / "scripts" / "bootstrap.py").write_text("y = 1\n", encoding="ascii")
    (p / "scripts" / "__pycache__").mkdir(exist_ok=True)
    (p / "scripts" / "__pycache__" / "junk.pyc").write_bytes(b"junk")
    (p / "patches" / "patches.yaml").write_text("target: {}\n", encoding="ascii")
    (p / "tools" / "python" / "python.exe").write_bytes(b"MZfake")
    return p


def _make_updater(d: Path, version: str) -> Path:
    """A COMPLETE resident updater at `d` -- what reconcile must require before promoting."""
    _make_payload(d)
    (d / bs.VERSION_FILE).write_text(version + "\n", encoding="ascii")
    return d


@pytest.fixture
def payload(tmp_path):
    return _make_payload(tmp_path / "payload")


# ---------------------------------------------------------------- deploy

# ---------------------------------------------------------------- the interpreter per Windows (3.12 / 3.8)

def test_runtime_family_follows_the_running_interpreter():
    """CPython 3.12 (tools/python) cannot start below Windows 8.1; the payload carries 3.8 (tools/python38)
    for 7 and 8. run-install.bat and the DLL chose the running interpreter by that boundary, so inside the
    scripts the family of the running interpreter IS the rule -- and keeps a Windows 7 copy on 3.8 forever."""
    assert bs.runtime_exe_rel((3, 8)) == "tools/python38/python.exe"
    assert bs.runtime_exe_rel((3, 12)) == "tools/python/python.exe"
    assert bs.runtime_exe_rel((3, 9)) == "tools/python/python.exe"      # < (3, 9), not == (3, 8)
    assert bs.runtime_exe_rel() == bs.runtime_exe_rel(sys.version_info[:2])
    assert ("tools/python38", "tools/python38") in bs.PAYLOAD, "deploy() must carry the 3.8 runtime into the resident updater"


def test_payload_python_picks_by_family_and_refuses_an_absent_interpreter(tmp_path):
    """Generation 2 is spawned from the DOWNLOADED payload with its own interpreter. Absent -> refuse: the
    old fallback to sys.executable ran the new installer out of the updater directory it was about to
    replace (and on Windows 7 would have been the 3.12 that cannot start)."""
    p = _make_payload(tmp_path / "pl")
    assert bs.payload_python(p, (3, 12)) == p / "tools" / "python" / "python.exe"
    with pytest.raises(ix.InstallerError) as e:
        bs.payload_python(p, (3, 8))
    assert "tools/python38/python.exe" in e.value.detail
    (p / "tools" / "python38").mkdir()
    (p / "tools" / "python38" / "python.exe").write_bytes(b"MZfake")
    assert bs.payload_python(p, (3, 8)) == p / "tools" / "python38" / "python.exe"


def test_generation_one_refuses_a_downloaded_payload_without_its_interpreter(game, payload, tmp_path, trust,
                                                                             monkeypatch):
    """The property the handover test cannot show (it gives its stub the interpreter): no interpreter in
    the downloaded payload -> the "downloaded installer is incomplete" verdict, nothing spawned, nothing
    patched -- never a fall-back to sys.executable."""
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    monkeypatch.setattr(bs, "_run_installer", lambda *a, **k: pytest.fail("generation 1 ran the installer"))
    newpay = tmp_path / "newpay"
    (newpay / "scripts").mkdir(parents=True)
    (newpay / "scripts" / "bootstrap.py").write_text("pass\n", encoding="ascii")
    monkeypatch.setattr(bs, "_download_new_payload", lambda *a, **k: newpay)
    spawned = []
    monkeypatch.setattr(bs.subprocess, "Popen", lambda cmd, **k: spawned.append(cmd))
    m = _signed_doc(tmp_path, latest="2.0.0",
                    modules={"base": {"version": "2.0.0", "url": "file:///x", "sha256": "0" * 64}})
    with pytest.raises(ix.InstallerError) as e:
        bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"])
    assert "incomplete" in e.value.message and bs.runtime_exe_rel() in e.value.detail
    assert not spawned and bs.resident_version(game) == "1.0.0"


def test_deploy_refuses_before_copying_when_this_windows_interpreter_is_absent(game, payload, tmp_path, monkeypatch):
    """deploy()'s pre-copy check and is_usable share required_parts(): a payload without the interpreter
    this Windows runs is refused before hundreds of MB are copied, with the parts named."""
    monkeypatch.setattr(bs, "runtime_exe_rel", lambda version=None: "tools/python38/python.exe")
    with pytest.raises(OSError) as e:
        bs.deploy(game, payload, "1.0.0", dest=tmp_path / "dest", say=lambda *a: None)
    assert "tools/python38/python.exe" in str(e.value) and not (tmp_path / "dest").exists()


def test_is_usable_needs_the_interpreter_this_windows_runs(tmp_path, monkeypatch):
    p = _make_payload(tmp_path / "pl")
    assert bs.is_usable(p)                                       # 3.12 here: tools/python is enough
    monkeypatch.setattr(bs, "runtime_exe_rel", lambda version=None: "tools/python38/python.exe")
    assert not bs.is_usable(p) and bs.missing_parts(p) == ["tools/python38/python.exe"]
    (p / "tools" / "python38").mkdir()
    (p / "tools" / "python38" / "python.exe").write_bytes(b"MZfake")
    assert bs.is_usable(p)
    assert bs.missing_parts(tmp_path / "nowhere")                # not a dir: everything is missing


def test_a_resident_updater_resolves_its_own_game_dir(tmp_path, monkeypatch):
    """A resident copy acts ONLY on the install it lives in. The game's hand-off passes no
    --game-dir, and a test driving a throwaway install's updater once fell through to
    autodetection and updated the real GOG install (2026-09-27)."""
    import config
    game = tmp_path / "Some Game"
    scripts = game / "LongevityMods" / "updater" / "scripts"
    scripts.mkdir(parents=True)
    assert config.resident_game_dir(scripts) == game.resolve()
    assert config.resident_game_dir(tmp_path / "work" / "scripts") is None          # a checkout
    assert config.resident_game_dir(game / "LongevityMods" / "staging" / "payload-9.9.9" / "scripts") is None
    # game_dir() itself prefers the resident location over every other source
    monkeypatch.setenv("SMACX_GAME_DIR", str(tmp_path / "elsewhere"))
    monkeypatch.setattr(config, "resident_game_dir", lambda d: game)
    assert config.game_dir() == game


def test_deploy_creates_the_one_shipped_layout(game, payload):
    """A resident updater always has the shipped layout, however it was deployed.

    It does not matter whether the payload came from a downloaded archive or a developer's
    working tree: one layout in the field means one layout under test. `..\\tools\\python` must
    still resolve from the launcher, and uimod.dll / the ffmpeg DLLs must land where
    uimod_dll() / ffmpeg_bin() look -- getting either wrong means an update that patches the exe
    and then cannot deploy the mod.
    """
    d = bs.deploy(game, payload, "1.2.3", say=lambda *a: None)
    assert d == bs.updater_dir(game)
    assert (d / "scripts" / "run-install.bat").is_file()
    assert (d / "scripts" / "install.py").is_file()
    assert (d / "patches" / "patches.yaml").is_file()
    assert not (d / "work").exists(), "the `work` folder must not reach a payload"
    assert (d / "tools" / "python" / "python.exe").is_file(), \
        "run-install.bat's ..\\tools\\python must resolve inside the resident copy"
    assert (d / bs.VERSION_FILE).read_text(encoding="ascii").strip() == "1.2.3"
    assert bs.is_usable(d)


def test_the_changelog_ships_as_txt_and_an_older_payload_list_still_deploys(game, payload, monkeypatch):
    """CHANGELOG.txt opens in Notepad; the .md it was up to 0.2.1 opened in nothing on a stock
    Windows. A 0.2.0 / 0.2.1 bootstrap still lists CHANGELOG.md: staging a payload without it
    must skip the entry, not refuse the update."""
    assert ("CHANGELOG.txt", "work/CHANGELOG.md") in bs.PAYLOAD
    assert not [d for d, _s in bs.PAYLOAD if d == "CHANGELOG.md"]
    (payload / "CHANGELOG.txt").write_text("## 9.9.9\n", encoding="ascii")
    d = bs.deploy(game, payload, "1.2.3", say=lambda *a: None)
    assert (d / "CHANGELOG.txt").is_file() and not (d / "CHANGELOG.md").exists()
    old = tuple(("CHANGELOG.md", s) if dst == "CHANGELOG.txt" else (dst, s) for dst, s in bs.PAYLOAD)
    monkeypatch.setattr(bs, "PAYLOAD", old)
    d = bs.deploy(game, payload, "1.2.4", say=lambda *a: None)
    assert bs.is_usable(d) and not (d / "CHANGELOG.md").exists()


def test_deploy_refuses_an_incomplete_payload(game, tmp_path):
    """It used to warn per missing item and publish anyway -- which is how --repair, run from a
    resident copy whose layout it could not read, replaced a working updater with one file."""
    empty = tmp_path / "not-a-payload"
    empty.mkdir()
    with pytest.raises(OSError, match="not a complete installer"):
        bs.deploy(game, empty, "9.9.9", say=lambda *a: None)


def test_deploy_never_replaces_a_working_updater_with_a_broken_one(game, payload, tmp_path):
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(OSError):
        bs.deploy(game, empty, "9.9.9", say=lambda *a: None)
    assert bs.is_usable(bs.updater_dir(game)), "the working updater was destroyed"
    assert bs.resident_version(game) == "1.0.0", "VERSION was overwritten with a lie"


def test_the_version_file_is_readable_without_starting_python(game, payload):
    """Deciding whether to replace the interpreter must not require running it."""
    bs.deploy(game, payload, "1.2.3", say=lambda *a: None)
    raw = (bs.updater_dir(game) / bs.VERSION_FILE).read_bytes()
    assert raw.decode("ascii").strip() == "1.2.3"
    assert bs.resident_version(game) == "1.2.3"


def test_deploy_excludes_pycache(game, payload):
    d = bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    assert not list(d.rglob("__pycache__"))
    assert not list(d.rglob("*.pyc"))


def test_a_redeploy_replaces_the_previous_one_atomically(game, payload):
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    (bs.updater_dir(game) / "leftover.txt").write_text("old", encoding="ascii")
    bs.deploy(game, payload, "2.0.0", say=lambda *a: None)
    assert bs.resident_version(game) == "2.0.0"
    assert not (bs.updater_dir(game) / "leftover.txt").exists(), \
        "the old payload was merged instead of replaced"
    assert not list(bs.mods_root(game).glob("*.staging"))
    assert not list(bs.mods_root(game).glob("*.prev"))


def test_a_failed_publish_puts_the_working_updater_back(game, payload, monkeypatch):
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    real = Path.replace
    calls = {"n": 0}

    def flaky(self, target):
        calls["n"] += 1
        # Let the "move the live one aside" rename through, fail the "publish the new one" rename.
        if calls["n"] == 2:
            raise OSError("publish failed")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    with pytest.raises(OSError):
        bs.deploy(game, payload, "2.0.0", say=lambda *a: None)
    monkeypatch.undo()
    assert bs.updater_dir(game).is_dir(), "the resident updater vanished"
    assert bs.resident_version(game) == "1.0.0", "the working version was not restored"


def test_resident_version_is_unknown_when_absent_or_garbage(game, payload):
    assert bs.resident_version(game) == ver.UNKNOWN
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    (bs.updater_dir(game) / bs.VERSION_FILE).write_text("not a version\n", encoding="ascii")
    assert bs.resident_version(game) == ver.UNKNOWN
    (bs.updater_dir(game) / bs.VERSION_FILE).write_bytes(b"\xff\xfe\x00bad")
    assert bs.resident_version(game) == ver.UNKNOWN


# ---------------------------------------------------------------- the swap + reconcile

def test_swap_in_makes_the_new_payload_resident(game, payload, tmp_path):
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    newp = _make_updater(tmp_path / "newgen", "2.0.0")
    (newp / "marker.txt").write_text("new", encoding="ascii")
    bs.swap_in(game, newp, say=lambda *a: None)
    assert bs.resident_version(game) == "2.0.0"
    assert (bs.updater_dir(game) / "marker.txt").is_file()
    assert not (bs.mods_root(game) / bs.OLD_DIR).exists()
    assert not (bs.mods_root(game) / bs.NEW_DIR).exists()


def test_swap_in_refuses_an_incomplete_payload(game, payload, tmp_path):
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / bs.VERSION_FILE).write_text("2.0.0\n", encoding="ascii")
    with pytest.raises(OSError, match="incomplete"):
        bs.swap_in(game, broken, say=lambda *a: None)
    assert bs.is_usable(bs.updater_dir(game))
    assert bs.resident_version(game) == "1.0.0"


#: What the installer says, once, when it starts waiting for another program's handle.
WAITING = "is using the installer's files; waiting up to"


class _Hold:
    """Holds `path` open the way an on-access scan does -- no FILE_SHARE_DELETE, which blocks
    renaming any directory above it -- until the installer SAYS it is waiting. So the rename is
    refused at least once and then succeeds, however loaded the machine is (a timer could fire
    before the first attempt and prove nothing)."""

    def __init__(self, path: Path):
        self.f = open(path, "rb")
        self.said = []

    def say(self, *parts):
        text = " ".join(str(p) for p in parts)
        self.said.append(text)
        if WAITING in text:
            self.f.close()


def test_swap_in_waits_out_a_file_another_program_holds_briefly(game, payload, tmp_path):
    """THE load flake of test_the_base_real_dev_scenario_really_self_updates (2026-10-28): one
    handle inside `updater` made the rename fail at once, generation 2 carried on, and the
    receipt named 9.9.9 over a resident 0.1.0."""
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    newp = _make_updater(tmp_path / "newgen", "2.0.0")
    hold = _Hold(bs.updater_dir(game) / "tools" / "python" / "python.exe")
    try:
        bs.swap_in(game, newp, say=hold.say)
    finally:
        hold.f.close()
    assert any(WAITING in s for s in hold.said), hold.said
    assert bs.resident_version(game) == "2.0.0"
    assert not (bs.mods_root(game) / bs.OLD_DIR).exists()
    assert not (bs.mods_root(game) / bs.NEW_DIR).exists()


def test_swap_in_gives_up_on_a_lasting_lock_with_the_working_updater_in_place(
        game, payload, tmp_path, monkeypatch):
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    newp = _make_updater(tmp_path / "newgen", "2.0.0")
    monkeypatch.setattr(bs, "RENAME_RETRY_SECONDS", 0.1, raising=False)
    with open(bs.updater_dir(game) / "tools" / "python" / "python.exe", "rb"):
        with pytest.raises(PermissionError):
            bs.swap_in(game, newp, say=lambda *a: None)
    assert bs.is_usable(bs.updater_dir(game))
    assert bs.resident_version(game) == "1.0.0"


def test_swap_in_puts_the_working_updater_back_when_the_new_one_cannot_be_published(
        game, payload, tmp_path, monkeypatch):
    """A failure on the SECOND rename used to leave no `updater` at all: the game's update
    prompt spawns the resident copy, so it was dead until a manual reinstall."""
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    newp = _make_updater(tmp_path / "newgen", "2.0.0")
    monkeypatch.setattr(bs, "RENAME_RETRY_SECONDS", 0.1, raising=False)
    real = Path.replace

    def locked_new(self, target):
        if self.name == bs.NEW_DIR:
            raise PermissionError(13, "Access is denied")
        return real(self, target)
    monkeypatch.setattr(Path, "replace", locked_new)
    with pytest.raises(PermissionError):
        bs.swap_in(game, newp, say=lambda *a: None)
    monkeypatch.undo()
    assert bs.is_usable(bs.updater_dir(game)), "the resident updater vanished"
    assert bs.resident_version(game) == "1.0.0"


def test_a_redeploy_waits_out_a_file_another_program_holds_briefly(game, payload):
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    hold = _Hold(bs.updater_dir(game) / "scripts" / "install.py")
    try:
        bs.deploy(game, payload, "2.0.0", say=hold.say)
    finally:
        hold.f.close()
    assert any(WAITING in s for s in hold.said), hold.said
    assert bs.resident_version(game) == "2.0.0"
    assert not list(bs.mods_root(game).glob("*.prev"))


def test_a_refused_new_copy_is_waited_out_with_the_working_updater_in_place(
        game, payload, tmp_path, monkeypatch):
    """The likely lock is a scan of `updater.new`, copied a moment earlier. Waiting for it with
    `updater` already moved aside meant a closed window or a power cut left NO updater: every
    pause must find the working copy back in place."""
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    newp = _make_updater(tmp_path / "newgen", "2.0.0")
    real = Path.replace
    refusals = {"left": 2}

    def scanned_new(self, target):
        if self.name == bs.NEW_DIR and refusals["left"]:
            refusals["left"] -= 1
            raise PermissionError(13, "Access is denied")
        return real(self, target)
    seen = []
    monkeypatch.setattr(Path, "replace", scanned_new)
    monkeypatch.setattr(bs.time, "sleep",
                        lambda s: seen.append((bs.is_usable(bs.updater_dir(game)),
                                               bs.resident_version(game))))
    bs.swap_in(game, newp, say=lambda *a: None)
    monkeypatch.undo()
    assert seen == [(True, "1.0.0")] * 2, seen
    assert bs.resident_version(game) == "2.0.0"


def test_an_occupied_destination_is_refused_at_once_not_waited_on(game, payload, tmp_path):
    """Renaming onto an existing directory fails as access-denied too -- forever. Waiting on it
    would cost the full RENAME_RETRY_SECONDS for nothing."""
    import time
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    live = bs.updater_dir(game)
    incoming = _make_updater(tmp_path / "incoming", "2.0.0")
    aside = bs.mods_root(game) / "in-the-way"
    aside.mkdir()
    t = time.monotonic()
    with pytest.raises(OSError):
        bs._publish(incoming, live, aside, say=lambda *a: None)
    with pytest.raises(PermissionError):
        bs._replace_retrying(incoming, aside)
    assert time.monotonic() - t < 2, "an occupied destination was waited on"
    assert bs.resident_version(game) == "1.0.0"


def test_a_redeploy_steps_around_a_prev_copy_it_cannot_delete(game, payload):
    """rmtree(ignore_errors=True) leaves `updater.prev` behind when a file in it is held; the
    publish then renamed onto an existing directory and failed on every later deploy."""
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    stuck = _make_updater(bs.mods_root(game) / (bs.UPDATER_DIR + ".prev"), "0.9.0")
    with open(stuck / "scripts" / "install.py", "rb"):
        bs.deploy(game, payload, "2.0.0", say=lambda *a: None)
    assert bs.resident_version(game) == "2.0.0"
    assert bs.is_usable(bs.updater_dir(game))


def test_a_refused_undo_reports_what_blocked_the_publish_and_loses_nothing(
        game, payload, tmp_path, monkeypatch):
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    newp = _make_updater(tmp_path / "newgen", "2.0.0")
    monkeypatch.setattr(bs, "RENAME_RETRY_SECONDS", 0.1, raising=False)
    real = Path.replace

    def both_locked(self, target):
        if self.name == bs.NEW_DIR:
            raise PermissionError(13, "publish blocked")
        if self.name == bs.OLD_DIR:
            raise PermissionError(13, "undo blocked")
        return real(self, target)
    monkeypatch.setattr(Path, "replace", both_locked)
    with pytest.raises(PermissionError, match="publish blocked"):
        bs.swap_in(game, newp, say=lambda *a: None)
    monkeypatch.undo()
    bs.reconcile(game, say=lambda *a: None)
    assert bs.resident_version(game) == "2.0.0", "neither copy survived a refused undo"


def test_reconcile_moves_on_when_a_candidate_cannot_be_promoted(game, monkeypatch):
    """reconcile() ships frozen in generation 1: a promotion that fails must not take every other
    copy down with it into the crash handler."""
    root = bs.mods_root(game)
    root.mkdir(parents=True)
    new = _make_updater(root / bs.NEW_DIR, "2.0.0")
    _make_updater(root / bs.OLD_DIR, "1.0.0")
    monkeypatch.setattr(bs, "RENAME_RETRY_SECONDS", 0.1, raising=False)
    said = []
    with open(new / "tools" / "python" / "python.exe", "rb"):
        bs.reconcile(game, say=said.append)
    assert any("could not put updater.new in place" in s for s in said), said
    assert bs.resident_version(game) == "1.0.0"


def test_reconcile_waits_out_a_held_candidate(game):
    """reconcile() promotes a freshly copied tree -- what a scan is still reading. A bare rename
    there sent generation 1 to the crash handler."""
    root = bs.mods_root(game)
    root.mkdir(parents=True)
    new = _make_updater(root / bs.NEW_DIR, "2.0.0")
    hold = _Hold(new / "tools" / "python" / "python.exe")
    try:
        bs.reconcile(game, say=hold.say)
    finally:
        hold.f.close()
    assert any(WAITING in s for s in hold.said), hold.said
    assert bs.resident_version(game) == "2.0.0"


#: All eight live/old/new combinations, exhaustively.
_COMBOS = [(l, o, n) for l in (0, 1) for o in (0, 1) for n in (0, 1)]


@pytest.mark.parametrize("live_v,old_v,new_v", _COMBOS,
                         ids=[f"live{l}-old{o}-new{n}" for l, o, n in _COMBOS])
def test_reconcile_repairs_every_crash_mid_swap_state(game, live_v, old_v, new_v):
    """A crash during the swap leaves one of these states. Each must end with a WORKING resident
    updater (not merely a directory with a VERSION file), leave no debris, and be idempotent."""
    root = bs.mods_root(game)
    root.mkdir(parents=True, exist_ok=True)
    live, old, new = root / bs.UPDATER_DIR, root / bs.OLD_DIR, root / bs.NEW_DIR
    if live_v:
        _make_updater(live, "1.0.0")
    if old_v:
        _make_updater(old, "1.0.0")
    if new_v:
        _make_updater(new, "2.0.0")

    bs.reconcile(game, say=lambda *a: None)
    first = bs.resident_version(game)
    if not (live_v or old_v or new_v):
        assert first == ver.UNKNOWN
    else:
        assert bs.is_usable(live), "no USABLE updater after reconcile"
        assert not old.exists() and not new.exists(), "debris left behind"

    bs.reconcile(game, say=lambda *a: None)
    assert bs.resident_version(game) == first, "reconcile is not idempotent"


def test_reconcile_prefers_the_new_generation_over_the_old_one(game):
    """A crash after `new -> updater` but before deleting `updater.old` must keep the NEW one."""
    root = bs.mods_root(game)
    root.mkdir(parents=True)
    _make_updater(root / bs.NEW_DIR, "2.0.0")
    _make_updater(root / bs.OLD_DIR, "1.0.0")
    bs.reconcile(game, say=lambda *a: None)
    assert bs.resident_version(game) == "2.0.0"


def test_reconcile_never_promotes_a_partial_copy_over_a_good_one(game):
    """THE destructive case. `updater.new` is built by a multi-hundred-megabyte copytree, so for
    tens of seconds it is a partial directory. Promoting by NAME meant reconcile installed that
    shell and then deleted `updater.old` -- the only working copy left."""
    root = bs.mods_root(game)
    root.mkdir(parents=True)
    _make_updater(root / bs.OLD_DIR, "1.0.0")
    partial = root / bs.NEW_DIR
    partial.mkdir()
    (partial / bs.VERSION_FILE).write_text("2.0.0\n", encoding="ascii")   # nothing else yet

    bs.reconcile(game, say=lambda *a: None)
    assert bs.is_usable(bs.updater_dir(game)), "a partial copy was promoted"
    assert bs.resident_version(game) == "1.0.0", "the good previous copy was discarded"


def test_reconcile_recovers_from_an_interrupted_deploy(game):
    """deploy() renames `updater -> updater.prev` then `staging -> updater`. A kill between them
    leaves NO updater and a perfectly good `.prev`, which reconcile did not know about."""
    root = bs.mods_root(game)
    root.mkdir(parents=True)
    _make_updater(root / (bs.UPDATER_DIR + ".prev"), "1.0.0")
    assert not bs.updater_dir(game).exists()
    bs.reconcile(game, say=lambda *a: None)
    assert bs.is_usable(bs.updater_dir(game))
    assert bs.resident_version(game) == "1.0.0"


def test_reconcile_keeps_leftovers_when_nothing_can_be_recovered(game):
    """If no candidate is usable, the debris may be all the player has -- deleting it is worse
    than leaving it."""
    root = bs.mods_root(game)
    root.mkdir(parents=True)
    junk = root / bs.OLD_DIR
    junk.mkdir()
    (junk / "something.txt").write_text("partial", encoding="ascii")
    bs.reconcile(game, say=lambda *a: None)
    assert junk.exists(), "the only remaining copy was deleted"


# ---------------------------------------------------------------- generation cap

def test_generation_two_never_re_execs(game, monkeypatch):
    """SAFEGUARD 1: the cap is what makes an update loop structurally impossible rather than
    merely unlikely. Generation 2 must not spawn a generation 3 whatever the manifest offers."""
    spawned = []
    monkeypatch.setattr(bs.subprocess, "Popen",
                        lambda *a, **k: spawned.append(a) or pytest.fail("gen 2 re-exec'd"))
    monkeypatch.setattr(bs, "_run_installer", lambda *a, **k: ix.EXIT_OK)
    monkeypatch.setattr(bs, "_wait_for_pid", lambda *a, **k: True)
    code = bs.run(["--game-dir", str(game), "--generation", "2", "--no-wait"])
    assert code == ix.EXIT_OK
    assert spawned == []


def test_a_generation_above_the_cap_is_treated_as_the_cap(game, monkeypatch):
    monkeypatch.setattr(bs, "_run_installer", lambda *a, **k: ix.EXIT_OK)
    monkeypatch.setattr(bs, "_wait_for_pid", lambda *a, **k: True)
    monkeypatch.setattr(bs.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("a capped generation re-exec'd"))
    assert bs.run(["--game-dir", str(game), "--generation", "7", "--no-wait"]) == ix.EXIT_OK


def test_a_failed_update_still_leaves_the_NEW_installer_resident(game, payload, tmp_path,
                                                                 monkeypatch):
    """The swap precedes the install deliberately.

    Generation 2 is already the new payload, so the swap has no effect on the install about to
    run -- it only decides what the player has next time. Swapping first means an interrupted or
    failed update leaves the CORRECT installer armed, with nothing to download again. The
    previous order (install, then swap) left the old installer resident, so a retry re-downloaded
    the same payload and re-ran the whole handover.
    """
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    newgen = _make_updater(tmp_path / "gen2" / "payload", "2.0.0")
    # Generation 2 runs from <payload>/scripts/ in the shipped layout.
    monkeypatch.setattr(bs, "_SCRIPTS", newgen / "scripts")
    monkeypatch.setattr(bs, "_run_installer", lambda *a, **k: ix.EXIT_ERROR)
    monkeypatch.setattr(bs, "_wait_for_pid", lambda *a, **k: True)

    code = bs.run(["--game-dir", str(game), "--generation", "2", "--no-wait",
                   "--swap-into", str(bs.updater_dir(game))])
    assert code == ix.EXIT_ERROR, "the failure must still be reported"
    assert bs.resident_version(game) == "2.0.0", \
        "a failed update left the OLD installer resident; the retry would re-download"


def test_the_swap_happens_before_the_install(game, payload, tmp_path, monkeypatch):
    """Ordering, asserted directly: the installer must observe the new payload already resident."""
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    newgen = _make_updater(tmp_path / "gen2" / "payload", "2.0.0")
    monkeypatch.setattr(bs, "_SCRIPTS", newgen / "scripts")
    monkeypatch.setattr(bs, "_wait_for_pid", lambda *a, **k: True)
    seen = {}

    def spy(*a, **k):
        seen["resident_at_install_time"] = bs.resident_version(game)
        return ix.EXIT_OK
    monkeypatch.setattr(bs, "_run_installer", spy)

    bs.run(["--game-dir", str(game), "--generation", "2", "--no-wait",
            "--swap-into", str(bs.updater_dir(game))])
    assert seen["resident_at_install_time"] == "2.0.0"


def test_a_failed_swap_does_not_stop_the_update(game, payload, monkeypatch):
    """SAFEGUARD 4: becoming resident is secondary; applying the update is the point."""
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    monkeypatch.setattr(bs, "_wait_for_pid", lambda *a, **k: True)

    def boom(*a, **k):
        raise OSError("cannot replace the resident updater")
    monkeypatch.setattr(bs, "swap_in", boom)
    ran = []
    monkeypatch.setattr(bs, "_run_installer", lambda *a, **k: ran.append(1) or ix.EXIT_OK)
    code = bs.run(["--game-dir", str(game), "--generation", "2", "--no-wait",
                   "--swap-into", str(bs.updater_dir(game))])
    assert code == ix.EXIT_OK
    assert ran, "the update was skipped because the swap failed"
    assert bs.resident_version(game) == "1.0.0", "the previous installer should remain"


def test_generation_two_refuses_to_run_alongside_generation_one(game, monkeypatch):
    monkeypatch.setattr(bs, "_wait_for_pid", lambda *a, **k: False)
    monkeypatch.setattr(bs, "_run_installer",
                        lambda *a, **k: pytest.fail("ran while gen 1 was still alive"))
    with pytest.raises(ix.InstallerError, match="did not exit"):
        bs.run(["--game-dir", str(game), "--generation", "2", "--wait-pid", "4321",
                "--no-wait"])


def test_a_swap_failure_does_not_undo_a_successful_install(game, payload, monkeypatch):
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    monkeypatch.setattr(bs, "_run_installer", lambda *a, **k: ix.EXIT_OK)
    monkeypatch.setattr(bs, "_wait_for_pid", lambda *a, **k: True)

    def boom(*a, **k):
        raise OSError("cannot replace the resident updater")
    monkeypatch.setattr(bs, "swap_in", boom)
    code = bs.run(["--game-dir", str(game), "--generation", "2", "--no-wait",
                   "--swap-into", str(bs.updater_dir(game))])
    assert code == ix.EXIT_OK, "a cosmetic swap failure must not fail a completed update"


# ---------------------------------------------------------------- generation 1

def _signed_doc(tmp_path: Path, **over):
    doc = {
        "schema": 1, "protocol": 1, "product": "longevity-vaccine",
        "latest": "1.0.0", "min_upgradable_from": "0.0.0",
        "manual_install_required": False, "manual_install_reason": None,
        "unsupported_versions": [], "unsupported_targets": [], "yanked": [],
        "modules": {},
    }
    doc.update(over)
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    sm.sign_file(SEED, m)
    return m


@pytest.fixture
def trust(monkeypatch):
    monkeypatch.setattr(mf, "PUBLIC_KEY_HEX", PK_HEX)


def test_generation_one_never_patches_when_it_hands_over(game, payload, tmp_path, trust,
                                                         monkeypatch):
    """SAFEGUARD 2: if gen 1 decides to re-exec it exits WITHOUT touching the game, so a failure
    during self-update leaves the previous working install completely intact."""
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    monkeypatch.setattr(bs, "_run_installer",
                        lambda *a, **k: pytest.fail("generation 1 ran the installer"))
    # The SHIPPED layout, which is what _download_new_payload actually produces (it runs the
    # payload through deploy()). A stub whose shape disagrees with production is how this test
    # once passed while the only self-update path there is aborted every time.
    newpay = tmp_path / "newpay"
    (newpay / "scripts").mkdir(parents=True)
    (newpay / "scripts" / "bootstrap.py").write_text("pass\n", encoding="ascii")
    newpy = newpay / bs.runtime_exe_rel()               # the interpreter deploy() put there, for THIS Windows
    newpy.parent.mkdir(parents=True)
    newpy.write_bytes(b"MZfake")
    monkeypatch.setattr(bs, "_download_new_payload", lambda *a, **k: newpay)
    spawned = []
    monkeypatch.setattr(bs.subprocess, "Popen", lambda cmd, **k: spawned.append(cmd))

    m = _signed_doc(tmp_path, latest="2.0.0",
                    modules={"base": {"version": "2.0.0", "url": "file:///x", "sha256": "0" * 64}})
    code = bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"])
    assert code == ix.EXIT_OK
    assert spawned, "generation 2 was never started"
    cmd = spawned[0]
    assert cmd[0] == str(newpy), "generation 2 must run on the DOWNLOADED payload's interpreter, never sys.executable"
    assert "--generation" in cmd and "2" in cmd
    assert "--wait-pid" in cmd, "gen 2 must know which process to wait for"
    assert bs.resident_version(game) == "1.0.0", "gen 1 replaced the resident updater itself"


def test_generation_one_hands_over_to_a_REALLY_downloaded_payload(game, payload, tmp_path,
                                                                   trust, monkeypatch):
    """The shape check the previous test cannot make.

    That one stubs `_download_new_payload`, so it proves only that gen 1 spawns SOMETHING -- and
    while its stub built the old flat layout, it went on passing even though the real production
    path aborted with "the downloaded installer is incomplete" on every self-update. Here the
    payload is a real zip, fetched and unpacked by the real code, so the paths gen 1 looks for
    must match the paths `deploy()` actually writes.
    """
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    monkeypatch.setattr(bs, "_run_installer",
                        lambda *a, **k: pytest.fail("generation 1 ran the installer"))
    archive = tmp_path / "base-2.0.0.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for f in sorted(payload.rglob("*")):
            if f.is_file():
                z.write(f, str(f.relative_to(payload)).replace("\\", "/"))
    spawned = []
    monkeypatch.setattr(bs.subprocess, "Popen", lambda cmd, **k: spawned.append(cmd))
    m = _signed_doc(tmp_path, latest="2.0.0", modules={"base": {
        "version": "2.0.0", "url": archive.as_uri(),
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "size": archive.stat().st_size}})

    monkeypatch.delenv("LONGEVITY_NO_WAIT", raising=False)
    code = bs.run(["--game-dir", str(game), "--manifest", str(m)])
    assert code == ix.EXIT_OK
    assert spawned, "generation 2 was never started from the downloaded payload"
    # Gen 2 waits for gen 1 to EXIT before swapping; a "Press Enter" here made it refuse.
    assert os.environ.get("LONGEVITY_NO_WAIT") == "1", "generation 1 must exit without a keypress after handing over"
    assert not ix.interactive()
    cmd = spawned[0]
    # The interpreter and the script both have to come out of the DOWNLOADED tree.
    assert any(str(c).endswith("bootstrap.py") for c in cmd), cmd
    assert any("payload-2.0.0" in str(c) for c in cmd), cmd
    assert bs.resident_version(game) == "1.0.0", "gen 1 replaced the resident updater itself"


def test_the_bootstrap_accepts_the_flags_the_launcher_forwards(game, payload, tmp_path, trust,
                                                               monkeypatch):
    """run-install.bat routes --update here, so every flag a player may type after --update has
    to parse. A usage error would surface as "the installer did not understand its arguments"."""
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    seen = {}
    monkeypatch.setattr(bs, "_run_installer",
                        lambda scripts, gd, args: seen.update(vars(args)) or ix.EXIT_OK)
    m = _signed_doc(tmp_path, latest="1.0.0")
    # `--update` FIRST: run-install.bat forwards its whole argument list, and that flag is the
    # one it always includes. Leaving it out of this test hid a bootstrap that rejected it --
    # every `run-install.bat --update` died with "unrecognized arguments".
    code = bs.run(["--update", "--game-dir", str(game), "--manifest", str(m), "--no-wait",
                   "--modules", "movies-hd", "--no-prompt", "--offline", "--only-listed"])
    assert code == ix.EXIT_OK
    assert seen.get("modules") == "movies-hd", "the module selection was dropped"
    assert seen.get("only_listed") is True, "the game's --only-listed was dropped"


def test_generation_two_hands_only_listed_to_the_worker(game, monkeypatch):
    seen = {}
    monkeypatch.setattr(bs, "_run_installer",
                        lambda scripts, gd, args: seen.update(vars(args)) or ix.EXIT_OK)
    monkeypatch.setattr(bs, "_wait_for_pid", lambda *a, **k: True)
    assert bs.run(["--game-dir", str(game), "--generation", "2", "--no-wait", "--only-listed",
                   "--modules", "portraits-hd"]) == ix.EXIT_OK
    assert seen["only_listed"] is True and seen["modules"] == "portraits-hd"


def test_only_listed_with_repair_is_refused(game):
    with pytest.raises(ix.InstallerError, match="cannot be combined with --repair"):
        bs.run(["--update", "--game-dir", str(game), "--no-wait", "--repair", "--only-listed"])


def test_generation_two_never_calls_a_pack_current_under_only_listed(game, monkeypatch):
    import receipt as rc
    rc.write(game, target_id="pracx", modules={"base": {"version": "2.0.0"},
                                               "movies-hd": {"version": "1.0.0"}})
    monkeypatch.setattr(bs, "_run_installer", lambda *a, **k: ix.EXIT_OK)
    monkeypatch.setattr(bs, "_wait_for_pid", lambda *a, **k: True)
    assert bs.run(["--game-dir", str(game), "--generation", "2", "--no-wait",
                   "--only-listed"]) == ix.EXIT_OK
    assert "up to date" not in bs._VERDICT[1] and "installed packs: HD cinematics v1.0.0" \
        in bs._VERDICT[1], bs._VERDICT
    assert bs.run(["--game-dir", str(game), "--generation", "2", "--no-wait"]) == ix.EXIT_OK
    assert "(HD cinematics v1.0.0 up to date)" in bs._VERDICT[1]


def test_an_unknown_flag_from_a_newer_game_is_ignored_not_fatal(game, payload, tmp_path, trust,
                                                               monkeypatch, capsys):
    """The DLL can be newer than the resident bootstrap (a failed swap is not fatal). A strict
    parse made every new protocol flag kill the in-game update path until a manual reinstall."""
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    seen = {}
    monkeypatch.setattr(bs, "_run_installer",
                        lambda scripts, gd, args: seen.update(vars(args)) or ix.EXIT_OK)
    m = _signed_doc(tmp_path, latest="1.0.0")
    assert bs.run(["--update", "--game-dir", str(game), "--manifest", str(m), "--no-wait",
                   "--modules", "movies-hd", "--some-future-flag", "--offline"]) == ix.EXIT_OK
    assert seen.get("modules") == "movies-hd"
    assert "ignoring arguments this version does not know: --some-future-flag" \
        in capsys.readouterr().err


def test_the_worker_gets_only_listed_exactly_when_the_game_passed_it(game, monkeypatch):
    calls = []
    monkeypatch.setattr(bs.subprocess, "call", lambda cmd, **k: calls.append(cmd) or 0)
    base = dict(repair=False, manifest=None, modules="portraits-hd", wait_pid=None, no_wait=True,
                offline=True)
    for flag in (True, False):
        bs._run_installer(_SCRIPTS, game, type("A", (), dict(base, only_listed=flag))())
    assert "--only-listed" in calls[0] and "--only-listed" not in calls[1]
    assert calls[0][calls[0].index("--modules") + 1] == "portraits-hd"


def test_generation_one_hands_only_listed_to_generation_two(game, payload, tmp_path, trust,
                                                            monkeypatch):
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    monkeypatch.setattr(bs, "_run_installer", lambda *a, **k: pytest.fail("generation 1 installed"))
    newpay = tmp_path / "newpay"
    (newpay / "scripts").mkdir(parents=True)
    (newpay / "scripts" / "bootstrap.py").write_text("pass\n", encoding="ascii")
    py = newpay / bs.runtime_exe_rel()
    py.parent.mkdir(parents=True)
    py.write_bytes(b"MZfake")
    monkeypatch.setattr(bs, "_download_new_payload", lambda *a, **k: newpay)
    spawned = []
    monkeypatch.setattr(bs.subprocess, "Popen", lambda cmd, **k: spawned.append(cmd))
    m = _signed_doc(tmp_path, latest="2.0.0",
                    modules={"base": {"version": "2.0.0", "url": "file:///x", "sha256": "0" * 64}})
    assert bs.run(["--update", "--game-dir", str(game), "--manifest", str(m), "--no-wait",
                   "--only-listed", "--modules", "portraits-hd"]) == ix.EXIT_OK
    (cmd,) = spawned
    assert "--only-listed" in cmd and cmd[cmd.index("--modules") + 1] == "portraits-hd"
    assert cmd[cmd.index("--generation") + 1] == "2"


def test_only_listed_with_nothing_listed_and_a_current_base_changes_nothing(game, payload,
                                                                            tmp_path, trust,
                                                                            monkeypatch, capsys):
    """A stale pack the game did not list is not part of the update: no worker, and the pack is
    named as left behind -- never called current."""
    import receipt as rc
    bs.deploy(game, payload, "2.0.0", say=lambda *a: None)
    rc.write(game, target_id="pracx", modules={"base": {"version": "2.0.0"},
                                               "movies-hd": {"version": "1.0.0"}})
    monkeypatch.setattr(bs.subprocess, "Popen", lambda *a, **k: pytest.fail("re-exec'd"))
    called = []
    monkeypatch.setattr(bs, "_run_installer", lambda *a, **k: called.append(1) or ix.EXIT_OK)
    m = _signed_doc(tmp_path, latest="2.0.0",
                    modules={"base": {"version": "2.0.0", "url": "file:///x", "sha256": "0" * 64},
                             "movies-hd": {"version": "1.1.0", "url": "file:///y",
                                           "sha256": "0" * 64}})
    assert bs.run(["--update", "--game-dir", str(game), "--manifest", str(m), "--no-wait",
                   "--only-listed"]) == ix.EXIT_OK
    out = capsys.readouterr().out
    assert called == [], "an empty list was handed to the installer"
    assert "HD cinematics v1.1.0: not part of this update (stays at v1.0.0)" in out, out
    title, body = bs._VERDICT
    assert title == "ALREADY UP TO DATE" and "Everything you have installed is current" not in body
    # Without the flag the same run updates the pack (the console's own semantics).
    assert bs.run(["--update", "--game-dir", str(game), "--manifest", str(m), "--no-wait"]) \
        == ix.EXIT_OK
    assert called == [1]


def test_an_unknown_extra_is_refused_before_anything_is_fetched(game, payload, tmp_path, trust,
                                                                 monkeypatch):
    """Through the launcher a typo used to cache the manifest, reconcile the tree, download a
    whole new installer and swap it in -- and only THEN be refused, as a worker whose refusal
    text was muted, under a verdict saying it was not certain how far the install got."""
    import install as inst
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    monkeypatch.setattr(inst, "fetch_manifest",
                        lambda *a, **k: pytest.fail("fetched the manifest for a bad --modules"))
    with pytest.raises(ix.InstallerError, match='"bogus" is not an extra') as e:
        bs.run(["--update", "--game-dir", str(game), "--no-wait", "--modules", "bogus"])
    assert e.value.changed is False
    assert "HD cinematics" in (e.value.detail or "")


def test_a_manifest_whose_modules_field_is_not_a_dict_is_refused_cleanly(game, payload,
                                                                         tmp_path, trust,
                                                                         monkeypatch):
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    for bad in (["x"], "abc", {"base": "x"}):
        m = _signed_doc(tmp_path, latest="2.0.0", modules=bad)
        with pytest.raises(ix.InstallerError, match="does not say where"):
            bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"])


def test_the_new_installer_is_staged_under_its_own_folder_by_the_shared_sanitiser(game, payload,
                                                                                  monkeypatch):
    """The bootstrap had its own, weaker name filter: a URL ending in `/.~` reduced to "." and
    the archive became the staging DIRECTORY itself, its .part landing outside staging."""
    import fetch as fetchmod
    seen = {}

    def fake_download(url, dest, **kw):
        seen["dest"] = Path(dest)
        raise fetchmod.FetchError("stop here")
    monkeypatch.setattr(fetchmod, "download", fake_download)
    args = bs.build_args(["--game-dir", str(game), "--no-wait"]) if hasattr(bs, "build_args") \
        else type("A", (), {"manifest": None})()
    for url in ("https://h/.~", "https://h/..", "https://h/C:evil.zip"):
        with pytest.raises(ix.InstallerError, match="could not be downloaded"):
            bs._download_new_payload(game, {"url": url, "sha256": "0" * 64}, "2.0.0", args)
        staging = fetchmod.staging_dir(game).resolve()
        assert seen["dest"].resolve().parent == staging / "base", seen["dest"]
        assert seen["dest"].name not in (".", "..", "")
    with pytest.raises(ix.InstallerError, match="does not say where"):
        bs._download_new_payload(game, {"url": 5, "sha256": "0" * 64}, "2.0.0", args)


def test_an_update_launched_from_the_game_waits_for_it_to_exit(game, payload, tmp_path, trust,
                                                              monkeypatch):
    """The game spawns `run-install.bat --update --wait-pid <its pid>` and then exits; the exe
    and every DLL are held open until it has. Starting the preflight a second early refused
    with "terranx_PRACX.exe is in use" for the player who had just clicked update."""
    import subprocess as sp
    import install as inst
    bs.deploy(game, payload, "2.0.0", say=lambda *a: None)
    seen = {}
    monkeypatch.setattr(bs, "_run_installer",
                        lambda scripts, gd, args: seen.update(vars(args)) or ix.EXIT_OK)
    m = _signed_doc(tmp_path, latest="2.0.0", modules={
        "base": {"version": "2.0.0", "url": "file:///x", "sha256": "0" * 64}})
    # A process that has already exited: the wait returns at once and the run proceeds.
    dead = sp.run([sys.executable, "-c", "pass"], capture_output=True)
    gone = sp.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    code = bs.run(["--update", "--game-dir", str(game), "--manifest", str(m), "--no-wait",
                   "--modules", "movies-hd", "--wait-pid", str(gone.pid)])
    assert code == ix.EXIT_OK and seen.get("wait_pid") == gone.pid, \
        "the pid is forwarded so the worker's preflight asserts it too"
    # A process that keeps running: a bounded wait, then a clean refusal -- never a crash and
    # never a preflight against files the game still holds.
    monkeypatch.setattr(inst, "GAME_EXIT_WAIT", 1)
    alive = sp.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with pytest.raises(ix.InstallerError, match="still running") as e:
            bs.run(["--update", "--game-dir", str(game), "--manifest", str(m), "--no-wait",
                    "--wait-pid", str(alive.pid)])
        assert e.value.changed is False
    finally:
        alive.kill()
    del dead


def test_a_pack_only_update_names_the_pack_in_its_verdict(game, payload, tmp_path, trust,
                                                          monkeypatch):
    bs.deploy(game, payload, "2.0.0", say=lambda *a: None)
    _receipt(game, base="2.0.0", **{"movies-hd": "1.0.0"})

    def fake_install(scripts, gd, args):
        _receipt(game, base="2.0.0", **{"movies-hd": "1.1.0"})     # what the worker would do
        return ix.EXIT_OK
    monkeypatch.setattr(bs, "_run_installer", fake_install)
    monkeypatch.setattr(bs, "_VERDICT", None)
    m = _signed_doc(tmp_path, latest="2.0.0", modules={
        "base": {"version": "2.0.0", "url": "file:///x", "sha256": "0" * 64},
        "movies-hd": {"version": "1.1.0", "url": "file:///y", "sha256": "0" * 64},
    })
    assert bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"]) == ix.EXIT_OK
    assert bs._VERDICT == ("UPDATE COMPLETE",
                           "HD cinematics v1.1.0 installed. Nothing else needed changing.")
    assert bs._NOTE_ARGS and bs._NOTE_ARGS[0] == game, "the closing note (exe + shortcut) follows every completed update"


def test_a_completed_update_offers_to_start_the_game(game, monkeypatch):
    """User 2026-11-05: an update ended with "Press Enter to close" and no "Start the game now?",
    which a first install offers. The bootstrap's guard now offers the exe its closing note names
    -- after a completed update only (no note on a hand-over or a failure: no offer either)."""
    import install as inst
    exe = game / "terranx_PRACX.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(inst, "mod_exe", lambda gd, tid: exe if (gd, tid) == (game, "pracx") else None)
    monkeypatch.setattr(bs, "_NOTE_ARGS", None)
    assert bs._relaunch_exe() is None
    monkeypatch.setattr(bs, "_NOTE_ARGS", (game, "pracx"))
    assert bs._relaunch_exe() == exe
    src = (_SCRIPTS / "bootstrap.py").read_text(encoding="utf-8")
    main_block = src[src.index('if __name__ == "__main__":'):]
    assert "relaunch_exe=_relaunch_exe" in main_block, "the guard must be handed the offer"
    # ...and the guard turns it into the question, as after an install.
    asked = []
    monkeypatch.setattr(ix, "offer_relaunch", lambda e: asked.append(e) or False)
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)
    assert ix.run_guarded(lambda: ix.EXIT_OK, relaunch_exe=bs._relaunch_exe) == ix.EXIT_OK
    assert asked == [exe]


def test_a_kill_switch_stops_everything_before_any_download(game, payload, tmp_path, trust,
                                                            monkeypatch):
    """SAFEGUARD 6, and the ordering that matters: the kill switch is honoured BEFORE any version
    compare and before any download, because it is the only remedy for a defective bootstrap
    already in the wild."""
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    monkeypatch.setattr(bs, "_download_new_payload",
                        lambda *a, **k: pytest.fail("downloaded despite the kill switch"))
    monkeypatch.setattr(bs.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("spawned despite the kill switch"))
    m = _signed_doc(tmp_path, latest="2.0.0", manual_install_required=True,
                    manual_install_reason="bootstrap_defect",
                    modules={"base": {"version": "2.0.0", "url": "file:///x",
                                      "sha256": "0" * 64}})
    with pytest.raises(ix.InstallerError) as e:
        bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"])
    assert mf.DOWNLOAD_URL in (e.value.remedy or "")
    assert e.value.changed is False


def test_an_unknown_protocol_stops_with_the_compiled_url(game, payload, tmp_path, trust,
                                                         monkeypatch):
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    monkeypatch.setattr(bs, "_download_new_payload",
                        lambda *a, **k: pytest.fail("downloaded despite an unknown protocol"))
    m = _signed_doc(tmp_path, protocol=99, latest="2.0.0")
    with pytest.raises(ix.InstallerError) as e:
        bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"])
    assert mf.DOWNLOAD_URL in (e.value.remedy or "")


def test_a_manifest_supplied_url_is_never_shown(game, payload, tmp_path, trust, monkeypatch):
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    m = _signed_doc(tmp_path, latest="2.0.0", manual_install_required=True,
                    download_url="http://evil.example/pwn")
    with pytest.raises(ix.InstallerError) as e:
        bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"])
    blob = " ".join(str(x) for x in (e.value.message, e.value.detail, e.value.remedy))
    assert "evil.example" not in blob
    assert "longevitymods.com" in blob


def test_an_untrusted_manifest_stops_generation_one(game, payload, tmp_path, trust):
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    m = _signed_doc(tmp_path, latest="2.0.0")
    m.write_bytes(m.read_bytes().replace(b"2.0.0", b"3.0.0"))     # breaks the signature
    with pytest.raises(ix.InstallerError, match="could not be trusted"):
        bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"])


def test_an_already_current_installer_applies_in_place(game, payload, tmp_path, trust,
                                                       monkeypatch):
    bs.deploy(game, payload, "2.0.0", say=lambda *a: None)
    monkeypatch.setattr(bs.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("re-exec'd when already current"))
    called = []
    monkeypatch.setattr(bs, "_run_installer", lambda *a, **k: called.append(1) or ix.EXIT_OK)
    m = _signed_doc(tmp_path, latest="2.0.0",
                    modules={"base": {"version": "2.0.0", "url": "file:///x",
                                      "sha256": "0" * 64}})
    # latest == installed -> decide() says NOTHING, so it should not even run the installer.
    assert bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"]) == ix.EXIT_OK
    assert called == []


def test_an_incomplete_downloaded_payload_is_refused(game, payload, tmp_path, trust, monkeypatch):
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    empty = tmp_path / "empty-payload"
    empty.mkdir()
    monkeypatch.setattr(bs, "_download_new_payload", lambda *a, **k: empty)
    monkeypatch.setattr(bs.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("spawned an incomplete payload"))
    m = _signed_doc(tmp_path, latest="2.0.0",
                    modules={"base": {"version": "2.0.0", "url": "file:///x",
                                      "sha256": "0" * 64}})
    with pytest.raises(ix.InstallerError, match="incomplete"):
        bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"])


def test_a_missing_game_dir_is_refused(tmp_path):
    with pytest.raises(ix.InstallerError):
        bs.run(["--game-dir", str(tmp_path / "nope"), "--no-wait"])


# ---------------------------------------------------------------- the frozen contract

def test_the_bootstrap_depends_only_on_things_that_ship():
    """It must not import a dev-only module: the resident copy has only the shipped set."""
    src = (_SCRIPTS / "bootstrap.py").read_text(encoding="utf-8")
    for forbidden in ("import pytest", "import numpy", "import frida", "import capstone",
                      "import keystone", "import pefile", "sign_manifest"):
        assert forbidden not in src, f"bootstrap.py references {forbidden}"


def test_the_generation_cap_is_a_constant_not_a_literal():
    assert bs.MAX_GENERATION == 2
    src = (_SCRIPTS / "bootstrap.py").read_text(encoding="utf-8")
    assert "if gen >= MAX_GENERATION" in src, \
        "the cap must be enforced against the constant, so it cannot drift"


# ---------------------------------------------------------------- independent module updates

def _receipt(game: Path, **modules) -> None:
    import receipt as rc
    rc.write(game, target_id="pracx",
             modules={n: {"version": v} for n, v in modules.items()}, say=lambda *a: None)


class _Killed(BaseException):
    """Generation 2 dying mid-run: not an Exception, so nothing on the way out handles it."""


@pytest.mark.parametrize("ending", ["killed", "failed"])
def test_a_gen_2_that_swapped_and_died_is_completed_by_the_next_run(game, payload, tmp_path,
                                                                    trust, monkeypatch, capsys,
                                                                    ending):
    """Gen 2 swaps the resident updater BEFORE it installs, so a gen 2 that dies (or fails) after
    the swap leaves a NEW resident over an OLD receipt. Generation 1 decided with the resident
    version alone and answered that state with "already current" -- forever, while --check
    (receipt-driven) kept offering the update. The next run must finish the install with the
    resident installer: no new download, no second hand-over."""
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    _receipt(game, base="1.0.0")
    newgen = _make_updater(tmp_path / "gen2" / "payload", "2.0.0")
    monkeypatch.setattr(bs, "_SCRIPTS", newgen / "scripts")
    monkeypatch.setattr(bs, "_wait_for_pid", lambda *a, **k: True)

    def die(*a, **k):
        if ending == "killed":
            raise _Killed()
        return ix.EXIT_ERROR
    monkeypatch.setattr(bs, "_run_installer", die)
    gen2 = ["--game-dir", str(game), "--generation", "2", "--no-wait",
            "--swap-into", str(bs.updater_dir(game))]
    if ending == "killed":
        with pytest.raises(_Killed):
            bs.run(gen2)
    else:
        assert bs.run(gen2) == ix.EXIT_ERROR
    assert bs.resident_version(game) == "2.0.0", "precondition: the swap happened"
    import receipt as rc
    assert rc.module_version(rc.read(game), "base") == "1.0.0", "precondition: no install"

    # The next run is generation 1 of the NEW resident copy.
    monkeypatch.setattr(bs, "_SCRIPTS", bs.updater_dir(game) / "scripts")
    monkeypatch.setattr(bs.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("re-exec'd although the resident is current"))
    monkeypatch.setattr(bs, "_download_new_payload",
                        lambda *a, **k: pytest.fail("re-downloaded the installer already in place"))
    called = []
    monkeypatch.setattr(bs, "_run_installer",
                        lambda scripts, gd, args: called.append(Path(scripts)) or ix.EXIT_OK)
    m = _signed_doc(tmp_path, latest="2.0.0",
                    modules={"base": {"version": "2.0.0", "url": "file:///x", "sha256": "0" * 64}})
    capsys.readouterr()
    assert bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"]) == ix.EXIT_OK
    out = capsys.readouterr().out
    assert called == [bs.updater_dir(game) / "scripts"], \
        "the unfinished update was not retried with the resident installer"
    assert "already current" not in out, out
    assert "the last update did not finish" in out, out


def _pending(game, payload, monkeypatch, *, resident="2.0.0", receipt_base="1.0.0",
             from_resident=True):
    """An unfinished update: the resident updater at `resident`, the receipt behind it."""
    import receipt as rc
    bs.deploy(game, payload, resident, say=lambda *a: None)
    if receipt_base is None:
        rc.write(game, target_id="pracx", modules={"base": {"version": "garbage"}},
                 say=lambda *a: None)
    else:
        _receipt(game, base=receipt_base)
    if from_resident:
        monkeypatch.setattr(bs, "_SCRIPTS", bs.updater_dir(game) / "scripts")
    calls = {"inplace": 0, "download": 0}

    def inplace(*a, **k):
        calls["inplace"] += 1
        return ix.EXIT_OK

    def download(*a, **k):
        calls["download"] += 1
        raise ix.InstallerError("stop at the download", code=ix.EXIT_ABORTED, changed=False)
    monkeypatch.setattr(bs, "_run_installer", inplace)
    monkeypatch.setattr(bs, "_download_new_payload", download)
    return calls


def _run_gen1(game, m):
    try:
        return bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"])
    except ix.InstallerError as e:
        assert "stop at the download" in e.message, e.message
        return "downloaded"


def test_a_withdrawn_resident_is_never_installed_by_completing_in_place(game, payload, tmp_path,
                                                                        trust, monkeypatch):
    """Rolled back: 2.0.0 swapped in and died, then the manifest yanked it for 1.5.0. Completing
    in place would run the resident worker, which installs ITS OWN 2.0.0 -- the yanked release.
    The update to 1.5.0 is fetched instead (and brings the resident back down)."""
    calls = _pending(game, payload, monkeypatch)
    m = _signed_doc(tmp_path, latest="1.5.0", yanked=["2.0.0"],
                    modules={"base": {"version": "1.5.0", "url": "file:///x", "sha256": "0" * 64}})
    assert _run_gen1(game, m) == "downloaded"
    assert calls == {"inplace": 0, "download": 1}


def test_an_unreadable_base_receipt_under_a_resident_is_completed_not_current(game, payload,
                                                                             tmp_path, trust,
                                                                             monkeypatch, capsys):
    """--check offers base=0.0.0>2.0.0 for such a receipt on every launch; answering "already
    current" here was the same nag loop as a failed gen 2."""
    calls = _pending(game, payload, monkeypatch, receipt_base=None)
    m = _signed_doc(tmp_path, latest="2.0.0",
                    modules={"base": {"version": "2.0.0", "url": "file:///x", "sha256": "0" * 64}})
    assert _run_gen1(game, m) == ix.EXIT_OK
    assert calls == {"inplace": 1, "download": 0}
    assert "already current" not in capsys.readouterr().out


def test_only_the_resident_copy_completes_an_unfinished_update_in_place(game, payload, tmp_path,
                                                                         trust, monkeypatch):
    """An OLDER downloaded installer run with --update would install its own version: it fetches
    the release on offer instead."""
    calls = _pending(game, payload, monkeypatch, from_resident=False)
    m = _signed_doc(tmp_path, latest="2.0.0",
                    modules={"base": {"version": "2.0.0", "url": "file:///x", "sha256": "0" * 64}})
    assert _run_gen1(game, m) == "downloaded"
    assert calls == {"inplace": 0, "download": 1}


def test_a_completed_update_names_the_base_in_its_verdict(game, payload, tmp_path, trust,
                                                          monkeypatch):
    import receipt as rc
    _pending(game, payload, monkeypatch)

    def install(*a, **k):
        _receipt(game, base="2.0.0", **{"movies-hd": "1.1.0"})
        return ix.EXIT_OK
    monkeypatch.setattr(bs, "_run_installer", install)
    _receipt(game, base="1.0.0", **{"movies-hd": "1.0.0"})
    m = _signed_doc(tmp_path, latest="2.0.0", modules={
        "base": {"version": "2.0.0", "url": "file:///x", "sha256": "0" * 64},
        "movies-hd": {"version": "1.1.0", "url": "file:///y", "sha256": "0" * 64}})
    assert _run_gen1(game, m) == ix.EXIT_OK
    assert rc.module_version(rc.read(game), "base") == "2.0.0"
    assert bs._VERDICT[1].startswith("Longevity Vaccine v2.0.0, HD cinematics v1.1.0 installed"), \
        bs._VERDICT


def test_a_kill_switch_on_the_resident_version_holds_over_an_older_receipt(game, payload,
                                                                           tmp_path, trust,
                                                                           monkeypatch):
    """Deciding with the receipt's older version must not let a defective RESIDENT bootstrap slip
    past a kill switch that names it."""
    bs.deploy(game, payload, "2.0.0", say=lambda *a: None)
    _receipt(game, base="1.0.0")
    monkeypatch.setattr(bs, "_run_installer", lambda *a, **k: pytest.fail("ran past the switch"))
    monkeypatch.setattr(bs, "_download_new_payload",
                        lambda *a, **k: pytest.fail("downloaded despite the kill switch"))
    m = _signed_doc(tmp_path, latest="2.0.0", unsupported_versions=["2.0.0"],
                    modules={"base": {"version": "2.0.0", "url": "file:///x", "sha256": "0" * 64}})
    with pytest.raises(ix.InstallerError) as e:
        bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"])
    assert e.value.changed is False


def test_a_receipt_newer_than_the_resident_still_fetches_the_new_installer(game, payload,
                                                                           tmp_path, trust,
                                                                           monkeypatch):
    """The other disagreement -- gen 2's swap failed, its install succeeded: the game is current
    but the resident installer is not, so the next run still re-arms it."""
    bs.deploy(game, payload, "1.0.0", say=lambda *a: None)
    _receipt(game, base="2.0.0")
    fetched = []

    def fake_download(*a, **k):
        fetched.append(1)
        raise ix.InstallerError("stop here", code=ix.EXIT_ABORTED, changed=False)
    monkeypatch.setattr(bs, "_download_new_payload", fake_download)
    monkeypatch.setattr(bs, "_run_installer", lambda *a, **k: pytest.fail("ran in place"))
    m = _signed_doc(tmp_path, latest="2.0.0",
                    modules={"base": {"version": "2.0.0", "url": "file:///x", "sha256": "0" * 64}})
    with pytest.raises(ix.InstallerError, match="stop here"):
        bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"])
    assert fetched, "a stale resident installer was left in place"


def test_a_stale_pack_hands_off_in_place_without_a_new_installer(game, payload, tmp_path, trust,
                                                                 monkeypatch):
    """A module release with the installer current is an UPDATE, applied by THIS installer: no
    download of a new payload, no generation 2 -- and no "already current" exit either, which is
    what used to happen because only the base version was ever compared."""
    bs.deploy(game, payload, "2.0.0", say=lambda *a: None)
    _receipt(game, base="2.0.0", **{"movies-hd": "1.0.0"})
    monkeypatch.setattr(bs.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("re-exec'd for a module-only update"))
    monkeypatch.setattr(bs, "_download_new_payload",
                        lambda *a, **k: pytest.fail("downloaded a new installer needlessly"))
    called = []
    monkeypatch.setattr(bs, "_run_installer",
                        lambda scripts, gd, args: called.append(args.modules) or ix.EXIT_OK)
    m = _signed_doc(tmp_path, latest="2.0.0", modules={
        "base": {"version": "2.0.0", "url": "file:///x", "sha256": "0" * 64},
        "movies-hd": {"version": "1.1.0", "url": "file:///y", "sha256": "0" * 64},
    })
    assert bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"]) == ix.EXIT_OK
    assert called == [None], "the installer must run, with the stale set left for it to derive"


def test_a_current_pack_does_not_make_an_already_current_run_do_anything(game, payload,
                                                                         tmp_path, trust,
                                                                         monkeypatch):
    bs.deploy(game, payload, "2.0.0", say=lambda *a: None)
    _receipt(game, base="2.0.0", **{"movies-hd": "1.1.0"})
    monkeypatch.setattr(bs, "_run_installer", lambda *a, **k: pytest.fail("ran for nothing"))
    m = _signed_doc(tmp_path, latest="2.0.0", modules={
        "base": {"version": "2.0.0", "url": "file:///x", "sha256": "0" * 64},
        "movies-hd": {"version": "1.1.0", "url": "file:///y", "sha256": "0" * 64},
    })
    assert bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"]) == ix.EXIT_OK


def test_an_already_current_run_announces_a_pack_the_player_does_not_have(game, payload,
                                                                          tmp_path, trust,
                                                                          monkeypatch, capsys):
    """The player who is up to date is precisely the one who never heard about a new pack: the
    notice used to be reachable only at the end of a base update."""
    bs.deploy(game, payload, "2.0.0", say=lambda *a: None)
    _receipt(game, base="2.0.0")
    monkeypatch.setattr(bs, "_run_installer", lambda *a, **k: pytest.fail("ran for nothing"))
    m = _signed_doc(tmp_path, latest="2.0.0", modules={
        "base": {"version": "2.0.0", "url": "file:///x", "sha256": "0" * 64},
        "movies-hd": {"version": "1.0.0", "url": "file:///y", "sha256": "0" * 64,
                      "size": 1300 << 20},
    })
    assert bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"]) == ix.EXIT_OK
    out = capsys.readouterr().out
    assert "HD cinematics: available, not installed (1.4 GB download)" in out, out
    assert f'run-install.bat" --update --modules movies-hd --manifest "{m}"' in out, \
        "the notice must give a command that can be pasted as-is, with the launcher's full path"
    assert "HD cinematics: up to date" not in out
    assert "see \"optional extras\" above" in bs._VERDICT[1]
    # The notice informs, it does not ask -- so --no-prompt (the bootstrap's own worker mode)
    # does not silence it. Gating it did: a player only ever heard about a pack on an idle run.
    capsys.readouterr()
    bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait", "--no-prompt"])
    assert "optional extras" in capsys.readouterr().out
    # Turned down -- "Don't ask me again" in game, or left unticked at install: neither the
    # notice nor the verdict mentions it (user 2026-11-01).
    import receipt as rc
    assert rc.decline(game, "new:movies-hd", rc.DECLINE_ANY)
    bs.run(["--game-dir", str(game), "--manifest", str(m), "--no-wait"])
    out = capsys.readouterr().out
    assert "optional extras" not in out and "available, not installed" not in out, out
    assert "optional extras" not in bs._VERDICT[1]
