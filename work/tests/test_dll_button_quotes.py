"""Button and option names in the DLL's player-facing text are in single quotes (user 2026-11-14: the startup dialog's
"Choose 'Update now' ...", then "Yes, match it" for the in-game offer and the Reset Skipped Updates confirmation).

The DLL's counterpart of the installer's own scan (which reads only work/scripts/*.py): every narrow string literal in
src/uimod/src that carries an escaped double quote must belong to a statement that is not player-facing -- a log line
(it names a log call or carries the "[uimod]" tag), the LAN-join HTTP / SOAP text, or a wide (L"...") command line.
Static text scan, no build.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "uimod" / "src"
LOG_MARKERS = ("[uimod]", "UimodLog(", "UimodDbg(", "Dbg(", "Log(")
PROTOCOL_FILES = ("lanjoin.cpp", "lanjoin_core.h")                # HTTP headers and SOAP XML, never shown to a player
ESCAPED_QUOTE = re.compile(r'(?<![\\L])"((?:[^"\\\n]|\\.)*)"')   # a narrow literal (not L"...") on one line


def _statements(text: str):
    """The source without // comments, cut at ';' and '{' / '}' -- coarse, but enough to keep a multi-line log call
    (format string on its own line) in one piece."""
    code = re.sub(r"//[^\n]*", "", text)
    start = 0
    for m in re.finditer(r"[;{}]", code):
        yield code[start:m.end()]
        start = m.end()


def _offenders() -> list[str]:
    found = []
    for path in sorted(list(SRC.glob("*.cpp")) + list(SRC.glob("*.h"))):
        if path.name in PROTOCOL_FILES:
            continue
        for st in _statements(path.read_text(encoding="utf-8", errors="replace")):
            for lit in ESCAPED_QUOTE.finditer(st):
                if re.search(r'(?<!\\)\\"', lit.group(1)) and not any(m in st for m in LOG_MARKERS):
                    found.append(f"{path.name}: {lit.group(0)[:100]}")
    return found


def test_no_player_facing_text_names_a_button_in_double_quotes():
    assert _offenders() == []


def test_the_scan_sees_what_it_should():
    """The scan must catch the old form and pass the new one, or it proves nothing."""
    import tempfile
    global SRC
    real = SRC
    with tempfile.TemporaryDirectory() as d:
        SRC = Path(d)
        (SRC / "a.h").write_text('constexpr char kX[] = "This undoes every \\"Don\'t ask me again\\" you chose.";\n',
                                 encoding="utf-8")
        (SRC / "b.cpp").write_text('void f() {\n    UimodLog("[uimod] x: \\"%s\\" read\\n");\n'
                                   '    put(L" /D /S /C \\"", 11);\n    const char* p = "a\\\\";\n}\n', encoding="utf-8")
        try:
            assert [o.split(":")[0] for o in _offenders()] == ["a.h"]
        finally:
            SRC = real


def test_the_reset_skipped_updates_confirmation_uses_single_quotes():
    core = (SRC / "update_core.h").read_text(encoding="utf-8")
    assert "\"This undoes every 'Don't ask me again' and 'Don't show this again' you chose for Longevity Vaccine \"" in core
