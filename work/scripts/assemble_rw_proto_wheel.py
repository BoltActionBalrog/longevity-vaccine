# Report-screen wheel caves (proto v9.2): position-independent bytes chained IN FRONT of the baked
# t_dl_wheel_down/up at the WinProc sites 0x5F07B0 / 0x5F07F0. Mirrors assemble_dw.py asm_wheel /
# assemble_dl.py asm_dl_wheel_* exactly (same gates, same chevron press + present), with the report's
# own gate: basepop==0, modal top == ReportWin, kind==2, captured list bar non-null.
# External targets use absolute forms (mov eax,imm; call eax / push imm; ret) so the bytes are
# valid at any cave address; the two data cells are placeholders patched by the JS.
import struct, sys
from keystone import Ks, KS_ARCH_X86, KS_MODE_32
import ks_guard  # noqa: E402,F401  (keystone hex-misread guard, see ks_guard.py)
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import *

GET_TARGET, CHEVRON, MODAL_TOP, BASEPOP = 0x005F6A50, 0x00606B20, 0x009B7AE0, 0x009B8D7C
KIND, REPORTWIN = 0x885F40, 0x876478
DL_DOWN, DL_UP = 0xA2F0B0, 0xA2F210
CELL_SB, CELL_PARENT = 0x11111111, 0x22222222

DOWN = f"""
cmp dword ptr [{BASEPOP:#x}], 0
jne chain
cmp dword ptr [{MODAL_TOP:#x}], {REPORTWIN:#x}
jne chain
cmp dword ptr [{KIND:#x}], 2
jne chain
mov eax, dword ptr [{CELL_SB:#x}]
test eax, eax
jz chain
mov eax, {GET_TARGET:#x}
call eax
test eax, eax
jz xout
cmp dword ptr [esp+0x6C], 0
jne xout
mov edx, dword ptr [esp+0x68]
cmp edx, 0x26
je go
cmp edx, 0x28
jne xout
go:
push ebx
push esi
push edi
mov edi, dword ptr [{CELL_SB:#x}]
cmp dword ptr [edi+0xC4], 0
je restore
mov ecx, dword ptr [edi+0xA24]
cmp ecx, dword ptr [edi+0xA20]
jle restore
mov ebx, 1
cmp edx, 0x26
je press
mov ebx, 2
press:
push ebx
mov ecx, edi
mov eax, {CHEVRON:#x}
call eax
mov esi, dword ptr [{CELL_PARENT:#x}]
mov edx, dword ptr [esi]
mov ecx, esi
call dword ptr [edx+0xFC]
xor eax, eax
pop edi
pop esi
pop ebx
ret
restore:
pop edi
pop esi
pop ebx
xout:
ret
chain:
push {DL_DOWN:#x}
ret
"""
UP = f"""
cmp dword ptr [{BASEPOP:#x}], 0
jne chain
cmp dword ptr [{MODAL_TOP:#x}], {REPORTWIN:#x}
jne chain
cmp dword ptr [{KIND:#x}], 2
jne chain
mov eax, dword ptr [{CELL_SB:#x}]
test eax, eax
jz chain
mov eax, {GET_TARGET:#x}
call eax
test eax, eax
jz xout
cmp dword ptr [esp+0x6C], 0
jne xout
mov edx, dword ptr [esp+0x68]
cmp edx, 0x26
je eat
cmp edx, 0x28
jne xout
eat:
xor eax, eax
xout:
ret
chain:
push {DL_UP:#x}
ret
"""
ks = Ks(KS_ARCH_X86, KS_MODE_32)
down, _ = ks.asm(DOWN, 0x10000000); up, _ = ks.asm(UP, 0x10000000)
down, up = bytes(down), bytes(up)
# position independence: re-assemble at another base and compare
d2, _ = ks.asm(DOWN, 0x20000000); u2, _ = ks.asm(UP, 0x20000000)
assert bytes(d2) == down and bytes(u2) == up, "NOT position independent"
assert down.count(struct.pack("<I", CELL_SB)) == 2 and down.count(struct.pack("<I", CELL_PARENT)) == 1
assert up.count(struct.pack("<I", CELL_SB)) == 1

# ---- Unicorn: stub GET_TARGET (returns 1) and CHEVRON (records ecx + arg, RET 4), a parent vtbl+0xFC stub ----
def run(code, setup, steps=200):
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    for base, size in ((0x10000000, 0x1000), (0x5F6000, 0x1000), (0x606000, 0x1000), (0x9B7000, 0x2000), (0x885000, 0x1000),
                       (0x11111000, 0x1000), (0x22222000, 0x1000), (0x30000000, 0x4000), (0xA2F000, 0x1000), (0x200000, 0x10000), (0x40000000, 0x1000)):
        mu.mem_map(base, size)
    mu.mem_write(0x10000000, code)
    mu.mem_write(GET_TARGET, b"\xb8\x01\x00\x00\x00\xc3")                       # mov eax,1; ret
    mu.mem_write(CHEVRON, b"\xa3\x00\x00\x00\x40\x8b\x44\x24\x04\xa3\x04\x00\x00\x40\xc2\x04\x00")   # [0x40000000]=ecx? (eax) — see below
    # CHEVRON stub: mov [0x40000000],eax is wrong reg; use: mov [0x40000000],ecx ; mov eax,[esp+4]; mov [0x40000004],eax ; ret 4
    mu.mem_write(CHEVRON, b"\x89\x0d\x00\x00\x00\x40\x8b\x44\x24\x04\xa3\x04\x00\x00\x40\xc2\x04\x00")
    mu.mem_write(DL_DOWN, b"\xb8\x77\x00\x00\x00\xc3"); mu.mem_write(DL_UP, b"\xb8\x77\x00\x00\x00\xc3")   # chain stubs: eax=0x77
    # parent window at 0x30000000 with vtbl at 0x30001000, slot +0xFC -> present stub at 0x30002000: mov [0x40000008],ecx; ret
    mu.mem_write(0x30000000, struct.pack("<I", 0x30001000)); mu.mem_write(0x30001000 + 0xFC, struct.pack("<I", 0x30002000))
    mu.mem_write(0x30002000, b"\x89\x0d\x08\x00\x00\x40\xc3")
    # sb object at 0x30002800: +0xC4 engaged, +0xA20 min, +0xA24 max
    mu.reg_write(UC_X86_REG_ESP, 0x208000)
    # simulate an E8 entry from the site: push a return address, and the site's frame contents [esp+0x68]=VK, [esp+0x6C]=scan
    mu.mem_write(0x208000 - 4, struct.pack("<I", 0x5F07B5)); mu.reg_write(UC_X86_REG_ESP, 0x208000 - 4)
    setup(mu)
    mu.emu_start(0x10000000, 0x5F07B5, count=steps)
    return mu
def frame(mu, vk, scan): mu.mem_write(0x208000 - 4 + 0x68, struct.pack("<II", vk, scan))
def gates(mu, basepop=0, top=REPORTWIN, kind=2, sb=0x30002800, parent=0x30000000, engaged=1, mn=0, mx=5):
    mu.mem_write(BASEPOP, struct.pack("<I", basepop)); mu.mem_write(MODAL_TOP, struct.pack("<I", top)); mu.mem_write(KIND, struct.pack("<I", kind))
    mu.mem_write(CELL_SB, struct.pack("<I", sb)); mu.mem_write(CELL_PARENT, struct.pack("<I", parent))
    if sb: mu.mem_write(sb + 0xC4, struct.pack("<I", engaged)); mu.mem_write(sb + 0xA20, struct.pack("<II", mn, mx))
def rec(mu): return struct.unpack("<III", mu.mem_read(0x40000000, 12))
ok = True
def chk(name, cond):
    global ok
    print(("OK   " if cond else "FAIL ") + name); ok &= cond
# 1 wheel down (VK_DOWN synthetic) -> chevron(sb, 2), present(parent), eax=0
mu = run(down, lambda m: (gates(m), frame(m, 0x28, 0))); chk("down: press 2 + present, eax=0", rec(mu) == (0x30002800, 2, 0x30000000) and mu.reg_read(UC_X86_REG_EAX) == 0 and mu.reg_read(UC_X86_REG_ESP) == 0x208000)
mu = run(down, lambda m: (gates(m), frame(m, 0x26, 0))); chk("up-notch: press 1", rec(mu)[1] == 1)
mu = run(down, lambda m: (gates(m), frame(m, 0x28, 0x50))); chk("real key (scan!=0): passthrough eax=1, no press", rec(mu) == (0, 0, 0) and mu.reg_read(UC_X86_REG_EAX) == 1)
mu = run(down, lambda m: (gates(m, engaged=0), frame(m, 0x28, 0))); chk("bar not engaged: passthrough", rec(mu) == (0, 0, 0) and mu.reg_read(UC_X86_REG_EAX) == 1)
mu = run(down, lambda m: (gates(m, mn=3, mx=3), frame(m, 0x28, 0))); chk("range empty: passthrough", rec(mu) == (0, 0, 0))
mu = run(down, lambda m: (gates(m, kind=4), frame(m, 0x28, 0))); chk("other kind: chained to t_dl_wheel_down (eax=0x77)", mu.reg_read(UC_X86_REG_EAX) == 0x77 and mu.reg_read(UC_X86_REG_ESP) == 0x208000)
mu = run(down, lambda m: (gates(m, top=0x123), frame(m, 0x28, 0))); chk("not report modal: chained", mu.reg_read(UC_X86_REG_EAX) == 0x77)
mu = run(down, lambda m: (gates(m, sb=0), frame(m, 0x28, 0))); chk("no captured bar: chained", mu.reg_read(UC_X86_REG_EAX) == 0x77)
mu = run(down, lambda m: (gates(m, basepop=5), frame(m, 0x28, 0))); chk("basepop up: chained", mu.reg_read(UC_X86_REG_EAX) == 0x77)
mu = run(up, lambda m: (gates(m), frame(m, 0x28, 0))); chk("keyup synthetic: eaten eax=0", mu.reg_read(UC_X86_REG_EAX) == 0 and mu.reg_read(UC_X86_REG_ESP) == 0x208000)
mu = run(up, lambda m: (gates(m), frame(m, 0x28, 1))); chk("keyup real: passthrough eax=1", mu.reg_read(UC_X86_REG_EAX) == 1)
mu = run(up, lambda m: (gates(m, kind=3), frame(m, 0x28, 0))); chk("keyup other kind: chained", mu.reg_read(UC_X86_REG_EAX) == 0x77)
print("DOWN(%dB)=%s" % (len(down), down.hex()))
print("UP(%dB)=%s" % (len(up), up.hex()))
print("ALL-OK" if ok else "FAILURES"); sys.exit(0 if ok else 1)
