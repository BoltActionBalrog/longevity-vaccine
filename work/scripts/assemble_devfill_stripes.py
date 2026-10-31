#!/usr/bin/env python
# Keystone assembler for the devfill-stripe fix (2026-07-04):
#   * thunk_fe_pair_remap v4 @ pcave2+0x4000 — v3 + g_rm_force one-shot: when set (by
#     thunk_box_thick_devfill v2), the pre-scan keys on the DEST rect content (the mask
#     devfill just tiled) counting BOTH 0xC4 (navy family) and NEW 0xC6 (backdrop family
#     0x41/0xC6), instead of the frame_enlarge src scan. Adds the backdrop pair to the
#     pixel loop (force path only — the enlarge path stays byte-behavior-identical to v3).
#   * thunk_box_thick_devfill v2 @ pcave2+0x4220 — v1 + stripe tail: after STEP2's 1:1
#     device-density mask tile, stage g_fe_dst/x/y/w/h from the caller's rect, set
#     g_rm_force, call thunk_s54_restripe (assemble_editorwho.py; it calls fe_pair_remap
#     first, then the 0x54/0xC2 hatch pass) → the interior's 1px dither becomes the popup
#     stripe language (P = scaling_laws.stripe_period(g) = 2*stripe_rows(g), read from
#     g_stripe_period) matching the title band / rows / buttons.
#     The STEP3 call target is thunk_s54_restripe since 2026-08-14 (the shipped bytes);
#     test_stale_sources.py pins every template here to patches.yaml.
#     GATE: dest == faction-quote window buffer (0x9403e0+0x444) → skip (the picker's
#     approved language is 1px device density, A5 lock).
# Root cause (frida_wimpout.log 2026-07-04): every popup's d690 backdrop + d528 body
# render via devfill → 1px device dither → reads flat black at 4K (user report
# refs\MangledSmacx.png vs refs\pristine\Multiplayer\Quit.png).
#
# Regenerate if any referenced cave offset moves.
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

PCAVE2 = 0xA0C000

SENT = {
    0x71111111: "{abs32:g_popup_scale_num}",
    0x7A111111: "{abs32:g_fe_dst}",
    0x7A222222: "{abs32:g_fe_x}",
    0x7A333333: "{abs32:g_fe_y}",
    0x7A444444: "{abs32:g_fe_w}",
    0x7A555555: "{abs32:g_fe_h}",
    0x7B111111: "{abs32:g_rm_xend}",
    0x7B222222: "{abs32:g_rm_yend}",
    0x7B333333: "{abs32:g_rm_hn}",
    0x7B444444: "{abs32:g_rm_col}",
    0x7B555555: "{abs32:g_fe_src}",
    0x7B666666: "{abs32:g_rm_navy}",
    0x7B777777: "{abs32:g_rm_povr}",
    0x7C111111: "{abs32:g_rm_force}",
    0x7C222222: "{abs32:g_rm_bd}",
    0x7C333333: "{abs32:g_rm_bdcol}",
    0x7F111111: "{abs32:g_rm_c5}",     # v6: C5-family counter->flag (dword)
    0x7F222222: "{abs32:g_rm_bf}",     # v6: BF-family counter->flag (dword)
    0x7F333333: "{abs32:g_rm_c5col}",  # v6: per-row C5-pair write colour
    0x7F444444: "{abs32:g_rm_bfcol}",  # v6: per-row BF-pair write colour
    0x7F555555: "{abs32:g_rm_f0ovr}",  # v7: F0-family ONE-SHOT arm (callers: sb_restripe, btn_stripes v3)
    0x7F666666: "{abs32:g_rm_f0}",     # v7: F0-family enable (consumed one-shot, dword)
    0x7F777777: "{abs32:g_rm_f0col}",  # v7: per-row F0-pair write colour
    0x7F888888: "{abs32:g_rm_yph}",    # v8: row-phase add (btn_stripes v13 sets it around its plain fe call)
    # NB 0x7F family deliberately — 0x7D collides with assemble_clipfix.py's
    # sentinels inside test_clipfix_asm_parity.py's shared emulator.
    0x7E111111: "{abs32:g_devfill_params}",
    0x7E222222: "{abs32:g_devfill_rect}",
    0x7E333333: "{abs32:g_devfill_rect_T}",   # g_devfill_rect+4 — resolved manually below
    0x7E444444: "{abs32:g_devfill_rect_R}",   # +8
    0x7E555555: "{abs32:g_devfill_rect_B}",   # +12
    0x76222222: "{abs32:Buffer_box_sprite}",
}
CALL_SENT = {
    0x75111111: "{rel32:thunk_box_thick_hollow_flat}",
    0x75222222: "{rel32:Buffer_box_sprite}",
    0x75333333: "{rel32:thunk_s54_restripe}",       # STEP3: s54 wraps fe_pair_remap (2026-08-14)
    0x75444444: "{rel32:thunk_dfstep1_dispatch}",   # 2026-07-08: STEP1 frame render -> faction(0x940824)=intK else hollow_flat
}

THUNKS = []
def thunk(name, offset, asm):
    THUNKS.append((name, offset, asm))

# ============ thunk_fe_pair_remap v9 @ 0x10000 ============
# v9 (2026-10-17, fix 7 -- law scaling_laws.force_prescan_bounds): the FORCE-path prescan is clamped
# to the dest BUFFER (columns min(w, W - x0), rows min(h, 8, H - y0)); v8 read up to 8 rows from
# max(y,0) and w columns from max(x,0) unchecked, so a half-open rect (B = H) staged inclusive, or a
# frame within 8 rows of / below the buffer bottom, read past the plane (Unicorn: READ_UNMAPPED when
# the DIB ends on a page).  Byte-identical flags for every in-bounds frame (test_force_prescan_bounds).
# Paid for in place: the four flag zeroes store one zeroed register, g_rm_force is consumed by xchg,
# the dead `mov eax,[g]` + nop before the period load are gone.  940B, ends 0x103AC < g_rr_src 0x103B0.
# v8 (2026-10-11, button faces on the parent grid — law scaling_laws.btn_face_stripe_phase):
# the per-row stripe test reads (row + [g_rm_yph]) mod P instead of row mod P.  g_rm_yph is
# a plain cell (pcave2 0x103FC, in this thunk's own tail slack), 0 for every caller except
# thunk_btn_stripes v13, which stores the FlatButton's parent-local top around its plain-path
# call and clears it after.  +6B: 938B, ends 0x103AA < thunk_rail_ytop 0x10400.
# v7 (2026-08-08, sb banding fix — laws scaling_laws.DITHER_ONESHOT_PAIRS /
# stripe_color_sb / pair_remap_pixel): adds the scrollbar-face pair 0xF0/0xB9
# (arrow faces + thumb grip; palette 240/185, sampled from the 20260808 shots).
# 0xF0 is ALSO solid console art (frida_pp_rail.log bake row: 21px 0xF0 run in
# the rail strip) so the family is enabled ONLY by the self-clearing one-shot
# g_rm_f0ovr (consumed at entry into g_rm_f0; NEVER content-keyed). Callers:
# thunk_sb_restripe (whole sb canvas after every armed ScrollBar_draw) and
# thunk_btn_stripes v3 (the two picker arrow statics). Everything else
# byte-behavior identical to v6.
# (RELOCATED 0xC1C0 -> 0x10000 2026-08-06 in the pcave2 0x10000->0x11000 grow:
#  v6 outgrew the 688B slot against thunk_filedlg_railscale @0xC470; the first
#  target 0xE380 CRASHED THE GAME — it sits inside g_staple_scratch's 2304B
#  BSS 0xE360..0xEC60 (thunk_staple_coverage's 48x48 runtime capture block,
#  recorded ONLY in the cave length-comment ledger; the symbols section gives
#  BSS no size). ALLOCATE FROM THE LEDGER, never from a symbols/content scan.
#  All callers are {rel32:} name refs, both old slots freed/zeros. Prior
#  relocation 0x4000 -> 0xC1C0 2026-07-19 for v5.)
# v6 (2026-08-06, ProdPicker pass 5c — laws scaling_laws.DITHER_FORCE_PAIRS /
# stripe_period / stripe_top / dither_force_mate): the FORCE-path prescan also
# counts 0xC5 and 0xBF, enabling the base-screen-palette pairs 0xC5/0x41
# (picker grid-gutter tile) and 0xBF/0x53 (picker selected-cell fill) —
# content-keyed exactly like navy/backdrop, so no other screen changes.  The
# pixel loop gains the two pairs (colored member top); 0x41 arbitration order
# navy -> backdrop -> C5 (several families can key; 0x41 goes to the first in that order).
# Enlarge path (src prescan) untouched — new flags zeroed at entry.
# v5 was: v4 + CLIP CLAMP (2026-07-19, law scaling_laws.remap_clip_bounds):
# walk bounds intersect the dest buffer's active clip [g_fe_dst]+0x20..+0x2C.
# v4 was: v3 (398B @0x3860) + force-path dest prescan + backdrop pair. CALL helper, preserves
# ebx/esi/edi/ebp, clobbers eax/ecx/edx. g<=16 -> ret (does NOT consume g_rm_force —
# devfill only calls under g>16, same contract as g_rm_povr).
thunk("thunk_fe_pair_remap", 0x10000, """
    cmp     dword ptr [0x71111111], 0x10
    jle     ret0
    push    ebx
    push    esi
    push    edi
    push    ebp
; v9: the four family flags are zeroed from one register (same stores, fewer bytes)
    xor     eax, eax
    mov     byte ptr [0x7B666666], al
    mov     byte ptr [0x7C222222], al
    mov     dword ptr [0x7F111111], eax
    mov     dword ptr [0x7F222222], eax
; ---- v7: consume the F0/B9 one-shot (0xF0 is ALSO solid console art -> NEVER content-keyed;
;      same set-only-under-g>16 contract as g_rm_povr, the g<=16 ret above does not consume) ----
    xchg    eax, [0x7F555555]
    mov     [0x7F666666], eax
; v9: consume g_rm_force the same way (xchg 0 in; was cmp + je + a separate 0 store on the force path)
    xor     eax, eax
    xchg    eax, [0x7C111111]
    test    eax, eax
    je      src_prescan
; ---- force path (devfill): content-key from the DEST rect the mask was just tiled into ----
; v9: the scanned block is clamped to the BUFFER (law scaling_laws.force_prescan_bounds):
;     columns [x0, min(x0+w, W)), rows [y0, min(y0+min(h,8), H)), x0/y0 = max(x/y, 0);
;     empty -> no family.  The clip is deliberately NOT applied (cosmetic, deferred).
    mov     ebx, [0x7A111111]
    test    ebx, ebx
    jz      prescan_done
    mov     esi, [ebx+0x54]
    test    esi, esi
    jz      prescan_done
    mov     edx, [ebx+0x4a8]
    mov     ecx, [0x7A333333]
    test    ecx, ecx
    jge     fy_ok
    xor     ecx, ecx
fy_ok:
    mov     ebp, [ebx+0x84]
    neg     ebp
    sub     ebp, ecx
    imul    ecx, edx
    add     esi, ecx
    mov     eax, [0x7A222222]
    test    eax, eax
    jge     fx_ok
    xor     eax, eax
fx_ok:
    add     esi, eax
    neg     eax
    add     eax, [ebx+0x80]
    mov     edi, [0x7A444444]
    cmp     edi, eax
    jle     fw_ok
    mov     edi, eax
fw_ok:
    test    edi, edi
    jle     prescan_done
    mov     ecx, [0x7A555555]
    cmp     ecx, 8
    jle     fh_ok
    mov     ecx, 8
fh_ok:
    cmp     ecx, ebp
    jle     fh_ok2
    mov     ecx, ebp
fh_ok2:
    test    ecx, ecx
    jle     prescan_done
    xor     ebx, ebx
    xor     ebp, ebp
frow:
    dec     ecx
    js      fscan_done
    push    ecx
    push    esi
    mov     ecx, edi
fpix:
    dec     ecx
    js      frow_done
    mov     al, [esi+ecx]
    cmp     al, 0xC4
    jne     fchk6
    inc     ebx
    jmp     fpix
fchk6:
    cmp     al, 0xC6
    jne     fchk5
    inc     ebp
    jmp     fpix
fchk5:
    cmp     al, 0xC5
    jne     fchkbf
    inc     dword ptr [0x7F111111]
    jmp     fpix
fchkbf:
    cmp     al, 0xBF
    jne     fpix
    inc     dword ptr [0x7F222222]
    jmp     fpix
frow_done:
    pop     esi
    pop     ecx
    add     esi, edx
    jmp     frow
fscan_done:
    mov     eax, edi
    shr     eax, 1
    cmp     ebx, eax
    jle     fchk_bd
    mov     byte ptr [0x7B666666], 1
fchk_bd:
    cmp     ebp, eax
    jle     fchk_c5
    mov     byte ptr [0x7C222222], 1
fchk_c5:
    xor     edx, edx
    cmp     [0x7F111111], eax
    jle     fc5_store
    inc     edx
fc5_store:
    mov     [0x7F111111], edx
    xor     edx, edx
    cmp     [0x7F222222], eax
    jle     fbf_store
    inc     edx
fbf_store:
    mov     [0x7F222222], edx
    jmp     prescan_done
; ---- enlarge path (unchanged v3 semantics): navy iff the SRC is a genuine C4/41 field ----
src_prescan:
    mov     eax, [0x7B555555]
    test    eax, eax
    jz      prescan_done
    mov     esi, [eax+0x54]
    test    esi, esi
    jz      prescan_done
    mov     ecx, [eax+0x84]
    neg     ecx
    jle     prescan_done
    cmp     ecx, 8
    jle     hok
    mov     ecx, 8
hok:
    mov     edi, [eax+0x80]
    test    edi, edi
    jle     prescan_done
    mov     edx, [eax+0x4a8]
    xor     ebx, ebx
rowl:
    dec     ecx
    js      rows_done
    mov     ebp, esi
    push    ecx
    mov     ecx, edi
pixl:
    dec     ecx
    js      row_done
    cmp     byte ptr [ebp+ecx], 0xC4
    jne     pixl
    inc     ebx
    jmp     pixl
row_done:
    pop     ecx
    add     esi, edx
    jmp     rowl
rows_done:
    mov     eax, edi
    shr     eax, 1
    cmp     ebx, eax
    jle     prescan_done
    mov     byte ptr [0x7B666666], 1
prescan_done:
; ---- clamps (dest walk bounds) ----
    mov     esi, [0x7A111111]
    mov     eax, [esi+0x80]
    mov     ecx, [esi+0x84]
    neg     ecx
    mov     edx, [0x7A222222]
    add     edx, [0x7A444444]
    cmp     edx, eax
    jle     xok
    mov     edx, eax
xok:
    cmp     edx, [esi+0x28]
    jle     xok2
    mov     edx, [esi+0x28]
xok2:
    mov     [0x7B111111], edx
    mov     edx, [0x7A333333]
    add     edx, [0x7A555555]
    cmp     edx, ecx
    jle     yok
    mov     edx, ecx
yok:
    cmp     edx, [esi+0x2C]
    jle     yok2
    mov     edx, [esi+0x2C]
yok2:
    mov     [0x7B222222], edx
; P = override (one-shot) else [g_stripe_period] (law stripe_period) -> ebx ; hN = (P+1)>>1
    mov     eax, [0x7B777777]
    test    eax, eax
    jz      natp
    mov     dword ptr [0x7B777777], 0
    jmp     havep
natp:
    mov eax, dword ptr [0x66879c]
havep:
    mov     ebx, eax
    lea     ecx, [eax+1]
    shr     ecx, 1
    mov     [0x7B333333], ecx
    mov     edi, [0x7A333333]
    test    edi, edi
    jge     ycl
    xor     edi, edi
ycl:
    cmp     edi, [esi+0x24]
    jge     yloop
    mov     edi, [esi+0x24]
yloop:
    cmp     edi, [0x7B222222]
    jge     done
; row colours: dl=navy(C4/41), dh=blue(E0/E1), g_rm_col=teal(AE/EE), g_rm_bdcol=backdrop(C6/41)
; v8: the grid row is edi + g_rm_yph (0 unless thunk_btn_stripes v13 staged the button's parent-local top)
    mov     eax, edi
    add     eax, [0x7F888888]
    xor     edx, edx
    div     ebx
    cmp     edx, [0x7B333333]
    mov     dx, 0xE0C4
    jl      top_cols
    mov     dx, 0xE141
    mov     byte ptr [0x7B444444], 0xEE
    mov     byte ptr [0x7C333333], 0x41
    mov     byte ptr [0x7F333333], 0x41
    mov     byte ptr [0x7F444444], 0x53
    mov     byte ptr [0x7F777777], 0xB9
    jmp     colsok
top_cols:
    mov     byte ptr [0x7B444444], 0xAE
    mov     byte ptr [0x7C333333], 0xC6
    mov     byte ptr [0x7F333333], 0xC5
    mov     byte ptr [0x7F444444], 0xBF
    mov     byte ptr [0x7F777777], 0xF0
colsok:
    mov     eax, [esi+0x4a8]
    imul    eax, edi
    add     eax, [esi+0x54]
    mov     ecx, [0x7A222222]
    test    ecx, ecx
    jge     xcl
    xor     ecx, ecx
xcl:
    cmp     ecx, [esi+0x20]
    jge     xstart
    mov     ecx, [esi+0x20]
xstart:
    lea     ebp, [eax+ecx]
xloop:
    cmp     ecx, [0x7B111111]
    jge     nextrow
    mov     al, [ebp]
    cmp     al, 0xE0
    je      wr_blue
    cmp     al, 0xE1
    je      wr_blue
    cmp     al, 0xAE
    je      wr_teal
    cmp     al, 0xEE
    je      wr_teal
    cmp     al, 0x41
    je      chk41
    cmp     al, 0xC4
    je      chk_navy
    cmp     al, 0xC5
    je      chk_c5
    cmp     al, 0xBF
    je      chk_bf
    cmp     al, 0x53
    je      chk_bf
    cmp     al, 0xF0
    je      chk_f0
    cmp     al, 0xB9
    je      chk_f0
    cmp     al, 0xC6
    jne     skip
    cmp     byte ptr [0x7C222222], 0
    je      skip
wr_bd:
    mov     al, [0x7C333333]
    mov     [ebp], al
    jmp     skip
chk_c5:
    cmp     byte ptr [0x7F111111], 0
    je      skip
wr_c5:
    mov     al, [0x7F333333]
    mov     [ebp], al
    jmp     skip
chk_bf:
    cmp     byte ptr [0x7F222222], 0
    je      skip
    mov     al, [0x7F444444]
    mov     [ebp], al
    jmp     skip
chk_f0:
    cmp     dword ptr [0x7F666666], 0
    je      skip
    mov     al, [0x7F777777]
    mov     [ebp], al
    jmp     skip
chk41:
    cmp     byte ptr [0x7B666666], 0
    jne     wr_navy
    cmp     byte ptr [0x7C222222], 0
    jne     wr_bd
    cmp     byte ptr [0x7F111111], 0
    jne     wr_c5
    jmp     skip
chk_navy:
    cmp     byte ptr [0x7B666666], 0
    je      skip
wr_navy:
    mov     [ebp], dl
    jmp     skip
wr_teal:
    mov     al, [0x7B444444]
    mov     [ebp], al
    jmp     skip
wr_blue:
    mov     [ebp], dh
skip:
    inc     ebp
    inc     ecx
    jmp     xloop
nextrow:
    inc     edi
    jmp     yloop
done:
    pop     ebp
    pop     edi
    pop     esi
    pop     ebx
ret0:
    ret
""")

# ============ thunk_box_thick_devfill v2 @ 0x4220 ============
# v1 (165B @0xE00) + stripe tail. Drop-in for a Buffer_box_sprite call
# (ecx=dest, [esp+4]=&rect, [esp+8]=params; RET 8). Scratch globals unchanged
# (g_devfill_rect/params keep their 0xEF0/0xEC0 slots).
thunk("thunk_box_thick_devfill", 0x42A0, """
    cmp     dword ptr [0x71111111], 0x10
    jg      scaled
    push    0x76222222
    ret
scaled:
    push    ebp
    mov     ebp, esp
    sub     esp, 0x10
    push    ebx
    push    esi
    push    edi
    cld
    mov     [ebp-4], ecx
    mov     eax, [ebp+8]
    mov     [ebp-8], eax
    mov     eax, [ebp+0xc]
    mov     [ebp-0xc], eax
    push    dword ptr [ebp-0xc]
    push    dword ptr [ebp-8]
    mov     ecx, [ebp-4]
    call    0x75444444
    mov     eax, [0x71111111]
    add     eax, 0xf
    shr     eax, 4
    mov     ebx, eax
    lea     edx, [ebx+1]
    mov     edi, [ebp-8]
    mov     eax, [edi]
    add     eax, ebx
    mov     [0x7E222222], eax
    mov     eax, [edi+4]
    add     eax, ebx
    mov     [0x7E333333], eax
    mov     eax, [edi+8]
    sub     eax, edx
    mov     [0x7E444444], eax
    mov     eax, [edi+0xc]
    sub     eax, edx
    mov     [0x7E555555], eax
    mov     esi, [ebp-0xc]
    mov     edi, 0x7E111111
    mov     ecx, 0xa
    rep movsd dword ptr es:[edi], dword ptr [esi]
    mov     edi, 0x7E111111
    xor     eax, eax
    mov     ecx, 8
    rep stosd
    push    0x7E111111
    push    0x7E222222
    mov     ecx, [ebp-4]
    call    0x75222222
; ---- v2 stripe tail: interior 1px device dither -> popup P-stripe language ----
    mov     ecx, [ebp-4]
    cmp     ecx, 0x940824
    je      quote_too
quote_too:
    mov     [0x7A111111], ecx
    mov     edi, [ebp-8]
    mov     eax, [edi]
    mov     [0x7A222222], eax
    mov     edx, [edi+8]
    sub     edx, eax
    inc     edx
    mov     [0x7A444444], edx
    mov     eax, [edi+4]
    mov     [0x7A333333], eax
    mov     edx, [edi+12]
    sub     edx, eax
    inc     edx
    mov     [0x7A555555], edx
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    nop
    mov     dword ptr [0x7C111111], 1
    call    0x75333333
tail_done:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     8
""")

def template(name):
    """(offset, placeholder byte template) for one thunk, exactly as patches.yaml carries it."""
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    cs = Cs(CS_ARCH_X86, CS_MODE_32)
    for n, offset, asm in THUNKS:
        if n != name:
            continue
        va = PCAVE2 + offset
        src = "\n".join(l.split(";")[0] for l in asm.splitlines())
        enc, _ = ks.asm(src, va)
        b = bytes(enc)
        parts = []
        for ins in cs.disasm(b, va):
            raw = ins.bytes
            hexs = " ".join(f"{x:02X}" for x in raw)
            if raw[0] in (0xE8, 0xE9) and len(raw) == 5:
                tgt = (ins.address + 5 + int.from_bytes(raw[1:], "little", signed=True)) & 0xFFFFFFFF
                if tgt in CALL_SENT:
                    hexs = f"{raw[0]:02X} " + CALL_SENT[tgt]
            else:
                for sent, ph in SENT.items():
                    sb = " ".join(f"{x:02X}" for x in sent.to_bytes(4, "little"))
                    if sb in hexs:
                        hexs = hexs.replace(sb, ph)
            parts.append(hexs)
        return offset, " ".join(parts), len(b)
    raise KeyError(name)


if __name__ == "__main__":
    for name, offset, _asm in THUNKS:
        _off, yaml_bytes, n = template(name)
        va = PCAVE2 + offset
        print(f"==== {name} @ pcave2+0x{offset:X} (VA 0x{va:X}) len={n} ends 0x{offset+n:X} ====")
        print(f'  bytes: "{yaml_bytes}"')
        print()
