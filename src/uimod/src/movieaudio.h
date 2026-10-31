#pragma once
// Movie audio output for the in-process cinematic player (movie.cpp): XAudio2 where the system has
// it, winmm waveOut where it does not. Header-only so the test harness (work\tests\movie_audio)
// compiles the very code the DLL runs.
//
// WHY A LOADER OF OUR OWN. The Windows 10 SDK's inline XAudio2Create does
//   LoadLibraryEx(L"xaudio2_9.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32)
// at the first movie. Windows 7 / 8 / 8.1 ship no xaudio2_9.dll, and on Windows 7 the flag itself
// needs KB2533623 -- so there the call failed twice over and every movie played silent, with nothing
// in uimod.log to say so. Here the DLL is opened by its full System32 path (no search-order games,
// no flag), kept loaded for the life of the process (Microsoft: unloading XAudio2 while its worker
// thread still runs can crash), and when it is not there the sound goes through waveOut, which every
// Windows has and winmm.dll (already imported) provides.
//
// [UIMod] MovieAudio= in Alpha Centauri.ini picks the backend: auto (default: XAudio2, else
// waveOut) | xaudio2 | waveout | off. A player with a broken XAudio2 install has a one-line
// workaround; the harness forces each path on a machine that has them all.
//
// Fits the "DLLs that fail to load must be reported" plan: Probe() answers at Init, the choice is
// logged once per process by the caller, and a failure disables movie SOUND only -- the video plays.

#include <windows.h>
#include <mmsystem.h>
#include <xaudio2.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

namespace movieaudio {

enum Mode { kAuto = 0, kXAudio2, kWaveOut, kOff };
enum Backend { kNone = 0, kBackendXAudio2, kBackendWaveOut };

inline bool EqualNoCase(const char* a, const char* b)
{
    for (;; ++a, ++b) {
        const int ca = (*a >= 'A' && *a <= 'Z') ? *a + 32 : *a;
        const int cb = (*b >= 'A' && *b <= 'Z') ? *b + 32 : *b;
        if (ca != cb) return false;
        if (!ca) return true;
    }
}

// An unknown word is `auto`: a typo in the ini must never silence the movies.
inline Mode ParseMode(const char* s)
{
    if (!s) return kAuto;
    if (EqualNoCase(s, "xaudio2")) return kXAudio2;
    if (EqualNoCase(s, "waveout")) return kWaveOut;
    if (EqualNoCase(s, "off") || EqualNoCase(s, "0") || EqualNoCase(s, "none")) return kOff;
    return kAuto;
}

inline Mode ModeFromIni(const char* iniPath)
{
    char buf[32];
    GetPrivateProfileStringA("UIMod", "MovieAudio", "auto", buf, sizeof buf, iniPath);
    return ParseMode(buf);
}

inline const char* ModeName(Mode m)
{
    switch (m) {
    case kXAudio2: return "xaudio2";
    case kWaveOut: return "waveout";
    case kOff:     return "off";
    default:       return "auto";
    }
}

inline const char* BackendName(Backend b)
{
    switch (b) {
    case kBackendXAudio2: return "XAudio2";
    case kBackendWaveOut: return "waveOut";
    default:              return "none";
    }
}

// ---- XAudio2, resolved once per process -------------------------------------------------------

struct XAudio2Module {
    typedef HRESULT (__stdcall* CreateWithVersionFn)(IXAudio2**, UINT32, XAUDIO2_PROCESSOR, DWORD);
    typedef HRESULT (__stdcall* CreateFn)(IXAudio2**, UINT32, XAUDIO2_PROCESSOR);
    bool                tried       = false;
    HMODULE             dll         = nullptr;     // never freed (see the header comment)
    CreateWithVersionFn withVersion = nullptr;
    CreateFn            create      = nullptr;
    DWORD               error       = 0;           // GetLastError of the step that failed
    wchar_t             path[MAX_PATH + 32] = {};
    bool Usable() const { return dll && (withVersion || create); }
};

// Test seam: the harness points this at a file that does not exist to walk the Windows 7 path
// (no xaudio2_9.dll) on a machine that has one. Must be set before the first Module() call.
inline const wchar_t*& OverridePathForTest()
{
    static const wchar_t* p = nullptr;
    return p;
}

inline XAudio2Module& Module()
{
    static XAudio2Module m;
    if (m.tried) return m;
    m.tried = true;
    if (const wchar_t* ov = OverridePathForTest()) {
        lstrcpynW(m.path, ov, MAX_PATH + 32);
    } else {
        const UINT n = GetSystemDirectoryW(m.path, MAX_PATH);
        if (n == 0 || n >= MAX_PATH) { m.error = GetLastError(); if (!m.error) m.error = ERROR_BUFFER_OVERFLOW; return m; }
        lstrcatW(m.path, L"\\xaudio2_9.dll");
    }
    m.dll = LoadLibraryW(m.path);
    if (!m.dll) { m.error = GetLastError(); return m; }
    // Same preference as the SDK inline: the RS5+ entry that is told which OS we were built for,
    // else the classic one.
    m.withVersion = reinterpret_cast<XAudio2Module::CreateWithVersionFn>(
        reinterpret_cast<void*>(GetProcAddress(m.dll, "XAudio2CreateWithVersionInfo")));
    if (!m.withVersion) {
        m.create = reinterpret_cast<XAudio2Module::CreateFn>(
            reinterpret_cast<void*>(GetProcAddress(m.dll, "XAudio2Create")));
        if (!m.create) m.error = GetLastError();
    }
    return m;
}

inline HRESULT CreateEngine(IXAudio2** out)
{
    XAudio2Module& m = Module();
    if (!m.Usable()) return HRESULT_FROM_WIN32(m.error ? m.error : ERROR_MOD_NOT_FOUND);
    if (m.withVersion) return m.withVersion(out, 0, XAUDIO2_DEFAULT_PROCESSOR, NTDDI_VERSION);
    const HRESULT hr = m.create(out, 0, XAUDIO2_DEFAULT_PROCESSOR);
    // Windows 10 before 1903: XAudio2Create does not know XAUDIO2_USE_DEFAULT_PROCESSOR (0) and
    // refuses it; the pre-RS5 default was Processor1.
    if (FAILED(hr) && XAUDIO2_DEFAULT_PROCESSOR != Processor1) return m.create(out, 0, Processor1);
    return hr;
}

// ---- the sink the decode loop feeds -----------------------------------------------------------

// Submitted buffers stay the CALLER's and must outlive Stop() (movie.cpp frees them after it, as it
// did for XAudio2: the device reads them asynchronously).
struct Sink {
    virtual ~Sink() {}
    virtual Backend Kind() const = 0;
    virtual bool Submit(const uint8_t* data, uint32_t bytes) = 0;   // false = refused; the caller frees, Dropped() counts
    virtual void Stop() = 0;      // stops at once and releases the device; idempotent
    unsigned Dropped() const { return dropped_; }
protected:
    unsigned dropped_ = 0;
};

inline WAVEFORMATEX Pcm16Stereo(int rate)
{
    WAVEFORMATEX wfx{};
    wfx.wFormatTag = WAVE_FORMAT_PCM; wfx.nChannels = 2;
    wfx.nSamplesPerSec = static_cast<DWORD>(rate); wfx.wBitsPerSample = 16;
    wfx.nBlockAlign = static_cast<WORD>(wfx.nChannels * wfx.wBitsPerSample / 8);
    wfx.nAvgBytesPerSec = wfx.nSamplesPerSec * wfx.nBlockAlign;
    return wfx;
}

class XAudio2Sink : public Sink {
public:
    // false (and everything released) when any step fails: the engine, the mastering voice, the
    // source voice -- a mastering voice fails with no audio device, which is not a Windows 7 matter.
    bool Open(int rate, HRESULT* why)
    {
        // XAudio2 2.9 wants COM up on the calling thread BEFORE its first call (CO_E_NOTINITIALIZED
        // otherwise, and the harness showed a retry after initialising still fails: the first call is
        // what counts), in the MULTITHREADED apartment. So: ask first. S_OK = the thread had none and it is
        // ours for the movie's duration, given back at Stop(); S_FALSE = already MTA, balance the count at
        // once; RPC_E_CHANGED_MODE = the thread is STA already (the game thread with COM from elsewhere, as
        // the old code relied on) -- leave it. (A later apartment-threaded CoInitializeEx on a thread we
        // made MTA would see RPC_E_CHANGED_MODE only while a movie plays, and no portrait loads during one.)
        const HRESULT co = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
        if (co == S_OK) coOurs_ = true;
        else if (co == S_FALSE) CoUninitialize();
        HRESULT hr = CreateEngine(&xa_);
        if (SUCCEEDED(hr)) hr = xa_->CreateMasteringVoice(&mv_);
        if (SUCCEEDED(hr)) {
            const WAVEFORMATEX wfx = Pcm16Stereo(rate);
            hr = xa_->CreateSourceVoice(&sv_, &wfx);
        }
        if (SUCCEEDED(hr)) hr = sv_->Start(0);
        if (why) *why = hr;
        if (FAILED(hr)) { Stop(); return false; }
        return true;
    }
    Backend Kind() const override { return kBackendXAudio2; }
    bool Submit(const uint8_t* data, uint32_t bytes) override
    {
        if (!sv_) { ++dropped_; return false; }
        XAUDIO2_BUFFER xb{};
        xb.AudioBytes = bytes;
        xb.pAudioData = data;
        if (FAILED(sv_->SubmitSourceBuffer(&xb))) { ++dropped_; return false; }
        return true;
    }
    void Stop() override
    {
        if (sv_) { sv_->Stop(0); sv_->DestroyVoice(); sv_ = nullptr; }
        if (mv_) { mv_->DestroyVoice(); mv_ = nullptr; }
        if (xa_) { xa_->Release(); xa_ = nullptr; }
        if (coOurs_) { CoUninitialize(); coOurs_ = false; }
    }
    ~XAudio2Sink() override { Stop(); }
private:
    bool                    coOurs_ = false;
    IXAudio2*               xa_ = nullptr;
    IXAudio2MasteringVoice* mv_ = nullptr;
    IXAudio2SourceVoice*    sv_ = nullptr;
};

class WaveOutSink : public Sink {
public:
    bool Open(int rate, MMRESULT* why)
    {
        const WAVEFORMATEX wfx = Pcm16Stereo(rate);
        const MMRESULT r = waveOutOpen(&h_, WAVE_MAPPER, &wfx, 0, 0, CALLBACK_NULL);
        if (why) *why = r;
        if (r != MMSYSERR_NOERROR) { h_ = nullptr; return false; }
        return true;
    }
    Backend Kind() const override { return kBackendWaveOut; }
    // One WAVEHDR per buffer, kept until Stop(): waveOutUnprepareHeader is only legal once the
    // device is done with it, and after waveOutReset every header is.
    bool Submit(const uint8_t* data, uint32_t bytes) override
    {
        if (!h_ || !bytes) { ++dropped_; return false; }
        WAVEHDR* w = new WAVEHDR();
        memset(w, 0, sizeof *w);
        w->lpData = reinterpret_cast<LPSTR>(const_cast<uint8_t*>(data));
        w->dwBufferLength = bytes;
        if (waveOutPrepareHeader(h_, w, sizeof *w) != MMSYSERR_NOERROR) { delete w; ++dropped_; return false; }
        if (waveOutWrite(h_, w, sizeof *w) != MMSYSERR_NOERROR) {
            waveOutUnprepareHeader(h_, w, sizeof *w);
            delete w;
            ++dropped_;
            return false;
        }
        hdrs_.push_back(w);
        return true;
    }
    size_t Queued() const { return hdrs_.size(); }
    void Stop() override
    {
        if (!h_) return;
        // waveOutReset returns every pending header marked done -- the one legal point to unprepare them.
        // If the device is gone and Reset fails, the headers may still be the driver's: leak them (and the
        // handle) rather than free memory a driver thread can touch; the caller's buffers outlive us anyway.
        if (waveOutReset(h_) == MMSYSERR_NOERROR) {
            for (WAVEHDR* w : hdrs_) {
                waveOutUnprepareHeader(h_, w, sizeof *w);
                delete w;
            }
            waveOutClose(h_);
        }
        hdrs_.clear();
        h_ = nullptr;
    }
    ~WaveOutSink() override { Stop(); }
private:
    HWAVEOUT h_ = nullptr;
    std::vector<WAVEHDR*> hdrs_;
};

// What Open() did and why, for the log: "XAudio2" / "waveOut (xaudio2_9.dll: error 126)" / ...
struct Verdict {
    Backend backend = kNone;
    char    why[160] = {};
};

// The sink for `mode`, or nullptr (silent movie) with `v.why` saying what happened.
//   auto    : XAudio2, else waveOut, else none
//   xaudio2 : XAudio2 or none          waveout : waveOut or none          off : none
inline Sink* Open(Mode mode, int rate, Verdict& v)
{
    v = Verdict();
    if (mode == kOff) { _snprintf_s(v.why, sizeof v.why, _TRUNCATE, "off ([UIMod] MovieAudio=off)"); return nullptr; }

    HRESULT xaErr = S_OK;
    if (mode == kAuto || mode == kXAudio2) {
        XAudio2Sink* s = new XAudio2Sink();
        if (s->Open(rate, &xaErr)) { v.backend = kBackendXAudio2; _snprintf_s(v.why, sizeof v.why, _TRUNCATE, "XAudio2 (%ls)", Module().path); return s; }
        delete s;
        if (mode == kXAudio2) {
            _snprintf_s(v.why, sizeof v.why, _TRUNCATE, "none: XAudio2 forced ([UIMod] MovieAudio=xaudio2) and it failed (%ls: 0x%08lX)",
                        Module().path, static_cast<unsigned long>(xaErr));
            return nullptr;
        }
    }
    MMRESULT woErr = MMSYSERR_NOERROR;
    WaveOutSink* w = new WaveOutSink();
    if (w->Open(rate, &woErr)) {
        v.backend = kBackendWaveOut;
        if (mode == kWaveOut) _snprintf_s(v.why, sizeof v.why, _TRUNCATE, "waveOut ([UIMod] MovieAudio=waveout)");
        else _snprintf_s(v.why, sizeof v.why, _TRUNCATE, "waveOut (XAudio2 unavailable: %ls 0x%08lX)", Module().path, static_cast<unsigned long>(xaErr));
        return w;
    }
    delete w;
    if (mode == kWaveOut) _snprintf_s(v.why, sizeof v.why, _TRUNCATE, "none: waveOut forced ([UIMod] MovieAudio=waveout) and waveOutOpen failed (%u)", woErr);
    else _snprintf_s(v.why, sizeof v.why, _TRUNCATE, "none: XAudio2 unavailable (%ls 0x%08lX) and waveOutOpen failed (%u)",
                     Module().path, static_cast<unsigned long>(xaErr), woErr);
    return nullptr;
}

// At Init, before any movie: does this Windows have XAudio2, and what will the movies use?
// Loads the DLL (kept, see above) but creates no engine -- that needs an audio device and belongs
// to the movie. `out` gets one log-ready line.
inline Backend Probe(Mode mode, char* out, size_t cap)
{
    const XAudio2Module& m = Module();
    const bool devices = waveOutGetNumDevs() > 0;
    Backend b = kNone;
    if (mode == kOff) {
        _snprintf_s(out, cap, _TRUNCATE, "movie audio: off ([UIMod] MovieAudio=off)");
    } else if (mode != kWaveOut && m.Usable()) {
        b = kBackendXAudio2;
        _snprintf_s(out, cap, _TRUNCATE, "movie audio: XAudio2 (%ls)%s", m.path, devices ? "" : " -- no audio device present");
    } else if (mode == kXAudio2) {
        _snprintf_s(out, cap, _TRUNCATE, "movie audio: NONE -- [UIMod] MovieAudio=xaudio2 but %ls failed to load (error %lu); movies will play silent",
                    m.path, m.error);
    } else {
        b = kBackendWaveOut;
        if (mode == kWaveOut) _snprintf_s(out, cap, _TRUNCATE, "movie audio: waveOut ([UIMod] MovieAudio=waveout)%s", devices ? "" : " -- no audio device present");
        else _snprintf_s(out, cap, _TRUNCATE, "movie audio: waveOut -- %ls failed to load (error %lu; normal on Windows 7/8.1)%s",
                         m.path, m.error, devices ? "" : " -- no audio device present");
    }
    return b;
}

} // namespace movieaudio
