"""Nothing the installer removes is ever removed through a link (user rule 2026-11-15, no exceptions): the remaining
unlinks after 1b70fc5 -- the patch-log pruning, the staged manifest and its .part/.sig, manifest-issued.txt, and the
download's own .part / dest (fetch.download refuses up front when a link is on the way, given the game folder).
Each written to fail first, with real junctions."""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch                        # noqa: E402
import install as inst              # noqa: E402
import thinker_flow as tf           # noqa: E402

pytestmark = [pytest.mark.usefixtures("install_globals"),
              pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions")]


def _junctioned_longevitymods(tmp_path) -> tuple:
    """<game>\\LongevityMods is a junction to a folder of the player's elsewhere."""
    import _winapi
    outside = tmp_path / "players"
    outside.mkdir()
    g = tmp_path / "game"
    g.mkdir()
    _winapi.CreateJunction(str(outside), str(g / "LongevityMods"))
    return g, outside


def test_patch_logs_are_never_pruned_through_a_link(tmp_path):
    g, outside = _junctioned_longevitymods(tmp_path)
    (outside / "logs").mkdir()
    names = [f"patch-2026010{i}-000000.log" for i in range(1, 9)]
    for n in names:
        (outside / "logs" / n).write_text("player's", encoding="ascii")
    assert inst.prune_logs(g / "LongevityMods" / "logs", "patch", keep=2) == 0
    assert all((outside / "logs" / n).is_file() for n in names)


def test_a_future_issued_file_is_never_discarded_through_a_link(tmp_path):
    g, outside = _junctioned_longevitymods(tmp_path)
    (outside / "manifest-issued.txt").write_text(str(int(time.time()) + 10 ** 7), encoding="ascii")
    tf.issued_floor(g)
    assert (outside / "manifest-issued.txt").is_file()


def test_the_staged_manifest_is_never_discarded_through_a_link(tmp_path):
    g, outside = _junctioned_longevitymods(tmp_path)
    (outside / "staging").mkdir()
    for n in ("manifest.json", "manifest.json.sig", "manifest.json.part"):
        (outside / "staging" / n).write_text("player's", encoding="ascii")
    inst.discard_staged_manifest(g)
    assert all((outside / "staging" / n).is_file() for n in ("manifest.json", "manifest.json.sig", "manifest.json.part"))


def test_a_download_in_the_game_folder_refuses_a_link_before_touching_anything(tmp_path):
    g, outside = _junctioned_longevitymods(tmp_path)
    (outside / "staging").mkdir()
    (outside / "staging" / "x.zip.part").write_text("player's", encoding="ascii")
    (outside / "staging" / "x.zip").write_text("player's", encoding="ascii")
    with pytest.raises(fetch.FetchError):
        fetch.download("https://example.invalid/x.zip", g / "LongevityMods" / "staging" / "x.zip",
                       sha256="0" * 64, size=1, root=g)
    assert (outside / "staging" / "x.zip.part").read_text() == "player's"
    assert (outside / "staging" / "x.zip").read_text() == "player's"


def _spy_download(monkeypatch) -> list:
    seen = []

    def spy(url, dest, **kw):
        seen.append(kw.get("root"))
        raise fetch.FetchError("stop")
    monkeypatch.setattr(fetch, "download", spy)
    return seen


def test_every_download_into_the_game_folder_names_the_game_folder(tmp_path, monkeypatch):
    """The Thinker zip, the packs (preflight), the new installer (bootstrap) and the manifest: each hands
    fetch.download the game folder, so the link check runs."""
    import bootstrap as bs
    import preflight as pfm
    g = tmp_path / "game"
    (g / "LongevityMods" / "staging" / "thinker").mkdir(parents=True)
    seen = _spy_download(monkeypatch)
    with pytest.raises(Exception):
        tf.prepare(g, tf.compiled_pin(), tf.compiled_meta(), "1.0.0", route="B", fresh=True)
    pf = types.SimpleNamespace(add=lambda *a, **k: True)
    doc = {"modules": {"movies-hd": {"version": "1.0.0", "url": "https://x/m.zip", "sha256": "0" * 64, "size": 1}}}
    pfm.check_archives(pf, doc, g / "LongevityMods" / "staging", ["movies-hd"])
    with pytest.raises(Exception):
        bs._download_new_payload(g, {"url": "https://x/i.zip", "sha256": "0" * 64, "size": 1}, "9.9.9",
                                 types.SimpleNamespace(manifest=None))
    with pytest.raises(Exception):
        inst.fetch_manifest(g)
    assert seen and all(r is not None and Path(r) == g for r in seen), seen


def test_fetching_the_manifest_never_clears_a_part_through_a_link(tmp_path, monkeypatch):
    """fetch_manifest starts every manifest download clean by removing the .part files first: never through a link."""
    g, outside = _junctioned_longevitymods(tmp_path)
    (outside / "staging").mkdir()
    for n in ("manifest.json.part", "manifest.json.sig.part"):
        (outside / "staging" / n).write_text("player's", encoding="ascii")
    _spy_download(monkeypatch)
    with pytest.raises(Exception):
        inst.fetch_manifest(g)
    assert all((outside / "staging" / n).is_file() for n in ("manifest.json.part", "manifest.json.sig.part"))


def test_the_link_refusal_reads_as_approved_and_names_the_link(tmp_path):
    """User-approved 2026-11-15: "<folder> is a link to another folder, so nothing was downloaded there." -- the
    folder named is the link itself (here LongevityMods), not whatever lies under it -- in full, however long the
    game folder's path (a 120-character cut once ended it at "Longevit...")."""
    import _winapi
    g = tmp_path / ("Sid Meier's Alpha Centauri Planetary Pack " * 3).strip()
    g.mkdir()
    (tmp_path / "players").mkdir()
    _winapi.CreateJunction(str(tmp_path / "players"), str(g / "LongevityMods"))
    assert len(str(g / "LongevityMods")) > 120
    with pytest.raises(fetch.FetchError) as e:
        fetch.download("https://example.invalid/x.zip", g / "LongevityMods" / "staging" / "x.zip",
                       sha256="0" * 64, size=1, root=g)
    assert str(e.value) == f"{g / 'LongevityMods'} is a link to another folder, so nothing was downloaded there."
