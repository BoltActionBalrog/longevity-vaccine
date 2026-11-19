"""uimod pssphere.cpp / pslabel_core.h -- under Thinker 5.5 the PSYCH tab's row-label append at 0x408DBD is CHAINED.

Thinker write_calls the engine's `call crt_strcat` at 0x408DBD to its BaseWin_draw_psych_strcat, which (a) relabels a
sphere / stapled base's rows ("Stapled Base" -> "Unmodified", "Secret Projects" -> "Stapled Base") and (b) prints the
captured-base countdown ("Captured Base: N turns").  Our would-be totals sit in row 4 on exactly the sphere / stapled
bases, so (a) is squashed there (user decision 2026-10-29); the old squash put the engine's strcat back for EVERY base
and so lost (b) too (THINKER AUDIT 2026-11-09).  Now the call goes to PsychLabelChain: the engine's strcat for labels
971 / 327 on a sphere / stapled base, Thinker's own function for everything else.

Pinned here:
  1. the engine site: the five-row label switch (which labels reach 0x408DBD), the call's cdecl shape, that eax is not
     read after it, and that crt_strcat really is strcat (Unicorn on the shipped exe); our bake and the plain exe agree;
  2. Thinker: the source writes the call (and the two jumps the chain sits behind) in every mode; the 5.5 release
     binary stores exactly that call, its function makes the base / label tests KeepOwn mirrors, and every pointer it
     reads is the engine's;
  3. KeepOwn, native, over every base kind, label, id and label-table state;
  4. the composition, end to end: Thinker's REAL function from the 5.5 binary run under Unicorn, behind KeepOwn's
     choice, over every base kind (ordinary / captured / sphere / staple and their mixes) and render_base_info on and
     off: every row reads its own label except the captured countdown, which is Thinker's;
  5. the module: every chained Thinker target must land inside thinker.dll (base_energy, base_compute and this call;
     the rel32 decode / encode is pslabel_core.h, run natively against the x86 rule), each chain stores Thinker's
     target and points its own site at its own wrapper, the call is chained only behind the other two, and plain PRACX
     (no jump at base_energy) is untouched.
"""
from __future__ import annotations

import pathlib
import re
import struct
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import cpp_harness  # noqa: E402
import thinker_overlap as T  # noqa: E402

UIMOD = ROOT.parent / "src" / "uimod" / "src"
PS = (UIMOD / "pssphere.cpp").read_text(encoding="utf-8")
CORE = (UIMOD / "pslabel_core.h").read_text(encoding="utf-8")

SITE, STRCAT, BUF, TEXTLABELS = 0x408DBD, 0x645470, 0x9B86A0, 0x9B90F8
CURRENT_BASE_ID, BASES, BASE_SIZE = 0x689370, 0x97D040, 0x134
SWITCH, TABLE, ROW_JOIN, AFTER = 0x408C94, 0x408E94, 0x408DAC, 0x408DC5
L_UNMOD, L_FAC, L_POLICE, L_SP, L_CAPTURED, L_STAPLED = 322, 323, 324, 327, 970, 971
TEXT = {L_UNMOD: "Unmodified", L_FAC: "Facilities", L_POLICE: "Police", L_SP: "Secret Projects",
        L_CAPTURED: "Captured Base", L_STAPLED: "Stapled Base"}
TH_FN = 0x14E10                                  # BaseWin_draw_psych_strcat in the 5.5 release (RVA)
TH_STRCMP, TH_STRNCAT, TH_SNPRINTF = 0x713C7320, 0x713C7348, 0x713CD410
TH_CONF_RBI, TH_CUR_ID_PTR, TH_BASES_PTR, TH_LABELS_PTR, TH_FMT = 0x713E6E58, 0x713E9F40, 0x713E5D60, 0x713E5CB0, 0x713E6480


def _code(text: str) -> str:
    return re.sub(r"//.*", "", text)


def _fn(code: str, signature: str) -> str:
    start = code.index(signature)
    return code[start:code.index("\n}\n", start)]


CODE = _code(PS)


# ---------------------------------------------------------------------------------------------- 1. the engine site
def _dis(img, va, n):
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    return list(md.disasm(img.rd(va, n), va))


def test_the_label_switch_routes_rows_0_1_2_4_to_the_site(bak_path):
    """Row 0 = 970 Captured / 971 Stapled / 322 Unmodified, rows 1, 2, 4 = 323, 324, 327: all join at 0x408DAC and end
    in the call at 0x408DBD; row 3 has its own call (0x408D94), which nobody hooks."""
    pytest.importorskip("capstone")
    img = T.Image(bak_path)
    rows = struct.unpack("<5I", img.rd(TABLE, 20))
    assert rows == (0x408CA7, 0x408CF6, 0x408D07, 0x408D17, 0x408DA1)
    ends = list(rows) + [0x408DA1]
    want = {0: [L_CAPTURED * 4, L_STAPLED * 4, L_UNMOD * 4], 1: [L_FAC * 4], 2: [L_POLICE * 4], 4: [L_SP * 4]}
    for row in (0, 1, 2):
        ins = _dis(img, rows[row], ends[row + 1] - rows[row])
        disp = [i.operands[1].mem.disp for i in ins if i.mnemonic == "mov" and len(i.operands) == 2
                and i.operands[1].type == 3 and i.operands[1].mem.base != 0 and 0x500 <= i.operands[1].mem.disp < 0x1000]
        assert disp == want[row], (row, [hex(d) for d in disp])
        assert [i.op_str for i in ins if i.mnemonic == "jmp"] == ["0x408dac"] * len(want[row])
    # row 0's choice, as the engine makes it: assimilation turns (+7) AND faction (+5) != former (+4) -> 970;
    # else staple turns (+8) -> 971; else 322
    r0 = " | ".join(f"{i.mnemonic} {i.op_str}" for i in _dis(img, rows[0], 0x4F))
    assert "mov cl, byte ptr [eax + 7] | test cl, cl | jbe 0x408cce | mov cl, byte ptr [eax + 5] | mov dl, byte ptr [eax + 4] | cmp cl, dl | je 0x408cce" in r0
    assert "mov cl, byte ptr [eax + 8] | test cl, cl | je 0x408ce5" in r0
    tail = " | ".join(f"{i.mnemonic} {i.op_str}" for i in _dis(img, 0x408DA1, AFTER - 0x408DA1))
    assert tail == ("mov eax, dword ptr [0x9b90f8] | mov eax, dword ptr [eax + 0x51c] | push eax | mov ecx, 0x9b90d8 | "
                    "call 0x6169a0 | push eax | push 0x9b86a0 | call 0x645470 | add esp, 8")
    # row 3 has its own append, and the row loop empties the buffer first (so strcat == the whole label)
    assert img.rd(0x408D94, 5) == b"\xE8" + struct.pack("<i", STRCAT - 0x408D99)
    assert img.rd(0x408C81, 7) == b"\xC6\x05" + struct.pack("<I", BUF) + b"\x00"


def test_nothing_reads_eax_after_the_call(bak_path):
    """Thinker's function returns void: the code after the call must not read eax before writing it."""
    pytest.importorskip("capstone")
    img = T.Image(bak_path)
    for i in _dis(img, AFTER, 0x20):
        if i.mnemonic == "call":
            break
        regs_read, regs_written = i.regs_access()
        names = {i.reg_name(r) for r in regs_read}
        assert not names & {"eax", "ax", "al"}, f"{i.mnemonic} {i.op_str}"


def test_crt_strcat_is_strcat(bak_path):
    """Measured, not assumed: the shipped exe's 0x645470 under Unicorn appends and returns dest."""
    pytest.importorskip("unicorn", reason="unicorn absent -- crt_strcat is unverified")
    import pefile
    from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
    from unicorn import x86_const as X
    pe = pefile.PE(str(bak_path), fast_load=True)
    uc = Uc(UC_ARCH_X86, UC_MODE_32)
    base = pe.OPTIONAL_HEADER.ImageBase
    for s in pe.sections:
        va = base + s.VirtualAddress
        size = (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF
        try:
            uc.mem_map(va & ~0xFFF, size)
        except Exception:
            pass
        uc.mem_write(va, s.get_data())
    uc.mem_map(0x30000000, 0x10000)
    for dest_text, src_text in [(b"", b"Secret Projects"), (b"ab", b"cd"), (b"x" * 7, b"y" * 13)]:
        dest, src, ret = 0x30001000, 0x30002003, 0x30008000
        uc.mem_write(dest, dest_text + b"\0" + b"\xEE" * 64)
        uc.mem_write(src, src_text + b"\0")
        sp = 0x3000F000
        uc.mem_write(sp, struct.pack("<III", ret, dest, src))
        uc.reg_write(X.UC_X86_REG_ESP, sp)
        uc.emu_start(STRCAT, ret, count=10000)
        assert uc.reg_read(X.UC_X86_REG_EAX) == dest
        out = bytes(uc.mem_read(dest, len(dest_text) + len(src_text) + 1))
        assert out == dest_text + src_text + b"\0"
        assert uc.reg_read(X.UC_X86_REG_ESP) == sp + 4, "cdecl: the caller cleans"


def test_our_bake_and_the_plain_exe_leave_the_site_alone(bak_path, baked_exe):
    img, baked = T.Image(bak_path), T.Image(baked_exe)
    for va, n in [(SWITCH, AFTER - SWITCH + 0x20), (TABLE, 20), (STRCAT, 0x40)]:
        assert baked.rd(va, n) == img.rd(va, n), hex(va)
    plain = bak_path.parent / "terranx.exe"
    if plain.exists():
        p = T.Image(plain)
        for va, n in [(SWITCH, AFTER - SWITCH + 0x20), (TABLE, 20), (STRCAT, 0x40)]:
            assert p.rd(va, n) == img.rd(va, n), hex(va)


def test_the_site_has_one_owner_in_our_tree():
    """No other uimod module, patch table or Thinker-site table touches 0x408DBD."""
    hits = []
    for f in list(UIMOD.glob("*.cpp")) + list(UIMOD.glob("*.h")) + list((ROOT / "patches").glob("*.yaml")):
        text = f.read_text(encoding="utf-8", errors="replace")
        if re.search(r"0x0*408DBD", _code(text) if f.suffix != ".yaml" else text, re.I):
            hits.append(f.name)
    assert hits == ["pssphere.cpp"]


# ---------------------------------------------------------------------------------------------- 2. Thinker
@pytest.fixture(scope="module")
def thinker(need_local) -> dict:
    src = need_local(T.THINKER_SRC / "patch.cpp", "the Thinker source clone (refs/thinker)").parent
    return T.load_thinker(src)


def test_thinker_writes_the_call_and_both_jumps_in_every_mode(thinker):
    for reduced in (True, False):
        known = T.forced_options(thinker.get("assigns", []), reduced)
        for kind, addr, target in [("write_call", SITE, "BaseWin_draw_psych_strcat"),
                                   ("write_jump", 0x4EB560, "mod_base_energy"), ("write_jump", 0x4EC3B0, "base_compute")]:
            w = [w for w in thinker["writes"] if w.kind == kind and w.addr == addr]
            assert len(w) == 1 and target in w[0].target, (kind, hex(addr))
            assert w[0].gating(reduced, known)[0] == "always", (kind, hex(addr), reduced)
        others = [w for w in thinker["writes"] if w.addr <= SITE < w.addr + max(1, w.length) and w.addr != SITE]
        assert others == []


def test_thinker_source_prints_what_the_squash_assumes(need_local):
    """The rule KeepOwn mirrors and the countdown it must leave alone, as Thinker 5.5's source states them."""
    src = need_local(T.THINKER_SRC / "basewin.cpp", "the Thinker source clone (refs/thinker)").read_text(encoding="utf-8")
    body = _fn(src, "void __cdecl BaseWin_draw_psych_strcat(char* buffer, char* source)")
    flat = " ".join(body.split())
    assert "if (conf.render_base_info && *CurrentBaseID >= 0) {" in flat
    assert "if (base->nerve_staple_turns_left > 0 || has_fac_built(FAC_PUNISHMENT_SPHERE, *CurrentBaseID)) {" in flat
    assert "if (!strcmp(source, label_get(971))) { // Stapled Base strncat(buffer, label_get(322), StrBufLen);" in flat
    assert "if (!strcmp(source, label_get(327))) { // Secret Projects strncat(buffer, label_get(971), StrBufLen);" in flat
    assert "if (turns > 0 && !strcmp(source, label_get(970))) { // Captured Base snprintf(buffer, StrBufLen, label_captured_base, turns);" in flat
    assert flat.rstrip().endswith("strncat(buffer, source, StrBufLen);")


@pytest.fixture(scope="module")
def th_dll(need_local):
    import pefile
    p = need_local(ROOT.parent / "refs" / "thinker-release" / "v5.5" / "thinker.dll", "the Thinker 5.5 release")
    pe = pefile.PE(str(p))
    return pe, bytes(pe.get_memory_mapped_image()), pe.OPTIONAL_HEADER.ImageBase


def test_the_release_binary_writes_this_call_to_this_function(th_dll):
    pe, img, base = th_dll
    v = (ROOT.parent / "src" / "uimod" / "src" / "version.h").read_text(encoding="utf-8")
    assert int(re.search(r"THINKER_SUPPORTED_STAMP (0x[0-9A-Fa-f]+)", v).group(1), 16) == pe.FILE_HEADER.TimeDateStamp
    # patch_setup: mov [esp+4], fn; mov [esp], 0x408DBD; call write_call
    store = b"\xC7\x44\x24\x04" + struct.pack("<I", base + TH_FN) + b"\xC7\x04\x24" + struct.pack("<I", SITE) + b"\xE8"
    assert img.count(store) == 1
    assert img.count(b"\xC7\x04\x24" + struct.pack("<I", SITE)) == 1, "no second write to the site"
    assert pe.OPTIONAL_HEADER.ImageBase <= base + TH_FN < base + pe.OPTIONAL_HEADER.SizeOfImage


def test_the_release_function_makes_the_tests_keepown_mirrors(th_dll):
    """Base: id >= 0, staple byte +8 != 0, else has_fac_built(23, id); labels 971 / 327 / 970 / 322; buffer limit 256;
    every engine pointer it reads is the engine's (CurrentBaseID, Bases, TextLabels)."""
    pytest.importorskip("capstone")
    import capstone
    _, img, base = th_dll
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    text = " | ".join(f"{i.mnemonic} {i.op_str}" for i in md.disasm(img[TH_FN:TH_FN + 0x12D], base + TH_FN))
    for needle in ["mov eax, dword ptr [0x713e9f40]", "mov edx, dword ptr [0x713e6e58]", "test edx, edx | je 0x71314e80",
                   "test eax, eax | js 0x71314e80", "imul esi, eax, 0x134 | add esi, dword ptr [0x713e5d60]",
                   "cmp byte ptr [esi + 8], 0 | jne 0x71314ea0", "mov dword ptr [esp], 0x17 | call 0x71308cb0",
                   "movzx esi, byte ptr [esi + 7]", "mov dword ptr [esp], 0x3ca", "mov dword ptr [esp], 0x3cb",
                   "mov dword ptr [esp], 0x147", "mov dword ptr [esp], 0x142", "mov dword ptr [esp + 8], 0x100"]:
        assert needle in text, needle
    rd = lambda va: struct.unpack_from("<I", img, va - base)[0]
    assert (rd(TH_CUR_ID_PTR), rd(TH_BASES_PTR), rd(TH_LABELS_PTR)) == (CURRENT_BASE_ID, BASES, TEXTLABELS)
    # has_fac_built: unsigned id <= 0x1FF, facility <= 0x40, Bases[id].facilities_built (+0x8C) bit
    hf = " | ".join(f"{i.mnemonic} {i.op_str}" for i in md.disasm(img[0x8CB0:0x8CF0], 0x71308CB0))
    assert "cmp eax, 0x1ff | ja 0x71308cc2" in hf and "imul eax, eax, 0x134" in hf and "movzx eax, byte ptr [eax + edx + 0x8c]" in hf


# ---------------------------------------------------------------------------------------------- 3. KeepOwn, native
@pytest.fixture(scope="module")
def keep_own():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    exe = cpp_harness.build(ROOT / "tests" / "pslabel_selftest.cpp", "pslabel_selftest_")

    def run(lines):
        out = subprocess.run([str(exe)], input="\n".join(lines) + "\n", capture_output=True, text=True, check=True,
                             timeout=60).stdout.split()
        assert len(out) == len(lines) and "bad" not in out, out
        return [x == "1" for x in out]
    run.exe = exe
    return run


@pytest.fixture(scope="module")
def keep_raw(keep_own):
    def run(lines):
        out = subprocess.run([str(keep_own.exe)], input="\n".join(lines) + "\n", capture_output=True, text=True,
                             check=True, timeout=60).stdout.split()
        assert len(out) == len(lines) and "bad" not in out, out
        return out
    return run


KINDS = {  # staple byte, sphere byte (facilities_built[2])
    "ordinary": (0, 0x00), "sphere": (0, 0x80), "staple": (3, 0x00), "staple 255": (255, 0x00),
    "sphere + staple": (2, 0x80), "other facilities": (0, 0x7F),
}
LABELS = [L_UNMOD, L_FAC, L_POLICE, L_SP, L_CAPTURED, L_STAPLED, 0, 1199]


def test_keepown_is_exactly_the_squash(keep_own):
    cases, want = [], []
    for kind, (staple, sphere) in KINDS.items():
        suppressed = staple != 0 or sphere & 0x80
        for lab in LABELS:
            for src in (str(lab), f"c{lab}"):            # the label's own pointer, and a copy of its text
                for bid in (0, 7, 511):
                    cases.append(f"{bid} {staple} {sphere} 1200 {src}")
                    want.append(bool(suppressed) and lab in (L_STAPLED, L_SP))
    assert keep_own(cases) == want


@pytest.mark.parametrize("line, why", [
    ("-1 3 128 1200 971", "no current base: Thinker's own call (it appends the label as is)"),
    ("512 3 128 1200 971", "id past the table: Thinker's to handle"),
    ("100000 3 128 1200 327", "id far past the table"),
    ("0 3 128 971 971", "label table shorter than 972: not loaded"),
    ("0 3 128 0 327", "empty label table"),
    ("0 3 128 1200 null", "no source text"),
    ("0 3 128 1200 x", "a text that is no label"),
])
def test_keepown_falls_back_to_thinker(keep_own, line, why):
    assert keep_own([line]) == [False], why


def _ref_target(b: bytes, at: int, op: int, lo: int, hi: int) -> int:
    if b[0] != op or lo >= hi:
        return 0
    t = (at + 5 + struct.unpack("<i", b[1:5])[0]) & 0xFFFFFFFF
    return t if lo <= t < hi else 0


def _target_line(b: bytes, at: int, op: int, lo: int, hi: int) -> str:
    return "target " + " ".join(f"{x:x}" for x in b) + f" {at:x} {op:x} {lo:x} {hi:x}"


def test_branch_target_is_the_rel32_decode_inside_the_range(keep_raw):
    import random
    rng = random.Random(0x408DBD)
    lo, hi = 0x71300000, 0x7149F000                      # thinker.dll 5.5's image
    cases = []
    for at, op in [(0x4EB560, 0xE9), (0x4EC3B0, 0xE9), (SITE, 0xE8)]:
        for t in (lo, lo + 1, base_fn := lo + TH_FN, hi - 1, hi, hi + 1, lo - 1, 0x10000000, 0x645470, at, at + 5, 0):
            rel = (t - at - 5) & 0xFFFFFFFF
            for opcode in (op, 0xE8 if op == 0xE9 else 0xE9, 0x55, 0x90):
                cases.append((bytes([opcode]) + struct.pack("<I", rel), at, op, lo, hi))
        cases.append((bytes([op]) + struct.pack("<I", 0), at, op, at + 5, at + 6))      # rel 0 lands on the next byte
        cases.append((bytes([op]) + struct.pack("<I", base_fn - at - 5), at, op, hi, lo))  # no range at all
        for _ in range(60):
            cases.append((bytes([op]) + struct.pack("<I", rng.getrandbits(32)), at, op, lo, hi))
    got = keep_raw([_target_line(*c) for c in cases])
    want = [f"{_ref_target(*c):x}" for c in cases]
    assert got == want
    assert sum(w != "0" for w in want) >= 12 and sum(w == "0" for w in want) > 100


def test_encode_branch_round_trips_and_matches_the_x86_rule(keep_raw):
    sites = [(0x4EB560, 0xE9, 0x10032F10), (0x4EC3B0, 0xE9, 0x10031000), (SITE, 0xE8, 0x10032F10), (SITE, 0xE8, 0x400000),
             (0x7FFFFFF0, 0xE9, 0x10)]
    got = keep_raw([f"encode {at:x} {op:x} {fn:x}" for at, op, fn in sites])
    for (at, op, fn), hexed in zip(sites, got):
        b = bytes.fromhex(hexed)
        assert b == bytes([op]) + struct.pack("<I", (fn - at - 5) & 0xFFFFFFFF), hex(at)
    # what Branch writes, ThinkerBranchTarget reads back
    back = keep_raw([_target_line(bytes.fromhex(h), at, op, 0, 0xFFFFFFFF) for (at, op, _), h in zip(sites, got)])
    assert back == [f"{fn:x}" for _, _, fn in sites]


# ---------------------------------------------------------------------------------------------- 4. the composition
class ThinkerFn:
    """Thinker 5.5's BaseWin_draw_psych_strcat from the release binary under Unicorn, with the engine memory it reads
    (CurrentBaseID, Bases, TextLabels, the label buffer) and its three CRT imports done in Python."""

    LBL, STACK, RET = 0x20000000, 0x30000000, 0x3000F000

    def __init__(self, img: bytes, base: int):
        from unicorn import UC_ARCH_X86, UC_HOOK_CODE, UC_MODE_32, Uc
        from unicorn import x86_const as X
        self.X = X
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        uc.mem_map(base, (len(img) + 0xFFF) & ~0xFFF)
        uc.mem_write(base, img)
        for va, size in [(0x689000, 0x1000), (0x97D000, 0x27000), (0x9B8000, 0x2000), (self.LBL, 0x10000),
                         (self.STACK, 0x10000)]:
            uc.mem_map(va, size)
        self.fn = base + TH_FN
        # labels: TextLabels {char** labels; count} -> a pointer table and the texts
        texts = {i: f"label {i}" for i in range(1200)}
        texts.update(TEXT)
        self.ptr = {}
        pool = self.LBL + 0x2000
        table = b""
        for i in range(1200):
            self.ptr[i] = pool
            data = texts[i].encode() + b"\0"
            uc.mem_write(pool, data)
            pool += len(data)
            table += struct.pack("<I", self.ptr[i])
        uc.mem_write(self.LBL, table[:0x2000])
        assert len(table) <= 0x2000 and pool < self.LBL + 0x10000
        uc.mem_write(TEXTLABELS, struct.pack("<II", self.LBL, 1200))
        self.text = texts
        for va, fn in [(TH_STRCMP, self._strcmp), (TH_STRNCAT, self._strncat), (TH_SNPRINTF, self._snprintf)]:
            uc.mem_write(va, b"\xC3")                     # the import thunk / mingw snprintf becomes a bare ret ...
            uc.hook_add(UC_HOOK_CODE, fn, begin=va, end=va)   # ... after the Python body runs
        self.calls = []

    def _cstr(self, va):
        out = bytearray()
        while True:
            b = bytes(self.uc.mem_read(va + len(out), 64))
            if b"\0" in b:
                return bytes(out + b[:b.index(b"\0")])
            out += b

    def _args(self, n):
        sp = self.uc.reg_read(self.X.UC_X86_REG_ESP)
        return struct.unpack("<%dI" % n, bytes(self.uc.mem_read(sp + 4, 4 * n)))

    def _strcmp(self, uc, *_):
        a, b = (self._cstr(p) for p in self._args(2))
        uc.reg_write(self.X.UC_X86_REG_EAX, ((a > b) - (a < b)) & 0xFFFFFFFF)
        self.calls.append("strcmp")

    def _strncat(self, uc, *_):
        dest, src, n = self._args(3)
        d = self._cstr(dest)
        uc.mem_write(dest + len(d), self._cstr(src)[:n] + b"\0")
        uc.reg_write(self.X.UC_X86_REG_EAX, dest)
        self.calls.append("strncat")

    def _snprintf(self, uc, *_):
        buf, n, fmt, a = self._args(4)
        f = self._cstr(fmt).decode()
        assert f.count("%") == 1 and "%d" in f, f
        out = f.replace("%d", str(struct.unpack("<i", struct.pack("<I", a))[0])).encode()[:n - 1]
        uc.mem_write(buf, out + b"\0")
        uc.reg_write(self.X.UC_X86_REG_EAX, len(out))
        self.calls.append("snprintf")

    def run(self, base_id: int, record: dict, label: int, render_base_info: int = 1) -> str:
        uc, X = self.uc, self.X
        uc.mem_write(BASES, b"\0" * (512 * BASE_SIZE))
        if 0 <= base_id < 512:
            r = bytearray(BASE_SIZE)
            for off, val in record.items():
                r[off] = val
            uc.mem_write(BASES + base_id * BASE_SIZE, bytes(r))
        uc.mem_write(CURRENT_BASE_ID, struct.pack("<i", base_id))
        uc.mem_write(TH_CONF_RBI, struct.pack("<i", render_base_info))
        uc.mem_write(BUF, b"\0" * 0x100)                  # the row loop empties it (0x408C81)
        sp = self.RET - 0x100
        uc.mem_write(sp, struct.pack("<III", self.RET, BUF, self.ptr[label]))
        uc.reg_write(X.UC_X86_REG_ESP, sp)
        for reg, val in [(X.UC_X86_REG_EBX, 0x11111111), (X.UC_X86_REG_ESI, 0x22222222), (X.UC_X86_REG_EDI, 0x33333333),
                         (X.UC_X86_REG_EBP, 0x44444444)]:
            uc.reg_write(reg, val)
        uc.emu_start(self.fn, self.RET, count=20000)
        assert uc.reg_read(X.UC_X86_REG_ESP) == sp + 4, "cdecl"
        for reg, val in [(X.UC_X86_REG_EBX, 0x11111111), (X.UC_X86_REG_ESI, 0x22222222), (X.UC_X86_REG_EDI, 0x33333333),
                         (X.UC_X86_REG_EBP, 0x44444444)]:
            assert uc.reg_read(reg) == val, "callee-saved"
        return self._cstr(BUF).decode()


@pytest.fixture(scope="module")
def thinker_fn(th_dll):
    pytest.importorskip("unicorn", reason="unicorn absent -- Thinker's function is unverified")
    _, img, base = th_dll
    t = ThinkerFn(img, base)
    assert t._cstr(TH_FMT) == b"Captured Base: %d turns", "label_captured_base, Thinker's default"
    return t


# (assimilation turns +7, former faction +4, faction +5, staple turns +8, facilities_built[2] +0x8E)
BASES_UNDER_TEST = {
    "ordinary": {4: 1, 5: 1},
    "captured": {7: 4, 4: 2, 5: 1},
    "captured, faction back with its founder": {7: 4, 4: 1, 5: 1},
    "sphere": {4: 1, 5: 1, 0x8E: 0x80},
    "staple": {4: 1, 5: 1, 8: 5},
    "captured + sphere": {7: 3, 4: 2, 5: 1, 0x8E: 0x80},
    "captured + staple": {7: 3, 4: 2, 5: 1, 8: 5},
    "captured + sphere + staple": {7: 9, 4: 2, 5: 1, 8: 1, 0x8E: 0x80},
    "sphere + staple": {4: 1, 5: 1, 8: 2, 0x8E: 0xFF},
    "other facilities only": {4: 1, 5: 1, 0x8E: 0x7F},
}


def _row0(rec: dict) -> int:
    """The engine's row-0 label (pinned above): captured beats stapled beats unmodified."""
    if rec.get(7, 0) > 0 and rec.get(5, 0) != rec.get(4, 0):
        return L_CAPTURED
    return L_STAPLED if rec.get(8, 0) else L_UNMOD


def _keep_line(base_id: int, rec: dict, label: int) -> str:
    return f"{base_id} {rec.get(8, 0)} {rec.get(0x8E, 0)} 1200 {label}"


def _expected(rec: dict, label: int, rbi: int) -> str:
    """What a player must see: every row its own label, except Thinker's captured countdown."""
    if rbi and label == L_CAPTURED and rec.get(7, 0) > 0:
        return f"Captured Base: {rec[7]} turns"
    return TEXT[label]


def test_the_composition_shows_own_labels_and_thinkers_countdown(thinker_fn, keep_own):
    cases = []
    for name, rec in BASES_UNDER_TEST.items():
        for bid in (0, 13, 511):
            for rbi in (1, 0):
                for label in (_row0(rec), L_FAC, L_POLICE, L_SP):
                    cases.append((name, bid, rec, label, rbi))
    keep = keep_own([_keep_line(bid, rec, label) for _, bid, rec, label, _ in cases])
    bad = []
    for (name, bid, rec, label, rbi), own in zip(cases, keep):
        got = TEXT[label] if own else thinker_fn.run(bid, rec, label, rbi)     # own = crt_strcat into the empty buffer
        if got != _expected(rec, label, rbi):
            bad.append((name, bid, label, rbi, got))
    assert bad == []


def test_the_countdown_is_back_on_every_captured_base(thinker_fn, keep_own):
    for name in ("captured", "captured + sphere", "captured + staple", "captured + sphere + staple"):
        rec = BASES_UNDER_TEST[name]
        assert _row0(rec) == L_CAPTURED
        assert keep_own([_keep_line(5, rec, L_CAPTURED)]) == [False], name
        assert thinker_fn.run(5, rec, L_CAPTURED) == f"Captured Base: {rec[7]} turns", name


def test_without_the_squash_thinker_relabels_so_the_squash_is_live(thinker_fn, keep_own):
    """The emulation is Thinker's real behaviour: on a sphere / stapled base it relabels both rows -- the text the
    squash exists to keep off row 4 -- and KeepOwn takes exactly those two calls away from it."""
    for name in ("sphere", "staple", "sphere + staple", "captured + sphere"):
        rec = BASES_UNDER_TEST[name]
        assert thinker_fn.run(9, rec, L_SP) == "Stapled Base", name
        assert thinker_fn.run(9, rec, L_STAPLED) == "Unmodified", name
        assert keep_own([_keep_line(9, rec, L_SP), _keep_line(9, rec, L_STAPLED)]) == [True, True], name
    assert thinker_fn.run(9, BASES_UNDER_TEST["sphere"], L_SP, render_base_info=0) == "Secret Projects"


def test_no_current_base_is_thinkers_plain_append(thinker_fn, keep_own):
    assert keep_own([_keep_line(-1, {8: 3, 0x8E: 0x80}, L_SP)]) == [False]
    assert thinker_fn.run(-1, {}, L_SP) == "Secret Projects"
    assert thinker_fn.run(-1, {}, L_CAPTURED) == "Captured Base"


# ---------------------------------------------------------------------------------------------- 5. the module
def test_every_chained_thinker_target_must_land_in_thinker_dll():
    body = _fn(CODE, "void ThinkerCheck(bool inGame)")
    assert "rel" not in body, "no branch operand is decoded outside ThinkerBranchTarget"
    for site, op in [("e", "0xE9"), ("c", "0xE9"), ("s", "0xE8")]:
        assert f"ThinkerBranchTarget({site}, {op})" in body, site
    helper = _fn(CODE, "BYTE* ThinkerBranchTarget(BYTE* p, BYTE opcode)")
    assert "if (p[0] != opcode || !ThinkerRange(&lo, &hi)) return nullptr;" in helper
    assert "return reinterpret_cast<BYTE*>(pslabel::BranchTarget(p, reinterpret_cast<uintptr_t>(p), opcode, lo, hi));" in helper
    branch = _fn(CODE, "void Branch(BYTE* p, BYTE opcode, const void* fn)")
    assert "pslabel::EncodeBranch(b, reinterpret_cast<uintptr_t>(p), opcode, reinterpret_cast<uintptr_t>(fn));" in branch
    assert "Patch(p, b, 5);" in branch
    assert CODE.count("ThinkerRange(") == 1, "the one range check is the helper's"
    # each chain stores Thinker's target and points its own site at its own wrapper (audit 2026-11-15: a self-loop or
    # a swapped wrapper crashes on the first base screen)
    flat = " ".join(body.split())
    for want in ["BYTE* energy = ThinkerBranchTarget(e, 0xE9); if (energy) { g_energyNext = reinterpret_cast<FVoid>(energy); "
                 "Branch(e, 0xE9, &WrapEnergy); BYTE* c = At(kVA_BaseCompute);",
                 "if (BYTE* compute = ThinkerBranchTarget(c, 0xE9)) { g_computeNext = reinterpret_cast<FInt>(compute); "
                 "Branch(c, 0xE9, &WrapBaseCompute);",
                 "if (BYTE* label = ThinkerBranchTarget(s, 0xE8)) { g_labelNext = reinterpret_cast<FLabel>(label); "
                 "Branch(s, 0xE8, &PsychLabelChain);"]:
        assert want in flat, want
    assert "BYTE* e = At(kVA_BaseEnergy);" in body and "BYTE* s = At(kVA_PsychLabelSite);" in body
    assert body.count("ThinkerBranchTarget(") == 3 and len(re.findall(r"(?<!Thinker)Branch\(", body)) == 3, "three lookups, three writes"
    # the label chain sits behind both jumps (its squash exists only while our would-be totals feed row 4)
    assert body.index("ThinkerBranchTarget(e, 0xE9)") < body.index("ThinkerBranchTarget(c, 0xE9)") < \
        body.index("ThinkerBranchTarget(s, 0xE8)")
    assert body.index("g_labelNext = reinterpret_cast<FLabel>(label);") < body.index("Branch(s, 0xE8, &PsychLabelChain);")
    assert "kVA_PsychLabelOrig" not in body, "the engine's strcat is never written back over Thinker's call"
    # plain PRACX: vanilla base_energy bytes leave without a write (looked at once more in game)
    vanilla = body[body.index("} else if (memcmp(e, kEnergyEntry, sizeof kEnergyEntry) == 0) {"):]
    assert vanilla.split("}", 1)[0].count("Branch(") == 0 and "if (!inGame) return;" in vanilla


def test_the_chain_calls_thinker_unless_keepown():
    body = _fn(CODE, "char* __cdecl PsychLabelChain(char* buffer, const char* source)")
    assert re.search(r"if \(pslabel::KeepOwn\(Rd<int>\(kVA_CurrentBaseID\), At\(kVA_Bases\), "
                     r"Rd<const char\* const\*>\(kVA_TextLabels\),\s*Rd<uint32_t>\(kVA_TextLabels \+ 4\), source\)\)", body)
    assert "return reinterpret_cast<FStrcat>(At(kVA_PsychLabelOrig))(buffer, source);" in body
    assert body.rstrip().endswith("g_labelNext(buffer, source);\n    return buffer;")
    for name, val in [("kVA_PsychLabelSite = 0x00408DBD", 1), ("kVA_PsychLabelOrig = 0x00645470", 1),
                      ("kVA_TextLabels     = 0x009B90F8", 1), ("kVA_CurrentBaseID  = 0x00689370", 1),
                      ("kVA_Bases          = 0x0097D040", 1)]:
        assert PS.count(name) == val, name


def test_the_chain_contract_and_the_check_lifecycle():
    """Second review 2026-11-15: mutations that no execution test reaches (a stdcall pointer, a lost guard, a check
    that never runs or runs forever, a short Patch) are pinned here."""
    # cdecl on both sides: the caller at 0x408DBD cleans 8 bytes (pinned above), Thinker's function is cdecl (pinned
    # in the release binary), the engine's strcat too
    assert "using FLabel = void(__cdecl*)(char*, const char*);" in CODE
    assert "using FStrcat = char*(__cdecl*)(char*, const char*);" in CODE
    assert "__stdcall" not in _fn(CODE, "char* __cdecl PsychLabelChain(char* buffer, const char* source)")
    body = _fn(CODE, "void ThinkerCheck(bool inGame)")
    assert body.split("\n")[2].strip() == "if (g_thinkerChecked || !g_installed) return;"
    assert body.count("g_thinkerChecked = true;") == 1 and CODE.count("g_thinkerChecked = false") == 1   # the declaration
    # the flag is set after every branch of the chain but the "vanilla so far, look again in game" return
    assert body.index("if (!inGame) return;") < body.index("g_thinkerChecked = true;")
    install = _fn(CODE, "void InstallPunishmentSphereView()")
    assert install.index("g_installed = true;") < install.index("ThinkerCheck(false);")
    for fn in ("void __cdecl PopEnter()", "void __cdecl OpsEnter()", "bool PsSphereWouldBePop("):
        assert "ThinkerCheck(true);" in _fn(CODE, fn), fn
    patch = _fn(CODE, "void Patch(BYTE* p, const BYTE* bytes, size_t n)")
    assert "memcpy(p, bytes, n);" in patch and "FlushInstructionCache(GetCurrentProcess(), p, n);" in patch
    assert "VirtualProtect(p, n, PAGE_EXECUTE_READWRITE, &old);" in patch


def test_an_unchained_psych_never_falls_back_to_the_engines():
    """A base_energy that is neither vanilla nor chained (a thinker.dll the startup check did not see): the draw-time
    would-be pass must not run the ENGINE's base_psych on that game (second review 2026-11-15)."""
    pick = _fn(CODE, "FVoid DrawTimePsych()")
    assert "if (g_energyNext) return g_energyNext;" in pick and "return g_energyForeign ? nullptr : g_psychTramp;" in pick
    assert CODE.count("g_energyForeign = true;") == 1
    body = _fn(CODE, "void ThinkerCheck(bool inGame)")
    neither = body[body.index("} else {", body.index("memcmp(e, kEnergyEntry")):]
    assert "g_energyForeign = true;" in neither.split("g_thinkerChecked = true;")[0]
    for fn in ("void __cdecl PopEnter()", "bool PsSphereWouldBePop("):
        f = _fn(CODE, fn)
        assert "FVoid next = DrawTimePsych();" in f and "g_psychTramp" not in f, fn
    assert CODE.count("g_psychTramp") == 4, "declared, the base_psych hook, DrawTimePsych, the install"


def test_keepown_offsets_are_the_modules():
    for core, mod in [("kBaseSize = 0x134", "kBaseSize = 0x134"), ("kBaseStaple = 0x08", "kBaseStaple = 0x08"),
                      ("kBaseSphereByte = 0x8E", "kBaseSphereByte = 0x8E"), ("kSphereBit = 0x80", "kSphereBit = 0x80"),
                      ("kMaxBases = 512", "kMaxBases = 512")]:
        assert core in CORE and mod in PS, core
    assert "kLabelStapledBase = 971" in CORE and "kLabelSecretProjects = 327" in CORE


def test_symbol_recorded():
    h = (ROOT / "symbols" / "terranx.h").read_text(encoding="utf-8")
    assert re.search(r"^extern char\* crt_strcat\(char\* dest, const char\* src\);\s+// addr: 0x00645470  observed", h, re.M)
