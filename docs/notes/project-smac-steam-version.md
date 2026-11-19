---
name: project-smac-steam-version
description: Steam SMAC (app 2204130, build 12965079) exes = GOG vanilla code + EA Authenticode sig; Steam lacks GOG's support depot (PRACX, DDrawCompat, ini). Assessed 2026-11-11, not a target yet
type: project
---

Assessed 2026-11-11 (static only, nothing launched). A Steam install (`steamapps\common\Sid Meier's Alpha Centauri\`), appid 2204130, buildid 12965079.

- `terranx.exe` / `terran.exe` = GOG's cc659f / 680490 byte for byte except PE checksum (opt+64), the security-directory entry, and an appended EA Authenticode cert (0x2830 bytes at EOF). Zero those two fields and truncate at the cert offset and the MD5 equals cc659f / 680490. No SteamStub/.bind section. Raw MD5s start d505e007 / 761e6db1.
- All other shipped files are identical to GOG's (except generated .tmp files, and helpx/conceptsx, which our installer patches on GOG).
- Steam does NOT have GOG's support-depot files: terranx_PRACX.exe (2d0b1438), terran_PRACX.exe, prac.dll, prax.dll, pracxpatch.exe, the PRACX uninstaller, DDrawCompat v0.5.4 ddraw.dll. Its `Alpha Centauri.Ini` has DirectDraw=0 (GOG: 1).
- Steam's launch options are terran.exe and terranx.exe only. Steam Cloud syncs `saves\`. Steam's `game.sdb` / `game_add.sdb` (an IgnoreAltTab shim for terran/terranx.exe) are NOT registered on the machine assessed.
- Open (needs a run): whether pracxpatch.exe accepts the signed exe (PRACX patches in place at the same size, so normalized output is probably 2d0b1438), and how the Steam overlay interacts with ClipCursor/fullscreen/movies.

Not a shipping target. Targets are still PRACX and PRACX+Thinker on GOG: [[project-smac-supported-targets]]. Thinker test flow: [[project-smac-thinker-compat]].
