"""The self-update bootstrap. A FROZEN CONTRACT -- change it as rarely as possible.

Every installed copy of the mod runs the bootstrap it shipped with, forever. A defect here is
unreachable by any future update: the only remedy is a manual reinstall by every affected player.
So this file stays small, its behaviour is pinned by tests, and volatile logic belongs in
install.py instead.

WHY A SELF-UPDATE AT ALL: the installer and `patches.yaml` ship in the same module, and
`patches.yaml` changes every release. An installer that patched with last release's data would be
applying a patch set its own code was never written against. So "update the core patch" and
"update the installer" are one operation, and the installer has to be able to replace itself.

THE GENERATION DANCE
--------------------
A process cannot overwrite the files it is executing. A directory whose DLLs are merely MAPPED (a
loaded python312.dll) can still be renamed -- but one ordinary open file handle anywhere inside it
blocks the rename outright. So "the resident directory is idle" is a load-bearing precondition,
not a nicety, and it is why generation 2 runs from staging and waits for generation 1 to exit:

    gen 1  (runs from <game>\\LongevityMods\\updater)
      fetch + verify the manifest
      honour the kill switches FIRST -- before any version compare or download
      if a newer base module exists:
          download + verify it into staging, extract
          spawn gen 2 from staging, passing our own PID
          exit 0            <-- GEN 1 NEVER PATCHES ANYTHING
      else:
          hand off to install.py --update in place

    gen 2  (runs from staging, so `updater` is idle)
      wait for gen 1 to exit
      swap: updater -> updater.old | new -> updater | rm updater.old
      THEN do the real install (install.py --update)

The swap comes BEFORE the install on purpose. Generation 2 is already the new payload, so which
copy is resident has no effect on the install about to run -- it only decides what the player has
next time. Swapping first means an interrupted or failed update leaves the CORRECT installer
armed, with nothing to download again.

SAFEGUARDS, each of which exists because getting it wrong strands players:
  1. `--generation` is capped at 2. Gen 2 never re-execs, whatever the manifest says, so an
     update loop is structurally impossible rather than merely unlikely.
  2. Gen 1 never patches. If it decides to re-exec it exits without touching the game, so a
     failure during self-update leaves the previous working install completely intact.
  3. The swap is idempotent, and `reconcile()` repairs a crash part-way through it.
  4. A failed swap does not stop the update -- this generation applies it from staging either way.
  5. `--repair` re-deploys the resident updater from whatever payload it is run from.
  6. An unknown `manifest.protocol`, or a kill switch, stops everything and prints the
     COMPILED-IN message and URL. Never a manifest-supplied one.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import installer_exit as ix  # noqa: E402  (stdlib-only; safe at module scope)
import version as ver        # noqa: E402  (stdlib-only; ships in `base`)

MAX_GENERATION = 2
#: How long gen 2 waits for gen 1 to exit before giving up and refusing to swap.
PARENT_WAIT_SECONDS = 60

UPDATER_DIR = "updater"
OLD_DIR = "updater.old"
NEW_DIR = "updater.new"
VERSION_FILE = "VERSION"


def mods_root(game_dir: Path) -> Path:
    return Path(game_dir) / "LongevityMods"


def updater_dir(game_dir: Path) -> Path:
    return mods_root(game_dir) / UPDATER_DIR


def resident_version(game_dir: Path) -> str:
    """The resident updater's version, read from a plain text file.

    Deliberately not imported from Python: reading it must not require starting the interpreter
    that lives in the directory we may be about to replace.
    """
    import version as ver
    p = updater_dir(game_dir) / VERSION_FILE
    try:
        raw = p.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return ver.UNKNOWN
    return ver.normalise(raw) if ver.is_valid(raw) else ver.UNKNOWN


def _tree_size(root: Path, relatives) -> int:
    total = 0
    for rel in relatives:
        p = Path(root) / rel
        if p.is_file():
            total += p.stat().st_size
        elif p.is_dir():
            for f in p.rglob("*"):
                try:
                    if f.is_file():
                        total += f.stat().st_size
                except OSError:
                    pass
    return total


def reconcile(game_dir: Path, say=print) -> None:
    """Repair a crash during a swap or a deploy. Safe and idempotent; run before anything else.

    The swap is: rename updater -> updater.old, rename new -> updater, delete updater.old.
    A deploy is: build updater.staging, rename updater -> updater.prev, rename staging -> updater.
    A crash anywhere in either leaves one of a handful of states.

    EVERY candidate is validated before it is promoted. Promoting by NAME alone destroyed data:
    `updater.new` is created by a multi-hundred-megabyte copytree, so for tens of seconds it is a
    partial directory -- and reconcile would promote that empty shell and then delete
    `updater.old`, which was the only working copy left.
    """
    root = mods_root(game_dir)
    if not root.is_dir():
        return
    live = root / UPDATER_DIR
    old, new = root / OLD_DIR, root / NEW_DIR
    prev, staging = live.with_name(live.name + ".prev"), live.with_name(live.name + ".staging")

    if is_usable(live):
        for stale in (old, new, prev, staging):
            if stale.exists():
                say(f"  cleaning up {stale.name} left by an interrupted update")
                shutil.rmtree(stale, ignore_errors=True)
        return

    # The live copy is missing or unusable. Promote the best VALID candidate, newest first.
    if live.exists() and not live.is_dir():
        say("  removing a stray file where the updater directory belongs")
        try:
            live.unlink()
        except OSError:
            pass

    for cand, why in ((new, "completing an interrupted update"),
                      (staging, "completing an interrupted deploy"),
                      (old, "restoring the previous updater"),
                      (prev, "restoring the previous updater")):
        if not cand.is_dir():
            continue
        if not is_usable(cand):
            say(f"  ignoring {cand.name}: incomplete ({', '.join(missing_parts(cand))})")
            continue
        say(f"  {why} ({cand.name})")
        if live.exists():
            shutil.rmtree(live, ignore_errors=True)
        try:
            # Usually a freshly copied tree -- exactly what a virus scan is still reading.
            _replace_retrying(cand, live, say=say)
        except OSError as e:
            # Try the next candidate. Raising sent generation 1 (and --repair) to the crash
            # handler with every other copy untried.
            say(f"  could not put {cand.name} in place ({e})")
            continue
        break

    # Only now discard leftovers, and only if a usable updater survived -- otherwise the debris
    # may be all the player has.
    if is_usable(live):
        for stale in (old, new, prev, staging):
            if stale.exists():
                shutil.rmtree(stale, ignore_errors=True)
    elif any(p.exists() for p in (old, new, prev, staging)):
        say("  WARNING: no complete updater could be recovered; leftover copies were KEPT.")
        say("  Re-run the installer you downloaded to restore it.")


def _wait_for_pid(pid: int, timeout: int = PARENT_WAIT_SECONDS) -> bool:
    """Wait for a process to exit. True if it is gone."""
    import preflight
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not preflight._pid_alive(pid):
            return True
        time.sleep(0.25)
    return not preflight._pid_alive(pid)


#: What a resident updater must contain to be usable. Checked before publishing AND before
#: promoting a candidate in reconcile(): a directory that is missing any of these cannot install
#: anything, and publishing it over a working copy is how an installed copy gets stranded.
REQUIRED = (
    "scripts/run-install.bat",
    "scripts/install.py",
    "scripts/bootstrap.py",
    "patches/patches.yaml",
    "tools/python/python.exe",
)

#: The ship set, as (path IN THE PAYLOAD, where to find it in a repo checkout).
#:
#: There is exactly ONE payload layout -- the flat one above -- and a resident updater always has
#: it, whether it was deployed from a downloaded archive or from a developer's working tree. The
#: second element exists only because a checkout keeps these files under `work\`, which is a
#: folder full of tests, screenshots and notes rather than a payload. Nothing in the field ever
#: sees that shape.
PAYLOAD = (
    ("scripts/run-install.bat", "work/run-install.bat"),
    ("scripts", "work/scripts"),
    ("patches", "work/patches"),
    ("CHANGELOG.txt", "work/CHANGELOG.md"),   # .txt opens in Notepad; up to 0.2.1 it shipped as .md,
                                              # and those bootstraps skip the .md this payload lacks
    ("tools/python", "tools/python"),
    ("tools/python38", "tools/python38"),    # the Windows 7 / 8 interpreter (fetch_python38.py; absent on a bare dev tree)
    ("src/uimod/build/Release/uimod.dll", "src/uimod/build/Release/uimod.dll"),
    ("src/uimod/third_party/ffmpeg/bin", "src/uimod/third_party/ffmpeg/bin"),
    ("art/longevity_sm.pcx", "work/art/longevity_sm.pcx"),   # the update prompt's picture (optional)
)


def _source_of(root: Path, rel: str) -> Path:
    """Where `rel` -- a path INSIDE a payload -- comes from under `root`.

    `root` may be a payload (the usual case: an extracted archive, or a resident updater) or a
    developer's checkout. Payload first, checkout second, and the mapping applies to paths BELOW
    a mapped directory too, not only to exact matches: the required-files check asks for
    `scripts/install.py`, which lives at `work/scripts/install.py` in a checkout. Handling only
    exact matches made `--repair` from a checkout refuse its own tree as "not a complete
    installer".
    """
    here = Path(root) / rel
    if here.exists():
        return here
    for dst, src in PAYLOAD:
        if rel == dst:
            return Path(root) / src
        if rel.startswith(dst + "/"):
            return Path(root) / src / rel[len(dst) + 1:]
    return here


#: The interpreter THIS Windows runs the payload with. CPython 3.12 (tools/python) does not start below
#: Windows 8.1, so the payload carries CPython 3.8 (tools/python38) for Windows 7 and 8; run-install.bat
#: (`ver` 6.1 / 6.2) and the DLL's update check (lvupd::RuntimeExeRel) chose the running interpreter by that
#: boundary, so "the family of the running interpreter" is the same rule seen from inside -- and it keeps
#: a Windows 7 copy on 3.8 across every self-update.
def runtime_subdir(version=None) -> str:
    v = tuple(version) if version is not None else tuple(sys.version_info[:2])
    return "python38" if v < (3, 9) else "python"


def runtime_exe_rel(version=None) -> str:
    return f"tools/{runtime_subdir(version)}/python.exe"


def payload_python(payload: Path, version=None) -> Path:
    """`payload`'s interpreter for this Windows, or InstallerError when it is not there: a downloaded
    payload without it cannot run generation 2, and falling back to sys.executable would run the new
    installer out of the very updater directory it is about to replace."""
    import manifest as mfmod
    py = Path(payload) / runtime_exe_rel(version)
    if not py.is_file():
        raise ix.InstallerError(
            "The downloaded installer is incomplete.",
            code=ix.EXIT_ABORTED, detail=f"  no {runtime_exe_rel(version)} in {payload}",
            changed=False,
            remedy=f"download the current version from {mfmod.DOWNLOAD_URL}")
    return py


def is_usable(d: Path) -> bool:
    """True if `d` looks like an updater that can actually run -- on THIS Windows: REQUIRED names the
    3.12 interpreter every payload carries; a Windows 7 / 8 copy also needs the 3.8 one it runs on."""
    return not missing_parts(d)


def required_parts() -> tuple:
    """REQUIRED plus the interpreter THIS Windows runs the payload with (one rule for deploy()'s
    pre-copy check and for is_usable / missing_parts, so a payload is refused BEFORE it is copied)."""
    return REQUIRED if runtime_exe_rel() in REQUIRED else REQUIRED + (runtime_exe_rel(),)


def missing_parts(d: Path) -> list:
    d = Path(d)
    want = required_parts()
    return [rel for rel in want if not (d / rel).exists()] if d.is_dir() else list(want)


#: How long one publish waits for another program to let go of a file inside a directory.
#:
#: ONE handle opened without FILE_SHARE_DELETE anywhere inside a directory blocks renaming it,
#: and an on-access virus scan or an indexer opens exactly such handles -- on freshly copied
#: files above all, which is what every rename here publishes. Under load that lasts seconds.
#: Giving up at once left the PREVIOUS installer resident behind a receipt that already named
#: the new release (2026-10-28).
RENAME_RETRY_SECONDS = 30


class _Patience:
    """One bounded wait: RENAME_RETRY_SECONDS in all, backing off to 1 s, announced once."""

    def __init__(self, say):
        self.deadline = time.monotonic() + RENAME_RETRY_SECONDS
        self.delay, self.say = 0.1, say

    def wait(self) -> bool:
        """Pause before the next attempt; False once the time is up."""
        if time.monotonic() >= self.deadline:
            return False
        if self.say:
            self.say(f"  another program is using the installer's files; waiting up to "
                     f"{RENAME_RETRY_SECONDS:.0f} s for it to let go")
            self.say = None
        time.sleep(self.delay)
        self.delay = min(self.delay * 2, 1.0)
        return True


def _replace_retrying(src: Path, dst: Path, say=None) -> None:
    """`src.replace(dst)`, waited out while Windows refuses it as access-denied -- but only while
    `dst` is still free: renaming onto an existing directory is refused the same way, forever."""
    patience = _Patience(say)
    while True:
        try:
            src.replace(dst)
            return
        except PermissionError:
            if dst.exists() or not patience.wait():
                raise


def _publish(incoming: Path, live: Path, aside: Path, say=print) -> None:
    """Make `incoming` the directory at `live`, moving the previous one to `aside` (the caller
    removes it). `aside` must not exist.

    The two renames are retried as a PAIR, so `live` is missing for one rename at most: when the
    second is refused, the first is undone AT ONCE and all the waiting is done with the working
    copy in place. Waiting with it moved aside meant a closed window or a power cut left no
    updater at all -- and the game's update prompt spawns that copy, so it was dead until a
    reinstall.
    """
    if live.is_dir() and aside.exists():
        raise FileExistsError(f"{aside} is in the way")
    patience = _Patience(say)
    while True:
        moved = False
        try:
            if live.is_dir():
                live.replace(aside)
                moved = True
            incoming.replace(live)
            return
        except OSError as e:
            if moved:
                try:
                    _replace_retrying(aside, live, say=say)  # put the working one back NOW
                except OSError:
                    # What blocked the PUBLISH is the error worth reporting; the refused undo
                    # stays attached as its context, and reconcile() promotes either copy.
                    raise e
                occupied = False
            else:
                occupied = aside.exists() if live.is_dir() else live.exists()
            if not isinstance(e, PermissionError) or occupied or not patience.wait():
                raise


def deploy(game_dir: Path, payload_root: Path, version: str, dest: Path = None,
           say=print) -> Path:
    """Copy the installer's own payload into the resident updater directory, repo-shaped.

    This is what makes the in-game prompt able to find an installer at all: before it existed,
    install.py deployed only uimod.dll and the ffmpeg DLLs, so "spawn the installer" had nothing
    to spawn once the player deleted their download.

    REFUSES to publish an incomplete payload. It used to warn per missing item and publish
    anyway, so running --repair from a resident copy (whose layout it could not read) replaced a
    working 400 MB updater with a single VERSION file -- and that VERSION then lied, so the next
    check reported "already current" forever. The repair button destroyed the thing it repairs.
    """
    payload_root = Path(payload_root)
    dest = Path(dest) if dest else updater_dir(game_dir)
    staged = dest.with_name(dest.name + ".staging")

    absent = [rel for rel in required_parts() if not _source_of(payload_root, rel).exists()]
    if absent:
        raise OSError(
            f"the payload at {payload_root} is not a complete installer (missing: "
            f"{', '.join(absent)}). Refusing to publish it over the resident updater.")

    need = _tree_size(payload_root, [str(_source_of(payload_root, d)) for d, _s in PAYLOAD])
    free = shutil.disk_usage(str(dest.parent if dest.parent.exists() else game_dir)).free
    # The publish keeps the old copy alongside the new one until the last rename, so the peak is
    # roughly twice the payload.
    if free < need * 2:
        raise OSError(
            f"not enough space to install the updater: need about "
            f"{need * 2 / (1 << 20):.0f} MB free, have {free / (1 << 20):.0f} MB")

    shutil.rmtree(staged, ignore_errors=True)
    staged.mkdir(parents=True, exist_ok=True)

    copied = 0
    for dst_rel, _src_rel in PAYLOAD:
        src = _source_of(payload_root, dst_rel)
        if not src.exists():
            continue                    # optional extras (CHANGELOG, assets on a dev tree)
        dst = staged / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(src, dst)
        copied += 1
    (staged / VERSION_FILE).write_text(version + "\n", encoding="ascii")

    if not is_usable(staged):
        shutil.rmtree(staged, ignore_errors=True)
        raise OSError(f"the staged updater is incomplete (missing: "
                      f"{', '.join(missing_parts(staged))}); nothing was replaced")

    # Publish by rename, so a half-copied payload is never visible as the resident updater.
    dest.parent.mkdir(parents=True, exist_ok=True)
    prev = dest.with_name(dest.name + ".prev")
    shutil.rmtree(prev, ignore_errors=True)
    if prev.exists():
        # rmtree(ignore_errors=True) can be silently defeated by a lock, and the publish would
        # then fail against an existing directory. Step aside to a unique name instead.
        prev = dest.with_name(f"{dest.name}.prev.{os.getpid()}")
        shutil.rmtree(prev, ignore_errors=True)
    _publish(staged, dest, prev, say=say)
    shutil.rmtree(prev, ignore_errors=True)
    say(f"  resident updater deployed: {dest}  (v{version}, {copied} component(s))")
    return dest


def swap_in(game_dir: Path, new_payload: Path, say=print) -> None:
    """Make `new_payload` the resident updater."""
    if not is_usable(new_payload):
        raise OSError(f"refusing to install an incomplete updater (missing: "
                      f"{', '.join(missing_parts(new_payload))})")
    root = mods_root(game_dir)
    live, old, new = root / UPDATER_DIR, root / OLD_DIR, root / NEW_DIR
    shutil.rmtree(new, ignore_errors=True)
    shutil.copytree(new_payload, new, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if not is_usable(new):
        shutil.rmtree(new, ignore_errors=True)
        raise OSError("the copy of the new updater came out incomplete; nothing was replaced")
    if live.is_dir():
        shutil.rmtree(old, ignore_errors=True)
        if old.exists():
            # rmtree(ignore_errors=True) can be silently defeated by a lock, and the rename below
            # would then fail against an existing directory. Step aside to a unique name instead.
            old = root / f"{OLD_DIR}.{os.getpid()}"
            shutil.rmtree(old, ignore_errors=True)
    _publish(new, live, old, say=say)
    shutil.rmtree(old, ignore_errors=True)
    say("  resident updater replaced with the new generation")


def run(argv: list = None) -> int:
    apr = argparse.ArgumentParser(description="Longevity Vaccine self-update bootstrap")
    # NOT required: run-install.bat routes --update here, and a player typing
    # `run-install.bat --update` gives no --game-dir. argparse would have answered that with a
    # usage error, which the guard reports as "the installer did not understand its arguments".
    apr.add_argument("--game-dir", default=None)
    apr.add_argument("--generation", type=int, default=1)
    apr.add_argument("--wait-pid", type=int, default=None)
    apr.add_argument("--swap-into", default=None,
                     help="the resident updater directory this generation should become")
    apr.add_argument("--manifest", default=None)
    # run-install.bat forwards its WHOLE argument list here, `--update` included. Without this
    # line argparse answered every `run-install.bat --update` with "unrecognized arguments":
    # the launcher's one job, and the in-game update button's whole path, was dead.
    apr.add_argument("--update", action="store_true", help=argparse.SUPPRESS)
    apr.add_argument("--modules", default=None,
                     help="Forwarded to the installer: extras to add or re-install "
                          "(movies-hd = HD Cinematics, portraits-hd = Turovetsky's HD Portrait Pack).")
    apr.add_argument("--no-prompt", action="store_true",
                     help="Forwarded to the installer: never ask anything.")
    # The GAME's hand-off flag (FROZEN: the DLL passes it, and every later generation must accept
    # it). The packs to fetch are exactly --modules -- what the game's prompt listed and the
    # player accepted -- and no other stale pack. The base still updates when it is stale.
    apr.add_argument("--only-listed", action="store_true",
                     help="Forwarded to the installer: fetch only the packs named by --modules.")
    apr.add_argument("--repair", action="store_true",
                     help="re-deploy the resident updater from a freshly downloaded module")
    apr.add_argument("--no-wait", action="store_true")
    apr.add_argument("--offline", action="store_true")
    # TOLERANT of flags it does not know. The game's DLL can be newer than this bootstrap (the
    # resident copy is the previous release's until a swap succeeds, and a failed swap is not
    # fatal), and a strict parse turned every new protocol flag into "the installer did not
    # understand its arguments" -- the in-game update path dead until a manual reinstall. An
    # ignored flag degrades to this release's behaviour; it is named on stderr for the log.
    args, unknown = apr.parse_known_args(argv)
    if unknown:
        print("bootstrap: ignoring arguments this version does not know: "
              + " ".join(str(a)[:40] for a in unknown[:8]), file=sys.stderr)
    if args.only_listed and args.repair:
        # --repair re-deploys the updater; narrowing an update's pack set means nothing there,
        # and generation 2 never sees --repair (it would silently become a narrowed update).
        raise ix.InstallerError("--only-listed cannot be combined with --repair.",
                                code=ix.EXIT_ABORTED, changed=False,
                                remedy="run --repair on its own.")

    import manifest as mfmod
    import receipt as rc
    import version as ver

    import install as inst
    inst._load_modules()        # banner() prints ver.VERSION, which only exists after this
    # The same header the first-time install prints, before anything (the folder picker) asks;
    # the generation is an implementation detail no player needs to see (it is still in the
    # exit code / worker env for us).
    inst.banner()
    # The same folder rules as install.py: --game-dir, else the resident updater's own folder,
    # else the installed folders found on this PC (asked about when someone is at the console).
    game_dir = inst.resolve_game_dir(args, installed=True)
    inst._CRASH_LOG_GAME_DIR = game_dir      # a crash log from here goes to LongevityMods\logs (install.crash_log_dir)
    if not game_dir.is_dir():
        raise ix.InstallerError(
            "The game folder could not be found.",
            code=ix.EXIT_NO_GAME, detail=f"Looked for: {game_dir}", changed=False,
            remedy="check the --game-dir path: it must be the folder that holds terranx.exe.")
    args.game_dir = str(game_dir)

    gen = max(1, int(args.generation))
    # One installer at a time, before anything is read or written. Generation 2 waits for
    # generation 1 (which holds it until it exits) and for no one else.
    inst.hold_installer_lock(game_dir, wait_for=args.wait_pid if gen >= MAX_GENERATION else None,
                             wait_s=PARENT_WAIT_SECONDS)

    if gen >= MAX_GENERATION:
        reconcile(game_dir, say=ix.say)
        return _generation_two(game_dir, args)

    # ---- generation 1 -----------------------------------------------------------------
    # The manifest and its kill switches come FIRST -- before reconcile, before any download,
    # before touching anything. A client we are deliberately stranding should not have its
    # LongevityMods tree rewritten on the way to being told to stop.
    # Launched FROM the game: let it finish exiting before anything is checked or fetched.
    # (Generation 2 has its own --wait-pid: generation 1's.)
    inst.wait_for_game(args.wait_pid)
    explicit = []
    if args.modules:
        # BEFORE the fetch: a typo here used to cache the manifest, reconcile the tree, download
        # a whole new installer and swap it in, and only then be refused by install.py.
        explicit = inst.validate_module_names(args.modules, game_dir)
    raw, sig = inst.fetch_manifest(game_dir, args.manifest, args.offline)
    try:
        doc = mfmod.load_verified(
            raw, sig, allow_env=inst._local_manifest(args.manifest))
    except mfmod.ManifestError as e:
        raise ix.InstallerError(
            "The update information could not be trusted, so nothing was changed.",
            code=ix.EXIT_ABORTED, detail=f"  {e}", changed=False,
            remedy=f"try again later, or download the latest version from {mfmod.DOWNLOAD_URL}")

    state = rc.read(game_dir)
    # TWO versions, and they can disagree. `resident` is the installer on disk -- what decides
    # whether a NEW INSTALLER must be fetched. `installed` is what the game has, and it is the
    # OLDER of the two: generation 2 swaps the resident copy BEFORE it installs, so a gen 2 that
    # swapped and then failed (or was killed) leaves a new resident over an old receipt. Deciding
    # with the resident alone answered that state with "already current" forever, while --check
    # (which reads the receipt) went on offering the update. A base entry whose version cannot
    # be read counts as older too (--check offers it as 0.0.0); NO receipt at all proves nothing
    # and leaves the resident's.
    resident = resident_version(game_dir)
    recorded = rc.module_version(state, "base")
    has_base = isinstance((state.get("modules") or {}).get("base"), dict)
    if resident == ver.UNKNOWN:
        resident = recorded
    installed = resident
    if (recorded != ver.UNKNOWN or has_base) and ver.is_newer(resident, recorded):
        installed = recorded

    # KILL SWITCHES FIRST -- before any version comparison and before any download. This is the
    # only remedy for a defective bootstrap already in the wild: we cannot fix those installs,
    # but we can stop them retrying forever and tell them what to do.
    # Installed CONTENT modules and their versions: a stale pack is an update in its own right,
    # even when the installer itself is current (then it is applied in place, below).
    content = {n: rc.module_version(state, n) for n in rc.installed_modules(state)
               if n in inst.GAME_CONTENT_MODULES}
    decision = mfmod.decide(doc, installed, state.get("target_id"), installed_modules=content)
    if decision.action != mfmod.MANUAL and installed != resident:
        # The RUNNING installer's own version is listed too: a kill switch aimed at a defective
        # resident bootstrap must stop it whatever the receipt says.
        own = mfmod.decide(doc, resident, state.get("target_id"), installed_modules=content)
        if own.action == mfmod.MANUAL:
            decision = own
    if decision.action == mfmod.MANUAL:
        raise ix.InstallerError(
            decision.message,                      # compiled-in, never from the manifest
            code=ix.EXIT_ABORTED, changed=False,
            # `detail` is manifest-derived; manifest.py says in so many words that it must not be
            # interpolated into a player-facing sentence, and this was doing exactly that.
            remedy=f"download the current version from {decision.url}")
    # --only-listed: a stale pack the game did not list is not part of this update, so it is
    # neither announced nor fetched here; with nothing listed and the base current, there is
    # nothing to do (the worker would say the same after re-verifying the exe).
    left = [n for n in decision.modules if n not in explicit] if args.only_listed else []
    if left:
        decision.modules = [n for n in decision.modules if n in explicit]
        if decision.action == mfmod.UPDATE and not decision.modules \
                and not ver.is_newer(decision.version or installed, installed):
            decision = mfmod.Decision(mfmod.NOTHING, detail="nothing listed is stale")

    # Only now is it safe to touch the tree.
    reconcile(game_dir, say=ix.say)

    if args.repair:
        # --repair must work in the state it exists for: a corrupt resident copy, which is
        # usually ALSO "already current". Checking the version first made it a no-op precisely
        # when it was needed.
        ix.say("  --repair: re-deploying the resident updater from the downloaded installer")
    elif decision.action == mfmod.NOTHING and not args.modules:
        ix.say(f"  already current (v{installed}); nothing needs updating")
        for n in sorted(content):
            ix.say(f"  {inst.MODULE_LABELS.get(n, n)}: up to date (v{content[n]})" if n not in left
                   else f"  {inst.MODULE_LABELS.get(n, n)} v{_offered(doc, n) or '?'}: not part "
                        f"of this update (stays at v{content[n]})")
        rc.note_check(game_dir)
        # The one thing an up-to-date player has not been told: a pack they could add.
        inst.offer_optional_modules(game_dir, doc, sorted(content), args)
        global _VERDICT, _NOTE_ARGS
        current = {n: v for n, v in content.items() if n not in left}
        _VERDICT = ("ALREADY UP TO DATE", _idle_verdict(inst, installed, current,
                                                        inst.announced_modules(game_dir, doc, sorted(content)),
                                                        left=[inst.MODULE_LABELS.get(n, n)
                                                              for n in sorted(left)]))
        return ix.EXIT_OK
    elif decision.action == mfmod.UPDATE and decision.modules \
            and not ver.is_newer(decision.version or installed, installed):
        for n in decision.modules:
            ix.say(f"  {inst.MODULE_LABELS.get(n, n)} v{content.get(n, '?')} -> "
                   f"v{_offered(doc, n) or '?'}: updating now")
    elif decision.action == mfmod.NOTHING:
        # `--modules` asks for a specific module, and module versions are independent of the
        # product version. Returning "nothing to do" here killed the one flow the installer
        # itself tells players to run -- `run-install.bat --update --modules movies-hd`, printed
        # verbatim by offer_optional_modules -- whenever the base happened to be current, which
        # is the normal case for someone adding an optional pack.
        ix.say("  adding " + ", ".join(inst.MODULE_LABELS.get(n, n) for n in explicit))

    latest = decision.version or installed
    # Shape-checked: a signed manifest whose `modules` is a list, or whose `base` is a string,
    # reached `.get` and went to the crash handler instead of the "does not say where" refusal.
    mods = doc.get("modules")
    base = mods.get("base") if isinstance(mods, dict) else None
    base = base if isinstance(base, dict) else {}
    # An UNFINISHED update (the game behind the resident installer) is completed in place only
    # by the resident copy itself, and only when it is still the release on offer: the worker
    # installs its OWN version, so a resident the manifest has since withdrawn (latest rolled
    # back below it), or an older downloaded copy run with --update, would install the wrong
    # one. Those fetch `latest` instead, which also brings the resident back in line.
    pending = installed != resident
    in_place = not args.repair and not ver.is_newer(latest, resident) and (
        not pending or (latest == resident and _runs_from(updater_dir(game_dir))))
    if in_place:
        if pending:
            ix.say(f"  the last update did not finish (the game has v{installed}); "
                   f"completing it with the installer already in place")
        ix.say(f"  the installer itself is current (v{resident}); no new installer needed")
        code = _hand_off_in_place(game_dir, args)
        if code == ix.EXIT_OK and (decision.modules or explicit or pending):
            # Name what was done: "Your installation is up to date" after adding a pack said
            # nothing about the pack. `explicit` is the VALIDATED id list, so a label or a
            # different case on the command line still finds the receipt entry.
            after = rc.read(game_dir)
            names = list(dict.fromkeys(list(decision.modules) + explicit))
            done = ([f"Longevity Vaccine v{rc.module_version(after, 'base')}"] if pending
                    else []) + [f"{inst.MODULE_LABELS.get(n, n)} v{rc.module_version(after, n)}"
                                for n in names if n in rc.installed_modules(after)]
            if done:
                # A pack the game's list did not name stayed where it was: never "nothing else".
                stays = "".join(f" {inst.MODULE_LABELS.get(n, n)} stays at v{content.get(n, '?')} "
                                f"(not part of this update)." for n in sorted(left))
                _VERDICT = ("UPDATE COMPLETE", ", ".join(done) + " installed."
                            + (stays or " Nothing else needed changing."))
        if code == ix.EXIT_OK:
            _NOTE_ARGS = (game_dir, rc.read(game_dir).get("target_id"))
        return code

    if ver.is_newer(latest, resident):
        ix.say(f"  a newer installer is available: v{resident} -> v{latest}")
    else:
        ix.say(f"  the update to v{latest} needs its own installer (this one is v{resident}); "
               "fetching it")
    payload = _download_new_payload(game_dir, base, latest, args)

    # Spawn generation 2 from the downloaded payload and EXIT WITHOUT PATCHING.
    #
    # REPO-SHAPED paths. These three were left over from the flat resident layout, so `boot`
    # never existed and generation 1 aborted with "the downloaded installer is incomplete" on
    # every real self-update -- the one code path that cannot be fixed by a later release.
    boot = payload / "scripts" / "bootstrap.py"
    if not boot.is_file():
        raise ix.InstallerError(
            "The downloaded installer is incomplete.",
            code=ix.EXIT_ABORTED, detail=f"  no scripts/bootstrap.py in {payload}",
            changed=False,
            remedy=f"download the current version from {mfmod.DOWNLOAD_URL}")
    py = payload_python(payload)         # refuses when absent: never sys.executable, which runs out of
    launcher = [str(py), str(boot)]      # the very updater directory generation 2 is about to replace
    cmd = launcher + ["--game-dir", str(game_dir), "--generation", "2",
                      "--wait-pid", str(os.getpid()),
                      "--swap-into", str(updater_dir(game_dir))]
    if args.manifest:
        cmd += ["--manifest", args.manifest]
    if args.modules:
        cmd += ["--modules", args.modules]
    if args.only_listed:
        cmd += ["--only-listed"]
    if args.no_prompt:
        cmd += ["--no-prompt"]
    if args.no_wait:
        cmd += ["--no-wait"]
    ix.say(f"  handing over to the new installer ({latest})")
    # A NEW CONSOLE. Inheriting this one meant generation 2 wrote over generation 1's own
    # "press Enter to close this window" and the two interleaved.
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        # cwd = the GAME folder, not the staged payload: generation 2 RENAMES that payload into
        # place (swap_in), so a console started inside it is left with a working directory that
        # no longer exists -- Windows Terminal then cannot restart or close the tab cleanly
        # (2026-09-27). Every path gen 2 uses is absolute; it needs nothing from the cwd.
        subprocess.Popen(cmd, cwd=str(game_dir), close_fds=True, creationflags=flags)
    except OSError as e:
        raise ix.InstallerError(
            "The new installer could not be started, so nothing was changed.",
            code=ix.EXIT_ABORTED, detail=f"  {e}", changed=False,
            remedy=f"download the current version from {mfmod.DOWNLOAD_URL}")
    ix.say("  the new installer continues in its own window; this one closes.")
    # NOT "INSTALLATION SUCCESSFUL": generation 2 has not patched a single byte yet, and
    # telling the player it worked before it has started is the worst thing this screen can
    # say -- if gen 2 then fails they have already been told otherwise.
    _VERDICT = ("UPDATE HANDED OVER",
                f"A newer installer (v{latest}) was downloaded and has taken over in a new "
                "window. Watch THAT window for the result -- nothing has been changed in "
                "your game yet.")
    # EXIT WITHOUT A KEYPRESS. Generation 2 waits for THIS process to exit before it swaps the
    # resident updater (PARENT_WAIT_SECONDS); a "Press Enter to close this window" here left
    # gen 1 alive until the player noticed, and gen 2 refused with "the previous installer did
    # not exit" (2026-09-27). The env flag is what installer_exit.interactive() honours.
    os.environ["LONGEVITY_NO_WAIT"] = "1"
    return ix.EXIT_OK


def _idle_verdict(inst, installed: str, content: dict, absent: list, left=()) -> str:
    """One text for "nothing to do", shared in spirit with install.py's: everything installed,
    by name and version, then the extras that could be added. `left`: labels of stale packs the
    game's list did not name (--only-listed) -- not current, and not called current."""
    have = [f"Longevity Vaccine v{installed}"] + [
        f"{inst.MODULE_LABELS.get(n, n)} v{content[n]}" for n in sorted(content)]
    if left:
        text = (f"Nothing was changed: nothing listed for this update needed it "
                f"({', '.join(have)} current). {' and '.join(left)} "
                f"{'has' if len(left) == 1 else 'have'} a newer version that was not part of this "
                f"update; it was left as it is.")
    else:
        text = f"Everything you have installed is current ({', '.join(have)}). Nothing was changed."
    if absent:
        text += (" " + " and ".join(inst.MODULE_LABELS.get(n, n) for n in absent)
                 + " can be added -- see \"optional extras\" above.")
    return text


def _offered(doc: dict, name: str):
    mods = doc.get("modules") if isinstance(doc, dict) else None
    info = mods.get(name) if isinstance(mods, dict) else None
    v = info.get("version") if isinstance(info, dict) else None
    return ver.normalise(v) if isinstance(v, str) and ver.is_valid(v) else None


def _download_new_payload(game_dir: Path, base: dict, latest: str, args) -> Path:
    import fetch as fetchmod
    import manifest as mfmod
    import preflight as pfm
    url, digest, size = base.get("url"), base.get("sha256"), base.get("size")
    # TYPE-checked, not just truthy: `url: 5` reached fetch and went to the crash handler.
    if not isinstance(url, str) or not isinstance(digest, str) or not url or not digest:
        raise ix.InstallerError(
            "The update information does not say where to get the new installer.",
            code=ix.EXIT_ABORTED, changed=False,
            remedy=f"download the current version from {mfmod.DOWNLOAD_URL}")
    staging = fetchmod.staging_dir(game_dir)
    # The SAME sanitiser the preflight uses for pack archives. This had its own, weaker one:
    # a URL ending in `/.~` reduced to "." and the archive path became the staging DIRECTORY
    # itself (its .part landed beside it, outside staging); `/..` reached LongevityMods.
    archive = staging / pfm.staging_name(url, "base")
    try:
        # file:// is a TEST affordance, enabled only when the operator pointed --manifest at a
        # local file. Hardcoding it meant a signed manifest could name a local path and the
        # self-update would read it -- a capability nothing in production needs.
        local_manifest = bool(getattr(args, "manifest", None)) and not str(
            args.manifest).lower().startswith(("http://", "https://"))
        fetchmod.download(url, archive, sha256=digest, size=size,
                          mirror=base.get("mirror"), allow_file=local_manifest, label="installer")
    except fetchmod.FetchError as e:
        raise ix.InstallerError(
            "The new installer could not be downloaded, so nothing was changed.",
            code=ix.EXIT_ABORTED, detail=f"  {e}", changed=False,
            remedy="check your connection and try again.")
    out = staging / f"base-{latest}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as z:
            z.extractall(out)
    except (zipfile.BadZipFile, OSError) as e:
        raise ix.InstallerError("The downloaded installer could not be unpacked.",
                                code=ix.EXIT_ABORTED, detail=f"  {e}", changed=False)
    # The archive is repo-shaped; the resident layout is flatter.
    flat = staging / f"payload-{latest}"
    shutil.rmtree(flat, ignore_errors=True)
    try:
        deploy(game_dir, out, latest, dest=flat, say=ix.say)
    except OSError as e:
        # deploy() refuses a payload that lacks a required part (on Windows 7: tools/python38) with a bare
        # OSError; to the player that is the "downloaded installer is incomplete" verdict, not a crash.
        raise ix.InstallerError(
            "The downloaded installer is incomplete.",
            code=ix.EXIT_ABORTED, detail=f"  {e}", changed=False,
            remedy=f"download the current version from {mfmod.DOWNLOAD_URL}")
    return flat


def _runs_from(d: Path) -> bool:
    """True if THIS bootstrap is the copy inside `d` (the resident updater)."""
    try:
        return Path(d).resolve() in _SCRIPTS.resolve().parents
    except (OSError, ValueError):
        return False


def _hand_off_in_place(game_dir: Path, args) -> int:
    """Run install.py --update from THIS payload (no new installer was needed)."""
    return _run_installer(_SCRIPTS, game_dir, args)


def _generation_two(game_dir: Path, args) -> int:
    """The real work, from the downloaded payload, then the swap."""
    if args.wait_pid and not _wait_for_pid(args.wait_pid):
        raise ix.InstallerError(
            "The previous installer did not exit, so this one stopped rather than run alongside "
            "it.", code=ix.EXIT_ABORTED, changed=False,
            remedy="close any other installer window and run it again.")

    # SWAP FIRST, THEN INSTALL.
    #
    # The swap has no bearing on the install that is about to run: generation 2 is ALREADY the
    # new payload, so which copy is resident only decides what the player has NEXT time.
    # Deferring it therefore buys nothing for this run, and costs the player the correct
    # installer whenever the run fails -- and the common failures here are environmental (the
    # game is open, the disk is full, the network dropped), where the right outcome is "retry,
    # with the new installer already armed and nothing to re-download".
    #
    # The order was originally install-then-swap, on the theory that a broken new installer
    # should not become resident. That protects nobody: with the old copy resident, a broken
    # release is simply re-downloaded and re-fails on every attempt. The remedy for a bad release
    # is the kill switch (honoured by generation 1 before anything else), not a stale resident
    # copy -- and `--repair` re-deploys from whatever payload it is run from.
    if args.swap_into:
        try:
            # The payload ROOT. Found by looking for the bundled interpreter rather
            # than by counting .parent hops, because a payload is flat and a checkout is not.
            import config as _cfg
            swap_in(game_dir, _cfg.payload_root_from(_SCRIPTS), say=ix.say)
        except OSError as e:
            # Not fatal: the update itself is what matters, and this generation can still apply
            # it from staging. The player keeps the previous installer for next time.
            ix.say(f"  WARNING: could not make the new installer resident ({e}).")
            ix.say("  Continuing with the update; run --repair afterwards to refresh it.")

    ix.say("  generation 2: applying the update")
    code = _run_installer(_SCRIPTS, game_dir, args)
    if code != ix.EXIT_OK:
        ix.say("  The update did not complete. The NEW installer is already in place, so simply "
               "running it again retries from here -- nothing needs downloading twice.")
    else:
        # Name what was installed, from the receipt the worker just wrote. "Your installation
        # is up to date" said nothing about what changed.
        import install as inst
        import receipt as rc
        after = rc.read(game_dir)
        packs = [f"{inst.MODULE_LABELS.get(n, n)} v{rc.module_version(after, n)}"
                 for n in rc.installed_modules(after) if n in inst.GAME_CONTENT_MODULES]
        global _VERDICT, _NOTE_ARGS
        # Under --only-listed a stale pack the game did not name may have been left behind, and
        # this generation does not re-derive which: name the packs, do not call them current.
        _VERDICT = ("UPDATE COMPLETE",
                    f"Longevity Vaccine v{ver.VERSION} installed"
                    + ((f" (installed packs: {', '.join(packs)})." if args.only_listed
                        else f" ({', '.join(packs)} up to date).") if packs else "."))
        _NOTE_ARGS = (game_dir, after.get("target_id"))
    return code


def _payload_root_of(scripts: Path) -> Path:
    import config as _cfg
    return _cfg.payload_root_from(scripts)


def _run_installer(scripts: Path, game_dir: Path, args) -> int:
    scripts = Path(scripts)
    cmd = [sys.executable, str(scripts / "install.py"),
           "--update", "--game-dir", str(game_dir),
           # Be explicit rather than relying on install.py deriving it from its own location:
           # this generation runs from a staging payload, and its assets (uimod.dll, the ffmpeg
           # DLLs) must be found there rather than in whatever tree happens to be above it.
           "--payload-root", str(_payload_root_of(scripts))]
    if args.repair:
        cmd += ["--repair"]
    if args.manifest:
        cmd += ["--manifest", args.manifest]
    if getattr(args, "modules", None):
        # Without this a `--update --modules movies-hd` that came in through the bootstrap lost
        # the module selection entirely and updated only what was already installed.
        cmd += ["--modules", args.modules]
    if getattr(args, "only_listed", False):
        # Without it the worker added every stale pack again -- the one thing the flag forbids.
        cmd += ["--only-listed"]
    if getattr(args, "wait_pid", None):
        # Already waited for above; forwarded so the worker's preflight ASSERTS it too.
        cmd += ["--wait-pid", str(args.wait_pid)]
    if args.no_wait:
        cmd += ["--no-wait"]
    if args.offline:
        cmd += ["--offline"]
    # --no-prompt: a generation spawned by the bootstrap has no one watching it.
    cmd += ["--no-prompt"]
    # The child is a WORKER. Without this the player saw TWO verdict banners and was asked
    # to press Enter twice -- and on a failure the two contradicted each other ("Nothing on
    # disk was changed" from the child, "it is not certain how far the install got" from the
    # bootstrap). The child still writes the guard marker, so the batch handshake is intact.
    import install as inst
    env = inst.hold_installer_lock(game_dir).child_env(os.environ)     # lent: we wait for it
    env[ix.WORKER_ENV] = "1"
    try:
        # Flush first: when stdout is a pipe or a log, everything this process printed so far
        # was still buffered and came out AFTER the whole child's output.
        try:
            sys.stdout.flush()
        except (OSError, ValueError, AttributeError):
            pass
        return int(subprocess.call(cmd, cwd=str(scripts), env=env))
    except OSError as e:
        raise ix.InstallerError("The installer could not be started.",
                                code=ix.EXIT_ABORTED, detail=f"  {e}", changed=False)


def main() -> int:
    try:
        return run()
    finally:
        # Let go BEFORE run_guarded's verdict waits for Enter: a window left open on "UPDATE
        # FAILED -- simply run it again" must not refuse that very retry.
        inst = sys.modules.get("install")
        for lock in list(getattr(inst, "_HELD_LOCKS", {}).values()):
            lock.release()


#: (title, body) for the success verdict. The bootstrap is reached through
#: `run-install.bat --update`, so its outcomes are UPDATE outcomes -- run_guarded's default
#: "INSTALLATION SUCCESSFUL / ready to play" was wrong for every one of them.
_VERDICT = None
#: (game_dir, target_id) once an update really completed here (never on a hand-over: generation
#: 2 prints the closing note itself). The worker's own note is muted, so the parent prints it.
_NOTE_ARGS = None


def _closing_note() -> None:
    if _NOTE_ARGS:
        import install as inst
        inst.print_play_note(*_NOTE_ARGS)


def _relaunch_exe():
    """The program to offer to start after an update that completed here: the one the closing note
    names (thinker.exe in a Thinker folder). An update ended without the offer a first install
    makes, though the game had just been closed for it (user 2026-11-05). None on a hand-over or a
    failure, where there is no closing note either."""
    if not _NOTE_ARGS:
        return None
    import install as inst
    return inst.mod_exe(*_NOTE_ARGS)


def _crash_log_dir():
    """install.crash_log_dir once install is imported and knows the game folder; else None (beside the script)."""
    inst = sys.modules.get("install")
    return inst.crash_log_dir() if inst is not None else None


if __name__ == "__main__":
    sys.exit(ix.run_guarded(
        main,
        log_dir=_crash_log_dir,
        relaunch_exe=_relaunch_exe,
        success_title=lambda: _VERDICT[0] if _VERDICT else "UPDATE COMPLETE",
        success_body=lambda: _VERDICT[1] if _VERDICT else
        "Your installation is up to date.",
        success_after=_closing_note))
