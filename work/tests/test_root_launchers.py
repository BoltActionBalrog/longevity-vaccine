"""The launchers at the base archive's root (INSTALL.bat, UNINSTALL.bat), run through the real cmd.exe.

release.py synthesises both from one template. Running them through cmd is the only way to see what cmd
makes of them: the 1.0.0 INSTALL.bat passed every text check, yet on an incomplete extraction its
`endlocal ^& exit /b 9` (inside a parenthesised block) never exited -- it fell through to `call ""`, printed
a stray "is not recognized" line and exited 1.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import release as rel  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe launchers")

LAUNCHERS = sorted(rel._SYNTHESISED)

#: A stand-in for scripts\run-install.bat: prints the arguments it was given, then exits 7.
FAKE_INNER = "@echo off\r\necho ARGS=[%*]\r\nexit /b 7\r\n"


def _write(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_bytes(rel._SYNTHESISED[name].encode("ascii"))
    return p


def _run(bat: Path, *args: str) -> subprocess.CompletedProcess:
    """As Explorer starts a .bat: cmd /s /c with the whole command line in one pair of quotes, so a
    folder name with spaces or an `&` reaches the launcher intact."""
    line = " ".join([f'"{bat}"'] + [f'"{a}"' if " " in a else a for a in args])
    return subprocess.run(f'cmd /d /s /c "{line}"', capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=60)


def test_the_base_archive_synthesises_both_launchers():
    try:
        entries = rel.collect("base", include_python=False)
    except (FileNotFoundError, SystemExit) as e:          # a checkout without the built DLL
        pytest.skip(f"base cannot be collected here: {e}")
    assert sorted(arc for src, arc in entries if src is None) == ["INSTALL.bat", "UNINSTALL.bat"]


@pytest.mark.parametrize("name", LAUNCHERS)
def test_each_launcher_is_ascii_crlf_and_targets_run_install(name):
    data = rel._SYNTHESISED[name].encode("ascii")
    assert data.count(b"\r\n") == data.count(b"\n"), f"{name} must be CRLF for cmd"
    text = data.decode("ascii")
    assert 'set "INNER=%~dp0scripts\\run-install.bat"' in text
    assert "^&" not in text, "a caret-escaped & in a launcher is the 1.0.0 fall-through bug"
    assert "(" not in text.split(":incomplete")[0], "no parenthesised block before the exit"


@pytest.mark.parametrize("name, failed", [("INSTALL.bat", "INSTALLATION FAILED"),
                                          ("UNINSTALL.bat", "UNINSTALL FAILED")])
def test_an_incomplete_extraction_reports_and_exits_9(tmp_path, name, failed):
    p = _run(_write(tmp_path / "partial", name), "--no-wait")
    out = p.stdout + p.stderr
    assert p.returncode == 9, out
    assert failed in out and "scripts\\run-install.bat is missing" in out, out
    assert "Nothing on disk was changed" in out and f"before running {name}" in out, out
    assert "not recognized" not in out and "ARGS=" not in out, out


@pytest.mark.parametrize("name, mode", [("INSTALL.bat", ""), ("UNINSTALL.bat", "--uninstall ")])
@pytest.mark.parametrize("folder", ["plain", "with space & ampersand", "100% done", "car^et", "a & b (1)"])
@pytest.mark.parametrize("game_dir", [r"C:\Games\SMAC X", r"D:\Games\100% SMAC", r"D:\Ga^me"])
def test_the_launcher_passes_its_mode_and_the_players_arguments_and_the_exit_code(tmp_path, name, mode, folder,
                                                                                   game_dir):
    """`call` re-expands its line: a % or ^ in the extraction folder or an argument once broke the path or
    reached the installer changed (D:\\100% SMAC -> D:\\100 SMAC, D:\\Ga^me -> D:\\Ga^^me)."""
    root = tmp_path / folder
    bat = _write(root, name)
    (root / "scripts").mkdir()
    (root / "scripts" / "run-install.bat").write_bytes(FAKE_INNER.encode("ascii"))
    p = subprocess.run(f'cmd /d /s /c ""{bat}" --no-wait --game-dir "{game_dir}""', capture_output=True,
                       text=True, stdin=subprocess.DEVNULL, timeout=60)
    out = p.stdout + p.stderr
    assert p.returncode == 7, out
    assert f'ARGS=[{mode}--no-wait --game-dir "{game_dir}"]' in out, out
    assert "not recognized" not in out and "cannot find the path" not in out, out


@pytest.mark.parametrize("name", LAUNCHERS)
def test_the_incomplete_branch_waits_for_a_key_only_without_no_wait(tmp_path, name):
    bat = _write(tmp_path / "p", name)
    assert "Press any key" not in _run(bat, "--no-wait").stdout
    assert "Press any key" in _run(bat).stdout


def test_uninstall_bat_with_no_arguments_runs_the_uninstall_mode_only(tmp_path):
    root = tmp_path / "x"
    bat = _write(root, "UNINSTALL.bat")
    (root / "scripts").mkdir()
    (root / "scripts" / "run-install.bat").write_bytes(FAKE_INNER.encode("ascii"))
    p = _run(bat)
    assert p.returncode == 7
    assert "ARGS=[--uninstall]" in p.stdout, p.stdout
