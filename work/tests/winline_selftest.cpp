// Self-test harness for uimod's lineoverlay.h (the window-line overlay of the stretched display modes) and mapgate.h
// (the Modern Control Set's map-pointer gate). tests\test_winline_overlay.py builds and runs it.
// winline_selftest <script.txt>: one command per line, results on stdout, one line per query:
//   add x0 y0 x1 y1 color width style ret   -> "kept 0|1"   (ret = the call's return address, hex)
//   flip l t r b                            -> "changed 0|1"
//   prune armed hasSecond                   -> "changed 0|1"
//   dump                                    -> "n N" then "x0 y0 x1 y1 tag nErase" per line, oldest first
//   touches x0 y0 x1 y1 width l t r b       -> "touches 0|1"
//   toclient v client frame                 -> "client C"
//   penw width style client frame           -> "penw W"
//   gate lx ly rx ry mox moy nb [bl bt br bb]*nb -> "verdict V hit H"
//   win id delegate shown l t r b nchild [child]*  (a synthetic window; id 1..63, 0 = none)
//   walk map strip overlay tut n [id]*             -> "map M block id id ..." (mapgate::Blockers over that list)
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "../../src/uimod/src/lineoverlay.h"
#include "../../src/uimod/src/mapgate.h"

// Synthetic windows for mapgate::Blockers: id 1..63, a window's address is &g_win[id].
struct FakeWin { int delegate, shown, nchild, child[8]; mapgate::Rect r; };
FakeWin g_win[64];
const void* WinPtr(int id) { return id > 0 && id < 64 ? &g_win[id] : nullptr; }
int WinId(const void* w) { return w ? static_cast<int>(static_cast<const FakeWin*>(w) - g_win) : 0; }
const void* FDelegate(const void* w) { return WinPtr(static_cast<const FakeWin*>(w)->delegate); }
int FChildCount(const void* w) { return static_cast<const FakeWin*>(w)->nchild; }
const void* FChild(const void* w, int i) { return WinPtr(static_cast<const FakeWin*>(w)->child[i]); }
bool FRect(const void* w, mapgate::Rect* r)
{
    const FakeWin* f = static_cast<const FakeWin*>(w);
    if (!f->shown) return false;
    *r = f->r;
    return true;
}
const mapgate::WinAccess kFake = { FDelegate, FChildCount, FChild, FRect };

int main(int argc, char** argv)
{
    if (argc != 2) return 2;
    FILE* f = std::fopen(argv[1], "r");
    if (!f) return 3;
    lineoverlay::List s = {};
    char line[512];
    while (std::fgets(line, sizeof line, f)) {
        char cmd[32] = {};
        int n = 0;
        if (std::sscanf(line, "%31s%n", cmd, &n) != 1) continue;
        const char* rest = line + n;
        if (!std::strcmp(cmd, "add")) {
            lineoverlay::Line l = {};
            unsigned ret = 0;
            if (std::sscanf(rest, "%d %d %d %d %d %d %d %x", &l.x0, &l.y0, &l.x1, &l.y1, &l.color, &l.width, &l.style, &ret) != 8) return 4;
            l.tag = lineoverlay::TagOf(ret);
            std::printf("kept %d\n", lineoverlay::Add(s, l) ? 1 : 0);
        } else if (!std::strcmp(cmd, "flip")) {
            lineoverlay::Rect r;
            if (std::sscanf(rest, "%d %d %d %d", &r.l, &r.t, &r.r, &r.b) != 4) return 5;
            std::printf("changed %d\n", lineoverlay::OnFlip(s, r) ? 1 : 0);
        } else if (!std::strcmp(cmd, "prune")) {
            int armed, second;
            if (std::sscanf(rest, "%d %d", &armed, &second) != 2) return 6;
            std::printf("changed %d\n", lineoverlay::PruneTutorial(s, armed != 0, second != 0) ? 1 : 0);
        } else if (!std::strcmp(cmd, "dump")) {
            std::printf("n %d\n", s.n);
            for (int i = 0; i < s.n; ++i)
                std::printf("%d %d %d %d %d %d\n", s.line[i].x0, s.line[i].y0, s.line[i].x1, s.line[i].y1, s.line[i].tag, s.line[i].nErase);
        } else if (!std::strcmp(cmd, "touches")) {
            lineoverlay::Line l = {};
            lineoverlay::Rect r;
            if (std::sscanf(rest, "%d %d %d %d %d %d %d %d %d", &l.x0, &l.y0, &l.x1, &l.y1, &l.width, &r.l, &r.t, &r.r, &r.b) != 9) return 7;
            std::printf("touches %d\n", lineoverlay::Touches(l, r) ? 1 : 0);
        } else if (!std::strcmp(cmd, "toclient")) {
            int v, c, fr;
            if (std::sscanf(rest, "%d %d %d", &v, &c, &fr) != 3) return 8;
            std::printf("client %d\n", lineoverlay::ToClient(v, c, fr));
        } else if (!std::strcmp(cmd, "penw")) {
            int w, st, c, fr;
            if (std::sscanf(rest, "%d %d %d %d", &w, &st, &c, &fr) != 4) return 9;
            std::printf("penw %d\n", lineoverlay::ClientPenWidth(w, st, c, fr));
        } else if (!std::strcmp(cmd, "gate")) {
            mapgate::Pt local, raw, mapOrg;
            mapgate::Rect blk[8];
            int nb, used = 0;
            if (std::sscanf(rest, "%d %d %d %d %d %d %d%n", &local.x, &local.y, &raw.x, &raw.y, &mapOrg.x, &mapOrg.y, &nb,
                            &used) != 7 || nb < 0 || nb > 8)
                return 10;
            rest += used;
            for (int i = 0; i < nb; ++i) {
                int u = 0;
                if (std::sscanf(rest, "%d %d %d %d%n", &blk[i].l, &blk[i].t, &blk[i].r, &blk[i].b, &u) != 4) return 11;
                rest += u;
            }
            int hit = -2;
            const int v = static_cast<int>(mapgate::Gate(local, raw, mapOrg, blk, nb, &hit));
            std::printf("verdict %d hit %d\n", v, hit);
        } else if (!std::strcmp(cmd, "win")) {        // win id delegate shown l t r b nchild [child]*
            int id, used = 0;
            FakeWin f = {};
            if (std::sscanf(rest, "%d %d %d %d %d %d %d %d%n", &id, &f.delegate, &f.shown, &f.r.l, &f.r.t, &f.r.r, &f.r.b,
                            &f.nchild, &used) != 8 || id <= 0 || id >= 64 || f.nchild < 0 || f.nchild > 8)
                return 13;
            rest += used;
            for (int i = 0; i < f.nchild; ++i) {
                int u = 0;
                if (std::sscanf(rest, "%d%n", &f.child[i], &u) != 1) return 14;
                rest += u;
            }
            g_win[id] = f;
        } else if (!std::strcmp(cmd, "walk")) {       // walk map strip overlay tut n [listId]* -> "map M block id..."
            int map, strip, ovl, tut, n, used = 0;
            if (std::sscanf(rest, "%d %d %d %d %d%n", &map, &strip, &ovl, &tut, &n, &used) != 5 || n < 0 || n > 32) return 15;
            rest += used;
            const void* list[32];
            for (int i = 0; i < n; ++i) {
                int u = 0, id = 0;
                if (std::sscanf(rest, "%d%n", &id, &u) != 1) return 16;
                list[i] = WinPtr(id);
                rest += u;
            }
            mapgate::Rect out[8];
            const void* who[8];
            int mapIdx = -2;
            const int nb = mapgate::Blockers(kFake, list, n, WinPtr(map), WinPtr(strip), WinPtr(ovl), WinPtr(tut), out, who, 8, &mapIdx);
            std::printf("map %d block", mapIdx);
            for (int i = 0; i < nb; ++i) std::printf(" %d", WinId(who[i]));
            std::printf("\n");
        } else {
            return 12;
        }
    }
    std::fclose(f);
    return 0;
}
