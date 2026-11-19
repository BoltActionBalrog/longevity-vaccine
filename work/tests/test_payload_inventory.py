"""Generation 2 owns its payload: whatever list an OLDER generation 1 copied the new release with, the payload that
becomes resident and runs the install is exactly the release's own file list.

The defect this pins (found live on 1.0.1, 2026-11-18): generation 1 is the previous release's frozen bootstrap.py,
and it staged the new archive with ITS `PAYLOAD` list. 1.0.0's list predates `art/pracx_icons_overlay.pcx`, so
every in-game 1.0.0 -> 1.0.1 update made a resident updater without PRACX's icon art -- and printed read-only
advice that could not help. No release check failed.

Now: release.py writes `scripts/payload_inventory.json` into the base archive (scripts/ is copied whole by every
shipped generation 1), and generation 2 completes its staged payload against it from the verified archive BEFORE
the swap (bootstrap.complete_payload). Pinned here:

  * the release archive carries an exact, deterministic inventory;
  * deploy() copies exactly the inventory (so a first install and every later generation 1 copy the archive,
    not a second list);
  * EVERY shipped generation 1 (0.1.0, 0.2.0, 0.2.1, 0.2.2, 1.0.0, 1.0.1 -- their real code, from the release
    commits) stages this release, and the CURRENT generation 2 then makes it exact -- canary files in a brand-new
    folder included;
  * completion fails CLOSED (nothing changed, nothing swapped) when it cannot be done;
  * every file install.py reads from its payload is in the inventory;
  * everything generation 2 imports lives under scripts/, the folder every generation 1 copies whole.

The shipped generations' sources come from git; a checkout without that history (the public source) skips them.
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import types
import zipfile
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent.parent
_SCRIPTS = _REPO / "work" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import bootstrap as bs        # noqa: E402
import installer_exit as ix   # noqa: E402
import manifest as mf         # noqa: E402
import sign_manifest as sm    # noqa: E402

SEED = bytes(range(32))
PK_HEX = sm.public_key(SEED).hex()
VERSION = "9.9.9"
CANARIES = ("newdir/sub/canary.txt", "art/canary.pcx")

#: Every shipped generation 1: the release commit and the git blob of the bootstrap.py its archive shipped (read
#: from dist\release\<v>\LongevityVaccine_<v>.zip), so a wrong commit is caught rather than silently tested.
SHIPPED = {
    "0.1.0": ("7a5c9fca80c260d5a7c8a3e0754ea697cc3a2c90", "3c7e4ac74d9bdb7d53981b3e0b34ca8a165daba8"),
    "0.2.0": ("a82e903cfd1aef547c309c23553ff05dad8a1e04", "367ab2eeaeb610c31cf3a55aade52f7a77361fcc"),
    "0.2.1": ("370fd2906c784cb9b9d4ccc3511ae6b964557d90", "d8ad44fbbde47488ec922df954c724f950af9bf2"),
    "0.2.2": ("9aa1eedcd2672b1e5dd348e9e14e23f0cfed3902", "df3b2a62aecd6919f8fd1fa95feba5f5a01edc47"),
    "1.0.0": ("b7fa02c904fd2a63906f0cbe67f1b2d0ba116ea3", "18344d45473df5a2aed79f213d799bd157859557"),
    "1.0.1": ("53f291b9f0f8eb923402c354be42c94e61a303c1", "e71a8b47a611c56347f1908fa764a1e21d6ac4b0"),
}


@pytest.fixture(autouse=True)
def _release_installer_locks():
    yield
    inst = sys.modules.get("install")
    for lock in list(getattr(inst, "_HELD_LOCKS", {}).values()):
        lock.release()


@pytest.fixture
def trust(monkeypatch):
    monkeypatch.setattr(mf, "PUBLIC_KEY_HEX", PK_HEX)


# ---------------------------------------------------------------- the release archive (built once)

@pytest.fixture(scope="module")
def release_archive(tmp_path_factory) -> Path:
    """This release's base archive as release.py builds it -- the real file set (without the 18 MB runtime: a
    stand-in interpreter in its place), plus canary files where no shipped generation 1 looks."""
    import release as rel
    try:
        entries = rel.collect("base", include_python=False)
    except FileNotFoundError as e:
        pytest.skip(f"the base module's inputs are not all here: {e}")
    extra = tmp_path_factory.mktemp("extra")
    for rel_path in ("tools/python/python.exe", "tools/python/Lib/os.py", "tools/python38/python.exe") + CANARIES:
        f = extra / rel_path.replace("/", "_")
        f.write_bytes(b"stand-in for " + rel_path.encode("ascii"))
        entries.append((f, rel_path))
    out = tmp_path_factory.mktemp("release") / "LongevityVaccine_9.9.9.zip"
    rel.write_zip(entries, out)
    return out


def _inventory_of(archive: Path) -> dict:
    with zipfile.ZipFile(archive) as z:
        return bs.parse_inventory(z.read(bs.INVENTORY_REL))


def _signed_manifest(d: Path, archive: Path, version: str = VERSION, url: str = None) -> Path:
    doc = {
        "schema": 1, "protocol": 1, "product": "longevity-vaccine", "latest": version,
        "min_upgradable_from": "0.0.0", "manual_install_required": False, "manual_install_reason": None,
        "unsupported_versions": [], "unsupported_targets": [], "yanked": [],
        "modules": {"base": {"version": version, "url": url or archive.as_uri(),
                             "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                             "size": archive.stat().st_size}},
    }
    d.mkdir(parents=True, exist_ok=True)
    m = d / "manifest.json"
    m.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    sm.sign_file(SEED, m)
    return m


def _args(manifest, offline: bool = False, swap_into="updater"):
    """Generation 2's arguments on a hand-over (`--swap-into` set: completion runs only then)."""
    return types.SimpleNamespace(manifest=str(manifest) if manifest is not None else None, offline=offline,
                                 modules=None, only_listed=False, no_prompt=True, no_wait=True, repair=False,
                                 with_thinker=False, keep_thinker=False, swap_into=swap_into)


@pytest.fixture
def game(tmp_path):
    g = tmp_path / "game"
    g.mkdir()
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    return g


def _extract(archive: Path, dest: Path) -> Path:
    with zipfile.ZipFile(archive) as z:
        z.extractall(dest)
    return dest


def _quiet(*_a, **_k):
    pass


# ---------------------------------------------------------------- the inventory itself

def test_the_archive_lists_every_payload_file_exactly(release_archive):
    """Every member but the root launchers and the list itself, with its true hash and size."""
    inv = _inventory_of(release_archive)
    with zipfile.ZipFile(release_archive) as z:
        members = {n: z.read(n) for n in z.namelist() if not n.endswith("/")}
    want = {n for n in members if n not in bs.ROOT_ONLY and n != bs.INVENTORY_REL}
    assert set(inv) == want
    for rel_path, (digest, size) in inv.items():
        assert (digest, size) == (hashlib.sha256(members[rel_path]).hexdigest(), len(members[rel_path])), rel_path
    for must in ("art/pracx_icons_overlay.pcx", "portraits/LONGEVITY_PORTRAITS_README.txt",
                 "scripts/bootstrap.py", *CANARIES):
        assert must in inv, must


def test_the_inventory_is_deterministic(release_archive, tmp_path):
    """A rebuilt archive must hash the same (release.py's reproducible-zip guarantee)."""
    import release as rel
    entries = rel.collect("base", include_python=False)
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    rel.write_zip(entries, a)
    rel.write_zip(list(reversed(entries)), b)
    assert a.read_bytes() == b.read_bytes()


def test_a_list_naming_a_path_outside_the_payload_is_refused():
    for bad in ("../x", "/abs", "C:evil", "a\\b", "a//b", "./a"):
        raw = json.dumps({"format": 1, "files": {bad: {"sha256": "0" * 64, "size": 1}}}).encode()
        with pytest.raises(OSError):
            bs.parse_inventory(raw)


def test_deploy_copies_exactly_the_list_not_a_second_one(game, release_archive, tmp_path, monkeypatch):
    """A first install and every later generation 1 deploy the ARCHIVE: PAYLOAD (a second list, the one that went
    stale) no longer decides -- emptying it changes nothing."""
    src = _extract(release_archive, tmp_path / "x")
    monkeypatch.setattr(bs, "PAYLOAD", ())
    d = bs.deploy(game, src, VERSION, say=_quiet)
    assert bs._inexact(d, _inventory_of(release_archive)) == ""
    assert not (d / "INSTALL.bat").exists(), "a root launcher reached the resident updater"


def test_deploy_refuses_a_source_missing_a_listed_file(game, release_archive, tmp_path):
    src = _extract(release_archive, tmp_path / "x")
    (src / "art" / "pracx_icons_overlay.pcx").unlink()
    with pytest.raises(OSError, match="pracx_icons_overlay"):
        bs.deploy(game, src, VERSION, say=_quiet)
    assert not bs.updater_dir(game).exists()


# ---------------------------------------------------------------- every shipped generation 1

_GEN1_PROBE = r'''
import json, sys, types
from pathlib import Path
scripts, game, manifest, url, sha, size, latest = sys.argv[1:8]
sys.path.insert(0, scripts)
import installer_exit as ix
import bootstrap as bs
args = types.SimpleNamespace(manifest=manifest, offline=False, modules=None, only_listed=False, no_prompt=True,
                             no_wait=True, repair=False, with_thinker=False, keep_thinker=False)
p = bs._download_new_payload(Path(game), {"url": url, "sha256": sha, "size": int(size)}, latest, args)
print("RESULT " + json.dumps(str(p)))
'''


def _git_ok(rev: str) -> bool:
    try:
        return subprocess.run(["git", "-C", str(_REPO), "cat-file", "-e", rev + "^{commit}"],
                              capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _shipped_scripts(version: str, dest: Path) -> Path:
    rev, blob = SHIPPED[version]
    if not _git_ok(rev):
        pytest.skip(f"the {version} sources (commit {rev[:7]}) are not in this repository")
    got = subprocess.run(["git", "-C", str(_REPO), "rev-parse", f"{rev}:work/scripts/bootstrap.py"],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    assert got == blob, f"commit {rev[:7]} is not the {version} that shipped (its bootstrap.py differs)"
    tar = subprocess.run(["git", "-C", str(_REPO), "archive", "--format=tar", rev, "work/scripts"],
                         capture_output=True, timeout=300, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(dest, filter="data")
    return dest / "work" / "scripts"


def _run_generation_one(version: str, game: Path, manifest: Path, archive: Path, tmp_path: Path) -> Path:
    scripts = _shipped_scripts(version, tmp_path / f"gen1-{version}")
    probe = tmp_path / "probe.py"
    probe.write_text(_GEN1_PROBE, encoding="utf-8")
    p = subprocess.run([sys.executable, "-I", str(probe), str(scripts), str(game), str(manifest), archive.as_uri(),
                        hashlib.sha256(archive.read_bytes()).hexdigest(), str(archive.stat().st_size), VERSION],
                       capture_output=True, text=True, timeout=600, cwd=str(tmp_path))
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, f"generation 1 {version} did not stage:\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}"
    return Path(json.loads(line[len("RESULT "):]))


@pytest.mark.parametrize("gen1", sorted(SHIPPED))
def test_every_shipped_generation_one_then_this_generation_two_makes_the_exact_payload(
        gen1, game, release_archive, tmp_path, trust, monkeypatch):
    """The test that would have caught 1.0.1: the REAL older generation 1 stages this release with its own frozen
    list, then this generation 2 completes it -- before the swap -- and the resident updater is exactly the
    release's file list. The canaries (a new folder, a new art file) stand for whatever the next release adds."""
    m = _signed_manifest(tmp_path / "srv", release_archive)
    staged = _run_generation_one(gen1, game, m, release_archive, tmp_path)
    inv = _inventory_of(release_archive)
    missing, _differing, _extra = bs.payload_diff(staged, inv)
    assert set(CANARIES) <= set(missing), \
        f"generation 1 {gen1} copied the canaries, so this test no longer proves that generation 2 adds them"
    # What generation 2 runs from is what generation 1 staged; the bootstrap closure must be there.
    assert (staged / "scripts" / "bootstrap.py").is_file() and (staged / bs.INVENTORY_REL).is_file()

    bs.complete_payload(game, staged, VERSION, _args(m), say=_quiet)
    assert bs._inexact(staged, inv) == ""
    bs.swap_in(game, staged, say=_quiet)
    assert bs._inexact(bs.updater_dir(game), inv) == "", "the resident updater is not the release's payload"
    assert (bs.updater_dir(game) / "art" / "pracx_icons_overlay.pcx").is_file()


# ---------------------------------------------------------------- completion, unit by unit

@pytest.fixture
def staged(game, release_archive, tmp_path):
    """A payload as a stale generation 1 left it, in the staging folder, with the archive downloaded beside it."""
    import fetch as fetchmod
    import preflight as pfm
    x = _extract(release_archive, tmp_path / "x")
    p = fetchmod.staging_dir(game) / f"payload-{VERSION}"
    bs.deploy(game, x, VERSION, dest=p, say=_quiet)
    for gone in ("art/pracx_icons_overlay.pcx", "portraits/LONGEVITY_PORTRAITS_README.txt", *CANARIES):
        (p / gone).unlink()
    archive = fetchmod.staging_dir(game) / pfm.staging_name(release_archive.as_uri(), "base")
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(release_archive.read_bytes())
    return p


def test_completion_adds_replaces_and_removes_until_exact(game, staged, release_archive, tmp_path, trust):
    (staged / "scripts" / "install.py").write_bytes(b"# not the release's\n")
    (staged / "scripts" / "stray.py").write_text("x = 1\n", encoding="ascii")
    (staged / "scripts" / "__pycache__").mkdir(exist_ok=True)
    (staged / "scripts" / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"bytecode")
    said = []
    bs.complete_payload(game, staged, VERSION, _args(_signed_manifest(tmp_path / "srv", release_archive)),
                        say=said.append)
    assert bs._inexact(staged, _inventory_of(release_archive)) == ""
    assert not (staged / "scripts" / "stray.py").exists()
    assert (staged / "scripts" / "__pycache__" / "a.cpython-312.pyc").exists(), "bytecode is never a difference"
    assert not list(staged.rglob("*.lvpart")), "a temporary file was left behind"
    assert any("completing the new installer: " in s for s in said)


def test_an_exact_payload_reads_no_manifest_and_no_archive(game, release_archive, tmp_path, monkeypatch):
    import install as inst
    import fetch as fetchmod
    x = _extract(release_archive, tmp_path / "y")
    exact = fetchmod.staging_dir(game) / "payload-exact"
    bs.deploy(game, x, VERSION, dest=exact, say=_quiet)
    monkeypatch.setattr(inst, "fetch_manifest", lambda *a, **k: pytest.fail("read the manifest for an exact payload"))
    bs.complete_payload(game, exact, VERSION, _args(tmp_path / "none.json"), say=_quiet)


def test_a_payload_without_a_list_is_left_alone(game, tmp_path, monkeypatch):
    """A developer's checkout, or a payload from before 1.0.2: nothing to complete against."""
    import install as inst
    monkeypatch.setattr(inst, "fetch_manifest", lambda *a, **k: pytest.fail("no list, nothing to fetch"))
    (tmp_path / "p" / "scripts").mkdir(parents=True)
    bs.complete_payload(game, tmp_path / "p", VERSION, _args(tmp_path / "none.json"), say=_quiet)


def test_a_vanished_archive_is_downloaded_again(game, staged, release_archive, tmp_path, trust):
    import fetch as fetchmod
    import shutil
    shutil.rmtree(fetchmod.staging_dir(game) / "base")
    bs.complete_payload(game, staged, VERSION, _args(_signed_manifest(tmp_path / "srv", release_archive)),
                        say=_quiet)
    assert bs._inexact(staged, _inventory_of(release_archive)) == ""


def _refused(game, staged, args, match):
    before = sorted(p.relative_to(staged).as_posix() for p in staged.rglob("*"))
    with pytest.raises(ix.InstallerError, match=match) as e:
        bs.complete_payload(game, staged, VERSION, args, say=_quiet)
    assert e.value.changed is False and e.value.code == ix.EXIT_ABORTED
    assert sorted(p.relative_to(staged).as_posix() for p in staged.rglob("*")) == before
    return e.value


def test_offline_with_the_archive_gone_fails_closed(game, staged, release_archive, tmp_path, trust):
    import fetch as fetchmod
    import shutil
    shutil.rmtree(fetchmod.staging_dir(game) / "base")
    err = _refused(game, staged, _args(_signed_manifest(tmp_path / "srv", release_archive), offline=True),
                   "could not be completed")
    assert "offline" in err.detail


def test_a_server_serving_other_bytes_fails_closed(game, staged, release_archive, tmp_path, trust):
    import fetch as fetchmod
    import shutil
    shutil.rmtree(fetchmod.staging_dir(game) / "base")
    wrong = tmp_path / "wrong.zip"
    wrong.write_bytes(release_archive.read_bytes()[:-10] + b"0123456789")
    m = _signed_manifest(tmp_path / "srv", release_archive, url=wrong.as_uri())
    _refused(game, staged, _args(m), "could not be completed")


def test_a_manifest_for_another_release_fails_closed(game, staged, release_archive, tmp_path, trust):
    m = _signed_manifest(tmp_path / "srv", release_archive, version="9.9.10")
    err = _refused(game, staged, _args(m), "could not be completed")
    assert "9.9.10" in err.detail


def test_an_unsigned_manifest_fails_closed(game, staged, release_archive, tmp_path, monkeypatch):
    monkeypatch.setattr(mf, "PUBLIC_KEY_HEX", "11" * 32)
    _refused(game, staged, _args(_signed_manifest(tmp_path / "srv", release_archive)), "could not be completed")


def test_an_archive_from_another_release_fails_closed(game, staged, release_archive, tmp_path, trust):
    """The archive's own list must be the one this payload runs with."""
    import release as rel
    entries = rel.collect("base", include_python=False)
    other = tmp_path / "other.zip"
    rel.write_zip(entries, other)
    import fetch as fetchmod
    import shutil
    shutil.rmtree(fetchmod.staging_dir(game) / "base")
    m = _signed_manifest(tmp_path / "srv", other)
    err = _refused(game, staged, _args(m), "could not be completed")
    assert "not the one this installer came from" in err.detail


def test_a_file_held_open_fails_closed_after_waiting(game, staged, release_archive, tmp_path, trust, monkeypatch):
    """A differing file Windows will not let go of (the running interpreter's DLL): stop, never half-swap."""
    monkeypatch.setattr(bs, "RENAME_RETRY_SECONDS", 0.2)
    (staged / "scripts" / "install.py").write_bytes(b"# differs\n")
    real = bs.os.replace

    def held(src, dst):
        if str(dst).endswith("install.py"):
            raise PermissionError(13, "held")
        return real(src, dst)
    monkeypatch.setattr(bs.os, "replace", held)
    with pytest.raises(ix.InstallerError) as e:
        bs.complete_payload(game, staged, VERSION, _args(_signed_manifest(tmp_path / "srv", release_archive)),
                            say=_quiet)
    assert e.value.changed is False
    assert not list(staged.rglob("*.lvpart"))


def test_generation_two_completes_before_the_swap_and_never_installs_an_incomplete_payload(
        game, staged, release_archive, tmp_path, trust, monkeypatch):
    """The order: complete, THEN swap, THEN install. A completion that fails leaves the previous updater armed and
    the game untouched."""
    import config
    x = _extract(release_archive, tmp_path / "old")
    bs.deploy(game, x, "1.0.0", say=_quiet)
    resident_before = bs.resident_version(game)
    monkeypatch.setattr(bs, "_SCRIPTS", staged / "scripts")
    monkeypatch.setattr(config, "payload_root_from", lambda s: Path(s).parent)
    monkeypatch.setattr(bs, "_wait_for_pid", lambda *a, **k: True)
    monkeypatch.setattr(bs.ver, "VERSION", VERSION, raising=False)
    import shutil  # noqa: F401
    import fetch as fetchmod
    shutil.rmtree(fetchmod.staging_dir(game) / "base")
    m = _signed_manifest(tmp_path / "srv", release_archive)
    monkeypatch.setattr(bs, "_run_installer", lambda *a, **k: pytest.fail("installed an incomplete payload"))
    monkeypatch.setattr(bs, "swap_in", lambda *a, **k: pytest.fail("swapped an incomplete payload"))
    with pytest.raises(ix.InstallerError):
        bs._generation_two(game, types.SimpleNamespace(**vars(_args(m, offline=True, swap_into=str(
            bs.updater_dir(game)))), wait_pid=None))
    assert bs.resident_version(game) == resident_before

    seen = {}
    monkeypatch.undo()
    monkeypatch.setattr(mf, "PUBLIC_KEY_HEX", PK_HEX)
    monkeypatch.setattr(bs, "_SCRIPTS", staged / "scripts")
    monkeypatch.setattr(config, "payload_root_from", lambda s: Path(s).parent)
    monkeypatch.setattr(bs, "_wait_for_pid", lambda *a, **k: True)
    monkeypatch.setattr(bs.ver, "VERSION", VERSION, raising=False)

    def install(*a, **k):
        seen["resident"] = bs._inexact(bs.updater_dir(game), _inventory_of(release_archive))
        return ix.EXIT_OK
    monkeypatch.setattr(bs, "_run_installer", install)
    staged_archive = fetchmod.staging_dir(game) / "base"
    staged_archive.mkdir(parents=True, exist_ok=True)
    import preflight as pfm
    (fetchmod.staging_dir(game) / pfm.staging_name(release_archive.as_uri(), "base")).write_bytes(
        release_archive.read_bytes())
    bs._generation_two(game, types.SimpleNamespace(**vars(_args(m, swap_into=str(bs.updater_dir(game)))),
                                                   wait_pid=None))
    assert seen == {"resident": ""}, "the install ran against a resident updater that is not the release's payload"


# ---------------------------------------------------------------- what install.py reads, what gen 2 imports

#: install.py's readers of its own payload -> the path each resolves to IN A PAYLOAD. A new reader must be added
#: here (the guard below finds every find_payload / payload_root caller), so a file the installer reads can never
#: again be left out of what ships -- the portraits guide was read by every update and shipped by none.
PAYLOAD_READERS = {
    "uimod_dll": "src/uimod/build/Release/uimod.dll",
    "popup_art": "art/longevity_sm.pcx",
    "ffmpeg_bin": "src/uimod/third_party/ffmpeg/bin/avcodec-62.dll",
    "portraits_readme": "portraits/LONGEVITY_PORTRAITS_README.txt",
    "pracx_icons_overlay": "art/pracx_icons_overlay.pcx",
    "launcher_path": "scripts/run-install.bat",
}
#: Readers of a PACK's files, staged by preflight from the pack's own archive -- not the base payload.
PACK_READERS = {"default_pack", "default_portrait_pack"}
#: Callers that use the payload root as a whole (deploying it), not one file of it.
WHOLE_PAYLOAD = {"payload_root", "find_payload", "do_repair", "_deploy_resident", "main", "run"}


def _payload_callers() -> set:
    src = (_SCRIPTS / "install.py").read_text(encoding="utf-8")
    out = set()
    for fn in ast.walk(ast.parse(src)):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                        and node.func.id in ("find_payload", "payload_root"):
                    out.add(fn.name)
    return out


def test_every_payload_reader_is_accounted_for():
    unknown = _payload_callers() - set(PAYLOAD_READERS) - PACK_READERS - WHOLE_PAYLOAD
    assert not unknown, (f"install.py reads its payload in {sorted(unknown)}: add each to PAYLOAD_READERS with "
                         "the payload path it reads, so the release is checked to ship it")


def test_every_file_install_py_reads_from_its_payload_ships(release_archive):
    inv = _inventory_of(release_archive)
    missing = {fn: p for fn, p in PAYLOAD_READERS.items() if p not in inv}
    assert not missing, f"install.py reads these from its payload but the release does not ship them: {missing}"


def test_install_py_resolves_every_reader_inside_a_deployed_payload(game, release_archive, tmp_path, monkeypatch):
    import install as inst
    d = bs.deploy(game, _extract(release_archive, tmp_path / "x"), VERSION, say=_quiet)
    monkeypatch.setenv("LONGEVITY_PAYLOAD_ROOT", str(d))
    for fn in ("uimod_dll", "popup_art", "ffmpeg_bin", "portraits_readme", "pracx_icons_overlay"):
        p = getattr(inst, fn)()
        assert p.exists() and d in p.parents, f"{fn}() -> {p}"


def _imports(path: Path) -> set:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_everything_generation_two_imports_ships_under_scripts(release_archive):
    """Generation 2 runs from what generation 1 staged, before it can complete anything: its own code must lie
    where every shipped generation 1 copies whole -- scripts/ (and the interpreter's own folder)."""
    inv = _inventory_of(release_archive)
    seen, todo = set(), ["bootstrap"]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        f = _SCRIPTS / f"{name}.py"
        if f.is_file():
            todo.extend(_imports(f))
    ours = sorted(n for n in seen if (_SCRIPTS / f"{n}.py").is_file())
    assert "install" in ours and "fetch" in ours
    absent = [n for n in ours if f"scripts/{n}.py" not in inv and not n.startswith(("dev_", "test_"))]
    assert not absent, f"generation 2 imports modules the release does not ship under scripts/: {absent}"


def test_a_missing_overlay_says_so_rather_than_read_only(tmp_path, monkeypatch):
    """The warning names the real problem: a read-only Icons.pcx is FAILED, a missing overlay is MISSING_ART."""
    import install as inst
    import patch_icons as pi
    monkeypatch.setattr(pi, "patch_folder", lambda *a, **k: {pi.SHEET: pi.MISSING_ART})
    said = []
    monkeypatch.setattr(ix, "warn", said.append)
    inst.patch_pracx_icons(tmp_path)
    assert said and "missing or damaged in this copy of the installer" in said[0] and "read-only" not in said[0]
    assert inst.pracx_icons_status({pi.SHEET: pi.MISSING_ART}) == "error", "the summary row says skip (audit M4)"
    said.clear()
    monkeypatch.setattr(pi, "patch_folder", lambda *a, **k: {pi.SHEET: pi.FAILED})
    inst.patch_pracx_icons(tmp_path)
    assert said and "read-only" in said[0]


def test_warning_lines_reach_the_candidate_file(tmp_path, monkeypatch):
    f = tmp_path / "w.txt"
    monkeypatch.setenv(ix.WARNINGS_FILE_ENV, str(f))
    ix.say("  ordinary line")
    ix.warn("  WARNING: something the player must read")
    assert f.read_text(encoding="utf-8").splitlines() == ["WARNING: something the player must read"]


_PY38 = next((p for p in (_REPO / "work" / "build" / "runtime38" / "python.exe", _REPO / "tools" / "python38" / "python.exe")
              if p.is_file()), None)
_PY38_PROBE = r'''
import sys, zipfile
from pathlib import Path
scripts, work = sys.argv[1], Path(sys.argv[2])
sys.path.insert(0, scripts)
import bootstrap as bs
files = {"scripts/a.py": b"a = 1\n", "art/x.pcx": b"art", "newdir/n.txt": b"new"}
inv_raw = bs.make_inventory(files.items())
inv = bs.parse_inventory(inv_raw)
archive = work / "r.zip"
with zipfile.ZipFile(archive, "w") as z:
    for k, v in files.items():
        z.writestr(k, v)
    z.writestr(bs.INVENTORY_REL, inv_raw)
root = work / "payload"
(root / "scripts").mkdir(parents=True)
(root / "scripts" / "a.py").write_bytes(b"a = 1\n")
(root / bs.INVENTORY_REL).write_bytes(inv_raw)
(root / "stray.txt").write_bytes(b"x")
missing, differing, extra = bs.payload_diff(root, inv)
assert missing == ["art/x.pcx", "newdir/n.txt"] and extra == ["stray.txt"], (missing, extra)
bs._restore_members(work, archive, root, missing, inv)
bs._unlink_in(work, root / "stray.txt")
assert bs._inexact(root, inv) == "", bs._inexact(root, inv)
print("OK38")
'''


@pytest.mark.skipif(_PY38 is None, reason="the Windows 7 interpreter is not here (run fetch_python38.py)")
def test_the_completion_core_runs_under_the_windows_7_interpreter(tmp_path):
    """Windows 7 / 8 players run generation 2 on CPython 3.8: the list, the diff and the restore must work there."""
    probe = tmp_path / "probe.py"
    probe.write_text(_PY38_PROBE, encoding="utf-8")
    p = subprocess.run([str(_PY38), str(probe), str(_SCRIPTS), str(tmp_path)], capture_output=True, text=True,
                       timeout=120, cwd=str(tmp_path))
    assert "OK38" in p.stdout, p.stdout[-2000:] + p.stderr[-2000:]



# ---------------------------------------------------------------- the antagonistic audit (2026-11-19)

def test_h1_a_frozen_generation_one_stages_a_list_it_cannot_read(game, release_archive, tmp_path):
    """1.0.2 will run as generation 1 for every later release: a newer list format (or a missing file) must never
    stop it staging -- exactness is the newer generation 2's, which can repair it from the archive."""
    import json as _json
    src = _extract(release_archive, tmp_path / "x")
    doc = _json.loads((src / bs.INVENTORY_REL).read_text(encoding="ascii"))
    doc["format"] = 2
    doc["signature"] = {"anything": [1, 2]}
    (src / bs.INVENTORY_REL).write_text(_json.dumps(doc), encoding="ascii")
    (src / "art" / "pracx_icons_overlay.pcx").unlink()
    with pytest.raises(OSError):
        bs.deploy(game, src, VERSION, dest=tmp_path / "strict", say=_quiet)            # first install: strict
    staged = bs.deploy(game, src, VERSION, dest=tmp_path / "lenient", say=_quiet, strict=False)
    assert (staged / bs.INVENTORY_REL).is_file(), "the newer list must still reach the newer generation 2"
    assert (staged / "scripts" / "bootstrap.py").is_file() and bs.is_usable(staged)


def test_h1_generation_one_stages_a_payload_missing_a_listed_file(game, release_archive, tmp_path):
    src = _extract(release_archive, tmp_path / "x")
    (src / "portraits" / "LONGEVITY_PORTRAITS_README.txt").unlink()
    with pytest.raises(bs.IncompletePayload) as e:
        bs.deploy(game, src, VERSION, dest=tmp_path / "strict", say=_quiet)
    assert e.value.missing == ["portraits/LONGEVITY_PORTRAITS_README.txt"]
    staged = bs.deploy(game, src, VERSION, dest=tmp_path / "lenient", say=_quiet, strict=False)
    missing, _d, _e = bs.payload_diff(staged, _inventory_of(release_archive))
    assert missing == ["portraits/LONGEVITY_PORTRAITS_README.txt"]


def test_h1_this_generation_one_hands_its_staging_to_deploy_leniently():
    src = (_SCRIPTS / "bootstrap.py").read_text(encoding="utf-8")
    body = src[src.index("def _download_new_payload"):src.index("def _runs_from")]
    assert "strict=False" in body


def test_m1_a_staged_payload_that_lost_its_list_is_completed_from_the_archive(
        game, staged, release_archive, tmp_path, trust):
    (staged / bs.INVENTORY_REL).unlink()
    bs.complete_payload(game, staged, VERSION, _args(_signed_manifest(tmp_path / "srv", release_archive)),
                        say=_quiet)
    assert (staged / bs.INVENTORY_REL).read_bytes() == zipfile.ZipFile(release_archive).read(bs.INVENTORY_REL)
    assert bs._inexact(staged, _inventory_of(release_archive)) == ""


def test_m1_a_staged_list_that_disagrees_with_the_archive_fails_closed(game, staged, release_archive, tmp_path,
                                                                         trust):
    inv = _inventory_of(release_archive)
    inv.pop("art/canary.pcx")
    raw = bs.make_inventory([])          # a list of a different release
    (staged / bs.INVENTORY_REL).write_bytes(raw)
    (staged / "scripts" / "stray.txt").write_text("x", encoding="ascii")
    err = _refused(game, staged, _args(_signed_manifest(tmp_path / "srv", release_archive)),
                   "could not be completed")
    assert "not the one this installer came from" in err.detail


def test_m2_the_list_is_made_from_the_very_bytes_written(tmp_path, monkeypatch):
    """A source file that changes between two reads must not ship a list its own archive contradicts."""
    import release as rel
    f = tmp_path / "f.txt"
    f.write_bytes(b"one")
    reads = {"n": 0}
    real = Path.read_bytes

    def drifting(self):
        if self == f:
            reads["n"] += 1
            return b"one" if reads["n"] == 1 else b"two"
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", drifting)
    out = tmp_path / "a.zip"
    rel.write_zip([(f, "scripts/f.txt"), (None, bs.INVENTORY_REL)], out)
    assert reads["n"] == 1, "write_zip read the file twice"
    assert rel.inventory_problem(out) is None


def test_m2_the_built_archive_is_checked_against_its_list(release_archive, tmp_path):
    import release as rel
    assert rel.inventory_problem(release_archive) is None
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(release_archive) as src, zipfile.ZipFile(bad, "w") as z:
        for n in src.namelist():
            z.writestr(n, b"tampered" if n == "scripts/bootstrap.py" else src.read(n))
    assert "scripts/bootstrap.py does not match" in rel.inventory_problem(bad)
    pyc = tmp_path / "pyc.zip"
    with zipfile.ZipFile(pyc, "w") as z:
        z.writestr("scripts/x.pyc", b"bytecode")
        z.writestr(bs.INVENTORY_REL, bs.make_inventory([("scripts/x.pyc", b"bytecode")]))
    assert "bytecode" in rel.inventory_problem(pyc)


def test_m3_the_swap_copies_exactly_the_list_and_never_bytecode(game, release_archive, tmp_path):
    staged = bs.deploy(game, _extract(release_archive, tmp_path / "x"), VERSION, dest=tmp_path / "p", say=_quiet)
    (staged / "scripts" / "__pycache__").mkdir()
    (staged / "scripts" / "__pycache__" / "install.cpython-312.pyc").write_bytes(b"bytecode")
    bs.swap_in(game, staged, say=_quiet)
    live = bs.updater_dir(game)
    assert bs._inexact(live, _inventory_of(release_archive)) == ""
    assert bs.resident_version(game) == VERSION
    assert not (live / "scripts" / "__pycache__").exists()


def test_m5_an_incomplete_first_install_folder_says_extract_again(tmp_path, monkeypatch, capsys):
    import install as inst
    src = (_SCRIPTS / "install.py").read_text(encoding="utf-8")
    assert "isinstance(resident_error, _bs.IncompletePayload)" in src
    assert "Extract the whole download again" in src


def test_m5_repair_from_a_damaged_copy_points_at_the_downloading_repair(game, release_archive, tmp_path,
                                                                         monkeypatch):
    import install as inst
    src = _extract(release_archive, tmp_path / "x")
    (src / "art" / "longevity_sm.pcx").unlink()
    monkeypatch.setenv("LONGEVITY_PAYLOAD_ROOT", str(src))
    inst._load_modules()
    with pytest.raises(ix.InstallerError) as e:
        inst.do_repair(game)
    assert "--update --repair" in e.value.remedy and "missing some of its own files" in e.value.message


def test_l1_reconcile_never_promotes_a_listed_copy_cut_short(game, release_archive, tmp_path):
    """python.exe present, its DLLs not: is_usable passed it; its own list does not."""
    import shutil
    good = bs.deploy(game, _extract(release_archive, tmp_path / "x"), VERSION, dest=tmp_path / "full", say=_quiet)
    root = bs.mods_root(game)
    shutil.copytree(good, root / bs.NEW_DIR)
    (root / bs.NEW_DIR / "scripts" / "install.py").unlink()
    (root / bs.NEW_DIR / "scripts" / "install.py").write_text("x = 1\n", encoding="ascii")   # usable, not exact
    shutil.copytree(good, root / bs.OLD_DIR)
    said = []
    bs.reconcile(game, say=said.append)
    assert any("ignoring updater.new: incomplete" in x for x in said), said
    assert bs._inexact(bs.updater_dir(game), _inventory_of(release_archive)) == ""


def test_l2_the_warnings_file_never_reaches_a_relaunched_game(monkeypatch):
    monkeypatch.setenv(ix.WARNINGS_FILE_ENV, "x")
    assert ix.WARNINGS_FILE_ENV not in ix.outliving_env()


@pytest.mark.parametrize("bad", ["art/x.pcx.", "art/x ", "CON", "scripts/nul.txt", "a/LPT1.dat", "COM9.x"])
def test_l3_names_windows_cannot_hold_are_refused(bad):
    raw = json.dumps({"format": 1, "files": {bad: {"sha256": "0" * 64, "size": 1}}}).encode()
    with pytest.raises(OSError):
        bs.parse_inventory(raw)


def test_l3_a_name_listed_twice_in_different_case_is_refused():
    raw = json.dumps({"format": 1, "files": {"a/B.txt": {"sha256": "0" * 64, "size": 1},
                                             "a/b.txt": {"sha256": "0" * 64, "size": 1}}}).encode()
    with pytest.raises(OSError, match="twice"):
        bs.parse_inventory(raw)


def test_l3_every_real_payload_name_passes(release_archive):
    assert len(_inventory_of(release_archive)) > 20


def test_l4_completion_only_runs_on_a_hand_over(game, staged, release_archive, tmp_path, trust, monkeypatch):
    """A manual `--generation 2` run without --swap-into, or a payload outside staging (the resident updater
    itself), is never rewritten."""
    import install as inst
    monkeypatch.setattr(inst, "fetch_manifest", lambda *a, **k: pytest.fail("not a hand-over"))
    before = sorted(x.relative_to(staged).as_posix() for x in staged.rglob("*"))
    bs.complete_payload(game, staged, VERSION, _args(None, swap_into=None), say=_quiet)
    resident = bs.deploy(game, _extract(release_archive, tmp_path / "x"), VERSION, say=_quiet)
    (resident / "scripts" / "stray.txt").write_text("x", encoding="ascii")
    bs.complete_payload(game, resident, VERSION, _args(None), say=_quiet)
    assert (resident / "scripts" / "stray.txt").exists()
    assert sorted(x.relative_to(staged).as_posix() for x in staged.rglob("*")) == before


def test_l6_the_production_path_completes_from_the_cache_without_a_network(game, staged, release_archive, tmp_path,
                                                                            trust, monkeypatch):
    """No --manifest: the manifest generation 1 cached in staging, an https URL, the archive it downloaded."""
    import fetch as fetchmod
    import preflight as pfm
    url = "https://github.com/x/y/releases/download/v9.9.9/LongevityVaccine_9.9.9.zip"
    m = _signed_manifest(tmp_path / "srv", release_archive, url=url)
    st = fetchmod.staging_dir(game)
    (st / "manifest.json").write_bytes(m.read_bytes())
    (st / "manifest.json.sig").write_bytes(Path(str(m) + ".sig").read_bytes())
    arch = st / pfm.staging_name(url, "base")
    arch.parent.mkdir(parents=True, exist_ok=True)
    arch.write_bytes(release_archive.read_bytes())
    monkeypatch.setattr(fetchmod, "_fetch_one", lambda *a, **k: pytest.fail("went to the network"))
    bs.complete_payload(game, staged, VERSION, _args(None), say=_quiet)
    assert bs._inexact(staged, _inventory_of(release_archive)) == ""


_GEN2_PROBE = r"""
import sys, types
from pathlib import Path
scripts, game, manifest, version, pk = sys.argv[1:6]
sys.path.insert(0, scripts)
import installer_exit as ix
import manifest as mf
mf.PUBLIC_KEY_HEX = pk
import bootstrap as bs
args = types.SimpleNamespace(manifest=manifest, offline=False, swap_into=str(bs.updater_dir(Path(game))))
root = Path(scripts).parent
bs.complete_payload(Path(game), root, version, args, say=lambda *a: None)
print("RESULT " + (bs._inexact(root, bs.read_inventory(root)) or "exact"))
"""


def test_l6_generation_two_completes_running_from_what_generation_one_1_0_0_staged(
        game, release_archive, tmp_path):
    """The staged copy's OWN code, in its own interpreter process, from exactly what 1.0.0 staged: proves the
    import closure is there at run time, not only in an AST walk."""
    m = _signed_manifest(tmp_path / "srv", release_archive)
    staged = _run_generation_one("1.0.0", game, m, release_archive, tmp_path)
    probe = tmp_path / "gen2.py"
    probe.write_text(_GEN2_PROBE, encoding="utf-8")
    p = subprocess.run([sys.executable, "-I", str(probe), str(staged / "scripts"), str(game), str(m), VERSION,
                        PK_HEX], capture_output=True, text=True, timeout=300, cwd=str(tmp_path))
    assert "RESULT exact" in p.stdout, p.stdout[-3000:] + p.stderr[-3000:]
