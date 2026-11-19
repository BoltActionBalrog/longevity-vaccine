"""The in-game update offer's Thinker Mod step (journey A; src/uimod/src/update_core.h, update.cpp): the pipe's
`thinker=` line, the offer's wording per direction, the "Update Longevity Vaccine only" row, the consent the updater
reads, and Esc.

Spec: work/briefs/thinker-updater-design.md sections 4 (T1 / T1-G) and 8 (pipe, Esc, consent). The wording is the
user's: an update says "update"; a downgrade is said plainly, with the approved sentence ("This is a downgrade! ...");
anything not comparable is "changed"; a development-build pin is named by its date, never "development build". Since
2026-11-15 the offer is short and ends with the recommendation; the installer's own Thinker question says the rest.

The pure half runs through the update_core self-test (one build per module); the installer's own writer and reader
(work/scripts/thinker_flow.py) are held against it, so the two sides cannot drift. No game, no network.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import cpp_harness  # noqa: E402

SRC = ROOT.parent / "src" / "uimod" / "src"
UPDATE = re.sub(r"//.*", "", (SRC / "update.cpp").read_text(encoding="utf-8"))

pytestmark = pytest.mark.skipif(not cpp_harness.have_toolchain(), reason="Visual Studio x86 toolchain not available")

MAIN_MENU, IN_GAME = 0, 1
# User 2026-11-15: "It is far too wordy, and it doesn't help, considering this text is just going to be set again in
# the installer." The Thinker-step offer is the list, the two builds, what the updater can do with the settings kept,
# and the recommendation -- nothing after it. The installer's own Thinker question says the rest.
SETTINGS = "All of your Thinker Mod settings will be preserved."
RECOMMEND_UP = "We STRONGLY recommend updating Longevity Vaccine and Thinker Mod together."
RECOMMEND_DOWN = "We STRONGLY recommend updating Longevity Vaccine and downgrading Thinker Mod together."
RECOMMEND_OTHER = "We STRONGLY recommend updating Longevity Vaccine and changing Thinker Mod together."
# The fatal case (lo=0: the folder's Thinker cannot run with the new Longevity Vaccine) says why instead (user
# 2026-11-15: "Replace the "strongly recommend" line with your suggested "cannot run" line.")
CANNOT_UP = "Thinker Mod {have} cannot run with Longevity Vaccine {lv}, so both must be updated together."
CANNOT_DOWN = "Thinker Mod {have} cannot run with Longevity Vaccine {lv}, so Thinker Mod must be downgraded with this update."
CANNOT_OTHER = "The Thinker Mod in this game folder cannot run with Longevity Vaccine {lv}, so it must be changed with this update."
# Everything the offer used to carry after "The updater can update Thinker Mod for you." (and the installer still says)
GONE = ("backed up", "LongevityMods", "carried over", "You do not need to change", "installing Thinker Mod",
        "Induktio", "github", "not affiliated", "leaves your", "tell you the two", "Updating closes the game",
        "saved game", "without saving", "saves your game", "Skips", "undo in Preferences", "needed by this update",
        "KB", "MB", "downloaded from", "multiplayer", "thinker.ini", '"')


@pytest.fixture(scope="module")
def exe():
    return cpp_harness.build(ROOT / "tests" / "update_core_selftest.cpp", "update_core_selftest_")


def run(exe, *args) -> str:
    r = subprocess.run([str(exe), *map(str, args)], capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    return r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")


def answer(tmp_path, text: str) -> Path:
    p = tmp_path / "in.txt"
    p.write_bytes(text.encode("latin-1"))
    return p


def parse(exe, tmp_path, text: str, exit_code: int = 10) -> list[str]:
    return run(exe, "parse", exit_code, answer(tmp_path, text)).rstrip("\n").split("\n")


def body(exe, tmp_path, ctx: int, text: str, run_words: str = "-") -> list[str]:
    out = run(exe, "thinker-body", ctx, 10, answer(tmp_path, text), run_words).rstrip("\n")
    return out.split("\n")


BASE = "latest=1.2.0\nbase=1.1.0>1.2.0\n"


# ---------------------------------------------------------------- the pipe line

@pytest.mark.parametrize("line, shown", [
    ("thinker=5.5.0|5.6.0|760000|1", "thinker=5.5.0|5.6.0|760000|1 dir=0 dev=0"),      # a lower version: update
    ("thinker=5.7.0|5.6.0|760000|1", "thinker=5.7.0|5.6.0|760000|1 dir=1 dev=0"),      # a higher one: downgrade
    ("thinker=?|5.6.0|760000|0", "thinker=?|5.6.0|760000|0 dir=2 dev=0"),              # not comparable: replace
    ("thinker=?|dev-20251109|579137|1", "thinker=?|dev-20251109|579137|1 dir=2 dev=1"),  # a development-build pin
    ("thinker=5.5.0|5.6.0||1", "thinker=5.5.0|5.6.0||1 dir=0 dev=0"),                  # size unknown
    ("thinker=5.5.1|5.5.0|1|0", "thinker=5.5.1|5.5.0|1|0 dir=1 dev=0"),
])
def test_a_thinker_line_is_read_with_its_direction(exe, tmp_path, line, shown):
    out = parse(exe, tmp_path, BASE + line + "\n")
    assert out[0] == "status=ok code=10 badline=0"
    assert out[1:] == ["latest=1.2.0", "base=1.1.0>1.2.0", shown]


def test_it_sits_between_base_and_the_packs(exe, tmp_path):
    out = parse(exe, tmp_path, BASE + "thinker=5.5.0|5.6.0|760000|1\nstale=movies-hd|HD Cinematics|0.1.0>0.2.0|5\n"
                                      "new=music-hd|HD Music|0.1.0|7\n")
    assert out[0] == "status=ok code=10 badline=0" and out[3] == "thinker=5.5.0|5.6.0|760000|1 dir=0 dev=0"
    assert any(line.startswith("stale=movies-hd|") for line in out), out


@pytest.mark.parametrize("text, status, bad", [
    ("latest=1.2.0\nthinker=5.5.0|5.6.0|1|1\n", "bad-order", 2),                                  # no base=: refused
    ("latest=1.2.0\nthinker=5.5.0|5.6.0|1|1\nbase=1.1.0>1.2.0\n", "bad-order", 2),                # before base=
    (BASE + "stale=movies-hd|HD Cinematics|0.1.0>0.2.0|5\nthinker=5.5.0|5.6.0|1|1\n", "bad-order", 4),   # after a pack
    (BASE + "thinker=5.5.0|5.6.0|1|1\nthinker=5.5.0|5.6.0|1|1\n", "duplicate-key", 4),
    (BASE + "thinker=5.6.0|5.6.0|1|1\n", "bad-field", 3),            # have == offered must be sent as "?"
    (BASE + "thinker=5.5.0|dev-20251109|1|1\n", "bad-field", 3),     # beside a development-build pin have is "?"
    (BASE + "thinker=5.5|5.6.0|1|1\n", "bad-field", 3),              # versions are 3-part on the pipe
    (BASE + "thinker=5.5.0|5.6|1|1\n", "bad-field", 3),
    (BASE + "thinker=|5.6.0|1|1\n", "bad-field", 3),
    (BASE + "thinker=??|5.6.0|1|1\n", "bad-field", 3),
    (BASE + "thinker=5.5.0|dev-2025119|1|1\n", "bad-field", 3),      # a short date
    (BASE + "thinker=?|dev-20251309|1|1\n", "bad-field", 3),         # month 13
    (BASE + "thinker=?|dev-20251100|1|1\n", "bad-field", 3),         # day 0
    (BASE + "thinker=?|DEV-20251109|1|1\n", "bad-field", 3),
    (BASE + "thinker=5.5.0|5.6.0|01|1\n", "bad-field", 3),           # a size with a leading zero
    (BASE + "thinker=5.5.0|5.6.0|x|1\n", "bad-field", 3),
    (BASE + "thinker=5.5.0|5.6.0|1|2\n", "bad-field", 3),            # lo is 0 or 1
    (BASE + "thinker=5.5.0|5.6.0|1|\n", "bad-field", 3),
    (BASE + "thinker=5.5.0|5.6.0|1\n", "bad-field", 3),              # three fields
    (BASE + "thinker=5.5.0|5.6.0|1|1|x\n", "bad-field", 3),          # five
])
def test_any_error_in_the_line_refuses_the_whole_answer(exe, tmp_path, text, status, bad):
    """A half-understood Thinker step must never be shown: the DLL then offers nothing this launch."""
    out = parse(exe, tmp_path, text)
    assert out == [f"status={status} code=12 badline={bad}"]


def test_an_answer_without_the_line_is_exactly_as_before(exe, tmp_path):
    out = parse(exe, tmp_path, BASE)
    assert out == ["status=ok code=10 badline=0", "latest=1.2.0", "base=1.1.0>1.2.0"]


def test_the_check_asks_for_this_grammar_with_a_versioned_token(exe):
    line = run(exe, "buildcmd-thinker", r"C:\g\py.exe", r"C:\g\install.py", r"C:\Games\SMAC").strip()
    assert line == r'"C:\g\py.exe" "C:\g\install.py" --check --accept thinker1 --game-dir "C:\Games\SMAC"'
    plain = run(exe, "buildcmd", r"C:\g\py.exe", r"C:\g\install.py", r"C:\Games\SMAC").strip()
    assert plain == r'"C:\g\py.exe" "C:\g\install.py" --check --game-dir "C:\Games\SMAC"', "without the token: today's line"


def test_the_token_is_sent_only_to_an_installer_copy_that_knows_it():
    """A new DLL beside an older installer copy: that copy would ignore the token, so it is not sent to it."""
    assert "const bool acceptThinker = ResidentKnowsThinker(j.gameDir);" in UPDATE
    assert "j.cmd, sizeof j.cmd / sizeof *j.cmd, acceptThinker)" in UPDATE
    knows = UPDATE[UPDATE.index("bool ResidentKnowsThinker(const wchar_t* gameDir)"):]
    knows = knows[:knows.index("\n}\n")]
    assert 'L"LongevityMods\\\\updater\\\\VERSION"' in knows
    assert "return !thinkercheck::VersionOlder(buf, UIMOD_VERSION_STRING);" in knows
    assert knows.count("return false;") == 2, "no path, no file: not known"


# ---------------------------------------------------------------- the offer's text

def test_an_update_says_update(exe, tmp_path):
    """The user's own text (2026-11-15), word for word."""
    for ctx in (MAIN_MENU, IN_GAME):
        out = body(exe, tmp_path, ctx, BASE + "thinker=5.5.0|5.6.0|760000|1\n")
        assert out == [
            "Updates are available:",
            "Longevity Vaccine 1.1.0 -> 1.2.0",
            "Thinker Mod 5.5 -> 5.6",
            "",
            "This game folder has Thinker Mod 5.5. Longevity Vaccine 1.2.0 needs Thinker Mod 5.6.",
            "",
            "The updater can update Thinker Mod for you. " + SETTINGS,
            "",
            RECOMMEND_UP,
        ], ctx
        text = "\n".join(out)
        for gone in GONE:
            assert gone not in text, gone


def test_a_downgrade_is_said_plainly_with_the_approved_sentence(exe, tmp_path):
    out = body(exe, tmp_path, MAIN_MENU, BASE + "thinker=5.7.0|5.6.0|760000|1\n")
    assert out == [
        "Updates are available:",
        "Longevity Vaccine 1.1.0 -> 1.2.0",
        "Thinker Mod 5.7 -> 5.6 (a downgrade)",
        "",
        "This game folder has Thinker Mod 5.7. Longevity Vaccine 1.2.0 needs Thinker Mod 5.6.",
        "",
        "This is a downgrade! It replaces your newer Thinker Mod 5.7 with the older Thinker Mod 5.6, the version Longevity "
        "Vaccine 1.2.0 supports. The updater can do this downgrade for you. " + SETTINGS,
        "",
        RECOMMEND_DOWN,
    ]
    # every line about this step says "downgrade"; none calls it an update of Thinker Mod
    para = "\n".join(out[2:])
    assert "update thinker" not in para.lower() and "new version" not in para and "and thinker mod" not in para.lower()


@pytest.mark.parametrize("run_words", ["a development build of Thinker Mod", "an unrecognised build of Thinker Mod",
                                       "a different build of Thinker Mod 5.6"])
def test_a_build_that_cannot_be_compared_is_changed(exe, tmp_path, run_words):
    out = body(exe, tmp_path, MAIN_MENU, BASE + "thinker=?|5.6.0|760000|1\n", run_words)
    assert out[2:] == [
        "Thinker Mod: your build -> 5.6",
        "",
        f"This game folder has {run_words}. Longevity Vaccine 1.2.0 needs Thinker Mod 5.6.",
        "",
        "The updater can change Thinker Mod for you. " + SETTINGS,
        "",
        RECOMMEND_OTHER,
    ]
    assert "downgrade" not in "\n".join(out) and "update thinker" not in "\n".join(out).lower()


def test_without_a_label_the_build_reads_as_unrecognised(exe, tmp_path):
    """The game was started without Thinker in the process: the DLL has no label to name the folder's build from."""
    out = body(exe, tmp_path, MAIN_MENU, BASE + "thinker=?|5.6.0||1\n")
    assert out[2] == "Thinker Mod: your build -> 5.6"
    assert out[4] == "This game folder has an unrecognised build of Thinker Mod. Longevity Vaccine 1.2.0 needs Thinker Mod 5.6."


def test_a_development_build_pin_is_named_by_its_date_never_as_a_development_build(exe, tmp_path):
    out = body(exe, tmp_path, MAIN_MENU, BASE + "thinker=?|dev-20251109|579137|1\n", "Thinker Mod 5.5")
    text = "\n".join(out)
    assert out[2] == "Thinker Mod: your build -> rel. Nov 9 2025"
    assert out[4] == "This game folder has Thinker Mod 5.5. Longevity Vaccine 1.2.0 needs Thinker Mod rel. Nov 9 2025."
    assert out[8] == RECOMMEND_OTHER
    assert "development build" not in text and "dev-" not in text and "20251109" not in text


@pytest.mark.parametrize("pin, shown", [("dev-20260101", "rel. Jan 1 2026"), ("dev-20251231", "rel. Dec 31 2025"),
                                        ("dev-20250704", "rel. Jul 4 2025")])
def test_the_date_reads_month_day_year_without_a_leading_zero(exe, tmp_path, pin, shown):
    out = body(exe, tmp_path, MAIN_MENU, BASE + f"thinker=?|{pin}|1|0\n", "Thinker Mod 5.5")
    assert out[2] == f"Thinker Mod: your build -> {shown}"


def test_a_version_is_shown_as_thinker_writes_it(exe, tmp_path):
    out = body(exe, tmp_path, MAIN_MENU, BASE + "thinker=5.5.1|5.10.0|1|0\n")
    assert out[2] == "Thinker Mod 5.5.1 -> 5.10"


@pytest.mark.parametrize("line, run_words, last", [
    ("thinker=5.5.0|5.6.0|760000|0", "-", CANNOT_UP.format(have="5.5", lv="1.2.0")),
    ("thinker=5.7.0|5.6.0|760000|0", "-", CANNOT_DOWN.format(have="5.7", lv="1.2.0")),
    ("thinker=?|5.6.0|760000|0", "a development build of Thinker Mod", CANNOT_OTHER.format(lv="1.2.0")),
    ("thinker=?|dev-20251109|1|0", "Thinker Mod 5.5", CANNOT_OTHER.format(lv="1.2.0")),
])
def test_the_fatal_case_says_why_both_must_change_instead_of_recommending(exe, tmp_path, line, run_words, last):
    """lo=0: the folder's Thinker cannot run with the new Longevity Vaccine, so there is no Longevity-only row and the
    last line says why, in place of the recommendation. The rest of the offer is as with lo=1."""
    for ctx in (MAIN_MENU, IN_GAME):
        fatal = body(exe, tmp_path, ctx, BASE + line + "\n", run_words)
        allowed = body(exe, tmp_path, ctx, BASE + line[:-1] + "1\n", run_words)
        assert fatal[-1] == last, fatal
        assert fatal[:-1] == allowed[:-1] and allowed[-1].startswith("We STRONGLY recommend")
        assert "recommend" not in "\n".join(fatal)


def test_the_user_worded_fatal_line(exe, tmp_path):
    out = body(exe, tmp_path, MAIN_MENU, "latest=9.9.9\nbase=1.0.0>9.9.9\nthinker=5.5.0|5.6.0|6291456|0\n")
    assert out[-1] == "Thinker Mod 5.5 cannot run with Longevity Vaccine 9.9.9, so both must be updated together."


def test_the_offer_ends_with_the_recommendation_in_every_form(exe, tmp_path):
    """User 2026-11-15: nothing after the recommendation (or, in the fatal case, the "cannot run" line) -- not the
    Longevity-only paragraph, the closing paragraph, the save warning or the 'Don't ask me again' line -- at the menu
    or in a game."""
    for line, last in (("thinker=5.5.0|5.6.0|760000|1", RECOMMEND_UP),
                       ("thinker=5.5.0|5.6.0|760000|0", CANNOT_UP.format(have="5.5", lv="1.2.0")),
                       ("thinker=5.7.0|5.6.0|760000|1", RECOMMEND_DOWN),
                       ("thinker=?|5.6.0|760000|0", CANNOT_OTHER.format(lv="1.2.0")),
                       ("thinker=?|dev-20251109|1|1", RECOMMEND_OTHER)):
        for ctx in (MAIN_MENU, IN_GAME):
            out = body(exe, tmp_path, ctx, BASE + line + "\n")
            assert out[-1] == last and len(out) == 9, (line, ctx, out)
            for gone in GONE:
                assert gone not in "\n".join(out), (line, ctx, gone)


def test_no_line_of_the_offer_breaks_the_popup_rules(exe, tmp_path):
    """Paragraphs only: the engine wraps; and none of the script markup characters the writer would blank."""
    for line in ("thinker=5.5.0|5.6.0|760000|1", "thinker=5.7.0|5.6.0|760000|1", "thinker=?|dev-20251109|1|1"):
        for ctx in (MAIN_MENU, IN_GAME):
            out = body(exe, tmp_path, ctx, BASE + line + "\n")
            assert out != ["<refused>"], "the body must fit the 4096-byte buffer"
            for para in out:
                assert not re.search(r"[$\{\}\[\]^]", para), para
                assert para == para.strip()
            assert sum(len(p) + 1 for p in out) < 1000, "short (user 2026-11-15)"


def test_an_offer_without_a_thinker_step_keeps_todays_words(exe, tmp_path):
    out = run(exe, "body", "update", MAIN_MENU, 10, answer(tmp_path, BASE)).rstrip("\n").split("\n")
    assert out == ["An update is available:", "Longevity Vaccine 1.1.0 -> 1.2.0", "",
                   "Updating closes the game and opens the updater in its own window. Your saved games are not affected.", "",
                   "'Don't ask me again' Skips this update (undo in Preferences)."]
    game = run(exe, "body", "update", IN_GAME, 10, answer(tmp_path, BASE)).rstrip("\n").split("\n")
    assert game[3].endswith(" If you update without saving, progress since your last save is lost.")


def test_the_release_page_is_the_installers_repository():
    """The offer no longer repeats the installer's Thinker question (user 2026-11-15), so only the repository both
    sides link to is shared: the startup check's fallback boxes link its release page."""
    import thinker_source as tsrc
    core = (SRC / "update_core.h").read_text(encoding="utf-8")
    assert f'kThinkerReleasePagePrefix[] = "{tsrc.THINKER_REPO_URL}/releases/tag/"' in core
    assert "kThinkerAuthor" not in core and "kThinkerRepoUrl" not in core, "the project line is the installer's alone"


# ---------------------------------------------------------------- the replies

def rows(exe, ctx, kind, *extra) -> list[str]:
    out = run(exe, "replies-lo", ctx, kind, *extra).rstrip("\n").split("\n")
    assert out[-1] == "esc=4", "Esc is Not now"
    assert out[0].startswith("4 "), "reply 0 is Not now"
    return [r.split(" ", 1)[1] for r in out[:-1]]


def test_the_update_rows_say_both_and_recommend_it(exe):
    """User 2026-11-15: "Quit and update both (strongly recommended)", "Update Longevity Vaccine only (not
    recommended)". In a game the save pair carries the same words."""
    assert rows(exe, MAIN_MENU, 0) == ["Not now", "Quit and update both (strongly recommended)",
                                       "Update Longevity Vaccine only (not recommended)", "Don't ask me again"]
    assert rows(exe, IN_GAME, 0) == ["Not now", "Save, then update both (strongly recommended)",
                                     "Update both without saving", "Update Longevity Vaccine only (not recommended)",
                                     "Don't ask me again"]


@pytest.mark.parametrize("ctx, dir_, expected", [
    (MAIN_MENU, 1, ["Not now", "Quit, update and downgrade (strongly recommended)"]),
    (IN_GAME, 1, ["Not now", "Save, update and downgrade (strongly recommended)", "Update and downgrade without saving"]),
    (MAIN_MENU, 2, ["Not now", "Quit, update and change (strongly recommended)"]),
    (IN_GAME, 2, ["Not now", "Save, update and change (strongly recommended)", "Update and change without saving"]),
])
def test_a_downgrade_or_a_change_is_never_called_updating_both(exe, ctx, dir_, expected):
    out = rows(exe, ctx, 0, dir_, 1)
    assert out == expected + ["Update Longevity Vaccine only (not recommended)", "Don't ask me again"]
    assert not any("update both" in r.lower() for r in out)


@pytest.mark.parametrize("ctx, dir_, expected", [
    (MAIN_MENU, 0, ["Not now", "Quit and update both", "Don't ask me again"]),
    (IN_GAME, 0, ["Not now", "Save, then update both", "Update both without saving", "Don't ask me again"]),
    (MAIN_MENU, 1, ["Not now", "Quit, update and downgrade", "Don't ask me again"]),
    (IN_GAME, 1, ["Not now", "Save, update and downgrade", "Update and downgrade without saving", "Don't ask me again"]),
    (MAIN_MENU, 2, ["Not now", "Quit, update and change", "Don't ask me again"]),
    (IN_GAME, 2, ["Not now", "Save, update and change", "Update and change without saving", "Don't ask me again"]),
])
def test_the_fatal_case_has_one_update_row_and_recommends_nothing(exe, ctx, dir_, expected):
    """lo=0 (the folder's Thinker cannot run with the new Longevity Vaccine): no Longevity-only row, and with no
    alternative the update row is not "(strongly recommended)" (user 2026-11-15: "Drop the "strongly recommended"
    from the fatal case", superseding "Keep it")."""
    assert rows(exe, ctx, 0, dir_, 0) == expected


def test_no_reply_row_reaches_the_label_line_limit(exe):
    """A popup label line over 96 characters smashes the engine's stack; a reply row is one line of the label file."""
    for ctx in (MAIN_MENU, IN_GAME):
        for d in (0, 1, 2):
            for r in rows(exe, ctx, 0, d, 1):
                assert len(r) < 60, r


def test_a_pack_popup_and_an_offer_without_a_thinker_step_keep_their_rows(exe):
    assert "only" not in run(exe, "replies-lo", MAIN_MENU, 1), "a pack popup never grows the row"
    plain = run(exe, "replies", MAIN_MENU, 0)
    assert "Quit and update\n" in plain and "both" not in plain and "recommended" not in plain
    assert "Save, then update\n" in run(exe, "replies", IN_GAME, 0)


def test_the_rows_follow_the_offers_direction():
    present = UPDATE[UPDATE.index("void Present(lvupd::Context ctx)"):]
    assert ("lvupd::ReplySetFor(ctx, lvupd::kPromptUpdate, &r, thinkerStep ? lvupd::ThinkerDirection(u) : lvupd::kThinkerNone,\n"
            "                           thinkerStep && u.thinkerLongevityOnly);") in present
    only = present[present.index("case lvupd::kActLongevityOnly:"):]
    only = only[:only.index("break;")]
    assert "longevityOnly = true; quitPending = true; wantSave = ctx == lvupd::kCtxInGame;" in only, "in a game it saves first"


# ---------------------------------------------------------------- the consent

def test_the_consent_is_what_the_installer_reads(exe, tmp_path):
    import thinker_flow as F
    a = answer(tmp_path, BASE + "thinker=5.5.0|5.6.0|760000|1\n")
    full = run(exe, "thinker-consent", 10, a, 0, 1763136000, 4242).strip()
    keep = run(exe, "thinker-consent", 10, a, 1, 1763136000, 4242).strip()
    assert full == "5.6.0|1763136000|4242|game" and keep == "keep:1.2.0|1763136000|4242|game"
    assert full == F.format_consent("pin", "5.6.0", "game", pid=4242, now=1763136000)
    assert keep == F.format_consent("keep", "1.2.0", "game", pid=4242, now=1763136000)
    c = F.parse_consent(full)
    assert (c.kind, c.target, c.at, c.pid, c.source) == ("pin", "5.6.0", 1763136000, 4242, "game")
    c = F.parse_consent(keep)
    assert (c.kind, c.target, c.at, c.pid, c.source) == ("keep", "1.2.0", 1763136000, 4242, "game")
    dev = run(exe, "thinker-consent", 10, answer(tmp_path, BASE + "thinker=?|dev-20251109|1|1\n"), 0, 5, 6).strip()
    assert dev == "dev-20251109|5|6|game" and F.parse_consent(dev).target == "dev-20251109"
    assert F.CONSENT_KEY == "ThinkerUpdate"
    assert 'kThinkerConsentKey[] = L"ThinkerUpdate"' in (SRC / "update_core.h").read_text(encoding="utf-8")


def test_no_thinker_step_no_consent(exe, tmp_path):
    assert run(exe, "thinker-consent", 10, answer(tmp_path, BASE), 0, 1, 2).strip() == "<refused>"
    assert run(exe, "thinker-consent", 10, answer(tmp_path, BASE), 1, 1, 2).strip() == "<refused>"


def test_the_installers_own_line_is_one_this_parser_accepts(exe, tmp_path):
    """Every shape thinker_flow.check_line can print: 3-part or '?' have, a release or a development-build pin id,
    its size, lo 0 or 1."""
    import thinker_flow as F
    src = (ROOT / "scripts" / "thinker_flow.py").read_text(encoding="utf-8")
    assert 'return f"thinker={have}|{pid}|{pin.zip_size}|{lo}"' in src
    for have in ("5.5.0", "5.7.0", "?"):
        for pid in ("5.6.0", "dev-20251109"):
            if pid.startswith("dev-") and have != "?":
                continue
            for lo in (0, 1):
                line = f"thinker={have}|{pid}|760000|{lo}"
                assert F.PIN_ID_RE.fullmatch(pid), pid
                out = parse(exe, tmp_path, BASE + line + "\n")
                assert out[0] == "status=ok code=10 badline=0" and out[3].startswith(line + " "), (line, out)


def test_the_consent_is_written_flushed_and_read_back_just_before_the_spawn():
    present = UPDATE[UPDATE.index("void Present(lvupd::Context ctx)"):]
    present = present[:present.index("\n}\n")]
    i_save = present.index("SaveGameDialog()")
    i_write = present.index("WriteThinkerConsent(u, longevityOnly)")
    i_spawn = present.index("SpawnUpdater(mods, nMods)")
    assert i_save < i_write < i_spawn, "after the save (a cancelled save leaves nothing behind), before the spawn"
    assert "const bool consent = thinkerStep && updateAccepted && WriteThinkerConsent(u, longevityOnly);" in present
    failed = present[i_spawn:]
    assert failed.index('if (consent) DeleteThinkerConsent("the updater could not be started");') < failed.index("return;")
    write = UPDATE[UPDATE.index("bool WriteThinkerConsent(const lvupd::UpdateInfo& u, bool keep)"):]
    write = write[:write.index("\n}\n")]
    order = [write.index(s) for s in ('WritePrivateProfileStringW(L"Longevity", lvupd::kThinkerConsentKey, wide, ini)',
                                      "WritePrivateProfileStringW(nullptr, nullptr, nullptr, ini)",
                                      'GetPrivateProfileStringW(L"Longevity", lvupd::kThinkerConsentKey')]
    assert order == sorted(order), "write, flush, read back"
    assert "GetCurrentProcessId()" in write and "time(nullptr)" in write


def test_a_stale_consent_is_removed_at_every_start():
    install = UPDATE[UPDATE.index("void InstallUpdateCheck()"):]
    i_del = install.index("DeleteThinkerConsent(")
    assert i_del < install.index("if (!g_enabled) {"), "also when update checks are off"
    delete = UPDATE[UPDATE.index("void DeleteThinkerConsent(const char* why)"):]
    delete = delete[:delete.index("\n}\n")]
    assert "if (!cur[0]) return;" in delete, "an absent key is not written: the ini is not touched on a normal start"


# ---------------------------------------------------------------- Esc

def test_esc_means_not_now_on_any_row():
    """The engine returns the HIGHLIGHTED reply on Esc: backing out with the highlight on "Quit and update" would
    have accepted the update."""
    popup = UPDATE[UPDATE.index("int Popup(const char* body, const lvupd::ReplySet& r)"):]
    popup = popup[:popup.index("\n}\n")]
    i_up, i_call = popup.index("InterlockedExchange(&g_popupUp, 1);"), popup.index("At(kVA_XPops18)")
    i_down, i_esc = popup.index("InterlockedExchange(&g_popupUp, 0);"), popup.index("if (InterlockedExchange(&g_popupEsc, 0)) {")
    assert popup.index("InterlockedExchange(&g_popupEsc, 0);") < i_up < i_call < i_down < i_esc
    assert "reply = -1;" in popup[i_esc:]
    hook = UPDATE[UPDATE.index("void UpdateOnMessage(MSG* m)"):]
    assert ("if (g_popupUp && m->message == WM_KEYDOWN && m->wParam == VK_ESCAPE) InterlockedExchange(&g_popupEsc, 1);"
            in hook[:hook.index("kMsgPresent")]), "recorded before anything else looks at the message"


# ---------------------------------------------------------------- the name

def test_the_product_is_longevity_vaccine_wherever_the_offer_names_it(exe):
    core = (SRC / "update_core.h").read_text(encoding="utf-8")
    assert 'kCaption[]    = "Longevity Vaccine"' in core and 'kCoreLabel[]  = "Longevity Vaccine"' in core
    for reason in range(0, 6):
        assert run(exe, "manual", reason).startswith("Longevity Vaccine can no longer update itself.")
    assert "you chose for Longevity Vaccine and its optional packs" in run(exe, "text", "subscribe")
    assert '"Longevity Preferences"' in (SRC / "prefs.cpp").read_text(encoding="utf-8")
    for name in ("update_core.h", "update.cpp", "prefs.cpp"):
        code = re.sub(r"//.*", "", (SRC / name).read_text(encoding="utf-8"))
        left = [m.group(0) for m in re.finditer(r'"[^"\n]*Longevity Mod[^"\n]*"', code)]
        assert all("generated by uimod.dll" in s for s in left), f"{name}: {left}"
        # the tab is "Longevity Preferences" (user 2026-11-17); neither earlier name survives in a string
        old = re.findall(r'"[^"\n]*Longevity (?:Vaccine|Mod)\s*"?\s*"?Preferences[^"\n]*"', code)
        assert not old, f"{name}: {old}"
