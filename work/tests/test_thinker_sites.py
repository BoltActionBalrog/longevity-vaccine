"""Which run-time sites the "apply after Thinker" pass may write (src/uimod/src/thinkersites_core.h), decided over the
REAL generated table (thinker_sites.h) in every state an exe can be in.

The rules (work/briefs/thinker-runtime-error-design.md sections 7 and 8, final audit 2026-11-14):
- a site is written only when it matches AND our code is at the other end of every call or jump our bytes make
  (the developer exe carries no code cave: before this, calls into nothing were written there);
- the sites of one patches.yaml group go together or not at all (the rest of the group is baked on disk);
- the Design Workshop's allocation size is a MINIMUM: raised only when smaller, whatever value was there, and never
  skipped with its group. If the instruction around it is not the one we mean the game cannot run safely
  (user 2026-11-14: "Telling users to avoid a core part of the game doesn't really make sense").

One self-test exe for the module (cpp_harness), one run over a fake image: no process memory, no game.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import cpp_harness  # noqa: E402

SRC = ROOT.parent / "src" / "uimod" / "src"
COMPAT = re.sub(r"//.*", "", (SRC / "thinkercompat.cpp").read_text(encoding="utf-8"))
CORE = re.sub(r"//.*", "", (SRC / "thinkersites_core.h").read_text(encoding="utf-8"))

CAVIAR = "Caviar.E_imm_618a92"
KEYED = "SetupWin_draw_item.decoration_keyed_scaled"
SOFT = "SetupWin_draw_item.decoration_soft_update_scaled"
CREDITS = "load_credits_a.subwin"
BLIT = "SetupWin_draw_item.decoration_blit_redirect"      # the one kRestore site; same group as KEYED and SOFT


@pytest.fixture(scope="module")
def out():
    if not cpp_harness.have_toolchain():
        pytest.skip("MSVC toolchain not present")
    exe = cpp_harness.build(ROOT / "tests" / "thinkersites_selftest.cpp", "thinkersites_selftest_")
    p = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return p.stdout.splitlines()


def plan(out, name: str) -> dict:
    line = next(line for line in out if line.startswith(f"PLAN {name} "))
    assert "NO-REASON" not in line and "STRAY-REASON" not in line, line
    return dict(item.split("=") for item in line.split(" ")[2:])


@pytest.mark.parametrize("check", ["table_has_the_min_imm32_site", "every_code_site_names_a_destination",
                                   "every_site_names_its_group"])
def test_the_generated_table_carries_what_the_rules_need(out, check):
    assert f"PASS {check} " in [line.rstrip() + " " for line in out], [line for line in out if check in line]


def test_a_plain_pracx_exe_has_everything_on_disk_and_nothing_is_written(out):
    assert plan(out, "pracx_exe") == {CAVIAR: "min-enough", KEYED: "already", SOFT: "already", CREDITS: "already",
                                      BLIT: "already"}


def test_a_thinker_folder_started_without_thinker_still_gets_its_excluded_sites(out):
    assert plan(out, "thinker_folder_without_thinker") == {CAVIAR: "min-write", KEYED: "write", SOFT: "write",
                                                           CREDITS: "write", BLIT: "already"}


def test_under_thinker_every_site_is_written_over_thinkers_calls(out):
    assert plan(out, "under_thinker") == {CAVIAR: "min-write", KEYED: "write", SOFT: "write", CREDITS: "write",
                                          BLIT: "write"}


def test_an_exe_without_our_code_gets_no_call_into_nothing(out):
    """The developer exe: the sites read clean, but nothing of ours is at the other end of their calls."""
    assert plan(out, "exe_without_our_code") == {CAVIAR: "min-write", KEYED: "skip", SOFT: "skip", CREDITS: "skip",
                                                 BLIT: "skip"}


def test_when_thinkers_image_is_unknown_its_calls_do_not_count_as_thinkers(out):
    assert plan(out, "thinker_header_unreadable") == {CAVIAR: "min-write", KEYED: "skip", SOFT: "skip", CREDITS: "skip",
                                                      BLIT: "skip"}


def test_one_site_that_does_not_match_takes_its_whole_group_out_and_only_that_group(out):
    assert plan(out, "foreign_byte_in_one_menu_site") == {CAVIAR: "min-write", KEYED: "skip", SOFT: "skip",
                                                          CREDITS: "write", BLIT: "skip"}
    assert plan(out, "credits_destination_differs") == {CAVIAR: "min-write", KEYED: "write", SOFT: "write",
                                                        CREDITS: "skip", BLIT: "write"}
    assert plan(out, "call_into_neither") == {CAVIAR: "min-write", KEYED: "write", SOFT: "write", CREDITS: "skip",
                                              BLIT: "write"}


def test_the_group_rule_does_not_depend_on_the_order_of_the_table(out):
    """A later site failing takes an earlier one out; a missing destination on one site of a multi-site group takes
    the others out; and a site that already holds our bytes is never flipped by a failing sibling."""
    assert plan(out, "foreign_byte_in_a_later_menu_site") == {CAVIAR: "min-write", KEYED: "skip", SOFT: "skip",
                                                              CREDITS: "write", BLIT: "skip"}
    assert plan(out, "menu_destination_differs") == {CAVIAR: "min-write", KEYED: "skip", SOFT: "skip", CREDITS: "write",
                                                     BLIT: "skip"}
    assert plan(out, "failing_sibling_beside_already_ours") == {CAVIAR: "min-write", KEYED: "skip", SOFT: "skip",
                                                                CREDITS: "write", BLIT: "already"}


def test_the_two_window_forms_the_table_does_not_hold_today(out):
    """Thinker's write_call over an FF15 site (90 E8 rel32) and a Scient byte inside an ordinary site: both are in the
    matcher for the day a site needs them, and neither would otherwise ever run."""
    line = next(line for line in out if line.startswith("SYNTH "))
    assert line == "SYNTH clean=1 ff15=1 ff15_without_thinker=0 scient=1 foreign_scient=0"


def test_a_refused_write_takes_the_whole_group_out_before_anything_is_written():
    """All or nothing must hold when Windows will not let us write, not only when a site does not match."""
    install = COMPAT[COMPAT.index("void InstallThinkerCompat()"):]
    probe = install.index("CanWrite(At(kSites[i].va), kSites[i].len)")
    first_write = install.index("WriteCode(p, s.ours, s.len)")
    assert install.index("thinkersites::Plan(kSites, kNumSites, view, plan, why);") < probe < first_write
    block = install[probe:first_write]
    assert "plan[j] = thinkersites::Action::SkipGroup;" in block and "kSites[j].mode == kMinImm32" in block, \
        "the minimum-value site is never skipped with a group"
    can = COMPAT[COMPAT.index("bool CanWrite(BYTE* p, size_t n)"):]
    can = can[:can.index("\n}\n")]
    assert can.count("VirtualProtect(") == 2, "opened and put back: the probe changes nothing"


def test_the_chains_read_their_cave_bytes_through_the_guarded_reader():
    chain = COMPAT[COMPAT.index("int InstallChain(const Chain& c)"):]
    chain = chain[:chain.index("\n}\n")]
    assert "ReadLive(nullptr, c.thunk_va, c.thunk_len)" in chain and "ReadLive(nullptr, c.core_va, c.core_len)" in chain
    assert chain.index("if (!thunk || !core) {") < chain.index("memcmp(thunk, c.thunk_bytes, c.thunk_len)")
    assert "At(c.thunk_va)" not in chain and "At(c.core_va)" not in chain, "an exe without our cave must not be read blind"
    read = COMPAT[COMPAT.index("const uint8_t* ReadLive(void*, uint32_t va, uint32_t len)"):]
    read = read[:read.index("\n}\n")]
    assert "for (uintptr_t a = reinterpret_cast<uintptr_t>(p); a < end;)" in read, "a span may cross a region boundary"


def test_the_allocation_size_is_a_minimum_whatever_value_was_there(out):
    rows = {line.split()[1]: line.split()[2:] for line in out if line.startswith("MIN ")}
    assert rows["00020000"] == ["min-write", "00020000"], "the clean exe"
    assert rows["00100000"] == ["min-write", "00100000"], "Scient's / Thinker's"
    assert rows["001FFFFF"] == ["min-write", "001FFFFF"]
    assert rows["00200000"] == ["min-enough", "00200000"], "ours"
    assert rows["00400000"] == ["min-enough", "00400000"], "a larger foreign size is safe: left alone"
    assert rows["01000000"] == ["min-enough", "01000000"], "16 MB: the high byte differs and that is fine"
    assert rows["FFFFFFFF"] == ["min-enough", "FFFFFFFF"], "compared unsigned"
    assert rows["00000000"] == ["min-write", "00000000"]
    assert rows["unmapped"] == ["fatal"]


def test_a_wrong_instruction_around_it_stops_the_game_rather_than_guessing(out):
    guards = [line.split() for line in out if line.startswith("GUARD ")]
    assert [g[1] for g in guards] == ["-1", "4", "9", "10", "11"], "push imm32 / call rel32 / add esp,4"
    assert all(g[2] == "fatal" and g[3] == "reason" for g in guards)


def test_the_pass_performs_the_plan_and_stops_the_game_on_the_one_fatal_failure():
    assert "thinkersites::Plan(kSites, kNumSites, view, plan, why);" in COMPAT
    assert "view.read = &ReadLive;" in COMPAT
    read = COMPAT[COMPAT.index("const uint8_t* ReadLive(void*, uint32_t va, uint32_t len)"):]
    read = read[:read.index("\n}\n")]
    assert "VirtualQuery(" in read and "MEM_COMMIT" in read and "return nullptr;" in read, "an unmapped destination must not fault"
    install = COMPAT[COMPAT.index("void InstallThinkerCompat()"):]
    # a min-value write that does not land, or a wrong instruction: the game is stopped; nothing else stops it
    assert "cannotStart |= s.mode == kMinImm32;" in install
    fatal = install[install.index("case thinkersites::Action::Fatal:"):]
    assert "cannotStart = true;" in fatal[:fatal.index("break;")]
    assert install.rstrip().endswith("if (cannotStart) ThinkerCannotStart();\n}")
    assert install.count("cannotStart = true;") == 1
    assert "Avoid the Design Workshop" not in COMPAT and "MessageBoxA" not in COMPAT
    # the decisions live in the pure header only
    for moved in ("bool SiteMatches(", "int ApplySite(", "const Window* WindowAt("):
        assert moved not in COMPAT, f"{moved} is still in thinkercompat.cpp"
    assert "windows.h" not in CORE and "VirtualProtect" not in CORE and "memcpy(p," not in CORE, "the header decides, it never writes"


def test_the_project_lists_the_header():
    proj = (ROOT.parent / "src" / "uimod" / "uimod.vcxproj").read_text(encoding="utf-8")
    assert "src\\thinkersites_core.h" in proj
