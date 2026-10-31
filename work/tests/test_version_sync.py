"""Version identity: the Python and C++ sources of truth must agree, and comparison must be
numeric rather than lexical.

Why this test exists: before 2026-09-21 the product had no version at all -- the only version
string anywhere was a hardcoded `v0.1.0` literal in a log line that had never been bumped across
dozens of builds. The update path now compares versions to decide whether to re-patch a player's
exe, so a drift between work\\scripts\\version.py and src\\uimod\\src\\version.h would mean the
DLL reports one version while the installer believes another.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import version as V  # noqa: E402  (path set above)

_REPO = Path(__file__).resolve().parent.parent.parent
_VERSION_H = _REPO / "src" / "uimod" / "src" / "version.h"
_UIMOD_RC = _REPO / "src" / "uimod" / "uimod.rc"


def _defines(text: str) -> dict:
    """Pull `#define NAME value` pairs out of a C header."""
    out = {}
    for m in re.finditer(r'^\s*#define\s+(\w+)\s+(.+?)\s*$', text, re.M):
        out[m.group(1)] = m.group(2).strip()
    return out


# ---------------------------------------------------------------- the sync guarantee

def test_version_h_exists():
    assert _VERSION_H.exists(), f"missing {_VERSION_H} -- the C++ side of the version identity"


def test_python_and_cpp_version_strings_agree():
    d = _defines(_VERSION_H.read_text(encoding="utf-8"))
    cpp = d["UIMOD_VERSION_STRING"].strip('"')
    assert cpp == V.VERSION, (
        f"version drift: version.py says {V.VERSION!r}, version.h says {cpp!r}. "
        "Bump both in the same commit."
    )


def test_supported_thinker_build_agrees_between_python_and_cpp():
    """The Thinker pin (stamp, image size, the version the warning names) has one Python and one C++ home;
    the Thinker-side modules and the installer read theirs from those, never a private literal."""
    d = _defines(_VERSION_H.read_text(encoding="utf-8"))
    assert d["UIMOD_THINKER_SUPPORTED_VERSION"].strip('"') == V.THINKER_SUPPORTED_VERSION
    assert int(d["UIMOD_THINKER_SUPPORTED_STAMP"], 0) == V.THINKER_SUPPORTED_STAMP
    assert int(d["UIMOD_THINKER_SUPPORTED_IMAGE_SIZE"], 0) == V.THINKER_SUPPORTED_IMAGE_SIZE
    src = _REPO / "src" / "uimod" / "src"
    for name in ("thinkeraivis.cpp", "thinkertext.cpp", "thinkerversion.cpp"):
        text = (src / name).read_text(encoding="utf-8")
        assert "UIMOD_THINKER_SUPPORTED_STAMP" in text, f"{name} must take the pin from version.h"
        code = re.sub(r"//.*", "", text)      # a comment may quote the measured build; code may not
        assert f"{V.THINKER_SUPPORTED_STAMP:08x}" not in code.lower(), \
            f"{name} carries a private copy of the Thinker stamp"


def test_cpp_numeric_components_match_the_string():
    """FILEVERSION in the .rc is built from the numeric defines, so they must track the string."""
    d = _defines(_VERSION_H.read_text(encoding="utf-8"))
    numeric = (
        int(d["UIMOD_VERSION_MAJOR"]),
        int(d["UIMOD_VERSION_MINOR"]),
        int(d["UIMOD_VERSION_PATCH"]),
    )
    assert numeric == V.parse(V.VERSION)


def test_rc_takes_its_numbers_from_the_header():
    """Guard against someone hardcoding a literal FILEVERSION back into the .rc."""
    rc = _UIMOD_RC.read_text(encoding="utf-8")
    assert "src/version.h" in rc, "uimod.rc must include src/version.h, not hardcode a version"
    assert "UIMOD_VERSION_MAJOR" in rc and "UIMOD_VERSION_STRING" in rc
    # No bare dotted-quad literal on the FILEVERSION / PRODUCTVERSION lines.
    for line in rc.splitlines():
        if re.match(r'\s*(FILEVERSION|PRODUCTVERSION)\b', line):
            assert not re.search(r'\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*\d+', line), (
                f"hardcoded version in uimod.rc: {line.strip()!r}"
            )


def test_every_rc_version_value_uses_the_macro():
    """Checking that the macro appears *somewhere* is too weak: there are two VALUE lines
    (FileVersion and ProductVersion) and hardcoding either one would keep such a test green."""
    rc = _UIMOD_RC.read_text(encoding="utf-8")
    seen = 0
    for line in rc.splitlines():
        m = re.match(r'\s*VALUE\s+"(FileVersion|ProductVersion)"\s*,\s*(.+?)\s*$', line)
        if m:
            seen += 1
            assert "UIMOD_VERSION_STRING" in m.group(2), (
                f'VALUE "{m.group(1)}" must use UIMOD_VERSION_STRING, got {m.group(2)!r}'
            )
    assert seen == 2, f"expected FileVersion and ProductVersion VALUE lines, found {seen}"


def test_vcxproj_actually_compiles_the_resource():
    """The .rc can be perfectly correct and still not be in the build.

    If the <ResourceCompile Include="uimod.rc" /> item is dropped -- by a merge, an IDE 'remove
    unused item', or a hand-edit -- the build still succeeds, the DLL silently loses its
    VERSIONINFO, and every other test here stays green. That is exactly the drift this phase
    exists to prevent, so it needs its own assertion.
    """
    proj = (_REPO / "src" / "uimod" / "uimod.vcxproj").read_text(encoding="utf-8")
    assert re.search(r'<ResourceCompile\s+Include="uimod\.rc"\s*/?>', proj), (
        "uimod.vcxproj no longer compiles uimod.rc -- the DLL would build without a version "
        "resource and nothing else would notice"
    )
    assert re.search(r'<ClInclude\s+Include="src\\version\.h"\s*/?>', proj)


def test_init_cpp_logs_the_shared_constant():
    """init.cpp must not carry its own version literal (it did until 2026-09-21)."""
    init = (_REPO / "src" / "uimod" / "src" / "init.cpp").read_text(encoding="utf-8")
    assert "UIMOD_VERSION_STRING" in init

    # Look for a version literal that is presented AS this product's version, i.e. the
    # `v<maj>.<min>.<patch>` shape in a string. Deliberately narrow: an earlier pass matched any
    # dotted triple anywhere in a string, which false-positived on dates ("built 2026.09.21"),
    # another product's version ("PRACX 1.0.0.0 detected"), IP addresses, and any line with a
    # trailing // comment -- all legitimate future edits. A false positive that blocks real work
    # is worse than this narrower net, because it teaches people to delete the test.
    pat = re.compile(r'"[^"]*\bv\d+\.\d+\.\d+')
    stripped = _strip_cpp_comments(init)
    for ln, line in enumerate(stripped.splitlines(), 1):
        if "UIMOD_VERSION_STRING" in line:
            # A literal can still hide beside the macro on the same line, so re-check the parts
            # of the line that are not the macro reference.
            assert not pat.search(line.replace("UIMOD_VERSION_STRING", "")), (
                f"init.cpp:{ln} hides a version literal next to the macro: {line.strip()!r}")
            continue
        assert not pat.search(line), (
            f"init.cpp:{ln} hardcodes a version literal: {line.strip()!r}")


def _strip_cpp_comments(src: str) -> str:
    """Blank out // and /* */ comments so a comment mentioning an old version is not a failure."""
    out, i, n = [], 0, len(src)
    while i < n:
        if src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            seg = src[i:(n if j < 0 else j + 2)]
            out.append("\n" * seg.count("\n"))   # keep line numbers aligned
            i = n if j < 0 else j + 2
        elif src[i] == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 2 if src[j] == "\\" else 1
            out.append(src[i:min(j + 1, n)])
            i = j + 1
        else:
            out.append(src[i])
            i += 1
    return "".join(out)


# ---------------------------------------------------------------- parse / compare

@pytest.mark.parametrize("s,expected", [
    ("0.0.0", (0, 0, 0)),
    ("1.0.0", (1, 0, 0)),
    ("1.2.3", (1, 2, 3)),
    ("10.20.30", (10, 20, 30)),
    ("1.0.10", (1, 0, 10)),
    (" 1.2.3 ", (1, 2, 3)),
])
def test_parse_accepts_well_formed(s, expected):
    assert V.parse(s) == expected


@pytest.mark.parametrize("s", [
    "", "1", "1.2", "1.2.3.4", "1.2.x", "v1.2.3", "1.-2.3", "1..3",
    "1.2.3-rc1", "1.2.3+build", "01.2.3a", "a.b.c",
    # LEADING ZEROS: must be rejected, not silently equal to the canonical spelling. Consumers
    # store the raw string (receipt, ini, signed manifest bytes) and later compare with ==, so two
    # spellings that parse equal while differing as text would cause a re-patch loop or a false
    # "tampered" verdict.
    "01.2.3", "1.02.3", "1.2.03", "001.000.000", "00.0.0",
    # NON-ASCII DECIMAL DIGITS: str.isdigit() accepts these, so an earlier version of parse()
    # turned them into real ints. Such a string would then be written into an ANSI ini via
    # WritePrivateProfileStringA, which cannot encode it.
    "١.٢.٣",      # Arabic-Indic
    "１.０.０",      # fullwidth
    "১.0.0",                # Bengali
    "₁.0.0",                # subscript one
    # NON-ASCII WHITESPACE: only ASCII space/tab/CR/LF may be stripped.
    "\xa01.2.3", "1.2.3\x0b", "1.2.3 ",
])
def test_parse_rejects_malformed(s):
    with pytest.raises(ValueError):
        V.parse(s)
    assert not V.is_valid(s)


@pytest.mark.parametrize("s", ["1.2.3\n", "1.2.3\r\n", " 1.2.3", "1.2.3\t"])
def test_ascii_whitespace_is_tolerated(s):
    """Values arrive from files with trailing CRLF; that much must still parse."""
    assert V.parse(s) == (1, 2, 3)


@pytest.mark.parametrize("bad", [None, b"1.2.3", 123, 1.0, ["1", "2", "3"], {"v": "1.2.3"}])
def test_non_string_input_raises_valueerror_and_is_never_valid(bad):
    """parse() promises ValueError for anything malformed, and is_valid() is the gate for
    untrusted input -- so it must never be the thing that throws (bytes used to raise TypeError)."""
    with pytest.raises(ValueError):
        V.parse(bad)
    assert V.is_valid(bad) is False


def test_compare_rejects_bad_input_rather_than_guessing():
    for bad in (None, b"1.0.0", "01.0.0"):
        with pytest.raises(ValueError):
            V.compare(bad, "1.0.0")
        with pytest.raises(ValueError):
            V.compare("1.0.0", bad)


def test_parsing_is_canonical():
    """Exactly one string represents a version, so text equality and compare() never disagree."""
    for a in ("0.0.0", "1.0.0", "1.0.10", "10.20.30", V.VERSION):
        for b in ("0.0.0", "1.0.0", "1.0.10", "10.20.30", V.VERSION):
            assert (a == b) == (V.compare(a, b) == 0), f"{a!r} vs {b!r}"


def test_current_version_is_valid():
    assert V.is_valid(V.VERSION)
    assert V.is_valid(V.UNKNOWN)


def test_unknown_is_older_than_every_release():
    assert V.is_newer(V.VERSION, V.UNKNOWN)
    assert V.compare(V.UNKNOWN, V.VERSION) == -1


@pytest.mark.parametrize("a,b,expected", [
    ("1.0.0", "1.0.0", 0),
    ("1.0.1", "1.0.0", 1),
    ("1.0.0", "1.0.1", -1),
    ("1.1.0", "1.0.99", 1),
    ("2.0.0", "1.99.99", 1),
    # THE case a lexical compare gets wrong:
    ("1.0.10", "1.0.9", 1),
    ("1.0.9", "1.0.10", -1),
    ("1.10.0", "1.9.0", 1),
])
def test_compare_is_numeric_not_lexical(a, b, expected):
    assert V.compare(a, b) == expected
    assert V.compare(b, a) == -expected


def test_compare_is_a_total_order():
    versions = ["0.0.0", "0.0.1", "0.1.0", "1.0.0", "1.0.9", "1.0.10", "1.1.0", "2.0.0", "10.0.0"]
    for i, a in enumerate(versions):
        for j, b in enumerate(versions):
            assert V.compare(a, b) == ((i > j) - (i < j)), f"{a} vs {b}"


def test_is_newer_is_strict():
    assert not V.is_newer("1.0.0", "1.0.0"), "an equal version is not an update"
    assert V.is_newer("1.0.1", "1.0.0")
    assert not V.is_newer("1.0.0", "1.0.1")


@pytest.mark.parametrize("raw", ["1.2.3", " 1.2.3", "1.2.3\n", "1.2.3\r\n", "\t1.0.0 "])
def test_normalise_gives_one_canonical_spelling(raw):
    """`parse` tolerates surrounding ASCII whitespace because values arrive from files with a
    trailing CRLF -- which makes the RAW text non-canonical: "1.0.0" and "1.0.0\\r\\n" compare
    equal via compare() but differ under `==`. A consumer storing the raw field and later doing
    `stored == VERSION` would see a mismatch where compare() sees equality: a re-patch loop, or a
    false "tampered" verdict. normalise() is what consumers must store."""
    out = V.normalise(raw)
    assert out == out.strip()
    assert V.normalise(out) == out, "normalise must be idempotent"
    assert V.compare(out, raw) == 0


def test_normalised_text_equality_agrees_with_compare():
    variants = ["1.0.0", " 1.0.0", "1.0.0\r\n", "1.0.0\t", "\n1.0.0 "]
    normalised = {V.normalise(v) for v in variants}
    assert normalised == {"1.0.0"}, "every spelling must collapse to one canonical string"
    for a in variants:
        for b in variants:
            assert (V.normalise(a) == V.normalise(b)) == (V.compare(a, b) == 0)


@pytest.mark.parametrize("v", ["65536.0.0", "0.65536.0", "0.0.65536", "99999.1.1",
                               "9" * 400 + ".0.0"])
def test_components_are_bounded_by_the_fileversion_word_size(v):
    """uimod.rc feeds these into 16-bit FILEVERSION words, where a larger value truncates
    silently. It also stops a garbled manifest version comparing 'newer' than every release."""
    with pytest.raises(ValueError):
        V.parse(v)
    assert not V.is_valid(v)


def test_the_boundary_value_is_accepted():
    assert V.parse("65535.65535.65535") == (65535, 65535, 65535)


def test_is_valid_is_total_even_for_hostile_input():
    """is_valid is the gate for untrusted input, so it must never be the thing that raises."""
    class Hostile(str):
        def strip(self, *a):
            raise RuntimeError("boom")

    class BadStr:
        def __str__(self):
            raise RuntimeError("boom")

    for bad in (Hostile("1.2.3"), BadStr(), object(), b"1.2.3", bytearray(b"1.2.3"), None,
                float("nan"), 1j, {"v": 1}, [1, 2, 3]):
        assert V.is_valid(bad) is False


def test_at_least_is_inclusive():
    assert V.at_least("1.0.0", "1.0.0")
    assert V.at_least("1.0.1", "1.0.0")
    assert not V.at_least("0.9.9", "1.0.0")
