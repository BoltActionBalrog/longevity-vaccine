"""uimod prewarm.cpp: the background pre-bake of the replacement leader portraits.

Three things are held to ground truth here:
  1. the vanilla-sheet model -- the slot the engine cuts from <faction>.pcx (Buffer_load_pcx stores (raw + 10) & 0xFF,
     Sprite_extract_2 copies load_faction_art's rect) reproduces the engine's sprite bit for bit: the Phase-0 probe
     (2026-09-30) hashed every leader slot at load_faction_art, and those hashes are the oracle;
  2. the C++ sheet reader equals that model (PIL) and the law's scanline parameters;
  3. every pre-baked result equals the plain law, with the lookups made while the worker runs (waiting on a running
     job, taking a queued one over), after a cancel, with failing jobs, after a re-key and after an invalidate.
Needs the VS x86 toolchain and the game's sheets; the real pack image if installed (one faction is enough)."""
from __future__ import annotations

import pathlib
import random
import re
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import config  # noqa: E402
import cpp_harness  # noqa: E402
import scaling_laws as SL  # noqa: E402

pytestmark = pytest.mark.skipif(not cpp_harness.have_toolchain(), reason="Visual Studio x86 toolchain not available")

#: load_faction_art's Sprite_extract_2 literals (decompiled 2026-10-14): x, y, w, h in the sheet; prewarm's slot order
SHEET_RECTS = [(0x58, 0x1C9, 96, 115), (0xB9, 0x1C9, 118, 144), (0x130, 0x1C9, 131, 157), (0x213, 1, 164, 198)]
SLOT_NAMES = ["smallcouncil", "bigcouncil", "diplomacy", "datalink"]

#: Phase-0 probe, 4K run (work\frida_portrait_palette_2026-09-30T06-55-35-117Z.log, not tracked): FNV-1a 32 over
#: pitch*h bytes of each leader slot sprite right after load_faction_art(f), f = 1..7 of the default ini roster.
ENGINE_HASHES = {
    ("gaians", "smallcouncil"): 0xF9CCC6B3, ("gaians", "bigcouncil"): 0x5103F6D5,
    ("gaians", "diplomacy"): 0xF03AE85A, ("gaians", "datalink"): 0x8A5B2B93,
    ("hive", "smallcouncil"): 0x2151D687, ("hive", "bigcouncil"): 0xA04345AE,
    ("hive", "diplomacy"): 0x903C8633, ("hive", "datalink"): 0xD7977ECC,
    ("univ", "smallcouncil"): 0x1860F517, ("univ", "bigcouncil"): 0x79195C34,
    ("univ", "diplomacy"): 0x1A3E1C66, ("univ", "datalink"): 0x908575E5,
    ("morgan", "smallcouncil"): 0xB2C5D461, ("morgan", "bigcouncil"): 0xF0C96182,
    ("morgan", "diplomacy"): 0x62C57430, ("morgan", "datalink"): 0x6904BE35,
    ("spartans", "smallcouncil"): 0x93D7D15B, ("spartans", "bigcouncil"): 0x5235C40F,
    ("spartans", "diplomacy"): 0x4E0460E2, ("spartans", "datalink"): 0x86A484BB,
    ("believe", "smallcouncil"): 0xF81D53B8, ("believe", "bigcouncil"): 0x853B6948,
    ("believe", "diplomacy"): 0xD0D000F2, ("believe", "datalink"): 0x3A43F84F,
    ("peace", "smallcouncil"): 0xA324921B, ("peace", "bigcouncil"): 0x8284A6B8,
    ("peace", "diplomacy"): 0x15FF3B2B, ("peace", "datalink"): 0x6ACDFF52,
}
ALL_FACTIONS = ["gaians", "hive", "univ", "morgan", "spartans", "believe", "peace",
                "cyborg", "drone", "pirates", "angels", "fungboy", "caretake", "usurper"]


def fnv32(data: bytes) -> int:
    h = 0x811C9DC5
    for b in data:
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


def sheet_path(fac: str) -> pathlib.Path:
    gd = config.game_dir(required=False)
    if not gd or not (gd / f"{fac}.pcx").exists():
        pytest.skip("game art not available")
    return gd / f"{fac}.pcx"


def engine_cut(fac: str, slot: int) -> bytes:
    """The slot sprite as the engine holds it: the sheet's rect, every index + 10 mod 256 (key 9 = raw 255)."""
    from PIL import Image
    im = Image.open(sheet_path(fac))
    x, y, w, h = SHEET_RECTS[slot]
    cell = im.crop((x, y, x + w, y + h))
    return bytes((v + 10) & 0xFF for v in cell.tobytes())


def synth_pal(seed: int = 7) -> bytes:
    rnd = random.Random(seed)
    pal = bytearray(1024)
    for i in range(256):
        pal[i * 4], pal[i * 4 + 1], pal[i * 4 + 2] = rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)
    return bytes(pal)


# ---------------------------------------------------------------------------------------------- 1. the sheet model

@pytest.mark.parametrize("fac,slot", sorted(ENGINE_HASHES))
def test_sheet_cut_model_reproduces_the_engine_sprite(fac, slot):
    assert fnv32(engine_cut(fac, SLOT_NAMES.index(slot))) == ENGINE_HASHES[(fac, slot)]


# ---------------------------------------------------------------------------------------------- the harness

@pytest.fixture(scope="module")
def exe():
    return cpp_harness.build(ROOT / "tests" / "portrait_prewarm_selftest.cpp", "portrait_prewarm_selftest_")


def hd_image(fac: str) -> pathlib.Path:
    gd = config.game_dir(required=False)
    if gd and (gd / "portraits" / "hd" / f"{fac}.png").exists():
        return gd / "portraits" / "hd" / f"{fac}.png"
    pytest.skip("portraits-hd pack not installed")


def game(tmp_path, exe, factions=("gaians",), images=True):
    """A throwaway game dir: the harness exe, the factions' vanilla sheets and (optionally) their pack images."""
    d = tmp_path / "game"
    (d / "portraits" / "hd").mkdir(parents=True)
    shutil.copy(exe, d / "probe.exe")
    for fac in factions:
        shutil.copy(sheet_path(fac), d / f"{fac}.pcx")
        if images:
            shutil.copy(hd_image(fac), d / "portraits" / "hd" / f"{fac}.png")
    (d / "pal.bin").write_bytes(synth_pal())
    return d


# Every scenario below is synchronised on what the worker / lock holder has DONE, never on how long it took (the
# harness waits for the state it needs; see its header), and asserts outcomes: the counters say which path each
# lookup took.  A loaded machine (several suites at once) starves the below-normal worker for whole seconds, and the
# millisecond bounds these tests used to assert failed there while the code was right.  A hang is still caught: by
# the probe's timeout, far beyond any load.
def probe(d, *args, timeout=600):
    r = subprocess.run([str(d / "probe.exe"), *map(str, args)], capture_output=True, text=True, timeout=timeout)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    return r.stdout.strip(), r.stderr


WHY_FAILED = 5                                       # prewarm.h: enum Why { kHit, kNotStarted, kAbsent, kQueuedTaken,
                                                     #   kRunningTimeout, kFailed, kDropped }


def kv(line: str) -> dict:
    return {k: int(v) for k, v in re.findall(r"(\w+)=(-?\d+)", line)}


# ---------------------------------------------------------------------------------------------- 2. the C++ reader

@pytest.mark.parametrize("fac", ALL_FACTIONS)
@pytest.mark.parametrize("slot", range(4))
def test_cpp_sheet_reader_matches_pil_and_the_law(tmp_path, exe, fac, slot):
    d = game(tmp_path, exe, (fac,), images=False)
    out, _ = probe(d, "sheet", fac, slot, d / "pal.bin")
    assert out != "none"
    b, r, h = out.split()
    cut = engine_cut(fac, slot)
    x, y, w, hh = SHEET_RECTS[slot]
    want_b, want_r = SL.portrait_scanline_params(cut, w, w, hh, synth_pal())
    assert (int(b), int(r), int(h, 16)) == (want_b, want_r, fnv32(cut))


def test_sheet_reader_refuses_garbage_and_a_missing_sheet(tmp_path, exe):
    d = game(tmp_path, exe, ("gaians",), images=False)
    (d / "hive.pcx").write_bytes(b"\x0a\x05\x01\x08" + bytes(124) + b"\xc5" * 3000)   # header ok, data cut short
    assert probe(d, "sheet", "hive", 3, d / "pal.bin")[0] == "none"
    assert probe(d, "sheet", "nosuch", 3, d / "pal.bin")[0] == "none"
    (d / "faction.pcx").write_bytes((d / "gaians.pcx").read_bytes())                   # the engine's fallback sheet
    assert probe(d, "sheet", "nosuch", 3, d / "pal.bin")[0] == probe(d, "sheet", "gaians", 3, d / "pal.bin")[0]


def test_list_names_is_the_pack_plus_the_players_files(tmp_path, exe):
    from PIL import Image
    d = game(tmp_path, exe, ("gaians",), images=False)
    for p in ("portraits/hd/gaians.png", "portraits/HIVE.png", "portraits/Gaians.jpg", "portraits/BTwrm.png",
              "portraits/my.dotted.png", "portraits/con.png"):
        Image.new("RGB", (64, 80), (1, 2, 3)).save(d / p, format="JPEG" if p.endswith(".jpg") else "PNG")
    (d / "portraits" / "sub.png").mkdir()
    names = probe(d, "names")[0].split()
    assert sorted(n.lower() for n in names) == ["gaians", "hive"]                      # unique, no native life, no devices


# ---------------------------------------------------------------------------------------------- 3. the pre-bake

@pytest.mark.parametrize("g,scan", [(16, 1), (25, 1), (40, 0), (40, 1), (40, 2)])
def test_prebaked_results_equal_the_synchronous_law(tmp_path, exe, g, scan):
    d = game(tmp_path, exe)
    out, log = probe(d, "run", g, scan, d / "pal.bin")
    c = kv(out)
    phases = 2 * SL.art_scan_rows(g, 16) if g > 16 else 0
    assert c["entries"] == 4 * (2 + phases), (out, log)                                 # 4 slots x (2 native modes: current + the other reachable one + every phase)
    assert c["done"] == c["entries"] and c["failed"] == 0 and c["dropped"] == 0, (out, log)
    assert c["hits"] == c["entries"] and c["mismatch"] == 0 and c["missing"] == 0, (out, log)
    assert c["bytes"] > 0


def test_lookups_during_the_run_wait_or_take_over_never_mismatch(tmp_path, exe):
    d = game(tmp_path, exe)
    out, log = probe(d, "race", 40, 1, d / "pal.bin")
    c = kv(out)
    assert c["mismatch"] == 0 and c["final_mismatch"] == 0 and c["final_missing"] == 0, (out, log)
    assert c["hits"] + c["taken"] == c["entries"] and c["other"] == 0, (out, log)       # every key: a hit or taken over
    assert c["final_hits"] == c["entries"]                                              # ... and all of them stored


def test_cancel_never_hangs_a_waiter(tmp_path, exe):
    """After Cancel a lookup waits on the one running job at most, never on the queue: every job still queued at the
    cancel comes back at once, taken over (not a hit -- the worker never baked it).  (Was `lookupms < 1500`.)"""
    d = game(tmp_path, exe)
    out, log = probe(d, "cancel", 40, 1, d / "pal.bin")
    c = kv(out)
    assert c["running"] <= 1, (out, log)                                 # one worker: one running job at most
    assert c["queuedhit"] == 0 and c["queuedtaken"] == c["queued"], (out, log)   # the queue: never waited for
    assert c["mismatch"] == 0


def test_failed_jobs_are_misses_not_hangs(tmp_path, exe):
    d = game(tmp_path, exe)
    out, log = probe(d, "fail", 2, 25, 1, d / "pal.bin")
    c = kv(out)
    assert c["failed"] >= 1 and c["failedmiss"] == c["failed"], (out, log)
    assert c["mismatch"] == 0 and c["missing"] == 0, (out, log)
    assert c["done"] + c["failed"] == c["entries"] or c["done"] + c["failed"] < c["entries"]   # it may give up after 3


@pytest.mark.parametrize("mode", ["rekey", "rekeylate"])    # reported while queued / after the worker finished
def test_measured_params_rekey_the_prediction(tmp_path, exe, mode):
    d = game(tmp_path, exe)
    out, log = probe(d, mode, 25, 1, d / "pal.bin")
    c = kv(out)
    assert c["slot2"] == 2 + 2 * SL.art_scan_rows(25, 16), (out, log)                 # the slot's jobs (2 native modes + phases), no duplicates
    assert c["oldhit"] == 0 and c["newhit"] == c["slot2"] and c["newmiss"] == 0 and c["mismatch"] == 0, (out, log)


def test_restart_in_another_scan_mode_keeps_natives_and_rebuilds_enlarges(tmp_path, exe):
    d = game(tmp_path, exe)
    out, log = probe(d, "restartscan", 25, 1, d / "pal.bin")
    c = kv(out)
    phases = 2 * SL.art_scan_rows(25, 16)
    assert c["done0"] == 4 * (2 + phases), (out, log)                             # natives of mode 1 (the harness's) + 0
    # mode 1 -> 2: the kept natives (1, 0) + the new mode's native + its enlarges; old-mode enlarges gone
    assert c["done"] == 4 * (3 + phases) and c["doneenlold"] == 0, (out, log)
    assert c["dropped"] == 4 * phases and c["donenewscan"] == 4 * (1 + phases), (out, log)
    assert c["mismatch"] == 0 and c["missing"] == 0 and c["failed"] == 0, (out, log)


def test_restart_after_the_image_set_changed_rebuilds_everything(tmp_path, exe):
    d = game(tmp_path, exe)
    out, log = probe(d, "restartimg", 25, 1, d / "pal.bin")
    c = kv(out)
    phases = 2 * SL.art_scan_rows(25, 16)
    assert c["done0"] == 4 * (2 + phases) and c["donemid"] == 0, (out, log)      # pack off: nothing reachable, all freed
    assert c["done"] == 4 * (2 + phases) and c["mismatch"] == 0 and c["missing"] == 0, (out, log)   # back on: rebuilt


@pytest.mark.parametrize("throw_every", [0, 5])
def test_restarts_palette_changes_and_exceptions_under_concurrent_lookups(tmp_path, exe, throw_every):
    """A second thread restarts the worker every ~400 ms (scan mode cycling, the palette perturbed, two restarts back to
    back) while the main thread looks random jobs up and checks every hit against the plain law under the palette that
    keyed it; with throw_every, every 5th job throws bad_alloc.  Nothing may mismatch, hang, or stay 'running'.
    The harness runs >= 6 s AND until 8 restarts, 30 lookups and a hit have happened (a taken-over job costs the
    lookup thread a bake, so a loaded machine fitted fewer than 30 into a fixed 6 s); `capped` = its 300 s hang
    bound ran out first."""
    d = game(tmp_path, exe)
    args = ["stress", 25, 1, d / "pal.bin", 6000] + ([throw_every] if throw_every else [])
    out, log = probe(d, *args)
    c = kv(out)
    assert c["capped"] == 0, (out, log)                                                # the main thread never hung
    assert c["restarts"] >= 8 and c["lookups"] >= 30, (out, log)
    assert c["hits"] >= 1, (out, log)                                                  # results do get reused under the churn
    assert c["mismatch"] == 0 and c["final_mismatch"] == 0, (out, log)
    assert c["running"] == 0, (out, log)                                               # no orphaned job after it all
    if throw_every:
        assert "exception" in log or c["failed"] >= 1 or c["done"] >= 1, (out, log)


def test_an_access_violation_in_a_job_fails_it_and_three_stop_the_worker(tmp_path, exe):
    d = game(tmp_path, exe)
    out, log = probe(d, "sehfault", 3, 25, 1, d / "pal.bin")
    c = kv(out)
    assert c["failed"] == 3 and c["failedmiss"] == 3, (out, log)       # each failed key: one "failed" miss, then taken over
    assert c["done"] == 6 and c["queued"] == c["entries"] - 9, (out, log)   # jobs 3, 6, 9 faulted; stopped after the third
    assert c["mismatch"] == 0 and c["missing"] == 0, (out, log)


def test_a_worker_dying_inside_the_lock_never_hangs_the_game_thread(tmp_path, exe):
    d = game(tmp_path, exe)
    out, log = probe(d, "orphan", 25, 1, d / "pal.bin")
    c = kv(out)
    assert c["dead"] == 1, (out, log)                                  # remembered: no later call pays the bound
    # one bounded wait (the first call's), which latches the dead state; every later entry returns on it at once
    # (each checks `dead` first).  (Was `ms < 1500` for the 100 calls.)
    assert c["calls"] == 100 and c["deadafterfirst"] == 1, (out, log)


def test_a_fault_outside_any_job_stops_the_worker_without_orphaning_the_lock(tmp_path, exe):
    d = game(tmp_path, exe)
    out, log = probe(d, "thunkfault", 25, 1, d / "pal.bin")
    c = kv(out)
    assert c["running"] == 0 and c["dead"] == 0, (out, log)            # reported through the handler: the lock is free
    # every key a miss: nothing is left running to wait on (the faulted job is failed), so each is prompt
    assert c["entries"] > 0 and c["hits"] == 0 and c["misses"] == c["entries"], (out, log)
    assert "faulted" in log


def test_a_worker_dying_mid_job_ends_the_wait_by_the_reaper(tmp_path, exe):
    d = game(tmp_path, exe)
    out, log = probe(d, "diewait", 25, 1, d / "pal.bin")
    c = kv(out)
    assert c["found"] == 1, (out, log)
    # reaped within the slices (the job is FAILED: kFailed), not timed out at the 4 s bound (kRunningTimeout = 4)
    assert c["hit"] == 0 and c["why"] == WHY_FAILED, (out, log)
    assert c["running"] == 0, (out, log)


@pytest.mark.parametrize("ms,die", [(600, 0), (1500, 0), (300, 1), (0, 2)])
def test_files_lock_latches_only_for_a_dead_holder(tmp_path, exe, ms, die):
    """The harness starts Find only once the holder OWNS the lock (it used to give the below-normal holder 20 ms, and a
    loaded machine had not run it by then: Find found the lock free).  Outcomes, not milliseconds: `same` says whether
    the first Find's image went into the cache (it took the lock) or was decoded uncached (it bypassed); `dead` whether
    the bypass latched; `heldatreturn` whether Find came back while the holder still held the lock."""
    d = game(tmp_path, exe)
    out, log = probe(d, "fileslock", ms, die, "gaians")
    c = kv(out)
    assert c["first"] == 1 and c["second"] == 1, (out, log)             # Find always answers
    if die == 2:                                                       # orphaned by the calling thread itself
        assert c["dead"] == 1 and c["same"] == 0, (out, log)           # latched at once (the owner is THIS thread)
    elif die:
        # the holder died holding it: past the bound the bypass latches, and both calls decode uncached; the second
        # never waits again (Locked returns on the latch before trying the lock)
        assert c["contended"] == 1 and c["dead"] == 1 and c["same"] == 0, (out, log)
    elif ms < 1000:
        # a live holder inside the bound: Find waited for it -- it took the lock and cached (same), never bypassed
        assert c["contended"] == 1 and c["heldatreturn"] == 0, (out, log)
        assert c["dead"] == 0 and c["same"] == 1, (out, log)
    else:
        assert c["dead"] == 0, (out, log)                              # past the bound: NO latch for a live holder


@pytest.mark.parametrize("text,want,fmt", [
    ("2,0,1,3", (2, 0, 1, 3), "2,0,1,3"), ("", (-1, -1, -1, -1), "-1,-1,-1,-1"), ("5", (5, -1, -1, -1), "5,-1,-1,-1"),
    ("-1,2,-1,3", (-1, 2, -1, 3), "-1,2,-1,3"), ("x,2", (-1, -1, -1, -1), "-1,-1,-1,-1"), ("99,1", (-1, 1, -1, -1), "-1,1,-1,-1"),
    (" 1 , 2 ,3,4,5,6", (1, 2, 3, 4), "1,2,3,4"), ("12,13,0,63", (12, 13, 0, 63), "12,13,0,63"),
])
def test_ini_phases_parse_and_format(exe, text, want, fmt):
    r = subprocess.run([str(exe), "phases", text], capture_output=True, text=True, check=True)
    vals, s = r.stdout.split("|")[0].split(), r.stdout.split("|")[1]
    assert tuple(int(v) for v in vals) == want and s == fmt, r.stdout


def test_no_images_means_no_jobs(tmp_path, exe):
    d = game(tmp_path, exe, images=False)
    out, log = probe(d, "run", 40, 1, d / "pal.bin")
    assert kv(out)["entries"] == 0, (out, log)
