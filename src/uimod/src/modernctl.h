// uimod "Modern Control Set" (opt-in, [UIMod] ModernControls): right click moves the selected unit at once,
// the move-to line follows the pointer whenever a unit is selected, Shift+left click opens the tile orders
// menu, no left drag. Child [UIMod] RightClickDragsToMove: vanilla's hold-and-drag on the RIGHT button instead.
// [UIMod] MapDragButton: which button drag-scrolls the map under PRACX (2 right, 1 middle, 0 none).
// Also owns the Shift-branch neutralisation (no Shift+click instant drag in any mode) and the modifier
// auto-repeat filter that fixes the engine's swallowed-click bug. See modernctl.cpp.
#pragma once

#include <windows.h>

constexpr int kModernControlsDefault = 0;     // vanilla
constexpr int kRightClickDragDefault = 0;
constexpr int kMapDragButtonDefault  = 2;     // PRACX's right-button drag scroll
constexpr int kMapDragRight = 2, kMapDragMiddle = 1, kMapDragNone = 0;

// Byte-checks every site, installs the detours / vtable wrappers once, reads the three ini keys and applies
// them. Call AFTER InstallPraxDrag (praxdrag.h) and before the prefs tab builds. Both exes.
void InstallModernControls();

bool ModernControlsAvailable();               // every terranx site checked out (the page shows the rows)
bool ModernCtlBusy();                         // inside the hover line's forward to the engine's drag painter
int  ModernControlsGet();
void ModernControlsSet(int on);               // live-apply (no persist)
void ModernControlsSave();

bool RightClickDragAvailable();               // Available() and (no PRACX, or PRACX's drag sites checked out)
int  RightClickDragGet();
void RightClickDragSet(int on);
void RightClickDragSave();

bool MapDragButtonAvailable();                // PRACX bound and its drag sites checked out (the cell row shows)
int  MapDragButtonGet();                      // the STORED value (2/1/0)
void MapDragButtonSet(int button);
void MapDragButtonSave();
bool MapDragRightAllowed();                   // false while ModernControls && RightClickDragsToMove (forced to none)

// Camera options (independent of Modern Control Set; byte-checked sites of their own):
//   [UIMod] ClickKeepsView      -- a left click on the map never recentres it (bases at the edge included)
//   [UIMod] BaseCloseKeepsView  -- closing the base screen never recentres the map (cursor near the edge,
//                                  or the selected unit off screen)
constexpr int kClickKeepsViewDefault = 0, kBaseCloseKeepsViewDefault = 0;
bool CameraAvailable();
int  ClickKeepsViewGet();     void ClickKeepsViewSet(int on);     void ClickKeepsViewSave();
int  BaseCloseKeepsViewGet(); void BaseCloseKeepsViewSet(int on); void BaseCloseKeepsViewSave();

// WH_GETMESSAGE hook (wheel.cpp), PM_REMOVE: drops Shift/Ctrl auto-repeat key-downs everywhere, and any
// Shift/Ctrl key-down while a map press is armed or dragging (go_reset would swallow the release).
void ModernCtlFilterKey(MSG* m);
// Same hook, every removed message: tears the hover line down when the map can no longer take input.
void ModernCtlPoll(const MSG* m);
void ModernCtlMapScrollStep();                // mapscroll: the canvas moved under the hover line -- hide it until the next dispatch
BYTE* ModernCtlVehs();                        // the live unit array (stock 0x952828, or where Thinker's modify_unit_limit put it)
bool  ModernCtlVehOk(int veh);                // 0 <= veh < VehCount (and under the hard cap)
