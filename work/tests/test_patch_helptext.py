"""patch_helptext.py: the Datalinks text patches (helpx.txt cloaking rules, conceptsx.txt Waypoints paragraph).

Pure checks on synthetic files (no game install needed) plus, when the game folder is present, the real live files
(read only): every stock block must be found exactly once in the pristine file, the patched result must start with
the version marker, keep the file's line ending, and contain each new block exactly once -- and uninstall must be the
EXACT inverse: the bytes the file would have had if we had never patched it, whatever happened to it in between.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import config  # noqa: E402
import patch_helptext as ph  # noqa: E402


def _synthetic(spec: dict, nl: bytes) -> bytes:
    """A minimal 'pristine' file: a comment header, then every stock block once, with filler between."""
    parts = [b";", b"; synthetic", b"#FILLER0", b"filler text", b""]
    for tag, stock in spec["stock"].items():
        parts += [tag] + stock + [b""]
    parts += [b"#FILLER1", b"more", b""]
    return nl.join(parts) + nl


def _newer_stock(spec: dict, nl: bytes) -> bytes:
    """A Thinker / GOG update: the same stock blocks, in another order, with different text all around them."""
    parts = [b";", b"; Thinker 9.9 header", b"#NEWENTRY", b"an entry the update added", b""]
    for tag, stock in reversed(list(spec["stock"].items())):
        parts += [b"#BEFORE" + tag[1:], b"updated words", b"", tag] + stock + [b"", b"after it"]
    parts += [b"#TAIL", b"tail", b""]
    return nl.join(parts) + nl


@pytest.mark.parametrize("name", sorted(ph.FILES))
@pytest.mark.parametrize("nl", [b"\r\n", b"\n"], ids=["crlf", "lf"])
def test_patch_bytes_synthetic(name: str, nl: bytes) -> None:
    spec = ph.FILES[name]
    data = _synthetic(spec, nl)
    out = ph.patch_bytes(data, spec)
    assert out.startswith(spec["mark"] + nl)
    assert out.count(b"\r\n") == (out.count(b"\n") if nl == b"\r\n" else 0), "line ending changed"
    for tag in spec["stock"]:
        new = tag + nl + nl.join(spec["new"][tag]) + nl
        assert out.count(new) == 1, f"{name} {tag!r} new block not exactly once"
        assert out.count(tag + nl) == 1, f"{name} {tag!r} tag duplicated"
    # idempotence lives in patch_file's marker check (a new block keeps the stock text as its prefix, so
    # patch_bytes alone would happily patch twice): the marker must be the first line
    assert out.split(nl, 1)[0] == spec["mark"]


@pytest.mark.parametrize("name", sorted(ph.FILES))
def test_new_text_is_well_formed(name: str) -> None:
    spec = ph.FILES[name]
    for tag, lines in spec["new"].items():
        for ln in lines:
            assert len(ln) <= 96, f"{name} {tag!r}: a physical line over 96 chars ({len(ln)}): {ln!r}"
            assert b"\n" not in ln and b"\r" not in ln
            assert ln.count(b"{") == ln.count(b"}"), f"{name} {tag!r}: unbalanced braces in {ln!r}"
        assert lines[: len(spec["stock"][tag])] == spec["stock"][tag] or tag == b"#ABILDESC6", \
            f"{name} {tag!r}: the stock text is not kept verbatim at the top"


#: The text each marker revision stands for. A wording change under an unchanged marker is invisible to the patcher
#: (the live file reads "already patched" and keeps the OLD text -- it happened on 2026-10-30 with the ZOC sentence):
#: when this fails, bump the file's MARK, append the previous one to its OLD_MARKS, add the new text to its REVISIONS
#: and record the new hash here. The older helpx hashes are of the text patch_helptext.py wrote at c34738c (v6),
#: fa287e6 (v7) and f96dec3 (v8), computed from git history on 2026-11-10: they pin HELPX_REVISIONS to what those
#: revisions really wrote, which is what restore takes back out.
TEXT_OF_MARK = {
    b"; longevity-helptext v6": "9d62f33535b3",
    b"; longevity-helptext v7": "8103c05e792b",
    b"; longevity-helptext v8": "f4760e51f927",
    b"; longevity-helptext v12": "e16bd4ed66b4",
    b"; longevity-concepts v2": "89446025592c",
    b"; longevity-concepts v3": "6ca5b016e0ca",
}


def _text_hash(new: dict) -> str:
    return hashlib.sha1(b"\n".join(b"\n".join(v) for v in new.values())).hexdigest()[:12]


@pytest.mark.parametrize("name", sorted(ph.FILES))
def test_marker_matches_the_text(name: str) -> None:
    spec = ph.FILES[name]
    h = _text_hash(spec["new"])
    assert spec["mark"] in TEXT_OF_MARK, f"{name}: new marker {spec['mark']!r} -- record its text hash {h} in TEXT_OF_MARK"
    assert TEXT_OF_MARK[spec["mark"]] == h, \
        f"{name}: the text changed under marker {spec['mark']!r} -- bump the marker (and OLD_MARKS), then record {h}"
    assert spec["mark"] not in spec["old_marks"]
    for old in spec["old_marks"]:
        assert old < spec["mark"] or len(old) < len(spec["mark"]), f"{name}: old marker {old!r} not older than {spec['mark']!r}"


#: The whole layout each revision patched with -- tags, stock blocks and new blocks, in order:
#: sha1(repr((sorted(stock.items()), list(new.items())))). Computed on 2026-11-10 by running the HISTORICAL modules
#: (git show <commit>:work/scripts/patch_helptext.py at c34738c, fa287e6, 6054951, f96dec3, 0eb472b), not this one,
#: so it pins HELPX_REVISIONS / CONCEPTS_REVISIONS to what those builds really did (audit 2026-11-10: TEXT_OF_MARK
#: alone covers only the new lines). The marker's place (first line, the file's newline) is _apply's, pinned by
#: test_every_older_revision.
LAYOUT_OF_MARK = {
    b"; longevity-helptext v6": "0579bc28edca",
    b"; longevity-helptext v7": "e6668899ac34",
    b"; longevity-helptext v8": "decfa6c689fd",
    b"; longevity-helptext v12": "e9ee06787e37",
    b"; longevity-concepts v2": "c7540f483b4b",
    b"; longevity-concepts v3": "afa1b664a9d3",
}


@pytest.mark.parametrize("name", sorted(ph.FILES))
def test_every_revision_on_record_is_the_text_it_wrote(name: str) -> None:
    """REVISIONS is what restore takes back out: the current text under the current marker, each older one under its
    own (hash-pinned to git history), and nothing under a marker the file never carried."""
    spec = ph.FILES[name]
    assert spec["revisions"][spec["mark"]] is spec["new"]
    for mark, new in spec["revisions"].items():
        assert mark == spec["mark"] or mark in spec["old_marks"], f"{name}: {mark!r} is not one of our markers"
        assert list(new) == list(spec["stock"]), f"{name} {mark!r}: blocks differ from the stock tags"
        assert TEXT_OF_MARK.get(mark) == _text_hash(new), f"{name} {mark!r}: not the text that revision wrote"
        layout = hashlib.sha1(repr((sorted(spec["stock"].items()), list(new.items()))).encode()).hexdigest()[:12]
        assert LAYOUT_OF_MARK.get(mark) == layout, f"{name} {mark!r}: not the layout that revision patched with"


def test_the_safety_checks_survive_python_optimize() -> None:
    """The stock-block and undo checks are raises, not asserts: a player's PYTHONOPTIMIZE must not switch them off
    (audit 2026-11-10)."""
    import subprocess
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import patch_helptext as ph\n"
            "try:\n    ph.patch_bytes(b'not the stock text\\n', ph.FILES['helpx.txt'])\n"
            "except AssertionError:\n    print('raised')\n")
    out = subprocess.run([sys.executable, "-OO", "-c", code, str(ROOT / "scripts")], capture_output=True, text=True)
    assert out.stdout.strip() == "raised", out


# ---------------------------------------------------------------- the exact inverse (what uninstall does)

@pytest.mark.parametrize("name", sorted(ph.FILES))
@pytest.mark.parametrize("nl", [b"\r\n", b"\n"], ids=["crlf", "lf"])
def test_unpatch_bytes_is_the_exact_inverse(name: str, nl: bytes) -> None:
    spec = ph.FILES[name]
    for pristine in (_synthetic(spec, nl), _newer_stock(spec, nl), _synthetic(spec, nl).rstrip(b"\r\n")):
        assert ph.unpatch_bytes(ph.patch_bytes(pristine, spec), spec) == pristine


@pytest.mark.parametrize("name", sorted(ph.FILES))
def test_the_re_patch_proof_refuses_a_file_our_patch_could_not_have_written(name: str) -> None:
    """Pins the proof itself (audit 2026-11-16: removing it left every test green). Our blocks are there once and
    the marker is right, so a naive inverse "succeeds" -- but the result holds a stock block twice, which our patch
    refuses to patch: these bytes cannot have come from patching that result, and the file is left alone."""
    spec = ph.FILES[name]
    tag, stock = next(iter(spec["stock"].items()))
    extra = ph._block(tag, stock, b"\r\n")
    data = ph.patch_bytes(_synthetic(spec, b"\r\n"), spec) + extra
    with pytest.raises(ph.Refused) as r:
        ph.unpatch_bytes(data, spec)
    assert r.value.status == ph.EDITED and "patch back" in r.value.detail, r.value.detail


@pytest.mark.parametrize("name", sorted(ph.FILES))
def test_a_sentence_of_ours_outside_our_entries_is_refused_not_left_behind(name: str) -> None:
    """A line of ours copied outside our block: taking the blocks out would leave it, the file would read as
    unmarked on every later run, and the uninstall would have said RESTORED (audit 2026-11-16)."""
    spec = ph.FILES[name]
    ours = sorted(ph._our_lines(spec))[0]
    data = ph.patch_bytes(_synthetic(spec, b"\r\n"), spec) + ours + b"\r\n"
    with pytest.raises(ph.Refused) as r:
        ph.unpatch_bytes(data, spec)
    assert r.value.status == ph.EDITED and "outside its entries" in r.value.detail, r.value.detail


@pytest.mark.parametrize("name", sorted(ph.FILES))
@pytest.mark.parametrize("how", ["trailing-space", "trailing-tab", "leading-space", "caret", "run-on"])
def test_a_sentence_of_ours_copied_with_blanks_or_run_on_is_still_found(name: str, how: str) -> None:
    """A copied sentence with a blank or a '^' around it, or run onto the end of the last line (the stock
    conceptsx.txt has no final line break), read as none of ours: RESTORED was said with it still in the file (audit
    2026-11-16, D8). Found inside our patched file, and without the marker as unmarked."""
    spec = ph.FILES[name]
    ours = sorted(ph._our_lines(spec))[0]
    copied = {"trailing-space": ours + b" \r\n", "trailing-tab": ours + b"\t\r\n", "leading-space": b" " + ours + b"\r\n",
              "caret": b"^" + ours + b"\r\n", "run-on": b" " + ours}[how]
    patched = ph.patch_bytes(_synthetic(spec, b"\r\n"), spec)
    with pytest.raises(ph.Refused) as r:
        ph.unpatch_bytes(patched + copied, spec)
    assert r.value.status == ph.EDITED and "outside its entries" in r.value.detail, r.value.detail
    with pytest.raises(ph.Refused) as r:
        ph.unpatch_bytes(_synthetic(spec, b"\r\n") + copied, spec)
    assert r.value.status == ph.UNMARKED, r.value.status


def test_no_sentence_of_ours_is_found_in_the_stock_text() -> None:
    """Matching anywhere in a line must never claim the stock text: no sentence of ours is part of it."""
    for spec in ph.FILES.values():
        stock = _synthetic(spec, b"\r\n")
        assert not ph._carries_our_text(stock, spec)
        assert all(len(s) >= ph.OUR_LINE_MIN and s == s.strip() and not s.startswith(b"^") for s in ph._our_lines(spec))


def test_an_old_marker_is_not_read_as_a_newer_one() -> None:
    """v1 is a prefix of v12: only the whole first line names the revision."""
    spec = ph.FILES["helpx.txt"]
    assert ph.marker_of(spec["mark"] + b"\r\nx", spec) == spec["mark"]
    assert ph.marker_of(b"; longevity-helptext v1\r\nx", spec) == b"; longevity-helptext v1"
    assert ph.marker_of(b"; longevity-helptext v13\r\nx", spec) is None


def test_a_padded_marker_line_is_still_ours() -> None:
    """Pinned on its own (audit round 3: the edited-file tests also trip _carries_our_text, which hid a revert)."""
    spec = ph.FILES["conceptsx.txt"]
    for pad in (b" ", b"\t", b"  \t"):
        assert ph.marker_of(spec["mark"] + pad + b"\r\nx", spec) == spec["mark"]
        assert ph.marker_of(pad + spec["mark"] + b"\nx", spec) == spec["mark"]
        assert ph._stray_marker(b"x\r\n" + spec["mark"] + pad + b"\r\n", spec)


def test_only_a_higher_number_is_a_newer_marker() -> None:
    spec = ph.FILES["helpx.txt"]
    newer = [b"; longevity-helptext v13", b"; longevity-helptext v99999", b"; longevity-helptext v13 ",
             b"; longevity-helptext v" + b"1" * 5000]     # past int()'s digit limit: must not raise (audit round 5)
    not_newer = [b"; longevity-helptext v0", b"; longevity-helptext v012", b"; longevity-helptext v11",
                 b"; longevity-helptext v12", b"; longevity-helptext v12a", b"; longevity-helptext v",
                 b"; longevity-helptext v-1", b"; longevity-helptext v 13", b"; longevity-something v13"]
    for m in newer:
        assert ph._newer_marker(m + b"\r\nx", spec) == m.strip(), m
    for m in not_newer:
        assert ph._newer_marker(m + b"\r\nx", spec) is None, m


def test_a_huge_newer_marker_is_not_echoed_in_full() -> None:
    spec = ph.FILES["helpx.txt"]
    with pytest.raises(ph.Refused) as r:
        ph.unpatch_bytes(b"; longevity-helptext v" + b"1" * 5000 + b"\r\nx\r\n", spec)
    assert r.value.status == ph.NEWER_REVISION and len(str(r.value)) < 300, len(str(r.value))
    assert "v" + "1" * 40 + "..." in r.value.detail, r.value.detail     # 40 digits shown, not 40 bytes of line


def test_an_unmarked_file_with_our_wording_does_not_claim_it_was_ours() -> None:
    """Someone else's file may quote a sentence of ours: the refusal must not say the mod patched it (audit round 5)."""
    spec = ph.FILES["conceptsx.txt"]
    ours = sorted(ph._our_lines(spec))[0]
    data = _synthetic(spec, b"\r\n").replace(b"#FILLER1\r\n", b"#FILLER1\r\n" + ours + b"\r\n")
    with pytest.raises(ph.Refused) as r:
        ph.unpatch_bytes(data, spec)
    assert r.value.status == ph.UNMARKED and r.value.why == ph.UNMARKED_WHY
    assert "patched" not in r.value.why and "changed after" not in r.value.why


def _thinker_shaped(spec: dict, nl: bytes) -> bytes:
    """Like Thinker's real smac_mod\\helpx.txt: each stock entry runs straight on into a '^' break and a paragraph
    of its own ('^Desc: ...'), the same way ours does -- it must still read as stock (audit round 4: a one-line
    signature refused Thinker's real file forever, and no test noticed)."""
    parts = [b";", b"; Thinker-shaped", b""]
    for tag, stock in spec["stock"].items():
        parts += [tag] + stock + [b"^", b"^Desc: a paragraph Thinker adds.", b"", b"#AFTER" + tag[1:], b"x", b""]
    return nl.join(parts) + nl


@pytest.mark.parametrize("name", sorted(ph.FILES))
@pytest.mark.parametrize("nl", [b"\r\n", b"\n"], ids=["crlf", "lf"])
def test_a_thinker_shaped_file_patches_and_restores(tmp_path, name: str, nl: bytes) -> None:
    spec = ph.FILES[name]
    data = _thinker_shaped(spec, nl)
    with pytest.raises(ph.Refused) as r:
        ph.unpatch_bytes(data, spec)
    assert r.value.status == ph.UNPATCHED
    g = tmp_path / "g"
    g.mkdir()
    (g / name).write_bytes(data)
    assert ph.patch_folder(g, say=_quiet) == {name: ph.PATCHED}
    assert ph.restore_folder(g, say=_quiet) == {name: ph.RESTORED}
    assert (g / name).read_bytes() == data


@pytest.mark.parametrize("name", sorted(ph.FILES))
@pytest.mark.parametrize("nl", [b"\r\n", b"\n"], ids=["crlf", "lf"])
def test_our_text_without_its_marker_is_found_in_either_line_ending(tmp_path, name: str, nl: bytes) -> None:
    """The marker gone and the end of our text reworded, in LF as well as CRLF (audit round 4: LF was unpinned)."""
    spec = ph.FILES[name]
    patched = ph.patch_bytes(_synthetic(spec, nl), spec)
    tag = next(iter(spec["new"]))
    last = spec["new"][tag][-1]
    edited = patched[len(spec["mark"] + nl):].replace(last, last + b" (note)")
    with pytest.raises(ph.Refused) as r:
        ph.unpatch_bytes(edited, spec)
    assert r.value.status == ph.UNMARKED


@pytest.mark.parametrize("name", sorted(ph.FILES))
@pytest.mark.parametrize("nl", [b"\r\n", b"\n"], ids=["crlf", "lf"])
def test_our_text_without_its_marker_survives_any_one_edit(name: str, nl: bytes) -> None:
    """The marker gone and ANY one of our sentences reworded (the first one included: audit round 5, one comma in
    conceptsx's first added sentence let the paragraph be added twice): still recognised, refused as UNMARKED."""
    spec = ph.FILES[name]
    body = ph.patch_bytes(_synthetic(spec, nl), spec)[len(spec["mark"] + nl):]
    mine = [ln for lines in spec["new"].values() for ln in lines if ln in ph._our_lines(spec)]
    assert mine
    for ln in mine:
        edited = body.replace(ln, ln.replace(b" ", b"  ", 1))
        assert edited != body
        with pytest.raises(ph.Refused) as r:
            ph.unpatch_bytes(edited, spec)
        assert r.value.status == ph.UNMARKED, ln


def test_our_sentences_are_ours_alone() -> None:
    """Every line used to recognise our text is a real sentence (OUR_LINE_MIN) and not stock text."""
    for name, spec in ph.FILES.items():
        stock = {ln for lines in spec["stock"].values() for ln in lines}
        for ln in ph._our_lines(spec):
            assert len(ln) >= ph.OUR_LINE_MIN and ln not in stock, (name, ln)
        for new in spec["revisions"].values():   # every revision's text can be recognised by some sentence of it
            assert any(ln in ph._our_lines(spec) for lines in new.values() for ln in lines), name


@pytest.mark.parametrize("name", sorted(ph.FILES))
def test_a_newer_versions_marker_is_left_alone(tmp_path, name: str) -> None:
    """An older installer run over a newer install: the newer build's text is never re-patched or taken out, and the
    status says so (not 'edited', whose detail would be false)."""
    spec = ph.FILES[name]
    family = spec["mark"].rsplit(b" v", 1)[0] + b" v"
    newer = family + b"99" + b"\r\n" + ph.patch_bytes(_synthetic(spec, b"\r\n"), spec)[len(spec["mark"]) + 2:]
    g = tmp_path / "g"
    g.mkdir()
    (g / name).write_bytes(newer)
    lines = []
    assert ph.patch_folder(g, say=lines.append) == {name: ph.NEWER_REVISION}
    assert ph.restore_folder(g, say=lines.append) == {name: ph.NEWER_REVISION}
    assert (g / name).read_bytes() == newer
    assert all("newer Longevity Vaccine version" in ln for ln in lines), lines


def test_patch_never_writes_what_it_could_not_undo(tmp_path, monkeypatch) -> None:
    """The self-check before the write, pinned on its own: a patch whose result would not undo exactly leaves the
    file alone (audit round 3: removing the check went unnoticed)."""
    g = _game_folder(tmp_path, smac_mod=False)
    pristine = (g / "conceptsx.txt").read_bytes()
    monkeypatch.setattr(ph, "patch_bytes", lambda data, spec: spec["mark"] + b"\r\n" + data)   # blocks not replaced
    assert ph.patch_folder(g, say=_quiet)["conceptsx.txt"] == ph.FOREIGN
    assert (g / "conceptsx.txt").read_bytes() == pristine


# ---------------------------------------------------------------- folders (what the installer calls)

def _game_folder(tmp_path: pathlib.Path, smac_mod: bool = True, nl: bytes = b"\r\n") -> pathlib.Path:
    """A fake game folder: both Datalinks files at the top level and, like a Thinker install, under smac_mod\\."""
    g = tmp_path / "game"
    folders = [g] + ([g / "smac_mod"] if smac_mod else [])
    for d in folders:
        d.mkdir(parents=True, exist_ok=True)
        for name, spec in ph.FILES.items():
            (d / name).write_bytes(_synthetic(spec, nl))
    return g


def _quiet(_: str) -> None:
    pass


def test_patch_folder_patches_the_game_folder_and_thinkers_smac_mod_copies(tmp_path) -> None:
    g = _game_folder(tmp_path)
    res = ph.patch_folder(g, say=_quiet)
    assert res == {"helpx.txt": ph.PATCHED, "conceptsx.txt": ph.PATCHED,
                   "smac_mod\\helpx.txt": ph.PATCHED, "smac_mod\\conceptsx.txt": ph.PATCHED}
    for d in (g, g / "smac_mod"):
        for name, spec in ph.FILES.items():
            assert (d / name).read_bytes() == ph.patch_bytes(_synthetic(spec, b"\r\n"), spec)
    assert not list(g.rglob("*.longevity.bak")), "no backup is written: undo is the exact inverse"
    # a second run changes nothing and says so
    before = {p: p.read_bytes() for p in g.rglob("*.txt")}
    assert set(ph.patch_folder(g, say=_quiet).values()) == {ph.CURRENT}
    assert {p: p.read_bytes() for p in g.rglob("*.txt")} == before


def test_patch_folder_without_smac_mod_patches_the_top_level_only(tmp_path) -> None:
    g = _game_folder(tmp_path, smac_mod=False)
    assert set(ph.patch_folder(g, say=_quiet)) == {"helpx.txt", "conceptsx.txt"}


def test_patch_folder_skips_a_missing_file_and_an_empty_folder(tmp_path) -> None:
    g = _game_folder(tmp_path, smac_mod=False)
    (g / "conceptsx.txt").unlink()
    assert ph.patch_folder(g, say=_quiet) == {"helpx.txt": ph.PATCHED}
    empty = tmp_path / "empty"
    empty.mkdir()
    assert ph.patch_folder(empty, say=_quiet) == {}


def test_a_foreign_file_is_left_alone_and_reported_not_raised(tmp_path) -> None:
    """Another mod's helpx.txt (a stock block missing) must never fail an install: FOREIGN, bytes untouched."""
    g = _game_folder(tmp_path, smac_mod=False)
    foreign = (g / "helpx.txt").read_bytes().replace(b"#ABILDESC2", b"#ABILDESC2X")
    (g / "helpx.txt").write_bytes(foreign)
    lines = []
    res = ph.patch_folder(g, say=lines.append)
    assert res["helpx.txt"] == ph.FOREIGN and res["conceptsx.txt"] == ph.PATCHED
    assert (g / "helpx.txt").read_bytes() == foreign
    assert not ph.backup_of(g / "helpx.txt").exists(), "no backup of a file we did not touch"
    assert any("left alone" in ln for ln in lines)


@pytest.mark.parametrize("name", sorted(ph.FILES))
@pytest.mark.parametrize("nl", [b"\r\n", b"\n"], ids=["crlf", "lf"])
def test_round_trip_in_both_folders(tmp_path, name: str, nl: bytes) -> None:
    g = _game_folder(tmp_path, nl=nl)
    pristine = {p: p.read_bytes() for p in g.rglob(name)}
    assert len(pristine) == 2
    assert set(ph.patch_folder(g, say=_quiet).values()) == {ph.PATCHED}
    for p, data in pristine.items():
        assert p.read_bytes() == ph.patch_bytes(data, ph.FILES[name])
    res = ph.restore_folder(g, say=_quiet)
    assert set(res.values()) == {ph.RESTORED}
    assert {p: p.read_bytes() for p in g.rglob(name)} == pristine
    assert not list(g.rglob("*.longevity.bak"))


def test_restore_folder_puts_the_originals_back(tmp_path) -> None:
    g = _game_folder(tmp_path)
    pristine = {p: p.read_bytes() for p in g.rglob("*.txt")}
    ph.patch_folder(g, say=_quiet)
    res = ph.restore_folder(g, say=_quiet)
    assert set(res.values()) == {ph.RESTORED} and len(res) == 4
    assert {p: p.read_bytes() for p in g.rglob("*.txt")} == pristine
    assert not list(g.rglob("*.longevity.bak"))
    # a second restore finds nothing of ours
    assert set(ph.restore_folder(g, say=_quiet).values()) == {ph.UNPATCHED}


def test_restore_folder_never_touches_a_file_that_is_not_ours(tmp_path) -> None:
    g = _game_folder(tmp_path, smac_mod=False)
    foreign = b"; someone else's helpx\r\n" + (g / "helpx.txt").read_bytes()
    (g / "helpx.txt").write_bytes(foreign)
    res = ph.restore_folder(g, say=_quiet)
    assert res["helpx.txt"] == ph.UNPATCHED
    assert (g / "helpx.txt").read_bytes() == foreign


def test_restore_folder_quiet_statuses_are_not_said(tmp_path) -> None:
    g = _game_folder(tmp_path, smac_mod=False)
    ph.patch_folder(g, say=_quiet)
    (g / "conceptsx.txt").write_bytes(_synthetic(ph.FILES["conceptsx.txt"], b"\r\n"))
    lines = []
    assert ph.restore_folder(g, say=lines.append, quiet=(ph.UNPATCHED,)) == \
        {"helpx.txt": ph.RESTORED, "conceptsx.txt": ph.UNPATCHED}
    assert len(lines) == 1 and lines[0].startswith("restored ")


# ---------------------------------------------------------------- whatever happened to the file in between

@pytest.mark.parametrize("nl", [b"\r\n", b"\n"], ids=["crlf", "lf"])
def test_a_thinker_update_between_runs_is_what_uninstall_gives_back(tmp_path, nl: bytes) -> None:
    """Stock A patched; Thinker (or GOG) replaces the file with a newer stock B carrying the same blocks; the next
    install/update run patches B; --uninstall gives back B exactly -- never A, and never an old backup of A."""
    g = _game_folder(tmp_path, nl=nl)
    ph.patch_folder(g, say=_quiet)
    newer = {}
    for d in (g, g / "smac_mod"):
        for name, spec in ph.FILES.items():
            p = d / name
            ph.backup_of(p).write_bytes(_synthetic(spec, nl))   # what an earlier version kept: a copy of A
            newer[p] = _newer_stock(spec, nl)
            p.write_bytes(newer[p])
    assert set(ph.patch_folder(g, say=_quiet).values()) == {ph.PATCHED}
    for p, data in newer.items():
        assert p.read_bytes() == ph.patch_bytes(data, ph.FILES[p.name])
    assert not list(g.rglob("*.longevity.bak")), "the copy of A must not survive for a later run to trust"
    assert set(ph.restore_folder(g, say=_quiet).values()) == {ph.RESTORED}
    assert {p: p.read_bytes() for p in newer} == newer


def test_a_file_replaced_after_the_last_run_is_left_untouched(tmp_path) -> None:
    """A patched (an earlier version kept A's backup), B replaced it after the last run, then --uninstall: B stays
    byte-for-byte, and the stale backup of A is gone."""
    g = _game_folder(tmp_path)
    ph.patch_folder(g, say=_quiet)
    newer = {}
    for d in (g, g / "smac_mod"):
        for name, spec in ph.FILES.items():
            p = d / name
            ph.backup_of(p).write_bytes(_synthetic(spec, b"\r\n"))
            newer[p] = _newer_stock(spec, b"\r\n")
            p.write_bytes(newer[p])
    assert set(ph.restore_folder(g, say=_quiet).values()) == {ph.UNPATCHED}
    assert {p: p.read_bytes() for p in newer} == newer
    assert not list(g.rglob("*.longevity.bak"))


def test_an_existing_install_loses_its_backup_on_the_next_run(tmp_path) -> None:
    """An install by an earlier version: our current text plus a .longevity.bak. The next run reads CURRENT and
    deletes the backup (the file is undone exactly without it); --check deletes nothing."""
    g = _game_folder(tmp_path, smac_mod=False)
    ph.patch_folder(g, say=_quiet)
    for name, spec in ph.FILES.items():
        ph.backup_of(g / name).write_bytes(_synthetic(spec, b"\r\n"))
    assert set(ph.patch_folder(g, check=True, say=_quiet).values()) == {ph.CURRENT}
    assert len(list(g.glob("*.longevity.bak"))) == 2
    assert set(ph.patch_folder(g, say=_quiet).values()) == {ph.CURRENT}
    assert not list(g.glob("*.longevity.bak"))


def test_a_stale_backup_beside_a_foreign_file_is_removed(tmp_path) -> None:
    g = _game_folder(tmp_path, smac_mod=False)
    foreign = b"; a translation\r\n#ABILDESC2\r\nother words\r\n"
    (g / "helpx.txt").write_bytes(foreign)
    ph.backup_of(g / "helpx.txt").write_bytes(b"stale")
    assert ph.patch_folder(g, say=_quiet)["helpx.txt"] == ph.FOREIGN
    assert (g / "helpx.txt").read_bytes() == foreign
    assert not ph.backup_of(g / "helpx.txt").exists()


def test_a_backup_that_cannot_be_deleted_never_fails_the_text(tmp_path) -> None:
    """An earlier version's backup that cannot be removed (here a folder by that name; a read-only file is the same
    on Windows) is said, never a FAILED text file: the file is patched / current / restored, and a run after the
    restore is quiet (audit 2026-11-10: every run reported FAILED, the uninstall asked to be re-run forever)."""
    g = _game_folder(tmp_path, smac_mod=False)
    pristine = (g / "helpx.txt").read_bytes()
    stuck = ph.backup_of(g / "helpx.txt")
    stuck.mkdir()
    (stuck / "x").write_bytes(b"")
    lines = []
    assert ph.patch_folder(g, say=lines.append)["helpx.txt"] == ph.PATCHED
    assert (g / "helpx.txt").read_bytes() == ph.patch_bytes(pristine, ph.FILES["helpx.txt"])
    assert ph.patch_folder(g, say=lines.append)["helpx.txt"] == ph.CURRENT
    assert ph.restore_folder(g, say=lines.append)["helpx.txt"] == ph.RESTORED
    assert (g / "helpx.txt").read_bytes() == pristine
    assert ph.restore_folder(g, say=lines.append)["helpx.txt"] == ph.UNPATCHED
    assert all("could not remove" in ln for ln in lines if "helpx" in ln), lines


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")
def test_a_dangling_junction_backup_is_removed(tmp_path) -> None:
    """A .bak that is a junction whose target is gone: exists() is False for it, so only lexists() finds it."""
    import _winapi
    g = _game_folder(tmp_path, smac_mod=False)
    target = tmp_path / "gone"
    target.mkdir()
    link = ph.backup_of(g / "helpx.txt")
    _winapi.CreateJunction(str(target), str(link))
    target.rmdir()
    assert not link.exists()
    assert ph.patch_folder(g, say=_quiet)["helpx.txt"] == ph.PATCHED
    assert not os.path.lexists(link)


def test_restore_never_reads_the_backup(tmp_path) -> None:
    """A backup that says something else entirely is never written over the file: our text comes out exactly."""
    g = _game_folder(tmp_path, smac_mod=False)
    pristine = (g / "helpx.txt").read_bytes()
    ph.patch_folder(g, say=_quiet)
    ph.backup_of(g / "helpx.txt").write_bytes(b"an old backup that must never come back")
    assert ph.restore_folder(g, say=_quiet)["helpx.txt"] == ph.RESTORED
    assert (g / "helpx.txt").read_bytes() == pristine
    assert not ph.backup_of(g / "helpx.txt").exists()


def _every_old_mark() -> list:
    return [(name, m) for name in sorted(ph.FILES) for m in ph.FILES[name]["old_marks"]]


@pytest.mark.parametrize("name,mark", _every_old_mark(), ids=lambda v: v.decode().lstrip("; ") if isinstance(v, bytes) else v)
def test_every_older_revision(tmp_path, name: str, mark: bytes) -> None:
    """A revision on record is taken back out exactly, both by --uninstall and by the re-patch of an update run. One
    whose text is not on record (never committed, never shipped) is left alone by both, its backup kept beside it."""
    spec = ph.FILES[name]
    g = tmp_path / "g"
    g.mkdir()
    p = g / name
    pristine = _newer_stock(spec, b"\r\n")
    if mark in spec["revisions"]:
        old = ph._apply(pristine, spec["stock"], spec["revisions"][mark], mark)
        assert old != ph.patch_bytes(pristine, spec)
        p.write_bytes(old)
        ph.backup_of(p).write_bytes(b"stale")
        assert ph.patch_folder(g, say=_quiet) == {name: ph.PATCHED}
        assert p.read_bytes() == ph.patch_bytes(pristine, spec)
        assert not ph.backup_of(p).exists()
        p.write_bytes(old)
        assert ph.restore_folder(g, say=_quiet) == {name: ph.RESTORED}
        assert p.read_bytes() == pristine
    else:
        old = mark + b"\r\n" + pristine.replace(b"updated words", b"text we no longer know", 1)
        p.write_bytes(old)
        ph.backup_of(p).write_bytes(b"stale")
        lines = []
        assert ph.patch_folder(g, say=lines.append) == {name: ph.OLD_REVISION}
        assert ph.restore_folder(g, say=lines.append) == {name: ph.OLD_REVISION}
        assert p.read_bytes() == old and ph.backup_of(p).read_bytes() == b"stale"
        assert all("left alone" in ln and "never put back automatically" in ln for ln in lines), lines


EDITS = ["block-reworded", "block-deleted", "block-doubled", "marker-moved-down", "marker-line-ending",
         "marker-trailing-space", "marker-trailing-tab", "marker-leading-space", "marker-removed",
         "marker-removed-text-reworded"]


def _edited(spec: dict, patched: bytes, edit: str) -> bytes:
    nl = b"\r\n"
    tag = next(iter(spec["new"]))
    blk = ph._block(tag, spec["new"][tag], nl)
    last = spec["new"][tag][-1]
    return {
        "block-reworded": lambda: patched.replace(last, last + b" (a player's note)"),
        "block-deleted": lambda: patched.replace(blk, b""),
        "block-doubled": lambda: patched + blk,
        "marker-moved-down": lambda: b"; my notes" + nl + patched,
        "marker-line-ending": lambda: patched.replace(spec["mark"] + nl, spec["mark"] + b"\n", 1),
        # audit 2026-11-10: a padded marker read as "not ours", so patch doubled conceptsx's paragraph and both
        # runs deleted the backup; a marker removed with our text left behind lost the backup the same way
        "marker-trailing-space": lambda: patched.replace(spec["mark"] + nl, spec["mark"] + b" " + nl, 1),
        "marker-trailing-tab": lambda: patched.replace(spec["mark"] + nl, spec["mark"] + b"\t" + nl, 1),
        "marker-leading-space": lambda: b" " + patched,
        "marker-removed": lambda: patched[len(spec["mark"] + nl):],
        # audit 2026-11-10 (round 3): the marker gone AND the end of our text reworded read as stock, so the patch
        # added our paragraph a second time
        "marker-removed-text-reworded": lambda: patched[len(spec["mark"] + nl):].replace(last, last + b" (note)"),
    }[edit]()


@pytest.mark.parametrize("name", sorted(ph.FILES))
@pytest.mark.parametrize("edit", EDITS)
def test_an_edited_file_is_refused_by_patch_and_restore(tmp_path, name: str, edit: str) -> None:
    """Our marker, but a block of ours changed, missing or doubled: neither run writes a byte (the text around it
    could be newer than anything we know); both report EDITED (UNMARKED when the marker is gone); an earlier version's
    backup stays as the manual way back."""
    spec = ph.FILES[name]
    g = tmp_path / "g"
    g.mkdir()
    p = g / name
    edited = _edited(spec, ph.patch_bytes(_synthetic(spec, b"\r\n"), spec), edit)
    p.write_bytes(edited)
    ph.backup_of(p).write_bytes(b"kept")
    lines = []
    # the marker gone: it cannot be told from someone else's file quoting our wording (audit round 6)
    status = ph.UNMARKED if edit.startswith("marker-removed") else ph.EDITED
    assert ph.patch_folder(g, say=lines.append) == {name: status}
    assert ph.restore_folder(g, say=lines.append) == {name: status}
    assert p.read_bytes() == edited and ph.backup_of(p).read_bytes() == b"kept"
    assert len(lines) == 2 and all("left alone" in ln for ln in lines), lines
    with pytest.raises(ph.Refused):
        ph.unpatch_bytes(edited, spec)


# ---------------------------------------------------------------- the real files (read only)

def test_the_thinker_workspace_copies_patch_cleanly() -> None:
    """Thinker 5.5's smac_mod\\ files (its SMAC-only mode) keep the stock blocks: the same patch applies."""
    folder = pathlib.Path(r"D:\SmacxThinker\game\smac_mod")
    if not folder.is_dir():
        pytest.skip("Thinker workspace not present")
    for name, spec in ph.FILES.items():
        data = (folder / name).read_bytes()
        if ph.marker_of(data, spec) is not None:
            data = ph.unpatch_bytes(data, spec)
        # the stock text reads as stock, never as "ours, edited" (Thinker continues entries the way ours does)
        with pytest.raises(ph.Refused) as r:
            ph.unpatch_bytes(data, spec)
        assert r.value.status == ph.UNPATCHED, f"{name}: Thinker's stock text classified {r.value.status}"
        assert ph.unpatch_bytes(ph.patch_bytes(data, spec), spec) == data


@pytest.mark.parametrize("name", sorted(ph.FILES))
def test_game_file(name: str) -> None:
    """Against the install, read only: a patched live file inverts exactly; the pristine text patches cleanly."""
    game = config.game_dir(required=False)
    if game is None or not (game / name).exists():
        pytest.skip(f"{name} not found in the game folder")
    live = (game / name).read_bytes()
    spec = ph.FILES[name]
    if ph.marker_of(live, spec) == spec["mark"]:
        pristine = ph.unpatch_bytes(live, spec)
        assert ph.patch_bytes(pristine, spec) == live, f"{name}: the live file is not patch_bytes(its inverse)"
    else:
        pristine = live
    out = ph.patch_bytes(pristine, spec)
    assert out.startswith(spec["mark"])
    assert pristine.count(b"\r\n") > 0 and out.count(b"\r\n") == out.count(b"\n"), "the game files are CRLF"
