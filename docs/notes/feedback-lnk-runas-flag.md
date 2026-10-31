---
name: feedback-lnk-runas-flag
description: Editing a desktop .lnk via WScript.Shell strips its 'Run as administrator' flag, breaking elevation-requiring shortcuts
type: feedback
---

WScript.Shell `CreateShortcut(path)` + `.Save()` does NOT preserve a `.lnk`'s "Run as administrator" flag. Editing an elevation-requiring shortcut in place (e.g. the SMACX Frida trace shortcuts, which run `run-frida-at-res.bat` and need UAC) silently clears that flag — the shortcut then launches non-elevated (or, after a Save+Rename, fails to launch at all: no window, no UAC).

**Why:** the flag lives in a byte the COM API doesn't round-trip; Save rewrites the .lnk without it.

**How to apply:** after `.Save()`, re-set it by patching the file bytes: read all bytes, `bytes[0x15] = bytes[0x15] -bor 0x20`, write back. Prefer deleting + recreating the .lnk fresh over in-place edit. Verify with `[bool]($bytes[0x15] -band 0x20)`.
