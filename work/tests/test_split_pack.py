"""A pack too big for one GitHub release asset (2 GiB) is published as byte slices of its one archive
(work/briefs/split-cinematics-pack.md).

What is pinned:
  * manifest.module_parts accepts exactly the shape release.py writes and fails closed on anything else;
  * release.py cuts deterministically (plan_slices / split_archive), never splits the base, and a split manifest entry
    carries `parts` and NO top-level `url` (the 1.0.0 installer must not see one -- test_client_100_compat.py);
  * fetch.download_parts fetches every part with its own digest, resume and mirror, shows ONE pack, and keeps the
    verified parts when a later one fails; fetch.ConcatReader reads the parts as the one archive;
  * preflight.check_archives and install.install_modules install a split pack exactly as the same pack unsplit;
  * release.parts_rollback_problem refuses a manifest older clients could roll back from. The release_all,
    publish and dev_candidate checks are in test_split_pack_publish.py, which stays with the operator tooling.

Everything runs on small synthetic packs with a tiny part size: no 5 GB archive is ever cut here.
"""
from __future__ import annotations

import hashlib
import http.server
import io
import json
import random
import sys
import threading
import types
import zipfile
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_SCRIPTS = _TESTS.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_TESTS))

import fetch                 # noqa: E402
import manifest as mf        # noqa: E402
import release as rel        # noqa: E402

PART_MAX = 4096


def _pack_zip(path: Path, clips: int = 6, clip_size: int = 3000, seed: int = 7) -> Path:
    """A movies-hd-shaped archive, STORED so its size is predictable: random clips, then the pack's own files (the
    manifest's bytes land in the LAST part)."""
    rnd = random.Random(seed)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        for i in range(clips):
            z.writestr(f"movies/hd/clip{i:02d}.mp4", bytes(rnd.getrandbits(8) for _ in range(clip_size)))
        z.writestr("movies/hd/PROVENANCE.txt", b"credit")
        z.writestr("movies/hd/pack-manifest.json", b'{"clips": []}')
    return path


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture
def pack(tmp_path):
    """(archive, its parts as release.py cuts them at PART_MAX, the manifest entry with file:// part URLs)."""
    d = tmp_path / "dist"
    d.mkdir()
    archive = _pack_zip(d / rel.archive_name("movies-hd", "2.0.0"))
    parts = rel.split_archive(archive, "movies-hd", "2.0.0", PART_MAX)
    info = {"version": "2.0.0", "required": False, "sha256": _sha(archive.read_bytes()),
            "size": archive.stat().st_size,
            "parts": [{"url": Path(p["path"]).as_uri(), "sha256": p["sha256"], "size": p["size"]} for p in parts]}
    return archive, [Path(p["path"]) for p in parts], info


# ---------------------------------------------------------------- manifest.module_parts

def test_an_unsplit_entry_has_no_parts():
    assert mf.module_parts({"url": "https://x/a.zip", "sha256": "a" * 64, "size": 3}) is None
    assert mf.module_parts(None) is None


def test_parts_are_read_in_order_with_their_digests(pack):
    _archive, paths, info = pack
    got = mf.module_parts(info)
    assert [p["size"] for p in got] == [p.stat().st_size for p in paths]
    assert all(p["mirror"] is None for p in got)
    info["parts"][0]["sha256"] = info["parts"][0]["sha256"].upper()
    assert mf.module_parts(info)[0]["sha256"] == info["parts"][0]["sha256"].lower()


def _bad(mut):
    info = {"size": 10, "parts": [{"url": "https://h/a.001", "sha256": "a" * 64, "size": 6},
                                  {"url": "https://h/a.002", "sha256": "b" * 64, "size": 4}]}
    mut(info)
    return info


@pytest.mark.parametrize("mut", [
    lambda i: i.update(parts={}),
    lambda i: i.update(parts=[]),
    lambda i: i.update(parts=[i["parts"][0]] * (mf.MAX_PARTS + 1)),
    lambda i: i.update(url="https://h/a.zip"),                 # a 1.0.0 client would fetch it whole
    lambda i: i.update(mirror="https://m/a.zip"),
    lambda i: i.update(size=11),                               # parts do not add up
    lambda i: i.update(size=True),
    lambda i: i.pop("size"),
    lambda i: i["parts"].__setitem__(0, "https://h/a.001"),
    lambda i: i["parts"][0].pop("url"),
    lambda i: i["parts"][0].update(sha256="z" * 64),
    lambda i: i["parts"][0].update(sha256="a" * 63),
    lambda i: i["parts"][0].update(size=0),
    lambda i: i["parts"][0].update(size="6"),
    lambda i: i["parts"][0].update(mirror=5),
    lambda i: i["parts"][1].update(url="https://h/a.001"),     # the same part twice
], ids=lambda f: "case")
def test_a_malformed_split_entry_fails_closed(mut):
    with pytest.raises(mf.PartsError):
        mf.module_parts(_bad(mut))


# ---------------------------------------------------------------- release.py: the cut

def test_the_cinematics_is_cut_into_three_equal_parts_under_githubs_limit():
    sizes = rel.plan_slices(4_963_447_978)
    assert sizes == [1_654_482_660, 1_654_482_660, 1_654_482_658]
    assert sum(sizes) == 4_963_447_978
    assert all(s < 2 * 1024 ** 3 for s in sizes) and rel.PART_MAX < 2 * 1024 ** 3


def test_an_archive_that_fits_one_asset_is_not_split():
    assert rel.plan_slices(rel.PART_MAX) == [] and rel.plan_slices(30_150_491) == []
    assert len(rel.plan_slices(rel.PART_MAX + 1)) == 2


def test_the_cut_is_deterministic_and_joins_back_to_the_archive(tmp_path, pack):
    archive, paths, _info = pack
    assert len(paths) == len(rel.plan_slices(archive.stat().st_size, PART_MAX)) >= 3
    assert [p.name for p in paths] == [f"LV-movies-hd-2.0.0.zip.{i:03d}" for i in range(1, len(paths) + 1)]
    assert b"".join(p.read_bytes() for p in paths) == archive.read_bytes()
    first = [p.read_bytes() for p in paths]
    again = rel.split_archive(archive, "movies-hd", "2.0.0", PART_MAX)
    assert [Path(p["path"]).read_bytes() for p in again] == first


def test_a_wrong_or_stale_part_on_disk_is_replaced_or_removed(pack):
    archive, paths, _info = pack
    paths[1].write_bytes(b"x" * paths[1].stat().st_size)          # same size, wrong bytes
    stray = archive.with_name(archive.name + ".009")
    stray.write_bytes(b"left by an earlier, larger build")
    rel.split_archive(archive, "movies-hd", "2.0.0", PART_MAX)
    assert b"".join(p.read_bytes() for p in paths) == archive.read_bytes()
    assert not stray.exists()
    # The archive now fits one asset: every part goes.
    rel.split_archive(archive, "movies-hd", "2.0.0", archive.stat().st_size)
    assert not any(p.exists() for p in paths)


def test_a_split_entry_lists_its_parts_and_carries_no_url(pack):
    archive, paths, _info = pack
    built = {"version": "2.0.0", "sha256": _sha(archive.read_bytes()), "size": archive.stat().st_size,
             "parts": rel.split_archive(archive, "movies-hd", "2.0.0", PART_MAX)}
    e = rel._module_entry("movies-hd", built, rel.BASE_URL, rel.PACK_URL)
    assert "url" not in e and "mirror" not in e
    assert e["size"] == archive.stat().st_size and e["sha256"] == built["sha256"]
    tag = "https://github.com/BoltActionBalrog/longevity-vaccine/releases/download/movies-hd-v2.0.0/"
    assert [p["url"] for p in e["parts"]] == [tag + p.name for p in paths]
    assert mf.module_parts(e) is not None
    plain = rel._module_entry("portraits-hd", {"version": "1.0.0", "sha256": "a" * 64, "size": 5, "parts": []},
                              rel.BASE_URL, rel.PACK_URL)
    assert plain["url"].endswith("/portraits-hd-v1.0.0/LV-portraits-hd-1.0.0.zip") and "parts" not in plain


def test_the_base_is_never_split(pack):
    with pytest.raises(SystemExit, match="REFUSING to split the base"):
        rel._module_entry("base", {"version": "1.0.1", "sha256": "a" * 64, "size": 10,
                                   "parts": [{"sha256": "a" * 64, "size": 10}]}, rel.BASE_URL, rel.PACK_URL)
    import inspect
    assert "check_base_fits(dest)" in inspect.getsource(rel.main), "release.main runs the check on the base"


def test_a_base_over_one_asset_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(rel, "PART_MAX", 100)
    big = tmp_path / "LongevityVaccine_1.0.1.zip"
    big.write_bytes(b"x" * 101)
    with pytest.raises(SystemExit, match="the base can never be split.*What to do"):
        rel.check_base_fits(big)
    big.write_bytes(b"x" * 100)
    rel.check_base_fits(big)


def test_an_unsplit_entry_keeps_its_exact_shape():
    """A pack under the limit, and the base, are written exactly as before the split existed (key order included):
    unsplit releases are byte-for-byte unchanged."""
    e = rel._module_entry("portraits-hd", {"version": "1.0.0", "sha256": "c" * 64, "size": 5, "parts": []},
                          rel.BASE_URL, rel.PACK_URL)
    assert list(e) == ["version", "required", "url", "sha256", "size"]
    b = rel._module_entry("base", {"version": "1.0.1", "sha256": "a" * 64, "size": 5}, rel.BASE_URL, rel.PACK_URL)
    assert list(b) == ["version", "required", "url", "sha256", "size"]
    assert b["url"].endswith("/download/v1.0.1/LongevityVaccine_1.0.1.zip")


def test_a_split_that_would_need_too_many_parts_is_refused(pack):
    archive, _paths, _info = pack
    with pytest.raises(SystemExit, match="at most 16"):
        rel.split_archive(archive, "movies-hd", "2.0.0", archive.stat().st_size // 17)


def test_an_interrupted_split_leaves_no_old_part_under_a_final_name(pack, monkeypatch):
    archive, paths, _info = pack
    good = [p.read_bytes() for p in paths]
    paths[1].write_bytes(b"o" * paths[1].stat().st_size)                 # an older archive's part, same size
    real = Path.replace

    def stop(self, dest):
        if self.name.endswith(".002.tmp"):
            raise KeyboardInterrupt
        return real(self, dest)
    monkeypatch.setattr(Path, "replace", stop)
    with pytest.raises(KeyboardInterrupt):
        rel.split_archive(archive, "movies-hd", "2.0.0", PART_MAX)
    assert not paths[1].exists(), "the old bytes are gone before the rewrite starts"
    assert paths[1].with_name(paths[1].name + ".tmp").exists()
    monkeypatch.setattr(Path, "replace", real)
    rel.split_archive(archive, "movies-hd", "2.0.0", PART_MAX)
    assert [p.read_bytes() for p in paths] == good
    assert not list(archive.parent.glob("*.tmp")), "the next run sweeps the interrupted split's temp file"


# ---------------------------------------------------------------- fetch: the joined reader

def test_the_concat_reader_is_the_archive_byte_for_byte(pack):
    archive, paths, _info = pack
    whole = archive.read_bytes()
    with fetch.ConcatReader(paths) as r:
        assert r.read() == whole
        for pos, n in [(0, 10), (PART_MAX - 3, 7), (PART_MAX * 2 - 1, PART_MAX + 5), (len(whole) - 4, 100)]:
            r.seek(pos)
            assert r.read(n) == whole[pos:pos + n] and r.tell() == min(pos + n, len(whole))
        assert r.seek(-22, io.SEEK_END) == len(whole) - 22 and r.read() == whole[-22:]
        r.seek(5)
        r.seek(3, io.SEEK_CUR)
        assert r.tell() == 8
        assert r.seek(len(whole) + 10) and r.read(4) == b""
        with pytest.raises(OSError):
            r.seek(-1)
    assert r.closed


def test_zipfile_reads_and_verifies_the_joined_parts(pack):
    archive, paths, _info = pack
    with zipfile.ZipFile(archive) as a, fetch.ConcatReader(paths) as src, zipfile.ZipFile(src) as b:
        assert b.testzip() is None
        assert [i.filename for i in b.infolist()] == [i.filename for i in a.infolist()]
        assert all(b.read(n) == a.read(n) for n in a.namelist())


@pytest.fixture(scope="module")
def zip64_cut(tmp_path_factory):
    """A real ZIP64 archive (over 65,535 entries: the ZIP64 end records are written) cut by hand with boundaries
    inside the central directory and inside the ZIP64 end records. Module-scoped: about a second to build."""
    d = tmp_path_factory.mktemp("zip64")
    whole = d / "big.zip"
    with zipfile.ZipFile(whole, "w", zipfile.ZIP_STORED) as z:
        for i in range(65_600):
            z.writestr(f"m/{i:05d}", b"" if i % 97 else bytes([i % 256]) * 7)
    data = whole.read_bytes()
    assert b"PK\x06\x06" in data[-200:], "the ZIP64 end record is there"
    cuts = [len(data) // 3, len(data) - 120, len(data) - 40, len(data)]
    parts, start = [], 0
    for i, end in enumerate(cuts):
        p = d / f"big.zip.{i + 1:03d}"
        p.write_bytes(data[start:end])
        parts.append(p)
        start = end
    return whole, parts


def test_a_zip64_archive_reads_through_the_joined_parts(zip64_cut):
    whole, parts = zip64_cut
    with zipfile.ZipFile(whole) as a, fetch.ConcatReader(parts) as src, zipfile.ZipFile(src) as b:
        assert len(b.infolist()) == len(a.infolist()) == 65_600
        assert b.testzip() is None and b.read("m/00097") == a.read("m/00097")


def test_a_part_that_grew_never_stands_in_for_the_next(pack):
    archive, paths, _info = pack
    with fetch.ConcatReader(paths) as r:
        with paths[0].open("ab") as f:
            f.write(b"GROWN" * 10)                    # after the reader measured it
        r.seek(paths[0].stat().st_size - 50 - 5)
        got = r.read(20)
    whole = archive.read_bytes()
    first = len(whole) - sum(p.stat().st_size for p in paths[1:])
    assert got == whole[first - 5:first + 15]


def test_parts_joined_in_the_wrong_order_are_not_a_readable_archive(pack):
    _archive, paths, _info = pack
    with fetch.ConcatReader([paths[1], paths[0], *paths[2:]]) as src:
        with pytest.raises((zipfile.BadZipFile, OSError)):
            with zipfile.ZipFile(src) as z:
                if z.testzip() is not None:
                    raise zipfile.BadZipFile("crc")


# ---------------------------------------------------------------- fetch.download_parts

def _parts(info):
    return mf.module_parts(info)


def test_every_part_is_fetched_and_verified_as_one_pack(tmp_path, pack, capsys):
    _archive, paths, info = pack
    dests = [tmp_path / "stage" / p.name for p in paths]
    got = fetch.download_parts(_parts(info), dests, label="Z2k Retro's HD Cinematics", allow_file=True)
    assert [p.read_bytes() for p in got] == [p.read_bytes() for p in paths]
    out = capsys.readouterr().out
    assert out.count("verified") == 1 and f"{info['size']:,} bytes verified" in out
    assert ".00" not in out and "part" not in out.lower(), "the parts never show"
    # A re-run downloads nothing and still says one line.
    fetch.download_parts(_parts(info), dests, label="x", allow_file=True)
    assert capsys.readouterr().out.count("\n") == 1


def test_a_bad_part_keeps_the_parts_before_it(tmp_path, pack):
    _archive, paths, info = pack
    info["parts"][1]["sha256"] = "0" * 64
    dests = [tmp_path / "stage" / p.name for p in paths]
    with pytest.raises(fetch.MismatchError):
        fetch.download_parts(_parts(info), dests, label="x", allow_file=True)
    assert dests[0].read_bytes() == paths[0].read_bytes()
    assert not dests[1].exists() and not dests[2].exists()


def test_a_part_falls_back_to_its_own_mirror(tmp_path, pack):
    _archive, paths, info = pack
    info["parts"][1]["mirror"] = info["parts"][1]["url"]
    info["parts"][1]["url"] = (tmp_path / "gone.001").as_uri()
    dests = [tmp_path / "stage" / p.name for p in paths]
    fetch.download_parts(_parts(info), dests, label="x", allow_file=True, max_attempts=1)
    assert dests[1].read_bytes() == paths[1].read_bytes()


class _PartServer(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        body = self.server.files[self.path]
        rng = self.headers.get("Range")
        self.server.seen.append((self.path, rng))
        if rng and not getattr(self.server, "norange", False):
            start = int(rng.split("=", 1)[1].split("-")[0])
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(body) - 1}/{len(body)}")
            body = body[start:]
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.server.sent = getattr(self.server, "sent", 0) + len(body)


@pytest.fixture
def part_server(pack, monkeypatch):
    """The pack's parts over (loopback) http, with the module's https-only guard widened to it."""
    _archive, paths, info = pack
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _PartServer)
    srv.files = {f"/{p.name}": p.read_bytes() for p in paths}
    srv.seen = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    real = fetch.urllib.parse.urlparse
    monkeypatch.setattr(fetch.urllib.parse, "urlparse", lambda u, *a, **k: (
        lambda r: r._replace(scheme="https") if r.scheme == "http" else r)(real(u, *a, **k)))
    monkeypatch.setattr(fetch, "_opener", lambda allow_file=False: fetch.urllib.request.build_opener())
    for pt, p in zip(info["parts"], paths):
        pt["url"] = f"{base}/{p.name}"
    yield srv
    srv.shutdown()


def test_a_stopped_download_resumes_inside_the_part_it_stopped_in(tmp_path, pack, part_server):
    _archive, paths, info = pack
    stage = tmp_path / "stage"
    stage.mkdir()
    dests = [stage / p.name for p in paths]
    dests[0].write_bytes(paths[0].read_bytes())                       # verified by an earlier run
    dests[1].with_name(dests[1].name + ".part").write_bytes(paths[1].read_bytes()[:1000])   # stopped mid-part
    fetch.download_parts(_parts(info), dests, label="x")
    assert [d.read_bytes() for d in dests] == [p.read_bytes() for p in paths]
    assert part_server.seen[0] == (f"/{paths[1].name}", "bytes=1000-")
    assert all(path != f"/{paths[0].name}" for path, _ in part_server.seen), "a verified part is never fetched again"


def test_a_part_that_restarts_never_claims_the_whole_pack_restarts(tmp_path, pack, part_server, capsys):
    _archive, paths, info = pack
    part_server.norange = True                                         # the host ignores Range
    stage = tmp_path / "stage"
    stage.mkdir()
    dests = [stage / p.name for p in paths]
    dests[1].with_name(dests[1].name + ".part").write_bytes(paths[1].read_bytes()[:1000])
    fetch.download_parts(_parts(info), dests, label="Z2k Retro's HD Cinematics")
    out = capsys.readouterr().out
    assert "some of the download is being fetched again" in out
    assert "from the beginning" not in out and ".00" not in out
    assert [d.read_bytes() for d in dests] == [p.read_bytes() for p in paths]


class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_one_bar_runs_to_100_percent_across_the_parts_on_a_console(tmp_path, pack, monkeypatch):
    _archive, paths, info = pack
    out = _Tty()
    monkeypatch.setattr(sys, "stdout", out)
    stage = tmp_path / "stage"
    stage.mkdir()
    dests = [stage / p.name for p in paths]
    dests[-1].write_bytes(paths[-1].read_bytes())                    # the LAST part is already here
    fetch.download_parts(_parts(info), dests, label="Z2k Retro's HD Cinematics", allow_file=True)
    text = out.getvalue()
    lines = text.split("\n")
    assert lines[-1] == "" and lines[-2] == f"  Z2k Retro's HD Cinematics: {info['size']:,} bytes verified"
    bar = lines[-3]
    assert bar.count("\r") >= len(paths) - 1 and "\n" not in bar, "ONE bar line across every part"
    assert bar.rsplit("\r", 1)[-1].split("]")[1].strip().startswith("100.0%")
    assert not fetch._LINE_OPEN


def test_a_single_download_still_ends_its_bar_line(tmp_path, pack, monkeypatch):
    archive, _paths, info = pack
    out = _Tty()
    monkeypatch.setattr(sys, "stdout", out)
    fetch.download(archive.as_uri(), tmp_path / "one.zip", sha256=info["sha256"], size=info["size"],
                   allow_file=True, label="pack")
    lines = out.getvalue().split("\n")
    assert "100.0%" in lines[-3] and lines[-2].endswith("bytes verified") and lines[-1] == ""
    assert not fetch._LINE_OPEN


# ---------------------------------------------------------------- preflight.check_archives

def _check(tmp_path, info, **kw):
    import preflight as pfm
    pf = pfm.Preflight()
    staging = tmp_path / "game" / "LongevityMods" / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    pfm.check_archives(pf, {"modules": {"movies-hd": info}}, staging, ["movies-hd"], allow_file=True,
                       labels={"movies-hd": "Z2k Retro's HD Cinematics"}, **kw)
    return pf


def test_the_preflight_stages_a_split_pack_as_its_parts(tmp_path, pack):
    _archive, paths, info = pack
    pf = _check(tmp_path, info)
    assert pf.ok, [(c.name, c.detail) for c in pf.blockers]
    staged = pf.staged["movies-hd"]
    assert isinstance(staged, tuple)
    assert [p.name for p in staged] == [f"movies-hd.{pt['sha256'][:16]}.{i:03d}"
                                        for i, pt in enumerate(info["parts"], 1)]
    assert all(p.parent.name == "movies-hd" for p in staged)
    assert [p.read_bytes() for p in staged] == [p.read_bytes() for p in paths]
    assert any("readable archive" in c.name and c.ok for c in pf.checks)


def test_a_malformed_split_entry_downloads_nothing(tmp_path, pack, monkeypatch):
    _archive, _paths, info = pack
    info["url"] = info["parts"][0]["url"]
    monkeypatch.setattr(fetch, "download", lambda *a, **k: pytest.fail("nothing may be downloaded"))
    pf = _check(tmp_path, info)
    assert "movies-hd" not in pf.staged
    bad = [c for c in pf.checks if not c.ok]
    assert bad and "malformed" in bad[0].detail and bad[0].advisory


def test_parts_in_the_wrong_order_are_refused_before_anything_is_placed(tmp_path, pack):
    _archive, _paths, info = pack
    info["parts"][0], info["parts"][1] = info["parts"][1], info["parts"][0]
    pf = _check(tmp_path, info)
    assert "movies-hd" not in pf.staged
    assert any("readable archive" in c.name and not c.ok for c in pf.checks)


def test_the_free_space_check_counts_the_total_size(tmp_path, pack, monkeypatch):
    """Unchanged rule: the archive plus what it expands to. Parts are never joined on disk, so the total is right."""
    import preflight as pfm
    _archive, _paths, info = pack
    doc = {"min_free_bytes": 1000, "modules": {"movies-hd": info}}
    asked = []

    def fake_manifest(pf, *a, **k):
        pf.doc = doc
        pf.decision = mf.Decision(mf.UPDATE, version="1.0.1", modules=[])
    monkeypatch.setattr(pfm, "check_game_dir", lambda pf, g: True)
    monkeypatch.setattr(pfm, "check_target_and_backup", lambda *a, **k: None)
    monkeypatch.setattr(pfm, "check_not_locked", lambda *a, **k: None)
    monkeypatch.setattr(pfm, "check_manifest", fake_manifest)
    monkeypatch.setattr(pfm, "check_space", lambda pf, g, need: asked.append(need))
    monkeypatch.setattr(pfm, "check_archives", lambda *a, **k: None)
    monkeypatch.setattr(pfm, "check_patch_plan", lambda *a, **k: None)
    pfm.run(game_dir=tmp_path, target=tmp_path / "t.exe", patches=tmp_path, table={}, manifest_raw=b"{}",
            wanted_modules=["movies-hd"])
    assert asked == [1000 + 2 * info["size"]]


def test_a_stopped_part_is_never_resumed_against_another_releases_part(tmp_path, pack, part_server):
    """Audit P2: a download stopped part-way under one release, then a manifest naming a NEW release of the pack
    behind the same URLs. The leftover must not be resumed (a new tail spliced onto an old prefix, a whole part thrown
    away when the hash fails): no Range request, and not one byte fetched beyond the new pack. Leftovers under the
    index-only names an earlier client used are not resumed either, and are removed; nothing else is touched."""
    archive, paths, info_a = pack
    stage = tmp_path / "game" / "LongevityMods" / "staging" / "movies-hd"
    stage.mkdir(parents=True)
    stale = stage / f"movies-hd.{info_a['parts'][1]['sha256'][:16]}.002.part"      # release A, stopped in part 2
    stale.write_bytes(paths[1].read_bytes()[:1000])
    old_style = [stage / "movies-hd.002.part", stage / "movies-hd.001", stage / "MOVIES-HD.003"]
    old_style[0].write_bytes(paths[1].read_bytes()[:1000])
    old_style[1].write_bytes(paths[0].read_bytes())
    old_style[2].write_bytes(paths[2].read_bytes())
    unrelated = [stage / "LV-movies-hd-1.0.0.zip.part", stage / "movies-hd.002.txt", stage / "movies-hd.12.part"]
    for u in unrelated:
        u.write_bytes(b"not a part of ours")

    bdir = tmp_path / "distB"
    bdir.mkdir()
    b = rel.split_archive(_pack_zip(bdir / archive.name, seed=99), "movies-hd", "2.0.0", PART_MAX)
    assert [p["size"] for p in b] == [p.stat().st_size for p in paths]
    assert all(x["sha256"] != y["sha256"] for x, y in zip(b, info_a["parts"]))
    info_b = dict(info_a, sha256="0" * 64,
                  parts=[{"url": pt["url"], "sha256": bp["sha256"], "size": bp["size"]}
                         for pt, bp in zip(info_a["parts"], b)])
    part_server.files = {f"/{p.name}": Path(bp["path"]).read_bytes() for p, bp in zip(paths, b)}
    part_server.seen.clear()
    part_server.sent = 0

    pf = _check(tmp_path, info_b)
    assert pf.ok, [(c.name, c.detail) for c in pf.blockers]
    assert part_server.seen and all(rng is None for _, rng in part_server.seen), "nothing was resumed"
    assert part_server.sent == info_b["size"], "not one byte fetched twice or thrown away"
    assert [p.read_bytes() for p in pf.staged["movies-hd"]] == [Path(bp["path"]).read_bytes() for bp in b]
    assert not stale.exists() and not any(p.exists() for p in old_style)
    assert all(u.exists() for u in unrelated), "only our part names are swept"


def test_the_sweep_never_acts_through_a_link(tmp_path, pack, monkeypatch):
    import preflight as pfm
    import safe_fs
    folder = tmp_path / "staging" / "movies-hd"
    folder.mkdir(parents=True)
    leftover = folder / "movies-hd.001"
    leftover.write_bytes(b"x")
    monkeypatch.setattr(safe_fs, "link_on_path", lambda root, target: True)
    pfm._sweep_stale_parts(folder, "movies-hd", [], tmp_path)
    assert leftover.exists()


def test_parts_whose_urls_share_a_file_name_are_staged_apart(tmp_path, pack):
    """Staged by index, never by the URL's name: `a.001` and `a.001.` are one file on Windows, and one part's
    `.part` could be another's final name."""
    _archive, paths, info = pack
    for i, (pt, p) in enumerate(zip(info["parts"], paths)):
        d = tmp_path / "hosts" / f"h{i}"
        d.mkdir(parents=True)
        q = d / ("a.001." if i % 2 else "a.001")
        q.write_bytes(p.read_bytes())
        pt["url"] = q.as_uri()
    pf = _check(tmp_path, info)
    assert pf.ok, [(c.name, c.detail) for c in pf.blockers]
    assert [p.read_bytes() for p in pf.staged["movies-hd"]] == [p.read_bytes() for p in paths]


# ---------------------------------------------------------------- install.py

pytestmark = pytest.mark.usefixtures("install_globals")


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_a_split_pack_installs_exactly_as_the_same_pack_unsplit(tmp_path, pack):
    import install as inst
    archive, paths, _info = pack
    inst._load_modules()
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    out_a = inst.install_modules(a, {"movies-hd": archive}, {"movies-hd": "2.0.0"})
    out_b = inst.install_modules(b, {"movies-hd": tuple(paths)}, {"movies-hd": "2.0.0"})
    assert out_a == out_b and out_b["movies-hd"]["files"]
    assert _tree(a) == _tree(b) and (b / "movies" / "hd" / "pack-manifest.json").is_file()


def test_a_split_pack_still_places_its_manifest_last(tmp_path, pack, monkeypatch):
    import install as inst
    _archive, paths, _info = pack
    inst._load_modules()
    game = tmp_path / "g"
    game.mkdir()
    order = []
    real = Path.replace
    monkeypatch.setattr(Path, "replace", lambda self, dest: order.append(Path(dest).name) or real(self, dest))
    inst.install_modules(game, {"movies-hd": tuple(paths)}, {"movies-hd": "2.0.0"})
    assert order[-2:] == ["PROVENANCE.txt", "pack-manifest.json"]


def test_the_install_list_offers_a_split_pack_at_its_total_size(tmp_path, pack, monkeypatch):
    import install as inst
    import installer_exit as ix
    _archive, _paths, info = pack
    inst._load_modules()
    game = tmp_path / "g"
    game.mkdir()
    doc = {"modules": {"movies-hd": info}}
    monkeypatch.setattr(ix, "has_console", lambda: False)
    monkeypatch.setattr(inst, "_thinker_off_pin", lambda g: False)
    monkeypatch.setattr(inst, "fetch_manifest", lambda *a, **k: (b"{}", "sig"))
    monkeypatch.setattr(mf, "load_verified", lambda *a, **k: doc)
    args = types.SimpleNamespace(pack=str(tmp_path / "none"), portrait_pack=str(tmp_path / "none"), ai="ask",
                                 modules="movies-hd", no_prompt=False, manifest=None, offline=False)
    cat = inst.module_catalogue(game, args)[0]
    assert cat["movies-hd"]["size"] == info["size"] and cat["movies-hd"]["source"] == "manifest"
    info["parts"][0]["size"] += 1                                       # malformed: not offered
    assert "movies-hd" not in inst.module_catalogue(game, args)[0]
    info["parts"][0]["size"] -= 1
    info["url"] = "https://h/LV-movies-hd-2.0.0.zip"                    # a url beside parts: malformed, not offered
    assert "movies-hd" not in inst.module_catalogue(game, args)[0]


def test_nothing_holds_a_part_open_after_the_preflight_and_the_install(tmp_path, pack):
    """Windows refuses to rename a file something still has open: every part must be closed on every path."""
    import install as inst
    import os
    _archive, _paths, info = pack
    inst._load_modules()
    pf = _check(tmp_path, info)
    staged = pf.staged["movies-hd"]
    game = tmp_path / "g2"
    game.mkdir()
    inst.install_modules(game, {"movies-hd": staged}, {"movies-hd": "2.0.0"})
    for p in staged:
        os.replace(p, p.with_name(p.name + ".moved"))
        os.replace(p.with_name(p.name + ".moved"), p)


def test_the_rollback_rule_is_checked():
    doc = {"latest": "1.0.1", "yanked": [], "modules": {"movies-hd": {"parts": []}, "base": {}}}
    assert rel.parts_rollback_problem(doc) is None
    assert rel.parts_rollback_problem(doc | {"latest": "1.2.0"}) is None
    assert "older than 1.0.1" in rel.parts_rollback_problem(doc | {"latest": "1.0.0"})
    assert "older than 1.0.1" in rel.parts_rollback_problem(doc | {"latest": "garbage"})
    assert "is yanked" in rel.parts_rollback_problem(doc | {"yanked": ["1.0.1 "]})
    assert rel.parts_rollback_problem({"latest": "1.0.0", "modules": {"base": {}, "movies-hd": {"url": "x"}}})         is None, "no split pack: nothing to protect"
