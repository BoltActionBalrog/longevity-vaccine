// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// Ring-overdraw prototype v2 — runtime injection of the REAL bake thunk (zero Interceptor).
// Retargets the E8 rel32 inside thunk_btn_2dscale (pcave2+0x4D1: call thunk_btn_stripes)
// to an RWX stub holding the assembled thunk_btn_ringfix bytes (work/patches/ringfix_hex.txt,
// sentinels patched at load: 11111111 -> g_popup_scale_num VA, 22222222 -> thunk_btn_stripes VA).
// Synchronous with the draw — exactly the baked placement, so no redraw race.
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_dl_ringfix.log";
log("=== hook_dl_ringfix_proto2.js started ===");

if (requireBase()) {
  const SITE    = VA(0xA0C4D1);      // E8 opcode inside thunk_btn_2dscale
  const STRIPES = VA(0xA0EFD0);      // thunk_btn_stripes
  const GVA     = VA(0x668740);      // g_popup_scale_num

  // --- verify the site before touching anything ---
  const op = SITE.readU8();
  const rel = SITE.add(1).readS32();
  const curTarget = SITE.add(5).add(rel);
  if (op !== 0xE8 || !curTarget.equals(STRIPES)) {
    log("!! site verify FAILED: op=" + op.toString(16) + " target=" + curTarget +
        " expected E8 -> " + STRIPES + " — NOT patching");
  } else try {
    // --- load + patch the thunk bytes ---
    const hexText = File.readAllText("D:/SmacxUi/work/patches/ringfix_hex.txt");
    const hexLine = hexText.split("\n").filter(l => l.trim() && !l.startsWith(";"))[0];
    const bytes = hexLine.trim().split(/\s+/).map(h => parseInt(h, 16));
    function patchSentinel(sentLE, addr) {
      for (let i = 0; i + 3 < bytes.length; i++) {
        if (bytes[i] === sentLE[0] && bytes[i+1] === sentLE[1] &&
            bytes[i+2] === sentLE[2] && bytes[i+3] === sentLE[3]) {
          const v = addr.toUInt32();
          bytes[i] = v & 0xFF; bytes[i+1] = (v >>> 8) & 0xFF;
          bytes[i+2] = (v >>> 16) & 0xFF; bytes[i+3] = (v >>> 24) & 0xFF;
          return 1;
        }
      }
      return 0;
    }
    const n1 = patchSentinel([0x11,0x11,0x11,0x11], GVA);
    const n2 = patchSentinel([0x22,0x22,0x22,0x22], STRIPES);
    if (n1 !== 1 || n2 !== 1) {
      log("!! sentinel patch failed (" + n1 + "," + n2 + ") — NOT arming");
    } else {
      const stub = Memory.alloc(4096);
      globalThis._ringfixStub = stub;              // retain — alloc pages are GC-freed
      Memory.protect(stub, 4096, "rwx");
      stub.writeByteArray(bytes);
      // retarget the call: rel32 = stub - (SITE + 5)
      const newRel = stub.sub(SITE.add(5)).toInt32();
      Memory.patchCode(SITE.add(1), 4, code => { code.writeS32(newRel); });
      log("[armed] ringfix stub @" + stub + " (" + bytes.length + "B), site " + SITE +
          " retargeted (was " + STRIPES + ")");
    }
  } catch (e) { log("!! arming threw: " + e); }
  let beats = 0;
  setInterval(() => { if (++beats <= 12) log("[hb] alive g=" + GVA.readU32()); }, 5000);
}
