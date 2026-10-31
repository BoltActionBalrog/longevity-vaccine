// mapscroll.cpp -- smooth map scrolling under PRACX (see mapscroll.h).
//
// ENGINE FACTS (pristine exe, 2026-10-10; symbols in work\symbols\terranx.h, specs in memory
// project-smac-drag-scroll-perf):
//   * The map draws into the Console's GraphicWin canvas (Console+0x23D94, Buffer at +0x444: data +0x54, stride
//     +0x4A8, w +0x80, -h +0x84, clip RECT +0x20, bounds RECT +0x30). Win_update_screen composites it to the screen.
//   * MapWin_calculate_dimensions 0x462980 derives the view from the centre tile (+0x1DD9C/+0x1DDA0): origin
//     iMapTileLeft/Top (+0x1DDA4/+0x1DDA8), the tile counts OddX/OddY/EvenX/EvenY (+0x1DDCC..+0x1DDD8), the pixel
//     steps (+0x1DDBC = 4z per x unit, +0x1DDC0 = 2z per row, z = +0x1DDC8) and zeroes the sub-tile offsets
//     iMapPixelLeft/Top (+0x1DDAC/+0x1DDB0). PRACX's wrapper around draw_map's call to it (the rel32 at 0x46A5AA
//     is PRACX's at startup) then writes the offsets = (int)m_dScrollOffsetX/Y while m_fScrolling.
//   * MapWin_tile_to_pixel: px = (x - left - 1) * 4z + offX; py = (y - top - 1) * 2z + offY - altitude(tile).
//     So a view change moves every tile on screen by dx = fold(oldLeft - newLeft) * 4z + (newOffX - oldOffX),
//     dy = (oldTop - newTop) * 2z + (newOffY - oldOffY) (the per-tile altitude cancels; fold = the round-map
//     wrap into (-MapX/2, MapX/2]). dx > 0 = the content moves right.
//   * MapWin_draw_map's scroll path (Console+0x21A44 != 0, whole-tile only -- the entry gate clears the flag for a
//     sub-tile offset): self-blit Buffer_copy_4(canvas -> canvas, max(-dx,0), max(-dy,0), max(dx,0), max(dy,0),
//     W, H) @0x46A93B; GraphicWin_fill_3(GW, X, Y, W, H, 0) over the exposed x strip ((0,0,dx,H) or
//     (W-|dx|,0,|dx|,H)) and y strip ((0,0,W,dy) or (0,H-|dy|,W,|dy|)); the exposed-tile rects +0x21A48 (x strip:
//     L, T, R, B) and +0x21A58 (y strip) -- x half-open [L,R) in map x units with the round-map band when L > R,
//     y inclusive [T,B]; then MapWin_gen_map(owner, 0) under Buffer_set_clip(canvas, strip) once (one strip) or
//     twice (both; the y strip's clip top is extended by 10 px; the second call collapses the x rect, the first
//     sets the y rect's L to the x rect's R so the corner is drawn once); gen_map with the flag set skips the
//     clear and draws only the tiles inside either rect (terrain) / either rect widened by 2 (units); base names,
//     legend and wars still run clipped. Then: the cursor diamond POINT[4] @0x7D3BE8 -= (dx, dy); set_clip(canvas,
//     bounds). gen_map's owner = (GameState 0x9A64C0 & 0x80) ? -1 : CurrentPlayerFaction 0x939284.
//   * PRACX wraps the 4 gen_map call sites inside draw_map (PRACXDrawMap, prax.dll +0x5BA0, thiscall thunk
//     +0x5E50): with a sub-tile offset it adds one column / row on the exposed side (left/top when the offset is
//     positive) before calling gen_map and restores the fields after -- so calling gen_map through that thunk
//     renders the partial edge tiles.
//   * Our thunk_minimap_force sits at draw_map's entry (minimap box tracking on view change): bypassed here, so
//     WorldWin_on_redraw 0x4C3EC0 is called per step instead (0.1 ms).
// PRACX FACTS (prax.dll 1.11, md5 89a0037b stock / 0f189a32 with the patcher's scroll-zone fix; DYNAMIC_BASE):
//   ACADDRESSES_T m_STACAddresses @+0x47000 (pfncZoomProcessing +0x18, pMain +0x1C, pfncMoveMap +0x38,
//   pfncRedrawMap +0x3C, pfncDrawMap +0x40), m_pAC @+0x470E4 (-> the table), m_fScrolling @+0x4809F (byte),
//   m_dScrollOffsetX/Y @+0x480C0/+0x480C8 (doubles). DoScroll (the drag / edge-scroll loop): adjusts the centre
//   tile by +-2 per 8z / 4z of pointer travel, keeps the remainder in m_dScrollOffset, then
//   m_pAC->pfncRedrawMap(pMain, 0), pfncPaintHandler, pfncPaintMain (present). SetTerrainMode / SetResourceMode
//   call pfncRedrawMap too, with m_fScrolling == 0 (-> the full draw, as before).
#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>

#include "mapscroll.h"
#include "modernctl.h"

void UimodLog(const char* msg);
void UimodDbg(const char* msg);
bool UimodDebugLogOn();

namespace {

void IniPath(char* out, size_t n)
{
    GetModuleFileNameA(nullptr, out, static_cast<DWORD>(n));
    char* slash = strrchr(out, '\\');
    if (slash) slash[1] = '\0';
    lstrcatA(out, "Alpha Centauri.ini");
}

constexpr uintptr_t kImageBase = 0x00400000;
BYTE* At(uintptr_t va) { return reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (va - kImageBase); }
template <typename T> T RdP(const BYTE* p) { T v; memcpy(&v, p, sizeof v); return v; }
template <typename T> void WrP(BYTE* p, T v) { memcpy(p, &v, sizeof v); }

// ---- engine ---------------------------------------------------------------------------------------------
constexpr uintptr_t kVA_Console        = 0x9156B0;
constexpr uintptr_t kVA_DrawMap        = 0x46A550;   // MapWin_draw_map(this, a2) thiscall RET 4 (entry = thunk_minimap_force)
constexpr uintptr_t kVA_GWinFill3      = 0x5D5440;   // GraphicWin_fill_3(this=GW; x, y, w, h, color)
constexpr uintptr_t kVA_BufferSetClip  = 0x5D8000;   // Buffer_set_clip(this; RECT*) RET 4
constexpr uintptr_t kVA_WorldWinRedraw = 0x4C3EC0;   // WorldWin_on_redraw(this=WorldWin)
constexpr uintptr_t kVA_WorldWin       = 0x8E9F60;
constexpr uintptr_t kVA_MapAreaX       = 0x949870;
constexpr uintptr_t kVA_MapAreaY       = 0x949874;
constexpr uintptr_t kVA_MapFlags       = 0x94988C;   // bit 0 = flat map
constexpr uintptr_t kVA_GameState      = 0x9A64C0;
constexpr uintptr_t kVA_CurFaction     = 0x939284;
constexpr uintptr_t kVA_CursorDiamond  = 0x7D3BE8;   // POINT[4], shifted with the frame
constexpr size_t kConGWin = 0x23D94, kGWCanvas = 0x444;
constexpr size_t kConCX = 0x1DD9C, kConCY = 0x1DDA0, kConLeft = 0x1DDA4, kConTop = 0x1DDA8, kConOffX = 0x1DDAC,
                 kConOffY = 0x1DDB0, kConStepX = 0x1DDBC, kConStepY = 0x1DDC0, kConZ = 0x1DDC8, kConOddX = 0x1DDCC,
                 kConOddY = 0x1DDD0, kConEvenX = 0x1DDD4, kConEvenY = 0x1DDD8, kConDrag = 0x1DD80,
                 kConScrollFlag = 0x21A44, kConXRect = 0x21A48, kConYRect = 0x21A58;
constexpr size_t kBufClip = 0x20, kBufBounds = 0x30, kBufData = 0x54, kBufW = 0x80, kBufH = 0x84, kBufStride = 0x4A8;
// the engine sites whose behaviour this module mirrors: checked so a different exe disables the feature
constexpr uintptr_t kVA_SiteSelfBlit = 0x46A93B, kVA_SiteGenMap1 = 0x46ABD1, kVA_SiteCalcDim = 0x46A5A9;
const BYTE kSelfBlitBytes[5] = { 0xE8, 0xC0, 0x55, 0x17, 0x00 };   // call Buffer_copy_4
const BYTE kGateBytes[8] = { 0x8B, 0x86, 0xAC, 0xDD, 0x01, 0x00, 0x89, 0x7D };   // draw_map 0x46A55D: the offset gate
const BYTE kGenMapPrologue[6] = { 0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x38 };
const BYTE kFill3Pro[4]    = { 0x8B, 0x44, 0x24, 0x14 };                  // GraphicWin_fill_3: mov eax, [esp+0x14] (its 5th arg)
const BYTE kSetClipPro[3]  = { 0x83, 0xEC, 0x40 };                        // Buffer_set_clip: sub esp, 0x40
const BYTE kWorldWinPro[5] = { 0xA1, 0x6C, 0x1E, 0x69, 0x00 };            // WorldWin_on_redraw: mov eax, [0x691E6C]

// ---- PRACX ----------------------------------------------------------------------------------------------
constexpr uintptr_t kPx_Table = 0x47000, kPx_pAC = 0x470E4, kPx_fScrolling = 0x4809F;
constexpr uintptr_t kPx_ScrollOffY = 0x480C8;    // double m_dScrollOffsetY (verify mode only: the full redraw must use the nudged row)
constexpr uintptr_t kPx_ScrollingSet = 0x514F;   // DoScroll: C6 05 <m_fScrolling> 01   (mov byte [m_fScrolling], 1)
constexpr uintptr_t kPx_OffYRead = 0x4930;       // DoScroll: F2 0F 2C 15 <m_dScrollOffsetY> (cvttsd2si edx, [m_dScrollOffsetY])
const BYTE kScrollingSetOp[2] = { 0xC6, 0x05 };
const BYTE kOffYReadOp[4] = { 0xF2, 0x0F, 0x2C, 0x15 };
constexpr uintptr_t kPx_DrawMapThunk = 0x5E50, kPx_DrawMapFn = 0x5BA0, kPx_ZoomThunk = 0x9930, kPx_ZoomFn = 0x9600;
constexpr size_t kTab_Zoom = 0x18, kTab_Main = 0x1C, kTab_MoveMap = 0x38, kTab_RedrawMap = 0x3C, kTab_DrawMap = 0x40;
const BYTE kThunkDrawMap[8] = { 0x58, 0x51, 0x50, 0xE9, 0x48, 0xFD, 0xFF, 0xFF };   // pop eax; push ecx; push eax; jmp PRACXDrawMap
const BYTE kThunkZoom[8]    = { 0x58, 0x51, 0x50, 0xE9, 0xC8, 0xFC, 0xFF, 0xFF };   // -> PRACXZoomProcessing
const BYTE kDrawMapFnPro[6] = { 0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x2C };

using FDrawMap   = int(__fastcall*)(BYTE* con, void* edx, int a2);
using FFill3     = void(__fastcall*)(BYTE* gw, void* edx, int x, int y, int w, int h, int color);
using FSetClip   = void(__fastcall*)(BYTE* buf, void* edx, RECT* r);
using FGenMap    = int(__fastcall*)(BYTE* con, void* edx, int owner, int unitsOnly);
using FThis      = int(__fastcall*)(BYTE* self, void* edx);
using FMoveMap   = int(__fastcall*)(BYTE* con, void* edx, int x, int y, int a4);   // MapWin_set_center 0x46B1F0 (PRACX's pfncMoveMap)

BYTE* g_px = nullptr;
BYTE* g_table = nullptr;
bool  g_bound = false;
int   g_on = kSmoothScrollDefault;
int   g_verify = 0;
FDrawMap g_origRedraw = nullptr;        // what the table held (MapWin_draw_map)
FMoveMap g_origMoveMap = nullptr;       // what the table held (MapWin_set_center)
bool  g_pendingSettle = false;          // the canvas shows a shifted frame that no full draw has replaced yet
FGenMap  g_genMap = nullptr;            // PRACX's gen_map wrapper (adds the partial edge column / row)
FThis    g_calcDim = nullptr;           // PRACX's calculate_dimensions wrapper (writes the sub-tile offsets)
int   g_steps = 0, g_full = 0;
void Phase(const char* what, int a = 0, int b = 0, int c = 0, int d = 0)   // breadcrumbs: the last line names the phase a crash died in
{                                                                          // (DebugLog=1 only: a player's log holds load/install/warnings)
    if (g_steps >= 400 && (g_steps % 50) != 0) return;
    char m[160];
    _snprintf_s(m, sizeof m, _TRUNCATE, "[uimod] mapscroll: #%d %s %d %d %d %d\n", g_steps, what, a, b, c, d);
    UimodDbg(m);
}
BYTE* g_scratch = nullptr; size_t g_scratchLen = 0;   // verify mode

BYTE* Console() { return At(kVA_Console); }
int   C(size_t off) { return RdP<int>(Console() + off); }
BYTE* GWin() { return Console() + kConGWin; }
BYTE* Canvas() { return GWin() + kGWCanvas; }
bool  FlatMap() { return (RdP<BYTE>(At(kVA_MapFlags)) & 1) != 0; }
int   MapX() { return RdP<int>(At(kVA_MapAreaX)); }
int   MapY() { return RdP<int>(At(kVA_MapAreaY)); }

int WrapX(int x)            // one wrap, as the engine (never modulo)
{
    if (FlatMap()) return x;
    const int mx = MapX();
    if (x < 0) return x + mx;
    if (x >= mx) return x - mx;
    return x;
}
int FoldX(int d)            // a tile-x difference folded into (-MapX/2, MapX/2]
{
    if (FlatMap()) return d;
    const int mx = MapX();
    if (d > mx / 2) return d - mx;
    if (d < -mx / 2) return d + mx;                                       // the engine's tie-break (tile_to_pixel 0x462FB8 keeps -MapX/2)
    return d;
}
int FloorDiv(int a, int b) { return a >= 0 ? a / b : -((-a + b - 1) / b); }
int CeilDiv(int a, int b)  { return a >= 0 ? (a + b - 1) / b : -((-a) / b); }

void Log(const char* fmt, int a = 0, int b = 0, int c = 0, int d = 0, int e = 0, int f = 0)
{
    char m[256];
    _snprintf_s(m, sizeof m, _TRUNCATE, fmt, a, b, c, d, e, f);
    UimodLog(m);
}
void Dbg(const char* fmt, int a = 0, int b = 0, int c = 0, int d = 0, int e = 0, int f = 0)   // DebugLog=1 only
{
    if (!UimodDebugLogOn()) return;
    Log(fmt, a, b, c, d, e, f);
}

int Owner() { return (RdP<BYTE>(At(kVA_GameState)) & 0x80) ? -1 : RdP<int>(At(kVA_CurFaction)); }

// The scroll step. Entered from PRACX's loop in place of MapWin_draw_map(con, a2). Returns true when handled.
bool ScrollStep(BYTE* con)
{
    // the canvas state = what the last draw left in the Console (every draw path runs calculate_dimensions)
    const int oLeft = C(kConLeft), oTop = C(kConTop), oOffX = C(kConOffX), oOffY = C(kConOffY), oZ = C(kConZ);
    const int oOddX = C(kConOddX), oOddY = C(kConOddY), oEvenX = C(kConEvenX), oEvenY = C(kConEvenY);
    BYTE* canvas = Canvas();
    const int W = RdP<int>(canvas + kBufW), H = -RdP<int>(canvas + kBufH);
    if (W <= 0 || H <= 0 || RdP<BYTE*>(canvas + kBufData) == nullptr) return false;
    if (C(kConDrag) != 0) return false;                                   // an engine go-to drag: let draw_map redraw its line
    if (memcmp(canvas + kBufClip, canvas + kBufBounds, sizeof(RECT)) != 0) return false;   // mid-draw state: not ours

    g_calcDim(con, nullptr);                                              // the new view (+ PRACX's sub-tile offsets)
    const int nLeft = C(kConLeft), nTop = C(kConTop), nOffX = C(kConOffX), nOffY = C(kConOffY), nZ = C(kConZ);
    const int nOddX = C(kConOddX), nOddY = C(kConOddY), nEvenX = C(kConEvenX), nEvenY = C(kConEvenY);
    if (nZ != oZ || nOddX != oOddX || nOddY != oOddY || nEvenX != oEvenX || nEvenY != oEvenY) return false;
    const int Wn = nOddX + nEvenX, Hn = nOddY + nEvenY;
    if (Wn >= MapX() || Hn >= MapY()) return false;                      // the view spans the map: the engine's strip maths is wrong there
    const int stepX = C(kConStepX), stepY = C(kConStepY);
    if (stepX <= 0 || stepY <= 0) return false;

    const int dx = FoldX(oLeft - nLeft) * stepX + (nOffX - oOffX);
    int dy = (oTop - nTop) * stepY + (nOffY - oOffY);
    // The terrain's dither has a TWO-ROW phase tied to the destination row (verify runs 2026-10-10: every odd
    // vertical shift mismatched ~80% of the frame, every even one matched), and the engine's own whole-tile
    // shifts are always even. So an odd shift is pulled one pixel toward zero by nudging the sub-tile offset
    // the engine draws with: the fresh strips, hit-testing and the next step all see the nudged value (PRACX's
    // own offset is untouched, so there is no drift -- the view sits at most 1 px from where PRACX put it).
    int nudged = 0;
    if (dy & 1) {
        nudged = dy > 0 ? -1 : 1;
        WrP<int>(con + kConOffY, nOffY + nudged);
        dy += nudged;
    }
    const int nOffYd = C(kConOffY);                                       // the offset the strips are drawn with
    if (dx == 0 && dy == 0) return true;                                  // nothing moved (PRACX still presents)
    if (dx >= W || -dx >= W || dy >= H || -dy >= H) return false;
    ModernCtlMapScrollStep();                                             // the hover move-to line is screen-fixed: hide it for the scroll
    Phase("shift", dx, dy, W, H);
    // 1. shift the frame. NOT the engine's Buffer_copy_4 self-blit: its backward copy's byte-remainder loop reads
    //    one byte BEFORE the buffer when a row's byte count is not a multiple of 4 (crash dump 2026-10-09 22:46,
    //    rep movsb @0x5E076D with esi = data - 1; vanilla's whole-tile shifts are multiples of 8 px, so it never
    //    trips it). A row-wise memmove in the right row order is overlap-safe for any shift.
    {
        GdiFlush();                                                       // text goes onto the canvas through GDI: no batched draw may land after the shift
        BYTE* data = RdP<BYTE*>(canvas + kBufData);
        const int stride = RdP<int>(canvas + kBufStride);
        const int rowBytes = W - (dx < 0 ? -dx : dx), rows = H - (dy < 0 ? -dy : dy);
        const int sx = dx < 0 ? -dx : 0, tx = dx > 0 ? dx : 0, sy = dy < 0 ? -dy : 0, ty = dy > 0 ? dy : 0;
        if (dy > 0) { for (int y = rows - 1; y >= 0; --y) memmove(data + (ty + y) * stride + tx, data + (sy + y) * stride + sx, rowBytes); }
        else        { for (int y = 0; y < rows; ++y)      memmove(data + (ty + y) * stride + tx, data + (sy + y) * stride + sx, rowBytes); }
    }
    POINT* pts = reinterpret_cast<POINT*>(At(kVA_CursorDiamond));
    for (int i = 0; i < 4; ++i) { pts[i].x -= dx; pts[i].y -= dy; }

    // 2. the exposed strips (pixels) and their fills. The engine's own scroll path fills with 0 (black), but a
    //    full redraw clears to 0x41 (gen_map's GraphicWin_clear) and only map tiles repaint over it -- a strip that
    //    reaches past the map's edge must show the clear colour, not black (verify dump 2026-10-10: 174,948 px of
    //    (0 vs 65) in a strip exposed above the map's first row).
    constexpr int kClearColor = 0x41;
    RECT xs = { 0, 0, 0, 0 }, ys = { 0, 0, 0, 0 };
    FFill3 fill = reinterpret_cast<FFill3>(At(kVA_GWinFill3));
    if (dx > 0)      { xs = { 0, 0, dx, H };        fill(GWin(), nullptr, 0, 0, dx, H, kClearColor); }
    else if (dx < 0) { xs = { W + dx, 0, W, H };    fill(GWin(), nullptr, W + dx, 0, -dx, H, kClearColor); }
    if (dy > 0)      { ys = { 0, 0, W, dy };        fill(GWin(), nullptr, 0, 0, W, dy, kClearColor); }
    else if (dy < 0) { ys = { 0, H + dy, W, H };    fill(GWin(), nullptr, 0, H + dy, W, -dy, kClearColor); }

    // 3. the tile filter rects (map units; generous: a filter only, the clip bounds the pixels). Columns: x unit
    //    u sits at pixel (u - left - 1) * stepX + offX; rows: y at (y - top - 1) * stepY + offY - altitude. Margins:
    //    x units -2/+2 around the strip's columns (the engine's rect is -1/+1; its units loop widens by 2 more
    //    itself), rows -4/+4 (the engine's: a tile up to 4 rows below the strip can lift into it by its altitude).
    //    A round map's x ends wrap; a span that reaches the map's width is the whole band [0, MapX) -- wrapping
    //    both ends would land R at or before L and gen_map would read a 0-3 unit range, not the band.
    int xr[4] = { 0, 0, 0, 0 }, yr[4] = { 0, 0, 0, 0 };
    auto xSpan = [&](int L, int R, int* out) {
        if (FlatMap()) { if (L < -4) L = -4; if (R > MapX() + 4) R = MapX() + 4; if (L >= R) R = L + 1; }
        else if (R - L >= MapX()) { L = 0; R = MapX(); }
        else { L = WrapX(L); R = WrapX(R); }
        out[0] = L; out[2] = R;
    };
    if (dx != 0) {
        xSpan(nLeft + 1 + FloorDiv(xs.left - nOffX, stepX) - 2, nLeft + 1 + CeilDiv(xs.right - nOffX, stepX) + 2, xr);
        xr[1] = nTop - 4; xr[3] = nTop + Hn + 4;
    }
    if (dy != 0) {
        xSpan(nLeft - 2, nLeft + Wn + 2, yr);
        yr[1] = nTop + 1 + FloorDiv(ys.top - nOffYd, stepY) - 4;
        yr[3] = nTop + 1 + CeilDiv(ys.bottom - nOffYd, stepY) + 4;
    }
    memcpy(con + kConXRect, xr, sizeof xr);
    memcpy(con + kConYRect, yr, sizeof yr);
    Phase("rects x", xr[0], xr[1], xr[2], xr[3]);
    Phase("rects y", yr[0], yr[1], yr[2], yr[3]);

    // 4. the strip renders through the engine's filtered gen_map (via PRACX's wrapper), as draw_map sequences them
    FSetClip setClip = reinterpret_cast<FSetClip>(At(kVA_BufferSetClip));
    const int owner = Owner();
    const bool haveX = dx != 0, haveY = dy != 0;
    if (haveY) ys.top -= 10;                                              // the engine's own widening of the y strip's clip
    // the "other" rect while one strip draws: far off the map. A zero rect is empty for the terrain filter but
    // the units / overlay loops widen their rect by 2 first and would still render tiles (0,0), (1,1), (0,2).
    static const int kNone[4] = { -100, -100, -100, -100 };
    const int flag0 = C(kConScrollFlag);
    WrP<int>(con + kConScrollFlag, 1);
    if (haveX) {                                                          // the x strip alone
        memcpy(con + kConYRect, kNone, sizeof kNone);
        Phase("genmap x", xs.left, xs.top, xs.right, xs.bottom);
        setClip(canvas, nullptr, &xs);
        g_genMap(con, nullptr, owner, 0);
    }
    if (haveY) {                                                          // the y strip alone
        memcpy(con + kConXRect, kNone, sizeof kNone);
        memcpy(con + kConYRect, yr, sizeof yr);
        Phase("genmap y", ys.left, ys.top, ys.right, ys.bottom);
        setClip(canvas, nullptr, &ys);
        g_genMap(con, nullptr, owner, 0);
    }
    WrP<int>(con + kConScrollFlag, flag0);
    setClip(canvas, nullptr, reinterpret_cast<RECT*>(canvas + kBufBounds));
    Phase("worldwin");
    reinterpret_cast<FThis>(At(kVA_WorldWinRedraw))(At(kVA_WorldWin), nullptr);   // the minimap viewport box
    Phase("done");

    g_pendingSettle = true;
    if (g_steps < 6 || g_verify) {
        Dbg("[uimod] mapscroll: step dx=%d dy=%d (lattice %d,%d) xstrip %d px, ystrip %d px\n", dx, dy,
            FoldX(oLeft - nLeft) * stepX, (oTop - nTop) * stepY, xs.right - xs.left, ys.bottom - (ys.top + (haveY ? 10 : 0)));
    }
    if (g_verify) {                                                       // the full redraw is the truth: compare, keep it
        const int stride = RdP<int>(canvas + kBufStride);
        const size_t need = static_cast<size_t>(stride) * H;
        if (g_scratchLen < need) { free(g_scratch); g_scratch = static_cast<BYTE*>(malloc(need)); g_scratchLen = g_scratch ? need : 0; }
        if (g_scratch) {
            memcpy(g_scratch, RdP<BYTE*>(canvas + kBufData), need);
            // a fair comparison: the full redraw must land on the same (nudged) row as the strips did. PRACX's wrapper
            // rewrites the Console offset from its own double, so shift that double by the nudge for the call.
            double* poff = reinterpret_cast<double*>(g_px + kPx_ScrollOffY);
            const double savedOff = *poff;
            *poff = nOffYd;                                               // (int) of it = the drawn offset exactly (adding the nudge to a fractional offset would not)
            g_origRedraw(con, nullptr, 0);
            *poff = savedOff;
            const BYTE* now = RdP<BYTE*>(canvas + kBufData);
            int bad = 0, fx = -1, fy = -1;
            for (int y = 0; y < H; ++y) {
                const BYTE* a = g_scratch + static_cast<size_t>(y) * stride; const BYTE* b = now + static_cast<size_t>(y) * stride;
                for (int x = 0; x < W; ++x) if (a[x] != b[x]) { if (fx < 0) { fx = x; fy = y; } ++bad; }
            }
            Log("[uimod] mapscroll: VERIFY %d pixels differ (first at %d,%d) of %dx%d\n", bad, fx, fy, W, H);
            static bool dumped = false;
            if (bad > 300 && !dumped) {                               // the first non-trivial mismatch: both frames (+ palette) to disk for offline diffing
                dumped = true;
                char path[MAX_PATH]; IniPath(path, sizeof path);
                char* slash = strrchr(path, '\\'); if (slash) slash[1] = '\0';
                char ours[MAX_PATH], full[MAX_PATH], meta[MAX_PATH];
                _snprintf_s(ours, sizeof ours, _TRUNCATE, "%suimod_scroll_ours.raw", path);
                _snprintf_s(full, sizeof full, _TRUNCATE, "%suimod_scroll_full.raw", path);
                _snprintf_s(meta, sizeof meta, _TRUNCATE, "%suimod_scroll_meta.txt", path);
                FILE* f;
                if (fopen_s(&f, ours, "wb") == 0 && f) { fwrite(g_scratch, 1, need, f); fclose(f); }
                if (fopen_s(&f, full, "wb") == 0 && f) { fwrite(now, 1, need, f); fclose(f); }
                char pal[MAX_PATH];
                _snprintf_s(pal, sizeof pal, _TRUNCATE, "%suimod_scroll_pal.raw", path);
                if (fopen_s(&f, pal, "wb") == 0 && f) { fwrite(At(0x94C590), 1, 1024, f); fclose(f); }   // PALETTEENTRY[256]
                if (fopen_s(&f, meta, "w") == 0 && f) {
                    fprintf(f, "W %d H %d stride %d dx %d dy %d xs %d %d %d %d ys %d %d %d %d xr %d %d %d %d yr %d %d %d %d left %d top %d offx %d offy %d stepx %d stepy %d z %d\n",
                            W, H, stride, dx, dy, xs.left, xs.top, xs.right, xs.bottom, ys.left, ys.top, ys.right, ys.bottom,
                            xr[0], xr[1], xr[2], xr[3], yr[0], yr[1], yr[2], yr[3], nLeft, nTop, nOffX, nOffYd, stepX, stepY, nZ);
                    fclose(f);
                }
                Log("[uimod] mapscroll: VERIFY frames dumped (uimod_scroll_ours.raw / _full.raw / _meta.txt)\n");
            }
        }
    }
    return true;
}

int __fastcall RedrawHook(BYTE* con, void* edx, int a2)
{
    if (g_on && g_bound && con == Console() && a2 == 0 && RdP<BYTE>(g_px + kPx_fScrolling) != 0) {
        if (ScrollStep(con)) { ++g_steps; return 0; }
        ++g_full;
        if (g_full <= 6) Dbg("[uimod] mapscroll: full redraw fallback (%d so far)\n", g_full);
    }
    if (con == Console()) g_pendingSettle = false;                        // a full draw: the canvas is the truth again
    return g_origRedraw(con, edx, a2);
}

// PRACX ends a scroll with pfncMoveMap(main, centre, 1) -- MapWin_set_center, which draws only when the centre
// CHANGES (0x46B2B8..0x46B2C7 -> 0x46B2ED), and after a drag it never does. Under the stock full-redraw-per-step
// that was fine; after a run of shifted frames it would leave the last shift on screen for good: the nudged row,
// the 0x41 fill past the map's edge, a unit's blink phase. So when the step left the canvas shifted and
// set_center drew nothing, draw it fully here, once, at the position PRACX's own offsets put it (the flag
// PRACX sets around this call is cleared for the draw: with it set, an unchanged origin draws nothing at all).
int __fastcall MoveMapHook(BYTE* con, void* edx, int x, int y, int a4)
{
    const bool mine = g_bound && con == Console() && g_pendingSettle;
    const int cx = mine ? C(kConCX) : 0, cy = mine ? C(kConCY) : 0;
    const int r = g_origMoveMap(con, edx, x, y, a4);
    if (mine) {
        g_pendingSettle = false;
        if (C(kConCX) == cx && C(kConCY) == cy) {
            const int flag = C(kConScrollFlag);
            WrP<int>(con + kConScrollFlag, 0);
            g_origRedraw(con, nullptr, 0);
            WrP<int>(con + kConScrollFlag, flag);
            Dbg("[uimod] mapscroll: settled (full draw at the end of the scroll)\n");
        }
    }
    return r;
}

// nullptr when every site matches, else the name of the first one that does not (a tracer's jmp on a checked
// entry is the usual cause -- the log line must say WHICH, or the feature just goes quiet under a probe)
const char* Bind(const BYTE* px)
{
    if (memcmp(px + kPx_DrawMapThunk, kThunkDrawMap, sizeof kThunkDrawMap) != 0) return "prax gen_map thunk";
    if (memcmp(px + kPx_ZoomThunk, kThunkZoom, sizeof kThunkZoom) != 0) return "prax calc_dim thunk";
    if (memcmp(px + kPx_DrawMapFn, kDrawMapFnPro, sizeof kDrawMapFnPro) != 0) return "prax PRACXDrawMap prologue";
    if (RdP<const BYTE*>(px + kPx_pAC) != px + kPx_Table) return "prax m_pAC";
    const BYTE* t = px + kPx_Table;
    if (RdP<uintptr_t>(t + kTab_Zoom) != 0x462980 || RdP<uintptr_t>(t + kTab_Main) != kVA_Console ||
        RdP<uintptr_t>(t + kTab_MoveMap) != 0x46B1F0 || RdP<uintptr_t>(t + kTab_RedrawMap) != kVA_DrawMap ||
        RdP<uintptr_t>(t + kTab_DrawMap) != 0x469CA0)
        return "prax ACADDRESSES table";
    // the engine sites this mirrors
    if (memcmp(At(kVA_SiteSelfBlit), kSelfBlitBytes, sizeof kSelfBlitBytes) != 0) return "draw_map self-blit call";
    if (memcmp(At(0x46A55D), kGateBytes, sizeof kGateBytes) != 0) return "draw_map offset gate";
    if (memcmp(At(0x469CA0), kGenMapPrologue, sizeof kGenMapPrologue) != 0) return "gen_map prologue";
    if (RdP<BYTE>(At(kVA_SiteGenMap1)) != 0xE8 || RdP<BYTE>(At(kVA_SiteCalcDim)) != 0xE8) return "draw_map call sites";
    // the engine functions the step calls
    if (memcmp(At(kVA_GWinFill3), kFill3Pro, sizeof kFill3Pro) != 0) return "GraphicWin_fill_3";
    if (memcmp(At(kVA_BufferSetClip), kSetClipPro, sizeof kSetClipPro) != 0) return "Buffer_set_clip";
    if (memcmp(At(kVA_WorldWinRedraw), kWorldWinPro, sizeof kWorldWinPro) != 0) return "WorldWin_on_redraw";
    // the two PRACX globals, through the instructions that use them (their operands are relocated with the DLL,
    // so compare against the live module base): DoScroll's `mov byte [m_fScrolling], 1` and its
    // `cvttsd2si edx, [m_dScrollOffsetY]`
    if (memcmp(px + kPx_ScrollingSet, kScrollingSetOp, sizeof kScrollingSetOp) != 0 ||
        RdP<uintptr_t>(px + kPx_ScrollingSet + 2) != reinterpret_cast<uintptr_t>(px + kPx_fScrolling) ||
        RdP<BYTE>(px + kPx_ScrollingSet + 6) != 1)
        return "prax m_fScrolling";
    if (memcmp(px + kPx_OffYRead, kOffYReadOp, sizeof kOffYReadOp) != 0 ||
        RdP<uintptr_t>(px + kPx_OffYRead + 4) != reinterpret_cast<uintptr_t>(px + kPx_ScrollOffY))
        return "prax m_dScrollOffsetY";
    return nullptr;
}

} // namespace

void InstallMapScroll(bool pracx)
{
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    g_on = GetPrivateProfileIntA("UIMod", "SmoothScroll", kSmoothScrollDefault, ini) != 0 ? 1 : 0;
    g_verify = (UimodDebugLogOn() && GetPrivateProfileIntA("UIMod", "MapScrollVerify", 0, ini) != 0) ? 1 : 0;   // debug only: needs DebugLog=1 too
    g_px = pracx ? reinterpret_cast<BYTE*>(GetModuleHandleA("prax.dll")) : nullptr;
    if (!g_px) { UimodLog("[uimod] mapscroll: no PRACX -> smooth scrolling n/a\n"); return; }
    if (const char* bad = Bind(g_px)) {
        char m[160];
        _snprintf_s(m, sizeof m, _TRUNCATE, "[uimod] mapscroll: byte check FAILED at %s -> smooth scrolling disabled\n", bad);
        UimodLog(m);
        return;
    }
    g_table = g_px + kPx_Table;
    g_genMap = reinterpret_cast<FGenMap>(g_px + kPx_DrawMapThunk);
    g_calcDim = reinterpret_cast<FThis>(g_px + kPx_ZoomThunk);
    g_origRedraw = reinterpret_cast<FDrawMap>(RdP<uintptr_t>(g_table + kTab_RedrawMap));
    g_origMoveMap = reinterpret_cast<FMoveMap>(RdP<uintptr_t>(g_table + kTab_MoveMap));
    DWORD old;
    if (!VirtualProtect(g_table + kTab_MoveMap, 8, PAGE_READWRITE, &old)) { UimodLog("[uimod] mapscroll: VirtualProtect failed\n"); return; }
    WrP<uintptr_t>(g_table + kTab_RedrawMap, reinterpret_cast<uintptr_t>(&RedrawHook));
    WrP<uintptr_t>(g_table + kTab_MoveMap, reinterpret_cast<uintptr_t>(&MoveMapHook));     // the two slots are adjacent (+0x38, +0x3C)
    VirtualProtect(g_table + kTab_MoveMap, 8, old, &old);
    g_bound = true;
    Log("[uimod] mapscroll: installed on PRACX's redraw + move entries; SmoothScroll=%d verify=%d\n", g_on, g_verify);
    if (g_verify) UimodLog("[uimod] mapscroll: WARNING MapScrollVerify=1 -- every scroll step is followed by a full redraw and a frame compare (slow; debug only)\n");
}

bool SmoothScrollAvailable() { return g_bound; }
int  SmoothScrollGet() { return g_on; }
void SmoothScrollSet(int on) { if (g_bound) g_on = on ? 1 : 0; }
void SmoothScrollSave()
{
    if (!g_bound) return;
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "SmoothScroll", g_on ? "1" : "0", ini);
}
