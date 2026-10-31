// uimod AI perception filter.
//
// VANILLA BUG: the engine keeps a correct per-faction visibility byte on every unit (VEH+0x27; spot_all
// 0x5B6260 classes a mover hidden on ABL_CLOAKED / ABL_DEEP_PRESSURE_HULL / VFLAG_INVISIBLE for AI
// factions too), but the AI's per-unit planner enemy_move (0x56B5B0) never consults it: it finds foreign
// units through veh_at / veh_who / anything_at / stack_check, which report the true tile contents. So a
// cloaked unit is invisible to a human and fully known to every AI.
//
// THE FIX, two halves (prototype: work\scripts\hook_aivis_proto.js):
//   1. FILTER. The 128 E8 call sites to those four primitives INSIDE enemy_move are re-pointed at
//      wrappers. While an AI faction plans, a non-base tile whose WHOLE foreign stack is hidden by
//      ability/flag AND unseen by that faction reads as empty. One seen unit exposes the tile's stack.
//      Census (2026-09-18): enemy_move has no inline unit-presence reads and its 14 inline unit loops
//      scan the planner's OWN faction, so the call sites are the complete surface. zoc_* is left alone on
//      purpose: move legality must agree with what order_veh will actually allow.
//   2. BUMP. order_veh (0x5947C0) reveals-and-cancels a step into an unseen hidden stack for the LOCAL
//      HUMAN only; an AI mover falls through to a blind attack. Our entry hook gives AI movers the same
//      discovery: spot_stack, clear the order, no attack. action() ignores order_veh's result, so
//      enemy_turn's loop re-enters enemy_move, which now sees the stack and re-plans against it.
//   3. PATHS. Path_find (0x59A530, two copies of the test) and Path_move's greedy fallback (0x59BC10) read
//      the map's unit-present bit + owner nibble INLINE and treat any non-pact occupied tile as
//      impassable -- so an AI's routes bent around stacks it had never seen and it never bumped into them
//      (user test 2026-09-18). Three 6-byte site detours make such a tile read as unoccupied for a
//      filtered AI faction; the route then runs into the stack and half 2 does the discovery.
//      The same inline test leaked hidden units to a HUMAN's go-to routing (the route bent around units
//      the player could not see). That half is closed ALWAYS, independent of the checkbox; order_veh's
//      own human reveal path (the SPOTTED popup) then does the discovery, as vanilla intended.
//   Halves 1-2 never touch humans; the native faction (0) is never filtered anywhere.
//
// NETWORK GAMES. AI turns are REPLICATED: net_upkeep runs enemy_turn on every peer and the host repairs
// divergence by checksum resync. So all peers must agree: the HOST's settings ride in its NEXT-UPKEEP
// broadcast -- net_upkeep_phase's message_data(0x4303, 0, phase, turn, 0, 0), whose last two params no
// receiver reads -- as p3 = settings BITMASK (bit 0 = this filter; the rest reserved for future
// net-critical settings), p4 = kNetMagic. A vanilla host sends 0/0 => every bit off == vanilla.
//
// COMPAT. No cave VAs, no patcher artifacts: byte-checked rel32 rewrites + two entry detours, each group
// all-or-nothing, self-disabling with a log line (unpatched exe, Scient's, Thinker, a GOG update).

#include "aivis.h"

#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "modernctl.h"   // ModernCtlVehs(): the live unit array
#include "thinkercompat.h"   // ThinkerLoaded() / ThinkerRange(): the core group installs differently under Thinker

void UimodLog(const char* msg);   // init.cpp

namespace {

constexpr uintptr_t kImageBase = 0x00400000;

// ---- engine addresses (work\symbols\terranx.h, "AI unit visibility + net upkeep") ----------------
constexpr uintptr_t kVA_EnemyMove      = 0x0056B5B0;
constexpr uintptr_t kVA_EnemyMoveEnd   = 0x00579208;
constexpr uintptr_t kVA_VehAt          = 0x005BFE90;
constexpr uintptr_t kVA_VehWho         = 0x00500250;
constexpr uintptr_t kVA_AnythingAt     = 0x005798E0;
constexpr uintptr_t kVA_StackCheck     = 0x005B9580;
constexpr uintptr_t kVA_OrderVeh       = 0x005947C0;
constexpr uintptr_t kVA_SpotStack      = 0x005B58E0;
constexpr uintptr_t kVA_MessageData    = 0x00592EE0;
constexpr uintptr_t kVA_ProcessMessage = 0x00534400;
constexpr uintptr_t kVA_UpkeepSendSite = 0x0052902A;   // net_upkeep_phase: call message_data(0x4303,...)
constexpr uintptr_t kVA_PathFindOcc1   = 0x0059AE58;   // Path_find: test byte [eax+8],2 ; jne +5   (eax = tile)
constexpr uintptr_t kVA_PathFindOcc2   = 0x0059B6EF;   // Path_find: the same test, second search loop
constexpr uintptr_t kVA_PathMoveOcc    = 0x0059BFA6;   // Path_move: mov al,[eax+edx*4+8] ; test al,3 (ecx = tile)
constexpr uintptr_t kVA_Vehs           = 0x00952828;
constexpr uintptr_t kVA_VehCount       = 0x009A64C8;
constexpr uintptr_t kVA_Units          = 0x009AB868;
constexpr uintptr_t kVA_MapTiles       = 0x0094A30C;
constexpr uintptr_t kVA_MapHalfX       = 0x0068FAF0;
constexpr uintptr_t kVA_MapAreaX       = 0x00949870;
constexpr uintptr_t kVA_MapAreaY       = 0x00949874;
constexpr uintptr_t kVA_MapToggleFlat  = 0x0094988C;
constexpr uintptr_t kVA_DirDX          = 0x0066EF50;
constexpr uintptr_t kVA_DirDY          = 0x0066EF74;
constexpr uintptr_t kVA_FactionStatus  = 0x009A64E8;   // low byte = human-player mask
constexpr uintptr_t kVA_MultiplayerActive = 0x0093F660;
// zone of control: the three engine primitives (zoc_move 0x5C8D40 = zoc_sea off base tiles, so it needs no detour);
// the relocated prologue bytes are position-independent: zoc_any `push ebp ; mov ebp,esp ; push ecx ; mov ecx,[MapToggleFlat]`
// (10, the mov carries an absolute address), zoc_veh / zoc_sea `push ebp ; mov ebp,esp ; sub esp,8` (6)
constexpr uintptr_t kVA_ZocAny = 0x005C89F0, kVA_ZocVeh = 0x005C8AC0, kVA_ZocSea = 0x005C8BA0;
const BYTE kZocAnyPrologue[10] = { 0x55, 0x8B, 0xEC, 0x51, 0x8B, 0x0D, 0x8C, 0x98, 0x94, 0x00 };
const BYTE kZocVehPrologue[6] = { 0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x08 };
const BYTE kZocSeaPrologue[6] = { 0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x08 };
constexpr uintptr_t kVA_NetIsServer    = 0x0093E8C0;
constexpr uintptr_t kVA_CurrentPlayer  = 0x00939284;

constexpr int kVehSize = 0x34, kUnitSize = 0x34, kMapSize = 0x2C;
constexpr int kVehX = 0x00, kVehY = 0x02, kVehFlags = 0x08, kVehUnit = 0x0A, kVehFaction = 0x0E,
              kVehOrder = 0x11, kVehVisibility = 0x27, kVehNext = 0x30, kVehPrev = 0x32;
constexpr int kUnitAbility = 0x20;
constexpr int kUnitChassis = 0x24, kUnitCarry = 0x28;
constexpr int kVehWaypointX0 = 0x14;                   // int16: for ORDER_SENTRY_BOARD, the transport's veh id
constexpr int kOrderSentryBoard = 1;
constexpr uintptr_t kVA_ChassisTriad = 0x0094A379;     // Chassis[i].triad, stride 0x90
constexpr int kChassisSize = 0x90, kTriadLand = 0;
constexpr uint32_t kAblHidden = 0x04 | 0x40;           // ABL_CLOAKED | ABL_DEEP_PRESSURE_HULL
constexpr uint16_t kVflagInvisible = 0x400;

constexpr uint16_t kMsgNextUpkeep = 0x4303;
constexpr uint32_t kNetMagic      = 0x4C4D0001;        // 'LM' + carrier version 1
constexpr uint32_t kNetBitAiVis   = 1u << 0;           // the checkbox: AI perception filter
constexpr uint32_t kNetBitHumanLeaks = 1u << 1;         // always-on: human routes ignore unseen hidden stacks
constexpr uint32_t kNetBitPodRadius = 1u << 3;         // parent-gated: a Survey Pod base's whole radius counts as sensor tiles
constexpr uint32_t kNetBitCargoOne = 1u << 2;          // checkbox: a hidden transport + its cargo spot as ONE unit
constexpr uint32_t kNetBitAirdrop  = 1u << 4;          // checkbox: air drops divert around unseen defenders
                                                       // bits 5..31: future net-critical settings

// ---- call sites inside enemy_move (py _callers.py <fn> --range 0x56B5B0 0x579208, pristine) ------
const uint32_t kSitesVehAt[] = {
    0x56ccbe, 0x56d1c5, 0x56dd52, 0x56e137, 0x56e47a, 0x56e84d, 0x56eabc, 0x56ec8d, 0x56f074, 0x56f5a6,
    0x56fc6d, 0x57024b, 0x571a69, 0x571cfc, 0x57203f, 0x572116, 0x57229b, 0x57253d, 0x57270e, 0x5728ce,
    0x573ac7, 0x573bfd, 0x573d95, 0x57517a, 0x575237, 0x575346, 0x576379, 0x57754a, 0x579157 };
const uint32_t kSitesVehWho[] = {
    0x56e746, 0x574788, 0x575665, 0x5759ed, 0x575a01, 0x575ead, 0x57632a };
const uint32_t kSitesAnythingAt[] = {
    0x56db28, 0x56eb9f, 0x56ee50, 0x56f471, 0x56f7d4, 0x56fbb5, 0x5700a0, 0x5724c9, 0x572bab, 0x572e68,
    0x574507, 0x5773f1, 0x578c5c };
const uint32_t kSitesStackCheck[] = {
    0x56bd35, 0x56ccf2, 0x56d1ce, 0x56dd9f, 0x56e170, 0x56e483, 0x56e570, 0x56e66c, 0x56e856, 0x56ead3,
    0x56eaef, 0x56f186, 0x56f31e, 0x56f602, 0x56f618, 0x56f706, 0x56f868, 0x56fcbf, 0x571159, 0x571236,
    0x57142e, 0x571459, 0x5715ca, 0x5715e2, 0x571640, 0x57166a, 0x571697, 0x57175a, 0x571772, 0x57178e,
    0x5717dd, 0x571aba, 0x571d05, 0x5723d7, 0x5723e8, 0x572554, 0x572564, 0x572751, 0x5728df, 0x5734ea,
    0x57377b, 0x573af5, 0x573c15, 0x573dc4, 0x574d88, 0x574dc5, 0x575183, 0x5751e9, 0x575240, 0x57534f,
    0x576391, 0x576783, 0x57679b, 0x576dda, 0x57779f, 0x5778a9, 0x577b3f, 0x577bae, 0x577be0, 0x577d24,
    0x577d6d, 0x577df1, 0x577e08, 0x577ecb, 0x577edf, 0x577f30, 0x577f44, 0x577f66, 0x577f7d, 0x578056,
    0x57815d, 0x578241, 0x578355, 0x5783e3, 0x578440, 0x57849e, 0x5784c3, 0x578653, 0x5791ce };
const uint32_t kSitesEnemyMove[] = { 0x512842, 0x579362 };   // Console_veh_turn, enemy_veh

// ---- helpers ------------------------------------------------------------------------------------

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleA(nullptr)) + (va - kImageBase);
}
template <typename T> T Rd(uintptr_t va) { return *reinterpret_cast<T*>(At(va)); }

void IniPath(char* out, size_t n)
{
    GetModuleFileNameA(nullptr, out, static_cast<DWORD>(n));
    char* slash = strrchr(out, '\\');
    if (slash) slash[1] = '\0';
    lstrcatA(out, "Alpha Centauri.ini");
}

using FTile2   = int(__cdecl*)(int x, int y);
using FStackCk = int(__cdecl*)(int veh, int type, int a3, int a4, int a5);
using FVeh1    = int(__cdecl*)(int veh);
using FOrder   = int(__cdecl*)(int veh, int dir, int a3);
using FSpot    = void(__cdecl*)(int veh, int faction);
using FMsgData = void(__cdecl*)(int msg, int dest, int p1, int p2, int p3, int p4);

// ---- state --------------------------------------------------------------------------------------

int  g_local = kAiVisDefault;     // the ini / checkbox value
int  g_cargoOne = kCargoOneDefault; // "Cloaked Transport Hides Its Cargo" ini / checkbox value
bool g_cargoOk = false;           // spot_all's stack-count site installed
int  g_airdropOn = kAirdropDivertDefault;   // "Air Drops Divert Around Unseen Defenders" ini / checkbox value
bool g_airdropOk = false;         // the action_airdrop detour (the engine's entry, or Thinker's function) is installed
bool g_coreOk = false;            // filter + bump installed
bool g_netOk = false;             // send + receive carrier installed
bool g_netValid = false;          // a host bitmask arrived this network session
uint32_t g_netMask = 0;
int  g_viewer = -1;               // AI faction whose enemy_move is running; -1 = no filtering
FOrder g_orderVehTramp = nullptr;
void*  g_procMsgTramp = nullptr;

// The setting in force right now. Single-player / hotseat / PBEM: the local value. Network game: the
// host uses its local value and broadcasts it; a client uses what the host sent (nothing received, or
// no carrier installed => off, i.e. exactly what a vanilla host's peers run).
bool Enabled()
{
    if (!g_coreOk) return false;
    if (Rd<int>(kVA_MultiplayerActive) == 0) {
        g_netValid = false;
        return g_local != 0;
    }
    if (!g_netOk) return false;
    if (Rd<int>(kVA_NetIsServer) != 0) return g_local != 0;
    return g_netValid && (g_netMask & kNetBitAiVis) != 0;
}

// The HUMAN half of the pathfinder leak (a player's go-to routes bent around cloaked enemy units they could
// not see) is closed unconditionally -- it is not part of the checkbox (user decision 2026-09-18). Only a
// network game can switch it off: peers execute each other's go-to steps, so they must path identically,
// and a vanilla or pre-fix host (bit absent) means everyone paths the vanilla way.
bool HumanLeakFixActive()
{
    if (Rd<int>(kVA_MultiplayerActive) == 0) return true;
    if (!g_netOk) return false;
    if (Rd<int>(kVA_NetIsServer) != 0) return true;
    return g_netValid && (g_netMask & kNetBitHumanLeaks) != 0;
}

// "Cloaked Transport Hides Its Cargo": changes the ENGINE's spotting for every observer (AI and human), so in
// a network game it follows the host like the other game-logic settings.
bool CargoOneActive()
{
    if (!g_cargoOk) return false;
    if (Rd<int>(kVA_MultiplayerActive) == 0) return g_cargoOne != 0;
    if (!g_netOk) return false;
    if (Rd<int>(kVA_NetIsServer) != 0) return g_cargoOne != 0;
    return g_netValid && (g_netMask & kNetBitCargoOne) != 0;
}

// The Geosynchronous Survey Pod rule (below, WrapSpotAllMoverSensor) rides the parent setting; it changes the
// ENGINE's spotting for every observer, so in a network game it follows the host.
bool g_podOk = false;
bool PodRadiusActive()
{
    if (!g_podOk) return false;
    if (Rd<int>(kVA_MultiplayerActive) == 0) return g_local != 0;
    if (!g_netOk) return false;
    if (Rd<int>(kVA_NetIsServer) != 0) return g_local != 0;
    return g_netValid && (g_netMask & kNetBitPodRadius) != 0;
}

// The airdrop diversion changes how a drop resolves for every faction, and action_airdrop runs on every peer, so a
// network game follows the HOST's checkbox (the carrier below); single player follows the local one.
bool AirdropActive()
{
    if (!g_airdropOk) return false;
    if (Rd<int>(kVA_MultiplayerActive) == 0) return g_airdropOn != 0;
    if (!g_netOk) return false;
    if (Rd<int>(kVA_NetIsServer) != 0) return g_airdropOn != 0;
    return g_netValid && (g_netMask & kNetBitAirdrop) != 0;
}

uint32_t LocalNetMask()
{
    return (g_local ? kNetBitAiVis : 0) | kNetBitHumanLeaks | (g_cargoOne && g_cargoOk ? kNetBitCargoOne : 0) |
           (g_local && g_podOk ? kNetBitPodRadius : 0) | (g_airdropOn && g_airdropOk ? kNetBitAirdrop : 0);
}

// ---- the visibility predicate ---------------------------------------------------------------------

// The live unit array: stock 0x952828, or where Thinker's modify_unit_limit moved it (resolved like
// modernctl's veh_selectable operand read). Reading the stock address under Thinker sees a dead copy -- no
// unit is ever hidden-kind there, so the alert mark never drew (user 2026-10-28).
BYTE* g_vehs = nullptr;
inline BYTE* Veh(int id) { return g_vehs + id * kVehSize; }
inline int   VehFaction(int id) { return Veh(id)[kVehFaction]; }
inline bool  IsHuman(int f) { return ((Rd<BYTE>(kVA_FactionStatus) >> f) & 1) != 0; }
inline bool  IsFilteredAi(int f) { return f > 0 && f < 8 && !IsHuman(f); }   // natives (0): vanilla

BYTE* MapSq(int x, int y)
{
    if (x < 0 || y < 0 || x >= Rd<int>(kVA_MapAreaX) || y >= Rd<int>(kVA_MapAreaY)) return nullptr;
    return Rd<BYTE*>(kVA_MapTiles) + (y * Rd<int>(kVA_MapHalfX) + (x >> 1)) * kMapSize;
}

// Is this unit hidden by its own ability or flag (Cloaking Device, Deep Pressure Hull, scenario-invisible)?
bool HiddenKind(const BYTE* v)
{
    const int unit = *reinterpret_cast<const int16_t*>(v + kVehUnit);
    const uint32_t abil = unit >= 0
        ? *reinterpret_cast<const uint32_t*>(At(kVA_Units) + unit * kUnitSize + kUnitAbility) : 0;
    return (abil & kAblHidden) != 0 ||
           (*reinterpret_cast<const uint16_t*>(v + kVehFlags) & kVflagInvisible) != 0;
}

// Is unit `i` (standing at x,y) LOADED in a hidden-kind transport on that tile?
//   Loaded = order ORDER_SENTRY_BOARD (1) with waypoint_x[0] (+0x14) naming a transport on the same tile.
//   Fallback for cargo that carries no board order (scenario-editor placement): a LAND-triad unit on an
//   ocean tile can only be aboard something -- accepted when the stack holds a hidden-kind carrier.
bool RidesHiddenTransport(int i, int n, int x, int y, bool ocean, bool hiddenCarrier)
{
    const BYTE* v = Veh(i);
    if (static_cast<int8_t>(v[kVehOrder]) == kOrderSentryBoard) {
        const int t = *reinterpret_cast<const int16_t*>(v + kVehWaypointX0);
        if (t >= 0 && t < n && t != i &&
            *reinterpret_cast<int16_t*>(Veh(t) + kVehX) == x &&
            *reinterpret_cast<int16_t*>(Veh(t) + kVehY) == y && HiddenKind(Veh(t)))
            return true;
    }
    if (ocean && hiddenCarrier) {
        const int unit = *reinterpret_cast<const int16_t*>(v + kVehUnit);
        if (unit >= 0) {
            const int chassis = At(kVA_Units)[unit * kUnitSize + kUnitChassis];
            if (At(kVA_ChassisTriad)[chassis * kChassisSize] == kTriadLand) return true;
        }
    }
    return false;
}

// Does the stack topped by `top` hold a hidden-kind unit that can carry?
bool StackHasHiddenCarrier(int top, int n)
{
    int guard = 0;
    for (int i = top; i >= 0 && i < n && guard++ < 4096; i = *reinterpret_cast<int16_t*>(Veh(i) + kVehNext)) {
        const BYTE* v = Veh(i);
        const int unit = *reinterpret_cast<const int16_t*>(v + kVehUnit);
        if (unit >= 0 && HiddenKind(v) && At(kVA_Units)[unit * kUnitSize + kUnitCarry] != 0) return true;
    }
    return false;
}

// True iff the stack holding `id` is hidden from `f`. THE RULE (user, 2026-09-18 -- do not relitigate):
// a stack is hidden only if EVERY unit in it is either hidden-kind itself, or LOADED in a transport that
// is hidden-kind (a submarine's cargo rides hidden; a plain unit standing beside a cloaked one exposes the
// tile). On top of that: all foreign to `f`, not on a base tile, and no unit carrying f's seen bit (the
// engine marks the whole stack when it spots it).
// ("Loaded": see RidesHiddenTransport.)
bool HiddenStack(int id, int f)
{
    const int n = Rd<int>(kVA_VehCount);
    if (id < 0 || id >= n) return false;
    const int x = *reinterpret_cast<int16_t*>(Veh(id) + kVehX), y = *reinterpret_cast<int16_t*>(Veh(id) + kVehY);
    const BYTE* sq = MapSq(x, y);
    if (!sq || (*reinterpret_cast<const uint32_t*>(sq + 8) & 1) != 0) return false;   // base tile
    const bool ocean = (sq[0] & 0xE0) < 0x60;

    int top = id, guard = 0;
    for (int p = *reinterpret_cast<int16_t*>(Veh(top) + kVehPrev); p >= 0 && p < n && guard++ < 4096;
         p = *reinterpret_cast<int16_t*>(Veh(top) + kVehPrev))
        top = p;

    const bool hiddenCarrier = StackHasHiddenCarrier(top, n);

    guard = 0;
    int count = 0;
    for (int i = top; i >= 0 && i < n && guard++ < 4096; i = *reinterpret_cast<int16_t*>(Veh(i) + kVehNext)) {
        const BYTE* v = Veh(i);
        ++count;
        if (v[kVehFaction] == f) return false;
        if ((v[kVehVisibility] >> f) & 1) return false;
        if (HiddenKind(v)) continue;
        // not hidden-kind: only acceptable as cargo of a hidden-kind transport
        const bool ridesHidden = RidesHiddenTransport(i, n, x, y, ocean, hiddenCarrier);
        if (!ridesHidden) return false;
    }
    return count > 0;
}

bool TileHidden(int x, int y, int f)
{
    const int v = reinterpret_cast<FTile2>(At(kVA_VehAt))(x, y);
    return v >= 0 && HiddenStack(v, f);
}

// ---- diagnostics ([UIMod] AiVisDebug=1) -------------------------------------------------------------
// When a planning AI reads a stack that CONTAINS a hidden-kind foreign unit and the filter lets it through,
// say why (once per tile/viewer/reason): the engine's own spotting rules (spot_all 0x5B6260) legitimately
// reveal a hidden stack to a mover within 2 tiles when the stack holds more than one unit, the observer has
// a sensor ability / stands in its own sensor range, or the two factions have no commlink.
bool g_debug = false;

void DebugWhyVisible(const char* via, int id, int f)
{
    if (!g_debug) return;
    const int n = Rd<int>(kVA_VehCount);
    if (id < 0 || id >= n) return;
    int top = id, guard = 0;
    for (int p = *reinterpret_cast<int16_t*>(Veh(top) + kVehPrev); p >= 0 && p < n && guard++ < 4096;
         p = *reinterpret_cast<int16_t*>(Veh(top) + kVehPrev))
        top = p;
    int count = 0, hiddenKinds = 0, seen = 0, own = 0;
    guard = 0;
    for (int i = top; i >= 0 && i < n && guard++ < 4096;
         i = *reinterpret_cast<int16_t*>(Veh(i) + kVehNext)) {
        const BYTE* v = Veh(i);
        ++count;
        if (v[kVehFaction] == f) ++own;
        const int unit = *reinterpret_cast<const int16_t*>(v + kVehUnit);
        const uint32_t abil = unit >= 0
            ? *reinterpret_cast<const uint32_t*>(At(kVA_Units) + unit * kUnitSize + kUnitAbility) : 0;
        if ((abil & kAblHidden) != 0 ||
            (*reinterpret_cast<const uint16_t*>(v + kVehFlags) & kVflagInvisible) != 0)
            ++hiddenKinds;
        if ((v[kVehVisibility] >> f) & 1) ++seen;
    }
    if (hiddenKinds == 0 || own != 0) return;                   // nothing hidden-kind here: not our business
    const int x = *reinterpret_cast<int16_t*>(Veh(id) + kVehX), y = *reinterpret_cast<int16_t*>(Veh(id) + kVehY);
    const BYTE* sq = MapSq(x, y);
    const bool base = sq && (*reinterpret_cast<const uint32_t*>(sq + 8) & 1) != 0;
    static uint32_t recent[64]; static int next = 0;
    const uint32_t key = (static_cast<uint32_t>(x) << 20) ^ (static_cast<uint32_t>(y) << 8) ^
                         (static_cast<uint32_t>(f) << 4) ^ (seen ? 1u : 0u) ^ (base ? 2u : 0u) ^
                         (static_cast<uint32_t>(count) << 28);
    for (uint32_t k : recent) if (k == key) return;
    recent[next++ & 63] = key;
    char s[200];
    _snprintf_s(s, sizeof s, _TRUNCATE,
                "[uimod] aivis dbg: %s viewer=%d sees (%d,%d): stack=%d hiddenKind=%d seenBits=%d base=%d -> %s\n",
                via, f, x, y, count, hiddenKinds, seen, base ? 1 : 0,
                base ? "in a base (always known)"
                     : seen ? "already marked seen by the engine (see the SPOTTED line for who/why; marks last until the unit moves)"
                            : "exposed by rule: a unit here is neither hidden-kind nor loaded in a hidden-kind transport");
    UimodLog(s);
}

struct FixRec { int x, y, judged; };
FixRec g_fixRec[16]; int g_fixNext = 0;   // debug: what spot_all judged each tile by
int __cdecl WrapSpotAllStackCount(int veh, int type, int a3, int a4, int a5);

// ---- diagnostics: WHO spotted a hidden unit, and by which engine rule (AiVisDebug=1 only) -----------
// spot_all(veh, flag) 0x5B6260 runs for every mover and is where the engine marks nearby stacks seen. Its six
// call sites are re-pointed here ONLY in debug mode: snapshot the seen bytes of hidden-kind units near the
// mover, run the engine, log every bit that appeared together with the inputs of spot_all's reveal test.
using FSpotAll  = void(__cdecl*)(int veh, int flag);
using FIsSensor = int(__cdecl*)(int x, int y);
constexpr uintptr_t kVA_SpotAll  = 0x005B6260;
constexpr uintptr_t kVA_IsSensor = 0x005BF010;
constexpr uintptr_t kVA_DiploStatus = 0x0096C9F8;      // uint32 [observer*0x833 + other] ; bit 8 = commlink
const uint32_t kSitesSpotAll[] = { 0x4ccfc3, 0x511655, 0x5230ba, 0x57b813, 0x598d3e, 0x5c04ee };

// spot_all's FIRST is_sensor call (0x5B63A1) asks "does the MOVER stand on a sensor?" -- with whose_territory ==
// mover right after it, that is the rule that lets a unit without Deep Radar see adjacent cloaked units.
// is_sensor answers 2 for a Geosynchronous Survey Pod base, but only on the base tile and the 8 tiles at
// dx,dy in {0,2}: nine VIRTUAL sensor sites whose radius-2 effects (defence bonus, ordinary detection) blanket
// the base radius. For this one "standing exactly ON a sensor" question the lattice shows through as nine
// arbitrary tiles (user test 2026-09-19: plane at (25,23) saw a cloaked unit, one tile over it did not).
// Here the pod covers its base's whole work radius. ONLY this call site: is_sensor itself has 14 other
// callers (combat bonus, AI terraforming, pathing) that must keep the engine's answer.
constexpr uintptr_t kVA_SpotAllMoverSensorSite = 0x005B63A1;
constexpr uintptr_t kVA_Bases = 0x0097D040, kVA_BaseCount = 0x009A64CC;
constexpr int kBaseSize = 0x134, kBaseFaction = 0x04, kBaseFacilities = 0x8C, kFacSurveyPod = 41;

int __cdecl WrapSpotAllMoverSensor(int x, int y)
{
    const int r = reinterpret_cast<FIsSensor>(At(kVA_IsSensor))(x, y);
    if (r != 0 || !PodRadiusActive()) return r;
    const BYTE* sq = MapSq(x, y);
    if (!sq) return 0;
    const int owner = static_cast<int8_t>(sq[7]);                       // the engine then demands owner == mover
    if (owner < 1 || owner > 7) return 0;
    const int w = Rd<int>(kVA_MapAreaX), nb = Rd<int>(kVA_BaseCount);
    const bool flat = (Rd<uint32_t>(kVA_MapToggleFlat) & 1) != 0;
    for (int i = 0; i < nb && i < 512; ++i) {
        const BYTE* base = At(kVA_Bases) + i * kBaseSize;
        if (base[kBaseFaction] != owner) continue;
        if (!(base[kBaseFacilities + kFacSurveyPod / 8] & (1 << (kFacSurveyPod % 8)))) continue;
        int dx = x - *reinterpret_cast<const int16_t*>(base); if (dx < 0) dx = -dx;
        if (!flat && dx > w / 2) dx = w - dx;
        int dy = y - *reinterpret_cast<const int16_t*>(base + 2); if (dy < 0) dy = -dy;
        if (dx <= 3 && dy <= 3 && dx + dy <= 4) return 2;               // the 21-tile work radius
    }
    return 0;
}

void __cdecl WrapSpotAllDbg(int veh, int flag)
{
    const int n = Rd<int>(kVA_VehCount);
    if (veh < 0 || veh >= n) { reinterpret_cast<FSpotAll>(At(kVA_SpotAll))(veh, flag); return; }
    const int mx = *reinterpret_cast<int16_t*>(Veh(veh) + kVehX), my = *reinterpret_cast<int16_t*>(Veh(veh) + kVehY);
    const int mf = VehFaction(veh);

    struct Snap { int id; BYTE vis; };
    static Snap snap[256];
    int ns = 0;
    const int w = Rd<int>(kVA_MapAreaX);
    for (int i = 0; i < n && ns < 256; ++i) {
        const BYTE* v = Veh(i);
        if (v[kVehFaction] == mf || !HiddenKind(v)) continue;
        int dx = *reinterpret_cast<const int16_t*>(v + kVehX) - mx; if (dx < 0) dx = -dx;
        if ((Rd<uint32_t>(kVA_MapToggleFlat) & 1) == 0 && dx > w / 2) dx = w - dx;
        int dy = *reinterpret_cast<const int16_t*>(v + kVehY) - my; if (dy < 0) dy = -dy;
        if (dx > 8 || dy > 8) continue;
        snap[ns].id = i; snap[ns].vis = v[kVehVisibility]; ++ns;
    }

    const BYTE moverVis = Veh(veh)[kVehVisibility];
    const bool moverHidden = HiddenKind(Veh(veh));

    reinterpret_cast<FSpotAll>(At(kVA_SpotAll))(veh, flag);

    if (mf <= 0 || mf >= 8 || veh >= Rd<int>(kVA_VehCount)) return;
    // the REVERSE rule: a hidden mover reveals ITSELF to an adjacent stack whose judged unit has Deep Radar
    // (or to a faction it has no commlink with) -- its own stack never counts, sensors never count
    if (moverHidden) {
        const BYTE gainedSelf = static_cast<BYTE>(Veh(veh)[kVehVisibility] & ~moverVis & ~(1u << mf));
        if (gainedSelf) {
            char r[200];
            _snprintf_s(r, sizeof r, _TRUNCATE, "[uimod] aivis dbg: REVEALED ITSELF fac %d hidden veh %d moved to (%d,%d) and is now "
                        "seen by faction mask %02X (an adjacent unit of theirs has Deep Radar, or no commlink)\n",
                        mf, veh, mx, my, gainedSelf);
            UimodLog(r);
        }
    }
    for (int k = 0; k < ns; ++k) {
        const int i = snap[k].id;
        if (i >= Rd<int>(kVA_VehCount)) continue;
        const BYTE* v = Veh(i);
        const BYTE gained = static_cast<BYTE>(v[kVehVisibility] & ~snap[k].vis);
        if (!((gained >> mf) & 1)) continue;
        const int tx = *reinterpret_cast<const int16_t*>(v + kVehX), ty = *reinterpret_cast<const int16_t*>(v + kVehY);
        const int munit = *reinterpret_cast<int16_t*>(Veh(veh) + kVehUnit);
        const uint32_t mabil = munit >= 0
            ? *reinterpret_cast<const uint32_t*>(At(kVA_Units) + munit * kUnitSize + kUnitAbility) : 0;
        const int sensorTile = WrapSpotAllMoverSensor(mx, my);      // what spot_all itself was told
        const BYTE* msq = MapSq(mx, my);
        const int terr = msq ? static_cast<int8_t>(msq[7]) : -1;
        const uint32_t diplo = Rd<uint32_t>(kVA_DiploStatus + (mf * 0x833 + v[kVehFaction]) * 4);
        int stack = 0, guard = 0, top = i;
        for (int pv = *reinterpret_cast<int16_t*>(Veh(top) + kVehPrev); pv >= 0 && guard++ < 4096;
             pv = *reinterpret_cast<int16_t*>(Veh(top) + kVehPrev)) top = pv;
        guard = 0;
        char dump[120]; int dl = 0; dump[0] = 0;
        for (int q = top; q >= 0 && guard++ < 4096; q = *reinterpret_cast<int16_t*>(Veh(q) + kVehNext)) {
            ++stack;
            if (dl < 100)
                dl += _snprintf_s(dump + dl, sizeof dump - dl, _TRUNCATE, " %d:o%02X:w%d:h%d", q,
                                  Veh(q)[kVehOrder] & 0xFF, *reinterpret_cast<int16_t*>(Veh(q) + kVehWaypointX0),
                                  HiddenKind(Veh(q)) ? 1 : 0);
        }
        int ddx = tx - mx; if (ddx < 0) ddx = -ddx;
        if ((Rd<uint32_t>(kVA_MapToggleFlat) & 1) == 0 && ddx > w / 2) ddx = w - ddx;
        int ddy = ty - my; if (ddy < 0) ddy = -ddy;
        const int dist = (ddx + ddy) / 2;
        int tested = -1;                                          // the unit the engine judged the stack by
        for (const FixRec& e : g_fixRec) if (e.x == tx && e.y == ty) tested = e.judged;
        const bool testedHidden = tested < 0 || (tested >= 0 && tested < Rd<int>(kVA_VehCount) && HiddenKind(Veh(tested)));
        const int effCount = WrapSpotAllStackCount(i, 1, -1, -1, -1);
        char s[520];
        _snprintf_s(s, sizeof s, _TRUNCATE,
                    "[uimod] aivis dbg: SPOTTED veh %d of fac %d at (%d,%d) [stack=%d, counts as %d, judged by veh %d hiddenKind=%d] "
                    "by fac %d veh %d \"%.24s\" at (%d,%d) dist=%d: deepRadar=%d sensorTile=%d moverTerritory=%d commlink=%d units[id:order:wp0:hidden]=%s -> %s\n",
                    i, v[kVehFaction], tx, ty, stack, effCount, tested, testedHidden ? 1 : 0, mf, veh,
                    munit >= 0 ? reinterpret_cast<const char*>(At(kVA_Units) + munit * kUnitSize) : "?",
                    mx, my, dist, (mabil & 2) ? 1 : 0, sensorTile, terr, (diplo & 8) ? 1 : 0, dump,
                    !testedHidden ? "the unit the engine judges the stack by is NOT hidden-kind: ordinary sighting (up to 2 squares)"
                    : dist > 1 ? "UNEXPECTED: hidden-kind stack seen beyond 1 square"
                    : effCount > 1 ? "rule: more than one unit in the stack"
                    : (mabil & 2) ? "rule: mover has Deep Radar (adjacent)"
                    : (sensorTile && terr == mf) ? "rule: mover stands ON a sensor in its own territory (adjacent)"
                    : !(diplo & 8) ? "rule: no commlink between the factions"
                    : "UNEXPECTED: no spot_all rule matched");
        UimodLog(s);
    }
}

// ---- spot_all's "more than one unit in the stack" reveal rule -----------------------------------------
// spot_all 0x5B6260 reveals a hidden stack to a nearby mover when `stack_check(stack, 1, -1, -1, -1) != 1`
// (site 0x5B7810): ANY second unit gives the stack away, so a submarine transport is exposed by its own
// cargo. With the option on, units LOADED in a hidden-kind transport are not counted -- the transport and
// its cargo spot as one unit; two subs, or a sub beside a loose unit, still count as several.
constexpr uintptr_t kVA_SpotAllCountSite = 0x005B7810;

// spot_all WAKES the stack it is looking at (wake_stack 0x5B6060, sites 0x5B7631 / 0x5B84A0) BEFORE it counts
// it: a passenger's ORDER_SENTRY_BOARD is cleared, and on LAND nothing else says "aboard" -- so a cloaked
// ground transport next to an enemy unit counted as 2 and was spotted (user trace 2026-09-19, hovertank
// transport at (10,56): "counts as 2 ... rule: more than one unit"). At sea the land-unit-on-ocean fallback
// masked this. Fix: remember who was riding a hidden-kind transport at the moment of the wake; the count that
// follows (same spot_all pass, same tile) still treats them as cargo.
using FWake = void(__cdecl*)(int veh);
constexpr uintptr_t kVA_WakeStack = 0x005B6060;
const uint32_t kSitesSpotAllWake[] = { 0x5b7631, 0x5b84a0 };
int g_wakeX = -1, g_wakeY = -1, g_wakeN = 0;
int g_wakeRiders[48];

bool WasRiderAtWake(int i, int x, int y)
{
    if (x != g_wakeX || y != g_wakeY) return false;
    for (int k = 0; k < g_wakeN; ++k) if (g_wakeRiders[k] == i) return true;
    return false;
}

void __cdecl WrapSpotAllWake(int veh)
{
    const int n = Rd<int>(kVA_VehCount);
    g_wakeN = 0; g_wakeX = g_wakeY = -1;
    if (veh >= 0 && veh < n && CargoOneActive()) {
        const int x = *reinterpret_cast<int16_t*>(Veh(veh) + kVehX), y = *reinterpret_cast<int16_t*>(Veh(veh) + kVehY);
        if (const BYTE* sq = MapSq(x, y)) {
            const bool ocean = (sq[0] & 0xE0) < 0x60;
            int top = veh, guard = 0;
            for (int p = *reinterpret_cast<int16_t*>(Veh(top) + kVehPrev); p >= 0 && p < n && guard++ < 4096;
                 p = *reinterpret_cast<int16_t*>(Veh(top) + kVehPrev))
                top = p;
            if (StackHasHiddenCarrier(top, n)) {
                g_wakeX = x; g_wakeY = y;
                guard = 0;
                for (int i = top; i >= 0 && i < n && guard++ < 4096 && g_wakeN < 48;
                     i = *reinterpret_cast<int16_t*>(Veh(i) + kVehNext))
                    if (RidesHiddenTransport(i, n, x, y, ocean, true)) g_wakeRiders[g_wakeN++] = i;
            }
        }
    }
    // Passengers of a hidden-kind transport are NOT woken: waking clears the only thing that says "aboard",
    // which would also make the AI filter (HiddenStack) and every later pass see a loose plain unit on the
    // tile. The transport itself still wakes, so a human owner is still alerted. Exact rollback: order + state.
    static BYTE savedOrder[48]; static uint32_t savedState[48];
    for (int k = 0; k < g_wakeN; ++k) {
        savedOrder[k] = Veh(g_wakeRiders[k])[kVehOrder];
        savedState[k] = *reinterpret_cast<uint32_t*>(Veh(g_wakeRiders[k]) + 4);
    }
    reinterpret_cast<FWake>(At(kVA_WakeStack))(veh);
    for (int k = 0; k < g_wakeN; ++k) {
        if (g_wakeRiders[k] >= Rd<int>(kVA_VehCount)) continue;
        Veh(g_wakeRiders[k])[kVehOrder] = savedOrder[k];
        *reinterpret_cast<uint32_t*>(Veh(g_wakeRiders[k]) + 4) = savedState[k];
    }
}

int __cdecl WrapSpotAllStackCount(int veh, int type, int a3, int a4, int a5)
{
    const int r = reinterpret_cast<FStackCk>(At(kVA_StackCheck))(veh, type, a3, a4, a5);
    const int n = Rd<int>(kVA_VehCount);
    if (r <= 1 || type != 1 || a3 >= 0 || veh < 0 || veh >= n || !CargoOneActive()) return r;
    const int x = *reinterpret_cast<int16_t*>(Veh(veh) + kVehX), y = *reinterpret_cast<int16_t*>(Veh(veh) + kVehY);
    const BYTE* sq = MapSq(x, y);
    if (!sq) return r;
    const bool ocean = (sq[0] & 0xE0) < 0x60;
    int top = veh, guard = 0;
    for (int p = *reinterpret_cast<int16_t*>(Veh(top) + kVehPrev); p >= 0 && p < n && guard++ < 4096;
         p = *reinterpret_cast<int16_t*>(Veh(top) + kVehPrev))
        top = p;
    const bool hiddenCarrier = StackHasHiddenCarrier(top, n);
    int count = 0;
    guard = 0;
    for (int i = top; i >= 0 && i < n && guard++ < 4096; i = *reinterpret_cast<int16_t*>(Veh(i) + kVehNext))
        if (!RidesHiddenTransport(i, n, x, y, ocean, hiddenCarrier) && !(hiddenCarrier && WasRiderAtWake(i, x, y))) ++count;
    return count < 1 ? 1 : count;
}

// The other half of the cargo option. spot_all judges a stack's hiddenness by ONE unit -- the one stack_fix
// 0x5B8E10 returns for the tile (sites 0x5B743D adjacent ring, 0x5B7FCA radius-2 ring). When that unit is a
// plain passenger, the engine treats the whole submarine as an ordinary visible stack (seen from 2 squares:
// user trace 2026-09-18, loaded sub at (79,55) spotted from (79,51)). With the option on, a passenger of a
// hidden-kind transport is answered with the TRANSPORT, so the engine tests the right unit. Everything
// spot_all does with the id afterwards is stack-level (veh_top / wake_stack / want_to_wake).
using FStackFix = int(__cdecl*)(int veh);
constexpr uintptr_t kVA_StackFix = 0x005B8E10;
const uint32_t kSitesSpotAllStackFix[] = { 0x5b743d, 0x5b7fca };

int StackFixAdjusted(int r)      // pure: never calls the engine (stack_fix can reorder the stack)
{
    const int n = Rd<int>(kVA_VehCount);
    if (r < 0 || r >= n || !CargoOneActive() || HiddenKind(Veh(r))) return r;
    const int x = *reinterpret_cast<int16_t*>(Veh(r) + kVehX), y = *reinterpret_cast<int16_t*>(Veh(r) + kVehY);
    const BYTE* sq = MapSq(x, y);
    if (!sq) return r;
    const bool ocean = (sq[0] & 0xE0) < 0x60;
    int top = r, guard = 0;
    for (int p = *reinterpret_cast<int16_t*>(Veh(top) + kVehPrev); p >= 0 && p < n && guard++ < 4096;
         p = *reinterpret_cast<int16_t*>(Veh(top) + kVehPrev))
        top = p;
    if (!StackHasHiddenCarrier(top, n) || !RidesHiddenTransport(r, n, x, y, ocean, true)) return r;
    // prefer the transport the passenger names; else any hidden-kind carrier in the stack
    if (static_cast<int8_t>(Veh(r)[kVehOrder]) == kOrderSentryBoard) {
        const int t = *reinterpret_cast<const int16_t*>(Veh(r) + kVehWaypointX0);
        if (t >= 0 && t < n && HiddenKind(Veh(t)) &&
            *reinterpret_cast<int16_t*>(Veh(t) + kVehX) == x && *reinterpret_cast<int16_t*>(Veh(t) + kVehY) == y)
            return t;
    }
    guard = 0;
    for (int i = top; i >= 0 && i < n && guard++ < 4096; i = *reinterpret_cast<int16_t*>(Veh(i) + kVehNext)) {
        const int unit = *reinterpret_cast<const int16_t*>(Veh(i) + kVehUnit);
        if (unit >= 0 && HiddenKind(Veh(i)) && At(kVA_Units)[unit * kUnitSize + kUnitCarry] != 0) return i;
    }
    return r;
}

int __cdecl WrapSpotAllStackFix(int veh)
{
    const int r = StackFixAdjusted(reinterpret_cast<FStackFix>(At(kVA_StackFix))(veh));
    if (g_debug && r >= 0 && r < Rd<int>(kVA_VehCount)) {
        FixRec& e = g_fixRec[g_fixNext++ & 15];
        e.x = *reinterpret_cast<int16_t*>(Veh(r) + kVehX); e.y = *reinterpret_cast<int16_t*>(Veh(r) + kVehY); e.judged = r;
    }
    return r;
}

// ---- wrappers the enemy_move call sites land on ---------------------------------------------------

int __cdecl WrapVehAt(int x, int y)
{
    const int r = reinterpret_cast<FTile2>(At(kVA_VehAt))(x, y);
    if (g_viewer < 0 || r < 0) return r;
    if (HiddenStack(r, g_viewer)) return -1;
    DebugWhyVisible("veh_at", r, g_viewer);
    return r;
}

int __cdecl WrapVehWho(int x, int y)
{
    const int r = reinterpret_cast<FTile2>(At(kVA_VehWho))(x, y);
    return (g_viewer >= 0 && r >= 0 && r != g_viewer && TileHidden(x, y, g_viewer)) ? -1 : r;
}

int __cdecl WrapAnythingAt(int x, int y)
{
    const int r = reinterpret_cast<FTile2>(At(kVA_AnythingAt))(x, y);
    return (g_viewer >= 0 && r >= 0 && r != g_viewer && TileHidden(x, y, g_viewer)) ? -1 : r;
}

int __cdecl WrapStackCheck(int veh, int type, int a3, int a4, int a5)
{
    if (g_viewer >= 0 && veh >= 0 && veh < Rd<int>(kVA_VehCount) && VehFaction(veh) != g_viewer &&
        HiddenStack(veh, g_viewer))
        return 0;
    return reinterpret_cast<FStackCk>(At(kVA_StackCheck))(veh, type, a3, a4, a5);
}

// Both callers of enemy_move land here: establish the planning faction for the wrappers above.
// Debug: after an AI unit has planned, is it HEADING for a stack it has never seen? A go-to whose destination
// is on / next to an unseen hidden stack means some knowledge path is still unfiltered (or an old goal from an
// earlier sighting is being followed) -- this is how "the AI found my sub immediately" gets explained.
void DebugDestination(int veh, int f)
{
    const int n = Rd<int>(kVA_VehCount);
    if (veh < 0 || veh >= n) return;
    const BYTE* m = Veh(veh);
    const int order = static_cast<int8_t>(m[kVehOrder]);
    if (order != 0x18 && order != 0x58) return;                            // go-to family only
    const int wx = *reinterpret_cast<const int16_t*>(m + kVehWaypointX0);
    const int wy = *reinterpret_cast<const int16_t*>(m + 0x1C);             // waypoint_y[0]
    if (wx < 0 || wy < 0) return;
    if (const BYTE* dsq = MapSq(wx, wy))
        if (*reinterpret_cast<const uint32_t*>(dsq + 8) & 1) return;   // going to a BASE (aircraft returning home): not evidence
    const int w = Rd<int>(kVA_MapAreaX);
    for (int i = 0; i < n; ++i) {
        const BYTE* v = Veh(i);
        if (v[kVehFaction] == f || !HiddenKind(v) || ((v[kVehVisibility] >> f) & 1)) continue;
        int dx = *reinterpret_cast<const int16_t*>(v + kVehX) - wx; if (dx < 0) dx = -dx;
        if ((Rd<uint32_t>(kVA_MapToggleFlat) & 1) == 0 && dx > w / 2) dx = w - dx;
        int dy = *reinterpret_cast<const int16_t*>(v + kVehY) - wy; if (dy < 0) dy = -dy;
        if ((dx + dy) / 2 > 1) continue;
        static uint32_t recent[32]; static int next = 0;
        const uint32_t key = (static_cast<uint32_t>(veh) << 16) ^ (static_cast<uint32_t>(wx) << 8) ^ static_cast<uint32_t>(wy);
        for (uint32_t k : recent) if (k == key) return;
        recent[next++ & 31] = key;
        const int unit = *reinterpret_cast<const int16_t*>(m + kVehUnit);
        char s[260];
        _snprintf_s(s, sizeof s, _TRUNCATE,
                    "[uimod] aivis dbg: HEADING fac %d veh %d \"%.24s\" at (%d,%d) order=%02X goes to (%d,%d), which is %s UNSEEN hidden "
                    "veh %d of fac %d at (%d,%d)\n", f, veh,
                    unit >= 0 ? reinterpret_cast<const char*>(At(kVA_Units) + unit * kUnitSize) : "?",
                    *reinterpret_cast<const int16_t*>(m + kVehX), *reinterpret_cast<const int16_t*>(m + kVehY), order & 0xFF,
                    wx, wy, (dx + dy) == 0 ? "ON" : "next to", i, v[kVehFaction],
                    *reinterpret_cast<const int16_t*>(v + kVehX), *reinterpret_cast<const int16_t*>(v + kVehY));
        UimodLog(s);
        return;
    }
}

int __cdecl WrapEnemyMove(int veh)
{
    const int saved = g_viewer;
    g_viewer = -1;
    if (veh >= 0 && veh < Rd<int>(kVA_VehCount) && Enabled()) {
        const int f = VehFaction(veh);
        if (IsFilteredAi(f)) g_viewer = f;
    }
    const int viewer = g_viewer;
    const int r = reinterpret_cast<FVeh1>(At(kVA_EnemyMove))(veh);
    if (g_debug && viewer >= 0) DebugDestination(veh, viewer);
    g_viewer = saved;
    return r;
}

// The bump: a filtered AI unit stepping into an unseen hidden stack discovers it instead of attacking. 1 = handled
// (the stack is spotted, the order cleared; the order_veh caller returns 0), 0 = let order_veh run. Shared with the
// Thinker half, whose order_veh is a different function (thinkeraivis.cpp).
int BumpCheck(int veh, int dir)
{
    if (dir >= 0 && dir < 8 && veh >= 0 && veh < Rd<int>(kVA_VehCount) && Enabled()) {
        const int f = VehFaction(veh);
        if (IsFilteredAi(f)) {
            int tx = *reinterpret_cast<int16_t*>(Veh(veh) + kVehX) + Rd<int>(kVA_DirDX + dir * 4);
            const int ty = *reinterpret_cast<int16_t*>(Veh(veh) + kVehY) + Rd<int>(kVA_DirDY + dir * 4);
            if ((Rd<uint32_t>(kVA_MapToggleFlat) & 1) == 0) {
                const int w = Rd<int>(kVA_MapAreaX);
                if (tx < 0) tx += w; else if (tx >= w) tx -= w;
            }
            const BYTE* sq = MapSq(tx, ty);
            if (sq && (*reinterpret_cast<const uint32_t*>(sq + 8) & 3) == 2) {   // units, no base
                const int tgt = reinterpret_cast<FTile2>(At(kVA_VehAt))(tx, ty);
                if (tgt >= 0 && HiddenStack(tgt, f)) {
                    reinterpret_cast<FSpot>(At(kVA_SpotStack))(tgt, f);
                    Veh(veh)[kVehOrder] = 0;
                    return 1;
                }
            }
        }
    }
    return 0;
}

// order_veh entry (the engine's; without Thinker).
int __cdecl HookOrderVeh(int veh, int dir, int a3)
{
    if (BumpCheck(veh, dir)) return 0;
    return g_orderVehTramp(veh, dir, a3);
}

// ---- pathfinder sites ------------------------------------------------------------------------------

// Called from the three site stubs with the tile the pathfinder is weighing and the faction it paths
// for. Nonzero = treat the tile as unoccupied. The map stores x>>1; x's parity equals y's.
int __cdecl PathTileHidden(const BYTE* tile, int faction)
{
    if (faction <= 0 || faction >= 8) return 0;                // natives: vanilla
    if (IsHuman(faction) ? !HumanLeakFixActive() : !Enabled()) return 0;
    if ((tile[2] & 0x0F) == faction) return 0;                 // own stack: the common case, no scan
    const int half = Rd<int>(kVA_MapHalfX);
    if (half <= 0) return 0;
    const int idx = static_cast<int>(tile - Rd<BYTE*>(kVA_MapTiles)) / kMapSize;
    const int y = idx / half;
    const int x = (idx % half) * 2 + (y & 1);
    return TileHidden(x, y, faction) ? 1 : 0;
}

void* g_pf1Empty = nullptr; void* g_pf1Occupied = nullptr;     // resume addresses, set at install
void* g_pf2Empty = nullptr; void* g_pf2Occupied = nullptr;
void* g_pmResume = nullptr;

// Path_find site 1 (replaces `test byte [eax+8],2 ; jne occupied`): eax = tile, faction = Path_find's
// 7th arg [ebp+0x1C]. Flags are dead on both successor paths.
void __declspec(naked) StubPathFind1()
{
    __asm {
        test byte ptr [eax + 8], 2
        jz   pf1_empty
        pushad
        push dword ptr [ebp + 0x1C]
        push eax
        call PathTileHidden
        add  esp, 8
        test eax, eax
        popad
        jnz  pf1_empty
        jmp  dword ptr [g_pf1Occupied]
    pf1_empty:
        jmp  dword ptr [g_pf1Empty]
    }
}

// Path_find site 2: the same test in the second search loop.
void __declspec(naked) StubPathFind2()
{
    __asm {
        test byte ptr [eax + 8], 2
        jz   pf2_empty
        pushad
        push dword ptr [ebp + 0x1C]
        push eax
        call PathTileHidden
        add  esp, 8
        test eax, eax
        popad
        jnz  pf2_empty
        jmp  dword ptr [g_pf2Occupied]
    pf2_empty:
        jmp  dword ptr [g_pf2Empty]
    }
}

// Path_move site (replaces `mov al,[eax+edx*4+8] ; test al,3`; the `je passable` that follows stays):
// ecx = tile, faction = [ebp-0xC]. Returns to that je with ZF=1 for "nothing in the way".
void __declspec(naked) StubPathMove()
{
    __asm {
        mov  al, byte ptr [ecx + 8]
        test al, 3
        jz   pm_done
        pushad
        push dword ptr [ebp - 0x0C]
        push ecx
        call PathTileHidden
        add  esp, 8
        test eax, eax
        popad
        jz   pm_occupied
        xor  eax, eax
        jmp  pm_done
    pm_occupied:
        mov  al, byte ptr [ecx + 8]
        test al, 3
    pm_done:
        jmp  dword ptr [g_pmResume]
    }
}

// ---- diplomacy: "withdraw your units from my territory" -------------------------------------------
// territory(owner, intruder, ...) 0x55EB80 is the ONE counter behind both directions of the demand (the
// human's commlink "demand withdrawal" reply, the AI's complaints in communicate / enemy_diplomacy /
// make_treaty). It walks the unit array with no visibility test, so a faction could complain about -- and
// get a "we will withdraw" / "we have no units there" answer about -- units it has never seen. Its per-unit
// whose_territory call is the hook: an intruder stack hidden from the territory's owner is reported as
// "not in anyone's territory", i.e. not counted. do_withdrawal 0x548F80 then leaves such stacks where they
// are (its per-unit base_find_2 call finds "no base to go home to"): the owner never knew of them, and the
// intruder's sneaking units are not yanked home by an agreement about the visible ones.

using FWhoseTerr = int(__cdecl*)(int faction, int x, int y, int* base, int flag);
using FBaseFind2 = int(__cdecl*)(int x, int y, int faction);
constexpr uintptr_t kVA_WhoseTerritory   = 0x004E3EF0;
constexpr uintptr_t kVA_BaseFind2        = 0x004E3C60;
constexpr uintptr_t kVA_TerritorySite    = 0x0055ED62;   // territory(): call whose_territory
constexpr uintptr_t kVA_WithdrawSite     = 0x005491A3;   // do_withdrawal(): call base_find_2

// Does `owner` get the corrected (visibility-honouring) answer? Humans always (net: host bit 1), AIs by
// the checkbox.
bool LeakFixAppliesTo(int owner)
{
    if (owner <= 0 || owner >= 8) return false;
    return IsHuman(owner) ? HumanLeakFixActive() : Enabled();
}

int __cdecl WrapTerritoryWhose(int faction, int x, int y, int* base, int flag)
{
    const int owner = reinterpret_cast<FWhoseTerr>(At(kVA_WhoseTerritory))(faction, x, y, base, flag);
    if (owner != faction && LeakFixAppliesTo(owner) && TileHidden(x, y, owner)) return -1;
    return owner;
}

bool g_withdrawAll = false;     // the human chose "also withdraw my undetected cloaked troops" (below)

int __cdecl WrapWithdrawBaseFind(int x, int y, int faction)
{
    if (g_withdrawAll) return reinterpret_cast<FBaseFind2>(At(kVA_BaseFind2))(x, y, faction);
    if (const BYTE* sq = MapSq(x, y)) {
        const int owner = static_cast<int8_t>(sq[7]);              // the tile's territory owner
        if (owner != faction && LeakFixAppliesTo(owner) && TileHidden(x, y, owner)) return -1;
    }
    return reinterpret_cast<FBaseFind2>(At(kVA_BaseFind2))(x, y, faction);
}

// ---- diplomacy: the human's extra reply "also withdraw my undetected cloaked troops" ------------------
// communicate 0x54FFD0 (esi = the AI that speaks, edi = the human) shows #GETOUT<1..5> through X_pops_11 at
// 0x5503E1; reply 0 runs do_withdrawal(ai, human) at 0x55046F, which (above) leaves the human's unseen hidden
// units where they are. Popups have no per-option mask -- every option line of a label is shown -- so, like
// vanilla's #DISBAND/#DISBAND2, the extra reply needs its own label. It is generated from the very block the
// engine would have shown (alien speakers' files included, so translated/modded wording survives): reply 0's
// text + kGetoutSuffix is inserted as reply 1 into a one-label file, shown through X_pops_18 (a filename other
// than SCRIPT goes straight to pops_18). Single player only: in a network game do_withdrawal runs on every
// peer (msg 0x244A) and a local "withdraw all" would desync them.

using FXPops11 = int(__cdecl*)(const char* label, int flags, void* sprite, void* fn);
using FXPops18 = int(__cdecl*)(const char* file, const char* label, int a3, char* a4, int flags, void* sprite,
                               int x, int y, void* fn);
using FDoWithdrawal = int(__cdecl*)(int owner, int intruder);
constexpr uintptr_t kVA_XPops11 = 0x005BF7D0, kVA_XPops18 = 0x005BF930, kVA_DoWithdrawal = 0x00548F80;
constexpr uintptr_t kVA_GetoutPopSite      = 0x005503E1;   // communicate: call X_pops_11("GETOUTn", ...)
constexpr uintptr_t kVA_GetoutWithdrawSite = 0x0055046F;   // communicate: call do_withdrawal (reply 0)
constexpr uintptr_t kVA_GetoutMutualSite   = 0x005505EB;   // communicate: call do_withdrawal(ai, human), reply 1 accepted
constexpr uintptr_t kVA_MFactionFlags = 0x00946F58;        // MFactions[f].rule_flags, stride 0x59C; 0x80 = alien
constexpr uintptr_t kVA_ExpansionOn   = 0x009A6488;
constexpr uintptr_t kVA_DiploSecond   = 0x0093F7CC;
constexpr int kMFactionSize = 0x59C, kUnitPlan = 0x2A, kPlanExempt = 0x0B;
const char kGetoutFile[]   = "uimod_getout";
const char kGetoutSuffix[] = " (Including undetected cloaked troops)";   // fits one line above 1024x768; wraps there
bool g_getoutOk = false;
bool g_wantAll = false;             // an "all" reply was chosen; consumed by the next withdrawal in communicate

// Would an agreed withdrawal leave any of `human`'s units behind in `ai`'s territory? (do_withdrawal's own
// filters + WrapWithdrawBaseFind's skip test)
bool HumanHasUnseenIntruders(int ai, int human)
{
    if (!LeakFixAppliesTo(ai)) return false;
    const int n = Rd<int>(kVA_VehCount);
    for (int i = 0; i < n; ++i) {                                         // VehCount bounds the live array (Thinker: up to 8192)
        const BYTE* v = Veh(i);
        if (v[kVehFaction] != human) continue;
        const int unit = *reinterpret_cast<const int16_t*>(v + kVehUnit);
        if (unit >= 0 && At(kVA_Units)[unit * kUnitSize + kUnitPlan] == kPlanExempt) continue;
        const int x = *reinterpret_cast<const int16_t*>(v + kVehX), y = *reinterpret_cast<const int16_t*>(v + kVehY);
        const BYTE* sq = MapSq(x, y);
        if (!sq || (sq[0] & 0xE0) < 0x60 || static_cast<int8_t>(sq[7]) != ai) continue;
        if (TileHidden(x, y, ai)) return true;
    }
    return false;
}

bool GameFilePath(const char* name, char* out, size_t cap)
{
    char exe[MAX_PATH];
    const DWORD n = GetModuleFileNameA(nullptr, exe, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return false;
    char* slash = strrchr(exe, '\\');
    if (!slash) return false;
    slash[1] = 0;
    return _snprintf_s(out, cap, _TRUNCATE, "%s%s", exe, name) > 0;
}

// Copy `#label`'s block out of script file `name` with the extra reply inserted after reply 0.
bool ExtractGetout(const char* name, const char* label, char* out, size_t cap)
{
    char path[MAX_PATH];
    if (!GameFilePath(name, path, sizeof path)) return false;
    FILE* f = nullptr;
    if (fopen_s(&f, path, "rb") != 0 || !f) return false;
    fseek(f, 0, SEEK_END);
    const long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    char* data = size > 0 && size < (8 << 20) ? static_cast<char*>(malloc(size + 1)) : nullptr;
    const bool read = data && fread(data, 1, size, f) == static_cast<size_t>(size);
    fclose(f);
    if (!read) { free(data); return false; }
    data[size] = 0;

    bool ok = false;
    const size_t ll = strlen(label);
    size_t o = 0;
    auto put = [&](const char* s, size_t n) { if (o + n < cap) { memcpy(out + o, s, n); o += n; return true; } return false; };
    for (const char* p = data; p && *p; ) {
        const char* eol = strchr(p, '\n');
        const char* next = eol ? eol + 1 : p + strlen(p);
        if (p[0] == '#' && strncmp(p + 1, label, ll) == 0 && (p[1 + ll] == '\r' || p[1 + ll] == '\n')) {
            // header + body up to the blank line, the blank line, then the replies:
            // 0 withdraw, 1 withdraw all, 2 likewise, 3 likewise all, 4 refuse
            int stage = 0, replies = 0;                     // stage 0 body, 1 replies
            for (const char* q = p; *q; ) {
                const char* e = strchr(q, '\n');
                const char* qn = e ? e + 1 : q + strlen(q);
                size_t len = (e ? e : qn) - q;
                if (len && q[len - 1] == '\r') --len;
                if (stage == 0) {
                    if (!put(q, len) || !put("\r\n", 2)) break;
                    if (len == 0) stage = 1;
                } else {
                    if (len == 0 || q[0] == '#') { ok = replies == 3; break; }
                    if (!put(q, len)) break;
                    if (replies < 2 &&                      // withdraw / "only if you likewise": + the "all" twin
                        (!put("\r\n", 2) || !put(q, len) || !put(kGetoutSuffix, sizeof kGetoutSuffix - 1))) break;
                    if (!put("\r\n", 2)) break;
                    ++replies;
                }
                q = qn;
                if (!*q) ok = replies == 3;
            }
            break;
        }
        p = next;
    }
    free(data);
    static const char tail[] = "\r\n# ; This line must remain at end of file\r\n\r\n";
    if (ok) ok = put(tail, sizeof tail - 1);
    if (ok) out[o] = 0;
    return ok;
}

// Write uimod_getout.txt for `label`, reading the file X_pops_18 would have used for this conversation.
bool BuildGetoutFile(const char* label)
{
    static char block[8192];
    const auto alien = [](int f) {
        return f > 0 && f < 8 && (At(kVA_MFactionFlags)[f * kMFactionSize] & 0x80) != 0;
    };
    bool ok = false;
    if (Rd<int>(kVA_ExpansionOn) != 0) {
        if (alien(Rd<int>(kVA_CurrentPlayer))) ok = ExtractGetout("alienIscript.txt", label, block, sizeof block);
        else if (alien(Rd<int>(kVA_DiploSecond))) ok = ExtractGetout("alienuscript.txt", label, block, sizeof block);
    }
    if (!ok) ok = ExtractGetout("script.txt", label, block, sizeof block);
    char path[MAX_PATH];
    FILE* f = nullptr;
    if (ok) ok = GameFilePath("uimod_getout.txt", path, sizeof path) && fopen_s(&f, path, "wb") == 0 && f;
    if (ok) {
        static const char head[] = "; generated by uimod.dll (Longevity Mod) -- rewritten on demand, safe to delete\r\n\r\n";
        ok = fwrite(head, 1, sizeof head - 1, f) == sizeof head - 1 && fwrite(block, 1, strlen(block), f) == strlen(block);
        fclose(f);
    }
    if (!ok) {
        static bool said = false;
        if (!said) UimodLog("[uimod] aivis: could not build uimod_getout.txt -> stock withdrawal replies shown\n");
        said = true;
    }
    return ok;
}

int __cdecl WrapGetoutPopup(const int* a, int ai, int human)
{
    const char* label = reinterpret_cast<const char*>(a[0]);
    void* sprite = reinterpret_cast<void*>(a[2]);
    void* fn = reinterpret_cast<void*>(a[3]);
    g_wantAll = false;
    if (Rd<int>(kVA_MultiplayerActive) == 0 && IsHuman(human) && HumanHasUnseenIntruders(ai, human) &&
        BuildGetoutFile(label)) {
        const int r = reinterpret_cast<FXPops18>(At(kVA_XPops18))(kGetoutFile, label, -1, nullptr, a[1], sprite, 1, 1, fn);
        if (r >= 0 && r <= 4) {
            static const int stock[5] = { 0, 0, 1, 1, 2 };
            g_wantAll = (r == 1 || r == 3);
            return stock[r];
        }
    }
    return reinterpret_cast<FXPops11>(At(kVA_XPops11))(label, a[1], sprite, fn);
}

__declspec(naked) void StubGetoutPopup()
{
    __asm {
        lea  eax, [esp + 4]
        push edi
        push esi
        push eax
        call WrapGetoutPopup
        add  esp, 12
        ret
    }
}

int __cdecl WrapGetoutWithdraw(int owner, int intruder)
{
    g_withdrawAll = g_wantAll;          // the human's own withdrawal only; the AI's reciprocal one stays filtered
    g_wantAll = false;
    const int moved = reinterpret_cast<FDoWithdrawal>(At(kVA_DoWithdrawal))(owner, intruder);
    g_withdrawAll = false;
    return moved;
}

// ---- network carrier ------------------------------------------------------------------------------

// net_upkeep_phase's NEXT-UPKEEP broadcast lands here (host only reaches that call).
void __cdecl WrapUpkeepSend(int msg, int dest, int p1, int p2, int p3, int p4)
{
    if ((msg & 0xFFFF) == kMsgNextUpkeep && Rd<int>(kVA_NetIsServer) != 0) {
        p3 = static_cast<int>(LocalNetMask());
        p4 = static_cast<int>(kNetMagic);
    }
    reinterpret_cast<FMsgData>(At(kVA_MessageData))(msg, dest, p1, p2, p3, p4);
}

void __cdecl PeekNextUpkeep(const uint32_t* m)
{
    if (!m || (m[0] & 0xFFFF) != kMsgNextUpkeep) return;
    if (Rd<int>(kVA_NetIsServer) != 0) return;
    // a host without the mod sends 0/0: valid, and every bit off
    const bool ours = m[7] == kNetMagic;
    const uint32_t mask = ours ? m[6] : 0;
    if (!g_netValid || mask != g_netMask) {
        char s[96];
        _snprintf_s(s, sizeof s, _TRUNCATE, "[uimod] aivis: host settings mask=%08X (%s)\n",
                    mask, ours ? "mod host" : "vanilla host");
        UimodLog(s);
    }
    g_netMask = mask;
    g_netValid = true;
}

// NetDaemon_process_message entry (thiscall: ecx = daemon, [esp+4] = message). Peek, then run the
// relocated prologue + the rest of the function.
void __declspec(naked) HookProcessMessage()
{
    __asm {
        push ecx
        mov  eax, [esp + 8]
        push eax
        call PeekNextUpkeep
        add  esp, 4
        pop  ecx
        jmp  dword ptr [g_procMsgTramp]
    }
}

// ---- "your cloak is blown" flag mark ---------------------------------------------------------------
// A red exclamation mark with a white stroke on the top-right of the unit's status flag, wherever a flag is
// drawn (map, HUD stack strip, active-unit panel, stack picker, base garrison, battle report, F-report),
// when one of the LOCAL PLAYER's cloaked / submerged units is currently marked seen by another faction, and on a
// foreign cloaked / submerged unit the local player has detected.
//
// Every one of those views draws through veh_draw (0x5594F0). Its entry belongs to the exe patcher
// (thunk_hud_vehargs), so the hook is the function's LAST draw call instead -- the status-letter text out at
// 0x55A11D (call Buffer_write_cent_l_7, thiscall ecx=buf, RET 0xC), reached only when a flag was drawn. At
// that point veh_draw's own frame (ebp) holds everything:
//   [ebp+0x08] Buffer* dest        [ebp+0x10],[ebp+0x14] the flag's final x,y (chassis offset + stack shift)
//   [ebp+0x18] size (s = (size+16)/16 unless g_map_zoom_num > 0: then num/den; HUD views arrive pre-scaled)
//   [ebp-0x14] veh_id * 0x34       ([ebp+0x0C]'s low byte is reused as a temp by then -- do NOT read it)
//   [ebp+0x04] the caller's return address (the map / move-animation callers draw ONE unit for a stack)
// Drawn as clipped Buffer_fill_3 rects, not a sprite: the stroke and the bar/dot gap keep >= 1 px at every
// zoom (the flag is 9x13 at the furthest flag-drawing zoom), and PRACX scrolls units partly off-canvas.
constexpr uintptr_t kVA_VehDrawTailSite = 0x0055A11D;
constexpr uintptr_t kVA_WriteCentL7     = 0x005DD130;
constexpr uintptr_t kVA_BufferFill3     = 0x005DFCD0;   // thiscall (RECT*, color) RET 8; honours the clip
constexpr uintptr_t kVA_MapZoomNum      = 0x00691E6C;
constexpr uintptr_t kVA_MapZoomDen      = 0x00691E70;
constexpr uintptr_t kVA_Factions        = 0x0096C9E0;
constexpr int kFactionSize = 0x20CC, kFactionDiplo = 0x18;
constexpr int kColorRed = 0xF9, kColorWhite = 0xFF;      // static system-palette slots (the HP bar uses 0xF9)
const uint32_t kStackDrawReturns[] = { 0x467183, 0x55AAFF, 0x55ACE0, 0x55AE6D };   // MapWin_draw_vehicles, veh_scoot x3

void* g_writeCent = nullptr;
int   g_markOn = kCloakMarkDefault;

// Is `v` (the local player's) a hidden-kind unit that some other living-or-not faction, not a pact brother,
// has marked seen?
bool CloakBlown(const BYTE* v, int own)
{
    if (!HiddenKind(v)) return false;
    if (v[kVehFaction] != own) return ((v[kVehVisibility] >> own) & 1) != 0;   // a foreign cloaked unit WE have detected
    unsigned seen = v[kVehVisibility] & 0xFEu & ~(1u << own);           // natives (bit 0) do not count
    for (int f = 1; f < 8 && seen; ++f)
        if (((seen >> f) & 1) &&
            (*reinterpret_cast<const uint32_t*>(At(kVA_Factions) + own * kFactionSize + kFactionDiplo + f * 4) & 1))
            seen &= ~(1u << f);                                           // pact brothers see everything anyway
    return seen != 0;
}

void __cdecl DrawCloakMark(BYTE* frame)
{
    if (!g_markOn) return;
    const int n = Rd<int>(kVA_VehCount);
    const int off = *reinterpret_cast<int*>(frame - 0x14);
    if (off < 0 || off % kVehSize != 0) return;
    const int veh = off / kVehSize;
    if (veh >= n || !ModernCtlVehOk(veh)) return;                         // veh_fake's scratch slot is >= VehCount in both builds
    const int own = Rd<int>(kVA_CurrentPlayer);
    if (own < 1 || own > 7) return;
    const int x = *reinterpret_cast<int16_t*>(Veh(veh) + kVehX), y = *reinterpret_cast<int16_t*>(Veh(veh) + kVehY);
    const BYTE* sq = MapSq(x, y);
    if (!sq || (*reinterpret_cast<const uint32_t*>(sq + 8) & 1) != 0) return;   // in a base: always known

    bool blown = CloakBlown(Veh(veh), own);
    if (g_debug) {                                                         // AiVisDebug=1: one census line per unit
        static uint32_t said[64]; static int lastOwn = -1;                 // (2048 bits), reset when the viewer changes
        if (lastOwn != own) { memset(said, 0, sizeof said); lastOwn = own; }
        if (veh < 2048 && !((said[veh >> 5] >> (veh & 31)) & 1)) {
            said[veh >> 5] |= 1u << (veh & 31);
            const BYTE* v = Veh(veh);
            if (HiddenKind(v)) {
                char s[200];
                _snprintf_s(s, sizeof s, _TRUNCATE,
                            "[uimod] aivis dbg: mark census veh %d fac %d at (%d,%d) hidden-kind vis=%02X own=%d -> %s\n",
                            veh, v[kVehFaction], x, y, v[kVehVisibility], own, blown ? "BLOWN" : "not blown");
                UimodLog(s);
            }
        }
    }
    if (!blown) {
        const uintptr_t ret = *reinterpret_cast<uintptr_t*>(frame + 4);
        bool wholeStack = false;
        for (uint32_t r : kStackDrawReturns) wholeStack = wholeStack || ret == reinterpret_cast<uintptr_t>(At(r));
        if (!wholeStack) return;                                          // list views: each unit speaks for itself
        int top = veh, guard = 0;
        for (int p = *reinterpret_cast<int16_t*>(Veh(top) + kVehPrev); p >= 0 && p < n && guard++ < 4096;
             p = *reinterpret_cast<int16_t*>(Veh(top) + kVehPrev))
            top = p;
        guard = 0;
        for (int i = top; i >= 0 && i < n && guard++ < 4096 && !blown; i = *reinterpret_cast<int16_t*>(Veh(i) + kVehNext))
            blown = CloakBlown(Veh(i), own);
        if (!blown) return;
    }

    int num = Rd<int>(kVA_MapZoomNum), den = Rd<int>(kVA_MapZoomDen);
    if (num <= 0 || den <= 0) { num = *reinterpret_cast<int*>(frame + 0x18) + 16; den = 16; }
    if (num <= 0 || num > den * 8) return;
    auto rnd = [&](int v, int lo) { const int r = (2 * v * num + den) / (2 * den); return r < lo ? lo : r; };
    // native mark: 5 x 10 = 1 px white stroke around a 3x5 bar, a 1 px gap, a 3x2 dot
    const int t = rnd(1, 1), cw = rnd(3, 1), bar = rnd(5, 2), dot = rnd(2, 1);
    const int w = cw + 2 * t, h = bar + dot + 3 * t;
    const int fx = *reinterpret_cast<int*>(frame + 0x10), fy = *reinterpret_cast<int*>(frame + 0x14);
    const int left = fx + 19 * num / den, top = fy + 1 * num / den;    // straddles the banner's top-right corner

    void* buf = *reinterpret_cast<void**>(frame + 8);
    if (!buf) return;
    using FFill3 = void(__thiscall*)(void*, RECT*, int);
    const FFill3 fill = reinterpret_cast<FFill3>(At(kVA_BufferFill3));
    RECT r;
    r = { left, top, left + w, top + h };                          fill(buf, &r, kColorWhite);
    r = { left + t, top + t, left + t + cw, top + t + bar };       fill(buf, &r, kColorRed);
    r = { left + t, top + 2 * t + bar, left + t + cw, top + 2 * t + bar + dot }; fill(buf, &r, kColorRed);
}

__declspec(naked) void StubVehDrawTail()
{
    __asm {
        push dword ptr [esp + 0xC]            // re-push (str, RECT*, len); ecx = buf is untouched
        push dword ptr [esp + 0xC]
        push dword ptr [esp + 0xC]
        call dword ptr [g_writeCent]
        push eax
        push ebp                              // veh_draw's frame
        call DrawCloakMark
        add  esp, 4
        pop  eax
        ret  0xC
    }
}

// ---- airdrop diversion ----------------------------------------------------------------------------
// BASE-GAME LEAK (user 2026-10-30): an air drop onto a tile whose cloaked stack the dropping faction has never
// detected was refused with #DROPUNIT ("... an area containing other factions' units"), and the refusal itself
// told the player an enemy stood exactly there. Now (the user's design): the unit is DIVERTED to the first free
// neighbouring tile, the hidden stack is revealed to the dropping faction (the same discovery as walking into it)
// and the local player reads "Our unit was diverted by a cloaked defender occupying the drop zone!". With no free
// neighbour the drop fails exactly as before (DROPUNIT, nothing dropped, nothing revealed); a drop onto an already
// REVEALED cloaked unit is untouched. "Free" = a square the unit could share: on the map, terrain its triad can
// stand on, no units of a faction it has no pact with, no base of such a faction (own and pact squares are fine).
// The neighbours are walked in the engine's own direction order (DirDX/DirDY), so every peer of a network game
// picks the same tile; the group is a Preferences row, "Air Drops Divert Around Unseen Defenders" ([UIMod]
// AirdropDiversion, default on; AirdropActive(): the local value in single player, the HOST's in a network game,
// since action_airdrop runs on every peer). The engine's action_airdrop 0x4CC360 (cdecl veh, tx, ty, flags) is
// entered through one detour that covers the player's drop, the AI's and the network path; under Thinker that
// entry is Thinker's write_jump, which the detour chains instead. The diverted drop runs the original with the
// real flags: its own refusals (range, air defences, ZOC) show their one message and reveal nothing; the AI's
// drops (engine and Thinker) take the same path without a popup.
// SCOPE (engine bytes, 0x4CC5CF..0x4CC5E3): action_airdrop applies zone of control ONLY to a non-combat unit
// (weapon offense 0: colony pods, formers, probes, crawlers -> #NONCOMDROP), and the engine's zoc_sea 0x5C8BA0 lets
// an unseen non-pact unit exert it in single player unless the unit carries VFLAG_INVISIBLE. Every neighbour of
// the target is adjacent to the hidden stack, so a NON-COMBAT drop onto it is refused on all eight squares and
// falls through to the base game's #DROPUNIT (no regression: the same stack already stops the unit's moves). The
// diversion is in practice a COMBAT-unit feature, which is how the user describes it (2026-10-30).
constexpr uintptr_t kVA_ActionAirdrop = 0x004CC360;
constexpr uintptr_t kVA_Popp          = 0x0048C0A0;   // popp(filename, label, a3, pcx, fn): a script popup with a picture
constexpr uintptr_t kVA_BaseAt        = 0x004E3A50;   // base_at(x, y): base id or -1
constexpr uintptr_t kVA_DropRange     = 0x00500320;   // drop_range(faction): the engine's airdrop limit (orbital insertion /
                                                      // Space Elevator -> unlimited, else Rules->max_airdrop_rng_wo_orbital_insert)
constexpr uintptr_t kVA_AirdropRule   = 0x00949740;   // Rules->max_airdrop_rng_wo_orbital_insert, the finite limit drop_range reads
const BYTE kAirdropPrologue[6] = { 0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x1C };   // push ebp ; mov ebp,esp ; sub esp,0x1C
constexpr uintptr_t kVA_GameState     = 0x009A64C0;
constexpr uint32_t  kStateOmniscient  = 0x80;         // STATE_OMNISCIENT_VIEW: the player sees every unit
const char kAirdropFile[]     = "uimod_airdrop";
const char kAirdropLabel[]    = "DROPDIVERTED";
const char kAirdropText[]     = "Our unit was diverted by a cloaked defender occupying the drop zone!";
const char kAirdropLabelFog[] = "DROPDIVERTEDFOG";    // the defender was merely out of sight (fog of war)
const char kAirdropTextFog[]  = "Our unit was diverted by an unseen defender occupying the drop zone!";
using FAirdrop = int(__cdecl*)(int veh, int tx, int ty, int flags);
using FPopp    = int(__cdecl*)(const char* file, const char* label, int a3, const char* pcx, void* fn);
using FBaseAt  = int(__cdecl*)(int x, int y);
FAirdrop g_airdropNext = nullptr;

bool HasPact(int f, int other)   // Factions[f].diplo_status[other] & DIPLO_PACT
{
    return f >= 0 && f < 8 && other >= 0 && other < 8 &&
           (*reinterpret_cast<const uint32_t*>(At(kVA_Factions) + f * kFactionSize + kFactionDiplo + other * 4) & 1) != 0;
}

// The engine's tile distance, as action_airdrop computes it (0x4CC388..): (|dx| + |dy|) >> 1, |dx| folded past
// MapHalfX on a round map.
int MapRange(int x1, int y1, int x2, int y2)
{
    int dx = x1 > x2 ? x1 - x2 : x2 - x1;
    const int dy = y1 > y2 ? y1 - y2 : y2 - y1;
    if ((Rd<uint32_t>(kVA_MapToggleFlat) & 1) == 0 && dx > Rd<int>(kVA_MapHalfX)) dx = Rd<int>(kVA_MapAreaX) - dx;
    return (dx + dy) >> 1;
}

// The diverted square is adjacent to a target that was within range, so it may be ONE tile past the limit; the
// engine must not refuse it for that (user 2026-10-30). drop_range's finite limit is raised by one around the call
// (its unlimited branches -- orbital insertion, the Space Elevator -- are unaffected) and put back exactly. The
// executing call runs modal UI (capture, combat and goody popups) and pumps the network, so the restore is a
// destructor: it runs on any C++ unwind out of that call, not only on the normal return.
struct RangeWaiver
{
    int* rule; int old;
    RangeWaiver() : rule(reinterpret_cast<int*>(At(kVA_AirdropRule))), old(*rule) { *rule = old + 1; }
    ~RangeWaiver() { *rule = old; }
};
int AirdropWithRangeWaiver(int veh, int x, int y, int flags)
{
    RangeWaiver w;
    return g_airdropNext(veh, x, y, flags);
}

// Every unit of the stack is one the faction has NO current sight of: its sight bit (Veh +0x27, maintained by the
// engine's spot_all on every move and masked back to the tile's observers) is clear on each, and none is the
// faction's own. This is the per-unit truth of "could not see"; the tile's own byte (MAP +4) is only "ever
// explored" (set-only, copied by map trades) and would miss a tile seen once and now out of sight.
bool UnseenStack(int id, int f)
{
    const int n = Rd<int>(kVA_VehCount);
    if (id < 0 || id >= n) return false;
    int top = id, guard = 0;                      // to the stack top first, as HiddenStack does (veh_at: ANY unit on the tile)
    for (int p = *reinterpret_cast<int16_t*>(Veh(top) + kVehPrev); p >= 0 && p < n && guard++ < 4096;
         p = *reinterpret_cast<int16_t*>(Veh(p) + kVehPrev))
        top = p;
    int count = 0;
    guard = 0;
    for (int i = top; i >= 0 && i < n && guard++ < 4096; i = *reinterpret_cast<int16_t*>(Veh(i) + kVehNext)) {
        const BYTE* v = Veh(i);
        if (v[kVehFaction] == f || ((v[kVehVisibility] >> f) & 1)) return false;
        ++count;
    }
    return count > 0;
}

int WrapMapX(int x)
{
    if ((Rd<uint32_t>(kVA_MapToggleFlat) & 1) == 0) {
        const int w = Rd<int>(kVA_MapAreaX);
        if (x < 0) x += w; else if (x >= w) x -= w;
    }
    return x;
}

// A square the dropping unit could share (see the header). The engine refuses every drop into the sea (DROPSEA),
// whatever the unit, so ocean is never free.
bool DropTileFree(int f, int x, int y)
{
    const BYTE* sq = MapSq(x, y);
    if (!sq) return false;
    if ((sq[0] & 0xE0) < 0x60) return false;
    const int owner = reinterpret_cast<FTile2>(At(kVA_VehWho))(x, y);
    if (owner >= 0 && owner != f && !HasPact(f, owner)) return false;
    const int base = reinterpret_cast<FBaseAt>(At(kVA_BaseAt))(x, y);
    if (base >= 0) {
        const int bf = At(kVA_Bases)[base * kBaseSize + kBaseFaction];
        if (bf != f && !HasPact(f, bf)) return false;
    }
    return true;
}

bool BuildAirdropFile();
bool g_airdropFileOk = false;

// flags: bit 0 = interactive (the engine's refusals pop their message), bit 1 = execute (without it the call is a
// CHECK: every refusal still applies, 1 = allowed, nothing moves -- in a network game the local peer checks with
// flags 1, then every peer executes the broadcast with flags 2; single player passes 3). The wrapper therefore
// probes each candidate with flags & ~3 (silent, no execution), runs the first allowed one with the real flags,
// and reveals the stack ONLY on an executing call, so every peer reveals it at the same moment. No diversion unless
// the TARGET itself would have passed the engine's own pre-unit refusals (range, then sea, then units): the target
// must be land and within drop_range of the unit, so an out-of-range or ocean square with a hidden stack still
// says "out of range" / "sea" and reveals nothing. The diverted square is then never refused for range (one tile
// past the limit is allowed: AirdropWithRangeWaiver); a square the engine refuses for any other reason (air
// defences, a zone of control for a non-combat unit, ...) is skipped silently and the next one is tried.
// EXTENDED (user 2026-10-30) to any defender the dropping faction could not SEE: a human faction's drop onto a
// stack none of whose units it currently sees (fog of war; UnseenStack, the omniscient view excepted) is diverted
// the same way, with its own wording; the discovery then comes from the dropped unit's normal vision plus the
// same spot_stack. AI factions keep the cloaked rule only: they have no fog of war in the base game, so extending
// it would turn their refused drops into successful ones.
// ACCEPTED NETWORK RESIDUAL (audit 2026-10-30): the sight bits are kept in step by the replayed moves and the
// engine's synch_bit traffic, but a peer whose copy still differs at the instant of the flags-2 execute runs the
// original (#DROPUNIT, nothing dropped) while the actor's unit has moved -- a desync the base game's own
// visibility traffic can already produce. Noted, not guarded.
int __cdecl WrapActionAirdrop(int veh, int tx, int ty, int flags)
{
    if (AirdropActive() && veh >= 0 && veh < Rd<int>(kVA_VehCount)) {
        const int f = VehFaction(veh);
        const BYTE* tsq = MapSq(tx, ty);
        const int tgt = reinterpret_cast<FTile2>(At(kVA_VehAt))(tx, ty);
        const int owner = reinterpret_cast<FTile2>(At(kVA_VehWho))(tx, ty);
        const bool blocked = owner >= 0 && owner != f && !HasPact(f, owner);         // the engine's DROPUNIT condition
        const bool cloaked = tgt >= 0 && HiddenStack(tgt, f);
        const bool fogged  = f > 0 && f < 8 && IsHuman(f) && tgt >= 0 && UnseenStack(tgt, f) &&
                             (Rd<uint32_t>(kVA_GameState) & kStateOmniscient) == 0;
        if (f > 0 && f < 8 && tsq && (tsq[0] & 0xE0) >= 0x60 && blocked && (cloaked || fogged)) {
            const int vx = *reinterpret_cast<const int16_t*>(Veh(veh) + kVehX);
            const int vy = *reinterpret_cast<const int16_t*>(Veh(veh) + kVehY);
            const bool inRange = MapRange(vx, vy, tx, ty) <= reinterpret_cast<FVeh1>(At(kVA_DropRange))(f);
            for (int d = 0; inRange && d < 8; ++d) {
                const int ax = WrapMapX(tx + Rd<int>(kVA_DirDX + d * 4));
                const int ay = ty + Rd<int>(kVA_DirDY + d * 4);
                if (!DropTileFree(f, ax, ay)) continue;
                if (AirdropWithRangeWaiver(veh, ax, ay, flags & ~3) == 0) continue;   // silent probe: the engine's own rules
                const int r = AirdropWithRangeWaiver(veh, ax, ay, flags);
                if (r != 0 && (flags & 2)) {
                    const int now = reinterpret_cast<FTile2>(At(kVA_VehAt))(tx, ty);   // re-resolved: the drop may have killed units
                    if (now >= 0 && VehFaction(now) != f) reinterpret_cast<FSpot>(At(kVA_SpotStack))(now, f);
                }
                // the popup on the EXECUTING call (single player passes 3; a network game executes with 2 after its
                // check with 1, and a peer move in between could change the square) -- the acting player's machine only
                if (r != 0 && (flags & 2) && f == Rd<int>(kVA_CurrentPlayer)) {
                    if (!g_airdropFileOk) g_airdropFileOk = BuildAirdropFile();
                    if (g_airdropFileOk) {
                        const bool alien = (At(kVA_MFactionFlags)[f * kMFactionSize] & 0x80) != 0;
                        reinterpret_cast<FPopp>(At(kVA_Popp))(kAirdropFile, cloaked ? kAirdropLabel : kAirdropLabelFog, 0,
                                                              alien ? "al_drop_sm.pcx" : "airdp_sm.pcx", nullptr);
                    }
                }
                return r;
            }
        }
    }
    return g_airdropNext(veh, tx, ty, flags);
}

// uimod_airdrop.txt: the one popup label, in the script-file format popp() reads.
bool BuildAirdropFile()
{
    char path[MAX_PATH];
    FILE* fp = nullptr;
    if (!GameFilePath("uimod_airdrop.txt", path, sizeof path) || fopen_s(&fp, path, "wb") != 0 || !fp) return false;
    char block[768];
    _snprintf_s(block, sizeof block, _TRUNCATE,
                "; generated by uimod.dll (Longevity Mod) -- rewritten at every start, safe to delete\r\n\r\n"
                "#%s\r\n#xs 440\r\n#caption Operations Director\r\n%s\r\n\r\n"
                "#%s\r\n#xs 440\r\n#caption Operations Director\r\n%s\r\n\r\n",
                kAirdropLabel, kAirdropText, kAirdropLabelFog, kAirdropTextFog);
    const size_t n = strlen(block);
    const bool ok = fwrite(block, 1, n, fp) == n;
    fclose(fp);
    return ok;
}

// ---- installation ---------------------------------------------------------------------------------

bool IsCallTo(uintptr_t site, uintptr_t target)
{
    const BYTE* p = At(site);
    if (p[0] != 0xE8) return false;
    int32_t rel; memcpy(&rel, p + 1, 4);
    return reinterpret_cast<uintptr_t>(p) + 5 + rel == reinterpret_cast<uintptr_t>(At(target));
}

template <size_t N> bool CheckSites(const uint32_t (&sites)[N], uintptr_t target)
{
    for (uint32_t s : sites)
        if (!IsCallTo(s, target)) return false;
    return true;
}

// Under Thinker two core hosts are Thinker's by design: enemy_veh's enemy_move call (0x579362) is its write_call to
// mod_enemy_move, and order_veh's entry is its write_jump. Both must then point INTO thinker.dll (anything else is a
// third patch); thinkeraivis.cpp takes them over there.
bool InThinker(uintptr_t a)
{
    uintptr_t lo, hi;
    return ThinkerRange(&lo, &hi) && a >= lo && a < hi;
}

bool TransfersIntoThinker(uintptr_t site, BYTE opcode)   // E8 call / E9 jmp with a rel32 into thinker.dll
{
    const BYTE* p = At(site);
    if (p[0] != opcode) return false;
    int32_t rel; memcpy(&rel, p + 1, 4);
    return InThinker(reinterpret_cast<uintptr_t>(p) + 5 + rel);
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

template <size_t N> void RetargetAll(const uint32_t (&sites)[N], void* fn)
{
    for (uint32_t s : sites) Retarget(s, fn);
}

// Both detoured entries open with the same position-independent 9 bytes:
//   55 / 8B EC / 64 A1 00 00 00 00   push ebp ; mov ebp,esp ; mov eax,fs:[0]
const BYTE kSehPrologue[9] = { 0x55, 0x8B, 0xEC, 0x64, 0xA1, 0x00, 0x00, 0x00, 0x00 };

bool HasSehPrologue(uintptr_t va) { return memcmp(At(va), kSehPrologue, sizeof kSehPrologue) == 0; }

// Entry detour: trampoline = the 9 prologue bytes + jmp back; entry = jmp hook (+4 int3 pad).
void* DetourEntry(uintptr_t va, void* hook)
{
    BYTE* fn = At(va);
    BYTE* tramp = static_cast<BYTE*>(VirtualAlloc(nullptr, 32, MEM_COMMIT | MEM_RESERVE,
                                                  PAGE_EXECUTE_READWRITE));
    if (!tramp) return nullptr;
    memcpy(tramp, kSehPrologue, sizeof kSehPrologue);
    tramp[9] = 0xE9;
    const int32_t back = static_cast<int32_t>((fn + 9) - (tramp + 9 + 5));
    memcpy(tramp + 10, &back, 4);

    DWORD old;
    VirtualProtect(fn, 9, PAGE_EXECUTE_READWRITE, &old);
    fn[0] = 0xE9;
    const int32_t fwd = static_cast<int32_t>(static_cast<BYTE*>(hook) - (fn + 5));
    memcpy(fn + 1, &fwd, 4);
    memset(fn + 5, 0xCC, 4);
    VirtualProtect(fn, 9, old, &old);
    FlushInstructionCache(GetCurrentProcess(), fn, 9);
    return tramp;
}

bool WriteCode(BYTE* p, const void* bytes, size_t n)
{
    DWORD old;
    if (!VirtualProtect(p, n, PAGE_EXECUTE_READWRITE, &old)) return false;
    memcpy(p, bytes, n);
    VirtualProtect(p, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, n);
    return true;
}

// Entry detour over `n` position-independent prologue bytes (checked by the caller): trampoline = those bytes +
// jmp back; entry = jmp hook, the rest of the prologue nop-filled.
void* DetourEntryBytes(uintptr_t va, size_t n, void* hook)
{
    BYTE* fn = At(va);
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

// 6-byte site -> `jmp stub ; nop`.
void DetourSite6(uintptr_t va, void* stub)
{
    BYTE* p = At(va);
    DWORD old;
    VirtualProtect(p, 6, PAGE_EXECUTE_READWRITE, &old);
    p[0] = 0xE9;
    const int32_t rel = static_cast<int32_t>(static_cast<BYTE*>(stub) - (p + 5));
    memcpy(p + 1, &rel, 4);
    p[5] = 0x90;
    VirtualProtect(p, 6, old, &old);
    FlushInstructionCache(GetCurrentProcess(), p, 6);
}

// ---- zone of control: the hidden-unit exemption (THE RULE, user 2026-10-30) --------------------------------------
// zoc_any / zoc_veh / zoc_sea decide whether faction X faces a zone of control at (x,y) from the eight neighbours.
// zoc_sea tests each unit of a neighbour stack: X's sight bit, else (single player only) any unit without
// VFLAG_INVISIBLE exerts; zoc_any / zoc_veh test only the tile's owner nibble, so even in multiplayer a stack X has
// never seen exerts. A human player's boxed-in unit is refused and SHOWN the blockers (order_veh reveals them); an
// AI's is refused silently and re-plans the same step until its iteration cap (probe 2026-10-30).
// THE RULE: a HUMAN faction's unit that is hidden-kind (Cloaking Device, Deep Pressure Hull, scenario-invisible) and
// not yet revealed to X exerts no zone of control on X -- X human or AI, natives included; once X has seen it, it
// exerts as before. Each primitive is entry-detoured: the ORIGINAL answers first, and only a nonzero answer with the
// setting on is recomputed by the ports below, which repeat the original's tests and add the exemption -- so they can
// turn a zone of control into none, never the reverse, and with the setting off the engine's bytes decide alone.
// The Thinker half detours Thinker's own ports (path.cpp mod_zoc_any / _veh / _sea) onto the same adjustment.
using FZoc = int(__cdecl*)(int x, int y, int f);
FZoc g_zocAnyTramp = nullptr, g_zocVehTramp = nullptr, g_zocSeaTramp = nullptr;
bool g_zocOk = false;

inline bool PactWith(int f, int g)
{
    return (*reinterpret_cast<const uint32_t*>(At(kVA_Factions) + f * kFactionSize + kFactionDiplo + g * 4) & 1) != 0;   // DIPLO_PACT
}
// the unit exerts no zone of control on f
bool ZocExempt(const BYTE* v, int f)
{
    return HiddenKind(v) && ((v[kVehVisibility] >> f) & 1) == 0 && IsHuman(v[kVehFaction]);
}
// every unit standing on (x,y) is exempt for f. Never on a base tile (a base is in plain view, and the stack rule
// never hides a base's garrison -- all three ports agree, audit 2026-10-30); never when the engine's veh_at finds
// nothing (the caller saw the tile's unit bit, so the engine's own answer stands then); never on a broken stack link.
bool StackAllExempt(int x, int y, int f, const BYTE* sq)
{
    if ((*reinterpret_cast<const uint32_t*>(sq + 8) & 1) != 0) return false;
    const int n = Rd<int>(kVA_VehCount);
    int k = reinterpret_cast<FTile2>(At(kVA_VehAt))(x, y);
    if (k < 0) return false;
    int guard = 0;
    for (; k >= 0; k = *reinterpret_cast<int16_t*>(Veh(k) + kVehNext)) {
        if (k >= n || guard++ >= 4096) return false;
        if (!ZocExempt(Veh(k), f)) return false;
    }
    return true;
}
// the neighbour (x,y)+dir with the engine's x wrap; null when off the map
const BYTE* ZocNeighbour(int x, int y, int d, int* nx, int* ny)
{
    int tx = x + Rd<int>(kVA_DirDX + d * 4);
    const int ty = y + Rd<int>(kVA_DirDY + d * 4);
    if ((Rd<uint32_t>(kVA_MapToggleFlat) & 1) == 0) {
        const int w = Rd<int>(kVA_MapAreaX);
        if (tx < 0) tx += w; else if (tx >= w) tx -= w;
    }
    *nx = tx; *ny = ty;
    return MapSq(tx, ty);
}
inline bool ForeignOwner(int owner, int f) { return owner >= 0 && owner < 8 && owner != f && !PactWith(f, owner); }

int ZocAnyRule(int x, int y, int f)      // zoc_any: units or a base on the neighbour; first foreign non-pact owner -> owner+1
{
    for (int d = 0; d < 8; ++d) {
        int nx, ny;
        const BYTE* sq = ZocNeighbour(x, y, d, &nx, &ny);
        if (!sq) continue;
        const uint32_t items = *reinterpret_cast<const uint32_t*>(sq + 8);
        if ((items & 3) == 0) continue;
        const int owner = sq[2] & 0xF;
        if (!ForeignOwner(owner, f)) continue;
        if ((items & 2) != 0 && StackAllExempt(nx, ny, f, sq)) continue;
        return owner + 1;
    }
    return 0;
}
int ZocVehRule(int x, int y, int f)      // zoc_veh: units on the neighbour; the highest foreign non-pact owner+1
{
    int value = 0;
    for (int d = 0; d < 8; ++d) {
        int nx, ny;
        const BYTE* sq = ZocNeighbour(x, y, d, &nx, &ny);
        if (!sq) continue;
        if ((*reinterpret_cast<const uint32_t*>(sq + 8) & 2) == 0) continue;
        const int owner = sq[2] & 0xF;
        if (!ForeignOwner(owner, f)) continue;
        if (StackAllExempt(nx, ny, f, sq)) continue;
        if (owner + 1 > value) value = owner + 1;
    }
    return value;
}
int ZocSeaRule(int x, int y, int f)      // zoc_sea: neighbours on the same land/sea; per unit: seen, or (single player) not invisible -- and not exempt
{
    const BYTE* here = MapSq(x, y);
    if (!here) return 0;
    const bool ocean = (here[0] & 0xE0) < 0x60;
    const bool mp = Rd<int>(kVA_MultiplayerActive) != 0;
    const int n = Rd<int>(kVA_VehCount);
    for (int d = 0; d < 8; ++d) {
        int nx, ny;
        const BYTE* sq = ZocNeighbour(x, y, d, &nx, &ny);
        if (!sq) continue;
        const uint32_t items = *reinterpret_cast<const uint32_t*>(sq + 8);
        if ((items & 2) == 0) continue;
        const int owner = sq[2] & 0xF;
        if (owner >= 8 || owner == f) continue;
        if (((sq[0] & 0xE0) < 0x60) != ocean) continue;
        if (PactWith(f, owner)) continue;
        const bool baseTile = (items & 1) != 0;          // a base's garrison always exerts (see StackAllExempt)
        int k = reinterpret_cast<FTile2>(At(kVA_VehAt))(nx, ny);
        int guard = 0;
        for (; k >= 0 && k < n && guard++ < 4096; k = *reinterpret_cast<int16_t*>(Veh(k) + kVehNext)) {
            const BYTE* v = Veh(k);
            if (v[kVehFaction] == f) continue;
            if ((v[kVehVisibility] >> f) & 1) return owner + 1;
            if (!mp && (*reinterpret_cast<const uint16_t*>(v + kVehFlags) & kVflagInvisible) == 0 && (baseTile || !ZocExempt(v, f))) return owner + 1;
        }
    }
    return 0;
}
// `r` = the original's answer; recomputed only when it says ZOC and the setting is on
int ZocAdjust(int kind, int r, int x, int y, int f)
{
    if (r == 0 || f < 0 || f >= 8 || !Enabled()) return r;
    switch (kind) {
    case 0:  return ZocAnyRule(x, y, f);
    case 1:  return ZocVehRule(x, y, f);
    default: return ZocSeaRule(x, y, f);
    }
}
int __cdecl HookZocAny(int x, int y, int f) { return ZocAdjust(0, g_zocAnyTramp(x, y, f), x, y, f); }
int __cdecl HookZocVeh(int x, int y, int f) { return ZocAdjust(1, g_zocVehTramp(x, y, f), x, y, f); }
int __cdecl HookZocSea(int x, int y, int f) { return ZocAdjust(2, g_zocSeaTramp(x, y, f), x, y, f); }

} // namespace

int  AiVisZocAdjust(int kind, int r, int x, int y, int f) { return ZocAdjust(kind, r, x, y, f); }

int AiVisGetLocal() { return g_local; }

int  AiVisGetCargoOne() { return g_cargoOne; }
void AiVisSetCargoOne(int on) { g_cargoOne = on ? 1 : 0; }
void AiVisSaveCargoOne()
{
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "CloakedTransportHidesCargo", g_cargoOne ? "1" : "0", ini);
}

void AiVisSetLocal(int on) { g_local = on ? 1 : 0; }

int  AiVisGetAirdrop() { return g_airdropOn; }
void AiVisSetAirdrop(int on) { g_airdropOn = on ? 1 : 0; }
void AiVisSaveAirdrop()
{
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "AirdropDiversion", g_airdropOn ? "1" : "0", ini);
}

int  AiVisGetMark() { return g_markOn; }
void AiVisSetMark(int on) { g_markOn = on ? 1 : 0; }
void AiVisSaveMark()
{
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "CloakAlertIcon", g_markOn ? "1" : "0", ini);
}

void AiVisSaveLocal()
{
    char ini[MAX_PATH]; IniPath(ini, sizeof ini);
    WritePrivateProfileStringA("UIMod", "AiRespectsCloak", g_local ? "1" : "0", ini);
}

void InstallAiVisibility()
{
    g_vehs = ModernCtlVehs();
    if (g_vehs != At(kVA_Vehs)) {
        char buf[160];
        _snprintf_s(buf, sizeof buf, _TRUNCATE, "[uimod] aivis: unit array relocated to 0x%08X (Thinker) -> every unit read follows it\n",
                    static_cast<unsigned>(reinterpret_cast<uintptr_t>(g_vehs)));
        UimodLog(buf);
    }
    {
        char ini[MAX_PATH]; IniPath(ini, sizeof ini);
        g_local = GetPrivateProfileIntA("UIMod", "AiRespectsCloak", kAiVisDefault, ini) != 0 ? 1 : 0;
        g_debug = GetPrivateProfileIntA("UIMod", "AiVisDebug", 0, ini) != 0;
        g_cargoOne = GetPrivateProfileIntA("UIMod", "CloakedTransportHidesCargo", kCargoOneDefault, ini) != 0 ? 1 : 0;
        g_markOn = GetPrivateProfileIntA("UIMod", "CloakAlertIcon", kCloakMarkDefault, ini) != 0 ? 1 : 0;
        if (!g_local) g_cargoOne = g_markOn = 0;                  // nested under AiRespectsCloak (prefs page)
        g_airdropOn = GetPrivateProfileIntA("UIMod", "AirdropDiversion", kAirdropDivertDefault, ini) != 0 ? 1 : 0;   // top-level row
    }

    // cargo group: independent of the AI filter (it changes the engine's spotting, for every observer)
    if (IsCallTo(kVA_SpotAllCountSite, kVA_StackCheck) && CheckSites(kSitesSpotAllStackFix, kVA_StackFix) &&
        CheckSites(kSitesSpotAllWake, kVA_WakeStack)) {
        RetargetAll(kSitesSpotAllWake, &WrapSpotAllWake);
        Retarget(kVA_SpotAllCountSite, &WrapSpotAllStackCount);
        RetargetAll(kSitesSpotAllStackFix, &WrapSpotAllStackFix);
        g_cargoOk = true;
    } else {
        UimodLog("[uimod] aivis: spot_all stack-count byte check FAILED -> cloaked-transport cargo option disabled\n");
    }

    // survey-pod group: one call site in spot_all
    if (IsCallTo(kVA_SpotAllMoverSensorSite, kVA_IsSensor)) {
        Retarget(kVA_SpotAllMoverSensorSite, &WrapSpotAllMoverSensor);
        g_podOk = true;
    } else {
        UimodLog("[uimod] aivis: spot_all sensor-site byte check FAILED -> Survey Pod keeps the engine's 9-tile pattern\n");
    }

    // flag-mark group: one call site inside veh_draw (identical bytes on the vanilla and PRACX exes)
    if (IsCallTo(kVA_VehDrawTailSite, kVA_WriteCentL7)) {
        g_writeCent = At(kVA_WriteCentL7);
        Retarget(kVA_VehDrawTailSite, &StubVehDrawTail);
        UimodLog("[uimod] aivis: spotted-cloak flag mark installed\n");
    } else {
        UimodLog("[uimod] aivis: veh_draw tail byte check FAILED -> no spotted-cloak flag mark\n");
    }

    // core group: the filter's call sites + both enemy_move callers + order_veh's entry. Under Thinker the second
    // enemy_move caller and order_veh's entry are Thinker's (see TransfersIntoThinker): the engine's enemy_move is then
    // entered through Thinker's own function pointer and its order_veh never runs, so thinkeraivis.cpp wraps the
    // pointer and detours Thinker's order_veh instead; here only Console_veh_turn's call is re-pointed.
    const bool thinker = ThinkerLoaded();
    const bool hostsOk = thinker
        ? (IsCallTo(kSitesEnemyMove[0], kVA_EnemyMove) && TransfersIntoThinker(kSitesEnemyMove[1], 0xE8) &&
           TransfersIntoThinker(kVA_OrderVeh, 0xE9))
        : (CheckSites(kSitesEnemyMove, kVA_EnemyMove) && HasSehPrologue(kVA_OrderVeh));
    if (!CheckSites(kSitesVehAt, kVA_VehAt) || !CheckSites(kSitesVehWho, kVA_VehWho) ||
        !CheckSites(kSitesAnythingAt, kVA_AnythingAt) || !CheckSites(kSitesStackCheck, kVA_StackCheck) || !hostsOk) {
        UimodLog("[uimod] aivis: core byte check FAILED (foreign patch on the AI move code?) -> "
                 "AI perception filter disabled\n");
        return;
    }
    if (!thinker) {
        g_orderVehTramp = reinterpret_cast<FOrder>(DetourEntry(kVA_OrderVeh, &HookOrderVeh));
        if (!g_orderVehTramp) {
            UimodLog("[uimod] aivis: trampoline alloc failed -> AI perception filter disabled\n");
            return;
        }
    }
    RetargetAll(kSitesVehAt, &WrapVehAt);
    RetargetAll(kSitesVehWho, &WrapVehWho);
    RetargetAll(kSitesAnythingAt, &WrapAnythingAt);
    RetargetAll(kSitesStackCheck, &WrapStackCheck);
    if (thinker) Retarget(kSitesEnemyMove[0], &WrapEnemyMove);
    else RetargetAll(kSitesEnemyMove, &WrapEnemyMove);
    g_coreOk = true;

    // debug tracer: spot_all's call sites (AiVisDebug=1 only; never installed otherwise)
    if (g_debug) {
        if (CheckSites(kSitesSpotAll, kVA_SpotAll)) {
            RetargetAll(kSitesSpotAll, &WrapSpotAllDbg);
            UimodLog("[uimod] aivis dbg: spot_all tracer armed\n");
        } else {
            UimodLog("[uimod] aivis dbg: spot_all site check FAILED -> no spotting trace\n");
        }
    }

    // path group: the pathfinder's inline occupied-tile tests (see header, half 3)
    static const BYTE pfExpect[11] = { 0xF6, 0x40, 0x08, 0x02, 0x75, 0x05, 0x83, 0xCB, 0xFF, 0xEB, 0x3D };
    static const BYTE pmExpect[8]  = { 0x8A, 0x44, 0x90, 0x08, 0xA8, 0x03, 0x74, 0x39 };
    bool pathOk = false;
    if (memcmp(At(kVA_PathFindOcc1), pfExpect, sizeof pfExpect) == 0 &&
        memcmp(At(kVA_PathFindOcc2), pfExpect, sizeof pfExpect) == 0 &&
        memcmp(At(kVA_PathMoveOcc), pmExpect, sizeof pmExpect) == 0) {
        g_pf1Empty = At(kVA_PathFindOcc1 + 6);  g_pf1Occupied = At(kVA_PathFindOcc1 + 11);
        g_pf2Empty = At(kVA_PathFindOcc2 + 6);  g_pf2Occupied = At(kVA_PathFindOcc2 + 11);
        g_pmResume = At(kVA_PathMoveOcc + 6);
        DetourSite6(kVA_PathFindOcc1, &StubPathFind1);
        DetourSite6(kVA_PathFindOcc2, &StubPathFind2);
        DetourSite6(kVA_PathMoveOcc, &StubPathMove);
        pathOk = true;
    } else {
        UimodLog("[uimod] aivis: pathfinder byte check FAILED -> AI routes will still avoid unseen stacks\n");
    }

    // diplomacy group: territory()'s intruder count + do_withdrawal's teleport
    bool diploOk = false;
    if (IsCallTo(kVA_TerritorySite, kVA_WhoseTerritory) && IsCallTo(kVA_WithdrawSite, kVA_BaseFind2)) {
        Retarget(kVA_TerritorySite, &WrapTerritoryWhose);
        Retarget(kVA_WithdrawSite, &WrapWithdrawBaseFind);
        diploOk = true;
        // the human's "also withdraw my undetected troops" reply rides on the group above
        if (IsCallTo(kVA_GetoutPopSite, kVA_XPops11) && IsCallTo(kVA_GetoutWithdrawSite, kVA_DoWithdrawal) &&
            IsCallTo(kVA_GetoutMutualSite, kVA_DoWithdrawal)) {
            Retarget(kVA_GetoutMutualSite, &WrapGetoutWithdraw);
            Retarget(kVA_GetoutPopSite, &StubGetoutPopup);
            Retarget(kVA_GetoutWithdrawSite, &WrapGetoutWithdraw);
            g_getoutOk = true;
        } else {
            UimodLog("[uimod] aivis: GETOUT byte check FAILED -> no \"withdraw undetected troops\" reply\n");
        }
    } else {
        UimodLog("[uimod] aivis: diplomacy byte check FAILED -> withdrawal demands still count unseen units\n");
    }

    // airdrop diversion group: the engine's action_airdrop entry (its 6-byte prologue). Under Thinker that entry is
    // Thinker's write_jump AND Thinker's planner calls its own action_airdrop directly, so the Thinker half detours
    // Thinker's function instead (thinkeraivis.cpp -> AiVisAirdropSetNext); nothing is done here then.
    {
        BYTE* e = At(kVA_ActionAirdrop);
        g_airdropFileOk = BuildAirdropFile();                          // retried at popup time if it failed
        if (thinker) {
            UimodLog(TransfersIntoThinker(kVA_ActionAirdrop, 0xE9)
                     ? "[uimod] aivis: airdrop diversion: Thinker replaces action_airdrop -> left to the thinker half (its line says whether Thinker's entry was detoured)\n"
                     : "[uimod] aivis: action_airdrop entry is neither the engine's prologue nor Thinker's jump -> airdrop diversion off\n");
        } else if (memcmp(e, kAirdropPrologue, sizeof kAirdropPrologue) == 0) {
            g_airdropNext = reinterpret_cast<FAirdrop>(DetourEntryBytes(kVA_ActionAirdrop, sizeof kAirdropPrologue, &WrapActionAirdrop));
            g_airdropOk = g_airdropNext != nullptr;
            UimodLog(g_airdropOk ? "[uimod] aivis: airdrop diversion installed (a combat unit dropped onto a stack its faction cannot "
                                   "see -- cloaked and undetected, or out of sight -- lands beside it and reveals it; the Preferences "
                                   "row decides whether it is on)\n"
                                 : "[uimod] aivis: action_airdrop trampoline alloc failed -> airdrop diversion off\n");
        } else {
            UimodLog("[uimod] aivis: action_airdrop entry byte check FAILED -> a drop onto an undetected cloaked unit is "
                     "refused as in the base game\n");
        }
    }

    // zone-of-control group: the three engine primitives, entry-detoured (the originals answer first; see ZocAdjust).
    // Installed under Thinker too: Thinker keeps its own ports for its planner (the Thinker half detours those) but
    // Path_move, base_compute, alien_move and the engine's enemy_move still call these.
    if (memcmp(At(kVA_ZocAny), kZocAnyPrologue, sizeof kZocAnyPrologue) == 0 &&
        memcmp(At(kVA_ZocVeh), kZocVehPrologue, sizeof kZocVehPrologue) == 0 &&
        memcmp(At(kVA_ZocSea), kZocSeaPrologue, sizeof kZocSeaPrologue) == 0) {
        g_zocAnyTramp = reinterpret_cast<FZoc>(DetourEntryBytes(kVA_ZocAny, sizeof kZocAnyPrologue, &HookZocAny));
        if (g_zocAnyTramp) g_zocVehTramp = reinterpret_cast<FZoc>(DetourEntryBytes(kVA_ZocVeh, sizeof kZocVehPrologue, &HookZocVeh));
        if (g_zocVehTramp) g_zocSeaTramp = reinterpret_cast<FZoc>(DetourEntryBytes(kVA_ZocSea, sizeof kZocSeaPrologue, &HookZocSea));
        g_zocOk = g_zocSeaTramp != nullptr;
        UimodLog(g_zocOk ? "[uimod] aivis: zone of control: a human faction's cloaked / submerged unit exerts none on a faction that has "
                           "not yet detected it (zoc_any, zoc_veh, zoc_sea detoured; the setting gates it)\n"
                         : "[uimod] aivis: zoc_* trampoline alloc failed -> undetected hidden units still exert zone of control\n");
    } else {
        UimodLog("[uimod] aivis: zoc_* prologue byte check FAILED -> undetected hidden units still exert zone of control\n");
    }

    // net group: without it the filter stays OFF in network games (peers could not agree)
    if (IsCallTo(kVA_UpkeepSendSite, kVA_MessageData) && HasSehPrologue(kVA_ProcessMessage)) {
        g_procMsgTramp = DetourEntry(kVA_ProcessMessage, &HookProcessMessage);
        if (g_procMsgTramp) {
            Retarget(kVA_UpkeepSendSite, &WrapUpkeepSend);
            g_netOk = true;
        }
    }

    char s[512];                             // audit 2026-10-30: the Thinker-case text is 397 chars; 320 cut the tail
    _snprintf_s(s, sizeof s, _TRUNCATE,
                "[uimod] aivis: AI perception filter installed (128 sites%s; paths %s; diplomacy %s; airdrop diversion %s; "
                "hidden units exert no ZOC until seen %s; net carrier %s; setting %s)\n",
                thinker ? "; bump + Thinker's planner: see the thinker lines" : " + bump",
                pathOk ? "on" : "OFF", diploOk ? "on" : "OFF",
                thinker ? "left to the Thinker half (its own line says whether Thinker's entry was detoured)"
                        : (g_airdropOk ? (g_airdropOn ? "on" : "installed, setting off") : "OFF"),
                g_zocOk ? (thinker ? "on (engine primitives; Thinker's own ports: see the thinker line)" : "on") : "OFF",
                g_netOk ? "on" : "OFF -> disabled in network games", g_local ? "on" : "off");
    UimodLog(s);
}

// ---- for the Thinker half (thinkeraivis.cpp) ----------------------------------------------------------

bool  AiVisCoreInstalled() { return g_coreOk; }
bool  AiVisFactionFiltered(int f) { return Enabled() && IsFilteredAi(f); }
bool  AiVisHiddenStack(int vehId, int f) { return HiddenStack(vehId, f); }
bool  AiVisTileHidden(int x, int y, int f) { return TileHidden(x, y, f); }
int   AiVisBump(int veh, int dir) { return BumpCheck(veh, dir); }
void* AiVisEnemyMoveWrapper() { return reinterpret_cast<void*>(&WrapEnemyMove); }
void* AiVisAirdropWrapper() { return reinterpret_cast<void*>(&WrapActionAirdrop); }
void  AiVisAirdropSetNext(void* next)
{
    g_airdropNext = reinterpret_cast<FAirdrop>(next);
    g_airdropOk = next != nullptr;
}
