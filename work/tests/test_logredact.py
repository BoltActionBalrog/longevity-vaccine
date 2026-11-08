"""uimod.log redaction (src/uimod/src/logredact.h).

Players attach uimod.log to public bug reports, so a path under their profile folder must not name their Windows
account: UimodLog replaces the profile folder with %USERPROFILE% in every line.  The C++ is driven through
logredact_selftest.cpp; a source guard pins that UimodLog applies it.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import cpp_harness  # noqa: E402

PROFILE = r"C:\Users\Ann"


@pytest.fixture(scope="module")
def exe():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    return cpp_harness.build(ROOT / "tests" / "logredact_selftest.cpp", "logredact_selftest_")


def run(exe, pairs):
    out = subprocess.run([str(exe)], input="".join(f"{p}\t{l}\n" for p, l in pairs), capture_output=True, text=True,
                         check=True).stdout.splitlines()
    assert len(out) == len(pairs), out
    return out


@pytest.mark.parametrize("line,want", [
    (r"hand-off: refused: bat=C:\Users\Ann\Games\SMAC\LongevityMods\x.bat game=C:\Users\Ann\Games\SMAC",
     r"hand-off: refused: bat=%USERPROFILE%\Games\SMAC\LongevityMods\x.bat game=%USERPROFILE%\Games\SMAC"),
    (r"playing: c:\users\ann\GOG\movies\intro.wve", r"playing: %USERPROFILE%\GOG\movies\intro.wve"),   # case folded
    ("playing: C:/Users/Ann/GOG/x.wve", "playing: %USERPROFILE%/GOG/x.wve"),                          # '/' too
    (r'cmd "C:\Users\Ann" end', r'cmd "%USERPROFILE%" end'),                                        # quote ends it
    (r"C:\Users\Ann end", r"%USERPROFILE% end"),                                                     # space ends it
    (r"C:\Users\Ann", r"%USERPROFILE%"),                                                             # whole line
    (r"C:\Users\Anna\Games", r"C:\Users\Anna\Games"),                     # another account sharing the prefix
    (r"C:\Users\Ann.old\x", r"C:\Users\Ann.old\x"),
    (r"D:\GOG Games\SMAC\terranx.exe", r"D:\GOG Games\SMAC\terranx.exe"),                           # nothing to hide
    ("", ""),
])
def test_profile_folder_is_redacted(exe, line, want):
    assert run(exe, [(PROFILE, line)]) == [want]


def test_trailing_separator_and_unusable_profiles(exe):
    assert run(exe, [(PROFILE + "\\", r"C:\Users\Ann\x"), ("", r"C:\Users\Ann\x"), ("C:\\", r"C:\x"),
                     ("C:", r"C:\x")]) == [r"%USERPROFILE%\x", r"C:\Users\Ann\x", r"C:\x", r"C:\x"]


def _uimodlog_code():
    src = (ROOT.parent / "src" / "uimod" / "src" / "init.cpp").read_text(encoding="utf-8")
    body = src[src.index("void UimodLog(const char* msg)"):]
    body = body[body.index("{"):body.index("\n}\n")]
    return "\n".join(ln.split("//", 1)[0] for ln in body.splitlines())          # code only, comments dropped


def test_uimodlog_redacts_before_any_use():
    """The first use of msg is the RedactProfile call, the second replaces msg with the redacted text, and both come
    before anything that writes (the debugger mirror, the file)."""
    code = _uimodlog_code()
    uses = [m.start() for m in re.finditer(r"\bmsg\b", code)]
    redact = code.index("RedactProfile(")
    assign = re.search(r"\bmsg\s*=\s*redacted\.c_str\(\)", code)
    assert assign, "UimodLog must log the redacted text"
    call_end = code.index(");", redact)
    in_call = [u for u in uses if redact < u < call_end]
    assert in_call and uses[:len(in_call)] == in_call, "the first uses of msg must be RedactProfile's argument"
    assert uses[len(in_call)] == assign.start(), "the next use of msg must replace it with the redacted text"
    for sink in ("OutputDebugStringA(", "fopen(", "fputs(", "fwrite("):
        assert assign.start() < code.index(sink), f"{sink} runs before msg is redacted"


def test_uimodlog_drops_a_line_it_cannot_redact():
    code = _uimodlog_code()
    t = code.index("try")
    assert t < code.index("RedactProfile(") < code.index("catch (...)"), "the redaction must sit in a try"
    handler = code[code.index("catch (...)"):]
    assert re.match(r"catch \(\.\.\.\)\s*\{\s*return;\s*\}", handler), "on failure UimodLog returns without writing"
