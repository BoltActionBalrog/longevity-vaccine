#pragma once

// Smooth leader portraits at enlarged UI scales (de-scanline + Lanczos-3 + dithered palette fit); hooks the
// patcher's two scanline re-blit thunks, patched exe only, [UIMod] SmoothPortraits=0 opts out. See portrait.cpp.
void InstallSmoothPortraits();

// Scanlines on REPLACEMENT portraits (<game>\portraits\, the portraits-hd pack): Preferences row "Add Scanlines"
// ([UIMod] PortraitScanlines).  Set = live (no persist); Save = write the ini (Preferences OK / Enter).
// PortraitScanMode(): scaling_laws PORTRAIT_SCAN_* -- 0 off, 2 brightness kept.  The scanlines are always the
// brightness-keeping kind: the former "Brighten Scanlines" row and its PortraitScanlinesBright key are gone (user
// 2026-10-30), and the darkening overlay mode 1 is no longer selectable.
//
// The whole group hangs under "Enable User Portraits" ([UIMod] CustomPortraits): off = the game's own portraits
// everywhere.  Its children: "Use Longevity HD Portrait Pack" ([UIMod] HdPortraits; the row exists only while the
// portraits-hd pack is installed) and "Add Scanlines".  A parent turned off forces its children off; turned on,
// they follow it on (the cloak rows' pattern).
constexpr int kPortraitCustomDefault = 1;
constexpr int kPortraitHdDefault = 1;
constexpr int kPortraitScanDefault = 1;
int  PortraitCustomGet();
void PortraitCustomSet(int on);   // live: re-bakes (off restores the game's portraits)
void PortraitCustomSave();
int  PortraitHdGet();
void PortraitHdSet(int on);       // live: re-bakes
void PortraitHdSave();
bool PortraitPackInstalled();
// All three at once (a parent toggle, Restore Defaults): one re-bake, not one per setting.
void PortraitSetAll(int custom, int hd, int scan);
int  PortraitScanGet();
void PortraitScanSet(int on);
void PortraitScanSave();
int  PortraitScanMode();
// Re-bake every replaced leader slot with the current scan mode (Preferences toggles call it; the enlarged results
// and the native-life bakes are keyed on the mode, so they follow by themselves).
void PortraitRebake();
