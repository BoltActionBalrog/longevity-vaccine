// uimod: lines the engine draws straight onto the game WINDOW (Win_window_line_raw 0x5F2AC0), kept right while the
// frame is stretched into a client of another size.
//
// Win_window_line_raw(this, x, y, x2, y2, color, pen_width, pen_style) thiscall RET 0x1C: GetDC(g_main_hwnd), a
// PALETTEINDEX pen, MoveToEx(x2, y2) + LineTo(x, y) at FRAME coordinates, no mapping. Callers: the tutorial box's
// pointer lines (TutWin_draw_arrow / TutWin_tut_win, through the patcher's pen-width thunk) and the console crosshair.
// In Fullscreen the client IS the frame. Stretched, the line landed at frame coordinates in client space at the native
// pen width, and the GPU present (a DISCARD swap chain repainting the whole client per flip) wiped it on the next flip.
//
// So, while stretched (VidModeStretched() and a client of another size -- the one predicate every scaled present
// uses), the line is kept in frame coordinates (lineoverlay.h) and the GPU presents the frame again with it
// composited (gpuscale.cpp); each flip repaints the part of a line it covers, as on a real window; the tutorial's
// lines go when its pointer is disarmed. When the GPU path is not current, the engine's own GDI line is drawn at
// CLIENT coordinates with the pen scaled like the frame (the CPU present keeps what is drawn on the window, exactly
// as Fullscreen does). Not stretched: the engine's own line, untouched.

#include "winlines.h"
#include "gpuscale.h"
#include "lineoverlay.h"
#include "vidmode.h"

#include <intrin.h>
#include <cstdint>
#include <cstring>

namespace {

constexpr uintptr_t kImageBase  = 0x400000;
constexpr uintptr_t kVA_phWnd   = 0x009B7B28;   // HWND g_main_hwnd
constexpr uintptr_t kVA_ScreenW = 0x009B7B1C;   // ScreenWidth  (the frame)
constexpr uintptr_t kVA_ScreenH = 0x009B7B20;   // ScreenHeight
// The entry's first instruction `mov eax,[0x9B3AB0]` (5 B) becomes `jmp LineRawHook`; the trampoline replays it.
constexpr uintptr_t kVA_LineRaw = 0x005F2AC0, kVA_LineRawResume = 0x005F2AC5;
const BYTE kLineRawBytes[13] = { 0xA1, 0xB0, 0x3A, 0x9B, 0x00, 0x83, 0xEC, 0x10, 0x85, 0xC0, 0x56, 0x8B, 0xF1 };
constexpr uintptr_t kVA_TutArmed  = 0x008C6E68 + 0x53A4;   // TutWin +0x53A4: the pointer line is drawn
constexpr uintptr_t kVA_TutLine2X = 0x008C6E68 + 0x539C;   // TutWin +0x539C: the second line's x, -1 = none

template <typename T> T Rd(uintptr_t va)
{
    return *reinterpret_cast<T*>(reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (va - kImageBase));
}

lineoverlay::List g_lines = {};
using FLineRaw = void(__fastcall*)(void* self, void* edx, int x, int y, int x2, int y2, int color, int width, int style);
FLineRaw g_lineRawOrig = nullptr;      // the trampoline: the displaced instruction, then 0x5F2AC5

void PublishLines() { GpuSetLines(g_lines.line, g_lines.n); }

void ClearLines()
{
    if (!g_lines.n) return;
    lineoverlay::Clear(g_lines);
    PublishLines();
}

// The tutorial box dismissed (its pointer disarmed) or down to one line: the engine draws those lines no more.
bool PruneTutorialLines()
{
    return lineoverlay::PruneTutorial(g_lines, Rd<int>(kVA_TutArmed) != 0, Rd<int>(kVA_TutLine2X) >= 0);
}

// The frame is stretched into a client of another size (where a line drawn at frame coordinates lands wrong).
bool ScaledClient(HWND* hwnd, RECT* cr, int* sw, int* sh)
{
    *hwnd = Rd<HWND>(kVA_phWnd);
    *sw = Rd<int>(kVA_ScreenW);
    *sh = Rd<int>(kVA_ScreenH);
    return VidModeStretched() && *hwnd && *sw > 0 && *sh > 0 && GetClientRect(*hwnd, cr) && cr->right > 0 &&
           cr->bottom > 0 && !(cr->right == *sw && cr->bottom == *sh);
}

bool g_presentOwed = false;            // lines changed since the last present: WinLinesPoll presents once per batch
bool g_nullPosted = false;             // a WM_NULL is (probably) queued to make the poll run; expires after kNullPostMs
DWORD g_nullPostedAt = 0;
constexpr DWORD kNullPostMs = 50;

void __fastcall LineRawHook(void* self, void* edx, int x, int y, int x2, int y2, int color, int width, int style)
{
    HWND hwnd; RECT cr; int sw, sh;
    // (another thread than the window's -- never seen, but the GPU and the record belong to the window's thread)
    if (!ScaledClient(&hwnd, &cr, &sw, &sh) || GetWindowThreadProcessId(hwnd, nullptr) != GetCurrentThreadId()) {
        ClearLines();
        g_lineRawOrig(self, edx, x, y, x2, y2, color, width, style);
        return;
    }
    lineoverlay::Line l = {};
    l.x0 = x2; l.y0 = y2; l.x1 = x; l.y1 = y;               // MoveToEx(x2, y2), LineTo(x, y)
    l.color = color & 0xFFFF; l.width = width; l.style = style;
    l.tag = lineoverlay::TagOf(static_cast<unsigned>(reinterpret_cast<uintptr_t>(_ReturnAddress())));
    if (!lineoverlay::Add(g_lines, l)) {                     // PS_NULL: nothing to draw, as the engine draws nothing
        g_lineRawOrig(self, edx, x, y, x2, y2, color, width, style);
        return;
    }
    PruneTutorialLines();
    PublishLines();
    // The GPU path: one re-present per batch, not one full-client present per line. A tutorial pointer's batch is
    // known complete at its last line (line 2, or line 1 with no second line): present at once -- the cursor blink's
    // flip has just erased the pointer's end. Anything else (the crosshair pair) presents from the next message poll
    // or flip; a WM_NULL is posted so an idle queue still polls (latched by TIME -- a post another pass ate must
    // not block the next, and a dequeue never clears it: memory feedback-posted-message-latch-storm).
    if (GpuCurrent(hwnd, cr.right, cr.bottom)) {
        const bool batchDone = l.tag == lineoverlay::kTagTut2 || (l.tag == lineoverlay::kTagTut1 && Rd<int>(kVA_TutLine2X) < 0);
        if (batchDone) {
            g_presentOwed = false;
            GpuRepresent(hwnd, cr.right, cr.bottom);
            return;
        }
        g_presentOwed = true;
        if (!g_nullPosted || GetTickCount() - g_nullPostedAt >= kNullPostMs) {
            g_nullPosted = PostMessageA(hwnd, WM_NULL, 0, 0) != 0;
            g_nullPostedAt = GetTickCount();
        }
        return;
    }
    using lineoverlay::ToClient;
    g_lineRawOrig(self, edx, ToClient(x, cr.right, sw), ToClient(y, cr.bottom, sh), ToClient(x2, cr.right, sw),
                  ToClient(y2, cr.bottom, sh), color, lineoverlay::ClientPenWidth(width, style, cr.right, sw), style);
}

} // namespace

void WinLinesPoll()
{
    if (!g_presentOwed) return;
    g_presentOwed = false;
    HWND hwnd; RECT cr; int sw, sh;
    if (ScaledClient(&hwnd, &cr, &sw, &sh)) GpuRepresent(hwnd, cr.right, cr.bottom);   // stale meanwhile: the next flip
}

void WinLinesOnFlip(bool stretched, int l, int t, int r, int b)
{
    g_presentOwed = false;             // this flip's present carries the lines (or the window is not stretched)
    if (!stretched) { ClearLines(); return; }
    bool changed = PruneTutorialLines();
    if (l < r && t < b) changed = lineoverlay::OnFlip(g_lines, { l, t, r, b }) || changed;
    if (changed) PublishLines();
}

bool InstallWinLines()
{
    BYTE* site = reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (kVA_LineRaw - kImageBase);
    if (memcmp(site, kLineRawBytes, sizeof kLineRawBytes) != 0) return false;
    BYTE* tramp = static_cast<BYTE*>(VirtualAlloc(nullptr, 16, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (!tramp) return false;
    memcpy(tramp, site, 5);                                  // mov eax,[0x9B3AB0] (an absolute: position-independent)
    tramp[5] = 0xE9;
    const BYTE* resume = reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (kVA_LineRawResume - kImageBase);
    const DWORD back = reinterpret_cast<DWORD>(resume) - reinterpret_cast<DWORD>(tramp + 10);
    memcpy(tramp + 6, &back, 4);
    FlushInstructionCache(GetCurrentProcess(), tramp, 16);
    g_lineRawOrig = reinterpret_cast<FLineRaw>(tramp);
    BYTE jmp[5] = { 0xE9 };
    const DWORD rel = reinterpret_cast<DWORD>(&LineRawHook) - reinterpret_cast<DWORD>(site + 5);
    memcpy(jmp + 1, &rel, 4);
    DWORD prot;
    if (!VirtualProtect(site, 5, PAGE_EXECUTE_READWRITE, &prot)) return false;
    memcpy(site, jmp, 5);
    VirtualProtect(site, 5, prot, &prot);
    FlushInstructionCache(GetCurrentProcess(), site, 5);
    return true;
}
