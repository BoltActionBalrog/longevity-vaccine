// Offline drive of the movie-audio backend (src\uimod\src\movieaudio.h) -- no game, no decoder.
// Usage:
//   audio_harness parse <word>                 -> mode=<auto|xaudio2|waveout|off>
//   audio_harness ini <ini-path>               -> mode=<...>            ([UIMod] MovieAudio= of that file)
//   audio_harness probe [no-xaudio2]           -> probe=<XAudio2|waveOut|none> line=<the log line>
//   audio_harness play <mode> <ms> [stop-after=<ms>] [no-xaudio2] -> backend=<...> submitted=<n> dropped=<n> why=<verdict>
//   audio_harness abuse <mode> [no-xaudio2]        -> abuse=ok   (Stop twice, Submit after Stop, delete without Stop)
// `no-xaudio2` points the loader at a file that does not exist: the Windows 7 path (no
// xaudio2_9.dll) walked on a machine that has one. `play` pushes <ms> of silence at 22050 Hz
// stereo s16 in ~46 ms buffers (the decoder's packet size), waits it out -- or only `stop-after`
// ms, the Esc/skip path: Stop() with most of the queue still pending, then the buffers freed --
// and stops.
#include <windows.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "../../../src/uimod/src/movieaudio.h"

static bool HasArg(int argc, char** argv, const char* w)
{
    for (int i = 1; i < argc; ++i) if (!strcmp(argv[i], w)) return true;
    return false;
}

int main(int argc, char** argv)
{
    if (argc < 2) { fprintf(stderr, "args\n"); return 2; }
    if (HasArg(argc, argv, "no-xaudio2"))
        movieaudio::OverridePathForTest() = L"C:\\no-such-dir-4f2a\\xaudio2_9.dll";
    // com=sta | com=mta: the calling thread already has COM, as the game thread does (the old code never
    // initialised it and worked). The sink must then leave the apartment exactly as it found it.
    DWORD comMode = 0; bool comPre = false;
    if (HasArg(argc, argv, "com=sta")) { comMode = COINIT_APARTMENTTHREADED; comPre = true; }
    if (HasArg(argc, argv, "com=mta")) { comMode = COINIT_MULTITHREADED; comPre = true; }
    if (comPre && FAILED(CoInitializeEx(nullptr, comMode))) { printf("com=initfail\n"); return 0; }

    const char* cmd = argv[1];
    if (!strcmp(cmd, "parse") && argc >= 3) {
        printf("mode=%s\n", movieaudio::ModeName(movieaudio::ParseMode(argv[2])));
        return 0;
    }
    if (!strcmp(cmd, "ini") && argc >= 3) {
        printf("mode=%s\n", movieaudio::ModeName(movieaudio::ModeFromIni(argv[2])));
        return 0;
    }
    if (!strcmp(cmd, "probe")) {
        char line[320];
        const movieaudio::Backend b = movieaudio::Probe(movieaudio::kAuto, line, sizeof line);
        printf("probe=%s line=%s\n", movieaudio::BackendName(b), line);
        return 0;
    }
    if (!strcmp(cmd, "play") && argc >= 4) {
        const movieaudio::Mode mode = movieaudio::ParseMode(argv[2]);
        const int ms = atoi(argv[3]);
        int stopAfter = -1;
        for (int i = 4; i < argc; ++i)
            if (!strncmp(argv[i], "stop-after=", 11)) stopAfter = atoi(argv[i] + 11);
        const int rate = 22050;
        if (waveOutGetNumDevs() == 0) { printf("nodevice\n"); return 0; }
        movieaudio::Verdict v;
        movieaudio::Sink* sink = movieaudio::Open(mode, rate, v);
        int submitted = 0; unsigned dropped = 0;
        std::vector<uint8_t*> bufs;
        if (sink) {
            const uint32_t chunk = 1024 * 4;                    // 1024 frames of s16 stereo = ~46 ms
            const uint32_t total = static_cast<uint32_t>(ms) * rate / 1000 * 4;
            for (uint32_t done = 0; done < total; done += chunk) {
                uint8_t* b = static_cast<uint8_t*>(calloc(chunk, 1));
                if (sink->Submit(b, chunk)) { bufs.push_back(b); ++submitted; }
                else free(b);
            }
            Sleep(static_cast<DWORD>(stopAfter >= 0 ? stopAfter : ms + 100));
            dropped = sink->Dropped();
            sink->Stop();                                       // movie.cpp's order: Stop, delete, then free
            delete sink;
        }
        for (uint8_t* b : bufs) { memset(b, 0xCD, 4096); free(b); }   // a driver still reading would read junk, not silence
        const char* com = "n/a";
        if (comPre) {
            // Still initialised in OUR mode exactly once? A second init of the same mode answers S_FALSE
            // (count 1 -> 2); S_OK would mean the sink tore our apartment down, RPC_E_CHANGED_MODE that it
            // left another mode behind.
            const HRESULT again = CoInitializeEx(nullptr, comMode);
            com = again == S_FALSE ? "kept" : again == S_OK ? "lost" : "changed";
            if (SUCCEEDED(again)) CoUninitialize();
            CoUninitialize();
        }
        printf("backend=%s submitted=%d dropped=%u com=%s why=%s\n", movieaudio::BackendName(v.backend), submitted, dropped, com, v.why);
        return 0;
    }
    if (!strcmp(cmd, "abuse") && argc >= 3) {
        const movieaudio::Mode mode = movieaudio::ParseMode(argv[2]);
        if (waveOutGetNumDevs() == 0) { printf("nodevice\n"); return 0; }
        movieaudio::Verdict v;
        std::vector<uint8_t*> bufs;
        movieaudio::Sink* s = movieaudio::Open(mode, 22050, v);
        if (!s) { printf("abuse=noopen why=%s\n", v.why); return 0; }
        for (int i = 0; i < 3; ++i) { uint8_t* b = static_cast<uint8_t*>(calloc(4096, 1)); if (s->Submit(b, 4096)) bufs.push_back(b); else free(b); }
        s->Stop();
        s->Stop();                                              // idempotent
        uint8_t* late = static_cast<uint8_t*>(calloc(4096, 1));
        const bool lateOk = s->Submit(late, 4096);              // after Stop: refused, counted
        free(late);
        const unsigned dropped = s->Dropped();
        delete s;
        for (uint8_t* b : bufs) free(b);
        movieaudio::Sink* t = movieaudio::Open(mode, 22050, v);  // delete without Stop: the destructor stops
        if (t) { uint8_t* b = static_cast<uint8_t*>(calloc(4096, 1)); t->Submit(b, 4096); delete t; free(b); }
        printf("abuse=%s late=%d dropped=%u\n", (!lateOk && dropped == 1) ? "ok" : "bad", lateOk ? 1 : 0, dropped);
        return 0;
    }
    fprintf(stderr, "bad args\n");
    return 2;
}
