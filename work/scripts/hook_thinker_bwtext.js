"use strict";
// THINKER BASE-WINDOW TEXT PROBE -- OBSERVER ONLY, function-ENTRY hosts only, writes nothing.
//
// Question (2026-10-28 pass): Thinker's render_base_info lines are drawn through the ENGINE's text primitives at
// native offsets inside the base window (basewin.cpp: satellite "N +x / M +x / E +x" at rResWindow x1+5, y2-36-28 /
// -14 / -36 via Buffer_write_l_3; stockpile / staple-turns / riot / golden-age notes near them; "Pop: T / W / D / S"
// right-aligned at (690, 381) via Buffer_write_right_l_5 inside BaseWin_draw_energy; "Eco-Damage: N%" at the vanilla
// site through our bw2 chain). On the 4K workspace only the eco-damage line was ever seen (Survival Base has an
// Aerospace Complex + satellites, yet no N/M/E lines; no Pop: line anywhere). Overdrawn by our scaled panels, drawn
// off the visible rect, clipped, or never reached? This logs every text draw whose CALLER is thinker.dll (or whose
// text looks like one of those labels), with the dest buffer's size and clip, the x/y, and the font height, so the
// answer can be read off one base-screen visit.
//
// Hosts: Buffer_write_l_3 0x5DCEA0, Buffer_write_right_l_5 0x5DD3B0, Buffer_write_right_l_4 0x5DD300 (thiscall
// this = dest Buffer; stack: str, x, y[, a5], len) -- each attached only if its live first bytes are a plain
// prologue (our bw2 chain re-points a CALL SITE at 0x415AD8, not the entry). Buffer layout: W +0x80, H +0x84
// (negative = top-down), clip RECT +0x88.. (read as four ints; verify by eye against W/H).
//
// Run: D:\SmacxThinker\trace.bat --hook hook_thinker_bwtext.js ; open Survival Base (satellites) and a stapled base,
// flip the RESOURCE / SUPPORT / PSYCH tabs, quit. Lines: TEXT  <who> "<text>" at (x,y) dest WxH clip(...) font=..

globalThis.LOG_PATH = globalThis.LOG_PATH || "D:/SmacxUi/work/frida_thinker_bwtext.log";
log("=== hook_thinker_bwtext.js started " + new Date().toISOString() + " ===");

const HOSTS = [
  { name: "Buffer_write_l_3",       va: 0x5DCEA0, args: ["str", "x", "y", "len"] },
  { name: "Buffer_write_right_l_5", va: 0x5DD3B0, args: ["str", "x", "y", "len"] },
  { name: "Buffer_write_right_l_4", va: 0x5DD300, args: ["str", "x", "y", "a5", "len"] },
];
const LABELS = /Pop:|Eco-Damage|Stockpile|Nerve|Staple|Riot|Golden|boom|^[NME] [+-]\d/;
let thinker = null, logged = 0;
const N = { total: 0, thinker: 0, labelled: 0 };

function where(p) {
  if (thinker && p.compare(thinker.base) >= 0 && p.compare(thinker.base.add(thinker.size)) < 0) return "thinker.dll+0x" + p.sub(thinker.base).toString(16);
  const v = p.sub(globalThis.TERRANX_BASE).toInt32() + 0x400000;
  return (v >= 0xA0C000 && v < 0xA4C000 ? "cave 0x" : "exe 0x") + v.toString(16);
}
function bufInfo(b) {
  try {
    const w = b.add(0x80).readS32(), h = b.add(0x84).readS32();
    const c = [0, 4, 8, 12].map(o => b.add(0x88 + o).readS32());
    return "dest " + w + "x" + h + " clip(" + c.join(",") + ")";
  } catch (e) { return "dest ?"; }
}
function plain(va, name) {
  const p = VA(va);
  const b = Array.from(new Uint8Array(p.readByteArray(3)));
  // a plain prologue: `push ebp; mov ebp,esp` or a run of pushed registers (these three start `53 56 57`:
  // push ebx; push esi; push edi -- the first run refused them, 2026-10-29)
  const ok = (b[0] === 0x55 && b[1] === 0x8B && b[2] === 0xEC) || (b[0] >= 0x50 && b[0] <= 0x57 && b[1] >= 0x50 && b[1] <= 0x57);
  log("  " + name + " @0x" + va.toString(16) + " bytes " + b.map(x => x.toString(16).padStart(2, "0")).join(" ") + (ok ? "" : " -> not a plain prologue, NOT hooked"));
  return ok ? p : null;
}

if (requireBase()) {
  thinker = Process.findModuleByName("thinker.dll");
  log("thinker.dll " + (thinker ? thinker.base + " size 0x" + thinker.size.toString(16) : "NOT loaded"));
  for (const h of HOSTS) {
    const p = plain(h.va, h.name);
    if (!p) continue;
    Interceptor.attach(p, {
      onEnter(args) {
        N.total++;
        const buf = this.context.ecx;
        let text = "";
        try { text = args[0].readCString(80) || ""; } catch (e) { text = "<unreadable>"; }
        const fromThinker = thinker && this.returnAddress.compare(thinker.base) >= 0 && this.returnAddress.compare(thinker.base.add(thinker.size)) < 0;
        const labelled = LABELS.test(text);
        if (fromThinker) N.thinker++;
        if (labelled) N.labelled++;
        if (!fromThinker && !labelled) return;
        if (logged++ > 400) return;
        const a = h.args.map((n, i) => n + "=" + (n === "str" ? "" : args[i].toInt32())).filter(s => !s.endsWith("=")).join(" ");
        log("TEXT     " + h.name + " \"" + text.replace(/\n/g, "\\n") + "\" " + a + " " + bufInfo(buf) + " from " + where(this.returnAddress));
      }
    });
  }
  log("installed; open a base screen with satellites / a stapled base, flip the tabs, quit.");
  setInterval(function () { log("SUMMARY text draws " + N.total + ", from thinker.dll " + N.thinker + ", label-like " + N.labelled); }, 30000);
}
rpc.exports = { summary: function () { log("SUMMARY text draws " + N.total + ", from thinker.dll " + N.thinker + ", label-like " + N.labelled); } };
