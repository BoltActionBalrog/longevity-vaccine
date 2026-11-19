"""Audit-n (2026-11-17, an antagonistic audit of ff582f5): the four fixes the user approved. Each test written to fail
first.

1. A local (checkout) pack copy killed mid-file left a full-size torn file (CopyFile2 sizes the destination first),
   which the next run KEPT. Now copied to a private temp name beside it and renamed into place.
2. The lock forced a fetch the player could decline before (a 1.0.0 uninstall left the packs, with no receipt entry).
   Now (a) only a pack this run will KEEP is locked; (b) a pack whose pack-manifest.json is byte-identical to the
   offered release's, every listed file present at its size, is ADOPTED: kept, and the offered version recorded.
3. A deeply nested pack-manifest.json raised RecursionError through setup and uninstall alike. Now any failure to
   parse it means "not proven".
4. Tests through the real setup path (_install_rest) that fail when it forgets the receipt's versions or drops a kept
   pack from the decline bookkeeping."""
from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import install as inst              # noqa: E402
import installer_exit as ix         # noqa: E402
import receipt as rc                # noqa: E402
from test_setup_pack_rerun import CLIPS, PORTRAITS, _World, _keys, _pack  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")

REPO = Path(__file__).resolve().parents[2]
FILES = {"movies-hd": CLIPS, "portraits-hd": PORTRAITS}


def _src(tmp_path: Path, name: str, files: dict = None) -> Path:
    """A local (checkout) pack folder, with its pack-manifest.json, as dist\\<pack> holds it."""
    files = files or FILES[name]
    src = tmp_path / f"src-{name}"
    src.mkdir()
    for n, data in files.items():
        (src / n).write_bytes(data)
    key = "clips" if name == "movies-hd" else "files"
    doc = {"schema": 1, "pack": name, key: [{"name": n, "size": len(d), "sha256": hashlib.sha256(d).hexdigest()}
                                            for n, d in files.items()]}
    (src / "pack-manifest.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    (src / "PROVENANCE.txt").write_bytes(PROV)        # every released pack carries its credit (audit-o)
    return src


PROV = b"Credit and licence.\r\n"


def _into_game(game: Path, src: Path, name: str) -> Path:
    """The local pack's files and its very pack-manifest.json bytes in the game folder (what a 1.0.0 uninstall left)."""
    root = game / inst.MODULE_ROOTS[name][0]
    root.mkdir(parents=True, exist_ok=True)
    for p in src.iterdir():
        (root / p.name).write_bytes(p.read_bytes())
    return root


def _catalogue(game: Path, tmp_path: Path, monkeypatch, **srcs) -> dict:
    """module_catalogue over local packs only (offline, no console: no manifest is fetched)."""
    monkeypatch.setattr(ix, "has_console", lambda: False)
    monkeypatch.setattr(inst, "_thinker_off_pin", lambda g: False)
    args = types.SimpleNamespace(pack=str(srcs.get("movies", tmp_path / "none")),
                                 portrait_pack=str(srcs.get("portraits", tmp_path / "none")),
                                 ai="ask", modules=None, no_prompt=False, manifest=None, offline=True)
    return inst.module_catalogue(game, args)[0]


def _game(tmp_path) -> Path:
    g = tmp_path / "game"
    g.mkdir()
    inst._load_modules()
    return g


# ---------------------------------------------------------------- 1. a local copy killed mid-file

@pytest.mark.parametrize("name", ["movies-hd", "portraits-hd"])
def test_a_local_copy_killed_mid_file_never_leaves_a_full_size_file(tmp_path, monkeypatch, name):
    game = _game(tmp_path)
    src = _src(tmp_path, name)
    first = next(iter(FILES[name]))

    def torn(s, d, *a, **k):
        Path(d).write_bytes(b"\0" * Path(s).stat().st_size)     # CopyFile2 (Python 3.12): the full size first
        raise KeyboardInterrupt                                  # ... then the process is stopped
    monkeypatch.setattr(inst.shutil, "copy2", torn)
    copy = inst.install_movie_pack if name == "movies-hd" else inst.install_portrait_pack
    with pytest.raises(KeyboardInterrupt):
        copy(game, src)
    root = game / inst.MODULE_ROOTS[name][0]
    assert not (root / first).exists()
    assert inst.pack_action(game, name, "2.0.0", "2.0.0") != "keep"


@pytest.mark.parametrize("name", ["movies-hd", "portraits-hd"])
def test_a_local_copy_still_lands_every_file(tmp_path, name):
    game = _game(tmp_path)
    src = _src(tmp_path, name)
    copy = inst.install_movie_pack if name == "movies-hd" else inst.install_portrait_pack
    assert copy(game, src) is True
    root = game / inst.MODULE_ROOTS[name][0]
    assert sorted(p.name for p in root.iterdir()) == sorted([*FILES[name], "pack-manifest.json", "PROVENANCE.txt"])
    assert inst.pack_intact(game, name)


# ---------------------------------------------------------------- 3. a pathological pack-manifest.json

DEEP = '{"clips": ' + "[" * 100000 + "]" * 100000 + "}"


@pytest.mark.parametrize("name", ["movies-hd", "portraits-hd"])
def test_a_pathological_pack_manifest_proves_nothing(tmp_path, name):
    game = _game(tmp_path)
    root = _pack(game, name, FILES[name])
    (root / "pack-manifest.json").write_text(DEEP, encoding="utf-8")
    assert inst._pack_names(root / "pack-manifest.json") is None
    assert inst.pack_action(game, name, "1.0.0", "1.0.0") == "install"
    assert inst.pack_intact(game, name) is False


def test_uninstall_leaves_a_pack_whose_manifest_is_pathological(tmp_path, capsys):
    game = _game(tmp_path)
    root = _pack(game, "movies-hd", CLIPS)
    (root / "pack-manifest.json").write_text(DEEP, encoding="utf-8")
    assert inst.remove_pack(game, "movies-hd") == (0, 0)
    assert "pack-manifest.json could not be read" in capsys.readouterr().out
    assert (root / "angels.mp4").is_file() and inst._PACKS_UNREAD == ["movies-hd"]


# ---------------------------------------------------------------- 2a. only a pack the run will keep is locked

def test_a_pack_left_without_a_receipt_entry_and_not_this_release_is_not_locked(tmp_path, monkeypatch):
    """What a 1.0.0 uninstall left (the packs stayed, the receipt went): not the release on offer, so it may be
    unticked, and unticking it skips it -- no download, no decline."""
    game = _game(tmp_path)
    _pack(game, "movies-hd", {"old.mp4": b"o" * 9})                   # an older release's files and manifest
    cat = _catalogue(game, tmp_path, monkeypatch, movies=_src(tmp_path, "movies-hd"))
    assert cat["movies-hd"]["on_disk"] is True and cat["movies-hd"]["locked"] is False
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _keys(monkeypatch, "enter", "down", "enter")                       # untick it, then Continue
    chosen, turned_down, _ticked = inst.pick_modules(cat, types.SimpleNamespace(modules=None, ai="ask",
                                                                                no_prompt=False), game)
    assert chosen == [] and turned_down == []


@pytest.mark.parametrize("case", ["damaged", "newer-offered"])
def test_a_pack_this_run_would_change_is_not_locked(tmp_path, monkeypatch, case):
    game = _game(tmp_path)
    src = _src(tmp_path, "movies-hd")
    root = _into_game(game, src, "movies-hd")
    rc.write(game, modules={"movies-hd": {"version": "1.0.0" if case == "newer-offered" else "2.0.0"}})
    if case == "damaged":
        (root / "angels.mp4").write_bytes(b"x")
        (src / "pack-manifest.json").write_text("{}", encoding="utf-8")   # not adoptable either
    else:
        (root / "pack-manifest.json").write_text(
            (root / "pack-manifest.json").read_text(encoding="utf-8") + " ", encoding="utf-8")   # the older release's
    cat = _catalogue(game, tmp_path, monkeypatch, movies=src)
    assert cat["movies-hd"]["locked"] is False


def test_a_kept_pack_is_locked(tmp_path, monkeypatch):
    game = _game(tmp_path)
    src = _src(tmp_path, "movies-hd")
    _into_game(game, src, "movies-hd")
    rc.write(game, modules={"movies-hd": {"version": inst.ver.module_version("movies-hd")}})
    assert _catalogue(game, tmp_path, monkeypatch, movies=src)["movies-hd"]["locked"] is True


# ---------------------------------------------------------------- 2b. adopting the release on offer

def test_a_local_pack_left_in_place_is_adopted(tmp_path, monkeypatch, capsys):
    """The folder holds exactly the local pack (its pack-manifest.json byte for byte, every file at its size) but the
    receipt does not know it: kept with no copy, locked, and the offered version recorded."""
    w = _World(tmp_path, monkeypatch)
    game = w.game
    inst._load_modules()
    src = _src(tmp_path, "movies-hd")
    _into_game(game, src, "movies-hd")
    cat = _catalogue(game, tmp_path, monkeypatch, movies=src)
    assert cat["movies-hd"]["locked"] is True
    capsys.readouterr()
    got, status, how = w.place(["movies-hd"], cat, {"movies-hd": inst.ver.UNKNOWN})
    v = inst.ver.module_version("movies-hd")
    assert w.copies == [] and w.downloads == []
    assert how["movies-hd"] == "adopt" and status["movies-hd"] == "ok" and got == {"movies-hd": {"version": v}}
    assert f"  v{v} is already installed; nothing was downloaded." in capsys.readouterr().out
    assert inst.pack_summary_status("ok", "adopt") == "kept"


def test_a_downloaded_release_left_in_place_is_adopted(tmp_path, monkeypatch):
    """The remote form: the offered version is the one this installer ships (version.MODULE_VERSIONS), whose
    pack-manifest.json hash is compiled in (version.PACK_MANIFEST_SHA256)."""
    w = _World(tmp_path, monkeypatch)
    game = w.game
    root = _pack(game, "portraits-hd", PORTRAITS)
    (root / "PROVENANCE.txt").write_bytes(PROV)
    v = inst.ver.module_version("portraits-hd")
    monkeypatch.setitem(inst.ver.PACK_MANIFEST_SHA256, "portraits-hd",
                        hashlib.sha256((root / "pack-manifest.json").read_bytes()).hexdigest())
    monkeypatch.setitem(inst.ver.PACK_PROVENANCE_SHA256, "portraits-hd", hashlib.sha256(PROV).hexdigest())
    entry = {"source": "manifest", "version": v}
    assert inst.release_manifest_sha256(entry, "portraits-hd") == inst.ver.PACK_MANIFEST_SHA256["portraits-hd"]
    assert inst.release_provenance_sha256(entry, "portraits-hd") == hashlib.sha256(PROV).hexdigest()
    cat = {"portraits-hd": {"size": 1, "source": "manifest", "version": v,
                            "release_manifest": inst.ver.PACK_MANIFEST_SHA256["portraits-hd"],
                            "release_provenance": hashlib.sha256(PROV).hexdigest()}}
    got, _status, how = w.place(["portraits-hd"], cat, {})
    assert w.downloads == [] and how["portraits-hd"] == "adopt" and got == {"portraits-hd": {"version": v}}


@pytest.mark.parametrize("trick", ["one-byte-changed", "a-file-the-wrong-size", "a-file-missing",
                                   "another-version-offered", "no-local-manifest", "provenance-differs",
                                   "provenance-missing"])
def test_adoption_cannot_be_talked_into_recording_a_version(tmp_path, monkeypatch, trick):
    """Each trick alone stops adoption. For another offered version the compiled hashes are made to match this very
    folder (audit-o item 5: with a synthetic manifest the version guard was never what refused it), so only the guard
    that the compiled values describe version.MODULE_VERSIONS alone can refuse it."""
    game = _game(tmp_path)
    src = _src(tmp_path, "movies-hd")
    root = _into_game(game, src, "movies-hd")
    if trick == "another-version-offered":
        monkeypatch.setitem(inst.ver.PACK_MANIFEST_SHA256, "movies-hd",
                            hashlib.sha256((root / "pack-manifest.json").read_bytes()).hexdigest())
        monkeypatch.setitem(inst.ver.PACK_PROVENANCE_SHA256, "movies-hd", hashlib.sha256(PROV).hexdigest())
    elif trick == "provenance-differs":
        (root / "PROVENANCE.txt").write_bytes(b"the provisional licence")
    elif trick == "provenance-missing":
        (root / "PROVENANCE.txt").unlink()
    if trick == "one-byte-changed":
        m = root / "pack-manifest.json"
        m.write_bytes(m.read_bytes().replace(b'"schema": 1', b'"schema": 2'))
    elif trick == "a-file-the-wrong-size":
        (root / "intro.mp4").write_bytes(b"b" * 69)
    elif trick == "a-file-missing":
        (root / "intro.mp4").unlink()
    elif trick == "no-local-manifest":
        (src / "pack-manifest.json").unlink()
    cat = _catalogue(game, tmp_path, monkeypatch, movies=src)
    entry = cat["movies-hd"]
    if trick == "another-version-offered":
        entry = {**entry, "source": "manifest", "version": "9.9.9"}
        entry["release_manifest"] = inst.release_manifest_sha256(entry, "movies-hd")
        entry["release_provenance"] = inst.release_provenance_sha256(entry, "movies-hd")
        # each compiled value describes version.MODULE_VERSIONS alone (audit-o M7): neither guard may be dropped
        assert entry["release_manifest"] is None and entry["release_provenance"] is None
        # the same folder offered as the version this installer ships IS adopted: the guard is the only refusal
        shipped = {**entry, "version": inst.ver.MODULE_VERSIONS["movies-hd"]}
        assert inst.pack_action(game, "movies-hd", shipped["version"], inst.ver.UNKNOWN,
                                inst.release_manifest_sha256(shipped, "movies-hd"),
                                inst.release_provenance_sha256(shipped, "movies-hd")) == "adopt"
    assert inst.pack_action(game, "movies-hd", entry["version"], inst.ver.UNKNOWN,
                            entry.get("release_manifest"), entry.get("release_provenance")) == "install"


def test_an_unrecorded_update_already_in_place_is_adopted(tmp_path, monkeypatch):
    """The receipt says an older version, the folder already holds the offered release (an update whose receipt write
    did not happen): adopted, not downloaded again."""
    game = _game(tmp_path)
    src = _src(tmp_path, "movies-hd")
    _into_game(game, src, "movies-hd")
    cat = _catalogue(game, tmp_path, monkeypatch, movies=src)
    e = cat["movies-hd"]
    assert inst.pack_action(game, "movies-hd", e["version"], "1.0.0", e["release_manifest"],
                            e["release_provenance"]) == "adopt"           # adoption needs PROVENANCE too (audit-o)


@pytest.mark.parametrize("name", ["movies-hd", "portraits-hd"])
def test_the_compiled_manifest_hash_is_the_pack_this_installer_ships(name, need_local):
    """version.PACK_MANIFEST_SHA256 is the sha256 of dist\\<pack>\\pack-manifest.json, which release.py puts in the
    archive for version.MODULE_VERSIONS[<pack>]. A pack rebuilt without updating it fails here."""
    p = need_local(REPO / "dist" / name / "pack-manifest.json", f"the {name} pack source")
    assert inst.ver.PACK_MANIFEST_SHA256[name] == hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------- 4. through the real setup path

def _setup_rest(game: Path, monkeypatch, catalogue: dict, chosen: list, ticked_now: list) -> list:
    """install._install_rest as setup calls it, after the patch pass: only the network and the questions around the
    packs are stubbed. Returns the packs it asked to download."""
    downloads = []

    def download(game_dir, args, names, manifest, target_id, target):
        downloads.append(list(names))
        return {n: {"version": catalogue[n]["version"], "files": []} for n in names}, {n: "ok" for n in names}
    monkeypatch.setattr(inst, "install_packs_from_manifest", download)
    monkeypatch.setattr(inst, "check_display_resolution", lambda *a, **k: None)
    monkeypatch.setattr(inst, "check_desktop_shortcut", lambda *a, **k: None)
    monkeypatch.setattr(inst.config, "remember_game_dir", lambda d: True)
    args = types.SimpleNamespace(ai="ask", no_prompt=True, manifest=None, modules=None)
    tstep = types.SimpleNamespace(prep=None, keep=None)
    assert inst._install_rest(game, args, {}, "terranx.exe", None, None, {}, {}, catalogue, ("raw", "sig", {}),
                              chosen, [], ticked_now, tstep) == 0
    return downloads


def _installed_remote(tmp_path) -> tuple:
    """A game folder with the HD Cinematics 1.0.0 installed by an earlier setup: its files, its pack-manifest.json, its
    receipt entry. 1.0.0 is not the version this installer ships, so there is nothing to adopt: only the receipt says
    which release is there."""
    game = _game(tmp_path)
    _pack(game, "movies-hd", CLIPS)
    rc.write(game, modules={"base": {"version": inst.ver.VERSION}, "movies-hd": {"version": "1.0.0"}})
    cat = {"movies-hd": {"size": 1, "source": "manifest", "version": "1.0.0", "on_disk": True, "locked": True,
                         "release_manifest": None}}
    return game, cat


def test_setup_keeps_an_installed_pack_it_reads_from_the_receipt(tmp_path, monkeypatch, capsys):
    game, cat = _installed_remote(tmp_path)
    assert _setup_rest(game, monkeypatch, cat, ["movies-hd"], []) == []
    out = capsys.readouterr().out
    assert "  v1.0.0 is already installed; nothing was downloaded." in out
    assert rc.module_version(rc.read(game), "movies-hd") == "1.0.0"


def test_setup_forgets_an_old_decline_of_a_pack_it_keeps(tmp_path, monkeypatch):
    """A kept pack counts as installed by the run: an earlier "Don't ask me again" on it is forgotten, as for a pack
    the run placed (here with --no-prompt: nothing was ticked in a list)."""
    game, cat = _installed_remote(tmp_path)
    rc.decline(game, inst.NEW_PACK_PREFIX + "movies-hd", rc.DECLINE_ANY)
    assert inst.NEW_PACK_PREFIX + "movies-hd" in rc.declined(game)
    _setup_rest(game, monkeypatch, cat, ["movies-hd"], [])
    assert inst.NEW_PACK_PREFIX + "movies-hd" not in rc.declined(game)
