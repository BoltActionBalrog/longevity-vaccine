"""Differential: the BAKED thunk_scale_boxw v7 (+ its CALL-helper t_boxw_t1_term) must agree with the Python reference.

`scaling_laws.py` is the source of truth; `scaling_laws.js` is checked against it by
test_scaling_js_parity.py; the x86 that ships is checked here by emulating the REAL
assembled bytes (imported from scripts/assemble_scale_boxw.py) under Unicorn.

What it verifies, per g in [16,40] over both arms:
  * MIXED-SPACE arm (dlg_type in {1,2,8}, d5c!=0, no art): [esi+0x30bc] ==
    itemlist_box_width(itemlist_box_term_native(...), ...) — including both trim paths
    (init_w == -1 / >= 0); v7: the type-1 term is vanilla's [+0x5c] (xs + 2m - native gap),
    so the box content == thunk_list_fill_width's list window (type1_list_fill_width) at every g
  * every other regime (d5c==0, type not in {1,2}, type-1/2 WITH art): box == the v3
    formula, byte-for-byte semantics preserved (no regression on Quit/Difficulty/art)
  * at g <= 16 the box field is NOT written (native no-op)
  * ecx is untouched; ebx == padx on exit (the displaced `mov ebx,[esi+0x30e0]`
    contract the engine resumes with); control lands on RESUME 0x603D88
  * the yaml cave entry's bytes == the assembler's output (the content-desync class,
    [[feedback-yaml-thunk-content-desync]])

Skips (does not fail) if keystone/unicorn are absent.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from scaling_laws import (NATIVE_G, dialog_row_margin, itemlist_box_term_native, itemlist_box_width,  # noqa: E402
                          type1_list_fill_width)

keystone = pytest.importorskip("keystone", reason="keystone absent — asm parity unverified")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent — asm parity unverified")

from unicorn import UC_ARCH_X86, UC_MODE_32, Uc  # noqa: E402
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EBX,
    UC_X86_REG_ECX,
    UC_X86_REG_ESI,
    UC_X86_REG_ESP,
)


def _load_assembler():
    """Import the assembler as a module: its top-level run assembles + asserts fit."""
    spec = importlib.util.spec_from_file_location(
        "assemble_scale_boxw", SCRIPTS / "assemble_scale_boxw.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ASM = _load_assembler()
CODE = ASM.THUNK_VA            # 0xA16F00
G_ADDR = ASM.G_SCALE           # 0x668740 (real VA, mapped as scratch here)
RESUME = ASM.RESUME            # 0x603D88
BLOB = ASM.b
HELPER = ASM.HELPER_VA         # 0xA16294 t_boxw_t1_term
HBLOB = ASM.hb
CORE = ASM.CORE_VA             # 0xA162C1 t_t1_list_w (fix 18: the shared type-1 width core t_boxw_t1_term v2 calls)
CBLOB = ASM.cb

POPUP = 0x00300000             # scratch popup base (esi); fields reach +0x30e0
IVOBJ = 0x00380000             # scratch object behind [popup+0x21d0]
ART = 0x00390000               # scratch art object
STACK = 0x00200000
IV3 = 0xBA0                    # the real iv3 logged for these popups

PAGE = 0x1000
SENTINEL = 0x7CCCCCCC          # pre-set box value; must survive the native path


@pytest.fixture(scope="module")
def uc():
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    mu.mem_map(CODE & ~(PAGE - 1), 2 * PAGE)
    mu.mem_map(G_ADDR & ~(PAGE - 1), PAGE)
    mu.mem_map(POPUP, 0x4000)
    mu.mem_map(IVOBJ, PAGE)
    mu.mem_map(ART, PAGE)
    mu.mem_map(STACK, PAGE)
    mu.mem_write(CODE, BLOB)
    mu.mem_write(HELPER, HBLOB)
    mu.mem_write(CORE, CBLOB)
    return mu


def _w32(mu, addr, val):
    mu.mem_write(addr, int(val).to_bytes(4, "little", signed=True))


def _r32(mu, addr):
    return int.from_bytes(mu.mem_read(addr, 4), "little", signed=True)


def _run(mu, *, g, xs, d5c, dlg_type, init_w, padx, art_w=None, art_flag=0, pad_y=4,
         margin=0, gap=0, flags=0, fixed_h=0):
    _w32(mu, G_ADDR, g)
    dlg = POPUP + IV3 + 0x21d0                       # the Dialog: +0x20 flags, +0x30 fixed_h, +0x40 m, +0x44 gap
    _w32(mu, dlg + 0x20, flags)
    _w32(mu, dlg + 0x30, fixed_h)
    _w32(mu, dlg + 0x40, margin)
    _w32(mu, dlg + 0x44, gap)
    _w32(mu, POPUP + 0x21d0, IVOBJ)
    _w32(mu, IVOBJ + 8, IV3)
    _w32(mu, POPUP + IV3 + 0x222c, d5c)
    _w32(mu, POPUP + IV3 + 0x21fc, xs)
    _w32(mu, POPUP + 0x2350, dlg_type)
    _w32(mu, POPUP + 0x21cc, init_w)
    _w32(mu, POPUP + 0x30e0, padx)
    _w32(mu, POPUP + 0x30bc, SENTINEL)
    if art_w is None:
        _w32(mu, POPUP + 0x2144, 0)
    else:
        _w32(mu, POPUP + 0x2144, ART)
        _w32(mu, ART + 0x18, art_w)
    _w32(mu, POPUP + 0x2190, art_flag)
    _w32(mu, POPUP + 0x21c4, pad_y)

    sp = STACK + PAGE - 8
    mu.reg_write(UC_X86_REG_ESP, sp)
    mu.reg_write(UC_X86_REG_ESI, POPUP)
    mu.reg_write(UC_X86_REG_ECX, 0xCCCCCCCC)

    mu.emu_start(CODE, RESUME, count=128)   # thunk is a JMP-entered detour; it
    # push/rets to RESUME, where emulation stops before fetching.

    box = _r32(mu, POPUP + 0x30bc)
    ebx = mu.reg_read(UC_X86_REG_EBX)
    ecx = mu.reg_read(UC_X86_REG_ECX)
    return box, ebx, ecx


def _trim(init_w: int, padx: int) -> int:
    return 2 * padx if init_w == -1 else init_w + padx


def _v3_box(g, xs, d5c, init_w, padx, art_w=None, art_flag=0, pad_y=4) -> int:
    """The documented v3 law (unchanged arm)."""
    tw = d5c if d5c else xs
    cw = 0
    if art_w is not None:
        cw = art_w + padx + (3 * pad_y // 2 if art_flag else 0)
    return (max(cw, tw) + _trim(init_w, padx)) * g >> 4


ALL_G = list(range(NATIVE_G, 41))


@pytest.mark.parametrize("g", ALL_G)
@pytest.mark.parametrize("dlg_type", (1, 2, 8))
def test_mixed_space_arm_matches_the_law(uc, g: int, dlg_type: int):
    """The v5 arm (types 1 AND 2) == scaling_laws.itemlist_box_width, both trim paths."""
    for init_w, padx in ((0, 22), (-1, 11), (5, 10)):
        for xs, native_text in ((660, 356), (660, 900), (300, 356)):
            d5c = max(xs, native_text * g >> 4)   # what the scaled measure produces
            box, ebx, ecx = _run(uc, g=g, xs=xs, d5c=d5c, dlg_type=dlg_type,
                                 init_w=init_w, padx=padx)
            assert ecx == 0xCCCCCCCC, "ecx clobbered — engine register contract"
            assert ebx == padx, "displaced `mov ebx,[esi+0x30e0]` contract broken"
            if g <= NATIVE_G:
                assert box == SENTINEL, f"g={g} wrote the box on the native path"
            else:
                want = itemlist_box_width(itemlist_box_term_native(dlg_type, xs, 0, 0, 0, 0, g), d5c,
                                          _trim(init_w, padx), g)
                assert box == want, f"g={g} init_w={init_w}: asm {box} != law {want}"


def _dialogs(g):
    """Type-1 Dialog field sets: the popup lists (gap = thunk_rowgap's floor(3g/16) on the else-path, flags 0 or
    flags&1 without a height), a foreign gap, the fixed-height path (gap native 6) and fixed width (flags 3 / 2)."""
    for margin in (0, 3):
        yield dict(margin=margin, gap=dialog_row_margin(3, g), flags=0, fixed_h=0)
        yield dict(margin=margin, gap=dialog_row_margin(3, g), flags=1, fixed_h=0)
        yield dict(margin=margin, gap=5, flags=0, fixed_h=0)
        yield dict(margin=margin, gap=6, flags=1, fixed_h=281)
        yield dict(margin=margin, gap=6, flags=3, fixed_h=281)
        yield dict(margin=margin, gap=dialog_row_margin(3, g), flags=2, fixed_h=0)


@pytest.mark.parametrize("g", ALL_G)
@pytest.mark.parametrize("dlg_type", (1, 2, 8))
def test_mixed_space_term_matches_the_law(uc, g: int, dlg_type: int):
    """v7: the arm's native term is itemlist_box_term_native (t_boxw_t1_term): type 1 = vanilla's [+0x5c] re-formed
    from the native inputs; types 2 / 8 = xs (v6), whatever the Dialog fields hold."""
    for d in _dialogs(g):
        for xs, d5c in ((660, 890), (660, 653), (457, 451), (440, 300), (0, 300)):
            for init_w, padx in ((-1, 0), (0, 22)):
                box, ebx, ecx = _run(uc, g=g, xs=xs, d5c=d5c, dlg_type=dlg_type, init_w=init_w, padx=padx, **d)
                assert ecx == 0xCCCCCCCC and ebx == padx
                if g <= NATIVE_G:
                    assert box == SENTINEL
                    continue
                term = itemlist_box_term_native(dlg_type, xs, d["margin"], d["gap"], d["flags"], d["fixed_h"], g)
                assert box == itemlist_box_width(term, d5c, _trim(init_w, padx), g), (g, dlg_type, d, xs, d5c)
                if dlg_type != 1:
                    assert term == xs


CENSUS_D5C = (653, 890, 977, 1642)       # d5c as the calc leaves it: xs - s(gap), a device measure, the list's


@pytest.mark.parametrize("g", range(17, 41))
def test_type1_box_content_is_the_list_window(uc, g: int):
    """THE fix-14b property: a popup type-1 list's box content (box - s(trim)) == the list window thunk_list_fill_width
    builds (type1_list_fill_width w = floor(vanilla [+0x5c] * g/16)) -- vanilla builds both from one [+0x5c].  The
    fix-14 state (box s(660) around a list of s(657)) fails at every g where the two floors differ."""
    gap = dialog_row_margin(3, g)
    for flags in (0, 1):
        for d5c in CENSUS_D5C:
            d5c_dev = min(d5c, (657 * g) >> 4)                  # the calc's measure never exceeds vanilla x g/16
            for init_w, padx in ((-1, 0), (0, 22)):
                box, _, _ = _run(uc, g=g, xs=660, d5c=d5c_dev, dlg_type=1, init_w=init_w, padx=padx, margin=0,
                                 gap=gap, flags=flags, fixed_h=0)
                list_w = type1_list_fill_width(660, 0, 1, gap, flags, 0, 18, g)[0]
                assert box - ((_trim(init_w, padx) * g) >> 4) == list_w == (657 * g) >> 4, (g, flags, d5c_dev)


def test_customize_rules_golden_vector(uc):
    """The measured 4K defects, replayed against the shipping bytes: Customize Game Rules (xs 660, gap field
    fl(3*40/16) = 7, the calc's device measure 890, init_w -1, padx 0).  v3 2280 (d5c double-scaled), v4..v6 1650
    (s(xs): 8 px wider than the fix-14 list), v7 1642 == the list window fl(657 * 2.5)."""
    box, _, _ = _run(uc, g=40, xs=660, d5c=890, dlg_type=1, init_w=-1, padx=0, gap=7)
    assert box == 1642
    box, _, _ = _run(uc, g=40, xs=660, d5c=890, dlg_type=1, init_w=0, padx=22, gap=7)
    assert box == 1642 + 55    # the hook_rulesboxw trim form (s(22) = 55): v4..v6 1705


def test_faction_scenario_golden_vector(uc):
    """The scenario #FACTION 4K defect (frida_faction_scenario_crash.log:311):
    type-2 listbox, d5c pre-populated DEVICE-space by thunk_lbcalc_minw
    (1312 = 525*40>>4), xs=525 (=350 x the engine's own >1023px 3/2 bump),
    init_w=-1, padx=0. v4 shipped 1312*40>>4 = 3280 (near-full 4K width,
    position clamped to x=0); faithful is 1312."""
    box, _, _ = _run(uc, g=40, xs=525, d5c=1312, dlg_type=2, init_w=-1, padx=0)
    assert box == 1312         # was 3280 under v4


@pytest.mark.parametrize("g", ALL_G)
def test_other_regimes_keep_v3_semantics(uc, g: int):
    """Quit (type 16), Difficulty (type -1, d5c==0), and type-1/2 WITH art must
    all come out of the v3 formula — byte-preserved body, no regression."""
    cases = [
        dict(xs=980, d5c=977, dlg_type=16, init_w=-1, padx=11),           # Quit-like
        dict(xs=807, d5c=0, dlg_type=-1, init_w=0, padx=22),              # Difficulty-like
        dict(xs=660, d5c=890, dlg_type=1, init_w=0, padx=22,
             art_w=120, art_flag=1),                                      # type-1 + art
        dict(xs=525, d5c=1312, dlg_type=2, init_w=-1, padx=0,
             art_w=120, art_flag=1),                                      # type-2 + art
        dict(xs=700, d5c=0, dlg_type=-1, init_w=-1, padx=15,
             art_w=200, art_flag=0),                                      # art popup
        dict(xs=525, d5c=1312, dlg_type=0, init_w=-1, padx=0),            # gate edge: 0
        dict(xs=525, d5c=1312, dlg_type=3, init_w=-1, padx=0),            # gate edge: 3
        dict(xs=600, d5c=1591, dlg_type=7, init_w=-1, padx=20),           # gate edge: 7
        dict(xs=600, d5c=1591, dlg_type=9, init_w=-1, padx=20),           # gate edge: 9
        dict(xs=600, d5c=1591, dlg_type=8, init_w=-1, padx=20,
             art_w=120, art_flag=1),                                      # type-8 + art
    ]
    for c in cases:
        box, ebx, _ = _run(uc, g=g, **c)
        assert ebx == c["padx"]
        ref = {k: v for k, v in c.items() if k != "dlg_type"}
        if g <= NATIVE_G:
            assert box == SENTINEL
        else:
            assert box == _v3_box(g, **ref), f"g={g} case={c}"


def test_unit_stack_picker_golden_vector(uc):
    """v6 (2026-10-11, user 4K shot 225617): a 16-unit stack = a 2-column type-8 OptionList; d5c = max(native xs
    600, device content 2*797-3 = 1591).  v3 scaled the whole max: (1591+40)*40>>4 = 4077 (box wider than the
    screen, centred off both edges).  Law itemlist_box_width: max(s(600), 1591) + s(40) = 1691."""
    box, _, _ = _run(uc, g=40, xs=600, d5c=1591, dlg_type=8, init_w=-1, padx=20)
    assert box == 1691
    box, _, _ = _run(uc, g=40, xs=600, d5c=600, dlg_type=8, init_w=-1, padx=20)
    assert box == 1600                                                     # short single column: unchanged


def test_native_path_writes_nothing_and_restores_ebx(uc):
    box, ebx, ecx = _run(uc, g=16, xs=660, d5c=890, dlg_type=1, init_w=0, padx=22)
    assert box == SENTINEL
    assert ebx == 22
    assert ecx == 0xCCCCCCCC


def test_yaml_bytes_match_the_assembler():
    """The cave CONTENT entry is a separate yaml blob — verify it IS these bytes
    (placeholders resolved), so the ledger cannot desync from the source."""
    yaml_text = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    for name, off, va, blob in (("thunk_scale_boxw", "0xAF00", CODE, BLOB), ("t_boxw_t1_term", "0xA294", HELPER, HBLOB),
                                ("t_t1_list_w", "0xA2C1", CORE, CBLOB)):
        m = re.search(r"- id: %s\s+offset: %s\s+bytes: \"([^\"]+)\"" % (name, off), yaml_text)
        assert m, f"{name} content entry not found at offset {off}"
        toks = m.group(1).replace(
            "{abs32:g_popup_scale_num}",
            " ".join(f"{b:02X}" for b in int(G_ADDR).to_bytes(4, "little"))).split()
        for ph, tgt in (("{rel32:t_boxw_t1_term}", HELPER), ("{rel32:t_t1_list_w}", CORE)):
            if ph in toks:
                at = toks.index(ph)
                rel = (tgt - (va + at + 4)) & 0xFFFFFFFF
                toks[at:at + 1] = [f"{b:02X}" for b in rel.to_bytes(4, "little")]
        got = bytes(int(x, 16) for x in toks)
        assert got == blob, f"yaml cave bytes of {name} != assembler output — regenerate one of them"
