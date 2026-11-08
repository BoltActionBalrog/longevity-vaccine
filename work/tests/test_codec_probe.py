"""A codec DLL that fails to load must be REPORTED, never silent (user decision 2026-10-28).

The five ffmpeg DLLs were hard imports of uimod.dll: one missing (an antivirus quarantining an unsigned
DLL is the expected trigger) and Windows refused uimod.dll itself -- the whole mod gone. Now they are
delay-loaded, and src\\uimod\\src\\codecs.h probes them at Init: the hook stays out, uimod.log names the
file, the player gets one notice. These tests drive the probe (codecs\\codec_harness.cpp) against the
REAL shipped DLLs with one removed, one swapped for another build, one asked for the wrong major; pin the
built DLL's import tables; and pin the gate in init.cpp.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import cpp_harness  # noqa: E402

HARNESS = HERE / "codecs" / "codec_harness.cpp"
SRC = REPO / "src" / "uimod" / "src"
BIN = REPO / "src" / "uimod" / "third_party" / "ffmpeg" / "bin"
INC = REPO / "src" / "uimod" / "third_party" / "ffmpeg" / "include"
DLL = REPO / "src" / "uimod" / "build" / "Release" / "uimod.dll"

#: dependency order, as movie.cpp lists them: (dll, version export, header folder, macro stem)
LIBS = [("avutil-60.dll", "avutil_version", "libavutil", "LIBAVUTIL_VERSION"),
        ("swresample-6.dll", "swresample_version", "libswresample", "LIBSWRESAMPLE_VERSION"),
        ("swscale-9.dll", "swscale_version", "libswscale", "LIBSWSCALE_VERSION"),
        ("avcodec-62.dll", "avcodec_version", "libavcodec", "LIBAVCODEC_VERSION"),
        ("avformat-62.dll", "avformat_version", "libavformat", "LIBAVFORMAT_VERSION")]

pytestmark = pytest.mark.skipif(not cpp_harness.have_toolchain() or not BIN.is_dir(),
                                reason="needs the VS 2022 x86 toolchain and third_party/ffmpeg")


def _macro(folder: str, macro: str) -> int:
    """LIBxxx_VERSION_MAJOR / _MINOR from the headers the DLL was compiled against (version.h or version_major.h)."""
    for h in ("version_major.h", "version.h"):
        p = INC / folder / h
        if p.is_file():
            m = re.search(rf"#define\s+{macro}\s+(\d+)", p.read_text(encoding="utf-8", errors="replace"))
            if m:
                return int(m.group(1))
    raise AssertionError(f"{macro} not found under {INC / folder}")


@pytest.fixture(scope="module")
def exe() -> pathlib.Path:
    return cpp_harness.build(HARNESS, "codec-probe-", "/std:c++17 /EHsc /O1")


@pytest.fixture(scope="module")
def majors() -> dict:
    """name -> "major.minor" as compiled against"""
    return {name: f"{_macro(f, stem + '_MAJOR')}.{_macro(f, stem + '_MINOR')}" for name, _e, f, stem in LIBS}


@pytest.fixture(scope="module")
def dlls(tmp_path_factory) -> pathlib.Path:
    """One copy of the five shipped DLLs per module (~10 MB); each test derives its own folder from it."""
    d = tmp_path_factory.mktemp("codecs")
    for name, *_ in LIBS:
        shutil.copy2(BIN / name, d / name)
    return d


def _probe(exe, d: pathlib.Path, majors: dict, override: dict | None = None) -> dict:
    specs = [f"{n}:{e}:{(override or {}).get(n, majors[n])}" for n, e, _h, _m in LIBS]
    p = subprocess.run([str(exe), "probe", str(d), *specs], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    out = {"problems": [], "LOG": "", "NOTICE": "", "SIG": ""}
    for line in p.stdout.splitlines():
        if line.startswith("problems="):
            out["n"] = int(line.split()[0].split("=")[1])
            out["libs"] = int(line.split()[1].split("=")[1])
        elif line.startswith("problem "):
            f = dict(kv.split("=") for kv in line.split()[2:])
            out["problems"].append({"name": line.split()[1], **{k: int(v) for k, v in f.items()}})
        else:
            k, _, v = line.partition(":")
            out[k] = v
    return out


def _derive(dlls: pathlib.Path, tmp_path: pathlib.Path, drop=(), swap=None) -> pathlib.Path:
    d = tmp_path / "game"
    d.mkdir(parents=True)
    for name, *_ in LIBS:
        if name in drop:
            continue
        shutil.copy2(dlls / (swap[name] if swap and name in swap else name), d / name)
    return d


# ---- the probe against the real DLLs ------------------------------------------------------------

def test_all_present_is_clean(exe, dlls, majors):
    r = _probe(exe, dlls, majors)
    assert r["n"] == 0 and r["libs"] == 5, r
    assert r["SIG"] == "" and r["LOG"] == ""


def test_a_missing_dll_is_named_with_the_windows_error(exe, dlls, majors, tmp_path):
    r = _probe(exe, _derive(dlls, tmp_path, drop=("avcodec-62.dll",)), majors)
    names = [p["name"] for p in r["problems"]]
    assert "avcodec-62.dll" in names, r
    acodec = next(p for p in r["problems"] if p["name"] == "avcodec-62.dll")
    assert acodec["fault"] == 1 and acodec["error"] == 126        # kNotLoaded, ERROR_MOD_NOT_FOUND
    # avformat imports avcodec: it fails too, and the ROOT cause is listed first (dependency order)
    assert names[0] == "avcodec-62.dll" and "avformat-62.dll" in names
    assert "avcodec-62.dll is missing (Windows error 126)" in r["LOG"]
    assert "avcodec-62.dll is missing" in r["NOTICE"] and "re-run the Longevity Vaccine installer" in r["NOTICE"]
    assert r["SIG"].startswith("avcodec-62.dll:1;")


def test_a_dll_of_another_build_under_the_right_name_is_caught(exe, dlls, majors, tmp_path):
    """The name is right, the exports are not: the first delay-load bind would have crashed the game."""
    d = _derive(dlls, tmp_path, swap={"swscale-9.dll": "swresample-6.dll"})
    r = _probe(exe, d, majors)
    sws = next(p for p in r["problems"] if p["name"] == "swscale-9.dll")
    assert sws["fault"] == 2 and sws["error"] == 127            # kNoVersionExport, ERROR_PROC_NOT_FOUND
    assert "swscale-9.dll is not the file the mod shipped" in r["LOG"]


def test_a_wrong_major_is_caught_with_both_numbers(exe, dlls, majors):
    r = _probe(exe, dlls, majors, override={"avutil-60.dll": "99.0"})
    assert r["n"] == 1, r
    p = r["problems"][0]
    have = int(majors["avutil-60.dll"].split(".")[0])
    assert p["name"] == "avutil-60.dll" and p["fault"] == 3 and p["found"] == have and p["wanted"] == 99
    assert f"avutil-60.dll is version {have}, the mod needs 99" in r["LOG"]
    assert r["SIG"] == "avutil-60.dll:3;"


def test_an_older_minor_of_the_right_major_is_caught(exe, dlls, majors):
    """ffmpeg adds exports within a major: a DLL of the right major but an older minor can lack one the
    player binds to, and that bind would raise inside the first movie. Asking for minor 255 makes the
    shipped DLL "too old"."""
    have_major, have_minor = majors["avcodec-62.dll"].split(".")
    r = _probe(exe, dlls, majors, override={"avcodec-62.dll": f"{have_major}.255"})
    assert r["n"] == 1, r
    p = r["problems"][0]
    assert p["name"] == "avcodec-62.dll" and p["fault"] == 4 and p["foundminor"] == int(have_minor) and p["wantedminor"] == 255
    assert f"avcodec-62.dll is version {have_major}.{have_minor}, the mod needs {have_major}.255 or newer" in r["LOG"]
    # and the shipped minor itself passes (the clean probe above), so the rule is >=, not ==


def test_the_signature_distinguishes_problem_sets(exe, dlls, majors, tmp_path):
    a = _probe(exe, _derive(dlls, tmp_path / "a", drop=("avformat-62.dll",)), majors)["SIG"]
    b = _probe(exe, _derive(dlls, tmp_path / "b", drop=("swscale-9.dll",)), majors)["SIG"]
    assert a and b and a != b


def test_the_notice_is_one_paragraph_the_label_writer_can_wrap(exe, dlls, majors, tmp_path):
    r = _probe(exe, _derive(dlls, tmp_path, drop=("avutil-60.dll",)), majors)
    n = r["NOTICE"]
    assert "\n" not in n and len(n) < 2000
    for bad in ("^", "$", "{", "}", "[", "]"):      # script.txt markup
        assert bad not in n, bad
    assert "everything else in the mod works" in n


# ---- the built DLL and the wiring ----------------------------------------------------------------

def test_built_dll_delay_loads_every_codec_and_hard_imports_none():
    if not DLL.is_file():
        pytest.skip("uimod.dll not built")
    import pefile
    pe = pefile.PE(str(DLL), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                           pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
    hard = {e.dll.decode().lower() for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])}
    delay = {e.dll.decode().lower() for e in getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])}
    codecs = {name for name, *_ in LIBS}
    assert codecs <= delay, f"not delay-loaded: {codecs - delay}"
    assert not (codecs & hard), f"still hard imports: {codecs & hard}"
    assert "xaudio2_9.dll" not in hard | delay


def test_the_shipped_dll_set_is_the_probed_set():
    shipped = {p.name.lower() for p in BIN.glob("*.dll")}
    assert shipped == {name for name, *_ in LIBS}, shipped
    proj = (REPO / "src" / "uimod" / "uimod.vcxproj").read_text(encoding="utf-8")
    m = re.search(r"<DelayLoadDLLs>([^<]+)</DelayLoadDLLs>", proj)
    assert m, "DelayLoadDLLs missing from uimod.vcxproj"
    # plus Windows' own Winsock / IP Helper: never shipped, delay-loaded only so a single-player session never maps
    # them (lanjoin.cpp, the multiplayer home-network fix; test_lanjoin_core.test_winsock_is_not_loaded_at_game_start)
    system = {"ws2_32.dll", "iphlpapi.dll"}
    assert {x.lower() for x in m.group(1).split(";") if x.endswith(".dll")} == shipped | system
    movie = (SRC / "movie.cpp").read_text(encoding="utf-8", errors="replace")
    for name, export, _f, stem in LIBS:
        assert f'L"{name}"' in movie and f'"{export}"' in movie, name
        assert stem + "_MAJOR" in movie and stem + "_MINOR" in movie, name
    assert "PlayGuarded(" in movie and "0xC06D007E" in movie, "the first movie must survive a delay-load bind failure"


def test_init_gates_the_movie_hook_on_the_probe_and_queues_the_notice():
    init = (SRC / "init.cpp").read_text(encoding="utf-8", errors="replace")
    gate = init.index("MovieCodecsOk(")
    assert init.index("InstallMovieHook(pracx)") > gate, "the hook must not go in before the probe"
    assert "UpdateQueueStartupNotice(codecNotice, codecSig)" in init
    upd = (SRC / "update.cpp").read_text(encoding="utf-8", errors="replace")
    assert "if (g_noticePending) g_phase = kPhaseArmed;" in upd, "a notice must show even with the update check off"
    assert 'WritePrivateProfileStringW(L"UIMod", kNoticeKey' in upd
    assert "__pfnDliFailureHook2" in (SRC / "movie.cpp").read_text(encoding="utf-8", errors="replace")


# ---- the whole point, without a game launch: uimod.dll itself loads with a codec gone ------------

PY32 = REPO / "tools" / "python38" / "python.exe"      # the Windows 7 interpreter is 32-bit, like uimod.dll


@pytest.mark.skipif(not PY32.is_file(), reason="needs the 32-bit interpreter (fetch_python38.py)")
@pytest.mark.parametrize("gone", [("avcodec-62.dll",), tuple(n for n, *_ in LIBS)], ids=["one-missing", "all-missing"])
def test_uimod_dll_loads_into_a_process_with_codecs_missing(dlls, tmp_path, gone):
    """Before: a hard import -> LoadLibrary(uimod.dll) failed with 126 and the boot guard left the game.
    Now the DLL loads (DllMain only disables thread calls; Init is a separate export the exe calls), and
    what is missing is the probe's business. Done in a 32-bit child process: the DLL is x86."""
    if not DLL.is_file():
        pytest.skip("uimod.dll not built")
    d = _derive(dlls, tmp_path, drop=gone)
    shutil.copy2(DLL, d / "uimod.dll")
    code = ("import ctypes, sys\n"
            "k = ctypes.WinDLL('kernel32', use_last_error=True)\n"
            "k.LoadLibraryExW.restype = ctypes.c_void_p\n"
            "h = k.LoadLibraryExW(sys.argv[1], None, 0x8)\n"      # LOAD_WITH_ALTERED_SEARCH_PATH
            "print('handle' if h else 'error=%d' % ctypes.get_last_error())\n")
    p = subprocess.run([str(PY32), "-c", code, str(d / "uimod.dll")], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and p.stdout.strip() == "handle", f"uimod.dll refused to load with {gone} gone: {p.stdout}{p.stderr}"
