# Unicorn emulation check for the three F2 tech-header Frida caves (proto v8),
# per feedback-emulate-frida-stubs: verify every hand-assembled stub against the
# law (scaling_laws.scale_px) + the callee/return contract BEFORE arming.
#
# Cave_B1 @site 0x498C99 (clobbers 9 bytes: lea edi,[eax+0x46]; add eax,3; add ebx,0x43)
#   body: lea edi,[eax+S46]; add eax,S3; add ebx,S43; jmp 0x498CA2
# Cave_B2 @site 0x498CCF (clobbers 5 bytes: and eax,0x62; push 0)
#   body: and eax,S62; push 0; jmp 0x498CD4
# Cave_C  @site 0x498E43 (clobbers 6 bytes: push 0x40; push eax; mov eax,[ebp-0x34])
#   body: push S40; push eax; mov eax,[ebp-0x34]; jmp 0x498E49
import sys, struct
sys.path.insert(0, r"D:\SmacxUi\work\scripts")
from scaling_laws import scale_px
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_EDI,
                               UC_X86_REG_ESP, UC_X86_REG_EBP, UC_X86_REG_EIP)
import capstone

CAVE = 0x10000000
EXE_PAGE = 0x498000          # map the return-target page so the final jmp lands


def d32(v):
    return list(struct.pack("<i", v & 0xFFFFFFFF if v >= 0 else v))


def rel(from_end, to):
    return d32(to - from_end)


def build_b1(g):
    S46, S3, S43 = scale_px(0x46, g), scale_px(3, g), scale_px(0x43, g)
    body = [0x8D, 0xB8] + d32(S46) + [0x05] + d32(S3) + [0x81, 0xC3] + d32(S43)
    body += [0xE9] + rel(CAVE + len(body) + 5, 0x498CA2)
    return bytes(body), (S46, S3, S43)


def build_b2(g):
    S62 = scale_px(0x62, g)
    body = [0x25] + d32(S62) + [0x6A, 0x00]
    body += [0xE9] + rel(CAVE + len(body) + 5, 0x498CD4)
    return bytes(body), S62


def build_c(g):
    S40 = scale_px(0x40, g)
    body = [0x68] + d32(S40) + [0x50, 0x8B, 0x45, 0xCC]
    body += [0xE9] + rel(CAVE + len(body) + 5, 0x498E49)
    return bytes(body), S40


def run(code, setup, until, steps=64):
    mu = Uc(UC_ARCH_X86, UC_MODE_32)
    mu.mem_map(CAVE, 0x1000)
    mu.mem_map(EXE_PAGE, 0x2000)          # covers 0x498CA2/0x498CD4/0x498E49
    mu.mem_map(0x200000, 0x10000)         # stack + fake ebp frame
    mu.mem_write(CAVE, code)
    mu.reg_write(UC_X86_REG_ESP, 0x208000)
    setup(mu)
    mu.emu_start(CAVE, until, count=steps)
    return mu


def dis(code):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    return "; ".join(f"{i.mnemonic} {i.op_str}" for i in md.disasm(code, CAVE))


ok = True
for g in (17, 22, 25, 40):
    # --- B1 ---
    code, (S46, S3, S43) = build_b1(g)
    mu = run(code, lambda m: (m.reg_write(UC_X86_REG_EAX, 1000),
                              m.reg_write(UC_X86_REG_EBX, 2000),
                              m.reg_write(UC_X86_REG_EDI, 0xDEAD)), 0x498CA2)
    got = (mu.reg_read(UC_X86_REG_EDI), mu.reg_read(UC_X86_REG_EAX),
           mu.reg_read(UC_X86_REG_EBX), mu.reg_read(UC_X86_REG_EIP))
    want = (1000 + S46, 1000 + S3, 2000 + S43, 0x498CA2)
    if got != want:
        ok = False; print(f"B1 g={g} FAIL got={got} want={want}\n  {dis(code)}")
    else:
        print(f"B1 g={g} OK edi=+{S46} eax=+{S3} ebx=+{S43}")

    # --- B2: mask -1 and mask 0 ---
    code, S62 = build_b2(g)
    for mask, exp in ((0xFFFFFFFF, S62), (0, 0)):
        mu = run(code, lambda m: m.reg_write(UC_X86_REG_EAX, mask), 0x498CD4)
        eax = mu.reg_read(UC_X86_REG_EAX)
        esp = mu.reg_read(UC_X86_REG_ESP)
        top = struct.unpack("<I", mu.mem_read(esp, 4))[0]
        if (eax, top, mu.reg_read(UC_X86_REG_EIP)) != (exp, 0, 0x498CD4):
            ok = False; print(f"B2 g={g} mask={mask:#x} FAIL eax={eax} top={top}")
        else:
            print(f"B2 g={g} mask={mask:#x} OK eax={eax}")

    # --- C ---
    code, S40 = build_c(g)
    def setup_c(m):
        m.reg_write(UC_X86_REG_EAX, 55)
        m.reg_write(UC_X86_REG_EBP, 0x204000)
        m.mem_write(0x204000 - 0x34, struct.pack("<I", 777))
    mu = run(code, setup_c, 0x498E49)
    esp = mu.reg_read(UC_X86_REG_ESP)
    col = struct.unpack("<I", mu.mem_read(esp, 4))[0]
    num = struct.unpack("<I", mu.mem_read(esp + 4, 4))[0]
    eax = mu.reg_read(UC_X86_REG_EAX)
    if (col, num, eax, mu.reg_read(UC_X86_REG_EIP)) != (55, S40, 777, 0x498E49):
        ok = False; print(f"C g={g} FAIL col={col} num={num} eax={eax}")
    else:
        print(f"C g={g} OK num=s(64)={S40} col/y preserved")

print("ALL-OK" if ok else "FAILURES")
sys.exit(0 if ok else 1)
