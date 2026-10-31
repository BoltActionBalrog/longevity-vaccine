"use strict";
// MODERN CONTROL SET in-game observer -- OBSERVER ONLY, function-ENTRY hosts only (first bytes of every host
// read on the live exe 2026-10-07: plain prologues; the DLL's vtable wrappers call the engine thunks, which jmp
// to these handlers, so hooking the handlers sees the wrapped calls too).
//
// What it answers for the uimod.dll build with [UIMod] ModernControls (modernctl.cpp):
//   (1) right click -> NetDaemon_lock_veh from the INLINE site (ret 0x46DF34) with the right unit, no menu,
//       move mode kept (set_move/set_view never called with force=1 on that path);
//   (2) the hover line: MapWin_on_mouse_move entered with drag=1/sel=1 only while the DLL wrapper holds them,
//       back to 0 at its exit; the overlay 0x937118 shown/hidden by whom (Win_show/Win_hide callers); cost per
//       move (avg/max microseconds, printed every 3 s) with the line on vs off;
//   (3) Shift+left click -> MapWin_right_menu from MapWin_click (ret 0x46E565) on a LEFT release;
//   (4) the right-drag child: right press -> MapWin_on_left_down (ret inside uimod.dll) -> go_timer -> the
//       right release reaching MapWin_click with is_right=0 (the DLL's left-click route) -> inline lock_veh;
//   (5) Shift/Ctrl key-downs: WinProc never sees an auto-repeat (lParam bit 30) for VK_SHIFT/VK_CONTROL;
//   (6) draw_my_dest (the committed path) vs the overlay the hover line clears.
// Drive (Modern ON, child OFF): select a unit, hover across tiles (watch the line), right-click a far tile, a
// near tile, the unit's own tile; press V (view mode) and right-click with the cursor on an idle unit of yours,
// then on a foreign unit; Shift+left click a tile (menu), ESC; hold Shift 2 s then Shift+left click again;
// left press-and-hold on a tile (no drag must start); open a popup / the base screen / end the turn with the
// line showing. Then child ON: right hold-drag-release (move), quick right click (menu), middle-drag (no scroll:
// MapDragButton forced to none), left hold (nothing). Then Modern OFF: vanilla left drag, menu, right-drag scroll.
const STAMP = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15);
globalThis.LOG_PATH = "D:/SmacxUi/work/frida_modernctl_" + STAMP + ".log";
log("=== hook_modernctl.js started ===");
installAVHandler("modernctl");
if (requireBase()) {
  const CON = VA(0x9156B0), OVERLAY = VA(0x937118), GOTIMER = VA(0x939E60);
  const G = {
    moveMode: VA(0x939288), veh: VA(0x93928C), pend: VA(0x939294), selMode: VA(0x9393C0), goWin: VA(0x68A5CC),
    morePrefs: VA(0x9A6494), ctc: VA(0x93A938), mapMouse: VA(0x90D938), modal: VA(0x9B7AE0), basepop: VA(0x9B8D7C),
    curIdx: VA(0x9392B8), curX: VA(0x9392C0), curY: VA(0x939340), vehs: VA(0x952828), gameState: VA(0x9A64C0)
  };
  const CAP = 12000;
  let lines = 0;
  function L_(s) { if (lines < CAP) { lines++; log(s); } }
  const t0 = Date.now();
  function t() { return "[" + (Date.now() - t0) + "]"; }
  function hex(v) { return "0x" + (v >>> 0).toString(16); }
  function s16(v) { v &= 0xffff; return v >= 0x8000 ? v - 0x10000 : v; }
  function where(ra) {
    const m = Process.findModuleByAddress(ra);
    return m ? m.name + "+" + hex(ra.sub(m.base).toInt32()) : ra.toString();
  }
  function vehXY(v) {
    if (v < 0 || v > 2048) return "";
    const p = G.vehs.add(v * 0x34);
    return " veh" + v + "@(" + p.readS16() + "," + p.add(2).readS16() + ") fac=" + p.add(0xE).readU8() +
      " order=" + p.add(0x11).readU8() + " flags=" + hex(p.add(4).readU32()) +
      " wp0=(" + p.add(0x14).readS16() + "," + p.add(0x1C).readS16() + ")";
  }
  function cursor() {
    const i = G.curIdx.readS32();
    if (i < 0 || i > 31) return "cur(i=" + i + ")";
    return "cur(" + G.curX.add(i * 4).readS32() + "," + G.curY.add(i * 4).readS32() + ")";
  }
  function state() {
    const veh = G.veh.readS32();
    return "move=" + G.moveMode.readS32() + " veh=" + veh + " pend=" + G.pend.readS32() + " sel=" + G.selMode.readS32() +
      " goWin=" + G.goWin.readS32() + " drag=" + CON.add(0x1DD80).readS32() + " swallow=" + CON.add(0x1DD88).readS32() +
      " curSpr=" + hex(CON.add(0x1EF4C).readU32()) + " overlay=" + (OVERLAY.add(0x9C).readU32() & 1) +
      " menuPref=" + ((G.morePrefs.readU32() & 0x100) ? 1 : 0) + " ctc=" + G.ctc.readS32() +
      " modal=" + hex(G.modal.readU32()) + " bpop=" + hex(G.basepop.readU32()) + " " + cursor() + vehXY(veh);
  }
  function a(sp, n) { return sp.add(n * 4).readS32(); }
  function hostOk(va) {
    const b = VA(va).readByteArray(2);
    const u = new Uint8Array(b);
    return !(u[0] === 0xE9 || u[0] === 0xE8 || (u[0] === 0x68));
  }
  for (const va of [0x46D5D0, 0x46ED30, 0x46EC10, 0x46EBA0, 0x46EBE0, 0x46F000, 0x46C0D0, 0x531020, 0x5310F0, 0x50F170,
                    0x50EF50, 0x616780, 0x5ED9D0, 0x5EDCD0, 0x4B4BF0, 0x511520, 0x511480, 0x4D2F00, 0x5C0CB0, 0x5F0650]) {
    if (!hostOk(va)) L_("!! host " + hex(va) + " starts with a jump/call/push -- NOT attaching (baked detour?)");
  }

  // --- raw buttons at the game WndProc + the Shift/Ctrl key-down census
  const MSG = { 0x201: "LDOWN", 0x202: "LUP", 0x203: "LDBLCLK", 0x204: "RDOWN", 0x205: "RUP", 0x206: "RDBLCLK",
                0x207: "MDOWN", 0x208: "MUP", 0x209: "MDBLCLK" };
  let modKeyDowns = 0, modRepeats = 0;
  let lastMoveLp = 0, lastMoveFrom = "";
  Interceptor.attach(VA(0x5F0650), {
    onEnter() {
      const sp = this.context.esp;
      const msg = sp.add(8).readU32();
      const wp = sp.add(0xC).readU32(), lp = sp.add(0x10).readU32();
      if (msg === 0x100 && (wp === 0x10 || wp === 0x11)) {          // WM_KEYDOWN Shift / Ctrl
        modKeyDowns++;
        if (lp & 0x40000000) { modRepeats++; L_(t() + " !! WINPROC saw a Shift/Ctrl AUTO-REPEAT key-down (the filter should drop these)"); }
        return;
      }
      if (msg === 0x200) { lastMoveLp = lp; lastMoveFrom = where(this.returnAddress); return; }   // WM_MOUSEMOVE (as the engine got it)
      const name = MSG[msg];
      if (!name) return;
      L_(t() + " WINPROC " + name + " x=" + s16(lp) + " y=" + s16(lp >>> 16) + " wParam=" + hex(wp) + " from=" + where(this.returnAddress));
    }
  });

  const GetAsync = new NativeFunction(Process.getModuleByName("user32.dll").getExportByName("GetAsyncKeyState"), "int16", ["int"]);
  // --- the map handlers (this = Console+0x21A6C)
  function handler(va, name, withState) {
    Interceptor.attach(VA(va), {
      onEnter() { const sp = this.context.esp; this.n = name;
        L_(t() + " >> " + name + " xy=" + a(sp, 1) + "," + a(sp, 2) + " from=" + where(this.returnAddress) + (withState ? " | " + state() : "")); },
      onLeave() { if (withState) L_(t() + " << " + this.n + " | " + state()); }
    });
  }
  handler(0x46ED30, "MapWin_on_left_down", true);
  handler(0x46EC10, "MapWin_on_right_down", true);
  handler(0x46EBA0, "MapWin_on_left_click", true);
  handler(0x46EBE0, "MapWin_on_right_click", true);
  Interceptor.attach(VA(0x46D5D0), {              // MapWin_click(this=Console, px, py, is_right)
    onEnter() { const sp = this.context.esp;
      L_(t() + "  MapWin_click px,py=" + a(sp, 1) + "," + a(sp, 2) + " is_right=" + a(sp, 3) + " shift=" + ((GetAsync(0x10) & 0x8000) ? 1 : 0) +
        " ctrl=" + ((GetAsync(0x11) & 0x8000) ? 1 : 0)); }
  });

  // --- consequences
  Interceptor.attach(VA(0x46C0D0), {              // MapWin_right_menu(this, tx, ty, dev_x, dev_y)
    onEnter() { const sp = this.context.esp; L_(t() + "   MENU open tile=(" + a(sp, 1) + "," + a(sp, 2) + ") from=" + where(this.returnAddress) + " | " + state()); },
    onLeave() { L_(t() + "   MENU closed | " + state()); }
  });
  let lastLocked = -1;
  Interceptor.attach(VA(0x531020), {              // NetDaemon_lock_veh(this, int* veh, ...)
    onEnter() { const sp = this.context.esp;
      try { lastLocked = sp.add(4).readPointer().readS32(); } catch (e) { lastLocked = -1; }
      L_(t() + "   LOCK veh=" + lastLocked + " from=" + where(this.returnAddress) + vehXY(lastLocked)); }
  });
  Interceptor.attach(VA(0x5310F0), { onEnter() { L_(t() + "   UNLOCK from=" + where(this.returnAddress) + vehXY(lastLocked)); } });
  Interceptor.attach(VA(0x50F170), { onEnter() { const sp = this.context.esp; L_(t() + "   go_timer(" + a(sp, 1) + ") from=" + where(this.returnAddress) + " | " + state()); } });
  let lastReset = "", resetRepeat = 0;
  Interceptor.attach(VA(0x50EF50), {              // go_reset (dedup the key-repeat storm)
    onEnter() { const w = where(this.returnAddress);
      if (w === lastReset) { resetRepeat++; return; }
      if (resetRepeat) L_(t() + "   go_reset x" + resetRepeat + " more from " + lastReset);
      lastReset = w; resetRepeat = 0;
      L_(t() + "   go_reset from=" + w + " | " + state()); }
  });
  Interceptor.attach(VA(0x616780), {              // Time_stop(this=Time) -- only the go timer
    onEnter() { if (this.context.ecx.equals(GOTIMER)) L_(t() + "   Time_stop(g_go_timer) from=" + where(this.returnAddress)); }
  });
  Interceptor.attach(VA(0x5ED9D0), { onEnter() { if (this.context.ecx.equals(OVERLAY)) L_(t() + "   OVERLAY Win_show from=" + where(this.returnAddress)); } });
  Interceptor.attach(VA(0x5EDCD0), { onEnter() { if (this.context.ecx.equals(OVERLAY)) L_(t() + "   OVERLAY Win_hide from=" + where(this.returnAddress)); } });
  Interceptor.attach(VA(0x4B4BF0), { onEnter() { const sp = this.context.esp; L_(t() + "   draw_my_dest(" + a(sp, 1) + ") from=" + where(this.returnAddress) + " overlay=" + (OVERLAY.add(0x9C).readU32() & 1)); } });
  Interceptor.attach(VA(0x511520), { onEnter() { const sp = this.context.esp; L_(t() + "   set_move force=" + a(sp, 1) + " from=" + where(this.returnAddress)); } });
  Interceptor.attach(VA(0x511480), { onEnter() { const sp = this.context.esp; L_(t() + "   set_view force=" + a(sp, 1) + " from=" + where(this.returnAddress)); } });
  Interceptor.attach(VA(0x4D2F00), { onEnter() { const sp = this.context.esp; L_(t() + "   ACTIVATE tile=(" + a(sp, 1) + "," + a(sp, 2) + ") from=" + where(this.returnAddress)); } });
  Interceptor.attach(VA(0x5C0CB0), {              // veh_find(x, y, faction, -1) -> veh
    onEnter() { const sp = this.context.esp; this.args = a(sp, 1) + "," + a(sp, 2) + " fac=" + a(sp, 3); this.w = where(this.returnAddress); },
    onLeave(rv) { if (this.w.indexOf("uimod") >= 0 || this.w.indexOf("terranx") >= 0 && this.w.indexOf("+0x10f2") >= 0)
      L_(t() + "   veh_find(" + this.args + ") -> " + rv.toInt32() + " from=" + this.w + vehXY(rv.toInt32())); }
  });

  // --- the hover line: MapWin_on_mouse_move with drag/sel held by the DLL wrapper; cost per move
  let movesOn = 0, movesOff = 0, usOnSum = 0, usOnMax = 0, usOffSum = 0, usOffMax = 0, lastOn = -1;
  Interceptor.attach(VA(0x46F000), {
    onEnter() {
      this.on = CON.add(0x1DD80).readS32() !== 0 && G.selMode.readS32() !== 0;
      this.t = Date.now();
      const on = this.on ? 1 : 0;
      if (on !== lastOn) { lastOn = on; L_(t() + "   mouse_move: line " + (on ? "ON" : "off") + " from=" + where(this.returnAddress) + " | " + state()); }
    },
    onLeave() {
      const us = (Date.now() - this.t) * 1000;
      if (this.on) { movesOn++; usOnSum += us; if (us > usOnMax) usOnMax = us; }
      else { movesOff++; usOffSum += us; if (us > usOffMax) usOffMax = us; }
    }
  });
  setInterval(function () {
    if (!movesOn && !movesOff) return;
    L_(t() + "   moves: line ON " + movesOn + " (avg " + (movesOn ? Math.round(usOnSum / movesOn) : 0) + " us, max " + usOnMax +
      ") | off " + movesOff + " (avg " + (movesOff ? Math.round(usOffSum / movesOff) : 0) + " us, max " + usOffMax + ")" +
      " | Shift/Ctrl key-downs " + modKeyDowns + " repeats " + modRepeats);
    movesOn = movesOff = usOnSum = usOnMax = usOffSum = usOffMax = 0;
  }, 3000);
  // --- which window the engine resolves under the pointer: Win_get_mouse_window 0x5F6F10 (cdecl int* x, int* y)
  // -> Win* (coords rewritten window-local). One line per change of resolved window (per caller kind), so the
  // band above the console, COMMLINK, MENU and the HUD strip each show their window, its vtable and origin.
  let lastResolved = ptr(0), lastResKey = "";
  function winDesc(w) {
    if (w.isNull()) return "NULL";
    const vt = w.readPointer();
    const org = "(" + (w.add(0x13C).readS32() + w.add(0x14C).readS32()) + "," + (w.add(0x140).readS32() + w.add(0x150).readS32()) + ")";
    const tag = w.equals(CON.add(0x23D94)) ? " =MAP" : "";
    return w + " vt=" + where(vt) + " org=" + org + " f98=" + hex(w.add(0x98).readU32()) + tag;
  }
  Interceptor.attach(VA(0x5F6F10), {
    onEnter() {
      const sp = this.context.esp;
      this.px = sp.add(4).readPointer(); this.py = sp.add(8).readPointer();
      this.rx = this.px.readS32(); this.ry = this.py.readS32();
      this.from = where(this.returnAddress);
    },
    onLeave(rv) {
      lastResolved = rv;
      const key = this.from + "|" + rv;
      if (key === lastResKey) return;
      lastResKey = key;
      L_(t() + "   WIN raw=(" + this.rx + "," + this.ry + ") -> local=(" + this.px.readS32() + "," + this.py.readS32() + ") from=" + this.from +
         " win=" + winDesc(rv) + " | nc stash=" + hex(VA(0x9B7AAC).readU32()) + " 9B7AA4=" + hex(VA(0x9B7AA4).readU32()));
    }
  });

  // --- pointer -> tile census (the band above the console; edge drags): MapWin_pixel_to_tile 0x463040 called
  // from MapWin_on_mouse_move (ret 0x46F06A), thiscall(this=Console, px, py, int* tx, int* ty) RET 0x10.
  // One line per change of (rv, tile) or map scroll: raw WM_MOUSEMOVE as the WinProc got it, window-local px/py,
  // the origin fields the conversion subtracts, the result, and whether the line is drawn.
  let lastKey = "";
  Interceptor.attach(VA(0x463040), {
    onEnter() {
      this.mine = this.returnAddress.equals(VA(0x46F06A));
      if (!this.mine) return;
      const sp = this.context.esp;
      this.px = a(sp, 1); this.py = a(sp, 2);
      this.ptx = sp.add(12).readPointer(); this.pty = sp.add(16).readPointer();
    },
    onLeave(rv) {
      if (!this.mine) return;
      const r = rv.toInt32();
      const tx = r === 0 ? this.ptx.readS32() : -999, ty = r === 0 ? this.pty.readS32() : -999;
      const org = CON.add(0x1DDAC).readS32() + "," + CON.add(0x1DDB0).readS32() + " ctr=" + CON.add(0x1DD9C).readS32() + "," + CON.add(0x1DDA0).readS32();
      const key = r + ":" + tx + "," + ty + "|" + org;
      if (key === lastKey) return;
      lastKey = key;
      L_(t() + "   PT raw=(" + s16(lastMoveLp) + "," + s16(lastMoveLp >>> 16) + ") via " + lastMoveFrom + " local=(" + this.px + "," + this.py +
         ") -> rv=" + r + " tile=(" + tx + "," + ty + ") org=" + org + " drag=" + CON.add(0x1DD80).readS32() + " sel=" + G.selMode.readS32() +
         " overlay=" + (OVERLAY.add(0x9C).readU32() & 1) + " resolved=" + lastResolved + " engineRaw=(" + VA(0x9B6628).readS32() + "," + VA(0x9B662C).readS32() + ") mapOrg=(" +
         (CON.add(0x23D94 + 0x13C).readS32() + CON.add(0x23D94 + 0x14C).readS32()) + "," +
         (CON.add(0x23D94 + 0x140).readS32() + CON.add(0x23D94 + 0x150).readS32()) + ")");
    }
  });

  // --- camera census: who recentres the map, and which preference bits were set at the time.
  // Hosts are plain function entries, and never a site uimod.dll byte-checks at startup (a Frida hook rewrites
  // the entry first): NOT MapWin_set_center 0x46B1F0 (detoured) nor Console_center 0x515400 (checked).
  // BaseWin_exit's origin change shows the Console_center recentre.
  function origin() {
    return CON.add(0x1DD9C).readS32() + "," + CON.add(0x1DDA0).readS32() + "," + CON.add(0x1DDAC).readS32() + "," + CON.add(0x1DDB0).readS32();
  }
  function prefBits() {
    const p = VA(0x9A6490).readU32(), m = G.morePrefs.readU32();
    return "noCenterOrders=" + ((p & 0x80000) ? 1 : 0) + " zoomNoRecenter=" + ((m & 0x4) ? 1 : 0);
  }
  const CAM = [
    [0x46B310, "MapWin_focus", 2],     // this=Console, x, y
    [0x5108A0, "Console_focus", 2],    // this=Console, x, y, faction
    [0x510F50, "Console_ready", 0],
    [0x41A4C0, "BaseWin_exit", 0],
    [0x41A920, "BaseWin_zoom", 1],     // this=BaseWin, base_id, a3
    [0x48C650, "popb", 0]
  ];
  for (const [va, name, nargs] of CAM) {
    if (!hostOk(va)) { L_("!! camera host " + hex(va) + " " + name + " is patched -- NOT attaching"); continue; }
    Interceptor.attach(VA(va), {
      onEnter() {
        const sp = this.context.esp;
        this.o = origin();
        let args = "";
        for (let i = 1; i <= nargs; i++) args += (i > 1 ? "," : "") + a(sp, i);
        this.desc = name + "(" + args + ") from=" + where(this.returnAddress);
        if (name === "BaseWin_exit" || name === "BaseWin_zoom" || name === "popb" || name === "Console_ready")
          L_(t() + "   CAM> " + this.desc + " | " + prefBits() + " " + cursor() + vehXY(G.veh.readS32()));
      },
      onLeave(rv) {
        const o2 = origin();
        if (o2 !== this.o) L_(t() + "   CAM* " + this.desc + " MOVED THE MAP origin " + this.o + " -> " + o2 + " rv=" + rv.toInt32() + " | " + prefBits());
      }
    });
  }

  L_("hooks installed; " + state() + " | " + prefBits());
  setTimeout(function () { L_("screen " + VA(0x9B7B1C).readS32() + "x" + VA(0x9B7B20).readS32()); }, 15000);
}
