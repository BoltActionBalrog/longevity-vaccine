// modernctl.cpp -- the "Modern Control Set" (see modernctl.h). Everything here is byte-checked at Init and
// installs on both exes; with [UIMod] ModernControls=0 the engine runs vanilla code paths (the detours and
// the vtable wrappers forward unchanged), except for the two unconditional fixes at the end.
//
// Engine map (traced 2026-10-07, symbols in work\symbols\terranx.h "map tile CLICK chain"):
//   * MapWin_click 0x46D5D0 is the ONE tile-click handler for both buttons (this=Console 0x9156B0, args px, py,
//     is_right). Locals: [ebp-0x10] = tile x, [ebp-0x14] = tile y, [ebp+8] = dev x, EBX = dev y, ESI = Console.
//     Its right-click branch opens at 0x46E36D (`mov eax,[ebp+0x10]; test eax,eax; jz 0x46E5E6` = is_right?);
//     Shift / Ctrl+Shift are decided at 0x46E378..0x46E391 (Shift -> 'Move cursor to here' 0x46E463 or the menu
//     by the stock preference; Ctrl+Shift -> info); the plain right click reaches the menu gate at 0x46E529
//     (`mov eax,[GameMorePreferences]; test ah,1`) -> ControlTurnC check 0x46E544 -> MapWin_right_menu 0x46C0D0.
//     The inline go-to at 0x46DF0E (what a drag release runs: lock_veh, order 0x18, waypoint 0, synch_veh,
//     unlock, Console_set_move(1) in view mode) needs only EAX = unit id, ESI and the two tile locals.
//   * The Console's GraphicWin (Console+0x23D94, = 0x939444) dispatches mouse events through its vtable
//     g_console_win_vtbl 0x66EC18: +0x44 mouse_move, +0x48 mouse_leave (a ret-8 stub), +0x50 left_down,
//     +0x58 right_click (fires on WM_RBUTTONUP), +0x5C right_down; the entries are vbase adjustor thunks
//     0x51DExx (`sub ecx,[ecx-4]; sub ecx,0x2328; jmp handler`), so a wrapper forwards by calling the saved
//     entry with the untouched ecx.
//   * The drag line: MapWin_on_mouse_move 0x46F000 draws the path + "Move to" label on the overlay window
//     oWinBuffed 0x937118 whenever Console+0x1DD80 (drag active) and [0x9393C0] (selecting mode) are set,
//     and only when the tile under the pointer changed (+0x1DE0C/+0x1DE10). In that mode it also WRITES the
//     unit's waypoint bytes (Vehs[veh]+0x12..+0x23) on every move, so the hover wrapper saves and restores them.
//   * The status window's refresh (~156 ms timer, 0x4B5D7C-0x4B5DC7) owns the same overlay in vanilla: it draws
//     the selected unit's committed route (draw_my_dest 0x4B5D95 + Win_show) when its order is go-to, else
//     Win_hide (0x4B5DC2). Both calls are redirected to stubs that stand aside while the hover line owns the
//     overlay (traced 2026-10-07: 1,596 hides per session wiped the line whenever the pointer rested).
//   * MapWin_click returns at once for a RIGHT release while the go-to cursor is set (0x46D7E1 -> 0x46EAC4):
//     the right-drag option therefore routes such a release through the LEFT click entry.
//   * go_reset 0x50EF50 (every click and every key-down) hides the overlay, stops the hold timer and, while a
//     map press is armed (g_go_win_idx 0x68A5CC >= 0), sets Console+0x1DD88 = swallow the next click. Shift's
//     key auto-repeat therefore ate the release of a Shift+click after the repeat delay: fixed here for good.
//   * Thinker (modify_unit_limit) relocates the unit array and repoints every engine operand: the array base
//     is read from veh_selectable's own operand at Init, never assumed.
//   * The scenario editor (GameState 0x40) changes map input only for its paint keys (Ctrl, Scroll Lock) and its
//     armed paint drag (Console+0x1DD8C): see EditorEngaged. The bit itself stays set for the rest of the game and
//     in its saves, so the set must not key on it alone.

#include "modernctl.h"
#include "mapgate.h"
#include "praxdrag.h"

#include <cstdint>
#include <cstdio>
#include <cstring>

void UimodLog(const char* msg);
void UimodDbg(const char* msg);

namespace {

constexpr uintptr_t kImageBase = 0x400000;

// ---- engine objects, globals, functions ------------------------------------------------------------
constexpr uintptr_t kVA_Console        = 0x9156B0;   // MapWin_g (Console)
constexpr uintptr_t kVA_ConsoleVtbl    = 0x66EC18;   // g_console_win_vtbl (.rdata)
constexpr uintptr_t kVA_Overlay        = 0x937118;   // Console+0x21A68 oWinBuffed: the drag-line overlay
constexpr uintptr_t kVA_GoTimer        = 0x939E60;   // g_go_timer (Time)
constexpr uintptr_t kVA_GoWinIdx       = 0x68A5CC;   // g_go_win_idx: MapWinPtr slot of the armed press, -1 idle
constexpr uintptr_t kVA_MoveMode       = 0x939288;   // Console+0x23BD8: nonzero = a unit awaits orders
constexpr uintptr_t kVA_CurVeh         = 0x93928C;   // Console+0x23BDC: selected unit, -1 none
constexpr uintptr_t kVA_SelMode        = 0x9393C0;   // Console+0x23D10: selecting mode (go_timer sets 1)
constexpr int kPickModeLo = 2, kPickModeHi = 11;     // MapWin_click's pick table (0x46E1AF: mode - 2 <= 9)
constexpr uintptr_t kVA_ConSelected  = 0x5107E0;   // Console_selected (thiscall, plain ret): takes the pick -- clears
                                                     // +0x23D10 and puts the arrow back on every map window
constexpr int kSelModeCtrlDrag = 9;                  // go_timer's Ctrl drag in view mode (a left drag, not a pick)
constexpr uintptr_t kVA_GroupFormed    = 0x9393CC;   // Console+0x23D1C: a group is formed (Console_group 0x4D92D0 sets 1; go_timer then keeps mode 1 and sets goto_group +0x1DD84) -- unused here; was misnamed "editor unit placement"
constexpr uintptr_t kVA_CurIdx         = 0x9392B8;   // map cursor history index
constexpr uintptr_t kVA_CurXs          = 0x9392C0;   // int[32]
constexpr uintptr_t kVA_CurYs          = 0x939340;   // int[32]
constexpr uintptr_t kVA_Faction        = 0x939284;   // CurrentPlayerFaction
constexpr uintptr_t kVA_ControlTurnC   = 0x93A938;   // nonzero = not the human's turn
constexpr uintptr_t kVA_PbemActive     = 0x93A95C;   // hotseat / PBEM: the overlay doubles as the blackout
constexpr uintptr_t kVA_MapMouse       = 0x90D938;   // g_map_mouse_enabled
// Over the console window's transparent top band a buttonless move reaches the map's +0x44 with coordinates local
// to the CONSOLE window (traced 2026-10-10: raw y 1471 -> local y 26 = "top of the map"); vanilla never draws a
// line on such a move, so only the hover line showed it. Win_get_mouse_window 0x5F6F10 keeps the event's raw
// screen point (0x5F6F2A / 0x5F6F38) and makes it local by the window's origin = +0x13C + +0x14C (x),
// +0x140 + +0x150 (y) (0x5F6FC3..0x5F6FE5): a move is the MAP's own only when its x/y equal that.
constexpr uintptr_t kVA_MouseRawX      = 0x9B6628, kVA_MouseRawY = 0x9B662C;
// g_last_mouse_win: the window Win_OnMouseMove resolved (stored 0x5F231C). Traced 2026-10-10: over the console's
// transparent top band it IS the map window -- the resolver tried a HUD window there, found the pixel see-through,
// fell back to the map and kept that HUD window's local coordinates (an engine bug). Over COMMLINK / MENU / the strip
// it is that widget's own window, and the map gets no move at all.
constexpr uintptr_t kVA_LastMouseWin   = 0x9B7A7C;
// mapgate.h: the shown top-level windows Win_get_mouse_window tries BEFORE the map block it (their see-through pixels
// hand the event on); the HUD strip window does not (its see-through top band IS the map to the player).
constexpr uintptr_t kVA_TopWindows     = 0x9B6E48;   // g_top_windows[]: the list Win_get_mouse_window walks (0x5F72DB)
constexpr uintptr_t kVA_TopWindowCount = 0x9B7B34;   // g_top_window_count
constexpr uintptr_t kVA_MainWin        = 0x7AE820;   // MainWin_g: the HUD strip window
constexpr uintptr_t kVA_TutWin         = 0x8C6E68;   // TutWin: the tutorial box -- blocks even when the list walk is not understood
constexpr size_t kWinStyle = 0x98;                   // Win: bit 0x20 = rect relative to the parent
constexpr size_t kWinRect1 = 0x13C, kWinRect2 = 0x14C;   // Win rRect1 / rRect2 (rRect2 = position when +0x9C & 2, else 0)
constexpr size_t kWinDelegate = 0xA8;                // Win: the window the walk returns for this one (0x5F730E)
constexpr size_t kWinChildren = 0x1A4, kWinChildCount = 0x3FC;   // the hit-test's child array (0x5F6B0C..0x5F6B58)
constexpr int    kMaxBlockers = 32;
constexpr uintptr_t kVA_SetMove        = 0x511520;   // Console_set_move(this, force) thiscall RET 4
constexpr uintptr_t kVA_PixelToTile    = 0x463040;   // MapWin_pixel_to_tile(this=Console, px, py, int* tx, int* ty) RET 0x10; 0 = ok
// Waypoints (Ctrl+right in Modern instant mode) -- the engine's own G/Space branch in Console_on_key_click
// (0x517C74..0x517D45, live only during a go-to drag): unit flag 0x2000000 = collecting, +0x12 = fixed waypoints,
// slots x +0x14 / y +0x1C (int16 x4), the drag painter writes the moving target into slot[count] (0x46F18C), and
// the go-to commit (0x46DFC6) keeps the path when the flag is set (slot[count] = the destination). 4 slots: 3
// waypoints + the destination.
constexpr uint32_t kVehWaypointFlag = 0x2000000;
constexpr uint32_t kVehPathCommitted = 0x2000200;   // the go-to commit's `or 0x2000200` (0x46DFD8)
constexpr uint32_t kVehOrderGoTo = 0x18;
constexpr size_t kVehUnitId = 0xA;
constexpr uintptr_t kVA_MultiplayerActive = 0x93F660;   // Thinker MultiplayerActive (DirectPlay/TCP game)
constexpr size_t kVehWpCount = 0x12, kVehWpAux = 0x13, kVehWpX = 0x14, kVehWpY = 0x1C;
constexpr int kWpSlots = 4;
constexpr int kWinOrgX0 = 0x13C, kWinOrgX1 = 0x14C, kWinOrgY0 = 0x140, kWinOrgY1 = 0x150;
constexpr uintptr_t kVA_GameState      = 0x9A64C0;   // bit 0x40 = scenario editor
constexpr uintptr_t kVA_MorePrefs      = 0x9A6494;   // GameMorePreferences
constexpr uintptr_t kVA_VehCount       = 0x9A64C8;   // VehCount (live)
constexpr uintptr_t kVA_ModalTop       = 0x9B7AE0;   // g_modal_top
constexpr uintptr_t kVA_BasePop        = 0x9B8D7C;   // g_current_basepop
constexpr uintptr_t kVA_MainHwnd       = 0x9B7B28;   // g_main_hwnd
constexpr uintptr_t kVA_Vehs           = 0x952828;   // VEH[] (stock base; Thinker relocates it -- see g_vehs)
constexpr uintptr_t kVA_VehSelOperand  = 0x5C1A39;   // veh_selectable: `movsx edx,[eax+0x95282A]` -- the live array base + 2
constexpr uintptr_t kVA_VehFind        = 0x5C0CB0;   // cdecl(x, y, faction, -1) -> veh or -1
constexpr uintptr_t kVA_VehSelectable  = 0x5C1A20;   // cdecl(veh) -> nonzero = selectable
constexpr uintptr_t kVA_TimeStop       = 0x616780;   // thiscall(Time*): KillTimer / timeKillEvent
constexpr uintptr_t kVA_WinShow        = 0x5ED9D0;   // thiscall(Win*, int) RET 4
constexpr uintptr_t kVA_WinHide        = 0x5EDCD0;   // thiscall(Win*)
constexpr uintptr_t kVA_GWinClear      = 0x5D5250;   // thiscall(GraphicWin*, color) RET 4; 9 = transparent
constexpr uintptr_t kVA_DrawMyDest     = 0x4B4BF0;   // cdecl(veh): the committed go-to route on the overlay

constexpr size_t kConGWin       = 0x23D94;   // the Console's GraphicWin member (vtable 0x66EC18)
constexpr size_t kConFlags      = 0x1DD70;   // bit 0x40000 = base-route window
constexpr size_t kConMapWinIdx  = 0x1DD78;   // 0 = the main map
constexpr size_t kConDragActive = 0x1DD80;
constexpr size_t kConCenterX    = 0x1DD9C;   // map view centre tile (+4 y)
constexpr size_t kConPixelLeft  = 0x1DDAC;   // sub-tile pixel offset (+4 top): PRACX's pixel scroll moves these
constexpr size_t kConLastTileX  = 0x1DE0C;   // last drawn drag tile (x; y at +4), -1 = none
constexpr size_t kConCursorSpr  = 0x1EF4C;   // current cursor sprite
constexpr size_t kConPaintMode  = 0x1DD8C;   // scenario editor terrain-paint drag: 1 left / 2 right, 0 idle (editor_paint_mode)
// The mouse-capture globals Win_get_mouse_window 0x5F6F10 consults BEFORE its window walk: while g_sb_track_win
// names a shown window, every mouse event is that window's. A scenario-editor paint press (MapWin_on_left_down
// 0x46EE73 / _right_down 0x46ECC9) sets it to the map, exactly as go_timer does for a drag, but the paint release
// never clears it: go_reset 0x50EF50 releases only a map that is dragging or armed (0x50EF93..0x50EFAA), and
// MapWin_click's paint consumption (0x46D958) does not touch it. Vanilla gets the HUD back by accident -- the next
// unit drag's go_reset, or any modal popup (Win_set_modal 0x5EE1C8) -- and with the Modern Control Set there is
// no left drag-to-move, so after a paint stroke the HUD and its palette stayed dead (user 2026-10-14, traced
// with hook_editorhud.js). The map's Win vtbl+0x10 "track end" is go_reset itself (0x51DE30 -> 0x46EB90 -> jmp).
constexpr uintptr_t kVA_TrackWin   = 0x9B7ABC;   // g_sb_track_win
constexpr uintptr_t kVA_TrackPhase = 0x9B7AC0;   // g_sb_track_phase (go_reset / FlatButton release zero it when it names the window)
constexpr size_t    kSlotTrackEnd  = 0x10;       // Win vtbl+0x10: what every engine release path calls after clearing the capture
// The palette's selected-button highlight: Console_editor_paints 0x4E0A50 maps a mode back to its button id through
// the mode table 0x691888 (19 entries of 0x20 B, first dword 0 = absent in this game) only for modes 6..25
// (`cmp esi,0x1A; jge` @0x4E0A86); modes 26..29 -- the right column's rows 2..5, real paint modes in MapWin_editor --
// take the raw `esi+0x3F3`, an id no button carries, so their highlight never sticks (vanilla; user 2026-10-14).
// MainWinIface_on_event's id->mode expansion (0x45CCF6..0x45CD1A) has no such bound. Raising the bound to 0x1E
// (30, past the last mode 0x1D) runs the same compression for them: 26 -> 0x408 .. 29 -> 0x40B, the buttons pressed.
constexpr uintptr_t kVA_PaintsBound = 0x4E0A86;  // cmp esi,0x1A; jge +0x28
const BYTE kPaintsBoundBytes[5] = { 0x83, 0xFE, 0x1A, 0x7D, 0x28 };
constexpr BYTE kPaintsBoundNew = 0x1E;
constexpr uint32_t kGameStateEditorOnly = 0x8000000;   // GameState: "Editor Only" mode (Ctrl+Shift+F10), Console_edit_lock's second arm
constexpr uintptr_t kVA_GotoCursorSpr = 0x93AA9C;   // the go-to target cursor go_timer installs
constexpr size_t kWinFlags2     = 0x9C;      // Win: bit0 = shown
constexpr size_t kVehStride = 0x34, kVehFlags = 0x4, kVehFaction = 0xE, kVehOrder = 0x11, kVehSave0 = 0x12, kVehSaveLen = 0x12;
constexpr int    kMaxVehHard = 8192;         // Thinker's enlarged array

// ---- byte sites (pristine bytes; every one is memcmp'd at Install, nothing is written on a mismatch) -------
// S1: MapWin_on_left_down's Shift branch after `call GetKeyState(VK_SHIFT)` (0x46EF8A, 27 B); `push 3` @0x46EF9B
// (6A 03 = go_timer(3) at once) becomes `jmp 0x46EFD8` (EB 3B = the epilogue: Shift arms nothing, in every mode).
constexpr uintptr_t kVA_ShiftSite = 0x46EF8A;
constexpr size_t    kShiftLen = 27, kOffPush3 = 0x46EF9B - 0x46EF8A;
const BYTE kShiftBytes[kShiftLen] = {
    0x33, 0xC9, 0x8A, 0xCC, 0x84, 0xC9, 0x74, 0x1C,
    0xF6, 0x05, 0xC0, 0x64, 0x9A, 0x00, 0x40, 0x75, 0x13,
    0x6A, 0x03, 0xE8, 0xCE, 0x01, 0x0A, 0x00, 0x83, 0xC4, 0x04,
};
const BYTE kJmpOut[2] = { 0xEB, 0x3B };
// S2: the right-click menu gate (27 B); its first instruction `mov eax,[0x9A6494]` becomes `jmp GateTramp`.
constexpr uintptr_t kVA_Gate = 0x46E529, kVA_GateResume = 0x46E52E, kVA_InlineGoto = 0x46DF0E;
constexpr size_t    kGateLen = 27;
const BYTE kGateBytes[kGateLen] = {
    0xA1, 0x94, 0x64, 0x9A, 0x00,  0xBF, 0x01, 0x00, 0x00, 0x00,  0xF6, 0xC4, 0x01,  0x75, 0x0C,
    0x39, 0xBE, 0x78, 0xDD, 0x01, 0x00,  0x0F, 0x85, 0x9A, 0x00, 0x00, 0x00,
};
const BYTE kInlineBytes[9] = { 0x8B, 0x96, 0x84, 0xDD, 0x01, 0x00, 0x83, 0xCF, 0xFF };
// S3: the left/right split (11 B): `mov eax,[ebp+0x10]; test eax,eax; jz 0x46E5E6` becomes `jmp SplitTramp` + 6 nops.
// Exits: 0x46E378 (the engine's right branch), 0x46E5E6 (the plain click), 0x46E544 (ControlTurnC check -> the
// menu; the engine arrives there with EDI = 1), 0x46E463 ('Move cursor to here': set_view([ebp+0x10]) + set_cursor
// + set_center).
constexpr uintptr_t kVA_Split = 0x46E36D, kVA_SplitRight = 0x46E378, kVA_SplitLeft = 0x46E5E6, kVA_SplitMenu = 0x46E544,
                    kVA_SplitCursor = 0x46E463;
constexpr size_t    kSplitLen = 11;
const BYTE kSplitBytes[kSplitLen] = { 0x8B, 0x45, 0x10, 0x85, 0xC0, 0x0F, 0x84, 0x6E, 0x02, 0x00, 0x00 };
const BYTE kSplitRightBytes[8] = { 0x6A, 0x10, 0xFF, 0x15, 0x30, 0x93, 0x66, 0x00 };   // push 0x10; call [GetAsyncKeyState]
const BYTE kSplitLeftBytes[5]  = { 0xBF, 0x01, 0x00, 0x00, 0x00 };                     // mov edi,1
const BYTE kSplitMenuBytes[13] = { 0xA1, 0x38, 0xA9, 0x93, 0x00, 0x85, 0xC0, 0x0F, 0x85, 0x8D, 0x00, 0x00, 0x00 };
const BYTE kSplitCursorBytes[14] = { 0x8B, 0x45, 0x10, 0xB9, 0xB0, 0x56, 0x91, 0x00, 0x50, 0xE8, 0x0F, 0x30, 0x0A, 0x00 };
// S4: the vtable entries we wrap (the thunk each slot must hold) and the thunk prologue.
constexpr size_t kSlotMove = 0x44, kSlotLeave = 0x48, kSlotLeftDown = 0x50, kSlotLeftClick = 0x4C,
                 kSlotRightClick = 0x58, kSlotRightDown = 0x5C;
constexpr uintptr_t kThunkMove = 0x51DE70, kThunkLeftClick = 0x51DE80, kThunkLeftDown = 0x51DE90,
                    kThunkRightClick = 0x51DEB0, kThunkRightDown = 0x51DEC0, kLeaveStub = 0x404260;
const BYTE kThunkPrologue[10] = { 0x2B, 0x49, 0xFC, 0x81, 0xE9, 0x28, 0x23, 0x00, 0x00, 0xE9 };
// S5: the status window's overlay calls (E8 rel32): draw_my_dest @0x4B5D95 and Win_hide(overlay) @0x4B5DC2.
constexpr uintptr_t kVA_StatusDrawDest = 0x4B5D95, kVA_StatusHide = 0x4B5DC2;
const BYTE kStatusDrawDestBytes[5] = { 0xE8, 0x56, 0xEE, 0xFF, 0xFF };
const BYTE kStatusHideBytes[10]    = { 0xB9, 0x18, 0x71, 0x93, 0x00, 0xE8, 0x09, 0x7F, 0x13, 0x00 };   // mov ecx,overlay; call Win_hide
// MapWin_set_center 0x46B1F0 clears the overlay (GraphicWin_clear(overlay, 9) @0x46B2A5) and redraws the route
// (draw_my_dest(veh) @0x46B2F2, which hides the overlay when the unit has none). A recentre animation after Tab
// calls set_center step by step, so the hover line vanished every ~300 ms until the re-post throttle let it
// back (traced 2026-10-10). Both calls stand aside while the hover owns the overlay, like the StatusWin pair.
constexpr uintptr_t kVA_CenterClear = 0x46B2A5, kVA_CenterDest = 0x46B2F2;
const BYTE kCenterClearBytes[12] = { 0x6A, 0x09, 0xB9, 0x18, 0x71, 0x93, 0x00, 0xE8, 0xA6, 0x9F, 0x16, 0x00 };   // push 9; mov ecx,overlay; call GraphicWin_clear  (@0x46B29E)
const BYTE kCenterDestBytes[5]   = { 0xE8, 0xF9, 0x98, 0x04, 0x00 };                                               // call draw_my_dest
// go_timer's view-mode unit rule, which PickUnit ports: its veh_find / veh_selectable calls.
const BYTE kGoTimerFind[5] = { 0xE8, 0x15, 0x1A, 0x0B, 0x00 };   // 0x50F296 call veh_find
const BYTE kGoTimerSel[5]  = { 0xE8, 0x72, 0x27, 0x0B, 0x00 };   // 0x50F2A9 call veh_selectable
const BYTE kVehSelOperandBytes[3] = { 0x0F, 0xBF, 0x90 };         // movsx edx, word ptr [eax + disp32]
// S6 (camera options, their own availability): MapWin_set_center's entry (push ebp; mov ebp,esp; push ecx; push
// ebx = 5 B -> `jmp StubSetCenter`, resume 0x46B1F5) and the base screen's two closing `call Console_center`
// sites (-> a stub that skips the recentre when the option is on): BaseWin_exit @0x41A600 (cursor near the edge)
// and BaseWin_on_button_clicked @0x41D6A3 (the close button, move mode, selected unit 2+ tiles off screen).
// Console_center 0x515400 = set_center(map cursor, 1). BaseWin_base_killed's own call 0x41A791 is not a close.
constexpr uintptr_t kVA_SetCenter = 0x46B1F0, kVA_SetCenterResume = 0x46B1F5;
const BYTE kSetCenterBytes[5] = { 0x55, 0x8B, 0xEC, 0x51, 0x53 };
constexpr uintptr_t kVA_BaseExitCenter = 0x41A600, kVA_BaseButtonCenter = 0x41D6A3, kVA_ConsoleCenter = 0x515400;
const BYTE kBaseExitCenterBytes[5] = { 0xE8, 0xFB, 0xAD, 0x0F, 0x00 };
const BYTE kBaseButtonCenterBytes[5] = { 0xE8, 0x58, 0x7D, 0x0F, 0x00 };
const BYTE kConsoleCenterBytes[7] = { 0xA1, 0xB8, 0x92, 0x93, 0x00, 0x6A, 0x01 };   // mov eax,[cursor idx]; push 1

// ---- state ------------------------------------------------------------------------------------------------
bool g_available = false;
bool g_shiftOk = false;
bool g_pickOk = false;           // P then right click completes the pick (PickSitesOk)
bool g_pickByRight = false;      // set only around PickByRight's own left click: that one EXECUTES the pick
bool PickCancelByLeft(BYTE* gw, void* edx, int x, int y);
int  g_on = kModernControlsDefault;
int  g_rightDrag = kRightClickDragDefault;
int  g_dragBtn = kMapDragButtonDefault;
bool g_hoverOwned = false;        // the hover line owns the overlay (shown it, or took it over)
bool g_inForward = false;         // inside the hover's forward to the engine's mouse_move
bool g_movePosted = false;        // a synthetic WM_MOUSEMOVE is queued (refresh / teardown)
DWORD g_movePostedAt = 0;         // when; the latch expires after 500 ms (a move another window consumed never clears it)
int*  g_hoverTries = nullptr;     // ModernCtlPoll's "posts owed after a unit change" counter, zeroed when the wrapper runs
int  g_hoverOrigin[4] = { 0, 0, 0, 0 };   // map centre + pixel offsets the line was last drawn for
BYTE* g_vehs = nullptr;           // the live unit array (stock 0x952828, or Thinker's)
bool g_camOk = false;             // the camera sites checked out and are detoured
int  g_clickKeepsView = kClickKeepsViewDefault;
int  g_baseKeepsView = kBaseCloseKeepsViewDefault;
bool g_inLeftClick = false;       // inside the map's left-click handler (the set_center stub reads it)
bool g_rightNotMap = false;       // inside a right release the gate says is not over the map (no move, no waypoint)

using FGwXY = void(__fastcall*)(BYTE* gw, void* edx, int x, int y);   // thiscall(this, x, y) RET 8
FGwXY g_origMove = nullptr, g_origLeave = nullptr, g_origLeftDown = nullptr, g_origLeftClick = nullptr,
      g_origRightClick = nullptr, g_origRightDown = nullptr;

// absolute targets for the naked trampolines / stubs (relocated through the load base at Install)
BYTE* g_morePrefs = nullptr;
void* g_gateGoto = nullptr;
void* g_gateResume = nullptr;
void* g_splitLeft = nullptr;
void* g_splitRight = nullptr;
void* g_splitMenu = nullptr;
void* g_splitCursor = nullptr;
void* g_drawMyDest = nullptr;
void* g_gwinClear = nullptr;
void* g_winHide = nullptr;
void* g_setCenterResume = nullptr;
void* g_consoleCenter = nullptr;

BYTE* At(uintptr_t va) { return reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (va - kImageBase); }
template <typename T> T Rd(uintptr_t va) { return *reinterpret_cast<T*>(At(va)); }
template <typename T> void Wr(uintptr_t va, T v) { *reinterpret_cast<T*>(At(va)) = v; }
template <typename T> T RdP(const BYTE* p) { T v; memcpy(&v, p, sizeof v); return v; }
template <typename T> void WrP(BYTE* p, T v) { memcpy(p, &v, sizeof v); }

void IniPath(char* out, size_t n)
{
    GetModuleFileNameA(nullptr, out, static_cast<DWORD>(n));
    char* slash = strrchr(out, '\\');
    if (slash) slash[1] = '\0';
    lstrcatA(out, "Alpha Centauri.ini");
}

BYTE* Console() { return At(kVA_Console); }
BYTE* MainGw() { return At(kVA_Console) + kConGWin; }
BYTE* Overlay() { return At(kVA_Overlay); }
bool  Editor() { return (Rd<BYTE>(kVA_GameState) & 0x40) != 0; }
bool  MapTakesInput()
{
    return Rd<int>(kVA_MapMouse) != 0 && Rd<int>(kVA_ControlTurnC) == 0 &&
           Rd<void*>(kVA_ModalTop) == nullptr && Rd<void*>(kVA_BasePop) == nullptr;
}
bool  VehOk(int v) { return v >= 0 && v < kMaxVehHard && v < Rd<int>(kVA_VehCount); }
BYTE* Veh(int v) { return g_vehs + static_cast<size_t>(v) * kVehStride; }
int   VehX(int v) { return RdP<int16_t>(Veh(v)); }
int   VehY(int v) { return RdP<int16_t>(Veh(v) + 2); }
uint32_t VehFlags(int v) { return RdP<uint32_t>(Veh(v) + kVehFlags); }
int   VehOrder(int v) { return Veh(v)[kVehOrder]; }
bool  VehOurs(int v) { return Veh(v)[kVehFaction] == static_cast<BYTE>(Rd<int>(kVA_Faction)); }
bool  VehSelectable(int v)
{
    return reinterpret_cast<int(__cdecl*)(int)>(At(kVA_VehSelectable))(v) != 0;
}
int   VehFind(int x, int y)
{
    return reinterpret_cast<int(__cdecl*)(int, int, int, int)>(At(kVA_VehFind))(x, y, Rd<int>(kVA_Faction), -1);
}
void  TimeStop(BYTE* timer) { reinterpret_cast<void(__fastcall*)(void*, void*)>(At(kVA_TimeStop))(timer, nullptr); }
void  WinShow(BYTE* w) { reinterpret_cast<void(__fastcall*)(void*, void*, int)>(At(kVA_WinShow))(w, nullptr, 0); }
void  WinHide(BYTE* w) { reinterpret_cast<void(__fastcall*)(void*, void*)>(At(kVA_WinHide))(w, nullptr); }
void  GWinClear(BYTE* w, int color) { reinterpret_cast<void(__fastcall*)(void*, void*, int)>(At(kVA_GWinClear))(w, nullptr, color); }
bool  OverlayShown() { return (RdP<int>(Overlay() + kWinFlags2) & 1) != 0; }
bool  ShiftHeld() { return (GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0; }
bool  CtrlHeld() { return (GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0; }
bool  LeftHeld() { return (GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0; }
bool  ScrollLockOn() { return (GetKeyState(VK_SCROLL) & 1) != 0; }   // the toggle, as the engine reads it (GetKeyState(0x91) & 1)
// The scenario editor's own map input, and nothing else (read from the engine 2026-10-12): a press with Ctrl+Shift,
// or with Scroll Lock on and no Ctrl, arms a terrain-paint drag (Console+0x1DD8C := 1 / 2 in MapWin_on_left_down /
// _right_down 0x46EE18 / 0x46EC74, painted by MapWin_on_mouse_move 0x46F0A0 -> MapWin_editor 0x46B510); a click
// paints the tile when MapWin_click's [ebp-0x20] is set (0x46E299: = Ctrl, except with Scroll Lock on and no Shift
// where it is !Ctrl, so Ctrl + Scroll Lock alone is an ordinary click), or when a paint drag is still armed
// (0x46D93D, before the key test); and Console_edit_lock 0x4E1F40 (Scroll Lock, or the "Editor Only" bit) blocks
// the go-to arming. The gate below is a strict superset of those conditions. A plain press, drag,
// click or right click in editor mode is the ordinary game (go_timer's mode 9 is the Ctrl drag in view mode, not
// the editor), so the Modern Control Set stands aside only while one of these is engaged. The editor bit itself
// (GameState 0x40, set by "Activate Scenario Editor" through Console_load_proc 0x51BC17 `or 0xE0`) is never
// cleared in a session and is saved with the game: the first build gated on the bit alone, which switched the
// whole set off for good -- in that game and in every save made after -- once the editor had been activated.
bool  EditorEngaged()
{
    if (!Editor()) return false;
    return CtrlHeld() || ScrollLockOn() || RdP<int>(Console() + kConPaintMode) != 0 ||
           (Rd<uint32_t>(kVA_GameState) & kGameStateEditorOnly) != 0;
}
void  ReadOrigin(int* o)
{
    const BYTE* con = Console();
    o[0] = RdP<int>(con + kConCenterX); o[1] = RdP<int>(con + kConCenterX + 4);
    o[2] = RdP<int>(con + kConPixelLeft); o[3] = RdP<int>(con + kConPixelLeft + 4);
}

// The unit the hover line, a right click and a Ctrl+right waypoint act on -- ONE rule for all three, so a
// right click can only move the unit the line is showing (user 2026-10-10). Move mode: the selected unit
// (go_timer's rule). View mode: the selected unit while it is ours, selectable, order-less AND stands on the
// map cursor tile (go_timer's own condition: once the player has looked at another square the old unit is
// not the target). Nothing is ever selected by these paths: selecting is the left click's job. The allowFind
// arm (a unit of ours on the cursor tile, then SELECTED as go_timer does) is kept for reference but no caller
// uses it any more: on 2026-10-10 it selected units near the pointer on hover and moved unshown units on a
// right click.
void DropStalePath(int v);       // the Ctrl+right waypoint section (below)

int PickUnit(bool allowFind)
{
    const int cur = Rd<int>(kVA_CurVeh);
    if (Rd<int>(kVA_MoveMode) != 0) return VehOk(cur) ? cur : -1;
    (void)allowFind;                 // the view-mode arm (the current unit on the cursor tile, else veh_find there and SELECT it,
                                     // as go_timer does) was removed 2026-10-10: in view mode nothing is selected for movement --
                                     // no line, no right-click move, no waypoint (user); viewdragfix.cpp cuts the engine's own arm
    return -1;
}

// ---- S2: right click = move (GateTramp) --------------------------------------------------------------------
// Called from GateTramp with MapWin_click's frame live: con = ESI, tile = the two locals. Returns the unit to
// move, or -1 to let the engine's own gate run (menu or cursor move, per the stock preference).
int __cdecl RightClickVeh(BYTE* con, int /*tx*/, int /*ty*/)
{
    if (!g_available || !g_on || g_rightDrag || g_rightNotMap) return -1;
    if (con != Console() || RdP<int>(con + kConMapWinIdx) != 0) return -1;
    if (EditorEngaged() || !MapTakesInput()) return -1;
    const int veh = PickUnit(false);                       // the unit the hover line shows, or nothing: a right click never SELECTS (user 2026-10-10)
    if (veh >= 0 && Rd<int>(kVA_MoveMode) == 0) {
        reinterpret_cast<void(__fastcall*)(BYTE*, void*, int)>(At(kVA_SetMove))(con, nullptr, 1);
        if (Rd<int>(kVA_MoveMode) == 0 || Rd<int>(kVA_CurVeh) != veh) return -1;   // refused / another unit: no order
    }
    DropStalePath(veh);
    return veh;
}

__declspec(naked) void GateTramp()
{
    __asm {
        push ecx
        push edx
        push dword ptr [ebp - 0x14]          // tile y
        push dword ptr [ebp - 0x10]          // tile x
        push esi                             // Console
        call RightClickVeh
        add  esp, 12
        pop  edx
        pop  ecx
        test eax, eax
        jl   passthru
        jmp  dword ptr [g_gateGoto]          // 0x46DF0E: the inline go-to, EAX = unit
    passthru:
        mov  eax, dword ptr [g_morePrefs]    // the displaced `mov eax,[GameMorePreferences]`
        mov  eax, dword ptr [eax]
        jmp  dword ptr [g_gateResume]        // 0x46E52E
    }
}

// ---- S3: the Shift clicks (SplitTramp) ----------------------------------------------------------------------
// Modern mode: Shift+RIGHT = the orders menu, Shift+LEFT = 'Move cursor to here' (user 2026-10-07; vanilla has
// them the other way round by the stock preference). Ctrl+Shift+right (info) and everything else stay vanilla.
// Returns 0 = engine's own split, 1 = menu (0x46E544, EDI must be 1 there), 2 = cursor move (0x46E463).
int __cdecl SplitRoute(BYTE* con, int is_right)
{
    if (!g_available || !g_on) return 0;
    if (con != Console() || RdP<int>(con + kConMapWinIdx) != 0) return 0;
    if (EditorEngaged() || !ShiftHeld() || CtrlHeld()) return 0;
    return is_right ? 1 : 2;
}

__declspec(naked) void SplitTramp()
{
    __asm {
        push ecx
        push edx
        push dword ptr [ebp + 0x10]          // is_right
        push esi                             // Console
        call SplitRoute
        add  esp, 8
        pop  edx
        pop  ecx
        cmp  eax, 1
        je   menu
        cmp  eax, 2
        je   cursor
        mov  eax, dword ptr [ebp + 0x10]     // the displaced test
        test eax, eax
        jz   leftpath
        jmp  dword ptr [g_splitRight]        // 0x46E378: the engine's right-click branch
    leftpath:
        jmp  dword ptr [g_splitLeft]         // 0x46E5E6: the plain click
    menu:
        mov  edi, 1                          // what the engine's path set at 0x46E52E before reaching here
        jmp  dword ptr [g_splitMenu]         // 0x46E544: ControlTurnC check -> MapWin_right_menu
    cursor:
        jmp  dword ptr [g_splitCursor]       // 0x46E463: Console_set_view([ebp+0x10]) + set_cursor + set_center
    }
}

// ---- S5: the status window's overlay calls stand aside while the hover line owns the overlay ------------
__declspec(naked) void StubDrawMyDest()      // cdecl(veh): the caller pops the argument
{
    __asm {
        cmp  byte ptr [g_hoverOwned], 0
        jne  skip
        jmp  dword ptr [g_drawMyDest]
    skip:
        ret
    }
}

__declspec(naked) void StubOverlayHide()     // thiscall(ecx = the overlay)
{
    __asm {
        cmp  byte ptr [g_hoverOwned], 0
        jne  skip
        jmp  dword ptr [g_winHide]
    skip:
        ret
    }
}

__declspec(naked) void StubOverlayClear()    // thiscall(ecx = the overlay, color) RET 4: MapWin_set_center's clear
{
    __asm {
        cmp  byte ptr [g_hoverOwned], 0
        jne  skip
        jmp  dword ptr [g_gwinClear]
    skip:
        ret  4
    }
}

// ---- S6: the camera options ---------------------------------------------------------------------------------
// MapWin_set_center(x, y, flag) called from inside the map's left-click handler with the option on keeps the view
// (StubSetCenter then passes this map's CURRENT centre, so the engine skips only its redraw; TutWin_reset and the
// route-overlay repaint still run):
// every such call targets the clicked tile (the four MapWin_click sites, Console_activate's focus), which is on
// screen by definition -- including a base half off the edge, which the engine's RenderTileBounds test calls
// "off screen" (2026-10-07: an edge base still recentred under that test).
int __cdecl KeepView(int, int)
{
    return g_clickKeepsView && g_inLeftClick ? 1 : 0;
}

__declspec(naked) void StubSetCenter()       // thiscall(this, x, y, flag) RET 0xC; entered by the jmp at 0x46B1F0
{
    __asm {
        cmp  byte ptr [g_inLeftClick], 0
        je   orig
        push ecx
        push edx
        push dword ptr [esp + 0x10]          // y   ([esp+8] before the two pushes)
        push dword ptr [esp + 0x10]          // x   ([esp+4] before the pushes, +0xC after two, +0x10 after three)
        call KeepView
        add  esp, 8
        pop  edx
        pop  ecx
        test eax, eax
        jz   orig
        mov  eax, dword ptr [ecx + 0x1DD9C]  // this->centre x (stored wrapped, legal parity)
        mov  dword ptr [esp + 4], eax
        mov  eax, dword ptr [ecx + 0x1DDA0]  // this->centre y
        mov  dword ptr [esp + 8], eax
    orig:
        push ebp                             // the five displaced bytes
        mov  ebp, esp
        push ecx
        push ebx
        jmp  dword ptr [g_setCenterResume]   // 0x46B1F5
    }
}

__declspec(naked) void StubBaseCenter()      // in place of both closing `call Console_center` sites (no args)
{
    __asm {
        cmp  byte ptr [g_baseKeepsView], 0
        jne  skip
        jmp  dword ptr [g_consoleCenter]
    skip:
        ret
    }
}

// After a release on the map: a capture the map still holds with nothing dragging or armed is a paint press's
// (see kVA_TrackWin); release it the way go_reset releases a drag's -- clear, then the window's track-end slot.
void ReleasePaintCapture(BYTE* gw)
{
    if (!Editor() || Rd<BYTE*>(kVA_TrackWin) != gw) return;
    const BYTE* con = Console();
    if (RdP<int>(con + kConPaintMode) != 0 || RdP<int>(con + kConDragActive) != 0 || Rd<int>(kVA_GoWinIdx) >= 0) return;
    Wr<BYTE*>(kVA_TrackWin, nullptr);
    reinterpret_cast<void(__fastcall*)(BYTE*, void*)>(RdP<BYTE*>(RdP<BYTE*>(gw) + kSlotTrackEnd))(gw, nullptr);
    if (Rd<BYTE*>(kVA_TrackPhase) == gw) Wr<BYTE*>(kVA_TrackPhase, nullptr);
}

// vtbl+0x4C: the left click (release) -- brackets MapWin_click so the set_center stub knows the caller.
void __fastcall LeftClickWrap(BYTE* gw, void* edx, int x, int y)
{
    if (gw != MainGw()) { g_origLeftClick(gw, edx, x, y); return; }
    if (PickCancelByLeft(gw, edx, x, y)) { ReleasePaintCapture(gw); return; }
    const bool outer = g_inLeftClick;
    g_inLeftClick = true;
    g_origLeftClick(gw, edx, x, y);
    g_inLeftClick = outer;
    ReleasePaintCapture(gw);
}

// ---- the hover line ---------------------------------------------------------------------------------------
void HoverDbg(const char* what, int extra = 0);   // DebugLog=1 diagnostics (defined below HoverMouseMove)

void HoverTeardown()
{
    if (!g_hoverOwned) return;
    HoverDbg("teardown");
    BYTE* con = Console();
    if (RdP<int>(con + kConDragActive) == 0 && OverlayShown()) WinHide(Overlay());
    WrP<int>(con + kConLastTileX, -1);
    g_hoverOwned = false;
}

// A synthetic WM_MOUSEMOVE at the pointer: the wrapper then redraws (origin changed, overlay hidden) or tears
// down (the map stopped taking input) from the engine's own dispatch context -- never from inside the pump.
void PostPointerMove()
{
    // the latch is cleared by the map wrapper when the posted move reaches it; a move another window consumed
    // would otherwise block every later re-post, so the latch expires after half a second instead (2026-10-10:
    // clearing it on every dequeued mouse move re-posted from the same poll pass -- an endless storm on Tab)
    if (g_movePosted && GetTickCount() - g_movePostedAt < 500) { HoverDbg("post-throttled"); return; }
    HoverDbg("post");
    HWND hwnd = Rd<HWND>(kVA_MainHwnd);
    POINT p;
    if (!hwnd || !GetCursorPos(&p) || !ScreenToClient(hwnd, &p)) return;
    // a 1-px nudge first, then the true position: a dispatcher that ignores an unchanged position still sees a
    // change, and the second message leaves the engine's idea of the pointer where it really is
    PostMessageA(hwnd, WM_MOUSEMOVE, 0, MAKELPARAM(p.x + 1, p.y));
    if (PostMessageA(hwnd, WM_MOUSEMOVE, 0, MAKELPARAM(p.x, p.y))) { g_movePosted = true; g_movePostedAt = GetTickCount(); }
}

// A window's origin: what Win_get_mouse_window subtracts from the raw point to make it local (see kVA_MouseRawX).
mapgate::Pt WinOrigin(const BYTE* w)
{
    return { RdP<int>(w + kWinOrgX0) + RdP<int>(w + kWinOrgX1), RdP<int>(w + kWinOrgY0) + RdP<int>(w + kWinOrgY1) };
}

bool WinShown(const BYTE* w) { return (RdP<int>(w + kWinFlags2) & 1) != 0; }

// A shown TOP-LEVEL window's screen rect (a parent-relative one would need the parent chain: false).
bool WinScreenRect(const BYTE* w, mapgate::Rect* r)
{
    if (!WinShown(w) || (RdP<uint32_t>(w + kWinStyle) & 0x20)) return false;
    const int* r1 = reinterpret_cast<const int*>(w + kWinRect1);
    const int* r2 = reinterpret_cast<const int*>(w + kWinRect2);
    if (RdP<int>(w + kWinFlags2) & 2) *r = { r2[0], r2[1], r2[2], r2[3] };          // the frame's position (client inside it)
    else *r = { r1[0] + r2[0], r1[1] + r2[1], r1[2] + r2[0], r1[3] + r2[1] };     // rRect2 is 0 here
    return r->l < r->r && r->t < r->b;
}

// mapgate::Blockers reads the engine's windows through these (Win +0xA8 delegate, +0x3FC / +0x1A4 children).
const void* WinDelegateOf(const void* w) { return RdP<const void*>(static_cast<const BYTE*>(w) + kWinDelegate); }
int WinChildCountOf(const void* w) { return RdP<int>(static_cast<const BYTE*>(w) + kWinChildCount); }
const void* WinChildOf(const void* w, int i) { return RdP<const void*>(static_cast<const BYTE*>(w) + kWinChildren + 4 * i); }
bool WinRectOf(const void* w, mapgate::Rect* r) { return WinScreenRect(static_cast<const BYTE*>(w), r); }
const mapgate::WinAccess kWinAccess = { WinDelegateOf, WinChildCountOf, WinChildOf, WinRectOf };

int MapBlockers(const BYTE* gw, mapgate::Rect* out, const void** who, int* mapIdx)
{
    int count = Rd<int>(kVA_TopWindowCount);
    if (count < 0) count = 0;
    if (count > 256) count = 256;
    return mapgate::Blockers(kWinAccess, reinterpret_cast<const void* const*>(At(kVA_TopWindows)), count, gw,
                             At(kVA_MainWin), Overlay(), At(kVA_TutWin), out, who, kMaxBlockers, mapIdx);
}

// DebugLog=1: one line whenever the gate's answer (or the window it names) changes -- the in-game check of the
// strip band and of what blocks (LastMouseWin, local, raw, strip rect, map's list index, blocker).
void GateDbg(const BYTE* gw, int x, int y, mapgate::Verdict v, const void* blocker, int mapIdx)
{
    static int lastV = -1, lastIdx = -2;
    static const void* lastB = nullptr;
    if (static_cast<int>(v) == lastV && blocker == lastB && mapIdx == lastIdx) return;
    lastV = static_cast<int>(v); lastB = blocker; lastIdx = mapIdx;
    mapgate::Rect sr = { 0, 0, 0, 0 };
    WinScreenRect(At(kVA_MainWin), &sr);
    char m[300];
    _snprintf_s(m, sizeof m, _TRUNCATE,
                "[uimod] mapgate: verdict %d (0 not map, 1 map-local, 2 rebuilt) last %p gw %p local %d,%d raw %d,%d "
                "strip %d,%d-%d,%d mapIdx %d/%d blocker %p\n",
                static_cast<int>(v), Rd<const void*>(kVA_LastMouseWin), static_cast<const void*>(gw), x, y,
                Rd<int>(kVA_MouseRawX), Rd<int>(kVA_MouseRawY), sr.l, sr.t, sr.r, sr.b, mapIdx,
                Rd<int>(kVA_TopWindowCount), blocker);
    UimodDbg(m);
}

mapgate::Verdict MapPointVerdict(const BYTE* gw, int x, int y)
{
    mapgate::Rect blockers[kMaxBlockers];
    const void* who[kMaxBlockers];
    int mapIdx;
    const int nb = MapBlockers(gw, blockers, who, &mapIdx);
    int hit;
    const mapgate::Verdict v =
        mapgate::Gate({ x, y }, { Rd<int>(kVA_MouseRawX), Rd<int>(kVA_MouseRawY) }, WinOrigin(gw), blockers, nb, &hit);
    GateDbg(gw, x, y, v, hit >= 0 ? who[hit] : nullptr, mapIdx);
    return v;
}

// A move/press the engine resolved to the MAP: not the map's when the raw point is over a window above it (false);
// otherwise the map's, with its coordinates rebuilt from the raw point when they are not map-local (the strip band).
bool FixMapPoint(const BYTE* gw, int& x, int& y)
{
    if (Rd<const BYTE*>(kVA_LastMouseWin) != gw) return false;
    const mapgate::Verdict v = MapPointVerdict(gw, x, y);
    if (v == mapgate::kMapRebuilt) {
        const mapgate::Pt o = WinOrigin(gw);
        x = Rd<int>(kVA_MouseRawX) - o.x;
        y = Rd<int>(kVA_MouseRawY) - o.y;
    }
    return v != mapgate::kNotMap;
}

// vtbl+0x44: with a unit selected and the map live, run the engine's own drag-line painter for this move.
// DebugLog=1 diagnostics for the hover line's re-post path (2026-10-10: a ~0.5 s delay after Tab)
void HoverDbg(const char* what, int extra)
{
    static bool on = false, known = false;
    if (!known) { known = true; char ini[MAX_PATH]; IniPath(ini, sizeof ini); on = GetPrivateProfileIntA("UIMod", "DebugLog", 0, ini) != 0; }
    if (!on) return;
    char m[256];
    _snprintf_s(m, sizeof m, _TRUNCATE, "[uimod] hover[%lu] %s %d: veh %d mode %d takes %d shown %d owned %d posted %d drag %d\n",
                static_cast<unsigned long>(GetTickCount()), what, extra, Rd<int>(kVA_CurVeh), Rd<int>(kVA_MoveMode),
                MapTakesInput() ? 1 : 0, OverlayShown() ? 1 : 0, g_hoverOwned ? 1 : 0, g_movePosted ? 1 : 0,
                RdP<int>(Console() + kConDragActive));
    UimodDbg(m);
}

void __fastcall HoverMouseMove(BYTE* gw, void* edx, int x, int y)
{
    g_movePosted = false;
    if (gw == MainGw() && !g_inForward) {
        HoverDbg("move", x);
        if (g_hoverTries) *g_hoverTries = 0;              // the wrapper ran for the current unit: no more posts owed
    }
    if (gw != MainGw() || g_inForward) { g_origMove(gw, edx, x, y); return; }
    BYTE* con = Console();
    if (RdP<int>(con + kConDragActive) != 0) {           // the engine's own drag (hold timer fired)
        g_hoverOwned = false;
        g_origMove(gw, edx, x, y);
        return;
    }
    int veh = -1;
    int mx = x, my = y;
    const bool want = g_on && !g_rightDrag && MapTakesInput() && !EditorEngaged() && Rd<int>(kVA_PbemActive) == 0 &&
                      Rd<int>(kVA_SelMode) == 0 && FixMapPoint(gw, mx, my) && (veh = PickUnit(false)) >= 0;  // never SELECTS on hover: only the current unit, and only while it stands on the cursor tile (user 2026-10-10: a find here selected units near the pointer)
    if (!want) {
        HoverDbg("no-want", veh);
        HoverTeardown();
        g_origMove(gw, edx, x, y);
        return;
    }
    HoverDbg("draw", veh);
    DropStalePath(veh);
    BYTE saved[kVehSaveLen];
    memcpy(saved, Veh(veh) + kVehSave0, kVehSaveLen);
    int origin[4];
    ReadOrigin(origin);
    if (!OverlayShown()) {                                // what go_timer does when a drag starts
        GWinClear(Overlay(), 9);
        WinShow(Overlay());
        WrP<int>(con + kConLastTileX, -1);
    } else if (memcmp(origin, g_hoverOrigin, sizeof origin) != 0) {
        WrP<int>(con + kConLastTileX, -1);                // the map moved under the line: redraw this tile
    }
    memcpy(g_hoverOrigin, origin, sizeof origin);
    g_hoverOwned = true;
    g_inForward = true;
    WrP<int>(con + kConDragActive, 1);
    Wr<int>(kVA_SelMode, 1);
    g_origMove(gw, edx, mx, my);
    WrP<int>(con + kConDragActive, 0);
    Wr<int>(kVA_SelMode, 0);
    g_inForward = false;
    if (Rd<int>(kVA_CurVeh) == veh) memcpy(Veh(veh) + kVehSave0, saved, kVehSaveLen);
    else UimodDbg("[uimod] modernctl: hover: the selected unit changed inside mouse_move (waypoints not restored)\n");
}

// vtbl+0x48: the pointer left the map window (Win_OnMouseMove calls this on a mouse-window change).
void __fastcall LeaveWrap(BYTE* gw, void* edx, int x, int y)
{
    if (gw == MainGw() && !g_inForward) HoverTeardown();
    g_origLeave(gw, edx, x, y);
}

// vtbl+0x50: a left press. Modern mode has no left drag-to-move: undo the arming the engine just did. The base-route
// window's drag and the Ctrl rally drag are not unit moves: kept. The scenario editor's paint drag never arms the
// timer (g_go_win_idx stays -1), and its plain drag is the ordinary go-to drag (go_timer has no editor arm).
void __fastcall LeftDownWrap(BYTE* gw, void* edx, int x, int y)
{
    g_origLeftDown(gw, edx, x, y);
    if (!g_on || gw != MainGw() || Rd<int>(kVA_GoWinIdx) < 0) return;
    if (EditorEngaged() || CtrlHeld() || (RdP<uint32_t>(Console() + kConFlags) & 0x40000)) return;
    TimeStop(At(kVA_GoTimer));
    Wr<int>(kVA_GoWinIdx, -1);
}

// vtbl+0x5C: a right press. With the right-drag option, arm the hold timer exactly as a left press would.
void __fastcall RightDownWrap(BYTE* gw, void* edx, int x, int y)
{
    g_origRightDown(gw, edx, x, y);
    if (!(g_on && g_rightDrag) || gw != MainGw()) return;
    if (!MapTakesInput() || EditorEngaged() || Rd<int>(kVA_SelMode) != 0) return;   // EditorEngaged sees the paint drag the press just armed
    if (!FixMapPoint(gw, x, y)) return;
    g_origLeftDown(gw, edx, x, y);
}

// A target pick armed from a key or menu (Console_set_selecting 0x510490: 2/3 0x4D7CE3, 4 0x4D89B9, 8 patrol 0x4D7F55,
// 0xA 0x4D928D, 0xB 0x4D8CBD) -- not go_timer's drags (1 / 9, written directly at 0x50F359 / 0x50F5F3).
bool PickArmed()
{
    const int m = Rd<int>(kVA_SelMode);
    return m >= kPickModeLo && m <= kPickModeHi && m != kSelModeCtrlDrag;
}

// Modern mode orders with the right button, so a right release on the map completes an armed pick (P then right
// click = patrol) through the engine's own LEFT click: MapWin_click takes the mode (0x5107E0), and its left path
// runs the pick (0x46E11F, the 2..11 table at 0x46EB68) while a right release only drops it (0x46D7F1 -> 0x46EAC4).
// The right PRESS arms nothing while a pick is armed (MapWin_on_right_down 0x46EC62 -> 0x46ED1A). A left click
// cancels (PickCancelByLeft). Not on the map (a window above it), the editor's paint input, or the map not taking input: the
// engine's own right click, which cancels the pick as in vanilla.
bool PickByRight(BYTE* gw, void* edx, int x, int y)
{
    if (!g_available || !g_on || gw != MainGw()) return false;
    if (!g_pickOk || !PickArmed() || EditorEngaged() || !MapTakesInput() || RdP<int>(Console() + kConMapWinIdx) != 0) return false;
    if (!FixMapPoint(gw, x, y)) return false;
    const bool outer = g_pickByRight;
    g_pickByRight = true;
    LeftClickWrap(gw, edx, x, y);
    g_pickByRight = outer;
    return true;
}

// Modern mode orders with the RIGHT button only (user 2026-10-15): a left click on the map while a pick is armed
// (patrol 8, bomb run 0xB, airdrop 4, artillery 0xA, road / tube to 2 / 3) CANCELS it, the way a vanilla right
// release does -- Console_selected 0x5107E0 takes the mode and restores the arrow on every map window -- and the
// click goes no further (vanilla's left would run the pick at 0x46E11F). Not PickByRight's own click, not the
// editor's paint input, not a map other than the main one, not Classic.
// The cancel is the engine's OWN right release (vtbl+0x58 original): MapWin_click(is_right) runs its pre-steps
// (TutWin / StatusWin / ...), go_reset 0x50EF50 -- which undoes what a PRESS armed while the pick was set: patrol's
// press (0x46ED98) arms a drag +0x1DD80, captures the mouse g_sb_track_win and draws the patrol line on the overlay --
// then takes the mode (Console_selected 0x5107E0) and, being a right release, drops it (0x46D807 -> 0x46EAC4): exactly
// vanilla's right-click cancel (audit 2026-10-15: Console_selected alone left patrol's drag, line and capture behind).
bool PickCancelByLeft(BYTE* gw, void* edx, int x, int y)
{
    if (g_pickByRight || !g_available || !g_on || !g_pickOk || gw != MainGw()) return false;
    if (!PickArmed() || EditorEngaged() || RdP<int>(Console() + kConMapWinIdx) != 0) return false;
    g_origRightClick(gw, edx, x, y);
    return true;
}

// ---- Ctrl+right: add a waypoint (Modern instant mode) --------------------------------------------------------
int g_wpVeh = -1;                 // the unit collecting waypoints we started (none = -1)
int16_t g_wpUnitId = 0, g_wpX = 0, g_wpY = 0;   // its identity: an index alone survives a load / unit compaction
BYTE g_wpFaction = 0;

void RememberWpVeh(int v)
{
    g_wpVeh = v;
    g_wpUnitId = RdP<int16_t>(Veh(v) + kVehUnitId);
    g_wpX = RdP<int16_t>(Veh(v) + 0);
    g_wpY = RdP<int16_t>(Veh(v) + 2);
    g_wpFaction = Veh(v)[kVehFaction];
}

// g_wpVeh still names the unit we started the path on (same slot, same unit, same tile: it has no order).
bool WpVehIsOurs()
{
    const int v = g_wpVeh;
    return VehOk(v) && RdP<int16_t>(Veh(v) + kVehUnitId) == g_wpUnitId && Veh(v)[kVehFaction] == g_wpFaction &&
           RdP<int16_t>(Veh(v) + 0) == g_wpX && RdP<int16_t>(Veh(v) + 2) == g_wpY;
}

// Strips a collecting flag and its slots from a unit (never a committed path: that belongs to its order).
void StripPath(int v)
{
    const uint32_t f = VehFlags(v);
    WrP<uint32_t>(Veh(v) + kVehFlags, f & ~kVehWaypointFlag);
    Veh(v)[kVehWpCount] = 0;
    Veh(v)[kVehWpAux] = 0;
}

// Drops the path we were collecting, if it is still ours and was never committed.
void ClearPendingWaypoints()
{
    const bool ours = g_wpVeh >= 0 && WpVehIsOurs();
    const int v = g_wpVeh;
    g_wpVeh = -1;
    if (ours && VehOrder(v) == 0 && (VehFlags(v) & kVehWaypointFlag)) StripPath(v);
}

// A collecting flag on a unit with no order that is not OUR pending path is stale (a save made mid-path, a go-to
// the engine interrupted, a path abandoned another way): the hover line, a Ctrl+right or a plain right click on
// that unit would otherwise route through the old points. Modern instant mode never has an engine drag that
// could own it.
void DropStalePath(int v)
{
    if (!VehOk(v) || VehOrder(v) != 0 || !(VehFlags(v) & kVehWaypointFlag)) return;
    if (g_wpVeh == v && WpVehIsOurs()) return;
    StripPath(v);
}

// Per message: forget a committed path; drop ours when the unit changed, another order replaced it, an engine
// drag / pending cursor action started, or the mode went away.
void WaypointHousekeeping()
{
    if (g_wpVeh < 0) return;
    if (!WpVehIsOurs()) { g_wpVeh = -1; return; }                    // load / compaction: not ours any more
    const int v = g_wpVeh;
    if (VehOrder(v) != 0) {
        const bool committed = VehOrder(v) == kVehOrderGoTo && (VehFlags(v) & kVehPathCommitted) == kVehPathCommitted;
        if (!committed) StripPath(v);                                 // menu go-to, sentry, hold...: not this path
        g_wpVeh = -1;
        return;
    }
    if (Rd<int>(kVA_CurVeh) != v || !g_on || g_rightDrag || Rd<int>(kVA_SelMode) != 0 ||
        (RdP<int>(Console() + kConDragActive) != 0 && !g_inForward))
        ClearPendingWaypoints();
}

// A right release with Ctrl (no Shift) in Modern instant mode: fix the clicked tile as the next waypoint. Returns
// false to let the release run as an ordinary right click (no unit). With the slots full (the engine's cap: 3
// waypoints + the destination, saved in the unit record) the click is swallowed, so only a plain right click
// commits the path.
bool AddWaypoint(BYTE* gw, int x, int y)
{
    if (!g_available || !g_on || g_rightDrag || gw != MainGw()) return false;
    if (!(GetKeyState(VK_CONTROL) & 0x8000) || (GetKeyState(VK_SHIFT) & 0x8000)) return false;
    BYTE* con = Console();
    if (RdP<int>(con + kConMapWinIdx) != 0 || EditorEngaged() || !MapTakesInput() || Rd<int>(kVA_PbemActive) != 0 ||   // Ctrl is held here: in editor mode Ctrl+click paints, so no waypoints there
        Rd<int>(kVA_MultiplayerActive) != 0 || Rd<int>(kVA_SelMode) != 0)
        return false;
    int tx = -1, ty = -1;
    if (reinterpret_cast<int(__fastcall*)(BYTE*, void*, int, int, int*, int*)>(At(kVA_PixelToTile))(con, nullptr, x, y, &tx, &ty) != 0)
        return true;                                       // off the map: nothing to add, nothing to order
    const int veh = PickUnit(false);                       // the unit the hover line shows, or nothing: a right click never SELECTS (user 2026-10-10)
    if (veh < 0) return false;
    if (Rd<int>(kVA_MoveMode) == 0) {                      // as RightClickVeh: move mode first (keeps the unit)
        reinterpret_cast<void(__fastcall*)(BYTE*, void*, int)>(At(kVA_SetMove))(con, nullptr, 1);
        if (Rd<int>(kVA_MoveMode) == 0 || Rd<int>(kVA_CurVeh) != veh) return true;
    }
    if (g_wpVeh != veh || !WpVehIsOurs()) {
        ClearPendingWaypoints();
        DropStalePath(veh);
    }
    BYTE* u = Veh(veh);
    const uint32_t f = VehFlags(veh);
    const int n = (f & kVehWaypointFlag) ? u[kVehWpCount] : 0;
    if (n >= kWpSlots - 1) return true;                    // full (3 waypoints + the destination is the engine's cap): the
                                                           // click is swallowed; a plain right click sets the destination (user 2026-10-10)
    const int px = n ? RdP<int16_t>(u + kVehWpX + 2 * (n - 1)) : RdP<int16_t>(u + 0);
    const int py = n ? RdP<int16_t>(u + kVehWpY + 2 * (n - 1)) : RdP<int16_t>(u + 2);
    if (px == tx && py == ty) return true;                 // the unit's own tile / the same waypoint again
    if (!(f & kVehWaypointFlag)) {
        WrP<uint32_t>(u + kVehFlags, f | kVehWaypointFlag);
        u[kVehWpAux] = 0;
    }
    WrP<int16_t>(u + kVehWpX + 2 * n, static_cast<int16_t>(tx));
    WrP<int16_t>(u + kVehWpY + 2 * n, static_cast<int16_t>(ty));
    u[kVehWpCount] = static_cast<BYTE>(n + 1);
    RememberWpVeh(veh);
    WrP<int>(con + kConLastTileX, -1);                     // redraw the line through the new waypoint
    PostPointerMove();
    return true;
}

void RightClickInner(BYTE* gw, void* edx, int x, int y);

// vtbl+0x58: a right release. With the right-drag option and a live drag, this release IS the move: run it
// through the left-click entry (MapWin_click drops a right release while the go-to cursor is set).
void __fastcall RightClickWrap(BYTE* gw, void* edx, int x, int y)
{
    if (PickByRight(gw, edx, x, y)) return;          // LeftClickWrap releases a paint capture itself
    RightClickInner(gw, edx, x, y);
    if (gw == MainGw()) ReleasePaintCapture(gw);
}

void RightClickInner(BYTE* gw, void* edx, int x, int y)
{
    // over the tutorial box (or carrying another window's coordinates): the engine's own right click, no move
    if (g_available && g_on && !g_rightDrag && gw == MainGw() && MapPointVerdict(gw, x, y) == mapgate::kNotMap) {
        const bool outer = g_rightNotMap;
        g_rightNotMap = true;
        g_origRightClick(gw, edx, x, y);
        g_rightNotMap = outer;
        return;
    }
    if (AddWaypoint(gw, x, y)) return;
    if (g_on && g_rightDrag && gw == MainGw()) {
        BYTE* con = Console();
        if (RdP<int>(con + kConDragActive) != 0 || RdP<uintptr_t>(con + kConCursorSpr) == reinterpret_cast<uintptr_t>(At(kVA_GotoCursorSpr))) {
            g_origLeftClick(gw, edx, x, y);
            return;
        }
    }
    g_origRightClick(gw, edx, x, y);
}

// ---- apply -----------------------------------------------------------------------------------------------
// Only the RIGHT button is taken away while it is the move button (user 2026-10-07: the conflict -> none); a
// stored middle keeps scrolling (PRACX's middle remap passes right messages through untouched).
bool RightIsMoveButton() { return g_available && g_on && g_rightDrag; }
int EffectiveDragButton() { return RightIsMoveButton() && g_dragBtn == kMapDragRight ? kMapDragNone : g_dragBtn; }

// ---- the tile context menu's hotkey column ----------------------------------------------------------------
// labels.txt loads into TextLabels 0x9B90F8 {char** labels; count}: one char* per label (index = file line - 11)
// into the TextTable string pool 0x9B90D8 {flags, base +4, cursor +8, size +0xC, free +0x10}. The menu shows
// "Move cursor to here|Shift+Right"; Modern mode swaps the Shift clicks (S3), so the hint must read Shift+Left
// there, and "Move unit to here" gains "|Right" in instant mode. Strings_get 0x6169A0 only validates a pointer
// against the pool, so a replacement has to live IN the pool: the shorter text overwrites in place, the longer
// one goes through Strings_put 0x616970 only while the pool's free count covers it (the allocator otherwise
// reallocs -- moves -- the pool, which would dangle every label). Unknown text (a localisation) is left alone.
constexpr uintptr_t kVA_TextLabels = 0x9B90F8, kVA_TextTable = 0x9B90D8, kVA_StringsPut = 0x616970;
constexpr size_t kPoolFree = 0x10;
constexpr int kLblMoveUnit = 557, kLblMoveCursor = 565;
const char kMoveUnitOrig[]    = "Move unit to here";
const char kMoveUnitModern[]  = "Move unit to here|Right";
const char kMoveCursorOrig[]  = "Move cursor to here|Shift+Right";
const char kMoveCursorModern[] = "Move cursor to here|Shift+Left";
static_assert(sizeof kMoveCursorModern <= sizeof kMoveCursorOrig, "the Shift+Left text must fit the vanilla slot");
char** g_lblArray = nullptr;          // the label array the current state was applied to (labels load after us)
const BYTE* g_lblPoolBase = nullptr;  // the string pool's base at that time (read_rules re-makes both)
char*  g_lblMoveUnitOrig = nullptr;   // the vanilla pointer of label 557
char*  g_lblMoveUnitModern = nullptr; // our pooled copy, made once per pool
size_t g_lblCursorCap = 0;            // label 565's slot capacity (strlen + 1 when first seen): never written past
int    g_lblState = 0;                // 0 vanilla, 1 Modern with the right-drag child, 2 Modern instant
bool   g_lblSeen = false;             // a pass has run against g_lblArray / g_lblPoolBase

// read_rules 0x5873C0 (a new game, a scenario) re-inits the pool and re-fills the array -- often at the same
// addresses -- so the cache is keyed on the pool base AND on the table still holding one of our pointers;
// anything else means a reload: forget every pointer (the pooled copy is gone with the old pool).
void RelabelMenu()
{
    char** labels = Rd<char**>(kVA_TextLabels);
    if (!labels || Rd<uint32_t>(kVA_TextLabels + 4) <= static_cast<uint32_t>(kLblMoveCursor)) return;   // not loaded yet
    BYTE* pool = At(kVA_TextTable);
    const BYTE* base = RdP<const BYTE*>(pool + 4);
    const uint32_t size = RdP<uint32_t>(pool + 0xC);
    auto inPool = [&](const char* p) { return p && reinterpret_cast<const BYTE*>(p) >= base && reinterpret_cast<const BYTE*>(p) < base + size; };
    char* unit = labels[kLblMoveUnit];
    char* cur = labels[kLblMoveCursor];
    if (labels != g_lblArray || base != g_lblPoolBase || (unit != g_lblMoveUnitOrig && unit != g_lblMoveUnitModern)) {
        g_lblArray = labels; g_lblPoolBase = base;
        g_lblMoveUnitOrig = nullptr; g_lblMoveUnitModern = nullptr; g_lblCursorCap = 0; g_lblState = 0; g_lblSeen = false;
    }
    const int want = g_available && g_on ? (g_rightDrag ? 1 : 2) : 0;
    if (g_lblSeen && want == g_lblState) return;
    // 565 in place, never past the slot it was found with (a labels.txt that already says Shift+Left has a shorter slot)
    if (cur && inPool(cur)) {
        if (!g_lblCursorCap && (strcmp(cur, kMoveCursorOrig) == 0 || strcmp(cur, kMoveCursorModern) == 0)) g_lblCursorCap = strlen(cur) + 1;
        if (g_lblCursorCap) {
            const char* t = want ? kMoveCursorModern : kMoveCursorOrig;
            if (strlen(t) + 1 <= g_lblCursorCap) strcpy_s(cur, g_lblCursorCap, t);
        }
    }
    // 557 through a pooled copy (longer than the slot); the pointer swap is reversible
    if (!g_lblMoveUnitOrig && unit && inPool(unit) && strcmp(unit, kMoveUnitOrig) == 0) g_lblMoveUnitOrig = unit;
    if (g_lblMoveUnitOrig) {
        if (want == 2 && !g_lblMoveUnitModern && Rd<int>(kVA_TextTable + kPoolFree) >= static_cast<int>(sizeof kMoveUnitModern))
            g_lblMoveUnitModern = reinterpret_cast<char*(__fastcall*)(BYTE*, void*, const char*)>(At(kVA_StringsPut))(pool, nullptr, kMoveUnitModern);
        if (g_lblMoveUnitModern && !inPool(g_lblMoveUnitModern)) g_lblMoveUnitModern = nullptr;
        labels[kLblMoveUnit] = (want == 2 && g_lblMoveUnitModern) ? g_lblMoveUnitModern : g_lblMoveUnitOrig;
    }
    g_lblState = want;
    g_lblSeen = true;
}

void ApplyAll()
{
    PraxDragApply(EffectiveDragButton());
    if (!g_on || g_rightDrag) HoverTeardown();   // from the Preferences page: PrefWin is modal, the map idle
    RelabelMenu();
}

bool WriteCode(BYTE* p, const void* bytes, size_t n)
{
    DWORD old;
    if (!VirtualProtect(p, n, PAGE_EXECUTE_READWRITE, &old)) return false;
    memcpy(p, bytes, n);
    VirtualProtect(p, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, n);
    return true;
}

bool WriteBranch(uintptr_t va, BYTE opcode, void* target, size_t siteLen)
{
    BYTE buf[16];
    buf[0] = opcode;                                        // E9 jmp / E8 call
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(target) - (reinterpret_cast<uintptr_t>(At(va)) + 5));
    memcpy(buf + 1, &rel, 4);
    for (size_t i = 5; i < siteLen; ++i) buf[i] = 0x90;
    return WriteCode(At(va), buf, siteLen);
}

bool SlotIs(size_t slot, uintptr_t expect)
{
    const uintptr_t entry = RdP<uintptr_t>(At(kVA_ConsoleVtbl) + slot);
    if (entry != reinterpret_cast<uintptr_t>(At(expect))) return false;
    return expect == kLeaveStub || memcmp(At(expect), kThunkPrologue, sizeof kThunkPrologue) == 0;
}

// The right-click pick (PickByRight) relies on: MapWin_click taking the mode through 0x5107E0 into [ebp-0x24]
// (0x46D758), its left path running the pick from that local (0x46E11F) through the 2..11 table (0x46E1AF), and the
// right press arming nothing while a mode is set (0x46EC62). Checked on its own: a mismatch only turns it off.
const BYTE kPickTakeBytes[10]   = { 0xE8, 0x83, 0x30, 0x0A, 0x00, 0x85, 0xC0, 0x89, 0x45, 0xDC };   // call 0x5107E0; test; mov [ebp-0x24],eax
const BYTE kPickRunBytes[11]    = { 0x8B, 0x7D, 0xDC, 0x85, 0xFF, 0x0F, 0x84, 0x6F, 0x01, 0x00, 0x00 };
const BYTE kPickTableBytes[6]   = { 0x8D, 0x77, 0xFE, 0x83, 0xFE, 0x09 };                          // lea esi,[edi-2]; cmp esi,9
const BYTE kPickRDownBytes[12]  = { 0x39, 0x1D, 0xC0, 0x93, 0x93, 0x00, 0x0F, 0x85, 0xAC, 0x00, 0x00, 0x00 };
const BYTE kPickCancelBytes[12] = { 0x55, 0x8B, 0xEC, 0x51, 0x8B, 0x81, 0x10, 0x3D, 0x02, 0x00, 0x85, 0xC0 };   // Console_selected head
bool PickSitesOk()
{
    return memcmp(At(0x46D758), kPickTakeBytes, sizeof kPickTakeBytes) == 0 &&
           memcmp(At(0x46E11F), kPickRunBytes, sizeof kPickRunBytes) == 0 &&
           memcmp(At(0x46E1AF), kPickTableBytes, sizeof kPickTableBytes) == 0 &&
           memcmp(At(0x46EC62), kPickRDownBytes, sizeof kPickRDownBytes) == 0 &&
           memcmp(At(kVA_ConSelected), kPickCancelBytes, sizeof kPickCancelBytes) == 0;
}

bool SitesOk()
{
    return memcmp(At(kVA_Gate), kGateBytes, kGateLen) == 0 &&
           memcmp(At(kVA_InlineGoto), kInlineBytes, sizeof kInlineBytes) == 0 &&
           memcmp(At(kVA_Split), kSplitBytes, kSplitLen) == 0 &&
           memcmp(At(kVA_SplitRight), kSplitRightBytes, sizeof kSplitRightBytes) == 0 &&
           memcmp(At(kVA_SplitLeft), kSplitLeftBytes, sizeof kSplitLeftBytes) == 0 &&
           memcmp(At(kVA_SplitMenu), kSplitMenuBytes, sizeof kSplitMenuBytes) == 0 &&
           memcmp(At(kVA_SplitCursor), kSplitCursorBytes, sizeof kSplitCursorBytes) == 0 &&
           memcmp(At(kVA_StatusDrawDest), kStatusDrawDestBytes, sizeof kStatusDrawDestBytes) == 0 &&
           memcmp(At(kVA_StatusHide - 5), kStatusHideBytes, sizeof kStatusHideBytes) == 0 &&
           memcmp(At(kVA_CenterClear - 7), kCenterClearBytes, sizeof kCenterClearBytes) == 0 &&
           memcmp(At(kVA_CenterDest), kCenterDestBytes, sizeof kCenterDestBytes) == 0 &&
           memcmp(At(0x50F296), kGoTimerFind, 5) == 0 && memcmp(At(0x50F2A9), kGoTimerSel, 5) == 0 &&
           memcmp(At(kVA_VehSelOperand), kVehSelOperandBytes, 3) == 0 &&
           SlotIs(kSlotMove, kThunkMove) && SlotIs(kSlotLeave, kLeaveStub) && SlotIs(kSlotLeftDown, kThunkLeftDown) &&
           SlotIs(kSlotLeftClick, kThunkLeftClick) && SlotIs(kSlotRightClick, kThunkRightClick) &&
           SlotIs(kSlotRightDown, kThunkRightDown);
}

bool InstallSites()
{
    // originals first, so a half-install can never forward into an unsaved slot
    BYTE* vt = At(kVA_ConsoleVtbl);
    g_origMove = RdP<FGwXY>(vt + kSlotMove);
    g_origLeave = RdP<FGwXY>(vt + kSlotLeave);
    g_origLeftDown = RdP<FGwXY>(vt + kSlotLeftDown);
    g_origLeftClick = RdP<FGwXY>(vt + kSlotLeftClick);
    g_origRightClick = RdP<FGwXY>(vt + kSlotRightClick);
    g_origRightDown = RdP<FGwXY>(vt + kSlotRightDown);
    g_morePrefs = At(kVA_MorePrefs);
    g_gateGoto = At(kVA_InlineGoto);
    g_gateResume = At(kVA_GateResume);
    g_splitLeft = At(kVA_SplitLeft);
    g_splitRight = At(kVA_SplitRight);
    g_splitMenu = At(kVA_SplitMenu);
    g_splitCursor = At(kVA_SplitCursor);
    g_drawMyDest = At(kVA_DrawMyDest);
    g_winHide = At(kVA_WinHide);
    // the live unit array: veh_selectable's operand (+2 = the y field) -- Thinker repoints it
    // (the operand is an absolute VA: At() rebases it -- never subtract the image base here as well)
    g_vehs = At(RdP<uint32_t>(At(kVA_VehSelOperand) + 3) - 2);
    {   // the array must be committed writable data, or every hover would write into the wrong place
        MEMORY_BASIC_INFORMATION mbi{};
        // plain data only: a code page (even one PRACX left writable) is never the unit array
        const DWORD rw = PAGE_READWRITE | PAGE_WRITECOPY;
        if (!VirtualQuery(g_vehs, &mbi, sizeof mbi) || mbi.State != MEM_COMMIT || !(mbi.Protect & rw)) {
            UimodLog("[uimod] modernctl: unit array is not writable data -> Modern Control Set disabled\n");
            return false;
        }
    }
    if (!WriteBranch(kVA_Gate, 0xE9, reinterpret_cast<void*>(&GateTramp), 5)) return false;
    if (!WriteBranch(kVA_Split, 0xE9, reinterpret_cast<void*>(&SplitTramp), kSplitLen)) return false;
    if (!WriteBranch(kVA_StatusDrawDest, 0xE8, reinterpret_cast<void*>(&StubDrawMyDest), 5)) return false;
    if (!WriteBranch(kVA_StatusHide, 0xE8, reinterpret_cast<void*>(&StubOverlayHide), 5)) return false;
    g_gwinClear = At(kVA_GWinClear);
    if (!WriteBranch(kVA_CenterClear, 0xE8, reinterpret_cast<void*>(&StubOverlayClear), 5)) return false;
    if (!WriteBranch(kVA_CenterDest, 0xE8, reinterpret_cast<void*>(&StubDrawMyDest), 5)) return false;
    DWORD old;
    if (!VirtualProtect(vt, 0x60, PAGE_READWRITE, &old)) return false;
    WrP<FGwXY>(vt + kSlotMove, &HoverMouseMove);
    WrP<FGwXY>(vt + kSlotLeave, &LeaveWrap);
    WrP<FGwXY>(vt + kSlotLeftDown, &LeftDownWrap);
    WrP<FGwXY>(vt + kSlotLeftClick, &LeftClickWrap);
    WrP<FGwXY>(vt + kSlotRightClick, &RightClickWrap);
    WrP<FGwXY>(vt + kSlotRightDown, &RightDownWrap);
    VirtualProtect(vt, 0x60, old, &old);
    return true;
}

// The camera options' two sites (after the vtable wrappers, whose +0x4C bracket the set_center stub reads).
bool InstallCamera()
{
    if (memcmp(At(kVA_SetCenter), kSetCenterBytes, sizeof kSetCenterBytes) != 0 ||
        memcmp(At(kVA_BaseExitCenter), kBaseExitCenterBytes, sizeof kBaseExitCenterBytes) != 0 ||
        memcmp(At(kVA_BaseButtonCenter), kBaseButtonCenterBytes, sizeof kBaseButtonCenterBytes) != 0 ||
        memcmp(At(kVA_ConsoleCenter), kConsoleCenterBytes, sizeof kConsoleCenterBytes) != 0)
        return false;
    g_setCenterResume = At(kVA_SetCenterResume);
    g_consoleCenter = At(kVA_ConsoleCenter);
    if (!WriteBranch(kVA_SetCenter, 0xE9, reinterpret_cast<void*>(&StubSetCenter), 5)) return false;
    if (!WriteBranch(kVA_BaseExitCenter, 0xE8, reinterpret_cast<void*>(&StubBaseCenter), 5)) return false;
    if (!WriteBranch(kVA_BaseButtonCenter, 0xE8, reinterpret_cast<void*>(&StubBaseCenter), 5)) return false;
    return true;
}

} // namespace

void InstallModernControls()
{
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    g_on = GetPrivateProfileIntA("UIMod", "ModernControls", kModernControlsDefault, ini) != 0 ? 1 : 0;
    g_rightDrag = GetPrivateProfileIntA("UIMod", "RightClickDragsToMove", kRightClickDragDefault, ini) != 0 ? 1 : 0;
    g_dragBtn = static_cast<int>(GetPrivateProfileIntA("UIMod", "MapDragButton", kMapDragButtonDefault, ini));
    if (g_dragBtn < 0 || g_dragBtn > 2) g_dragBtn = kMapDragButtonDefault;
    WritePrivateProfileStringA("UIMod", "ShiftInstantMove", nullptr, ini);   // the retired setting (2026-10-07)

    // the scenario editor palette's highlight for its last four modes (vanilla; independent of the set)
    if (memcmp(At(kVA_PaintsBound), kPaintsBoundBytes, sizeof kPaintsBoundBytes) == 0) {
        if (WriteCode(At(kVA_PaintsBound) + 2, &kPaintsBoundNew, 1))
            UimodLog("[uimod] modernctl: scenario editor palette highlight covers modes 26..29 (Console_editor_paints bound 0x1A -> 0x1E)\n");
    } else {
        UimodLog("[uimod] modernctl: Console_editor_paints byte check FAILED @0x4E0A86 -> palette highlight left as is\n");
    }

    // S1: Shift+click arms no drag, in every mode (the setting that made this optional is gone)
    g_shiftOk = memcmp(At(kVA_ShiftSite), kShiftBytes, kShiftLen) == 0;
    if (g_shiftOk) WriteCode(At(kVA_ShiftSite) + kOffPush3, kJmpOut, 2);
    else UimodLog("[uimod] modernctl: Shift-branch byte check FAILED @0x46EF8A -> vanilla Shift+click drag kept\n");

    if (!SitesOk() || !InstallSites()) {
        UimodLog("[uimod] modernctl: byte check FAILED (MapWin_click 0x46E36D/0x46E529, StatusWin 0x4B5D95/0x4B5DC2, Console vtable 0x66EC18) -> Modern Control Set disabled\n");
        g_on = 0;                         // the feature is off; the map-drag button still applies on its own
        g_rightDrag = 0;
        ApplyAll();
        return;
    }
    g_available = true;
    g_pickOk = PickSitesOk();
    if (!g_pickOk) UimodLog("[uimod] modernctl: pick byte check FAILED (MapWin_click 0x46D758/0x46E11F/0x46E1AF, right_down 0x46EC62) -> a right click does not complete a P/target pick\n");
    g_clickKeepsView = GetPrivateProfileIntA("UIMod", "ClickKeepsView", kClickKeepsViewDefault, ini) != 0 ? 1 : 0;
    g_baseKeepsView = GetPrivateProfileIntA("UIMod", "BaseCloseKeepsView", kBaseCloseKeepsViewDefault, ini) != 0 ? 1 : 0;
    g_camOk = InstallCamera();
    if (!g_camOk) {
        char m[256];
        const BYTE* a = At(kVA_SetCenter); const BYTE* b = At(kVA_BaseExitCenter); const BYTE* c = At(kVA_ConsoleCenter);
        wsprintfA(m, "[uimod] modernctl: camera install FAILED -> camera options disabled; live bytes 46B1F0=%02X %02X %02X %02X %02X"
                     " 41A600=%02X %02X %02X %02X %02X 515400=%02X %02X %02X %02X %02X %02X %02X\n",
                  a[0], a[1], a[2], a[3], a[4], b[0], b[1], b[2], b[3], b[4], c[0], c[1], c[2], c[3], c[4], c[5], c[6]);
        UimodLog(m);
    }
    if (g_rightDrag && !RightClickDragAvailable()) {
        UimodLog("[uimod] modernctl: PRACX drag sites unavailable -> Right-Click Drags to Move forced off\n");
        g_rightDrag = 0;
    }
    ApplyAll();
    char msg[200];
    _snprintf_s(msg, sizeof msg, _TRUNCATE,
                "[uimod] modernctl: installed; ModernControls=%d RightClickDragsToMove=%d MapDragButton=%d (effective %d) ClickKeepsView=%d BaseCloseKeepsView=%d, units @%p%s\n",
                g_on, g_rightDrag, g_dragBtn, EffectiveDragButton(), g_clickKeepsView, g_baseKeepsView, g_vehs,
                g_vehs == At(kVA_Vehs) ? "" : " (relocated)");
    UimodLog(msg);
}

bool ModernControlsAvailable() { return g_available; }
bool ModernCtlBusy() { return g_inForward; }
int  ModernControlsGet() { return g_on; }
void ModernControlsSet(int on)
{
    if (!g_available) return;
    g_on = on ? 1 : 0;
    ApplyAll();
}
void ModernControlsSave()
{
    if (!g_available) return;
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "ModernControls", g_on ? "1" : "0", ini);
}

bool RightClickDragAvailable()
{
    return g_available && (GetModuleHandleA("prax.dll") == nullptr || PraxDragAvailable());
}
int  RightClickDragGet() { return g_rightDrag; }
void RightClickDragSet(int on)
{
    if (!RightClickDragAvailable()) return;
    g_rightDrag = on ? 1 : 0;
    ApplyAll();
}
void RightClickDragSave()
{
    if (!RightClickDragAvailable()) return;   // a forced-off value is never written over the player's choice
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "RightClickDragsToMove", g_rightDrag ? "1" : "0", ini);
}

bool MapDragButtonAvailable() { return PraxDragAvailable(); }
int  MapDragButtonGet() { return g_dragBtn; }
void MapDragButtonSet(int button)
{
    if (!MapDragButtonAvailable()) return;
    if (button < 0 || button > 2) return;
    g_dragBtn = button;
    ApplyAll();
}
void MapDragButtonSave()
{
    if (!MapDragButtonAvailable()) return;
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    char val[4];
    _snprintf_s(val, sizeof val, _TRUNCATE, "%d", g_dragBtn);
    WritePrivateProfileStringA("UIMod", "MapDragButton", val, ini);
}
bool MapDragRightAllowed() { return !RightIsMoveButton(); }

bool CameraAvailable() { return g_camOk; }
int  ClickKeepsViewGet() { return g_clickKeepsView; }
void ClickKeepsViewSet(int on) { if (g_camOk) g_clickKeepsView = on ? 1 : 0; }
void ClickKeepsViewSave()
{
    if (!g_camOk) return;
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "ClickKeepsView", g_clickKeepsView ? "1" : "0", ini);
}
int  BaseCloseKeepsViewGet() { return g_baseKeepsView; }
void BaseCloseKeepsViewSet(int on) { if (g_camOk) g_baseKeepsView = on ? 1 : 0; }
void BaseCloseKeepsViewSave()
{
    if (!g_camOk) return;
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "BaseCloseKeepsView", g_baseKeepsView ? "1" : "0", ini);
}

void ModernCtlFilterKey(MSG* m)
{
    if (m->message != WM_KEYDOWN) return;
    if (m->wParam == VK_ESCAPE && g_wpVeh >= 0 && WpVehIsOurs() && VehOrder(g_wpVeh) == 0 &&
        (VehFlags(g_wpVeh) & kVehWaypointFlag) && Rd<int>(kVA_CurVeh) == g_wpVeh && MapTakesInput() && !EditorEngaged() &&
        Rd<int>(kVA_SelMode) == 0 && RdP<int>(Console() + kConDragActive) == 0) {   // Esc drops the uncommitted path
        ClearPendingWaypoints();
        WrP<int>(Console() + kConLastTileX, -1);
        PostPointerMove();
        m->message = WM_NULL;
        return;
    }
    if (m->wParam != VK_SHIFT && m->wParam != VK_CONTROL) return;
    if (m->lParam & (1 << 30)) { m->message = WM_NULL; return; }   // auto-repeat: the engine learns nothing from it
    // a map press is armed or dragging and the button is still down: go_reset would swallow its release
    if (Rd<int>(kVA_GoWinIdx) >= 0 && (RdP<int>(Console() + kConDragActive) != 0 || LeftHeld())) m->message = WM_NULL;
}

void ModernCtlPoll(const MSG* m)
{
    if (g_inForward) return;
    (void)m;
    RelabelMenu();                                        // labels.txt loads after the DLL's install: apply on the first message after
    WaypointHousekeeping();
    // A new unit became the one to move (Tab, the engine advancing, a click) while the pointer sat still: the
    // line waits for the next WM_MOUSEMOVE, so post one (user 2026-10-10). The wrapper then draws, or tears down.
    static int lastVeh = -2, lastMode = -1;
    static int tries = 0;             // posts still owed for the latest unit change
    static DWORD lastTry = 0;
    const int curVeh = Rd<int>(kVA_CurVeh), mode = Rd<int>(kVA_MoveMode);
    if (curVeh != lastVeh || mode != lastMode) {
        lastVeh = curVeh; lastMode = mode;
        HoverDbg("unit-changed", m ? static_cast<int>(m->message) : -1);
        tries = 12;
    }
    // The switch is seen from INSIDE the engine's Tab dispatch (its nested pump runs this hook), and Console_ready's
    // flush_input then discards any move posted so far (traced twice, 2026-10-10). So the need is kept, and a move
    // is posted every 40 ms until the map wrapper has run for the new unit (it zeroes `tries`) -- at most 12 times.
    if (tries > 0) {
        if (!(g_on && !g_rightDrag && mode != 0 && curVeh >= 0 && MapTakesInput())) tries = 0;
        else if (GetTickCount() - lastTry >= 40) {
            lastTry = GetTickCount();
            --tries;
            g_movePosted = false;
            g_hoverTries = &tries;
            PostPointerMove();
        }
    }
    if (!g_hoverOwned) return;
    if (!MapTakesInput() || !OverlayShown()) { PostPointerMove(); return; }   // teardown / re-show on the next dispatch
    int origin[4];
    ReadOrigin(origin);
    if (memcmp(origin, g_hoverOrigin, sizeof origin) != 0) PostPointerMove();   // the map scrolled under the line
}

// Smooth map scrolling (mapscroll.cpp) shifts the canvas from inside PRACX's scroll loop, which pumps no
// messages: the line on the screen-fixed overlay would sit at its old place until the next dispatch (user
// 2026-10-10). Hide it for the scroll; g_hoverOwned stays set, so ModernCtlPoll's "!OverlayShown" re-post
// redraws it at the pointer on the first message after the scroll (the engine's own drag is left alone).
void ModernCtlMapScrollStep()
{
    if (!g_hoverOwned || g_inForward) return;
    if (RdP<int>(Console() + kConDragActive) == 0 && OverlayShown()) WinHide(Overlay());
}

// The live unit array for the other HUD modules (hudsync, hudmovesfix): resolved the way InstallSites does it,
// from veh_selectable's operand, so Thinker's relocated array (modify_unit_limit) is honoured even when the
// Modern Control Set itself is disabled.
BYTE* ModernCtlVehs()
{
    if (g_vehs) return g_vehs;
    if (memcmp(At(kVA_VehSelOperand), kVehSelOperandBytes, 3) == 0) return At(RdP<uint32_t>(At(kVA_VehSelOperand) + 3) - 2);
    return At(kVA_Vehs);
}
bool ModernCtlVehOk(int veh) { return VehOk(veh); }
