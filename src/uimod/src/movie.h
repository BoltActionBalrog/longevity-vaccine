#pragma once
// In-process cinematic player (replaces PRACX's external playuv15 + the native uV pipeline).
//
// InstallMovieHook re-points amovie_project_2 (0x00403BE0) to uimod_PlayMovie so movies play
// inside the game process/window -- no external app, no display-mode change.
//   * pracx=true  : PRACX already stamped E9+rel32 at the entry; we only re-point the rel32.
//   * pracx=false : native exe has no hook; we lay down the whole E9 JMP ourselves.
//
// SPIKE A: uimod_PlayMovie currently draws a test pattern (no codec) to validate the
// intercept + GDI present + skip + WM_MOVIEOVER contract before the real decoder lands.
void InstallMovieHook(bool pracx);

// Before InstallMovieHook: are the five codec DLLs (delay-loaded; see codecs.h) beside uimod.dll and the
// builds this DLL was compiled against? False -> do NOT install the hook; `log` holds the uimod.log lines,
// `notice` the player's one-time popup body, `sig` the problem set's signature (the notice is shown once
// per distinct set). The probe keeps the DLLs loaded.
bool MovieCodecsOk(char* log, size_t logCap, char* notice, size_t noticeCap, char* sig, size_t sigCap);

// __cdecl(const char*) to match amovie_project_2 / PRACXShowMovie (caller cleans the arg).
extern "C" void __cdecl uimod_PlayMovie(const char* name);

// True while uimod_PlayMovie runs (the movie owns the game window).
bool MovieActive();
