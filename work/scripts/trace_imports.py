"""Record exactly which interpreter files the installer needs, by RUNNING it.

The installer payload is ~96% bundled CPython (428 MB, and double that once the resident copy
exists). Trimming it means deciding which stdlib modules ship -- and a hand-written guess at that
list is the classic way to produce a release that dies on someone else's machine with an
ImportError we never saw, because the module it wanted was present on the dev box.

So the list is MEASURED, not declared. This drives the real entry points through the real bundled
interpreter, dumps `sys.modules` at exit, and maps each module to the file that backed it. What
comes out is a set of concrete paths under tools\\python.

Usage:
    py work\\scripts\\trace_imports.py --out work\\build\\import-trace.json

It needs a clean base binary to patch (config.terranx_bak) and works in a scratch directory; it
never touches the real game install.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
_REPO = _SCRIPTS.parent.parent

#: Scenarios whose non-zero exit is by design: the self-update run ends in "UPDATE HANDED OVER"
#: with a code the launcher understands, and `--check` answers 10 ("updates available") over its
#: pipe. build_runtime.EXPECTED_NONZERO must agree.
EXPECTED_NONZERO = {"bootstrap-selfupdate", "check"}
sys.path.insert(0, str(_SCRIPTS))

import config  # noqa: E402
import version as _ver  # noqa: E402

PY = _REPO / "tools" / "python" / "python.exe"
PY_ROOT = _REPO / "tools" / "python"

#: Written into a shim directory and put on PYTHONPATH, so it runs in EVERY child process --
#: including the ones the installer spawns for itself, which is where the self-update path lives.
_SHIM = '''
import atexit, json, os, sys

def _dump():
    out = os.environ.get("LONGEVITY_IMPORT_TRACE")
    if not out:
        return
    seen = {}
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        seen[name] = f
    try:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(seen) + "\\n")
    except OSError:
        pass

atexit.register(_dump)
'''


def _scratch_game(root: Path) -> Path:
    """A throwaway game directory with a clean base binary in it."""
    bak = config.terranx_bak(required=False)
    if not bak.exists():
        raise SystemExit(f"need a clean base binary; not found at {bak}")
    g = root / "game"
    g.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bak, g / config.exe_name())
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    prax = config.game_dir(required=False) / "prax.dll.bak"
    if prax.is_file():
        shutil.copy2(prax, g / "prax.dll")     # exercise the companion path too
    return g


SEED = bytes(range(32))


def _fake_payload(root: Path) -> Path:
    """A minimal REPO-SHAPED payload, enough for bootstrap.deploy() to accept it.

    Deliberately not the real 428 MB tree: what is being traced here is generation 1's
    download -> extract -> deploy -> swap, all of which happens before the new payload is ever
    executed. Generation 2's own imports are covered by the direct install runs.
    """
    p = root / "fakepayload"
    (p / "work" / "scripts").mkdir(parents=True, exist_ok=True)
    (p / "work" / "patches").mkdir(parents=True, exist_ok=True)
    (p / "tools" / "python").mkdir(parents=True, exist_ok=True)
    (p / "work" / "run-install.bat").write_bytes(b"@echo off\r\n")
    (p / "work" / "scripts" / "install.py").write_text("x = 1\n", encoding="ascii")
    (p / "work" / "scripts" / "bootstrap.py").write_text("y = 1\n", encoding="ascii")
    (p / "work" / "patches" / "patches.yaml").write_text("target: {}\n", encoding="ascii")
    (p / "tools" / "python" / "python.exe").write_bytes(b"MZfake")
    return p


def _publish(root: Path, *, latest: str, with_base: bool, name: str):
    """A signed local manifest plus the archives it points at."""
    sys.path.insert(0, str(_SCRIPTS))
    import sign_manifest as sm
    import hashlib

    pub = root / name
    pub.mkdir(parents=True, exist_ok=True)

    def _entry(archive: Path, version: str, required: bool) -> dict:
        return {"version": version, "required": required, "url": archive.as_uri(),
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "size": archive.stat().st_size}

    mods = {}
    movies = pub / f"movies-hd-{latest}.zip"
    with zipfile.ZipFile(movies, "w") as z:
        z.writestr("movies/hd/probe.mp4", b"probe")
    mods["movies-hd"] = _entry(movies, latest, False)

    if with_base:
        payload = _fake_payload(pub)
        base = pub / f"base-{latest}.zip"
        with zipfile.ZipFile(base, "w") as z:
            for f in sorted(payload.rglob("*")):
                if f.is_file():
                    z.write(f, str(f.relative_to(payload)).replace("\\", "/"))
        mods["base"] = _entry(base, latest, True)

    doc = {
        "schema": 1, "protocol": 1, "product": "longevity-vaccine",
        "latest": latest, "min_upgradable_from": "0.0.0",
        "manual_install_required": False, "manual_install_reason": None,
        "unsupported_versions": [], "unsupported_targets": [], "yanked": [],
        "min_free_bytes": 1 << 20, "modules": mods,
    }
    m = pub / "manifest.json"
    m.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    sm.sign_file(SEED, m)
    return m, sm.public_key(SEED).hex()


def run_all(root: Path, trace_file: Path) -> list:
    """Drive every entry point that ships. Returns [(label, returncode)]."""
    shim = root / "shim"
    shim.mkdir(parents=True, exist_ok=True)
    # sitecustomize, NOT usercustomize: the latter is only imported when the per-user site is
    # enabled, and PYTHONNOUSERSITE above disables it -- which silently killed the tracer.
    (shim / "sitecustomize.py").write_text(_SHIM, encoding="ascii")

    game = _scratch_game(root)
    # Three manifests, because the bootstrap branches on the version comparison and each branch
    # imports a different part of the runtime.
    manifest, pk = _publish(root, latest="9.9.9", with_base=False, name="published")
    current, _ = _publish(root, latest=_ver.VERSION, with_base=False,
                          name="published-current")
    selfup, _ = _publish(root, latest="9.9.9", with_base=True, name="published-selfupdate")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(shim)
    env["LONGEVITY_IMPORT_TRACE"] = str(trace_file)
    env["LONGEVITY_NO_WAIT"] = "1"
    env["LONGEVITY_TRUST_KEY"] = pk
    # Inherited by the processes the installer spawns for ITSELF, which `-s` on our own command
    # line cannot reach: bootstrap runs install.py via sys.executable with no flags, and that
    # child was picking up the dev box's %APPDATA% user site (_distutils_hack, pywin32_bootstrap).
    env["PYTHONNOUSERSITE"] = "1"

    install = _SCRIPTS / "install.py"
    boot = _SCRIPTS / "bootstrap.py"
    runs = [
        ("install", [install, "--ai", "off"]),
        ("reinstall", [install, "--ai", "off"]),
        ("force", [install, "--ai", "off", "--force"]),
        ("update", [install, "--update", "--manifest", str(manifest),
                    "--modules", "movies-hd", "--no-prompt"]),
        # The bootstrap's in-place branch: no new installer needed, so it hands off to
        # install.py as a worker child.
        ("bootstrap-inplace", [boot, "--manifest", str(current),
                               "--modules", "movies-hd", "--no-prompt"]),
        # The self-update branch: download, verify, extract, deploy, swap, spawn generation 2.
        ("bootstrap-selfupdate", [boot, "--manifest", str(selfup),
                                  "--modules", "movies-hd", "--no-prompt"]),
        # The game's launch-time query -- the most-run command in the product. It must be in
        # the trace or the trimmed runtime is measured for everything except it.
        ("check", [install, "--check", "--manifest", str(current)]),
        ("repair", [install, "--repair"]),
        ("uninstall", [install, "--uninstall"]),
    ]
    results = []
    for label, argv in runs:
        # -s: NO per-user site-packages. The dev box has its own
        # %APPDATA%\Python\Python312\site-packages, and a module that resolved from there
        # would have been silently dropped from the plan (to_paths discards anything outside
        # tools\python), producing a shipped runtime missing a file nobody could account for.
        # PYTHONPATH still carries the shim, so -E cannot be used here.
        cmd = [str(PY), "-s", str(argv[0]), "--no-wait", "--game-dir", str(game)] + \
              [str(a) for a in argv[1:]]
        p = subprocess.run(cmd, capture_output=True, text=True, env=env,
                           stdin=subprocess.DEVNULL, timeout=1800)
        results.append((label, p.returncode, (p.stdout + p.stderr)[-2000:]))
    return results


def collect(trace_file: Path) -> dict:
    """Merge every dumped sys.modules into one {module: file} map."""
    merged = {}
    for line in trace_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            merged.update({k: v for k, v in json.loads(line).items() if v})
        except ValueError:
            continue
    return merged


def to_paths(modules: dict) -> tuple[list, list]:
    """Split the traced files into (inside the bundled interpreter, outside it)."""
    root = PY_ROOT.resolve()
    inside, outside = set(), set()
    for f in modules.values():
        try:
            p = Path(f).resolve()
        except (OSError, ValueError):
            continue
        if not p.exists():
            continue
        try:
            p.relative_to(root)
        except ValueError:
            outside.add(str(p))
            continue
        inside.add(p.relative_to(root).as_posix())
    return sorted(inside), sorted(outside)


def main() -> int:
    apr = argparse.ArgumentParser(description=__doc__)
    apr.add_argument("--out", default=str(_REPO / "work" / "build" / "import-trace.json"))
    apr.add_argument("--keep", action="store_true", help="keep the scratch directory")
    args = apr.parse_args()

    if not PY.is_file():
        raise SystemExit(f"bundled interpreter not found at {PY}")

    root = Path(tempfile.mkdtemp(prefix="longevity-trace-"))
    trace_file = root / "trace.jsonl"
    try:
        results = run_all(root, trace_file)
        for label, code, tail in results:
            print(f"  {label:18} exit {code}")
            if code != 0:
                print("    " + "\n    ".join(tail.splitlines()[-12:]))
        if not trace_file.is_file():
            raise SystemExit("no trace was produced -- the shim never ran")
        modules = collect(trace_file)
        inside, outside = to_paths(modules)

        # Anything loaded from OUTSIDE the bundled interpreter must be one of the installer's own
        # scripts or the tracing shim. Silently discarding the rest is how a needed module
        # vanishes from the plan without a word.
        allowed = (str(_SCRIPTS.resolve()).lower(), str(root.resolve()).lower())
        strays = [f for f in outside if not f.lower().startswith(allowed)]
        if strays:
            print("\nERROR: modules were loaded from outside the bundled interpreter and would "
                  "be silently dropped from the shipped runtime:")
            for f in strays[:20]:
                print(f"  {f}")
            print("Re-run with a clean environment (no PYTHONPATH beyond the shim).")
            return 2
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "runs": [{"label": l, "returncode": c} for l, c, _ in results],
            "module_count": len(modules),
            "interpreter_files": inside,
            "outside_files": outside,
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\n{len(modules)} modules; {len(inside)} files inside tools\\python")
        print(f"written: {out}")
        # A run whose non-zero exit is BY DESIGN is not a failed run. build_runtime.py carries
        # the same set (EXPECTED_NONZERO) for its own reading of the trace; without the
        # exemption here, every release_all.py run stopped at the trace step because the
        # bootstrap self-update scenario exits 3 on purpose.
        failed = [l for l, c, _ in results if c != 0 and l not in EXPECTED_NONZERO]
        if failed:
            print(f"\nWARNING: these runs failed, so their imports may be MISSING "
                  f"from the trace: {', '.join(failed)}")
            return 1
        return 0
    finally:
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)
        else:
            print(f"scratch kept: {root}")


if __name__ == "__main__":
    sys.exit(main())
