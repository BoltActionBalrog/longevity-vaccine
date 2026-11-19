---
name: feedback-frida-no-float-in-callbacks
description: Float arithmetic inside a Frida Interceptor callback in terranx returns NaN (MMX state live); keep timings as UInt64 ticks
type: feedback
---

Inside a Frida `Interceptor` callback on `terranx` (seen at `draw_map` 0x46B190, 2026-11-16), any JS floating-point arithmetic can return NaN: the game reaches the hook with MMX state live (every x87 register tagged in use), and Frida's JS engine then loads NaN. Integer work is unaffected (readS32, counters, string building).

**Why:** the first PR 9 timing run logged "NaN ms" for all 22 repaints and cost the owner a wasted run. Reproduced outside the game: a native stub that runs `movq mm0, mm0` before calling a hooked function gives NaN for `x * 1000.0 / freq` in the callback, while `UInt64.sub(...).toString()` is correct.

**How to apply:** in a probe that times or scales anything, do no float math in `onEnter` / `onLeave`. Read `QueryPerformanceCounter` into a `Memory.alloc(8)` cell, keep the values as `UInt64`, log tick differences with `.sub().toString()`, and convert when reading the log. Float math at script load (outside callbacks) is fine. Test a new probe's callback body in a harmless 32-bit process with such an MMX stub before asking for a game run; see [[feedback-emulate-frida-stubs]].
