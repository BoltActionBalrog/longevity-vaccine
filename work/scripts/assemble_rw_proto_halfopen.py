# Half-open call-helper for the ReportWin show-path frame draws (proto v9.8).
# Entered by E8 (call-helper contract, feedback-thunk-call-vs-detour): [esp]=ret, [esp+4]=rect ptr,
# [esp+8]=params, ecx=dest. Decrements rect.R/rect.B by 1 IN PLACE for the thick renderer (which covers
# the rect inclusively), calls the renderer with re-pushed args (RET 8), restores R/B, RET 8.
# ebx preserved (live in the caller), ecx passed through untouched, eax/edx dead after the call.
import struct, sys
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import *
def src(target):
    return f"""
push ebx
mov ebx, dword ptr [esp+8]
dec dword ptr [ebx+8]
dec dword ptr [ebx+0xC]
push dword ptr [esp+0xC]
push ebx
mov eax, {target:#x}
call eax
inc dword ptr [ebx+8]
inc dword ptr [ebx+0xC]
pop ebx
ret 8
"""
ks = Ks(KS_ARCH_X86, KS_MODE_32)
HF, DF = 0xA0C140, 0xA102A0
hf, _ = ks.asm(src(HF), 0x10000000); df, _ = ks.asm(src(DF), 0x10000000)
hf, df = bytes(hf), bytes(df)
assert bytes(ks.asm(src(HF), 0x20000000)[0]) == hf
ok = True
for code, target in ((hf, HF), (df, DF)):
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for b, n in ((0x10000000, 0x1000), (0xA0C000, 0x1000), (0xA10000, 0x1000), (0x200000, 0x10000), (0x300000, 0x1000)): mu.mem_map(b, n)
    mu.mem_write(0x10000000, code)
    # renderer stub: record ecx, [esp+4] rect ptr, [esp+8] params and the rect contents; ret 8
    stub = b"\x89\x0d\x00\x00\x30\x00" + b"\x8b\x44\x24\x04\xa3\x04\x00\x30\x00" + b"\x8b\x44\x24\x08\xa3\x08\x00\x30\x00" \
         + b"\x8b\x44\x24\x04\x8b\x40\x08\xa3\x0c\x00\x30\x00" + b"\x8b\x44\x24\x04\x8b\x40\x0c\xa3\x10\x00\x30\x00" + b"\xc2\x08\x00"
    mu.mem_write(target, stub)
    rect = 0x300100; mu.mem_write(rect, struct.pack("<iiii", 100, 200, 700, 260))
    esp = 0x208000 - 12
    mu.mem_write(esp, struct.pack("<III", 0x496CD5, rect, 0x78D5A0))   # ret, rect, params (as after the E8)
    mu.reg_write(UC_X86_REG_ESP, esp); mu.reg_write(UC_X86_REG_ECX, 0x8768BC); mu.reg_write(UC_X86_REG_EBX, 7)
    mu.emu_start(0x10000000, 0x496CD5, count=64)
    got_ecx, got_rect, got_params, got_R, got_B = struct.unpack("<IIIii", mu.mem_read(0x300000, 20))
    after = struct.unpack("<iiii", mu.mem_read(rect, 16))
    cond = (got_ecx == 0x8768BC and got_rect == rect and got_params == 0x78D5A0 and (got_R, got_B) == (699, 259)
            and after == (100, 200, 700, 260) and mu.reg_read(UC_X86_REG_EBX) == 7 and mu.reg_read(UC_X86_REG_ESP) == 0x208000
            and mu.reg_read(UC_X86_REG_EIP) == 0x496CD5)
    ok &= cond
    print(("OK  " if cond else "FAIL") + " target %#x: renderer saw R/B=%d/%d, rect restored=%s, ebx=%d, esp clean=%s" %
          (target, got_R, got_B, after, mu.reg_read(UC_X86_REG_EBX), mu.reg_read(UC_X86_REG_ESP) == 0x208000))
print("HF(%dB)=%s" % (len(hf), hf.hex())); print("DF(%dB)=%s" % (len(df), df.hex()))
print("ALL-OK" if ok else "FAILURES"); sys.exit(0 if ok else 1)
