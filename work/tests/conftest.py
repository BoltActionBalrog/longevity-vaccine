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
import tempfile
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
os.environ["LONGEVITY_DESKTOP_DIRS"] = tempfile.mkdtemp(prefix="lv-desktop-")
# Nor find the real game, nor remember a throwaway install as one of the player's: an installer
# run without --game-dir looks only at the folders a test names, and the folders it installed
# into are recorded in a throwaway file (config.CANDIDATES_ENV / INSTALLS_ENV).
# Assigned, not setdefault: a value inherited from a developer's shell would point the suite at
# real folders or record test installs into a real list.
os.environ["LONGEVITY_GAME_CANDIDATES"] = ""
os.environ["LONGEVITY_INSTALLS_FILE"] = str(Path(tempfile.mkdtemp(prefix="lv-installs-")) / "installs.txt")

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
    candidates = [game / (ap.PRISTINE_EXE + ".bak"), game / ap.PRISTINE_EXE]
    for p in candidates:
        if p.is_file() and hashlib.md5(p.read_bytes()).hexdigest() == ap.PRISTINE_MD5:
            return p.read_bytes()
    _missing(candidates[0],
             f"the pristine {ap.PRISTINE_EXE} ({ap.PRISTINE_MD5}, needed for the native "
             f"DLL-loader site checks; looked in the .bak and the live exe)")


@pytest.fixture
def pristine_pe_ctx(pristine_bytes) -> dict:
    pe = pefile.PE(data=pristine_bytes, fast_load=True)
    return {"data": pristine_bytes, "pe": pe, "resolver": ap.VaResolver(pe)}
