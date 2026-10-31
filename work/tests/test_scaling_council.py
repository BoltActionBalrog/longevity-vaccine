"""Council-screen scaling laws — sweep + g=16 identity goldens.

Goldens are the frida_council_trace.log 2026-08-21 values (1024x768, g=16,
live exe = native no-op) — the measured VANILLA, per the proportionate rule.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import scaling_laws as SL  # noqa: E402

GS = list(range(16, 41))


# ---- g=16 identity: the trace table verbatim --------------------------------

def test_window_identity():
    assert SL.council_window_rect(1024, 768, 213, 16) == (122, 160, 812, 395)


def test_seed_identity():
    s = SL.council_seed_rects(16)
    assert s["banner"] == (245, 355, 538, 378)
    assert s["params"] == (30, 750, 27)
    assert s["outer"][0] == (30, 53, 128, 335)
    assert s["outer"][1] == (130, 45, 228, 327)
    assert s["outer"][2] == (230, 37, 328, 319)
    assert s["outer"][3] == (330, 29, 450, 352)
    assert s["outer"][4] == (452, 37, 550, 319)
    assert s["outer"][5] == (552, 45, 650, 327)
    assert s["outer"][6] == (652, 53, 750, 335)
    assert s["inner"] == [(32, 29, 130, 311), (135, 29, 233, 311),
                          (238, 29, 336, 311), (341, 29, 439, 311),
                          (444, 29, 542, 311), (547, 29, 645, 311),
                          (650, 29, 748, 311)]


def test_button_row_identity():
    # conRect @1024 = (262,66,763,172); trace: box (266,70,759,168),
    # text bottom 142, full (269,145,756,165), thirds L 269/432/595 R 429/592/755.
    r = SL.council_button_row((262, 66, 763, 172), 16)
    assert r["box"] == (266, 70, 759, 168)
    assert r["text_bottom"] == 142
    assert r["full"] == (269, 145, 756, 165)
    assert r["thirds"] == [(269, 145, 429, 165), (432, 145, 592, 165),
                           (595, 145, 755, 165)]


def test_chip_identity():
    # inner col0 (32,29,130,311) -> chip (36,287,126,307), votes (36,267,126,287)
    c = SL.council_chip_rects((32, 29, 130, 311), 16)
    assert c["chip"] == (36, 287, 126, 307)
    assert c["votes"] == (36, 267, 126, 287)


def test_backdrop_identity():
    assert SL.council_backdrop_rect(812, 395, 16) == (23, 0, 757, 396)


def test_misc_identity():
    assert SL.council_text_y(29, 115, 16) == 149          # T+1+115+4
    # logo faction1 @g16: inner col0, canvas 86 -> x=38 (trace [spr] x=38)
    assert SL.council_logo_x(32, 130, 86, 16) == 38
    assert SL.council_sd2_pre(33, 0, 16) == 33


# ---- sweep properties -------------------------------------------------------

def test_seed_sweep():
    for g in GS:
        s = SL.council_seed_rects(g)
        w = SL.dp(98, g)
        for name in ("outer", "inner"):
            cols = s[name]
            for i, (l, t, r, b) in enumerate(cols):
                if not (name == "outer" and i == 3):
                    assert r - l == w, (name, i, g)          # pinned width
                assert b > t and r > l
            # no adjacent overlap (columns never butt)
            for a, b2 in zip(cols, cols[1:]):
                assert b2[0] >= a[2], (name, g)
        # every rect inside the window box
        win_w, win_h = SL.dp(812, g), SL.dp(395, g)
        for (l, t, r, b) in s["outer"] + s["inner"] + [s["banner"]]:
            assert 0 <= l and r <= win_w, (g, l, r, win_w)
            assert 0 <= t, (g, t)
            assert b <= win_h + 1, (g, b, win_h)  # vanilla B=352 < 395 holds scaled


def test_chip_sweep():
    for g in GS:
        s = SL.council_seed_rects(g)
        for inner in s["inner"]:
            c = SL.council_chip_rects(inner, g)
            l, t, r, b = c["chip"]
            assert inner[0] < l and r < inner[2], g       # chip inside column
            assert t > inner[1] and b < inner[3], g
            assert b - t == SL.dp(0x17, g) - SL.dp(3, g), g  # chip height law
            v = c["votes"]
            assert v[3] <= t, g                            # label above chip


def test_button_row_sweep():
    # conRect scales ~ device (HUD-baked); model it as vanilla x g/16
    for g in GS:
        con = tuple(SL.dp(v, g) for v in (262, 66, 763, 172))
        r = SL.council_button_row(con, g)
        box = r["box"]
        assert box[0] < box[2] and box[1] < box[3], g
        full = r["full"]
        assert box[0] < full[0] and full[2] < box[2], g
        assert full[3] < box[3] + 1, g
        th = r["thirds"]
        # thirds ordered, non-overlapping, inside the box (pull-in only)
        assert th[0][0] == full[0] and th[2][2] <= box[2], g
        for a, b2 in zip(th, th[1:]):
            assert b2[0] > a[2], g
        # button band height = full row height everywhere
        for t in th:
            assert t[3] - t[1] == full[3] - full[1], g


def test_window_sweep():
    # (SW, SH, strip) triples: strip = dp(213) model
    for sw, sh, g in ((1024, 768, 16), (1920, 1080, 22),
                      (1600, 1200, 25), (3840, 2160, 40)):
        strip = SL.dp(213, g)
        x, y, w, h = SL.council_window_rect(sw, sh, strip, g)
        assert w == SL.dp(812, g)
        assert h <= SL.dp(395, g)
        assert x >= 0 and y >= 0, (sw, sh, g)
        assert y + h + strip <= sh, (sw, sh, g)
        # window horizontally on-screen
        assert x + w <= sw + SL.dp(32, g), (sw, sh, g)  # vanilla overhang 812-780=32


def test_sd2_pre_sweep():
    # content lands within 1px of target at every g, exact at g=16
    for g in GS:
        for target in range(0, 3000, 37):
            for off in (0, 5, 7, 12):
                x = SL.council_sd2_pre(target, off, g)
                drawn = ((x + off) * g) >> 4
                assert abs(drawn - target) <= 1, (g, target, off)
                if g == 16:
                    assert drawn == target


def test_logo_x_sweep():
    for g in GS:
        s = SL.council_seed_rects(g)
        for inner in s["inner"]:
            for cw in (62, 72, 74, 76, 84, 86):
                x = SL.council_logo_x(inner[0], inner[2], cw, g)
                # scaled logo fits inside the column frame
                assert x >= inner[0], (g, cw)
                assert x + SL.dp(cw, g) <= inner[2] + 1, (g, cw)


def test_castvote_art_x_compensation():
    # v3 LAW (2026-10-14): the seeds are ALREADY DEVICE (never rescaled: the run-8
    # double-scale regression); only thunk_sprite_draw's NATIVE x-5 offset is
    # compensated, x' = x - ((5g>>4)-5): 7 @g40, 2 @g25, 1 @g22, 0 at g<=16 --
    # the measured right-shift of the flag vs BadCastVote.png (frame- and row-relative).
    for g in GS:
        for xy in ((47, 117), (39, 41), (5, 6), (0, 0)):
            comp = 0 if g <= 16 else (5 * g >> 4) - 5
            assert SL.council_castvote_art(xy[0], xy[1], g)[0] == xy[0] - comp, (g, xy)
    assert [SL.council_castvote_art(47, 117, g)[0] for g in (40, 25, 22, 16)] == [40, 45, 46, 47]


def test_castvote_art_y_compensation():
    # v2 LAW: thunk_sprite_draw applies the NATIVE y-6 draw offset to the
    # DEVICE seed, so the stub pre-subtracts dp(6)-6 (0 at g<=16); the drawn
    # art_top then equals y_dev - dp(6).  Measured 2026-08-23: build
    # aaeb05d5 flag 9 dev px low @g40 vs BadCastVote.png, both band-gap and
    # row-gap relations restored exactly by +9.
    for g in GS:
        for xy in ((47, 117), (39, 41), (5, 6), (0, 0)):
            comp = 0 if g <= 16 else (6 * g >> 4) - 6
            assert SL.council_castvote_art(xy[0], xy[1], g)[1] == xy[1] - comp, (g, xy)
    assert SL.council_castvote_art(47, 117, 40) == (40, 108)   # x: 7, y: dp(6,40)-6 = 9
    assert SL.council_castvote_art(47, 117, 25) == (45, 114)   # x: 2, y: dp(6,25)-6 = 3
    assert SL.council_castvote_art(47, 117, 22) == (46, 115)   # x: 1, y: dp(6,22)-6 = 2
    assert SL.council_castvote_art(47, 117, 16) == (47, 117)   # native no-op


def test_castvote_art_run8_regression():
    # the exact run-8 measured seeds @g40: NOT the dp(seed-5)+5 double-scale
    assert SL.council_castvote_art(47, 117, 40) != (SL.dp(42, 40) + 5, SL.dp(111, 40) + 6)


# ---- council TALK popups (v25): textfollow gate + ornate art x ---------------

def test_textfollow_gate_matches_frame_align():
    # LAW A: one gate, one stash — textfollow applies iff frame_align applies.
    for g in GS:
        for raw in (0, 50000, 20000, 60000, 10000000):
            assert SL.popup_textfollow_applies(raw, 0, 0, g) == (
                g > 16 and SL.popup_frame_rewrite_applies(raw)), (g, raw)
    # run-24 regression: the ornate University popup (60000, no art) must
    # NOT take the stale g_d528_left (it drew X=372 = the PD popup's 51+321)
    assert not SL.popup_textfollow_applies(60000, 0, 0, 25)
    # art popups and external-window popups never take it (baked v2 gates)
    assert not SL.popup_textfollow_applies(0, 0x78f4a4, 0, 25)
    assert not SL.popup_textfollow_applies(0, 0, 0x733990, 25)


def test_art_x_identity_g16():
    for raw in (0, 60000):
        for bl in (27, 15, 41, 6):
            assert SL.popup_art_x(bl, raw, 16) == bl + 5      # drawn = bandL, native law
            assert SL.popup_art_y(29, raw, 16) == 35


def test_art_x_flat_unchanged():
    # the baked v5 Quit law, user-approved 4K/1600/1920 — ornate delta must
    # not leak into the flat/slide family
    for g in GS:
        assert SL.popup_art_x(27, 0, g) == (27 + 5 + (g >> 4) if g > 16 else 32), g
        assert SL.popup_art_x(27, 50000, g) == SL.popup_art_x(27, 0, g)


def test_art_x_ornate_run24():
    # run 24 @g25: bandL stash 15, art drawn at 16 while the ornate band
    # stroke was measured at 22-23 (= 15 + ornate_title_inset_delta(25) = 7)
    assert SL.ornate_title_inset_delta(25) == 7
    # 2026-09-18 (title draws FLAT): the band stroke is AT its rect (22-23), the art adjacent at 24
    assert SL.popup_art_x(15, 60000, 25) == 15 + 7 + 5 + 2          # seed 29 -> drawn 24
    assert SL.popup_art_x(15, 60000, 25) - 5 == 15 + SL.ornate_title_inset_delta(25) + 2
    # y (2026-09-18, title_grow_delta == 0): both families = anchor - ps3 + 6 -> art top ON the ring top
    assert SL.popup_art_y(62, 0, 25) == 64
    assert SL.popup_art_y(62, 60000, 25) == 64
    assert SL.popup_art_ornate_x_adjust(25) == 1 and SL.popup_art_ornate_x_adjust(40) == 1
    for g in GS:
        # the ornate art frame sits ceil(g/16) - delta right of the MOVED band rect
        # (= adjacent to the stroke thunk_box_thick grows delta outward); @g25 that
        # equals the flat relation (g>>4), the user-approved run-26 look
        moved = 15 + (SL.ornate_title_inset_delta(g) if g > 16 else 0)
        want = moved + (((g + 15) >> 4) - SL.title_grow_delta(g) if g > 16 else 0)
        assert SL.popup_art_x(15, 60000, g) - 5 == want, g
        # ornate art top == ornate field drawn top (anchor - ps3) at every scaled g
        # (native: the engine's own seeds, identity y = anchor + 6)
        if g > 16:
            assert SL.popup_art_y(69, 60000, g) - 6 == 69 - SL.popup_pad(3, g), g
        else:
            assert SL.popup_art_y(69, 60000, g) == 75


def test_field_top_ornate_probe_vectors():
    # ornate family = ENGINE arm: run 25/26 @g25 t_src 73 -> 69 (user-approved); 4K probe t_src 117 -> 110
    assert SL.popup_field_top(73, 57, 60000, True, 25) == 69
    assert SL.popup_field_top(117, 92, 60000, True, 40) == 110
    # the title band (law ornate_title_rect) is what moved: s(13)/s(37) from the engine top; R on the half-open
    # axis since fix 26 v2 (ORNATE_HALF_OPEN: was 1067 / 1709)
    assert SL.ornate_title_engine_top(25) == 15 and SL.ornate_title_rect(15, 15, 1072, 25) == (20, 20, 1066, 57)
    assert SL.ornate_title_engine_top(40) == 19 and SL.ornate_title_rect(19, 19, 1722, 40) == (32, 32, 1708, 92)
    assert SL.ornate_title_outer_bottom(15, 25) == 57 and SL.ornate_title_outer_bottom(19, 40) == 92
    assert SL.ornate_title_outer_bottom(13, 16) == 37                    # native identity
    # 4K chain: flat band stroke ends ON row 92 (inclusive footprint), union top 110-7 = 103 -> 10 clear rows
    # == vanilla's 4 (rows 37..40 between the half-open band bottom 37 and the ring top 41) x 2.5
    assert (110 - 7) - (92 + 1) == 10
    # the portrait rides the anchor: ornate art top == union drawn top (anchor - ps3)
    assert SL.popup_art_y(69, 60000, 25) - 6 == 69 - SL.popup_pad(3, 25)
    # flat/slide: the band-anchored arm is GONE (2026-09-18) -- engine arm 59 - ps3
    assert SL.popup_field_top(59, 43, 0, True, 25) == 55
    assert SL.popup_field_top(59, 43, 50000, True, 25) == 55
    # unkeyed popups: default arm
    assert SL.popup_field_top(59, 43, 0, False, 25) == 55


def test_field_top_identity_and_gate():
    for g in GS:
        # native: vanilla's ebx-3 for every family
        if g == 16:
            for raw in (0, 50000, 60000):
                assert SL.popup_field_top(47, 37, raw, True, g) == 44
            continue
        engine_arm = 47 - SL.popup_pad(3, g)
        # every family, keyed or not == the engine arm (the flat band arm died with the title grow)
        for raw in (0, 50000, 20000, 60000):
            assert SL.popup_field_top(47, 37, raw, True, g) == engine_arm, (g, raw)
            assert SL.popup_field_top(47, 37, raw, False, g) == engine_arm, (g, raw)


def test_field_right_src_ornate_run26():
    # run 26 @g25: '' popup box 1087, band pre-shift R 1072 -> engine ecx
    # 1063 (1072 - 9 native) -> field R 1067 / union 1071, measured 6px
    # right of the band inner/outer strokes (1061-1062 / 1065-1066).
    ecx = SL.popup_field_right_src_ornate(1072, 25)
    assert ecx == 1057
    r_drawn = 1072 - SL.ornate_title_inset_delta(25)                  # 1065
    assert ecx + SL.popup_pad(3, 25) == r_drawn - SL.popup_pad(3, 25) + SL.title_grow_delta(25)  # field R 1062 == inner
    assert ecx + 2 * SL.popup_pad(3, 25) == r_drawn + SL.title_grow_delta(25)                     # union R 1066 == outer
    # University / ELIGIBLE (box 1084, pre R 1069)
    assert SL.popup_field_right_src_ornate(1069, 25) == 1054


def test_field_right_src_ornate_identity_and_sweep():
    # native: band pre R = winR - 13 (9+3+1), vanilla ecx = winR - 10 - 9
    for w in (696, 693, 637):
        assert SL.popup_field_right_src_ornate(w - 13, 16) == w - 19
    for g in GS:
        w = SL.dp(696, g)
        pre_r = w - 9 - SL.popup_pad(3, g) - 2            # the engine chain as probed (@g25: 1072)
        ecx = SL.popup_field_right_src_ornate(pre_r, g)
        ps3, delta = SL.popup_pad(3, g), SL.title_grow_delta(g)
        r_drawn = pre_r - (SL.ornate_title_inset_delta(g) if g > 16 else 0)
        field_r, union_r = ecx + ps3, ecx + 2 * ps3
        # drawn relations: field == band inner (+delta grow), union == band outer (+delta grow)
        assert field_r == r_drawn - ps3 + delta, g
        assert union_r == r_drawn + delta, g
        # field strictly inside the band outer rect; never wider than the old native-9 arm @g16
        assert field_r < r_drawn or g == 16, g
        if g == 16:
            assert ecx == pre_r - 6
    # the naive "scale the 9" arm drifts off the band (why the law anchors to it): 1px @g25 since the title draws flat
    pre25 = SL.dp(696, 25) - 9 - SL.popup_pad(3, 25) - 2
    assert SL.popup_field_right_src_ornate(pre25, 25) == pre25 + 9 + 2 + SL.popup_pad(3, 25) - SL.popup_pad(10, 25) - SL.popup_pad(9, 25) - 1
    pre40 = SL.dp(696, 40) - 9 - SL.popup_pad(3, 40) - 2
    assert SL.popup_field_right_src_ornate(pre40, 40) != pre40 + 9 + 2 + SL.popup_pad(3, 40) - SL.popup_pad(10, 40) - SL.popup_pad(9, 40)
