"""The movie player's pure pacing logic (src\\uimod\\src\\moviepace.h), driven through
moviepace_selftest.cpp: decoder-thread count, the affinity widen/poll/restore rules, the skip and discard
verdicts and the sound timeline. Plus source pins on movie.cpp for the rules that live in the shell.

Built once per module with the VS x86 toolchain (a run per test is a few milliseconds). No game launch.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cpp_harness  # noqa: E402

SRC = HERE / "moviepace_selftest.cpp"
MOVIE = HERE.parent.parent / "src" / "uimod" / "src" / "movie.cpp"


@pytest.fixture(scope="module")
def exe():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    return cpp_harness.build(SRC, "moviepace_selftest_")


def run(exe, *args) -> str:
    r = subprocess.run([str(exe), *map(str, args)], capture_output=True, timeout=30)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    return r.stdout.decode().replace("\r\n", "\n").strip()


def fields(line: str) -> dict:
    return {k: float(v) for k, v in (t.split("=") for t in line.split())}


# ---------------------------------------------------------------- decoder threads

@pytest.mark.parametrize("cores,want", [(0, 1), (1, 1), (2, 1), (3, 2), (4, 3), (5, 4), (6, 4), (8, 4), (32, 4), (64, 4)])
def test_threads_are_cores_minus_one_capped_at_four(exe, cores, want):
    assert run(exe, "threads", cores) == str(want)


def test_core_count_uses_the_widened_mask_not_the_pin(exe):
    table = ["3", "c", "30", "c0"]                  # four cores, two hardware threads each
    assert run(exe, "cores", "1", *table) == "1", "pinned to one CPU: one core"
    assert run(exe, "cores", "ff", *table) == "4", "widened: all four"


def test_core_count_on_a_machine_folded_by_wow64(exe):
    """More than 32 CPUs: core masks repeat once folded onto 32 bits. Duplicates count once, and never more
    than the CPUs in the mask."""
    table = ["3", "c", "3", "c", "30"]
    assert run(exe, "cores", "ffffffff", *table) == "3"
    assert run(exe, "cores", "1", "3", "3", "3") == "1"
    assert run(exe, "cores", "ffffffff", *[f"{1 << (i % 32):x}" for i in range(64)]) == "32"


@pytest.mark.parametrize("cpus,want", [(0, 1), (1, 1), (2, 1), (4, 2), (8, 4), (64, 32)])
def test_unknown_topology(exe, cpus, want):
    assert run(exe, "cpus", cpus) == str(want)


# ---------------------------------------------------------------- whether to widen

@pytest.mark.parametrize("proc,sys_,want", [
    ("1", "ff", 1), ("4", "ff", 1), ("80000000", "ffffffff", 1),     # one CPU of many: DDrawCompat's shape
    ("ff", "ff", 0),                                                  # not pinned: nothing to do
    ("3", "ff", 0),                                                   # a deliberate partial mask is left alone
    ("1", "1", 0),                                                    # a one-CPU machine
    ("0", "ff", 0), ("1", "0", 0),                                    # the call failed
    ("100", "ff", 0),                                                 # outside the system mask: nonsense
])
def test_is_pinned(exe, proc, sys_, want):
    assert run(exe, "pinned", proc, sys_) == str(want)


@pytest.mark.parametrize("before,after,want", [("1", "ff", 1), ("1", "1", 0), ("1", "2", 0), ("1", "0", 0)])
def test_a_widen_counts_only_when_the_read_back_has_more_cpus(exe, before, after, want):
    """("1", "2"): DDrawCompat's rotation landed between our set and our read."""
    assert run(exe, "took", before, after) == str(want)


@pytest.mark.parametrize("w,h,want", [(320, 240, 0), (400, 192, 0), (592, 288, 0), (640, 480, 0), (641, 480, 1),
                                      (1278, 614, 1), (2368, 1152, 1), (0, 0, 0)])
def test_the_originals_stay_on_one_cpu(exe, w, h, want):
    assert run(exe, "wants", w, h) == str(want)


# ---------------------------------------------------------------- polling and restoring

def affinity(exe, *events) -> list[str]:
    return run(exe, "affinity", *events).split("\n")


def test_a_quiet_movie_restores_the_original_pin(exe):
    out = affinity(exe, "widen:1:ff", "poll:ff", "poll:ff", "restore:ff")
    assert out == ["widened pinned=1 wide=ff", "poll=0 pinned=1 repins=0", "poll=0 pinned=1 repins=0", "restore=1 to=1"]


def test_a_rotation_is_rewidened_and_the_newest_pin_is_what_comes_back(exe):
    out = affinity(exe, "widen:1:ff", "poll:2", "back:ff", "poll:ff", "poll:4", "back:ff", "restore:ff")
    assert out[1] == "poll=1 pinned=2 repins=1"
    assert out[-1] == "restore=1 to=4", "not the stale 1"


def test_never_restores_over_a_newer_pin(exe):
    assert affinity(exe, "widen:1:ff", "restore:2")[-1] == "restore=0 to=1"


def test_stops_fighting_after_three_failed_rewidens(exe):
    out = affinity(exe, "widen:1:ff", "poll:2", "back:2", "poll:2", "back:2", "poll:2", "back:2", "poll:2", "restore:2")
    assert out[6] == "gaveup=1"
    assert out[7].startswith("poll=0"), "no more attempts"
    assert out[8].startswith("restore=0"), "nothing of ours to undo"


def test_one_good_rewiden_clears_the_failure_streak(exe):
    out = affinity(exe, "widen:1:ff", "poll:2", "back:2", "poll:2", "back:2", "poll:2", "back:ff",
                   "poll:2", "back:2", "poll:2", "back:2")
    assert out[-1] == "gaveup=0"


def test_a_restore_took_once_the_mask_is_no_longer_ours(exe):
    assert affinity(exe, "widen:1:ff", "took:ff")[-1] == "took=0"
    assert affinity(exe, "widen:1:ff", "took:1")[-1] == "took=1"
    assert affinity(exe, "widen:1:ff", "took:2")[-1] == "took=1", "a rotation in between: pinned again either way"


def test_no_state_no_action(exe):
    assert affinity(exe, "poll:2")[0].startswith("poll=0")
    assert affinity(exe, "restore:ff")[0].startswith("restore=0")


# ---------------------------------------------------------------- the frame loop on a virtual clock

def sim(exe, *args) -> dict:
    return fields(run(exe, "sim", *args))


def test_keeping_up_draws_everything(exe):
    r = sim(exe, 300, 33.3, 5, 5)
    assert r["skipped"] == 0 and r["shown"] == 300 and r["entries"] == 0


def test_jitter_under_a_frame_never_skips(exe):
    r = sim(exe, 300, 33.3, 30, 3, 1)
    assert r["skipped"] == 0 and r["entries"] == 0


def test_too_slow_to_draw_every_frame_catches_up_by_skipping(exe):
    """Decoding is fast enough, drawing every frame is not: every so often a frame is skipped and the lateness
    stays bounded."""
    r = sim(exe, 900, 33.3, 10, 40)
    assert 0 < r["skipped"] < 900
    assert r["finallate"] < 2 * 33.3, r


def test_a_picture_appears_at_least_four_times_a_second_when_hopeless(exe):
    r = sim(exe, 300, 33.3, 60, 30)
    assert r["worstgap"] <= 250 + 60 + 30, r
    assert r["shown"] > 10


def test_a_one_off_stall_is_recovered(exe):
    r = sim(exe, 300, 33.3, 5, 5, 1, 100, 800)
    assert r["skipped"] > 5
    assert r["entries"] == 1
    assert r["discard_end"] == 0, "the discard ended once caught up"
    assert r["last_drawn"] == 1 and r["finallate"] <= 0.01


def test_discarding_is_not_asked_for_without_permission(exe):
    r = sim(exe, 300, 33.3, 5, 5, 0, 100, 800)
    assert r["entries"] == 0


def test_a_slow_clip_at_15fps_is_not_called_late_by_the_30fps_threshold(exe):
    r = sim(exe, 150, 66.7, 45, 15)
    assert r["skipped"] == 0


def test_first_frame_always_shows_however_slow(exe):
    r = sim(exe, 1, 33.3, 5000, 5000)
    assert r["shown"] == 1 and r["skipped"] == 0


def test_a_stream_with_no_reference_frames_cannot_leave_the_picture_frozen(exe):
    out = run(exe, "stuck", 40).split("\n")
    assert out == ["before=1", "after=0", "again=0"], "switched off, and it stays off"


def test_a_short_gap_in_frames_does_not_turn_discarding_off(exe):
    assert run(exe, "stuck", 8).split("\n")[1] == "after=1"


# ---------------------------------------------------------------- the end of the movie

@pytest.mark.parametrize("eof,length,pkt,want", [
    (0, 60000, 1000, 0), (0, 60000, 57999, 0), (0, 60000, 58000, 1), (0, 60000, 60000, 1),
    (1, 60000, 1000, 1),                                              # the file has run out
    (0, 0, 1000, 1), (0, -1, 1000, 1),                                # length unknown: never discard
])
def test_near_end(exe, eof, length, pkt, want):
    assert run(exe, "nearend", eof, length, pkt) == str(want)


# ---------------------------------------------------------------- reading ahead for the sound

@pytest.mark.parametrize("live,lead,queued,bytes_,want", [
    (0, 0, 0, 0, 1), (1, 9999, 0, 0, 1),                              # nothing queued: always read
    (0, 0, 1, 1000, 0),                                               # no sound: one packet at a time, as ever
    (1, 100, 1, 1000, 1), (1, 499, 399, 1000, 1),                     # a whole 250-frame GOP fits
    (1, 500, 1, 1000, 0),                                             # far enough ahead
    (1, 100, 400, 1000, 0), (1, 100, 2, 24 << 20, 0),                 # bounded in packets and in bytes
])
def test_want_demux(exe, live, lead, queued, bytes_, want):
    assert run(exe, "demux", live, lead, queued, bytes_) == str(want)


@pytest.mark.parametrize("late,want", [(0, 0), (500, 0), (999, 0), (1000, 1), (5000, 1)])
def test_drop_to_keyframe_is_the_last_resort(exe, late, want):
    assert run(exe, "drop", late) == str(want)


def audio(exe, *events) -> dict:
    return fields(run(exe, "audio", *events))


def test_sound_before_the_first_picture_is_counted_as_lead(exe):
    assert audio(exe, "q:300", "q:46", "lead:0")["lead"] == 346


def test_sound_starts_with_the_first_picture(exe):
    r = audio(exe, "q:300", "start:1000", "lead:1100")
    assert r["lead"] == 200 and r["shift"] == 0


def test_a_steady_feed_never_shifts_the_picture(exe):
    events = ["q:500", "start:0"] + [f"sub:{t}:46" for t in range(0, 4600, 46)] + ["lead:4600"]
    r = audio(exe, *events)
    assert r["shift"] == 0 and r["under"] == 0


def test_a_starved_queue_moves_the_picture_by_exactly_the_gap(exe):
    r = audio(exe, "q:100", "start:1000", "sub:1400:46", "lead:1400")
    assert r["shift"] == 300 and r["under"] == 1
    assert r["lead"] == 46


def test_sound_before_a_late_first_picture_keeps_only_the_newest_second(exe):
    out = run(exe, "audio", "q:800", "trim:1000", "q:800", "trim:1000", "lead:0").split("\n")
    assert out == ["drop=0.0", "drop=600.0", "lead=1000.0 shift=0.0 under=0"]


def test_refused_sound_stops_steering_the_picture(exe):
    r = audio(exe, "q:100", "start:1000", "refused:0", "sub:1400:46", "sub:2000:46", "lead:2000")
    assert r["shift"] == 0 and r["under"] == 0
    assert r["lead"] == 46, "the lead still counts what is read, so reading goes on"


def test_every_gap_adds_up(exe):
    r = audio(exe, "q:0", "start:0", "sub:100:50", "sub:300:50", "lead:300")
    assert r["shift"] == 250 and r["under"] == 2


# ---------------------------------------------------------------- the shell: rules that live in movie.cpp

@pytest.fixture(scope="module")
def movie() -> str:
    return MOVIE.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")


def test_affinity_is_set_through_ntdll_and_read_back(movie):
    assert "NtSetInformationProcess" in movie
    assert not re.search(r"\bSetProcessAffinityMask\s*\(", movie), "DDrawCompat swallows the kernel32 call"
    widen = movie[movie.index("void WidenAffinity()"):movie.index("void RestoreAffinity()")]
    assert widen.index("SetProcessMaskNt(sys)") < widen.index("after = CurrentProcessMask()")


def test_the_widen_comes_before_the_thread_count_and_the_open(movie):
    body = movie[movie.index("void DecodeAndPlay("):]
    assert body.index("WidenAffinity()") < body.index("DecoderThreadCount()") < body.index("avcodec_open2(ctx")
    assert "thread_count = 0" not in body


def test_the_restore_is_on_the_one_path_every_exit_shares(movie):
    guarded = movie[movie.index("void PlayGuarded("):movie.index("} // namespace", movie.index("void PlayGuarded("))]
    assert guarded.index("__except") < guarded.index("__finally") < guarded.index("RestoreAffinity()"), \
        "in the __finally around the handler, so the SEH path and a caught exception are covered"
    assert "RestoreAffinity" not in movie[movie.index("void DecodeAndPlay("):movie.index("DWORD DelayLoadFilter")]


def test_the_watchdog_is_stopped_before_the_restore_and_only_it_polls(movie):
    restore = movie[movie.index("void RestoreAffinity()"):movie.index("int DecoderThreadCount()")]
    assert restore.index("StopWatchdog()") < restore.index("SetProcessMaskNt(g_affinity.pinned)")
    assert "PollAffinity()" not in movie[movie.index("void DecodeAndPlay("):movie.index("DWORD DelayLoadFilter")], \
        "g_affinity has one writer while the movie plays"
    start = movie.index("void WidenAffinity()")
    assert movie.index("OnWidened(g_affinity", start) < movie.index("StartWatchdog();", start)


def test_every_read_of_sound_reaches_the_device_as_one_buffer(movie):
    body = movie[movie.index("void DecodeAndPlay("):movie.index("DWORD DelayLoadFilter")]
    assert body.count("sink->Submit(") == 1, "XAudio2 refuses past 64 queued buffers"
    assert body.index("demuxEof = true") < body.index("submitAudio();\n        if (queue.empty())")


def test_the_affinity_state_needs_no_unwinding(movie):
    assert re.search(r"^moviepace::AffinityState g_affinity;", movie, re.M), "file scope: SEH unwinds no C++ frame"


def test_no_game_address_was_added_to_the_shared_player(movie):
    """The DLL loads on the pristine exe too, where cave addresses do not exist."""
    assert "0xA1" not in movie.replace("0xA1)", "") and "pcave" not in movie


def test_the_schedule_does_not_use_the_coarse_clock(movie):
    body = movie[movie.index("void DecodeAndPlay("):movie.index("DWORD DelayLoadFilter")]
    assert "GetTickCount" not in body


def test_every_frame_goes_through_pump_or_hold(movie):
    body = movie[movie.index("auto showFrames"):movie.index("auto feedAudio")]
    skip = body[body.index("moviepace::kSkip"):body.index("scaleToBack(frm)")]
    assert "Pump(&skip)" in skip and "av_frame_move_ref(held, frm)" in skip


def test_a_drop_leaves_the_keyframe_and_everything_after_it(movie):
    start = movie.index("ShouldDropToKeyframe(pacer.LateMs())")
    assert "haveBasePts &&" in movie[start - 40:start], "no timestamps, no knowing which keyframe is due"
    body = movie[start:movie.index("AVPacket* q = takePacket(0);\n        ctx->skip_frame")]
    assert "i-- > 1" in body, "a keyframe at the front is no jump"
    assert "> now) continue" in body, "never a jump into the future"
    assert "n < i" in body and "AV_PKT_FLAG_KEY" in body, "only the packets before it go"


def test_the_last_frame_reaches_the_back_buffer(movie):
    tail = movie[movie.index("const bool eof = demuxEof"):movie.index("RunMovieCaption")]
    assert tail.index("avcodec_send_packet(ctx, nullptr)") < tail.index("scaleToBack(held)")
