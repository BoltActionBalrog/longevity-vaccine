// Self-test harness for leaderfree_core.h (tests\test_leaderfree.py builds and runs it). One case per stdin line:
//   prober jailer aliveMask d0..d7 f0 c0 .. f5 c5    -> leaderfree::Pick on parsed slots (23 integers)
//   tables <file> prober jailer                      -> leaderfree::PickFromTables on raw engine memory; <file> holds
//       8 * 0x4F4 bytes from 0x94CD58, then 1 byte FactionStatus[1], then 8 * 0x20CC bytes from 0x96C9F8
// Prints one result per line ("bad" for a malformed line).
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <iterator>
#include <sstream>
#include <string>
#include <vector>

#include "../../src/uimod/src/leaderfree_core.h"

namespace {

int Tables(std::istringstream& in)
{
    std::string path;
    int prober = 0, jailer = 0;
    if (!(in >> path >> prober >> jailer)) return -100;
    std::ifstream f(path, std::ios::binary);
    std::vector<uint8_t> b((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    const size_t cap = 8 * leaderfree::kMonumentSize, dip = 8 * leaderfree::kFactionSize;
    if (b.size() != cap + 1 + dip) return -100;
    return leaderfree::PickFromTables(b.data(), b[cap], b.data() + cap + 1, prober, jailer);
}

// The C runtime's rand, as the game uses it (seed * 214013 + 2531011, bits 16..30).
struct CrtRand {
    uint32_t seed;
    int calls = 0;
    int operator()()
    {
        ++calls;
        seed = seed * 214013u + 2531011u;
        return static_cast<int>((seed >> 16) & 0x7FFF);
    }
};

// The landing commands. Each prints one line of integers.
//   band i x y w h flat           -> InDrawBand
//   vdraw j n                     -> VirtualDraw
//   shuffle w h seed              -> n, FNV-1a of the shuffled (x, y) list, rand calls
//   search <file> aquatic jailer seed -> kind x y draw nextCalls randCalls ; <file>: int32 w h halfX flat, then the
//       tiles (0x2C bytes each); a tile's bytes 0x28..0x29 hold the first draw index the "game" accepts it at
//       (0xFFFF: never). kind 1 = accepted by the rules, 2 = handed over unjudged, 3 = left to the game's own draw.
bool Landing(const std::string& line)
{
    std::istringstream in(line);
    std::string word;
    in >> word;
    if (word == "band") {
        int i, x, y, w, h, flat;
        if (!(in >> i >> x >> y >> w >> h >> flat)) return false;
        std::printf("%d\n", leaderfree::InDrawBand(i, x, y, w, h, flat != 0) ? 1 : 0);
        return true;
    }
    if (word == "vdraw") {
        int j, n;
        if (!(in >> j >> n)) return false;
        std::printf("%d\n", leaderfree::VirtualDraw(j, n));
        return true;
    }
    if (word == "shuffle") {
        int w, h;
        uint32_t seed;
        if (!(in >> w >> h >> seed)) return false;
        std::vector<leaderfree::Tile> t(static_cast<size_t>(w) * h);
        CrtRand r{ seed };
        const int n = leaderfree::ShuffledTiles(t.data(), w, h, r);
        uint32_t hash = 2166136261u;
        for (int k = 0; k < n; ++k)
            for (int v : { static_cast<int>(t[k].x), static_cast<int>(t[k].y) }) {
                hash = (hash ^ static_cast<uint32_t>(v & 0xFF)) * 16777619u;
                hash = (hash ^ static_cast<uint32_t>((v >> 8) & 0xFF)) * 16777619u;
            }
        std::printf("%d %u %d\n", n, hash, r.calls);
        return true;
    }
    if (word == "search") {
        std::string path;
        int aquatic, jailer;
        uint32_t seed;
        if (!(in >> path >> aquatic >> jailer >> seed)) return false;
        std::ifstream f(path, std::ios::binary);
        std::vector<uint8_t> b((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
        if (b.size() < 16) return false;
        const int32_t* head = reinterpret_cast<const int32_t*>(b.data());
        const leaderfree::LandMap map{ head[0], head[1], head[2], head[3] != 0, b.data() + 16 };
        if (!leaderfree::LandMapUsable(map) ||
            b.size() != 16 + static_cast<size_t>(map.halfX) * map.h * leaderfree::kTileSize) return false;
        std::vector<leaderfree::Tile> t(static_cast<size_t>(map.halfX) * map.h);
        CrtRand r{ seed };
        leaderfree::LandSearch search;
        search.Begin(t.data(), leaderfree::ShuffledTiles(t.data(), map.w, map.h, r));
        int x = -1, y = -1, draw = -1, calls = 0, kind = 3;
        for (;;) {
            ++calls;
            if (!search.Next(map, aquatic != 0, jailer, &x, &y, &draw)) { x = y = -1; break; }
            if (draw == leaderfree::kDraws) { kind = 2; break; }
            const uint8_t* tile = leaderfree::TileAt(map, x, y);
            if (draw >= (tile[0x28] | tile[0x29] << 8)) { kind = 1; break; }
        }
        std::printf("%d %d %d %d %d %d\n", kind, x, y, draw, calls, r.calls);
        return true;
    }
    if (word == "usable") {                     // usable w h halfX hasTiles -> LandMapUsable
        int w, h, half, has;
        if (!(in >> w >> h >> half >> has)) return false;
        static const uint8_t one = 0;
        std::printf("%d\n", leaderfree::LandMapUsable(leaderfree::LandMap{ w, h, half, false, has ? &one : nullptr }) ? 1 : 0);
        return true;
    }
    if (word == "loop") {
        // loop <file> aquatic jailer seed mode -> LandDriver::Step driven as setup_player's loop drives it, on a real
        // frame image; the "body" accepts as in `search`. mode 0: a rescue. Prints kind x y draw steps randCalls.
        // Other modes must leave the frame alone and print "0 <steps> <randCalls> <frame untouched>":
        //   1 another caller's return address, 2 multiplayer, 3 turn 0, 4 faction 0, 5 jailer 8, 6 no tile memory,
        //   7 a search left unfinished, then the same frame mid-loop for a caller that is not a rescue.
        std::string path;
        int aquatic, jailer, mode;
        uint32_t seed;
        if (!(in >> path >> aquatic >> jailer >> seed >> mode)) return false;
        std::ifstream f(path, std::ios::binary);
        std::vector<uint8_t> b((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
        if (b.size() < 16) return false;
        const int32_t* head = reinterpret_cast<const int32_t*>(b.data());
        const leaderfree::LandMap map{ head[0], head[1], head[2], head[3] != 0, b.data() + 16 };
        const int faction = mode == 4 ? 0 : 5;
        std::vector<uint8_t> rules(8 * leaderfree::kFactionRulesStride);
        const uint32_t flags = aquatic ? 0xFFFFFFFFu : ~leaderfree::kRuleAquatic;
        std::memcpy(rules.data() + faction * leaderfree::kFactionRulesStride, &flags, 4);
        const uint32_t kReturn = 0x5A3CA0;
        const leaderfree::LandEnv env{ kReturn, mode == 2, mode == 3 ? 0 : 120, map, rules.data() };
        std::vector<leaderfree::Tile> t(leaderfree::kMaxLandTiles);
        int32_t image[16];
        for (int k = 0; k < 16; ++k) image[k] = 0x7E570000 + k;
        uint8_t* const frame = reinterpret_cast<uint8_t*>(image + 8);
        const auto local = [&](int offset) -> int32_t& { return *reinterpret_cast<int32_t*>(frame + offset); };
        local(4) = static_cast<int32_t>(mode == 1 ? kReturn + 5 : kReturn);
        local(8) = faction;
        local(0xC) = mode == 5 ? 8 : jailer;
        local(-0x14) = 0;
        CrtRand r{ seed };
        leaderfree::LandDriver driver;
        leaderfree::Tile* const tiles = mode == 6 ? nullptr : t.data();
        int steps = 0;
        if (mode == 7) {
            for (int k = 0; k < 3; ++k) {                                  // a rescue's first draws, all rejected
                ++steps;
                if (!driver.Step(frame, env, tiles, r)) return false;
                local(-0x14) += 1;
            }
            local(4) = static_cast<int32_t>(kReturn + 5);                  // the next setup_player call: same frame, no rescue
            local(-0x14) = 0;
            ++steps;
            if (driver.Step(frame, env, tiles, r)) return false;
            local(-0x14) = 9;                                              // ... and its later draws
        }
        if (mode != 0) {
            int32_t before[16];
            std::memcpy(before, image, sizeof before);
            const int calls = r.calls;
            ++steps;
            const int got = driver.Step(frame, env, tiles, r);
            std::printf("%d %d %d %d\n", got, steps, r.calls - calls, std::memcmp(before, image, sizeof before) == 0 ? 1 : 0);
            return true;
        }
        int kind = 0, x = -1, y = -1, draw = -1;
        for (;;) {
            ++steps;
            const int given = driver.Step(frame, env, tiles, r);
            draw = local(-0x14);
            if (given) { x = local(-4); y = local(-8); } else { x = y = -1; }
            local(-0x14) = draw + 1;                                       // the body's own step
            if (draw + 1 > leaderfree::kDraws) { kind = given ? 2 : 3; break; }
            if (!given) return false;                                      // a rescue never hands back before the end
            const uint8_t* tile = leaderfree::TileAt(map, x, y);
            if (draw >= (tile[0x28] | tile[0x29] << 8)) { kind = 1; break; }
        }
        for (int k = 0; k < 16; ++k)                                       // nothing but x, y and the counter was written
            if (k != 8 - 1 && k != 8 - 2 && k != 8 - 5 && k != 8 + 1 && k != 8 + 2 && k != 8 + 3 && image[k] != 0x7E570000 + k) return false;
        if (local(4) != static_cast<int32_t>(kReturn) || local(8) != faction || local(0xC) != jailer) return false;
        std::printf("%d %d %d %d %d %d\n", kind, x, y, draw, steps, r.calls);
        return true;
    }
    return false;
}

} // namespace

int main()
{
    std::string line;
    while (std::getline(std::cin, line)) {
        std::istringstream in(line);
        if (line.rfind("band ", 0) == 0 || line.rfind("vdraw ", 0) == 0 || line.rfind("shuffle ", 0) == 0 ||
            line.rfind("search ", 0) == 0 || line.rfind("loop ", 0) == 0 || line.rfind("usable ", 0) == 0) {
            if (!Landing(line)) std::printf("bad\n");
            continue;
        }
        if (line.rfind("view ", 0) == 0) {          // view rescuer currentPlayer textReady -> JailerSeesOwnMessage
            std::string word;
            int r = 0, c = 0, ready = 0;
            in >> word >> r >> c >> ready;
            std::printf("%d\n", leaderfree::JailerSeesOwnMessage(r, c, ready != 0) ? 1 : 0);
            continue;
        }
        if (line.rfind("tables ", 0) == 0) {
            std::string word;
            in >> word;
            const int r = Tables(in);
            if (r == -100) std::printf("bad\n"); else std::printf("%d\n", r);
            continue;
        }
        long long v[23];
        int n = 0;
        while (n < 23 && (in >> v[n])) ++n;
        if (n != 23) { std::printf("bad\n"); continue; }
        int32_t diplo[8];
        for (int i = 0; i < 8; ++i) diplo[i] = static_cast<int32_t>(v[3 + i]);
        leaderfree::Slot slots[leaderfree::kSlots];
        for (int i = 0; i < leaderfree::kSlots; ++i) {
            slots[i].faction = static_cast<int32_t>(v[11 + 2 * i]);
            slots[i].captured = static_cast<int32_t>(v[12 + 2 * i]);
        }
        std::printf("%d\n", leaderfree::Pick(slots, leaderfree::kSlots, static_cast<uint32_t>(v[2]), diplo,
                                             static_cast<int>(v[0]), static_cast<int>(v[1])));
    }
    return 0;
}
