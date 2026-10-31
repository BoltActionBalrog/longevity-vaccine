---
name: project-smac-mouse-scheme-proposals
description: Modern Control Set + camera options LIVE (2026-10-14: editor gate = EditorEngaged, LIVE in ba2a91b6; editor paint-capture release + palette highlight bound USER-VERIFIED 2026-10-15 in uimod.dll 0cbc9f0d (master build incl. the other checkout's right-click pick); uimod.dll builds are NOT byte-reproducible (LTCG), MD5 = build id only) in uimod.dll modernctl.cpp (847aab7 / ec56c30 / e78fec3, DLL abd738bc; user-verified 4K PRACX 2026-10-10): map-tile click engine map (MapWin_click chain, vtable 0x66EC18, go_timer rule, StatusWin timer, PRACX drag sites) + what was built, what was dropped, and the open residue
type: project
---

Survey 2026-10-06 -> plan (a private planning document) -> BUILT
2026-10-07 in `src\uimod\src\modernctl.cpp` + `praxdrag.cpp` (uimod.dll e41f195f deployed; site test
`work\tests\test_modernctl_sites.py`; observer `scripts\hook_modernctl.js`). independent reviews done after each phase, every finding triaged. COMMITTED+PUSHED 847aab7 (feature),
ec56c30 (four vanilla fixes + polish: one PickUnit for line / right click / waypoint, move mode only; instant line
on Tab via bounded 40 ms re-posts; set_center overlay guards; overlay hidden during a smooth scroll step and
re-posted after; menu hotkey relabel; 4th waypoint swallowed) and e78fec3 (wheel capture: a synthetic arrow never
reaches the map). User-verified at 4K on PRACX 2026-10-10; CHANGELOG lines in. OPEN residue (all in
the maintainer's work log): nothing from the session itself (wheel fix + Datalinks line COMMITTED 6054951, DLL dde2c0d9, article render user-confirmed); hudmovesfix inert under Thinker; website deploy go. CLOSED
by the maintainer 2026-10-10: the in-game pass (every item fine), the no-route line 'better solution' (dropped).

**What shipped (all [UIMod], default = vanilla):** ModernControls (right click = go-to at gate 0x46E529,
own tile counts, view mode too; hover move-to line via the +0x44 wrapper; Shift+RIGHT = orders menu at
0x46E544 with EDI=1, Shift+LEFT = move cursor; NO left drag: LeftDownWrap stops go_timer unless Editor /
Ctrl / base-route flag 0x40000) · child RightClickDragsToMove (RightDownWrap arms the original left_down;
quick right click = menu; forces MapDragButton to none) · MapDragButton 2/1/0 (prax.dll imm32 rewrite,
relocation-aware: VK sites `6A 02 FF 15` abs32 == base+0x341E8) · ClickKeepsView (MapWin_set_center
0x46B1F0 entry stub, skips inside a left click when the tile is inside RenderTileBounds 0x7D3C28) ·
BaseCloseKeepsView (stub at BaseWin_exit's `call Console_center` 0x41A600; Console_center 0x515400).
REMOVED: ShiftInstantMove (ini key deleted at install; Shift branch 0x46EF9B `EB 3B` always; Shift/Ctrl
auto-repeat key filter unconditional). Dropped by the maintainer: click-lock, double-click move, middle-click
centring. Drag Hold Time slider: inert + arrows' tooltip "Requires drag to move" when Modern on / child
off -- NO greyed look (user rejected the invented disabled style as a "tacky gray rectangle").

**Traps found while building:** (1) go_timer's view-mode found-unit rule needs flag 0x4000, which idle
units never carry -> PickUnit drops that test or right click "randomly" does nothing after Shift+right
moved the cursor. (2) StatusWin's ~156 ms refresh timer (0x4B5D7C-0x4B5DC7) calls Win_hide on the go-to
overlay 0x937118 every tick (1,596 hides/session) -> the hover line flickered; the two call sites
(draw_my_dest 0x4B5D95, Win_hide 0x4B5DC2) stand aside while the line is owned. (3) Any go_reset (Shift
or Ctrl key-down) hides the overlay -> the poll posts a synthetic WM_MOUSEMOVE whenever the overlay is
hidden while owned, and when the map origin (+0x1DD9C/+0x1DDA0/+0x1DDAC/+0x1DDB0) changes under edge
scroll (stale line). (4) Thinker relocates Vehs -> read the base from veh_selectable's operand 0x5C1A39 -- an ABSOLUTE VA: rebase it through At() once. Subtracting the image base too gave 0x552828 (exe code), and a left click on a unit crashed (fixed in DLL b523cdf9, 2026-10-07). A '(relocated)' log line on a non-Thinker run means the pointer is wrong.
(5b) Base close recentres through TWO Console_center sites: BaseWin_exit 0x41A600 (cursor near the edge) and the close button in BaseWin_on_button_clicked 0x41D6A3 (move mode, selected unit 2+ tiles off screen -- the jump the maintainer saw); both stubbed by BaseCloseKeepsView ('Closing a Base Never Recenters Map'). Stock 'Don't center on units with orders' gates only Console_ready/order_veh; 'Zoom-to-base doesn't recenter map' only popb -- neither covers clicks or base close (trace-confirmed). RenderTileBounds calls a half-visible edge tile off screen, so ClickKeepsView now keeps the view for every set_center inside a left click. (5) The stock 'More' button belongs to the two-page stock tabs only; nothing of ours hides it.

**Engine facts (all read from the listing, not modelled):**
- MapWin_click 0x46D5D0 = ONE handler for both buttons (this=Console, args px,py,is_right; RET 0xC).
  Locals: [ebp-0x10]=tile x, [ebp-0x14]=tile y, [ebp+0x10]=is_right, ESI=Console, EBX=dev y.
  Order: swallow check (+0x1DD88) -> housekeeping + go_reset -> cursor_sprite checks -> pixel_to_tile
  -> go-to-cursor path (cursor_sprite 0x93AA9C = drag release) -> inline go-to 0x46DF0E (needs EAX=veh;
  lock_veh/order 0x18/wp0/Console_group/synch_veh/unlock; ends 0x46E11A -> 0x46EB4A) -> pending-action
  switch -> RIGHT: Shift -> StatusWin_set_loc; else gate 0x46E529 `MOV EAX,[0x9A6494]; TEST AH,1`
  (MPREF 0x100 or +0x1DD78==1, and !ControlTurnC) -> MapWin_right_menu 0x46C0D0 else 0x46E5DE ->
  0x46E5EB -> LEFT/no-menu: view mode or right -> set_view+set_cursor; base_at -> (left, ours) set_center
  x2 + BaseWin_zoom; else set_center(tile,1) with drawOnlyCursor=1 @0x46E4A1/0x46E8CA, veh_at -> ours+left
  -> Console_activate 0x4D2F00. Four set_center sites 0x46E4A1/0x46E7CF/0x46E7FA/0x46E8CA = Thinker's
  write_call targets (collision fatal) -> hook MapWin_set_center ENTRY 0x46B1F0 instead.
- Vtable g_console_win_vtbl 0x66EC18 (entries = vbase adjustor thunks 0x51DExx `sub ecx,[ecx-4]; sub
  ecx,0x2328; jmp`): +0x44 mouse_move 0x46F000, +0x4C left_click 0x46EBA0, +0x50 left_down 0x46ED30,
  +0x54 left_up 0x46EFF0 (empty), +0x58 right_click 0x46EBE0, +0x5C right_down 0x46EC10, +0x64 key
  0x5178C0, +0x70 left_double_click 0x46EBD0 (EMPTY 3 bytes — free slot), +0x144/148/14C/150 =
  Win_on_l_button_down/up 0x5F63C0/0x5F6550, Win_on_r_button_down/up 0x5F6710/0x5F6880.
- WinProc 0x5F0650: 0x201 -> Win_OnLButtonDown(is_double=0); table 0x5F104C: 0x202 up, 0x203 DBLCLK ->
  Win_OnLButtonDown(is_double=1) -> Win_on_l_button_down calls +0x70 THEN Win_left_down_event -> +0x50;
  0x204 -> +0x14C -> +0x5C; 0x205 -> +0x150 -> +0x58 (RIGHT CLICK FIRES ON UP); 0x207..0x209 (middle)
  index>4 -> 0x5F0D11 DefWindowProcA = unhandled. WNDCLASS style 0x2B (Win_init_class 0x5F01F0) has
  CS_DBLCLKS. 0x5D5C50 = CallWindowProc forwarder (PRACX redirect imm @0x5D5C70).
- PRACX: swallows WM_RBUTTONDOWN on the map, right-drag >2.5px scrolls, on RBUTTONUP without drag calls
  pfncWinProc(RBUTTONDOWN) + (RBUTTONUP) directly from prax.dll (not via the queue) -> our
  WH_GETMESSAGE hook sees only the originals.
- Globals = Console fields: 0x939288 = +0x23BD8 fUnitNotViewMode (move mode), 0x93928C = +0x23BDC veh,
  0x939294 = +0x23BE4, 0x9393C0 = +0x23D10 selecting_mode (go_timer 1/9, patrol 8), 0x9393CC = +0x23D1C.
  0x90D938 g_map_mouse_enabled gates every MapWin_on_*. Ctrl+left in game mode = free (only blocks drag).
- MapWin_on_mouse_move 0x46F000 drag branch WRITES Vehs[veh].wp0 each move (0x46F17A) — hover preview
  (P6) cannot simply arm the drag state.
- Right-click modifiers (TRACED): Ctrl+Shift = Info on this square (0x46E3A4); Shift = pref ON ? 'Move cursor
  to here' + set_view(1) (0x46E463) : the menu (0x46E45C) -- the manual is RIGHT; plain = gate 0x46E529,
  pref OFF -> set_view(1)+set_cursor+centre (DROPS MOVE MODE -- P1 must not reuse that branch).
- swallow_click (+0x1DD88) is cleared by every MapWin_on_left_down; a drag release never eats the next
  click. Shift key-repeat go_resets (0x517EDB) re-set it: with ShiftInstantMove OFF a Shift+click is
  swallowed entirely (no drag, no click) -- harmless, not fixed.
- Double-click = click, then DBLCLK (+0x70 empty, then +0x50), then release (+0x4C) = two full clicks today.
- Menu_show returns the picked ROW index (-1 cancelled); 'Move unit to here' locks from 0x46CFCA.

**Original proposals (for the record; see 'What shipped'):** P1 Right-Click Moves the Active Unit (detour at gate 0x46E529 ->
JMP 0x46DF0E with EAX=veh) · P2 Left Click Doesn't Recenter (vtable +0x4C wrapper flag + set_center
entry, RenderTileBounds test) · P3 Double-/Ctrl+Click Moves Here (empty slot +0x70) · P4 Middle Click
Centers (WH_GETMESSAGE, 0x207) · P5 Click-Lock drag (message-level UP swallow) · P6 hover preview (stretch).
Shipped already: DragMoveHoldMs slider, ShiftInstantMove. Stock prefs not to duplicate: Right-Click Pops
Up Menus (0x100), Detailed Right-Click Menus (0x400), Click on Unit Always Cancels Orders (0x40000),
Mouse at Edge Scrolls View, Don't Center On Units With Orders.

**Complaint ranking (Steam/GOG/forums):** 1 "dated/clunky controls" · 2 no right-click-to-move, drag is
the newcomer wall · 3 huge right-click menu / too many clicks (RSI) · 4 numpad dependence · 5 no group
select · 6 Win11 mouse crashes; veterans like keyboard+numpad -> everything opt-in.

**How to apply:** run hook_mapclick.js first (its header lists the six claims + the drive script); the
dry-run hosts are all function entries (hazard-audited). Related: [[project-smac-map-goto-drag]],
[[project-smac-wheel-over-map]], [[project-smac-thinker-compat]], [[feedback-frida-attach-branch-target]].

**2026-10-12 SCENARIO EDITOR vs the set (user report "the editor breaks the Modern Control Set"):** every gate keyed on
GameState 0x9A64C0 bit 0x40 via Editor(). The engine sets it in Console_load_proc 0x51BC17 (`or [GameState],0xE0`,
menu id 0x61A "Activate Scenario Editor" Ctrl+K), NOTHING clears it in a session (capstone scan: no `and` on
0x9A64C0; only load/new-game register stores), and it is saved with the game -> the set went dark for good in that
game and in every later save. The editor's real map input (decompiled): press with Ctrl+Shift or ScrollLock&&!Ctrl
-> paint drag (Console+0x1DD8C = 1/2, MapWin_on_left_down 0x46ED30 / _right_down 0x46EC10, painted by mouse_move
0x46F0A0 -> MapWin_editor 0x46B510); click with Ctrl, or ScrollLock (&& !Shift) -> MapWin_click 0x46E299 paints
([ebp-0x20]); Console_edit_lock 0x4E1F40 = editor && (ScrollLock || GameState 0x8000000 "Editor Only") blocks
go_timer arming. go_timer's mode 9 is the Ctrl drag in view mode (EditorVeh 0x9393CC==0), NOT an editor arm.
FIX (branch fix/editor-modernctl-gate, worktree scratch/edgate, DLL MD5 7cb7f87d (after the audit nits: comment, test pins, kVA_GroupFormed rename, terranx.h field Console +0x23D1C), test
test_editor_gate_is_the_paint_input_only): EditorEngaged() = Editor() && (Ctrl || ScrollLockOn || paint_mode != 0
|| EditorOnly bit) at all 7 gates. Known: Ctrl+right waypoints are off while the editor is active (Ctrl+click is
the editor's paint). Worktree build needs a junction src/uimod/third_party -> the main checkout's (gitignored ffmpeg).
Awaiting the maintainer's symptom confirmation + in-game verify; see [[project-smac-scenario-editor]].

**2026-10-14 integration:** the maintainer asked for one live DLL carrying both lines of work. The second line of work applied the code patch (modernctl.cpp + test_modernctl_sites.py) into master's working tree,
hand-merged the two work-log bullets and the terranx.h lines, ran the 26 site tests (pass), and built uimod.dll **ba2a91b6**
= master 2f8cfaf + my fix (the other checkout had NO DLL source changes of its own; its day's work is exe-side: patches.yaml, 0x46741E dashed
order line). ba2a91b6 is NOT deployed; the game folder still holds cf7e2be5. The other checkout relays the deploy request + my in-game check
list to the maintainer. Branch fix/editor-modernctl-gate in my worktree is now redundant (same bytes in master's tree, uncommitted).
**Build fact:** uimod.vcxproj has WholeProgramOptimization (LTCG). Rebuilding IDENTICAL source at the SAME path changed the MD5
(7cb7f87d -> fe08580e, .text vsize +-32 B); ~85% of .text differs between any two builds because x86-32 absolute .rdata/.data
refs shift. Never infer a source difference from a DLL byte diff; diff the sources.

**2026-10-14 the REAL "editor kills the HUD" bug (traced, hook_editorhud.js; log work/frida_editorhud_2026-10-15T06-41-25):**
NOT the gate. A scenario-editor paint PRESS (Scroll Lock plain click, or Ctrl+Shift stroke, either button) sets the mouse
capture g_sb_track_win 0x9B7ABC to the map (MapWin_on_left_down 0x46EE73 / _right_down 0x46ECC9), and the release never
clears it: go_reset 0x50EF50 releases only an armed (g_go_win_idx) or dragging (+0x1DD80) map, MapWin_click's paint
consumption 0x46D958 clears only paint_mode. Win_get_mouse_window 0x5F6F10 checks four capture globals BEFORE its window
walk (0x9B7ACC pressed-L, 0x9B7AD0 pressed-R, 0x9B7ABC track, 0x9B7AC0) -> every later click goes to the map, HUD dead.
Vanilla recovers by accident: the next unit drag's go_reset, or Win_set_modal 0x5EE1C8 (any popup) -- the Modern Control
Set has no left drag, so it stayed dead; the maintainer read it as "after a move command". The map's Win vtbl+0x10 (track end,
adjustor 0x51DE30 -> 0x46EB90) is `jmp go_reset`. Fix: ReleasePaintCapture after LeftClickWrap/RightClickWrap (editor bit,
capture == map, no paint/drag/armed -> clear, call vtbl+0x10, clear phase). Also VANILLA: palette right column rows 2..5
(modes 26..29) never highlight -- Console_editor_paints 0x4E0A50 compresses mode->button id through the mode table
0x691888 (19 x 0x20 B; absent entries 10,15..18) only for modes < 0x1A (`cmp esi,0x1A` @0x4E0A86); DLL raises the byte to
0x1E (byte-checked). Both get CHANGELOG lines (vanilla bugs). Ruled out on the way: the overlay (child of the map window,
never over the strip), the HUD centre-mode switch (nothing in the move path writes it), swallow flag +0x1DD88.
Win_show(w,0)/a press move the window to the FRONT of g_top_windows (0x5F5140 / Win_on_l_button_down 0x5F63F7).

**2026-10-15 CLOSED:** user confirmed in game ("All fixes correctly landed") with uimod.dll 0cbc9f0d (master build: both editor patches + the other checkout's PickByRight + its cursor/portrait work). CHANGELOG lines and the commit followed with the maintainer's OK. Open design item only: the map label showing through the console strip's keyed slot (vanilla).

**2026-10-17 USER DECISION:** with a unit selected (move mode), a plain left click on an empty square does nothing under Modern + ClickKeepsView (vanilla recentres; the engine skips set_cursor in move mode at 0x46E5F5). The maintainer confirmed this is CORRECT, not a bug -- do not add a "left click moves cursor" route. Shift+left is the cursor move.
