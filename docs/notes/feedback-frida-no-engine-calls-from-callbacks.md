---
name: feedback-frida-no-engine-calls-from-callbacks
description: Never drive an engine repaint/UI action via NativeFunction from inside a Frida Interceptor callback — hooks are suppressed on that thread for the nested call; emit a native stub instead
type: feedback
---

Calling engine code (NativeFunction) from inside an `Interceptor.attach` onEnter/onLeave runs that nested call with EVERY Frida hook on the thread SUPPRESSED (Frida's re-entrancy guard). A chevron press made from a PostMessageA hook (DW proto v14t, 2026-08-29) triggered the picker's full redraw, whose Caviar draws ran without the FIT/composite/restripe hooks → all icons dropped to native size until a hover redrew a cell normally.

**Why:** Gum ignores the current thread while a listener callback executes, so nested calls to hooked functions bypass their hooks silently — no error, just vanilla behaviour.

**How to apply:** a JS callback may only READ/patch args or memory. Anything that must run through the hooked engine paths (repaints, present, scroll notifies) must be emitted as native code (keystone stub at the bake's own site, Unicorn-checked) or deferred to engine-driven execution. Tiny leaf calls with no hooked descendants (e.g. a present blit) are the only safe exception — and audit that claim per call. See [[project-smac-design-workshop]].
