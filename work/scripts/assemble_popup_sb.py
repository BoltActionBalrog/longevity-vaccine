"""Popup-family console-rail scrollbar (2026-08-14) -- the two ARMING thunks.

The rail geometry itself is handled by assemble_rail_scrollbar.py v2 (family gate
thunk_rail_gate + g_rail_sb stash in thunk_rail_sbfit + thunk_railout_hstep).  Once
a Popup's embedded ScrollBar (Popup+0x3230) is fitted at bp(24) wide, its ART must
be armed exactly like the ProdPicker's static bar 0x6AF164 was:

  thunk_pref_sbzoom v6  -- ScrollBar_draw vtable slot [0x669D88] repoint.  v5 + one
                           dynamic allowlist entry `cmp ecx,[g_rail_sb] / je go`
                           (8B; 95B total, slot 0xADB0..0xAE20 = 112B).  Arms
                           g_netwin_active around the draw (thunk_sb_thumb grip zoom
                           + btn_gate netwin branch) and the sb_restripe tail
                           (device-density 0x41/0xC5 trough + F0/B9 one-shot).
                           g_rail_sb==0 (no fitted bar) never matches a live ecx.
  thunk_btn_stripes v8  -- v5 + dynamic arm of the F0/B9 one-shot for the fitted
                           bar's two arrow FlatButtons (esi == [g_rail_sb]+0xAAC or
                           +0x15F8) before the common devfill+remap call, AND the
                           thunk_ed_remap pass for every sb arrow (statics + dynamic)
                           before the fe call: the HOVER chevron pair 0xA2/0xEF is
                           owned by no fe family (2026-08-15 1600x1200 shot); v8 adds
                           thunk_sbarrow_bg for the same arrows (face background
                           C2/C5 row dither, 1920x1080 shot). Every other esi
                           byte-path identical to v5.

Both are byte-verified against the shipped v5 (this script re-derives v5 from the
same asm with the new lines removed and asserts equality with the yaml bytes) and
emitted yaml-ready with {abs32:}/{rel32:} placeholders.  Unicorn differential in
tests\test_rail_asm_parity.py (popup arms).  No inline `;` comments (keystone hangs).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2 = 0xA0C000
SB_DRAW = 0x6066F0
SB_RESTRIPE_VA = PCAVE2 + 0x105B0
SBZOOM_OFF = 0xADB0              # v5..v7 slot (the v5 re-derivation anchor; rel32s are position-dependent)
SBZOOM_LIMIT = 0xAE20            # thunk_scale_nn_v1shim starts here
SBZOOM8_OFF, SBZOOM8_LIMIT = 0x880, 0x940   # v8 (2026-09-26): RELOCATED (0x878..0xA00 was free then); next occupant t_pw_shrink @0x940 (cave_map, fix 7); the old slot 0xADB0..0xAE17 is FREE
G_MODAL_TOP = 0x9B7AE0           # g_modal_top; == ReportWin_g 0x876478 while an HQ report / intel PROFILE is up
RW_WIN = 0x876478
G_RW_SBS = 0xA33564              # assemble_rw CELL g_rw_sbs[2] (pcave2 0x27564, frozen): the two console list bars stashed by t_rw_sbinit (slot 0 left / 1 right)
G_RW_SBPARENTS = 0xA3356C        # assemble_rw CELL g_rw_sbparents[2]: each bar's parent (the RW-embedded console ListBox part, +0xC4 of the bar) -- a stale heap pointer whose +0xC4 no longer matches is refused
T_RW_SBARROWS_OFF = 0xC980       # t_rw_sbarrows v2 (assemble_rw_kinds, pinned): eax = 1 when esi is an arrow of either stashed console bar (parent-checked), else 0; clobbers eax only
STRIPES_OFF = 0x2FD0
STRIPES_LIMIT = 0x3160           # thunk_filedlg_listpitch starts here

SLIDERS = (0x862064, 0x8641B0, 0x8662FC, 0x868448)
SUPPORT_SB = 0x6EABC8
FAC_SB = 0x6E8A7C                # BaseWin_g+0x41454: BASE FACILITIES list ScrollBar (v7 2026-09-21f)
PICKER_SB = 0x6AF164
ARROW_UP = 0x6AFC10
ARROW_DN = 0x6B075C
DW_CHAT_SB = 0x745A80           # DiploWin (0x73ACD8) chat TextScroll +0xA388, its ScrollBar +0xA20 (static; v9 2026-09-27)
DW_ARROW_UP, DW_ARROW_DN = DW_CHAT_SB + 0xAAC, DW_CHAT_SB + 0x15F8   # its two arrow FlatButtons (v12)
BASEWIN_BTN_LO, BASEWIN_BTN_HI = 0x6B4DE8, 0x6C4670
EDITOR_LO, EDITOR_HI = 0x7B7264, 0x7CD098
# v9 (2026-09-10): the HUD base-locator globe / grid FlatButtons (MainWin statics, HUD group #10): their PRESSED
# face dithers E0/E2 -- an editor-face family (e0/e2, E0's mate is E2 here, not the baked E1) that fe_pair_remap
# cannot own -> they take the ed_remap pass too (1600x1200 banding under the report screens' BASE LOCATOR well,
# user 2026-09-09; proto hook_report_icons_proto.js v4 census + restripe, user-verified).
HUD_LOC_GLOBE, HUD_LOC_GRID = 0x7B39E8, 0x7B4534
# v10 (2026-09-11): the satellite report's ATTACK! FlatButton (ReportWin+0xB5AC, id 0xD3E, the third of the
# RW+0x9F14 group the kinds gate admits): its bevel face is the red 1px pair C9/6D (palette 201/109) -- an
# editor-face family fe_pair_remap does not own, NN-banded 1,2,1,1,2,1 at g=22 (user shot 1920x1080
# 20260911-195502; label is black 0x41, untouched) -> ed_remap pass, exactly the v9 locator treatment.
RW_SAT_ATTACK = 0x881A24

# sentinels -> yaml placeholders (abs32) ; rel32 targets are cave-internal fixed VAs
SENT = {
    0xDEADBE00: "{abs32:g_dll_pref_slider}",
    0xDEADBE04: "{abs32:g_sb_cur}",
    0xDEADBE08: "{abs32:g_netwin_active}",
    0xDEADBE0C: "{abs32:g_rail_sb}",
    0xDEADBE10: "{abs32:g_rm_f0ovr}",
    0xDEADBE14: "{abs32:g_faction_active}",
    0xDEADBE18: "{abs32:g_rm_povr}",
    0xDEADBE1C: "{abs32:g_fe_dst}",
    0xDEADBE20: "{abs32:g_fe_x}",
    0xDEADBE24: "{abs32:g_fe_y}",
    0xDEADBE28: "{abs32:g_fe_src}",
    0xDEADBE2C: "{abs32:g_btn_origW}",
    0xDEADBE30: "{abs32:g_fe_w}",
    0xDEADBE34: "{abs32:g_btn_origH}",
    0xDEADBE38: "{abs32:g_fe_h}",
    0xDEADBE3C: "{abs32:g_popup_scale_num}",
    0xDEADBE40: "{abs32:g_ab_w}",
    0xDEADBE44: "{abs32:g_ab_h}",
    0xDEADBE48: "{abs32:g_rm_yph}",
}
G_DLL_SLIDER, G_SB_CUR, G_NETWIN, G_RAIL_SB = 0xDEADBE00, 0xDEADBE04, 0xDEADBE08, 0xDEADBE0C
G_RM_F0OVR, G_FACTION, G_RM_POVR = 0xDEADBE10, 0xDEADBE14, 0xDEADBE18
G_FE_DST, G_FE_X, G_FE_Y, G_FE_SRC = 0xDEADBE1C, 0xDEADBE20, 0xDEADBE24, 0xDEADBE28
G_BTN_ORIGW, G_FE_W, G_BTN_ORIGH, G_FE_H = 0xDEADBE2C, 0xDEADBE30, 0xDEADBE34, 0xDEADBE38
G_SCALE, G_AB_W, G_AB_H = 0xDEADBE3C, 0xDEADBE40, 0xDEADBE44
G_RM_YPH = 0xDEADBE48            # v13: thunk_fe_pair_remap v8 row-phase cell (assemble_devfill_stripes.py)
G_STRIPE_PERIOD = 0x66879C       # g_stripe_period (P, law stripe_period; >= 2 whenever btn_stripes runs, g > 16)
SBARROW_BG_OFF = 0x11400          # thunk_sbarrow_bg (CALL helper) in the pcave2 free tail
SBARROW_BG_END = 0x114C0
G_AB_OFF = 0x114C0                # g_ab_w / g_ab_h scratch dwords
ARROW_BG_TOP, ARROW_BG_BOT = 0xC2, 0xC5   # the arrow face background row dither (palette 194/197)
# rel32 call targets (fixed cave VAs, emitted as {rel32:} tokens)
REL = {
    0xDEADC000: "{rel32:thunk_btn_devfill}",
    0xDEADC004: "{rel32:thunk_ed_remap}",
    0xDEADC008: "{rel32:thunk_fe_pair_remap}",
    0xDEADC00C: "{rel32:thunk_sbarrow_bg}",
    0xDEADC010: "{rel32:t_rw_sbarrows}",
    0xDEADC014: "{rel32:t_face_own}",
}
T_DEVFILL, T_ED_REMAP, T_FE_REMAP, T_SBARROW_BG = 0xDEADC000, 0xDEADC004, 0xDEADC008, 0xDEADC00C
T_RW_SBARROWS = 0xDEADC010
T_FACE_OWN = 0xDEADC014           # v14: assemble_face_own.t_face_own (own-top faces: PrefWin's children, the SE column)


def asm_sbarrow_bg():
    """thunk_sbarrow_bg (2026-08-15, CALL helper, pcave2 tail 0x11400): the
    scrollbar arrow FlatButton's face BACKGROUND is a 1px row dither 0xC2/0xC5
    (palette 194/197 -- NOT the bar's 41/C5 trough, and owned by no fe or ed
    family), so after the NN zoom it bands (1920x1080 shot 20260815-010148, also
    1600x1200).  Over the staged g_fe_dst button canvas (origin 0,0; w/h =
    g_fe_w/g_fe_h clipped to the buffer) rewrite every 0xC2/0xC5 to C2 on
    stripe-top rows / C5 below (law sbarrow_bg_pixel; same phase grid as fe/ed).
    Called by btn_stripes v8 for the sb arrows only (statics + [g_rail_sb]
    dynamic).  Preserves every register (pushad); g<=16 never reaches it
    (btn_stripes only runs under g_btn_pending)."""
    return f"""
        pushad
        mov  ebx, dword ptr [{G_FE_DST}]
        test ebx, ebx
        je   done
        mov  esi, dword ptr [ebx + 0x54]
        test esi, esi
        je   done
        mov  ebp, dword ptr [ebx + 0x4A8]
        mov  ecx, dword ptr [{G_FE_W}]
        cmp  ecx, dword ptr [ebx + 0x80]
        jle  wok
        mov  ecx, dword ptr [ebx + 0x80]
    wok:
        test ecx, ecx
        jle  done
        mov  dword ptr [{G_AB_W}], ecx
        mov  edx, dword ptr [{G_FE_H}]
        mov  eax, dword ptr [ebx + 0x84]
        neg  eax
        cmp  edx, eax
        jle  hok
        mov  edx, eax
    hok:
        test edx, edx
        jle  done
        mov  dword ptr [{G_AB_H}], edx
        mov  ebx, dword ptr [{G_SCALE}]
        mov ebx, dword ptr [0x66879c]
        xor  edi, edi
    row:
        mov  eax, edi
        xor  edx, edx
        div  ebx
        lea  eax, [ebx + 1]
        shr  eax, 1
        cmp  edx, eax
        mov  dl, {ARROW_BG_TOP}
        jb   col
        mov  dl, {ARROW_BG_BOT}
    col:
        mov  ecx, dword ptr [{G_AB_W}]
        mov  eax, esi
    px:
        cmp  byte ptr [eax], {ARROW_BG_TOP}
        je   set
        cmp  byte ptr [eax], {ARROW_BG_BOT}
        jne  next
    set:
        mov  byte ptr [eax], dl
    next:
        inc  eax
        dec  ecx
        jnz  px
        add  esi, ebp
        inc  edi
        cmp  edi, dword ptr [{G_AB_H}]
        jl   row
    done:
        popad
        ret
    """


def asm_sbzoom(v6=True, v7=True, v8=True, v9=True, v11=True):
    """v7 (2026-09-21f, 103B, ends 0xAE17 < scale_nn_v1shim 0xAE20): + the BASE
    FACILITIES list ScrollBar static FAC_SB (BaseWin_g+0x41454) -> go.  Its rect
    is device space via thunk_bw_facsb_attach (law basewin_facsb_rect); this
    arms the ART zoom: thunk_sb_thumb for the grip, btn_gate's netwin branch for
    the two label-less arrows inside the bracket (btn_gate v9 also admits the
    arrows directly for hover redraws).
    v8 (2026-09-26, intel PROFILE / F3 probe frida_intelsb_20260927T030613): + the TWO HQ-report console list
    bars g_rw_sbs[0..1] while g_modal_top == ReportWin_g.  The rail admission alone keyed on the single-owner
    g_rail_sb cell = the LAST stashed bar, so the left console list (BASE EXPENDITURES on F3, TECHNOLOGY on the
    PROFILE) drew its chevrons + grip native on every paint (171 [SBDRAW] records: slot 0 'vanilla', slot 1
    'ARMED').  Heap bars -> gated on the report being the modal top so a stale pointer can never admit a later
    object at the same address.
    v9 (2026-09-27): + the multiplayer negotiation window's chat-history bar DW_CHAT_SB (a static object inside the
    static DiploWin, so no parent guard): its rect is device via the diplowin t_dw_ts3 g_netwin_active bracket
    around TextScroll_attach; this arms the grip / arrow ART zoom and the trough restripe.
    v11 (2026-10-17, fix 7): the bracket is a COUNT -- `inc [g_netwin_active]` in place of the absolute `:= 1`
    (thunk_sb_restripe's head is the matching clamped `dec`), so an armed bar painted inside another holder's
    bracket (Datalinks, the tech-breakthrough modal, the lobby) no longer zeroes that holder's flag on exit.
    Every reader tests nonzero; the clamp keeps a stray close from going negative (= permanently armed).
    (v10, the energy-report bar admission, is inserted by assemble_stripes_rwsb.sbzoom_text.)"""
    arm = f"        inc  dword ptr [{G_NETWIN}]\n" if v11 else f"        mov  dword ptr [{G_NETWIN}], 1\n"
    dw =f"        cmp  ecx, {DW_CHAT_SB:#x}\n        je   go\n" if v9 else ""
    rail = f"        cmp  ecx, dword ptr [{G_RAIL_SB}]\n        je   go\n" if v6 else ""
    rw = (f"        mov  eax, dword ptr [{G_MODAL_TOP:#x}]\n        cmp  eax, {RW_WIN:#x}\n        jne  norw\n"
          f"        cmp  ecx, dword ptr [{G_RW_SBS:#x}]\n        jne  rw1\n        mov  eax, dword ptr [ecx+0xC4]\n        cmp  eax, dword ptr [{G_RW_SBPARENTS:#x}]\n        je   go\n"
          f"    rw1:\n        cmp  ecx, dword ptr [{G_RW_SBS + 4:#x}]\n        jne  norw\n        mov  eax, dword ptr [ecx+0xC4]\n        cmp  eax, dword ptr [{G_RW_SBPARENTS + 4:#x}]\n        je   go\n    norw:\n") if v8 else ""
    fac = f"        cmp  ecx, {FAC_SB}\n        je   go\n" if v7 else ""
    return f"""
        cmp  ecx, {SLIDERS[0]}
        je   go
        cmp  ecx, {SLIDERS[1]}
        je   go
        cmp  ecx, {SLIDERS[2]}
        je   go
        cmp  ecx, {SLIDERS[3]}
        je   go
        cmp  ecx, {SUPPORT_SB}
        je   go
{fac}{dw}        cmp  ecx, {PICKER_SB}
        je   go
        cmp  ecx, dword ptr [{G_DLL_SLIDER}]
        je   go
{rail}{rw}        jmp  {SB_DRAW}
    go:
        mov  dword ptr [{G_SB_CUR}], ecx
{arm}        call {SB_DRAW}
        jmp  {SB_RESTRIPE_VA}
    """


def asm_btn_stripes(v6=True, v7=True, v11=True, v12=True, v13=True, v14=True):
    """v5 (v6=False): the shipped editor-range template.  v6: + dynamic F0 one-shot
    arm for the rail-fitted bar's arrows.  v7 (2026-08-15): the sb arrows (statics
    + dynamic) ALSO take the thunk_ed_remap pass before the common fe call -- the
    HOVER chevron dithers 0xA2/0xEF (palette 162/239), a pair no fe family owns
    (the 1600x1200 shot 20260815-001842: down arrow F0/B9 lawfully striped, hovered
    up arrow NN-banded).  ed_remap is the generic run-chain pair restriper (families
    f0/b9, a2/ef, e0/e2, c9/6d, 6d/68; law scaling_laws.editor_face_*), and its
    composition with fe is a fixed point, so the normal-state F0/B9 face is unchanged.
    v9 (2026-09-10): + the two HUD base-locator statics (HUD_LOC_GLOBE/GRID) -> ed pass (E0/E2 pressed face).
    v10 (2026-09-11): + the satellite report's ATTACK! static (RW_SAT_ATTACK) -> ed pass (C9/6D red face).
    v11 (2026-09-26): the dynamic arrow admission (F0 one-shot + sbarrow_bg/ed pass) also asks t_rw_sbarrows, so
    the arrows of BOTH HQ-report console list bars take the restripe (g_rail_sb alone = the last stashed bar; the
    left list's arrows would have NN-banded at g=22/25 once sbzoom v8 zoomed them).
    v12 (2026-09-27): + the negotiation window's chat-bar arrows DW_ARROW_UP/DN, routed exactly like the picker
    statics ARROW_UP/DN (F0 one-shot + sbarrow_bg / ed pass) -- zoomed by sbzoom v9 / t_dw_gate.
    v13 (2026-10-11): the plain fe path (every button that takes neither the arrow nor the ed arm: popup / council /
    Social Engineering / faction faces) stripes on its PARENT canvas's grid, law scaling_laws.btn_face_stripe_phase =
    list_stripe_phase(child_top): the parent-local top [esi+0x140] + [esi+0x150] goes into g_rm_yph around the fe
    call (fe_pair_remap v8 adds it to the row before `div P`), cleared after.  A negative top is reduced here
    (cdq / idiv P, + P -> 1..P; == P is phase 0 for fe's div).  The ed / arrow paths keep their phase-0 fe call.
    1600x1200 SE shot 140606: window top 315, POLICE STATE face top 360 -> parent-local 45, phase 1 = the panel's.
    v14 (2026-10-27 W9A, the user's decision; law scaling_laws.btn_face_phase): the plain path first asks t_face_own
    (assemble_face_own.py; edx = the button) -- an own-top face (PrefWin's children, the SE society column) takes its
    own_face_stripe_phase (CF = 1, edx) instead of the parent-local top; every other button's staging is v13's,
    byte-identical.  +11 B (355 of the 400-byte slot)."""
    dw_sb = (f"        cmp  esi, {DW_ARROW_UP:#x}\n        je   sbarrow\n        cmp  esi, {DW_ARROW_DN:#x}\n        je   sbarrow\n"
             if v12 else "")
    dw_ar = (f"        cmp  esi, {DW_ARROW_UP:#x}\n        je   arrow\n        cmp  esi, {DW_ARROW_DN:#x}\n        je   arrow\n"
             if v12 else "")
    sb_tail = (f"        je   arrow\n    chk2:\n        call {T_RW_SBARROWS}\n        test eax, eax\n        jnz  arrow\n        jmp  fe\n" if v11
               else "        jne  fe\n")
    sb_zero = "        je   chk2\n" if v11 else "        je   fe\n"
    ed_tail = f"        call {T_FE_REMAP}\n        ret\n" if v13 else ""
    own = (f"        mov  edx, esi\n        call {T_FACE_OWN}\n        mov  eax, edx\n        jc   phok\n"
           if v13 and v14 else "")
    fe_body = (f"{own}        mov  eax, dword ptr [esi + 0x140]\n        add  eax, dword ptr [esi + 0x150]\n"
               f"        jns  phok\n        cdq\n        idiv dword ptr [{G_STRIPE_PERIOD:#x}]\n        mov  eax, edx\n"
               f"        add  eax, dword ptr [{G_STRIPE_PERIOD:#x}]\n    phok:\n        mov  dword ptr [{G_RM_YPH}], eax\n"
               f"        call {T_FE_REMAP}\n        and  dword ptr [{G_RM_YPH}], 0\n"
               if v13 else f"        call {T_FE_REMAP}\n")
    if v7:
        tail = f"""
        cmp  esi, {EDITOR_LO}
        jb   chk
        cmp  esi, {EDITOR_HI}
        jb   ed
    chk:
        cmp  esi, {HUD_LOC_GLOBE}
        je   ed
        cmp  esi, {HUD_LOC_GRID}
        je   ed
        cmp  esi, {RW_SAT_ATTACK}
        je   ed
        cmp  esi, {ARROW_UP}
        je   arrow
        cmp  esi, {ARROW_DN}
        je   arrow
{dw_ar}        mov  eax, dword ptr [{G_RAIL_SB}]
        test eax, eax
{sb_zero}        add  eax, 0xAAC
        cmp  esi, eax
        je   arrow
        add  eax, 0xB4C
        cmp  esi, eax
{sb_tail}    arrow:
        call {T_SBARROW_BG}
    ed:
        call {T_ED_REMAP}
{ed_tail}    fe:
{fe_body}        ret
    """
    else:
        tail = f"""
        cmp  esi, {EDITOR_LO}
        jb   fe
        cmp  esi, {EDITOR_HI}
        jae  fe
        call {T_ED_REMAP}
    fe:
        call {T_FE_REMAP}
        ret
    """
    dyn_zero = "        je   dyn2\n" if v11 else "        je   nof0\n"
    dyn_tail = (f"        je   sbarrow\n    dyn2:\n        call {T_RW_SBARROWS}\n        test eax, eax\n        jnz  sbarrow\n        jmp  nof0\n" if v11
                else "        jne  nof0\n")
    dyn = f"""
        mov  eax, dword ptr [{G_RAIL_SB}]
        test eax, eax
{dyn_zero}        add  eax, 0xAAC
        cmp  esi, eax
        je   sbarrow
        add  eax, 0xB4C
        cmp  esi, eax
{dyn_tail}""" if v6 else "        jne  nof0\n"
    dn_tail = "        je   sbarrow\n" if v6 else ""
    return f"""
        cmp  esi, {BASEWIN_BTN_LO}
        jb   cont
        cmp  esi, {BASEWIN_BTN_HI}
        jae  cont
        ret
    cont:
        cmp  esi, {ARROW_UP}
        je   sbarrow
        cmp  esi, {ARROW_DN}
{dn_tail}{dw_sb}{dyn}    sbarrow:
        mov  dword ptr [{G_RM_F0OVR}], 1
    nof0:
        cmp  dword ptr [{G_FACTION}], 0
        je   common
        mov  dword ptr [{G_RM_POVR}], 0
    common:
        call {T_DEVFILL}
        lea  eax, [esi + 0x444]
        mov  dword ptr [{G_FE_DST}], eax
        xor  eax, eax
        mov  dword ptr [{G_FE_X}], eax
        mov  dword ptr [{G_FE_Y}], eax
        mov  dword ptr [{G_FE_SRC}], eax
        mov  eax, dword ptr [{G_BTN_ORIGW}]
        mov  dword ptr [{G_FE_W}], eax
        mov  eax, dword ptr [{G_BTN_ORIGH}]
        neg  eax
        mov  dword ptr [{G_FE_H}], eax
{tail}"""


def assemble(src, va):
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    code, _ = ks.asm(src, addr=va)
    return bytes(code)


def to_template(blob, va):
    """Render bytes as a yaml token string: abs32 sentinels -> {abs32:}, and E8/E9
    whose rel32 lands on a REL sentinel -> {rel32:} (the sentinel is placed as an
    ABSOLUTE target, so rel = sent - (va+i+5))."""
    out, i = [], 0
    while i < len(blob):
        b = blob[i]
        if b in (0xE8,) and i + 5 <= len(blob):
            rel = int.from_bytes(blob[i + 1:i + 5], "little", signed=True)
            tgt = (va + i + 5 + rel) & 0xFFFFFFFF
            if tgt in REL:
                out.append("E8"); out.append(REL[tgt]); i += 5; continue
        if i + 4 <= len(blob):
            v = int.from_bytes(blob[i:i + 4], "little")
            if v in SENT:
                out.append(SENT[v]); i += 4; continue
        out.append(f"{b:02X}"); i += 1
    return " ".join(out)


# the SHIPPED v5 byte templates (yaml, live cb35ac87) -- regression anchors
SBZOOM_V5 = ("81 F9 64 20 86 00 74 35 81 F9 B0 41 86 00 74 2D 81 F9 FC 62 86 00 74 25 "
             "81 F9 48 84 86 00 74 1D 81 F9 C8 AB 6E 00 74 15 81 F9 64 F1 6A 00 74 0D "
             "3B 0D {abs32:g_dll_pref_slider} 74 05 E9 03 F9 BE FF 89 0D {abs32:g_sb_cur} "
             "C7 05 {abs32:g_netwin_active} 01 00 00 00 E8 EE F8 BE FF E9 A9 57 00 00")
STRIPES_V5 = ("81 FE E8 4D 6B 00 72 09 81 FE 70 46 6C 00 73 01 C3 "
              "81 FE 10 FC 6A 00 74 08 81 FE 5C 07 6B 00 75 0A "
              "C7 05 {abs32:g_rm_f0ovr} 01 00 00 00 "
              "83 3D {abs32:g_faction_active} 00 74 0A C7 05 {abs32:g_rm_povr} 00 00 00 00 "   # 2026-10-04: the faction 1-px override stores 0 (law period)
              "E8 {rel32:thunk_btn_devfill} "
              "8D 86 44 04 00 00 A3 {abs32:g_fe_dst} 31 C0 A3 {abs32:g_fe_x} A3 {abs32:g_fe_y} "
              "A3 {abs32:g_fe_src} A1 {abs32:g_btn_origW} A3 {abs32:g_fe_w} A1 {abs32:g_btn_origH} "
              "F7 D8 A3 {abs32:g_fe_h} "
              "81 FE 64 72 7B 00 72 0D 81 FE 98 D0 7C 00 73 05 E8 {rel32:thunk_ed_remap} "
              "E8 {rel32:thunk_fe_pair_remap} C3")


def main():
    ok = True
    v5 = to_template(assemble(asm_sbzoom(False, False, False, False, False), PCAVE2 + SBZOOM_OFF), PCAVE2 + SBZOOM_OFF)
    print("sbzoom v5 re-derivation:", "OK" if v5 == SBZOOM_V5 else "MISMATCH")
    ok &= v5 == SBZOOM_V5
    # the live entry is asm_sbzoom() + assemble_stripes_rwsb's energy-bar admission (sbzoom_text(True)); the bare
    # asm_sbzoom() is that minus the 12-byte admission
    import assemble_stripes_rwsb as RWSB
    b6 = assemble(RWSB.sbzoom_text(True), PCAVE2 + SBZOOM8_OFF)
    print(f"thunk_pref_sbzoom v11 {len(b6)}B @0x{SBZOOM8_OFF:X}..0x{SBZOOM8_OFF+len(b6):X}"
          f" (limit 0x{SBZOOM8_LIMIT:X}) {'OK' if SBZOOM8_OFF+len(b6) <= SBZOOM8_LIMIT else 'OVERFLOW'}")
    ok &= SBZOOM8_OFF + len(b6) <= SBZOOM8_LIMIT
    print('  bytes: "' + to_template(b6, PCAVE2 + SBZOOM8_OFF) + '"')
    print()
    s5 = to_template(assemble(asm_btn_stripes(False, False, False, False), PCAVE2 + STRIPES_OFF), PCAVE2 + STRIPES_OFF)
    print("btn_stripes v5 re-derivation:", "OK" if s5 == STRIPES_V5 else "MISMATCH")
    if s5 != STRIPES_V5:
        print("  got:", s5)
    ok &= s5 == STRIPES_V5
    s6 = assemble(asm_btn_stripes(True, True, True), PCAVE2 + STRIPES_OFF)
    print(f"thunk_btn_stripes v14 {len(s6)}B @0x{STRIPES_OFF:X}..0x{STRIPES_OFF+len(s6):X}"
          f" (limit 0x{STRIPES_LIMIT:X}) {'OK' if STRIPES_OFF+len(s6) <= STRIPES_LIMIT else 'OVERFLOW'}")
    ok &= STRIPES_OFF + len(s6) <= STRIPES_LIMIT
    print('  bytes: "' + to_template(s6, PCAVE2 + STRIPES_OFF) + '"')
    bg = assemble(asm_sbarrow_bg(), PCAVE2 + SBARROW_BG_OFF)
    print(f"thunk_sbarrow_bg  {len(bg)}B @0x{SBARROW_BG_OFF:X}..0x{SBARROW_BG_OFF+len(bg):X}"
          f" (limit 0x{SBARROW_BG_END:X}) {'OK' if SBARROW_BG_OFF+len(bg) <= SBARROW_BG_END else 'OVERFLOW'}")
    ok &= SBARROW_BG_OFF + len(bg) <= SBARROW_BG_END
    print('  bytes: "' + to_template(bg, PCAVE2 + SBARROW_BG_OFF) + '"')
    print("RESULT:", "ALL OK" if ok else "FAILURES -- do not bake")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
