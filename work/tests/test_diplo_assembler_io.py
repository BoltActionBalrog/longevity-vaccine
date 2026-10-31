"""assemble_diplo.py's file I/O: a run never churns the line endings of the _fragment_diplo_*.yaml files or of
patches.yaml, an unchanged file is not rewritten at all, and --splice is idempotent (the second run is a byte-exact
no-op) and refuses to drop an entry another bake left inside the diplo_talk_scale markers.

Everything is written to tmp copies: the real work\\patches files are only READ (their bytes seed the copies).
The emit itself is pinned against the shipped patches.yaml in test_stale_sources.py (test_diplo_emit_*).
"""
from __future__ import annotations

import contextlib
import io
import os
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
PATCHES = ROOT / "patches"
sys.path.insert(0, str(SCRIPTS))
pytest.importorskip("keystone", reason="keystone absent")
pytest.importorskip("pefile", reason="pefile absent")

with contextlib.redirect_stdout(io.StringIO()):
    import assemble_diplo as AD  # noqa: E402

CRLF, LF = "\r\n", "\n"
OLD_NS = 1_600_000_000 * 10**9          # a fixed past mtime: a write moves it, a skipped write keeps it
SECTS = ("symbols", "cave", "groups", "sites")


@pytest.fixture(scope="module")
def emit(bak_path):
    with contextlib.redirect_stdout(io.StringIO()):
        _layout, _end, sym, ce, sites, group = AD.build_fragments()
    return sym, ce, sites, group


@pytest.fixture(scope="module")
def texts(emit):
    return AD.fragment_texts(*emit)


def _enc(text: str, eol: str) -> bytes:
    return text.replace("\n", eol).encode("utf-8")


def _put(p: pathlib.Path, data: bytes) -> None:
    p.write_bytes(data)
    os.utime(p, ns=(OLD_NS, OLD_NS))


def _eol_of(data: bytes) -> str:
    crlf, lf = data.count(b"\r\n"), data.count(b"\n")
    assert crlf in (0, lf), f"mixed EOLs: {crlf} CRLF of {lf} newlines"
    return CRLF if crlf else LF


# ---- fragments -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("layout", ["crlf", "lf", "mixed"])
def test_unchanged_fragments_are_not_rewritten(tmp_path, texts, layout):
    """Content == emit: no file is written (bytes AND mtime unchanged), whatever EOL each file has."""
    want = {}
    for i, (fn, body) in enumerate(sorted(texts.items())):
        eol = {"crlf": CRLF, "lf": LF}.get(layout, CRLF if i % 2 else LF)
        want[fn] = _enc(body, eol)
        _put(tmp_path / fn, want[fn])
    assert AD.write_fragments(str(tmp_path), texts) == []
    for fn, data in want.items():
        assert (tmp_path / fn).read_bytes() == data, f"{fn} rewritten"
        assert (tmp_path / fn).stat().st_mtime_ns == OLD_NS, f"{fn} touched"


@pytest.mark.parametrize("eol", [CRLF, LF], ids=["crlf", "lf"])
def test_changed_fragment_keeps_its_own_eol(tmp_path, texts, eol):
    for fn, body in texts.items():
        _put(tmp_path / fn, _enc(body + "  # stale entry\n", eol))
    assert sorted(AD.write_fragments(str(tmp_path), texts)) == sorted(texts)
    for fn, body in texts.items():
        assert (tmp_path / fn).read_bytes() == _enc(body, eol), fn


def test_new_fragment_is_written_lf(tmp_path, texts):
    assert sorted(AD.write_fragments(str(tmp_path), texts)) == sorted(texts)
    for fn, body in texts.items():
        assert (tmp_path / fn).read_bytes() == _enc(body, LF), fn


def test_a_full_run_leaves_the_committed_fragments_byte_identical(tmp_path, texts):
    """main() on byte copies of the four committed fragments (whatever EOL each has in this working copy) changes
    nothing -- the defect was every run rewriting all four as LF."""
    for fn in texts:
        _put(tmp_path / fn, (PATCHES / fn).read_bytes())
    with contextlib.redirect_stdout(io.StringIO()):
        assert AD.main(["--out-dir", str(tmp_path)]) == 0
    for fn in texts:
        assert (tmp_path / fn).read_bytes() == (PATCHES / fn).read_bytes(), f"{fn} changed"
        assert (tmp_path / fn).stat().st_mtime_ns == OLD_NS, f"{fn} rewritten with identical bytes"


# ---- --splice ------------------------------------------------------------------------------------------------------

def _block_re(sect: str):
    return re.compile(rf"^{re.escape(AD.MARK_B)} {sect}\n.*?\n{re.escape(AD.MARK_E)} {sect}\n", re.S | re.M)


@pytest.fixture
def yaml_copy(tmp_path, emit):
    """(path, eol) of a byte copy of the real patches.yaml, in its own EOL and converted to the other.  No entry
    another bake owns sits inside the diplo markers any more (Dialog_type16_calc.measure_native moved after the
    sites END marker, fix 8), so the copy splices as is."""
    def make(eol: str) -> pathlib.Path:
        txt = (PATCHES / "patches.yaml").read_bytes().decode("utf-8").replace("\r\n", "\n")
        p = tmp_path / f"patches_{'crlf' if eol == CRLF else 'lf'}.yaml"
        _put(p, _enc(txt, eol))
        return p
    return make


def test_splice_of_the_real_patches_yaml_is_a_byte_exact_noop(tmp_path, emit):
    """--splice on a byte copy of the shipped patches.yaml succeeds (no foreign entry in the markers) and writes
    nothing: the copy stays byte-identical to the real file, mtime included."""
    real = (PATCHES / "patches.yaml").read_bytes()
    p = tmp_path / "patches.yaml"
    _put(p, real)
    assert AD.splice(*emit, yaml_path=str(p)) is False
    assert p.read_bytes() == real and p.stat().st_mtime_ns == OLD_NS


@pytest.mark.parametrize("eol", [CRLF, LF], ids=["crlf", "lf"])
def test_splice_is_idempotent_and_keeps_the_eol(yaml_copy, emit, eol):
    p = yaml_copy(eol)
    AD.splice(*emit, yaml_path=str(p))
    once = p.read_bytes()
    assert _eol_of(once) == eol, "splice changed patches.yaml's line endings"
    os.utime(p, ns=(OLD_NS, OLD_NS))
    assert AD.splice(*emit, yaml_path=str(p)) is False, "second splice reported a change"
    assert p.read_bytes() == once, "second splice is not a byte-exact no-op"
    assert p.stat().st_mtime_ns == OLD_NS, "second splice rewrote identical bytes"
    txt = once.decode("utf-8").replace("\r\n", "\n")
    for sect in SECTS:
        assert txt.count(f"{AD.MARK_B} {sect}\n") == 1 and txt.count(f"{AD.MARK_E} {sect}\n") == 1, sect


def test_splice_inserts_missing_blocks_once(yaml_copy, emit):
    """Markers absent (first ever splice): inserted once, and a second splice replaces them in place -- no growth."""
    p = yaml_copy(CRLF)
    txt = p.read_bytes().decode("utf-8").replace("\r\n", "\n")
    for sect in SECTS:
        txt = _block_re(sect).sub("", txt)
        assert f"{AD.MARK_B} {sect}" not in txt
    _put(p, _enc(txt, CRLF))
    assert AD.splice(*emit, yaml_path=str(p)) is True
    once = p.read_bytes()
    assert _eol_of(once) == CRLF
    assert AD.splice(*emit, yaml_path=str(p)) is False and p.read_bytes() == once
    t1 = once.decode("utf-8").replace("\r\n", "\n")
    assert all(t1.count(f"{AD.MARK_B} {s}\n") == 1 for s in SECTS)
    assert AD.splice_text(t1, *emit) == t1


def test_splice_refuses_to_drop_a_foreign_entry(yaml_copy, emit):
    """An entry inside the diplo markers that this assembler does not emit (another bake's site, a hand edit) would
    be deleted by the in-place rewrite: the splice stops, writing nothing."""
    p = yaml_copy(CRLF)
    txt = p.read_bytes().decode("utf-8").replace("\r\n", "\n")
    end = f"{AD.MARK_E} sites\n"
    alien = ("  - id: Someone_else.site\n    status: confirmed\n    group: other\n    virtual_addr: 0x00400000\n"
             "    length: 1\n    original_bytes: \"90\"\n    new_bytes:      \"90\"\n    pattern: byte_patch\n")
    txt = txt.replace(end, alien + end)
    _put(p, _enc(txt, CRLF))
    before = p.read_bytes()
    with pytest.raises(SystemExit, match=r"Someone_else\.site"):
        AD.splice(*emit, yaml_path=str(p))
    assert p.read_bytes() == before and p.stat().st_mtime_ns == OLD_NS
