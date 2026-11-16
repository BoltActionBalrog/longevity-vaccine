"""terrainhd.cpp's own bookkeeping, run: the row off from the ini (nothing cut) and live (the exact stock textures
back, the span stubs' list of ours empty, nothing held); a new game at a level and the level per screen (2x / 4x / 8x,
8x the cell as painted), the list following each; PRACX's Alt+T overlays never in the list (drawn natively, nothing
copied); a pack damaged after install and no address room for a level (each decided once: several passes, one read
at most, one log line, nothing held, tried again only by switching the row); a failed level after a level; back to
stock from every level with every texture keeping bits.

tests/terrainhd_cache_selftest.cpp compiles terrainhd.cpp itself (TERRAINHD_SELFTEST: a fake exe image and fake
engine functions that follow the engine where the hook depends on it -- mem_alloc never returns null, a Buffer's
pixels at +0x54 with the lock pointer null, Texture_extract_2's only quiet returns 0x10 and 3 -- and a real
8192 x 6144 pack on disk, written once for the module, read by the real hdpack reader). One scenario per process.
Skipped when Visual Studio is absent.
"""
from __future__ import annotations

import pathlib
import shutil
import struct
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import cpp_harness  # noqa: E402

SCENARIOS = ["off_holds_nothing", "new_game_and_levels", "overlays", "pack_damaged_later", "no_room",
             "failed_after_a_level", "restore_from_every_level", "bad_pack"]


@pytest.fixture(scope="module")
def exe():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    return cpp_harness.build(ROOT / "tests" / "terrainhd_cache_selftest.cpp", "terrainhd_cache_", "/Oi /GL")


@pytest.fixture(scope="module")
def pack(exe, tmp_path_factory):
    d = tmp_path_factory.mktemp("terrainhd_pack")
    r = subprocess.run([str(exe), str(d), "make_pack"], capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return d / "terrain" / "texture_x8.pcx"


def test_give_bits_writes_the_texture_as_texture_extract_2_does(exe, tmp_path):
    """GiveBits stands in for Texture_extract_2: after a cut at any level, width and height (+4 / +8) are the level's
    size and every other field (+0x0C..+0x6C) equals what the engine's own code writes for a 56 x 56 cut, run under
    emulation on the pristine exe (the tail 0x61985F..0x6198C9). The corner coordinates stay stock because
    Texture_draw_trans_2 (0x61A240) draws from them as its UVs and the span stubs multiply them by the level."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import config
    import pefile
    from unicorn import UC_ARCH_X86, UC_MODE_32, Uc
    from unicorn.x86_const import UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_ESP
    bak = config.terranx_bak(required=False)
    if not bak or not pathlib.Path(bak).exists():
        pytest.skip("pristine exe not available")
    pe = pefile.PE(str(bak), fast_load=True)
    ib = pe.OPTIONAL_HEADER.ImageBase
    r = subprocess.run([str(exe), str(tmp_path), "corners"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    ours = {int(ln.split()[0]): [int(v) for v in ln.split()[1:]] for ln in r.stdout.splitlines()}
    assert sorted(ours) == [56, 112, 224, 448]
    for side, got in ours.items():
        mu = Uc(UC_ARCH_X86, UC_MODE_32)
        for s in pe.sections:
            mu.mem_map(ib + s.VirtualAddress, (max(s.Misc_VirtualSize, s.SizeOfRawData) + 0xFFF) & ~0xFFF)
            mu.mem_write(ib + s.VirtualAddress, s.get_data())
        mu.mem_map(0x0F000000, 0x100000)
        tex, sp = 0x0F010000, 0x0F080000
        mu.mem_write(tex, struct.pack("<3i", 0x1234, 56, 56) + b"\xEE" * (0x70 - 12))
        mu.reg_write(UC_X86_REG_ESI, tex)
        mu.reg_write(UC_X86_REG_EBX, 0)                      # ebx = 0 through the function (xor ebx, ebx)
        mu.reg_write(UC_X86_REG_ESP, sp)
        mu.emu_start(0x61985F, 0x6198C9)
        eng = list(struct.unpack("<27i", bytes(mu.mem_read(tex + 4, 0x6C))))
        eng[-1] = 0                                          # +0x6C: 0 for bits not from a TexHeap (0x61980E)
        eng[0], eng[1] = side, side                          # +4 / +8: the level's size (the row stride)
        assert got == eng, (side, got, eng)


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_terrainhd_bookkeeping(exe, pack, tmp_path, scenario):
    (tmp_path / "terrain").mkdir()
    shutil.copyfile(pack, tmp_path / "terrain" / "texture_x8.pcx")
    r = subprocess.run([str(exe), str(tmp_path), scenario], capture_output=True, text=True, timeout=300)
    lines = r.stdout.splitlines()
    fails = [ln for ln in lines if ln.startswith("FAIL")]
    assert not fails, "\n".join(fails)
    assert r.returncode == 0, r.stdout + r.stderr
    assert any(ln.startswith("ok ") for ln in lines), r.stdout + r.stderr
