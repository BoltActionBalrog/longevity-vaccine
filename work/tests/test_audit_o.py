"""Audit-o (2026-11-17, an antagonistic audit of 69abb2b): the fixes triaged for the user. Each test written to fail
first.

1. PROVENANCE.txt counts: adoption needs the release's own (compiled for the version this installer ships, or the
   local pack's file); a kept pack whose release carries one needs it present and right, else it is repaired -- a
   local pack by re-placing that one file. A release known to carry none (the 1.0.0 Cinematics) asks for none.
2. A pack's pack-manifest.json, and PROVENANCE.txt, are placed LAST (archive and local copy alike): a stopped copy
   never leaves the new manifest beside old files.
3. release.py refuses a pack archive whose pack-manifest.json or PROVENANCE.txt is not the compiled one.
4. The list hint shows only when every row marked "already installed" is locked."""
from __future__ import annotations

import hashlib
import inspect
import sys
import types
import zipfile
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import install as inst              # noqa: E402
import receipt as rc                # noqa: E402
import release as rel               # noqa: E402
from test_audit_n import PROV, REPO, _catalogue, _game, _into_game, _src  # noqa: E402
from test_setup_pack_rerun import CLIPS, _World, _keys, _listed, _pack, _remote  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")

SHA_PROV = hashlib.sha256(PROV).hexdigest()
HINT = "Modules that are already installed stay ticked."


# ---------------------------------------------------------------- 1. PROVENANCE.txt

def _kept_remote(tmp_path, *, provenance: bytes = PROV):
    """An installed HD Cinematics recorded at the version on offer, whose release is known to carry PROVENANCE."""
    game = _game(tmp_path)
    root = _pack(game, "movies-hd", CLIPS)
    if provenance is not None:
        (root / "PROVENANCE.txt").write_bytes(provenance)
    return game, root


@pytest.mark.parametrize("case,expect", [("right", "keep"), ("stale", "repair"), ("missing", "repair")])
def test_a_kept_pack_needs_its_release_provenance(tmp_path, case, expect):
    game, root = _kept_remote(tmp_path, provenance={"right": PROV, "stale": b"provisional", "missing": None}[case])
    assert inst.pack_action(game, "movies-hd", "2.0.0", "2.0.0", None, SHA_PROV) == expect


def test_a_release_without_provenance_asks_for_none(tmp_path):
    """The released 1.0.0 Cinematics archive has no PROVENANCE.txt: requiring one would re-download it every run."""
    game, _root = _kept_remote(tmp_path, provenance=None)
    assert inst.pack_action(game, "movies-hd", "1.0.0", "1.0.0", None, None) == "keep"


def test_the_catalogue_knows_each_releases_provenance(tmp_path, monkeypatch):
    v = inst.ver.MODULE_VERSIONS["portraits-hd"]
    assert inst.release_provenance_sha256({"source": "manifest", "version": v}, "portraits-hd") \
        == inst.ver.PACK_PROVENANCE_SHA256["portraits-hd"]
    assert inst.release_provenance_sha256({"source": "manifest", "version": "0.9.0"}, "portraits-hd") is None
    game = _game(tmp_path)
    cat = _catalogue(game, tmp_path, monkeypatch, movies=_src(tmp_path, "movies-hd"))
    assert cat["movies-hd"]["release_provenance"] == SHA_PROV


def test_a_local_pack_with_a_stale_provenance_gets_just_that_file(tmp_path, monkeypatch, capsys):
    w = _World(tmp_path, monkeypatch)
    inst._load_modules()
    src = _src(tmp_path, "movies-hd")
    root = _into_game(w.game, src, "movies-hd")
    (root / "PROVENANCE.txt").write_bytes(b"the provisional licence")
    v = inst.ver.module_version("movies-hd")
    rc.write(w.game, modules={"movies-hd": {"version": v}})
    placed = []
    real = inst._copy_into_place
    monkeypatch.setattr(inst, "_copy_into_place", lambda s, d: placed.append(Path(d).name) or real(s, d))
    cat = _catalogue(w.game, tmp_path, monkeypatch, movies=src)
    got, status, how = w.place(["movies-hd"], cat, {"movies-hd": v})
    assert how["movies-hd"] == "repair" and status["movies-hd"] == "ok" and placed == ["PROVENANCE.txt"]
    assert w.copies == [] and (root / "PROVENANCE.txt").read_bytes() == PROV and got == {"movies-hd": {"version": v}}
    assert inst.pack_summary_status("ok", "repair") == "repaired"


def test_a_downloaded_pack_with_a_stale_provenance_is_repaired_by_its_archive(tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch)
    root = _pack(w.game, "movies-hd", CLIPS)
    (root / "PROVENANCE.txt").write_bytes(b"provisional")
    cat = {"movies-hd": _remote("2.0.0", release_provenance=SHA_PROV)}
    _got, _status, how = w.place(["movies-hd"], cat, {"movies-hd": "2.0.0"})
    assert how["movies-hd"] == "repair" and w.downloads == [["movies-hd"]]


@pytest.mark.parametrize("name", ["movies-hd", "portraits-hd"])
def test_the_compiled_provenance_hash_is_the_pack_this_installer_ships(name, need_local):
    p = need_local(REPO / "dist" / name / "PROVENANCE.txt", f"the {name} pack's PROVENANCE.txt")
    assert inst.ver.PACK_PROVENANCE_SHA256[name] == hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------- 2. the manifest last

def _zip(path: Path, members: list) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members:
            z.writestr(name, data)
    return path


def test_an_archive_stopped_part_way_never_leaves_its_new_manifest(tmp_path, monkeypatch):
    """The manifest sits early in the archive (entry 36 of 62 in the real one); a stop after it used to leave the new
    manifest beside old clips."""
    game = _game(tmp_path)
    archive = _zip(tmp_path / "m.zip", [("movies/hd/pack-manifest.json", b"{}"), ("movies/hd/PROVENANCE.txt", PROV),
                                         ("movies/hd/a.mp4", b"a" * 10), ("movies/hd/b.mp4", b"b" * 10)])
    real = inst.shutil.copyfileobj

    def stop_at_b(src, dst, *a):
        if str(getattr(dst, "name", "")).endswith(f"b.mp4.tmp-{inst.os.getpid()}"):
            raise KeyboardInterrupt
        return real(src, dst, *a)
    monkeypatch.setattr(inst.shutil, "copyfileobj", stop_at_b)
    with pytest.raises(KeyboardInterrupt):
        inst.install_modules(game, {"movies-hd": archive}, {"movies-hd": "2.0.0"})
    root = game / "movies" / "hd"
    assert not (root / "pack-manifest.json").exists() and not (root / "PROVENANCE.txt").exists()


def test_an_archive_lands_its_manifest_after_everything_else(tmp_path, monkeypatch):
    game = _game(tmp_path)
    archive = _zip(tmp_path / "m.zip", [("movies/hd/pack-manifest.json", b"{}"), ("movies/hd/PROVENANCE.txt", PROV),
                                         ("movies/hd/a.mp4", b"a"), ("movies/hd/z.mp4", b"z")])
    order = []
    real = Path.replace
    monkeypatch.setattr(Path, "replace", lambda self, dest: order.append(Path(dest).name) or real(self, dest))
    inst.install_modules(game, {"movies-hd": archive}, {"movies-hd": "2.0.0"})
    assert order == ["a.mp4", "z.mp4", "PROVENANCE.txt", "pack-manifest.json"]


@pytest.mark.parametrize("name", ["movies-hd", "portraits-hd"])
def test_a_local_copy_places_its_manifest_last(tmp_path, monkeypatch, name):
    game = _game(tmp_path)
    src = _src(tmp_path, name)
    order = []
    real = inst._copy_into_place
    monkeypatch.setattr(inst, "_copy_into_place", lambda s, d: order.append(Path(d).name) or real(s, d))
    copy = inst.install_movie_pack if name == "movies-hd" else inst.install_portrait_pack
    assert copy(game, src) is True
    assert order[-2:] == ["PROVENANCE.txt", "pack-manifest.json"] and len(order) == len(set(order))


# ---------------------------------------------------------------- 3. release time

def _pack_zip(tmp_path, name: str, manifest: bytes, provenance) -> Path:
    root = inst.MODULE_ROOTS[name][0]
    members = [(f"{root}/x.bin", b"x"), (f"{root}/pack-manifest.json", manifest)]
    if provenance is not None:
        members.append((f"{root}/PROVENANCE.txt", provenance))
    return _zip(tmp_path / f"{name}.zip", members)


@pytest.mark.parametrize("name", ["movies-hd", "portraits-hd"])
def test_release_refuses_an_archive_that_is_not_the_compiled_pack(tmp_path, monkeypatch, name):
    import version as ver
    monkeypatch.setitem(ver.PACK_MANIFEST_SHA256, name, hashlib.sha256(b"{ok}").hexdigest())
    monkeypatch.setitem(ver.PACK_PROVENANCE_SHA256, name, SHA_PROV)
    rel._check_pack_archive_compiled(_pack_zip(tmp_path, name, b"{ok}", PROV), name)        # the shipped one
    for bad in ((b"{re-hashed}", PROV), (b"{ok}", b"another licence"), (b"{ok}", None)):
        with pytest.raises(SystemExit, match="REFUSING"):
            rel._check_pack_archive_compiled(_pack_zip(tmp_path, name, *bad), name)


def test_release_checks_both_a_built_and_a_reused_pack_archive():
    src = inspect.getsource(rel.main)
    assert src.count("_check_pack_archive_compiled(dest, name)") == 2
    built = src.index("write_zip(entries, dest)")
    reused = src.index('how = "reused"')
    first, second = (src.index("_check_pack_archive_compiled(dest, name)"),
                     src.rindex("_check_pack_archive_compiled(dest, name)"))
    assert built < first < reused < second


# ---------------------------------------------------------------- 4. the hint never contradicts a row

def _picker_out(monkeypatch, capsys, catalogue) -> str:
    _keys(monkeypatch, "down", "down", "enter")
    capsys.readouterr()
    inst._tick_picker(list(catalogue), catalogue, {n: True for n in catalogue})
    return capsys.readouterr().out


def test_no_hint_when_an_already_installed_row_can_be_unticked(monkeypatch, capsys):
    """C1: a 1.0.0 Cinematics left in the folder (on disk, not locked) beside the release portraits (locked)."""
    cat = {"movies-hd": _listed(on_disk=True, locked=False), "portraits-hd": _listed(on_disk=True, locked=True)}
    assert HINT not in _picker_out(monkeypatch, capsys, cat)


def test_the_hint_when_every_already_installed_row_is_locked(monkeypatch, capsys):
    cat = {"movies-hd": _listed(on_disk=True, locked=True), "portraits-hd": _listed(on_disk=True, locked=True)}
    assert _picker_out(monkeypatch, capsys, cat).count(HINT) == 1
