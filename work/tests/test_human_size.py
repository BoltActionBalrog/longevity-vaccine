"""fetch.human_size prints a size the way the game does (user ruling 2026-11-17, "Match the game"): it is a port of the
DLL's FormatBytes (src/uimod/src/update_core.h) -- binary units with GB / MB / KB labels, the unit picked by the
ROUNDED value, "N bytes" below 1 KB -- so the installer's "1.3 GB" is the prompt's "1.3 GB". "?" for a size that is not
a number.

EXPECTED was produced by the C++ itself: update_core_selftest.exe's `bytes` mode, which calls FormatBytes. The
compiled check below re-asks it whenever the Visual Studio x86 toolchain is present; without it the table stands."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cpp_harness            # noqa: E402
import fetch                  # noqa: E402

MB, GB = 1 << 20, 1 << 30
EXPECTED = {
    0: "0 bytes",
    1023: "1023 bytes",
    1024: "1 KB",
    MB - 1: "1 MB",                       # rounds up: the unit by the rounded value, never "1024 KB"
    MB: "1 MB",
    int(1023.5 * MB): "1.0 GB",           # 1023.5 MB rounds to 1024 MB, so GB
    GB - 1: "1.0 GB",
    GB: "1.0 GB",
    1_388_170_092: "1.3 GB",              # the HD Cinematics pack (decimal said 1.4 GB)
    30_150_491: "29 MB",
    4_963_963_187: "4.6 GB",              # the Z2k pack (decimal would say 5.0 GB)
    1 << 40: "1024.0 GB",
}


@pytest.mark.parametrize("n,text", sorted(EXPECTED.items()), ids=lambda v: str(v))
def test_human_size_is_the_games_formatbytes(n, text):
    assert fetch.human_size(n) == text
    assert fetch.human_size(str(n)) == text                     # a manifest's size may arrive as a string


@pytest.mark.parametrize("bad", [None, "", "12 MB", "x", object()])
def test_a_size_that_is_not_a_number_is_a_question_mark(bad):
    assert fetch.human_size(bad) == "?"


@pytest.mark.skipif(not cpp_harness.have_toolchain(), reason="Visual Studio x86 toolchain not available")
def test_the_table_is_what_the_compiled_formatbytes_prints():
    exe = cpp_harness.build(ROOT / "tests" / "update_core_selftest.cpp", "update_core_selftest_")
    for n, text in EXPECTED.items():
        r = subprocess.run([str(exe), "bytes", str(n)], capture_output=True, timeout=60)
        assert r.returncode == 0
        assert r.stdout.decode("ascii").strip() == text, n
