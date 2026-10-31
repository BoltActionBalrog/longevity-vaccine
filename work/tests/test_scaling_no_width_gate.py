"""The lo-res gate is g, never the screen width: no cave thunk gates on `ScreenWidth` vs 0x3FF / 0x400.

Law (CLAUDE.md; memory feedback_loores_gate_on_g): a scaling thunk's native no-op is `g_popup_scale_num <= 16`.  g is
clamp(floor(16 * min(W/1024, H/768)), 16, 40) (scaling_laws.popup_g), so every 16:9 screen up to 1366 wide runs at
g = 16 with W > 1024: a `cmp [ScreenWidth], 0x400` gate scales there (fix 10, 2026-10-18: the faction picker title /
button font, its connector corners and fan rows, the main-menu Load/Save window position), and `cmp [ScreenWidth],
0x3FF` (thunk_list_fill_width, thunk_wrap_budget) even fired at 1024x768 itself.

Two guards over the REAL patches.yaml bytes:

* STATIC: no cave content compares ScreenWidth or ScreenHeight with ANY immediate -- `cmp dword [SW|SH], imm` or a
  register loaded from [SW|SH] and compared within the next few instructions (capstone), plus the canonical byte
  forms on the template text (robust to a linear-disassembly desync).  Deliberate exceptions, pinned by owner and
  offset: the three
  SW == 800 tests that replay vanilla's own 800-wide branch (t_slide_rail_a / t_slide_rail_a2: the slide windows'
  rail row; thunk_credits_subwin: the credits sub-window), which select a layout, not a scale, and deco_art's
  SW == 800 (the engine's own choice of the 800x600 opening backdrop, whose per-axis map the planet-customisation
  decoration follows: scaling_laws.opening_art; fix 15).  (thunk_pf_union_align's SW > 0x3FF native-fix arm, the
  former exception at +0x1c9, was removed by fix 16: its "vanilla regime" was our own g=16 list widening.)
* GATE PINS: each fix-10 re-gated thunk carries `cmp dword [g_popup_scale_num], 0x10` (imm32 form) followed by its
  recorded jcc, so a jle -> jl / jg -> jge / 0x10 -> 0x11 slip is caught statically; and g = 17 behaves differently
  from g = 16 (the first scaled g takes the scaled path).
* BEHAVIOUR (Unicorn): each fix-10 re-gated thunk at g = 16 does the SAME thing on an 800 / 1024 / 1366 / 3840-wide
  screen -- first exit from the cave code, every register, the stack (above and below esp) and every byte written.

Mutants restore the width gate in one thunk of each family (faction, connector, file dialog, popup list) and must be
killed by both guards.  Skips (does not fail) if unicorn / capstone are absent.
"""
from __future__ import annotations

import hashlib
import re
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import apply_patches as ap  # noqa: E402

capstone = pytest.importorskip("capstone", reason="capstone absent")
unicorn = pytest.importorskip("unicorn", reason="unicorn absent")
from unicorn import (  # noqa: E402
    UC_ARCH_X86, UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED, UC_MODE_32, Uc, UcError)
from unicorn.x86_const import (  # noqa: E402
    UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX, UC_X86_REG_EIP,
    UC_X86_REG_ESI, UC_X86_REG_ESP)


def _load():
    _s, _g, caves, symbols = ap.load_patches(Path(ap.DEFAULT_PATCHES))
    sym = dict(ap.build_symbol_table(symbols, caves))
    tmpl = {}
    for c in caves:
        for e in c.get("contents") or []:
            tmpl[e["id"]] = (int(c["virtual_addr"]) + int(e["offset"]), " ".join(str(e["bytes"]).split()))
    spans = [(int(c["virtual_addr"]), int(c["virtual_addr"]) + int(c["length"])) for c in caves]
    return sym, tmpl, spans


SYM, TMPL, CAVE_SPANS = _load()
SW, SH, G = SYM["ScreenWidth"], SYM["ScreenHeight"], SYM["g_popup_scale_num"]
WIDTH_LITERALS = (0x3FF, 0x400, 0x401)          # the fix-10 forms (the mutants below restore them)


def resolve(name: str, template: str | None = None) -> bytes:
    va, t = TMPL[name]
    return bytes(ap.ByteTemplate(template or t).resolve(va, SYM))


# ---- static --------------------------------------------------------------------------------------------------------
_SW_TOKEN = r"(?:\{abs32:ScreenWidth\}|1C 7B 9B 00|\{abs32:ScreenHeight\}|20 7B 9B 00)"
_HEX = r"[0-9A-F]{2}"
CANONICAL = re.compile(r"(?:81 3D " + _SW_TOKEN + " " + " ".join([_HEX] * 4) + "|83 3D " + _SW_TOKEN + " " + _HEX + ")")
_MD = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
_MD.detail = True


def width_gates(name: str, template: str | None = None) -> list:
    """Offsets of every ScreenWidth / ScreenHeight vs immediate comparison in cave content `name`."""
    va, t = TMPL[name]
    t = template or t
    code = resolve(name, t)
    hits = set()
    loaded = {}                                        # reg -> instruction index it was loaded from [SW]
    ins = list(_MD.disasm(code, va))
    for k, i in enumerate(ins):
        ops = i.operands
        if i.mnemonic == "cmp" and len(ops) == 2 and ops[1].type == capstone.x86.X86_OP_IMM:
            a = ops[0]
            if a.type == capstone.x86.X86_OP_MEM and a.mem.base == 0 and a.mem.index == 0 \
                    and (a.mem.disp & 0xFFFFFFFF) in (SW, SH):
                hits.add(i.address - va)
            elif a.type == capstone.x86.X86_OP_REG and k - loaded.get(a.reg, -99) <= 4:
                hits.add(i.address - va)
        if i.mnemonic == "mov" and len(ops) == 2 and ops[0].type == capstone.x86.X86_OP_REG:
            b = ops[1]
            if b.type == capstone.x86.X86_OP_MEM and b.mem.base == 0 and b.mem.index == 0 \
                    and (b.mem.disp & 0xFFFFFFFF) in (SW, SH):
                loaded[ops[0].reg] = k
            else:
                loaded.pop(ops[0].reg, None)
    if CANONICAL.search(t):
        # the canonical form must also be seen by the disassembly (else the linear sweep desynced over it)
        for m in CANONICAL.finditer(t):
            hits.add(len(ap.ByteTemplate(t[:m.start()].strip()).resolve(va, SYM)) if m.start() else 0)
    return sorted(hits)


# The deliberate screen-size comparisons: regime / layout selectors, not scaling gates (see the module docstring).
ALLOWED = {"t_slide_rail_a": [0x3A], "t_slide_rail_a2": [0x33],   # mov reg, [SW]; cmp reg, 0x320: vanilla's 800 arm
           "thunk_credits_subwin": [0x22],                        # cmp [SW], 0x320: the credits sub-window's 800 layout
           "deco_art": [0x0A]}                                    # cmp [SW], 0x320: change_opening's 800x600 backdrop
                                                                  # (the art the decoration follows; fix 15)


def all_width_gates(templates: dict | None = None) -> dict:
    out = {}
    for name in TMPL:
        t = (templates or {}).get(name)
        hits = width_gates(name, t)
        if hits:
            out[name] = hits
    return out


def test_no_cave_gates_on_the_screen_width():
    assert all_width_gates() == ALLOWED


# ---- behaviour -----------------------------------------------------------------------------------------------------
# the fix-10 re-gated thunks (24 x `cmp [SW], 0x400` + 2 x `cmp [SW], 0x3FF`)
REGATED = ("thunk_factionwin_graphicwin", "thunk_factionwin_button", "thunk_factionwin_list",
           "thunk_factionwin_quoteloc", "thunk_factionwin_framecover", "thunk_factionwin_font",
           "thunk_factionwin_pitch", "thunk_faction_rowgap", "thunk_faction_droppos", "thunk_rebuild_pitch",
           "thunk_rebuild_gap", "thunk_filedlg_graphicwin", "thunk_filedlg_rects", "thunk_filedlg_titlefont",
           "thunk_filedlg_dlgfont", "thunk_filedlg_editfont", "thunk_conn_vline", "thunk_conn_hline",
           "thunk_conn_pixel", "thunk_conn_chevron", "thunk_conn_diag", "thunk_conn_fan_vline", "thunk_conn_fan_row",
           "thunk_conn_fan_tick", "thunk_wrap_budget", "thunk_list_fill_width")
SCREENS = ((800, 600), (1024, 768), (1366, 768), (3840, 2160))     # all at g = 16 here (the gate must not care)
PAGE = 0x1000
FILL = struct.pack("<I", 0x100) * (PAGE // 4)    # every unknown dword: a small count > 1, a mapped pointer, a width
STACK = 0x00200000
SENT = 0x0DEAD000                                # the caller's return address (unmapped: a fetch there is the exit)
REG_INIT = {UC_X86_REG_EAX: 0x00300000, UC_X86_REG_EBX: 0x00310000, UC_X86_REG_ECX: 0x00320000,
            UC_X86_REG_EDX: 0x00330000, UC_X86_REG_ESI: 0x00340000, UC_X86_REG_EDI: 0x00350000,
            UC_X86_REG_EBP: 0x00360000}
ARGS = tuple(0x00380000 + 0x100 * i for i in range(10))       # pointer-shaped stack args (deref'able, distinct)


def _code_with(overrides: dict | None) -> dict:
    code = {n: resolve(n) for n in TMPL}
    for n, t in (overrides or {}).items():
        code[n] = resolve(n, t)
    return code


def run_at(code: dict, entry: str, sw: int, sh: int, g: int = 16):
    """Enter `entry` with the same frame and memory on a sw x sh screen; run to the first fetch outside the caves.
    -> (exit eip, registers, stack window, digest of every byte of mapped data)."""
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    mapped = set()

    def map_page(p, fill=FILL):
        if p not in mapped:
            mu.mem_map(p, PAGE)
            mu.mem_write(p, fill)
            mapped.add(p)

    for lo, hi in CAVE_SPANS:
        for p in range(lo & ~0xFFF, (hi + 0xFFF) & ~0xFFF, PAGE):
            map_page(p, bytes(PAGE))
    for n, (va, _t) in TMPL.items():
        mu.mem_write(va, code[n])
    map_page(SW & ~0xFFF)
    map_page(G & ~0xFFF, bytes(PAGE))
    mu.mem_write(SW, struct.pack("<ii", sw, sh))
    mu.mem_write(G, struct.pack("<i", g))
    mu.mem_write(SYM["g_faction_build_active"], struct.pack("<I", 1))   # thunk_factionwin_button's pre-gate: reach g's
    for p in range((STACK - 0x8000) & ~0xFFF, STACK + 0x2000, PAGE):
        map_page(p, bytes(PAGE))
    mu.mem_write(STACK, struct.pack("<I", SENT) + b"".join(struct.pack("<I", a) for a in ARGS))

    def on_unmapped(m, _acc, addr, size, _v, _u):
        for p in {addr & ~0xFFF, (addr + size - 1) & ~0xFFF}:
            map_page(p)
        return True
    mu.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED, on_unmapped)
    for r, v in REG_INIT.items():
        mu.reg_write(r, v)
    mu.reg_write(UC_X86_REG_ESP, STACK)
    try:
        mu.emu_start(TMPL[entry][0], SENT, count=200_000)
    except UcError:
        pass
    eip = mu.reg_read(UC_X86_REG_EIP)
    assert not any(lo <= eip < hi for lo, hi in CAVE_SPANS), (entry, hex(eip), "still in the caves")
    regs = tuple(mu.reg_read(r) for r in (*REG_INIT, UC_X86_REG_ESP))
    esp = mu.reg_read(UC_X86_REG_ESP)
    stack = bytes(mu.mem_read(STACK - 0x100, 0x100 + 4 * (len(ARGS) + 1)))
    h = hashlib.sha256()
    for p in sorted(mapped):
        data = bytearray(mu.mem_read(p, PAGE))
        if p == SW & ~0xFFF:
            data[SW - p:SW - p + 8] = bytes(8)                    # the screen size itself is the input under test
        if p == G & ~0xFFF:
            data[G - p:G - p + 4] = bytes(4)                      # so is g: compare what the code DID with it
        h.update(bytes(data))
    return eip, regs, esp, stack, h.hexdigest()


def g16_width_dependence(code: dict, names=REGATED) -> list:
    """Every re-gated thunk whose g = 16 behaviour depends on the screen size."""
    bad = []
    for n in names:
        outs = {s: run_at(code, n, *s) for s in SCREENS}
        if len(set(outs.values())) != 1:
            bad.append(n)
    return bad


LIVE = _code_with(None)


@pytest.mark.parametrize("name", REGATED)
def test_g16_is_the_same_on_every_screen_width(name):
    assert g16_width_dependence(LIVE, (name,)) == []


def test_regated_thunks_still_scale_above_g16():
    """g > 16 takes the scaled path (the exit differs from g = 16's on the same screen) -- the gate is live."""
    same = [n for n in REGATED if run_at(LIVE, n, 3840, 2160, 40)[:3] == run_at(LIVE, n, 3840, 2160, 16)[:3]
            and run_at(LIVE, n, 3840, 2160, 40)[4] == run_at(LIVE, n, 3840, 2160, 16)[4]]
    assert same == []


# each re-gated thunk's lo-res gate and the jcc right behind it, as shipped (7E jle / 0F 8E jle rel32 / 7F jg)
GATE_JCC = {"thunk_factionwin_graphicwin": "7E", "thunk_factionwin_button": "7E", "thunk_factionwin_list": "7E",
            "thunk_factionwin_quoteloc": "7E", "thunk_factionwin_framecover": "0F 8E", "thunk_factionwin_font": "7E",
            "thunk_factionwin_pitch": "7E", "thunk_faction_rowgap": "7E", "thunk_faction_droppos": "7E",
            "thunk_rebuild_pitch": "7E", "thunk_rebuild_gap": "7E",
            "thunk_filedlg_graphicwin": "7E",    # v3 (fix 19, 100 B): one anchored arm, the tail within a short jle (v2: 0F 8E)
            "thunk_filedlg_rects": "7E", "thunk_filedlg_titlefont": "7E", "thunk_filedlg_dlgfont": "7E",
            "thunk_filedlg_editfont": "7E", "thunk_conn_vline": "7F", "thunk_conn_hline": "7F",
            "thunk_conn_pixel": "7F", "thunk_conn_chevron": "7F", "thunk_conn_diag": "7F", "thunk_conn_fan_vline": "7F",
            "thunk_conn_fan_row": "7F", "thunk_conn_fan_tick": "7F", "thunk_wrap_budget": "7E",
            "thunk_list_fill_width": "7E"}     # v4 (fix 18, 128 B): the tail is within a short jle (v3: 0F 8E)


def gate_pin_failures(templates: dict | None = None) -> list:
    """Re-gated thunks whose template lacks exactly one `81 3D <g> 10 00 00 00 <recorded jcc>` (or its imm8 form
    `83 3D <g> 10`, keystone's encoding: thunk_filedlg_rects v2, 2026-10-25 W2D F41)."""
    bad = []
    for n in REGATED:
        t = (templates or {}).get(n) or TMPL[n][1]
        hits = sum(t.count(gate + " " + GATE_JCC[n] + " ") for gate in (_TOK, _RAW, _TOK8))
        if hits != 1:
            bad.append(n)
    return bad


def test_gate_pins_cover_every_regated_thunk():
    assert set(GATE_JCC) == set(REGATED)


def test_regated_gate_bytes_and_jcc_are_pinned():
    assert gate_pin_failures() == []


def g17_identical(code: dict, names=REGATED) -> list:
    """Re-gated thunks that do at g = 17 exactly what they do at g = 16 (a gate at 0x11, or jg -> jge)."""
    return [n for n in names if run_at(code, n, 1088, 816, 17) == run_at(code, n, 1088, 816, 16)]


def test_g17_takes_the_scaled_path():
    assert g17_identical(LIVE) == []


# ---- mutants: one restored width gate per family -------------------------------------------------------------------
_TOK = "81 3D {abs32:g_popup_scale_num} 10 00 00 00"
_RAW = "81 3D 40 87 66 00 10 00 00 00"
_TOK8 = "83 3D {abs32:g_popup_scale_num} 10"
MUTANTS = {
    "faction font: SW > 0x400": ("thunk_factionwin_font", _TOK, "81 3D {abs32:ScreenWidth} 00 04 00 00"),
    "connector pixel: SW > 0x400": ("thunk_conn_pixel", _RAW, "81 3D 1C 7B 9B 00 00 04 00 00"),
    "file dialog window: SW > 0x400": ("thunk_filedlg_graphicwin", _TOK, "81 3D {abs32:ScreenWidth} 00 04 00 00"),
    "popup list fill: SW > 0x3FF": ("thunk_list_fill_width", _TOK, "81 3D 1C 7B 9B 00 FF 03 00 00"),
    # static-only probes: the wrap-budget arm at g = 16 is edi * 16 >> 4 (an identity, and the thunk has no live
    # site), and the register-load form clobbers eax -- the behaviour sweep is not their guard, the scan is
    "wrap budget: SW > 0x3FF": ("thunk_wrap_budget", _TOK, "81 3D 1C 7B 9B 00 FF 03 00 00"),
    "faction list (load form): mov eax,[SW]; cmp eax,0x400": (
        "thunk_factionwin_list", _TOK, "A1 {abs32:ScreenWidth} 3D 00 04 00 00"),
}
STATIC_ONLY = {"wrap budget: SW > 0x3FF", "faction list (load form): mov eax,[SW]; cmp eax,0x400"}

# gate slips the pins must kill: (thunk, old, new, the guard that must catch it)
GATE_MUTANTS = {
    "list fill: jle -> jl": ("thunk_list_fill_width", _TOK + " 7E", _TOK + " 7C", "pin"),
    "faction font: jle -> jl": ("thunk_factionwin_font", _TOK + " 7E", _TOK + " 7C", "pin"),
    "connector diag: jg -> jge": ("thunk_conn_diag", _RAW + " 7F", _RAW + " 7D", "pin"),
    "list fill: gate 0x11": ("thunk_list_fill_width", _TOK, _TOK.replace(" 10 00", " 11 00"), "pin+g17"),
    "file dialog window: gate 0x11": ("thunk_filedlg_graphicwin", _TOK, _TOK.replace(" 10 00", " 11 00"), "pin+g17"),
    "connector chevron: gate 0x11": ("thunk_conn_chevron", _RAW, _RAW.replace(" 10 00 00 00", " 11 00 00 00"),
                                      "pin+g17"),
    "file dialog window: SH > 0x300": ("thunk_filedlg_graphicwin", _TOK, "81 3D {abs32:ScreenHeight} 00 03 00 00",
                                       "scan"),
}


@pytest.mark.parametrize("name", list(GATE_MUTANTS))
def test_gate_slip_mutants_are_killed(name):
    thunk, old, new, guard = GATE_MUTANTS[name]
    t = TMPL[thunk][1]
    assert t.count(old) == 1, (name, old)
    t = t.replace(old, new)
    assert len(resolve(thunk, t)) == len(LIVE[thunk])
    assert thunk in gate_pin_failures({thunk: t}), f"the gate pin misses {name}"
    if "g17" in guard:
        assert g17_identical(_code_with({thunk: t}), (thunk,)) == [thunk], f"the g = 17 check misses {name}"
    if guard == "scan":
        assert thunk in all_width_gates({thunk: t}), f"the static scan misses {name}"


def _mutant_template(name: str) -> tuple:
    thunk, old, new = MUTANTS[name]
    t = TMPL[thunk][1]
    assert t.count(old) == 1, (name, old)
    return thunk, t.replace(old, new)


@pytest.mark.parametrize("name", list(MUTANTS))
def test_width_gate_mutants_are_killed(name):
    thunk, t = _mutant_template(name)
    assert len(resolve(thunk, t)) == len(LIVE[thunk])            # same-length swap: nothing else moves
    assert thunk in all_width_gates({thunk: t}), f"the static scan misses mutant {name}"
    if name not in STATIC_ONLY:
        assert g16_width_dependence(_code_with({thunk: t}), (thunk,)) == [thunk], \
            f"the g = 16 behaviour sweep misses mutant {name}"
