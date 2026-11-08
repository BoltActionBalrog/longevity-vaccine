"""uimod lanjoin.cpp end to end on loopback: the REAL LiveEnv (caches, deadlines, probes), Resolve and the
QueryAddress hook against a fake UPnP router and fake peer games (lanjoin_livetest.cpp; no real network, no
DirectPlay).  127.0.0.1 is "the LAN"; the router's public address is 127.0.0.2 where it loops back and 127.0.0.3
where it does not.

The guarantee pinned here: a translation happens only where the router does NOT loop back AND the other machine's
game accepts on its private address -- including the second audit's case (2026-11-07), where a stale mapping to a
dead port after a cache reset used to poison the router-wide verdict and translate on a router that loops back.
One build, one run (~3 s of 500 ms probes); every assertion reads that run's output."""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import cpp_harness  # noqa: E402


@pytest.fixture(scope="module")
def run():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    exe = cpp_harness.build(ROOT / "tests" / "lanjoin_livetest.cpp", "lanjoin_livetest_", "/std:c++17")
    out = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120).stdout
    lines = dict(l.split(" ", 1) for l in out.splitlines() if " " in l)
    game, dead = lines["ports"].split()
    lines["_game"], lines["_dead"] = game, dead
    return lines


def test_no_loopback_translates_and_the_datagram_query_follows(run):
    g = run["_game"]
    assert run["noloop_tcp"] == f"translated 127.0.0.1:{g}"
    assert run["noloop_udp"] == "translated 127.0.0.1:2350"
    assert run["noloop_tcp_again"] == f"translated 127.0.0.1:{g}"      # SERVERNOTAVAILABLE is our case too


def test_a_router_that_loops_back_is_never_translated_and_not_re_probed(run):
    assert run["loops_tcp"] == "router-loops-back"
    assert run["loops_tcp_again"] == "router-loops-back"
    assert run["loops_no_reprobe"] == "0"


def test_a_dead_port_after_a_reset_cannot_poison_the_verdict(run):
    assert run["poison_dead"] == "unreachable"
    assert run["poison_good"] == "router-loops-back"


def test_a_stale_mapping_cannot_yield_no_loopback(run):
    """Third audit (2026-11-07): the mapping was cached while the game was down, then moved to another public port.
    'Does not loop back' needs the mapping read live, a fresh accept and a failed public connect, all in one query."""
    assert run["moved_before"] == "unreachable"
    assert run["moved_stale"] == "loopback-unknown"
    assert run["moved_new"] == "router-loops-back"


def test_an_answer_is_per_port(run):
    assert run["port_a"] == f"translated 127.0.0.1:{run['_game']}"
    assert run["port_dead"] == "unreachable"


def test_gates_that_never_touch_the_network(run):
    assert (run["enum_port"], run["internet"], run["helper_ok"], run["no_soap"]) == (
        "enum-port", "not-router-address", "not-our-case", "0")


def test_a_slow_router_stays_inside_the_budget(run):
    assert run["slow_router"] == "no-mapping in-budget"
    assert run["slow_again"] == "no-mapping"


def test_only_a_known_nat_helper_interface_is_patched(run):
    """Compatibility audit (2026-11-07): another DirectPlay build (Windows 7's, an old redistributable beside the game,
    Wine's) may hand out an interface whose slot 9 is not QueryAddress -- patching it would corrupt the stack."""
    assert run["iid_unknown_patched"] == "0"
    assert run["iid_known_patched"] == "1"


def test_the_hook_on_a_patched_vtable(run):
    assert run["hook"] == f"00000000 127.0.0.1:{run['_game']}"
    assert run["hook_patched"] == "1"
    assert run["hook_internet"] == "8015f050"
