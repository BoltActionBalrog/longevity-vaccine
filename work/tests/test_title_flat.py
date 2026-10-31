"""Guards for the 2026-09-18 flat popup title (law scaling_laws.title_grow_delta == 0).

* thunk_box_thick_flat is thunk_box_thick with ONLY the Delta computation replaced.
* the popup title pair tails into the flat clone; nobody else does, and thunk_box_thick keeps only
  the diplomacy talk title callers.
* CENSUS: no cave thunk outside the allow-list still computes `(g-16) >> 3` -- a new popup-chain
  compensation against a title grow that no longer exists would be a silent misalignment."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import apply_patches as ap  # noqa: E402
import scaling_laws as SL  # noqa: E402

DELTA_OLD = "83 E8 10 C1 E8 03 8B D8"
DELTA_NEW = "33 DB 90 90 90 90 90 90"

# thunks that legitimately keep a (g-16)>>3 term, and why
ALLOWED = {
    "thunk_box_thick",          # the growing thickener itself (diplomacy talk title)
    "thunk_title_textnudge",    # scaled-text ink centring N = (g-16)/8, not a frame grow
    "thunk_comm_cent5",         # same text nudge
    "t_dp_title_outer", "t_dp_title_inner", "t_dp_title_text",   # diplo rects pre-inset +D against thunk_box_thick
}
DELTA_RE = re.compile(rb"\x83[\xE8-\xEF]\x10\xC1[\xE8-\xEF\xF8-\xFF]\x03")


def _load():
    sites, groups, caves, symbols = ap.load_patches(ROOT / "patches" / "patches.yaml")
    return sites, caves, ap.build_symbol_table(symbols, caves)


def _entries(caves):
    for cave in caves:
        for ent in cave.get("contents") or []:
            yield ent


def test_flat_clone_differs_only_in_the_delta_computation():
    _, caves, _ = _load()
    ents = {e["id"]: e for e in _entries(caves)}
    grow, flat = ents["thunk_box_thick"]["bytes"], ents["thunk_box_thick_flat"]["bytes"]
    assert grow.count(DELTA_OLD) == 1
    assert flat == grow.replace(DELTA_OLD, DELTA_NEW)


def test_title_pair_tails_into_the_flat_clone():
    _, caves, _ = _load()
    users_flat = {e["id"] for e in _entries(caves) if "thunk_box_thick_flat}" in str(e.get("bytes", ""))}
    users_grow = {e["id"] for e in _entries(caves) if "thunk_box_thick}" in str(e.get("bytes", ""))}
    # 2026-10-24 W1A fix 25b: the pair reaches the flat clone through t_band_bdraw (law title_band_draw_rect: a copy
    # of the band rect with b - 1), which calls / tail-jumps it
    users_band = {e["id"] for e in _entries(caves) if "t_band_bdraw}" in str(e.get("bytes", ""))}
    assert users_band == {"thunk_inner_margin", "thunk_pf_title_stash"}
    assert users_flat == {"t_band_bdraw"}
    # the diplomacy talk title (t_dp_title_outer/inner) calls thunk_box_thick through HARDCODED rel32s
    # (built-exe census 2026-09-18), so no placeholder user is left
    assert users_grow == set()


def test_no_stray_title_grow_compensation_in_any_cave():
    _, caves, st = _load()
    hits = set()
    for ent in _entries(caves):
        if ent.get("data") or "bytes" not in ent:
            continue
        try:
            b = ap.ByteTemplate(ent["bytes"]).resolve(st[ent["id"]], st)
        except Exception:
            continue
        if DELTA_RE.search(b):
            hits.add(ent["id"])
    assert hits == ALLOWED, hits ^ ALLOWED


def test_law_is_zero_and_the_flat_chain_is_vanilla_proportionate():
    for g in range(16, 41):
        assert SL.title_grow_delta(g) == 0
        t_l, t_r = 67, 1932
        # body ring flush with the title RECT (== its drawn stroke now); field one channel inside
        assert SL.body_outer_edge_r(t_r, g) == t_r and SL.body_outer_edge_l(t_l, g) == t_l
        assert SL.body_inner_edge_r(t_r, g) == t_r - SL.popup_pad(3, g)
        if g > 16:
            # vertical: every family takes the engine arm; art top lands on the ring top
            t_src = SL.popup_pad(38, g)
            T = SL.popup_field_top(t_src, SL.popup_pad(28, g), 0, True, g)
            assert T == t_src - SL.popup_pad(3, g)
            assert SL.popup_art_y(SL.flat_art_anchor(T, g), 0, g) - 6 == T - SL.nested_frame_pad(g, body_only=True)
            # vanilla rows (pristine QuitWithComMenu.png): ring top 32, field top 35 -- within the floor cascade
            assert abs((T - SL.popup_pad(3, g)) - (32 * g) / 16) <= 1.5, g
            assert abs(T - (35 * g) / 16) <= 1.5, g
