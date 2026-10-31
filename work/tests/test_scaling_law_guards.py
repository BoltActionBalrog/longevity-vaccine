"""Tripwires that make the scaling laws hard to regress ACCIDENTALLY.

These do not test arithmetic — `test_scaling_laws.py` does that. These test the
*process*: that the laws still have a single source of truth, that the ports
still point at it, and that the documentation a future session reads has not
drifted away from the code it describes.

They exist because the laws are counter-intuitive (a stroke width that must NOT
be derived from the thing it strokes; a chrome edge that must NOT be scaled),
and the natural "cleanup" of each one silently breaks a resolution nobody is
looking at. Prose in a skill file cannot enforce that. A failing test can.

Each assertion names the defect it prevents.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent          # work/
SCRIPTS = ROOT / "scripts"
SKILLS = ROOT.parent / ".claude" / "skills"


def skill_file(name: str) -> Path:
    """The skill as this tree carries it: `.claude/skills/<name>/SKILL.md` in the private
    checkout, `docs/skills/<name>.md` in the public source export."""
    private = SKILLS / name / "SKILL.md"
    return private if private.exists() else ROOT.parent / "docs" / "skills" / f"{name}.md"

sys.path.insert(0, str(SCRIPTS))


# --------------------------------------------------------------------------
# The source of truth must exist, and the laws must be reachable from it.
# --------------------------------------------------------------------------

def test_reference_module_exports_every_law():
    """`scaling_laws.py` is the single source of truth. If a law is deleted or
    renamed, every port silently keeps its own private copy — which is exactly
    how the stroke-width law diverged per-element. Fail loudly instead."""
    import scaling_laws as sl

    for name in ("half_down", "scale_px", "stroke_width", "option_row_gap",
                 "cum", "distribute", "row_positions", "band_widths",
                 "axis_map", "ring_bottom"):
        assert hasattr(sl, name), f"scaling_laws.{name} is gone — ports will drift"


def test_stroke_width_takes_only_g():
    """LAW 4 tripwire. `stroke_width` must depend on the LEVER alone.

    If someone 'improves' it to accept the frame's span or src/dst ratio, two
    frames on one screen get different strokes (the exact defect this workstream
    cured). The signature is the guard.
    """
    import inspect

    import scaling_laws as sl

    params = list(inspect.signature(sl.stroke_width).parameters)
    assert params == ["g"], (
        "stroke_width must take g and nothing else — deriving K from an "
        "element's own ratio makes strokes disagree across a screen"
    )


# --------------------------------------------------------------------------
# The invariant that outranks everything: g == 16 is vanilla.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("n", [3, 6, 44, 61])
def test_native_g_is_the_identity_for_every_band_depth(n: int):
    """CLAUDE.md's hard invariant, restated as a guard. At 1024x768 the patched
    exe must draw byte-identically to vanilla. Any law that fails this is wrong
    regardless of how good 4K looks."""
    import scaling_laws as sl

    span = 8 * n
    assert sl.axis_map(span, span, n, sl.NATIVE_G) == list(range(span))
    assert sl.band_widths(n, n, sl.stroke_width(sl.NATIVE_G)) == [1] * n
    assert sl.row_positions(100, 19, 7, sl.NATIVE_G) == [100 + 19 * i for i in range(7)]


def test_no_resolution_gated_constants_in_the_reference():
    """A resolution-gated stopgap is never 'done' (CLAUDE.md). The reference must
    not contain screen-dimension literals — levers only."""
    src = (SCRIPTS / "scaling_laws.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    )
    # strip docstrings crudely: they are the only triple-quoted regions
    code = re.sub(r'""".*?"""', "", code, flags=re.S)
    for banned in ("1920", "1080", "1600", "1200", "3840", "2160", "1024", "768"):
        assert banned not in code, (
            f"screen literal {banned} in scaling_laws.py — gate on g "
            "(g_popup_scale_num), never a resolution. See feedback-loores-gate-on-g"
        )
    # ...nor their HEX spellings (the asm's own form: 0x400 / 0x3FF is how a width gate is written). The only lines
    # allowed to carry one are the definitions of these NAMED native-screen constants, used to DERIVE g or to place
    # a native layout -- never as a gate -- and OPENING_ART_B_*, the engine's OWN asset choice (change_opening's
    # caller picks the 800x600 backdrop on ScreenWidth == 0x320; the decoration follows that art, not a lever).
    allowed_defs = re.compile(r"^\s*(SCALE_UNIFORM_BASE_W|MON_NATIVE_W|DW_W|OPENING_ART_B_W)\b[\w, ]*=")
    hexes = {n: f"{n:#x}" for n in (1920, 1080, 1600, 1200, 3840, 2160, 1024, 768, 1023, 1025, 800, 600)}
    for line in code.splitlines():
        body = line.split("#", 1)[0]
        for n, h in hexes.items():
            if re.search(rf"\b{h}\b", body, re.I) and not allowed_defs.match(body):
                pytest.fail(f"screen literal {h} (= {n}) in scaling_laws.py: {line.strip()!r} -- name it as a "
                            "native-screen constant (SCALE_UNIFORM_BASE_*, MON_NATIVE_*, DW_*) or gate on g")


# --------------------------------------------------------------------------
# The ports must still point at the reference.
# --------------------------------------------------------------------------

def test_frida_frame9_port_documents_the_epilogue_law():
    """LAW 3 tripwire. `hook_frame9.js` replaces the four frame renderers, so it
    MUST replicate thunk_frame_enlarge's tail (g_fe_* stash -> fe_pair_remap ->
    consume g_fc_exact) or fractional-g dither banding returns.

    This is the single most costly regression in this workstream (it shipped,
    the user saw it, and it was misdiagnosed twice as a corner problem).
    """
    js = SCRIPTS / "hook_frame9.js"
    if not js.exists():
        pytest.skip("hook_frame9.js not present — the baked thunks carry the tail; check them "
                    "instead")
    src = js.read_text(encoding="utf-8")
    for token in ("fe_pair_remap", "G_FE_SRC", "G_FE_DST", "G_FC_EXACT"):
        assert token in src, (
            f"hook_frame9.js no longer references {token}: the frame_enlarge "
            "epilogue is not being replicated -> dither banding at g=22/25"
        )


def test_golden_vectors_exist_and_pin_the_approved_look():
    """The baked asm will be verified against these integers, not against the JS
    prototype. Losing the file means losing the only objective record of what the
    user actually signed off on."""
    import json

    path = Path(__file__).resolve().parent / "golden_scaling_vectors.json"
    assert path.exists(), "run: py work/scripts/gen_scaling_vectors.py --write"
    v = json.loads(path.read_text(encoding="utf-8"))
    assert v["stroke_width"]["40"] == 2, "the approved 4K stroke is 2px, not 3"
    assert v["stroke_width"]["16"] == 1, "native stroke must stay 1px"


# --------------------------------------------------------------------------
# The prose a future session reads must still match the code.
# --------------------------------------------------------------------------

def test_claude_md_names_the_reference_module_and_the_sweep():
    """CLAUDE.md is the ONLY document guaranteed to be in context every session.

    A skill gets skimmed; a test gets run only if you think to run it. The invariant
    that `scaling_laws.py` is the source of truth, and that the sweep is mandatory,
    has to live here or a fresh session will re-derive the laws from prose — badly.
    """
    p = ROOT.parent / "CLAUDE.md"
    if not p.exists() and (ROOT.parent / "docs" / "skills").is_dir():
        pytest.skip("public source export: CLAUDE.md is private (the skills carry the laws)")
    assert p.exists(), "CLAUDE.md missing"
    text = p.read_text(encoding="utf-8")
    assert "scaling_laws.py" in text, "CLAUDE.md must name the reference module"
    assert "pytest -k scaling" in text, "CLAUDE.md must name the mandatory sweep"
    assert "WHY.md" in text, "CLAUDE.md must point at the rejected-alternatives record"


def test_why_md_records_the_rejected_alternatives():
    """work/WHY.md is the record of what was TRIED AND ABANDONED.

    Records of what we did are everywhere; records of what failed exist nowhere, so a
    dead end that looks obviously correct gets re-proposed every few months. Each entry
    must carry a failure mechanism, not just a verdict.
    """
    p = ROOT / "WHY.md"
    assert p.exists(), "work/WHY.md missing — see CLAUDE.md"
    text = p.read_text(encoding="utf-8")
    for topic in ("lattice snap", "dst/src ratio", "half UP",
                  "floor(j·src/dst)", "compensation"):
        assert topic.lower() in text.lower(), f"WHY.md no longer records: {topic}"
    assert text.lower().count("why it fails") >= 5, \
        "every WHY.md entry needs a concrete failure mechanism, not just a verdict"


def test_pre_commit_hook_exists_and_is_wired():
    """The mechanical backstop. Prose can be skimmed; a failing commit cannot."""
    hook = ROOT.parent / ".githooks" / "pre-commit"
    assert hook.exists(), "missing .githooks/pre-commit"
    text = hook.read_text(encoding="utf-8")
    assert "test_scaling_law_guards.py" in text, "hook must run the guards"
    assert "-k scaling" in text, "hook must run the full sweep when scaling files change"
    assert "WHY.md" in text, "hook's failure message must point at WHY.md"


def test_skills_point_at_the_reference_module():
    """A skill that describes the laws without naming the module lets a reader
    reimplement them from the prose — badly. Both frame/layout skills must send
    the reader to scaling_laws.py and its sweep."""
    for skill in ("scaling-frames", "scaling-layout"):
        p = skill_file(skill)
        assert p.exists(), f"missing skill: {skill}"
        text = p.read_text(encoding="utf-8")
        assert "scaling_laws.py" in text, f"{skill} must name the reference module"
        assert "test_scaling_laws.py" in text, f"{skill} must name the sweep"
