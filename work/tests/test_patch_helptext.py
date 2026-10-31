"""patch_helptext.py: the Datalinks text patches (helpx.txt cloaking rules, conceptsx.txt Waypoints paragraph).

Pure checks on synthetic files (no game install needed) plus, when the game folder is present, the real
pristine backups / live files: every stock block must be found exactly once in the pristine file, the
patched result must start with the version marker, keep the file's line ending, and contain each new block
exactly once.
"""
from __future__ import annotations

import hashlib
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
#: when this fails, bump the file's MARK, append the previous one to its OLD_MARKS and record the new hash here.
TEXT_OF_MARK = {
    b"; longevity-helptext v12": "e16bd4ed66b4",
    b"; longevity-concepts v2": "89446025592c",
}


@pytest.mark.parametrize("name", sorted(ph.FILES))
def test_marker_matches_the_text(name: str) -> None:
    spec = ph.FILES[name]
    h = hashlib.sha1(b"\n".join(b"\n".join(v) for v in spec["new"].values())).hexdigest()[:12]
    assert spec["mark"] in TEXT_OF_MARK, f"{name}: new marker {spec['mark']!r} -- record its text hash {h} in TEXT_OF_MARK"
    assert TEXT_OF_MARK[spec["mark"]] == h, \
        f"{name}: the text changed under marker {spec['mark']!r} -- bump the marker (and OLD_MARKS), then record {h}"
    assert spec["mark"] not in spec["old_marks"]
    for old in spec["old_marks"]:
        assert old < spec["mark"] or len(old) < len(spec["mark"]), f"{name}: old marker {old!r} not older than {spec['mark']!r}"


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
            assert (d / name).read_bytes().startswith(spec["mark"])
            assert ph.backup_of(d / name).read_bytes() == _synthetic(spec, b"\r\n"), "the backup is the pristine file"
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


def test_an_older_revision_is_rebuilt_from_its_backup(tmp_path) -> None:
    g = _game_folder(tmp_path, smac_mod=False)
    spec = ph.FILES["helpx.txt"]
    ph.patch_folder(g, say=_quiet)
    live = g / "helpx.txt"
    # simulate a file patched by the previous release: its marker is an old one, the text whatever it was
    old = spec["old_marks"][-1]
    live.write_bytes(old + b"\r\n" + b"stale text\r\n")
    res = ph.patch_folder(g, say=_quiet)
    assert res["helpx.txt"] == ph.PATCHED
    assert live.read_bytes() == ph.patch_bytes(_synthetic(spec, b"\r\n"), spec)
    # ... but an old revision WITHOUT a backup cannot be rebuilt: left alone, reported
    ph.backup_of(live).unlink()
    live.write_bytes(old + b"\r\n" + b"stale text\r\n")
    assert ph.patch_folder(g, say=_quiet)["helpx.txt"] == ph.FOREIGN
    assert live.read_bytes().startswith(old)


def test_restore_folder_puts_the_originals_back_and_removes_the_backups(tmp_path) -> None:
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
    ph.backup_of(g / "helpx.txt").write_bytes(b"a stray backup")
    res = ph.restore_folder(g, say=_quiet)
    assert res["helpx.txt"] == ph.UNPATCHED
    assert (g / "helpx.txt").read_bytes() == foreign
    # ours but without its backup: left alone, reported
    ph.patch_folder(g, say=_quiet)
    ph.backup_of(g / "conceptsx.txt").unlink()
    res = ph.restore_folder(g, say=_quiet)
    assert res["conceptsx.txt"] == ph.NO_BACKUP
    assert (g / "conceptsx.txt").read_bytes().startswith(ph.FILES["conceptsx.txt"]["mark"])


def test_the_thinker_workspace_copies_patch_cleanly() -> None:
    """Thinker 5.5's smac_mod\\ files (its SMAC-only mode) keep the stock blocks: the same patch applies."""
    folder = pathlib.Path(r"D:\SmacxThinker\game\smac_mod")
    if not folder.is_dir():
        pytest.skip("Thinker workspace not present")
    for name, spec in ph.FILES.items():
        data = (folder / name).read_bytes()
        if data.startswith(spec["mark"]):
            data = ph.backup_of(folder / name).read_bytes()
        assert ph.patch_bytes(data, spec).startswith(spec["mark"])


@pytest.mark.parametrize("name", sorted(ph.FILES))
def test_game_file(name: str) -> None:
    """Against the install: the pristine backup (or the live file when still unpatched) patches cleanly."""
    game = config.game_dir(required=False)
    if game is None or not (game / name).exists():
        pytest.skip(f"{name} not found in the game folder")
    live = (game / name).read_bytes()
    bak = game / f"{name}.longevity.bak"
    spec = ph.FILES[name]
    if live.startswith(spec["mark"]):
        assert bak.exists(), f"{name} is patched but has no backup"
        pristine = bak.read_bytes()
        assert ph.patch_bytes(pristine, spec) == live, f"{name}: the live file is not patch_bytes(backup)"
    else:
        pristine = live
    out = ph.patch_bytes(pristine, spec)
    assert out.startswith(spec["mark"])
    assert pristine.count(b"\r\n") > 0 and out.count(b"\r\n") == out.count(b"\n"), "the game files are CRLF"
