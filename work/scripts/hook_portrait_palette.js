'use strict';
// =====================================================================================
// PORTRAIT PHASE-0 PROBE (observer only) — replaceable leader portraits.
//
// Answers, in one run per resolution:
//  1. load_faction_art(f) @0x453710: the 37 sprites it cuts per faction (w/h/pitch/offsets,
//     content hash), which caller loaded it (picker / game setup / save load), and the
//     interface buffer's colour table (0x798668+0xA4) + g_main_palette at return.
//  2. Every Sprite_draw_2 whose SOURCE is one of the 4 portrait slots (council small/big,
//     diplomacy, datalink) or g_art_spr: consumer (return address), dest, scale num/den,
//     and the DEST's colour table (dest+0xA4) — full dump on first sight of each distinct hash.
//  3. Whether any portrait-shaped draw reaches g_art_spr (would break slot identification).
//  4. Whether any portrait draws at num < den (g < 16).
//
// Hosts (function entries only):
//  - 0x453710 load_faction_art: pristine prologue 55 8B EC 83 EC 10.
//  - 0xA12330: the cave target of the baked Sprite_draw_2 detour (0x5E4B4A is push/ret, NOT a
//    host). Entered by push/ret with the original thiscall stack intact: ecx=Sprite*,
//    [esp+4]=dest, [+8]=key, [+c]=x, [+10]=y, [+14]=num, [+18]=den. First insn is a plain
//    `mov eax,[0x668740]`; no in-thunk branch targets its first 5 bytes.
//
// Run: 4K and 1024x768 (g=16 native path) at minimum; drive: new game faction picker (browse
// several factions, SMAC + SMACX), start game, F-key PROFILE report, Datalinks faction entry,
// a diplomacy contact / council session, a combat (combat console). Then load a save.
// =====================================================================================

globalThis.LOG_PATH = "D:/SmacxUi/work/frida_portrait_palette_" +
    new Date().toISOString().replace(/[:.]/g, "-") + ".log";
log("=== hook_portrait_palette.js started ===");

const LOAD_FACTION_ART = 0x00453710;
const SD2_CAVE         = 0x00A12330;  // Sprite_draw_2 baked-detour target (cross-checked live 2026-09-29)
const SLOT_BLOCK       = 0x0078E978;
const FACTION_STRIDE   = 0x65C;
const SPRITE_STRIDE    = 0x2C;
const N_SPRITES        = 37;
const SLOTS = { 0x478: "smallcouncil", 0x4A4: "bigcouncil", 0x4D0: "diplomacy", 0x554: "datalink" };
const IFACE_BUF        = 0x00798668;
const MAIN_PAL         = 0x0094C590;  // PALETTEENTRY[256] r,g,b,flags
const G_ART_SPR        = 0x00A35FC0;  // pcave2 0xA0C000 + 0x29FC0
const G_SCALE          = 0x00668740;  // the value the SD2 thunk compares to 0x10
const BUFFER_LOAD_PCX  = 0x005D7DE0;  // thiscall; pristine SEH prologue 6A FF 68 ...
const SCRATCH_BUF      = 0x009B6080;  // g_sprite_load_scratch
const ART_CORE         = 0x00A28AB0;  // thunk_art_core (pcave2+0x1CAB0), E8-called from 0x5E4C01; entry push esi / mov esi,ecx

function hex(v) { return "0x" + (v >>> 0).toString(16); }
function pp(v) { return ptr(hex(v)); }

function fnv(bytes) {
    let h = 0x811c9dc5;
    for (let i = 0; i < bytes.length; i++) { h ^= bytes[i]; h = Math.imul(h, 0x01000193) >>> 0; }
    return h >>> 0;
}
function hexBytes(bytes) {
    let s = "";
    for (let i = 0; i < bytes.length; i++) s += (bytes[i] < 16 ? "0" : "") + bytes[i].toString(16);
    return s;
}

const seenPal = new Set();
// Hash a 1024-byte colour table; dump it in full the first time each distinct table is seen.
function palTag(addr, label) {
    try {
        const b = new Uint8Array(addr.readByteArray(1024));
        const h = fnv(b);
        if (!seenPal.has(h)) {
            seenPal.add(h);
            log(`PAL ${hex(h)} first-seen-as=${label} bytes=${hexBytes(b)}`);
        }
        return hex(h);
    } catch (e) { return "READ-FAIL"; }
}

// Sprite fields per reference_smac_sprite_struct_fields: data +4, pitch +0xC, w +0x10, h +0x14;
// draw offsets +0x20/+0x24. Also +0x18/+0x1C (an older probe read w/h there) to settle it.
function spriteInfo(sp) {
    try {
        const b = pp(sp);
        const data = b.add(4).readPointer();
        const pitch = b.add(0xC).readS32(), w = b.add(0x10).readS32(), h = b.add(0x14).readS32();
        const f18 = b.add(0x18).readS32(), f1c = b.add(0x1C).readS32();
        const ox = b.add(0x20).readS32(), oy = b.add(0x24).readS32();
        let chash = "-";
        const ah = Math.abs(h), st = pitch > 0 ? pitch : w;
        if (!data.isNull() && w > 0 && ah > 0 && st * ah <= 0x100000) {
            chash = hex(fnv(new Uint8Array(data.readByteArray(st * ah))));
        }
        return { data: hex(data.toUInt32()), pitch, w, h, f18, f1c, ox, oy, chash };
    } catch (e) { return { err: String(e) }; }
}
function fmtSprite(s) {
    if (s.err) return "ERR " + s.err;
    return `data=${s.data} pitch=${s.pitch} w=${s.w} h=${s.h} [+18]=${s.f18} [+1c]=${s.f1c} ` +
           `off=${s.ox},${s.oy} hash=${s.chash}`;
}

// sprite address -> "f<N>:<slot>" for the 4 portrait slots of factions 0..7
function slotOf(ecx) {
    const d = (ecx >>> 0) - SLOT_BLOCK;
    if (d < 0 || d >= 8 * FACTION_STRIDE) return null;
    const f = Math.floor(d / FACTION_STRIDE), off = d % FACTION_STRIDE;
    return SLOTS[off] ? `f${f}:${SLOTS[off]}` : null;
}

let drawTotal = 0;
const seenDraw = new Set();

if (requireBase()) {
    installAVHandler("portrait_palette");

    Interceptor.attach(VA(LOAD_FACTION_ART), {
        onEnter() {
            this.f = arg(this.context.esp, 1) | 0;
            this.ret = this.returnAddress;
        },
        onLeave() {
            const f = this.f;
            let g = "?";
            try { g = VA(G_SCALE).readS32(); } catch (e) { }
            log(`LOAD f=${f} caller=${this.ret} g=${g} ifacePal=${palTag(VA(IFACE_BUF).add(0xA4), "iface@load f" + f)} ` +
                `mainPal=${palTag(VA(MAIN_PAL), "main@load f" + f)}`);
            if (f < 0 || f > 7) { log(`  f out of 0..7 — slot block not indexed`); return; }
            for (let k = 0; k < N_SPRITES; k++) {
                const off = k * SPRITE_STRIDE;
                const sp = SLOT_BLOCK + f * FACTION_STRIDE + off;
                const tag = SLOTS[off] ? " <" + SLOTS[off] + ">" : "";
                log(`  spr[${k}] +${hex(off)} ${hex(sp)}${tag} ${fmtSprite(spriteInfo(VA(sp).toUInt32()))}`);
            }
        }
    });

    // Every PCX the game loads (first sight per name+caller): finds where non-faction portraits
    // (native life etc.) come from. thiscall: ecx=Buffer*, [esp+4]=filename.
    const seenPcx = new Set();
    let scratchName = "";   // last file loaded into g_sprite_load_scratch (filename-backed sprites)
    Interceptor.attach(VA(BUFFER_LOAD_PCX), {
        onEnter() {
            let name = "?";
            try { name = pp(arg(this.context.esp, 1)).readCString(); } catch (e) { }
            if ((this.context.ecx.toUInt32() >>> 0) === SCRATCH_BUF) scratchName = name;
            const k = name + "|" + this.returnAddress;
            if (seenPcx.has(k)) return;
            seenPcx.add(k);
            log(`PCX "${name}" buf=${hex(this.context.ecx.toUInt32())} caller=${this.returnAddress}`);
        }
    });

    // NATIVE-LIFE portraits (BT*.pcx, 96x115) are filename-backed: the blit core loads the file
    // into g_sprite_load_scratch each draw, then CALLs thunk_art_core @0x5E4C01 with
    // ecx=scratch Buffer and 6 stack args. Log args, scratch dims + table, arg1's table (if it
    // is a Buffer), and the chain, once per (file, caller, args).
    const seenCore = new Set();
    Interceptor.attach(VA(ART_CORE), {
        onEnter() {
            if (!/^bt/i.test(scratchName)) return;
            const sp = this.context.esp;
            const a = [1, 2, 3, 4, 5, 6].map(n => argS(sp, n));
            const k = scratchName + "|" + this.returnAddress + "|" + a.join(",");
            if (seenCore.has(k)) return;
            seenCore.add(k);
            let sw = "?", sh = "?";
            try { sw = VA(SCRATCH_BUF).add(0x80).readS32(); sh = VA(SCRATCH_BUF).add(0x84).readS32(); } catch (e) { }
            let g = "?";
            try { g = VA(G_SCALE).readS32(); } catch (e) { }
            const scratchPal = palTag(VA(SCRATCH_BUF).add(0xA4), "scratch " + scratchName);
            let a1Pal = "n/a", a1wh = "";
            try {
                const b = pp(a[0]);
                a1wh = ` (${b.add(0x80).readS32()}x${b.add(0x84).readS32()})`;
                a1Pal = palTag(b.add(0xA4), "art_core arg1 " + scratchName);
            } catch (e) { }
            log(`NATIVE "${scratchName}" art_core ret=${this.returnAddress} g=${g} args=${a.map(hex).join(",")} ` +
                `arg1${a1wh} pal=${a1Pal} scratch=${sw}x${sh} scratchPal=${scratchPal} ` +
                `mainPal=${palTag(VA(MAIN_PAL), "main@native")}\n    bt: ${backtrace(this.context)}`);
        }
    });

    function backtrace(ctx) {
        try {
            return Thread.backtrace(ctx, Backtracer.FUZZY).slice(0, 8).map(a => a.toString()).join(" < ");
        } catch (e) { return "bt-fail"; }
    }

    // Portrait-SHAPED draws from sprites outside the faction slot block (native life portraits
    // and any other leader-like art): first sight per (sprite, caller), with a backtrace.
    const seenOther = new Set();
    function otherPortrait(ctx, ecx, retAddr) {
        let w, h;
        try { w = pp(ecx).add(0x10).readS32(); h = Math.abs(pp(ecx).add(0x14).readS32()); } catch (e) { return; }
        if (!(w >= 32 && h > w && h <= 400)) return;
        const k = hex(ecx) + "|" + retAddr;
        if (seenOther.has(k)) return;
        seenOther.add(k);
        const sp = ctx.esp;
        const dest = arg(sp, 1) >>> 0, num = argS(sp, 5), den = argS(sp, 6);
        log(`OTHER-PORTRAIT spr=${hex(ecx)} ret=${retAddr} dest=${hex(dest)} scale=${num}/${den} ` +
            `src: ${fmtSprite(spriteInfo(ecx))}\n    bt: ${backtrace(ctx)}`);
    }

    Interceptor.attach(VA(SD2_CAVE), {
        onEnter() {
            const ecx = this.context.ecx.toUInt32() >>> 0;
            const slot = slotOf(ecx);
            const isArt = ecx === (VA(G_ART_SPR).toUInt32() >>> 0);
            if (!slot && !isArt) { otherPortrait(this.context, ecx, this.returnAddress); return; }
            const sp = this.context.esp;
            const dest = arg(sp, 1) >>> 0, key = argS(sp, 2), x = argS(sp, 3), y = argS(sp, 4);
            const num = argS(sp, 5), den = argS(sp, 6);
            const s = spriteInfo(ecx);
            if (isArt && !(s.h && Math.abs(s.h) > s.w && s.w >= 32)) return;  // non-portrait art
            drawTotal++;
            let g = "?";
            try { g = VA(G_SCALE).readS32(); } catch (e) { }
            const who = slot || "G_ART_SPR";
            const pal = palTag(pp(dest).add(0xA4), `dest ${hex(dest)} ${who}`);
            const key2 = `${who}|${this.returnAddress}|${hex(dest)}|${num}/${den}|${pal}|${s.chash}`;
            if (seenDraw.has(key2)) return;
            seenDraw.add(key2);
            let dw = "?", dh = "?";
            try { dw = pp(dest).add(0x80).readS32(); dh = pp(dest).add(0x84).readS32(); } catch (e) { }
            log(`DRAW ${who}${isArt ? " !!PORTRAIT-SHAPED VIA g_art_spr!!" : ""} ret=${this.returnAddress} ` +
                `dest=${hex(dest)} (${dw}x${dh}) key=${key} at=${x},${y} scale=${num}/${den}` +
                `${num < den ? " !!BELOW-NATIVE!!" : ""} g=${g} destPal=${pal} ` +
                `mainPal=${palTag(VA(MAIN_PAL), "main@draw " + who)} src: ${fmtSprite(s)}` +
                (slot && slot.startsWith("f0:") ? `\n    bt: ${backtrace(this.context)}` : ""));
        }
    });

    setInterval(() => log(`.. alive: portrait draws=${drawTotal} distinct=${seenDraw.size} palettes=${seenPal.size}`), 15000);
}
