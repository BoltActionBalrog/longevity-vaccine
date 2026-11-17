// terrainhd_bench -- times the engine's own terrain rasterizer natively, with and without the HD span stubs (the
// measurement behind the PR #9 round-3 answer on repaint speed). Not a test: a tool, run by hand.
//
// The pristine exe's image is mapped at 0x400000 in this process (it relaunches itself suspended and reserves that
// range in the child before the loader can use it), its imports resolved, its malloc / free sent to ours; the stubs
// are terrainhd.cpp's own (InstallSpanScaling, compiled here with TERRAINHD_SELFTEST, writing into the mapped image).
// A "repaint": a screen of tile diamonds, the 4 table quads each through Texture_draw_2 (0x6233C0) mode -1, a ground
// texture per tile plus an overlay texture on every third tile, so the drawn texture changes as in the terrain pass.
// Per tile width: stock (nothing patched), the stubs with the row off, the stubs scanning a full list of 163 others,
// the row on at 4x and 8x, and the row on with only 2 distinct textures (the cache footprint taken away).
//
// Build (x86 Native Tools prompt, from this folder):
//   cl /nologo /O2 /EHsc /std:c++17 /DNOMINMAX terrainhd_bench.cpp /I ..\..\src\uimod\src
//      /link /BASE:0x30000000 /FIXED /DYNAMICBASE:NO psapi.lib user32.lib gdi32.lib
// Run:   terrainhd_bench.exe <pristine terranx.exe> [repeats=10] [width=3840] [height=2160]
#define TERRAINHD_SELFTEST
#include "terrainhd.cpp"
#include <algorithm>
#include <vector>

void UimodLog(const char* m) { fputs(m, stderr); }
void UimodDbg(const char*) {}
bool PrefsTabInstalled() { return true; }

static void* __cdecl MyMalloc(size_t n) { return malloc(n); }
static void __cdecl MyFree(void* p) { free(p); }
static void Jmp(uintptr_t at, const void* to)
{
    uint8_t* p = reinterpret_cast<uint8_t*>(at);
    p[0] = 0xE9;
    int32_t rel = static_cast<int32_t>(reinterpret_cast<uintptr_t>(to) - (at + 5));
    memcpy(p + 1, &rel, 4);
}

static bool MapImage(const char* path)
{
    FILE* f = nullptr;
    if (fopen_s(&f, path, "rb")) return false;
    std::vector<uint8_t> file;
    fseek(f, 0, SEEK_END); file.resize(ftell(f)); fseek(f, 0, SEEK_SET);
    fread(file.data(), 1, file.size(), f); fclose(f);
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(file.data());
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS32*>(file.data() + dos->e_lfanew);
    // the parent reserved the range in this (then suspended) process before the loader could use it: commit it
    uint8_t* base = static_cast<uint8_t*>(VirtualAlloc(reinterpret_cast<void*>(0x400000),
                                                       nt->OptionalHeader.SizeOfImage, MEM_COMMIT,
                                                       PAGE_EXECUTE_READWRITE));
    if (base != reinterpret_cast<uint8_t*>(0x400000)) {
        printf("0x400000 not free (%p, error %lu, own module %p)\n", base, GetLastError(), GetModuleHandleW(nullptr));
        for (uintptr_t a = 0x400000; a < 0xA10000;) {
            MEMORY_BASIC_INFORMATION mi;
            VirtualQuery(reinterpret_cast<void*>(a), &mi, sizeof mi);
            if (mi.State != MEM_FREE)
                printf("  %p +%zx state %lx type %lx\n", mi.BaseAddress, mi.RegionSize, mi.State, mi.Type);
            a = reinterpret_cast<uintptr_t>(mi.BaseAddress) + mi.RegionSize;
        }
        return false;
    }
    memcpy(base, file.data(), nt->OptionalHeader.SizeOfHeaders);
    auto* sec = IMAGE_FIRST_SECTION(nt);
    for (int i = 0; i < nt->FileHeader.NumberOfSections; ++i) {
        DWORD n = sec[i].SizeOfRawData;
        if (sec[i].Misc.VirtualSize && sec[i].Misc.VirtualSize < n) n = sec[i].Misc.VirtualSize;
        memcpy(base + sec[i].VirtualAddress, file.data() + sec[i].PointerToRawData, n);
    }
    auto& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    for (auto* d = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(base + dir.VirtualAddress); d->Name; ++d) {
        HMODULE m = LoadLibraryA(reinterpret_cast<char*>(base + d->Name));
        const DWORD names = d->OriginalFirstThunk ? d->OriginalFirstThunk : d->FirstThunk;
        auto* th = reinterpret_cast<IMAGE_THUNK_DATA32*>(base + names);
        auto* iat = reinterpret_cast<IMAGE_THUNK_DATA32*>(base + d->FirstThunk);
        for (; th->u1.AddressOfData; ++th, ++iat) {
            FARPROC fn = nullptr;
            if (m) {
                if (th->u1.Ordinal & IMAGE_ORDINAL_FLAG32)
                    fn = GetProcAddress(m, reinterpret_cast<char*>(static_cast<uintptr_t>(th->u1.Ordinal & 0xFFFF)));
                else
                    fn = GetProcAddress(m, reinterpret_cast<IMAGE_IMPORT_BY_NAME*>(base + th->u1.AddressOfData)->Name);
            }
            iat->u1.Function = static_cast<DWORD>(reinterpret_cast<uintptr_t>(fn));
        }
    }
    for (uintptr_t va : { 0x6470A6u, 0x64558Au }) Jmp(va, reinterpret_cast<const void*>(&MyMalloc));
    for (uintptr_t va : { 0x644EF2u, 0x64557Fu }) Jmp(va, reinterpret_cast<const void*>(&MyFree));
    return true;
}

static const int QUADS[16][2] = { {27,27},{27,55},{0,55},{0,0},{27,27},{27,0},{55,0},{55,55},{27,27},{55,27},{55,55},
                                  {27,55},{27,27},{0,27},{0,0},{27,0} };

typedef int (__thiscall* Draw2)(void* tex, void* dst, int* pts, int* light, int n, int* uvs, int mode);
static const Draw2 kDraw = reinterpret_cast<Draw2>(0x6233C0);

static uint8_t* MakeTex(int side, int seed)
{
    uint8_t* t = static_cast<uint8_t*>(calloc(1, kTexSize));
    uint8_t* b = static_cast<uint8_t*>(malloc(static_cast<size_t>(side) * side));
    for (int i = 0; i < side * side; ++i) b[i] = static_cast<uint8_t>(20 + (i * 7 + seed * 13 + (i / side) * 3) % 180);
    auto* tt = reinterpret_cast<Texture*>(t);
    tt->data = b; tt->w = side; tt->h = side;
    TexCorners(reinterpret_cast<int32_t*>(t), 56, 56);
    return t;
}

static uint8_t g_buf[0x588 + 64];

static void Repaint(std::vector<uint8_t*>& tex, int tilePx, int W, int H)
{
    int light[4] = { 0, 0, 0, 0 };
    unsigned seed = 1;
    int pts[8], uvs[8];
    for (int ty = -tilePx / 2, row = 0; ty < H; ty += tilePx / 4, ++row)
        for (int tx = (row & 1) ? tilePx / 2 : 0; tx < W; tx += tilePx) {
            seed = seed * 1103515245 + 12345;
            const int ground = (seed >> 8) % 32, over = 32 + (seed >> 16) % 100;
            const int layers = ((seed >> 4) % 3) == 0 ? 2 : 1;
            for (int layer = 0; layer < layers; ++layer) {
                void* t = tex[layer ? over : ground];
                for (int q = 0; q < 4; ++q) {
                    for (int c = 0; c < 4; ++c) {
                        const int u = QUADS[q * 4 + c][0], v = QUADS[q * 4 + c][1];
                        pts[2 * c] = tx + (u + v) * tilePx / 110;
                        pts[2 * c + 1] = ty + tilePx / 4 - u * tilePx / 220 + v * tilePx / 220;
                        uvs[2 * c] = u; uvs[2 * c + 1] = v;
                    }
                    kDraw(t, g_buf, pts, light, 4, uvs, -1);
                }
            }
        }
}

static double Time(const char* name, std::vector<uint8_t*>& tex, int tilePx, int reps, int W, int H)
{
    std::vector<double> ms;
    LARGE_INTEGER f, a, b;
    QueryPerformanceFrequency(&f);
    Repaint(tex, tilePx, W, H);
    for (int r = 0; r < reps; ++r) {
        QueryPerformanceCounter(&a);
        Repaint(tex, tilePx, W, H);
        QueryPerformanceCounter(&b);
        ms.push_back(1000.0 * (b.QuadPart - a.QuadPart) / f.QuadPart);
    }
    std::sort(ms.begin(), ms.end());
    printf("  %-48s median %7.2f ms (min %7.2f)\n", name, ms[ms.size() / 2], ms[0]);
    fflush(stdout);
    return ms[ms.size() / 2];
}

static void SetList(std::vector<uint8_t*>& l, int shift)
{
    g_span.count = static_cast<uint32_t>(l.size());
    for (size_t i = 0; i < l.size(); ++i) g_span.ptrs[i] = reinterpret_cast<Texture*>(l[i])->data;
    g_span.levelShift = shift;
    g_span.last = reinterpret_cast<const void*>(1);
}

int main(int argc, char** argv)
{
    if (argc < 2) return 2;
    if (!GetEnvironmentVariableA("THD_BENCH_CHILD", nullptr, 0)) {
        // relaunch suspended, reserve 0x400000..0xA0C000 in the child, let it run
        SetEnvironmentVariableA("THD_BENCH_CHILD", "1");
        STARTUPINFOA si = { sizeof si };
        PROCESS_INFORMATION pi = {};
        if (!CreateProcessA(nullptr, GetCommandLineA(), nullptr, nullptr, TRUE, CREATE_SUSPENDED, nullptr, nullptr,
                            &si, &pi))
            return 3;
        if (!VirtualAllocEx(pi.hProcess, reinterpret_cast<void*>(0x400000), 0x60C000, MEM_RESERVE, PAGE_NOACCESS)) {
            printf("could not reserve in the child: %lu\n", GetLastError());
            TerminateProcess(pi.hProcess, 4);
            return 4;
        }
        ResumeThread(pi.hThread);
        WaitForSingleObject(pi.hProcess, INFINITE);
        DWORD code = 0;
        GetExitCodeProcess(pi.hProcess, &code);
        return static_cast<int>(code);
    }
    if (!MapImage(argv[1])) return 2;
    const int W = argc > 3 ? atoi(argv[3]) : 3840, H = argc > 4 ? atoi(argv[4]) : 2160;
    reinterpret_cast<void(__thiscall*)(void*)>(0x5D7210)(g_buf);
    int rc = reinterpret_cast<int(__thiscall*)(void*, int, int, int, int)>(0x5D7670)(g_buf, W, H, 0, 0);
    printf("Buffer_init %d, w %d pitch %d bits %p\n", rc, *reinterpret_cast<int*>(g_buf + 0x80),
           *reinterpret_cast<int*>(g_buf + 0x4A8), *reinterpret_cast<void**>(g_buf + 0x54));
    g_testImage = reinterpret_cast<BYTE*>(0x400000);
    uint8_t orig[100][6];
    for (int i = 0; i < 100; ++i) memcpy(orig[i], At(kSpanSites[i]), 6);

    const int nTex = 163;
    std::vector<uint8_t*> stock(nTex), hd4(nTex), hd8(nTex), dummies(nTex);
    for (int i = 0; i < nTex; ++i) {
        stock[i] = MakeTex(56, i);
        hd4[i] = MakeTex(224, i);
        hd8[i] = MakeTex(448, i);
        dummies[i] = MakeTex(56, 1000 + i);
    }
    const int reps = argc > 2 ? atoi(argv[2]) : 10;
    for (int tile : { 56, 96, 200 }) {
        printf("%dx%d, tile %d px\n", W, H, tile);
        for (int i = 0; i < 100; ++i) {
            DWORD o;
            VirtualProtect(At(kSpanSites[i]), 6, PAGE_EXECUTE_READWRITE, &o);
            memcpy(At(kSpanSites[i]), orig[i], 6);
        }
        FlushInstructionCache(GetCurrentProcess(), nullptr, 0);
        Time("stock, nothing patched", stock, tile, reps, W, H);
        if (!InstallSpanScaling()) { printf("install failed\n"); return 1; }
        g_span.count = 0; g_span.levelShift = 0; g_span.last = reinterpret_cast<const void*>(1);
        Time("stubs, row off (empty list)", stock, tile, reps, W, H);
        SetList(dummies, 3);
        Time("stubs, 163 others listed, stock drawn (scans)", stock, tile, reps, W, H);
        SetList(stock, 0);
        Time("stubs, stock textures listed with shift 0", stock, tile, reps, W, H);
        SetList(hd4, 2);
        Time("stubs, row on at 4x", hd4, tile, reps, W, H);
        SetList(hd8, 3);
        Time("stubs, row on at 8x", hd8, tile, reps, W, H);
        std::vector<uint8_t*> two8(nTex), two4(nTex);
        for (int i = 0; i < nTex; ++i) { two8[i] = hd8[i & 1]; two4[i] = hd4[i & 1]; }
        Time("stubs, row on at 8x, only 2 distinct textures", two8, tile, reps, W, H);
        SetList(hd4, 2);
        Time("stubs, row on at 4x, only 2 distinct textures", two4, tile, reps, W, H);
    }
    return 0;
}
