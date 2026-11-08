"""End-to-end: a real fresh install and a real manifest-driven update, in a throwaway game dir.

Everything else in this suite tests a module in isolation. This drives `install.py` as a
subprocess against a scratch directory, because the integration is where the interesting bugs
live -- a payload-root that resolves in a test but not from the CLI, a receipt nobody writes, a
preflight whose blockers never reach the user.

NOTHING here touches the real game install: every run passes an explicit --game-dir. (A test
run without one once deployed into the live install -- see
[[feedback-never-test-installer-on-live-game]].)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import sys
import zipfile
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent.parent
_SCRIPTS = _REPO / "work" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import apply_patches as ap    # noqa: E402
import receipt as rc          # noqa: E402
import sign_manifest as sm    # noqa: E402
import version as ver         # noqa: E402
import installer_exit as ix   # noqa: E402

_PY = _REPO / "tools" / "python" / "python.exe"
_INSTALL = _SCRIPTS / "install.py"
PATCHES = _REPO / "work" / "patches" / "patches.yaml"
SEED = bytes(range(32))
PK_HEX = sm.public_key(SEED).hex()

pytestmark = pytest.mark.skipif(not _PY.exists(), reason="bundled interpreter not present")


@pytest.fixture
def game(tmp_path, bak_path):
    """A scratch game dir with a clean PRACX base and no mod files."""
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    return g


@pytest.fixture(scope="module")
def _payload_root(tmp_path_factory) -> Path:
    """A payload shaped like the one a player gets, whose tools/python is the TRIMMED runtime.

    WHY THIS EXISTS: every install deploys a resident updater, and from a CHECKOUT the thing it
    copies as `tools/python` is the full 407 MB developer interpreter -- frida, numpy, PIL, pip --
    instead of the 18 MB runtime that actually ships. That is 425 MB of copying per install, ~8s
    of the ~9.4s a test install used to take, repeated across ~50 invocations in this file.
    A real install never pays it: the archive's tools/python IS the trimmed runtime.

    So the tests get the real shape. This is faster AND more faithful; the checkout-shaped deploy
    keeps its own coverage in test_bootstrap, which builds payload fixtures directly.
    """
    runtime = _REPO / "work" / "build" / "runtime"
    if not (runtime / "python.exe").is_file():
        pytest.skip("no staged runtime; run build_runtime.py first")
    if not (_REPO / "src" / "uimod" / "build" / "Release" / "uimod.dll").is_file():
        pytest.skip("no built uimod.dll; run src\\uimod\\build.bat Release first")
    if not any((_REPO / "src" / "uimod" / "third_party" / "ffmpeg" / "bin").glob("*.dll")):
        pytest.skip("no ffmpeg DLLs under src\\uimod\\third_party\\ffmpeg\\bin (README: building the DLL)")
    root = tmp_path_factory.mktemp("payload")
    (root / "scripts").mkdir()
    for f in (_SCRIPTS).glob("*.py"):
        shutil.copy2(f, root / "scripts" / f.name)
    shutil.copy2(_REPO / "work" / "run-install.bat", root / "scripts" / "run-install.bat")
    shutil.copytree(_REPO / "work" / "patches", root / "patches")
    shutil.copy2(_REPO / "work" / "CHANGELOG.md", root / "CHANGELOG.txt")
    shutil.copytree(runtime, root / "tools" / "python")
    dll = _REPO / "src" / "uimod" / "build" / "Release" / "uimod.dll"
    (root / "src" / "uimod" / "build" / "Release").mkdir(parents=True)
    shutil.copy2(dll, root / "src" / "uimod" / "build" / "Release" / "uimod.dll")
    shutil.copytree(_REPO / "src" / "uimod" / "third_party" / "ffmpeg" / "bin",
                    root / "src" / "uimod" / "third_party" / "ffmpeg" / "bin")
    (root / "art").mkdir()
    shutil.copy2(_REPO / "work" / "art" / "longevity_sm.pcx", root / "art" / "longevity_sm.pcx")
    return root


@pytest.fixture(scope="module")
def _installed_template(tmp_path_factory, bak_path, _payload_root):
    """ONE real install, kept as a template for tests that only need the resulting STATE.

    This file was 46% of the whole suite's runtime, and 28 of its 58 installer invocations were a
    throwaway `--ai off` run used purely as setup. A directory copy reproduces that state far more
    cheaply than re-running the installer.

    Used ONLY by tests whose setup install is the first statement in the body. A test that places
    a file (prax.dll) or removes one BEFORE installing depends on the install happening after that,
    so it keeps doing the real thing -- swapping those for a copy would make them assert a patch
    that never ran.

    Takes `_payload_root` EXPLICITLY: a module-scoped fixture is built before the function-scoped
    autouse `_use_trimmed_payload` has set `_PAYLOAD`, so relying on it installed from the
    checkout -- a 447 MB template (the full developer interpreter as the resident updater) that
    every `game_installed` test then copied (~6s) and `_tree`-hashed (~70s per call).
    """
    g = tmp_path_factory.mktemp("installed") / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    rcode, out = _run("--ai", "off", game=g,
                      env_extra={"LONGEVITY_PAYLOAD_ROOT": str(_payload_root)})
    assert "INSTALLATION SUCCESSFUL" in out, out
    # `--ai off` turns the HD Cinematics down exactly as the game's "Don't ask me again" does
    # (user 2026-11-01). The template stands for an install that decided nothing about packs, so
    # the tests built on it (new-pack offers, the extras notice) start without that decline.
    assert rc.declined(g) == {"new:movies-hd": rc.DECLINE_ANY}, rc.declined(g)
    assert rc.clear_declines(g)
    size = sum(p.stat().st_size for p in g.rglob("*") if p.is_file())
    assert size < 150 << 20, f"installed template is {size >> 20} MB: not the trimmed payload"
    return g


@pytest.fixture
def game_installed(tmp_path, _installed_template):
    """A private copy of the installed template, so no test can affect another."""
    g = tmp_path / "game"
    shutil.copytree(_installed_template, g)
    return g


#: Set by the autouse fixture below so every _run() in this module uses the trimmed payload.
_PAYLOAD: Path = None


@pytest.fixture(autouse=True)
def _use_trimmed_payload(_payload_root):
    """Point every installer run in this file at the real-shaped payload."""
    global _PAYLOAD
    _PAYLOAD = _payload_root
    yield
    _PAYLOAD = None


def _run(*args, game=None, env_extra=None, expect_ok=True, timeout=900):
    env = dict(os.environ)
    env["LONGEVITY_NO_WAIT"] = "1"
    if _PAYLOAD is not None:
        env["LONGEVITY_PAYLOAD_ROOT"] = str(_PAYLOAD)
    env.update(env_extra or {})
    # stdin=DEVNULL, always. `--ai ask` reaches input(); with fd 0 inherited from an interactive
    # terminal the child blocks on the console until the 900 s timeout, so the suite's behaviour
    # depended on how it was launched.
    p = subprocess.run([str(_PY), str(_INSTALL), "--no-wait", "--game-dir", str(game), *args],
                       capture_output=True, text=True, env=env, timeout=timeout,
                       stdin=subprocess.DEVNULL)
    out = p.stdout + p.stderr
    if expect_ok:
        assert p.returncode == 0, f"expected success, got {p.returncode}:\n{out}"
    return p.returncode, out


# ---------------------------------------------------------------- fresh install

def test_a_fresh_install_patches_and_records(game):
    rcode, out = _run("--ai", "off", game=game)
    assert "INSTALLATION SUCCESSFUL" in out, out

    exe = game / "terranx_PRACX.exe"
    table = ap.load_targets(PATCHES)
    assert hashlib.md5(exe.read_bytes()).hexdigest() == table["pracx"].patched_md5
    assert (game / "terranx_PRACX.exe.bak").is_file(), "the clean base must be backed up"
    assert hashlib.md5((game / "terranx_PRACX.exe.bak").read_bytes()).hexdigest() \
        == table["pracx"].base_md5

    assert (game / "uimod.dll").is_file()
    assert (game / "longevity_sm.pcx").is_file(), "the update prompt's picture ships beside the exe"
    assert len(list(game.glob("av*.dll"))) >= 2

    state = rc.read(game)
    assert state["target_id"] == "pracx"
    assert rc.module_version(state, "base") == ver.VERSION
    assert (game / rc.JSON_NAME).is_file()
    assert rc.ini_get(game, rc.KEY_TARGET) == "pracx"


def test_a_fresh_install_patches_the_datalinks_text_and_uninstall_restores_it(game):
    """helpx.txt / conceptsx.txt (and Thinker's smac_mod copies) get the mod's Datalinks text; --uninstall puts the
    originals back. Synthetic files with the stock blocks stand in for the game's (test_patch_helptext owns the
    real-file checks); a file that is not the stock text is left alone without failing the install."""
    sys.path.insert(0, str(_SCRIPTS))
    import patch_helptext as ph
    from test_patch_helptext import _synthetic
    (game / "smac_mod").mkdir()
    pristine = {}
    for d in (game, game / "smac_mod"):
        for name, spec in ph.FILES.items():
            data = _synthetic(spec, b"\r\n")
            (d / name).write_bytes(data)
            pristine[d / name] = data
    foreign = b"; a translation\r\n#ABILDESC2\r\nother words\r\n"
    (game / "smac_mod" / "helpx.txt").write_bytes(foreign)
    rcode, out = _run("--ai", "off", game=game)
    assert "INSTALLATION SUCCESSFUL" in out, out
    assert "--- Datalinks text ---" in out and "Datalinks text" in out.split("--- summary ---", 1)[1], out
    for p, data in pristine.items():
        if p == game / "smac_mod" / "helpx.txt":
            assert p.read_bytes() == foreign, "a foreign file was touched"
            assert not ph.backup_of(p).exists()
            continue
        spec = ph.FILES[p.name]
        assert p.read_bytes() == ph.patch_bytes(data, spec), f"{p} not patched"
        assert ph.backup_of(p).read_bytes() == data, f"{p}: backup is not the original"
    assert "left alone" in out, "the foreign file must be reported"
    summary = out.split("--- summary ---", 1)[1]
    assert "left alone: not the stock text" in summary, "a file left alone is named under the summary row"

    # The hard case (audit 2026-10-30): the player already restored the exe by hand and deleted uimod.dll, so the
    # exe/DLL pass finds nothing -- the text must still go back instead of a "nothing to uninstall" refusal.
    shutil.copy2(game / "terranx_PRACX.exe.bak", game / "terranx_PRACX.exe")
    (game / "uimod.dll").unlink()
    rcode, out = _run("--uninstall", game=game)
    assert "UNINSTALL COMPLETE" in out, out
    assert "Datalinks text file(s)" in out, out
    for p, data in pristine.items():
        expected = foreign if p == game / "smac_mod" / "helpx.txt" else data
        assert p.read_bytes() == expected, f"{p} not restored"
    assert not list(game.rglob("*.longevity.bak"))


def test_a_fresh_install_leaves_a_resident_updater(game):
    """The in-game prompt needs something to spawn. Before this, install.py deployed only
    uimod.dll and the ffmpeg DLLs, so once the player deleted their download there was no
    installer on disk at all."""
    import bootstrap as bs
    _run("--ai", "off", game=game)
    d = bs.updater_dir(game)
    assert d.is_dir(), "no resident updater was deployed"
    # Assert against the module's own contract rather than a hand-written path list. A literal
    # list here has already gone stale once, asserting a layout production had moved away from
    # while staying green.
    assert bs.missing_parts(d) == [], f"resident updater is incomplete: {bs.missing_parts(d)}"
    assert bs.is_usable(d)
    # The launcher must be able to find its own interpreter by its own relative path.
    assert (d / "tools" / "python" / "python.exe").is_file()
    assert bs.resident_version(game) == ver.VERSION
    assert not list(bs.mods_root(game).glob("*.staging")), "staging debris left behind"


def test_repair_redeploys_the_updater_without_patching(game):
    import bootstrap as bs
    _run("--ai", "off", game=game)
    exe_before = (game / "terranx_PRACX.exe").read_bytes()
    shutil.rmtree(bs.updater_dir(game))
    assert bs.resident_version(game) == ver.UNKNOWN

    rcode, out = _run("--repair", game=game)
    assert "repair" in out.lower()
    assert bs.resident_version(game) == ver.VERSION
    assert (game / "terranx_PRACX.exe").read_bytes() == exe_before, \
        "--repair patched the game"


def test_repair_recovers_a_half_swapped_updater(game):
    """The state a crash mid-swap leaves: no `updater`, only `updater.old`."""
    import bootstrap as bs
    _run("--ai", "off", game=game)
    root = bs.mods_root(game)
    bs.updater_dir(game).replace(root / bs.OLD_DIR)
    assert not bs.updater_dir(game).exists()
    _run("--repair", game=game)
    assert bs.resident_version(game) == ver.VERSION
    assert not (root / bs.OLD_DIR).exists()


def test_a_second_run_is_idempotent(game_installed):
    game = game_installed
    exe_after_first = (game / "terranx_PRACX.exe").read_bytes()
    bak_after_first = (game / "terranx_PRACX.exe.bak").read_bytes()
    rcode, out = _run("--ai", "off", game=game)
    assert "already patched" in out
    assert (game / "terranx_PRACX.exe").read_bytes() == exe_after_first
    assert (game / "terranx_PRACX.exe.bak").read_bytes() == bak_after_first, \
        "the backup must never be rewritten"


def _uimod_flag(game: Path) -> str:
    """Read [UIMod] UpscaledVideos. rc.ini_get reads [Longevity], which is a DIFFERENT section --
    using it here made the original version of this test read '' no matter what the file said."""
    import configparser
    cp = configparser.ConfigParser(strict=False)
    cp.read(game / "Alpha Centauri.ini", encoding="mbcs")
    return cp.get("UIMod", "UpscaledVideos", fallback="")


def test_an_unattended_rerun_does_not_reverse_the_players_choice(game_installed):
    """set_ini_flag runs on every invocation, so an update that fell back to a hardcoded default
    silently flipped a setting the player had chosen.

    The original version of this test was vacuous three ways: a trailing `or True`, a read of the
    wrong ini section, and no assertion at all on the second run.
    """
    game = game_installed
    assert _uimod_flag(game) == "0", "explicit --ai off should record 0"

    _run("--ai", "ask", game=game)          # unattended: EOF on the prompt
    assert _uimod_flag(game) == "0", "an unattended re-run reversed an explicit opt-out"


def test_an_unattended_first_install_leaves_update_checks_at_the_default_and_says_so(game):
    """The update-check question (user 2026-11-06) needs a keyboard: the e2e runs have none (stdin is
    DEVNULL), so the line says the default stands and the key is NOT written -- the installer never
    writes a default, only an answer. A re-run says "the default" again and still writes nothing."""
    import configparser
    rcode, out = _run("--ai", "off", game=game)
    assert "INSTALLATION SUCCESSFUL" in out, out
    assert ("--- automatic updates ---\n  The game checks for updates when it starts (the default); change it in "
            "Longevity Mod Preferences (\"Check for Updates at Startup\").") in out, out
    assert "Check for updates when the game starts?" not in out
    cp = configparser.ConfigParser(strict=False)
    cp.read(game / "Alpha Centauri.ini", encoding="mbcs")
    assert not cp.has_option("UIMod", "CheckForUpdates")
    rcode, out = _run("--ai", "off", "--no-prompt", game=game)
    assert "checks for updates when it starts (the default)" in out, out
    cp.read(game / "Alpha Centauri.ini", encoding="mbcs")
    assert not cp.has_option("UIMod", "CheckForUpdates")
    # the player's own setting from the game is respected and reported on the next run
    (game / "Alpha Centauri.ini").write_text((game / "Alpha Centauri.ini").read_text(encoding="mbcs")
                                             .replace("[UIMod]", "[UIMod]\nCheckForUpdates=0", 1), encoding="mbcs")
    rcode, out = _run("--ai", "off", game=game)
    assert "The game does not check for updates when it starts (as before)" in out, out


def test_a_first_install_defaults_the_cinematics_on(game):
    """GetPrivateProfileInt cannot tell "no key" from "key = 0", so a first install under
    --no-wait used to answer the EOF prompt with 0 and silently skip the headline feature."""
    assert _uimod_flag(game) == "", "fixture should start with no key"
    _run("--ai", "ask", "--pack", str(game / "no-such-pack"), game=game)
    assert _uimod_flag(game) == "1", "a first install should default to installing them"


# ---------------------------------------------------------------- update

def _publish(tmp_path: Path, game: Path, *, latest: str, modules: dict,
             versions: dict = None) -> Path:
    """Write a signed manifest (and the module archives it points at) to a local directory.

    `versions` overrides a module's version (default: `latest`) -- a module's release is
    independent of the product's, and that independence is what several tests exercise.
    """
    pub = tmp_path / "published"
    pub.mkdir(parents=True, exist_ok=True)
    mods = {}
    for name, files in modules.items():
        mver = (versions or {}).get(name, latest)
        archive = pub / f"{name}-{mver}.zip"
        with zipfile.ZipFile(archive, "w") as z:
            for arcname, data in files.items():
                z.writestr(arcname, data)
        mods[name] = {
            "version": mver, "required": name == "base",
            "url": archive.as_uri(),
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "size": archive.stat().st_size,
        }
    doc = {
        "schema": 1, "protocol": 1, "product": "longevity-vaccine",
        "latest": latest, "min_upgradable_from": "0.0.0",
        "manual_install_required": False, "manual_install_reason": None,
        "unsupported_versions": [], "unsupported_targets": [], "yanked": [],
        "min_free_bytes": 1 << 20, "modules": mods,
    }
    m = pub / "manifest.json"
    m.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    sm.sign_file(SEED, m)
    return m


def test_an_update_preflights_then_commits(game_installed, tmp_path):
    game = game_installed
    exe_before = (game / "terranx_PRACX.exe").read_bytes()
    bak_before = (game / "terranx_PRACX.exe.bak").read_bytes()

    m = _publish(tmp_path, game, latest="9.9.9", modules={
        "movies-hd": {"movies/hd/opening.mp4": b"fake clip data"},
    })
    rcode, out = _run("--update", "--manifest", str(m), "--modules", "movies-hd",
                      "--no-prompt", game=game, env_extra={"LONGEVITY_TRUST_KEY": PK_HEX})
    assert "preflight" in out and "commit" in out, out
    assert "UPDATE COMPLETE" in out, out          # an update's verdict, not a first install's

    table = ap.load_targets(PATCHES)
    assert hashlib.md5((game / "terranx_PRACX.exe").read_bytes()).hexdigest() \
        == table["pracx"].patched_md5
    assert (game / "terranx_PRACX.exe.bak").read_bytes() == bak_before, \
        "the update path must never write to .bak"
    assert (game / "movies" / "hd" / "opening.mp4").read_bytes() == b"fake clip data"
    state = rc.read(game)
    assert rc.module_version(state, "movies-hd") == "9.9.9"


def test_an_update_skips_files_that_are_already_current(game_installed, tmp_path):
    """The whole point of hash-skip: not recopying 1.3 GB because one module changed."""
    game = game_installed
    m = _publish(tmp_path, game, latest="9.9.9", modules={
        "movies-hd": {"movies/hd/a.mp4": b"aaa", "movies/hd/b.mp4": b"bbb"},
    })
    env = {"LONGEVITY_TRUST_KEY": PK_HEX}
    _run("--update", "--manifest", str(m), "--modules", "movies-hd", "--no-prompt",
         game=game, env_extra=env)
    _, out = _run("--update", "--manifest", str(m), "--modules", "movies-hd", "--no-prompt",
                  game=game, env_extra=env)
    assert "2 already current" in out, out


def _tree(root: Path) -> dict:
    """RECURSIVE digest of the whole game dir. The original comparison was top-level files only,
    so it missed the pre-preflight writes into LongevityMods\\staging that actually happened."""
    return {str(p.relative_to(root)): hashlib.md5(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_zip_slip_member_cannot_escape_the_game_directory(game_installed, tmp_path):
    """zipfile.extract() sanitises member names; z.open() plus a manual join does not. A `..`
    member escapes, and an ABSOLUTE member discards the game dir entirely -- so a member could
    land on another drive, or overwrite the exe we just committed."""
    game = game_installed
    outside = tmp_path / "OUTSIDE"
    exe_before = (game / "terranx_PRACX.exe").read_bytes()
    dll_before = (game / "uimod.dll").read_bytes()
    bak_before = (game / "terranx_PRACX.exe.bak").read_bytes()
    escape = str((tmp_path / "abs_evil.txt")).replace("\\", "/")
    m = _publish(tmp_path, game, latest="9.9.9", modules={
        "movies-hd": {
            "../../OUTSIDE/evil.txt": b"PWNED",
            "../escaped.txt": b"PWNED",
            escape: b"PWNED",
            # Contained, but nowhere movies-hd may write. Each of these is a file the commit
            # phase just verified or depends on.
            "terranx_PRACX.exe": b"PWNED",
            "terranx_PRACX.exe.bak": b"PWNED",
            "uimod.dll": b"PWNED",
            "Alpha Centauri.ini": b"PWNED",
            "movies/hd/legit.mp4": b"ok",
        }})
    _run("--update", "--manifest", str(m), "--modules", "movies-hd", "--no-prompt",
         game=game, env_extra={"LONGEVITY_TRUST_KEY": PK_HEX}, expect_ok=False)

    assert not outside.exists(), "a `..` member escaped the game directory"
    assert not (game.parent / "escaped.txt").exists()
    assert not (tmp_path / "abs_evil.txt").exists(), "an absolute member escaped"
    assert (game / "terranx_PRACX.exe").read_bytes() == exe_before, \
        "an archive member overwrote the committed exe"
    assert (game / "terranx_PRACX.exe.bak").read_bytes() == bak_before, \
        "an archive member overwrote the clean backup"
    assert (game / "uimod.dll").read_bytes() == dll_before
    assert "PWNED" not in (game / "Alpha Centauri.ini").read_text(encoding="mbcs")
    # No debris: the refused members must not leave temp files behind either.
    assert not list(game.rglob("*.tmp-*")), "temp files left behind"


def test_a_tampered_manifest_blocks_the_update_and_changes_nothing(game_installed, tmp_path):
    game = game_installed
    before = _tree(game)

    m = _publish(tmp_path, game, latest="9.9.9", modules={})
    data = m.read_bytes().replace(b"9.9.9", b"9.9.8")
    m.write_bytes(data)          # signature no longer matches

    rcode, out = _run("--update", "--manifest", str(m), "--no-prompt", game=game,
                      env_extra={"LONGEVITY_TRUST_KEY": PK_HEX}, expect_ok=False)
    assert rcode != 0
    assert "signature" in out.lower()
    assert "Nothing on disk was changed" in out
    after = _tree(game)
    assert after == before, (
        "a refused update modified the install: "
        f"added={sorted(set(after) - set(before))} "
        f"changed={sorted(k for k in set(after) & set(before) if after[k] != before[k])}")


def test_a_manifest_signed_by_an_untrusted_key_refuses(game_installed, tmp_path):
    """The real-world property, now that a release key is compiled in.

    This test used to assert the "no signing key is provisioned" message, which was reachable
    only while PUBLIC_KEY_HEX was empty. Generating the release key made that branch unreachable
    from here -- and a test whose premise has silently expired is worse than no test, so it now
    asserts what actually protects players: a manifest signed by a key this build does not trust
    is refused, and nothing on disk moves. The empty-anchor branch keeps its own coverage in
    test_manifest.py.

    Note the deliberate absence of LONGEVITY_TRUST_KEY: every other update test supplies it, so
    without this case the suite would never once exercise a genuine signature rejection.
    """
    game = game_installed
    before = _tree(game)
    m = _publish(tmp_path, game, latest="9.9.9", modules={})   # signed with the TEST seed
    rcode, out = _run("--update", "--manifest", str(m), "--no-prompt", game=game,
                      expect_ok=False)
    assert rcode != 0
    assert "signature" in out.lower(), out
    assert "INSTALLER ERROR" not in out, "a rejected signature is a refusal, not a crash"
    assert _tree(game) == before, "a refused update modified the install"


def test_a_kill_switched_manifest_shows_the_compiled_url(game_installed, tmp_path):
    game = game_installed
    pub = tmp_path / "published"
    pub.mkdir(exist_ok=True)
    doc = {
        "schema": 1, "protocol": 1, "product": "longevity-vaccine", "latest": "9.9.9",
        "min_upgradable_from": "0.0.0", "manual_install_required": True,
        "manual_install_reason": "bootstrap_defect",
        "download_url": "http://evil.example/pwn",       # must be ignored
        "unsupported_versions": [], "unsupported_targets": [], "yanked": [], "modules": {},
    }
    m = pub / "manifest.json"
    m.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    sm.sign_file(SEED, m)
    rcode, out = _run("--update", "--manifest", str(m), "--no-prompt", game=game,
                      env_extra={"LONGEVITY_TRUST_KEY": PK_HEX}, expect_ok=False)
    assert rcode != 0
    assert "longevitymods.com" in out, "the compiled-in URL must be what is shown"
    assert "evil.example" not in out, "a manifest-supplied URL must never be displayed"


def test_offline_without_a_staged_manifest_refuses(game_installed):
    game = game_installed
    rcode, out = _run("--update", "--offline", "--no-prompt", game=game, expect_ok=False)
    assert rcode != 0
    assert "offline" in out.lower()


# ---------------------------------------------------------------- uninstall

def test_uninstall_restores_the_original_and_removes_the_mod(game_installed):
    game = game_installed
    clean = (game / "terranx_PRACX.exe.bak").read_bytes()
    rcode, out = _run("--uninstall", game=game)
    assert "restored" in out
    assert (game / "terranx_PRACX.exe").read_bytes() == clean
    assert not (game / "uimod.dll").exists()
    assert not (game / "longevity_sm.pcx").exists()
    assert not (game / rc.JSON_NAME).exists()
    assert rc.ini_get(game, rc.KEY_TARGET) == ""


def _run_found(*args, candidates, installs, expect_ok=True, timeout=900):
    """An installer run WITHOUT --game-dir: it finds the folder itself, from `candidates` (the
    only folders it may see -- never the real game) and the remembered installs in `installs`."""
    env = dict(os.environ, LONGEVITY_NO_WAIT="1", LONGEVITY_PAYLOAD_ROOT=str(_PAYLOAD),
               LONGEVITY_GAME_CANDIDATES="|".join(str(c) for c in candidates),
               LONGEVITY_INSTALLS_FILE=str(installs))
    p = subprocess.run([str(_PY), str(_INSTALL), "--no-wait", *args], capture_output=True,
                       text=True, env=env, timeout=timeout, stdin=subprocess.DEVNULL)
    out = p.stdout + p.stderr
    if expect_ok:
        assert p.returncode == 0, f"expected success, got {p.returncode}:\n{out}"
    return p.returncode, out


def test_an_install_without_game_dir_finds_the_folder_and_uninstall_remembers_it(game, tmp_path):
    """No --game-dir anywhere: the install takes the one good folder it was shown (skipping an
    empty one), remembers it, and a later --uninstall that is shown NO folders still finds it."""
    installs = tmp_path / "installs.txt"
    empty = tmp_path / "empty"
    empty.mkdir()
    rcode, out = _run_found("--ai", "off", candidates=[empty, game], installs=installs)
    assert "INSTALLATION SUCCESSFUL" in out and f"Game dir: {game}" in out, out
    assert (game / "terranx_PRACX.exe.bak").is_file()
    assert installs.read_text(encoding="utf-8").splitlines() == [str(game.resolve())]
    # an uninstall that cannot finish (the DLL in use) keeps the folder remembered, so the
    # "run --uninstall again" it asks for finds it
    with open(game / "uimod.dll", "rb"):
        rcode, out = _run_found("--uninstall", candidates=[], installs=installs, expect_ok=False)
    assert "UNINSTALL INCOMPLETE" in out, out
    assert installs.read_text(encoding="utf-8").splitlines() == [str(game.resolve())]
    rcode, out = _run_found("--uninstall", candidates=[], installs=installs)
    assert "UNINSTALL COMPLETE" in out and f"Game dir: {game.resolve()}" in out, out
    assert not (game / "uimod.dll").exists()
    assert installs.read_text(encoding="utf-8").strip() == ""


def test_with_no_game_folder_found_an_unattended_run_explains_and_changes_nothing(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    rcode, out = _run_found("--ai", "off", candidates=[empty], installs=tmp_path / "i.txt",
                            expect_ok=False)
    assert rcode == ix.EXIT_NO_GAME, out
    assert "No folder the installer found can be used" in out and "double-clicking INSTALL.bat" in out
    assert f"Found {empty}, but Alpha Centauri is not in that folder" in out, out
    assert "Nothing on disk was changed" in out
    assert "SMACX_GAME_DIR" not in out and "GOG Galaxy" not in out and "SmacxUi" not in out, out
    assert list(empty.iterdir()) == [] and not (tmp_path / "i.txt").exists()


def test_uninstall_with_nothing_installed_is_an_explained_refusal(game):
    rcode, out = _run("--uninstall", game=game, expect_ok=False)
    assert rcode != 0
    assert "Nothing to uninstall" in out
    assert "Nothing on disk was changed" in out


def test_uninstall_and_update_together_are_rejected(game):
    rcode, out = _run("--uninstall", "--update", game=game, expect_ok=False)
    assert rcode != 0
    assert "cannot be combined" in out


def test_uninstall_says_what_it_leaves_behind_and_refuses_a_second_run(game_installed):
    """A successful uninstall used to print "INSTALLATION SUCCESSFUL" -- the exact opposite of
    what had just happened -- and said nothing about the LongevityMods folder it leaves on disk,
    which reads as a failed uninstall the next time the player looks."""
    game = game_installed
    rcode, out = _run("--uninstall", game=game)
    assert "UNINSTALL COMPLETE" in out, out
    assert "INSTALLATION SUCCESSFUL" not in out
    assert "LongevityMods" in out, "the folder left behind is never mentioned"
    assert "movies" in out

    rcode, out = _run("--uninstall", game=game, expect_ok=False)
    assert rcode != 0, "a second uninstall reported success with nothing to do"
    assert "Nothing to uninstall" in out


def test_uninstall_restores_the_companion_too(game, prax_bak_path):
    """Leaving a patched prax.dll behind is not an uninstall."""
    clean = prax_bak_path.read_bytes()
    shutil.copy2(prax_bak_path, game / "prax.dll")
    _run("--ai", "off", game=game)
    assert (game / "prax.dll").read_bytes() != clean, "fixture precondition: it should be patched"
    _run("--uninstall", game=game)
    assert (game / "prax.dll").read_bytes() == clean, "the companion was left patched"


def test_uninstall_will_not_restore_a_backup_it_did_not_make(game):
    """`--uninstall` used to copy ANY `<exe>.bak` it found over the live file and count it as a
    successful restore of ours -- including another mod's backup."""
    (game / "terranx_PRACX.exe").write_bytes(b"SOMEONE ELSE'S PATCHED EXE")
    (game / "terranx_PRACX.exe.bak").write_bytes(b"SOMEONE ELSE'S ORIGINAL")
    rcode, out = _run("--uninstall", game=game, expect_ok=False)
    assert rcode != 0, out
    assert (game / "terranx_PRACX.exe").read_bytes() == b"SOMEONE ELSE'S PATCHED EXE", \
        "a foreign backup was restored over a foreign executable"
    assert "not a backup this installer made" in out, out


def test_uninstall_with_only_a_corrupt_receipt_is_still_a_refusal(game):
    """receipt.read reports source='corrupt-json', which is not 'none' -- so a refusal gated on
    that string let an uninstall with nothing to do report UNINSTALL COMPLETE."""
    (game / rc.JSON_NAME).write_text("{ this is not json", encoding="utf-8")
    rcode, out = _run("--uninstall", game=game, expect_ok=False)
    assert rcode != 0, out
    assert "Nothing to uninstall" in out
    assert "UNINSTALL COMPLETE" not in out
    assert not (game / rc.JSON_NAME).exists(), "the stray record should still be cleared"


def test_two_modes_at_once_are_rejected(game):
    for a, b in (("--uninstall", "--repair"), ("--repair", "--update"),
                 ("--uninstall", "--update")):
        rcode, out = _run(a, b, game=game, expect_ok=False)
        assert rcode != 0, f"{a} {b} was accepted"
        assert "cannot be combined" in out, out


def test_repair_does_not_claim_an_installation(game_installed):
    game = game_installed
    rcode, out = _run("--repair", game=game)
    assert "REPAIR COMPLETE" in out, out
    assert "INSTALLATION SUCCESSFUL" not in out


# ---------------------------------------------------------------- companions

def test_a_fresh_install_patches_the_prax_companion(game, prax_bak_path):
    """patches_prax.yaml (the PRACX edge-scroll console fix) shipped in the payload and was never
    applied on a fresh install: only the --update path looked at `companion:`. And because the exe
    was already-patched afterwards, nothing brought it up to date later either."""
    table = ap.load_targets(PATCHES)
    cinfo = table["pracx"].companion["prax.dll"]
    shutil.copy2(prax_bak_path, game / "prax.dll")

    _run("--ai", "off", game=game)
    assert hashlib.md5((game / "prax.dll").read_bytes()).hexdigest() == cinfo["patched_md5"], \
        "prax.dll was not patched by a fresh install"
    assert (game / "prax.dll.bak").is_file(), "no clean backup of the companion"
    assert hashlib.md5((game / "prax.dll.bak").read_bytes()).hexdigest() == cinfo["base_md5"]


def test_a_second_run_leaves_the_companion_alone(game, prax_bak_path):
    shutil.copy2(prax_bak_path, game / "prax.dll")
    _run("--ai", "off", game=game)
    after_first = (game / "prax.dll").read_bytes()
    bak_first = (game / "prax.dll.bak").read_bytes()
    _run("--ai", "off", game=game)
    assert (game / "prax.dll").read_bytes() == after_first
    assert (game / "prax.dll.bak").read_bytes() == bak_first, \
        "the companion's backup must never be rewritten"


def test_a_foreign_companion_is_left_alone_and_does_not_fail_the_install(game):
    """A different PRACX build is not a reason to refuse an install that otherwise works."""
    junk = b"not PRACX at all" * 100
    (game / "prax.dll").write_bytes(junk)
    rcode, out = _run("--ai", "off", game=game)
    assert rcode == 0, out
    assert "leaving it alone" in out, out
    assert (game / "prax.dll").read_bytes() == junk
    assert not (game / "prax.dll.bak").exists(), "a foreign file must not be backed up as clean"


def test_the_update_path_patches_a_clean_companion(game, prax_bak_path, tmp_path):
    """The companion's base_size used to be read off the LIVE file, so the size check compared
    the clean .bak against the patched file's length."""
    table = ap.load_targets(PATCHES)
    cinfo = table["pracx"].companion["prax.dll"]
    _run("--ai", "off", game=game)
    # A CLEAN companion put in place after the install, so the update has work to do.
    shutil.copy2(prax_bak_path, game / "prax.dll")
    m = _publish(tmp_path, game, latest="9.9.9", modules={
        "movies-hd": {"movies/hd/a.mp4": b"aaa"}})
    _run("--update", "--manifest", str(m), "--modules", "movies-hd", "--no-prompt",
         game=game, env_extra={"LONGEVITY_TRUST_KEY": PK_HEX})
    assert hashlib.md5((game / "prax.dll").read_bytes()).hexdigest() == cinfo["patched_md5"]


# ---------------------------------------------------------------- odds and ends

def test_two_updates_in_a_row_both_work(game_installed, tmp_path):
    """The second exercises the path where the live files are already patched, which is where a
    missing game-dir .bak used to make every later update fail permanently."""
    game = game_installed
    env = {"LONGEVITY_TRUST_KEY": PK_HEX}
    m1 = _publish(tmp_path, game, latest="9.9.9",
                  modules={"movies-hd": {"movies/hd/a.mp4": b"aaa"}})
    _run("--update", "--manifest", str(m1), "--modules", "movies-hd", "--no-prompt",
         game=game, env_extra=env)
    pub2 = tmp_path / "second"
    pub2.mkdir()
    m2 = _publish(pub2, game, latest="9.9.10",
                  modules={"movies-hd": {"movies/hd/a.mp4": b"aaa", "movies/hd/b.mp4": b"bbb"}})
    rcode, out = _run("--update", "--manifest", str(m2), "--modules", "movies-hd",
                      "--no-prompt", game=game, env_extra=env)
    assert rcode == 0, out
    assert (game / "movies" / "hd" / "b.mp4").read_bytes() == b"bbb"
    assert rc.module_version(rc.read(game), "movies-hd") == "9.9.10"


def test_a_relative_game_dir_does_not_write_to_the_windows_directory(game):
    """The Win32 profile API resolves a relative path against %WINDIR%, so `--game-dir .` used to
    send every [Longevity] read and write to the Windows directory."""
    env = dict(os.environ)
    env["LONGEVITY_NO_WAIT"] = "1"
    p = subprocess.run([str(_PY), str(_INSTALL), "--no-wait", "--ai", "off", "--game-dir", "."],
                       cwd=str(game), capture_output=True, text=True, env=env, timeout=900)
    assert p.returncode == 0, p.stdout + p.stderr
    assert rc.ini_get(game, rc.KEY_TARGET) == "pracx", "the receipt did not land in the game dir"
    assert "[Longevity]" in (game / "Alpha Centauri.ini").read_text(encoding="mbcs")


def test_a_non_ascii_signature_does_not_crash_and_does_not_persist(game_installed, tmp_path):
    """An unreadable .sig used to escape into the crash handler -- and because the bad pair stayed
    cached in staging, every later --offline run crashed the same way, permanently."""
    game = game_installed
    m = _publish(tmp_path, game, latest="9.9.9",
                 modules={"movies-hd": {"movies/hd/a.mp4": b"aaa"}})
    Path(str(m) + ".sig").write_bytes(b"\xff\xfe not ascii at all")
    rcode, out = _run("--update", "--manifest", str(m), "--no-prompt", game=game,
                      env_extra={"LONGEVITY_TRUST_KEY": PK_HEX}, expect_ok=False)
    assert rcode != 0
    assert "INSTALLER ERROR" not in out, "an unreadable signature was reported as a crash"
    assert "Nothing on disk was changed" in out
    staging = game / "LongevityMods" / "staging"
    assert not (staging / "manifest.json").exists(), "an unverified manifest was left on disk"


def test_a_manifest_path_that_is_a_folder_is_explained(game_installed, tmp_path):
    game = game_installed
    rcode, out = _run("--update", "--manifest", str(tmp_path), "--no-prompt", game=game,
                      expect_ok=False)
    assert rcode != 0
    assert "folder" in out and "manifest.json" in out, out
    assert "schemeless" not in out, "the old message named neither the problem nor the fix"


def test_a_manifest_path_that_does_not_exist_is_explained(game_installed, tmp_path):
    game = game_installed
    rcode, out = _run("--update", "--manifest", str(tmp_path / "nope.json"), "--no-prompt",
                      game=game, expect_ok=False)
    assert rcode != 0
    assert "no update manifest at" in out.lower(), out


def test_an_update_run_from_the_resident_updater_works(game, tmp_path):
    """The configuration players actually use: the game spawns the resident copy, which has no
    game-exe.txt, so config.exe_name() falls back to terranx.exe -- a file that exists on every
    stock install and made the in-game update button dead."""
    import bootstrap as bs
    _run("--ai", "off", game=game)
    resident = bs.updater_dir(game) / "scripts" / "install.py"
    assert resident.is_file()
    m = _publish(tmp_path, game, latest="9.9.9",
                 modules={"movies-hd": {"movies/hd/a.mp4": b"aaa"}})
    env = dict(os.environ)
    env["LONGEVITY_NO_WAIT"] = "1"
    env["LONGEVITY_TRUST_KEY"] = PK_HEX
    py = bs.updater_dir(game) / "tools" / "python" / "python.exe"
    p = subprocess.run([str(py), str(resident), "--no-wait", "--game-dir", str(game),
                        "--update", "--manifest", str(m), "--modules", "movies-hd",
                        "--no-prompt"],
                       capture_output=True, text=True, env=env, timeout=900)
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    assert (game / "movies" / "hd" / "a.mp4").read_bytes() == b"aaa"


# ---------------------------------------------------------------- independent module updates
#
# `latest=ver.VERSION` keeps the BASE current (a fresh install records version.py's VERSION), so
# what these runs do is decided by the pack versions alone.

_ENV = {"LONGEVITY_TRUST_KEY": PK_HEX}


def _with_pack(tmp_path, game, pack_version: str, files: dict) -> Path:
    """Install movies-hd at `pack_version` via the explicit path; returns the manifest."""
    m = _publish(tmp_path / f"pub-{pack_version}", game, latest=ver.VERSION,
                 modules={"movies-hd": files}, versions={"movies-hd": pack_version})
    _run("--update", "--manifest", str(m), "--modules", "movies-hd", "--no-prompt",
         game=game, env_extra=_ENV)
    assert rc.module_version(rc.read(game), "movies-hd") == pack_version
    return m


def test_a_pack_release_updates_the_pack_with_no_flags(game_installed, tmp_path):
    """The defect: a module-only release used to be invisible, because only the base version
    was compared and `--update` said "already up to date"."""
    game = game_installed
    _with_pack(tmp_path, game, "1.0.0", {"movies/hd/a.mp4": b"v1"})
    m2 = _publish(tmp_path / "pub-1.1.0", game, latest=ver.VERSION,
                  modules={"movies-hd": {"movies/hd/a.mp4": b"v2", "movies/hd/b.mp4": b"new"}},
                  versions={"movies-hd": "1.1.0"})
    _, out = _run("--update", "--manifest", str(m2), "--no-prompt", game=game, env_extra=_ENV)
    assert "Already up to date" not in out, out
    assert "HD Cinematics v1.1.0 downloaded" in out, out    # the player-facing label, not the module id
    assert (game / "movies" / "hd" / "a.mp4").read_bytes() == b"v2"
    assert (game / "movies" / "hd" / "b.mp4").read_bytes() == b"new"
    assert rc.module_version(rc.read(game), "movies-hd") == "1.1.0"
    assert "update offered: HD Cinematics v1.0.0 -> v1.1.0" in out, out
    assert "HD Cinematics v1.1.0 installed. Nothing else needed changing." in out, out


def test_a_base_release_does_not_redownload_a_current_pack(game_installed, tmp_path):
    """The 1.3 GB defect: every base release re-fetched every installed pack, changed or not."""
    game = game_installed
    _with_pack(tmp_path, game, "1.0.0", {"movies/hd/a.mp4": b"v1"})
    m2 = _publish(tmp_path / "pub-base", game, latest="9.9.9",
                  modules={"movies-hd": {"movies/hd/a.mp4": b"v1"}},
                  versions={"movies-hd": "1.0.0"})
    _, out = _run("--update", "--manifest", str(m2), "--no-prompt", game=game, env_extra=_ENV)
    assert "commit" in out, out                      # the base update itself still happens
    assert "HD Cinematics: up to date (v1.0.0), no download needed" in out, out
    assert "module movies-hd downloaded" not in out, out
    assert rc.module_version(rc.read(game), "movies-hd") == "1.0.0", \
        "an untouched pack keeps its recorded version"


def _check_lines(game, m) -> list:
    """The game's own launch query: what its update offer would list."""
    p = subprocess.run([str(_PY), str(_INSTALL), "--check", "--game-dir", str(game), "--manifest",
                        str(m)], capture_output=True, env={**os.environ, **_ENV}, timeout=120,
                       stdin=subprocess.DEVNULL)
    return p.stdout.decode("ascii").splitlines()


def test_a_declined_pack_is_installed_only_when_the_offer_listed_it(game_installed, tmp_path):
    """THE RESET RULE end to end (user, 2026-10-31): "a decline of any pack is reset when any new
    update releases for a module that is already installed". --update brings every stale module
    current, so the offer must list a declined pack whenever an update for something installed is
    on the table -- and --update then installs exactly what was listed."""
    game = game_installed
    _with_pack(tmp_path, game, "1.0.0", {"movies/hd/a.mp4": b"v1"})
    assert rc.decline(game, "movies-hd", "1.1.0")         # "Don't ask me again" on 1.0.0 -> 1.1.0

    # Only the declined pack moved: the offer stays quiet, and nothing would be launched.
    quiet = _publish(tmp_path / "pub-pack", game, latest=ver.VERSION,
                     modules={"movies-hd": {"movies/hd/a.mp4": b"v2"}},
                     versions={"movies-hd": "1.1.0"})
    assert _check_lines(game, quiet) == [f"latest={ver.VERSION}"]

    # The core moved too: the decline is void, the offer lists BOTH, and accepting installs both.
    core = _publish(tmp_path / "pub-core", game, latest="9.9.9",
                    modules={"movies-hd": {"movies/hd/a.mp4": b"v2"}},
                    versions={"movies-hd": "1.1.0"})
    lines = _check_lines(game, core)
    assert [ln.split("|", 1)[0] for ln in lines] == \
        ["latest=9.9.9", f"base={ver.VERSION}>9.9.9", "stale=movies-hd"], lines
    _, out = _run("--update", "--manifest", str(core), "--no-prompt", game=game, env_extra=_ENV)
    assert "UPDATE COMPLETE" in out, out
    assert (game / "movies" / "hd" / "a.mp4").read_bytes() == b"v2"
    assert rc.module_version(rc.read(game), "movies-hd") == "1.1.0"


def test_a_declined_new_pack_is_offered_again_beside_an_installed_packs_update(game_installed,
                                                                               tmp_path):
    """`new:<id>:*` is "not until the next undeclined release for something installed"."""
    game = game_installed
    _with_pack(tmp_path, game, "1.0.0", {"movies/hd/a.mp4": b"v1"})
    assert rc.decline(game, "new:portraits-hd", rc.DECLINE_ANY)
    mods = {"movies-hd": {"movies/hd/a.mp4": b"v1"}, "portraits-hd": {"portraits/hd/x.pcx": b"p"}}
    alone = _publish(tmp_path / "pub-alone", game, latest=ver.VERSION, modules=mods,
                     versions={"movies-hd": "1.0.0", "portraits-hd": "1.0.0"})
    assert _check_lines(game, alone) == [f"latest={ver.VERSION}"]
    beside = _publish(tmp_path / "pub-beside", game, latest=ver.VERSION,
                      modules={**mods, "movies-hd": {"movies/hd/a.mp4": b"v2"}},
                      versions={"movies-hd": "1.1.0", "portraits-hd": "1.0.0"})
    assert [ln.split("|", 1)[0] for ln in _check_lines(game, beside)] == \
        [f"latest={ver.VERSION}", "stale=movies-hd", "new=portraits-hd"]


# ---- --only-listed: the game hands the updater the exact list it showed and the player accepted
# (user, 2026-10-31); the updater installs exactly that, plus the core whenever it is stale.

_BOTH = {"movies-hd": {"movies/hd/a.mp4": b"v2"}, "portraits-hd": {"portraits/hd/x.pcx": b"p"}}


def _heads(lines) -> list:
    return [ln.split("|", 1)[0] for ln in lines]


def test_only_listed_installs_the_listed_new_pack_and_leaves_a_declined_one(game_installed,
                                                                            tmp_path):
    game = game_installed
    _with_pack(tmp_path, game, "1.0.0", {"movies/hd/a.mp4": b"v1"})
    entry_before = dict(rc.read(game)["modules"]["movies-hd"])
    m = _publish(tmp_path / "pub", game, latest=ver.VERSION, modules=_BOTH,
                 versions={"movies-hd": "1.1.0", "portraits-hd": "1.0.0"})
    assert rc.decline(game, "movies-hd", "1.1.0")
    # A declined stale PACK hides only itself: the new pack is still offered.
    assert _heads(_check_lines(game, m)) == [f"latest={ver.VERSION}", "new=portraits-hd"]
    _, out = _run("--update", "--only-listed", "--modules", "portraits-hd", "--manifest", str(m),
                  "--no-prompt", game=game, env_extra=_ENV)
    assert "UPDATE COMPLETE" in out, out
    assert "HD Cinematics v1.1.0: not part of this update" in out, out
    assert "HD Cinematics v1.1.0 downloaded" not in out, out
    # The verdict names the pack left behind -- never "Nothing else needed changing".
    assert "HD Cinematics stays at v1.0.0 (v1.1.0 was not part of this update)" in out, out
    assert "Nothing else needed changing" not in out, out
    state = rc.read(game)
    assert rc.module_version(state, "portraits-hd") == "1.0.0"
    assert state["modules"]["movies-hd"] == entry_before, "the unlisted pack's receipt entry changed"
    assert (game / "movies" / "hd" / "a.mp4").read_bytes() == b"v1"
    assert (game / "portraits" / "hd" / "x.pcx").read_bytes() == b"p"


def test_only_listed_with_the_core_and_a_listed_pack_installs_both(game_installed, tmp_path):
    game = game_installed
    _with_pack(tmp_path, game, "1.0.0", {"movies/hd/a.mp4": b"v1"})
    m = _publish(tmp_path / "pub", game, latest="9.9.9",
                 modules={"movies-hd": {"movies/hd/a.mp4": b"v2"}},
                 versions={"movies-hd": "1.1.0"})
    assert _heads(_check_lines(game, m)) == ["latest=9.9.9", f"base={ver.VERSION}>9.9.9",
                                             "stale=movies-hd"]
    _, out = _run("--update", "--only-listed", "--modules", "movies-hd", "--manifest", str(m),
                  "--no-prompt", game=game, env_extra=_ENV)
    assert "game patch: applied" in out and "UPDATE COMPLETE" in out, out
    assert (game / "movies" / "hd" / "a.mp4").read_bytes() == b"v2"
    assert rc.module_version(rc.read(game), "movies-hd") == "1.1.0"


def test_only_listed_without_modules_brings_only_the_core_current(game_installed, tmp_path):
    game = game_installed
    _with_pack(tmp_path, game, "1.0.0", {"movies/hd/a.mp4": b"v1"})
    m = _publish(tmp_path / "pub", game, latest="9.9.9",
                 modules={"movies-hd": {"movies/hd/a.mp4": b"v2"}},
                 versions={"movies-hd": "1.1.0"})
    _, out = _run("--update", "--only-listed", "--manifest", str(m), "--no-prompt", game=game,
                  env_extra=_ENV)
    assert "game patch: applied" in out, out
    assert "HD Cinematics v1.1.0: not part of this update" in out, out
    assert "HD Cinematics: up to date" not in out, out
    assert (game / "movies" / "hd" / "a.mp4").read_bytes() == b"v1"
    assert rc.module_version(rc.read(game), "movies-hd") == "1.0.0"


def test_only_listed_with_nothing_stale_listed_changes_nothing_and_says_so(game_installed,
                                                                           tmp_path):
    game = game_installed
    _with_pack(tmp_path, game, "1.0.0", {"movies/hd/a.mp4": b"v1"})
    m = _publish(tmp_path / "pub", game, latest=ver.VERSION,
                 modules={"movies-hd": {"movies/hd/a.mp4": b"v2"}},
                 versions={"movies-hd": "1.1.0"})
    _, out = _run("--update", "--only-listed", "--manifest", str(m), "--no-prompt", game=game,
                  env_extra=_ENV)
    assert "ALREADY UP TO DATE" in out and "Nothing the game listed needs updating" in out, out
    assert "Everything you have installed is current" not in out, out
    assert (game / "movies" / "hd" / "a.mp4").read_bytes() == b"v1"


def test_without_only_listed_the_console_still_adds_every_stale_pack(game_installed, tmp_path):
    """Regression pin: a hand-typed `--update --modules X` is X PLUS the stale installed packs."""
    game = game_installed
    _with_pack(tmp_path, game, "1.0.0", {"movies/hd/a.mp4": b"v1"})
    m = _publish(tmp_path / "pub", game, latest=ver.VERSION, modules=_BOTH,
                 versions={"movies-hd": "1.1.0", "portraits-hd": "1.0.0"})
    assert rc.decline(game, "movies-hd", "1.1.0")         # declines never narrow the console
    _run("--update", "--modules", "portraits-hd", "--manifest", str(m), "--no-prompt", game=game,
         env_extra=_ENV)
    state = rc.read(game)
    assert rc.module_version(state, "movies-hd") == "1.1.0"
    assert rc.module_version(state, "portraits-hd") == "1.0.0"


def test_only_listed_is_refused_outside_an_update(game_installed):
    code, out = _run("--only-listed", "--ai", "off", game=game_installed, expect_ok=False)
    assert code == ix.EXIT_ABORTED and "--only-listed works only with --update" in out, out


def test_an_already_current_run_says_which_pack_could_be_added(game_installed, tmp_path):
    game = game_installed
    m = _publish(tmp_path, game, latest=ver.VERSION,
                 modules={"movies-hd": {"movies/hd/a.mp4": b"v1"}},
                 versions={"movies-hd": "1.0.0"})
    _, out = _run("--update", "--manifest", str(m), game=game, env_extra=_ENV)
    assert "Already up to date" in out, out
    assert "HD Cinematics: available, not installed" in out, out
    launcher = game / "LongevityMods" / "updater" / "scripts" / "run-install.bat"
    assert launcher.is_file()
    assert f'"{launcher}" --update --modules movies-hd --manifest "{m}"' in out, \
        "the notice must give a command that can be pasted as-is"
    assert "ALREADY UP TO DATE" in out and "optional extras" in out, out
    assert not (game / "movies").exists(), "announced, never fetched"


def test_a_pack_can_be_named_by_its_label(game_installed, tmp_path):
    game = game_installed
    m = _publish(tmp_path, game, latest=ver.VERSION,
                 modules={"movies-hd": {"movies/hd/a.mp4": b"v1"}},
                 versions={"movies-hd": "1.0.0"})
    _, out = _run("--update", "--manifest", str(m), "--modules", "hd CINEMATICS",
                  "--no-prompt", game=game, env_extra=_ENV)
    assert (game / "movies" / "hd" / "a.mp4").read_bytes() == b"v1"
    assert "HD Cinematics v1.0.0 installed. Nothing else needed changing." in out, out
    assert "available, not installed" not in out, "the pack just installed must not be offered"


def test_asking_for_a_pack_the_manifest_does_not_offer_is_refused(game_installed, tmp_path):
    """It used to be a [warn] followed by UPDATE COMPLETE with no pack."""
    game = game_installed
    m = _publish(tmp_path, game, latest=ver.VERSION, modules={})
    exe_before = (game / "terranx_PRACX.exe").read_bytes()
    code, out = _run("--update", "--manifest", str(m), "--modules", "portraits-hd",
                     "--no-prompt", game=game, env_extra=_ENV, expect_ok=False)
    assert code == 3, out
    assert "[FAIL] Turovetsky's HD Portrait Pack: not released yet" in out, out
    assert "Turovetsky's HD Portrait Pack is not available for download yet. Nothing was downloaded " \
           "or changed." in out, out
    assert "NOTHING WAS CHANGED" in out and "CANCELLED" not in out, out
    assert "nothing to do now; your game is fine" in out, out
    assert "fix the items above" not in out, "a retry cannot fix an unreleased pack"
    assert (game / "terranx_PRACX.exe").read_bytes() == exe_before


def test_a_pack_only_update_whose_download_fails_changes_nothing(game_installed, tmp_path):
    """The pack IS the update: a failed download must not re-commit, write the receipt and say
    UPDATE COMPLETE about an update that did not happen."""
    game = game_installed
    _with_pack(tmp_path, game, "1.0.0", {"movies/hd/a.mp4": b"v1"})
    m2 = _publish(tmp_path / "pub-bad", game, latest=ver.VERSION,
                  modules={"movies-hd": {"movies/hd/a.mp4": b"v2"}},
                  versions={"movies-hd": "1.1.0"})
    doc = json.loads(m2.read_text(encoding="utf-8"))
    Path(doc["modules"]["movies-hd"]["url"][len("file:///"):]).write_bytes(b"corrupt")
    receipt_before = (game / rc.JSON_NAME).read_bytes()
    code, out = _run("--update", "--manifest", str(m2), "--no-prompt", game=game,
                     env_extra=_ENV, expect_ok=False)
    assert code == 3, out
    assert "The update to HD Cinematics v1.1.0 could not be downloaded. HD Cinematics v1.0.0 " \
           "are still installed and work as before. Nothing was changed." in out, out
    assert "NOTHING WAS CHANGED" in out, out
    assert "UPDATE COMPLETE" not in out and "INSTALLATION SUCCESSFUL" not in out
    assert "installed terranx_PRACX.exe" not in out, "the exe is not rewritten before the abort"
    assert (game / rc.JSON_NAME).read_bytes() == receipt_before
    assert (game / "movies" / "hd" / "a.mp4").read_bytes() == b"v1"


def test_a_base_update_with_a_failed_pack_is_not_reported_as_complete(game_installed,
                                                                      tmp_path):
    game = game_installed
    _with_pack(tmp_path, game, "1.0.0", {"movies/hd/a.mp4": b"v1"})
    m2 = _publish(tmp_path / "pub-bad", game, latest="9.9.9",
                  modules={"movies-hd": {"movies/hd/a.mp4": b"v2"}},
                  versions={"movies-hd": "1.1.0"})
    doc = json.loads(m2.read_text(encoding="utf-8"))
    Path(doc["modules"]["movies-hd"]["url"][len("file:///"):]).write_bytes(b"corrupt")
    code, out = _run("--update", "--manifest", str(m2), "--no-prompt", game=game,
                     env_extra=_ENV, expect_ok=False)
    assert code == 1, out
    assert "UPDATE PARTLY COMPLETE" in out, out
    assert f"Longevity Vaccine v{ver.VERSION} is installed and the game is ready to play. " \
           "The update to HD Cinematics v1.1.0 could not be downloaded. HD Cinematics v1.0.0 " \
           "are still installed and work as before." in out, out
    assert "only the pack update is missing" in out and "partway through" not in out, out
    assert "run the update again to get HD Cinematics v1.1.0" in out, out
    assert "UPDATE COMPLETE" not in out and "INSTALLATION SUCCESSFUL" not in out
    assert "INSTALLATION FAILED" not in out
    state = rc.read(game)
    assert rc.module_version(state, "base") == ver.VERSION      # the core update was recorded
    assert rc.module_version(state, "movies-hd") == "1.0.0"     # the pack was not


# ---------------------------------------------------------------- --check over a real pipe

def _check(game: Path, *args) -> tuple:
    """Run `install.py --check` exactly as the game does: a pipe on stdout, stderr separate."""
    env = dict(os.environ)
    if _PAYLOAD is not None:
        env["LONGEVITY_PAYLOAD_ROOT"] = str(_PAYLOAD)
    env.update(_ENV)
    p = subprocess.run([str(_PY), str(_INSTALL), "--check", "--game-dir", str(game), *args],
                       capture_output=True, env=env, timeout=300, stdin=subprocess.DEVNULL)
    raw = p.stdout                       # BYTES: a text-mode read would hide a CRLF
    assert b"\r" not in raw, f"the pipe must be LF-only for a C++ parser: {raw!r}"
    lines = raw.decode("ascii").split("\n")
    assert lines[-1] == "", "every line ends in LF"
    lines = lines[:-1]
    for ln in lines:
        assert re.match(r"^(latest|base|stale|new|manual)=[\x20-\x7e]*$", ln), \
            f"stdout is a pipe the game parses; this is not a protocol line: {ln!r}\n{p.stderr}"
    return p.returncode, lines, p.stderr.decode("utf-8", "replace")


def test_check_reports_nothing_when_current(game_installed, tmp_path):
    game = game_installed
    m = _publish(tmp_path, game, latest=ver.VERSION, modules={})
    code, lines, err = _check(game, "--manifest", str(m))
    assert code == 0, err
    assert lines == [f"latest={ver.VERSION}"]
    assert "LONGEVITY VACCINE" not in "\n".join(lines), "no banner on the pipe"
    assert rc.ini_get(game, rc.KEY_LAST_CHECK), "a verified check is recorded"


def test_check_reports_a_new_pack_then_honours_a_decline(game_installed, tmp_path):
    game = game_installed
    m = _publish(tmp_path, game, latest=ver.VERSION,
                 modules={"movies-hd": {"movies/hd/a.mp4": b"v1"}},
                 versions={"movies-hd": "1.0.0"})
    code, lines, err = _check(game, "--manifest", str(m))
    assert code == 10, err
    assert lines[0] == f"latest={ver.VERSION}"
    assert lines[1].startswith("new=movies-hd|HD Cinematics|1.0.0|"), lines
    assert not (game / "movies").exists(), "--check installs nothing"
    assert rc.decline(game, "new:movies-hd", "1.0.0")
    code, lines, err = _check(game, "--manifest", str(m))
    assert code == 0 and lines == [f"latest={ver.VERSION}"], \
        (lines, err, (game / "Alpha Centauri.ini").read_text(encoding="utf-8", errors="replace"))


@pytest.fixture(scope="module")
def dll_parser():
    """The DLL's parser (src\\uimod\\src\\update_core.h) built as a harness -- the other end of the pipe."""
    import cpp_harness
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    return cpp_harness.build(Path(__file__).resolve().parent / "update_core_selftest.cpp", "e2e_update_core_")


def _dll_parse(exe: Path, code: int, raw: bytes, tmp_path: Path) -> list:
    p = tmp_path / f"pipe_{code}_{len(raw)}.bin"
    p.write_bytes(raw)
    r = subprocess.run([str(exe), "parse", str(code), str(p)], capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.decode("ascii").replace("\r\n", "\n").rstrip("\n").split("\n")


def _check_raw(game: Path, *args) -> tuple:
    env = dict(os.environ)
    if _PAYLOAD is not None:
        env["LONGEVITY_PAYLOAD_ROOT"] = str(_PAYLOAD)
    env.update(_ENV)
    p = subprocess.run([str(_PY), str(_INSTALL), "--check", "--game-dir", str(game), *args],
                       capture_output=True, env=env, timeout=300, stdin=subprocess.DEVNULL)
    return p.returncode, p.stdout


def test_the_dll_parser_reads_every_real_check_answer(game_installed, tmp_path, dll_parser):
    """GOLDEN: the real python.exe's bytes, as the game would read them off the pipe, into the
    C++ parser. One row per state the installer can be in."""
    game = game_installed
    # nothing to offer
    m = _publish(tmp_path / "p0", game, latest=ver.VERSION, modules={})
    code, raw = _check_raw(game, "--manifest", str(m))
    assert _dll_parse(dll_parser, code, raw, tmp_path) == ["status=ok code=0 badline=0", f"latest={ver.VERSION}"]
    # a new pack, with its size
    m = _publish(tmp_path / "p1", game, latest=ver.VERSION,
                 modules={"movies-hd": {"movies/hd/a.mp4": b"v1" * 1000}}, versions={"movies-hd": "1.0.0"})
    code, raw = _check_raw(game, "--manifest", str(m))
    out = _dll_parse(dll_parser, code, raw, tmp_path)
    assert out[0] == "status=ok code=10 badline=0" and out[1] == f"latest={ver.VERSION}"
    assert re.fullmatch(r"new=movies-hd\|HD Cinematics\|1\.0\.0\|\d+", out[2]), out
    # base update + stale pack
    _with_pack(tmp_path, game, "1.0.0", {"movies/hd/a.mp4": b"v1"})
    m = _publish(tmp_path / "p2", game, latest="9.9.9",
                 modules={"movies-hd": {"movies/hd/a.mp4": b"v2"}}, versions={"movies-hd": "1.1.0"})
    code, raw = _check_raw(game, "--manifest", str(m))
    out = _dll_parse(dll_parser, code, raw, tmp_path)
    assert out[:3] == ["status=ok code=10 badline=0", "latest=9.9.9", f"base={ver.VERSION}>9.9.9"]
    assert re.fullmatch(r"stale=movies-hd\|HD Cinematics\|1\.0\.0>1\.1\.0\|\d+", out[3]), out
    # manual (kill switch)
    pub = tmp_path / "p3"
    pub.mkdir()
    doc = {"schema": 1, "protocol": 1, "product": "longevity-vaccine", "latest": ver.VERSION,
           "min_upgradable_from": "0.0.0", "manual_install_required": True,
           "manual_install_reason": "bootstrap_defect", "unsupported_versions": [],
           "unsupported_targets": [], "yanked": [], "modules": {}}
    mm = pub / "manifest.json"
    mm.write_text(json.dumps(doc), encoding="utf-8")
    sm.sign_file(SEED, mm)
    code, raw = _check_raw(game, "--manifest", str(mm))
    assert _dll_parse(dll_parser, code, raw, tmp_path) == ["status=ok code=11 badline=0",
                                                           "manual=bootstrap_defect reason=2"]
    # untrusted: tampered signature -> 12, empty pipe
    (pub / "manifest.json.sig").write_bytes(b"\x00" * 64)
    code, raw = _check_raw(game, "--manifest", str(mm))
    assert code == 12 and raw == b""
    assert _dll_parse(dll_parser, code, raw, tmp_path) == ["status=ok code=12 badline=0"]
    # the "for good" decline string the previous builds' update.cpp wrote (today only a new pack's
    # `new:<id>:*` is written that way) stays honoured: an ini from an older build keeps its silence
    assert rc.ini_set(game, rc.KEY_DECLINED, "base:*;movies-hd:*")
    code, raw = _check_raw(game, "--manifest", str(m))
    assert _dll_parse(dll_parser, code, raw, tmp_path) == ["status=ok code=0 badline=0", "latest=9.9.9"]
    assert rc.clear_declines(game)


def _wait_for_processes_under(root: Path, hang_guard_s: float) -> bool:
    """Block until no process whose image lives under `root` is running; False only if the hang
    guard expires first.

    Generation 2 runs in its own console from <game>\\LongevityMods\\staging and outlives the
    command the test ran, so its exit is the one signal that the update is over. Its worker
    (install.py) runs on the same interpreter, and gen 2 waits for it, so both are covered; the
    snapshot is retaken until it comes back empty in case a process started another. `root` is
    under this test's tmp_path, so no other test's processes can match.
    """
    import ctypes
    from ctypes import wintypes as W

    class PE32(ctypes.Structure):
        _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", W.DWORD),
                    ("cntThreads", W.DWORD), ("th32ParentProcessID", W.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", W.DWORD),
                    ("szExeFile", ctypes.c_char * 260)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = W.HANDLE
    k32.OpenProcess.restype = W.HANDLE
    k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    k32.WaitForSingleObject.restype = W.DWORD
    k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    k32.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR,
                                               ctypes.POINTER(W.DWORD)]
    prefix = str(Path(root).resolve()).lower().rstrip("\\") + "\\"
    deadline = time.monotonic() + hang_guard_s

    def under_root() -> list:
        handles = []
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)                  # TH32CS_SNAPPROCESS
        if not snap or snap == W.HANDLE(-1).value:
            raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
        try:
            e = PE32(dwSize=ctypes.sizeof(PE32))
            ok = k32.Process32First(W.HANDLE(snap), ctypes.byref(e))
            while ok:
                # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION
                h = k32.OpenProcess(0x00100000 | 0x1000, False, e.th32ProcessID)
                if h:
                    buf = ctypes.create_unicode_buffer(1024)
                    n = W.DWORD(len(buf))
                    # An exited process another program still holds a handle to can stay in the
                    # snapshot; it is already signalled, so it is not waited on (no busy spin).
                    if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) \
                            and buf.value.lower().startswith(prefix) \
                            and k32.WaitForSingleObject(h, 0) != 0:
                        handles.append(h)
                    else:
                        k32.CloseHandle(W.HANDLE(h))
                ok = k32.Process32Next(W.HANDLE(snap), ctypes.byref(e))
        except BaseException:
            for h in handles:
                k32.CloseHandle(W.HANDLE(h))
            raise
        finally:
            k32.CloseHandle(W.HANDLE(snap))
        return handles

    while True:
        handles = under_root()
        if not handles:
            return True
        try:
            for h in handles:
                left = deadline - time.monotonic()
                if left <= 0 or k32.WaitForSingleObject(h, int(left * 1000)) != 0:   # WAIT_OBJECT_0
                    return False
        finally:
            for h in handles:
                k32.CloseHandle(W.HANDLE(h))


def _self_update_report(game: Path, out1: str) -> str:
    """Everything a failed self-update leaves on disk, for the assertion message. Generation 2
    runs in its own console, so its output is not captured: the tree it left is the evidence
    (an `updater.new` beside an old `updater` = the swap failed after the copy). Never raises:
    generation 2 may still be writing, and a report that throws hides the real assertion."""
    import bootstrap as bs

    def read(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else "(none)"
        except OSError as e:
            return f"(unreadable: {e})"

    root = bs.mods_root(game)
    lines = ["--- generation 1 output ---", out1, f"--- {root} ---"]
    try:
        for d in sorted(root.iterdir()) if root.is_dir() else []:
            if d.is_dir() and not d.name.startswith(bs.UPDATER_DIR):
                lines.append(f"  {d.name}/")
            elif d.is_dir():
                usable = bs.is_usable(d)
                lines.append(f"  {d.name}/  VERSION={read(d / bs.VERSION_FILE).strip()}  "
                             f"usable={usable}" + ("" if usable else f"  missing={bs.missing_parts(d)}"))
            else:
                lines.append(f"  {d.name}")
        lines += ["--- receipt ---", read(game / rc.JSON_NAME)]
        logs = sorted((root / "logs").glob("*.log")) if (root / "logs").is_dir() else []
        logs += sorted((root / bs.UPDATER_DIR / "scripts").glob("install-crash-*.log"))
        for log in logs:
            lines += [f"--- {log.relative_to(game)} (last 40 lines) ---",
                      *read(log).splitlines()[-40:]]
    except OSError as e:
        lines.append(f"(report incomplete: {e})")
    return "\n".join(lines)


def test_the_base_real_dev_scenario_really_self_updates(game_installed, tmp_path):
    """The `base-real` scenario of dev_test_manifest.py, driven the way the game's hand-off
    drives it (run-install.bat --update --manifest <m> --wait-pid <dead pid>): generation 1
    downloads the 9.9.9 archive, hands over to generation 2 in its own console, which swaps the
    resident updater and re-installs. We wait for the receipt to say 9.9.9."""
    import dev_test_manifest as dtm
    game = game_installed
    out = tmp_path / "base-real"
    out.mkdir()
    m = out / "manifest.json"
    m.write_text(json.dumps(dtm.build("base-real", ver.VERSION, out), indent=2), encoding="utf-8")
    sm.sign_file(SEED, m)
    assert rc.module_version(rc.read(game), "base") == ver.VERSION
    bat = game / "LongevityMods" / "updater" / "scripts" / "run-install.bat"
    env = dict(os.environ)
    env.update(_ENV)
    env["LONGEVITY_NO_WAIT"] = "1"
    gone = subprocess.Popen(["cmd", "/c", "exit"])          # a pid that HAS exited (pid 4 is System)
    gone.wait()
    # One STRING, exactly as the DLL builds it (a list would be re-quoted by Python).
    # --only-listed with no --modules: the game's hand-off when the player accepted the core alone;
    # it must survive generation 1 -> generation 2 -> the worker.
    cmdline = (f'cmd /D /S /C ""{bat}" --update --game-dir "{game}" --wait-pid {gone.pid} --only-listed '
               f'--manifest "{m}" --no-prompt --no-wait"')
    p = subprocess.run(cmdline, capture_output=True, text=True, env=env, timeout=600, stdin=subprocess.DEVNULL)
    out1 = p.stdout + p.stderr
    assert "Waiting for Alpha Centauri to close." in out1 and "Updating..." in out1, out1
    assert "a newer installer is available" in out1 and "handing over to the new installer" in out1, out1
    # Wait for generation 2 to EXIT -- the observable end of the update -- not for the receipt to
    # change within a wall-clock budget. The old 300 s poll failed under a loaded full suite and
    # passed alone (2026-10-28), and asserting while gen 2 still ran raced its last writes. The
    # limit below is a hang guard only: a live update is never cut short by machine load.
    import bootstrap as bs
    assert _wait_for_processes_under(bs.mods_root(game), hang_guard_s=1800), \
        "generation 2 never exited (hang guard)\n" + _self_update_report(game, out1)
    assert rc.module_version(rc.read(game), "base") == dtm.REAL_VERSION, _self_update_report(game, out1)
    # Generation 2 swaps BEFORE it installs, so a receipt at 9.9.9 over a resident 0.1.0 means
    # the swap itself failed (gen 2 then carries on by design). That was a load flake until
    # swap_in learned to wait out a briefly-held file (2026-10-28); if it still happens, the
    # lock outlasted RENAME_RETRY_SECONDS and the report says what was left behind.
    assert bs.resident_version(game) == dtm.REAL_VERSION, \
        "the resident updater was not swapped\n" + _self_update_report(game, out1)
    assert (game / "uimod.dll").is_file() and (game / "longevity_sm.pcx").is_file()
    # ... and the check now says "nothing to offer" against the same manifest
    code, lines, err = _check(game, "--manifest", str(m))
    assert code == 0 and lines == [f"latest={dtm.REAL_VERSION}"], (lines, err)


def test_check_honours_an_any_version_decline_across_releases(game_installed, tmp_path):
    """The game's "Don't ask me again": `new:movies-hd:*` hides the pack at 1.0.0 AND at 2.0.0;
    "Reset Skipped Updates" (clear_declines) brings it back."""
    game = game_installed
    m1 = _publish(tmp_path / "p1", game, latest=ver.VERSION,
                  modules={"movies-hd": {"movies/hd/a.mp4": b"v1"}},
                  versions={"movies-hd": "1.0.0"})
    assert rc.decline(game, "new:movies-hd", rc.DECLINE_ANY)
    code, lines, err = _check(game, "--manifest", str(m1))
    assert code == 0 and lines == [f"latest={ver.VERSION}"], (lines, err)
    m2 = _publish(tmp_path / "p2", game, latest=ver.VERSION,
                  modules={"movies-hd": {"movies/hd/a.mp4": b"v2"}},
                  versions={"movies-hd": "2.0.0"})
    code, lines, err = _check(game, "--manifest", str(m2))
    assert code == 0 and lines == [f"latest={ver.VERSION}"], (lines, err)
    assert rc.clear_declines(game)
    code, lines, err = _check(game, "--manifest", str(m2))
    assert code == 10 and lines[1].startswith("new=movies-hd|HD Cinematics|2.0.0|"), (lines, err)


def test_check_reports_a_stale_pack_and_a_base_update(game_installed, tmp_path):
    game = game_installed
    _with_pack(tmp_path, game, "1.0.0", {"movies/hd/a.mp4": b"v1"})
    m = _publish(tmp_path / "pub-next", game, latest="9.9.9",
                 modules={"movies-hd": {"movies/hd/a.mp4": b"v2"}},
                 versions={"movies-hd": "1.1.0"})
    code, lines, err = _check(game, "--manifest", str(m))
    assert code == 10, err
    assert lines[0] == "latest=9.9.9"
    assert lines[1] == f"base={ver.VERSION}>9.9.9"
    assert lines[2].startswith("stale=movies-hd|HD Cinematics|1.0.0>1.1.0|"), lines
    assert (game / "movies" / "hd" / "a.mp4").read_bytes() == b"v1", "--check installs nothing"


def test_check_reports_manual_for_a_kill_switch(game_installed, tmp_path):
    game = game_installed
    pub = tmp_path / "published"
    pub.mkdir()
    doc = {"schema": 1, "protocol": 1, "product": "longevity-vaccine", "latest": ver.VERSION,
           "min_upgradable_from": "0.0.0", "manual_install_required": True,
           "manual_install_reason": "bootstrap_defect", "unsupported_versions": [],
           "unsupported_targets": [], "yanked": [], "modules": {}}
    m = pub / "manifest.json"
    m.write_text(json.dumps(doc), encoding="utf-8")
    sm.sign_file(SEED, m)
    code, lines, err = _check(game, "--manifest", str(m))
    assert code == 11, err
    assert lines == ["manual=bootstrap_defect"]


def test_an_update_with_wait_pid_proceeds_once_that_process_is_gone(game_installed, tmp_path):
    game = game_installed
    m = _publish(tmp_path, game, latest=ver.VERSION,
                 modules={"movies-hd": {"movies/hd/a.mp4": b"v1"}},
                 versions={"movies-hd": "1.0.0"})
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    _, out = _run("--update", "--manifest", str(m), "--modules", "movies-hd", "--no-prompt",
                  "--wait-pid", str(gone.pid), game=game, env_extra=_ENV)
    assert "Waiting for Alpha Centauri to close." in out, out
    assert "Updating..." in out and "spawning game has exited" in out, out
    assert out.count("LONGEVITY VACCINE") == 1, "the in-place worker must not print the header a second time"
    assert "generation" not in out.split("Waiting for Alpha Centauri")[0], "no bootstrap jargon before the wait"
    assert "LONGEVITY VACCINE" in out, "the update flow opens with the same header as a first install"
    assert (game / "movies" / "hd" / "a.mp4").read_bytes() == b"v1"


def test_check_keeps_working_when_the_game_folder_is_not_writable(game_installed, tmp_path):
    """A Program Files install run unelevated cannot create LongevityMods\\staging; the check
    used to exit 12 on every launch, so the player was never told about an update."""
    game = game_installed
    m = _publish(tmp_path, game, latest=ver.VERSION,
                 modules={"movies-hd": {"movies/hd/a.mp4": b"v1"}},
                 versions={"movies-hd": "1.0.0"})
    shutil.rmtree(game / "LongevityMods")
    (game / "LongevityMods").write_bytes(b"not a directory")     # staging cannot be created
    env = dict(os.environ)
    env.update(_ENV)
    env["LOCALAPPDATA"] = str(tmp_path / "appdata")               # keep the fallback in tmp
    if _PAYLOAD is not None:
        env["LONGEVITY_PAYLOAD_ROOT"] = str(_PAYLOAD)
    p = subprocess.run([str(_PY), str(_INSTALL), "--check", "--game-dir", str(game),
                        "--manifest", str(m)], capture_output=True, env=env, timeout=300,
                       stdin=subprocess.DEVNULL)
    assert p.returncode == 10, p.stderr.decode("utf-8", "replace")
    assert b"new=movies-hd|HD Cinematics|1.0.0|" in p.stdout
    assert b"is not writable; caching the manifest under" in p.stderr
    cached = list((tmp_path / "appdata" / "LongevityVaccine").rglob("manifest.json"))
    assert len(cached) == 1, "the manifest is cached per user, per install"
    assert (game / "LongevityMods").read_bytes() == b"not a directory", "nothing forced"


def test_check_fails_closed_with_an_empty_pipe(game_installed, tmp_path):
    game = game_installed
    # an untrusted manifest
    m = _publish(tmp_path, game, latest=ver.VERSION, modules={})
    m.write_bytes(m.read_bytes().replace(b"longevity-vaccine", b"longevity-vaccinf"))
    code, lines, err = _check(game, "--manifest", str(m))
    assert code == 12 and lines == [], (lines, err)
    assert "signature" in err
    # a manifest that is not there at all
    code, lines, err = _check(game, "--manifest", str(tmp_path / "nope.json"))
    assert code == 12 and lines == [], (lines, err)
    # no game directory
    p = subprocess.run([str(_PY), str(_INSTALL), "--check", "--game-dir", str(tmp_path / "x")],
                       capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    assert p.returncode == 12 and p.stdout == "", p.stderr
    # an EMPTY --game-dir must not fall through to autodetection (which would find the REAL
    # install): refused before anything is read or fetched.
    p = subprocess.run([str(_PY), str(_INSTALL), "--check", "--game-dir", ""],
                       capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
                       env={**os.environ, "SMACX_GAME_DIR": str(tmp_path / "decoy")})
    assert p.returncode == 12 and p.stdout == "", p.stderr
    assert "--game-dir is required" in p.stderr
    assert not (tmp_path / "decoy").exists()
    # the reader closing early must not turn the exit code into 120
    p = subprocess.Popen([str(_PY), str(_INSTALL), "--check", "--game-dir", str(game),
                          "--manifest", str(tmp_path / "nope.json")],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL)
    p.stdout.close()
    assert p.wait(timeout=120) == 12


def test_an_unknown_module_name_is_refused_before_anything_happens(game_installed, tmp_path):
    game = game_installed
    m = _publish(tmp_path, game, latest=ver.VERSION,
                 modules={"movies-hd": {"movies/hd/a.mp4": b"v1"}})
    before = _tree(game)
    code, out = _run("--update", "--manifest", str(m), "--modules", "bogus,movies-hd",
                     "--no-prompt", game=game, env_extra=_ENV, expect_ok=False)
    assert code == 3, out
    assert '"bogus" is not an extra this installer knows.' in out, out
    assert "movies-hd" in out and "Turovetsky's HD Portrait Pack" in out, \
        "the refusal must list the extras it does know, by id and by label"
    assert "--update --modules movies-hd" in out, "the remedy must show the exact form"
    assert _tree(game) == before, "refused before the manifest was even fetched"

# ---------------------------------------------------------------- fresh install + optional packs

def test_a_fresh_install_can_take_a_pack_from_the_manifest(game, tmp_path):
    """`--modules movies-hd` on a FIRST install: the pack is fetched through the update's
    verified path after the game is patched, recorded at the manifest's version, and the
    cinematics flag is switched on. The downloads section is not the preflight checklist."""
    m = _publish(tmp_path, game, latest=ver.VERSION, modules={
        "movies-hd": {"movies/hd/opening.mp4": b"fake clip data"},
    })
    rcode, out = _run("--modules", "movies-hd", "--manifest", str(m), game=game,
                      env_extra={"LONGEVITY_TRUST_KEY": PK_HEX})
    assert "INSTALLATION SUCCESSFUL" in out, out
    assert "--- downloads ---" in out and "[ok  ]" not in out, out
    assert (game / "movies" / "hd" / "opening.mp4").read_bytes() == b"fake clip data"
    state = rc.read(game)
    assert rc.module_version(state, "movies-hd") == ver.VERSION
    assert rc.module_version(state, "base") == ver.VERSION
    assert _uimod_flag(game) == "1"
    rows = [l for l in out.split("\n") if l.startswith("  HD Cinematics")]
    assert rows and rows[-1].split()[-1] == "Success", rows
    lines = out.split("\n")
    assert not any(l.startswith("  recorded") for l in lines), "no bookkeeping row"
    assert not any(l.startswith("  terranx.exe ") for l in lines), "no row for an exe the mod does not touch"


def test_a_pack_that_cannot_be_downloaded_leaves_a_partly_complete_install(game, tmp_path):
    """The game is patched and playable; the pack is not; the verdict and the exit code say
    exactly that (the same shape as do_update's partial outcome), and nothing claims the pack."""
    m = _publish(tmp_path, game, latest=ver.VERSION, modules={
        "movies-hd": {"movies/hd/opening.mp4": b"fake clip data"},
    })
    (tmp_path / "published" / f"movies-hd-{ver.VERSION}.zip").unlink()
    rcode, out = _run("--modules", "movies-hd", "--manifest", str(m), game=game,
                      env_extra={"LONGEVITY_TRUST_KEY": PK_HEX}, expect_ok=False)
    assert rcode == ix.EXIT_ERROR, out
    assert "INSTALLATION PARTLY COMPLETE" in out and "INSTALLATION SUCCESSFUL" not in out, out
    assert "ready to play" in out
    table = ap.load_targets(PATCHES)
    assert hashlib.md5((game / "terranx_PRACX.exe").read_bytes()).hexdigest() \
        == table["pracx"].patched_md5
    state = rc.read(game)
    assert rc.module_version(state, "base") == ver.VERSION
    assert "movies-hd" not in (state.get("modules") or {})
    rows = [l for l in out.split("\n") if l.startswith("  HD Cinematics")]
    assert rows and rows[-1].split()[-1] == "Error", rows


def test_content_left_on_disk_is_not_recorded_as_an_installed_pack(game):
    """An uninstall leaves movies\\hd behind. A re-install must not record that folder as the
    current pack (it would hide the pack from the update prompt for good); it only turns the
    cinematics flag on so the clips that are there play."""
    (game / "movies" / "hd").mkdir(parents=True)
    (game / "movies" / "hd" / "stray.mp4").write_bytes(b"x")
    rcode, out = _run("--ai", "off", game=game)
    assert "INSTALLATION SUCCESSFUL" in out, out
    assert "movies-hd" not in (rc.read(game).get("modules") or {})
    assert _uimod_flag(game) == "1"


# ---------------------------------------------------------------- PRACX + Thinker (2026-10-28)

def _ac_key(game: Path, key: str):
    """One `[Alpha Centauri]` value as the file holds it; None when the key is absent."""
    sect = None
    for line in (game / "Alpha Centauri.ini").read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            sect = s[1:-1].strip().lower()
            continue
        if sect == "alpha centauri" and "=" in s:
            k, v = s.split("=", 1)
            if k.strip().lower() == key.lower():
                return v.strip()
    return None


@pytest.fixture
def thinker_game(tmp_path, bak_path):
    """A Thinker folder: the clean PRACX base under the name Thinker's launcher starts, with thinker.dll
    and thinker.exe beside it (detection is by presence; their bytes are never read)."""
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx.exe")
    (g / "thinker.dll").write_bytes(b"not a real dll")
    (g / "thinker.exe").write_bytes(b"not a real exe")
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    return g


def test_a_thinker_folder_installs_the_pracx_thinker_overlay(thinker_game):
    """thinker.dll beside the exe selects target pracx_thinker: the same patch set minus the four sites
    Thinker's launch-time guards would reject (its own lock), the receipt says so, and the play note
    points at Thinker's launcher instead of calling terranx.exe "the unmodified game"."""
    g = thinker_game
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out, out
    table = ap.load_targets(PATCHES)
    assert "PRACX + Thinker configuration" in out
    assert hashlib.md5((g / "terranx.exe").read_bytes()).hexdigest() == table["pracx_thinker"].patched_md5
    assert hashlib.md5((g / "terranx.exe.bak").read_bytes()).hexdigest() == table["pracx_thinker"].base_md5
    assert rc.ini_get(g, rc.KEY_TARGET) == "pracx_thinker"
    assert "start thinker.exe" in out, out
    assert "without Thinker" in out
    assert "start the unmodified game" not in out
    assert (g / "uimod.dll").is_file()


def test_the_same_base_without_thinker_files_is_plain_pracx(tmp_path, bak_path):
    """The negative of the test above: the PRACX base named terranx.exe with nothing beside it is pracx."""
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx.exe")
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out, out
    assert "PRACX + Thinker" not in out
    assert hashlib.md5((g / "terranx.exe").read_bytes()).hexdigest() == ap.load_targets(PATCHES)["pracx"].patched_md5
    assert rc.ini_get(g, rc.KEY_TARGET) == "pracx"


def test_install_blanks_thinkers_movie_player_key_silently(game):
    """Movie ownership decision A2 (user 2026-10-28): every install run writes MoviePlayerPath= (blank), so
    Thinker routes every movie to the mod's in-process player; an auto-detected VLC path goes, the player's
    other keys stay, and nothing is said about it. Written whether or not Thinker is present."""
    (game / "Alpha Centauri.ini").write_text(
        "[Alpha Centauri]\nMoviePlayerPath=C:\\Program Files\\VideoLAN\\VLC\\vlc.exe\n"
        "MoviePlayerArgs=--fullscreen --play-and-exit\nMovieExtension=mp4\n[UIMod]\n", encoding="ascii")
    rcode, out = _run("--ai", "off", game=game)
    assert "INSTALLATION SUCCESSFUL" in out, out
    assert _ac_key(game, "MoviePlayerPath") == ""
    assert _ac_key(game, "MoviePlayerArgs") == "--fullscreen --play-and-exit"
    assert _ac_key(game, "MovieExtension") == "mp4"
    assert "MoviePlayerPath" not in out, "the override is silent by decision"


def test_uninstall_deletes_the_blank_movie_key_so_thinker_redetects(game_installed):
    """After uninstall the key is ABSENT (not blank): Thinker treats a blank as the explicit in-game
    player forever, while an absent key makes it re-run its own VLC scan / prompt on the next launch."""
    g = game_installed
    assert _ac_key(g, "MoviePlayerPath") == "", "the installed template should carry the blank"
    _run("--uninstall", game=g)
    assert _ac_key(g, "MoviePlayerPath") is None


def test_uninstall_leaves_a_movie_key_the_player_changed(game_installed):
    g = game_installed
    ini = g / "Alpha Centauri.ini"
    ini.write_text(ini.read_text(encoding="utf-8", errors="replace").replace(
        "MoviePlayerPath=", "MoviePlayerPath=C:\\Tools\\mpv.exe", 1), encoding="utf-8")
    assert _ac_key(g, "MoviePlayerPath") == "C:\\Tools\\mpv.exe"
    _run("--uninstall", game=g)
    assert _ac_key(g, "MoviePlayerPath") == "C:\\Tools\\mpv.exe", "a value the player set since must survive"



# ---------------------------------------------------------------- audit 2026-10-28: overlay by exe name, target flips

def test_an_unrecognised_terranx_beside_thinker_is_swapped_out_and_kept(tmp_path, bak_path):
    """A Thinker folder whose terranx.exe is something the installer does not know (not GOG's, not
    PRACX), the PRACX exe as terranx_PRACX.exe. Thinker's launcher starts terranx.exe only, so the
    set-up swaps it for the PRACX build without asking (user 2026-11-06), keeps the unknown file
    under a hashed _original name, says so in one line, and --uninstall puts it back. (Until
    2026-11-06 this case was left alone and the player got the plain PRACX build, which Thinker
    never loads.)"""
    g = tmp_path / "game"
    g.mkdir()
    own = b"NOT THE PRACX BASE: a stock exe the installer does not know"
    (g / "terranx.exe").write_bytes(own)
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    (g / "thinker.dll").write_bytes(b"not a real dll")
    (g / "thinker.exe").write_bytes(b"not a real exe")
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    own_md5 = hashlib.md5(own).hexdigest()
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out, out
    table = ap.load_targets(PATCHES)
    assert _md5(g / "terranx.exe") == table["pracx_thinker"].patched_md5
    assert _md5(g / "terranx_PRACX.exe") == table["pracx"].base_md5, "left as it is"
    assert _md5(g / "terranx_original.exe") == own_md5
    assert rc.ini_get(g, rc.KEY_TARGET) == "pracx_thinker"
    assert ("Swapped the terranx.exe that was here for the PRACX .exe. This is required to load both Longevity and "
            "Thinker. Your original is kept as terranx_original.exe. Uninstalling Longevity Vaccine puts it back.") in out, out
    assert "Thinker starts only" not in out and "Set this folder up" not in out, out
    assert "start thinker.exe" in out, out
    rcode, out = _run("--uninstall", game=g)
    assert "UNINSTALL COMPLETE" in out and _md5(g / "terranx.exe") == own_md5, out
    assert not (g / "terranx_original.exe").exists()


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def test_adding_thinker_after_a_pracx_install_re_patches_for_thinker(tmp_path, bak_path):
    """Install plain PRACX as terranx.exe, then drop Thinker beside it and re-run: the exe must become
    the Thinker build (Thinker's launch guard refuses the plain one), not be left alone as "already
    patched" while the receipt and the play note switch (audit 2026-10-28, reproduced)."""
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx.exe")
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    table = ap.load_targets(PATCHES)
    rcode, out = _run("--ai", "off", game=g)
    assert _md5(g / "terranx.exe") == table["pracx"].patched_md5
    assert rc.ini_get(g, rc.KEY_TARGET) == "pracx"

    (g / "thinker.dll").write_bytes(b"not a real dll")
    (g / "thinker.exe").write_bytes(b"not a real exe")
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out, out
    assert "not the build this installer produces" in out, out
    assert _md5(g / "terranx.exe") == table["pracx_thinker"].patched_md5, "the exe keeps the plain build"
    assert _md5(g / "terranx.exe.bak") == table["pracx_thinker"].base_md5
    assert rc.ini_get(g, rc.KEY_TARGET) == "pracx_thinker"
    assert "start thinker.exe" in out, out

    # and back: Thinker removed -> the plain build again
    (g / "thinker.dll").unlink()
    (g / "thinker.exe").unlink()
    rcode, out = _run("--ai", "off", game=g)
    assert _md5(g / "terranx.exe") == table["pracx"].patched_md5, "the exe keeps the Thinker build"
    assert rc.ini_get(g, rc.KEY_TARGET) == "pracx"

    # a plain re-run with nothing changed is still a no-op
    rcode, out = _run("--ai", "off", game=g)
    assert "already patched" in out, out


# ---------------------------------------------------------------- audit round 2 (2026-10-29)

def test_a_hand_modified_exe_is_kept_beside_when_re_patched(tmp_path, bak_path):
    """The re-patch-on-mismatch path must never destroy bytes it does not understand: a player's own
    edit (or another tool's work) on top of our build is copied beside the exe, named by its hash,
    before the backup is restored and the fresh build written."""
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx.exe")
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    _run("--ai", "off", game=g)
    exe = g / "terranx.exe"
    data = bytearray(exe.read_bytes())
    data[0x1000] ^= 0xFF
    exe.write_bytes(bytes(data))
    modified = hashlib.md5(bytes(data)).hexdigest()
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out, out
    table = ap.load_targets(PATCHES)
    assert _md5(exe) == table["pracx"].patched_md5
    kept = g / f"terranx.exe.replaced-{modified[:8]}"
    assert kept.is_file() and _md5(kept) == modified, "the replaced bytes were not kept"
    assert "kept as" in out, out
    assert _md5(g / "terranx.exe.bak") == table["pracx"].base_md5, ".bak must stay the clean base"


def test_a_thinker_folder_that_keeps_a_second_pracx_exe_records_the_thinker_configuration(tmp_path, bak_path):
    """terranx.exe (PRACX, for thinker.exe) beside terranx_PRACX.exe (PRACX too) and Thinker: both are
    patched, each for its own configuration, and the receipt, play note and launcher follow the exe
    Thinker runs -- whatever the candidate order on this machine. No note claims the folder needs a
    rename, since terranx.exe is PRACX already."""
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx.exe")
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    (g / "thinker.dll").write_bytes(b"not a real dll")
    (g / "thinker.exe").write_bytes(b"not a real exe")
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out, out
    table = ap.load_targets(PATCHES)
    assert _md5(g / "terranx.exe") == table["pracx_thinker"].patched_md5
    assert _md5(g / "terranx_PRACX.exe") == table["pracx"].patched_md5
    assert rc.ini_get(g, rc.KEY_TARGET) == "pracx_thinker"
    assert "start thinker.exe" in out, out
    assert "Thinker starts only" not in out, out


def test_a_plain_pracx_exe_named_terranx_is_not_called_unmodified(tmp_path, bak_path):
    """A PRACX exe named terranx.exe with no Thinker beside it is a plain install whose play note must
    not say in the next line that terranx.exe starts the unmodified game."""
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx.exe")
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    rcode, out = _run("--ai", "off", game=g)
    assert "To play with the mod, start terranx.exe." in out, out
    assert "terranx.exe and terran.exe all start" not in out, out
    assert "terran.exe" in out and "unmodified game" in out, out


# ---------------------------------------------------------------- setting a folder up for Thinker

def _thinker_folder(tmp_path, bak_path, original: bytes = None) -> Path:
    """The stock GOG layout with Thinker dropped in: `original` as terranx.exe (None: no
    terranx.exe at all), the clean PRACX build as terranx_PRACX.exe, thinker.dll / thinker.exe."""
    g = tmp_path / "game"
    g.mkdir()
    if original is not None:
        (g / "terranx.exe").write_bytes(original)
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    (g / "thinker.dll").write_bytes(b"not a real dll")
    (g / "thinker.exe").write_bytes(b"not a real exe")
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    return g


def test_a_stock_thinker_folder_is_set_up_and_uninstall_puts_the_original_back(tmp_path, bak_path,
                                                                              pristine_bytes):
    """The stock GOG terranx.exe (the original game, no PRACX) with Thinker beside it: the
    installer keeps the original as terranx_original.exe, puts the PRACX build in its place and
    patches it as PRACX + Thinker; terranx_PRACX.exe is left as it is. A re-run neither asks nor
    backs anything up again; --uninstall puts the original back and leaves nothing of the set-up."""
    g = _thinker_folder(tmp_path, bak_path, pristine_bytes)
    table = ap.load_targets(PATCHES)
    vanilla, base = _md5(g / "terranx.exe"), table["pracx"].base_md5
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out, out
    # no question, one line (user 2026-11-06)
    assert ("Swapped the vanilla Alien Crossfire .exe for the PRACX .exe. This is required to load both Longevity and "
            "Thinker. Your original is kept as terranx_original.exe. Uninstalling Longevity Vaccine puts it back.") in out, out
    assert _md5(g / "terranx_original.exe") == vanilla
    assert _md5(g / "terranx.exe") == table["pracx_thinker"].patched_md5
    assert _md5(g / "terranx.exe.bak") == base
    assert _md5(g / "terranx_PRACX.exe") == base and not (g / "terranx_PRACX.exe.bak").exists()
    assert rc.ini_get(g, rc.KEY_TARGET) == "pracx_thinker"
    # the set-up explains nothing; the patch pass adds no "rename it" note either
    assert "start thinker.exe" in out and "Thinker starts only" not in out and "Set this folder up" not in out, out
    assert not list(g.glob("*.longevity-tmp"))

    rcode, out = _run("--ai", "off", game=g)
    assert "--- Thinker ---" not in out and "already patched" in out, out
    assert sorted(p.name for p in g.glob("terranx_original*")) == ["terranx_original.exe"]

    rcode, out = _run("--uninstall", game=g)
    assert "UNINSTALL COMPLETE" in out and "put the original terranx.exe back" in out, out
    assert _md5(g / "terranx.exe") == vanilla
    assert not (g / "terranx_original.exe").exists() and not (g / "terranx.exe.bak").exists()
    assert _md5(g / "terranx_PRACX.exe") == base
    assert not (g / "longevity-thinker-setup.json").exists()


def test_a_foreign_terranx_backup_fails_the_install_before_anything_is_patched(tmp_path, bak_path, pristine_bytes):
    """User 2026-11-05: a terranx.exe.bak nobody can vouch for stops the WHOLE install, in red, with
    the user's wording, and the folder is byte-for-byte untouched -- terranx_PRACX.exe included,
    which a plain install would otherwise have patched."""
    g = _thinker_folder(tmp_path, bak_path, pristine_bytes)
    (g / "terranx.exe.bak").write_bytes(b"MZ another tool's backup")
    before = _tree(g)
    rcode, out = _run("--ai", "off", game=g, expect_ok=False)
    assert rcode == ix.EXIT_ABORTED, out
    assert "INSTALLATION FAILED" in out, out
    assert ("Your game installation folder has an unrecognized terranx.exe.bak file. This should only happen if "
            "you edited that file by hand. Longevity Vaccine cannot install over it. To install, verify that you "
            "do not need terranx.exe.bak and delete it, then re-run this installer. Your game was not modified.") in out, out
    assert "Nothing on disk was changed" not in out and "What to do" not in out, out
    assert "--- terranx" not in out and "patching" not in out, out
    assert _tree(g) == before, "nothing may be written before the check"


def test_a_foreign_backup_in_a_plain_folder_fails_the_install_the_same_way(game, pristine_bytes):
    """The backup rule for every exe the pass patches (user 2026-11-06): the same refusal for
    terranx_PRACX.exe.bak in a folder without Thinker, before anything is written."""
    g = game
    (g / "terranx_PRACX.exe.bak").write_bytes(b"MZ another tool's backup")
    before = _tree(g)
    rcode, out = _run("--ai", "off", game=g, expect_ok=False)
    assert rcode == ix.EXIT_ABORTED and "INSTALLATION FAILED" in out, out
    assert ("Your game installation folder has an unrecognized terranx_PRACX.exe.bak file. This should only happen if "
            "you edited that file by hand. Longevity Vaccine cannot install over it. To install, verify that you "
            "do not need terranx_PRACX.exe.bak and delete it, then re-run this installer. Your game was not modified.") in out, out
    assert "Nothing on disk was changed" not in out and "patching" not in out, out
    assert _tree(g) == before


def test_gogs_original_under_the_plain_exes_backup_name_is_set_aside_and_the_install_goes_on(game, pristine_bytes):
    """GOG's stock terranx.exe sitting as terranx_PRACX.exe.bak (an old tool's backup): kept as
    terranx_original.exe, the pass writes its own clean-base .bak, re-run and --uninstall work."""
    g = game
    (g / "terranx_PRACX.exe.bak").write_bytes(pristine_bytes)
    gog = hashlib.md5(pristine_bytes).hexdigest()
    table = ap.load_targets(PATCHES)
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out, out
    assert "terranx_PRACX.exe.bak (GOG's original) is kept as terranx_original.exe" in out, out
    assert _md5(g / "terranx_original.exe") == gog
    assert _md5(g / "terranx_PRACX.exe") == table["pracx"].patched_md5
    assert _md5(g / "terranx_PRACX.exe.bak") == table["pracx"].base_md5, "the pass's own backup, not the GOG copy"
    rcode, out = _run("--ai", "off", game=g)
    assert "already patched" in out and "GOG's original" not in out, out
    rcode, out = _run("--uninstall", game=g)
    assert "UNINSTALL COMPLETE" in out and _md5(g / "terranx_PRACX.exe") == table["pracx"].base_md5, out
    assert _md5(g / "terranx_original.exe") == gog, "a kept file is never the uninstall's to remove"


def test_thinker_removed_with_the_kept_original_gone_still_gets_a_clean_backup(tmp_path, bak_path, pristine_bytes):
    """Audit HIGH-2: Thinker removed after a set-up AND the kept original gone: the revert leaves
    terranx.exe the clean PRACX copy, which the pass then patches -- its GOG-original .bak (the
    dev harness's layout) is set aside first, so the pass writes a clean-base .bak and the next
    run recognises the build."""
    g = _thinker_folder(tmp_path, bak_path, pristine_bytes)
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out, out
    (g / "thinker.dll").unlink()
    (g / "thinker.exe").unlink()
    (g / "terranx_original.exe").unlink()
    (g / "terranx.exe.bak").write_bytes(pristine_bytes)                # GOG's copy under the pass's name
    gog = hashlib.md5(pristine_bytes).hexdigest()
    table = ap.load_targets(PATCHES)
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out and "Thinker is no longer in this folder" in out, out
    assert _md5(g / "terranx.exe") == table["pracx"].patched_md5, "the plain build now"
    assert _md5(g / "terranx.exe.bak") == table["pracx"].base_md5, "the pass's own backup, not the GOG copy"
    assert gog in {_md5(p) for p in g.glob("terranx_original*")}, "GOG's copy kept"
    rcode, out = _run("--ai", "off", game=g)
    assert "already patched" in out, out


def test_a_terranx_replaced_after_the_set_up_fails_the_install_before_anything_is_patched(tmp_path, bak_path,
                                                                                         pristine_bytes):
    """User 2026-11-06: a Thinker player asked for Thinker. With terranx.exe neither the file the
    set-up put there nor the original it kept, the install stops in red with nothing written --
    it used to install the plain build beside it with a note."""
    g = _thinker_folder(tmp_path, bak_path, pristine_bytes)
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out, out
    (g / "terranx.exe.bak").unlink()
    (g / "terranx.exe").write_bytes(b"MZ the player's own build")
    before = _tree(g)
    rcode, out = _run("--ai", "off", game=g, expect_ok=False)
    assert rcode == ix.EXIT_ABORTED and "INSTALLATION FAILED" in out, out
    assert ("Your game installation folder was set up for Thinker by an earlier Longevity Vaccine install, but its "
            "terranx.exe is no longer the file that install put there, and it is not the original that install kept "
            "as terranx_original.exe. This should only happen if you replaced that file by hand. Longevity Vaccine "
            "cannot install over it. To install, verify that you do not need the current terranx.exe and delete it, "
            "then re-run this installer. Your game was not modified.") in out, out
    assert "Thinker will not load" not in out and "patching" not in out and "Nothing on disk was changed" not in out, out
    assert _tree(g) == before, "nothing may be written before the check"
    assert "INSTALLATION FAILED" in _run("--ai", "off", game=g, expect_ok=False)[1], "a re-run is refused the same way"
    # the remedy works end to end: the file gone, the set-up puts PRACX in place and patches it
    (g / "terranx.exe").unlink()
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out and "Your original is kept as terranx_original.exe" in out, out
    table = ap.load_targets(PATCHES)
    assert _md5(g / "terranx.exe") == table["pracx_thinker"].patched_md5
    rcode, out = _run("--uninstall", game=g)
    assert "UNINSTALL COMPLETE" in out and _md5(g / "terranx.exe") == hashlib.md5(pristine_bytes).hexdigest(), out


def test_a_gog_original_terranx_backup_is_accepted_by_the_set_up(tmp_path, bak_path, pristine_bytes):
    """A spare copy of GOG's original under terranx.exe.bak (an old tool's backup, or the dev
    harness) is accepted without a word: the set-up keeps the original as terranx_original.exe,
    the duplicate goes, and the patch pass writes its own clean-base .bak under that name."""
    g = _thinker_folder(tmp_path, bak_path, pristine_bytes)
    (g / "terranx.exe.bak").write_bytes(pristine_bytes)
    table = ap.load_targets(PATCHES)
    vanilla, base = _md5(g / "terranx.exe"), table["pracx"].base_md5
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out and "Your original is kept as terranx_original.exe." in out, out
    # accepted without a word: no refusal, and no "kept as" line for the spare it dropped
    assert "unrecognized" not in out and "did not make" not in out and "GOG's original" not in out, out
    assert _md5(g / "terranx_original.exe") == vanilla
    assert _md5(g / "terranx.exe") == table["pracx_thinker"].patched_md5
    assert _md5(g / "terranx.exe.bak") == base, "the set-up's own backup, not the GOG copy"
    rcode, out = _run("--ai", "off", game=g)
    assert "already patched" in out and "--- Thinker ---" not in out, out
    rcode, out = _run("--uninstall", game=g)
    assert "UNINSTALL COMPLETE" in out and _md5(g / "terranx.exe") == vanilla, out
    assert not (g / "terranx_original.exe").exists() and not (g / "terranx.exe.bak").exists()


def test_a_thinker_folder_with_no_terranx_gets_one_and_uninstall_removes_it(tmp_path, bak_path):
    g = _thinker_folder(tmp_path, bak_path, None)
    table = ap.load_targets(PATCHES)
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out, out
    assert ("Put the PRACX .exe in place as terranx.exe. This is required to load both Longevity and Thinker. "
            "Uninstalling Longevity Vaccine removes it again.") in out, out
    assert _md5(g / "terranx.exe") == table["pracx_thinker"].patched_md5
    assert not list(g.glob("terranx_original*"))
    rcode, out = _run("--uninstall", game=g)
    assert "UNINSTALL COMPLETE" in out, out
    assert not (g / "terranx.exe").exists() and not (g / "terranx.exe.bak").exists()
    assert _md5(g / "terranx_PRACX.exe") == table["pracx"].base_md5


def test_gog_restoring_the_original_then_update_and_uninstall_lose_nothing(tmp_path, bak_path,
                                                                         pristine_bytes):
    """GOG Galaxy's "verify files" writes the original terranx.exe back over a set-up folder. The
    game's update then stops with what to do (not "a binary we did not make"), and --uninstall
    keeps that original -- its generic restore used to copy our PRACX .bak over it, destroying the
    only copy left once the kept duplicate was gone (audit 2026-11-01, blocker)."""
    g = _thinker_folder(tmp_path, bak_path, pristine_bytes)
    vanilla = _md5(g / "terranx.exe")
    _run("--ai", "off", game=g)
    (g / "terranx.exe").write_bytes(pristine_bytes)                    # GOG's verify
    (g / "terranx_original.exe").unlink()                              # and the player tidied up
    m = _publish(tmp_path, g, latest=ver.VERSION, modules={})
    rcode, out = _run("--update", "--manifest", str(m), "--no-prompt", game=g, expect_ok=False,
                      env_extra={"LONGEVITY_TRUST_KEY": PK_HEX})
    assert rcode == ix.EXIT_ABORTED and "original terranx.exe is back" in out, out
    assert _md5(g / "terranx.exe") == vanilla
    rcode, out = _run("--uninstall", game=g)
    assert "UNINSTALL COMPLETE" in out, out
    assert _md5(g / "terranx.exe") == vanilla, "the original was overwritten"
    assert not (g / "terranx.exe.bak").exists() and not (g / "longevity-thinker-setup.json").exists()


def test_thinker_removed_after_the_set_up_returns_the_folder_to_plain_pracx(tmp_path, bak_path,
                                                                          pristine_bytes):
    g = _thinker_folder(tmp_path, bak_path, pristine_bytes)
    vanilla = _md5(g / "terranx.exe")
    table = ap.load_targets(PATCHES)
    _run("--ai", "off", game=g)
    (g / "thinker.dll").unlink()
    (g / "thinker.exe").unlink()
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out and "no longer in this folder" in out, out
    assert _md5(g / "terranx.exe") == vanilla and not (g / "terranx_original.exe").exists()
    assert _md5(g / "terranx_PRACX.exe") == table["pracx"].patched_md5
    assert rc.ini_get(g, rc.KEY_TARGET) == "pracx" and "start terranx_PRACX.exe" in out, out


def test_a_plain_install_then_thinker_leaves_one_patched_exe(tmp_path, bak_path, pristine_bytes):
    """An earlier plain install patched terranx_PRACX.exe; Thinker added, the set-up puts it back
    to the clean build, so no second patched copy is left to go stale."""
    g = _thinker_folder(tmp_path, bak_path, pristine_bytes)
    (g / "thinker.dll").rename(g / "thinker.dll.off")
    table = ap.load_targets(PATCHES)
    _run("--ai", "off", game=g)
    assert _md5(g / "terranx_PRACX.exe") == table["pracx"].patched_md5
    (g / "thinker.dll.off").rename(g / "thinker.dll")
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out, out
    assert _md5(g / "terranx.exe") == table["pracx_thinker"].patched_md5
    assert _md5(g / "terranx_PRACX.exe") == table["pracx"].base_md5, out
    assert rc.ini_get(g, rc.KEY_TARGET) == "pracx_thinker"


def test_an_earlier_releases_build_is_brought_up_to_date_and_uninstalls(tmp_path, bak_path,
                                                                       pristine_bytes):
    """Every release has its own patched hash: the build a set-up folder holds from an earlier
    release is still recognised as ours (re-audit: it was "not recognised", the set-up dropped and
    the old build left running against the new uimod.dll)."""
    g = _thinker_folder(tmp_path, bak_path, pristine_bytes)
    vanilla = _md5(g / "terranx.exe")
    table = ap.load_targets(PATCHES)
    _run("--ai", "off", game=g)
    data = bytearray((g / "terranx.exe").read_bytes())
    data[0x2000] ^= 0xFF                                               # "an earlier release"
    (g / "terranx.exe").write_bytes(bytes(data))
    rcode, out = _run("--ai", "off", game=g)
    assert "INSTALLATION SUCCESSFUL" in out and "--- Thinker ---" not in out, out
    assert _md5(g / "terranx.exe") == table["pracx_thinker"].patched_md5
    assert _md5(g / "terranx_PRACX.exe") == table["pracx"].base_md5
    assert rc.ini_get(g, rc.KEY_TARGET) == "pracx_thinker" and "start thinker.exe" in out
    (g / "terranx.exe").write_bytes(bytes(data))
    rcode, out = _run("--uninstall", game=g)
    assert "UNINSTALL COMPLETE" in out, out
    assert _md5(g / "terranx.exe") == vanilla


def test_an_exe_the_uninstall_must_leave_makes_it_incomplete(tmp_path, bak_path, pristine_bytes):
    g = _thinker_folder(tmp_path, bak_path, pristine_bytes)
    _run("--ai", "off", game=g)
    (g / "terranx.exe.bak").unlink()
    (g / "terranx.exe").write_bytes(b"MZ the player's own")
    rcode, out = _run("--uninstall", game=g)
    assert "UNINSTALL INCOMPLETE" in out and "terranx.exe was left as it is" in out, out
    assert (g / "terranx.exe").read_bytes() == b"MZ the player's own"
    assert (g / "terranx_original.exe").is_file()


def test_our_build_without_its_backup_never_blocks_uninstall_or_install(tmp_path, bak_path,
                                                                       pristine_bytes):
    """This release's build with its terranx.exe.bak gone: known by its hash, it is restored from the
    folder's other clean PRACX copy and the original goes back -- never "could not restore ... try
    again" on every run (audit 3 #1), never "left as it is" for our own build (audit 4 #1); with
    Thinker removed the install does the same."""
    g = _thinker_folder(tmp_path, bak_path, pristine_bytes)
    vanilla = _md5(g / "terranx.exe")
    _run("--ai", "off", game=g)
    (g / "terranx.exe.bak").unlink()
    rcode, out = _run("--uninstall", game=g)
    assert "UNINSTALL COMPLETE" in out and "Could not restore" not in out, out
    assert _md5(g / "terranx.exe") == vanilla and not (g / "terranx_original.exe").exists()

    (tmp_path / "second").mkdir()
    g2 = _thinker_folder(tmp_path / "second", bak_path, pristine_bytes)
    _run("--ai", "off", game=g2)
    (g2 / "terranx.exe.bak").unlink()
    (g2 / "thinker.dll").unlink()
    rcode, out = _run("--ai", "off", game=g2)
    assert "INSTALLATION SUCCESSFUL" in out and "Could not restore" not in out, out
    assert _md5(g2 / "terranx.exe") == vanilla and "start terranx_PRACX.exe" in out, out


@pytest.mark.parametrize("junk", ["{not json", "[]"])
def test_an_unreadable_set_up_record_is_no_uninstall(tmp_path, bak_path, pristine_bytes, junk):
    """An unreadable record describes nothing: the uninstall removes it and is still the honest
    "Nothing to uninstall" (audit 5 #1: it reported UNINSTALL COMPLETE on every run)."""
    g = _thinker_folder(tmp_path, bak_path, pristine_bytes)
    (g / "longevity-thinker-setup.json").write_text(junk, encoding="utf-8")
    rcode, out = _run("--uninstall", game=g, expect_ok=False)
    assert "Nothing to uninstall" in out and "UNINSTALL COMPLETE" not in out, out
    assert not (g / "longevity-thinker-setup.json").exists()


# ---------------------------------------------------------------- a REAL earlier release's build

#: The commit 0.1.0 was cut from (dist\release\0.1.0\release-log.json) and what it shipped for
#: `pracx` (its signed manifest's `targets`).
RELEASE_010 = ("c50e7bcdd9174dbc208811dc03978172723c6f3e", "ed30ac8bc96b6f30dc1ba4e1461b97bd")


def test_the_in_game_update_from_a_real_0_1_0_build_is_not_refused(game, tmp_path, bak_path):
    """patched_md5 changes with every release; the build 0.1.0 left on a player's disk is ours by
    the target's known_patched history, so the update goes through -- it was refused as "a binary
    we did not make" (audit 2026-11-01) -- and a fresh install over it keeps no .replaced copy.

    0.1.0's actual pracx build is made here by 0.1.0's OWN patcher from its release commit (~3 s of
    the test's ~10; not conftest's baked_exe, which is THIS release's build)."""
    import io
    import tarfile
    commit, want = RELEASE_010
    try:
        tar = subprocess.run(["git", "-C", str(_REPO), "archive", "--format=tar", commit,
                              "work/scripts", "work/patches"], capture_output=True)
    except FileNotFoundError:
        pytest.skip("no git on PATH")
    if tar.returncode != 0:
        pytest.skip(f"0.1.0's sources ({commit[:8]}) are not in this checkout's history")
    old = tmp_path / "rel010"
    with tarfile.open(fileobj=io.BytesIO(tar.stdout)) as t:
        t.extractall(old / "src", filter="data")
    exe = old / "terranx_PRACX.exe"
    shutil.copy2(bak_path, exe)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["SMACX_GAME_DIR"] = str(old / "no-game")         # its config must never find a real game
    scripts = old / "src" / "work" / "scripts"
    p = subprocess.run([sys.executable, str(scripts / "apply_patches.py"), "--target", str(exe),
                        "--patches", str(old / "src" / "work" / "patches" / "patches.yaml"),
                        "--apply", "--target-id", "pracx"],
                       cwd=scripts, capture_output=True, text=True, env=env, timeout=300,
                       stdin=subprocess.DEVNULL)
    build_010 = exe.read_bytes()
    assert hashlib.md5(build_010).hexdigest() == want, p.stdout[-2000:] + p.stderr[-2000:]

    table = ap.load_targets(PATCHES)
    (game / "terranx_PRACX.exe.bak").write_bytes((game / "terranx_PRACX.exe").read_bytes())
    (game / "terranx_PRACX.exe").write_bytes(build_010)
    rc.write(game, target_id="pracx", modules={"base": {"version": "0.1.0"}}, say=lambda *a: None)
    m = _publish(tmp_path, game, latest=ver.VERSION, modules={})
    rcode, out = _run("--update", "--manifest", str(m), "--no-prompt", game=game,
                      env_extra={"LONGEVITY_TRUST_KEY": PK_HEX})
    assert "UPDATE COMPLETE" in out and "did not make" not in out, out
    assert _md5(game / "terranx_PRACX.exe") == table["pracx"].patched_md5

    (game / "terranx_PRACX.exe").write_bytes(build_010)
    rcode, out = _run("--ai", "off", game=game)
    assert "INSTALLATION SUCCESSFUL" in out, out
    assert _md5(game / "terranx_PRACX.exe") == table["pracx"].patched_md5
    assert not list(game.glob("*.replaced-*")), "our own earlier build was kept as a stranger's"


def test_a_locked_terranx_fails_the_set_up_with_nothing_changed(tmp_path, bak_path, pristine_bytes):
    """terranx.exe held open without delete sharing (another program reading it) -- the rename
    fails, and the installer stops before patching with every file as it was. (A RUNNING exe can be
    renamed on Windows; the set-up then simply completes, and the patch pass is what reports the
    game still running.)"""
    g = _thinker_folder(tmp_path, bak_path, pristine_bytes)
    before = _tree(g)
    with open(g / "terranx.exe", "rb"):
        rcode, out = _run("--ai", "off", game=g, expect_ok=False)
    assert rcode == ix.EXIT_ABORTED, out
    assert "could not be set up for Thinker" in out and "Nothing on disk was changed" in out, out
    assert _tree(g) == before
