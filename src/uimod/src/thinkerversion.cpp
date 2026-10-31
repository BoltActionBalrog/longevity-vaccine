// thinkerversion.cpp -- one warning dialog when the game runs a Thinker Mod build this release was not measured on.
//
// Every detour into thinker.dll (thinkeraivis.cpp, thinkertext.cpp, the chains in thinkercompat.cpp) is pinned to one
// build by its PE TimeDateStamp and SizeOfImage (version.h UIMOD_THINKER_SUPPORTED_*). On any other build those
// modules disable themselves with a log line each and the game plays on -- silently, until this module: the player
// had no way to know why parts of the mod were missing (user 2026-10-30).
//
// What the player sees (before the first game window; the same words the installer prints):
//   "Longevity Vaccine <our version> was built for Thinker Mod <supported>. This game is running <what thinker.dll says>.
//    Some game features may not work as intended. We recommend checking for a Longevity Vaccine update in-game or at
//    <download page>. If no update exists, consider playing with the officially supported version of Thinker."
// with two buttons: OK (shown again next launch) and "Don't Show Again". Only the latter persists -- as
// [UIMod] ThinkerVersionWarningDismissed = "<our version>/<thinker stamp>-<image size>" -- and it holds exactly until either side
// changes: a Longevity update or a different thinker.dll shows the dialog again (user decision 2026-10-30).
// The dialog names NO features: another build can break anything, so the text promises nothing specific.
//
// Our version comes from version.h (the macro the DLL's own VERSIONINFO is built from), the supported Thinker version
// and pin from the same header, the download page from update_core.h: no literal here can drift from the product.
// The button text: a MessageBox cannot label its buttons, so a one-shot thread CBT hook renames the Cancel button on
// activation and widens it (and the box) when the new caption needs the room. No common-controls v6 dependency.
//
// Test switch: [UIMod] ThinkerVersionWarnTest = 1 treats the supported build as a mismatch and nothing else, so the
// whole flow can be exercised on 5.5: the dialog, OK (back next start), "Don't Show Again" (its token written, no
// dialog until the key is deleted or either version changes). Never set by the mod itself.
#include "thinkerversion.h"

#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "thinkercompat.h"   // ThinkerLoaded() / ThinkerRange()
#include "update_core.h"     // kDownloadUrlShown: the one URL the player ever sees
#include "version.h"         // UIMOD_VERSION_STRING, UIMOD_THINKER_SUPPORTED_*

void UimodLog(const char* msg);   // init.cpp

namespace {

constexpr char kSection[] = "UIMod";
constexpr char kKeyDismissed[] = "ThinkerVersionWarningDismissed";
constexpr char kKeyTest[] = "ThinkerVersionWarnTest";
constexpr char kTitle[] = "Longevity Vaccine";
constexpr char kDontShowAgain[] = "Don't Show Again";

void Log(const char* fmt, ...)
{
    char buf[768];
    va_list ap;
    va_start(ap, fmt);
    _vsnprintf_s(buf, sizeof buf, _TRUNCATE, fmt, ap);
    va_end(ap);
    UimodLog(buf);
}

void IniFile(char* out, size_t n)
{
    GetModuleFileNameA(nullptr, out, static_cast<DWORD>(n));
    char* slash = strrchr(out, '\\');
    if (slash) slash[1] = '\0';
    strncat_s(out, n, "Alpha Centauri.ini", _TRUNCATE);
}

// The PE header of the loaded thinker.dll: stamp + image size, or false when unreadable.
bool ThinkerBuild(uint32_t* stamp, uint32_t* size)
{
    uintptr_t lo, hi;
    if (!ThinkerLoaded() || !ThinkerRange(&lo, &hi)) return false;
    const BYTE* base = reinterpret_cast<const BYTE*>(lo);
    auto dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return false;
    auto nt = reinterpret_cast<const IMAGE_NT_HEADERS32*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return false;
    *stamp = nt->FileHeader.TimeDateStamp;
    *size = nt->OptionalHeader.SizeOfImage;
    return true;
}

// What thinker.dll calls itself: the "Thinker Mod v<digits and dots>" string in its read-only data (its own
// version label; Thinker 5.5 draws it on the credits). Falls back to a neutral phrase when the string is not there.
// This runs on every FOREIGN build, whose image may hold reserved (uncommitted) pages inside SizeOfImage: the scan
// walks VirtualQuery regions and reads only committed, readable ones (audit 2026-10-30).
const char* RunningThinker()
{
    static char v[48];
    strcpy_s(v, "an unrecognised build of Thinker Mod");
    uintptr_t lo, hi;
    if (!ThinkerRange(&lo, &hi)) return v;
    const char key[] = "Thinker Mod v";
    const size_t klen = sizeof key - 1;
    for (uintptr_t a = lo; a < hi;) {
        MEMORY_BASIC_INFORMATION mbi;
        if (VirtualQuery(reinterpret_cast<LPCVOID>(a), &mbi, sizeof mbi) != sizeof mbi) break;
        uintptr_t rlo = reinterpret_cast<uintptr_t>(mbi.BaseAddress);
        uintptr_t rhi = rlo + mbi.RegionSize;
        if (rhi > hi) rhi = hi;
        const bool readable = mbi.State == MEM_COMMIT && !(mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) && mbi.Protect != 0;
        if (readable) {
            const BYTE* p = reinterpret_cast<const BYTE*>(a);
            const size_t n = rhi - a;
            for (size_t i = 0; i + klen + 1 < n; ++i) {
                if (p[i] != 'T' || memcmp(p + i, key, klen) != 0) continue;
                if (p[i + klen] < '0' || p[i + klen] > '9') continue;
                size_t k = 0;
                for (; k < klen && k + 1 < sizeof v; ++k) v[k] = static_cast<char>(p[i + k]);
                for (size_t j = i + klen; k + 1 < sizeof v && j < n && ((p[j] >= '0' && p[j] <= '9') || p[j] == '.'); ++j)
                    v[k++] = static_cast<char>(p[j]);
                v[k] = '\0';
                return v;
            }
        }
        if (rhi <= a) break;
        a = rhi;
    }
    return v;
}

// ---- the two-button box ------------------------------------------------------------------------------------------

HHOOK g_cbt = nullptr;
bool  g_relabelled = false;   // the Cancel button reads "Don't Show Again": only then does IDCANCEL mean it

LRESULT CALLBACK CbtRelabel(int code, WPARAM wp, LPARAM lp)
{
    if (code == HCBT_ACTIVATE) {
        HWND box = reinterpret_cast<HWND>(wp);
        HWND cancel = GetDlgItem(box, IDCANCEL);
        if (!cancel) return CallNextHookEx(nullptr, code, wp, lp);   // not our box: stay hooked for it
        if (cancel) {
            g_relabelled = SetWindowTextA(cancel, kDontShowAgain) != 0;
            // Widen the button (and the box) when the caption needs more than the stock button offers.
            RECT rb; GetWindowRect(cancel, &rb);
            HDC dc = GetDC(cancel);
            if (dc) {
                HFONT f = reinterpret_cast<HFONT>(SendMessageA(cancel, WM_GETFONT, 0, 0));
                HGDIOBJ old = f ? SelectObject(dc, f) : nullptr;
                SIZE sz = { 0, 0 };
                GetTextExtentPoint32A(dc, kDontShowAgain, static_cast<int>(strlen(kDontShowAgain)), &sz);
                if (old) SelectObject(dc, old);
                ReleaseDC(cancel, dc);
                const int want = sz.cx + 2 * GetSystemMetrics(SM_CXEDGE) + 16;
                const int have = rb.right - rb.left;
                if (want > have) {
                    const int grow = want - have;
                    RECT rw; GetWindowRect(box, &rw);
                    SetWindowPos(box, nullptr, 0, 0, rw.right - rw.left + grow, rw.bottom - rw.top,
                                 SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
                    SetWindowPos(cancel, nullptr, 0, 0, want, rb.bottom - rb.top,
                                 SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE);
                }
            }
        }
        if (g_cbt) { UnhookWindowsHookEx(g_cbt); g_cbt = nullptr; }
    }
    return CallNextHookEx(nullptr, code, wp, lp);
}

// Returns true when the player chose "Don't Show Again". A Cancel that was never relabelled (hook refused, button not
// found) is a plain "close this", never a dismissal: the player cannot have meant words they did not see.
bool ShowBox(const char* text)
{
    g_relabelled = false;
    g_cbt = SetWindowsHookExA(WH_CBT, CbtRelabel, nullptr, GetCurrentThreadId());
    if (!g_cbt) Log("[uimod] thinker: the button hook could not be installed (error %lu) -> the box shows OK / Cancel; Cancel does not dismiss\n", GetLastError());
    const int r = MessageBoxA(nullptr, text, kTitle, MB_OKCANCEL | MB_ICONWARNING | MB_DEFBUTTON1 | MB_SETFOREGROUND | MB_TOPMOST);
    if (g_cbt) { UnhookWindowsHookEx(g_cbt); g_cbt = nullptr; }
    return r == IDCANCEL && g_relabelled;
}

} // namespace

void ThinkerVersionWarning()
{
    if (!ThinkerLoaded()) return;
    char ini[MAX_PATH]; IniFile(ini, sizeof ini);
    uint32_t stamp = 0, size = 0;
    const bool readable = ThinkerBuild(&stamp, &size);
    const bool supported = readable && stamp == UIMOD_THINKER_SUPPORTED_STAMP && size == UIMOD_THINKER_SUPPORTED_IMAGE_SIZE;
    const bool test = GetPrivateProfileIntA(kSection, kKeyTest, 0, ini) != 0;
    if (supported && !test) return;

    const char* running = RunningThinker();
    // the dismissal token: OUR version + THEIR build (stamp AND image size, the same identity the pin uses), so either
    // side changing brings the dialog back
    char token[64];
    _snprintf_s(token, sizeof token, _TRUNCATE, "%s/%08X-%X", UIMOD_VERSION_STRING, static_cast<unsigned>(stamp),
                static_cast<unsigned>(size));
    char dismissed[64] = "";
    GetPrivateProfileStringA(kSection, kKeyDismissed, "", dismissed, sizeof dismissed, ini);
    if (strcmp(dismissed, token) == 0) {
        Log("[uimod] thinker: \"%s\" (stamp 0x%08X, image 0x%X) is not the supported %s build; the warning was dismissed for "
            "this pairing (%s)\n", running, static_cast<unsigned>(stamp), static_cast<unsigned>(size),
            UIMOD_THINKER_SUPPORTED_VERSION, token);
        return;
    }

    char text[768];
    _snprintf_s(text, sizeof text, _TRUNCATE,
        "Longevity Vaccine %s was built for Thinker Mod %s. This game is running %s.\n\n"
        "Some game features may not work as intended. We recommend checking for a Longevity Vaccine update in-game or at "
        "%s. If no update exists, consider playing with the officially supported version of Thinker.",
        UIMOD_VERSION_STRING, UIMOD_THINKER_SUPPORTED_VERSION, running, lvupd::kDownloadUrlShown);
    Log("[uimod] thinker: \"%s\" (stamp 0x%08X, image 0x%X) is not the supported %s build%s -> warning shown\n",
        running, static_cast<unsigned>(stamp), static_cast<unsigned>(size), UIMOD_THINKER_SUPPORTED_VERSION,
        test ? " (ThinkerVersionWarnTest)" : "");
    const bool dontShowAgain = ShowBox(text);
    if (dontShowAgain) {
        if (WritePrivateProfileStringA(kSection, kKeyDismissed, token, ini))
            Log("[uimod] thinker: the player chose Don't Show Again -> %s = %s\n", kKeyDismissed, token);
        else
            Log("[uimod] thinker: the player chose Don't Show Again but %s could not be written (error %lu) -> shown again next start\n",
                ini, GetLastError());
    } else {
        Log("[uimod] thinker: the player chose OK (shown again next start)\n");
    }
}
