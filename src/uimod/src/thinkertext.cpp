// thinkertext.cpp -- Thinker's own UI text, placed at our scale.
//
// Thinker (induktio/thinker 5.5) adds lines of its own to the base screen (basewin.cpp): the satellite bonus lines
// "N +1 / M +1 / E +1" and the stockpile-energy line in BaseWin_draw_farm_set_font, and the "Pop: T/W/D/S", pop-boom and
// nerve-staple lines in BaseWin_draw_energy_set_text_color. It writes them straight into the base canvas through the
// engine's Buffer_write_l_3 / Buffer_write_right_l_5 at VANILLA coordinates (x1 + 5, y2 - 36 - 28 ...; 690, 423 - 42
// ...; the resource-window rect it reads is the engine's native one), so under our scaled base screen they land at
// 1/2.5 of their place at 4K (probe 2026-10-29, hook_thinker_bwtext.js: "N +1" at (171,193) in the 1895x1225 canvas,
// "Pop:" at (690,381)). Their FONT is already ours: Thinker's set_font replacement is reached through the chained
// engine site (thinkercompat.cpp bw2.setfont_40f8f8), and draw_energy's text runs in the engine's current font.
//
// THE FIX: Thinker reaches the two writers through its own function pointers in .data (engine.h `extern
// FBuffer_write_l_3 Buffer_write_l_3;`). Those two pointers are swapped for wrappers that look at the RETURN ADDRESS:
// the seven base-screen call sites get x,y re-anchored by LAW popup_scale_floor (work\scripts\scaling_laws.py:
// floor(v * g / 16), the base window's own floor idiom), every other caller passes straight through -- the eco-damage
// line (BaseWin_draw_misc_eco_damage) already arrives with the engine's scaled x,y via our chain, and the "Thinker Mod
// v5.5 / date" label window_scale_load_pcx paints onto the main-menu-time backgrounds is screen-anchored (20, H-32).
// User decision 2026-10-30: scale all of Thinker's UI text; the version label is handled per kVersionLabel below.
// g <= 16 (1024x768 and below): nothing changes. Proportionate: every anchor = vanilla x g/16, same factor as the
// canvas; the 14-px native line step between the satellite lines becomes 14 * g/16, matching the scaled font.
//
// PINNED to thinker.dll 5.5 (TimeDateStamp + SizeOfImage from version.h); each pointer must hold the engine's
// writer and each listed site must be `call dword ptr [that pointer]` before anything is written.
// work\tests\test_thinker_text_sites.py checks this table against the DLL, completeness included (every call through
// either pointer is classified here).

#include "thinkertext.h"

#include <windows.h>
#include <intrin.h>
#pragma intrinsic(_ReturnAddress)
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "pssphere.h"        // PsSphereWouldBePop(): the numbers for the "Pop:" line on a sphere / stapled base
#include "thinkercompat.h"   // ThinkerLoaded() / ThinkerRange()
#include "version.h"        // UIMOD_THINKER_SUPPORTED_*: the Thinker build this half is measured on

void UimodLog(const char* msg);   // init.cpp

namespace {

constexpr uint32_t kStamp = UIMOD_THINKER_SUPPORTED_STAMP, kSizeOfImage = UIMOD_THINKER_SUPPORTED_IMAGE_SIZE;   // version.h: the one pin
constexpr uint32_t kPtrWriteL3 = 0xE456C;        // .data: FBuffer_write_l_3 Buffer_write_l_3 = 0x5DCEA0
constexpr uint32_t kPtrWriteRightL5 = 0xE4550;   // .data: FBuffer_write_right_l_5 Buffer_write_right_l_5 = 0x5DD3B0
constexpr uintptr_t kVA_WriteL3 = 0x005DCEA0;    // thiscall RET 0x10: (this, str, x, y, len), left-anchored
constexpr uintptr_t kVA_WriteRightL5 = 0x005DD3B0;   // thiscall RET 0x10: (this, str, x, y, len), right-anchored at x
constexpr uintptr_t kVA_PopupScaleNum = 0x00668740;  // g_popup_scale_num (patcher cell; 0 or 16 = native)
// The gate of the base-window text family (patches.yaml basewin slice 2, thunk_bw_xy_core): the draw's dest must be
// THE BaseWin canvas and that canvas must be the ENLARGED one (its width past the native 758) -- the live observable,
// never g alone (a g > 16 run whose canvas is still native would otherwise push the lines off a 758-wide buffer).
constexpr uintptr_t kVA_BaseWinCanvas = 0x006A7A6C;  // Buffer; width at +0x80 (= 0x6A7AEC)
constexpr int kBaseCanvasNativeW = 758;

// Thinker's "Thinker Mod v5.5 / <date>" label on the credits / interlude backgrounds (drawn only while the game is
// halted, i.e. from the main menu) at (20, H - 32) in MapWin's label font, which our Base Font Size slider re-inits:
// at a large slider value the face overran the native 32-px bottom margin. User decision 2026-10-30: KEEP it, on a
// SCALED margin -- x = floor(20 * g/16), y = H - floor(32 * g/16) (the proportionate rule on Thinker's two literals).
// 'D' would drop it instead.
constexpr char kVersionLabel = 'K';
constexpr int kLabelX = 20, kLabelBottomMargin = 32;   // Thinker's literals (gui.cpp window_scale_load_pcx)

// mode: 'S' = re-anchor x,y (base canvas, native coordinates); 'N' = re-anchor AND renumber (the "Pop: T/W/D/S" line
// prints the LIVE record's totals, which a sphere / staple has zeroed; under our badged would-be row the four numbers
// are replaced with the would-be talents / workers / drones / specialists -- user decision 2026-10-30. Thinker's
// painter itself keeps reading the live record, so its riot / golden-age colour and its pop-boom and staple lines
// stay what the engine will actually do); 'P' = pass through (already scaled, or screen-anchored); 'L' = the version
// label (see kVersionLabel).
struct TextSite { uint32_t site; uint32_t ptr; char mode; const char* what; };
const TextSite kSites[] = {
    { 0x1466C, kPtrWriteL3,      'P', "BaseWin_draw_misc_eco_damage: the engine's x,y, scaled by our chain already" },
    { 0x1499B, kPtrWriteL3,      'S', "satellite nutrient line (x1 + 5, y2 - 64)" },
    { 0x14A1C, kPtrWriteL3,      'S', "satellite mineral line (x1 + 5, y2 - 50)" },
    { 0x14A9D, kPtrWriteL3,      'S', "satellite energy line (x1 + 5, y2 - 36)" },
    { 0x3E59A, kPtrWriteL3,      'L', "window_scale_load_pcx: the version label at (20, H - 32) on the menu-time backgrounds" },
    { 0x14908, kPtrWriteRightL5, 'S', "stockpile energy line (x2 - 5, y2 - 36)" },
    { 0x14C9E, kPtrWriteRightL5, 'N', "Pop: T/W/D/S (690, 381): renumbered with the would-be totals" },
    { 0x14D45, kPtrWriteRightL5, 'S', "pop boom (690, 402)" },
    { 0x14DF2, kPtrWriteRightL5, 'S', "nerve staple turns (690, 423)" },
};

// Thinker formats the line with label_pop_size (gui.cpp; thinker.ini may override it; parse_format_args admits at
// most four conversions, each a bare %d / %i / %u, plus %% -- strings.cpp count_format_args). The live format is read
// from Thinker's own array and walked in step with the formatted string: literal text must match, each conversion
// consumes the live number and emits the would-be value in T / W / D / S order. Any mismatch (a label the walk does
// not reproduce, a sphere-free base, no fresh totals) leaves the string untouched. Audit 2026-10-30: counting digit
// runs instead would mis-slot a label with a literal digit ("P2: ...") and eat hyphen separators.
constexpr uint32_t kLabelPopSize = 0xE6780;      // .data: char label_pop_size[StrBufLen = 256]
constexpr uint32_t kLabelPopSizeRef = 0x14C55;   // the painter's `mov dword ptr [esp+8], label_pop_size` before its snprintf
constexpr size_t kStrBufLen = 256;
bool g_popFmtOk = false;
const char* RenumberPop(const char* in, char* out, size_t n);   // below, after the state it reads
// thiscall through a fastcall shape: ecx = this, edx = unused, the rest on the stack, callee cleans -- byte for byte
// the same ABI, and it lets a free function stand in for the engine's method.
using FWrite = int(__fastcall*)(void* self, void* edx, const char* str, int x, int y, int len);

BYTE*  g_base = nullptr;
FWrite g_writeL3 = nullptr;
FWrite g_writeRightL5 = nullptr;

void Log(const char* fmt, ...)
{
    char s[512];
    va_list ap;
    va_start(ap, fmt);
    _vsnprintf_s(s, sizeof s, _TRUNCATE, fmt, ap);
    va_end(ap);
    UimodLog(s);
}

BYTE* At(uintptr_t va) { return reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)) + (va - 0x400000); }

inline int ScaleFloor(int v, int g) { return (v * g) >> 4; }   // LAW popup_scale_floor (scaling_laws.py)

const char* RenumberPop(const char* in, char* out, size_t n)
{
    int v[4];
    if (!g_popFmtOk || !PsSphereWouldBePop(&v[0], &v[1], &v[2], &v[3])) return in;
    const char* f = reinterpret_cast<const char*>(g_base + kLabelPopSize);
    const char* const fend = f + kStrBufLen;
    const char* s = in;
    size_t o = 0;
    int k = 0;
    while (f < fend && *f) {
        if (*f == '%' && (f[1] == 'd' || f[1] == 'i' || f[1] == 'u')) {
            if (k >= 4 || !(*s >= '0' && *s <= '9') || o + 12 >= n) return in;
            while (*s >= '0' && *s <= '9') ++s;              // the live number
            const int w = _snprintf_s(out + o, n - o, _TRUNCATE, "%d", v[k++]);
            if (w < 0) return in;
            o += static_cast<size_t>(w);
            f += 2;
        } else if (*f == '%' && f[1] == '%') {
            if (*s != '%' || o + 1 >= n) return in;
            out[o++] = *s++;
            f += 2;
        } else {
            if (*s != *f || o + 1 >= n) return in;
            out[o++] = *s++;
            ++f;
        }
    }
    if (*s) return in;                                       // the string must be the format and nothing more
    out[o] = '\0';
    return out;
}

// The site a call came from (the return address is the byte after the 6-byte `call dword ptr [ptr]`), or nullptr.
const TextSite* SiteOf(const void* ret)
{
    const uintptr_t off = reinterpret_cast<const BYTE*>(ret) - g_base;
    for (const TextSite& s : kSites)
        if (off == s.site + 6) return &s;
    return nullptr;
}

// Returns false when the draw is to be skipped altogether; *str may be re-pointed at a renumbered copy.
bool Place(const void* ret, const void* self, const char** str, int* x, int* y)
{
    const TextSite* s = SiteOf(ret);
    if (!s) return true;
    if (s->mode == 'N') {
        static char buf[256];
        *str = RenumberPop(*str, buf, sizeof buf);
    }
    if (s->mode == 'L') {
        if constexpr (kVersionLabel == 'D') return false;
        const int g = *reinterpret_cast<const int*>(At(kVA_PopupScaleNum));
        if (g > 16 && *x == kLabelX) {                           // the background is screen-sized: only the margins scale
            *x = ScaleFloor(kLabelX, g);
            *y += kLabelBottomMargin - ScaleFloor(kLabelBottomMargin, g);
        }
        return true;
    }
    if (s->mode != 'S' && s->mode != 'N') return true;
    if (self != At(kVA_BaseWinCanvas) || *reinterpret_cast<const int*>(At(kVA_BaseWinCanvas + 0x80)) <= kBaseCanvasNativeW)
        return true;                                             // not the enlarged base canvas: native placement
    const int g = *reinterpret_cast<const int*>(At(kVA_PopupScaleNum));
    if (g <= 16) return true;
    *x = ScaleFloor(*x, g);
    *y = ScaleFloor(*y, g);
    return true;
}

int __fastcall WrapWriteL3(void* self, void* edx, const char* str, int x, int y, int len)
{
    if (!Place(_ReturnAddress(), self, &str, &x, &y)) return 0;
    return g_writeL3(self, edx, str, x, y, len);
}

int __fastcall WrapWriteRightL5(void* self, void* edx, const char* str, int x, int y, int len)
{
    if (!Place(_ReturnAddress(), self, &str, &x, &y)) return 0;
    return g_writeRightL5(self, edx, str, x, y, len);
}

bool WriteData(BYTE* p, const void* bytes, size_t n)
{
    DWORD old;
    if (!VirtualProtect(p, n, PAGE_READWRITE, &old)) return false;
    memcpy(p, bytes, n);
    VirtualProtect(p, n, old, &old);
    return true;
}

bool IsCallThrough(const BYTE* site, uint32_t ptrOff)   // FF 15 <absolute address of the pointer variable>
{
    if (site[0] != 0xFF || site[1] != 0x15) return false;
    uint32_t abs; memcpy(&abs, site + 2, 4);
    return abs == static_cast<uint32_t>(reinterpret_cast<uintptr_t>(g_base + ptrOff));
}

} // namespace

void InstallThinkerText()
{
    uintptr_t lo, hi;
    if (!ThinkerLoaded() || !ThinkerRange(&lo, &hi)) return;
    g_base = reinterpret_cast<BYTE*>(lo);

    const IMAGE_DOS_HEADER* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(g_base);
    const IMAGE_NT_HEADERS32* nt = reinterpret_cast<const IMAGE_NT_HEADERS32*>(g_base + dos->e_lfanew);
    if (nt->FileHeader.TimeDateStamp != kStamp || nt->OptionalHeader.SizeOfImage != kSizeOfImage) {
        Log("[uimod] thinker: thinker.dll (stamp 0x%08X, image 0x%X) is not the 5.5 build this mod places text for "
            "(0x%08X, 0x%X) -> Thinker's base-screen lines stay at their native places\n",
            static_cast<unsigned>(nt->FileHeader.TimeDateStamp), static_cast<unsigned>(nt->OptionalHeader.SizeOfImage), kStamp, kSizeOfImage);
        return;
    }
    // every check before any write
    uint32_t p3, p5;
    memcpy(&p3, g_base + kPtrWriteL3, 4);
    memcpy(&p5, g_base + kPtrWriteRightL5, 4);
    const char* bad = nullptr;   // the FIRST failing check is the one reported
    if (p3 != reinterpret_cast<uintptr_t>(At(kVA_WriteL3))) bad = "Thinker's Buffer_write_l_3 pointer";
    if (!bad && p5 != reinterpret_cast<uintptr_t>(At(kVA_WriteRightL5))) bad = "Thinker's Buffer_write_right_l_5 pointer";
    for (const TextSite& s : kSites)
        if (!bad && !IsCallThrough(g_base + s.site, s.ptr)) bad = s.what;
    if (bad) {
        Log("[uimod] thinker: %s does not hold the expected 5.5 bytes (another mod on thinker.dll?) -> Thinker's "
            "base-screen lines stay at their native places\n", bad);
        return;
    }

    // the Pop line's format: the painter must reference Thinker's label_pop_size where the table says (else the line
    // keeps Thinker's live numbers and says so)
    {
        BYTE ref[8] = { 0xC7, 0x44, 0x24, 0x08 };
        const uint32_t abs = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(g_base + kLabelPopSize));
        memcpy(ref + 4, &abs, 4);
        g_popFmtOk = memcmp(g_base + kLabelPopSizeRef, ref, sizeof ref) == 0;
        if (!g_popFmtOk)
            UimodLog("[uimod] thinker: the energy-tab painter does not reference label_pop_size where expected -> the "
                     "\"Pop:\" line keeps Thinker's live numbers on a sphere / stapled base\n");
    }

    g_writeL3 = reinterpret_cast<FWrite>(At(kVA_WriteL3));
    g_writeRightL5 = reinterpret_cast<FWrite>(At(kVA_WriteRightL5));
    const uint32_t w3 = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(&WrapWriteL3));
    const uint32_t w5 = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(&WrapWriteRightL5));
    const bool ok3 = WriteData(g_base + kPtrWriteL3, &w3, 4);
    const bool ok5 = WriteData(g_base + kPtrWriteRightL5, &w5, 4);
    int scaled = 0;
    for (const TextSite& s : kSites) scaled += (s.mode == 'S' || s.mode == 'N') ? 1 : 0;
    Log("[uimod] thinker: base-screen text: %d Thinker lines re-anchored at x,y * g/16 (satellite N/M/E, stockpile, "
        "Pop/boom/staple; the Pop line renumbered with the would-be totals on a sphere / stapled base)%s; eco-damage "
        "passes through; version label %s; pointers %s/%s\n",
        scaled, (ok3 && ok5) ? "" : " PARTIALLY", kVersionLabel == 'D' ? "dropped" : "kept on a scaled margin",
        ok3 ? "write_l_3 wrapped" : "write_l_3 NOT wrapped", ok5 ? "write_right_l_5 wrapped" : "write_right_l_5 NOT wrapped");
}
