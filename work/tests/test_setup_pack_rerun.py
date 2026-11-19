"""A setup re-run and the optional packs already installed (user-approved change, 2026-11-17).

Before it, a setup re-run downloaded (or, from a checkout, copied) every ticked pack again -- 1.39 GB for the HD
Cinematics -- even when it was installed, current and intact; unticking it was the only way to skip that. Now:
  * an installed pack (its files and its pack-manifest.json in the game folder) stays ticked in the list and cannot
    be unticked;
  * a re-run downloads or copies it only when it needs it: the offered version is newer than the receipt's, or a
    file its pack-manifest.json lists is missing or the wrong size. Otherwise nothing is fetched or copied, and its
    receipt entry stays exactly as it was.
Each test written to fail first."""
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

pytestmark = pytest.mark.usefixtures("install_globals")

CLIPS = {"angels.mp4": b"a" * 40, "intro.mp4": b"b" * 70}
PORTRAITS = {"caretake.png": b"p" * 30}


def _pack(game: Path, name: str, files: dict, *, manifest: bool = True, sizes: dict = None) -> Path:
    """An installed pack: its files in its game folder, and the pack-manifest.json the release archive carries."""
    inst._load_modules()
    root = game / inst.MODULE_ROOTS[name][0]
    root.mkdir(parents=True, exist_ok=True)
    for n, data in files.items():
        (root / n).write_bytes(data)
    if manifest:
        key = "clips" if name == "movies-hd" else "files"
        doc = {"schema": 1, "pack": name, key: [
            {"name": n, "size": (sizes or {}).get(n, len(d)), "sha256": hashlib.sha256(d).hexdigest()}
            for n, d in files.items()]}
        (root / "pack-manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    return root


# ---------------------------------------------------------------- what a re-run does with each pack

@pytest.mark.parametrize("case,expect", [
    ("current-and-intact", "keep"),
    ("newer-offered", "update"),
    ("a-file-missing", "repair"),
    ("a-file-the-wrong-size", "repair"),
    ("not-in-the-game-folder", "install"),
    ("no-receipt-version", "install"),
    ("no-pack-manifest", "install"),
    ("unreadable-pack-manifest", "install"),
])
@pytest.mark.parametrize("name", ["movies-hd", "portraits-hd"])
def test_what_a_rerun_does_with_a_pack(tmp_path, name, case, expect):
    files = CLIPS if name == "movies-hd" else PORTRAITS
    game = tmp_path / "game"
    game.mkdir()
    recorded, offered = "1.0.0", "1.0.0"
    if case != "not-in-the-game-folder":
        root = _pack(game, name, files, manifest=case != "no-pack-manifest")
        first = next(iter(files))
        if case == "a-file-missing":
            (root / first).unlink()
        elif case == "a-file-the-wrong-size":
            (root / first).write_bytes(b"x")
        elif case == "unreadable-pack-manifest":
            (root / "pack-manifest.json").write_text("{not json", encoding="utf-8")
    if case == "newer-offered":
        offered = "1.1.0"
    if case == "no-receipt-version":
        recorded = inst.ver.UNKNOWN
    assert inst.pack_action(game, name, offered, recorded) == expect


def test_an_older_or_unreadable_offer_never_replaces_an_intact_pack(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    _pack(game, "movies-hd", CLIPS)
    assert inst.pack_action(game, "movies-hd", "0.9.0", "1.0.0") == "keep"
    assert inst.pack_action(game, "movies-hd", None, "1.0.0") == "keep"


def test_a_listed_name_that_leaves_the_folder_is_not_intact(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    root = _pack(game, "movies-hd", CLIPS)
    doc = json.loads((root / "pack-manifest.json").read_text(encoding="utf-8"))
    doc["clips"].append({"name": "..\\..\\uimod.dll", "size": 1})
    (root / "pack-manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    assert inst.pack_action(game, "movies-hd", "1.0.0", "1.0.0") == "install"


# ---------------------------------------------------------------- the placing step

class _World:
    def __init__(self, tmp_path, monkeypatch):
        self.game = tmp_path / "game"
        self.game.mkdir()
        self.downloads, self.copies = [], []
        monkeypatch.setattr(inst, "install_packs_from_manifest", self._download)
        monkeypatch.setattr(inst, "install_movie_pack", lambda g, p: self.copies.append("movies-hd") or True)
        monkeypatch.setattr(inst, "install_portrait_pack", lambda g, p: self.copies.append("portraits-hd") or True)
        self.args = types.SimpleNamespace(manifest=None)

    def _download(self, game_dir, args, names, manifest, target_id, target):
        self.downloads.append(list(names))
        return {n: {"version": "1.1.0", "files": []} for n in names}, {n: "ok" for n in names}

    def place(self, chosen, catalogue, recorded):
        return inst.place_packs(self.game, self.args, chosen, catalogue, ("raw", "sig", {}), "pracx",
                                self.game / "terranx.exe", recorded)


def _remote(version="1.0.0", **kw):
    return {"size": 1, "source": "manifest", "version": version, **kw}


def test_an_installed_current_intact_pack_is_never_downloaded_again(tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch)
    _pack(w.game, "movies-hd", CLIPS)
    got, status, how = w.place(["movies-hd"], {"movies-hd": _remote()}, {"movies-hd": "1.0.0"})
    assert w.downloads == [] and got == {}                              # its receipt entry is left exactly as it was
    assert status["movies-hd"] == "ok" and how["movies-hd"] == "keep"


def test_only_the_packs_that_need_it_are_downloaded(tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch)
    _pack(w.game, "movies-hd", CLIPS)                                   # current and intact
    root = _pack(w.game, "portraits-hd", PORTRAITS)
    (root / "caretake.png").unlink()                                    # damaged
    got, status, how = w.place(["movies-hd", "portraits-hd"],
                               {"movies-hd": _remote(), "portraits-hd": _remote()},
                               {"movies-hd": "1.0.0", "portraits-hd": "1.0.0"})
    assert w.downloads == [["portraits-hd"]] and set(got) == {"portraits-hd"}
    assert how == {"movies-hd": "keep", "portraits-hd": "repair"} and status["portraits-hd"] == "ok"


def test_a_newer_release_is_still_downloaded(tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch)
    _pack(w.game, "movies-hd", CLIPS)
    got, _status, how = w.place(["movies-hd"], {"movies-hd": _remote("1.1.0")}, {"movies-hd": "1.0.0"})
    assert w.downloads == [["movies-hd"]] and got["movies-hd"]["version"] == "1.1.0" and how["movies-hd"] == "update"


def test_a_first_install_downloads_as_before(tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch)
    _got, status, how = w.place(["movies-hd"], {"movies-hd": _remote()}, {})
    assert w.downloads == [["movies-hd"]] and how["movies-hd"] == "install" and status["movies-hd"] == "ok"


def test_a_local_pack_is_not_copied_again_when_current_and_intact(tmp_path, monkeypatch):
    w = _World(tmp_path, monkeypatch)
    _pack(w.game, "movies-hd", CLIPS)
    v = inst.ver.module_version("movies-hd")
    cat = {"movies-hd": {"size": 1, "source": "local", "path": tmp_path, "version": v}}
    got, status, how = w.place(["movies-hd"], cat, {"movies-hd": v})
    assert w.copies == [] and got == {} and how["movies-hd"] == "keep" and status["movies-hd"] == "ok"
    (w.game / "movies" / "hd" / "intro.mp4").unlink()
    got, _s, how = w.place(["movies-hd"], cat, {"movies-hd": v})
    assert w.copies == ["movies-hd"] and how["movies-hd"] == "repair" and got["movies-hd"] == {"version": v}


# ---------------------------------------------------------------- the list: an installed pack cannot be unticked

def _keys(monkeypatch, *keys):
    it = iter(keys)
    monkeypatch.setattr(inst, "_read_key", lambda: next(it))
    monkeypatch.setattr(inst, "_drop_typed_ahead", lambda: None)
    monkeypatch.setattr(ix, "_colour_ok", lambda: False)


def _listed(**kw):
    return {"size": 1, "source": "manifest", "on_disk": False, "locked": False, **kw}


def test_enter_and_space_never_untick_an_installed_pack(monkeypatch):
    cat = {"movies-hd": _listed(on_disk=True, locked=True), "portraits-hd": _listed()}
    _keys(monkeypatch, "enter", "space", "enter", "down", "down", "enter")
    names = list(cat)
    assert inst._tick_picker(names, cat, {"movies-hd": True, "portraits-hd": True}) == ["movies-hd", "portraits-hd"]


def test_other_rows_still_tick_and_untick(monkeypatch):
    cat = {"movies-hd": _listed(on_disk=True, locked=True), "portraits-hd": _listed()}
    _keys(monkeypatch, "down", "enter", "down", "enter")
    assert inst._tick_picker(list(cat), cat, {"movies-hd": True, "portraits-hd": True}) == ["movies-hd"]


def test_the_catalogue_marks_an_installed_pack_and_its_version(tmp_path, monkeypatch):
    """A checkout's local packs (no manifest is fetched): the HD Cinematics installed in the game folder (its receipt
    entry at the version on offer: a pack this run keeps -- audit-n: only those are locked) is locked, the portrait
    pack (not installed) is not; each carries the version a re-run would install."""
    import receipt as rc
    game = tmp_path / "game"
    game.mkdir()
    _pack(game, "movies-hd", CLIPS)
    rc.write(game, modules={"movies-hd": {"version": inst.ver.module_version("movies-hd")}})
    src_m = tmp_path / "src-movies"
    src_m.mkdir()
    (src_m / "angels.mp4").write_bytes(b"a")
    src_p = tmp_path / "src-portraits"
    src_p.mkdir()
    (src_p / "caretake.png").write_bytes(b"p")
    monkeypatch.setattr(ix, "has_console", lambda: False)
    monkeypatch.setattr(inst, "_thinker_off_pin", lambda g: False)
    args = types.SimpleNamespace(pack=str(src_m), portrait_pack=str(src_p), ai="ask", modules=None, no_prompt=False,
                                 manifest=None, offline=True)
    cat, _manifest = inst.module_catalogue(game, args)
    assert cat["movies-hd"]["locked"] is True and cat["portraits-hd"]["locked"] is False
    assert cat["movies-hd"]["version"] == inst.ver.module_version("movies-hd")


def test_setup_places_packs_through_the_one_step_with_the_receipts_versions():
    """_install_rest places the packs through place_packs, with each pack's receipt version from before the run (its
    receipt write merges only what place_packs placed, so a kept pack's entry is left as it was)."""
    import inspect
    src = inspect.getsource(inst._install_rest)
    assert "place_packs(" in src and "install_packs_from_manifest(" not in src
    # the receipt as the run found it, read once before place_packs (which records each landed pack: audit-t ROOT 4)
    assert src.index("before = rc.read(game_dir)") < src.index("rc.module_version(before, n)") \
        < src.index("place_packs(") < src.index("rc.write(")
    assert "mods.update(installed_packs)" in src


def test_a_cinematics_folder_without_its_pack_manifest_is_not_locked(tmp_path, monkeypatch):
    """movies\\hd holding clips but no pack-manifest.json: nothing proves what it is, so it is not the pack -- not on
    disk (audit-t ROOT 1: the player's files), neither locked nor kept (audit-n): a ticked re-run downloads it."""
    game = tmp_path / "game"
    game.mkdir()
    _pack(game, "movies-hd", CLIPS, manifest=False)
    assert inst.pack_on_disk(game, "movies-hd") is False         # audit-t ROOT 1: files without a list are the player's
    assert inst.pack_action(game, "movies-hd", "1.0.0", "1.0.0") == "install"
