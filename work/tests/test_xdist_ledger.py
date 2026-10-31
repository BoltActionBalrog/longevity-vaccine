"""xdist_sched's run ledger: suites started together size their workers against each other, not each against the
same free commit charge (three at once took 64 workers each and died in MemoryError at collection)."""
from __future__ import annotations

import json
import os
import sys

import pytest

import xdist_sched as XS


def test_pending_is_what_other_runs_have_not_committed_yet():
    procs = {10: (1, 0.5), 11: (10, 1.0), 12: (10, 2.0), 20: (1, 0.1), 21: (20, 0.2), 30: (1, 0.0)}
    ledger = {"10": {"gb": 10.0}, "20": {"gb": 0.2}, "30": {"gb": 4.0}, "99": {"gb": 50.0}}
    # 10: 10 - (0.5 + 1 + 2) = 6.5; 20: fully up (0.3 >= 0.2) -> 0; 30 is ME -> skipped; 99 is dead -> skipped
    assert XS.pending_gb(ledger, procs, me=30) == pytest.approx(6.5)
    assert XS._tree_commit_gb(10, procs) == pytest.approx(3.5)


def test_memory_cap_subtracts_the_pending_commit(monkeypatch):
    monkeypatch.setattr(XS, "commit_headroom_gb", lambda: XS.COMMIT_RESERVE_GB + 30 * XS.WORKER_COMMIT_GB)
    assert XS.memory_cap(64) == 30
    assert XS.memory_cap(64, pending_gb=10 * XS.WORKER_COMMIT_GB) == 20
    assert XS.memory_cap(64, pending_gb=1e6) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="the ledger reads the Windows process table")
def test_two_runs_reserving_together_see_each_other(monkeypatch, tmp_path):
    monkeypatch.setattr(XS, "_ledger_path", lambda: tmp_path / XS.LEDGER_NAME)
    monkeypatch.setattr(XS, "commit_headroom_gb", lambda: XS.COMMIT_RESERVE_GB + 100 * XS.WORKER_COMMIT_GB)
    monkeypatch.setattr(XS.atexit, "register", lambda fn: None)
    other = os.getppid()                                     # a live process that is not this one: "another run"
    (tmp_path / XS.LEDGER_NAME).write_text(json.dumps({str(other): {"gb": 1e5}, "4000000000": {"gb": 1e5}}))
    procs = XS._proc_info()
    assert procs and os.getpid() in procs and other in procs
    pend = 1e5 - XS._tree_commit_gb(other, procs)
    n = XS.reserve_workers(lambda pending: XS.memory_cap(64, pending))
    assert n == 1 and pend > 9e4                             # the other run's reservation is pending: we shrink
    led = json.loads((tmp_path / XS.LEDGER_NAME).read_text())
    assert set(led) == {str(other), str(os.getpid())}        # the dead pid is dropped, we are recorded
    assert led[str(os.getpid())]["gb"] == pytest.approx(XS.WORKER_COMMIT_GB)
    XS._ledger_release()
    assert set(json.loads((tmp_path / XS.LEDGER_NAME).read_text())) == {str(other)}
