#!/usr/bin/env python
"""combat_console_scale bake (2026-09-18): the BattleWin combat console + its post-combat
console restore.  Static map work\\_cmb_static_map.md; ground truth work\\_cmb_probe\\ (pristine
1024 + patched 1024/1600/4K runs of hook_combat_geom.js); laws scaling_laws.battlewin_rects /
battle_portrait_layout / battle_slot / battle_unit_name_y / battle_stats_y.

  t_cmb_init    wraps the sole BattleWin_init call (system_init 0x58F1DB): the engine derives the
                4 boxes from seed-SCALED D80/DC0 with NATIVE insets 4 / gap 3 -> recompute with
                fl(4g/16) / fl(3g/16), far edges R-1/B-1 (inclusive band-map footprint; law battlewin_rects).
  t_cmb_slot    0x421C90 `and ebx,0x19; add ebx,0x32` -> slot 75 x g/16 (veh centring, unit-name
                y, "destroyed" y all read this one register/local).
  t_cmb_ins3a/b 0x421E13 / 0x421E19: the inner text-rect inset 3 (8 uses) x g/16.
  t_cmb_stat5   0x42250D: first stats line y +5 x g/16.
  t_cmb_wL/wR   0x421EF2 / 0x422025: portrait sprite WIDTH read -> fl(w g/16) (the engine's own
                centring x and y = T+(x-L) then follow).
  t_cmb_hL/hR   0x421F3F / 0x42206E: portrait sprite HEIGHT read -> fl(h g/16), label gap 3 x g/16.
  t_cmb_snap    BattleWin iface vtbl 0x66AA44 slot 0: clone of the diplo console save-under arm
                (t_cr_snap) in front of BattleWin_on_status -- combat close re-tiles only DA0/DB0,
                leaving the box5/box6 band holding combat pixels unless the save-under is armed
                (it was armed by DiploTalkIface_on_mode / the DL iface only).
REUSED (no new code): the 3 local Font_init sites -> thunk_hud_font (direct-init law: face/style
kept, size fl(12g/16)); find_font(14,1)/(16,1) sites -> t_ffn (face law); the two portrait
Sprite_draw_2 sites -> thunk_cw_portrait (council: 1/1 -> g/16 + parity re-blit; the portraits carry a
1-row scanline dither that plain NN row duplication bands -- measured 1/2-row runs at g=22/25).
All thunks over flag-neutral originals are pushfd/popfd transparent.  g<=16: every thunk is the
identity (popup_scale at g=16), t_cmb_init/t_cmb_snap gate explicitly.

Usage: py assemble_combat.py            (assemble + print)
       py assemble_combat.py --splice   (also splice into ..\\patches\\patches.yaml, byte-safe)
"""
import pathlib
import re
import struct
import sys

import pefile
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config  # noqa: E402

PCAVE2 = 0x00A0C000
BASE_OFF = 0x29780                     # cave_map --at 0x29780: FREE (prev ends 0x29764, next 0x2A000)
LIMIT_OFF = 0x2A000
G = 0x668740                           # g_popup_scale_num
PS = 0x668750                          # popup_scale: eax = eax*g >> 4
ENSURE = 0x668760                      # thunk_ensure_scale
BW_INIT, BW_ONSTATUS = 0x4219E0, 0x422CC0
SEED_D80, SEED_D90, SEED_DB0, SEED_DC0 = 0x7AF5A0, 0x7AF5B0, 0x7AF5D0, 0x7AF5E0
MW_CANVAS = 0x7AEC64
CANVAS_DATA, CANVAS_STRIDE = MW_CANVAS + 0x54, MW_CANVAS + 0x4A8
IAT_VIRTUALALLOC = 0x669134
CRBUF, CRL, CRR, CRB, CRARM = (PCAVE2 + 0x12790 + 4 * i for i in range(5))   # diplo save-under cells
T_CR_MARK = PCAVE2 + 0x17080                 # assemble_diplo t_cr_mark (FIXED_OFF)

ks = Ks(KS_ARCH_X86, KS_MODE_32)
THUNKS = []


def T(name, asm):
    THUNKS.append((name, asm))


def scaled_const(reg_out, k):
    """reg_out = fl(k*g/16); preserves eax unless it is reg_out."""
    if reg_out == "eax":
        return f"mov eax, {k}\ncall {PS:#x}\n"
    return f"push eax\nmov eax, {k}\ncall {PS:#x}\nmov {reg_out}, eax\npop eax\n"


T("t_cmb_init", f"""
    push ecx
    call {ENSURE:#x}
    pop ecx
    push ecx
    call {BW_INIT:#x}
    pop ecx
    cmp dword ptr [{G:#x}], 16
    jle ci_out
    pushad
    mov esi, ecx
    mov eax, 4
    call {PS:#x}
    mov ebx, eax
    mov eax, 3
    call {PS:#x}
    mov ebp, eax
    mov edi, {SEED_DC0:#x}
    mov eax, dword ptr [edi]
    add eax, ebx
    mov dword ptr [esi+0x30], eax
    mov edx, dword ptr [edi+4]
    add edx, ebx
    mov dword ptr [esi+0x34], edx
    mov dword ptr [esi+0x44], edx
    mov edx, dword ptr [edi+0xC]
    sub edx, ebx
    mov dword ptr [esi+0x3C], edx
    mov dword ptr [esi+0x4C], edx
    mov ecx, dword ptr [edi+8]
    sub ecx, eax
    dec ecx
    sar ecx, 1
    sub ecx, ebp
    add ecx, eax
    mov dword ptr [esi+0x38], ecx
    mov edx, ecx
    sub edx, eax
    add edx, ebp
    add eax, edx
    mov dword ptr [esi+0x40], eax
    add ecx, edx
    mov dword ptr [esi+0x48], ecx
    mov edi, {SEED_D80:#x}
    mov eax, dword ptr [edi]
    add eax, ebx
    mov dword ptr [esi+0x50], eax
    mov edx, dword ptr [edi+4]
    add edx, ebx
    mov dword ptr [esi+0x54], edx
    mov dword ptr [esi+0x64], edx
    mov edx, dword ptr [edi+0xC]
    sub edx, ebx
    mov dword ptr [esi+0x5C], edx
    mov dword ptr [esi+0x6C], edx
    mov ecx, dword ptr [edi+8]
    sub ecx, eax
    dec ecx
    sar ecx, 1
    sub ecx, ebp
    add ecx, eax
    mov dword ptr [esi+0x58], ecx
    add ecx, ebp
    mov dword ptr [esi+0x60], ecx
    mov ecx, dword ptr [edi+8]
    sub ecx, ebx
    mov dword ptr [esi+0x68], ecx
    dec dword ptr [esi+0x38]
    dec dword ptr [esi+0x3C]
    dec dword ptr [esi+0x48]
    dec dword ptr [esi+0x4C]
    dec dword ptr [esi+0x58]
    dec dword ptr [esi+0x5C]
    dec dword ptr [esi+0x68]
    dec dword ptr [esi+0x6C]
    popad
ci_out:
    ret
""")

# 0x421C90: and ebx,0x19 / add ebx,0x32  (eax live; originals set flags themselves)
T("t_cmb_slot", f"""
    and ebx, 0x19
    add ebx, 0x32
    push eax
    mov eax, ebx
    call {PS:#x}
    mov ebx, eax
    pop eax
    ret
""")

# 0x421E13: add eax,3 / mov [ebp-0x70],eax   (add sets flags itself)
T("t_cmb_ins3a", f"""
    push edx
    mov edx, eax
    mov eax, 3
    call {PS:#x}
    add eax, edx
    pop edx
    mov dword ptr [ebp-0x70], eax
    ret
""")

# 0x421E19: mov eax,3   (flag-neutral)
T("t_cmb_ins3b", f"""
    pushfd
    mov eax, 3
    call {PS:#x}
    popfd
    ret
""")

# 0x42250D: lea ebx,[edx+5] / mov [ebp-0x10],eax   (flag-neutral; eax live)
T("t_cmb_stat5", f"""
    pushfd
    mov dword ptr [ebp-0x10], eax
    push eax
    mov eax, 5
    call {PS:#x}
    lea ebx, [edx+eax]
    pop eax
    popfd
    ret
""")


def wthunk(name, rect_off):
    # mov edx,[eax+0x18] / mov ecx,[esi+rect_off]   (flag-neutral; eax live)
    T(name, f"""
    pushfd
    mov edx, dword ptr [eax+0x18]
    push eax
    mov eax, edx
    call {PS:#x}
    mov edx, eax
    pop eax
    mov ecx, dword ptr [esi+{rect_off:#x}]
    popfd
    ret
""")


wthunk("t_cmb_wL", 0x50)
wthunk("t_cmb_wR", 0x60)

# 0x421F3F: mov eax,[eax+0x1c] / mov edx,[edi+4]; the engine then does lea eax,[eax+esi+3]
# -> return h' + (s3 - 3) so the engine's own +3 lands on y + h' + s3.
T("t_cmb_hL", f"""
    pushfd
    mov eax, dword ptr [eax+0x1c]
    call {PS:#x}
    push eax
    mov eax, 3
    call {PS:#x}
    sub eax, 3
    add dword ptr [esp], eax
    pop eax
    mov edx, dword ptr [edi+4]
    popfd
    ret
""")

# 0x42206E: mov eax,[eax+0x1c] / lea esi,[esi+eax+3]   (eax dead after: next is mov eax,[edx])
T("t_cmb_hR", f"""
    pushfd
    mov eax, dword ptr [eax+0x1c]
    call {PS:#x}
    add esi, eax
    mov eax, 3
    call {PS:#x}
    add esi, eax
    popfd
    ret
""")

# clone of assemble_diplo.t_cr_snap (same cells, same region), tail = BattleWin_on_status
T("t_cmb_snap", f"""
    cmp dword ptr [{G:#x}], 0x10
    jle cs_pass
    cmp dword ptr [esp+4], 0
    je cs_pass
    pushad
    mov eax, dword ptr [{SEED_D80 + 8:#x}]
    dec eax
    mov dword ptr [{CRL:#x}], eax
    mov edx, dword ptr [{SEED_D90:#x}]
    mov dword ptr [{CRR:#x}], edx
    mov ecx, dword ptr [{SEED_DB0 + 4:#x}]
    add ecx, 2
    mov dword ptr [{CRB:#x}], ecx
    mov ebx, dword ptr [{CRBUF:#x}]
    test ebx, ebx
    jnz cs_have
    mov eax, edx
    sub eax, dword ptr [{CRL:#x}]
    imul eax, ecx
    push 4
    push 0x3000
    push eax
    push 0
    call dword ptr [{IAT_VIRTUALALLOC:#x}]
    test eax, eax
    jz cs_bail
    mov dword ptr [{CRBUF:#x}], eax
    mov ebx, eax
cs_have:
    mov esi, dword ptr [{CANVAS_DATA:#x}]
    test esi, esi
    jz cs_bail
    add esi, dword ptr [{CRL:#x}]
    mov edi, ebx
    mov edx, dword ptr [{CRR:#x}]
    sub edx, dword ptr [{CRL:#x}]
    mov ebp, dword ptr [{CRB:#x}]
cs_row:
    push esi
    push edi
    mov ecx, edx
    rep movsb
    pop edi
    pop esi
    add esi, dword ptr [{CANVAS_STRIDE:#x}]
    add edi, edx
    dec ebp
    jnz cs_row
    call {T_CR_MARK:#x}
    .byte 0x0F, 0x1F, 0x40, 0x00
cs_bail:
    popad
cs_pass:
    jmp {BW_ONSTATUS:#x}
""")

# ---------------- assemble at fixed, 16-aligned offsets ----------------
OUT = {}
off = BASE_OFF
for name, asm in THUNKS:
    enc, _ = ks.asm(asm, PCAVE2 + off)
    b = bytes(enc)
    OUT[name] = (off, b)
    print(f"OK  {name:14s} @0x{off:05X} len={len(b):3d}")
    off = (off + len(b) + 15) & ~15
assert off <= LIMIT_OFF, hex(off)

# ---------------- sites (original bytes read from the PRISTINE exe) ----------------
bak = pathlib.Path(config.game_exe_path()).with_suffix(".exe.bak") if hasattr(config, "game_exe_path") else None
if bak is None or not bak.exists():
    bak = pathlib.Path(r"D:\GOG Galaxy\Games\Sid Meier's Alpha Centauri Planetary Pack\terranx_PRACX.exe.bak")
pe = pefile.PE(str(bak), fast_load=True)
IMG = pe.OPTIONAL_HEADER.ImageBase


def orig(va, n):
    for s in pe.sections:
        a = IMG + s.VirtualAddress
        if a <= va < a + s.SizeOfRawData:
            return s.get_data()[va - a: va - a + n]
    raise KeyError(hex(va))


# (id, function, va, length, target, pattern, note)
SITES = [
    ("system_init.battlewin_init",        "system_init",             0x58F1DB, 5, "t_cmb_init",     "BattleWin_init call: rects recomputed with scaled insets"),
    ("battle_report.font_stats0",         "BattleWin_battle_report", 0x421CA8, 5, "thunk_hud_font", "Font_init(hud,12,0) local stats font"),
    ("battle_report.font_stats2",         "BattleWin_battle_report", 0x421CC0, 5, "thunk_hud_font", "Font_init(hud,12,2) local stats font"),
    ("battle_report.font_stats1",         "BattleWin_battle_report", 0x421CD7, 5, "thunk_hud_font", "Font_init(hud,12,1) local stats font"),
    ("battle_report.font_faction",        "BattleWin_battle_report", 0x421E5E, 5, "t_ffn",          "find_font(14,1) faction names"),
    ("battle_report.font_unit",           "BattleWin_battle_report", 0x422459, 5, "t_ffn",          "find_font(16,1) unit name"),
    ("battle_report.slot",                "BattleWin_battle_report", 0x421C90, 6, "t_cmb_slot",     "unit slot 75"),
    ("battle_report.inset3a",             "BattleWin_battle_report", 0x421E13, 6, "t_cmb_ins3a",    "text-rect inset 3 (first use)"),
    ("battle_report.inset3b",             "BattleWin_battle_report", 0x421E19, 5, "t_cmb_ins3b",    "text-rect inset 3 (mov eax,3: 7 uses)"),
    ("battle_report.stats_y",             "BattleWin_battle_report", 0x42250D, 6, "t_cmb_stat5",    "stats first line y +5"),
    ("battle_report.portraitL_w",         "BattleWin_battle_report", 0x421EF2, 6, "t_cmb_wL",       "left portrait width read"),
    ("battle_report.portraitL_draw",      "BattleWin_battle_report", 0x421F30, 5, "thunk_cw_portrait", "left portrait Sprite_draw_2 1/1 -> g/16 + parity re-blit (scanline dither regenerated)"),
    ("battle_report.portraitL_h",         "BattleWin_battle_report", 0x421F3F, 6, "t_cmb_hL",       "left portrait height read + label gap"),
    ("battle_report.portraitR_w",         "BattleWin_battle_report", 0x422025, 6, "t_cmb_wR",       "right portrait width read"),
    ("battle_report.portraitR_draw",      "BattleWin_battle_report", 0x422060, 5, "thunk_cw_portrait", "right portrait Sprite_draw_2 1/1 -> g/16 + parity re-blit (scanline dither regenerated)"),
    ("battle_report.portraitR_h",         "BattleWin_battle_report", 0x42206E, 7, "t_cmb_hR",       "right portrait height read + label gap"),
]
VTBL = ("battlewin_on_status_saveunder", 0x66AA44, "t_cmb_snap", BW_ONSTATUS)
assert orig(VTBL[1], 4) == struct.pack("<I", BW_ONSTATUS), orig(VTBL[1], 4).hex()
for sid, fn, va, ln, tgt, note in SITES:
    o = orig(va, ln)
    if tgt in ("thunk_hud_font", "t_ffn", "thunk_cw_portrait", "t_cmb_init"):
        assert o[0] == 0xE8 and ln == 5, (sid, o.hex())

GROUP = "combat_console_scale"
M_SYM = (f"  # ==== {GROUP} symbols (2026-09-18, src assemble_combat.py) ====\n", f"# ==== {GROUP} END ==== symbols\n")
M_CAVE = (f"      # ==== {GROUP} cave (src assemble_combat.py; laws scaling_laws.battlewin_rects et al) ====\n", f"# ==== {GROUP} END ==== cave\n")
M_GRP = (f"  # ==== {GROUP} group ====\n", f"# ==== {GROUP} END ==== groups\n")
M_SITE = (f"  # ==== {GROUP} sites (2026-09-18; src assemble_combat.py) ====\n", f"# ==== {GROUP} END ==== sites\n")

sym = M_SYM[0]
for name, (o, b) in OUT.items():
    sym += f"  {name}:{' ' * max(1, 29 - len(name))}{{ cave: pcave2, offset: 0x{o:05x} }}   # {GROUP} ({len(b)}B)\n"
sym += M_SYM[1]

cave = M_CAVE[0]
for name, (o, b) in OUT.items():
    cave += f"      - id: {name}\n        offset: 0x{o:05x}\n        bytes: \"" + " ".join(f"{x:02X}" for x in b) + "\"\n"
cave += M_CAVE[1]

members = [s[0] for s in SITES] + [VTBL[0]]
grp = M_GRP[0] + f"""  - id: {GROUP}
    description: >
      COMBAT CONSOLE (BattleWin) scales with the HUD: box insets/gap (BattleWin_init recompute),
      the three local stats fonts + faction/unit name fonts (font law), both faction portraits
      (sprite dims scaled at the engine's own centring reads + the draws 1/1 -> g/16), unit slot 75,
      text insets 3, stats y 5; and the post-combat console restore (save-under armed from
      BattleWin_on_status like the diplo/DL ifaces).  Ground truth work\\_cmb_probe (pristine 1024 +
      patched 1024/1600/4K), map work\\_cmb_static_map.md, laws scaling_laws.battlewin_rects /
      battle_portrait_layout / battle_slot / battle_unit_name_y / battle_stats_y, parity
      tests\\test_scaling_combat_parity.py.
    members:
""" + "".join(f"      - {m}\n" for m in members) + M_GRP[1]

PAD = {5: "", 6: " 90", 7: " 90 90"}
site = M_SITE[0]
for sid, fn, va, ln, tgt, note in SITES:
    site += (f"  - id: {sid}\n    status: confirmed\n    group: {GROUP}\n    function: {fn}\n"
             f"    virtual_addr: 0x{va:08X}\n    length: {ln}\n"
             f"    original_bytes: \"{' '.join(f'{x:02X}' for x in orig(va, ln))}\"\n"
             f"    new_bytes:      \"E8 {{rel32:{tgt}}}{PAD[ln]}\"\n"
             f"    pattern: call_target_redirect\n    # {note}\n")
site += (f"  - id: {VTBL[0]}\n    status: confirmed\n    group: {GROUP}\n    function: {VTBL[0]}\n"
         f"    virtual_addr: 0x{VTBL[1]:08x}\n    length: 4\n"
         f"    original_bytes: \"{' '.join(f'{x:02X}' for x in orig(VTBL[1], 4))}\"  # BattleWin_on_status slot (console save-under snapshot)\n"
         f"    new_bytes:      \"{{abs32:{VTBL[2]}}}\"\n    pattern: vtable_repoint\n")
site += M_SITE[1]

if "--splice" in sys.argv:
    y = pathlib.Path(__file__).resolve().parent.parent / "patches" / "patches.yaml"
    data = y.read_bytes()
    nl = b"\r\n" if b"\r\n" in data[:4096] else b"\n"

    def put(data, block, markers, anchor):
        blk = block.replace("\n", nl.decode()).encode("utf-8")
        a, z = markers[0].strip("\n").encode(), markers[1].strip("\n").encode()
        if a in data:                                    # refresh in place
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

    data = put(data, sym, M_SYM, "# ==== diplo_talk_scale END ==== symbols")
    data = put(data, cave, M_CAVE, "# ==== diplo_talk_scale END ==== cave")
    data = put(data, grp, M_GRP, "# ==== diplo_talk_scale END ==== groups")
    data = put(data, site, M_SITE, "# ==== diplo_talk_scale END ==== sites")
    y.write_bytes(data)
    print("spliced into", y)
