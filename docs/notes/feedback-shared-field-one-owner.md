---
name: feedback-shared-field-one-owner
description: A later arc that starts scaling a shared struct field at init silently double-scales every older bracket thunk that relative-scales the same field; magnitude guards hide it at 4K
type: feedback
---

When a new arc makes a SHARED engine field device-space permanently (e.g. rw_scale_shared's init lever writing RW+0x5980/+0xE268), grep every older thunk that reads-scales-restores the same field (`[esi+0xOFF]` + HD) — they now double-scale. Never gate such a bracket on a magnitude guard (`cmp eax,800`): it is resolution-dependent, so 4K can pass by accident while 1600/1920 break. Discriminate native vs device by a vanilla IDENTITY between fields (textB == win_h − 0x35), or give the field one owner.

**Why:** 2026-09-19 Datalinks tech-page side buttons sat +225px low at 1600 (only +26 at 4K) for two weeks after 7b4588e; parity tests seeded native values so nothing caught it. See [[project-smac-datalinks]], [[feedback-shared-field-per-row-doublescale]].

**How to apply:** before baking any init-time lever on a shared struct, census all readers/writers of each field across assemble_*.py; parity tests of bracket thunks must sweep BOTH entry states (native + already-device) at g 16/22/25/40.
