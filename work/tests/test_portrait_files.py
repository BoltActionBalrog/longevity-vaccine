"""uimod portrait_files.h pure helpers: the gate between game data (faction / picture file names from alpha(x).txt,
scenarios, saves, a multiplayer host) and a path on disk.  A name that is not plainly a file stem never becomes one."""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import cpp_harness  # noqa: E402

pytestmark = pytest.mark.skipif(not cpp_harness.have_toolchain(), reason="Visual Studio x86 toolchain not available")


@pytest.fixture(scope="module")
def exe():
    return cpp_harness.build(ROOT / "tests" / "portrait_files_selftest.cpp", "portrait_files_selftest_")


def run(exe, mode, arg):
    return subprocess.run([str(exe), mode, arg], capture_output=True, text=True, check=True).stdout


@pytest.mark.parametrize("name", ["gaians", "GAIANS", "BTwrm", "my_faction-2", "a", "x" * 23])
def test_plain_stems_are_safe(exe, name):
    assert run(exe, "safe", name) == "1"


@pytest.mark.parametrize("name", ["", "x" * 24, "..", "..\\gaians", "../gaians", "C:gaians", "a.b", "a b", "gai*ans",
                                  "con", "CON", "Nul", "aux", "prn", "com1", "COM9", "lpt1", "LPT9", "été"])
def test_anything_else_is_refused(exe, name):
    assert run(exe, "safe", name) == "0"


@pytest.mark.parametrize("name", ["com0", "com10", "console", "conx", "lpt"])
def test_device_names_only_exactly(exe, name):
    assert run(exe, "safe", name) == "1"


@pytest.mark.parametrize("name,want", [("BTwrm", "1"), ("btwrm", "1"), ("BTISL", "1"), ("btchi", "1"),
                                       ("BTsealrk", "1"), ("BTsporlnch", "1"), ("btfungtow", "1"),
                                       ("btwrm2", "0"), ("bt", "0"), ("gaians", "0"), ("mindworm_sm", "0")])
def test_native_life_names(exe, name, want):
    assert run(exe, "native", name) == want


@pytest.mark.parametrize("file,want", [("BTwrm.pcx", "BTwrm"), ("btisl.PCX", "btisl"), ("art\\BTchi.pcx", "BTchi"),
                                       ("a/b/BTsealrk.pcx", "BTsealrk"), ("C:BTwrm.pcx", "BTwrm"),
                                       ("BTwrm.flc", "-"), (".pcx", "-"), ("BTwrm", "-"), ("x" * 40 + ".pcx", "-")])
def test_base_name(exe, file, want):
    assert run(exe, "base", file) == want


# ---------------------------------------------------------------------------------------------- the real decode

@pytest.fixture(scope="module")
def decoder():
    return cpp_harness.build(ROOT / "tests" / "portrait_decode_selftest.cpp", "portrait_decode_selftest_")


def game(tmp_path, decoder):
    """A throwaway 'game dir': the harness exe's own folder (never the real install)."""
    import shutil
    d = tmp_path / "game"
    (d / "portraits" / "hd").mkdir(parents=True)
    shutil.copy(decoder, d / "probe.exe")
    return d


def find(d, name, mode=None):
    r = subprocess.run([str(d / "probe.exe"), name] + ([mode] if mode else []), capture_output=True, text=True)
    assert r.returncode == 0, (r.returncode, r.stderr)
    return r.stdout, r.stderr


def img(path, size, colour, fmt="PNG"):
    from PIL import Image
    Image.new("RGB", size, colour).save(path, format=fmt)


def test_pack_on_wins_and_the_players_files_fill_in(tmp_path, decoder):
    """The SETTING decides: with "Use Turovetsky's HD Portrait Pack" on, the pack's image wins; a name the pack lacks
    falls back to the player's own png, then jpg (user 2026-10-03)."""
    d = game(tmp_path, decoder)
    img(d / "portraits" / "gaians.png", (64, 80), (255, 0, 0))          # the player's own
    img(d / "portraits" / "hd" / "gaians.png", (100, 120), (0, 0, 255))  # the pack's
    assert find(d, "gaians")[0] == "100 120 0 0 255"                    # pack on: the pack
    assert find(d, "GAIANS")[0] == "100 120 0 0 255"                    # case-insensitive name
    img(d / "portraits" / "BTwrm.jpg", (64, 80), (0, 255, 0), "JPEG")   # native life: the pack has none
    out = find(d, "BTwrm")[0].split()
    assert out[:2] == ["64", "80"] and int(out[3]) > 200 and int(out[2]) < 40
    (d / "portraits" / "hd" / "gaians.png").unlink()                    # a pack image the player deleted
    assert find(d, "gaians")[0] == "64 80 255 0 0"


def test_pack_off_uses_only_the_players_files(tmp_path, decoder):
    d = game(tmp_path, decoder)
    img(d / "portraits" / "hd" / "gaians.png", (100, 120), (0, 0, 255))
    assert find(d, "gaians", "nopack")[0] == "none"
    img(d / "portraits" / "gaians.png", (64, 80), (255, 0, 0))
    assert find(d, "gaians", "nopack")[0] == "64 80 255 0 0"


def test_an_unusable_pack_file_falls_back_to_the_players(tmp_path, decoder):
    d = game(tmp_path, decoder)
    (d / "portraits" / "hd" / "gaians.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"broken" * 50)
    img(d / "portraits" / "gaians.png", (64, 80), (255, 0, 0))
    out, log = find(d, "gaians")
    assert out == "64 80 255 0 0", log                                   # the broken pack file is skipped
    assert "hd" in log and "not a complete PNG" in log                   # ... and said so in the log


def test_user_portraits_off_means_nothing_is_used(tmp_path, decoder):
    d = game(tmp_path, decoder)
    img(d / "portraits" / "gaians.png", (64, 80), (255, 0, 0))
    img(d / "portraits" / "hd" / "gaians.png", (100, 120), (0, 0, 255))
    assert find(d, "gaians", "off")[0] == "none"


def test_missing_and_unsafe_names_are_none(tmp_path, decoder):
    d = game(tmp_path, decoder)
    img(d / "portraits" / "gaians.png", (64, 80), (255, 0, 0))
    assert find(d, "hive")[0] == "none"
    for bad in ("..\\portraits\\gaians", "gaians.png", "con"):
        assert find(d, bad)[0] == "none"


@pytest.mark.parametrize("case", ["garbage", "truncated", "renamed_bmp", "too_small", "too_big", "directory", "empty"])
def test_unusable_files_fall_back_to_vanilla(tmp_path, decoder, case):
    from PIL import Image
    d = game(tmp_path, decoder)
    p = d / "portraits" / "gaians.png"
    if case == "garbage":
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8)
    elif case == "truncated":
        import random
        rnd = random.Random(1)                                # noise: a PNG large enough to cut in half
        Image.frombytes("RGB", (200, 240), bytes(rnd.randrange(256) for _ in range(200 * 240 * 3))).save(p)
        data = p.read_bytes()
        p.write_bytes(data[:len(data) // 2])
    elif case == "renamed_bmp":                               # another format under a .png name: magic bytes refuse it
        Image.new("RGB", (64, 64), (1, 2, 3)).save(p, format="BMP")
    elif case == "too_small":
        img(p, (31, 64), (1, 2, 3))
    elif case == "too_big":
        Image.new("RGB", (2049, 40), (1, 2, 3)).save(p, format="PNG")
    elif case == "directory":
        p.mkdir()
    elif case == "empty":
        p.write_bytes(b"")
    out, log = find(d, "gaians")
    assert out == "none", log


def test_large_image_is_box_prereduced(tmp_path, decoder):
    d = game(tmp_path, decoder)
    img(d / "portraits" / "hd" / "univ.png", (2000, 2000), (200, 100, 50))
    assert find(d, "univ")[0] == "1000 1000 200 100 50"                                # k = ceil(2000/1536) = 2


def test_alpha_is_dropped_not_composited(tmp_path, decoder):
    from PIL import Image
    d = game(tmp_path, decoder)
    Image.new("RGBA", (64, 80), (90, 80, 70, 0)).save(d / "portraits" / "angels.png")
    assert find(d, "angels")[0] == "64 80 90 80 70"


def test_truncated_jpeg_falls_back(tmp_path, decoder):
    import random
    from PIL import Image
    d = game(tmp_path, decoder)
    p = d / "portraits" / "peace.jpg"
    rnd = random.Random(2)
    Image.frombytes("RGB", (200, 240), bytes(rnd.randrange(256) for _ in range(200 * 240 * 3))).save(p, format="JPEG")
    data = p.read_bytes()
    p.write_bytes(data[:len(data) // 2])
    assert find(d, "peace")[0] == "none"
