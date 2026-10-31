import sys, struct, re, io
sys.path.insert(0, r"D:\SmacxUi\work\scripts")
from scaling_laws import scale_px
import config
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import *

# ---- pristine PE mapper ----
import os
bak = None
if not bak or not os.path.exists(bak):
    import glob
    cands = glob.glob(r"D:\GOG Galaxy\Games\Sid Meier's Alpha Centauri Planetary Pack\terranx_PRACX.exe.bak")
    bak = cands[0]
data = open(bak, "rb").read()
pe = struct.unpack_from("<I", data, 0x3c)[0]
nsec = struct.unpack_from("<H", data, pe + 6)[0]
opt = struct.unpack_from("<H", data, pe + 20)[0]
secs = []
for i in range(nsec):
    o = pe + 24 + opt + i * 40
    vs, va, rs, ro = struct.unpack_from("<IIII", data, o + 8)
    secs.append((0x400000 + va, vs, ro, rs))
def rb(va, n=1):
    for base, vs, ro, rs in secs:
        if base <= va < base + max(vs, rs):
            off = ro + (va - base)
            return data[off:off + n]
    raise KeyError(hex(va))

# ---- 1) guard-byte audit of every v9 poke (va, expected pristine byte) ----
src = io.open(r"D:\SmacxUi\work\scripts\hook_report_scale_proto.js", encoding="utf-8").read()
bad = 0; n = 0
for m in re.finditer(r"\b(?:P|pk8|poke8)\((0x[0-9a-f]+),\s*(0x[0-9a-f]+)", src):
    va, want = int(m.group(1), 16), int(m.group(2), 16)
    have = rb(va)[0]; n += 1
    if have != want:
        bad += 1; print("GUARD MISMATCH poke8 @%#x want %02x pristine %02x" % (va, want, have))
for m in re.finditer(r"\b(?:pk32|poke32)\((0x[0-9a-f]+),\s*(-?\d+|0x[0-9a-f]+)", src):
    va = int(m.group(1), 16); want = int(m.group(2), 0)
    have = struct.unpack("<i", rb(va, 4))[0]; n += 1
    if have != want:
        bad += 1; print("GUARD MISMATCH poke32 @%#x want %d pristine %d" % (va, want, have))
# explicit multi-byte guards
for va, want in [(0x4a75ff, b"\x83\xe0\x4c\x03\xc8"), (0x4a5b43, b"\x83\xc1\x46\x83\xc0\x46"),
                 (0x4a42e0, b"\x8b\x8e\xb0\x4f\x00\x00"), (0x4a42e6, b"\x8b\x96\xac\x4f\x00\x00"),
                 (0x4a43ba, b"\x8d\x51\x4b\x2b\xf9\xa3\x7c\xe0\x87\x00"), (0x5e2dd3, b"\x51\x53\x55\x56\x57"),
                 (0x4a461a, struct.pack("<I", 0x6e84b4)), (0x4a46d2, struct.pack("<I", 0x6e84b4)),
                 (0x498d06, b"\xc7\x45\xa0\x2f\x00\x00\x00"), (0x498d0d, b"\xc7\x45\xdc\x31\x00\x00\x00")]:
    n += 1
    if rb(va, len(want)) != want:
        bad += 1; print("GUARD MISMATCH bytes @%#x want %s pristine %s" % (va, want.hex(), rb(va, len(want)).hex()))
for site in [0x4a7df2, 0x4a7e31, 0x4a7f8f, 0x4a7fce, 0x4a812c, 0x4a816b, 0x4a82c8, 0x4a8307]:
    n += 1
    b = rb(site, 5); tgt = site + 5 + struct.unpack("<i", b[1:])[0]
    if b[0] != 0xe8 or tgt != 0x5e2dd3:
        bad += 1; print("BAR SITE MISMATCH @%#x -> %#x" % (site, tgt))
print("guard audit: %d sites, %d mismatches" % (n, bad))

# ---- 2) Unicorn: title-mask cave, crest cave, bar prologue cave ----
CAVE = 0x10000000
def d32(v): return list(struct.pack("<i", v))
def run(body, back, setup, until, extra_maps=()):
    code = bytes(body + [0xe9] + d32(back - (CAVE + len(body) + 5)))
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    mu.mem_map(CAVE, 0x1000); mu.mem_map(0x4a4000, 0x5000); mu.mem_map(0x5e2000, 0x1000); mu.mem_map(0x200000, 0x10000)
    mu.mem_write(CAVE, code); mu.reg_write(UC_X86_REG_ESP, 0x208000); setup(mu)
    mu.emu_start(CAVE, until, count=32); return mu
ok = True
for g in (17, 22, 25, 28, 40):
    S4c, S46 = scale_px(0x4c, g), scale_px(0x46, g)
    for mask, exp in ((0xffffffff, S4c), (0, 0)):
        mu = run([0x25] + d32(S4c) + [0x03, 0xc8], 0x4a7604,
                 lambda m: (m.reg_write(UC_X86_REG_EAX, mask), m.reg_write(UC_X86_REG_ECX, 500)), 0x4a7604)
        got = (mu.reg_read(UC_X86_REG_EAX), mu.reg_read(UC_X86_REG_ECX), mu.reg_read(UC_X86_REG_EIP))
        if got != (exp, 500 + exp, 0x4a7604): ok = False; print("TITLE g=%d mask=%#x FAIL %r" % (g, mask, got))
    mu = run([0x81, 0xc1] + d32(S46) + [0x05] + d32(S46), 0x4a5b49,
             lambda m: (m.reg_write(UC_X86_REG_ECX, 100), m.reg_write(UC_X86_REG_EAX, 200)), 0x4a5b49)
    got = (mu.reg_read(UC_X86_REG_ECX), mu.reg_read(UC_X86_REG_EAX), mu.reg_read(UC_X86_REG_EIP))
    if got != (100 + S46, 200 + S46, 0x4a5b49): ok = False; print("CREST g=%d FAIL %r" % (g, got))
    print("g=%d title s(0x4C)=%d crest s(0x46)=%d OK" % (g, S4c, S46))
# bar prologue replay: pushes ecx,ebx,ebp,esi,edi then lands at 0x5E2DD8 with esp-20
def st(m):
    for r, v in ((UC_X86_REG_ECX, 1), (UC_X86_REG_EBX, 2), (UC_X86_REG_EBP, 3), (UC_X86_REG_ESI, 4), (UC_X86_REG_EDI, 5)): m.reg_write(r, v)
mu = run([0x51, 0x53, 0x55, 0x56, 0x57], 0x5e2dd8, st, 0x5e2dd8)
esp = mu.reg_read(UC_X86_REG_ESP)
stack = struct.unpack("<5I", mu.mem_read(esp, 20))
if stack != (5, 4, 3, 2, 1) or esp != 0x208000 - 20 or mu.reg_read(UC_X86_REG_EIP) != 0x5e2dd8: ok = False; print("BARCAVE FAIL", stack, hex(esp))
else: print("BARCAVE prologue replay OK (edi,esi,ebp,ebx,ecx on stack, resumes 0x5E2DD8)")
print("ALL-OK" if ok and bad == 0 else "FAILURES")
