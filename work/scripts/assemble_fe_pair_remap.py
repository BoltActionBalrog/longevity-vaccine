"""Assemble thunk_fe_pair_remap v2 (generalizes thunk_fe_dither_remap) with keystone.

The popup 9-slice frame ART carries 1px scanline dither BAKED IN. thunk_frame_enlarge's NN blit
beats it into irregular 1,2,1,2 runs at fractional g (refs\\MangledSmacx.png, Customize Game Rules
@1920x1080) — in EVERY menu, but the old remap only fired for the file dialog (g_filedlg_active
gate) and only knew the navy pair.

v2 EVIDENCE-DRIVEN DESIGN (frida_dither_map.log 2026-07-03): idx 0x41 (black) is AMBIGUOUS — it
partners 0xC4 in the navy title/field dither, but ALSO 0xC6 in the d690 near-black backdrop pair,
0x54 under the ornate game-start frame, and appears as the SOLID interior pre-fill of
thunk_box_thick title outers (vrun=22). Blanket-remapping it would navy-stripe backdrops and the
title ring. So:
  - NAVY family (0x41/0xC4): remapped ONLY when the enlarged SOURCE is a genuine navy field —
    pre-scan the small src's first 8 rows; enable iff #C4 > srcW/2 (title d618 / d528 field /
    filedlg inner+title are ~50%% C4 -> ON; backdrops/rings have ~0 C4 -> OFF, stay faithful).
  - BLUE row bars (0xE0/0xE1) and TEAL/PURPLE bars (0xAE/0xEE): unambiguous pairs (log: only ever
    1px-alternating), remapped unconditionally.
Stripe law (skill scaling-frames §7, same phase as thunk_ensure_stripes): P = scaling_laws.stripe_period(g)
(the live thunk reads the cell g_stripe_period), hN=(P+1)>>1, top colour (0xC4/0xE0/0xAE) while
(y mod P) < hN, else 0x41/0xE1/0xEE. Phase anchored at the OWNING buffer's origin so all layers in
one buffer fuse. HISTORICAL SOURCE: this v2 text still emits the RETIRED period (g+4)>>3 below; the
live thunk_fe_pair_remap (v8) is assembled by assemble_devfill_stripes.py -- never bake from here.

Inputs (stashed by thunk_frame_enlarge pre-blit): g_fe_dst/x/y/w/h + NEW g_fe_src. Row colours:
dl=navy, dh=blue (one flags-preserving `mov dx,imm16`), teal in g_rm_col (reused). Navy enable in
g_rm_navy. Plain CALL helper; preserves ebx/esi/edi/ebp, clobbers eax/ecx/edx. No engine calls.
Buffer fields: data +0x54, stride +0x4a8, W +0x80, H +0x84 (NEGATIVE).
Emits yaml-ready hex with {abs32:...} placeholders to work\\patches\\fe_pair_remap_hex.txt.

RETIRED (2026-10-10): this emits v2; the shipped thunk_fe_pair_remap is v7 @pcave2+0x10000, owned
by scripts\\assemble_devfill_stripes.py (pinned to patches.yaml by tests\\test_stale_sources.py).
Kept as history only; running it exits non-zero so it can never regenerate stale bytes.
"""
import sys
sys.exit("assemble_fe_pair_remap.py is SUPERSEDED by assemble_devfill_stripes.py "
         "(thunk_fe_pair_remap v7); it emits the retired v2 and must not be run.")
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

PCAVE2_VA = 0x00A0C000
THUNK_OFF = 0x3860
THUNK_VA  = PCAVE2_VA + THUNK_OFF

SYMS = {
    "g_fe_dst":          PCAVE2_VA + 0x2FA0,
    "g_fe_x":            PCAVE2_VA + 0x2FA4,
    "g_fe_y":            PCAVE2_VA + 0x2FA8,
    "g_fe_w":            PCAVE2_VA + 0x2FAC,
    "g_fe_h":            PCAVE2_VA + 0x2FB0,
    "g_rm_xend":         PCAVE2_VA + 0x2FB4,
    "g_rm_yend":         PCAVE2_VA + 0x2FB8,
    "g_rm_hn":           PCAVE2_VA + 0x2FBC,
    "g_rm_col":          PCAVE2_VA + 0x2FC0,   # reused: per-row teal/purple colour byte
    "g_fe_src":          PCAVE2_VA + 0x2FC4,   # NEW: src small-buffer ptr (stashed by frame_enlarge)
    "g_rm_navy":         PCAVE2_VA + 0x2FC8,   # NEW: navy-family enable (per-blit, from src pre-scan)
    "g_rm_povr":         PCAVE2_VA + 0x2FCC,   # NEW: one-shot P override (self-clearing; 2 = 1px parity
                                               #      law for the faction-button states). NOTE: only set
                                               #      when g>16 is guaranteed — the g<=16 early-ret does
                                               #      NOT consume it (btn_stripes runs under g_btn_pending
                                               #      which implies g>16).
    "g_popup_scale_num": 0x00668740,
}

ASM = r"""
    cmp     dword ptr [{g_popup_scale_num}], 0x10
    jle     ret0
    push    ebx
    push    esi
    push    edi
    push    ebp
    ; ---- pre-scan: navy family enabled iff the SRC is a genuine C4/41 field ----
    mov     byte ptr [{g_rm_navy}], 0
    mov     eax, [{g_fe_src}]
    test    eax, eax
    jz      prescan_done
    mov     esi, [eax+0x54]           ; src data
    test    esi, esi
    jz      prescan_done
    mov     ecx, [eax+0x84]
    neg     ecx                       ; srcH (stored negative)
    jle     prescan_done
    cmp     ecx, 8
    jle     hok
    mov     ecx, 8                    ; scan at most 8 rows
hok:
    mov     edi, [eax+0x80]           ; srcW
    test    edi, edi
    jle     prescan_done
    mov     edx, [eax+0x4a8]          ; src stride
    xor     ebx, ebx                  ; C4 count
rowl:
    dec     ecx
    js      rows_done
    mov     ebp, esi                  ; row ptr
    push    ecx
    mov     ecx, edi                  ; x countdown
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
    shr     eax, 1                    ; threshold: srcW/2
    cmp     ebx, eax
    jle     prescan_done
    mov     byte ptr [{g_rm_navy}], 1
prescan_done:
    ; ---- clamps (dest walk bounds) ----
    mov     esi, [{g_fe_dst}]
    mov     eax, [esi+0x80]
    mov     ecx, [esi+0x84]
    neg     ecx                       ; destH (stored negative)
    mov     edx, [{g_fe_x}]
    add     edx, [{g_fe_w}]
    cmp     edx, eax
    jle     xok
    mov     edx, eax
xok:
    mov     [{g_rm_xend}], edx
    mov     edx, [{g_fe_y}]
    add     edx, [{g_fe_h}]
    cmp     edx, ecx
    jle     yok
    mov     edx, ecx
yok:
    mov     [{g_rm_yend}], edx
    ; P = override (one-shot, self-clearing) else the RETIRED (g+4)>>3 (live v8: [g_stripe_period]) -> ebx ; hN = (P+1)>>1 -> g_rm_hn
    mov     eax, [{g_rm_povr}]
    test    eax, eax
    jz      natp
    mov     dword ptr [{g_rm_povr}], 0
    jmp     havep
natp:
    mov     eax, [{g_popup_scale_num}]
    add     eax, 4
    shr     eax, 3
havep:
    mov     ebx, eax
    lea     ecx, [eax+1]
    shr     ecx, 1
    mov     [{g_rm_hn}], ecx
    ; y = max(g_fe_y, 0) -> edi
    mov     edi, [{g_fe_y}]
    test    edi, edi
    jge     yloop
    xor     edi, edi
yloop:
    cmp     edi, [{g_rm_yend}]
    jge     done
    ; row colours: dl=navy (0xC4 top / 0x41), dh=blue (0xE0 top / 0xE1), g_rm_col=teal (0xAE top / 0xEE)
    mov     eax, edi
    xor     edx, edx
    div     ebx                       ; edx = y mod P
    cmp     edx, [{g_rm_hn}]
    mov     dx, 0xE0C4                ; imm16 mov preserves flags
    jl      top_cols
    mov     dx, 0xE141
    mov     byte ptr [{g_rm_col}], 0xEE
    jmp     colsok
top_cols:
    mov     byte ptr [{g_rm_col}], 0xAE
colsok:
    ; pixel ptr = destData + y*stride + max(g_fe_x,0) -> ebp ; x -> ecx
    mov     eax, [esi+0x4a8]
    imul    eax, edi
    add     eax, [esi+0x54]
    mov     ecx, [{g_fe_x}]
    test    ecx, ecx
    jge     xstart
    xor     ecx, ecx
xstart:
    lea     ebp, [eax+ecx]
xloop:
    cmp     ecx, [{g_rm_xend}]
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
    je      chk_navy
    cmp     al, 0xC4
    jne     skip
chk_navy:
    cmp     byte ptr [{g_rm_navy}], 0
    je      skip
    mov     [ebp], dl
    jmp     skip
wr_teal:
    mov     al, [{g_rm_col}]
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
"""


def main():
    out = open(r"D:\SmacxUi\work\patches\fe_pair_remap_hex.txt", "w")
    def w(s): out.write(s + "\n"); out.flush()
    try:
        ks = Ks(KS_ARCH_X86, KS_MODE_32)
        asm = ASM
        for name, va in SYMS.items():
            asm = asm.replace("{%s}" % name, "0x%08X" % va)
        clean = "\n".join(ln.split(";", 1)[0].rstrip() for ln in asm.splitlines() if ln.split(";", 1)[0].strip())
        enc, count = ks.asm(clean, THUNK_VA)
        raw = bytes(enc)
        # substitute {abs32:name} placeholders back over the literal address dwords
        hexstr = raw.hex().upper()
        for name, va in SYMS.items():
            le = va.to_bytes(4, "little").hex().upper()
            hexstr = hexstr.replace(le, "!" + name + "!")
        toks, i = [], 0
        while i < len(hexstr):
            if hexstr[i] == "!":
                j = hexstr.index("!", i + 1)
                toks.append("{abs32:" + hexstr[i + 1:j] + "}")
                i = j + 1
            else:
                toks.append(hexstr[i:i + 2]); i += 2
        nbytes = sum(4 if t.startswith("{") else 1 for t in toks)
        assert nbytes == len(raw), f"placeholder substitution corrupted byte count ({nbytes} != {len(raw)})"
        w(f"; thunk_fe_pair_remap v2 @ VA 0x{THUNK_VA:X} (pcave2 +0x{THUNK_OFF:X})")
        w(f"; {len(raw)} bytes, {count} statements; ends at pcave2 +0x{THUNK_OFF + len(raw):X}")
        w(" ".join(toks))
    except Exception as e:
        w(f"; ERROR: {type(e).__name__}: {e}"); out.close(); raise
    out.close(); return 0


if __name__ == "__main__":
    sys.exit(main())
