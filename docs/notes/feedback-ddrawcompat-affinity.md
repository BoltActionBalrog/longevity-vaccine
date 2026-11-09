---
name: feedback-ddrawcompat-affinity
description: DDrawCompat (the GOG install's ddraw.dll, v0.5.4) pins the game process to ONE CPU and swallows kernel32 SetProcessAffinityMask process-wide; children inherit the pin -- use NtSetInformationProcess and read the mask back
type: feedback
---

The game process runs on ONE CPU: DDrawCompat's default `[default] CpuAffinity = 1` (with rotation) is applied at its
load, before uimod's PreInit (its log: "Applying configured CPU affinity: 1"). Consequences measured 2026-11-08:
extra worker threads gain nothing (they share that core, below the game thread); every CHILD process inherits the
pin (the update check's Python child: 24-32 s and 3 timeouts in 11 cold launches; 1 s once widened).

DDrawCompat v0.5.4 (Win32/Thread.cpp) HOOKS kernel32 `SetProcessAffinityMask` process-wide (inline jmp) and, while
its CpuAffinity is set, returns TRUE without calling through -- for ANY process handle. A widen through it is a silent
no-op (an audit caught it with a probe that loaded the game's ddraw.dll). ntdll `NtSetInformationProcess(h, 21
/*ProcessAffinityMask*/, &mask, sizeof mask)` is not hooked and is exactly what 32-bit kernel32 calls internally;
`GetProcessAffinityMask` is not faked. update.cpp: create the child CREATE_SUSPENDED, widen via ntdll, read back,
resume, LOG the before/after mask.

**Why:** a plausible API call that "succeeds" inside the game proved nothing; only the read-back did.
**How to apply:** never assume a process-wide Win32 setting call worked inside terranx.exe -- DDrawCompat, PRACX and
Thinker hook kernel32; read the effect back and log it. Leave DDrawCompat's pin on the game itself alone (the maintainer's
decision: it protects old-DirectDraw timing). Related: [[project-smac-portrait-prewarm]], [[feedback-frida-attach-branch-target]].
