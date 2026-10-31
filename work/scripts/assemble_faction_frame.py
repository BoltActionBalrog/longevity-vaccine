#!/usr/bin/env python
# Keystone assembler for the faction-quote concentric double-frame — g(x) rewrite
# (2026-07-08). Replaces the tuned per-edge delta stacks in thunk_d5a0_center
# (OUTER d5a0) and thunk_channel_adjust (INNER d528) with a single law:
#
#     each stroke rect = its PRISTINE-NATIVE rect x g/16
#
# Native rects (frida hook_factionquote.js, PRISTINE terranx_pristine.exe g=16,
# faction winbuf 722x193, params-tagged):
#     d5a0 OUTER = (139, 12, 718, 161)
#     d528 INNER = (142, 15, 715, 158)   (= outer inset 3px on all sides)
#
# Why this is regression-proof: the box itself is now box_w = 722*g/16 exactly
# (thunk_scale_boxw v3, 2026-07-08), so native*g/16 frame coords are box-consistent
# at EVERY resolution. Outer.top = 12*g/16 == the portrait top (thunk_portrait_drop
# already emits 12*g/16), so portrait and outer stroke are flush by construction.
# Channel = (inner-outer)*g/16 = 3*g/16 uniform. No coupling, no draw-order
# dependency, pure function of g -- the deltas that drifted are gone.
#
# WHY the deltas regressed (the thing we are deleting): the old chain positioned
# the frame from an UNSCALED content_top via additive grows (box_thick Delta,
# channel ps4->ps3, d5a0_center inward Delta). Composed integer deltas don't
# reconstruct native*g/16, so at g=40 the outer landed at top 22 (want 30 -> 8px
# too high) and the channel at 11 (want ~7). Measured: work\tests\frida_factionquote.log.
#
# thunk_d5a0_center: keeps the +Delta/-Delta inward pre-shift AFTER setting
# native*g/16 so thunk_box_thick_hollow's outward Delta grow cancels -> the OUTER
# stroke lands exactly on native*g/16. thunk_channel_adjust draws flat (Delta=0 via
# thunk_box_thick_hollow_flat) so the INNER needs no pre-shift.
#
# RELOCATED to the free .pcave2 tail (old 0x900/0x940 slots outgrew; they revert to
# section zero-padding). Callers reference both via {abs32:} placeholders, which the
# patcher re-resolves to the new offsets automatically.
#
# Regenerate if any cave offset moves (absolute addrs are baked as sentinels then
# tokenized back to {abs32:name} for the yaml).

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)
from capstone import Cs, CS_ARCH_X86, CS_MODE_32

PCAVE2 = 0xA0C000
OFF_D5A0     = 0x6900             # thunk_d5a0_center    (relocated from 0x940)
OFF_CHANNEL  = 0x6A00            # thunk_channel_adjust (relocated from 0x900)
OFF_PORTRAIT = 0x6B00            # thunk_portrait_drop  (relocated from 0xDA0; +X-scale outgrew slot)
OFF_WRAPWIDTH = 0x6E00           # thunk_faction_wrapwidth (v12; free tail, highest prior alloc 0x6D50)

# --- symbol sentinels (unique, collision-free); tokenized to {abs32:name} after ---
SENT = {
    0xE1E1E1E1: "g_popup_scale_num",
    0xE2E2E2E2: "g_faction_quote",
    0xE3E3E3E3: "g_frame_inset_rect",
    0xE4E4E4E4: "thunk_box_thick_hollow",
    0xE5E5E5E5: "thunk_pf_frame_align",
    0xE6E6E6E6: "FUN_005e4b4a",
    0xE7E7E7E7: "thunk_box_thick_hollow_flat",
    0xE8E8E8E8: "thunk_frame_intK",
    0xE9E9E9E9: "g_faction_text_bottom",
    0xEAEAEAEA: "thunk_box_thick_devfill",
    0xEBEBEBEB: "g_fac_body_bottom",
    0xECECECEC: "Buffer_wrap_height_flying",
}
G      = 0xE1E1E1E1
FQ     = 0xE2E2E2E2
INSET  = 0xE3E3E3E3
THICK  = 0xE4E4E4E4
ALIGN  = 0xE5E5E5E5
SDRAW  = 0xE6E6E6E6
FLAT   = 0xE7E7E7E7
INTK   = 0xE8E8E8E8
TEXTBOT = 0xE9E9E9E9
DEVFILL = 0xEAEAEAEA
FACBOT = 0xEBEBEBEB   # g_fac_body_bottom: dedicated (un-clobbered) copy of the faction quote's real text bottom
WRAPFLY = 0xECECECEC  # Buffer_wrap_height_flying (0x5DDDA0): tail-jmp target of thunk_faction_wrapwidth
WINH   = 0x009408A8   # faction winbuf (0x940824) + 0x84 = H field (stored NEGATIVE)
TEXTBOT_G = 0x009B8CE8  # g_popup_body_bottom: ACTUAL drawn text bottom (Buffer_write_strings return, stored by BasePop_on_redraw)
BOT_MARGIN = 3         # native px gap text-bottom -> inner frame bottom (scaled x g/16 = ps(BOT_MARGIN)); TUNABLE knob

# 2026-07-08 v8: CONCENTRIC-FROM-ENGINE-RECT (abandon the from-scratch native*g/16 L/T/R).
# The whole quote+attribution is drawn by ONE engine Buffer_write_strings (BasePop_on_redraw)
# from the engine's content geometry -- the text is positioned by the ENGINE, not us. v1-v7 set
# the frame L/T/R from native*g/16 (fixed), which DECOUPLED the frame from where the engine draws
# the text -> Yang's top line pokes above inner.T=37 (the "overflow"), and any per-side mismatch
# between d528_inset's engine-rect insets and our fixed coords shows as a lopsided channel.
# v8 derives the frame from the engine content rect on ALL sides: thunk_channel_adjust (reverted
# to the committed delta form) sets the INNER = engine g_frame_inset_rect (tracks the text box);
# thunk_d5a0_center then sets OUTER = that inner grown by ps3=(3g)>>4 on all four sides -> the
# channel is EXACTLY ps3 everywhere by construction, and the whole frame stays locked to the text
# so it can't overflow. Both still render via thunk_frame_intK (integer-K uniform strokes). Reads
# g_frame_inset_rect via edi (offset addressing; the raw INSET sentinel can't carry a +disp).
d5a0_asm = f"""
    cmp dword ptr [{G}], 0x10
    jle nonfac
    cmp dword ptr [{FQ}], 1
    jne nonfac
    push ebx
    push edi
    mov ebx, [{G}]
    imul ebx, ebx, 3
    sar ebx, 4
    mov edi, {INSET}
    mov edx, [esp+0xc]
    mov eax, [edi]
    sub eax, ebx
    mov [edx], eax
    mov eax, [edi+4]
    sub eax, ebx
    mov [edx+4], eax
    mov eax, [edi+8]
    add eax, ebx
    mov [edx+8], eax
    mov eax, [edi+0xc]
    add eax, ebx
    mov [edx+0xc], eax
    pop edi
    pop ebx
    mov dword ptr [{FQ}], 0
    push {INTK}
    ret
nonfac:
    push {THICK}
    ret
"""

# INNER d528 (v12, MEASURE-SOURCED + DERIVED K): L/T/R stay the committed delta form (inner = ENGINE
# g_frame_inset_rect, the text-fitted content box, nudged by d=ps4-ps3). The BOTTOM is derived from the
# engine's FRESH per-quote content MEASURE, read at frame-draw time -- never captured/fed forward (the
# v9/v10 capture architecture is unsound: the frame draws BEFORE the text, and consecutive redraws carry
# DIFFERENT-length quotes, so any captured bottom is the WRONG quote's -> it never settles).
#
#     inner.B = content_top + content_h + ps3 + K
#
# where K = y_in - content_top = the Y offset thunk_faction_textmargin itself applies to the text draw.
# Read straight off that thunk's bytes (disasm 0xA0C6C0), NOT fitted:
#     K = g - ps4 + 2*ps3 - 18      (ps4 = g>>2, ps3 = (3g)>>4)
#       = 26 @g40, 9 @g25, 7 @g22, 0 @g16   <- exact native no-op, verified live at all three res
# v11 used K=(9g-152)>>3, a 2-POINT FIT through g=40/25 that silently gives 5 (not 7) at g=22 (1920x1080)
# and -1 at g=16 -- an eyeballed magnitude. Ground truth (hook_factexact, 26 draws @ g=40/25/22): the
# drawn bottom minus measB equals K exactly, every leader, every resolution, 0 mismatches.
#
# Substituting ps4 = d + ps3 folds the whole bottom into the regs already live (eax=d, ebx=ps3):
#     inner.B = (content_top + content_h) - d + 2*ps3 + g - 18
# content_top=[P+0x30e8]+[P+0x30e0], content_h=[P+0x30d4], P=faction popup 0x009403E0 (fixed addr, same
# as the esi gate). ps3 = the text->inner-stroke gap (= channel width, uniform); thunk_d5a0_center grows
# the outer by +ps3. ecx (dest buffer) PRESERVED. Requires thunk_faction_wrapwidth so content_h counts
# the lines the draw actually renders (else a wrap-width desync makes content_h under-count -> overflow).
channel_asm = f"""
    cmp dword ptr [{FQ}], 1
    jne skip
    cmp dword ptr [{G}], 0x10
    jle skip
    push ebx
    mov eax, [{G}]
    mov ebx, eax
    sar eax, 2
    lea ebx, [ebx+ebx*2]
    sar ebx, 4
    sub eax, ebx
    mov edx, {INSET}
    sub [edx], eax
    sub [edx+4], eax
    add [edx+8], eax
    neg eax
    add eax, [0x009434c8]
    add eax, [0x009434c0]
    add eax, [0x009434b4]
    add eax, ebx
    add eax, ebx
    add eax, [{G}]
    sub eax, 18
    mov [edx+0xc], eax
    pop ebx
skip:
    push {ALIGN}
    ret
"""

# thunk_faction_wrapwidth (v12, THE OVERFLOW ROOT CAUSE FIX). BasePop_calculate_dimensions wraps the
# quote at the FULL interior width (ebx = [30bc] - 2*[30e0] - [21c8] - [30d8], set @0x603d82..0x603da8)
# and pushes it as arg2 to Buffer_wrap_height_flying. But the DRAW wraps NARROWER: thunk_faction_textmargin
# does `width -= 4*ps3 - 12` (16 @g40, 4 @g25/g22, 0 @g16 -- read off its bytes; terranx.h's old
# "2*ps4+2*ps3-12" note was WRONG). Word-wrap turns that constant width delta into a whole-LINE step, so
# any quote with a line ending inside the delta renders one MORE line than the box was measured for ->
# that line punches through the inner bottom stroke (Yang @4K; harmless at 1600 where the delta is 4).
#
# The DRAW is faithful (its inset is the vanilla 3px margin x g/16, no-op at g=16) -- widening it shoves
# text into the right border. So we narrow the MEASURE by the SAME amount: measure wraps == draw wraps
# => content_h counts the lines actually rendered => the box grows to hold them => the frame encloses.
# Text layout does not move; only the box height changes.
#
# Proof that this is exactly symmetric (hook_factfields, 3 res): box_width [30bc] grows by precisely
# [30f4]+[30f0] between calc and draw (thunk_scale_boxw), so the draw's pre-narrowing width
# ([30bc]+f4+f0) - [30d8] - f4 - f0 == [30bc] - [30d8] == the measure's ebx. The ONLY delta between
# measure and draw is textmargin's own subtraction. Hence: subtract 4*ps3-12 here.
#
# Entered via E8 from BOTH wrap_height_flying call sites in calculate_dimensions (0x603e42, 0x603f3d);
# [esp]=ret, [esp+4]=str, [esp+8]=width. ecx = the popup's winbuf ([esi+0xa3c]+0x444) -> 0x940824 is the
# faction quote's, a clean faction-only identity gate (same gate thunk_portrait_drop uses). eax/edx are
# call-clobbered (wrap_height_flying trashes them anyway); ecx PRESERVED. Tail-jmps to
# Buffer_wrap_height_flying with the ret addr + args intact -- its RET 8 returns to the caller and cleans
# the 2 args, exactly as a direct call would. D(16)=0 so the native path is byte-identical.
wrapwidth_asm = f"""
    cmp ecx, 0x940824
    jne tail
    mov eax, [{G}]
    cmp eax, 0x10
    jle tail
    lea edx, [eax+eax*2]
    sar edx, 4
    shl edx, 2
    sub edx, 12
    sub dword ptr [esp+8], edx
tail:
    push {WRAPFLY}
    ret
"""

# thunk_fac_bottom_stash: capture detour at the on_redraw text-bottom store (0x604E1A,
# `mov [0x9b8ce8],eax` after Buffer_write_strings). ENTERED VIA E8 CALL (the site's E8 pushes the
# resume addr 0x604E1F) -> bare RET consumes it and resumes there. Replays the store, then for the
# faction quote popup (esi==0x9403e0) copies eax (the REAL drawn text bottom) into the dedicated
# g_fac_body_bottom (nothing else writes it, so it survives other windows' redraws). esi/eax
# preserved; only flags touched (overwritten by the CMP at 0x604E21 before its JG).
facbot_stash_asm = f"""
    mov dword ptr [0x009b8ce8], eax
    cmp esi, 0x009403e0
    jne s
    mov dword ptr [{FACBOT}], eax
s:
    ret
"""

# thunk_d690_fill: at the shared d690 backdrop draw (0x405f77 -> was direct to devfill), extend
# the FACTION quote backdrop's bottom to the full box height so the bottom-anchored attribution
# sits on the backdrop (not black) and the frame encloses it. dest(ecx)==0x940824 gate keeps every
# OTHER popup's d690 byte-identical. Sets [rect].bottom = box_h = -[0x9408A8]; tail push devfill.
d690_asm = f"""
    cmp dword ptr [{G}], 0x10
    jle tail
    cmp ecx, 0x940824
    jne tail
    push ebx
    mov ebx, dword ptr [{WINH}]
    neg ebx
    mov eax, [esp+8]
    mov [eax+0xc], ebx
    pop ebx
tail:
    push {DEVFILL}
    ret
"""

# thunk_portrait_drop: keep the Y drop (12*(g-16)/16 == 12*g/16 for native y=12) AND
# add an X-scale -- the portrait's x arrives UNSCALED-offset (drawn 20 @g40 vs faithful
# 5*g/16=12), butting the outer stroke. SET x = 5*g/16 (native x=5) so the portrait
# lands faithfully and the outer stroke (139*g/16=347) clears its right edge (340) by
# the faithful 3*g/16 gap. Gate dest==0x940824 & g>16 (native no-op at g<=16).
portrait_asm = f"""
    cmp dword ptr [esp+4], 0x940824
    jne tail
    mov eax, [{G}]
    cmp eax, 0x10
    jle tail
    sub eax, 0x10
    imul eax, eax, 12
    sar eax, 4
    add [esp+0x10], eax
    mov eax, [{G}]
    imul eax, eax, 5
    sar eax, 4
    mov [esp+0xc], eax
tail:
    push {SDRAW}
    ret
"""

# thunk_dfstep1_dispatch: devfill's STEP1 frame-render dispatcher. devfill draws EVERY
# popup's d690 backdrop + d528 body, so its STEP1 (thunk_box_thick_hollow_flat, fractional)
# can't be globally swapped yet. This wrapper (entered via CALL from devfill STEP1, same
# ecx=dest/[esp+4]=rect/[esp+8]=params contract) routes ONLY the faction quote window buffer
# (dest 0x940824 -> d690 + d528) to thunk_frame_intK (integer-K, exact footprint -> concentric
# with the intK outer), and every other popup to the unchanged hollow_flat. Tail-jmps (push;ret)
# so the target's RET 8 returns straight to devfill with the 2 args cleaned. ecx/args untouched.
dfstep1_asm = f"""
    cmp ecx, 0x940824
    jne frac
    push {INTK}
    ret
frac:
    push {FLAT}
    ret
"""

ks = Ks(KS_ARCH_X86, KS_MODE_32)
cs = Cs(CS_ARCH_X86, CS_MODE_32)


def build(name, asm, va, slot_end):
    src = "\n".join(l.split(";")[0] for l in asm.splitlines())
    enc, _ = ks.asm(src, va)
    b = bytes(enc)
    off = va - PCAVE2
    print(f"\n=== {name} @ VA 0x{va:X} (pcave2 + 0x{off:X}) ===")
    print(f"length = {len(b)} bytes -> ends 0x{off + len(b):X} (slot must stay < 0x{slot_end:X})")
    assert off + len(b) <= slot_end, "OVERFLOW"
    for i in cs.disasm(b, va):
        print(f"  {i.address:08X}  {i.bytes.hex(' '):<22}  {i.mnemonic} {i.op_str}")
    # tokenize: replace each sentinel's LE bytes with {abs32:name}
    parts, i = [], 0
    while i < len(b):
        for sent, sym in SENT.items():
            le = sent.to_bytes(4, "little")
            if b[i:i+4] == le:
                parts.append("{abs32:" + sym + "}")
                i += 4
                break
        else:
            parts.append(f"{b[i]:02X}")
            i += 1
    print("YAML bytes:")
    print(" ".join(parts))
    return b


build("thunk_d5a0_center", d5a0_asm, PCAVE2 + OFF_D5A0, 0x6A00)
build("thunk_channel_adjust", channel_asm, PCAVE2 + OFF_CHANNEL, 0x6B00)
build("thunk_portrait_drop", portrait_asm, PCAVE2 + OFF_PORTRAIT, 0x6C00)
build("thunk_faction_wrapwidth", wrapwidth_asm, PCAVE2 + OFF_WRAPWIDTH, 0x6E80)
# v7: thunk_d690_fill DEPRECATED (backdrop reverts to pristine's per-draw window rect; the
# 0x405f77 call site is repointed back to thunk_box_thick_devfill in patches.yaml). Its cave
# content is left as unreferenced deprecated space. d690_asm retained above for reference only.
# build("thunk_d690_fill", d690_asm, PCAVE2 + 0x6D00, 0x6D40)

# v10: g_fac_body_bottom @ 0x6D40 (4B dedicated global) ; thunk_fac_bottom_stash @ 0x6D50
build("thunk_fac_bottom_stash", facbot_stash_asm, PCAVE2 + 0x6D50, 0x6D90)
