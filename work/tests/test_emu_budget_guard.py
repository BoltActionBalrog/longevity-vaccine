"""No emulation may be budgeted by a wall clock that machine load can trip.

Unicorn's `emu_start(..., timeout=us)` stops after `us` microseconds of WALL time and returns as if nothing happened.
The suite runs beside other suites, emulator jobs and agents (64 workers each), and a run that finishes in 1 s alone
took over 5 s there: at least 20 sites had a 1-20 s timeout, and the council / art-reblit rigs (5 s) failed under
load with `None == RET_SITE` while passing alone (2026-10-25, w7F).  Two budgets are deterministic:

  * an instruction `count` -- the same stop on every machine (it instruments every instruction: slower), or
  * a wall-clock HANG bound no load can reach (>= MIN_HANG_US) with the end marker deciding pass/fail -- the
    test asserts the run reached its `until` (or its documented other exit), so a cut-short run fails loudly.

This guard fails any literal `timeout=` in an `emu_start` call (keyword or 3rd positional) that is nonzero and below
MIN_HANG_US.  A name (council_mirror_emu.BUDGET_US) is not evaluated: such a constant carries its own rationale.
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MIN_HANG_US = 600_000_000          # 10 minutes: a hang bound, never a measurement


@functools.lru_cache(maxsize=1)
def _timeouts() -> tuple:
    return tuple(_scan())


def _scan():
    for p in sorted(ROOT.rglob("*.py")):
        if "timings" in p.parts or "__pycache__" in p.parts:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "emu_start" not in text:
            continue
        for n in ast.walk(ast.parse(text, str(p))):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "emu_start":
                arg = next((k.value for k in n.keywords if k.arg == "timeout"), n.args[2] if len(n.args) > 2 else None)
                if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
                    yield f"{p.relative_to(ROOT)}:{n.lineno}", arg.value


def test_no_emulation_is_cut_short_by_a_wall_clock():
    bad = [f"{site} timeout={v}" for site, v in _timeouts() if 0 < v < MIN_HANG_US]
    assert not bad, ("a wall-clock emulation budget that machine load can trip (use an instruction `count`, or a "
                     f"hang bound >= {MIN_HANG_US} us with an end-marker check):\n  " + "\n  ".join(bad))


def test_the_guard_sees_the_sites():
    """The scan is not vacuous: it finds the literal hang bounds the rigs carry."""
    assert sum(1 for _s, v in _timeouts() if v >= MIN_HANG_US) >= 5
