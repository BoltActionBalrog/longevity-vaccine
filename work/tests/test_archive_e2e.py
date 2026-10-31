"""The archive a player actually receives: build it, extract it, run INSTALL.bat.

WHY THIS EXISTS. Everything else runs the CHECKOUT's `install.py`: test_install_e2e points it at a
hand-built flat payload with the trimmed runtime (LONGEVITY_PAYLOAD_ROOT), so the payload SHAPE is
the player's, but nothing there was produced by release.py. That leaves the shipped artifact itself
untested: the archive layout, the synthesised INSTALL.bat, the launcher's relative paths, and
whether the trimmed interpreter inside the zip can run at all. The archive layout is NOT the
checkout layout -- a payload is flat (`scripts\\`, `patches\\`) while a checkout keeps those under
`work\\` -- so "it works from the repo" says nothing about what a tester will double-click.

This is the only test that exercises the thing we hand people.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent.parent
_SCRIPTS = _REPO / "work" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import apply_patches as ap    # noqa: E402
import config                 # noqa: E402
import receipt as rc          # noqa: E402
import release as rel         # noqa: E402
import version as ver         # noqa: E402

_PY = _REPO / "tools" / "python" / "python.exe"

pytestmark = pytest.mark.skipif(not _PY.exists(), reason="bundled interpreter not present")


@pytest.fixture(scope="module")
def extracted(tmp_path_factory) -> Path:
    """A real release archive, built and unpacked. Shared: building it is not cheap."""
    if not (rel.RUNTIME_DIR / "python.exe").is_file():
        pytest.skip("no staged runtime; run build_runtime.py first")
    if not (rel.RUNTIME38_DIR / "python.exe").is_file():
        pytest.skip("runtime38 not staged (fetch_python38.py + build_runtime.py); release.py requires both")
    out = tmp_path_factory.mktemp("rel")
    p = subprocess.run([str(_PY), str(_SCRIPTS / "release.py"), "--skip-gate",
                        "--modules", "base", "--out", str(out)],
                       capture_output=True, text=True, timeout=1800)
    assert p.returncode == 0, p.stdout + p.stderr
    archive = out / ver.VERSION / rel.archive_name("base", ver.VERSION)
    assert archive.is_file(), f"no archive at {archive}"
    dest = out / "x"
    with zipfile.ZipFile(archive) as z:
        z.extractall(dest)
    return dest


def test_the_archive_has_the_shipped_layout_and_no_work_folder(extracted):
    """`work` is a checkout's folder -- it holds tests, screenshots and notes. It means nothing
    to a player and must not reach the archive."""
    assert (extracted / "INSTALL.bat").is_file(), "no obvious thing to double-click"
    assert (extracted / "scripts" / "run-install.bat").is_file()
    assert (extracted / "scripts" / "install.py").is_file()
    assert (extracted / "scripts" / "bootstrap.py").is_file()
    assert (extracted / "patches" / "patches.yaml").is_file()
    assert (extracted / "tools" / "python" / "python.exe").is_file()
    assert not any(p.name == "work" for p in extracted.rglob("*")), \
        "the checkout's `work` folder reached the shipped archive"


def test_the_archive_ships_no_build_or_signing_tooling(extracted):
    """release.py and sign_manifest.py build and SIGN releases. Neither belongs on a player's
    disk -- the second one is the private-key machinery."""
    shipped = {p.name for p in (extracted / "scripts").iterdir()}
    for forbidden in ("release.py", "sign_manifest.py", "hash_hd_pack.py",
                      "trace_imports.py", "build_runtime.py"):
        assert forbidden not in shipped, f"{forbidden} must not ship"


def test_installing_from_the_extracted_archive_patches_the_game(extracted, tmp_path, bak_path):
    """The whole point: what a tester does, done for real.

    Runs INSTALL.bat -- not install.py -- so the synthesised launcher, the batch handshake and
    the relative paths inside the archive are all exercised, using the TRIMMED interpreter that
    ships in the zip rather than the developer's full one.
    """
    game = tmp_path / "game"
    game.mkdir()
    shutil.copy2(bak_path, game / "terranx_PRACX.exe")
    (game / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")

    env = dict(os.environ)
    env["LONGEVITY_NO_WAIT"] = "1"
    env.pop("PYTHONPATH", None)          # the shipped runtime must stand alone
    p = subprocess.run(["cmd", "/c", str(extracted / "INSTALL.bat"),
                        "--ai", "off", "--no-wait", "--game-dir", str(game)],
                       capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL, timeout=1800)
    out = p.stdout + p.stderr
    assert p.returncode == 0, out
    assert "INSTALLATION SUCCESSFUL" in out, out

    table = ap.load_targets(ap.DEFAULT_PATCHES)
    got = hashlib.md5((game / "terranx_PRACX.exe").read_bytes()).hexdigest()
    assert got == table["pracx"].patched_md5, "the shipped archive produced the wrong build"
    assert (game / "terranx_PRACX.exe.bak").is_file()
    assert (game / "uimod.dll").is_file()
    assert rc.module_version(rc.read(game), "base") == ver.VERSION


def test_the_resident_updater_deployed_from_the_archive_is_usable(extracted, tmp_path, bak_path):
    """A resident updater always has the shipped layout, and must be complete enough to run --
    it is what the in-game update prompt will spawn."""
    import bootstrap as bs
    game = tmp_path / "game2"
    game.mkdir()
    shutil.copy2(bak_path, game / "terranx_PRACX.exe")
    (game / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")

    env = dict(os.environ)
    env["LONGEVITY_NO_WAIT"] = "1"
    env.pop("PYTHONPATH", None)
    p = subprocess.run(["cmd", "/c", str(extracted / "INSTALL.bat"),
                        "--ai", "off", "--no-wait", "--game-dir", str(game)],
                       capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL, timeout=1800)
    assert p.returncode == 0, p.stdout + p.stderr

    d = bs.updater_dir(game)
    assert bs.missing_parts(d) == [], f"resident updater incomplete: {bs.missing_parts(d)}"
    assert bs.resident_version(game) == ver.VERSION
    assert not (d / "work").exists(), "the resident copy is not in the shipped layout"
    # The launcher resolves its interpreter as ..\\tools\\python from its own directory.
    assert (d / "tools" / "python" / "python.exe").is_file()


def test_running_install_bat_from_an_incomplete_extraction_still_reports(extracted, tmp_path):
    """Half-extracting the archive is a real thing people do. It must not flash and vanish."""
    partial = tmp_path / "partial"
    partial.mkdir()
    shutil.copy2(extracted / "INSTALL.bat", partial / "INSTALL.bat")
    p = subprocess.run(["cmd", "/c", str(partial / "INSTALL.bat"), "--no-wait"],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300)
    out = p.stdout + p.stderr
    assert p.returncode != 0
    assert "INSTALLATION FAILED" in out, out
    assert "extract the WHOLE archive" in out, out
    assert "Nothing on disk was changed" in out, out
