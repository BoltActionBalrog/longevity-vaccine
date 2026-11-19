// Self-test harness for thinkersites_core.h (tests\test_thinker_sites.py builds and runs it once per module).
// Drives the REAL generated table (thinker_sites.h) through every state an exe can be in, over a fake image made of
// byte regions -- no process memory, no writes. Prints one "PASS <name>" or "FAIL <name> <detail>" line per check.
#include <cstdio>
#include <map>
#include <string>
#include <vector>

#include "../../src/uimod/src/thinkersites_core.h"

namespace {

using namespace thinkersites;

constexpr uint32_t kThLo = 0x10000000, kThHi = 0x10200000;

struct Image {
    std::map<uint32_t, std::vector<uint8_t>> regions;     // start va -> bytes
    uint8_t* At(uint32_t va, uint32_t len)
    {
        auto it = regions.upper_bound(va);
        if (it == regions.begin()) return nullptr;
        --it;
        if (va < it->first || va + len > it->first + it->second.size()) return nullptr;
        return it->second.data() + (va - it->first);
    }
    void Put(uint32_t va, const uint8_t* b, uint32_t n)
    {
        if (uint8_t* p = At(va, n)) { memcpy(p, b, n); return; }
        regions[va].assign(b, b + n);
    }
};

const uint8_t* Read(void* ctx, uint32_t va, uint32_t len) { return static_cast<Image*>(ctx)->At(va, len); }

void Check(const char* name, bool ok, const std::string& detail = "")
{
    std::printf("%s %s %s\n", ok ? "PASS" : "FAIL", name, ok ? "" : detail.c_str());
}

const char* Name(Action a)
{
    switch (a) {
    case Action::AlreadyOurs: return "already";
    case Action::Write: return "write";
    case Action::SkipGroup: return "skip";
    case Action::MinEnough: return "min-enough";
    case Action::MinWrite: return "min-write";
    default: return "fatal";
    }
}

enum Fill { kClean, kOurs, kThinker };     // kThinker: the reference bytes with every kCall window an E8 into thinker.dll

// A region around each site (so the guards of a kMinImm32 site are inside it), its bytes, and its destinations.
Image Build(Fill excluded, Fill restore, bool dests, uint32_t caviar)
{
    Image img;
    for (uint32_t i = 0; i < kNumSites; ++i) {
        const Site& s = kSites[i];
        std::vector<uint8_t> pad(s.len + 48, 0xCC);
        img.regions[s.va - 16] = pad;
        uint8_t* p = img.At(s.va, s.len);
        if (s.mode == kMinImm32) {
            memcpy(p, &caviar, 4);
            for (uint32_t g = 0; g < s.nguards; ++g) *img.At(s.va + s.guards[g].off, 1) = s.guards[g].byte;
            continue;
        }
        const Fill f = s.mode == kRestore ? restore : excluded;
        // kClean is the unpatched exe's bytes at EVERY site (a kRestore site too: an exe our patcher never touched);
        // kThinker starts from what is on disk under Thinker (clean for kExcluded, ours for kRestore)
        const uint8_t* ref = s.mode == kRestore ? s.ours : s.clean;
        memcpy(p, f == kOurs ? s.ours : f == kClean ? s.clean : ref, s.len);
        if (f == kThinker) {
            for (uint32_t w = 0; w < s.nwindows; ++w) {
                if (s.windows[w].kind != kCall) continue;
                const uint32_t at = s.va + s.windows[w].off + (s.windows[w].len == 6 ? 1 : 0);
                if (s.windows[w].len == 6) p[s.windows[w].off] = 0x90;
                uint8_t call[5] = { 0xE8 };
                const int32_t rel = static_cast<int32_t>(kThLo + 0x1000 - (at + 5));
                memcpy(call + 1, &rel, 4);
                memcpy(img.At(at, 5), call, 5);
            }
        }
        if (dests)
            for (uint32_t d = 0; d < s.ndests; ++d) img.Put(s.dests[d].va, s.dests[d].bytes, sizeof s.dests[d].bytes);
    }
    return img;
}

std::string Run(Image& img, bool thinker)
{
    View v;
    v.read = &Read;
    v.ctx = &img;
    if (thinker) { v.thinkerLo = kThLo; v.thinkerHi = kThHi; }
    Action plan[64];
    char why[64][kWhyLen];
    Plan(kSites, kNumSites, v, plan, why);
    std::string out;
    for (uint32_t i = 0; i < kNumSites; ++i) {
        if (i) out += " ";
        out += std::string(kSites[i].id) + "=" + Name(plan[i]);
        const bool needsWhy = plan[i] == Action::SkipGroup || plan[i] == Action::Fatal;
        if (needsWhy && !why[i][0]) out += "(NO-REASON)";
        if (!needsWhy && why[i][0]) out += "(STRAY-REASON)";
    }
    return out;
}

const Site* Find(const char* idPart, SiteMode mode)
{
    for (uint32_t i = 0; i < kNumSites; ++i)
        if (kSites[i].mode == mode && strstr(kSites[i].id, idPart)) return &kSites[i];
    return nullptr;
}

} // namespace

int main()
{
    constexpr uint32_t kOursSize = 0x00200000;

    // the table itself
    const Site* min = Find("Caviar", kMinImm32);
    Check("table_has_the_min_imm32_site", min && min->len == 4 && min->nguards == 5 && Imm32(min->ours) == kOursSize && min->ndests == 0);
    bool everyCodeSiteHasADest = true, everyGroupNamed = true;
    for (uint32_t i = 0; i < kNumSites; ++i) {
        everyGroupNamed = everyGroupNamed && kSites[i].group && kSites[i].group[0];
        if (kSites[i].mode != kMinImm32) everyCodeSiteHasADest = everyCodeSiteHasADest && kSites[i].ndests >= 1;
    }
    Check("every_code_site_names_a_destination", everyCodeSiteHasADest);
    Check("every_site_names_its_group", everyGroupNamed);

    // each state of an exe prints its whole plan; test_thinker_sites.py pins the lines
    { Image i = Build(kOurs, kOurs, true, kOursSize);        std::printf("PLAN pracx_exe %s\n", Run(i, false).c_str()); }
    // (the Thinker-folder exe: excluded sites clean on disk, the restore site ours on disk)
    { Image i = Build(kClean, kOurs, true, 0x00020000);      std::printf("PLAN thinker_folder_without_thinker %s\n", Run(i, false).c_str()); }
    { Image i = Build(kThinker, kThinker, true, 0x00100000); std::printf("PLAN under_thinker %s\n", Run(i, true).c_str()); }
    { Image i = Build(kClean, kClean, false, 0x00020000);    std::printf("PLAN exe_without_our_code %s\n", Run(i, false).c_str()); }
    { Image i = Build(kThinker, kThinker, true, 0x00100000); std::printf("PLAN thinker_header_unreadable %s\n", Run(i, false).c_str()); }
    {   // a byte outside Thinker's window is not the reference byte: that site's whole group is out, the others are not
        Image i = Build(kThinker, kThinker, true, 0x00100000);
        const Site* s = Find("keyed_scaled", kExcluded);
        uint32_t off = 0;
        while (s && WindowAt(*s, off)) ++off;
        if (s) *i.At(s->va + off, 1) ^= 0xFF;
        std::printf("PLAN foreign_byte_in_one_menu_site %s\n", Run(i, true).c_str());
    }
    {   // our code is not at the other end of the credits site's jump
        Image i = Build(kThinker, kThinker, true, 0x00100000);
        const Site* s = Find("load_credits", kExcluded);
        if (s) *i.At(s->dests[0].va, 1) ^= 0xFF;
        std::printf("PLAN credits_destination_differs %s\n", Run(i, true).c_str());
    }
    {   // a window holds a call that goes neither where the clean exe's does nor into thinker.dll
        Image i = Build(kThinker, kThinker, true, 0x00100000);
        const Site* s = Find("load_credits", kExcluded);
        if (s) {
            const uint32_t at = s->va + s->windows[0].off;
            uint8_t call[5] = { 0xE8 };
            const int32_t rel = static_cast<int32_t>(0x20000000 - (at + 5));
            memcpy(call + 1, &rel, 4);
            memcpy(i.At(at, 5), call, 5);
        }
        std::printf("PLAN call_into_neither %s\n", Run(i, true).c_str());
    }

    {   // the group rule works BACKWARDS too: a later site of the table failing takes an earlier one out
        Image i = Build(kThinker, kThinker, true, 0x00100000);
        const Site* s = Find("soft_update_scaled", kExcluded);
        uint32_t off = 0;
        while (s && WindowAt(*s, off)) ++off;
        if (s) *i.At(s->va + off, 1) ^= 0xFF;
        std::printf("PLAN foreign_byte_in_a_later_menu_site %s\n", Run(i, true).c_str());
    }
    {   // ... and so does a missing destination on ONE site of a multi-site group
        Image i = Build(kThinker, kThinker, true, 0x00100000);
        const Site* s = Find("keyed_scaled", kExcluded);
        if (s) *i.At(s->dests[0].va, 1) ^= 0xFF;
        std::printf("PLAN menu_destination_differs %s\n", Run(i, true).c_str());
    }
    {   // a site that already holds our bytes stays "already" when a sibling fails: nothing un-writes it
        Image i = Build(kClean, kOurs, true, 0x00020000);
        const Site* s = Find("keyed_scaled", kExcluded);
        uint32_t off = 0;
        while (s && WindowAt(*s, off)) ++off;
        if (s) *i.At(s->va + off, 1) ^= 0xFF;
        std::printf("PLAN failing_sibling_beside_already_ours %s\n", Run(i, false).c_str());
    }
    {   // the two window forms today's table does not contain: Thinker's write_call over an FF15 site (90 E8 rel32,
        // six bytes) and a Scient byte inside an ordinary site
        static const uint8_t clean[10] = { 0x51, 0xFF, 0x15, 0x10, 0x20, 0x30, 0x40, 0x6A, 0x02, 0xC3 };
        static const uint8_t ours[10]  = { 0x51, 0xE8, 0x00, 0x00, 0x00, 0x00, 0x90, 0x6A, 0x20, 0xC3 };
        static const Window wins[2] = { { 1, 6, kCall, 0x00 }, { 8, 1, kScient, 0x10 } };
        const Site syn = { "synthetic", 0x00500000, 10, clean, ours, wins, 2, "synthetic", nullptr, 0, nullptr, 0, kExcluded };
        auto verdict = [&](const uint8_t* bytes, bool thinker) {
            Image img;
            img.Put(syn.va, bytes, 10);
            View v; v.read = &Read; v.ctx = &img;
            if (thinker) { v.thinkerLo = kThLo; v.thinkerHi = kThHi; }
            char why[kWhyLen] = "";
            return SiteMatches(syn, v, why, sizeof why);
        };
        uint8_t t[10];
        memcpy(t, clean, 10);
        const bool asClean = verdict(t, true);
        t[1] = 0x90; t[2] = 0xE8;                                 // 90 E8 rel32 into thinker.dll
        const int32_t rel = static_cast<int32_t>(kThLo + 0x2000 - (syn.va + 2 + 5));
        memcpy(t + 3, &rel, 4);
        const bool ff15 = verdict(t, true), ff15NoThinker = verdict(t, false);
        t[8] = 0x10;                                              // Scient's byte
        const bool scient = verdict(t, true);
        t[8] = 0x33;                                              // neither clean nor Scient's
        const bool foreign = verdict(t, true);
        std::printf("SYNTH clean=%d ff15=%d ff15_without_thinker=%d scient=%d foreign_scient=%d\n", asClean, ff15, ff15NoThinker, scient, foreign);
    }

    // the minimum-value rule over the values the byte can hold
    for (uint32_t v : { 0x00020000u, 0x00100000u, 0x001FFFFFu, 0x00200000u, 0x00400000u, 0x01000000u, 0xFFFFFFFFu, 0u }) {
        Image i = Build(kOurs, kOurs, true, v);
        View view; view.read = &Read; view.ctx = &i;
        uint32_t live = 0;
        char why[kWhyLen] = "";
        const Action a = MinImm32(*min, view, &live, why, sizeof why);
        std::printf("MIN %08X %s %08X\n", v, Name(a), live);
    }
    for (uint32_t g = 0; g < min->nguards; ++g) {           // each guard byte, one at a time
        Image i = Build(kOurs, kOurs, true, 0x00020000);
        *i.At(min->va + min->guards[g].off, 1) ^= 0xFF;
        View view; view.read = &Read; view.ctx = &i;
        uint32_t live = 0;
        char why[kWhyLen] = "";
        const Action a = MinImm32(*min, view, &live, why, sizeof why);
        std::printf("GUARD %d %s %s\n", min->guards[g].off, Name(a), why[0] ? "reason" : "NO-REASON");
    }
    {
        Image empty;
        View view; view.read = &Read; view.ctx = &empty;
        uint32_t live = 0;
        char why[kWhyLen] = "";
        std::printf("MIN unmapped %s\n", Name(MinImm32(*min, view, &live, why, sizeof why)));
    }
    return 0;
}
