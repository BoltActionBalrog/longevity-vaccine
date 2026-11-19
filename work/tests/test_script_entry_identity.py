"""A script run as __main__ must be the module its own imports get back by name.

run-install.bat starts install.py as a script; thinker_flow then does `import install`. Without
install.py registering itself as sys.modules["install"], that import loaded a SECOND copy, journey R
set its verdict, launch exe and play note on the copy, and run_guarded (reading __main__'s) printed
"INSTALLATION SUCCESSFUL / The Longevity Vaccine is installed." with no offer to start the game
after a Thinker-only update (in-game check 2026-11-14). The unit tests import install as a module,
so only a script run shows it. bootstrap.py, also a script that install.py imports by name, gets the
same registration.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"

# Run the script as __main__ (runpy, the way `python install.py` does), then ask what a later
# `import <name>` and thinker_flow's own lookup return.
_DRIVER = r"""
import runpy, sys
script, name, argv = sys.argv[1], sys.argv[2], sys.argv[3:]
sys.path.insert(0, str(__import__("pathlib").Path(script).parent))
sys.argv = [script] + argv
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit:
    pass
mod = sys.modules.get(name)
print("REGISTERED", mod is not None and mod.__name__ == "__main__" and mod.__file__ == script)
if name == "install":
    import thinker_flow
    print("THINKER_FLOW_SEES_MAIN", thinker_flow._inst() is mod)
"""


def _run(script: str, name: str, *argv: str, tmp_path: Path) -> str:
    env = {**os.environ, "LONGEVITY_NO_WAIT": "1", "SMACX_GAME_DIR": str(tmp_path)}
    r = subprocess.run([sys.executable, "-c", _DRIVER, str(SCRIPTS / script), name, *argv],
                       capture_output=True, text=True, timeout=120, cwd=str(tmp_path), env=env,
                       stdin=subprocess.DEVNULL)
    return r.stdout


def test_install_run_as_a_script_is_the_install_module(tmp_path):
    # --help: through run_guarded like every run, and touches neither the network nor a game folder
    # (--check would fetch the live manifest).
    out = _run("install.py", "install", "--help", tmp_path=tmp_path)
    assert "REGISTERED True" in out, out[-2000:]
    assert "THINKER_FLOW_SEES_MAIN True" in out, out[-2000:]


def test_bootstrap_run_as_a_script_is_the_bootstrap_module(tmp_path):
    out = _run("bootstrap.py", "bootstrap", "--help", tmp_path=tmp_path)
    assert "REGISTERED True" in out, out[-2000:]


@pytest.mark.parametrize("script,name", [("install.py", "install"), ("bootstrap.py", "bootstrap")])
def test_the_registration_sits_before_any_import_of_our_modules(script, name):
    """The alias must be in place before the first module of ours is imported, or that module's own
    `import <name>` at import time would already have made the copy."""
    src = (SCRIPTS / script).read_text(encoding="utf-8")
    alias = src.index(f'sys.modules.setdefault("{name}", sys.modules[__name__])')
    first_ours = min(src.index(f"\nimport {m}") for m in ("installer_exit",) if f"\nimport {m}" in src)
    assert alias < first_ours
