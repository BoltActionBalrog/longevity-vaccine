"""E8/E9 (rel32) call/jmp sites in the PRISTINE .bak whose target is one of the given VAs.
Usage: py _callers.py 0x43E9A0 [0x...]   (optionally  --range 0xLO 0xHI  to restrict the scan)"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(__file__))
import config, pefile
pe = pefile.PE(str(config.terranx_bak(required=True)), fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
text = next(s for s in pe.sections if s.Name.startswith(b".text"))
data = text.get_data(); va0 = base + text.VirtualAddress
args = sys.argv[1:]
lo, hi = va0, va0 + len(data)
if "--range" in args:
    i = args.index("--range"); lo, hi = int(args[i + 1], 16), int(args[i + 2], 16); del args[i:i + 3]
targets = {int(a, 16) for a in args}
for t in sorted(targets):
    hits = []
    for i in range(max(0, lo - va0), min(len(data) - 5, hi - va0)):
        op = data[i]
        if op != 0xE8 and op != 0xE9:
            continue
        rel = struct.unpack_from("<i", data, i + 1)[0]
        if (va0 + i + 5 + rel) & 0xFFFFFFFF == t:
            hits.append((va0 + i, "call" if op == 0xE8 else "jmp"))
    print(f"{t:#010x}: {len(hits)} sites: " + " ".join(f"{k}@{a:#x}" for a, k in hits))
