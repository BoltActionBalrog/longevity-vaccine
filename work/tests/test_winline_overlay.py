"""uimod's window-line overlay (src/uimod/src/lineoverlay.h + vidmode.cpp + gpuscale.cpp) and the Modern Control Set's
map-pointer gate (src/uimod/src/mapgate.h + modernctl.cpp).

Win_window_line_raw 0x5F2AC0 draws the tutorial box's pointer lines (and the console crosshair) with GDI straight onto
the game WINDOW at FRAME coordinates. In the stretched display modes the frame is scaled into the client, so the line
landed at frame coordinates in client space (half way at 1920x1080 on a 4K client) at native pen width, and the GPU
present (a DISCARD swap chain repainting the whole client per flip) wiped it on the next flip: it blinked. vidmode.cpp
detours the function when stretched, keeps the lines (lineoverlay.h) and gpuscale.cpp composites them in client space.

The hover gate: Win_get_mouse_window's hit-test lets a window with flag 0x10000000 decline a see-through pixel; the
event falls through to the map. The HUD strip's see-through band is the map to the player (coordinates rebuilt); the
tutorial box is not (the hover line and a right click acted under it, 2026-10-11).

Builds tests/winline_selftest.cpp with the VS x86 toolchain (skipped when VS is absent); the site checks read the
pristine exe.
"""
from __future__ import annotations

import pathlib
import re
import struct
import subprocess
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import cpp_harness  # noqa: E402
import config  # noqa: E402
import pefile  # noqa: E402

SRC_DIR = ROOT.parent / "src" / "uimod" / "src"
VID = (SRC_DIR / "vidmode.cpp").read_text(encoding="utf-8")
WL = (SRC_DIR / "winlines.cpp").read_text(encoding="utf-8")
VCX = (SRC_DIR.parent / "uimod.vcxproj").read_text(encoding="utf-8")
GPU = (SRC_DIR / "gpuscale.cpp").read_text(encoding="utf-8")
CTL = (SRC_DIR / "modernctl.cpp").read_text(encoding="utf-8")
LO = (SRC_DIR / "lineoverlay.h").read_text(encoding="utf-8")
SYMS = (ROOT / "symbols" / "terranx.h").read_text(encoding="utf-8")

LINE_RAW = 0x5F2AC0
TUT_CALLS = {0x4BDED9: 1, 0x4BDF0F: 2, 0x4BE3FA: 1, 0x4BE432: 2}   # call site -> pointer line
CROSSHAIR_CALLS = (0x5103BC, 0x5103E5)
TUT1, TUT2, OTHER = "4BDEDE", "4BDF14", "5103C1"

BAK = config.terranx_bak(required=False)
needs_exe = pytest.mark.skipif(not BAK or not pathlib.Path(BAK).exists(), reason="pristine exe not available")
needs_vs = pytest.mark.skipif(not cpp_harness.have_toolchain(), reason="Visual Studio x86 toolchain not available")


# ---- the C++ logic -----------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def exe():
    return cpp_harness.build(ROOT / "tests" / "winline_selftest.cpp", "winline_selftest_", "/Oi /GL")


def run(exe, *cmds: str) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="wl_") as t:
        p = pathlib.Path(t) / "s.txt"
        p.write_text("\n".join(cmds) + "\n", encoding="ascii")
        r = subprocess.run([str(exe), str(p)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, (r.returncode, r.stderr)
    return r.stdout.split("\n")[:-1]


def dump(out: list[str]) -> list[tuple[int, ...]]:
    i = max(k for k, s in enumerate(out) if s.startswith("n "))
    n = int(out[i].split()[1])
    return [tuple(map(int, s.split())) for s in out[i + 1:i + 1 + n]]


def add(x0, y0, x1, y1, ret, width=3, style=2, color=255):
    return f"add {x0} {y0} {x1} {y1} {color} {width} {style} {ret}"


@needs_vs
def test_pointer_redraw_restores_a_partly_repainted_line(exe):
    """A flip over part of the line erases that part (an erase rect); the next blink redraw restores it whole."""
    out = run(exe, add(100, 100, 600, 400, TUT1), add(100, 120, 600, 400, TUT2),
              "flip 580 380 620 420", "dump", add(100, 100, 600, 400, TUT1), "dump")
    assert out[2] == "changed 1"
    first = dump(out[:6])
    assert [(l[4], l[5]) for l in first] == [(1, 1), (2, 1)]          # both touched the cursor tile's flip
    assert [(l[4], l[5]) for l in dump(out)] == [(1, 0), (2, 1)]      # line 1 redrawn whole, line 2 not yet


@needs_vs
def test_new_pointer_drops_the_old_pointer(exe):
    out = run(exe, add(100, 100, 600, 400, TUT1), add(100, 120, 600, 400, TUT2), add(5, 5, 9, 9, OTHER, 1, 0),
              add(300, 300, 50, 50, TUT1), "dump")
    assert [(l[0], l[4]) for l in dump(out)] == [(5, 0), (300, 1)]


@needs_vs
def test_flip_over_the_whole_line_removes_it_and_misses_leave_it(exe):
    out = run(exe, add(0, 0, 100, 100, OTHER, 1, 0),
              "flip 80 0 100 20",        # inside the bounding box, nowhere near the diagonal
              "flip -5 -5 200 200", "dump")
    assert out[1] == "changed 0" and out[2] == "changed 1" and dump(out) == []


@needs_vs
def test_crosshair_flip_of_exactly_its_own_pixels_removes_it(exe):
    """Console_on_nc_mouse_move draws MoveTo(0,y) -> LineTo(W,y) and MoveTo(x,0) -> LineTo(x,H) with a 1-px pen and
    erases the old pair by flipping exactly [0,W) x [y,y+1) and [x,x+1) x [0,H) (0x5D55D0): GDI's LineTo stops one
    pixel short, so those rects hold every pixel and the lines go (they leaked and evicted the pointer before)."""
    out = run(exe, add(0, 500, 1200, 500, OTHER, 1, 0), add(700, 0, 700, 900, OTHER, 1, 0),
              "flip 0 500 1200 501", "flip 700 0 701 900", "dump")
    assert out[2:4] == ["changed 1", "changed 1"] and dump(out) == []


@needs_vs
def test_crosshair_storm_never_evicts_the_pointer(exe):
    """Even lines nobody erases cannot push the tutorial pointer out: only non-tutorial lines are evicted."""
    storm = [add(0, y, 1200, y, OTHER, 1, 0) for y in range(20)]
    out = run(exe, add(100, 100, 600, 400, TUT1), add(100, 120, 600, 400, TUT2), *storm, "dump")
    lines = dump(out)
    assert len(lines) == 8 and [l[4] for l in lines[:2]] == [1, 2]
    assert [l[1] for l in lines[2:]] == list(range(14, 20))


@needs_vs
def test_too_many_partial_repaints_drop_the_line_until_its_redraw(exe):
    flips = [f"flip {x} 95 {x + 10} 105" for x in range(0, 140, 20)]    # 7 disjoint partial repaints, 6 slots
    out = run(exe, add(0, 100, 1000, 100, TUT1), *flips, "dump", add(0, 100, 1000, 100, TUT1), "dump")
    assert dump(out[:out.index("n 0") + 1]) == []
    assert [(l[4], l[5]) for l in dump(out)] == [(1, 0)]


@needs_vs
def test_a_repaint_inside_a_remembered_one_changes_nothing(exe):
    out = run(exe, add(0, 100, 1000, 100, TUT1), "flip 0 90 200 110", "flip 50 95 60 105", "dump")
    assert out[1:3] == ["changed 1", "changed 0"] and dump(out)[0][5] == 1


@needs_vs
def test_dismissed_pointer_is_pruned(exe):
    out = run(exe, add(100, 100, 600, 400, TUT1), add(100, 120, 600, 400, TUT2), add(5, 5, 9, 9, OTHER, 1, 0),
              "prune 1 1", "prune 1 0", "dump", "prune 0 0", "dump")
    assert out[3:5] == ["changed 0", "changed 1"]
    assert [l[4] for l in dump(out[:out.index("n 2") + 3])] == [1, 0]
    assert [l[4] for l in dump(out)] == [0]


@needs_vs
def test_ps_null_and_zero_length_are_not_kept_and_the_oldest_line_goes_first(exe):
    adds = [add(i, 0, i, 50, OTHER, 1, 0) for i in range(9)]
    out = run(exe, add(1, 1, 2, 2, OTHER, 1, 5), add(7, 7, 7, 7, OTHER, 1, 0), *adds, "dump")
    assert out[0:2] == ["kept 0", "kept 0"]          # PS_NULL; a 1-px line of no length (GDI draws nothing)
    assert [l[0] for l in dump(out)] == list(range(1, 9))


@needs_vs
@pytest.mark.parametrize("x0,y0,x1,y1,w,rect,want", [
    (0, 100, 1000, 100, 3, (500, 101, 510, 120), 1),     # the pen's lower half reaches row 101
    (0, 100, 1000, 100, 3, (500, 102, 510, 120), 0),
    (0, 100, 1000, 100, 1, (500, 101, 510, 120), 0),
    (50, 50, 50, 50, 1, (50, 50, 51, 51), 1),            # a point
    (0, 0, 100, 100, 1, (60, 40, 70, 50), 0),
    (0, 0, 100, 100, 1, (45, 45, 55, 55), 1),
])
def test_touches(exe, x0, y0, x1, y1, w, rect, want):
    assert run(exe, f"touches {x0} {y0} {x1} {y1} {w} {' '.join(map(str, rect))}") == [f"touches {want}"]


@needs_vs
@pytest.mark.parametrize("v,client,frame,want", [
    (100, 3840, 1920, 201), (0, 3840, 1920, 1), (1919, 3840, 1920, 3839),
    (100, 2880, 1600, 180), (-1, 3840, 1920, -1), (100, 1600, 1600, 100), (100, 1280, 3840, 33),
])
def test_to_client_is_the_image_of_the_pixel_centre(exe, v, client, frame, want):
    assert run(exe, f"toclient {v} {client} {frame}") == [f"client {want}"]


@needs_vs
@pytest.mark.parametrize("w,style,client,frame,want", [
    (3, 2, 3840, 1920, 6),     # the TutWin pen (2 x g/16 = 3 at g 22), PS_DOT drawn solid: x2 on a 4K client
    (3, 2, 2880, 1600, 5),     # 1600x1200 on a 2880x2160 client: 5.4
    (0, 0, 3840, 1920, 2),     # a cosmetic one-pixel pen scales with the frame
    (1, 1, 3840, 1920, 1),     # ... unless it is dashed: GDI would draw a wider pen solid
    (5, 0, 1280, 3840, 2),     # shrinking (a small Windowed window)
    (1, 0, 1280, 3840, 1),
])
def test_client_pen_width_is_vanilla_times_scale(exe, w, style, client, frame, want):
    assert run(exe, f"penw {w} {style} {client} {frame}") == [f"penw {want}"]


MAP_ORG = (0, 0)
TUT_BOX = (1500, 600, 2300, 900)
TICKER = (1200, 1300, 2600, 1360)


def gate(local, raw, blockers=()):
    b = " ".join(" ".join(map(str, r)) for r in blockers)
    return f"gate {local[0]} {local[1]} {raw[0]} {raw[1]} {MAP_ORG[0]} {MAP_ORG[1]} {len(blockers)} {b}".strip()


@needs_vs
@pytest.mark.parametrize("local,raw,blockers,want,hit", [
    ((1000, 700), (1000, 700), (), 1, -1),                      # the map's own move
    ((552, 34), (1000, 1471), (), 2, -1),                       # the strip band, whatever coordinates arrive: rebuilt
    ((1000, 1471), (1000, 1471), (), 1, -1),                    # ... already map-local (a top-level decliner restored them)
    ((5, 5), (1000, 700), (TUT_BOX,), 2, -1),                   # off every window: the map's
    ((10, 20), (1510, 620), (TUT_BOX,), 0, 0),                  # tutorial-local coordinates under the box
    ((1510, 620), (1510, 620), (TUT_BOX,), 0, 0),               # map-local, but the raw point is on the box
    ((2299, 899), (2299, 899), (TUT_BOX,), 0, 0),
    ((2300, 900), (2300, 900), (TUT_BOX,), 1, -1),              # half-open: just outside the box is the map
    ((1300, 1320), (1300, 1320), (TUT_BOX, TICKER), 0, 1),      # the NetMsg ticker (or any window above the map)
])
def test_map_point_gate(exe, local, raw, blockers, want, hit):
    assert run(exe, gate(local, raw, blockers)) == [f"verdict {want} hit {hit}"]


# ---- the engine sites the DLL relies on -------------------------------------------------------------------

@pytest.fixture(scope="module")
def pe():
    if not BAK or not pathlib.Path(BAK).exists():
        pytest.skip("pristine exe not available")
    return pefile.PE(str(BAK))


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def call_target(pe, va):
    b = rd(pe, va, 5)
    assert b[0] == 0xE8, f"no call at {va:#x}"
    return va + 5 + struct.unpack("<i", b[1:])[0]


def cpp_bytes(src: str, name: str) -> bytes:
    m = re.search(name + r"\[[^\]]*\]\s*=\s*\{([^}]*)\}", src)
    assert m, name
    return bytes(int(t, 16) for t in re.findall(r"0x([0-9A-Fa-f]{2})", m.group(1)))


def iat_name(pe, va) -> str:
    for d in pe.DIRECTORY_ENTRY_IMPORT:
        for imp in d.imports:
            if imp.address == va:
                return imp.name.decode()
    return ""


@needs_exe
def test_line_raw_entry_and_its_gdi_calls(pe):
    """The detour replaces the 5-byte `mov eax,[0x9B3AB0]` and the trampoline resumes at +5; the function is RET 0x1C
    (7 stack args = the fastcall hook's), draws MoveToEx(x2, y2) -> LineTo(x, y) with a PALETTEINDEX pen on GetDC(hwnd)."""
    assert rd(pe, LINE_RAW, 13) == cpp_bytes(WL, "kLineRawBytes")
    assert re.search(r"kVA_LineRaw = 0x005F2AC0, kVA_LineRawResume = 0x005F2AC5", WL)
    assert rd(pe, 0x5F2C10, 3) == bytes.fromhex("C21C00")
    assert iat_name(pe, 0x66927C) == "GetDC" and iat_name(pe, 0x66904C) == "CreatePenIndirect"
    assert iat_name(pe, 0x669048) == "MoveToEx" and iat_name(pe, 0x6690C4) == "LineTo"
    assert rd(pe, 0x5F2B6B, 5) == bytes.fromhex("0D00000001")              # or eax, 0x1000000 = PALETTEINDEX
    assert rd(pe, 0x5F2B9B, 4) == bytes.fromhex("8B4C2428")                # MoveToEx x = arg 3 (x2)
    assert rd(pe, 0x5F2BBA, 4) == bytes.fromhex("8B4C2420")                # LineTo x = arg 1 (x)
    assert "l.x0 = x2; l.y0 = y2; l.x1 = x; l.y1 = y;" in WL


@needs_exe
def test_callers_and_their_return_addresses(pe):
    """The tutorial lines are told apart by the call's return address; the patcher's pen-width thunk in front of the
    four TutWin calls tail-jumps by push/ret, so the hook still sees the site's own return address."""
    for site, which in TUT_CALLS.items():
        assert call_target(pe, site) == LINE_RAW
        assert f"0x{site + 5:X}" in re.search(rf"kRetTutLine{which}\[2\] = \{{[^}}]*\}}", LO).group(0)
    for site in CROSSHAIR_CALLS:
        assert call_target(pe, site) == LINE_RAW
    patches = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    assert re.search(r'id: thunk_tutwin_line\s*\n[^\n]*\n\s*bytes: "[^"]*68 \{abs32:Win_window_line_raw\} C3"', patches)


@needs_exe
def test_tutorial_pointer_state_fields(pe):
    """TutWin_draw_arrow: draws while +0x53A4, the second line while +0x539C >= 0 (vidmode prunes on the same tests)."""
    assert rd(pe, 0x4BDEA3, 6) == bytes.fromhex("8B86A4530000")            # mov eax, [esi+0x53A4]
    assert rd(pe, 0x4BDEDE, 10) == bytes.fromhex("8B869C53000085C07C2C")   # mov eax,[esi+0x539C]; test; jl
    assert "kVA_TutArmed  = 0x008C6E68 + 0x53A4" in WL and "kVA_TutLine2X = 0x008C6E68 + 0x539C" in WL
    assert "Rd<int>(kVA_TutLine2X) >= 0" in WL


def test_nothing_else_patches_the_hooked_entry():
    """Thinker patches the exe in memory and the patcher bakes sites: neither may touch 0x5F2AC0..0x5F2AC4."""
    patches = (ROOT / "patches" / "patches.yaml").read_text(encoding="utf-8")
    sites = [(int(m.group(1), 16), int(m.group(2)))
             for m in re.finditer(r"virtual_addr:\s*0x([0-9A-Fa-f]+)\s*\n\s*length:\s*(\d+)", patches)]
    assert len(sites) > 100, "patches.yaml sites not parsed"
    for lo, n in sites:
        assert lo + n <= LINE_RAW or lo >= LINE_RAW + 5, f"patch site {lo:#x}+{n} overlaps Win_window_line_raw's entry"
    thinker = ROOT.parent / "refs" / "thinker" / "src"
    if thinker.exists():
        for f in thinker.glob("*.cpp"):
            for m in re.finditer(r"write_(?:call|jump|offset|bytes|byte)\s*\(\s*0x([0-9A-Fa-f]{6})", f.read_text(encoding="utf-8", errors="replace")):
                va = int(m.group(1), 16)
                assert not (LINE_RAW - 4 < va < LINE_RAW + 5), f"{f.name}: {va:#x}"


def test_every_stretched_present_without_the_gpu_invalidates_its_frame():
    """A line re-present draws the GPU's frame copy over the whole client: every stretched update that reaches the
    window another way (the CPU resampler, GDI's stretch, a movie frame) marks that copy stale first."""
    sf = VID[VID.index("bool ScaledFlip("):VID.index("BOOL WINAPI FlipBlt")]
    gpu_ok = sf.index("return true;", sf.index("GpuPresent(hwnd"))
    assert sf.index("GpuInvalidate();") > gpu_ok and sf.index("GpuInvalidate();") < sf.index("RunJob();")
    flip = VID[VID.index("BOOL WINAPI FlipBlt"):VID.index("bool HookFlipBlt")]
    assert flip.index("GpuInvalidate();", flip.index("ScaledFlip(hwnd")) < flip.index("StretchBlt(")
    movie = (SRC_DIR / "movie.cpp").read_text(encoding="utf-8")
    present = movie[movie.index("auto present = [&]()"):movie.index("};", movie.index("auto present = [&]()"))]
    assert "GpuInvalidate();" in present
    assert "return GpuCurrent(hwnd, cw, ch) && DrawPresent();" in GPU
    assert "return !g_failed && g_dev && g_frame && !g_stale && hwnd == g_hwnd && cw == g_cw && ch == g_ch;" in GPU


def test_line_presents_are_batched():
    """One GPU re-present per batch of line draws (from the message poll), never one per line; a flip carries them."""
    hook = WL[WL.index("void __fastcall LineRawHook"):WL.index("void WinLinesPoll")]
    assert hook.count("GpuRepresent(") == 1 and "g_presentOwed = true" in hook   # only for a completed pointer batch
    assert "if (code == HC_ACTION) WinLinesPoll();" in (SRC_DIR / "wheel.cpp").read_text(encoding="utf-8")
    on_flip = WL[WL.index("void WinLinesOnFlip"):]
    assert on_flip.index("g_presentOwed = false;") < on_flip.index("if (!stretched)")
    assert "if (flipOk)" in VID[VID.index("const bool flipOk = HookFlipBlt(px);"):]


def test_present_paths_carry_the_lines():
    """Stretched: every flip erases what it repaints, the GPU present composites, the CPU fallback draws the engine's own
    line at client coordinates; not stretched: the engine's line untouched and the record cleared."""
    flip = VID[VID.index("BOOL WINAPI FlipBlt"):]
    assert flip.index("WinLinesOnFlip(false, 0, 0, 0, 0);") < flip.index("WinLinesOnFlip(true, sx, sy, sx + w, sy + h);")
    hook = WL[WL.index("void __fastcall LineRawHook"):WL.index("void WinLinesOnFlip")]
    assert "GpuCurrent(hwnd, cr.right, cr.bottom)" in hook and "ToClient(x, cr.right, sw)" in hook
    assert hook.index("if (!ScaledClient(") < hook.index("lineoverlay::Add(")
    assert "VidModeStretched() &&" in WL          # the one "frame stretched to the client" predicate
    assert "InstallWinLines()" in VID and 'ClCompile Include="src\\winlines.cpp"' in VCX
    assert "float4 lineErase[48];" in GPU and "lineoverlay::kMaxLines == 8 && lineoverlay::kMaxErase == 6" in GPU
    assert "return float4(Lines(pos.xy, acc / (foot.x * foot.y)), 1.0);" in GPU
    assert "return DrawPresent();" in GPU


@needs_exe
def test_map_gate_engine_facts(pe):
    """The hit-test declines a see-through pixel only for a window with flag 0x10000000 (0x5F6C26); a top-level
    window's screen rect is rRect2 (+0x14C, the hit-test's first test) when +0x9C & 2, else rRect1 (+0x13C)."""
    assert rd(pe, 0x5F6C26, 11) == bytes.fromhex("8B8698000000A900000010")   # mov eax,[esi+0x98]; test eax,0x10000000
    assert rd(pe, 0x5F6B5A, 7) == bytes.fromhex("F6869C00000002")            # test byte [esi+0x9C], 2
    assert rd(pe, 0x5F6B6C, 6) == bytes.fromhex("8D9E4C010000")              # lea ebx, [esi+0x14C]
    assert rd(pe, 0x5F6BFB, 6) == bytes.fromhex("8D9E3C010000")              # lea ebx, [esi+0x13C]
    assert "kVA_MainWin        = 0x7AE820" in CTL and "kVA_TutWin         = 0x8C6E68" in CTL
    assert re.search(r"MainWin_g;\s*// addr: 0x007AE820", SYMS) and re.search(r"TutWin;\s*// addr: 0x008C6E68", SYMS)
    assert "kWinRect1 = 0x13C, kWinRect2 = 0x14C" in CTL
    # the top-level walk: count, list, first claimant wins, the claimant's +0xA8 is what the walk returns
    assert rd(pe, 0x5F72D1, 6) == bytes.fromhex("8B0D347B9B00")              # mov ecx, [g_top_window_count]
    assert rd(pe, 0x5F72DB, 5) == bytes.fromhex("BD486E9B00")                # mov ebp, g_top_windows
    assert rd(pe, 0x5F72EE, 4) == bytes.fromhex("85C07512")                  # test eax,eax; jnz (first hit wins)
    assert rd(pe, 0x5F730E, 6) == bytes.fromhex("8B80A8000000")              # mov eax, [eax+0xA8]
    assert rd(pe, 0x5F6B0C, 6) == bytes.fromhex("8B86FC030000")              # children count +0x3FC
    assert rd(pe, 0x5F6B18, 6) == bytes.fromhex("8D8EA4010000")              # children array +0x1A4
    assert "kVA_TopWindows     = 0x9B6E48" in CTL and "kVA_TopWindowCount = 0x9B7B34" in CTL
    assert "kWinDelegate = 0xA8" in CTL and "kWinChildren = 0x1A4, kWinChildCount = 0x3FC" in CTL
    assert re.search(r"g_top_windows\[\];\s*// addr: 0x009B6E48", SYMS)


def test_gate_blockers_are_the_windows_tried_before_the_map():
    """Blockers = shown top-level windows the walk tries BEFORE the one holding the map, minus the strip and the map's
    overlay; the global tutorial box always; nothing else when the map is not found in the walk (never block it all)."""
    mb = CTL[CTL.index("int MapBlockers("):CTL.index("void GateDbg(")]
    assert "mapgate::Blockers(kWinAccess" in mb and "gw," in mb and "At(kVA_MainWin), Overlay(), At(kVA_TutWin)" in mb
    assert "{ WinDelegateOf, WinChildCountOf, WinChildOf, WinRectOf }" in CTL
    assert "kWinChildren + 4 * i" in CTL and "static_cast<const BYTE*>(w) + kWinDelegate" in CTL
    assert "UimodDbg(m);" in CTL[CTL.index("void GateDbg("):CTL.index("mapgate::Verdict MapPointVerdict")]


# synthetic windows: id delegate shown l t r b nchild children
WINS = [
    "win 1 0 1 0 0 3840 2160 0",            # the map's GraphicWin
    "win 2 0 1 0 0 3840 2160 1 1",          # a frame holding the map as its child
    "win 3 0 1 448 1437 3392 2160 0",       # MainWin_g, the strip
    "win 4 0 1 0 0 3840 2160 0",            # the map's drag overlay
    "win 5 0 1 1500 600 2300 900 0",        # TutWin
    "win 6 0 1 1000 400 2800 1200 0",       # a heap tutorial popup (#COMMERCE)
    "win 7 0 1 1200 1300 2600 1360 0",      # the NetMsg ticker
    "win 8 0 0 0 0 100 100 0",              # a hidden popup
    "win 9 1 1 0 0 3840 2160 0",            # a window delegating to the map
    "win 10 0 1 0 1400 3840 2160 1 3",      # a window holding the strip as its child
    "win 11 0 1 0 0 3840 2160 0",           # a shown window below the map
]


@needs_vs
@pytest.mark.parametrize("order,want", [
    ([1, 6, 7], "map 0 block 5"),                     # the map first: only the tutorial box
    ([6, 3, 4, 8, 1, 11], "map 4 block 6 5"),         # after a popup: it blocks; strip / overlay / hidden do not
    ([6, 7, 11], "map -1 block 5"),                   # the map not in the walk: never block it all, the box only
    ([6, 9, 7], "map 1 block 6 5"),                   # a window delegating to the map is the map
    ([10, 7, 2], "map 2 block 7 5"),                  # the strip as a child is still the strip; the map as a child
])
def test_blockers_walk_synthetic_lists(exe, order, want):
    out = run(exe, *WINS, f"walk 1 3 4 5 {len(order)} {' '.join(map(str, order))}")
    assert out == [want]


@needs_vs
def test_blockers_hidden_tutorial_box_blocks_nothing(exe):
    out = run(exe, *WINS, "win 5 0 0 1500 600 2300 900 0", "walk 1 3 4 5 3 6 1 7")
    assert out == ["map 1 block 6"]


def test_pointer_batch_presents_at_once_and_posts_a_poll_otherwise():
    hook = WL[WL.index("void __fastcall LineRawHook"):WL.index("void WinLinesPoll")]
    assert "l.tag == lineoverlay::kTagTut2 || (l.tag == lineoverlay::kTagTut1 && Rd<int>(kVA_TutLine2X) < 0)" in hook
    assert hook.index("GpuRepresent(hwnd, cr.right, cr.bottom);") < hook.index("g_presentOwed = true;")
    assert "PostMessageA(hwnd, WM_NULL, 0, 0)" in hook and "GetTickCount() - g_nullPostedAt >= kNullPostMs" in hook
    poll = WL[WL.index("void WinLinesPoll"):WL.index("void WinLinesOnFlip")]
    assert "g_nullPosted" not in poll                 # never cleared on dequeue: the latch expires by time


def test_gate_is_applied_to_hover_right_press_and_right_click():
    assert "FixMapPoint(gw, mx, my)" in CTL and "if (!FixMapPoint(gw, x, y)) return;" in CTL
    wrap = CTL[CTL.index("void __fastcall RightClickWrap"):]
    assert wrap.index("MapPointVerdict(gw, x, y) == mapgate::kNotMap") < wrap.index("AddWaypoint(gw, x, y)")
    assert "|| g_rightNotMap) return -1;" in CTL
    # the tutorial box never stops input around it: MapTakesInput is untouched
    mti = CTL[CTL.index("bool  MapTakesInput()"):CTL.index("bool  VehOk")]
    assert "TutWin" not in mti
