#!/usr/bin/env python
"""ORNATE band-map blit (group frame_bandmap_ornate, 2026-09-19): the 9-slice band map for the ornate def
&0x6846B0 (corner canvas 61x44) with the stroke cell pinned PER SIDE and the outer transparent margin re-keyed.

PORT OF: scaling_laws.py :: chrome_band_widths / axis_map_chrome / ornate_outer_key (the SOURCE OF TRUTH).
Parity: tests\\test_bandmap_ornate_asm_parity.py (Unicorn).  Evidence: tech-breakthrough shots 20260919-1543xx.

DEFECTS (both in the shared renderer, every ornate menu): the inner green line drew 2/3 px left/right @4K and 1/2
@1600 + 1920 (vanilla 1/1), and the device-density underlay showed as a dark rim outside the metal where vanilla
is transparent.  One cause: thunk_bandmap_blit pins cells 0 and 1 of the corner band to K — right for plain defs
(stroke + bevel), wrong here, where cells 0..3 are transparent margin and the stroke is cell 7/8/7/5.

DESIGN — the verified thunk_bandmap_blit stays BYTE-IDENTICAL, so no plain frame can move:
  thunk_bandmap_sel   head on thunk_frame_enlarge's ONE `E8 thunk_bandmap_blit`: g_band_nx == 61 && g_band_ny ==
                      44 (the ornate def's corner canvas; consumed later by whichever blit runs) -> the ornate
                      blit, else the old blit.  Same stack, push;ret.
  thunk_bandmap_orn   thunk_bandmap_blit's OWN SOURCE with asserted edits (derive(), below):
                        * bm_axis takes (c_near, c_far, farbuf): the forward table is built twice, the far band
                          reads its own table (not a mirror of the near band);
                        * bm_cum's pinned mode = ONE chrome cell c: y <= c -> hd(y*rem, n-1), else K + hd((y-1)*
                          rem, n-1), rem = B - K;
                        * post-pass (key != -1): ornate_outer_key — walking in from each dest edge while the mapped
                          source pixel is the key, write the key to the dest (clipped like the copy loop).
Native no-op: the renderers never reach the enlarge at g<=16 (assemble_bandmap.py), so neither thunk runs.

FIX 26 v2 (2026-10-24, user-approved "F2 + P", reworked after audit26; laws scaling_laws.ornate_popup_axis_map_x /
_row_map / _row_mirrors / _outer_width / popup_content_frame_right / ornate_popup_margin_r; guards
tests\\test_bandmap_ornate_asm_parity.py + tests\\test_scaling_ornate_popup_symmetry.py):
  * bm_axis takes a 4th extra arg `skip` (_mirror(), below): the x call pushes dword [g_orn_mirror], the y call 0 --
    the mirror-row map, monotone, on the half-open axis.  t_orn_rowcls (once per blit) sets D / E; every column
    lookup goes through t_orn_oc (the per-row law, classes from the art).
  * t_orn_cfpost: thunk_content_frame's tail -- an ornate ring widened to box_w - L moves 1 px onto the half-open
    axis (a patches.yaml edit of the content frame's tail, outside this file's blocks).
  * t_orn_bd_arm sets g_orn_mirror around thunk_tutwin_backdrop; thunk_backdrop_railtrim's tail (the backdrop call
    @0x405F77 only) pushes it instead of thunk_tutwin_backdrop -- a patches.yaml edit outside this file's blocks.
    NetTechWin's direct call (0x483998) never arms it.
  * t_orn_rmargin: the CALL target of the site Popup_calc.ornate_margin_r @0x404E19 (also a separate yaml entry).
FIX 26 v3/v4 (2026-10-24, audit26b F1/F3/F4 + the user's corner decision "O4"; law scaling_laws.ornate_popup_row_class /
_dup_start / _rows_continue / _line_end / _row_map): the row classes are BLOCKS of the art -- t_orn_rcls (+ t_orn_rpat,
the mirror pattern, and t_orn_rnb, the foot link) classifies a source row CORNER / MIRROR / DUP; t_orn_oc shifts the
right's outer segment one source column outward on a non-MIRROR row (DUP through the line: jj < E; CORNER left of it:
jj < D) -- the old outer cells at vanilla x g/16, the duplicate line column / the corner's innermost column dropped;
t_orn_rowcls sets D and E = D + K.  (v3's corner squeeze and its t_orn_rowfill are gone.)  v5 (audit26c N1):
t_orn_rplain marks a row with no extra column at all (both line columns key, equal key runs: the bottom edge's last
row) PLAIN -- the near layout unshifted across the whole far band (jj < b), so its key runs stay equal.

Usage: py assemble_bandmap_ornate.py            (assemble + checks)
       py assemble_bandmap_ornate.py --splice   (splice into ..\\patches\\patches.yaml, byte-safe, idempotent)
"""
from __future__ import annotations

import pathlib
import sys

from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import assemble_bandmap as AB  # noqa: E402
import scaling_laws as SL  # noqa: E402

PCAVE2 = 0x00A0C000
BASE_OFF = 0x2F600                     # cave_map: free tail after the ntw_scale block (ends < 0x2F5E0)
LIMIT_OFF = 0x2FE20                    # t_orn_fieldsub (cave_map --at 0x2f840: next code starts 0x2fe20)
OFF_FARX, OFF_FARY = BASE_OFF, BASE_OFF + 0x100
OFF_SEL = BASE_OFF + 0x200
OFF_ORN = BASE_OFF + 0x240
OLD_BLIT = PCAVE2 + 0xA300             # thunk_bandmap_blit
G_BAND_NX, G_BAND_NY = PCAVE2 + 0xA200, PCAVE2 + 0xA204
NX, NY = SL.ORNATE_BAND
(CX_NEAR, CX_FAR), (CY_NEAR, CY_FAR) = SL.ORNATE_STROKE_CELL["x"], SL.ORNATE_STROKE_CELL["y"]

SENT = dict(AB.SENT)
SENT.update({0x73111111: "{abs32:g_bmo_farx}", 0x73222222: "{abs32:g_bmo_fary}",
             0x73333333: "{abs32:thunk_bandmap_blit}", 0x73444444: "{abs32:thunk_bandmap_orn}",
             0x73555555: "{abs32:g_orn_mirror}", 0x73666666: "{abs32:thunk_pf_union_align}"})
# fix 26 (F2 + P): the popup-backdrop arm of the far-band mirror, its flag, and the ornate right margin.
OFF_ARM, OFF_MIRROR = 0x1620, 0x165C   # cave_map --at 0x1620: FREE 0x161c..0x1660 (old thunk_btn_fillcap slot)
OFF_RMARGIN = 0x2EE0                   # cave_map --at 0x2ee0: FREE 0x2ee0..0x2f00
OFF_OC = 0x2DF60                       # fix 26 v2: cave_map --at 0x2df60: FREE 0x2df5e..0x2e000
OFF_CFPOST = 0x2E9B0                   # cave_map --at 0x2e9b0: FREE 0x2e9a8..0x2ea00
OFF_ROWCLS = 0x1F70                    # cave_map --at 0x1f70: FREE 0x1f68..0x2000
OFF_RCLS = 0x5570                      # fix 26 v3: cave_map: FREE 0x5565..0x5600
OFF_RPAT = 0x29E30                     # fix 26 v3: cave_map: FREE 0x29e22..0x29eb0
OFF_RNB = 0x2560                       # fix 26 v3: cave_map: FREE 0x2558..0x25e0
OFF_RPLAIN = 0x0E70                    # fix 26 v5: cave_map --at 0xe70: FREE 0xe6f..0xec0 (g_devfill_params at 0xEC0)
UNION_ALIGN = PCAVE2 + 0x35000         # thunk_pf_union_align (v18 RELOCATED 0xC1C0 -> 0x35000, F34)
TUTWIN_BACKDROP = PCAVE2 + 0xA920      # thunk_tutwin_backdrop
G_POPUP_SCALE_NUM = 0x668740


def _sub(s: str, old: str, new: str, count: int = 1) -> str:
    assert s.count(old) == count, (s.count(old), old[:60])
    return s.replace(old, new)


def derive() -> str:
    a = dict((n, s) for n, _o, s in AB.THUNKS)["thunk_bandmap_blit"]
    # ---- call sites: 3 extra args (c_near, c_far, farbuf) pushed FIRST (cdecl tail), cleanup 24 -> 36
    a = _sub(a, """    push    0x71555555
    push    0x71333333
    push    dword ptr [ebp-12]
    push    dword ptr [ebp+0x18]
    push    dword ptr [ebp+0x28]
    push    dword ptr [ebp-48]
    call    bm_axis
    add     esp, 24""", f"""    push    0x73111111
    push    {CX_FAR}
    push    {CX_NEAR}
    push    0x71555555
    push    0x71333333
    push    dword ptr [ebp-12]
    push    dword ptr [ebp+0x18]
    push    dword ptr [ebp+0x28]
    push    dword ptr [ebp-48]
    call    bm_axis
    add     esp, 36""")
    a = _sub(a, """    push    0x71666666
    push    0x71444444
    push    dword ptr [ebp-12]
    push    dword ptr [ebp+0x1c]
    push    dword ptr [ebp+0x2c]
    push    dword ptr [ebp-52]
    call    bm_axis
    add     esp, 24""", f"""    push    0x73222222
    push    {CY_FAR}
    push    {CY_NEAR}
    push    0x71666666
    push    0x71444444
    push    dword ptr [ebp-12]
    push    dword ptr [ebp+0x1c]
    push    dword ptr [ebp+0x2c]
    push    dword ptr [ebp-52]
    call    bm_axis
    add     esp, 36""")
    # ---- bm_axis: pinned mode = ONE chrome cell -> rem = B - K, m = n - 1
    a = _sub(a, """    mov     eax, [ebp-4]
    sub     eax, [ebp+0x14]
    sub     eax, [ebp+0x14]
    mov     [ebp-12], eax
    mov     eax, [ebp+8]
    sub     eax, 2
    mov     [ebp-16], eax
ax_mode_done:
""", """    mov     eax, [ebp-4]
    sub     eax, [ebp+0x14]
    mov     [ebp-12], eax
    mov     eax, [ebp+8]
    dec     eax
    mov     [ebp-16], eax
ax_mode_done:
    /* two forward tables: pass 0 -> fbuf with c_near, pass 1 -> farbuf with c_far.
       locals: -36 c (read by bm_cum), -40 pass */
    mov     dword ptr [ebp-40], 0
    mov     eax, [ebp+0x20]
    mov     [ebp-36], eax
ax_pass:
""")
    a = _sub(a, """    mov     edi, [ebp+0x18]
    add     edi, [ebp-20]
    mov     eax, [ebp-24]
ax_fill:""", """    mov     edi, [ebp+0x18]
    cmp     dword ptr [ebp-40], 0
    je      ax_tgt
    mov     edi, [ebp+0x28]
ax_tgt:
    add     edi, [ebp-20]
    mov     eax, [ebp-24]
ax_fill:""")
    a = _sub(a, """ax_build_out:
    mov     edi, [ebp+0x1c]""", """ax_build_out:
    cmp     dword ptr [ebp-40], 0
    jne     ax_tables_done
    mov     dword ptr [ebp-40], 1
    mov     eax, [ebp+0x24]
    mov     [ebp-36], eax
    jmp     ax_pass
ax_tables_done:
    mov     edi, [ebp+0x1c]""")
    # the y loop's init must sit INSIDE the pass loop: move it under ax_pass
    a = _sub(a, """    /* fbuf: pos=0; for y=0..n-1: repeat width(y): fbuf[pos++] = y */
    mov     dword ptr [ebp-20], 0
    mov     dword ptr [ebp-24], 0
ax_y_loop:""", """ax_y_loop:""")
    a = _sub(a, """ax_pass:
""", """ax_pass:
    mov     dword ptr [ebp-20], 0
    mov     dword ptr [ebp-24], 0
""")
    # far band reads its own table
    a = _sub(a, """ax_far:
    cmp     ebx, [ebp+0xc]
    jge     ax_ok""", """ax_far:
    mov     esi, [ebp+0x28]
ax_far_loop:
    cmp     ebx, [ebp+0xc]
    jge     ax_ok""")
    a = _sub(a, """    mov     [edi+ebx*2], ax
    inc     ebx
    jmp     ax_far
""", """    mov     [edi+ebx*2], ax
    inc     ebx
    jmp     ax_far_loop
""")
    # ---- bm_cum pinned mode: y <= c -> hd(y*rem, m) ; else K + hd((y-1)*rem, m)
    a = _sub(a, """cum_pinned:
    cmp     eax, 2
    jg      cum_tail
    imul    eax, [ebx+0x14]
    jmp     cum_ret
cum_tail:
    sub     eax, 2
    imul    eax, [ebx-12]
    add     eax, eax
    add     eax, [ebx-16]
    dec     eax
    xor     edx, edx
    mov     ecx, [ebx-16]
    add     ecx, ecx
    div     ecx
    mov     ecx, [ebx+0x14]
    add     ecx, ecx
    add     eax, ecx
cum_ret:""", """cum_pinned:
    push    esi
    xor     esi, esi
    cmp     eax, [ebx-36]
    jle     cum_lin
    dec     eax
    mov     esi, [ebx+0x14]
cum_lin:
    imul    eax, [ebx-12]
    add     eax, eax
    add     eax, [ebx-16]
    dec     eax
    xor     edx, edx
    mov     ecx, [ebx-16]
    add     ecx, ecx
    div     ecx
    add     eax, esi
    pop     esi
cum_ret:""")
    # ---- post-pass: every exit of the copy goes through it
    a = _sub(a, """
done:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0x2c
""", """
done:
    /* ornate_outer_key.  locals: -60 r, -64 cnt, -68 dr */
    cmp     dword ptr [ebp+0x30], -1
    je      pp_done
    mov     eax, [ebp-40]
    cmp     eax, [ebp-44]
    jge     pp_done
    /* rows: from the left and from the right, at most Bx px */
    mov     dword ptr [ebp-60], 0
pp_row:
    mov     eax, [ebp-60]
    cmp     eax, [ebp+0x2c]
    jge     pp_cols
    mov     ecx, [ebp+0x24]
    add     ecx, eax
    js      pp_row_next
    cmp     ecx, [ebp-36]
    jge     pp_cols
    mov     edx, 0x71666666
    movzx   edx, word ptr [edx+eax*2]
    imul    edx, [ebp-20]
    add     edx, [ebp-16]
    mov     esi, edx
    mov     eax, ecx
    imul    eax, [ebp-28]
    add     eax, [ebp-24]
    add     eax, [ebp+0x20]
    mov     edi, eax
    xor     ebx, ebx
pp_left:
    cmp     ebx, [ebp-4]
    jge     pp_right_init
    cmp     ebx, [ebp+0x28]
    jge     pp_right_init
    mov     edx, 0x71555555
    movzx   edx, word ptr [edx+ebx*2]
    movzx   eax, byte ptr [esi+edx]
    cmp     eax, [ebp+0x30]
    jne     pp_right_init
    cmp     ebx, [ebp-40]
    jl      pp_left_next
    cmp     ebx, [ebp-44]
    jge     pp_left_next
    mov     [edi+ebx], al
pp_left_next:
    inc     ebx
    jmp     pp_left
pp_right_init:
    mov     ebx, [ebp+0x28]
    dec     ebx
    mov     eax, [ebp-4]
    mov     [ebp-64], eax
pp_right:
    cmp     dword ptr [ebp-64], 0
    jle     pp_row_next
    test    ebx, ebx
    js      pp_row_next
    mov     edx, 0x71555555
    movzx   edx, word ptr [edx+ebx*2]
    movzx   eax, byte ptr [esi+edx]
    cmp     eax, [ebp+0x30]
    jne     pp_row_next
    cmp     ebx, [ebp-40]
    jl      pp_right_next
    cmp     ebx, [ebp-44]
    jge     pp_right_next
    mov     [edi+ebx], al
pp_right_next:
    dec     ebx
    dec     dword ptr [ebp-64]
    jmp     pp_right
pp_row_next:
    inc     dword ptr [ebp-60]
    jmp     pp_row

    /* columns: from the top and from the bottom, at most By px.  ebx = dest col (clipped i0..i1) */
pp_cols:
    mov     ebx, [ebp-40]
pp_col:
    cmp     ebx, [ebp-44]
    jge     pp_done
    mov     edx, 0x71555555
    movzx   edx, word ptr [edx+ebx*2]
    mov     [ebp-68], edx
    mov     dword ptr [ebp-60], 0
pp_top:
    mov     eax, [ebp-60]
    cmp     eax, [ebp-8]
    jge     pp_bot_init
    cmp     eax, [ebp+0x2c]
    jge     pp_bot_init
    call    pp_probe
    jne     pp_bot_init
    inc     dword ptr [ebp-60]
    jmp     pp_top
pp_bot_init:
    mov     eax, [ebp+0x2c]
    dec     eax
    mov     [ebp-60], eax
    mov     eax, [ebp-8]
    mov     [ebp-64], eax
pp_bot:
    cmp     dword ptr [ebp-64], 0
    jle     pp_col_next
    mov     eax, [ebp-60]
    test    eax, eax
    js      pp_col_next
    call    pp_probe
    jne     pp_col_next
    dec     dword ptr [ebp-60]
    dec     dword ptr [ebp-64]
    jmp     pp_bot
pp_col_next:
    inc     ebx
    jmp     pp_col

pp_done:
    pop     edi
    pop     esi
    pop     ebx
    mov     esp, ebp
    pop     ebp
    ret     0x2c

/* pp_probe: eax = dest row r, ebx = dest col, [ebp-68] = src col.  ZF set iff the mapped source pixel is the key;
   when it is and the dest row is inside the buffer, the key is written.  Uses the blit's frame (ebp unchanged). */
pp_probe:
    mov     edx, 0x71666666
    movzx   edx, word ptr [edx+eax*2]
    imul    edx, [ebp-20]
    add     edx, [ebp-16]
    add     edx, [ebp-68]
    movzx   ecx, byte ptr [edx]
    cmp     ecx, [ebp+0x30]
    jne     pp_probe_ret
    mov     edx, [ebp+0x24]
    add     edx, eax
    js      pp_probe_hit
    cmp     edx, [ebp-36]
    jge     pp_probe_hit
    imul    edx, [ebp-28]
    add     edx, [ebp-24]
    add     edx, [ebp+0x20]
    mov     [edx+ebx], cl
pp_probe_hit:
    cmp     eax, eax
pp_probe_ret:
    ret
""")
    # early exits of the copy that jumped to `done` with an empty x clip still reach pp (it re-checks)
    return _mirror(a)


def _mirror(a: str) -> str:
    """fix 26 v2 (laws scaling_laws.axis_map_chrome skip / ornate_popup_axis_map_x / ornate_popup_row_map).
    bm_axis takes a 4th extra arg `skip` ([ebp+0x2c]; x call: dword [g_orn_mirror], armed only by t_orn_bd_arm; y call:
    0): pass 1 builds the far table with chrome cell c_far - skip and values cell + skip and the far loop reads it as
    is -- with skip 1 the x map is the MIRROR row map (the right band = the near layout one source column out, on the
    half-open axis; monotone).  Then t_orn_rowcls (after the buffer fields) sets D / E, and every column lookup of the
    copy and of the outer-key post-pass goes through t_orn_oc (fx, or fx + 1 on a non-mirror row's outer segment; the
    class from the art, t_orn_rcls).  Frame locals added (fix 26 v4): -76 current dest row, -80 E (0 = off),
    -84 cached dest row, -88 its class, -92 D, -96 the DUP block start (-1 = not scanned)."""
    a = _sub(a, f"""    push    0x73111111
    push    {CX_FAR}
    push    {CX_NEAR}""", f"""    push    dword ptr [0x73555555]
    push    0x73111111
    push    {CX_FAR}
    push    {CX_NEAR}""")
    a = _sub(a, f"""    push    0x73222222
    push    {CY_FAR}
    push    {CY_NEAR}""", f"""    push    0
    push    0x73222222
    push    {CY_FAR}
    push    {CY_NEAR}""")
    a = _sub(a, "    call    bm_axis\n    add     esp, 36", "    call    bm_axis\n    add     esp, 40", count=2)
    a = _sub(a, """    mov     dword ptr [ebp-40], 1
    mov     eax, [ebp+0x24]
    mov     [ebp-36], eax""", """    mov     dword ptr [ebp-40], 1
    mov     eax, [ebp+0x24]
    sub     eax, [ebp+0x2c]
    mov     [ebp-36], eax""")
    a = _sub(a, """ax_tgt:
    add     edi, [ebp-20]
    mov     eax, [ebp-24]
ax_fill:""", """ax_tgt:
    add     edi, [ebp-20]
    mov     eax, [ebp-24]
    cmp     dword ptr [ebp-40], 0
    je      ax_val
    add     eax, [ebp+0x2c]
ax_val:
ax_fill:""")
    # D / E for the per-row classes, once the src/dst fields are known
    a = _sub(a, """    mov     eax, [edi+0x84]
    neg     eax
    mov     [ebp-36], eax
""", f"""    mov     eax, [edi+0x84]
    neg     eax
    mov     [ebp-36], eax
    call    {PCAVE2 + OFF_ROWCLS:#x}
""")
    # the current dest row for t_orn_oc
    a = _sub(a, """row_loop:
    mov     eax, [ebp-56]
    cmp     eax, [ebp+0x2c]
    jge     done
""", """row_loop:
    mov     eax, [ebp-56]
    cmp     eax, [ebp+0x2c]
    jge     done
    mov     [ebp-76], eax
""")
    a = _sub(a, """pp_row:
    mov     eax, [ebp-60]
    cmp     eax, [ebp+0x2c]
    jge     pp_cols
""", """pp_row:
    mov     eax, [ebp-60]
    cmp     eax, [ebp+0x2c]
    jge     pp_cols
    mov     [ebp-76], eax
""")
    # column lookups -> t_orn_oc
    oc = f"    call    {PCAVE2 + OFF_OC:#x}\n"
    a = _sub(a, """    mov     edx, 0x71555555
    movzx   edx, word ptr [edx+ebx*2]
    mov     al, [esi+edx]""", oc + """    mov     al, [esi+edx]""")
    a = _sub(a, """    mov     edx, 0x71555555
    movzx   edx, word ptr [edx+ebx*2]
    movzx   eax, byte ptr [esi+edx]""", oc + """    movzx   eax, byte ptr [esi+edx]""", count=2)
    a = _sub(a, """    mov     edx, 0x71555555
    movzx   edx, word ptr [edx+ebx*2]
    mov     [ebp-68], edx
""", "")
    a = _sub(a, """pp_probe:
    mov     edx, 0x71666666
    movzx   edx, word ptr [edx+eax*2]
    imul    edx, [ebp-20]
    add     edx, [ebp-16]
    add     edx, [ebp-68]
""", """pp_probe:
    mov     [ebp-76], eax
""" + oc + """    mov     ecx, edx
    mov     edx, 0x71666666
    movzx   edx, word ptr [edx+eax*2]
    imul    edx, [ebp-20]
    add     edx, [ebp-16]
    add     edx, ecx
""")
    return a


# t_orn_oc (fix 26 v4): the source column of dest col ebx on the current dest row [ebp-76] -> edx (eax, ecx, ebx, esi,
# edi kept; EFLAGS clobbered -- dead at every call site).  Runs in thunk_bandmap_orn's frame (law ornate_popup_row_map):
# fx[ebx], unless armed (E = [ebp-80] != 0) and ebx lies in the right band (jj = dstW-1-ebx < b = [ebp-4]): then by
# the source row's class (t_orn_rcls, cached per dest row: [ebp-84] row, [ebp-88] class) -- MIRROR (1): fx; PLAIN (3):
# fx + 1; DUP (2): fx + 1 while jj < E; CORNER (0): fx + 1 while jj < D = [ebp-92]; else fx.
ASM_OC = f"""
    movzx   edx, word ptr [0x71555555+ebx*2]
    cmp     dword ptr [ebp-80], 0
    je      oc_ret
    push    eax
    mov     eax, [ebp+0x28]
    dec     eax
    sub     eax, ebx
    cmp     eax, [ebp-4]
    jae     oc_pop
    push    eax
    mov     eax, [ebp-76]
    cmp     eax, [ebp-84]
    je      oc_cached
    mov     [ebp-84], eax
    movzx   eax, word ptr [0x71666666+eax*2]
    call    {PCAVE2 + OFF_RCLS:#x}
    mov     [ebp-88], eax
oc_cached:
    pop     eax
    cmp     dword ptr [ebp-88], 1
    je      oc_pop
    jb      oc_corner
    cmp     dword ptr [ebp-88], 3
    je      oc_inc
    cmp     eax, [ebp-80]
    jae     oc_pop
    jmp     oc_inc
oc_corner:
    cmp     eax, [ebp-92]
    jae     oc_pop
oc_inc:
    inc     edx
oc_pop:
    pop     eax
oc_ret:
    ret
"""
# t_orn_rowcls (fix 26 v4): called once per blit after the buffer fields, in thunk_bandmap_orn's frame; all registers
# kept.  [ebp-84] = [ebp-96] = -1 (no cached row; the DUP block start not yet scanned); [ebp-80] = E = D + K and
# [ebp-92] = D (laws ornate_popup_line_end / _outer_width: D = the near cells 0..6, counted off the near forward
# table g_bm_fwdx) when armed ([g_orn_mirror]), keyed (key -1 = an opaque blit: all MIRROR) and pinned (b >= 2K),
# else 0.
ASM_ROWCLS = f"""
    pushad
    xor     eax, eax
    mov     [ebp-80], eax
    mov     [ebp-92], eax
    dec     eax
    mov     [ebp-84], eax
    mov     [ebp-96], eax
    cmp     dword ptr [0x73555555], 0
    je      rc_done
    cmp     dword ptr [ebp+0x30], -1
    je      rc_done
    mov     eax, [ebp-12]
    add     eax, eax
    cmp     [ebp-4], eax
    jl      rc_done
    xor     ecx, ecx
    xor     edx, edx
rc_cnt:
    cmp     ecx, [ebp-4]
    jge     rc_cnt_end
    movzx   eax, byte ptr [0x71333333+ecx]
    cmp     eax, {CX_NEAR}
    adc     edx, 0
    inc     ecx
    jmp     rc_cnt
rc_cnt_end:
    mov     [ebp-92], edx
    add     edx, [ebp-12]
    mov     [ebp-80], edx
rc_done:
    popad
    ret
"""
# t_orn_rcls (fix 26 v3/v5, law ornate_popup_row_class): eax = source row y -> eax = its class (0 CORNER, 1 MIRROR,
# 2 DUP, 3 PLAIN -- t_orn_rplain, checked first); every other register kept.  In thunk_bandmap_orn's frame (srcW [ebp+0x18], srcH [ebp+0x1c], key [ebp+0x30],
# rows at [ebp-16] + y * [ebp-20]).  The DUP block start (ornate_popup_dup_start: the first row of the lower half whose
# right columns c_near and c_near + 1 both carry the left line column's colour, not the key) is scanned once into
# [ebp-96].  Above it: t_orn_rpat's mirror pattern, and a pattern row whose neighbour fails the pattern and shares a
# non-key colour with it in one of the right's 8 outer columns (ornate_popup_rows_continue) joins the CORNER.
ASM_RCLS = f"""
    push    ebx
    push    ecx
    push    edx
    push    esi
    push    edi
    mov     ebx, eax
    call    {PCAVE2 + OFF_RPLAIN:#x}
    test    eax, eax
    mov     eax, 3
    jnz     rk_out
    mov     edi, [ebp-96]
    test    edi, edi
    jns     yd_have
    mov     edi, [ebp+0x1c]
    shr     edi, 1
yd_l:
    cmp     edi, [ebp+0x1c]
    jge     yd_set
    mov     eax, edi
    imul    eax, [ebp-20]
    add     eax, [ebp-16]
    movzx   edx, byte ptr [eax+{CX_NEAR}]
    cmp     edx, [ebp+0x30]
    je      yd_n
    add     eax, [ebp+0x18]
    cmp     dl, [eax-{CX_NEAR + 1}]
    jne     yd_n
    cmp     dl, [eax-{CX_NEAR + 2}]
    je      yd_set
yd_n:
    inc     edi
    jmp     yd_l
yd_set:
    mov     [ebp-96], edi
yd_have:
    mov     eax, 2
    cmp     ebx, edi
    jge     rk_out
    mov     eax, ebx
    call    {PCAVE2 + OFF_RPAT:#x}
    test    eax, eax
    jz      rk_out
    lea     edi, [ebx-1]
    call    {PCAVE2 + OFF_RNB:#x}
    jnz     rk_corner
    lea     edi, [ebx+1]
    call    {PCAVE2 + OFF_RNB:#x}
    jnz     rk_corner
    mov     eax, 1
    jmp     rk_out
rk_corner:
    xor     eax, eax
rk_out:
    pop     edi
    pop     esi
    pop     edx
    pop     ecx
    pop     ebx
    ret
"""
# t_orn_rnb (fix 26 v3, t_orn_rcls's neighbour test): edi = neighbour row n, ebx = row y -> eax != 0 (ZF clear) iff
# 0 <= n < the DUP block start, n fails t_orn_rpat, and the two rows share a non-key colour in one of the right's 8
# outer columns (ornate_popup_rows_continue); ecx, edx, esi clobbered.
ASM_RNB = f"""
    xor     eax, eax
    test    edi, edi
    js      nb_r
    cmp     edi, [ebp-96]
    jge     nb_r
    mov     eax, edi
    call    {PCAVE2 + OFF_RPAT:#x}
    test    eax, eax
    jnz     nb_r0
    mov     edx, edi
    imul    edx, [ebp-20]
    add     edx, [ebp-16]
    add     edx, [ebp+0x18]
    mov     eax, ebx
    imul    eax, [ebp-20]
    add     eax, [ebp-16]
    add     eax, [ebp+0x18]
    mov     esi, {SL.ORNATE_POPUP_OUTER_CELLS}
nb_l:
    dec     eax
    dec     edx
    movzx   ecx, byte ptr [eax]
    cmp     cl, [edx]
    jne     nb_x
    cmp     ecx, [ebp+0x30]
    jne     nb_r
nb_x:
    dec     esi
    jnz     nb_l
nb_r0:
    xor     eax, eax
nb_r:
    test    eax, eax
    ret
"""
# t_orn_rplain (fix 26 v5, audit26c N1, law ornate_popup_row_plain): eax = source row y -> eax = 1 iff both line
# columns (c_near from the left, c_near + 1 from the right) are the key and the two outer key runs are equal (keyed
# blits only: the key is a palette index, compared as a byte); ecx, edx, esi clobbered, ebx / edi kept.
ASM_RPLAIN = f"""
    push    edi
    push    ebx
    imul    eax, [ebp-20]
    add     eax, [ebp-16]
    mov     esi, [ebp+0x18]
    mov     ebx, [ebp+0x30]
    cmp     byte ptr [eax+{CX_NEAR}], bl
    jne     rq_no
    cmp     byte ptr [eax+esi-{CX_NEAR + 2}], bl
    jne     rq_no
    xor     edx, edx
rq_l:
    cmp     edx, esi
    jge     rq_le
    cmp     byte ptr [eax+edx], bl
    jne     rq_le
    inc     edx
    jmp     rq_l
rq_le:
    lea     edi, [eax+esi-1]
    xor     eax, eax
rq_r:
    cmp     eax, esi
    jge     rq_re
    cmp     byte ptr [edi], bl
    jne     rq_re
    inc     eax
    dec     edi
    jmp     rq_r
rq_re:
    cmp     eax, edx
    sete    al
    movzx   eax, al
    jmp     rq_out
rq_no:
    xor     eax, eax
rq_out:
    pop     ebx
    pop     edi
    ret
"""
# t_orn_rpat (fix 26 v3, law ornate_popup_row_mirrors): eax = source row y -> eax = 1 iff its last column is the key
# and its 8 columns before that repeat the first 8's key / line-colour pattern (line = row[c_near]); ecx, edx, esi
# clobbered, ebx / edi kept.
ASM_RPAT = f"""
    push    edi
    push    ebx
    imul    eax, [ebp-20]
    add     eax, [ebp-16]
    mov     esi, [ebp+0x18]
    lea     esi, [eax+esi-1]
    movzx   ecx, byte ptr [esi]
    cmp     ecx, [ebp+0x30]
    jne     rp_no
    movzx   edx, byte ptr [eax+{CX_NEAR}]
    mov     ebx, {CX_NEAR + 1}
rp_l:
    movzx   ecx, byte ptr [eax]
    cmp     ecx, [ebp+0x30]
    sete    ch
    cmp     cl, dl
    sete    cl
    mov     edi, ecx
    dec     esi
    movzx   ecx, byte ptr [esi]
    cmp     ecx, [ebp+0x30]
    sete    ch
    cmp     cl, dl
    sete    cl
    cmp     ecx, edi
    jne     rp_no
    inc     eax
    dec     ebx
    jnz     rp_l
    mov     eax, 1
    jmp     rp_r
rp_no:
    xor     eax, eax
rp_r:
    pop     ebx
    pop     edi
    ret
"""


# t_orn_cfpost (fix 26 v2, law popup_content_frame_right): thunk_content_frame's tail target (was
# thunk_pf_union_align): an ornate 2/6 popup's OUTER-UNION ring that the content frame left at exactly box_w - L is
# pulled in by one px onto the half-open axis; everything else passes straight through.  [esp+4] = &rect.
ASM_CFPOST = """
    cmp     dword ptr [0x71777777], 16
    jle     cf_out
    push    eax
    mov     eax, [esi+0x30ac]
    sub     eax, 20000
    cmp     eax, 10000
    jb      cf_orn
    sub     eax, 40000
    cmp     eax, 10000
    jae     cf_pop
cf_orn:
    push    edx
    mov     eax, [esp+0xc]
    mov     edx, [esi+0x30bc]
    sub     edx, [eax]
    cmp     edx, [eax+8]
    jne     cf_keep
    dec     dword ptr [eax+8]
cf_keep:
    pop     edx
cf_pop:
    pop     eax
cf_out:
    push    0x73666666
    ret
"""


ASM_SEL = f"""
    cmp     dword ptr [0x71111111], {NX}
    jne     sel_old
    cmp     dword ptr [0x71222222], {NY}
    jne     sel_old
    push    0x73444444
    ret
sel_old:
    push    0x73333333
    ret
"""


# t_orn_bd_arm (fix 26): thunk_backdrop_railtrim's tail jumps here instead of thunk_tutwin_backdrop, i.e. ONLY the
# Popup_on_draw_background backdrop call @0x405F77 (Buffer_box_sprite thiscall, 2 args, ret 8; ecx/eax pass through).
# The flag is read by thunk_bandmap_orn's x call (skip), so only an ornate band map drawn inside this call mirrors.
ASM_ARM = f"""
    mov     dword ptr [0x73555555], 1
    push    dword ptr [esp+8]
    push    dword ptr [esp+8]
    call    {TUTWIN_BACKDROP:#x}
    mov     dword ptr [0x73555555], 0
    ret     8
"""
# t_orn_rmargin (fix 26, law scaling_laws.ornate_popup_margin_r): CALL-redirect over Popup_calc's
# `mov dword [esi+0x21b4], 21` @0x404E19 (10 B -> E8 + 5 NOP; EFLAGS dead: 0x404E3F `cmp edi, 6` redefines them).
ASM_RMARGIN = f"""
    mov     dword ptr [esi+0x21b4], {SL.ornate_popup_margin_r(SL.NATIVE_G)}
    cmp     dword ptr [0x71777777], {SL.NATIVE_G}
    jle     rm_done
    mov     dword ptr [esi+0x21b4], {SL.ornate_popup_margin_r(SL.NATIVE_G + 1)}
rm_done:
    ret
"""
# rel32 operands to template by hand (keystone encodes them against the real VA): name -> [(byte pos, symbol)].
# thunk_bandmap_orn's calls into t_orn_oc / t_orn_rowcls are found by disassembling the blob (build()).
REL32 = {"t_orn_bd_arm": [(19, "thunk_tutwin_backdrop")]}
EXT_CALLS = {PCAVE2 + OFF_OC: "t_orn_oc", PCAVE2 + OFF_ROWCLS: "t_orn_rowcls", PCAVE2 + OFF_RCLS: "t_orn_rcls",
             PCAVE2 + OFF_RPAT: "t_orn_rpat", PCAVE2 + OFF_RNB: "t_orn_rnb", PCAVE2 + OFF_RPLAIN: "t_orn_rplain"}


def _ext_calls(blob: bytes, va: int) -> list:
    """(byte pos of the rel32, symbol) of every `call` in blob that leaves it for EXT_CALLS (capstone, linear: the
    blob is code only)."""
    from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    out, end = [], va + len(blob)
    for ins in Cs(CS_ARCH_X86, CS_MODE_32).disasm(blob, va):
        if ins.mnemonic == "call" and ins.bytes[0] == 0xE8:
            tgt = int(ins.op_str, 16)
            if not va <= tgt < end:
                assert tgt in EXT_CALLS, f"unexpected external call {tgt:#x} @{ins.address:#x}"
                out.append((ins.address - va + 1, EXT_CALLS[tgt]))
    return out


def build() -> dict[str, tuple[int, bytes]]:
    ks = Ks(KS_ARCH_X86, KS_MODE_32)
    out = {}
    for name, off, asm in (("thunk_bandmap_sel", OFF_SEL, ASM_SEL), ("thunk_bandmap_orn", OFF_ORN, derive()),
                           ("t_orn_bd_arm", OFF_ARM, ASM_ARM), ("t_orn_rmargin", OFF_RMARGIN, ASM_RMARGIN),
                           ("t_orn_oc", OFF_OC, ASM_OC), ("t_orn_cfpost", OFF_CFPOST, ASM_CFPOST),
                           ("t_orn_rowcls", OFF_ROWCLS, ASM_ROWCLS),
                           ("t_orn_rcls", OFF_RCLS, ASM_RCLS), ("t_orn_rpat", OFF_RPAT, ASM_RPAT),
                           ("t_orn_rnb", OFF_RNB, ASM_RNB), ("t_orn_rplain", OFF_RPLAIN, ASM_RPLAIN)):
        enc, _ = ks.asm(asm, PCAVE2 + off)
        out[name] = (off, bytes(enc))
    assert OFF_SEL + len(out["thunk_bandmap_sel"][1]) <= OFF_ORN
    assert OFF_ORN + len(out["thunk_bandmap_orn"][1]) <= LIMIT_OFF
    assert OFF_ARM + len(out["t_orn_bd_arm"][1]) <= OFF_MIRROR and OFF_MIRROR + 4 <= 0x1660
    assert OFF_RMARGIN + len(out["t_orn_rmargin"][1]) <= 0x2F00
    assert OFF_OC + len(out["t_orn_oc"][1]) <= 0x2E000
    assert OFF_CFPOST + len(out["t_orn_cfpost"][1]) <= 0x2EA00
    assert OFF_ROWCLS + len(out["t_orn_rowcls"][1]) <= 0x2000
    assert OFF_RCLS + len(out["t_orn_rcls"][1]) <= 0x5600
    assert OFF_RPAT + len(out["t_orn_rpat"][1]) <= 0x29EB0
    assert OFF_RNB + len(out["t_orn_rnb"][1]) <= 0x25E0
    assert OFF_RPLAIN + len(out["t_orn_rplain"][1]) <= 0xEC0
    arm = out["t_orn_bd_arm"][1]
    assert arm[18] == 0xE8 and int.from_bytes(arm[19:23], "little", signed=True) == TUTWIN_BACKDROP - (PCAVE2 + OFF_ARM + 23)
    calls = _ext_calls(out["thunk_bandmap_orn"][1], PCAVE2 + OFF_ORN)
    assert sorted({s for _p, s in calls}) == ["t_orn_oc", "t_orn_rowcls"] and len(calls) == 5, calls
    REL32["thunk_bandmap_orn"] = calls
    for name, want in (("t_orn_oc", ["t_orn_rcls"]), ("t_orn_rcls", ["t_orn_rplain", "t_orn_rpat", "t_orn_rnb", "t_orn_rnb"]),
                       ("t_orn_rnb", ["t_orn_rpat"])):
        c = _ext_calls(out[name][1], PCAVE2 + out[name][0])
        assert [s for _p, s in c] == want, (name, c)
        REL32[name] = c
    return out


REAL = {0x73111111: PCAVE2 + OFF_FARX, 0x73222222: PCAVE2 + OFF_FARY, 0x73333333: OLD_BLIT, 0x73444444: PCAVE2 + OFF_ORN,
        0x73555555: PCAVE2 + OFF_MIRROR, 0x73666666: UNION_ALIGN}


def templ(b: bytes, name: str = "") -> str:
    hx = [f"{x:02X}" for x in b]
    for pos, sym in sorted(REL32.get(name, ()), reverse=True):
        hx[pos:pos + 4] = ["{rel32:%s}" % sym]
    hexs = " ".join(hx)
    for val, ph in SENT.items():
        hexs = hexs.replace(" ".join(f"{x:02X}" for x in val.to_bytes(4, "little")), ph)
    return hexs


GROUP = "frame_bandmap_ornate"
M_SYM = (f"  # ==== {GROUP} symbols (2026-09-19, src assemble_bandmap_ornate.py) ====\n", f"# ==== {GROUP} END ==== symbols\n")
M_CAVE = (f"      # ==== {GROUP} cave (src assemble_bandmap_ornate.py; laws scaling_laws.axis_map_chrome / ornate_outer_key) ====\n", f"# ==== {GROUP} END ==== cave\n")
ENLARGE_OLD = "E8 {rel32:thunk_bandmap_blit} E8 {rel32:thunk_fe"
ENLARGE_NEW = "E8 {rel32:thunk_bandmap_sel} E8 {rel32:thunk_fe"


def main() -> int:
    out = build()
    for n, (o, b) in out.items():
        print(f"OK  {n:18s} @0x{o:05X} len={len(b):5d} end 0x{o + len(b):05X}")
    if "--splice" not in sys.argv:
        return 0
    sym = M_SYM[0]
    sym += f"  g_bmo_farx:                    {{ cave: pcave2, offset: {OFF_FARX:#07x}, size: 256 }}   # far-band forward table X (u8; the ornate far band is NOT a mirror); fix 26 v2: then the squeeze table q[jj] (t_orn_rowcls)\n"
    sym += f"  g_bmo_fary:                    {{ cave: pcave2, offset: {OFF_FARY:#07x}, size: 256 }}\n"
    sym += f"  g_orn_mirror:                  {{ cave: pcave2, offset: {OFF_MIRROR:#07x}, size: 4 }}   # fix 26: 1 only inside t_orn_bd_arm\n"
    for n, (o, b) in out.items():
        sym += f"  {n}:{' ' * max(1, 29 - len(n))}{{ cave: pcave2, offset: {o:#07x} }}   # {GROUP} ({len(b)}B)\n"
    sym += M_SYM[1]
    cave = M_CAVE[0]
    cave += ("      # thunk_frame_enlarge's one `E8 thunk_bandmap_blit` is retargeted to thunk_bandmap_sel (in place, same length):\n"
             "      # corner canvas 61x44 (the ornate def &0x6846B0) -> thunk_bandmap_orn, everything else -> the UNCHANGED\n"
             "      # thunk_bandmap_blit.  orn = that thunk's own source + per-side stroke cell (x 7/8, y 7/5) + outer-key re-key.\n")
    for n, (o, b) in out.items():
        cave += f"      - id: {n}\n        offset: {o:#07x}\n        bytes: \"{templ(b, n)}\"\n"
    cave += M_CAVE[1]
    y = pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml"
    data = y.read_bytes()
    nl = b"\r\n" if b"\r\n" in data[:4096] else b"\n"

    def put_block(data, block, markers, anchor):
        blk = block.replace("\n", nl.decode()).encode("utf-8")
        a, z = markers[0].strip("\n").encode(), markers[1].strip("\n").encode()
        if a in data:
            s = data.index(a)
            s = data.rfind(nl, 0, s) + len(nl)
            e = data.index(z, s) + len(z)
            if data[e:e + len(nl)] == nl:
                e += len(nl)
            assert 0 < s < e
            return data[:s] + blk + data[e:]
        anc = anchor.encode()
        assert data.count(anc) == 1, anchor
        p = data.index(anc) + len(anc)
        p = data.index(nl, p) + len(nl)
        return data[:p] + blk + data[p:]

    data = put_block(data, sym, M_SYM, "# ==== ntw_scale END ==== symbols")
    data = put_block(data, cave, M_CAVE, "# ==== ntw_scale END ==== cave")
    old, new = ENLARGE_OLD.encode(), ENLARGE_NEW.encode()
    if new not in data:
        assert data.count(old) == 1, "thunk_frame_enlarge's bandmap call not found exactly once"
        data = data.replace(old, new)
    y.write_bytes(data)
    print("spliced into", y)
    return 0


if __name__ == "__main__":
    sys.exit(main())
