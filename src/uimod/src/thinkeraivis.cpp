// thinkeraivis.cpp -- the AI perception filter's Thinker half.
//
// Thinker (induktio/thinker) replaces the engine's per-unit AI planner: its mod_enemy_move sends combat units to its
// own combat_move and the rest to colony / former / crawler / artifact / trans / nuclear_move, all compiled into
// thinker.dll and reading the unit array directly, so none of aivis.cpp's 128 engine call sites is reached for them.
// Measured 2026-10-29 (work\scripts\hook_thinker_aivis.js on the "Cloaking Setup" save): Thinker's artillery attacked
// never-seen cloaked stacks blind (mod_battle_fight from combat_move's artillery loop) and its go-tos converged on
// unseen stacks (the threat map move_upkeep builds from EVERY at-war unit). Decision 5 (user, 2026-10-29): option 2,
// version-pinned detours inside thinker.dll 5.5; the upstream fix is backlogged under THINKER FORK.
//
// Where Thinker's planner learns about foreign units (refs\thinker\src\move.cpp, path.cpp; v5.5 offsets below):
//   non_ally_in_tile(x, y, f)   the cached "a non-pact unit stands here" set behind allow_move / allow_civ_move /
//                               choose_defender / TileSearch -- 10 call sites -> a wrapper answers "no" for a tile whose
//                               stack is hidden from f (the unit then walks in and the bump discovers the stack)
//   stack_search(x, y, f, ..)   "an enemy / neutral / non-pact unit of this kind stands here" (probe and artifact
//                               checks) -- 3 sites -> "nothing there" for a hidden stack
//   allow_combat(x, y, f, sq)   "no commlinked neutral forbids attacking here" -- 1 site -> true for a hidden stack
//   combat_move's artillery     scores every at-war unit on a candidate tile: at_war(f, v->faction_id) at +0x60ED9 with
//   loop                        v in ebx -> a stub answers "not at war" for a hidden v, so the tile scores 0 and is skipped
//   move_upkeep's unit census   mapdata.enemy / enemy_near / safety from every at-war unit: at_war at +0x66FAA with the
//                               unit in esi -> the same stub; a hidden unit leaves no mark on the threat map
//   the engine fallback         mod_enemy_move calls the engine's enemy_move through Thinker's own function pointer
//                               (tutorial units, anything its planner declines) -> the pointer is swapped for aivis.cpp's
//                               viewer-setting wrapper, so the engine half's 128 sites filter there too
//   Thinker's order_veh         the engine's order_veh is a write_jump into it, so aivis.cpp's bump detour has no host:
//                               the same reveal-and-cancel (spot_stack, order cleared, no attack) is detoured onto
//                               Thinker's entry instead. Thinker's mod_enemy_veh then sees action() fail and skips the
//                               unit for this turn; it re-plans next turn with the stack now seen.
// Left as Thinker has them (documented residuals, reviewed with the user 2026-10-30): defender_count / garrison_count
// (no faction argument; every caller counts the AI's OWN or a pact partner's tile, where a human's units stand only as
// an ally), nuclear_move's planet-buster tally (missile chassis can carry neither cloak nor pressure hull, so only a
// scenario-invisible buster is ever hidden) and plans_upkeep's mil_strength (every faction's units summed, hidden or
// not -- vanilla's strength estimates are omniscient too). allow_airdrop's pact check IS stubbed (below).
// FIXED 2026-10-30 (user rule): mod_zoc_any / mod_zoc_veh / mod_zoc_sea (single player: every non-pact unit exerted ZOC,
// cloaked or not, on humans and AIs alike -- a human mover was refused AND shown the blockers, an AI mover refused
// silently and re-planned the same step until its iteration cap) -- detoured onto aivis.cpp's ZocAdjust: a human
// faction's hidden-kind unit not yet seen by the mover's faction exerts no zone of control on it.
// FIXED 2026-10-30 (user): Thinker's action_destroy bombardment (veh_action.cpp ~651: after pillaging an at-war tile's
// sensor / airbase / borehole it bombards any stack of the territory owner within two tiles, found through its own
// veh_at) -- its combat call is wrapped so a stack hidden from the acting faction is not shot (WrapPillageFight).
// Gate: the same as the engine half -- the checkbox / host setting, AI factions only (natives and humans never; a human
// whose units Thinker moves for them under manage_player_units is a documented design point).
//
// PINNED to thinker.dll 5.5 (TimeDateStamp + SizeOfImage from version.h, "Thinker Mod v5.5"), and every site is
// byte-checked besides (the rel32 to the expected callee, the unit-faction read that proves the stub's register, the
// pointer's value, the entry's prologue). Any mismatch disables this whole half with one log line and leaves Thinker's
// AI exactly as it was. Offsets are image-relative: thinker.dll relocates. work\tests\test_thinker_aivis_sites.py
// checks this table against the DLL (completeness included: every call site of the wrapped functions is listed).

#include "thinkeraivis.h"

#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "aivis.h"           // the predicate, the setting, the bump, the engine-side viewer wrapper
#include "modernctl.h"       // ModernCtlVehs(): the live (relocated) unit array
#include "thinkercompat.h"   // ThinkerLoaded() / ThinkerRange()
#include "version.h"        // UIMOD_THINKER_SUPPORTED_*: the Thinker build this half is measured on

void UimodLog(const char* msg);   // init.cpp

namespace {

// ---- thinker.dll 5.5 (work\scripts\thinker_symbols.py + thinker_locate.py, 2026-10-29) --------------------
constexpr uint32_t kStamp = UIMOD_THINKER_SUPPORTED_STAMP, kSizeOfImage = UIMOD_THINKER_SUPPORTED_IMAGE_SIZE;   // version.h: the one pin
constexpr uint32_t kAtWar = 0x23210;          // faction.cpp at_war: Factions[f1].diplo_status[f2] & DIPLO_VENDETTA
constexpr uint32_t kNonAllyInTile = 0x561F0;  // move.cpp non_ally_in_tile(x, y, faction_id)
constexpr uint32_t kStackSearch = 0x54AA0;    // move.cpp stack_search(x, y, faction_id, type, mode)
constexpr uint32_t kAllowCombat = 0x55A90;    // move.cpp allow_combat(x, y, faction_id, sq)
constexpr uint32_t kOrderVeh = 0x99790;       // veh_action.cpp order_veh(veh_id, offset, flag) -- the engine's is a jmp here
constexpr uint32_t kModEnemyMove = 0xAECE0;   // veh_turn.cpp mod_enemy_move -- enemy_veh's call at 0x579362 lands here
constexpr uint32_t kEnemyMovePtr = 0xE5404;   // .data: Fenemy_move enemy_move = (Fenemy_move)0x56B5B0 (engine.h)
constexpr uintptr_t kVA_EngineEnemyMove = 0x0056B5B0;
constexpr uintptr_t kVA_EngineOrderVeh = 0x005947C0;   // Thinker's write_jump -> kOrderVeh
constexpr uintptr_t kVA_EngineAirdrop  = 0x004CC360;   // Thinker's write_jump -> kThinkerAirdrop
constexpr uintptr_t kVA_EnemyVehCallSite = 0x00579362; // Thinker's write_call -> kModEnemyMove
constexpr int kVehSize = 0x34;

constexpr uint32_t kModBattleFight = 0xAD450;   // combat.cpp mod_battle_fight(veh_id, offset, a3, a4, a5)
constexpr uintptr_t kVA_MapAreaX = 0x00949870, kVA_MapToggleFlat = 0x0094988C;
// action_destroy's bombardment (veh_action.cpp ~651): after pillaging an at-war tile it scans the 24 tiles within
// two of the unit (TableOffset 1..24), stack_fix(veh_at), mod_stack_check(stack, 15, owner) and fires
// mod_battle_fight(veh_id, i, 1, 1, 0) at the first hit -- through its OWN veh_at, so a hidden stack of the territory
// owner was hit blind (audit 2026-10-30; user: fix). The combat call carries the unit and the offset, so the wrapper
// recomputes the tile and lets the engine's veh_at + the stack rule decide: hidden from the acting faction -> no shot.
constexpr uint32_t kSitePillageFight = 0xA13C4;   // call mod_battle_fight inside that loop
constexpr uint32_t kPillageWitness = 0xA13A3;     // mov eax, [esp+0x60] (the veh id) right before the call's argument stores
const BYTE kPillageWitnessBytes[4] = { 0x8B, 0x44, 0x24, 0x60 };
const int kTableOffsetX[25] = { 0, 1, 2, 1, 0, -1, -2, -1, 0, 2, 2, -2, -2, 1, 3, 3, 1, -1, -3, -3, -1, 4, -4, 0, 0 };
const int kTableOffsetY[25] = { 0, -1, 0, 1, 2, 1, 0, -1, -2, -2, 2, 2, -2, -3, -1, 1, 3, 3, 1, -1, -3, 0, 0, 4, -4 };

// allow_airdrop's unit loop (move.cpp ~2367: `veh->faction_id != faction_id && !has_pact(faction_id, veh->faction_id)
// -> false`) declined a drop onto a tile holding a hidden stack, so Thinker's AI never got the diversion the engine
// gives every dropper (aivis.cpp WrapActionAirdrop; user 2026-10-30). The loop keeps the unit INDEX in ebx; the stub
// forwards it and a hidden unit reads as "no obstacle": the AI attempts the drop and is diverted like everyone else.
constexpr uint32_t kHasPact = 0x23250;
// Thinker's own action_airdrop (veh_action.cpp:937; the engine's 0x4CC360 is its write_jump, and Thinker's
// colony_move / airdrop_move call it DIRECTLY), so the airdrop diversion (aivis.cpp WrapActionAirdrop) is detoured on
// THIS entry: `push ebp ; mov edx, <thinker.dll address>` = six bytes that are position-independent once loaded.
constexpr uint32_t kThinkerAirdrop = 0x96670;
constexpr uint32_t kSiteAirdropPact = 0x55D4C;     // call has_pact inside that loop
constexpr uint32_t kAirdropPactWitness = 0x55D25;  // imul eax, ebx, 0x34: ebx is the loop index
const BYTE kAirdropPactWitnessBytes[3] = { 0x6B, 0xC3, 0x34 };

const uint32_t kSitesNonAlly[] = { 0x564E5, 0x56610, 0x567FF, 0x56F0E, 0x574F5, 0x5BF5B, 0x5F19D, 0x60A30, 0x61F38, 0x72CC8 };
const uint32_t kSitesStackSearch[] = { 0x6084D, 0x67368, 0x673EC };
const uint32_t kSitesAllowCombat[] = { 0x60279 };

// at_war inside a loop over the unit array: the site, where the unit pointer sits, and the instruction that proves it
// (a read of that unit's faction byte, VEH+0x0E, through the same register).
struct StubSite { uint32_t site; const char* reg; void* stub; uint32_t witness; BYTE bytes[4]; };

// Thinker's order_veh opens `push ebp ; mov eax, 0x543C` (the stack-probe size): six relocatable bytes.
const BYTE kOrderVehPrologue[6] = { 0x55, 0xB8, 0x3C, 0x54, 0x00, 0x00 };

// Thinker's zone-of-control ports (path.cpp mod_zoc_any / mod_zoc_veh / mod_zoc_sea / mod_zoc_move; located 2026-10-30
// through their shared NearbyTiles table + the call graph: mod_zoc_move is the pair of back-to-back calls in order_veh's
// ZOC gate, mod_zoc_sea its only callee besides mapsq, mod_zoc_any the one mod_enemy_veh's skip test calls). Thinker's
// planner and its order_veh call THESE, never the engine's, so the hidden-unit exemption (aivis.cpp ZocAdjust, the
// user's rule) is detoured onto their entries; mod_zoc_move calls mod_zoc_sea and needs none. Prologues: `push ebp ;
// mov ebp, <NearbyTiles>` (6), `push ebp ; push edi ; push esi ; xor esi,esi ; push ebx` (6), `push ebp ; push edi ;
// push esi ; push ebx ; mov ebx, <NearbyTiles>` (9) -- position-independent once loaded (the immediates are checked
// to lie inside thinker.dll).
constexpr uint32_t kModZocAny = 0x70820, kModZocVeh = 0x70940, kModZocSea = 0x709E0, kModZocMove = 0x70B10;
constexpr uint32_t kSiteZocMoveGate = 0x9A17E;    // order_veh: the first of the two consecutive mod_zoc_move calls
const BYTE kZocAnyHead[2] = { 0x55, 0xBD };                               // + imm32 NearbyTiles
const BYTE kZocVehHead[6] = { 0x55, 0x57, 0x56, 0x31, 0xF6, 0x53 };
const BYTE kZocSeaHead[5] = { 0x55, 0x57, 0x56, 0x53, 0xBB };             // + imm32 NearbyTiles

// ---- state ----------------------------------------------------------------------------------------------
using FDiplo       = int(__cdecl*)(int f1, int f2);
using FNonAlly     = int(__cdecl*)(int x, int y, int f);
using FStackSearch = int(__cdecl*)(int x, int y, int f, int type, int mode);
using FAllowCombat = int(__cdecl*)(int x, int y, int f, void* sq);
using FOrder       = int(__cdecl*)(int veh, int dir, int flag);
using FFight       = int(__cdecl*)(int veh, int offset, int a3, int a4, int a5);

BYTE*        g_base = nullptr;
BYTE*        g_vehs = nullptr;
FFight       g_battleFight = nullptr;
FDiplo       g_atWar = nullptr;
FDiplo       g_hasPact = nullptr;
FNonAlly     g_nonAlly = nullptr;
FStackSearch g_stackSearch = nullptr;
FAllowCombat g_allowCombat = nullptr;
FOrder       g_orderVehTramp = nullptr;
using FZoc = int(__cdecl*)(int x, int y, int f);
FZoc         g_zocAnyTramp = nullptr, g_zocVehTramp = nullptr, g_zocSeaTramp = nullptr;

void Log(const char* fmt, ...)
{
    char s[768];
    va_list ap;
    va_start(ap, fmt);
    _vsnprintf_s(s, sizeof s, _TRUNCATE, fmt, ap);
    va_end(ap);
    UimodLog(s);
}

BYTE* At(uintptr_t va)   // engine VA -> address (the exe has no relocations, but keep the convention)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)) + (va - 0x400000);
}

// GCC returns bool in al and leaves the rest of eax as it was: mask before testing.
inline bool B(int r) { return (r & 0xFF) != 0; }

// ---- the wrappers (cdecl, same signatures as Thinker's functions) ------------------------------------------

int __cdecl WrapNonAllyInTile(int x, int y, int f)
{
    const bool r = B(g_nonAlly(x, y, f));
    if (r && AiVisFactionFiltered(f) && AiVisTileHidden(x, y, f)) return 0;
    return r ? 1 : 0;
}

int __cdecl WrapStackSearch(int x, int y, int f, int type, int mode)
{
    if (AiVisFactionFiltered(f) && AiVisTileHidden(x, y, f)) return 0;
    return B(g_stackSearch(x, y, f, type, mode)) ? 1 : 0;
}

int __cdecl WrapAllowCombat(int x, int y, int f, void* sq)
{
    if (AiVisFactionFiltered(f) && AiVisTileHidden(x, y, f)) return 1;
    return B(g_allowCombat(x, y, f, sq)) ? 1 : 0;
}

// The pillage bombardment: no shot at a tile whose stack the acting faction has never seen.
int __cdecl WrapPillageFight(int veh, int offset, int a3, int a4, int a5)
{
    if (veh >= 0 && offset > 0 && offset < 25) {
        const BYTE* v = g_vehs + veh * kVehSize;
        const int f = v[0x0E];
        int tx = *reinterpret_cast<const int16_t*>(v) + kTableOffsetX[offset];
        const int ty = *reinterpret_cast<const int16_t*>(v + 2) + kTableOffsetY[offset];
        if ((*reinterpret_cast<const uint32_t*>(At(kVA_MapToggleFlat)) & 1) == 0) {
            const int w = *reinterpret_cast<const int*>(At(kVA_MapAreaX));
            if (tx < 0) tx += w; else if (tx >= w) tx -= w;
        }
        if (AiVisFactionFiltered(f) && AiVisTileHidden(tx, ty, f)) return 0;
    }
    return g_battleFight(veh, offset, a3, a4, a5);
}

// at_war(f1, v->faction_id) with v the unit the loop is looking at: "not at war" when f1 has never seen v's stack.
int __cdecl AtWarUnit(int f1, int f2, const BYTE* veh)
{
    const int r = B(g_atWar(f1, f2)) ? 1 : 0;
    if (!r || !AiVisFactionFiltered(f1)) return r;
    const ptrdiff_t off = veh - g_vehs;
    if (off < 0 || off % kVehSize != 0) return r;
    return AiVisHiddenStack(static_cast<int>(off / kVehSize), f1) ? 0 : r;
}

// has_pact(f1, Vehs[idx].faction_id) in allow_airdrop's loop: a unit f1 has never seen is no obstacle to a drop.
int __cdecl HasPactUnitIdx(int f1, int f2, int idx)
{
    const int r = B(g_hasPact(f1, f2)) ? 1 : 0;
    if (r || !AiVisFactionFiltered(f1)) return r;
    return AiVisHiddenStack(idx, f1) ? 1 : 0;
}

void __declspec(naked) StubHasPactIdxEbx()
{
    __asm {
        mov  eax, dword ptr [esp + 4]
        mov  edx, dword ptr [esp + 8]
        push ebx
        push edx
        push eax
        call HasPactUnitIdx
        add  esp, 12
        ret
    }
}

// The two stub flavours: the caller's unit pointer rides in a callee-saved register, which the stub forwards as a
// third argument. eax/ecx/edx are caller-saved in Thinker's code as in at_war itself.
void __declspec(naked) StubAtWarEbx()
{
    __asm {
        mov  eax, dword ptr [esp + 4]
        mov  edx, dword ptr [esp + 8]
        push ebx
        push edx
        push eax
        call AtWarUnit
        add  esp, 12
        ret
    }
}

void __declspec(naked) StubAtWarEsi()
{
    __asm {
        mov  eax, dword ptr [esp + 4]
        mov  edx, dword ptr [esp + 8]
        push esi
        push edx
        push eax
        call AtWarUnit
        add  esp, 12
        ret
    }
}

const StubSite kStubs[] = {
    // combat_move's artillery loop: `for (v = Vehs; v < Vehs + *VehCount; ++v)` -- v in ebx, movzx eax, byte [ebx+0xE]
    { 0x60ED9, "ebx", &StubAtWarEbx, 0x60EC2, { 0x0F, 0xB6, 0x43, 0x0E } },
    // move_upkeep's census: `veh = &Vehs[i]` in esi -- movzx eax, byte [esi+0xE] (the compare that jumps to this call)
    { 0x66FAA, "esi", &StubAtWarEsi, 0x666FA, { 0x0F, 0xB6, 0x46, 0x0E } },
};

// Thinker's order_veh entry: aivis.cpp's bump, then Thinker's own function through the trampoline.
int __cdecl HookThinkerOrderVeh(int veh, int dir, int flag)
{
    if (AiVisBump(veh, dir)) return 0;
    return g_orderVehTramp(veh, dir, flag);
}

// Thinker's zone-of-control ports: Thinker's own function answers first; a nonzero answer is recomputed without the
// human factions' unseen hidden units when the setting is on (aivis.cpp ZocAdjust; same semantics as the engine's).
int __cdecl HookThinkerZocAny(int x, int y, int f) { return AiVisZocAdjust(0, g_zocAnyTramp(x, y, f), x, y, f); }
int __cdecl HookThinkerZocVeh(int x, int y, int f) { return AiVisZocAdjust(1, g_zocVehTramp(x, y, f), x, y, f); }
int __cdecl HookThinkerZocSea(int x, int y, int f) { return AiVisZocAdjust(2, g_zocSeaTramp(x, y, f), x, y, f); }

// ---- byte checks and writes ----------------------------------------------------------------------------------

bool TransfersTo(const BYTE* site, BYTE opcode, const BYTE* target)   // E8 call / E9 jmp with a rel32 to exactly target
{
    if (site[0] != opcode) return false;
    int32_t rel; memcpy(&rel, site + 1, 4);
    return site + 5 + rel == target;
}

bool IsCallTo(const BYTE* site, const BYTE* target) { return TransfersTo(site, 0xE8, target); }

bool WriteCode(BYTE* p, const void* bytes, size_t n)
{
    DWORD old;
    if (!VirtualProtect(p, n, PAGE_EXECUTE_READWRITE, &old)) return false;
    memcpy(p, bytes, n);
    VirtualProtect(p, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, n);
    return true;
}

bool Retarget(BYTE* site, void* fn)
{
    BYTE call[5] = { 0xE8 };
    const int32_t rel = static_cast<int32_t>(static_cast<BYTE*>(fn) - (site + 5));
    memcpy(call + 1, &rel, 4);
    return WriteCode(site, call, 5);
}

// Entry detour over the six relocatable prologue bytes: trampoline = those bytes + jmp back; entry = jmp hook + nop.
void* DetourEntry6(BYTE* fn, void* hook)
{
    BYTE* tramp = static_cast<BYTE*>(VirtualAlloc(nullptr, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (!tramp) return nullptr;
    memcpy(tramp, fn, 6);
    tramp[6] = 0xE9;
    const int32_t back = static_cast<int32_t>((fn + 6) - (tramp + 11));
    memcpy(tramp + 7, &back, 4);
    FlushInstructionCache(GetCurrentProcess(), tramp, 11);
    BYTE jmp[6] = { 0xE9, 0, 0, 0, 0, 0x90 };
    const int32_t fwd = static_cast<int32_t>(static_cast<BYTE*>(hook) - (fn + 5));
    memcpy(jmp + 1, &fwd, 4);
    if (!WriteCode(fn, jmp, 6)) return nullptr;
    return tramp;
}

// The same over `n` relocatable prologue bytes (5 <= n <= 16; the caller checked them): entry = jmp hook, nop-filled.
void* DetourEntryN(BYTE* fn, size_t n, void* hook)
{
    if (n < 5 || n > 16) return nullptr;
    BYTE* tramp = static_cast<BYTE*>(VirtualAlloc(nullptr, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (!tramp) return nullptr;
    memcpy(tramp, fn, n);
    tramp[n] = 0xE9;
    const int32_t back = static_cast<int32_t>((fn + n) - (tramp + n + 5));
    memcpy(tramp + n + 1, &back, 4);
    FlushInstructionCache(GetCurrentProcess(), tramp, n + 5);
    BYTE patch[16];
    memset(patch, 0x90, sizeof patch);
    patch[0] = 0xE9;
    const int32_t fwd = static_cast<int32_t>(static_cast<BYTE*>(hook) - (fn + 5));
    memcpy(patch + 1, &fwd, 4);
    if (!WriteCode(fn, patch, n)) return nullptr;
    return tramp;
}

// the mod_zoc_* entries hold their 5.5 prologues (the NearbyTiles immediates inside thinker.dll) and the call graph
// still ties them together: mod_zoc_move -> mod_zoc_sea, and order_veh's gate calls mod_zoc_move twice in a row
bool ZocPortsLookRight(uintptr_t lo, uintptr_t hi)
{
    const BYTE* a = g_base + kModZocAny;
    const BYTE* v = g_base + kModZocVeh;
    const BYTE* s = g_base + kModZocSea;
    uint32_t immA, immS;
    memcpy(&immA, a + 2, 4);
    memcpy(&immS, s + 5, 4);
    if (memcmp(a, kZocAnyHead, sizeof kZocAnyHead) != 0 || immA < lo || immA >= hi) return false;
    if (memcmp(v, kZocVehHead, sizeof kZocVehHead) != 0) return false;
    if (memcmp(s, kZocSeaHead, sizeof kZocSeaHead) != 0 || immS < lo || immS >= hi) return false;
    if (!IsCallTo(g_base + kSiteZocMoveGate, g_base + kModZocMove)) return false;
    // mod_zoc_move's body: mapsq, then the base test, then its one call to mod_zoc_sea (scan its first 0xC0 bytes)
    bool seaCall = false;
    for (uint32_t i = 0; i + 5 <= 0xC0; ++i)
        if (IsCallTo(g_base + kModZocMove + i, s)) { seaCall = true; break; }
    return seaCall;
}

const char* Version(uintptr_t lo, uintptr_t hi)   // "Thinker Mod v5.5" lives in .rdata; for the log only
{
    static char v[40] = "unknown";
    const char key[] = "Thinker Mod v";
    const BYTE* p = reinterpret_cast<const BYTE*>(lo);
    for (size_t i = 0, n = hi - lo; i + sizeof key < n; ++i) {
        if (p[i] == 'T' && memcmp(p + i, key, sizeof key - 1) == 0) {
            size_t k = 0;
            while (k + 1 < sizeof v && i + k < n && p[i + k] >= 0x20 && p[i + k] < 0x7F) { v[k] = static_cast<char>(p[i + k]); ++k; }
            v[k] = '\0';
            break;
        }
    }
    return v;
}

} // namespace

void InstallThinkerAiVis()
{
    uintptr_t lo, hi;
    if (!ThinkerLoaded() || !ThinkerRange(&lo, &hi)) return;
    if (!AiVisCoreInstalled()) {
        UimodLog("[uimod] thinker: the AI perception filter's engine half is not installed -> its Thinker half is skipped too\n");
        return;
    }
    g_base = reinterpret_cast<BYTE*>(lo);
    g_vehs = ModernCtlVehs();

    // the pin: this exact build
    const IMAGE_DOS_HEADER* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(g_base);
    const IMAGE_NT_HEADERS32* nt = reinterpret_cast<const IMAGE_NT_HEADERS32*>(g_base + dos->e_lfanew);
    if (nt->FileHeader.TimeDateStamp != kStamp || nt->OptionalHeader.SizeOfImage != kSizeOfImage) {
        Log("[uimod] thinker: thinker.dll is \"%s\" (stamp 0x%08X, image 0x%X), not the 5.5 build this mod was measured on "
            "(0x%08X, 0x%X) -> Thinker's own AI keeps seeing cloaked units; the engine's planner is still filtered\n",
            Version(lo, hi), static_cast<unsigned>(nt->FileHeader.TimeDateStamp), static_cast<unsigned>(nt->OptionalHeader.SizeOfImage),
            kStamp, kSizeOfImage);
        return;
    }

    // every check before any write
    const char* bad = nullptr;
    for (uint32_t s : kSitesNonAlly)     if (!IsCallTo(g_base + s, g_base + kNonAllyInTile)) bad = "a non_ally_in_tile call site";
    for (uint32_t s : kSitesStackSearch) if (!IsCallTo(g_base + s, g_base + kStackSearch))   bad = "a stack_search call site";
    for (uint32_t s : kSitesAllowCombat) if (!IsCallTo(g_base + s, g_base + kAllowCombat))   bad = "the allow_combat call site";
    for (const StubSite& st : kStubs)
        if (!IsCallTo(g_base + st.site, g_base + kAtWar) || memcmp(g_base + st.witness, st.bytes, 4) != 0) bad = "a unit-loop at_war site";
    if (!IsCallTo(g_base + kSitePillageFight, g_base + kModBattleFight) || memcmp(g_base + kPillageWitness, kPillageWitnessBytes, 4) != 0)
        bad = "the pillage bombardment's combat call";
    if (!IsCallTo(g_base + kSiteAirdropPact, g_base + kHasPact) || memcmp(g_base + kAirdropPactWitness, kAirdropPactWitnessBytes, 3) != 0)
        bad = "allow_airdrop's has_pact site";
    {
        const BYTE* a = g_base + kThinkerAirdrop;
        uint32_t imm; memcpy(&imm, a + 2, 4);
        static const BYTE tail[4] = { 0x57, 0x56, 0x53, 0x83 };    // push edi ; push esi ; push ebx ; sub esp,..
        if (a[0] != 0x55 || a[1] != 0xBA || imm < lo || imm >= hi || memcmp(a + 6, tail, 4) != 0) bad = "Thinker's action_airdrop prologue";
    }
    if (!TransfersTo(At(kVA_EngineAirdrop), 0xE9, g_base + kThinkerAirdrop)) bad = "the engine's action_airdrop jump (not to Thinker's)";
    uint32_t ptr; memcpy(&ptr, g_base + kEnemyMovePtr, 4);
    if (ptr != reinterpret_cast<uintptr_t>(At(kVA_EngineEnemyMove))) bad = "Thinker's enemy_move pointer";
    if (memcmp(g_base + kOrderVeh, kOrderVehPrologue, sizeof kOrderVehPrologue) != 0) bad = "order_veh's prologue";
    // the engine's two Thinker-owned hosts must land on THESE entries (a third patch jumping elsewhere inside
    // thinker.dll would pass aivis.cpp's range check and leave the bump unreachable while the filter sites run)
    if (!TransfersTo(At(kVA_EngineOrderVeh), 0xE9, g_base + kOrderVeh)) bad = "the engine's order_veh jump (not to Thinker's order_veh)";
    if (!TransfersTo(At(kVA_EnemyVehCallSite), 0xE8, g_base + kModEnemyMove)) bad = "enemy_veh's call (not to Thinker's mod_enemy_move)";
    if (bad) {
        Log("[uimod] thinker: %s does not hold the expected 5.5 bytes (another mod on thinker.dll?) -> Thinker's own AI keeps "
            "seeing cloaked units; the engine's planner is still filtered\n", bad);
        return;
    }

    g_battleFight = reinterpret_cast<FFight>(g_base + kModBattleFight);
    g_atWar       = reinterpret_cast<FDiplo>(g_base + kAtWar);
    g_hasPact     = reinterpret_cast<FDiplo>(g_base + kHasPact);
    g_nonAlly     = reinterpret_cast<FNonAlly>(g_base + kNonAllyInTile);
    g_stackSearch = reinterpret_cast<FStackSearch>(g_base + kStackSearch);
    g_allowCombat = reinterpret_cast<FAllowCombat>(g_base + kAllowCombat);

    // the bump first: without it a filtered unit walking into a hidden stack would attack it blind
    g_orderVehTramp = reinterpret_cast<FOrder>(DetourEntry6(g_base + kOrderVeh, &HookThinkerOrderVeh));
    if (!g_orderVehTramp) {
        UimodLog("[uimod] thinker: order_veh detour failed -> Thinker's own AI keeps seeing cloaked units\n");
        return;
    }
    int sites = 0;
    for (uint32_t s : kSitesNonAlly)     sites += Retarget(g_base + s, &WrapNonAllyInTile) ? 1 : 0;
    for (uint32_t s : kSitesStackSearch) sites += Retarget(g_base + s, &WrapStackSearch) ? 1 : 0;
    for (uint32_t s : kSitesAllowCombat) sites += Retarget(g_base + s, &WrapAllowCombat) ? 1 : 0;
    for (const StubSite& st : kStubs)    sites += Retarget(g_base + st.site, st.stub) ? 1 : 0;
    sites += Retarget(g_base + kSitePillageFight, &WrapPillageFight) ? 1 : 0;
    sites += Retarget(g_base + kSiteAirdropPact, &StubHasPactIdxEbx) ? 1 : 0;
    void* airdropTramp = DetourEntry6(g_base + kThinkerAirdrop, AiVisAirdropWrapper());
    if (airdropTramp) AiVisAirdropSetNext(airdropTramp);
    else UimodLog("[uimod] thinker: action_airdrop detour failed -> airdrop diversion off under Thinker\n");
    // zone of control: Thinker's three ports onto the hidden-unit exemption (its planner and order_veh use these)
    bool zocOk = false;
    if (ZocPortsLookRight(lo, hi)) {
        g_zocAnyTramp = reinterpret_cast<FZoc>(DetourEntryN(g_base + kModZocAny, 6, &HookThinkerZocAny));
        if (g_zocAnyTramp) g_zocVehTramp = reinterpret_cast<FZoc>(DetourEntryN(g_base + kModZocVeh, 6, &HookThinkerZocVeh));
        if (g_zocVehTramp) g_zocSeaTramp = reinterpret_cast<FZoc>(DetourEntryN(g_base + kModZocSea, 9, &HookThinkerZocSea));
        zocOk = g_zocSeaTramp != nullptr;
        if (!zocOk) UimodLog("[uimod] thinker: mod_zoc_* detour failed -> undetected hidden units still exert zone of control on Thinker's AI\n");
    } else {
        UimodLog("[uimod] thinker: mod_zoc_* do not hold the expected 5.5 bytes -> undetected hidden units still exert zone of control on Thinker's AI\n");
    }
    const uint32_t wrapper = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(AiVisEnemyMoveWrapper()));
    const bool ptrOk = WriteCode(g_base + kEnemyMovePtr, &wrapper, 4);

    const unsigned total = static_cast<unsigned>(sizeof kSitesNonAlly / 4 + sizeof kSitesStackSearch / 4 +
                                                 sizeof kSitesAllowCombat / 4 + sizeof kStubs / sizeof kStubs[0] + 2);
    const bool partial = static_cast<unsigned>(sites) != total || !ptrOk;
    Log("[uimod] thinker: AI perception filter ported into thinker.dll 5.5%s: %d/%u planner sites re-pointed "
        "(non_ally_in_tile, stack_search, allow_combat, two unit-loop at_war stubs, the pillage bombardment, allow_airdrop's pact check), order_veh bump detoured (trampoline %p), "
        "engine enemy_move pointer %s, airdrop diversion on Thinker's action_airdrop %s, zone of control (mod_zoc_any/veh/sea) %s -> Thinker's AI plans against the units it has actually seen\n",
        partial ? " PARTIALLY (a write failed; some planner paths still see hidden units)" : "", sites, total,
        g_orderVehTramp, ptrOk ? "wrapped" : "NOT wrapped (write failed)", airdropTramp ? "detoured" : "NOT detoured",
        zocOk ? "detoured" : "NOT detoured");
}
