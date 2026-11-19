// uimod Punishment Sphere / nerve-staple display: show the drones the sphere or the staple is suppressing.
//
// A base with a Punishment Sphere (facility 23) OR a nerve staple in effect has its talents AND drones zeroed
// by the last stage of base_psych (0x4EA540), so the citizens row shows a contented base and the PSYCH tab
// credits the removal to "Secret Projects". DISPLAY ONLY -- the base record keeps the engine's zeroed totals
// at all times outside the two painters below, so riots, golden ages and the AI are untouched:
//   A. PSYCH tab: the last stage row (index 4 of BasePsychTalents/NDrones/SDrones) holds the WOULD-BE
//      totals, i.e. what the base would have with no sphere and no staple. No badge there.
//   B. The base screen citizens row (BaseWin_draw_pop 0x414B40) and the F4 Base Operations CITIZENS rows
//      (ReportWin_draw_ops 0x49D540) draw the would-be talents / drones / superdrones, and every drone or
//      superdrone face carries a small badge in its upper-left corner: the gold Punishment Sphere badge, or
//      the steel nerve-staple badge on a stapled base without a sphere (user 2026-10-29; the earlier
//      "a stapled base stays vanilla" is withdrawn).
//
// WOULD-BE, implementation-agnostic (PsychWrap): run the psych function as usual; then, for a sphere base
// outside upkeep, snapshot the base record, clear the facility bit, run it again, capture the three totals,
// and put the snapshot back -- every value the function owns is the real one again, the sphere bit included.
// (A third "restoring" run was the earlier design; Thinker's mod_base_energy accumulates energy_intake_2 across
// runs, so only a snapshot restores it.) base_psych writes only base+0x118/+0x11C/+0x120 and the three stage
// arrays while BaseUpkeepState == 0 (its social_psych accumulation at 0x4EB45E is gated on state 1), so the
// extra run leaves nothing behind in the globals either (stages 0-3 do not depend on the sphere).
//
// PAINTERS. draw_pop reads the three totals from the base record: its one call site (0x41E840) is wrapped
// to swap the cached would-be totals in for the duration of the call. draw_ops calls set_base +
// base_compute(0) per row, which reaches base_psych; while draw_ops runs, PsychWrap leaves the would-be
// totals IN the record and the draw_ops wrapper puts every real value back on exit. base_compute(0) skips
// a base whose values are current (ComputeBaseID 0x689374), so the wrapper invalidates that id on entry.
//
// BADGES ride the face blits: 4 E8 sites in draw_pop (Sprite_draw_2 contract) and 8 in draw_ops
// (Sprite_blit_scaled_core contract). On the patched exe those sites already call the patcher's cave
// thunks (t_pop_ratio / t_rwk_face_blit), so each site's LIVE target is read, accepted when it is the
// vanilla function or lies inside .pcave2, and chained. Size law + rasteriser: psbadge.h, a port of
// scaling_laws.ps_badge / ps_badge_raster. Drawn with clipped Buffer_fill_3 runs at device size -- new art is
// rasterised, never resampled -- in the nearest colours of the DEST buffer's own colour table.
//
// COMPAT. Everything is byte-checked first and installed all-or-nothing. THINKER (user decision 2026-10-28,
// option C -- no byte of thinker.dll is written): Thinker jumps base_energy (0x4EB560) and base_compute
// (0x4EC3B0) to its own mod_base_energy / base_compute, and its base_compute calls mod_base_energy DIRECTLY,
// so the engine's base_energy entry is never reached from the base screen or F4. Both jumps are re-pointed:
// the base_energy one at PsychWrap around Thinker's function (engine callers), the base_compute one at a
// wrapper that lets Thinker compute, then runs the would-be passes through Thinker's mod_base_energy (its
// address is the E9 operand Thinker itself wrote) whenever Thinker recomputed the current base or our cache
// is stale. The would-be totals are therefore Thinker's psych without the sphere, which is what that
// ruleset would really give. Thinker also NOPs draw_pop's two superdrone assignments (its way of hiding the
// vanilla leftover-superdrone count on a sphere base); they are restored because the row draws the would-be
// totals, which need the faces. Thinker's PSYCH-tab label append (0x408DBD) is chained as well: its relabel of a
// sphere / stapled base's rows is squashed over our would-be totals, and everything else it prints -- the captured-base
// countdown included -- is its own (pslabel_core.h). Every chained jump or call must land inside thinker.dll's image
// as the startup check found it (thinkerversion.cpp Detect, decided once before Init): a thinker.dll that turns up
// later is never chained. Looked at once more on first use, in case Thinker's writes land after our Init.

#include "pssphere.h"

#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "prefs.h"
#include "psbadge.h"
#include "pslabel_core.h"    // which PSYCH-tab row labels skip Thinker's relabel
#include "thinkercompat.h"   // ThinkerRange(): every Thinker target we chain must lie inside thinker.dll
#include "thinkerversion.h"  // ThinkerPresent() / ThinkerOnPin(): the startup check's one decision

void UimodLog(const char* msg);   // init.cpp

namespace {

constexpr uintptr_t kImageBase = 0x00400000;

// ---- engine addresses (work\symbols\terranx.h) ------------------------------------------------------
constexpr uintptr_t kVA_BasePsych      = 0x004EA540;   // cdecl, no args
constexpr uintptr_t kVA_BaseEnergy     = 0x004EB560;   // cdecl, no args; its tail calls base_psych
constexpr uintptr_t kVA_BaseCompute    = 0x004EC3B0;   // cdecl (update_prev); Thinker jumps it to its own base_compute
constexpr uintptr_t kVA_DrawPop        = 0x00414B40;   // thiscall (a2) RET 4
constexpr uintptr_t kVA_DrawPopSite    = 0x0041E840;   // its only caller
constexpr uintptr_t kVA_DrawOps        = 0x0049D540;   // fastcall ecx = ReportWin, plain ret
constexpr uintptr_t kVA_SpriteDraw2    = 0x005E4B4A;   // thiscall (dest,key,x,y,num,den) RET 0x18
constexpr uintptr_t kVA_SpriteBlitCore = 0x005E4B9A;   // thiscall (dest,key,x,y) RET 0x10
constexpr uintptr_t kVA_BufferFill3    = 0x005DFCD0;   // thiscall (RECT*, color) RET 8; honours the clip
constexpr uintptr_t kVA_Bases          = 0x0097D040;
constexpr uintptr_t kVA_CurrentBase    = 0x0090EA30;
constexpr uintptr_t kVA_CurrentBaseID  = 0x00689370;
constexpr uintptr_t kVA_ComputeBaseID  = 0x00689374;
constexpr uintptr_t kVA_BaseUpkeepState = 0x0090EA34;
constexpr uintptr_t kVA_PsychTalents   = 0x0090E984;   // int[5]
constexpr uintptr_t kVA_PsychNDrones   = 0x0090E920;
constexpr uintptr_t kVA_PsychSDrones   = 0x0090E94C;
constexpr uintptr_t kVA_PopupScaleNum  = 0x00668740;   // the patcher's g; zeroed .data on the unpatched exe
constexpr uintptr_t kVA_MainPalette    = 0x0094C590;   // PALETTEENTRY[256] (r,g,b,flags)
constexpr uintptr_t kVA_CitHumanLg     = 0x0078CAD0;   // Sprite[8]: class + 4 * variant (loader 0x4550D7)
constexpr uintptr_t kVA_CitAlienLg     = 0x007AD1B0;   // Sprite[4]: class
constexpr uintptr_t kVA_CitHumanSm     = 0x00776420;   // Sprite[8]
constexpr uintptr_t kVA_CitAlienSm     = 0x0075B180;   // Sprite[4]
constexpr uintptr_t kVA_SuperAlienSite = 0x00414D52;   // draw_pop: mov ebx,3
constexpr uintptr_t kVA_SuperHumanSite = 0x00414EE2;   // draw_pop: mov dword [ebp-0x10],3

constexpr int kBaseSize = 0x134, kMaxBases = 512;
constexpr int kBasePop = 0x06, kBaseSpecialists = 0x7C, kBaseSphereByte = 0x8E;   // facility 23: byte 23/8, bit 23%8
constexpr BYTE kSphereBit = 0x80;
constexpr int kBaseStaple = 0x08;                      // uint8 nerve_staple_turns_left (Thinker engine_base.h); > 0 = stapled
constexpr int kKindSphere = 1, kKindStaple = 2;        // what suppresses the base's drones (both bits for a stapled sphere)
constexpr uintptr_t kVA_PsychLabelSite = 0x00408DBD;   // BaseWin_draw_psych: `call crt_strcat` (the row-label append)
constexpr uintptr_t kVA_PsychLabelOrig = 0x00645470;   //   crt_strcat, cdecl; Thinker write_calls the site to its relabel
constexpr uintptr_t kVA_TextLabels     = 0x009B90F8;   // TextLabels {char** labels; uint32 count}
constexpr int kBaseTalents = 0x118, kBaseDrones = 0x11C, kBaseSuperdrones = 0x120;
constexpr int kSpriteSize = 0x2C, kSpriteW = 0x10, kSpriteH = 0x14, kSpriteOffX = 0x20, kSpriteOffY = 0x24;
constexpr int kBufferColors = 0xA4, kBufferPalStamp = 0x4A4;   // RGBQUAD[256] + the synced palette's generation
constexpr int kClassDrone = 2, kClassSuperdrone = 3;

const uint32_t kSitesPopFace[] = { 0x414D90, 0x414E23, 0x414F38, 0x414FCD };
const uint32_t kSitesOpsFace[] = { 0x49E4D1, 0x49E56D, 0x49E604, 0x49E681, 0x49E745, 0x49E806, 0x49E8CA, 0x49E96D };

const BYTE kPsychEntry[11]  = { 0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x48, 0xA1, 0x30, 0xEA, 0x90, 0x00 };   // steal 6
const BYTE kEnergyEntry[11] = { 0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x28, 0xA1, 0x30, 0xEA, 0x90, 0x00 };
const BYTE kOpsEntry[6]     = { 0x55, 0x8B, 0xEC, 0x6A, 0xFF, 0x68 };                                 // + imm32: steal 10
const BYTE kSuperAlien[5]   = { 0xBB, 0x03, 0x00, 0x00, 0x00 };
const BYTE kSuperHuman[7]   = { 0xC7, 0x45, 0xF0, 0x03, 0x00, 0x00, 0x00 };

// ---- helpers ----------------------------------------------------------------------------------------

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (va - kImageBase);
}
template <typename T> T Rd(uintptr_t va) { return *reinterpret_cast<T*>(At(va)); }

void LogOnce(bool& said, const char* msg)
{
    if (!said) UimodLog(msg);
    said = true;
}

using FVoid = void(__cdecl*)();
struct Triple { int talents, drones, superdrones; };

Triple ReadTriple(const BYTE* base)
{
    return { *reinterpret_cast<const int*>(base + kBaseTalents), *reinterpret_cast<const int*>(base + kBaseDrones),
             *reinterpret_cast<const int*>(base + kBaseSuperdrones) };
}
void WriteTriple(BYTE* base, const Triple& t)
{
    *reinterpret_cast<int*>(base + kBaseTalents) = t.talents;
    *reinterpret_cast<int*>(base + kBaseDrones) = t.drones;
    *reinterpret_cast<int*>(base + kBaseSuperdrones) = t.superdrones;
}

// The current base, only when CurrentBase and CurrentBaseID agree and something suppresses its drones: a
// Punishment Sphere, a nerve staple in effect, or both (`kindOut` says which; both psych implementations zero
// talents and drones for either -- user 2026-10-29: the staple joins the would-be display with its own badge).
BYTE* CurrentSphereBase(int* idOut, int* kindOut = nullptr)
{
    BYTE* base = Rd<BYTE*>(kVA_CurrentBase);
    const int id = Rd<int>(kVA_CurrentBaseID);
    if (!base || id < 0 || id >= kMaxBases || base != At(kVA_Bases) + id * kBaseSize) return nullptr;
    const int kind = ((base[kBaseSphereByte] & kSphereBit) ? kKindSphere : 0) | (base[kBaseStaple] ? kKindStaple : 0);
    if (!kind) return nullptr;
    if (idOut) *idOut = id;
    if (kindOut) *kindOut = kind;
    return base;
}

// ---- state --------------------------------------------------------------------------------------------

bool  g_installed = false;
bool  g_inPsych = false;              // inside PsychWrap: nested psych entries pass straight through
int   g_inOps = 0;                    // inside ReportWin_draw_ops
FVoid g_psychTramp = nullptr;         // base_psych past our detour
FVoid g_energyNext = nullptr;         // Thinker's mod_base_energy (the E9 operand Thinker writes at 0x4EB560)
using FInt = void(__cdecl*)(int);
FInt  g_computeNext = nullptr;        // Thinker's base_compute (the E9 operand Thinker writes at 0x4EC3B0)
using FLabel = void(__cdecl*)(char*, const char*);
FLabel g_labelNext = nullptr;         // Thinker's BaseWin_draw_psych_strcat (the E8 operand Thinker writes at 0x408DBD)
bool  g_energyForeign = false;        // base_energy is neither vanilla nor chained: its psych is not the engine's
unsigned g_cacheGen = 0;              // bumped whenever the would-be cache is (re)filled
bool  g_superNoped = false;           // Thinker NOPed draw_pop's superdrone face assignments (see SuperFacesVanilla)
void* g_opsTramp = nullptr;
void* g_popTarget = nullptr;          // live targets of the wrapped call sites
void* g_popFaceTarget = nullptr;
void* g_opsFaceTarget = nullptr;
bool  g_thinkerChecked = false;

struct Cache { int baseId = -1, pop = 0, specialists = 0, kind = 0; Triple wouldBe{}; } g_cache;

struct Restore { BYTE* base; Triple real; };
Restore g_restore[kMaxBases];
int     g_restoreN = 0;

BYTE*  g_popSwapBase = nullptr;       // draw_pop: the record holding would-be totals right now
Triple g_popSwapReal{};

// Does the cache describe THIS base as it is now (same base, population, specialists and suppression kind)?
bool CacheStale(const BYTE* base, int id, int kind)
{
    return g_cache.baseId != id || g_cache.kind != kind || g_cache.pop != static_cast<int8_t>(base[kBasePop]) ||
           g_cache.specialists != *reinterpret_cast<const int*>(base + kBaseSpecialists);
}

// ---- Thinker compatibility -------------------------------------------------------------------------------

void PsychCore(FVoid next, bool runReal);
void PsychWrap(FVoid next) { PsychCore(next, true); }
void __cdecl WrapEnergy() { PsychWrap(g_energyNext); }

// Thinker's base_compute calls its mod_base_energy directly, never through 0x4EB560: the would-be passes
// run here, after it, when it recomputed the current base (its own condition: update_prev, or a new base)
// or our cache does not describe the current sphere base. Skipped when the call already refilled the cache
// (conf.base_psych=0 routes Thinker through the engine's base_psych, which our detour wraps).
void __cdecl WrapBaseCompute(int update_prev)
{
    const bool recompute = update_prev != 0 || Rd<int>(kVA_ComputeBaseID) != Rd<int>(kVA_CurrentBaseID);
    const unsigned gen = g_cacheGen;
    g_computeNext(update_prev);
    if (!g_energyNext || g_inPsych || g_cacheGen != gen) return;
    int id = -1, kind = 0;
    BYTE* base = CurrentSphereBase(&id, &kind);
    if (!base) return;
    if (recompute || CacheStale(base, id, kind)) PsychCore(g_energyNext, false);
}

void Patch(BYTE* p, const BYTE* bytes, size_t n)
{
    DWORD old;
    VirtualProtect(p, n, PAGE_EXECUTE_READWRITE, &old);
    memcpy(p, bytes, n);
    VirtualProtect(p, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, n);
}

bool AllNops(const BYTE* p, size_t n)
{
    for (size_t i = 0; i < n; ++i) if (p[i] != 0x90) return false;
    return true;
}

void PsychCore(FVoid next, bool runReal);

// The target of the E9 / E8 at `p` when it lies inside thinker.dll; nullptr otherwise (no Thinker, another module's
// jump, or no jump at all). Every Thinker function this file chains comes through here (arithmetic: pslabel_core.h).
BYTE* ThinkerBranchTarget(BYTE* p, BYTE opcode)
{
    uintptr_t lo = 0, hi = 0;
    if (p[0] != opcode || !ThinkerRange(&lo, &hi)) return nullptr;
    return reinterpret_cast<BYTE*>(pslabel::BranchTarget(p, reinterpret_cast<uintptr_t>(p), opcode, lo, hi));
}

// Re-points the 5-byte E9 / E8 at `p` (opcode kept) at `fn`.
void Branch(BYTE* p, BYTE opcode, const void* fn)
{
    BYTE b[5];
    pslabel::EncodeBranch(b, reinterpret_cast<uintptr_t>(p), opcode, reinterpret_cast<uintptr_t>(fn));
    Patch(p, b, 5);
}

// The PSYCH tab's row-label append at 0x408DBD under Thinker (pslabel_core.h): its relabel of "Stapled Base" and
// "Secret Projects" on a sphere / stapled base -- where row 4 holds our would-be totals -- is squashed by the engine's
// own strcat (user decision 2026-10-29); every other label, the captured-base countdown included, is Thinker's.
// cdecl like both callees; the caller cleans the stack and never reads eax (Thinker's function returns void).
char* __cdecl PsychLabelChain(char* buffer, const char* source)
{
    if (pslabel::KeepOwn(Rd<int>(kVA_CurrentBaseID), At(kVA_Bases), Rd<const char* const*>(kVA_TextLabels),
                         Rd<uint32_t>(kVA_TextLabels + 4), source)) {
        using FStrcat = char*(__cdecl*)(char*, const char*);
        return reinterpret_cast<FStrcat>(At(kVA_PsychLabelOrig))(buffer, source);
    }
    g_labelNext(buffer, source);
    return buffer;
}

// The psych a draw-time would-be pass runs: Thinker's chained mod_base_energy, else the engine's base_psych -- but
// only while base_energy is still the engine's; under a psych we did not chain, none (the base draws vanilla).
FVoid DrawTimePsych()
{
    if (g_energyNext) return g_energyNext;
    return g_energyForeign ? nullptr : g_psychTramp;
}

// Checked at install AND on first use (`inGame`): Thinker may load after us, but not after the game runs.
void ThinkerCheck(bool inGame)
{
    if (g_thinkerChecked || !g_installed) return;
    BYTE* e = At(kVA_BaseEnergy);
    BYTE* energy = ThinkerBranchTarget(e, 0xE9);
    if (energy) {
        g_energyNext = reinterpret_cast<FVoid>(energy);
        Branch(e, 0xE9, &WrapEnergy);
        BYTE* c = At(kVA_BaseCompute);
        if (BYTE* compute = ThinkerBranchTarget(c, 0xE9)) {
            g_computeNext = reinterpret_cast<FInt>(compute);
            Branch(c, 0xE9, &WrapBaseCompute);
            UimodLog("[uimod] pssphere: Thinker: base_energy 0x4EB560 and base_compute 0x4EC3B0 are its jumps -> both "
                     "chained; the would-be psych runs through Thinker's mod_base_energy after its base_compute\n");
            // Thinker's PSYCH-tab label append (its relabel of a sphere / stapled base's rows, and the captured-base
            // countdown) is chained, with the relabel squashed where row 4 holds our would-be totals.
            BYTE* s = At(kVA_PsychLabelSite);
            if (BYTE* label = ThinkerBranchTarget(s, 0xE8)) {
                g_labelNext = reinterpret_cast<FLabel>(label);
                Branch(s, 0xE8, &PsychLabelChain);
                UimodLog("[uimod] pssphere: Thinker: its PSYCH-tab label append at 0x408DBD is chained -> a sphere / "
                         "stapled base keeps its own row labels over our would-be totals; every other label is Thinker's\n");
            } else {
                UimodLog("[uimod] pssphere: Thinker: 0x408DBD is not a call into thinker.dll -> the PSYCH-tab labels "
                         "are left as they are\n");
            }
        } else {
            UimodLog("[uimod] pssphere: Thinker: base_energy 0x4EB560 chained, but base_compute 0x4EC3B0 is not a jmp "
                     "into thinker.dll -> a base_compute that bypasses base_energy would show no suppressed drones\n");
        }
    } else if (memcmp(e, kEnergyEntry, sizeof kEnergyEntry) == 0) {
        if (!inGame) return;                             // vanilla so far: look once more when the game runs
    } else {
        // Not ours to chain (e.g. a thinker.dll the startup check did not see): the draw-time fallback must not run
        // the ENGINE's psych on that game (DrawTimePsych), so a stale base draws vanilla instead (review 2026-11-15).
        g_energyForeign = true;
        UimodLog("[uimod] pssphere: base_energy 0x4EB560 is neither vanilla nor a jmp into thinker.dll -> not chained; "
                 "a psych replacement that bypasses base_psych will show no suppressed drones\n");
    }
    g_thinkerChecked = true;

    // Thinker NOPs draw_pop's two superdrone face assignments to hide the vanilla leftover-superdrone count on a
    // sphere or STAPLED base. The vanilla bytes are needed only while the row draws OUR would-be totals, so they
    // are put back for exactly that window (PopEnter / PopLeave) and Thinker's NOPs stay for every other draw --
    // a stapled base without a sphere keeps Thinker's look (audit 2026-10-28; a permanent restore showed the
    // leftover faces there).
    if (AllNops(At(kVA_SuperAlienSite), sizeof kSuperAlien) && AllNops(At(kVA_SuperHumanSite), sizeof kSuperHuman)) {
        g_superNoped = true;
        UimodLog("[uimod] pssphere: Thinker: draw_pop's superdrone faces are NOPed by Thinker -> the vanilla bytes are "
                 "put back only while the row draws our would-be totals\n");
    }
}

void SuperFacesVanilla(bool on)
{
    if (!g_superNoped) return;
    static const BYTE nopA[sizeof kSuperAlien] = { 0x90, 0x90, 0x90, 0x90, 0x90 };
    static const BYTE nopH[sizeof kSuperHuman] = { 0x90, 0x90, 0x90, 0x90, 0x90, 0x90, 0x90 };
    Patch(At(kVA_SuperAlienSite), on ? kSuperAlien : nopA, sizeof kSuperAlien);
    Patch(At(kVA_SuperHumanSite), on ? kSuperHuman : nopH, sizeof kSuperHuman);
}

// ---- the would-be computation ---------------------------------------------------------------------------

// runReal = false when the caller already ran the real pass (WrapBaseCompute, after Thinker's base_compute).
void PsychCore(FVoid next, bool runReal)
{
    if (g_inPsych) { if (runReal) next(); return; }
    g_inPsych = true;
    if (runReal) next();                                        // the real values
    ThinkerCheck(true);

    int id = -1, kind = 0;
    BYTE* base = CurrentSphereBase(&id, &kind);
    if (base && Rd<int>(kVA_BaseUpkeepState) == 0) {            // never re-run during upkeep (social_psych scoring)
        // The would-be pass runs on a SNAPSHOT of the whole base record, put back afterwards: a third "restoring"
        // pass is not enough under Thinker, whose mod_base_energy ACCUMULATES energy_intake_2 (+= convoy, commerce,
        // energy grid; only base_update resets it -- audit 2026-10-28), so every extra pass would inflate the
        // energy, economy and labs totals the AI and the governor read. The engine's base_psych writes only the
        // three totals, which the snapshot covers just the same.
        static BYTE snap[kBaseSize];
        memcpy(snap, base, kBaseSize);
        base[kBaseSphereByte] &= static_cast<BYTE>(~kSphereBit);
        base[kBaseStaple] = 0;                                  // ... and without the nerve staple
        next();
        const Triple wouldBe = ReadTriple(base);
        memcpy(base, snap, kBaseSize);                          // every real value back, sphere bit and staple included
        const Triple real = ReadTriple(base);

        const int pop = static_cast<int8_t>(base[kBasePop]);
        const int spec = *reinterpret_cast<const int*>(base + kBaseSpecialists);
        // Thinker's psych can legally leave more superdrones than drones (facilities subtract from drone_total
        // only), so the check is the engine's invariant, not superdrones <= drones.
        const bool sane = wouldBe.talents >= 0 && wouldBe.drones >= 0 && wouldBe.superdrones >= 0 &&
                          wouldBe.superdrones <= pop && wouldBe.talents + wouldBe.drones <= pop - spec;
        if (sane) {
            reinterpret_cast<int*>(At(kVA_PsychTalents))[4] = wouldBe.talents;
            reinterpret_cast<int*>(At(kVA_PsychNDrones))[4] = wouldBe.drones;
            reinterpret_cast<int*>(At(kVA_PsychSDrones))[4] = wouldBe.superdrones;
            g_cache.baseId = id; g_cache.pop = pop; g_cache.specialists = spec; g_cache.kind = kind; g_cache.wouldBe = wouldBe;
            ++g_cacheGen;
            if (g_inOps > 0 && g_restoreN < kMaxBases) {        // draw_ops reads the record: lend it the totals
                g_restore[g_restoreN++] = { base, real };
                WriteTriple(base, wouldBe);
            }
        } else {
            static bool said = false;
            LogOnce(said, "[uimod] pssphere: would-be psych totals failed the sanity check -> that base draws vanilla\n");
            if (g_cache.baseId == id) g_cache.baseId = -1;
        }
    } else if (id < 0 && g_cache.baseId == Rd<int>(kVA_CurrentBaseID)) {
        g_cache.baseId = -1;                                    // the base lost its sphere / staple: stale
    }
    g_inPsych = false;
}

void __cdecl HookBasePsych() { PsychWrap(g_psychTramp); }

// ---- badge ------------------------------------------------------------------------------------------------

// glyph: 0 = the Punishment Sphere badge (gold), 1 = the nerve-staple badge (steel)
struct Run { int16_t y, x0, x1; int8_t tone; };
struct RunList { int d = 0, glyph = -1, n = 0; Run runs[psbadge::kMaxDiameter * psbadge::kMaxDiameter]; };
RunList g_runCache[4];
int     g_runNext = 0;

const RunList* RunsFor(int d, int glyph)
{
    for (const RunList& r : g_runCache) if (r.d == d && r.glyph == glyph) return &r;
    RunList& r = g_runCache[g_runNext++ & 3];
    static int8_t tones[psbadge::kMaxDiameter * psbadge::kMaxDiameter];
    if (glyph) psbadge::RasterStaple(d, tones); else psbadge::Raster(d, tones);
    r.d = d; r.glyph = glyph; r.n = 0;
    for (int y = 0; y < d; ++y) {
        for (int x = 0; x < d; ) {
            const int8_t t = tones[y * d + x];
            int x1 = x + 1;
            while (x1 < d && tones[y * d + x1] == t) ++x1;
            if (t >= 0) r.runs[r.n++] = { static_cast<int16_t>(y), static_cast<int16_t>(x), static_cast<int16_t>(x1), t };
            x = x1;
        }
    }
    return &r;
}

// The 5 ramp tones as indices of the dest buffer's colour table; re-resolved when the buffer's palette
// generation changes. Never the key or a reserved slot (scaling-sprites skill: a quantiser must not emit them).
struct ToneCache { const BYTE* buf = nullptr; uint32_t stamp = 0; bool valid = false; BYTE index[5]; };
ToneCache g_tones[2][2];                                        // [glyph][0 base screen / 1 F4]

bool Excluded(int i) { return i == 8 || i == 9 || i == 246 || i == 247 || i == 253; }

// table = 256 x 4 bytes; (r,g,b) at byte offsets ro,go,bo of each entry
void ResolveTones(int glyph, const BYTE* table, int ro, int go, int bo, BYTE* out)
{
    for (int t = 0; t < 5; ++t) {
        const int r = glyph ? psbadge::RampChannelStaple(t, 0) : psbadge::RampChannel(t, 0);
        const int g = glyph ? psbadge::RampChannelStaple(t, 1) : psbadge::RampChannel(t, 1);
        const int b = glyph ? psbadge::RampChannelStaple(t, 2) : psbadge::RampChannel(t, 2);
        long best = 0x7FFFFFFF; int bestI = 0;
        for (int i = 0; i < 256; ++i) {
            if (Excluded(i)) continue;
            const long dr = table[i * 4 + ro] - r, dg = table[i * 4 + go] - g, db = table[i * 4 + bo] - b;
            const long dist = dr * dr + dg * dg + db * db;
            if (dist < best) { best = dist; bestI = i; }
        }
        out[t] = static_cast<BYTE>(bestI);
    }
}

const BYTE* TonesFor(int kind, const BYTE* buf, int glyph)
{
    ToneCache& c = g_tones[glyph & 1][kind & 1];
    const uint32_t stamp = *reinterpret_cast<const uint32_t*>(buf + kBufferPalStamp);
    if (c.valid && c.buf == buf && c.stamp == stamp) return c.index;
    ResolveTones(glyph, buf + kBufferColors, 2, 1, 0, c.index);        // RGBQUAD: b,g,r,0
    if (c.index[0] == c.index[4])                                      // an unsynced (blank) table: the game palette
        ResolveTones(glyph, At(kVA_MainPalette), 0, 1, 2, c.index);    // PALETTEENTRY: r,g,b,flags
    c.buf = buf; c.stamp = stamp; c.valid = true;
    return c.index;
}

struct Badge { BYTE* dest; int x, y, d, glyph; };
Badge g_badges[64];                                             // this painter pass, in draw order
int   g_badgeN = 0;

void DrawBadge(int kind, const Badge& b)
{
    const RunList* runs = RunsFor(b.d, b.glyph);
    const BYTE* tone = TonesFor(kind, b.dest, b.glyph);
    using FFill3 = void(__thiscall*)(void*, RECT*, int);
    const FFill3 fill = reinterpret_cast<FFill3>(At(kVA_BufferFill3));
    for (int i = 0; i < runs->n; ++i) {
        const Run& r = runs->runs[i];
        RECT rc = { b.x + r.x0, b.y + r.y, b.x + r.x1, b.y + r.y + 1 };      // half-open, like aivis's mark
        fill(b.dest, &rc, tone[r.tone]);
    }
}

// Citizen class of a face sprite by pointer identity: 0 talent, 1 worker, 2 drone, 3 superdrone; -1 other.
int CitizenClass(int kind, const BYTE* spr)
{
    const uintptr_t human = kind == 0 ? kVA_CitHumanLg : kVA_CitHumanSm;
    const uintptr_t alien = kind == 0 ? kVA_CitAlienLg : kVA_CitAlienSm;
    ptrdiff_t off = spr - At(human);
    if (off >= 0 && off < 8 * kSpriteSize && off % kSpriteSize == 0) return static_cast<int>(off / kSpriteSize) & 3;
    off = spr - At(alien);
    if (off >= 0 && off < 4 * kSpriteSize && off % kSpriteSize == 0) return static_cast<int>(off / kSpriteSize);
    return -1;
}

// Runs after every citizen face blit of the two painters. kind: 0 = base screen, 1 = F4.
void __cdecl AfterFace(int kind, const BYTE* spr, BYTE* dest, int x, int y, int num, int den)
{
    if (!spr || !dest || num != den) return;
    int g = Rd<int>(kVA_PopupScaleNum);
    if (g < 16) g = 16;                                         // incl. 0 on the unpatched exe
    const int fx = x + *reinterpret_cast<const int*>(spr + kSpriteOffX) * g / 16;
    const int fy = y + *reinterpret_cast<const int*>(spr + kSpriteOffY) * g / 16;
    const int fw = *reinterpret_cast<const int*>(spr + kSpriteW) * g / 16;
    const int fh = *reinterpret_cast<const int*>(spr + kSpriteH) * g / 16;
    if (fw <= 0 || fh <= 0) return;

    // This face may have covered badges drawn before it (the row overlaps when crowded; the base screen
    // draws left to right, F4 right to left -- onto the previous face's badge corner): put them back on top.
    for (int i = 0; i < g_badgeN; ++i) {
        const Badge& b = g_badges[i];
        if (b.dest == dest && b.x < fx + fw && b.x + b.d > fx && b.y < fy + fh && b.y + b.d > fy) DrawBadge(kind, b);
    }

    const int cls = CitizenClass(kind, spr);
    if (cls != kClassDrone && cls != kClassSuperdrone) return;
    int suppressed = 0;
    if (!CurrentSphereBase(nullptr, &suppressed)) return;
    const int d = psbadge::Diameter(fw), inset = psbadge::Inset(fw);
    if (d < 1 || d > psbadge::kMaxDiameter) return;
    const int glyph = (suppressed & kKindSphere) ? 0 : 1;      // a stapled sphere base keeps the sphere badge
    const Badge b = { dest, psbadge::OriginX(fx, fw, kind == 1), fy + inset, d, glyph };   // F4 (kind 1): upper-right
    DrawBadge(kind, b);
    if (g_badgeN == 64) { memmove(g_badges, g_badges + 1, 63 * sizeof(Badge)); g_badgeN = 63; }
    g_badges[g_badgeN++] = b;
}

// Face call-site stubs: re-push the args, call the site's live target, then AfterFace. eax and every
// callee-saved register survive; ecx/edx are the callee's to clobber under both contracts.
__declspec(naked) void StubPopFace()                          // Sprite_draw_2 contract, RET 0x18
{
    __asm {
        push ecx
        push dword ptr [esp + 0x1C]             // den, num, y, x, key, dest
        push dword ptr [esp + 0x1C]
        push dword ptr [esp + 0x1C]
        push dword ptr [esp + 0x1C]
        push dword ptr [esp + 0x1C]
        push dword ptr [esp + 0x1C]
        call dword ptr [g_popFaceTarget]
        push eax                                // [esp] eax, +4 Sprite*, +8 ret, +0xC dest, key, x, y, num, den
        push dword ptr [esp + 0x20]             // den
        push dword ptr [esp + 0x20]             // num
        push dword ptr [esp + 0x20]             // y
        push dword ptr [esp + 0x20]             // x
        push dword ptr [esp + 0x1C]             // dest
        push dword ptr [esp + 0x18]             // Sprite*
        push 0
        call AfterFace
        add  esp, 0x1C
        pop  eax
        pop  ecx
        ret  0x18
    }
}

__declspec(naked) void StubOpsFace()                          // Sprite_blit_scaled_core contract, RET 0x10
{
    __asm {
        push ecx
        push dword ptr [esp + 0x14]             // y, x, key, dest
        push dword ptr [esp + 0x14]
        push dword ptr [esp + 0x14]
        push dword ptr [esp + 0x14]
        call dword ptr [g_opsFaceTarget]
        push eax                                // [esp] eax, +4 Sprite*, +8 ret, +0xC dest, key, x, y
        push 1                                  // den
        push 1                                  // num
        push dword ptr [esp + 0x20]             // y
        push dword ptr [esp + 0x20]             // x
        push dword ptr [esp + 0x1C]             // dest
        push dword ptr [esp + 0x18]             // Sprite*
        push 1
        call AfterFace
        add  esp, 0x1C
        pop  eax
        pop  ecx
        ret  0x10
    }
}

// ---- painters -----------------------------------------------------------------------------------------------

void __cdecl PopEnter()
{
    ThinkerCheck(true);
    g_badgeN = 0;
    g_popSwapBase = nullptr;
    int id = -1, kind = 0;
    BYTE* base = CurrentSphereBase(&id, &kind);
    if (!base) return;
    if (CacheStale(base, id, kind) && !g_inPsych && Rd<int>(kVA_BaseUpkeepState) == 0) {
        // A staple just applied (or a sphere just built) redraws the row before anything recomputed the base:
        // compute the would-be totals now, through whichever psych the build runs (user 2026-10-29: the staple
        // badge appeared only after closing and reopening the base).
        // runReal = false: the real totals are already in the record; a real pass outside PsychCore's snapshot would
        // let Thinker's mod_base_energy accumulate energy_intake_2 once more (audit 2026-10-30)
        FVoid next = DrawTimePsych();
        if (next) PsychCore(next, false);
    }
    if (CacheStale(base, id, kind)) {
        static bool said = false;
        LogOnce(said, "[uimod] pssphere: no current would-be totals for a sphere / stapled base at draw time -> drawn "
                      "vanilla (logged once)\n");
        return;
    }
    g_popSwapBase = base;
    g_popSwapReal = ReadTriple(base);
    WriteTriple(base, g_cache.wouldBe);
    SuperFacesVanilla(true);                                    // Thinker: the faces the would-be totals need
}

void __cdecl PopLeave()
{
    if (g_popSwapBase) {
        WriteTriple(g_popSwapBase, g_popSwapReal);
        SuperFacesVanilla(false);                               // Thinker's NOPs back for every other draw
    }
    g_popSwapBase = nullptr;
    g_badgeN = 0;
}

__declspec(naked) void StubDrawPop()                          // replaces `call BaseWin_draw_pop` (ecx = win, 1 arg)
{
    __asm {
        push ecx
        call PopEnter
        pop  ecx
        push dword ptr [esp + 4]
        call dword ptr [g_popTarget]
        push eax
        call PopLeave
        pop  eax
        ret  4
    }
}

void __cdecl OpsEnter()
{
    ThinkerCheck(true);
    g_badgeN = 0;
    if (g_inOps++ == 0) {
        g_restoreN = 0;
        *reinterpret_cast<int*>(At(kVA_ComputeBaseID)) = -1;   // base_compute(0) must not skip the first row's base
    }
}

void __cdecl OpsLeave()
{
    if (g_inOps > 0 && --g_inOps == 0) {
        while (g_restoreN > 0) { --g_restoreN; WriteTriple(g_restore[g_restoreN].base, g_restore[g_restoreN].real); }
    }
    g_badgeN = 0;
}

__declspec(naked) void HookDrawOps()                          // entry detour; fastcall ecx = ReportWin
{
    __asm {
        push ecx
        push edx
        call OpsEnter
        pop  edx
        pop  ecx
        call dword ptr [g_opsTramp]
        push eax
        call OpsLeave
        pop  eax
        ret
    }
}

// ---- installation -----------------------------------------------------------------------------------------

// An E8 site whose live target is `vanilla` or lies inside the patcher's .pcave2 (a baked thunk that honours
// the same contract). Returns the target, nullptr when the site is anything else.
void* LiveCallTarget(uintptr_t site, uintptr_t vanilla, uintptr_t caveLo, uintptr_t caveHi)
{
    BYTE* p = At(site);
    if (p[0] != 0xE8) return nullptr;
    int32_t rel; memcpy(&rel, p + 1, 4);
    BYTE* target = p + 5 + rel;
    const uintptr_t t = reinterpret_cast<uintptr_t>(target);
    if (target == At(vanilla) || (t >= caveLo && t < caveHi)) return target;
    return nullptr;
}

template <size_t N> void* LiveCallTargetAll(const uint32_t (&sites)[N], uintptr_t vanilla, uintptr_t lo, uintptr_t hi)
{
    void* first = LiveCallTarget(sites[0], vanilla, lo, hi);
    for (uint32_t s : sites)
        if (!first || LiveCallTarget(s, vanilla, lo, hi) != first) return nullptr;   // one target per painter
    return first;
}

void Retarget(uintptr_t site, void* fn)
{
    BYTE* p = At(site);
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(fn) -
                                             (reinterpret_cast<uintptr_t>(p) + 5));
    DWORD old;
    VirtualProtect(p, 5, PAGE_EXECUTE_READWRITE, &old);
    memcpy(p + 1, &rel, 4);
    VirtualProtect(p, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, 5);
}

// General entry detour: the caller has byte-checked the entry and names how many bytes to steal (whole,
// position-independent instructions, >= 5). tramp = the stolen LIVE bytes + jmp back; entry = jmp hook + int3.
void DetourEntryN(uintptr_t va, size_t steal, BYTE* tramp, void* hook)
{
    BYTE* fn = At(va);
    memcpy(tramp, fn, steal);
    tramp[steal] = 0xE9;
    const int32_t back = static_cast<int32_t>((fn + steal) - (tramp + steal + 5));
    memcpy(tramp + steal + 1, &back, 4);

    DWORD old;
    VirtualProtect(fn, steal, PAGE_EXECUTE_READWRITE, &old);
    fn[0] = 0xE9;
    const int32_t fwd = static_cast<int32_t>(static_cast<BYTE*>(hook) - (fn + 5));
    memcpy(fn + 1, &fwd, 4);
    memset(fn + 5, 0xCC, steal - 5);
    VirtualProtect(fn, steal, old, &old);
    FlushInstructionCache(GetCurrentProcess(), fn, steal);
}

} // namespace

void InstallPunishmentSphereView()
{
    // Reduced mode. Under Thinker this view runs INSIDE Thinker's compute flow (its base_energy / base_compute jumps,
    // the psych pass, three naked stubs) and chains into Thinker's functions on first use; all of that is measured on
    // the pinned build only. On any other Thinker the whole view stays out -- not one hook is installed, so there is
    // nothing left to gate later (a gate inside ThinkerCheck would leave five hook families running; audit 2026-11-14).
    if (ThinkerPresent() && !ThinkerOnPin()) {
        UimodLog("[uimod] pssphere: not the supported Thinker Mod build -> Punishment Sphere drone view NOT installed\n");
        return;
    }
    uintptr_t lo = 0, hi = 0;
    if (!UimodPcave2Range(&lo, &hi)) lo = hi = 0;               // unpatched exe: only the vanilla targets pass

    // 1) check everything, touch nothing
    const bool entriesOk = memcmp(At(kVA_BasePsych), kPsychEntry, sizeof kPsychEntry) == 0 &&
                           memcmp(At(kVA_DrawOps), kOpsEntry, sizeof kOpsEntry) == 0;
    void* popTarget = LiveCallTarget(kVA_DrawPopSite, kVA_DrawPop, lo, hi);
    void* popFace = LiveCallTargetAll(kSitesPopFace, kVA_SpriteDraw2, lo, hi);
    void* opsFace = LiveCallTargetAll(kSitesOpsFace, kVA_SpriteBlitCore, lo, hi);
    if (!entriesOk || !popTarget || !popFace || !opsFace) {
        char s[256];
        _snprintf_s(s, sizeof s, _TRUNCATE,
                    "[uimod] pssphere: byte check FAILED (entries %s, draw_pop site %s, base faces %s, F4 faces %s) -> "
                    "Punishment Sphere drone view feature disabled\n", entriesOk ? "ok" : "BAD", popTarget ? "ok" : "BAD",
                    popFace ? "ok" : "BAD", opsFace ? "ok" : "BAD");
        UimodLog(s);
        return;
    }
    BYTE* tramps = static_cast<BYTE*>(VirtualAlloc(nullptr, 64, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (!tramps) {
        UimodLog("[uimod] pssphere: trampoline alloc FAILED -> Punishment Sphere drone view feature disabled\n");
        return;
    }

    // 2) install
    g_popTarget = popTarget; g_popFaceTarget = popFace; g_opsFaceTarget = opsFace;
    g_psychTramp = reinterpret_cast<FVoid>(tramps);
    g_opsTramp = tramps + 32;
    DetourEntryN(kVA_BasePsych, 6, tramps, &HookBasePsych);              // push ebp; mov ebp,esp; sub esp,0x48
    DetourEntryN(kVA_DrawOps, 10, tramps + 32, &HookDrawOps);            // ... push -1; push <seh handler>
    Retarget(kVA_DrawPopSite, &StubDrawPop);
    for (uint32_t s : kSitesPopFace) Retarget(s, &StubPopFace);
    for (uint32_t s : kSitesOpsFace) Retarget(s, &StubOpsFace);
    g_installed = true;

    char s[256];
    _snprintf_s(s, sizeof s, _TRUNCATE,
                "[uimod] pssphere: Punishment Sphere drone view installed (psych + draw_pop + F4; face blits chain to %s / %s)\n",
                popFace == At(kVA_SpriteDraw2) ? "the engine" : "the patcher's cave thunk",
                opsFace == At(kVA_SpriteBlitCore) ? "the engine" : "the patcher's cave thunk");
    UimodLog(s);
    ThinkerCheck(false);                                        // TENTATIVE; looked at again on first use
}

// The current base's would-be citizen totals for another painter (thinkertext.cpp renumbers Thinker's "Pop:
// T/W/D/S" line with them; user decision 2026-10-30: the numbers follow our badged row, the painter's own colour and
// boom / staple lines keep reading the live record). Lazily computed when stale, like the citizens row; false when
// the current base has no sphere / staple or no fresh totals exist.
bool PsSphereWouldBePop(int* talents, int* workers, int* drones, int* specialists)
{
    if (!g_installed) return false;
    ThinkerCheck(true);
    int id = -1, kind = 0;
    BYTE* base = CurrentSphereBase(&id, &kind);
    if (!base) return false;
    if (CacheStale(base, id, kind) && !g_inPsych && Rd<int>(kVA_BaseUpkeepState) == 0) {
        FVoid next = DrawTimePsych();                           // runReal = false: the real totals are in the record
        if (next) PsychCore(next, false);
    }
    if (CacheStale(base, id, kind)) return false;
    const int pop = static_cast<int8_t>(base[kBasePop]);
    const int spec = *reinterpret_cast<const int*>(base + kBaseSpecialists);
    *talents = g_cache.wouldBe.talents;
    *drones = g_cache.wouldBe.drones;
    *specialists = spec;
    *workers = pop - g_cache.wouldBe.talents - g_cache.wouldBe.drones - spec;
    return true;
}
