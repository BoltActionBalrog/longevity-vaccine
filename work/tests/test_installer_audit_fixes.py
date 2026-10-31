"""Installer fixes from the independent review of 2026-10-28 (unit level; the end-to-end flows are in
test_install_e2e.py): the pinned-resolution check covers every PRACX configuration, and an uninstall
restores only from backups of the bases the shipping targets patch."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import apply_patches as ap    # noqa: E402
import install as inst        # noqa: E402

inst._load_modules()          # the installer binds its patcher module lazily, inside its guard


def test_the_resolution_check_covers_every_pracx_configuration():
    assert inst.resolution_check_applies("pracx")
    assert inst.resolution_check_applies("pracx_thinker"), "PRACX + Thinker pins the same [PRACX] keys"
    assert not inst.resolution_check_applies("vanilla")
    assert not inst.resolution_check_applies(None)
    assert not inst.resolution_check_applies("no_such_target")


def test_uninstall_restores_only_from_the_shipping_targets_bases():
    table = ap.load_targets()
    ours = inst.restorable_base_hashes()
    for tid, t in table.items():
        if t.launch:
            assert t.base_md5 in ours, tid
            for cinfo in (t.companion or {}).values():
                if isinstance(cinfo, dict) and cinfo.get("base_md5"):
                    assert str(cinfo["base_md5"]).lower() in ours, tid
        elif t.base_md5:
            assert t.base_md5 not in ours, f"{tid} is dev-only: a .bak of it is not ours to restore"


def test_mod_exe_prefers_the_launcher_only_for_a_launcher_target(tmp_path):
    g = tmp_path
    (g / "terranx.exe").write_bytes(b"x")
    (g / "thinker.exe").write_bytes(b"x")
    assert inst.mod_exe(g, "pracx_thinker").name == "thinker.exe"
    assert inst.mod_exe(g, "pracx").name == "terranx.exe"
    (g / "thinker.exe").unlink()
    assert inst.mod_exe(g, "pracx_thinker").name == "terranx.exe", "launcher missing -> the exe itself"
