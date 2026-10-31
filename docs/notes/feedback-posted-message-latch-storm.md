---
name: feedback-posted-message-latch-storm
description: A self-posted window message must be throttled by TIME, never by "clear the latch when a message of that type is dequeued" -- the dequeue and the re-post happen in the same poll pass and the game hangs
type: feedback
---

2026-10-10: modernctl's hover line re-posts a synthetic WM_MOUSEMOVE (PostPointerMove) guarded by a latch the
map wrapper clears. To un-stick a latch left set by a move another window consumed, I cleared it at the top of
the per-message poll whenever a WM_MOUSEMOVE was dequeued -- and the same poll pass, a few lines later, re-posted
because the hover was still owned with the overlay hidden: an endless message storm; Tab froze the game and the
user had to force-close it.

**Why:** a GetMsgProc poll sees the message it is reacting to; any "reset on dequeue + post on condition" pair
in one pass is a loop whenever the condition is not cleared by the message itself.
**Also:** a message posted from a hook that runs inside the engine's NESTED pump (Console_ready / wait_loop /
flush_input during a key dispatch) is discarded by flush_input -- keep the NEED (a bounded retry every ~40 ms until
the handler runs), not the post.
**How to apply:** throttle self-posted messages by wall-clock (a latch that EXPIRES, e.g. 500 ms), never by
dequeue events; a posted message that never reaches its handler is a normal case, not an error. Related:
[[feedback-frida-no-engine-calls-from-callbacks]], [[project-smac-mouse-scheme-proposals]].
