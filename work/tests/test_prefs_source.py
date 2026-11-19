r"""The Longevity Preferences tab (prefs.cpp), pinned at the source: the option-row ORDER the user chose on
2026-11-07, the PAGE each row is on (two fixed pages, the owner's split of 2026-11-12/13), the More button's
caption, the parent row's label wherever a player reads it, and the Restore Defaults rule for a consent.

- Row order (top to bottom), page 1: "Check for Updates at Startup"; "Modern Control Set" + "Right-Click Drags to
  Move" + "Hide Move Line" (one line); the two map-drag cells; the two camera rows; "AI Cannot See Cloaked Units..." + its two nested rows; "Air
  Drops Divert...". Page 2: "Enable Custom Portraits" + the HD row + "Add Scanlines" (the contributor's HD art rows
  join it when they land). Every row goes through ONE `row()` lambda in BuildWidgets, so the order is
  the order of the `row(g_w.xxx, ...)` calls (the drag cells and the display-mode cells are built inline).
  BuildWidgets restarts its row counter where page 2 starts, and ForPage1 / ForPage2 (what each page shows and
  hides) list the same rows the build puts there: a row never changes page.
- The stock More button reads "More" on page 1 and "Back" on page 2, from the engine's own TextLabels entries.
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

#: the checkbox rows BuildWidgets constructs through the shared row() lambda, page by page, in order
PAGE1_ROWS = [
    "updcheck",
    "moderncheck",
    # Modern's two children share one line (built inline, see test_modern_children_share_a_line)
    # the map-drag cells sit here (built inline, see test_drag_cells_sit_between_modern_and_camera)
    "clickview", "baseview",
    "aicheck", "cargocheck", "markcheck",
    "airdropcheck",
]
PAGE2_ROWS = ["customcheck", "hdcheck", "scancheck"]
EXPECTED_ROW_ORDER = PAGE1_ROWS + PAGE2_ROWS
#: page-1 widgets that are not row() checkboxes: the display-mode row, the update button, the slider frame
PAGE1_OTHER = {"clipcheck", "modecheck", "subbtn", "rcmovecheck", "hidelinecheck", "dragcell", "label", "slider",
               "holdlabel", "holdslider"}
ROW_RE = r"\brow\(g_w\.(\w+)(?:\[\w+\])?,"


def _build_widgets() -> str:
    a = PREFS.index("void BuildWidgets()")
    b = PREFS.index("\n}\n", a)
    return PREFS[a:b]


def _restore_defaults() -> str:
    a = PREFS.index("} else if (id == 0x5A) {")
    b = PREFS.index("g_origCommand(self, edx, id);", a)
    return PREFS[a:b]


def _page_split() -> tuple[str, str]:
    """BuildWidgets cut where page 2's row counter restarts."""
    bw = _build_widgets()
    cut = bw.index("// page 2\n")
    return bw[:cut], bw[cut:]


def _for_page(n: int) -> set[str]:
    a = PREFS.index(f"template <typename F> void ForPage{n}(F f)")
    b = PREFS.index("\n}\n", a)
    return set(re.findall(r"g_w\.(\w+)", PREFS[a:b]))


def test_row_order_is_the_users():
    assert re.findall(ROW_RE, _build_widgets()) == EXPECTED_ROW_ORDER


def test_each_row_is_on_its_page():
    p1, p2 = _page_split()
    assert re.findall(ROW_RE, p1) == PAGE1_ROWS
    assert re.findall(ROW_RE, p2) == PAGE2_ROWS
    assert re.search(r"// page 2\s*\n\s*base = 0;\s*\n\s*k = 0;", _build_widgets())   # page 2 starts at its row 0


def test_the_pages_show_what_they_build():
    assert _for_page(1) == set(PAGE1_ROWS) | PAGE1_OTHER
    assert _for_page(2) == set(PAGE2_ROWS)


def test_the_more_button_says_more_then_back():
    assert "constexpr int  kLabelMore = 1088, kLabelBack = 664;" in PREFS      # the engine's own TextLabels
    assert "SetMoreCaption(g_page ? kLabelBack : kLabelMore);" in PREFS


def test_leaving_page_two_for_warnings_restores_the_engines_caption():
    """Longevity -> More -> Warning Preferences showed Warning's first page under "Back" (user shot
    20261114-190556): the engine sets the caption in PrefWin_show_cur_page but its show does not repaint a button we
    left shown, so leaving our tab for Warnings sets that page's caption (case 6 "Back", else "More") and repaints."""
    r = PREFS.index("void __fastcall WrapRefresh(void* self, void* edx)")
    body = PREFS[r:PREFS.index("\n}\n", r)]
    leave = body[body.index("g_page = 0;"):body.index("g_moreShown = false;", body.index("g_page = 0;"))]
    assert "SetMoreCaption(tab == 6 ? kLabelBack : kLabelMore);" in leave
    assert leave.index("SetMoreCaption(tab == 6") < leave.index("WinRedraw(At(kVA_MoreBtn));")


def test_drag_cells_sit_between_modern_and_camera():
    bw = _build_widgets()
    drag = bw.index("g_w.dragcell[i]")
    assert bw.index("cell(g_w.hidelinecheck,") < drag < bw.index("row(g_w.clickview,")


def test_every_row_is_built_once():
    names = re.findall(ROW_RE, _build_widgets())
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


def test_hide_move_line_is_saved_and_reset():
    """"Hide Move Line" ([UIMod] HideMoveLine, owner 2026-11-14) persists with OK / Enter and Restore Defaults resets it
    -- a tuning, not a consent."""
    a = PREFS.index("void CommitAll()")
    commit = PREFS[a:PREFS.index("\n}\n", a)]
    assert "HideMoveLineSave();" in commit
    assert "HideMoveLineSet(kHideMoveLineDefault);" in _restore_defaults()


def test_more_button_turns_yellow_before_the_engine_paints():
    """The More / Back button gets its yellow-face vtable BEFORE the engine's refresh paints the stock widgets, on
    every tab (owner 2026-11-14: one button, one look), and the face is recoloured AFTER the stock content_draw (the
    zoom / stripe pipeline) has run, never at its sprites (the stripe remap keys on the stock indices)."""
    a = PREFS.index("void __fastcall WrapRefresh(void* self, void* edx)")
    body = PREFS[a:a + 400]
    assert body.index("ApplyYellowMore();") < body.index("g_origRefresh(self, edx);")
    m = PREFS.index("void __fastcall MoreContentDraw(void* self, void* edx)")
    draw = PREFS[m:PREFS.index("\n}\n", m)]
    assert draw.index("g_moreOrigDraw(self, edx);") < draw.index("g_moreMap[row[x]]")


def test_our_tab_hides_the_warning_more_pages_list():
    """Warning Preferences -> More -> Longevity left the More page's four rows over our tab (ACTION_ITEMS; user shot
    20261114-165245): the engine's hide switch never runs case 6 on a tab click, so our tab hides that list itself
    (PrefWin +0x913C, through its virtual hide, only while shown) whenever it is the active tab."""
    a = PREFS.index("void HideStockMorePageList()")
    fn = PREFS[a:PREFS.index("\n}\n", a)]
    assert "kWarnMoreListOfs" in fn and "0x9C) & 1" in fn and "vt[2]" in fn
    assert "constexpr size_t kWarnMoreListOfs = 0x913C;" in PREFS
    r = PREFS.index("void __fastcall WrapRefresh(void* self, void* edx)")
    body = PREFS[r:PREFS.index("\n}\n", r)]
    ours = body.index("if (OurTabActive()) {")
    assert ours < body.index("HideStockMorePageList();") < body.index("SetMoreCaption(")


def test_modern_children_share_a_line():
    """"Right-Click Drags to Move" and "Hide Move Line" sit on ONE line under Modern Control Set (owner 2026-11-14), Hide
    Move Line in the map-drag cells' second column; it reads UNCHECKED while Right-Click Drags to Move is on (stored
    value kept), like the right-drag map cell."""
    bw = _build_widgets()
    m = bw.index("row(g_w.moderncheck,")
    seg = bw[m:bw.index("if (g_dragRow)", m)]
    assert "cell(g_w.rcmovecheck, kRcMoveChkId, kRcMoveChkText, x0, x1);" in seg
    assert "cell(g_w.hidelinecheck, kHideLineChkId, kHideLineChkText, x1, fx + fw);" in seg
    assert seg.count("k++") == 2                      # Modern's own line + the children's shared line
    assert "x1 = CellX(fx, fw, kDragCells, 1)" in seg
    assert "hideLineRow ? HideMoveLineDimmed()" in PREFS


def test_a_dimmed_row_reads_unchecked():
    """Every dimmed row reads UNCHECKED whatever it stores (owner 2026-11-14: "Constrain Mouse to Window" stayed checked
    in Borderless) -- the right-drag map cell's rule, for all of them; the stored value is kept."""
    a = PREFS.index("void __fastcall CheckContentDraw(")
    body = PREFS[a:PREFS.index("\n}\n", a)]
    assert body.index("const bool dim =") < body.index("const bool on = !dim && (")
    assert "clipRow ? !VidModeFullscreenRunning()" in body and "dim ? g_greyText" in body
