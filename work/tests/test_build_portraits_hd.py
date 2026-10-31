"""work\\scripts\\art\\build_portraits_hd.py: registration, framing, refusals, manifest.  Synthetic images only (no
game art, no HD source): a random 'painting' stands in for the HD image and a scanlined, downscaled crop of it for
the vanilla portrait."""
from __future__ import annotations

import json
import pathlib

import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "art"))
sys.path.insert(0, str(ROOT / "scripts"))
import build_portraits_hd as B  # noqa: E402

Image = pytest.importorskip("PIL.Image")
pytest.importorskip("scipy")


def painting(w, h, seed):
    """Smooth random blobs: enough structure for correlation, like a portrait."""
    import numpy as np
    rnd = np.random.default_rng(seed)
    small = rnd.integers(0, 256, size=(h // 40 + 2, w // 40 + 2, 3), dtype=np.uint8)
    return Image.fromarray(small).resize((w, h), Image.BICUBIC)


def vanilla_from(hd, rect, size=B.INTERIOR[2:]):
    """What the game's 164x198 art would be if it were this crop of the painting: downscaled + scanlined."""
    import numpy as np
    x, y, w, h = rect
    v = np.asarray(hd.crop((x, y, x + w, y + h)).resize(size, Image.LANCZOS), dtype=np.float64)
    v[1::2] *= 0.72
    return Image.fromarray(v.clip(0, 255).astype("uint8"))


@pytest.mark.parametrize("rect", [(40, 90, 1000, 1208), (0, 0, 1100, 1329), (70, 20, 900, 1087)])
def test_register_recovers_the_crop(rect):
    hd = painting(1140, 1420, seed=rect[0] + 1)
    ncc, (x, y, w, h) = B.register(hd, vanilla_from(hd, rect))
    assert ncc > 0.9
    assert abs(x - rect[0]) < 12 and abs(y - rect[1]) < 12 and abs(w - rect[2]) < 25


@pytest.mark.parametrize("rect,img", [((10.4, 30.2, 1000.0, 1208.0), (1100, 1400)),
                                      ((-8.0, 0.0, 1120.0, 1353.0), (1110, 1350)),
                                      ((0.0, 0.0, 2000.0, 2416.0), (1100, 1400))])
def test_crop_rect_is_the_interior_aspect_inside_the_image(rect, img):
    (x, y, w, h), over = B.crop_rect(rect, *img)
    assert 0 <= x and 0 <= y and x + w <= img[0] and y + h <= img[1]
    assert abs(w * B.INTERIOR[3] - h * B.INTERIOR[2]) <= B.INTERIOR[3]   # aspect to within a pixel
    if rect[0] < 0:
        assert over > 0


def _fake_sources(tmp_path, monkeypatch, leaders, bad=()):
    src = tmp_path / "src"
    src.mkdir()
    vans = {}
    for n, fac in leaders.items():
        hd = painting(1136, 1384, seed=n)
        hd.save(src / f"alpha centauri ({n}).png")
        vans[fac] = vanilla_from(painting(1136, 1384, seed=n + 99) if fac in bad else hd, (8, 14, 1120, 1353))
    monkeypatch.setattr(B, "LEADERS", leaders)
    monkeypatch.setattr(B, "vanilla_interior", lambda fac: vans[fac])
    return src


def test_build_writes_pack_manifest_and_provenance(tmp_path, monkeypatch):
    src = _fake_sources(tmp_path, monkeypatch, {1: "gaians", 2: "hive"})
    prov = tmp_path / "prov.txt"
    prov.write_text("Art: test source. Licence: test.\n", encoding="utf-8")
    out = tmp_path / "out"
    assert B.build(src, out, prov, dry_run=False) == 0
    assert sorted(p.name for p in out.iterdir()) == ["PROVENANCE.txt", "gaians.png", "hive.png", "pack-manifest.json"]
    doc = json.loads((out / "pack-manifest.json").read_text(encoding="utf-8"))
    assert doc["pack"] == "portraits-hd" and doc["file_count"] == 2
    for f in doc["files"]:
        p = out / f["name"]
        assert f["sha256"] == B.sha256_file(p) and f["size"] == p.stat().st_size
        w, h = Image.open(p).size
        assert abs(w * B.INTERIOR[3] - h * B.INTERIOR[2]) <= B.INTERIOR[3]
    assert (out / "PROVENANCE.txt").read_text(encoding="utf-8").startswith("Art: test source")


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    src = _fake_sources(tmp_path, monkeypatch, {1: "gaians"})
    assert B.build(src, tmp_path / "out", None, dry_run=True) == 0
    assert not (tmp_path / "out").exists()


def test_refuses_without_provenance(tmp_path, monkeypatch):
    src = _fake_sources(tmp_path, monkeypatch, {1: "gaians"})
    with pytest.raises(SystemExit, match="provenance"):
        B.build(src, tmp_path / "out", None, dry_run=False)


def test_refuses_a_wrong_image_and_a_missing_one(tmp_path, monkeypatch):
    src = _fake_sources(tmp_path, monkeypatch, {1: "gaians", 2: "hive"}, bad=("hive",))
    with pytest.raises(SystemExit, match="hive: registration NCC"):
        B.build(src, tmp_path / "out", None, dry_run=True)
    (src / "alpha centauri (1).png").unlink()
    with pytest.raises(SystemExit, match="missing source"):
        B.build(src, tmp_path / "out", None, dry_run=True)


def test_refuses_stray_files_in_the_output(tmp_path, monkeypatch):
    src = _fake_sources(tmp_path, monkeypatch, {1: "gaians"})
    out = tmp_path / "out"
    out.mkdir()
    (out / "Thumbs.db").write_bytes(b"x")
    prov = tmp_path / "prov.txt"
    prov.write_text("p", encoding="utf-8")
    with pytest.raises(SystemExit, match="unexpected files"):
        B.build(src, out, prov, dry_run=False)


def test_leader_table_is_the_fourteen_stock_factions():
    assert sorted(B.LEADERS.values()) == sorted(
        ["gaians", "hive", "univ", "morgan", "spartans", "believe", "peace",
         "cyborg", "pirates", "drone", "angels", "fungboy", "caretake", "usurper"])



def test_refuses_two_sources_swapped_between_leaders(tmp_path, monkeypatch):
    """A mis-numbered source (gaians' image filed as hive's and the reverse) must be refused: each image matches
    the OTHER leader's vanilla art better than its own."""
    src = tmp_path / "src"
    src.mkdir()
    a, b = painting(1136, 1384, seed=1), painting(1136, 1384, seed=2)
    a.save(src / "alpha centauri (1).png")       # filed as gaians ...
    b.save(src / "alpha centauri (2).png")       # ... filed as hive
    vans = {"gaians": vanilla_from(b, (8, 14, 1120, 1353)), "hive": vanilla_from(a, (8, 14, 1120, 1353))}
    monkeypatch.setattr(B, "LEADERS", {1: "gaians", 2: "hive"})
    monkeypatch.setattr(B, "vanilla_interior", lambda fac: vans[fac])
    with pytest.raises(SystemExit, match="also matches|registration NCC"):
        B.build(src, tmp_path / "out", None, dry_run=True)


def test_crop_rect_keeps_the_aspect_and_reports_overhang_when_too_tall():
    (x, y, w, h), over = B.crop_rect((0.0, -50.0, 1242.0, 1500.0), 1300, 1400)
    assert h <= 1400 and abs(w * B.INTERIOR[3] - h * B.INTERIOR[2]) <= B.INTERIOR[3]
    assert over > 0.02                              # 50 px above + the rest below: refused by MAX_OVERHANG


def test_only_is_dry_run_only(tmp_path):
    with pytest.raises(SystemExit):
        B.main(["--only", "gaians", "--src", str(tmp_path), "--out", str(tmp_path / "o")])
