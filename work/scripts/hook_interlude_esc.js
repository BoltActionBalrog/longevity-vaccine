"use strict";
// INTERLUDE ESC -- OBSERVER ONLY, function-ENTRY hosts only, writes nothing.
//
// Question (2026-10-30, user, PRACX + our mod and under Thinker alike): during a story interlude the first Esc
// does not close it; instead "the escape quit menu momentarily opens over the interlude"; the second Esc closes it.
// Who receives the Esc? The interlude's own window, or the Console (map) because the interlude never went modal
// (pristine load_credits_b 0x45F2E0 calls no Win_set_modal)? Which popup opens, from where, and who closes it?
//
// Hosts (all plain prologues on the live exe, checked before attaching):
//   interlude 0x5230E0 (cdecl: event_id, text, a3, a4) / load_credits_b 0x45F2E0 (thiscall: InterludeWin*, section)
//   Win_on_key 0x5F5D10 (thiscall: Win*, vk, is_down, repeat, scan) -- vtbl+0x138 of every Win: the key dispatcher
//   Console_on_key_click 0x5178C0 (thiscall: Console*, a2, key)
//   Popup_start 0x406380 (thiscall: Popup*, filename, label, ...)   -> which popup is that "quit menu"
//   Win_set_modal 0x5EE190 (modal push; g_modal_top 0x9B7AE0)       -> who goes modal when
//   GraphicWin_close 0x? (not hooked: read g_modal_top + the interlude's window state in the key events instead)
// Each line carries the time since the trace started, the modal top and the interlude nesting depth.
//
// Run: the desktop "SMACX Frida Trace" shortcuts after `pwsh -File work\repoint-trace-shortcut.ps1 hook_interlude_esc.js`
// (4K + 1920x1080 + 1600x1200 on the live PRACX install); %resume, reach an interlude, press Esc twice, quit.

// one timestamped log per run (the launcher presets frida_trace.log; two runs -- vanilla and ours -- must not overwrite)
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_interlude_esc_" + new Date().toISOString().replace(/[-:]/g, "").replace(/\..*/, "") + ".log";
log("=== hook_interlude_esc.js started " + new Date().toISOString() + " ===");

const VA_interlude = 0x5230E0, VA_load_credits_b = 0x45F2E0, VA_Win_on_key = 0x5F5D10, VA_Console_on_key_click = 0x5178C0,
      VA_Popup_start = 0x406380, VA_Win_set_modal = 0x5EE190, VA_Win_get_active_target = 0x5F6A50, VA_Console_menu_proc = 0x51BC70,
      VA_g_modal_top = 0x9B7AE0, VA_g_sb_track_win = 0x9B7ABC,
      // run 2 (2026-10-30): the generic per-window key handler 0x5EEA90 (thiscall: this, composite, key; Enter/Esc ->
      // vtbl+0xB0, then the +0x42C callback, vtbl+0x64 on_key, then the +0x38 chain) and Win_release_modal 0x5EE280 --
      // run 1 showed the interlude's modal gone BEFORE the Console got the Esc, by a path not yet seen
      VA_Win_key_default = 0x5EEA90, VA_Win_release_modal = 0x5EE280;
function vtbl(p) { try { return "vt 0x" + p.readPointer().sub(globalThis.TERRANX_BASE).add(0x400000).toString(16); } catch (e) { return "vt ?"; } }
const t0 = Date.now();
let depth = 0;           // interlude nesting (interlude -> load_credits_b)
let interludeWin = null; // the InterludeWin* seen at load_credits_b entry

function ms() { return ("      " + (Date.now() - t0)).slice(-6) + "ms"; }
function where(p) {
  try {
    const m = Process.findModuleByAddress(p);
    if (m && m.name.toLowerCase() === "terranx.exe") {
      const v = p.sub(m.base).toInt32() + 0x400000;
      return (v >= 0xA0C000 && v < 0xA4C000 ? "cave 0x" : "exe 0x") + v.toString(16);
    }
    return m ? m.name + "+0x" + p.sub(m.base).toString(16) : p.toString();
  } catch (e) { return p.toString(); }
}
function bt(ctx) {
  try { return Thread.backtrace(ctx, Backtracer.FUZZY).slice(0, 10).map(where).join(" < "); } catch (e) { return "(no backtrace)"; }
}
function modal() {
  try { const m = VA(VA_g_modal_top).readPointer(); return "modal=" + (m.isNull() ? "none" : m) + (interludeWin && m.equals(interludeWin) ? "(INTERLUDE)" : ""); } catch (e) { return "modal=?"; }
}
function plain(va, name) {
  const p = VA(va);
  const b = Array.from(new Uint8Array(p.readByteArray(5)));
  const ok = (b[0] === 0x55 && b[1] === 0x8B && b[2] === 0xEC) || (b[0] >= 0x50 && b[0] <= 0x57) || (b[0] === 0x83 && b[1] === 0xEC) || b[0] === 0xA1;
  log("  " + name + " @0x" + va.toString(16) + " bytes " + b.map(x => x.toString(16).padStart(2, "0")).join(" ") + (ok ? "" : " -> not a plain prologue, NOT hooked"));
  return ok ? p : null;
}
function cstr(p) { try { return p.isNull() ? "(null)" : (p.readCString(60) || ""); } catch (e) { return "<unreadable>"; } }

if (requireBase()) {
  let p;
  if ((p = plain(VA_interlude, "interlude"))) Interceptor.attach(p, {
    onEnter(args) { depth++; log(ms() + " INTERLUDE enter event " + args[0].toInt32() + " text \"" + cstr(args[1]) + "\" depth " + depth + " " + modal()); },
    onLeave(r) { log(ms() + " INTERLUDE leave depth " + depth + " " + modal()); depth--; interludeWin = null; }
  });
  if ((p = plain(VA_load_credits_b, "load_credits_b"))) Interceptor.attach(p, {
    onEnter(args) { interludeWin = this.context.ecx; log(ms() + " LOAD_B   enter win " + interludeWin + " section \"" + cstr(args[0]) + "\" " + modal()); },
    onLeave(r) { log(ms() + " LOAD_B   leave " + modal()); }
  });
  if ((p = plain(VA_Win_on_key, "Win_on_key"))) Interceptor.attach(p, {
    onEnter(args) {
      if (depth === 0) return;
      const vk = args[0].toInt32() & 0xFFFF, down = args[1].toInt32();
      if (vk !== 0x1B && vk !== 0x0D && vk !== 0x20) return;                      // Esc / Enter / Space only
      log(ms() + " KEY      Win_on_key win " + this.context.ecx + (interludeWin && this.context.ecx.equals(interludeWin) ? "(INTERLUDE)" : "") +
          " vk 0x" + vk.toString(16) + " down " + down + " " + modal() + " from " + where(this.returnAddress));
    }
  });
  if ((p = plain(VA_Console_on_key_click, "Console_on_key_click"))) Interceptor.attach(p, {
    onEnter(args) {
      if (depth === 0) return;
      log(ms() + " KEY      Console_on_key_click key 0x" + (args[1].toInt32() & 0xFFFF).toString(16) + " a2 " + args[0].toInt32() + " " + modal() + "\n           " + bt(this.context));
    }
  });
  if ((p = plain(VA_Console_menu_proc, "Console_menu_proc"))) Interceptor.attach(p, {
    onEnter(args) { if (depth > 0) log(ms() + " MENU     Console_menu_proc item " + args[0].toInt32() + " " + modal() + "\n           " + bt(this.context)); }
  });
  if ((p = plain(VA_Popup_start, "Popup_start"))) Interceptor.attach(p, {
    onEnter(args) {
      if (depth === 0) return;
      this.label = cstr(args[0]) + " / " + cstr(args[1]);
      log(ms() + " POPUP    Popup_start popup " + this.context.ecx + " \"" + this.label + "\" " + modal() + "\n           " + bt(this.context));
    },
    onLeave(r) { if (depth > 0) log(ms() + " POPUP    Popup_start returned " + r.toInt32() + " for \"" + this.label + "\" " + modal()); }
  });
  if ((p = plain(VA_Win_key_default, "Win_key_default"))) Interceptor.attach(p, {
    onEnter(args) {
      if (depth === 0) return;
      const key = args[1].toInt32() & 0xFFFF;
      if (key !== 0x1B && key !== 0x0D && key !== 0x20) { this.skip = true; return; }
      this.key = key;
      log(ms() + " KEYDEF   Win_key_default win " + this.context.ecx + (interludeWin && this.context.ecx.equals(interludeWin) ? "(INTERLUDE)" : "") + " " + vtbl(this.context.ecx) +
          " key 0x" + key.toString(16) + " composite 0x" + (args[0].toInt32() >>> 0).toString(16) + " " + modal() + " from " + where(this.returnAddress));
    },
    onLeave(r) { if (!this.skip && depth > 0) log(ms() + " KEYDEF   returned " + r.toInt32() + " for key 0x" + this.key.toString(16) + " " + modal()); }
  });
  if ((p = plain(VA_Win_release_modal, "Win_release_modal"))) Interceptor.attach(p, {
    onEnter(args) { if (depth > 0) log(ms() + " MODAL    Win_release_modal win " + this.context.ecx + (interludeWin && this.context.ecx.equals(interludeWin) ? "(INTERLUDE)" : "") + " " + modal() + "\n           " + bt(this.context)); }
  });
  if ((p = plain(VA_Win_set_modal, "Win_set_modal"))) Interceptor.attach(p, {
    onEnter(args) { if (depth > 0) log(ms() + " MODAL    Win_set_modal win " + this.context.ecx + " arg0 " + args[0] + " " + modal() + "\n           " + bt(this.context)); }
  });
  log("installed; reach an interlude, press Esc (watch the menu flash), press Esc again, quit. t0 = now.");
}
