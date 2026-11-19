r"""A minimal reader for an MSVC PDB (MSF 7.00): the procedures and data symbols of chosen compilands, as virtual
addresses in the linked image. Enough to locate uimod.dll's compiled C functions and their globals for the Unicorn
tests (test_artillery_101_exec.py); no third-party PDB library is needed.

Format: https://llvm.org/docs/PDB/ (MSF, DBI stream, module info, CodeView symbol records).
"""
from __future__ import annotations

import struct
from pathlib import Path

_MAGIC = b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\x00\x00\x00"
S_LDATA32, S_GDATA32, S_LPROC32, S_GPROC32 = 0x110C, 0x110D, 0x110F, 0x1110
S_LPROC32_ID, S_GPROC32_ID, S_PUB32 = 0x1146, 0x1147, 0x110E
_PROCS = (S_LPROC32, S_GPROC32, S_LPROC32_ID, S_GPROC32_ID)
_DATA = (S_LDATA32, S_GDATA32)


class Pdb:
    def __init__(self, path: Path):
        self.raw = Path(path).read_bytes()
        if not self.raw.startswith(_MAGIC):
            raise ValueError(f"{path}: not an MSF 7.00 PDB")
        bs, _fpm, _nblocks, dir_bytes, _unk, map_addr = struct.unpack_from("<6I", self.raw, len(_MAGIC))
        self.bs = bs
        nblk = (dir_bytes + bs - 1) // bs
        dir_blocks = struct.unpack_from(f"<{nblk}I", self.raw, map_addr * bs)
        d = b"".join(self._block(b) for b in dir_blocks)[:dir_bytes]
        n = struct.unpack_from("<I", d, 0)[0]
        sizes = struct.unpack_from(f"<{n}I", d, 4)
        off = 4 + 4 * n
        self.streams: list[tuple[int, tuple[int, ...]]] = []
        for size in sizes:
            if size == 0xFFFFFFFF:
                size = 0
            k = (size + bs - 1) // bs
            self.streams.append((size, struct.unpack_from(f"<{k}I", d, off)))
            off += 4 * k

    def _block(self, b: int) -> bytes:
        return self.raw[b * self.bs:(b + 1) * self.bs]

    def stream(self, i: int) -> bytes:
        size, blocks = self.streams[i]
        return b"".join(self._block(b) for b in blocks)[:size]

    def modules(self) -> list[tuple[str, int, int]]:
        """(object file name, symbol stream index, symbol byte size) per compiland, from the DBI stream."""
        dbi = self.stream(3)
        mod_size = struct.unpack_from("<i", dbi, 24)[0]
        out, p, end = [], 64, 64 + mod_size
        while p < end:
            stream_idx = struct.unpack_from("<H", dbi, p + 34)[0]
            sym_bytes = struct.unpack_from("<I", dbi, p + 36)[0]
            q = p + 64
            name_end = dbi.index(b"\0", q)
            obj_end = dbi.index(b"\0", name_end + 1)
            obj = dbi[name_end + 1:obj_end].decode("latin-1")
            out.append((obj, stream_idx, sym_bytes))
            p = (obj_end + 1 + 3) & ~3
        return out

    def symbols(self, obj_suffix: str) -> dict[str, tuple[int, int, int]]:
        """name -> (kind, segment, offset) for every procedure and data symbol of the compiland(s) whose object file
        name ends with obj_suffix. Names lose a leading "`anonymous namespace'::"."""
        out: dict[str, tuple[int, int, int]] = {}
        clash: set[str] = set()
        for obj, si, nbytes in self.modules():
            if not obj.lower().endswith(obj_suffix.lower()) or si == 0xFFFF:
                continue
            s = self.stream(si)
            p = 4
            while p < nbytes:
                rlen, kind = struct.unpack_from("<HH", s, p)
                body = p + 4
                if kind in _PROCS:
                    off, seg = struct.unpack_from("<IH", s, body + 28)
                    name = s[body + 35:s.index(b"\0", body + 35)].decode("latin-1")
                elif kind in _DATA:
                    off, seg = struct.unpack_from("<IH", s, body + 4)
                    name = s[body + 10:s.index(b"\0", body + 10)].decode("latin-1")
                else:
                    p += 2 + rlen
                    continue
                name = name.replace("`anonymous namespace'::", "")
                if name in out and out[name][1:] != (seg, off):
                    clash.add(name)            # two records (e.g. a static local and a namespace global): ambiguous
                out.setdefault(name, (kind, seg, off))
                p += 2 + rlen
        for name in clash:
            del out[name]
        return out

    def guid(self) -> bytes:
        """The PDB's GUID (info stream 1), which the linked image's CodeView RSDS record must carry."""
        return self.stream(1)[12:28]

    def age(self) -> int:
        """The PDB's age (info stream 1); the image's RSDS age must equal it."""
        return struct.unpack_from("<I", self.stream(1), 8)[0]

    def globals(self) -> dict[str, tuple[int, int, int]]:
        """name -> (kind, segment, offset) for the global data records of the symbol record stream (S_GDATA32 /
        S_LDATA32 carry the undecorated name; S_PUB32 the decorated one). A name recorded at two different places
        (an anonymous-namespace `g_vehs` in three compilands) is AMBIGUOUS and left out, so a lookup fails loudly
        instead of silently picking another compiland's copy."""
        dbi = self.stream(3)
        s = self.stream(struct.unpack_from("<H", dbi, 20)[0])
        seen: dict[str, set[tuple[int, int]]] = {}
        kinds: dict[str, int] = {}
        p = 0
        while p + 4 <= len(s):
            rlen, kind = struct.unpack_from("<HH", s, p)
            if rlen < 2:
                break
            body = p + 4
            if kind in _DATA or kind == S_PUB32:
                off, seg = struct.unpack_from("<IH", s, body + 4)
                name = s[body + 10:s.index(b"\0", body + 10)].decode("latin-1").replace("`anonymous namespace'::", "")
                seen.setdefault(name, set()).add((seg, off))
                kinds.setdefault(name, kind)
            p += 2 + rlen
        return {n: (kinds[n],) + next(iter(where)) for n, where in seen.items() if len(where) == 1}


def image_symbols(pdb_path: Path, dll_path: Path, obj_suffix: str) -> dict[str, int]:
    """name -> VA in the DLL at its preferred base, for the compiland's procedures and data."""
    import pefile
    pe = pefile.PE(str(dll_path), fast_load=True)
    base = pe.OPTIONAL_HEADER.ImageBase
    secs = [s.VirtualAddress for s in pe.sections]
    pdb = Pdb(pdb_path)
    syms = {**pdb.globals(), **pdb.symbols(obj_suffix)}   # the compiland's own records win
    return {name: base + secs[seg - 1] + off for name, (_k, seg, off) in syms.items() if 1 <= seg <= len(secs)}
