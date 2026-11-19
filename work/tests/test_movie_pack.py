"""The movies-hd pack (Z2k Retro's HD Cinematics): what release.py will ship, the provenance the sidecar records,
and the upscaler's credit wherever the pack is installed or distributed.

The pack is checked by NAME because the game looks clips up by name: movies\\hd\\<movie>.mp4 for every
movies\\<movie>.wve. A misspelt or missing clip is not an error the game reports -- that movie just plays the
original -- so the release must refuse it. Every test builds a tiny throwaway pack (61 small files); none reads the
real 5 GB pack or touches a game folder."""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO / "work" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import hash_hd_pack as hhp    # noqa: E402
import install as inst        # noqa: E402
import release as rel         # noqa: E402

inst._load_modules()          # binds install.py's guarded imports (version, config) as its own main() does

_PROV = _REPO / "work" / "art" / "movies-hd-PROVENANCE.txt"
_CREDIT = ("Z2k Retro", "https://www.youtube.com/@Z2KRetroGaming", "https://www.youtube.com/@Z2kRetroVideo")


def _pack(root: Path) -> Path:
    """A shippable pack in miniature: 61 clips by the game's names, the sidecar, the tracked provenance."""
    d = root / "movies-hd"
    d.mkdir()
    for n in hhp.MOVIE_CLIPS:
        (d / f"{n}.mp4").write_bytes(b"clip:" + n.encode())
    assert hhp.build(d) == 0
    shutil.copyfile(_PROV, d / "PROVENANCE.txt")
    return d


def test_the_game_movie_names_are_61_distinct():
    assert len(hhp.MOVIE_CLIPS) == 61
    assert len({n.lower() for n in hhp.MOVIE_CLIPS}) == 61


def test_the_names_are_the_games_own_movies():
    """Every name is a movies\\<name>.wve of the installed game, exact case included (skipped without a game)."""
    try:
        import config
        dirs = config.candidate_game_dirs()
    except Exception:  # noqa: BLE001 - no game is not a failure here
        dirs = []
    movies = next((Path(d) / "movies" for d in dirs if (Path(d) / "movies").is_dir()), None)
    if movies is None:
        pytest.skip("no game install with a movies folder on this machine")
    wve = sorted(p.stem for p in movies.glob("*.wve"))
    assert wve == sorted(hhp.MOVIE_CLIPS)


def test_a_shippable_pack_passes(tmp_path):
    rel._check_movie_pack(_pack(tmp_path))


@pytest.mark.parametrize("damage", ["missing_clip", "wrong_case", "space_in_name", "stray_file", "edited_clip",
                                    "no_provenance", "edited_provenance", "credit_without_links",
                                    "sidecar_missing_a_clip"])
def test_an_unshippable_pack_is_refused(tmp_path, damage):
    d = _pack(tmp_path)
    if damage == "missing_clip":
        (d / "theyTranscend.mp4").unlink()
    elif damage == "wrong_case":           # the archive.org originals were capitalised: "Angels.mp4"
        (d / "angels.mp4").rename(d / "tmp.mp4")
        (d / "tmp.mp4").rename(d / "Angels.mp4")
    elif damage == "space_in_name":        # ...and three had spaces: "Close Ct.mp4"
        (d / "close_ct.mp4").rename(d / "Close Ct.mp4")
    elif damage == "stray_file":
        (d / "Thumbs.db").write_bytes(b"x")
    elif damage == "edited_clip":
        (d / "gaians.mp4").write_bytes(b"re-encoded after hashing")
    elif damage == "no_provenance":
        (d / "PROVENANCE.txt").unlink()
    elif damage == "edited_provenance":
        (d / "PROVENANCE.txt").write_bytes(_PROV.read_bytes().replace(b"GPL-3.0-or-later", b"CC-BY-NC"))
    elif damage == "credit_without_links":
        (d / "PROVENANCE.txt").write_text("Upscaled by Z2k Retro.", encoding="utf-8")
    elif damage == "sidecar_missing_a_clip":
        doc = json.loads((d / hhp.SIDECAR_NAME).read_text(encoding="utf-8"))
        doc["clips"] = doc["clips"][1:]
        (d / hhp.SIDECAR_NAME).write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError):
        rel._check_movie_pack(d)


def _zip(path: Path, members: dict) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def test_a_reused_archive_must_carry_the_current_credit(tmp_path):
    """The 1.0.0 Real-ESRGAN archive has no PROVENANCE.txt: it can never ride along into a later manifest."""
    old = _zip(tmp_path / "LV-movies-hd-1.0.0.zip", {"movies/hd/angels.mp4": b"x", "movies/hd/pack-manifest.json": b"{}"})
    with pytest.raises(SystemExit):
        rel._check_reused_movie_pack(old, "1.0.0")
    stale = _zip(tmp_path / "LV-movies-hd-2.0.0.zip", {"movies/hd/PROVENANCE.txt": b"Upscaled by Z2k Retro."})
    with pytest.raises(SystemExit):
        rel._check_reused_movie_pack(stale, "2.0.0")
    good = _zip(tmp_path / "LV-movies-hd-2.0.1.zip", {"movies/hd/PROVENANCE.txt": _PROV.read_bytes()})
    rel._check_reused_movie_pack(good, "2.0.1")


def test_the_pack_ships_its_provenance():
    assert ("dist/movies-hd", "PROVENANCE.txt", "movies/hd") in rel.MODULE_SPEC["movies-hd"]["globs"]


def test_the_sidecar_keeps_a_clips_recorded_provenance_while_its_bytes_are_unchanged(tmp_path):
    """release_all re-runs hash_hd_pack on the pack. It used to stamp every clip with pipeline.ini's Real-ESRGAN
    settings, so a third-party pack shipped claiming to be ours. Provenance now belongs to the bytes."""
    d = tmp_path / "pack"
    d.mkdir()
    (d / "a.mp4").write_bytes(b"aaa")
    (d / "b.mp4").write_bytes(b"bbb")
    assert hhp.build(d) == 0
    doc = json.loads((d / hhp.SIDECAR_NAME).read_text(encoding="utf-8"))
    theirs = {"model": "topaz-starlight-precise+chronos-30fps", "scale": None, "crf": None}
    for c in doc["clips"]:
        c.update(theirs)
    doc["defaults"] = dict(theirs)
    (d / hhp.SIDECAR_NAME).write_text(json.dumps(doc), encoding="utf-8")

    os.utime(d / "a.mp4", ns=(1, 1))                    # a copy that lost its mtime: re-hashed, same bytes
    assert hhp.build(d) == 0
    doc = json.loads((d / hhp.SIDECAR_NAME).read_text(encoding="utf-8"))
    assert all(c["model"] == theirs["model"] for c in doc["clips"])
    assert doc["defaults"] == theirs

    (d / "b.mp4").write_bytes(b"rebuilt by our pipeline")     # new bytes: pipeline.ini describes them
    assert hhp.build(d) == 0
    doc = json.loads((d / hhp.SIDECAR_NAME).read_text(encoding="utf-8"))
    by = {c["name"]: c for c in doc["clips"]}
    assert by["a.mp4"]["model"] == theirs["model"]
    defaults, overrides = hhp.read_pipeline()
    assert by["b.mp4"]["model"] == hhp.settings_for("b", defaults, overrides)["model"]
    assert doc["defaults"]["model"] == defaults.get("model")       # mixed pack: the pipeline's defaults


def test_the_upscaler_is_credited_everywhere_the_pack_goes():
    """The credit the author asked for (2026-11-10/12): his name and both channels, in the installer's line for
    anyone installing the pack and in the PROVENANCE.txt shipped inside it. (The pack's release page carries it
    too; that page is written by the release tooling, which is not part of the public source, and is pinned there.)"""
    prov = _PROV.read_text(encoding="utf-8")
    for text in (inst.CINEMATICS_CREDIT, prov):
        for must in _CREDIT:
            assert must in text, (must, text)
    assert "GPL-3.0-or-later" in prov
    assert inst.MODULE_LABELS["movies-hd"] == "Z2k Retro's HD Cinematics"


def test_a_local_pack_install_copies_the_provenance_and_credits_the_upscaler(tmp_path):
    pack = _pack(tmp_path)
    game = tmp_path / "game"
    game.mkdir()
    out = io.StringIO()
    with redirect_stdout(out):
        assert inst.install_movie_pack(game, pack) is True
    hd = game / "movies" / "hd"
    assert (hd / "PROVENANCE.txt").read_bytes() == _PROV.read_bytes()
    assert (hd / hhp.SIDECAR_NAME).is_file()
    assert len(list(hd.glob("*.mp4"))) == 61
    assert inst.CINEMATICS_CREDIT.strip() in out.getvalue()
