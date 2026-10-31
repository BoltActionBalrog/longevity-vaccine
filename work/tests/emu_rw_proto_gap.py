import sys, struct
sys.path.insert(0, r"D:\SmacxUi\work\scripts")
from scaling_laws import scale_px
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import *
CAVE=0x10000000
def d32(v): return list(struct.pack("<i", v))
def run(body, back, setup, until):
    code=bytes(body+[0xe9]+d32(back-(CAVE+len(body)+5)))
    mu=Uc(UC_ARCH_X86,UC_MODE_32); mu.mem_map(CAVE,0x1000); mu.mem_map(0x4a4000,0x1000); mu.mem_map(0x885000,0x21000); mu.mem_map(0x200000,0x10000)
    mu.mem_write(CAVE,code); mu.reg_write(UC_X86_REG_ESP,0x208000); setup(mu); mu.emu_start(CAVE,until,count=16); return mu
ok=True
for g in (17,22,25,40):
    gap=scale_px(2,g); a=gap>>1; b=gap-a
    def st(m): m.reg_write(UC_X86_REG_EAX,900); m.reg_write(UC_X86_REG_EDX,400); m.reg_write(UC_X86_REG_ESI,0x885f38); m.reg_write(UC_X86_REG_EDI,700); m.reg_write(UC_X86_REG_ECX,55)
    mu=run([0x2b,0xc2,0x89,0x96,0xc8,0xe1,0x01,0x00,0x2d]+d32(a),0x4a4421,st,0x4a4421)
    got=(mu.reg_read(UC_X86_REG_EAX), struct.unpack("<I",mu.mem_read(0x885f38+0x1e1c8,4))[0], mu.reg_read(UC_X86_REG_EIP))
    if got!=(900-400-a,400,0x4a4421): ok=False; print("G1 FAIL",g,got)
    mu=run([0x2b,0xc2,0x2d]+d32(b)+[0x81,0xc7]+d32(b)+[0x89,0x8e,0xcc,0xe1,0x01,0x00],0x4a44de,st,0x4a44de)
    got=(mu.reg_read(UC_X86_REG_EAX), mu.reg_read(UC_X86_REG_EDI), struct.unpack("<I",mu.mem_read(0x885f38+0x1e1cc,4))[0], mu.reg_read(UC_X86_REG_EIP))
    if got!=(900-400-b,700+b,55,0x4a44de): ok=False; print("G2 FAIL",g,got)
    print("g=%d gap=%d (a=%d b=%d) OK"%(g,gap,a,b))
print("ALL-OK" if ok else "FAILURES")
