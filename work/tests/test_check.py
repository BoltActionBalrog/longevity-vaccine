"""`install.py --check`: what the game is told at launch, and the decline memory it honours.

The pipe protocol is a CONTRACT with the DLL's parser (install.py, "--check (the game's query)").
These tests pin it as a truth table over (manifest, receipt, declines) -> (exit code, lines), and
assert the one property that matters most for a pipe reader: nothing but `key=value` lines.
The subprocess end of it -- a real python.exe, a real pipe -- lives in test_install_e2e.py.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import install as inst        # noqa: E402
import installer_exit as ix   # noqa: E402
import receipt as rc          # noqa: E402
import version as ver         # noqa: E402

inst._load_modules()

LINE = re.compile(r"^(latest|base|stale|new|manual)=[\x20-\x7e]*$")


def _doc(latest="1.0.0", **mods) -> dict:
    return {
        "schema": 1, "protocol": 1, "product": "longevity-vaccine",
        "latest": latest, "min_upgradable_from": "0.0.0",
        "manual_install_required": False, "manual_install_reason": None,
        "unsupported_versions": [], "unsupported_targets": [], "yanked": [],
        "modules": {n: ({"version": v, "url": "https://x/" + n, "sha256": "0" * 64,
                         "size": 1300 << 20} if isinstance(v, str) else v)
                    for n, v in mods.items()},
    }


def _state(base="1.0.0", **mods) -> dict:
    m = {"base": {"version": base}}
    m.update({n: {"version": v} for n, v in mods.items()})
    return {"modules": m, "target_id": "pracx", "source": "json"}


def _report(doc, state, declined=None):
    code, lines = inst.check_report(doc, state, declined or {})
    for ln in lines:
        assert LINE.match(ln), f"not a protocol line: {ln!r}"
    return code, lines


# ---------------------------------------------------------------- the truth table

def test_nothing_to_offer():
    code, lines = _report(_doc(base="1.0.0"), _state())
    assert (code, lines) == (ix.CHECK_NOTHING, ["latest=1.0.0"])


def test_a_base_update():
    code, lines = _report(_doc(latest="1.1.0", base="1.1.0"), _state(base="1.0.0"))
    assert code == ix.CHECK_UPDATES
    assert lines == ["latest=1.1.0", "base=1.0.0>1.1.0"]


def test_a_stale_pack_with_the_base_current():
    doc = _doc(base="1.0.0", **{"movies-hd": "1.2.0"})
    code, lines = _report(doc, _state(**{"movies-hd": "1.1.0"}))
    assert code == ix.CHECK_UPDATES
    assert lines == ["latest=1.0.0", f"stale=movies-hd|HD Cinematics|1.1.0>1.2.0|{1300 << 20}"]


def test_a_pack_the_player_does_not_have():
    doc = _doc(base="1.0.0", **{"portraits-hd": "1.0.0"})
    code, lines = _report(doc, _state())
    assert code == ix.CHECK_UPDATES
    assert lines == ["latest=1.0.0", f"new=portraits-hd|Turovetsky's HD Portrait Pack|1.0.0|{1300 << 20}"]


def test_everything_at_once_in_a_fixed_order():
    doc = _doc(latest="2.0.0", base="2.0.0", **{"movies-hd": "1.5.0", "portraits-hd": "1.0.0"})
    code, lines = _report(doc, _state(base="1.0.0", **{"movies-hd": "1.0.0"}))
    assert code == ix.CHECK_UPDATES
    assert [ln.split("=", 1)[0] for ln in lines] == ["latest", "base", "stale", "new"]


def test_a_kill_switch_is_manual_with_a_compiled_reason_key():
    doc = _doc(base="1.0.0")
    doc["manual_install_required"] = True
    doc["manual_install_reason"] = "bootstrap_defect"
    assert _report(doc, _state()) == (ix.CHECK_MANUAL, ["manual=bootstrap_defect"])
    doc["manual_install_reason"] = "See http://evil.example"      # not a key -> empty
    assert _report(doc, _state()) == (ix.CHECK_MANUAL, ["manual="])
    assert _report(_doc(base="1.0.0", latest="1.0.0") | {"protocol": 99}, _state()) \
        == (ix.CHECK_MANUAL, ["manual=protocol"])


def test_a_yanked_latest_is_silent_about_everything():
    doc = _doc(latest="1.1.0", base="1.1.0", **{"portraits-hd": "1.0.0"})
    doc["yanked"] = ["1.1.0"]
    assert _report(doc, _state(base="1.0.0")) == (ix.CHECK_NOTHING, [])


def test_a_module_the_installer_does_not_know_is_never_mentioned():
    doc = _doc(base="1.0.0", **{"weapons-hd": "1.0.0", "portraits-hd": "1.0.0"})
    _, lines = _report(doc, _state())
    assert not any("weapons" in ln for ln in lines)
    assert any(ln.startswith("new=portraits-hd|") for ln in lines)


def test_labels_are_compiled_in_never_from_the_manifest():
    doc = _doc(base="1.0.0")
    doc["modules"]["movies-hd"] = {"version": "1.2.0", "label": "Free RAM download",
                                   "name": "x", "size": 5, "url": "https://x", "sha256": "0"}
    _, lines = _report(doc, _state(**{"movies-hd": "1.0.0"}))
    assert lines[1] == "stale=movies-hd|HD Cinematics|1.0.0>1.2.0|5"


@pytest.mark.parametrize("size,shown", [(True, ""), (-1, ""), (1.5, ""), ("9", ""), (0, "0"),
                                        (7, "7"), (10 ** 400, ""), (2 ** 1100, "")])
def test_sizes_are_non_negative_integers_or_empty(size, shown):
    doc = _doc(base="1.0.0")
    doc["modules"]["movies-hd"] = {"version": "1.2.0", "size": size}
    _, lines = _report(doc, _state(**{"movies-hd": "1.0.0"}))
    assert lines[1].endswith(f"|{shown}")


def test_an_unreadable_receipt_version_is_offered_as_unknown():
    doc = _doc(latest="1.1.0", base="1.1.0", **{"movies-hd": "1.0.0"})
    state = {"modules": {"base": {"version": "what"}, "movies-hd": {"version": "?"}},
             "target_id": None}
    code, lines = _report(doc, state)
    assert code == ix.CHECK_UPDATES
    assert "base=0.0.0>1.1.0" in lines
    # An unreadable PACK version is still an INSTALLED pack (its files are on disk): it is
    # offered as stale from UNKNOWN, never as "new" and never silently skipped.
    assert any(ln.startswith("stale=movies-hd|HD Cinematics|0.0.0>1.0.0|") for ln in lines), lines
    assert not any(ln.startswith("new=") for ln in lines)


# ---------------------------------------------------------------- declines

def test_a_declined_item_is_omitted_only_at_the_declined_version():
    doc = _doc(latest="1.1.0", base="1.1.0", **{"movies-hd": "1.2.0", "portraits-hd": "1.0.0"})
    state = _state(base="1.0.0", **{"movies-hd": "1.0.0"})
    all_three = _report(doc, state)[1]
    assert len(all_three) == 4
    declined = {"base": "1.1.0", "movies-hd": "1.2.0", "new:portraits-hd": "1.0.0"}
    assert _report(doc, state, declined) == (ix.CHECK_NOTHING, ["latest=1.1.0"])
    # A NEWER version than the one declined is offered again.
    older = {"base": "1.0.5", "movies-hd": "1.1.9", "new:portraits-hd": "0.9.0"}
    assert _report(doc, state, older)[1] == all_three


def test_an_any_version_decline_hides_the_item_while_nothing_installed_is_pending():
    """`<item>:*` hides the item at every version -- the game's "Don't ask me again" on a NEW pack's
    offer (and what older builds wrote for every decline) -- for as long as nothing installed has an
    undeclined release."""
    doc = _doc(latest="1.1.0", base="1.1.0", **{"movies-hd": "1.2.0", "portraits-hd": "1.0.0"})
    state = _state(base="1.0.0", **{"movies-hd": "1.0.0"})
    star = {"base": rc.DECLINE_ANY, "movies-hd": rc.DECLINE_ANY,
            "new:portraits-hd": rc.DECLINE_ANY}
    assert _report(doc, state, star) == (ix.CHECK_NOTHING, ["latest=1.1.0"])
    # ... and stays hidden when the release moves on: every offer is still a declined one.
    doc2 = _doc(latest="3.0.0", base="3.0.0", **{"movies-hd": "2.5.0", "portraits-hd": "2.0.0"})
    assert _report(doc2, state, star) == (ix.CHECK_NOTHING, ["latest=3.0.0"])


# ---- THE RESET RULE (user, 2026-10-31): "a decline of any pack is reset when any new update
# releases for a module that is already installed". One undeclined offer for the base or an
# installed pack voids EVERY decline, so the popup lists everything --update would install.

def _kinds(lines) -> list:
    return [ln.split("=", 1)[0] + ("=" + ln.split("=", 1)[1].split("|")[0]
                                   if ln.startswith(("stale=", "new=")) else "")
            for ln in lines[1:]]


def test_a_declined_stale_pack_is_re_listed_when_the_core_is_newer():
    doc = _doc(latest="1.1.0", base="1.1.0", **{"movies-hd": "1.2.0"})
    state = _state(base="1.0.0", **{"movies-hd": "1.0.0"})
    code, lines = _report(doc, state, {"movies-hd": "1.2.0"})
    assert code == ix.CHECK_UPDATES
    assert _kinds(lines) == ["base", "stale=movies-hd"], lines
    # ... legacy `<id>:*` likewise.
    assert _kinds(_report(doc, state, {"movies-hd": rc.DECLINE_ANY})[1]) == ["base", "stale=movies-hd"]


def test_a_declined_new_pack_is_re_offered_when_an_installed_pack_has_an_undeclined_update():
    doc = _doc(latest="1.0.0", base="1.0.0", **{"movies-hd": "1.2.0", "portraits-hd": "1.0.0"})
    state = _state(**{"movies-hd": "1.0.0"})
    code, lines = _report(doc, state, {"new:portraits-hd": rc.DECLINE_ANY})
    assert code == ix.CHECK_UPDATES
    assert _kinds(lines) == ["stale=movies-hd", "new=portraits-hd"], lines


def test_a_declined_new_pack_returns_beside_the_installed_packs_next_release():
    """Hidden while the installed pack's offer is the declined one; offered again with everything
    once that pack moves past the declined version."""
    doc = _doc(latest="1.0.0", base="1.0.0", **{"movies-hd": "1.2.0", "portraits-hd": "2.0.0"})
    state = _state(**{"movies-hd": "1.0.0"})
    declined = {"movies-hd": "1.2.0", "new:portraits-hd": rc.DECLINE_ANY}
    assert _report(doc, state, declined) == (ix.CHECK_NOTHING, ["latest=1.0.0"])
    doc["modules"]["movies-hd"]["version"] = "1.3.0"
    assert _kinds(_report(doc, state, declined)[1]) == ["stale=movies-hd", "new=portraits-hd"]


def test_a_new_pack_declined_at_its_version_returns_at_the_next_one():
    """`new:<id>:<ver>` with nothing installed on offer: hidden at that version only."""
    doc = _doc(latest="1.0.0", base="1.0.0", **{"portraits-hd": "1.0.0"})
    assert _report(doc, _state(), {"new:portraits-hd": "1.0.0"}) == (ix.CHECK_NOTHING,
                                                                      ["latest=1.0.0"])
    doc["modules"]["portraits-hd"]["version"] = "1.1.0"
    assert _kinds(_report(doc, _state(), {"new:portraits-hd": "1.0.0"})[1]) == ["new=portraits-hd"]


def test_a_legacy_base_star_hides_new_packs_until_the_declines_are_reset():
    """`base:*` (older builds' update decline) is never voided by a newer base, so it holds new
    packs back at every release; Reset Skipped Updates is what ends it."""
    state = _state(base="1.0.0")
    for latest in ("1.1.0", "2.0.0", "9.0.0"):
        doc = _doc(latest=latest, base=latest, **{"portraits-hd": "1.0.0"})
        assert _report(doc, state, {"base": rc.DECLINE_ANY}) == (ix.CHECK_NOTHING,
                                                                 [f"latest={latest}"])
        assert _kinds(_report(doc, state, {})[1]) == ["base", "new=portraits-hd"]


def test_a_new_pack_alone_resets_nothing():
    """Only an offer for something INSTALLED voids the declines: a pack the player does not have
    is listed on its own, and a declined one beside it stays hidden."""
    doc = _doc(latest="1.0.0", base="1.0.0", **{"movies-hd": "1.0.0", "portraits-hd": "1.0.0"})
    code, lines = _report(doc, _state(), {"new:portraits-hd": rc.DECLINE_ANY})
    assert code == ix.CHECK_UPDATES and _kinds(lines) == ["new=movies-hd"], lines


# ---- and while the BASE offer stays declined, NEW packs are not offered either (user,
# 2026-10-31): the game's --only-listed hand-off fetches exactly the packs it lists, but a stale
# core always comes along. A declined stale PACK hides only itself.

def test_a_declined_stale_pack_alone_hides_only_itself():
    """The game hands off `--only-listed --modules <accepted>`, so accepting the new pack leaves
    the declined one where it is: nothing else needs hiding (user, 2026-10-31)."""
    doc = _doc(latest="1.0.0", base="1.0.0", **{"movies-hd": "1.2.0", "portraits-hd": "1.0.0"})
    state = _state(**{"movies-hd": "1.0.0"})
    for d in ({"movies-hd": "1.2.0"}, {"movies-hd": rc.DECLINE_ANY}):
        code, lines = _report(doc, state, d)
        assert code == ix.CHECK_UPDATES and _kinds(lines) == ["new=portraits-hd"], (d, lines)
    both = {"movies-hd": "1.2.0", "new:portraits-hd": rc.DECLINE_ANY}
    assert _report(doc, state, both) == (ix.CHECK_NOTHING, ["latest=1.0.0"])


def test_a_declined_base_beside_a_declined_pack_still_hides_new_packs():
    doc = _doc(latest="1.1.0", base="1.1.0", **{"movies-hd": "1.2.0", "portraits-hd": "1.0.0"})
    state = _state(base="1.0.0", **{"movies-hd": "1.0.0"})
    assert _report(doc, state, {"base": "1.1.0", "movies-hd": "1.2.0"}) == \
        (ix.CHECK_NOTHING, ["latest=1.1.0"])


def test_a_declined_base_alone_hides_new_packs():
    doc = _doc(latest="1.1.0", base="1.1.0", **{"portraits-hd": "1.0.0"})
    state = _state(base="1.0.0")
    for d in ({"base": "1.1.0"}, {"base": rc.DECLINE_ANY}):
        assert _report(doc, state, d) == (ix.CHECK_NOTHING, ["latest=1.1.0"]), d


def test_cleared_declines_bring_the_new_pack_back():
    doc = _doc(latest="1.1.0", base="1.1.0", **{"movies-hd": "1.2.0", "portraits-hd": "1.0.0"})
    state = _state(base="1.0.0", **{"movies-hd": "1.0.0"})
    assert _report(doc, state, {"base": "1.1.0", "movies-hd": "1.2.0"})[1] == ["latest=1.1.0"]
    assert _kinds(_report(doc, state, {})[1]) == ["base", "stale=movies-hd", "new=portraits-hd"]


def test_an_undeclined_installed_offer_still_lists_everything():
    doc = _doc(latest="1.1.0", base="1.1.0", **{"movies-hd": "1.2.0", "portraits-hd": "1.0.0"})
    state = _state(base="1.0.0", **{"movies-hd": "1.0.0"})
    declined = {"base": "1.1.0", "new:portraits-hd": rc.DECLINE_ANY}    # the pack is undeclined
    code, lines = _report(doc, state, declined)
    assert code == ix.CHECK_UPDATES
    assert _kinds(lines) == ["base", "stale=movies-hd", "new=portraits-hd"], lines


def test_with_nothing_installed_on_offer_new_packs_follow_their_own_declines():
    doc = _doc(latest="1.0.0", base="1.0.0", **{"movies-hd": "1.0.0", "portraits-hd": "1.0.0"})
    state = _state()
    assert _kinds(_report(doc, state)[1]) == ["new=movies-hd", "new=portraits-hd"]
    assert _kinds(_report(doc, state, {"new:movies-hd": rc.DECLINE_ANY})[1]) == ["new=portraits-hd"]
    # A decline of something NOT on offer (an installed pack that is current) hides nothing.
    current = _state(**{"movies-hd": "1.0.0"})
    assert _kinds(_report(doc, current, {"movies-hd": "1.0.0"})[1]) == ["new=portraits-hd"]


def test_everything_declined_offers_nothing():
    doc = _doc(latest="1.1.0", base="1.1.0", **{"movies-hd": "1.2.0", "portraits-hd": "1.0.0"})
    state = _state(base="1.0.0", **{"movies-hd": "1.0.0"})
    declined = {"base": "1.1.0", "movies-hd": "1.2.0", "new:portraits-hd": rc.DECLINE_ANY}
    assert _report(doc, state, declined) == (ix.CHECK_NOTHING, ["latest=1.1.0"])


def test_a_legacy_base_star_is_hidden_alone_and_re_listed_beside_an_undeclined_offer():
    doc = _doc(latest="1.1.0", base="1.1.0", **{"movies-hd": "1.2.0", "portraits-hd": "1.0.0"})
    state = _state(base="1.0.0", **{"movies-hd": "1.0.0"})
    # Nothing else pending (the pack declined at its version, the new pack declined): hidden.
    quiet = {"base": rc.DECLINE_ANY, "movies-hd": "1.2.0", "new:portraits-hd": rc.DECLINE_ANY}
    assert _report(doc, state, quiet) == (ix.CHECK_NOTHING, ["latest=1.1.0"])
    # The pack has an undeclined release: every decline is void, the base included.
    code, lines = _report(doc, state, {"base": rc.DECLINE_ANY})
    assert _kinds(lines) == ["base", "stale=movies-hd", "new=portraits-hd"], lines
    # A pack declined at an OLDER version is an undeclined release too.
    stale_again = dict(quiet, **{"movies-hd": "1.1.0"})
    assert _kinds(_report(doc, state, stale_again)[1]) == ["base", "stale=movies-hd",
                                                           "new=portraits-hd"]


def test_the_reset_never_touches_the_manual_notice():
    doc = _doc(latest="1.1.0", base="1.1.0", **{"movies-hd": "1.2.0"})
    doc["manual_install_required"] = True
    doc["manual_install_reason"] = "bootstrap_defect"
    state = _state(base="1.0.0", **{"movies-hd": "1.0.0"})
    assert _report(doc, state, {"manual-bootstrap_defect": rc.DECLINE_ANY}) == (ix.CHECK_NOTHING, [])


def test_new_star_does_not_hide_the_same_ids_stale_line():
    """`new:<id>:*` names the offer of a pack the player does NOT have; the STALE line is a
    different item (a pack the player has)."""
    doc = _doc(latest="1.1.0", base="1.1.0", **{"movies-hd": "1.2.0"})
    state = _state(base="1.1.0", **{"movies-hd": "1.0.0"})
    _, lines = _report(doc, state, {"new:movies-hd": rc.DECLINE_ANY})
    assert _kinds(lines) == ["stale=movies-hd"]


def test_manual_star_silences_the_kill_switch_notice_for_that_reason_only(capsys):
    doc = _doc(latest="1.0.0")
    doc["manual_install_required"] = True
    doc["manual_install_reason"] = "bootstrap_defect"
    assert _report(doc, _state())[0] == ix.CHECK_MANUAL
    assert rc.manual_decline_item("bootstrap_defect") == "manual-bootstrap_defect"
    code, lines = _report(doc, _state(), {"manual-bootstrap_defect": rc.DECLINE_ANY})
    assert (code, lines) == (ix.CHECK_NOTHING, [])
    assert "manual install required (bootstrap_defect)" in capsys.readouterr().err   # never the pipe
    # A DIFFERENT reason is a different notice and shows again.
    doc["manual_install_reason"] = "too_old"
    assert _report(doc, _state(), {"manual-bootstrap_defect": rc.DECLINE_ANY})[0] == ix.CHECK_MANUAL
    assert _report(doc, _state(), {"manual-too_old": rc.DECLINE_ANY})[0] == ix.CHECK_NOTHING
    # No reason at all -> `manual-unspecified`.
    doc["manual_install_reason"] = None
    assert rc.manual_decline_item(None) == "manual-unspecified" == rc.manual_decline_item("")
    assert _report(doc, _state(), {"manual-unspecified": rc.DECLINE_ANY})[0] == ix.CHECK_NOTHING
    # A per-version "manual" entry means nothing (the notice has no version).
    assert _report(doc, _state(), {"manual-unspecified": "1.0.0"})[0] == ix.CHECK_MANUAL


def test_decline_refuses_what_the_dll_reader_would_drop(tmp_path):
    """Both sides keep the same entries, so a rewrite by either never erases the other's."""
    g = tmp_path / "game"
    g.mkdir()
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    assert rc.decline(g, "x" * 63, "*")
    assert rc.decline(g, "y" * 64, "*") is False                     # DLL item cap is 63
    # A value that would read back truncated is refused, not written cut.
    for i in range(28):                                              # 65 + 28 * 34 = 1017 chars
        assert rc.decline(g, f"module-name-{i:02d}-padding-more", "1.0.0")
    assert 1000 < len(rc.ini_get(g, rc.KEY_DECLINED)) < 1023
    assert rc.decline(g, "one-more-module-that-does-not-fit-in-the-profile-buffer", "1.0.0") is False
    assert "one-more" not in rc.ini_get(g, rc.KEY_DECLINED)
    # Exotic whitespace is NOT stripped (the DLL strips only space/tab/CR/LF).
    (g / "Alpha Centauri.ini").write_text("[Longevity]\nDeclinedUpdates=base:\x0b*;movies-hd:*\n",
                                          encoding="utf-8")
    assert rc.declined(g) == {"movies-hd": "*"}


def test_any_version_declines_round_trip_and_clear(tmp_path):
    g = tmp_path / "game"
    g.mkdir()
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    assert rc.decline(g, "movies-hd", "1.2.0")
    assert rc.decline(g, "base", rc.DECLINE_ANY)
    assert rc.decline(g, "new:portraits-hd", " * ")               # tolerated whitespace
    assert rc.decline(g, "manual", "*")
    assert rc.declined(g) == {"base": "*", "manual": "*", "movies-hd": "1.2.0",
                              "new:portraits-hd": "*"}
    assert rc.ini_get(g, rc.KEY_DECLINED) == "base:*;manual:*;movies-hd:1.2.0;new:portraits-hd:*"
    assert rc.decline(g, "base", "2.0.0")                          # a version replaces the star
    assert rc.declined(g)["base"] == "2.0.0"
    assert rc.decline(g, "base", "*") and rc.declined(g)["base"] == "*"
    # Hand-edited variants that are NOT the wildcard stay refused / dropped.
    assert rc.decline(g, "base", "**") is False
    assert rc.decline(g, "base", "*1.0.0") is False
    (g / "Alpha Centauri.ini").write_text(
        "[Longevity]\nDeclinedUpdates=base:**;movies-hd: * ;x:*.*;new:y:*\n", encoding="ascii")
    assert rc.declined(g) == {"movies-hd": "*", "new:y": "*"}
    assert rc.clear_declines(g)
    assert rc.declined(g) == {} and rc.ini_get(g, rc.KEY_DECLINED) == ""


def test_the_one_download_url_is_the_same_everywhere():
    """installer_exit prints it in the crash verdict but cannot import manifest (stdlib only)."""
    import manifest as mf
    assert ix.DOWNLOAD_URL == mf.DOWNLOAD_URL


def test_declining_a_pack_never_hides_a_base_release():
    doc = _doc(latest="1.1.0", base="1.1.0", **{"movies-hd": "1.2.0"})
    state = _state(base="1.0.0", **{"movies-hd": "1.0.0"})
    code, lines = _report(doc, state, {"movies-hd": "1.2.0"})
    assert code == ix.CHECK_UPDATES and "base=1.0.0>1.1.0" in lines


def test_declines_round_trip_through_the_ini(tmp_path):
    g = tmp_path / "game"
    g.mkdir()
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    assert rc.declined(g) == {}
    assert rc.decline(g, "base", "1.1.0")
    assert rc.decline(g, "new:portraits-hd", "1.0.0")
    assert rc.decline(g, "movies-hd", " 1.2.0\r\n")          # tolerated whitespace, normalised
    assert rc.declined(g) == {"base": "1.1.0", "movies-hd": "1.2.0", "new:portraits-hd": "1.0.0"}
    assert rc.decline(g, "base", "1.2.0")                     # re-declining replaces
    assert rc.declined(g)["base"] == "1.2.0"
    assert rc.ini_get(g, rc.KEY_DECLINED) == "base:1.2.0;movies-hd:1.2.0;new:portraits-hd:1.0.0"


@pytest.mark.parametrize("item,version", [
    ("a;b", "1.0.0"), ("x=y", "1.0.0"), ("[Longevity]", "1.0.0"),
    ("", "1.0.0"), (None, "1.0.0"), ("base", "1.0"), ("base", "١.٠.١"), ("base", None),
])
def test_a_malformed_decline_is_refused_and_writes_nothing(tmp_path, item, version):
    g = tmp_path / "game"
    g.mkdir()
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    assert rc.decline(g, item, version) is False
    assert rc.ini_get(g, rc.KEY_DECLINED) == ""


def test_a_hand_edited_decline_list_degrades_to_what_parses(tmp_path):
    g = tmp_path / "game"
    g.mkdir()
    (g / "Alpha Centauri.ini").write_text(
        "[Longevity]\nDeclinedUpdates=base:1.1.0;garbage;movies-hd:nope;;new:x:2.0.0\n",
        encoding="ascii")
    assert rc.declined(g) == {"base": "1.1.0", "new:x": "2.0.0"}


def _game(tmp_path, ini: str = "[UIMod]\n") -> Path:
    g = tmp_path / "game"
    g.mkdir()
    (g / "Alpha Centauri.ini").write_text(ini, encoding="ascii")
    return g


def test_a_corrupt_json_version_falls_back_to_the_ini(tmp_path):
    """A garbage BaseVersion in the JSON used to become UNKNOWN even though the ini still had
    the real one -- and UNKNOWN then read as "too old"."""
    g = _game(tmp_path, "[UIMod]\n[Longevity]\nBaseVersion=0.1.0\nMoviesHdVersion=garbage\n")
    (g / rc.JSON_NAME).write_text(json.dumps({"schema": 1, "modules": {
        "base": {"version": "garbage"}}}), encoding="utf-8")
    state = rc.read(g)
    assert rc.module_version(state, "base") == "0.1.0"
    # and an unreadable ini pack version still counts as INSTALLED (its files are on disk)
    assert "movies-hd" in rc.installed_modules(state)
    assert rc.module_version(state, "movies-hd") == ver.UNKNOWN


def test_a_truncated_decline_list_drops_its_last_entry(tmp_path):
    """The profile API cuts a value at 1023 chars; `base:9.9.99` cut to `base:9.9.9` would
    suppress a real 9.9.9 offer."""
    filler = ";".join(f"new:x{i}:1.0.0" for i in range(80))       # well over 1024 chars
    g = _game(tmp_path, f"[UIMod]\n[Longevity]\nDeclinedUpdates={filler};base:9.9.99\n")
    d = rc.declined(g)
    assert "base" not in d
    assert len(d) > 0


def test_a_whitespace_only_decline_item_is_refused(tmp_path):
    """decline() used to return True for " " and write an entry declined() then dropped."""
    g = _game(tmp_path)
    for item in (" ", "\t", "a\x7fb", "néw:x"):
        assert rc.decline(g, item, "1.0.0") is False, repr(item)
    assert rc.declined(g) == {}
    assert rc.decline(g, " new:x ", "1.0.0") is True          # surrounding space is tolerated
    assert rc.declined(g) == {"new:x": "1.0.0"}


def test_the_fallback_cache_is_per_user_and_per_install(tmp_path, monkeypatch):
    import fetch as fetchmod
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "la"))
    a = fetchmod.fallback_cache_dir(tmp_path / "game-a")
    b = fetchmod.fallback_cache_dir(tmp_path / "game-b")
    assert a != b and a.is_dir() and b.is_dir()
    assert a.parent.parent == tmp_path / "la" / "LongevityVaccine"
    assert fetchmod.fallback_cache_dir(tmp_path / "game-a") == a      # stable across launches
    ro = tmp_path / "ro"
    ro.write_bytes(b"")                                                # a file where a dir goes
    with pytest.raises(OSError):
        fetchmod.assert_writable(ro)


def test_the_import_trace_and_the_runtime_verify_cover_check():
    """The trimmed runtime is measured from these scenarios; --check is the one the game runs
    at every launch, and it was missing from both."""
    trace = (Path(__file__).resolve().parent.parent / "scripts" / "trace_imports.py") \
        .read_text(encoding="utf-8")
    assert '("check", [install, "--check"' in trace
    build = (Path(__file__).resolve().parent.parent / "scripts" / "build_runtime.py") \
        .read_text(encoding="utf-8")
    assert '"--check"' in build and '"check"' in build
    import build_runtime
    import trace_imports
    assert build_runtime.EXPECTED_NONZERO == trace_imports.EXPECTED_NONZERO >= {"check"}


def test_the_check_exit_codes_do_not_collide_with_install_codes():
    install_codes = {ix.EXIT_OK, ix.EXIT_ERROR, ix.EXIT_NO_GAME, ix.EXIT_ABORTED,
                     ix.EXIT_UNSUPPORTED, ix.EXIT_INTERRUPTED, ix.EXIT_CRASH}
    for c in (ix.CHECK_UPDATES, ix.CHECK_MANUAL, ix.CHECK_FAILED):
        assert c not in install_codes
    assert ix.CHECK_NOTHING == ix.EXIT_OK
