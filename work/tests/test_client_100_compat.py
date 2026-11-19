"""The PUBLISHED 1.0.0 client against a manifest the CURRENT release.py writes.

1.0.0 is in players' hands and never changes, so the manifest is the only lever: whatever it carries must keep that
client's behaviour right. Run here against the real 1.0.0 sources (git, release commit b7fa02c), in a subprocess so
its modules never mix with the current ones. Pinned, for a split pack (work/briefs/split-cinematics-pack.md):

  * `--check` still prints ONE `new=` / `stale=` line per pack with the TOTAL size -- the game's "4.6 GB" offer;
  * decide() still calls the stale pack an update (the update itself runs in generation 2, the NEW code);
  * the 1.0.0 fresh install does NOT list the split pack and downloads nothing for it (no top-level `url`): with one
    it would fetch the first part three times and fail;
  * 1.0.0 generation 1 still fetches the new installer from `base.url`.

Skipped where the 1.0.0 commit is not in the repository (a public-source checkout).
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO = _TESTS.parent.parent
_SCRIPTS = _TESTS.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import release as rel        # noqa: E402
import version as ver        # noqa: E402

RELEASE_100 = "b7fa02c904fd2a63906f0cbe67f1b2d0ba116ea3"
RELEASE_100_FALLBACK = "v1.0.0"
TOTAL = 4_963_447_978

_PROBE = r'''
import json, sys, types
from pathlib import Path
scripts, doc_path, work = sys.argv[1], sys.argv[2], Path(sys.argv[3])
sys.path.insert(0, scripts)
import installer_exit as ix
import install as inst
inst._load_modules()
import manifest as mf, preflight as pfm, fetch, bootstrap as bs
doc = json.loads(Path(doc_path).read_text(encoding="utf-8"))
res = {}
res["new"] = list(inst.check_report(doc, {"modules": {"base": {"version": "1.0.0"}}}, {}, None))
res["stale"] = list(inst.check_report(
    doc, {"modules": {"base": {"version": "1.0.0"}, "movies-hd": {"version": "1.0.0"}}}, {}, None))
d = mf.decide(doc, "1.0.0", None, installed_modules={"movies-hd": "1.0.0"})
res["decide"] = [d.action, d.version, d.modules]
# A rollback: `latest` back at 1.0.0. bootstrap.run's in-place test is `not is_newer(latest, resident)`.
import version as v0
d2 = mf.decide(dict(doc, latest="1.0.0"), "1.0.0", None, installed_modules={"movies-hd": "1.0.0"})
res["rollback"] = [d2.action, d2.version, d2.modules, not v0.is_newer(d2.version or "1.0.0", "1.0.0")]

calls = []
def no_network(url, *a, **k):
    calls.append(url)
    raise fetch.FetchError("no network in this test")
fetch.download = no_network
inst.fetch_manifest = lambda *a, **k: (b"", "")
mf.load_verified = lambda *a, **k: doc
ix.can_ask = lambda: False
game = work / "game"
game.mkdir()
args = types.SimpleNamespace(pack=str(work / "none"), portrait_pack=str(work / "none"), ai="ask",
                             modules="movies-hd", manifest=None, offline=False)
res["catalogue"] = sorted(inst.module_catalogue(game, args)[0])
pf = pfm.Preflight()
staging = game / "LongevityMods" / "staging"
staging.mkdir(parents=True)
pfm.check_archives(pf, doc, staging, ["movies-hd"], explicit={"movies-hd"})
res["archives"] = [[c.name, c.ok, c.detail, c.advisory] for c in pf.checks]
res["staged"] = sorted(pf.staged)
res["downloads_before_gen1"] = list(calls)
try:
    bs._download_new_payload(game, doc["modules"]["base"], "1.0.1", types.SimpleNamespace(manifest=None))
except ix.InstallerError:
    pass
res["gen1"] = calls[len(res["downloads_before_gen1"]):]
print("RESULT " + json.dumps(res))
'''


@pytest.fixture(scope="module")
def client_100(tmp_path_factory):
    """The 1.0.0 work/scripts tree, extracted once: from the commit the release was cut from (the maintainer's
    checkout), else the public tag v1.0.0 (a clone of the public repository has no private history; the tag
    marks the same installer sources)."""
    rev = None
    for cand in (RELEASE_100, RELEASE_100_FALLBACK):
        try:
            if subprocess.run(["git", "-C", str(_REPO), "cat-file", "-e", cand + "^{commit}"],
                              capture_output=True, timeout=60).returncode == 0:
                rev = cand
                break
        except (OSError, subprocess.SubprocessError):
            pass
    if rev is None:
        pytest.skip(f"the 1.0.0 sources (commit {RELEASE_100[:7]} or tag {RELEASE_100_FALLBACK}) are not in "
                    "this repository")
    tar = subprocess.run(["git", "-C", str(_REPO), "archive", "--format=tar", rev, "work/scripts"],
                         capture_output=True, timeout=300, check=True).stdout
    root = tmp_path_factory.mktemp("client-1.0.0")
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(root, filter="data")
    return root / "work" / "scripts"


def _manifest() -> dict:
    """The modules exactly as the CURRENT release.py writes them: the Cinematics split, the rest whole."""
    sizes = rel.plan_slices(TOTAL)
    movies = rel._module_entry("movies-hd", {"version": "2.0.0", "sha256": "b" * 64, "size": TOTAL,
                                             "parts": [{"sha256": f"{i}" * 64, "size": s}
                                                       for i, s in enumerate(sizes, 1)]},
                               rel.BASE_URL, rel.PACK_URL)
    base = rel._module_entry("base", {"version": "1.0.1", "sha256": "a" * 64, "size": 20_729_810},
                             rel.BASE_URL, rel.PACK_URL)
    portraits = rel._module_entry("portraits-hd", {"version": "1.0.0", "sha256": "c" * 64, "size": 30_150_491},
                                  rel.BASE_URL, rel.PACK_URL)
    return {"schema": 1, "protocol": 1, "product": "longevity-vaccine", "latest": "1.0.1",
            "min_upgradable_from": ver.MIN_UPGRADABLE_FROM, "manual_install_required": False,
            "manual_install_reason": None, "unsupported_versions": [], "unsupported_targets": [],
            "targets": {}, "min_free_bytes": 3 * 1024 ** 3,
            "modules": {"base": base, "movies-hd": movies, "portraits-hd": portraits}, "yanked": []}


@pytest.fixture(scope="module")
def answers(client_100, tmp_path_factory):
    work = tmp_path_factory.mktemp("probe")
    doc = work / "manifest.json"
    doc.write_text(json.dumps(_manifest()), encoding="utf-8")
    probe = work / "probe.py"
    probe.write_text(_PROBE, encoding="utf-8")
    p = subprocess.run([sys.executable, str(probe), str(client_100), str(doc), str(work)],
                       capture_output=True, text=True, timeout=300, cwd=str(work))
    line = next((ln for ln in p.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, f"the 1.0.0 probe did not finish:\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}"
    return json.loads(line[len("RESULT "):])


def _pack_lines(lines, prefix):
    return [ln for ln in lines if ln.startswith(prefix + "movies-hd|")]


def test_the_100_check_offers_the_new_pack_once_at_its_total_size(answers):
    _code, lines = answers["new"]
    got = _pack_lines(lines, "new=")
    assert len(got) == 1 and got[0].endswith(f"|2.0.0|{TOTAL}"), lines
    assert "base=1.0.0>1.0.1" in lines


def test_the_100_check_offers_the_stale_pack_once_at_its_total_size(answers):
    _code, lines = answers["stale"]
    got = _pack_lines(lines, "stale=")
    assert len(got) == 1 and got[0].endswith(f"|1.0.0>2.0.0|{TOTAL}"), lines


def test_the_100_decision_still_updates_the_stale_pack(answers):
    assert answers["decide"] == ["update", "1.0.1", ["movies-hd"]]


def test_a_100_fresh_install_neither_lists_nor_fetches_the_split_pack(answers):
    assert "movies-hd" not in answers["catalogue"] and "portraits-hd" in answers["catalogue"]
    assert answers["staged"] == [] and answers["downloads_before_gen1"] == []
    (name, ok, detail, advisory), = answers["archives"]
    assert not ok and advisory and "lacks a url" in detail


def test_a_rollback_would_send_100_players_to_their_own_installer_so_it_is_refused(answers):
    """Why the rollback rule exists: at `latest` 1.0.0 the stale split pack is still an update, and 1.0.0's bootstrap
    applies it IN PLACE -- with the 1.0.0 installer, whose check_archives refuses a pack without a url (above). So the
    pipeline refuses to build or publish such a manifest."""
    action, version, modules, in_place = answers["rollback"]
    assert (action, version, modules, in_place) == ("update", "1.0.0", ["movies-hd"], True)
    assert "older than 1.0.1" in rel.parts_rollback_problem(dict(_manifest(), latest="1.0.0"))
    assert rel.parts_rollback_problem(_manifest()) is None


def test_100_generation_one_still_fetches_the_installer_from_base_url(answers):
    assert answers["gen1"] == [_manifest()["modules"]["base"]["url"]]
