// uimod.dll — SMACX UI Mod addon DLL.
//
// Part of the hybrid binary-patch + DLL architecture (src\uimod\README.md):
// the static binary-patch corpus stays for surgical, MD5-lockable UI-math fixes; this
// DLL is the home for features that need code volume, must be last-writer over PRACX,
// or want real C++ ergonomics.
//
// DllMain stays minimal on purpose. The real entry points are PreInit() and Init() (init.cpp),
// which our bootstrap loader calls *around* PRACX's own init: PreInit just before it (prax.dll
// loaded, nothing of its run yet), Init just after — the loader is the patch group
// `uimod_bootstrap` in work\patches\patches.yaml, chained off PRACX's own loader stub.

#include <windows.h>

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID /*reserved*/)
{
    if (reason == DLL_PROCESS_ATTACH) {
        // No per-thread bookkeeping; suppress THREAD_ATTACH/DETACH callbacks.
        DisableThreadLibraryCalls(module);
    }
    return TRUE;
}
