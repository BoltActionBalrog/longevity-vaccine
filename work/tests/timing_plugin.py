"""Per-test timing log for every pytest run of this suite (pre-commit, release gate, by hand).

Records, for each run, every test's setup/call/teardown seconds and every module's collection
(import) seconds, to `timings/` beside this file (gitignored):

    timings/runs/<YYYYmmdd-HHMMSS>-<pid>.json   one file per run, the newest KEEP_RUNS kept
    timings/history.jsonl                       one summary line per run
    .git/smacx-test-costs.json                  each test's newest cost, shared by every worktree --
                                                xdist_sched.py plans runs from it (costs_file())

Read them with `py timing_report.py` (slowest tests / modules / collection, run history).

Cost: the test durations are the ones pytest already measures for every report
(`TestReport.duration`), so per test this adds one dict update. Collection adds two
perf_counter() calls per module. The files are written once, at session end.
Disable with SMACX_TIMINGS=0.

Session-scoped fixtures are billed to the SETUP of the first test that requests them -- that is
where their cost actually lands, so a large setup on one test usually means an expensive fixture.

Under pytest-xdist the controller writes the log: test reports reach it as usual, and each
worker hands over its collection times at shutdown (pytest_testnodedown). Per-test times are
then measured under contention, so compare a module across runs with the same worker count.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

TIMINGS_DIR = Path(__file__).resolve().parent / "timings"
KEEP_RUNS = 40

_enabled = os.environ.get("SMACX_TIMINGS", "1") != "0"
_tests: dict[str, dict] = {}
_collect: dict[str, float] = {}
_t0 = 0.0
_t_collected = 0.0


def _is_xdist_worker(config) -> bool:
    return hasattr(config, "workerinput")


def pytest_sessionstart(session):
    global _t0
    _t0 = time.perf_counter()


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    if not _enabled or not isinstance(collector, pytest.Module):
        yield
        return
    t = time.perf_counter()
    yield
    _collect[collector.nodeid] = round(time.perf_counter() - t, 4)


def pytest_collection_finish(session):
    global _t_collected
    _t_collected = time.perf_counter()


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error):
    """xdist controller: a worker's collection times arrive with its shutdown (only FAILED collect reports are
    forwarded, so they cannot ride on those)."""
    for k, v in getattr(node, "workeroutput", {}).get("smacx_collect", {}).items():
        _collect[k] = max(v, _collect.get(k, 0.0))      # every worker imports every module: keep the slowest


def _nodeid(report) -> str:
    """Without xdist's `@<group>` suffix (--dist loadgroup), so serial and parallel runs compare."""
    nid = report.nodeid
    mod = nid.split("::", 1)[0]
    return nid[:-len(mod) - 1] if nid.endswith("@" + mod) else nid


def pytest_runtest_logreport(report):
    if not _enabled:
        return
    nid = _nodeid(report)
    rec = _tests.get(nid)
    if rec is None:
        rec = _tests[nid] = {"setup": 0.0, "call": 0.0, "teardown": 0.0, "outcome": ""}
    rec[report.when] = round(report.duration, 4)
    # The outcome that matters: a failed/skipped setup, else the call's.
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed") \
            or (report.when == "teardown" and report.outcome == "failed"):
        # pytest reports an xfail as "skipped" and an xpass as "passed"; name them.
        xfail = hasattr(report, "wasxfail")
        rec["outcome"] = ("xfailed" if report.outcome == "skipped" else "xpassed") if xfail else report.outcome


def _prune(runs: Path) -> None:
    """Keep the newest KEEP_RUNS runs -- and always the newest WHOLE-suite one (most tests), which timing_report
    shows by default: a day of pre-commit `-k scaling` runs must not evict it."""
    files = sorted(runs.glob("*.json"))
    if len(files) <= KEEP_RUNS:
        return
    best, best_n = None, -1
    try:
        for line in (TIMINGS_DIR / "history.jsonl").read_text(encoding="utf-8").splitlines():
            s = json.loads(line)
            if s.get("n_tests", 0) >= best_n and (runs / f"{s['run']}.json").is_file():
                best, best_n = s["run"], s["n_tests"]
    except (OSError, ValueError, KeyError):
        pass
    for old in files[:-KEEP_RUNS]:
        if old.stem != best:
            old.unlink(missing_ok=True)


def _git_common_dir(start: Path) -> Path | None:
    """The repository's shared .git directory -- the same one for the main checkout and every worktree -- found
    without running git. None outside a git checkout."""
    for d in (start, *start.parents):
        dot = d / ".git"
        if dot.is_dir():
            return dot
        if dot.is_file():                        # a worktree: "gitdir: <main>/.git/worktrees/<name>"
            try:
                gitdir = Path(dot.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip())
                common = (gitdir / "commondir").read_text(encoding="utf-8").strip()
                return (gitdir / common).resolve()
            except (OSError, IndexError):
                return None
    return None


def costs_file() -> Path:
    """Where the cost table lives: in the repository's shared .git directory, so the main checkout and every
    worktree plan from the same measurements (a fresh worktree has no timings/ of its own, and with nothing
    measured its heavy modules ran unsplit: 395 s instead of ~2 min). timings/costs.json outside git;
    SMACX_COSTS_FILE overrides."""
    env = os.environ.get("SMACX_COSTS_FILE")
    if env:
        return Path(env)
    common = _git_common_dir(Path(__file__).resolve().parent)
    return common / "smacx-test-costs.json" if common else TIMINGS_DIR / "costs.json"


def read_costs() -> dict[str, list[float]]:
    """{nodeid: [setup_s, total_s]}, each test's NEWEST real measurement -- which xdist_sched.py reads to size and
    order a run's work. Built from this checkout's kept runs when the table does not exist yet."""
    try:
        costs = json.loads(costs_file().read_text(encoding="utf-8"))
        if isinstance(costs, dict):
            return costs
    except (OSError, ValueError):
        pass
    costs = {}
    for old in sorted((TIMINGS_DIR / "runs").glob("*.json")):          # oldest first: newest wins
        try:
            for k, v in json.loads(old.read_text(encoding="utf-8"))["tests"].items():
                if not (v["outcome"] == "skipped" and k in costs):
                    costs[k] = [v["setup"], v["total"]]
        except (OSError, ValueError, KeyError):
            continue
    return costs


def _update_costs(tests: dict) -> None:
    """Fold this run into the cost table. Every checkout writes the same table, so entries are never pruned by
    THIS checkout's files (another branch may still have them). Concurrent runs may lose each other's update:
    harmless."""
    path = costs_file()
    costs = read_costs()
    for k, v in tests.items():
        # an interrupted test has no full measurement; a SKIP (a missing asset, a gated platform) measures nothing
        # but the skip, so it never replaces what the test cost when it ran
        if v["outcome"] and not (v["outcome"] == "skipped" and k in costs):
            costs[k] = [v["setup"], v["total"]]
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(costs, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def pytest_sessionfinish(session, exitstatus):
    if not _enabled:
        return
    if _is_xdist_worker(session.config):        # hand collection times to the controller (pytest_testnodedown)
        session.config.workeroutput["smacx_collect"] = _collect
        return
    if not _tests:                               # --collect-only, or nothing selected: no run to log
        return
    end = time.perf_counter()
    workers = n if isinstance(n := getattr(session.config.option, "numprocesses", None), int) else 0
    # Under xdist the controller never collects (workers do, concurrently), so there is no collection phase to time.
    collect_wall = None if workers else (_t_collected or end) - _t0
    stamp = time.strftime("%Y%m%d-%H%M%S")
    tests = {k: dict(v, total=round(v["setup"] + v["call"] + v["teardown"], 4))
             for k, v in _tests.items()}
    summary = {
        "run": f"{stamp}-{os.getpid()}",
        "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - (end - _t0))),
        "args": list(session.config.invocation_params.args),
        "python": sys.executable,
        "exitstatus": int(exitstatus),
        "workers": workers,
        "wall_s": round(end - _t0, 2),
        "collect_s": None if collect_wall is None else round(collect_wall, 2),
        "tests_s": round(sum(t["total"] for t in tests.values()), 2),
        "n_tests": len(tests),
        "n_failed": sum(1 for t in tests.values() if t["outcome"] == "failed"),
        "n_skipped": sum(1 for t in tests.values() if t["outcome"] == "skipped"),
    }
    try:
        runs = TIMINGS_DIR / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        out = runs / f"{summary['run']}.json"
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps({"summary": summary, "collect": _collect, "tests": tests},
                                  indent=0, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, out)
        with open(TIMINGS_DIR / "history.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(summary) + "\n")
        _prune(runs)
        _update_costs(tests)
    except OSError as e:                     # timing is advisory: never fail a run over it
        print(f"timing_plugin: could not write timings ({e})", file=sys.stderr)
