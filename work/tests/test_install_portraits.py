"""The portraits-hd pack's installer and release wiring.

The invariant above all: the player's own images live in <game>\\portraits\\, so the pack -- and anything the
installer does for it -- may only ever write, or prune, inside <game>\\portraits\\hd\\ (and never through a junction
or symlink planted there).  Every test
uses a throwaway game dir (tmp_path); none touches the real install."""
from __future__ import annotations

import json
import sys
import types
import zipfile
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "work" / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "art"))

import install as inst        # noqa: E402
import release as rel         # noqa: E402
import build_portraits_hd as bph   # noqa: E402

inst._load_modules()          # binds install.py's guarded imports (version, config) as its own main() does


def test_the_pack_may_write_only_into_portraits_hd(tmp_path):
    roots = inst.MODULE_ROOTS["portraits-hd"]
    assert roots == ("portraits/hd",)
    assert inst._contained(tmp_path, "portraits/hd/gaians.png", roots) is not None
    for bad in ("portraits/gaians.png", "portraits/README.txt", "gaians.png", "portraits/hd/../gaians.png",
                "movies/hd/x.mp4", "terranx_PRACX.exe"):
        assert inst._contained(tmp_path, bad, roots) is None, bad


def _zip(path: Path, members: dict) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def test_install_modules_prunes_only_inside_portraits_hd(tmp_path):
    game = tmp_path / "game"
    (game / "portraits" / "hd").mkdir(parents=True)
    (game / "portraits" / "gaians.png").write_bytes(b"the player's own")          # must survive everything
    (game / "portraits" / "hd" / "oldfaction.png").write_bytes(b"stale pack file")  # gone from the new pack
    (game / "portraits" / "hd" / "keep").mkdir()                                  # never a directory
    archive = _zip(tmp_path / "pack.zip", {"portraits/hd/gaians.png": b"pack gaians",
                                           "portraits/hd/pack-manifest.json": b"{}",
                                           "portraits/gaians.png": b"OVERWRITE ATTEMPT"})
    out = inst.install_modules(game, {"portraits-hd": archive}, {"portraits-hd": "1.0.0"})
    assert (game / "portraits" / "gaians.png").read_bytes() == b"the player's own"
    assert (game / "portraits" / "hd" / "gaians.png").read_bytes() == b"pack gaians"
    # the refused member makes the module incomplete: no receipt entry, and NOTHING is pruned from a pack
    # that did not install cleanly
    assert (game / "portraits" / "hd" / "oldfaction.png").exists()
    assert (game / "portraits" / "hd" / "keep").is_dir()
    assert "portraits-hd" not in out


def test_a_clean_pack_installs_and_prunes(tmp_path):
    game = tmp_path / "game"
    (game / "portraits" / "hd").mkdir(parents=True)
    (game / "portraits" / "hd" / "oldfaction.png").write_bytes(b"stale")
    (game / "portraits" / "mine.png").write_bytes(b"mine")
    archive = _zip(tmp_path / "pack.zip", {"portraits/hd/gaians.png": b"g", "portraits/hd/PROVENANCE.txt": b"p"})
    out = inst.install_modules(game, {"portraits-hd": archive}, {"portraits-hd": "1.0.0"})
    assert out["portraits-hd"]["version"] == "1.0.0"
    assert sorted(p.name for p in (game / "portraits" / "hd").iterdir()) == ["PROVENANCE.txt", "gaians.png"]
    assert (game / "portraits" / "mine.png").read_bytes() == b"mine"


def test_local_pack_copy_only_takes_pack_files_and_prunes(tmp_path):
    pack = tmp_path / "dist"
    pack.mkdir()
    for n in ("gaians.png", "hive.png", "pack-manifest.json", "PROVENANCE.txt", "Thumbs.db", "notes.txt"):
        (pack / n).write_bytes(n.encode())
    game = tmp_path / "game"
    (game / "portraits" / "hd").mkdir(parents=True)
    (game / "portraits" / "hd" / "old.png").write_bytes(b"old")
    (game / "portraits" / "gaians.png").write_bytes(b"mine")
    assert inst.install_portrait_pack(game, pack)
    assert sorted(p.name for p in (game / "portraits" / "hd").iterdir()) == \
        ["PROVENANCE.txt", "gaians.png", "hive.png", "pack-manifest.json"]
    assert (game / "portraits" / "gaians.png").read_bytes() == b"mine"


def test_pack_on_disk_ignores_the_players_folder_and_the_readme(tmp_path):
    (tmp_path / "portraits").mkdir()
    (tmp_path / "portraits" / "README.txt").write_text("guide")
    (tmp_path / "portraits" / "gaians.png").write_bytes(b"mine")
    assert not inst.pack_on_disk(tmp_path, "portraits-hd")
    (tmp_path / "portraits" / "hd").mkdir()
    (tmp_path / "portraits" / "hd" / "gaians.png").write_bytes(b"pack")
    assert inst.pack_on_disk(tmp_path, "portraits-hd")


def test_local_portrait_pack_is_catalogued(tmp_path):
    pack = tmp_path / "dist"
    pack.mkdir()
    (pack / "gaians.png").write_bytes(b"x" * 10)
    args = types.SimpleNamespace(modules=None, ai="off", pack=str(tmp_path / "nope"), portrait_pack=str(pack),
                                 manifest=None, offline=True)
    cat, _ = inst.module_catalogue(tmp_path / "game", args)
    assert cat["portraits-hd"]["source"] == "local" and cat["portraits-hd"]["path"] == pack


def test_deploy_runtime_places_the_portraits_readme_and_nothing_else_there(tmp_path, monkeypatch):
    payload = tmp_path / "payload"
    (payload / "ff").mkdir(parents=True)
    (payload / "ff" / "avutil.dll").write_bytes(b"d")
    (payload / "uimod.dll").write_bytes(b"u")
    readme = payload / "portraits-README.txt"
    readme.write_text("guide", encoding="utf-8")
    monkeypatch.setattr(inst, "uimod_dll", lambda: payload / "uimod.dll")
    monkeypatch.setattr(inst, "ffmpeg_bin", lambda: payload / "ff")
    monkeypatch.setattr(inst, "popup_art", lambda: payload / "missing.pcx")
    monkeypatch.setattr(inst, "portraits_readme", lambda: readme)
    game = tmp_path / "game"
    (game / "portraits").mkdir(parents=True)
    (game / "portraits" / "gaians.png").write_bytes(b"mine")
    (game / "portraits" / "README.txt").write_text("a community pack's own readme", encoding="utf-8")
    assert inst.deploy_runtime(game)
    assert (game / "portraits" / inst.PORTRAITS_README).read_text(encoding="utf-8") == "guide"
    assert (game / "portraits" / "README.txt").read_text(encoding="utf-8") == "a community pack's own readme"
    assert sorted(p.name for p in (game / "portraits").iterdir()) == \
        sorted([inst.PORTRAITS_README, "README.txt", "gaians.png"])


def test_the_release_spec_ships_the_pack_to_portraits_hd_and_the_readme_with_base():
    spec = rel.MODULE_SPEC["portraits-hd"]
    assert {g[2] for g in spec["globs"]} == {"portraits/hd"}
    assert ("work/art/portraits-README.txt", "portraits/" + inst.PORTRAITS_README) in rel.MODULE_SPEC["base"]["files"]


def _built_pack(tmp_path: Path) -> Path:
    d = tmp_path / "portraits-hd"
    d.mkdir()
    files = []
    for fac in bph.LEADERS.values():
        p = d / f"{fac}.png"
        p.write_bytes(fac.encode() * 10)
        files.append({"name": p.name, "size": p.stat().st_size, "sha256": bph.sha256_file(p)})
    (d / bph.MANIFEST).write_text(json.dumps({"files": files}), encoding="utf-8")
    (d / bph.PROVENANCE).write_text("Art by Turovetsky\nhttps://www.youtube.com/@Turovetsky\nhttps://x.com/turovetsky\n",
                                    encoding="utf-8")
    return d


def test_release_accepts_exactly_the_built_pack(tmp_path):
    rel._check_portrait_pack(_built_pack(tmp_path))


@pytest.mark.parametrize("damage", ["stray", "missing", "edited", "no_credit", "credit_without_links"])
def test_release_refuses_anything_else(tmp_path, damage):
    d = _built_pack(tmp_path)
    if damage == "stray":
        (d / "Thumbs.db").write_bytes(b"x")
    elif damage == "missing":
        (d / "gaians.png").unlink()
    elif damage == "edited":
        (d / "hive.png").write_bytes(b"retouched by hand")
    elif damage == "no_credit":
        (d / bph.PROVENANCE).write_text("  ", encoding="utf-8")
    elif damage == "credit_without_links":
        (d / bph.PROVENANCE).write_text("Art by Turovetsky", encoding="utf-8")
    with pytest.raises(ValueError):
        rel._check_portrait_pack(d)


def test_the_installer_credits_the_artist():
    assert "Turovetsky" in inst.PORTRAIT_ART_CREDIT
    assert "youtube.com/@Turovetsky" in inst.PORTRAIT_ART_CREDIT and "x.com/turovetsky" in inst.PORTRAIT_ART_CREDIT
    readme = (_REPO / "work" / "art" / "portraits-README.txt").read_text(encoding="utf-8")
    prov = (_REPO / "work" / "art" / "portraits-hd-PROVENANCE.txt").read_text(encoding="utf-8")
    for text in (readme, prov):
        assert "Turovetsky" in text and "youtube.com/@Turovetsky" in text and "x.com/turovetsky" in text


def _junction(link: Path, target: Path) -> bool:
    """A directory junction (no admin needed); False where it cannot be made."""
    import subprocess
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    return r.returncode == 0 and link.exists()


@pytest.mark.parametrize("target", ["portraits", "."])
def test_a_junction_at_portraits_hd_writes_and_prunes_nothing(tmp_path, target):
    """portraits\\hd planted as a junction to portraits\\ (the player's folder) or the game root: every member is
    refused and nothing is pruned -- the player's portraits, the exe and the saves are untouched."""
    game = tmp_path / "game"
    (game / "portraits").mkdir(parents=True)
    (game / "portraits" / "gaians.png").write_bytes(b"the player's own")
    (game / "terranx_PRACX.exe").write_bytes(b"exe")
    if not _junction(game / "portraits" / "hd", (game / target).resolve()):
        pytest.skip("cannot create a junction here")
    archive = _zip(tmp_path / "pack.zip", {"portraits/hd/gaians.png": b"pack", "portraits/hd/hive.png": b"pack"})
    out = inst.install_modules(game, {"portraits-hd": archive}, {"portraits-hd": "1.0.0"})
    assert "portraits-hd" not in out
    assert (game / "portraits" / "gaians.png").read_bytes() == b"the player's own"
    assert (game / "terranx_PRACX.exe").read_bytes() == b"exe"
    assert not (game / "portraits" / "hive.png").exists() and not (game / "hive.png").exists()
    assert inst.prune_pack_dir(game, "portraits/hd", set()) == 0


def test_prune_is_case_insensitive(tmp_path):
    game = tmp_path / "game"
    (game / "portraits" / "hd").mkdir(parents=True)
    (game / "portraits" / "hd" / "Gaians.PNG").write_bytes(b"current, old casing")
    (game / "portraits" / "hd" / "stale.png").write_bytes(b"stale")
    assert inst.prune_pack_dir(game, "portraits/hd", {"gaians.png"}) == 1
    assert (game / "portraits" / "hd" / "Gaians.PNG").exists()


def test_members_in_other_casing_still_land_in_the_pack_folder(tmp_path):
    game = tmp_path / "game"
    (game / "portraits" / "hd").mkdir(parents=True)
    archive = _zip(tmp_path / "pack.zip", {"Portraits/HD/gaians.png": b"g"})
    out = inst.install_modules(game, {"portraits-hd": archive}, {"portraits-hd": "1.0.0"})
    assert "portraits-hd" in out
    assert (game / "portraits" / "hd" / "gaians.png").read_bytes() == b"g"


def test_release_refuses_to_reuse_a_stale_portrait_archive(tmp_path, monkeypatch):
    d = tmp_path / "dist" / "portraits-hd"
    d.mkdir(parents=True)
    (d / "gaians.png").write_bytes(b"new crop")
    archive = _zip(tmp_path / "LV-portraits-hd-0.1.0.zip", {"portraits/hd/gaians.png": b"old crop",
                                                         "portraits/hd/pack-manifest.json": b"{}"})
    monkeypatch.setattr(rel, "_REPO", tmp_path)
    with pytest.raises(SystemExit, match="Bump MODULE_VERSIONS"):
        rel._check_reused_portrait_pack(archive, "0.1.0")
    (d / "gaians.png").write_bytes(b"old crop")
    (d / "pack-manifest.json").write_bytes(b"{}")
    rel._check_reused_portrait_pack(archive, "0.1.0")          # identical: reused silently
    bare = _zip(tmp_path / "LV-portraits-hd-0.2.0.zip", {"x.bin": b"x"})
    rel._check_reused_portrait_pack(bare, "0.2.0")             # no manifest: not built from a pack folder
