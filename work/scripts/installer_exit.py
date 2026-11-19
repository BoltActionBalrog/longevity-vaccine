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
EXIT_DECLINED = 7         # the player declined a consent question (chose to keep or cancel); NOTHING was changed
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
                 remedy: str = None, title: str = None, disk_note=None,
                 red: bool = False, any_key: bool = False,
                 offer_play: bool = False, offer_play_default: bool = True):
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
        #: Optional replacement for the generic disk statement, for the same reason; False = the
        #: message already states it, print nothing more.
        self.disk_note = disk_note
        #: The message in red (a refusal the player must read before anything else), and the
        #: window held on ANY key rather than Enter (user 2026-11-05, the foreign-backup refusal).
        self.red = red
        self.any_key = any_key
        #: Offer to start the game after this outcome (the Thinker repair window's no-change outcomes,
        #: thinker-updater-design.md section 4.0), and whether Enter means yes ([Y/n]) or no ([y/N]).
        self.offer_play = offer_play
        self.offer_play_default = offer_play_default


def stopped_error(disk_note=None) -> InstallerError:
    """Ctrl-C (or EOF) at a question asked before anything is written: the optional modules, the Thinker
    questions, automatic updates -- one outcome for every such question of a run, the folder list's too
    (EXIT_ABORTED, NOTHING WAS CHANGED; code review 2026-11-15: a setup run had two codes and two titles).
    Nothing was changed, and that is certain here; Ctrl-C once writing has started stays run_guarded's
    INSTALLATION CANCELLED."""
    # The message already says nothing was changed: no second "Nothing on disk was changed." under it (execution
    # audit 2026-11-15), unless the caller has a note of its own.
    return InstallerError("You stopped the installer, so nothing was changed.", code=EXIT_ABORTED, changed=False,
                          title="NOTHING WAS CHANGED", disk_note=disk_note if disk_note else False)


def say(*parts: object) -> None:
    """print(), but it records everything and can never raise.

    stdout may be None (pythonw) or a broken pipe; neither may be allowed to turn a reportable
    failure into a silent one -- least of all from inside the `finally` that owns the guarantee.
    """
    global _last_blank
    text = " ".join(str(p) for p in parts)
    _transcript.append(text)
    _last_blank = text.endswith("\n") or text == ""
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


#: Did the last line this process printed end in an empty one? blank() reads it so a prompt gets
#: exactly ONE empty line above it, never two. Unknown at start (a parent's output) = not blank.
_last_blank = False


def blank() -> None:
    """Exactly one empty line here: printed unless the last line already was one."""
    if not _last_blank:
        say("")


#: The rules a question sits between (user 2026-11-03: a question must not read as output). Plain
#: '-': every console codepage has it, and Windows 7 shows no colour to tell the two apart.
RULE = "-" * 60


def question_head(title: str, notes=(), title_kind: str = None) -> None:
    """The top of a question block, one empty line below the output above it (user rule
    2026-11-01): a rule, the title in capitals (in `title_kind`'s colour, if given), the notes, a
    rule. An arrow-key list's keys go with its rows (ask_block), not here (user 2026-11-15)."""
    blank()
    say(RULE)
    say(" " + (painted(title.upper(), title_kind) if title_kind else title.upper()))
    for n in notes:
        say(" " + n)
    say(RULE)


def _keys_blue(prompt: str) -> str:
    """A yes/no prompt's own control hint, "[Y/n]" / "[y/N]", in blue like every key hint."""
    for hint in ("[Y/n]", "[y/N]"):
        prompt = prompt.replace(hint, painted(hint, "keys"))
    return prompt


def stdin_is_console() -> bool:
    """Is stdin a real console input? isatty() alone is not that on Windows: stdin redirected from NUL reports
    isatty() True (it is a character device), and a question asked there polled a console that does not exist,
    forever (verification of 9f2cb08, 2026-11-15: `install.py < NUL` and a bootstrap worker that inherited NUL hung).
    So the handle must also be a console (GetConsoleMode succeeds). A stdin with no file handle (a test's
    stand-in) is judged by isatty() alone."""
    try:
        if sys.stdin is None or not sys.stdin.isatty():
            return False
    except (ValueError, AttributeError, OSError):
        return False
    if os.name != "nt":
        return True
    try:
        fd = sys.stdin.fileno()
    except (AttributeError, ValueError, OSError):
        return True
    try:
        import ctypes
        import msvcrt
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        k.GetConsoleMode.restype = ctypes.c_int
        mode = ctypes.c_ulong()
        return bool(k.GetConsoleMode(ctypes.c_void_p(msvcrt.get_osfhandle(fd)), ctypes.byref(mode)))
    except Exception:  # noqa: BLE001 - no answer is no console
        return False


def flush_input() -> None:
    """Discard keys typed before a question was shown (an Enter pressed while the window waited for
    the game to close must not answer a default-yes question unread; thinker-updater-design.md
    section 3E). Console only; never raises."""
    try:
        if not stdin_is_console():
            return
        if os.name == "nt":
            import msvcrt
            while msvcrt.kbhit():
                msvcrt.getwch()
        else:
            import termios
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:  # noqa: BLE001
        pass


def ask(prompt: str, title: str = None, notes=(), flush: bool = False, title_kind: str = None) -> str:
    """input() for every question the installer puts. With `title` (every real question) it is a
    ruled block: question_head (with `notes`, the explanation above the closing rule), the prompt
    (its [Y/n] in blue), a rule under the answer. Without, just the one empty line above. Raises
    what input() raises (EOFError, KeyboardInterrupt)."""
    global _last_blank
    if title:
        question_head(title, notes, title_kind=title_kind)
    else:
        blank()
    if flush:
        flush_input()
    try:
        return input((" " + _keys_blue(prompt)) if title else prompt)
    finally:
        _last_blank = False         # the player's answer ended the prompt's line
        if title:
            say(RULE)


def ask_line(prompt: str, flush: bool = False) -> str:
    """A one-line question with no ruled block, for a question whose answer the lines above already
    explain (user 2026-11-15: the Thinker changelog offer): one empty line above, the prompt indented
    like a ruled question's, its [Y/n] in blue. Raises what input() raises (EOFError, KeyboardInterrupt)."""
    global _last_blank
    blank()
    if flush:
        flush_input()
    try:
        return input(" " + _keys_blue(prompt))
    finally:
        _last_blank = False         # the player's answer ended the prompt's line


#: An arrow-key list's row marker (user 2026-11-15: "->" left of the selected row, nothing after its text); the
#: other rows keep the same indent, so every row's text starts in the same column.
MARK_ON, MARK_OFF = " -> ", "    "


def _plain(text: str) -> str:
    """`text` without its colour codes."""
    global _ANSI_RX
    import re
    if _ANSI_RX is None:
        _ANSI_RX = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
    return _ANSI_RX.sub("", text)


def marked(text: str, on: bool, whole_row: bool = True) -> str:
    """One row of an arrow-key list: ` -> text` under the marker, `    text` otherwise. The selected row, its arrow
    included, is green as a whole (user 2026-11-15): its own colours (a blue "Thinker Mod", a red version) are
    dropped while it is selected and come back when the marker moves off. Plain on a console without colour.
    `whole_row=False` keeps the row's own colours under a plain marker: the one list that asks for it is the
    optional modules' pack rows, where green means ticked, so a green unticked row would read as ticked (user
    2026-11-15)."""
    if not on:
        return MARK_OFF + text
    if not whole_row:
        return MARK_ON + text
    return painted(MARK_ON + _plain(text), "good")


def ask_block(title: str, notes, rows, keys: str = None, title_kind: str = None) -> None:
    """A question that is a list the arrow keys move through: question_head, then the keys to press
    (blue) on their own line directly above the first row (user 2026-11-15: "Move the movement controls
    down to the actual selections"), then `rows` (the caller ends them with RULE, so a redraw rewrites
    the closing rule with them). redraw() rewrites `rows` only: the keys line stays where it is. No `title`: no
    ruled head at all, just the one empty line above (user 2026-11-15: the Thinker changelog offer), then the `notes`
    as they are, directly above the keys line (user 2026-11-16: the thinker.ini choice's note line)."""
    global _last_blank
    if title:
        question_head(title, notes, title_kind=title_kind)
    else:
        blank()
        for note in notes:
            say(note)
    if keys:
        say(" " + painted(keys, "keys"))
    for row in rows:
        say(row)
    _last_blank = False


_ANSI_RX = None


def _screen_lines(rows: list) -> int:
    """How many console lines `rows` took when printed: a row longer than the window wraps (a
    long game path does), and the cursor has to go back over every line, not every row."""
    global _ANSI_RX
    import re
    import shutil
    if _ANSI_RX is None:
        _ANSI_RX = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
    cols = max(1, shutil.get_terminal_size((80, 24)).columns)
    return sum(max(1, -(-len(_ANSI_RX.sub("", r)) // cols)) for r in rows)


def redraw(old_rows: list, new_rows: list) -> list:
    """Replace the block of `old_rows` just printed with `new_rows` in place (cursor back over
    every line the old rows took, then erase to the end of the screen, so a shorter or wrapped
    row leaves nothing behind); on a console that cannot move the cursor, print the block again
    below. Returns `new_rows`."""
    out = sys.stdout
    if out is None:
        return new_rows
    try:
        if can_redraw():
            out.write(f"\x1b[{_screen_lines(old_rows)}F\x1b[J" + "".join(r + "\n" for r in new_rows))
            out.flush()
        else:
            out.write("\n" + "".join(r + "\n" for r in new_rows))
            out.flush()
    except (OSError, ValueError, UnicodeEncodeError):
        pass
    return new_rows


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
    return stdin_is_console()


def wait_for_key(prompt: str = "Press Enter to close this window... ", any_key: bool = False) -> None:
    """Hold the window. Never raises -- it runs inside the guarantee's `finally`. `any_key`: one
    keypress of any kind ends the wait (the console's own reader; Enter where there is none)."""
    if not interactive():
        _vsay("\n(non-interactive session: not waiting for input)")
        return
    try:
        if any_key:
            blank()
            say(prompt)
            try:
                import msvcrt
                msvcrt.getwch()
                return
            except (ImportError, OSError):
                pass                    # no console reader: fall back to a line
            input()
        else:
            ask(prompt)
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
_BLUE = "\x1b[94m"      # BRIGHT blue: the keys to press (user 2026-11-04); dark blue is unreadable on black


def warn(text: str) -> None:
    """A warning the player should read: yellow on a colour console, plain otherwise."""
    say((_YELLOW + text + _RESET) if _colour_ok() else text)


def painted(text: str, kind: str) -> str:
    """`text` in green ("good"), red ("bad"), blue ("keys", a control hint) or yellow ("warn") on a colour
    console, unchanged otherwise -- so a caller's own marks ([X] / [ ]) must carry the meaning without it."""
    colour = {"good": _GREEN, "bad": _RED, "keys": _BLUE, "warn": _YELLOW}.get(kind)
    return (colour + text + _RESET) if (colour and _colour_ok()) else text


def can_redraw() -> bool:
    """Can a printed block be rewritten in place (ANSI cursor movement)? The same virtual-terminal
    switch colour needs; False on a console without it (Windows 7)."""
    return _colour_ok()


def good(text: str) -> None:
    """A happy line: green on a colour console, plain otherwise."""
    say((_GREEN + text + _RESET) if _colour_ok() else text)


def bad(text: str) -> None:
    """A failure line: red on a colour console, plain otherwise."""
    say((_RED + text + _RESET) if _colour_ok() else text)


def status_line(label: str, status: str, width: int = 30) -> None:     # 30: the longest pack name fits
    """One summary row: `label` padded, then a coloured Success / Error / Skipped."""
    # "Already installed" / "Updated" / "Repaired": a setup re-run's optional pack (user-approved 2026-11-17).
    word = {"ok": "Success", "error": "Error", "kept": "Already installed", "updated": "Updated",
            "repaired": "Repaired"}.get(status, "Skipped")
    colour = {"ok": _GREEN, "error": _RED, "kept": _GREEN, "updated": _GREEN, "repaired": _GREEN}.get(status, "")
    row = f"  {label:<{width}} "
    say(row + ((colour + word + _RESET) if (colour and _colour_ok()) else word))


#: The PLAYER passed --no-prompt ("Never ask anything"): set by install.main for its own run; a worker learns it from
#: the bootstrap's LONGEVITY_PLAYER_NO_PROMPT marker.
_PLAYER_NO_PROMPT = False


def set_player_no_prompt(on: bool) -> None:
    global _PLAYER_NO_PROMPT
    _PLAYER_NO_PROMPT = bool(on)


def player_no_prompt() -> bool:
    return _PLAYER_NO_PROMPT or bool(os.environ.get("LONGEVITY_PLAYER_NO_PROMPT"))


def can_ask() -> bool:
    """May a question be put to the player right now? A console (has_console), and no --no-prompt from the PLAYER
    (execution audit 2026-11-15: the changelog question and the relaunch still asked under it) -- regardless of the
    bootstrap's own --no-prompt, which exists so a spawned worker never asks about optional extras,
    not because nobody is watching: the update console the player just opened is watched."""
    return has_console() and not player_no_prompt()


def has_console() -> bool:
    """Is someone at a console (a keyboard on stdin, no --no-wait)? Whether or not they said not to be asked: a
    --no-prompt run in a console still fetches the update information a console run would (the optional modules on
    offer, the Thinker builds it must refuse; verification of 7b53fbb, 2026-11-15)."""
    if os.environ.get("LONGEVITY_NO_WAIT"):
        return False
    # --no-wait straight off argv, as interactive() reads it: the bootstrap asks (the folder
    # picker) before anything exports LONGEVITY_NO_WAIT, so a scripted `--update --no-wait` run
    # from a console stopped at the question.
    for a in sys.argv[1:]:
        if a == "--no-wait" or a.startswith("--no-wait="):
            return False
    return stdin_is_console()
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


def redact_profile(text, profile: Optional[str] = None):
    """`text` with the player's profile folder (C:\\Users\\<account>) replaced by %USERPROFILE%.

    Players attach LongevityMods\\logs to public bug reports, and a game folder, a staging cache or a
    traceback under their profile would name their Windows account. The same rule as the game's
    uimod.log (src/uimod/src/logredact.h): case-insensitive, either separator, and only a whole folder
    (C:\\Users\\Ann is not redacted inside C:\\Users\\Anna). `profile` None = %USERPROFILE%. Anything
    that is not a str is returned as is. A UNC profile (\\\\server\\share\\...) is matched from its first
    folder name on. Never raises: text that cannot be redacted (out of memory) is withheld, never written
    as is -- the DLL's UimodLog drops such a line the same way."""
    if not isinstance(text, str):
        return text
    try:
        p = (os.environ.get("USERPROFILE", "") if profile is None else profile).rstrip("\\/")
        if len(p) < 4:                     # empty, or a bare drive: nothing account-specific to hide
            return text
        import re
        # A separator is any run of "/" and "\" -- a repr() doubles them (argv lines, OSError messages), a repr of
        # a repr doubles them again.
        sep = r"[\\/]+"
        pat = sep.join(re.escape(part) for part in re.split(r"[\\/]+", p) if part) + r"(?![\w.\-])"
        return re.sub(pat, lambda _m: "%USERPROFILE%", text, flags=re.IGNORECASE)
    except Exception:  # noqa: BLE001 - a log line must never fail its writer
        return "[line withheld: could not redact]\n"


class RedactingWriter:
    """A text stream that passes everything written through redact_profile; every other attribute is the
    wrapped stream's (flush, close, encoding, fileno...)."""

    def __init__(self, stream, profile: Optional[str] = None):
        self._stream = stream
        self._profile = profile

    def write(self, s):
        return self._stream.write(redact_profile(s, self._profile))

    def writelines(self, lines):
        for s in lines:
            self.write(s)

    def __getattr__(self, name):
        return getattr(self._stream, name)


def write_crash_log(exc: BaseException, log_dir=None) -> Optional[Path]:
    """Persist a traceback so the user has something to send. Never raises.

    `log_dir`: a Path, or a zero-argument callable resolved NOW (the game folder is known only once the run
    is underway), or None / a callable returning None = beside this script. A callable that raises counts
    as None: the crash being reported must never be lost to the choice of folder (audit 2026-11-07: the
    default folder is the extracted download or an updater generation the next update deletes).
    """
    try:
        if callable(log_dir):
            try:
                log_dir = log_dir()
            except Exception:  # noqa: BLE001 - see the docstring
                log_dir = None
        d = Path(log_dir) if log_dir else Path(__file__).resolve().parent
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        p = d / f"install-crash-{stamp}.log"
        with p.open("w", encoding="utf-8") as raw:
            f = RedactingWriter(raw)        # argv and the traceback carry folder paths
            f.write(f"Longevity Vaccine installer crash {stamp}\n")
            f.write(f"python  : {sys.version}\n")
            f.write(f"argv    : {sys.argv!r}\n\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
        return p
    except Exception:  # noqa: BLE001 - a logging failure must never mask the original error
        return None


#: Run-scoped variables that must never reach a process that outlives this run (the relaunched game,
#: and through it a later updater it spawns).
_RUN_SCOPED_ENV = ("LONGEVITY_NO_WAIT", "LONGEVITY_WORKER", "LONGEVITY_PAYLOAD_ROOT", "LONGEVITY_GUARD_MARKER",
                   "LONGEVITY_INSTALL_LOCK", "LONGEVITY_PLAYER_NO_PROMPT", "LONGEVITY_THINKER_CONSENT")


def outliving_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in _RUN_SCOPED_ENV}


def arrow_choice(title, notes, options: list, at: int = 0) -> int:
    """An arrow-key choice (install._arrow_menu: the ruled block, the keys line above the rows, the marker on row
    `at`): the index of the row Enter took. Raises EOFError / KeyboardInterrupt as the menu does. The menu and
    the console key reading live in install.py; imported HERE, lazily, so this module stays standard-library
    only at import time (it owns the exit guarantee). In a run, install is already loaded (it registers itself
    when run as a script), so this is that same module."""
    import install as _install
    return _install._arrow_menu(title, [[o] for o in options], at=at, notes=list(notes))


#: "Start the game" (user-approved 2026-11-15): an arrow choice in this order, always.
START_TITLE = "Start the game"
CLOSE_ROW = "Close this window"


def offer_relaunch(exe: Path, default: bool = True) -> bool:
    """Ask whether to start the game: "Start the game (<exe>)" / "Close this window" (user-approved 2026-11-15),
    the marker on "Start" after a run that changed something (`default`) and on "Close" after one that changed
    nothing (only an explicit choice starts the game). True when the window is to close at once -- the game was
    started, or the player chose "Close this window" (no separate "Press Enter" after it: the verdict is printed
    above). False (the usual keypress wait follows) when there is no one to ask, on Ctrl-C / EOF, or when the
    game could not be started. Never raises."""
    try:
        if not exe or not Path(exe).exists() or not interactive() or player_no_prompt():
            return False
        try:
            pick = arrow_choice(START_TITLE, [], [f"Start the game ({Path(exe).name})", CLOSE_ROW],
                                at=0 if default else 1)
        except ImportError:
            return False                        # the installer's own package is broken: just wait as before
        if pick != 0:
            return True
        subprocess.Popen([str(exe)], cwd=str(Path(exe).parent), close_fds=True, env=outliving_env())
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


def _installed_line() -> str:
    """The fallback success body: "Longevity Vaccine 1.0.0 is installed." (user 2026-11-14: no "The", the version)."""
    try:
        import version as _v
        return f"Longevity Vaccine {_v.VERSION} is installed."
    except Exception:  # noqa: BLE001 - a verdict must print whatever is missing
        return "Longevity Vaccine is installed."


def _offer_after_nothing_changed(relaunch_exe) -> bool:
    """`Start the game ... [y/N]` after an outcome that changed nothing, when the caller named a program
    (user 2026-11-14). Never raises."""
    try:
        exe = relaunch_exe() if callable(relaunch_exe) else relaunch_exe
        return bool(exe) and offer_relaunch(exe, default=False)
    except Exception:  # noqa: BLE001
        return False


def run_guarded(main_fn: Callable[[], int], *,
                relaunch_exe=None,
                relaunch_default=None,
                success_title=None,
                success_body=None,
                success_after: Callable[[], None] = None,
                log_dir=None,
                handover=None,
                cancelled=None) -> int:
    """Run `main_fn` so that EVERY outcome prints a verdict, states disk status, and waits.

    `main_fn` returns an exit code, or raises InstallerError for an expected failure. Anything
    else it raises is treated as a bug in the installer and reported as such.

    `relaunch_exe` may be a Path or a zero-argument callable. It is resolved AFTER main_fn
    returns, because the game directory is usually only known once the run is underway.

    `cancelled`: a zero-argument callable giving (title, body, closing line) for a Ctrl-C, or None for the
    installer's own "INSTALLATION CANCELLED" (install.py's --uninstall: "UNINSTALL CANCELLED").
    """
    code = EXIT_CRASH
    # Set when the player said yes to starting the game: the window then closes on its own
    # instead of asking for a keypress behind the game (user, 2026-09-27).
    launched = False
    wait_any = False            # an InstallerError that holds the window on ANY key
    try:
        try:
            # Normalise BEFORE anything is printed: the old order reported the raw value ("stopped
            # with code 100") while the finally clamped the actual exit status to 6, so the number
            # the batch told the user to report matched nothing. A bool is rejected outright --
            # `int(False or EXIT_OK)` is 0, so a main() returning a success flag would have
            # rendered failure as "INSTALLATION SUCCESSFUL".
            code = _normalise_code(main_fn())
            h = None
            try:
                h = handover() if callable(handover) else None
            except Exception:  # noqa: BLE001
                h = None
            if code == EXIT_OK and h is not None:
                # The Thinker repair's hand-over (thinker-updater-design.md section 3R step 3): main_fn
                # has returned, so the installer lock is released; only now start the update console.
                start, fail = h
                if start():
                    _rule(_resolve(success_title, "UPDATE HANDED OVER"), ok=True)
                    _vsay(_resolve(success_body, "The update continues in a new window."))
                    import time as _time
                    _time.sleep(3)
                    launched = True                     # closes without a keypress
                else:
                    fail()
                    code = EXIT_ABORTED
                    _rule("NOTHING WAS CHANGED")
                    say("The update could not be started in a new window, so nothing was changed.")
                    try:
                        exe = relaunch_exe() if callable(relaunch_exe) else relaunch_exe
                        if exe:
                            launched = offer_relaunch(exe, default=False)
                    except Exception:  # noqa: BLE001
                        pass
            elif code == EXIT_OK:
                # The verdict is settable because not every successful run is an INSTALL: an
                # uninstall that printed "INSTALLATION SUCCESSFUL" told the user the exact
                # opposite of what had just happened to their game.
                _rule(_resolve(success_title, "INSTALLATION SUCCESSFUL"), ok=True)
                _vsay(_resolve(success_body, _installed_line()))
                if success_after and not is_worker():       # the parent owns the verdict block
                    try:
                        success_after()
                    except Exception as e:  # noqa: BLE001 - the install already succeeded
                        say(f"(could not print the closing note: {e})")
                try:
                    exe = relaunch_exe() if callable(relaunch_exe) else relaunch_exe
                    if exe:
                        # [Y/n] after a change; a caller whose success changed nothing (ALREADY UP TO
                        # DATE) says so through `relaunch_default` and gets [y/N].
                        try:
                            yes = relaunch_default() if callable(relaunch_default) else relaunch_default
                        except Exception:  # noqa: BLE001
                            yes = None
                        launched = offer_relaunch(exe) if yes is not False else offer_relaunch(exe, default=False)
                except Exception as e:  # noqa: BLE001
                    # The install already succeeded; a relaunch problem must not contradict that.
                    say(f"\n(could not offer to launch the game: {e})")
            elif code == EXIT_DECLINED:
                # A worker the player cancelled in: its own reason is printed above.
                _rule("UPDATE CANCELLED")
                _vsay("You cancelled the update, so your game files were not changed.")    # user-approved 2026-11-16
                launched = _offer_after_nothing_changed(relaunch_exe)
            elif code == EXIT_ABORTED:
                # A worker child refused before touching anything; its own message, disk
                # statement and remedy are printed above (with `say`, not muted). Do not
                # contradict them with "not certain how far it got".
                _rule("NOTHING WAS CHANGED")
                _vsay("The update was stopped before anything was changed. The reason is shown above.")
                launched = _offer_after_nothing_changed(relaunch_exe)
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
            (bad if e.red else say)(e.message)
            if e.detail:
                say("")
                say(e.detail)
            if e.disk_note is not False:
                _disk_statement(e.changed, e.disk_note, out=say)
            if e.remedy:
                say(f"\nWhat to do: {e.remedy}")
            wait_any = e.any_key
            if e.offer_play and not is_worker():
                try:
                    exe = relaunch_exe() if callable(relaunch_exe) else relaunch_exe
                    if exe:
                        launched = offer_relaunch(exe, default=e.offer_play_default)
                except Exception:  # noqa: BLE001
                    pass

        except KeyboardInterrupt:
            code = EXIT_INTERRUPTED
            try:
                c = cancelled() if callable(cancelled) else cancelled
            except Exception:  # noqa: BLE001 - a verdict must print whatever is missing
                c = None
            if c:
                title, body, closing = c
                _rule(title)
                _vsay(body)
                _vsay("\n" + closing)
            else:
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
                if wait_any:
                    wait_for_key("Press any key to close this window...", any_key=True)
                else:
                    wait_for_key()
            if not console_available():
                # pythonw.exe / no console: everything above went nowhere. Show it.
                _show_message_box("Longevity Vaccine Installer", "\n".join(_transcript))
        except BaseException:  # noqa: BLE001
            pass

    return code
