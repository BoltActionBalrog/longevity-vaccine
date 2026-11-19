// leaderfree_core.h -- which captured faction leader an AI probe team frees (pure logic; leaderfree.cpp feeds it the
// engine's tables, tests\leaderfree_selftest.cpp feeds it cases).
//
// The engine records a captured leader when a faction is eliminated for good: mon_killed_faction 0x477A60 (called
// only from eliminate_player, only when setup_player found no escape pod) writes the FIRST FREE of the jailer's six
// "captured" slots: Monuments[jailer].data2[i][7] = the eliminated faction, data2[i][9] = 1. So a slot's index says
// nothing about whose leader it holds. The base game's AI pick (probe 0x59F120, loop 0x5A29B9) assumed slot i held
// faction i + 1: it read the prober's treaty with faction i + 1 and chose faction i + 1, over 7 slots. The first
// leader ever captured sits in slot 0, so the AI "freed" faction 1 whoever that was -- and the free calls
// setup_player, which deletes every base and unit of a living faction and lands it again as a colony pod.
//
// Pick keeps the base game's own preference rule (a pact partner over a treaty partner over anyone; never a faction
// the prober is in vendetta with) and applies it to the faction each slot really holds, and only to one that can be
// freed: in 1..7, still eliminated, neither the prober nor the jailer.
#pragma once

#include <cstdint>

namespace leaderfree {

constexpr int kSlots = 6;                 // mon_killed_faction, the free's clean-up loop and the player's menu: 6 slots
constexpr int kFirstFaction = 1;          // 0 = the natives
constexpr int kLastFaction = 7;
constexpr int32_t kPact = 0x1;            // diplo_status bits (Thinker's DIPLO_PACT / DIPLO_TREATY / DIPLO_VENDETTA)
constexpr int32_t kTreaty = 0x2;
constexpr int32_t kVendetta = 0x10;

struct Slot {
    int32_t faction;                      // data2[i][7]
    int32_t captured;                     // data2[i][9]
};

// The faction an AI probe team of `prober` frees from `jailer`, or -1 when none qualifies (the AI then does not choose
// this action). aliveMask: FactionStatus[1] (bit f = faction f is alive). diplo: the prober's diplo_status[0..7].
inline int Pick(const Slot* slots, int nslots, uint32_t aliveMask, const int32_t* diplo, int prober, int jailer)
{
    int pick = -1;
    for (int i = 0; i < nslots; ++i) {
        if (!slots[i].captured) continue;
        const int f = slots[i].faction;
        if (f < kFirstFaction || f > kLastFaction) continue;
        if (f == prober || f == jailer) continue;
        if (aliveMask & (1u << f)) continue;                      // free only a faction that is still eliminated
        const int32_t d = diplo[f];
        if (d & kVendetta) continue;
        if (pick < 0 || (d & kPact) || ((d & kTreaty) && !(diplo[pick] & kPact))) pick = f;
    }
    return pick;
}

// The engine's tables, as laid out in memory (strides and offsets measured from the writer mon_killed_faction 0x477A60
// and the base game's own pick loop): captured = &Monuments[0] kill record 15's payload (0x94CD58; faction j's slot i
// at + j * 0x4F4 + i * 0x38, its "captured" word 8 bytes on), diplo = &Factions[0].diplo_status[0] (0x96C9F8; the
// prober's row at + prober * 0x20CC), alive = FactionStatus[1].
constexpr int kMonumentSize = 0x4F4;
constexpr int kSlotSize = 0x38;
constexpr int kCapturedFlagOffset = 8;
constexpr int kFactionSize = 0x20CC;

inline int PickFromTables(const uint8_t* captured, uint8_t alive, const uint8_t* diplo, int prober, int jailer)
{
    if (prober < 0 || prober > kLastFaction || jailer < 0 || jailer > kLastFaction) return -1;
    Slot slots[kSlots];
    for (int i = 0; i < kSlots; ++i) {
        const uint8_t* row = captured + jailer * kMonumentSize + i * kSlotSize;
        slots[i].faction = *reinterpret_cast<const int32_t*>(row);
        slots[i].captured = *reinterpret_cast<const int32_t*>(row + kCapturedFlagOffset);
    }
    return Pick(slots, kSlots, alive, reinterpret_cast<const int32_t*>(diplo + prober * kFactionSize), prober, jailer);
}

// The free's message (WILLYFREE, "You managed to liberate ...") is written for the rescuer, but the game shows it to the
// rescuer OR the jailer. True when the player watching is not the rescuer, i.e. is the jailer the gate let through, and
// our own text for that side is available; otherwise the game's own popup runs untouched.
inline bool JailerSeesOwnMessage(int rescuer, int currentPlayer, bool textReady)
{
    return textReady && rescuer != currentPlayer;
}

// ---------------------------------------------------------------------------------------------------------------------
// WHERE THE FREED FACTION LANDS. setup_player 0x5B0E00 looks for a landing tile with 1024 random draws (loop head
// 0x5B1688): each draw is judged by the game's site rules, several of which loosen with the draw number, and when none
// passes the 1025th draw is taken unjudged -- any tile, sea or a foreign base's own tile included. Draws repeat and most
// of a map is never drawn, so that happens while good tiles exist. For a rescue the draws are replaced by ONE shuffled
// list of every tile, fed to the game's own rules (the loop body is untouched; the hook only supplies x, y and the draw
// number):
//   pass 1   each tile once, judged at the draw number its place in the list maps to (VirtualDraw) -- the rules loosen
//            along the list exactly as they do along the 1024 draws, and never see a number the game cannot produce
//            (one rule, "landmass tiles per faction >= 64 - n/64", stops at 48 only because n stops at 1024);
//   pass 2   each tile once more at the last draw number: a tile early in the list was only ever judged strictly;
//   pass 3   the first tile of the faction's kind (land; sea for an aquatic faction) with no base and no unit, off the
//            two rows at each pole, outside the jailer's territory -- then the same inside it;
//   last     the game's own unjudged draw.
// The shuffle uses the game's random numbers (two per pick: one is 15 bits, too few for an even pick on a large list).

struct Tile {
    int16_t x, y;
};

constexpr int kDraws = 0x400;             // the game's draw count; draw numbers the rules see are 1..kDraws
constexpr int kTileSize = 0x2C;           // MAP: [0] altitude in the top 3 bits, [2] low nibble = unit owner (>= 8: none),
                                          // [7] territory owner, [8] flags (1 = base, 2 = unit)

// The band a draw comes from: the game leaves (kDraws - i) * size / 8192 tiles off each end (rows always, columns on
// a flat map), i = the draw's index 0..kDraws-1. Signed division by 8192 toward zero and the 9999 cap are the game's.
inline int DrawMargin(int i, int size)
{
    const int p = (kDraws - i) * size;
    const int m = (p + ((p >> 31) & 0x1FFF)) >> 13;
    return m < 0 ? 0 : m > 9999 ? 9999 : m;
}

// True when draw i can produce tile (x, y). The game draws a row and a raw column, then moves the column onto the
// row's parity (odd -> one left, then one right on an odd row): tile x comes from raw column x - (y & 1) or the next.
inline bool InDrawBand(int i, int x, int y, int w, int h, bool flat)
{
    const int ym = DrawMargin(i, h), ry = h - 2 * ym;
    if (y < ym || y > ym + (ry > 1 ? ry - 1 : 0)) return false;
    const int xm = flat ? DrawMargin(i, w) : 0, rx = w - 2 * xm;
    const int lo = xm, hi = xm + (rx > 1 ? rx - 1 : 0), raw = x - (y & 1);
    return (raw >= lo && raw <= hi) || (raw + 1 >= lo && raw + 1 <= hi);
}

// The draw index (0..kDraws-1) a tile at place j of n is judged at.
inline int VirtualDraw(int j, int n)
{
    return static_cast<int>(static_cast<int64_t>(j) * kDraws / n);
}

// Every tile of a w x h map in row order, then shuffled (Fisher-Yates) with rand15: the game's rand, 0..32767.
template <typename Rand>
inline int ShuffledTiles(Tile* out, int w, int h, Rand&& rand15)
{
    int n = 0;
    for (int y = 0; y < h; ++y)
        for (int x = y & 1; x < w; x += 2) out[n++] = Tile{ static_cast<int16_t>(x), static_cast<int16_t>(y) };
    for (int i = n - 1; i > 0; --i) {
        const uint32_t high = static_cast<uint32_t>(rand15()) & 0x7FFF;
        const uint32_t low = static_cast<uint32_t>(rand15()) & 0x7FFF;
        const int k = static_cast<int>(((high << 15) | low) % static_cast<uint32_t>(i + 1));
        const Tile t = out[i];
        out[i] = out[k];
        out[k] = t;
    }
    return n;
}

struct LandMap {
    int w, h, halfX;                      // MapAreaX, MapAreaY, MapHalfX
    bool flat;
    const uint8_t* tiles;                 // MapTiles
};

inline const uint8_t* TileAt(const LandMap& m, int x, int y)
{
    return m.tiles + (m.halfX * y + (x >> 1)) * kTileSize;
}

// Pass 3's tile: the faction's kind, nothing on it, off the pole rows. The kind test is the game's own (land is
// altitude >= 0x60; an aquatic faction takes <= 0x40).
inline bool FallbackTile(const LandMap& m, int x, int y, bool aquatic)
{
    if (y < 2 || y >= m.h - 2) return false;
    const uint8_t* t = TileAt(m, x, y);
    const int altitude = t[0] & 0xE0;
    if (aquatic ? altitude > 0x40 : altitude < 0x60) return false;
    if (t[8] & 1) return false;                                   // a base
    return !(t[8] & 2) || (t[2] & 0xF) >= 8;                      // a unit (the game's own test: flag and an owner)
}

inline bool InTerritoryOf(const LandMap& m, int x, int y, int faction)
{
    return static_cast<int8_t>(TileAt(m, x, y)[7]) == faction;
}

// One search. Begin, then Next until it returns false: each true is a tile for the game's loop body with the draw
// index to judge it at (kDraws = take it unjudged). False once: nothing left, the game's own draw runs at *draw.
class LandSearch {
public:
    void Begin(const Tile* list, int n)
    {
        list_ = list;
        n_ = n;
        pass_ = 1;
        at_ = 0;
    }

    bool Next(const LandMap& m, bool aquatic, int jailer, int* x, int* y, int* draw)
    {
        if (pass_ == 1) {
            while (at_ < n_) {
                const int j = at_++;
                const int i = VirtualDraw(j, n_);
                if (!InDrawBand(i, list_[j].x, list_[j].y, m.w, m.h, m.flat)) continue;
                return Give(j, i, x, y, draw);
            }
            pass_ = 2;
            at_ = 0;
        }
        if (pass_ == 2) {
            if (at_ < n_) {
                const int j = at_++;
                return Give(j, kDraws - 1, x, y, draw);
            }
            pass_ = 3;
        }
        *draw = kDraws;
        if (pass_ == 3) {
            pass_ = 4;
            for (int own = 0; own < 2; ++own)                      // outside the jailer's territory first
                for (int j = 0; j < n_; ++j)
                    if (FallbackTile(m, list_[j].x, list_[j].y, aquatic) &&
                        (own == 1 || !InTerritoryOf(m, list_[j].x, list_[j].y, jailer)))
                        return Give(j, kDraws, x, y, draw);
        }
        return false;
    }

    int pass() const { return pass_; }

private:
    bool Give(int j, int i, int* x, int* y, int* draw) const
    {
        *x = list_[j].x;
        *y = list_[j].y;
        *draw = i;
        return true;
    }

    const Tile* list_ = nullptr;
    int n_ = 0, pass_ = 4, at_ = 0;
};

// A map the search can run on: the list is w * h / 2 tiles, the index math needs an even width and halfX = w / 2.
constexpr int kMaxLandTiles = 1 << 17;
constexpr int kMaxLandSide = 4096;     // below 8192 the last draw's band is the whole map (DrawMargin(kDraws - 1) = 0)
inline bool LandMapUsable(const LandMap& m)
{
    return m.tiles && m.w > 0 && m.h > 4 && !(m.w & 1) && !(m.h & 1) && m.halfX * 2 == m.w && m.w <= kMaxLandSide && m.h <= kMaxLandSide &&
           static_cast<int64_t>(m.halfX) * m.h <= kMaxLandTiles;
}

// The hook's side of it, on setup_player's frame (ebp): [-4] x, [-8] y, [-0x14] the draw counter, [+4] the return
// address, [+8] the faction, [+0xC] the jailer. Step is called at the loop head, once per draw. The counter is 0 only on
// a call's first draw (the body leaves it >= 1, and Step never hands back less), which is where a search begins or the
// last one is forgotten. Returns 1 with x, y and the counter set (resume at the body), or 0 with x and y untouched (the
// game's own draw; after a search ran out the counter is kDraws, so that draw is the game's unjudged one).
struct LandEnv {
    uint32_t rescueReturn;                // where probe's own call of setup_player returns
    bool multiplayer;                     // every machine replays the action on a shared seed: left as the game has it
    int turn;
    LandMap map;
    const uint8_t* factionRules;          // MFactions[0]'s rule flags; faction f's at + f * kFactionRulesStride
};

constexpr int kFactionRulesStride = 0x59C;
constexpr uint32_t kRuleAquatic = 0x100;

inline int32_t FrameInt(const uint8_t* frame, int offset)
{
    return *reinterpret_cast<const int32_t*>(frame + offset);
}

// A rescue this search handles: probe's own call, in a single-player game under way, on a map the list fits.
inline bool LandIsRescue(const uint8_t* frame, const LandEnv& env)
{
    const int faction = FrameInt(frame, 8), jailer = FrameInt(frame, 0xC);
    return static_cast<uint32_t>(FrameInt(frame, 4)) == env.rescueReturn && !env.multiplayer && env.turn != 0 &&
           faction >= kFirstFaction && faction <= kLastFaction && jailer >= 0 && jailer <= kLastFaction &&
           LandMapUsable(env.map);
}

class LandDriver {
public:
    // tiles: room for kMaxLandTiles (null: no search). rand15: the game's rand.
    template <typename Rand>
    int Step(uint8_t* frame, const LandEnv& env, Tile* tiles, Rand&& rand15)
    {
        int32_t* const counter = reinterpret_cast<int32_t*>(frame - 0x14);
        if (*counter == 0) {
            owner_ = nullptr;
            if (tiles && LandIsRescue(frame, env)) {
                search_.Begin(tiles, ShuffledTiles(tiles, env.map.w, env.map.h, rand15));
                owner_ = frame;
            }
        }
        if (owner_ != frame) return 0;
        const int faction = FrameInt(frame, 8), jailer = FrameInt(frame, 0xC);
        const bool aquatic =
            (*reinterpret_cast<const uint32_t*>(env.factionRules + faction * kFactionRulesStride) & kRuleAquatic) != 0;
        int x = 0, y = 0, draw = 0;
        const bool given = search_.Next(env.map, aquatic, jailer, &x, &y, &draw);
        *counter = draw;
        if (!given) {
            owner_ = nullptr;
            return 0;
        }
        *reinterpret_cast<int32_t*>(frame - 4) = x;
        *reinterpret_cast<int32_t*>(frame - 8) = y;
        return 1;
    }

private:
    LandSearch search_;
    const uint8_t* owner_ = nullptr;      // the frame whose search is running
};

} // namespace leaderfree
