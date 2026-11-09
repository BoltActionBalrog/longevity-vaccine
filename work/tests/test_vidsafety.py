"""uimod display-topology safety (src/uimod/src/vidsafety.h, driven from vidmode.cpp / vidwatch.cpp / gpuscale.cpp).

2026-10-24: a monitor that changed identity mid-game dropped off the bus during driver resets; Windows moved the
native-4K Fullscreen window onto the portrait second monitor, and the old code took that system reposition for
PRACX's own SetWindowed(false), converted the game to the scaled popup there, made it topmost over a topmost
black backdrop and clipped the pointer to it -- with the D3D device then created on the game thread mid-reset.
The user had to power the PC off.

tests/vidsafety_selftest.cpp builds a scripted world (monitors, the game window, PRACX's SetWindowed / WM_USER+3 /
SC_MAXIMIZE / SetMinimised, our posted messages and the safety timer, the watchdog's releases and probes) around
the real Controller, so these tests replay message sequences and check the window state after each step:

1. the incident, in both message orders: nothing converges, nothing is held while the topology moves or while the
   game's monitor is gone, the game is never moved to the other monitor on its own, native again when it returns;
2. the audit's adversarial scenarios A-H (2026-10-25) as regressions -- USB / work-area notices with an unchanged
   monitor set change nothing, a flapping monitor converts nothing, no log spam with no monitor, a renumbered
   device name does not fool the home match, PRACX's own mode switch is no topology event;
3. topmost / the clip only while the game is the foreground window; a restore waits for the game to be active; the
   user's own actions (a mode picked, leaving and coming back) end a wait for a vanished monitor;
4. PRACX's own SetWindowed(false) still converges (once; a lost converge is re-posted when its latch expires);
5. the backdrop follows the window's monitor; storms; the escape hotkey; a Windows scaling change; the model gaps
   the audit listed (deactivation minimise, a stalled game thread, the hotkey under one, stale probes, a monitor
   list that changes after its notice, a non-foreground boot);
6. the watchdog's decision (stalls measured, never a release on one), the GPU device life (quiet gate, back-off),
   the backdrop owner decided once, the hotkey parser;
7. the source facts the DLL relies on.
"""
from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

import cpp_harness

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "tests" / "vidsafety_selftest.cpp"
UIMOD = ROOT.parent / "src" / "uimod" / "src"
pytestmark = pytest.mark.skipif(not cpp_harness.have_toolchain(), reason="Visual Studio x86 toolchain not available")

G80 = "mon DISPLAY1 0 0 3840 2160 primary"
DELL = "mon DISPLAY2 -1440 -207 0 2353"
FULL, BORDERLESS, WINDOWED = 0, 1, 2
QUIET = 3000                     # vidsafety::kQuietMs (pinned in test_constants)
SETTLE = QUIET + 100             # one timer tick past it


@pytest.fixture(scope="module")
def exe():
    return cpp_harness.build(SRC, "vidsafety_selftest_")


def run(exe, mode: str, stdin: str = "", *args: str) -> str:
    r = subprocess.run([str(exe), mode, *args], input=stdin.encode(), capture_output=True, timeout=60)
    assert r.returncode == 0, (r.stdout + r.stderr).decode("utf-8", "replace")
    return r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")


def _val(v: str):
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+(,-?\d+){3}", v):
        return tuple(int(x) for x in v.split(","))
    return v


ORDERS: list[list[str]] = []   # the `order` lines of the last script() run
FX: list[str] = []             # the `trace 1` effect changes of the last script() run ("clip 0", "topmost 1", "mark x")


def script(exe, text: str) -> tuple[dict[str, dict], list[str]]:
    """Run a scenario; return {dump label: state} and the controller's log lines (`order` lines go to ORDERS, the
    traced effects to FX)."""
    out = run(exe, "script", "\n".join(line.strip() for line in text.strip().splitlines()) + "\n")
    dumps, logs = {}, []
    ORDERS.clear()
    FX.clear()
    for line in out.splitlines():
        if line.startswith("fx "):
            FX.append(line[3:])
            continue
        if line.startswith("dump "):
            parts = line.split()
            dumps[parts[1]] = {k: _val(v) for k, v in (p.split("=", 1) for p in parts[2:])}
        elif line.startswith("log "):
            logs.append(line[4:])
        elif line.startswith("order"):
            ORDERS.append(line.split()[1:])
        else:
            raise AssertionError(f"unexpected harness output: {line}")
    return dumps, logs


def released(d: dict) -> None:
    """Nothing that can trap the user is held."""
    assert d["clip"] == 0, d
    assert d["topmost"] == 0, d
    assert d["bd"] == 0, d


def held_native(d: dict, rect=(0, 0, 3840, 2160)) -> None:
    assert d["fW"] == 0 and d["mode"] == FULL and d["win"] == rect, d
    assert d["topmost"] == 1 and d["clip"] == 1 and d["clipRect"] == rect and d["bd"] == 0, d


def fit(mon, sw, sh):
    l, t, r, b = mon
    mw, mh = r - l, b - t
    w, h = mw, mh
    if mw * sh <= mh * sw:
        h = mw * sh // sw
    else:
        w = mh * sw // sh
    x, y = l + (mw - w) // 2, t + (mh - h) // 2
    return (x, y, x + w, y + h)


# ---- 1. the incident ----------------------------------------------------------------------------------------------

REMOVE_BURST = {
    # Kernel-PnP first (the list has not changed yet), then Windows re-homes the window, then the mode broadcast
    "pnp_first": """
        display devnodes
        unmon DISPLAY1
        mon DISPLAY2 0 0 1440 2560 primary
        win 0 0 1440 2560
        display displaychange
    """,
    # the worst order: the reposition reaches the window before any display message
    "reposition_first": """
        unmon DISPLAY1
        mon DISPLAY2 0 0 1440 2560 primary
        win 0 0 1440 2560
        dump moved_before_event
        display displaychange
        display devnodes
    """,
}
RETURN_BURST = """
    mon DISPLAY2 -1440 -207 0 2353 primary
    display devnodes
    mon DISPLAY1 0 0 3840 2160 primary
    win -1440 568 0 1378
    display displaychange
    display workarea
"""


@pytest.mark.parametrize("order", sorted(REMOVE_BURST))
def test_incident_monitor_removed_and_back(exe, order):
    d, logs = script(exe, f"""
        {G80}
        {DELL}
        bb 3840 2160
        boot
        dump boot
        {REMOVE_BURST[order]}
        pump
        dump removed
        wait {QUIET - 100}
        dump still_quiet
        wait 200
        dump settled
        wait 20000
        dump much_later
        {RETURN_BURST}
        pump
        dump back
        wait {SETTLE}
        dump restored
    """)
    held_native(d["boot"])
    assert d["boot"]["home"] == "DISPLAY1"

    # the system reposition is no PRACX path: no converge, no SetWindowed, m_fWindowed untouched -- and never a move to
    # the Dell: while the game's monitor is gone nothing is held at all
    for k in ("removed", "still_quiet", "settled", "much_later"):
        released(d[k])
        assert d[k]["converges"] == 0 and d[k]["setWindowed"] == 0 and d[k]["fW"] == 0 and d[k]["restores"] == 0, (k, d[k])
    assert d["removed"]["quiet"] == 1 and d["still_quiet"]["quiet"] == 1
    assert d["settled"]["quiet"] == 0 and d["settled"]["await"] == 1 and d["settled"]["timer"] == 0
    assert d["much_later"]["await"] == 1
    assert not any(line.startswith("converge:") for line in logs)
    assert sum("monitor is gone" in line for line in logs) == 1

    released(d["back"])
    # the G80 is back: the user's monitor, the backbuffer's size -> PRACX's own Fullscreen there
    r = d["restored"]
    held_native(r)
    assert r["on"] == "DISPLAY1" and r["await"] == 0 and r["restores"] == 1 and r["converges"] == 0 and r["timer"] == 0


def test_incident_reposition_before_any_event_releases_at_once(exe):
    """The monitor list changed under the window before any display message: that placement is the event."""
    d, _ = script(exe, f"""
        {G80}
        {DELL}
        boot
        {REMOVE_BURST["reposition_first"]}
        dump x
    """)
    m = d["moved_before_event"]
    released(m)
    assert m["quiet"] == 1 and m["converges"] == 0 and m["fW"] == 0 and m["queue"] == 0 and m["gpuEvents"] == 1


def test_incident_while_away_the_return_to_the_game_adopts_the_monitor(exe):
    """The user was on another window when the monitor went: coming back to the game is their choice of monitor."""
    d, _ = script(exe, f"""
        {G80}
        {DELL}
        boot
        fg 0
        dump away
        {REMOVE_BURST["pnp_first"]}
        wait {SETTLE}
        dump settled
        fg 1
        dump activated
        wait 200
        dump restored
    """)
    released(d["away"])
    assert d["away"]["iconic"] == 1, "PRACX minimises its Fullscreen when the game is left"
    s = d["settled"]
    released(s)
    assert s["owed"] == 1 and s["quiet"] == 0 and s["timer"] == 0 and s["restores"] == 0, "nothing re-placed behind the user's back"
    assert d["activated"]["timer"] == 1, "activation re-arms the restore (it runs from the timer, not inside WM_ACTIVATE)"
    r = d["restored"]
    assert r["owed"] == 0 and r["fW"] == 1 and r["on"] == "DISPLAY2" and r["topmost"] == 1 and r["clip"] == 1
    assert r["home"] == "DISPLAY1" and r["adopted"] == "DISPLAY2", "provisional: home stays the 4K monitor"


def test_waiting_for_the_monitor_ends_when_the_user_leaves_and_returns(exe):
    d, logs = script(exe, f"""
        {G80}
        {DELL}
        boot
        {REMOVE_BURST["pnp_first"]}
        wait {SETTLE}
        dump waiting
        fg 0
        fg 1
        wait 200
        dump adopted
    """)
    released(d["waiting"])
    assert d["waiting"]["await"] == 1
    a = d["adopted"]
    assert a["await"] == 0 and a["fW"] == 1 and a["on"] == "DISPLAY2" and a["topmost"] == 1 and a["clip"] == 1
    assert any("re-activated" in line for line in logs)


def test_waiting_for_the_monitor_ends_when_the_user_picks_a_mode(exe):
    d, _ = script(exe, f"""
        {G80}
        {DELL}
        boot
        {REMOVE_BURST["pnp_first"]}
        wait {SETTLE}
        user fullscreen
        pump
        dump picked
    """)
    p = d["picked"]
    assert p["await"] == 0 and p["fW"] == 1 and p["mode"] == FULL and p["on"] == "DISPLAY2"
    assert p["home"] == "DISPLAY1" and p["adopted"] == "DISPLAY2", "a pick with home gone is provisional"
    assert p["topmost"] == 1 and p["clip"] == 1 and p["bd"] == 1


def test_never_topmost_or_clipped_while_not_foreground(exe):
    """Through a whole session: every dump with fg=0 holds nothing."""
    d, _ = script(exe, f"""
        {G80}
        {DELL}
        bb 1600 1200
        boot
        dump scaled
        fg 0
        dump away1
        fg 1
        dump back1
        user borderless
        fg 0
        dump away2
        fg 1
        user fullscreen
        dump full
        fg 0
        display displaychange
        wait {SETTLE}
        dump away3
    """)
    for k, v in d.items():
        if v["fg"] == 0:
            assert v["topmost"] == 0 and v["clip"] == 0, (k, v)
            assert not (v["bd"] == 1 and v["bdTop"] == 1), (k, v)
    assert d["scaled"]["topmost"] == 1 and d["scaled"]["clip"] == 1 and d["scaled"]["bd"] == 1
    assert d["away1"]["iconic"] == 1 and d["away1"]["bd"] == 0, "scaled Fullscreen minimises when left, backdrop gone"
    assert d["back1"]["iconic"] == 0 and d["back1"]["topmost"] == 1 and d["back1"]["clip"] == 1 and d["back1"]["bd"] == 1
    assert d["away2"]["iconic"] == 0 and d["away2"]["bd"] == 1 and d["away2"]["bdTop"] == 0, "Borderless stays, not topmost"
    assert d["full"]["mode"] == FULL and d["full"]["topmost"] == 1


def test_boot_without_foreground_holds_nothing(exe):
    d, _ = script(exe, f"""
        {G80}
        bb 1600 1200
        fg 0
        boot
        dump boot
        fg 1
        dump active
    """)
    b = d["boot"]
    assert b["topmost"] == 0 and b["clip"] == 0 and b["fW"] == 1 and b["mode"] == FULL
    assert not (b["bd"] == 1 and b["bdTop"] == 1)
    assert d["active"]["topmost"] == 1 and d["active"]["clip"] == 1 and d["active"]["bd"] == 1


# ---- 2. the audit's adversarial scenarios A-H (2026-10-25) --------------------------------------------------------

def test_audit_A_usb_plug_changes_nothing(exe):
    d, logs = script(exe, f"""
        {G80}
        {DELL}
        bb 1600 1200
        boot
        dump before
        display devnodes
        dump after_usb
        wait 1400
        dump at_1400
        wait 300
        dump at_1700
        wait 3000
        dump later
    """)
    for k in ("after_usb", "at_1400", "at_1700", "later"):
        v = d[k]
        assert v["bd"] == 1 and v["topmost"] == 1 and v["clip"] == 1 and v["quiet"] == 0 and v["gpuEvents"] == 0, (k, v)
    assert d["later"]["timer"] == 0, "the re-check window ends"
    assert sum("monitors unchanged" in line for line in logs) == 1


def test_audit_B_workarea_broadcasts_keep_nothing_released(exe):
    lines = [G80, DELL, "bb 1600 1200", "boot"]
    for i in range(30):
        lines += ["display workarea", "wait 1000", f"dump t{i}"]
    d, logs = script(exe, "\n".join(lines))
    assert all(v["clip"] == 1 and v["topmost"] == 1 and v["bd"] == 1 and v["gpuEvents"] == 0 for v in d.values())
    assert sum("display" in line for line in logs) <= 1


def test_audit_C_home_gone_the_game_is_not_moved_to_the_other_monitor(exe):
    d, _ = script(exe, f"""
        {G80}
        {DELL}
        bb 3840 2160
        boot
        display devnodes
        unmon DISPLAY1
        mon DISPLAY2 0 0 1440 2560 primary
        win 0 0 1440 2560
        display displaychange
        wait 1700
        dump gone_1700
        wait 2300
        dump gone_4000
        mon DISPLAY2 -1440 -207 0 2353
        mon DISPLAY1 0 0 3840 2160 primary
        display devnodes
        display displaychange
        wait {SETTLE}
        dump back
    """)
    for k in ("gone_1700", "gone_4000"):
        released(d[k])
        assert d[k]["setWindowed"] == 0 and d[k]["fW"] == 0 and d[k]["restores"] == 0, (k, d[k])
    assert d["gone_4000"]["await"] == 1
    b = d["back"]
    assert b["fW"] == 0 and b["on"] == "DISPLAY1" and b["win"] == (0, 0, 3840, 2160) and b["setWindowed"] == 0


def test_audit_D_a_flapping_monitor_converts_nothing(exe):
    lines = [G80, DELL, "bb 3840 2160", "boot"]
    for _ in range(5):
        lines += ["display devnodes", "unmon DISPLAY1", "mon DISPLAY2 0 0 1440 2560 primary", "win 0 0 1440 2560",
                  "display displaychange", "wait 2000",
                  "mon DISPLAY2 -1440 -207 0 2353", "mon DISPLAY1 0 0 3840 2160 primary", "display devnodes",
                  "display displaychange", "wait 2000"]
    lines += ["dump end", f"wait {SETTLE}", "dump settled"]
    d, logs = script(exe, "\n".join(lines))
    restores = [line for line in logs if "display: restore ->" in line]
    e = d["end"]
    released(e)
    assert e["restores"] == 0 and e["setWindowed"] == 0
    assert len(restores) <= 1, "at most the one restore after the flapping stopped"
    s = d["settled"]
    assert s["restores"] <= 1 and s["setWindowed"] == 0 and s["fW"] == 0 and s["on"] == "DISPLAY1"


def test_audit_E_no_monitor_logs_once(exe):
    d, logs = script(exe, f"""
        {G80}
        {DELL}
        bb 3840 2160
        boot
        unmon DISPLAY1
        unmon DISPLAY2
        display displaychange
        wait 10000
        dump nomon
    """)
    released(d["nomon"])
    assert sum("undecided" in line for line in logs) == 1


def test_audit_F_a_reused_device_name_does_not_fool_the_home_match(exe):
    d, _ = script(exe, f"""
        {G80}
        {DELL}
        bb 3840 2160
        boot
        display devnodes
        unmon DISPLAY1
        unmon DISPLAY2
        mon DISPLAY1 -1440 -207 0 2353
        mon DISPLAY3 0 0 3840 2160 primary
        win -1440 -207 0 2353
        display displaychange
        wait {SETTLE}
        dump renamed
    """)
    r = d["renamed"]
    assert r["on"] == "DISPLAY3" and r["fW"] == 0 and r["win"] == (0, 0, 3840, 2160), r
    assert r["home"] == "DISPLAY3", "the home record follows the monitor's current name"


def test_home_match_prefers_the_device_path(exe):
    """With device paths: the monitor whose path matches is home, even when it moved and the other one took its rect."""
    d, _ = script(exe, f"""
        mon DISPLAY1 0 0 3840 2160 primary path=G80
        mon DISPLAY2 -1440 -207 0 2353 path=DELL
        bb 3840 2160
        boot
        mon DISPLAY1 1440 0 5280 2160 path=G80
        mon DISPLAY2 0 0 1440 2560 primary path=DELL
        win 0 0 1440 2560
        display displaychange
        wait {SETTLE}
        dump x
    """)
    assert d["x"]["on"] == "DISPLAY1" and d["x"]["win"] == (1440, 0, 5280, 2160)


def test_audit_G_a_late_system_move_still_ends_native_on_the_4k_monitor(exe):
    d, _ = script(exe, f"""
        {G80}
        {DELL}
        bb 3840 2160
        boot
        display devnodes
        unmon DISPLAY1
        mon DISPLAY2 0 0 1440 2560 primary
        win 0 0 1440 2560
        display displaychange
        wait 1700
        mon DISPLAY2 -1440 -207 0 2353
        mon DISPLAY1 0 0 3840 2160 primary
        display displaychange
        win 0 0 1440 1080
        wait {SETTLE}
        dump after_late_move
    """)
    held_native(d["after_late_move"])


def test_audit_H_pracx_own_mode_switch_is_no_topology_event(exe):
    """[UIMod] FullscreenModeSwitch=1: PRACX's own ChangeDisplaySettings (on every minimise / restore) is marked by our
    wrapper on its import slot (vidmode.cpp MarkedDisplaySwitch). The audit's harness had no way to say whose switch
    a WM_DISPLAYCHANGE was; `ownswitch` is that mark."""
    d, logs = script(exe, f"""
        mon DISPLAY1 0 0 1600 1200 primary
        switch 1
        bb 1600 1200
        boot
        dump boot
        fg 0
        ownswitch 1
        mon DISPLAY1 0 0 3840 2160 primary
        display displaychange
        ownswitch 0
        wait 2000
        ownswitch 1
        mon DISPLAY1 0 0 1600 1200 primary
        fg 1
        display displaychange
        ownswitch 0
        dump back_0
        wait 1000
        dump back_1000
    """)
    assert d["boot"]["clip"] == 1
    for k in ("back_0", "back_1000"):
        assert d[k]["clip"] == 1 and d[k]["topmost"] == 1 and d[k]["quiet"] == 0 and d[k]["gpuEvents"] == 0, (k, d[k])


def test_legacy_switch_a_foreign_display_change_still_counts(exe):
    d, _ = script(exe, f"""
        mon DISPLAY1 0 0 1600 1200 primary
        switch 1
        bb 1600 1200
        boot
        mon DISPLAY2 1600 0 3520 1080
        display displaychange
        dump x
        wait {SETTLE}
        dump y
    """)
    released(d["x"])
    assert d["y"]["clip"] == 1 and d["y"]["setWindowed"] == 0


# ---- 4. PRACX's own path still converges --------------------------------------------------------------------------

def test_pracx_menu_toggle_from_scaled_fullscreen_converges_once(exe):
    d, logs = script(exe, f"""
        {G80}
        bb 1600 1200
        boot
        dump boot
        pracx-toggle
        dump toggled
        pump
        dump after
    """)
    b = d["boot"]
    assert b["fW"] == 1 and b["mode"] == FULL and b["win"] == fit((0, 0, 3840, 2160), 1600, 1200) and b["bd"] == 1
    assert d["toggled"]["fW"] == 0 and d["toggled"]["converges"] == 1
    a = d["after"]
    assert a["fW"] == 1 and a["mode"] == FULL and a["win"] == b["win"] and a["converges"] == 1 and a["queue"] == 0
    assert a["topmost"] == 1 and a["clip"] == 1 and a["bd"] == 1
    assert sum(line.startswith("converge: PRACX") for line in logs) == 1


def test_pracx_menu_toggle_from_windowed_converges(exe):
    d, _ = script(exe, f"""
        {G80}
        bb 1600 1200
        boot
        user windowed
        pump
        dump windowed
        pracx-toggle
        pump
        dump after
    """)
    assert d["windowed"]["mode"] == WINDOWED and d["windowed"]["topmost"] == 0 and d["windowed"]["clip"] == 0
    assert d["after"]["mode"] == FULL and d["after"]["fW"] == 1 and d["after"]["converges"] == 1


def test_lost_converge_is_posted_again_after_its_latch(exe):
    d, logs = script(exe, f"""
        {G80}
        bb 1600 1200
        boot
        lose-posted
        pracx-toggle
        pump
        dump lost
        wait 300
        dump latched
        wait 400
        dump after
    """)
    assert d["lost"]["fW"] == 0 and d["lost"]["converges"] == 1 and d["lost"]["timer"] == 1
    assert d["latched"]["converges"] == 1, "no re-post inside the latch (no storm)"
    a = d["after"]
    assert a["converges"] == 2 and a["fW"] == 1 and a["mode"] == FULL and a["timer"] == 0
    assert any("never arrived" in line for line in logs)


def test_native_size_monitor_never_converges(exe):
    d, _ = script(exe, f"""
        {G80}
        bb 3840 2160
        boot
        user windowed
        pump
        pracx-toggle
        pump
        wait 1000
        dump x
    """)
    assert d["x"]["converges"] == 0 and d["x"]["fW"] == 0 and d["x"]["timer"] == 0


# ---- 5. backdrop, storms, escape, scaling, the model gaps ---------------------------------------------------------

def test_backdrop_follows_the_window_to_another_monitor(exe):
    d, _ = script(exe, f"""
        {G80}
        mon DISPLAY2 3840 0 5760 1080
        bb 1600 1200
        boot
        user borderless
        dump b
        win 3840 0 5280 1080
        dump moved
    """)
    assert d["b"]["mode"] == BORDERLESS and d["b"]["bd"] == 1 and d["b"]["bdRect"] == (0, 0, 3840, 2160) and d["b"]["topmost"] == 0
    m = d["moved"]
    assert m["bd"] == 1 and m["bdRect"] == (3840, 0, 5760, 1080) and m["converges"] == 0 and m["bdTop"] == 0


def test_ignored_settings_change_is_no_event(exe):
    d, _ = script(exe, f"""
        {G80}
        boot
        display other
        dump x
    """)
    assert d["x"]["quiet"] == 0 and d["x"]["topmost"] == 1 and d["x"]["clip"] == 1


def test_storm_stays_released_and_logs_within_bounds(exe):
    burst = "\n".join("display displaychange\nwait 500" for _ in range(20))
    d, logs = script(exe, f"""
        {G80}
        {DELL}
        bb 1600 1200
        boot
        {burst}
        dump storm
        wait {SETTLE}
        dump settled
    """)
    released(d["storm"])
    assert d["storm"]["quiet"] == 1 and d["storm"]["owed"] == 0
    assert d["settled"]["quiet"] == 0 and d["settled"]["topmost"] == 1
    assert len([line for line in logs if line.startswith("display: WM_DISPLAYCHANGE")]) == 8, "kEventsLoggedPerBurst"
    assert any("20 events" in line for line in logs)


def test_monitor_list_that_changes_after_its_notice(exe):
    """A device notice arrives before the list changes, and no other message follows: the timer's re-check sees it."""
    d, _ = script(exe, f"""
        {G80}
        {DELL}
        bb 1600 1200
        boot
        display devnodes
        dump notice
        unmon DISPLAY2
        wait 200
        dump rechecked
        wait {SETTLE}
        dump settled
    """)
    assert d["notice"]["topmost"] == 1 and d["notice"]["timer"] == 1
    released(d["rechecked"])
    assert d["rechecked"]["quiet"] == 1 and d["rechecked"]["gpuEvents"] == 1
    assert d["settled"]["topmost"] == 1 and d["settled"]["on"] == "DISPLAY1"


def test_watchdog_only_event_releases_too(exe):
    d, _ = script(exe, f"""
        {G80}
        bb 1600 1200
        boot
        watchdog-display
        dump x
        wait {SETTLE}
        dump y
    """)
    released(d["x"])
    assert d["y"]["topmost"] == 1 and d["y"]["bd"] == 1


def test_escape_holds_everything_off_until_activated(exe):
    d, logs = script(exe, f"""
        {G80}
        bb 1600 1200
        boot
        escape
        dump escaped
        win 1120 0 2720 1200
        dump moved
        wait 1000
        dump later
        fg 0
        fg 1
        dump active
    """)
    for k in ("escaped", "moved", "later"):
        released(d[k])
        assert d[k]["escaped"] == 1
    a = d["active"]
    assert a["escaped"] == 0 and a["topmost"] == 1 and a["clip"] == 1 and a["bd"] == 1
    assert any(line.startswith("escape: hotkey") for line in logs)


def test_a_stalled_game_thread_keeps_everything_and_stale_probes_do_nothing(exe):
    """A game thread busy for seconds (a late-game AI turn), as the WINDOW sees it: it keeps its band, its clip and
    its backdrop through the stall, and the stale probes it answers afterwards arm no timer (nothing was released,
    nothing to re-state); nothing storms. The script harness has no watchdog model, so that the watchdog itself
    releases nothing is pinned by test_watchdog_never_releases_even_on_a_long_stall (its state machine) and
    test_watchdog_probe_loop_only_logs (its loop). (2026-11-08: the old release on Windows' hung test dropped a
    working game out of the topmost band at every 5 s AI turn.)"""
    d, _ = script(exe, f"""
        {G80}
        bb 1600 1200
        boot
        dump before
        hang
        wait 10000
        dump hung
        resume
        probe
        probe
        probe
        dump resumed
        wait 200
        dump after
    """)
    b = d["before"]
    for k in ("hung", "resumed", "after"):
        s = d[k]
        assert (s["topmost"], s["clip"], s["bd"]) == (b["topmost"], b["clip"], b["bd"]) == (1, 1, 1), (k, s)
    assert d["resumed"]["timer"] == 0 and d["resumed"]["queue"] == 0


def test_escape_under_a_stalled_game_thread(exe):
    """The user's way out of a game thread that truly hangs: the hotkey frees the pointer and the backdrop at once
    (the watchdog thread's own work); the leave-topmost request waits for the game thread (the documented limit)."""
    d, _ = script(exe, f"""
        {G80}
        bb 1600 1200
        boot
        hang
        escape
        dump hung
        resume
        dump resumed
        probe
        probe
        probe
        dump probed
        wait 200
        dump after
    """)
    h = d["hung"]
    assert h["clip"] == 0 and h["bd"] == 0 and h["topmost"] == 1, h
    assert d["resumed"]["topmost"] == 0
    # the release set the re-state flag: the first answered probe arms the timer once, the stale ones nothing
    p = d["probed"]
    assert p["timer"] == 1 and p["queue"] == 0, p
    a = d["after"]
    assert a["timer"] == 0 and (a["topmost"], a["clip"], a["bd"]) == (0, 0, 0), a   # held off until re-activated


def test_watchdog_probe_loop_only_logs():
    """The probe loop in WatchThread touches nothing but the log: no Release, no clip / window call, no re-state flag."""
    loop = WATCH[WATCH.index("vidsafety::Watch watch;"):]
    loop = loop[:loop.index("if (g_hotVk) UnregisterHotKey")]
    for banned in ("Release(", "ClipCursor", "ShowWindow", "SetWindowPos", "g_resync"):
        assert banned not in loop, banned
    assert "watch.Step(GetTickCount(), answered) == vidsafety::kWatchStall" in loop


def test_scaling_change_on_the_game_monitor(exe):
    """Windows re-scales the G80 (a new identity at 100% under a process started at 150%): a system-DPI-aware game
    sees it as 5760x3240. Found again by its device path -> no longer the backbuffer's size -> the scaled popup."""
    d, _ = script(exe, f"""
        mon DISPLAY1 0 0 3840 2160 primary path=G80
        mon DISPLAY2 -1440 -207 0 2353 path=DELL
        bb 3840 2160
        boot
        mon DISPLAY1 0 0 5760 3240 primary path=G80
        win 0 0 5760 3240
        display dpi
        display displaychange
        dump changed
        wait {SETTLE}
        dump settled
    """)
    released(d["changed"])
    s = d["settled"]
    assert s["fW"] == 1 and s["mode"] == FULL and s["on"] == "DISPLAY1" and s["win"] == (0, 0, 5760, 3240)
    assert s["bd"] == 0 and s["topmost"] == 1 and s["clip"] == 1


def test_scaling_change_without_a_device_path_waits(exe):
    """No path to recognise the re-scaled monitor by (its rect changed): it counts as gone -> nothing held, no move."""
    d, _ = script(exe, f"""
        {G80}
        bb 3840 2160
        boot
        mon DISPLAY1 0 0 5760 3240 primary
        win 0 0 5760 3240
        display dpioverride
        wait {SETTLE}
        dump x
    """)
    released(d["x"])
    assert d["x"]["await"] == 1 and d["x"]["restores"] == 0


def test_restore_waits_for_a_movie(exe):
    d, _ = script(exe, f"""
        mon DISPLAY1 0 0 3840 2160 primary path=G80
        bb 3840 2160
        boot
        movie 1
        mon DISPLAY1 0 0 5760 3240 primary path=G80
        win 0 0 5760 3240
        display displaychange
        wait {SETTLE + 1000}
        dump during
        movie 0
        wait 200
        dump after
    """)
    assert d["during"]["owed"] == 1 and d["during"]["fW"] == 0 and d["during"]["timer"] == 1
    released(d["during"])
    assert d["after"]["owed"] == 0 and d["after"]["fW"] == 1


def test_windowed_is_left_to_windows(exe):
    d, _ = script(exe, f"""
        {G80}
        {DELL}
        bb 1600 1200
        boot
        user windowed
        pump
        display displaychange
        wait {SETTLE}
        dump x
    """)
    x = d["x"]
    assert x["mode"] == WINDOWED and x["topmost"] == 0 and x["clip"] == 0 and x["bd"] == 0 and x["owed"] == 0


def test_constrain_mouse_off_never_clips(exe):
    d, _ = script(exe, f"""
        {G80}
        bb 1600 1200
        clipwanted 0
        boot
        display displaychange
        wait {SETTLE}
        dump x
    """)
    assert d["x"]["clip"] == 0 and d["x"]["topmost"] == 1


# ---- 6. watchdog, GPU life, backdrop owner, hotkey ----------------------------------------------------------------

def watch(exe, rows: list[str]) -> list[str]:
    return run(exe, "watch", "\n".join(rows) + "\n").strip().split("\n")


def test_watchdog_measures_a_stall(exe):
    # t answered -- a 4 s AI turn: one stall line, with its length
    rows = ["1000 1"] + [f"{1000 + 1000 * i} 0" for i in range(1, 5)] + ["6000 1"]
    out = watch(exe, rows)
    assert all(line.startswith("nothing") for line in out[:5]), out
    assert out[5].startswith("stall") and "stall=4500" in out[5], out


def test_watchdog_never_releases_even_on_a_long_stall(exe):
    """An 11.5 s AI turn (the 2026-11-08 save): measured once when it ends, nothing else -- the watchdog has no release
    action any more. (Windows' own hung test is not an input: it says "not responding" at 5 s of a working turn.)"""
    rows = ["1000 1"] + [f"{1000 + 1000 * i} 0" for i in range(1, 12)] + ["13000 1"]
    out = watch(exe, rows)
    assert [line.split()[0] for line in out] == ["nothing"] * 12 + ["stall"], out
    assert "stall=11500" in out[-1]                         # missed since 1500 (the first failed probe's send)


def test_watchdog_short_gaps_are_not_logged(exe):
    out = watch(exe, ["1000 1", "2000 0", "2100 1"])
    assert out[2].startswith("nothing"), "a 600 ms gap is below kWatchStallLogMs"


def test_watchdog_releases_only_on_a_display_event_or_the_hotkey():
    """Release has exactly two callers: the escape hotkey and a counted display event. Windows' hung test is not
    consulted (it called every 5 s AI turn a hang), and a stall only logs."""
    assert "IsHungAppWindow" not in WATCH and "g_isHung" not in WATCH
    calls = re.findall(r"\bRelease\(([^;]*)\);", WATCH)
    assert sorted(c.split(",")[0].strip() for c in calls) == ['"escape hotkey"', "vidsafety::EventName(msg"], calls
    assert "kWatchRelease" not in SAFE and "kWatchHangMs" not in SAFE


def gpu(exe, cmds: str) -> list[str]:
    return run(exe, "gpu", cmds).strip().split("\n")


def test_gpu_waits_two_seconds_after_a_display_event(exe):
    out = gpu(exe, "at 1000\nevent 5000\nat 6999\nat 7000\n")
    assert out[0] == "st=0 losses=0 maystart=1 mayuse=1"
    assert out[1] == "st=0 losses=0 maystart=0 mayuse=0"
    assert out[2] == "st=0 losses=0 maystart=0 mayuse=0"
    assert out[3] == "st=0 losses=0 maystart=1 mayuse=1"


def test_gpu_backoff_2_10_60_and_uncapped(exe):
    out = gpu(exe, "start\ncreated 1 1000\n"
                   "lost 887A0005 2000\nat 3999\nat 4000\n"          # 1st loss: 2 s
                   "start\ncreated 1 4100\nlost 887A0007 5000\nat 14999\nat 15000\n"   # 2nd: 10 s
                   "start\ncreated 1 15100\nlost 887A0006 16000\nat 75999\nat 76000\n"  # 3rd: 60 s
                   "start\ncreated 1 76100\nlost 887A0020 77000\nat 136999\nat 137000\n")  # 4th: 60 s again
    assert out[2] == "retry=1 st=0 losses=1 maystart=0 mayuse=0"
    assert out[3].endswith("maystart=0 mayuse=0") and out[4].endswith("maystart=1 mayuse=1")   # the loss is a display event
    assert out[7].startswith("retry=1 st=0 losses=2")
    assert out[8].endswith("maystart=0 mayuse=1") and out[9].endswith("maystart=1 mayuse=1")
    assert out[12].startswith("retry=1 st=0 losses=3")
    assert out[13].endswith("maystart=0 mayuse=1") and out[14].endswith("maystart=1 mayuse=1")
    assert out[17].startswith("retry=1 st=0 losses=4"), "never off for the session"
    assert out[18].endswith("maystart=0 mayuse=1") and out[19].endswith("maystart=1 mayuse=1")


def test_gpu_a_minute_live_resets_the_backoff(exe):
    out = gpu(exe, "start\ncreated 1 1000\nlost 887A0005 2000\nstart\ncreated 1 5000\npresented 64000\n"
                   "presented 65001\nlost 887A0005 70000\nat 71999\nat 72000\n")
    assert out[5].startswith("st=2 losses=1"), "59 s live: not yet"
    assert out[6].startswith("st=2 losses=0")
    assert out[7].startswith("retry=1 st=0 losses=1")
    assert out[9].endswith("maystart=1 mayuse=1"), "back to the 2 s step"


def test_gpu_creation_failing_after_a_loss_backs_off_but_a_first_failure_is_final(exe):
    out = gpu(exe, "start\ncreated 1 1000\nlost 887A0005 2000\nstart\ncreated 0 4500\nat 14499\nat 14500\n")
    assert out[4].startswith("st=0 losses=2")
    assert out[5].endswith("maystart=0 mayuse=1") and out[6].endswith("maystart=1 mayuse=1")
    out = gpu(exe, "start\ncreated 0 1000\n")
    assert out[1].startswith("st=3")
    out = gpu(exe, "start\ncreated 1 1000\nlost 80004005 2000\n")
    assert out[2].startswith("retry=0 st=3")


def test_gpu_an_older_display_tick_never_shortens_the_quiet(exe):
    out = gpu(exe, "event 1000\nstart\ncreated 1 4000\nlost 887A0005 9000\nevent 1000\nat 10999\nat 11000\n")
    assert out[3].startswith("retry=1 st=0")
    assert out[5].endswith("maystart=0 mayuse=0") and out[6].endswith("maystart=1 mayuse=1")


@pytest.mark.parametrize("claims,owners", [
    (["watchdog", "game"], ["watchdog", "watchdog"]),        # the thread came up in time
    (["game", "watchdog"], ["game", "game"]),                # the game thread gave up first: a late thread never takes over
    (["game", "game"], ["game", "game"]),
])
def test_backdrop_owner_is_decided_once(exe, claims, owners):
    out = run(exe, "owner", "", *claims).strip().split("\n")
    assert [line.split("owner=")[1] for line in out] == owners


@pytest.mark.parametrize("text,mods,vk,name", [
    ("Ctrl+Alt+Shift+End", 7, 0x23, "Ctrl+Alt+Shift+End"),
    ("ctrl + alt + end", 3, 0x23, "Ctrl+Alt+End"),
    ("Win+Shift+F12", 0xC, 0x7B, "Shift+Win+F12"),
    ("Control+Alt+k", 3, ord("K"), "Ctrl+Alt+K"),
    ("Alt+Shift+Pause", 5, 0x13, "Alt+Shift+Pause"),
    ("Ctrl+Alt+9", 3, ord("9"), "Ctrl+Alt+9"),
])
def test_hotkey_parse(exe, text, mods, vk, name):
    assert run(exe, "hotkey", "", text).strip() == f"ok mods={mods} vk={vk} name={name}"


@pytest.mark.parametrize("text", ["", "off", "none", "0", "End", "Ctrl+Alt", "Ctrl+Alt+End+Home", "Ctrl+Bogus", "Ctrl++End",
                                  "Ctrl+F25"])
def test_hotkey_rejects(exe, text):
    assert run(exe, "hotkey", "", text).strip() == "off"


# ---- 7. the source facts the DLL relies on -----------------------------------------------------------------------

def _src(name: str) -> str:
    return (UIMOD / name).read_text(encoding="utf-8").replace("\r\n", "\n")


VID, WATCH, GPU, INIT, SAFE = (_src(n) for n in ("vidmode.cpp", "vidwatch.cpp", "gpuscale.cpp", "init.cpp", "vidsafety.h"))


def _body(text: str, head: str) -> str:
    i = text.index(head)
    return text[i:text.index("\n}\n", i)]


def test_subclass_answers_the_probe_and_samples_m_fwindowed_first():
    sub = _body(VID, "LRESULT CALLBACK SubclassProc(")
    probe = sub.index("msg == WM_NULL && wp == kWatchProbeW && lp == kWatchProbeL")
    assert sub.index("g_safe.Observe(*g_fWindowed != 0, g_ownSetWindowed);") < probe
    assert probe < sub.index("CallWindowProcA("), "the probe never reaches PRACX or the engine"
    assert "vidsafety::IsDisplayEvent(msg, wp)" in sub and "g_safe.OnPlacement(w, fx);" in sub
    assert "NeedsScaledFullscreen(hwnd)" not in sub, "the converge decision is the controller's (PRACX's own path only)"
    assert sub.index("msg == WM_TIMER && wp == kSafetyTimer") < sub.index("CallWindowProcA(")
    assert "InterlockedExchange(&g_resyncOwed, 0)" in sub[probe:probe + 300], "a stale probe only arms the timer once"


def test_every_setwindowed_of_ours_is_flagged():
    assert len(re.findall(r"g_setWindowed\(", VID)) == 1 and "    g_setWindowed(on);" in _body(VID, "void OwnSetWindowed(int on)")


def test_detected_mode_is_not_read_from_topmost():
    det = _body(VID, "int VidModeDetect()")
    assert "WS_EX_TOPMOST" not in det and "g_popupKind" in det


def test_gpu_only_on_counted_events():
    assert "GpuDisplayEvent()" not in _body(VID, "void OnDisplayEvent(HWND hwnd")
    assert "void EventCounted() override { GpuDisplayEvent(); }" in VID
    ctl = _body(WATCH, "LRESULT CALLBACK CtlProc(")
    assert "if (counts) {" in ctl and ctl.index("if (counts) {") < ctl.index("GpuDisplayEvent();")
    assert "VidModeOwnDisplaySwitch()" in ctl and "NeedsMonitorCheck(msg, wp)" in ctl


def test_no_device_creation_on_the_game_thread():
    assert GPU.count("D3D11CreateDeviceAndSwapChain\")") == 1
    assert "MakeDevice(g_made);" in _body(GPU, "DWORD WINAPI MakeDeviceThread(")
    present = _body(GPU, "bool GpuPresent(")
    assert "EnsureDevice(hwnd, cw, ch)" in present and "MakeDevice(" not in present
    assert present.index("g_life.MayUse(GetTickCount())") < present.index("EnsureDevice(") < present.index("ResizeBuffers(")
    assert "if (!g_life.MayUse(GetTickCount())) return false;" in _body(GPU, "bool GpuCurrent(")
    ensure = _body(GPU, "bool EnsureDevice(")
    assert "WaitForSingleObject" not in ensure and "CreateThread(" in ensure


def test_cpu_pool_never_waits_on_a_thread_that_has_not_started():
    """M4: the device worker holds the loader lock while d3d11 / the driver load; a new thread needs it to start. The
    pool is made at the boot apply and a job waits only on workers that have run."""
    poll = _body(VID, "void VidModePoll()")
    assert poll.index("EnsurePool();") < poll.index("VidModeSet(want);")
    job = _body(VID, "void RunJob()")
    assert "EnsurePool()" not in job and "if (g_alive[i]) done[workers++] = g_done[i];" in job
    assert "WaitForMultipleObjects(static_cast<DWORD>(workers), done, TRUE, INFINITE)" in job
    assert "InterlockedExchange(&g_alive[i], 1);" in _body(VID, "DWORD WINAPI WorkerProc(")


def test_backdrop_owner_decided_once_in_the_source():
    """H1: the game thread never makes a backdrop while the watchdog owns it; a late watchdog destroys its own; every
    hide path hides every backdrop."""
    assert "if (VidWatchOwnsBackdrop()) return VidWatchBackdrop();" in _body(VID, "HWND BackdropWnd(bool create)")
    hide = _body(VID, "void HideBackdrop()")
    assert "VidWatchBackdrop(), g_ownBackdrop" in hide
    th = _body(WATCH, "DWORD WINAPI WatchThread(")
    assert th.index("g_backdrop = bd;") < th.index("InterlockedCompareExchange(&g_owner")
    assert "if (!mine && bd) { g_backdrop = nullptr; DestroyWindow(bd); bd = nullptr; }" in th
    start = _body(WATCH, "bool VidWatchStart(")
    assert "InterlockedCompareExchange(&g_owner, vidsafety::kOwnerGame, vidsafety::kOwnerUndecided)" in start
    assert "return g_owner == vidsafety::kOwnerWatchdog ? g_backdrop : nullptr;" in WATCH


def test_watchdog_calls_no_engine_code_and_never_blocks_on_the_game_window():
    sends = re.findall(r"SendMessageTimeoutA\(([^;]*)\)", WATCH)
    assert len(sends) == 1 and "SMTO_ABORTIFHUNG" in sends[0] and "SMTO_BLOCK" not in sends[0]
    assert "SendMessageA(" not in WATCH and "SendMessageW(" not in WATCH and "Rd<" not in WATCH
    rel = _body(WATCH, "void Release(")
    assert "SWP_ASYNCWINDOWPOS" in rel and "ShowWindowAsync(g_game, SW_MINIMIZE)" in rel and "ClipCursor(nullptr)" in rel
    danger = _body(WATCH, "bool Danger()")
    assert "IsWindowVisible(bd) && Topmost(bd)" in danger, "a Borderless (non-topmost) backdrop is no danger"
    assert "queued to the game thread" in WATCH and "Ctrl+Alt+Del" in WATCH, "the hang limit is documented"


def test_window_ghosting_is_off_before_any_window():
    """Windows swaps a window it calls "not responding" (5 s without a message pump -- a late-game AI turn) for a
    frozen ghost copy; the game turns that off, in PreInit (before PRACX makes a window) and again in Init for the
    one-phase chain. Resolved at run time: no new static import."""
    pre = _body(INIT, 'extern "C" void __stdcall PreInit(HMODULE prax)')
    ini = _body(INIT, 'extern "C" void __stdcall Init(HMODULE self)')
    assert pre.index("EnsureNoGhosting();") < pre.index("VidModePreInit(prax);")
    assert "EnsureNoGhosting();" in ini
    fn = _body(INIT, "void EnsureNoGhosting()")
    assert 'GetProcAddress(user32, "DisableProcessWindowsGhosting")' in fn and "static bool done" in fn


def test_legacy_switch_is_marked():
    inst = _body(VID, "void InstallVidMode(bool pracx)")
    assert "HookDisplaySwitch(px, &MarkedDisplaySwitch)" in inst
    assert "g_realCds = reinterpret_cast<FChangeDisplaySettings>(real);" in _body(VID, "bool HookDisplaySwitch(")
    assert "w.ownSwitch = VidModeOwnDisplaySwitch();" in VID


def test_log_lines_carry_time_and_pid_are_whole_and_bounded():
    log = _body(INIT, "void UimodLog(const char* msg)")
    assert "GetLocalTime(&t);" in log and "GetCurrentProcessId()" in log and "%03u" in log
    assert "AcquireSRWLockExclusive" in log and "(4u << 20)" in log and "(1u << 20)" in log
    assert "thread_local char part[1024];" in log, "a line is assembled per thread and written whole"


def test_constants():
    assert "constexpr uint32_t kQuietMs = 3000;" in SAFE and "constexpr uint32_t kGpuQuietMs = 2000;" in SAFE
    assert "constexpr uint32_t kConvergeLatchMs = 500;" in SAFE
    assert "constexpr uint32_t kRecheckMs = 3000;" in SAFE and "constexpr uint32_t kWatchStallLogMs = 1000;" in SAFE
    assert 'constexpr const char* kDefaultHotkey = "Ctrl+Alt+Shift+End";' in SAFE
    assert "return n <= 1 ? 2000u : n == 2 ? 10000u : 60000u;" in SAFE


# ---- 8. the delta re-audit of 9df9088 (2026-10-25): N-A / N-B / N-C and adv_v2's scenarios ----------------------------

GONE = ["display devnodes", "unmon DISPLAY1", "mon DISPLAY2 0 0 1440 2560 primary", "win 0 0 1440 2560", "display displaychange"]
BACK = ["mon DISPLAY2 -1440 -207 0 2353", "mon DISPLAY1 0 0 3840 2160 primary", "display devnodes", "display displaychange"]


def lines(*parts) -> str:
    out = []
    for p in parts:
        out += p if isinstance(p, list) else [p]
    return "\n".join(out)


def test_reaudit_F_prime_renumbered_name_settles_on_the_4k_monitor(exe):
    d, _ = script(exe, lines(G80, DELL, "bb 3840 2160", "boot", "display devnodes", "unmon DISPLAY1", "unmon DISPLAY2",
                             "mon DISPLAY1 -1440 -207 0 2353", "mon DISPLAY3 0 0 3840 2160 primary", "win -1440 -207 0 2353",
                             "display displaychange", "wait 3100", "dump t3100", "wait 2900", "dump t6000"))
    for k in ("t3100", "t6000"):
        held_native(d[k])
        assert d[k]["on"] == "DISPLAY3" and d[k]["restores"] == 1, (k, d[k])


def test_reaudit_H_prime_own_switch_marked(exe):
    d, _ = script(exe, """
        mon DISPLAY1 0 0 1600 1200 primary
        switch 1
        bb 1600 1200
        boot
        ownswitch 1
        fg 0
        mon DISPLAY1 0 0 3840 2160 primary
        display displaychange
        ownswitch 0
        wait 2000
        ownswitch 1
        mon DISPLAY1 0 0 1600 1200 primary
        fg 1
        display displaychange
        ownswitch 0
        dump back_0
        wait 1000
        dump back_1000
    """)
    for k in ("back_0", "back_1000"):
        assert d[k]["clip"] == 1 and d[k]["topmost"] == 1 and d[k]["restores"] == 0, (k, d[k])


def test_reaudit_D_prime_flapping_then_settled(exe):
    parts = [G80, DELL, "bb 3840 2160", "boot"]
    for _ in range(5):
        parts += GONE + ["wait 2000"] + BACK + ["wait 2000"]
    d, _ = script(exe, lines(parts, "wait 4000", "dump settled"))
    s_ = d["settled"]
    held_native(s_)
    assert s_["on"] == "DISPLAY1" and s_["restores"] <= 1 and s_["setWindowed"] == 0


def test_reaudit_N1_provisional_adoption_returns_to_the_4k_monitor(exe):
    """The 4K drops, the user Alt+Tabs away and back within a second (or a focus-stealing "new display" dialog is
    clicked away): the game plays on the Dell provisionally -- and goes back native on the 4K when it returns."""
    d, logs = script(exe, lines(G80, DELL, "bb 3840 2160", "boot", GONE, "wait 1000", "fg 0", "wait 500", "fg 1",
                                "wait 3500", "dump on_dell", BACK, "wait 4000", "dump g80_back"))
    o = d["on_dell"]
    assert o["on"] == "DISPLAY2" and o["fW"] == 1 and o["home"] == "DISPLAY1" and o["adopted"] == "DISPLAY2"
    g = d["g80_back"]
    held_native(g)
    assert g["on"] == "DISPLAY1" and g["home"] == "DISPLAY1" and g["adopted"] == "-" and g["await"] == 0
    assert any("provisional" in line for line in logs)
    assert not any("nothing to change" in line and "DISPLAY2" in line for line in logs[-6:])


def test_reaudit_N1b_coming_back_after_the_monitor_returned(exe):
    d, _ = script(exe, lines(G80, DELL, "bb 3840 2160", "boot", GONE, "wait 1000", "fg 0", "wait 2500", BACK,
                             "wait 500", "fg 1", "wait 4000", "dump end"))
    held_native(d["end"])
    assert d["end"]["on"] == "DISPLAY1" and d["end"]["adopted"] == "-"


def test_reaudit_N2_home_gone_nobody_acts_for_a_minute(exe):
    d, _ = script(exe, lines(G80, DELL, "bb 3840 2160", "boot", GONE, "wait 60000", "dump t60"))
    t = d["t60"]
    released(t)
    assert t["await"] == 1 and t["restores"] == 0 and t["setWindowed"] == 0 and t["home"] == "DISPLAY1" and t["timer"] == 0


def test_reaudit_N3_a_transient_empty_device_path_is_no_change(exe):
    d, logs = script(exe, lines("mon DISPLAY1 0 0 3840 2160 primary path=G80", "mon DISPLAY2 -1440 -207 0 2353 path=DELL",
                                "bb 1600 1200", "boot", "dump before", "mon DISPLAY1 0 0 3840 2160 primary",
                                "win 960 0 2880 1440", "dump after_blip", "mon DISPLAY1 0 0 3840 2160 primary path=G80",
                                "wait 200", "dump t200", "wait 3200", "dump t3400"))
    for k in ("after_blip", "t200", "t3400"):
        v = d[k]
        assert v["quiet"] == 0 and v["topmost"] == 1 and v["clip"] == 1 and v["bd"] == 1 and v["gpuEvents"] == 0, (k, v)
    assert d["t3400"]["restores"] == 0


def test_reaudit_N4_usb_notices_every_second(exe):
    parts = [G80, DELL, "bb 1600 1200", "boot", "dump booted"]
    for _ in range(30):
        parts += ["display devnodes", "wait 1000"]
    d, logs = script(exe, lines(parts, "dump end", "wait 3100", "dump idle"))
    e = d["end"]
    assert e["topmost"] == 1 and e["clip"] == 1 and e["bd"] == 1 and e["quiet"] == 0 and e["restores"] == 0
    assert e["gpuEvents"] == 0
    assert sum("ignored" in line for line in logs) == 1
    assert e["pathReads"] == d["booted"]["pathReads"], "no device-path read for a notice or a re-check tick"
    assert d["idle"]["timer"] == 0, "the re-check ends 3 s after the last notice"


def test_release_comes_before_the_monitor_list_is_read(exe):
    """N-A: WM_DISPLAYCHANGE / the DPI messages / a watchdog-only event release before anything is enumerated; a
    device or work-area notice (which needs the list to decide) reads it first and releases only on a change."""
    script(exe, lines(G80, DELL, "bb 1600 1200", "boot", "display displaychange", "order", "wait 3100",
                      "display dpi", "order", "wait 3100", "watchdog-display", "order", "wait 3100",
                      "display devnodes", "order"))
    assert [o[0] for o in ORDERS] == ["release", "release", "release", "enum"], ORDERS
    assert "release" not in ORDERS[3], "an unchanged notice releases nothing"


def _fx_between(start: str, end: str) -> list[str]:
    return FX[FX.index(f"mark {start}") + 1:FX.index(f"mark {end}")]


# what each running mode holds (in Sync's order: topmost, backdrop, clip) and the setup that gets it there
HELD = {
    "scaled_fullscreen": (["bb 1600 1200", "boot"], ["topmost", "backdrop", "clip"]),
    "native_fullscreen": (["bb 3840 2160", "boot"], ["topmost", "clip"]),
    "borderless": (["bb 1600 1200", "boot", "user borderless"], ["backdrop"]),
}


@pytest.mark.parametrize("event", ["display displaychange", "display dpi", "display dpioverride", "watchdog-display"])
@pytest.mark.parametrize("mode", sorted(HELD))
def test_pre_release_never_re_holds(exe, mode, event):
    """R1 (audit 2026-10-25): a WM_DISPLAYCHANGE with an unchanged monitor set (a refresh-rate change) in scaled
    Fullscreen. The pre-release's leave-topmost SetWindowPos sent a nested WM_WINDOWPOSCHANGED whose placement sync ran
    before the quiet period was set: it re-asserted topmost, the backdrop and the clip, and the controller's own release
    dropped them again (clip 0, topmost 0, topmost 1, clip 1, clip 0, topmost 0: a backdrop flash and three more
    SetWindowPos). Now the quiet starts before the first effect: each held thing is dropped exactly once, nothing is
    re-held until the display settles, and then each is re-held exactly once."""
    setup, held = HELD[mode]
    d, logs = script(exe, lines(G80, DELL, *setup, "dump held", "trace 1", "mark event", event, "mark after", "dump ev",
                                "wait 2900", "mark quiet", "wait 200", "mark settled", "dump settled"))
    for what, key in (("topmost", "topmost"), ("backdrop", "bd"), ("clip", "clip")):
        assert d["held"][key] == (1 if what in held else 0), (what, d["held"])
    assert _fx_between("event", "after") == [f"{h} 0" for h in ("clip", "backdrop", "topmost") if h in held], FX
    released(d["ev"])
    assert d["ev"]["quiet"] == 1 and d["ev"]["timer"] == 1 and d["ev"]["gpuEvents"] == 1
    assert _fx_between("after", "quiet") == [], "nothing re-held inside the quiet period"
    assert _fx_between("quiet", "settled") == [f"{h} 1" for h in held], FX
    assert all(d["settled"][k] == d["held"][k] for k in ("topmost", "bd", "clip", "win", "mode", "fW")), d["settled"]
    # the burst is still logged as one event with its release tail
    first = [line for line in logs if line.startswith("display: ") and "->" in line and "settled" not in line]
    assert first[0].endswith("-> clip released, topmost dropped, backdrop hidden"), logs
    assert any("display: settled (1 event over" in line for line in logs), logs


def test_pre_release_inside_a_burst_and_on_an_ignored_notice(exe):
    """A second always-counting message inside the quiet period changes nothing (all already released) and is not
    logged as a new burst; a device notice with an unchanged set does no pre-release at all."""
    script(exe, lines(G80, DELL, "bb 1600 1200", "boot", "trace 1", "mark a", "display devnodes", "display workarea",
                      "mark b", "display displaychange", "mark c", "wait 1000", "display dpi", "mark d", "wait 3100",
                      "mark e"))
    assert _fx_between("a", "b") == [], "an unchanged device / work-area notice holds on"
    assert _fx_between("b", "c") == ["clip 0", "backdrop 0", "topmost 0"]
    assert _fx_between("c", "d") == []
    assert _fx_between("d", "e") == ["topmost 1", "backdrop 1", "clip 1"]
    d, logs = script(exe, lines(G80, DELL, "bb 1600 1200", "boot", "display displaychange", "wait 1000", "display dpi",
                                "wait 3100"))
    assert sum(line.endswith("-> clip released, topmost dropped, backdrop hidden") for line in logs) == 1, logs
    assert any("display: settled (2 events over 1000 ms" in line for line in logs), logs


def test_device_paths_are_read_only_to_recognise_the_monitor(exe):
    """N-A: paths at the boot (NoteHome + the boot mode's UserPicked), at a due restore and at a user's pick or drag --
    not on releases, placements, activations, idle or re-check ticks."""
    d, _ = script(exe, lines(G80, DELL, "bb 1600 1200", "boot", "dump boot", "fg 0", "fg 1", "win 1120 0 2720 1200",
                             "wait 5000", "dump idle", GONE, "wait 2900", "dump quiet", "wait 200", "dump settled",
                             "user fullscreen", "pump", "dump picked", "drag 0 875 1440 1685", "dump dragged"))
    boot = d["boot"]["pathReads"]
    assert boot == 2
    assert d["idle"]["pathReads"] == boot and d["quiet"]["pathReads"] == boot
    assert d["settled"]["pathReads"] <= boot + 2, "the tick a restore is due on (and the one that finds home gone)"
    assert d["picked"]["pathReads"] == d["settled"]["pathReads"] + 1
    assert d["dragged"]["pathReads"] == d["picked"]["pathReads"] + 1


def test_a_drag_moves_home_a_pick_with_home_gone_does_not(exe):
    """N-B: home changes only by the user's own placement -- a drag, or a mode picked with home present."""
    d, _ = script(exe, lines(G80, DELL, "bb 3840 2160", "boot", GONE, "wait 3100", "user fullscreen", "pump",
                             "dump picked", BACK, "wait 3100", "dump back"))
    assert d["picked"]["home"] == "DISPLAY1" and d["picked"]["adopted"] == "DISPLAY2"
    held_native(d["back"])
    # with device paths (read at the drag and at the restore): the Dell is recognised after its coordinates shift
    d, _ = script(exe, lines("mon DISPLAY1 0 0 3840 2160 primary path=G80", "mon DISPLAY2 -1440 -207 0 2353 path=DELL",
                             "bb 3840 2160", "boot", "display devnodes", "unmon DISPLAY1",
                             "mon DISPLAY2 0 0 1440 2560 primary path=DELL", "win 0 0 1440 2560", "display displaychange",
                             "wait 3100", "user fullscreen", "pump", "drag 0 875 1440 1685", "dump dragged",
                             "mon DISPLAY2 -1440 -207 0 2353 path=DELL", "mon DISPLAY1 0 0 3840 2160 primary path=G80",
                             "win -1440 668 0 1478",                     # Windows keeps the window on the Dell
                             "display devnodes", "display displaychange", "wait 3100", "dump back"))
    assert d["dragged"]["home"] == "DISPLAY2" and d["dragged"]["adopted"] == "-"
    b = d["back"]
    assert b["fW"] == 1 and b["mode"] == FULL and b["on"] == "DISPLAY2", "the user put it on the Dell: it stays"
    assert b["win"] == fit((-1440, -207, 0, 2353), 3840, 2160)


def test_a_mode_picked_with_home_present_moves_home(exe):
    d, _ = script(exe, lines(G80, "mon DISPLAY2 3840 0 5760 1080", "bb 1600 1200", "boot", "user borderless",
                             "win 3840 0 5280 1080", "user fullscreen", "dump picked"))
    assert d["picked"]["home"] == "DISPLAY2" and d["picked"]["adopted"] == "-"


def test_source_release_before_enumeration_and_lazy_paths():
    ev = _body(VID, "void OnDisplayEvent(HWND hwnd")
    assert ev.index("const bool own = VidModeOwnDisplaySwitch();") < ev.index(
        "g_safe.PreRelease(GetTickCount(), own, msg, wp, fx);") < ev.index("MakeWorld(hwnd)")
    assert ev.index("MakeWorld(hwnd)") < ev.index("w.ownSwitch = own;") < ev.index("g_safe.OnDisplayEvent(w, fx, msg, wp, lp);"), \
        "the own-switch test is read once: PreRelease and the controller agree"
    pre = _body(SAFE, "    bool PreRelease(")
    assert "if (ownSwitch || NeedsMonitorCheck(msg, wp)) return false;" in pre
    assert pre.index("quiet_.Set(now);") < pre.index("fx.Clip(false);") < pre.index("fx.Topmost(false);") < pre.index(
        "fx.Timer(true);"), "R1: the quiet period is set before the leave-topmost's nested placement can sync"
    assert "const bool first = !quiet_.on || burstOpen_;" in SAFE
    ctl = _body(WATCH, "LRESULT CALLBACK CtlProc(")
    assert ctl.index("if (Danger()) Release(") < ctl.index("if (always) Resnapshot();")
    assert "always ? !VidModeOwnDisplaySwitch() : Resnapshot()" in ctl
    assert "for (DWORD i = 0; s.paths; ++i)" in WATCH and "VidEnumMonitors(now, nullptr, vidsafety::kMaxMonitors, false)" in WATCH
    assert VID.count("MakeWorld(hwnd, true)") == 3, "NoteHome at boot and at a drag, UserPicked in VidModeSet"
    assert VID.count("MakeWorld(hwnd, g_safe.NeedsPaths(GetTickCount()))") == 1, "the timer: paths only for a due restore"
    assert VID.count("MakeWorld(hwnd") == VID.count("MakeWorld(hwnd)") + 4
    assert "return a.rc == b.rc && a.primary == b.primary && !strcmp(a.name, b.name);" in SAFE, "N-C: no path in the set check"
