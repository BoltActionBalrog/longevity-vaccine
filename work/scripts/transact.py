"""Commit phase: patch a temp copy, verify it, then swap it in atomically.

Because the preflight already proved the patch set applies, the core update never needs a
destructive restore. The old shape was:

    restore .bak over the live exe   <- the live exe is now unpatched
    apply the new patch set          <- if this fails, the player has a half-done install

and the new one is:

    copy .bak -> temp
    apply the patch set to the temp copy
    assert md5(temp) == the target's recorded lock
    atomically replace the live exe with temp

so the live exe is never in a half-patched state and **.bak is never written to on the update
path** -- which matters, because it is the one file a player cannot afford to lose. The patcher
already refuses to overwrite an existing .bak, and this path never asks it to.

Companion binaries (prax.dll on the PRACX targets) commit the same way, and all of them commit or
none do: a failure patching prax.dll must not leave a patched exe paired with an unpatched
companion.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import apply_patches as ap  # noqa: E402


class CommitError(Exception):
    """A commit could not be completed. Nothing was swapped in."""


def _md5(p: Path) -> str:
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def _clean_base(target: Path, spec) -> Path:
    """The bytes to patch FROM: the .bak when one exists, else the target itself."""
    bak = Path(target).with_suffix(Path(target).suffix + ".bak")
    bak_md5 = _md5(bak) if bak.is_file() else None
    if bak_md5 == spec.base_md5:
        return bak
    live_md5 = _md5(Path(target))
    if live_md5 == spec.base_md5:
        return Path(target)
    # The measured hashes ARE the diagnosis (a PRACX the player updated, GOG re-verified files, another
    # mod): without them the refusal names only what was expected (audit 2026-11-07).
    raise CommitError(
        f"neither {Path(target).name} (MD5 {live_md5}) nor its .bak "
        f"({'MD5 ' + bak_md5 if bak_md5 else 'absent'}) is the clean base {spec.base_md5} that target "
        f"{spec.id!r} expects")


def stage_one(target: Path, patches: Path, spec, work_dir: Path, say=print, summary=None) -> Path:
    """Produce a fully patched candidate in `work_dir`. Does not touch the live file.

    `summary`, when given, is apply_patches' one-line-per-phase sink (status, text): the patcher then
    prints NO per-site transcript (the installer's patch log was 850 KB of it per run), while a
    failing site still arrives through the sink with its bytes. None = the developer transcript.
    """
    target, work_dir = Path(target), Path(work_dir)
    # The commit is an atomic rename, and a rename cannot cross volumes. With work_dir on %TEMP%
    # (C:) and the game on D: -- the most natural caller configuration -- every commit failed at
    # the last step with "cannot move the file to a different disk drive". Fail here, with a
    # reason, rather than after the whole patch run.
    #
    # BEFORE the mkdir: this is a pure path comparison, and creating the directory first meant a
    # refusal still littered a folder on the wrong volume -- and made the case untestable without
    # a second real volume, which is why it went unprotected.
    if Path(work_dir).resolve().drive.lower() != target.resolve().drive.lower():
        raise CommitError(
            f"the staging directory ({work_dir.resolve().drive}) is on a different volume from "
            f"{target.name} ({target.resolve().drive}). The commit is an atomic rename, which "
            f"cannot cross volumes -- stage under the game directory instead.")
    work_dir.mkdir(parents=True, exist_ok=True)
    src = _clean_base(target, spec)
    # Guarantee a CLEAN BACKUP in the game directory before anything is replaced.
    #
    # When the live file is itself the clean base (a first patch of a companion such as
    # prax.dll), the patcher's own backup went to the temp work dir and was discarded -- so after
    # the commit the game folder held a patched file and NO .bak, and the NEXT update found
    # neither a clean live file nor a backup and failed permanently. The main exe escaped this
    # only because install.py's non-transactional path happened to leave one behind.
    bak = target.with_suffix(target.suffix + ".bak")
    if src == target and not bak.exists():
        shutil.copy2(target, bak)
        say(f"  backed up the original {target.name} -> {bak.name}")

    # Which file the candidate is patched FROM is the one fact about the player's .bak a reader of the
    # record needs (is it trustworthy?); the header above it names only the TABLE's expected base.
    say(f"  patching {target.name}: target {spec.id!r}, from {src.name} (MD5 {spec.base_md5})")
    cand = work_dir / target.name
    shutil.copy2(src, cand)

    # The candidate has no .bak beside it, so the patcher's own backup step writes one in the temp
    # dir and the real .bak is untouched.
    sink = None
    if summary is not None:
        def sink(status, text, _summary=summary):
            # The patcher backs up the CANDIDATE in the work dir; left as is, "Backup: X.bak" reads as if
            # the game folder's .bak were written on every update, which this module promises never happens.
            if status == "info" and text.startswith("Backup: "):
                text += " (the patcher's copy of the staged candidate in the work folder; the game folder's " \
                        ".bak is not touched)"
            _summary(status, text)
    rc = ap.apply_patches(cand, Path(patches), do_apply=True, spec=spec, summary=sink)
    if rc != 0:
        raise CommitError(f"patching the staged copy of {target.name} failed (code {rc})")

    got = _md5(cand)
    if spec.patched_md5 and got != spec.patched_md5:
        raise CommitError(f"staged {target.name} is {got}, expected {spec.patched_md5}")
    say(f"  staged {target.name}: {got}")
    return cand


def commit(pairs: list, say=print) -> None:
    """Atomically replace each live file with its staged candidate.

    `pairs` is [(live_path, staged_path), ...]. All of them are swapped, or -- as far as is
    possible on Windows -- none: every candidate is verified and every destination is proven
    writable BEFORE the first swap, and any failure mid-sequence rolls the earlier swaps back.
    """
    for live, cand in pairs:
        live, cand = Path(live), Path(cand)
        if not cand.is_file():
            raise CommitError(f"staged file missing: {cand}")
        if live.exists():
            try:
                with live.open("r+b"):
                    pass
            except OSError as e:
                raise CommitError(f"{live.name} is not writable ({e}) -- nothing was swapped")

    done = []
    try:
        for live, cand in pairs:
            live, cand = Path(live), Path(cand)
            existed = live.exists()
            rollback = cand.with_suffix(cand.suffix + ".prev")
            if existed:
                shutil.copy2(live, rollback)      # so a later failure can be undone
            Path(cand).replace(live)
            # Record whether the destination EXISTED. A file we created has no .prev, and simply
            # skipping it on rollback left a new companion installed beside a reverted exe --
            # exactly the mixed state this function exists to prevent.
            done.append((live, rollback if existed else None, existed))
            say(f"  installed {live.name}")
    except OSError as e:
        undone, failed = 0, []
        for live, rollback, existed in reversed(done):
            try:
                if existed and rollback and rollback.is_file():
                    # Restore via a temp + rename: shutil.copy2 opens the destination 'wb', so an
                    # I/O error part-way through would leave the LIVE file truncated -- the
                    # forward path has no such window and the rollback must not either.
                    tmp = Path(str(live) + ".rollback")
                    shutil.copy2(rollback, tmp)
                    tmp.replace(live)
                    undone += 1
                elif not existed:
                    live.unlink(missing_ok=True)   # we created it; remove it again
                    undone += 1
            except OSError as e2:
                failed.append(f"{live.name} ({e2})")
        msg = f"swap failed ({e}); rolled back {undone} of {len(done)} file(s)"
        if failed:
            # NEVER claim a rollback that did not happen. The old code swallowed these and still
            # reported success, leaving the user believing their install was reverted.
            msg += ". COULD NOT ROLL BACK: " + ", ".join(failed) + \
                   " -- these still hold the NEW bytes; re-run the installer to repair."
        raise CommitError(msg)


def apply_transactional(target: Path, patches: Path, spec, work_dir: Path,
                        companions: list = None, say=print, summary=None) -> dict:
    """Stage the exe (and any companions), then commit them together.

    `companions` is [(live_path, patches_path, spec), ...]. `summary` as in stage_one.
    Returns {name: md5} for what was installed.
    """
    staged = []
    results = {}
    cand = stage_one(target, patches, spec, work_dir, say=say, summary=summary)
    staged.append((Path(target), cand))
    results[Path(target).name] = _md5(cand)

    for live, cpatches, cspec in (companions or []):
        c = stage_one(live, cpatches, cspec, work_dir, say=say, summary=summary)
        staged.append((Path(live), c))
        results[Path(live).name] = _md5(c)

    commit(staged, say=say)
    return results
