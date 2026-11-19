"""wine_ddraw.py: under Wine, GOG's DDrawCompat ddraw.dll is set aside (it crashes the game whenever a ddraw override
loads it); on Windows nothing changes except that a backup of ours with no live ddraw.dll goes back; --uninstall
restores. Pure file-level checks on synthetic DLLs, plus the real GOG file when the game folder is present.
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import wine_ddraw as wd  # noqa: E402


def _string(key: str, value: str) -> bytes:
    """One VS_VERSIONINFO String record (header, UTF-16LE key, padding to 4, UTF-16LE value)."""
    k = key.encode("utf-16le") + b"\0\0"
    v = value.encode("utf-16le") + b"\0\0"
    head = 6 + len(k)
    pad = (-head) % 4
    body = k + b"\0" * pad + v
    return (6 + len(body)).to_bytes(2, "little") + (len(v) // 2).to_bytes(2, "little") + b"\1\0" + body


def fake_dll(product: str = "DDrawCompat", version: str = "v0.5.4", mz: bool = True, filler: int = 64) -> bytes:
    """A stand-in DLL: MZ header, filler, then the version strings the identification reads."""
    out = (b"MZ" if mz else b"XX") + b"\x90" * filler
    out += _string("CompanyName", "") + _string("FileDescription", "https://github.com/narzoul/DDrawCompat")
    out += _string("ProductName", product) + _string("ProductVersion", version) + b"\0" * 16
    return out


DDC = fake_dll()
DDC_NEWER = fake_dll(version="v0.6.0")
CNC = fake_dll(product="cnc-ddraw", version="7.1.0.0")


@pytest.fixture
def game(tmp_path):
    g = tmp_path / "game"
    g.mkdir()
    return g


def _files(g: pathlib.Path) -> dict:
    return {p.name: p.read_bytes() for p in sorted(g.iterdir())}


# ---------------------------------------------------------------- identification

def test_identifies_ddrawcompat_and_its_version(tmp_path):
    p = tmp_path / "ddraw.dll"
    p.write_bytes(DDC)
    assert wd.ddrawcompat_version(p) == "v0.5.4"


@pytest.mark.parametrize("data", [CNC, fake_dll(mz=False), b"", b"MZ" + b"\0" * 100,
                                  fake_dll(product="DDrawCompatX"), fake_dll(product="ddrawcompat")],
                         ids=["other-wrapper", "not-pe", "empty", "no-version-info", "longer-name", "wrong-case"])
def test_anything_else_is_not_ddrawcompat(tmp_path, data):
    p = tmp_path / "ddraw.dll"
    p.write_bytes(data)
    assert wd.ddrawcompat_version(p) == ""


def test_a_missing_file_is_not_ddrawcompat(tmp_path):
    assert wd.ddrawcompat_version(tmp_path / "nope.dll") == ""


def test_ddrawcompat_without_a_version_string_still_counts(tmp_path):
    p = tmp_path / "ddraw.dll"
    p.write_bytes(b"MZ" + b"\x90" * 8 + _string("ProductName", "DDrawCompat"))
    assert wd.ddrawcompat_version(p) == "?"


def test_the_real_gog_ddraw_dll_is_recognised():
    """Read-only: GOG's own file (the one that crashed under ddraw=n,b) must be identified."""
    try:
        import config
        real = pathlib.Path(config.game_dir()) / "ddraw.dll"
    except Exception:  # noqa: BLE001
        pytest.skip("no game folder configured")
    if not real.is_file():
        pytest.skip("no ddraw.dll in the game folder")
    assert wd.ddrawcompat_version(real).startswith("v"), real


@pytest.mark.skipif(sys.platform != "win32", reason="Windows host only")
def test_this_windows_host_is_windows(monkeypatch):
    monkeypatch.delenv(wd.ASSUME_ENV, raising=False)
    assert wd.platform() == wd.WINDOWS and wd.running_under_wine() is False


def test_detection_failure_is_unknown_never_windows(monkeypatch):
    """A crash inside detection must not be read as "Windows" (that branch moves files back)."""
    monkeypatch.delenv(wd.ASSUME_ENV, raising=False)
    monkeypatch.setattr(wd.sys, "platform", "win32")
    monkeypatch.setattr(wd, "_wine_export", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert wd.platform() == wd.UNKNOWN


def test_hidden_wine_exports_still_detected_by_the_registry(monkeypatch):
    monkeypatch.delenv(wd.ASSUME_ENV, raising=False)
    monkeypatch.setattr(wd.sys, "platform", "win32")
    monkeypatch.setattr(wd, "_wine_export", lambda: False)
    monkeypatch.setattr(wd, "_wine_registry_key", lambda: True)
    assert wd.platform() == wd.WINE


def test_a_non_windows_python_is_unknown(monkeypatch):
    monkeypatch.delenv(wd.ASSUME_ENV, raising=False)
    monkeypatch.setattr(wd.sys, "platform", "linux")
    assert wd.platform() == wd.UNKNOWN


@pytest.mark.parametrize("value,expected", [("wine", "wine"), ("WINDOWS", "windows")])
def test_the_test_override(monkeypatch, value, expected):
    monkeypatch.setenv(wd.ASSUME_ENV, value)
    assert wd.platform() == expected


def test_unknown_platform_touches_nothing(game):
    (game / "ddraw.dll.longevity.bak").write_bytes(DDC)
    assert wd.set_aside(game, where=wd.UNKNOWN) == (wd.NOT_WINE, "")
    assert _files(game) == {"ddraw.dll.longevity.bak": DDC}


def test_a_productname_literal_before_the_resource_does_not_hide_it(tmp_path):
    p = tmp_path / "ddraw.dll"
    literal = "\\StringFileInfo\\040904B0\\ProductName".encode("utf-16le") + b"\0\0" + "x".encode("utf-16le") + b"\0\0"
    p.write_bytes(DDC[:2] + literal + DDC[2:])
    assert wd.ddrawcompat_version(p) == "v0.5.4"


@pytest.mark.parametrize("version,moves", [("v0.5.4", True), ("v0.4.1", True), ("v0.6.0", True),
                                           ("v0.4.0", False), ("v0.3.2", False), ("?", False)])
def test_only_builds_newer_than_v0_4_0_are_moved(game, version, moves):
    data = fake_dll(version=version) if version != "?" else b"MZ" + b"\x90" * 8 + _string("ProductName", "DDrawCompat")
    (game / "ddraw.dll").write_bytes(data)
    status, line = wd.set_aside(game, where=wd.WINE)
    if moves:
        assert status == wd.MOVED and _files(game) == {"ddraw.dll.longevity.bak": data}
    else:
        assert status == wd.FOREIGN and "left alone" in line and _files(game) == {"ddraw.dll": data}


# ---------------------------------------------------------------- under Wine

def test_wine_moves_ddrawcompat_aside_and_keeps_its_bytes(game):
    (game / "ddraw.dll").write_bytes(DDC)
    status, line = wd.set_aside(game, where=wd.WINE)
    assert status == wd.MOVED and "v0.5.4" in line and "--uninstall" in line
    assert _files(game) == {"ddraw.dll.longevity.bak": DDC}


def test_wine_second_run_reports_already(game):
    (game / "ddraw.dll").write_bytes(DDC)
    wd.set_aside(game, where=wd.WINE)
    status, line = wd.set_aside(game, where=wd.WINE)
    assert status == wd.ALREADY and line
    assert _files(game) == {"ddraw.dll.longevity.bak": DDC}


def test_wine_leaves_another_wrapper_alone(game):
    (game / "ddraw.dll").write_bytes(CNC)
    status, line = wd.set_aside(game, where=wd.WINE)
    assert status == wd.FOREIGN and "left alone" in line
    assert _files(game) == {"ddraw.dll": CNC}


def test_wine_without_a_ddraw_dll_does_nothing(game):
    assert wd.set_aside(game, where=wd.WINE) == (wd.ABSENT, "")
    assert _files(game) == {}


def test_wine_a_ddrawcompat_put_back_by_a_file_check_replaces_the_backup(game):
    (game / "ddraw.dll.longevity.bak").write_bytes(DDC)
    (game / "ddraw.dll").write_bytes(DDC_NEWER)
    status, _ = wd.set_aside(game, where=wd.WINE)
    assert status == wd.MOVED
    assert _files(game) == {"ddraw.dll.longevity.bak": DDC_NEWER}


def test_wine_a_failed_move_is_reported_not_raised(game, monkeypatch):
    (game / "ddraw.dll").write_bytes(DDC)
    monkeypatch.setattr(wd.os, "replace", lambda *_a: (_ for _ in ()).throw(PermissionError("in use")))
    status, line = wd.set_aside(game, where=wd.WINE)
    assert status == wd.FAILED and "in use" in line
    assert _files(game) == {"ddraw.dll": DDC}


# ---------------------------------------------------------------- not Wine (Windows)

def test_windows_never_touches_a_live_ddrawcompat(game):
    (game / "ddraw.dll").write_bytes(DDC)
    assert wd.set_aside(game, where=wd.WINDOWS) == (wd.NOT_WINE, "")
    assert _files(game) == {"ddraw.dll": DDC}


def test_windows_puts_back_a_backup_of_ours_with_no_live_file(game):
    """A folder installed under Wine and later used from Windows (dual boot) gets DDrawCompat back."""
    (game / "ddraw.dll.longevity.bak").write_bytes(DDC)
    status, line = wd.set_aside(game, where=wd.WINDOWS)
    assert status == wd.RESTORED and line
    assert _files(game) == {"ddraw.dll": DDC}


def test_windows_reports_a_failed_put_back(game, monkeypatch):
    (game / "ddraw.dll.longevity.bak").write_bytes(DDC)
    monkeypatch.setattr(wd.os, "replace", lambda *_a: (_ for _ in ()).throw(PermissionError("read-only")))
    status, line = wd.set_aside(game, where=wd.WINDOWS)
    assert status == wd.FAILED and "read-only" in line
    assert _files(game) == {"ddraw.dll.longevity.bak": DDC}


def test_windows_drops_a_backup_identical_to_the_live_file(game):
    """A file check put DDrawCompat back on a folder a Linux install had set it aside in: the backup is redundant."""
    (game / "ddraw.dll").write_bytes(DDC)
    (game / "ddraw.dll.longevity.bak").write_bytes(DDC)
    status, line = wd.set_aside(game, where=wd.WINDOWS)
    assert status == wd.DROPPED and line
    assert _files(game) == {"ddraw.dll": DDC}


def test_the_hkcu_wine_key_alone_is_not_wine(monkeypatch):
    """Any Windows program can create HKCU\\Software\\Wine; only the ntdll export or HKLM\\Software\\Wine count."""
    import inspect
    assert "HKEY_CURRENT_USER" not in inspect.getsource(wd._wine_registry_key)


def test_windows_leaves_both_when_both_exist(game):
    (game / "ddraw.dll").write_bytes(CNC)
    (game / "ddraw.dll.longevity.bak").write_bytes(DDC)
    assert wd.set_aside(game, where=wd.WINDOWS) == (wd.NOT_WINE, "")
    assert _files(game) == {"ddraw.dll": CNC, "ddraw.dll.longevity.bak": DDC}


def test_windows_with_nothing_says_nothing(game):
    assert wd.set_aside(game, where=wd.WINDOWS) == (wd.NOT_WINE, "")
    assert _files(game) == {}


# ---------------------------------------------------------------- uninstall

def test_restore_puts_the_backup_back(game):
    (game / "ddraw.dll.longevity.bak").write_bytes(DDC)
    status, _ = wd.restore(game)
    assert status == wd.RESTORED
    assert _files(game) == {"ddraw.dll": DDC}


def test_restore_drops_a_redundant_identical_backup(game):
    (game / "ddraw.dll").write_bytes(DDC)
    (game / "ddraw.dll.longevity.bak").write_bytes(DDC)
    status, line = wd.restore(game)
    assert status == wd.DROPPED and line
    assert _files(game) == {"ddraw.dll": DDC}


def test_restore_never_overwrites_a_different_live_file(game):
    (game / "ddraw.dll").write_bytes(CNC)
    (game / "ddraw.dll.longevity.bak").write_bytes(DDC)
    status, line = wd.restore(game)
    assert status == wd.KEPT and line
    assert _files(game) == {"ddraw.dll": CNC, "ddraw.dll.longevity.bak": DDC}


def test_restore_leaves_a_backup_that_is_not_ddrawcompat(game):
    (game / "ddraw.dll.longevity.bak").write_bytes(CNC)
    status, _ = wd.restore(game)
    assert status == wd.KEPT
    assert _files(game) == {"ddraw.dll.longevity.bak": CNC}


def test_restore_with_nothing_to_do(game):
    assert wd.restore(game) == (wd.NOTHING, "")


def test_round_trip_wine_install_then_uninstall_is_byte_identical(game):
    (game / "ddraw.dll").write_bytes(DDC)
    wd.set_aside(game, where=wd.WINE)
    wd.restore(game)
    assert _files(game) == {"ddraw.dll": DDC}
