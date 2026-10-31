import sys, struct
sys.path.insert(0, r"D:\SmacxUi\work\scripts")
from scaling_laws import scale_px
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import *
CAVE=0x10000000
def d32(v): return list(struct.pack("<i", v))
ok=True
for g in (17,22,25,28,40):
    S=scale_px(0x4b,g)
    body=[0x8d,0x91]+d32(S)+[0x2b,0xf9]+[0xa3,0x7c,0xe0,0x87,0x00]
    body+=[0xe9]+d32(0x4a43c4-(CAVE+len(body)+5))
    mu=Uc(UC_ARCH_X86,UC_MODE_32); mu.mem_map(CAVE,0x1000); mu.mem_map(0x4a4000,0x1000); mu.mem_map(0x87e000,0x1000); mu.mem_map(0x200000,0x10000)
    mu.mem_write(CAVE,bytes(body)); mu.reg_write(UC_X86_REG_ESP,0x208000)
    mu.reg_write(UC_X86_REG_ECX,65); mu.reg_write(UC_X86_REG_EDI,1675); mu.reg_write(UC_X86_REG_EAX,1300)
    mu.emu_start(CAVE,0x4a43c4,count=16)
    edx=mu.reg_read(UC_X86_REG_EDX); edi=mu.reg_read(UC_X86_REG_EDI); st=struct.unpack("<I",mu.mem_read(0x87e07c,4))[0]
    want=(65+S,1675-65,1300,0x4a43c4)
    got=(edx,edi,st,mu.reg_read(UC_X86_REG_EIP))
    print("g=%d s(0x4B)=%d"%(g,S), "OK" if got==want else "FAIL %r want %r"%(got,want)); ok&=got==want
print("ALL-OK" if ok else "FAILURES")
