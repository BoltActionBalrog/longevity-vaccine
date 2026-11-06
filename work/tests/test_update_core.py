"""uimod update_core.h (the DLL's --check parser, decline merge, command line, popup text) against
the installer's own contract -- the C++ side of the pipe pinned by test_check.py.

Builds tests/update_core_selftest.cpp with the VS x86 toolchain (skipped when VS is absent).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

import cpp_harness

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install as inst        # noqa: E402
import manifest as mf         # noqa: E402
import receipt as rc          # noqa: E402

SRC = ROOT / "tests" / "update_core_selftest.cpp"
pytestmark = pytest.mark.skipif(not cpp_harness.have_toolchain(), reason="Visual Studio x86 toolchain not available")


@pytest.fixture(scope="module")
def exe():
    return cpp_harness.build(SRC, "update_core_selftest_")


def run(exe, *args) -> str:
    r = subprocess.run([str(exe), *map(str, args)], capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    return r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")


def parse(exe, tmp_path, exit_code: int, text: str) -> list[str]:
    p = tmp_path / "in.txt"
    p.write_bytes(text.encode("latin-1"))
    return run(exe, "parse", exit_code, p).rstrip("\n").split("\n")


# ---------------------------------------------------------------- the parser: test_check.py's truth table, read back

def test_nothing_to_offer(exe, tmp_path):
    assert parse(exe, tmp_path, 0, "latest=1.0.0\n") == ["status=ok code=0 badline=0", "latest=1.0.0"]


def test_yanked_is_no_lines_exit_0(exe, tmp_path):
    assert parse(exe, tmp_path, 0, "") == ["status=ok code=0 badline=0"]


def test_base_update(exe, tmp_path):
    out = parse(exe, tmp_path, 10, "latest=1.1.0\nbase=1.0.0>1.1.0\n")
    assert out == ["status=ok code=10 badline=0", "latest=1.1.0", "base=1.0.0>1.1.0"]


def test_everything_in_the_fixed_order(exe, tmp_path):
    text = ("latest=1.1.0\nbase=0.0.0>1.1.0\nstale=movies-hd|HD cinematics|1.0.0>1.2.0|671088640\n"
            "new=portraits-hd|Longevity HD Portrait Pack|1.0.0|\n")
    out = parse(exe, tmp_path, 10, text)
    assert out == ["status=ok code=10 badline=0", "latest=1.1.0", "base=0.0.0>1.1.0",
                   "stale=movies-hd|HD cinematics|1.0.0>1.2.0|671088640",
                   "new=portraits-hd|Longevity HD Portrait Pack|1.0.0|"]


@pytest.mark.parametrize("key,reason", [("protocol", 1), ("bootstrap_defect", 2), ("base_unsupported", 3),
                                        ("too_old", 4), ("", 0), ("something_new", 5)])
def test_manual_reasons(exe, tmp_path, key, reason):
    out = parse(exe, tmp_path, 11, f"manual={key}\n")
    assert out == ["status=ok code=11 badline=0", f"manual={key} reason={reason}"]


def test_could_not_check_ignores_any_output(exe, tmp_path):
    assert parse(exe, tmp_path, 12, "") == ["status=ok code=12 badline=0"]
    assert parse(exe, tmp_path, 12, "latest=1.0.0\n") == ["status=ok code=12 badline=0"]


@pytest.mark.parametrize("exit_code,text,status,line", [
    (10, "latest=1.0.0\n", "exit-code-mismatch", 0),             # 10 promises an item
    (0, "latest=1.0.0\nbase=0.9.0>1.0.0\n", "exit-code-mismatch", 0),
    (11, "latest=1.0.0\n", "exit-code-mismatch", 0),
    (10, "manual=too_old\n", "exit-code-mismatch", 0),
    (7, "latest=1.0.0\n", "bad-exit-code", 0),
    (10, "latest=1.0.0\nbase=1.0.0>1.1.0", "no-final-lf", 0),
    (10, "latest=1.0.0\r\nbase=1.0.0>1.1.0\r\n", "bad-field", 1),   # CRLF never
    (10, "latest=1.0.0\nbogus=1\n", "unknown-key", 2),
    (10, "latest=1.0.0\nbase 1.0.0>1.1.0\n", "malformed-line", 2),
    (10, "latest=1.0.0\n\nbase=1.0.0>1.1.0\n", "malformed-line", 2),
    (10, "base=1.0.0>1.1.0\nlatest=1.1.0\n", "bad-order", 1),
    (10, "latest=1.0.0\nlatest=1.0.0\nbase=1.0.0>1.1.0\n", "duplicate-key", 2),
    (10, "latest=1.1.0\nbase=1.0.0>1.1.0\nbase=1.0.0>1.1.0\n", "duplicate-key", 3),
    (10, "latest=1.0.0\nnew=a|A|1.0.0|\nstale=b|B|1.0.0>1.1.0|\n", "bad-order", 3),
    (10, "latest=1.2\nbase=1.0.0>1.2\n", "bad-version", 1),
    (10, "latest=1.1.0\nbase=1.0.0>01.1.0\n", "bad-version", 2),
    (10, "latest=1.1.0\nbase=1.1.0>1.0.0\n", "bad-version", 2),                       # a downgrade
    (10, "latest=1.1.0\nbase=1.0.0>1.0.0\n", "bad-version", 2),                       # not an update
    (10, "latest=1.1.0\nbase=1.0.0>7.7.7\n", "bad-version", 2),                       # the core is offered AT latest
    (10, "latest=1.0.0\nstale=movies-hd|HD|1.1.0>1.0.0|\n", "bad-field", 2),          # pack downgrade
    (10, "latest=1.0.0\nstale=movies-hd|HD|1.0.0>1.1.0\n", "bad-field", 2),           # 3 fields
    (10, "latest=1.0.0\nstale=Movies|HD|1.0.0>1.1.0|\n", "bad-field", 2),             # id charset
    (10, "latest=1.0.0\nstale=movies-hd||1.0.0>1.1.0|\n", "bad-field", 2),            # empty label
    (10, "latest=1.0.0\nstale=movies-hd|H=D|1.0.0>1.1.0|\n", "bad-field", 2),         # '=' in a label
    (10, "latest=1.0.0\nnew=movies-hd|HD|1.0.0|12x\n", "bad-field", 2),
    (10, "latest=1.0.0\nnew=movies-hd|HD|1.0.0|1234567890123456789\n", "bad-field", 2),
    (10, "latest=1.0.0\nnew=movies-hd|HD|1.0.0|1125899906842624\n", "bad-field", 2),   # 2**50: too big
    (10, "latest=1.0.0\nnew=movies-hd|HD|1.0.0|007\n", "bad-field", 2),                # leading zeros
    (10, "latest=1.0.0\nnew=movies-hd|H\x80D|1.0.0|\n", "bad-field", 2),
    (10, "latest=1.0.0\nnew=movies-hd|" + "L" * 48 + "|1.0.0|\n", "bad-field", 2),     # label cap
    (10, "latest=1.0.0\nnew=" + "m" * 32 + "|L|1.0.0|\n", "bad-field", 2),             # id cap
    (10, "latest=1.0.0\nstale=movies-hd|HD|1.0.0>1.1.0|\nstale=movies-hd|HD|1.0.0>1.1.0|\n", "duplicate-key", 3),
    (10, "latest=1.0.0\nstale=movies-hd|HD|1.0.0>1.1.0|\nnew=movies-hd|HD|1.1.0|\n", "duplicate-key", 3),
    (10, "latest=1.0.0\nmanual=x\n", "bad-order", 2),
    (11, "manual=Too-Old\n", "bad-field", 1),
    (11, "manual=" + "k" * 24 + "\n", "bad-field", 1),
    (10, "latest=1.0.0 \n", "bad-version", 1),                                        # trailing space
    (10, "latest=1.0.0\nbase=1.0.0|x>1.1.0\n", "bad-version", 2),
])
def test_refused_answers_read_as_could_not_check(exe, tmp_path, exit_code, text, status, line):
    out = parse(exe, tmp_path, exit_code, text)
    assert out[0] == f"status={status} code=12 badline={line}", out
    assert len(out) == 1, "a refused answer carries no items"


def test_overflow_is_refused(exe):
    assert run(exe, "overflow", 10).split("\n")[0] == "status=overflow code=12 badline=0"


def test_accepted_edges(exe, tmp_path):
    """17-char versions (version.py's maximum), a 16-digit size under 2**50, the id/label caps."""
    text = ("latest=65535.65535.65535\nbase=0.1.0>65535.65535.65535\n"
            "stale=movies-hd|HD cinematics|10000.10000.10000>10000.10000.10001|1125899906842623\n"
            "new=portraits-hd|" + "L" * 47 + "|1.0.0|0\n")
    out = parse(exe, tmp_path, 10, text)
    assert out == ["status=ok code=10 badline=0", "latest=65535.65535.65535", "base=0.1.0>65535.65535.65535",
                   "stale=movies-hd|HD cinematics|10000.10000.10000>10000.10000.10001|1125899906842623",
                   "new=portraits-hd|Longevity HD Portrait Pack|1.0.0|0"]


def test_unknown_ids_are_skipped_not_fatal(exe, tmp_path):
    """A newer installer may know a pack this DLL does not: that ITEM is dropped, the rest stands."""
    text = "latest=1.1.0\nbase=1.0.0>1.1.0\nnew=zzz-evil|Free V-Bucks|1.0.0|\nnew=portraits-hd|X|1.0.0|\n"
    out = parse(exe, tmp_path, 10, text)
    assert out == ["status=ok code=10 badline=0", "latest=1.1.0", "base=1.0.0>1.1.0",
                   "new=portraits-hd|Longevity HD Portrait Pack|1.0.0|"]
    # only unknown items: still a valid exit-10 answer, just nothing to show
    out = parse(exe, tmp_path, 10, "latest=1.0.0\n" + "".join(f"new=p{i}|P|1.0.0|\n" for i in range(5)))
    assert out == ["status=ok code=10 badline=0", "latest=1.0.0"]


def test_the_pipe_label_is_never_shown(exe, tmp_path):
    """The DLL shows its OWN name for a known id; the pipe's label is validated and discarded."""
    out = parse(exe, tmp_path, 10, "latest=1.0.0\nstale=movies-hd|#xs 9999 ; evil|1.0.0>1.1.0|\n")
    assert out[2] == "stale=movies-hd|HD cinematics|1.0.0>1.1.0|"


def test_known_modules_match_the_installer(exe):
    inst._load_modules()
    got = dict(ln.split("=", 1) for ln in run(exe, "labels").strip().split("\n"))
    assert got == inst.MODULE_LABELS
    assert set(got) == set(inst.GAME_CONTENT_MODULES)


def test_manual_decline_item_matches_receipt(exe):
    for key in ("bootstrap_defect", "too_old", "protocol", "base_unsupported", ""):
        assert run(exe, "manualitem", key or "-").strip() == rc.manual_decline_item(key)


def test_the_real_installer_lines_parse(exe, tmp_path):
    """check_report's own output for the unit truth table round-trips through the C++ parser."""
    import installer_exit as ix
    inst._load_modules()
    doc = {"schema": 1, "protocol": 1, "product": "longevity-vaccine", "latest": "1.1.0",
           "min_upgradable_from": "0.0.0", "manual_install_required": False,
           "manual_install_reason": None, "unsupported_versions": [], "unsupported_targets": [],
           "yanked": [], "modules": {
               "movies-hd": {"version": "1.2.0", "url": "https://x/m", "sha256": "0" * 64, "size": 1300 << 20},
               "portraits-hd": {"version": "1.0.0", "url": "https://x/p", "sha256": "0" * 64, "size": 42}}}
    state = {"modules": {"base": {"version": "1.0.0"}, "movies-hd": {"version": "1.0.0"}},
             "target_id": "pracx", "source": "json"}
    code, lines = inst.check_report(doc, state, {})
    assert code == ix.CHECK_UPDATES
    out = parse(exe, tmp_path, code, "".join(ln + "\n" for ln in lines))
    assert out[0] == "status=ok code=10 badline=0"
    assert out[1:] == lines


# ---------------------------------------------------------------- sizes

@pytest.mark.parametrize("n,text", [
    (671088640, "640 MB"), (1395864371, "1.3 GB"), (1 << 30, "1.0 GB"), ((1 << 30) + (1 << 29), "1.5 GB"),
    (1300 << 20, "1.3 GB"), (1023, "1023 bytes"), (1024, "1 KB"), (12 << 10, "12 KB"), (0, "0 bytes"),
    ((1 << 20) - 1, "1 MB"), (1 << 50, "1048576.0 GB"),
])
def test_format_bytes(exe, n, text):
    assert run(exe, "bytes", n).strip() == text


# ---------------------------------------------------------------- declines: the C++ writer vs receipt.py's reader

def decline(exe, tmp_path, raw: str, *pairs) -> tuple:
    p = tmp_path / "raw.txt"
    p.write_text(raw, encoding="latin-1")
    out = run(exe, "decline", p, *pairs).split("\n")
    sets = [ln for ln in out if ln.startswith("set ")]
    ok = [ln for ln in out if ln.startswith("ok=")][0] == "ok=1"
    value = out[out.index([ln for ln in out if ln.startswith("ok=")][0]) + 1]
    return ok, value, sets


def test_decline_parse_matches_receipt(exe, tmp_path):
    raw = "base:1.1.0;garbage;movies-hd:nope;;new:x:2.0.0; portraits-hd : * ;dup:1.0.0;dup:2.0.0"
    ok, value, _ = decline(exe, tmp_path, raw)
    assert ok
    g = tmp_path / "g"
    g.mkdir()
    (g / "Alpha Centauri.ini").write_text(f"[Longevity]\nDeclinedUpdates={raw}\n", encoding="ascii")
    py = rc.declined(g)
    assert dict(kv.split(":", 1) if not kv.startswith("new:") else ("new:" + kv[4:].rsplit(":", 1)[0], kv.rsplit(":", 1)[1])
                for kv in value.split(";")) == py
    assert value == "base:1.1.0;dup:2.0.0;new:x:2.0.0;portraits-hd:*"


def test_decline_set_replaces_adds_sorts_and_refuses(exe, tmp_path):
    ok, value, sets = decline(exe, tmp_path, "movies-hd:1.2.0;base:1.0.0",
                              "base", "*", "new:portraits-hd", "*", "manual", "*",
                              "a;b", "1.0.0", "x=y", "*", "[Longevity]", "*", "", "*", "base", "**",
                              "base", "1.0", "sp ace", "*")
    assert ok
    assert sets == ["set base * -> 1", "set new:portraits-hd * -> 1", "set manual * -> 1",
                    "set a;b 1.0.0 -> 0", "set x=y * -> 0", "set [Longevity] * -> 0", "set  * -> 0",
                    "set base ** -> 0", "set base 1.0 -> 0", "set sp ace * -> 0"]
    assert value == "base:*;manual:*;movies-hd:1.2.0;new:portraits-hd:*"
    # ... and receipt.py reads exactly that back
    g = tmp_path / "g2"
    g.mkdir()
    (g / "Alpha Centauri.ini").write_text(f"[Longevity]\nDeclinedUpdates={value}\n", encoding="ascii")
    assert rc.declined(g) == {"base": "*", "manual": "*", "movies-hd": "1.2.0", "new:portraits-hd": "*"}
    # the same merge on the Python side produces the same string
    assert rc.decline(g, "portraits-hd", "3.0.0")
    ok2, value2, _ = decline(exe, tmp_path, value, "portraits-hd", "3.0.0")
    assert ok2 and value2 == rc.ini_get(g, rc.KEY_DECLINED)


def test_decline_truncated_value_drops_its_last_entry(exe, tmp_path):
    entries = ";".join(f"module-name-{i:02d}-padding:1.0.0" for i in range(30))   # 30 * 29 - 1 = 869
    raw = entries + ";cut-entry:9.9.9"
    raw = raw + "9" * (1023 - len(raw))                              # exactly 1023 = truncated read
    assert len(raw) == 1023
    ok, value, _ = decline(exe, tmp_path, raw)
    assert ok and "cut-entry" not in value and "module-name-29-padding:1.0.0" in value
    # ... and the same value one byte shorter is NOT truncated: every entry counts
    ok2, value2, _ = decline(exe, tmp_path, entries + ";cut-entry:9.9.9")
    assert ok2 and "cut-entry:9.9.9" in value2
    # more entries than the reader holds -> never rewritten (a rewrite would erase some)
    many = ";".join(f"m{i:03d}:*" for i in range(70))                 # 70 * 7 - 1 = 489 chars, 70 entries
    ok_many, value_many, _ = decline(exe, tmp_path, many)
    assert ok_many is False and value_many == ""
    # a value that will not fit the profile buffer is refused rather than written cut
    huge = ";".join(f"module-{i:02d}-with-a-longer-name-xx:1.0.0" for i in range(30))   # 1139 chars
    assert len(huge) > 1023
    ok3, value3, _ = decline(exe, tmp_path, huge)
    assert ok3 is False and value3 == ""


# ---------------------------------------------------------------- the game's command line and the child's

def cmdline(exe, tmp_path, text: str) -> str:
    p = tmp_path / "cmd.txt"
    p.write_text(text, encoding="utf-8")
    return run(exe, "cmdline", p).strip()


@pytest.mark.parametrize("text,want", [
    (r'"D:\Games\SMAC\terranx_PRACX.exe"', "<none>"),
    (r'"D:\Games\SMAC\terranx_PRACX.exe" --lv-manifest=C:\m\manifest.json', r"C:\m\manifest.json"),
    (r'terranx.exe --lv-manifest="C:\my games\m.json" -other', r"C:\my games\m.json"),
    (r'terranx.exe "--lv-manifest=C:\my games\m.json"', r"C:\my games\m.json"),
    (r'terranx.exe --lv-manifest=https://cdn.example/x/manifest.json', "https://cdn.example/x/manifest.json"),
    (r'terranx.exe --lv-manifest=a --lv-manifest=b', "b"),
    (r'terranx.exe --lv-manifest=', "<none>"),
    (r'terranx.exe --lv-manifest', "<none>"),
    (r'terranx.exe --lv-manifest-x=1', "<none>"),
    (r'terranx.exe --lv-manifest=C:\a"b', "<none>"),                # a quote inside the value
    (r'terranx.exe --LV-MANIFEST=x', "<none>"),                      # case-sensitive switch
    ('terranx.exe --lv-manifest=' + "x" * 3000, "<none>"),           # too long: refused, never cut
])
def test_extract_lv_manifest(exe, tmp_path, text, want):
    assert cmdline(exe, tmp_path, text) == want


@pytest.mark.parametrize("text,want", [
    ("terranx.exe", 0),
    ("terranx.exe --lv-delay=10", 10),
    ('terranx.exe --lv-manifest="C:\\m x\\m.json" --lv-delay=7', 7),
    ("terranx.exe --lv-delay=0", 0),
    ("terranx.exe --lv-delay=abc", 0),
    ("terranx.exe --lv-delay=-5", 0),
    ("terranx.exe --lv-delay=99999", 600),       # capped at ten minutes
    ("terranx.exe --lv-delay=", 0),
    ("terranx.exe --lv-delay=3 --lv-delay=12", 12),
])
def test_extract_lv_delay(exe, tmp_path, text, want):
    p = tmp_path / "cmd.txt"
    p.write_text(text, encoding="utf-8")
    assert run(exe, "delay", p).strip() == str(want)


@pytest.mark.parametrize("game,manifest,want", [
    (r"D:\Games\SMAC", None,
     r'"C:\g\LongevityMods\updater\tools\python\python.exe" "C:\g\LongevityMods\updater\scripts\install.py" --check --game-dir "D:\Games\SMAC"'),
    # A trailing backslash is kept and DOUBLED before the closing quote, so the receiver reads the
    # path back exactly (CRT rule; `"...\"` escaped the quote and swallowed the rest of the line).
    ("D:\\Games\\Sid Meier's\\", r"C:\my m\manifest.json",
     '"C:\\g\\LongevityMods\\updater\\tools\\python\\python.exe" "C:\\g\\LongevityMods\\updater\\scripts\\install.py"'
     ' --check --game-dir "D:\\Games\\Sid Meier\'s\\\\" --manifest "C:\\my m\\manifest.json"'),
    (r'D:\Ga"mes', None, "<refused>"),
    (r"D:\Games", r'C:\m"x', "<refused>"),
    ("", None, "<refused>"),
    (r"D:\Games", "\\\\", "<refused>"),                                 # nothing but backslashes
    ("D:\\", None,                                                      # a drive root: `"D:\\"` reads back `D:\`
     r'"C:\g\LongevityMods\updater\tools\python\python.exe" "C:\g\LongevityMods\updater\scripts\install.py" --check --game-dir "D:\\"'),
])
def test_build_check_command_line(exe, game, manifest, want):
    py = r"C:\g\LongevityMods\updater\tools\python\python.exe"
    sc = r"C:\g\LongevityMods\updater\scripts\install.py"
    args = [py, sc, game] + ([manifest] if manifest else [])
    assert run(exe, "buildcmd", *args).strip() == want


# ---------------------------------------------------------------- the popup label file

def test_label_file_body_is_wrapped_into_short_physical_lines(exe, tmp_path):
    """The engine's line reader has a fixed buffer sized for script.txt's <= 106-char lines; a
    330-char body on one physical line smashed its stack (main-menu crash 2026-09-27). The body
    must come out as lines of <= 96 chars broken at spaces, which the engine re-joins with a
    space -- so joining them back must give the sanitised body exactly."""
    body = tmp_path / "body.txt"
    # The real closing paragraph (user wording 2026-11-04): it must survive the wrap with its two
    # spaces after the label, on one physical line of its own.
    never = "\"Don't ask me again\"  Skips this update (undo in Preferences)."
    text = ("An update is available:\nLongevity Mod 0.1.0 -> 9.9.9\n\nUpdating closes the game and opens the updater "
            "in its own window.\nYour saved games are not affected. If you update without saving, progress since "
            "your last save is lost.\n\n" + never)
    body.write_text(text, encoding="ascii")
    out = run(exe, "label", body, 460, "longevity_sm.pcx", "Quit and update", "Not now", "Don't ask me again")
    lines = out.split("\n")
    assert max(len(ln) for ln in lines) <= 96, [ln for ln in lines if len(ln) > 96]
    start = lines.index("#sprite longevity_sm.pcx") + 1
    end = lines.index("", start)
    body_lines = lines[start:end]
    assert len(body_lines) >= 5, body_lines
    # the engine's reading: a line starting with ^ begins a new line (a lone ^ = blank line);
    # other lines continue the previous one, joined with a space
    rebuilt = ""
    for ln in body_lines:
        if ln.startswith("^"):
            rebuilt += "\n" + ln[1:]
        else:
            rebuilt += (" " if rebuilt and not rebuilt.endswith("\n") else "") + ln
    assert rebuilt == text, rebuilt
    assert "^" in "".join(body_lines) and all(not ln.startswith(("#", ";")) and not ln.endswith(" ") for ln in body_lines)
    assert "^" + never in body_lines, body_lines
    assert "^" in body_lines and body_lines.index("^") > 0, "an empty paragraph is a lone ^ line"
    # a single very long word cannot overflow the reader either
    body.write_text("x" * 300, encoding="ascii")
    out = run(exe, "label", body, 460, "-", "OK")
    assert max(len(ln) for ln in out.split("\n")) <= 96
    # every real body this DLL can produce stays under the cap too
    for reason in range(6):
        b = tmp_path / f"m{reason}.txt"
        b.write_text(run(exe, "manual", reason), encoding="ascii")
        assert max(len(ln) for ln in run(exe, "label", b, 460, "-", "OK", "Don't show this again").split("\n")) <= 96


def test_label_file_grammar_and_sanitiser(exe, tmp_path):
    body = tmp_path / "body.txt"
    body.write_text("Line one $NUM0 {bold} [it]^\nLine two\x01\xe9", encoding="latin-1")
    out = run(exe, "label", body, 400, "longevity_sm.pcx", "Quit and update", "Not now", "Don't ask me again")
    assert out == ("; generated by uimod.dll (Longevity Mod) -- rewritten on demand, safe to delete\n\n"
                   "#UPDATE\n#xs 400\n#caption Longevity Mod\n#sprite longevity_sm.pcx\n"
                   "Line one  NUM0  bold   it  \n^Line two  \n\n"          # '\n' -> a new line STARTING with ^
                   "Quit and update\nNot now\nDon't ask me again\n\n"
                   "# ; This line must remain at end of file\n\n")
    raw = subprocess.run([str(exe), "label", str(body), "320", "-", "OK"], capture_output=True).stdout
    assert b"\r\n" in raw and raw.count(b"\r\n") == raw.count(b"\n"), "CRLF like the game's own files"
    assert b"#sprite" not in raw, "no picture line when the file is absent"
    # a NOTICE has no reply lines: the engine draws its own OK, and exactly one blank line ends the body
    body.write_text("Just a message.", encoding="ascii")
    none = run(exe, "label", body, 320, "-")
    assert none.endswith("Just a message.\n\n# ; This line must remain at end of file\n\n"), none
    assert "\n\n\n" not in none
    # a body or reply that STARTS with '#' or ';' would become a directive / comment line
    body.write_text("#END rest\n;second", encoding="ascii")
    out = run(exe, "label", body, 320, "-", "#REPLY", ";reply", "OK")
    assert " END rest\n^;second\n" in out and "\n REPLY\n reply\nOK\n" in out
    assert not any(ln.startswith(("#", ";")) for ln in out.split("\n")[3:] if ln and not ln.startswith(("#xs", "#caption", "# ;")))


# ---------------------------------------------------------------- player-facing text: the flow accounting

def replies(exe, ctx, kind):
    out = run(exe, "replies", ctx, kind).strip().split("\n")
    rows = [ln.split(" ", 1) for ln in out if not ln.startswith(("esc=", "beyond="))]
    return [(int(a), t) for a, t in rows], out[-2], out[-1]


def test_reply_sets_per_context():
    pass  # placeholder for readability; real assertions below


def test_reply_sets(exe):
    QUIT, SAVE, TOO, NOTNOW, NEVER = 1, 2, 3, 4, 5
    # reply 0 is ALWAYS the safe "no": Esc returns the highlighted reply (0) in a plain reply-button popup
    assert replies(exe, 0, 0)[0] == [(NOTNOW, "Not now"), (QUIT, "Quit and update"), (NEVER, "Don't ask me again")]
    assert replies(exe, 1, 0)[0] == [(NOTNOW, "Not now"), (SAVE, "Save, then update"), (QUIT, "Update without saving"),
                                     (NEVER, "Don't ask me again")]
    assert replies(exe, 0, 1)[0] == [(NOTNOW, "Not now"), (QUIT, "Quit and install"), (NEVER, "Don't ask me again")]
    assert replies(exe, 1, 1)[0] == [(NOTNOW, "Not now"), (SAVE, "Save, then install"), (QUIT, "Install without saving"),
                                     (NEVER, "Don't ask me again")]
    for ctx in (0, 1):
        assert replies(exe, ctx, 2)[0] == [(NOTNOW, "Not now (update without it)"), (TOO, "Yes, include it"),
                                           (NEVER, "Don't ask me again")]
    for ctx in (0, 1):
        for kind in (0, 1, 2):
            assert replies(exe, ctx, kind)[0][0][0] == NOTNOW, "reply 0 must be the safe one"
    for ctx in (0, 1):
        for kind in (0, 1, 2):
            for _, text in replies(exe, ctx, kind)[0]:
                assert len(text) <= 27 and all(ord(c) < 128 for c in text), text
    for ctx in (0, 1):
        for kind in (0, 1, 2):
            _, esc, beyond = replies(exe, ctx, kind)
            assert esc == f"esc={NOTNOW}" and beyond == f"beyond={NOTNOW}", "Esc / -1 is Not now"


def test_update_body_names_every_item_and_the_action(exe, tmp_path):
    text = "latest=0.2.0\nbase=0.1.0>0.2.0\nstale=movies-hd|HD cinematics|0.1.0>0.2.0|671088640\n"
    p = tmp_path / "in.txt"
    p.write_bytes(text.encode())
    # user wording 2026-11-04: the label, two spaces, the meaning; "Not now" unexplained
    NO = '"Don\'t ask me again"  Skips these updates (undo in Preferences).\n'
    menu = run(exe, "body", "update", 0, 10, p)
    assert menu == ("Updates are available:\nLongevity Mod 0.1.0 -> 0.2.0\nHD cinematics 0.1.0 -> 0.2.0 (640 MB)\n\n"
                    "Updating closes the game and opens the updater in its own window. "
                    "Your saved games are not affected.\n\n" + NO)
    game = run(exe, "body", "update", 1, 10, p)
    assert ("Your saved games are not affected. If you update without saving, progress since your last save is lost.\n\n"
            + NO) in game
    # line breaks ONLY between paragraphs and list items: never inside a sentence
    for body in (menu, game):
        for ln in body.split("\n"):
            assert not ln or ln.endswith((".", ":", ")", "?")) or " -> " in ln, ln
    one = tmp_path / "one.txt"
    one.write_bytes(b"latest=0.2.0\nbase=0.1.0>0.2.0\n")
    single = run(exe, "body", "update", 0, 10, one)
    assert single.startswith("An update is available:\n")
    assert single.endswith('\n\n"Don\'t ask me again"  Skips this update (undo in Preferences).\n')
    assert "Not now" not in menu + single


def test_pack_body_variants(exe, tmp_path):
    text = "latest=0.2.0\nnew=movies-hd|HD cinematics|0.2.0|1395864371\nnew=portraits-hd|Longevity HD Portrait Pack|0.2.0|\n"
    p = tmp_path / "in.txt"
    p.write_bytes(text.encode())
    NO = '"Don\'t ask me again"  Skips this pack (undo in Preferences).\n'      # user wording 2026-11-04
    standalone = run(exe, "body", "pack", 0, 1, 0, "0.2.0", 10, p)
    assert standalone == ("HD cinematics 0.2.0 is available. It is an optional 1.3 GB download. "
                          "Installing it also brings Longevity Mod up to 0.2.0 (required).\n\n"
                          "Installing closes the game and opens the updater in its own window. "
                          "Your saved games are not affected.\n\n" + NO)
    pending = run(exe, "body", "pack", 1, 2, 1, "-", 10, p)
    assert pending == "You chose to update. Add Longevity HD Portrait Pack to that update? It is optional.\n\n" + NO
    pending_sz = run(exe, "body", "pack", 0, 2, 0, "-", 10, p)
    assert "Add HD cinematics (1.3 GB) to that update?" in pending_sz
    ingame = run(exe, "body", "pack", 1, 1, 0, "-", 10, p)
    assert " If you install without saving, progress since your last save is lost.\n" in ingame
    assert "brings Longevity Mod" not in ingame


def test_fixed_strings_and_the_one_url(exe):
    assert run(exe, "text", "url").strip() == mf.DOWNLOAD_URL
    shown = mf.DOWNLOAD_URL.split("://", 1)[1]                 # what the popups print: typable, no scheme
    for reason in range(6):
        body = run(exe, "manual", reason)
        assert body.startswith("Longevity Mod can no longer update itself. ")
        assert shown in body and "https://" not in body and "^" not in body
        assert "Your game and saved games are fine." in body and "web browser" in body
    assert shown in run(exe, "text", "noinstaller") and "nothing was installed" in run(exe, "text", "noinstaller")
    assert "within 90 seconds" in run(exe, "text", "quit")
    sub = run(exe, "text", "subscribe")
    assert "restart the game to check now" in sub and "Don't ask me again" in sub
    assert "module" not in sub.lower() and "core" not in sub.lower(), "no jargon"
    for w in ("noinstaller", "quit", "subscribe"):
        assert all(ord(c) < 128 for c in run(exe, "text", w)), "ASCII only: the engine font"
    # paragraphs only: every line of every fixed string ends a sentence (or is the address line)
    texts = [run(exe, "text", w) for w in ("noinstaller", "quit", "subscribe")] + [run(exe, "manual", r) for r in range(6)]
    for t in texts:
        for ln in t.rstrip("\n").split("\n"):
            assert not ln or ln.endswith((".", "?", ":")) or ln == shown, ln
        assert "\n\n\n" not in t


def test_version_grammar(exe):
    assert run(exe, "version", "1.0.0", "1.0.1").strip() == "1 1 -1"
    assert run(exe, "version", "10.2.3", "9.9.9").strip() == "1 1 1"
    assert run(exe, "version", "1.0.0", "1.0.0").strip() == "1 1 0"
    for bad in ("1.0", "01.0.0", "1.0.0.0", "65536.0.0", "a.b.c", "", "1..0", ".1.0"):
        assert run(exe, "version", bad, "1.0.0").split()[0] == "0", bad
    assert run(exe, "version", "65535.65535.65535", "0.0.0").strip() == "1 1 1"


# ---------------------------------------------------------------- the interpreter the check spawns, per Windows

@pytest.mark.parametrize("major,minor,exe_dir", [
    (6, 1, "python38"),     # Windows 7 SP1
    (6, 2, "python38"),     # Windows 8
    (6, 3, "python"),       # Windows 8.1: the first CPython 3.12 runs on
    (10, 0, "python"),      # Windows 10 / 11 (RtlGetVersion; GetVersionEx would say 6.2 here)
    (5, 1, "python38"),     # XP: not a target, but never the interpreter that cannot start
])
def test_runtime_exe_per_windows_version(exe, major, minor, exe_dir):
    out = run(exe, "runtime-exe", major, minor).strip()
    assert out == rf"LongevityMods\updater\tools\{exe_dir}\python.exe"


@pytest.mark.parametrize("ver, picks38", [
    ("Microsoft Windows [Version 6.1.7601]", True),      # Windows 7 SP1
    ("Microsoft Windows [version 6.1.7600]", True),      # a localised lower-case "version"
    ("Microsoft Windows [Version 6.2.9200]", True),      # Windows 8
    ("Microsoft Windows [Version 6.3.9600]", False),     # Windows 8.1: CPython 3.12 runs here
    ("Microsoft Windows [Version 10.0.19045.3803]", False),
    ("Microsoft Windows [Version 10.0.26200.6901]", False),
    ("Microsoft Windows [Version 6.0.6002]", False),     # Vista: not a target either way
])
def test_run_install_bat_picks_the_38_interpreter_only_on_61_and_62(ver, picks38):
    """Three places choose the interpreter: RuntimeExeRel above, run-install.bat (the `ver` regex) and
    bootstrap.py (the running interpreter's family). The batch rule is PROVED here: the regex is lifted from
    the file and run through findstr over `ver` samples, so a broken regex cannot hide behind a substring."""
    bat = (ROOT / "run-install.bat").read_text(encoding="ascii", errors="replace")
    assert r"tools\python38\python.exe" in bat
    m = re.search(r'ver \| findstr /R /C:"([^"]+)"', bat)
    assert m, "run-install.bat lost its `ver | findstr /R /C:...` interpreter rule"
    # findstr reads stdin: no cmd quoting of the regex to get wrong here
    p = subprocess.run(["findstr", "/R", "/C:" + m.group(1)], input=ver + "\r\n", capture_output=True, text=True, timeout=30)
    assert (p.returncode == 0) == picks38, f"{ver!r}: findstr exit {p.returncode} (regex {m.group(1)!r})"


def test_run_install_bat_kb2533623_probe_and_screen():
    """Windows 7 / 8 only (PY38 set by the `ver` rule): `import ctypes` under 3.8 is probed before the
    installer runs -- CPython 3.8's extension loader needs that 2011 update -- and a failure ends in its own
    screen: marker cleaned, --no-wait honoured, a code of its own (10; 9 is "package incomplete"). Never
    exercised on this Windows 11 box, so the block is pinned by text."""
    bat = (ROOT / "run-install.bat").read_text(encoding="ascii", errors="replace")
    probe = bat[bat.index("if not defined PY38 goto :afterkb"):bat.index("\n:afterkb")]
    # first "does the runtime start" (a quarantined DLL is NOT the KB), then the import the KB governs
    assert probe.index('"%PY%" -I -c "pass"') < probe.index('"%PY%" -I -c "import ctypes"')
    assert 'if not "%ERRORLEVEL%"=="0" goto :nostart' in probe and 'if not "%ERRORLEVEL%"=="0" goto :needkb' in probe
    assert "if errorlevel" not in probe, "a negative (NTSTATUS) exit code slips past `if errorlevel 1`"
    nostart = bat[bat.index("\n:nostart"):bat.index("\n:needkb")]
    assert 'rd /s /q "%MDIR%"' in nostart and "antivirus" in nostart and "endlocal & exit /b 11" in nostart
    assert "if not defined NOWAIT pause" in nostart
    block = bat[bat.index("\n:needkb"):bat.index("\n:incomplete")]
    assert 'rd /s /q "%MDIR%"' in block and "KB2533623" in block
    assert "if not defined NOWAIT pause" in block and "endlocal & exit /b 10" in block
    assert bat.index('set "PY38="') < bat.index("ver | findstr"), "PY38 must be cleared before the rule sets it"


# ---------------------------------------------------------------- the accept hand-off (--only-listed)

BAT = r"C:\g\LongevityMods\updater\run-install.bat"
HEAD = r'"C:\Windows\System32\cmd.exe" /D /S /C ""C:\g\LongevityMods\updater\run-install.bat" --update --game-dir "D:\Games\SMAC" --wait-pid 4242 --only-listed'


def test_handoff_always_says_only_listed_and_names_exactly_the_modules(exe):
    """The game hands the updater the list it showed; the updater installs the list (user, 2026-10-31)."""
    assert run(exe, "handoff", BAT, r"D:\Games\SMAC", 4242, "-").strip() == HEAD + '"'
    assert run(exe, "handoff", BAT, r"D:\Games\SMAC", 4242, "-", "movies-hd").strip() == HEAD + ' --modules movies-hd"'
    assert run(exe, "handoff", BAT, r"D:\Games\SMAC", 4242, "-", "movies-hd", "portraits-hd").strip() \
        == HEAD + ' --modules movies-hd,portraits-hd"'
    assert run(exe, "handoff", BAT, r"D:\Games\SMAC", 4242, r"C:\my m\manifest.json", "portraits-hd").strip() \
        == HEAD + ' --modules portraits-hd --manifest "C:\\my m\\manifest.json""'


@pytest.mark.parametrize("bat,game,manifest,ids", [
    (r'C:\g\run"x.bat', r"D:\Games", "-", []),               # a quote in a path
    (r"C:\g\run.bat", r"D:\Ga&mes", "-", []),                # a cmd metacharacter in the game path
    (r"C:\g\run.bat", r"D:\Games", r"C:\m|x.json", []),      # ... or in the manifest value
    (r"C:\g\run.bat", r"D:\Games", "-", ["movies hd"]),      # an id with a space
    (r"C:\g\run.bat", r"D:\Games", "-", ["Movies-HD"]),      # upper case is not a compiled-in id
    (r"C:\g\run.bat", r"D:\Games", "-", ["a" * 40]),         # longer than kIdCap
    (r"C:\g\run.bat", "", "-", []),                          # no game dir
    (r"C:\g\run.bat", "\\\\", "-", []),                      # nothing but backslashes (as the check line)
])
def test_handoff_refuses_anything_unclean(exe, bat, game, manifest, ids):
    assert run(exe, "handoff", bat, game, 7, manifest, *ids).strip() == "<refused>"


# ---------------------------------------------------------------- the paths survive the real parsers
#
# A game at a drive root (`D:\`) used to come out as `--game-dir "D:\"`: the CRT reads `\"` as an
# escaped quote, so the argument never closed and --wait-pid / --only-listed / --modules vanished
# into it (2026-11-01). Every shape a builder can see is read back -- by CommandLineToArgvW, and by
# the REAL receiving parser (bootstrap.py / install.py --check, under each shipped runtime, reached
# the way the game reaches it) -- and must come back exactly.

PATH_SHAPES = ["D:\\", "C:\\", r"D:\Games\SMAC", "D:\\Games\\SMAC\\", "D:\\Games\\SMAC\\\\",
               "\\\\server\\share\\", r"\\server\share\SMAC", r"D:\Sid Meier's Alpha Centauri",
               "D:\\Sid Meier's Alpha Centauri\\", r"\\?\D:\Games\SMAC"]


def _argv(line: str) -> list:
    import ctypes
    from ctypes import wintypes
    shell32, k32 = ctypes.WinDLL("shell32"), ctypes.WinDLL("kernel32")
    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    n = ctypes.c_int()
    p = shell32.CommandLineToArgvW(line, ctypes.byref(n))
    try:
        return [p[i] for i in range(n.value)]
    finally:
        k32.LocalFree(ctypes.cast(p, ctypes.c_void_p))


MANIFESTS = ["-", "C:\\my m\\man.json", "C:\\my m\\man\\"]


@pytest.mark.parametrize("manifest", MANIFESTS)
@pytest.mark.parametrize("game", PATH_SHAPES)
def test_the_check_line_reads_back_exactly_through_command_line_to_argv(exe, game, manifest):
    py, sc = r"C:\g\py\python.exe", r"C:\g\scripts\install.py"
    line = run(exe, "buildcmd", py, sc, game, *([] if manifest == "-" else [manifest])).strip()
    want = [py, sc, "--check", "--game-dir", game] + ([] if manifest == "-" else ["--manifest", manifest])
    assert _argv(line) == want, line


@pytest.mark.parametrize("manifest", MANIFESTS)
@pytest.mark.parametrize("game", PATH_SHAPES)
def test_the_handoff_reads_back_exactly_after_cmd_strips_its_quotes(exe, game, manifest):
    """cmd /S /C removes the outer quote pair and the batch file's %* passes the rest through
    verbatim, so python parses exactly `"<bat>" <args>` -- read that back."""
    line = run(exe, "handoff", BAT, game, 4242, manifest, "movies-hd", "portraits-hd").strip()
    inner = line.split(" /D /S /C ", 1)[1]
    assert inner[0] == '"' and inner[-1] == '"'
    assert _argv(inner[1:-1]) == [BAT, "--update", "--game-dir", game, "--wait-pid", "4242",
                                  "--only-listed", "--modules", "movies-hd,portraits-hd"] \
        + ([] if manifest == "-" else ["--manifest", manifest]), line


@pytest.mark.parametrize("exe_path,want", [
    (r"D:\Games\SMAC\terranx.exe", r"D:\Games\SMAC"),
    (r"D:\terranx.exe", "D:\\"),                              # a drive root keeps its backslash
    (r"\\?\C:\terranx.exe", "\\\\?\\C:\\"),                   # ... behind a \\?\ prefix too
    (r"\\.\C:\terranx.exe", "\\\\.\\C:\\"),
    (r"\\?\C:\Games\terranx.exe", r"\\?\C:\Games"),
    (r"\\server\share\terranx.exe", r"\\server\share"),
    (r"\\?\UNC\server\share\SMAC\terranx.exe", r"\\?\UNC\server\share\SMAC"),
    ("terranx.exe", "<refused>"),
])
def test_the_game_dir_from_the_exe_path(exe, exe_path, want):
    assert run(exe, "gamedir", exe_path).strip() == want


@pytest.mark.parametrize("manifest", ["-", "C:\\my m\\man.json"])
@pytest.mark.parametrize("game", [g for g in PATH_SHAPES if not g.endswith("\\")])
def test_a_path_without_a_trailing_backslash_comes_out_exactly_as_before(exe, game, manifest):
    """Byte-identical to what 0.2.0's DLL emitted (its format, rebuilt here) for every path that
    does not end in a backslash -- every ordinary game folder."""
    m = "" if manifest == "-" else f' --manifest "{manifest}"'
    assert run(exe, "buildcmd", r"C:\g\py.exe", r"C:\g\i.py", game,
               *([] if manifest == "-" else [manifest])).strip() \
        == rf'"C:\g\py.exe" "C:\g\i.py" --check --game-dir "{game}"' + m
    assert run(exe, "handoff", BAT, game, 4242, manifest, "movies-hd").strip() \
        == (r'"C:\Windows\System32\cmd.exe" /D /S /C ""' + BAT + f'" --update --game-dir "{game}" '
            f'--wait-pid 4242 --only-listed --modules movies-hd{m}"')


# ---- the FROZEN 0.2.0 receiver, reached the way the game reaches it
#
# Players' installs run the 0.2.0 resident updater until a swap succeeds, so the lines this DLL
# builds are parsed by THAT code: its run-install.bat (cmd.exe, `echo %* | findstr`, `%*`), its
# runtime (3.12, or 3.8 on Windows 7/8) and its bootstrap.py / install.py argparse. The 0.2.0
# sources come from the release commit; a spy named like the real script loads the frozen module
# and records what its argparse got, then exits before anything is checked or fetched.

#: The 0.2.0 sources: the commit the release was cut from (the maintainer's checkout), else the public tag
#: v0.2.0 (a clone of the public repository has no private history; the tag marks the same sources).
SHIPPED = "50a0e16648c6c2c14f3be85cdc59ecf104c72917"
SHIPPED_FALLBACK = "v0.2.0"

_SPY = r'''
import argparse, json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != here]
sys.path.insert(0, os.environ["LV_FROZEN_SCRIPTS"])
orig = argparse.ArgumentParser.parse_known_args
def spy(self, args=None, namespace=None):
    ns, unknown = orig(self, args, namespace)
    with open(os.environ["LV_ARGV_SPY"], "w", encoding="utf-8") as f:
        json.dump({"ns": {k: v for k, v in vars(ns).items() if isinstance(v, (str, int, bool, type(None)))},
                   "unknown": unknown, "python": sys.version_info[:2]}, f)
    os._exit(0)
argparse.ArgumentParser.parse_known_args = spy
name = os.path.splitext(os.path.basename(__file__))[0]
mod = __import__(name)
(mod.check_main if name == "install" else mod.run)()
'''

_RUNTIMES = [pytest.param(rel, id=rel) for rel in ("runtime", "runtime38")]


@pytest.fixture(scope="module")
def shipped(tmp_path_factory):
    """{"frozen": <0.2.0 work/scripts>, "updater": {runtime: <a resident updater dir>}}: the real
    0.2.0 run-install.bat, a spy bootstrap.py / install.py beside it, and tools\\python linked to
    each staged runtime (a junction, removed here -- never followed into the runtime)."""
    import _winapi
    import io
    import tarfile
    from conftest import _missing                 # skip, or fail under LONGEVITY_REQUIRE_E2E
    repo = ROOT.parent
    for rev in (SHIPPED, SHIPPED_FALLBACK):
        tar = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", rev,
                              "work/scripts", "work/run-install.bat"], capture_output=True)
        if tar.returncode == 0:
            break
    else:
        _missing(repo, f"the 0.2.0 sources (commit {SHIPPED[:7]} or tag {SHIPPED_FALLBACK} in this checkout)")
    d = tmp_path_factory.mktemp("shipped020")
    with tarfile.open(fileobj=io.BytesIO(tar.stdout)) as t:
        if hasattr(tarfile, "data_filter"):
            t.extractall(d / "frozen", filter="data")
        else:
            t.extractall(d / "frozen")
    # The bat as it SHIPPED: CRLF (cmd.exe needs it). git archive follows this clone's
    # core.autocrlf, and the blob itself is LF.
    bat_bytes = (d / "frozen" / "work" / "run-install.bat").read_bytes().replace(b"\r\n", b"\n")
    bat_bytes = bat_bytes.replace(b"\n", b"\r\n")
    links, updaters = [], {}
    try:
        for rel in ("runtime", "runtime38"):
            src = ROOT / "build" / rel
            if not (src / "python.exe").is_file():
                continue
            up = d / f"updater-{rel}"
            (up / "scripts").mkdir(parents=True)
            (up / "tools").mkdir()
            (up / "scripts" / "run-install.bat").write_bytes(bat_bytes)
            for name in ("bootstrap.py", "install.py"):
                (up / "scripts" / name).write_text(_SPY, encoding="utf-8")
            _winapi.CreateJunction(str(src), str(up / "tools" / "python"))
            links.append(up / "tools" / "python")
            updaters[rel] = up
        yield {"frozen": d / "frozen" / "work" / "scripts", "updater": updaters}
    finally:
        for link in links:
            os.rmdir(link)            # removes the junction only, never the runtime behind it


def _spied(cmdline: str, tmp_path, frozen) -> dict:
    out = tmp_path / "ns.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env.update(LV_ARGV_SPY=str(out), LV_FROZEN_SCRIPTS=str(frozen), LONGEVITY_NO_WAIT="1")
    r = subprocess.run(cmdline, capture_output=True, text=True, timeout=120, env=env,
                       stdin=subprocess.DEVNULL)
    assert out.is_file(), f"the receiver never parsed its arguments:\n{r.stdout}\n{r.stderr}"
    return json.loads(out.read_text(encoding="utf-8"))


def _updater(shipped, rel):
    if rel not in shipped["updater"]:
        from conftest import _missing             # skip, or fail under LONGEVITY_REQUIRE_E2E
        _missing(ROOT / "build" / rel / "python.exe", f"the staged {rel} (build_runtime.py / fetch_python38.py)")
    return shipped["updater"][rel]


RECEIVER_SHAPES = ["D:\\", "\\\\server\\share\\", r"D:\Games\SMAC", "D:\\Sid Meier's Alpha Centauri\\"]


@pytest.mark.parametrize("rel", _RUNTIMES)
@pytest.mark.parametrize("game", RECEIVER_SHAPES)
def test_the_shipped_bootstrap_gets_every_handoff_argument(exe, shipped, tmp_path, rel, game):
    """cmd.exe -> 0.2.0's run-install.bat (its --update routing and %*) -> the runtime -> 0.2.0's
    bootstrap.py argparse: every argument arrives, the game dir exactly as the game gave it."""
    up = _updater(shipped, rel)
    line = run(exe, "handoff", up / "scripts" / "run-install.bat", game, 4242, "C:\\my m\\man\\",
               "movies-hd", "portraits-hd").strip()
    got = _spied(line, tmp_path, shipped["frozen"])
    assert got["unknown"] == [], got
    ns = got["ns"]
    assert (ns["game_dir"], ns["wait_pid"], ns["only_listed"], ns["modules"], ns["manifest"],
            ns["update"]) == (game, 4242, True, "movies-hd,portraits-hd", "C:\\my m\\man\\", True), \
        (line, got)
    assert tuple(got["python"]) == ((3, 8) if rel == "runtime38" else (3, 12))


@pytest.mark.parametrize("rel", _RUNTIMES)
@pytest.mark.parametrize("game", RECEIVER_SHAPES)
def test_the_shipped_check_parser_gets_the_game_dir(exe, shipped, tmp_path, rel, game):
    up = _updater(shipped, rel)
    line = run(exe, "buildcmd", up / "tools" / "python" / "python.exe", up / "scripts" / "install.py",
               game, "C:\\my m\\man\\").strip()
    got = _spied(line, tmp_path, shipped["frozen"])
    assert got["unknown"] == [], got
    ns = got["ns"]
    assert (ns["game_dir"], ns["manifest"], ns["check"]) == (game, "C:\\my m\\man\\", True), (line, got)
    assert tuple(got["python"]) == ((3, 8) if rel == "runtime38" else (3, 12))


def test_handoff_modules_are_the_listed_stale_packs_plus_the_accepted_new_ones(exe, tmp_path):
    p = tmp_path / "in.txt"
    p.write_bytes(b"latest=0.3.0\nbase=0.2.0>0.3.0\nstale=movies-hd|HD cinematics|0.1.0>0.2.0|10\n"
                  b"stale=portraits-hd|Longevity HD Portrait Pack|0.1.0>0.2.0|20\n")
    # the update popup accepted: every stale pack it listed, in the order it listed them
    assert run(exe, "handoffmods", 10, p, 1).strip() == "movies-hd,portraits-hd"
    # a new pack accepted in its own popup rides along after them
    assert run(exe, "handoffmods", 10, p, 1, "newpack-x").strip() == "movies-hd,portraits-hd,newpack-x"
    # nothing accepted from the update popup -> only the new packs the player said yes to
    assert run(exe, "handoffmods", 10, p, 0, "newpack-x").strip() == "newpack-x"
    assert run(exe, "handoffmods", 10, p, 0).strip() == "<none>"
    # the core alone: the hand-off names no module at all (the updater brings the core by nature)
    core = tmp_path / "core.txt"
    core.write_bytes(b"latest=0.3.0\nbase=0.2.0>0.3.0\n")
    assert run(exe, "handoffmods", 10, core, 1).strip() == "<none>"
    # a stale line whose id this build does not know is NOT handed off (it was never named in a popup)
    unknown = tmp_path / "unknown.txt"
    unknown.write_bytes(b"latest=0.3.0\nbase=0.2.0>0.3.0\nstale=future-pack|Future|0.1.0>0.2.0|10\n"
                        b"stale=movies-hd|HD cinematics|0.1.0>0.2.0|10\n")
    assert run(exe, "handoffmods", 10, unknown, 1).strip() == "movies-hd"
