// Replacement portrait files: lookup, hardened decode, cache.  See portrait_files.h.
//
// Every file here is untrusted input (a player's folder, or a downloaded pack), so the decode is fail-closed:
//  - the name is validated (SafeName) before it becomes a path; wide-char paths; a path that would not fit is
//    refused, never truncated;
//  - the file is opened ONCE (no stat-then-open race), directories are refused, anything over kMaxFileBytes is
//    refused, and the whole file is read into memory.  Reparse points are followed like any program would (a
//    OneDrive placeholder is a reparse point; redirecting a file needs write access to the game folder, which
//    already owns the exe);
//  - the format comes from the MAGIC BYTES (PNG signature, JPEG FF D8 FF) and a complete file (PNG IEND, JPEG
//    EOI), and the decoder is the in-box WIC PNG / JPEG decoder created by CLSID -- never WIC's auto-dispatch,
//    which would run any third-party codec a player has installed (HEIF, RAW, camera codecs...) inside the game.
//    (That protects against installed codecs, not registry tampering: whoever can write HKCU runs code anyway.)
//  - frame 0 only, metadata on demand and never queried; the size is checked (kMinSide..kMaxSide, 64-bit
//    arithmetic) BEFORE the pixel buffer is allocated -- 2048 per side bounds WIC's own working buffers in this
//    32-bit process; conversion to 24bpp RGB through IWICFormatConverter (alpha is dropped: a transparent area
//    shows whatever colour the file stores there);
//  - every allocation failure, COM error or SEH fault returns "no replacement" (the vanilla portrait).
// COM: initialised per decode and uninitialised only after OUR successful init (S_OK / S_FALSE); a thread that
// already runs another apartment (RPC_E_CHANGED_MODE) is used as is.  Decodes are rare (a faction load, or a
// native-life picture not in the cache), so no factory is kept across them.
// Threads: the cache (and the decode that fills it) is under one SRW lock -- the pre-bake worker (prewarm.cpp)
// decodes ahead of the game thread, and whoever asks second for the same file waits and gets the cached image.
// A path is matched case-insensitively and the image id hashes the lower-cased path: the engine names a faction
// in its own case ("GAIANS"), the directory listing in the file's, and both must mean one image.
#include "portrait_files.h"
#include "portrait_law.h"

#include <windows.h>
#include <wincodec.h>
#include <cstdio>
#include <cstring>
#include <cwctype>
#include <new>

void UimodLog(const char* msg);

namespace portrait_files {
namespace {

constexpr DWORD kMaxFileBytes = 32u << 20;
constexpr int kMinSide = 32, kMaxSide = 2048;
constexpr size_t kCacheSlots = 20;            // the 14 pack / faction images + the 6 native-life pictures (~4.5 MB each)

struct CacheEntry {                           // one per FILE (a name can have a pack and a player file)
    char key[24] = {};                        // lower-case name (log context)
    wchar_t path[MAX_PATH] = {};
    uint64_t size = 0, mtime = 0;
    std::shared_ptr<const Image> img;         // null = the file exists but is unusable (do not retry it unchanged)
    unsigned stamp = 0;
};
// Heap, never freed: a static destructor would run at ExitProcess while a worker thread may have been killed
// mid-decode; a leak at exit costs nothing.
CacheEntry* const g_cache = new (std::nothrow) CacheEntry[kCacheSlots];
unsigned g_clock = 0;
SRWLOCK g_lock = SRWLOCK_INIT;                // g_cache, g_clock
volatile LONG g_lockOwner = 0;                // the thread id holding g_lock (0 = free)
volatile LONG g_lockDead = 0;                 // held by a thread that no longer exists: bypassed for good
constexpr DWORD kLockMs = 1000;               // the bound (a decode under the lock takes ~40 ms, a 2048px one ~150)
volatile LONG g_testHold = 0;                 // (test) a thread holds the lock this long, then releases / exits

// Is the thread that holds the lock gone?  (Its id is recorded on acquire.)  A thread id is reused by the system:
// one that now names a thread of another process, or no thread, is gone too.
bool OwnerGone(DWORD tid)
{
    if (!tid) return false;
    HANDLE h = OpenThread(SYNCHRONIZE | THREAD_QUERY_LIMITED_INFORMATION, FALSE, tid);
    if (!h) return true;                      // no such thread
    const bool gone = WaitForSingleObject(h, 0) == WAIT_OBJECT_0 || GetProcessIdOfThread(h) != GetCurrentProcessId();
    CloseHandle(h);
    return gone;
}

// Bounded: within kLockMs the holder (a below-normal worker decoding) is boosted so it finishes; past the bound
// the caller decodes uncached THIS time; and only a holder that no longer exists latches the bypass for good
// (a live but slow holder never does: that would turn a loaded machine into uncached decodes for the session).
struct Locked {
    Locked()
    {
        if (g_lockDead) return;
        const DWORD t0 = GetTickCount();
        HANDLE boosted = nullptr;
        int oldPrio = THREAD_PRIORITY_NORMAL;
        for (;;) {
            ok = TryAcquireSRWLockExclusive(&g_lock) != 0;
            if (ok) break;
            const DWORD tid = static_cast<DWORD>(g_lockOwner);
            // SRW is not recursive and Locked never nests: the lock "held" by THIS thread is one a caught fault
            // (SEH skips destructors) left behind -- it will never be released.  Bypass at once, for good.
            if (tid == GetCurrentThreadId()) { InterlockedExchange(&g_lockDead, 1); break; }
            const DWORD spent = GetTickCount() - t0;
            if (spent >= kLockMs) { if (OwnerGone(tid)) InterlockedExchange(&g_lockDead, 1); break; }
            if (!boosted && spent >= 20 && tid) {
                boosted = OpenThread(THREAD_SET_INFORMATION | THREAD_QUERY_INFORMATION, FALSE, tid);
                if (boosted) { oldPrio = GetThreadPriority(boosted); SetThreadPriority(boosted, THREAD_PRIORITY_NORMAL); }
            }
            Sleep(1);
        }
        if (boosted) { if (oldPrio != THREAD_PRIORITY_ERROR_RETURN) SetThreadPriority(boosted, oldPrio); CloseHandle(boosted); }
        if (ok) InterlockedExchange(&g_lockOwner, static_cast<LONG>(GetCurrentThreadId()));
    }
    ~Locked() { if (ok) { InterlockedExchange(&g_lockOwner, 0); ReleaseSRWLockExclusive(&g_lock); } }
    bool ok = false;
};

DWORD WINAPI TestHoldThread(LPVOID p)         // (test) hold the lock, then release (p = 0) or die holding it (p = 1)
{
    Locked l;
    Sleep(static_cast<DWORD>(g_testHold));
    if (p) ExitThread(0);
    return 0;
}

bool GameDirW(wchar_t* out, size_t n);

// The path relative to the game folder (portraits\hd\gaians.png): a log pasted into a bug report must not carry
// the player's Windows user name from an install under the user profile.
void RelPath(const wchar_t* path, char* out, size_t n)
{
    wchar_t dir[MAX_PATH];
    const wchar_t* rel = path;
    if (GameDirW(dir, MAX_PATH)) {
        const size_t dl = wcslen(dir);
        if (_wcsnicmp(path, dir, dl) == 0) rel = path + dl;
    }
    out[0] = 0;
    WideCharToMultiByte(CP_UTF8, 0, rel, -1, out, static_cast<int>(n) - 1, nullptr, nullptr);
}

void Log(const char* fmt, const char* a, const wchar_t* path = nullptr)
{
    char msg[512];
    char p[MAX_PATH * 2] = {};
    if (path) RelPath(path, p, sizeof p);
    _snprintf_s(msg, sizeof msg, _TRUNCATE, fmt, a, p);
    UimodLog(msg);
}

bool GameDirW(wchar_t* out, size_t n)
{
    const DWORD len = GetModuleFileNameW(nullptr, out, static_cast<DWORD>(n));
    if (len == 0 || len >= n) return false;
    wchar_t* slash = wcsrchr(out, L'\\');
    if (!slash) return false;
    slash[1] = 0;
    return true;
}

// <dir><sub><name><ext>, refused (false) if it does not fit
bool BuildPath(wchar_t* out, size_t n, const wchar_t* dir, const wchar_t* sub, const char* name, const wchar_t* ext)
{
    wchar_t wname[32];
    size_t i = 0;
    for (; name[i] && i < 31; ++i) wname[i] = static_cast<wchar_t>(static_cast<unsigned char>(name[i]));
    wname[i] = 0;
    const size_t need = wcslen(dir) + wcslen(sub) + wcslen(wname) + wcslen(ext) + 1;
    if (need > n) return false;
    wcscpy_s(out, n, dir);
    wcscat_s(out, n, sub);
    wcscat_s(out, n, wname);
    wcscat_s(out, n, ext);
    return true;
}

// Attribute query: exists as a plain file?  (size, mtime) for the cache key.
bool Stat(const wchar_t* path, uint64_t* size, uint64_t* mtime)
{
    WIN32_FILE_ATTRIBUTE_DATA a;
    if (!GetFileAttributesExW(path, GetFileExInfoStandard, &a)) return false;
    if (a.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) return false;
    *size = (static_cast<uint64_t>(a.nFileSizeHigh) << 32) | a.nFileSizeLow;
    *mtime = (static_cast<uint64_t>(a.ftLastWriteTime.dwHighDateTime) << 32) | a.ftLastWriteTime.dwLowDateTime;
    return true;
}

bool ReadWhole(const wchar_t* path, std::vector<uint8_t>* out)
{
    HANDLE f = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                           FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (f == INVALID_HANDLE_VALUE) return false;
    bool ok = false;
    BY_HANDLE_FILE_INFORMATION fi;
    if (GetFileInformationByHandle(f, &fi) &&
        !(fi.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) &&
        fi.nFileSizeHigh == 0 && fi.nFileSizeLow > 8 && fi.nFileSizeLow <= kMaxFileBytes) {
        out->resize(fi.nFileSizeLow);
        DWORD got = 0;
        ok = ReadFile(f, out->data(), fi.nFileSizeLow, &got, nullptr) && got == fi.nFileSizeLow;
    }
    CloseHandle(f);
    return ok;
}

template <typename T> void Release(T*& p) { if (p) { p->Release(); p = nullptr; } }

// Decode PNG / JPEG bytes to 24bpp RGB.  False on anything unexpected.
// The WIC step that refused the last decode on this thread (the game thread and the prewarm worker both decode),
// for the log: a codec missing on this Windows is not "a bad file".
thread_local const char* g_wicStep = nullptr;
thread_local HRESULT     g_wicHr = S_OK;

bool DecodeWic(const std::vector<uint8_t>& file, std::vector<uint8_t>* rgb, int* w, int* h)
{
    static const uint8_t kPng[8] = { 0x89, 'P', 'N', 'G', 0x0D, 0x0A, 0x1A, 0x0A };
    const bool png = file.size() >= 8 && memcmp(file.data(), kPng, 8) == 0;
    const bool jpg = file.size() >= 3 && file[0] == 0xFF && file[1] == 0xD8 && file[2] == 0xFF;
    if (!png && !jpg) return false;
    // a cut-off file must not become half a portrait: WIC decodes a truncated PNG "successfully" (measured), so
    // require the format's end -- the PNG IEND chunk as the last 12 bytes, the JPEG EOI marker in the last 1 KB
    if (png) {
        static const uint8_t kIend[12] = { 0, 0, 0, 0, 'I', 'E', 'N', 'D', 0xAE, 0x42, 0x60, 0x82 };
        if (file.size() < 8 + 12 || memcmp(file.data() + file.size() - 12, kIend, 12) != 0) return false;
    } else {
        bool eoi = false;
        const size_t from = file.size() > 1024 ? file.size() - 1024 : 3;
        for (size_t i = from; i + 1 < file.size() && !eoi; ++i) eoi = file[i] == 0xFF && file[i + 1] == 0xD9;
        if (!eoi) return false;
    }

    const HRESULT ci = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    const bool ownInit = ci == S_OK || ci == S_FALSE;
    if (FAILED(ci) && ci != RPC_E_CHANGED_MODE) return false;

    bool ok = false;
    IWICImagingFactory* fac = nullptr;
    IWICStream* stream = nullptr;
    IWICBitmapDecoder* dec = nullptr;
    IWICBitmapFrameDecode* frame = nullptr;
    IWICFormatConverter* conv = nullptr;
    g_wicStep = nullptr; g_wicHr = S_OK;
    auto fails = [](const char* step, HRESULT hr) { if (FAILED(hr)) { g_wicStep = step; g_wicHr = hr; return true; } return false; };
    do {
        // Same Windows 7 story as the PNG decoder below: the Win10 SDK's CLSID_WICImagingFactory is the v2 factory
        // (Windows 8+, Platform Update on 7); plain 7 SP1 has only CLSID_WICImagingFactory1, which decodes exactly
        // the same (v2 adds D2D interop we never use).
        HRESULT hrFac = CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&fac));
        if (hrFac == REGDB_E_CLASSNOTREG)
            hrFac = CoCreateInstance(CLSID_WICImagingFactory1, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&fac));
        if (fails("imaging factory (v2, then v1)", hrFac)) break;
        if (fails("stream", fac->CreateStream(&stream))) break;
        if (fails("stream init", stream->InitializeFromMemory(const_cast<BYTE*>(file.data()), static_cast<DWORD>(file.size())))) break;
        // PNG: with the Windows 10 SDK, CLSID_WICPngDecoder names the v2 decoder, registered on Windows 8+ and on
        // Windows 7 only by the Platform Update (KB2670838). A plain 7 SP1 answers REGDB_E_CLASSNOTREG -- which
        // used to drop EVERY PNG portrait, HD pack included, with a log line blaming the file. The v1 decoder
        // (CLSID_WICPngDecoder1) exists on every Windows since Vista: ask for it when v2 is not there.
        HRESULT hrDec = CoCreateInstance(png ? CLSID_WICPngDecoder : CLSID_WICJpegDecoder, nullptr, CLSCTX_INPROC_SERVER,
                                         IID_PPV_ARGS(&dec));
        if (png && hrDec == REGDB_E_CLASSNOTREG)
            hrDec = CoCreateInstance(CLSID_WICPngDecoder1, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&dec));
        if (fails(png ? "PNG decoder (v2, then v1)" : "JPEG decoder", hrDec)) break;
        if (fails("decoder init", dec->Initialize(stream, WICDecodeMetadataCacheOnDemand))) break;
        if (fails("frame", dec->GetFrame(0, &frame))) break;
        UINT fw = 0, fh = 0;
        if (fails("frame size", frame->GetSize(&fw, &fh))) break;
        if (fw < static_cast<UINT>(kMinSide) || fh < static_cast<UINT>(kMinSide) ||
            fw > static_cast<UINT>(kMaxSide) || fh > static_cast<UINT>(kMaxSide)) break;
        const unsigned long long stride = static_cast<unsigned long long>(fw) * 3ull;
        const unsigned long long bytes = stride * fh;
        if (bytes > 0x7FFFFFFFull) break;
        if (fails("format converter", fac->CreateFormatConverter(&conv))) break;
        if (fails("convert to 24bpp", conv->Initialize(frame, GUID_WICPixelFormat24bppRGB, WICBitmapDitherTypeNone, nullptr, 0.0,
                                                       WICBitmapPaletteTypeCustom))) break;
        try { rgb->resize(static_cast<size_t>(bytes)); } catch (...) { break; }   // keep the cleanup below
        if (fails("copy pixels", conv->CopyPixels(nullptr, static_cast<UINT>(stride), static_cast<UINT>(bytes), rgb->data()))) break;
        *w = static_cast<int>(fw);
        *h = static_cast<int>(fh);
        ok = true;
    } while (false);
    Release(conv); Release(frame); Release(dec); Release(stream); Release(fac);
    if (ownInit) CoUninitialize();
    return ok;
}

// SEH guard in a frame with nothing to unwind (MSVC: no __try beside C++ destructors)
bool DecodeWicGuarded(const std::vector<uint8_t>& file, std::vector<uint8_t>* rgb, int* w, int* h)
{
    __try { return DecodeWic(file, rgb, w, h); }
    __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
}

// 1 = reduced into *out, 0 = use as is, -1 = a fault (a C++ exception lands here too under /EHsc: "no replacement")
int PrereduceGuarded(const uint8_t* rgb, int w, int h, std::vector<uint8_t>* out, int* ow, int* oh)
{
    __try { return portrait_law::Prereduce(rgb, w, h, out, ow, oh) ? 1 : 0; }
    __except (EXCEPTION_EXECUTE_HANDLER) { return -1; }
}

std::shared_ptr<const Image> Decode(const wchar_t* path, uint64_t id, const char* name)
{
    try {
        std::vector<uint8_t> file, rgb;
        int w = 0, h = 0;
        if (!ReadWhole(path, &file)) { Log("[uimod] portrait: %s: replacement %s unreadable or too large -> vanilla\n", name, path); return nullptr; }
        if (!DecodeWicGuarded(file, &rgb, &w, &h)) {
            if (g_wicStep) {    // WIC itself refused (a missing codec on this Windows, not a bad file): say which step
                char why[256];
                _snprintf_s(why, sizeof why, _TRUNCATE, "%s: WIC %s failed (0x%08lX) for replacement", name, g_wicStep,
                            static_cast<unsigned long>(g_wicHr));
                Log("[uimod] portrait: %s %s -> vanilla\n", why, path);
            } else
                Log("[uimod] portrait: %s: replacement %s is not a complete PNG/JPEG of 32..2048 px -> vanilla\n", name, path);
            return nullptr;
        }
        auto img = std::make_shared<Image>();
        std::vector<uint8_t> red;
        int rw = w, rh = h;
        const int pr = PrereduceGuarded(rgb.data(), w, h, &red, &rw, &rh);
        if (pr < 0) { Log("[uimod] portrait: %s: replacement %s could not be reduced -> vanilla\n", name, path); return nullptr; }
        if (pr > 0) img->rgb.swap(red);
        else img->rgb.swap(rgb);
        img->w = rw; img->h = rh; img->id = id;
        char p[MAX_PATH * 2] = {};
        RelPath(path, p, sizeof p);
        char msg[600];
        _snprintf_s(msg, sizeof msg, _TRUNCATE, "[uimod] portrait: %s: replacement %s (%dx%d -> %dx%d)\n",
                    name, p, w, h, rw, rh);
        UimodLog(msg);
        return img;
    } catch (...) {                           // bad_alloc and friends: no replacement, never a crash
        Log("[uimod] portrait: %s: out of memory decoding %s -> vanilla\n", name, path);
        return nullptr;
    }
}

uint64_t Fnv(const void* p, size_t n, uint64_t h = 1469598103934665603ull)
{
    const BYTE* b = static_cast<const BYTE*>(p);
    for (size_t i = 0; i < n; ++i) { h ^= b[i]; h *= 1099511628211ull; }
    return h;
}

// The decoded image of one file, cached on (path, size, mtime); an edited file is decoded again.  Under g_lock
// for the whole of it: a second thread asking for the same file waits for this decode and hits.
std::shared_ptr<const Image> Load(const wchar_t* path, uint64_t size, uint64_t mtime, const char* key, const char* name)
{
    if (!g_cache) return Decode(path, 0, name);   // no cache memory at load: decode uncached (never happens in practice)
    Locked l;
    if (!l.ok) {                              // the lock is orphaned (a thread died holding it): uncached, never a hang
        wchar_t low[MAX_PATH];
        size_t n = 0;
        for (; path[n] && n < MAX_PATH - 1; ++n) low[n] = towlower(path[n]);
        low[n] = 0;
        uint64_t id = Fnv(low, n * sizeof(wchar_t));
        id = Fnv(&size, sizeof size, id);
        id = Fnv(&mtime, sizeof mtime, id);
        return Decode(path, id, name);
    }
    CacheEntry* lru = &g_cache[0];
    for (size_t i = 0; i < kCacheSlots; ++i) {
        CacheEntry& e = g_cache[i];
        if (e.stamp && _wcsicmp(e.path, path) == 0) {
            if (e.size == size && e.mtime == mtime) { e.stamp = ++g_clock; return e.img; }
            lru = &e;                         // same file, changed: replace this entry
            break;
        }
        if (e.stamp < lru->stamp) lru = &e;
    }
    wchar_t low[MAX_PATH];
    size_t n = 0;
    for (; path[n] && n < MAX_PATH - 1; ++n) low[n] = towlower(path[n]);
    low[n] = 0;
    uint64_t id = Fnv(low, n * sizeof(wchar_t));
    id = Fnv(&size, sizeof size, id);
    id = Fnv(&mtime, sizeof mtime, id);
    lru->img.reset();                         // free the evicted image before decoding the next
    std::shared_ptr<const Image> img = Decode(path, id, name);
    memcpy(lru->key, key, sizeof lru->key);
    wcscpy_s(lru->path, path);
    lru->size = size; lru->mtime = mtime;
    lru->img = img;
    lru->stamp = ++g_clock;
    return img;
}

// Append the stems of <dir><sub>*<ext> that Find would accept (no native life, no duplicates) to out.
void ListDir(const wchar_t* dir, const wchar_t* sub, const wchar_t* ext, char (*out)[24], size_t max, size_t* n)
{
    wchar_t pat[MAX_PATH];
    if (!BuildPath(pat, MAX_PATH, dir, sub, "*", ext)) return;
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
        char stem[24];
        size_t len = 0;
        bool ok = true;
        for (; fd.cFileName[len] && fd.cFileName[len] != L'.'; ++len) {
            if (len >= 23 || fd.cFileName[len] > 0x7E) { ok = false; break; }
            stem[len] = static_cast<char>(fd.cFileName[len]);
        }
        if (!ok || len == 0 || _wcsicmp(fd.cFileName + len, ext) != 0) continue;
        stem[len] = 0;
        if (!SafeName(stem) || IsNativeLifeName(stem)) continue;
        bool dup = false;
        for (size_t i = 0; i < *n && !dup; ++i) dup = _stricmp(out[i], stem) == 0;
        if (dup || *n >= max) continue;
        memcpy(out[*n], stem, sizeof stem);
        ++*n;
    } while (FindNextFileW(h, &fd));
    FindClose(h);
}

bool g_enabled = true;                        // Preferences "Enable Custom Portraits"
bool g_usePack = true;                        // Preferences "Use Turovetsky's HD Portrait Pack" (the portraits\hd\ pack)

} // namespace

void SetOptions(bool enabled, bool usePack)
{
    g_enabled = enabled;
    g_usePack = usePack;
}

bool GameDir(wchar_t* out, size_t n) { return GameDirW(out, n); }

void TestHoldLock(int ms, bool die)
{
    InterlockedExchange(&g_testHold, ms);
    const HANDLE h = CreateThread(nullptr, 0, TestHoldThread, reinterpret_cast<LPVOID>(static_cast<INT_PTR>(die ? 1 : 0)), 0, nullptr);
    if (h) { SetThreadPriority(h, THREAD_PRIORITY_BELOW_NORMAL); CloseHandle(h); }
    Sleep(20);                                // let it take the lock
}
void TestOrphanLockHere() { new (std::nothrow) Locked(); }   // (test) a Locked whose destructor never runs (a caught fault)
bool DebugLockDead() { return g_lockDead != 0; }

size_t ListNames(char (*out)[24], size_t max)
{
    size_t n = 0;
    wchar_t dir[MAX_PATH];
    if (!g_enabled || !GameDirW(dir, MAX_PATH)) return 0;
    if (g_usePack) ListDir(dir, L"portraits\\hd\\", L".png", out, max, &n);
    ListDir(dir, L"portraits\\", L".png", out, max, &n);
    ListDir(dir, L"portraits\\", L".jpg", out, max, &n);
    return n;
}

bool PackInstalled()
{
    wchar_t dir[MAX_PATH], path[MAX_PATH];
    if (!GameDirW(dir, MAX_PATH)) return false;
    if (wcslen(dir) + 40 >= MAX_PATH) return false;
    wcscpy_s(path, dir);
    wcscat_s(path, L"portraits\\hd\\pack-manifest.json");   // written by build_portraits_hd.py, shipped with the pack
    uint64_t size = 0, mtime = 0;
    return Stat(path, &size, &mtime);
}

std::shared_ptr<const Image> Find(const char* name)
{
    if (!g_enabled || !SafeName(name)) return nullptr;
    char key[24] = {};
    for (size_t i = 0; name[i] && i < 23; ++i) key[i] = (name[i] >= 'A' && name[i] <= 'Z') ? static_cast<char>(name[i] + 32) : name[i];

    wchar_t dir[MAX_PATH];
    if (!GameDirW(dir, MAX_PATH)) return nullptr;
    // The SETTING decides, not where a file sits: with "Use Turovetsky's HD Portrait Pack" on, the pack's image wins
    // for every name it has; a name the pack lacks (native life, a custom faction, a pack file the player deleted
    // or that will not decode) falls back to the player's own portraits\, then to the game's art.  With it off,
    // only the player's own files count.
    struct Cand { const wchar_t* sub; const wchar_t* ext; };
    static const Cand kPackFirst[] = { { L"portraits\\hd\\", L".png" }, { L"portraits\\", L".png" },
                                       { L"portraits\\", L".jpg" } };
    const Cand* order = g_usePack ? kPackFirst : kPackFirst + 1;
    const size_t n = g_usePack ? 3 : 2;
    for (size_t i = 0; i < n; ++i) {
        wchar_t path[MAX_PATH];
        uint64_t size = 0, mtime = 0;
        if (!BuildPath(path, MAX_PATH, dir, order[i].sub, name, order[i].ext)) continue;
        if (!Stat(path, &size, &mtime)) continue;
        if (std::shared_ptr<const Image> img = Load(path, size, mtime, key, name)) return img;
        // present but unusable (logged once): try the next file
    }
    return nullptr;
}

} // namespace portrait_files
