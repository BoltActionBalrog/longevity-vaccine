"""The preflight gate and the transactional commit.

THE PROPERTY UNDER TEST, for every abort condition: the function returns a blocker **and the game
directory is byte-identical afterwards**. "Prints an error" is not the requirement; "changes
nothing" is. So each case snapshots the whole directory tree (name, size, md5) before and after
and compares.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent.parent
_SCRIPTS = _REPO / "work" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import apply_patches as ap    # noqa: E402
import manifest as mf         # noqa: E402
import preflight as pfm       # noqa: E402
import sign_manifest as sm    # noqa: E402
import transact as tx         # noqa: E402
import version as ver         # noqa: E402

SEED = bytes(range(32))
PK_HEX = sm.public_key(SEED).hex()
PATCHES = _REPO / "work" / "patches" / "patches.yaml"


def snapshot(root: Path) -> dict:
    """name -> (size, md5) for every file under root. The equality this suite asserts."""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            b = p.read_bytes()
            out[str(p.relative_to(root))] = (len(b), hashlib.md5(b).hexdigest())
    return out


@pytest.fixture
def game(tmp_path, bak_path):
    """A throwaway game dir holding a clean PRACX base as both the exe and its .bak."""
    g = tmp_path / "game"
    g.mkdir()
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    shutil.copy2(bak_path, g / "terranx_PRACX.exe.bak")
    (g / "Alpha Centauri.ini").write_text("[UIMod]\nUpscaledVideos=1\n", encoding="ascii")
    return g


@pytest.fixture
def table():
    return ap.load_targets(PATCHES)


def _doc(**over) -> dict:
    d = {
        "schema": 1, "protocol": 1, "product": "longevity-vaccine",
        "latest": "2.0.0", "min_upgradable_from": "1.0.0",
        "manual_install_required": False, "manual_install_reason": None,
        "unsupported_versions": [], "unsupported_targets": [], "yanked": [],
        "min_free_bytes": 1 << 20,
        "modules": {},
    }
    d.update(over)
    return d


def _signed(doc):
    raw = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
    return raw, sm.sign(SEED, raw).hex()


# ---------------------------------------------------------------- the happy path

def test_a_clean_install_passes_preflight_and_changes_nothing(game, table):
    before = snapshot(game)
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES,
                 table=table, min_free_bytes=1 << 20)
    assert pf.ok, [c.detail for c in pf.blockers]
    assert pf.spec.id == "pracx"
    assert snapshot(game) == before, "preflight modified the game directory"


# ---------------------------------------------------------------- abort conditions

def test_a_missing_game_dir_blocks(tmp_path, table):
    pf = pfm.run(game_dir=tmp_path / "nope", target=tmp_path / "nope" / "t.exe",
                 patches=PATCHES, table=table)
    assert not pf.ok
    assert any("game directory" in c.name for c in pf.blockers)


def test_a_missing_target_blocks(game, table):
    (game / "terranx_PRACX.exe").unlink()
    before = snapshot(game)
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES, table=table)
    assert not pf.ok
    assert snapshot(game) == before


def test_an_unsupported_backup_blocks(game, table):
    (game / "terranx_PRACX.exe.bak").write_bytes(b"not a known base")
    before = snapshot(game)
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES, table=table)
    assert not pf.ok
    assert any("supported clean base" in c.name for c in pf.blockers)
    assert snapshot(game) == before


def test_crossing_targets_blocks(game, table):
    """Installing Thinker after our mod changes the base under the same filename."""
    before = snapshot(game)
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES,
                 table=table, receipt_target_id="thinker")
    assert not pf.ok
    assert any("has not changed" in c.name for c in pf.blockers)
    assert snapshot(game) == before


def test_insufficient_space_blocks(game, table):
    before = snapshot(game)
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES,
                 table=table, min_free_bytes=1 << 60)
    assert not pf.ok
    assert any("disk space" in c.name for c in pf.blockers)
    assert snapshot(game) == before


def test_a_bad_manifest_signature_blocks(game, table):
    raw, _ = _signed(_doc())
    before = snapshot(game)
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES, table=table,
                 manifest_raw=raw, manifest_sig="00" * 64, installed_version="1.0.0",
                 public_key_hex=PK_HEX)
    assert not pf.ok
    assert any("signature" in c.name for c in pf.blockers)
    assert snapshot(game) == before


def test_a_kill_switched_manifest_blocks_with_the_compiled_url(game, table):
    raw, sig = _signed(_doc(manual_install_required=True,
                            manual_install_reason="bootstrap_defect"))
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES, table=table,
                 manifest_raw=raw, manifest_sig=sig, installed_version="1.0.0",
                 public_key_hex=PK_HEX)
    assert not pf.ok
    blocker = next(c for c in pf.blockers if "automatically" in c.name)
    assert mf.DOWNLOAD_URL in blocker.detail
    assert pf.decision.action == mf.MANUAL


def test_a_version_below_min_upgradable_from_blocks(game, table):
    raw, sig = _signed(_doc(min_upgradable_from="1.5.0"))
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES, table=table,
                 manifest_raw=raw, manifest_sig=sig, installed_version="1.0.0",
                 public_key_hex=PK_HEX)
    assert not pf.ok


def test_a_module_missing_from_the_manifest_blocks(game, table):
    raw, sig = _signed(_doc())
    before = snapshot(game)
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES, table=table,
                 manifest_raw=raw, manifest_sig=sig, installed_version="1.0.0",
                 wanted_modules=["base"], public_key_hex=PK_HEX)
    assert not pf.ok
    assert any("module base" in c.name for c in pf.blockers)
    # staging may be created; no GAME file may change
    assert {k: v for k, v in snapshot(game).items() if "LongevityMods" not in k} == before


def test_a_module_whose_hash_is_wrong_blocks(game, table, tmp_path):
    payload = tmp_path / "base-2.0.0.zip"
    import zipfile
    with zipfile.ZipFile(payload, "w") as z:
        z.writestr("hello.txt", "hi")
    doc = _doc(modules={"base": {"version": "2.0.0", "required": True,
                                 "url": payload.as_uri(), "sha256": "0" * 64,
                                 "size": payload.stat().st_size}})
    raw, sig = _signed(doc)
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES, table=table,
                 manifest_raw=raw, manifest_sig=sig, installed_version="1.0.0",
                 wanted_modules=["base"], public_key_hex=PK_HEX, allow_file=True)
    assert not pf.ok
    assert any("download" in c.name for c in pf.blockers)


def test_a_verified_module_is_staged(game, table, tmp_path):
    import zipfile
    payload = tmp_path / "base-2.0.0.zip"
    with zipfile.ZipFile(payload, "w") as z:
        z.writestr("hello.txt", "hi")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    doc = _doc(modules={"base": {"version": "2.0.0", "required": True,
                                 "url": payload.as_uri(), "sha256": digest,
                                 "size": payload.stat().st_size}})
    raw, sig = _signed(doc)
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES, table=table,
                 manifest_raw=raw, manifest_sig=sig, installed_version="1.0.0",
                 wanted_modules=["base"], public_key_hex=PK_HEX, allow_file=True)
    assert pf.ok, [c.detail for c in pf.blockers]
    assert "base" in pf.staged and pf.staged["base"].is_file()


def test_a_corrupt_archive_blocks(game, table, tmp_path):
    payload = tmp_path / "base-2.0.0.zip"
    payload.write_bytes(b"PK\x03\x04 definitely not a real zip")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    doc = _doc(modules={"base": {"version": "2.0.0", "required": True,
                                 "url": payload.as_uri(), "sha256": digest,
                                 "size": payload.stat().st_size}})
    raw, sig = _signed(doc)
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES, table=table,
                 manifest_raw=raw, manifest_sig=sig, installed_version="1.0.0",
                 wanted_modules=["base"], public_key_hex=PK_HEX, allow_file=True)
    assert not pf.ok
    assert any("readable archive" in c.name for c in pf.blockers)


def test_every_blocker_leaves_the_report_readable(game, table):
    pf = pfm.run(game_dir=game, target=game / "nope.exe", patches=PATCHES, table=table)
    lines = []
    pf.report(say=lines.append)
    assert lines and any("FAIL" in ln for ln in lines)


# ---------------------------------------------------------------- transactional commit

def test_commit_never_writes_to_the_backup(game, table, tmp_path):
    """.bak is the one file a player cannot afford to lose, and the update path must not touch
    it -- the old restore-then-patch shape wrote to the live exe via the backup."""
    bak = game / "terranx_PRACX.exe.bak"
    bak_before = (bak.stat().st_size, hashlib.md5(bak.read_bytes()).hexdigest())
    spec = table["pracx"]
    tx.apply_transactional(game / "terranx_PRACX.exe", PATCHES, spec, tmp_path / "work")
    assert (bak.stat().st_size, hashlib.md5(bak.read_bytes()).hexdigest()) == bak_before


def test_commit_produces_the_locked_hash(game, table, tmp_path):
    spec = table["pracx"]
    out = tx.apply_transactional(game / "terranx_PRACX.exe", PATCHES, spec, tmp_path / "work")
    assert out["terranx_PRACX.exe"] == spec.patched_md5
    live = hashlib.md5((game / "terranx_PRACX.exe").read_bytes()).hexdigest()
    assert live == spec.patched_md5


def test_a_staged_hash_mismatch_aborts_before_the_live_file_is_touched(game, table, tmp_path):
    live = game / "terranx_PRACX.exe"
    before = hashlib.md5(live.read_bytes()).hexdigest()
    spec = ap.TargetSpec("pracx", {
        "label": "PRACX", "exe": "terranx_PRACX.exe", "launch": True,
        "base_md5": table["pracx"].base_md5, "base_size": table["pracx"].base_size,
        "groups": "all", "patched_md5": "deadbeef" * 4})
    with pytest.raises(tx.CommitError):
        tx.apply_transactional(live, PATCHES, spec, tmp_path / "work")
    assert hashlib.md5(live.read_bytes()).hexdigest() == before, "the live exe was modified"


def test_commit_refuses_a_missing_staged_file_before_any_swap(game, table, tmp_path):
    live = game / "terranx_PRACX.exe"
    before = hashlib.md5(live.read_bytes()).hexdigest()
    with pytest.raises(tx.CommitError, match="staged file missing"):
        tx.commit([(live, tmp_path / "work" / "absent.exe")])
    assert hashlib.md5(live.read_bytes()).hexdigest() == before


def test_commit_refuses_an_unwritable_destination_before_any_swap(game, table, tmp_path):
    """Every destination is proven writable before the FIRST swap, so a permissions problem on
    the second file cannot leave the first one already replaced."""
    live = game / "terranx_PRACX.exe"
    cand = tx.stage_one(live, PATCHES, table["pracx"], tmp_path / "work")
    before = hashlib.md5(live.read_bytes()).hexdigest()

    # A directory where a file is expected cannot be opened "r+b" -- a portable stand-in for a
    # locked or read-only destination.
    blocked = game / "blocked.dll"
    blocked.mkdir()
    second = tmp_path / "work" / "blocked.dll"
    second.write_bytes(b"staged")

    with pytest.raises(tx.CommitError, match="not writable"):
        tx.commit([(live, cand), (blocked, second)])
    assert hashlib.md5(live.read_bytes()).hexdigest() == before, \
        "the first file was swapped even though the second destination was unusable"


def test_a_failed_swap_rolls_back_earlier_ones(game, table, tmp_path, monkeypatch):
    """All of them commit or none do: a patched exe paired with an unpatched companion is a
    combination nobody has tested."""
    live = game / "terranx_PRACX.exe"
    companion = game / "companion.dll"
    companion.write_bytes(b"original companion")
    before_live = hashlib.md5(live.read_bytes()).hexdigest()

    cand1 = tx.stage_one(live, PATCHES, table["pracx"], tmp_path / "work")
    cand2 = tmp_path / "work" / "companion.dll"
    cand2.write_bytes(b"new companion")

    real_replace = Path.replace
    calls = {"n": 0}

    def flaky(self, target):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated failure on the second swap")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    with pytest.raises(tx.CommitError, match="rolled back"):
        tx.commit([(live, cand1), (companion, cand2)])
    monkeypatch.undo()

    assert hashlib.md5(live.read_bytes()).hexdigest() == before_live, \
        "the first swap was not rolled back"
    assert companion.read_bytes() == b"original companion"


def test_a_foreign_live_exe_is_refused_rather_than_overwritten(game, table):
    """THE destroy-a-binary case: preflight used to hash only the .bak, so a live exe we did not
    make -- a newer PRACX, a Thinker build, anything the player swapped in -- passed and was then
    replaced by a build patched from the .bak, destroying it with no backup of ITS bytes."""
    foreign = b"MZ" + b"\x00" * 4096
    (game / "terranx_PRACX.exe").write_bytes(foreign)
    before = snapshot(game)
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES,
                 table=table, min_free_bytes=1 << 20)
    assert not pf.ok
    assert any("live executable" in c.name for c in pf.blockers)
    assert snapshot(game) == before
    assert (game / "terranx_PRACX.exe").read_bytes() == foreign


def test_an_already_patched_live_exe_is_accepted(game, table, tmp_path):
    """The counterpart: our OWN patched build must still pass, or no update could ever run."""
    tx.apply_transactional(game / "terranx_PRACX.exe", PATCHES, table["pracx"], tmp_path / "w")
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES,
                 table=table, min_free_bytes=1 << 20)
    assert pf.ok, [c.detail for c in pf.blockers]
    assert any(c.name == "live executable is ours or the clean base" and c.ok for c in pf.checks)


@pytest.mark.parametrize("whose", ["pracx", "pracx_thinker"])
def test_an_earlier_releases_build_is_ours_by_the_history(game, table, whose):
    """patched_md5 changes with every release: the build an EARLIER release left on the player's
    disk is ours through the target's `known_patched` history -- this configuration's or a
    sibling's on the same base. Without it every in-game update from one release to the next was
    refused as "a binary we did not make" (audit 2026-11-01)."""
    older = b"MZ an earlier release's build" + b"\x00" * 4096
    (game / "terranx_PRACX.exe").write_bytes(older)
    md5 = hashlib.md5(older).hexdigest()
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES,
                 table=table, min_free_bytes=1 << 20)
    assert not pf.ok, "an unrecorded build must still be refused"
    table[whose].known_patched = table[whose].known_patched + [md5]
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES,
                 table=table, min_free_bytes=1 << 20)
    assert pf.ok, [c.detail for c in pf.blockers]


def test_the_shipped_builds_are_in_the_history(table):
    """What 0.1.0 and 0.2.0 shipped (their signed manifests' `targets`), recorded for good."""
    assert {"ed30ac8bc96b6f30dc1ba4e1461b97bd", "677a55d5b96c51750a27a72df8dffe74"} <= table["pracx"].builds
    assert "c4c0240a057878fbc530dd6acf02a2c6" in table["pracx_thinker"].builds


def test_run_returns_blockers_instead_of_raising(game, table, monkeypatch):
    """A crashed check is a blocker, not a traceback -- returning a Preflight is the contract,
    and an exception escaping sends a read-only game dir to the crash handler instead."""
    def boom(*a, **k):
        raise OSError("simulated staging failure")
    monkeypatch.setattr(pfm.fetch, "staging_dir", boom)
    raw, sig = _signed(_doc(modules={"movies-hd": {"version": "2.0.0", "url": "https://x/y.zip",
                                                   "sha256": "0" * 64, "size": 1}}))
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES, table=table,
                 manifest_raw=raw, manifest_sig=sig, installed_version="1.0.0",
                 wanted_modules=["movies-hd"], public_key_hex=PK_HEX)
    assert not pf.ok
    assert isinstance(pf, pfm.Preflight)        # a Preflight came back at all
    assert any("preflight completed" in c.name or "modules" in c.name for c in pf.blockers)


@pytest.mark.parametrize("url,expected", [
    ("https://h/v1/LV-movies-hd-1.0.0.zip", "LV-movies-hd-1.0.0.zip"),
    ("https://h/C:evil.zip", "Cevil.zip"),                 # drive-relative: would escape staging
    ("https://h/x.zip:ads", "x.zipads"),                   # alternate data stream
    ("https://h/..", "movies-hd.zip"),
    ("https://h/.~", "movies-hd.zip"),                     # reduced to "." = the staging DIR
    ("https://h/../../x.zip", "x.zip"),
    ("https://h/", "movies-hd.zip"),
    ("https://h/%2e%2e/y.zip", "y.zip"),
    (None, "movies-hd.zip"),
    (5, "movies-hd.zip"),
    ("https://h/évil.zip", "vil.zip"),
    ("https://h/CON", "movies-hd.zip"),                    # a device, on any Windows
    ("https://h/nul.zip", "movies-hd.zip"),
    ("https://h/COM1.zip", "movies-hd.zip"),
    ("https://h/manifest.json", "movies-hd.zip"),          # our own verified cache
    ("https://h/Manifest.JSON.sig", "movies-hd.zip"),
])
def test_the_staging_file_name_is_taken_apart_never_trusted(url, expected):
    """`Path(url).name` let a signed manifest choose `C:evil.zip`, which joined onto a D: staging
    dir is a path on drive C -- and fetch.download deletes a same-named file there when the hash
    differs. Every module stages in its own folder, so two modules whose URLs end in the same
    name cannot replace each other's verified archive. The bootstrap uses this for `base`."""
    assert pfm.staging_name(url, "movies-hd") == "movies-hd/" + expected
    fallback = expected == "movies-hd.zip"
    assert pfm.staging_name(url, "base") == "base/" + ("base.zip" if fallback else expected)


def test_two_modules_never_share_a_staging_path():
    a = pfm.staging_name("https://h/pack.zip", "movies-hd")
    b = pfm.staging_name("https://h/pack.zip", "portraits-hd")
    assert a != b and Path(a).name == Path(b).name == "pack.zip"


def test_explicit_modules_add_to_the_stale_set_and_a_missing_one_blocks(game, table):
    """`--modules portraits-hd` must not REPLACE a stale movies-hd (it was announced as "already
    current" and left behind), and asking for a pack the manifest does not offer is a blocker,
    not a warning followed by UPDATE COMPLETE."""
    raw, sig = _signed(_doc(latest="1.0.0", modules={
        "movies-hd": {"version": "2.0.0", "url": "https://x/y.zip", "sha256": "0" * 64,
                      "size": 1}}))
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES, table=table,
                 manifest_raw=raw, manifest_sig=sig, installed_version="1.0.0",
                 wanted_modules=["portraits-hd"], installed_modules={"movies-hd": "1.0.0"},
                 public_key_hex=PK_HEX, labels={"portraits-hd": "Turovetsky's HD Portrait Pack"})
    assert pf.wanted == ["portraits-hd", "movies-hd"]
    assert any(c.name == "Turovetsky's HD Portrait Pack: not released yet" for c in pf.blockers), pf.checks
    # movies-hd was attempted (an https URL that does not resolve -> advisory, not a blocker)
    assert any("movies-hd" in c.name for c in pf.warnings), pf.checks


def test_a_missing_manifest_is_a_blocker_when_one_was_required(game, table):
    """A caller whose manifest fetch failed used to get a CLEAN preflight -- the signature,
    kill-switch and download checks all silently skipped."""
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES,
                 table=table, min_free_bytes=1 << 20, require_manifest=True)
    assert not pf.ok
    assert any("manifest available" in c.name for c in pf.blockers)


def test_the_write_probe_never_clobbers_an_existing_file(game, table, monkeypatch):
    """The victim has to be the EXACT path the probe will choose.

    This used to plant `.longevity-write-probe`, a name no version of the probe has ever
    written, so it passed just as happily against the old fixed-name `"wb"` probe that did
    truncate whatever it found. Pinning os.urandom makes the real path predictable.
    """
    monkeypatch.setattr(pfm.os, "urandom", lambda n: b"\xab" * n)
    victim = game / f".longevity-probe-{os.getpid()}-{(b'\xab' * 4).hex()}"
    victim.write_bytes(b"someone else's file")
    pf = pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES,
                 table=table, min_free_bytes=1 << 20)
    assert victim.read_bytes() == b"someone else's file", "the probe truncated a foreign file"
    assert any("writable" in c.name and not c.ok for c in pf.checks), \
        "an exclusive-create that hit the victim must report the directory as NOT writable"


def test_the_write_probe_cleans_up_after_itself(game, table):
    before = set(p.name for p in game.iterdir())
    pfm.run(game_dir=game, target=game / "terranx_PRACX.exe", patches=PATCHES,
            table=table, min_free_bytes=1 << 20)
    after = set(p.name for p in game.iterdir())
    assert not [n for n in after - before if n.startswith(".longevity-probe")]


def test_a_new_destination_is_removed_when_a_later_swap_fails(game, table, tmp_path, monkeypatch):
    """A file we CREATED has no .prev, and simply skipping it on rollback left a new companion
    installed beside a reverted exe -- the mixed state this is supposed to prevent."""
    live = game / "terranx_PRACX.exe"
    brand_new = game / "brand-new.dll"
    assert not brand_new.exists()
    cand1 = tx.stage_one(live, PATCHES, table["pracx"], tmp_path / "w")
    cand2 = tmp_path / "w" / "brand-new.dll"
    cand2.write_bytes(b"NEW")
    cand3 = tmp_path / "w" / "third.dll"
    cand3.write_bytes(b"THIRD")
    (game / "third.dll").write_bytes(b"ORIGINAL-3")

    before_live = hashlib.md5(live.read_bytes()).hexdigest()
    real = Path.replace
    n = {"i": 0}

    def flaky(self, t):
        n["i"] += 1
        if n["i"] == 3:
            raise OSError("boom on the third swap")
        return real(self, t)

    monkeypatch.setattr(Path, "replace", flaky)
    with pytest.raises(tx.CommitError):
        tx.commit([(live, cand1), (brand_new, cand2), (game / "third.dll", cand3)])
    monkeypatch.undo()

    assert hashlib.md5(live.read_bytes()).hexdigest() == before_live
    assert not brand_new.exists(), "a file we created was left behind after rollback"


def test_a_failed_rollback_is_reported_not_swallowed(game, table, tmp_path, monkeypatch):
    """The old code swallowed rollback errors and still said 'rolled back N files', so the user
    was told their install was reverted while the live file held the new bytes."""
    a, b = game / "a.dll", game / "b.dll"
    a.write_bytes(b"ORIGINAL-A")
    b.write_bytes(b"ORIGINAL-B")
    ca, cb = tmp_path / "ca.dll", tmp_path / "cb.dll"
    ca.write_bytes(b"NEW-A")
    cb.write_bytes(b"NEW-B")

    real_replace, real_copy = Path.replace, shutil.copy2
    n = {"i": 0}

    def flaky_replace(self, t):
        n["i"] += 1
        if n["i"] == 2:
            raise OSError("boom")
        return real_replace(self, t)

    def flaky_copy(src, dst, *a, **k):
        if str(dst).endswith(".rollback"):
            raise OSError("rollback copy denied")
        return real_copy(src, dst, *a, **k)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    monkeypatch.setattr(shutil, "copy2", flaky_copy)
    with pytest.raises(tx.CommitError, match="COULD NOT ROLL BACK"):
        tx.commit([(a, ca), (b, cb)])
    monkeypatch.undo()


def test_commit_refuses_a_cross_volume_staging_dir(game, table):
    """The commit is an atomic rename, which cannot cross volumes. With work_dir on %TEMP% (C:)
    and the game on D:, every commit failed at the very last step."""
    # A drive letter that is NOT the game's, whether or not it exists. The old form compared
    # tempfile.gettempdir() with the game dir -- but the `game` fixture IS under the temp
    # dir, so the drives always matched and this test skipped on every machine, leaving the
    # bug it names completely unprotected.
    drive = Path(game).resolve().drive.upper()
    other_letter = "Z:" if drive != "Z:" else "Y:"
    with pytest.raises(tx.CommitError, match="different volume"):
        tx.stage_one(game / "terranx_PRACX.exe", PATCHES, table["pracx"],
                     Path(other_letter + "\\xvol"))
    assert not (Path(other_letter + "\\xvol")).exists(), \
        "the refusal must come BEFORE the staging directory is created"


def test_a_wrong_clean_base_is_refused(game, table, tmp_path):
    (game / "terranx_PRACX.exe.bak").write_bytes(b"wrong base")
    (game / "terranx_PRACX.exe").write_bytes(b"also wrong")
    with pytest.raises(tx.CommitError, match="clean base"):
        tx.apply_transactional(game / "terranx_PRACX.exe", PATCHES, table["pracx"],
                               tmp_path / "work")
