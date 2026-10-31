---
name: project-smac-win7-and-dll-load-robustness
description: Windows 7 support + DLL-load-failure reporting: user decisions 2026-10-31 (waveOut only, one archive with a CPython 3.8.10 second runtime, MovieAudio ini key, no VM yet); built on branch worktree-win7-support (not deployed); what still needs a Win7 machine; bootstrap.py/release.py edits pending the installer session's merge
type: project
---

**Canonical text:** the maintainer's work log section "ROBUSTNESS: DLL LOAD FAILURES + WINDOWS 7"; assessment + VM
checklist in `work\WIN7.md`. Both items were worked 2026-10-31 in a git worktree of D:\SmacxUi on branch
`worktree-win7-support`, NOT merged, NOT deployed anywhere.

**Facts that overturned the 2026-10-28 note (measured with pefile, not prose):**
- uimod.dll never imported xaudio2_9.dll: the Win10 SDK header's inline `XAudio2Create` LoadLibraryEx'd it with
  `LOAD_LIBRARY_SEARCH_SYSTEM32` at the first movie (that flag itself needs KB2533623 on Win7). So the DLL set loads on
  7 SP1; only movie SOUND and the Python runtime were blockers.
- The 2026-10-28 boot guard (thunk_uimod_preload v2) already MessageBoxes + exits when uimod.dll fails to load, so a
  quarantined codec DLL made the game NOT START (naming uimod.dll, the wrong file) -- not "plain PRACX silently".
- XAudio2 2.9 returns CO_E_NOTINITIALIZED on a thread without COM; the old code worked only because the game thread
  had COM from elsewhere. The harness caught it; movieaudio.h initialises COM only on that error and gives it back.
- The installer imports third-party `pefile` + `yaml` (from tools\python's site-packages); an embeddable has none, so
  the 3.8 runtime stages the pure-Python tops of the 3.12 plan (PyYAML's pure parser; apply_patches falls back from
  CSafeLoader). The 3.8.10 .asc is uncheckable: its signing subkey is absent from every published copy of the RM key.
- CPython 3.8 itself needs KB2533623 (its .pyd loader uses LOAD_LIBRARY_SEARCH_* flags): Windows 7 SP1 + that 2011
  update is the floor; the app-local UCRT covers KB2999226 only. run-install.bat probes `import ctypes` under 3.8 and
  names the KB when it fails.

**User decisions 2026-10-31:** (a) waveOut fallback only, no XAudio2Redist (licence + one more DLL); (b) one archive
with tools\python38 (CPython 3.8.10 embeddable + app-local UCRT from the SDK Redist), same scripts; (c) shipped
`[UIMod] MovieAudio=auto|xaudio2|waveout|off`; (d) no Win7 VM for now -> "built for, not confirmed", no CHANGELOG line.

**Done after the installer merge (2026-10-31):** bootstrap.py `payload_python`/`runtime_exe_rel` (family of the
running interpreter; REFUSES an absent interpreter -- the old sys.executable fallback ran gen 2 out of the directory
it replaces), PAYLOAD carries tools/python38, is_usable needs the interpreter this Windows runs; release.py RUNTIMES
ships both, runtime_root refuses without runtime38, runtime_stale names the stale one. The branch was rebased onto master before these edits. `tools\python38` is gitignored like tools\python: every clone runs fetch_python38.py once.
Still open: DLL-load item (2) (installer `--check` "mod loaded" line, DLL hash verification by the updater, a
Preferences status row -- the row budget on the Longevity page is full, 15/15, so a row needs a layout decision) and
(3) signing (options written in the maintainer's work log); the maintainer's in-game checks (renamed codec DLL in the Thinker workspace;
MovieAudio=waveout at 4K) and the Windows 7 machine.

**2026-10-31 close-out:** committed a5f29ab (+ the explicit "VERIFY THE WINDOWS 7 WORK" action item) on
`worktree-win7-support`, pushed to origin; merged as e551e6b (+ d650b58) on master; D:\SmacxThinker\game runs master's
rebuild 3c1685d7 (uimod.dll.e3f29e9e.bak beside it); master was pushed the same day. The merged
run-install.bat checked out LF once (autocrlf; blob is CRLF) -- test_run_install_bat_is_crlf catches it. Windows 7 stays "built for, not confirmed" until a
Windows 7 machine runs WIN7.md's checklist; no CHANGELOG line until then.

**Why:** the maintainer wants Windows 7 players served and no silent mod loss; it was relayed that the DLL-load
item is this branch's too.

Related: [[project-smac-movie-player]], [[project-smac-update-checker]], (a private note),
(a private note).
