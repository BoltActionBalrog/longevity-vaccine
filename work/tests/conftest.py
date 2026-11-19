"""Shared fixtures for the SMACX patcher regression suite.

Layer 1 (static patch-integrity) imports the *production* patcher in place
(`apply_patches.py`, `config.py`) — we add no copies, only reuse what ships.
The pristine `.bak` (MD5 2d0b1438) is the verification input: it's the exact
binary `patches.yaml` is written against, so every site anchor / cave padding
check runs on real pristine bytes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# One BLAS thread per process, set before anything imports numpy/scipy. OpenBLAS sizes its buffers for one thread per
# core when it loads: on this 64-core machine `import numpy` COMMITS ~750 MB and scipy.ndimage/signal (their own
# OpenBLAS) ~800 MB more -- 1.0 of the ~1.1 GB every xdist worker committed after collection (test_build_portraits_hd
# imports scipy), for threads no test uses (64 workers are the parallelism). Several suites at once ran the machine
# out of commit charge and collection died in MemoryError. With one thread: ~16 MB / ~70 MB, and a worker ~0.27 GB.
# Inherited by every worker and every child process; an explicit value in the environment wins.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import pytest
import yaml

# Per-test timing log (timings/, gitignored; read with `py timing_report.py`). See timing_plugin.py.
# Parallel runs (pytest.ini: `-n auto --dist loadgroup`): how many workers, and which tests share one, are decided
# from those timings by xdist_sched.py -- a targeted run of a heavy module is parallel too, a light one serial.
pytest_plugins = ["timing_plugin", "xdist_sched"]


def pytest_addoption(parser, pluginmanager):
    # Without the xdist PLUGIN the run must still go (serially), not die on pytest.ini's `-n auto`: not installed,
    # `-p no:xdist`, and PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 all land here. (Keyed on the plugin, not on `import
    # xdist`, which succeeds in the last two.)
    if not pluginmanager.has_plugin("xdist"):
        group = parser.getgroup("xdist", "pytest-xdist is NOT installed: these are ignored, the run is serial")
        group._addoption("-n", "--numprocesses", dest="numprocesses", default=None)   # lowercase short: as xdist does
        group.addoption("--dist", dest="dist", default="no")
        group.addoption("--max-worker-restart", dest="maxworkerrestart", default=None)


# No test -- and no installer a test spawns -- may read or write the REAL desktop: the installer's
# shortcut offer looks at LONGEVITY_DESKTOP_DIRS first, so point it at a throwaway folder for the
# whole session (tests that need their own use monkeypatch.setenv on top).
# Both throwaway folders belong to THIS process and are removed when it exits (after every test and every
# installer subprocess it ran); the controller also sweeps empty ones a killed run left. See lv_tempdirs.py.
import lv_tempdirs  # noqa: E402

if not os.environ.get("PYTEST_XDIST_WORKER"):
    lv_tempdirs.sweep_stale()
os.environ["LONGEVITY_DESKTOP_DIRS"] = lv_tempdirs.make("desktop")
# Nor find the real game, nor remember a throwaway install as one of the player's: an installer
# run without --game-dir looks only at the folders a test names, and the folders it installed
# into are recorded in a throwaway file (config.CANDIDATES_ENV / INSTALLS_ENV).
# Assigned, not setdefault: a value inherited from a developer's shell would point the suite at
# real folders or record test installs into a real list.
os.environ["LONGEVITY_GAME_CANDIDATES"] = ""
os.environ["LONGEVITY_INSTALLS_FILE"] = str(Path(lv_tempdirs.make("installs")) / "installs.txt")

# Cache compiled bytecode even when the environment says not to (PYTHONDONTWRITEBYTECODE=1, as agent shells set
# it). Without the cache EVERY worker of EVERY run re-does pytest's assertion rewrite of every test module and
# recompiles the scripts they import: ~20 s of a 35 s collection, paid again by each of 64 workers at once. The
# caches are gitignored `__pycache__` dirs, keyed on each source's mtime and size, written atomically.
sys.dont_write_bytecode = False

# Make the production scripts importable in place (no copies under tests/).
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import config            # noqa: E402  (path set above)
import apply_patches as ap  # noqa: E402
import pefile            # noqa: E402

# Parse each distinct YAML text ONCE per process. patches.yaml is ~2 MB (0.2-0.4 s even with libyaml) and the
# suite parses it thousands of times: the per-test `loaded` fixture, every ap.load_patches() a test or an
# assembler makes, several of them at module import. Same loader, so the same document; every caller gets a
# private copy, so `verify_cave`'s mutation of its parse still cannot leak into another caller's. The copy is a
# pickle round trip of the stored bytes: a safe_load document is plain dicts/lists/scalars, which pickle copies
# exactly (shared aliases included), ~5x faster than copy.deepcopy. Keyed on the TEXT, so an edit between two
# calls is a fresh parse. Installed before any test module imports `_yaml_load` by name.
import io  # noqa: E402
import hashlib  # noqa: E402
import pickle  # noqa: E402

_YAML_MEMO: dict = {}
_ap_yaml_load = ap._yaml_load


def _memo_yaml_load(stream):
    text = stream if isinstance(stream, (str, bytes)) else stream.read()
    key = hashlib.sha1(text if isinstance(text, bytes) else text.encode("utf-8", "surrogatepass")).digest()
    doc = _YAML_MEMO.get(key)
    if doc is None:
        src = text
        if hasattr(stream, "name"):            # keep the file name in a parse error, as a direct parse reports it
            src = (io.BytesIO if isinstance(text, bytes) else io.StringIO)(text)
            src.name = stream.name
        doc = _YAML_MEMO[key] = pickle.dumps(_ap_yaml_load(src), pickle.HIGHEST_PROTOCOL)
    return pickle.loads(doc)


ap._yaml_load = _memo_yaml_load

# The emulator harnesses stub thunk_ensure_scale and write g_popup_scale_num themselves.  The real thunk writes
# g_stripe_period (law scaling_laws.stripe_period) in the same breath, and the popup-g stripe thunks read that
# cell -- so model the pairing once, here: every 4-byte harness write of g also writes the period cell.  (A g the
# EMULATED code writes, i.e. t_hof_spr_pic's bracket, leaves the cell alone, exactly as in the game.)
# 0x71111111 is the sentinel several assemblers use for g before templatizing; the cell is always the raw VA.
G_POPUP_SCALE_NUM_VA = 0x00668740
G_POPUP_SCALE_NUM_ADDRS = (G_POPUP_SCALE_NUM_VA, 0x71111111)
G_STRIPE_PERIOD_VA = 0x0066879C
try:
    import unicorn as _unicorn
    import scaling_laws as _SL

    _uc_mem_write = _unicorn.Uc.mem_write

    def _mem_write_with_period(self, address, data):
        _uc_mem_write(self, address, data)
        if address in G_POPUP_SCALE_NUM_ADDRS and len(data) == 4:
            g = int.from_bytes(bytes(data), "little", signed=True)
            cell = _SL.stripe_period(g).to_bytes(4, "little")
            try:
                _uc_mem_write(self, G_STRIPE_PERIOD_VA, cell)
            except _unicorn.UcError:                 # a harness that maps only its sentinel pages
                self.mem_map(G_STRIPE_PERIOD_VA & ~0xFFF, 0x1000)
                _uc_mem_write(self, G_STRIPE_PERIOD_VA, cell)

    _unicorn.Uc.mem_write = _mem_write_with_period
except ImportError:                                  # the asm-parity modules importorskip the emulator themselves
    pass

# keystone 0.9.2 sometimes opens an engine that reads every unprefixed number as HEX for its whole life (1 in ~255
# engines opened in an xdist worker). scripts/ks_guard.py checks every X86 engine when it opens and reopens a bad
# one; the assemblers import it, and so does every test process here, so tests that open their own Ks are covered.
try:
    import ks_guard  # noqa: F401
except ImportError:                                  # no keystone: the asm-parity modules importorskip it themselves
    pass

# The asm-parity suites `pytest.importorskip` the emulator packages. On an interpreter without
# them every one of those modules skips and the run goes green having verified nothing -- which
# is exactly what happened in the release gate on 2026-09-27 (tools\python had no unicorn). Under
# the release gate that is a hard stop, not a skip.
if os.environ.get("LONGEVITY_REQUIRE_E2E"):
    import importlib.util
    _missing_emu = [m for m in ("unicorn", "keystone", "capstone")
                    if importlib.util.find_spec(m) is None]
    if _missing_emu:
        raise pytest.UsageError(
            f"{sys.executable} lacks {', '.join(_missing_emu)}: the asm-parity tests would SKIP "
            "and LONGEVITY_REQUIRE_E2E is set, so this is a failure, not a skip. Install them "
            "into that interpreter (README: tools/python).")

# Emulator garbage: a Uc that has a hook is a reference cycle (the binding keeps the callback, the callback keeps the
# Uc), so it is freed only by a FULL cyclic collection -- and Python runs those by object counts, which emulation
# barely moves. Each Uc holds ~5 MB of native commit plus its mapped guest memory, so a worker that builds emulators
# per call grew without bound: test_scaling_type1_box_fill to ~1.9 GB, test_force_prescan_bounds to ~1.7 GB (one
# gc.collect() takes either back to ~40 MB). Several suites at once then exhausted the commit charge, and whichever
# test was mapping memory failed (MemoryError / UC_ERR_NOMEM) -- those two modules most of all. So after every test,
# a worker whose private commit grew by GC_GROWTH_MB since its last collection collects: a few dozen collections per
# worker per run (~0.1 s each), and no worker carries more than that much garbage.
GC_GROWTH_MB = 256


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes as _W

    class _PMC(ctypes.Structure):
        _fields_ = [("cb", _W.DWORD), ("PageFaultCount", _W.DWORD)] + [(n, ctypes.c_size_t) for n in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
            "PrivateUsage")]

    _get_pmi = ctypes.windll.psapi.GetProcessMemoryInfo
    _get_pmi.argtypes = (_W.HANDLE, ctypes.c_void_p, _W.DWORD)

    def _private_commit_mb() -> float | None:
        c = _PMC(cb=ctypes.sizeof(_PMC))
        return c.PrivateUsage / 2**20 if _get_pmi(_W.HANDLE(-1), ctypes.byref(c), c.cb) else None
else:
    def _private_commit_mb() -> float | None:
        return None


_gc_floor_mb = None


@pytest.hookimpl(trylast=True)
def pytest_runtest_teardown(item, nextitem):
    """After the test's own fixtures are finalised: collect when this process grew by GC_GROWTH_MB (see above)."""
    global _gc_floor_mb
    now = _private_commit_mb()
    if now is None:
        return
    if _gc_floor_mb is None or now < _gc_floor_mb:
        _gc_floor_mb = now
    elif now - _gc_floor_mb >= GC_GROWTH_MB:
        import gc
        gc.collect()
        _gc_floor_mb = _private_commit_mb()


PATCHES_PATH = Path(ap.DEFAULT_PATCHES)


@pytest.fixture(scope="session")
def patches_path() -> Path:
    if not PATCHES_PATH.exists():
        pytest.skip(f"patches.yaml not found at {PATCHES_PATH}")
    return PATCHES_PATH


@pytest.fixture(scope="session")
def target_meta(patches_path) -> dict:
    """The `target:` block of patches.yaml (expected MD5s, size)."""
    spec = ap._yaml_load(patches_path.read_text(encoding="utf-8"))
    return spec.get("target", {}) or {}


def _missing(p: Path, what: str):
    """Skip -- unless the caller demanded the real thing.

    Every end-to-end installer test hangs off a binary that lives in the player's GOG install, so
    on a clean clone the whole module skips SILENTLY and a CI run goes green having verified
    nothing. LONGEVITY_REQUIRE_E2E=1 turns those skips into hard failures, which is what a
    release gate must set.
    """
    msg = f"{what} not found at {p}"
    if os.environ.get("LONGEVITY_REQUIRE_E2E"):
        pytest.fail(msg + " -- LONGEVITY_REQUIRE_E2E is set, so this is a failure, not a skip.")
    pytest.skip(msg)


@pytest.fixture(scope="session")
def need_local():
    """`need_local(path, what)`: the path, or a skip when it is absent (a failure under LONGEVITY_REQUIRE_E2E).

    For the gitignored things only the main checkout has -- the Thinker clone, a pack's source, the bundled
    interpreter. A fresh worktree lacks them, and a test that read them unguarded FAILED there, which reads
    as a regression."""
    def need(p, what: str) -> Path:
        p = Path(p)
        if not p.exists():
            _missing(p, what)
        return p
    return need


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "needs_local(path, what): skip when `path` is absent -- a FAILURE under LONGEVITY_REQUIRE_E2E")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """`@pytest.mark.needs_local(path, what)` in place of a plain `skipif(not path.exists())` (audit-j L4: the bundled
    interpreter's and the batch's ~100 end-to-end tests skipped silently under LONGEVITY_REQUIRE_E2E too, and the run
    "passed"). Absent: _missing -- a skip, or a failure when the release gate demands the real thing."""
    for mark in item.iter_markers("needs_local"):
        p, what = mark.args
        if not Path(p).exists():
            _missing(Path(p), what)


@pytest.fixture(scope="session")
def bak_path() -> Path:
    p = config.terranx_bak(required=False)
    if not p.exists():
        _missing(p, "the pristine .bak (needed for the patch-integrity and installer tests)")
    return p


@pytest.fixture(scope="session")
def bak_bytes(bak_path) -> bytes:
    return bak_path.read_bytes()


@pytest.fixture(scope="session")
def baked_exe(bak_path, tmp_path_factory) -> Path:
    """The .bak with the live patches.yaml applied (`apply_patches.py --target <copy> --apply`): the bytes a player runs.

    Built ONCE per pytest run, shared by every xdist worker (baked_exe.py): a module fixture that applied the patch set
    itself repaid the ~1.2 s apply in every chunk the cost-aware scheduler cut from its module.  READ-ONLY -- the file
    is shared, and a write raises.  test_baked_exe_shared.py fails a module that builds its own.
    """
    import baked_exe as B
    try:
        return B.build(bak_path, lambda: tmp_path_factory.mktemp("baked_exe"))
    except B.BuildError as e:
        pytest.fail(str(e))


@pytest.fixture(scope="session")
def prax_bak_path() -> Path:
    """The CLEAN prax.dll (MD5 89a0037b), for exercising the companion-patch path."""
    p = config.game_dir(required=False) / "prax.dll.bak"
    if not p.is_file():
        _missing(p, "the clean prax.dll (needed for the companion-patch tests)")
    return p


@pytest.fixture
def loaded(patches_path) -> dict:
    """A private copy of patches.yaml per test.

    Never shared on purpose: `verify_cave` mutates cave dicts (`_pending_section_*`), so sharing one parse across
    tests would leak state. (The parse itself is memoized per process -- `_memo_yaml_load` -- but every caller gets
    its own copy.)
    """
    sites, groups, caves, symbols = ap.load_patches(patches_path)
    s2v = ap.build_symbol_table(symbols, caves)
    return {"sites": sites, "groups": groups, "caves": caves,
            "symbols": symbols, "s2v": s2v}


@pytest.fixture
def pe_ctx(bak_bytes) -> dict:
    """A PE/VaResolver bound to the pristine bytes for VA→file-offset math."""
    pe = pefile.PE(data=bak_bytes, fast_load=True)
    return {"data": bak_bytes, "pe": pe, "resolver": ap.VaResolver(pe)}


# --- Pristine (un-PRACX'd, cc659f) target — for the native DLL-loader group ---

@pytest.fixture(scope="session")
def pristine_bytes() -> bytes:
    """The pristine (cc659f) terranx.exe — the --pristine loader target.

    PREFERS THE .bak, like `bak_path` does for the PRACX exe. Reading only the live
    `terranx.exe` meant this skipped the moment that file was patched — which is to say from the
    first install onwards, permanently. The native DLL-loader group's site verification was
    therefore not running at all on this machine (live terranx.exe is 01bb80b0, patched; the
    cc659f the fixture wants sits in terranx.exe.bak), and the skip said only "not the expected
    pristine binary", which reads like an unsupported machine rather than a hole in the run.
    """
    import hashlib
    game = config.game_dir(required=False)
    # Third place: a game folder the installer set up for Thinker keeps the original as
    # terranx_original.exe (terranx.exe is then our build and its .bak the clean PRACX base), and
    # every Thinker test skipped silently the moment the live game was set up (2026-11-06).
    stem, suf = os.path.splitext(ap.PRISTINE_EXE)
    candidates = [game / (ap.PRISTINE_EXE + ".bak"), game / ap.PRISTINE_EXE, game / f"{stem}_original{suf}"]
    for p in candidates:
        if p.is_file() and hashlib.md5(p.read_bytes()).hexdigest() == ap.PRISTINE_MD5:
            return p.read_bytes()
    _missing(candidates[0],
             f"the pristine {ap.PRISTINE_EXE} ({ap.PRISTINE_MD5}, needed for the native "
             f"DLL-loader site checks; looked in the .bak, the live exe and {candidates[2].name})")


@pytest.fixture
def pristine_pe_ctx(pristine_bytes) -> dict:
    pe = pefile.PE(data=pristine_bytes, fast_load=True)
    return {"data": pristine_bytes, "pe": pe, "resolver": ap.VaResolver(pe)}


#: install.py's run-wide globals and their import-time values. A test that runs _install / do_update sets them,
#: and the next test in the worker saw them (code review 2026-11-15: _THINKER_NEW, _VERDICT, _LAUNCH_EXE,
#: _NOTE_ARGS leaked between tests).
INSTALL_GLOBALS = {"_THINKER_NEW": False, "_VERDICT": None, "_LAUNCH_EXE": None, "_NOTE_ARGS": None,
                   "_PENDING_UPDATE_CHECKS": None, "_WHATS_NEW": None}


@pytest.fixture
def install_globals(monkeypatch):
    """Every install.py run-wide global at its import-time value, and put back after the test."""
    import install as inst
    import installer_exit as ix
    for name, value in INSTALL_GLOBALS.items():
        if hasattr(inst, name):
            monkeypatch.setattr(inst, name, value)
    monkeypatch.setattr(inst, "_PACKS_UNREAD", [], raising=False)     # a fresh list: never shared between tests
    monkeypatch.setattr(inst, "_UNTICKED", [], raising=False)          # the last list's unticks (audit-t)
    monkeypatch.setattr(inst, "_PENDING_CHOICES", None, raising=False)  # a first install's held answers (audit-t)
    import thinker_flow as tf
    monkeypatch.setattr(tf, "_INI_OWED", None, raising=False)           # a thinker.ini choice another test's change owed
    monkeypatch.setattr(ix, "_PLAYER_NO_PROMPT", False, raising=False)   # main() sets it from --no-prompt
    monkeypatch.delenv("LONGEVITY_PLAYER_NO_PROMPT", raising=False)
    monkeypatch.delenv("LONGEVITY_NO_WAIT", raising=False)     # an in-process main() exports it; ix.can_ask reads it


@pytest.fixture
def synthetic_pin(monkeypatch):
    """The synthetic Thinker files (test_thinker_update.NEW, plus the review tests' Changelog.md) stand in for the
    compiled pin's release: the install record is checked against the pin's own file hashes (audit-g HIGH-1), and a
    test's record holds the synthetic files' hashes."""
    import hashlib
    import thinker_flow as tf
    from test_thinker_update import NEW
    files = {**NEW, "Changelog.md": b"what's new"}
    table = {rel.lower(): (rel, hashlib.sha256(data).hexdigest()) for rel, data in files.items()}
    pid = tf.compiled_pin().pin_id
    monkeypatch.setattr(tf, "_pin_files", lambda pin_id: dict(table) if pin_id == pid else {})


#: Connections an in-process test tried to make to another host (the guard below refuses and records them).
_NET_TRIES: list = []


def _loopback(addr) -> bool:
    """This machine: "localhost", or an address that PARSES as a loopback one (audit-f L1: a prefix test let
    "127.example.invalid" through)."""
    import ipaddress
    host = addr[0] if isinstance(addr, tuple) and addr else addr
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


class _NetSink:
    """A local stand-in for the network, for every installer CHILD process a test starts: the session points
    HTTP_PROXY / HTTPS_PROXY here, the children inherit it, and a request for longevitymods.com, GitHub or anything
    else arrives here -- recorded and refused, never the real host (user 2026-11-15: no test may fetch the live
    manifest; a test that needs one passes a local signed manifest or --offline)."""

    def __init__(self):
        import socket
        import threading
        self.requests = []
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(32)
        self.port = self._srv.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                c, _ = self._srv.accept()
            except OSError:
                return
            try:
                c.settimeout(5)
                line = c.recv(4096).split(b"\r\n", 1)[0].decode("latin-1", "replace")
                self.requests.append(line)
                c.sendall(b"HTTP/1.1 502 Blocked by the test suite\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            finally:
                c.close()


_SINK = None


@pytest.fixture(scope="session", autouse=True)
def _no_network():
    """The suite is hermetic (user 2026-11-15). In this process: socket.connect to anything but this machine is
    refused and recorded (so a test fails even when the code under test swallows the error). In every child
    process: HTTP(S)_PROXY points at _NetSink (NO_PROXY keeps local test servers direct). A live check opts in with
    LONGEVITY_NET_TESTS=1.

    In this process connect, connect_ex and name lookups (getaddrinfo / gethostbyname) are all refused for anything
    but this machine (audit-f L1). The limit, which this guard cannot close: a CHILD process honours the proxy only
    for HTTP(S) it makes through a proxy-aware client, so a child started with a fresh environment (no
    HTTP(S)_PROXY), or one that opens raw sockets or resolves names itself, reaches the network directly. Every
    installer child the suite starts inherits os.environ and fetches through urllib, which honours the proxy."""
    global _SINK
    if os.environ.get("LONGEVITY_NET_TESTS"):
        yield
        return
    import socket
    _SINK = _NetSink()
    proxy = f"http://127.0.0.1:{_SINK.port}"
    saved = {k: os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                                            "NO_PROXY", "no_proxy")}
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ[k] = proxy
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "localhost,127.0.0.1,::1"
    real = socket.socket.connect
    real_ex = socket.socket.connect_ex
    real_gai = socket.getaddrinfo
    real_ghbn = socket.gethostbyname
    real_ghbn_ex = socket.gethostbyname_ex

    def refuse(addr):
        _NET_TRIES.append(addr)
        raise OSError("blocked by the test suite: no network")

    def guarded(self, addr):
        if getattr(self, "family", None) in (socket.AF_INET, socket.AF_INET6) and not _loopback(addr):
            refuse(addr)
        return real(self, addr)

    def guarded_ex(self, addr):
        if getattr(self, "family", None) in (socket.AF_INET, socket.AF_INET6) and not _loopback(addr):
            refuse(addr)
        return real_ex(self, addr)

    def lookup(real_fn):
        def guarded_lookup(host, *a, **k):
            if host is not None and not _loopback(host):      # None / "" : a local bind, never a lookup
                if host != "":
                    _NET_TRIES.append(("lookup", host))
                    raise socket.gaierror(socket.EAI_NONAME, "blocked by the test suite: no name lookups")
            return real_fn(host, *a, **k)
        return guarded_lookup

    socket.socket.connect = guarded
    socket.socket.connect_ex = guarded_ex
    socket.getaddrinfo = lookup(real_gai)
    socket.gethostbyname = lookup(real_ghbn)
    socket.gethostbyname_ex = lookup(real_ghbn_ex)
    try:
        yield
    finally:
        socket.socket.connect = real
        socket.socket.connect_ex = real_ex
        socket.getaddrinfo = real_gai
        socket.gethostbyname = real_ghbn
        socket.gethostbyname_ex = real_ghbn_ex
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture(autouse=True)
def _no_network_tried():
    """Fail the test that tried the network: in this process, or through a child (its request reached _NetSink).

    The limit of the attribution (audit-l L5): a child's request is charged to the test running in this worker when it
    ARRIVES. A child that outlives its test (one left running in the background) and fetches later is charged to the
    next test in the same worker. Every child the suite starts is waited for by its own test, so this does not happen
    today. A test that starts a child it does not wait for must tag it, or stop it, before it ends."""
    _NET_TRIES.clear()
    seen = len(_SINK.requests) if _SINK is not None else 0
    yield
    tried = list(_NET_TRIES) + (_SINK.requests[seen:] if _SINK is not None else [])
    _NET_TRIES.clear()
    assert not tried, f"the test tried to reach the network (blocked): {tried}"
