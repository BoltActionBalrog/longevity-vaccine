"""thinker_overlap.py: the static Thinker-vs-patches.yaml collision measurement (rebuilt 2026-10-28).

Thinker patches the exe IN MEMORY behind its own byte guards; a failed guard is `exit_fail` and the game never
starts.  These tests pin three things:

  1. The parser reads ALL of Thinker 5.5's write surface (counts per mechanism).  A count drift means either the
     clone moved off tag v5.5 or the parser lost a mechanism -- both need a re-measure, never a silent re-pin.
  2. Thinker's guards are evaluated in ITS order on an image that carries its earlier writes (engine call order):
     the unit-array operand table was generated against the Scient-patched image, so every one of its guards passes
     only after the Scient triples are applied.
  3. The collision set between Thinker and the baked exe.  Every entry is a USER decision
     (memory feedback-thinker-conflicts-user-decides); a new entry here is a new conflict a wave introduced, and the
     pin may change only with the decision recorded next to it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import thinker_overlap as T  # noqa: E402

# Thinker 5.5 (tag v5.5, 2026-08-16): the whole write surface of patch_setup() + the two tables.
V55_COUNTS = {"direct": 7, "long_jump": 4, "memcpy": 1, "memset": 8, "read_check": 3, "remove_call": 35,
              "scient": 3127, "short_jump": 23, "veh_operand": 4053, "write_byte": 7, "write_bytes": 40,
              "write_call": 572, "write_jump": 176, "write_offset": 25, "write_word": 5}

# The collision set under PRACX + Thinker (reduced_mode), measured 2026-10-28 on the PRACX bake (exe 5a3e20b0):
# (group, site id, class).  FATAL = our bytes fail Thinker's guard (exit_fail at launch); CLOBBER = Thinker's
# write replaces our bytes in memory.  DECISIONS (user, 2026-10-28; ACTION_ITEMS "THINKER" block):
#   dw_scale / menu strip / credits subwin (the 4 FATAL + decoration_blit_redirect): ours, applied by uimod.dll
#     AFTER Thinker (the FATAL four are `exclude_sites` of target pracx_thinker; the CLOBBERed E8 is restored);
#   bw2.setfont_40f8f8 / bw2.l3_415ad8: BOTH -- uimod.dll chains our thunk into Thinker's function;
#   load_credits_b / GraphicWin_load_pcx pcx_fullscreen: Thinker's (its Ctrl+F4 version label stays).
# This pin is the PRACX bake's view; `test_the_thinker_bake_has_no_fatal_collision` pins the shipped overlay's.
PINNED_COLLISIONS = {
    ("basewin_interior_slice2", "bw2.setfont_40f8f8", "CLOBBER"),
    ("basewin_interior_slice2", "bw2.l3_415ad8", "CLOBBER"),
    ("credits_interlude_scaling", "load_credits_a.subwin", "FATAL"),
    ("credits_interlude_scaling", "load_credits_b.pcx_fullscreen", "CLOBBER"),
    ("credits_interlude_scaling", "GraphicWin_load_pcx.pcx_fullscreen", "CLOBBER"),
    ("dw_scale", "Caviar.E_imm_618a92", "FATAL"),
    ("menu_strip_scaling", "SetupWin_draw_item.decoration_keyed_scaled", "FATAL"),
    ("menu_strip_scaling", "SetupWin_draw_item.decoration_blit_redirect", "CLOBBER"),
    ("menu_strip_scaling", "SetupWin_draw_item.decoration_soft_update_scaled", "FATAL"),
}

# Thinker guards that fail on the CLEAN PRACX base: Thinker's own `repair_*` write_bytes expect the pre-relocation
# unit-array operand after its own VehPatchData loop has rewritten it (non-default options; not ours).
BASE_FAILS_V55 = {0x52632E, 0x526376, 0x526422, 0x526540}


@pytest.fixture(scope="module")
def thinker_src(need_local) -> Path:
    return need_local(T.THINKER_SRC / "patch.cpp", "the Thinker source clone (refs/thinker)").parent


@pytest.fixture(scope="module")
def thinker(thinker_src) -> dict:
    return T.load_thinker(thinker_src)


@pytest.fixture(scope="module")
def base_img(bak_path) -> T.Image:
    return T.Image(bak_path)


@pytest.fixture(scope="module")
def patched_img(baked_exe) -> T.Image:
    return T.Image(baked_exe)


@pytest.fixture(scope="module")
def ours(patches_path):
    return T.load_sites(patches_path)


@pytest.fixture(scope="module")
def measured(thinker, ours, base_img, patched_img) -> dict:
    sites, caves, _ = ours
    return T.measure(thinker, sites, caves, base_img, patched_img, reduced_mode=True)


# ---------------------------------------------------------------- 1. the parser reads everything

def test_parser_counts_pin_thinker_v55(thinker):
    assert thinker["counts"] == V55_COUNTS, (
        "Thinker write-surface counts changed: the clone moved off tag v5.5, or the parser lost a mechanism. "
        "Re-measure with thinker_overlap.py and bring the collision set to the user before re-pinning.")


def test_every_write_bytes_length_and_old_bytes_resolved(thinker):
    for w in thinker["writes"]:
        if w.kind == "write_bytes":
            assert w.old is not None and len(w.old) == w.length, w.text
            assert w.new is not None and len(w.new) == w.length, w.text
        if w.kind == "scient":
            assert w.old and w.new and w.length == 1
        if w.kind == "veh_operand":
            assert w.field_off is not None and w.length == 4


def test_tables_sit_where_patch_setup_applies_them(thinker):
    """Scient's triples go first (line of their loop), then the unit-array operands, then the rest."""
    lines = thinker["table_lines"]
    assert lines["scient"] < lines["veh_operand"]
    first_cpp = min(w.line for w in thinker["writes"] if w.kind not in ("scient", "veh_operand"))
    assert lines["veh_operand"] < first_cpp
    order = [w.kind for w in thinker["writes"]]
    assert order.index("scient") < order.index("veh_operand") < order.index("write_word")


# ---------------------------------------------------------------- 2. gating

def test_pracx_gating_and_forced_options(thinker):
    by_addr = {w.addr: w for w in thinker["writes"] if w.kind != "scient"}
    known = T.forced_options(thinker["assigns"], reduced_mode=True)
    assert known == {"smooth_scrolling": False}, "patch_setup forces smooth_scrolling off under PRACX"
    assert T.forced_options(thinker["assigns"], reduced_mode=False) == {}
    # `if (!cf->reduced_mode)`: never under PRACX, always alone
    assert by_addr[0x62D3EC].gating(True, known)[0] == "never"
    assert by_addr[0x62D3EC].gating(False)[0] == "always"
    # `if (cf->smooth_scrolling)`: forced off under PRACX, an option alone
    assert by_addr[0x46AB81].gating(True, known)[0] == "never"
    assert by_addr[0x46AB81].gating(False) == ("option", ("cf->smooth_scrolling",))
    # plain writes and one-line `if (!cf->landmarks.x) remove_call(...)` bodies
    assert by_addr[0x4E27F6].gating(True, known) == ("always", ())
    assert by_addr[0x5C88A0].gating(True, known) == ("option", ("!cf->landmarks.jungle",))
    assert by_addr[0x5C88A9].gating(True, known) == ("option", ("!cf->landmarks.crater",))
    assert by_addr[0x414D52].kind == "memset" and by_addr[0x414D52].gating(True, known) == ("always", ())


def test_read_gates_are_recorded(thinker):
    rc = {w.addr: w for w in thinker["writes"] if w.kind == "read_check"}
    assert set(rc) == {0x5AF56D, 0x5AF5B5, 0x462F2E}
    assert rc[0x5AF56D].old == bytes.fromhex("83CB") and rc[0x5AF56D].width == 2


# ---------------------------------------------------------------- 3. the guards, in Thinker's order

def test_guards_pass_on_the_clean_base_in_engine_call_order(measured):
    fails = {b["write"]["addr"] for b in measured["base_fails"]}
    assert fails == BASE_FAILS_V55, (
        "a Thinker guard fails on the CLEAN PRACX base that did not before: either PRACX's base changed or the "
        "emulation order drifted (the unit-array table is only valid after the Scient triples)")
    for b in measured["base_fails"]:
        assert b["gate"] == "option", b     # every one is a non-default option of Thinker's own


def test_unit_array_guards_need_the_scient_pass_first(thinker, base_img):
    """Measured 2026-10-28: 17 VehPatchData operands sit inside Scient-patched bytes; against the raw exe their
    guards fail, after the Scient triples they pass.  This is the engine-call-order rule in one assertion."""
    raw = base_img.copy()
    veh = [w for w in thinker["writes"] if w.kind == "veh_operand"]
    raw_fails = sum(T.check(w, raw, thinker["skip_verify"], thinker["vehs_def"])[0] == "fail" for w in veh)
    assert raw_fails == 17
    ordered = base_img.copy()
    for w in thinker["writes"]:
        if w.kind == "scient":
            T.apply_write(w, ordered, thinker["vehs_def"])
    assert sum(T.check(w, ordered, thinker["skip_verify"], thinker["vehs_def"])[0] == "fail" for w in veh) == 0


# ---------------------------------------------------------------- 4. the collision set (user decisions)

def test_no_thinker_write_inside_our_caves(measured):
    assert measured["cave_hits"] == []


def test_nothing_overlaps_only_under_thinker_alone(measured):
    """Thinker-alone is not a target; a write gated off under PRACX that overlaps a site of ours is still listed."""
    assert measured["skipped_mode"] == []


def test_collision_set_is_pinned_to_user_decisions(measured):
    got = {(h["site"]["group"], h["site"]["id"], h["class"]) for h in measured["hits"]}
    new = got - PINNED_COLLISIONS
    gone = PINNED_COLLISIONS - got
    assert not new, f"NEW Thinker collisions (a user decision each; do not re-pin without one): {sorted(new)}"
    assert not gone, f"pinned collisions disappeared (re-measure, then re-pin with the user): {sorted(gone)}"
    for h in measured["hits"]:
        assert h["class"] in ("FATAL", "CLOBBER"), h
        assert h["check_base"][0] != "fail", h   # none is pre-existing: all are ours


#: What the SHIPPED overlay (target pracx_thinker) still shares with Thinker: every one a recorded decision.
#: The four excluded sites hold clean bytes on disk, so Thinker's write there is a plain CLOBBER of the base
#: (uimod.dll writes ours on top afterwards); the five others are the CLOBBERs of the PRACX pin.
THINKER_BAKE_HITS = {sid for _, sid, _ in PINNED_COLLISIONS}


@pytest.fixture(scope="module")
def thinker_bake_img(bak_path, patches_path, tmp_path_factory) -> T.Image:
    """The pracx_thinker overlay applied to the clean base (built once per module; ~1 s)."""
    import shutil
    import apply_patches as ap
    tgt = tmp_path_factory.mktemp("thinker_bake") / "terranx.exe"
    shutil.copy2(bak_path, tgt)
    spec = ap.load_targets(patches_path)["pracx_thinker"]
    assert ap.apply_patches(tgt, patches_path, do_apply=True, spec=spec) == 0
    return T.Image(tgt)


def test_the_thinker_bake_has_no_fatal_collision(thinker, ours, base_img, thinker_bake_img):
    """THE launch guarantee: on the bytes a PRACX + Thinker player actually runs, every Thinker guard passes
    (no exit_fail), and the only shared bytes are the decided ones."""
    sites, caves, _ = ours
    m = T.measure(thinker, sites, caves, base_img, thinker_bake_img, reduced_mode=True)
    fatal = [h for h in m["hits"] if h["class"] == "FATAL"]
    assert not fatal, f"the shipped Thinker overlay would exit_fail at launch: {[h['site']['id'] for h in fatal]}"
    assert m["cave_hits"] == []
    assert {h["site"]["id"] for h in m["hits"]} == THINKER_BAKE_HITS
    for h in m["hits"]:
        assert h["class"] == "CLOBBER", h
    assert {b["write"]["addr"] for b in m["base_fails"]} == BASE_FAILS_V55


def test_report_renders(measured, ours, base_img, patched_img):
    text = T.render(measured, T.summarize(measured, ours[2]), base_img, patched_img, None, T.THINKER_SRC)
    for g in {g for g, _, _ in PINNED_COLLISIONS}:
        assert f"`{g}`" in text
    assert "decides nothing" in text and "smooth_scrolling=0" in text
