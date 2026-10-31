'use strict';
// SMACX modal regression PROBE (Layer 2) -- NUMERIC capture only.
//
// Load AFTER frida_common.js:
//   frida -f <exe> -l ..\scripts\frida_common.js -l probe_modal.js
// (run-capture.bat builds that command for you.)
//
// Hands-off while you navigate the game by hand: watches
// Popup_on_draw_background (0x405c80, __fastcall ecx=popup). For each NEW modal
// (keyed by title, so the same modal isn't re-captured) it reads the
// regression-relevant popup-layout struct fields and writes
// snapshots/<slug>@<res>.json (the numeric golden).
//
// NOTE: pixel/PNG capture and per-button capture were both removed -- no single
// buffer holds the fully composited modal, and button capture was dominated by
// startup encyclopedia buttons + a non-deterministic parent pointer. The
// reproducible regression signal is the popup layout geometry. See memory
// project-smac-l2-pixel-capture.
//
// Offsets cite-checked against hook_popup_layout.js / hook_box_thickness.js /
// hook_button_layout.js and symbols/terranx.h.

globalThis.LOG_PATH = "D:/SmacxUi/work/tests/probe_modal.log";

// ---- config ----------------------------------------------------------------
const OUT_DIR = (globalThis.SNAP_DIR || "D:/SmacxUi/work/tests/snapshots").replace(/\\/g, "/");

const POPUP_ON_DRAW   = 0x405c80;   // __fastcall, ecx = popup (GraphicWin); titled-popup bg pass

const G_SCALE   = 0x668740;         // g_popup_scale_num  (g; native = 16)
const SCREEN_W  = 0x9b7b1c;
const SCREEN_H  = 0x9b7b20;

// popup struct field offsets ------------------------------------------------
const F = {
  branch:      0xa14,   // 0 = titled/generic else-branch, 0x733990 = list branch
  title:       0xa48,   // char*
  frameL:      0x474, frameT: 0x478, frameR: 0x47c, frameB: 0x480,
  box_w:       0x30bc, box_h: 0x30c0,
  band:        0x30d0, content_h: 0x30d4, content_w: 0x30d8,
  pad_x:       0x30e0, pad_y: 0x30e4,
  header:      0x30e8, footer: 0x30ec, margin_l: 0x30f0, margin_r: 0x30f4,
  win_w:       0x4c4, win_h: 0x4c8,
  intrinsic_w: 0x21fc,
  dialog_elem: 0x21d0,  // [[pop+0x21d0]+8] -> dialog sub-struct
};
// dialog sub-struct (dyn) field offsets
const D = { type: 0x60, row_w: 0x64, row_h: 0x68, font: 0x70, row_count: 0xcc };

// ---- helpers ---------------------------------------------------------------
function rd(p, off)  { try { return p.add(off).readS32(); } catch (e) { return null; } }
function rdU(p, off) { try { return p.add(off).readU32() >>> 0; } catch (e) { return 0; } }
function rdAbsS(va)  { try { return VA(va).readS32(); } catch (e) { return null; } }
function readStr(u32ptr) {
  if (!u32ptr) return null;
  try { return ptr("0x" + (u32ptr >>> 0).toString(16)).readUtf8String(); } catch (e) { return null; }
}
function slugify(s) {
  if (!s) return null;
  return s.toLowerCase().replace(/['"]/g, "").replace(/[^a-z0-9]+/g, "-")
          .replace(/^-+|-+$/g, "").slice(0, 60) || null;
}
function resTag() {
  const w = rdAbsS(SCREEN_W), h = rdAbsS(SCREEN_H);
  return (w && h) ? `${w}x${h}` : "unkres";
}
function writeText(path, str) {
  try { const f = new File(path, "w"); f.write(str); f.flush(); f.close(); return true; }
  catch (e) { log("  write FAIL " + path + " : " + e); return false; }
}

// NOTE: button capture (BaseButton_init 0x607210) was removed -- the encyclopedia
// buttons are built at startup and leak into the first captured modal, the rules
// controls are dialog rows (not BaseButtons), and the per-button parent is a
// non-deterministic heap pointer (breaks reproducibility). The reproducible,
// regression-critical signal is the popup layout geometry captured below.
//
// NOTE: an earlier build hooked the title Buffer_set_font CALL (0x4060aa) to
// record the title font, but a trampoline on that exact instruction suppressed
// the title render under Frida. Don't re-add it -- title_font was opportunistic.

// ---- numeric snapshot at popup background draw -----------------------------
const capturedSlugs = {};     // slug -> true (capture once per modal title)

function dialogFields(pp) {
  try {
    const elem = rdU(pp, F.dialog_elem);
    if (!elem) return null;
    const dyn = ptr("0x" + elem.toString(16)).add(8).readU32() >>> 0;
    if (!dyn) return null;
    const d = ptr("0x" + dyn.toString(16));
    return {
      type:      rd(d, D.type),  row_w: rd(d, D.row_w), row_h: rd(d, D.row_h),
      font:      rd(d, D.font),  row_count: rd(d, D.row_count),
    };
  } catch (e) { return null; }
}

Interceptor.attach(VA(POPUP_ON_DRAW), {
  onEnter() {
    const pp = this.context.ecx;
    const titlePtr = rdU(pp, F.title);
    const title = readStr(titlePtr);
    const dyn = dialogFields(pp);
    const slug = slugify(title)
      || `untitled-t${dyn ? dyn.type : "x"}-${rd(pp, F.box_w)}x${rd(pp, F.box_h)}`;

    if (capturedSlugs[slug]) return;    // capture once per modal
    capturedSlugs[slug] = true;

    const rec = {
      modal: slug,
      title: title,
      resolution: { w: rdAbsS(SCREEN_W), h: rdAbsS(SCREEN_H) },
      scale_num: rdAbsS(G_SCALE),
      branch: rdU(pp, F.branch) === 0x733990 ? "list" : "else",
      screen_rect: [rd(pp, F.frameL), rd(pp, F.frameT), rd(pp, F.frameR), rd(pp, F.frameB)],
      box:    { w: rd(pp, F.box_w), h: rd(pp, F.box_h) },
      window: { w: rd(pp, F.win_w), h: rd(pp, F.win_h) },
      content:{ w: rd(pp, F.content_w), h: rd(pp, F.content_h) },
      pad:    { x: rd(pp, F.pad_x), y: rd(pp, F.pad_y) },
      header_reserve: rd(pp, F.header),
      footer_reserve: rd(pp, F.footer),
      margins:{ l: rd(pp, F.margin_l), r: rd(pp, F.margin_r) },
      band: rd(pp, F.band),
      intrinsic_w: rd(pp, F.intrinsic_w),
      dialog: dyn,
    };

    const path = `${OUT_DIR}/${slug}@${resTag()}.json`;
    if (writeText(path, JSON.stringify(rec, null, 2)))
      log(`[probe] numeric  ${slug}@${resTag()}  box=${rec.box.w}x${rec.box.h} g=${rec.scale_num}`);
  }
});

requireBase();
log(`[probe_modal] armed (numeric-only). OUT_DIR=${OUT_DIR}`);
log('  %resume, then navigate directly to each modal. Snapshots write automatically. quit when done.');
