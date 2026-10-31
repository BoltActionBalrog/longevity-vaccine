"""Assemble the hud_widgets_scale group — the FULL v35 Frida lever set baked (2026-07-06).

Port of hook_hudframes45.js's active levers (user-verified at 4K across v8..v44):
  A/F  thunk_hud_fontobj    Font_init 0x618F40 entry detour: gate ecx in {3 StatusWin fonts,
                            label font 0x7AFD50, InfoWin ticker font 0x7AD2F8}, height<=16
                            native -> x g/16. Covers all 30 StatusWin re-init triples + the
                            ticker + label site with ONE patch (object-gated like the lever).
  B    thunk_hud_fcache     call-redirect @0x559DE5 (FontCache_get): veh_draw HUD-buf callers
                            get mul g/64 instead of 1/4 (caller ebp intact -> [ebp+8]=buf).
  C'   thunk_hud_vehargs    veh_draw 0x5594F0 entry detour (6B displaced): HUD-buf calls get
       thunk_hud_baseargs   size arg s'=(s+16)g/16-16 (gate -16<=s<=16) + the +11 unit-row
                            x-inset scaled via ret-key {0x4b84fd,0x4b8350}; base_draw twin (9B).
  E/G/H thunk_hud_slotw/titley/cellw  the three fallback `mov reg,imm` sites become thunk
                            calls computing the g-scaled value (all identity at g=16).
  N    thunk_hud_n01..n16   content-anchor joins: pushfd-safe register adjusts + displaced
                            original instructions + resume (n06 is a call-site tail-jmp; n11
                            ends in the displaced jmp).
  J    thunk_hud_boxframe   Buffer_box_sprite 0x5E2DD3 entry detour: HUD dests (strip/status
                            bufs) route to thunk_box_thick_hollow_flat with the g_fc_exact +
                            FC_RECT staging; 14-entry native-rect table (drifting inners/box5/
                            box9 get floor(native*g/16) per edge); internal small-render
                            re-enters with g_frame_buf dest -> native tail, no recursion.
  K    thunk_hud_cellring   call-redirect @0x4B8764 (box6 selected-cell Buffer_box_2): draw +
                            ceil(g/16)-1 concentric inset rings.
  W    thunk_btn_gate v4    RELOCATED+extended: 7 HUD FlatButtons (M/I/TOOLBAR/MENU/COMMLINK/
                            WORLD/DETAIL statics, checked via ESI at the shrink's pushad'd
                            call) answer YES unconditionally -> the baked shrink/2dscale
                            bracket composes native + stretches. No flag choreography (the
                            Frida g_popup_active arming + early-disarm dance was an artifact
                            of not being able to touch the gate).
  V    thunk_btn_fillcap v2 RELOCATED+extended: skip the bar-dither capture for the 4
                            sprite-content buttons (MENU/COMMLINK/WORLD/DETAIL) -> devfill
                            no-ops, the stretched state sprite survives (v29/v30 flood fix).
  R    thunk_hud_btnfont    0x607E50 entry detour: M/I button buffers get fA12 before draw.
NOT baked: X (proven inert v19), Z (proven no-op v22), Q (subsumed by W).
"""
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

P = 0x00A0C000
G_ = 0x668740            # g_popup_scale_num
ENSURE = 0x668760        # thunk_ensure_scale
HUD1, HUD2 = 0x7AEC64, 0x8C59AC

L = {}                   # name -> (offset, budget, asm)

def T(name, off, budget, asm):
    L[name] = (off, budget, asm)

# ---------- A/F ----------
T("thunk_hud_fontobj", 0x5000, 0x60, f"""
    cmp ecx, 0x8C6A98
    je m
    cmp ecx, 0x8C6AC0
    je m
    cmp ecx, 0x8C6AE8
    je m
    cmp ecx, 0x7AFD50
    je m
    cmp ecx, 0x7AD2F8
    jne out
m:  push ecx
    call {ENSURE:#x}
    pop ecx
    mov eax, dword ptr [{G_:#x}]
    cmp eax, 16
    jle out
    mov edx, dword ptr [esp+0xC]
    cmp edx, 16
    jg out
    imul edx, eax
    sar edx, 4
    mov dword ptr [esp+0xC], edx
out: add esp, 4
    sub esp, 0x74
    push ebx
    push esi
    push 0x618F45
    ret
""")

# ---------- B ----------
T("thunk_hud_fcache", 0x5060, 0x50, f"""
    mov eax, dword ptr [ebp+8]
    cmp eax, {HUD1:#x}
    je m
    cmp eax, {HUD2:#x}
    jne out
m:  cmp dword ptr [esp+4], 0
    jg out
    cmp dword ptr [esp+8], 1
    jne out
    cmp dword ptr [esp+0xC], 4
    jne out
    mov eax, dword ptr [{G_:#x}]
    cmp eax, 16
    jle out
    mov dword ptr [esp+8], eax
    mov dword ptr [esp+0xC], 64
out: push 0x5592D0
    ret
""")

# ---------- C' (veh_draw / base_draw) ----------
# The BASE LOCATOR minimap's base pass draws into the WorldWin's embedded Console's canvas: MapWin_draw_base_tile computes
# dest = console + [[console]+4] + 0x444 (0x467283..0x46728F) -- the Console's first dword is its VIRTUAL-BASE TABLE pointer
# (Console_ctor @0x50F49A stores 0x66EF04 = [0, 0x23D94]: the displacement of its virtual GraphicWin base), and inside the
# WorldWin that table can differ (the virtual base may be WorldWin's own window).  v2 (console+0x444 = 0x8EB8D0) and v2a
# (0x90F664, the standalone displacement) both failed on the user's shots, so v3 COMPUTES the canvas at run time exactly
# like the engine: [[WORLDWIN_CONSOLE]+4] + WORLDWIN_CONSOLE + 0x444.
WORLDWIN_CONSOLE = 0x8EB48C   # WorldWin 0x8E9F60 + 0x152C


def vehbody(sub, resume, pin_box=False):
    """Entry detour body shared by veh_draw/base_draw.  pin_box (base_draw only, 2026-09-12): when the
    dest buffer is the WorldWin minimap console's canvas (computed at run time like MapWin_draw_base_tile
    does: console + [[console]+4] + 0x444), the flags arg becomes exactly 0x100 = the pristine minimap's
    box path: bit 8 is base_draw's `test ah,1` box override on the `size >= threshold` branch (PRACX
    rewrites the -8 threshold imm at 0x55AF62 to -14 from its ZoomedOutShowDetails setting -> the icon
    path on patched installs), bits 3/11 (icon-path exits at 0x55AF6E/0x55AF76) and bit 9 (the box
    path's slanted-rect variant at 0x55AFE5) clear.  Nothing else changes."""
    pin = f"""
    mov eax, dword ptr [{WORLDWIN_CONSOLE:#x}]
    mov eax, dword ptr [eax+4]
    add eax, {WORLDWIN_CONSOLE + 0x444:#x}
    cmp dword ptr [esp+8], eax
    jne nb
    mov dword ptr [esp+0x1C], 0x100
nb:""" if pin_box else ""
    return f"""{pin}
    mov eax, dword ptr [esp+8]
    cmp eax, {HUD1:#x}
    je m
    cmp eax, {HUD2:#x}
    jne out
m:  mov eax, dword ptr [{G_:#x}]
    cmp eax, 16
    jle out
    mov edx, dword ptr [esp+4]
    cmp edx, 0x4b84fd
    je xa
    cmp edx, 0x4b8350
    jne sf
xa: imul edx, eax, 11
    sar edx, 4
    sub edx, 11
    add dword ptr [esp+0x10], edx
sf: mov edx, dword ptr [esp+0x18]
    cmp edx, 16
    jg out
    cmp edx, -16
    jl out
    add edx, 16
    imul edx, eax
    sar edx, 4
    sub edx, 16
    mov dword ptr [esp+0x18], edx
out: add esp, 4
    push ebp
    mov ebp, esp
    sub esp, {sub:#x}
    push {resume:#x}
    ret
"""
T("thunk_hud_vehargs",  0x50B0, 0x80, vehbody(0x2C, 0x5594F6))
T("thunk_hud_baseargs", 0x13D20, 0x100, vehbody(0x118, 0x55AF29, pin_box=True))   # v3: minimap box-style pin (runtime canvas); RELOCATED 0x5130 -> 0x13D20 (free after thunk_s54_restripe v2 ends 0x13D04, cave_map --at)

# ---------- E/G/H ----------
T("thunk_hud_slotw", 0x51B0, 0x10, f"""
    mov edx, dword ptr [{G_:#x}]
    imul edx, edx, 75
    sar edx, 4
    ret
""")
T("thunk_hud_titley", 0x51C0, 0x10, f"""
    mov eax, dword ptr [{G_:#x}]
    shl eax, 2
    sub eax, 8
    ret
""")
T("thunk_hud_cellw", 0x51D0, 0x10, f"""
    mov eax, dword ptr [{G_:#x}]
    imul eax, eax, 61
    sar eax, 4
    sub eax, 11
    ret
""")

# ---------- N joins ----------
# helpers emitted inline per thunk; D(n) = floor(n*g/16)-n; esi3: esi==3 -> 3g/16
def adj(scratch, code):
    return f"pushfd\n push {scratch}\n{code}\n pop {scratch}\n popfd\n"

def d_of(scratch, n):
    return f" mov {scratch}, dword ptr [{G_:#x}]\n imul {scratch}, {scratch}, {n}\n sar {scratch}, 4\n sub {scratch}, {n}\n"

def esi3(scratch):
    return (f" cmp esi, 3\n jne k\n mov {scratch}, dword ptr [{G_:#x}]\n"
            f" lea {scratch}, [{scratch}+{scratch}*2]\n sar {scratch}, 4\n mov esi, {scratch}\nk:\n")

NJ = [
 # (name, off, site, patchlen, adjust_asm, displaced_asm, tail)
 ("n01", 0x51E0, 0x4B4D84, 5, adj("eax", esi3("eax")), "push 0x78d7f8",              "push 0x4B4D89\n ret"),
 ("n02", 0x5210, 0x4B6A1F, 5, adj("eax", esi3("eax")), "push 0x78d7f8",              "push 0x4B6A24\n ret"),
 ("n03", 0x5240, 0x4B6B82, 5, adj("eax", d_of("eax",2)+" add esi, eax"), "and eax, 0x7aec64", "push 0x4B6B87\n ret"),
 ("n04", 0x5270, 0x4B6B88, 5, adj("eax", d_of("eax",1)+" add edx, eax"), "push edx\n push esi\n mov esi, dword ptr [ebp+0x14]", "push 0x4B6B8D\n ret"),
 ("n05", 0x52A0, 0x4B6BCB, 6, adj("eax", d_of("eax",3)+" add ebx, eax"), "mov eax, dword ptr [edx+0x15a8]", "push 0x4B6BD1\n ret"),
 ("n06", 0x52D0, 0x4B6BF2, 5, adj("eax", d_of("eax",4)+" sub ebx, eax"), "",          "push 0x5DACB0\n ret"),
 ("n07", 0x5300, 0x4B7F05, 8, adj("eax", d_of("eax",2)+" add ebx, eax"), "je 0x4b7f25\n push edx\n call 0x6453e0", "push 0x4B7F0D\n ret"),
 ("n08", 0x5340, 0x4B8001, 8, adj("eax", d_of("eax",2)+" sub ebx, eax"), "je 0x4b801e\n push edx\n call 0x6453e0", "push 0x4B8009\n ret"),
 ("n09", 0x5380, 0x45BF86, 6, adj("edx", d_of("edx",3)+" add eax, edx\n add ecx, edx"), "mov dword ptr [ebp-0x14], eax\n mov dword ptr [ebp-0x10], ecx", "push 0x45BF8C\n ret"),
 ("n10", 0x53B0, 0x4593A1, 6, adj("esi", d_of("esi",7)+" add ecx, esi\n add edi, esi\n sub eax, esi\n sub ebx, esi\n"
                                        + d_of("esi",32)+" sub eax, esi"), "cmp edx, 0x320", "push 0x4593A7\n ret"),
 ("n11", 0x5400, 0x4593CA, 6, adj("eax", d_of("eax",3)+" add edx, eax"), "add ecx, edx\n add eax, edx", "jmp 0x4593df"),
 ("n12", 0x5430, 0x456395, 6, adj("eax", d_of("eax",5)+" add ebx, eax\n add ecx, eax"), "add ebx, 5\n add ecx, 5", "push 0x45639B\n ret"),
 ("n13", 0x5460, 0x4B80D9, 5, adj("eax", esi3("eax")), "mov eax, dword ptr [ebp-0xc]\n add edx, esi", "push 0x4B80DE\n ret"),
 ("n14", 0x5490, 0x4B8230, 5, adj("edx", d_of("edx",5)+" add edi, edx"), "cdq\n idiv edi\n mov edi, eax", "push 0x4B8235\n ret"),
 ("n15", 0x54C0, 0x4B8295, 8, adj("edx", d_of("edx",5)+" sub eax, edx"), "mov dword ptr [ebp+0x18], eax\n mov eax, dword ptr [0x7b5080]", "push 0x4B829D\n ret"),
 ("n16", 0x5510, 0x4B86E6, 6, adj("ebx", " cmp edx, 27\n jne noadj\n mov ebx, dword ptr [" + hex(G_) + "]\n imul ebx, ebx, 19\n sar ebx, 4\n lea edx, [eax+ebx+1]\nnoadj:\n"),
                               "sub eax, edx\n lea edx, [eax+ecx+1]", "push 0x4B86EC\n ret"),
]
for name, off, site, plen, a, disp, tail in NJ:
    # E8-entered detours MUST consume the pushed return address before the
    # push-resume tail (the LAUNCH-GAME ret-leak law) — EXCEPT n06, whose
    # tail-jmp reaches a real callee whose own RET consumes it.
    consume = "" if name == "n06" else "add esp, 4" + chr(10)
    T("thunk_hud_" + name, off, 0x30 if name not in ("n10",) else 0x50,
      consume + a + (disp + "\n" if disp else "") + tail)

# ---------- J ----------
import scaling_laws as _SL
NAT = [_SL.hud_boxframe_table_row(site) for site in _SL.HUD_BOXFRAME_NAT]   # the law module owns the table (F32:
#   a HUD_BOXFRAME_MIRROR_SITES row carries its x edges negated = "mirror grid"; the split test reads l unsigned)
TABLE_OFF = 0x5600
RECT_OFF  = 0x5720           # g_hud_rect (16B, J scratch)
RECT2_OFF = 0x5730           # g_hud_rect2 (16B, K scratch)
TBL, TBL_END = P + TABLE_OFF, P + TABLE_OFF + 20 * len(NAT)
RECT, RECT2 = P + RECT_OFF, P + RECT2_OFF
FC_RECT, FC_EXACT, HOLLOW_FLAT = 0xA0D010, 0xA0E554, 0xA0C140
SPLIT = _SL.HUD_BOX5_SPLIT_NATIVE   # law hud_boxframe_rect: shared box-5 painters (0x45910D/0x4564A7) reach
P1_ENTRY = TBL + 20 * [e[0] for e in NAT].index(_SL.HUD_BOX5_RIGHT_PANEL_SITE)   # here with EITHER panel's rect

T("thunk_hud_boxframe", 0x5740, 0xE0, f"""
    cmp ecx, {HUD1:#x}
    je h
    cmp ecx, {HUD2:#x}
    je h
nat: add esp, 4
    push ecx
    push ebx
    push ebp
    push esi
    push edi
    push 0x5E2DD8
    ret
h:  mov eax, dword ptr [{G_:#x}]
    cmp eax, 16
    jle nat
    push esi
    push edi
    mov edx, dword ptr [esp+0xC]
    mov esi, {TBL:#x}
lp: cmp dword ptr [esi], edx
    je hit
    add esi, 20
    cmp esi, {TBL_END:#x}
    jb lp
    mov esi, dword ptr [esp+0x10]
    jmp stage
hit: mov edi, dword ptr [esp+0x10]
    mov edi, dword ptr [edi]
    shl edi, 4
    imul edx, eax, {SPLIT}
    cmp edi, edx
    jle sc
    cmp dword ptr [esi+4], {SPLIT}
    ja sc
    mov esi, {P1_ENTRY:#x}
sc: push ecx
    add esi, 4
    mov edi, {RECT:#x}
    mov ecx, 4
l2: mov edx, dword ptr [esi]
    imul edx, eax
    sar edx, 4
    jns l3
    neg edx
    cmp ecx, 2
    jne l3
    dec edx
l3: mov dword ptr [edi], edx
    add esi, 4
    add edi, 4
    loop l2
    pop ecx
    mov esi, {RECT:#x}
stage: push ecx
    push esi
    push edi
    mov edi, {FC_RECT:#x}
    mov ecx, 4
    .byte 0xF3, 0xA5
    pop edi
    pop esi
    pop ecx
    mov dword ptr [{FC_EXACT:#x}], 1
    push dword ptr [esp+0x14]
    push esi
    call {HOLLOW_FLAT:#x}
    mov dword ptr [{FC_EXACT:#x}], 0
    pop edi
    pop esi
    add esp, 4
    ret 8
""")

# ---------- K ----------
T("thunk_hud_cellring", 0x5820, 0x80, f"""
    push ebx
    push esi
    push edi
    push ebp
    mov esi, ecx
    mov ebp, dword ptr [esp+0x14]
    push dword ptr [esp+0x1C]
    push dword ptr [esp+0x1C]
    push ebp
    mov ecx, esi
    call 0x5E3203
    mov eax, dword ptr [{G_:#x}]
    cmp eax, 16
    jle done
    add eax, 15
    sar eax, 4
    mov edi, 1
rl: cmp edi, eax
    jge done
    mov ebx, dword ptr [ebp]
    add ebx, edi
    mov dword ptr [{RECT2:#x}], ebx
    mov ebx, dword ptr [ebp+4]
    add ebx, edi
    mov dword ptr [{RECT2+4:#x}], ebx
    mov ebx, dword ptr [ebp+8]
    sub ebx, edi
    mov dword ptr [{RECT2+8:#x}], ebx
    mov ebx, dword ptr [ebp+12]
    sub ebx, edi
    mov dword ptr [{RECT2+12:#x}], ebx
    push eax
    push dword ptr [esp+0x20]
    push dword ptr [esp+0x20]
    push {RECT2:#x}
    mov ecx, esi
    call 0x5E3203
    pop eax
    inc edi
    jmp rl
done: pop ebp
    pop edi
    pop esi
    pop ebx
    ret 0xC
""")

# ---------- W: gate v4 (relocated) ----------
PA, NW, FA, FD = 0xA0C530, 0xA10800, 0xA0D2D0, 0xA0E3A0
T("thunk_btn_gate_v4", 0x58A0, 0x80, f"""
    cmp esi, 0x7AF620
    je yes
    cmp esi, 0x7B016C
    je yes
    cmp esi, 0x7B0CB8
    je yes
    cmp esi, 0x7B1804
    je yes
    cmp esi, 0x7B2350
    je yes
    cmp esi, 0x7B39E8
    je yes
    cmp esi, 0x7B4534
    je yes
    mov eax, dword ptr [{PA:#x}]
    test eax, eax
    jne yes
    mov eax, dword ptr [{NW:#x}]
    test eax, eax
    jne yes
    mov eax, dword ptr [{FA:#x}]
    test eax, eax
    jne chk
    mov eax, dword ptr [{FD:#x}]
    test eax, eax
    je no
chk: mov eax, dword ptr [esi+0xA7C]
    test eax, eax
    je no
yes: mov eax, 1
    ret
no: xor eax, eax
    ret
""")

# ---------- V: fillcap v2 (relocated) ----------
PEND, FS = 0xA0C534, 0xA0D600
T("thunk_btn_fillcap_v2", 0x5920, 0x70, f"""
    cmp dword ptr [{PEND:#x}], 0
    je pass
    test ebp, ebp
    jne pass
    cmp esi, 0x7B1804
    je pass
    cmp esi, 0x7B2350
    je pass
    cmp esi, 0x7B39E8
    je pass
    cmp esi, 0x7B4534
    je pass
    mov eax, dword ptr [esp+4]
    mov dword ptr [{FS:#x}], eax
    mov eax, dword ptr [esp+0x10]
    mov dword ptr [{FS+4:#x}], eax
    mov eax, dword ptr [esp+0x14]
    mov dword ptr [{FS+8:#x}], eax
    mov eax, dword ptr [esp+0x18]
    mov dword ptr [{FS+0xC:#x}], eax
    mov eax, dword ptr [esp+0x1C]
    mov dword ptr [{FS+0x10:#x}], eax
pass: push 0x5DA9F0
    ret
""")

# ---------- R ----------
# v2 (2026-09-17, audit finding 3.8; probe hook_btnfont_probe.js at 1024x768): the M/I buttons' vanilla
# +0x970 is 0x7CFE8C = Arial 14 BOLD, so the canvas font0 becomes t_fdirect_a14b() (0xA3A590, assemble_fontlaw.py)
# = Arial fl(14g/16) bold on the shared keyed slot -- v1 set fA12 0x7CFEB4 (Arial 12 regular).
T("thunk_hud_btnfont", 0x5990, 0x60, f"""
    cmp ecx, 0x7AF620
    je m
    cmp ecx, 0x7B016C
    jne out
m:  mov eax, dword ptr [{G_:#x}]
    cmp eax, 16
    jle out
    push ecx
    call 0xA3A590
    pop ecx
    push ecx
    push 0
    push 0
    push 0
    push eax
    lea eax, [ecx+0x444]
    mov ecx, eax
    call 0x5DAC70
    pop ecx
out: add esp, 4
    sub esp, 0x14
    push ebx
    push ebp
    push 0x607E55
    ret
""")

ks = Ks(KS_ARCH_X86, KS_MODE_32)
out = {}
for name, (off, budget, asm) in sorted(L.items(), key=lambda kv: kv[1][0]):
    enc, _ = ks.asm(asm, P + off)
    b = bytes(enc)
    status = "OK " if len(b) <= budget else "OVER"
    print(f"{status} {name:26s} @0x{off:04X} len={len(b):3d} budget=0x{budget:02X}")
    assert len(b) <= budget, name
    out[name] = (off, b)

tbl = b""
for e in NAT:
    for v in e:
        tbl += v.to_bytes(4, "little", signed=True)
print(f"OK  g_hud_nat_table            @0x{TABLE_OFF:04X} len={len(tbl)}")
out["g_hud_nat_table"] = (TABLE_OFF, tbl)

print()
for name, (off, b) in sorted(out.items(), key=lambda kv: kv[1][0]):
    print(f"### {name} @ 0x{off:04X}")
    print(" ".join(f"{x:02X}" for x in b))

# ---------------- yaml fragment emission ----------------
SITES = [
    ("Font_init.hud_fontobj",      0x618F40, 5, "83 EC 74 53 56",             "thunk_hud_fontobj",  "sub esp,0x74; push ebx; push esi (Font_init prologue; object-gated A/F lever)"),
    ("veh_draw.hud_fcache",        0x559DE5, 5, "E8 E6 F4 FF FF",             "thunk_hud_fcache",   "call FontCache_get (unit-label font size mul 1/4 -> g/64 for HUD bufs)"),
    ("veh_draw.hud_args",          0x5594F0, 6, "55 8B EC 83 EC 2C",          "thunk_hud_vehargs",  "veh_draw prologue (size sentinel + x-inset rewrite for HUD-buf calls)"),
    ("base_draw.hud_args",         0x55AF20, 9, "55 8B EC 81 EC 18 01 00 00", "thunk_hud_baseargs", "base_draw prologue (same C' rewrite; PRACX calls +0x42, untouched)"),
    ("StatusWin.slotw",            0x4B4E23, 5, "BA 4B 00 00 00",             "thunk_hud_slotw",    "mov edx,75 fallback slot width (zoom path untouched)"),
    ("StatusWin.titley",           0x4B4EA3, 5, "B8 38 00 00 00",             "thunk_hud_titley",   "mov eax,0x38 fallback title y (64*g/16-8)"),
    ("StatusWin.cellw",            0x4B8156, 5, "B8 32 00 00 00",             "thunk_hud_cellw",    "mov eax,0x32 fallback unit-row cell width (61*g/16-11)"),
    ("hud.n01_box3_inset",         0x4B4D84, 5, "68 F8 D7 78 00",             "thunk_hud_n01",      "esi3 dual-purpose inset (box3)"),
    ("hud.n02_box4_inset",         0x4B6A1F, 5, "68 F8 D7 78 00",             "thunk_hud_n02",      "esi3 dual-purpose inset (box4)"),
    ("hud.n03_tile_x",             0x4B6B82, 5, "25 64 EC 7A 00",             "thunk_hud_n03",      "tile-info x +2"),
    ("hud.n04_tile_y",             0x4B6B88, 5, "52 56 8B 75 14",             "thunk_hud_n04",      "tile-info y +1"),
    ("hud.n05_tile_row",           0x4B6BCB, 6, "8B 82 A8 15 00 00",          "thunk_hud_n05",      "tile-info row +3"),
    ("hud.n06_tile_wrap",          0x4B6BF2, 5, "E8 B9 40 12 00",             "thunk_hud_n06",      "tile-info wrap -4 (call-site tail-jmp)"),
    ("hud.n07_coord_x",            0x4B7F05, 8, "74 1E 52 E8 D3 D4 18 00",    "thunk_hud_n07",      "map-coord x +2"),
    ("hud.n08_coord_x2",           0x4B8001, 8, "74 1B 52 E8 D7 D3 18 00",    "thunk_hud_n08",      "map-coord x -2"),
    ("hud.n09_box9_text",          0x45BF86, 6, "89 45 EC 89 4D F0",          "thunk_hud_n09",      "box9 text innerL/T+3"),
    ("hud.n10_infowin_template",   0x4593A1, 6, "81 FA 20 03 00 00",          "thunk_hud_n10",      "box5 InfoWin rects template +7/-39"),
    ("hud.n11_infowin_colgap",     0x4593CA, 6, "03 CA 03 C2 EB 0F",          "thunk_hud_n11",      "box5 colgap +3 (tail = displaced jmp)"),
    ("hud.n12_infowin_anchor",     0x456395, 6, "83 C3 05 83 C1 05",          "thunk_hud_n12",      "box5 line anchors +5"),
    ("hud.n13_box6_inset",         0x4B80D9, 5, "8B 45 F4 03 D6",             "thunk_hud_n13",      "esi3 dual-purpose inset (box6 row)"),
    ("hud.n14_box6_pitch",         0x4B8230, 5, "99 F7 FF 8B F8",             "thunk_hud_n14",      "slot pitch +5 before span idiv"),
    ("hud.n15_box6_slack",         0x4B8295, 8, "89 45 18 A1 80 50 7B 00",    "thunk_hud_n15",      "row span slack -5"),
    ("hud.n16_box6_labely",        0x4B86E6, 6, "2B C2 8D 54 08 01",          "thunk_hud_n16",      "0-1-1 label y: 27 -> eax+19g/16+1"),
    ("Buffer_box_sprite.hud_frames",0x5E2DD3, 5, "51 53 55 56 57",            "thunk_hud_boxframe", "Buffer_box_sprite prologue (HUD dests -> hollow_flat + NAT rect law)"),
    ("StatusWin.cell_highlight",   0x4B8764, 5, "E8 9A AA 12 00",             "thunk_hud_cellring", "call Buffer_box_2 core (box6 selected-cell ring thicken)"),
    ("FlatButton.hud_btnfont",     0x607E50, 5, "83 EC 14 53 55",             "thunk_hud_btnfont",  "FlatButton draw prologue (M/I label font -> fA12)"),
]
PATCH_PAD = {5: "", 6: " 90", 8: " 90 90 90", 9: " 90 90 90 90"}
with open("_hud_widgets_sites.yaml", "w", encoding="utf-8", newline="\n") as f:
    f.write("  # ==== hud_widgets_scale — see group of same name. The complete v35 Frida lever set\n")
    f.write("  # baked (prototype user-verified at 4K across hook_hudframes v8..v44). ====\n")
    for sid, va, ln, orig, tgt, note in SITES:
        f.write(f"  - id: {sid}\n")
        f.write("    status: confirmed\n")
        f.write("    group: hud_widgets_scale\n")
        f.write(f"    virtual_addr: 0x{va:08X}\n")
        f.write(f"    length: {ln}\n")
        f.write(f"    original_bytes: \"{orig}\"\n")
        f.write(f"    new_bytes:      \"E8 {{rel32:{tgt}}}{PATCH_PAD[ln]}\"\n")
        f.write("    pattern: call_target_redirect\n")
        f.write(f"    # {note}\n")
with open("_hud_widgets_contents.yaml", "w", encoding="utf-8", newline="\n") as f:
    f.write("      # ==== hud_widgets_scale (the baked v35 lever set) — pcave2 0x5000.. ====\n")
    f.write("      # src scripts\assemble_hud_widgets.py (keystone-baked, concrete VAs).\n")
    for name, (off, b) in sorted(out.items(), key=lambda kv: kv[1][0]):
        f.write(f"      - id: {name}\n")
        f.write(f"        offset: 0x{off:04X}\n")
        f.write("        bytes: \"" + " ".join(f"{x:02X}" for x in b) + "\"\n")
    for nm, off in (("g_hud_rect", RECT_OFF), ("g_hud_rect2", RECT2_OFF)):
        f.write(f"      - id: {nm}\n")
        f.write(f"        offset: 0x{off:04X}\n")
        f.write("        bytes: \"" + " ".join(["00"] * 16) + "\"\n")
with open("_hud_widgets_symbols.yaml", "w", encoding="utf-8", newline="\n") as f:
    for name, (off, b) in sorted(out.items(), key=lambda kv: kv[1][0]):
        f.write(f"  {name}:{' ' * max(1, 29 - len(name))}{{ cave: pcave2, offset: 0x{off:04X} }}   # {len(b)}B hud_widgets_scale\n")
    for nm, off in (("g_hud_rect", RECT_OFF), ("g_hud_rect2", RECT2_OFF)):
        f.write(f"  {nm}:{' ' * max(1, 29 - len(nm))}{{ cave: pcave2, offset: 0x{off:04X} }}   # 16B scratch RECT\n")
print("yaml fragments written")
