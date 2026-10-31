// uimod update checker -- at launch the game asks the RESIDENT INSTALLER what is available
// (`install.py --check` over a pipe, on a worker thread; zero start-time cost) and, once the player
// is at the top of the main menu or a turn begins, offers it. See update.cpp and
// update_core.h. Cave-free (no patcher artefact is touched), so it works on the
// PRACX-patched and the unpatched exe alike; its one code change is a byte-checked rel32
// retarget of the four vanilla `call Console_human_turn` sites (the turn-begin token).
#pragma once

#include <windows.h>

// Call once from Init(). Reads [UIMod] CheckForUpdates; when on, starts the worker thread that
// runs the installer's --check and arms the turn-begin hook. Never blocks. Off = no process.
void InstallUpdateCheck();

// From the WH_GETMESSAGE hook (wheel.cpp), on the game's main thread, every HC_ACTION: consumes
// the worker's answer once, logs it, and -- when the player is idle at the top of the main menu
// or at the start of a turn -- posts the presentation trigger.
void UpdatePoll();

// From the same hook, PM_REMOVE only: runs the prompt sequence when the trigger message comes
// off the queue (the message is turned into WM_NULL), and notes the player's first input of a
// turn (after which the turn is no longer "beginning").
void UpdateOnMessage(MSG* m);

// From Init(), before or after InstallUpdateCheck: a notice for the player (the codec probe found a DLL
// missing -> cinematics off), shown once at the top of the main menu -- or at a turn start, where the
// turn hook is armed (only with the update check on) -- through the same gate and popup as the update
// prompts, ahead of them, and then remembered by `sig` in [UIMod] CinematicsNotice so the same problem
// set is not announced again (a popup that could not show remembers nothing). Works when the update
// check itself is off or not applicable.
void UpdateQueueStartupNotice(const char* body, const char* sig);
// From Init() when the probe passes: forget the remembered set, so the same DLL vanishing again later is
// a new event and is announced again.
void UpdateClearStartupNotice();

// Preferences "Reset Skipped Updates": confirmation popup; on Yes clears every
// "Don't ask me again" ([Longevity] DeclinedUpdates) and turns checking on. True when cleared.
bool UpdateSubscribeAll();

// "Check for Updates at Startup" ([UIMod] CheckForUpdates; default 1). Takes effect at the NEXT
// launch: an in-flight check is not cancelled.
int  UpdateCheckGet();
void UpdateCheckSet(int on);     // live value (no persist)
void UpdateCheckSave();          // persist the current value
constexpr int kUpdateCheckDefault = 1;
