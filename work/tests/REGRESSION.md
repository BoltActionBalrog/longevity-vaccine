# SMACX patcher regression tests

Two layers guard the patcher so work on new modals can't silently break a
finished one. Everything lives under `work\tests\`; it reuses the production
`apply_patches.py` / `config.py` / `frida_common.js` in place (no copies).

```
tests\
  conftest.py  test_*.py  pytest.ini                 # Layer 1 (static, automated)
  probe_modal.js                                     # Layer 2 numeric capture (Frida)
  capture wrappers: run-capture[-WxH].bat            # Layer 2 driver (manual nav)
  compare_snapshots.py                               # Layer 2 numeric diff
  golden\        committed baselines  (<slug>@<WxH>.json)
  snapshots\     working capture output (gitignored)
```

`PY = ..\..\tools\python\python.exe`  (the bundled CPython 3.12; Layer 1 needs
`pytest` and `pytest-xdist` pip-installed into it).

---

## Layer 1 — static patch-integrity (no game, runs in <1 s)

Run before any apply, and after any `patches.yaml` edit:

```
work\tests\run-tests.bat              ::  or:  PY -m pytest work\tests -q
```

It checks, against the pristine `.bak` (MD5 2d0b1438) and the live
`patches.yaml`:
- every confirmed site's anchor + original bytes still match pristine;
- every cave is pure padding, contents resolve, fit, and don't overlap (incl.
  the `_SELFMOD` VirtualSize bump and the `pcave2` new-section append);
- the two caves don't overlap; all `{rel32/abs32:NAME}` symbols exist;
- every code thunk fully disassembles and ends in a control transfer;
- applying to a clean copy yields exactly `target.patched_md5` (the byte-exact
  lock — catches any output drift), and every group stays eligible.

**When you intentionally change the patch output**, the MD5 test fails until you
update `target.patched_md5` in `patches.yaml`. That's the deliberate, reviewed
gate — get the new value from the `New MD5:` line of `run-apply-patches.bat
--apply` (or the test's failure message).

**Parallel.** `pytest.ini` runs `-n auto --dist loadgroup` (pytest-xdist; install
it into both `py` and `tools\python`); `xdist_sched.py` decides the rest from the
timing log below. A run over the directory (the whole suite, `-k scaling`, the
release gate) uses 64 workers, fewer when the free commit charge cannot hold
them (~0.75 GB each at peak: another agent's run is already using it) -- less what
runs started just before it have yet to commit (a machine-wide ledger in %TEMP%,
so suites started together no longer each take the whole free charge). A run that names
files or node ids is parallel too when it is heavy enough to pay for its workers
(xdist starts them one at a time, ~0.25 s each): ~sqrt(measured cost / 0.25 s)
workers, serial under 8 s. `-n N` overrides either; `SMACX_XDIST_WORKERS` sets
the count. Each module is cut into contiguous chunks of near-equal measured cost
(never finer than its module-fixture setup allows) and the chunks run
longest-first, so no single slow module or test is left running alone at the
end. The C++ harnesses compile once per run, shared by every worker
(`cpp_harness.build`), and so is the patched exe the emulator suites run:
take conftest's read-only session fixture `baked_exe` (`baked_exe.py`) instead
of applying the patch set in a module fixture, which every chunk of the module
would repay (`test_baked_exe_shared.py` fails a module that does). Without
xdist, the suite runs serially. `pytest.ini` also
turns faulthandler off: its dumps on Unicorn's internal access violations killed
workers. It also sets `--max-worker-restart=0`, so a worker that dies fails the
run straight away instead of hanging it.

Typical wall times on this machine (64 cores): the whole suite (~44,000 tests)
~2 min (was ~5.5 min); `-k scaling` ~1.5 min; one heavy module such as
`test_portrait_rgb_port.py` or `test_scaling_rw_strip_frame.py` ~35 s (was
~5-6 min serial).
A brand-new module has no measurement yet: its first named run is serial, and a
directory run cuts it into 8 units by test count and starts them early; the run
after that is balanced. With nothing measured at all (a fresh clone) the whole
suite takes ~3 min.

**Deterministic under load.** Nothing in a test may depend on how busy the machine
is: emulation is budgeted by an instruction `count`, or by a wall-clock HANG bound
(>= 600 s) with an end-marker check deciding pass/fail (`test_emu_budget_guard.py`);
threads are synchronised on state, never on a sleep; a test writes only into its
own `tmp_path` (or under a lock, for a fixed path such as beside run-install.bat).
Each process uses one BLAS thread (conftest: OpenBLAS committed ~1.5 GB per worker
for 64 unused threads), and a worker whose commit grew 256 MB since its last
collection runs `gc.collect()` after the test (a Uc with a hook is a reference
cycle: emulator modules grew to ~1.9 GB a worker).

Two harness fixes ride along (conftest.py / xdist_sched.py): compiled bytecode is
cached even under `PYTHONDONTWRITEBYTECODE=1` (agent shells set it; without the
cache every worker re-did pytest's assertion rewrite of every module, ~20 s), and
a worker skips interpreter teardown at exit (64 workers tearing down together
overran xdist's 10 s exit timeout on every run). keystone 0.9.2 occasionally
opens an X86 engine that reads every unprefixed number as hex (`mov eax, 10` ->
`b8 10 00 00 00`; ~1 in 255 engines inside an xdist worker); conftest checks each
new engine once and reopens a bad one.

**Timing.** Every pytest run here (by hand, pre-commit, release gate) logs each
test's setup/call/teardown and each module's import time to `timings\`
(gitignored; `timing_plugin.py`, ~zero overhead, `SMACX_TIMINGS=0` disables), and
folds each test's newest cost into `.git\smacx-test-costs.json`, which the
parallel plan above reads. That table sits in the repository's shared `.git`
directory so the main checkout and every worktree plan from the same
measurements (`SMACX_COSTS_FILE` overrides; a skipped run never overwrites a
real cost).
`PY timing_report.py` shows the slowest modules/tests of the newest full run;
`--last`, `--history` for the rest.

---

## Layer 2 — runtime numeric snapshots (semi-automated; you navigate)

Captures, per modal, the regression-relevant popup-layout struct fields
(box/window/content sizes, margins, band, header/footer reserve, dialog row
count, screen rect, scale_num) as JSON — read straight from the game's own popup
struct, so no window chrome / cursor / DDraw noise. (Pixel/PNG capture AND
per-button capture were both removed — no single buffer holds the composited
modal, and button capture was dominated by startup encyclopedia buttons + a
non-deterministic parent pointer. See memory `project-smac-l2-pixel-capture`.)

### Capture a baseline (do this once per resolution, on a known-good build)

```
work\tests\run-capture-3840x2160.bat      :: also -1920x1080 / -1600x1200
```

Each wrapper self-elevates (Frida needs SeDebugPrivilege) and sets the
resolution (restoring it on exit). At the Frida prompt type `%resume`, then
**navigate to each modal you want covered** (Customize Game Rules, Quit, Faction
Select, …). Each modal auto-writes `snapshots\<slug>@<WxH>.json` the first time
it's drawn. Type `quit` when done.

Promote the captures to goldens:

```
PY work\tests\compare_snapshots.py --update     :: copies snapshots\ -> golden\
```

Commit the `golden\*.json`.

### Check for regressions (after changing a modal)

Re-apply the patch, re-capture the **same** resolutions navigating the **same**
modals, then:

```
PY work\tests\compare_snapshots.py
```

Same-resolution ⇒ identical runtime scale ⇒ values should reproduce; tolerance
is ±2 px (exact for scale_num / branch / title / row count).
Exit code is non-zero on any diff (CI-friendly).

A modal you *meant* to change will fail; confirm the named field diffs are the
intended change, then `--update` to re-baseline just that capture set.

### Notes / limitations
- Manual navigation is by design (driving an old Win32 game hands-off is
  brittle). The probe captures automatically once you reach a modal.
- External-window popups (`[+0xa14]!=0`) and per-row checkbox sprite scale
  aren't captured — see `ACTION_ITEMS.md`.

---

## Layer 3 — interactive visual verification (human-driven; THE correctness gate)

Layers 1–2 are necessary but **not sufficient**: they prove byte-integrity and
that struct fields hold their expected numbers. They do **not** prove the UI
*looks* right. Per the invariants (CLAUDE.md), the only
thing that closes a change is a human seeing it render correctly at **4K + at
least one non-4K res** (1920×1080 and/or 1600×1200). Nothing below replaces that.

### The trap this rung exists to prevent

Launching the game from a tool/shell is **non-interactive**: the intro cinematic
plays on its own, the main menu renders, and then the game **sits idle waiting
for input that never comes**. That idle is a *working* game with no operator at
the keyboard — **not** a hang. Two failure modes follow, both real here:

- **False "broken":** observing "intro, then nothing" from an unattended launch
  and concluding the patch hung the game. It didn't — there was just no one to
  click. (This note was written after exactly that mistake.)
- **False "verified":** seeing a side effect of load (e.g. `uimod.log` was
  written, a Frida hook fired, the process is still alive) and reporting the
  feature as "in-game verified." **DLL/hook loaded ≠ game playable ≠ UI correct.**
  Only Layer 3 may be described as "in-game verified."

### What the agent CAN do unattended (liveness — label it as liveness, not "verified")

These are cheap, worth doing, and the most an automated launch can honestly claim:
- launch via `work\run-game.bat` and confirm the process **stays alive** for
  several seconds (an immediate exit/crash = a real regression worth chasing);
- confirm the expected **load side effects** (e.g. `uimod.log` shows `Init` +
  the PRACX-mode line; the MD5 of the live exe matches `target.patched_md5`);
- Layer 1 (`run-tests.bat`) and, where a modal is reachable, Layer 2 numerics.

Report these as exactly what they are ("launched, no crash in ~5 s, DLL loaded
per log") and **stop short of** "looks right / works."

### What only a human can do (the actual gate — hand this off explicitly)

The agent cannot see the screen or drive the Win32 UI, so the visual gate is a
**structured hand-off to the owner**, not something to claim on their behalf. Ask
for it with a concrete checklist:

1. **Launch at each required resolution** — use the res shortcuts, which set the
   mode and restore it on exit:
   `work\run-3840x2160.bat`, `work\run-1920x1080.bat`, `work\run-1600x1200.bat`
   (plain default-res launch: `work\run-game.bat`). 4K **and** ≥1 non-4K, always.
2. **Navigate to the specific element** under test (name the modal/screen — e.g.
   "Faction Select → open a row dropdown", "Customize Game Rules", "Planetfall
   popup"). Give the exact path; don't assume the owner knows which screen.
3. **State what to look at and the pass criterion**, in `vanilla × (g/16)` terms
   where it applies (see the proportionate-scaling invariant): what element,
   what it should measure/align to, what a *fail* looks like (banding, dropped
   stroke, off-center text, distortion, clipping).
4. **Capture evidence** — a screenshot at each res beats prose ("looks fine").
   For pixel-measuring against vanilla, a same-res pristine `.bak` shot
   (`work\run-pristine-1600x1200.bat`) gives the baseline to compare.
5. Only after the owner confirms all required resolutions may the change be
   called done / MD5-locked / added to `CHANGELOG.md`.

### One-line rule

Automated launch = **liveness only**. "In-game verified" requires a human who
**navigated to the element and looked at it** at 4K + a non-4K res. Anything
short of that is reported as the narrower thing it actually was.
