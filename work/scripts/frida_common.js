// Shared Frida helpers for terranx.exe tracing.
//
// Load this BEFORE a hook script:  frida -f terranx.exe -l frida_common.js -l hook_*.js
// (run-frida.bat does this for you.)
//
// Everything is published on globalThis so the later -l script can use it.
// The log file is opened lazily on first log() call, so a hook can override
// the path by setting `globalThis.LOG_PATH = "..."` at the top of its own file.
//
// Targets Frida 17 (Module.findBaseAddress removed -> Process.findModuleByName).

globalThis.LOG_PATH = globalThis.LOG_PATH || "D:/SmacxUi/work/frida_trace.log";

// Log open mode: truncate ("w") by default. A loader (e.g. frida_log_append.js, loaded as an
// extra -l before the hook) can set globalThis.LOG_APPEND = true to APPEND instead — used to
// accumulate multiple runs (e.g. a 4K run then a 1600x1200 run) into one log.
let _logFile = null;
globalThis.log = function (msg) {
  if (_logFile === null) {
    _logFile = new File(globalThis.LOG_PATH, globalThis.LOG_APPEND ? "a" : "w");
    if (globalThis.LOG_APPEND) {
      _logFile.write("\n===== appended run (" + new Date().toISOString() + ") =====\n");
      _logFile.flush();
    }
  }
  const line = "" + msg;
  console.log(line);
  _logFile.write(line + "\n");
  _logFile.flush();
};

// The game image base is 0x00400000; translate a static VA to a runtime
// address through the actual load base. Use the main module so this works
// regardless of the exe name (terranx.exe vs terranx_PRACX.exe).
const _mod = Process.mainModule
  || (Process.enumerateModules ? Process.enumerateModules()[0] : null)
  || Process.findModuleByName("terranx.exe");
if (!_mod) {
  // Defer the error to the hook so it can log via our log().
  globalThis.TERRANX_BASE = null;
} else {
  globalThis.TERRANX_BASE = _mod.base;
}
globalThis.VA = function (offset) {
  if (globalThis.TERRANX_BASE === null) {
    throw new Error("game main module not found");
  }
  return globalThis.TERRANX_BASE.add(offset - 0x400000);
};

// Read a 32-bit value as an unsigned int regardless of Frida's NativePointer
// vs Number ambiguity in register/retval contexts.
globalThis.u32 = function (v) {
  if (v === null || v === undefined) return 0;
  if (typeof v === "number") return v >>> 0;
  return (v.toUInt32 ? v.toUInt32() : Number(v)) >>> 0;
};

// SMAC Buffer objects carry their pixel dimensions at +0x80 (W) and +0x84 (H).
// Returns {w,h} or {w:-1,h:-1} if unreadable.
globalThis.bufWH = function (bufAddrU32) {
  try {
    const p = ptr("0x" + (bufAddrU32 >>> 0).toString(16));
    return { w: p.add(0x80).readS32(), h: p.add(0x84).readS32() };
  } catch (e) {
    return { w: -1, h: -1 };
  }
};

// Read N consecutive 32-bit stack args (1-based: arg(esp,1) == [esp+4]).
globalThis.arg = function (espPtr, n) {
  return espPtr.add(n * 4).readU32();
};
globalThis.argS = function (espPtr, n) {
  return espPtr.add(n * 4).readS32();
};

// Install an access-violation handler that snapshots EIP/ESP context once and
// then lets the OS terminate the process. Useful when a trace is meant to run
// up to a crash. Pass a short label for the log lines.
globalThis.installAVHandler = function (label) {
  Process.setExceptionHandler(function (details) {
    if (details.type !== "access-violation") return false;
    try {
      const c = details.context;
      log("=== ACCESS VIOLATION (" + (label || "") + ") ===");
      log("  eip=0x" + u32(c.eip).toString(16) + " esp=0x" + u32(c.esp).toString(16));
      try {
        const eipBytes = c.eip.readByteArray(16);
        const hex = Array.from(new Uint8Array(eipBytes))
          .map(b => b.toString(16).padStart(2, "0")).join(" ");
        log("  bytes@eip: " + hex);
      } catch (e) {}
      for (let i = 0; i < 12; i++) {
        try {
          const a = c.esp.add(i * 4);
          log("  [esp+0x" + (i * 4).toString(16) + "] = 0x" + a.readU32().toString(16));
        } catch (e) {}
      }
    } catch (e) {}
    return false; // let the OS terminate
  });
};

globalThis.requireBase = function () {
  if (globalThis.TERRANX_BASE === null) {
    log("ERROR: terranx.exe module not found — cannot install hooks.");
    return false;
  }
  log("frida_common: terranx.exe base = 0x" + globalThis.TERRANX_BASE.toString(16));
  return true;
};
