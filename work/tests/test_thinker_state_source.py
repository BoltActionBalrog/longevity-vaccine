"""thinker_state (detection and naming) and thinker_source (the pinned build's download and unpacking).
Throwaway folders and synthetic zips only: no network, no game."""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import thinker_data as td      # noqa: E402
import thinker_source as src   # noqa: E402
import thinker_state as st     # noqa: E402

_FIXTURE = Path(__file__).resolve().parent / "thinker_labels.json"


# ---------------------------------------------------------------- labels and names

@pytest.mark.skipif(not _FIXTURE.is_file(), reason="shared label fixture not present yet")
def test_shared_label_fixture():
    cases = json.loads(_FIXTURE.read_text(encoding="utf-8"))["cases"]
    for c in cases:
        lab = st.parse_label(c["label"])
        assert lab.kind == c["kind"], c
        assert lab.version == c["version"], c
        assert st.run_name(lab) == c["run"], c
        assert st.run_name(lab, c["vs"]) == c["run_vs"], c
        assert st.same_number(lab, c["vs"]) == c["same"], c


def test_yours_forms():
    v = st.parse_label("Thinker Mod v5.4")
    assert st.yours(v) == "your Thinker Mod 5.4"
    assert st.yours(st.parse_label("Thinker Mod v5.5"), "5.5") == "your different build of Thinker Mod 5.5"
    assert st.yours(st.parse_label("Thinker Mod develop build")) == "your development build of Thinker Mod"
    assert st.yours(st.Label(), capital=True) == "Your unrecognised build of Thinker Mod"


def test_direction():
    assert st.direction(st.parse_label("Thinker Mod v5.4"), "5.5") == st.UP
    assert st.direction(st.parse_label("Thinker Mod v5.6"), "5.5") == st.DOWN
    assert st.direction(st.parse_label("Thinker Mod v5.5"), "5.5") == st.OTHER
    assert st.direction(st.parse_label("Thinker Mod develop build"), "5.5") == st.OTHER
    assert st.direction(st.parse_label("Thinker Mod v5.4"), "dev-20251109", pin_is_dev=True) == st.OTHER


def test_ts_display():
    assert st.ts_display("5.5.0") == "5.5"
    assert st.ts_display("5.6.1") == "5.6.1"
    assert st.ts_display("dev-20251109") == "rel. Nov 9 2025"
    assert st.ts_display("dev-20240731") == "rel. Jul 31 2024"


def _dll(label: bytes, stamp=0x6A821052, size=0x19F000, pad=b"") -> bytes:
    pe = 0x80
    head = bytearray(pe + 0x58)
    head[:2] = b"MZ"
    head[0x3C:0x40] = pe.to_bytes(4, "little")
    head[pe:pe + 4] = b"PE\0\0"
    head[pe + 8:pe + 12] = stamp.to_bytes(4, "little")
    head[pe + 0x50:pe + 0x54] = size.to_bytes(4, "little")
    return bytes(head) + pad + label + b"\0" + b"x" * 16 + label + b"\0"


def test_classify(tmp_path):
    assert st.classify(tmp_path, "0" * 64) == (st.NONE, None)
    data = _dll(b"Thinker Mod v5.5")
    (tmp_path / "thinker.dll").write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    state, dll = st.classify(tmp_path, sha.upper())
    assert state == st.PIN and dll.label.version == "5.5" and dll.stamp == 0x6A821052
    state, dll = st.classify(tmp_path, "0" * 64)
    assert state == st.OFF_PIN
    assert st.header_matches(dll, 0x6A821052, 0x19F000)        # the game would call it the pin


def test_dll_label_disagreement_is_unrecognised():
    data = _dll(b"Thinker Mod v5.5") + b"Thinker Mod v5.6\0"
    assert st.dll_label(data).kind == st.UNRECOGNISED
    assert st.dll_label(_dll(b"Thinker Mod develop build")).kind == st.DEVELOP
    assert st.dll_label(b"no label here").kind == st.UNRECOGNISED


@pytest.mark.skipif(not Path(os.environ.get("LONGEVITY_REFS", "")).joinpath("thinker-release", "v5.5",
                                                                          "thinker.dll").is_file(),
                    reason="LONGEVITY_REFS not set")
def test_real_5_5_dll():
    p = Path(os.environ["LONGEVITY_REFS"]) / "thinker-release" / "v5.5" / "thinker.dll"
    dll = st.read_dll(p)
    assert dll.label == st.parse_label("Thinker Mod v5.5")
    assert dll.sha256 == td.PIN_DLL_SHA256
    assert (dll.stamp, dll.image_size) == (0x6A821052, 0x19F000)


# ---------------------------------------------------------------- paths and addresses

@pytest.mark.parametrize("path", ["thinker.dll", "german/alphax.txt", "smac_mod/helpx.txt", "basenames/hive.txt",
                                  "Changelog.md"])
def test_allowed_paths(path):
    assert src.check_path(path) == path


@pytest.mark.parametrize("path", ["../x.txt", "/abs.txt", "a/b/c.txt", "other/x.txt", "uimod.dll",
                                  "LongevityMods/x.txt", "con.txt", "smac_mod/aux", "x .txt ", "x:y",
                                  "terranx.exe", "", "german/..", "nul"])
def test_refused_paths(path):
    with pytest.raises(src.SourceError):
        src.check_path(path)


def test_compiled_pin_paths_all_pass():
    pin = src.compiled_pin(td)
    assert len(pin.files) == 28
    for path, _ in pin.files:
        src.check_path(path)


def test_urls_github():
    pin = src.compiled_pin(td)
    assert src.download_url(pin) == "https://github.com/induktio/thinker/releases/download/v5.5/Thinker_v5.5.zip"
    assert src.page_url(pin) == "https://github.com/induktio/thinker/releases/tag/v5.5"


def test_urls_dropbox_verified_form():
    pin = src.Pin("dev-20251109", dropbox="scl/fo/exampleFolderId00/exampleShareKey0001/develop/"
                                          "Thinker-dev-20251109.zip", rlkey="examplerlkey0000000000000")
    assert src.download_url(pin) == ("https://www.dropbox.com/scl/fo/exampleFolderId00/exampleShareKey0001/"
                                     "develop/Thinker-dev-20251109.zip?rlkey=examplerlkey0000000000000&dl=1")
    assert src.page_url(pin).endswith("&dl=0")


@pytest.mark.parametrize("pin", [
    src.Pin("x", tag="v5.5/../evil", asset="a.zip"),
    src.Pin("x", tag="v5.5", asset="a.exe"),
    src.Pin("x", tag="5.5", asset="a.zip"),
    src.Pin("x", dropbox="scl/fo/../../evil.zip"),
    src.Pin("x", dropbox="sh/abc/def.zip"),
    src.Pin("x", dropbox="scl/fi/abcdefghij/x.zip", rlkey="BAD KEY"),
])
def test_bad_pins_are_refused(pin):
    with pytest.raises(src.SourceError):
        src.download_url(pin)


# ---------------------------------------------------------------- extraction

def _zip(files: dict, extra: dict = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in {**files, **(extra or {})}.items():
            z.writestr(k, v)
    return buf.getvalue()


def _pin(files: dict, blob: bytes) -> src.Pin:
    return src.Pin("5.5.0", tag="v5.5", asset="Thinker_v5.5.zip", zip_size=len(blob),
                   zip_sha256=hashlib.sha256(blob).hexdigest(),
                   files=tuple(sorted((k, hashlib.sha256(v).hexdigest()) for k, v in files.items())))


def test_extract_only_listed_files(tmp_path):
    files = {"thinker.dll": b"dll", "german/alphax.txt": b"de", "basenames/hive.txt": b"h"}
    blob = _zip(files, extra={"../evil.txt": b"x", "unlisted.txt": b"y"})
    z = tmp_path / "t.zip"
    z.write_bytes(blob)
    out = src.extract(_pin(files, blob), z, tmp_path / "out")
    assert sorted(out) == sorted(files)
    assert (tmp_path / "out" / "german" / "alphax.txt").read_bytes() == b"de"
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "out" / "unlisted.txt").exists()


def test_extract_refuses_a_changed_zip_or_member(tmp_path):
    files = {"thinker.dll": b"dll"}
    blob = _zip(files)
    pin = _pin(files, blob)
    z = tmp_path / "t.zip"
    z.write_bytes(blob + b"tail")
    with pytest.raises(src.SourceError):
        src.extract(pin, z, tmp_path / "out")
    other = _zip({"thinker.dll": b"DLL"})
    z.write_bytes(other)
    pin2 = src.Pin(**{**pin.__dict__, "zip_size": len(other), "zip_sha256": hashlib.sha256(other).hexdigest()})
    with pytest.raises(src.SourceError):
        src.extract(pin2, z, tmp_path / "out")


def test_extract_refuses_a_missing_member(tmp_path):
    files = {"thinker.dll": b"dll", "thinker.exe": b"exe"}
    blob = _zip({"thinker.dll": b"dll"})
    pin = _pin(files, blob)
    z = tmp_path / "t.zip"
    z.write_bytes(blob)
    with pytest.raises(src.SourceError):
        src.extract(pin, z, tmp_path / "out")


_REAL_ZIP = os.environ.get("LONGEVITY_THINKER_ZIP", "")


@pytest.mark.skipif(not Path(_REAL_ZIP).is_file() if _REAL_ZIP else True, reason="LONGEVITY_THINKER_ZIP not set")
def test_real_github_zip_extracts(tmp_path):
    out = src.extract(src.compiled_pin(td), Path(_REAL_ZIP), tmp_path)
    assert len(out) == 28
