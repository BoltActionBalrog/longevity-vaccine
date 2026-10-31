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
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent       # ...\work\scripts
sys.path.insert(0, str(_SCRIPTS))
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
                   "it -- running it from inside the zip is the usual cause.")
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


def _thinker_needs_renaming(target: Path, spec) -> bool:
    """True when thinker.dll sits beside a PRACX exe that Thinker's launcher will never start AND no
    file of the launcher's name in the folder is PRACX already (clean, ours, or ours with its .bak).
    With such a file present the folder is already set up for Thinker; a second PRACX exe under
    another name is just a plain install beside it (audit 2026-10-29: the note contradicted the
    line printed for terranx.exe two lines earlier)."""
    ov = _overlay_of(spec)
    if ov is None or not ov.exe or target.name.lower() == ov.exe.lower():
        return False
    other = target.parent / ov.exe
    if not other.is_file():
        return True
    known = {ov.base_md5, ov.patched_md5, spec.patched_md5} - {None}
    try:
        if _md5_safe(other, changed=False) in known:
            return False
        obak = other.with_suffix(other.suffix + ".bak")
        if obak.is_file() and _md5_safe(obak, changed=False) == ov.base_md5:
            return False
    except Exception:  # noqa: BLE001 - a note must never fail the install
        return True
    return True


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
                    ix.say("  already patched (backup is a supported clean base) -- skipping."
                           " Use --force to re-patch.")
                    return "already-patched"
                if not current:
                    ix.say(f"  not the build this installer produces for this folder (a different configuration, or an "
                           f"older build) -> restoring from .bak, then re-patching as {bak_spec.label}...")
                    # Those live bytes may be a player's own edit or another tool's work on top of ours:
                    # never destroy them (audit 2026-10-29) -- keep them beside, named by their hash.
                    keep = target.with_name(f"{target.name}.replaced-{md5[:8]}")
                    if not keep.exists():
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
    elif "thinker.dll" in beside and _thinker_needs_renaming(target, spec):
        ov = _overlay_of(spec)
        ix.say(f"  thinker.dll found beside it, but Thinker starts only a file named {ov.exe} -> patched as "
               f"plain {spec.label}. To play with Thinker and the mod, the PRACX executable must be {ov.exe}.")
    ix.say(f"  patching (clean {spec.label})")
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


def _patch_summary(status: str, text: str) -> None:
    """apply_patches' per-phase report line, coloured: green SUCCESS, red ERROR, plain otherwise."""
    if status == "ok":
        ix.good("  " + text)
    elif status == "error":
        ix.bad("  " + text)
    else:
        ix.say("  " + text)


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
            ix.say("  already patched -- skipping. Use --force to re-patch.")
            out[live.name] = "ok"
            continue
        if state == C_FOREIGN:
            # Someone else's build -- a newer PRACX, most likely. Restoring OUR backup over it
            # would silently downgrade their install, so never touch it.
            ix.say(f"  MD5 {md5} is not a build this patch set knows -- leaving it alone.")
            ix.say("  (the mod works without it; only the PRACX edge-scroll fix is missed)")
            continue
        if state != C_CLEAN:
            bak = _verified_backup(live, cspec, changed=True)
            if bak is None:
                ix.say(f"  {live.name} is patched but its backup is missing or is not the "
                       f"original -- leaving it alone.")
                ix.say("  (the mod works without it; only the PRACX edge-scroll fix is missed)")
                continue
            ix.say(f"  restoring from the verified {bak.name}, then patching...")
            if ap.restore(live) != 0:
                ix.warn("  WARNING: could not restore it from .bak; leaving it alone.")
                continue
            if _md5_safe(live, changed=True) != cspec.base_md5:
                ix.warn("  WARNING: the restored file is not the clean base; leaving it alone.")
                continue

        if ap.apply_patches(live, cpatch, do_apply=True, spec=cspec, summary=_patch_summary) != 0:
            ix.warn(f"  WARNING: patching {live.name} failed; the mod still works without it.")
            out[live.name] = "error"
            continue
        got = _md5_safe(live, changed=True)
        if cspec.patched_md5 and got != cspec.patched_md5:
            ix.bad(f"  ERROR: patched MD5 {got} != expected {cspec.patched_md5}")
            out[live.name] = "error"
            continue
        out[live.name] = "ok"
    return out


#: Thinker's build. Every detour the mod makes into thinker.dll is pinned to one build (version.py
#: THINKER_SUPPORTED_*); the game shows a dialog in these same words on any other build (uimod thinkerversion.cpp),
#: and the installer says it here so the player learns it before the first launch. A warning only: the install is
#: complete and correct either way.
def thinker_build(game_dir: Path):
    """(stamp, image size, label) of the folder's thinker.dll, or None when there is none. An unreadable PE
    reads as (None, None, 'an unreadable thinker.dll')."""
    p = game_dir / "thinker.dll"
    if not p.is_file():
        return None
    try:
        data = p.read_bytes()
        if data[:2] != b"MZ":
            raise ValueError("no MZ header")
        pe = int.from_bytes(data[0x3C:0x40], "little")
        if data[pe:pe + 4] != b"PE\0\0":
            raise ValueError("no PE signature")
        if len(data) < pe + 0x54:
            raise ValueError("truncated PE header")   # a short slice would read as 0, not raise
        stamp = int.from_bytes(data[pe + 8:pe + 12], "little")
        size = int.from_bytes(data[pe + 0x50:pe + 0x54], "little")
    except (OSError, ValueError, IndexError):
        return None, None, "an unreadable thinker.dll"
    m = re.search(rb"Thinker Mod v(\d+(?:\.\d+)*)", data)
    label = f"Thinker Mod v{m.group(1).decode('ascii')}" if m else "an unrecognised build of Thinker Mod"
    return stamp, size, label


def thinker_build_warning(game_dir: Path) -> str:
    """The warning text for a thinker.dll that is not the supported build, or '' (none / supported)."""
    import manifest
    found = thinker_build(game_dir)
    if found is None:
        return ""
    stamp, size, label = found
    if stamp == ver.THINKER_SUPPORTED_STAMP and size == ver.THINKER_SUPPORTED_IMAGE_SIZE:
        return ""
    return (f"Longevity Vaccine {ver.VERSION} was built for Thinker Mod {ver.THINKER_SUPPORTED_VERSION}. "
            f"This game folder's thinker.dll is {label}. Some game features may not work as intended. "
            f"We recommend checking for a Longevity Vaccine update in-game or at {manifest.DOWNLOAD_URL}. "
            "If no update exists, consider playing with the officially supported version of Thinker.")


def warn_thinker_build(game_dir: Path) -> bool:
    """Print the thinker.dll build warning when one applies. Returns True when it did."""
    text = thinker_build_warning(game_dir)
    if not text:
        return False
    ix.say("")
    ix.warn("  WARNING: " + text)
    return True


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
        ix.warn(f"  WARNING: the Datalinks text patch is missing from this installer ({type(e).__name__}: {e}) "
                "-- skipped; the mod works without it.")
        return {}
    ix.say("\n--- Datalinks text ---")
    try:
        res = ph.patch_folder(game_dir, say=lambda t: ix.say("  " + t))
    except OSError as e:
        ix.warn(f"  WARNING: could not update the Datalinks text ({e}); the mod works without it.")
        return {}
    if not res:
        ix.say("  no helpx.txt / conceptsx.txt in the game folder -- skipped")
    return res


def restore_datalinks_text(game_dir: Path) -> int:
    """--uninstall: the .longevity.bak copies go back wherever the live text is ours. Returns the count restored."""
    try:
        import patch_helptext as ph
    except Exception as e:  # noqa: BLE001
        ix.warn(f"  WARNING: the Datalinks text patch is missing from this installer ({type(e).__name__}: {e}) "
                "-- its text files were not restored.")
        return 0
    res = ph.restore_folder(game_dir, say=lambda t: ix.say("  " + t) if "restored" in t or "left alone" in t else None)
    failed = [n for n, s in res.items() if s == ph.FAILED]
    if failed:
        ix.warn(f"  WARNING: could not restore {', '.join(failed)} -- close the game and run --uninstall again.")
    return sum(1 for s in res.values() if s == ph.RESTORED)


def datalinks_text_status(res: dict) -> str:
    """One summary word for the table: ok when any file found took (or already had) the text, else skip. A file
    left alone beside patched ones is named under the row (datalinks_text_note), not hidden behind a Skipped."""
    return "ok" if res and any(s in ("patched", "current") for s in res.values()) else "skip"


def datalinks_text_note(res: dict) -> str:
    """The files patch_folder left alone, for the line under the summary row; '' when none."""
    left = sorted(n for n, s in res.items() if s not in ("patched", "current"))
    return f"  ({', '.join(left)} left alone: not the stock text)" if left else ""


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


def install_movie_pack(game_dir: Path, pack: Path) -> bool:
    """Copy the prebuilt HD mp4 pack into <game>\\movies\\hd."""
    mp4s = sorted(pack.glob("*.mp4")) if pack.is_dir() else []
    if not mp4s:
        print(f"  WARNING: no .mp4 found in {pack} -- the HD pack is empty.")
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
        ix.say("           The mod is installed; cinematics stay on the original .wve.")
        return False
    copied = 0
    for f in mp4s:
        try:
            shutil.copy2(f, dst / f.name)
        except OSError as e:
            ix.say(f"  WARNING: could not copy {f.name}: {e}")
            ix.say(f"           Copied {copied} of {len(mp4s)}. The mod itself is installed;"
                   " re-run to finish the pack.")
            return False
        copied += 1
    ix.say(f"  copied {copied} cinematic(s) -> {dst}")
    return True


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
    files = sorted({p for g in _PORTRAIT_PACK_GLOBS for p in pack.glob(g) if p.is_file()}) if pack.is_dir() else []
    if not any(p.suffix.lower() == ".png" for p in files):
        ix.say(f"  WARNING: no portraits found in {pack} -- the pack is empty (work\\scripts\\art\\build_portraits_hd.py).")
        return False
    dst = Path(game_dir) / "portraits" / "hd"
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        ix.say(f"  WARNING: could not create {dst}: {e}")
        return False
    copied = 0
    for f in files:
        try:
            shutil.copy2(f, dst / f.name)
        except OSError as e:
            ix.say(f"  WARNING: could not copy {f.name}: {e}")
            ix.say(f"           Copied {copied} of {len(files)}. Re-run to finish the pack.")
            return False
        copied += 1
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
    in-process player and the HD cinematics; an auto-detected or hand-set external player is
    overridden without a notice). Written whether or not Thinker is installed so that adding Thinker
    later cannot hand the movies to VLC on its first launch. Idempotent; never raises."""
    if read_ini_str(game_dir, THINKER_MOVIE_SECTION, THINKER_MOVIE_KEY, _INI_ABSENT) == "":
        return
    if not write_ini_str(game_dir, THINKER_MOVIE_SECTION, THINKER_MOVIE_KEY, ""):
        ix.warn(f"  WARNING: could not write [{THINKER_MOVIE_SECTION}] {THINKER_MOVIE_KEY}= to "
                f"{_ini_path_str(game_dir)}; under Thinker the cinematics may play through an external player.")


def release_in_process_movies(game_dir: Path) -> None:
    """--uninstall: delete the key when it is still the blank we wrote, so Thinker starts from "absent"
    on its next launch and re-runs its own player detection exactly as a fresh Thinker install does
    (a blank is the one value Thinker never re-initialises). A value the player changed since is left
    alone. Nothing of ours is remembered across the install (user decision 2026-10-28)."""
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


def check_display_resolution(game_dir: Path, target_id, no_prompt: bool = False) -> None:
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
    if not ix.can_ask():
        ix.say("Set [PRACX] ScreenWidth and ScreenHeight to <DEFAULT> in Alpha Centauri.ini to fix this.")
        return
    left = ("Left your resolution as is. Your game will likely appear stretched until you fix this! "
            "Set [PRACX] ScreenWidth and ScreenHeight to <DEFAULT> in Alpha Centauri.ini.")
    try:
        ans = input("Let the installer set the game to your display's resolution? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        ix.warn(left)
        return
    if ans not in ("", "y", "yes"):
        ix.warn(left)
        return
    ok = write_ini_str(game_dir, "PRACX", "ScreenWidth", "<DEFAULT>") and \
        write_ini_str(game_dir, "PRACX", "ScreenHeight", "<DEFAULT>")
    if ok:
        ix.say(f"[PRACX] ScreenWidth/ScreenHeight = <DEFAULT>: the game now follows your display ({display[0]}x{display[1]}).")
    else:
        ix.say("WARNING: could not write Alpha Centauri.ini; set [PRACX] ScreenWidth and ScreenHeight to <DEFAULT> by hand.")


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
    """Is the pack's content already in the game folder (left by an uninstall, say)?"""
    for rel in MODULE_ROOTS.get(name, ()):
        d = Path(game_dir) / rel
        try:
            if d.is_dir() and any(p.is_file() for p in d.rglob("*")):
                return True
        except OSError:
            pass
    return False


def _dir_size(d: Path) -> int:
    try:
        return sum(p.stat().st_size for p in Path(d).rglob("*") if p.is_file())
    except OSError:
        return 0


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
        catalogue["movies-hd"] = {"size": _dir_size(pack), "source": "local", "path": pack}
    ppack = Path(args.portrait_pack) if getattr(args, "portrait_pack", None) else default_portrait_pack()
    if ppack.is_dir() and any(ppack.glob("*.png")):
        catalogue["portraits-hd"] = {"size": _dir_size(ppack), "source": "local", "path": ppack}

    interactive = args.ai == "ask" and ix.can_ask()
    need = bool(args.modules) or interactive or (args.ai == "on" and "movies-hd" not in catalogue)
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
                if mfmod.size_ok(size) and size > 0 and isinstance(info.get("url"), str):
                    catalogue[name] = {"size": int(size), "source": "manifest"}
        except ix.InstallerError as e:
            ix.say(f"Optional modules could not be listed: {e.message.rstrip('.')}. "
                   "You can add them later from the game's update prompt.")
        except mfmod.ManifestError:
            ix.say("Optional modules could not be listed: the update information did not verify. "
                   "You can add them later from the game's update prompt.")
    for name in catalogue:
        catalogue[name]["on_disk"] = pack_on_disk(game_dir, name)
    return catalogue, manifest


def choose_modules(catalogue: dict, args, game_dir: Path) -> list:
    """Which optional modules to install.

    Flags decide unattended (`--modules a,b`, `--ai on|off`); otherwise the player picks from a
    numbered list and the installer WAITS for the answer -- an install must not run past this
    point on its own (user, 2026-09-27). Enter takes everything listed.
    """
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
        return wanted
    if args.ai == "on":
        return ["movies-hd"] if "movies-hd" in catalogue else []
    if args.ai == "off" or not names:
        return []
    if not ix.can_ask():
        # Unattended: a first install takes the headline pack, a re-run keeps the earlier choice
        # (set_ini_flag runs every time, and a hardcoded default here once reversed an opt-out).
        state = ini_flag_state(game_dir, "UpscaledVideos")
        return ["movies-hd"] if (state is None or state) and "movies-hd" in names else []

    ix.say("Optional modules (downloaded after the game is patched):")
    for i, n in enumerate(names, 1):
        c = catalogue[n]
        note = "   already on disk" if c.get("on_disk") else ""
        ix.say(f"  {i}. {_pack_label(n):<22}{human_size(c['size']):>8}{note}")
    # No implicit default: Enter re-asks. Every earlier prompt trains Enter as "yes", and a
    # reflex Enter here would commit to gigabytes (audit 2026-09-27). Ctrl-C is NOT an answer:
    # it propagates to run_guarded, which cancels with nothing changed.
    while True:
        try:
            ans = input('Type the numbers of the modules to install (for example "1 2"), '
                        '"all", or "none": ').strip().lower()
        except EOFError:
            ix.say("Selected: none")
            return []
        if ans in ("all", "a"):
            picks = list(range(1, len(names) + 1))
        elif ans in ("none", "n", "0"):
            picks = []
        else:
            toks = ans.replace(",", " ").split()
            if not toks or not all(t.isascii() and t.isdigit() and len(t) < 4
                                   and 1 <= int(t) <= len(names) for t in toks):
                ix.say(f'Please type numbers between 1 and {len(names)}, "all", or "none".')
                continue
            picks = sorted({int(t) for t in toks})
        chosen = [names[i - 1] for i in picks]
        ix.say("Selected: " + (", ".join(_pack_label(n) for n in chosen) if chosen else "none"))
        return chosen


def cinematics_flag(chosen: list, game_dir: Path, args, offered: list = ()) -> bool:
    """[UIMod] UpscaledVideos: play the HD clips when they are present.

    On when the pack was chosen, forced (`--ai on`) or is already on disk. Off when the player
    was shown the pack (`offered`) and did not take it, or said `--ai off`. Otherwise -- the
    pack could not be listed, or nobody was asked -- a first install leaves it on (harmless
    without the clips, and they play the moment a later run adds them) and a re-run keeps the
    player's earlier choice.
    """
    if "movies-hd" in chosen or args.ai == "on" or pack_on_disk(game_dir, "movies-hd"):
        return True
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
        # Just the header: "This will patch the game ..." on an update read as a threat, and the
        # update flow says what it is doing line by line (waiting / updating / the verdict).
        # (--generation: the bootstrap's second generation, which has no --update on its line.)
        return
    print("This will patch the game, installing features such as high-resolution UI, crash fixes, "
          "and quality of life changes. Your original game .exe will be backed up (.bak) and can be "
          "restored at any time.\n")


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
    "movies-hd": "HD cinematics",
    "portraits-hd": "Longevity HD Portrait Pack",
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
        try:
            with zipfile.ZipFile(archive) as z:
                root = Path(game_dir).resolve()
                for info in z.infolist():
                    if info.is_dir():
                        continue
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
            ix.say(f"  WARNING: {name} could not be read ({e}) -- skipping this module.")
            continue
        ix.say(f"  {copied} file{'s' if copied != 1 else ''} copied, {skipped} already current"
               + (f", {failed} FAILED" if failed else ""))
        if failed:
            ix.say(f"  {name} is incomplete; re-run the installer to finish it.")
            continue
        if name in PRUNED_MODULES:
            for rel in MODULE_ROOTS.get(name, ()):
                keep = {Path(m).name for m in files if Path(m).parent.as_posix().lower() == rel.lower()}
                pruned = prune_pack_dir(game_dir, rel, keep)
                if pruned:
                    ix.say(f"  removed {pruned} file{'s' if pruned != 1 else ''} the new pack no longer carries")
        if name == "portraits-hd":
            ix.say(PORTRAIT_ART_CREDIT)
        out[name] = {"version": versions.get(name, ver.UNKNOWN), "files": files}
    return out


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
            remedy="update manifests are fetched over https -- check the address, or leave "
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
                   quick: bool = False):
    """Return (raw_bytes, signature_hex). `source` may be a URL or a local path.

    `quick`: one attempt with a short timeout -- for `--check`, whose caller (the game) kills it
    after ~10 s anyway; the default 3 attempts x 30 s x two files took minutes on a black-holed
    network."""
    import fetch as fetchmod
    import manifest as mfmod
    try:
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
        print(f"--check: {game_dir} is not writable; caching the manifest under {staging}",
              file=sys.stderr)
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
                for p in (m_dest, s_dest):
                    p.with_suffix(p.suffix + ".part").unlink(missing_ok=True)
                fetchmod.download(src, m_dest, label="manifest", **kw)
                fetchmod.download(sig_url, s_dest, label="signature", **kw)
        except fetchmod.FetchError as e:
            # Whatever landed (a manifest without its .sig, a .part) is unverified: never leave it
            # for --offline or the next check to trip over.
            discard_staged_manifest(game_dir)
            # The technical reason goes to stderr for a developer reading a log; the player gets
            # one plain sentence and one thing to do (the URL/errno soup read as a fault of theirs).
            if quick:
                print(f"  ({e})", file=sys.stderr)
            raise ix.InstallerError(
                "Could not reach the update server.",
                code=ix.EXIT_ABORTED, title="UPDATE FAILED",
                disk_note="Check your connection and try again later.")
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
                (staging / name).unlink(missing_ok=True)
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
    out = _ps("[Environment]::GetFolderPath('Desktop'); [Environment]::GetFolderPath('CommonDesktopDirectory')")
    return [Path(line.strip()) for line in out.splitlines() if line.strip()]


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


def create_shortcut(lnk: Path, exe: Path) -> str:
    """Write `lnk` starting `exe` from its own folder with its icon. "" on success, else why."""
    script = ("$sh = New-Object -ComObject WScript.Shell; $s = $sh.CreateShortcut(" + _ps_quote(lnk) + "); "
              "$s.TargetPath = " + _ps_quote(exe) + "; $s.WorkingDirectory = " + _ps_quote(Path(exe).parent) + "; "
              "$s.IconLocation = " + _ps_quote(str(exe) + ",0") + "; $s.Save(); Write-Output 'saved'")
    out = _ps(script)
    if "saved" in out and Path(lnk).is_file():
        return ""
    return "the shortcut could not be written to the desktop"


def check_desktop_shortcut(game_dir: Path, target_id) -> None:
    """Stop and offer a desktop shortcut to the mod's exe when the player has none. Never raises."""
    global _SHORTCUT_NAME
    try:
        exe = mod_exe(game_dir, target_id)
        if exe is None:
            return
        found = find_shortcut_to(exe)
        if found:
            _SHORTCUT_NAME = found
            return
        ix.say("")
        ix.say("You do not have a desktop shortcut that starts the game with the mod.")
        if not ix.can_ask():
            ix.say(f"Run the installer again to create one, or start {exe.name} from the game folder.")
            return
        ix.say("Create a desktop shortcut that starts the game with the Longevity Vaccine mod?")
        try:
            ans = input("[Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        if ans not in ("", "y", "yes"):
            ix.say(f"No shortcut created. Start {exe.name} from the game folder to play with the mod.")
            return
        dirs = _desktop_dirs()
        if not dirs:
            ix.warn(f"Could not find your desktop folder. Start {exe.name} from the game folder to play with the mod.")
            return
        lnk = dirs[0] / (MOD_SHORTCUT_NAME + ".lnk")
        if lnk.exists():
            ix.say(f'A desktop shortcut named "{MOD_SHORTCUT_NAME}" already exists but starts something else.')
            ix.say("Replace it?")
            try:
                ans = input("[Y/n] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans not in ("", "y", "yes"):
                ix.say(f"Left as it is. Start {exe.name} from the game folder to play with the mod.")
                return
        why = create_shortcut(lnk, exe)
        if why:
            ix.warn(f"Could not create the shortcut ({why}). Start {exe.name} from the game folder to play with the mod.")
            return
        _SHORTCUT_NAME = MOD_SHORTCUT_NAME
        ix.say(f'Created "{MOD_SHORTCUT_NAME}" on your desktop.')
    except Exception as e:  # noqa: BLE001 - never fail a finished install over a shortcut
        ix.say(f"(desktop shortcut check skipped: {e})")


def print_play_note(game_dir: Path, target_id) -> None:
    """The closing lines of every success verdict: which exe carries the mod, and the shortcut."""
    exe = mod_exe(game_dir, target_id)
    if exe is None:
        ix.good(ENJOY_LINE)
        return
    spec = _targets().get(target_id) if target_id else None
    if spec is not None and getattr(spec, "launcher", None) and exe.name.lower() == spec.launcher.lower():
        # A launcher configuration (Thinker): the patched exe IS terranx.exe, and the launcher
        # is what adds Thinker on top. "terranx.exe starts the unmodified game" would be wrong
        # here on both counts.
        ix.good(f"To play with the mod, start {exe.name} as before.")
        ix.warn(f"Starting {spec.exe} directly plays with the mod but without Thinker; the GOG Galaxy "
                "Play button and the shortcuts GOG created may do that.")
    elif target_id == "pracx":
        ix.good(f"To play with the mod, start {exe.name}.")
        # Name only the stock exes that are NOT the one carrying the mod: a PRACX exe named
        # terranx.exe (Thinker's naming, or Thinker removed again) must not be called unmodified
        # in the next breath (audit 2026-10-29).
        others = [n for n in ("terranx.exe", "terran.exe") if n.lower() != exe.name.lower()]
        ix.warn("The GOG Galaxy Play button, the shortcuts GOG created" +
                ("".join(f", {n}" for n in others) if others else "") +
                (" all" if others else "") + " start the unmodified game, without the mod.")
    else:
        ix.good(f"To play with the mod, start {exe.name}.")
        ix.warn("The GOG Galaxy Play button and the shortcuts GOG created may start a different "
                "executable, without the mod.")
    name = _SHORTCUT_NAME or find_shortcut_to(exe)
    if name:
        ix.say(f'Your desktop shortcut "{name}" starts the right one.')
    ix.good(ENJOY_LINE)

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

    check_companion_declarations()
    wait_for_game(getattr(args, "wait_pid", None))
    state = rc.read(game_dir)
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
        # A player who is current is exactly the one who has not heard about a new pack: the
        # notice used to be reachable only as a side effect of a base update.
        offer_optional_modules(game_dir, pf.doc, installed, args)
        body = ("Everything you have installed is current. Nothing was changed." if not left else
                "Nothing was changed: nothing listed for this update needed it. "
                + " and ".join(_pack_label(n) for n in left)
                + (" has" if len(left) == 1 else " have")
                + " a newer version that was not part of this update; it was left as it is.")
        _VERDICT = ("ALREADY UP TO DATE",
                    body + ("  An optional extra is available -- see \"optional extras\" above."
                            if absent_modules(pf.doc, installed) else ""))
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
        """("<label> v1.1.0 update could not be downloaded. Your <label> v1.0.0 ...", detail)"""
        label, offered, have = _pack_label(n), _offered(n), installed_modules.get(n)
        what = f"{label} v{offered}" if offered else label
        if have and have != ver.UNKNOWN:
            msg = (f"The {what} update could not be downloaded. Your {label} v{have} "
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

    ix.say("\n--- commit ---")
    spec = pf.spec
    # A companion the commit cannot resolve must NOT sink the core update.
    #
    # transact.stage_one raises when neither the live companion nor its .bak is the clean base --
    # the state a player who updated PRACX is in -- and do_update turned that into "The patched
    # binary could not be installed ... close the game and try again": the wrong file, a remedy
    # that cannot work, and an update that could never succeed again. The fresh-install path has
    # always tolerated exactly this state; the two now agree.
    companions = []
    for live, cpatch, cspec in companion_specs(game_dir, spec):
        # NOT `state`: that is the receipt dict this function reads again further down, and
        # shadowing it crashed the run AFTER the commit had already swapped the new binaries in.
        cstate, md5 = companion_state(live, cspec, _known_patched(spec, live.name))
        if cstate == C_CLEAN or _verified_backup(live, cspec) is not None:
            companions.append((live, cpatch, cspec))
        else:
            ix.say(f"  {live.name} (MD5 {md5}) is not a build this patch set knows and has no "
                   f"clean backup -- leaving it alone.")
            ix.say("  (the mod updates without it; only the PRACX edge-scroll fix is missed)")

    work = fetchmod_staging(game_dir) / "commit"
    # The patcher narrates thousands of lines; on a pack-only run it also re-verifies an exe
    # that is not changing, which read as "installed terranx_PRACX.exe" right above "Nothing
    # else needed changing". Everything goes to a log; the console gets one line per outcome.
    patch_log = _log_path(game_dir, "patch")
    try:
        with _captured(patch_log):
            tx.apply_transactional(target, Path(ap.DEFAULT_PATCHES), spec, work,
                                   companions=companions, say=print)
    except tx.CommitError as e:
        raise ix.InstallerError(
            "The patched binary could not be installed.", detail=f"  {e}",
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
            "The game was patched, but copying the mod files into place failed.",
            changed=True,
            remedy="close the game if it is running and re-run the installer.")
    # Every update run, not only the fresh install: the resident updater reaches this path on each
    # release, and the decision is "every run" (a player who added Thinker since install included).
    ensure_in_process_movies(game_dir)
    # ... and the Datalinks text follows each release's wording (its marker says which revision a file carries).
    patch_datalinks_text(game_dir)
    # A Thinker build this release was not measured on: say so here too (the game says it at start).
    warn_thinker_build(game_dir)

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
    rc.write(game_dir, target_id=spec.id, modules=merged, say=ix.say)
    rc.note_check(game_dir)

    # The core update is committed and recorded. A pack that did not land after that is still a
    # failed run -- "UPDATE COMPLETE" would be a lie about the one thing the player may have
    # run this for -- and staging is kept so the retry does not download it again.
    missing = [n for n in wanted if n not in installed_now]
    if missing:
        msgs, details = zip(*(_pack_failure(n) for n in missing))
        raise ix.InstallerError(
            f"Longevity Vaccine v{ver.VERSION} is installed and the game is ready to play. "
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
        _VERDICT = ("UPDATE COMPLETE", " and ".join(done) + " installed." + stays)
    elif done:
        _VERDICT = ("UPDATE COMPLETE", ", ".join(done) + " installed."
                    + (stays or " Nothing else needed changing."))
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
            ix.warn(f"  {_pack_label(n)} could not be downloaded. The mod is installed without it; "
                    "the game's update prompt will offer it again.")
    if all(statuses[n] == "ok" for n in names):
        try:
            import fetch as fetchmod
            fetchmod.clear_staging(game_dir)
        except Exception as e:  # noqa: BLE001 - cleanup must not fail a completed install
            ix.say(f"  (could not clear staging: {e})")
    return got, statuses


def _log_path(game_dir: Path, kind: str) -> Path:
    import time as _t
    d = Path(game_dir) / "LongevityMods" / "logs"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        d = Path(tempfile.gettempdir())
    return d / f"{kind}-{_t.strftime('%Y%m%d-%H%M%S')}.log"


class _captured:
    """Redirect stdout into a log file for the duration; the console keeps the outcome line."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        import contextlib
        self._f = open(self.path, "w", encoding="utf-8", errors="replace")
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
    absent = absent_modules(doc, installed)
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


def check_report(doc: dict, state: dict, declined: dict, target_id: str = None) -> tuple:
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
    raw, sig = fetch_manifest(game_dir, args.manifest, args.offline, quick=True)
    try:
        doc = mfmod.load_verified(raw, sig, allow_env=_local_manifest(args.manifest))
    except mfmod.ManifestError:
        discard_staged_manifest(game_dir)
        raise
    state = rc.read(game_dir)
    code, lines = check_report(doc, state, rc.declined(game_dir),
                               target_id=_resolved_target_id(game_dir, state))
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
    real_stdout = sys.stdout
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
    ix.say("\n--- repair: resident updater ---")
    bsmod.reconcile(game_dir, say=ix.say)
    before = bsmod.resident_version(game_dir)
    ix.say(f"  currently resident: {before}")
    try:
        bsmod.deploy(game_dir, payload_root(), ver.VERSION, say=ix.say)
    except OSError as e:
        raise ix.InstallerError(
            "The resident updater could not be re-deployed.", detail=f"  {e}",
            # NOT False: reconcile() and deploy() both rewrite <game>\LongevityMods, and a
            # failure part-way through has certainly written something. The GAME is untouched,
            # which is what the message below says instead.
            changed=None,
            remedy="close any open installer window and run --repair again; your game files "
                   "were not touched.")
    now = bsmod.resident_version(game_dir)
    ix.say(f"  now resident: {now}")
    ix.say("  (the game itself was not touched)")
    global _VERDICT
    _VERDICT = ("REPAIR COMPLETE",
                f"The resident updater under LongevityMods was re-deployed (version {now}). "
                "Your game files were not touched.")
    return ix.EXIT_OK


def do_uninstall(game_dir: Path, args) -> int:
    """Restore the original exe from .bak and remove what we deployed."""
    import receipt as rc
    ix.say("\n--- uninstall ---")

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

    restored, already_clean, foreign = 0, 0, 0
    for name in names:
        exe = game_dir / name
        bak = exe.with_suffix(exe.suffix + ".bak")
        if not (exe.is_file() and bak.is_file()):
            continue
        changed = bool(restored)         # honest once the first restore has landed
        if _md5_safe(bak, changed=changed) not in ours:
            foreign += 1
            ix.say(f"  {bak.name} is not a backup this installer made -- leaving {name} alone.")
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

    removed, remove_failed = 0, 0
    for f in ["uimod.dll", POPUP_ART_NAME] + [p.name for p in sorted(ffmpeg_bin().glob("*.dll"))]:
        p = game_dir / f
        if not p.exists():
            continue
        try:
            p.unlink()
            removed += 1
        except OSError as e:
            remove_failed += 1
            ix.say(f"  WARNING: could not remove {f}: {e}")

    # The Datalinks text files go back to the originals (their .longevity.bak copies) wherever ours is in place --
    # BEFORE the refusal below, so a folder whose exe and DLL were already cleaned by hand still gets its text back.
    text_restored = restore_datalinks_text(game_dir)
    if text_restored:
        ix.say(f"  restored {text_restored} Datalinks text file(s)")
        restored += text_restored

    # Nothing restored and nothing removed is a REFUSAL, whatever the receipt says.
    #
    # Gating this on the receipt let a stray or corrupt record stand in for real work: the run
    # printed "UNINSTALL COMPLETE -- 0 file(s) restored, 0 removed. The game is back to how it
    # was", which is both useless and untrue. The record is still cleared on the way out, so a
    # leftover one never persists and re-running stays idempotent.
    if not restored and not removed:
        rc.clear(game_dir, say=ix.say)
        if foreign:
            msg = ("Nothing to uninstall: the backup beside your executable was not made by this "
                   "installer, so it was left alone.")
        elif already_clean:
            msg = "Nothing to uninstall: this copy of the game is already unmodified."
        else:
            msg = "Nothing to uninstall: no patched executable with a backup was found."
        raise ix.InstallerError(
            msg, code=ix.EXIT_ABORTED, changed=False,
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
    ix.say("\n  Left in place, deliberately:")
    ix.say("    movies\\hd            - the HD cinematics (a large download; delete it yourself")
    ix.say("                           if you want the space back)")
    ix.say("    portraits\\           - your own portraits, and the Longevity HD Portrait Pack in")
    ix.say("                           portraits\\hd (unused once the mod is gone)")
    ix.say("    LongevityMods\\       - the resident updater and its staging folder; safe to")
    ix.say("                           delete once this window is closed")
    ix.say("    [UIMod] settings     - your preferences in Alpha Centauri.ini")
    rc.clear(game_dir, say=ix.say)

    global _VERDICT
    # Say only what is true. "The game is back to how it was" contradicted the list of things
    # deliberately left in place printed directly above it -- and was printed unchanged even when
    # a removal had just warned that it failed.
    body = f"{restored} file(s) restored from their .bak backups, {removed} removed."
    if remove_failed:
        body += (f" {remove_failed} file(s) could NOT be removed (see the warnings above) -- "
                 "close the game and run --uninstall again to finish.")
    body += " The items listed above were deliberately left in place."
    _VERDICT = ("UNINSTALL COMPLETE" if not remove_failed else "UNINSTALL INCOMPLETE", body)
    ix.say(f"\n  {restored} file(s) restored, {removed} removed.")
    return ix.EXIT_OK


def main() -> int:
    _load_modules()     # must precede banner(): it prints ver.VERSION
    if not ix.is_worker():
        banner()        # a worker child runs in the bootstrap's console, which printed it already
    apr = argparse.ArgumentParser(
        description="Longevity Vaccine installer (SMACX UI scaling + HD cinematics)")
    apr.add_argument("--ai", choices=["on", "off", "ask"], default="ask",
                     help="Install the HD cinematics pack? Default: list the optional modules "
                          "and ask. `--modules a,b` picks packs by name instead.")
    apr.add_argument("--payload-root", default=None,
                     help="Where the installer's own files live (default: derived from this "
                          "script's location, which works in a checkout and in an extracted "
                          "release archive alike).")
    apr.add_argument("--pack", default=None,
                     help="HD cinematic pack dir (default: dist\\movies-hd).")
    apr.add_argument("--portrait-pack", default=None,
                     help="Longevity HD Portrait Pack dir (default: dist\\portraits-hd).")
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
                          "--modules -- the ones the game's update prompt listed and the player "
                          "accepted -- and no other; none without --modules. The core is still "
                          "brought up to date when it is stale.")
    apr.add_argument("--offline", action="store_true",
                     help="Do not touch the network; use only what is already in staging.")
    apr.add_argument("--no-prompt", action="store_true",
                     help="Never ask anything; decline every optional extra.")
    apr.add_argument("--wait-pid", type=int, default=None, metavar="PID",
                     help="(used by the game) wait for this process -- the game that launched "
                          "the update -- to exit before checking or touching anything.")
    apr.add_argument("--uninstall", action="store_true",
                     help="Restore the original exe from .bak and remove the mod's files.")
    apr.add_argument("--repair", action="store_true",
                     help="Re-deploy the resident updater from this payload, without patching "
                          "anything. Use when <game>\\LongevityMods\\updater is corrupt.")
    apr.add_argument("--check", action="store_true",
                     help="(used by the game at launch) print what updates are available as "
                          "key=value lines and exit; installs nothing. Handled before main().")
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
    if args.no_wait:
        os.environ["LONGEVITY_NO_WAIT"] = "1"
    if args.payload_root:
        # Exported rather than passed around, so every payload_root() caller agrees -- including
        # the ones reached from modules that never see `args`.
        os.environ["LONGEVITY_PAYLOAD_ROOT"] = str(Path(args.payload_root).resolve())

    game_dir = Path(args.game_dir) if args.game_dir else config.game_dir(required=False)
    ix.say(f"Game dir: {game_dir}")
    if not game_dir.is_dir():
        raise ix.InstallerError(
            "The game directory could not be found.",
            code=ix.EXIT_NO_GAME,
            detail=f"Looked for: {game_dir}",
            remedy="re-run with --game-dir \"<path to your Alpha Centauri folder>\", "
                   "or set the SMACX_GAME_DIR environment variable.")

    # Every pairing, not just one. main() dispatches uninstall > repair > update in that order,
    # so an unchecked `--repair --update` silently did the repair and the verdict claimed only
    # that -- the player asked for two things and was told about one, with no word about the
    # other.
    modes = [n for n, on in (("--uninstall", args.uninstall), ("--repair", args.repair),
                             ("--update", args.update)) if on]
    if len(modes) > 1:
        raise ix.InstallerError(f"{' and '.join(modes)} cannot be combined.",
                                code=ix.EXIT_ABORTED, changed=False,
                                remedy="run one of them at a time.")
    if args.only_listed and not args.update:
        # It narrows an UPDATE's pack set; anywhere else it would be silently ignored.
        raise ix.InstallerError("--only-listed works only with --update.",
                                code=ix.EXIT_ABORTED, changed=False,
                                remedy="add --update, or leave --only-listed out.")
    # Before the first write of every mode, and released before run_guarded offers to start the
    # game, so an update the game then offers is never refused by the window that is closing.
    lock = hold_installer_lock(game_dir)
    try:
        if args.uninstall:
            return do_uninstall(game_dir, args)
        if args.repair:
            return do_repair(game_dir)
        if args.update:
            return do_update(game_dir, args)
        return _install(game_dir, args)
    finally:
        lock.release()


def _install(game_dir: Path, args) -> int:
    """The first-time install (and its re-runs): main() without a mode flag."""
    # Candidate exes come from the target table's `exe` fields plus the configured name -- no
    # hardcoded executable names here (CLAUDE.md's opening invariant), and a base that is not a
    # shipping target contributes no candidate.
    candidates: list[Path] = []
    for name in _exe_names():
        p = game_dir / name
        if p.exists() and p not in candidates:
            candidates.append(p)
    if not candidates:
        raise ix.InstallerError(
            "No Alpha Centauri executable was found in the game directory.",
            code=ix.EXIT_NO_GAME,
            detail=f"Searched: {game_dir}",
            remedy="check that this is the folder containing terranx.exe.")

    # Before the first write: a companion declared without its baseline is a packaging fault, and
    # companions are patched AFTER the exe -- discovering it then would mean aborting with the exe
    # already modified.
    check_companion_declarations()

    # The optional modules are chosen BEFORE anything is written: the player sees what is on
    # offer, with sizes, and the installer waits for the answer (user, 2026-09-27). The downloads
    # themselves happen after the game is patched.
    ix.say("\n--- optional modules ---")
    catalogue, manifest = module_catalogue(game_dir, args)
    chosen = choose_modules(catalogue, args, game_dir)
    if args.ai == "off" and not args.modules:
        ix.say("  none requested")
    elif manifest is not None and not catalogue:
        ix.say("No optional modules are available for download right now.")

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
        # Only MEASURED launch targets may be advertised. Listing a declared-but-unmeasured one
        # tells a Thinker user "Supported: ... Thinker ..." and then refuses their exe, which is
        # self-contradictory and unactionable.
        try:
            labels = [t.label for t in _targets().values() if t.launch and t.measured]
        except Exception:  # noqa: BLE001 - explaining a failure must not become a second failure
            labels = []
        raise ix.InstallerError(
            "No game executable this mod can patch was found in the game folder.",
            code=ix.EXIT_UNSUPPORTED,
            detail="The mod is built for: " + ", ".join(labels) + ".\n"
                   + "Found: " + ", ".join(f"{n} (MD5 {_md5_safe(game_dir / n)})"
                                           for n in results) + ".",
            remedy="install the GOG Planetary Pack with the PRACX patch, or report your "
                   "executable's MD5 so it can be added.")

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
    companion_results = patch_companions(game_dir, spec, args.force) if spec is not None else {}
    thinker_warned = warn_thinker_build(game_dir)

    if not deploy_runtime(game_dir):
        raise ix.InstallerError(
            "The game was patched, but copying the mod files into place failed.",
            changed=True,
            remedy="close the game if it is running and re-run the installer.")
    text_results = patch_datalinks_text(game_dir)

    # The chosen optional modules. A local pack (a checkout) is copied; the rest are downloaded
    # through the same verified path the update uses. A pack that fails never fails the install:
    # the mod is complete without it, and the game's update prompt offers it again.
    pack_status = {n: "skip" for n in GAME_CONTENT_MODULES}
    installed_packs = {}
    local = [n for n in chosen if catalogue.get(n, {}).get("source") == "local"]
    remote = [n for n in chosen if catalogue.get(n, {}).get("source") == "manifest"]
    for name in local:
        ix.say(f"\n--- {_pack_label(name)} ---")
        copy_pack = install_portrait_pack if name == "portraits-hd" else install_movie_pack
        if copy_pack(game_dir, catalogue[name]["path"]):
            pack_status[name] = "ok"
            installed_packs[name] = {"version": ver.module_version(name)}
        else:
            pack_status[name] = "error"
    if remote:
        got, statuses = install_packs_from_manifest(game_dir, args, remote, manifest, target_id,
                                                    game_dir / patched)
        installed_packs.update(got)
        pack_status.update(statuses)
    # NOT inferred from disk: a folder that happens to hold files is not an installed pack, and
    # recording one at the current version would hide it from the update prompt for good
    # (audit 2026-09-27). Content left by an uninstall is re-offered and, once the archive is
    # verified, install_modules skips every file that is already current.
    set_ini_flag(game_dir, cinematics_flag(chosen, game_dir, args, offered=list(catalogue)))
    ensure_in_process_movies(game_dir)
    failed_packs = [n for n in GAME_CONTENT_MODULES if pack_status.get(n) == "error"]

    # A PRACX install carried over from before may pin an old resolution: warn, offer the fix.
    check_display_resolution(game_dir, target_id, no_prompt=bool(getattr(args, "no_prompt", False)))
    # ... and the player needs a way to start the RIGHT exe.
    check_desktop_shortcut(game_dir, target_id)
    global _NOTE_ARGS
    _NOTE_ARGS = (game_dir, target_id)

    # Record what was installed. Until this existed, "which release is this?" had no answer on
    # the player's disk and an update could not tell an old patch set from a current one.
    # Make the installer RESIDENT. Without this the in-game update prompt has nothing to spawn
    # once the player deletes their download, and whatever they kept would be the version they
    # first installed -- while patches.yaml changes every release.
    try:
        import bootstrap as bsmod
        bsmod.reconcile(game_dir, say=ix.say)
        # Quiet: "resident updater deployed: <long temp path> (v0.1.0, 8 component(s))" is
        # bookkeeping; a failure is reported below.
        bsmod.deploy(game_dir, payload_root(), ver.VERSION, say=lambda *a: None)
        if not bsmod.is_usable(bsmod.updater_dir(game_dir)):
            raise OSError("missing " + ", ".join(bsmod.missing_parts(bsmod.updater_dir(game_dir))))
    except Exception as e:  # noqa: BLE001 - a resident copy is not worth failing the install for
        ix.say(f"  WARNING: could not install the resident updater ({e}).")
        ix.say("  The mod itself IS installed and playable, but this copy cannot update itself:")
        ix.say("  future updates will have to be downloaded and run by hand.")

    import receipt as rc
    # MERGE with what the receipt already says: a re-run used to replace the whole module map,
    # forgetting packs that are still on disk. And the pack is recorded at ITS version
    # (version.py MODULE_VERSIONS), not the product's -- recording it as VERSION made a later
    # pack release invisible once the product version got ahead of it.
    mods = dict(rc.read(game_dir).get("modules") or {})
    mods["base"] = {"version": ver.VERSION}
    mods.update(installed_packs)
    rc.write(game_dir, target_id=target_id, modules=mods, say=ix.warn)   # warnings only

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
    if thinker_warned:
        # Said in full above; the row keeps it from scrolling out of sight under the summary.
        ix.status_line("Thinker Mod version", "skip")
        ix.warn("  (Thinker Mod version: not the supported build -- see the warning above)")
    for name in GAME_CONTENT_MODULES:
        # Only packs the player was offered or asked for: a row "Skipped" for a pack that was
        # never on the table (not released yet) says nothing.
        if name in catalogue or pack_status.get(name) != "skip":
            ix.status_line(_pack_label(name), pack_status.get(name, "skip"))
    if failed_packs:
        # Same shape as do_update's partial outcome: the mod IS installed, the pack the player
        # asked for is not, and a scripted caller must see a non-zero code for that.
        shown = " and ".join(_pack_label(n) for n in failed_packs)
        raise ix.InstallerError(
            f"The mod is installed and the game is ready to play. {shown} "
            f"{'was' if len(failed_packs) == 1 else 'were'} not installed.",
            code=ix.EXIT_ERROR, changed=True, title="INSTALLATION PARTLY COMPLETE",
            disk_note="The game is patched and ready to play; only the optional download is missing.",
            remedy="run the installer again, or take the pack from the game's update prompt.")

    # Remember where the game is so the guard can offer to launch it.
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
    return 0


#: Set by main() once the game dir is known, so run_guarded can offer a relaunch on success.
_LAUNCH_EXE: Path = None

#: (title, body) for the success verdict, when this run was not an install. Defaults to the
#: install wording.
_VERDICT = None


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
        success_after=lambda: print_play_note(*_NOTE_ARGS) if _NOTE_ARGS else None))
