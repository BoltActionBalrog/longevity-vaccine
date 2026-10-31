---
name: project-smac-pracx-load-mechanism
description: How prax.dll actually gets loaded into terranx_PRACX.exe — the bootstrap vector for chain-loading our own DLL
type: project
---

Reverse-engineered 2026-06-23 (for the hybrid DLL port, [[project-smac-uimod-dll]]). How PRACX loads:

- **NOT via PE imports** (prax.dll is absent from the import table) and **NOT via a redirected entry
  point** (entry 0x646C9D is plain MSVC `mainCRTStartup`). **No TLS directory** either.
- The loader is a hand-written stub in **`_SELFMOD` at VA `0x668160`** (`PRACX_load_stub`), a clean
  `void(void)`:
  - `call $+5` over an inline `"prax\0"` string @0x668165 (pushes &string), then
    `call ds:[0x669120]` = **LoadLibraryA("prax")** (auto-appends .dll); bail if NULL.
  - `push hMod; push 1; push hMod; call ds:[0x669124]` = **GetProcAddress(hMod, ordinal #1)**; bail if NULL.
  - `call eax` = **prax init(hMod)**, which is **`__stdcall`** (pops its own arg so the following `ret` balances).
  - `ret` @0x668189. **0x66818A onward is zero-filled free space** in _SELFMOD.
- Trigger: the stub is **entry[0] of a startup function-pointer table at `.data:0x682000`**
  (entry[0]=0x668160, entries[1..]=game init funcs 0x402f10/0x40444x…), walked early in process init —
  so PRACX loads before the game proper.
- IAT slots: `0x669120`=LoadLibraryA, `0x669124`=GetProcAddress (KERNEL32). Symbols recorded in
  terranx.h (PRACX bootstrap section).

**Why this matters:** the cleanest way to load OUR `uimod.dll` strictly AFTER prax.dll (last-writer) is
to **chain off this stub** — replace its final `ret` (0x668189, `c3` + zero padding) with `jmp` into a
new pcave2 thunk that mirrors the stub for "uimod", then rets. Runs immediately after PRACX init
returns, before the game proceeds. Tiny (5-byte hook + ~30-byte thunk), MD5-lockable, fits the existing
patches.yaml/regression harness. uimod.dll must live in the game dir (next to prax.dll) and export a
`__stdcall(HMODULE)` init (ordinal 1 or by name). All addresses pinned to MD5 2d0b1438.
