"""Stage the SHIPPED Python runtime: a curated subset of tools\\python.

WHY: `tools\\python` is 428 MB and ~96% of the base install, and the installer is resident, so it
is paid twice -- once on download, once on disk. Almost all of it is developer tooling (frida 114
MB, numpy 54 MB, PIL 16 MB, pip, pytest, capstone, keystone, pyghidra) plus parts of CPython the
installer never touches (Doc 56 MB, Lib/test 63 MB, tcl/tk, idlelib).

HOW THE FILE LIST IS DECIDED: by MEASUREMENT, not by declaration. `trace_imports.py` runs every
shipped entry point through the real interpreter and records which files actually backed the
modules that loaded. Writing the list by hand is the classic way to ship a release that dies on
someone else's machine with an ImportError the dev box never saw.

WHERE THE TRACE IS NOT ENOUGH: a trace is a LOWER bound -- it only sees the paths it exercised,
on this machine, with this locale. Two categories are therefore added wholesale rather than
sampled:

  * `Lib/encodings` -- Python loads codecs lazily BY NAME. A trace on an en-US box records cp1252
    and utf-8 and nothing else; a player on a Japanese or Cyrillic system needs a codec that was
    never imported here. 1.7 MB is not worth the risk of a startup crash we cannot reproduce.
  * native support DLLs -- `_ssl.pyd` and `_hashlib.pyd` link against libssl/libcrypto, which are
    not Python modules and so never appear in `sys.modules` at all. A trace CANNOT see them.

VERIFY, DON'T ASSUME: `--verify` re-runs the whole installer flow against the staged runtime, in
a scratch game directory. That is the only evidence that the subset is complete.

    py work\\scripts\\trace_imports.py --out work\\build\\import-trace.json
    py work\\scripts\\build_runtime.py --out work\\build\\runtime --verify
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_REPO = _SCRIPTS.parent.parent
sys.path.insert(0, str(_SCRIPTS))

SRC = _REPO / "tools" / "python"
DEFAULT_TRACE = _REPO / "work" / "build" / "import-trace.json"

#: The interpreter itself. Not discoverable from a module trace -- python.exe is the thing DOING
#: the importing, and the vcruntime DLLs are loaded by the OS loader before Python starts.
CORE_FILES = (
    "python.exe",
    "python312.dll",
    "python3.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "LICENSE.txt",              # CPython's licence must ship with CPython
)

#: Native support libraries are DERIVED, not listed.
#:
#: They are INVISIBLE TO THE IMPORT TRACE -- they are not Python modules, so they never appear in
#: sys.modules. A hand-written list is a guess, and the first staged build proved it: `_ctypes.pyd`
#: links against `libffi-8.dll`, which nothing in the trace mentions and which no amount of
#: reading module names would have revealed. The staged interpreter simply died with
#: "ImportError: DLL load failed while importing _ctypes" -- on a player's machine, that is the
#: whole installer gone with no verdict.
#:
#: So instead: read the actual PE import tables of every binary being staged, follow anything we
#: also ship, and repeat to a fixpoint. A CPython upgrade that changes linkage is then picked up
#: automatically rather than silently breaking a release.


def _pe_imports(path: Path) -> set:
    """The DLL names a PE binary links against (lowercase)."""
    import pefile
    try:
        pe = pefile.PE(str(path), fast_load=True)
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
        out = {e.dll.decode("ascii", "ignore").lower()
               for e in (getattr(pe, "DIRECTORY_ENTRY_IMPORT", None) or [])}
        pe.close()
        return out
    except Exception:  # noqa: BLE001 - an unreadable binary is not a reason to abort the build
        return set()


def resolve_native(want: set, say=print) -> set:
    """Every DLL the staged binaries need that lives in our own tree. Transitive."""
    index = {}
    for p in list((SRC / "DLLs").glob("*.dll")) + list(SRC.glob("*.dll")):
        index.setdefault(p.name.lower(), p.relative_to(SRC).as_posix())

    pending = [r for r in want if r.lower().endswith((".pyd", ".dll", ".exe"))]
    added, seen = set(), set(pending)
    while pending:
        rel = pending.pop()
        src = SRC / rel
        if not src.is_file():
            continue
        for dep in _pe_imports(src):
            cand = index.get(dep)
            # Not found in our tree = an OS DLL (kernel32, ws2_32, crypt32, ole32...), which
            # Windows supplies. Only what WE ship needs staging.
            if cand and cand not in want and cand not in added:
                added.add(cand)
                if cand not in seen:
                    seen.add(cand)
                    pending.append(cand)
    if added:
        say(f"  native support libraries pulled in: {', '.join(sorted(added))}")
    return added

#: Shipped wholesale, for the reasons in the module docstring.
WHOLE_TREES = (
    "Lib/encodings",
)

#: Staged by a closure, then removed again -- each verified to have NO importer that can reach it.
#:
#: The closures are deliberately generous (they follow guarded `try/except ImportError` imports
#: too, because a "merely optional" module going missing still changes behaviour silently). That
#: generosity has a cost, and this is where it is paid back, one reviewed entry at a time.
EXCLUDE = {
    # Stable-ABI forwarder. Only a third-party .pyd built against the limited API needs it, and
    # none of ours is -- confirmed against the PE import tables of every binary we ship.
    "python3.dll",
    # MSVC C++ exception-handling runtime. Nothing in the tree imports it, statically or by
    # delay-load, so its absence cannot change how anything loads.
    "vcruntime140_1.dll",
    # NOTE: yaml's C loader (_yaml.pyd + cyaml.py) was excluded here and is now SHIPPED again.
    # The original reasoning -- "nothing in the repo uses CSafeLoader" -- was circular: nothing
    # used it because nobody had asked for it. It parses the 1.78 MB patches.yaml in 0.22s against
    # 2.0s for the pure-Python loader, and every installer run parses that file, so 254 KB of an
    # 11.6 MB download buys ~2s off every install a player performs.
    # uuid.py guards _uuid; uuid itself is pulled in only by pefile's top-level import.
    "DLLs/_uuid.pyd",
    # shutil registers bz2/lzma archive formats inside try/except ImportError. Everything we read
    # or write is ZIP_DEFLATED.
    "DLLs/_bz2.pyd", "DLLs/_lzma.pyd", "Lib/bz2.py", "Lib/lzma.py",
}

#: KEPT ON PURPOSE, against the temptation to cut it: dropping `_hashlib.pyd` saves 69 KB and
#: makes hashlib fall back to the builtin `_sha2`/`_md5`, which have no SHA-NI -- sha256 drops
#: from ~1900 MB/s to ~294 MB/s. That is +4 s on the 1.3 GB pack for 69 KB, and libcrypto has to
#: ship for `ssl` regardless, so the saving is illusory. It only becomes worth revisiting if
#: OpenSSL leaves entirely.
_KEEP_HASHLIB = "DLLs/_hashlib.pyd"


#: Subtrees that must never be dragged in by the import closure below, whatever references them.
#: These are developer/interactive//test-only corners of CPython; a reference into one is either
#: unreachable in our paths or a sign something is importing far more than it should.
CLOSURE_DENY = (
    "Lib/test", "Lib/idlelib", "Lib/tkinter", "Lib/turtledemo", "Lib/lib2to3",
    "Lib/ensurepip", "Lib/pydoc_data", "Lib/distutils", "Lib/venv", "Lib/unittest",
    "Lib/site-packages/pip", "Lib/multiprocessing", "Lib/concurrent", "Lib/asyncio",
    "Lib/sqlite3", "Lib/xmlrpc", "Lib/wsgiref", "Lib/curses", "Lib/dbm", "Lib/ctypes/macholib",
)

#: Modules that resolve nowhere on Windows because their import sits in a platform branch that
#: cannot execute here (`if _mswindows: ... else: import _posixsubprocess`). Reviewed by hand --
#: this list is short on purpose, and anything joining it needs the same look.
PLATFORM_ABSENT = {
    "_posixsubprocess", "_posixshmem", "fcntl", "grp", "pwd", "posix", "termios", "tty",
    "resource", "syslog", "readline", "_scproxy", "java", "org", "vms_lib", "ce",
    "_frozen_importlib", "_frozen_importlib_external", "__main__", "antigravity", "this",
}


def shipped_scripts() -> list:
    """The installer's own .py files, as release.py defines them.

    Read from MODULE_SPEC rather than globbing work/scripts: most of that directory is developer
    tooling whose imports (capstone, keystone, frida) must never influence what ships.
    """
    try:
        import release
    except Exception:  # noqa: BLE001
        return []
    out = []
    for src, _dst in release.MODULE_SPEC["base"]["files"]:
        p = _REPO / src
        if p.suffix == ".py" and p.is_file():
            out.append(p)
    return out


def _module_candidates(name: str) -> list:
    """Where module `name` could live in the source interpreter, best first."""
    rel = name.replace(".", "/")
    return [f"Lib/{rel}.py", f"Lib/{rel}/__init__.py",
            f"DLLs/{rel}.pyd", f"Lib/site-packages/{rel}.py",
            f"Lib/site-packages/{rel}/__init__.py"]


def _imports_of(path: Path, package: str) -> set:
    """Every module name a source file imports, absolute-ised. Guarded ones included.

    Guarded imports (`try: import x except ImportError:`) are deliberately KEPT. They are cheap --
    almost all of them are small stdlib modules -- and the alternative is deciding, per site,
    whether the fallback path is one we can live with. A missing module that was supposed to be
    optional still changes behaviour, and `preflight._pid_alive` is the proof: its
    `from ctypes import wintypes` sits inside `except Exception: return True`, so losing the
    module did not raise, it just silently answered "the game is still running" forever.
    """
    import ast
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))
    except (OSError, SyntaxError, ValueError):
        return set()
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:                      # relative: resolve against the package
                base = package
                for _ in range(node.level - 1):
                    base = base.rpartition(".")[0]
                mod = f"{base}.{node.module}" if node.module else base
            else:
                mod = node.module or ""
            if not mod:
                continue
            out.add(mod)
            # `from pkg import name` may be importing a SUBMODULE, not an attribute. Adding both
            # is harmless: a name that is merely an attribute resolves to no file and is dropped.
            for a in node.names:
                if a.name != "*":
                    out.add(f"{mod}.{a.name}")
    return out


def _denied(rel: str) -> bool:
    return any(rel == d or rel.startswith(d + "/") for d in CLOSURE_DENY)


def resolve_python_deps(want: set, say=print) -> set:
    """Close the staged set under Python-level imports.

    THIS IS THE CHECK THAT WAS MISSING. `WHOLE_TREES = ("Lib/encodings",)` is not closed under
    import: `encodings/idna.py` imports `stringprep` and `unicodedata`, neither of which lives
    under Lib/encodings -- so the staged runtime had an idna codec that could not load. Because
    `socket.getaddrinfo()` pushes EVERY hostname through that codec, the trimmed installer could
    not resolve a single name: every download died with `LookupError: unknown encoding: idna`,
    which is not a URLError and so escaped fetch.py's handling entirely and crashed the run.
    Neither the import trace (its manifests were file:// URIs) nor --verify (--ai off, no network)
    could see it.

    Same mechanism found `ctypes/wintypes.py`, whose absence silently inverted
    `preflight._pid_alive` -- no error, just "the game is always running" forever.
    """
    import sys as _sys
    builtin = set(_sys.builtin_module_names)
    pending = [r for r in want if r.endswith(".py")]
    added, seen = set(), set(pending)
    unresolved = set()

    # SEED WITH THE INSTALLER'S OWN SCRIPTS, not just the interpreter's files.
    #
    # Without this the closure never reads the code that actually runs. `preflight.py` does
    # `from ctypes import wintypes` inside `except Exception: return True`, so a missing
    # wintypes.py raised nothing -- `_pid_alive` simply answered "still running" forever, which
    # makes preflight refuse to install ("close Alpha Centauri" for a game that already exited)
    # and makes the self-update handover time out. Silent, and unreachable from the interpreter's
    # own import graph.
    for own in shipped_scripts():
        for name in _imports_of(own, ""):
            top = name.split(".")[0]
            if top in builtin or top in PLATFORM_ABSENT:
                continue
            for cand in _module_candidates(name):
                if (SRC / cand).is_file() and not _denied(cand):
                    if cand not in want and cand not in added:
                        added.add(cand)
                        seen.add(cand)
                        pending.append(cand)
                    break

    while pending:
        rel = pending.pop()
        src = SRC / rel
        if not src.is_file():
            continue
        pkg = rel[len("Lib/"):] if rel.startswith("Lib/") else rel
        pkg = pkg[len("site-packages/"):] if pkg.startswith("site-packages/") else pkg
        pkg = pkg.rsplit("/", 1)[0].replace("/", ".") if pkg.endswith("__init__.py")             else pkg.rsplit("/", 1)[0].replace("/", ".")
        for name in _imports_of(src, pkg):
            top = name.split(".")[0]
            if top in builtin or name in builtin or top in PLATFORM_ABSENT                     or name in PLATFORM_ABSENT:
                continue
            hit = None
            for cand in _module_candidates(name):
                if (SRC / cand).is_file() and not _denied(cand):
                    hit = cand
                    break
            if hit is None:
                if "." not in name and top not in builtin:
                    unresolved.add(name)
                continue
            if hit not in want and hit not in added:
                added.add(hit)
                if hit not in seen:
                    seen.add(hit)
                    pending.append(hit)

    if added:
        say(f"  import closure added {len(added)} file(s): "
            + ", ".join(sorted(added)[:8]) + ("..." if len(added) > 8 else ""))
    if unresolved:
        say(f"  (unresolved, treated as absent: {', '.join(sorted(unresolved)[:12])})")
    return added


#: Written next to python.exe. WITHOUT IT the staged interpreter is not isolated at all: it puts
#: the PLAYER'S %APPDATA%\Python\Python312\site-packages AHEAD of our own, honours PYTHONPATH,
#: and executes their .pth files and usercustomize.py inside our process. `yaml` and `pefile` are
#: ordinary PyPI names someone may have under `pip install --user`, and this process rewrites
#: their game binary -- so a hijacked import is code execution, not merely a crash. A `._pth`
#: also disables the registry PythonPath entries, which `-E -s` on the launcher does not.
PTH_NAME = "python312._pth"
#: When this runtime was staged (wall clock, not a copied mtime).
STAMP_NAME = ".staged-at"
VERIFIED_NAME = ".verified-at"      # written by --verify on success; release.py requires it

#: The Windows 7 / 8 interpreter (CPython 3.8.10 embeddable + app-local UCRT, fetched by
#: fetch_python38.py into tools\python38). Staged WHOLESALE: the embeddable is already the minimal
#: interpreter (its stdlib is one zip), so there is nothing to trim and no trace to take -- but it is
#: probed and run through the installer exactly like the 3.12 runtime, because it runs the same
#: scripts on a Windows that cannot run anything else we ship.
SRC38 = _REPO / "tools" / "python38"
PTH38_NAME = "python38._pth"
PTH38_BODY = "python38.zip\n.\nLib\\site-packages\n"
#: Third-party packages the installer imports (pefile, PyYAML) are not in any embeddable; they come
#: from tools\python's site-packages -- the top-level packages the 3.12 PLAN names, copied WHOLE and
#: .py only. Whole, because the 3.12 trace saw PyYAML through its C loader (_yaml.pyd, cp312-only) and
#: never imported the pure parser modules the 3.8 copy will run on; .py only, because every .pyd there
#: is built for 3.12. Both packages are pure Python at heart and support 3.8 (pefile 2024.8, PyYAML 6.0).
SITE_PACKAGES = "Lib/site-packages"
#: What tools\python38 must hold to be the interpreter fetch_python38.py produces.
CORE38_FILES = ("python.exe", "python38.dll", "python38.zip", "vcruntime140.dll", "ucrtbase.dll",
                "api-ms-win-crt-runtime-l1-1-0.dll", "_ssl.pyd", "libssl-1_1.dll", "_ctypes.pyd",
                "LICENSE.txt", "PROVENANCE.txt")
PTH_BODY = "python312.zip\nLib\nDLLs\nLib\\site-packages\n.\n"

#: Never ship, whatever a trace says. A stray dev package is the single biggest release-payload
#: defect and it is invisible in a working tree.
DEV_ONLY = (
    "frida", "frida_tools", "numpy", "numpy.libs", "PIL", "pillow", "pip", "pytest", "_pytest",
    "capstone", "keystone", "unicorn", "pyghidra", "jpype", "_jpype", "pygments", "prompt_toolkit",
    "websockets", "colorama", "pluggy", "wcwidth", "iniconfig", "setuptools", "pkg_resources",
    "xdist", "execnet", "pytest_xdist",
)


class BuildError(Exception):
    pass


def load_trace(path: Path) -> list:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BuildError(f"could not read the import trace at {path}: {e}\n"
                         f"Run: py work\\scripts\\trace_imports.py --out {path}")
    failed = [r["label"] for r in doc.get("runs", []) if r.get("returncode")
              and r["label"] not in EXPECTED_NONZERO]
    if failed:
        raise BuildError(
            f"the trace was produced by a run that FAILED ({', '.join(failed)}), so the module "
            f"list is incomplete. Fix the failure and re-trace rather than shipping a guess.")
    files = doc.get("interpreter_files")
    if not isinstance(files, list) or not files:
        raise BuildError(f"{path} carries no interpreter_files")
    return files


#: Runs whose non-zero exit is by design (see trace_imports.py; the two sets must agree).
EXPECTED_NONZERO = {"bootstrap-selfupdate", "check"}


def _is_dev(rel: str) -> bool:
    parts = rel.split("/")
    if "site-packages" not in parts:
        return False
    i = parts.index("site-packages")
    if i + 1 >= len(parts):
        return False
    name = parts[i + 1]
    stem = name.split("-")[0].split(".")[0]
    return stem in DEV_ONLY or name in DEV_ONLY


def plan(trace_files: list) -> list:
    """The full relative-path list to stage, sorted and de-duplicated."""
    want = set()

    for rel in trace_files:
        if _is_dev(rel):
            raise BuildError(
                f"the trace contains a developer-only package ({rel}). The installer must not "
                f"import it -- fix the import rather than shipping the package.")
        want.add(rel)

    for rel in CORE_FILES:
        if not (SRC / rel).is_file():
            raise BuildError(f"required runtime file missing from {SRC}: {rel}")
        want.add(rel)

    for tree in WHOLE_TREES:
        d = SRC / tree
        if not d.is_dir():
            raise BuildError(f"required runtime tree missing from {SRC}: {tree}")
        for p in d.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts:
                want.add(p.relative_to(SRC).as_posix())

    # Python-level closure FIRST (it can add .pyd files), then the native closure, then repeat
    # until neither adds anything -- a newly added .py can need a new .pyd, which can need a new
    # DLL.
    for _ in range(8):
        grew = resolve_python_deps(want)
        want |= grew
        native = resolve_native(want)
        want |= native
        if not grew and not native:
            break

    dropped = want & EXCLUDE
    if dropped:
        want -= dropped
        say_drop = ", ".join(sorted(dropped))
        print(f"  excluded (no reachable importer): {say_drop}")

    missing = [r for r in sorted(want) if not (SRC / r).is_file()]
    if missing:
        raise BuildError("traced files that no longer exist: " + ", ".join(missing[:10]))
    return sorted(want)


def stage(files: list, dest: Path, say=print) -> int:
    """Copy the plan into `dest`. Returns the total byte size."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    total = 0
    for rel in files:
        src = SRC / rel
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        total += out.stat().st_size
    pth = dest / PTH_NAME
    pth.write_text(PTH_BODY, encoding="ascii")
    total += pth.stat().st_size
    # A real build stamp. shutil.copy2 PRESERVES the source mtime, so every staged file
    # carries tools\python's timestamps -- release.py's "is this runtime stale?" check was
    # comparing today's scripts against a 2024 python.exe and firing every single time.
    (dest / STAMP_NAME).write_text(str(time.time()), encoding="ascii")
    say(f"  staged {len(files)} files, {total:,} bytes ({total / 1048576:.1f} MB) -> {dest}")
    return total


def third_party_tops(files: list) -> list:
    """The top-level site-packages names (a package dir or a module file) in a 3.12 plan."""
    tops = set()
    for rel in files:
        if rel.startswith(SITE_PACKAGES + "/"):
            top = rel[len(SITE_PACKAGES) + 1:].split("/", 1)[0]
            if not top.endswith((".dist-info", ".pth", ".pyd", ".dll")):
                tops.add(top)
    return sorted(tops)


def stage38(dest: Path, files: list, say=print) -> int:
    """Copy tools\\python38 into `dest` as the shipped tools\\python38, plus the third-party packages
    the 3.12 plan `files` names (see SITE_PACKAGES). Returns the byte size.

    No plan, no closure for the interpreter itself: every file of the embeddable ships. A missing
    core file means fetch_python38.py was never run (or ran against a different package) -- refuse
    rather than stage a runtime that cannot start on the one Windows it exists for."""
    dest = Path(dest)
    if not SRC38.is_dir():
        raise BuildError(f"no Windows 7 interpreter at {SRC38}: run  py work\\scripts\\fetch_python38.py")
    missing = [f for f in CORE38_FILES if not (SRC38 / f).is_file()]
    if missing:
        raise BuildError(f"{SRC38} lacks {missing}: re-run fetch_python38.py")
    if dest.exists():
        shutil.rmtree(dest)
    total = 0
    for p in sorted(SRC38.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        rel = p.relative_to(SRC38)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)
        total += out.stat().st_size
    tops = third_party_tops(files)
    if not tops:
        raise BuildError("the 3.12 plan names no site-packages module, yet the installer imports pefile and yaml: "
                         "the trace is incomplete")
    n_tp = 0
    for top in tops:
        src = SRC / SITE_PACKAGES / top
        if src.is_dir():
            for p in sorted(src.rglob("*.py")):
                if "__pycache__" in p.parts:
                    continue
                out = dest / SITE_PACKAGES / p.relative_to(SRC / SITE_PACKAGES)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, out)
                total += out.stat().st_size
                n_tp += 1
        elif src.is_file() and src.suffix == ".py":
            out = dest / SITE_PACKAGES / top
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
            total += out.stat().st_size
            n_tp += 1
        else:
            raise BuildError(f"third-party {top!r} in the plan is neither a package dir nor a .py under {SRC / SITE_PACKAGES}")
    (dest / PTH38_NAME).write_text(PTH38_BODY, encoding="ascii")   # isolation, as for 3.12
    (dest / STAMP_NAME).write_text(str(time.time()), encoding="ascii")
    say(f"  staged Windows 7 interpreter: {total:,} bytes ({total / 1048576:.1f} MB) -> {dest} "
        f"(+ {n_tp} .py of {', '.join(tops)})")
    return total


#: Run INSIDE the staged interpreter. Everything here is a property the four installer runs
#: cannot observe, because they are offline and never wait on a process.
_PROBE = r"""
import os, socket, sys, traceback

fails = []

def check(label, fn):
    try:
        fn()
    except BaseException as e:
        fails.append(f"{label}: {type(e).__name__}: {e}")

# 1. HOSTNAME RESOLUTION. socket.getaddrinfo() pushes EVERY str host through the `idna` codec,
#    including a literal IPv4 address -- so a missing stringprep/unicodedata makes the codec
#    unloadable and kills ALL networking with `LookupError: unknown encoding: idna`. That is not
#    a URLError, so fetch.py's handling never sees it and a handled network error becomes a
#    crash. No offline run and no file:// trace can reach this.
check("idna codec", lambda: __import__("codecs").lookup("idna"))

def _resolve(host):
    # A gaierror is a CORRECT outcome -- it means the codec worked and DNS answered "no such
    # name". Only a LookupError (dead idna codec) is a defect. The first version of this probe
    # failed on `example.invalid` and blamed the runtime for DNS doing its job.
    try:
        socket.getaddrinfo(host, 443)
    except socket.gaierror:
        pass
check("getaddrinfo (name)", lambda: _resolve("example.invalid"))
check("getaddrinfo (literal ip)", lambda: _resolve("93.184.216.34"))

# 2. TLS. The context is built for every fetch, file:// included, but the cert store is not
#    touched until a real handshake would be.
def _tls():
    import ssl
    ctx = ssl.create_default_context()
    assert ctx.get_ca_certs() is not None
check("ssl default context", _tls)

# 3. HASHES. sha256 verifies every download; md5 is binary identity.
def _hash():
    import hashlib
    assert hashlib.sha256(b"x").hexdigest()
    assert hashlib.md5(b"x").hexdigest()
check("hashlib sha256+md5", _hash)

# 4. _pid_alive. A missing ctypes.wintypes does not raise -- it silently answers "still running"
#    forever, which makes preflight refuse to install and the self-update handover time out.
def _pid():
    sys.path.insert(0, os.environ["LONGEVITY_SCRIPTS"])
    import preflight
    assert preflight._pid_alive(999999) is False, "a dead pid was reported as alive"
    from ctypes import wintypes            # the import whose failure it swallows
    assert wintypes.DWORD is not None
check("preflight._pid_alive", _pid)

# 5. traceback formatting over a NON-ASCII source line -- the crash-report path, which reaches
#    an unguarded `import unicodedata`. Our own apply_patches.py carries em dashes.
def _tb():
    try:
        raise ValueError("\u2014 em dash \u2014")
    except ValueError:
        assert "em dash" in traceback.format_exc()
check("traceback with non-ASCII", _tb)

# 6. Codecs a non-en-US player needs.
for enc in ("cp1251", "cp932", "cp936", "cp949", "cp950", "mbcs", "oem", "koi8-r", "cp437"):
    check(f"codec {enc}", lambda e=enc: __import__("codecs").lookup(e))

# 7. ISOLATION. With a ._pth the player's own site-packages and PYTHONPATH must be ignored.
def _iso():
    bad = [q for q in sys.path if "AppData" in q or "site-packages" in q.replace(
        os.path.dirname(os.path.dirname(os.__file__)), "")]
    assert not any("AppData" in q for q in sys.path), f"user site on sys.path: {sys.path}"
check("sys.path isolation", _iso)

print("PROBE_FAILURES=" + str(len(fails)))
for f in fails:
    print("  PROBE FAIL: " + f)
sys.exit(1 if fails else 0)
"""


ZIP_NAME = "python312.zip"


def zip_stdlib(dest: Path, say=print) -> int:
    """Move the stdlib into python312.zip as bytecode. Returns the net bytes saved.

    WHY, and what it costs (all measured):
      * -4.7 MB RESIDENT. The installer lives on the player's disk permanently -- it IS the
        updater -- so this is the cost they keep paying, and a zipped stdlib also never writes
        __pycache__, which is another ~1.9 MB they would otherwise pay on first run.
      * +0.5 MB DOWNLOAD. Bytecode compresses WORSE than source, so this is a genuine trade
        rather than a free win. Shipping loose .pyc is the worst of both: barely smaller on disk
        and half a megabyte bigger to download.
      * Startup is unchanged (~116 ms zipped vs ~109 ms warm-cache loose). Suppressing bytecode
        with -B instead is NOT an alternative: 342 ms per process, paid on every one of the
        installer's several subprocess launches.

    site-packages stays loose: yaml and pefile are third-party and are easier to inspect, replace
    or version there, and they are a small share of the total.

    Compiled by the SOURCE interpreter, which is the same build as the staged one, so the .pyc
    magic number cannot disagree with the interpreter that has to read it.
    """
    dest = Path(dest)
    lib = dest / "Lib"
    before = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())

    src_py = SRC / "python.exe"
    r = subprocess.run([str(src_py), "-m", "compileall", "-b", "-q",
                        "-x", r"[\\/]site-packages[\\/]", str(lib)],
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        say(f"  WARNING: compileall failed ({r.returncode}); leaving the stdlib loose")
        say("    " + "\n    ".join((r.stdout + r.stderr).splitlines()[-5:]))
        return 0

    pycs = [f for f in lib.rglob("*.pyc")
            if "site-packages" not in f.parts and "__pycache__" not in f.parts]
    if not pycs:
        say("  WARNING: compileall produced no .pyc; leaving the stdlib loose")
        return 0

    zpath = dest / ZIP_NAME
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(pycs):
            arc = f.relative_to(lib).as_posix()
            info = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, f.read_bytes())

    # Remove what moved into the archive: the .pyc AND the .py they came from.
    for f in pycs:
        f.unlink(missing_ok=True)
        f.with_suffix(".py").unlink(missing_ok=True)
    clean_pycache(dest, say=lambda *a: None)
    for d in sorted(lib.rglob("*"), reverse=True):
        if d.is_dir():
            try:
                d.rmdir()          # only succeeds when empty
            except OSError:
                pass

    after = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file())
    say(f"  stdlib -> {ZIP_NAME}: {len(pycs)} modules, "
        f"{before - after:+,} bytes on disk")
    return before - after


def clean_pycache(dest: Path, say=print) -> int:
    """Remove every __pycache__ from the staged tree. Returns bytes reclaimed.

    Belt and braces alongside PYTHONDONTWRITEBYTECODE: the verify and probe runs execute the real
    installer, which spawns further processes, and one of them inheriting a different environment
    is enough to leave bytecode behind. That inflated every size this script reported after a
    verify -- and while release.py filters __pycache__ out of the archive, a stale .pyc sitting in
    the shipped tree is a correctness question, not just a size one.
    """
    freed = 0
    for d in sorted(Path(dest).rglob("__pycache__"), reverse=True):
        for f in d.rglob("*"):
            if f.is_file():
                freed += f.stat().st_size
        shutil.rmtree(d, ignore_errors=True)
    if freed:
        say(f"  cleaned {freed:,} bytes of __pycache__ from the staged tree")
    return freed


def probe(runtime: Path, say=print) -> bool:
    """Assert the properties the installer runs cannot reach. Returns True on success."""
    py = Path(runtime) / "python.exe"
    script = Path(tempfile.mkdtemp(prefix="longevity-probe-")) / "probe.py"
    script.write_text(_PROBE, encoding="utf-8")
    env = dict(os.environ)
    env["LONGEVITY_SCRIPTS"] = str(_SCRIPTS)
    env["PYTHONDONTWRITEBYTECODE"] = "1"      # never pollute the tree being measured
    # A POISONED environment on purpose: a correctly isolated runtime must ignore both.
    env["PYTHONPATH"] = str(script.parent / "does-not-exist")
    try:
        p = subprocess.run([str(py), str(script)], capture_output=True, text=True,
                           env=env, stdin=subprocess.DEVNULL, timeout=300)
    except OSError as e:
        say(f"  probe could not run: {e}")
        return False
    finally:
        shutil.rmtree(script.parent, ignore_errors=True)
    for line in (p.stdout + p.stderr).splitlines():
        if "PROBE FAIL" in line or "Error" in line or "Traceback" in line:
            say("  " + line)
    say(f"  probe {'ok' if p.returncode == 0 else 'FAILED'} (exit {p.returncode})")
    return p.returncode == 0


def verify(runtime: Path, say=print) -> bool:
    """Run the real installer flow against the STAGED runtime. The only real evidence.

    A missing stdlib module or support DLL shows up here as an ImportError or a failed run --
    which is exactly what would otherwise happen on a player's machine, except here we see it.
    """
    import config
    py = Path(runtime) / "python.exe"
    if not py.is_file():
        say(f"  VERIFY FAILED: no python.exe in {runtime}")
        return False
    bak = config.terranx_bak(required=False)
    if not bak.exists():
        say(f"  VERIFY SKIPPED: no clean base binary at {bak}")
        return False

    root = Path(tempfile.mkdtemp(prefix="longevity-verify-"))
    try:
        game = root / "game"
        game.mkdir()
        shutil.copy2(bak, game / config.exe_name())
        (game / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
        env = dict(os.environ)
        env["LONGEVITY_NO_WAIT"] = "1"
        env.pop("PYTHONPATH", None)          # the staged runtime must stand alone
        # DO NOT WRITE BYTECODE INTO THE THING BEING MEASURED. The verify runs were leaving ~2 MB
        # of __pycache__ inside the staged tree, so every size reported after a verify was wrong
        # -- and while release.py filters __pycache__ out of the zip, the player still pays it on
        # their disk at first run, which is the number that was being under-reported.
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        ok = True
        # (label, extra args, expected exit code). `--check` against a manifest that does not
        # exist must reach its own failure verdict (12): that proves fetch/manifest/receipt all
        # import in the trimmed runtime, which is what a player's game launch will exercise.
        for label, extra, want in (("install", ["--ai", "off"], 0),
                                   ("re-run", ["--ai", "off"], 0),
                                   ("check", ["--check", "--manifest",
                                              str(root / "no-such-manifest.json")], 12),
                                   ("repair", ["--repair"], 0),
                                   ("uninstall", ["--uninstall"], 0)):
            cmd = [str(py), str(_SCRIPTS / "install.py"), "--no-wait",
                   "--game-dir", str(game)] + extra
            p = subprocess.run(cmd, capture_output=True, text=True, env=env,
                               stdin=subprocess.DEVNULL, timeout=1800)
            mark = "ok" if p.returncode == want else "FAILED"
            say(f"  verify {label:10} {mark} (exit {p.returncode}, expected {want})")
            if p.returncode != want:
                ok = False
                for line in (p.stdout + p.stderr).splitlines()[-15:]:
                    say("    " + line)
        return ok
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    apr = argparse.ArgumentParser(description="Stage the shipped Python runtime.")
    apr.add_argument("--trace", default=str(DEFAULT_TRACE))
    apr.add_argument("--out", default=str(_REPO / "work" / "build" / "runtime"))
    apr.add_argument("--verify", action="store_true",
                     help="run the installer against the staged runtime afterwards")
    apr.add_argument("--list", action="store_true", help="print the plan and exit")
    apr.add_argument("--no-zip-stdlib", action="store_true",
                     help="keep the stdlib as loose .py files (smaller download, ~4.7 MB more "
                          "on the player's disk forever)")
    apr.add_argument("--out38", default=str(_REPO / "work" / "build" / "runtime38"),
                     help="where the Windows 7 / 8 interpreter (tools\\python38) is staged")
    apr.add_argument("--skip-38", action="store_true",
                     help="stage only the 3.12 runtime (a release needs both; dev use)")
    args = apr.parse_args()

    try:
        files = plan(load_trace(Path(args.trace)))
    except BuildError as e:
        print(f"ERROR: {e}")
        return 2

    if args.list:
        for rel in files:
            print(rel)
        return 0

    before = sum(p.stat().st_size for p in SRC.rglob("*") if p.is_file())
    total = stage(files, Path(args.out))
    if not args.no_zip_stdlib:
        total -= zip_stdlib(Path(args.out))
    print(f"  was {before:,} bytes ({before / 1048576:.0f} MB) -> "
          f"{total / before * 100:.1f}% of the original")

    runtimes = [Path(args.out)]
    if args.skip_38:
        # A runtime38 staged earlier is now suspect (the scripts may have moved on): drop its verified
        # marker so release.py refuses it until a full run re-stages and re-verifies it.
        stale = Path(args.out38) / VERIFIED_NAME
        if stale.exists():
            stale.unlink()
            print(f"  --skip-38: {stale} removed; runtime38 must be re-verified before a release")
    else:
        try:
            stage38(Path(args.out38), files)
        except BuildError as e:
            print(f"ERROR: {e}")
            return 2
        runtimes.append(Path(args.out38))

    if args.verify:
        # Both interpreters run the same scripts; both are probed and run the installer end to end.
        # The 3.8 run on this Windows 10/11 box proves the scripts are 3.8-clean and the embeddable
        # complete; only a Windows 7 machine can prove the loader side (see ACTION_ITEMS, Win7).
        all_ok = True
        for rt in runtimes:
            print(f"  -- verifying {rt.name}")
            ok = probe(rt)           # properties the installer runs cannot observe
            ok = verify(rt) and ok   # the installer itself, end to end
            clean_pycache(rt)
            final = sum(f.stat().st_size for f in rt.rglob("*") if f.is_file())
            print(f"  final: {final:,} bytes ({final / 1048576:.1f} MB)")
            if not ok:
                print(f"\nThe staged runtime {rt.name} did NOT pass verification -- do not ship it.")
                all_ok = False
                continue
            # The marker release.runtime_stale() looks for: written only after the probes AND the
            # end-to-end install passed, and always newer than .staged-at. A runtime that was
            # staged and then failed here has the stamp but not this.
            (rt / VERIFIED_NAME).write_text(str(time.time()), encoding="ascii")
        if not all_ok:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
