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
      make its own payload EXACTLY its release's file list (complete_payload): gen 1 is the OLDER
          release and staged it with ITS list; missing files come from the verified archive
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
# Run as a script, this module is __main__; install.py and thinker_flow's `import bootstrap` must get THIS one,
# never a second copy with its own state (the double import that hid journey R's verdict in install.py).
if __name__ == "__main__":
    sys.modules.setdefault("bootstrap", sys.modules[__name__])

import installer_exit as ix  # noqa: E402  (stdlib-only; safe at module scope)
import version as ver        # noqa: E402  (stdlib-only; ships in `base`)

MAX_GENERATION = 2
#: How long gen 2 waits for gen 1 to exit before giving up and refusing to swap.
PARENT_WAIT_SECONDS = 60

UPDATER_DIR = "updater"
OLD_DIR = "updater.old"
NEW_DIR = "updater.new"
VERSION_FILE = "VERSION"


def _rm_tree(game_dir: Path, p: Path) -> None:
    """shutil.rmtree, never through a junction or symlink on the way from the game folder (safe_fs; verification
    of f076f34). A tree outside the game folder (a test's deploy target) is checked from its own parent."""
    import safe_fs
    p = Path(p)
    try:
        p.relative_to(Path(game_dir))
        root = Path(game_dir)
    except ValueError:
        root = p.parent
    safe_fs.rmtree(root, p)


def _refuse_link(game_dir: Path, dest: Path) -> None:
    """Nothing of the updater is written through a junction or symlink on the way from the game folder (audit-j L3: a
    junctioned LongevityMods got a new updater copy at every setup, and updater.prev copies outside the game folder
    that could not be deleted again) -- as logs and staging. Raises OSError naming the link; the caller says that this
    copy cannot update itself. A destination outside the game folder (a test's) is not checked."""
    import safe_fs
    try:
        Path(dest).relative_to(Path(game_dir))
    except ValueError:
        return
    link = safe_fs.first_link(Path(game_dir), Path(dest))
    if link is not None:
        raise OSError(f"{link} is a link to another folder")      # user-approved wording 2026-11-16 (in the updater warning)


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
    import safe_fs
    if safe_fs.link_on_path(Path(game_dir), root / UPDATER_DIR):
        return                                        # never promotes or deletes through a link (audit-j L3)
    live = root / UPDATER_DIR
    old, new = root / OLD_DIR, root / NEW_DIR
    prev, staging = live.with_name(live.name + ".prev"), live.with_name(live.name + ".staging")

    if is_usable(live):
        for stale in (old, new, prev, staging):
            if stale.exists():
                say(f"  cleaning up {stale.name} left by an interrupted update")
                _rm_tree(game_dir, stale)
        return

    # The live copy is missing or unusable. Promote the best VALID candidate, newest first.
    if live.exists() and not live.is_dir():
        say("  removing a stray file where the updater directory belongs")
        try:
            import safe_fs
            safe_fs.unlink(Path(game_dir), live)          # never through a junctioned LongevityMods
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
        # A copy that carries its file list (written FIRST) must match it: is_usable alone passed a copy cut
        # short after python.exe but before its DLLs (audit 2026-11-19, L1). A list this code cannot read (a
        # newer release's) leaves is_usable as the test.
        cand_inv = _lenient_inventory(cand)
        off = _inexact(cand, cand_inv) if cand_inv is not None else ""
        if off:
            say(f"  ignoring {cand.name}: incomplete ({off})")
            continue
        say(f"  {why} ({cand.name})")
        if live.exists():
            _rm_tree(game_dir, live)
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
                _rm_tree(game_dir, stale)
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
    ("art/pracx_icons_overlay.pcx", "work/art/pracx_icons_overlay.pcx"),   # patch_icons.py's art (optional)
    ("portraits/LONGEVITY_PORTRAITS_README.txt", "work/art/portraits-README.txt"),   # deploy_runtime's guide (optional)
)

#: The release's OWN list of its payload: every file of the base archive but the root launchers, with its sha256
#: and size (release.py writes it). It lives under scripts/, the one folder every shipped generation 1 copies
#: whole, so it reaches generation 2 whatever list the older generation 1 copied with. Where it exists it -- not
#: PAYLOAD -- says what a payload is: PAYLOAD is a second list that a FROZEN generation 1 applied to a NEWER
#: archive, which is how 1.0.1's in-game update lost the PRACX icon art (2026-11-18).
INVENTORY_REL = "scripts/payload_inventory.json"
INVENTORY_FORMAT = 1
#: Archive members that are not part of the payload: the launchers a player runs from the extracted zip.
ROOT_ONLY = ("INSTALL.bat", "UNINSTALL.bat")
#: Files of a payload directory that are not payload: the version stamp deploy() writes, and the list itself.
_NOT_PAYLOAD = (VERSION_FILE, INVENTORY_REL)


def make_inventory(entries) -> bytes:
    """The inventory for `entries`, an iterable of (payload path, bytes). Deterministic (sorted, no timestamps),
    so a rebuilt archive still hashes the same."""
    import hashlib
    import json
    files = {}
    for rel, data in entries:
        if rel in ROOT_ONLY or rel in _NOT_PAYLOAD:
            continue
        files[rel] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    doc = {"format": INVENTORY_FORMAT, "files": dict(sorted(files.items()))}
    return (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("ascii")


#: Names Windows reserves at every folder level, with or without an extension.
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}


def _safe_rel(rel) -> bool:
    """A payload path that stays inside the payload and names one file Windows can hold: relative, forward
    slashes, no `..`, no drive or stream, no part ending in a dot or space (Windows drops them) and no device
    name (audit 2026-11-19, L3)."""
    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\\" in rel or ":" in rel:
        return False
    for part in rel.split("/"):
        if part in ("", ".", "..") or part.endswith((".", " ")):
            return False
        if part.split(".")[0].upper() in _RESERVED_NAMES:
            return False
    return True


def parse_inventory(raw: bytes) -> dict:
    """{payload path: (sha256, size)} from an inventory's bytes; OSError when it is not one."""
    import json
    try:
        doc = json.loads(raw.decode("ascii"))
        files = doc["files"] if doc.get("format") == INVENTORY_FORMAT else None
        out = {rel: (str(v["sha256"]).lower(), int(v["size"])) for rel, v in files.items()}
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise OSError(f"the installer's file list cannot be read ({type(e).__name__})")
    bad = [rel for rel in out if not _safe_rel(rel)]
    if bad:
        raise OSError(f"the installer's file list names a path outside it: {bad[0][:80]}")
    if len({rel.casefold() for rel in out}) != len(out):
        raise OSError("the installer's file list names one file twice (letter case only differs)")
    return out


def read_inventory(root: Path):
    """The inventory of the payload at `root`, or None when it has none (a payload from before inventories, or a
    developer's checkout). OSError when one is there and cannot be read."""
    p = Path(root) / INVENTORY_REL
    if not p.is_file():
        return None
    return parse_inventory(p.read_bytes())


def _sha256_file(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _is_bytecode(rel: str) -> bool:
    """Bytecode the interpreter writes beside a script it runs: never payload, never a difference."""
    return "__pycache__" in rel.split("/") or rel.endswith(".pyc")


def payload_diff(root: Path, inv: dict) -> tuple:
    """(missing, differing, extra) payload paths of the directory `root` against inventory `inv`, each sorted.
    `extra` leaves out the version stamp, the inventory and bytecode."""
    root = Path(root)
    missing, differing = [], []
    for rel, (digest, size) in sorted(inv.items()):
        p = root / rel
        if not p.is_file():
            missing.append(rel)
        elif p.stat().st_size != size or _sha256_file(p) != digest:
            differing.append(rel)
    extra = []
    if root.is_dir():
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if rel not in inv and rel not in _NOT_PAYLOAD and not _is_bytecode(rel):
                extra.append(rel)
    return missing, differing, sorted(extra)


def _inexact(root: Path, inv: dict) -> str:
    """'' when `root` holds exactly the files of `inv`, else a short account of what is off (for a log line)."""
    missing, differing, extra = payload_diff(root, inv)
    out = []
    for what, items in (("missing", missing), ("different", differing), ("not in the list", extra)):
        if items:
            out.append(f"{what}: {', '.join(items[:3])}" + (f" and {len(items) - 3} more" if len(items) > 3 else ""))
    return "; ".join(out)


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


class IncompletePayload(OSError):
    """A payload that lacks (or has damaged) files its own list names. The remedy is a complete copy -- extract the
    whole archive again, or download it -- never the same run again."""

    def __init__(self, msg: str, missing=()):
        super().__init__(msg)
        self.missing = list(missing)


def _lenient_inventory(root: Path):
    """read_inventory, or None when the list is absent OR cannot be read: a NEWER release's list, which this
    (by then frozen) code may not understand, must never stop it staging that release (audit 2026-11-19, H1)."""
    try:
        return read_inventory(root)
    except OSError:
        return None


def _copy_listed(src_root: Path, dst: Path, inv: dict) -> int:
    """Copy the listed files that exist from `src_root` to `dst`; the number copied. The list goes FIRST, so a
    copy cut short still carries it and reconcile() can tell it is not complete."""
    src_root, dst = Path(src_root), Path(dst)
    (dst / INVENTORY_REL).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_root / INVENTORY_REL, dst / INVENTORY_REL)
    copied = 0
    for rel in sorted(inv):
        src = src_root / rel
        if not src.is_file():
            continue
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        copied += 1
    return copied


def _short(items) -> str:
    items = list(items)
    return ", ".join(items[:3]) + (f" and {len(items) - 3} more" if len(items) > 3 else "")


def deploy(game_dir: Path, payload_root: Path, version: str, dest: Path = None,
           say=print, strict: bool = True) -> Path:
    """Copy the installer's own payload into the resident updater directory, repo-shaped.

    This is what makes the in-game prompt able to find an installer at all: before it existed,
    install.py deployed only uimod.dll and the ffmpeg DLLs, so "spawn the installer" had nothing
    to spawn once the player deleted their download.

    REFUSES to publish an incomplete payload. It used to warn per missing item and publish
    anyway, so running --repair from a resident copy (whose layout it could not read) replaced a
    working 400 MB updater with a single VERSION file -- and that VERSION then lied, so the next
    check reported "already current" forever. The repair button destroyed the thing it repairs.

    `strict` (a first install, --repair): the payload must be exactly its own file list
    (IncompletePayload otherwise). Not strict (generation 1 staging a NEWER release): copy what the
    list names, or PAYLOAD when the list is absent or not understood, and leave exactness to that
    release's generation 2, which can complete it from the archive -- a frozen generation 1 that
    refused here would stop the one program able to repair it (audit 2026-11-19, H1).
    """
    payload_root = Path(payload_root)
    dest = Path(dest) if dest else updater_dir(game_dir)
    staged = dest.with_name(dest.name + ".staging")
    _refuse_link(game_dir, dest)

    absent = [rel for rel in required_parts() if not _source_of(payload_root, rel).exists()]
    if absent:
        raise OSError(
            f"the payload at {payload_root} is not a complete installer (missing: "
            f"{', '.join(absent)}). Refusing to publish it over Longevity Vaccine's updater.")

    # The payload's own list, when it has one: then exactly its files are copied, whatever PAYLOAD says.
    inv = read_inventory(payload_root) if strict else _lenient_inventory(payload_root)
    if inv is not None and strict:
        lacking = [rel for rel in sorted(inv) if not (payload_root / rel).is_file()]
        if lacking:
            raise IncompletePayload(f"{payload_root} is missing {len(lacking)} of the installer's files "
                                    f"({_short(lacking)})", lacking)
    if inv is not None:
        need = sum(size for _d, size in inv.values())
    else:
        need = _tree_size(payload_root, [str(_source_of(payload_root, d)) for d, _s in PAYLOAD])
    free = shutil.disk_usage(str(dest.parent if dest.parent.exists() else game_dir)).free
    # The publish keeps the old copy alongside the new one until the last rename, so the peak is
    # roughly twice the payload.
    if free < need * 2:
        raise OSError(
            f"not enough space to install the updater: need about "
            f"{need * 2 / (1 << 20):.0f} MB free, have {free / (1 << 20):.0f} MB")

    _rm_tree(game_dir, staged)
    staged.mkdir(parents=True, exist_ok=True)

    if inv is not None:
        copied = _copy_listed(payload_root, staged, inv)
    else:
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
        _rm_tree(game_dir, staged)
        raise OSError(f"the staged updater is incomplete (missing: "
                      f"{', '.join(missing_parts(staged))}); nothing was replaced")
    if inv is not None and strict:
        missing, differing, _extra = payload_diff(staged, inv)
        if missing or differing:
            _rm_tree(game_dir, staged)
            raise IncompletePayload(f"{len(missing) + len(differing)} of the installer's files are missing or "
                                    f"damaged in {payload_root} ({_short(missing + differing)})",
                                    missing + differing)

    # Publish by rename, so a half-copied payload is never visible as the resident updater.
    dest.parent.mkdir(parents=True, exist_ok=True)
    prev = dest.with_name(dest.name + ".prev")
    _rm_tree(game_dir, prev)
    if prev.exists():
        # rmtree(ignore_errors=True) can be silently defeated by a lock, and the publish would
        # then fail against an existing directory. Step aside to a unique name instead.
        prev = dest.with_name(f"{dest.name}.prev.{os.getpid()}")
        _rm_tree(game_dir, prev)
    _publish(staged, dest, prev, say=say)
    _rm_tree(game_dir, prev)
    say(f"  Longevity Vaccine's updater deployed: {dest}  (v{version}, {copied} component(s))")
    return dest


def swap_in(game_dir: Path, new_payload: Path, say=print) -> None:
    """Make `new_payload` the resident updater. With a file list it copies exactly the list (and the version
    stamp) and requires the copy to match it; bytecode the running interpreter wrote is never copied."""
    if not is_usable(new_payload):
        raise OSError(f"refusing to install an incomplete updater (missing: "
                      f"{', '.join(missing_parts(new_payload))})")
    root = mods_root(game_dir)
    live, old, new = root / UPDATER_DIR, root / OLD_DIR, root / NEW_DIR
    _rm_tree(game_dir, new)
    inv = read_inventory(new_payload)
    if inv is not None:
        new.mkdir(parents=True, exist_ok=True)
        _copy_listed(new_payload, new, inv)
        if (Path(new_payload) / VERSION_FILE).is_file():
            shutil.copy2(Path(new_payload) / VERSION_FILE, new / VERSION_FILE)
    else:
        shutil.copytree(new_payload, new, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if not is_usable(new):
        _rm_tree(game_dir, new)
        raise OSError("the copy of the new updater came out incomplete; nothing was replaced")
    off = _inexact(new, inv) if inv is not None else ""
    if off:
        _rm_tree(game_dir, new)
        raise OSError(f"the copy of the new updater does not match its file list ({off}); nothing was replaced")
    if live.is_dir():
        _rm_tree(game_dir, old)
        if old.exists():
            # rmtree(ignore_errors=True) can be silently defeated by a lock, and the rename below
            # would then fail against an existing directory. Step aside to a unique name instead.
            old = root / f"{OLD_DIR}.{os.getpid()}"
            _rm_tree(game_dir, old)
    _publish(new, live, old, say=say)
    _rm_tree(game_dir, old)
    say("  Longevity Vaccine's updater replaced with the new generation")


def run(argv: list = None) -> int:
    apr = argparse.ArgumentParser(description="Longevity Vaccine self-update bootstrap")
    # NOT required: run-install.bat routes --update here, and a player typing
    # `run-install.bat --update` gives no --game-dir. argparse would have answered that with a
    # usage error, which the guard reports as "the installer did not understand its arguments".
    apr.add_argument("--game-dir", default=None)
    apr.add_argument("--generation", type=int, default=1)
    apr.add_argument("--wait-pid", type=int, default=None)
    apr.add_argument("--swap-into", default=None,
                     help="the folder of Longevity Vaccine's updater that this generation should become")
    apr.add_argument("--manifest", default=None)
    # run-install.bat forwards its WHOLE argument list here, `--update` included. Without this
    # line argparse answered every `run-install.bat --update` with "unrecognized arguments":
    # the launcher's one job, and the in-game update button's whole path, was dead.
    apr.add_argument("--update", action="store_true", help=argparse.SUPPRESS)
    apr.add_argument("--modules", default=None,
                     help="Forwarded to the installer: extras to add or re-install "
                          "(movies-hd = Z2k Retro's HD Cinematics, portraits-hd = Turovetsky's HD Portrait Pack).")
    apr.add_argument("--no-prompt", action="store_true",
                     help="Forwarded to the installer: never ask anything.")
    # The GAME's hand-off flag (FROZEN: the DLL passes it, and every later generation must accept
    # it). The packs to fetch are exactly --modules -- what the game's prompt listed and the
    # player accepted -- and no other stale pack. The base still updates when it is stale.
    apr.add_argument("--only-listed", action="store_true",
                     help="Forwarded to the installer: fetch only the packs named by --modules.")
    apr.add_argument("--repair", action="store_true",
                     help="reinstall Longevity Vaccine's updater from a freshly downloaded module")
    apr.add_argument("--no-wait", action="store_true")
    apr.add_argument("--offline", action="store_true")
    # Thinker update (thinker-updater-design.md): forwarded to the worker; the second only changes the
    # waiting line (the pid is the startup-box repair window, not the game).
    apr.add_argument("--with-thinker", action="store_true", help=argparse.SUPPRESS)
    apr.add_argument("--keep-thinker", action="store_true", help=argparse.SUPPRESS)
    apr.add_argument("--from-fix-thinker", action="store_true", help=argparse.SUPPRESS)
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
    global _GAME_DIR, _WAIT_PID
    _GAME_DIR, _WAIT_PID = game_dir, args.wait_pid

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
    if args.from_fix_thinker and args.wait_pid:
        ix.say("\nWaiting for the previous window to close.")
        _wait_for_pid(int(args.wait_pid))
    else:
        inst.wait_for_game(args.wait_pid)
    # The game's (or the repair window's) Thinker consent: checked and deleted HERE, after its writer has
    # gone, and handed to the worker in its environment only (section 8; round-6 finding B5).
    try:
        import thinker_flow
        _consent = thinker_flow.take_for_generation_one(game_dir)
    except Exception:  # noqa: BLE001 - no consent is the safe outcome: the worker asks
        _consent = None
    if _consent:
        os.environ[thinker_flow.CONSENT_ENV] = _consent
    if args.no_prompt:
        os.environ["LONGEVITY_PLAYER_NO_PROMPT"] = "1"
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
        ix.say("  --repair: reinstalling Longevity Vaccine's updater from the downloaded installer")
    elif decision.action == mfmod.NOTHING and not args.modules:
        ix.say(f"  already current (v{installed}); nothing needs updating")
        for n in sorted(content):
            ix.say(f"  {inst.MODULE_LABELS.get(n, n)}: up to date (v{content[n]})" if n not in left
                   else f"  {inst.MODULE_LABELS.get(n, n)} v{_offered(doc, n) or '?'}: not part "
                        f"of this update (stays at v{content[n]})")
        rc.note_check(game_dir)
        # The retry of an update that failed past its receipt write (audit-h L1, W23): "See what's new" still closes
        # this verdict, and the kept file goes.
        inst.finish_whats_new(game_dir, recorded, recorded)
        # Wine: a GOG / Heroic file check may have put DDrawCompat back since the install, and this branch is
        # what a player's `--update` with nothing new reaches (install.py never runs). getattr: an install.py
        # from before this step must not break the idle answer.
        ddraw_step = getattr(inst, "wine_ddrawcompat", None)
        ddraw_status = ddraw_step(game_dir) if ddraw_step else ""
        # The one thing an up-to-date player has not been told: a pack they could add.
        inst.offer_optional_modules(game_dir, doc, sorted(content), args)
        global _VERDICT, _NOTE_ARGS
        current = {n: v for n, v in content.items() if n not in left}
        idle = _idle_verdict(inst, installed, current, inst.announced_modules(game_dir, doc, sorted(content)),
                             left=[inst.MODULE_LABELS.get(n, n) for n in sorted(left)])
        if ddraw_status in ("moved", "restored", "dropped"):
            idle = idle.replace("Nothing was changed", "Nothing else was changed (ddraw.dll: see above)")
        _VERDICT = ("ALREADY UP TO DATE", idle)
        _offer_start()                          # nothing changed: [y/N]
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
    if args.with_thinker:
        cmd += ["--with-thinker"]
    if args.keep_thinker:
        cmd += ["--keep-thinker"]
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
                "window. Watch THAT window for the result. Nothing has been changed in "
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
                 + " can be added (see \"optional extras\" above).")
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
                          mirror=base.get("mirror"), allow_file=local_manifest, label="installer", root=game_dir)
    except fetchmod.LinkError as e:
        # A link on the way into the game folder: the approved line alone, uncut (audit-g LOW-1).
        raise ix.InstallerError(str(e), code=ix.EXIT_ABORTED, changed=False) from e
    except fetchmod.MismatchError as e:
        # Arrived whole and is not the release: not a connection problem (verification 2026-11-15). User-approved
        # message (2026-11-15); the remedy is this file's own (the manifest-fetch failure's).
        raise ix.InstallerError(
            "The new installer that was downloaded did not match the release, so nothing was changed.",
            code=ix.EXIT_ABORTED, detail=f"  {e}", changed=False,
            remedy=f"try again later, or download the latest version from {mfmod.DOWNLOAD_URL}")
    except fetchmod.FetchError as e:
        raise ix.InstallerError(
            "The new installer could not be downloaded, so nothing was changed.",
            code=ix.EXIT_ABORTED, detail=f"  {e}", changed=False,
            remedy="check your connection and try again.")
    out = staging / f"base-{latest}"
    _rm_tree(game_dir, out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as z:
            z.extractall(out)
    except (zipfile.BadZipFile, OSError) as e:
        raise ix.InstallerError("The downloaded installer could not be unpacked.",
                                code=ix.EXIT_ABORTED, detail=f"  {e}", changed=False)
    # The archive is repo-shaped; the resident layout is flatter.
    flat = staging / f"payload-{latest}"
    _rm_tree(game_dir, flat)
    try:
        deploy(game_dir, out, latest, dest=flat, say=ix.say, strict=False)   # exactness is gen 2's (H1)
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


def _is_handover(game_dir: Path, root: Path, args) -> bool:
    """True for the one run completion is for: generation 2 handed `--swap-into`, running from a payload in the
    staging folder. A manual `--generation 2` run from the resident updater must never rewrite the folder it
    runs from (audit 2026-11-19, L4)."""
    if not getattr(args, "swap_into", None):
        return False
    try:
        Path(root).resolve().relative_to((mods_root(game_dir) / "staging").resolve())
        return True
    except (OSError, ValueError):
        return False


def complete_payload(game_dir: Path, root: Path, version: str, args, say=print) -> None:
    """Make the payload at `root` (generation 2's own, staged by generation 1) exactly its release's file list:
    add what is missing, replace what differs and delete what does not belong. The bytes -- and the list itself
    whenever the staged one is not exact -- come only from this release's archive, as pinned by the signed
    manifest: the copy generation 1 downloaded (still in staging: only this generation's install clears it),
    else downloaded again. Nothing is fetched when the payload already matches its list.

    Runs only on a hand-over (_is_handover). Raises InstallerError(changed=False) when the payload cannot be made
    exact; it runs before the swap and the install, so the previous updater stays in place and the game is
    untouched. A staged payload WITHOUT a list is completed from the archive's list too: generation 2 is always a
    release that ships one, so a missing list means generation 1 lost it (audit 2026-11-19, M1)."""
    root = Path(root)
    if not _is_handover(game_dir, root, args):
        return
    try:
        staged_inv = _lenient_inventory(root)
        if staged_inv is not None and not any(payload_diff(root, staged_inv)):
            return
        archive = _release_archive(game_dir, version, args)
        raw, inv = _archive_inventory(archive)
        if staged_inv is not None and staged_inv != inv:
            raise OSError("the downloaded release is not the one this installer came from")
        missing, differing, extra = payload_diff(root, inv)
        need = missing + differing
        list_ok = (root / INVENTORY_REL).is_file() and (root / INVENTORY_REL).read_bytes() == raw
        if need:
            say(f"  completing the new installer: {len(need)} file(s) from the downloaded release")      # user-approved wording 2026-11-19
            _restore_members(game_dir, archive, root, need, inv)
        if not list_ok:
            _write_in(game_dir, root / INVENTORY_REL, raw)
        for rel in extra:
            _unlink_in(game_dir, root / rel)
        off = _inexact(root, inv)
        if off:
            raise OSError(f"still not the release's files ({off})")
    except ix.InstallerError:
        raise
    except (OSError, zipfile.BadZipFile) as e:
        import manifest as mfmod
        raise ix.InstallerError(
            "The new installer's files could not be completed, so nothing was changed.",      # user-approved wording 2026-11-19
            code=ix.EXIT_ABORTED, detail=f"  {e}", changed=False,
            remedy=f"run the update again, or download the latest version from {mfmod.DOWNLOAD_URL}")


def _archive_inventory(archive: Path) -> tuple:
    """(raw bytes, parsed) of the file list inside the release archive; OSError when it has none."""
    try:
        with zipfile.ZipFile(archive) as z:
            if INVENTORY_REL not in z.namelist():
                raise OSError("the downloaded release has no file list")
            raw = z.read(INVENTORY_REL)
    except zipfile.BadZipFile as e:
        raise OSError(f"the downloaded release could not be opened ({e})")
    return raw, parse_inventory(raw)


def _release_archive(game_dir: Path, version: str, args) -> Path:
    """This release's base archive in staging, verified against the signed manifest (downloaded when it is not
    there). OSError, or InstallerError for a manifest that cannot be trusted."""
    import fetch as fetchmod
    import install as inst
    import manifest as mfmod
    import preflight as pfm
    try:
        raw, sig = inst.fetch_manifest(game_dir, args.manifest, offline=True)     # the one generation 1 used
    except ix.InstallerError:
        if args.offline:
            raise
        raw, sig = inst.fetch_manifest(game_dir, args.manifest, False)
    try:
        doc = mfmod.load_verified(raw, sig, allow_env=inst._local_manifest(args.manifest))
    except mfmod.ManifestError as e:
        raise OSError(f"the update information could not be trusted ({e})")
    mods = doc.get("modules")
    base = mods.get("base") if isinstance(mods, dict) else None
    base = base if isinstance(base, dict) else {}
    url, digest, size, have = base.get("url"), base.get("sha256"), base.get("size"), base.get("version")
    if not isinstance(have, str) or not ver.is_valid(have) or ver.normalise(have) != ver.normalise(version):
        raise OSError(f"the update information is for v{str(have)[:20]}, not this installer's v{version}")
    if not isinstance(url, str) or not isinstance(digest, str) or not url or not digest:
        raise OSError("the update information does not say where the release is")
    archive = fetchmod.staging_dir(game_dir) / pfm.staging_name(url, "base")
    if args.offline and not archive.is_file():
        raise OSError("the downloaded release is no longer in the staging folder, and --offline forbids fetching it")
    local_manifest = bool(getattr(args, "manifest", None)) and not str(
        args.manifest).lower().startswith(("http://", "https://"))
    try:
        fetchmod.download(url, archive, sha256=digest, size=size, mirror=base.get("mirror"),
                          allow_file=local_manifest, label="installer", root=game_dir)
    except fetchmod.FetchError as e:
        raise OSError(str(e))
    return archive


def _restore_members(game_dir: Path, archive: Path, root: Path, rels: list, inv: dict) -> None:
    """Write each of `rels` from `archive` into the payload at `root`, each checked against `inv` first."""
    import hashlib
    try:
        z = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as e:
        raise OSError(f"the downloaded release could not be opened ({e})")
    with z:
        names = set(z.namelist())
        for rel in rels:
            if rel not in names:
                raise OSError(f"{rel} is not in the downloaded release")
            data = z.read(rel)
            digest, size = inv[rel]
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise OSError(f"{rel} in the downloaded release does not match its file list")
            _write_in(game_dir, root / rel, data)


def _write_in(game_dir: Path, dst: Path, data: bytes) -> None:
    """Write one payload file: under a temporary name, then renamed into place, so no half-written file is ever
    visible; never through a link on the way from the game folder."""
    import safe_fs
    dst = Path(dst)
    try:
        dst.relative_to(Path(game_dir))
        link = safe_fs.first_link(Path(game_dir), dst.parent)
    except ValueError:
        link = None
    if link is not None:
        raise OSError(f"{link} is a link to another folder")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".lvpart")
    try:
        tmp.write_bytes(data)
        _replace_file_retrying(tmp, dst)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _replace_file_retrying(src: Path, dst: Path) -> None:
    """os.replace for one FILE, waited out while another program holds `dst` (a virus scan of a fresh copy)."""
    patience = _Patience(None)
    while True:
        try:
            os.replace(str(src), str(dst))
            return
        except PermissionError:
            if not patience.wait():
                raise


def _unlink_in(game_dir: Path, p: Path) -> None:
    """Delete one stray file of the payload; never through a link on the way from the game folder."""
    import safe_fs
    try:
        p.relative_to(Path(game_dir))
        root = Path(game_dir)
    except ValueError:
        root = p.parent
    if p.exists() and not safe_fs.unlink(root, p):
        raise OSError(f"{p.name} could not be removed")


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
    #
    # But FIRST make this payload whole. Generation 1 is the OLDER release's code and staged this payload with ITS
    # list of files, so anything this release added outside the folders it copies whole was left behind -- and
    # then became resident, so every later run lacked it too (1.0.0 -> 1.0.1 lost the PRACX icon art). This
    # generation's own list decides, and a payload that cannot be made exact stops here: nothing changed.
    import config as _cfg
    complete_payload(game_dir, _cfg.payload_root_from(_SCRIPTS), ver.VERSION, args, say=ix.say)
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
    if args.no_prompt:
        os.environ["LONGEVITY_PLAYER_NO_PROMPT"] = "1"
    code = _run_installer(_SCRIPTS, game_dir, args)
    if code not in (ix.EXIT_OK, ix.EXIT_DECLINED, ix.EXIT_ABORTED):
        ix.say("  The update did not complete. The NEW installer is already in place, so simply "
               "running it again retries from here; nothing needs downloading twice.")
    elif code == ix.EXIT_OK:
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
    if getattr(args, "with_thinker", False):
        cmd += ["--with-thinker"]
    if getattr(args, "keep_thinker", False):
        cmd += ["--keep-thinker"]
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
        # Ctrl-C reaches every process on the console: only the worker, which put the question,
        # handles it (R-STOP, "nothing was changed"); this parent ignores it while it waits
        # (thinker-updater-design.md section 3E; round-6 finding B1).
        import signal
        import receipt as rc
        # The base version before and after the worker: "See what's new" closes this verdict only when the worker
        # brought Longevity Vaccine up from an older one (never on --repair, a pack-only update or a failure).
        before = rc.module_version(rc.read(game_dir), "base")
        old = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            code = int(subprocess.call(cmd, cwd=str(scripts), env=env))
        finally:
            signal.signal(signal.SIGINT, old)
        if code == ix.EXIT_OK and not args.repair:
            after = rc.module_version(rc.read(game_dir), "base")
            inst.finish_whats_new(game_dir, before, after)    # the rule and the kept file (audit-h M2)
        return code
    except OSError as e:
        raise ix.InstallerError("The installer could not be started.",
                                code=ix.EXIT_ABORTED, detail=f"  {e}", changed=False)


def main() -> int:
    try:
        code = run()
        if code in (ix.EXIT_DECLINED, ix.EXIT_ABORTED):
            _offer_start()                      # the worker changed nothing: run_guarded offers [y/N]
        return code
    except ix.InstallerError as e:
        # A refusal that changed nothing ends like journey R's: `Start the game ... [y/N]` (user 2026-11-14).
        if e.changed is False and not e.offer_play and _offer_start():
            e.offer_play, e.offer_play_default = True, False
        raise
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
#: (game_dir, target_id) of an outcome that changed nothing but may still offer `Start the game ... [y/N]`.
_OFFER = None
#: The game folder and the --wait-pid of this run, once known (for _offer_start).
_GAME_DIR = None
_WAIT_PID = None


def _offer_start() -> bool:
    """Arm `Start the game ... [y/N]` for an outcome that changed nothing (user 2026-11-14): only for a
    folder Longevity Vaccine is installed in, and never while the game that started us is still running."""
    global _OFFER
    try:
        if _GAME_DIR is None or _NOTE_ARGS:
            return False
        import preflight
        if _WAIT_PID and preflight._pid_alive(int(_WAIT_PID)):
            return False
        import receipt as rc
        tid = rc.read(_GAME_DIR).get("target_id")
        if not tid:
            return False
        _OFFER = (_GAME_DIR, tid)
        return _relaunch_exe() is not None
    except Exception:  # noqa: BLE001 - an offer is never worth failing a verdict
        _OFFER = None
        return False


def _closing_note() -> None:
    if _NOTE_ARGS:
        import install as inst
        inst.print_play_note(*_NOTE_ARGS)
    elif sys.modules.get("install") is not None:
        # ALREADY UP TO DATE after a run that failed past its receipt write (audit-h L1, W23): the armed line alone.
        sys.modules["install"]._say_whats_new()


def _relaunch_exe():
    """The program to offer to start after an update that completed here: the one the closing note
    names (thinker.exe in a Thinker folder). An update ended without the offer a first install
    makes, though the game had just been closed for it (user 2026-11-05). After an outcome that
    changed nothing, the same program when _offer_start armed it ([y/N], user 2026-11-14). None on a
    hand-over or a failure."""
    where = _NOTE_ARGS or _OFFER
    if not where:
        return None
    import install as inst
    return inst.mod_exe(*where)


def _crash_log_dir():
    """install.crash_log_dir once install is imported and knows the game folder; else None (beside the script)."""
    inst = sys.modules.get("install")
    return inst.crash_log_dir() if inst is not None else None


if __name__ == "__main__":
    sys.exit(ix.run_guarded(
        main,
        log_dir=_crash_log_dir,
        relaunch_exe=_relaunch_exe,
        relaunch_default=lambda: bool(_NOTE_ARGS),        # [Y/n] after a change, [y/N] otherwise
        success_title=lambda: _VERDICT[0] if _VERDICT else "UPDATE COMPLETE",
        success_body=lambda: _VERDICT[1] if _VERDICT else
        "Your installation is up to date.",
        success_after=_closing_note))
