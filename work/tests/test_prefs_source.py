r"""The Longevity Preferences tab (prefs.cpp), pinned at the source: the option-row ORDER the user chose on
2026-11-07, the parent row's label wherever a player reads it, and the Restore Defaults rule for a consent.

- Row order (top to bottom): "Check for Updates at Startup"; "Modern Control Set" + "Right-Click Drags to Move";
  the two map-drag cells; the two camera rows; "AI Cannot See Cloaked Units..." + its two nested rows; "Air Drops
  Divert..."; "Enable Custom Portraits" + the HD row + "Add Scanlines". Every row goes through ONE `row()` lambda in
  BuildWidgets, so the order is the order of the `row(g_w.xxx, ...)` calls (the drag cells are built inline).
- "Enable User Portraits" became "Enable Custom Portraits" (the HD pack is not the player's own art); the shipped
  portraits guide names the row and must say the same.
- Restore Defaults must NOT touch "Check for Updates at Startup": the installer asked the player once, and a button
  that says nothing about updates must not reverse that answer. Only the row itself and "Reset Skipped Updates"
  (whose popup says so) turn it on.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "uimod" / "src"
PREFS = (SRC / "prefs.cpp").read_text(encoding="utf-8")
README = (ROOT / "work" / "art" / "portraits-README.txt").read_text(encoding="utf-8")

#: the order of the checkbox rows BuildWidgets constructs through the shared row() lambda
EXPECTED_ROW_ORDER = [
    "updcheck",
    "moderncheck", "rcmovecheck",
    # the map-drag cells sit here (built inline, see test_drag_cells_sit_between_modern_and_camera)
    "clickview", "baseview",
    "aicheck", "cargocheck", "markcheck",
    "airdropcheck",
    "customcheck", "hdcheck", "scancheck",
]


def _build_widgets() -> str:
    a = PREFS.index("void BuildWidgets()")
    b = PREFS.index("\n}\n", a)
    return PREFS[a:b]


def _restore_defaults() -> str:
    a = PREFS.index("} else if (id == 0x5A) {")
    b = PREFS.index("g_origCommand(self, edx, id);", a)
    return PREFS[a:b]


def test_row_order_is_the_users():
    assert re.findall(r"\brow\(g_w\.(\w+),", _build_widgets()) == EXPECTED_ROW_ORDER


def test_drag_cells_sit_between_modern_and_camera():
    bw = _build_widgets()
    drag = bw.index("g_w.dragcell[i]")
    assert bw.index("row(g_w.rcmovecheck,") < drag < bw.index("row(g_w.clickview,")


def test_every_row_is_built_once():
    names = re.findall(r"\brow\(g_w\.(\w+),", _build_widgets())
    assert len(names) == len(set(names))


def test_parent_label_is_custom_portraits_everywhere_a_player_reads_it():
    m = re.search(r'kCustomChkText\[\] = "([^"]+)"', PREFS)
    assert m and m.group(1) == "Enable Custom Portraits"
    assert m.group(1) in README
    assert '"Enable User Portraits"' not in README


def test_restore_defaults_leaves_the_update_consent_alone():
    block = _restore_defaults()
    assert "UpdateCheckSet(" not in block
    assert "kUpdateCheckDefault" not in PREFS
    # the ONE other control that turns it on says so in its popup
    core = (SRC / "update_core.h").read_text(encoding="utf-8")
    assert "turns on Check for Updates at Startup" in core


def test_restore_defaults_keeps_a_hidden_hd_value():
    # no pack = no HD row = the stored HdPortraits is not the page's to reset (the parent toggle keeps it too)
    assert re.search(r"PortraitSetAll\(kPortraitCustomDefault,\s*g_hdRow \?", _restore_defaults())
