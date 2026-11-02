"""The multi-target base table (patches.yaml schema 0.3).

Before this, the patcher hardcoded a two-way branch on two MD5s, so supporting another base meant
editing code. The table makes it a data change. These tests pin the two properties that matter:

  1. The table cannot DRIFT from the authoritative `target:` lock block it mirrors.
  2. A declared-but-unmeasured entry can never match a real file, so the installer reports an
     unsupported base rather than patching bytes it has never verified.
  3. (schema 0.4, 2026-10-28) `pracx_thinker` is a FOLDER-DETECTED OVERLAY of `pracx`: same base hash
     (Thinker patches terranx.exe in memory only), chosen only when thinker.dll sits beside the exe,
     with four sites excluded on disk (user decisions; uimod.dll applies them after Thinker).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import apply_patches as ap  # noqa: E402

LAUNCH_TARGETS = {"pracx", "pracx_thinker"}
DEV_ONLY_TARGETS = {"vanilla"}
#: The four sites left unpatched on disk under Thinker (ACTION_ITEMS "THINKER" decisions 1-3, 2026-10-28).
THINKER_EXCLUDED = {"Caviar.E_imm_618a92", "SetupWin_draw_item.decoration_keyed_scaled",
                    "SetupWin_draw_item.decoration_soft_update_scaled", "load_credits_a.subwin"}


@pytest.fixture(scope="module")
def spec(patches_path) -> dict:
    return ap._yaml_load(patches_path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def targets(patches_path) -> dict:
    t = ap.load_targets(patches_path)
    assert t, "patches.yaml has no `targets:` table"
    return t


# ---------------------------------------------------------------- schema

def test_the_expected_targets_exist(targets):
    assert set(targets) == LAUNCH_TARGETS | DEV_ONLY_TARGETS


def test_launch_flags_match_the_shipping_decision(targets):
    """Vanilla was dropped as a shipping configuration (user decision 2026-09-21)."""
    assert {tid for tid, t in targets.items() if t.launch} == LAUNCH_TARGETS
    assert {tid for tid, t in targets.items() if not t.launch} == DEV_ONLY_TARGETS


def test_every_entry_has_a_label_and_an_exe(targets):
    for tid, t in targets.items():
        assert t.label and t.label != tid, f"{tid} needs a human label for the error message"
        assert t.exe, f"{tid} should name its expected exe"


def test_measured_entries_carry_a_full_fingerprint(targets):
    for tid, t in targets.items():
        if not t.measured:
            continue
        assert len(t.base_md5) == 32, tid
        assert t.base_sha256 and len(t.base_sha256) == 64, tid
        assert t.base_size and t.base_size > 0, tid


def test_no_entry_is_left_pending(targets):
    """Every shipped entry has been measured on real bytes (the Thinker ones on 2026-10-28). A pending
    entry can never resolve, so one here would be a declared configuration nobody can install."""
    assert {tid for tid, t in targets.items() if t.pending} == set()
    for tid, t in targets.items():
        assert t.measured, tid


# ---------------------------------------------------------------- the Thinker overlay (schema 0.4)

def test_pracx_thinker_is_a_folder_detected_overlay_of_pracx(targets):
    """Thinker patches the exe IN MEMORY, so on disk PRACX + Thinker is PRACX's own base named
    terranx.exe; thinker.dll beside it is what tells the two apart."""
    t, p = targets["pracx_thinker"], targets["pracx"]
    assert t.base_md5 == p.base_md5 and t.base_sha256 == p.base_sha256 and t.base_size == p.base_size
    assert t.requires_files == ["thinker.dll"]
    assert p.requires_files == [] and targets["vanilla"].requires_files == []
    assert t.exe == "terranx.exe", "Thinker's launcher starts that name and nothing else"
    assert t.launcher == "thinker.exe" and p.launcher is None
    assert t.groups is None, "every group applies; only SITES are excluded"
    assert t.companion == p.companion, "prax.dll is patched the same way under Thinker"
    assert t.patched_md5 and t.patched_md5 != p.patched_md5, "4 fewer sites -> a lock of its own"


def test_pracx_thinker_excludes_exactly_the_decided_sites(targets, spec):
    known = {s["id"] for s in spec["sites"]}
    assert set(targets["pracx_thinker"].exclude_sites) == THINKER_EXCLUDED
    assert THINKER_EXCLUDED <= known
    for tid in ("pracx", "vanilla"):
        assert targets[tid].exclude_sites == []


def test_the_overlay_is_chosen_only_when_its_files_are_present(targets):
    md5 = targets["pracx"].base_md5
    assert ap.resolve_target(md5, targets).id == "pracx", "no folder given -> the plain entry"
    assert ap.resolve_target(md5, targets, present_files=set()).id == "pracx"
    assert ap.resolve_target(md5, targets, present_files={"terranx.exe", "prax.dll"}).id == "pracx"
    assert ap.resolve_target(md5, targets, present_files={"terranx.exe", "thinker.dll"}).id == "pracx_thinker"
    assert ap.resolve_target(md5, targets, present_files={"THINKER.DLL"}).id == "pracx_thinker", "case-insensitive"
    assert ap.resolve_target(md5, targets, present_files={"thinker.dll"}, launch_only=True).id == "pracx_thinker"


def test_overlay_selection_does_not_depend_on_table_order():
    md5 = "c" * 32
    plain = ap.TargetSpec("plain", {"label": "Plain", "exe": "x.exe", "launch": True, "base_md5": md5})
    over = ap.TargetSpec("over", {"label": "Over", "exe": "x.exe", "launch": True, "base_md5": md5,
                                  "requires_files": ["mod.dll"]})
    for order in ({"plain": plain, "over": over}, {"over": over, "plain": plain}):
        assert ap.resolve_target(md5, order, present_files={"mod.dll"}).id == "over", list(order)
        assert ap.resolve_target(md5, order, present_files=set()).id == "plain", list(order)
        assert ap.resolve_target(md5, order).id == "plain", list(order)


def test_an_overlay_alone_never_resolves_without_its_files():
    """An overlay with no plain sibling is still unreachable without its files: the folder is part of
    the identity, not a hint."""
    md5 = "d" * 32
    tbl = {"over": ap.TargetSpec("over", {"label": "Over", "exe": "x.exe", "launch": True,
                                          "base_md5": md5, "requires_files": ["mod.dll"]})}
    with pytest.raises(ap.UnsupportedBase):
        ap.resolve_target(md5, tbl, present_files=set())
    assert ap.resolve_target(md5, tbl, present_files={"mod.dll"}).id == "over"


def test_folder_files_lists_file_names_lower_cased(tmp_path):
    (tmp_path / "Thinker.DLL").write_bytes(b"x")
    (tmp_path / "sub").mkdir()
    assert ap.folder_files(tmp_path) == {"thinker.dll"}
    assert ap.folder_files(tmp_path / "missing") == set()


@pytest.mark.parametrize("field", ["requires_files", "exclude_sites"])
def test_bare_string_name_lists_are_rejected(field):
    with pytest.raises(ValueError) as e:
        ap.TargetSpec("t", {field: "thinker.dll"})
    assert "must be a YAML list" in str(e.value)
    for bad in ([""], [1], 42):
        with pytest.raises(ValueError):
            ap.TargetSpec("t", {field: bad})
    assert ap.TargetSpec("t", {}).requires_files == [] and ap.TargetSpec("t", {}).exclude_sites == []


def test_an_unknown_excluded_site_is_refused_before_any_write(bak_path, tmp_path, patches_path):
    import shutil
    tgt = tmp_path / "copy.exe"
    shutil.copy2(bak_path, tgt)
    before = tgt.read_bytes()
    spec = ap.TargetSpec("x", {"label": "X", "exe": "x.exe", "launch": False, "base_md5": ap.EXPECTED_MD5,
                               "base_size": ap.EXPECTED_SIZE, "exclude_sites": ["no.such.site"]})
    assert ap.apply_patches(tgt, patches_path, do_apply=True, spec=spec) == 4
    assert tgt.read_bytes() == before


def test_the_thinker_bake_leaves_exactly_the_excluded_bytes_clean(bak_path, baked_exe, tmp_path,
                                                                  patches_path, targets, loaded):
    """The overlay's output = the pracx bake with the four excluded sites still holding the clean base's
    bytes, and nothing else different. Built once here from the API (the dry-run-only rule is
    satisfied by the recorded lock)."""
    import shutil
    tgt = tmp_path / "thinker.exe"
    shutil.copy2(bak_path, tgt)
    assert ap.apply_patches(tgt, patches_path, do_apply=True, spec=targets["pracx_thinker"]) == 0
    out = tgt.read_bytes()
    import hashlib
    assert hashlib.md5(out).hexdigest() == targets["pracx_thinker"].patched_md5
    clean, pracx = bak_path.read_bytes(), baked_exe.read_bytes()
    import pefile
    res = ap.VaResolver(pefile.PE(data=clean, fast_load=True))
    excluded_spans = []
    for s in loaded["sites"]:
        if s["id"] in THINKER_EXCLUDED:
            off = res.to_file_offset(int(s["virtual_addr"]))
            excluded_spans.append((off, off + int(s["length"])))
            assert out[off:off + int(s["length"])] == clean[off:off + int(s["length"])], s["id"]
            assert pracx[off:off + int(s["length"])] != clean[off:off + int(s["length"])], s["id"]
    assert len(excluded_spans) == len(THINKER_EXCLUDED)
    diff = [i for i in range(len(out)) if out[i] != pracx[i]]
    assert all(any(a <= i < b for a, b in excluded_spans) for i in diff), "a byte outside the excluded sites differs"


def test_explicit_group_lists_name_real_groups(targets, spec):
    known = {g["id"] for g in (spec.get("groups") or [])}
    for tid, t in targets.items():
        if t.groups is None:
            continue
        for gid in t.groups:
            assert gid in known, f"target {tid} names group {gid!r}, which is not in patches.yaml"


def test_all_means_every_eligible_group(targets):
    """`groups: all` must normalise to None -- what apply_patches() spells as 'no restriction'."""
    assert targets["pracx"].groups is None


# ---------------------------------------------------------------- anti-drift

def test_pracx_entry_mirrors_the_authoritative_target_block(targets, spec):
    """The `target:` block stays the lock; this entry mirrors it. They must never disagree."""
    legacy = spec["target"]
    t = targets["pracx"]
    assert t.base_md5 == legacy["md5"].lower()
    assert t.base_sha256 == legacy["sha256"].lower()
    assert t.base_size == legacy["size"]
    assert t.patched_md5 == legacy["patched_md5"], (
        "targets.pracx.patched_md5 drifted from target.patched_md5 -- update both when the "
        "build hash moves."
    )


def test_vanilla_entry_mirrors_the_pristine_lock(targets, spec):
    legacy = spec["target"]
    t = targets["vanilla"]
    assert t.base_md5 == legacy["pristine_md5"].lower()
    assert t.base_sha256 == legacy["pristine_sha256"].lower()


def test_vanilla_groups_match_the_legacy_pristine_set(targets):
    assert targets["vanilla"].groups == list(ap.PRISTINE_GROUPS)


def test_legacy_constants_still_agree_with_the_table(targets):
    """The module constants are now aliases; they must not diverge from the data."""
    assert targets["pracx"].base_md5 == ap.EXPECTED_MD5.lower()
    assert targets["pracx"].base_size == ap.EXPECTED_SIZE
    assert targets["vanilla"].base_md5 == ap.PRISTINE_MD5.lower()
    assert targets["vanilla"].exe == ap.PRISTINE_EXE


def test_companion_binaries_are_declared_with_their_own_patch_file(targets):
    comp = targets["pracx"].companion
    assert "prax.dll" in comp, "the PRACX target also patches prax.dll"
    assert comp["prax.dll"]["patches"] == "patches_prax.yaml"
    assert len(comp["prax.dll"]["base_md5"]) == 32
    assert len(comp["prax.dll"]["patched_md5"]) == 32


def test_companion_hashes_match_the_prax_lock(targets, patches_path):
    prax = ap._yaml_load((patches_path.parent / "patches_prax.yaml").read_text(encoding="utf-8"))
    comp = targets["pracx"].companion["prax.dll"]
    assert comp["base_md5"] == prax["target"]["md5"]
    assert comp["patched_md5"] == prax["target"]["patched_md5"]


def test_no_two_plain_targets_share_a_base_hash(targets):
    """Two PLAIN entries with the same base would make resolution order-dependent. An overlay
    (`requires_files`) may share its plain sibling's hash -- the folder decides between them."""
    seen = {}
    for tid, t in targets.items():
        if not t.measured or t.requires_files:
            continue
        assert t.base_md5 not in seen, f"{tid} and {seen[t.base_md5]} share base {t.base_md5}"
        seen[t.base_md5] = tid
    for tid, t in targets.items():
        if t.requires_files:
            assert t.base_md5 in seen, f"overlay {tid} has no plain sibling for base {t.base_md5}"


# ---------------------------------------------------------------- resolution

def test_resolves_each_measured_base(targets):
    for tid, t in targets.items():
        if t.measured:
            files = set(t.requires_files) if t.requires_files else None
            assert ap.resolve_target(t.base_md5, targets, present_files=files).id == tid


def test_resolution_is_case_insensitive(targets):
    md5 = targets["pracx"].base_md5
    assert ap.resolve_target(md5.upper(), targets).id == "pracx"


def test_unknown_base_raises_with_the_supported_labels(targets):
    with pytest.raises(ap.UnsupportedBase) as e:
        ap.resolve_target("0" * 32, targets)
    assert e.value.md5 == "0" * 32
    # The message must name what IS supported -- a bare hash is useless to a player.
    assert "PRACX" in str(e.value)
    for tid in DEV_ONLY_TARGETS:
        assert targets[tid].label not in e.value.labels, "dev-only targets must not be advertised"


@pytest.mark.parametrize("bad", ["", None, "not-a-hash", "0" * 31, "0" * 33])
def test_malformed_hashes_never_resolve(targets, bad):
    with pytest.raises(ap.UnsupportedBase):
        ap.resolve_target(bad, targets)


def test_launch_only_refuses_the_dev_target(targets):
    """The shipping installer must not patch a base that was dropped from support."""
    vanilla = targets["vanilla"].base_md5
    assert ap.resolve_target(vanilla, targets).id == "vanilla"   # dev path still works
    with pytest.raises(ap.UnsupportedBase):
        ap.resolve_target(vanilla, targets, launch_only=True)


def test_a_dev_only_entry_does_not_short_circuit_the_scan():
    """REGRESSION: `launch_only` used to `break` on a rejected match instead of continuing, so a
    shipping entry that shared a base with a dev-only one was reported unsupported -- and which
    answer you got depended on dict insertion order."""
    md5 = "b" * 32
    dev = ap.TargetSpec("dev", {"label": "Dev", "exe": "x.exe", "launch": False,
                                "base_md5": md5})
    ship = ap.TargetSpec("ship", {"label": "Ship", "exe": "x.exe", "launch": True,
                                  "base_md5": md5})
    for order in ({"dev": dev, "ship": ship}, {"ship": ship, "dev": dev}):
        assert ap.resolve_target(md5, order, launch_only=True).id == "ship", list(order)


def test_unsupported_message_advertises_only_measured_launch_targets():
    """REGRESSION: the label list came from every `launch` entry, so a Thinker user was told
    "Supported: ... Thinker ..." and then refused -- naming as supported a configuration that could
    not resolve. Now both shipped entries are measured, and the dev-only one stays out."""
    tbl = ap.load_targets()
    with pytest.raises(ap.UnsupportedBase) as e:
        ap.resolve_target("0" * 32, tbl)
    assert e.value.labels == [tbl["pracx"].label, tbl["pracx_thinker"].label]
    assert tbl["vanilla"].label not in e.value.labels
    pend = dict(tbl)
    pend["x"] = ap.TargetSpec("x", {"label": "Pending one", "exe": "x.exe", "launch": True,
                                    "pending": "measurement"})
    with pytest.raises(ap.UnsupportedBase) as e:
        ap.resolve_target("0" * 32, pend)
    assert "Pending one" not in e.value.labels, "an unmeasured entry must not be advertised"


@pytest.mark.parametrize("bad", [123, 1.5, [], {}, object(), b"a" * 32])
def test_non_string_md5_raises_unsupportedbase_not_attributeerror(bad):
    with pytest.raises(ap.UnsupportedBase):
        ap.resolve_target(bad, ap.load_targets())


# ---------------------------------------------------------------- groups normalisation

@pytest.mark.parametrize("g", ["all", "All", "ALL", " all ", None])
def test_all_forms_of_all_mean_no_restriction(g):
    assert ap.TargetSpec("t", {"groups": g}).groups is None


def test_a_bare_string_group_is_rejected_not_split_into_characters():
    """`groups: uimod_bootstrap_native` (no brackets) is the natural mistake when adding a
    target. list() on a str yields its CHARACTERS, which would restrict the run to ~22 one-letter
    group names, skip every group, and leave the exe 'patched' with zero changes."""
    with pytest.raises(ValueError) as e:
        ap.TargetSpec("t", {"groups": "uimod_bootstrap_native"})
    assert "must be a YAML list" in str(e.value)
    assert "[uimod_bootstrap_native]" in str(e.value), "the error should show the fix"


def test_an_empty_group_list_is_rejected():
    """apply_patches gates on `if only_groups:`, so [] is falsy and means "apply EVERY group" --
    the opposite of what someone writing "nothing is eligible yet" intends, and the worst
    possible default on an unverified base."""
    with pytest.raises(ValueError) as e:
        ap.TargetSpec("t", {"groups": []})
    assert "pending: measurement" in str(e.value), "the error should name the right alternative"


@pytest.mark.parametrize("g", [[1, 2], [None], [["nested"]], 42])
def test_malformed_group_values_are_rejected(g):
    with pytest.raises(ValueError):
        ap.TargetSpec("t", {"groups": g})


def test_patched_md5_is_lower_cased_like_the_other_hashes():
    t = ap.TargetSpec("t", {"base_md5": "A" * 32, "patched_md5": "B" * 32})
    assert t.base_md5 == "a" * 32
    assert t.patched_md5 == "b" * 32, "an upper-case spelling would fail the drift test spuriously"


# ---------------------------------------------------------------- multi-binary CLI

_PY = Path(__file__).resolve().parent.parent.parent / "tools" / "python" / "python.exe"
_APPLY = _SCRIPTS = Path(__file__).resolve().parent.parent / "scripts" / "apply_patches.py"


def _cli(*args, timeout=300):
    import subprocess
    return subprocess.run([str(_PY), str(_APPLY), *args],
                          capture_output=True, text=True, timeout=timeout)


@pytest.mark.skipif(not _PY.exists(), reason="bundled interpreter not present")
def test_list_targets_shows_every_base_and_its_writability():
    p = _cli("--list-targets")
    assert p.returncode == 0, p.stdout + p.stderr
    for tid in ("pracx", "vanilla", "pracx_thinker"):
        assert tid in p.stdout
    assert "DRY-RUN" in p.stdout, "unmeasured/unlocked targets must be marked non-writable"


@pytest.mark.skipif(not _PY.exists(), reason="bundled interpreter not present")
def test_unknown_target_id_lists_the_known_ones():
    p = _cli("--target-id", "bogus")
    assert p.returncode == 2
    assert "unknown --target-id" in p.stdout
    assert "pracx" in p.stdout, "the error must name what IS available"


@pytest.mark.skipif(not _PY.exists(), reason="bundled interpreter not present")
def test_an_unmeasured_target_is_refused_before_anything_else(tmp_path):
    """A target that declares no baseline cannot be used in either mode -- and the refusal must name
    the missing data rather than falling back to some other target's hash. (No such entry ships any
    more, so this uses a table of its own.)"""
    y = tmp_path / "p.yaml"
    y.write_text("target:\n  md5: x\ntargets:\n  future:\n    label: Future\n    exe: terranx.exe\n"
                 "    launch: true\n    pending: measurement\n", encoding="utf-8")
    p = _cli("--target-id", "future", "--apply", "--target", r"Z:\nope.exe", "--patches", str(y))
    assert p.returncode == 2
    assert "declares no base_md5/base_size" in p.stdout
    assert "in either mode" in p.stdout


def test_apply_is_refused_for_a_shipping_target_with_no_recorded_lock(tmp_path):
    """THE safety rule: a SHIPPING base that has never produced a verified output is dry-run
    only, so registering one with `groups: all` to measure eligibility cannot turn into an
    --apply against a binary nobody has checked. (No such entry exists in the shipped table --
    `vanilla` is deliberately exempt as dev-only -- so this uses a synthetic spec.)"""
    spec = ap.TargetSpec("provisional", {"label": "Provisional", "exe": "x.exe", "launch": True,
                                         "base_md5": "a" * 32, "base_size": 1234})
    rc = ap.apply_patches(tmp_path / "x.exe", tmp_path / "p.yaml", do_apply=True, spec=spec)
    assert rc == 2
    # ...but a dry run of the same spec gets past the gate (it fails later, on the missing file).
    assert ap.apply_patches(tmp_path / "x.exe", tmp_path / "p.yaml",
                            do_apply=False, spec=spec) != 2


def test_apply_refuses_and_writes_nothing_when_the_output_disagrees_with_the_lock(
        bak_path, tmp_path, patches_path):
    """REGRESSION: only the dry-run path compared its output to spec.patched_md5, so ANY 32-char
    string satisfied the gate and the apply path wrote the binary silently with rc 0."""
    import shutil
    tgt = tmp_path / "copy.exe"
    shutil.copy2(bak_path, tgt)
    before = tgt.read_bytes()

    spec = ap.TargetSpec("fake", {"label": "Fake", "exe": "x.exe", "launch": True,
                                  "base_md5": ap.EXPECTED_MD5, "base_size": ap.EXPECTED_SIZE,
                                  "groups": "all", "patched_md5": "deadbeef" * 4})
    rc = ap.apply_patches(tgt, patches_path, do_apply=True, spec=spec)
    assert rc == 4, "a lock mismatch must be its own failure code"
    assert tgt.read_bytes() == before, "the target was modified despite the mismatch"
    assert not tgt.with_suffix(".exe.bak").exists(), "a backup was taken before the refusal"


def test_apply_patches_refuses_apply_without_a_lock_before_touching_the_file(tmp_path):
    """The refusal must come before any read or write of the target -- a nonexistent path proves
    it never got as far as opening anything."""
    spec = ap.TargetSpec("t", {"label": "T", "exe": "t.exe", "launch": True,
                               "base_md5": "a" * 32, "base_size": 1})
    assert spec.patched_md5 is None
    rc = ap.apply_patches(tmp_path / "does-not-exist.exe", tmp_path / "nope.yaml",
                          do_apply=True, spec=spec)
    assert rc == 2
    assert not (tmp_path / "does-not-exist.exe").exists()


@pytest.mark.skipif(not _PY.exists(), reason="bundled interpreter not present")
def test_dry_run_reports_the_hash_it_would_produce(bak_path, target_meta):
    """This is what breaks the deadlock the dry-run-only rule creates: you cannot record a
    patched_md5 without applying, and cannot apply without it. Dry-run now tells you the hash."""
    p = _cli("--target", str(bak_path))
    assert p.returncode == 0, p.stdout + p.stderr
    assert "Nothing was written" in p.stdout
    assert f"Would produce MD5 : {target_meta['patched_md5']}" in p.stdout, (
        "the prospective hash must match the recorded build lock")


@pytest.mark.skipif(not _PY.exists(), reason="bundled interpreter not present")
def test_the_base_is_auto_detected_by_hash(bak_path):
    """No --target-id needed: hashing the file resolves it through the table."""
    p = _cli("--target", str(bak_path))
    assert "Base    : pracx" in p.stdout, p.stdout


# ---------------------------------------------------------------- baseline substitution

def test_a_spec_without_its_own_baseline_is_refused_not_given_the_pracx_one(tmp_path):
    """REGRESSION: `if spec.base_md5:` with no else let a target that declared nothing inherit
    EXPECTED_MD5. `--target-id thinker` then verified a PRACX binary against PRACX's hash while
    calling it "thinker", and told the operator to record the PRACX build lock as Thinker's --
    at which point the per-target baseline is gone entirely."""
    for d in ({"label": "T", "exe": "t.exe", "launch": True},
              {"label": "T", "exe": "t.exe", "launch": True, "base_md5": "a" * 32},
              {"label": "T", "exe": "t.exe", "launch": True, "base_size": 100}):
        spec = ap.TargetSpec("t", d)
        rc = ap.apply_patches(tmp_path / "x.exe", tmp_path / "p.yaml", do_apply=False, spec=spec)
        assert rc == 2, d
    # ...and it is refused in DRY RUN too, not just on apply.


def test_a_pending_spec_is_refused_in_both_modes(tmp_path):
    spec = ap.TargetSpec("t", {"label": "T", "exe": "t.exe", "launch": True,
                               "base_md5": "a" * 32, "base_size": 10,
                               "pending": "measurement"})
    for do_apply in (False, True):
        assert ap.apply_patches(tmp_path / "x.exe", tmp_path / "p.yaml",
                                do_apply=do_apply, spec=spec) == 2


def test_dev_only_targets_are_exempt_from_the_lock_gate():
    """`launch: false` targets never reach a player, so the dry-run-only rule protects nobody
    there and would break the workflow they exist for (--pristine --apply)."""
    tbl = ap.load_targets()
    assert tbl["vanilla"].launch is False
    assert tbl["vanilla"].patched_md5 is None
    # The gate is `do_apply and not patched_md5 and launch`, so a dev target passes it.
    assert not (True and not tbl["vanilla"].patched_md5 and tbl["vanilla"].launch)


@pytest.mark.skipif(not _PY.exists(), reason="bundled interpreter not present")
def test_conflicting_base_selectors_are_rejected():
    p = _cli("--target-id", "pracx", "--pristine")
    assert p.returncode == 2
    assert "both select a base" in p.stdout


@pytest.mark.skipif(not _PY.exists(), reason="bundled interpreter not present")
def test_a_missing_patches_file_is_reported_as_missing():
    p = _cli("--list-targets", "--patches", r"Z:\nope.yaml")
    assert p.returncode == 1
    assert "not found" in p.stdout, "it used to claim the file had no targets: table"


@pytest.mark.skipif(not _PY.exists(), reason="bundled interpreter not present")
def test_a_non_mapping_targets_table_is_explained_not_a_traceback(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("target:\n  md5: x\ntargets:\n  - pracx: {}\n", encoding="utf-8")
    p = _cli("--list-targets", "--patches", str(bad))
    assert p.returncode == 2
    assert "must be a mapping" in p.stdout
    assert "Traceback" not in p.stdout + p.stderr


def test_load_targets_raises_valueerror_for_malformed_yaml(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("targets: [oops]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        ap.load_targets(bad)
    worse = tmp_path / "worse.yaml"
    worse.write_text("targets:\n  x: {\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid YAML"):
        ap.load_targets(worse)
    with pytest.raises(ValueError, match="cannot read"):
        ap.load_targets(tmp_path / "absent.yaml")


def test_a_pending_entry_with_a_hash_still_does_not_match():
    """Defence in depth: `pending` alone disqualifies an entry even if a hash gets filled in."""
    tbl = {"x": ap.TargetSpec("x", {"label": "X", "exe": "x.exe", "launch": True,
                                    "base_md5": "a" * 32, "pending": "measurement"})}
    assert not tbl["x"].measured
    with pytest.raises(ap.UnsupportedBase):
        ap.resolve_target("a" * 32, tbl)


def test_an_overlay_is_for_its_own_exe_name_only(targets):
    """Thinker's launcher starts a file named terranx.exe and nothing else, so the PRACX + Thinker
    overlay applies to that file only: a PRACX exe under another name beside thinker.dll (the stock
    GOG layout with terranx_PRACX.exe next to a vanilla terranx.exe) gets the plain PRACX build and
    the plain instructions (audit 2026-10-28). Without a name, the folder alone decides, as before."""
    md5 = targets["pracx"].base_md5
    files = {"terranx.exe", "terranx_pracx.exe", "thinker.dll", "thinker.exe"}
    assert ap.resolve_target(md5, targets, present_files=files, exe_name="terranx.exe").id == "pracx_thinker"
    assert ap.resolve_target(md5, targets, present_files=files, exe_name="TERRANX.EXE").id == "pracx_thinker"
    assert ap.resolve_target(md5, targets, present_files=files, exe_name="terranx_PRACX.exe").id == "pracx"
    assert ap.resolve_target(md5, targets, present_files=files).id == "pracx_thinker", "no name -> folder decides"


def test_known_patched_is_the_release_history(targets):
    t = ap.TargetSpec("x", {"base_md5": "a" * 32, "patched_md5": "B" * 32,
                            "known_patched": ["C" * 32, " " + "d" * 32 + " "]})
    assert t.known_patched == ["c" * 32, "d" * 32]
    assert t.builds == {"b" * 32, "c" * 32, "d" * 32}
    assert ap.TargetSpec("y", {"base_md5": "a" * 32}).builds == set()


@pytest.mark.parametrize("bad", ["c" * 32, ["not-an-md5"], ["c" * 31], [""], [5]])
def test_a_malformed_known_patched_is_refused_not_skipped(bad):
    """A typo would make a released build "not ours" again, silently."""
    with pytest.raises(ValueError, match="known_patched"):
        ap.TargetSpec("x", {"base_md5": "a" * 32, "known_patched": bad})
