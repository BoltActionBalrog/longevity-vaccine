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
        assert re.search(rf'^    \{{ "{re.escape(sid)}", .*kExcluded \}},$', generated, re.M), sid
    for sid in G.RESTORE_SITES:
        assert re.search(rf'^    \{{ "{re.escape(sid)}", .*kRestore \}},$', generated, re.M), sid


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
