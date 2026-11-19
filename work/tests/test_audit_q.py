"""Audit-q (2026-11-17, an antagonistic audit of 4729b38): the fixes triaged for the user. Each test written to fail
first.

M1: an uninstall from a .partial alone deletes a listed file only when its size AND sha256 match the .partial's entry
    (provably the file the installer placed); anything else stays, and so does the .partial.
M2: a .partial makes the run fetch the manifest, so unattended and NUL-stdin runs complete the pack too (the real
    flow, a signed test manifest, the network stubbed).
M3: a pack a run chose whose download or placing did not finish is recorded as pending (no archive needed); the next
    run starts it ticked and completes it; never a keep, adopt or lock; --check still offers it.
L1: nothing is written through a junction.  L2: an empty or non-dict list is unreadable.  L4: release.py refuses
    case and trailing-dot variants.  Q13: the lists stay while a listed file remains."""
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
import manifest as mf               # noqa: E402
import receipt as rc                # noqa: E402
import release as rel               # noqa: E402
import sign_manifest as sm          # noqa: E402
from test_audit_n import PROV, _game, _setup_rest  # noqa: E402
from test_audit_p import PARTIAL, _archive, _failed_portraits, _manifest_bytes, _rerun_game  # noqa: E402
from test_check import _doc as _check_doc  # noqa: E402
from test_install_portraits import _junction  # noqa: E402
from test_rerun_pack_defaults import _cat  # noqa: E402
from test_setup_pack_rerun import CLIPS, PORTRAITS, _keys, _pack  # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")

SEED = bytes(range(32))


# ---------------------------------------------------------------- M1: only what the .partial proves is ours

def _killed_first_install(game: Path) -> Path:
    """K7: a first install of the Cinematics stopped after angels.mp4; intro.mp4 is the player's own clip."""
    root = game / "movies" / "hd"
    root.mkdir(parents=True)
    (root / "angels.mp4").write_bytes(CLIPS["angels.mp4"])
    (root / "intro.mp4").write_bytes(b"the player's own intro")
    (root / PARTIAL).write_bytes(_manifest_bytes("movies-hd", CLIPS))
    return root


def test_uninstall_from_a_partial_deletes_only_the_files_it_placed(tmp_path, capsys):
    game = _game(tmp_path)
    root = _killed_first_install(game)
    (root / f"angels.mp4.tmp-{1234}").write_bytes(b"half")               # our own extract's leftover
    (root / "angels.mp4.tmp-x").write_bytes(b"not ours")                 # not our naming pattern
    removed, failed = inst.remove_pack(game, "movies-hd")
    assert (root / "intro.mp4").read_bytes() == b"the player's own intro"
    assert not (root / "angels.mp4").exists() and not (root / "angels.mp4.tmp-1234").exists()
    assert (root / "angels.mp4.tmp-x").is_file()
    # audit-r MEDIUM-2 a: the .partial goes all the same (it used to stay, and later drove an install over the player's
    # own file); the unproven file stays, and "removed" is not said
    assert not (root / PARTIAL).exists()
    assert "removed Z2k Retro's HD Cinematics" not in capsys.readouterr().out


def test_a_later_uninstall_finishes_once_the_player_moved_their_file(tmp_path):
    game = _game(tmp_path)
    root = _killed_first_install(game)
    inst.remove_pack(game, "movies-hd")
    (root / "intro.mp4").unlink()
    inst.remove_pack(game, "movies-hd")
    assert not root.exists()


def test_the_complete_manifest_path_is_unchanged(tmp_path):
    """The user's earlier ruling: a pack with its real manifest is removed by name."""
    game = _game(tmp_path)
    root = _pack(game, "movies-hd", CLIPS)
    (root / "intro.mp4").write_bytes(b"changed by the player, same name")
    inst.remove_pack(game, "movies-hd")
    assert not root.exists()


# ---------------------------------------------------------------- Q13 and L2: never "removed" while files remain

def test_the_lists_stay_while_a_listed_file_could_not_be_removed(tmp_path, monkeypatch):
    game = _game(tmp_path)
    root = _pack(game, "movies-hd", CLIPS)
    (root / PARTIAL).write_bytes((root / "pack-manifest.json").read_bytes())
    import safe_fs
    real = safe_fs.unlink_entitled

    def held(p, *a, **k):
        if Path(p).name == "intro.mp4":
            raise OSError("in use")
        return real(p, *a, **k)
    monkeypatch.setattr(safe_fs, "unlink_entitled", held)
    removed, failed = inst.remove_pack(game, "movies-hd")
    assert failed == 1 and (root / "intro.mp4").is_file()
    assert (root / "pack-manifest.json").is_file() and (root / PARTIAL).is_file()


@pytest.mark.parametrize("doc", ["[]", "{}", '"x"', "null", '{"clips": []}', '{"files": []}'])
def test_an_empty_or_non_dict_partial_is_unreadable(tmp_path, capsys, doc):
    game = _game(tmp_path)
    root = _failed_portraits(game)
    (root / PARTIAL).write_text(doc, encoding="utf-8")
    (root / "PROVENANCE.txt").write_bytes(PROV)
    assert inst.remove_pack(game, "portraits-hd") == (0, 0)
    out = capsys.readouterr().out
    assert "could not be read" in out and "removed" not in out and inst._PACKS_UNREAD == ["portraits-hd"]
    assert (root / PARTIAL).is_file() and (root / "PROVENANCE.txt").is_file() and (root / "caretake.png").is_file()


# ---------------------------------------------------------------- M2: unattended and NUL runs fetch for a .partial

def _signed(tmp_path: Path, monkeypatch, modules: dict) -> list:
    """A manifest signed with a test key the client is told to trust; fetch_manifest stubbed to serve it."""
    doc = _check_doc(base=inst.ver.VERSION, **modules)
    doc["latest"] = inst.ver.VERSION
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    sig = sm.sign_file(SEED, m)
    monkeypatch.setattr(mf, "PUBLIC_KEY_HEX", sm.public_key(SEED).hex())
    fetched = []
    monkeypatch.setattr(inst, "fetch_manifest",
                        lambda *a, **k: fetched.append(1) or (m.read_bytes(), Path(sig).read_text().strip()))
    return fetched


def _unattended(monkeypatch):
    monkeypatch.setattr(ix, "has_console", lambda: False)
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    monkeypatch.setattr(inst, "_thinker_off_pin", lambda g: False)
    empty = Path(str(inst.payload_root())) / "no-such-dist"
    monkeypatch.setattr(inst, "default_pack", lambda: empty)
    monkeypatch.setattr(inst, "default_portrait_pack", lambda: empty)


def _args(**kw):
    return types.SimpleNamespace(**{"pack": None, "portrait_pack": None, "ai": "ask", "modules": None,
                                    "no_prompt": False, "manifest": None, "offline": False, **kw})


def test_an_unattended_rerun_fetches_and_completes_a_partial_pack(tmp_path, monkeypatch):
    game = _rerun_game(tmp_path)
    _failed_portraits(game)
    _unattended(monkeypatch)
    fetched = _signed(tmp_path, monkeypatch, {"portraits-hd": "1.0.0"})
    cat, manifest = inst.module_catalogue(game, _args())
    assert fetched and manifest is not None and "portraits-hd" in cat
    chosen, _down, _t = inst.pick_modules(cat, _args(), game)
    assert chosen == ["portraits-hd"]
    downloads = _setup_rest(game, monkeypatch, cat, chosen, [])
    assert downloads == [["portraits-hd"]]


# ---------------------------------------------------------------- M3: a pack whose download did not finish

def _remote_cat(game) -> dict:
    return {n: {"size": 1, "source": "manifest", "version": "1.0.0", "on_disk": inst.pack_on_disk(game, n),
                "locked": False, "release_manifest": None, "release_provenance": None}
            for n in ("movies-hd", "portraits-hd")}


def _failed_download(game, monkeypatch):
    """A setup run that chose the portrait pack and whose download failed."""
    monkeypatch.setattr(inst, "install_packs_from_manifest",
                        lambda g, a, names, *r: ({}, {n: "error" for n in names}))
    _got, status, _how = inst.place_packs(game, _args(), ["portraits-hd"], _remote_cat(game), ("r", "s", {}), None,
                                          game / "terranx.exe", {})
    assert status["portraits-hd"] == "error"


def test_a_failed_download_is_pending_and_the_next_run_starts_it_ticked(tmp_path, monkeypatch):
    game = _rerun_game(tmp_path)
    _failed_download(game, monkeypatch)
    assert inst.pack_pending(game, "portraits-hd") is True
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _keys(monkeypatch, "down", "down", "enter")
    assert inst.pick_modules(_remote_cat(game), _args(), game)[0] == ["portraits-hd"]


@pytest.mark.parametrize("how", ["no-prompt", "unattended"])
def test_no_prompt_and_unattended_runs_complete_a_pending_pack(tmp_path, monkeypatch, how):
    game = _rerun_game(tmp_path)
    _failed_download(game, monkeypatch)
    if how == "unattended":
        _unattended(monkeypatch)
        fetched = _signed(tmp_path, monkeypatch, {"portraits-hd": "1.0.0"})
        cat, _m = inst.module_catalogue(game, _args())
        assert fetched
    else:
        monkeypatch.setattr(ix, "can_ask", lambda: True)
        cat = _remote_cat(game)
    assert inst.pick_modules(cat, _args(no_prompt=how == "no-prompt"), game)[0] == ["portraits-hd"]


def test_success_clears_the_pending_mark(tmp_path, monkeypatch):
    game = _rerun_game(tmp_path)
    _failed_download(game, monkeypatch)
    inst.install_modules(game, {"portraits-hd": _archive(tmp_path, "portraits-hd", PORTRAITS)},
                         {"portraits-hd": "1.0.0"})
    assert inst.pack_pending(game, "portraits-hd") is False


def test_an_explicit_untick_clears_it_and_records_the_decline(tmp_path, monkeypatch):
    game = _rerun_game(tmp_path)
    _failed_download(game, monkeypatch)
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _keys(monkeypatch, "down", "enter", "down", "enter")                 # untick the portrait pack, then Continue
    chosen, turned_down, ticked = inst.pick_modules(_remote_cat(game), _args(), game)
    assert chosen == [] and turned_down == ["portraits-hd"]
    inst.record_module_choice(game, ticked, turned_down)
    assert inst.pack_pending(game, "portraits-hd") is False
    assert inst.NEW_PACK_PREFIX + "portraits-hd" in rc.declined(game)


def test_uninstall_clears_the_pending_mark(tmp_path, monkeypatch):
    game = _rerun_game(tmp_path)
    _failed_download(game, monkeypatch)
    inst.forget_pending_packs(game)
    assert inst.pack_pending(game, "portraits-hd") is False
    # that a real uninstall calls it: test_audit_r.test_uninstall_clears_the_pending_mark (behaviour, not source text)


def test_a_pending_pack_is_never_kept_adopted_or_locked(tmp_path, monkeypatch):
    """The marker alone never CAUSES a keep or an adopt, but no longer blocks a deserved one (audit-r L-a: a stale
    marker re-downloaded a complete pack every run); a .partial still blocks both."""
    game = _rerun_game(tmp_path)
    _pack(game, "portraits-hd", PORTRAITS)                               # complete on disk
    assert inst.pack_action(game, "portraits-hd", "1.0.0", "1.0.0") == "keep"
    _failed_download(game, monkeypatch)
    assert inst.pack_action(game, "portraits-hd", "1.0.0", "1.0.0") == "keep"
    root = game / "portraits" / "hd"
    (root / PARTIAL).write_bytes((root / "pack-manifest.json").read_bytes())
    assert inst.pack_action(game, "portraits-hd", "1.0.0", "1.0.0") == "repair"
    sha = hashlib.sha256((root / "pack-manifest.json").read_bytes()).hexdigest()
    (root / "PROVENANCE.txt").write_bytes(PROV)
    assert inst.pack_action(game, "portraits-hd", "1.0.0", inst.ver.UNKNOWN, sha,
                            hashlib.sha256(PROV).hexdigest()) == "install"


def test_check_still_offers_a_pending_pack(tmp_path, monkeypatch):
    game = _rerun_game(tmp_path)
    _failed_download(game, monkeypatch)
    doc = _check_doc(base="1.0.0", **{"portraits-hd": "1.0.0"})
    lines = inst.check_report(doc, rc.read(game), rc.declined(game))[1]
    assert any(ln.startswith("new=portraits-hd|") for ln in lines)


# ---------------------------------------------------------------- L1: nothing through a junction

def test_no_partial_is_written_through_a_junction(tmp_path):
    game = _game(tmp_path)
    (game / "portraits").mkdir()
    if not _junction(game / "portraits" / "hd", (game / "portraits").resolve()):
        pytest.skip("cannot create a junction here")
    inst.install_modules(game, {"portraits-hd": _archive(tmp_path, "portraits-hd", PORTRAITS)},
                         {"portraits-hd": "1.0.0"})
    assert not (game / "portraits" / PARTIAL).exists()
    assert inst._has_partial(game, "portraits-hd") is False and inst.pack_on_disk(game, "portraits-hd") is False


def test_a_partial_behind_a_junction_is_not_seen(tmp_path):
    game = _game(tmp_path)
    (game / "portraits").mkdir()
    (game / "portraits" / PARTIAL).write_bytes(_manifest_bytes("portraits-hd", PORTRAITS))   # planted earlier
    if not _junction(game / "portraits" / "hd", (game / "portraits").resolve()):
        pytest.skip("cannot create a junction here")
    assert inst._has_partial(game, "portraits-hd") is False and inst.pack_on_disk(game, "portraits-hd") is False


# ---------------------------------------------------------------- L4: release.py name variants

@pytest.mark.parametrize("variant", ["movies/hd/PACK-MANIFEST.json", "movies/hd/provenance.TXT",
                                     "movies/hd/pack-manifest.json.", "movies/hd/PROVENANCE.txt ",
                                     "MOVIES/HD/pack-manifest.json"])
def test_release_refuses_case_and_trailing_dot_variants(tmp_path, monkeypatch, variant):
    import version as ver
    monkeypatch.setitem(ver.PACK_MANIFEST_SHA256, "movies-hd", hashlib.sha256(b"{ok}").hexdigest())
    monkeypatch.setitem(ver.PACK_PROVENANCE_SHA256, "movies-hd", hashlib.sha256(PROV).hexdigest())
    p = tmp_path / "v.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("movies/hd/pack-manifest.json", b"{ok}")
        z.writestr("movies/hd/PROVENANCE.txt", PROV)
        z.writestr(variant, b"{bad}")
    with pytest.raises(SystemExit, match="REFUSING"):
        rel._check_pack_archive_compiled(p, "movies-hd")
