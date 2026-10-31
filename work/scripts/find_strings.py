import sys, struct, os
sys.path.insert(0, os.path.dirname(__file__))
from config import terranx  # type: ignore

exe = str(terranx())
data = open(exe, "rb").read()
print("EXE", exe, "size", len(data))

# PE section table -> map file offset to VA
pe = data.find(b"PE\0\0")
num_sec = struct.unpack_from("<H", data, pe+6)[0]
opt_sz = struct.unpack_from("<H", data, pe+20)[0]
img_base = struct.unpack_from("<I", data, pe+24+28)[0]
sec_off = pe+24+opt_sz
secs=[]
for i in range(num_sec):
    o=sec_off+i*40
    name=data[o:o+8].rstrip(b"\0").decode("latin1")
    vsize,va,rsize,roff=struct.unpack_from("<IIII", data, o+8)
    secs.append((name,va,vsize,roff,rsize))

def off_to_va(off):
    for name,va,vsize,roff,rsize in secs:
        if roff <= off < roff+rsize:
            return img_base+va+(off-roff)
    return None

for s in [b"NO CONTACTS", b"CONTACTS", b"VOTES", b"Council", b"COUNCIL", b"Commlink", b"COMMLINK"]:
    hits=[]
    i=data.find(s)
    while i!=-1 and len(hits)<6:
        hits.append((i, off_to_va(i)))
        i=data.find(s, i+1)
    print(s.decode(), "->", [(hex(o), hex(va) if va else None) for o,va in hits])
