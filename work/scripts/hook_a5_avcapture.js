'use strict';
// =====================================================================================
// A5 AV-CAPTURE — run the DETOUR-ENABLED (crashing) build under Frida and snapshot the
// exact fault. The probe proved the only thunk-firing call (131x157 portrait @25/16) has
// a fully-readable source and in-bounds dest writes, so the crash is either an asm bug in
// the 923-byte thunk or a side-effect of REPLACING Sprite_draw_2. The fault EIP decides:
//   * EIP in pcave2 [0xA0CA00..0xA0CDA0)  -> asm bug; the +offset names the instruction.
//   * EIP elsewhere in the engine          -> replacement side-effect (skipped native draw).
//
// We do NOT Interceptor.attach on Sprite_draw_2: that relocates the detour bytes and would
// corrupt the very thing under test. We only install a process-wide exception handler that
// dumps full context + the thunk's stack frame, then let the OS terminate.
//
// Run on the DETOUR-ENABLED build at 1600x1200. Navigate:
//   %resume -> Choose Your Factions -> SELECT a faction  (crash expected here).
// =====================================================================================

globalThis.LOG_PATH = "D:/SmacxUi/work/frida_a5_avcapture.log";
log("=== hook_a5_avcapture.js started ===");

const THUNK_LO = 0x00A0CA00;   // thunk_portrait_avg entry (pcave2 +0xA00)
const THUNK_HI = 0x00A0CDA0;   // just past its end

if (requireBase()) {
  // Translate the thunk range through the real load base (base was 0x400000 last run, but be safe).
  const base = globalThis.TERRANX_BASE;
  const lo = base.add(THUNK_LO - 0x400000);
  const hi = base.add(THUNK_HI - 0x400000);
  log(`thunk range (runtime): 0x${lo.toString(16)} .. 0x${hi.toString(16)}`);

  Process.setExceptionHandler(function (details) {
    if (details.type !== 'access-violation') return false;
    try {
      const c = details.context;
      const eip = u32(c.eip), esp = u32(c.esp), ebp = u32(c.ebp);
      log("");
      log("================= ACCESS VIOLATION =================");
      log(`  fault addr     : ${details.memory ? details.memory.address : '?'}  op=${details.memory ? details.memory.operation : '?'}`);
      log(`  eip=0x${eip.toString(16)}  esp=0x${esp.toString(16)}  ebp=0x${ebp.toString(16)}`);
      log(`  eax=0x${u32(c.eax).toString(16)} ebx=0x${u32(c.ebx).toString(16)} ecx=0x${u32(c.ecx).toString(16)} edx=0x${u32(c.edx).toString(16)}`);
      log(`  esi=0x${u32(c.esi).toString(16)} edi=0x${u32(c.edi).toString(16)}`);

      // Where did we fault?
      if (eip >= (THUNK_LO>>>0) && eip < (THUNK_HI>>>0)) {
        log(`  *** EIP IS INSIDE thunk_portrait_avg: pcave2 +0x${(eip - 0xA0C000).toString(16)}  (thunk +0x${(eip - THUNK_LO).toString(16)}) -> ASM BUG ***`);
      } else {
        log(`  EIP is OUTSIDE the thunk -> likely a replacement side-effect (skipped native draw).`);
      }

      try {
        const hex = Array.from(new Uint8Array(c.eip.readByteArray(16)))
          .map(b => b.toString(16).padStart(2,"0")).join(" ");
        log(`  bytes@eip: ${hex}`);
      } catch(e){ log(`  bytes@eip: <unreadable> ${e}`); }

      // Dump the thunk's stack frame [ebp-0x90 .. ebp+0x20] so we can read its locals at fault time.
      try {
        const eb = ptr("0x"+ebp.toString(16));
        log("  --- frame [ebp-0x90 .. ebp+0x1c] ---");
        for (let off=-0x90; off<=0x1c; off+=4) {
          let v="?"; try { v = "0x"+(eb.add(off).readU32()>>>0).toString(16); } catch(e){ v="<unmapped>"; }
          const sign = off<0 ? "-0x"+(-off).toString(16) : "+0x"+off.toString(16);
          log(`    [ebp${sign}] = ${v}`);
        }
      } catch(e){ log(`  frame dump failed: ${e}`); }

      // Raw stack
      try {
        const sp = ptr("0x"+esp.toString(16));
        log("  --- stack [esp .. esp+0x2c] ---");
        for (let i=0;i<12;i++){ let v="?"; try { v="0x"+(sp.add(i*4).readU32()>>>0).toString(16); } catch(e){ v="<unmapped>"; }
          log(`    [esp+0x${(i*4).toString(16)}] = ${v}`); }
      } catch(e){}
      log("===================================================");
    } catch(e){ log("AV handler error: "+e); }
    return false; // let the OS terminate (we have our snapshot)
  });

  log("AV-capture installed. Choose Your Factions -> SELECT a faction. Crash expected; read frida_a5_avcapture.log");
}
