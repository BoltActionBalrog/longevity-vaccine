// uimod display mode: Fullscreen / Borderless / Windowed on top of PRACX's window code. See vidmode.cpp.
#pragma once

#include <windows.h>

enum VidMode { kVidFullscreen = 0, kVidBorderless = 1, kVidWindowed = 2 };
constexpr int kVidModeDefault = kVidFullscreen;

void VidModePreInit(HMODULE prax);    // bootstrap phase one (init.cpp PreInit): before PRACX's own init runs
void InstallVidMode(bool pracx);
bool VidModeAvailable();              // false on the PRACX-less exe or an unknown prax.dll
bool VidModeOwnDisplaySwitch();       // PRACX's own ChangeDisplaySettings is running or just ran ([UIMod] FullscreenModeSwitch=1)
int  VidModeDetect();                 // the mode the game is RUNNING in (live window state, never the ini)
void VidModeSet(int mode);            // live switch
void VidModeSave(int mode);           // [UIMod] VideoMode
void VidModeOnChange(void (*fn)());   // called when the running mode changes (any cause)
void VidModePoll();                   // from the WH_GETMESSAGE hook: one-shot boot apply

// Fullscreen's pointer hold ([UIMod] ConstrainMouse, default on): the "Constrain Mouse to Window" row.
bool VidModeFullscreenRunning();      // Fullscreen in either form (PRACX's own or the scaled popup) = the row means something
int  VidModeClipGet();
void VidModeClipSet(int on);          // live
void VidModeClipSave();               // with OK

// True while PRACX stretches the backbuffer into the client area (Borderless / Windowed):
// anything of ours that draws to or hit-tests the window must map through the client rect.
bool VidModeStretched();
void VidModeClientToBackbuffer(HWND hwnd, POINT* p);
