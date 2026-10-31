"""dev_player_zip.py: the first-install test artifact must BE the player's download.

The earlier test archive (dev_test_manifest.build_base_archive) re-implemented the payload
layout and silently lacked the root INSTALL.bat, so a "player path" test built on it would have
started from a folder no player ever sees. These tests pin the new builder to release.py's own
functions: same name, same root launcher, the checkout's real version, nothing developer-only.
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent.parent
_SCRIPTS = _REPO / "work" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import release as rel          # noqa: E402
import version as ver          # noqa: E402
import dev_player_zip as dpz   # noqa: E402

_PY = _REPO / "tools" / "python" / "python.exe"
pytestmark = pytest.mark.skipif(not _PY.exists(), reason="bundled interpreter not present")


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    """One build without the interpreter (seconds, not minutes), shared by the read-only tests."""
    out = tmp_path_factory.mktemp("player")
    p = subprocess.run([str(_PY), str(_SCRIPTS / "dev_player_zip.py"), "--no-python",
                        "--out", str(out)], capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stdout + p.stderr
    return out


def test_the_zip_is_named_like_the_download(built):
    assert (built / rel.archive_name("base", ver.VERSION)).is_file()


def test_install_bat_sits_at_the_archive_root(built):
    names = zipfile.ZipFile(built / rel.archive_name("base", ver.VERSION)).namelist()
    assert "INSTALL.bat" in names
    assert "scripts/run-install.bat" in names
    assert "scripts/install.py" in names


def test_the_version_is_the_checkouts_not_a_test_stamp(built):
    z = zipfile.ZipFile(built / rel.archive_name("base", ver.VERSION))
    src = z.read("scripts/version.py").decode("utf-8")
    assert f'VERSION = "{ver.VERSION}"' in src
    assert "9.9.9" not in src


def test_nothing_developer_only_ships(built):
    names = zipfile.ZipFile(built / rel.archive_name("base", ver.VERSION)).namelist()
    for forbidden in ("scripts/sign_manifest.py", "scripts/release.py", "scripts/dev_player_zip.py",
                      "scripts/dev_test_manifest.py"):
        assert forbidden not in names, forbidden


def test_extraction_matches_explorers_extract_all(built):
    folder = Path((built / "extracted.txt").read_text(encoding="utf-8").strip())
    assert folder.name == rel.archive_name("base", ver.VERSION)[:-len(".zip")]
    assert folder.parent == built / "Downloads"
    assert (folder / "INSTALL.bat").is_file()
    assert (folder / "scripts" / "run-install.bat").is_file()
    # The root launcher must be the release's own text, CRLF included.
    assert (folder / "INSTALL.bat").read_bytes() == rel._ROOT_LAUNCHER.encode("ascii")


def test_no_extract_writes_no_downloads_folder(tmp_path):
    out = tmp_path / "o"
    assert dpz.main(["--no-python", "--no-extract", "--out", str(out)]) == 0
    assert (out / rel.archive_name("base", ver.VERSION)).is_file()
    assert not (out / "Downloads").exists()
    assert not (out / "extracted.txt").exists()


def test_the_zip_is_byte_identical_to_a_release_build(built, tmp_path):
    """Same inputs, same functions: a diff here means the test artifact is not what ships."""
    out = tmp_path / "rel"
    p = subprocess.run([str(_PY), str(_SCRIPTS / "release.py"), "--skip-gate", "--no-python",
                        "--modules", "base", "--out", str(out)],
                       capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stdout + p.stderr
    name = rel.archive_name("base", ver.VERSION)
    assert (out / ver.VERSION / name).read_bytes() == (built / name).read_bytes()
