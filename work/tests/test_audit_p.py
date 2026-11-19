"""Audit-p (2026-11-17, an antagonistic audit of 69abb2b..1cb02b4): the fixes triaged for the user. Each test written
to fail first.

MEDIUM-1/2: before any file of a pack is extracted or copied, the release's pack-manifest.json is written as
pack-manifest.json.partial in the pack folder; the real manifest still lands last, then the .partial goes. A folder
holding a .partial is a pack the player chose that is not complete: a re-run starts it ticked and completes it
(--no-prompt and unattended too), it is never kept or adopted, and an uninstall removes what the .partial lists. A
pack folder with neither list is never left silently.
LOW-1: a pack left unticked by DEFAULT on a re-run does not switch the HD Cinematics off.
LOW-2: release.py checks the exact archive paths and refuses duplicates.
Test gaps: N8, N3b/N3c, N6b, N15."""
from __future__ import annotations

import hashlib
import json
import sys
import types
import zipfile
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import install as inst              # noqa: E402
import installer_exit as ix         # noqa: E402
import receipt as rc                # noqa: E402
import release as rel               # noqa: E402
from test_audit_n import PROV, _catalogue, _game, _into_game, _setup_rest, _src  # noqa: E402
from test_rerun_pack_defaults import _cat  # noqa: E402
from test_setup_pack_rerun import CLIPS, PORTRAITS, _keys, _pack  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")

PARTIAL = "pack-manifest.json.partial"


def _manifest_bytes(name: str, files: dict) -> bytes:
    key = "clips" if name == "movies-hd" else "files"
    return json.dumps({"schema": 1, "pack": name, key: [
        {"name": n, "size": len(d), "sha256": hashlib.sha256(d).hexdigest()} for n, d in files.items()]}).encode()


def _archive(tmp_path, name: str, files: dict) -> Path:
    """A release archive in the real order: the manifest early (entry 36 of 62 in the Cinematics one)."""
    root = inst.MODULE_ROOTS[name][0]
    p = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(f"{root}/pack-manifest.json", _manifest_bytes(name, files))
        z.writestr(f"{root}/PROVENANCE.txt", PROV)
        for n, d in files.items():
            z.writestr(f"{root}/{n}", d)
    return p


def _rerun_game(tmp_path) -> Path:
    g = _game(tmp_path)
    rc.write(g, target_id="pracx", modules={"base": {"version": "1.0.0"}})
    return g


def _failed_portraits(game: Path) -> Path:
    """What a portrait install that failed part-way leaves: some images and the .partial, no manifest."""
    root = game / "portraits" / "hd"
    root.mkdir(parents=True, exist_ok=True)
    (root / "caretake.png").write_bytes(PORTRAITS["caretake.png"])
    (root / PARTIAL).write_bytes(_manifest_bytes("portraits-hd", {**PORTRAITS, "usurper.png": b"u" * 20}))
    return root


# ---------------------------------------------------------------- the .partial is written first, removed last

def test_an_archive_writes_its_partial_before_any_file(tmp_path, monkeypatch):
    game = _game(tmp_path)
    archive = _archive(tmp_path, "movies-hd", CLIPS)
    seen = []
    real = inst.shutil.copyfileobj

    def watch(src, dst, *a):
        seen.append((Path(dst.name).name, (game / "movies" / "hd" / PARTIAL).is_file()))
        return real(src, dst, *a)
    monkeypatch.setattr(inst.shutil, "copyfileobj", watch)
    inst.install_modules(game, {"movies-hd": archive}, {"movies-hd": "2.0.0"})
    assert seen and all(present for _n, present in seen)                # there before the first member
    root = game / "movies" / "hd"
    assert not (root / PARTIAL).exists() and (root / "pack-manifest.json").is_file()      # gone once complete


def test_an_archive_stopped_part_way_leaves_the_partial(tmp_path, monkeypatch):
    game = _game(tmp_path)
    archive = _archive(tmp_path, "movies-hd", CLIPS)
    real = inst.shutil.copyfileobj

    def stop(src, dst, *a):
        if "intro.mp4" in str(getattr(dst, "name", "")):
            raise KeyboardInterrupt
        return real(src, dst, *a)
    monkeypatch.setattr(inst.shutil, "copyfileobj", stop)
    with pytest.raises(KeyboardInterrupt):
        inst.install_modules(game, {"movies-hd": archive}, {"movies-hd": "2.0.0"})
    root = game / "movies" / "hd"
    assert (root / PARTIAL).read_bytes() == _manifest_bytes("movies-hd", CLIPS)
    assert not (root / "pack-manifest.json").exists()


def test_a_failed_member_keeps_the_manifest_out_and_the_partial_in(tmp_path):
    """N8: a member that could not be placed (here a folder in its way) keeps the real manifest out."""
    game = _game(tmp_path)
    (game / "movies" / "hd" / "intro.mp4").mkdir(parents=True)
    inst.install_modules(game, {"movies-hd": _archive(tmp_path, "movies-hd", CLIPS)}, {"movies-hd": "2.0.0"})
    root = game / "movies" / "hd"
    assert not (root / "pack-manifest.json").exists() and (root / PARTIAL).is_file()


@pytest.mark.parametrize("name", ["movies-hd", "portraits-hd"])
def test_a_local_copy_writes_its_partial_first_and_removes_it_last(tmp_path, monkeypatch, name):
    game = _game(tmp_path)
    src = _src(tmp_path, name)
    root = game / inst.MODULE_ROOTS[name][0]
    seen = []
    real = inst._copy_into_place
    monkeypatch.setattr(inst, "_copy_into_place",
                        lambda s, d: seen.append((Path(d).name, (root / PARTIAL).is_file())) or real(s, d))
    copy = inst.install_movie_pack if name == "movies-hd" else inst.install_portrait_pack
    assert copy(game, src) is True
    assert [p for n, p in seen if n != PARTIAL] and all(p for n, p in seen if n != PARTIAL)
    assert not (root / PARTIAL).exists()


# ---------------------------------------------------------------- MEDIUM-1: a re-run completes it

def test_a_failed_portrait_install_counts_as_chosen(tmp_path):
    game = _rerun_game(tmp_path)
    _failed_portraits(game)
    assert inst.pack_on_disk(game, "portraits-hd") is True


def test_a_rerun_starts_an_incomplete_pack_ticked(tmp_path, monkeypatch):
    game = _rerun_game(tmp_path)
    _failed_portraits(game)
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _keys(monkeypatch, "down", "down", "enter")
    args = types.SimpleNamespace(modules=None, ai="ask", no_prompt=False)
    assert inst.pick_modules(_cat(game), args, game)[0] == ["portraits-hd"]


@pytest.mark.parametrize("how", ["no-prompt", "unattended"])
def test_no_prompt_and_unattended_reruns_complete_it(tmp_path, monkeypatch, how):
    game = _rerun_game(tmp_path)
    _failed_portraits(game)
    monkeypatch.setattr(ix, "can_ask", lambda: how == "no-prompt")
    args = types.SimpleNamespace(modules=None, ai="ask", no_prompt=how == "no-prompt")
    assert "portraits-hd" in inst.pick_modules(_cat(game), args, game)[0]


def test_a_partial_is_never_kept_or_adopted(tmp_path, monkeypatch):
    """Even beside a complete older pack (an update stopped part-way): never "keep", never "adopt"."""
    game = _game(tmp_path)
    src = _src(tmp_path, "movies-hd")
    root = _into_game(game, src, "movies-hd")
    cat = _catalogue(game, tmp_path, monkeypatch, movies=src)["movies-hd"]
    v = cat["version"]
    assert inst.pack_action(game, "movies-hd", v, v, cat["release_manifest"], cat["release_provenance"]) == "keep"
    (root / PARTIAL).write_bytes((root / "pack-manifest.json").read_bytes())
    assert inst.pack_action(game, "movies-hd", v, v, cat["release_manifest"], cat["release_provenance"]) == "repair"
    assert inst.pack_action(game, "movies-hd", v, inst.ver.UNKNOWN, cat["release_manifest"],
                            cat["release_provenance"]) == "install"
    # an update stopped part-way (its own manifest and the .partial) is LOCKED ticked: completing it is the only
    # consistent state (audit-t ROOT 3, M3) -- yet never "keep" or "adopt" (above)
    assert _catalogue(game, tmp_path, monkeypatch, movies=src)["movies-hd"]["locked"] is True


# ---------------------------------------------------------------- MEDIUM-2: the uninstall

def test_uninstall_removes_what_the_partial_lists(tmp_path):
    game = _game(tmp_path)
    root = _failed_portraits(game)
    (root / "PROVENANCE.txt").write_bytes(PROV)
    (root / "mine.png").write_bytes(b"the player's own")                 # not listed: kept
    removed, failed = inst.remove_pack(game, "portraits-hd")
    assert failed == 0 and removed == 3                                   # caretake.png, PROVENANCE.txt, the .partial
    assert sorted(p.name for p in root.iterdir()) == ["mine.png"]


def test_uninstall_removes_a_partial_pack_and_its_folder(tmp_path):
    game = _game(tmp_path)
    root = _failed_portraits(game)
    inst.remove_pack(game, "portraits-hd")
    assert not root.exists()


def test_uninstall_removes_what_both_lists_name(tmp_path):
    """An update stopped part-way: the old manifest and the new .partial; every file either lists goes."""
    game = _game(tmp_path)
    root = _pack(game, "movies-hd", CLIPS)
    (root / "new.mp4").write_bytes(b"n")
    (root / PARTIAL).write_bytes(_manifest_bytes("movies-hd", {"new.mp4": b"n"}))
    inst.remove_pack(game, "movies-hd")
    assert not root.exists()


@pytest.mark.parametrize("bad", ["..\\..\\uimod.dll", "deep"])
def test_an_unsafe_or_unreadable_partial_leaves_the_pack_and_says_so(tmp_path, capsys, bad):
    game = _game(tmp_path)
    root = _failed_portraits(game)
    (root / PARTIAL).write_text('{"files": ' + "[" * 100000 + "]" * 100000 + "}" if bad == "deep"
                                else json.dumps({"files": [{"name": bad, "size": 1}]}), encoding="utf-8")
    assert inst.remove_pack(game, "portraits-hd") == (0, 0)
    assert "could not be read" in capsys.readouterr().out and inst._PACKS_UNREAD == ["portraits-hd"]
    assert (root / "caretake.png").is_file()


def test_a_pack_folder_with_no_list_is_never_left_silently(tmp_path, capsys):
    game = _game(tmp_path)
    root = game / "movies" / "hd"
    root.mkdir(parents=True)
    (root / "angels.mp4").write_bytes(b"a")
    assert inst.remove_pack(game, "movies-hd") == (0, 0)
    assert "could not be read" in capsys.readouterr().out and inst._PACKS_UNREAD == ["movies-hd"]


def test_no_pack_folder_says_nothing(tmp_path, capsys):
    game = _game(tmp_path)
    (game / "portraits" / "hd").mkdir(parents=True)                       # empty
    assert inst.remove_pack(game, "portraits-hd") == (0, 0) and inst.remove_pack(game, "movies-hd") == (0, 0)
    assert capsys.readouterr().out == "" and inst._PACKS_UNREAD == []


# ---------------------------------------------------------------- LOW-1: UpscaledVideos

def _cinematics_offered(game) -> dict:
    return {"movies-hd": {"size": 1, "source": "manifest", "version": "1.0.0", "on_disk": False, "locked": False,
                          "release_manifest": None, "release_provenance": None}}


@pytest.mark.parametrize("before", [None, True])
def test_a_rerun_that_leaves_the_cinematics_unticked_by_default_keeps_upscaled_videos(tmp_path, monkeypatch, before):
    game = _rerun_game(tmp_path)
    if before is not None:
        inst.set_ini_flag(game, before)
    _setup_rest(game, monkeypatch, _cinematics_offered(game), [], [])
    assert inst.ini_flag_state(game, "UpscaledVideos") is not False


def test_an_explicit_untick_still_switches_the_cinematics_off(tmp_path, monkeypatch):
    game = _rerun_game(tmp_path)
    inst.set_ini_flag(game, True)
    downloads = []
    monkeypatch.setattr(inst, "install_packs_from_manifest", lambda *a: downloads.append(a) or ({}, {}))
    monkeypatch.setattr(inst, "check_display_resolution", lambda *a, **k: None)
    monkeypatch.setattr(inst, "check_desktop_shortcut", lambda *a, **k: None)
    monkeypatch.setattr(inst.config, "remember_game_dir", lambda d: True)
    args = types.SimpleNamespace(ai="ask", no_prompt=False, manifest=None, modules=None)
    inst._install_rest(game, args, {}, "terranx.exe", None, None, {}, {}, _cinematics_offered(game), ("r", "s", {}),
                       [], ["movies-hd"], [], types.SimpleNamespace(prep=None, keep=None))
    assert inst.ini_flag_state(game, "UpscaledVideos") is False


# ---------------------------------------------------------------- LOW-2: release.py's exact paths

def _zip(tmp_path, members: list) -> Path:
    p = tmp_path / "x.zip"
    with zipfile.ZipFile(p, "w") as z:
        for n, d in members:
            z.writestr(n, d)
    return p


@pytest.mark.parametrize("name", ["movies-hd", "portraits-hd"])
def test_release_checks_the_exact_archive_paths(tmp_path, monkeypatch, name):
    import version as ver
    monkeypatch.setitem(ver.PACK_MANIFEST_SHA256, name, hashlib.sha256(b"{ok}").hexdigest())
    monkeypatch.setitem(ver.PACK_PROVENANCE_SHA256, name, hashlib.sha256(PROV).hexdigest())
    root = inst.MODULE_ROOTS[name][0]
    other = inst.MODULE_ROOTS["portraits-hd" if name == "movies-hd" else "movies-hd"][0]
    good = [(f"{root}/pack-manifest.json", b"{ok}"), (f"{root}/PROVENANCE.txt", PROV)]
    rel._check_pack_archive_compiled(_zip(tmp_path, good), name)
    bad_sets = [
        [(f"{root}/sub/pack-manifest.json", b"{ok}"), (f"{root}/PROVENANCE.txt", PROV)],          # nested
        [("pack-manifest.json", b"{ok}"), (f"{root}/PROVENANCE.txt", PROV)],                      # wrong root
        [(f"{other}/pack-manifest.json", b"{ok}"), (f"{root}/PROVENANCE.txt", PROV)],             # the other pack
        [("pack-manifest.json", b"{bad}")] + good,                                                # wrong, then right
        good + [(f"{root}/sub/PROVENANCE.txt", PROV)],                                            # an extra copy
    ]
    for members in bad_sets:
        with pytest.raises(SystemExit, match="REFUSING"):
            rel._check_pack_archive_compiled(_zip(tmp_path, members), name)
    with zipfile.ZipFile(tmp_path / "dup.zip", "w") as z:                                          # the same path twice
        for n, d in good + [good[0]]:
            z.writestr(n, d)
    with pytest.raises(SystemExit, match="REFUSING"):
        rel._check_pack_archive_compiled(tmp_path / "dup.zip", name)


# ---------------------------------------------------------------- the test gaps

def test_rerun_detection_from_the_ini_alone(tmp_path):
    """N3b: an install whose JSON receipt is gone still has the ini keys the game reads."""
    g = _game(tmp_path)
    assert inst._lv_recorded(g) is False
    rc.ini_set(g, rc.KEY_TARGET, "pracx")
    assert inst._lv_recorded(g) is True
    (tmp_path / "b").mkdir()
    g2 = _game(tmp_path / "b")
    rc.ini_set(g2, rc.MODULE_KEYS["base"], "1.0.0")
    assert inst._lv_recorded(g2) is True


def test_rerun_detection_from_a_receipt_without_target(tmp_path):
    """N3c: a receipt that records modules but no target (an older or a part-written one)."""
    g = _game(tmp_path)
    (g / rc.JSON_NAME).write_text(json.dumps({"modules": {"base": {"version": "1.0.0"}}}), encoding="utf-8")
    assert rc.read(g).get("target_id") is None and inst._lv_recorded(g) is True


def test_a_local_pack_without_provenance_is_never_adopted(tmp_path, monkeypatch):
    """N6b: the folder holds exactly the local pack, but the local pack has no PROVENANCE.txt to compare against."""
    game = _game(tmp_path)
    src = _src(tmp_path, "movies-hd")
    _into_game(game, src, "movies-hd")
    (src / "PROVENANCE.txt").unlink()
    cat = _catalogue(game, tmp_path, monkeypatch, movies=src)["movies-hd"]
    assert cat["release_provenance"] is None and cat["release_manifest"] is not None
    assert inst.pack_action(game, "movies-hd", cat["version"], inst.ver.UNKNOWN, cat["release_manifest"],
                            cat["release_provenance"]) == "install"


def test_the_provenance_keep_check_is_only_for_the_same_release(tmp_path):
    """N15: a pack recorded at a NEWER version than the one on offer is kept whatever the offered release's
    PROVENANCE.txt is: that hash describes another release."""
    game = _game(tmp_path)
    root = _pack(game, "movies-hd", CLIPS)
    (root / "PROVENANCE.txt").write_bytes(b"the newer release's credit")
    assert inst.pack_action(game, "movies-hd", "1.9.0", "2.0.0", None, hashlib.sha256(PROV).hexdigest()) == "keep"
