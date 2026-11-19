"""src\\uimod\\src\\thinker_sites.h is GENERATED from patches.yaml + Thinker's source + the baked cave bytes
(work\\scripts\\gen_thinker_sites.py). The DLL must never carry a private, drifting copy of the yaml: this module
regenerates the header and fails when the checked-in one differs, and pins the shape the DLL's loop relies on.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import apply_patches as ap  # noqa: E402
import gen_thinker_sites as G  # noqa: E402
import thinker_overlap as T  # noqa: E402


@pytest.fixture(scope="module")
def generated(need_local, bak_path, patches_path) -> str:
    need_local(T.THINKER_SRC / "patch.cpp", "the Thinker source clone (refs/thinker)")
    return G.build(patches_path, bak_path, T.THINKER_SRC)


def test_the_checked_in_header_is_current(generated):
    assert G.HEADER.is_file(), f"missing {G.HEADER}: run gen_thinker_sites.py"
    cur = G.HEADER.read_text(encoding="utf-8")
    assert cur == generated, (
        f"{G.HEADER.name} is stale (patches.yaml, Thinker's source or the cave bytes changed): "
        f"regenerate with  py work\\scripts\\gen_thinker_sites.py")


def test_header_covers_exactly_the_decided_sites(generated, patches_path):
    spec = ap.load_targets(patches_path)["pracx_thinker"]
    ids = re.findall(r'^    \{ "([^"]+)", 0x[0-9a-f]{8}, \d+, k_', generated, re.M)
    chains = re.findall(r'^    \{ "([^"]+)", 0x[0-9a-f]{8}, 0x[0-9a-f]{8}, k_', generated, re.M)
    assert set(ids) == set(spec.exclude_sites) | set(G.RESTORE_SITES)
    assert set(chains) == set(G.CHAIN_SITES)
    assert f"static const uint32_t kNumSites = {len(ids)};" in generated
    assert f"static const uint32_t kNumChains = {len(chains)};" in generated
    for sid in spec.exclude_sites:
        # an excluded site that is a MINIMUM (an immediate raised only when smaller) carries its own mode
        mode = "kMinImm32" if sid in G.MIN_IMM32_SITES else "kExcluded"
        assert re.search(rf'^    \{{ "{re.escape(sid)}", .*{mode} \}},$', generated, re.M), sid
    for sid in G.RESTORE_SITES:
        assert re.search(rf'^    \{{ "{re.escape(sid)}", .*kRestore \}},$', generated, re.M), sid
    assert set(G.MIN_IMM32_SITES) <= set(spec.exclude_sites)


def test_every_site_names_its_group_and_every_code_site_its_destinations(generated, patches_path):
    """What the DLL's all-or-nothing rule and its "is our code really there" check read (thinkersites_core.h)."""
    sites, _groups, _caves, _symbols = G._quiet_load(patches_path)
    # patches.yaml also has standalone sites (no group); the table holds only sites Thinker writes into, and each of
    # those must name its group (test_no_standalone_site_collides_with_thinker)
    group_of = {s["id"]: s.get("group") for s in sites}
    rows =re.findall(r'^    \{ "([^"]+)", 0x[0-9a-f]{8}, \d+, k_\w+, k_\w+, k_\w+, \d+, "([^"]+)", (\w+), (\d+), (\w+), (\d+), (k\w+) \},$',
                      generated, re.M)
    assert len(rows) == len(set(ap.load_targets(patches_path)["pracx_thinker"].exclude_sites) | set(G.RESTORE_SITES))
    for sid, group, dest, ndest, guard, nguard, mode in rows:
        assert group_of[sid] and group == group_of[sid], sid
        if mode == "kMinImm32":
            assert (dest, ndest) == ("nullptr", "0") and int(nguard) == len(G.MIN_IMM32_SITES[sid]) and guard != "nullptr", sid
        else:
            assert int(ndest) >= 1 and dest != "nullptr" and (guard, nguard) == ("nullptr", "0"), \
                f"{sid}: our bytes call or jump somewhere; the DLL must be able to check our code is there"
    assert f"struct Dest {{ uint32_t va; uint8_t bytes[{G.DEST_BYTES}]; }};" in generated


@pytest.fixture(scope="module")
def thinker_spans(need_local, bak_path) -> tuple[list[int], list[int], int]:
    """Every byte span Thinker can write in reduced mode, sorted by start: (starts, ends, widest span). Built ONCE --
    asking _thinker_windows per site rescans all ~8000 writes for each of ~1450 sites (183 s serial)."""
    need_local(T.THINKER_SRC / "patch.cpp", "the Thinker source clone (refs/thinker)")
    thinker = T.load_thinker(T.THINKER_SRC)
    base = T.Image(bak_path)
    known = T.forced_options(thinker.get("assigns", []), True)
    spans = sorted((w.addr, w.addr + T.footprint(w, base)) for w in thinker["writes"]
                   if w.gating(True, known)[0] != "never")
    return [a for a, _ in spans], [b for _, b in spans], max(b - a for a, b in spans)


def test_no_standalone_site_collides_with_thinker(patches_path, thinker_spans):
    """Reduced mode skips a GROUP (thinkersites_core.h): a site Thinker writes into must have one. patches.yaml's
    standalone sites (no group, e.g. Sprite_draw_2.portrait_avg_detour) are fine only while none of them does;
    gen_thinker_sites.build refuses such a site, and this pins it independently of the generator."""
    from bisect import bisect_left
    starts, ends, widest = thinker_spans
    sites, _groups, _caves, _symbols = G._quiet_load(patches_path)

    def written_into(s) -> bool:              # the overlap _thinker_windows uses: w < va + ln and va < w + fp
        va, ln = int(s["virtual_addr"]), int(s["length"])
        lo, hi = bisect_left(starts, va - widest + 1), bisect_left(starts, va + ln)
        return any(ends[i] > va for i in range(lo, hi))

    hit = [s for s in sites if "length" in s and written_into(s)]
    assert hit, "the measurement must see Thinker's collisions at all, or this proves nothing"
    assert [s["id"] for s in hit if not s.get("group")] == []
    standalone = [s for s in sites if not s.get("group")]
    assert standalone, "patches.yaml has standalone sites: the generator and the DLL must tolerate them"
    # the table's rows are sites Thinker writes into: the fast measure must agree with the generator's on them
    rows = set(ap.load_targets(patches_path)["pracx_thinker"].exclude_sites) | set(G.RESTORE_SITES)
    assert rows <= {s["id"] for s in hit}, sorted(rows - {s["id"] for s in hit})


def test_every_excluded_site_has_a_thinker_window_and_the_chains_end_in_the_engine(generated):
    """A site with no Thinker write inside it has no business in the table; a chain whose core does not enter
    the engine function exactly once cannot be re-pointed."""
    assert "kScient, 0x10" in generated, "the Design Workshop byte: Scient writes 0x10 where we write 0x20"
    assert generated.count("kCall, 0x00") == 4, "three excluded write_call windows + the restored one"
    assert "0x005dac70 }," in generated and "0x005dcea0 }," in generated   # Buffer_set_font / Buffer_write_l_3
    for m in re.finditer(r'^    \{ "([^"]+)", 0x[0-9a-f]{8}, 0x[0-9a-f]{8}, k_\w+, (\d+), (\d+), 0x[0-9a-f]{8}, k_\w+, (\d+), k_\w+, (\d+), (0x[0-9a-f]+), (0x[0-9a-f]{8}) \},$',
                         generated, re.M):
        sid, thunk_len, prelude, core_len, nfix, tail, native = m.groups()
        assert int(thunk_len) == int(prelude) + 5, f"{sid}: the thunk must end in a 5-byte jmp"
        assert int(tail, 16) < int(prelude) + int(core_len), sid
        assert int(nfix) >= 1, sid
