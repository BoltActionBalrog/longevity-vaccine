"""Longevity Vaccine — SMACX UI-scaling + cinematics installer (end-user CLI wizard).

One command that takes a stock GOG install to the finished mod:
  1. detect the target exe(s) by MD5 and apply the right patch set
     (PRACX  -> full UI-scaling set;  pristine -> the uimod DLL loader),
  2. deploy uimod.dll + the slim ffmpeg DLLs beside the exe,
  3. optionally install the AI-upscaled cinematic pack and flip the runtime
     setting [UIMod] UpscaledVideos.

Re-runnable: an already-patched exe is detected and left alone (use --force to
restore from its .bak and re-patch). Reuses apply_patches.py (patch/restore/MD5)
and config.py (game-dir resolution) — no duplicated logic.

  run-install.bat                  # interactive (prompts for AI cinematics)
  run-install.bat --ai on          # non-interactive: install the HD pack
  run-install.bat --ai off         # non-interactive: original .wve (live upscale)
  run-install.bat --force          # restore + re-patch even if already patched
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
import re
import shutil
import contextlib
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent       # ...\work\scripts
sys.path.insert(0, str(_SCRIPTS))
# Run as a script (run-install.bat), this module is __main__. A module that does `import install`
# (thinker_flow, bootstrap) must get THIS one: a second copy holds its own _VERDICT / _LAUNCH_EXE /
# _NOTE_ARGS, which run_guarded below never reads.
if __name__ == "__main__":
    sys.modules.setdefault("install", sys.modules[__name__])
#: installer_exit is stdlib-only, so importing it here cannot fail for the reasons below. It must
#: be available before anything else, because it owns the exit guarantee.
import installer_exit as ix  # noqa: E402

#: config / apply_patches / version are imported INSIDE main() by _load_modules(), not here.
#: apply_patches needs pyyaml and pefile, and a module-scope ImportError would escape run_guarded
#: entirely -- the process would exit 1 with no verdict, no disk statement and no wait, which is
#: precisely the silent exit the guarantee forbids. That is not hypothetical: the payload-trim
#: task (ACTION_ITEMS "TRIM THE INSTALLER PAYLOAD") drops the bundled interpreter to the embeddable
#: distribution, and the first mistrimmed package would land here.
config = None
ap = None
ver = None


def _load_modules() -> None:
    """Import the third-party-dependent modules from inside the guard."""
    global config, ap, ver
    try:
        import config as _config
        import apply_patches as _apply_patches
        import version as _version
    except Exception as e:  # noqa: BLE001 - any import failure is the same user-facing problem
        raise ix.InstallerError(
            "The installer could not start: part of its own package is missing or unreadable.",
            detail=f"  {type(e).__name__}: {e}",
            changed=False,
            remedy="download the installer again and extract the WHOLE archive before running "
                   "it. Running it from inside the zip is the usual cause.")
    config, ap, ver = _config, _apply_patches, _version

def payload_root() -> Path:
    """Where the installer's own files live.

    The shipped payload is FLAT (`<root>/scripts/install.py`); a checkout is not
    (`<root>/work/scripts/install.py`). So the root is found by looking for the bundled
    interpreter rather than by counting `.parent` hops, which would be right for exactly one of
    the two. LONGEVITY_PAYLOAD_ROOT overrides it, which is what lets a test drive a relocated
    payload without a repo checkout.
    """
    env = os.environ.get("LONGEVITY_PAYLOAD_ROOT")
    if env:
        return Path(env)
    import config as _cfg
    return _cfg.payload_root_from(_SCRIPTS)


def find_payload(*relatives: str):
    """First existing candidate under the payload root, or None.

    Several inputs sit at different places in the repo than in a release archive -- the HD pack is
    `dist\\movies-hd` in a checkout but `movies\\hd` once staged -- so the caller lists both rather
    than the installer assuming a checkout.
    """
    root = payload_root()
    for rel in relatives:
        p = root / rel
        if p.exists():
            return p
    return None


_REPO = _SCRIPTS.parent.parent                   # kept for the repo-only dev paths below


def uimod_dll() -> Path:
    return find_payload("src/uimod/build/Release/uimod.dll", "uimod.dll") \
        or payload_root() / "src/uimod/build/Release/uimod.dll"


#: Files deploy_runtime() places beside the exe besides uimod.dll + the ffmpeg DLLs, and
#: uninstall removes: the update prompt's popup picture (release.py MODULE_SPEC "base").
POPUP_ART_NAME = "longevity_sm.pcx"


def popup_art() -> Path:
    return find_payload("art/" + POPUP_ART_NAME, "work/art/" + POPUP_ART_NAME) \
        or payload_root() / "art" / POPUP_ART_NAME


def ffmpeg_bin() -> Path:
    return find_payload("src/uimod/third_party/ffmpeg/bin", "ffmpeg") \
        or payload_root() / "src/uimod/third_party/ffmpeg/bin"


def default_pack() -> Path:
    return find_payload("movies/hd", "dist/movies-hd") or payload_root() / "dist/movies-hd"


def default_portrait_pack() -> Path:
    return find_payload("portraits/hd", "dist/portraits-hd") or payload_root() / "dist/portraits-hd"


#: The player's guide to replacement portraits (release.py MODULE_SPEC "base"), placed in <game>\portraits\.
PORTRAITS_README = "LONGEVITY_PORTRAITS_README.txt"


def portraits_readme() -> Path:
    return find_payload("portraits/" + PORTRAITS_README, "work/art/portraits-README.txt") \
        or payload_root() / "portraits" / PORTRAITS_README


#: PRACX's icon art, copied into a stock GOG Icons.pcx that lacks it (patch_icons.py).
PRACX_ICONS_OVERLAY = "pracx_icons_overlay.pcx"


def pracx_icons_overlay() -> Path:
    return find_payload("art/" + PRACX_ICONS_OVERLAY, "work/art/" + PRACX_ICONS_OVERLAY) \
        or payload_root() / "art" / PRACX_ICONS_OVERLAY


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


#: Cached target table. load_targets() re-parses the 1.77 MB patches.yaml (~2 s), and resolution
#: happens once per candidate exe, so an uncached call would stall the run for seconds at a time.
_TARGETS = None


def _targets() -> dict:
    global _TARGETS
    if _TARGETS is None:
        try:
            _TARGETS = ap.load_targets(ap.DEFAULT_PATCHES)
        except ValueError as e:
            # A malformed or unreadable shipped patches.yaml is a packaging fault, not a bug in
            # the installer -- reporting it through the crash handler would tell the player the
            # opposite.
            raise ix.InstallerError(
                "The installer's patch data could not be read.",
                detail=f"  {e}",
                changed=False,
                remedy="download the installer again and extract the WHOLE archive.")
    return _TARGETS


def _exe_names() -> list:
    """Executable names worth looking for: the configured one plus every shipping target's.

    No hardcoded names (CLAUDE.md's opening invariant) -- and a base that is not a shipping
    target contributes no candidate.
    """
    names = [config.exe_name()]
    names += [t.exe for t in _targets().values() if t.launch and t.exe]
    out = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out


def _md5_safe(p: Path, changed=False) -> str:
    """Hash a file, turning a read failure into an explained abort rather than a crash.

    `changed` is NOT decorative. This is called from sites that run after the exe has already
    been patched (the companion pass, the uninstall loop), and a hardcoded False there told the
    player "Nothing on disk was changed" about a half-finished install. Every caller past the
    first write passes True or None.
    """
    try:
        return _md5(p)
    except OSError as e:
        raise ix.InstallerError(
            f"Could not read {p.name}.",
            detail=f"  {type(e).__name__}: {e}",
            changed=changed,
            remedy="close Alpha Centauri if it is running, then re-run the installer.")


def _overlay_of(spec):
    """The folder-detected overlay (PRACX + Thinker) of a plain target: a launch target with
    requires_files on the same base. None when the table has none."""
    return next((t for t in _targets().values()
                 if t.launch and t.requires_files and t.base_md5 == spec.base_md5 and t.id != spec.id), None)


# ---- setting a folder up for Thinker ----------------------------------------------------------
# Thinker's launcher starts a file named terranx.exe and nothing else, and on a stock GOG
# Planetary Pack that name is the ORIGINAL game (no PRACX) while the PRACX build is
# terranx_PRACX.exe. A player who drops Thinker in such a folder runs Thinker on the original game
# and the mod never loads. The installer sets the folder up itself: the original terranx.exe is
# kept under a clear name (never deleted), a copy of the clean PRACX build takes its place, and
# the normal pass then patches it as the PRACX + Thinker configuration. A record file says what
# was done, so --uninstall puts the original back and a later run neither redoes it nor backs
# the original up a second time. Nothing is asked (user 2026-11-06): the swap is reversible. Every later step first reads the folder as it IS (GOG's "verify
# files" may have put the original back, Thinker may be gone, the player may have renamed
# things): it acts on the record only while the set-up is still in effect.
#
# terranx_PRACX.exe is LEFT CLEAN in a folder set up this way (put back to clean when an earlier
# plain install had patched it). Thinker players start thinker.exe; what else starts the game --
# GOG's "SMAX PRACX" entry and shortcut start terranx_PRACX.exe, its main Play button the original
# SMAC terran.exe -- is said in the closing note. An update refreshes only the receipt's exe, so a
# second patched copy would go stale beside a newer uimod.dll; a clean one is always safe to start.

#: The record of a set-up folder, beside the receipt. JSON: exe, backup (null when there was no
#: original), original_md5, source.
THINKER_SETUP_NAME = "longevity-thinker-setup.json"
#: What the original terranx.exe is kept as (a hash suffix is added if the name is taken by
#: something else).
THINKER_ORIGINAL_STEM = "_original"
_SETUP_TMP = ".longevity-tmp"


def _thinker_overlay():
    """The launcher overlay target (PRACX + Thinker): exe, launcher, requires_files. None if the
    table has none."""
    return next((t for t in _targets().values()
                 if t.launch and t.requires_files and t.exe and getattr(t, "launcher", None)), None)


def _read_setup(game_dir: Path) -> dict:
    import json
    try:
        doc = json.loads((Path(game_dir) / THINKER_SETUP_NAME).read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError, UnicodeDecodeError):
        return {}


def _write_setup(game_dir: Path, doc: dict) -> None:
    import json
    p = Path(game_dir) / THINKER_SETUP_NAME
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _pracx_source(game_dir: Path, ov) -> Path:
    """A clean PRACX build in the folder under another name than the overlay's exe (the live file,
    or the .bak of one we patched), else None."""
    for n in _exe_names():
        if n.lower() == ov.exe.lower():
            continue
        for probe in (game_dir / n, game_dir / (n + ".bak")):
            try:
                if probe.is_file() and _md5(probe) == ov.base_md5:
                    return probe
            except OSError:
                continue
    return None


def _stock_original_hashes() -> set:
    """The hashes of the ORIGINAL game's exe under the overlay's name: the table's non-launch
    entries for that file name (the un-PRACX'd GOG terranx.exe)."""
    ov = _thinker_overlay()
    return {t.base_md5 for t in _targets().values()
            if not t.launch and t.exe and ov is not None and t.exe.lower() == ov.exe.lower()
            and t.base_md5}


def _our_builds(ov) -> set:
    """Every build this project made from the PRACX base (not the base itself): this release's
    and every earlier release's (known_patched), for every configuration of that base."""
    return ap.builds_on_base(_targets(), ov.base_md5)


def _pracx_family(ov) -> set:
    """Every hash that means "already a PRACX build": the clean base and each build we make from it."""
    return _our_builds(ov) | {ov.base_md5}


def _md5_or_none(p: Path):
    try:
        return _md5(p) if p.is_file() else None
    except OSError:
        return None


def _thinker_here(game_dir: Path, ov) -> bool:
    return all((Path(game_dir) / f).is_file() for f in ov.requires_files)


def _ours_in_setup(game_dir: Path, ov) -> bool:
    """In a folder the installer set up, is the exe Thinker starts a PRACX build of OURS -- the
    clean copy, or any release's build the table records (patched_md5 + known_patched)? A build
    the table does NOT record (a dev build, or a release whose hash was never added) is still
    recognised the way the uninstall trusts a backup: the record is there, the exe is not the
    recorded original, and its .bak is the clean PRACX base the set-up put there."""
    game_dir = Path(game_dir)
    rec = _read_setup(game_dir)
    if not rec:
        return False
    live = game_dir / (rec.get("exe") or ov.exe)
    md5 = _md5_or_none(live)
    if md5 is None or (rec.get("original_md5") and md5 == rec["original_md5"]) \
            or md5 in _stock_original_hashes():
        return False                      # the original (recorded, or GOG's stock one) is back
    if md5 in _pracx_family(ov):
        return True
    return _md5_or_none(live.with_suffix(live.suffix + ".bak")) == ov.base_md5


def _setup_in_effect(game_dir: Path) -> bool:
    """The installer set this folder up for Thinker, Thinker is still here, and the exe Thinker
    starts is still a PRACX build of ours (not the original put back by GOG or by hand)."""
    ov = _thinker_overlay()
    return (ov is not None and thinker_setup_folder(game_dir) and _thinker_here(game_dir, ov)
            and _ours_in_setup(game_dir, ov))


def _backup_name(game_dir: Path, ov, md5: str) -> Path:
    stem, suf = os.path.splitext(ov.exe)
    plain = game_dir / f"{stem}{THINKER_ORIGINAL_STEM}{suf}"
    try:
        if not plain.exists() or _md5(plain) == md5:
            return plain
    except OSError:
        pass
    return game_dir / f"{stem}{THINKER_ORIGINAL_STEM}-{md5[:8]}{suf}"


def _plain_name(src: Path) -> str:
    return src.name[:-4] if src.name.lower().endswith(".bak") else src.name


def plan_thinker_setup(game_dir: Path, args):
    """Decide what the install does about Thinker. Asks nothing (user 2026-11-06) and writes
    nothing (the install applies the plan just before it patches, after every question). The plan,
    or None:

    * {"action": "setup", ...}: thinker.dll beside a PRACX build that Thinker's launcher would never
      start: the stock original, one GOG put back, none at all, or one the installer does not
      recognise (kept under a hashed name) -- all set up, console or not. terranx.exe.bak follows
      the backup rule (`_backup_kind`): GOG's original is accepted (`gog_bak`), a build of ours is
      dropped (`drop_bak`); any other stops the whole install.
    * {"action": "aside", ...}: already PRACX, only a spare terranx.exe.bak to move or drop.
    * {"action": "release"}: a folder the installer set up whose set-up is no longer in effect and
      will not be redone -- Thinker removed from the folder: the
      original goes back and the record goes, so the plain install that follows never swaps it out.

    Raises the red refusal (nothing written) for a foreign terranx.exe.bak, and for a set-up folder
    whose terranx.exe is neither the file the set-up put there nor the original it kept: a Thinker
    player asked for Thinker, and the plain build is not that (user 2026-11-06).
    """
    game_dir = Path(game_dir)
    ov = _thinker_overlay()
    if ov is None:
        return None
    record = _read_setup(game_dir)
    thinker_here = _thinker_here(game_dir, ov)
    if not thinker_here and not record:
        return None
    live = game_dir / ov.exe
    # terranx.exe.bak FIRST, whatever terranx.exe is: the patch pass writes its own backup under
    # that name only when the name is free, and otherwise keeps what is there -- so a foreign .bak
    # beside a clean PRACX terranx.exe would be patched over and leave a build with no backup the
    # installer can trust (the next run calls it unknown; --uninstall cannot restore it). A .bak that
    # is GOG's original byte for byte is a spare copy of a file the set-up keeps anyway: accepted
    # without a word (apply removes the duplicate, or sets a non-duplicate aside, named in the
    # record). Anything else is a file nobody can vouch for: the whole install stops, before
    # anything is written (user 2026-11-05). Checked before the Thinker-removed shape too: the
    # revert can leave terranx.exe a clean PRACX copy that the pass then patches.
    # This is the backup rule (`_backup_kind`) applied to the exe Thinker starts, with the set-up's
    # record: a build of ours under that name is dropped (reproducible; the pass writes a fresh one).
    bak = live.with_suffix(live.suffix + ".bak")
    bak_md5 = _md5_or_none(bak)
    gog_bak = drop_bak = None
    if bak_md5 is not None:
        kind = _backup_kind(bak_md5, ov.base_md5)
        if kind == "gog":
            gog_bak = bak
        elif kind == "ours":
            drop_bak = bak
        elif kind == "foreign":
            raise _foreign_backup(bak)
    if not thinker_here:
        # Said when it is carried out (apply_thinker_setup), never here: the Thinker question comes after this
        # plan, and "Also install" there replaces it (code review 2026-11-15: the console said "installed for
        # PRACX without Thinker" and then installed Thinker).
        return {"action": "release", "game_dir": game_dir}   # a GOG/ours .bak: plan_backups, after the revert
    md5 = _md5_or_none(live)
    if md5 in _pracx_family(ov) or _ours_in_setup(game_dir, ov):
        if md5 != ov.base_md5:
            # A build of ours whose backup is GOG's copy or another build of ours: nothing the pass
            # can patch (no clean base anywhere under this name), so the spare is left where it is
            # -- moving or dropping it would be a write before the "nothing to patch" error.
            gog_bak = drop_bak = None
        if gog_bak is not None or drop_bak is not None:
            # Already PRACX, with a spare under the name the patch pass needs: GOG's copy set
            # aside, a build of ours dropped (apply), nothing else to set up.
            return {"action": "aside", "game_dir": game_dir, "ov": ov, "gog_bak": gog_bak,
                    "drop_bak": drop_bak, "record": record}
        return None                       # already PRACX: clean, or one of ours (any release)
    restored_by_gog = bool(record) and md5 is not None and (
        md5 == record.get("original_md5") or md5 in _stock_original_hashes())
    if record and md5 is not None and not restored_by_gog:
        # The folder was set up, and its terranx.exe is now neither ours nor the recorded original
        # (with no clean-base .bak beside it, or _ours_in_setup would have said so). Setting up
        # over it would replace the record's pointer to the real original, and installing the
        # plain build beside it would not be what a Thinker player asked for: the whole install
        # stops, before anything is written (user 2026-11-06), whether or not there is a PRACX
        # copy to set up from. --uninstall leaves this terranx.exe too, so the remedy is the file.
        raise _replaced_exe(game_dir, ov.exe, record)
    src = _pracx_source(game_dir, ov)
    if src is None:
        return None                       # no PRACX build here to set up from
    backup = None
    # For the one line only: GOG's own exe (or none). A recorded original GOG did NOT write (the
    # player's own build, copied back by hand) is restored_by_gog for the flow, not "vanilla".
    vanilla = md5 is None or md5 in _stock_original_hashes()
    if md5 is not None:
        if not vanilla and not restored_by_gog and bak_md5 == ov.base_md5:
            return None                   # ours under another build: patch_target re-patches it
        backup = _backup_name(game_dir, ov, md5)
    # No question (user 2026-11-06): Thinker starts terranx.exe and nothing else, the swap is the
    # one way to play Thinker with the mod, and it is reversible (the original is kept; --uninstall
    # puts it back) -- so it simply happens, a terranx.exe the installer does not recognise
    # included (kept under a hashed _original name). apply says what it did, in one line.
    return {"action": "setup", "game_dir": game_dir, "ov": ov, "live": live, "src": src,
            "backup": backup, "md5": md5, "record": record, "gog_bak": gog_bak, "drop_bak": drop_bak,
            "vanilla": vanilla, "keep_record": _keeps_record(game_dir, record, md5)}


#: The refusal for a <exe>.bak that is none of: the clean base, GOG's original, a build of ours.
#: The user's wording (2026-11-05), shown in red; the install stops before any write.
FOREIGN_BACKUP_TEXT = (
    "Your game installation folder has an unrecognized {name} file. This should only happen if you "
    "edited that file by hand. Longevity Vaccine cannot install over it. To install, verify that you "
    "do not need {name} and delete it, then re-run this installer. Your game was not modified.")

#: The refusal for a Thinker folder the installer set up whose terranx.exe is now neither the file
#: the set-up put there nor the original it kept (user 2026-11-06: a Thinker player asked for
#: Thinker; installing the plain build instead is not an install). Same shape as the .bak refusal.
#: {was} is the original clause: ", and it is not the original that install kept" + " as <name>"
#: while that file is still there and unchanged (""), or " (there was no <name> before it)" for a
#: set-up that found none.
REPLACED_EXE_TEXT = (
    "Your game installation folder was set up for Thinker by an earlier Longevity Vaccine install, but "
    "its {name} is no longer the file that install put there{was}. This should only happen if you "
    "replaced that file by hand. Longevity Vaccine cannot install over it. To install, verify that you "
    "do not need the current {name} and delete it, then re-run this installer. Your game was not modified.")


def _refusal(text: str) -> "ix.InstallerError":
    """A refusal in the user's shape: red, the install stops before any write, the window waits
    for any key; no second disk line (the text itself says the game was not modified)."""
    return ix.InstallerError(text, code=ix.EXIT_ABORTED, changed=False, title="INSTALLATION FAILED",
                             red=True, disk_note=False, any_key=True)


def _foreign_backup(bak: Path) -> "ix.InstallerError":
    return _refusal(FOREIGN_BACKUP_TEXT.format(name=bak.name))


def _replaced_exe(game_dir: Path, exe: str, record: dict) -> "ix.InstallerError":
    kept = record.get("backup")
    if not kept:
        was = f" (there was no {exe} before it)"
    else:
        still = record.get("original_md5") and _md5_or_none(Path(game_dir) / kept) == record["original_md5"]
        was = ", and it is not the original that install kept" + (f" as {kept}" if still else "")
    return _refusal(REPLACED_EXE_TEXT.format(name=exe, was=was))


# ---------------------------------------------------------------- the backup rule
#
# ONE rule for every exe the patch pass writes (its bytes are a clean shipping base, so the pass
# backs it up under <exe>.bak -- and keeps whatever already sits under that name). What may sit
# there: nothing, or that clean base -- fine. GOG's original game exe (an old tool's backup) is
# set aside under an _original name, or dropped when the folder keeps that copy already; a build
# of ours is dropped (it is remade from the clean base at will, as patch_target does). Anything
# else is a file nobody can vouch for: the install stops before any write, in the user's words.
# Without this the pass patched over such a .bak and left a build no later run could recognise
# and no --uninstall could restore. plan_thinker_setup applies the rule to the exe Thinker starts
# (with the set-up's record); plan_backups applies it to every other exe the pass will patch.

def _backup_kind(bak_md5: str, base_md5: str) -> str:
    """What a <exe>.bak beside an exe of base `base_md5` is: "clean" (that base), "gog" (the stock
    original game exe), "ours" (a build this project made from that base: any release, any
    configuration), or "foreign"."""
    if bak_md5 == base_md5:
        return "clean"
    if bak_md5 in _stock_original_hashes():
        return "gog"
    if bak_md5 in ap.builds_on_base(_targets(), base_md5):
        return "ours"
    return "foreign"


def plan_backups(game_dir: Path, candidates: list, thinker_plan) -> list:
    """Decide what the install does about the <exe>.bak of every exe the pass will patch. Writes
    nothing; raises the refusal now, before any write. Returns the items apply_backup_plan carries
    out just before the pass: {"bak", "md5", "base_md5", "kind", "aside_to"} per spare .bak (GOG's
    copy moved to `aside_to`, or dropped when None; a build of ours dropped).

    The exe Thinker starts is the Thinker plan's business whenever there is one (it already applied
    this rule to it); after a set-up the pass patches only that exe, so nothing else is checked."""
    if thinker_plan and thinker_plan["action"] == "setup":
        return []
    game_dir = Path(game_dir)
    ov = _thinker_overlay()
    beside = ap.folder_files(game_dir)
    out = []
    for p in candidates:
        if thinker_plan and ov is not None and p.name.lower() == ov.exe.lower():
            continue
        md5 = _md5_or_none(p)
        if md5 is None:
            continue
        try:
            spec = ap.resolve_target(md5, targets=_targets(), launch_only=True, present_files=beside,
                                     exe_name=p.name)
        except ap.UnsupportedBase:
            continue                      # not a clean base: the pass does not back this exe up
        bak = p.with_suffix(p.suffix + ".bak")
        bak_md5 = _md5_or_none(bak)
        if bak_md5 is None:
            continue
        kind = _backup_kind(bak_md5, spec.base_md5)
        if kind == "clean":
            continue
        if kind == "foreign":
            raise _foreign_backup(bak)
        aside_to = None
        if kind == "gog":
            # ov is not None: the stock hashes come from it. A copy the folder keeps already --
            # the stock exe under its own name, or at the _original name -- makes this a duplicate.
            aside_to = _backup_name(game_dir, ov, bak_md5)
            if _md5_or_none(game_dir / ov.exe) == bak_md5 or _md5_or_none(aside_to) == bak_md5:
                aside_to = None
            elif aside_to.exists():
                # Both _original names taken by other files: said now, with nothing written, not
                # at apply after the questions.
                raise ix.InstallerError(
                    f"{bak.name} could not be moved out of the way.",
                    detail=f"  {aside_to.name} is already there and is a different file", code=ix.EXIT_ABORTED,
                    changed=False, remedy=f"move {bak.name} out of the game folder yourself, then run the installer again.")
        out.append({"bak": bak, "md5": bak_md5, "base_md5": spec.base_md5, "kind": kind,
                    "aside_to": aside_to})
    return out


def _backup_still_as_planned(bak: Path, md5: str, base_md5: str) -> bool:
    """At apply: is this planned .bak still what the plan saw? False when it is gone or the clean
    base is back under its name (nothing to do); raises the refusal for anything else -- a file
    swapped in since the plan is nobody's to vouch for."""
    now = _md5_or_none(bak)
    if now is None or now == base_md5:
        return False
    if now != md5:
        raise _foreign_backup(bak)
    return True


def recheck_planned_backups(plan: list, thinker_plan) -> None:
    """Before the first write of the install: every .bak the two plans will move or drop is hashed
    again, so a refusal for one swapped since the plan comes before ANY drop (a dropped duplicate
    cannot be undone, and the refusal's text says the game was not modified)."""
    for item in plan:
        _backup_still_as_planned(item["bak"], item["md5"], item["base_md5"])
    if thinker_plan and thinker_plan["action"] in ("aside", "setup"):
        ov = thinker_plan["ov"]
        for key, kind in (("gog_bak", "gog"), ("drop_bak", "ours")):
            bak = thinker_plan.get(key)
            if bak is not None:
                now = _md5_or_none(bak)
                if now is not None and now != ov.base_md5 and _backup_kind(now, ov.base_md5) != kind:
                    raise _foreign_backup(bak)


def apply_backup_plan(plan: list) -> list:
    """Carry plan_backups' plan out, just before the patch pass (recheck_planned_backups first, so
    a swapped .bak is refused before anything is dropped; the check here is the belt to that brace).
    Returns the moves made as [(aside_to, bak)], for undo_backup_moves should a later step fail
    before the pass. Fails with the moves undone when a file cannot be moved."""
    moves = []
    for item in plan:
        bak, aside_to = item["bak"], item["aside_to"]
        try:
            if not _backup_still_as_planned(bak, item["md5"], item["base_md5"]):
                continue
        except ix.InstallerError:
            undo_backup_moves(moves)
            raise
        now = item["md5"]
        try:
            if item["kind"] == "ours":
                bak.unlink()
                line = f"  {bak.name} (a Longevity Vaccine build) was removed; the installer writes a fresh backup"
            elif aside_to is None:
                bak.unlink()              # a spare copy of a file the folder keeps: without a word
                line = None
            elif _md5_or_none(aside_to) == now:
                bak.unlink()              # kept there since the plan (a second spare, say): a duplicate
                line = None
            else:
                if aside_to.exists():
                    raise OSError(f"{aside_to.name} is already there and is a different file")
                os.replace(bak, aside_to)
                moves.append((aside_to, bak))
                line = f"  {bak.name} (GOG's original) is kept as {aside_to.name} (delete it if you do not need it)"
        except OSError as e:
            undo_backup_moves(moves)
            raise ix.InstallerError(
                f"{bak.name} could not be moved out of the way.",
                detail=f"  {type(e).__name__}: {e}", code=ix.EXIT_ABORTED, changed=False,
                remedy=f"move {bak.name} out of the game folder yourself, then run the installer again.")
        if line:
            ix.say(f"\n--- {bak.name} ---")
            ix.say(line)
    return moves


def undo_backup_moves(moves: list) -> None:
    """Put set-aside backups back where they were (a later step failed before the pass)."""
    for aside_to, bak in reversed(moves):
        try:
            if not bak.exists():
                os.replace(aside_to, bak)
        except OSError:
            pass


def _aside_name_for(game_dir: Path, ov, gog_md5: str, taken: Path = None) -> Path:
    """Where GOG's spare copy goes: the _original name when free (or already that file), else a
    hashed one; never the name the set-up is giving the live file (`taken`)."""
    stem, suf = os.path.splitext(ov.exe)
    aside = _backup_name(game_dir, ov, gog_md5)
    if taken is not None and aside == taken:
        aside = game_dir / f"{stem}{THINKER_ORIGINAL_STEM}-{gog_md5[:8]}{suf}"
    return aside


def _set_gog_backup_aside(game_dir: Path, ov, gog_bak: Path, aside_to: Path, gog_md5: str) -> str:
    """Move GOG's spare terranx.exe.bak to `aside_to`, or drop it when `aside_to` already IS that
    file. Returns "moved" / "dropped". Re-checks the bytes first: a file swapped in since the plan
    is refused like any other foreign .bak (nothing written yet). Raises OSError on a clash."""
    now = _md5_or_none(gog_bak)
    if now != gog_md5 or now not in _stock_original_hashes():
        raise _foreign_backup(gog_bak)
    if aside_to.exists():
        if _md5_or_none(aside_to) == gog_md5:
            gog_bak.unlink()
            return "dropped"
        raise OSError(f"{aside_to.name} is already there and is a different file")
    os.replace(gog_bak, aside_to)
    return "moved"


def _drop_our_backup(bak: Path, ov) -> bool:
    """Drop a terranx.exe.bak that is a build of ours (planned so). Hashed again first: gone, or
    the clean base back under the name -> nothing to do; anything else -> refused like any other
    foreign .bak (swapped since the plan; nothing of ours written yet). True when dropped."""
    now = _md5_or_none(bak)
    if now is None or now == ov.base_md5:
        return False
    if _backup_kind(now, ov.base_md5) != "ours":
        raise _foreign_backup(bak)
    bak.unlink()
    ix.say(f"  {bak.name} (a Longevity Vaccine build) was removed; the installer writes a fresh backup")
    return True


def _keeps_record(game_dir: Path, record: dict, md5) -> bool:
    """GOG's stock exe written over a set-up whose recorded original is the player's own and still
    kept: the record keeps pointing at that TRUE original, and the stock copy is only set aside
    (named in the record, so the uninstall can say where it is). With the kept original gone, the
    stock exe simply becomes the original."""
    if not record or md5 is None or not record.get("original_md5") or md5 == record["original_md5"]:
        return False
    kept = record.get("backup")
    return bool(kept) and _md5_or_none(Path(game_dir) / kept) == record["original_md5"]


def apply_thinker_setup(plan) -> bool:
    """Carry out plan_thinker_setup's plan: True when the folder was set up. Fails with nothing
    changed when it cannot finish (disk space, a locked file)."""
    if not plan:
        return False
    game_dir = plan["game_dir"]
    if plan["action"] == "release":
        ix.say("\n--- Thinker ---")
        ix.say("  Thinker is no longer in this folder, which the installer had set up for it: the installer undoes that set-up (see below), and Longevity Vaccine is installed for PRACX without Thinker.")
        revert_thinker_setup(game_dir, remedy="close Alpha Centauri and Thinker if they are running, then run the installer again.")
        return False
    if plan["action"] == "aside":
        # terranx.exe is already PRACX; only a spare terranx.exe.bak is in the way of the patch
        # pass's own backup: a build of ours is dropped; GOG's copy is set aside (or a duplicate
        # dropped) and named; a record, when there is one, names it too for --uninstall.
        ov, gog_bak, record = plan["ov"], plan["gog_bak"], plan["record"]
        if plan.get("drop_bak") is not None:
            _drop_our_backup(plan["drop_bak"], ov)
        if gog_bak is None:
            return False
        gog_md5 = _md5_or_none(gog_bak)
        if gog_md5 is None:
            return False                              # gone since the plan: nothing to do
        aside_to = _aside_name_for(game_dir, ov, gog_md5)
        try:
            how = _set_gog_backup_aside(game_dir, ov, gog_bak, aside_to, gog_md5)
            if how == "moved" and record:
                _write_setup(game_dir, {**record, "set_aside": (record.get("set_aside") or []) + [aside_to.name]})
        except OSError as e:
            raise ix.InstallerError(
                f"{gog_bak.name} (GOG's original) could not be moved out of the way.",
                detail=f"  {type(e).__name__}: {e}", code=ix.EXIT_ABORTED, changed=False,
                remedy=f"move {gog_bak.name} out of the game folder yourself, then run the installer again.")
        ix.say(f"  the {gog_bak.name} that was here (GOG's original) is "
               + (f"kept as {aside_to.name}" if how == "moved" else f"a duplicate of {aside_to.name}: removed"))
        return False
    ov, live, src = plan["ov"], plan["live"], plan["src"]
    backup, md5, record = plan["backup"], plan["md5"], plan["record"]
    # The copy, then the patch pass: its .bak and its temporary build.
    need = 3 * src.stat().st_size + (1 << 20)
    try:
        free = shutil.disk_usage(game_dir).free
    except OSError:
        free = None
    if free is not None and free < need:
        raise ix.InstallerError(
            "There is not enough free disk space to set the folder up for Thinker.",
            detail=f"  {need >> 20} MB is needed on the game's drive; {free >> 20} MB is free.",
            code=ix.EXIT_ABORTED, changed=False,
            remedy="free some space on that drive and run the installer again.")

    tmp = game_dir / (ov.exe + _SETUP_TMP)
    # An identical copy of the original is already kept (GOG put it back after an earlier
    # set-up): the live file is a duplicate, so it is simply replaced -- never renamed over the
    # kept one, which a failure could then not undo.
    kept_already = backup is not None and _md5_or_none(backup) == md5
    # A terranx.exe.bak that is GOG's original (plan_thinker_setup accepted it): the set-up's own
    # backup needs that name (the patch pass writes it, and only when it is free). A duplicate of
    # the original being kept goes; anything else is set aside under an _original name and
    # recorded, so --uninstall names it. Done AFTER the live file is kept and BEFORE the copy
    # lands, so a failure undoes it along with the rest.
    gog_bak = plan.get("gog_bak")
    gog_md5 = _md5_or_none(gog_bak) if gog_bak is not None else None
    if gog_md5 is not None and gog_md5 not in _stock_original_hashes():
        raise _foreign_backup(gog_bak)                # swapped since the plan: nothing written yet
    # Where the spare goes, decided before the record is written: a duplicate of the live file
    # (kept as `backup` in a moment) or of a copy already at the _original name is dropped;
    # anything else is set aside and the record names it.
    aside_to = None
    if gog_md5 is not None and gog_md5 != md5:
        aside_to = _aside_name_for(game_dir, ov, gog_md5, taken=backup)
        if aside_to.exists() and _md5_or_none(aside_to) == gog_md5:
            aside_to = None                           # already kept there: the .bak is a duplicate
    extra_aside = [aside_to.name] if aside_to is not None else []
    moved = False
    dropped = False
    moved_aside = False
    dropped_ours = False
    try:
        # A build of ours under the name the pass needs for its backup: dropped first (the rule;
        # remade from the clean base by the pass that follows).
        if plan.get("drop_bak") is not None:
            dropped_ours = _drop_our_backup(plan["drop_bak"], ov)
        shutil.copy2(src, tmp)
        if _md5(tmp) != ov.base_md5:
            raise OSError(f"the copy of {src.name} does not match the original")
        if backup is not None:
            if plan.get("keep_record"):
                aside = [n for n in record.get("set_aside") or [] if n != backup.name]
                _write_setup(game_dir, {**record, "set_aside": aside + [backup.name] + extra_aside})
            else:
                _write_setup(game_dir, {"exe": ov.exe, "backup": backup.name, "original_md5": md5,
                                        "source": _plain_name(src),
                                        **({"set_aside": extra_aside} if extra_aside else {})})
            if not kept_already:
                os.replace(live, backup)
                moved = True
        elif not record.get("backup"):
            _write_setup(game_dir, {"exe": ov.exe, "backup": None, "original_md5": None,
                                    "source": _plain_name(src),
                                    **({"set_aside": extra_aside} if extra_aside else {})})
        elif extra_aside:
            # A set-up that stopped between its two steps keeps its record; the spare it sets
            # aside now is named in it too, or --uninstall could never name it.
            _write_setup(game_dir, {**record, "set_aside": (record.get("set_aside") or []) + extra_aside})
        if gog_md5 is not None and gog_bak.is_file():
            if aside_to is None:
                if _md5_or_none(gog_bak) != gog_md5:
                    raise _foreign_backup(gog_bak)    # swapped since the plan
                gog_bak.unlink()                      # a duplicate of a copy that is kept
                dropped = True
            else:
                moved_aside = _set_gog_backup_aside(game_dir, ov, gog_bak, aside_to, gog_md5) == "moved"
        os.replace(tmp, live)
        plan["applied"] = True        # the folder IS set up from here: _install keeps a first Thinker install with it
    except ix.InstallerError:
        # The foreign-backup refusal, raised with nothing of ours left behind: the copy, and a
        # record that only this run wrote, go first.
        for p in (tmp,) + ((game_dir / THINKER_SETUP_NAME,) if not record else ()):
            try:
                p.unlink()
            except OSError:
                pass
        if record:
            try:
                _write_setup(game_dir, record)
            except OSError:
                pass
        try:
            if moved and not live.exists():
                os.replace(backup, live)
        except OSError:
            pass
        raise
    except (OSError, KeyboardInterrupt) as e:
        # Undo in reverse: nothing half-done is left behind -- Ctrl-C included (verification 2026-11-15: a Ctrl-C
        # between the two renames left no terranx.exe and a 4 MB terranx.exe.longevity-tmp).
        try:
            if moved_aside and not gog_bak.exists():
                os.replace(aside_to, gog_bak)
                moved_aside = False
        except OSError:
            pass
        try:
            if moved and not live.exists():
                os.replace(backup, live)
                moved = False
        except OSError:
            pass
        for p in (tmp,) + ((game_dir / THINKER_SETUP_NAME,) if not moved and not record else ()):
            try:
                p.unlink()
            except OSError:
                pass
        if record and not moved:
            try:
                _write_setup(game_dir, record)          # the record as it was before this run
            except OSError:
                pass
        if isinstance(e, KeyboardInterrupt):
            raise                                       # rolled back: the run stops as Ctrl-C stops it anywhere
        detail = f"  {type(e).__name__}: {e}"
        if dropped:
            detail += (f"\n  {gog_bak.name} (a spare copy of GOG's original) was removed; the original is still "
                       f"{backup.name if backup is not None and backup.exists() else ov.exe}.")
        if dropped_ours:
            detail += f"\n  {plan['drop_bak'].name} (a Longevity Vaccine build) was removed."
        raise ix.InstallerError(
            "The folder could not be set up for Thinker.",
            detail=detail,
            code=ix.EXIT_ABORTED,
            changed=None if (moved or moved_aside) else (True if (dropped or dropped_ours) else False),
            remedy="close Alpha Centauri and Thinker if they are running, then run the installer again.")
    # One line, the user's wording (2026-11-06); the shapes that differ from it say so.
    ix.say("\n--- Thinker ---")
    if md5 is None:
        kept = record.get("backup")
        kept_intact = bool(kept) and record.get("original_md5") \
            and _md5_or_none(game_dir / kept) == record["original_md5"]
        ix.say(f"  Put the PRACX .exe in place as {ov.exe}. This is required to load both Longevity and Thinker. "
               + (f"Your original is kept as {kept}. Uninstalling Longevity Vaccine puts it back." if kept_intact
                  else "Uninstalling Longevity Vaccine removes it again." if not kept
                  # the kept original gone or changed since: undo leaves the PRACX copy and says so (state 5)
                  else f"Uninstalling Longevity Vaccine undoes this where it can ({kept}, the original it kept, "
                       f"{'is no longer in the folder' if not (game_dir / kept).is_file() else 'has changed since it was kept'})."))
    elif plan.get("keep_record"):
        ix.say(f"  Swapped the vanilla Alien Crossfire .exe for the PRACX .exe. This is required to load both Longevity "
               f"and Thinker. Your earlier {ov.exe} is still kept as {record['backup']}, and GOG's copy as "
               f"{backup.name}. Uninstalling Longevity Vaccine puts your earlier {ov.exe} back.")
    else:
        what = "the vanilla Alien Crossfire .exe" if plan.get("vanilla") else f"the {ov.exe} that was here"
        ix.say(f"  Swapped {what} for the PRACX .exe. This is required to load both Longevity and Thinker. "
               f"Your original is kept as {backup.name}. Uninstalling Longevity Vaccine puts it back.")
    if moved_aside:
        ix.say(f"  The {ov.exe}.bak that was here (GOG's original) is kept as {aside_to.name}.")
    # An earlier plain install's patched terranx_PRACX.exe: back to clean, so no second patched
    # copy is left to go stale (see the section comment). Ours by its hash; nothing else touched.
    if src.name.lower().endswith(".bak"):
        other = src.with_name(_plain_name(src))
        if _md5_or_none(other) in _our_builds(ov):
            # Through a temporary file and one rename: a Ctrl-C mid-copy leaves the old build whole, never half a file
            # (verification 2026-11-15).
            tmp_other = other.with_name(other.name + _SETUP_TMP)
            try:
                shutil.copy2(src, tmp_other)
                os.replace(tmp_other, other)
                ix.say(f"  {other.name} is back to the clean PRACX build (Thinker players start thinker.exe)")
            except BaseException as e:
                try:
                    tmp_other.unlink()
                except OSError:
                    pass
                if not isinstance(e, OSError):
                    raise
                ix.warn(f"  {other.name} could not be put back to the clean PRACX build ({e}); it keeps an older build of Longevity Vaccine.")
    return True


def thinker_setup_folder(game_dir: Path) -> bool:
    """Was this folder set up for Thinker by the installer (its record is there)?"""
    return (Path(game_dir) / THINKER_SETUP_NAME).is_file()


def revert_thinker_setup(game_dir: Path, held: list = None, remedy: str = None,
                         title: str = None) -> int:
    """Put a folder the installer set up for Thinker back the way it was (--uninstall, and a
    set-up that will not be redone): our build of terranx.exe back to the clean PRACX copy, then
    undo_thinker_setup. Returns the number of files put back; `held` collects the exe it had to
    leave as it is (the uninstall's generic restore must not touch it either).

    The clean copy comes from terranx.exe.bak when that is the clean base; for a build the table
    records (any release's, by its hash), also from the folder's other clean PRACX copy when the
    .bak is gone. A build known only by its place (one the table does not record) needs the .bak:
    without it nothing proves the file is ours, and undo leaves it."""
    game_dir = Path(game_dir)
    rec = _read_setup(game_dir)
    ov = _thinker_overlay()
    if not rec or ov is None:
        return 0
    exe = rec.get("exe") or ov.exe
    live, bak = game_dir / exe, game_dir / (exe + ".bak")
    live_md5 = _md5_or_none(live)
    n = 0
    kept = False
    clean = None
    if live_md5 not in (None, ov.base_md5) and _ours_in_setup(game_dir, ov):
        if _md5_or_none(bak) == ov.base_md5:
            clean = bak
        elif live_md5 in _our_builds(ov):
            clean = _pracx_source(game_dir, ov)
    if clean is not None:
        try:
            if live_md5 not in _our_builds(ov):
                # A build the table does not record, recognised by its place, not its hash: keep
                # the bytes beside, named by their hash, as patch_target does -- never destroy them.
                keep = live.with_name(f"{live.name}.replaced-{live_md5[:8]}")
                if not keep.exists():
                    shutil.copy2(live, keep)
                    kept = True
                    ix.say(f"  the replaced {exe} is kept as {keep.name} (delete it if you do not need it)")
            shutil.copy2(clean, live)
            n += 1
        except OSError as e:
            raise ix.InstallerError(
                f"Could not restore {exe} from its backup.", detail=f"  {e}", changed=kept, title=title,
                remedy=remedy or "close the game and Thinker if they are running and try again.")
    put_back = undo_thinker_setup(game_dir, held, changed=bool(n), remedy=remedy, title=title)
    if n and not put_back:
        ix.say(f"  restored {exe} from {clean.name}")
    return put_back or n


def _free_pracx_name(game_dir: Path, rec: dict, ov) -> Path:
    """Where the folder's only PRACX copy goes when it is not to stay as the overlay's exe: the
    name it was copied from, else a numbered one beside it."""
    first = game_dir / (rec.get("source") or "terranx_PRACX.exe")
    if not first.exists():
        return first
    stem, suf = os.path.splitext(first.name)
    i = 2
    while (game_dir / f"{stem} ({i}){suf}").exists():
        i += 1
    return game_dir / f"{stem} ({i}){suf}"


def undo_thinker_setup(game_dir: Path, held: list = None, changed: bool = False,
                       remedy: str = None, title: str = None) -> int:
    """Put the original terranx.exe back where the installer set the folder up for Thinker, from
    whatever state the folder is in now. Returns the number of files put back. Never destroys a
    PRACX build the folder has no other copy of, nor a file it did not put there. Where it has to
    leave the exe as it is, it says where the original is and appends the exe to `held`.

    The states, in order (live = terranx.exe now, kept = the original the set-up kept):
      1. live is the recorded original                -> in place; a duplicate kept copy goes.
      2. live is GOG's stock exe and the kept original is still there and is something else (the
         player's own) -> the stock copy is set aside, the kept original goes back.
      3. live is GOG's stock exe otherwise            -> it is the original now; in place.
      4. live is not the clean PRACX copy             -> left as it is, said so, held.
      5. the kept original changed / is gone          -> live stays (clean PRACX or none), said so.
      6. otherwise (live is the clean copy, or none)  -> the kept original goes back (or our copy
         goes, when there was none before), the only PRACX copy kept under a plain name.

    Two things always hold afterwards, so no later run acts on a stale picture: the record is gone
    (once undone or explained it describes nothing left to do; keeping it would make the folder
    read as installed for good), and our clean-PRACX terranx.exe.bak is gone too -- deleted when
    the folder has another PRACX copy or live is the base, else renamed to a plain PRACX exe --
    because a .bak of ours beside some other terranx.exe is exactly what the uninstall's generic
    restore copies over it. Files the set-up set aside are named."""
    game_dir = Path(game_dir)
    rec = _read_setup(game_dir)
    ov = _thinker_overlay()
    if not rec or ov is None:
        return 0
    exe = rec.get("exe") or ov.exe
    live, bak = game_dir / exe, game_dir / (exe + ".bak")
    back = (game_dir / rec["backup"]) if rec.get("backup") else None
    original = rec.get("original_md5")
    put_back = 0
    left = None
    gog = "GOG Galaxy's \"verify files\" restores the original"
    try:
        live_md5 = _md5_or_none(live)
        back_md5 = _md5_or_none(back) if back is not None else None
        stock = live_md5 is not None and live_md5 in _stock_original_hashes()
        still = f"; the original is still {back.name}." if back_md5 is not None else "."
        now = (f"{exe} stays a clean PRACX copy" if live_md5 == ov.base_md5
               else f"there is no {exe} in the folder now")
        aside_names = [n for n in rec.get("set_aside") or [] if (game_dir / n).is_file()]
        stock_aside = next((game_dir / n for n in aside_names
                            if _md5_or_none(game_dir / n) in _stock_original_hashes()), None)
        if live_md5 is not None and original and live_md5 == original:                       # 1
            if back is not None and back_md5 == live_md5:
                back.unlink()                         # a duplicate of the file now in place
                changed = True
        elif stock and original and back_md5 == original:                                    # 2
            aside = live.with_name(f"{live.name}.replaced-{live_md5[:8]}")
            same = [game_dir / n for n in aside_names if _md5_or_none(game_dir / n) == live_md5]
            if same:
                aside = same[0]
                live.unlink()                         # the same copy is already set aside
            elif aside.exists() and _md5_or_none(aside) == live_md5:
                live.unlink()                         # the same copy is already set aside
            else:
                i = 2
                while aside.exists():
                    aside = live.with_name(f"{live.name}.replaced-{live_md5[:8]}-{i}")
                    i += 1
                os.replace(live, aside)
            changed = True
            if not same:                              # a set-aside copy is named below
                ix.say(f"  GOG's copy of {exe} is kept as {aside.name} (delete it if you do not need it)")
            os.replace(back, live)
            ix.say(f"  put your earlier {exe} back (from {back.name})")
            put_back += 1
        elif stock:                                                                           # 3
            if back is not None and back_md5 == live_md5:
                back.unlink()
                changed = True
            elif back_md5 is not None:
                ix.say(f"  your earlier {exe} is still kept as {back.name}")
        elif live_md5 is not None and live_md5 != ov.base_md5:                               # 4
            left = f"  {exe} is not the PRACX copy the installer put there, so it was left as it is" + still
        elif ((back_md5 is not None and original and back_md5 != original)
              or (back is not None and back_md5 is None)) and stock_aside:                   # 5, GOG's copy at hand
            if live_md5 is not None and _pracx_source(game_dir, ov) is None \
                    and _md5_or_none(bak) != ov.base_md5:
                keep = _free_pracx_name(game_dir, rec, ov)
                os.replace(live, keep)
                ix.say(f"  {exe} was the folder's only PRACX copy: kept as {keep.name}")
            os.replace(stock_aside, live)
            changed = True
            ix.say(f"  the kept original is {'gone' if back_md5 is None else 'changed'}: put GOG's copy of {exe} back (from {stock_aside.name})")
            put_back += 1
        elif back_md5 is not None and original and back_md5 != original:                    # 5
            ix.warn(f"  {back.name} has changed since the installer kept it, so it was not put back as {exe}: {now}, and {gog}.")
        elif back is not None and back_md5 is None:
            ix.warn(f"  The original {exe} the installer kept ({back.name}) is no longer in the folder: {now}, and {gog}.")
        else:                                                                                 # 6
            if live_md5 is not None and _pracx_source(game_dir, ov) is None \
                    and _md5_or_none(bak) != ov.base_md5:
                # The folder's only PRACX build: keep it under the name it was copied from.
                keep = _free_pracx_name(game_dir, rec, ov)
                os.replace(live, keep)
                changed = True
                ix.say(f"  {exe} was the folder's only PRACX copy: kept as {keep.name}")
                live_md5 = None
            if back_md5 is not None:
                os.replace(back, live)
                changed = True
                ix.say(f"  put the original {exe} back (from {back.name})")
                put_back += 1
            elif back is None and live_md5 is not None:
                live.unlink()
                changed = True
                ix.say(f"  removed the {exe} the installer had put there (there was none before)")
                put_back += 1
        if left is not None:
            ix.warn(left)
            if held is not None:
                held.append(exe)
        if _md5_or_none(bak) == ov.base_md5:
            if _pracx_source(game_dir, ov) is not None or _md5_or_none(live) == ov.base_md5:
                bak.unlink()                          # nobody's backup any more
            else:
                keep = _free_pracx_name(game_dir, rec, ov)
                os.replace(bak, keep)                 # the folder's only PRACX copy: kept
                ix.say(f"  the folder's only PRACX copy is kept as {keep.name}")
            changed = True
        for name in rec.get("set_aside") or []:
            if (game_dir / name).is_file() and name != (back.name if back is not None else None):
                ix.say(f"  GOG's copy of {exe} that the installer set aside is kept as {name} (delete it if you do not need it)")
        for p in (game_dir / (exe + _SETUP_TMP), game_dir / (THINKER_SETUP_NAME + ".tmp"),
                  game_dir / THINKER_SETUP_NAME):
            if p.exists():
                p.unlink()
    except OSError as e:
        raise ix.InstallerError(
            f"Could not put the original {exe} back.", detail=f"  {e}", changed=bool(changed), title=title,
            remedy=remedy or "close the game and Thinker if they are running and run --uninstall again.")
    return put_back


def thinker_undo_plan(game_dir: Path) -> tuple:
    """What revert_thinker_setup (and the undo_thinker_setup it calls) would change in this folder as it is now,
    without changing it. Returns ([(path, modes)], held), `modes` one or more of preflight.PROBE_MODES joined by
    "+", each the call the step makes on that file: "overwrite" = the revert's copy2 onto the exe; "source" = copied
    from (the revert's clean copy, or the unrecorded build it keeps beside); "delete"; "rename" = moved to a free
    name; "replace" = a name another file is moved onto -- and a deleted name another file then takes (on a volume
    or Windows without POSIX deletes, a program still holding the deleted file keeps its name taken). Each file's
    reads (its md5) are listed by uninstall_targets. `held` is True when the undo leaves the exe to the player
    (the generic restore then skips it). Mirrors the two functions branch by branch; keep the three together.
    test_install_e2e's property test holds them to it: for each set-up state and each read-only or running file,
    the uninstall's check refuses exactly when the run would fail part-way or leave something undone (audits
    2026-11-15: a coarse "rename for everything but the exe" let a read-only terranx.exe.bak through; treating the
    copy source as taken let a read-only terranx_PRACX.exe through)."""
    game_dir = Path(game_dir)
    rec = _read_setup(game_dir)
    ov = _thinker_overlay()
    if not rec or ov is None:
        return [], False
    plan = {}

    def put(p, mode: str) -> None:
        if p is None or not os.path.lexists(p):
            return
        plan[p] = plan.get(p, set()) | set(mode.split("+"))

    exe = rec.get("exe") or ov.exe
    live, bak = game_dir / exe, game_dir / (exe + ".bak")
    live_md5 = _md5_or_none(live)
    bak_md5 = _md5_or_none(bak)
    # revert_thinker_setup: a build of ours goes back to the clean copy (copy2 carries the clean file's read-only
    # flag onto the exe, which the undo below then moves or deletes: a read-only clean file fails too).
    if live_md5 not in (None, ov.base_md5) and _ours_in_setup(game_dir, ov):
        clean = bak if bak_md5 == ov.base_md5 else (_pracx_source(game_dir, ov) if live_md5 in _our_builds(ov)
                                                    else None)
        if clean is not None:
            put(live, "overwrite")                      # copy2 onto it
            put(clean, "source")
            if live_md5 not in _our_builds(ov) and not live.with_name(f"{live.name}.replaced-{live_md5[:8]}").exists():
                put(live, "source")                     # an unrecorded build: copied beside first
            live_md5 = ov.base_md5
    # undo_thinker_setup, case by case (its comments number them)
    back = (game_dir / rec["backup"]) if rec.get("backup") else None
    original = rec.get("original_md5")
    back_md5 = _md5_or_none(back) if back is not None else None
    stock = live_md5 is not None and live_md5 in _stock_original_hashes()
    aside_names = [n for n in rec.get("set_aside") or [] if (game_dir / n).is_file()]
    stock_aside = next((game_dir / n for n in aside_names
                        if _md5_or_none(game_dir / n) in _stock_original_hashes()), None)
    held = False
    moved = False
    final = live_md5                                    # the exe's hash once the case is done
    if live_md5 is not None and original and live_md5 == original:                           # 1
        if back is not None and back_md5 == live_md5:
            put(back, "delete")
    elif stock and original and back_md5 == original:                                        # 2
        aside = live.with_name(f"{live.name}.replaced-{live_md5[:8]}")
        same = [n for n in aside_names if _md5_or_none(game_dir / n) == live_md5]
        if not same:
            put(aside, "read")                          # hashed: the same copy already set aside? (audit F4)
        put(live, "replace" if (same or (aside.exists() and _md5_or_none(aside) == live_md5)) else "rename")
        put(back, "rename")                             # onto the exe's name, freed just before
        final = back_md5
    elif stock:                                                                               # 3
        if back is not None and back_md5 == live_md5:
            put(back, "delete")
    elif live_md5 is not None and live_md5 != ov.base_md5:                                   # 4
        held = True
    elif ((back_md5 is not None and original and back_md5 != original)
          or (back is not None and back_md5 is None)) and stock_aside:                       # 5
        moved = live_md5 is not None and _pracx_source(game_dir, ov) is None and bak_md5 != ov.base_md5
        put(live, "rename" if moved else "replace")     # moved away, or GOG's copy is moved onto it
        put(stock_aside, "rename")
        final = _md5_or_none(stock_aside)
    elif back_md5 is not None and original and back_md5 != original:                        # 5, said only
        pass
    elif back is not None and back_md5 is None:
        pass
    else:                                                                                     # 6
        moved = live_md5 is not None and _pracx_source(game_dir, ov) is None and bak_md5 != ov.base_md5
        if moved:
            put(live, "rename")
            final = None
        if back_md5 is not None:
            put(back, "rename")
            if final is not None:
                put(live, "replace")                    # the original is moved onto it
            final = back_md5
        elif back is None and final is not None:
            put(live, "delete")                         # deleted: there was none before
            final = None
    # our clean-PRACX .bak: deleted, or kept under a plain name when it is the folder's only PRACX copy (a copy the
    # case moved under such a name may become the folder's PRACX source first: both are checked then)
    if bak_md5 == ov.base_md5:
        deleted = moved or _pracx_source(game_dir, ov) is not None or final == ov.base_md5
        put(bak, "delete+rename" if moved else ("delete" if deleted else "rename"))
    for p in (game_dir / (exe + _SETUP_TMP), game_dir / (THINKER_SETUP_NAME + ".tmp"), game_dir / THINKER_SETUP_NAME):
        put(p, "delete")
    return [(p, "+".join(sorted(m))) for p, m in plan.items()], held


def patch_target(target: Path, force: bool) -> str:
    """Patch one exe according to its MD5, via the patches.yaml target table.

    Resolution is `resolve_target(md5, launch_only=True)`: a base that is not a SHIPPING target is
    refused even if the patcher technically knows how to patch it. That is what enforces the
    "vanilla is no longer a supported configuration" decision -- before this, the table recorded
    the decision and the installer ignored it, happily patching the dropped base and reporting
    success.
    """
    md5 = _md5_safe(target)
    beside = ap.folder_files(target.parent)   # thinker.dll beside the exe selects the overlay

    try:
        spec = ap.resolve_target(md5, targets=_targets(), launch_only=True, present_files=beside,
                                 exe_name=target.name)
    except ap.UnsupportedBase:
        # Not a supported clean base. If its backup IS one, this exe is already patched.
        bak = target.with_suffix(target.suffix + ".bak")
        if bak.exists():
            try:
                bak_spec = ap.resolve_target(_md5_safe(bak), targets=_targets(), launch_only=True,
                                             present_files=beside, exe_name=target.name)
            except ap.UnsupportedBase:
                bak_spec = None
            if bak_spec is not None:
                ix.say(f"\n--- {target.name} ---")
                # The .bak says WHICH base; the live bytes say which BUILD. The folder may have
                # changed since that build was made (Thinker added or removed beside it), and the
                # two configurations share one base: a build for the other one is not "already
                # patched", it is the wrong build -- Thinker's own launch guard refuses the plain
                # PRACX build, and the plain configuration runs the Thinker build without the DLL
                # pass that completes it (audit 2026-10-28). Re-patch from the backup.
                current = bak_spec.patched_md5 is None or md5 == bak_spec.patched_md5
                if not force and current:
                    ix.say("  already patched (backup is a supported clean base): skipping."
                           " Use --force to re-patch.")
                    _patch_log_line(f"{target.name}: already patched (MD5 {md5}; .bak is the clean base "
                                    f"{bak_spec.base_md5}, target {bak_spec.id!r})")
                    return "already-patched"
                if not current:
                    ix.say(f"  not the build this installer produces for this folder (a different configuration, or an "
                           f"older build) -> restoring from .bak, then re-patching as {bak_spec.label}...")
                    # Those live bytes may be a player's own edit or another tool's work on top of ours:
                    # never destroy them (audit 2026-10-29) -- keep them beside, named by their hash.
                    # A build this project made (any release, any configuration of this base) is
                    # ours to replace: re-made from the backup at will, so no copy is kept.
                    keep = target.with_name(f"{target.name}.replaced-{md5[:8]}")
                    ours = ap.builds_on_base(_targets(), bak_spec.base_md5)
                    if md5 not in ours and not keep.exists():
                        try:
                            shutil.copy2(target, keep)
                            ix.say(f"  the replaced file is kept as {keep.name} (delete it if you do not need it)")
                        except OSError as e:
                            ix.say(f"  WARNING: could not keep a copy of the replaced file ({e}); nothing restored.")
                            return "error"
                else:
                    ix.say("  --force: restoring from .bak, then re-patching...")
                if ap.restore(target) != 0:
                    return "error"
                return patch_target(target, force=False)
        # Some other executable in the folder (the stock terranx.exe beside terranx_PRACX.exe,
        # most often). Not a candidate, not worth a line: "not a supported configuration"
        # printed for a file the player never asked about only read as a fault (user, 2026-09-27).
        return "unknown"

    ix.say(f"\n--- {target.name} ---")
    if spec.requires_files:
        ix.say(f"  {', '.join(spec.requires_files)} found beside it -> {spec.label} configuration")
    # (No "run the installer again and let it set the folder up" note here any more: the set-up
    # happens before this pass, unasked, whenever a clean PRACX source exists, so the only Thinker
    # folder that reaches a plain build has no clean PRACX copy to set up from.)
    ix.say(f"  patching (clean {spec.label})")
    _patch_log_line(f"{target.name}: target {spec.id!r} ({spec.label}), clean base {md5}, "
                    f"expected result {spec.patched_md5 or '(unrecorded)'}")
    # Pass the spec, not loose hashes: the baseline, size and group selection all come from the
    # one table entry, and the installer inherits its dry-run-only rule -- a base with no
    # recorded patched_md5 can never be written to, even if someone adds it to the launch set.
    # `summary`: one coloured line per phase instead of the patcher's 3,000-line transcript.
    rc = ap.apply_patches(target, Path(ap.DEFAULT_PATCHES), do_apply=True, spec=spec,
                          summary=_patch_summary)
    if rc == 2:
        # A refusal, not a failure: the target is declared but not ready to be written to (no
        # recorded lock, no measured baseline). "A patch step failed -- re-run the installer"
        # would be the wrong thing to tell the user, because re-running cannot help.
        return "unsupported"
    if rc == 4:
        ix.bad("  ERROR: the patched result does not match this release's recorded lock; nothing "
               "was written.")
        return "error"
    if rc != 0:
        return "error"
    if spec.patched_md5:
        got = _md5_safe(target, changed=True)
        if got != spec.patched_md5:
            ix.bad(f"  ERROR: patched MD5 {got} != expected {spec.patched_md5}")
            return "error"
    return "patched"


_PATCH_LOG = None   # the open fresh-install patch log while fresh_patch_log() is active; _patch_summary tees into it


def _patch_log_line(text: str) -> None:
    """One line into the fresh-install patch log, if one is open. Never raises."""
    if _PATCH_LOG is None:
        return
    try:
        _PATCH_LOG.write(ix.redact_profile(text) + "\n")     # the log goes into public bug reports
        _PATCH_LOG.flush()
    except (OSError, ValueError):
        pass


def _patch_summary(status: str, text: str) -> None:
    """apply_patches' per-phase report line, coloured: green SUCCESS, red ERROR, plain otherwise -- and
    recorded in the fresh-install patch log (fresh_patch_log) as `[status] text`."""
    if status == "ok":
        ix.good("  " + text)
    elif status == "error":
        ix.bad("  " + text)
    else:
        ix.say("  " + text)
    _patch_log_line(f"[{status}] {text}")


def check_companion_declarations() -> None:
    """Refuse a patch set whose companion entries are incomplete, BEFORE anything is written.

    Raised early on purpose: a companion is only patched after the exe, so discovering the
    problem there would mean aborting with the exe already modified.
    """
    bad = []
    for t in _targets().values():
        if not t.launch:
            continue
        for fname, cinfo in (t.companion or {}).items():
            if not isinstance(cinfo, dict):
                bad.append(f"{t.id}:{fname} (not a table)")
                continue
            missing = [k for k in ("patches", "base_md5", "base_size")
                       if cinfo.get(k) in (None, "")]
            # ALSO check the patch file is actually in the payload. companion_specs() skips a
            # missing one silently, which reproduces the original defect -- shipped but never
            # applied -- with no diagnostics at all.
            if cinfo.get("patches") and not (
                    Path(ap.DEFAULT_PATCHES).parent / cinfo["patches"]).is_file():
                missing.append(f"the file {cinfo['patches']}")
            # base_size must come from the TABLE, never from the live file. The live prax.dll may
            # already be patched (or be some other build entirely), and feeding its size in as
            # "the size the clean base should have" made the check compare the .bak against the
            # patched file's length -- so the companion aborted on every second update, and on a
            # foreign prax.dll the check was simply vacuous.
            if missing:
                bad.append(f"{t.id}:{fname} (no {', '.join(missing)})")
    if bad:
        raise ix.InstallerError(
            "The installer's patch data is incomplete.",
            code=ix.EXIT_ABORTED, changed=False,
            detail="  incomplete companion entries: " + "; ".join(bad),
            remedy="download the installer again; if it keeps happening, report this.")


def companion_specs(game_dir: Path, spec) -> list:
    """[(live_path, patches_path, TargetSpec)] for each companion of `spec` present on disk."""
    out = []
    for fname, cinfo in (spec.companion or {}).items():
        live = Path(game_dir) / fname
        cpatch = Path(ap.DEFAULT_PATCHES).parent / (cinfo.get("patches") or "")
        if not (live.is_file() and cpatch.is_file()):
            continue
        out.append((live, cpatch, ap.TargetSpec(f"{spec.id}:{fname}", {
            "label": f"{spec.label} companion {fname}", "exe": fname, "launch": spec.launch,
            "base_md5": cinfo.get("base_md5"), "base_size": cinfo.get("base_size"),
            "groups": "all", "patched_md5": cinfo.get("patched_md5")})))
    return out


#: What a companion binary on disk turns out to be.
C_CLEAN, C_PATCHED, C_STALE, C_FOREIGN = "clean", "patched", "stale", "foreign"


def _known_patched(spec, fname: str) -> set:
    """Every MD5 this project has ever produced for `fname`.

    Needed to tell OUR older output from somebody else's file. Without it, a companion patched by
    a previous release matches neither `base_md5` nor the current `patched_md5`, so it was
    written off as foreign and left stale beside a freshly-patched exe -- exactly the drift
    `patch_companions` exists to prevent. `known_patched:` in patches.yaml is the append-only
    history; the current lock is always a member.
    """
    cinfo = (spec.companion or {}).get(fname) or {}
    out = {str(m).lower() for m in (cinfo.get("known_patched") or []) if m}
    if cinfo.get("patched_md5"):
        out.add(str(cinfo["patched_md5"]).lower())
    return out


def companion_state(live: Path, cspec, known: set, changed=False) -> tuple:
    """(state, md5) for a companion binary on disk.

    `changed` is threaded through to _md5_safe: this runs BEFORE any write on the update path
    and AFTER the exe has been patched on the fresh path, and an unreadable file must not be
    reported as "nothing was changed" in the second case.
    """
    md5 = _md5_safe(live, changed=changed)
    if md5 == cspec.base_md5:
        return C_CLEAN, md5
    if cspec.patched_md5 and md5 == cspec.patched_md5:
        return C_PATCHED, md5
    if md5 in known:
        return C_STALE, md5
    return C_FOREIGN, md5


def _verified_backup(live: Path, cspec, changed=False):
    """The companion's .bak, but ONLY when it really is the clean base. Else None.

    `ap.restore()` is an unconditional copy, so calling it on an unverified backup overwrites a
    good file with whatever happens to sit in the .bak -- and for a companion there is no second
    copy anywhere. The exe path has always verified this; the companion path did not.
    """
    bak = live.with_suffix(live.suffix + ".bak")
    if bak.is_file() and _md5_safe(bak, changed=changed) == cspec.base_md5:
        return bak
    return None


def patch_companions(game_dir: Path, spec, force: bool) -> dict:
    """Patch the target's companion binaries (prax.dll on the PRACX targets).

    Returns {file name: "ok" | "skip" | "error"} for the summary table.

    Without this a FRESH install patched only the exe. patches_prax.yaml -- the PRACX
    bottom/left/right edge-scroll console-exemption fix -- shipped in the payload and was never
    applied, and because the exe was already-patched afterwards, nothing brought the companion up
    to date later either: only the --update path ever looked at `companion:`.

    A companion failure is never fatal. The mod is complete without it; only the PRACX-specific
    click fix is missed, and saying so is better than refusing an install that would work.
    """
    out = {}
    for live, cpatch, cspec in companion_specs(game_dir, spec):
        ix.say(f"\n--- {live.name} ---")
        out[live.name] = "skip"
        # changed=True throughout: the exe was patched before this function was called.
        state, md5 = companion_state(live, cspec, _known_patched(spec, live.name), changed=True)

        if state == C_PATCHED and not force:
            ix.say("  already patched: skipping. Use --force to re-patch.")
            out[live.name] = "ok"
            continue
        if state == C_FOREIGN:
            # Someone else's build -- a newer PRACX, most likely. Restoring OUR backup over it
            # would silently downgrade their install, so never touch it.
            ix.say(f"  MD5 {md5} is not a build this patch set knows, so it is left alone.")
            ix.say("  (Longevity Vaccine works without it; only the PRACX edge-scroll fix is missed)")
            continue
        if state != C_CLEAN:
            bak = _verified_backup(live, cspec, changed=True)
            if bak is None:
                ix.say(f"  {live.name} is patched but its backup is missing or is not the "
                       f"original, so it is left alone.")
                ix.say("  (Longevity Vaccine works without it; only the PRACX edge-scroll fix is missed)")
                continue
            ix.say(f"  restoring from the verified {bak.name}, then patching...")
            if ap.restore(live) != 0:
                ix.warn("  WARNING: could not restore it from .bak; leaving it alone.")
                continue
            if _md5_safe(live, changed=True) != cspec.base_md5:
                ix.warn("  WARNING: the restored file is not the clean base; leaving it alone.")
                continue

        _patch_log_line(f"{live.name}: target {cspec.id!r} ({cspec.label}), clean base {cspec.base_md5}, "
                        f"expected result {cspec.patched_md5 or '(unrecorded)'}")
        if ap.apply_patches(live, cpatch, do_apply=True, spec=cspec, summary=_patch_summary) != 0:
            ix.warn(f"  WARNING: patching {live.name} failed; Longevity Vaccine still works without it.")
            out[live.name] = "error"
            continue
        got = _md5_safe(live, changed=True)
        if cspec.patched_md5 and got != cspec.patched_md5:
            ix.bad(f"  ERROR: patched MD5 {got} != expected {cspec.patched_md5}")
            out[live.name] = "error"
            continue
        out[live.name] = "ok"
    return out


#: Thinker's build: what the folder has, and the installer's question about it, are thinker_state /
#: thinker_flow (thinker-updater-design.md); the game's own startup dialog is uimod thinkerversion.cpp.


#: The Datalinks text: helpx.txt's cloaking / submarine detection rules and conceptsx.txt's Waypoints paragraph
#: (scripts/patch_helptext.py, shipped in the base payload). Applied on every install and update run, to the game
#: folder and to Thinker's smac_mod\ copies when present; undone by --uninstall. Documentation only: a file that is
#: not the stock text (another mod's, a translation) is left alone and said so, and a missing file is skipped --
#: never a reason to fail an install that works.
def patch_datalinks_text(game_dir: Path) -> dict:
    """Returns {relative file name: patch_helptext status} for the summary; {} when nothing was found."""
    try:
        import patch_helptext as ph
    except Exception as e:  # noqa: BLE001 - a mistrimmed payload is the same user-facing problem whatever the type
        ix.warn(f"  WARNING: the Datalinks text patch is missing from this installer ({type(e).__name__}: {e}), "
                "so it was skipped. Longevity Vaccine works without it.")
        return {}
    ix.say("\n--- Datalinks text ---")
    try:
        res = ph.patch_folder(game_dir, say=lambda t: ix.say("  " + t))
    except OSError as e:
        ix.warn(f"  WARNING: could not update the Datalinks text ({e}); Longevity Vaccine works without it.")
        return {}
    if not res:
        ix.say("  no helpx.txt / conceptsx.txt in the game folder: skipped")
    return res


def restore_datalinks_text(game_dir: Path) -> tuple:
    """--uninstall: our text comes back out of each file that carries it -- the exact inverse of the patch, so the
    file is what it would be had we never patched it, whatever updated it in between (no saved copy is put back).
    Returns (count restored, [files left holding the mod's text], [files that could not be written], [files with the
    mod's wording but no marker -- ours with the marker removed, or someone else's quoting it], [earlier versions'
    backups deleted]); the caller names the middle three in the verdict and the last in a refusal's disk note."""
    try:
        import patch_helptext as ph
    except Exception as e:  # noqa: BLE001
        ix.warn(f"  WARNING: the Datalinks text patch is missing from this installer ({type(e).__name__}: {e}), "
                "so its text files were not restored.")
        return 0, [], [], [], []
    # An earlier version's .longevity.bak is deleted beside an untouched file too, where the file's own line is
    # quiet: said here, so "nothing on disk was changed" is never printed over it (audit 2026-11-16).
    baks = {rel: ph.backup_of(p) for rel, p, _ in ph._targets(Path(game_dir))}
    had = {rel: b for rel, b in baks.items() if b.exists()}
    res = ph.restore_folder(game_dir, say=lambda t: ix.say("  " + t), quiet=(ph.UNPATCHED,))

    def shown(b: Path) -> str:
        return b.name if b.parent == Path(game_dir) else f"{b.parent.name}\\{b.name}"
    gone = {rel: b for rel, b in had.items() if not b.exists()}
    dropped = sorted(shown(b) for b in gone.values())
    # Said once: a file whose own line was said names its backup there ("restored ... (removed ...)"); only a quiet
    # one's is said here (audit 2026-11-16, D7: a normal uninstall said it twice).
    for rel, b in sorted(gone.items()):
        if res.get(rel) in (ph.UNPATCHED,):
            ix.say(f"  removed {shown(b)}, a copy an earlier version kept")
    held = [n for n, s in res.items() if s in ph.REFUSED and s != ph.UNMARKED]
    failed = [n for n, s in res.items() if s == ph.FAILED]
    if failed:      # master's warning: the verdict's "(see the warnings above)" points here
        ix.warn(f"  WARNING: could not restore {', '.join(failed)}. Close the game and run --uninstall again.")
    unmarked = [n for n, s in res.items() if s == ph.UNMARKED]
    return sum(1 for s in res.values() if s == ph.RESTORED), held, failed, unmarked, dropped


#: Wine / Proton: GOG's DDrawCompat ddraw.dll crashes the game during DLL loading whenever a ddraw override makes
#: Wine load it (scripts/wine_ddraw.py). Every install and update run sets it aside under Wine, and puts a backup of
#: ours back when the same folder is installed from Windows; --uninstall puts it back. Never a reason to fail a run.
def wine_ddrawcompat(game_dir: Path) -> str:
    """Returns wine_ddraw's set_aside status ('' when the module is missing from this installer)."""
    try:
        import wine_ddraw as wd
    except Exception as e:  # noqa: BLE001 - a mistrimmed payload is the same user-facing problem whatever the type
        ix.warn(f"  WARNING: the Wine ddraw.dll check is missing from this installer ({type(e).__name__}: {e}), "
                "so it was skipped. It only matters under Wine.")
        return ""
    status, line = wd.set_aside(game_dir)
    if line:
        ix.say("\n--- ddraw.dll ---")
        (ix.warn if status == wd.FAILED else ix.say)("  " + line)
    return status


def restore_wine_ddrawcompat(game_dir: Path) -> str:
    """--uninstall: GOG's DDrawCompat back from the backup wine_ddrawcompat made. Returns wine_ddraw's restore
    status ('restored' = a file put back, 'dropped' = a redundant backup deleted; '' when the module is missing)."""
    try:
        import wine_ddraw as wd
    except Exception as e:  # noqa: BLE001
        ix.warn(f"  WARNING: the Wine ddraw.dll check is missing from this installer ({type(e).__name__}: {e}), "
                "so a ddraw.dll.longevity.bak, if any, was not put back.")
        return ""
    status, line = wd.restore(game_dir)
    if line:
        (ix.warn if status in (wd.FAILED, wd.KEPT) else ix.say)("  " + line)
    if status == wd.RESTORED and wd.platform() == wd.WINE:
        ix.warn("  Under Wine the game starts without it, as before; but a ddraw DLL override would now load it "
                "again and crash the game at start.")
    return status


def datalinks_text_status(res: dict) -> str:
    """One summary word for the table: ok when any file found took (or already had) the text, else skip. A file
    left alone beside patched ones is named under the row (datalinks_text_note), not hidden behind a Skipped."""
    return "ok" if res and any(s in ("patched", "current") for s in res.values()) else "skip"


#: Why patch_folder left a file alone, by its status (patch_helptext's names), for datalinks_text_note.
_DATALINKS_LEFT_REASON = {
    "foreign": "not the stock text",
    "edited": "changed after Longevity Vaccine patched it",
    "old-revision": "an older Longevity Vaccine text that cannot be updated",
    "newer-revision": "a newer Longevity Vaccine version's text",
    "unmarked": "Longevity Vaccine's wording without its marker line",
    "failed": "could not be written",
}


def datalinks_text_note(res: dict) -> str:
    """The files patch_folder left alone and why, for the line under the summary row; '' when none."""
    by_reason = {}
    for n, s in sorted(res.items()):
        if s not in ("patched", "current"):
            by_reason.setdefault(_DATALINKS_LEFT_REASON.get(s, s), []).append(n)
    parts = [f"{', '.join(names)} left alone: {why}" for why, names in by_reason.items()]
    return f"  ({'; '.join(parts)})" if parts else ""


def patch_pracx_icons(game_dir: Path) -> dict:
    """GOG's Planetary Pack ships PRACX without PRACX's Icons.pcx, so its grey unworked-tile yields and its map
    views draw nothing (GOG's bug). Adds that art to a stock sheet; any other sheet is left alone. Never fails a run.
    Returns {"Icons.pcx": patch_icons status}; {} when the folder has no Icons.pcx."""
    try:
        import patch_icons as pi
    except Exception as e:  # noqa: BLE001 - a mistrimmed payload is the same user-facing problem whatever the type
        ix.warn(f"  WARNING: the PRACX icon fix is missing from this installer ({type(e).__name__}: {e}), "
                "so it was skipped. Longevity Vaccine works without it.")
        return {}
    ix.say("\n--- PRACX icons ---")
    res = pi.patch_folder(game_dir, pracx_icons_overlay(), say=lambda t: ix.say("  " + t))
    if not res:
        ix.say(f"  no {pi.SHEET} in the game folder: skipped")
    elif any(s == pi.FAILED for s in res.values()):
        ix.warn(f"  WARNING: PRACX's grey unworked-tile yields were not added. Close the game, make sure {pi.SHEET} "
                "is not read-only, and run the installer again. Longevity Vaccine works without them.")
    return res


def restore_pracx_icons(game_dir: Path) -> tuple:
    """--uninstall: Icons.pcx goes back to its .longevity.bak while it is still ours.
    Returns (restored, failed, [leftovers deleted]): failed is 1 when the restore was due but could not be done (the
    verdict says so); a leftover is a spare backup beside a sheet that is already the original, or a temporary file
    an interrupted write left -- said here, and named in a refusal's disk note, so "nothing on disk was changed" is
    never said over them (audit 2026-11-16, D6)."""
    try:
        import patch_icons as pi
    except Exception as e:  # noqa: BLE001
        ix.warn(f"  WARNING: the PRACX icon fix is missing from this installer ({type(e).__name__}: {e}), "
                "so Icons.pcx was not restored.")
        return 0, 0, []
    sheet = Path(game_dir) / pi.SHEET
    bak = pi.backup_of(sheet)
    temps = [t for t in (pi.tmp_of(sheet), pi.tmp_of(bak)) if t.exists()]
    had_bak = bak.exists()
    # Only what the player needs to hear: a restore, a sheet left alone, a failure -- not "nothing to restore" on
    # every folder the mod never had to change.
    res = pi.restore_folder(game_dir, say=lambda t: ix.say("  " + t)
                            if ("restored" in t or "left alone" in t or "could not" in t) else None)
    dropped = []
    for t in temps:
        if not t.exists():
            ix.say(f"  removed {t.name}, left by an interrupted write")
            dropped.append(t.name)
    if had_bak and not bak.exists() and res.get(pi.SHEET) != pi.RESTORED:
        ix.say(f"  removed {bak.name}, a spare copy: {pi.SHEET} is already the original")
        dropped.append(bak.name)
    if any(s == pi.FAILED for s in res.values()):
        ix.warn("  WARNING: could not restore Icons.pcx. Close the game, make sure Icons.pcx is not read-only, "
                "and run --uninstall again.")
    return (sum(1 for s in res.values() if s == pi.RESTORED), sum(1 for s in res.values() if s == pi.FAILED),
            dropped)


def pracx_icons_status(res: dict) -> str:
    """Summary word: ok when the sheet has the art now (added or already there), error on a failure, else skip."""
    st = next(iter(res.values()), "")
    return "ok" if st in ("added", "current") else ("error" if st == "failed" else "skip")


def deploy_runtime(game_dir: Path, quiet: bool = False) -> bool:
    """Copy uimod.dll + the slim ffmpeg DLLs into the game dir.

    `quiet`: a pack-only update re-deploys the same files; six "deployed x.dll" lines above
    "Nothing else needed changing" contradicted it."""
    if quiet:
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            return deploy_runtime(game_dir, quiet=False)
    ix.say("\n--- mod files ---")
    dll, ffmpeg = uimod_dll(), ffmpeg_bin()
    if not dll.exists():
        ix.say(f"  ERROR: {dll} not found -- build it first (src\\uimod\\build.bat).")
        return False
    if not ffmpeg.is_dir():
        ix.say(f"  ERROR: ffmpeg DLLs not found at {ffmpeg}.")
        return False

    dlls = sorted(ffmpeg.glob("*.dll"))
    if not dlls:
        ix.say(f"  ERROR: no DLLs in {ffmpeg}.")
        return False
    # Copy failures here are USER-side conditions (the game is running and holds uimod.dll, an
    # antivirus has the file open, the directory is read-only), not installer bugs. Letting an
    # OSError escape would route them to the crash handler, which tells the user "this is a bug
    # in the installer, not something you did wrong" -- false, and unhelpful.
    for src in [dll] + dlls:
        try:
            shutil.copy2(src, game_dir / src.name)
        except OSError as e:
            ix.bad(f"  ERROR: could not write {src.name}: {e}")
            return False
    copied = len(dlls) + 1

    # The popup picture is cosmetic: the DLL shows a text-only prompt without it. Neither a
    # payload that lacks it (a resident updater from before the picture existed) nor a copy
    # failure may strand an update -- warn and go on.
    art = popup_art()
    if not art.exists():
        ix.warn(f"  WARNING: {art.name} is not in this installer; the update prompt will show no picture.")
    else:
        try:
            shutil.copy2(art, game_dir / art.name)
            copied += 1
        except OSError as e:
            ix.warn(f"  WARNING: could not write {art.name} ({e}); the update prompt will show no picture.")
    # The replacement-portraits guide: the folder players put their own portraits in.  Cosmetic, like the
    # picture: a payload without it or a copy failure warns and goes on.  Only README.txt is ever written there
    # by the base mod -- the player's images in portraits\ are never touched.
    readme = portraits_readme()
    if readme.exists():
        try:
            (game_dir / "portraits").mkdir(parents=True, exist_ok=True)
            shutil.copy2(readme, game_dir / "portraits" / PORTRAITS_README)
            copied += 1
        except OSError as e:
            ix.warn(f"  WARNING: could not write portraits\\{PORTRAITS_README} ({e}).")
    # One line, not one per file: the names mean nothing to a player (audit 2026-09-27).
    ix.say(f"  {copied} files copied")
    return True


def set_ini_flag(game_dir: Path, enabled: bool) -> None:
    """Write [UIMod] UpscaledVideos via the Win32 profile API (preserves the file)."""
    ini = _ini_path_str(game_dir)
    k = _kernel32()
    try:
        if k is None:
            raise OSError("no Win32 profile API available")
        ok = k.WritePrivateProfileStringW("UIMod", "UpscaledVideos",
                                          "1" if enabled else "0", ini)
    except (OSError, ValueError, AttributeError) as e:
        # A non-ANSI-encodable path, or the call itself failing, must not crash a finished
        # install: everything else is already on disk and the game runs without this flag.
        print(f"  WARNING: could not write the ini flag ({e}).")
        print(f"  Set [UIMod] UpscaledVideos={1 if enabled else 0} by hand in {ini} if needed.")
        return
    if not ok:
        ix.warn(f"  WARNING: could not write [UIMod] UpscaledVideos={1 if enabled else 0} to {ini}.")


def _copy_into_place(src: Path, dst: Path) -> None:
    """Copy `src` to a private temp name beside `dst`, then rename it into place, as install_modules places an archive
    member (audit-n 2026-11-17: on Python 3.12 CopyFile2 sizes the destination before any data arrives, so a copy
    straight to `dst` that was stopped part-way left a full-size torn file, which the next run's size check kept)."""
    tmp = dst.with_name(dst.name + f".tmp-{os.getpid()}")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
        tmp = None
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def _local_partial(pack: Path, dst: Path) -> bool:
    """A local pack's own pack-manifest.json as the .partial in `dst`, before any of its files (audit-p 2026-11-17).
    False (said with the copy-failure wording) when it cannot be written. A pack without a manifest writes none."""
    src = Path(pack) / "pack-manifest.json"
    import safe_fs
    if not src.is_file() or safe_fs.link_on_path(Path(dst).parent.parent, Path(dst)):
        return True                                       # nothing written through a link (audit-q L1)
    try:
        _write_partial(dst, src.read_bytes())
        return True
    except OSError as e:
        ix.say(f"  WARNING: could not copy {src.name}: {e}")
        return False


def install_movie_pack(game_dir: Path, pack: Path) -> bool:
    """Copy the prebuilt HD mp4 pack into <game>\\movies\\hd."""
    mp4s = sorted(pack.glob("*.mp4")) if pack.is_dir() else []
    if not mp4s:
        print(f"  WARNING: no .mp4 found in {pack}. The HD pack is empty.")
        print("           Cinematics will fall back to the original .wve until the pack is built")
        print("           (work\\run-build-hd-pack.bat). Leaving UpscaledVideos on so they")
        print("           upgrade automatically once the pack is present.")
        return False
    dst = game_dir / "movies" / "hd"
    # Guarded like deploy_runtime: a read-only game dir, a full disk, or a clip held open by a
    # media indexer are USER-side conditions. Letting an OSError escape would reach the crash
    # handler, which tells the user "this is a bug in the installer" and -- worse -- this runs
    # AFTER the exe is patched, so the honest report is a partial install, not a crash.
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        ix.say(f"  WARNING: could not create {dst}: {e}")
        ix.say("           Longevity Vaccine is installed; cinematics stay on the original .wve.")
        return False
    if not _local_partial(pack, dst):
        return False
    copied = 0
    for f in mp4s:
        try:
            _copy_into_place(f, dst / f.name)
        except OSError as e:
            ix.say(f"  WARNING: could not copy {f.name}: {e}")
            ix.say(f"           Copied {copied} of {len(mp4s)}. Longevity Vaccine itself is installed;"
                   " re-run to finish the pack.")
            return False
        copied += 1
    # The pack's manifest and its credit/licence travel with the clips, as the released archive carries them.
    complete = True
    for extra in _MOVIE_PACK_EXTRAS:
        f = pack / extra
        if f.is_file():
            try:
                _copy_into_place(f, dst / f.name)
            except OSError as e:
                complete = complete and extra != "pack-manifest.json"
                ix.say(f"  WARNING: could not copy {f.name}: {e}")
    if complete:
        _drop_partial(dst)                                  # the manifest has landed after every file (audit-p)
    ix.say(f"  copied {copied} cinematic(s) -> {dst}")
    ix.say(CINEMATICS_CREDIT)
    return True


#: Copied beside the clips from a local pack folder: the provenance sidecar and the upscaler's credit/licence.
_MOVIE_PACK_EXTRAS = ("PROVENANCE.txt", "pack-manifest.json")     # the manifest LAST (audit-o: _placed_last)

#: The movies-hd pack's required credit (work\art\movies-hd-PROVENANCE.txt): shown whenever the pack is installed.
CINEMATICS_CREDIT = ("  Cinematics upscaled by Z2k Retro -- https://www.youtube.com/@Z2KRetroGaming -- "
                     "https://www.youtube.com/@Z2kRetroVideo")


#: The portraits-hd art's required credit (work\art\portraits-hd-PROVENANCE.txt): shown whenever the pack is installed.
PORTRAIT_ART_CREDIT = ("  Portrait art by Turovetsky -- https://www.youtube.com/@Turovetsky -- "
                       "https://x.com/turovetsky")


#: What the portraits-hd pack is made of (build_portraits_hd.py): the leader images, its manifest and the art's
#: provenance/credit.  Nothing else is copied from a local pack folder.
_PORTRAIT_PACK_GLOBS = ("*.png", "pack-manifest.json", "PROVENANCE.txt")


def prune_pack_dir(game_dir: Path, rel: str, keep: set) -> int:
    """Delete the files directly in <game>\\<rel> that the new pack no longer carries.  ONLY for a folder the pack
    owns outright (portraits\\hd: players keep their own images one level up, and the README says so); never
    recursive, never a directory, never anything outside it.  Returns how many were removed."""
    d = Path(game_dir) / rel
    removed = 0
    try:
        root = Path(game_dir).resolve()
        # never through a junction / symlink: the folder must be exactly <game>\<rel>, or nothing is touched
        if not d.is_dir() or os.path.normcase(str(d.resolve())) != os.path.normcase(str(root / Path(*rel.split("/")))):
            return 0
        entries = list(d.iterdir())
    except OSError:
        return 0
    keep_l = {k.lower() for k in keep}                    # Windows names are case-insensitive
    for p in entries:
        try:
            if p.is_file() and not p.is_symlink() and p.name.lower() not in keep_l:
                p.unlink()
                removed += 1
        except OSError as e:
            ix.say(f"  WARNING: could not remove the old {p.name}: {e}")
    return removed


def install_portrait_pack(game_dir: Path, pack: Path) -> bool:
    """Copy a local portraits-hd pack (a checkout's dist\\portraits-hd) into <game>\\portraits\\hd."""
    files = sorted({p for g in _PORTRAIT_PACK_GLOBS for p in pack.glob(g) if p.is_file()},
                   key=lambda p: (_placed_last(p.name), p.name)) if pack.is_dir() else []    # the manifest LAST (audit-o)
    if not any(p.suffix.lower() == ".png" for p in files):
        ix.say(f"  WARNING: no portraits found in {pack} -- the pack is empty (work\\scripts\\art\\build_portraits_hd.py).")
        return False
    dst = Path(game_dir) / "portraits" / "hd"
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        ix.say(f"  WARNING: could not create {dst}: {e}")
        return False
    if not _local_partial(pack, dst):
        return False
    copied = 0
    for f in files:
        try:
            _copy_into_place(f, dst / f.name)
        except OSError as e:
            ix.say(f"  WARNING: could not copy {f.name}: {e}")
            ix.say(f"           Copied {copied} of {len(files)}. Re-run to finish the pack.")
            return False
        copied += 1
    _drop_partial(dst)                                      # the manifest has landed after every file (audit-p)
    pruned = prune_pack_dir(game_dir, "portraits/hd", {f.name for f in files})
    ix.say(f"  copied {copied} file(s) -> {dst}" + (f", removed {pruned} old" if pruned else ""))
    ix.say(PORTRAIT_ART_CREDIT)
    return True


def _ini_path_str(game_dir: Path) -> str:
    """Absolute path to Alpha Centauri.ini.

    RESOLVED: the Win32 profile API looks in %WINDIR% for a relative path, so a relative
    --game-dir would silently read and write C:\\Windows\\Alpha Centauri.ini.
    """
    try:
        return str(Path(game_dir).resolve() / "Alpha Centauri.ini")
    except OSError:
        return str(Path(game_dir) / "Alpha Centauri.ini")


def _kernel32():
    """kernel32, or None where there is no Win32 API to call."""
    try:
        return ctypes.windll.kernel32
    except (AttributeError, OSError):
        return None


#: Room for any value we store, plus a hand-edited one. The old buffer was 512 BYTES through the
#: ANSI entry points; the wide ones count characters.
_INI_BUF = 1024
#: Cannot occur in an ini value, so it distinguishes "no such key" from "present but empty".
_INI_ABSENT = "\x01<absent>"
_INI_TRUE = ("1", "true", "yes", "on")


def read_ini_str(game_dir: Path, section: str, key: str, default: str = "") -> str:
    """One profile value, as a string. Never raises.

    WIDE entry points deliberately. The ANSI ones take an mbcs-encoded path, and encoding it with
    `errors="replace"` turned an unencodable character into `?` -- a DIFFERENT, perfectly valid
    path. A player whose install lives under a Cyrillic, CJK or accented folder name therefore had
    every read and write land on a file that was not theirs, silently and with a success return.
    """
    k = _kernel32()
    if k is None:
        return default
    try:
        buf = ctypes.create_unicode_buffer(_INI_BUF)
        n = k.GetPrivateProfileStringW(section, key, default, buf, _INI_BUF,
                                       _ini_path_str(game_dir))
        return buf[:n]
    except (OSError, ValueError, AttributeError):
        return default


def write_ini_str(game_dir: Path, section: str, key: str, value: str) -> bool:
    """Write one ini value via the Win32 profile API (preserves the rest of the file)."""
    k = _kernel32()
    if k is None:
        return False
    try:
        return bool(k.WritePrivateProfileStringW(section, key, value, _ini_path_str(game_dir)))
    except (OSError, ValueError, AttributeError):
        return False


def delete_ini_key(game_dir: Path, section: str, key: str) -> bool:
    """Remove one key (a NULL value deletes it; the section and the rest of the file stay)."""
    k = _kernel32()
    if k is None:
        return False
    try:
        return bool(k.WritePrivateProfileStringW(section, key, None, _ini_path_str(game_dir)))
    except (OSError, ValueError, AttributeError):
        return False


#: Thinker's external-movie-player key. thinker.dll reads it on EVERY launch (refs\thinker\src\patch.cpp,
#: video player setup); the game and PRACX never do (neither binary contains the string). Its states:
#: absent / `<DEFAULT>` -> Thinker scans two VLC paths and uses VLC if found, else asks Yes/No at launch;
#: a path -> that external player; BLANK -> Thinker's own "default video player" = amovie_project_2 =
#: our in-process player, and Thinker writes nothing back, so blank is sticky.
THINKER_MOVIE_SECTION = "Alpha Centauri"
THINKER_MOVIE_KEY = "MoviePlayerPath"


def ensure_in_process_movies(game_dir: Path) -> None:
    """`[Alpha Centauri] MoviePlayerPath=` (blank), on every install AND update run, Thinker present or
    not, silently (user decision 2026-10-28, movie ownership option A2: every player gets the mod's
    in-process player and the HD Cinematics; an auto-detected or hand-set external player is
    overridden without a notice). Written whether or not Thinker is installed so that adding Thinker
    later cannot hand the movies to VLC on its first launch. Idempotent; never raises."""
    if read_ini_str(game_dir, THINKER_MOVIE_SECTION, THINKER_MOVIE_KEY, _INI_ABSENT) == "":
        return
    if not write_ini_str(game_dir, THINKER_MOVIE_SECTION, THINKER_MOVIE_KEY, ""):
        ix.warn(f"  WARNING: could not write [{THINKER_MOVIE_SECTION}] {THINKER_MOVIE_KEY}= to "
                f"{_ini_path_str(game_dir)}; under Thinker the cinematics may play through an external player.")


def release_in_process_movies(game_dir: Path) -> None:
    """--uninstall: delete the key when it is blank, so Thinker starts from "absent" on its next
    launch and re-runs its own player detection exactly as a fresh Thinker install does (a blank is
    the one value Thinker never re-initialises). Nothing of ours is remembered across the install
    (user decision 2026-10-28), so a blank the player set by hand cannot be told from ours and is
    deleted too; any non-blank value is left alone."""
    if read_ini_str(game_dir, THINKER_MOVIE_SECTION, THINKER_MOVIE_KEY, _INI_ABSENT) != "":
        return
    if not delete_ini_key(game_dir, THINKER_MOVIE_SECTION, THINKER_MOVIE_KEY):
        ix.say(f"  WARNING: could not remove [{THINKER_MOVIE_SECTION}] {THINKER_MOVIE_KEY} from "
               f"{_ini_path_str(game_dir)}; delete the line by hand to restore Thinker's video player prompt.")


# ---------------------------------------------------------------- display resolution check
#
# PRACX runs the game at [PRACX] ScreenWidth x ScreenHeight. Its default, written to the ini as
# "<DEFAULT>", is the display's CURRENT mode (pracxsettings.cpp Load: EnumDisplaySettings), but a
# player who once picked a lower resolution in PRACX's dialog, or changed monitors, has explicit
# numbers that no longer match. PRACX then switches the display to that mode in fullscreen
# (pracx.cpp SetVideoMode: ChangeDisplaySettings when the sizes differ) and the display or GPU
# scales it up -- blurred, and distorted when the aspect differs; the Borderless/Windowed modes
# stretch the backbuffer the same way. The whole point of the mod is a native-resolution UI, so
# the installer notices and offers to put "<DEFAULT>" back (which follows the display from then
# on) rather than baking today's numbers in.

def current_display_mode():
    """(width, height) of the primary display's CURRENT mode in physical pixels, or None.
    EnumDisplaySettings, not GetSystemMetrics: the latter is DPI-virtualised for an unaware
    process and would report 2560x1440 for a 4K display at 150%."""
    try:
        class DEVMODEW(ctypes.Structure):
            _fields_ = [("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", ctypes.c_ushort),
                        ("dmDriverVersion", ctypes.c_ushort), ("dmSize", ctypes.c_ushort),
                        ("dmDriverExtra", ctypes.c_ushort), ("dmFields", ctypes.c_uint),
                        ("dmPositionX", ctypes.c_int), ("dmPositionY", ctypes.c_int),
                        ("dmDisplayOrientation", ctypes.c_uint), ("dmDisplayFixedOutput", ctypes.c_uint),
                        ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                        ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
                        ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32),
                        ("dmLogPixels", ctypes.c_ushort), ("dmBitsPerPel", ctypes.c_uint),
                        ("dmPelsWidth", ctypes.c_uint), ("dmPelsHeight", ctypes.c_uint),
                        ("dmDisplayFlags", ctypes.c_uint), ("dmDisplayFrequency", ctypes.c_uint),
                        ("dmICMMethod", ctypes.c_uint), ("dmICMIntent", ctypes.c_uint),
                        ("dmMediaType", ctypes.c_uint), ("dmDitherType", ctypes.c_uint),
                        ("dmReserved1", ctypes.c_uint), ("dmReserved2", ctypes.c_uint),
                        ("dmPanningWidth", ctypes.c_uint), ("dmPanningHeight", ctypes.c_uint)]
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(DEVMODEW)
        if not ctypes.windll.user32.EnumDisplaySettingsW(None, -1, ctypes.byref(dm)):   # ENUM_CURRENT_SETTINGS
            return None
        if dm.dmPelsWidth <= 0 or dm.dmPelsHeight <= 0:
            return None
        return int(dm.dmPelsWidth), int(dm.dmPelsHeight)
    except (OSError, AttributeError, ValueError):
        return None


def resolution_mismatch(ini_w: str, ini_h: str, display) -> tuple:
    """(game_w, game_h) when the ini pins an explicit resolution DIFFERENT from `display`
    (a (w, h) pair), else None. "<DEFAULT>", an absent key, or anything non-numeric means PRACX
    follows the display, so there is nothing to fix; an unknown display means nothing to compare."""
    if not display:
        return None
    try:
        w, h = int(str(ini_w).strip()), int(str(ini_h).strip())
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0 or (w, h) == tuple(display):
        return None
    return w, h


def resolution_check_applies(target_id) -> bool:
    """The pinned-resolution check is for every configuration that carries PRACX (its prax.dll
    companion), not for the id "pracx" alone: PRACX + Thinker has the same keys and the same
    stretched-game hazard (audit 2026-10-28)."""
    spec = _targets().get(target_id) if target_id else None
    return spec is not None and bool(spec.companion)


def check_display_resolution(game_dir: Path, target_id, no_prompt: bool = False, ask: bool = True) -> None:
    """Warn about a pinned [PRACX] resolution that differs from the display; offer to reset it.
    Never raises: it runs after the install has succeeded."""
    if not resolution_check_applies(target_id):
        return                      # only the PRACX configurations have these keys
    if read_ini_str(game_dir, "PRACX", "Disabled", "").strip() == "1":
        return                      # PRACX switched off: its resolution keys do nothing
    ini_w = read_ini_str(game_dir, "PRACX", "ScreenWidth", "")
    ini_h = read_ini_str(game_dir, "PRACX", "ScreenHeight", "")
    display = current_display_mode()
    mm = resolution_mismatch(ini_w, ini_h, display)
    if not mm:
        return
    ix.say("")
    ix.warn(f"WARNING: Alpha Centauri.ini sets the game to {mm[0]}x{mm[1]}, but your display is "
            f"{display[0]}x{display[1]}. The game would run stretched instead of at your display's resolution.")
    # Ask whenever a keyboard is attached. `no_prompt` alone is not the gate: the bootstrap's
    # worker always carries --no-prompt (for optional extras) yet runs in the console the player
    # is watching (2026-09-27: the question was skipped there and only the hint printed).
    # `ask` is False only for a first install run with the PLAYER's --no-prompt ("never ask").
    if not ix.can_ask() or not ask:
        ix.say("Set [PRACX] ScreenWidth and ScreenHeight to <DEFAULT> in Alpha Centauri.ini to fix this.")
        return
    left = ("Left your resolution as is. Your game will likely appear stretched until you fix this! "
            "Set [PRACX] ScreenWidth and ScreenHeight to <DEFAULT> in Alpha Centauri.ini.")
    try:
        # User-approved 2026-11-15: an arrow choice, the display's resolution first (the default).
        pick = ix.arrow_choice("Game resolution", [], [f"Use your display's resolution ({display[0]}x{display[1]})",
                                                       f"Keep {mm[0]}x{mm[1]} (the game will look stretched)"])
    except (EOFError, KeyboardInterrupt):
        ix.warn(left)
        return
    if pick != 0:
        ix.warn(left)
        return
    ok = write_ini_str(game_dir, "PRACX", "ScreenWidth", "<DEFAULT>") and \
        write_ini_str(game_dir, "PRACX", "ScreenHeight", "<DEFAULT>")
    if ok:
        ix.say(f"[PRACX] ScreenWidth/ScreenHeight = <DEFAULT>: the game now follows your display ({display[0]}x{display[1]}).")
    else:
        ix.say("WARNING: could not write Alpha Centauri.ini; set [PRACX] ScreenWidth and ScreenHeight to <DEFAULT> by hand.")


#: The game's own setting (update.cpp reads [UIMod] CheckForUpdates; absent = on). The installer writes it
#: ONLY from the player's answer to the question below, never a default.
UPDATE_CHECK_KEY = "CheckForUpdates"
UPDATE_CHECK_TITLE = "Automatic updates"
#: The user's wording (2026-11-06), as the block's note lines. No Preferences option name in any installer line
#: (user 2026-11-15: first dropped from this block, then "Drop it everywhere"; UPDATE_CHECK_PREFS below).
UPDATE_CHECK_NOTES = (
    "When the game starts, it can check our server for a newer version of Longevity Vaccine and its",
    "optional modules, and offer to install them. You can change this any time in",
    "Longevity Preferences.",
)
#: The two options (user 2026-11-15: an arrow-key choice, the marker on the first).
UPDATE_CHECK_YES = "Check for updates when the game starts"
UPDATE_CHECK_NO = "Don't check for updates"
UPDATE_CHECK_PREFS = "Longevity Preferences"   # no option name (user 2026-11-15: "Drop it everywhere")


def update_check_state(game_dir: Path):
    """[UIMod] CheckForUpdates as the GAME reads it (update.cpp: GetPrivateProfileIntW with default
    1): None when absent; else the leading integer != 0, an empty value the default (on), a word
    ("yes") 0. ini_flag_state's rules are UpscaledVideos', which our own Python reads; for this key
    the installer must report what the game will do (audit 2026-11-06)."""
    raw = read_ini_str(game_dir, "UIMod", UPDATE_CHECK_KEY, _INI_ABSENT)
    if raw == _INI_ABSENT:
        return None
    s = raw.strip()
    if not s:
        return True
    import re
    m = re.match(r"[+-]?\d+", s)
    return bool(int(m.group(0))) if m else False


def ask_update_checks(game_dir: Path, args):
    """The opt-in for the game's update check (user 2026-11-06), asked once: on a FIRST install, at a
    console, without --no-prompt. Returns True / False for the answer (written the moment the exe is
    patched: before that every refusal says the game was not modified; after it the folder counts
    as installed and a re-run would not ask again), or None to leave the setting as it is -- a
    re-run keeps what the player has (the game's default, on, when the key was never written),
    --no-prompt and an unattended run keep the default; each says so in one line. An arrow-key choice
    (user 2026-11-15), the marker on UPDATE_CHECK_YES: only Enter on that option turns the checks on.
    Ctrl+C cancels the install like the picker; a closed stdin keeps the default."""
    state = update_check_state(game_dir)
    first = state is None and not _has_install(game_dir)
    if first and ix.can_ask() and not getattr(args, "no_prompt", False):
        try:
            pick = _arrow_menu(UPDATE_CHECK_TITLE, [[UPDATE_CHECK_YES], [UPDATE_CHECK_NO]], notes=UPDATE_CHECK_NOTES)
        except EOFError:
            pick = None
        if pick is not None:
            on = pick == 0
            ix.say("  The game will check for updates when it starts." if on else
                   f"  The game will not check for updates. Turn it on any time in {UPDATE_CHECK_PREFS}.")
            return on
    on = state is None or state
    ix.say("\n--- automatic updates ---")
    ix.say(f"  The game {'checks' if on else 'does not check'} for updates when it starts"
           f" ({'the default' if state is None else 'as before'}); change it in {UPDATE_CHECK_PREFS}.")
    return None


def write_update_check(game_dir: Path, on) -> None:
    """Record the answer as the game's setting; None (not asked) writes nothing."""
    if on is None:
        return
    if not write_ini_str(game_dir, "UIMod", UPDATE_CHECK_KEY, "1" if on else "0"):
        ix.warn(f"  WARNING: could not write [UIMod] {UPDATE_CHECK_KEY}={1 if on else 0} to Alpha Centauri.ini; "
                f"set it in {UPDATE_CHECK_PREFS}.")


def ini_flag_state(game_dir: Path, key: str):
    """True / False / None, where None means the key is ABSENT.

    The absent case is the one that matters: a FIRST install has no ini at all, and treating that
    as "the user chose 0" silently skipped the headline HD-cinematics feature under --no-wait.
    GetPrivateProfileInt cannot express it -- it returns the caller's default for a missing key
    and 0 for a non-numeric one, so `UpscaledVideos=yes` read back as "off" -- so this reads the
    raw string and decides for itself.

    A key that is PRESENT but unreadable (`UpscaledVideos=`, or `0 ; keep it off`, which the
    profile API hands back comment and all) resolves to False, never to None. Mapping it to
    "absent" would have made it mean "first install", and a first install defaults the HD pack
    ON -- so blanking or commenting a `0` re-copied 1.3 GB and reversed the player's choice.
    """
    raw = read_ini_str(game_dir, "UIMod", key, _INI_ABSENT)
    if raw == _INI_ABSENT:
        return None
    s = raw.strip().strip('"').lower()
    s = s.split(";")[0].split("#")[0].strip()      # trailing ini comment
    s = s.split()[0] if s.split() else ""          # `1 whatever` -> `1`
    return s in _INI_TRUE


def pack_on_disk(game_dir: Path, name: str) -> bool:
    """Is the pack's content already in the game folder (left by an uninstall, say)? The picker
    calls it "already installed", so it uses the game's own test where the game has one: the
    portrait pack counts only with its pack-manifest.json (portrait_files.cpp PackInstalled; a
    stray image or an interrupted copy in portraits\\hd is not the pack, and the game would not
    use it -- audit 2026-11-06). The HD Cinematics alike (audit-t ROOT 1: any file in movies\\hd used to count, so
    the player's own clips there reinstalled a declined pack over them): a readable pack-manifest.json, or the .partial
    of a pack the player chose whose install stopped part-way (audit-p MEDIUM-1). Files without a list are the
    player's."""
    return _manifest_readable(game_dir, name) or _has_partial(game_dir, name)


def _manifest_readable(game_dir: Path, name: str) -> bool:
    """The pack's own pack-manifest.json is in its folder and readable (_pack_names) -- never seen through a link."""
    import safe_fs
    try:
        root = Path(game_dir) / MODULE_ROOTS[name][0]
        return not safe_fs.link_on_path(Path(game_dir), root) and _pack_names(root / "pack-manifest.json") is not None
    except (OSError, KeyError):
        return False


#: Written in a pack's folder before any of its files is extracted or copied -- the release's own pack-manifest.json
#: under this name -- and removed once the real pack-manifest.json has landed after every file (audit-p 2026-11-17).
#: Its presence means a pack the player chose whose placing did not finish: never kept or adopted, completed by the
#: next run, and removed (with what it lists) by an uninstall.
PACK_PARTIAL = "pack-manifest.json.partial"


def _has_partial(game_dir: Path, name: str) -> bool:
    """The pack folder holds a .partial -- never one seen through a junction or symlink (audit-q L1)."""
    import safe_fs
    try:
        root = Path(game_dir) / MODULE_ROOTS[name][0]
        return not safe_fs.link_on_path(Path(game_dir), root) and (root / PACK_PARTIAL).is_file()
    except (OSError, KeyError):
        return False


#: LongevityMods\pending-packs.json: the packs a setup run chose whose download or placing did not finish (audit-q
#: M3) -- the case a .partial cannot mark, because the archive never arrived. Written before the run fetches or copies
#: them, cleared per pack when it lands, on an explicit untick and on uninstall. {"packs": [<id>, ...]}.
PENDING_PACKS = "pending-packs.json"


def _pending_path(game_dir: Path) -> Path:
    return Path(game_dir) / "LongevityMods" / PENDING_PACKS


def pending_packs(game_dir: Path) -> set:
    """The packs marked pending. Unreadable, malformed or behind a link: none. Never raises."""
    import json
    import safe_fs
    p = _pending_path(game_dir)
    try:
        if safe_fs.link_on_path(Path(game_dir), p) or not p.is_file():
            return set()
        doc = json.loads(p.read_text(encoding="utf-8"))
        packs = doc.get("packs") if isinstance(doc, dict) else None
        return {n for n in packs if n in GAME_CONTENT_MODULES} if isinstance(packs, list) else set()
    except Exception:  # noqa: BLE001 - a marker that cannot be read marks nothing
        return set()


def _mark_pending(game_dir: Path, names, on: bool) -> None:
    """Add (`on`) or remove `names` in the pending marker. Never through a link; never raises."""
    import json
    import safe_fs
    cur = pending_packs(game_dir)
    new = (cur | set(names)) if on else (cur - set(names))
    if new == cur:
        return
    p = _pending_path(game_dir)
    try:
        if safe_fs.link_on_path(Path(game_dir), p):
            return
        if not new:
            if p.is_file():
                safe_fs.unlink_entitled(p)                # a read-only copy too, as our other files (audit-r L-a)
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".tmp-{os.getpid()}")
        tmp.write_text(json.dumps({"packs": sorted(new)}), encoding="utf-8")
        if p.is_file() and not os.access(p, os.W_OK):
            import stat
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)      # our own marker, made read-only by someone (audit-r L-a)
        os.replace(tmp, p)
    except OSError:
        pass             # left as it was: a KEEP still wins over it (pack_action ignores the marker)


def forget_pending_packs(game_dir: Path) -> None:
    """Uninstall: nothing is pending for a folder Longevity Vaccine leaves (audit-q M3)."""
    _mark_pending(game_dir, GAME_CONTENT_MODULES, False)


def pack_pending(game_dir: Path, name: str) -> bool:
    """A pack the player chose that is not complete: marked pending, or its folder holds a .partial."""
    return name in pending_packs(game_dir) or _has_partial(game_dir, name)


def _pack_declined(game_dir: Path, name: str) -> bool:
    """The player said no to this pack: a new:<pack> decline is recorded, whatever its version."""
    import receipt as rc
    try:
        return NEW_PACK_PREFIX + name in rc.declined(game_dir)
    except Exception:  # noqa: BLE001
        return False


def pending_allowed(game_dir: Path, name: str) -> bool:
    """Pending state completes a pack only when nothing says no (audit-r 2026-11-17): no decline of the pack recorded --
    the player's latest explicit "no" always wins, and ends the pending state (end_pending). On a first install too
    (audit-s): the receipt is written only at the end, so a first install stopped while placing a pack runs again as a
    first install, and pending state can outlive a run only that way (an uninstall clears it). Such a pack starts
    ticked and is completed interactively, with --no-prompt and unattended. An interrupted UPDATE of an installed pack
    (_interrupted_update) is always completed: a decline is about a pack the player does not have (audit-t ROOT 3)."""
    return pack_pending(game_dir, name) and (_interrupted_update(game_dir, name) or not _pack_declined(game_dir, name))


def _interrupted_update(game_dir: Path, name: str) -> bool:
    """An update of an installed pack stopped part-way: the older pack's own manifest beside the newer .partial.
    Completing it is the only consistent state, so it is locked ticked in the list and never ended by a "no" (audit-t
    ROOT 3, M3: unticking it orphaned new-release files and left a mixed pack). The player can still uninstall."""
    return _manifest_readable(game_dir, name) and _has_partial(game_dir, name)


def end_pending(game_dir: Path, name: str) -> None:
    """An explicit "no" to a half-placed pack -- an untick, --ai off for the Cinematics, or a decline the game recorded
    -- ends its pending state (audit-s 2026-11-17), so nothing installs it on its own later (a "Reset Skipped Updates"
    finds nothing pending). In order: the files its .partial proves ours (size + sha256, as at uninstall) and our own
    "<name>.tmp-<pid>" leftovers, with its PROVENANCE.txt; then the .partial; then the marker entry; then the folder
    when empty. Unproven files stay. A pack whose own pack-manifest.json is there (an update stopped part-way: an
    installed older pack) loses nothing but the .partial. Nothing through a link. Never raises."""
    import safe_fs
    game_dir = Path(game_dir)
    root = game_dir / MODULE_ROOTS[name][0]
    try:
        if not safe_fs.link_on_path(game_dir, root) and (root / PACK_PARTIAL).is_file():
            if not (root / "pack-manifest.json").is_file():
                partial = root / PACK_PARTIAL
                proofs = _partial_proofs(partial) if _pack_names(partial) is not None else None
                ours = {"provenance.txt", "pack-manifest.json", PACK_PARTIAL.lower()}
                for n, (size, sha) in (proofs or {}).items():
                    ours.add(n.lower())
                    f = root / n
                    if f.is_file() and not _is_link(f) and _matches(f, size, sha):
                        try:
                            safe_fs.unlink_entitled(f)
                        except OSError:
                            pass         # left, unlisted once the .partial goes: an uninstall says so
                for f in list(root.iterdir()):
                    m = re.fullmatch(r"(.+)\.tmp-\d+", f.name)
                    if (f.name == "PROVENANCE.txt" or (m and m.group(1).lower() in ours)) \
                            and f.is_file() and not _is_link(f):
                        try:
                            safe_fs.unlink_entitled(f)
                        except OSError:
                            pass
            _drop_partial(root)
            try:
                root.rmdir()                                  # only when empty
            except OSError:
                pass
    except OSError:
        pass
    _mark_pending(game_dir, [name], False)


def _pack_installed(catalogue_entry: dict, game_dir: Path, name: str) -> bool:
    """Installed for the list's purposes (ticked by default, never turned down): its own pack-manifest.json is there
    (audit-t ROOT 1) -- an update stopped part-way (that manifest and a newer .partial) included. A half-placed pack (a
    .partial alone) is not installed: an untick of it is a "no" like any other (audit-r MEDIUM-1). module_catalogue
    records it as the entry's "installed"; an entry without it falls back to on disk and not half-placed."""
    if "installed" in catalogue_entry:
        return bool(catalogue_entry["installed"])
    return bool(catalogue_entry.get("on_disk")) and not _has_partial(game_dir, name)


def _write_partial(root: Path, data: bytes) -> None:
    """The pack's .partial, beside where its files go, before the first of them (private temp name, then renamed)."""
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f"{PACK_PARTIAL}.tmp-{os.getpid()}"
    try:
        tmp.write_bytes(data)
        os.replace(tmp, root / PACK_PARTIAL)
        tmp = None
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def _drop_partial(root: Path) -> None:
    try:
        (root / PACK_PARTIAL).unlink(missing_ok=True)
    except OSError:
        pass                    # left: the next run completes the pack again rather than keeping it


def _pack_entries(game_dir: Path, name: str):
    """(name, size) for every file the installed pack's pack-manifest.json lists, or None when there is no such file,
    it cannot be read, or a name in it could leave the pack's folder (then it is not a pack this installer placed)."""
    import json
    rels = MODULE_ROOTS.get(name, ())
    if not rels:
        return None
    manifest = Path(game_dir) / rels[0] / "pack-manifest.json"
    names = _pack_names(manifest)
    if not names:
        return None
    try:
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        entries = doc.get("clips") or doc.get("files")
        sizes = [e.get("size") for e in entries]
    except Exception:  # noqa: BLE001 - any failure to parse it (RecursionError too: audit-n D1) proves nothing
        return None
    if not all(isinstance(s, int) and not isinstance(s, bool) and s >= 0 for s in sizes):
        return None
    return list(zip(names, sizes))


def release_manifest_sha256(entry: dict, name: str):
    """The sha256 of the pack-manifest.json the offered release carries, when it is known without downloading it
    (audit-n 2026-11-17): a local pack's own file; for a download, the compiled one (version.PACK_MANIFEST_SHA256),
    only when the offered version is the one this installer ships. Else None (nothing to adopt)."""
    if entry.get("source") == "local":
        try:
            return hashlib.sha256((Path(entry["path"]) / "pack-manifest.json").read_bytes()).hexdigest()
        except (OSError, KeyError, TypeError):
            return None
    if entry.get("version") is not None and entry.get("version") == ver.MODULE_VERSIONS.get(name):
        return ver.PACK_MANIFEST_SHA256.get(name)
    return None


def release_provenance_sha256(entry: dict, name: str):
    """The sha256 of the PROVENANCE.txt the offered release carries, when it is known without downloading it
    (audit-o 2026-11-17), as release_manifest_sha256: a local pack's own file (None when it has none); for a download,
    the compiled one, only for the version this installer ships. None: not known (the released 1.0.0 Cinematics
    carries no PROVENANCE.txt at all), so nothing is asked of it."""
    if entry.get("source") == "local":
        try:
            return hashlib.sha256((Path(entry["path"]) / "PROVENANCE.txt").read_bytes()).hexdigest()
        except (OSError, KeyError, TypeError):
            return None
    if entry.get("version") is not None and entry.get("version") == ver.MODULE_VERSIONS.get(name):
        return ver.PACK_PROVENANCE_SHA256.get(name)
    return None


def _provenance_ok(game_dir: Path, name: str, release_provenance) -> bool:
    """The folder's PROVENANCE.txt is the release's (release_provenance_sha256); True when that is not known."""
    if not release_provenance:
        return True
    try:
        data = (Path(game_dir) / MODULE_ROOTS[name][0] / "PROVENANCE.txt").read_bytes()
    except (OSError, KeyError):
        return False
    return hashlib.sha256(data).hexdigest() == release_provenance


def _is_release(game_dir: Path, name: str, release_manifest) -> bool:
    """The folder's pack-manifest.json is byte-identical to the offered release's (release_manifest_sha256)."""
    if not release_manifest:
        return False
    try:
        data = (Path(game_dir) / MODULE_ROOTS[name][0] / "pack-manifest.json").read_bytes()
    except (OSError, KeyError):
        return False
    return hashlib.sha256(data).hexdigest() == release_manifest


def pack_intact(game_dir: Path, name: str) -> bool:
    """Every file the installed pack's pack-manifest.json lists is there, at the size it lists. Size and presence only,
    never a hash (user 2026-11-17: measured, a full sha256 of the 4.96 GB Cinematics is about 4 s on an NVMe disk and
    25-50 s on a hard disk, on every re-run; this check takes milliseconds). A file damaged without changing its size
    is not caught here."""
    entries = _pack_entries(game_dir, name)
    if entries is None:
        return False
    root = Path(game_dir) / MODULE_ROOTS[name][0]
    try:
        return all((root / n).is_file() and (root / n).stat().st_size == size for n, size in entries)
    except OSError:
        return False


def pack_action(game_dir: Path, name: str, offered, recorded, release_manifest=None, release_provenance=None) -> str:
    """What a setup run does with a pack the player chose (user 2026-11-17): "install" (not in the game folder, or
    nothing proves which release is there: no receipt version, no readable pack-manifest.json); "update" (the offered
    version is newer than the receipt's); "repair" (a listed file is missing or the wrong size); "keep" (current and
    intact: nothing is downloaded or copied, and its receipt entry stays as it is).

    "adopt" (audit-n 2026-11-17): in place of "install" or "update", when the folder already holds the offered release
    -- its pack-manifest.json byte-identical to that release's (`release_manifest`, release_manifest_sha256), every
    listed file there at its size. Kept like "keep", but the offered version is recorded. The limit is pack_intact's:
    a listed file swapped for another of the same size is not caught.

    PROVENANCE.txt (audit-o 2026-11-17): adoption also needs the release's own (`release_provenance`,
    release_provenance_sha256; a release whose PROVENANCE is not known is never adopted), and a pack recorded at the
    version on offer is repaired when that release's PROVENANCE.txt is missing or different. A release not known to
    carry one (the 1.0.0 Cinematics) asks for none."""
    if not pack_on_disk(game_dir, name) or _pack_entries(game_dir, name) is None:
        return "install"
    offered_ok = isinstance(offered, str) and ver.is_valid(offered)
    known = ver.is_valid(recorded) and ver.normalise(recorded) != ver.UNKNOWN
    newer = known and offered_ok and ver.is_newer(offered, recorded)
    partial = _has_partial(game_dir, name)         # half-placed: never kept, never adopted (audit-p). The pending
    # marker alone never blocks a deserved KEEP (audit-r L-a: a stale marker re-downloaded a complete pack).
    if not known or newer:
        if offered_ok and release_provenance and not partial and _is_release(game_dir, name, release_manifest) \
                and _provenance_ok(game_dir, name, release_provenance) and pack_intact(game_dir, name):
            return "adopt"
        return "update" if newer else "install"
    same = offered_ok and ver.normalise(offered) == ver.normalise(recorded)
    prov = _provenance_ok(game_dir, name, release_provenance) if same else True
    return "keep" if pack_intact(game_dir, name) and prov and not partial else "repair"


def _dir_size(d: Path) -> int:
    try:
        return sum(p.stat().st_size for p in Path(d).rglob("*") if p.is_file())
    except OSError:
        return 0


def _thinker_off_pin(game_dir: Path) -> bool:
    """A Thinker Mod in the folder that is not this release's pinned build (the manifest's fatal list applies)."""
    try:
        import thinker_flow
        state, _dll = thinker_flow.st.classify(Path(game_dir), thinker_flow.compiled_meta()["dll"])
        return state == thinker_flow.st.OFF_PIN
    except Exception:  # noqa: BLE001 - a probe: when in doubt, the manifest is worth fetching
        return True


def _split_ok(info) -> bool:
    """The manifest entry is a split pack (manifest.module_parts) whose parts are usable."""
    import manifest as mfmod
    try:
        return mfmod.module_parts(info) is not None
    except mfmod.PartsError:
        return False


def module_catalogue(game_dir: Path, args) -> tuple:
    """What optional modules this run could install, and how big each is.

    Returns (catalogue, manifest). catalogue: name -> {"size": bytes, "source": "local" |
    "manifest", "on_disk": bool, ["path": Path]}. "local" is a pack folder inside this payload
    (a checkout); "manifest" is a download the signed release manifest offers. manifest is
    (raw, sig, doc) when one was fetched and verified, else None.

    The manifest is fetched only when the answer can matter -- someone is at the keyboard, or
    the command line names a pack -- and with the quick single-attempt profile, so an offline
    player waits seconds, not minutes. A failure lists nothing and says so in one line: the
    packs can always be added later from the game's own update prompt.
    """
    import manifest as mfmod
    catalogue = {}
    pack = Path(args.pack) if getattr(args, "pack", None) else default_pack()
    if pack.is_dir() and any(pack.glob("*.mp4")):
        catalogue["movies-hd"] = {"size": _dir_size(pack), "source": "local", "path": pack,
                                  "version": ver.module_version("movies-hd")}
    ppack = Path(args.portrait_pack) if getattr(args, "portrait_pack", None) else default_portrait_pack()
    if ppack.is_dir() and any(ppack.glob("*.png")):
        catalogue["portraits-hd"] = {"size": _dir_size(ppack), "source": "local", "path": ppack,
                                     "version": ver.module_version("portraits-hd")}

    # Fetched whenever the answer can matter (verifications 2026-11-15), console or not: a console run (asked or
    # --no-prompt), --no-prompt anywhere ("installs every module on offer"), and any run with a Thinker Mod that is
    # not the pinned build: the manifest's fatal list decides whether it may be kept. Without it, --keep-thinker
    # beside a build the manifest marks fatal installed whenever no console was attached (--no-wait,
    # LONGEVITY_NO_WAIT, an unattended run). --keep-thinker alone fetches nothing: with no off-pin Thinker there is
    # nothing for it to keep (and every scripted run that passes it would reach for the network).
    interactive = args.ai == "ask" and (ix.has_console() or bool(getattr(args, "no_prompt", False)))
    # ... and whenever a pack the player chose is not complete (a .partial or the pending marker): an unattended or
    # NUL-stdin run completes it too, so it needs the manifest (audit-q M2).
    need = (bool(args.modules) or interactive or (args.ai == "on" and "movies-hd" not in catalogue)
            or _thinker_off_pin(game_dir) or any(pending_allowed(game_dir, n) for n in GAME_CONTENT_MODULES))
    manifest = None
    if need:
        try:
            raw, sig = fetch_manifest(game_dir, args.manifest, args.offline, quick=True)
            doc = mfmod.load_verified(raw, sig, allow_env=_local_manifest(args.manifest))
            manifest = (raw, sig, doc)
            mods = doc.get("modules") if isinstance(doc.get("modules"), dict) else {}
            for name in GAME_CONTENT_MODULES:
                info = mods.get(name)
                if name in catalogue or not isinstance(info, dict):
                    continue
                size = info.get("size")
                # A split entry is offered only when the preflight will accept its parts (a `url` beside them is
                # malformed there too); any other entry needs its `url`.
                fetchable = _split_ok(info) if "parts" in info else isinstance(info.get("url"), str)
                if mfmod.size_ok(size) and size > 0 and fetchable:
                    v = info.get("version")
                    catalogue[name] = {"size": int(size), "source": "manifest",
                                       "version": ver.normalise(v) if isinstance(v, str) and ver.is_valid(v) else None}
        except ix.InstallerError as e:
            ix.say(f"Optional modules could not be listed: {e.message.rstrip('.')}. "
                   "You can add them later from the game's update prompt.")
        except mfmod.ManifestError:
            discard_staged_manifest(game_dir)     # unverified: never left in staging (verification of f076f34)
            ix.say("Optional modules could not be listed: the update information did not verify. "
                   "You can add them later from the game's update prompt.")
    for name in catalogue:
        catalogue[name]["on_disk"] = pack_on_disk(game_dir, name)
        catalogue[name]["installed"] = _manifest_readable(game_dir, name)      # its own manifest (audit-t ROOT 1)
        catalogue[name]["release_manifest"] = release_manifest_sha256(catalogue[name], name)
        catalogue[name]["release_provenance"] = release_provenance_sha256(catalogue[name], name)
    import receipt as rc
    receipt = rc.read(game_dir)
    for name in catalogue:
        # Locked (ticked, cannot be unticked) ONLY when this run will keep it (audit-n 2026-11-17): a pack it would
        # install, update or repair stays the player's choice, and unticking it skips it, as before.
        c = catalogue[name]
        c["locked"] = pack_action(game_dir, name, c.get("version"), rc.module_version(receipt, name),
                                  c.get("release_manifest"), c.get("release_provenance")) in ("keep", "adopt")
        if _interrupted_update(game_dir, name):
            c["locked"] = True                   # completing it is the only consistent state (audit-t ROOT 3, M3)
    # A decline the game recorded ends the pack's pending state at the start of the run (audit-s: what we placed of it
    # goes, so a later "Reset Skipped Updates" finds nothing to install). With the verified manifest in hand, a marker
    # entry for a pack no longer on offer is dropped (audit-r L-c: unattended runs fetched the manifest for it forever).
    for n in GAME_CONTENT_MODULES:
        if pack_pending(game_dir, n) and _pack_declined(game_dir, n) and not _interrupted_update(game_dir, n):
            end_pending(game_dir, n)
            if n in catalogue:
                catalogue[n]["on_disk"] = pack_on_disk(game_dir, n)
                catalogue[n]["installed"] = _manifest_readable(game_dir, n)
    _mark_pending(game_dir, [n for n in pending_packs(game_dir) if manifest is not None and n not in catalogue], False)
    return catalogue, manifest


def choose_modules(catalogue: dict, args, game_dir: Path) -> list:
    """Which optional modules to install (pick_modules without the declines)."""
    return pick_modules(catalogue, args, game_dir)[0]


def pick_modules(catalogue: dict, args, game_dir: Path) -> tuple:
    """(the optional modules to install, the ones the player turned down, the ones the player
    ticked in the list -- [] when no list was shown).

    Flags decide without asking (`--modules a,b`, `--ai on|off`, `--no-prompt`); otherwise the
    player ticks packs in a list and the installer WAITS for Confirm -- an install must not run
    past this point on its own (user, 2026-09-27). Turned down = shown in the list and left
    unticked, or `--ai off` for the HD Cinematics: the install records each as the game's
    "Don't ask me again" (user 2026-11-01). Nothing is turned down when nobody chose: an
    unattended run, `--no-prompt`, a pack already on disk.
    """
    global _UNTICKED
    _UNTICKED = []                                   # no list, no untick (set below when one is shown)
    names = [n for n in GAME_CONTENT_MODULES if n in catalogue]
    if args.modules:
        wanted = validate_module_names(args.modules, game_dir)
        missing = [n for n in wanted if n not in catalogue]
        if missing:
            shown = ", ".join(_pack_label(n) for n in missing)
            raise ix.InstallerError(
                f"{shown} {'is' if len(missing) == 1 else 'are'} not available for download "
                "right now.", code=ix.EXIT_ABORTED, changed=False,
                remedy="run the installer without --modules; the pack can be added later from "
                       "the game's update prompt.")
        return wanted, [], []
    if args.ai == "on":
        return (["movies-hd"] if "movies-hd" in catalogue else []), [], []
    if args.ai == "off":
        # Not read from the catalogue: --ai off never fetches the manifest.
        # Installed (its manifest): never declined; anything else -- a half-placed pack too (audit-r MEDIUM-1), or files
        # without a list (audit-t ROOT 1) -- is turned down. The flag goes off either way (cinematics_flag).
        return [], ([] if _manifest_readable(game_dir, "movies-hd") else ["movies-hd"]), []
    if not names:
        return [], [], []
    import receipt as rc
    declines = rc.declined(game_dir)
    rerun = _lv_recorded(game_dir)
    ticked = {n: _starts_ticked(n, catalogue, game_dir, declines, rerun) for n in names}
    if getattr(args, "no_prompt", False):
        # The PLAYER's --no-prompt (only --update workers get the bootstrap's): nothing asked, and
        # the list taken as it would start (user 2026-11-01) -- every module on a first install;
        # on a re-run a pack the player said no to stays out (a default here once reversed an
        # opt-out, see below).
        chosen = [n for n in names if ticked[n]]
        ix.say("Selected: " + (", ".join(_pack_label(n) for n in chosen) if chosen else "none")
               + " (--no-prompt)")
        return chosen, [], []
    if not ix.can_ask():
        # Unattended: a first install takes the headline pack, a re-run keeps the earlier choice
        # (set_ini_flag runs every time, and a hardcoded default here once reversed an opt-out).
        # On a re-run, only a pack the player already has (user rule 2026-11-17: never a new pack by default).
        state = ini_flag_state(game_dir, "UpscaledVideos")
        take = (state is None or state) and "movies-hd" in names \
            and (not rerun or _pack_installed(catalogue["movies-hd"], game_dir, "movies-hd"))
        # ... and any pack whose placing an earlier run did not finish (its .partial): completed (audit-p MEDIUM-1)
        return [n for n in names if (n == "movies-hd" and take) or pending_allowed(game_dir, n)], [], []

    chosen = _tick_picker(names, catalogue, ticked)
    ix.say("Selected: " + (", ".join(_pack_label(n) for n in chosen) if chosen else "none"))
    # Turned down: ONLY a pack the player explicitly unticked -- it started ticked and was toggled off (decision for
    # the user, 2026-11-17; on a first install too since audit-t's fuzz re-run, F018): one that merely started
    # unticked -- the re-run default, or the Cinematics with UpscaledVideos=0 kept across an uninstall -- and was left
    # so records nothing new, and the game's update prompt still offers it. Existing declines stay as they are. An
    # installed pack never is.
    down = [n for n in names if n not in chosen and not _pack_installed(catalogue[n], game_dir, n) and ticked[n]]
    _UNTICKED = [n for n in names if ticked[n] and n not in chosen]     # every explicit untick, installed ones too
    return chosen, down, chosen


#: The packs the player unticked in this run's list -- started ticked, left unticked -- installed ones included
#: (audit-t): an untick of the installed Cinematics switches UpscaledVideos off, and an installed pack's pending update
#: is no longer pending. Set by pick_modules; [] when no list was shown.
_UNTICKED: list = []


def unticked_packs() -> list:
    return list(_UNTICKED)


def record_module_choice(game_dir: Path, wanted: list, turned_down: list) -> None:
    """A pack turned down at install time is declined exactly as the game's "Don't ask me again"
    on its offer declines it (`new:<id>:*`): hidden from the update prompt, undone by Preferences'
    "Reset Skipped Updates", void under check_report's reset rule. A pack in `wanted` -- ticked
    by the player, or installed by this run -- forgets any earlier decline; one a flag or an
    unattended run merely tried and failed to fetch keeps it. Written after the install, never
    before (a cancelled install changes nothing); a failed write only means the game asks
    again. Never raises."""
    try:
        import receipt as rc
        for n in turned_down:
            # an explicit untick (or --ai off) ends a pending pack: what we placed goes, nothing stays pending (audit-s)
            if pack_pending(game_dir, n):
                end_pending(game_dir, n)
        for n in turned_down:
            rc.decline(game_dir, NEW_PACK_PREFIX + n, rc.DECLINE_ANY)
        for n in wanted:
            rc.forget_decline(game_dir, NEW_PACK_PREFIX + n)
    except Exception:  # noqa: BLE001 - bookkeeping must not fail a finished install
        pass


def record_choices_now(game_dir: Path, args, catalogue: dict, chosen: list, turned_down: list,
                       ticked_now: list) -> None:
    """The answers to the list (or what the flags decided), recorded the moment they are given -- before the patch,
    the Thinker question and every later step (audit-t ROOT 2: a run killed or cancelled in that window lost them, and
    a stale decline still recorded mid-run made the next run end a pack the player had just ticked). Each one is the
    player's latest word, so it stands whatever happens to the rest of the run:
      * a yes (ticked in the list, or named by --modules / --ai on) forgets an earlier decline of the pack;
      * a no (turned down) ends its pending state (end_pending) and records the decline;
      * an untick of an INSTALLED pack ends its pending update -- no decline, no file touched; it stays at its version
        and the game's update prompt offers the update later (audit-t ROOT 3, M2);
      * every pack this run will place is marked pending (place_packs marks it again), so a run stopped before it
        landed leaves it chosen.
    record_module_choice repeats the decline bookkeeping at the end (idempotent).

    Over an existing install (a re-run) at once. A first install holds them until the exe is patched
    (apply_pending_choices, beside the update-check answer): stopped or failed before that it still changes nothing on
    disk (its verdict says so) and the next run asks the same list again; from the patch on, a kill while placing the
    packs keeps the player's answers (audit-t fuzz F002/F024). The Cinematics flag is recorded with the answer too.
    Never raises."""
    global _PENDING_CHOICES
    if not _lv_recorded(game_dir):
        # A first install: held until the exe is patched (apply_pending_choices), where the update-check answer is
        # written for the same reason -- before that every stop still changes nothing (audit-t F002/F024).
        _PENDING_CHOICES = (args, catalogue, list(chosen), list(turned_down), list(ticked_now), unticked_packs())
        return
    _PENDING_CHOICES = None
    _record_choices(game_dir, args, catalogue, chosen, turned_down, ticked_now, unticked_packs())


#: A first install's answers, held by record_choices_now until the exe is patched (apply_pending_choices).
_PENDING_CHOICES = None


def apply_pending_choices(game_dir: Path) -> None:
    """The moment a first install has patched the exe: record the answers it held (record_choices_now). Never raises."""
    global _PENDING_CHOICES
    held, _PENDING_CHOICES = _PENDING_CHOICES, None
    if held is not None:
        _record_choices(game_dir, *held)


def _record_choices(game_dir: Path, args, catalogue: dict, chosen: list, turned_down: list, ticked_now: list,
                    unticked: list) -> None:
    import receipt as rc
    try:
        yes = set(ticked_now) | (set(chosen) if (getattr(args, "modules", None) or args.ai == "on") else set())
        # The Cinematics flag with the answer (audit-t: a run that later completes the pack changes nothing).
        if "movies-hd" in yes:
            set_ini_flag(game_dir, True)
        elif args.ai == "off" or "movies-hd" in turned_down or "movies-hd" in unticked:
            set_ini_flag(game_dir, False)
        for n in yes:
            rc.forget_decline(game_dir, NEW_PACK_PREFIX + n)
        for n in turned_down:
            if pack_pending(game_dir, n):
                end_pending(game_dir, n)
            rc.decline(game_dir, NEW_PACK_PREFIX + n, rc.DECLINE_ANY)
        for n in unticked:
            if n not in turned_down and _pack_installed(catalogue.get(n, {}), game_dir, n) \
                    and not _has_partial(game_dir, n):
                _mark_pending(game_dir, [n], False)
        state = rc.read(game_dir)
        todo = [n for n in chosen if n in catalogue and pack_action(
            game_dir, n, catalogue[n].get("version"), rc.module_version(state, n),
            catalogue[n].get("release_manifest"), catalogue[n].get("release_provenance")) not in ("keep", "adopt")]
        _mark_pending(game_dir, todo, True)
    except Exception:  # noqa: BLE001 - bookkeeping: the end of the run records it again
        pass


def _lv_recorded(game_dir: Path) -> bool:
    """Longevity Vaccine is already installed here: its receipt is in the folder (a re-install or an update, not a
    first install). A part-finished uninstall that kept the receipt counts too."""
    import receipt as rc
    try:
        state = rc.read(game_dir)
        return bool(state.get("target_id") or state.get("modules"))
    except Exception:  # noqa: BLE001 - unreadable: treated as a first install (the list as it always started)
        return False


def _starts_ticked(name: str, catalogue: dict, game_dir: Path, declines: dict, rerun: bool = False) -> bool:
    """Ticked unless the player said no before (user 2026-11-01: everything on a first run).
    No = "Don't ask me again" on the pack's offer (in game or by an earlier unticked install), or
    the HD Cinematics switched off. A pack already on disk is always ticked. On a re-run over an
    existing install (`rerun`), a pack the player does not have starts unticked, whatever the
    declines say (user rule 2026-11-17: never a new pack by default for a player who already has
    Longevity Vaccine). A pack the player chose whose download or placing did not finish (audit-q) is
    ticked too -- unless anything says no: a recorded decline, or a first install (audit-r)."""
    if _pack_installed(catalogue[name], game_dir, name):
        return True
    if NEW_PACK_PREFIX + name in declines:
        return False                  # the player's latest "no" beats pending state (audit-r HIGH-1)
    if pending_allowed(game_dir, name):
        return True
    if rerun:
        return False
    return not (name == "movies-hd" and ini_flag_state(game_dir, "UpscaledVideos") is False)


#: The DeclinedUpdates item for a pack the player does not have (update_core.h writes
#: `new:<id>:*` for "Don't ask me again" on a NEW pack's offer; check_report reads it).
NEW_PACK_PREFIX = "new:"


class _KeyEventRecord(ctypes.Structure):
    _fields_ = [("bKeyDown", ctypes.c_int), ("wRepeatCount", ctypes.c_ushort),
                ("wVirtualKeyCode", ctypes.c_ushort), ("wVirtualScanCode", ctypes.c_ushort),
                ("uChar", ctypes.c_wchar), ("dwControlKeyState", ctypes.c_ulong)]


class _InputRecord(ctypes.Structure):
    class _Event(ctypes.Union):
        _fields_ = [("KeyEvent", _KeyEventRecord), ("_size", ctypes.c_byte * 16)]
    _fields_ = [("EventType", ctypes.c_ushort), ("Event", _Event)]


_K32 = None


def _poll_key():
    """The next key PRESS waiting in the console's input buffer, as (virtual-key code, character),
    or None when nothing is waiting; never blocks. Read as the console's own key records, not
    through msvcrt.getwch: getwch hands out an arrow as "\\xe0" and its second code only on the
    NEXT call, so an arrow cannot be told from a typed a-grave (2026-11-03: every arrow was read
    as one and ignored, in a plain Command Prompt). The record says VK_UP outright."""
    global _K32
    if _K32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.GetStdHandle.restype = ctypes.c_void_p
        k.GetStdHandle.argtypes = [ctypes.c_ulong]
        k.GetNumberOfConsoleInputEvents.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        k.ReadConsoleInputW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_InputRecord), ctypes.c_ulong,
                                        ctypes.POINTER(ctypes.c_ulong)]
        _K32 = k
    h = _K32.GetStdHandle(ctypes.c_ulong(-10 & 0xFFFFFFFF))      # STD_INPUT_HANDLE
    n, rec = ctypes.c_ulong(), _InputRecord()
    while True:
        # A failing query is no console to read (stdin redirected from NUL passes isatty()): EOFError, never an
        # endless poll for a key nobody can press (verification of 9f2cb08, 2026-11-15).
        if not _K32.GetNumberOfConsoleInputEvents(h, ctypes.byref(n)):
            raise EOFError("the console's input cannot be read")
        if not n.value:
            return None
        if not _K32.ReadConsoleInputW(h, ctypes.byref(rec), 1, ctypes.byref(n)) or not n.value:
            return None
        e = rec.Event.KeyEvent
        if rec.EventType == 0x0001 and e.bKeyDown:            # KEY_EVENT, pressed (not released)
            return e.wVirtualKeyCode, e.uChar
    return None                                                 # mouse / focus / resize events: skipped


_VK_KEYS = {0x26: "up", 0x28: "down", 0x0D: "enter", 0x20: "space"}


def _read_key() -> str:
    """One key from the console: "up", "down", "enter", "space", or "" for any other key.
    Ctrl-C raises KeyboardInterrupt, as at every other prompt. No console on stdin raises
    EOFError: the console would be waited on for a key nobody can press (only a caller that
    skipped ix.can_ask() gets here -- a test that forgot to supply the keys)."""
    if not ix.stdin_is_console():
        raise EOFError("no console to read a key from")
    # Poll, never block: Python delivers a console Ctrl-C between bytecodes, so a blocking read
    # would hold the cancel back until the player pressed some other key.
    while True:
        key = _poll_key()
        if key is not None:
            break
        time.sleep(0.03)
    vk, ch = key
    if ch == "\x03":
        raise KeyboardInterrupt
    if ch == "\x1b":
        # A console with virtual-terminal input on hands an arrow over as text, ESC [ A / ESC O A,
        # one character per record. The rest follows within milliseconds; a lone ESC (the Esc
        # key) is no key of ours.
        seq = ""
        while len(seq) < 8:
            deadline, nxt = time.monotonic() + 0.05, _poll_key()
            while nxt is None and time.monotonic() < deadline:
                time.sleep(0.005)
                nxt = _poll_key()
            if nxt is None:
                break
            seq += nxt[1]
            if len(seq) > 1 and (seq[-1].isalpha() or seq[-1] == "~"):
                break
        return {"[A": "up", "OA": "up", "[B": "down", "OB": "down"}.get(seq, "")
    if vk in _VK_KEYS:
        return _VK_KEYS[vk]
    return {"\r": "enter", "\n": "enter", " ": "space"}.get(ch, "")


def _drop_typed_ahead() -> None:
    """Forget keys pressed before the list was drawn: an extra Enter at the folder prompt, typed
    while the manifest was fetched, would otherwise untick the first pack unseen. Never raises."""
    try:
        if ix.stdin_is_console():
            for _ in range(1000):
                if _poll_key() is None:
                    break
    except Exception:  # noqa: BLE001 - a key we could not drop only flips a box the player sees
        pass


def _picker_rows(names: list, catalogue: dict, ticked: dict, at: int) -> list:
    """The pick list as printed: a box per pack (green ticked, red not -- kept under the marker,
    which is plain on these rows: a whole-row green would look ticked, user 2026-11-15), then the
    row that ends the pick, green as a whole when selected like every other list: "Continue", or "Continue without optional modules" with nothing ticked (user wording
    2026-11-15: nothing is downloaded at this row; the downloads come after the game is patched)."""
    rows = []
    width = max([28] + [len(_pack_label(n)) + 1 for n in names])    # the size column lines up under every label
    for i, n in enumerate(names):
        c = catalogue[n]
        note = "   already installed" if c.get("on_disk") else ""   # user wording 2026-11-06
        box = "[X]" if ticked[n] else "[ ]"
        row = ix.painted(f"{box} {_pack_label(n):<{width}}{human_size(c['size']):>8}{note}",
                         "good" if ticked[n] else "bad")
        rows.append(ix.marked(row, i == at, whole_row=False))   # green = ticked here, so no whole-row green
    last = INSTALL_SELECTED if any(ticked[n] for n in names) else SKIP_MODULES
    rows.append(ix.marked(last, at == len(names)))
    return rows + [ix.RULE]                 # the block's closing rule, redrawn with the rows


INSTALL_SELECTED = "Continue"
SKIP_MODULES = "Continue without optional modules"


def _hint_holds(names: list, catalogue: dict) -> bool:
    """"Modules that are already installed stay ticked." is true of this list: at least one row says "already
    installed" (on_disk), and every such row is locked."""
    shown = [n for n in names if catalogue[n].get("on_disk")]
    return bool(shown) and all(catalogue[n].get("locked") for n in shown)


def _tick_picker(names: list, catalogue: dict, ticked: dict) -> list:
    """Up / Down move the marker, Enter (or Space) ticks or unticks the pack under it -- never an
    installed one (catalogue "locked"), which stays ticked (user 2026-11-17) -- and Enter
    on Confirm -- the last row -- ends the pick (user 2026-11-01). The marker starts on the first
    pack, never on Confirm: a reflex Enter (every earlier prompt trains Enter as "yes") then flips
    a box the player can see, instead of committing to gigabytes (audit 2026-09-27). Ctrl-C is NOT
    an answer: it propagates to run_guarded, which cancels with nothing changed."""
    ticked = dict(ticked)
    at = 0
    rows = _picker_rows(names, catalogue, ticked, at)
    _drop_typed_ahead()
    ix.ask_block("Choose the optional modules",
                 # user wording 2026-11-04. "Later": Preferences' "Reset Skipped Updates" makes the
                 # game's update prompt offer a pack left unticked here again.
                 ["Select which optional modules you would like to install. You can download these "
                  "later from the in-game preferences menu."]
                 # User-approved wording 2026-11-17: only when a module in the list is installed (locked), and
                 # (audit-o) only when EVERY row marked "already installed" is locked -- never beside one that unticks.
                 + (["Modules that are already installed stay ticked."]
                    if _hint_holds(names, catalogue) else []),
                 # User-approved wording 2026-11-16 (audit-j's unmarked lines).
                 rows, keys="Up/Down: move   Enter: tick or untick, or continue")
    while True:
        key = _read_key()
        if key == "up":
            at = max(0, at - 1)
        elif key == "down":
            at = min(len(names), at + 1)
        elif key in ("enter", "space") and at < len(names):
            if catalogue[names[at]].get("locked"):
                continue                      # an installed pack stays ticked (user 2026-11-17)
            ticked[names[at]] = not ticked[names[at]]
        elif key == "enter":
            return [n for n in names if ticked[n]]
        else:
            continue
        rows = ix.redraw(rows, _picker_rows(names, catalogue, ticked, at))


def cinematics_flag(chosen: list, game_dir: Path, args, offered: list = ()) -> bool:
    """[UIMod] UpscaledVideos: play the HD clips when they are present.

    Explicit choices only, never the files (audit-t ROOT 1): on when the pack was chosen (`chosen`: ticked, named by a
    flag, or placed by this run) or forced (`--ai on`); off for `--ai off` or a "no" (`offered`: turned down or
    unticked -- even over an installed pack: "don't play HD movies"). Otherwise -- the pack could not be listed, or
    nobody was asked -- a first install leaves it on (harmless without the clips, and they play the moment a later run
    adds them) and a re-run keeps the player's earlier choice.
    """
    if "movies-hd" in chosen or args.ai == "on":
        return True                    # (a pack named with --modules beside --ai off: the named pack wins, as before)
    if args.ai == "off" or "movies-hd" in offered:
        return False
    state = ini_flag_state(game_dir, "UpscaledVideos")
    return True if state is None else bool(state)


def banner() -> None:
    line = "=" * 60
    print(line)
    print("   LONGEVITY VACCINE")
    print("   UI Scaling + HD Cinematics for Sid Meier's Alpha Centauri")
    print(line)
    print(f"   version {ver.VERSION}")
    print(line)
    if any(a in ("--update", "--generation") for a in sys.argv[1:]):
        # Just the header: "This installer will patch ..." on an update read as a threat, and the
        # update flow says what it is doing line by line (waiting / updating / the verdict).
        # (--generation: the bootstrap's second generation, which has no --update on its line.)
        return
    # ix.say, not print: the blank line it ends with must count for ix.blank() (one, never two).
    ix.say("This installer will patch Alpha Centauri: Alien Crossfire with Longevity Vaccine. Your "
           "original game .exe will be backed up (.bak) and can be restored at any time.\n")


#: Modules whose payload belongs in the GAME directory, and the ONLY subtrees each may write to.
#: `base` is the installer's own payload and is handled by the bootstrap/self-update path, not
#: extracted over the game. The subtrees mirror release.py's MODULE_SPEC globs -- an optional pack
#: has no business writing anywhere else, least of all over the exe the commit phase just
#: verified.
MODULE_ROOTS = {
    "movies-hd": ("movies/hd",),
    # portraits\hd, NOT portraits: the player's own images live in portraits\ (and fill in whatever the pack
    # lacks), so the pack may never write (or prune) there.
    "portraits-hd": ("portraits/hd",),
}
#: Packs whose root folder they own outright, so an update removes files the new archive no longer carries.
PRUNED_MODULES = ("portraits-hd",)
GAME_CONTENT_MODULES = tuple(MODULE_ROOTS)

#: Player-facing names, COMPILED IN. The manifest carries ids only; a label is never read from it
#: (see manifest.py's trust boundary). These are what the game shows when it asks about a pack.
MODULE_LABELS = {
    "movies-hd": "Z2k Retro's HD Cinematics",
    "portraits-hd": "Turovetsky's HD Portrait Pack",
}
#: Names a pack was shown under before, still accepted by `--modules`: a 1.0.0 game or notice said "HD Cinematics".
_FORMER_LABELS = {
    "movies-hd": ("HD Cinematics",),
    "portraits-hd": ("Longevity HD Portrait Pack",),
}


def validate_module_names(spec: str, game_dir=None) -> list:
    """`--modules a,b` may only name modules this installer knows how to place.

    An unknown name used to be downloaded in full and then silently ignored by install_modules,
    which iterates GAME_CONTENT_MODULES: 1.3 GB of bandwidth for no message at all. Called by
    the bootstrap too, BEFORE it fetches anything -- otherwise a typo still cached the manifest,
    downloaded a whole new installer and swapped it in before install.py got to refuse.
    """
    table = "\n".join(f"    {n:<14} {MODULE_LABELS.get(n, n)}" for n in GAME_CONTENT_MODULES)
    heading = "  Extras this installer knows (some may not be released yet):\n"
    example = (f'"{launcher_path(game_dir)}" --update --modules {GAME_CONTENT_MODULES[0]}'
               if game_dir else f"--update --modules {GAME_CONTENT_MODULES[0]}")
    remedy = "run it again with one of the names above, for example:\n    " + example
    raw = [m.strip() for m in str(spec).split(",") if m.strip()]
    if not raw:
        raise ix.InstallerError(
            "--modules was given without saying which extra.", code=ix.EXIT_ABORTED,
            changed=False, detail=heading + table, remedy=remedy)
    # The short id, or the label a player will have read in the extras notice -- either way,
    # case does not matter.
    by_key = {n.lower(): n for n in GAME_CONTENT_MODULES}
    by_key.update({MODULE_LABELS[n].lower(): n for n in GAME_CONTENT_MODULES if n in MODULE_LABELS})
    by_key.update({old.lower(): n for n, olds in _FORMER_LABELS.items() for old in olds})
    names, bad = [], []
    for m in raw:
        hit = by_key.get(m.lower())
        (names if hit else bad).append(hit or m)
    if bad:
        shown = ", ".join('"' + "".join(ch for ch in b if 32 <= ord(ch) < 127)[:40] + '"'
                          for b in bad)
        raise ix.InstallerError(
            f"{shown} is not an extra this installer knows.",
            code=ix.EXIT_ABORTED, changed=False, detail=heading + table, remedy=remedy)
    return list(dict.fromkeys(names))


def human_size(n) -> str:
    import fetch as fetchmod
    return fetchmod.human_size(n)


def _pack_label(name: str) -> str:
    return MODULE_LABELS.get(name, name)


def launcher_path(game_dir) -> Path:
    """The run-install.bat a player can actually paste: the resident copy once installed, else
    this payload's own. A bare `run-install.bat` only works from the right folder in cmd."""
    try:
        import bootstrap as bsmod
        p = bsmod.updater_dir(Path(game_dir)) / "scripts" / "run-install.bat"
        if p.is_file():
            return p
        return payload_root() / "scripts" / "run-install.bat"
    except Exception:  # noqa: BLE001 - a path in a notice must not become a failure
        return Path("run-install.bat")


def _placed_last(member) -> int:
    """Sort key: a pack's PROVENANCE.txt, then its pack-manifest.json, after every other file (audit-o 2026-11-17: a
    copy stopped part-way left the NEW manifest -- entry 36 of 62 in the Cinematics archive -- beside OLD clips, and
    the next run judged the folder by it). Stable: everything else keeps its order."""
    name = Path(getattr(member, "filename", member)).name.lower()
    return {"provenance.txt": 1, "pack-manifest.json": 2}.get(name, 0)


def install_modules(game_dir: Path, staged: dict, versions: dict) -> dict:
    """Extract verified module archives into the game dir, skipping unchanged files.

    The archive as a whole was already sha256-verified against the SIGNED manifest, so integrity
    is settled; per-file CRC32 from the zip directory is then enough to decide what to skip, and
    it costs nothing to read. That is what turns "recopy 1.3 GB every run" into "copy what
    changed".

    Each module is isolated: one that fails does not abort the others, and does not roll back the
    core update that already succeeded.
    """
    import zipfile
    out = {}
    for name in GAME_CONTENT_MODULES:
        archive = staged.get(name)
        if not archive:
            continue
        ix.say(f"\n--- {_pack_label(name)} ---")
        copied = skipped = failed = 0
        files = []
        # The installed release's own list, read before the new one replaces it: an update of a pack whose folder is not
        # pruned wholesale removes the files the new release dropped -- only those still the old release's (audit-t M4).
        old_proofs = None
        if name not in PRUNED_MODULES and _manifest_readable(game_dir, name):
            old_proofs = _partial_proofs(Path(game_dir) / MODULE_ROOTS[name][0] / "pack-manifest.json")
        try:
            import preflight as pfm
            # One archive, or a split pack's parts read in place as that archive (preflight.open_staged).
            with pfm.open_staged(archive) as src, zipfile.ZipFile(src) as z:
                root = Path(game_dir).resolve()
                # The release's manifest as the .partial, before any file of the pack (audit-p 2026-11-17).
                want = f"{MODULE_ROOTS[name][0]}/pack-manifest.json".lower() if MODULE_ROOTS.get(name) else None
                head = next((i for i in z.infolist() if i.filename.replace("\\", "/").lower() == want), None)
                pack_root = Path(game_dir) / MODULE_ROOTS[name][0]
                import safe_fs
                if head is not None and not safe_fs.link_on_path(Path(game_dir), pack_root):
                    _write_partial(pack_root, z.read(head))      # never through a link (audit-q L1)
                for info in sorted(z.infolist(), key=_placed_last):
                    if info.is_dir():
                        continue
                    if Path(info.filename).name.lower() == "pack-manifest.json":
                        if failed:
                            continue  # its presence must mean every file before it is in place (audit-o)
                        if old_proofs:
                            # the old release's dropped files go BEFORE the new manifest replaces their proof
                            # (audit-t fuzz F006: a kill after the manifest left them orphaned for good)
                            _drop_old_files(game_dir, name, old_proofs, z)
                            old_proofs = None
                    dest = _contained(root, info.filename, MODULE_ROOTS.get(name, ()))
                    if dest is None:
                        # ZIP-SLIP. zipfile.extract() sanitises member names; z.open() plus a
                        # manual join does not. `game/"../../x"` escapes, and an ABSOLUTE member
                        # discards the game dir entirely -- so a member could land on another
                        # drive, or overwrite the exe we just committed. The archive is
                        # sha256-verified against a signed manifest, so this needs the signing
                        # key to weaponise, but the same bug fires on an ordinary packaging
                        # mistake, which is the likelier way to meet it.
                        failed += 1
                        ix.say(f"  REFUSED: {info.filename!r} is not somewhere {name} may write "
                               f"(allowed: {', '.join(MODULE_ROOTS.get(name, ())) or 'nothing'})")
                        continue
                    files.append(info.filename)
                    tmp = None
                    try:
                        if dest.is_file() and dest.stat().st_size == info.file_size \
                                and _crc32(dest) == info.CRC:
                            skipped += 1
                            continue
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        # A PRIVATE temp name, not `<dest>.part`. Two things went wrong with the
                        # obvious form: an archive carrying both `x.mp4` and `x.mp4.part` had one
                        # member destroy the other, and a player who already had a file called
                        # `x.mp4.part` (an interrupted download of their own) lost it. `.tmp-<pid>`
                        # is ours, is not a name anything else writes, and is swept below.
                        tmp = dest.with_name(dest.name + f".tmp-{os.getpid()}")
                        with z.open(info) as src, tmp.open("wb") as dst:
                            shutil.copyfileobj(src, dst, 1 << 20)
                        tmp.replace(dest)     # rename, so an interrupted copy is never mistaken
                        tmp = None            # for a complete file
                        copied += 1
                    except (OSError, zipfile.BadZipFile) as e:
                        failed += 1
                        ix.say(f"  WARNING: {info.filename}: {e}")
                    finally:
                        # Leave NOTHING behind. A half-written temp used to survive every failure
                        # -- so a player who ran out of disk part-way through the 1.3 GB pack was
                        # left with the wasted space still occupied, and re-running made another.
                        if tmp is not None:
                            try:
                                tmp.unlink(missing_ok=True)
                            except OSError:
                                pass
        except (zipfile.BadZipFile, OSError) as e:
            ix.say(f"  WARNING: {name} could not be read ({e}), so this module is skipped.")
            continue
        ix.say(f"  {copied} file{'s' if copied != 1 else ''} copied, {skipped} already current"
               + (f", {failed} FAILED" if failed else ""))
        if failed:
            ix.say(f"  {name} is incomplete; re-run the installer to finish it.")
            continue                                  # the .partial stays: the re-run completes the pack
        _drop_partial(Path(game_dir) / MODULE_ROOTS[name][0])
        _mark_pending(game_dir, [name], False)        # landed, by setup or the update route (audit-q M3)
        if name in PRUNED_MODULES:
            for rel in MODULE_ROOTS.get(name, ()):
                keep = {Path(m).name for m in files if Path(m).parent.as_posix().lower() == rel.lower()}
                pruned = prune_pack_dir(game_dir, rel, keep)
                if pruned:
                    ix.say(f"  removed {pruned} file{'s' if pruned != 1 else ''} the new pack no longer carries")
        if name == "portraits-hd":
            ix.say(PORTRAIT_ART_CREDIT)
        elif name == "movies-hd":
            ix.say(CINEMATICS_CREDIT)
        out[name] = {"version": versions.get(name, ver.UNKNOWN), "files": files}
        if _ON_LANDED is not None:
            _ON_LANDED(name, out[name])               # setup records it in the receipt at once (audit-t ROOT 4)
    return out


def _drop_old_files(game_dir: Path, name: str, old_proofs: dict, z) -> None:
    """An update of a pack whose folder is not pruned wholesale (the Cinematics): delete the files the installed
    release listed and the new archive no longer carries -- only those still that release's by size and sha256 (a file
    the player replaced stays). Run before the new manifest lands (audit-t M4, fuzz F006). Never raises."""
    import safe_fs
    rel = MODULE_ROOTS[name][0]
    carried = {Path(i.filename).name.lower() for i in z.infolist()
               if not i.is_dir() and Path(i.filename).parent.as_posix().lower() == rel.lower()}
    dropped = 0
    for n, (size, sha) in old_proofs.items():
        f = Path(game_dir) / rel / n
        try:
            if n.lower() not in carried and f.is_file() and not _is_link(f) and _matches(f, size, sha):
                safe_fs.unlink_entitled(f)
                dropped += 1
        except OSError:
            pass
    if dropped:
        ix.say(f"  removed {dropped} file{'s' if dropped != 1 else ''} the new pack no longer carries")


#: Set by place_packs while it downloads: called with (name, receipt entry) the moment a pack lands, so a run stopped
#: at a later question still has it in the receipt (audit-t ROOT 4). None otherwise (the update route writes the
#: receipt right after its own install_modules, before any question).
_ON_LANDED = None


def _record_landed(game_dir: Path, name: str, entry: dict, target_id=None) -> None:
    """A pack that has just landed, in the receipt now: its entry, and -- on a first install, where setup writes the
    receipt only at the end -- the base this run has already patched in (place_packs runs after the patch and the
    runtime files). Everything else the run has not done yet stays out. Never raises."""
    import receipt as rc
    try:
        state = rc.read(game_dir)
        mods = dict(state.get("modules") or {})
        mods[name] = dict(entry)
        mods.setdefault("base", {"version": ver.VERSION})
        rc.write(game_dir, target_id=state.get("target_id") or target_id, modules=mods, say=ix.warn)
    except Exception:  # noqa: BLE001 - the end of the run writes it again
        pass


#: Windows device names. Reserved at every directory level, with or without an extension.
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} \
    | {f"LPT{i}" for i in range(1, 10)}


def _contained(root: Path, member: str, allowed: tuple = ()):
    """Resolve an archive member under `root`, or None if it may not be written.

    Two separate refusals, because containment alone is not enough:

      * ESCAPE -- `..` traversal, absolute paths, drive-qualified paths, and anything that
        resolves outside the tree. Also a name whose final component is empty or `.`, which on
        Windows turns into a file where a directory belongs.
      * OUT OF SCOPE -- a member that is contained but lands somewhere the module has no business
        writing. `movies-hd` ships `movies/hd/*`; a member called `terranx_PRACX.exe` is perfectly
        contained and would overwrite the executable the commit phase JUST verified byte for byte
        -- as would `uimod.dll`, `terranx_PRACX.exe.bak`, or `Alpha Centauri.ini`. Each optional
        module is confined to the subtree it is packaged from (release.py's MODULE_SPEC globs).
    """
    name = str(member).replace("\\", "/").strip()
    if not name or name.endswith("/"):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    for p in parts:
        # Windows STRIPS trailing dots and spaces when it opens a path, so `".. "` and `"...."`
        # are `".."` to the filesystem while comparing unequal in Python. The open itself happens
        # to fail here, so nothing escaped -- but the mkdir above it still created undeletable
        # junk directories, and relying on an incidental open failure for a containment property
        # is not a guarantee.
        if p != p.rstrip(" ."):
            return None
        # Reserved DEVICE names. `NUL` can never be os.replace()d, so a module containing one
        # would report "incomplete; re-run the installer" forever and never record its version.
        if p.split(".")[0].upper() in _RESERVED_NAMES:
            return None
    if Path(name).is_absolute() or Path(name).drive or name.startswith("/"):
        return None
    if allowed:
        rel = "/".join(parts).lower()
        if not any(rel.startswith(a.lower().rstrip("/") + "/") for a in allowed):
            return None
    dest = (root / Path(*parts))
    try:
        resolved = dest.resolve()
    except OSError:
        return None
    if resolved != root and root not in resolved.parents:
        return None
    if allowed and not any(_inside_subtree(root, a, resolved) for a in allowed):
        # A junction or symlink at (or above) the module's subtree -- `portraits\hd` pointing at `portraits\` or the
        # game root -- would land a contained-looking member on the player's files or the exe.
        return None
    return dest


def _inside_subtree(root: Path, rel: str, resolved: Path) -> bool:
    """`resolved` lies under <root>/<rel>, and <root>/<rel> itself is where it says it is (no reparse point on the
    way: its resolved path equals the lexical one, case-insensitively as on Windows)."""
    lexical = Path(root) / Path(*[p for p in rel.split("/") if p])
    try:
        real = lexical.resolve()
    except OSError:
        return False
    if os.path.normcase(str(real)) != os.path.normcase(str(lexical)):
        return False
    r, x = os.path.normcase(str(resolved)), os.path.normcase(str(real))
    return r.startswith(x.rstrip("\\/") + os.sep)


def _crc32(p: Path, _buf: int = 1 << 20) -> int:
    import zlib
    crc = 0
    with Path(p).open("rb") as f:
        for chunk in iter(lambda: f.read(_buf), b""):
            crc = zlib.crc32(chunk, crc)
    return crc & 0xFFFFFFFF


def _local_manifest(source) -> bool:
    """True when --manifest names a local path rather than a URL.

    Anything that is not http(s) is treated as a path, which is what makes the error message for
    a typo'd path say "that file does not exist" instead of "refusing to fetch a schemeless URL".
    """
    return bool(source) and not str(source).lower().startswith(("http://", "https://"))


def _looks_like_url(source) -> bool:
    """A scheme-ish argument that is not http(s) -- a typo, most likely."""
    s = str(source or "")
    return "://" in s and not s.lower().startswith(("http://", "https://"))


def _resolve_local_manifest(src) -> Path:
    """The manifest file behind a local --manifest argument, or an explained abort.

    Accepts a DIRECTORY too, because `--manifest <the folder release.py wrote>` is the obvious
    thing to type; it used to fall through to the downloader and report "refusing to fetch a
    schemeless URL: C:\\...\\dist", which names neither the real problem nor the fix.
    """
    if _looks_like_url(src):
        raise ix.InstallerError(
            f"{src} is not a web address this installer can use.",
            code=ix.EXIT_ABORTED, changed=False,
            remedy="update manifests are fetched over https: check the address, or leave "
                   "--manifest off to use the normal update service.")
    p = Path(src)
    if p.is_dir():
        inner = p / "manifest.json"
        if inner.is_file():
            return inner
        raise ix.InstallerError(
            f"{p} is a folder with no manifest.json in it.",
            code=ix.EXIT_ABORTED, changed=False,
            remedy="point --manifest at the manifest.json file itself.")
    if p.is_file():
        return p
    raise ix.InstallerError(
        f"There is no update manifest at {p}.",
        code=ix.EXIT_ABORTED, changed=False,
        remedy="check the path, or leave --manifest off to use the normal update service.")


#: A manifest is a few KB; anything beyond this is not one.
MANIFEST_MAX_BYTES = 1 << 20


def fetch_manifest(game_dir: Path, source: str = None, offline: bool = False,
                   quick: bool = False, check: bool = False):
    """Return (raw_bytes, signature_hex). `source` may be a URL or a local path.

    `quick`: one attempt with a short timeout -- for `--check`, whose caller (the game) kills it
    after ~10 s anyway; the default 3 attempts x 30 s x two files took minutes on a black-holed
    network. `check`: this is --check itself, whose stderr (check.log) says where the manifest went; no other run
    prints those lines (audit-h L4: a setup run's quick fetch printed two of them)."""
    import fetch as fetchmod
    import manifest as mfmod
    import safe_fs
    link = None
    try:
        # Checked BEFORE staging_dir, which creates the folder -- through a link, outside the game folder.
        link = safe_fs.first_link(Path(game_dir), Path(game_dir) / "LongevityMods" / "staging")
        if link is not None:
            # Nothing is written through a link (audit-g LOW-8: --check exited 12 at every launch). The check uses
            # the per-user cache, as for a folder it cannot write; a full run says why it stops.
            if quick:
                raise OSError("a link on the way to the staging folder")
            raise ix.InstallerError(f"{link} is a link to another folder, so nothing was downloaded there.",
                                    code=ix.EXIT_ABORTED, changed=False)       # user-approved wording 2026-11-15
        staging = fetchmod.staging_dir(game_dir)
        fetchmod.assert_writable(staging)
    except OSError as e:
        if not quick:
            raise ix.InstallerError(
                "The game folder is not writable, so nothing can be downloaded into it.",
                code=ix.EXIT_ABORTED, changed=False, detail=f"  {e}",
                remedy="run the installer as administrator, or move the game out of Program "
                       "Files.")
        # The CHECK must keep working: cache the manifest where this user can always write.
        staging = fetchmod.fallback_cache_dir(game_dir)
        if check:                     # one line, and the true one: a link is not an unwritable folder (audit-h L4)
            # User-approved wording 2026-11-16 (audit-j's unmarked lines).
            print(f"--check: {link} is a link; caching the manifest under {staging}" if link is not None else
                  f"--check: {game_dir} is not writable; caching the manifest under {staging}", file=sys.stderr)
    m_dest, s_dest = staging / "manifest.json", staging / "manifest.json.sig"

    # An explicit LOCAL --manifest satisfies --offline: reading a file off the player's own disk
    # is not network access. Refusing it produced a message that contradicted itself -- "pass
    # --manifest <path>" said to someone who had just passed exactly that.
    if offline and _local_manifest(source):
        offline = False

    if offline:
        if not (m_dest.is_file() and s_dest.is_file()):
            raise ix.InstallerError(
                "--offline was given but there is no manifest in staging to use.",
                code=ix.EXIT_ABORTED, changed=False,
                remedy="run once without --offline, or pass --manifest <path>.")
    else:
        src = source or mfmod.MANIFEST_URL
        local = _resolve_local_manifest(src) if _local_manifest(source) else None
        try:
            if local is not None:                   # a local path, for testing
                shutil.copy2(local, m_dest)
                sig_src = Path(str(local) + ".sig")
                if not sig_src.is_file():
                    # The manifest is ALREADY in staging by this point, and --offline prefers
                    # whatever is cached there. Leaving an unverified one behind is exactly
                    # what discard_staged_manifest exists to prevent.
                    discard_staged_manifest(game_dir)
                    raise ix.InstallerError(
                        f"no signature beside {local.name}.",
                        code=ix.EXIT_ABORTED, changed=False,
                        remedy=f"put {sig_src.name} next to it.")
                shutil.copy2(sig_src, s_dest)
            else:
                sig_url = source + ".sig" if source else mfmod.SIGNATURE_URL
                # A manifest is a few KB. Without a cap the CDN (or any host it redirected
                # to) could stream 4 GiB into staging on every launch, or trickle bytes to
                # hold the hidden check process open forever.
                kw = {"max_bytes": MANIFEST_MAX_BYTES}
                if quick:
                    import time as _t
                    kw.update(timeout=8, max_attempts=1, deadline=_t.monotonic() + 20)
                # Never RESUME a manifest. A 1 MiB `.part` left by one oversized response made
                # every later hidden check send `Range: bytes=1048576-`, get 416/206 from the CDN
                # and fail -- update checks silently dead for good (offline audit 2026-09-27). In
                # a full run a `.part` of an OLDER manifest resumed into the new one fails the
                # signature once for no reason. A manifest is a few KB: always start clean.
                in_game = _under(Path(game_dir), m_dest)
                if in_game:
                    kw["root"] = Path(game_dir)       # never through a link (safe_fs, via fetch.download)
                for p in (m_dest, s_dest):
                    _unlink_where(Path(game_dir), p.with_suffix(p.suffix + ".part"))
                fetchmod.download(src, m_dest, label="manifest", **kw)
                fetchmod.download(sig_url, s_dest, label="signature", **kw)
        except fetchmod.LinkError as e:
            # A link on the way into the game folder: not a connection problem (audit-g LOW-1). The approved line
            # alone, uncut; nothing was downloaded.
            raise ix.InstallerError(str(e), code=ix.EXIT_ABORTED, changed=False) from e
        except fetchmod.FetchError as e:
            # Whatever landed (a manifest without its .sig, a .part) is unverified: never leave it
            # for --offline or the next check to trip over.
            discard_staged_manifest(game_dir)
            # The technical reason goes to stderr for a developer reading a log; the player gets
            # one plain sentence and one thing to do (the URL/errno soup read as a fault of theirs).
            if quick:
                print(f"  ({e})", file=sys.stderr)
            # The reason travels with the error in BOTH paths: a bug report from an interactive update
            # used to carry only "check your connection" (a certificate problem on an old Windows
            # looks exactly like no connection to the player).
            raise ix.InstallerError(
                "Could not reach the update server.",
                code=ix.EXIT_ABORTED, title="UPDATE FAILED", detail=f"  ({fetchmod.clean(e)})",
                disk_note="Check your connection and try again later. If it keeps happening, the message above "
                          "says why (a certificate problem means Windows is missing the server's certificate authority).")
        except OSError as e:
            discard_staged_manifest(game_dir)
            raise ix.InstallerError("Could not read the update information.", code=ix.EXIT_ABORTED,
                                    title="UPDATE FAILED", detail=f"  {e}",
                                    disk_note="Check your connection and try again later.")
    try:
        # Inside the try: a non-ASCII .sig raised UnicodeDecodeError out of here into the CRASH
        # handler ("this is a bug in the installer"), and -- because the bad pair stays cached in
        # staging -- every subsequent --offline run crashed the same way, permanently.
        return m_dest.read_bytes(), s_dest.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as e:
        discard_staged_manifest(game_dir)
        raise ix.InstallerError(
            "The update information could not be read.",
            code=ix.EXIT_ABORTED, detail=f"  {e}", changed=False,
            remedy="try again; if it keeps happening, download the installer by hand.")


def _under(root: Path, p: Path) -> bool:
    try:
        Path(p).relative_to(root)
        return True
    except ValueError:
        return False


def _unlink_where(game_dir: Path, p: Path) -> None:
    """Remove p: in the game folder never through a link (safe_fs); elsewhere (the per-user fallback cache in
    %LOCALAPPDATA%) a plain unlink. Raises OSError for a file that cannot be removed."""
    import safe_fs
    if _under(game_dir, p):
        safe_fs.unlink(game_dir, p)
    else:
        Path(p).unlink(missing_ok=True)


def discard_staged_manifest(game_dir: Path) -> None:
    """Remove an unverified manifest from staging. Never raises.

    An unverified manifest must not persist in the game folder: it is attacker-supplied by
    definition, --offline prefers whatever is cached, and leaving it there made the installer
    tell the user "Nothing on disk was changed" while a tampered file sat in their install.
    """
    try:
        import fetch as fetchmod
        places = []
        try:
            places.append(fetchmod.staging_dir(game_dir))
        except OSError:
            pass
        places.append(fetchmod.fallback_cache_dir(game_dir))   # --check's read-only fallback
        # The .part files too: an abandoned partial was resumed by the next run with a Range
        # request, so a refused download was never really discarded.
        for staging in places:
            for name in ("manifest.json", "manifest.json.sig",
                         "manifest.json.part", "manifest.json.sig.part"):
                _unlink_where(Path(game_dir), staging / name)
    except Exception:  # noqa: BLE001
        pass


#: How long an update launched FROM the game waits for the game to finish exiting. The exe and
#: every DLL are held open until it does; starting the preflight a second early produced a
#: "terranx_PRACX.exe is in use" refusal for the player who had just clicked "update".
GAME_EXIT_WAIT = 90

#: The last line of every success verdict (printed by print_play_note; its own line on purpose).
ENJOY_LINE = "Open the game and enjoy playing Alpha Centauri!"

# ---------------------------------------------------------------- which exe to run + the desktop shortcut
#
# A player who installs over GOG's copy has several executables and a Play button that all start
# the game WITHOUT the mod. Every success verdict therefore ends by naming the one to run, and the
# installer offers a desktop shortcut to it when none exists (user, 2026-09-27).

#: A shortcut's name IS its file name, and Windows forbids ':' in file names -- "SMACX: Longevity"
#: (the first choice) cannot exist on a desktop. Also < > " / \ | ? *.
MOD_SHORTCUT_NAME = "SMACX Longevity"
_SHORTCUT_NAME = None          # the shortcut the verdict may name (found or just created)
_NOTE_ARGS = None              # (game_dir, target_id) once an install/update succeeded
_THINKER_NEW = False           # this run installed Thinker Mod in a folder that had none (B): no "as before"


def mod_exe(game_dir: Path, target_id) -> Path:
    """The program the player starts to play with the mod: the target's launcher when it has one
    (thinker.exe injects Thinker into terranx.exe; starting terranx.exe itself would skip Thinker),
    else its own exe, else the first configured candidate that exists. None when nothing is there."""
    names = []
    spec = _targets().get(target_id) if target_id else None
    if spec is not None and getattr(spec, "launcher", None):
        names.append(spec.launcher)
    if spec is not None and getattr(spec, "exe", None):
        names.append(spec.exe)
    names += _exe_names()
    for n in names:
        if n and (Path(game_dir) / n).is_file():
            return Path(game_dir) / n
    return None


def _desktop_dirs() -> list:
    """The player's Desktop, then the Public Desktop. LONGEVITY_DESKTOP_DIRS (os.pathsep-joined)
    overrides both -- tests use it so nothing ever touches a real desktop."""
    env = os.environ.get("LONGEVITY_DESKTOP_DIRS")
    if env:
        return [Path(p) for p in env.split(os.pathsep) if p]
    # SHGetFolderPathW (XP-era), not PowerShell: a stock Windows 7 has PowerShell 2.0 on .NET 3.5, where
    # [Environment]::GetFolderPath('CommonDesktopDirectory') does not exist (.NET 4) -- the whole snippet failed,
    # the list came back empty, and every run asked for a shortcut and then said "could not find your desktop".
    out = []
    try:
        shell32 = ctypes.windll.shell32
        for csidl in (0x0010, 0x0019):            # CSIDL_DESKTOPDIRECTORY, CSIDL_COMMON_DESKTOPDIRECTORY
            buf = ctypes.create_unicode_buffer(260)
            if shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0 and buf.value:
                out.append(Path(buf.value))
    except (AttributeError, OSError):
        pass
    return out


def _ps(script: str) -> str:
    """Run a PowerShell snippet hidden; its stdout, or "" on any failure."""
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-Command", script], capture_output=True, text=True, timeout=60,
                           creationflags=flags, stdin=subprocess.DEVNULL)
        return p.stdout if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""


def _ps_quote(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def list_shortcuts() -> list:
    """[(name, target)] for every .lnk on the desktop dirs (name without .lnk)."""
    dirs = _desktop_dirs()
    if not dirs:
        return []
    script = ("$sh = New-Object -ComObject WScript.Shell; foreach ($d in @(" +
              ", ".join(_ps_quote(d) for d in dirs) + ")) { Get-ChildItem -LiteralPath $d -Filter *.lnk "
              "-ErrorAction SilentlyContinue | ForEach-Object { $s = $sh.CreateShortcut($_.FullName); "
              "Write-Output ($_.BaseName + '|' + $s.TargetPath) } }")
    out = []
    for line in _ps(script).splitlines():
        name, sep, target = line.partition("|")
        if sep:
            out.append((name, target.strip()))
    return out


def find_shortcut_to(exe: Path):
    """The name of a desktop shortcut whose target is `exe`, else None."""
    want = str(Path(exe)).lower()
    for name, target in list_shortcuts():
        if target.lower() == want:
            return name
    return None


def shortcut_icon(game_dir: Path, target_id, exe: Path) -> Path:
    """The file whose icon the desktop shortcut shows: the GAME's exe, never a launcher's. A Thinker
    folder's shortcut starts thinker.exe, whose icon is a plain "Mod" square (user 2026-11-06: use
    the game's own art); the exe it launches (the target's `exe`, terranx.exe) carries the game's
    icon, as every PRACX build does. The target itself when it is the game exe or that file is gone."""
    spec = _targets().get(target_id) if target_id else None
    if spec is not None and getattr(spec, "launcher", None) and getattr(spec, "exe", None):
        game_exe = Path(game_dir) / spec.exe
        if game_exe.is_file():
            return game_exe
    return Path(exe)


def refresh_shortcut_icon(name: str, exe: Path, icon: Path) -> bool:
    """An existing shortcut of OURS (MOD_SHORTCUT_NAME) keeps the icon it was made with; when the
    icon rule changes (2026-11-06: the game's, not the launcher's) it is brought up to date, quietly,
    provided it still starts `exe`. Never a shortcut the player made (another name). True when
    changed. Never raises."""
    want = str(icon) + ",0"
    try:
        for d in _desktop_dirs():
            lnk = d / (name + ".lnk")
            if not lnk.is_file():
                continue
            out = _ps("$sh = New-Object -ComObject WScript.Shell; $s = $sh.CreateShortcut(" + _ps_quote(lnk) + "); "
                      "if ($s.TargetPath -eq " + _ps_quote(exe) + " -and $s.IconLocation -ne " + _ps_quote(want) + ") "
                      "{ $s.IconLocation = " + _ps_quote(want) + "; $s.Save(); Write-Output 'refreshed' } "
                      "else { Write-Output 'kept' }")
            return "refreshed" in out
    except Exception:  # noqa: BLE001 - cosmetic; never fails an install
        pass
    return False


def create_shortcut(lnk: Path, exe: Path, icon: Path = None) -> str:
    """Write `lnk` starting `exe` from its own folder, with `icon`'s icon (default: `exe`'s own).
    "" on success, else why."""
    icon = Path(icon) if icon is not None else Path(exe)
    script = ("$sh = New-Object -ComObject WScript.Shell; $s = $sh.CreateShortcut(" + _ps_quote(lnk) + "); "
              "$s.TargetPath = " + _ps_quote(exe) + "; $s.WorkingDirectory = " + _ps_quote(Path(exe).parent) + "; "
              "$s.IconLocation = " + _ps_quote(str(icon) + ",0") + "; $s.Save(); Write-Output 'saved'")
    out = _ps(script)
    if "saved" in out and Path(lnk).is_file():
        return ""
    return "the shortcut could not be written to the desktop"


def check_desktop_shortcut(game_dir: Path, target_id, ask: bool = True) -> None:
    """Stop and offer a desktop shortcut to the mod's exe when the player has none. Never raises."""
    global _SHORTCUT_NAME
    try:
        exe = mod_exe(game_dir, target_id)
        if exe is None:
            return
        found = find_shortcut_to(exe)
        if found:
            _SHORTCUT_NAME = found
            if found == MOD_SHORTCUT_NAME:
                refresh_shortcut_icon(found, exe, shortcut_icon(game_dir, target_id, exe))
            return
        none_line = "You do not have a desktop shortcut that starts the game with Longevity Vaccine."
        if not ix.can_ask() or not ask:
            ix.blank()                    # one empty line, never a second after the thinker.ini note (audit-i LOW-1)
            ix.say(none_line)
            ix.say(f"Run the installer again to create one, or start {exe.name} from the game folder.")
            return
        # ONE question (user-approved 2026-11-15): the desktop folder is found first, so a shortcut of our name that
        # starts something else is the replace question itself -- no second "Replace it?" stop.
        dirs = _desktop_dirs()
        lnk = dirs[0] / (MOD_SHORTCUT_NAME + ".lnk") if dirs else None
        exists = lnk is not None and lnk.exists()
        if exists:
            note = f'A desktop shortcut named "{MOD_SHORTCUT_NAME}" already exists but starts something else.'
            make = f'Replace "{MOD_SHORTCUT_NAME}" with a shortcut that starts Longevity Vaccine'
        else:
            note, make = none_line, f'Create the "{MOD_SHORTCUT_NAME}" shortcut on your desktop'
        try:
            pick = ix.arrow_choice("Desktop shortcut", [note], [make, "Don't create a shortcut"])
        except (EOFError, KeyboardInterrupt):
            pick = 1
        if pick != 0:
            ix.say(f"Left as it is. Start {exe.name} from the game folder to play with Longevity Vaccine." if exists
                   else f"No shortcut created. Start {exe.name} from the game folder to play with Longevity Vaccine.")
            return
        if lnk is None:
            ix.warn(f"Could not find your desktop folder. Start {exe.name} from the game folder to play with Longevity Vaccine.")
            return
        why = create_shortcut(lnk, exe, shortcut_icon(game_dir, target_id, exe))
        if why:
            ix.warn(f"Could not create the shortcut ({why}). Start {exe.name} from the game folder to play with Longevity Vaccine.")
            return
        _SHORTCUT_NAME = MOD_SHORTCUT_NAME
        ix.say(f'Created "{MOD_SHORTCUT_NAME}" on your desktop.')
    except Exception as e:  # noqa: BLE001 - never fail a finished install over a shortcut
        ix.say(f"(desktop shortcut check skipped: {e})")


#: The Longevity Vaccine version this run brought up from an OLDER installed one (the receipt's base before the run),
#: else None: only then does "See what's new" close the verdict. Set by note_whats_new at the three places that know
#: both versions (do_update, _install_rest, bootstrap._run_installer); never by a repair or --fix-thinker.
_WHATS_NEW = None


def note_whats_new(before, now) -> None:
    """Arm the "See what's new" line when `before` (the receipt's base version before this run) is a real version
    and `now` is newer: an update, or an install over an older install. A fresh install (no receipt, UNKNOWN), a
    same-version re-run and a downgrade leave it unarmed."""
    global _WHATS_NEW
    import version as v                               # stdlib-only; the bootstrap calls this outside main()
    if v.is_valid(before) and v.normalise(before) != v.UNKNOWN and v.is_valid(now) and v.is_newer(now, before):
        _WHATS_NEW = v.normalise(now)


#: The version a run that brings Longevity Vaccine up started from, kept from just before the receipt says the new
#: one until the run's verdict: a run that fails after the receipt write (a disk error, a Ctrl-C) still ends its
#: retry with "See what's new" (audit-g LOW-3). LongevityMods\, never through a link.
WHATS_NEW_FILE = "whats-new-from.txt"


def _whats_new_path(game_dir: Path) -> Path:
    return Path(game_dir) / "LongevityMods" / WHATS_NEW_FILE


def remember_whats_new(game_dir: Path, before, now) -> None:
    """Just before the receipt is rewritten: keep "<before>|<now>" when `now` is newer (note_whats_new's rule) -- the
    version the run started from AND the one it is installing, so only the retry of this very run can use it (audit-h
    M2). Never raises."""
    import version as v
    import safe_fs
    if not (v.is_valid(before) and v.normalise(before) != v.UNKNOWN and v.is_valid(now) and v.is_newer(now, before)):
        return
    p = _whats_new_path(game_dir)
    try:
        if safe_fs.link_on_path(Path(game_dir), p.parent):
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{v.normalise(before)}|{v.normalise(now)}", encoding="ascii")
    except OSError:
        pass


def finish_whats_new(game_dir: Path, before, now) -> None:
    """Every successful run that installs or finds Longevity Vaccine current (audit-h M2, L1): arm "See what's new" when
    the version the run STARTED from is older than `now`, and delete the kept file whatever it says. The start is
    `before` (the receipt's base when this run began) unless the file was kept by the run that wrote that very receipt
    -- its "to" is both `before` and `now`, so this run is that run's retry -- and then the file's "from". Never the
    file alone: a fresh install (`before` UNKNOWN), a downgrade, another version's or a planted file, garbage or UTF-16
    arm nothing. Never raises."""
    import version as v
    import safe_fs
    start = before
    p = _whats_new_path(game_dir)
    try:
        if not safe_fs.link_on_path(Path(game_dir), p) and p.is_file():
            try:
                frm, to = p.read_bytes()[:64].decode("ascii").strip().split("|")
            except (UnicodeDecodeError, ValueError):
                frm = to = None
            if (v.is_valid(frm) and v.is_valid(to) and v.is_valid(before) and v.is_valid(now)
                    and v.normalise(to) == v.normalise(before) == v.normalise(now)):
                start = frm
            safe_fs.unlink(Path(game_dir), p)
    except OSError:
        pass
    note_whats_new(start, now)


def forget_whats_new(game_dir: Path) -> None:
    """Uninstall: a kept version describes an install that is going (audit-h M2, W02). Never raises."""
    import safe_fs
    try:
        safe_fs.unlink(Path(game_dir), _whats_new_path(game_dir))
    except OSError:
        pass


def whats_new_line(version: str) -> str:
    """User-approved wording (2026-11-15). "(Ctrl-click to open)" only in Windows Terminal (WT_SESSION set): the old
    console window does not open links."""
    import manifest as mfmod
    tail = " (Ctrl-click to open)" if os.environ.get("WT_SESSION") else ""
    return f"See what's new in Longevity Vaccine {version}: {ix.painted(mfmod.CHANGELOG_URL, 'keys')}{tail}"


def _say_whats_new() -> None:
    if _WHATS_NEW:
        ix.say(whats_new_line(_WHATS_NEW))


def _success_after() -> None:
    """run_guarded's closing lines of a success verdict: the play note; or, for a verdict without one (ALREADY UP TO
    DATE), the armed "See what's new" line alone (audit-h L1: the retry of an update that failed past its receipt)."""
    if _NOTE_ARGS:
        print_play_note(*_NOTE_ARGS)
    else:
        _say_whats_new()


def print_play_note(game_dir: Path, target_id) -> None:
    """The closing lines of every success verdict: which exe carries the mod, and the shortcut. After an update
    from an older version, "See what's new" is the very last line, before any closing question."""
    import thinker_flow
    # The thinker.ini choice, then CL, nothing between (user 2026-11-16): before the early return below
    thinker_flow.offer_closing(game_dir, _PROCESS_START)
    exe = mod_exe(game_dir, target_id)
    if exe is None:
        ix.good(ENJOY_LINE)
        _say_whats_new()
        return
    spec = _targets().get(target_id) if target_id else None
    if spec is not None and getattr(spec, "launcher", None) and exe.name.lower() == spec.launcher.lower():
        # A launcher configuration (Thinker): the patched exe IS terranx.exe, and the launcher
        # is what adds Thinker on top. "terranx.exe starts the unmodified game" would be wrong
        # here on both counts.
        # "as before" only when the player already started the game through it (user 2026-11-15: not after this
        # run installed Thinker Mod).
        ix.good(f"To play with Longevity Vaccine, start {exe.name}." if _THINKER_NEW else
                f"To play with Longevity Vaccine, start {exe.name} as before.")
        # GOG's own entries never start Thinker: its Play button starts terran.exe (SMAC, no mod),
        # "SMAX PRACX" terranx_PRACX.exe (no mod), "Alien Crossfire" terranx.exe -- here the mod
        # without Thinker (audit 2026-11-01, read from goggame-*.info and GOG's shortcuts).
        ix.warn(f"The GOG Galaxy Play button and the shortcuts GOG created do not start Thinker: some start the game without Longevity Vaccine, and starting {spec.exe} directly plays with Longevity Vaccine but without Thinker.")
    elif target_id == "pracx":
        ix.good(f"To play with Longevity Vaccine, start {exe.name}.")
        # Name only the stock exes that are NOT the one carrying the mod: a PRACX exe named
        # terranx.exe (Thinker's naming, or Thinker removed again) must not be called unmodified
        # in the next breath (audit 2026-10-29).
        others = [n for n in ("terranx.exe", "terran.exe") if n.lower() != exe.name.lower()]
        ix.warn("The GOG Galaxy Play button, the shortcuts GOG created" +
                ("".join(f", {n}" for n in others) if others else "") +
                (" all" if others else "") + " start the unmodified game, without Longevity Vaccine.")
    else:
        ix.good(f"To play with Longevity Vaccine, start {exe.name}.")
        ix.warn("The GOG Galaxy Play button and the shortcuts GOG created may start a different "
                "executable, without Longevity Vaccine.")
    name = _SHORTCUT_NAME or find_shortcut_to(exe)
    if name:
        ix.say(f'Your desktop shortcut "{name}" starts the right one.')
    ix.good(ENJOY_LINE)
    _say_whats_new()

#: --check's wall deadline (seconds), enforced by a watchdog thread in check_main. Above the
#: fetch's 8 s socket / 20 s read deadline, below the game's 30 s kill (update.cpp kDeadlineMs).
CHECK_WALL_SECONDS = 24


# ---- one installer at a time -----------------------------------------------------------------
# Two installers on one game folder interleave their writes: an unfinished update is completed by
# the next run, so a generation 2 still installing a pack and an update the player accepts from
# the game meanwhile used to run side by side over the same exe, staging folder and receipt.
#
# A NAMED MUTEX, not a lock file. The OS releases it when the holder dies however it dies (a
# crash, a closed console, Task Manager) -- the next installer then sees it ABANDONED and simply
# takes it, so nothing stale can block for ever. It lives in no folder an uninstall deletes, and
# it is named after the game folder's on-disk identity (volume serial + file index), so a
# junction, a subst drive or a different spelling of the same folder still finds the same lock.
#
# A process the holder runs and WAITS ON (the bootstrap's install.py worker) cannot own the same
# mutex -- ownership is per thread -- so the holder lends it: it also holds a second, private
# mutex named by a random token and passes the token in INSTALL_LOCK_ENV. A child that finds the
# lock taken proceeds only if that private mutex still exists, i.e. only while the holder that
# issued the token is alive -- and it queues a thread on the real lock at once, so if the holder
# is killed while the child still works, the abandoned lock passes to the CHILD, never to a new
# installer. The token is consumed on use, so nothing the child starts inherits it.
INSTALL_LOCK_ENV = "LONGEVITY_INSTALL_LOCK"
#: Everyone may wait on and release the lock, at a LOW integrity label: an installer elevated by
#: UAC and the game's own (medium) updater must see one lock, not "access denied" for each other.
_LOCK_SDDL = "D:(A;;0x00100001;;;WD)S:(ML;;NW;;;LW)"
_LOCK_ACCESS = 0x00100001             # SYNCHRONIZE | MUTEX_MODIFY_STATE
_HELD_LOCKS: dict = {}
_WAIT_TIMEOUT = 0x102


class InstallerLock:
    def __init__(self, name: str, handle=None, lent=None, delegated: bool = False, heir=None):
        self.name, self._handle, self._lent, self.delegated = name, handle, lent, delegated
        self._heir = heir                 # (thread, stop event) of a delegated child

    def child_env(self, env: dict) -> dict:
        """`env` for a child this process will WAIT for, carrying the lent lock."""
        env = dict(env)
        if self._lent:
            env[INSTALL_LOCK_ENV] = self._lent[0]
        return env

    def release(self) -> None:
        if _HELD_LOCKS.get(self.name) is not self:
            return
        del _HELD_LOCKS[self.name]
        k32 = _lock_kernel32()
        if self._heir:
            k32.SetEvent(self._heir[1])   # the heir thread releases what it may have inherited
            self._heir[0].join(timeout=5)
            if not self._heir[0].is_alive():
                k32.CloseHandle(self._heir[1])
        for h in (self._handle, self._lent[1] if self._lent else None):
            if h:
                k32.ReleaseMutex(h)
                k32.CloseHandle(h)
        self._handle = self._lent = self._heir = None


def _lock_kernel32():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    from ctypes import wintypes as wt
    k32.CreateMutexExW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, wt.DWORD, wt.DWORD]
    k32.CreateMutexExW.restype = wt.HANDLE
    k32.OpenMutexW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
    k32.OpenMutexW.restype = wt.HANDLE
    k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
    k32.WaitForSingleObject.restype = wt.DWORD
    k32.WaitForMultipleObjects.argtypes = [wt.DWORD, ctypes.POINTER(wt.HANDLE), wt.BOOL, wt.DWORD]
    k32.WaitForMultipleObjects.restype = wt.DWORD
    k32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
    k32.CreateEventW.restype = wt.HANDLE
    k32.SetEvent.argtypes = [wt.HANDLE]
    k32.ReleaseMutex.argtypes = [wt.HANDLE]
    k32.CloseHandle.argtypes = [wt.HANDLE]
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    return k32


def installer_lock_name(game_dir: Path) -> str:
    """The lock's name for this game folder: its identity on disk, not its spelling."""
    try:
        st = os.stat(game_dir)
        if st.st_ino:
            return f"Global\\LongevityVaccineInstaller-{st.st_dev:x}-{st.st_ino:x}"
    except OSError:
        pass
    # A filesystem with no file index (some network shares): the resolved, case-folded path.
    try:
        key = str(Path(game_dir).resolve())
    except (OSError, ValueError):
        key = os.path.abspath(str(game_dir))
    return ("Global\\LongevityVaccineInstaller-"
            + hashlib.sha256(os.path.normcase(key).casefold().encode("utf-8")).hexdigest()[:32])


def _lock_attributes(k32):
    """A SECURITY_ATTRIBUTES for _LOCK_SDDL, or None (the default) if it cannot be built."""
    from ctypes import wintypes as wt

    class SA(ctypes.Structure):
        _fields_ = [("nLength", wt.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                    ("bInheritHandle", wt.BOOL)]
    try:
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        conv = adv.ConvertStringSecurityDescriptorToSecurityDescriptorW
        conv.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        conv.restype = wt.BOOL
        sd = ctypes.c_void_p()
        if not conv(_LOCK_SDDL, 1, ctypes.byref(sd), None):
            return None, None
    except (OSError, AttributeError):
        return None, None
    return SA(ctypes.sizeof(SA), sd, False), sd


def _open_mutex(k32, name: str):
    """A handle to the named mutex (created if absent), or None if a FOREIGN object squats the
    name and refuses us (ERROR_ACCESS_DENIED: ours always grants _LOCK_ACCESS)."""
    sa, sd = _lock_attributes(k32)
    try:
        # Only the rights _LOCK_SDDL grants. CreateMutexW asks for MUTEX_ALL_ACCESS, which that
        # descriptor refuses on an EXISTING mutex -- every contender then saw "access denied"
        # and never waited at all.
        h = k32.CreateMutexExW(ctypes.byref(sa) if sa else None, name, 0, _LOCK_ACCESS)
        err = ctypes.get_last_error()
    finally:
        if sd:
            k32.LocalFree(sd)
    if not h:
        if err == 5:
            return None
        raise OSError(err, f"CreateMutexExW failed ({err})")
    return h


def _create_mutex(k32, name: str, keep_waiting=None):
    """(handle, owned). Not owned = someone else holds it (or squats its name).

    `keep_waiting()`: while it returns True, wait for a held mutex instead of giving up."""
    h = _open_mutex(k32, name)
    if h is None:
        return None, False
    rc = k32.WaitForSingleObject(h, 0)
    while rc == _WAIT_TIMEOUT and keep_waiting and keep_waiting():
        rc = k32.WaitForSingleObject(h, 250)
    if rc in (0, 0x80):                                 # WAIT_OBJECT_0, WAIT_ABANDONED
        return h, True
    err = ctypes.get_last_error()
    k32.CloseHandle(h)
    if rc == _WAIT_TIMEOUT:
        return None, False
    raise OSError(err, "WaitForSingleObject failed on the installer lock")


def _lent_by_live_holder(k32, name: str) -> bool:
    """True if INSTALL_LOCK_ENV names a lock lent by a holder that is still running. Consumed."""
    token = os.environ.pop(INSTALL_LOCK_ENV, "")
    if not re.fullmatch(r"[0-9a-f]{32}", token or ""):
        return False
    h = k32.OpenMutexW(0x00100000, False, f"{name}-lent-{token}")     # SYNCHRONIZE
    if not h:
        return False
    k32.CloseHandle(h)
    return True


def _queue_heir(k32, name: str):
    """A daemon thread queued on the real lock: it takes the lock over if the lending holder dies
    while this (delegated) process is still working. Returns (thread, stop event handle).

    ONE uninterrupted wait on [lock, stop]: a thread that waited in slices was not queued between
    them, and a new installer's Wait(0) could take the abandoned lock in that gap (audit: 1 in 80
    kills with a busy worker). Queued, it is handed the lock atomically on abandonment."""
    import threading
    from ctypes import wintypes as wt
    h = _open_mutex(k32, name)
    stop = k32.CreateEventW(None, True, False, None)
    if not stop:
        raise OSError(ctypes.get_last_error(), "CreateEventW failed")

    def heir():
        if h is None:
            return
        try:
            both = (wt.HANDLE * 2)(h, stop)
            if k32.WaitForMultipleObjects(2, both, False, 0xFFFFFFFF) in (0, 0x80):
                k32.WaitForSingleObject(stop, 0xFFFFFFFF)     # owned: hold it until release()
                k32.ReleaseMutex(h)
        finally:
            k32.CloseHandle(h)
    t = threading.Thread(target=heir, name="installer-lock-heir", daemon=True)
    t.start()
    return t, stop


def installer_running(game_dir: Path) -> bool:
    """True if another process holds this game folder's installer lock right now. Never waits,
    never raises: --check uses it to stay out of a running installer's way."""
    if os.name != "nt":
        return False
    try:
        k32 = _lock_kernel32()
        h = _open_mutex(k32, installer_lock_name(game_dir))
        if h is None:
            return False
        try:
            rc = k32.WaitForSingleObject(h, 0)
            if rc in (0, 0x80):
                k32.ReleaseMutex(h)
            return rc == _WAIT_TIMEOUT
        finally:
            k32.CloseHandle(h)
    except OSError:
        return False


def hold_installer_lock(game_dir: Path, wait_for=None, wait_s: int = 60) -> InstallerLock:
    """Take the one-installer-at-a-time lock for `game_dir`, or refuse with nothing changed.

    `wait_for`: a PID that holds the lock now and is about to exit (generation 1, for its
    generation 2). The lock is waited for while that process lives, up to `wait_s`; a lock
    that is still held after it has gone belongs to someone else, and is refused like any other.
    Taking it again in a process that already holds it returns a view whose release() is a
    no-op: only the first taker lets go.
    """
    if os.name != "nt":
        return InstallerLock("")
    name = installer_lock_name(game_dir)
    if name in _HELD_LOCKS:
        return InstallerLock(name, lent=_HELD_LOCKS[name]._lent)
    h = None
    try:
        k32 = _lock_kernel32()
        h, owned = _create_mutex(k32, name)
        if not owned and wait_for:
            # Wait ON THE MUTEX while that process lives, and a little after: Windows reports a
            # process as exited a moment before it abandons the mutexes it owned, so one retry
            # after "it has gone" could still find the lock held (seen under load).
            import time
            import preflight as pfm
            deadline, gone, waited = time.monotonic() + wait_s, [None], [False]

            def keep_waiting():
                waited[0] = True              # (not reached for a name squatted by a stranger)
                now = time.monotonic()
                if gone[0] is None and not pfm._pid_alive(int(wait_for)):
                    gone[0] = now
                return now < deadline and (gone[0] is None or now - gone[0] < 3)
            h, owned = _create_mutex(k32, name, keep_waiting)
            if not owned and waited[0] and gone[0] is None:
                raise ix.InstallerError(
                    "The previous installer did not exit, so this one stopped rather than run "
                    "alongside it.", code=ix.EXIT_ABORTED, changed=False,
                    remedy="close any other installer window and run it again.")
        if not owned:
            if _lent_by_live_holder(k32, name):
                lock = _HELD_LOCKS[name] = InstallerLock(name, delegated=True,
                                                         heir=_queue_heir(k32, name))
                return lock
            raise ix.InstallerError(
                "Another Longevity Vaccine installer is already working on this game, so this "
                "one stopped without changing anything.",
                code=ix.EXIT_ABORTED, changed=False, title="INSTALLER ALREADY RUNNING",
                remedy="let the other installer window finish, or close it if it is waiting for "
                       "you to press Enter (an update the game started runs in its own window), "
                       "then run this again.")
    except OSError as e:
        # The lock guards against an accident; it must never be the reason an install fails.
        if h:
            k32.ReleaseMutex(h)
            k32.CloseHandle(h)
        ix.say(f"  (could not take the one-installer-at-a-time lock: {e}; continuing without it)")
        return InstallerLock(name)
    token = os.urandom(16).hex()     # not `secrets`: the trimmed runtime does not ship it
    try:
        lent, _ = _create_mutex(k32, f"{name}-lent-{token}")
        if not lent:
            raise OSError(0, "the lending mutex was refused")
    except OSError as e:
        # Holding a lock we cannot lend would refuse our OWN worker as "another installer" --
        # an update that can never run. Fail open instead, like any other lock failure.
        k32.ReleaseMutex(h)
        k32.CloseHandle(h)
        ix.say(f"  (could not take the one-installer-at-a-time lock: {e}; continuing without it)")
        return InstallerLock(name)
    lock = InstallerLock(name, h, (token, lent))
    _HELD_LOCKS[name] = lock
    return lock


def wait_for_game(pid) -> None:
    """Block until `pid` (the game that launched us) has exited, or refuse."""
    if not pid:
        return
    import bootstrap as bsmod
    ix.say("\nWaiting for Alpha Centauri to close.")
    if not bsmod._wait_for_pid(int(pid), timeout=GAME_EXIT_WAIT):
        raise ix.InstallerError(
            "Alpha Centauri is still running, so the update did not start.",
            code=ix.EXIT_ABORTED, title="UPDATE NOT STARTED",
            disk_note="Close the game, then start it again: it will offer the update again.")
    ix.say("Updating...")


def do_update(game_dir: Path, args) -> int:
    """Manifest-driven update. Preflight everything, then commit transactionally."""
    import preflight as pfm
    import receipt as rc
    import transact as tx
    import manifest as mfmod

    import thinker_flow
    check_companion_declarations()
    wait_for_game(getattr(args, "wait_pid", None))
    state = rc.read(game_dir)
    _recover_thinker(game_dir, state)
    installed = rc.installed_modules(state)     # (the version is in the header; the packs show in the preflight)

    # EXPLICIT `--modules` is fetched as named (it doubles as the repair path for a pack);
    # otherwise the preflight fetches exactly the installed modules the manifest says are stale.
    explicit = validate_module_names(args.modules, game_dir) if args.modules else None
    # The game's hand-off: the packs its popups named and the player accepted, and ONLY those
    # (none without --modules). The base is still brought current -- the bootstrap runs the newest
    # installer by nature, and the game always lists the core when it is stale.
    only_listed = bool(getattr(args, "only_listed", False))
    installed_modules = {n: rc.module_version(state, n)
                         for n in installed if n in GAME_CONTENT_MODULES}
    base_version = rc.module_version(state, "base")

    raw, sig = fetch_manifest(game_dir, args.manifest, args.offline)
    # NOTE: LastUpdateCheck is recorded at the END, not here. Writing it before the preflight put
    # a write to Alpha Centauri.ini inside the phase that is documented as touching no game file
    # -- and it is wrong on its own terms: a check that failed verification is not a check that
    # happened, and recording it would suppress the next one.

    # Choose the exe by the RECEIPT's target, not by config.exe_name().
    #
    # `work\game-exe.txt` is machine-specific and correctly not shipped, so from a resident
    # updater config.exe_name() falls back to the default "terranx.exe" -- which exists on every
    # stock Planetary Pack install. `target.is_file()` was therefore true, the fallback never ran,
    # and the update aborted with "unrecognised base binary": the in-game update button was dead
    # in the one configuration players actually use.
    target = None
    tid = state.get("target_id")
    tbl = _targets()
    if tid and tid in tbl and tbl[tid].exe and (game_dir / tbl[tid].exe).is_file():
        target = game_dir / tbl[tid].exe
        pass                                  # the receipt's target; no need to say so
    if target is None:
        target = next((game_dir / n for n in _exe_names() if (game_dir / n).is_file()), None)
    if target is None:
        raise ix.InstallerError(
            "No Alpha Centauri executable was found to update.",
            code=ix.EXIT_NO_GAME, detail=f"Searched: {game_dir}", changed=False,
            remedy="check that --game-dir points at the folder containing the game.")
    rec = _read_setup(game_dir)
    if rec.get("original_md5") and target.name.lower() == str(rec.get("exe", "")).lower() \
            and _md5_or_none(target) == rec["original_md5"]:
        # A folder set up for Thinker whose original terranx.exe is back (GOG's "verify files"):
        # the preflight would refuse it as "a binary we did not make", which is true and useless.
        raise ix.InstallerError(
            f"The game's original {target.name} is back in this folder, so the update did not start.",
            code=ix.EXIT_ABORTED, changed=False,
            detail="  GOG Galaxy may have restored it while checking the game's files.",
            remedy=("run the installer again (INSTALL.bat in the download; download it again if you no longer have it)"
                    + (" to set the folder up for Thinker again"
                       if _thinker_overlay() is not None and _thinker_here(game_dir, _thinker_overlay()) else "")
                    + "; the game's update prompt then works again."))

    ix.say("")
    pf = pfm.run(game_dir=game_dir, target=target,
                 patches=Path(ap.DEFAULT_PATCHES), table=_targets(),
                 manifest_raw=raw, manifest_sig=sig,
                 installed_version=base_version,
                 receipt_target_id=state.get("target_id"),
                 wanted_modules=explicit, installed_modules=installed_modules,
                 only_listed=only_listed,
                 game_pid=getattr(args, "wait_pid", None),
                 public_key_hex=None, labels=MODULE_LABELS,
                 # file:// URLs are a TEST affordance and are enabled only when the operator
                 # pointed --manifest at something local. Hardcoding True in the production path
                 # meant a signed manifest could name `file:///...` module URLs and the installer
                 # would read them -- turning the signed document into a local-file reader for no
                 # reason anyone shipping needs.
                 allow_file=_local_manifest(args.manifest))
    pf.report(say=ix.say)

    if not pf.ok:
        # Leave nothing unverified behind, so "your install is untouched" is literally true.
        if any("signature" in c.name or "manifest" in c.name for c in pf.blockers):
            discard_staged_manifest(game_dir)
        unreleased = [c.name[:-len(": not released yet")] for c in pf.blockers
                      if c.name.endswith(": not released yet")]
        if unreleased and len(unreleased) == len(pf.blockers):
            # The generic "not everything checked out ... fix the items above" was wrong here:
            # nothing is broken and a retry fails identically.
            names = " and ".join(unreleased)
            raise ix.InstallerError(
                f"{names} {'is' if len(unreleased) == 1 else 'are'} not available for download "
                "yet. Nothing was downloaded or changed.",
                code=ix.EXIT_ABORTED, changed=False,
                remedy=f"nothing to do now; your game is fine. Run --update again after a "
                       f"release that includes {names}.")
        raise ix.InstallerError(
            "The installer stopped before changing anything, because not everything it needs "
            "checked out.",
            code=ix.EXIT_ABORTED,
            detail="\n".join(f"  - {c.name}: {c.detail}" for c in pf.blockers)
                   + "\n\nYour game files are exactly as they were. Anything already downloaded is "
                     "kept under LongevityMods\\staging so a retry does not fetch it again; that "
                     "folder is safe to delete.",
            changed=False,
            remedy="fix the items above and run it again; your game is untouched.")

    # `--modules` names specific modules, and a module's version is independent of the product
    # version, so "the product is current" is not an answer to "install movies-hd". Without the
    # exemption, `run-install.bat --update --modules movies-hd` -- the command
    # offer_optional_modules prints verbatim -- did nothing at all once the base was current.
    global _VERDICT
    base_stale = not ver.is_valid(base_version) or base_version == ver.UNKNOWN or (
        pf.decision is not None and pf.decision.version is not None
        and ver.is_newer(pf.decision.version, base_version))
    # --only-listed: stale packs the game's popups did not name stay as they are (the preflight
    # said so above, one line each) -- never "up to date", and never fetched.
    left = [n for n in (pf.decision.modules if pf.decision is not None else [])
            if n not in pf.wanted] if only_listed else []
    if pf.decision is not None and (
            (pf.decision.action == mfmod.NOTHING and not args.modules)
            or (only_listed and not pf.wanted and not base_stale)):
        ix.say("\nAlready up to date. Nothing needs updating." if not left else
               "\nNothing the game listed needs updating.")
        for n in sorted(installed_modules):
            if n not in left:
                ix.say(f"  {_pack_label(n)}: up to date (v{installed_modules[n]})")
        rc.note_check(game_dir)      # a completed check, even though there was nothing to apply
        if not ix.is_worker():
            # The retry of an update that failed past its receipt write finds nothing to do (audit-h L1, W21): its
            # verdict still ends with "See what's new", and the kept file goes. A worker leaves it to the bootstrap.
            finish_whats_new(game_dir, base_version, base_version)
        # A GOG / Heroic file check may have put DDrawCompat back since the install (or, on Windows, a Linux
        # install of the same folder set it aside). bootstrap.py's own "already current" branch does the same.
        ddraw_status = wine_ddrawcompat(game_dir)
        # A player who is current is exactly the one who has not heard about a new pack: the
        # notice used to be reachable only as a side effect of a base update.
        offer_optional_modules(game_dir, pf.doc, installed, args)
        body = ("Everything you have installed is current. Nothing was changed." if not left else
                "Nothing was changed: nothing listed for this update needed it. "
                + " and ".join(_pack_label(n) for n in left)
                + (" has" if len(left) == 1 else " have")
                + " a newer version that was not part of this update; it was left as it is.")
        if ddraw_status in ("moved", "restored", "dropped"):
            body = body.replace("Nothing was changed", "Nothing else was changed (ddraw.dll: see above)")
        _VERDICT = ("ALREADY UP TO DATE",
                    body + ("  An optional extra is available (see \"optional extras\" above)."
                            if announced_modules(game_dir, pf.doc, installed) else ""))
        return ix.EXIT_OK
    wanted = list(pf.wanted)
    for n in sorted(installed_modules):
        if n not in wanted and n not in left:
            ix.say(f"  {_pack_label(n)}: up to date (v{installed_modules[n]}), no download needed")

    # A pack that failed to download is only ADVISORY in the preflight (an extras problem must
    # not block the core patch). But when the pack IS the update -- the base is current and
    # nothing else is stale -- committing anyway re-patched the exe, wrote the receipt and said
    # "UPDATE COMPLETE" about an update that had not happened.
    not_staged = [n for n in wanted if n not in pf.staged]

    def _offered(n):
        info = (pf.doc.get("modules") or {}).get(n)
        v = info.get("version") if isinstance(info, dict) else None
        return ver.normalise(v) if isinstance(v, str) and ver.is_valid(v) else None

    def _pack_failure(n) -> tuple:
        """("The update to <label> v1.1.0 could not be downloaded. <label> v1.0.0 ...", detail). No article
        or "Your" before the label: "Turovetsky's HD Portrait Pack" takes neither (audit 2026-11-06)."""
        label, offered, have = _pack_label(n), _offered(n), installed_modules.get(n)
        what = f"{label} v{offered}" if offered else label
        if have and have != ver.UNKNOWN:
            msg = (f"The update to {what} could not be downloaded. {label} v{have} "
                   f"{'are' if label.endswith('s') else 'is'} still installed and "
                   f"{'work' if label.endswith('s') else 'works'} as before.")
        else:
            msg = f"{what} could not be downloaded."
        why = next((c.detail for c in pf.warnings if c.name.startswith(label)), "")
        return msg, f"  - {label}: {why or 'see the line marked above'}"

    if not_staged and not base_stale:
        msgs, details = zip(*(_pack_failure(n) for n in not_staged))
        raise ix.InstallerError(
            " ".join(msgs) + " Nothing was changed.",
            code=ix.EXIT_ABORTED, changed=False, detail="\n".join(details),
            remedy="check your connection and run it again; anything already downloaded is "
                   "kept and is not fetched twice.")

    # The Thinker step (thinker-updater-design.md journeys A and B): only when the core changes. Decided
    # (consent, --with-thinker or Q1) and downloaded / verified / planned here, before anything is written.
    tstep = thinker_flow.UpdateThinker()
    if base_stale:
        args._lv_have = base_version if ver.is_valid(base_version) else ""
        try:
            tstep = thinker_flow.update_preflight(game_dir, args, pf.doc, fresh=False, lv=ver.VERSION,
                                                  persist_issued=not _local_manifest(args.manifest))
        except ix.InstallerError as e:
            # The update fetched its manifest (and the updater refreshed itself) before this refusal: "Nothing on
            # disk was changed" would not be true, the updater's own note is (execution audit 2026-11-15).
            if e.changed is False and e.disk_note is None:
                e.disk_note = "Only the updater itself was refreshed; your game files are exactly as they were."
            raise

    ix.say("\n--- commit ---")
    spec = pf.spec
    # A companion the commit cannot resolve must NOT sink the core update.
    #
    # transact.stage_one raises when neither the live companion nor its .bak is the clean base --
    # the state a player who updated PRACX is in -- and do_update turned that into "The patched
    # binary could not be installed ... close the game and try again": the wrong file, a remedy
    # that cannot work, and an update that could never succeed again. The fresh-install path has
    # always tolerated exactly this state; the two now agree.
    companions, left_alone = [], []
    for live, cpatch, cspec in companion_specs(game_dir, spec):
        # NOT `state`: that is the receipt dict this function reads again further down, and
        # shadowing it crashed the run AFTER the commit had already swapped the new binaries in.
        cstate, md5 = companion_state(live, cspec, _known_patched(spec, live.name))
        if cstate == C_CLEAN or _verified_backup(live, cspec) is not None:
            companions.append((live, cpatch, cspec))
        else:
            ix.say(f"  {live.name} (MD5 {md5}) is not a build this patch set knows and has no "
                   f"clean backup, so it is left alone.")
            ix.say("  (Longevity Vaccine updates without it; only the PRACX edge-scroll fix is missed)")
            left_alone.append(f"{live.name}: left alone (MD5 {md5}: not a build this patch set knows, "
                              f"no clean .bak)")

    work = fetchmod_staging(game_dir) / "commit"
    # On a pack-only run the patcher also re-verifies an exe that is not changing, which read as
    # "installed terranx_PRACX.exe" right above "Nothing else needed changing". Everything goes
    # to a log (the patcher's phase summary, never its per-site transcript); the console gets one
    # line per outcome.
    patch_log = _log_path(game_dir, "patch")
    exe_before = _md5_or_none(target)
    before_commit = None
    if tstep.prep is not None:
        # Section 7: the exe is STAGED first (apply_transactional), then the Thinker swap and the exe
        # rename run back to back -- a routine staging failure never touches Thinker.
        def before_commit(results):
            thinker_flow.commit(tstep.prep, route="longevity",
                                exe={"current": exe_before, "staged": results.get(target.name)})
    try:
        run_patch_logged(patch_log, game_dir, target, spec, work, companions, notes=left_alone,
                         before_commit=before_commit)
        if tstep.prep is not None and tstep.prep.committed:
            thinker_flow.tu.set_step(game_dir, 4)     # section 7: from here Thinker is never rolled back
    except KeyboardInterrupt:
        # A Ctrl-C inside the Thinker swap put it back, but said so into the patch log (run_patch_logged captures
        # the console): say it where the player reads it (verification of f076f34, 2026-11-15).
        if tstep.prep is not None and getattr(tstep.prep, "put_back", False):
            ix.say("  Thinker Mod was put back as it was.")
        raise
    except tx.CommitError as e:
        if tstep.prep is not None and tstep.prep.committed:
            if _md5_or_none(target) == exe_before:      # the old exe is in place: Thinker goes back too
                thinker_flow.undo(tstep.prep)
                raise ix.InstallerError(
                    "The patched binary could not be installed, so nothing was updated. Thinker Mod is back as it was.",
                    detail=f"  {e}\n  (log: {patch_log})", changed=False,
                    remedy="close the game if it is running and try again; your game files are as they were.")
            thinker_flow.finish(tstep.prep)           # the new exe stayed: the new Thinker stays with it
            raise ix.InstallerError(
                "The patched binary was installed only in part.", detail=f"  {e}\n  (log: {patch_log})",
                changed=None, remedy="close the game if it is running and run the updater again: it completes the update.")
        raise ix.InstallerError(
            "The patched binary could not be installed.", detail=f"  {e}\n  (log: {patch_log})",
            # The commit is transactional, so no live file was swapped. Staging a candidate can
            # still have created a .bak that was previously missing -- a correct backup of the
            # player's own bytes, which is why this is still "nothing was changed" for the game
            # itself rather than a partial install.
            changed=False,
            remedy="close the game if it is running and try again; your game files are as they "
                   "were.")
    if base_stale:
        ix.say(f"  game patch: applied (details in {patch_log})")
    else:
        ix.say("  game patch: already current, checked (no changes)")

    if not deploy_runtime(game_dir, quiet=not base_stale):
        raise ix.InstallerError(
            "The game was patched, but copying Longevity Vaccine's files into place failed.",
            changed=True,
            remedy="close the game if it is running and re-run the installer.")
    # Every update run, not only the fresh install: the resident updater reaches this path on each
    # release, and the decision is "every run" (a player who added Thinker since install included).
    ensure_in_process_movies(game_dir)
    # ... and the Datalinks text follows each release's wording (its marker says which revision a file carries).
    if tstep.prep is not None:
        thinker_flow.tu.set_step(game_dir, 5)
    patch_datalinks_text(game_dir)
    # ... and a GOG Icons.pcx without PRACX's icon art gets it (a player may have had GOG repair the folder since).
    patch_pracx_icons(game_dir)
    # Every update run: a GOG / Heroic file check can put DDrawCompat back since the install.
    wine_ddrawcompat(game_dir)
    if tstep.prep is not None:
        thinker_flow.tu.set_step(game_dir, 6)
        thinker_flow.finish(tstep.prep)               # section 7 step 6: before the packs
        thinker_flow.report_change(game_dir, tstep.prep, args)    # the summary; the thinker.ini choice closes the run
    if tstep.keep and ix.is_worker():
        ix.say("  " + tstep.keep)                    # the worker's verdict is muted: say it here; else the verdict does
    if base_stale:
        thinker_flow.clear_dont_ask(game_dir)         # decision K: an install clears the box's choice

    versions = {}
    for n in wanted:
        info = (pf.doc.get("modules") or {}).get(n)
        v = info.get("version") if isinstance(info, dict) else None
        # normalise(): the receipt stores the CANONICAL text (version.py's rule), not the
        # manifest's bytes with their possible surrounding whitespace.
        versions[n] = ver.normalise(v) if isinstance(v, str) and ver.is_valid(v) else ver.UNKNOWN
    installed_now = install_modules(game_dir, pf.staged, versions)
    if "movies-hd" in installed_now:
        # The clips play only with [UIMod] UpscaledVideos on; a player who once said no and now
        # takes the pack from the game's prompt must not get silent .wve playback.
        set_ini_flag(game_dir, True)

    # `base` records the version of the installer that ACTUALLY ran, never the manifest's.
    # Taking it from the manifest recorded a version that was downloaded but never extracted --
    # after which decide() said "already current" and the real release could never install.
    # The base payload is applied by the self-update (bootstrap.py), not by this function.
    # Only names this installer knows survive a rewrite: a hand-edited receipt entry used to be
    # copied forward forever (and printed raw).
    merged = {n: i for n, i in (state.get("modules") or {}).items()
              if n == "base" or n in GAME_CONTENT_MODULES}
    merged.update(installed_now)
    merged["base"] = {"version": ver.VERSION}
    if base_stale:
        remember_whats_new(game_dir, base_version, ver.VERSION)
    rc.write(game_dir, target_id=spec.id, modules=merged, say=ix.say)
    rc.note_check(game_dir)
    config.remember_game_dir(game_dir)

    # The core update is committed and recorded. A pack that did not land after that is still a
    # failed run -- "UPDATE COMPLETE" would be a lie about the one thing the player may have
    # run this for -- and staging is kept so the retry does not download it again.
    missing = [n for n in wanted if n not in installed_now]
    if missing:
        msgs, details = zip(*(_pack_failure(n) for n in missing))
        raise ix.InstallerError(
            f"Longevity Vaccine {ver.VERSION} is installed. "       # user 2026-11-15: as the install's
            + " ".join(msgs),
            code=ix.EXIT_ERROR, changed=True, title="UPDATE PARTLY COMPLETE",
            detail="\n".join(details),
            disk_note="The game is patched and up to date; only the pack update is missing.",
            remedy="run the update again to get "
                   + " and ".join(f"{_pack_label(n)} v{_offered(n)}" if _offered(n)
                                  else _pack_label(n) for n in missing)
                   + "; nothing already downloaded is fetched twice.")

    # Reclaim the staging space now that everything is installed. Nothing removed it before, so a
    # 1.3 GB pack stayed on disk twice over, indefinitely.
    try:
        import fetch as fetchmod
        fetchmod.clear_staging(game_dir)
    except Exception as e:  # noqa: BLE001 - cleanup must not fail a completed install
        ix.say(f"  (could not clear staging: {e})")

    # What is installed NOW, not what was before this run: the old list offered the pack that
    # had just been installed as "available but not installed".
    # The configuration as it is NOW (the receipt was just rewritten; the pre-update state may carry
    # no target_id at all -- audit 2026-10-29), not the one the run started from.
    tid_now = _resolved_target_id(game_dir, state) or state.get("target_id")
    check_display_resolution(game_dir, tid_now, no_prompt=bool(getattr(args, "no_prompt", False)))
    check_desktop_shortcut(game_dir, tid_now)
    offer_optional_modules(game_dir, pf.doc, installed + list(installed_now), args)
    # Say what happened. "Your installation is up to date" after adding a pack told the player
    # nothing about the pack, and "INSTALLATION SUCCESSFUL ... ready to play" after a base
    # update did not say what was updated.
    done = [f"{_pack_label(n)} v{installed_now[n]['version']}" for n in sorted(installed_now)]
    # A pack the game's list did not name was left on purpose: say so, never "nothing else".
    stays = "".join(f" {_pack_label(n)} stays at v{installed_modules.get(n, '?')}"
                    f" (v{_offered(n) or '?'} was not part of this update)." for n in sorted(left))
    if base_stale:
        done.insert(0, f"Longevity Vaccine v{ver.VERSION}")
        tp = None if getattr(tstep.prep, "repair", 0) else tstep.prep     # a repair says itself (its summary line)
        if tp is not None and tp.direction in (thinker_flow.st.UP, thinker_flow.st.OTHER):
            done.insert(1, f"Thinker Mod {tp.ts}")
        body = " and ".join(done) + " installed"
        if tp is not None and tp.direction == thinker_flow.st.DOWN:
            body += f", and Thinker Mod downgraded from {tp.dll.label.version} to {tp.ts}"
        elif tp is not None and tp.direction == thinker_flow.st.OTHER:
            body += f", in place of {thinker_flow.st.yours(tp.dll.label, tp.ts)}"
        body += "."
        if tstep.keep:
            body += " " + tstep.keep
        _VERDICT = ("UPDATE COMPLETE", body + stays)
    elif done:
        _VERDICT = ("UPDATE COMPLETE", ", ".join(done) + " installed."
                    + (stays or " Nothing else needed changing."))
    if ix.is_worker():
        if base_stale:
            note_whats_new(base_version, ver.VERSION)   # a worker leaves the file to the bootstrap, which prints the line
    else:
        finish_whats_new(game_dir, base_version, ver.VERSION if base_stale else base_version)
    thinker_flow.settle_install_record(game_dir)     # audit-f H2: an unfinished "Also uninstall" is over
    global _NOTE_ARGS
    _NOTE_ARGS = (game_dir, tid_now)
    return ix.EXIT_OK


def install_packs_from_manifest(game_dir: Path, args, names: list, manifest, target_id,
                                target: Path) -> tuple:
    """Download and place the optional packs a fresh install chose, through the update's own
    verified path (preflight stages the archives against the signed manifest; install_modules
    extracts them). Returns ({name: receipt entry}, {name: "ok" | "error"}).

    Never raises for a pack: the game is already patched and playable, so a pack that cannot be
    fetched is reported and left for the game's update prompt to offer again.
    """
    import preflight as pfm
    statuses = {n: "error" for n in names}
    if not manifest:
        ix.warn("  The optional modules could not be downloaded: no verified update information.")
        return {}, statuses
    raw, sig, _doc = manifest
    ix.say("\n--- downloads ---")
    pf = pfm.run(game_dir=game_dir, target=target, patches=Path(ap.DEFAULT_PATCHES),
                 table=_targets(), manifest_raw=raw, manifest_sig=sig,
                 installed_version=ver.VERSION, receipt_target_id=target_id,
                 wanted_modules=list(names), installed_modules={},
                 public_key_hex=None, labels=MODULE_LABELS,
                 allow_file=_local_manifest(args.manifest))
    # Not pf.report(): its twenty "[ok  ]" lines are the update's preflight checklist, which
    # tells a first-time player nothing here. Only what went wrong is worth a line.
    if not pf.ok:
        for c in pf.blockers:
            ix.warn(f"  {c.name}: {c.detail}")
    versions = {}
    for n in names:
        info = (pf.doc.get("modules") or {}).get(n) if pf.doc else None
        v = info.get("version") if isinstance(info, dict) else None
        versions[n] = ver.normalise(v) if isinstance(v, str) and ver.is_valid(v) else ver.UNKNOWN
    staged = {n: a for n, a in (pf.staged or {}).items() if n in names}
    got = install_modules(game_dir, staged, versions) if staged else {}
    for n in names:
        if n in got:
            statuses[n] = "ok"
        else:
            ix.warn(f"  {_pack_label(n)} could not be downloaded. Longevity Vaccine is installed without it; "
                    "the game's update prompt will offer it again.")
    if all(statuses[n] == "ok" for n in names):
        try:
            import fetch as fetchmod
            fetchmod.clear_staging(game_dir)
        except Exception as e:  # noqa: BLE001 - cleanup must not fail a completed install
            ix.say(f"  (could not clear staging: {e})")
    return got, statuses


PATCH_LOGS_KEPT = 3   # LongevityMods\logs\patch-<stamp>.log: the newest this many survive a run (audit 2026-11-07:
                      # one per update, never pruned, was the mod's only file that grew without bound)


def _log_path(game_dir: Path, kind: str) -> Path:
    import time as _t
    d = Path(game_dir) / "LongevityMods" / "logs"
    import safe_fs
    try:
        if safe_fs.link_on_path(Path(game_dir), d):
            raise OSError("a link on the way")         # never written through a link (audit-g LOW-7): %TEMP%
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        d = Path(tempfile.gettempdir())
    return d / f"{kind}-{_t.strftime('%Y%m%d-%H%M%S')}.log"


def prune_logs(log_dir: Path, kind: str, keep: int = PATCH_LOGS_KEPT) -> int:
    """Delete all but the newest `keep` `<kind>-YYYYMMDD-HHMMSS.log` in `log_dir`; returns how many went.

    Newest by NAME: the stamp sorts in time order, so a player's clock or a copied folder cannot reorder them.
    ONLY names of exactly that shape count (audit 2026-11-07: a `patch-notes.log` matched the glob, sorted
    after every stamp, and would have displaced -- or deleted -- the run's own fresh log); check.log and
    anything else stays. `log_dir` is where the run's log went (_log_path may fall back to %TEMP%).
    Never raises: a log that cannot be deleted is left for the next run."""
    d = Path(log_dir)
    import safe_fs
    # Never through a link (the user's rule 2026-11-15): <game>\LongevityMods\logs checked from the game folder down,
    # any other log folder (the %TEMP% fallback) itself.
    if (safe_fs.link_on_path(d.parent.parent, d) if d.parent.name.lower() == "longevitymods" else safe_fs.is_link(d)):
        return 0
    shape = re.compile(re.escape(kind) + r"-\d{8}-\d{6}\.log\Z")
    try:
        names = sorted(p for p in d.glob(f"{kind}-*.log") if shape.fullmatch(p.name) and p.is_file())
    except OSError:
        return 0
    gone = 0
    for p in names[:-keep] if keep > 0 else names:
        try:
            p.unlink()
            gone += 1
        except OSError:
            pass
    return gone


def _log_summary(status: str, text: str) -> None:
    """apply_patches' per-phase line, as the patch log records it (stdout is redirected into the log)."""
    print(f"[{status}] {text}")


@contextlib.contextmanager
def fresh_patch_log(game_dir: Path):
    """The fresh-install counterpart of run_patch_logged: LongevityMods\\logs\\patch-<stamp>.log around the
    patch_target / patch_companions pass -- a header, then whatever _patch_summary and _patch_log_line record
    (per-exe target / measured base / expected result, the phase lines, a companion's outcome), `done` or
    `[error] <text>` on the way out, then the prune. Until 2026-11-07 a first install -- the common 1.0.0
    case -- left no record at all; the console closed with the window and the receipt carries no hashes.
    A log that cannot be opened disables the tee for this run and nothing else."""
    global _PATCH_LOG
    import time as _t
    path = _log_path(game_dir, "patch")
    try:
        f = open(path, "w", encoding="utf-8", errors="replace")
    except OSError:
        f = None
    _PATCH_LOG = f
    try:
        _patch_log_line(f"Longevity Vaccine {ver.VERSION} -- install patch run {_t.strftime('%Y-%m-%d %H:%M:%S')}")
        _patch_log_line(f"game folder: {game_dir}")
        yield path
        _patch_log_line("done")
    except BaseException as e:   # noqa: BLE001 - recorded, then propagated unchanged
        _patch_log_line(f"[error] {str(e) or type(e).__name__}")
        raise
    finally:
        _PATCH_LOG = None
        if f is not None:
            try:
                f.close()
            except OSError:
                pass
        prune_logs(path.parent, "patch")


def run_patch_logged(patch_log: Path, game_dir: Path, target: Path, spec, work: Path, companions: list,
                     notes: list = (), before_commit=None) -> None:
    """The transactional patch of the exe (+ companions), narrated into `patch_log`.

    The log is a RECORD, not a transcript: a header (installer version, run time, each binary's target id,
    clean-base and expected hashes, `notes` = decisions taken before the run, e.g. a companion left alone),
    then the patcher's one-line-per-phase summary -- skipped sites by name, a FAILING site with its bytes --
    the stage / commit lines, and `done`; a failure is recorded as `[error] <text>` before it propagates
    (a CommitError's text -- the clean-base refusal, the lock mismatch, a swap rolled back -- lived only in
    the exception until the audit of 2026-11-07, so the one log support needs most said nothing). Before
    2026-11-07 the full per-site transcript (4,200 lines, 850 KB) went here on every update. Older patch logs
    beyond PATCH_LOGS_KEPT are pruned whether the run succeeds or raises."""
    import time as _t
    import transact as tx   # lazy, as do_update imports it: install.py has no module-level transact
    binaries = [(Path(target), spec)] + [(Path(c[0]), c[2]) for c in (companions or [])]
    try:
        with _captured(patch_log):
            print(f"Longevity Vaccine {ver.VERSION} -- update patch run {_t.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"game folder: {game_dir}")
            for live, cspec in binaries:
                print(f"{live.name}: target {cspec.id!r} ({cspec.label}), clean base {cspec.base_md5}, "
                      f"expected result {cspec.patched_md5 or '(unrecorded)'}")
            for n in notes:
                print(n)
            try:
                # before_commit only when there is one: the Thinker swap (thinker-updater-design.md section 7)
                hook = {"before_commit": before_commit} if before_commit is not None else {}
                tx.apply_transactional(target, Path(ap.DEFAULT_PATCHES), spec, work,
                                       companions=companions, say=print, summary=_log_summary, **hook)
            except BaseException as e:   # noqa: BLE001 - recorded, then propagated unchanged
                print(f"[error] {str(e) or type(e).__name__}")
                raise
            print("done")
    finally:
        prune_logs(Path(patch_log).parent, "patch")


class _captured:
    """Redirect stdout into a log file for the duration; the console keeps the outcome line."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        import contextlib
        # The log goes into public bug reports: the profile folder (the account name) is redacted.
        self._f = ix.RedactingWriter(open(self.path, "w", encoding="utf-8", errors="replace"))
        self._cm = contextlib.redirect_stdout(self._f)
        self._cm.__enter__()
        return self

    def __exit__(self, *exc):
        self._cm.__exit__(*exc)
        self._f.close()
        return False


def fetchmod_staging(game_dir: Path) -> Path:
    import fetch as fetchmod
    return fetchmod.staging_dir(game_dir)


def absent_modules(doc: dict, installed: list) -> list:
    """Content modules the manifest offers that the player does not have. Only names this
    installer knows (GAME_CONTENT_MODULES): a module it cannot place is not one it can offer."""
    mods = (doc or {}).get("modules") if isinstance(doc, dict) else None
    if not isinstance(mods, dict):
        return []
    return [n for n in GAME_CONTENT_MODULES
            if n not in installed and isinstance(mods.get(n), dict)]


def announced_modules(game_dir: Path, doc: dict, installed: list) -> list:
    """absent_modules less the packs the player turned down ("Don't ask me again" on the game's
    offer, or left unticked at install): what the console tells an up-to-date player about.
    The game's own offer (--check) applies the declines through check_report's reset rule."""
    import receipt as rc
    declines = rc.declined(game_dir)
    mods = doc.get("modules") if isinstance(doc, dict) else None

    import version as _ver           # this runs from the bootstrap too, before _load_modules

    def offered(n):
        v = str((mods.get(n) or {}).get("version") or "")
        return _ver.normalise(v) if _ver.is_valid(v) else v    # as check_report compares it
    return [n for n in absent_modules(doc, installed)
            if not rc.is_declined(declines, NEW_PACK_PREFIX + n, offered(n))]


def offer_optional_modules(game_dir: Path, doc: dict, installed: list, args) -> None:
    """After everything else is done, announce the optional modules that are NOT installed.

    Sequencing is the user's explicit instruction: update what is there first, then ask about
    extras. A decline here cannot affect the core update, which is already committed. Takes the
    verified manifest dict (not a Preflight) so the bootstrap can call it on its own
    already-current path too.
    """
    # NOT gated on --no-prompt: this asks nothing, it informs. Gating it meant the bootstrap's
    # worker (always --no-prompt) never announced extras after a real update, so a player only
    # ever heard about a pack on an idle check.
    if not doc:
        return
    absent = announced_modules(game_dir, doc, installed)
    if not absent:
        return
    import manifest as mfmod
    # The command has to be one the player can paste: a bare `run-install.bat` only works from
    # the right folder in cmd (and not at all in PowerShell). Name the resident copy in full.
    launcher = launcher_path(game_dir)
    extra = f' --manifest "{args.manifest}"' if args.manifest else ""
    ix.say("\n--- optional extras ---")
    for name in absent:
        info = doc["modules"][name] or {}
        size = info.get("size")
        dl = f" ({human_size(size)} download)" if mfmod.size_ok(size) and size > 0 else ""
        # Do NOT ask a yes/no question here: the in-game prompt is where a pack gets offered
        # interactively (Phase 8); this is the console's honest form -- what is available and
        # exactly what to paste to get it.
        ix.say(f"  {_pack_label(name)}: available, not installed{dl}")
        ix.say("    To add it, open Command Prompt and paste:")
        ix.say(f'      "{launcher}" --update --modules {name}{extra}')


# ---------------------------------------------------------------- --check (the game's query)
#
# At launch the game runs `python.exe install.py --check --game-dir <game>` as a hidden
# subprocess with stdout on a pipe, and reads the result. This is how the game learns WHAT is
# available -- a base update, a stale pack, a pack it does not have -- with the manifest
# signature verified by the same code that would install it, and the one decide() rule applied
# once rather than ported to C++.
#
# THE CONTRACT (the DLL's parser is written against this; changing it strands shipped clients):
#   * exit code: ix.CHECK_NOTHING / CHECK_UPDATES / CHECK_MANUAL / CHECK_FAILED
#   * stdout: ASCII `key=value` lines and NOTHING else -- no banner, no prompt, no progress.
#     Every diagnostic goes to stderr. A stray line would be parsed as an item; a prompt would
#     hang the game's reader.
#       latest=<ver>                                 always (except manual/failed/yanked)
#       base=<have>><offered>                        the installer/core patch is stale
#       stale=<id>|<label>|<have>><offered>|<bytes>  an installed pack is stale
#       new=<id>|<label>|<offered>|<bytes>           a pack the player does not have
#       manual=<reason>                              kill switch; <reason> is a REASONS key or ''
#   * Only compiled-in ids (GAME_CONTENT_MODULES) and labels (MODULE_LABELS), normalised
#     versions and integer sizes cross the pipe. No manifest text, ever.
#   * Declined items ([Longevity] DeclinedUpdates): `<item>:<ver>` names that version only (the
#     game's "Don't ask me again" on an update offer), `<item>:*` every version (its "Don't ask me
#     again" on a NEW pack's offer, `new:<id>:*`; a legacy `base:*` / `<id>:*` reads the same).
#     THE RESET RULE (user, 2026-10-31): "a decline of any pack is reset when any new update
#     releases for a module that is already installed". If the base or an installed pack has an
#     offer the player has NOT declined at that version, EVERY decline is ignored and every
#     candidate is listed. Otherwise:
#       - a declined BASE offer hides everything, new packs included (user, 2026-10-31): the game
#         hands off `--update --only-listed --modules <accepted>`, and while that fetches exactly
#         the packs listed, a stale core is always brought along -- so any accept would install
#         the declined core unannounced;
#       - a declined stale PACK hides only itself: a new pack is still offered, and accepting it
#         hands off `--only-listed --modules <that pack>`, which leaves the declined one alone;
#       - a new pack is listed unless `new:<id>` is declined at `*` or that version.
#     The base hiding ends with the next base release past the declined version, with Reset
#     Skipped Updates, or -- for a legacy `base:*`, which the game no longer writes -- only with
#     Reset. With nothing left the answer is exit 0 with `latest=` alone. check_report is the ONE
#     filter point; --update, --repair and --modules never consult the declines, and only the
#     game's --only-listed narrows what an update fetches (to exactly --modules).
#     `manual-<reason>:*` (reason = the REASONS key, `unspecified` for none) turns THAT
#     manual-install verdict into exit 0 with no lines; a different reason still shows.
#   * Disk: writes only the manifest cache under LongevityMods\staging and LastUpdateCheck.

_LINE_OK = set(chr(c) for c in range(0x20, 0x7f))


def _pipe_field(s) -> str:
    """One protocol field: printable ASCII, no separators. Belt and braces -- every input is
    already compiled-in or validated, and this makes that a property rather than an audit."""
    return "".join(ch for ch in str(s) if ch in _LINE_OK and ch not in "|=\n\r")


def _pipe_size(info: dict) -> str:
    import manifest as mfmod
    s = info.get("size") if isinstance(info, dict) else None
    return str(s) if mfmod.size_ok(s) else ""


def check_report(doc: dict, state: dict, declined: dict, target_id: str = None, pending=()) -> tuple:
    """(exit code, protocol lines) for a VERIFIED manifest and a receipt. Pure: no I/O.

    `target_id` is the id resolved from the exe's own bytes when the caller has it; the
    receipt's is the fallback. The surgical kill switch keyed on a stale or hand-edited
    receipt disagreed with --update, which resolves by MD5."""
    import manifest as mfmod
    import receipt as rc
    installed = rc.installed_modules(state)
    content = {n: rc.module_version(state, n) for n in installed if n in GAME_CONTENT_MODULES}
    base = rc.module_version(state, "base")
    d = mfmod.decide(doc, base, target_id or state.get("target_id"), installed_modules=content)
    declined = declined if isinstance(declined, dict) else {}

    if d.action == mfmod.MANUAL:
        reason = d.reason if isinstance(d.reason, str) and d.reason in mfmod.REASONS else ""
        if declined.get(rc.manual_decline_item(reason)) == rc.DECLINE_ANY:
            # "Don't show this again" on the manual-install notice, keyed by REASON: a later,
            # different kill switch is a different situation and shows again. The condition
            # still holds (say so on stderr for the log); the game just is not told to nag.
            print(f"--check: manual install required ({reason or 'unspecified'}); "
                  f"notice silenced by DeclinedUpdates {rc.manual_decline_item(reason)}:*",
                  file=sys.stderr)          # never the pipe, whoever calls this
            return ix.CHECK_NOTHING, []
        return ix.CHECK_MANUAL, [f"manual={_pipe_field(reason)}"]

    latest = doc.get("latest")
    if not isinstance(latest, str) or not ver.is_valid(latest):
        return ix.CHECK_NOTHING, []          # decide() already refused this as MANUAL; defensive
    latest = ver.normalise(latest)
    yanked, _ok = mfmod._str_list(doc, "yanked")
    if latest in yanked:
        return ix.CHECK_NOTHING, []          # "stay quiet" means quiet about everything
    mods = doc.get("modules") if isinstance(doc.get("modules"), dict) else {}

    # Every candidate first, as (line, decline item, offered version, for something installed).
    offers = []
    if d.action == mfmod.UPDATE and (not ver.is_valid(base) or ver.is_newer(latest, base)):
        have = ver.normalise(base) if ver.is_valid(base) else ver.UNKNOWN
        offers.append((f"base={have}>{latest}", "base", latest, True))
    for n in d.modules:
        info = mods.get(n)
        offered = info.get("version") if isinstance(info, dict) else None
        if not isinstance(offered, str) or not ver.is_valid(offered):
            continue
        offered = ver.normalise(offered)
        have = content.get(n)
        have = ver.normalise(have) if isinstance(have, str) and ver.is_valid(have) else ver.UNKNOWN
        offers.append((f"stale={_pipe_field(n)}|{_pipe_field(MODULE_LABELS.get(n, n))}"
                       f"|{have}>{offered}|{_pipe_size(info)}", n, offered, True))
    for n in absent_modules(doc, installed):
        info = mods.get(n)
        offered = info.get("version") if isinstance(info, dict) else None
        if not isinstance(offered, str) or not ver.is_valid(offered):
            continue
        offered = ver.normalise(offered)
        offers.append((f"new={_pipe_field(n)}|{_pipe_field(MODULE_LABELS.get(n, n))}"
                       f"|{offered}|{_pipe_size(info)}", "new:" + n, offered, False))
    # A pending pack (a .partial or a marker entry: a placing a kill or a failed download did not finish) the receipt
    # records at the version on offer: offered too, so the game's prompt can complete it (the parent's decision after
    # audit-t, 2026-11-17: players rarely run setup again). As a new= line -- the game's own new-pack offer, which hands
    # the pack to --update --only-listed --modules: a stale= line must go up a version (the DLL refuses have >= offered).
    # A pending pack the receipt does not know is offered above already; an older one is stale=. Never a declined one.
    for n in pending:
        if n not in GAME_CONTENT_MODULES or n not in installed or n in d.modules \
                or NEW_PACK_PREFIX + n in declined:
            continue
        info = mods.get(n)
        offered = info.get("version") if isinstance(info, dict) else None
        if not isinstance(offered, str) or not ver.is_valid(offered):
            continue
        offered = ver.normalise(offered)
        offers.append((f"new={_pipe_field(n)}|{_pipe_field(MODULE_LABELS.get(n, n))}"
                       f"|{offered}|{_pipe_size(info)}", "new:" + n, offered, False))

    # THE RESET RULE (user, 2026-10-31): "a decline of any pack is reset when any new update
    # releases for a module that is already installed". An offer for something installed (the
    # base, a stale pack) that the player has NOT declined at that version makes every decline
    # void and lists every candidate. Only when no such offer exists do the declines hide what
    # they name -- and then a declined BASE hides new packs too: the game hands off with
    # --only-listed, which fetches exactly the packs it lists, but a stale core is always brought
    # along, so offering a pack would install the declined core unannounced. A declined stale PACK
    # alone hides nothing else: --only-listed leaves it where it is.
    pending = any(own and not rc.is_declined(declined, item, v) for _, item, v, own in offers)
    base_held = any(item == "base" and rc.is_declined(declined, item, v)
                    for _, item, v, _own in offers)
    if pending:
        shown = offers                       # every decline void: one popup with everything
    elif base_held:
        shown = []                           # the core is declined; anything else drags it in
    else:
        shown = [o for o in offers if not rc.is_declined(declined, o[1], o[2])]
    lines = [f"latest={latest}"] + [line for line, _item, _v, _own in shown]
    code = ix.CHECK_UPDATES if len(lines) > 1 else ix.CHECK_NOTHING
    return code, lines


def restorable_base_hashes() -> set:
    """Every base MD5 an uninstall may restore FROM a .bak: the bases of the SHIPPING targets and
    their companions. A dev-only entry (the plain vanilla exe, patched only by --pristine tooling)
    is not among them: a terranx.exe.bak of that build that another tool left behind is not ours,
    and copying it over the live file "restored" a different game (audit 2026-10-28)."""
    ours = set()
    for t in _targets().values():
        if not t.launch:
            continue
        if t.base_md5:
            ours.add(t.base_md5)
        for cinfo in (t.companion or {}).values():
            if isinstance(cinfo, dict) and cinfo.get("base_md5"):
                ours.add(str(cinfo["base_md5"]).lower())
    return ours


def _resolved_target_id(game_dir: Path, state: dict):
    """The target id from the exe's (or its .bak's) MD5, the way --update resolves it; None if
    that cannot be determined (then the receipt's id is used)."""
    try:
        tbl = _targets()
        tid = state.get("target_id")
        exe = None
        if tid and tid in tbl and tbl[tid].exe and (game_dir / tbl[tid].exe).is_file():
            exe = game_dir / tbl[tid].exe
        if exe is None:
            exe = next((game_dir / n for n in _exe_names() if (game_dir / n).is_file()), None)
        if exe is None:
            return None
        bak = exe.with_suffix(exe.suffix + ".bak")
        probe = bak if bak.is_file() else exe
        return ap.resolve_target(_md5_safe(probe, changed=False), tbl, launch_only=True,
                                 present_files=ap.folder_files(game_dir), exe_name=exe.name).id
    except Exception:  # noqa: BLE001 - a check must degrade, never raise over this
        return None


def do_check(game_dir: Path, args) -> tuple:
    """Fetch + verify, then check_report. Returns (code, lines); raises nothing but lets
    InstallerError/ManifestError propagate to check_main, which maps them to CHECK_FAILED."""
    import manifest as mfmod
    import receipt as rc
    raw, sig = fetch_manifest(game_dir, args.manifest, args.offline, quick=True, check=True)
    try:
        doc = mfmod.load_verified(raw, sig, allow_env=_local_manifest(args.manifest))
    except mfmod.ManifestError:
        discard_staged_manifest(game_dir)
        raise
    state = rc.read(game_dir)
    code, lines = check_report(doc, state, rc.declined(game_dir),
                               target_id=_resolved_target_id(game_dir, state),
                               pending=[n for n in GAME_CONTENT_MODULES if pack_pending(game_dir, n)])
    # The thinker= line (section 8), only for a DLL that asked for this exact grammar, only after base=.
    if "thinker1" in (getattr(args, "accept", None) or []):
        base_i = next((i for i, ln in enumerate(lines) if ln.startswith("base=")), None)
        if base_i is not None:
            try:
                import thinker_flow
                info = thinker_flow.thinker_info(doc)
                if thinker_flow.issued_check(game_dir, info, persist=not _local_manifest(args.manifest)):
                    tl = thinker_flow.check_line(game_dir, doc, lines[0].split("=", 1)[1])
                    if tl:
                        lines.insert(base_i + 1, tl)
            except Exception as e:  # noqa: BLE001 - the Thinker line must never cost the check
                print(f"--check: no thinker line ({type(e).__name__}: {e})", file=sys.stderr)
    rc.note_check(game_dir)          # a check that verified is a check that happened
    # One line for the developer log (stderr): what was offered. Success used to be silent.
    print("--check: verified; " + (", ".join(lines[1:]) if len(lines) > 1 else "nothing to offer"),
          file=sys.stderr)
    return code, lines


# ---- mod health, for check.log and a player's own --check console ---------------------------------
#
# STDERR ONLY, never the pipe: the DLL's parser (update_core.h ParseCheckOutputInto) refuses a key it does
# not know, so one extra stdout line would turn every check into "could not check" for the DLL that is
# installed today. stderr is the game's LongevityMods\logs\check.log -- the file a bug report comes with.

def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def mod_files_line(game_dir: Path) -> str:
    """Are the DLLs beside the exe the ones the resident installer carries? uimod.dll + the five codec
    DLLs (deploy_runtime's set; the popup art is optional). Missing or altered ones are named: an
    antivirus quarantine or a foreign ffmpeg build is exactly what the DLL's own codec probe reports
    in-game, and here the installer says the same thing to whoever reads the log."""
    try:
        dll, ffmpeg = uimod_dll(), ffmpeg_bin()
        want = {}
        if dll.is_file():
            want["uimod.dll"] = dll
        if ffmpeg.is_dir():
            want.update({p.name: p for p in sorted(ffmpeg.glob("*.dll"))})
        if not want:
            return "Mod files: cannot compare -- the resident installer carries no DLLs"
        missing, altered = [], []
        for name, src in want.items():
            dst = Path(game_dir) / name
            if not dst.is_file():
                missing.append(name)
            elif dst.stat().st_size != src.stat().st_size or _sha256_file(dst) != _sha256_file(src):
                altered.append(name)
        if not missing and not altered:
            return f"Mod files: OK ({len(want)} DLLs match the installer's)"
        parts = []
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if altered:
            parts.append("altered: " + ", ".join(altered))
        return "Mod files: " + "; ".join(parts) + " -- re-run the installer (--repair restores them)"
    except OSError as e:
        return f"Mod files: could not check ({e})"


_INIT_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\.\d+ \[\d+\] \[uimod\] Init: v(\S+)")


def mod_loaded_line(game_dir: Path) -> str:
    """Did the game last start WITH the mod? From uimod.log's newest "[uimod] Init: v..." stamp against the
    receipt's install time -- the exe-side boot guard and a renamed DLL both leave a game that starts
    without the mod and without a word in this log. Adds what the DLL said about its codecs and movie
    sound at that start, when it said anything."""
    import json
    import time
    import receipt as rc
    game_dir = Path(game_dir)
    log = game_dir / "uimod.log"
    if not log.is_file():
        return "Mod loaded: never -- no uimod.log beside the exe (the game has not started with the mod)"
    try:
        with log.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - (1 << 20)))
            text = f.read().decode("utf-8", "replace")
    except OSError as e:
        return f"Mod loaded: could not read uimod.log ({e})"
    newest = None
    codecs = audio = None
    for ln in text.splitlines():
        m = _INIT_LINE.match(ln)
        if m:
            newest = (m.group(1), m.group(2))
            codecs = audio = None            # what follows belongs to this start
        elif newest and "[uimod] codecs: " in ln and ("missing" in ln or "not the file" in ln or "version" in ln):
            codecs = ln.split("[uimod] codecs: ", 1)[1].strip()
        elif newest and "[uimod] movie audio: " in ln and audio is None:
            audio = ln.split("[uimod] movie audio: ", 1)[1].strip()
    if not newest:
        return "Mod loaded: never -- uimod.log has no Init line"
    stamp, version = newest
    installed_at = None
    try:
        doc = json.loads((game_dir / rc.JSON_NAME).read_text(encoding="utf-8"))
        installed_at = doc.get("installed_at") if isinstance(doc, dict) else None
    except (OSError, ValueError):
        pass
    try:
        seen = time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        seen = None
    if isinstance(installed_at, (int, float)) and seen is not None and seen < installed_at:
        return f"Mod loaded: not since this install (last seen {stamp}, v{version})"
    out = f"Mod loaded: yes, last at {stamp} (v{version})"
    if codecs:
        out += f" -- cinematics OFF: {codecs}"
    if audio:
        out += f" -- movie audio: {audio}"
    return out


def mod_health(game_dir: Path) -> list:
    return [mod_files_line(game_dir), mod_loaded_line(game_dir)]


def _log_health(game_dir) -> None:
    """The health lines to stderr (check.log); never raises -- a health line must not fail a check."""
    if game_dir is None:
        return
    try:
        for health in mod_health(game_dir):
            print("--check: " + health, file=sys.stderr, flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"--check: mod health could not be determined ({type(e).__name__}: {e})", file=sys.stderr, flush=True)


def check_main() -> int:
    """Entry for --check. Bypasses run_guarded on purpose: no banner, no verdict, no wait --
    stdout is a pipe the game parses, so it carries the protocol lines and nothing else."""
    real_stdout, real_stderr = sys.stdout, sys.stderr
    # stderr is the game's check.log, which goes into public bug reports: the profile folder (the account
    # name) is redacted from every line, tracebacks included.
    sys.stderr = ix.RedactingWriter(real_stderr)
    sys.stdout = sys.stderr          # fetch progress, ix.say, anything chatty -> stderr
    lines, code = [], ix.CHECK_FAILED
    health_dir = None                # set once --game-dir is a directory; _log_health runs on both paths
    # A REAL wall deadline. fetch's own deadline is only checked between reads, so a host with
    # several dead addresses (8 s each) or a trickling body ran past 30 s and the game had to
    # kill us with an empty check.log (offline audit 2026-09-27). Nothing has been written to
    # stdout before the answer, so exiting here is the ordinary "could not check".
    print("--check: starting", file=sys.stderr, flush=True)
    import threading

    def _give_up():
        print(f"--check: gave up after {CHECK_WALL_SECONDS} s (network not answering)",
              file=sys.stderr, flush=True)
        os._exit(ix.CHECK_FAILED)
    watchdog = threading.Timer(CHECK_WALL_SECONDS, _give_up)
    watchdog.daemon = True
    watchdog.start()
    try:
        _load_modules()
        apr = argparse.ArgumentParser(add_help=False)
        apr.add_argument("--check", action="store_true")
        apr.add_argument("--game-dir", default=None)
        apr.add_argument("--manifest", default=None)
        apr.add_argument("--offline", action="store_true")
        apr.add_argument("--payload-root", default=None)
        apr.add_argument("--accept", action="append", default=[])
        args, _unknown = apr.parse_known_args()
        if args.payload_root:
            os.environ["LONGEVITY_PAYLOAD_ROOT"] = str(Path(args.payload_root).resolve())
        # NEVER autodetect here. The game passes its own directory; an omitted or empty
        # --game-dir used to fall through to SMACX_GAME_DIR / game-path.txt / the GOG paths --
        # i.e. a check launched from one install could fetch into, and stamp the ini of, a
        # different one.
        if not args.game_dir or not str(args.game_dir).strip():
            print("--check: --game-dir is required", file=sys.stderr)
            return ix.CHECK_FAILED
        game_dir = Path(args.game_dir)
        if not game_dir.is_dir():
            print(f"--check: no game directory at {game_dir}", file=sys.stderr)
            return ix.CHECK_FAILED
        if installer_running(game_dir):
            # Not locked (the game must never wait), but out of the way: a check fetches into the
            # same staging folder and writes the same ini the running installer is using.
            print("--check: an installer is working on this game; not checking now",
                  file=sys.stderr)
            return ix.CHECK_FAILED
        health_dir = game_dir
        code, lines = do_check(game_dir, args)
        # The two health lines go to check.log AFTER the fetch (its deadline accounting is not charged
        # the disk reads: ~8 MB of DLLs to hash, 10 ms warm, well under a second cold) -- and on the
        # failure path too, so a bug report's log says whether the mod's files are intact and whether the
        # game last started with the mod even when the network did not answer.
        _log_health(health_dir)
    except BaseException as e:  # noqa: BLE001 - the pipe must see a code, never a traceback
        expected = isinstance(e, ix.InstallerError) or type(e).__name__ in (
            "ManifestError", "FetchError")
        if not expected:
            import traceback
            traceback.print_exc(file=sys.stderr)
        msg = getattr(e, "message", None) or str(e)
        print(f"--check: could not check: {type(e).__name__}: {msg}", file=sys.stderr)
        _log_health(health_dir)
        return ix.CHECK_FAILED
    finally:
        sys.stdout = real_stdout
        sys.stderr = real_stderr
    # BYTES with a bare LF. A text-mode stdout on Windows wrote CRLF, so a parser splitting on
    # '\n' saw `manual=\r` (not empty) and `latest=0.1.0\r` (not a version).
    payload = b"".join(
        ("".join(ch for ch in ln if ch in _LINE_OK)).encode("ascii") + b"\n" for ln in lines)
    try:
        out = getattr(real_stdout, "buffer", None)
        if out is None:
            raise OSError("no stdout")
        out.write(payload)
        out.flush()
    except BaseException:  # noqa: BLE001 - the reader went away, or there never was one
        # Park fd 1 on NUL so the interpreter's shutdown flush cannot fail: an unflushed
        # buffer on a closed pipe made Python exit with status 120, and a missing stdout with
        # an AttributeError -- both outside the contract's four codes.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
        except OSError:
            pass
    try:
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    os._exit(code)                    # the code is the contract; nothing at shutdown may alter it


def do_repair(game_dir: Path) -> int:
    """Re-deploy the resident updater from THIS payload. Patches nothing.

    For the case the resident copy is corrupt or half-swapped -- which is precisely when the
    normal update path cannot be trusted to fix itself.
    """
    import bootstrap as bsmod
    ix.say("\n--- repair: Longevity Vaccine's updater ---")
    bsmod.reconcile(game_dir, say=ix.say)
    before = bsmod.resident_version(game_dir)
    ix.say(f"  currently resident: {before}")
    try:
        bsmod.deploy(game_dir, payload_root(), ver.VERSION, say=ix.say)
    except OSError as e:
        raise ix.InstallerError(
            "Longevity Vaccine's updater could not be reinstalled.", detail=f"  {e}",
            # NOT False: reconcile() and deploy() both rewrite <game>\LongevityMods, and a
            # failure part-way through has certainly written something. The GAME is untouched,
            # which is what the message below says instead.
            changed=None,
            remedy="close any open installer window and run --repair again; your game files "
                   "were not touched.")
    now = bsmod.resident_version(game_dir)
    import thinker_flow
    thinker_flow.clear_dont_ask(game_dir)             # decision K: --repair counts as an install
    ix.say(f"  now resident: {now}")
    ix.say("  (the game itself was not touched)")
    # Offer to start the game afterwards, like every successful outcome (user 2026-11-14).
    global _LAUNCH_EXE
    try:
        import receipt as rc
        tid = rc.read(game_dir).get("target_id")
        _LAUNCH_EXE = mod_exe(game_dir, tid) if tid else None
    except Exception:  # noqa: BLE001 - the repair itself succeeded
        _LAUNCH_EXE = None
    global _VERDICT
    _VERDICT = ("REPAIR COMPLETE",
                f"Longevity Vaccine's updater was reinstalled (version {ver.VERSION}). "      # user 2026-11-15
                "Your game files were not touched.")
    return ix.EXIT_OK


def _uninstall_files() -> list:
    """The files an uninstall removes from the game folder (the folder picker's "installed here"
    test reads the same list, so a part-finished uninstall is still found by the retry)."""
    try:
        dlls = [p.name for p in sorted(ffmpeg_bin().glob("*.dll"))]
    except OSError:
        dlls = []
    return ["uimod.dll", POPUP_ART_NAME] + dlls


def _is_link(p: Path) -> bool:
    """A junction or symlink (never followed by an uninstall's removals)."""
    import safe_fs
    return safe_fs.is_link(p)                          # one rule (audit-g LOW-9: junctions and symlinks only)


def _pack_names(manifest: Path) -> list:
    """The files a pack's pack-manifest.json lists (movies-hd "clips", portraits-hd "files"): plain names in the
    pack's own folder only; None when the manifest cannot be read (then nothing of the pack is touched)."""
    import json
    try:
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        entries = (doc.get("clips") or doc.get("files") or []) if isinstance(doc, dict) else []
        if not entries:
            return None              # a non-dict document or no entries at all is unreadable, not "nothing" (audit-q L2)
        out = []
        for e in entries:
            n = e.get("name") if isinstance(e, dict) else None
            if not isinstance(n, str) or not n or n in (".", "..") or any(c in n for c in '/\\:') or n.startswith("."):
                return None                               # a name that could leave the folder: not our manifest
            out.append(n)
        return out
    except Exception:  # noqa: BLE001 - any failure to parse it (RecursionError too: audit-n D1) is "cannot be read"
        return None


#: The packs the current uninstall left because their pack-manifest.json could not be read (do_uninstall lists them
#: under "Left in place:"). Not a failure: a re-run could not read the file either.
_PACKS_UNREAD: list = []


def _pack_left_row(name: str) -> str:
    """The "Left in place:" row for a pack whose file list could not be read. User-approved wording 2026-11-16."""
    rel = MODULE_ROOTS[name][0].replace("/", chr(92)) + chr(92)
    return f"{rel:<20} - {_pack_label(name)}: its file list could not be read"


def remove_pack(game_dir: Path, name: str) -> tuple:
    """Uninstall an optional pack (user design 2026-11-15: always removed). Only the files its pack-manifest.json
    lists, then PROVENANCE.txt and the manifest itself (last: a run stopped part-way still knows what to remove), then
    the folder when that leaves it empty. Never the player's own images elsewhere in portraits\\; never through a
    junction or symlink. Returns (removed, failed)."""
    import safe_fs
    game_dir = Path(game_dir)
    rel = MODULE_ROOTS[name][0]
    d = game_dir.joinpath(*rel.split("/"))
    cur = game_dir
    for part in rel.split("/"):
        cur = cur / part
        if _is_link(cur):
            ix.say(f"  WARNING: {rel.replace('/', chr(92))} is a link to another folder, so it was left alone.")  # user-approved 2026-11-15
            return 0, 0
    def unread() -> tuple:
        # Unreadable, or naming a file outside the pack: nothing of the pack is touched -- said, never silent (audit-f
        # L3). User-approved wording 2026-11-16.
        ix.say(f"  WARNING: {rel.replace('/', chr(92))}{chr(92)}pack-manifest.json could not be read, so "
               f"{_pack_label(name)} was left in place.")
        _PACKS_UNREAD.append(name)
        return 0, 0
    # The lists: the manifest, and the .partial a placing that did not finish left (audit-p MEDIUM-2), each validated
    # alike (_pack_names); every file either names goes.
    present = [p for p in (d / "pack-manifest.json", d / PACK_PARTIAL) if p.is_file()]
    if not present:
        try:
            left = d.is_dir() and any(d.iterdir())
        except OSError:
            left = True
        # Files and no list (audit-p MEDIUM-2: a failed pack was left silently): left, and said, with the same warning.
        if left:
            return unread()
        try:
            d.rmdir()                                     # our pack folder, empty: what an earlier uninstall left
        except OSError:
            pass
        return 0, 0
    names, by_manifest, proofs = [], set(), {}
    for p in present:
        got = _pack_names(p)
        if got is None:
            return unread()
        if p.name == PACK_PARTIAL:
            proofs = _partial_proofs(p)
            if proofs is None:
                return unread()
        else:
            by_manifest.update(got)
        names += [n for n in got if n not in names
                  and n.lower() not in ("pack-manifest.json", PACK_PARTIAL.lower(), "provenance.txt")]
    removed, failed, kept = 0, 0, 0

    def unlink(n: str) -> None:
        nonlocal removed, failed
        f = d / n
        try:
            safe_fs.unlink_entitled(f)                    # a read-only copy too (audit-j MEDIUM-3)
            removed += 1
        except OSError as e:
            failed += 1
            # user-approved: the existing mod-file warning (install.py's "could not remove {f}"), reused
            ix.say(f"  WARNING: could not remove {rel.replace('/', chr(92))}{chr(92)}{n}: {e}")
    for n in names:
        f = d / n
        if _is_link(f) or not f.is_file():
            continue
        if n not in by_manifest and not _matches(f, *proofs.get(n, (None, None))):
            kept += 1          # named only by the .partial and not provably the file we placed: the player's (audit-q M1)
            continue
        unlink(n)
    # Our own extract's leftovers, exactly "<a name we place>.tmp-<pid>" (audit-q M1).
    ours = {n.lower() for n in names} | {"provenance.txt", "pack-manifest.json", PACK_PARTIAL.lower()}
    try:
        stray = [f.name for f in d.iterdir() if f.is_file() and not _is_link(f)
                 and (m := re.fullmatch(r"(.+)\.tmp-\d+", f.name)) and m.group(1).lower() in ours]
    except OSError:
        stray = []
    for n in stray:
        unlink(n)
    for n in ["PROVENANCE.txt", PACK_PARTIAL, "pack-manifest.json"]:
        if n in (PACK_PARTIAL, "pack-manifest.json") and failed:
            # keep the lists while a file of ours could not be removed (the next uninstall finishes). Files we cannot
            # prove are ours stay, but the .partial goes all the same: after an uninstall nothing completes the pack
            # on its own (audit-r MEDIUM-2 a).
            break
        f = d / n
        if not _is_link(f) and f.is_file():
            unlink(n)
    if not failed and not kept:
        try:
            d.rmdir()                                     # only when empty
        except OSError:
            pass
        if removed:
            ix.say(f"  removed {_pack_label(name)}")      # user-approved wording 2026-11-15
    return removed, failed


def pack_removal_plan(game_dir: Path, name: str) -> list:
    """What remove_pack would read and change, without changing anything: [(path, modes)] -- preflight.PROBE_MODES
    joined by "+", "entitled" where it deletes (unlink_entitled: read-only or not). Mirrors remove_pack branch by
    branch; keep the two together. A pack folder reached through a link is left alone by the run (said there): nothing
    of it is listed. Never raises."""
    out = []
    try:
        game_dir = Path(game_dir)
        rel = MODULE_ROOTS[name][0]
        d = game_dir.joinpath(*rel.split("/"))
        cur = game_dir
        for part in rel.split("/"):
            cur = cur / part
            if _is_link(cur):
                return out
        present = [p for p in (d / "pack-manifest.json", d / PACK_PARTIAL) if p.is_file()]
        names, by_manifest, proofs = [], set(), {}
        for p in present:
            out.append((p, "read"))
            got = _pack_names(p)
            if got is None:
                return out                                # left in place, unread: nothing else is touched
            if p.name == PACK_PARTIAL:
                proofs = _partial_proofs(p)
                if proofs is None:
                    return out
            else:
                by_manifest.update(got)
            names += [n for n in got if n not in names
                      and n.lower() not in ("pack-manifest.json", PACK_PARTIAL.lower(), "provenance.txt")]
        for n in names:
            f = d / n
            if _is_link(f) or not f.is_file():
                continue
            if n not in by_manifest:
                # Hashed against the .partial's proof first. A size that differs is not ours whatever its bytes (the
                # run never opens it); one that matches is read -- listed while it cannot be, as the run would then
                # keep a file of ours -- and goes only when the hash proves it ours.
                size, sha = proofs.get(n, (None, None))
                try:
                    if size is None or f.stat().st_size != size:
                        continue
                    with open(f, "rb"):
                        pass
                except OSError:
                    out.append((f, "read"))
                    continue
                if not _matches(f, size, sha):
                    continue                              # not provably ours: kept
                out.append((f, "read+delete+entitled"))
                continue
            out.append((f, "delete+entitled"))
        ours = {n.lower() for n in names} | {"provenance.txt", "pack-manifest.json", PACK_PARTIAL.lower()}
        try:
            for f in d.iterdir():
                m = re.fullmatch(r"(.+)\.tmp-\d+", f.name)
                if f.is_file() and not _is_link(f) and m and m.group(1).lower() in ours:
                    out.append((f, "delete+entitled"))
        except OSError:
            pass
        for n in ["PROVENANCE.txt", PACK_PARTIAL, "pack-manifest.json"]:
            f = d / n
            if not _is_link(f) and f.is_file():
                out.append((f, "delete+entitled"))
    except Exception:  # noqa: BLE001 - a plan never stops the uninstall; the run says what it meets
        pass
    return out


def pending_marker_plan(game_dir: Path) -> list:
    """What forget_pending_packs would read and change: [(path, modes)]. Mirrors _mark_pending: the marker is read,
    then deleted when no other name is left in it (unlink_entitled) or replaced. A marker behind a link is never
    touched. Never raises. A held marker used to survive an uninstall ending COMPLETE, and with the declines cleared
    the next first install placed the pack, --no-prompt too (audit of 356c8f8, M2)."""
    import safe_fs
    try:
        p = _pending_path(game_dir)
        if safe_fs.link_on_path(Path(game_dir), p) or not p.is_file():
            return []
        out = [(p, "read")]
        cur = pending_packs(game_dir)
        if cur & set(GAME_CONTENT_MODULES):
            out.append((p, "replace" if cur - set(GAME_CONTENT_MODULES) else "delete+entitled"))
        return out
    except Exception:  # noqa: BLE001
        return []


def shortcut_plan(game_dir: Path) -> list:
    """What remove_our_shortcut would read and change: [(path, modes)]. Mirrors it: a "SMACX Longevity" shortcut on a
    desktop is read for its target, and deleted (unlink_entitled) when that is in this game folder. Never raises."""
    out = []
    try:
        want = str(Path(game_dir).resolve()).lower()
        for d in _desktop_dirs():
            lnk = Path(d) / (MOD_SHORTCUT_NAME + ".lnk")
            if not lnk.is_file():
                continue
            target = _shortcut_target(lnk)
            if not target:
                out.append((lnk, "read"))                 # unreadable: whose it is cannot be told -- listed for that
                continue
            if str(Path(target).resolve().parent).lower() == want:
                out.append((lnk, "read+delete+entitled"))
    except Exception:  # noqa: BLE001
        pass
    return out


def portraits_readme_plan(game_dir: Path) -> list:
    """What remove_portraits_readme would change: [(path, modes)]. Mirrors it. Never raises."""
    import safe_fs
    try:
        f = Path(game_dir) / "portraits" / PORTRAITS_README
        if safe_fs.link_on_path(Path(game_dir), f) or not f.is_file():
            return []
        return [(f, "delete+entitled")]
    except Exception:  # noqa: BLE001
        return []


def _partial_proofs(partial: Path):
    """{name: (size, sha256)} from a .partial (the release's manifest, which carries both), or None when an entry lacks
    a usable size or sha256 -- then it proves nothing and the pack is left as unreadable (audit-q M1)."""
    import json
    try:
        doc = json.loads(partial.read_text(encoding="utf-8"))
        out = {}
        for e in doc.get("clips") or doc.get("files"):
            size, sha = e.get("size"), e.get("sha256")
            if not (isinstance(size, int) and not isinstance(size, bool) and size >= 0 and isinstance(sha, str)
                    and re.fullmatch(r"[0-9a-fA-F]{64}", sha)):
                return None
            out[e["name"]] = (size, sha.lower())
        return out
    except Exception:  # noqa: BLE001 - _pack_names already vetted it; anything else proves nothing
        return None


def _matches(f: Path, size, sha) -> bool:
    """`f` is `size` bytes whose sha256 is `sha`: provably the file the installer placed."""
    try:
        if size is None or f.stat().st_size != size:
            return False
        h = hashlib.sha256()
        with open(f, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest() == sha
    except OSError:
        return False


def remove_portraits_readme(game_dir: Path) -> tuple:
    """--uninstall: portraits/LONGEVITY_PORTRAITS_README.txt is ours (release.py ships it there): it goes, and then
    portraits/ when that leaves it empty (audit-j L2b). No other file in portraits/ is ever touched, and nothing
    through a link. Returns (removed, failed)."""
    import safe_fs
    d = Path(game_dir) / "portraits"
    f = d / PORTRAITS_README
    if safe_fs.link_on_path(Path(game_dir), f) or not f.is_file():
        return 0, 0
    try:
        safe_fs.unlink_entitled(f)
    except OSError as e:
        # user-approved: the existing mod-file warning (install.py's "could not remove {f}"), reused
        ix.say(f"  WARNING: could not remove portraits{chr(92)}{PORTRAITS_README}: {e}")
        return 0, 1
    safe_fs.rmdir(Path(game_dir), d)                  # only when empty, never a link
    return 1, 0


def lv_in_place(game_dir: Path) -> bool:
    """Is Longevity Vaccine itself in this folder: uimod.dll, and an exe that is not its .bak (our patched build)? A
    receipt alone is not enough: a part-finished uninstall keeps it (audit-k LOW-1)."""
    g = Path(game_dir)
    if not (g / "uimod.dll").is_file():
        return False
    for n in _exe_names():
        exe, bak = g / n, g / (n + ".bak")
        if exe.is_file() and bak.is_file() and _md5_or_none(exe) != _md5_or_none(bak):
            return True
    return False


def drop_empty_ini_section(game_dir: Path, section: str) -> bool:
    """Remove `[section]` from Alpha Centauri.ini when no key is left in it (audit-j L2c: an empty [Longevity] stayed
    after an uninstall). Only the header and the empty lines under it go; every other byte of the file stays as it
    was. A section holding any other line (a key, a comment) is left alone. True when it was removed."""
    import re
    p = Path(_ini_path_str(game_dir))
    try:
        data = p.read_bytes()
    except OSError:
        return False
    lines = data.splitlines(keepends=True)
    head = re.compile(rb"\s*\[\s*" + re.escape(section.encode("ascii")) + rb"\s*\]\s*$", re.I)
    for i, line in enumerate(lines):
        if not head.match(line):
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines) and not lines[j].lstrip().startswith(b"["):
            return False                              # something is still in it
        tmp = p.with_name(p.name + ".longevity-tmp")
        try:
            tmp.write_bytes(b"".join(lines[:i] + lines[j:]))
            os.replace(tmp, p)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)       # never left in the game folder (audit-k LOW-3: a read-only ini)
            except OSError:
                pass
            return False
        return True
    return False


def _shortcut_target(lnk: Path) -> str:
    """A .lnk file's target path ("" when it cannot be read)."""
    return _ps("$s = (New-Object -ComObject WScript.Shell).CreateShortcut(" + _ps_quote(lnk) + "); "
               "Write-Output $s.TargetPath").strip()


def remove_our_shortcut(game_dir: Path) -> int:
    """The "SMACX Longevity" desktop shortcut, when it is ours: its target is in this game folder. Any other shortcut
    -- one the player made, or ours pointing at another install -- is left. Returns how many were removed."""
    n = 0
    want = str(Path(game_dir).resolve()).lower()
    for d in _desktop_dirs():
        lnk = Path(d) / (MOD_SHORTCUT_NAME + ".lnk")
        if not lnk.is_file():
            continue
        target = _shortcut_target(lnk)
        try:
            if not target or str(Path(target).resolve().parent).lower() != want:
                continue
            import safe_fs
            safe_fs.unlink_entitled(lnk)                  # read-only or not, as our other files (audit of 356c8f8, M2)
            n += 1
        except OSError:
            continue
    if n:
        ix.say(f'  removed the desktop shortcut "{MOD_SHORTCUT_NAME}"')        # user-approved wording 2026-11-15
    return n


def uninstall_targets(game_dir: Path, names: list, ours: set, thinker_too: bool = False) -> list:
    """Every file --uninstall would read or change in this folder as it is now, as [(path, modes)], `modes` one or
    more of preflight.PROBE_MODES joined by "+": what the up-front check probes. Each step's own conditions decide
    (the restore modules' restore_plan, thinker_undo_plan, the restore loop's test), so a file the run would leave
    alone is not listed for a change and never blocks it (audit 2026-11-15: a read-only kept original, a marked
    help file without its backup, a kept ddraw backup did). Every file the run READS to decide what to do is listed
    for reading: an unreadable one read as "absent" to the plan, which then missed what the run would change
    (audit 2026-11-16: a held set-up record let the generic restore copy the PRACX build over the only original)."""
    game_dir = Path(game_dir)
    out = {}

    def add(p: Path, modes: str = "delete") -> None:
        if not p.is_file():
            return
        out[p] = out.get(p, set()) | set(modes.split("+"))

    # What the run reads before it acts: the set-up record and every file it names (the undo hashes them all), and
    # an exe / companion with its .bak when both are there (the restore loop hashes the pair; alone, neither is read).
    rec = _read_setup(game_dir)
    ov = _thinker_overlay()
    add(game_dir / THINKER_SETUP_NAME, "read")
    if rec:
        exe_name = rec.get("exe") or (ov.exe if ov is not None else "terranx.exe")
        for n in [exe_name, exe_name + ".bak", rec.get("backup") or ""] + list(rec.get("set_aside") or []):
            if n:
                add(game_dir / n, "read")
        for n in names:                                 # _pracx_source hashes each, and its .bak
            add(game_dir / n, "read")
            add(game_dir / (n + ".bak"), "read")
    for name in names:
        if (game_dir / name).is_file() and (game_dir / (name + ".bak")).is_file():
            add(game_dir / name, "read")
            add(game_dir / (name + ".bak"), "read")
    # The Thinker set-up's undo says what it would change (thinker_undo_plan, beside the undo it mirrors).
    thinker_plan, thinker_held = thinker_undo_plan(game_dir)
    for p, modes in thinker_plan:
        add(p, modes)
    # Gone or moved before the generic restore runs. NOT a copy source the revert only reads (audit 2026-11-15:
    # counting terranx_PRACX.exe.bak as taken dropped terranx_PRACX.exe from the check, and its restore failed).
    consumed = {p for p, modes in thinker_plan if {"delete", "rename"} & set(modes.split("+"))}
    setup_exe = (rec.get("exe") or (ov.exe if ov is not None else "")).lower() if rec else ""
    # The generic restore: an exe or companion whose .bak is ours and differs from it is copied over (copy2: the
    # .bak is its source, whose read-only bit the exe would inherit) -- unless the set-up's undo has taken that .bak
    # first or left the exe to the player (do_uninstall's `hold`).
    for name in names:
        exe = game_dir / name
        bak = exe.with_suffix(exe.suffix + ".bak")
        if bak in consumed or (thinker_held and name.lower() == setup_exe):
            continue
        if exe.is_file() and bak.is_file() and _md5_or_none(bak) in ours and _md5_or_none(exe) != _md5_or_none(bak):
            add(exe, "overwrite")
            add(bak, "source")
    for f in _uninstall_files():
        add(game_dir / f, "delete+entitled")            # unlink_entitled: read-only or not (audit-j MEDIUM-3)
    # The install receipt: a run that cannot delete it is unfinished (a leftover reads as "installed here" to the
    # folder picker and to the next run), so do_uninstall counts that as INCOMPLETE -- and it is checked up front.
    # Its keys in Alpha Centauri.ini are removed too (rc.clear), and keys left there read as "installed" as much
    # as the file does (rc.read falls back to them; audit 2026-11-16): checked while any is there -- or while the ini
    # cannot be read, which the profile API answers exactly as it answers a missing key (D3).
    try:
        import receipt as rc
        add(game_dir / rc.JSON_NAME)
        if rc.receipt_keys_present(game_dir) or rc.ini_unreadable(game_dir):
            add(Path(rc._ini_path(game_dir)), "profile")
    except Exception:  # noqa: BLE001
        pass
    # The restore modules say for themselves what they would change.
    try:
        import patch_helptext as ph
        for folder in ph.FOLDERS:
            for name, spec in ph.FILES.items():
                for p, mode in ph.restore_plan((game_dir / folder / name) if folder else (game_dir / name), spec):
                    add(p, mode)
    except Exception:  # noqa: BLE001 - a mistrimmed payload: restore_datalinks_text says so itself
        pass
    try:
        import patch_icons as pi
        for p, mode in pi.restore_plan(game_dir / pi.SHEET):
            add(p, mode)
    except Exception:  # noqa: BLE001
        pass
    try:
        import wine_ddraw as wd
        for p, mode in wd.restore_plan(game_dir):
            add(p, mode)
    except Exception:  # noqa: BLE001
        pass
    # The steps this branch adds, in the run's order (user ruling 2026-11-17: refused up front like master's): the
    # Thinker install record (and thinker.dll / thinker.exe for a valid one), the Thinker Mod removal when the player
    # chose it (after the Datalinks restore above, which removal_plan allows for), the optional packs, the pending
    # marker, our desktop shortcut, our portraits readme, the Thinker consent key and the emptied [Longevity] section.
    # Each mirrors its step: a file whose read or change failing would end the run differently is listed. Not
    # listed: Thinker's movie-player key (its failure is said and changes nothing else).
    import thinker_flow
    if (game_dir / thinker_flow.INSTALL_RECORD).is_file():
        # Read by every uninstall (the question; whether it waits for thinker.dll) and deleted at the end
        # (clear_install_record): one that cannot be read or deleted ends differently.
        add(game_dir / thinker_flow.INSTALL_RECORD, "read+delete+entitled")
        if thinker_flow.read_install_record(game_dir) is not None:
            # A record that is acted on: thinker.dll and thinker.exe decide the question (_removal_ready hashes both)
            # and whether the record waits for a later run. An invalid record is inert: they never block for it
            # (audit of 356c8f8, L5).
            add(game_dir / "thinker.dll", "read")
            add(game_dir / "thinker.exe", "read")
    if thinker_too:
        for p, modes in thinker_flow.removal_plan(game_dir)[0]:
            add(p, modes)
    for pack in GAME_CONTENT_MODULES:
        for p, modes in pack_removal_plan(game_dir, pack):
            add(p, modes)
    for p, modes in pending_marker_plan(game_dir) + shortcut_plan(game_dir) + portraits_readme_plan(game_dir):
        add(p, modes)
    if thinker_flow.read_ini_str_absent(game_dir, thinker_flow.CONSENT_SECTION, thinker_flow.CONSENT_KEY) is not None:
        add(Path(_ini_path_str(game_dir)), "profile")     # delete_ini_key removes the consent key (M2)
    # The [Longevity] section that clearing the receipt and the consent key leaves empty goes too
    # (drop_empty_ini_section: a new file moved onto Alpha Centauri.ini's name).
    if _ini_section_would_empty(game_dir):
        add(Path(_ini_path_str(game_dir)), "read+replace")
    return [(p, "+".join(sorted(m))) for p, m in out.items()]


def _ini_section_would_empty(game_dir: Path) -> bool:
    """Would [Longevity] be empty once the uninstall has removed the receipt's keys and the Thinker consent key? Then
    drop_empty_ini_section replaces the file. Mirrors it on the file as it is now. Never raises."""
    import receipt as rc
    import thinker_flow
    try:
        data = Path(_ini_path_str(game_dir)).read_bytes()
    except OSError:
        return False
    gone = {k.lower() for k in rc.RECEIPT_KEYS} | {thinker_flow.CONSENT_KEY.lower()}
    head = re.compile(rb"\s*\[\s*" + re.escape(rc.INI_SECTION.encode("ascii")) + rb"\s*\]\s*$", re.I)
    lines = data.splitlines()
    for i, line in enumerate(lines):
        if not head.match(line):
            continue
        for ln in lines[i + 1:]:
            t = ln.strip()
            if not t:
                continue
            if t.startswith(b"["):
                return True
            key = t.split(b"=", 1)[0].strip().decode("latin-1").lower()
            if b"=" not in t or key not in gone:
                return False
        return True
    return False


#: The bookkeeping files do_uninstall removes on its way even when nothing else is to do -- the what's-new file, the
#: pending marker, the Thinker install record -- as the "Nothing to uninstall" disk note names them.
_BOOKKEEPING = ("LongevityMods\\" + WHATS_NEW_FILE, "LongevityMods\\" + PENDING_PACKS, "longevity-thinker-install.json")


def uninstall_links(game_dir: Path, thinker_too: bool) -> list:
    """The junctions and symlinks on the way to a file the uninstall would remove -- the Thinker Mod files when the
    player chose to remove it -- each once, as [(relative name with backslashes, leads to a folder)]. The uninstall
    refuses them up front, nothing changed (user ruling 2026-11-17, D3(c))."""
    if not thinker_too:
        return []
    import thinker_flow
    out = []
    for rel in thinker_flow.removal_plan(game_dir)[1]:
        p = Path(game_dir).joinpath(*rel.split("/"))
        out.append((rel.replace("/", "\\"), os.path.isdir(p)))
    return sorted(out)


def _shown_rel(p: Path, game_dir: Path) -> str:
    """How a refusal names a file it lists: relative to the game folder -- also when one side is a resolved path and
    the folder was reached through a junction, a symlink or a subst drive (audit of 356c8f8, M3: relative_to raised
    there and the refusal crashed) -- else in full (a file outside it: our desktop shortcut). Never raises."""
    p, game_dir = Path(p), Path(game_dir)
    for a, b in ((p, game_dir), (p, None)):
        try:
            if b is not None:
                return str(a.relative_to(b))
            return str(a.resolve().relative_to(game_dir.resolve()))
        except (ValueError, OSError):
            continue
    return str(p)


def _link_line(rel: str, folder: bool) -> str:
    """A link refusal's detail line, both user-approved 2026-11-17: a link to a folder, or a link that is itself a
    file (a symlinked thinker.dll, or one whose target is gone)."""
    return f"  {rel}: a link to another folder" if folder else f"  {rel}: a link to another file"


def do_uninstall(game_dir: Path, args) -> int:
    """Restore the original exe from .bak and remove what we deployed."""
    import receipt as rc
    import thinker_flow
    import preflight as pfm
    del _PACKS_UNREAD[:]
    ix.say("\n--- uninstall ---")
    # The Thinker Mod question (user design 2026-11-15), after the folder is chosen and before anything is removed.
    remove_thinker_too = thinker_flow.ask_uninstall_thinker(game_dir)

    # Companions (prax.dll) are ours to undo too -- leaving a patched companion behind is not an
    # uninstall. Their names come from the target table, never hardcoded.
    names = list(_exe_names())
    for t in _targets().values():
        for fname in (t.companion or {}):
            if fname not in names:
                names.append(fname)

    #: Every base MD5 we could have patched FROM, exe and companion alike. A .bak is only ours to
    #: restore if it hashes to one of these. Without the check, `--uninstall` copied ANY
    #: `<exe>.bak` it found over the live file -- another mod's backup included -- and counted it
    #: as a successful restore of ours.
    ours = restorable_base_hashes()

    # Refuse BEFORE the first change when any file the run must read or change is in use or read-only (user,
    # 2026-11-15). Without it a running game left a half-done uninstall -- the exe restored, uimod.dll still there --
    # and a second run with the DLL still held did no work and refused as "already unmodified", forgetting the
    # folder. Each file is probed for the calls the run makes on it (preflight.PROBE_MODES): an uninstall deletes,
    # and moves files onto names, which a plain open for writing does not prove.
    # A file to remove reached through a junction or symlink: refused up front too, nothing changed (user ruling
    # 2026-11-17, D3(c)) -- a re-run alone never gets past a link.
    links = uninstall_links(game_dir, remove_thinker_too)
    if links:
        # User-approved 2026-11-17: the heading, message, detail (a link to a folder; see _link_line), disk note and
        # remedy.
        raise ix.InstallerError(
            "Some Thinker Mod files the uninstall has to remove are reached through a link (a junction or symbolic "
            "link), so the uninstall did not start.",
            code=ix.EXIT_ABORTED, changed=False, title="UNINSTALL NOT STARTED",
            detail="\n".join(_link_line(rel, folder) for rel, folder in links),
            disk_note="The uninstall itself changed nothing, so running it again is safe.",
            remedy="replace the link named above with an ordinary folder, then run the uninstall again.")
    blocked = []
    for p, modes in uninstall_targets(game_dir, names, ours, remove_thinker_too):
        why = pfm.probe(p, modes.split("+"))
        if why:
            blocked.append((p, why))
    if blocked:
        raise ix.InstallerError(
            "Some files the uninstall has to read or change are in use, read-only or hidden, so the uninstall did "
            "not start.",
            code=ix.EXIT_ABORTED, changed=False, title="UNINSTALL NOT STARTED",
            detail="\n".join(f"  {_shown_rel(p, game_dir)}: {why}" for p, why in blocked),
            # disk_note, not changed=False's "Nothing on disk was changed": a recovery of an interrupted Thinker
            # set-up may have run before this (main's _recover_thinker) and says what it did itself.
            disk_note="The uninstall itself changed nothing, so running it again is safe.",
            remedy="close Alpha Centauri and any program that has these files open, make sure they are not "
                   "read-only or hidden, and run the uninstall again. If nothing else is open, a virus scanner may have been "
                   "checking a file: wait a moment and run it again. If the game is in Program Files and every file "
                   "says \"Access is denied\", run the uninstall as administrator.")

    # Bookkeeping files a run with nothing else to do still removes: the refusal's disk note names each one that went
    # (audit of 356c8f8, L1).
    left_before = {rel: (game_dir / rel).is_file() for rel in _BOOKKEEPING}
    forget_whats_new(game_dir)                        # audit-h M2 (W02): it belongs to the install that is going

    restored, already_clean, foreign = 0, 0, 0
    # A folder the installer set up for Thinker FIRST: its terranx.exe.bak is our PRACX copy's,
    # and copying it over whatever terranx.exe is now in place (the original, put back by GOG or
    # by hand) would destroy the only copy of the original. This reads the folder as it is and
    # puts the original back; an exe it had to leave as it is (the player's own, say), the loop
    # below leaves alone too.
    held: list = []
    # Its undo changes files even when it puts none back. An unreadable record describes nothing:
    # it goes, said so, and does not count as work done.
    had_setup = bool(_read_setup(game_dir))
    removed_records = []                # bookkeeping files removed though nothing else was: the refusal says so
    if thinker_setup_folder(game_dir) and not had_setup:
        try:
            (game_dir / THINKER_SETUP_NAME).unlink()
            ix.say(f"  removed an unreadable {THINKER_SETUP_NAME}")
            removed_records.append(THINKER_SETUP_NAME)
        except OSError:
            pass
    restored += revert_thinker_setup(game_dir, held, title="UNINSTALL FAILED")
    if had_setup and not thinker_setup_folder(game_dir):
        ix.say("  the installer's Thinker set-up of this folder is undone")
    hold = {n.lower() for n in held}
    for name in names:
        exe = game_dir / name
        bak = exe.with_suffix(exe.suffix + ".bak")
        if not (exe.is_file() and bak.is_file()) or name.lower() in hold:
            continue
        changed = bool(restored)         # honest once the first restore has landed
        if _md5_safe(bak, changed=changed) not in ours:
            foreign += 1
            ix.say(f"  {bak.name} is not a backup this installer made, so {name} is left alone.")
            continue
        # COMPARE FIRST. Restoring unconditionally meant a second --uninstall copied the .bak
        # over an already-clean file, counted it, and reported a successful uninstall of
        # something that was not installed.
        if _md5_safe(exe, changed=changed) == _md5_safe(bak, changed=changed):
            already_clean += 1
            continue
        try:
            shutil.copy2(bak, exe)
            ix.say(f"  restored {name} from {bak.name}")
            restored += 1
        except OSError as e:
            raise ix.InstallerError(
                f"Could not restore {name} from its backup.", detail=f"  {e}", changed=True,
                remedy="close the game if it is running and try again.")

    import safe_fs
    removed, remove_failed = 0, 0
    for f in _uninstall_files():
        p = game_dir / f
        if not p.exists():
            continue
        try:
            safe_fs.unlink_entitled(p)                    # a read-only copy too (audit-j MEDIUM-3)
            removed += 1
        except OSError as e:
            remove_failed += 1
            ix.say(f"  WARNING: could not remove {f}: {e}")

    # The Datalinks text files lose our text again (the exact inverse of the patch) wherever ours is in place --
    # BEFORE the refusal below, so a folder whose exe and DLL were already cleaned by hand still gets its text back.
    text_restored, text_held, text_failed, text_unmarked, text_dropped = restore_datalinks_text(game_dir)
    removed_records.extend(text_dropped)
    # Left as it is on purpose (patch_helptext could not take our text out exactly): unfinished, but no re-run
    # changes it -- the verdict says how to get the original text back. A file that could not be WRITTEN is a
    # failed restore like any other (restore_failed below).
    text_left = text_held or text_unmarked
    if text_restored:
        ix.say(f"  restored {text_restored} Datalinks text file(s)")
        restored += text_restored
    icons_restored, icons_failed, icons_dropped = restore_pracx_icons(game_dir)
    removed_records.extend(icons_dropped)
    restored += icons_restored
    ddraw_back = restore_wine_ddrawcompat(game_dir)
    if ddraw_back == "restored":
        restored += 1
    elif ddraw_back == "dropped":
        removed += 1
    # Thinker Mod (only when the player chose it), the optional packs (always), our desktop shortcut (user design
    # 2026-11-15). A file that cannot be removed is unfinished work: the verdict says so and the re-run finishes it.
    linked = 0
    if remove_thinker_too:
        r, f = thinker_flow.remove_thinker(game_dir)
        removed += r
        remove_failed += f
        linked = thinker_flow.LAST_LINKED
    for pack in GAME_CONTENT_MODULES:
        r, f = remove_pack(game_dir, pack)
        removed += r
        remove_failed += f
    forget_pending_packs(game_dir)                        # nothing stays chosen for a folder we leave (audit-q M3)
    removed += remove_our_shortcut(game_dir)
    r, f = remove_portraits_readme(game_dir)              # ours (audit-j L2b); then portraits/ only when empty
    removed += r
    remove_failed += f
    # A restore that was due and failed is unfinished work, like a file that could not be removed: the verdict says
    # INCOMPLETE and the folder stays remembered for the re-run (and that re-run is not a "nothing to uninstall").
    # A failed ddraw.dll put-back counts too: its .longevity.bak is then the only copy of GOG's DDrawCompat.
    restore_failed = len(text_failed) + icons_failed + (1 if ddraw_back == "failed" else 0)
    remove_failed += restore_failed

    # Nothing restored and nothing removed is a REFUSAL, whatever the receipt says.
    #
    # Gating this on the receipt let a stray or corrupt record stand in for real work: the run
    # printed "UNINSTALL COMPLETE -- 0 file(s) restored, 0 removed. The game is back to how it
    # was", which is both useless and untrue. The record is still cleared on the way out, so a
    # leftover one never persists and re-running stays idempotent. A removal or restore that failed
    # is unfinished work, not nothing: the up-front check above makes that rare (a file taken
    # between the check and the change), and then the verdict says INCOMPLETE and the folder stays
    # remembered -- never "already unmodified" with the DLL still there (audit-f M4: a Thinker file or a pack file
    # still locked from the last run is work left to do). A Datalinks text file still holding Longevity Vaccine's
    # text is NOT nothing either: it gets the INCOMPLETE verdict below, never a "Nothing to uninstall" that tells
    # the player to reinstall the game.
    if not restored and not removed and not had_setup and not remove_failed and not text_left:
        had_record = (game_dir / rc.JSON_NAME).exists() or bool(rc.receipt_keys_present(game_dir))
        if not rc.clear(game_dir, say=ix.say):
            # Taken between the check and now: the record still says "installed", so keep the folder for the
            # re-run and say what to do (the warning above names what is left). Part of it may be gone already
            # (the file, or some keys): the disk note does not claim nothing changed (audit 2026-11-16).
            raise ix.InstallerError(
                f"Nothing else to uninstall, but the install record ({rc.JSON_NAME} and its keys in "
                f"{rc.INI_NAME}) could not be removed completely.",
                code=ix.EXIT_ABORTED, changed=False, title="UNINSTALL INCOMPLETE",
                disk_note="Part of Longevity Vaccine's leftover bookkeeping may have been removed already (see the "
                          "warnings above); nothing else was changed.",
                remedy=f"make sure {rc.JSON_NAME} and {rc.INI_NAME} are not read-only or open in another program, "
                       "and run the uninstall again.")
        section_gone = drop_empty_ini_section(game_dir, rc.INI_SECTION)  # audit-j L2c
        if not remove_thinker_too and not thinker_flow.record_waits_for_dll(game_dir):
            # (a thinker.dll another program holds could not be asked about: a valid record stays, so a later
            # uninstall can -- audit-m #7)
            thinker_flow.clear_install_record(game_dir)   # as on the way out below (audit-g LOW-6: it stayed)
        config.forget_game_dir(game_dir)
        if foreign:
            msg = ("Nothing to uninstall: the backup beside your executable was not made by this "
                   "installer, so it was left alone.")
        elif already_clean:
            msg = "Nothing to uninstall: this copy of the game is already unmodified."
        else:
            msg = "Nothing to uninstall: no patched executable with a backup was found."
        if had_record:
            removed_records.append(f"{rc.JSON_NAME} and any of its keys in Alpha Centauri.ini")
        removed_records.extend(rel for rel, was in left_before.items() if was and not (game_dir / rel).is_file())
        if section_gone:
            removed_records.append(f"the empty [{rc.INI_SECTION}] section in Alpha Centauri.ini")
        # The banner and the disk statement say what this refusal changed: "NOTHING WAS CHANGED" was untrue once a
        # stray record was cleared on the way out (audit 2026-11-15; the unreadable set-up record too, as on master).
        raise ix.InstallerError(
            msg, code=ix.EXIT_ABORTED, changed=False,
            title="NOTHING TO UNINSTALL" if removed_records else None,
            disk_note=(f"Only Longevity Vaccine's leftover bookkeeping was removed "
                       f"({'; '.join(removed_records)}); nothing else was changed." if removed_records else None),
            remedy="if you moved or deleted the .bak file, reinstall the game.")
    if removed:
        ix.say(f"  removed {removed} mod file(s)")
    # Thinker's video-player key goes back to "absent" (if still our blank), so Thinker re-detects
    # its player on the next launch as if the mod had never been there.
    release_in_process_movies(game_dir)
    # The HD clips, the resident updater and the [UIMod] preferences are deliberately LEFT: the
    # clips are a large download the player may want to keep, the updater is what an uninstall
    # run may itself be executing from, and the preferences are theirs, not our bookkeeping.
    # SAY SO, item by item -- an uninstall that leaves a folder behind without mentioning it
    # reads as a failed uninstall the next time the player looks.
    ix.say("\n  Left in place:")                         # user-approved wording 2026-11-15 (was "..., deliberately:")
    thinker_lines = thinker_flow.uninstall_lines(game_dir, also=remove_thinker_too)
    if remove_thinker_too:
        thinker_lines = thinker_lines + thinker_flow.kept_lines()
    for line in thinker_lines:
        ix.say("    " + line)
    for pack in _PACKS_UNREAD:
        ix.say("    " + _pack_left_row(pack))
    if thinker_flow.tu.older_backups(game_dir):          # the backups line names them only when there are some
        ix.say("    LongevityMods\\       - Longevity Vaccine's updater, its staging folder, the Thinker Mod backups above")
        ix.say("                           and the Thinker Mod changelog copy; safe to delete once this window is closed")
    else:
        ix.say("    LongevityMods\\       - Longevity Vaccine's updater and its staging folder; safe to")
        ix.say("                           delete once this window is closed")
    thinker_flow.delete_ini_key(game_dir, thinker_flow.CONSENT_SECTION, thinker_flow.CONSENT_KEY)
    ix.say("    [UIMod] settings     - your preferences in Alpha Centauri.ini")
    if not remove_failed:
        # Kept while something is left to remove (a locked pack file, a Thinker file): the re-run --uninstall must
        # still find this folder installed, and finish (user design 2026-11-15: partial failures stay re-runnable).
        if not rc.clear(game_dir, say=ix.say):
            # A receipt left behind reads as "installed here" to the folder picker and the next run: unfinished
            # work, like a file that could not be removed (it said why above).
            remove_failed += 1
        else:
            drop_empty_ini_section(game_dir, rc.INI_SECTION)  # audit-j L2c: no empty [Longevity] left behind
            if not remove_thinker_too and not thinker_flow.record_waits_for_dll(game_dir):    # audit-m #7, above
                thinker_flow.clear_install_record(game_dir)
    if not remove_failed:
        # Kept while something is left to remove: the verdict asks for another --uninstall,
        # which has to find this folder again.
        config.forget_game_dir(game_dir)

    global _VERDICT
    # Say only what is true: the counts, then any failure or held exe. ("The game is back to how it was" was dropped
    # because it was printed unchanged even when a removal had just warned that it failed; the list of items kept is
    # printed above the verdict and is not repeated in it -- user ruling 2026-11-17.)
    body = f"{restored} file(s) put back to the originals, {removed} removed."
    if remove_failed:
        body += (f" {remove_failed} file(s) could NOT be removed or restored (see the warnings above). "
                 # Every failure a link on the way (the up-front check refuses those, so only one made between the
                 # check and the change): a re-run alone cannot fix it (audit-g LOW-6). User-approved wording
                 # 2026-11-16, in that case only.
                 + ("Replace the link named above with an ordinary folder, then run the uninstall again to finish."
                    if linked and linked == remove_failed else
                    "Close the game and any program that has those files open, make sure they are not read-only, "
                    "and run --uninstall again to finish."))
    if held:
        # An exe left to the player (see its warning above) may still carry an older build of
        # the mod: say so in the verdict, not in one console line above it.
        body += (f" {', '.join(held)} was left as it is (see the warning above): if it still starts "
                 "the game with Longevity Vaccine, replace it with the original yourself; GOG Galaxy's \"verify files\" restores it.")
    if foreign and text_left:
        # The "Nothing to uninstall" refusal that says this is skipped when a Datalinks file is still to report.
        body += (" A .bak file in the game folder was not made by this installer, so the file it backs up was "
                 "left alone.")
    restore_advice = ("restore the file from the game's own files (GOG Galaxy's \"verify files\" does it, or "
                      "reinstall the game); the smac_mod copies come from Thinker's download.")
    if text_held:
        # Ours, but it does not invert exactly (changed since, or an unrecorded / newer revision): writing it could
        # overwrite whatever changed it, so patch_helptext left it alone. Documentation only -- the game runs.
        body += (f" Datalinks text left as it is, because Longevity Vaccine's text could not be taken out of it "
                 f"safely (see above): {', '.join(text_held)}. It may still show Longevity Vaccine's wording; the "
                 "game runs either way. To get the original text back, " + restore_advice)
    if text_unmarked:
        # Ours with the marker removed, or someone else's file quoting our wording: they cannot be told apart, so
        # the advice covers both -- restoring another mod's or a translation's file would wipe their text (audit 6).
        body += (f" Datalinks text with Longevity Vaccine's wording but without its marker line, left as it is "
                 f"(see above): {', '.join(text_unmarked)}. If another mod or a translation put that text there, "
                 "nothing needs doing. If it is Longevity Vaccine's text with its marker removed, the game runs "
                 "either way; to get the original text back, " + restore_advice)
    _VERDICT = ("UNINSTALL COMPLETE" if not (remove_failed or held or text_left)
                else "UNINSTALL INCOMPLETE", body)
    ix.say(f"\n  {restored} file(s) restored, {removed} removed.")
    return ix.EXIT_OK


# ---- the game folder --------------------------------------------------------------------------
# A player never needs a command prompt to install: without --game-dir the installer lists the
# folders it found (the ones it installed into before, the GOG locations, every folder the GOG
# registry names), lets the player pick one or another, and -- when it found none -- asks for the
# folder in a Windows folder picker or as a typed path. Every choice is checked before anything is
# written; a non-interactive run never asks, it takes the first good folder or explains.

#: The folder holds a game build this mod installs onto (clean, or ours with its backup).
FOLDER_OK = "ok"


def _folder_exe_spec(d: Path, name: str):
    """The launch target `d/name` installs as -- from its own bytes, else from its .bak (an
    already-patched exe) -- or None. Never raises."""
    p = d / name
    try:
        beside = ap.folder_files(d)
        for probe in (p, p.with_suffix(p.suffix + ".bak")):
            if not probe.is_file():
                continue
            try:
                return ap.resolve_target(_md5(probe), targets=_targets(), launch_only=True,
                                         present_files=beside, exe_name=name)
            except ap.UnsupportedBase:
                continue
    except Exception:  # noqa: BLE001 - a probe is a verdict, never a crash
        return None
    return None


def _has_install(d: Path) -> bool:
    """Is the mod (or what is left of a part-finished uninstall) here: a receipt, the mod's DLL, a
    Thinker set-up record, or one of our backups beside an exe that differs from it? Not the
    resident updater, and not a .bak alone: an uninstall leaves both behind on purpose (it copies
    the backup back and keeps it)."""
    import receipt as rc
    try:
        state = rc.read(d)
        if state.get("target_id") or state.get("modules") or thinker_setup_folder(d) \
                or any((d / f).is_file() for f in _uninstall_files()):
            return True
        ours = None
        for n in _exe_names():
            exe, bak = d / n, d / (n + ".bak")
            if not (exe.is_file() and bak.is_file()):
                continue
            if ours is None:
                ours = restorable_base_hashes()
            b = _md5(bak)
            if b in ours and _md5(exe) != b:
                return True
        return False
    except Exception:  # noqa: BLE001 - a probe is a verdict, never a crash
        return False


def check_game_folder(d: Path, installed: bool = False):
    """(FOLDER_OK, label) when `d` is a folder the installer can work on, else (problem, the
    plain-words reason). `installed`: the mode needs the mod to be there already (uninstall,
    repair, update). Never raises for the folder itself: an access-denied folder (is_dir() still
    answers for one) or a dropped network share is a reason, not a crash."""
    try:
        return _check_game_folder(d, installed)
    except OSError as e:
        return "missing", f"that folder cannot be read ({e.strerror or e})"


def _check_game_folder(d: Path, installed: bool):
    try:
        if d.is_file():
            if d.suffix.lower() == ".lnk":
                return "file", "that is a shortcut; choose the game folder itself (the one with terranx.exe)"
            return "file", "that is a file, not a folder; choose the folder that holds terranx.exe"
        if not d.is_dir():
            return "missing", "there is no folder at that location"
    except OSError as e:
        return "missing", f"that folder cannot be read ({e.strerror or e})"
    # An exe present -- or, in a Thinker folder only, just its .bak (its one PRACX copy as terranx_PRACX.exe.bak):
    # the Thinker set-up starts from either (_pracx_source), so the folder check and the early refusal take both
    # there (verification 2026-11-15: 75245c5 installed that folder). A plain folder with only that .bak has
    # nothing the pass can patch, and is refused before any question, as at 7b53fbb (verification of 9f2cb08).
    ov = _thinker_overlay()
    orphan_ok = ov is not None and _thinker_here(d, ov)
    names = [n for n in _exe_names() if (d / n).is_file() or (orphan_ok and (d / (n + ".bak")).is_file())]
    if installed:
        if _has_install(d):
            return FOLDER_OK, "Longevity Vaccine is installed here"
        return "not-installed", "Longevity Vaccine is not installed in that folder"
    if not names:
        inner = []
        try:
            inner = [c for c in sorted(d.iterdir()) if c.is_dir()
                     and any((c / n).is_file() for n in _exe_names())]
        except OSError:
            pass
        if inner:
            return "nested", (f"the game is one folder further in: choose \"{inner[0].name}\" "
                              f"inside it")
        return "no-game", ("Alpha Centauri is not in that folder: choose the folder that holds "
                           "terranx.exe")
    specs = [s for s in (_folder_exe_spec(d, n) for n in names) if s is not None]
    if not specs:
        return "unsupported", ("the Alpha Centauri there is not a version this mod supports: it "
                               "needs the GOG Planetary Pack (Alpha Centauri with Alien "
                               "Crossfire) with PRACX, on its own or with Thinker")
    label = specs[0].label
    ov = _thinker_overlay()
    if ov is not None and _thinker_here(d, ov):
        label = ov.label                  # the install sets a stock Thinker folder up for Thinker
    return FOLDER_OK, label + (" (Longevity Vaccine is installed here)" if _has_install(d) else "")


def browse_for_folder(title: str):
    """The Windows folder picker (IFileOpenDialog, FOS_PICKFOLDERS) in front of this console.
    The chosen folder, or None (cancelled, or no picker on this system). Never raises."""
    try:
        from ctypes import wintypes
        ole32 = ctypes.WinDLL("ole32")
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        ole32.CoCreateInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                                           ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        hr_init = ole32.CoInitializeEx(None, 0x2 | 0x4)     # STA, no OLE1 DDE
        try:
            return _show_folder_dialog(ole32, title)
        finally:
            if hr_init in (0, 1):                           # S_OK / S_FALSE: ours to balance
                ole32.CoUninitialize()
    except Exception:  # noqa: BLE001 - the typed path is always there as the fallback
        return None


def _guid(text: str):
    import uuid
    return (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)


def _com_call(obj, index: int, restype, *args):
    """Call vtable slot `index` of the COM object `obj` (a c_void_p). Each arg is a ctypes value;
    an out-pointer is passed as `_ptr(x)`."""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *[type(a) for a in args])
    return proto(vtbl[index])(obj, *args)


def _ptr(x) -> ctypes.c_void_p:
    return ctypes.c_void_p(ctypes.addressof(x))


# IFileDialog vtable slots (IUnknown 0-2, IModalWindow::Show 3, then IFileDialog in order).
_FD_SHOW, _FD_SETOPTIONS, _FD_GETOPTIONS, _FD_SETTITLE, _FD_GETRESULT, _RELEASE = 3, 9, 10, 17, 20, 2
_SI_GETDISPLAYNAME = 5                       # IShellItem::GetDisplayName
_FOS_PICKFOLDERS, _FOS_FORCEFILESYSTEM, _FOS_PATHMUSTEXIST = 0x20, 0x40, 0x800
_SIGDN_FILESYSPATH = 0x80058000 - (1 << 32)  # an enum: a signed int


def _show_folder_dialog(ole32, title: str):
    from ctypes import wintypes
    dlg = ctypes.c_void_p()
    clsid = _guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")    # FileOpenDialog
    iid = _guid("D57C7288-D4AD-4768-BE02-9D969532D960")      # IFileOpenDialog
    if ole32.CoCreateInstance(_ptr(clsid), None, 1, _ptr(iid), ctypes.byref(dlg)) != 0 or not dlg.value:
        return None
    try:
        opts = wintypes.DWORD()
        _com_call(dlg, _FD_GETOPTIONS, ctypes.HRESULT, _ptr(opts))
        _com_call(dlg, _FD_SETOPTIONS, ctypes.HRESULT,
                  wintypes.DWORD(opts.value | _FOS_PICKFOLDERS | _FOS_FORCEFILESYSTEM | _FOS_PATHMUSTEXIST))
        _com_call(dlg, _FD_SETTITLE, ctypes.HRESULT, wintypes.LPCWSTR(title))
        k32 = ctypes.windll.kernel32
        k32.GetConsoleWindow.restype = ctypes.c_void_p
        try:
            # Owned by the console window: Show() disables its owner while it is up. Under Windows
            # Terminal that is the hidden pseudo-console window, which the terminal owns -- so the
            # picker still stacks above the terminal, and the terminal itself is never disabled
            # (its root owner as the owner froze every tab, and stayed frozen if the installer was
            # killed with the picker open: re-audit 2026-11-01).
            ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
            owner = k32.GetConsoleWindow() or ctypes.windll.user32.GetForegroundWindow()
            _com_call(dlg, _FD_SHOW, ctypes.HRESULT, ctypes.c_void_p(owner))
        except OSError:
            return None                                       # cancelled (HRESULT 0x800704C7)
        item = ctypes.c_void_p()
        _com_call(dlg, _FD_GETRESULT, ctypes.HRESULT, _ptr(item))
        try:
            name = ctypes.c_void_p()
            _com_call(item, _SI_GETDISPLAYNAME, ctypes.HRESULT, ctypes.c_int(_SIGDN_FILESYSPATH), _ptr(name))
            try:
                return Path(ctypes.wstring_at(name.value))
            finally:
                ole32.CoTaskMemFree(name)
        finally:
            _com_call(item, _RELEASE, ctypes.c_ulong)
    finally:
        _com_call(dlg, _RELEASE, ctypes.c_ulong)


def _no_folder_chosen(installed: bool) -> "ix.InstallerError":
    # "... so nothing was installed" says it: no second "Nothing on disk was changed." under it (verification
    # 2026-11-15), as at every other question. The installed form says nothing of the disk, so it keeps the line.
    return ix.InstallerError("No game folder was chosen, so nothing was installed."
                             if not installed else "No game folder was chosen.",
                             code=ix.EXIT_ABORTED, changed=False, disk_note=False if not installed else None,
                             remedy="run the installer again and choose the folder.")


def copy_error_summary(e: BaseException) -> str:
    """One readable line for a failed copy. shutil.copytree raises shutil.Error carrying a list
    of (source, destination, reason) for EVERY file it could not copy, and printing that dumped
    a screenful of paths (2026-11-04). The count, the first destination and its reason; plus a
    plain word when Windows refused a path for its length (WinError 206)."""
    errors = e.args[0] if isinstance(e, shutil.Error) and e.args and isinstance(e.args[0], list) else None
    if not errors:
        return str(e)
    first = errors[0]
    where, why = (first[1], first[2]) if isinstance(first, tuple) and len(first) == 3 else (first, "")
    text = (f"{len(errors)} file{'s' if len(errors) != 1 else ''} could not be copied, the first "
            f"{where}: {why}")
    if any("WinError 206" in str(x) for x in errors):
        text += "; some paths in the game folder are longer than Windows allows (260 characters)"
    return text


def _absolute(d) -> Path:
    """Absolute, so nothing later resolves it against another working directory (a shortcut's
    target, generation 2 started in the game folder, the profile API's %WINDIR%)."""
    return Path(os.path.abspath(str(d)))


def _arrow_menu(title, items: list, before=(), at: int = 0, notes=(), title_kind: str = None) -> int:
    """A ruled question block (ix.ask_block) whose rows the arrow keys move through: Up / Down move
    the marker over `items` -- each a list of printed lines, the marker on the first; the selected
    row is green as a whole (ix.marked) -- and Enter takes the one under it: its index. `before`: output lines printed above the
    block (why the list is what it is); `notes`: the block's own text, above the rows; `title_kind`:
    the title's colour. No `title`: no ruled head and no closing rule, the keys line and the rows alone
    (user 2026-11-15: the Thinker changelog offer). Keys typed before the list was drawn are dropped. Ctrl-C
    raises KeyboardInterrupt."""
    closing = [ix.RULE] if title else []

    def rows(at):
        out = []
        for i, lines in enumerate(items):
            if i == at:
                out.append(ix.marked(lines[0], True))
            else:
                out.append(ix.marked(lines[0], False))
            out += [ix.MARK_OFF + ln for ln in lines[1:]]
        return out + closing
    shown = rows(at)
    _drop_typed_ahead()
    if before:
        ix.blank()
        for line in before:
            ix.say(line)
    ix.ask_block(title, list(notes), shown, keys="Up/Down: move   Enter: choose", title_kind=title_kind)
    while True:
        key = _read_key()
        if key == "enter":
            return at
        nxt = max(0, at - 1) if key == "up" else min(len(items) - 1, at + 1) if key == "down" else at
        if nxt != at:
            at = nxt
            shown = ix.redraw(shown, rows(at))


def pick_game_folder(found: list, installed: bool, rejected: list = ()) -> Path:
    """Ask the player which folder to use: a list the arrow keys move through (user 2026-11-03) --
    each folder found, then Browse, then Quit -- and Enter takes the highlighted row. A folder is
    chosen from the list or in the Windows folder window; a typed or pasted path is not taken
    (user 2026-11-03). `found`: [(folder, label)] that already checked out; `rejected`: [(folder,
    reason)] that were looked at and do not. Loops until a folder checks out or the player quits;
    every rejection says why. Ctrl-C is "no folder chosen": nothing was written yet."""
    verb = "Use" if installed else "Install into"
    browse_title = "Choose your Alpha Centauri folder (the one with terranx.exe)"
    while True:
        if found:
            before = []
            items = [[f"{verb} {d}   ({label})"] for d, label in found]     # user 2026-11-04
            items.append(["Browse for a different folder"])
        else:
            if rejected:
                before = ["No folder the installer found can be used:"]
                before += [f"  Found {d}, but {why}." for d, why in rejected]
            elif installed:
                before = ["The installer could not find a game folder Longevity Vaccine is installed in."]
            else:
                before = ["The installer could not find Alpha Centauri on this PC by itself."]
            items = [["Choose the game folder in a window"]]
        items.append(["Quit"])
        try:
            pick = _arrow_menu("Choose the game folder", items, before)
        except KeyboardInterrupt:
            raise _no_folder_chosen(installed)
        if pick == len(items) - 1:
            raise _no_folder_chosen(installed)
        if pick < len(found):
            return found[pick][0]
        chosen = browse_for_folder(browse_title)
        if chosen is None:
            ix.say("  No folder chosen in the window.")
            continue
        chosen = _absolute(chosen)
        status, why = check_game_folder(chosen, installed=installed)
        if status == FOLDER_OK:
            ix.say(f"  {chosen}: {why}")
            return chosen
        ix.warn(f"  Not that folder: {why}.")
        ix.say("  Try again.")


def resolve_game_dir(args, installed: bool = False) -> Path:
    """The game folder this run works on, always absolute.

    --game-dir wins and is taken as given (scripted runs; its own checks follow). A resident
    updater works on the folder it lives in. Otherwise: the folders found on this PC, checked;
    an interactive run lets the player pick one or another, a non-interactive one takes the one
    good folder or stops with a reason a player can act on -- and with more than one install it
    does not guess which one an --uninstall / --update / --repair is meant for.
    """
    if getattr(args, "game_dir", None):
        d = _absolute(args.game_dir)
        try:
            if d.suffix.lower() == ".exe" and d.is_file():
                d = d.parent                    # --game-dir given the game's program: its folder
        except OSError:
            pass
        return d
    resident = config.resident_game_dir(_SCRIPTS)
    if resident is not None:
        return resident
    cands = config._dedup_dirs(config.remembered_game_dirs() + config.candidate_game_dirs())
    found, rejected = [], []
    for d in cands:
        d = _absolute(d)
        status, label = check_game_folder(d, installed=installed)
        (found if status == FOLDER_OK else rejected).append((d, label))
    if ix.can_ask() and not ix.is_worker() and not getattr(args, "no_prompt", False):
        return pick_game_folder(found, installed, rejected)
    if found and (len(found) == 1 or not installed):
        return found[0][0]
    flag = "--game-dir \"<the folder that holds terranx.exe>\""
    if found:
        raise ix.InstallerError(
            "Longevity Vaccine is installed in more than one game folder, so this run did not guess which one.",
            code=ix.EXIT_ABORTED, changed=False,
            detail="\n".join(f"  {d}" for d, _ in found),
            remedy=f"run it again from a console window and choose the folder when it asks, or pass {flag}.")
    if installed:
        raise ix.InstallerError(
            "No game folder with Longevity Vaccine installed could be found.",
            code=ix.EXIT_NO_GAME, changed=False,
            detail="\n".join(f"  Found {d}, but {why}." for d, why in rejected) or None,
            remedy=f"run it again from a console window and choose the folder when it asks, or pass {flag}.")
    raise ix.InstallerError(
        "The game folder could not be found." if not rejected else
        "No folder the installer found can be used.",
        code=ix.EXIT_NO_GAME, changed=False,
        detail=("\n".join(f"  Found {d}, but {why}." for d, why in rejected) if rejected else
                "  Alpha Centauri is not in any of the usual GOG locations on this PC."),
        remedy=f"start the installer by double-clicking INSTALL.bat and choose the game folder when it asks; a scripted run passes {flag}.")


def main() -> int:
    _load_modules()     # must precede banner(): it prints ver.VERSION
    if not ix.is_worker():
        banner()        # a worker child runs in the bootstrap's console, which printed it already
    apr = argparse.ArgumentParser(
        description="Longevity Vaccine installer (SMACX UI scaling + HD Cinematics)")
    apr.add_argument("--ai", choices=["on", "off", "ask"], default="ask",
                     help="Install Z2k Retro's HD Cinematics? Default: list the optional modules "
                          "and ask. `--modules a,b` picks packs by name instead.")
    apr.add_argument("--payload-root", default=None,
                     help="Where the installer's own files live (default: derived from this "
                          "script's location, which works in a checkout and in an extracted "
                          "release archive alike).")
    apr.add_argument("--pack", default=None,
                     help="Z2k Retro's HD Cinematics pack dir (default: dist\\movies-hd).")
    apr.add_argument("--portrait-pack", default=None,
                     help="Turovetsky's HD Portrait Pack dir (default: dist\\portraits-hd).")
    apr.add_argument("--force", action="store_true",
                     help="Restore from .bak and re-patch even if already patched.")
    apr.add_argument("--game-dir", default=None, help="Override the game install dir.")
    apr.add_argument("--no-wait", action="store_true",
                     help="Do not wait for a keypress before exiting (for scripted runs). "
                          "The outcome is still always printed.")
    apr.add_argument("--update", action="store_true",
                     help="Manifest-driven update: preflight everything, then bring the core "
                          "patch and every installed module up to date.")
    apr.add_argument("--manifest", default=None, metavar="URL|PATH",
                     help="Where to read the update manifest from (default: the compiled-in "
                          "URL). A local path is allowed for testing.")
    apr.add_argument("--modules", default=None,
                     help="Comma-separated extras to add or re-install (default: the installed "
                          "ones that have a newer version). Extras: "
                          + ", ".join(f"{n} ({MODULE_LABELS.get(n, n)})"
                                      for n in GAME_CONTENT_MODULES) + ".")
    apr.add_argument("--only-listed", action="store_true",
                     help="(used by the game) with --update: fetch exactly the packs named by "
                          "--modules (the ones the game's update prompt listed and the player "
                          "accepted) and no other; none without --modules. The core is still "
                          "brought up to date when it is stale.")
    apr.add_argument("--offline", action="store_true",
                     help="Do not touch the network; use only what is already in staging.")
    apr.add_argument("--no-prompt", action="store_true",
                     help="Never ask anything: install every optional module on offer, set a "
                          "Thinker folder up when its game file is recognised, and create no "
                          "desktop shortcut and leave the game's resolution setting as it is "
                          "(each says how to do it yourself). --modules and --ai still choose "
                          "the modules when given.")
    apr.add_argument("--wait-pid", type=int, default=None, metavar="PID",
                     help="(used by the game) wait for this process (the game that launched "
                          "the update) to exit before checking or touching anything.")
    apr.add_argument("--uninstall", action="store_true",
                     help="Restore the original exe from .bak and remove the mod's files.")
    apr.add_argument("--repair", action="store_true",
                     help="Reinstall Longevity Vaccine's updater from this payload, without patching "
                          "anything. Use when <game>\\LongevityMods\\updater is corrupt.")
    apr.add_argument("--check", action="store_true",
                     help="(used by the game at launch) print what updates are available as "
                          "key=value lines and exit; installs nothing. Handled before main().")
    apr.add_argument("--fix-thinker", action="store_true",
                     help="(used by the game's Thinker Mod message) offer a newer Longevity Vaccine, then the "
                          "Thinker Mod version that goes with it, and make the two work together.")
    # User-approved wording 2026-11-16 (audit-j's unmarked lines).
    apr.add_argument("--with-thinker", action="store_true",
                     help="Install Thinker Mod, or change it to the version this release needs, without asking "
                          "(for scripted runs).")
    apr.add_argument("--keep-thinker", action="store_true",
                     help="Leave Thinker Mod as it is without asking, and install Longevity Vaccine on its own "
                          "(for scripted runs; refused when this release does not start with that Thinker Mod).")
    # Accept `--no-wait=1` as well as the bare flag. argparse rejects the `=` form for a
    # store_true, so a scripted run that wrote it had the wait suppressed (installer_exit scans
    # argv) and then aborted with a usage error -- the guarantee held while the install silently
    # did nothing. Rewrite the token to the bare flag BEFORE parsing; do not just drop it, or
    # installer_exit's argv scan loses the only thing it can see.
    argv = []
    for a in sys.argv[1:]:
        if a.startswith("--no-wait="):
            if a.split("=", 1)[1].strip().lower() in ("1", "true", "yes", "on", ""):
                argv.append("--no-wait")
            # an explicit false value simply drops out
        else:
            argv.append(a)
    sys.argv[1:] = argv

    args = apr.parse_args()
    if args.uninstall:
        global _CANCELLED
        _CANCELLED = UNINSTALL_CANCELLED                 # a Ctrl-C from here on is the uninstall's
    # The PLAYER's --no-prompt means no question at all, the changelog and "Start the game" ones included (a
    # worker's --no-prompt is the bootstrap's; the player's reaches it as the LONGEVITY_PLAYER_NO_PROMPT marker).
    ix.set_player_no_prompt(bool(args.no_prompt) and not ix.is_worker())
    if args.no_wait:
        os.environ["LONGEVITY_NO_WAIT"] = "1"
    if args.payload_root:
        # Exported rather than passed around, so every payload_root() caller agrees -- including
        # the ones reached from modules that never see `args`.
        os.environ["LONGEVITY_PAYLOAD_ROOT"] = str(Path(args.payload_root).resolve())

    # Every pairing, not just one. main() dispatches uninstall > repair > update in that order,
    # so an unchecked `--repair --update` silently did the repair and the verdict claimed only
    # that -- the player asked for two things and was told about one, with no word about the
    # other.
    modes = [n for n, on in (("--uninstall", args.uninstall), ("--repair", args.repair),
                             ("--update", args.update), ("--fix-thinker", args.fix_thinker)) if on]
    if len(modes) > 1:
        raise ix.InstallerError(f"{' and '.join(modes)} cannot be combined.",
                                code=ix.EXIT_ABORTED, changed=False,
                                remedy="run one of them at a time.")
    if getattr(args, "with_thinker", False) and getattr(args, "keep_thinker", False):
        raise ix.InstallerError("--with-thinker and --keep-thinker cannot be combined.",
                                code=ix.EXIT_ABORTED, changed=False, remedy="choose one of them.")
    if args.only_listed and not args.update:
        # It narrows an UPDATE's pack set; anywhere else it would be silently ignored.
        raise ix.InstallerError("--only-listed works only with --update.",
                                code=ix.EXIT_ABORTED, changed=False,
                                remedy="add --update, or leave --only-listed out.")
    # After the flag checks (a refused combination never asks for a folder), before the lock
    # (which is named after the folder).
    game_dir = resolve_game_dir(args, installed=bool(args.uninstall or args.repair or args.update
                                                     or args.fix_thinker))
    global _CRASH_LOG_GAME_DIR
    _CRASH_LOG_GAME_DIR = game_dir      # from here a crash log goes to LongevityMods\logs, with the rest
    ix.say(f"Game dir: {game_dir}")
    if not game_dir.is_dir():
        raise ix.InstallerError(
            "The game folder could not be found.",
            code=ix.EXIT_NO_GAME,
            detail=f"Looked for: {game_dir}",
            remedy="check the --game-dir path: it must be the folder that holds terranx.exe.")
    # Before the first write of every mode, and released before run_guarded offers to start the
    # game, so an update the game then offers is never refused by the window that is closing.
    lock = hold_installer_lock(game_dir)
    try:
        if args.fix_thinker:
            import thinker_flow
            return thinker_flow.fix_thinker(game_dir, args)
        if not args.update:
            # Every entry finishes or undoes an interrupted Thinker change first (an update does it
            # after waiting for the game, in do_update).
            import receipt as rc
            _recover_thinker(game_dir, rc.read(game_dir))
        if args.uninstall:
            return do_uninstall(game_dir, args)
        if args.repair:
            return do_repair(game_dir)
        if args.update:
            return _saying_thinker_state(do_update, game_dir, args)
        return _saying_thinker_state(_install, game_dir, args)
    finally:
        lock.release()


def _recover_thinker(game_dir: Path, state: dict) -> None:
    """Section 7 recovery, with the live exe's md5 for a Longevity route's journal."""
    import thinker_flow
    if not thinker_flow.tu.journal_path(game_dir).exists():
        return None
    md5 = None
    try:
        tbl = _targets()
        tid = state.get("target_id")
        exe = game_dir / tbl[tid].exe if tid and tid in tbl and tbl[tid].exe else None
        if exe is None or not exe.is_file():
            exe = next((game_dir / n for n in _exe_names() if (game_dir / n).is_file()), None)
        md5 = _md5_or_none(exe) if exe is not None else None
    except Exception:  # noqa: BLE001
        md5 = None
    return thinker_flow.recover_at_entry(game_dir, live_exe_md5=md5)


def _install_candidates(game_dir: Path) -> list:
    """The exes the install pass patches: every configured name that is in the folder -- except
    that in a folder the installer set up for Thinker, only the exe Thinker starts (terranx_PRACX.exe
    is left as it is; see "setting a folder up for Thinker")."""
    candidates: list[Path] = []
    for name in _exe_names():
        p = game_dir / name
        if p.exists() and p not in candidates:
            candidates.append(p)
    ov = _thinker_overlay()
    if ov is not None and _setup_in_effect(game_dir):
        candidates = [p for p in candidates if p.name.lower() == ov.exe.lower()]
    return candidates


def _install(game_dir: Path, args) -> int:
    """The first-time install (and its re-runs): main() without a mode flag."""
    # Candidate exes come from the target table's `exe` fields plus the configured name -- no
    # hardcoded executable names here (CLAUDE.md's opening invariant), and a base that is not a
    # shipping target contributes no candidate.
    # Before the first write: a companion declared without its baseline is a packaging fault, and
    # companions are patched AFTER the exe -- discovering it then would mean aborting with the exe
    # already modified.
    check_companion_declarations()
    _clear_setup_tmps(game_dir)
    # A Thinker folder whose terranx.exe is not PRACX: decided now (no question), set up just before
    # the patch pass (after every question), so the pass patches the exe Thinker actually starts.
    thinker_plan = plan_thinker_setup(game_dir, args)
    candidates = _install_candidates(game_dir)
    if not candidates:
        raise ix.InstallerError(
            "No Alpha Centauri executable was found in the game directory.",
            code=ix.EXIT_NO_GAME,
            detail=f"Searched: {game_dir}",
            remedy="check that this is the folder containing terranx.exe.")
    # A folder this mod cannot patch at all (a Steam or a vanilla install without PRACX) is refused now, as the
    # folder list refuses it -- not after every question, and never after a Thinker Mod download that the patch
    # pass would then have to take out again (code review 2026-11-15). The pass's own refusal, word for word.
    if check_game_folder(game_dir)[0] == "unsupported":
        raise _unsupported_folder(game_dir, [p.name for p in candidates])
    # The backup rule for every other exe the pass will patch: refuses now (nothing written),
    # moves just before the pass.
    backup_plan = plan_backups(game_dir, candidates, thinker_plan)

    # The optional modules are chosen BEFORE anything is written: the player sees what is on
    # offer, with sizes, and the installer waits for the answer (user, 2026-09-27). The downloads
    # themselves happen after the game is patched.
    lm_existed = (game_dir / "LongevityMods").exists()
    import thinker_flow
    try:
        code = _install_from_questions(game_dir, args, thinker_plan, candidates, backup_plan)
    except BaseException as e:
        # NOTHING WAS CHANGED, or a Ctrl-C (Thinker's change undone, or never begun; a kept one already cleared it),
        # leaves nothing of this run: its Thinker download goes in any folder (verification 2026-11-15: a
        # re-install kept staging\thinker, and a Ctrl-C's survived into the next run), and the whole folder when
        # this run created it and nothing changed.
        no_change = isinstance(e, ix.InstallerError) and e.changed is False
        if no_change or isinstance(e, KeyboardInterrupt):
            thinker_flow._clear_staging(game_dir)
        if no_change and not lm_existed:
            _forget_staging(game_dir)
        raise
    thinker_flow._clear_staging(game_dir)       # a successful run: an earlier run's leftover download is not needed
    return code


def _clear_setup_tmps(game_dir: Path) -> None:
    """A set-up's temporary copies (<exe>.longevity-tmp) left by a run that was killed: never needed again
    (verification 2026-11-15: a 4 MB terranx.exe.longevity-tmp survived later runs)."""
    for n in _exe_names():
        try:
            (game_dir / (n + _SETUP_TMP)).unlink()
        except OSError:
            pass


def _forget_staging(game_dir: Path) -> None:
    """A first install that ends with nothing changed must not leave the LongevityMods folder its questions created
    (execution audit 2026-11-15: a cancel said "Nothing on disk was changed" over a fetched manifest in
    LongevityMods\\staging). Removed only when everything in it is under staging\\ -- the fetched manifest, a Thinker
    download -- and never when anything else is there."""
    lm = game_dir / "LongevityMods"
    try:
        files = [p for p in lm.rglob("*") if p.is_file()]
        if all(p.relative_to(lm).parts[0] == "staging" for p in files):
            import safe_fs
            safe_fs.rmtree(game_dir, lm)                  # never a junctioned LongevityMods (safe_fs)
    except OSError:
        pass


def _install_from_questions(game_dir: Path, args, thinker_plan, candidates, backup_plan) -> int:
    """_install from the first question on."""
    ix.say("\n--- optional modules ---")
    catalogue, manifest = module_catalogue(game_dir, args)
    try:
        chosen, turned_down, ticked_now = pick_modules(catalogue, args, game_dir)
    except KeyboardInterrupt:
        raise ix.stopped_error()          # before any write: as at the Thinker question (code review 2026-11-15)
    # The answers are the player's latest word: recorded now, before every later step (audit-t ROOT 2).
    record_choices_now(game_dir, args, catalogue, chosen, turned_down, ticked_now)
    if args.ai == "off" and not args.modules:
        ix.say("  none requested")
    elif manifest is not None and not catalogue:
        ix.say("No optional modules are available for download right now.")
    # The Thinker question (Q1, journey B1), or B for a folder with no thinker.dll, then the update-check
    # opt-in (user 2026-11-15: the Thinker question first). Decided now, downloaded after every question.
    import thinker_flow
    tstep = thinker_flow.update_preflight(game_dir, args, manifest[2] if manifest else None, fresh=True,
                                          lv=ver.VERSION, persist_issued=False, defer=True)
    if tstep.prep is None and tstep.todo is None and not tstep.keep:
        tstep = thinker_flow.offer_thinker_install(game_dir, args, ver.VERSION, defer=True)
    # The update-check opt-in, the last "what do you want" question, before any write.
    try:
        update_checks = ask_update_checks(game_dir, args)
    except KeyboardInterrupt:
        raise ix.stopped_error()
    global _PENDING_UPDATE_CHECKS
    _PENDING_UPDATE_CHECKS = update_checks
    # The Thinker download is verified and planned here, after the questions and before any write. Ctrl-C during it
    # is a stop with nothing changed, as at the questions (its partial download goes with the no-change exit).
    try:
        tstep = thinker_flow.download_step(game_dir, tstep)
    except KeyboardInterrupt:
        raise ix.stopped_error()

    # The first writes: the spare backups out of the way, then the Thinker set-up; a set-up that
    # fails leaves the folder as it found it, moved backups included. Every planned .bak is hashed
    # again before the first of them, so a refusal never follows a drop.
    recheck_planned_backups(backup_plan, thinker_plan)
    # Section 7, fresh install: the Thinker swap comes first, so its own failure (F5) leaves the folder as it
    # was; every later failure before the exe is patched puts Thinker back.
    if tstep.prep is not None:
        thinker_flow.commit(tstep.prep, route="fresh")
    new_thinker = tstep.prep is not None and tstep.prep.new
    moves = []
    try:
        if new_thinker:
            # Thinker Mod is in the folder now (B): everything decided while it was absent is decided again, as for
            # a folder that came with it -- the set-up (terranx.exe becomes the PRACX build Thinker's launcher
            # starts), the exes the pass patches, their backups (code review 2026-11-15: a folder set up before
            # and released kept the candidates from without Thinker, and the pass patched terranx_PRACX.exe).
            thinker_plan = plan_thinker_setup(game_dir, args)
            candidates = _install_candidates(game_dir)
            backup_plan = plan_backups(game_dir, candidates, thinker_plan)
            recheck_planned_backups(backup_plan, thinker_plan)
        moves = apply_backup_plan(backup_plan)
        if apply_thinker_setup(thinker_plan):
            candidates = _install_candidates(game_dir)
        elif thinker_plan and thinker_plan["action"] == "release":
            # The revert changed what terranx.exe is (the kept original back, or the clean PRACX
            # copy left): the rule for it runs on the folder as it is now. Its foreign shape was
            # refused at plan time, so this only moves or drops.
            candidates = _install_candidates(game_dir)
            moves += apply_backup_plan(plan_backups(game_dir, candidates, None))
    except BaseException as e:
        # Before the set-up is applied nothing but the backup moves and Thinker's own swap happened (a set-up that
        # fails or is stopped rolls itself back): both go back, and the folder is as the run found it. Once a first
        # Thinker install's set-up IS applied (a Ctrl-C in the copy-back after it), Thinker stays with it, as after
        # the patch pass (verification 2026-11-15).
        undo_backup_moves(moves)
        if tstep.prep is not None and tstep.prep.committed:
            if new_thinker and thinker_plan and thinker_plan.get("applied"):
                _keep_new_thinker(tstep.prep, e)
            else:
                thinker_flow.undo(tstep.prep)
                ix.say("  Thinker Mod was put back as it was.")
        raise
    try:
        _patched = _install_patch_pass(game_dir, args, candidates)
    except BaseException as e:
        if tstep.prep is not None and tstep.prep.committed:
            if new_thinker:
                _keep_new_thinker(tstep.prep, e)
            else:
                thinker_flow.undo(tstep.prep)
                ix.say("  Thinker Mod was put back as it was.")
        raise
    results, patched, spec, target_id, companion_results = _patched
    thinker_flow.clear_dont_ask(game_dir)             # decision K
    # The resident updater BEFORE uimod.dll: a new DLL beside an old installer copy would send the
    # in-game "Update now" to an installer that does not know its arguments (round-5 finding J4).
    resident_error = _deploy_resident(game_dir)
    if not deploy_runtime(game_dir):
        raise ix.InstallerError(
            "The game was patched, but copying Longevity Vaccine's files into place failed.",
            changed=True,
            remedy="close the game if it is running and re-run the installer.")
    if tstep.prep is not None:
        thinker_flow.tu.set_step(game_dir, 5)
    text_results = patch_datalinks_text(game_dir)
    icon_results = patch_pracx_icons(game_dir)
    ddraw_status = wine_ddrawcompat(game_dir)
    if tstep.prep is not None:
        thinker_flow.finish(tstep.prep)
        thinker_flow.report_change(game_dir, tstep.prep, args)    # the summary; the thinker.ini choice closes the run
    return _install_rest(game_dir, args, results, patched, spec, target_id, companion_results, text_results,
                         catalogue, manifest, chosen, turned_down, ticked_now, tstep,
                         resident_error=resident_error, icon_results=icon_results, ddraw_status=ddraw_status)


def _unsupported_folder(game_dir: Path, names: list) -> "ix.InstallerError":
    """No exe here is one this mod can patch: the patch pass's refusal, and _install's before any question."""
    # Only MEASURED launch targets may be advertised. Listing a declared-but-unmeasured one
    # tells a Thinker user "Supported: ... Thinker ..." and then refuses their exe, which is
    # self-contradictory and unactionable.
    try:
        labels = [t.label for t in _targets().values() if t.launch and t.measured]
    except Exception:  # noqa: BLE001 - explaining a failure must not become a second failure
        labels = []
    return ix.InstallerError(
        "No game executable this mod can patch was found in the game folder.",
        code=ix.EXIT_UNSUPPORTED,
        detail="Longevity Vaccine is built for: " + ", ".join(labels) + ".\n"
               + "Found: " + ", ".join(f"{n} (MD5 {_md5_safe(game_dir / n)})" for n in names) + ".",
        remedy="install the GOG Planetary Pack with the PRACX patch, or report your "
               "executable's MD5 so it can be added.")


def _saying_thinker_state(run, game_dir: Path, args) -> int:
    """`run` (the setup or the update), and when it is stopped (Ctrl-C) with a Thinker Mod change committed and not
    put back -- past the patch pass, where it is never undone -- the console says what the folder holds (verification
    of f076f34, 2026-11-15: the verdict said only "You interrupted"). The user-approved line of _keep_new_thinker."""
    import thinker_flow
    thinker_flow.LAST_COMMITTED = None
    try:
        return run(game_dir, args)
    except KeyboardInterrupt:
        prep = thinker_flow.LAST_COMMITTED
        if prep is not None and prep.committed and not getattr(prep, "state_said", False):
            ix.say(_THINKER_STAYS.format(ts=prep.ts))
        raise


#: User-approved (2026-11-15): a Thinker Mod change that stays while Longevity Vaccine is not finished.
_THINKER_STAYS = ("  Thinker Mod {ts} was installed and stays in the game folder. Run the installer again to finish "
                  "installing Longevity Vaccine.")


def _keep_new_thinker(prep, e: BaseException) -> None:
    """A first Thinker install (B) whose patch pass failed or was stopped: Thinker Mod STAYS (code review
    2026-11-15). By now the folder may be set up for it (terranx.exe the PRACX copy Thinker's launcher starts, the
    original kept) and the pass may have written terranx.exe as the pracx_thinker build. Taking Thinker out again
    would leave a set-up, or a Thinker build of the exe, with no Thinker -- states nothing else produces -- and
    undoing those too is a second multi-file revert inside an error path, where its own failure is worse. Kept,
    the folder is one with Thinker Mod installed, which every later run and the game handle, and which the player
    asked for. The change is finished (no journal for the next run to roll), and the console says so."""
    import thinker_flow
    thinker_flow.finish(prep)
    ix.say(_THINKER_STAYS.format(ts=prep.ts))
    prep.state_said = True
    if isinstance(e, ix.InstallerError):
        e.changed = True                    # never "nothing on disk was changed": Thinker Mod was installed


def _deploy_resident(game_dir: Path):
    """Make the installer RESIDENT; the error, or None. Never raises: a resident copy is not worth
    failing the install for.

    Without it the in-game update prompt has nothing to spawn once the player deletes their
    download, and whatever they kept would be the version they first installed -- while
    patches.yaml changes every release."""
    # Said BEFORE the copy: it is the slowest step after the questions, and a silent console
    # right after the shortcut question read as a hang (user 2026-11-04).
    ix.say("")
    ix.say("Setting up Longevity Vaccine's updater in the game folder (this can take a minute)...")
    try:
        import bootstrap as bsmod
        bsmod.reconcile(game_dir, say=ix.say)
        # Quiet: "resident updater deployed: <long temp path> (v0.1.0, 8 component(s))" is
        # bookkeeping; a failure is reported by _install_rest.
        bsmod.deploy(game_dir, payload_root(), ver.VERSION, say=lambda *a: None)
        if not bsmod.is_usable(bsmod.updater_dir(game_dir)):
            raise OSError("missing " + ", ".join(bsmod.missing_parts(bsmod.updater_dir(game_dir))))
    except Exception as e:  # noqa: BLE001
        return e
    return None


def _install_patch_pass(game_dir: Path, args, candidates):
    """The patch pass of a first-time install: (results, patched, spec, target_id, companion_results)."""
    with fresh_patch_log(game_dir):
        results = {p.name: patch_target(p, args.force) for p in candidates}
        if any(v == "error" for v in results.values()):
            raise ix.InstallerError(
                "A patch step failed, so the installer stopped before deploying anything.",
                detail="\n".join(f"  {n}: {s}" for n, s in results.items()),
                # NOT changed=True. An "error" can come from apply_patches long before any write
                # (a missing patches.yaml, a missing target), and telling the user their exe may be
                # half-patched -- and to restore a .bak that does not exist -- is worse than saying
                # we do not know. None renders the honest "not certain how far it got" wording.
                changed=None,
                remedy="re-run the installer; if it keeps failing, report the output above.")
        if not any(v in ("patched", "already-patched") for v in results.values()):
            raise _unsupported_folder(game_dir, list(results))

        # Which target was actually applied. Resolved ONCE here, then used for the companions and the
        # receipt alike, so the two can never disagree about what is installed.
        # With two patched candidates (a Thinker folder that also keeps terranx_PRACX.exe) the one the
        # player's launcher runs -- the configuration with a `launcher` -- is the installation; the
        # candidate ORDER (config.exe_name()) used to decide, and on a machine whose game-exe.txt names
        # terranx_PRACX.exe the receipt, play note and shortcut all bypassed Thinker (audit 2026-10-29).
        patched, spec = None, None
        for n, s in results.items():
            if s not in ("patched", "already-patched"):
                continue
            try:
                bak = game_dir / (n + ".bak")
                probe = bak if bak.is_file() else game_dir / n
                cand = ap.resolve_target(_md5_safe(probe, changed=True), _targets(),
                                         launch_only=True, present_files=ap.folder_files(game_dir),
                                         exe_name=n)
            except (ap.UnsupportedBase, ix.InstallerError):
                cand = None
            if patched is None or (cand is not None and getattr(cand, "launcher", None)
                                   and not (spec is not None and getattr(spec, "launcher", None))):
                patched, spec = n, cand
        target_id = spec.id if spec else None
        # The update-check answer, the moment the exe is patched: from here the folder counts as installed
        # (_has_install), so a re-run would not ask again -- an answer lost to a later failure (a copy, a
        # download, Ctrl+C) would leave the game checking against a stated "no" (audit 2026-11-06). Every
        # refusal that says the game was not modified comes before this line.
        write_update_check(game_dir, _PENDING_UPDATE_CHECKS)
        apply_pending_choices(game_dir)                   # a first install's list answers, for the same reason (audit-t)
        companion_results = patch_companions(game_dir, spec, args.force) if spec is not None else {}
    return results, patched, spec, target_id, companion_results


_PENDING_UPDATE_CHECKS = None


def place_packs(game_dir: Path, args, chosen: list, catalogue: dict, manifest, target_id, target: Path,
                recorded: dict) -> tuple:
    """The chosen optional modules. A local pack (a checkout) is copied; the rest are downloaded through the same
    verified path the update uses. A pack that fails never fails the install: the mod is complete without it, and the
    game's update prompt offers it again.

    A pack already installed is downloaded or copied again only when it needs it (user 2026-11-17, pack_action): a
    newer release, or a listed file missing or the wrong size. One that is current and intact is left alone -- before
    this, a re-run fetched the whole 1.39 GB Cinematics archive again -- and gets no receipt entry here, so the
    receipt keeps the one it has. `recorded` is the receipt's version of each pack when the run began.

    Returns ({name: receipt entry} for what was placed, {name: "ok" | "error" | "skip"}, {name: pack_action's word}).
    """
    pack_status = {n: "skip" for n in GAME_CONTENT_MODULES}
    installed_packs = {}
    how = {n: pack_action(game_dir, n, catalogue.get(n, {}).get("version"), recorded.get(n),
                          catalogue.get(n, {}).get("release_manifest"),
                          catalogue.get(n, {}).get("release_provenance")) for n in chosen}
    kept = ("keep", "adopt")
    for n in chosen:
        if how[n] in kept:
            pack_status[n] = "ok"
            v = recorded.get(n) if how[n] == "keep" else catalogue[n]["version"]
            if how[n] == "adopt":
                installed_packs[n] = {"version": v}       # the release in the folder, now in the receipt (audit-n)
                _record_landed(game_dir, n, installed_packs[n], target_id)     # at once (audit-t ROOT 4)
            # User-approved wording 2026-11-17: the kept pack's own section, then its credit as on install.
            ix.say(f"\n--- {_pack_label(n)} ---")
            ix.say(f"  v{v} is already installed; nothing was downloaded.")
            ix.say(PORTRAIT_ART_CREDIT if n == "portraits-hd" else CINEMATICS_CREDIT)
    local = [n for n in chosen if catalogue.get(n, {}).get("source") == "local" and how[n] not in kept]
    remote = [n for n in chosen if catalogue.get(n, {}).get("source") == "manifest" and how[n] not in kept]
    # Pending until it lands (audit-q M3): a download that fails -- or a run stopped before it -- leaves the pack marked
    # as chosen, so the next run starts it ticked and completes it. Cleared below per pack that lands.
    was_pending = {n: pack_pending(game_dir, n) for n in chosen}
    _mark_pending(game_dir, local + remote, True)
    for name in local:
        ix.say(f"\n--- {_pack_label(name)} ---")
        if how[name] == "repair" and pack_intact(game_dir, name) and not was_pending[name]:
            # Only its PROVENANCE.txt is wrong (audit-o 2026-11-17): re-placed alone, the credit line as on install.
            try:
                _copy_into_place(Path(catalogue[name]["path"]) / "PROVENANCE.txt",
                                 Path(game_dir) / MODULE_ROOTS[name][0] / "PROVENANCE.txt")
                pack_status[name] = "ok"
                installed_packs[name] = {"version": ver.module_version(name)}
                _record_landed(game_dir, name, installed_packs[name], target_id)
                ix.say(PORTRAIT_ART_CREDIT if name == "portraits-hd" else CINEMATICS_CREDIT)
            except OSError as e:
                ix.say(f"  WARNING: could not copy PROVENANCE.txt: {e}")
                pack_status[name] = "error"
            continue
        copy_pack = install_portrait_pack if name == "portraits-hd" else install_movie_pack
        if copy_pack(game_dir, catalogue[name]["path"]):
            pack_status[name] = "ok"
            installed_packs[name] = {"version": ver.module_version(name)}
            _record_landed(game_dir, name, installed_packs[name], target_id)     # at once (audit-t ROOT 4)
        else:
            pack_status[name] = "error"
    if remote:
        global _ON_LANDED
        _ON_LANDED = lambda n, e: _record_landed(game_dir, n, e, target_id)      # each pack as it lands (audit-t)
        try:
            got, statuses = install_packs_from_manifest(game_dir, args, remote, manifest, target_id, target)
        finally:
            _ON_LANDED = None
        installed_packs.update(got)
        pack_status.update(statuses)
    _mark_pending(game_dir, [n for n in chosen if pack_status.get(n) == "ok"], False)    # kept ones too (audit-r L-a)
    return installed_packs, pack_status, how


def pack_summary_status(status: str, how) -> str:
    """A pack's summary row (ix.status_line): what a setup run really did with it (user-approved 2026-11-17):
    "Already installed" (kept), "Updated", "Repaired", or "Success" for a new install; "Error" / "Skipped" as before."""
    if status != "ok":
        return status
    return {"keep": "kept", "adopt": "kept", "update": "updated", "repair": "repaired"}.get(how, "ok")


def _install_rest(game_dir: Path, args, results, patched, spec, target_id, companion_results, text_results,
                  catalogue, manifest, chosen, turned_down, ticked_now, tstep, resident_error=None,
                  icon_results=None, ddraw_status="") -> int:
    """A first-time install after the patch pass and the runtime files: packs, questions, receipt, summary."""

    import receipt as rc
    # The receipt as this run found it -- read before place_packs, which records each pack the moment it lands
    # (audit-t ROOT 4): "See what's new" and the merge below compare against the state before the run.
    before = rc.read(game_dir)
    recorded = {n: rc.module_version(before, n) for n in GAME_CONTENT_MODULES}
    installed_packs, pack_status, pack_how = place_packs(game_dir, args, chosen, catalogue, manifest, target_id,
                                                          game_dir / patched, recorded)
    # NOT inferred from disk: a folder that happens to hold files is not an installed pack, and
    # recording one at the current version would hide it from the update prompt for good
    # (audit 2026-09-27). Content left by an uninstall is re-offered and, once the archive is
    # verified, install_modules skips every file that is already current.
    # Explicit choices only (audit-t ROOT 1; audit-p LOW-1): off for a pack the player turned down or unticked
    # (installed too) or --ai off -- one left unticked by the re-run DEFAULT is not a "no" -- and on for a tick or a
    # flag; never inferred from the files. (Recorded with the answer too: _record_choices.)
    movies = "movies-hd"
    said_no = movies in turned_down or movies in unticked_packs()
    # A pack that merely lands is not a choice (audit-t fuzz fB F003: --no-prompt updating an unticked Cinematics
    # switched HD movies back on); an unset flag still counts as on (cinematics_flag).
    said_yes = movies in ticked_now or (bool(getattr(args, "modules", None)) and movies in chosen)
    set_ini_flag(game_dir, cinematics_flag([movies] if said_yes else [], game_dir, args,
                                           offered=[movies] if said_no else []))
    record_module_choice(game_dir, sorted(set(ticked_now) | {n for n, s in pack_status.items() if s == "ok"}),
                         turned_down)
    ensure_in_process_movies(game_dir)
    failed_packs = [n for n in GAME_CONTENT_MODULES if pack_status.get(n) == "error"]

    # A PRACX install carried over from before may pin an old resolution: warn, offer the fix.
    # A first install's --no-prompt is the PLAYER's (only --update workers get the bootstrap's):
    # neither question is asked, and each prints how to do it by hand.
    asks = not getattr(args, "no_prompt", False)
    check_display_resolution(game_dir, target_id, ask=asks)
    # ... and the player needs a way to start the RIGHT exe.
    check_desktop_shortcut(game_dir, target_id, ask=asks)
    global _NOTE_ARGS
    _NOTE_ARGS = (game_dir, target_id)

    # Record what was installed. Until this existed, "which release is this?" had no answer on
    # the player's disk and an update could not tell an old patch set from a current one.
    # The resident updater was deployed before uimod.dll (_deploy_resident); its failure is
    # reported here, once the mod itself is in place.
    if resident_error is not None:
        ix.say(f"  WARNING: could not install Longevity Vaccine's updater ({copy_error_summary(resident_error)}).")
        ix.say("  Longevity Vaccine itself IS installed and playable, but this copy cannot update itself:")
        ix.say("  future updates will have to be downloaded and run by hand.")

    import receipt as rc
    # MERGE with what the receipt already says: a re-run used to replace the whole module map,
    # forgetting packs that are still on disk. And the pack is recorded at ITS version
    # (version.py MODULE_VERSIONS), not the product's -- recording it as VERSION made a later
    # pack release invisible once the product version got ahead of it.
    base_before = rc.module_version(before, "base")      # "See what's new" over an older install (set on success)
    remember_whats_new(game_dir, base_before, ver.VERSION)
    mods = dict(before.get("modules") or {})
    mods["base"] = {"version": ver.VERSION}
    mods.update(installed_packs)
    rc.write(game_dir, target_id=target_id, modules=mods, say=ix.warn)   # warnings only
    # So the next run -- an --uninstall, a re-run of this download or a newer one -- finds this
    # folder by itself, wherever the player put the game.
    config.remember_game_dir(game_dir)

    # One row per thing the player cares about, coloured; the executables the folder happens
    # to hold but the mod does not touch are not rows.
    ix.say("\n--- summary ---")
    for name, st in results.items():
        if st == "unknown":
            continue
        ix.status_line(name, "ok" if st in ("patched", "already-patched")
                       else ("error" if st == "error" else "skip"))
    for name, st in companion_results.items():
        ix.status_line(name, st)
    ix.status_line("mod files", "ok")
    if text_results:
        ix.status_line("Datalinks text", datalinks_text_status(text_results))
        if datalinks_text_note(text_results):
            ix.say(datalinks_text_note(text_results))
    if icon_results:
        ix.status_line("PRACX icons", pracx_icons_status(icon_results))
    if ddraw_status in ("moved", "already"):
        ix.status_line("Wine: DDrawCompat set aside", "ok")
    elif ddraw_status in ("foreign", "failed"):
        ix.status_line("Wine: DDrawCompat set aside", "skip")
    if tstep.prep is not None:
        ix.status_line("Thinker Mod", "ok")
    elif tstep.keep:
        ix.status_line("Thinker Mod version", "skip")      # the KEEP line itself is in the verdict below, once
    for name in GAME_CONTENT_MODULES:
        # Only packs the player was offered or asked for: a row "Skipped" for a pack that was
        # never on the table (not released yet) says nothing.
        if name in catalogue or pack_status.get(name) != "skip":
            ix.status_line(_pack_label(name), pack_summary_status(pack_status.get(name, "skip"), pack_how.get(name)))
    # Remember where the game is so the guard can offer to launch it -- also after a partly complete
    # install, which leaves the game patched and ready to play (user 2026-11-14: every outcome that
    # changed the game offers to start it).
    global _LAUNCH_EXE
    # The program that plays WITH the mod: the target's launcher where it has one (thinker.exe --
    # starting terranx.exe directly would skip Thinker, right after the play note said otherwise;
    # audit 2026-10-28), else the exe we just patched. Never an exe we refused as unsupported.
    _LAUNCH_EXE = None
    if target_id and any(results.get(n) in ("patched", "already-patched") for n in _exe_names()):
        _LAUNCH_EXE = mod_exe(game_dir, target_id)
    if _LAUNCH_EXE is None:
        _LAUNCH_EXE = next((game_dir / n for n in _exe_names()
                            if (game_dir / n).exists()
                            and results.get(n) in ("patched", "already-patched")), None)
    if failed_packs:
        # Same shape as do_update's partial outcome: the mod IS installed, the pack the player
        # asked for is not, and a scripted caller must see a non-zero code for that.
        shown = " and ".join(_pack_label(n) for n in failed_packs)
        raise ix.InstallerError(
            f"Longevity Vaccine {ver.VERSION} is installed. {shown} "          # user 2026-11-15
            f"{'was' if len(failed_packs) == 1 else 'were'} not installed.",
            code=ix.EXIT_ERROR, changed=True, title="INSTALLATION PARTLY COMPLETE",
            disk_note="The game is patched and ready to play; only the optional download is missing.",
            remedy="run the installer again, or take the pack from the game's update prompt.",
            offer_play=True, offer_play_default=True)

    import thinker_flow             # the verdict below names its directions (local, like every caller here)
    add = ""
    tp = tstep.prep
    global _THINKER_NEW
    _THINKER_NEW = bool(tp is not None and tp.new)
    if tp is not None and getattr(tp, "repair", 0):
        tp = None                                                 # a repair says itself (its summary line)
    if tp is not None and tp.new:
        add = f" Thinker Mod {tp.ts} was installed."              # B (user 2026-11-15)
    elif tp is not None:
        add = {thinker_flow.st.UP: f" Thinker Mod was updated to {tp.ts}.",
               thinker_flow.st.DOWN: f" Thinker Mod was downgraded to {tp.ts}.",
               thinker_flow.st.OTHER: f" Thinker Mod {tp.ts} was installed in place of "
                                      f"{thinker_flow.st.yours(tp.dll.label, tp.ts)}."}[tp.direction]
    if tstep.keep:
        add += " " + tstep.keep
    global _VERDICT
    # User 2026-11-14: "Longevity Vaccine 1.0.0 is installed." -- no "The", the version.
    _VERDICT = ("INSTALLATION SUCCESSFUL", f"Longevity Vaccine {ver.VERSION} is installed." + add)
    finish_whats_new(game_dir, base_before, ver.VERSION)     # a fresh install deletes a leftover (audit-h M2)
    thinker_flow.settle_install_record(game_dir)     # audit-f H2: an unfinished "Also uninstall" is over
    return 0


#: Set by main() once the game dir is known, so run_guarded can offer a relaunch on success.
_LAUNCH_EXE: Path = None
_PROCESS_START = __import__("time").time()     # CL: a Thinker change recorded before this is not this run's


def _handover():
    """run_guarded's hand-over hook: (start, on_failure) when --fix-thinker handed over, else None."""
    import thinker_flow
    h = thinker_flow.pending_handover()
    if h is None:
        return None
    gd = _NOTE_ARGS[0] if _NOTE_ARGS else None
    return (lambda: thinker_flow.handover_spawn(h),
            lambda: thinker_flow.handover_failed(Path(h.cwd)))
_CRASH_LOG_GAME_DIR: Path = None   # set by main() once the game folder is resolved (crash_log_dir)


def crash_log_dir():
    """Where run_guarded writes install-crash-<stamp>.log: the game's LongevityMods\\logs once the folder is
    known (the folder a bug report is asked to attach), else None = beside the script (audit 2026-11-07: the
    default landed in the extracted download or in an updater generation the next update deletes)."""
    if not _CRASH_LOG_GAME_DIR:
        return None
    d = _CRASH_LOG_GAME_DIR / "LongevityMods" / "logs"
    import safe_fs
    # Never written through a link (audit-g LOW-7): the %TEMP% folder instead, as for an unwritable one.
    return Path(tempfile.gettempdir()) if safe_fs.link_on_path(Path(_CRASH_LOG_GAME_DIR), d) else d

#: (title, body) for the success verdict, when this run was not an install. Defaults to the
#: install wording.
_VERDICT = None

#: A Ctrl-C during --uninstall (user-approved wording 2026-11-16): (title, body, closing line) for run_guarded.
UNINSTALL_CANCELLED = ("UNINSTALL CANCELLED", "You interrupted the uninstall (Ctrl-C).",
                       "Run the uninstall again to finish it.")
#: Set by main() for an --uninstall; None keeps run_guarded's own "INSTALLATION CANCELLED".
_CANCELLED = None


if __name__ == "__main__":
    # --check is the GAME's query over a pipe: it has its own guarantee (an exit code, always;
    # protocol lines or nothing on stdout) and must never print a banner or wait for a key.
    if "--check" in sys.argv[1:]:
        sys.exit(check_main())
    # EVERY other exit goes through run_guarded: it prints a verdict for success, expected
    # failure, Ctrl-C and unhandled exceptions alike, and waits for a keypress before the window
    # closes. Nothing here may call sys.exit() directly.
    sys.exit(ix.run_guarded(
        main,
        relaunch_exe=lambda: _LAUNCH_EXE,
        success_title=lambda: _VERDICT[0] if _VERDICT else None,
        success_body=lambda: _VERDICT[1] if _VERDICT else None,
        success_after=_success_after,
        cancelled=lambda: _CANCELLED,
        log_dir=crash_log_dir,
        handover=_handover))
