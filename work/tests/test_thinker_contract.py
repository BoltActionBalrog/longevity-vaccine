"""The contract between the installer's Thinker update and the rest: the game DLL's constants and command line
(the runtime session's side, src/uimod), version.py's pin, and the release's compiled data. Each test pins one
fact both sides rely on, so neither can move alone."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import installer_exit as ix     # noqa: E402
import thinker_data as td       # noqa: E402
import thinker_flow as tf       # noqa: E402
import thinker_source as src    # noqa: E402
import thinker_state as st      # noqa: E402
import version as ver           # noqa: E402

_REPO = _SCRIPTS.parent.parent
_CORE = _REPO / "src" / "uimod" / "src" / "update_core.h"


def test_pin_matches_version_py():
    assert st.ts_display(td.PIN_VERSION) == ver.THINKER_SUPPORTED_VERSION
    assert td.PIN_TAG == ver.THINKER_SUPPORTED_TAG
    assert (td.PIN_DLL_STAMP, td.PIN_DLL_IMAGE_SIZE) == (ver.THINKER_SUPPORTED_STAMP, ver.THINKER_SUPPORTED_IMAGE_SIZE)
    assert bool(td.PIN_DROPBOX) == bool(ver.THINKER_DEV_PAGE)
    if td.PIN_DROPBOX:
        assert src.page_url(src.compiled_pin(td)) == ver.THINKER_DEV_PAGE


def test_release_page_prefix_matches_the_dll():
    text = _CORE.read_text(encoding="utf-8")
    m = re.search(r'kThinkerReleasePagePrefix\[\]\s*=\s*"([^"]+)"', text)
    assert m, "update_core.h no longer defines kThinkerReleasePagePrefix"
    assert m.group(1) == src.RELEASE_PAGE_PREFIX


def test_dll_scrub_list_is_a_subset_of_ours():
    """The game's spawn removes these six; the installer's own scrub list must cover at least the same."""
    for name in ("LONGEVITY_NO_WAIT", "LONGEVITY_WORKER", "LONGEVITY_PAYLOAD_ROOT", "LONGEVITY_GUARD_MARKER",
                 "LONGEVITY_INSTALL_LOCK", "LONGEVITY_PLAYER_NO_PROMPT"):
        assert name in tf.SCRUB_ENV and name in ix._RUN_SCOPED_ENV
    assert tf.CONSENT_ENV in tf.SCRUB_ENV and tf.CONSENT_ENV in ix._RUN_SCOPED_ENV


def test_install_py_accepts_the_dlls_fix_thinker_command_line(tmp_path):
    """The DLL launches run-install.bat --fix-thinker --game-dir X --wait-pid N [--manifest V]; run-install.bat sends
    it to install.py (no "--update" substring). It must reach the game-folder check, never argparse's refusal."""
    missing = tmp_path / "no such game"
    env = dict(os.environ, LONGEVITY_NO_WAIT="1")
    r = subprocess.run([sys.executable, str(_SCRIPTS / "install.py"), "--fix-thinker", "--game-dir", str(missing),
                        "--wait-pid", "1", "--manifest", str(tmp_path / "m.json")],
                       capture_output=True, text=True, env=env, cwd=str(_SCRIPTS), timeout=120)
    assert "did not understand its arguments" not in r.stdout, r.stdout[-800:]
    assert r.returncode == ix.EXIT_NO_GAME, (r.returncode, r.stdout[-800:])
    for a in ("--fix-thinker", "--game-dir", "--wait-pid", "--manifest"):
        assert "--update" not in a and "--no-wait" not in a


def test_journal_name_the_dll_reads():
    text = (_REPO / "src" / "uimod" / "src").glob("*.cpp")
    hits = [p for p in text if "thinker-journal.json" in p.read_text(encoding="utf-8", errors="replace")]
    assert hits, "the DLL no longer reads LongevityMods\\thinker-journal.json"
    import thinker_update as tu
    assert tu.JOURNAL.as_posix() == "LongevityMods/thinker-journal.json"


def test_dont_ask_key_matches_the_dll():
    text = "".join(p.read_text(encoding="utf-8", errors="replace")
                   for p in (_REPO / "src" / "uimod" / "src").glob("*.*") if p.suffix in (".cpp", ".h"))
    assert tf.DONT_ASK_KEY in text and tf.DONT_ASK_SECTION in text


def test_a_fresh_install_deploys_the_resident_updater_before_the_dll():
    """Round-5 finding J4: the game's "Update now" runs the resident installer copy; a new uimod.dll beside an old
    copy would hand it arguments it does not know. So _install places the resident copy first."""
    import inspect
    import install as inst
    body = inspect.getsource(inst._install_from_questions)       # _install's run from the first question on
    assert 0 <= body.index("_deploy_resident(game_dir)") < body.index("deploy_runtime(game_dir)")
    assert "bsmod.deploy(" not in inspect.getsource(inst._install_rest)


def test_a_failed_resident_deploy_is_returned_not_raised(tmp_path, monkeypatch):
    import bootstrap as bs
    import install as inst

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(bs, "reconcile", lambda *a, **k: None)
    monkeypatch.setattr(bs, "deploy", boom)
    monkeypatch.setattr(inst, "ver", ver)
    monkeypatch.setattr(inst, "payload_root", lambda: tmp_path)
    e = inst._deploy_resident(tmp_path)
    assert isinstance(e, OSError) and "disk full" in str(e)
