"""uimod's HD main menu (src/uimod/src/menuhd.cpp), against the pristine and the patched exe and Thinker's source.

menuhd detours Buffer_load_pcx's entry (to learn which picture each Buffer holds -- the exe's callers and
Thinker's alike), retargets the opening's two Buffer_copy_3 stretches (change_opening @0x589AE8, the stock top_menu's;
init_opening @0x589CCB, Thinker's top_menu's) and the 5 calls of SetupWin_draw_item. Its DrawItemHook mirrors
draw_item's early-out, empties deco[clamp(item, 0, 2)] (SetupWin +0xA1C) -- with it null draw_item skips its three
preview draws, Thinker's re-pointed ones too -- and draws the HD preview into the TopMenuWin canvas (+0x444) itself,
presented with GraphicWin_soft_update. Every one of those facts is pinned here.
"""
from __future__ import annotations

import pathlib
import re
import struct
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pefile  # noqa: E402

import apply_patches as ap  # noqa: E402
import config  # noqa: E402

BAK = config.terranx_bak(required=False)
pytestmark = pytest.mark.skipif(not BAK or not pathlib.Path(BAK).exists(), reason="pristine exe not available")

SRC_DIR = ROOT.parent / "src" / "uimod" / "src"
HD = (SRC_DIR / "menuhd.cpp").read_text(encoding="utf-8")
SYMBOLS = (ROOT / "symbols" / "terranx.h").read_text(encoding="utf-8")

LOAD_PCX, COPY3, DRAW_ITEM, SOFT_UPDATE = 0x5D7DE0, 0x5D9610, 0x4AE4D0, 0x5D5720
CHANGE_OPENING, CHANGE_OPENING_END = 0x589A30, 0x589B20
INIT_OPENING, INIT_OPENING_END = 0x589B60, 0x589D20
CUSTOM_PLANET, CUSTOM_PLANET_END = 0x58C2A0, 0x58D6B0      # map_menu follows
TOPMENUWIN = 0x945824
OPENING_LOADS = {CHANGE_OPENING: 0x589AA1, INIT_OPENING: 0x589C84}
COPY_SITES = [0x589AE8, 0x589CCB]
DRAW_ITEM_SITES = [0x4AE0D7, 0x4AE3B6, 0x4AE3C9, 0x4AE43A, 0x4AE44A]
PLANET_LOAD_SITES = [0x58C44F, 0x58C4D1, 0x58C4F8, 0x58C51F, 0x58C5DB, 0x58C6B7]


@pytest.fixture(scope="module")
def pe():
    return pefile.PE(str(BAK), fast_load=True)


@pytest.fixture(scope="module")
def baked(baked_exe):
    return pefile.PE(str(baked_exe), fast_load=True)


def rd(pe, va, n):
    return pe.get_data(va - pe.OPTIONAL_HEADER.ImageBase, n)


def calls(pe, lo, hi, target):
    """Every E8 call to target in [lo, hi), searched over the image's executable sections."""
    out = []
    for s in pe.sections:
        if not s.Characteristics & 0x20000000:          # IMAGE_SCN_MEM_EXECUTE
            continue
        va0 = pe.OPTIONAL_HEADER.ImageBase + s.VirtualAddress
        d = s.get_data()
        for va in range(max(lo, va0), min(hi, va0 + len(d)) - 4):
            o = va - va0
            if d[o] == 0xE8 and va + 5 + struct.unpack("<i", d[o + 1:o + 5])[0] == target:
                out.append(va)
    return out


def table(name):
    m = re.search(name + r"\[\]\s*=\s*\{(.*?)\};", HD, re.S)
    assert m, name
    return [int(v, 16) for v in re.findall(r"0x[0-9A-Fa-f]+", m.group(1))]


def entry_bytes():
    return bytes(table("kLoadPcxEntry"))


@pytest.mark.parametrize("which", ["pristine", "patched"])
def test_both_openings_load_once_and_stretch_once_to_the_topmenuwin(pe, baked, which):
    img = pe if which == "pristine" else baked
    for (lo, hi), load in zip(((CHANGE_OPENING, CHANGE_OPENING_END), (INIT_OPENING, INIT_OPENING_END)),
                              OPENING_LOADS.values()):
        assert calls(img, lo, hi, LOAD_PCX) == [load]
        assert calls(img, lo, hi, COPY3) == [c for c in COPY_SITES if lo <= c < hi]
        assert struct.pack("<I", TOPMENUWIN) in rd(img, lo, hi - lo)
        # Buffer_load_pcx(name, 0, 10, 236): push 0xEC; push 0x0A just before the load
        assert bytes.fromhex("68EC0000006A0A") in rd(img, load - 0x20, 0x20)
    assert table("kCopySites") == COPY_SITES


def test_init_opening_has_no_caller_in_the_exe(pe):
    """Only Thinker's top_menu calls init_opening: in the exe it is dead code, so the stock path is change_opening."""
    assert calls(pe, 0x401000, 0x700000, INIT_OPENING) == []
    assert calls(pe, 0x401000, 0x700000, CHANGE_OPENING)


@pytest.mark.parametrize("which", ["pristine", "patched"])
def test_buffer_load_pcx_entry_is_the_detoured_bytes(pe, baked, which):
    """push -1; push <SEH handler>: position-independent, moved to the trampoline as they are."""
    img = pe if which == "pristine" else baked
    e = entry_bytes()
    assert len(e) == 7 and rd(img, LOAD_PCX, 7) == e
    assert e[:3] == b"\x6A\xFF\x68"


@pytest.mark.parametrize("which", ["pristine", "patched"])
def test_every_draw_item_call_is_retargeted(pe, baked, which):
    img = pe if which == "pristine" else baked
    assert calls(img, 0x401000, 0x700000, DRAW_ITEM) == DRAW_ITEM_SITES == table("kDrawItemSites")


def test_custom_planet_loads_its_previews_through_buffer_load_pcx_like_the_opening(pe):
    """custom_planet's 6 loads (S#L#C#, MOON#) go through Buffer_load_pcx(name, 0, 10, 236): the detour sees them, and
    the pictures share the opening's colours 10..245."""
    assert calls(pe, CUSTOM_PLANET, CUSTOM_PLANET_END, LOAD_PCX) == PLANET_LOAD_SITES
    assert rd(pe, CUSTOM_PLANET, CUSTOM_PLANET_END - CUSTOM_PLANET).count(bytes.fromhex("68EC000000" "6A0A")) >= 4
    assert re.search(r"kLo = 10, kHi = 246", HD)


def test_draw_item_early_out_clamp_and_null_deco_skip(pe):
    body = rd(pe, DRAW_ITEM, 0x290)
    # cmp ebx, [esi + 0xFCC]; jge -> the hook mirrors it before touching a slot
    assert body[0x0D:0x13] == bytes.fromhex("3B9ECC0F0000") and body[0x13:0x15] == bytes.fromhex("0F8D")
    assert re.search(r"kItemCountOfs = 0xFCC", HD)
    assert bytes.fromhex("85DB7C0C83FB027E09BB02000000EB0233DB") in body        # clamp item to 0..2 (<0 -> 0)
    assert bytes.fromhex("8BBC9E1C0A0000") in body                              # mov edi, [esi + ebx*4 + 0xA1C]
    # test edi, edi; je past the keyed draw, the copy and the soft update (0x4AE6D5, 0x4AE710, 0x4AE73B)
    i = body.index(bytes.fromhex("85FF0F84"))
    skip_to = DRAW_ITEM + i + 8 + struct.unpack("<i", body[i + 4:i + 8])[0]
    assert skip_to >= 0x4AE73B + 5                                              # right after the last of them
    assert bytes.fromhex("05" "44040000") in body                               # TopMenuWin + 0x444 (the canvas)
    assert calls(pe, DRAW_ITEM, DRAW_ITEM + 0x290, SOFT_UPDATE)
    assert rd(pe, DRAW_ITEM + 0x284, 3) == bytes.fromhex("C20800")              # ret 8
    assert rd(pe, SOFT_UPDATE, 3) == bytes.fromhex("83EC20")


def test_no_patch_site_overlaps_a_menuhd_lever():
    sites, _g, _c, _sym = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    ours = [(LOAD_PCX, 7)] + [(s, 5) for s in COPY_SITES + DRAW_ITEM_SITES]
    span = {s["id"]: s.get("length") or len(s.get("original_bytes", "").split()) or 5 for s in sites}
    hits = [(s["id"], hex(s["virtual_addr"])) for s in sites for o, n in ours
            if s["virtual_addr"] < o + n and o < s["virtual_addr"] + span[s["id"]]]
    assert hits == []


def test_thinker_replaces_top_menu_and_custom_planet_and_writes_none_of_our_levers():
    """Thinker v5.5's own top_menu calls init_opening and its custom_planet loads the previews from thinker.dll (both
    through the exe's Buffer_load_pcx); it re-points three calls INSIDE draw_item, never one of its callers, and
    writes neither stretch site nor Buffer_load_pcx's entry."""
    T = pytest.importorskip("thinker_overlap")
    if not T.THINKER_SRC.exists():
        pytest.skip("refs/thinker (v5.5) not checked out")
    writes = T.load_thinker()["writes"]
    by_addr = {w.addr: w for w in writes}
    assert "top_menu" in by_addr[0x52AC4A].target and "custom_planet" in by_addr[0x58D7A3].target
    assert {0x4AE6D5, 0x4AE710, 0x4AE73B} <= set(by_addr)                       # inside draw_item: skipped on null
    ours = [(LOAD_PCX, 7)] + [(s, 5) for s in COPY_SITES + DRAW_ITEM_SITES]
    assert [hex(w.addr) for w in writes for o, n in ours if w.addr < o + n and o < w.addr + max(w.length, 1)] == []
    game = (T.THINKER_SRC / "game.cpp").read_text(encoding="utf-8", errors="replace")
    assert "init_opening(menu_image())" in game and "Buffer_load_pcx(&cur_preview[i], filename, 0, 10, 236)" in game


def test_symbols_and_names():
    assert re.search(r"\binit_opening\b.*0x00589B60.*0x589C84.*0x589CCB", SYMBOLS)
    assert "kVA_BufferInit" in HD and "BufferResize" not in HD
    assert "pcx_decode" not in HD and "std::vector" not in HD                   # the bounded reader; no exceptions
    assert not (SRC_DIR / "pcx_decode.h").exists()


DESKTOP_INIT = 0x58EE60
DESKTOP_INIT_CALLERS = [0x51543C, 0x51BC0F, 0x51C5D4, 0x52ACC0, 0x58DFEB, 0x58F4D0]   # 0x52ACC0: control_game
BUFFER_CLOSE = 0x5D7470


def src_bytes(name):
    m = re.search(name + r"\[\] = \{([^}]*)\}", HD)
    assert m, name
    return bytes(int(v, 16) for v in m.group(1).replace(" ", "").split(","))


@pytest.mark.parametrize("which", ["pristine", "patched"])
def test_the_menu_is_released_where_a_game_begins(pe, which, request):
    """desktop_init (0x58EE60) is called after the menu and never at it: the engine's control_game (0x52ACC0, the
    WinMain loop: top_menu returns, then desktop_init), game_reload (0x58F4D0), the in-game loads and multiplayer_init;
    Thinker's control_game calls it from thinker.dll (game.cpp), which only an entry detour sees. The detour's 8
    moved bytes are the exe's on both images, and Buffer_close (what Buffer_init calls first) is the one ReleaseMenu
    closes the scratch with."""
    img = pe if which == "pristine" else request.getfixturevalue("baked")
    assert rd(img, DESKTOP_INIT, 8) == src_bytes("kDesktopInitEntry") == bytes.fromhex("558BECA184929300")
    assert rd(img, BUFFER_CLOSE, 6) == src_bytes("kBufferCloseEntry")
    lo = img.OPTIONAL_HEADER.ImageBase + [s for s in img.sections if s.Name.rstrip(b"\0") == b".text"][0].VirtualAddress
    text = [s for s in img.sections if s.Name.rstrip(b"\0") == b".text"][0]
    hi = lo + text.Misc_VirtualSize
    assert calls(img, lo, hi, DESKTOP_INIT) == DESKTOP_INIT_CALLERS
    assert rd(img, 0x5D76D8, 5)[0] == 0xE8 and calls(img, 0x5D76D8, 0x5D76DD, BUFFER_CLOSE) == [0x5D76D8]
    assert "ReleaseMenu();\n    return g_desktopInit(a);" in HD.replace("\r\n", "\n")
    assert '"TEXTURE"' not in HD and "32-bit process had" not in HD


def test_nothing_writes_or_branches_into_the_moved_bytes(pe):
    """No patches.yaml site writes the two detoured entries, and no rel8 / rel32 branch in .text lands inside them
    (only their first byte is a target)."""
    sites, _g, _c, _sym = ap.load_patches(pathlib.Path(ap.DEFAULT_PATCHES))
    span = {s["id"]: s.get("length") or len(s.get("original_bytes", "").split()) or 5 for s in sites}
    for va, n in ((LOAD_PCX, 7), (DESKTOP_INIT, 8)):
        assert [s["id"] for s in sites if s["virtual_addr"] < va + n and va < s["virtual_addr"] + span[s["id"]]] == []
    import capstone
    text = [s for s in pe.sections if s.Name.rstrip(b"\0") == b".text"][0]
    base = pe.OPTIONAL_HEADER.ImageBase + text.VirtualAddress
    data = text.get_data()
    inside = {va + i for va, n in ((LOAD_PCX, 7), (DESKTOP_INIT, 8)) for i in range(1, n)}
    hits = []
    for i in range(len(data) - 5):
        b = data[i]
        if b in (0xE8, 0xE9):
            t = base + i + 5 + struct.unpack("<i", data[i + 1:i + 5])[0]
        elif b == 0x0F and 0x80 <= data[i + 1] <= 0x8F:
            t = base + i + 6 + struct.unpack("<i", data[i + 2:i + 6])[0]
        elif b == 0xEB or 0x70 <= b <= 0x7F:
            t = base + i + 2 + struct.unpack("<b", data[i + 1:i + 2])[0]
        else:
            continue
        if t in inside:
            hits.append((hex(base + i), hex(t)))
    # a byte-pattern scan also matches bytes inside other instructions: confirm any hit by disassembling from it
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    real = [h for h in hits if any(ins.address == int(h[0], 16) and ins.mnemonic.startswith(("j", "call"))
                                   for ins in md.disasm(rd(pe, int(h[0], 16), 6), int(h[0], 16), 1))]
    assert not real, real


@pytest.mark.parametrize("entry,name,n", [(0x5D7DE0, "kLoadPcxEntry", 7), (0x58EE60, "kDesktopInitEntry", 8)])
def test_each_trampoline_runs_the_moved_bytes_then_continues_at_entry_plus_n(pe, entry, name, n):
    """MakeTrampoline's stub (the n moved bytes, then E9 to entry + n), emulated once against the real image: from the
    same registers it leaves the same registers and stack as the exe's own first n bytes, and arrives at entry + n."""
    from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EIP, UC_X86_REG_ESP
    moved = src_bytes(name)
    assert len(moved) == n and rd(pe, entry, n) == moved

    def run(start, stop, code=None):
        mu = Uc(UC_ARCH_X86, UC_MODE_32)
        ib = pe.OPTIONAL_HEADER.ImageBase
        for s in pe.sections:
            mu.mem_map(ib + s.VirtualAddress, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
            mu.mem_write(ib + s.VirtualAddress, s.get_data())
        mu.mem_map(0x0F000000, 0x100000)
        mu.mem_map(0x20000000, 0x1000)
        if code:
            mu.mem_write(0x20000000, code)
        for r, v in ((UC_X86_REG_ESP, 0x0F080000), (UC_X86_REG_EBP, 0x0F090000), (UC_X86_REG_EAX, 0x1234)):
            mu.reg_write(r, v)
        mu.emu_start(start, stop)
        regs = tuple(mu.reg_read(r) for r in (UC_X86_REG_ESP, UC_X86_REG_EBP, UC_X86_REG_EAX, UC_X86_REG_EIP))
        return regs, bytes(mu.mem_read(0x0F07FFE0, 0x20))

    stub = moved + b"\xE9" + struct.pack("<i", (entry + n) - (0x20000000 + n + 5))
    assert run(0x20000000, entry + n, stub) == run(entry, entry + n)
