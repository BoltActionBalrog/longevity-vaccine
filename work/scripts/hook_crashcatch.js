"use strict";
// hook_crashcatch.js -- ZERO-interference crash catcher for the BAKED exe.
// No Interceptor.attach at all: just the AV handler (EIP/ESP/stack snapshot on
// access violation). Used to locate the Quick Start crash on build 2ec360f5.
globalThis.LOG_PATH = "D:/SmacxUi/work/tests/frida_crashcatch.log";
log("=== hook_crashcatch.js armed (AV handler only, no hooks) ===");
installAVHandler("bakecrash");
if (requireBase()) {
  log("module base OK; reproduce the crash now (Quick Start).");
}
