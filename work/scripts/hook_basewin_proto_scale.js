// HISTORICAL PROTOTYPE -- read it, do not run it as is. It WRITES to the game process at
// addresses that were right for the build it was written against; a later bake moves code
// caves, and a stale offset crashes the game. The shipped fix is the baked patch group in
// work\patches\patches.yaml; this file is kept as the readable record of the logic.

"use strict";
// hook_basewin_proto_scale.js -- PROTOTYPE (mutates draw args at runtime, no exe writes).
//
// Question this answers IN-GAME: what does the base screen look like if we keep the
// center BaseWin rendering native 758x490 and scale it at COMPOSITE time through the
// engine's own Buffer_draw_2 num/den scaler (the vanilla call already passes n/d=1/1)?
//
// Law (all from vanilla x g/16):
//   W' = 758*g/16, H' = 490*g/16
//   x' = (SW - 758*g/16)/2 + 16*g/16     (vanilla: (SW-726)/2 = centered +16 nudge)
//   y' = (SH - strip_h) - 490*g/16       (vanilla: bottom rests on console strip)
//
// KNOWN LIMITS (prototype only -- do not judge these as defects):
//   - Input/hit-testing is NOT remapped: clicks inside the base screen will land on the
//     OLD native rects. Navigate/close with keyboard (ESC) if buttons misbehave.
//   - FlatButton children may still composite native if they blit to screen directly;
//     the log records every direct-to-screen blit while the base is open so we can see
//     exactly which paths need covering in the real fix.
//   - Partial-canvas copy_3 redraws are logged but NOT scaled (only full-canvas blits).
//
// Attach audit (all entries verified clean this workstream, 2026-07-18):
//   Buffer_draw_2 0x5D84C0, Buffer_copy_3 0x5D9610, BaseWin_on_status 0x41DAD0.
//   NO-ATTACH respected: no GraphicWin_init, no Buffer_box_sprite/wmfr_l/Sprite_draw_2/
//   Sprite_blit_scaled_core, no Popup_* zones.

globalThis.LOG_PATH = "D:/SmacxUi/work/frida_basewin_proto.log";
log("=== hook_basewin_proto_scale.js started ===");
installAVHandler("basewin_proto");

if (requireBase()) {
    const CANVAS = 0x6A7A6C;         // BaseWin canvas Buffer (BaseWin_g + 0x444)
    const G = {
        ScreenW: 0x9B7B1C, ScreenH: 0x9B7B20,
        consoleStripH: 0x7AF59C,
        gCave: 0x668740,             // g_popup_scale_num (patched exe only; 0/garbage on pristine)
    };
    function gv(a) { try { return VA(a).readS32(); } catch (e) { return 0; } }
    function gval() {
        const g = gv(G.gCave);
        return (g >= 16 && g <= 64) ? g : 16;   // pristine exe / unpatched -> native no-op
    }

    const canvasPtr = VA(CANVAS);
    let baseMode = false;
    let rewrites = 0, partials = 0;
    const seenDirect = {};

    Interceptor.attach(VA(0x41DAD0), {   // BaseWin_on_status(visible)
        onEnter() {
            const vis = argS(this.context.esp, 1);
            baseMode = (vis !== 0);
            log(">> base " + (baseMode ? "OPEN" : "CLOSED") + " g=" + gval() +
                " screen=" + gv(G.ScreenW) + "x" + gv(G.ScreenH) +
                " strip_h=" + gv(G.consoleStripH));
        }
    });

    // Core rewrite: any Buffer_draw_2 whose SOURCE is the BaseWin canvas gets scaled
    // placement + n/d = g/16. Catches every composite site uniformly (flash loop,
    // redraw, generic paint) without touching the sites themselves.
    const SCREENBUF = VA(0x9B7490);      // desktop/screen Buffer object (dest of composites)
    Interceptor.attach(VA(0x5D84C0), {   // Buffer_draw_2(ecx=src; dest,key,X,Y,num,den)
        onEnter() {
            if (!this.context.ecx.equals(canvasPtr)) {
                // census: who ELSE composites straight to the screen while the base is open?
                if (baseMode && arg(this.context.esp, 1) === SCREENBUF.toUInt32()) {
                    const key = this.context.ecx.toString();
                    if (!seenDirect[key]) {
                        seenDirect[key] = 1;
                        const sp2 = this.context.esp;
                        log("direct-to-screen draw_2: src=" + key +
                            " x=" + argS(sp2, 3) + " y=" + argS(sp2, 4) +
                            " n/d=" + argS(sp2, 5) + "/" + argS(sp2, 6));
                    }
                }
                return;
            }
            const g = gval();
            if (g <= 16) return;
            const sp = this.context.esp;
            const SW = gv(G.ScreenW), SH = gv(G.ScreenH), strip = gv(G.consoleStripH);
            const W2 = Math.floor(758 * g / 16), H2 = Math.floor(490 * g / 16);
            const x2 = Math.floor((SW - W2) / 2) + g;   // vanilla +16 nudge, scaled
            const y2 = (SH - strip) - H2;
            const ox = argS(sp, 3), oy = argS(sp, 4);
            sp.add(3 * 4).writeS32(x2);
            sp.add(4 * 4).writeS32(y2);
            sp.add(5 * 4).writeS32(g);    // num
            sp.add(6 * 4).writeS32(16);   // den
            rewrites++;
            if (rewrites <= 4) {
                log("draw_2 canvas->dest=" + hexn(arg(sp, 1)) + " key=" + argS(sp, 2) +
                    " (" + ox + "," + oy + ",1/1) -> (" + x2 + "," + y2 + "," + g + "/16) " +
                    W2 + "x" + H2);
            }
        }
    });

    // Census-only: full/partial copy_3 blits out of the canvas, and (while the base is
    // open) any OTHER source blitting straight to the screen buffer -- the inventory of
    // composite paths the real fix must cover.
    Interceptor.attach(VA(0x5D9610), {   // Buffer_copy_3(ecx=src; dst,sx,sy,sw,sh,dx,dy,dw,dh)
        onEnter() {
            if (!this.context.ecx.equals(canvasPtr)) return;
            const sp = this.context.esp;
            partials++;
            if (partials <= 12) {
                log("copy_3 FROM canvas (NOT scaled): dst=" + hexn(arg(sp, 1)) +
                    " s=" + argS(sp, 2) + "," + argS(sp, 3) + " " + argS(sp, 4) + "x" + argS(sp, 5) +
                    " d=" + argS(sp, 6) + "," + argS(sp, 7) + " " + argS(sp, 8) + "x" + argS(sp, 9));
            }
        }
    });

    function hexn(n) { return "0x" + (n >>> 0).toString(16); }

    let last = -1;
    setInterval(function () {
        if (rewrites !== last) {
            last = rewrites;
            log("[alive] draw_2 rewrites=" + rewrites + " canvas copy_3 (unscaled)=" + partials);
        }
    }, 5000);

    log("attached ok: composite rewrite armed (g=" + gval() + ")");
}
