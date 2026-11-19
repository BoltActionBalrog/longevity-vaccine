"""thinker_flow: consent, the manifest's Thinker data, the --check line, Q1 (journey B) and the
--fix-thinker repair (journey R). Downloads and swaps are replaced by fakes here (thinker_source /
thinker_update have their own tests); no network, no game."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import types
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import install as inst            # noqa: E402
import installer_exit as ix       # noqa: E402

inst._load_modules()
import thinker_data as td         # noqa: E402
import thinker_flow as tf         # noqa: E402
import thinker_state as st        # noqa: E402
import thinker_update as tu       # noqa: E402
import version as ver             # noqa: E402

pytestmark = pytest.mark.usefixtures("install_globals")     # install.py's run-wide globals reset per test

SHA_A = "a" * 64
SHA_B = "b" * 64


# ---------------------------------------------------------------- consent

def test_consent_format_and_parse():
    raw = tf.format_consent("pin", "5.5.0", "game", pid=42, now=1000)
    assert raw == "5.5.0|1000|42|game"
    c = tf.parse_consent(raw)
    assert (c.kind, c.target, c.at, c.pid, c.source) == ("pin", "5.5.0", 1000, 42, "game")
    k = tf.parse_consent(tf.format_consent("keep", "1.2.0", "fix", pid=1, now=5))
    assert (k.kind, k.target, k.source) == ("keep", "1.2.0", "fix")
    assert tf.parse_consent("dev-20251109|5|1|fix").target == "dev-20251109"


@pytest.mark.parametrize("raw", ["", "x", "5.5|1|2|game", "5.5.0|1|2|evil", "5.5.0|-1|2|game", "keep:1.2|1|2|fix",
                                 "../x|1|2|game", "5.5.0|1|2|game|extra", "5.5.0|" + "9" * 200 + "|1|game"])
def test_bad_consent_is_ignored(raw):
    assert tf.parse_consent(raw) is None


def test_consent_freshness():
    c = tf.parse_consent("5.5.0|1000|42|game")
    dead = lambda pid: False
    assert tf.consent_fresh(c, now=1000 + 60, alive=dead)
    assert not tf.consent_fresh(c, now=1000 + tf.CONSENT_TTL + 1, alive=dead)       # too old
    assert not tf.consent_fresh(c, now=1000 - 60, alive=dead)                        # from the future
    assert not tf.consent_fresh(c, now=1060, alive=lambda pid: True)                 # writer still running


def test_consent_matches():
    assert tf.consent_matches(tf.parse_consent("5.5.0|1|2|game"), "5.5.0", "1.2.0")
    assert not tf.consent_matches(tf.parse_consent("5.6.0|1|2|game"), "5.5.0", "1.2.0")
    assert tf.consent_matches(tf.parse_consent("keep:1.2.0|1|2|game"), "5.5.0", "1.2.0")
    assert not tf.consent_matches(tf.parse_consent("keep:1.1.0|1|2|game"), "5.5.0", "1.2.0")


def test_worker_takes_generation_ones_handoff(monkeypatch, tmp_path):
    deleted = []
    monkeypatch.setattr(tf, "read_consent_key", lambda g: "")
    monkeypatch.setattr(tf, "delete_ini_key", lambda *a: deleted.append(a))
    monkeypatch.setenv(tf.CONSENT_ENV, f"5.5.0|{int(time.time())}|1|game|{int(time.time())}")
    c = tf.take_for_worker(tmp_path, "5.5.0", "1.2.0")
    assert c is not None and c.source == "game"
    assert tf.CONSENT_ENV not in os.environ                                          # used once


def test_worker_reads_ini_when_nothing_was_handed_over(monkeypatch, tmp_path):
    raw = f"5.5.0|{int(time.time()) - 10}|999999|game"
    deleted = []
    monkeypatch.delenv(tf.CONSENT_ENV, raising=False)
    monkeypatch.setattr(tf, "read_consent_key", lambda g: raw)
    monkeypatch.setattr(tf, "delete_ini_key", lambda *a: deleted.append(a))
    monkeypatch.setattr(tf, "_pid_alive", lambda pid: False)
    assert tf.take_for_worker(tmp_path, "5.5.0", "1.2.0") is not None
    assert deleted                                                                   # always deleted
    assert tf.take_for_worker(tmp_path, "5.6.0", "1.2.0") is None                    # another pin


def test_run_scoped_env_never_outlives_the_run(monkeypatch):
    monkeypatch.setenv(tf.CONSENT_ENV, "x")
    monkeypatch.setenv(tf.PLAYER_NO_PROMPT_ENV, "1")
    env = tf.scrubbed_env()
    assert tf.CONSENT_ENV not in env and tf.PLAYER_NO_PROMPT_ENV not in env
    assert tf.CONSENT_ENV not in ix.outliving_env()


# ---------------------------------------------------------------- manifest data

def _doc(**over):
    doc = {"issued": 100, "thinker": {
        "release_pins": {"1.1.0": "5.5.0", "1.3.0": "5.7.0"},
        "pins": {"5.7.0": {"dll": SHA_B, "stamp": 1, "image_size": 2, "release_tag": "v5.7",
                           "download": {"asset": "Thinker_v5.7.zip", "sha256": SHA_A, "size": 760000}}},
        "fatal": {"1.3.0": [SHA_A]}}}
    doc.update(over)
    return doc


def test_thinker_info_parses_a_good_section():
    i = tf.thinker_info(_doc())
    assert i.issued == 100 and i.release_pins["1.3.0"] == "5.7.0"
    pin, meta = i.pins["5.7.0"]
    assert pin.tag == "v5.7" and pin.asset == "Thinker_v5.7.zip" and meta["dll"] == SHA_B
    assert i.fatal["1.3.0"] == frozenset({SHA_A})


@pytest.mark.parametrize("bad", [
    {"release_tag": "v5.6"},                                      # names another version
    {"release_tag": "v5.7/../x"},
    {"dll": "zz"},
    {"download": {"asset": "x.exe", "sha256": SHA_A, "size": 1}},
    {"download": {"asset": "Thinker_v5.7.zip", "sha256": SHA_A, "size": 1 << 40}},
    {"download": {"dropbox": "sh/abc/x.zip", "sha256": SHA_A, "size": 5}},
])
def test_thinker_info_drops_a_bad_pin(bad):
    doc = _doc()
    doc["thinker"]["pins"]["5.7.0"].update(bad)
    assert "5.7.0" not in tf.thinker_info(doc).pins


def test_thinker_info_tolerates_garbage():
    for d in (None, [], {"thinker": []}, {"thinker": {"pins": "x", "release_pins": [1], "fatal": 3}},
              {"issued": True}):
        i = tf.thinker_info(d)
        assert i.pins == {} and i.issued == 0


def test_fatal_union_only_for_own_version(monkeypatch):
    monkeypatch.setattr(td, "FATAL", frozenset({SHA_B}))
    i = tf.thinker_info(_doc())
    assert tf.fatal_for(ver.VERSION, i, ver.VERSION) >= {SHA_B}
    assert tf.fatal_for("1.3.0", i, ver.VERSION) == frozenset({SHA_A})            # another release: manifest only


def test_issued_floor(tmp_path):
    i = tf.thinker_info(_doc())
    assert tf.issued_check(tmp_path, i, persist=True) and tf.issued_floor(tmp_path) == 100
    old = tf.thinker_info(_doc(issued=50))
    assert not tf.issued_check(tmp_path, old, persist=True)
    assert tf.issued_floor(tmp_path) == 100
    assert tf.issued_check(tmp_path, tf.thinker_info(_doc(issued=200)), persist=False)
    assert tf.issued_floor(tmp_path) == 100                                         # a test manifest never persists


def test_manifest_section_round_trips():
    sec = tf.manifest_section("9.9.9")
    i = tf.thinker_info({"issued": 1, "thinker": sec})
    assert i.release_pins["9.9.9"] == td.PIN_VERSION
    pin, meta = i.pins[td.PIN_VERSION]
    assert pin.tag == td.PIN_TAG and pin.zip_sha256 == td.PIN_ZIP_SHA256 and meta["dll"] == td.PIN_DLL_SHA256
    assert (meta["stamp"], meta["image_size"]) == (td.PIN_DLL_STAMP, td.PIN_DLL_IMAGE_SIZE)


# ---------------------------------------------------------------- a fake thinker.dll

def _dll(label: bytes, stamp=1, size=2) -> bytes:
    pe = 0x80
    head = bytearray(pe + 0x58)
    head[:2] = b"MZ"
    head[0x3C:0x40] = pe.to_bytes(4, "little")
    head[pe:pe + 4] = b"PE\0\0"
    head[pe + 8:pe + 12] = stamp.to_bytes(4, "little")
    head[pe + 0x50:pe + 0x54] = size.to_bytes(4, "little")
    return bytes(head) + label + b"\0"


def _game(tmp_path, label=b"Thinker Mod v5.4", **kw) -> Path:
    g = tmp_path / "game"
    g.mkdir(exist_ok=True)
    (g / "thinker.dll").write_bytes(_dll(label, **kw))
    return g


# ---------------------------------------------------------------- --check line

def test_check_line_forms(tmp_path):
    doc = _doc()
    g = _game(tmp_path, b"Thinker Mod v5.4")
    assert tf.check_line(g, doc, "1.3.0") == "thinker=5.4.0|5.7.0|760000|1"
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod develop build"))
    assert tf.check_line(g, doc, "1.3.0") == "thinker=?|5.7.0|760000|1"
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod v5.7"))                    # same number, other bytes
    assert tf.check_line(g, doc, "1.3.0").startswith("thinker=?|")
    (g / "thinker.dll").unlink()
    assert tf.check_line(g, doc, "1.3.0") == ""                                   # NONE
    assert tf.check_line(g, doc, "9.9.9") == ""                                   # no pin data


def test_check_line_lo_zero_for_fatal(tmp_path):
    g = _game(tmp_path)
    doc = _doc()
    doc["thinker"]["fatal"]["1.3.0"] = [hashlib.sha256((g / "thinker.dll").read_bytes()).hexdigest()]
    assert tf.check_line(g, doc, "1.3.0").endswith("|0")


def test_check_line_on_the_pin_is_empty(tmp_path):
    g = _game(tmp_path)
    doc = _doc()
    doc["thinker"]["pins"]["5.7.0"]["dll"] = hashlib.sha256((g / "thinker.dll").read_bytes()).hexdigest()
    assert tf.check_line(g, doc, "1.3.0") == ""


# ---------------------------------------------------------------- Q1 texts (approved sentences)

def _pin():
    return tf.compiled_pin()


def test_q1_texts_downgrade_and_neutral(tmp_path):
    g = _game(tmp_path, b"Thinker Mod v5.8")
    _s, dll = st.classify(g, "0" * 64)
    title, notes, options = tf.q1_texts(dll, "1.2.0", _pin(), tf.compiled_meta(), fresh=False, fatal=False)
    assert title == "Thinker Mod downgrade"
    assert ("This is a downgrade! It replaces your newer Thinker Mod 5.8 with the older Thinker Mod 5.5, "
            "the version Longevity Vaccine 1.2.0 supports.") in notes
    assert options == ["Also downgrade Thinker Mod from 5.8 to 5.5", "Only update Longevity Vaccine"]
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod develop build"))
    _s, dll = st.classify(g, "0" * 64)
    title, notes, options = tf.q1_texts(dll, "1.2.0", _pin(), tf.compiled_meta(), fresh=True, fatal=False)
    assert any("It replaces a development build of Thinker Mod with Thinker Mod 5.5, the version Longevity "
               "Vaccine 1.2.0 supports." in n for n in notes)
    assert options == ["Also replace your development build of Thinker Mod with Thinker Mod 5.5",
                       "Only install Longevity Vaccine"]
    assert not any("on its own" in n for n in notes)       # no "If you choose 'Only install ...'" (user 2026-11-15)


def test_q1_fatal_note(tmp_path):
    g = _game(tmp_path)
    _s, dll = st.classify(g, "0" * 64)
    _t, notes, options = tf.q1_texts(dll, "1.2.0", _pin(), tf.compiled_meta(), fresh=False, fatal=True)
    assert notes[-1] == "Longevity Vaccine 1.2.0 does not start with your Thinker Mod 5.4, so if you cancel, neither mod is changed."
    assert options == ["Also update Thinker Mod to 5.5", "Cancel the update"]
    _t, notes, options = tf.q1_texts(dll, "1.2.0", _pin(), tf.compiled_meta(), fresh=True, fatal=True)
    assert notes[-1] == "Longevity Vaccine 1.2.0 does not start with your Thinker Mod 5.4, so if you cancel, nothing is installed."
    assert options == ["Also update Thinker Mod to 5.5", "Cancel the installation"]


def test_promise_follows_the_header_test(tmp_path):
    g = _game(tmp_path, stamp=td.PIN_DLL_STAMP, size=td.PIN_DLL_IMAGE_SIZE)         # the game calls it the pin
    _s, dll = st.classify(g, "0" * 64)
    assert not tf.game_sees_mismatch(dll, tf.compiled_meta())
    assert tf.keep_line(dll, "1.2.0", _pin(), tf.compiled_meta()).endswith("works with Thinker Mod 5.5.")


# ---------------------------------------------------------------- update_preflight (journeys A / B)

class FakePrep:
    def __init__(self):
        self.committed = False


@pytest.fixture
def fake_prepare(monkeypatch):
    calls = []
    monkeypatch.setattr(tf, "prepare", lambda *a, **k: calls.append((a, k)) or FakePrep())
    monkeypatch.setattr(tf, "take_for_worker", lambda *a: None)
    return calls


def test_preflight_none_or_pin_does_nothing(tmp_path, fake_prepare):
    g = tmp_path / "g"
    g.mkdir()
    r = tf.update_preflight(g, types.SimpleNamespace(), None, fresh=True, lv="1.2.0", persist_issued=False)
    assert r.prep is None and not r.keep and not fake_prepare


def test_preflight_cannot_ask_is_r2(tmp_path, fake_prepare, monkeypatch):
    g = _game(tmp_path)
    monkeypatch.setattr(tf, "_asks", lambda a: False)
    with pytest.raises(ix.InstallerError) as e:
        tf.update_preflight(g, types.SimpleNamespace(with_thinker=False), None, fresh=True, lv="1.2.0",
                            persist_issued=False)
    assert "cannot ask questions, so nothing was installed" in e.value.message and not e.value.changed


def test_preflight_with_thinker_flag(tmp_path, fake_prepare, monkeypatch):
    g = _game(tmp_path)
    monkeypatch.setattr(tf, "_asks", lambda a: False)
    r = tf.update_preflight(g, types.SimpleNamespace(with_thinker=True), None, fresh=False, lv="1.2.0",
                            persist_issued=False)
    assert r.prep is not None and "route_text" not in fake_prepare[0][1]      # no route note (user 2026-11-14)


def test_preflight_q1_yes_and_no(tmp_path, fake_prepare, monkeypatch):
    g = _game(tmp_path)
    monkeypatch.setattr(tf, "_asks", lambda a: True)
    monkeypatch.setattr(inst, "_arrow_menu", lambda *a, **k: 0)          # "Also update Thinker Mod to 5.5"
    r = tf.update_preflight(g, types.SimpleNamespace(), None, fresh=False, lv="1.2.0", persist_issued=False)
    assert r.prep is not None
    monkeypatch.setattr(inst, "_arrow_menu", lambda *a, **k: 1)          # "Only update Longevity Vaccine"
    r = tf.update_preflight(g, types.SimpleNamespace(), None, fresh=False, lv="1.2.0", persist_issued=False)
    assert r.prep is None and r.keep.startswith("Your Thinker Mod 5.4 stays as it is.")


def test_preflight_the_second_option_keeps_and_ctrl_c_aborts(tmp_path, fake_prepare, monkeypatch):
    g = _game(tmp_path)
    monkeypatch.setattr(tf, "_asks", lambda a: True)
    monkeypatch.setattr(inst, "_arrow_menu", lambda *a, **k: 1)
    assert tf.update_preflight(g, types.SimpleNamespace(), None, fresh=False, lv="1.2.0",
                               persist_issued=False).keep

    def ctrl_c(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(inst, "_arrow_menu", ctrl_c)
    with pytest.raises(ix.InstallerError) as e:
        tf.update_preflight(g, types.SimpleNamespace(), None, fresh=False, lv="1.2.0", persist_issued=False)
    assert e.value.message == "You stopped the installer, so nothing was changed." and e.value.code == ix.EXIT_ABORTED


def test_preflight_fatal_no_is_declined(tmp_path, fake_prepare, monkeypatch):
    g = _game(tmp_path)
    monkeypatch.setattr(td, "FATAL", frozenset({hashlib.sha256((g / "thinker.dll").read_bytes()).hexdigest()}))
    monkeypatch.setattr(tf, "_asks", lambda a: True)
    monkeypatch.setattr(inst, "_arrow_menu", lambda *a, **k: 1)          # "Cancel the update"
    with pytest.raises(ix.InstallerError) as e:
        tf.update_preflight(g, types.SimpleNamespace(), None, fresh=False, lv=ver.VERSION, persist_issued=False)
    assert e.value.code == ix.EXIT_DECLINED and e.value.title == "UPDATE CANCELLED"
    assert "does not start with your Thinker Mod 5.4" in e.value.message


def test_preflight_keep_consent_refused_for_fatal(tmp_path, monkeypatch):
    g = _game(tmp_path)
    monkeypatch.setattr(td, "FATAL", frozenset({hashlib.sha256((g / "thinker.dll").read_bytes()).hexdigest()}))
    monkeypatch.setattr(tf, "take_for_worker", lambda *a: tf.parse_consent(f"keep:{ver.VERSION}|1|2|game"))
    with pytest.raises(ix.InstallerError) as e:
        tf.update_preflight(g, types.SimpleNamespace(), None, fresh=False, lv=ver.VERSION, persist_issued=False)
    assert "was not installed on its own" in e.value.message


# ---------------------------------------------------------------- --fix-thinker (journey R)

class World:
    """A fake world for fix_thinker: a game folder, a receipt, a manifest, scripted answers."""

    def __init__(self, tmp_path, monkeypatch, *, label=b"Thinker Mod v5.4", installed=None, doc="default",
                 answers=(), latest=None):
        self.g = _game(tmp_path, label) if label else (tmp_path / "game")
        self.g.mkdir(exist_ok=True)
        self.answers = list(answers)
        self.asked = []
        self.title_kinds = []
        self.committed = []
        installed = installed or ver.VERSION
        if doc == "default":
            doc = {"protocol": 1, "manual_install_required": False, "unsupported_versions": [],
                   "unsupported_targets": [], "latest": latest or installed, "yanked": [], "issued": 1,
                   "thinker": tf.manifest_section(installed)}
            if latest:
                doc["thinker"]["release_pins"][latest] = "5.7.0"
                doc["thinker"]["pins"]["5.7.0"] = {"dll": SHA_B, "stamp": 9, "image_size": 9, "release_tag": "v5.7",
                                                   "download": {"asset": "Thinker_v5.7.zip", "sha256": SHA_A, "size": 9}}
        self.doc = doc
        import receipt as rc
        monkeypatch.setattr(rc, "read", lambda g: {"modules": {"base": {"version": installed}}, "target_id": None})
        monkeypatch.setattr(rc, "module_version", lambda s, n: installed)
        if doc is None:
            def no_net(*a, **k):
                raise ix.InstallerError("offline")
            monkeypatch.setattr(inst, "fetch_manifest", no_net)
        else:
            monkeypatch.setattr(inst, "fetch_manifest", lambda *a, **k: (b"", ""))
            import manifest as mf
            monkeypatch.setattr(mf, "load_verified", lambda *a, **k: self.doc)
        monkeypatch.setattr(ix, "ask", self._ask)                 # Q-L, still [Y/n]
        monkeypatch.setattr(inst, "_arrow_menu", self._menu)      # the Thinker choices (user 2026-11-15)
        monkeypatch.setattr(ix, "can_ask", lambda: True)          # the game's Update now window: a console
        monkeypatch.setattr(tf, "prepare", lambda *a, **k: types.SimpleNamespace(
            committed=False, dll=st.read_dll(self.g / "thinker.dll"), direction=st.UP, ts="5.5", report=None, plan=None))
        monkeypatch.setattr(tf, "commit", lambda prep, **k: self.committed.append(k))
        monkeypatch.setattr(tf, "finish", lambda prep: None)
        monkeypatch.setattr(tf, "summary_lines", lambda prep: [])
        monkeypatch.setattr(tf, "write_consent", lambda g, v: self.committed.append(("consent", v)) or True)
        monkeypatch.setattr(inst, "patch_datalinks_text", lambda g: {})
        monkeypatch.setattr(tf, "_relaunch_setup", lambda g: None)
        monkeypatch.setattr(inst, "lv_in_place", lambda g: True)  # a folder Longevity Vaccine is installed in (audit-k)
        tf._HANDOVER = None
        self.args = types.SimpleNamespace(wait_pid=None, manifest=None, offline=False)

    def _ask(self, prompt, title=None, notes=(), flush=False, title_kind=None):
        self.asked.append((prompt, list(notes)))
        self.title_kinds.append((title, title_kind))
        a = self.answers.pop(0)
        if isinstance(a, BaseException):
            raise a
        return a

    def _menu(self, title, items, before=(), at=0, notes=(), title_kind=None):
        """An arrow-key choice: recorded as (its options' first lines, notes); "" / "y" take the first option,
        anything else the second."""
        self.asked.append(([i[0] for i in items], list(notes)))
        self.title_kinds.append((title, title_kind))
        a = self.answers.pop(0)
        if isinstance(a, BaseException):
            raise a
        return 0 if a in ("", "y", "yes") else 1

    def run(self):
        return tf.fix_thinker(self.g, self.args)


def test_fix_thinker_only_yes(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, answers=[""])                     # the change
    assert w.run() == ix.EXIT_OK
    assert w.asked[0][0] == ["Update Thinker Mod to 5.5", "Keep Thinker Mod 5.4"]
    # thinker.ini is asked in the closing lines, directly before the changelog (user 2026-11-16), not under the summary
    assert len(w.asked) == 1
    assert w.committed == [{"route": "thinker"}]
    assert inst._VERDICT[0] == "UPDATE COMPLETE"


def test_a_thinker_swap_leaves_the_datalinks_help_text_patched(tmp_path, monkeypatch):
    """The swap replaces Thinker's smac_mod\\helpx.txt / conceptsx.txt with stock ones; Longevity's help-text
    patch must run AFTER it on every route (user 2026-11-15: a swap must leave Longevity's patches in place)."""
    order = []
    w = World(tmp_path, monkeypatch, answers=["", ""])
    monkeypatch.setattr(tf, "commit", lambda prep, **k: order.append("swap"))
    monkeypatch.setattr(inst, "patch_datalinks_text", lambda g: order.append("help text") or {})
    assert w.run() == ix.EXIT_OK
    assert order == ["swap", "help text"]
    # setup and the updater: the same order in install.py
    src = (Path(inst.__file__)).read_text(encoding="utf-8")
    for route in ('route="fresh"', 'route="longevity"'):
        at = src.index(f"thinker_flow.commit(tstep.prep, {route}")
        assert at < src.index("patch_datalinks_text(game_dir)", at), route


def test_fix_thinker_only_no_is_r1(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, answers=["n"])
    with pytest.raises(ix.InstallerError) as e:
        w.run()
    assert e.value.code == ix.EXIT_DECLINED and e.value.offer_play and not e.value.offer_play_default
    assert e.value.message == ("You chose to keep Thinker Mod 5.4, so nothing was changed. The game will tell you "
                               "about the mismatch again the next time it starts.")    # user 2026-11-15 (to confirm)


def test_fix_thinker_ctrl_c_at_q_t_changes_nothing(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, answers=[KeyboardInterrupt()])
    with pytest.raises(ix.InstallerError) as e:
        w.run()
    assert e.value.message == "You stopped the installer, so nothing was changed." and not w.committed


def test_fix_thinker_q_l_then_q_t_hands_over_with_a_pin_consent(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, latest="9.9.9", answers=["", ""])
    import bootstrap as bs
    up = bs.updater_dir(w.g) / "scripts"
    up.mkdir(parents=True)
    (up / "run-install.bat").write_text("@echo off")
    assert w.run() == ix.EXIT_OK
    assert w.asked[0][0] == ["Update Longevity Vaccine to 9.9.9", f"Keep Longevity Vaccine {ver.VERSION}"]
    assert w.asked[1][0] == ["Update Thinker Mod to 5.7", "Keep Thinker Mod 5.4"]
    consent = [c for c in w.committed if c[0] == "consent"][0][1]
    assert consent.startswith("5.7.0|") and consent.endswith("|fix")
    h = tf.pending_handover()
    assert h is not None and isinstance(h.cmd, str) and "--update" in h.cmd and "--no-wait" not in h.cmd


def test_fix_thinker_longevity_only_writes_keep(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, latest="9.9.9", answers=["", "n"])
    import bootstrap as bs
    up = bs.updater_dir(w.g) / "scripts"
    up.mkdir(parents=True)
    (up / "run-install.bat").write_text("@echo off")
    w.run()
    consent = [c for c in w.committed if c[0] == "consent"][0][1]
    assert consent.startswith("keep:9.9.9|")
    notes = w.asked[1][1]                       # Q-T after a yes to Q-L: no "If you choose 'Keep ...'" (user 2026-11-15)
    assert notes[-1] == tf.project_line() and notes[-2] == "" and "If you choose" not in " ".join(notes)


def test_fix_thinker_longevity_only_refused_for_fatal(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, latest="9.9.9", answers=["", "n"])
    sha = hashlib.sha256((w.g / "thinker.dll").read_bytes()).hexdigest()
    w.doc["thinker"]["fatal"]["9.9.9"] = [sha]
    with pytest.raises(ix.InstallerError) as e:
        w.run()
    assert e.value.code == ix.EXIT_DECLINED
    assert "neither mod is changed" in w.asked[1][1][-1]


def test_fix_thinker_q_l_no_then_thinker_only(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, latest="9.9.9", answers=["n", "", ""])
    assert w.run() == ix.EXIT_OK
    assert w.asked[1][0] == ["Update Thinker Mod to 5.5", "Keep Thinker Mod 5.4"] and {"route": "thinker"} in w.committed


def test_fix_thinker_downgrade_wording(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, label=b"Thinker Mod v5.8", answers=["n"])
    with pytest.raises(ix.InstallerError):
        w.run()
    prompt, notes = w.asked[0]
    assert prompt == ["Downgrade Thinker Mod from 5.8 to 5.5", "Keep Thinker Mod 5.8"]
    assert any(n.startswith("This is a downgrade! It replaces your newer Thinker Mod 5.8 with the older Thinker "
                            "Mod 5.5, the version Longevity Vaccine") for n in notes)


def test_fix_thinker_already_matching(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, label=None, answers=[])
    (w.g / "thinker.dll").write_bytes((Path(os.environ["LONGEVITY_REFS"]) / "thinker-release" / "v5.5" / "thinker.dll")
                                      .read_bytes()) if os.environ.get("LONGEVITY_REFS") else None
    if not (w.g / "thinker.dll").exists():
        with pytest.raises(ix.InstallerError) as e:
            w.run()
        assert "no Thinker Mod now" in e.value.message and e.value.offer_play
        return
    with pytest.raises(ix.InstallerError) as e:
        w.run()
    assert e.value.title == "ALREADY UP TO DATE" and not e.value.offer_play_default


def test_fix_thinker_offline_still_offers_thinker_only(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, doc=None, answers=["n"])
    with pytest.raises(ix.InstallerError):
        w.run()
    assert w.asked and w.asked[0][0] == ["Update Thinker Mod to 5.5", "Keep Thinker Mod 5.4"]


def test_fix_thinker_none_without_newer_release(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, label=None, answers=[])
    with pytest.raises(ix.InstallerError) as e:
        w.run()
    assert "no Thinker Mod now" in e.value.message


def test_handover_refuses_cmd_unsafe_paths(tmp_path, monkeypatch):
    g = tmp_path / "a&b"
    g.mkdir()
    monkeypatch.setattr(tf, "write_consent", lambda *a: pytest.fail("no consent for a refused path"))
    with pytest.raises(ix.InstallerError) as e:
        tf._hand_over(g, types.SimpleNamespace(manifest=None), "5.5.0|1|2|fix")
    assert "could not be started in a new window" in e.value.message


# ---------------------------------------------------------------- run_guarded: the declined code and the start offer

def test_run_guarded_declined_and_offer_play(monkeypatch, capsys, tmp_path):
    offered = []
    monkeypatch.setattr(ix, "offer_relaunch", lambda exe, default=True: offered.append(default) or False)
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)
    exe = tmp_path / "thinker.exe"
    exe.write_bytes(b"")

    def main():
        raise ix.InstallerError("You answered no, so nothing was changed.", code=ix.EXIT_DECLINED,
                                title="UPDATE CANCELLED", disk_note=False, offer_play=True, offer_play_default=False)
    assert ix.run_guarded(main, relaunch_exe=exe, log_dir=tmp_path) == ix.EXIT_DECLINED
    assert offered == [False]
    assert "UPDATE CANCELLED" in capsys.readouterr().out


def test_run_guarded_bare_declined_code(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)
    assert ix.run_guarded(lambda: ix.EXIT_DECLINED, log_dir=tmp_path) == ix.EXIT_DECLINED
    out = capsys.readouterr().out
    assert "UPDATE CANCELLED" in out and "DID NOT COMPLETE" not in out


def test_run_guarded_handover(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: pytest.fail("a hand-over closes on its own"))
    import time as _t
    monkeypatch.setattr(_t, "sleep", lambda s: None)
    started = []
    assert ix.run_guarded(lambda: ix.EXIT_OK, handover=lambda: (lambda: started.append(1) or True, lambda: None),
                          success_title="UPDATE HANDED OVER", log_dir=tmp_path) == ix.EXIT_OK
    assert started == [1]


def test_offer_relaunch_no_default(monkeypatch, tmp_path):
    from test_arrow_choices import _keys
    exe = tmp_path / "x.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(ix, "interactive", lambda: True)
    started = []
    monkeypatch.setattr(ix.subprocess, "Popen", lambda *a, **k: started.append(k))
    _keys(monkeypatch, "enter")
    ix.offer_relaunch(exe, default=False)                                          # Enter = Close this window
    assert started == []
    _keys(monkeypatch, "up", "enter")
    assert ix.offer_relaunch(exe, default=False)
    assert "LONGEVITY_THINKER_CONSENT" not in started[0]["env"]


# ---------------------------------------------------------------- round-7 regressions

def test_impossible_dev_date_is_refused_and_never_crashes():
    assert tf.parse_consent("dev-20251340|1|2|game") is None
    assert st.ts_display("dev-20251340") == "dev-20251340"
    doc = _doc()
    doc["thinker"]["release_pins"]["1.4.0"] = "dev-20251340"
    assert "1.4.0" not in tf.thinker_info(doc).release_pins


def test_a_hostile_issued_floor_is_capped(tmp_path):
    (tmp_path / tf.ISSUED_FILE).parent.mkdir(parents=True)
    (tmp_path / tf.ISSUED_FILE).write_text("9" * 30, encoding="ascii")
    assert tf.issued_floor(tmp_path) <= int(time.time()) + 86400
    assert tf.issued_check(tmp_path, tf.thinker_info(_doc(issued=int(time.time()) + 90000)), persist=False)


@pytest.mark.parametrize("label,have", [(b"Thinker Mod v5.70000", "?"), (b"Thinker Mod v5.4.1.2", "?"),
                                        (b"Thinker Mod v5", "5.0.0"), (b"Thinker Mod v65535.1", "65535.1.0")])
def test_check_line_have_stays_inside_the_dlls_grammar(tmp_path, label, have):
    g = _game(tmp_path, label)
    assert tf.check_line(g, _doc(), "1.3.0").split("=", 1)[1].split("|")[0] == have



@pytest.mark.skipif(os.name != "nt", reason="cmd.exe")
def test_handover_command_really_runs_through_cmd(tmp_path, monkeypatch):
    """The hand-over string through the REAL cmd.exe, in a folder with a space (round-7 review, B2): the batch
    file must run and receive exactly the arguments. A harmless stand-in .bat records them."""
    g = tmp_path / "Game Folder"
    import bootstrap as bs
    up = bs.updater_dir(g) / "scripts"
    up.mkdir(parents=True)
    out = tmp_path / "args.txt"
    (up / "run-install.bat").write_text(f'@echo off\necho %*> "{out}"\n', encoding="ascii")
    monkeypatch.setattr(tf, "write_consent", lambda *a: True)
    tf._HANDOVER = None
    tf._hand_over(g, types.SimpleNamespace(manifest=None), "5.5.0|1|2|fix")
    h = tf.pending_handover()
    import subprocess as sp
    r = sp.run(h.cmd, cwd=h.cwd, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    got = out.read_text(encoding="ascii", errors="replace").strip()
    assert got.startswith("--update --only-listed --game-dir") and str(g) in got and "--from-fix-thinker" in got


def test_recovery_on_the_longevity_route_follows_the_exe(tmp_path):
    """Round-7 review M1: a complete NEW Thinker beside the OLD exe is rolled BACK, not called finished."""
    game = tmp_path / "game"
    staged_dir = tmp_path / "staged"
    for root, files in ((game, {"thinker.dll": b"old"}), (staged_dir, {"thinker.dll": b"new"})):
        root.mkdir()
        for k, v in files.items():
            (root / k).write_bytes(v)
    p = tu.plan(game, "5.5.0", {"thinker.dll": staged_dir / "thinker.dll"}, known=set(), old_stock=None,
                ts="5.5", from_label=st.parse_label("Thinker Mod v5.4"))
    tu.commit(p, route="longevity", exe={"current": "aa", "staged": "bb"})
    assert tu.recover(game, live_exe_md5="aa") == tu.UNDONE
    assert (game / "thinker.dll").read_bytes() == b"old"


def test_recovery_after_the_datalinks_repatch_is_finished(tmp_path):
    """Round-7 review D1: from step 5 the live help files are re-patched; that is not an unfinished swap."""
    game = tmp_path / "game"
    staged_dir = tmp_path / "staged"
    for root, files in ((game, {"thinker.dll": b"old", "smac_mod/helpx.txt": b"old help"}),
                        (staged_dir, {"thinker.dll": b"new", "smac_mod/helpx.txt": b"new help"})):
        for k, v in files.items():
            (root / k).parent.mkdir(parents=True, exist_ok=True)
            (root / k).write_bytes(v)
    staged = {k: staged_dir / k for k in ("thinker.dll", "smac_mod/helpx.txt")}
    p = tu.plan(game, "5.5.0", staged, known=set(), old_stock=None, ts="5.5", from_label=st.parse_label("Thinker Mod v5.4"))
    tu.commit(p, route="thinker")
    tu.set_step(game, 5)
    (game / "smac_mod" / "helpx.txt").write_bytes(b"new help, re-patched")
    assert tu.recover(game) == tu.FINISHED and (game / "thinker.dll").read_bytes() == b"new"



# ---------------------------------------------------------------- final-review regressions

def test_a_floor_from_the_future_is_discarded_and_never_stored(tmp_path):
    f = tmp_path / tf.ISSUED_FILE
    f.parent.mkdir(parents=True)
    f.write_text(str(int(time.time()) + 10 * 86400), encoding="ascii")
    assert tf.issued_floor(tmp_path) == 0 and not f.exists()
    assert tf.issued_check(tmp_path, tf.thinker_info(_doc(issued=int(time.time()) + 10 * 86400)), persist=True)
    assert tf.issued_floor(tmp_path) == 0                       # a manifest from the future is not stored
    assert tf.issued_check(tmp_path, tf.thinker_info(_doc(issued=int(time.time()))), persist=True)


def test_step_four_breaks_the_tie_when_the_exe_did_not_change(tmp_path):
    """A release that changes only uimod.dll: CURRENT == STAGED; step 4 recorded means forward."""
    game, staged_dir = tmp_path / "game", tmp_path / "staged"
    for root, data in ((game, b"old"), (staged_dir, b"new")):
        root.mkdir()
        (root / "thinker.dll").write_bytes(data)
    p = tu.plan(game, "5.5.0", {"thinker.dll": staged_dir / "thinker.dll"}, known=set(), old_stock=None, ts="5.5",
                from_label=st.parse_label("Thinker Mod v5.4"))
    tu.commit(p, route="longevity", exe={"current": "m", "staged": "m"})
    tu.set_step(game, 4)
    assert tu.recover(game, live_exe_md5="m") == tu.FINISHED and (game / "thinker.dll").read_bytes() == b"new"


def test_a_recovery_makes_the_verdict_say_so(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, answers=["n"])
    monkeypatch.setattr(inst, "_recover_thinker", lambda g, s: tu.UNDONE)
    with pytest.raises(ix.InstallerError) as e:
        w.run()
    assert e.value.message.startswith("The interrupted Thinker Mod change was undone. ")
    assert "so nothing else was changed" in e.value.message and e.value.changed is True


def test_a_failed_handover_is_not_a_success(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ix, "wait_for_key", lambda *a, **k: None)
    failed = []
    code = ix.run_guarded(lambda: ix.EXIT_OK, handover=lambda: (lambda: False, lambda: failed.append(1)),
                          log_dir=tmp_path)
    assert code == ix.EXIT_ABORTED and failed == [1]
    assert "NOTHING WAS CHANGED" in capsys.readouterr().out


def test_with_and_keep_thinker_cannot_be_combined(tmp_path):
    import subprocess as sp
    env = dict(os.environ, LONGEVITY_NO_WAIT="1")
    r = sp.run([sys.executable, str(_SCRIPTS / "install.py"), "--with-thinker", "--keep-thinker",
                "--game-dir", str(tmp_path)], capture_output=True, text=True, env=env, cwd=str(_SCRIPTS), timeout=120)
    assert "cannot be combined" in r.stdout and r.returncode == ix.EXIT_ABORTED


def test_a_drive_root_game_folder_is_quoted_safely(monkeypatch):
    monkeypatch.setattr(tf, "write_consent", lambda *a: True)
    import bootstrap as bs
    monkeypatch.setattr(bs, "updater_dir", lambda g: Path(__file__).resolve().parent)    # any existing folder
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    tf._HANDOVER = None
    tf._hand_over(Path("D:\\"), types.SimpleNamespace(manifest=None), "5.5.0|1|2|fix")
    assert '--game-dir D:\\.' in tf.pending_handover().cmd


# ---------------------------------------------------------------- dev_test_manifest's Thinker scenarios

@pytest.mark.parametrize("scenario, line", [
    ("thinker", "thinker=5.5.0|5.6.0|6291456|1"),
    ("thinker-down", "thinker=5.5.0|5.4.0|6291456|1"),
    ("thinker-fatal", "thinker=5.5.0|5.6.0|6291456|0"),
])
def test_the_signers_thinker_scenarios_give_the_check_line_the_game_reads(tmp_path, scenario, line):
    import dev_test_manifest as dtm
    doc = dtm.build(scenario, "1.0.0", tmp_path)
    dll = _dll(b"Thinker Mod v5.5")
    (tmp_path / "thinker.dll").write_bytes(dll)
    if scenario == "thinker-fatal":                     # the scenario lists the compiled pin's dll as fatal
        doc["thinker"]["fatal"]["9.9.9"] = [hashlib.sha256(dll).hexdigest()]
    assert tf.check_line(tmp_path, doc, doc["latest"]) == line
    pin, _meta = tf.thinker_info(doc).pins[line.split("|")[1]]
    assert tf.src.download_url(pin).endswith("/lvtest-not-a-release.zip")


# ---------------------------------------------------------------- button names (user 2026-11-14: "Yes, match it")

def test_every_console_line_names_a_button_in_single_quotes():
    """The startup box quotes its buttons as 'Update now' / 'Not now' / 'Don't ask me again'; every installer
    line that names one does the same. Docstrings and comments are not console text."""
    import io
    import re
    import tokenize
    buttons = re.compile(r"Update now|Not now|Don't ask me again")
    bad = []
    for path in sorted(_SCRIPTS.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type != tokenize.STRING:
                continue
            body = tok.string.lstrip("rRbBuUfF")
            if body.startswith(('"""', "\'\'\'")):
                continue
            for m in buttons.finditer(body):
                before, after = body[m.start() - 1:m.start()], body[m.end():m.end() + 1]
                if before != "'" or after != "'":
                    bad.append(f"{path.name}:{tok.start[0]}: {body[:90]}")
    assert not bad, "\n".join(bad)


# ---------------------------------------------------------------- the Thinker question block (user rulings 2026-11-14)

BLOCK_54_55 = [
    "Longevity Vaccine 1.0.0 works with Thinker Mod 5.5. This game folder has Thinker Mod 5.4.",
    "",
    "This installer can update Thinker Mod from 5.4 to 5.5. Your Thinker Mod 5.4 files will be backed up to a new "
    "folder in LongevityMods\\backups.",
    "",
    "Your Thinker settings will be carried over into the new version of Thinker. You do not need to change them.",
    "",
    "We STRONGLY recommend installing Thinker Mod 5.5 while playing with Thinker + Longevity Vaccine.",
    "",
    "Thinker Mod is a project by Induktio and is not affiliated with Longevity Vaccine. Learn more here: "
    "https://github.com/induktio/thinker",
]                                              # no "If you choose 'Keep ...'" after it (user 2026-11-15)


def test_the_thinker_question_block_reads_as_ruled(tmp_path, monkeypatch):
    monkeypatch.setattr(ver, "VERSION", "1.0.0")   # before World: it reads VERSION for the installed receipt
    w = World(tmp_path, monkeypatch, answers=["n"])
    with pytest.raises(ix.InstallerError):
        w.run()
    prompt, notes = w.asked[0]
    assert prompt == ["Update Thinker Mod to 5.5", "Keep Thinker Mod 5.4"]
    assert notes == BLOCK_54_55
    text = " ".join(notes)
    for gone in ("1 MB", "can change the AI", "multiplayer", "nothing deletes", "The installer can"):
        assert gone not in text


def test_the_repository_link_and_author_come_from_the_constants():
    assert tf.project_line().endswith(f"Learn more here: {tf.src.THINKER_REPO_URL}")
    assert tf.src.RELEASE_PAGE_PREFIX.startswith(tf.src.THINKER_REPO_URL + "/")
    assert tf.src.THINKER_AUTHOR in tf.project_line()


def test_a_downgrade_is_never_called_an_update(tmp_path):
    g = _game(tmp_path, b"Thinker Mod v5.8")
    _s, dll = st.classify(g, "0" * 64)
    _t, notes, options = tf.q1_texts(dll, "1.2.0", _pin(), tf.compiled_meta(), fresh=False, fatal=False)
    text = " ".join(notes)
    assert "Your Thinker settings will be carried over into Thinker Mod 5.5. You do not need to change them." in notes
    assert "We STRONGLY recommend installing Thinker Mod 5.5 while playing with Thinker + Longevity Vaccine." in notes
    assert "This installer can do this downgrade for you. Your Thinker Mod 5.8 files will be backed up" in text
    assert "new version" not in text and "updat" not in text.lower()     # the notes never say "update"
    assert options[0].startswith("Also downgrade") and "updat" not in options[0].lower()


def _colour(monkeypatch):
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    return ix._RED, ix._GREEN, ix._BLUE, ix._YELLOW, ix._RESET


def test_the_block_colours(tmp_path, monkeypatch):
    """User 2026-11-14: in the notes only the version numbers carry colour (installed red, supported green),
    "Thinker Mod" itself plain; the author blue; the recommendation yellow. The prompt line keeps "Thinker Mod"
    blue. Plain on a console without colour (every other test)."""
    R, G, B, Y, X = _colour(monkeypatch)
    g = _game(tmp_path)                                   # Thinker Mod 5.4
    _s, dll = st.classify(g, "0" * 64)
    _t, notes, options = tf.q1_texts(dll, "1.2.0", _pin(), tf.compiled_meta(), fresh=False, fatal=False)
    assert notes[0] == f"This game folder has Thinker Mod {R}5.4{X}. Longevity Vaccine 1.2.0 needs Thinker Mod {G}5.5{X}."
    assert notes[2] == (f"This installer can update Thinker Mod for you. Your Thinker Mod {R}5.4{X} files will be "
                        "backed up to a new folder in LongevityMods\\backups.")
    assert notes[4] == "Your Thinker settings will be carried over into the new version of Thinker. You do not need to change them."
    assert notes[6] == f"{Y}We STRONGLY recommend installing Thinker Mod 5.5 while playing with Thinker + Longevity Vaccine.{X}"
    assert notes[8] == (f"Thinker Mod is a project by {B}Induktio{X} and is not affiliated with Longevity Vaccine. "
                        f"Learn more here: {B}https://github.com/induktio/thinker{X}")
    # the URL is one unbroken token inside its colour run (a console's link detection), nothing after the reset
    assert re.search(rf" {re.escape(B)}https://\S+{re.escape(X)}$", notes[8])
    assert notes[8].split(B)[-1] == f"https://github.com/induktio/thinker{X}"
    assert len(notes) == 9                                # Q1 ends at the project line (user 2026-11-15)
    assert options == [f"Also update {B}Thinker Mod{X} to {G}5.5{X}", "Only update Longevity Vaccine"]
    for n in notes:                                       # no blue "Thinker Mod", no whole coloured build
        assert f"{B}Thinker Mod" not in n and f"{R}Thinker Mod" not in n and f"{G}Thinker Mod" not in n


def test_the_block_colours_downgrade_and_other(tmp_path, monkeypatch):
    R, G, B, Y, X = _colour(monkeypatch)
    g = _game(tmp_path, b"Thinker Mod v5.8")
    _s, dll = st.classify(g, "0" * 64)
    _t, notes, options = tf.q1_texts(dll, "1.2.0", _pin(), tf.compiled_meta(), fresh=False, fatal=False)
    assert notes[2] == (f"This is a downgrade! It replaces your newer Thinker Mod {R}5.8{X} with the older "
                        f"Thinker Mod {G}5.5{X}, the version Longevity Vaccine 1.2.0 supports.")
    assert f"Your Thinker settings will be carried over into Thinker Mod {G}5.5{X}." in notes[5]
    assert options[0] == f"Also downgrade {B}Thinker Mod{X} from {R}5.8{X} to {G}5.5{X}"
    # a build without a number: red as a whole, in the notes and on the prompt line
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod develop build"))
    _s, dll = st.classify(g, "0" * 64)
    _t, notes, options = tf.q1_texts(dll, "1.2.0", _pin(), tf.compiled_meta(), fresh=False, fatal=False)
    assert notes[0] == (f"This game folder has {R}a development build of Thinker Mod{X}. Longevity Vaccine 1.2.0 "
                        f"needs Thinker Mod {G}5.5{X}.")
    assert notes[2] == (f"This installer can change Thinker Mod for you. It replaces {R}a development build of Thinker "
                        f"Mod{X} with Thinker Mod {G}5.5{X}, the version Longevity Vaccine 1.2.0 supports. Your "
                        f"{R}development build of Thinker Mod{X} will be backed up to a new folder in "
                        "LongevityMods\\backups.")
    assert options[0] == f"Also replace your {R}development build of Thinker Mod{X} with {B}Thinker Mod{X} {G}5.5{X}"
    # the same number as the supported build: the number does not name it, so the phrase is red as a whole
    (g / "thinker.dll").write_bytes(_dll(b"Thinker Mod v5.5"))
    _s, dll = st.classify(g, "0" * 64)
    _t, notes, options = tf.q1_texts(dll, "1.2.0", _pin(), tf.compiled_meta(), fresh=False, fatal=False)
    assert notes[0].startswith(f"This game folder has {R}a different build of Thinker Mod 5.5{X}.")
    assert options[0] == f"Also replace your {R}different build of Thinker Mod 5.5{X} with {B}Thinker Mod{X} {G}5.5{X}"
    # a numbered build on a prompt line (a development pin makes even a plain version OTHER): blue words, red number
    assert tf._have(st.parse_version("5.4"), "5.5") == f"your {B}Thinker Mod{X} {R}5.4{X}"
    assert tf._tm("5.5") == f"{B}Thinker Mod{X} {G}5.5{X}"


def test_the_block_colours_journey_r_and_the_blue_title(tmp_path, monkeypatch):
    R, G, B, Y, X = _colour(monkeypatch)
    monkeypatch.setattr(ver, "VERSION", "1.0.0")   # before World: it reads VERSION for the installed receipt
    w = World(tmp_path, monkeypatch, answers=["n"])
    with pytest.raises(ix.InstallerError):
        w.run()
    prompt, notes = w.asked[0]
    assert notes[0] == f"Longevity Vaccine 1.0.0 works with Thinker Mod {G}5.5{X}. This game folder has Thinker Mod {R}5.4{X}."
    assert notes[2].startswith(f"This installer can update Thinker Mod from {R}5.4{X} to {G}5.5{X}. Your Thinker Mod "
                               f"{R}5.4{X} files will be backed up")
    assert prompt == [f"Update {B}Thinker Mod{X} to {G}5.5{X}", f"Keep {B}Thinker Mod{X} {R}5.4{X}"]
    assert w.title_kinds[0] == ("Thinker Mod", "keys")


def test_a_question_title_takes_its_colour_after_capitals(monkeypatch, capsys):
    R, G, B, Y, X = _colour(monkeypatch)
    ix.question_head("Thinker Mod downgrade", ["a note"], title_kind="keys")
    ix.question_head("Longevity Vaccine update")
    out = capsys.readouterr().out
    assert f" {B}THINKER MOD DOWNGRADE{X}\n" in out and " LONGEVITY VACCINE UPDATE\n" in out


# ---------------------------------------------------------------- the download line (user 2026-11-14)

_DEV_PIN = tf.src.Pin("dev-20251109", dropbox="scl/fo/exampleFolderId00/exampleShareKey0001/develop/"
                                           "Thinker-dev-20251109.zip", rlkey="examplerlkey0000000000000",
                   zip_size=9, zip_sha256=SHA_A)


@pytest.mark.parametrize("pin", [tf.compiled_pin(), _DEV_PIN], ids=["github", "dropbox"])
@pytest.mark.parametrize("route", ["R", "A"])
def test_the_download_line_names_the_url_the_fetch_requests(tmp_path, monkeypatch, pin, route):
    """The line names the exact URL handed to fetch.download (the request, not a redirect target),
    uncoloured, with no credentials and no query beyond Dropbox's own share key; no "(you accepted this above)"."""
    import fetch
    from urllib.parse import parse_qs, urlsplit
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    said, requested = [], []
    monkeypatch.setattr(ix, "say", lambda *p: said.append(" ".join(map(str, p))))

    def download(url, dest, **kw):
        requested.append(url)
        raise fetch.FetchError("stop here")
    monkeypatch.setattr(fetch, "download", download)
    g = _game(tmp_path)
    with pytest.raises(ix.InstallerError) as e:
        tf.prepare(g, pin, tf.compiled_meta(), "1.0.0", route=route)
    assert requested == [tf.src.download_url(pin)]
    line = [s for s in said if "Downloading Thinker Mod" in s]
    assert line == [f"  Downloading Thinker Mod {st.ts_display(pin.pin_id)} from {requested[0]}"]
    assert "\x1b" not in line[0] and not line[0].endswith("...")
    u = urlsplit(requested[0])
    assert u.scheme == "https" and u.username is None and u.password is None and "@" not in u.netloc
    assert u.netloc in ("github.com", "www.dropbox.com") and not u.fragment
    assert set(parse_qs(u.query)) <= {"rlkey", "dl"}
    assert not any("accepted this" in s or "--with-thinker" in s for s in said)
    # the failure names the same URL, uncoloured, in place of "its author's GitHub release"
    assert e.value.message.startswith(f"Thinker Mod {st.ts_display(pin.pin_id)} could not be downloaded from "
                                      f"{requested[0]}, so nothing was changed.")
    assert "\x1b" not in e.value.message and "author's" not in e.value.message


def test_no_route_carries_an_accepted_note(tmp_path, fake_prepare, monkeypatch):
    monkeypatch.setattr(tf, "_asks", lambda a: True)
    monkeypatch.setattr(inst, "_arrow_menu", lambda *a, **k: 0)
    g = _game(tmp_path)
    tf.update_preflight(g, types.SimpleNamespace(), None, fresh=False, lv="1.2.0", persist_issued=False)
    assert fake_prepare and "route_text" not in fake_prepare[0][1]
    assert "you accepted this" not in open(tf.__file__, encoding="utf-8").read()


def test_fetch_zip_refuses_a_url_other_than_the_pins(tmp_path):
    with pytest.raises(tf.src.SourceError):
        tf.src.fetch_zip(tf.compiled_pin(), tmp_path, url="https://example.invalid/x.zip")


# ---------------------------------------------------------------- CL: the changelog offer (user 2026-11-15)

def _cl_game(tmp_path, monkeypatch, copy=True):
    g = _game(tmp_path, b"Thinker Mod v5.5")
    (g / "LongevityMods").mkdir(exist_ok=True)
    (g / tf.RECORD_FILE).write_text(json.dumps({"from": "Thinker Mod 5.4", "to": td.PIN_VERSION, "at": 2000000000,
                                                "changelog_offered": False}), encoding="utf-8")
    if copy:
        (g / "LongevityMods" / "thinker-changelog-5.5.txt").write_text("changes", encoding="utf-8")
    return g


def test_the_changelog_offer_is_the_question_alone(tmp_path, monkeypatch, capsys):
    """No rule, no "THINKER MOD CHANGELOG" title, no "comes with a list of its changes": an arrow choice without
    a title (user-approved 2026-11-15), one empty line above it and one after it before the play note."""
    from test_arrow_choices import _keys
    g = _cl_game(tmp_path, monkeypatch)
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _keys(monkeypatch, "down", "enter")
    ix.say("Thinker Mod updated from 5.4 to 5.5.")
    tf.offer_changelog(g, 1999999999)
    out = capsys.readouterr().out
    assert "CHANGELOG" not in out and "comes with a list" not in out and ix.RULE not in out
    assert out.startswith("Thinker Mod updated from 5.4 to 5.5.\n\n Up/Down: move   Enter: choose\n"
                          " -> Open the Thinker Mod 5.5 changelog\n    Don't open it\n")
    assert out.endswith("\n\n")
    assert json.loads((g / tf.RECORD_FILE).read_text(encoding="utf-8"))["changelog_offered"] is True
    monkeypatch.setattr(inst, "_read_key", lambda: pytest.fail("offered twice"))
    tf.offer_changelog(g, 1999999999)                    # once only


def test_the_changelog_question_keeps_its_blue_hint(tmp_path, monkeypatch, capsys):
    from test_arrow_choices import _keys
    g = _cl_game(tmp_path, monkeypatch)
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    _keys(monkeypatch, "down", "enter")
    monkeypatch.setattr(ix, "_colour_ok", lambda: True)
    tf.offer_changelog(g, 1999999999)
    assert f" {ix._BLUE}Up/Down: move   Enter: choose{ix._RESET}\n" in capsys.readouterr().out


def test_the_changelog_falls_back_to_a_line_when_it_cannot_ask_or_has_no_copy(tmp_path, monkeypatch, capsys):
    g = _cl_game(tmp_path, monkeypatch)
    monkeypatch.setattr(ix, "can_ask", lambda: False)
    tf.offer_changelog(g, 1999999999)
    assert capsys.readouterr().out.strip() == ("What's new in Thinker Mod 5.5: LongevityMods\\thinker-changelog-5.5.txt "
                                               f"in your game folder, or online: {tf.CHANGELOG_URL}")
    (tmp_path / "b").mkdir()
    g2 = _cl_game(tmp_path / "b", monkeypatch, copy=False)
    tf.offer_changelog(g2, 1999999999)
    assert capsys.readouterr().out.strip() == f"What's new in Thinker Mod: {tf.CHANGELOG_URL}"


def test_a_yes_opens_the_changelog_with_one_plain_line(tmp_path, monkeypatch, capsys):
    """User 2026-11-15: no "(newest changes at the top)"."""
    g = _cl_game(tmp_path, monkeypatch)
    monkeypatch.setattr(ix, "can_ask", lambda: True)
    from test_arrow_choices import _keys
    _keys(monkeypatch, "enter")
    started = []
    monkeypatch.setattr(tf.subprocess, "Popen", lambda argv, **k: started.append(argv))
    tf.offer_changelog(g, 1999999999)
    out = capsys.readouterr().out
    assert started and started[0][-1].endswith("thinker-changelog-5.5.txt")
    assert "Opening the Thinker Mod 5.5 changelog in Notepad. If it does not appear, it is in your game folder at " \
           "LongevityMods" in out
    assert "newest changes" not in out
