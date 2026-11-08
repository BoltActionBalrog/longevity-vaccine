"""Guard: every asm port of the stripe period carries the ONE law (scaling_laws.stripe_period = 2 * stripe_rows).

stripe_rows(g) is 1 below g = 22 (screens under 1080 px high), else art_scan_rows(g) = max(2, g // 16).
- thunk_ensure_scale stores g_stripe_period = 2 below g = 22, else 4, next to g; g is clamped to 40 there, and the
  law is 4 for g = 22..47.  If the clamp is ever raised past 47 that store must take the general form.
- The popup-g ports read that cell (raw VA 0x66879C).
- The num ports compute T themselves: t_mon_panel / t_hof_pairnn from the Monument / Hall of Fame num (unclamped /
  72), t_rwk_parity_nn from g_popup_scale_num, which t_hof_spr_pic brackets with the Hall of Fame num around its
  call (the only other writer of that cell -- a new writer must be reviewed against every cell reader);
  t_mon_face leaves num < 22 untouched (law mon_face_restripe: P <= 2) and uses max(2, num >> 4) above.
No entry may carry the old P = (g + 4) >> 3 arithmetic (a byte-signature check of the forms the ports used, not a
proof) or the interim constant period.
"""
import re
import struct
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

PATCHES = HERE.parent / "patches" / "patches.yaml"

POPUP_G_PORTS = [
    "thunk_fe_pair_remap", "thunk_s54_restripe", "thunk_ensure_stripes", "restripe_core", "hm_synth_core",
    "thunk_rail_bake", "thunk_sbarrow_bg", "thunk_ed_remap", "thunk_se_stripe_top", "thunk_se_tiles",
    "thunk_dw_restripe", "thunk_dw_backdrop", "t_dl_restripe", "t_rw_restripe", "thunk_face_hybrid",
]
NUM_PORTS = ["t_mon_face", "t_mon_panel", "t_hof_pairnn", "t_rwk_parity_nn"]
G_WRITERS = {"thunk_ensure_scale", "t_hof_spr_pic"}
# cell readers with their own period arithmetic (not a plain "P into a register" port):
# the faction drop-arrow cell ((row mod P) < P/2) and the council flag (T = P/2 rows per LUT half)
OTHER_CELL_READERS = {"t_fdicon_checker", "t_msg_icon", "t_sb_tile2", "t_sbt_zoom",
                      "t_hud_backdrop", "t_si_chip", "t_spr_paint", "t_spr_stripes", "thunk_faction_dropimg",
                      "thunk_flag_restripe",
                      "thunk_btn_stripes",   # reduces a NEGATIVE parent-local top by P (v13, g_rm_yph)
                      "thunk_se_rowdraw_ph",   # the same reduction for the SE face phase (g_se_yph)
                      "t_rowbox_ph",   # the same reduction for the popup option-row phase (g_rm_yph)
                      "t_lbi_restripe_ph",   # the same reduction for the faction-picker list rows (g_rm_yph)
                      "t_sbt_ph",   # the same reduction for owned-button zoom faces (t_sbt_zoom; [ebp-0x14])
                      "t_dw_face_ph",   # the same reduction for the Design Workshop button faces (g_se_yph)
                      "t_clhd_draw",   # the COMMLINK MP header strip: stripe_top(dest y) for its scanicon shade
                      "t_clhd_snap",   # the COMMLINK MP header strip: its inner box snapped to whole periods
                      "t_face_own",   # T = P / 2 for the own-top face phase search (W9A, own_face_stripe_phase)
                      "t_ck_draw",   # T = P / 2 for the checkbox law's (dest row + phase) / T field
                      "t_ck_list",   # floor-reduces the list canvas's parent-local top by P (g_ck_ph)
                      "t_nw_box",   # T = P / 2 for the lobby panel fill's dest-row field
                      "t_nwf_core",   # the same field: t_nw_box's stripe tail inside the K band (netwin_frame_strokes)
                      "thunk_pp_scrollblit"}   # reads P only to test pitch % P (never draws a stripe)

# add r,4 / lea r,[r+4] then shr|sar r,3: the old period
OLD = re.compile(r"(83 C[0-7] 04|8D [45][0-9A-F] 04) C1 [EF][0-9A-F] 03")
CONST4 = re.compile(r"B[89B] 04 00 00 00 90")                 # mov eax|ecx|ebx, 4 ; nop (the interim constant)
CELL_READ = re.compile(r"(A1|8B [01]D) 9C 87 66 00")          # mov eax|ecx|ebx, [g_stripe_period]
# cmp eax,22 ; sbb edx,edx ; shr eax,4 ; cmp eax,2 ; adc eax,edx   = stripe_rows(eax)
GENERAL = re.compile(r"83 F8 16 (19 D2|1B D2) C1 E8 04 83 F8 02 (11 D0|13 C2)")
FACE = re.compile(r"83 F8 16 (0F 8C [0-9A-F ]{11}|7C [0-9A-F]{2}) C1 E8 04 83 F8 02 83 D0 00")   # cmp eax,22 ; jl ; max(2, n>>4)
PERIOD_STORE = "83 F8 16 19 C0 8D 44 00 04 A3 {ABS32:G_STRIPE_PERIOD}"   # cmp eax,22 ; sbb eax,eax ; lea eax,[eax+eax+4]
CLAMP40 = "83 F8 28 7E 05 B8 28 00 00 00"                     # cmp eax,40 ; jle +5 ; mov eax,40
G_CELL = r"(\{ABS32:G_POPUP_SCALE_NUM\}|40 87 66 00)"
# mov [g],eax / mov [g],r32 / mov dword [g],imm32 / pop [g] / xchg [g],r32
G_STORE = re.compile(r"(A3|89 [0-3][5D]|C7 05|8F 05|87 [0-3][5D]) " + G_CELL)


def _contents():
    _, _, caves, _ = ap.load_patches(PATCHES)
    return {ct["id"]: " ".join(str(ct["bytes"]).upper().split()) for c in caves for ct in c.get("contents", []) or []}


def _run(code: bytes, eax: int) -> int:
    uc_mod = pytest.importorskip("unicorn")
    from unicorn import x86_const as X
    uc = uc_mod.Uc(uc_mod.UC_ARCH_X86, uc_mod.UC_MODE_32)
    uc.mem_map(0x1000, 0x1000)
    uc.mem_write(0x1000, code)
    uc.reg_write(X.UC_X86_REG_EAX, eax)
    uc.reg_write(X.UC_X86_REG_EDX, 0x12345678)
    uc.emu_start(0x1000, 0x1000 + len(code))
    return struct.unpack("<i", struct.pack("<I", uc.reg_read(X.UC_X86_REG_EAX)))[0]


def test_ensure_scale_stores_the_law_period_for_every_clamped_g():
    c = _contents()
    assert CLAMP40 in c["thunk_ensure_scale"] and PERIOD_STORE in c["thunk_ensure_scale"]
    assert c["g_stripe_period"] == "02 00 00 00"
    code = bytes.fromhex("83F81619C08D440004")
    for g in range(16, 41):
        assert _run(code, g) == SL.stripe_period(g), g
    assert [SL.stripe_period(g) for g in (16, 17, 21, 22, 40)] == [2, 2, 2, 4, 4]
    assert SL.STRIPE_2ROW_MIN_G == 16 * 1080 // 768


def test_num_port_formula_is_stripe_rows():
    c = _contents()
    for cid in NUM_PORTS:
        m = GENERAL.search(c[cid])
        assert m, cid
        code = bytes.fromhex(m.group(0).replace(" ", ""))
        for n in range(17, 81):
            assert _run(code, n) == SL.stripe_rows(n), (cid, n)
def test_the_popup_g_cell_has_only_its_two_known_writers():
    assert {cid for cid, b in _contents().items() if G_STORE.search(b)} == G_WRITERS


def test_popup_g_ports_read_the_period_cell():
    c = _contents()
    for cid in POPUP_G_PORTS:
        assert len(CELL_READ.findall(c[cid])) == 1, cid
        assert not OLD.search(c[cid]) and not CONST4.search(c[cid]), cid
    readers = {cid for cid, b in c.items() if "9C 87 66 00" in b or "{ABS32:G_STRIPE_PERIOD}" in b}
    want = set(POPUP_G_PORTS) | {"thunk_ensure_scale"} | OTHER_CELL_READERS
    assert readers == want, readers ^ want


def test_no_thunk_forces_a_private_period():
    """The faction buttons' 1-px override is gone (user 2026-10-04: every striped surface on the one rule): no
    entry may store a non-zero g_rm_povr, and the faction quote buffer no longer skips the devfill restripe."""
    c = _contents()
    forced = [cid for cid, b in c.items() if re.search(r"C7 05 \{ABS32:G_RM_POVR\} (?!00 00 00 00)", b)]
    assert forced == [], forced
    assert "81 F9 24 08 94 00 74 00" in c["thunk_box_thick_devfill"]


def test_no_entry_carries_the_old_period():
    hits = [cid for cid, b in _contents().items() if OLD.search(b)]
    assert hits == [], hits


@pytest.mark.parametrize("g", [17, 18, 22, 25, 32, 40, 48])
def test_btn_face_stripe_phase_is_the_parent_grid(g):
    """btn_stripes v13: a FlatButton face stripes on its parent canvas's grid -- the phase is
    list_stripe_phase of rRect1.top + rRect2.top; a negative top takes the floor modulus."""
    p = SL.stripe_period(g)
    for t1, t2 in ((0, 0), (1, 0), (0, 361), (7, 30), (100, -3), (2, 2)):
        ph = SL.btn_face_stripe_phase(t1, t2, g)
        assert ph == SL.list_stripe_phase(t1 + t2, g) and 0 <= ph < p
        for y in range(3 * p):
            assert SL.stripe_top(y + ph, g) == SL.stripe_top(t1 + t2 + y, g)
    for t in (-1, -5, -6, -p, -37):                 # above the parent: still the parent grid (floor mod)
        assert SL.btn_face_stripe_phase(t, 0, g) == t % p


def test_btn_stripes_stages_the_parent_top_for_the_plain_path_only():
    """The shipped btn_stripes reads [esi+0x140] + [esi+0x150] into g_rm_yph once, right before its last
    fe_pair_remap call, and zeroes the cell after it; fe_pair_remap adds the cell to its row before `div P`."""
    c = _contents()
    b = c["thunk_btn_stripes"]
    assert b.count("8B 86 40 01 00 00 03 86 50 01 00 00") == 1
    assert b.endswith("A3 {ABS32:G_RM_YPH} E8 {REL32:THUNK_FE_PAIR_REMAP} 83 25 {ABS32:G_RM_YPH} 00 C3")
    assert "89 F8 03 05 {ABS32:G_RM_YPH} 31 D2 F7 F3" in c["thunk_fe_pair_remap"]
