"""timing_plugin keeps what a flake leaves behind: a failed test's message (tail) and, under xdist, the worker that ran
each test -- so a failure that passes on re-run can be read back with `py timing_report.py --failures`."""
import contextlib
from types import SimpleNamespace

import timing_plugin as TP


@contextlib.contextmanager
def _fresh_log():
    """A private _tests for the body only: restored before this test's own call report reaches the real log."""
    saved, enabled = TP._tests, TP._enabled
    TP._tests, TP._enabled = {}, True
    try:
        yield TP._tests
    finally:
        TP._tests, TP._enabled = saved, enabled


def _report(nid, when, outcome, worker=None, text=""):
    node = SimpleNamespace(gateway=SimpleNamespace(id=worker)) if worker else None
    r = SimpleNamespace(nodeid=nid, when=when, outcome=outcome, duration=0.01, longreprtext=text)
    if node:
        r.node = node
    return r


def test_failure_message_and_worker_are_recorded():
    with _fresh_log() as log:
        _feed()
    ok, bad = log["m.py::ok"], log["m.py::bad"]
    assert ok["w"] == bad["w"] == "gw3" and "failure" not in ok
    assert bad["outcome"] == "failed" and bad["failure"].startswith("[call] ")
    assert bad["failure"].endswith("E   assert 1 == 2") and len(bad["failure"]) <= TP.FAILURE_CHARS + 7


def _feed():
    for when in ("setup", "call", "teardown"):
        TP.pytest_runtest_logreport(_report("m.py::ok", when, "passed", "gw3"))
    TP.pytest_runtest_logreport(_report("m.py::bad", "setup", "passed", "gw3"))
    TP.pytest_runtest_logreport(_report("m.py::bad", "call", "failed", "gw3", "x" * 9000 + "E   assert 1 == 2"))


def test_serial_runs_name_no_worker():
    with _fresh_log() as log:
        TP.pytest_runtest_logreport(_report("m.py::t", "call", "passed"))
    assert "w" not in log["m.py::t"]
