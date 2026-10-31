"""uimod vidmode.cpp binds prax.dll's display-mode switch by offset; pin what the DLL byte-checks.

HookDisplaySwitch (src/uimod/src/vidmode.cpp) redirects ONE import slot of prax.dll -- user32!ChangeDisplaySettingsA
at RVA 0x341BC -- after checking RestoreVideoMode's prologue (RVA 0x9940: push ebp; mov ebp,esp; push 0; push 0;
call [slot]) and SetVideoMode's (RVA 0x9ED0: push ebp; mov ebp,esp; sub esp,0x9C). This test reads the installed
prax.dll (skipped when no game install is configured) and verifies those facts from the PE itself, plus the claim
the suppression rests on: that slot is prax.dll's ONLY route to ChangeDisplaySettings (exactly two `call [slot]`
sites in .text, the two functions above).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import config  # noqa: E402

CDS_SLOT_RVA = 0x341BC
RESTORE_RVA = 0x9940
SETVIDEO_RVA = 0x9ED0
SETWINDOWED_RVA = 0x9F60
IMAGE_BASE = 0x10000000

RESTORE_PROLOGUE = bytes.fromhex("55 8B EC 6A 00 6A 00 FF 15") + struct.pack("<I", IMAGE_BASE + CDS_SLOT_RVA) + bytes.fromhex("5D C3")
SETVIDEO_PROLOGUE = bytes.fromhex("55 8B EC 81 EC 9C 00 00 00")
SETWINDOWED_PROLOGUE = bytes.fromhex("55 8B EC 6A FF")
CALL_SLOT = bytes.fromhex("FF 15") + struct.pack("<I", IMAGE_BASE + CDS_SLOT_RVA)


def _prax() -> bytes:
    d = config.game_dir(required=False)
    p = d / "prax.dll" if d else None
    if not p or not p.is_file():
        pytest.skip("no prax.dll: game install not configured")
    return p.read_bytes()


class Pe:
    def __init__(self, data: bytes) -> None:
        self.d = data
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        assert data[pe:pe + 4] == b"PE\0\0"
        nsec = struct.unpack_from("<H", data, pe + 6)[0]
        optsz = struct.unpack_from("<H", data, pe + 20)[0]
        opt = pe + 24
        self.image_base = struct.unpack_from("<I", data, opt + 28)[0]
        self.import_rva = struct.unpack_from("<I", data, opt + 96 + 8)[0]   # data directory 1
        self.secs = []
        off = opt + optsz
        for _ in range(nsec):
            name = data[off:off + 8].rstrip(b"\0").decode()
            vs, va, rs, ro = struct.unpack_from("<IIII", data, off + 8)
            self.secs.append((name, va, vs, ro, rs))
            off += 40

    def fo(self, rva: int) -> int:
        for _, va, vs, ro, rs in self.secs:
            if va <= rva < va + max(vs, rs):
                return ro + rva - va
        raise KeyError(hex(rva))

    def section(self, name: str) -> bytes:
        for n, va, vs, ro, rs in self.secs:
            if n == name:
                return self.d[ro:ro + rs]
        raise KeyError(name)

    def cstr(self, rva: int) -> str:
        o = self.fo(rva)
        return self.d[o:self.d.index(b"\0", o)].decode()

    def import_of_slot(self, slot_rva: int) -> tuple[str, str]:
        """(dll, symbol) bound to the IAT slot at slot_rva."""
        off = self.fo(self.import_rva)
        while True:
            oft, _, _, name_rva, ft = struct.unpack_from("<IIIII", self.d, off)
            if ft == 0 and name_rva == 0:
                break
            dll = self.cstr(name_rva)
            i = 0
            while True:
                thunk = struct.unpack_from("<I", self.d, self.fo((oft or ft) + 4 * i))[0]
                if thunk == 0:
                    break
                if ft + 4 * i == slot_rva:
                    if thunk & 0x80000000:
                        return dll, f"#{thunk & 0xFFFF}"
                    return dll, self.cstr(thunk + 2)
                i += 1
            off += 20
        raise KeyError(hex(slot_rva))


@pytest.fixture(scope="module")
def pe() -> Pe:
    p = Pe(_prax())
    assert p.image_base == IMAGE_BASE
    return p


def test_cds_slot_is_user32_change_display_settings(pe: Pe) -> None:
    dll, sym = pe.import_of_slot(CDS_SLOT_RVA)
    assert dll.lower() == "user32.dll"
    assert sym == "ChangeDisplaySettingsA"


def test_prologues_match_the_dll_byte_check(pe: Pe) -> None:
    d = pe.d
    assert d[pe.fo(RESTORE_RVA):pe.fo(RESTORE_RVA) + len(RESTORE_PROLOGUE)] == RESTORE_PROLOGUE
    assert d[pe.fo(SETVIDEO_RVA):pe.fo(SETVIDEO_RVA) + len(SETVIDEO_PROLOGUE)] == SETVIDEO_PROLOGUE
    assert d[pe.fo(SETWINDOWED_RVA):pe.fo(SETWINDOWED_RVA) + len(SETWINDOWED_PROLOGUE)] == SETWINDOWED_PROLOGUE


def test_slot_is_the_only_route_to_a_mode_switch(pe: Pe) -> None:
    """Two call sites through the slot: RestoreVideoMode and SetVideoMode. No other import of the function
    (W variant or ordinal) and no other reference to the slot."""
    text = pe.section(".text")
    text_va = next(va for n, va, _, _, _ in pe.secs if n == ".text")
    sites = []
    i = text.find(CALL_SLOT)
    while i >= 0:
        sites.append(text_va + i)
        i = text.find(CALL_SLOT, i + 1)
    assert len(sites) == 2, [hex(s) for s in sites]
    assert RESTORE_RVA < sites[0] < RESTORE_RVA + 0x20
    assert SETVIDEO_RVA < sites[1] < SETVIDEO_RVA + 0x100
    # the slot address appears nowhere else in the image as an abs32 (no `mov reg,[slot]` / `jmp [slot]` elsewhere)
    assert pe.d.count(struct.pack("<I", IMAGE_BASE + CDS_SLOT_RVA)) == 2
    # and ChangeDisplaySettings is imported exactly once, as the A variant
    off = pe.fo(pe.import_rva)
    names = []
    while True:
        oft, _, _, name_rva, ft = struct.unpack_from("<IIIII", pe.d, off)
        if ft == 0 and name_rva == 0:
            break
        i = 0
        while True:
            thunk = struct.unpack_from("<I", pe.d, pe.fo((oft or ft) + 4 * i))[0]
            if thunk == 0:
                break
            if not thunk & 0x80000000:
                s = pe.cstr(thunk + 2)
                if "ChangeDisplaySettings" in s:
                    names.append(s)
            i += 1
        off += 20
    assert names == ["ChangeDisplaySettingsA"]
