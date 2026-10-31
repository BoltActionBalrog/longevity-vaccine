"""run-at-resolution.ps1: the dev launcher's ini edit / restore, exercised with -DryRun (no game).

The script forces [PRACX] ScreenWidth/ScreenHeight/WindowWidth/WindowHeight and the two [UIMod] keys
VideoMode=0 + FullscreenModeSwitch=1 for the run (Fullscreen with PRACX's REAL display-mode switch, so a
capture is the game's own pixels), then restores every key -- a [UIMod] key that was absent must be
absent again, a missing [UIMod] section must not survive, and a leftover sidecar from an interrupted
run (with or without the [UIMod] entries) must be recovered first.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "run-at-resolution.ps1"
PWSH = shutil.which("pwsh")

BASE_INI = """[PREFERENCES]
Preferences=12345

[Alpha Centauri]
DirectDraw=0

[PRACX]
ScreenWidth=3840
ScreenHeight=2160
WindowWidth=1920
WindowHeight=1080
Zoom=1
"""

UIMOD_SECTION = """
[UIMod]
DebugLog=1
VideoMode=1

[Longevity]
VideoMode=7
FullscreenModeSwitch=7
"""


def sections(text: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    cur = ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1]
            out.setdefault(cur, {})
        elif "=" in s and cur:
            k, v = s.split("=", 1)
            out[cur][k.strip()] = v.strip()
    return out


def run(game_dir: Path, exe: str = "terranx_fake.exe") -> subprocess.CompletedProcess:
    return subprocess.run(
        [PWSH, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
         "-Width", "1600", "-Height", "1200", "-GameDir", str(game_dir), "-GameExe", exe, "-DryRun"],
        capture_output=True, text=True, timeout=120)


@pytest.fixture
def game_dir(tmp_path: Path) -> Path:
    (tmp_path / "terranx_fake.exe").write_bytes(b"")
    return tmp_path


def lines(text: str) -> list[str]:
    return [l.rstrip() for l in text.splitlines() if l.strip()]


@pytest.mark.skipif(PWSH is None, reason="pwsh not installed")
@pytest.mark.parametrize("ini_text", [
    pytest.param(BASE_INI + UIMOD_SECTION, id="uimod-section-present"),
    pytest.param(BASE_INI, id="no-uimod-section"),
    pytest.param(BASE_INI + "\n[UIMod]\nFullscreenModeSwitch=0\nVideoMode=2\n", id="both-keys-present"),
])
def test_dry_run_forces_then_restores(game_dir: Path, ini_text: str) -> None:
    ini = game_dir / "Alpha Centauri.Ini"
    ini.write_text(ini_text, encoding="ascii")
    r = run(game_dir)
    assert r.returncode == 0, r.stdout + r.stderr

    during = sections((game_dir / "Alpha Centauri.Ini.dryrun").read_text(encoding="ascii"))
    assert during["PRACX"]["ScreenWidth"] == "1600" and during["PRACX"]["ScreenHeight"] == "1200"
    assert during["PRACX"]["WindowWidth"] == "1600" and during["PRACX"]["WindowHeight"] == "1200"
    assert during["UIMod"]["VideoMode"] == "0"
    assert during["UIMod"]["FullscreenModeSwitch"] == "1"
    if "Longevity" in during:                      # the section after [UIMod] is untouched
        assert during["Longevity"] == {"VideoMode": "7", "FullscreenModeSwitch": "7"}

    assert lines(ini.read_text(encoding="ascii")) == lines(ini_text)   # restored exactly
    assert not (game_dir / "Alpha Centauri.Ini.resbak").exists()


@pytest.mark.skipif(PWSH is None, reason="pwsh not installed")
@pytest.mark.parametrize("sidecar", [
    pytest.param("ScreenWidth=3840\nScreenHeight=2160\nWindowWidth=1920\nWindowHeight=1080\n", id="old-sidecar"),
    pytest.param("ScreenWidth=3840\nScreenHeight=2160\nWindowWidth=1920\nWindowHeight=1080\n"
                 "VideoMode=1\nFullscreenModeSwitch=<absent>\n", id="new-sidecar"),
])
def test_interrupted_run_is_recovered_first(game_dir: Path, sidecar: str) -> None:
    """The ini still carries a previous run's forced values; the sidecar holds the truth."""
    ini = game_dir / "Alpha Centauri.Ini"
    clobbered = BASE_INI.replace("3840", "1600").replace("2160", "1200") + \
        "\n[UIMod]\nDebugLog=1\nVideoMode=0\nFullscreenModeSwitch=1\n"
    ini.write_text(clobbered, encoding="ascii")
    (game_dir / "Alpha Centauri.Ini.resbak").write_text(sidecar, encoding="ascii")
    r = run(game_dir)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "recovering" in r.stdout

    final = sections(ini.read_text(encoding="ascii"))
    assert final["PRACX"]["ScreenWidth"] == "3840" and final["PRACX"]["WindowWidth"] == "1920"
    if "<absent>" in sidecar:
        assert final["UIMod"] == {"DebugLog": "1", "VideoMode": "1"}
    else:                                          # an old sidecar knows nothing of [UIMod]: those keys are dropped
        assert final["UIMod"] == {"DebugLog": "1"}
    assert not (game_dir / "Alpha Centauri.Ini.resbak").exists()


@pytest.mark.skipif(PWSH is None, reason="pwsh not installed")
def test_missing_resolution_key_refuses(game_dir: Path) -> None:
    ini = game_dir / "Alpha Centauri.Ini"
    ini.write_text(BASE_INI.replace("WindowHeight=1080\n", ""), encoding="ascii")
    r = run(game_dir)
    assert r.returncode != 0
    assert "WindowHeight" in r.stdout + r.stderr
