// leaderfree.cpp -- an AI probe team "freeing a captured faction leader" reset a living faction (base-game bug).
//
// probe 0x59F120, the AI's choice of probe action at a base with Headquarters (Alien Crossfire, single player): the
// loop at 0x5A29B9..0x5A2A3E walks the target faction's captured-leader slots (Monuments[jailer].data2[i], 0x38 bytes
// each from 0x94CD58) and, for each occupied slot i, reads the prober's treaty with faction i + 1 and records i + 1 in
// [ebp-0x64] as the leader to free ([ebp-0x1C] = 1: "action 8 is possible"). A slot does not belong to faction
// i + 1 -- mon_killed_faction 0x477A60 fills the first free slot -- so the AI freed faction 1 for the first leader
// ever captured, faction 2 for the second, and so on (the loop also reads a 7th "slot" past the six real ones --
// Monument +0x4A8, which nothing is known to write -- and weighs a treaty candidate against the current pick's pact
// read one faction too far, diplo_status[pick + 1]). The free (0x5A3C50) sets that faction's alive bit and calls
// setup_player(f, jailer, 1), which deletes every base and unit faction f owns before landing it again: a living
// faction (whoever holds slot 1, 2, ... -- often the player) was reset to a colony pod, and the real captive stayed in
// jail; it could even be the probing faction itself. The player's own choice (the FREEWHO menu) was always right.
//
// Fix: a 7-byte jump at 0x5A29B9 (the loop's first instruction) to StubPick, which asks leaderfree::Pick (the base
// game's preference rule, applied to the faction each slot really holds and only to one that is still eliminated)
// and writes [ebp-0x64] / [ebp-0x1C] exactly as the loop would have, then leaves every register and loop local as
// the loop leaves them and resumes at 0x5A2A3E. The free itself is unchanged.
//
// Thinker Mod replaces probe() wholesale (write_jump 0x59F120) and carries its own fix of this bug (its fix 27), so
// under Thinker the pick is left alone: this module stands down when thinker.dll is loaded, and again when probe's entry
// is not the base game's prologue (someone else owns the function). Byte-checked (the whole replaced loop), cave-free,
// both exes.
//
// THE MESSAGE (a second base-game flaw, and Thinker's port kept it): after a free the game shows WILLYFREE, "You managed
// to liberate ... gives you all of their technology", when the current player is the rescuer OR the jailer (gate
// 0x5A3CE3). The text only fits the rescuer: the jailer gets no technology and freed nobody. Every sibling probe result
// shown to both sides has a version per side or neutral wording (DECIPHERED0/1, PRODVIRUS0/1, GOTENERGY / TOOKENERGY,
// ASSASSINATED); this one never got a jailer version. Fix: the one call that shows it is redirected, and when the
// watching player is not the rescuer the jailer's text from our own file (uimod_leaderfree.txt, rewritten at every
// start) is shown with the SAME image the game passes for the rescuer. The rescuer's popup is the game's own, untouched.
//   Base game: E8 at 0x5A3D40, rescuer in ebx. Thinker 5.5: its port (probe.cpp) makes the same call through its own
//   function pointer at +0x8122F, rescuer in the frame slot [ebp-0x54D0] (veh_fc_id). That half is pinned to the 5.5
//   build (version.h) and every byte it depends on is checked first; any other Thinker keeps its own popup.

#include "leaderfree.h"
#include "leaderfree_core.h"
#include "thinkercompat.h"   // ThinkerLoaded() / ThinkerRange()
#include "thinkerversion.h"  // ThinkerOnPin(): the startup check's one decision
#include "version.h"         // UIMOD_THINKER_SUPPORTED_*: the Thinker build the message half is measured on

#include <windows.h>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

void UimodLog(const char* msg);

namespace {

constexpr uintptr_t kVA_ProbeEntry = 0x59F120;      // probe(veh_id, base_id, veh_id_2, toggle)
constexpr uintptr_t kVA_PickLoop   = 0x5A29B9;      // mov eax, ebx  (the AI's captured-leader loop starts here)
constexpr uintptr_t kVA_Resume     = 0x5A2A3E;      // mov eax, [ebp-0x1C]  (the loop's only exit)
constexpr uintptr_t kVA_Captured   = 0x94CD58;      // Monuments[0].data2[0][7]; +8 = data2[0][9]
constexpr uintptr_t kVA_Alive      = 0x9A64E9;      // FactionStatus[1]: bit f = faction f alive
constexpr uintptr_t kVA_Diplo      = 0x96C9F8;      // Factions[0].diplo_status[0]

const BYTE kExpectEntry[8] = { 0x55, 0x8B, 0xEC, 0x64, 0xA1, 0x00, 0x00, 0x00 };
// 0x5A29B9 .. 0x5A2A3E: the whole loop this module replaces (setup, body, back edge).
const BYTE kExpectLoop[0x85] = {
    0x8B, 0xC3, 0x33, 0xFF, 0xC1, 0xE0, 0x06, 0x03, 0xC3, 0xC7, 0x45, 0xD8, 0x07, 0x00, 0x00, 0x00,
    0x8D, 0x0C, 0x43, 0x8D, 0x14, 0xCB, 0x8D, 0x0C, 0xB6, 0xC1, 0xE1, 0x04, 0x8D, 0x04, 0x53, 0xC1,
    0xE0, 0x02, 0x2B, 0xCE, 0x8D, 0x90, 0xFC, 0xC9, 0x96, 0x00, 0x8D, 0x0C, 0x8E, 0x8D, 0x0C, 0x8D,
    0x60, 0xCD, 0x94, 0x00, 0x89, 0x4D, 0xD4, 0x8B, 0x4D, 0xD4, 0x83, 0x39, 0x00, 0x74, 0x30, 0x8B,
    0x0A, 0xF6, 0xC1, 0x10, 0x75, 0x29, 0x8B, 0x75, 0x9C, 0xC7, 0x45, 0xE4, 0x01, 0x00, 0x00, 0x00,
    0x83, 0xFE, 0xFF, 0x74, 0x14, 0xF6, 0xC1, 0x01, 0x75, 0x0F, 0xF6, 0xC1, 0x02, 0x74, 0x10, 0xF6,
    0x84, 0xB0, 0xFC, 0xC9, 0x96, 0x00, 0x01, 0x75, 0x06, 0x8D, 0x4F, 0x01, 0x89, 0x4D, 0x9C, 0x8B,
    0x75, 0xD4, 0x8B, 0x4D, 0xD8, 0x47, 0x83, 0xC2, 0x04, 0x83, 0xC6, 0x38, 0x49, 0x89, 0x75, 0xD4,
    0x89, 0x4D, 0xD8, 0x75, 0xB2,
};
constexpr size_t kJumpLen = 7;                      // mov eax,ebx / xor edi,edi / shl eax,6  ->  jmp StubPick; nop; nop

// The message. Base game: the free's gate and its one call.
constexpr uintptr_t kVA_FreedGate    = 0x5A3CE3;    // rescuer (ebx) == current player || jailer == current player
constexpr uintptr_t kVA_FreedPush    = 0x5A3D36;    // push "fac_escape_sm.pcx" ; push "WILLYFREE" ; call NetMsg_pop_2
constexpr uintptr_t kVA_FreedCall    = 0x5A3D40;
constexpr uintptr_t kVA_FreedImage   = 0x690984;
constexpr uintptr_t kVA_FreedLabel   = 0x690998;
constexpr uintptr_t kVA_CurrentPlayer = 0x939284;
constexpr uintptr_t kVA_NetMsgPop2   = 0x50B9E0;    // (label, image) cdecl: the game's own popup
constexpr uintptr_t kVA_Popp         = 0x48C0A0;    // (file, label, 0, image, 0): same popup, from a named script file
constexpr uintptr_t kVA_ParseSays    = 0x625EC0;    // (slot, text, -1, -1)
constexpr uintptr_t kVA_GetNoun      = 0x50B930;    // (faction) -> noun; also sets gender / plural for parse_says
constexpr uintptr_t kVA_GenderDefault = 0x9BBFEC;
constexpr uintptr_t kVA_PluralDefault = 0x9BBFF0;
const BYTE kExpectFreedGate[14] = { 0xA1, 0x84, 0x92, 0x93, 0x00, 0x3B, 0xD8, 0x74, 0x05, 0x39, 0x45, 0xEC, 0x75, 0x57 };
const BYTE kExpectFreedPush[15] = { 0x68, 0x84, 0x09, 0x69, 0x00, 0x68, 0x98, 0x09, 0x69, 0x00, 0xE8, 0x9B, 0x7C, 0xF6, 0xFF };
const char kFreedImageName[] = "fac_escape_sm.pcx";
const char kFreedLabelName[] = "WILLYFREE";

// The homeless probe. The free deletes a probe with no home base (veh_kill, which shifts every later unit down one)
// BEFORE the rest of probe() is done with veh_id, so the code after it decides the fate of whichever unit now sits at
// that index: an unrelated unit is teleported or deleted, and if the probe was the last unit it is the freed faction's
// first colony pod. Every other action that ends in a survival roll leaves the unit to that same code, and so does
// Thinker's port. The branch that guards the early delete becomes unconditional: `jge` -> `jmp`, one byte.
constexpr uintptr_t kVA_HomelessBranch = 0x5A3C74;  // jge +0xC, over: mov ecx,[ebp+8] ; push ecx ; call veh_kill ; add esp,4
const BYTE kExpectHomeless[14] = { 0x7D, 0x0C, 0x8B, 0x4D, 0x08, 0x51, 0xE8, 0x41, 0xCC, 0x01, 0x00, 0x83, 0xC4, 0x04 };

// Where the freed faction lands (base game, single player; the design and the passes: leaderfree_core.h). The free's
// setup_player(f, jailer, 1) searches with 1024 random draws and takes an unjudged 1025th when none passes. The loop
// head 0x5B1688 (reload the draw counter, draw x and y, fix the parity) is entered once per draw and writes only
// [ebp-4] = x, [ebp-8] = y; the body from 0x5B1757 reads no register the head leaves. A 9-byte jump at the head asks
// LandNext: for a rescue it supplies x, y and the draw number the body judges at, and resumes at the body; for anything
// else (game start, escape pods, the scenario editor, multiplayer) it runs the head's two replaced instructions and the
// game's own draw. The rules, the counter's increment and the exit are the game's own code, untouched.
constexpr uintptr_t kVA_LandHead     = 0x5B1688;    // mov edx,[ebp-0x14] ; mov esi,[MapAreaX]  (9 bytes replaced)
constexpr uintptr_t kVA_LandHeadRest = 0x5B1691;    // the head's third instruction
constexpr uintptr_t kVA_LandBody     = 0x5B1757;    // mov dword ptr [ebp-0x30],0x20: first instruction after the draw
constexpr uintptr_t kVA_LandCount    = 0x5B1AE6;    // counter++ ; cmp 0x400 ; the unjudged exit
constexpr uintptr_t kVA_LandCall     = 0x5A3C96;    // probe's free: mov eax,[ebp-0x14] ; push eax ; push esi ; call setup_player
constexpr uintptr_t kVA_LandReturn   = 0x5A3CA0;    // ... and where that call returns: how a rescue is recognised
constexpr uintptr_t kVA_LandEntry    = 0x5B0E00;    // setup_player(faction, jailer, is_probe)
constexpr uintptr_t kVA_MapAreaX     = 0x949870;
constexpr uintptr_t kVA_MapAreaY     = 0x949874;
constexpr uintptr_t kVA_MapHalfX     = 0x68FAF0;
constexpr uintptr_t kVA_MapFlat      = 0x94988C;
constexpr uintptr_t kVA_MapTiles     = 0x94A30C;
constexpr uintptr_t kVA_CurrentTurn  = 0x9A64D4;
constexpr uintptr_t kVA_Multiplayer  = 0x93F660;
constexpr uintptr_t kVA_FactionRules = 0x946F58;    // MFactions[f] rule flags at + f * 0x59C; 0x100 = aquatic
constexpr uintptr_t kVA_GameRand     = 0x64601D;
constexpr size_t kLandJumpLen = 9;
// The whole draw (both rand calls, the parity fix) through the body's first two instructions; then the counter's step.
const BYTE kExpectLandHead[0xD8] = {
    0x8B, 0x55, 0xEC, 0x8B, 0x35, 0x70, 0x98, 0x94, 0x00, 0xBF, 0x00, 0x04, 0x00, 0x00, 0x2B, 0xFA,
    0x8B, 0xC7, 0x0F, 0xAF, 0xC6, 0x99, 0x81, 0xE2, 0xFF, 0x1F, 0x00, 0x00, 0x03, 0xC2, 0xC1, 0xF8,
    0x0D, 0x78, 0x12, 0x3D, 0x0F, 0x27, 0x00, 0x00, 0x7E, 0x07, 0xBB, 0x0F, 0x27, 0x00, 0x00, 0xEB,
    0x06, 0x8B, 0xD8, 0xEB, 0x02, 0x33, 0xDB, 0xF6, 0x05, 0x8C, 0x98, 0x94, 0x00, 0x01, 0x74, 0x05,
    0x8D, 0x04, 0x1B, 0xEB, 0x02, 0x33, 0xC0, 0x2B, 0xF0, 0x8D, 0x46, 0xFF, 0x85, 0xC0, 0x7F, 0x04,
    0x33, 0xD2, 0xEB, 0x08, 0xE8, 0x3C, 0x49, 0x09, 0x00, 0x99, 0xF7, 0xFE, 0x8B, 0x0D, 0x8C, 0x98,
    0x94, 0x00, 0x8B, 0x35, 0x74, 0x98, 0x94, 0x00, 0x80, 0xE1, 0x01, 0x8B, 0xC7, 0xF6, 0xD9, 0x1B,
    0xC9, 0x0F, 0xAF, 0xC6, 0x23, 0xCB, 0x03, 0xCA, 0x99, 0x81, 0xE2, 0xFF, 0x1F, 0x00, 0x00, 0x89,
    0x4D, 0xFC, 0x03, 0xC2, 0xC1, 0xF8, 0x0D, 0x78, 0x12, 0x3D, 0x0F, 0x27, 0x00, 0x00, 0x7E, 0x07,
    0xBF, 0x0F, 0x27, 0x00, 0x00, 0xEB, 0x06, 0x8B, 0xF8, 0xEB, 0x02, 0x33, 0xFF, 0x8D, 0x14, 0x3F,
    0x2B, 0xF2, 0x8D, 0x46, 0xFF, 0x85, 0xC0, 0x7F, 0x04, 0x33, 0xD2, 0xEB, 0x0B, 0xE8, 0xE3, 0x48,
    0x09, 0x00, 0x8B, 0x4D, 0xFC, 0x99, 0xF7, 0xFE, 0x03, 0xD7, 0xF6, 0xC1, 0x01, 0x89, 0x55, 0xF8,
    0x74, 0x04, 0x49, 0x89, 0x4D, 0xFC, 0xF6, 0xC2, 0x01, 0x74, 0x04, 0x41, 0x89, 0x4D, 0xFC, 0xC7,
    0x45, 0xD0, 0x20, 0x00, 0x00, 0x00, 0x33, 0xDB,
};
const BYTE kExpectLandCount[0x26] = {
    0x8B, 0x45, 0xEC, 0x40, 0x3D, 0x00, 0x04, 0x00, 0x00, 0x89, 0x45, 0xEC, 0x7E, 0x18, 0xA0, 0xE8,
    0x64, 0x9A, 0x00, 0x8A, 0x4D, 0xC4, 0x84, 0xC8, 0x0F, 0x84, 0xE0, 0x03, 0x00, 0x00, 0x85, 0xDB,
    0x0F, 0x85, 0xD8, 0x03, 0x00, 0x00,
};
const BYTE kExpectLandCall[10] = { 0x8B, 0x45, 0xEC, 0x50, 0x56, 0xE8, 0x60, 0xD1, 0x00, 0x00 };
const BYTE kExpectLandEntry[12] = { 0x55, 0x8B, 0xEC, 0x81, 0xEC, 0xDC, 0x00, 0x00, 0x00, 0x53, 0x56, 0x57 };

// Thinker 5.5 (offsets into thinker.dll; absolute operands are compared against the DLL's load address).
constexpr uint32_t kThStamp = UIMOD_THINKER_SUPPORTED_STAMP, kThImageSize = UIMOD_THINKER_SUPPORTED_IMAGE_SIZE;
constexpr uint32_t kThCall     = 0x8122F;           // call dword ptr [NetMsg_pop_2]  (6 bytes)
constexpr uint32_t kThPushes   = 0x81220;           // mov [esp+4], image ; mov [esp], label
constexpr uint32_t kThPointer  = 0xE3728;           // .data: FNetMsg_pop_2 NetMsg_pop_2 = 0x50B9E0
constexpr uint32_t kThLabel    = 0xFDE38;
constexpr uint32_t kThImage    = 0xFDE26;
constexpr uint32_t kThSetSlot  = 0x7A0CE;           // mov [ebp-0x54D0], esi  (veh_fc_id, at probe's entry)
constexpr uint32_t kThReadSlot = 0x81007;           // mov edx, [ebp-0x54D0]  (the message's own gate)
const BYTE kExpectThSetSlot[6]  = { 0x89, 0xB5, 0x30, 0xAB, 0xFF, 0xFF };
const BYTE kExpectThReadSlot[6] = { 0x8B, 0x95, 0x30, 0xAB, 0xFF, 0xFF };

// The jailer's message. Lines stay short: the engine copies each physical line into a fixed buffer and joins them.
const char kFreedFile[]  = "uimod_leaderfree";
const char kFreedJailerLabel[] = "WILLYFREE1";
const char kFreedScript[] =
    "; generated by uimod.dll (Longevity Mod) -- rewritten at every start, safe to delete\r\n\r\n"
    "#WILLYFREE1\r\n"
    "#xs 440\r\n"
    "#wave 19\r\n"
    "#caption Operations Director\r\n"
    "A probe team from the $FACTION3 has broken into our Punishment Sphere and\r\n"
    "freed $TITLE0 $NAME1 of the $FACTION2! The $FACTION2 $<2:has:have> pledged\r\n"
    "allegiance to the $FACTION3.\r\n\r\n"
    "# ; This line must remain at end of file\r\n\r\n";

BYTE* g_resume = nullptr;
bool  g_freedTextReady = false;

BYTE* At(uintptr_t va)
{
    return reinterpret_cast<BYTE*>(GetModuleHandleW(nullptr)) + (va - 0x400000);
}

// The leader `prober`'s probe team frees from `jailer`, or -1 (strides and offsets: leaderfree_core.h).
int __cdecl PickFromEngine(int prober, int jailer)
{
    return leaderfree::PickFromTables(At(kVA_Captured), *At(kVA_Alive), At(kVA_Diplo), prober, jailer);
}

// Entered by jmp from 0x5A29B9 with the loop's inputs live: ebx = the probe team's faction, esi = the target base's
// faction (the jailer), ebp = probe's frame. [ebp-0x1C] is 0 and [ebp-0x64] -1 (set before the loop, untouched).
// Leaves every register and the loop's two locals ([ebp-0x28] counter, [ebp-0x2C] slot pointer) at the values the
// base game's loop leaves after its 7 rounds -- the code after it sees no difference but the answer.
__declspec(naked) void StubPick()
{
    __asm {
        pushad
        push esi
        push ebx
        call PickFromEngine
        add  esp, 8
        test eax, eax
        js   none
        mov  dword ptr [ebp - 0x64], eax
        mov  dword ptr [ebp - 0x1C], 1
    none:
        popad
        mov  eax, ebx
        imul eax, eax, 0x20CC
        lea  edx, [eax + 0x96CA18]          // 0x96C9FC + 7 * 4: past the 7th diplo_status the loop read
        imul esi, esi, 0x4F4
        lea  esi, [esi + 0x94CEE8]          // 0x94CD60 + 7 * 0x38: past the 7th slot flag the loop read
        mov  dword ptr [ebp - 0x2C], esi
        mov  dword ptr [ebp - 0x28], 0
        xor  ecx, ecx
        mov  edi, 7
        jmp  dword ptr [g_resume]
    }
}

// Stands in for the game's NetMsg_pop_2(label, image) at the free's one call site. `rescuer` comes from the site.
int __cdecl ShowFreed(const char* label, const char* image, int rescuer)
{
    using FNetMsgPop2 = int(__cdecl*)(const char*, const char*);
    using FPopp       = int(__cdecl*)(const char*, const char*, int, const char*, void*);
    using FParseSays  = int(__cdecl*)(int, const char*, int, int);
    using FGetNoun    = const char*(__cdecl*)(int);
    const int current = *reinterpret_cast<const int*>(At(kVA_CurrentPlayer));
    if (!leaderfree::JailerSeesOwnMessage(rescuer, current, g_freedTextReady))
        return reinterpret_cast<FNetMsgPop2>(At(kVA_NetMsgPop2))(label, image);
    // get_noun leaves the rescuer's gender / plural in the defaults the next parse_says would inherit: put them back.
    int* const gender = reinterpret_cast<int*>(At(kVA_GenderDefault));
    int* const plural = reinterpret_cast<int*>(At(kVA_PluralDefault));
    const int savedGender = *gender, savedPlural = *plural;
    reinterpret_cast<FParseSays>(At(kVA_ParseSays))(3, reinterpret_cast<FGetNoun>(At(kVA_GetNoun))(rescuer), -1, -1);
    *gender = savedGender;
    *plural = savedPlural;
    return reinterpret_cast<FPopp>(At(kVA_Popp))(kFreedFile, kFreedJailerLabel, 0, image, nullptr);
}

// Base game: reached by the retargeted call, so [esp+4] = label, [esp+8] = image; ebx = the rescuer. cdecl: caller cleans.
__declspec(naked) void StubFreedBaseGame()
{
    __asm {
        mov  eax, dword ptr [esp + 8]
        mov  ecx, dword ptr [esp + 4]
        push ebx
        push eax
        push ecx
        call ShowFreed
        add  esp, 12
        ret
    }
}

// Thinker 5.5: same entry state; the rescuer is probe()'s veh_fc_id, in the frame slot [ebp-0x54D0].
__declspec(naked) void StubFreedThinker()
{
    __asm {
        mov  eax, dword ptr [esp + 8]
        mov  ecx, dword ptr [esp + 4]
        push dword ptr [ebp - 0x54D0]
        push eax
        push ecx
        call ShowFreed
        add  esp, 12
        ret
    }
}

// The landing search (the logic and the frame layout: leaderfree_core.h, LandDriver).
BYTE* g_landHeadRest = nullptr;
BYTE* g_landBody = nullptr;
leaderfree::Tile* g_landTiles = nullptr;
leaderfree::LandDriver g_landDriver;
bool g_landMapLogged = false;

template <typename T>
T Game(uintptr_t va)
{
    return *reinterpret_cast<const T*>(At(va));
}

// Called at the loop head, once per draw, with setup_player's ebp. 1 = x, y and the counter are set, resume at the
// body; 0 = run the game's own draw.
int __cdecl LandNext(BYTE* frame)
{
    const leaderfree::LandEnv env{
        static_cast<uint32_t>(reinterpret_cast<uintptr_t>(At(kVA_LandReturn))),
        Game<int>(kVA_Multiplayer) != 0,
        Game<int>(kVA_CurrentTurn),
        leaderfree::LandMap{ Game<int>(kVA_MapAreaX), Game<int>(kVA_MapAreaY), Game<int>(kVA_MapHalfX),
                             (Game<int>(kVA_MapFlat) & 1) != 0, Game<const uint8_t*>(kVA_MapTiles) },
        At(kVA_FactionRules),
    };
    if (!g_landTiles && leaderfree::LandIsRescue(frame, env))
        g_landTiles = static_cast<leaderfree::Tile*>(malloc(leaderfree::kMaxLandTiles * sizeof(leaderfree::Tile)));
    if (!g_landMapLogged && !leaderfree::LandMapUsable(env.map) &&
        *reinterpret_cast<BYTE* const*>(frame + 4) == At(kVA_LandReturn)) {
        g_landMapLogged = true;
        UimodLog("[uimod] leaderfree: this map's size is outside the landing search's limits -> the base game's draws\n");
    }
    using FRand = int(__cdecl*)();
    return g_landDriver.Step(frame, env, g_landTiles, reinterpret_cast<FRand>(At(kVA_GameRand)));
}

// Entered by jmp from 0x5B1688 with setup_player's frame in ebp. Every register is handed on as it came: the body
// reads none of them before writing it, and the head's own code sets its own.
__declspec(naked) void StubLand()
{
    __asm {
        pushad
        push ebp
        call LandNext
        add  esp, 4
        test eax, eax
        popad
        jnz  given
        mov  edx, dword ptr [ebp - 0x14]
        mov  esi, dword ptr ds:[0x949870]
        jmp  dword ptr [g_landHeadRest]
    given:
        jmp  dword ptr [g_landBody]
    }
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

bool BuildFreedScript()
{
    char exe[MAX_PATH], path[MAX_PATH];
    const DWORD n = GetModuleFileNameA(nullptr, exe, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return false;
    char* slash = strrchr(exe, '\\');
    if (!slash) return false;
    slash[1] = 0;
    if (_snprintf_s(path, sizeof path, _TRUNCATE, "%suimod_leaderfree.txt", exe) <= 0) return false;
    FILE* fp = nullptr;
    if (fopen_s(&fp, path, "wb") != 0 || !fp) return false;
    const size_t len = sizeof kFreedScript - 1;
    const bool ok = fwrite(kFreedScript, 1, len, fp) == len;
    return fclose(fp) == 0 && ok;                       // a short disk only shows up here: the text is still in stdio's buffer
}

bool Abs32At(const BYTE* p, const BYTE* target)
{
    uint32_t v;
    memcpy(&v, p, 4);
    return v == static_cast<uint32_t>(reinterpret_cast<uintptr_t>(target));
}

// Base game: retarget the free's one call. The pick is already installed; a failure here only keeps the game's popup.
void InstallFreedMessageBaseGame()
{
    BYTE* call = At(kVA_FreedCall);
    if (memcmp(At(kVA_FreedGate), kExpectFreedGate, sizeof kExpectFreedGate) != 0 ||
        memcmp(At(kVA_FreedPush), kExpectFreedPush, sizeof kExpectFreedPush) != 0 ||
        memcmp(At(kVA_FreedImage), kFreedImageName, sizeof kFreedImageName) != 0 ||
        memcmp(At(kVA_FreedLabel), kFreedLabelName, sizeof kFreedLabelName) != 0) {
        UimodLog("[uimod] leaderfree: unexpected bytes at the free's message -> the jailer keeps the game's popup\n");
        return;
    }
    if (!BuildFreedScript()) {
        UimodLog("[uimod] leaderfree: could not write uimod_leaderfree.txt -> the jailer keeps the game's popup\n");
        return;
    }
    g_freedTextReady = true;
    BYTE e8[5] = { 0xE8 };
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(&StubFreedBaseGame) -
                                             (reinterpret_cast<uintptr_t>(call) + 5));
    memcpy(e8 + 1, &rel, 4);
    if (!WriteCode(call, e8, sizeof e8)) {
        UimodLog("[uimod] leaderfree: VirtualProtect failed -> the jailer keeps the game's popup\n");
        return;
    }
    UimodLog("[uimod] leaderfree: the jailer of a freed leader gets its own message\n");
}

// Base game only: Thinker's probe() has no early delete. A failure here only leaves the base game's behaviour.
void InstallHomelessProbeFix()
{
    BYTE* branch = At(kVA_HomelessBranch);
    if (memcmp(branch, kExpectHomeless, sizeof kExpectHomeless) != 0) {
        UimodLog("[uimod] leaderfree: unexpected bytes at the homeless-probe branch -> left as the base game has it\n");
        return;
    }
    const BYTE jmp = 0xEB;
    if (!WriteCode(branch, &jmp, 1)) {
        UimodLog("[uimod] leaderfree: VirtualProtect failed -> the homeless-probe branch stays as the base game has it\n");
        return;
    }
    UimodLog("[uimod] leaderfree: a homeless probe that frees a leader no longer corrupts another unit\n");
}

// Base game only: Thinker lands the faction with its own search (mod_setup_player), which this never touches. A failure
// here only leaves the base game's draws.
void InstallLandingSearch()
{
    BYTE* head = At(kVA_LandHead);
    if (memcmp(head, kExpectLandHead, sizeof kExpectLandHead) != 0 ||
        memcmp(At(kVA_LandCount), kExpectLandCount, sizeof kExpectLandCount) != 0 ||
        memcmp(At(kVA_LandCall), kExpectLandCall, sizeof kExpectLandCall) != 0 ||
        memcmp(At(kVA_LandEntry), kExpectLandEntry, sizeof kExpectLandEntry) != 0) {
        UimodLog("[uimod] leaderfree: unexpected bytes in setup_player's landing search -> left as the base game has it\n");
        return;
    }
    g_landHeadRest = At(kVA_LandHeadRest);
    g_landBody = At(kVA_LandBody);
    BYTE jump[kLandJumpLen] = { 0xE9, 0, 0, 0, 0, 0x90, 0x90, 0x90, 0x90 };
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(&StubLand) -
                                             (reinterpret_cast<uintptr_t>(head) + 5));
    memcpy(jump + 1, &rel, 4);
    if (!WriteCode(head, jump, sizeof jump)) {
        UimodLog("[uimod] leaderfree: VirtualProtect failed -> the landing search stays as the base game has it\n");
        return;
    }
    UimodLog("[uimod] leaderfree: a freed leader's faction lands on a tile picked from the whole map\n");
}

// Thinker 5.5: repoint the one call in Thinker's own probe(). Every check comes before the one write; anything else
// (another Thinker build, another mod on thinker.dll) leaves thinker.dll exactly as it was.
void InstallFreedMessageThinker()
{
    uintptr_t lo, hi;
    if (!ThinkerRange(&lo, &hi)) return;
    if (!ThinkerOnPin()) {                                     // reduced mode: nothing of ours touches thinker.dll
        UimodLog("[uimod] leaderfree: not the supported Thinker Mod build -> the jailer keeps Thinker's popup\n");
        return;
    }
    BYTE* const base = reinterpret_cast<BYTE*>(lo);
    const IMAGE_DOS_HEADER* dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    const IMAGE_NT_HEADERS32* nt = reinterpret_cast<const IMAGE_NT_HEADERS32*>(base + dos->e_lfanew);
    if (nt->FileHeader.TimeDateStamp != kThStamp || nt->OptionalHeader.SizeOfImage != kThImageSize) {
        UimodLog("[uimod] leaderfree: thinker.dll is not the 5.5 build -> the jailer keeps Thinker's popup\n");
        return;
    }
    BYTE* const call = base + kThCall;
    const BYTE* const push = base + kThPushes;
    uint32_t pointer;
    memcpy(&pointer, base + kThPointer, 4);
    const bool ok =
        pointer == static_cast<uint32_t>(reinterpret_cast<uintptr_t>(At(kVA_NetMsgPop2))) &&
        call[0] == 0xFF && call[1] == 0x15 && Abs32At(call + 2, base + kThPointer) &&
        push[0] == 0xC7 && push[1] == 0x44 && push[2] == 0x24 && push[3] == 0x04 && Abs32At(push + 4, base + kThImage) &&
        push[8] == 0xC7 && push[9] == 0x04 && push[10] == 0x24 && Abs32At(push + 11, base + kThLabel) &&
        memcmp(base + kThImage, kFreedImageName, sizeof kFreedImageName) == 0 &&
        memcmp(base + kThLabel, kFreedLabelName, sizeof kFreedLabelName) == 0 &&
        memcmp(base + kThSetSlot, kExpectThSetSlot, sizeof kExpectThSetSlot) == 0 &&
        memcmp(base + kThReadSlot, kExpectThReadSlot, sizeof kExpectThReadSlot) == 0;
    if (!ok) {
        UimodLog("[uimod] leaderfree: unexpected bytes at Thinker's free message -> the jailer keeps Thinker's popup\n");
        return;
    }
    if (!BuildFreedScript()) {
        UimodLog("[uimod] leaderfree: could not write uimod_leaderfree.txt -> the jailer keeps Thinker's popup\n");
        return;
    }
    g_freedTextReady = true;
    BYTE e8[6] = { 0xE8, 0, 0, 0, 0, 0x90 };
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(&StubFreedThinker) -
                                             (reinterpret_cast<uintptr_t>(call) + 5));
    memcpy(e8 + 1, &rel, 4);
    if (!WriteCode(call, e8, sizeof e8)) {
        UimodLog("[uimod] leaderfree: VirtualProtect failed -> the jailer keeps Thinker's popup\n");
        return;
    }
    UimodLog("[uimod] leaderfree: the jailer of a freed leader gets its own message (Thinker 5.5)\n");
}

} // namespace

void InstallLeaderFreeFix()
{
    if (ThinkerLoaded()) {
        UimodLog("[uimod] leaderfree: thinker.dll loaded -> the pick stands down (Thinker replaces probe() and fixes "
                 "it itself)\n");
        InstallFreedMessageThinker();
        return;
    }
    BYTE* entry = At(kVA_ProbeEntry);
    BYTE* loop = At(kVA_PickLoop);
    if (memcmp(entry, kExpectEntry, sizeof kExpectEntry) != 0) {
        UimodLog("[uimod] leaderfree: probe() is not the base game's (Thinker or another mod owns it) -> fix NOT "
                 "installed\n");
        return;
    }
    if (memcmp(loop, kExpectLoop, sizeof kExpectLoop) != 0) {
        UimodLog("[uimod] leaderfree: unexpected bytes in probe's captured-leader loop -> fix NOT installed\n");
        return;
    }
    g_resume = At(kVA_Resume);
    BYTE jump[kJumpLen] = { 0xE9, 0, 0, 0, 0, 0x90, 0x90 };
    const int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(&StubPick) -
                                             (reinterpret_cast<uintptr_t>(loop) + 5));
    memcpy(jump + 1, &rel, 4);
    DWORD old;
    if (!VirtualProtect(loop, kJumpLen, PAGE_EXECUTE_READWRITE, &old)) {
        UimodLog("[uimod] leaderfree: VirtualProtect failed -> fix NOT installed\n");
        return;
    }
    memcpy(loop, jump, kJumpLen);
    VirtualProtect(loop, kJumpLen, old, &old);
    FlushInstructionCache(GetCurrentProcess(), loop, kJumpLen);
    UimodLog("[uimod] leaderfree: AI probe teams free the captured leader they target, never a living faction\n");
    InstallFreedMessageBaseGame();
    InstallHomelessProbeFix();
    InstallLandingSearch();
}
