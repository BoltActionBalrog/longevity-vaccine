// pslabel_core.h -- under Thinker, which function appends a PSYCH-tab row label (pure logic; pssphere.cpp feeds it the
// engine's memory, tests\pslabel_selftest.cpp feeds it cases).
//
// BaseWin_draw_psych appends rows 0, 1, 2 and 4's label at one call site, 0x408DBD (`call strcat`, buffer 0x9B86A0
// emptied just before). Row 0 is label 970 "Captured Base" (assimilation turns left and a former owner), else 971
// "Stapled Base" (staple turns left), else 322 "Unmodified"; rows 1, 2, 4 are labels 323, 324, 327 "Secret Projects".
// Thinker 5.5 write_calls the site to its BaseWin_draw_psych_strcat (basewin.cpp), which under render_base_info
//   - on a base with staple turns left or a Punishment Sphere: 971 -> "Unmodified" (322), 327 -> "Stapled Base" (971);
//   - on a base with assimilation turns left: 970 -> label_captured_base "Captured Base: %d turns";
//   - appends every other label as it is.
// Our would-be totals sit in row 4 on exactly those sphere / stapled bases, under which "Stapled Base" reads backwards
// (user decision 2026-10-29: squash the relabel). KeepOwn picks the engine's strcat for those two labels on those
// bases and Thinker's function for everything else, so the captured countdown and every other line stay Thinker's.
// The base test is Thinker's own (staple byte != 0, or facility 23 built; an id outside 0..511 is Thinker's to handle)
// and so is the label test (strcmp against the raw label text, TextLabels.labels[n]). With render_base_info off
// Thinker appends every label unchanged, so the engine's strcat gives the same text.
#pragma once

#include <cstdint>
#include <cstring>

namespace pslabel {

constexpr int kMaxBases = 512;
constexpr int kBaseSize = 0x134;
constexpr int kBaseStaple = 0x08;                 // uint8 nerve_staple_turns_left
constexpr int kBaseSphereByte = 0x8E;             // facilities_built (+0x8C) byte 23 / 8
constexpr uint8_t kSphereBit = 0x80;              //   bit 23 % 8
constexpr uint32_t kLabelStapledBase = 971;
constexpr uint32_t kLabelSecretProjects = 327;

// True: the engine's strcat appends `source` (our squash); false: Thinker's function does.
inline bool KeepOwn(int baseId, const uint8_t* bases, const char* const* labels, uint32_t labelCount, const char* source)
{
    if (!source || !bases || !labels || baseId < 0 || baseId >= kMaxBases) return false;
    if (labelCount <= kLabelStapledBase) return false;          // labels not (fully) loaded: Thinker's call as it is
    const uint8_t* base = bases + static_cast<size_t>(baseId) * kBaseSize;
    if (base[kBaseStaple] == 0 && (base[kBaseSphereByte] & kSphereBit) == 0) return false;
    const char* stapled = labels[kLabelStapledBase];
    const char* projects = labels[kLabelSecretProjects];
    return (stapled && strcmp(source, stapled) == 0) || (projects && strcmp(source, projects) == 0);
}

// The target of the 5-byte E9 / E8 `bytes` found at address `at`, when its opcode is `opcode` and the target lies in
// [lo, hi) (thinker.dll's image); 0 otherwise. Every Thinker function pssphere.cpp chains comes through here.
inline uintptr_t BranchTarget(const uint8_t* bytes, uintptr_t at, uint8_t opcode, uintptr_t lo, uintptr_t hi)
{
    if (bytes[0] != opcode || lo >= hi) return 0;
    int32_t rel;
    memcpy(&rel, bytes + 1, 4);
    const uintptr_t target = static_cast<uintptr_t>(static_cast<uint32_t>(at + 5 + static_cast<uint32_t>(rel)));
    return target >= lo && target < hi ? target : 0;
}

// The 5-byte E9 / E8 at address `at` that reaches `fn`.
inline void EncodeBranch(uint8_t out[5], uintptr_t at, uint8_t opcode, uintptr_t fn)
{
    out[0] = opcode;
    const uint32_t rel = static_cast<uint32_t>(fn) - static_cast<uint32_t>(at + 5);
    memcpy(out + 1, &rel, 4);
}

} // namespace pslabel
