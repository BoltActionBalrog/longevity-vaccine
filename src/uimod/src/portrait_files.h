// Replacement portrait files.  With "Use Turovetsky's HD Portrait Pack" on: <game>\portraits\hd\<name>.png (the
// portraits-hd pack) first, then the player's own <game>\portraits\<name>.png|.jpg; with it off, only the player's
// own.  A file that is missing or unusable falls through to the next, and past the last to the game's own art.
// <name> is a faction's file name (MFactions[f].filename, e.g. "gaians") or a native-life picture's base name
// (e.g. "BTwrm").
//
// The pure helpers here have no Windows dependency, so a self-test can compile them alone.
#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>

namespace portrait_files {

// [A-Za-z0-9_-]{1,23} and not a DOS device name.  The name comes from game data (alpha(x).txt, scenarios, saves,
// a multiplayer host): anything else -- '.', ':', '\\', '/', spaces, an over-long name -- is refused, never mapped.
inline bool SafeName(const char* n)
{
    if (!n) return false;
    size_t len = 0;
    for (; n[len]; ++len) {
        const char c = n[len];
        const bool ok = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' || c == '-';
        if (!ok || len >= 23) return false;
    }
    if (len == 0) return false;
    auto up = [](char c) { return c >= 'a' && c <= 'z' ? static_cast<char>(c - 32) : c; };
    auto is = [&](const char* dev) {
        size_t i = 0;
        for (; dev[i]; ++i) if (up(n[i]) != dev[i]) return false;
        return n[i] == 0;
    };
    static const char* const kDev[] = { "CON", "PRN", "AUX", "NUL" };
    for (const char* d : kDev) if (is(d)) return false;
    if (len == 4 && (up(n[0]) == 'C' || up(n[0]) == 'L')) {          // COM1..9 / LPT1..9
        const bool com = up(n[0]) == 'C' && up(n[1]) == 'O' && up(n[2]) == 'M';
        const bool lpt = up(n[0]) == 'L' && up(n[1]) == 'P' && up(n[2]) == 'T';
        if ((com || lpt) && n[3] >= '1' && n[3] <= '9') return false;
    }
    return true;
}

// The six native-life combat portraits (filename-backed sprites, 96x115).  Case-insensitive.
inline bool IsNativeLifeName(const char* base)
{
    static const char* const kNames[] = { "btwrm", "btisl", "btchi", "btsealrk", "btsporlnch", "btfungtow" };
    if (!base) return false;
    for (const char* k : kNames) {
        size_t i = 0;
        for (; k[i]; ++i) {
            char c = base[i];
            if (c >= 'A' && c <= 'Z') c = static_cast<char>(c + 32);
            if (c != k[i]) break;
        }
        if (!k[i] && !base[i]) return true;
    }
    return false;
}

// "BTwrm.pcx" / "art\\BTwrm.PCX" -> "BTwrm".  False unless the name ends in ".pcx" and the base fits.
inline bool BaseName(const char* file, char* out, size_t n)
{
    if (!file || !out || n == 0) return false;
    size_t len = 0;
    while (file[len] && len < 260) ++len;
    if (len < 5 || len >= 260) return false;
    auto lo = [](char c) { return c >= 'A' && c <= 'Z' ? static_cast<char>(c + 32) : c; };
    const char* ext = file + len - 4;
    if (!(ext[0] == '.' && lo(ext[1]) == 'p' && lo(ext[2]) == 'c' && lo(ext[3]) == 'x')) return false;
    size_t start = len - 4;
    while (start > 0 && file[start - 1] != '\\' && file[start - 1] != '/' && file[start - 1] != ':') --start;
    const size_t bl = len - 4 - start;
    if (bl == 0 || bl + 1 > n) return false;
    for (size_t i = 0; i < bl; ++i) out[i] = file[start + i];
    out[bl] = 0;
    return true;
}

// A decoded replacement: r,g,b bytes, pre-reduced (portrait_law::Prereduce).  id changes whenever the file does.
struct Image {
    std::vector<uint8_t> rgb;
    int w = 0, h = 0;
    uint64_t id = 0;
};

// The replacement for `name`, decoded and cached; nullptr when there is none or it is unusable (logged once).
// Every call re-checks the files (a cheap attribute query), so an added / edited / removed image is seen at the
// next faction load or native-life draw.  Any thread: the cache is under a lock, held across the decode, so a
// file is decoded once however many threads ask (the pre-bake worker and the game thread).
std::shared_ptr<const Image> Find(const char* name);

// Preferences: `enabled` = "Enable Custom Portraits" (off: Find never returns an image); `usePack` = "Enable HD
// Portraits" (off: portraits\hd\ is not looked at, the player's own portraits\ still are).
void SetOptions(bool enabled, bool usePack);
// The names Find could serve right now (the pack's and the player's png / jpg stems, case-insensitively unique,
// SafeName, not native life), at most `max`.  Any thread.
size_t ListNames(char (*out)[24], size_t max);
// The game folder (the exe's), with its trailing backslash.
bool GameDir(wchar_t* out, size_t n);
// (test) a thread takes the cache lock for `ms`, then releases it or exits holding it; the bypass latch's state.
void TestHoldLock(int ms, bool die);
void TestOrphanLockHere();                    // (test) the calling thread takes the cache lock and never releases it
bool DebugLockDead();
// The portraits-hd pack is installed: portraits\hd\pack-manifest.json exists (the pack always ships it).
bool PackInstalled();

} // namespace portrait_files
