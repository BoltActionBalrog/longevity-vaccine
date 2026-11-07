// uimod "Longevity Mod Preferences" -- a new tab in the game's Preferences window with a
// font-scale slider for the on-map base-name/landmark labels.
//
// The slider interpolates the map-label font size between PRISTINE (left, pct=0: the
// vanilla min(12, zoom-derived) size) and the FULL patched scale (right, pct=100:
// size x g/16). The percent lives in the exe code cave (g_map_font_pct @ 0xA1712C) where
// thunk_map_font -- the redirect target of the 3 MapWin_calculate_dimensions Font_init
// sites -- reads it per re-init: size' = native*(16+(g-16)*pct/100)>>4 (law
// scaling_laws.map_label_font_size). Persisted as [UIMod] MapLabelFontScale in
// "Alpha Centauri.ini" (same section as the movie player's UpscaledVideos).
//
// UI mechanism (ground truth from the PrefWin decompiles, 2026-07-12 session):
//   * PrefWin (static @ 0x8578D8, vtable 0x66D424) builds in PrefWin_build (0x48D840, sole caller
//     desktop_init @ 0x58EED5) -- AGAIN on every game load, tearing our widgets down (see BuildWidgets). Tab buttons are FlatButtons
//     (ids 0..5, y pitch 0x16) in ButtonGroup 0x8577F0; Gamma Correction (id 6) sits at
//     y0+0x9A leaving one blank row after Map Preferences (y0+0x6E).
//   * We patch (byte-checked, at Init time -- the DLL loads before desktop_init):
//       - the gamma button's `ADD EDX,0x9A` imm @ 0x48DD03 -> 0xB0 (down one row), and
//       - the desktop_init call rel32 @ 0x58EED6 -> our thunk, which chains the real
//         PrefWin_build then builds our widgets.
//   * Our widgets are DLL statics constructed with the ENGINE's own classes
//     (FlatButton_ctor/BaseButton_init, ScrollBar ctor/init/set_range/set_pos) parented
//     to PrefWin, so the baked prefwin_scale machinery scales them like the stock 19:
//     GraphicWin_init entry-gate (B) scales children of PrefWin; the DLL WIDGET REGISTRY
//     (g_dll_pref_lo/hi/slider @ 0xA17120/24/28, zero until we fill them) extends the
//     FlatButton/ScrollBar zoom stubs + the slider-internals init gate to our instances.
//   * Tab switching: a tab click runs ButtonGroup_select -> PrefWin vtbl+0xB8 (stores
//     [0xA14]=new id) -> vtbl+0xB0 (command switch; unknown ids fall through to a
//     refresh). The engine's show/hide switches (0x48FFB0/0x490140) have no case for our
//     id, so they show NOTHING for our tab -- our vtbl+0x30 (refresh) wrapper shows/hides
//     our label+slider by [0xA14]==kTabId and draws the slider-area frame.
//   * Persistence follows the volume sliders' semantics: live-apply on drag (vtbl+0xC4),
//     write the ini only on commit (OK button id 0x5C via vtbl+0xB0, or the Enter key via
//     vtbl+0x64 key 0xD); ESC/Cancel keeps the session value but does not persist.
//     Restore Defaults (id 0x5A) resets to 100 (full scale, the mod default). A single chevron click
//     notifies through vtbl+0xC0 instead (PrefWin's slot is a `ret 8` stub), wrapped to the same handler.
//   * A second slider row ("Drag Hold Time", dragdelay.cpp) sits in the audio page's row 1 (y + 0x16);
//     the one-slider registry slot is re-pointed around its draws by a private vtable (HoldSliderDraw).
//   * On pct change we invalidate MapWin's zoom cache (+0x1EEC0) and the 3 font size
//     caches (+0x1EEF0/+0x1EF1C/+0x1EF48) so the next map draw re-runs the Font_inits
//     through thunk_map_font; the engine itself calls draw_map(1) when the prefs window
//     closes, which repaints the labels at the new size.

#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "prefs.h"
#include "aivis.h"
#include "portrait.h"
#include "vidmode.h"
#include "dragdelay.h"
#include "modernctl.h"
#include "update.h"

void UimodLog(const char* msg);   // init.cpp: uimod.log + debugger
void UimodDbg(const char* msg);   // init.cpp: only with [UIMod] DebugLog=1 (developer geometry dumps)

namespace {

// ---- terranx.exe absolute VAs (image base 0x400000) ------------------------------

constexpr uintptr_t kImageBase = 0x00400000;

constexpr uintptr_t kVA_PrefWin        = 0x008578D8;  // PrefWin object (GraphicWin static)
constexpr uintptr_t kVA_PrefWinVtbl    = 0x0066D424;  // PrefWin class vtable (.rdata)
constexpr uintptr_t kVA_PrefTabGroup   = 0x008577F0;  // the 6-tab ButtonGroup static
constexpr uintptr_t kVA_GammaAddImm    = 0x0048DD01;  // ADD EDX,0x9A (imm32 at +2)
constexpr uintptr_t kVA_BuildCallSite  = 0x0058EED5;  // desktop_init: E8 -> PrefWin_build
constexpr uintptr_t kVA_PrefWinBuild   = 0x0048D840;

// engine widget API (all __thiscall)
constexpr uintptr_t kVA_FindFont       = 0x005882F0;  // cdecl(size, variant) -> Font*
constexpr uintptr_t kVA_FontDirectA14B = 0x00A3A590;  // pcave2+0x2E590 t_fdirect_a14b() cdecl -> Font* (font_face_law; gate on Pcave2Present)
constexpr uintptr_t kVA_PopupScaleNum  = 0x00668740;  // g_popup_scale_num (16..40)
constexpr uintptr_t kVA_FlatButtonCtor = 0x00607CF0;
constexpr uintptr_t kVA_BaseButtonInit = 0x00607210;  // (text,id,x,y,w,h,parent,a9) -> int
constexpr uintptr_t kVA_ScrollBarCtor  = 0x006051D0;
constexpr uintptr_t kVA_ScrollBarInit  = 0x006058D0;  // (x,y,w,parent,id) -> int
constexpr uintptr_t kVA_ScrollBarRange = 0x006059B0;  // (min,max)
constexpr uintptr_t kVA_ScrollBarSet   = 0x00605D20;  // (pos)
constexpr uintptr_t kVA_ButtonGroupAdd = 0x0062B850;  // (ecx=group; btn)

// PrefWin layout statics (values computed by the engine's static initializers; we READ
// them at build time -- native units, the baked GraphicWin_init gate scales at the
// construction boundary)
constexpr uintptr_t kVA_TabX      = 0x0085788C;
constexpr uintptr_t kVA_TabY0     = 0x00857890;
constexpr uintptr_t kVA_TabW      = 0x00857894;
constexpr uintptr_t kVA_TabH      = 0x00686B88;
constexpr uintptr_t kVA_LabelX    = 0x008578B4;
constexpr uintptr_t kVA_LabelY0   = 0x008578BC;
constexpr uintptr_t kVA_LabelW    = 0x00686B8C;
constexpr uintptr_t kVA_LabelH    = 0x00686B90;
constexpr uintptr_t kVA_SliderX   = 0x008578CC;
constexpr uintptr_t kVA_SliderY0  = 0x008578D0;
constexpr uintptr_t kVA_SliderW   = 0x008578B8;
constexpr uintptr_t kVA_BotShift  = 0x00872CA8;   // the SW==800 bottom-stack shift
constexpr uintptr_t kVA_FrameX    = 0x008577D8;   // audio slider-area frame rect statics
constexpr uintptr_t kVA_FrameY    = 0x008577DC;
constexpr uintptr_t kVA_FrameH    = 0x008577E0;
constexpr uintptr_t kVA_FrameW    = 0x008577E4;
constexpr uintptr_t kVA_PrefWinInst      = 0x008578D8;   // PrefWin static instance
constexpr uintptr_t kVA_PrefWinRefreshFn = 0x00491C00;   // PrefWin_refresh (vtbl+0x30, thiscall): full page repaint
constexpr uintptr_t kVA_FrameArt  = 0x0078D690;   // the d690 box-sprite params (filled frame)

// exe code cave (pcave2): the DLL widget registry + the font-scale percent + the
// PrefWin chrome thunk (rect x g/16 + thick-stroke dispatch; Buffer_box_sprite contract)
constexpr uintptr_t kVA_DllPrefLo     = 0x00A17120;
constexpr uintptr_t kVA_DllPrefHi     = 0x00A17124;
constexpr uintptr_t kVA_DllPrefSlider = 0x00A17128;
constexpr uintptr_t kVA_MapFontPct    = 0x00A1712C;
constexpr uintptr_t kVA_BigF4         = 0x00A17170;  // g_big_f4: "Large F4 Base Indicators" flag read by t_rwk_blink
constexpr uintptr_t kVA_PrefBoxFrame  = 0x00A16D00;  // thunk_pref_boxframe
constexpr uintptr_t kVA_DrawMap       = 0x0046B190;  // draw_map, cdecl(int) -- full map repaint
constexpr uintptr_t kVA_SpriteDraw2   = 0x005E4B4A;  // Sprite_draw_2: thiscall(ecx=Sprite)(dest,key,x,y,num,den) RET 0x18
constexpr uintptr_t kVA_BufSetFont    = 0x005DAC70;  // Buffer_set_font(f0,f1,f2,f3) RET 0x10
constexpr uintptr_t kVA_BufSetColor   = 0x005DACB0;  // Buffer_set_text_color(color,a3,a4,a5)
constexpr uintptr_t kVA_BufWriteL3    = 0x005DCEA0;  // Buffer_write_l_3(str,x,y,len): left text at (x,y)
constexpr uintptr_t kVA_FontWidth     = 0x00619280;  // Font_width: thiscall(ecx=Font)(str) -> px
constexpr uintptr_t kVA_FlatBtnVtbl   = 0x00669754;  // FlatButton vtable (+0x30 content_draw, +0x4C release -> parent command)
constexpr uintptr_t kVA_GWinClear     = 0x005D5250;  // GraphicWin_clear(color) RET 4: fills the window canvas (key = transparent)
constexpr uintptr_t kVA_BufSetPal     = 0x005DE8F0;  // canvas palette sync (FlatButton_content_draw's first call) RET 4
constexpr uintptr_t kVA_MainPalette   = 0x009B8180;  // the palette object it passes
constexpr uintptr_t kVA_TransKey      = 0x00696D14;  // byte: the UI transparency key (9)
constexpr uintptr_t kVA_ChkOffSprite  = 0x00779504;  // the Preferences CheckList's unchecked box (sprite_a, g_checkbox_sprites[1])
constexpr uintptr_t kVA_ChkOnSprite   = 0x00779530;  // its checked box (sprite_b, g_checkbox_sprites[2])
// fix 28 (2026-10-24): the checkbox X sprites carry a 1-row scanline dither; the engine's NN at g/16 bands it.  The exe's
// t_ck_draw (pcave2+0x33000, group checkbox_stripes; Sprite_draw_2 contract) draws them by the scaling law
// (scaling_laws.scanicon_pixels) on the dest canvas's stripe grid advanced by g_ck_ph -- the same entry the stock
// CheckList rows reach through t_ck_list.  Gate: inside .pcave2 AND its entry bytes (an exe without fix 28 may still
// have the section that long), else the old Sprite_draw_2 call.
constexpr uintptr_t kVA_CkDraw        = 0x00A3F000;  // t_ck_draw: thiscall(ecx=Sprite)(dest,key,x,y,num,den) RET 0x18
constexpr uintptr_t kVA_CkPhase       = 0x00A3FFF0;  // g_ck_ph: t_ck_draw's grid phase (0 at rest)
constexpr uintptr_t kVA_StripePeriod  = 0x0066879C;  // g_stripe_period: P = 2T, written with g by thunk_ensure_scale
constexpr BYTE kCkDrawEntry[] = { 0x81, 0xF9, 0xD8, 0x94, 0x77, 0x00, 0x74, 0x10, 0x81, 0xF9, 0x04, 0x95 };   // cmp ecx,7794D8h; je; cmp ecx,779504h...
// The PrefWin pages' CheckLists (PrefWin_ctor 0x492272..0x4922E2: seven CheckList_ctor calls, stride 0xB28;
// CheckList vtbl 0x670718: [+4] = 0x1C GraphicWin part, [+8] = 0xA34 Dialog part).  The stock option rows
// are painted by the CheckList painter FUN_0060f030 (decompiled 2026-09-13, user AB shots at 4K/1600/1920):
//   rowTop = list y + gap/2 + i*(rowH + gap);  rowB = max(rowH [Dialog+0x68], Buffer_text_line_height)
//   box:   Sprite_draw_2 at y = rowTop + ((rowB - sprite.h) >> 1), then thunk_checkbox_scale (0x668C40)
//          zooms it x g/16 and adds (16 - g) >> 1 to y
//   label: Buffer_write_l_4 in the rect (rowTop + [window+0x970 font].tmDescent .. rowTop + rowB), which
//          centres the font's cap height: y = top + (bottom - top - Font.capH) / 2
// RowLabelY ports that arithmetic with the Map page's live fields, so only the engine's numbers place our
// label relative to our box (our box sits at canvas y 0; the row-top term cancels).
constexpr uintptr_t kPrefChkList[7] = { 0x5974, 0x649C, 0x6FC4, 0x7AEC, 0x8614, 0x913C, 0x9C64 };
constexpr int kPrefChkMapIdx = 5;        // Map Preferences page (ctor order = tab order)
constexpr int kChkListWinOfs = 0x1C;     // GraphicWin part (+0x970 label font)
constexpr int kChkListDlgOfs = 0xA34;    // Dialog part: +0x34 indent, +0x44 gap, +0x68 rowH
// engine Font (0x28 B, Font_init 0x618F40): +0 line pad (-1 = none), +0xC cell = tmHeight+tmExternalLeading,
// +0x10 cap height = tmAscent-tmInternalLeading (Buffer_text_height), +0x1C tmDescent

// MapWin (Console static @ 0x9156B0) font re-init caches
constexpr uintptr_t kVA_MapWinZoomCache = 0x00934570;  // +0x1EEC0 last-zoom for the font block
constexpr uintptr_t kVA_MapFontCache0   = 0x009345A0;  // +0x1EEF0 style-0 (base names) size
constexpr uintptr_t kVA_MapFontCache1   = 0x009345CC;  // +0x1EF1C style-1 size
constexpr uintptr_t kVA_MapFontCache2   = 0x009345F8;  // +0x1EF48 style-2 (landmarks) size

// PrefWin fields / ids
constexpr int  kTabIdOfs    = 0xA14;      // current tab ([0x285]*4)
constexpr int  kFontSlotOfs = 0x970;      // FlatButton label font ptr
constexpr int  kForceStateOfs = 0xAB8;    // FlatButton forced draw state: 0..2 override
                                          // hover/pressed resolve entirely (content_draw
                                          // reads it FIRST); out-of-range = dynamic
constexpr int  kTabId    = 0x5F;          // our tab button id (0..6,7..0x4F,0x50..0x5E used)
constexpr int  kSliderId = 0x60;
constexpr int  kLabelId  = 0x61;
constexpr int  kDefaultBig = 1;           // the big (2x) F4 ring; ini-only since 2026-10-11 ([UIMod] BigF4Indicators=0 turns it off --
                                          // the Preferences row made way for "Constrain Mouse to Window"); the cave flag ships 1 too
// The option rows are drawn like the stock option lists' rows (Map Preferences tab, measured on the user's 4K shot
// 2026-09-12): the CheckList box sprite (16 native) at the list's left inset -- the same x as the slider-area
// frame -- 5 native under the first tab button's top, the label 23 native to the right in the list text colour
// (palette 224) and the regular 14-pt font; no button face.
// 0x62: RETIRED 2026-10-11 (the "Large F4 Base Indicators" row -- the setting is ini-only now); never reuse
constexpr int  kAiChkId    = 0x63;        // the "AI Cannot See Cloaked Units" row (aivis.cpp)
constexpr int  kCargoChkId = 0x64;        // the "Cloaked Transport Hides Its Cargo" row (aivis.cpp); 
constexpr int  kMarkChkId = 0x65;         // the "Show Alert Icon on Detected Cloaked Units" row (aivis.cpp)
constexpr int  kModeChkId0 = 0x66;       // the display-mode row: Fullscreen 0x66 / Borderless 0x67 / Windowed 0x68 (vidmode.cpp)
constexpr int  kHoldLabelId  = 0x69;     // the "Drag Hold Time" row (dragdelay.cpp): its inert label ...
constexpr int  kHoldSliderId = 0x6A;     // ... and its slider
// 0x6B: RETIRED 2026-10-07 ("Shift+Click Instant Move" -- the setting is gone, the engine's Shift branch is always off); never reuse
constexpr int  kUpdChkId   = 0x6C;       // the "Check for Updates at Startup" row (update.cpp) ...
constexpr int  kSubBtnId   = 0x6D;       // ... and its "Reset Skipped Updates" button on the same line
constexpr int  kScanChkId  = 0x6E;       // the "Add Scanlines" row (replacement portraits, portrait.cpp) ...
// 0x6F RETIRED ("Brighten Scanlines", removed 2026-10-30: the brightened scanlines are simply always on; never reuse)
constexpr int  kAirdropChkId = 0x79;     // "Air Drops Divert Around Unseen Defenders" (aivis.cpp), top-level after the cloak rows
                                         // (0x78 is kClipChkId below -- the audit of 2026-10-30 caught a collision; test_airdrop_divert pins uniqueness)
constexpr int  kCustomChkId = 0x70;      // "Enable Custom Portraits": the parent of the portrait rows
constexpr int  kHdChkId    = 0x71;       // "Use Turovetsky's HD Portrait Pack" (only while the portraits-hd pack is installed)
constexpr int  kModernChkId = 0x72;      // "Modern Control Set" (modernctl.cpp): the parent ...
constexpr int  kRcMoveChkId = 0x73;      // ... and "Right-Click Drags to Move" nested under it
constexpr int  kDragCellId0 = 0x74;      // the map-drag row: "Middle-Click Drags Map" 0x74 / "Right-Click Drags Map" 0x75, one line,
                                         // exclusive, the selected cell clicked = both off (no drag scrolling); 0x76..0x79 below
constexpr int  kDragCells   = 2;
constexpr int  kDragCellValue[kDragCells] = { kMapDragMiddle, kMapDragRight };   // [UIMod] MapDragButton per cell
constexpr int  kAudioRowPitch = 0x16;    // PrefWin_build's audio rows: label/slider y0 + i*0x16 (0x48F344/0x48F60F); ours take rows 0 and 1
constexpr int  kSliderFrameRows = 2;     // our slider frame holds two rows (the audio page's holds four) ...
constexpr int  kSliderBlockDy = (4 - kSliderFrameRows) * kAudioRowPitch;   // ... and sits 44 native lower, same bottom edge
constexpr int  kSliderFrameH  = kSliderFrameRows * kAudioRowPitch + 4;     // 48 native (the audio frame: 4*22 + 4 = 92)
// camera rows (modernctl.cpp): the map stays put on a left click / when a base closes
constexpr int  kClickViewChkId = 0x76;   // "Left Click Doesn't Recenter the Map" ([UIMod] ClickKeepsView)
constexpr int  kBaseViewChkId  = 0x77;   // "Closing a Base Never Recenters Map" ([UIMod] BaseCloseKeepsView)
constexpr int  kClipChkId      = 0x78;   // "Constrain Mouse to Window" nested under the display-mode row ([UIMod] ConstrainMouse,
                                         // vidmode.cpp); dimmed and inert outside Fullscreen; next free 0x7A
constexpr uintptr_t kVA_ScrollBarVtbl = 0x00669D58;   // ScrollBar vtable (+0x30 draw = thunk_pref_sbzoom on the patched exe)
constexpr int  kSbVtblBytes = 0x170;     // its extent: 0x168 GraphicWin + 2 ScrollBar virtuals; FileDlg_vtbl starts at 0x669EC8
constexpr int  kSbValueOfs = 0xA2C;      // ScrollBar raw position; +0xA20/+0xA24 range, +0xA28 inverted flag
constexpr int  kModeCells  = 3;
constexpr int  kModeRow    = 0;          // the page's first row ...
constexpr int  kOptRow0    = 1;          // ... "Constrain Mouse to Window" nested under it (neither without PRACX's window code),
                                         // then the option rows.  15 row INDICES (0..14) fit above the two-row slider frame:
                                         // with PRACX the mode + clip rows take 0..1 and the 13 option rows (BuildWidgets' k = 0..12)
                                         // take 2..14 -- ZERO slack; the overlap log in BuildWidgets is the guard
constexpr uintptr_t kVA_WinIsVisible = 0x005F7E90;   // Win_is_visible: thiscall(ecx=Win) -> int
constexpr int  kChkSubIndent = 18;       // a sub-option row sits one box width (native) to the right of its parent
constexpr int  kChkRowPitch = 20;         // row-to-row pitch (native): the stock CheckList rowH, logged live as 50 px at g=40 (chkrow line in uimod.log)
constexpr int  kChkRowDy   = 3;           // box top = TabY0 + 3 (native): the stock box is 18 native tall with the same
                                          // bottom as ours (17), so ours sits one native higher; the text keeps its place (+1)
constexpr int  kChkTextDy  = 3;           // label cell y inside the row (native): 1 measured ~2 native high vs the stock rows at 4K/1600/1920 (user AB shots 2026-09-13)
constexpr int  kChkRowH    = 16;          // row/box height (native)
constexpr int  kChkTextDx  = 23;          // label x = box x + 23 (native)
constexpr int  kChkTextColor = 0xE0;      // (120,164,212), the stock rows' text
constexpr int  kSlotContentDraw = 0x30;   // FlatButton vtbl+0x30 content_draw(self): the face painter we replace
// The stock option rows are drawn by the pages' CheckList widgets in the DEF-DIALOG font the baked
// thunk_tutwin_fonts installs at g>16: find_font(g, variant) -- scale_px(16, g) == g exactly, and the
// rows use the BOLD variant (measured on the user's shots: 'S' 12x16 at 1920 = Arial Narrow 22 bold,
// 13x19 at 1600 = 25 bold, each one px of anti-alias fringe wider than GDI's own render).  At g<=16 the
// engine's native default f1 (g_text_font_v1 @0x94575C) is what the rows use.  (Reading page 1's Dialog
// font triple matched at 1600 but not at 1920 -- those pointers depend on which popups ran.)
constexpr uintptr_t kVA_TextFontV1 = 0x0094575C;  // native def-dialog bold font (Dialog_set_def_dialog_font f1 seed @0x5884C8)
// find_font snaps to the pool table {40,36,32,24,22,20,18,16,14,12,10,8}: at g=25 (1600x1200) it hands out 24 while
// the stock rows measure 25 px ('S' 13x19 with fringe = Arial Narrow 25 bold; our 24 gave 17-px caps vs their 19,
// user shots 001625/001626).  So the row owns a Font (0x28 B, zeroed = safe for Font_init like the rw bake's
// cave scratch fonts) Font_init'd at EXACTLY g px, bold, "Arial Narrow" (the popup pool's face above 12 px).
constexpr uintptr_t kVA_FontInit      = 0x00618F40;  // Font_init(name, size, style) thiscall(ecx=Font) RET 0xC
constexpr uintptr_t kVA_FontNameNarrow = 0x00691B30; // const char** -> "Arial Narrow"
// v17 (2026-09-13, user shots 002458/002500 @1600 + 002525/002526 @1920, glyph-measured): the stock rows are
// NOT a plain g-px font -- at g=25 their ascender is 19 px to our 18, at g=22 their x-height/descender 12/5 to
// our 11/4.  They draw with the popups' scaled BODY font: thunk_build_scaled_fonts' scratch0_font (pcave2+0x810,
// = g_pf0/g_pf1), Arial Narrow bold at the first nominal size >= g whose GDI cell [Font+0xC] reaches (20*g)>>4
// (26 @g25, 23 @g22, 42 @g40).  We draw with that very Font when the cave has built it (identity with the rows),
// and port its calibration law into g_rowFont otherwise.
constexpr uintptr_t kVA_Scratch0Font  = 0x00A0C810;  // pcave2+0x810 scratch0_font (engine Font, 0x28 B; +8 HFONT, +0xC cell)
constexpr int       kPfCellNative     = 20;          // the body font's native cell height: target cell = (20*g)>>4
constexpr int  kVtblBytes  = 0x180;       // FlatButton vtable extent: 0x168 (GraphicWin) + 6 FlatButton virtuals (+0x168..+0x17C); the next class vtable starts at +0x180 (dtor, 0x5ED9D0, ..., 0x5D5540 signature). 0x168 crashed the save load.
constexpr int  kTabRowY  = 0x84;          // y0+0x84: the blank row under Map Preferences
constexpr int  kDefaultPct = 100;         // mod default = full scale

// ---- helpers ----------------------------------------------------------------------

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (va - kImageBase);
}
template <typename T> T Rd(uintptr_t va) { return *reinterpret_cast<T*>(At(va)); }
template <typename T> void Wr(uintptr_t va, T v) { *reinterpret_cast<T*>(At(va)) = v; }

void Dbg(const char* s) { UimodLog(s); }

void IniPath(char* out, size_t n)
{
    GetModuleFileNameA(nullptr, out, static_cast<DWORD>(n));
    char* slash = strrchr(out, '\\');
    if (slash) slash[1] = '\0';
    lstrcatA(out, "Alpha Centauri.ini");
}

int LoadPct()
{
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    int pct = static_cast<int>(GetPrivateProfileIntA("UIMod", "MapLabelFontScale",
                                                     kDefaultPct, ini));
    if (pct < 0) pct = 0;
    if (pct > 100) pct = 100;
    return pct;
}

void SavePct(int pct)
{
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    char val[16];
    _snprintf_s(val, sizeof val, _TRUNCATE, "%d", pct);
    WritePrivateProfileStringA("UIMod", "MapLabelFontScale", val, ini);
}

// ini-only (no row, nothing writes it back): [UIMod] BigF4Indicators, default on
int LoadBig()
{
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    return GetPrivateProfileIntA("UIMod", "BigF4Indicators", kDefaultBig, ini) != 0 ? 1 : 0;
}

// The flag lives in the exe cave (g_big_f4); t_rwk_blink reads it at every ring stamp.
void ApplyBig(int big) { Wr<int>(kVA_BigF4, big ? 1 : 0); }

// Write pct into the cave and invalidate MapWin's font-block caches so the next
// MapWin_calculate_dimensions re-runs the three Font_inits through thunk_map_font.
void ApplyPct(int pct)
{
    Wr<int>(kVA_MapFontPct, pct);
    Wr<int>(kVA_MapWinZoomCache, 0x7FFFFFFF);
    Wr<int>(kVA_MapFontCache0, 0);
    Wr<int>(kVA_MapFontCache1, 0);
    Wr<int>(kVA_MapFontCache2, 0);
}

// ---- engine call shims (thiscall via the fastcall-dummy-edx idiom) ------------------

using FCtor      = void(__fastcall*)(void* self, void* edx);
using FBtnInit   = int(__fastcall*)(void* self, void* edx, const char* text, int id,
                                    int x, int y, int w, int h, void* parent, int a9);
using FSbInit    = int(__fastcall*)(void* self, void* edx, int x, int y, int w,
                                    void* parent, int id);
using FSbRange   = void(__fastcall*)(void* self, void* edx, int mn, int mx);
using FSbSet     = void(__fastcall*)(void* self, void* edx, int pos);
using FGroupAdd  = void(__fastcall*)(void* group, void* edx, void* btn);
using FRefresh   = void(__fastcall*)(void* self, void* edx);
using FOnKey     = int(__fastcall*)(void* self, void* edx, int a2, int key);
using FOnCommand = void(__fastcall*)(void* self, void* edx, int id);
using FOnSlider  = void(__fastcall*)(void* self, void* edx, int id, int value);
using FBoxSprite = void(__fastcall*)(void* buf, void* edx, int* rect, void* params);
using FSpriteDraw2 = void(__fastcall*)(void* spr, void* edx, void* dest, int key, int x, int y,
                                       int num, int den);
using FBufSetFont  = void(__fastcall*)(void* buf, void* edx, void* f0, void* f1, void* f2, void* f3);
using FBufSetColor = void(__fastcall*)(void* buf, void* edx, int color, int a3, int a4, int a5);
using FBufWriteL3  = void(__fastcall*)(void* buf, void* edx, const char* s, int x, int y, int len);
using FFontWidth   = int(__fastcall*)(void* font, void* edx, const char* s);
using FFontInit    = int(__fastcall*)(void* font, void* edx, const char* name, int size, int style);
using FGWinClear   = void(__fastcall*)(void* self, void* edx, int color);
using FBufSetPal   = void(__fastcall*)(void* buf, void* edx, void* pal);

// vtable slot indexes (byte offsets)
constexpr int kSlotRefresh = 0x30;
constexpr int kSlotOnKey   = 0x64;
constexpr int kSlotCommand = 0xB0;
constexpr int kSlotSlider  = 0xC4;
constexpr int kSlotScrolled = 0xC0;

FRefresh   g_origRefresh = nullptr;
FOnKey     g_origOnKey = nullptr;
FOnCommand g_origCommand = nullptr;
FOnSlider  g_origSlider = nullptr;
FOnSlider  g_origScrolled = nullptr;

// ---- our widget storage (engine-class instances in DLL .data) ----------------------
// Sizes from the PrefWin object strides: FlatButton 0xB4C, ScrollBar 0x214C; padded.

struct alignas(16) Widgets {
    BYTE tab[0xC00];
    BYTE label[0xC00];
    BYTE clipcheck[0xC00];   // "Constrain Mouse to Window", nested under the display-mode row: a FlatButton with a PRIVATE vtable
                             // (face painter = ours); built only with the mode row
    BYTE aicheck[0xC00];     // the "AI Cannot See Cloaked Units" row: same widget, same private vtable
    BYTE cargocheck[0xC00];  // the "Cloaked Transport Hides Its Cargo" row: ditto
    BYTE markcheck[0xC00];   // the "Show Alert Icon on Detected Cloaked Units" row: ditto
    BYTE moderncheck[0xC00]; // the "Modern Control Set" row (modernctl.cpp): ditto
    BYTE rcmovecheck[0xC00]; // "Right-Click Drags to Move", nested under it: ditto
    BYTE dragcell[kDragCells][0xC00];   // "Middle-Click Drags Map" / "Right-Click Drags Map", side by side on one line: ditto
    BYTE clickview[0xC00];   // "Left Click Doesn't Recenter the Map" (modernctl.cpp camera options): ditto
    BYTE baseview[0xC00];    // "Closing a Base Never Recenters Map": ditto
    BYTE updcheck[0xC00];    // the "Check for Updates at Startup" row: ditto
    BYTE subbtn[0xC00];      // "Reset Skipped Updates": a STOCK FlatButton (engine face) right of that row's label
    BYTE customcheck[0xC00]; // "Enable Custom Portraits": same widget, same private vtable as the checkbox rows
    BYTE hdcheck[0xC00];     // "Use Turovetsky's HD Portrait Pack", nested under it (built only with the pack installed)
    BYTE scancheck[0xC00];   // the "Add Scanlines" row, nested under "Enable Custom Portraits": ditto
    BYTE airdropcheck[0xC00]; // the "Air Drops Divert Around Unseen Defenders" row (top-level, after the cloak rows): ditto
    BYTE modecheck[kModeCells][0xC00];   // Fullscreen / Borderless / Windowed, side by side on one line: ditto
    BYTE slider[0x2200];
    BYTE holdlabel[0xC00];   // "Drag Hold Time": inert FlatButton label, the audio page's row 1
    BYTE holdslider[0x2200]; // its ScrollBar, with a PRIVATE vtable copy (see HoldSliderDraw)
};
Widgets g_w;                 // zero-initialized (.bss)
bool g_built = false;
int  g_pct = kDefaultPct;
int  g_big = kDefaultBig;
void* g_chkVtbl[kVtblBytes / 4];      // copy of the FlatButton vtable with +0x30 -> CheckContentDraw
alignas(16) BYTE g_rowFont[0x40];      // our own row font (engine Font object, 0x28 B; zero = uninitialised) -- fallback only
void* g_rowFontPtr = nullptr;          // the Font the row draws with at g>16: scratch0_font when built, else g_rowFont
bool  Pcave2Present();
bool  CkLawPresent();
const char kAiChkText[] = "AI Cannot See Cloaked Units Until Actually Discovered";   // user wording 2026-09-19
const char kCargoChkText[] = "Cloaked Transport Hides Its Cargo";
const char kMarkChkText[] = "Show Alert Icon on Detected Cloaked Units";
const char kModernChkText[] = "Modern Control Set";             // [UIMod] ModernControls (modernctl.cpp)
const char kRcMoveChkText[] = "Right-Click Drags to Move";      // [UIMod] RightClickDragsToMove, nested under it
const char* const kDragCellText[kDragCells] = { "Middle-Click Drags Map", "Right-Click Drags Map" };   // [UIMod] MapDragButton 1 / 2
bool g_modernRow = false;                                       // the Modern Control Set rows exist (modernctl's byte checks passed)
bool g_dragRow = false;                                         // the map-drag cells exist (PRACX's drag sites bound)
const char kClickViewText[] = "Left Click Doesn't Recenter the Map";        // [UIMod] ClickKeepsView
const char kBaseViewText[]  = "Closing a Base Never Recenters Map";         // [UIMod] BaseCloseKeepsView
bool g_cameraRow = false;                                       // the two camera rows exist (modernctl's camera sites bound)
const char kUpdChkText[] = "Check for Updates at Startup";      // [UIMod] CheckForUpdates; takes effect at the next launch
const char kSubBtnText[] = "Reset Skipped Updates";          // clears every "Don't ask me again" (after a confirmation)
const char kCustomChkText[] = "Enable Custom Portraits";        // user wording 2026-11-07, was "Enable User Portraits" ([UIMod] CustomPortraits)
const char kHdChkText[] = "Use Turovetsky's HD Portrait Pack";   // user wording 2026-10-03, pack renamed 2026-11-06 ([UIMod] HdPortraits)
bool g_hdRow = false;                                           // the HD row exists (the pack is installed)
const char kScanChkText[] = "Add Scanlines";                    // user wording 2026-09-30 ([UIMod] PortraitScanlines)
const char kAirdropChkText[] = "Air Drops Divert Around Unseen Defenders";   // [UIMod] AirdropDiversion (aivis.cpp)
const char* const kModeText[kModeCells] = { "Fullscreen", "Borderless", "Windowed" };   // index = VidMode
bool g_modeRow = false;                // the display-mode cells exist (PRACX's window code is bound)
const char kClipChkText[] = "Constrain Mouse to Window";   // [UIMod] ConstrainMouse (vidmode.cpp): Fullscreen holds the pointer
const char kHoldText[] = "Drag Hold Time";   // the value shows in a tooltip bubble while the slider is held (SliderBubbleUpdate)
bool  g_holdRow = false;               // the drag-hold row exists (dragdelay's site byte check passed)
void* g_labelFont = nullptr;           // the scaled label font set at build (g>16), for the drag-hold label
// Both sliders share a PRIVATE copy of the ScrollBar vtable: +0x30 draw (registry-slot bracket for the hold
// slider), +0x50 press / +0x54 release / +0xB0 chevron (the value bubble).
void* g_sbVtbl[kSbVtblBytes / 4];
using FSbDraw = void(__fastcall*)(void* self, void* edx);
using FSbXY   = void(__fastcall*)(void* self, void* edx, int a, int b);   // RET 8
using FSbOne  = void(__fastcall*)(void* self, void* edx, int a);          // RET 4
FSbDraw g_origSbDraw = nullptr;
FSbXY   g_origSbPress = nullptr;
FSbXY   g_origSbRelease = nullptr;
FSbOne  g_origSbChevron = nullptr;
constexpr int kSbSlotPress = 0x50, kSbSlotRelease = 0x54, kSbSlotChevron = 0xB0;

// engine tooltip ("bubble") API -- every mouseover tooltip in the game goes through these
constexpr uintptr_t kVA_SetBubble    = 0x005F83D0;  // Win_set_bubble_text: thiscall(owner)(text, RECT* screen anchor) RET 8
constexpr uintptr_t kVA_ClearBubble  = 0x005F8500;  // Win_clear_bubble_text: cdecl()
constexpr uintptr_t kVA_BubbleOwner  = 0x009B7A4C;  // g_bubble_owner
constexpr uintptr_t kVA_BubbleText   = 0x009B7A50;  // g_bubble_text
constexpr uintptr_t kVA_LocalToScreen = 0x005ED240; // GraphicWin_local_to_screen: thiscall(int* x, int* y) RET 8
constexpr uintptr_t kVA_ThumbRect    = 0x00606C50;  // ScrollBar_thumb_rect: thiscall(RECT* out) RET 4
constexpr uintptr_t kVA_PressedWinL  = 0x009B7ACC;  // g_pressed_win_l
constexpr int kSbArrowUp = 0xAAC, kSbArrowDown = 0x15F8;   // the two arrow FlatButtons inside a ScrollBar
char  g_bubbleBuf[16];                 // the bubble text (the engine keeps the POINTER)
void* g_bubbleSb = nullptr;            // the slider whose value bubble is showing, or null

// ---- the INERT slider (the engine has no disabled state for a ScrollBar, and the page invents no look for one:
// user 2026-10-07).  Inert: our private ScrollBar vtable early-outs the press (+0x50), the arrows' own repeat
// timer (+0xA4) and the arrow release (+0xB0), and the mouse-move override (+0x44, the thumb-drag handler) shows
// the tooltip "Requires drag to move" instead of dragging.  NEVER the Win input gate (+0x98 & 0x200000): it
// blocks mouse-move too, so no tooltip could show.  The arrows carry the same tooltip through the engine's own
// per-button bubble (BaseButton_set_bubble_text, shown after its 1000 ms hover timer).
constexpr uintptr_t kVA_SetBtnBubble = 0x00607550;  // BaseButton_set_bubble_text: thiscall(text) RET 4; strdup's, nullptr clears
constexpr uintptr_t kVA_GamePalette  = 0x0094C590;  // PALETTEENTRY[256] g_main_palette (kVA_MainPalette above is the Palette* SLOT)
constexpr int kSbSlotMove = 0x44, kSbSlotLeave = 0x48, kSbSlotRepeat = 0xA4;
constexpr int kGreyMid = 248;                        // the static Windows mid grey (128,128,128): in every game palette
FSbXY g_origSbMove = nullptr;
FSbXY g_origSbLeave = nullptr;
FSbOne g_origSbRepeat = nullptr;
char  g_tipBuf[] = "Requires drag to move";          // the tooltip text (the engine keeps the POINTER)
void* g_tipSb = nullptr;                             // the slider whose tooltip is showing, or null
bool  g_holdDisabled = false;
int   g_greyText = kGreyMid;                         // dimmed row text for a child whose parent is off (palette-matched at build)
int   g_holdApplied = -1;                            // the arrows' tooltip state: 1 enabled (none), 0 disabled (set), -1 unknown

void* WinVtbl(void* w) { return *reinterpret_cast<void**>(w); }
void WinShow(void* w)
{
    auto f = reinterpret_cast<void(__fastcall*)(void*, void*, int)>(
        reinterpret_cast<void**>(WinVtbl(w))[1]);
    f(w, nullptr, 0);
}
void WinHide(void* w)
{
    auto f = reinterpret_cast<void(__fastcall*)(void*, void*)>(
        reinterpret_cast<void**>(WinVtbl(w))[2]);
    f(w, nullptr);
}
void WinRedraw(void* w)
{
    auto f = reinterpret_cast<void(__fastcall*)(void*, void*)>(
        reinterpret_cast<void**>(WinVtbl(w))[0xF8 / 4]);
    f(w, nullptr);
}

// ---- vtable wrappers ---------------------------------------------------------------

bool OurTabActive() { return Rd<int>(kVA_PrefWin + kTabIdOfs) == kTabId; }

// The drag-hold slider's draw (ScrollBar vtbl+0x30 in its PRIVATE vtable copy). The baked zoom machinery
// knows ONE DLL slider: thunk_pref_sbzoom arms the thumb/arrow zoom for ecx == [g_dll_pref_slider], and
// thunk_pref_gwinit scales the arrow/thumb children whose parent == [g_dll_pref_slider]. So the slot holds
// the font slider, and becomes this slider only around its own draws (here) and its construction
// (BuildWidgets) -- no exe change. Every draw reaches this slot through the vtable (GraphicWin_redraw
// vtbl+0xF8, set_pos, the engine's hover/drag redraws), exactly as the font slider's reach sbzoom.
void __fastcall HoldSliderDraw(void* self, void* edx)
{
    if (self != static_cast<void*>(g_w.holdslider)) { g_origSbDraw(self, edx); return; }   // the font slider owns the slot
    const DWORD prev = Rd<DWORD>(kVA_DllPrefSlider);
    Wr<DWORD>(kVA_DllPrefSlider, reinterpret_cast<DWORD>(self));
    g_origSbDraw(self, edx);
    Wr<DWORD>(kVA_DllPrefSlider, prev);
}

// The drag-hold slider's logical position (the value the engine notifies with: +0xA28 inverts the raw one).
int HoldSliderPos()
{
    const BYTE* sb = g_w.holdslider;
    const int raw = *reinterpret_cast<const int*>(sb + kSbValueOfs);
    if (*reinterpret_cast<const int*>(sb + 0xA28) == 0) return raw;
    return *reinterpret_cast<const int*>(sb + 0xA24) - raw + *reinterpret_cast<const int*>(sb + 0xA20);
}

// Commit (OK / Enter): pick up a position the notifications missed, then persist.
void HoldCommit()
{
    if (!g_holdRow) return;
    const int pos = HoldSliderPos();
    if (pos != DragDelayPosFromMs(DragDelayGet())) DragDelaySet(DragDelayMsFromPos(pos));
    DragDelaySave();
}

// ---- value bubble: the game's own mouseover tooltip, shown while one of our sliders is HELD ----------
// Win_set_bubble_text (the call every engine tooltip makes) sizes the box from g_bubble_font (12 px, scaled
// 12g/16 by the patcher's thunk_bubble_font; border floor(g/16) by thunk_bubble_inset_fill), places it
// centred over the anchor with its bottom on the anchor top (below it if that leaves the screen), clamps x
// to [0, ScreenWidth], erases the previous box (Win_update_screen over the old rect) and paints the new one
// (overlay_compositor, per frame). Win_clear_bubble_text erases it. So there is no geometry of ours beyond
// the anchor: the thumb's rect (ScrollBar_thumb_rect, window-local device px) moved to screen space the way
// the engine anchors a button's bubble (GraphicWin_local_to_screen of the window origin, 0x607B91).

// A slider is held while the left button is down on it (thumb drag, track press) or on one of its arrows.
bool SliderHeld(const void* sb)
{
    const BYTE* p = Rd<const BYTE*>(kVA_PressedWinL);
    const BYTE* b = static_cast<const BYTE*>(sb);
    return p && (p == b || p == b + kSbArrowUp || p == b + kSbArrowDown);
}

void SliderBubbleClear()
{
    if (!g_bubbleSb) return;
    if (Rd<void*>(kVA_BubbleOwner) == g_bubbleSb && Rd<const char*>(kVA_BubbleText) == g_bubbleBuf)
        reinterpret_cast<void(__cdecl*)()>(At(kVA_ClearBubble))();   // only our own bubble, never someone else's
    g_bubbleSb = nullptr;
}

void SliderBubbleShow(void* sb)
{
    const bool hold = sb == static_cast<void*>(g_w.holdslider);
    if (hold) _snprintf_s(g_bubbleBuf, sizeof g_bubbleBuf, _TRUNCATE, "%d ms", DragDelayGet());
    else      _snprintf_s(g_bubbleBuf, sizeof g_bubbleBuf, _TRUNCATE, "%d%%", g_pct);

    const BYTE* w = static_cast<const BYTE*>(sb);
    const int ww = *reinterpret_cast<const int*>(w + 0x144) - *reinterpret_cast<const int*>(w + 0x13C);
    const int wh = *reinterpret_cast<const int*>(w + 0x148) - *reinterpret_cast<const int*>(w + 0x140);
    int sx = 0, sy = 0;
    reinterpret_cast<void(__fastcall*)(void*, void*, int*, int*)>(At(kVA_LocalToScreen))(sb, nullptr, &sx, &sy);
    RECT th = {};
    reinterpret_cast<void(__fastcall*)(void*, void*, RECT*)>(At(kVA_ThumbRect))(sb, nullptr, &th);
    const bool thumbOk = th.left >= 0 && th.right > th.left && th.right <= ww;   // else anchor on the whole bar
    RECT a;
    a.left   = sx + (thumbOk ? th.left : 0);
    a.right  = sx + (thumbOk ? th.right : ww);
    a.top    = sy;
    a.bottom = sy + wh;
    static char lastText[sizeof g_bubbleBuf];
    static RECT lastA;
    if (g_bubbleSb == sb && Rd<void*>(kVA_BubbleOwner) == sb && Rd<const char*>(kVA_BubbleText) == g_bubbleBuf &&
        memcmp(&lastA, &a, sizeof a) == 0 && strcmp(lastText, g_bubbleBuf) == 0)
        return;                                         // unchanged: no erase/repaint per mouse move
    lastA = a;
    memcpy(lastText, g_bubbleBuf, sizeof lastText);
    static int logged = 0;
    if (logged < 4) {                                   // a few samples for the first in-game check
        ++logged;
        char msg[200];
        _snprintf_s(msg, sizeof msg, _TRUNCATE,
                    "[uimod] prefs: value bubble '%s' win %dx%d @(%d,%d) thumb (%ld,%ld,%ld,%ld) ok=%d -> anchor (%ld,%ld,%ld,%ld)\n",
                    g_bubbleBuf, ww, wh, sx, sy, th.left, th.top, th.right, th.bottom, thumbOk ? 1 : 0,
                    a.left, a.top, a.right, a.bottom);
        UimodDbg(msg);
    }
    reinterpret_cast<void(__fastcall*)(void*, void*, char*, RECT*)>(At(kVA_SetBubble))(sb, nullptr, g_bubbleBuf, &a);
    g_bubbleSb = sb;
}

// Show / move / refresh the bubble while `sb` is held, drop it otherwise. `force` = we are inside the
// press handler (the pressed-window global may not be set yet).
void SliderBubbleUpdate(void* sb, bool force = false)
{
    if (force || SliderHeld(sb)) SliderBubbleShow(sb);
    else if (g_bubbleSb == sb) SliderBubbleClear();
}

bool HoldDisabled(const void* self)      // per POINTER: the private vtable is shared with the font slider
{
    return g_holdDisabled && self == static_cast<const void*>(g_w.holdslider);
}

// The disabled slider's tooltip: the engine's own bubble, anchored on the whole bar, shown at once on
// enter / move (the engine's buttons wait 1000 ms) and dropped on leave.  Only ever clears ITS OWN bubble.
void SliderTipClear()
{
    if (!g_tipSb) return;
    if (Rd<void*>(kVA_BubbleOwner) == g_tipSb && Rd<const char*>(kVA_BubbleText) == g_tipBuf)
        reinterpret_cast<void(__cdecl*)()>(At(kVA_ClearBubble))();
    g_tipSb = nullptr;
}

void SliderTipShow(void* sb)
{
    if (g_tipSb == sb && Rd<void*>(kVA_BubbleOwner) == sb && Rd<const char*>(kVA_BubbleText) == g_tipBuf)
        return;                                         // already up: no erase/repaint per mouse move
    const BYTE* w = static_cast<const BYTE*>(sb);
    const int ww = *reinterpret_cast<const int*>(w + 0x144) - *reinterpret_cast<const int*>(w + 0x13C);
    const int wh = *reinterpret_cast<const int*>(w + 0x148) - *reinterpret_cast<const int*>(w + 0x140);
    int sx = 0, sy = 0;
    reinterpret_cast<void(__fastcall*)(void*, void*, int*, int*)>(At(kVA_LocalToScreen))(sb, nullptr, &sx, &sy);
    RECT a = { sx, sy, sx + ww, sy + wh };
    reinterpret_cast<void(__fastcall*)(void*, void*, char*, RECT*)>(At(kVA_SetBubble))(sb, nullptr, g_tipBuf, &a);
    g_tipSb = sb;
}

void __fastcall SbPress(void* self, void* edx, int x, int y)
{
    if (HoldDisabled(self)) return;      // inert: no track-zone arming, no capture (the press calls +0x44 itself)
    g_origSbPress(self, edx, x, y);
    SliderBubbleUpdate(self, true);
}

void __fastcall SbRelease(void* self, void* edx, int a, int b)
{
    g_origSbRelease(self, edx, a, b);
    SliderBubbleUpdate(self);            // the pressed-window global is already cleared -> drops the bubble
}

void __fastcall SbChevron(void* self, void* edx, int btn)
{
    if (HoldDisabled(self)) return;      // an arrow released on the inert bar: no step
    g_origSbChevron(self, edx, btn);     // arrow released: value step + parent notify
    SliderBubbleUpdate(self);
}

void __fastcall SbRepeat(void* self, void* edx, int btn)
{
    if (HoldDisabled(self)) return;      // an arrow HELD on the inert bar: its own repeat timer lands here
    g_origSbRepeat(self, edx, btn);
}

void __fastcall SbMove(void* self, void* edx, int x, int y)
{
    if (HoldDisabled(self)) {                                 // not chaining = no thumb drag
        if (!Rd<void*>(kVA_PressedWinL)) SliderTipShow(self);  // never over a drag of the font slider
        return;
    }
    g_origSbMove(self, edx, x, y);
}

void __fastcall SbLeave(void* self, void* edx, int a, int b)
{
    if (g_tipSb == self) SliderTipClear();
    g_origSbLeave(self, edx, a, b);      // the stock slot is a `ret 8` stub
}

// The palette entry nearest (r,g,b) among the game's own ramps (entries 10..245, never the transparency key),
// neutral only (channel spread <= 24) and close enough (sum of channel diffs <= 60); else `fallback`.
int PalGrey(int r, int g, int b, int fallback)
{
    const BYTE* pal = At(kVA_GamePalette);
    const int key = Rd<BYTE>(kVA_TransKey);
    int best = fallback, bestD = 61;
    for (int i = 10; i < 246; ++i) {
        if (i == key) continue;
        const int pr = pal[i * 4], pg = pal[i * 4 + 1], pb = pal[i * 4 + 2];
        const int mx = pr > pg ? (pr > pb ? pr : pb) : (pg > pb ? pg : pb);
        const int mn = pr < pg ? (pr < pb ? pr : pb) : (pg < pb ? pg : pb);
        if (mx - mn > 24) continue;
        const int d = abs(pr - r) + abs(pg - g) + abs(pb - b);
        if (d < bestD) { bestD = d; best = i; }
    }
    return best;
}

// The inert state: no look of its own (the bar draws as always); the arrows carry the tooltip while inert.
// `g_holdApplied` is reset by every build (BaseButton_init re-runs on the arrows), so the first call after a
// build always writes the arrows' bubble text again.
void SetHoldSliderEnabled(bool en)
{
    if (!g_holdRow) return;
    g_holdDisabled = !en;
    if (g_holdApplied == (en ? 1 : 0)) return;       // already in that state: never re-free an arrow's bubble text
    g_holdApplied = en ? 1 : 0;
    BYTE* sb = g_w.holdslider;
    BYTE* arrows[2] = { sb + kSbArrowUp, sb + kSbArrowDown };
    for (BYTE* btn : arrows) {
        // the engine's bubble may be showing this arrow's current text (its pointer): drop it before set frees it
        if (Rd<void*>(kVA_BubbleOwner) == btn) reinterpret_cast<void(__cdecl*)()>(At(kVA_ClearBubble))();
        reinterpret_cast<void(__fastcall*)(void*, void*, const char*)>(At(kVA_SetBtnBubble))(btn, nullptr, en ? nullptr : g_tipBuf);
    }
    if (en) SliderTipClear();
}

// Drag Hold Time matters only while some drag-to-move exists: vanilla's left drag (Modern Control Set off) or
// the right-drag option. Modern on + right-drag off = no drag at all -> the slider is inert and says why.
void UpdateHoldSliderState()
{
    const bool dis = g_holdRow && g_modernRow && ModernControlsGet() != 0 && RightClickDragGet() == 0;
    SetHoldSliderEnabled(!dis);
}

// The checkbox row's face painter (FlatButton vtbl+0x30 in the row's PRIVATE vtable copy; called by
// GraphicWin_redraw before it composites the button canvas onto the parent, and again on hover /
// press because FlatButton_on_mouse_move redraws).  Paints the row the way the stock option lists
// draw theirs: the canvas cleared to the transparency key (what the engine's own face painter does
// first, so the page shows through), the Preferences CheckList's box sprite (unchecked/checked) at
// the row's left through Sprite_draw_2 at g/16 (1:1 at g<=16), then the label in the list text
// colour and the regular 14-pt font.  The row's window rect (x,y,w,h, native) is set at build time
// and scaled by the baked GraphicWin_init gate; inside the canvas we place at 0 and dev(23).
int RowLabelY(int g, const BYTE* rowFont, uintptr_t sprVA);

void __fastcall CheckContentDraw(void* self, void* /*edx*/)
{
    const int g = Rd<int>(kVA_PopupScaleNum);
    const bool sc = g > 16;
    void* buf = static_cast<BYTE*>(self) + 0x444;
    reinterpret_cast<FBufSetPal>(At(kVA_BufSetPal))(buf, nullptr, At(kVA_MainPalette));
    reinterpret_cast<FGWinClear>(At(kVA_GWinClear))(self, nullptr, Rd<BYTE>(kVA_TransKey));

    // all the rows share this painter: state + label by widget
    const bool aiRow = self == static_cast<void*>(g_w.aicheck);
    const bool cargoRow = self == static_cast<void*>(g_w.cargocheck);
    const bool markRow = self == static_cast<void*>(g_w.markcheck);
    const bool modernRow = self == static_cast<void*>(g_w.moderncheck);
    const bool rcRow = self == static_cast<void*>(g_w.rcmovecheck);
    int dragCell = -1;                   // the map-drag cells: the STORED button, 0 = neither checked
    for (int i = 0; i < kDragCells; ++i)
        if (self == static_cast<void*>(g_w.dragcell[i])) dragCell = i;
    const bool clickViewRow = self == static_cast<void*>(g_w.clickview);
    const bool baseViewRow = self == static_cast<void*>(g_w.baseview);
    const bool updRow = self == static_cast<void*>(g_w.updcheck);
    const bool customRow = self == static_cast<void*>(g_w.customcheck);
    const bool hdRow = self == static_cast<void*>(g_w.hdcheck);
    const bool scanRow = self == static_cast<void*>(g_w.scancheck);
    const bool airdropRow = self == static_cast<void*>(g_w.airdropcheck);
    const bool clipRow = self == static_cast<void*>(g_w.clipcheck);
    int modeCell = -1;                   // the display-mode cells show the mode the game is RUNNING in, read live
    for (int i = 0; i < kModeCells; ++i)
        if (self == static_cast<void*>(g_w.modecheck[i])) modeCell = i;
    const bool on = modeCell >= 0 ? VidModeDetect() == modeCell
                  : aiRow ? AiVisGetLocal() != 0 : cargoRow ? AiVisGetCargoOne() != 0 : markRow ? AiVisGetMark() != 0
                  : modernRow ? ModernControlsGet() != 0 : rcRow ? RightClickDragGet() != 0
                  : dragCell >= 0 ? (MapDragButtonGet() == kDragCellValue[dragCell] && (dragCell != 1 || MapDragRightAllowed()))
                  : clickViewRow ? ClickKeepsViewGet() != 0 : baseViewRow ? BaseCloseKeepsViewGet() != 0
                  : updRow ? UpdateCheckGet() != 0
                  : customRow ? PortraitCustomGet() != 0 : hdRow ? PortraitHdGet() != 0
                  : scanRow ? PortraitScanGet() != 0 : airdropRow ? AiVisGetAirdrop() != 0 : VidModeClipGet() != 0;
    const char* text = modeCell >= 0 ? kModeText[modeCell]
                     : aiRow ? kAiChkText : cargoRow ? kCargoChkText : markRow ? kMarkChkText
                     : modernRow ? kModernChkText : rcRow ? kRcMoveChkText
                     : dragCell >= 0 ? kDragCellText[dragCell]
                     : clickViewRow ? kClickViewText : baseViewRow ? kBaseViewText : updRow ? kUpdChkText
                     : customRow ? kCustomChkText : hdRow ? kHdChkText
                     : scanRow ? kScanChkText : airdropRow ? kAirdropChkText : kClipChkText;
    const uintptr_t spr = on ? kVA_ChkOnSprite : kVA_ChkOffSprite;
    const int key = Rd<BYTE>(spr + 8);
    if (sc && CkLawPresent()) {
        // the box on the PARENT's stripe grid (the row canvas is keyed and composited onto it): the row's
        // parent-local top (Win +0x140 + +0x150) floor-mod P -- law scaling_laws.checkbox_list_phase, what
        // t_ck_list stages for the stock CheckList rows
        const int P = Rd<int>(kVA_StripePeriod);
        const int top = *reinterpret_cast<const int*>(static_cast<BYTE*>(self) + 0x140) +
                        *reinterpret_cast<const int*>(static_cast<BYTE*>(self) + 0x150);
        int* const ph = reinterpret_cast<int*>(At(kVA_CkPhase));
        *ph = P >= 2 ? ((top % P) + P) % P : 0;
        reinterpret_cast<FSpriteDraw2>(At(kVA_CkDraw))(At(spr), nullptr, buf, key, 0, 0, g, 16);
        *ph = 0;
    } else {
        reinterpret_cast<FSpriteDraw2>(At(kVA_SpriteDraw2))(At(spr), nullptr, buf, key, 0, 0,
                                                            sc ? g : 1, sc ? 16 : 1);
    }

    // the stock rows' font: the popups' scaled body font at g>16 (see kVA_Scratch0Font), the native def f1
    // else; a null or HFONT-less result falls back to the tab buttons' scaled 14-bold
    void* f0 = sc ? g_rowFontPtr : Rd<void*>(kVA_TextFontV1);
    if (!f0 || !*reinterpret_cast<void**>(static_cast<BYTE*>(f0) + 8))
        f0 = *reinterpret_cast<void**>(At(0x00858338 + kFontSlotOfs));
    if (void* font = f0) {
        reinterpret_cast<FBufSetFont>(At(kVA_BufSetFont))(buf, nullptr, font, nullptr, nullptr, nullptr);
        // a row that means nothing right now reads dimmed: a child under a parent that is off (the same
        // conditions WrapCommand ignores its clicks on), the right-drag cell while the right button moves units,
        // the pointer hold outside Fullscreen (the only mode that holds it)
        const bool dim = rcRow ? (ModernControlsGet() == 0 || !RightClickDragAvailable())
                       : dragCell == 1 ? !MapDragRightAllowed()
                       : (cargoRow || markRow) ? AiVisGetLocal() == 0
                       : (hdRow || scanRow) ? PortraitCustomGet() == 0
                       : clipRow ? !VidModeFullscreenRunning() : false;
        reinterpret_cast<FBufSetColor>(At(kVA_BufSetColor))(buf, nullptr, dim ? g_greyText : kChkTextColor, -1, 1, 1);
        const int tx = sc ? (kChkTextDx * g) >> 4 : kChkTextDx;
        // the stock painter's label placement relative to the box (RowLabelY, see kPrefChkList)
        const int ty = sc ? RowLabelY(g, static_cast<const BYTE*>(font), spr) : kChkTextDy;
        reinterpret_cast<FBufWriteL3>(At(kVA_BufWriteL3))(buf, nullptr, text, tx, ty,
                                                          static_cast<int>(strlen(text)));
    }
}

// The label's y inside our row canvas (box at y 0), at g>16: the CheckList painter's own arithmetic
// (Frida-traced 2026-09-13, hook_chkrow_observer.js: the stock rows never call Buffer_write_l_4 -- their
// label goes through Buffer_wrap_2, whose FIRST LINE starts at the label rect's top, no cap-height centring)
// (see kPrefChkList) evaluated with the Map page's live Dialog fields, the CheckList window's label
// font (its tmDescent seeds the label rect top) and the row font's cap height / line height.
// Falls back to the former fitted law when a field is implausible.  Logs its inputs once per tuple.
int RowLabelY(int g, const BYTE* rowFont, uintptr_t sprVA)
{
    const int oldLaw = ((kChkTextDy * g) >> 4) + ((g + 15) >> 5);
    const BYTE* cl = At(kVA_PrefWin + kPrefChkList[kPrefChkMapIdx]);
    const int rowH   = *reinterpret_cast<const int*>(cl + kChkListDlgOfs + 0x68);
    const int gap    = *reinterpret_cast<const int*>(cl + kChkListDlgOfs + 0x44);
    const int indent = *reinterpret_cast<const int*>(cl + kChkListDlgOfs + 0x34);
    const BYTE* wfont = *reinterpret_cast<BYTE* const*>(cl + kChkListWinOfs + kFontSlotOfs);
    const int descW = (wfont && *reinterpret_cast<const void* const*>(wfont + 8))
                          ? *reinterpret_cast<const int*>(wfont + 0x1C) : -1;
    const int pad  = *reinterpret_cast<const int*>(rowFont + 0x0);
    const int cell = *reinterpret_cast<const int*>(rowFont + 0xC);
    const int capH = *reinterpret_cast<const int*>(rowFont + 0x10);
    const int lineH = pad >= 0 ? capH + pad : cell;             // Buffer_text_line_height 0x5DCAB0
    const int sprH = Rd<int>(sprVA + 0x1C);
    const bool sane = rowH > 0 && rowH < 256 && descW >= 0 && descW < 64 && capH > 0 && capH < 256 &&
                      cell >= capH && sprH > 0 && sprH < 64;
    int ty = oldLaw;
    int rowB = 0, boxDy = 0, textDy = 0;
    if (sane) {
        rowB = rowH <= lineH ? lineH : rowH;                     // painter: local_20 = max(rowH, lineH*1)
        boxDy = ((rowB - sprH) >> 1) + ((16 - g) >> 1);          // sprite y (sar) + thunk_checkbox_scale
        textDy = descW;                                          // Buffer_wrap_2: line 1 at rect.top = rowTop + tmDescent
        ty = textDy - boxDy;
    }
    static int lastKey = -1;
    const int key = (rowH * 131 + gap) * 131 + descW * 7 + capH * 3 + g;
    if (key != lastKey) {
        lastKey = key;
        char msg[256];
        _snprintf_s(msg, sizeof msg, _TRUNCATE,
                    "uimod: chkrow g=%d rowH=%d gap=%d indent=%d descW=%d pad=%d cell=%d capH=%d sprH=%d "
                    "-> rowB=%d boxDy=%d textDy=%d ty=%d (fitted law %d, sane=%d)\n",
                    g, rowH, gap, indent, descW, pad, cell, capH, sprH, rowB, boxDy, textDy, ty, oldLaw,
                    sane ? 1 : 0);
        UimodDbg(msg);
    }
    return ty;
}

// vtbl+0x30 on_redraw: chain, then show/hide our row by tab and draw its frame.
void __fastcall WrapRefresh(void* self, void* edx)
{
    g_origRefresh(self, edx);
    if (!g_built) return;

    // keep our button label fonts in sync with the stock buttons and ALWAYS re-render
    // the tab: find_font returns a pointer into a static font table, so the pointer
    // compares equal across shows while the font's CONTENT gets re-initialized under
    // it -- a pointer change-detect never fires and the tab kept its pre-init render
    // (the "correct only after hovering" bug, twice). One button re-render per PrefWin
    // refresh is the same cost class as the engine's own 14 widget redraws.
    if (void* f = *reinterpret_cast<void**>(At(0x00858338 + kFontSlotOfs))) {
        *reinterpret_cast<void**>(g_w.tab + kFontSlotOfs) = f;
        *reinterpret_cast<void**>(g_w.label + kFontSlotOfs) = f;
        *reinterpret_cast<void**>(g_w.subbtn + kFontSlotOfs) = f;
        if (g_holdRow) *reinterpret_cast<void**>(g_w.holdlabel + kFontSlotOfs) = f;
    }
    WinRedraw(g_w.tab);

    if (OurTabActive()) {
        WinShow(g_w.label);
        if (g_modeRow) WinShow(g_w.clipcheck);
        WinShow(g_w.aicheck);
        WinShow(g_w.cargocheck);
        WinShow(g_w.markcheck);
        if (g_modernRow) { WinShow(g_w.moderncheck); WinShow(g_w.rcmovecheck); }
        if (g_dragRow) for (auto& c : g_w.dragcell) WinShow(c);
        if (g_cameraRow) { WinShow(g_w.clickview); WinShow(g_w.baseview); }
        WinShow(g_w.updcheck);
        WinShow(g_w.subbtn);
        WinShow(g_w.customcheck);
        if (g_hdRow) WinShow(g_w.hdcheck);
        WinShow(g_w.scancheck);
        WinShow(g_w.airdropcheck);
        if (g_modeRow) for (auto& c : g_w.modecheck) WinShow(c);
        WinShow(g_w.slider);
        if (g_holdRow) { WinShow(g_w.holdlabel); WinShow(g_w.holdslider); }
        // slider-area frame, same rect family as the audio page's (drawn when tab==4):
        // NATIVE rect; thunk_pref_boxframe scales x g/16 and draws thick strokes.
        // Our frame holds TWO rows, not the audio page's four: it sits kSliderBlockDy lower with the same bottom
        // edge, which hands the option list two more rows (user 2026-10-07: no room wasted on empty rows).
        int rect[4];
        rect[0] = Rd<int>(kVA_FrameX);
        rect[1] = Rd<int>(kVA_FrameY) - Rd<int>(kVA_BotShift) + kSliderBlockDy;
        rect[2] = rect[0] + Rd<int>(kVA_FrameW);
        rect[3] = rect[1] + kSliderFrameH;
        auto box = reinterpret_cast<FBoxSprite>(At(kVA_PrefBoxFrame));
        box(At(kVA_PrefWin + 0x444), nullptr, rect, At(kVA_FrameArt));
        WinRedraw(g_w.label);
        if (g_modeRow) WinRedraw(g_w.clipcheck);
        WinRedraw(g_w.aicheck);
        WinRedraw(g_w.cargocheck);
        WinRedraw(g_w.markcheck);
        if (g_modernRow) { WinRedraw(g_w.moderncheck); WinRedraw(g_w.rcmovecheck); }
        if (g_dragRow) for (auto& c : g_w.dragcell) WinRedraw(c);
        if (g_cameraRow) { WinRedraw(g_w.clickview); WinRedraw(g_w.baseview); }
        WinRedraw(g_w.updcheck);
        WinRedraw(g_w.subbtn);
        WinRedraw(g_w.customcheck);
        if (g_hdRow) WinRedraw(g_w.hdcheck);
        WinRedraw(g_w.scancheck);
        WinRedraw(g_w.airdropcheck);
        if (g_modeRow) for (auto& c : g_w.modecheck) WinRedraw(c);   // re-detects: Alt+Enter may have changed the mode
        WinRedraw(g_w.slider);
        if (g_holdRow) { WinRedraw(g_w.holdlabel); WinRedraw(g_w.holdslider); }
    } else {
        WinHide(g_w.label);
        if (g_modeRow) WinHide(g_w.clipcheck);
        WinHide(g_w.aicheck);
        WinHide(g_w.cargocheck);
        WinHide(g_w.markcheck);
        if (g_modernRow) { WinHide(g_w.moderncheck); WinHide(g_w.rcmovecheck); }
        if (g_dragRow) for (auto& c : g_w.dragcell) WinHide(c);
        if (g_cameraRow) { WinHide(g_w.clickview); WinHide(g_w.baseview); }
        WinHide(g_w.updcheck);
        WinHide(g_w.subbtn);
        WinHide(g_w.customcheck);
        if (g_hdRow) WinHide(g_w.hdcheck);   // an optional row: never touch it unbuilt (zeroed vtable = AV)
        WinHide(g_w.scancheck);
        WinHide(g_w.airdropcheck);
        if (g_modeRow) for (auto& c : g_w.modecheck) WinHide(c);
        WinHide(g_w.slider);
        if (g_holdRow) { WinHide(g_w.holdlabel); WinHide(g_w.holdslider); }
        SliderBubbleClear();
        SliderTipClear();
    }
}

// OK and Enter persist the same list (one copy, so the two cannot drift).
void CommitAll()
{
    SavePct(g_pct);
    AiVisSaveLocal();
    AiVisSaveCargoOne();
    AiVisSaveMark();
    if (g_modernRow) { ModernControlsSave(); RightClickDragSave(); }
    if (g_dragRow) MapDragButtonSave();
    if (g_cameraRow) { ClickKeepsViewSave(); BaseCloseKeepsViewSave(); }
    UpdateCheckSave();
    PortraitCustomSave();
    PortraitHdSave();
    PortraitScanSave();
    AiVisSaveAirdrop();
    if (g_modeRow) { VidModeSave(VidModeDetect()); VidModeClipSave(); }   // the mode the game is running in, however it got there
    HoldCommit();
}

// vtbl+0xB0 command: persist on OK, reset on Restore Defaults, chain everything.
void __fastcall WrapCommand(void* self, void* edx, int id)
{
    if (g_built) {
        if (id == kLabelId || id == kHoldLabelId) return;   // the "Base Font Size" / "Drag Hold Time" labels are inert
        if (g_modeRow && id == kClipChkId) {   // live (SyncClip); persisted on OK / Enter; inert outside Fullscreen
            if (!VidModeFullscreenRunning()) return;
            VidModeClipSet(VidModeClipGet() ? 0 : 1);
            WinRedraw(g_w.clipcheck);
            return;
        }
        if (id == kAiChkId) {             // live-apply; persisted on OK / Enter like the other settings
            // the two nested rows only mean something under this one: they follow it off AND on
            const int on = AiVisGetLocal() ? 0 : 1;
            AiVisSetLocal(on);
            AiVisSetCargoOne(on);
            AiVisSetMark(on);
            WinRedraw(g_w.aicheck);
            WinRedraw(g_w.cargocheck);
            WinRedraw(g_w.markcheck);
            reinterpret_cast<void(__cdecl*)(int)>(At(kVA_DrawMap))(1);
            reinterpret_cast<int(__fastcall*)(void*, void*)>(At(0x004B9EA0))(At(0x008C5568), nullptr);   // StatusWin_redraw(StatusWin_g)
            return;
        }
        if (id == kCargoChkId) {
            if (!AiVisGetLocal()) return;     // no meaning with the parent off
            AiVisSetCargoOne(AiVisGetCargoOne() ? 0 : 1);
            WinRedraw(g_w.cargocheck);
            return;
        }
        if (id == kCustomChkId) {         // live; persisted on OK / Enter.  Every portrait row follows it off AND on
            const int on = PortraitCustomGet() ? 0 : 1;
            // one re-bake: off puts the game's own portraits back.  Without the HD row the stored HD value is
            // kept (it is not shown, so it does not follow)
            PortraitSetAll(on, g_hdRow ? on : PortraitHdGet(), on);
            WinRedraw(g_w.customcheck);
            if (g_hdRow) WinRedraw(g_w.hdcheck);
            WinRedraw(g_w.scancheck);
            return;
        }
        if (g_hdRow && id == kHdChkId) {
            if (!PortraitCustomGet()) return; // no meaning with the parent off
            PortraitHdSet(PortraitHdGet() ? 0 : 1);
            if (g_hdRow) WinRedraw(g_w.hdcheck);
            return;
        }
        if (id == kScanChkId) {           // live; persisted on OK / Enter
            if (!PortraitCustomGet()) return; // no meaning with the parent off
            PortraitScanSet(PortraitScanGet() ? 0 : 1);
            PortraitRebake();                 // the native-size replacements; enlarged draws follow the mode
            WinRedraw(g_w.scancheck);
            return;
        }
        if (id == kAirdropChkId) {        // live: WrapActionAirdrop reads the flag per drop; persisted on OK / Enter
            AiVisSetAirdrop(AiVisGetAirdrop() ? 0 : 1);
            WinRedraw(g_w.airdropcheck);
            return;
        }
        if (g_modernRow && id == kModernChkId) {   // live: the detours / wrappers read the flag per event
            ModernControlsSet(ModernControlsGet() ? 0 : 1);
            WinRedraw(g_w.moderncheck);
            WinRedraw(g_w.rcmovecheck);            // dims / undims with its parent (its stored value is kept)
            if (g_dragRow) for (auto& c : g_w.dragcell) WinRedraw(c);
            UpdateHoldSliderState();
            return;
        }
        if (g_modernRow && id == kRcMoveChkId) {
            if (!ModernControlsGet() || !RightClickDragAvailable()) return;   // no meaning with the parent off / PRACX's drag sites unbound
            RightClickDragSet(RightClickDragGet() ? 0 : 1);
            WinRedraw(g_w.rcmovecheck);
            if (g_dragRow) for (auto& c : g_w.dragcell) WinRedraw(c);   // the right cell dims while the right button moves units
            UpdateHoldSliderState();
            return;
        }
        if (g_cameraRow && id == kClickViewChkId) {   // live: the set_center stub reads the flag per click
            ClickKeepsViewSet(ClickKeepsViewGet() ? 0 : 1);
            WinRedraw(g_w.clickview);
            return;
        }
        if (g_cameraRow && id == kBaseViewChkId) {
            BaseCloseKeepsViewSet(BaseCloseKeepsViewGet() ? 0 : 1);
            WinRedraw(g_w.baseview);
            return;
        }
        if (g_dragRow && id >= kDragCellId0 && id < kDragCellId0 + kDragCells) {
            // two exclusive cells: the other one switches; the SELECTED one clears both (= no drag scrolling)
            const int i = id - kDragCellId0;
            if (i == 1 && !MapDragRightAllowed()) return;   // dimmed: the right button is the move button
            const int v = kDragCellValue[i];
            MapDragButtonSet(MapDragButtonGet() == v ? kMapDragNone : v);
            for (auto& c : g_w.dragcell) WinRedraw(c);
            return;
        }
        if (id == kMarkChkId) {
            if (!AiVisGetLocal()) return;
            AiVisSetMark(AiVisGetMark() ? 0 : 1);
            WinRedraw(g_w.markcheck);
            reinterpret_cast<void(__cdecl*)(int)>(At(kVA_DrawMap))(1);   // the flags repaint with / without the mark
            reinterpret_cast<int(__fastcall*)(void*, void*)>(At(0x004B9EA0))(At(0x008C5568), nullptr);   // StatusWin_redraw(StatusWin_g): the HUD unit panels too
            return;
        }
        if (g_modeRow && id >= kModeChkId0 && id < kModeChkId0 + kModeCells) {
            // one of three: the clicked cell becomes the mode (a click on the checked one changes nothing);
            // never an engine ButtonGroup -- PrefWin's group handler stores ANY group's id as the current tab
            VidModeSet(id - kModeChkId0);
            for (auto& c : g_w.modecheck) WinRedraw(c);
            WinRedraw(g_w.clipcheck);     // dims outside Fullscreen
            return;
        }
        if (id == kUpdChkId) {            // "Check for Updates at Startup": next launch; saved with OK
            UpdateCheckSet(UpdateCheckGet() ? 0 : 1);
            WinRedraw(g_w.updcheck);
            return;
        }
        if (id == kSubBtnId) {            // "Reset Skipped Updates": confirmation popup (an ACTION: applies at once)
            UpdateSubscribeAll();         // on Yes: DeclinedUpdates cleared, the checkbox turns on
            WinRedraw(g_w.updcheck);
            WinRedraw(g_w.subbtn);
            {   // the page repaints after the nested popup -- through vtbl+0x30, so WrapRefresh re-issues our rows too
                void** vtbl = *reinterpret_cast<void***>(At(kVA_PrefWinInst));
                reinterpret_cast<void(__fastcall*)(void*, void*)>(vtbl[kSlotRefresh / 4])(At(kVA_PrefWinInst), nullptr);
            }
            return;
        }
        if (id == 0x5C) {                 // OK -> commit (engine writes volumes the same way)
            CommitAll();
        } else if (id == 0x5A) {          // Restore Defaults -> full scale, lawful ring
            g_pct = kDefaultPct;
            ApplyPct(g_pct);
            auto set = reinterpret_cast<FSbSet>(At(kVA_ScrollBarSet));
            set(g_w.slider, nullptr, g_pct);
            if (g_modeRow) { VidModeClipSet(1); WinRedraw(g_w.clipcheck); }
            AiVisSetLocal(kAiVisDefault);
            WinRedraw(g_w.aicheck);
            AiVisSetCargoOne(kCargoOneDefault);
            WinRedraw(g_w.cargocheck);
            AiVisSetMark(kCloakMarkDefault);
            WinRedraw(g_w.markcheck);
            if (g_modernRow) {
                ModernControlsSet(kModernControlsDefault);
                RightClickDragSet(kRightClickDragDefault);
                WinRedraw(g_w.moderncheck);
                WinRedraw(g_w.rcmovecheck);
            }
            if (g_dragRow) {
                MapDragButtonSet(kMapDragButtonDefault);
                for (auto& c : g_w.dragcell) WinRedraw(c);
            }
            if (g_cameraRow) {
                ClickKeepsViewSet(kClickKeepsViewDefault);
                BaseCloseKeepsViewSet(kBaseCloseKeepsViewDefault);
                WinRedraw(g_w.clickview);
                WinRedraw(g_w.baseview);
            }
            UpdateHoldSliderState();      // before the hold row's set_pos below: an enabled bar takes it
            // NOT "Check for Updates at Startup": the player's answer to the installer's question is a consent, not a
            // tuning, and nothing on this button says it would turn update checks on (audit 2026-11-07; user). The
            // only control that turns it on is the row itself and "Reset Skipped Updates", whose popup says so.
            // without the HD row the stored HD value is kept, as the parent's toggle keeps it: a setting the page
            // does not show is not reset (audit 2026-11-07)
            PortraitSetAll(kPortraitCustomDefault, g_hdRow ? (kPortraitCustomDefault ? kPortraitHdDefault : 0) : PortraitHdGet(),
                           kPortraitCustomDefault ? kPortraitScanDefault : 0);
            WinRedraw(g_w.customcheck);
            if (g_hdRow) WinRedraw(g_w.hdcheck);
            WinRedraw(g_w.scancheck);
            AiVisSetAirdrop(kAirdropDivertDefault);
            WinRedraw(g_w.airdropcheck);
            if (g_modeRow) {
                VidModeSet(kVidModeDefault);
                for (auto& c : g_w.modecheck) WinRedraw(c);
            }
            if (g_holdRow) {               // vanilla 333 ms
                DragDelaySet(kDragDelayDefault);
                set(g_w.holdslider, nullptr, DragDelayPosFromMs(kDragDelayDefault));
            }
        }
    }
    g_origCommand(self, edx, id);
}

// vtbl+0x64 on_key: Enter (0xD) commits like OK; ESC cancels (no persist). Chain.
int __fastcall WrapOnKey(void* self, void* edx, int a2, int key)
{
    if (g_built && key == 0xD) CommitAll();
    return g_origOnKey(self, edx, a2, key);
}

// vtbl+0xC4 slider change: live-apply our percent; chain for the volume ids.
void __fastcall WrapSlider(void* self, void* edx, int id, int value)
{
    if (g_built && g_holdRow && id == kHoldSliderId) {   // live-apply: the next map press waits the new time
        if (g_holdDisabled) {                             // inert: put the engine's position back
            reinterpret_cast<FSbSet>(At(kVA_ScrollBarSet))(g_w.holdslider, nullptr, DragDelayPosFromMs(DragDelayGet()));
            return;
        }
        DragDelaySet(DragDelayMsFromPos(value));
        SliderBubbleUpdate(g_w.holdslider);
        return;
    }
    if (g_built && id == kSliderId) {
        if (value < 0) value = 0;
        if (value > 100) value = 100;
        g_pct = value;
        ApplyPct(value);
        // live preview: repaint the map behind the window at the new label size --
        // the same call the engine makes when the prefs window closes; the window
        // z-list composites the open PrefWin back on top (maps animate under open
        // windows constantly, this is the identical path)
        auto dm = reinterpret_cast<void(__cdecl*)(int)>(At(kVA_DrawMap));
        dm(1);
        SliderBubbleUpdate(g_w.slider);
        return;
    }
    g_origSlider(self, edx, id, value);
}

// vtbl+0xC0 scrolled: a single chevron click (ScrollBar_on_chevron 0x606B20) notifies the parent HERE, not
// through +0xC4 (drag / held-chevron repeat). PrefWin's own slot is the shared `ret 8` stub 0x404260, so the
// volume sliders ignore it; ours route it to the same live-apply as a drag.
void __fastcall WrapScrolled(void* self, void* edx, int id, int value)
{
    if (g_built && (id == kSliderId || (g_holdRow && id == kHoldSliderId))) {
        WrapSlider(self, edx, id, value);
        return;
    }
    g_origScrolled(self, edx, id, value);
}

// The running display mode changed outside the page (Alt+Enter, PRACX's menu item) -- or through it.
// With the page showing, repaint the three cells so the checked one follows at once, and the pointer-hold row
// under them (dimmed outside Fullscreen).
void OnVidModeChanged()
{
    if (!g_built || !g_modeRow || !OurTabActive()) return;
    if (!reinterpret_cast<int(__fastcall*)(void*, void*)>(At(kVA_WinIsVisible))(At(kVA_PrefWin), nullptr)) return;
    for (auto& c : g_w.modecheck) WinRedraw(c);
    WinRedraw(g_w.clipcheck);
}

// ---- build -------------------------------------------------------------------------

// Width for an option row starting at native x: what its label wants, but never into the tab-button column
// (rows are child windows ABOVE the page; one that overlaps the tab column hides the buttons under it).
int RowW(int x, int want)
{
    const int tabX = Rd<int>(kVA_TabX);
    const int room = tabX > x ? tabX - x - 4 : want;          // tabs to the right of the page: stop short of them
    const int w = want < room ? want : room;
    char msg[160];
    _snprintf_s(msg, sizeof msg, _TRUNCATE, "[uimod] prefs: row x=%d want=%d tabX=%d tabW=%d frameX=%d frameW=%d -> w=%d\n",
                x, want, tabX, Rd<int>(kVA_TabW), Rd<int>(kVA_FrameX), Rd<int>(kVA_FrameW), w);
    UimodDbg(msg);
    return w > 8 ? w : 8;
}

// Cell i of n on one line over the frame span (native x): scaling_laws.pref_mode_cell_x = frame_x + cum(i, frame_w, n),
// cum = half_down(i*total, n) -- never i*(frameW/n)
int CellX(int fx, int fw, int n, int i) { return fx + (2 * i * fw + n - 1) / (2 * n); }

// Runs after EVERY PrefWin_build. desktop_init runs again on a game load (callers 0x51BC14 / 0x51AD08), and
// its PrefWin_build re-inits PrefWin: GraphicWin_init opens with GraphicWin_close, which tears down every
// child (ours included: +0x9C = 0, Win_show then a no-op), and the tab group is reset to the six stock tabs.
// The engine re-inits its own widgets there WITHOUT re-running their constructors; we mirror that: the
// constructors, private vtables, ini loads and the PrefWin vtable hooks run once, every init runs each build.
// (Built once only, the whole Longevity page vanished after such a load -- user, 2026-09-26.)
void BuildWidgets()
{
    const bool first = !g_built;
    if (first) {
        g_pct = LoadPct();
        ApplyPct(g_pct);
        g_big = LoadBig();
        ApplyBig(g_big);
    } else {
        SliderBubbleClear();
    }

    // register our block in the cave FIRST: the init calls below must hit the
    // slider-internals gate (gwinit slkid) and the zoom stubs from day one
    Wr<DWORD>(kVA_DllPrefLo, reinterpret_cast<DWORD>(&g_w));
    Wr<DWORD>(kVA_DllPrefHi, reinterpret_cast<DWORD>(&g_w) + sizeof(g_w) - 1);
    Wr<DWORD>(kVA_DllPrefSlider, reinterpret_cast<DWORD>(&g_w.slider));

    const int shift = Rd<int>(kVA_BotShift);
    void* prefwin = At(kVA_PrefWin);

    const auto flatCtor = reinterpret_cast<FCtor>(At(kVA_FlatButtonCtor));
    auto ctor = [&](void* w, void* edx) { if (first) flatCtor(w, edx); };   // constructed once (see above)
    auto binit = reinterpret_cast<FBtnInit>(At(kVA_BaseButtonInit));

    // the tab button, one row under Map Preferences (gamma moved from +0x9A to +0xB0)
    ctor(g_w.tab, nullptr);
    binit(g_w.tab, nullptr, "Longevity Mod Preferences", kTabId,
          Rd<int>(kVA_TabX), Rd<int>(kVA_TabY0) + kTabRowY, Rd<int>(kVA_TabW), Rd<int>(kVA_TabH), prefwin, 0);
    auto gadd = reinterpret_cast<FGroupAdd>(At(kVA_ButtonGroupAdd));
    gadd(At(kVA_PrefTabGroup), nullptr, g_w.tab);

    // the slider row, in the audio sliders' position (our page shows one row there)
    ctor(g_w.label, nullptr);
    binit(g_w.label, nullptr, "Base Font Size", kLabelId,
          Rd<int>(kVA_LabelX), Rd<int>(kVA_LabelY0) - shift + kSliderBlockDy,
          Rd<int>(kVA_LabelW), Rd<int>(kVA_LabelH), prefwin, 0);
    // static label, not a control: pin the forced draw state to NORMAL so hover and
    // click never change its look (content_draw honors [+0xAB8] before the dynamic
    // hover/pressed resolve); the click id is additionally swallowed in WrapCommand
    *reinterpret_cast<int*>(g_w.label + kForceStateOfs) = 0;

    // the option rows (the stock option lists' row geometry): FlatButtons for the engine's hit-testing / press /
    // release -> command dispatch, with a PRIVATE vtable copy whose content_draw is ours (the engine never draws
    // a button face for them)
    if (const int gs = Rd<int>(kVA_PopupScaleNum); gs > 16) {   // the rows' font (once; g is fixed per run)
        g_rowFontPtr = nullptr;
        if (Pcave2Present() && Rd<void*>(kVA_Scratch0Font + 8) != nullptr)
            g_rowFontPtr = At(kVA_Scratch0Font);                  // the stock rows' own Font object
        else {                                                    // port of thunk_build_scaled_fonts' calibration
            const char* narrow = *reinterpret_cast<const char**>(At(kVA_FontNameNarrow));
            const int target = (kPfCellNative * gs) >> 4;
            for (int size = gs;; ++size) {
                reinterpret_cast<FFontInit>(At(kVA_FontInit))(g_rowFont, nullptr, narrow, size, 1);
                if (*reinterpret_cast<int*>(g_rowFont + 0xC) >= target || size >= 64) break;
            }
            g_rowFontPtr = g_rowFont;
        }
    }
    if (first) {
        memcpy(g_chkVtbl, At(kVA_FlatBtnVtbl), kVtblBytes);
        g_chkVtbl[kSlotContentDraw / 4] = reinterpret_cast<void*>(&CheckContentDraw);
    }
    {
        auto ff = reinterpret_cast<void*(__cdecl*)(int, int)>(At(kVA_FindFont));
        void* fm = Rd<void*>(kVA_TextFontV1);                     // the rows' native font: the rect is native, the gate scales it
        if (!fm || !*reinterpret_cast<void**>(static_cast<BYTE*>(fm) + 8)) fm = ff(16, 1);
        // row height = the box sprite's own logical height (17 native: the stock rows' box is 42 px at 4K;
        // a 16 row clipped ours to 40 -- user shot 232319), fallback 16 if the sprite is not loaded yet
        int boxH = Rd<int>(kVA_ChkOffSprite + 0x1C);
        if (boxH <= 0 || boxH > 64) boxH = kChkRowH;
        // the display-mode row leads the page with "Constrain Mouse to Window" nested under it (both only with PRACX's
        // window code bound); the option rows start right after
        const int optRow0 = VidModeAvailable() ? kOptRow0 + 1 : 0;
        if (VidModeAvailable()) {
            int clipTextW = 160;                                  // fallback if no font is measurable
            if (fm)
                clipTextW = reinterpret_cast<FFontWidth>(At(kVA_FontWidth))(fm, nullptr, kClipChkText) + 8;
            ctor(g_w.clipcheck, nullptr);
            *reinterpret_cast<void**>(g_w.clipcheck) = g_chkVtbl;
            binit(g_w.clipcheck, nullptr, "", kClipChkId,
                  Rd<int>(kVA_FrameX) + kChkSubIndent, Rd<int>(kVA_TabY0) + kChkRowDy + kOptRow0 * kChkRowPitch,
                  RowW(Rd<int>(kVA_FrameX) + kChkSubIndent, kChkTextDx + clipTextW + 4), boxH + kChkTextDy, prefwin, 0);   // room for the label's descenders below the box
        }
        // The option rows, in the user's order (2026-11-07), top to bottom: the update row (a program setting,
        // like the display rows above it), the mouse group (Modern Control Set with its child, the two map-drag
        // cells on ONE line, the two camera rows: one block, ending nearest the Drag Hold Time slider it governs),
        // the gameplay rules (the cloak group, then the airdrop row), and the portrait group closing the list.
        // A row whose feature is unbound is not built and the rows below it move up: k counts the rows built.
        // Every row is the same widget class, vtable and painter (CheckContentDraw); the row's window rect is
        // native and the GraphicWin_init gate scales it once.
        const int fx = Rd<int>(kVA_FrameX);
        auto rowY = [&](int k) { return Rd<int>(kVA_TabY0) + kChkRowDy + (optRow0 + k) * kChkRowPitch; };
        auto labelW = [&](const char* t, int fallback) {   // fallback only while no font is measurable
            return fm ? reinterpret_cast<FFontWidth>(At(kVA_FontWidth))(fm, nullptr, t) + 8 : fallback;
        };
        auto row = [&](BYTE* w, int id, const char* text, int indent, int k) {   // -> the label width it used
            const int lw = labelW(text, 160);
            ctor(w, nullptr);
            *reinterpret_cast<void**>(w) = g_chkVtbl;
            binit(w, nullptr, "", id, fx + indent, rowY(k),
                  RowW(fx + indent, kChkTextDx + lw + 4), boxH + kChkTextDy, prefwin, 0);
            return lw;
        };
        int k = 0;

        // the update-check row: the checkbox, then -- on the SAME line, right of its label -- a stock
        // FlatButton (the engine's own face, id kSubBtnId) that clears every "Don't ask me again".
        // Native geometry throughout, like the other rows: the GraphicWin_init gate scales the rects
        // once, and the FlatButton zoom stubs draw the face at g/16 (skill prefwin-settings Recipe A).
        {
            const int y = rowY(k);
            const int updTextW = row(g_w.updcheck, kUpdChkId, kUpdChkText, 0, k++);   // the row's own width: one measure
            const int btnTextW = labelW(kSubBtnText, 120);
            const int btnX = fx + kChkTextDx + updTextW + 4 + 12;   // a gap after the label
            const int btnH = Rd<int>(kVA_TabH);                     // the tab buttons' face height
            const int btnW = RowW(btnX, btnTextW + 12);
            ctor(g_w.subbtn, nullptr);                              // stock vtable: engine face + label
            binit(g_w.subbtn, nullptr, kSubBtnText, kSubBtnId,
                  btnX, y - (btnH - (boxH + kChkTextDy)) / 2, btnW, btnH, prefwin, 0);
        }

        // the mouse group: the Modern Control Set parent with its nested child, then the two map-drag cells on
        // ONE line (only with PRACX's drag sites bound; MapDragButton applies with Modern off too), then the two
        // camera rows (the map stays put on a left click / when a base closes; independent of Modern).
        // Latched at the FIRST build: a row is constructed once (ctor), so a feature bound or unbound mid-session
        // shows / hides its row at the next launch -- never a half-built widget
        if (first) {
            g_modernRow = ModernControlsAvailable();
            g_dragRow = MapDragButtonAvailable();
            g_cameraRow = CameraAvailable();
        }
        if (g_modernRow) {
            row(g_w.moderncheck, kModernChkId, kModernChkText, 0, k++);
            row(g_w.rcmovecheck, kRcMoveChkId, kRcMoveChkText, kChkSubIndent, k++);
        } else {
            UimodDbg("[uimod] prefs: Modern Control Set unavailable -> no rows for it\n");
        }
        if (g_dragRow) {
            const int fw = Rd<int>(kVA_FrameW);
            const int y = rowY(k++);
            for (int i = 0; i < kDragCells; ++i) {
                int w = kChkTextDx + labelW(kDragCellText[i], 160) + 4;
                if (const int cell = CellX(fx, fw, kDragCells, i + 1) - CellX(fx, fw, kDragCells, i); w > cell) w = cell;
                ctor(g_w.dragcell[i], nullptr);
                *reinterpret_cast<void**>(g_w.dragcell[i]) = g_chkVtbl;
                binit(g_w.dragcell[i], nullptr, "", kDragCellId0 + i, CellX(fx, fw, kDragCells, i), y,
                      RowW(CellX(fx, fw, kDragCells, i), w), boxH + kChkTextDy, prefwin, 0);
            }
        }
        if (g_cameraRow) {
            row(g_w.clickview, kClickViewChkId, kClickViewText, 0, k++);
            row(g_w.baseview, kBaseViewChkId, kBaseViewText, 0, k++);
        }

        // the gameplay rules: the AI-visibility parent with its two nested rows, then the airdrop-diversion row
        // (top-level: it covers fog of war, not only cloaks)
        row(g_w.aicheck, kAiChkId, kAiChkText, 0, k++);
        row(g_w.cargocheck, kCargoChkId, kCargoChkText, kChkSubIndent, k++);
        row(g_w.markcheck, kMarkChkId, kMarkChkText, kChkSubIndent, k++);
        row(g_w.airdropcheck, kAirdropChkId, kAirdropChkText, 0, k++);

        // the portrait group closes the list, the cloak rows' parent/child pattern: "Enable Custom Portraits" at
        // the list's left edge; nested one box width in, "Use Turovetsky's HD Portrait Pack" (only while the pack is
        // installed: no row for a pack the player does not have) and "Add Scanlines" (its scanlines are always the
        // brightened kind: the former "Brighten Scanlines" row made way for the airdrop row, user 2026-10-30)
        if (first) g_hdRow = PortraitPackInstalled();
        row(g_w.customcheck, kCustomChkId, kCustomChkText, 0, k++);
        if (g_hdRow) row(g_w.hdcheck, kHdChkId, kHdChkText, kChkSubIndent, k++);
        row(g_w.scancheck, kScanChkId, kScanChkText, kChkSubIndent, k++);

        {
            // the page's vertical room is runtime layout (PrefWin_build's statics): log it, and say so loudly if
            // the last row would reach the slider-area frame drawn below the option rows
            const int firstY = rowY(0);
            const int lastBottom = rowY(k - 1) + boxH + kChkTextDy;
            const int frameTop = Rd<int>(kVA_FrameY) - Rd<int>(kVA_BotShift) + kSliderBlockDy;
            char msg[192];
            _snprintf_s(msg, sizeof msg, _TRUNCATE,
                        "[uimod] prefs: %d option rows (updates..portraits) at row indices %d..%d of 0..14, y=%d..%d (native), slider frame top=%d%s\n",
                        k, optRow0, optRow0 + k - 1, firstY, lastBottom, frameTop, lastBottom > frameTop ? "  !! OVERLAPS THE FRAME" : "");
            if (lastBottom > frameTop) Dbg(msg);  // a real overlap is a fault: every log
            else UimodDbg(msg);
        }

        // the display-mode row: three cells on ONE line over the frame span, native x by
        // scaling_laws.pref_mode_cell_x (cum(): half_down(i*frameW, 3), never i*(frameW/3)); the gate
        // scales each cell's own x once. Only with PRACX's window code bound (vidmode.cpp).
        if (VidModeAvailable()) {
            const int fw = Rd<int>(kVA_FrameW);                 // fx: the option rows' above
            auto cellX = [&](int i) { return CellX(fx, fw, kModeCells, i); };
            for (int i = 0; i < kModeCells; ++i) {
                int w = 100;
                if (fm)
                    w = reinterpret_cast<FFontWidth>(At(kVA_FontWidth))(fm, nullptr, kModeText[i]) + 8;
                w += kChkTextDx + 4;
                if (const int cell = cellX(i + 1) - cellX(i); w > cell) w = cell;   // never into the next cell
                ctor(g_w.modecheck[i], nullptr);
                *reinterpret_cast<void**>(g_w.modecheck[i]) = g_chkVtbl;
                binit(g_w.modecheck[i], nullptr, "", kModeChkId0 + i,
                      cellX(i), Rd<int>(kVA_TabY0) + kChkRowDy + kModeRow * kChkRowPitch,
                      RowW(cellX(i), w), boxH + kChkTextDy, prefwin, 0);
            }
            g_modeRow = true;
            if (first) VidModeOnChange(&OnVidModeChanged);
        }
    }

    // scaled label font from the start: the stock buttons get theirs re-written by
    // thunk_pref_show at every SHOW, but our tab composites before our refresh wrapper
    // runs on the first show -- without this it rendered native until a hover redraw
    // The stock buttons' vanilla font is the shared 0x6E84B4 = Font_init("Arial", 14, 1): on a patched exe
    // thunk_pref_show stamps them with t_fdirect_a14b() = Arial fl(14g/16) BOLD on the font_face_law slot
    // (pcave2 0x2E590; 2026-09-17, audit finding 3.5), so our tab/label take the SAME Font object; without
    // the cave (unpatched exe) fall back to the pool lookup that v1 used.
    const int g = Rd<int>(kVA_PopupScaleNum);
    if (g > 16) {
        void* f = nullptr;
        if (Pcave2Present())
            f = reinterpret_cast<void*(__cdecl*)()>(At(kVA_FontDirectA14B))();
        if (!f) {
            auto ff = reinterpret_cast<void*(__cdecl*)(int, int)>(At(kVA_FindFont));
            f = ff((14 * g) >> 4, 1);
        }
        if (f) {
            *reinterpret_cast<void**>(g_w.tab + kFontSlotOfs) = f;
            *reinterpret_cast<void**>(g_w.label + kFontSlotOfs) = f;
            *reinterpret_cast<void**>(g_w.subbtn + kFontSlotOfs) = f;   // the stock-face button reads like the tab buttons
            g_labelFont = f;
        }
    }

    const auto sbCtor = reinterpret_cast<FCtor>(At(kVA_ScrollBarCtor));
    auto sctor = [&](void* w, void* edx) { if (first) sbCtor(w, edx); };
    auto sinit = reinterpret_cast<FSbInit>(At(kVA_ScrollBarInit));
    auto srange = reinterpret_cast<FSbRange>(At(kVA_ScrollBarRange));
    auto sset = reinterpret_cast<FSbSet>(At(kVA_ScrollBarSet));
    // the private ScrollBar vtable both our sliders use (draw bracket + value-bubble hooks)
    if (first) {
        memcpy(g_sbVtbl, At(kVA_ScrollBarVtbl), kSbVtblBytes);
        g_origSbDraw = reinterpret_cast<FSbDraw>(g_sbVtbl[0x30 / 4]);
        g_origSbPress = reinterpret_cast<FSbXY>(g_sbVtbl[kSbSlotPress / 4]);
        g_origSbRelease = reinterpret_cast<FSbXY>(g_sbVtbl[kSbSlotRelease / 4]);
        g_origSbChevron = reinterpret_cast<FSbOne>(g_sbVtbl[kSbSlotChevron / 4]);
        g_origSbMove = reinterpret_cast<FSbXY>(g_sbVtbl[kSbSlotMove / 4]);
        g_origSbLeave = reinterpret_cast<FSbXY>(g_sbVtbl[kSbSlotLeave / 4]);
        g_origSbRepeat = reinterpret_cast<FSbOne>(g_sbVtbl[kSbSlotRepeat / 4]);
        g_sbVtbl[0x30 / 4] = reinterpret_cast<void*>(&HoldSliderDraw);
        g_sbVtbl[kSbSlotPress / 4] = reinterpret_cast<void*>(&SbPress);
        g_sbVtbl[kSbSlotRelease / 4] = reinterpret_cast<void*>(&SbRelease);
        g_sbVtbl[kSbSlotChevron / 4] = reinterpret_cast<void*>(&SbChevron);
        g_sbVtbl[kSbSlotMove / 4] = reinterpret_cast<void*>(&SbMove);        // the disabled hold slider: tooltip, no drag
        g_sbVtbl[kSbSlotLeave / 4] = reinterpret_cast<void*>(&SbLeave);
        g_sbVtbl[kSbSlotRepeat / 4] = reinterpret_cast<void*>(&SbRepeat);
        // dimmed-row text: the game palette's nearest neutral to a darkened list colour
        g_greyText = PalGrey(104, 124, 124, kGreyMid);
    }
    sctor(g_w.slider, nullptr);
    *reinterpret_cast<void**>(g_w.slider) = g_sbVtbl;
    sinit(g_w.slider, nullptr, Rd<int>(kVA_SliderX), Rd<int>(kVA_SliderY0) + kSliderBlockDy,
          Rd<int>(kVA_SliderW), prefwin, kSliderId);
    srange(g_w.slider, nullptr, 0, 100);
    sset(g_w.slider, nullptr, g_pct);

    // the "Drag Hold Time" row, in the audio page's second row (label/slider y0 + 0x16, like the
    // engine's own row 1 at 0x48F344/0x48F60F) inside the same slider-area frame. Only when the delay
    // site passed its byte check (dragdelay.cpp).
    if (DragDelayAvailable()) {
        ctor(g_w.holdlabel, nullptr);
        binit(g_w.holdlabel, nullptr, kHoldText, kHoldLabelId,
              Rd<int>(kVA_LabelX), Rd<int>(kVA_LabelY0) - shift + kSliderBlockDy + kAudioRowPitch,
              Rd<int>(kVA_LabelW), Rd<int>(kVA_LabelH), prefwin, 0);
        *reinterpret_cast<int*>(g_w.holdlabel + kForceStateOfs) = 0;   // inert, like the font label
        if (g_labelFont) *reinterpret_cast<void**>(g_w.holdlabel + kFontSlotOfs) = g_labelFont;

        // the shared private ScrollBar vtable (its draw brackets the registry slot for THIS slider,
        // HoldSliderDraw); the slot also names it for its construction, so gwinit's slkid gate scales its
        // arrows/thumb
        Wr<DWORD>(kVA_DllPrefSlider, reinterpret_cast<DWORD>(&g_w.holdslider));
        sctor(g_w.holdslider, nullptr);
        *reinterpret_cast<void**>(g_w.holdslider) = g_sbVtbl;
        sinit(g_w.holdslider, nullptr, Rd<int>(kVA_SliderX), Rd<int>(kVA_SliderY0) + kSliderBlockDy + kAudioRowPitch,
              Rd<int>(kVA_SliderW), prefwin, kHoldSliderId);
        srange(g_w.holdslider, nullptr, 0, kDragDelayPositions - 1);
        sset(g_w.holdslider, nullptr, DragDelayPosFromMs(DragDelayGet()));
        Wr<DWORD>(kVA_DllPrefSlider, reinterpret_cast<DWORD>(&g_w.slider));
        g_holdRow = true;
        g_holdApplied = -1;                      // the arrows were re-initialised: their tooltip must be written again
        UpdateHoldSliderState();
    } else {
        Dbg("[uimod] prefs: drag-hold delay unavailable -> no Drag Hold Time row\n");
    }

    WinHide(g_w.label);                          // start hidden (shown by tab refresh)
    if (g_modeRow) WinHide(g_w.clipcheck);
    WinHide(g_w.aicheck);
    WinHide(g_w.cargocheck);
    WinHide(g_w.markcheck);
    if (g_modernRow) { WinHide(g_w.moderncheck); WinHide(g_w.rcmovecheck); }
    if (g_dragRow) for (auto& c : g_w.dragcell) WinHide(c);
    if (g_cameraRow) { WinHide(g_w.clickview); WinHide(g_w.baseview); }
    WinHide(g_w.updcheck);
    WinHide(g_w.subbtn);
    WinHide(g_w.customcheck);
    if (g_hdRow) WinHide(g_w.hdcheck);
    WinHide(g_w.scancheck);
    WinHide(g_w.airdropcheck);
    if (g_modeRow) for (auto& c : g_w.modecheck) WinHide(c);
    WinHide(g_w.slider);
    if (g_holdRow) { WinHide(g_w.holdlabel); WinHide(g_w.holdslider); }

    if (!first) {
        Dbg("[uimod] prefs: Longevity tab rebuilt (PrefWin_build ran again)\n");
        return;
    }

    // hook the PrefWin vtable ONCE (data writes; slots +0x30/+0x64/+0xB0/+0xC4): a second wrap would chain
    // our wrappers to themselves
    BYTE* vt = At(kVA_PrefWinVtbl);
    DWORD old;
    VirtualProtect(vt, 0x168, PAGE_READWRITE, &old);
    g_origRefresh = *reinterpret_cast<FRefresh*>(vt + kSlotRefresh);
    g_origOnKey = *reinterpret_cast<FOnKey*>(vt + kSlotOnKey);
    g_origCommand = *reinterpret_cast<FOnCommand*>(vt + kSlotCommand);
    g_origSlider = *reinterpret_cast<FOnSlider*>(vt + kSlotSlider);
    g_origScrolled = *reinterpret_cast<FOnSlider*>(vt + kSlotScrolled);
    *reinterpret_cast<void**>(vt + kSlotRefresh) = reinterpret_cast<void*>(&WrapRefresh);
    *reinterpret_cast<void**>(vt + kSlotOnKey) = reinterpret_cast<void*>(&WrapOnKey);
    *reinterpret_cast<void**>(vt + kSlotCommand) = reinterpret_cast<void*>(&WrapCommand);
    *reinterpret_cast<void**>(vt + kSlotSlider) = reinterpret_cast<void*>(&WrapSlider);
    *reinterpret_cast<void**>(vt + kSlotScrolled) = reinterpret_cast<void*>(&WrapScrolled);
    VirtualProtect(vt, 0x168, old, &old);

    g_built = true;
    Dbg("[uimod] prefs: Longevity tab built\n");
}

// The retargeted desktop_init call lands here: chain the real PrefWin_build (ecx is
// already the PrefWin static at the site, re-asserted for safety), then build ours.
void __declspec(naked) BuildHookThunk()
{
    __asm {
        mov  ecx, 0x008578D8
        mov  eax, 0x0048D840
        call eax
        pushad
    }
    BuildWidgets();
    __asm {
        popad
        ret
    }
}

// Byte-checked in-place code patch helper.
bool PatchBytes(uintptr_t va, const BYTE* expect, size_t n, const BYTE* repl,
                size_t off, size_t rn)
{
    BYTE* p = At(va);
    if (memcmp(p, expect, n) != 0) return false;
    DWORD old;
    VirtualProtect(p, n, PAGE_EXECUTE_READWRITE, &old);
    memcpy(p + off, repl, rn);
    VirtualProtect(p, n, old, &old);
    return true;
}

// True iff the loaded exe has the patcher's .pcave2 section covering the Longevity
// registry block. The PRISTINE terranx.exe (uimod loads there too) has no cave --
// without this gate the first cave write in BuildWidgets access-violates at
// desktop_init. The feature needs the cave thunks anyway (zoom stubs, thunk_map_font),
// so on an unpatched exe it must disable itself entirely.
bool Pcave2Present()
{
    uintptr_t lo, hi;
    if (!UimodPcave2Range(&lo, &hi)) return false;
    const BYTE* base = reinterpret_cast<const BYTE*>(GetModuleHandleA(nullptr));
    return reinterpret_cast<uintptr_t>(base) + (kVA_DllPrefLo - kImageBase) >= lo &&
           reinterpret_cast<uintptr_t>(base) + ((kVA_BigF4 + 4) - kImageBase) <= hi;
}

// True iff the loaded exe carries fix 28's checkbox law (t_ck_draw + g_ck_ph inside .pcave2, t_ck_draw's entry
// bytes in place).  Checked once.
bool CkLawPresent()
{
    static int s_present = -1;
    if (s_present < 0) {
        uintptr_t lo, hi;
        const uintptr_t draw = reinterpret_cast<uintptr_t>(At(kVA_CkDraw));
        const uintptr_t cell = reinterpret_cast<uintptr_t>(At(kVA_CkPhase));
        s_present = UimodPcave2Range(&lo, &hi) && draw >= lo && cell + 4 <= hi &&
                    memcmp(At(kVA_CkDraw), kCkDrawEntry, sizeof kCkDrawEntry) == 0;
        UimodDbg(s_present ? "uimod: checkbox law t_ck_draw present -> Longevity rows use it\n"
                           : "uimod: checkbox law t_ck_draw absent -> Longevity rows keep Sprite_draw_2\n");
    }
    return s_present == 1;
}

} // namespace

// The loaded exe's .pcave2 section as LIVE addresses [lo, hi); false on an unpatched exe (no such
// section). Other modules use it to recognise a call site the patcher already re-pointed at a cave thunk.
bool UimodPcave2Range(uintptr_t* lo, uintptr_t* hi)
{
    const BYTE* base = reinterpret_cast<const BYTE*>(GetModuleHandleA(nullptr));
    auto dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return false;
    auto nt = reinterpret_cast<const IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return false;
    const IMAGE_SECTION_HEADER* sec = IMAGE_FIRST_SECTION(nt);
    for (unsigned i = 0; i < nt->FileHeader.NumberOfSections; ++i, ++sec) {
        static const BYTE name[8] = { '.', 'p', 'c', 'a', 'v', 'e', '2', 0 };
        if (memcmp(sec->Name, name, 8) != 0) continue;
        const DWORD span = sec->Misc.VirtualSize > sec->SizeOfRawData
                               ? sec->Misc.VirtualSize : sec->SizeOfRawData;
        *lo = reinterpret_cast<uintptr_t>(base) + sec->VirtualAddress;
        *hi = *lo + span;
        return true;
    }
    return false;
}

// Called for every message the game thread retrieves (wheel.cpp's WH_GETMESSAGE hook): drops our value
// bubble once its slider is no longer held -- the backstop for releases that reach no handler of ours
// (an arrow released off itself, Esc / window close mid-press).
void PrefsBubblePoll()
{
    if (g_tipSb) {                     // the disabled slider's tooltip: forget it once the engine replaced it,
        if (Rd<void*>(kVA_BubbleOwner) != g_tipSb || Rd<const char*>(kVA_BubbleText) != g_tipBuf) g_tipSb = nullptr;
        else if (!reinterpret_cast<int(__fastcall*)(void*, void*)>(At(kVA_WinIsVisible))(At(kVA_PrefWin), nullptr) ||
                 !OurTabActive())
            SliderTipClear();          // ... drop it when the window closed / the tab changed under the cursor
    }
    if (!g_bubbleSb) return;
    if (Rd<void*>(kVA_BubbleOwner) != g_bubbleSb || Rd<const char*>(kVA_BubbleText) != g_bubbleBuf) {
        g_bubbleSb = nullptr;          // replaced or cleared by the engine: no longer ours
        return;
    }
    if (!SliderHeld(g_bubbleSb)) SliderBubbleClear();
}

void InstallPrefsTab()
{
    // 0) patched-exe gate: the pristine/unpatched exe has no code cave -- the tab's
    //    machinery (registry slots, thunk_map_font, zoom stubs) does not exist there.
    if (!Pcave2Present()) {
        Dbg("[uimod] prefs: no .pcave2 section (unpatched exe) -> Longevity tab disabled\n");
        return;
    }

    // 1) gamma button down one row: ADD EDX,0x9A -> ADD EDX,0xB0
    static const BYTE gammaExpect[6] = { 0x81, 0xC2, 0x9A, 0x00, 0x00, 0x00 };
    static const BYTE gammaNew[4] = { 0xB0, 0x00, 0x00, 0x00 };
    if (!PatchBytes(kVA_GammaAddImm, gammaExpect, 6, gammaNew, 2, 4)) {
        Dbg("[uimod] prefs: gamma-imm byte check FAILED -- tab not installed\n");
        return;
    }

    // 2) desktop_init's PrefWin_build call -> our thunk (rel32 rewrite inside the E8)
    BYTE* site = At(kVA_BuildCallSite);
    static const BYTE callExpect[5] = { 0xE8, 0x66, 0xE9, 0xEF, 0xFF };
    if (memcmp(site, callExpect, 5) != 0) {
        Dbg("[uimod] prefs: build-call byte check FAILED -- tab not installed\n");
        return;
    }
    const DWORD rel = reinterpret_cast<DWORD>(&BuildHookThunk)
                      - (reinterpret_cast<DWORD>(site) + 5);
    DWORD old;
    VirtualProtect(site, 5, PAGE_EXECUTE_READWRITE, &old);
    memcpy(site + 1, &rel, 4);
    VirtualProtect(site, 5, old, &old);

    Dbg("[uimod] Init: prefs tab hook installed\n");
}
