"""The Thinker Mod startup check, pure half (src/uimod/src/thinkercheck_core.h): what the loaded thinker.dll is, how it
is named to the player, and every sentence the dialog and its fallback boxes show.

The decision is two questions (user 2026-11-13: "We just needed to detect if any Thinker is present and whether or
not it is the one we expect"); the label is wording only. Every sentence here is user-approved, verbatim
(work/briefs/thinker-runtime-error-design.md, section 13): the tests pin the exact words, that they name no feature,
carry no line break inside a paragraph, and take every fact from the single sources.

One self-test exe for the module (cpp_harness), all cases in one batch: no game, no window, well under a second
after the build.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import cpp_harness  # noqa: E402
import version as ver  # noqa: E402

REPO = ROOT.parent
SRC = REPO / "src" / "uimod" / "src"
CORE = (SRC / "thinkercheck_core.h").read_text(encoding="utf-8")
CASES = json.loads((ROOT / "tests" / "thinker_labels.json").read_text(encoding="utf-8"))["cases"]

LV, TS = ver.VERSION, ver.THINKER_SUPPORTED_VERSION
URL = "longevitymods.com/vaccine/download"
PAGE = "https://example.invalid/thinker/releases/tag/vX"

#: Words that would name a feature or a module: none may appear in any player-facing text.
FEATURE_WORDS = ["cloak", "submarine", "zone of control", "air drop", "airdrop", "pillage", "base screen",
                 "base-screen", "Design Workshop", "scaling", "HUD", "text is drawn", "switched off", "Punishment",
                 "Preferences window", "AI filter"]

UNTESTED = "This combination has not been tested, and the game may not work correctly."
UPDATE_NOW = ("Choose 'Update now' to open the Longevity Vaccine installer and download the latest compatible versions of "
              "Longevity Vaccine and Thinker.")
NOT_NOW = "Choose 'Not now' to start the game and be asked again next time."
DONT_ASK = ("Choose 'Don't ask me again' to start the game and stop this question until you next update Longevity Vaccine (undo in "
            "Preferences).")
STAY_INACTIVE = "If you start the game anyway, parts of Longevity Vaccine stay inactive."
NOT_STARTED = "The Longevity Vaccine installer could not be started."
CLOSING = "The game will now start as it is, and parts of Longevity Vaccine will stay inactive."
NOT_SAVED = "Longevity Vaccine could not save your choice, so it will ask again next time."
CANNOT_START = ("Longevity Vaccine could not apply a memory patch it needs, so the game cannot start safely. Details are "
                "in uimod.log.")


def advice(ts: str, url: str, page: str) -> list[str]:
    return [f"We recommend downloading and running the Longevity Vaccine installer from {url}, or installing Thinker Mod "
            f"{ts} yourself from Thinker Mod's download page:", page]


def hexz(label: str) -> str:
    """The label as the DLL reads it: its bytes and the terminator."""
    return (label.encode("ascii") + b"\0").hex()


@pytest.fixture(scope="module")
def run():
    if not cpp_harness.have_toolchain():
        pytest.skip("MSVC toolchain not present")
    exe = cpp_harness.build(ROOT / "tests" / "thinkercheck_selftest.cpp", "thinkercheck_selftest_")

    def go(lines: list[str]) -> list[str]:
        p = subprocess.run([str(exe)], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=60)
        assert p.returncode == 0, p.stderr
        out = p.stdout.splitlines()
        assert len(out) == len(lines), (len(out), len(lines), p.stdout[-400:])
        return out
    return go


def paragraphs(escaped: str) -> list[str]:
    text = escaped.replace("\\n", "\n")
    paras = text.split("\n\n")
    for p in paras:
        assert "\n" not in p, f"a line break inside a paragraph: {p!r}"
        assert p == p.strip() and p, f"an empty or padded paragraph: {p!r}"
    return paras


# ---------------------------------------------------------------- the label grammar (shared fixture)

def test_every_fixture_label_is_read_and_named_as_the_fixture_says(run):
    out = run([f"label\t{hexz(c['label'])}" for c in CASES])
    for c, got in zip(CASES, out):
        assert got == f"{c['kind']}|{c['version']}|{c['run']}", c["label"]
    out = run([f"run\t{hexz(c['label'])}\t{c['vs']}" for c in CASES])
    for c, got in zip(CASES, out):
        assert got == f"{c['run_vs']}|{1 if c['same'] else 0}", c["label"]


def test_a_label_without_a_terminator_inside_the_readable_span_is_unrecognised(run):
    """The DLL stops reading at the end of thinker.dll's image: a string that runs off it is not a label."""
    raw = b"Thinker Mod v5.5".hex()
    assert run([f"label\t{raw}", f"label\t{raw}00", "label\t-"]) == [
        "unrecognised||an unrecognised build of Thinker Mod",
        "version|5.5|Thinker Mod 5.5",
        "unrecognised||an unrecognised build of Thinker Mod",
    ]


def test_the_possessive_form_follows_the_same_naming(run):
    """{YOURS}, for the in-game update offer: the same build, in a slot that owns it."""
    out = run([f"yours\t{hexz('Thinker Mod v5.4')}\t5.5", f"yours\t{hexz('Thinker Mod v5.5')}\t5.5",
               f"yours\t{hexz('Thinker Mod develop build')}\t5.5", f"yours\t{hexz('nonsense')}\t5.5",
               f"yours\t{hexz('Thinker Mod v5.5')}\t-"])
    assert out == ["your Thinker Mod 5.4", "your different build of Thinker Mod 5.5", "your development build of Thinker Mod",
                   "your unrecognised build of Thinker Mod", "your Thinker Mod 5.5"]


def test_the_fixture_covers_every_kind_and_the_real_labels():
    kinds = {c["kind"] for c in CASES}
    assert kinds == {"version", "develop", "unrecognised"}
    labels = {c["label"] for c in CASES}
    assert f"Thinker Mod v{TS}" in labels and "Thinker Mod develop build" in labels


# ---------------------------------------------------------------- the decision: present, and the pin or not

def test_state_is_none_pin_or_offpin_from_the_header_alone(run):
    s, z = ver.THINKER_SUPPORTED_STAMP, ver.THINKER_SUPPORTED_IMAGE_SIZE
    rows = [
        (0, 0, 0, 0, "none"),
        (0, 1, s, z, "none"),                # not in the process: the header is irrelevant
        (1, 1, s, z, "pin"),
        (1, 1, s + 1, z, "offpin"),
        (1, 1, s, z + 0x1000, "offpin"),     # the same stamp at another size is another build
        (1, 0, s, z, "offpin"),              # an unreadable header fails closed
        (1, 0, 0, 0, "offpin"),
    ]
    out = run([f"state\t{f}\t{r}\t{a}\t{b}\t{s}\t{z}" for f, r, a, b, _ in rows])
    assert out == [want for *_, want in rows]


# ---------------------------------------------------------------- the dialog's body

@pytest.mark.parametrize("label, opening", [
    ("Thinker Mod v5.6", "Longevity Vaccine {lv} was built for Thinker Mod {ts}. This game is running Thinker Mod 5.6."),
    ("Thinker Mod develop build",
     "Longevity Vaccine {lv} was built for Thinker Mod {ts}. This game is running a development build of Thinker Mod."),
    ("garbage", "Longevity Vaccine {lv} was built for Thinker Mod {ts}. This game is running an unrecognised build of Thinker Mod."),
    ("SAME", "Longevity Vaccine {lv} was tested with one specific build of Thinker Mod {ts}. This game is running a "
             "different build of Thinker Mod {ts}."),
])
def test_dialog_body_is_the_approved_five_paragraphs(run, label, opening):
    """User 2026-11-14: one paragraph per button, in button order, "stay inactive" last, and the opening and "not
    tested" in one paragraph."""
    if label == "SAME":
        label = f"Thinker Mod v{TS}"
    body = run([f"body\t{LV}\t{TS}\t{hexz(label)}"])[0]
    assert paragraphs(body) == [opening.format(lv=LV, ts=TS) + " " + UNTESTED, UPDATE_NOW, NOT_NOW, DONT_ASK, STAY_INACTIVE]


def test_fallback_boxes_are_the_approved_words_with_the_address_on_its_own_paragraph(run):
    f, g, g_same = run([f"boxf\t{TS}\t{URL}\t{PAGE}",
                        f"boxg\t{LV}\t{TS}\t{hexz('Thinker Mod v5.4')}\t{URL}\t{PAGE}",
                        f"boxg\t{LV}\t{TS}\t{hexz('Thinker Mod v' + TS)}\t{URL}\t{PAGE}"])
    assert paragraphs(f) == [NOT_STARTED, *advice(TS, URL, PAGE), CLOSING]
    assert paragraphs(g) == [f"Longevity Vaccine {LV} was built for Thinker Mod {TS}. This game is running Thinker Mod 5.4.",
                             UNTESTED, *advice(TS, URL, PAGE), CLOSING]
    assert paragraphs(g_same)[0] == (f"Longevity Vaccine {LV} was tested with one specific build of Thinker Mod {TS}. "
                                     f"This game is running a different build of Thinker Mod {TS}.")
    for box in (f, g):
        assert paragraphs(box)[-2] == PAGE, "the address is a paragraph of its own, so Ctrl+C gives a clean line"


def test_buttons_and_the_two_small_boxes(run):
    assert run(["const\ttitle", "const\tupdate", "const\tnotnow", "const\tdontask", "const\tnotsaved",
                "const\tcannotstart", "const\tids"]) == [
        "Longevity Vaccine", "Update now", "Not now", "Don't ask me again", NOT_SAVED, CANNOT_START, "100 101 102"]


def test_no_text_names_a_feature_or_a_path(run):
    texts = run([f"body\t{LV}\t{TS}\t{hexz('Thinker Mod v5.6')}", f"boxf\t{TS}\t{URL}\t{PAGE}",
                 f"boxg\t{LV}\t{TS}\t{hexz('x')}\t{URL}\t{PAGE}", "const\tnotsaved", "const\tcannotstart"])
    for t in texts:
        low = t.lower()
        for w in FEATURE_WORDS:
            assert w.lower() not in low, f"the text names a feature: {w!r}"
        assert "\\" not in t.replace("\\n", ""), "no file path in player text"
        assert "&" not in t, "an ampersand would be drawn as a shortcut underline"
    for caption in run(["const\tupdate", "const\tnotnow", "const\tdontask"]):
        assert "&" not in caption


def test_every_fact_comes_from_the_single_sources():
    """Our version, the supported Thinker version and both addresses are parameters, never literals in the header."""
    code = re.sub(r"//.*", "", CORE)
    assert ver.VERSION not in code, "the product version is written as a literal"
    assert f'"{TS}"' not in code and f" {TS}" not in code, "the supported Thinker version is written as a literal"
    assert "longevitymods.com" not in code and "github.com" not in code and "dropbox" not in code.lower(), \
        "an address is written as a literal"


# ---------------------------------------------------------------- the small rules

def test_default_button_never_goes_online_when_update_checks_are_off(run):
    assert run(["default\t1", "default\t0"]) == ["100", "101"]


def test_dont_ask_holds_exactly_for_our_own_version(run):
    assert run([f"dontask\t{LV}\t{LV}", f"dontask\t{LV}x\t{LV}", f"dontask\t\t{LV}", f"dontask\t0.9.9\t{LV}"]) == \
        ["1", "0", "0", "0"]


def test_an_installer_copy_older_than_the_mod_or_unreadable_is_refused(run):
    """Update now must not close the game for an installer copy that does not know --fix-thinker (audit J4)."""
    rows = [("1.0.0", "1.1.0", 1), ("1.1.0", "1.1.0", 0), ("1.2.0", "1.1.0", 0), ("1.1", "1.1.0", 0),
            ("1.10.0", "1.9.0", 0), ("1.9.0", "1.10.0", 1), ("", "1.1.0", 1), ("garbage", "1.1.0", 1),
            ("1.1.0 x", "1.1.0", 1), ("v1.1.0", "1.1.0", 1)]
    # (what the VERSION file reader hands over -- a BOM, CR LF, a second line -- is run in test_thinker_live.py)
    assert run([f"older\t{a}\t{b}" for a, b, _ in rows]) == [str(w) for *_, w in rows]


def test_the_thinker_page_is_the_pins_release_page_or_the_one_dev_build_page(run):
    prefix = "https://github.com/induktio/thinker/releases/tag/"
    assert run([f"page\t{prefix}\tv5.5\t-", f"page\t{prefix}\tv5.5\thttps://www.dropbox.com/scl/fo/a/b/x.zip?dl=0"]) == [
        prefix + "v5.5", "https://www.dropbox.com/scl/fo/a/b/x.zip?dl=0"]
    # the real constants: the tag in version.h, the prefix in update_core.h
    core = (SRC / "update_core.h").read_text(encoding="utf-8")
    assert f'kThinkerReleasePagePrefix[] = "{prefix}"' in core
    assert ver.THINKER_SUPPORTED_TAG == "v" + TS and ver.THINKER_DEV_PAGE == ""


def test_update_now_scrubs_the_installer_state_variables_and_nothing_else(run):
    """The game may have been started by an installer run and carry its state; the console must not inherit it."""
    block = ("=C:=C:\\Games;PATH=C:\\Windows;LONGEVITY_NO_WAIT=1;longevity_worker=1;LONGEVITY_PAYLOAD_ROOT=C:\\x;"
             "LONGEVITY_GUARD_MARKER=m;LONGEVITY_INSTALL_LOCK=l;LONGEVITY_PLAYER_NO_PROMPT=1;LONGEVITY_THINKER_CONSENT=5.6.0;"
             "LONGEVITY_TRUST_KEY=k;"
             "LONGEVITY_NO_WAITING=keep;TEMP=C:\\t")
    kept, empty, only = run([f"env\t{block}", "env\t-", "env\tLONGEVITY_NO_WAIT=1"])
    assert kept == "=C:=C:\\Games;PATH=C:\\Windows;LONGEVITY_TRUST_KEY=k;LONGEVITY_NO_WAITING=keep;TEMP=C:\\t;|1"
    assert empty == ";|1" and only == ";|1", "an empty block is still double-terminated"
    # the list IS the installer's own: a variable it learns to scrub and this one does not would reach the console
    import installer_exit
    names = re.findall(r'L"(LONGEVITY_[A-Z_]+)"', CORE)
    assert sorted(names) == sorted(installer_exit._RUN_SCOPED_ENV), "kScrubbedEnv and installer_exit._RUN_SCOPED_ENV differ"
    assert "LONGEVITY_THINKER_CONSENT" in names, "a pre-granted consent must never ride along: the click is not consent"


def test_the_test_switch_forces_each_wording(run):
    out = run([f"testlabel\t{v}\t5.5" for v in ("older", "newer", "same", "dev", "unknown", "", "0", "1", "yes")])
    assert out == ["version|5.4", "version|5.6", "version|5.5", "develop|", "unrecognised|", "none", "none", "none", "none"]
    assert run(["testlabel\tolder\t6.0"]) == ["version|5.9"]
