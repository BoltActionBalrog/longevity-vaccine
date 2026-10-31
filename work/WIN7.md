# Windows 7 support — assessment and verification checklist

Status 2026-10-31: the two measured blockers are fixed in code and tested on Windows 11; the in-game
pass on a real Windows 7 SP1 machine has NOT happened (no VM available). Until it has, Windows 7 is
"built for, not confirmed" and gets no CHANGELOG line.

## What is measured (PE import tables, this machine; `work\scripts` has no tool for it — a one-off pefile dump)

| Binary | OS/subsystem field | Newest API family imported | Verdict |
|---|---|---|---|
| `uimod.dll` | 6.0 | Vista (SRW locks, `GetTickCount64`, `InitializeProcThreadAttributeList`, job objects); static CRT (`/MT`), no vcruntime/ucrt import; `SetProcessDPIAware`, D3D11 and the display-mode calls are `GetProcAddress`-bound | loads on 7 SP1 |
| ffmpeg ×5 (`avcodec-62`, `avformat-62`, `avutil-60`, `swscale-9`, `swresample-6`) | 6.0 | Vista (`InitOnce*`, condition variables, `bcrypt` in avutil) | load on 7 SP1 |
| `prax.dll` | 5.1 | XP | fine |
| DDrawCompat `ddraw.dll` (GOG) | 6.0 | Vista (`D3DKMT*`, `RegCreateKeyTransacted`, `GetLocaleInfoEx`); its README: Vista/7+ with a WDDM driver and Desktop Composition ON | fine on 7 with Aero |
| `terranx.exe` | 4.0 | — | GOG supports 7+ |

So the DLL set itself never was the Windows 7 blocker. The blockers were:

**(a) Movie sound.** `uimod.dll` has no `xaudio2_9.dll` import; the SDK header's inline `XAudio2Create`
did `LoadLibraryEx(L"xaudio2_9.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32)` at the first movie. Windows 7 /
8 / 8.1 have no `xaudio2_9.dll`, and on 7 the flag itself needs KB2533623: silent movies, nothing logged.
Fixed in `src\uimod\src\movieaudio.h`: the system DLL is opened by full path and kept loaded; without it
the sound goes through winmm `waveOut` (every Windows). `[UIMod] MovieAudio=auto|xaudio2|waveout|off`
in `Alpha Centauri.ini` forces a backend; `uimod.log` gets one line at start ("movie audio: …") and
again whenever the answer changes. Decision 2026-10-31: no XAudio2Redist DLL (proprietary licence, one
more DLL to fail); waveOut only. Harness: `work\tests\test_movie_audio.py` walks every path on the development machine,
including the Windows 7 one (loader miss → waveOut) by pointing the loader at a missing file.

**(b) Installer + resident updater.** Both run on the bundled CPython 3.12, which dies in the loader
below Windows 8.1. The payload now carries CPython 3.8.10 (32-bit embeddable, the last CPython that runs
on 7; EOL 2024) as `tools\python38`, with the app-local UCRT from the Windows SDK so a Windows 7 that
never took KB2999226 can start it (KB2533623 stays required: CPython 3.8's extension loader uses the
`LOAD_LIBRARY_SEARCH_*` flags it adds; `run-install.bat` probes for it and names the update). The SAME
scripts run on both; `work\tests\test_runtime38.py` compiles
every shipped script with 3.8 and runs the Ed25519 known answer under it; `build_runtime.py --verify`
runs the whole installer flow under 3.8 too. Three places pick the interpreter by Windows version:
`run-install.bat` (`ver` 6.1/6.2), `bootstrap.py` (the running interpreter's family), and the DLL's
update check (`lvupd::RuntimeExeRel` fed by `RtlGetVersion`, because `GetVersionEx` lies to the
unmanifested `terranx.exe`). Fetch: `py work\scripts\fetch_python38.py` (size + python.org MD5 + pinned
SHA256; the 2021 OpenPGP signature is uncheckable — its signing subkey is gone from the published key).

## What only a Windows 7 SP1 machine can prove

Set-up: Windows 7 SP1 x64 or x86, fully updated through 2020-01. The installer path must ALSO be tried on
(i) SP1 + KB2533623 only (no KB2999226: the app-local UCRT must carry the 3.8 interpreter) and (ii) a bare SP1
with neither (CPython 3.8's own extension loader needs KB2533623; `run-install.bat` must stop with the
"missing update KB2533623" screen, not a Python traceback or a loader box).
GOG Planetary Pack installed with its DDrawCompat `ddraw.dll`; Aero (Desktop Composition) on; a WDDM
driver (any VM GPU driver that gives Aero). Audio device present.

1. **Install.** Extract `LongevityVaccine_<ver>.zip`, run `INSTALL.bat`. Expect: the console shows the
   installer running (not a loader "api-ms-win-core-path-l1-1-0.dll is missing" box); `scripts\run-install.bat`
   picked `tools\python38\python.exe` (add `echo %PY%` under a debug flag or read the receipt's interpreter
   line); install reports success; `terranx_PRACX.exe` + `uimod.dll` + ffmpeg DLLs land as on Windows 11.
   Repeat on image (i): the app-local UCRT must carry the interpreter; no "api-ms-win-crt-runtime-l1-1-0.dll" box.
   On image (ii): the KB2533623 screen, exit code 9, nothing changed on disk.
2. **DLL load.** Start the game. `uimod.log` appears beside `uimod.dll` with the Init lines and
   `movie audio: waveOut -- C:\Windows\system32\xaudio2_9.dll failed to load (error 126; normal on Windows 7/8.1)`.
   No "entry point not found" dialog (that would be a post-Vista API slipping into an import table — re-run the
   pefile dump against the shipped set).
3. **Movies.** Intro movie plays inside the window WITH sound, in sync within ~100 ms (waveOut adds latency
   over XAudio2); skip (Esc/click) works; the post-movie caption draws; the game continues. Then
   `[UIMod] MovieAudio=xaudio2` → `uimod.log` says NONE and the movie is silent but plays; `off` → silent;
   remove the key → waveOut again. HD pack installed: same with the `movies\hd\*.mp4`.
4. **Update check.** On a game start, `LongevityMods\logs\check.log` shows the check ran under
   `tools\python38\python.exe` (the DLL's `RuntimeExeRel(6,1)`); a test manifest offering a newer version
   (`--lv-manifest`) shows the update popup; accepting it runs `run-install.bat --update` → bootstrap →
   generation-2 handover under 3.8 → new payload installed. (The Windows 7 copy must keep choosing 3.8 after
   the update: `bootstrap.payload_python` picks by the running interpreter's family.)
5. **Everything else.** UI scaling at the VM's resolution (1920×1080 at least), Preferences page, the
   Fullscreen/Borderless modes (DDrawCompat needs Aero: Basic theme must not be forced), Thinker
   (if that combination is wanted on 7 — Thinker's own requirements first).
6. **Uninstall** (`run-install.bat --uninstall`) under 3.8 restores the vanilla set.

Record outcomes in the maintainer's work log (Win7 section) and give the CHANGELOG its one line only after 1–4 pass.

## Known limits

- CPython 3.8.10 and its OpenSSL 1.1.1k get no security fixes. The installer's trust is the Ed25519 manifest
  signature, not TLS; TLS is defence in depth. Windows 7 itself is out of support since 2020.
- Windows 8.0 (6.2) takes the same 3.8 path and is otherwise untested; 8.1 and up are unchanged.
- The Thinker + PRACX workspace and the live install run on Windows 11; nothing there exercises these paths.
