"use strict";
// CRASH CATCHER (2026-07-03): hotseat/multiplayer SAVE crashes right as the save
// completes (save file IS fully written; process tears down at the write timestamp;
// repros on pristine cc659f too -> base-game/PRACX/DDrawCompat fault, not our patches).
//
// Catches BOTH possible failure modes and prints a symbolized backtrace either way:
//   (A) access violation  -> Process.setExceptionHandler (module+VA of eip, regs, stack)
//   (B) graceful fatal     -> hooks ExitProcess/TerminateProcess/exit/_exit/abort +
//                             MessageBoxA/W (SMAC pops a fatal MessageBox then exits) +
//                             the known draw-buffer fatal branch 0x5D7798.
// Brackets the save path (save_game 0x5A9EB0, FileDlg_save_modal 0x613D50) so we know
// whether the fault is inside the save or in the return-to-game afterwards.
// Observer only; no writes to game state.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_savecrash.log";
log("=== hook_savecrash.js started ===");

// ---- module map (resolve any code address to module+offset) ----
// Rebuilt on demand: at script load the process is still spawn-suspended, so
// late-loaded DLLs (uimod.dll, PRACX-pulled modules) aren't present yet. Refresh
// before resolving a fault so those addresses still symbolize.
let mods = [];
function refreshMods() {
  mods = Process.enumerateModules().map(m => ({
    name: m.name, lo: m.base, hi: m.base.add(m.size)
  })).sort((a, b) => a.lo.compare(b.lo));
}
refreshMods();
// resolve a DLL export across Frida API variants (Frida 17 removed the static
// Module.findExportByName/getExportByName). Copied from hook_a5_avgscale.js.
function resolveExport(dll, name) {
  try { const m = Process.getModuleByName(dll); if (m) { if (m.getExportByName) return m.getExportByName(name);
        if (m.findExportByName) { const a = m.findExportByName(name); if (a) return a; } } } catch (e) {}
  try { const m = Process.findModuleByName(dll); if (m && m.findExportByName) { const a = m.findExportByName(name); if (a) return a; } } catch (e) {}
  try { if (Module.getGlobalExportByName) return Module.getGlobalExportByName(name); } catch (e) {}
  try { if (typeof Module.getExportByName === 'function') return Module.getExportByName(dll, name); } catch (e) {}
  return null;
}
function whereis(p) {
  if (p === null || p.isNull()) return "0x0";
  for (const m of mods) {
    if (p.compare(m.lo) >= 0 && p.compare(m.hi) < 0)
      return m.name + "+0x" + p.sub(m.lo).toString(16) +
             (m.name.toLowerCase().indexOf("terranx") === 0
               ? " (VA 0x" + p.sub(m.lo).add(0x400000).toString(16) + ")" : "");
  }
  return "0x" + p.toString(16) + " (unknown)";
}
log("modules:");
for (const m of mods)
  if (/terranx|prax|uimod|ddraw|opengl/i.test(m.name))
    log("  " + m.name + "  base=" + m.lo + " size=0x" + m.hi.sub(m.lo).toString(16));

// ---- raw-stack backtrace: scan esp for dwords that point into any module's .text ----
function stackTrace(sp, n, maxHits) {
  const out = [];
  for (let i = 0; i < n && out.length < maxHits; i++) {
    try {
      const v = sp.add(i * 4).readPointer();
      for (const m of mods) {
        if (v.compare(m.lo) >= 0 && v.compare(m.hi) < 0) {
          out.push("[esp+0x" + (i * 4).toString(16) + "] " + whereis(v));
          break;
        }
      }
    } catch (e) { break; }
  }
  return out;
}

// ---- (A) access-violation handler (richer than installAVHandler) ----
let saveDepth = 0;
Process.setExceptionHandler(function (d) {
  if (d.type !== "access-violation") return false;
  refreshMods();
  const c = d.context;
  log("");
  log("========== ACCESS VIOLATION ==========");
  log("  faulting eip = " + whereis(c.eip));
  log("  access " + d.memory.operation + " @ " + d.memory.address);
  log("  saveDepth=" + saveDepth);
  try {
    const hex = Array.from(new Uint8Array(c.eip.readByteArray(16)))
      .map(b => b.toString(16).padStart(2, "0")).join(" ");
    log("  bytes@eip: " + hex);
  } catch (e) {}
  for (const r of ["eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp"])
    log("  " + r + "=0x" + u32(c[r]).toString(16));
  log("  --- stack backtrace ---");
  for (const line of stackTrace(c.esp, 96, 24)) log("    " + line);
  log("  --- ebp chain (frame: saved ebp / return address / first 6 args) ---");
  try {
    let bp = c.ebp;
    for (let k = 0; k < 12 && !bp.isNull(); k++) {
      const nbp = bp.readPointer(), ret = bp.add(4).readPointer();
      const args = []; for (let j = 0; j < 6; j++) args.push("0x" + u32(bp.add(8 + 4 * j).readPointer()).toString(16));
      log("    frame" + k + " ebp=" + bp + " ret=" + whereis(ret) + " args=" + args.join(","));
      if (nbp.compare(bp) <= 0) break;
      bp = nbp;
    }
  } catch (e) { log("  ebp chain err " + e); }
  log("  --- raw stack esp..esp+0x2C0 (every dword; * = module .text) ---");
  try {
    for (let i = 0; i < 0xB0; i++) {
      const v = c.esp.add(i * 4).readPointer();
      let tag = "";
      for (const m of mods) if (v.compare(m.lo) >= 0 && v.compare(m.hi) < 0) { tag = " *" + whereis(v); break; }
      if (v.compare(ptr(0xA0C000)) >= 0 && v.compare(ptr(0xA2E000)) < 0) tag = " *pcave2+0x" + v.sub(0xA0C000).toString(16);
      log("    [esp+0x" + (i * 4).toString(16) + "] 0x" + u32(v).toString(16) + tag);
    }
  } catch (e) { log("  raw dump err " + e); }
  log("======================================");
  return false; // let it terminate
});

if (requireBase()) {
  const base0 = VA(0x400000);
  const sVA = p => whereis(p);

  function fatal(tag, sp) {
    refreshMods();
    log("");
    log(">>>> TEARDOWN: " + tag + " (saveDepth=" + saveDepth + ")");
    for (const line of stackTrace(sp, 96, 24)) log("    " + line);
    log("<<<<");
  }

  // ---- (B) teardown hooks ----
  const teardown = [
    ["kernel32.dll", "ExitProcess"],
    ["kernel32.dll", "TerminateProcess"],
    ["ntdll.dll", "RtlExitUserProcess"],
    ["user32.dll", "MessageBoxA"],
    ["user32.dll", "MessageBoxW"],
  ];
  for (const [mod, fn] of teardown) {
    const a = resolveExport(mod, fn);
    if (!a) { log("(no export " + mod + "!" + fn + ")"); continue; }
    Interceptor.attach(a, function (args) {
      refreshMods();
      let extra = "";
      if (fn === "MessageBoxA") { try { extra = " text='" + args[1].readAnsiString(80) + "'"; } catch (e) {} }
      if (fn === "MessageBoxW") { try { extra = " text='" + args[1].readUtf16String(80) + "'"; } catch (e) {} }
      log("");
      log(">>>> " + fn + extra + " called from " + sVA(this.returnAddress) +
          " (saveDepth=" + saveDepth + ")");
      for (const line of stackTrace(this.context.esp, 96, 24)) log("    " + line);
      log("<<<<");
    });
  }
  // CRT exit family (msvcrt or the statically-linked CRT — try both, ignore misses)
  for (const fn of ["exit", "_exit", "abort", "_amsg_exit", "_invalid_parameter"]) {
    const a = resolveExport("msvcrt.dll", fn);
    if (a) Interceptor.attach(a, function () { fatal("msvcrt!" + fn, this.context.esp); });
  }

  // known SMAC fatal branch: CreateDIBSection NULL -> MessageBox("Unable to allocate draw-buffer") -> exit(4)
  Interceptor.attach(VA(0x5D7798), function () {
    const b = this.context.esi;
    log("");
    log(">>>> FATAL draw-buffer branch 0x5D7798: buf=" + b +
        " w[+80]=" + b.add(0x80).readS32() + " h[+84]=" + b.add(0x84).readS32());
    fatal("drawbuffer_fatal", this.context.esp);
  });

  // ---- save path brackets ----
  Interceptor.attach(VA(0x5A9EB0), {   // save_game(a1,a2) — opens the save picker
    onEnter() { saveDepth++; log("[save_game] ENTER depth=" + saveDepth); },
    onLeave(r) { log("[save_game] LEAVE ret=" + r); saveDepth--; }
  });
  Interceptor.attach(VA(0x613D50), {   // FileDlg_save_modal — the picker loop
    onEnter() { saveDepth++; log("[FileDlg_save_modal] ENTER depth=" + saveDepth); },
    onLeave(r) { log("[FileDlg_save_modal] LEAVE ret=" + r); saveDepth--; }
  });

  // Correlate the actual disk write so we can see "write done, THEN crash".
  const wf = resolveExport("kernel32.dll", "WriteFile");
  if (wf) Interceptor.attach(wf, function (args) {
    if (saveDepth > 0) {
      const n = args[2].toInt32();
      if (n > 4096) log("  [WriteFile] " + n + " bytes (in save path) caller=" + sVA(this.returnAddress));
    }
  });

  log("crash-catcher armed: AV handler + teardown hooks + save brackets. Reproduce the save now.");
}
