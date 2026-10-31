"""Parse a WER minidump: exception record, x86 context, and a raw stack scan
for in-module return addresses. Usage: parse_minidump.py <dump> [nwords]"""
import struct, sys

data = open(sys.argv[1], "rb").read()
nwords = int(sys.argv[2]) if len(sys.argv) > 2 else 96

sig, ver, nstreams, dirrva = struct.unpack_from("<IIII", data, 0)
assert sig == 0x504D444D, "not a minidump"

streams = {}
for i in range(nstreams):
    st, sz, rva = struct.unpack_from("<III", data, dirrva + 12 * i)
    streams.setdefault(st, []).append((sz, rva))

# Exception stream (6)
sz, rva = streams[6][0]
tid, _align = struct.unpack_from("<II", data, rva)
code, flags = struct.unpack_from("<II", data, rva + 8)
exaddr, = struct.unpack_from("<Q", data, rva + 8 + 16)
nparams, = struct.unpack_from("<I", data, rva + 8 + 24)
params = struct.unpack_from("<15Q", data, rva + 8 + 32)
ctx_sz, ctx_rva = struct.unpack_from("<II", data, rva + 8 + 152)
print(f"thread {tid}  exception 0x{code:08X} @ 0x{exaddr:08X}  params={[hex(p) for p in params[:nparams]]}")

c = ctx_rva
regs = struct.unpack_from("<6I", data, c + 0x9C)   # edi esi ebx edx ecx eax
ebp, eip = struct.unpack_from("<II", data, c + 0xB4)
esp, = struct.unpack_from("<I", data, c + 0xC4)
efl, = struct.unpack_from("<I", data, c + 0xC0)
print(f"eip=0x{eip:08X} esp=0x{esp:08X} ebp=0x{ebp:08X} efl=0x{efl:08X}")
print(f"edi=0x{regs[0]:08X} esi=0x{regs[1]:08X} ebx=0x{regs[2]:08X} edx=0x{regs[3]:08X} ecx=0x{regs[4]:08X} eax=0x{regs[5]:08X}")

# memory list (5): find the stack region and dump return-addr candidates
def read_mem(addr, size):
    for lst in streams.get(5, []):
        n, = struct.unpack_from("<I", data, lst[1])
        for i in range(n):
            start, dsz, drva = struct.unpack_from("<QII", data, lst[1] + 4 + 16 * i)
            if start <= addr < start + dsz:
                off = addr - start
                return data[drva + off: drva + min(off + size, dsz)]
    return b""

stack = read_mem(esp, nwords * 4)
print(f"\nstack @0x{esp:08X} ({len(stack)} bytes):")
for i in range(0, len(stack) - 3, 4):
    v, = struct.unpack_from("<I", stack, i)
    tag = ""
    if 0x401000 <= v < 0x664000: tag = "  <- .text"
    elif 0x668200 <= v < 0x669000: tag = "  <- menu_strip cave"
    elif 0xA0C000 <= v < 0xA1A000: tag = "  <- pcave2"  # keep in sync with the pcave2 length in patches.yaml (0xE000 as of 2026-07-25d)
    elif 0x10000000 <= v < 0x10080000: tag = "  <- prax.dll?"
    if tag or i < 0x40:
        print(f"  esp+0x{i:03X}: 0x{v:08X}{tag}")
