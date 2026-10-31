---
name: feedback-frida-readcstring-fixed-buffers
description: Frida readCString(n) on a fixed-size C buffer returns ALL n bytes (stale garbage after the NUL); feeding that to an engine strcpy (Font_init LOGFONT) smashed its stack frame -> "regression" that was really a no-op proto
type: feedback
---

`ptr.readCString(n)` does NOT stop at the first NUL — it returns n bytes (garbage after the NUL decodes to U+FFFD,
which `Memory.allocUtf8String` re-encodes as 3 bytes each). Passing such a string to `Font_init` (0x618F40, which
`strcpy`s the name into a 32-byte stack LOGFONT) overwrote its return address (AV at 0xbdbfefbd = the EF BF BD bytes)
inside `applyPatches` — and because the `patched` guard was set first, NOTHING was patched: the maintainer saw a vanilla
window and reported "the entire menu regressed" (tech proto v3, 2026-08-28).

**Why:** fixed-size buffers (LOGFONT lfFaceName[32], TEXTMETRIC faces, engine name tables) keep stale bytes after the NUL.

**How to apply:** read fixed buffers with `readByteArray(n)` and cut at the first 0 (or `readCString()` with no size
only when the buffer is known NUL-terminated within reach); validate strings before handing them to engine code
(printable-ASCII regex); in a proto's patch bootstrap, put risky native calls inside try/catch with a per-item
fallback so one failure can't silently turn the whole proto into a no-op — and log the EXCEPTION line prominently.
See [[project-smac-tech-select]], [[feedback-frida-attach-branch-target]].

## 2026-09-13 recurrence (monument proto v4-v4e): `new NativeFunction(p, ret, args, "cdecl")` throws "invalid abi specified"

Frida's ia32 ABI names are `default`/`mscdecl`/`stdcall`/`thiscall`/`fastcall` — `"cdecl"` is invalid. The throw sat at
top level after the first four attaches, so those worked and every later lever (painter hook, font swap, the "armed" line)
was silently dead for five runs. **Rules:** omit the abi for cdecl; wrap the whole hook body in `try { ... } catch (e) { log(...) }`
so a bootstrap throw is LOUD; and read the log's attach list against the hook's attach list after every run.
