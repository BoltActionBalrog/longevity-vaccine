"""Write a SIGNED test manifest for exercising the in-game update prompt, and print the launch
recipe. Developer tool: signs with the test seed bytes(range(32)) (the same key
work\\tests\\test_install_e2e.py uses); the game must run with LONGEVITY_TRUST_KEY set to that
key's public hex so the resident installer trusts it. Nothing here touches the game install.

    py work\\scripts\\dev_test_manifest.py <scenario> [--out DIR] [--game-version V]

Scenarios (what the prompt should show):
    nothing   latest == the installed version               -> no prompt (F1)
    base      core update available (latest 9.9.9)          -> F2 only
    pack      a NEW pack (HD Cinematics) the install lacks  -> F3 only
    both      core update + a new pack + a stale pack       -> F2 then F3
    manual    kill switch (bootstrap_defect)                -> F6
    yanked    latest is yanked                              -> nothing (F1)
    protocol  protocol 99                                   -> F6 (protocol)
    base-real a REAL installer archive built from this checkout, stamped 9.9.9, published
              with a file:// URL -> F2, and "Quit and update" performs a genuine self-update
              (download, verify, swap in the new resident updater, re-install, receipt 9.9.9).
              Afterwards re-run the checkout's installer to record 0.1.0 again.

In every other scenario the module URLs point at a non-existent local path on purpose: the
CHECK only needs the manifest, and a hand-off fails cleanly at the fetch (no disk change).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import sign_manifest as sm   # noqa: E402
import version as ver        # noqa: E402

SEED = bytes(range(32))
REAL_VERSION = "9.9.9"
_REPO = _SCRIPTS.parent.parent


def build_base_archive(out: Path, stamp: str = REAL_VERSION) -> Path:
    """A complete installer payload from this checkout (the ONE shipped layout, as
    test_install_e2e's payload fixture and release.py's MODULE_SPEC lay it out), with
    scripts/version.py stamped `stamp`, zipped as `out/base-<stamp>.zip`. Needs the staged
    runtime work\\build\\runtime (build_runtime.py) and a built uimod.dll."""
    import re
    import shutil
    import zipfile
    runtime = _REPO / "work" / "build" / "runtime"
    dll = _REPO / "src" / "uimod" / "build" / "Release" / "uimod.dll"
    if not (runtime / "python.exe").is_file():
        raise SystemExit(f"no staged runtime at {runtime}: run work\\scripts\\build_runtime.py first")
    if not dll.is_file():
        raise SystemExit(f"no DLL at {dll}: build it first (src\\uimod\\build.bat)")
    root = out / f"payload-{stamp}"
    shutil.rmtree(root, ignore_errors=True)
    (root / "scripts").mkdir(parents=True)
    for f in _SCRIPTS.glob("*.py"):
        shutil.copy2(f, root / "scripts" / f.name)
    shutil.copy2(_REPO / "work" / "run-install.bat", root / "scripts" / "run-install.bat")
    shutil.copytree(_REPO / "work" / "patches", root / "patches")
    shutil.copy2(_REPO / "work" / "CHANGELOG.md", root / "CHANGELOG.txt")
    shutil.copytree(runtime, root / "tools" / "python")
    (root / "src" / "uimod" / "build" / "Release").mkdir(parents=True)
    shutil.copy2(dll, root / "src" / "uimod" / "build" / "Release" / "uimod.dll")
    shutil.copytree(_REPO / "src" / "uimod" / "third_party" / "ffmpeg" / "bin",
                    root / "src" / "uimod" / "third_party" / "ffmpeg" / "bin")
    (root / "art").mkdir()
    shutil.copy2(_REPO / "work" / "art" / "longevity_sm.pcx", root / "art" / "longevity_sm.pcx")
    vp = root / "scripts" / "version.py"
    src = vp.read_text(encoding="utf-8")
    stamped, n = re.subn(r'^VERSION = "[^"]+"', f'VERSION = "{stamp}"', src, count=1, flags=re.M)
    if n != 1:
        raise SystemExit("could not stamp VERSION in version.py")
    vp.write_text(stamped, encoding="utf-8")
    archive = out / f"base-{stamp}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, str(f.relative_to(root)).replace("\\", "/"))
    shutil.rmtree(root, ignore_errors=True)
    return archive


def build(scenario: str, game_version: str, out: Path = None) -> dict:
    latest = game_version
    modules = {}
    doc = {
        "schema": 1, "protocol": 1, "product": "longevity-vaccine",
        "latest": latest, "min_upgradable_from": "0.0.0",
        "manual_install_required": False, "manual_install_reason": None,
        "unsupported_versions": [], "unsupported_targets": [], "yanked": [],
        "modules": modules,
    }
    def module(name, v, size):
        modules[name] = {"version": v, "url": "file:///C:/nonexistent/lv-test/" + name + ".zip",
                         "sha256": "0" * 64, "size": size}
    if scenario == "base":
        doc["latest"] = "9.9.9"
    elif scenario == "pack":
        module("movies-hd", "9.9.9", 1395864371)
    elif scenario == "both":
        doc["latest"] = "9.9.9"
        module("movies-hd", "9.9.9", 1395864371)
        module("portraits-hd", "9.9.9", 671088640)
    elif scenario == "manual":
        doc["manual_install_required"] = True
        doc["manual_install_reason"] = "bootstrap_defect"
    elif scenario == "yanked":
        doc["latest"] = "9.9.9"
        doc["yanked"] = ["9.9.9"]
    elif scenario == "protocol":
        doc["protocol"] = 99
    elif scenario == "base-real":
        import hashlib
        archive = build_base_archive(out)
        doc["latest"] = REAL_VERSION
        modules["base"] = {"version": REAL_VERSION, "required": True, "url": archive.as_uri(),
                           "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                           "size": archive.stat().st_size}
    elif scenario != "nothing":
        raise SystemExit(f"unknown scenario {scenario!r}")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenario")
    ap.add_argument("--out", default=str(_SCRIPTS.parent / "build" / "lvtest"))
    ap.add_argument("--game-version", default=ver.VERSION,
                    help="the installed core version the manifest is judged against (default: version.py)")
    a = ap.parse_args()
    out = Path(a.out) / a.scenario
    out.mkdir(parents=True, exist_ok=True)
    m = out / "manifest.json"
    m.write_text(json.dumps(build(a.scenario, a.game_version, out), indent=2), encoding="utf-8")
    sm.sign_file(SEED, m)
    pk = sm.public_key(SEED).hex()
    print(f"wrote {m} (+ .sig)\n")
    print("Launch recipe (PowerShell, from the game folder):")
    print(f'  $env:LONGEVITY_TRUST_KEY = "{pk}"')
    print(f'  .\\terranx_PRACX.exe --lv-manifest="{m}"')
    print("Then read uimod.log ('[uimod] update:' lines) and LongevityMods\\logs\\check.log.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
