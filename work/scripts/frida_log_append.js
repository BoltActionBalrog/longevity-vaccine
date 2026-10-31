'use strict';
// APPEND-MODE PRELUDE. Load this as an extra -l BEFORE a hook script (frida_common.js first,
// then this, then the hook) to make the hook APPEND to its log file instead of truncating it.
// frida_common.js opens the log lazily on the first log() call and checks globalThis.LOG_APPEND,
// so this only needs to run before that first call (loading order guarantees it).
//
// Used by the "SMACX Faction NN 1600x1200" desktop shortcut so its g=25 control run accumulates
// into the same frida_faction_nn_roundtrip.log as the preceding 4K (g=40) run instead of clobbering it.
globalThis.LOG_APPEND = true;
