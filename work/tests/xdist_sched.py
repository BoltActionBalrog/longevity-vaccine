"""How this suite spreads over pytest-xdist workers: how MANY, and which tests go TOGETHER.

Both decisions read the measured cost of every test from the cost table timing_plugin.py keeps (each test's
newest setup and total seconds), which lives in the repository's .git directory so that every worktree shares it
(`timing_plugin.costs_file()`). Without it -- a fresh clone -- the run still works: a module with no measured test
is cut into UNMEASURED_CHUNKS units by count, and a targeted run with nothing measured runs serially.

HOW MANY (`pytest_xdist_auto_num_workers`, i.e. `-n auto` from pytest.ini):
- a run over the directory (the whole suite, `-k scaling`, the release gate) -> XDIST_WORKERS processes, fewer
  when the free commit charge cannot hold that many (another agent's run is already using it);
- a run that names files or node ids -> ~sqrt(cost / WORKER_START_S) workers for the named tests' measured cost,
  and none at all (serial) under SERIAL_BELOW_S: a worker is not free (xdist starts them one at a time, and each
  imports conftest -- unicorn, pefile, the patcher -- and collects the named files before its first test);
- `-n N` always wins; SMACX_XDIST_WORKERS overrides the count (memory cap included).

WHICH TOGETHER (`CostScheduling`, the scheduler for `--dist loadgroup`): the controller cuts each module into
contiguous CHUNKS of roughly equal measured cost and hands the chunks out longest-first. A chunk is a work unit:
its tests run in collection order on one worker, so module-scoped fixtures build once per chunk. A module is cut
only as finely as its fixture cost allows -- every chunk must be worth at least SETUP_RATIO times the module's
per-worker warm-up (its largest measured test SETUP). So a module whose time IS setup (test_scaling_js_parity's
~15 s node sweep) stays whole, and a module of many independent emulations is spread over many workers.

Longest-first is the point of the second half: xdist's own loadgroup queues groups by TEST COUNT, so a 40 s
single-test unit started last and ran alone at the end of the run.

An explicit `@pytest.mark.xdist_group("name")` still wins: every test carrying it is one unit, whatever the costs.
Grouping changes only WHERE a test runs, never which tests run or what they assert.
"""
from __future__ import annotations

import atexit
import math
import os
import sys
from collections import OrderedDict
from pathlib import Path

import pytest

XDIST_WORKERS = 64          # a directory run; physical cores on this machine. SMACX_XDIST_WORKERS overrides.
WORKER_COMMIT_GB = 0.75     # ... lowered to what the free commit charge holds at this much per worker: a full run's
                            # workers PEAK at 0.69 GB on average (2026-10-25: 44 GB over 64; one-thread BLAS and
                            # conftest's GC_GROWTH_MB bound; before them ~1.1 GB after collection alone)
COMMIT_RESERVE_GB = 8.0     # ... leaving this much for everything else
SERIAL_BELOW_S = 8.0        # a targeted run whose tests cost less than this in all runs serially
WORKER_START_S = 0.25       # ... else ~sqrt(cost / this) workers: xdist starts them one at a time
DEFAULT_COST_S = 0.05       # a test with no measurement yet, in a module that has some
UNMEASURED_CHUNKS = 8       # a module with none: cut by count into this many units, queued early
SETUP_RATIO = 4.0           # a chunk must cost >= this x its module's per-worker warm-up
CHUNK_MIN_S, CHUNK_MAX_S = 1.0, 30.0      # chunk size target: total / (CHUNKS_PER_WORKER x workers), clamped
CHUNKS_PER_WORKER = 2


# ---------------------------------------------------------------------------------------------- costs

def load_costs() -> dict[str, list[float]]:
    """{nodeid: [setup_s, total_s]} -- empty when nothing has been measured."""
    from timing_plugin import read_costs
    return read_costs()


def _module(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def _explicit_group(nodeid: str) -> str | None:
    """The `@name` xdist appends for an explicit xdist_group mark (as LoadGroupScheduling reads it)."""
    return nodeid.split("@")[-1] if nodeid.rfind("@") > nodeid.rfind("]") else None


# ---------------------------------------------------------------------------------------------- how many

def _selected_prefixes(config) -> list[str] | None:
    """The named files / node ids as nodeid prefixes (relative to rootdir), or None for a directory run.

    `config.args` is what pytest will actually collect (testpaths when none was given), after option parsing -- so
    an option's value (`--deselect x.py::t`, `-k "not x.py"`, `--ignore x.py`) can never pass for a path.
    """
    if not config.args:
        return None
    base, root = Path(config.invocation_params.dir), Path(config.rootpath)
    out = []
    for a in config.args:
        path, sep, rest = a.partition("::")
        p = (base / path)
        if not p.is_file():
            return None
        try:
            rel = p.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return None
        out.append(rel + sep + rest)
    return out


def estimate_cost(prefixes: list[str], costs: dict) -> float:
    """Measured seconds of every known test under the given nodeid prefixes."""
    total = 0.0
    for nid, (_, t) in costs.items():
        for p in prefixes:
            if nid == p or nid.startswith(p + "::") or nid.startswith(p + "["):
                total += t
                break
    return total


def targeted_workers(est_s: float, cap: int) -> int:
    """Workers for a run of `est_s` measured seconds. xdist starts workers ONE AT A TIME (~0.25 s each), so past
    ~sqrt(est / 0.25) the next worker costs more start-up than it saves."""
    if est_s < SERIAL_BELOW_S:
        return 0
    return max(2, min(cap, round(math.sqrt(est_s / WORKER_START_S))))


def commit_headroom_gb() -> float | None:
    """Commit charge still available (RAM + page file), or None where it cannot be read."""
    if sys.platform != "win32":
        return None
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MEMORYSTATUSEX(dwLength=ctypes.sizeof(MEMORYSTATUSEX))
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return None
    return m.ullAvailPageFile / 2**30


def memory_cap(cap: int, pending_gb: float = 0.0) -> int:
    """`cap`, lowered so the workers fit the commit charge still free -- less what runs already started will still
    commit (`pending_gb`, from the ledger below). Several agents running the suite at once exhausted the commit
    limit at 96 workers, and the run errored in hundreds of tests instead of slowing down."""
    free = commit_headroom_gb()
    if free is None:
        return cap
    return max(1, min(cap, int((free - COMMIT_RESERVE_GB - pending_gb) / WORKER_COMMIT_GB)))


# ---------------------------------------------------------------------------------------------- the run ledger
#
# The free commit charge is read ONCE, as a run starts -- before any of its workers exists. Three suites started
# together each saw the same ~115 GB free, each took 64 workers, and 192 workers' imports then ran the machine out
# of commit: collection died in MemoryError across hundreds of modules (2026-10-25, w7F: 3 of 3 such starts). So
# every auto-sized run records what it took in a machine-wide ledger (under a file lock), and a run that starts
# later subtracts what each live run it lists has NOT committed yet: its reservation (workers x WORKER_COMMIT_GB)
# less the private commit of its process tree now. Once a run's workers are up, the free charge already shows them
# and it pends nothing; a dead run's entry is dropped.

LEDGER_NAME = "smacx-xdist-ledger.json"


def _ledger_path() -> Path:
    import tempfile
    return Path(tempfile.gettempdir()) / LEDGER_NAME


def _proc_info() -> dict[int, tuple[int, float]] | None:
    """{pid: (parent pid, private commit GB)} of every process this user can query, or None off Windows."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes as W

    class PE32(ctypes.Structure):
        _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", W.DWORD), ("cntThreads", W.DWORD),
                    ("th32ParentProcessID", W.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", W.DWORD),
                    ("szExeFile", ctypes.c_char * 260)]

    class PMC(ctypes.Structure):
        _fields_ = [("cb", W.DWORD), ("PageFaultCount", W.DWORD)] + [(n, ctypes.c_size_t) for n in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
            "PrivateUsage")]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi")
    k32.CreateToolhelp32Snapshot.restype = W.HANDLE
    k32.OpenProcess.restype = W.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)                      # TH32CS_SNAPPROCESS
    if not snap or snap == W.HANDLE(-1).value:
        return None
    out: dict[int, tuple[int, float]] = {}
    try:
        e = PE32(dwSize=ctypes.sizeof(PE32))
        ok = k32.Process32First(W.HANDLE(snap), ctypes.byref(e))
        while ok:
            gb = 0.0
            h = k32.OpenProcess(0x1000, False, e.th32ProcessID)      # PROCESS_QUERY_LIMITED_INFORMATION
            if h:
                c = PMC(cb=ctypes.sizeof(PMC))
                if psapi.GetProcessMemoryInfo(W.HANDLE(h), ctypes.byref(c), c.cb):
                    gb = c.PrivateUsage / 2**30
                k32.CloseHandle(W.HANDLE(h))
            out[e.th32ProcessID] = (e.th32ParentProcessID, gb)
            ok = k32.Process32Next(W.HANDLE(snap), ctypes.byref(e))
    finally:
        k32.CloseHandle(W.HANDLE(snap))
    return out


def _tree_commit_gb(root: int, procs: dict[int, tuple[int, float]]) -> float:
    kids: dict[int, list[int]] = {}
    for pid, (ppid, _gb) in procs.items():
        kids.setdefault(ppid, []).append(pid)
    total, todo, seen = 0.0, [root], set()
    while todo:
        pid = todo.pop()
        if pid in seen or pid not in procs:
            continue
        seen.add(pid)
        total += procs[pid][1]
        todo.extend(kids.get(pid, ()))
    return total


def pending_gb(ledger: dict, procs: dict, me: int) -> float:
    """What the OTHER live runs in `ledger` ({pid: {"gb": reserved}}) have still to commit."""
    return sum(max(0.0, float(v.get("gb", 0.0)) - _tree_commit_gb(int(pid), procs))
               for pid, v in ledger.items() if int(pid) != me and int(pid) in procs)


def _ledger_update(fn):
    """fn(ledger, procs) -> new ledger, under the ledger's lock; returns fn's ledger (None when unavailable)."""
    import json
    from cpp_harness import file_lock
    procs = None
    path = _ledger_path()
    try:
        with file_lock(path.with_suffix(".lock"), 30):
            procs = _proc_info()
            if procs is None:
                return None
            try:
                ledger = json.loads(path.read_text(encoding="utf-8"))
                ledger = ledger if isinstance(ledger, dict) else {}
            except (OSError, ValueError):
                ledger = {}
            ledger = {k: v for k, v in ledger.items() if k.isdigit() and int(k) in procs}   # dead runs drop out
            ledger = fn(ledger, procs)
            tmp = path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(ledger), encoding="utf-8")
            os.replace(tmp, path)
            return ledger
    except (OSError, TimeoutError, ImportError):
        return None                       # no ledger: the run is sized from the free charge alone, as before


def _ledger_release() -> None:
    me = str(os.getpid())
    _ledger_update(lambda led, _procs: {k: v for k, v in led.items() if k != me})


def reserve_workers(size) -> int:
    """`size(pending_gb) -> workers`, decided and recorded in the ledger in one locked step (so two runs starting
    together see each other); the entry is released when this process exits."""
    me = os.getpid()
    box = {}

    def step(ledger, procs):
        box["n"] = n = size(pending_gb(ledger, procs, me))
        ledger[str(me)] = {"gb": round(n * WORKER_COMMIT_GB, 2)}
        return ledger
    if _ledger_update(step) is None or "n" not in box:
        return size(0.0)
    atexit.register(_ledger_release)
    return box["n"]


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_auto_num_workers(config):
    env = os.environ.get("SMACX_XDIST_WORKERS")
    prefixes = _selected_prefixes(config)
    est = None if prefixes is None else estimate_cost(prefixes, load_costs())

    def size(pending: float) -> int:
        cap = int(env) if env else memory_cap(min(XDIST_WORKERS, os.cpu_count() or 1), pending)
        return cap if est is None else targeted_workers(est, cap)
    if env:
        return size(0.0)
    n = size(0.0)
    if n == 0:
        return 0                          # serial: nothing to reserve
    return reserve_workers(size)


# ---------------------------------------------------------------------------------------------- which together

def plan(collection: list[str], costs: dict, workers: int) -> tuple[dict[str, str], list[str]]:
    """({nodeid: unit}, units longest-first) for one run's collection.

    Units are contiguous runs of one module (or an explicit xdist_group). Deterministic for a given collection and
    cost table, and every nodeid gets exactly one unit.
    """
    def cost(nid):
        c = costs.get(nid)
        return c[1] if c else DEFAULT_COST_S

    modules: OrderedDict[str, list[str]] = OrderedDict()
    unit_of: dict[str, str] = {}
    unit_cost: dict[str, float] = {}
    for nid in collection:
        g = _explicit_group(nid)
        if g is not None:
            unit_of[nid] = g
            unit_cost[g] = unit_cost.get(g, 0.0) + cost(nid)
        else:
            modules.setdefault(_module(nid), []).append(nid)

    grand = sum(cost(n) for n in collection)
    target = min(CHUNK_MAX_S, max(CHUNK_MIN_S, grand / (CHUNKS_PER_WORKER * max(1, workers))))

    for mod, ids in modules.items():
        if any(n in costs for n in ids):
            cs = [cost(n) for n in ids]
            total = sum(cs)
            warmup = max((costs.get(n) or (0.0, 0.0))[0] for n in ids)
            k = max(1, min(len(ids), int(total // max(target, SETUP_RATIO * warmup))))
        else:
            # Never measured (a new module): it may be the heaviest in the suite, and kept whole it would run alone
            # on one worker at the end. Cut it into UNMEASURED_CHUNKS by count and queue those early.
            k = min(len(ids), UNMEASURED_CHUNKS)
            cs = [CHUNK_MAX_S * k / len(ids)] * len(ids)
            total = sum(cs)
        # cut where the running cost crosses i*total/k: chunks of near-equal cost, in collection order
        acc, step = 0.0, total / k
        for nid, c in zip(ids, cs):
            i = min(k - 1, int(acc // step)) if step > 0 else 0
            unit = f"{mod}#{i}" if k > 1 else mod
            unit_of[nid] = unit
            unit_cost[unit] = unit_cost.get(unit, 0.0) + c
            acc += c

    order = sorted(unit_cost, key=lambda u: -unit_cost[u])       # stable: ties keep collection order
    return unit_of, order


try:
    from xdist.scheduler import LoadScopeScheduling
except ImportError:                                  # no xdist: the run is serial, nothing to schedule
    LoadScopeScheduling = None

if LoadScopeScheduling is not None:
    class CostScheduling(LoadScopeScheduling):
        """LoadScopeScheduling whose scopes are `plan()`'s units, queued longest-first."""

        def __init__(self, config, log=None):
            super().__init__(config, log)
            self._unit_of: dict[str, str] = {}

        def _split_scope(self, nodeid: str) -> str:
            return self._unit_of.get(nodeid) or _explicit_group(nodeid) or _module(nodeid)

        def schedule(self) -> None:
            # LoadScopeScheduling.schedule, with the work queue built from plan() instead of sorted by test count.
            assert self.collection_is_completed
            if self.collection is not None:
                for node in self.nodes:
                    self._reschedule(node)
                return
            if not self._check_nodes_have_same_collection():
                self.log("**Different tests collected, aborting run**")
                return
            self.collection = list(next(iter(self.registered_collections.values())))
            if not self.collection:
                return
            self._unit_of, order = plan(self.collection, load_costs(), len(self.nodes))
            units: dict[str, dict[str, bool]] = {u: {} for u in order}
            for nodeid in self.collection:
                units[self._split_scope(nodeid)][nodeid] = False
            for u in order:
                self.workqueue[u] = units[u]

            extra_nodes = len(self.nodes) - len(self.workqueue)
            if extra_nodes > 0:
                self.log(f"Shutting down {extra_nodes} nodes")
                for _ in range(extra_nodes):
                    unused_node, _assigned = self.assigned_work.popitem()
                    self.log(f"Shutting down unused node {unused_node}")
                    unused_node.shutdown()
            for node in self.nodes:
                self._assign_work_unit(node)
            # A worker runs a test only once it holds the NEXT one too (it needs it to plan fixture teardown), and
            # gets more work only when it completes a test. A node whose first unit is a single test would sit idle
            # until the end of the run -- so top every node up to two tests (a unit is never split).
            for node in self.nodes:
                while self.workqueue and self._pending_of(self.assigned_work[node]) < 2:
                    self._assign_work_unit(node)

    def _worker_fast_exit() -> None:
        """Run every other exit handler, then end the process without tearing the interpreter down.

        A worker's last act is interpreter finalization: freeing every module, cache and emulator it built. Alone
        that is ~1 s; with 48+ workers finishing together it took over xdist's 10 s exit timeout, so every parallel
        run ended with ~12 s of waiting for workers that had already reported everything -- and then killing them.
        Nothing a worker owns outlives it (results travel over the channel; files are closed by their tests)."""
        atexit.unregister(_worker_fast_exit)
        atexit._run_exitfuncs()
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except (OSError, ValueError, AttributeError):
                pass
        os._exit(0)

    def pytest_configure(config):
        if hasattr(config, "workerinput") and hasattr(atexit, "_run_exitfuncs"):
            atexit.register(_worker_fast_exit)

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_make_scheduler(config, log):
        if config.getvalue("dist") == "loadgroup":
            return CostScheduling(config, log)
        return None
