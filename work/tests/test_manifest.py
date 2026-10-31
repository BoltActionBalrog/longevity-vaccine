"""Manifest verification and the kill-switch precedence order.

The precedence order is tested as a TRUTH TABLE rather than case by case, because the whole point
is that the escape hatches beat the normal path: a client that has been told to stop must stop
even when a newer version is also on offer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
_REPO_ROOT = _SCRIPTS.parent.parent
sys.path.insert(0, str(_SCRIPTS))

import ed25519_verify as ed      # noqa: E402
import manifest as mf            # noqa: E402
import sign_manifest as sm       # noqa: E402
import version as ver            # noqa: E402

SEED = bytes(range(32))          # fixed, so tests are deterministic
PK_HEX = sm.public_key(SEED).hex()


def _doc(**over) -> dict:
    d = {
        "schema": 1,
        "protocol": 1,
        "product": "longevity-vaccine",
        "latest": "1.1.0",
        "min_upgradable_from": "1.0.0",
        "manual_install_required": False,
        "manual_install_reason": None,
        "unsupported_versions": [],
        "unsupported_targets": [],
        "yanked": [],
    }
    d.update(over)
    return d


def _signed(doc: dict) -> tuple[bytes, str]:
    raw = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
    return raw, sm.sign(SEED, raw).hex()


# ---------------------------------------------------------------- verification

def test_a_signed_manifest_loads():
    raw, sig = _signed(_doc())
    assert mf.load_verified(raw, sig, PK_HEX)["latest"] == "1.1.0"


def test_one_flipped_byte_is_refused():
    raw, sig = _signed(_doc())
    tampered = bytearray(raw)
    tampered[raw.index(b"1.1.0")] = ord("2")
    with pytest.raises(mf.ManifestError, match="does not verify"):
        mf.load_verified(bytes(tampered), sig, PK_HEX)


def test_whitespace_only_change_is_refused():
    """Verification is over exact bytes, so even a semantically identical reformat must fail."""
    doc = _doc()
    raw, sig = _signed(doc)
    reformatted = (json.dumps(doc) + "\n").encode("utf-8")   # no indent
    assert json.loads(reformatted) == json.loads(raw)
    with pytest.raises(mf.ManifestError):
        mf.load_verified(reformatted, sig, PK_HEX)


def test_a_signature_from_another_key_is_refused():
    raw, _ = _signed(_doc())
    other = sm.sign(bytes(range(1, 33)), raw).hex()
    with pytest.raises(mf.ManifestError):
        mf.load_verified(raw, other, PK_HEX)


@pytest.mark.parametrize("sig", ["", None, "zz", "00" * 64, "ab"])
def test_missing_or_garbage_signatures_are_refused(sig):
    raw, _ = _signed(_doc())
    with pytest.raises(mf.ManifestError):
        mf.load_verified(raw, sig, PK_HEX)


def test_no_provisioned_key_means_nothing_is_trusted():
    """A build with no signing key must refuse every manifest, not accept any."""
    raw, sig = _signed(_doc())
    with pytest.raises(mf.ManifestError, match="no release signing key"):
        mf.load_verified(raw, sig, "")


def test_text_input_is_refused():
    raw, sig = _signed(_doc())
    with pytest.raises(mf.ManifestError, match="raw bytes"):
        mf.load_verified(raw.decode("utf-8"), sig, PK_HEX)


def test_valid_signature_over_non_json_is_still_refused():
    """Authentic but unparseable must fail loudly, not half-succeed."""
    raw = b"this is signed but is not json"
    sig = sm.sign(SEED, raw).hex()
    with pytest.raises(mf.ManifestError, match="not valid UTF-8 JSON"):
        mf.load_verified(raw, sig, PK_HEX)


def test_signature_is_verified_before_parsing():
    """A tampered manifest that is also malformed JSON must report the SIGNATURE failure -- we
    must never have parsed attacker-controlled structure to find out it was bad."""
    raw, sig = _signed(_doc())
    with pytest.raises(mf.ManifestError, match="does not verify"):
        mf.load_verified(b"{ not json at all", sig, PK_HEX)


def test_file_pair_round_trip(tmp_path):
    doc = _doc()
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    sm.sign_file(SEED, m)
    assert (tmp_path / "manifest.json.sig").is_file()
    assert mf.load_verified_files(m, public_key_hex=PK_HEX)["latest"] == "1.1.0"


def test_a_missing_signature_file_is_an_error(tmp_path):
    m = tmp_path / "manifest.json"
    m.write_text("{}", encoding="utf-8")
    with pytest.raises(mf.ManifestError, match="could not read"):
        mf.load_verified_files(m, public_key_hex=PK_HEX)


# ---------------------------------------------------------------- precedence truth table

#: (label, manifest overrides, installed version, target, expected action, expected reason)
CASES = [
    ("normal update",        {},                                          "1.0.0", "pracx", mf.UPDATE,  None),
    ("already current",      {"latest": "1.0.0"},                         "1.0.0", "pracx", mf.NOTHING, None),
    ("installed is newer",   {"latest": "1.0.0"},                         "1.2.0", "pracx", mf.NOTHING, None),
    ("yanked latest",        {"yanked": ["1.1.0"]},                       "1.0.0", "pracx", mf.NOTHING, None),
    ("global kill",          {"manual_install_required": True},           "1.0.0", "pracx", mf.MANUAL,  None),
    ("global kill + reason", {"manual_install_required": True,
                              "manual_install_reason": "bootstrap_defect"}, "1.0.0", "pracx", mf.MANUAL, "bootstrap_defect"),
    ("version killed",       {"unsupported_versions": ["1.0.0"]},         "1.0.0", "pracx", mf.MANUAL,  "base_unsupported"),
    ("other version killed", {"unsupported_versions": ["0.9.0"]},         "1.0.0", "pracx", mf.UPDATE,  None),
    ("target killed",        {"unsupported_targets": ["thinker"]},        "1.0.0", "thinker", mf.MANUAL, "base_unsupported"),
    ("other target killed",  {"unsupported_targets": ["thinker"]},        "1.0.0", "pracx", mf.UPDATE,  None),
    ("too old",              {"min_upgradable_from": "1.0.0"},            "0.9.0", "pracx", mf.MANUAL,  "too_old"),
    ("protocol too new",     {"protocol": 99},                            "1.0.0", "pracx", mf.MANUAL,  "protocol"),
    ("protocol missing",     {"protocol": None},                          "1.0.0", "pracx", mf.MANUAL,  "protocol"),
    ("protocol not an int",  {"protocol": "1"},                           "1.0.0", "pracx", mf.MANUAL,  "protocol"),
    ("latest unusable",      {"latest": "not-a-version"},                 "1.0.0", "pracx", mf.MANUAL,  "protocol"),
]


@pytest.mark.parametrize("label,over,installed,target,action,reason", CASES,
                         ids=[c[0] for c in CASES])
def test_precedence(label, over, installed, target, action, reason):
    d = mf.decide(_doc(**over), installed, target)
    assert d.action == action, f"{label}: {d!r}"
    if reason is not None:
        assert d.reason == reason, f"{label}: {d!r}"


def test_each_hatch_beats_the_one_below_it():
    """The order itself, asserted by stacking every hatch at once and peeling them off."""
    base = {"manual_install_required": True, "unsupported_versions": ["1.0.0"],
            "unsupported_targets": ["pracx"], "yanked": ["1.1.0"], "protocol": 99}
    # protocol beats everything
    assert mf.decide(_doc(**base), "1.0.0", "pracx").reason == "protocol"
    # then the global kill
    base["protocol"] = 1
    assert mf.decide(_doc(**base), "1.0.0", "pracx").detail == "manual_install_required"
    # then the surgical kill
    base["manual_install_required"] = False
    assert mf.decide(_doc(**base), "1.0.0", "pracx").reason == "base_unsupported"
    # then yanked
    base["unsupported_versions"] = []
    base["unsupported_targets"] = []
    assert mf.decide(_doc(**base), "1.0.0", "pracx").action == mf.NOTHING
    # then a normal update
    base["yanked"] = []
    assert mf.decide(_doc(**base), "1.0.0", "pracx").action == mf.UPDATE


def test_kill_switch_fields_are_readable_when_everything_else_is_garbage():
    """An old client must be able to see that it has been told to stop, even facing a manifest
    whose other fields it cannot make sense of."""
    doc = {"protocol": 1, "manual_install_required": True,
           "latest": {"unexpected": "shape"}, "modules": 12345, "targets": "nonsense"}
    assert mf.decide(doc, "1.0.0", "pracx").action == mf.MANUAL


@pytest.mark.parametrize("field,scalar", [
    ("unsupported_versions", "1.0.0"),   # matched against the INSTALLED version
    ("unsupported_targets", "pracx"),    # matched against the resolved target
    ("yanked", "1.1.0"),                 # matched against `latest`, not the installed version
])
def test_a_scalar_string_is_accepted_where_a_list_is_expected(field, scalar):
    """Tolerate `unsupported_versions: "1.0.0"` -- a hand-edited manifest that meant to stop a
    client must not fail open just because someone omitted the brackets."""
    d = mf.decide(_doc(**{field: scalar}), "1.0.0", "pracx")
    assert d.action in (mf.MANUAL, mf.NOTHING), d


@pytest.mark.parametrize("bad", [None, [], "string", 42])
def test_a_non_dict_manifest_is_manual_install(bad):
    assert mf.decide(bad, "1.0.0", "pracx").action == mf.MANUAL


def test_an_unreadable_installed_version_does_not_mean_up_to_date():
    """Failing open here would leave a corrupted install permanently un-updated."""
    assert mf.decide(_doc(), "garbage", "pracx").action == mf.UPDATE


# ---------------------------------------------------------------- the trust boundary

def test_url_and_message_never_come_from_the_manifest():
    """The in-game checker does not verify signatures, so a manifest-supplied URL would be an
    attacker-controllable download link -- a phishing vector we would have built ourselves."""
    hostile = _doc(manual_install_required=True,
                   manual_install_reason="Download from http://evil.example/pwn",
                   download_url="http://evil.example/pwn",
                   message="Click here to fix your game")
    d = mf.decide(hostile, "1.0.0", "pracx")
    assert d.action == mf.MANUAL
    assert d.url == mf.DOWNLOAD_URL
    assert "evil.example" not in (d.message or "")
    assert "evil.example" not in (d.url or "")
    # An unknown reason key must fall back to our own default, not be echoed.
    assert d.message in mf.REASONS.values()


@pytest.mark.parametrize("value,expected", [
    (True, mf.MANUAL), (1, mf.MANUAL), (1.0, mf.MANUAL), ("true", mf.MANUAL),
    ("yes", mf.MANUAL), ("1", mf.MANUAL), ("on", mf.MANUAL),
    (False, mf.UPDATE), (0, mf.UPDATE), ("false", mf.UPDATE), ("no", mf.UPDATE),
    (None, mf.UPDATE),
    # Shapes we cannot read must FAIL CLOSED. This field's only purpose is to stop a client in
    # the wild; a hand-edited manifest with a JSON typo silently doing nothing is the worst
    # available outcome for a safety valve.
    ([1], mf.MANUAL), ({"x": 1}, mf.MANUAL), ("maybe", mf.MANUAL),
])
def test_the_global_kill_switch_reads_loosely_and_fails_closed(value, expected):
    assert mf.decide(_doc(manual_install_required=value), "1.0.0", "pracx").action == expected


@pytest.mark.parametrize("field", ["unsupported_versions", "unsupported_targets", "yanked"])
@pytest.mark.parametrize("bad", [{"1.0.0": "why"}, [["1.0.0"]], 1.0, 42, [1, 2]])
def test_an_unreadable_kill_switch_list_fails_closed(field, bad):
    d = mf.decide(_doc(**{field: bad}), "1.0.0", "pracx")
    assert d.action == mf.MANUAL, f"{field}={bad!r} was silently ignored"


def test_detail_never_carries_manifest_text_into_a_user_facing_string():
    """`detail` is a developer diagnostic. The player-facing pieces are `message` and `url`,
    both compiled in -- a manifest that put a URL in `latest` otherwise appeared inside our own
    "see the official link" sentence."""
    hostile = _doc(latest="Go to http://evil.example/pwn and run setup.exe")
    d = mf.decide(hostile, "1.0.0", "pracx")
    assert d.action == mf.MANUAL
    assert "evil.example" not in d.message
    assert d.url == mf.DOWNLOAD_URL
    # And even the diagnostic is sanitised: no control characters, bounded length.
    noisy = _doc(latest="a\x1b[31mred\x07" + "z" * 500)
    d2 = mf.decide(noisy, "1.0.0", "pracx")
    assert "\x1b" not in d2.detail and "\x07" not in d2.detail
    assert len(d2.detail) < 200


def test_the_offered_version_is_canonicalised():
    """A signed manifest could still carry "1.1.0\\n"; it must not reach a path or a URL."""
    d = mf.decide(_doc(latest="1.1.0\n"), "1.0.0", "pracx")
    assert d.action == mf.UPDATE
    assert d.version == "1.1.0"


def test_an_unhashable_reason_does_not_raise():
    for bad in ([1], {"a": 1}, {1, 2}):
        d = mf.Decision(mf.MANUAL, bad)
        assert d.message in mf.REASONS.values()


def test_every_reason_maps_to_a_compiled_message():
    for key in mf.REASONS:
        d = mf.Decision(mf.MANUAL, key)
        assert d.message and d.url == mf.DOWNLOAD_URL


def test_signing_capability_is_not_in_the_shipped_verifier():
    """ed25519_verify.py ships; it must expose no way to sign."""
    src = (_SCRIPTS / "ed25519_verify.py").read_text(encoding="utf-8")
    assert "def sign" not in src
    assert not hasattr(ed, "sign")


def test_keygen_refuses_to_write_inside_the_repository(tmp_path):
    """A private key inside the repo is one `git add -A` from being published."""
    inside = _SCRIPTS / "should-never-exist.key"
    with pytest.raises(SystemExit, match="inside the repository"):
        sm.keygen(inside)
    assert not inside.exists()


@pytest.mark.parametrize("alias", [
    r"\\?\{repo}\work\scripts\evil.key",          # extended-length prefix
    r"\\localhost\D$\SmacxUi\work\scripts\evil.key",   # UNC via the admin share
    r"\\127.0.0.1\D$\SmacxUi\work\scripts\evil.key",
])
def test_keygen_refuses_path_aliases_that_reach_the_repository(alias):
    """`Path.resolve()` leaves these alone, so `is_relative_to` said False and the key would have
    landed in the working tree through an alias."""
    p = alias.format(repo=str(_REPO_ROOT))
    with pytest.raises(SystemExit):
        sm.keygen(Path(p))
    assert not Path(p).exists()


def test_keygen_still_accepts_a_normal_path_outside_the_repo(tmp_path):
    """The alias guard must not have made every path unusable."""
    key = tmp_path / "ok.key"
    sm.keygen(key)
    assert key.is_file()
    assert len(bytes.fromhex(key.read_text(encoding="ascii").strip())) == 32


def test_keygen_refuses_to_overwrite(tmp_path):
    p = tmp_path / "k.key"
    p.write_text("00" * 32, encoding="ascii")
    with pytest.raises(SystemExit, match="already exists"):
        sm.keygen(p)


def test_sign_rejects_a_malformed_seed():
    for bad in (b"", b"\x00" * 31, b"\x00" * 33, "not bytes", None):
        with pytest.raises(ValueError):
            sm.sign(bad, b"m")


def test_our_signatures_verify_with_the_rfc_verifier():
    """Round-trip through the independent verifier, over a range of message sizes."""
    for n in (0, 1, 2, 63, 64, 65, 4096):
        msg = bytes(range(256)) * (n // 256) + bytes(range(n % 256))
        sig = sm.sign(SEED, msg)
        assert ed.verify(sm.public_key(SEED), sig, msg) is True
        assert ed.verify(sm.public_key(bytes(range(1, 33))), sig, msg) is False


# ---------------------------------------------------------------- module updates
#
# A module's release is independent of the product's. The rule, as a truth table: `_doc()` has
# latest 1.1.0, so installed "1.1.0" is a CURRENT base and "1.0.0" a stale one.

def _mods(**versions) -> dict:
    return {n: {"version": v, "url": f"https://x/{n}.zip", "sha256": "0" * 64}
            for n, v in versions.items()}


MODULE_CASES = [
    # label,                              installed base, manifest modules,            receipt modules,          action,     Decision.modules
    ("stale module, base current",        "1.1.0", _mods(**{"movies-hd": "1.2.0"}),   {"movies-hd": "1.1.0"},   mf.UPDATE,  ["movies-hd"]),
    ("module current, base current",      "1.1.0", _mods(**{"movies-hd": "1.1.0"}),   {"movies-hd": "1.1.0"},   mf.NOTHING, []),
    ("module OLDER in the manifest",      "1.1.0", _mods(**{"movies-hd": "1.0.0"}),   {"movies-hd": "1.1.0"},   mf.NOTHING, []),
    ("absent module is never fetched",    "1.1.0", _mods(**{"movies-hd": "1.2.0"}),   {},                       mf.NOTHING, []),
    ("base newer, module current",        "1.0.0", _mods(**{"movies-hd": "1.1.0"}),   {"movies-hd": "1.1.0"},   mf.UPDATE,  []),
    ("base newer and module stale",       "1.0.0", _mods(**{"movies-hd": "1.2.0"}),   {"movies-hd": "1.1.0"},   mf.UPDATE,  ["movies-hd"]),
    ("two stale modules, sorted",         "1.1.0", _mods(**{"portraits-hd": "2.0.0", "movies-hd": "2.0.0"}),
                                                                                       {"portraits-hd": "1.0.0", "movies-hd": "1.0.0"},
                                                                                                                 mf.UPDATE,  ["movies-hd", "portraits-hd"]),
    ("module dropped from the manifest",  "1.1.0", {},                                {"movies-hd": "1.1.0"},   mf.NOTHING, []),
    ("module entry is not a dict",        "1.1.0", {"movies-hd": "1.2.0"},            {"movies-hd": "1.1.0"},   mf.NOTHING, []),
    ("module version unusable",           "1.1.0", _mods(**{"movies-hd": "soon"}),    {"movies-hd": "1.1.0"},   mf.NOTHING, []),
    ("modules field is garbage",          "1.1.0", "not a dict",                       {"movies-hd": "1.1.0"},   mf.NOTHING, []),
    ("`base` in the receipt map is ignored", "1.1.0", _mods(base="9.9.9"),            {"base": "1.0.0"},        mf.NOTHING, []),
    ("unreadable receipt version -> offered", "1.1.0", _mods(**{"movies-hd": "1.1.0"}), {"movies-hd": "garbage"}, mf.UPDATE, ["movies-hd"]),
]


@pytest.mark.parametrize("label,installed,mods,have,action,modules", MODULE_CASES,
                         ids=[c[0] for c in MODULE_CASES])
def test_module_rule(label, installed, mods, have, action, modules):
    d = mf.decide(_doc(modules=mods), installed, "pracx", installed_modules=have)
    assert d.action == action, f"{label}: {d!r}"
    assert d.modules == modules, f"{label}: {d!r}"
    if action == mf.UPDATE:
        assert d.version == "1.1.0", "a module-only update still names `latest`"


def test_without_a_receipt_map_the_rule_is_unchanged():
    """Every existing caller passes nothing; they must see exactly what they saw before."""
    assert mf.decide(_doc(modules=_mods(**{"movies-hd": "9.9.9"})), "1.1.0", "pracx").action \
        == mf.NOTHING
    assert mf.decide(_doc(), "1.0.0", "pracx").modules == []


@pytest.mark.parametrize("over,action", [
    ({"yanked": ["1.1.0"]}, mf.NOTHING),
    ({"manual_install_required": True}, mf.MANUAL),
    ({"unsupported_versions": ["1.1.0"]}, mf.MANUAL),
    ({"unsupported_targets": ["pracx"]}, mf.MANUAL),
    ({"protocol": 99}, mf.MANUAL),
], ids=["yanked", "global kill", "unsupported version", "unsupported target", "protocol"])
def test_every_hatch_still_beats_a_stale_module(over, action):
    """A stale pack is a normal update; it ranks below every escape hatch and never leaks into
    Decision.modules on a refusal."""
    d = mf.decide(_doc(modules=_mods(**{"movies-hd": "1.2.0"}), **over), "1.1.0", "pracx",
                  installed_modules={"movies-hd": "1.1.0"})
    assert d.action == action, repr(d)
    assert d.modules == []


def test_an_unreadable_base_still_carries_the_stale_packs():
    """Generation 2 decides again from the receipt after a self-update; a corrupt BaseVersion
    there used to drop every pack from that run."""
    d = mf.decide(_doc(modules=_mods(**{"movies-hd": "1.2.0"})), "garbage", "pracx",
                  installed_modules={"movies-hd": "1.1.0"})
    assert d.action == mf.UPDATE and d.modules == ["movies-hd"]


@pytest.mark.parametrize("value,ok", [
    (0, True), (1, True), (1300 << 20, True), (mf.MAX_SIZE, True),
    (mf.MAX_SIZE + 1, False), (-1, False), (True, False), (False, False), (1.0, False),
    ("9", False), (None, False), (10 ** 400, False),
])
def test_size_ok_admits_only_plain_bounded_non_negative_ints(value, ok):
    """A 320-digit int raised OverflowError in the extras notice AFTER a completed install; a
    bool printed "(0 MB)"; a negative printed negative megabytes."""
    assert mf.size_ok(value) is ok


def test_min_upgradable_from_is_a_constant_older_than_the_release():
    """release.py used to publish min_upgradable_from = latest, which told EVERY existing
    install it was too old to update on EVERY release."""
    assert ver.is_valid(ver.MIN_UPGRADABLE_FROM)
    assert ver.at_least(ver.VERSION, ver.MIN_UPGRADABLE_FROM)
    d = mf.decide(_doc(latest="9.9.9", min_upgradable_from=ver.MIN_UPGRADABLE_FROM),
                  ver.VERSION, "pracx")
    assert d.action == mf.UPDATE, "the current release must be able to update itself"


def test_an_unknown_installed_version_is_a_repair_never_too_old():
    """receipt.module_version maps garbage to UNKNOWN ("0.0.0"), which is a VALID string: it
    used to fall through to min_upgradable_from and tell the player to reinstall by hand."""
    d = mf.decide(_doc(min_upgradable_from="1.0.0"), ver.UNKNOWN, "pracx")
    assert d.action == mf.UPDATE and d.reason is None, repr(d)
    assert mf.decide(_doc(min_upgradable_from="1.0.0"), "0.9.0", "pracx").reason == "too_old"


@pytest.mark.parametrize("field,value", [
    ("unsupported_versions", ["1.0.0 "]), ("unsupported_versions", ["1.0.0\r\n"]),
])
def test_kill_switch_versions_are_compared_normalised(field, value):
    """A hand-edited entry with trailing whitespace used to fail OPEN."""
    assert mf.decide(_doc(**{field: value}), "1.0.0", "pracx").action == mf.MANUAL


def test_a_yanked_entry_with_whitespace_still_yanks():
    assert mf.decide(_doc(yanked=["1.1.0\n"]), "1.0.0", "pracx").action == mf.NOTHING


def test_module_detail_is_sanitised():
    """`detail` may name the modules; a hostile id must arrive bounded and printable."""
    hostile = "x" * 500 + "\x07\n"
    d = mf.decide(_doc(modules={hostile: {"version": "1.2.0"}}), "1.1.0", "pracx",
                  installed_modules={hostile: "1.1.0"})
    assert d.action == mf.UPDATE
    assert "\x07" not in d.detail and "\n" not in d.detail and len(d.detail) < 120
