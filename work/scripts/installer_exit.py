"""Exit guarantee for the installer: no path may ever end in a closed window and no message.

HARD REQUIREMENT (user, 2026-09-21): every flow -- success, expected failure, preflight abort,
unhandled exception, Ctrl-C -- must (1) tell the user what happened, (2) say whether anything on
disk was changed, and (3) wait for a keypress before the window can close. A player who
double-clicks the installer and sees a window flash and vanish has learned nothing and cannot
report anything.

TWO LAYERS, COORDINATED BY A MARKER FILE
----------------------------------------
Layer 1 (this module) owns every outcome the Python process can reach.

Layer 2 (run-install.bat) must cover what Python cannot reach *at all*: a failure during the
module-scope imports, a hard crash that kills the process before any handler runs, a missing
interpreter, or being run under pythonw.exe. The batch cannot detect those by exit code -- an
uncaught ImportError exits 1, indistinguishable from an ordinary handled failure, and a Windows
fatal status such as 0xC0000005 reaches cmd as a NEGATIVE ERRORLEVEL, so a `GEQ 100` threshold
never fires for the very case it was written for.

So the handshake is explicit instead of inferred: the batch picks a marker path, deletes any stale
copy, and passes it in LONGEVITY_GUARD_MARKER. run_guarded() writes that file in its `finally`. If
the marker is missing when Python exits, the guard provably never ran, and the batch prints a
verdict and pauses. No arithmetic, no guessing.

`changed` is threaded through every failure on purpose. "It failed and nothing was touched" and
"it failed partway through" demand completely different actions from the user, and saying we do
not know is better than guessing wrong.
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Callable, List, Optional

# Exit codes. Kept below 100 purely for readability now that the batch uses the marker file
# rather than a numeric threshold.
EXIT_OK = 0
EXIT_ERROR = 1            # something failed; see `changed` for whether disk was touched
EXIT_NO_GAME = 2          # the game directory could not be found
EXIT_ABORTED = 3          # preflight refused, or the user declined; NOTHING was changed
EXIT_UNSUPPORTED = 4      # the installed base is not a supported configuration
EXIT_INTERRUPTED = 5      # Ctrl-C
EXIT_CRASH = 6            # unexpected exception -- a bug in the installer
MAX_OWN_CODE = 99

# `install.py --check` -- the launch-time query the GAME runs as a subprocess. Its exit code is
# the coarse answer, usable even if the stdout pipe breaks; stdout carries `key=value` lines
# only (see install.check_report). Disjoint from the install codes above on purpose.
CHECK_NOTHING = 0         # verified; nothing to offer
CHECK_UPDATES = 10        # verified; at least one item to offer (see the lines)
CHECK_MANUAL = 11         # verified; this install must be updated by hand (kill switch)
CHECK_FAILED = 12         # could not check: offline, untrusted manifest, no game dir, crash

MARKER_ENV = "LONGEVITY_GUARD_MARKER"

#: Set by a PARENT installer process on a child it spawned. The child then prints its detail
#: output but NO verdict banner and does not wait, so the parent owns the single verdict.
#:
#: Without it the bootstrap's in-place update printed two banners and waited for Enter twice --
#: and on a failure the two contradicted each other ("Nothing on disk was changed" from the
#: child, "it is not certain how far the install got" from the parent). The marker is still
#: written, so the batch's layer-2 handshake is unaffected.
WORKER_ENV = "LONGEVITY_WORKER"


def is_worker() -> bool:
    return bool(os.environ.get(WORKER_ENV))

#: Everything printed, so a GUI-subsystem run (pythonw, where sys.stdout is None) can still show
#: the user the outcome in a message box instead of silently discarding it.
_transcript: List[str] = []


class InstallerError(Exception):
    """An expected, explainable failure.

    Raise this instead of printing and returning a code: the guard then renders it consistently
    and cannot forget to wait for the user.
    """

    def __init__(self, message: str, code: int = EXIT_ERROR,
                 detail: str = None, changed: Optional[bool] = False,
                 remedy: str = None, title: str = None, disk_note: str = None):
        # changed: True = we wrote something, False = provably nothing, None = we do not know.
        # None is a legitimate answer and renders as such; guessing is what costs the user time.
        super().__init__(message)
        self.message = message
        self.code = code
        self.detail = detail
        self.changed = changed          # did we modify anything in the game dir?
        self.remedy = remedy            # one concrete thing the user can do
        #: Optional banner title. The default is chosen from `code`; a caller whose outcome is
        #: neither a refusal nor a failure (e.g. "the core updated, the pack did not") names it.
        self.title = title
        #: Optional replacement for the generic disk statement, for the same reason.
        self.disk_note = disk_note


def say(*parts: object) -> None:
    """print(), but it records everything and can never raise.

    stdout may be None (pythonw) or a broken pipe; neither may be allowed to turn a reportable
    failure into a silent one -- least of all from inside the `finally` that owns the guarantee.
    """
    text = " ".join(str(p) for p in parts)
    _transcript.append(text)
    if sys.stdout is None:
        return
    try:
        print(text)
    except UnicodeEncodeError:
        # The console codepage cannot represent this text -- typically a game path with Cyrillic,
        # CJK or accented characters. DEGRADE, never drop: a swallowed line is a missing part of
        # the verdict, and letting the error escape would send a legitimate install into the
        # crash handler and tell the user their path was an installer bug.
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        try:
            print(text.encode(enc, errors="replace").decode(enc, errors="replace"))
        except Exception:  # noqa: BLE001
            try:
                print(text.encode("ascii", errors="replace").decode("ascii"))
            except Exception:  # noqa: BLE001
                pass
    except (OSError, ValueError):
        pass


def _show_message_box(title: str, body: str) -> bool:
    """Last-resort output when there is no console at all. Returns True if it was shown."""
    try:
        import ctypes
        MB_OK, MB_ICONINFORMATION, MB_SETFOREGROUND = 0x0, 0x40, 0x10000
        ctypes.windll.user32.MessageBoxW(
            None, body[-4000:], title, MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND)
        return True
    except Exception:  # noqa: BLE001 - there is nothing left to fall back to
        return False


def console_available() -> bool:
    """False when stdout cannot carry a message (pythonw.exe, detached process)."""
    return sys.stdout is not None


def interactive() -> bool:
    """True when we can actually block on a keypress.

    A redirected or closed stdin makes input() raise immediately, so waiting is impossible; in
    that case we still print everything, we just cannot hold the window. Never silently skip the
    MESSAGE -- only the wait.
    """
    if os.environ.get("LONGEVITY_NO_WAIT") or is_worker():
        return False
    # Also honour the flag straight off argv. --no-wait is normally consumed by argparse and
    # exported into the environment, but argparse is exactly what fails on a bad flag -- and a
    # scripted run that mistyped one must still not block. Prefix match so --no-wait=1 counts.
    for a in sys.argv[1:]:
        if a == "--no-wait" or a.startswith("--no-wait="):
            return False
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, AttributeError, OSError):
        return False


def wait_for_key(prompt: str = "Press Enter to close this window... ") -> None:
    """Hold the window. Never raises -- it runs inside the guarantee's `finally`."""
    if not interactive():
        _vsay("\n(non-interactive session: not waiting for input)")
        return
    try:
        input("\n" + prompt)
    except (EOFError, KeyboardInterrupt, OSError, ValueError):
        pass


def _normalise_code(raw) -> int:
    """Map whatever main_fn returned onto our reserved 0..MAX_OWN_CODE range.

    A bool is NOT a code: `int(False or EXIT_OK)` is 0, so a main() that returned a success flag
    would report failure as success. Anything out of range, non-integral or unusable becomes
    EXIT_CRASH, and it is normalised here so the number we PRINT is the number we RETURN.
    """
    if isinstance(raw, bool):
        return EXIT_OK if raw else EXIT_ERROR
    if raw is None:
        return EXIT_OK
    # Require an actual integer. int(2.9) is 2, which is EXIT_NO_GAME -- silently turning a
    # nonsense return value into a plausible-looking code is worse than rejecting it.
    if not isinstance(raw, int):
        return EXIT_CRASH
    return raw if 0 <= raw <= MAX_OWN_CODE else EXIT_CRASH


def _vsay(*parts: object) -> None:
    """say(), but silent in a worker child -- verdict prose belongs to the parent alone."""
    if not is_worker():
        say(*parts)


#: Where a player gets a fresh installer. == manifest.DOWNLOAD_URL (this module must stay free
#: of imports beyond the standard library; test_check.py pins the two together).
DOWNLOAD_URL = "https://longevitymods.com/vaccine/download"

_GREEN, _RED, _YELLOW, _RESET = "\x1b[32m", "\x1b[31m", "\x1b[33m", "\x1b[0m"


def warn(text: str) -> None:
    """A warning the player should read: yellow on a colour console, plain otherwise."""
    say((_YELLOW + text + _RESET) if _colour_ok() else text)


def good(text: str) -> None:
    """A happy line: green on a colour console, plain otherwise."""
    say((_GREEN + text + _RESET) if _colour_ok() else text)


def bad(text: str) -> None:
    """A failure line: red on a colour console, plain otherwise."""
    say((_RED + text + _RESET) if _colour_ok() else text)


def status_line(label: str, status: str, width: int = 22) -> None:
    """One summary row: `label` padded, then a coloured Success / Error / Skipped."""
    word = {"ok": "Success", "error": "Error"}.get(status, "Skipped")
    colour = {"ok": _GREEN, "error": _RED}.get(status, "")
    row = f"  {label:<{width}} "
    say(row + ((colour + word + _RESET) if (colour and _colour_ok()) else word))


def can_ask() -> bool:
    """Can a question be put to the player right now? A keyboard on stdin -- regardless of the
    bootstrap's --no-prompt, which exists so a spawned worker never asks about optional extras,
    not because nobody is watching: the update console the player just opened is watched."""
    if os.environ.get("LONGEVITY_NO_WAIT"):
        return False
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, AttributeError, OSError):
        return False
_vt_ready = None


def _colour_ok() -> bool:
    """ANSI colour on a real console (Windows 10+ needs virtual-terminal processing switched
    on once); plain text when captured, piped or on a console that refuses."""
    global _vt_ready
    if _vt_ready is None:
        _vt_ready = False
        try:
            if sys.stdout.isatty():
                import ctypes
                k32 = ctypes.windll.kernel32
                h = k32.GetStdHandle(-11)
                mode = ctypes.c_uint()
                if k32.GetConsoleMode(h, ctypes.byref(mode)):
                    _vt_ready = bool(k32.SetConsoleMode(h, mode.value | 0x0004))
        except Exception:  # noqa: BLE001
            _vt_ready = False
    return _vt_ready


def _rule(title: str, ok: bool = False) -> None:
    """The verdict line: green for success, red for anything else (no banner of '=' signs)."""
    if is_worker():
        return              # the parent prints the one verdict
    if _colour_ok():
        say("\n" + (_GREEN if ok else _RED) + title + _RESET)
    else:
        say("\n" + title)


def _disk_statement(changed: Optional[bool], note: str = None, out=None) -> None:
    """Requirement (2). `None` means we genuinely do not know -- say so rather than guess.

    `out` defaults to _vsay (parent-only). An InstallerError's statement is printed with `say`
    even in a worker: the parent knows only an exit code, and "not certain how far the install
    got" from the parent, over a child whose "nothing was changed" had been muted, told the
    player their game might be damaged after a run that provably touched nothing.
    """
    # One sentence per line, no hard wraps and no indentation: the console wraps to its own
    # width, and a wrap chosen here breaks as soon as the window is narrower than we assumed.
    out = out or _vsay
    if note:
        out("\n" + note)
    elif changed is False:
        out("\nNothing on disk was changed.")
    elif changed is True:
        out("\nWARNING: the install was already partway through; see above for what completed. "
            "Re-running the installer is safe and will finish or repair it.")
    else:
        out("\nRe-running the installer is safe. If this issue persists, please uninstall and "
            f"download the latest installer from {DOWNLOAD_URL}")


def write_guard_marker() -> None:
    """Prove to run-install.bat that this module ran. Never raises."""
    try:
        p = os.environ.get(MARKER_ENV)
        if p:
            Path(p).write_text("ok\n", encoding="ascii")
    except Exception:  # noqa: BLE001
        pass


def write_crash_log(exc: BaseException, log_dir: Path = None) -> Optional[Path]:
    """Persist a traceback so the user has something to send. Never raises."""
    try:
        d = Path(log_dir) if log_dir else Path(__file__).resolve().parent
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        p = d / f"install-crash-{stamp}.log"
        with p.open("w", encoding="utf-8") as f:
            f.write(f"Longevity Vaccine installer crash {stamp}\n")
            f.write(f"python  : {sys.version}\n")
            f.write(f"argv    : {sys.argv!r}\n\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
        return p
    except Exception:  # noqa: BLE001 - a logging failure must never mask the original error
        return None


def offer_relaunch(exe: Path) -> bool:
    """Ask whether to start the game. Declining is not a failure. Never raises."""
    try:
        if not exe or not Path(exe).exists() or not interactive():
            return False
        ans = input(f"\nStart the game ({Path(exe).name}) now? [Y/n] ").strip().lower()
        if ans not in ("", "y", "yes"):
            return False
        subprocess.Popen([str(exe)], cwd=str(Path(exe).parent), close_fds=True)
        say(f"Starting {Path(exe).name}. This window will close.")
        return True
    except (EOFError, KeyboardInterrupt):
        return False
    except Exception as e:  # noqa: BLE001 - a relaunch failure must not undo a successful install
        say(f"  could not launch the game: {e}")
        say(f"  start it yourself from: {exe}")
        return False


def _resolve(v, default: str) -> str:
    """A verdict string that may be a callable resolved after main_fn ran. Never raises."""
    try:
        v = v() if callable(v) else v
    except Exception:  # noqa: BLE001
        v = None
    return v if isinstance(v, str) and v.strip() else default


def run_guarded(main_fn: Callable[[], int], *,
                relaunch_exe=None,
                success_title=None,
                success_body=None,
                success_after: Callable[[], None] = None,
                log_dir: Path = None) -> int:
    """Run `main_fn` so that EVERY outcome prints a verdict, states disk status, and waits.

    `main_fn` returns an exit code, or raises InstallerError for an expected failure. Anything
    else it raises is treated as a bug in the installer and reported as such.

    `relaunch_exe` may be a Path or a zero-argument callable. It is resolved AFTER main_fn
    returns, because the game directory is usually only known once the run is underway.
    """
    code = EXIT_CRASH
    # Set when the player said yes to starting the game: the window then closes on its own
    # instead of asking for a keypress behind the game (user, 2026-09-27).
    launched = False
    try:
        try:
            # Normalise BEFORE anything is printed: the old order reported the raw value ("stopped
            # with code 100") while the finally clamped the actual exit status to 6, so the number
            # the batch told the user to report matched nothing. A bool is rejected outright --
            # `int(False or EXIT_OK)` is 0, so a main() returning a success flag would have
            # rendered failure as "INSTALLATION SUCCESSFUL".
            code = _normalise_code(main_fn())
            if code == EXIT_OK:
                # The verdict is settable because not every successful run is an INSTALL: an
                # uninstall that printed "INSTALLATION SUCCESSFUL" told the user the exact
                # opposite of what had just happened to their game.
                _rule(_resolve(success_title, "INSTALLATION SUCCESSFUL"), ok=True)
                _vsay(_resolve(success_body, "The Longevity Vaccine is installed."))
                if success_after and not is_worker():       # the parent owns the verdict block
                    try:
                        success_after()
                    except Exception as e:  # noqa: BLE001 - the install already succeeded
                        say(f"(could not print the closing note: {e})")
                try:
                    exe = relaunch_exe() if callable(relaunch_exe) else relaunch_exe
                    if exe:
                        launched = offer_relaunch(exe)
                except Exception as e:  # noqa: BLE001
                    # The install already succeeded; a relaunch problem must not contradict that.
                    say(f"\n(could not offer to launch the game: {e})")
            elif code == EXIT_ABORTED:
                # A worker child refused before touching anything; its own message, disk
                # statement and remedy are printed above (with `say`, not muted). Do not
                # contradict them with "not certain how far it got".
                _rule("NOTHING WAS CHANGED")
                _vsay("The update was stopped before anything was changed -- see the reason "
                      "above.")
            else:
                _rule("INSTALLATION DID NOT COMPLETE")
                _vsay(f"The installer stopped with code {code}.")
                _vsay("Scroll up for the step that failed.")
                _disk_statement(None)

        except InstallerError as e:
            code = e.code
            # "CANCELLED" is for something the player did (Ctrl-C, declining a prompt). A
            # refusal the installer made is not a cancellation, and its one certain property
            # is the one worth putting in the title.
            _rule(e.title or ("NOTHING WAS CHANGED" if e.code == EXIT_ABORTED
                              else "INSTALLATION FAILED"))
            # `say`, not `_vsay`: in a worker the parent owns the BANNER, but the reason, the
            # disk statement and the remedy exist only here.
            say(e.message)
            if e.detail:
                say("")
                say(e.detail)
            _disk_statement(e.changed, e.disk_note, out=say)
            if e.remedy:
                say(f"\nWhat to do: {e.remedy}")

        except KeyboardInterrupt:
            code = EXIT_INTERRUPTED
            _rule("INSTALLATION CANCELLED")
            _vsay("You interrupted the installer (Ctrl-C).")
            _disk_statement(None)

        except SystemExit as e:
            # Mapped to EXIT_ERROR rather than argparse's own 2, which would collide with
            # EXIT_NO_GAME and make the code ambiguous for anything scripting the installer.
            code = EXIT_OK if e.code in (0, None) else EXIT_ERROR
            if code != EXIT_OK:
                _rule("INSTALLATION DID NOT START")
                _vsay("The installer did not understand its arguments (see the usage text above).")
                _disk_statement(False)
            else:
                # A clean SystemExit (--help, --version). argparse has usually printed something
                # already, but the guarantee is ours and must not depend on the caller having
                # printed: say plainly that nothing happened.
                _vsay("\nNothing was installed and nothing on disk was changed.")

        except BaseException as e:  # noqa: BLE001 - the whole point is that nothing escapes
            code = EXIT_CRASH
            _rule("INSTALLER ERROR")
            _vsay("The installer hit an unexpected problem.")
            _vsay(f"{type(e).__name__}: {e}")
            _disk_statement(None)
            log = write_crash_log(e, log_dir)
            if log:
                say(f"\nA full report was written to {log}")
                _vsay("  Please include that file if you report this.")

    finally:
        # Nothing below may raise: this block IS the guarantee.
        try:
            code = _normalise_code(code)
        except BaseException:  # noqa: BLE001
            code = EXIT_CRASH
        # Marker FIRST, before the wait. By this point the verdict is fully printed, which is all
        # the marker attests -- and writing it after the wait meant any death DURING the wait
        # (Ctrl-Break, taskkill, a parent killing the child) left no marker, so the batch appended
        # "stopped before it could report anything" to a run that had reported perfectly.
        write_guard_marker()
        try:
            if not launched:
                wait_for_key()
            if not console_available():
                # pythonw.exe / no console: everything above went nowhere. Show it.
                _show_message_box("Longevity Vaccine Installer", "\n".join(_transcript))
        except BaseException:  # noqa: BLE001
            pass

    return code
