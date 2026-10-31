"""The rail / scrollbar family's shipped bytes ARE scripts/assemble_rail_scrollbar.py's output.

assemble_rail_scrollbar.main() prints one `bytes:` template per thunk it owns (the rail strip bake / mark / wall /
walloff / nncol / sx, the bar fit, the slide-out hstep / capw, the gates, sb_arrowfit, sb_restripe, ...); the yaml
entry of each must be that template token for token, at the offset the script places it.  The emulation tests run the
ASSEMBLER's bytes (test_rail_asm_parity, test_rail_sbstrip_abut_asm via the build), so without this pin a hand-edited
yaml entry and a stale script could disagree silently.  Read-only: nothing is written.
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("keystone", reason="keystone absent")

import apply_patches as ap  # noqa: E402
import assemble_rail_scrollbar as A  # noqa: E402

EMIT_RE = re.compile(r'^(\S+)  (\d+) bytes @ pcave2\+(0x[0-9a-f]+)[^\n]*\n\s+bytes: "([^"]*)"', re.M)


def _emitted():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert A.main() == 0
    return {m.group(1): (int(m.group(3), 16), int(m.group(2)), m.group(4).split()) for m in EMIT_RE.finditer(buf.getvalue())}


EMITTED = _emitted()


def _yaml():
    _s, _g, caves, _sym = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    cave = next(c for c in caves if c["id"] == "pcave2")
    return {e["id"]: (int(e["offset"]), str(e["bytes"]).split()) for e in cave["contents"]}


YAML = _yaml()
# the family the fix 4f2 verifier named (sizes as baked) -- must all be emitted, at these lengths (sbfit 125 -> 105:
# W3B v5, the bar from t_rsb_bar)
CORE = {"thunk_rail_bake": 326, "thunk_rail_sbfit": 105, "thunk_railout_hstep": 82, "thunk_rail_wall": 120,
        "thunk_rail_walloff": 38, "thunk_rail_mark": 78, "thunk_rail_nncol": 62, "thunk_rail_sx": 35,
        "thunk_railout_capw": 62}


def test_the_family_is_emitted():
    assert set(CORE) <= set(EMITTED)
    for name, n in CORE.items():
        assert EMITTED[name][1] == n, (name, EMITTED[name][1])
    assert len(EMITTED) >= 19


@pytest.mark.parametrize("name", sorted(EMITTED))
def test_yaml_bytes_equal_the_assembler(name):
    off, n, toks = EMITTED[name]
    assert name in YAML, name
    yoff, ytoks = YAML[name]
    assert yoff == off, (name, hex(yoff), hex(off))
    assert ytoks == toks, (name, next((i, a, b) for i, (a, b) in enumerate(zip(ytoks, toks)) if a != b)
                           if len(ytoks) == len(toks) else (len(ytoks), len(toks)))
