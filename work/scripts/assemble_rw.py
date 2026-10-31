#!/usr/bin/env python
"""Assembler for the HQ REPORT SCREENS bake (ReportWin 0x876478 / ReportIf 0x885F38), 2026-09-04.
Ports the user-verified prototype hook_report_scale_proto.js v9.8 (F2 Technology page; pixel-audited
4K/1600/1920: strokes K, channels s(2), stripes P-law, gap s(2), no creep) into pcave2 thunks.

Two groups (same code region, one assembler):
  rw_scale_shared  the levers EVERY report kind goes through: window/clip/fonts lever at
                   init_report_screen, the bottom DATALINKS/CLOSE row (build imms, 0x4B/gap caves,
                   2dzoom gate admission, label font), the row frame + window border/backdrop, the
                   list scrollbar (width + g_rail_sb stash), the wheel, the bmxt snapshot store.
  rw_scale_tech    the F2 (kind 2) page + its console: header caves/insets, card cells, tech-range
                   bracket (DL tech imm table applied/reverted per paint + g_dl_exec), header
                   restripe, console painter imms, research bars (bypass + restripe), kind/faction
                   tab icons + geometry, toggles, title inset, crest.
Mechanisms:
  imm table  g_rw_immtab: (site,a,b,bits) rows in the DL walker format (assemble_dl KINDBITS), walked
             ONCE by t_dl_immfix at init_report_screen's return (report-only code: activate, the
             console painter, the F2 branch, the show path) — g is fixed for the session.
  tech table g_rw_immtab_tech: the 162 GEN.IMMS tech rows (no PTR rows) + assemble_dl.TECH_EXTRA_IMMS applied with g at every
             report-side tech_page call and REVERTED (g=16) after it (the range is DL-shared).
  thunks     CALL helpers (E8-entered, consume the ret) or detours (E9, prologue replay).
Every lever is a no-op at g<=16: the init leave thunk returns immediately, the walker is identity
at 16, the caves compute s(v)=v at 16, the bar bypass is what vanilla does anyway.
Parity: tests/test_rw_asm_parity.py (Unicorn).
"""
from __future__ import annotations

import contextlib
import io
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
import assemble_se as SE  # noqa: E402
import scaling_laws as SL  # noqa: E402
with contextlib.redirect_stdout(io.StringIO()):
    import assemble_dl as AD  # noqa: E402
    import assemble_dw as DW  # noqa: E402
    import dl_imms_gen as GEN  # noqa: E402
import assemble_rw_kinds as RK  # noqa: E402

PCAVE2 = 0x00A0C000
SECTION_END = 0x2B000
OFF_CODE = 0x23440            # first 16-aligned offset in the free region 0x23433..0x27E00 (cave_map --fit)
OFF_LIMIT = 0x27640           # thunk_art_reblit_body (popup_art_reblit v2, 2026-10-04); g_dl_* cells start at 0x27E00

# ---- engine VAs ---------------------------------------------------------------
G            = 0x00668740     # g_popup_scale_num
RW           = 0x00876478     # ReportWin
RW_CANVAS    = RW + 0x444
RI           = 0x00885F38     # ReportIf
MW_CANVAS    = 0x007AEC64
SW, SH       = 0x009B7B1C, 0x009B7B20
STRIP_H      = 0x007AF59C     # live scaled console strip height
FIND_FONT    = 0x005882F0     # cdecl (size, style)
FONT_INIT    = 0x00618F40     # thiscall(this, name, size, flags) RET 0xC
AN_STR       = PCAVE2 + 0x800 # "Arial Narrow" (popup arc's scaled-font name string)
# font_face_law helpers (assemble_fontlaw.py, 2026-09-17): find_font drop-ins that take the NATIVE size
T_FFN          = PCAVE2 + 0x2E570   # t_ffn(S, v) cdecl -> Font* (the pool's face/weight law at g)
T_FDIRECT_A14B = PCAVE2 + 0x2E590   # t_fdirect_a14b() cdecl -> the shared Arial fl(14g/16) bold slot (0x6E84B4 family)
RESIZE       = 0x005D5540     # GraphicWin_resize thiscall (self, w, h, a4)
TECH_PAGE    = 0x00498B30
TECH_HOVER   = 0x0049B220     # ReportWin_tech_hover(id, state) thiscall RET 8 = ReportWin vtbl+0xA0 (F2 entry; DL calls it E8 @0x432029)
RW_VTBL_HOVER = 0x0066D7F4    # ReportWin vtbl 0x66D754 + 0xA0
SCROLL_SMALL, SCROLL_NORMAL = 0x005883D0, 0x00588340
LISTBOX_CLOSE = 0x00609F20
SB_INIT_INNER, SB_INIT_RESUME = 0x006054D0, 0x006054D5
BOX_SPRITE, BOX_SPRITE_RESUME = 0x005E2DD3, 0x005E2DD8
G_SCROLLBAR_W = 0x009B8DD4
IAT_LOADLIB, IAT_GETPROC, IAT_VIRTUALALLOC = 0x00669120, 0x00669124, 0x00669134
GET_TARGET, CHEVRON, MODAL_TOP, BASEPOP = 0x005F6A50, 0x00606B20, 0x009B7AE0, 0x009B8D7C
KIND = 0x00885F40
IRS, IRS_RESUME = 0x004A3460, 0x004A3465          # init_report_screen (5B prologue 55 8B EC 6A FF)
LABS, LABS_RESUME = 0x004A7000, 0x004A7009        # kind-2 console painter (9B prologue)
FONT_FIXED = 0x006E84B4
FONT_PUSH_TECH = list(GEN.FONT_PUSH)              # 6 tech button label pushes (DL-shared range)
FONT_PUSH_RW = [0x4A4473, 0x4A452C, 0x4A461A, 0x4A46D2] + RK.FONT_PUSH_KINDS   # CLOSE, DATALINKS, toggles 0x92/0x93 + the 20 kinds-page buttons
TXTBOX_IMM, SPACER_IMM = 0x498D09, 0x498D10       # imm32 absolute-y constants (0x2F / 0x31)
FONTS = [(10, 0), (12, 0), (12, 2), (12, 1), (14, 0), (14, 2), (14, 1), (16, 0), (16, 2), (16, 1),
         (11, 0), (26, 0), (18, 2), (22, 0), (32, 0)]
SEEDS_WIDE = [0, 0x2A, 0x54, 0x7E, 0xA8, 0xD2, 0xFC]
BAR_SITES = [0x4A7DF2, 0x4A7E31, 0x4A7F8F, 0x4A7FCE, 0x4A812C, 0x4A816B, 0x4A82C8, 0x4A8307]
SPACER_SETS = [0x78DB18, 0x78DB90, 0x78DC08, 0x78DC80, 0x78DAC8, 0x78DB40, 0x78DBB8, 0x78DC30]
TXTBOX_SET = 0x78D550
TECH_CALLERS = [0x496D3E, 0x496EEF, 0x496F58]     # report-side callers of ReportWin_tech_page

# ---- existing pcave2 symbols --------------------------------------------------
G_DL_IMMG, G_DL_EXEC, G_DL_SNAPBUF = PCAVE2 + 0x27E10, PCAVE2 + 0x27E00, PCAVE2 + 0x27E78
G_NETWIN     = PCAVE2 + 0x4800
G_RAIL_SB    = PCAVE2 + 0x11260
HOLLOWFLAT   = PCAVE2 + 0x140
DEVFILL      = PCAVE2 + 0x42A0
G_FSR        = PCAVE2 + 0x1010                    # g_faction_scratch_rect (exact-fill source rect)
G_FC_EXACT   = PCAVE2 + 0x2554                    # g_fc_exact (consumed by thunk_frame_enlarge)
FACTION_PORTRAIT = PCAVE2 + 0x2100
T_DL_IMMFIX  = PCAVE2 + 0x22000
T_DL_BMXT    = PCAVE2 + 0x22680
DL_WHEEL_DOWN, DL_WHEEL_UP = PCAVE2 + 0x13DB0, PCAVE2 + 0x23210   # down v2 relocated 2026-09-22 (assemble_dl.WHEEL_DOWN_OFF); chained by a literal E9
BTN_GATE     = PCAVE2 + 0xA9E0
STR_K32, STR_VP = PCAVE2 + 0x106C0, PCAVE2 + 0x106D0
PAGE_RWX = 0x40
VP_PAGE = 0x0049C000                                # report-only code past the DL walker's own VP window (see vp_len)
DL_VP_LO, DL_VP_HI = AD.VP_PAGE, AD.VP_PAGE + AD.VP_LEN   # 0x429000..0x49C000: t_dl_immfix's bootstrap VP

HD, FL = SE.HD, SE.FL
K = {k: v for k, v in vars(AD).items() if k.startswith("K_")}
KINDBITS = AD.KINDBITS

# ---- imm table (report-only rows; one-shot at init) ----------------------------
# (imm address, width, a, b, label)  value = s(a) - s(b) (HD kind); width 4 = imm32
RW_IMMS = [
    # F2 card setup (0x498C5A+, imm32)
    (0x498C67, 4, 0xBE, 0, "card/btn w 0xBE -> [+0x59A0]/[+0x59A8]"),
    (0x498C8C, 4, 0x28, 0, "btn h 0x28 -> [+0x59A4]"),
    (0x498CDE, 4, 0, 0xBE, "card centring -0xBE"),
    (0x498CF1, 4, 0xAE, 0, "card h 0xAE"),
    (0x498CFC, 4, 0xBE, 0, "card right +0xBE"),
    # F2 header insets (imm8)
    (0x498C85, 1, 3, 0, "icon/inner x anchor +3"),
    (0x498CB0, 1, 0, 3, "band right -3"),
    (0x498CBC, 1, 0, 3, "band bottom -3"),
    (0x498CDB, 1, 0x1D, 0, "band->card gap 0x1D"),
    (0x498D4F, 1, 3, 0, "header text x +3"),
    (0x498D60, 1, 5, 0, "header text y +5"),
    (0x49911E, 1, 3, 0, "no-research spacer x0 +3"),
    (0x499177, 1, 5, 0, "line-2 y +5"),
    (0x499181, 1, 3, 0, "line-2 y +lineH+3"),
    # F2 card: the last native coordinate imms of the F2-only branch (2026-10-25 F45, law SL.rw_tech_card_imms;
    # appended to this once-per-session table like every F2-branch row above: the Datalinks path never runs them)
    (0x498DBF, 1, 3, 0, "blind-research text box L = band L +3 (lea eax,[edx+3]; R inset = row 0x498CB0)"),
    (0x498DC5, 1, 5, 0, "blind-research text x = box L +5"),
    (0x499171, 1, 3, 0, "line-2 x = text box L +3 (line 1 = row 0x498D4F)"),
    (0x498FDD, 1, 0xF, 0, "research name -> next text piece gap +0xF"),
    (0x49948A, 1, 4, 0, "'Breakthroughs every' -> 'Next breakthrough' gap +4"),
    (0x4992C7, 4, 7, 0, "research bracket 1: clip rect outset 7 (mov eax,7)"),
    (0x499334, 4, 7, 0, "research bracket 1: inset back 7 (mov eax,7)"),
    (0x49938B, 4, 7, 0, "research bracket 2: clip rect outset 7 (mov eax,7)"),
    (0x4993FB, 4, 7, 0, "research bracket 2: inset back 7 (mov eax,7)"),
    # console painter (kind 2): research bars 0xF x9
    (0x4A7CBD, 1, 0xF, 0, "bar: label-region h = pitch - 0xF"),
    (0x4A7DE9, 1, 0xF, 0, "EXPLORE bar bottom"), (0x4A7E4E, 1, 0xF, 0, "advance"),
    (0x4A7F86, 1, 0xF, 0, "DISCOVER bar bottom"), (0x4A7FEB, 1, 0xF, 0, "advance"),
    (0x4A8123, 1, 0xF, 0, "BUILD bar bottom"), (0x4A8188, 1, 0xF, 0, "advance"),
    (0x4A82BF, 1, 0xF, 0, "CONQUER bar bottom"), (0x4A8324, 1, 0xF, 0, "advance"),
    # console painter: left panel / tab box / list rect / row pitch
    (0x4A7023, 1, 6, 0, "L cursor x +6"), (0x4A7026, 1, 6, 0, "L cursor y +6"),
    # (0x4A7038 / 0x4A7052 `w/h -0xC` rows REMOVED 2026-10-17: inside the t_rw_labs_w / t_rw_labs_h detours, which
    #  compute span - 2*s(6) -- law rw_console_inset_w; s(0xC) != 2*s(6) at g=25)
    (0x4A708B, 1, 0x1A, 0, "tab-area box h 0x1A"),
    (0x4A70A4, 1, 2, 0, "list box top +2"), (0x4A70A7, 1, 6, 0, "list box bottom -6"),
    (0x4A70CF, 1, 0x20, 0, "list content top +0x20"), (0x4A70D2, 1, 0, 0x20, "list content h -0x20"),
    (0x4A70F8, 4, 0, 3, "list rect -3 (eax)"),
    (0x4A70FE, 1, 3, 0, "list rect +3"), (0x4A7108, 1, 3, 0, "list rect +3"),
    (0x4A713C, 1, 3, 0, "row pitch = lineH + 3"),
    # console painter: right panel cursor + bar block insets + label x
    (0x4A7A67, 1, 6, 0, "R cursor x +6"), (0x4A7A6A, 1, 6, 0, "R cursor y +6"),
    # (0x4A7A80 / 0x4A7A97 `R w/h -0xC` rows REMOVED 2026-10-17: inside t_rw_labs_rw / t_rw_labs_rh, span - 2*s(6))
    (0x4A7ABB, 1, 6, 0, "title box bottom +6"), (0x4A7AE6, 1, 2, 0, "divider +2"), (0x4A7AE9, 1, 6, 0, "body bottom -6"),
    (0x4A7C2F, 1, 0, 4, "h -4"), (0x4A7C40, 1, 4, 0, "title text y +4"),
    (0x4A7CA0, 1, 0, 2, "h -2"), (0x4A7CA3, 1, 3, 0, "bar area x +3"), (0x4A7CBA, 1, 0, 6, "bar w -6"),
    (0x4A7DC8, 1, 8, 0, "first bar y +8"),
    (0x4A7F33, 1, 2, 0, "label x +2"), (0x4A80D0, 1, 2, 0, "label x +2"), (0x4A8267, 1, 2, 0, "label x +2"), (0x4A8408, 1, 2, 0, "label x +2"),
    (0x4A7737, 1, 0xA, 0, "centre title y +10"),
    # ReportIf_activate: DATALINKS/CLOSE row build
    (0x4A43AB, 1, 7, 0, "row top = textB + 7"),
    (0x4A43B9, 1, 0x14, 0, "row bottom = top + 0x14"),
    (0x4A442B, 1, 0x14, 0, "CLOSE h 0x14"), (0x4A44E8, 1, 0x14, 0, "DATALINKS h 0x14"),
    # (0x4A43D2 -0x96 row REMOVED in bake v4: the right edge is now clipL + clipR - L in t_rw_btnr, so the
    #  row is centred on the clip at every g -- s(0x96) != 2*s(0x4B) at g=40 gave a 1px right-channel loss)
    # ReportIf_activate: TECHNOLOGY/BASES toggles
    (0x4A455C, 1, 9, 0, "toggles x +9"), (0x4A455F, 1, 9, 0, "toggles y +9"), (0x4A4571, 1, 0x12, 0, "toggles w -0x12"),
    # (0x4A45CC TECH h 0x14 row REMOVED 2026-10-17: t_rw_tabsplit1 v2 writes the TECH rect itself and resumes past it)
    # ReportIf_activate: faction tabs + crest
    (0x4A5AEF, 1, 5, 0, "faction tab w +5 (wide mask)"), (0x4A5AF2, 1, 0x25, 0, "faction tab w 0x25"),
    (0x4A5B19, 1, 5, 0, "faction tab w +5 (wide mask)"), (0x4A5B1C, 1, 0x25, 0, "faction tab w 0x25"),
    (0x4A5B77, 1, 0x1D, 0, "faction tab h 0x1D"),
    (0x4A5B33, 1, 0xF, 0, "crest x +0xF"), (0x4A5B36, 1, 0xF, 0, "crest y +0xF"),
    # ReportIf_activate: kind-tab button size (after the static mov-imm32 rewrite; excluded from the identity audit)
    (0x4A42E1, 4, 0x24, 0, "kind-tab h (sprite 0x24)"), (0x4A42E7, 4, 0x1E, 0, "kind-tab w (sprite 0x1E)"),
    # ReportIf_console_chrome 0x4A3D20 (every repaint): panel insets +-3 (d5a0) and restore; centre/strip
    # +-4 (d5a0), +-(7-4) more (d528), restore -+7 -- the restore is s(7) so the d528 inset MUST be
    # s(7)-s(4) (s(3)+s(4) != s(7) at g=22); strip frame drawn at x-7/+7 under the clip
    (0x4A3D7C, 1, 0, SL.RW_STRIP_FRAME_SHIFT, "strip frame x -7"), (0x4A3D93, 1, SL.RW_STRIP_FRAME_SHIFT, 0, "strip frame x +7 restore"),
    (0x4A3DA6, 4, 3, 0, "panels L/T +3"), (0x4A3DB5, 4, 0, 3, "panels R/B -3"),
    (0x4A3DE7, 4, 4, 0, "centre/strip L/T +4"), (0x4A3DF3, 4, 0, 4, "centre/strip R/B -4"),
    (0x4A3E59, 4, 7, 4, "centre/strip d528 inset +(s7-s4)"), (0x4A3E68, 4, 4, 7, "centre/strip d528 inset -(s7-s4)"),
    (0x4A3EBC, 4, 3, 0, "panels restore +3"), (0x4A3EC7, 4, 0, 3, "panels restore -3"),
    (0x4A3F0E, 4, 0, 7, "centre/strip restore -7"), (0x4A3F18, 4, 7, 0, "centre/strip restore +7"),
    # ReportWin show path: row frame grow/shrink
    (0x496CAA, 1, 0, 3, "row frame L -3"), (0x496CAD, 1, 0, 3, "row frame T -3"),
    (0x496CBC, 4, 3, 0, "row frame R/B +3"), (0x496CE7, 4, 0, 3, "row frame R/B shrink -3"),
]
IDENTITY_EXEMPT = {0x4A42E1, 0x4A42E7}
HOF_ROW_RANGE = (0x448000, 0x44B000)   # the proto's 57 Hall of Fame rows: owned by the hof_scale bake (assemble_mon.py) since 2026-09-14


def hof_rows_dropped():
    return [r for r in RK.KINDS_IMMS if HOF_ROW_RANGE[0] <= r[0] < HOF_ROW_RANGE[1]]


# ---- console chrome chain rows (2026-10-17): law scaling_laws.rw_console_box_inset / rw_console_step / rw_tab_inset ----
# Each value is a signed integer combination of s(v) terms (SL.RW_SUM_TERMS[key] x mult), which t_dl_immfix's
# s(a) - s(b) [x2/x3] rows cannot express -> stored by t_rw_immsum (the rw walker wrapper) from its own table, kept in
# g_rw_immtab's footprint after the HD rows' terminator.  These sites are NOT HD rows any more.
#   (site, width, key, mult, label)
CHAIN_ROWS = [
    # ReportIf_console_chrome: the centre / strip d528 sits one step inside its d5a0 (was s7 - s4; restores s4 + U)
    (0x4A3E59, 4, "U", 1, "centre/strip d528 L/T = d5a0 + U"), (0x4A3E68, 4, "U", -1, "centre/strip d528 R/B = d5a0 - U"),
    (0x4A3F0E, 4, "Q", -1, "centre/strip restore -(s4 + U)"), (0x4A3F18, 4, "Q", 1, "centre/strip restore +(s4 + U)"),
    # labs (F2): content cursors x/y = region + C (w/h: t_rw_labs_* detours, 2C); list / body bottoms = region B - C
    (0x4A7023, 1, "C", 1, "labs L x"), (0x4A7026, 1, "C", 1, "labs L y"), (0x4A70A7, 1, "C", 1, "labs list box B = B - C"),
    (0x4A7A67, 1, "C", 1, "labs R x"), (0x4A7A6A, 1, "C", 1, "labs R y"), (0x4A7AE9, 1, "C", 1, "labs body B = B - C"),
    # energy (F3)
    (0x4A84D4, 1, "C", 1, "energy L x"), (0x4A84D7, 1, "C", 1, "energy L y"), (0x4A84ED, 1, "C", 2, "energy L w"), (0x4A8504, 1, "C", 2, "energy L h"),
    (0x4A8BEE, 1, "C", 1, "energy R x"), (0x4A8BF1, 1, "C", 1, "energy R y"), (0x4A8C05, 1, "C", 2, "energy R w"), (0x4A8C14, 1, "C", 2, "energy R h"),
    # ops (F4): tab box x/y (w: t_rwk_ops_w), BEST BASES list box B, list h = H - (s(0x28) + C); BASE LOCATOR title
    (0x4A90B6, 1, "C", 1, "ops tab box y"), (0x4A90D4, 1, "C", 1, "ops tab box x"), (0x4A9112, 1, "C", 1, "ops list box B = B - C"),
    (0x4A90D1, 1, "L28C", 1, "ops list h = H - s(0x28) - C"),
    (0x4A9E01, 1, "C", 1, "ops R x"), (0x4A9E04, 1, "C", 1, "ops R y"), (0x4A9E19, 1, "C", 2, "ops R w"), (0x4A9E26, 1, "C", 2, "ops R h"),
    (0x4A9E58, 4, "U", 1, "locator d5a0 R/B = d528 + U"), (0x4A9E5D, 4, "U", -1, "locator d5a0 L/T = d528 - U"),
    (0x4A9E94, 1, "U", 1, "locator d528 x = d5a0 + U"), (0x4A9E9C, 1, "U", 1, "locator d528 y = d5a0 + U"),
    # projects (F5)
    (0x4AA16A, 1, "C", 1, "projects L x"), (0x4AA16D, 1, "C", 1, "projects L y"), (0x4AA182, 1, "C", 2, "projects L w"), (0x4AA199, 1, "C", 2, "projects L h"),
    (0x4AA1C8, 1, "C", 1, "projects body B = B - C"),
    (0x4AA64E, 1, "C", 1, "projects R x"), (0x4AA651, 1, "C", 1, "projects R y"), (0x4AA666, 1, "C", 2, "projects R w"), (0x4AA673, 1, "C", 2, "projects R h"),
    (0x4AA6A5, 4, "U", 1, "locator d5a0 R/B = d528 + U"), (0x4AA6AA, 4, "U", -1, "locator d5a0 L/T = d528 - U"),
    (0x4AA6E1, 1, "U", 1, "locator d528 x = d5a0 + U"), (0x4AA6EE, 1, "U", 1, "locator d528 y = d5a0 + U"),
    # sat (F6): attack / survey layouts, both panels
    (0x4AA9A3, 1, "C", 1, "sat L x (survey)"), (0x4AA9A6, 1, "C", 1, "sat L y"), (0x4AA9BB, 1, "C", 2, "sat L w"), (0x4AA9D2, 1, "C", -2, "sat L h (add -2C)"),
    (0x4AAB65, 1, "C", 1, "sat L x"), (0x4AAB68, 1, "C", 1, "sat L y"), (0x4AAB7D, 1, "C", 2, "sat L w"), (0x4AAB94, 1, "C", 2, "sat L h"),
    (0x4AABC3, 1, "C", 1, "sat L body B = B - C"),
    (0x4AAF99, 1, "C", 1, "sat R x (survey)"), (0x4AAF9C, 1, "C", 1, "sat R y"), (0x4AAFB0, 1, "C", 2, "sat R w"), (0x4AAFBF, 1, "C", -2, "sat R h (add -2C)"),
    (0x4AB13F, 1, "C", 1, "sat R x"), (0x4AB142, 1, "C", 1, "sat R y"), (0x4AB156, 1, "C", 2, "sat R w"), (0x4AB162, 1, "C", 2, "sat R h"),
    (0x4AB19C, 1, "C", 1, "sat R body B = B - C"),
    (0x4AB295, 1, "P", 1, "sat target buttons x = L + P"), (0x4AB2A8, 1, "P", 2, "sat target buttons w = W - 2P"),
    (0x4AB298, 1, "Y", 1, "sat target buttons y = T + Y (body top + U)"),
    # F6 SELECT FACTION TARGET (ReportIf_activate 0x4A574D, LEFT panel): the mirror of the satellite target list (fix 4g)
    (0x4A5755, 1, "P", 1, "faction-target buttons x = L + P"), (0x4A576A, 1, "P", 2, "faction-target w = W - 2P"),
    (0x4A5758, 1, "Y", 1, "faction-target buttons y = T + Y (body top + U)"),
    # units (F7)
    (0x4AB623, 1, "C", 1, "units L x"), (0x4AB626, 1, "C", 1, "units L y"), (0x4AB63B, 1, "C", 2, "units L w"), (0x4AB652, 1, "C", 2, "units L h"),
    (0x4AB681, 1, "C", 1, "units L body B = B - C"),
    (0x4ABC9B, 1, "C", 1, "units R x"), (0x4ABC9E, 1, "C", 1, "units R y"), (0x4ABCB2, 1, "C", 2, "units R w"), (0x4ABCC1, 1, "C", 2, "units R h"),
    (0x4ABCEF, 1, "C", 1, "units R body B = B - C"),
    (0x4A5505, 1, "P", 1, "unit command buttons x = L + P"), (0x4A551E, 1, "P", 2, "unit command buttons w = W - 2P"),
    (0x4A5508, 1, "Y", 1, "unit command buttons y = T + Y (body top + U)"),
    # score (F8)
    (0x4ABE90, 1, "C", 1, "score L x"), (0x4ABE93, 1, "C", 1, "score L y"), (0x4ABEA8, 1, "C", 2, "score L w"), (0x4ABEBF, 1, "C", -2, "score L h (add -2C)"),
    (0x4AC0CE, 1, "C", 1, "score R x"), (0x4AC0D1, 1, "C", 1, "score R y"), (0x4AC0E5, 1, "C", 2, "score R w"), (0x4AC0F1, 1, "C", -2, "score R h (add -2C)"),
    # intel (kind 0)
    (0x4AC1AF, 1, "C", 1, "intel L x"), (0x4AC1B2, 1, "C", 1, "intel L y"), (0x4AC1C4, 1, "C", 2, "intel L w"), (0x4AC1DE, 1, "C", 2, "intel L h"),
    (0x4AC64F, 1, "C", 1, "intel R x"), (0x4AC652, 1, "C", 1, "intel R y"), (0x4AC666, 1, "C", 2, "intel R w"), (0x4AC675, 1, "C", 2, "intel R h"),
    # ReportWin_draw_energy canvas text / list rects: x + s(6), w = W - 2*s(6) (law rw_console_inset_w; was W - s(0xC))
    (0x49BFCA, 1, "S6", 2, "energy canvas text w = W - 2*s(6)"), (0x49CC25, 1, "S6", 2, "energy canvas list w = W - 2*s(6)"),
]
# the console painters' d528 box draws still reaching Buffer_box_sprite natively (-> thunk_hud_boxframe, inclusive)
D528_SITES = [
    (0x4A8549, "ReportIf_console_energy", "BASE EXPENDITURES title"), (0x4A863A, "ReportIf_console_energy", "BASE EXPENDITURES list"),
    (0x4A8C32, "ReportIf_console_energy", "MAINTENANCE COSTS title"), (0x4A8CEF, "ReportIf_console_energy", "MAINTENANCE COSTS list"),
    (0x4A9EB5, "ReportIf_console_ops", "BASE LOCATOR title"),
    (0x4AA1B8, "ReportIf_console_projects", "PROJECT DESCRIPTION title"), (0x4AA1E3, "ReportIf_console_projects", "PROJECT DESCRIPTION body"),
    (0x4AA702, "ReportIf_console_projects", "BASE LOCATOR title"),
    (0x4AA9EB, "ReportIf_console_sat", "survey left"), (0x4AABB3, "ReportIf_console_sat", "SELECT FACTION TARGET title"),
    (0x4AABDE, "ReportIf_console_sat", "SELECT FACTION TARGET body"), (0x4AAFD7, "ReportIf_console_sat", "survey right"),
    (0x4AB189, "ReportIf_console_sat", "SELECT SATELLITE TARGET title"), (0x4AB1B4, "ReportIf_console_sat", "SELECT SATELLITE TARGET body"),
    (0x4AB671, "ReportIf_console_units", "UNIT TYPES title"), (0x4AB69C, "ReportIf_console_units", "UNIT TYPES body"),
    (0x4ABCDF, "ReportIf_console_units", "AUTOMATE UNITS title"), (0x4ABD0A, "ReportIf_console_units", "AUTOMATE UNITS body"),
    (0x4ABED8, "ReportIf_console_score", "left"), (0x4AC10C, "ReportIf_console_score", "right"),
    (0x4AC224, "ReportIf_console_intel", "left title"), (0x4AC2E4, "ReportIf_console_intel", "left body"),
    (0x4AC693, "ReportIf_console_intel", "right title"), (0x4AC752, "ReportIf_console_intel", "right body"),
]
SUM_TERMS = dict(SL.RW_SUM_TERMS, S6=((1, 6),))
# "S6" (plain s(6), not a chain law) belongs to the two ReportWin_draw_energy CANVAS rects only -- never a console box
# (fix 4g: a console row keyed S6 is self-consistent at g = 16 and passes every per-row test; C != s(6) at most g)
S6_SITES = {0x49BFCA, 0x49CC25}
assert {site for site, _w, key, *_ in CHAIN_ROWS if key == "S6"} == S6_SITES, "S6 key outside the energy canvas rects"
SUM_CONT = 0x40000000      # t_rw_immsum: site bit 30 = continuation (add the row's 4 terms, store nothing; the next row
                           # carries on the same sum) -- a law with more than 4 terms spans ceil(n/4) table rows


def chain_terms(key: str, mult: int):
    """The row's (coef, v) terms (any count; the table splits them 4 per t_rw_immsum row)."""
    t = tuple((c * mult, v) for c, v in SUM_TERMS[key])
    assert all(-128 <= c <= 127 and 0 <= v <= 255 for c, v in t), (key, mult, t)
    return t


def sum_tab_bytes() -> bytes:
    """t_rw_immsum rows: 12 B each = dword site (bit 31 = dword store, bit 30 = continuation) + 4 x (coef int8,
    v uint8); 0 terminator.  A CHAIN_ROWS entry whose law has n > 4 terms emits ceil(n/4) rows, all but the last
    flagged SUM_CONT (their site field = the store site | SUM_CONT, never 0)."""
    out = bytearray()
    for site, w, key, mult, _lbl in CHAIN_ROWS:
        if w == 1:                                                   # a sign-extended imm8 at every reachable g
            assert all(-128 <= SL.rw_sum_value(chain_terms(key, mult), g) <= 127 for g in range(17, SL.G_MAX + 1)), hex(site)
        t = list(chain_terms(key, mult))
        chunks = [t[i:i + 4] for i in range(0, len(t), 4)]
        for i, ch in enumerate(chunks):
            last = i == len(chunks) - 1
            out += struct.pack("<I", site | (0x80000000 if w == 4 and last else 0) | (0 if last else SUM_CONT))
            for c, v in (ch + [(0, 0)] * 4)[:4]:
                out += struct.pack("<bB", c, v)
    out += b"\x00" * 4
    return bytes(out)


CHAIN_SITES = {r[0] for r in CHAIN_ROWS}


def rw_rows():
    rows = []
    for site, w, a, b, _lbl in RW_IMMS:
        if site in CHAIN_SITES:                                      # stored by t_rw_immsum (CHAIN_ROWS)
            continue
        rows.append((site, a, b, KINDBITS['HD'] | (K['K_W4'] if w == 4 else 0)))
    kinds_sites = {r[0] for r in RK.KINDS_IMMS}
    assert set(RK.DETOUR_COVERED_ROWS) <= kinds_sites, "DETOUR_COVERED_ROWS must name proto rows"
    for site, w, a, b, _lbl in RK.KINDS_IMMS:                       # rw_scale_kinds: the proto's 400 rows
        if site in RK.DETOUR_COVERED_ROWS:                           # displaced into a seam cave (see the dict)
            continue
        if HOF_ROW_RANGE[0] <= site < HOF_ROW_RANGE[1]:              # Hall of Fame: the hof_scale bake's own table at ITS num
            continue
        if site in CHAIN_SITES:                                      # stored by t_rw_immsum (CHAIN_ROWS)
            continue
        rows.append((site, a, b, KINDBITS['HD'] | (K['K_W4'] if w == 4 else 0)))
    for site, a, _lbl in RK.VEH_ROWS:                                # unit/base icon size pushes (veh_size_scaled)
        rows.append((site, a, 0, KINDBITS['VEH']))
    assert len({r[0] for r in rows}) == len(rows), "duplicate imm row sites"
    return rows


def tech_rows():
    rows = []
    for site, off, w, kind, a, b, t, _lbl in GEN.IMMS:
        if not t:
            continue
        rows.append((site + off, a, b, KINDBITS[kind] | (K['K_W4'] if w == 4 else 0)))
    return rows + AD.tech_extra_rows()      # F44 (2026-10-25): the non-Datalinks odd row pair, one list for both tech tables


def row_site_conflicts(rows, sites):
    """Walker rows that touch a patched site. A row may overlap a site ONLY through the imm32 field of a
    `mov r32, imm32` rewrite (site bytes B8+r at va, row at va+1, 4 wide -- the kind-tab rewrites). Anything
    else is rewritten at RUNTIME by the walker: a row inside a detour's E9 / a redirect's E8 rel32 corrupts the
    jump (bake v1a: the 0x14 row at 0x4A4851 inside the gov_split2 detour made it jump to 0xA27B20 -> F2 crash).
    sites = [(va, length, first_new_byte, id)]. Returns [(row site, site id)]."""
    bad = []
    for site, _a, _b, bits in rows:
        w = 4 if bits & K['K_W4'] else 1
        for va, n, first, sid in sites:
            if site < va + n and va < site + w:
                if w == 4 and site == va + 1 and n >= 5 and 0xB8 <= first <= 0xBF:
                    continue
                bad.append((site, sid))
    return bad


def vp_len():
    """Length of the VirtualProtect window t_rw_init_leave opens at VP_PAGE (page-rounded to the last byte the
    walker stores). SIZED FROM THE TABLES: t_dl_immfix writes every row site of both tables, and a site outside
    the DL bootstrap window (DL_VP_LO..DL_VP_HI) and this one faults on the read-only .text page (bake v1's
    0xD000 constant ended at 0x4A9000; the kinds rows reach 0x4AC7A4 -> game load crashed at the walker's
    store, fault 0xA2E163)."""
    ends = [(site, site + (4 if bits & K['K_W4'] else 1)) for site, _a, _b, bits in rw_rows() + tech_rows()]
    ends += [(site, site + w) for site, w, *_ in CHAIN_ROWS]          # t_rw_immsum stores inside the same window
    n = (max(e for _s, e in ends) - VP_PAGE + 0xFFF) & ~0xFFF
    for site, end in ends:
        assert DL_VP_LO <= site and end <= VP_PAGE + n, f"imm row {site:#x} outside every VP window"
    assert VP_PAGE == DL_VP_HI, "the two windows must be contiguous (rows are only checked against their union)"
    return n


def tab_bytes(rows) -> bytes:
    out = bytearray()
    for site, a, b, bits in rows:
        out += struct.pack("<IIII", site, a & 0xFFFFFFFF, b & 0xFFFFFFFF, bits)
    out += b"\x00" * 4
    return bytes(out)


# The rw table keeps its baked footprint (2026-10-17): the tech table and every cell after it are referenced by LITERAL
# VA from other assemblers / the DLL (assemble_dw G_RW_INLIST 0x27488, assemble_popup_sb G_RW_SBS 0x27564), so a row
# removal must not move them -- the freed tail is zero padding after the walker's 0 terminator.
# 2026-10-25 F44: 32 B of that zero tail went to g_rw_immtab_tech (+2 rows): the tech table now starts at 0x26A30
# (was 0x26A50) and still ends at 0x27474, so g_rw_ret (0x27480) and every cell after it keep their VAs.  The tech
# table's only references are t_rw_techpage / t_rw_techhover's {abs32:g_rw_immtab_tech}.
RW_TAB_LEN = 6836 - 32
RW_TAB = tab_bytes(rw_rows())
RW_TAB += bytes(-len(RW_TAB) % 4)
SUM_TAB_OFF = len(RW_TAB)          # 2026-10-17: t_rw_immsum's table lives in the HD rows' freed tail (CHAIN_ROWS)
RW_TAB += sum_tab_bytes()
assert len(RW_TAB) <= RW_TAB_LEN, f"g_rw_immtab grew past its footprint ({len(RW_TAB)} > {RW_TAB_LEN})"
RW_TAB += bytes(RW_TAB_LEN - len(RW_TAB))
TECH_TAB = tab_bytes(tech_rows())

# ---- cells (after the tables; laid out by assemble_all) -------------------------
CELL_DEFS = [   # (name, size)
    ("g_rw_ret", 4), ("g_rw_labs_ret", 4), ("g_rw_inlist", 4), ("g_rw_sb", 4), ("g_rw_sbparent", 4),
    ("g_rw_font", 4), ("g_rw_vpdone", 4), ("g_rw_vpold", 4), ("g_rw_barn", 4), ("g_rw_barlist", 8 * 20),
    ("g_rw_rect", 16),
    ("g_rw_hov_exec", 4), ("g_rw_hov_netwin", 4), ("g_rw_hov_immg", 4),
] + RK.CELL_DEFS + [("g_rw_wheel_ate", 4), ("g_rwk_intel_pbot", 4)]   # v16: intel portrait drawn bottom + s(4) (appended LAST: cells before it keep their offsets)
CELL: dict[str, int] = {}     # name -> VA (filled by layout())
RK.CELL = CELL                # the kinds module reads the same dict
TAB_RW = TAB_TECH = 0


def layout_tables_and_cells(code_end_off: int):
    global TAB_RW, TAB_TECH
    off = (code_end_off + 15) & ~15
    TAB_RW = PCAVE2 + off
    off = (off + len(RW_TAB) + 15) & ~15
    TAB_TECH = PCAVE2 + off
    off = (off + len(TECH_TAB) + 15) & ~15
    cells = {}
    for name, size in CELL_DEFS:
        cells[name] = (off, size)
        off += (size + 3) & ~3
    CELL.clear()
    CELL.update({n: PCAVE2 + o for n, (o, _s) in cells.items()})
    return cells, off


# ==== thunks =====================================================================
def asm_rw_init_enter() -> str:
    # displaced 5B at init_report_screen: push ebp / mov ebp,esp / push -1
    return f"""
    pop     eax
    mov     dword ptr [{CELL['g_rw_ret']:#x}], eax
    push    t_rw_init_leave
    push    ebp
    mov     ebp, esp
    push    -1
    jmp     {IRS_RESUME:#x}
"""


# v3 line height (2026-09-26, intel PROFILE pixel audit vs the pristine): the rebuilt f12 font's metric is SUBLINEAR
# (36 at g=40 where vanilla's 15 x 2.5 = 37.5; 24 at g=25 vs 23.4) and every report row pitch, the console title
# boxes (lineH+6), the header band (lineH+9) and the list row pitch (lineH+3) consume [RW+0xE268]/[RI+0x1C]
# directly -> rows ran 0.6 native px short each (dossier row 10 at 176.8 vs 184 native).  Law
# scaling_laws.rw_line_h = scale_px(15, g) on the g>16 path (this lever); g<=16 keeps the engine's own metric read
# ([[feedback-font-metric-sublinearity]]).  15 = the native f12 metric measured on the pristine 1024 frame.
RW_LINE_H_NATIVE = 15

# v5 (2026-10-17): no page paint at init.  GraphicWin_resize(RW, w, h, 1) repaints synchronously (Win_resize ->
# vtbl+0x30 = 0x496D00), and that painter switches on g_reportwin_kind 0x885F40, which a game load never resets.
# With F3 last viewed, the resize ran ReportWin_draw_energy on the hidden window and built + showed its energy
# ListBox (RW+0x5A0C); no later page teardown closed it, so it stayed drawn over F4/F5/F7/F2.  Vanilla (g <= 16)
# never resizes here, so it never paints a page at init: the lever parks the kind at -1 for the resize (0x496D2C
# `cmp eax,8 / ja 0x496DD6` = the no-page default case; ReportWin_tech_reset at 0x496D04 still runs) and restores
# it after.  Never carry state across GraphicWin_resize -- the page kind included
# ([[feedback-resize-sync-repaint-scratch]]).
RESIZE_KIND = 0xFFFFFFFF


def asm_rw_init_leave() -> str:
    # fonts v2 (2026-09-17, audit findings 3.2a/3.2b): every report font through t_ffn(NATIVE size,
    # variant) = the face law (Arial regular/italic/bold for the <=12 natives on keyed cave slots;
    # the pool's Arial Narrow bold, sizes snapped as before, for the >12 natives while fl(S*g/16)
    # <= 40; Arial Narrow bold|variant on a slot above 40 -- v1's own scratch branch dropped the
    # bold there).  g_rw_fontscratch is no longer written (kept as a cell).
    fonts = ""
    for i, (sz, st) in enumerate(FONTS):
        fonts += f"""
    push    {st}
    push    {sz}
    call    {T_FFN:#x}
    add     esp, 8
    mov     dword ptr [{RI + 0x1E180 + 4 * i:#x}], eax
"""
    pushes = "".join(f"    mov     dword ptr [{va:#x}], eax\n" for va in FONT_PUSH_RW)
    # law rw_kind_tab_x (2026-10-18 fix 12 / N3): the 7 kind tabs anchor on the strip's DRAWN left edge
    # A = left panel R - K (rw_strip_anchor; K = (2g + 15) >> 5, t_rwk_stripanchor's own arithmetic), not on the
    # region's L (ReportIf+0x40, still untouched): L and A differ by 1 at g = 23 / 25 / 28 / 39 only.  ecx is free
    # here (reloaded from ReportIf+0x44 right after the tabs).
    tabs = f"""
    mov     ecx, dword ptr [{G:#x}]
    lea     ecx, [ecx*2+0xF]
    sar     ecx, 5
    neg     ecx
    add     ecx, dword ptr [{RI + 0x28:#x}]
"""
    for i in range(7):
        tabs += f"""
    mov     eax, {SL.RW_KIND_TAB_X0 + SL.RW_KIND_TAB_PITCH * i}
    {HD("eax")}
    add     eax, ecx
    mov     dword ptr [{RI + 0xA298 + 4 * i:#x}], eax
"""
    facs = ""
    for f in range(7):
        facs += f"""
    mov     eax, {SEEDS_WIDE[f] + 0x2B + 0x2E}
    {HD("eax")}
    add     eax, dword ptr [{RI + 0x50:#x}]
    mov     dword ptr [{RI + 0x60 + 4 * f:#x}], eax
"""
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     done
    push    ebx
    push    esi
    push    edi
    cmp     dword ptr [{CELL['g_rw_vpdone']:#x}], 0
    jne     vpok
    push    {STR_K32:#x}
    call    dword ptr [{IAT_LOADLIB:#x}]
    test    eax, eax
    je      bail
    push    {STR_VP:#x}
    push    eax
    call    dword ptr [{IAT_GETPROC:#x}]
    test    eax, eax
    je      bail
    push    {CELL['g_rw_vpold']:#x}
    push    {PAGE_RWX:#x}
    push    {vp_len():#x}
    push    {VP_PAGE:#x}
    call    eax
    test    eax, eax
    je      bail
    mov     dword ptr [{CELL['g_rw_vpdone']:#x}], 1
vpok:
    mov     eax, dword ptr [{G_DL_IMMG:#x}]
    push    eax
    mov     eax, dword ptr [{G:#x}]
    mov     dword ptr [{G_DL_IMMG:#x}], eax
    mov     esi, {TAB_RW:#x}
    call    t_rw_immsum
    pop     eax
    mov     dword ptr [{G_DL_IMMG:#x}], eax
    mov     esi, {RW:#x}
    mov     eax, dword ptr [esi+0xA1C]
    {FL("eax")}
    mov     edi, eax
    mov     eax, dword ptr [esi+0xA20]
    {FL("eax")}
    mov     ebx, eax
    mov     dword ptr [esi+0xA1C], edi
    mov     dword ptr [esi+0xA20], ebx
    mov     eax, dword ptr [{SH:#x}]
    sub     eax, ebx
    sub     eax, dword ptr [{STRIP_H:#x}]
    mov     dword ptr [esi+0xA18], eax
    mov     dword ptr [{CELL['g_rw_rect'] + 4:#x}], eax
    ; v5 (2026-10-17) law rw_window_rects: the frame ABUTS the slide rails through their own railscale cascades --
    ; R = fl((fl(cw*16/g) - 0x37)*g/16) (the inner right strip's x); L = fl(15g/16) + fl(8g/16) (the two left
    ; strips' extent); clip = frame inset s(3) on L/T/R in ONE cascade, bottom H - s(0x35).  rw_window_x: the frame
    ; (width R-L) is centred, A14 = (SW - (R-L)) >> 1, and the window starts L left of it (g_rw_rect+0, read back
    ; after the resize; v4 re-derived s(0x17) there).
    ; v6 (2026-10-17) law rw_canvas_w: the canvas cw (g_rw_rect+8) = ceil(N*g/16), N = ceil(W*16/g) + 0x4E (the
    ; native canvas, W's exact descale) -- the unique width whose railscale descale fl(cw*16/g) is N itself, so R =
    ; fl((N - 0x37)*g/16) = vanilla x g/16 (v5's W + s(0x4E) descaled 1 short at most g: R 1-2 px left).
    mov     ecx, dword ptr [{G:#x}]
    mov     eax, edi
    shl     eax, 4
    add     eax, ecx
    dec     eax
    xor     edx, edx
    div     ecx
    add     eax, {SL.RW_WIN_EXTRA:#x}
    push    eax
    imul    eax, ecx
    add     eax, 15
    shr     eax, 4
    mov     dword ptr [{CELL['g_rw_rect'] + 8:#x}], eax
    pop     eax
    sub     eax, {SL.SE_RAIL_RIGHT_OFF:#x}
    {FL("eax")}
    mov     dword ptr [esi+0x598C], eax
    mov     ecx, {SL.SE_RAIL_LEFT_STRIPS[0]}
    {FL("ecx")}
    mov     edx, {SL.SE_RAIL_LEFT_STRIPS[1]}
    {FL("edx")}
    add     ecx, edx
    mov     dword ptr [esi+0x5984], ecx
    mov     dword ptr [esi+0x5988], 0
    mov     dword ptr [esi+0x5990], ebx
    mov     edx, 3
    {HD("edx")}
    mov     dword ptr [esi+0x5978], edx
    sub     eax, edx
    mov     dword ptr [esi+0x597C], eax
    add     eax, edx
    sub     eax, ecx
    neg     eax
    add     eax, dword ptr [{SW:#x}]
    sar     eax, 1
    mov     dword ptr [esi+0xA14], eax
    sub     eax, ecx
    mov     dword ptr [{CELL['g_rw_rect']:#x}], eax
    lea     eax, [ecx+edx]
    mov     dword ptr [esi+0x5974], eax
    mov     eax, 0x35
    {HD("eax")}
    neg     eax
    add     eax, ebx
    mov     dword ptr [esi+0x5980], eax
{fonts}
    mov     edx, {RW_LINE_H_NATIVE}
    {HD("edx")}
    mov     dword ptr [{RW + 0xE268:#x}], edx
    mov     dword ptr [{RI + 0x1C:#x}], edx
    mov     eax, dword ptr [{CELL['g_rw_rect'] + 8:#x}]
    push    dword ptr [{KIND:#x}]
    mov     dword ptr [{KIND:#x}], {RESIZE_KIND:#x}
    push    1
    push    ebx
    push    eax
    mov     ecx, {RW:#x}
    call    {RESIZE:#x}
    pop     dword ptr [{KIND:#x}]
    mov     ecx, dword ptr [{CELL['g_rw_rect']:#x}]
    mov     dword ptr [{RW + 0x13C:#x}], ecx
    add     ecx, dword ptr [{CELL['g_rw_rect'] + 8:#x}]
    mov     dword ptr [{RW + 0x144:#x}], ecx
    mov     eax, dword ptr [{CELL['g_rw_rect'] + 4:#x}]
    mov     dword ptr [{RW + 0x140:#x}], eax
    add     eax, ebx
    mov     dword ptr [{RW + 0x148:#x}], eax
    call    {T_FDIRECT_A14B:#x}
    mov     dword ptr [{CELL['g_rw_font']:#x}], eax
{pushes}
    mov     ecx, dword ptr [{RW + 0x5978:#x}]
    mov     eax, 0x2C
    {HD("eax")}
    add     eax, ecx
    mov     dword ptr [{TXTBOX_IMM:#x}], eax
    mov     eax, 0x2E
    {HD("eax")}
    add     eax, ecx
    mov     dword ptr [{SPACER_IMM:#x}], eax
    cmp     dword ptr [{RI + 0x1E230:#x}], 0
    je      tabsdone
{tabs}
    mov     eax, 0x24
    {HD("eax")}
    mov     ecx, dword ptr [{RI + 0x44:#x}]
    add     ecx, dword ptr [{RI + 0x4C:#x}]
    sub     ecx, eax
    sar     ecx, 1
    mov     dword ptr [{RI + 0xA2CC:#x}], ecx
{facs}
    mov     eax, 0x28
    {HD("eax")}
    mov     ecx, dword ptr [{RI + 0x5C:#x}]
    sub     ecx, eax
    mov     dword ptr [{RI + 0x7C:#x}], ecx
tabsdone:
    cmp     dword ptr [{G_DL_SNAPBUF:#x}], 0
    jne     rcol
    push    4
    push    0x3000
    push    0x400000
    push    0
    call    dword ptr [{IAT_VIRTUALALLOC:#x}]
    test    eax, eax
    je      bail
    mov     dword ptr [{G_DL_SNAPBUF:#x}], eax
rcol:
    cmp     dword ptr [{CELL['g_rw_railcol']:#x}], 0
    jne     bail
    push    4
    push    0x3000
    push    0x40000
    push    0
    call    dword ptr [{IAT_VIRTUALALLOC:#x}]
    test    eax, eax
    je      bail
    mov     dword ptr [{CELL['g_rw_railcol']:#x}], eax
bail:
    pop     edi
    pop     esi
    pop     ebx
done:
    jmp     dword ptr [{CELL['g_rw_ret']:#x}]
"""


# --- F2 header caves (detours; displaced bytes replayed with s() operands) ---
def asm_rw_hdr1() -> str:   # @0x498C99 9B: lea edi,[eax+0x46] / add eax,3 / add ebx,0x43
    return f"""
    push    ecx
    mov     ecx, 0x46
    {HD("ecx")}
    lea     edi, [eax+ecx]
    mov     ecx, 3
    {HD("ecx")}
    add     eax, ecx
    mov     ecx, 0x43
    {HD("ecx")}
    add     ebx, ecx
    pop     ecx
    jmp     0x498CA2
"""


def asm_rw_hdr2() -> str:   # @0x498CCF 5B: and eax,0x62 / push 0  (eax is a 0/-1 mask)
    return f"""
    push    ecx
    mov     ecx, 0x62
    {HD("ecx")}
    and     eax, ecx
    pop     ecx
    push    0
    jmp     0x498CD4
"""


def asm_rw_hdr3() -> str:   # @0x498E43 6B: push 0x40 / push eax / mov eax,[ebp-0x34]
    return f"""
    push    eax
    push    eax
    mov     eax, 0x40
    {HD("eax")}
    mov     dword ptr [esp+4], eax
    mov     eax, dword ptr [ebp-0x34]
    jmp     0x498E49
"""


def asm_rw_btnl() -> str:   # @0x4A43BA 10B: lea edx,[ecx+0x4B] / sub edi,ecx / mov [0x87E07C],eax
    return f"""
    mov     edx, 0x4B
    {HD("edx")}
    add     edx, ecx
    sub     edi, ecx
    mov     dword ptr [0x87E07C], eax
    jmp     0x4A43C4
"""


def asm_rw_btnr() -> str:   # @0x4A43CF 7B: lea edx,[edi+edx-0x96]  (row R = L + W - 0x96, 0x96 == 2*0x4B in vanilla)
    # bake v4: R = clipL + clipR - L (opposite-edge margin law): symmetric around the clip centre by
    # construction at every g (s(0x96) is 375 at g=40 but 2*s(0x4B) is 374). g<=16 identity: 26+670-101 = 595.
    return f"""
    mov     edx, dword ptr [0x87BDEC]
    add     edx, dword ptr [0x87BDF4]
    sub     edx, dword ptr [0x87E070]
    jmp     0x4A43D6
"""


T_RW_BTNW = PCAVE2 + 0x34000   # t_rw_btnw (W2A region; assemble_halfopen_frames.py, law rw_btn_pair): eax = w, edx = CLOSE x


def asm_rw_gap1() -> str:   # @0x4A4418 9B: sub eax,edx / mov [esi+0x1E1C8],edx / dec eax  -> DATALINKS (L, w)
    # v2 (2026-10-25 W2A, F30): w from t_rw_btnw (rw_btn_pair); edx (row L) kept for the caller's `add edx, eax`.
    return f"""
    mov     dword ptr [esi+0x1E1C8], edx
    push    edx
    call    {T_RW_BTNW:#x}
    pop     edx
    jmp     0x4A4421
"""


def asm_rw_gap2() -> str:   # @0x4A44D4 10B: sub eax,edx / dec eax / inc edi / mov [esi+0x1E1CC],ecx -> CLOSE (x, w)
    # v2 (2026-10-25 W2A, F30): (w, x) from t_rw_btnw; edi = x (the caller stores it at +0x1E1C8 and adds w for R).
    return f"""
    call    {T_RW_BTNW:#x}
    mov     edi, edx
    mov     dword ptr [esi+0x1E1CC], ecx
    jmp     0x4A44DE
"""


def asm_rw_title() -> str:  # @0x4A75FF 5B: and eax,0x4C / add ecx,eax (eax is a 0/-1 mask)
    return f"""
    push    edx
    mov     edx, 0x4C
    {HD("edx")}
    and     eax, edx
    pop     edx
    add     ecx, eax
    jmp     0x4A7604
"""


def asm_rw_crest() -> str:  # @0x4A5B43 6B: add ecx,0x46 / add eax,0x46
    return f"""
    push    edx
    mov     edx, 0x46
    {HD("edx")}
    add     ecx, edx
    add     eax, edx
    pop     edx
    jmp     0x4A5B49
"""


def asm_rw_rowframe() -> str:
    # CALL helper for the row-frame draw @0x496CD0 (bake v3): g<=16 -> native Buffer_box_sprite (byte-
    # identical vanilla); else the t_dl_bmxt exact-fill pattern: original half-open rect ->
    # g_faction_scratch_rect + g_fc_exact=1 (thunk_frame_enlarge stretches to the EXACT W x H, so the
    # right/bottom strokes land flush at every g instead of the floor-phase +-1), R-1/B-1 in place for
    # the inclusive renderer, thunk_box_thick_hollow_flat, rect restored, flag cleared, RET 8.
    # ebx preserved (live in the caller).
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jg      scaled
    jmp     {BOX_SPRITE:#x}
scaled:
    push    ebx
    mov     ebx, dword ptr [esp+8]
    {EXACT_STASH("ebx")}
    dec     dword ptr [ebx+8]
    dec     dword ptr [ebx+0xC]
    push    dword ptr [esp+0xC]
    push    ebx
    call    {HOLLOWFLAT:#x}
    mov     dword ptr [{G_FC_EXACT:#x}], 0
    inc     dword ptr [ebx+8]
    inc     dword ptr [ebx+0xC]
    pop     ebx
    ret     8
"""


def EXACT_STASH(reg: str) -> str:
    """rect at [reg] -> g_faction_scratch_rect (4 dwords via eax), g_fc_exact = 1. Clobbers eax."""
    out = []
    for o in (0, 4, 8, 12):
        out.append(f"mov eax, dword ptr [{reg}+{o}]\n    mov dword ptr [{G_FSR + o:#x}], eax")
    out.append(f"mov dword ptr [{G_FC_EXACT:#x}], 1")
    return "\n    ".join(out)


def asm_rw_backdrop() -> str:
    # CALL helper for the d690 window backdrop+border @0x496C91: g<=16 -> native; else exact-fill
    # around thunk_box_thick_devfill (STEP1 = hollow_flat consumes the flag; the frame then covers the
    # half-open rect exactly: window border 1625 wide at 4K, not 1626). Same contract as t_rw_rowframe.
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jg      scaled
    jmp     {BOX_SPRITE:#x}
scaled:
    push    ebx
    mov     ebx, dword ptr [esp+8]
    {EXACT_STASH("ebx")}
    dec     dword ptr [ebx+8]
    dec     dword ptr [ebx+0xC]
    push    dword ptr [esp+0xC]
    push    ebx
    call    {DEVFILL:#x}
    mov     dword ptr [{G_FC_EXACT:#x}], 0
    inc     dword ptr [ebx+8]
    inc     dword ptr [ebx+0xC]
    pop     ebx
    ret     8
"""


# ==== console tab pairs v2 (2026-10-17): law scaling_laws.rw_tab_pair / rw_console_inset_w ==========================
# The F2 TECHNOLOGY|BASES and F4 GOVERNOR|BEST BASES pairs sit in the d5a0 tab box {L+6, T+6, R-6, T+6+0x1A} of the
# console panel region (ReportIf +0x20).  v1 scaled the parts independently (buttons s(9)/s(0x12)/s(0x14), the box
# s(6)/s(0xC)/s(0x1A), the box drawn INCLUSIVE through thunk_hud_boxframe): channels L5 R7 T5 B7 at 4K, L3 R6 T3 B5 at
# 1920x1080 against vanilla's 2/2/2/2.  v2: the box is drawn half-open (0x4A7094 -> t_rwk_boxforce) with its far edge
# mirroring the near one (w = W - 2*s(6), not W - s(0xC)), and the buttons are pinned to it: inset P = s6 + K + s2,
# bottom = boxB - K - s2, left = (W - s2) >> 1, seam s2, right = the remainder.  One helper computes both buttons from
# the region; the split caves call it and resume past vanilla's four rect stores.
def asm_rw_immsum() -> str:
    """The rw walker (2026-10-17 console chain): called by t_rw_init_leave in place of t_dl_immfix (esi = g_rw_immtab,
    g_dl_immg = g, g > 16 only).  Runs t_dl_immfix over the HD rows, then stores every CHAIN_ROWS row from its own table
    (SUM_TAB_OFF into g_rw_immtab): value = sum(coef * s(v)) over the row's 4 (int8 coef, uint8 v) terms, s(v) =
    half_down(v * g, 16) with the walker's g; site bit 31 = dword store, else byte; bit 30 = continuation (the row's
    terms are added, nothing is stored, the next row carries on the sum -- laws with > 4 terms).  Preserves
    esi/ebx/edi/ebp (t_dl_immfix's own contract); clobbers eax/ecx/edx.
    v2 (fix 4g): stores NOTHING when t_dl_immfix's own VirtualProtect bootstrap failed (g_dl_vpdone still 0 after the
    call; it then wrote no HD row either): row 0x49BFCA lies in that window only (a store there faulted at
    `mov byte ptr [eax], cl`), and chain rows stored over native HD neighbours would half-scale the console --
    all-or-nothing, like the DL walker's own fallback.  The rw window (VP_PAGE..) is t_rw_init_leave's, opened
    before the call (it bails without calling on failure)."""
    return f"""
    call    {T_DL_IMMFIX:#x}
    cmp     dword ptr [{AD.VPDONE:#x}], 0
    ; DL VirtualProtect failed: no HD / chain row is stored, the thunk-driven console levers still scale (a mixed console, never a fault)
    je      skip
    push    esi
    push    ebx
    push    edi
    mov     esi, {TAB_RW + SUM_TAB_OFF:#x}
    xor     ecx, ecx
rows:
    mov     eax, dword ptr [esi]
    test    eax, eax
    je      done
    xor     edi, edi
term:
    movzx   edx, byte ptr [esi+edi*2+5]
    imul    edx, dword ptr [{G_DL_IMMG:#x}]
    lea     edx, [edx*2+15]
    sar     edx, 5
    movsx   ebx, byte ptr [esi+edi*2+4]
    imul    edx, ebx
    add     ecx, edx
    inc     edi
    cmp     edi, 4
    jne     term
    test    eax, {SUM_CONT:#x}
    jne     adv
    test    eax, eax
    js      w4
    mov     byte ptr [eax], cl
    jmp     stored
w4:
    and     eax, 0x7FFFFFFF
    mov     dword ptr [eax], ecx
stored:
    xor     ecx, ecx
adv:
    add     esi, 12
    jmp     rows
done:
    pop     edi
    pop     ebx
    pop     esi
skip:
    ret
"""


INSETV_C = -1     # t_rw_insetv code for the content box inset C (law rw_console_box_inset); 0 = P (rw_tab_inset)


def asm_rw_insetv() -> str:
    """CALL helper, stdcall(code) RET 4 -> eax: code > 0 -> s(code); code 0 -> P = C + K + s(2) (rw_tab_inset);
    code -1 -> C = s(3) + K + s(2) (rw_console_box_inset).  v2 (2026-10-17 console chain): v1's P was s(6) + K + s(2)
    and the box inset s(6) (code 6).  g is clamped to >= 16, so at g <= 16 it returns vanilla's own constants
    (s(v) = v, C = 6, P = 9).  Preserves every register but eax (and flags)."""
    return f"""
    push    ecx
    mov     ecx, dword ptr [{G:#x}]
    cmp     ecx, 0x10
    jge     gok
    push    0x10
    pop     ecx
gok:
    add     ecx, ecx
    mov     eax, dword ptr [esp+8]
    test    eax, eax
    jle     pins
    imul    eax, ecx
    add     eax, 15
    sar     eax, 5
    pop     ecx
    ret     4
pins:
    push    edx
    lea     eax, [ecx+15]
    sar     eax, 5
    lea     edx, [ecx*{SL.RW_TAB_CHANNEL}+15]
    sar     edx, 5
    add     eax, edx
    cmp     dword ptr [esp+0xC], 0
    jne     one
    add     eax, eax
one:
    lea     edx, [ecx+ecx*{SL.RW_CONSOLE_PANEL_INSET - 1}+15]
    sar     edx, 5
    add     eax, edx
    pop     edx
    pop     ecx
    ret     4
"""


def asm_rw_tabpair() -> str:
    """CALL helper (g > 16 only): esi = ReportIf, eax = 0 (left button) / 1 (right button).  Writes that button's
    half-open rect into the scratch RECT +0x1E1C8..+0x1E1D4 from the panel region +0x20..+0x2C (law rw_tab_pair).
    Preserves ebx/esi/edi/ebp; clobbers eax/ecx/edx."""
    return f"""
    push    ebx
    push    edi
    push    ebp
    mov     ebp, eax
    push    0
    call    t_rw_insetv
    mov     ebx, eax
    push    {SL.RW_TAB_CHANNEL}
    call    t_rw_insetv
    mov     edi, eax
    push    {INSETV_C}
    call    t_rw_insetv
    mov     edx, eax
    push    {SL.RW_TAB_BOX_H}
    call    t_rw_insetv
    add     eax, edx
    add     eax, edx
    sub     eax, ebx
    add     eax, dword ptr [esi+0x24]
    mov     dword ptr [esi+0x1E1D4], eax
    mov     eax, dword ptr [esi+0x24]
    add     eax, ebx
    mov     dword ptr [esi+0x1E1CC], eax
    mov     ecx, dword ptr [esi+0x20]
    add     ecx, ebx
    mov     edx, dword ptr [esi+0x28]
    sub     edx, ebx
    mov     eax, edx
    sub     eax, ecx
    sub     eax, edi
    sar     eax, 1
    add     ecx, eax
    test    ebp, ebp
    jne     right
    mov     dword ptr [esi+0x1E1D0], ecx
    sub     ecx, eax
    mov     dword ptr [esi+0x1E1C8], ecx
    jmp     out
right:
    add     ecx, edi
    mov     dword ptr [esi+0x1E1C8], ecx
    mov     dword ptr [esi+0x1E1D0], edx
out:
    pop     ebp
    pop     edi
    pop     ebx
    ret
"""


def asm_rw_tabsplit1() -> str:   # @0x4A45B6 6B: sar eax,1 / add esp,8 / dec eax   (TECH toggle)
    return RK.asm_split_left(0x4A45BC, 0x4A45D9)


def asm_rw_tabsplit2() -> str:   # @0x4A4675 7B: add ecx,0x14 / lea edx,[eax+edx+1]   (BASES toggle)
    # g > 16: the `add esp, 8` at 0x4A467C is skipped with the stores -> done here; [+0x1E1CC] (stored at 0x4A466F
    # from the cursor) is overwritten by the law.
    return f"""
    cmp     dword ptr [{G:#x}], 0x10
    jle     native
    add     esp, 8
    mov     eax, 1
    call    t_rw_tabpair
    jmp     0x4A4693
native:
    add     ecx, 0x14
    lea     edx, [eax+edx+1]
    jmp     0x4A467C
"""


# ---- console box far edges: w/h = span - 2*s(6) (law rw_console_inset_w) -------------------------------------------
def asm_rw_labs_w() -> str:      # @0x4A7032 7B: sub edx,eax / push 0 / sub edx,0xC   (F2 left cursor w; eax dead after)
    return f"""
    sub     edx, eax
    push    0
    push    {INSETV_C}
    call    t_rw_insetv
    add     eax, eax
    sub     edx, eax
    jmp     0x4A7039
"""


def asm_rw_labs_h() -> str:      # @0x4A704A 9B: lea ecx,[esi+0xBA0C] / sub eax,0xC   (F2 left cursor h; edx = vtbl live)
    return f"""
    mov     ecx, eax
    push    {INSETV_C}
    call    t_rw_insetv
    add     eax, eax
    sub     ecx, eax
    mov     eax, ecx
    lea     ecx, [esi+0xBA0C]
    jmp     0x4A7053
"""


def asm_rw_labs_rw() -> str:     # @0x4A7A78 9B: mov edx,[esi+0x1E198] / sub eax,0xC   (F2 right cursor w)
    return f"""
    mov     edx, eax
    push    {INSETV_C}
    call    t_rw_insetv
    add     eax, eax
    sub     edx, eax
    mov     eax, edx
    mov     edx, dword ptr [esi+0x1E198]
    jmp     0x4A7A81
"""


def asm_rw_labs_rh() -> str:     # @0x4A7A8F 9B: mov eax,[esi+0x1E18C] / sub ecx,0xC   (F2 right cursor h)
    return f"""
    push    {INSETV_C}
    call    t_rw_insetv
    add     eax, eax
    sub     ecx, eax
    mov     eax, dword ptr [esi+0x1E18C]
    jmp     0x4A7A98
"""


def asm_rw_restripe() -> str:
    # CALL helper (buf, rect*, params*) RET 0xC: mate-required P-law restripe of the pair read from
    # the set's fill Buffer rows 0/1 (a = row 0 = top member). A pixel equal to a or b is rewritten
    # to (y%P<hN ? a : b) ONLY if its mate occurs within +-4 rows of the same column (solid
    # member-colour lines pass through). Rect half-open, clamped to the buffer. Preserves ebx/esi/edi.
    return f"""
    push    ebp
    mov     ebp, esp
    sub     esp, 0x40
    push    ebx
    push    esi
    push    edi
    mov     eax, dword ptr [ebp+0x10]
    mov     eax, dword ptr [eax+0x20]
    test    eax, eax
    je      out
    mov     ecx, dword ptr [eax+0x54]
    test    ecx, ecx
    je      out
    mov     edx, dword ptr [eax+0x4A8]
    test    edx, edx
    jle     out
    movzx   ebx, byte ptr [ecx]
    movzx   edi, byte ptr [ecx+edx]
    cmp     ebx, edi
    je      out
    cmp     ebx, 9
    je      out
    cmp     edi, 9
    je      out
    mov     dword ptr [ebp-4], ebx
    mov     dword ptr [ebp-8], edi
    mov     esi, dword ptr [ebp+8]
    mov     eax, dword ptr [esi+0x54]
    test    eax, eax
    je      out
    mov     dword ptr [ebp-0xC], eax
    mov     eax, dword ptr [esi+0x4A8]
    test    eax, eax
    jle     out
    mov     dword ptr [ebp-0x10], eax
    mov     eax, dword ptr [esi+0x80]
    mov     dword ptr [ebp-0x14], eax
    mov     eax, dword ptr [esi+0x84]
    test    eax, eax
    jns     hpos
    neg     eax
hpos:
    mov     dword ptr [ebp-0x18], eax
    mov     esi, dword ptr [ebp+0xC]
    mov     eax, dword ptr [esi]
    test    eax, eax
    jns     x0ok
    xor     eax, eax
x0ok:
    mov     dword ptr [ebp-0x1C], eax
    mov     eax, dword ptr [esi+8]
    cmp     eax, dword ptr [ebp-0x14]
    jle     x1ok
    mov     eax, dword ptr [ebp-0x14]
x1ok:
    mov     dword ptr [ebp-0x20], eax
    mov     eax, dword ptr [esi+4]
    test    eax, eax
    jns     y0ok
    xor     eax, eax
y0ok:
    mov     dword ptr [ebp-0x24], eax
    mov     eax, dword ptr [esi+12]
    cmp     eax, dword ptr [ebp-0x18]
    jle     y1ok
    mov     eax, dword ptr [ebp-0x18]
y1ok:
    mov     dword ptr [ebp-0x28], eax
    mov     eax, dword ptr [{G:#x}]
    mov eax, dword ptr [0x66879c]
    nop
    mov     dword ptr [ebp-0x2C], eax
    inc     eax
    sar     eax, 1
    mov     dword ptr [ebp-0x30], eax
    mov     esi, dword ptr [ebp-0x24]
yloop:
    cmp     esi, dword ptr [ebp-0x28]
    jge     out
    mov     eax, esi
    cdq
    idiv    dword ptr [ebp-0x2C]
    cmp     edx, dword ptr [ebp-0x30]
    mov     eax, dword ptr [ebp-8]
    jge     botrow
    mov     eax, dword ptr [ebp-4]
botrow:
    mov     dword ptr [ebp-0x34], eax
    mov     eax, esi
    imul    eax, dword ptr [ebp-0x10]
    add     eax, dword ptr [ebp-0xC]
    mov     dword ptr [ebp-0x38], eax
    mov     edi, dword ptr [ebp-0x1C]
xloop:
    cmp     edi, dword ptr [ebp-0x20]
    jge     xdone
    mov     ecx, dword ptr [ebp-0x38]
    movzx   eax, byte ptr [ecx+edi]
    cmp     eax, dword ptr [ebp-4]
    jne     notA
    mov     ebx, dword ptr [ebp-8]
    jmp     mate
notA:
    cmp     eax, dword ptr [ebp-8]
    jne     nextx
    mov     ebx, dword ptr [ebp-4]
mate:
    mov     ecx, esi
    sub     ecx, 4
    jns     m0
    xor     ecx, ecx
m0:
    mov     edx, esi
    add     edx, 5
    cmp     edx, dword ptr [ebp-0x18]
    jle     m1
    mov     edx, dword ptr [ebp-0x18]
m1:
mloop:
    cmp     ecx, edx
    jge     nextx
    cmp     ecx, esi
    je      mnext
    mov     eax, ecx
    imul    eax, dword ptr [ebp-0x10]
    add     eax, dword ptr [ebp-0xC]
    movzx   eax, byte ptr [eax+edi]
    cmp     eax, ebx
    je      found
mnext:
    inc     ecx
    jmp     mloop
found:
    mov     eax, dword ptr [ebp-0x34]
    mov     ecx, dword ptr [ebp-0x38]
    mov     byte ptr [ecx+edi], al
nextx:
    inc     edi
    jmp     xloop
xdone:
    inc     esi
    jmp     yloop
out:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0xC
"""


def asm_rw_bar() -> str:
    # The 8 research-bar Buffer_box_sprite sites: record (rect copy, params) into g_rw_barlist, then
    # replay the displaced prologue and continue at 0x5E2DD8 = the NATIVE 9-slice draw (bypasses
    # thunk_hud_boxframe's render-small/stretch). CALL helper semantics preserved (ret/args intact).
    L = CELL['g_rw_barlist']
    return f"""
    push    eax
    push    ecx
    push    edx
    mov     eax, dword ptr [{CELL['g_rw_barn']:#x}]
    cmp     eax, 8
    jae     skip
    lea     ecx, [eax+eax*4]
    lea     ecx, [{L:#x}+ecx*4]
    mov     edx, dword ptr [esp+0x10]
    mov     eax, dword ptr [edx]
    mov     dword ptr [ecx], eax
    mov     eax, dword ptr [edx+4]
    mov     dword ptr [ecx+4], eax
    mov     eax, dword ptr [edx+8]
    mov     dword ptr [ecx+8], eax
    mov     eax, dword ptr [edx+12]
    mov     dword ptr [ecx+12], eax
    mov     eax, dword ptr [esp+0x14]
    mov     dword ptr [ecx+16], eax
    inc     dword ptr [{CELL['g_rw_barn']:#x}]
skip:
    pop     edx
    pop     ecx
    pop     eax
    push    ecx
    push    ebx
    push    ebp
    push    esi
    push    edi
    push    {BOX_SPRITE_RESUME:#x}
    ret
"""


def asm_rw_labs_enter() -> str:
    # detour @0x4A7000 (9B: push ebp / mov ebp,esp / sub esp,0x280): ret-swap -> t_rw_labs_leave
    return f"""
    pop     eax
    mov     dword ptr [{CELL['g_rw_labs_ret']:#x}], eax
    push    t_rw_labs_leave
    mov     dword ptr [{CELL['g_rw_barn']:#x}], 0
    push    ebp
    mov     ebp, esp
    sub     esp, 0x280
    jmp     {LABS_RESUME:#x}
"""


def asm_rw_labs_leave() -> str:
    L = CELL['g_rw_barlist']
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     out
    push    eax
    push    ecx
    push    edx
    push    ebx
    push    esi
    xor     ebx, ebx
bloop:
    cmp     ebx, dword ptr [{CELL['g_rw_barn']:#x}]
    jge     bdone
    lea     esi, [ebx+ebx*4]
    lea     esi, [{L:#x}+esi*4]
    push    dword ptr [esi+16]
    push    esi
    push    {MW_CANVAS:#x}
    call    t_rw_restripe
    inc     ebx
    jmp     bloop
bdone:
    pop     esi
    pop     ebx
    pop     edx
    pop     ecx
    pop     eax
out:
    jmp     dword ptr [{CELL['g_rw_labs_ret']:#x}]
"""


def asm_rw_techpage() -> str:
    # CALL helper for the 3 report-side `call ReportWin_tech_page` sites (fastcall this=ecx, no args):
    # apply the DL tech imm table with g + the scaled label font + g_dl_exec/netwin, call the page,
    # revert (walker g=16, fixed font, gates 0), then restripe the header text box + spacer with the
    # mate-required P-law (pairs per set). Rects from the CLIP fields (+0x5974..) the init lever owns —
    # the page overwrites +0xA14/+0xA18 at its exit (0x49B1C9) and +0xA1C/+0xA20 in its layout, so the
    # painter-scratch fields are NOT usable after the call (bake v1 defect: header banding came back).
    # Same composition as the page: x0 = clipL + s(3) + s(0x43), x1 = clipR - s(3). Native tail at g<=16.
    # Scratch RECT = g_rw_tech_rect, NEVER g_rw_rect: t_rw_init_leave's GraphicWin_resize repaints
    # synchronously, and with g_reportwin_kind left at 2 (F2 last viewed) at a game load this thunk ran
    # INSIDE that resize and overwrote g_rw_rect before init_leave read the window origin back ->
    # every report drawn at the header rect's origin, (-868,-124) at 4K, until the next load.
    push_scaled = "".join(f"    mov     dword ptr [{va + 1:#x}], eax\n" for va in FONT_PUSH_TECH)
    R = CELL['g_rw_tech_rect']
    spacer_calls = "".join(f"""
    push    {s:#x}
    push    {R:#x}
    push    {RW_CANVAS:#x}
    call    t_rw_restripe
""" for s in SPACER_SETS)
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jg      go
    jmp     {TECH_PAGE:#x}
go:
    push    ebx
    push    esi
    push    edi
    push    ecx
    mov     eax, dword ptr [{G:#x}]
    mov     dword ptr [{G_DL_IMMG:#x}], eax
    mov     esi, {TAB_TECH:#x}
    call    {T_DL_IMMFIX:#x}
    mov     eax, dword ptr [{CELL['g_rw_font']:#x}]
    test    eax, eax
    je      nofont
{push_scaled}
nofont:
    mov     dword ptr [{G_DL_EXEC:#x}], 1
    mov     dword ptr [{G_NETWIN:#x}], 1
    pop     ecx
    call    {TECH_PAGE:#x}
    mov     dword ptr [{G_DL_IMMG:#x}], 16
    mov     esi, {TAB_TECH:#x}
    call    {T_DL_IMMFIX:#x}
    mov     eax, {FONT_FIXED:#x}
{push_scaled}
    mov     dword ptr [{G_DL_EXEC:#x}], 0
    mov     dword ptr [{G_NETWIN:#x}], 0
    mov     esi, {RW:#x}
    mov     eax, 0x46
    {HD("eax")}
    mov     edi, eax
    mov     eax, 3
    {HD("eax")}
    mov     ebx, eax
    mov     eax, 0x43
    {HD("eax")}
    add     eax, ebx
    add     eax, dword ptr [esi+0x5974]
    mov     dword ptr [{R:#x}], eax
    mov     eax, dword ptr [esi+0x597C]
    sub     eax, ebx
    mov     dword ptr [{R + 8:#x}], eax
    mov     eax, dword ptr [esi+0x5978]
    add     eax, ebx
    mov     dword ptr [{R + 4:#x}], eax
    mov     eax, dword ptr [{TXTBOX_IMM:#x}]
    mov     dword ptr [{R + 12:#x}], eax
    push    {TXTBOX_SET:#x}
    push    {R:#x}
    push    {RW_CANVAS:#x}
    call    t_rw_restripe
    mov     eax, dword ptr [{SPACER_IMM:#x}]
    mov     dword ptr [{R + 4:#x}], eax
    mov     eax, dword ptr [esi+0x5978]
    add     eax, edi
    sub     eax, ebx
    mov     dword ptr [{R + 12:#x}], eax
{spacer_calls}
    pop     edi
    pop     esi
    pop     ebx
    ret
"""


def asm_rw_techhover() -> str:
    # ReportWin vtbl+0xA0 slot (0x66D7F4): ReportWin_tech_hover(id, state) thiscall RET 8. In F2 the engine
    # calls it on mouse move OUTSIDE the paint bracket, so the DL tech imm table is at 16 and g_dl_exec=0:
    # the card/button frame rects come out with NATIVE +-3 insets and t_dl_bmt/bmxt/hover/arrowzoom take
    # their native paths -> a stray 1-px d5a0 ring 3 px inside the K-stroke card frame (user 4K shot
    # 221752). Same bracket as t_rw_techpage (imms g + exec/netwin 1) around the call, then the PRIOR
    # state restored (DL keeps its own exec=1/immg=g bracket alive across ReportWin slot calls). No
    # fonts (the hover draws frames + connector only). Native tail at g<=16 (slot -> vanilla body).
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jg      go
    jmp     {TECH_HOVER:#x}
go:
    push    ebx
    push    esi
    push    edi
    push    ecx
    mov     eax, dword ptr [{G_DL_EXEC:#x}]
    mov     dword ptr [{CELL['g_rw_hov_exec']:#x}], eax
    mov     eax, dword ptr [{G_NETWIN:#x}]
    mov     dword ptr [{CELL['g_rw_hov_netwin']:#x}], eax
    mov     eax, dword ptr [{G_DL_IMMG:#x}]
    test    eax, eax
    jne     keep
    mov     eax, 16
keep:
    mov     dword ptr [{CELL['g_rw_hov_immg']:#x}], eax
    mov     eax, dword ptr [{G:#x}]
    mov     dword ptr [{G_DL_IMMG:#x}], eax
    mov     esi, {TAB_TECH:#x}
    call    {T_DL_IMMFIX:#x}
    mov     dword ptr [{G_DL_EXEC:#x}], 1
    mov     dword ptr [{G_NETWIN:#x}], 1
    pop     ecx
    push    dword ptr [esp+0x14]
    push    dword ptr [esp+0x14]
    call    {TECH_HOVER:#x}
    mov     eax, dword ptr [{CELL['g_rw_hov_immg']:#x}]
    mov     dword ptr [{G_DL_IMMG:#x}], eax
    mov     esi, {TAB_TECH:#x}
    call    {T_DL_IMMFIX:#x}
    mov     eax, dword ptr [{CELL['g_rw_hov_exec']:#x}]
    mov     dword ptr [{G_DL_EXEC:#x}], eax
    mov     eax, dword ptr [{CELL['g_rw_hov_netwin']:#x}]
    mov     dword ptr [{G_NETWIN:#x}], eax
    pop     edi
    pop     esi
    pop     ebx
    ret     8
"""


def asm_rw_iconblit() -> str:
    # chain head at 0x607F43 (Sprite_draw_2 stateSprite blit): for the 7 kind-tab + 7 faction-tab
    # FlatButtons pass num=g/den=16 with the centre recomputed and draw through t_rwk_parity_nn (v2 2026-09-10:
    # the parity-preserving NN -- the engine NN banded the period-2 scanline art at g=22/25); everything else
    # -> thunk_faction_portrait.
    FT_LO, FT_HI = RI + 0x80, RI + 0x80 + 7 * 0xB4C
    KT_LO, KT_HI = RI + 0x5384, RI + 0x5384 + 7 * 0xB4C
    return f"""
    cmp     dword ptr [{G:#x}], 16
    jle     chain
    mov     eax, dword ptr [esp+4]
    sub     eax, 0x444
    cmp     eax, {FT_LO:#x}
    jb      kt
    cmp     eax, {FT_HI:#x}
    jb      hit
kt:
    cmp     eax, {KT_LO:#x}
    jb      chain
    cmp     eax, {KT_HI:#x}
    jae     chain
hit:
    cmp     dword ptr [esp+0x14], 1
    jne     chain
    cmp     dword ptr [esp+0x18], 1
    jne     chain
    push    ebx
    push    edx
    mov     edx, dword ptr [ecx+0x18]
    {FL("edx")}
    mov     ebx, dword ptr [eax+0x4C4]
    sub     ebx, edx
    sar     ebx, 1
    mov     dword ptr [esp+0x14], ebx
    mov     edx, dword ptr [ecx+0x1C]
    {FL("edx")}
    mov     ebx, dword ptr [eax+0x4C8]
    neg     ebx
    sub     ebx, edx
    sar     ebx, 1
    mov     dword ptr [esp+0x18], ebx
    mov     ebx, dword ptr [{G:#x}]
    mov     dword ptr [esp+0x1C], ebx
    mov     dword ptr [esp+0x20], 16
    pop     edx
    pop     ebx
    jmp     t_rwk_parity_nn
chain:
    jmp     {FACTION_PORTRAIT:#x}
"""


def asm_rw_scrollsmall() -> str:   # CALL helper @0x4A7114 (call scroll_small)
    return f"""
    call    {SCROLL_SMALL:#x}
    cmp     dword ptr [{G:#x}], 16
    jle     nx
    mov     eax, 12
    {HD("eax")}
    mov     dword ptr [{G_SCROLLBAR_W:#x}], eax
nx:
    mov     dword ptr [{CELL['g_rw_inlist']:#x}], 1
    mov     eax, dword ptr [{RI + 0xC:#x}]
    cmp     eax, dword ptr [{RI + 0x50:#x}]
    setge   al
    movzx   eax, al
    mov     dword ptr [{CELL['g_rw_slot']:#x}], eax
    mov     dword ptr [{CELL['g_rw_sbs']:#x}+eax*4], 0
    mov     dword ptr [{CELL['g_rw_sbparents']:#x}+eax*4], 0
    ret
"""


def asm_rw_scrollnormal() -> str:  # @0x4A75C9 (call scroll_normal)
    return f"""
    mov     dword ptr [{CELL['g_rw_inlist']:#x}], 0
    jmp     {SCROLL_NORMAL:#x}
"""


def asm_rw_sbinit() -> str:        # detour @ScrollBar_init_inner 0x6054D0 (5B: mov eax,[esp+0x14] / push ebx)
    return f"""
    cmp     dword ptr [{CELL['g_rw_inlist']:#x}], 0
    je      rep
    mov     dword ptr [{CELL['g_rw_sb']:#x}], ecx
    mov     eax, dword ptr [esp+0x14]
    mov     dword ptr [{CELL['g_rw_sbparent']:#x}], eax
    push    edx
    mov     edx, dword ptr [{CELL['g_rw_slot']:#x}]
    mov     dword ptr [{CELL['g_rw_sbs']:#x}+edx*4], ecx
    mov     dword ptr [{CELL['g_rw_sbparents']:#x}+edx*4], eax
    pop     edx
    cmp     dword ptr [{G:#x}], 16
    jle     rep
    mov     dword ptr [{G_RAIL_SB:#x}], ecx
rep:
    mov     eax, dword ptr [esp+0x14]
    push    ebx
    jmp     {SB_INIT_RESUME:#x}
"""


def asm_rw_lbclose() -> str:       # @0x4A8479 (call ListBox_close in ReportIf_hide_labs_widgets)
    return f"""
    mov     eax, dword ptr [{CELL['g_rw_sb']:#x}]
    cmp     dword ptr [{G_RAIL_SB:#x}], eax
    jne     nc
    mov     dword ptr [{G_RAIL_SB:#x}], 0
nc:
    mov     dword ptr [{CELL['g_rw_sb']:#x}], 0
    mov     dword ptr [{CELL['g_rw_sbparent']:#x}], 0
    jmp     {LISTBOX_CLOSE:#x}
"""


def asm_rw_wheel_down() -> str:
    """v2 (rw_scale_kinds): kind 2 = the stashed labs list bar (v1 path, proven); kinds 0/3/4 = the console list
    under the cursor (GetCursorPos/ScreenToClient via the IAT, MainWin-relative, panel L/R rect -> per-panel bar
    slot written by t_rw_scrollsmall/t_rw_sbinit). Eaten scrolls set g_rw_wheel_ate for the KEYUP twin.
    v3 (2026-10-11): the cursor goes through t_wheel_stc (client -> BACKBUFFER: PRACX stretches the backbuffer
    into the client in Windowed / Borderless / Fullscreen-without-mode-switch); kind 3 first asks
    t_rw_wheel_energy (the canvas energy ListBox under the cursor scrolls its heap V bar); every other kind-3
    notch that does not scroll a list ends in t_rw_wheel_hfail, which eats it while the energy list is open.
    Either way PRACX's VK_UP/VK_DOWN never reaches the focused energy list (ListBox_on_key would move the
    SELECTION one base per notch). Scroll tail = t_rw_wheel_have."""
    return f"""
    cmp     dword ptr [{BASEPOP:#x}], 0
    jne     chain
    cmp     dword ptr [{MODAL_TOP:#x}], {RW:#x}
    jne     chain
    mov     eax, dword ptr [{KIND:#x}]
    cmp     eax, 3
    je      gate
    cmp     eax, 4
    je      gate
    test    eax, eax
    je      gate
    cmp     eax, 2
    jne     chain
    mov     eax, dword ptr [{CELL['g_rw_sb']:#x}]
    test    eax, eax
    jz      chain
gate:
    call    {GET_TARGET:#x}
    test    eax, eax
    jz      xo
    cmp     dword ptr [esp+0x6C], 0
    jne     xo
    mov     edx, dword ptr [esp+0x68]
    cmp     edx, 0x26
    je      go
    cmp     edx, 0x28
    je      go
xo:
    ret
go:
    push    eax
    push    ebx
    push    esi
    push    edi
    xor     ebx, ebx
    cmp     edx, 0x26
    setne   bl
    inc     ebx
    cmp     dword ptr [{KIND:#x}], 2
    jne     kx
    mov     edi, dword ptr [{CELL['g_rw_sb']:#x}]
    mov     esi, dword ptr [{CELL['g_rw_sbparent']:#x}]
    jmp     t_rw_wheel_have
kx:
    sub     esp, 8
    push    esp
    call    dword ptr [{RK.IAT_GETCURSORPOS:#x}]
    push    esp
    push    dword ptr [{RK.G_HWND:#x}]
    call    t_wheel_stc
    nop
    call    t_rw_wheel_energy
    pop     eax
    pop     edx
    sub     eax, dword ptr [{RK.MAINWIN + 0x13C:#x}]
    sub     edx, dword ptr [{RK.MAINWIN + 0x140:#x}]
    cmp     eax, dword ptr [{RI + 0x20:#x}]
    jl      tryr
    cmp     eax, dword ptr [{RI + 0x28:#x}]
    jge     tryr
    cmp     edx, dword ptr [{RI + 0x24:#x}]
    jl      tryr
    cmp     edx, dword ptr [{RI + 0x2C:#x}]
    jge     tryr
    mov     edi, dword ptr [{CELL['g_rw_sbs']:#x}]
    mov     esi, dword ptr [{CELL['g_rw_sbparents']:#x}]
    jmp     t_rw_wheel_have
tryr:
    cmp     eax, dword ptr [{RI + 0x30:#x}]
    jl      restore
    cmp     eax, dword ptr [{RI + 0x38:#x}]
    jge     restore
    cmp     edx, dword ptr [{RI + 0x34:#x}]
    jl      restore
    cmp     edx, dword ptr [{RI + 0x3C:#x}]
    jge     restore
    mov     edi, dword ptr [{CELL['g_rw_sbs'] + 4:#x}]
    mov     esi, dword ptr [{CELL['g_rw_sbparents'] + 4:#x}]
    jmp     t_rw_wheel_have
restore:
    jmp     t_rw_wheel_hfail
chain:
    jmp     {DL_WHEEL_DOWN:#x}
"""


RW_ENERGY_LISTWIN = RW + 0x5A54      # the F3 energy ListBox (RW+0x5A0C) Win part = parent of its heap V bar
RW_ENERGY_VBAR = 0x0087C308          # ReportWin_energy_list_vbar = RW_ENERGY_LISTWIN + 0x43C (scroll_vert; 0 when closed)
assert RW_ENERGY_VBAR == RW_ENERGY_LISTWIN + 0x43C
LOCAL_TO_SCREEN = 0x005ED240         # GraphicWin_local_to_screen(self, int* x, int* y) thiscall RET 8


def asm_rw_wheel_energy() -> str:
    """CALL helper from t_rw_wheel_down's cursor path (kinds 0/3/4), right after ScreenToClient.
    Entry stack: [esp] ret, [esp+4] cursor x, [esp+8] cursor y (hwnd client = engine screen space),
    then the thunk's saved edi/esi/ebx/eax and ITS return. ebx = chevron id (1 up / 2 down), preserved.
    Not kind 3 / no energy bar / bar not parented by the energy list Win / list hidden / cursor outside the
    list Win's rect -> plain ret (eax/ecx/edx/esi/edi clobbered: the caller reloads them).
    Cursor inside the list Win's screen rect: origin = local_to_screen(0,0) (the engine already adds the Win's
    +0x13C AND +0x14C origins up the parent chain), x extent [0, max(R, bar R) - L) so the list's own scrollbar
    column (a child of the list Win, right of it) counts, y extent [0, B - T): the notch is NEVER passed on as a
    key.  v4 (2026-10-14, Frida probe frida_f3wheel_*_20261015T054340Z.log at 4K): v3 subtracted +0x14C/+0x150
    a second time; the list Win's +0x14C is its 882,137 place in ReportWin, so every notch over the list missed
    by 882 px (cursor 2268,1178 vs origin 1932,383, rect 0,0,729,1099, bar 729..779) and was eaten. The helper drops
    its return + the cursor pair and JMPs t_rw_wheel_have (edi = bar, or 0 when the bar is hidden):
    engaged -> CHEVRON(bar, id) + parent present + hover invalidate; else t_rw_wheel_hfail eats it (kind 3)."""
    return f"""
    cmp     dword ptr [{KIND:#x}], 3
    jne     no
    mov     edi, dword ptr [{RW_ENERGY_VBAR:#x}]
    test    edi, edi
    jz      no
    mov     esi, dword ptr [edi+0xC4]
    cmp     esi, {RW_ENERGY_LISTWIN:#x}
    jne     no
    test    byte ptr [esi+0x9C], 1
    jz      no
    push    0
    push    0
    lea     eax, [esp+4]
    push    eax
    lea     eax, [esp+4]
    push    eax
    mov     ecx, esi
    call    {LOCAL_TO_SCREEN:#x}
    pop     eax
    pop     edx
    mov     ecx, dword ptr [esp+4]
    sub     ecx, eax
    jl      no
    mov     eax, dword ptr [esi+0x144]
    cmp     eax, dword ptr [edi+0x144]
    jge     wr
    mov     eax, dword ptr [edi+0x144]
wr:
    sub     eax, dword ptr [esi+0x13C]
    cmp     ecx, eax
    jge     no
    mov     ecx, dword ptr [esp+8]
    sub     ecx, edx
    jl      no
    mov     eax, dword ptr [esi+0x148]
    sub     eax, dword ptr [esi+0x140]
    cmp     ecx, eax
    jge     no
    add     esp, 12
    test    byte ptr [edi+0x9C], 1
    jnz     have
    xor     edi, edi
have:
    jmp     t_rw_wheel_have
no:
    ret
"""


# POLICY (USER DECISION 2026-10-11: the wheel scrolls the list, never acts like the arrows): a notch over a list that cannot scroll (it fits / its bar is hidden)
# True  -> t_rw_wheel_hfail: eaten on F3 while the energy list is open (no selection move), passed elsewhere;
# False -> the key passes as before (PRACX's VK_UP/VK_DOWN: on F3 that moves the energy selection).
EAT_WHEN_LIST_FITS = True


def asm_rw_wheel_have() -> str:
    """JMP tail shared by t_rw_wheel_down (kind-2 labs bar, console panel bars) and t_rw_wheel_energy:
    edi = bar, esi = its parent ListBox Win part, ebx = chevron id; stack = saved edi/esi/ebx/eax, then the
    thunk's return. A bar that cannot scroll (null / unparented / hidden / the list fits): EAT_WHEN_LIST_FITS."""
    fits = ("    jmp     t_rw_wheel_hfail" if EAT_WHEN_LIST_FITS else
            "\n".join(f"    {i}" for i in ("pop     edi", "pop     esi", "pop     ebx", "pop     eax", "ret")))
    return f"""
    test    edi, edi
    jz      hf
    test    esi, esi
    jz      hf
    cmp     dword ptr [edi+0xC4], 0
    je      hf
    mov     ecx, dword ptr [edi+0xA24]
    cmp     ecx, dword ptr [edi+0xA20]
    jle     hf
    push    ebx
    mov     ecx, edi
    call    {CHEVRON:#x}
    mov     edx, dword ptr [esi]
    mov     ecx, esi
    call    dword ptr [edx+0xFC]
    ; hover invalidate (bake of the proto fix, user-verified clean 2026-09-05): the ListBox hover item
    ; [Dialog+0xA8] survives a wheel scroll; element = part-0x48; Dialog = element + [[element]+8].
    mov     eax, dword ptr [esi-0x48]
    mov     eax, dword ptr [eax+8]
    mov     dword ptr [esi+eax+0xA8], -1
    mov     dword ptr [{CELL['g_rw_wheel_ate']:#x}], 1
    pop     edi
    pop     esi
    pop     ebx
    pop     eax
    xor     eax, eax
    ret
hf:
{fits}
"""


def asm_rw_wheel_hfail() -> str:
    """JMP tail of every t_rw_wheel_down notch that scrolled nothing: cursor over no list (down's restore) or over
    a list that cannot scroll (t_rw_wheel_have, EAT_WHEN_LIST_FITS). Stack: saved edi/esi/ebx/eax, then the
    thunk's return. Kind 3 with the energy list open ([ReportWin_energy_list_vbar] != 0) eats the notch (else
    the key reaches the focused energy list and moves its selection); otherwise the key passes (eax = target)."""
    return f"""
    pop     edi
    pop     esi
    pop     ebx
    pop     eax
    cmp     dword ptr [{KIND:#x}], 3
    jne     r
    cmp     dword ptr [{RW_ENERGY_VBAR:#x}], 0
    je      r
    mov     dword ptr [{CELL['g_rw_wheel_ate']:#x}], 1
    xor     eax, eax
r:
    ret
"""


WHEEL_STC = PCAVE2 + 0x1292C        # t_wheel_stc  (pinned; uimod.dll wheel.cpp kVA_WheelStc byte-checks it)
G_WHEEL_STC = PCAVE2 + 0x1293C      # g_wheel_stc  (4 B, 0 in the image; uimod.dll stores its ScreenToClient+ClientToBackbuffer)


def asm_wheel_stc() -> str:
    """Drop-in for `call [ScreenToClient]` (stdcall (hwnd, POINT*) RET 8) at EVERY asm wheel head (t_rw / t_dl /
    t_bw / t_ntw _wheel_down): their hit rects are backbuffer (engine screen) coords, but PRACX stretches the
    backbuffer into the client when windowed (Windowed / Borderless / Fullscreen without the mode switch).
    uimod.dll puts WheelScreenToClient (ScreenToClient + VidModeClientToBackbuffer, PRACX's own
    ClientToBackbuffer) into g_wheel_stc; without the DLL (no stretched modes) it is the plain API."""
    return f"""
    mov     eax, dword ptr [{G_WHEEL_STC:#x}]
    test    eax, eax
    jnz     go
    mov     eax, dword ptr [{RK.IAT_SCREENTOCLIENT:#x}]
go:
    jmp     eax
"""


def asm_rw_wheel_up() -> str:
    """v2: the KEYUP twin -- kind 2 eats whenever the labs bar is stashed (v1); kinds 0/3/4 eat only a key-up
    whose key-down was scrolled (g_rw_wheel_ate)."""
    return f"""
    cmp     dword ptr [{BASEPOP:#x}], 0
    jne     chain
    cmp     dword ptr [{MODAL_TOP:#x}], {RW:#x}
    jne     chain
    mov     eax, dword ptr [{KIND:#x}]
    cmp     eax, 2
    je      klabs
    cmp     eax, 3
    je      kx
    cmp     eax, 4
    je      kx
    test    eax, eax
    jne     chain
kx:
    cmp     dword ptr [{CELL['g_rw_wheel_ate']:#x}], 0
    je      chain
    mov     dword ptr [{CELL['g_rw_wheel_ate']:#x}], 0
    jmp     gate
klabs:
    mov     eax, dword ptr [{CELL['g_rw_sb']:#x}]
    test    eax, eax
    jz      chain
gate:
    call    {GET_TARGET:#x}
    test    eax, eax
    jz      xout
    cmp     dword ptr [esp+0x6C], 0
    jne     xout
    mov     edx, dword ptr [esp+0x68]
    cmp     edx, 0x26
    je      eat
    cmp     edx, 0x28
    jne     xout
eat:
    xor     eax, eax
xout:
    ret
chain:
    jmp     {DL_WHEEL_UP:#x}
"""


def asm_btn_gate_pre_v5() -> str:
    """v6 (2026-09-07) = MISS prefix for the 7 kind-tab + 7 faction-tab FlatButtons (their icons are scaled
    by t_rw_iconblit and their windows by the init lever; the 2D-zoom pipeline must NEVER take them) +
    v5 = report HIT prefix (4 statics + the dynamic list-bar arrows) + DW's v4 VERBATIM (DW HIT prefix
    gated on g_dw_active + SE/council prefixes + v1 body). Why the MISS is explicit: DatalinkWin_open
    restores the report page (ReportIf_activate redraws the tabs) INSIDE its own exec bracket, where
    g_netwin_active=1 admits every FlatButton -> btn_shrink + 2D-zoom magnified the already-scaled icon
    (user shot 122919; probe run 7: BTNGATE KT0..6 -> 1 with netwin=1 dl_exec=1, ICONBLIT btn 30x36).
    Ownership of the thunk moved from the DW in-place upgrade (slot 0x16DA0, 96B) to this bake:
    RELOCATED into the rw region (the old slot is padding); thunk_btn_shrink's single E8 relinks
    through the symbol.
    v7 (2026-09-26): the dynamic list-bar arrow admission moved into the pinned helper t_rw_sbarrows
    (assemble_rw_kinds), which admits the arrows of BOTH stashed console bars g_rw_sbs[0..1] while the
    report is the modal top -- g_rw_sb (the last stashed bar) left the LEFT console list's arrows native
    on hover redraws.  The thunk shrank; t_rw_hdr1 is FROZEN at its slot so nothing after it moves."""
    v4 = DW.asm_btn_gate_pre_v4()
    RK_RANGES = "".join(f"    lea     eax, [esi-{lo:#x}]\n    cmp     eax, {n * 0xB4C:#x}\n    jb      rwhit\n" for lo, n, _ in RK.GATE_RANGES)   # v7: range admissions
    FT_LO, FT_HI = RI + 0x80, RI + 0x80 + 7 * 0xB4C
    KT_LO, KT_HI = RI + 0x5384, RI + 0x5384 + 7 * 0xB4C
    return f"""
    cmp     esi, {FT_LO:#x}
    jb      notft
    cmp     esi, {FT_HI:#x}
    jb      tabmiss
notft:
    cmp     esi, {KT_LO:#x}
    jb      rwv5
    cmp     esi, {KT_HI:#x}
    jae     rwv5
tabmiss:
    xor     eax, eax
    ret
rwv5:
    cmp     esi, 0x87C9D8
    je      rwhit
    cmp     esi, 0x87D524
    je      rwhit
    cmp     esi, {RI + 0xBA0C:#x}
    je      rwhit
    cmp     esi, {RI + 0xC558:#x}
    je      rwhit
{RK_RANGES}    call    t_rw_sbarrows
    test    eax, eax
    jnz     rwhit
    jmp     rwv4
rwhit:
    mov     eax, 1
    ret
rwv4:
{v4}
"""


# ==== listbox_hover_clamp: VANILLA ListBox hover-slot bug ==========================
# ListBox_set_hover 0x60CBC0 bounds the hovered slot against the ITEM COUNT only, never the visible
# rows*cols ([Dialog+0x10]*[Dialog+0xC] = the draw loop's bound @0x60C566/0x60C5B7): a mouse in the band
# below the last row picks item first+rows and draw_item paints it clipped under the list (pristine
# too; user shots 122805/122811, log run 6: slot=8 item=82 first=74 from 0x60cdf4). Two caves; the
# out-of-range case un-hovers through ListBox_clear_hover 0x60CE10 (hover=-1 + vtbl+0xF8 redraw,
# RET 8) when a row was hovered, else plain exit. Register contract at both sites: ebp=element,
# edi=ListBox part (lb), Dialog = lb + [[element]+8]; old hover = [esp+0x10]. Position-independent
# (absolute push/ret exits, `mov eax,imm; call eax`) so the proto (hook_report_kinds_proto.js
# LISTFIX, user-verified 2026-09-07 run 7) and the bake carry IDENTICAL bytes. UNGATED (applies at
# 1024: a base-game bug, logged in the CHANGELOG).
LB_CLEAR_HOVER, LB_HOVER_EXIT = 0x0060CE10, 0x0060CE03
LB_GRID_SITE, LB_GRID_RESUME = 0x0060CC29, 0x0060CD44     # idiv esi / add ebx,eax / jmp 0x60CD44 (9B)
LB_SLOT_SITE, LB_SLOT_RESUME = 0x0060CD44, 0x0060CD4C     # mov ecx,[ebp] / mov eax,[edi-0x30] / add eax,ebx (8B)
_LB_UNHOVER = f"""
unhover:
    mov     eax, dword ptr [esp+0x10]
    cmp     eax, -1
    je      xit
    push    0
    push    0
    mov     ecx, edi
    mov     eax, {LB_CLEAR_HOVER:#x}
    call    eax
xit:
    push    {LB_HOVER_EXIT:#x}
    ret
"""


def asm_lb_hover_grid() -> str:    # grid path (cols > 1): row >= rows -> unhover
    return f"""
    idiv    esi
    push    ecx
    mov     ecx, dword ptr [ebp]
    mov     ecx, dword ptr [ecx+8]
    cmp     eax, dword ptr [ecx+edi+0x10]
    pop     ecx
    jge     unhover
    add     ebx, eax
    push    {LB_GRID_RESUME:#x}
    ret
{_LB_UNHOVER}"""


def asm_lb_hover_slot() -> str:    # common point: slot >= rows*cols -> unhover
    return f"""
    mov     ecx, dword ptr [ebp]
    mov     eax, dword ptr [ecx+8]
    add     eax, edi
    mov     edx, dword ptr [eax+0x10]
    imul    edx, dword ptr [eax+0xC]
    cmp     ebx, edx
    jge     unhover
    mov     eax, dword ptr [edi-0x30]
    add     eax, ebx
    push    {LB_SLOT_RESUME:#x}
    ret
{_LB_UNHOVER}"""


# ==== layout =====================================================================
NEW_THUNKS = [
    ("t_rw_init_enter", asm_rw_init_enter, "rw_scale_shared"),
    ("t_rw_init_leave", asm_rw_init_leave, "rw_scale_shared"),
    ("t_rw_restripe", asm_rw_restripe, "rw_scale_shared"),
    ("t_rw_rowframe", asm_rw_rowframe, "rw_scale_shared"),
    ("t_rw_btnl", asm_rw_btnl, "rw_scale_shared"),
    ("t_rw_gap1", asm_rw_gap1, "rw_scale_shared"),
    ("t_rw_gap2", asm_rw_gap2, "rw_scale_shared"),
    ("t_rw_scrollsmall", asm_rw_scrollsmall, "rw_scale_shared"),
    ("t_rw_scrollnormal", asm_rw_scrollnormal, "rw_scale_shared"),
    ("t_rw_sbinit", asm_rw_sbinit, "rw_scale_shared"),
    ("t_rw_lbclose", asm_rw_lbclose, "rw_scale_shared"),
    ("t_rw_wheel_down", asm_rw_wheel_down, "rw_scale_shared"),
    ("t_rw_wheel_up", asm_rw_wheel_up, "rw_scale_shared"),
    ("t_rw_wheel_have", asm_rw_wheel_have, "rw_scale_shared"),
    ("t_rw_wheel_energy", asm_rw_wheel_energy, "rw_scale_shared"),
    ("t_rw_wheel_hfail", asm_rw_wheel_hfail, "rw_scale_shared"),
    ("t_wheel_stc", asm_wheel_stc, "rw_scale_shared"),
    ("t_rw_iconblit", asm_rw_iconblit, "rw_scale_shared"),
    ("thunk_btn_gate_pre", asm_btn_gate_pre_v5, "rw_scale_shared"),
    ("t_rw_hdr1", asm_rw_hdr1, "rw_scale_tech"),
    ("t_rw_hdr2", asm_rw_hdr2, "rw_scale_tech"),
    ("t_rw_hdr3", asm_rw_hdr3, "rw_scale_tech"),
    ("t_rw_title", asm_rw_title, "rw_scale_tech"),
    ("t_rw_crest", asm_rw_crest, "rw_scale_tech"),
    ("t_rw_bar", asm_rw_bar, "rw_scale_tech"),
    ("t_rw_labs_enter", asm_rw_labs_enter, "rw_scale_tech"),
    ("t_rw_labs_leave", asm_rw_labs_leave, "rw_scale_tech"),
    ("t_rw_techpage", asm_rw_techpage, "rw_scale_tech"),
    ("t_rw_backdrop", asm_rw_backdrop, "rw_scale_shared"),
    ("t_rw_tabsplit1", asm_rw_tabsplit1, "rw_scale_shared"),
    ("t_rw_tabsplit2", asm_rw_tabsplit2, "rw_scale_shared"),
    ("t_rw_labs_rw", asm_rw_labs_rw, "rw_scale_tech"),      # 2026-10-17: in tabsplit v2's freed slot tail (FROZEN t_rw_btnr)
    ("t_rw_tabpair", asm_rw_tabpair, "rw_scale_shared"),    # pinned (RK.PINNED)
    ("t_rw_insetv", asm_rw_insetv, "rw_scale_shared"),      # pinned
    ("t_rw_immsum", asm_rw_immsum, "rw_scale_shared"),      # pinned (2026-10-17 console chain)
    ("t_rw_labs_w", asm_rw_labs_w, "rw_scale_tech"),        # pinned
    ("t_rw_labs_h", asm_rw_labs_h, "rw_scale_tech"),        # pinned
    ("t_rw_labs_rh", asm_rw_labs_rh, "rw_scale_tech"),      # pinned
    ("t_rw_btnr", asm_rw_btnr, "rw_scale_shared"),
    ("t_rw_techhover", asm_rw_techhover, "rw_scale_tech"),
    ("t_lb_hover_grid", asm_lb_hover_grid, "listbox_hover_clamp"),
    ("t_lb_hover_slot", asm_lb_hover_slot, "listbox_hover_clamp"),
] + [(n, f, "rw_scale_kinds") for n, f in RK.THUNKS]
DATA = [("g_rw_immtab", lambda: RW_TAB), ("g_rw_immtab_tech", lambda: TECH_TAB), ("g_wheel_stc", lambda: bytes(4))]


def assemble_all():
    """Two-phase: code size fixes the table/cell VAs, which the code references -> iterate."""
    names = {n: PCAVE2 + OFF_CODE for n, _f, _g in NEW_THUNKS}
    code_end = OFF_CODE + 0x1800     # provisional
    layout = {}
    for _pass in range(8):
        cells, cells_end = layout_tables_and_cells(code_end)
        prev = (dict(names), code_end)
        off = OFF_CODE
        for name, fn, _g in NEW_THUNKS:
            if name in RK.PINNED:                    # v4: pinned free-slot helpers (the rw region is full)
                poff = RK.PINNED[name]
                b = SE.assemble(fn(), PCAVE2 + poff, names)
                assert poff + len(b) <= RK.PINNED_END[name], (name, poff, len(b), RK.PINNED_END[name])
                layout[name] = (poff, b)
                names[name] = PCAVE2 + poff
                continue
            if name in FROZEN:                       # a predecessor shrank: keep the baked slot map
                assert off <= FROZEN[name], (name, off, FROZEN[name])
                off = FROZEN[name]
            b = SE.assemble(fn(), PCAVE2 + off, names)
            layout[name] = (off, b)
            names[name] = PCAVE2 + off
            off = (off + len(b) + 15) & ~15
        code_end = off
        if (dict(names), code_end) == prev:
            break
    else:
        raise RuntimeError("layout did not converge")
    spans = sorted((o, o + len(b), n) for n, (o, b) in layout.items())
    for (o1, e1, n1), (o2, _e2, n2) in zip(spans, spans[1:]):
        assert e1 <= o2, f"thunk overlap: {n1} {o1:#x}..{e1:#x} runs into {n2} @{o2:#x}"
    # a FOREIGN occupant this script does not emit: assemble_dl's t_dl_tile_ph is pinned in the gap between
    # t_rw_init_leave and the frozen t_rw_restripe (cave_map.py --at 0x23460)
    il_off, il_b = layout["t_rw_init_leave"]
    assert il_off + len(il_b) <= DL_TILE_PH_OFF, f"t_rw_init_leave ends {il_off + len(il_b):#x} > t_dl_tile_ph {DL_TILE_PH_OFF:#x}"
    cells, cells_end = layout_tables_and_cells(code_end)
    layout["g_rw_immtab"] = (TAB_RW - PCAVE2, RW_TAB)
    layout["g_rw_immtab_tech"] = (TAB_TECH - PCAVE2, TECH_TAB)
    layout["g_wheel_stc"] = (G_WHEEL_STC - PCAVE2, bytes(4))
    assert names["t_wheel_stc"] == WHEEL_STC and WHEEL_STC + len(layout["t_wheel_stc"][1]) <= G_WHEEL_STC
    return layout, cells, cells_end, names


# Frozen offsets: t_rw_init_leave shrank (fonts v2) -- every later thunk, the tables and the cells keep
# their baked offsets (assemble_mon.py chains into t_rw_iconblit by literal VA; the DLL reads g_big_f4).
DL_TILE_PH_OFF = 0x23AC0   # assemble_dl.TILE_PH_OFF (t_dl_tile_ph, dl_scale), pinned in t_rw_init_leave's freed tail
FROZEN = {"t_rw_restripe": 0x23C20, "t_rw_hdr1": 0x24360,   # t_rw_hdr1: thunk_btn_gate_pre shrank (v7, 2026-09-26)
          "t_rwk_bases_namex": 0x24A10,   # rw_scale_kinds v18: t_rwk_proj_rowdiv / t_rwk_proj_rowy / t_rwk_units_rowdiv pinned out (0x24970..0x24A10 left free)
          "t_rw_wheel_up": 0x24110,
          # 2026-10-17 console tab pairs v2: the split caves shrank -> the next thunks keep their baked slots
          "t_rw_btnr": 0x24830, "t_rwk_sat_split1": 0x24B10,
          # 2026-10-25 W2A (F30): t_rw_gap1 / t_rw_gap2 v2 shrank (41 -> 18B, 49 -> 18B) -> the next thunks keep their slots
          "t_rw_gap2": 0x23E60, "t_rw_scrollsmall": 0x23EA0}   # t_rw_wheel_up keeps its slot: t_rw_wheel_have is pinned in t_rw_wheel_down's freed tail

SYM_ABS = {
    T_FFN: "t_ffn", T_FDIRECT_A14B: "t_fdirect_a14b",
    G: "g_popup_scale_num", HOLLOWFLAT: "thunk_box_thick_hollow_flat", DEVFILL: "thunk_box_thick_devfill",
    G_NETWIN: "g_netwin_active", G_RAIL_SB: "g_rail_sb", G_DL_IMMG: "g_dl_immg", AD.VPDONE: "g_dl_vpdone", G_DL_EXEC: "g_dl_exec",
    G_DL_SNAPBUF: "g_dl_snapbuf", T_DL_IMMFIX: "t_dl_immfix", T_DL_BMXT: "t_dl_bmxt",
    DL_WHEEL_DOWN: "t_dl_wheel_down", DL_WHEEL_UP: "t_dl_wheel_up", BTN_GATE: "thunk_btn_gate",
    STR_K32: "g_ed_str_k32", STR_VP: "g_ed_str_vp", FACTION_PORTRAIT: "thunk_faction_portrait",
    G_SCROLLBAR_W: "g_scrollbar_w", G_FSR: "g_faction_scratch_rect", G_FC_EXACT: "g_fc_exact",
    AN_STR: "an_str",
    RK.FE_PAIR_REMAP: "thunk_fe_pair_remap", RK.G_RM_FORCE: "g_rm_force", RK.G_FE_DST: "g_fe_dst",
    RK.G_BIG_F4: "g_big_f4",
    RK.G_FE_X: "g_fe_x", RK.G_FE_Y: "g_fe_y", RK.G_FE_W: "g_fe_w", RK.G_FE_H: "g_fe_h",
    RK.SCALE_NN: "thunk_sprite_scale_nn",
    RK.SPRITE_BILINEAR: "thunk_sprite_bilinear",
    G_WHEEL_STC: "g_wheel_stc",
    T_RW_BTNW: "t_rw_btnw",
}


def templatize(b: bytes, va: int, names: dict[str, int]) -> str:
    syms = dict(SYM_ABS)
    syms.update({v: n for n, v in names.items()})
    syms[TAB_RW] = "g_rw_immtab"
    syms[TAB_TECH] = "g_rw_immtab_tech"
    for n, v in CELL.items():
        syms[v] = n
    syms[CELL['g_rw_rect'] + 4] = None; syms[CELL['g_rw_rect'] + 8] = None; syms[CELL['g_rw_rect'] + 12] = None
    syms = {k: v for k, v in syms.items() if v}
    return SE.templatize(b, va, syms)


def hx(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


# ---- sites -------------------------------------------------------------------
def site_list(names: dict[str, int]) -> list[dict]:
    S = []

    def add(sid, grp, fn, va, orig, new, pattern, note=""):
        S.append({"id": sid, "group": grp, "function": fn, "va": va, "orig": orig, "new": new, "pattern": pattern, "note": note})

    def redirect(sid, grp, fn, va, native_target, thunk, note=""):
        orig = bytes([0xE8]) + struct.pack("<i", native_target - (va + 5))
        add(sid, grp, fn, va, orig, f"E8 {{rel32:{thunk}}}", "call_target_redirect", note)

    def detour(sid, grp, fn, va, ln, thunk, note=""):
        orig = SE.base_exe_bytes(va, ln)
        jmp = hx(bytes([0xE9]) + struct.pack("<i", names[thunk] - (va + 5)))
        add(sid, grp, fn, va, orig, jmp + " 90" * (ln - 5), "detour_inplace", f"{note} (E9 -> {thunk})")

    SH_, TE = "rw_scale_shared", "rw_scale_tech"
    detour("init_report_screen.enter", SH_, "init_report_screen", IRS, 5, "t_rw_init_enter",
           "ret-swap -> t_rw_init_leave: window/clip/font lever, imm table walk, tables, fonts, snapbuf (g>16)")
    detour("ReportIf_activate.row_left_inset", SH_, "ReportIf_activate", 0x4A43BA, 10, "t_rw_btnl", "row L = clipL + s(0x4B) (disp8 overflow)")
    detour("ReportIf_activate.row_right_edge", SH_, "ReportIf_activate", 0x4A43CF, 7, "t_rw_btnr", "row R = clipL + clipR - L (centred on the clip at every g)")
    detour("ReportIf_activate.gap_left", SH_, "ReportIf_activate", 0x4A4418, 9, "t_rw_gap1", "DATALINKS w -= s(2)>>1")
    detour("ReportIf_activate.gap_right", SH_, "ReportIf_activate", 0x4A44D4, 10, "t_rw_gap2", "CLOSE x += s(2)-a, w -= s(2)-a")
    detour("ScrollBar_init_inner.rw_stash", SH_, "ScrollBar_init_inner", SB_INIT_INNER, 5, "t_rw_sbinit", "report list bar -> g_rw_sb / g_rail_sb")
    redirect("ReportWin_show.row_frame", SH_, "ReportWin_show", 0x496CD0, BOX_SPRITE, "t_rw_rowframe", "d5a0 row frame: exact-fill half-open helper -> thunk_box_thick_hollow_flat (g<=16 native)")
    redirect("ReportWin_show.window_backdrop", SH_, "ReportWin_show", 0x496C91, BOX_SPRITE, "t_rw_backdrop", "d690 backdrop+border: exact-fill half-open helper -> thunk_box_thick_devfill (g<=16 native)")
    detour("ReportIf_activate.tabsplit_tech", SH_, "ReportIf_activate", 0x4A45B6, 6, "t_rw_tabsplit1", "v2: TECH rect = t_rw_tabpair(left) (law rw_tab_pair), resume 0x4A45D9")
    detour("ReportIf_activate.tabsplit_bases", SH_, "ReportIf_activate", 0x4A4675, 7, "t_rw_tabsplit2", "v2: BASES rect = t_rw_tabpair(right) (law rw_tab_pair), resume 0x4A4693")
    # 2026-10-17 console tab pairs v2: the F2 labs painter's boxes -- far edges mirror the near ones, drawn half-open
    detour("ReportIf_console_labs.left_w", TE, "ReportIf_console_labs", 0x4A7032, 7, "t_rw_labs_w", "left cursor w = W - 2*s(6) (law rw_console_inset_w; was W - s(0xC))")
    detour("ReportIf_console_labs.left_h", TE, "ReportIf_console_labs", 0x4A704A, 9, "t_rw_labs_h", "left cursor h = H - 2*s(6)")
    detour("ReportIf_console_labs.right_w", TE, "ReportIf_console_labs", 0x4A7A78, 9, "t_rw_labs_rw", "right cursor w = W - 2*s(6)")
    detour("ReportIf_console_labs.right_h", TE, "ReportIf_console_labs", 0x4A7A8F, 9, "t_rw_labs_rh", "right cursor h = H - 2*s(6)")
    redirect("ReportIf_console_labs.tab_box", TE, "ReportIf_console_labs", 0x4A7094, BOX_SPRITE, "t_rwk_boxforce", "TECHNOLOGY|BASES d5a0 tab box: half-open R-1/B-1 + C6/41 force restripe (the F4 tab strip's treatment; was inclusive via hud_boxframe -> R/B channel +1)")
    redirect("ReportIf_console_labs.list_box", TE, "ReportIf_console_labs", 0x4A70BF, BOX_SPRITE, "t_rw_rowframe", "tech list d528: half-open R-1/B-1 exact-fill helper (was inclusive via hud_boxframe)")
    redirect("ReportIf_console_labs.title_box", TE, "ReportIf_console_labs", 0x4A7AD6, BOX_SPRITE, "t_rw_rowframe", "right panel title d528: half-open")
    redirect("ReportIf_console_labs.body_box", TE, "ReportIf_console_labs", 0x4A7B01, BOX_SPRITE, "t_rw_rowframe", "right panel body d528: half-open")
    redirect("ReportIf_console_chrome.centre_d528", SH_, "ReportIf_console_chrome", 0x4A3EA4, BOX_SPRITE, "t_rw_rowframe", "centre panel inner d528: half-open (was inclusive: inner channel L5 R4 T5 B4 at 4K)")
    redirect("ReportIf_console_chrome.strip_d528", SH_, "ReportIf_console_chrome", 0x4A3EB4, BOX_SPRITE, "t_rw_rowframe", "kind-icon strip inner d528: half-open")
    RK.add_sites(add, redirect, detour)
    # 2026-10-17 console chain: every console painter's d528 content box drawn half-open (was inclusive through
    # thunk_hud_boxframe: R/B one past the mirror of L/T) -- the labs / chrome d528s' treatment (t_rw_rowframe)
    for va, fn, what in D528_SITES:
        redirect(f"{fn}.d528_{va:X}", "rw_scale_kinds", fn, va, BOX_SPRITE, "t_rw_rowframe",
                 f"{what} d528: half-open exact-fill helper (was inclusive via hud_boxframe)")
    redirect("ReportIf_console_labs.scroll_small", SH_, "ReportIf_console_labs", 0x4A7114, SCROLL_SMALL, "t_rw_scrollsmall", "g_scrollbar_w 12 -> s(12) inside the list attach; inlist=1")
    redirect("ReportIf_console_labs.scroll_normal", SH_, "ReportIf_console_labs", 0x4A75C9, SCROLL_NORMAL, "t_rw_scrollnormal", "inlist=0")
    redirect("ReportIf_hide_labs_widgets.listbox_close", SH_, "ReportIf_hide_labs_widgets", 0x4A8479, LISTBOX_CLOSE, "t_rw_lbclose", "drop the bar stashes")
    for va in TECH_CALLERS:
        redirect(f"ReportWin_paint.tech_page_{va:06x}", TE, "ReportWin_painter", va, TECH_PAGE, "t_rw_techpage", "tech bracket: DL tech imms + g_dl_exec around the call, header restripe after")
    detour("tech_page.hdr_band", TE, "ReportWin_tech_page", 0x498C99, 9, "t_rw_hdr1", "band h 0x46 / +3 / +0x43 -> s()")
    detour("tech_page.hdr_wide", TE, "ReportWin_tech_page", 0x498CCF, 5, "t_rw_hdr2", "wide extension 0x62 mask -> s()")
    detour("tech_page.hdr_icon", TE, "ReportWin_tech_page", 0x498E43, 6, "t_rw_hdr3", "brain icon target 0x40 -> s()")
    redirect("tech_page.hdr_band_frame", TE, "ReportWin_tech_page", 0x498D9B, BOX_SPRITE, "t_dl_bmxt", "outer band frame -> K stroke (bracket exec=1)")
    redirect("tech_page.hdr_textbox_frame", TE, "ReportWin_tech_page", 0x498E6C, BOX_SPRITE, "t_dl_bmxt", "text box frame -> K stroke (+restripe in t_rw_techpage)")
    detour("ReportIf_console_labs.title_inset", TE, "ReportIf_console_labs", 0x4A75FF, 5, "t_rw_title", "and eax,0x4C mask -> s(0x4C) (imm8 overflow)")
    detour("ReportIf_activate.crest_size", TE, "ReportIf_activate", 0x4A5B43, 6, "t_rw_crest", "crest 0x46 -> s() (imm8 overflow)")
    detour("ReportIf_console_labs.enter", TE, "ReportIf_console_labs", LABS, 9, "t_rw_labs_enter", "ret-swap -> t_rw_labs_leave: restripe the recorded bar rects")
    for va in BAR_SITES:
        redirect(f"ReportIf_console_labs.bar_{va:06x}", TE, "ReportIf_console_labs", va, BOX_SPRITE, "t_rw_bar", "research bar: record + NATIVE 9-slice (bypass hud_boxframe)")
    add("ReportWin_vtbl.tech_hover", TE, "ReportWin_vtbl", RW_VTBL_HOVER, struct.pack("<I", TECH_HOVER), "{abs32:t_rw_techhover}", "vtable_repoint",
        "ReportWin_tech_hover slot (+0xA0): F2 hover/un-hover frame draws bracketed like the paint (DL tech imms g + g_dl_exec) -> K strokes, no stray native ring")
    add("ReportIf_activate.kindtab_h", TE, "ReportIf_activate", 0x4A42E0, bytes.fromhex("8B8EB04F0000"), "B9 24 00 00 00 90", "inplace_rewrite",
        "mov ecx,[esi+0x4FB0] -> mov ecx,imm32 (native 0x24; scaled by the g_rw_immtab row)")
    add("ReportIf_activate.kindtab_w", TE, "ReportIf_activate", 0x4A42E6, bytes.fromhex("8B96AC4F0000"), "BA 1E 00 00 00 90", "inplace_rewrite",
        "mov edx,[esi+0x4FAC] -> mov edx,imm32 (native 0x1E; scaled by the g_rw_immtab row)")
    LB = "listbox_hover_clamp"
    detour("ListBox_set_hover.grid_row_clamp", LB, "ListBox_set_hover", LB_GRID_SITE, 9, "t_lb_hover_grid", "VANILLA bug: grid path row >= rows -> un-hover (was: item beyond the visible rows drawn clipped)")
    detour("ListBox_set_hover.slot_clamp", LB, "ListBox_set_hover", LB_SLOT_SITE, 8, "t_lb_hover_slot", "VANILLA bug: slot >= rows*cols -> un-hover via ListBox_clear_hover")
    return S


# existing yaml sites whose new_bytes must be RETARGETED (edited in place in patches.yaml)
RETARGETS = [
    ("WinProc.wm_keydown_target", "E8 {rel32:t_dl_wheel_down}", "E8 {rel32:t_rw_wheel_down}"),
    ("WinProc.wm_keyup_target", "E8 {rel32:t_dl_wheel_up}", "E8 {rel32:t_rw_wheel_up}"),
    ("FlatButton_content_draw.faction_dropdown_img", "E8 {rel32:thunk_faction_portrait}", "E8 {rel32:t_rw_iconblit}"),
]


def verify_live(sites) -> list[str]:
    probs = []
    for s in sites:
        cur = SE.base_exe_bytes(s["va"], len(s["orig"]))
        if cur != s["orig"]:
            probs.append(f"{s['id']} @{s['va']:#x}: base {cur.hex()} != expected {s['orig'].hex()}")
    return probs


def native_identity_problems() -> list[str]:
    probs = []
    for site, w, a, b, lbl in RW_IMMS:
        if site in IDENTITY_EXEMPT:
            continue
        want = SL.scale_px(a, 16) - SL.scale_px(b, 16)
        raw = SE.base_exe_bytes(site, 4 if w == 4 else 1)
        have = struct.unpack("<i", raw)[0] if w == 4 else struct.unpack("<b", raw)[0]
        if have != want:
            probs.append(f"imm @{site:#x} base={have} vs native={want} ({lbl})")
    return probs


def site_yaml(sites) -> str:
    lines = []
    for s in sites:
        lines.append(
            f"  - id: {s['id']}\n    status: confirmed\n    group: {s['group']}\n    function: {s['function']}\n"
            f"    virtual_addr: {s['va']:#010x}\n    length: {len(s['orig'])}\n    original_bytes: \"{hx(s['orig'])}\""
            + (f"   # {s['note']}" if s["note"] else "") + "\n"
            f"    new_bytes:      \"{s['new']}\"\n    pattern: {s['pattern']}\n")
    return "\n".join(lines)


def main(argv):
    layout, cells, cells_end, names = assemble_all()
    ok = True
    code_end = max(o + len(b) for n, (o, b) in layout.items() if (n.startswith("t_") or n.startswith("thunk_")) and n not in RK.PINNED)
    print("; ==== HQ report screens bake (assemble_rw.py) ====")
    print(f"; code {OFF_CODE:#x}..{code_end:#x} ({code_end - OFF_CODE}B); tables rw {TAB_RW - PCAVE2:#x} ({len(RW_TAB)}B, {len(rw_rows())} rows) tech {TAB_TECH - PCAVE2:#x} ({len(TECH_TAB)}B, {len(tech_rows())} rows); cells end {cells_end:#x}; limit {OFF_LIMIT:#x}")
    if cells_end > OFF_LIMIT:
        ok = False
        print("; OVERFLOW into the g_dl_* cells")
    sym_lines, content_lines = [], []
    for name, (off, size) in cells.items():
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {size} }}")
    for name, _fn in DATA:
        off, b = layout[name]
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x}, size: {len(b)} }}")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{hx(b)}\"")
    for name, _fn, grp in NEW_THUNKS:
        off, b = layout[name]
        sym_lines.append(f"  {name + ':':<31}{{ cave: pcave2, offset: {off:#x} }}   # {grp} ({len(b)}B)")
        content_lines.append(f"      - id: {name}\n        offset: {off:#x}\n        bytes: \"{templatize(b, PCAVE2 + off, names)}\"")
        print(f"; {name} @{off:#x} len {len(b)} end {off + len(b):#x}")
    sites = site_list(names)
    for p in verify_live(sites):
        ok = False
        print("; LIVE MISMATCH:", p)
    for p in native_identity_problems():
        ok = False
        print("; NATIVE-IDENTITY:", p)
    ids = [s["id"] for s in sites]
    if len(ids) != len(set(ids)):
        ok = False
        print("; DUPLICATE SITE IDS")
    def _site_tuple(s):
        toks = s["new"].split() if isinstance(s["new"], str) else [f"{b:02X}" for b in s["new"]]
        first = int(toks[0], 16) if toks and not toks[0].startswith("{") else -1
        return (s["va"], sum(4 if x.startswith("{") else 1 for x in toks), first, s["id"])
    chain = [(site, 0, 0, K['K_W4'] if w == 4 else 0) for site, w, *_ in CHAIN_ROWS]
    for site, sid in row_site_conflicts(rw_rows() + tech_rows() + chain, [_site_tuple(s) for s in sites]):
        ok = False
        print(f"; ROW/SITE CONFLICT: walker row {site:#x} inside site {sid}")
    if "--fragments" in argv:
        frag = os.path.join(os.path.dirname(__file__), "..", "patches")
        with open(os.path.join(frag, "_fragment_rw_symbols.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(sym_lines) + "\n")
        with open(os.path.join(frag, "_fragment_rw_cave.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(content_lines) + "\n")
        with open(os.path.join(frag, "_fragment_rw_sites.yaml"), "w", encoding="utf-8", newline="\n") as f:
            f.write(site_yaml(sites))
        print("; fragments written to work/patches/_fragment_rw_*.yaml")
    print(f"; sites: {len(sites)} (+{len(RETARGETS)} retargets)")
    print(f"; RESULT: {'ALL OK' if ok else 'FAILURES - do not bake'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
