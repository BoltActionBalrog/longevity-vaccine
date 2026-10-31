"""Preflight: acquire and verify EVERY input before a single game byte is modified.

THE ORDERING REQUIREMENT (user, 2026-09-21): "make sure that everything needed for the
installation is available (such as the network collection manifest, etc.) before actually
modifying on-disk bytes, such as restoring the backup."

So the run splits cleanly in two:

    PREFLIGHT  -- fetch, verify, dry-run, check space/locks/permissions. May populate
                  <game>\\LongevityMods\\staging. Touches NO game file, no exe, no .bak, no ini.
    COMMIT     -- transact.py, which patches a temp copy and atomically swaps it in.

Every check returns a reason instead of raising, so a failure reports ALL of what is wrong rather
than only the first thing -- a user who has to re-run four times to discover four problems will
give up. `Preflight.ok` is the gate; `Preflight.blockers` is what to tell them.

A check that cannot be performed is NOT a pass. `unknown` counts as a blocker unless it is
explicitly advisory, because "we could not tell" and "it is fine" are different answers.
"""

from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import apply_patches as ap   # noqa: E402
import fetch                 # noqa: E402
import manifest as mf        # noqa: E402
import version as ver        # noqa: E402

#: Advisory checks report but do not block.
ADVISORY = "advisory"


class Check:
    __slots__ = ("name", "ok", "detail", "advisory")

    def __init__(self, name: str, ok: bool, detail: str = "", advisory: bool = False):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.advisory = advisory

    def __repr__(self):  # pragma: no cover
        return f"<{self.name}: {'ok' if self.ok else 'FAIL'} {self.detail}>"


class Preflight:
    def __init__(self):
        self.checks: list[Check] = []
        self.staged: dict[str, Path] = {}      # module -> verified archive in staging
        self.doc: dict = None                  # the verified manifest
        self.decision = None
        self.wanted: list[str] = []            # modules to fetch: explicit, else the stale ones
        self.patch_log: str = ""               # the patcher's own narration (dry run)

    def add(self, name, ok, detail="", advisory=False) -> bool:
        self.checks.append(Check(name, ok, detail, advisory))
        return ok

    @property
    def blockers(self) -> list:
        return [c for c in self.checks if not c.ok and not c.advisory]

    @property
    def warnings(self) -> list:
        return [c for c in self.checks if not c.ok and c.advisory]

    @property
    def ok(self) -> bool:
        return not self.blockers

    def report(self, say=print) -> None:
        for c in self.checks:
            mark = "ok  " if c.ok else ("warn" if c.advisory else "FAIL")
            say(f"  [{mark}] {c.name}{(': ' + c.detail) if c.detail else ''}")


# ---------------------------------------------------------------- individual checks

def check_game_dir(pf: Preflight, game_dir: Path) -> bool:
    """Returns False when nothing further should be attempted in this directory."""
    game_dir = Path(game_dir)
    if not pf.add("game directory", game_dir.is_dir(), str(game_dir)):
        return False
    # Writability, proven by writing -- an ACL check is not the same question, and discovering a
    # permissions problem mid-write is exactly what this phase exists to prevent.
    #
    # The probe name is unique per run: a fixed name truncated and deleted any pre-existing file
    # of that name, and an exclusive-create refuses to touch someone else's file at all.
    probe = game_dir / f".longevity-probe-{os.getpid()}-{os.urandom(4).hex()}"
    try:
        with probe.open("xb") as f:      # "x" = fail if it exists; never clobber
            f.write(b"x")
    except OSError as e:
        pf.add("game directory is writable", False,
               f"{e} -- run the installer as administrator, or move the game out of "
               f"Program Files")
        return False
    pf.add("game directory is writable", True)
    try:
        probe.unlink()
    except OSError:
        # Cleanup failure is not the same question as writability, and reporting it as "not
        # writable" sent the user to a remedy that could not help.
        pf.add("write probe cleaned up", False,
               f"a stray {probe.name} was left in the game directory; it is safe to delete",
               advisory=True)
    return True


def check_target_and_backup(pf: Preflight, target: Path, table: dict,
                            receipt_target_id: str = None):
    """The exe must be present and its .bak must be a base we recognise AND still support."""
    target = Path(target)
    if not pf.add("target executable", target.is_file(), str(target)):
        return None
    beside = ap.folder_files(target.parent)   # thinker.dll beside the exe = the PRACX + Thinker overlay

    bak = target.with_suffix(target.suffix + ".bak")
    if not bak.is_file():
        # No backup yet = a first install from a clean base. The clean base is then the exe itself.
        try:
            md5 = hashlib.md5(target.read_bytes()).hexdigest()
        except OSError as e:
            pf.add("read the target executable", False, str(e))
            return None
        try:
            spec = ap.resolve_target(md5, table, launch_only=True, present_files=beside,
                                     exe_name=target.name)
        except ap.UnsupportedBase as e:
            pf.add("supported configuration", False, str(e))
            return None
        pf.add("clean base (no .bak yet)", True, f"{spec.id} ({spec.label})")
        return spec

    try:
        bak_md5 = hashlib.md5(bak.read_bytes()).hexdigest()
        live_md5 = hashlib.md5(target.read_bytes()).hexdigest()
    except OSError as e:
        pf.add("read the target and its backup", False, str(e))
        return None
    try:
        spec = ap.resolve_target(bak_md5, table, launch_only=True, present_files=beside,
                                 exe_name=target.name)
    except ap.UnsupportedBase as e:
        pf.add("backup is a supported clean base", False, str(e))
        return None
    pf.add("backup is a supported clean base", True, f"{spec.id} ({spec.label})")

    # THE LIVE EXE MUST BE ACCOUNTED FOR TOO. Hashing only the .bak meant a foreign live binary --
    # a newer PRACX, a Thinker build, anything the player swapped in -- passed preflight and was
    # then overwritten by a build patched from the .bak, destroying it with no backup of ITS
    # bytes. The live file must be either the clean base (not yet patched) or a build we produced:
    # this configuration's, or a sibling configuration's on the same base (PRACX and PRACX +
    # Thinker share one base -- a Thinker build in a folder Thinker was removed from is still ours,
    # not "a binary we did not make"; audit 2026-10-28).
    known = {spec.base_md5, spec.patched_md5} - {None}
    siblings = {t.patched_md5 for t in table.values()
                if t.launch and t.patched_md5 and t.id != spec.id and t.base_md5 == spec.base_md5}
    if live_md5 in known:
        pf.add("live executable is ours or the clean base", True,
               "clean" if live_md5 == spec.base_md5 else "already patched")
    elif live_md5 in siblings:
        pf.add("live executable is ours or the clean base", True,
               "patched for another configuration of the same base")
    else:
        pf.add("live executable is ours or the clean base", False,
               f"{target.name} is {live_md5}, which is neither the clean base ({spec.base_md5}) "
               f"nor a build this installer produced ({spec.patched_md5}). Refusing to replace a "
               f"binary we did not make -- back it up and restore the original first.")

    # Crossing targets silently is how you patch a base you never verified: someone who installs
    # Thinker after our mod has a different base underneath the same file name.
    if receipt_target_id and receipt_target_id != spec.id:
        pf.add("target has not changed since install", False,
               f"installed as {receipt_target_id!r}, now looks like {spec.id!r} -- run the installer "
               f"again (a normal install, not --update): it re-patches from the backup for the "
               f"configuration this folder now holds")
    elif receipt_target_id:
        pf.add("target has not changed since install", True, spec.id)
    return spec


def check_not_locked(pf: Preflight, game_dir: Path, game_pid: int = None,
                     target: Path = None, extra: list = None) -> None:
    """Everything we are about to replace is held open while the game runs; discover that now."""
    if game_pid:
        alive = _pid_alive(game_pid)
        pf.add("spawning game has exited", not alive,
               f"pid {game_pid} is still running -- close Alpha Centauri" if alive else "")

    # THE TARGET FIRST: it is the file the commit replaces, and it was not checked at all -- so a
    # locked exe surfaced only at commit, after the whole download and staging phase.
    names = []
    if target:
        names.append(Path(target).name)
    names += [p.name for p in sorted(Path(game_dir).glob("*.dll"))
              if p.name.lower().startswith(("uimod", "av", "sw", "prax"))]
    names += list(extra or [])

    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        p = Path(game_dir) / name
        if not p.exists():
            continue
        try:
            with p.open("r+b"):
                pass
            pf.add(f"{name} is not in use", True)
        except OSError as e:
            pf.add(f"{name} is not in use", False,
                   f"{e} -- close the game (or whatever is holding it) and re-run")


def _pid_alive(pid: int) -> bool:
    """True if the process is running. Fails SAFE: if we cannot tell, we say it is still alive.

    The old version returned False whenever the query failed -- including ERROR_ACCESS_DENIED,
    which a live elevated process produces. "We could not look" became "the game has exited",
    which is the dangerous direction: the installer would proceed to replace files the game still
    holds open.
    """
    try:
        import ctypes
        from ctypes import wintypes
        # use_last_error=True is REQUIRED for ctypes.get_last_error() to return anything. Reading
        # it off the default `ctypes.windll` handle always gave 0, so "no such process" (87) was
        # never recognised and EVERY dead PID was reported as still running -- which made the
        # bootstrap's wait-for-parent spin the full timeout and then refuse to run.
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        h = k32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            err = ctypes.get_last_error()
            # 87 = ERROR_INVALID_PARAMETER: no such process. Anything else (notably 5,
            # ERROR_ACCESS_DENIED) means we were refused, which tells us nothing about whether
            # it is running -- so we assume it is.
            return err != 87
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return True                            # could not tell -> assume alive
            return code.value == 259                   # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    except Exception:  # noqa: BLE001
        return True                                    # could not tell -> assume alive


def check_space(pf: Preflight, game_dir: Path, need: int) -> None:
    free = fetch.free_space(Path(game_dir))
    pf.add("free disk space", free >= need,
           f"{fetch.human_size(free)} free, {fetch.human_size(need)} needed")


def check_manifest(pf: Preflight, raw: bytes, sig: str, installed_version: str,
                   target_id: str, public_key_hex: str = None,
                   allow_env: bool = False, installed_modules: dict = None,
                   labels: dict = None) -> None:
    try:
        doc = mf.load_verified(raw, sig, public_key_hex, allow_env=allow_env)
    except mf.ManifestError as e:
        pf.add("manifest signature", False, str(e))
        return
    pf.add("manifest signature", True)
    pf.doc = doc

    d = mf.decide(doc, installed_version, target_id, installed_modules=installed_modules)
    pf.decision = d
    labels = labels or {}
    if d.action == mf.MANUAL:
        # ONLY the compiled-in message and URL. `d.detail` is manifest-derived and is a developer
        # diagnostic -- interpolating it here put attacker-choosable prose inside our own "see the
        # official link" sentence.
        pf.add("update is available automatically", False, f"{d.message} -- see {d.url}")
    elif d.action == mf.NOTHING:
        # Not a [warn]: being current is the healthy state, and a warning on every idle run
        # read as something the player might have to act on.
        pf.add("Longevity Vaccine is up to date", True,
               f"v{installed_version}" if ver.is_valid(installed_version)
               else (d.detail or "already current"))
    else:
        # Say WHAT is offered. "update offered: 0.1.0" on a pack-only update named the base
        # version the player already had.
        parts = []
        base_offered = not ver.is_valid(installed_version) \
            or ver.is_newer(d.version, installed_version)
        if base_offered:
            parts.append(f"Longevity Vaccine v{d.version}")
        mods = doc.get("modules") if isinstance(doc.get("modules"), dict) else {}
        for m in d.modules:
            info = mods.get(m)
            offered = info.get("version") if isinstance(info, dict) else None
            offered = ver.normalise(offered) if isinstance(offered, str) and ver.is_valid(offered) \
                else "?"
            have = (installed_modules or {}).get(m)
            have = ver.normalise(have) if isinstance(have, str) and ver.is_valid(have) else "?"
            parts.append(f"{labels.get(m, m)} v{have} -> v{offered}")
        pf.add("update offered", True, ", ".join(parts) or d.version)
        min_from = doc.get("min_upgradable_from")
        # Only meaningful when the BASE is offered; on a pack-only update it was noise.
        if base_offered and isinstance(min_from, str) and ver.is_valid(min_from):
            if ver.is_valid(installed_version):
                pf.add("this version can be updated directly",
                       ver.at_least(installed_version, min_from),
                       f"v{installed_version} (oldest supported v{min_from})")
            else:
                # Skipping this silently meant an unknown installed version passed the gate with
                # no trace. Say so instead: it is a repair, not a verified upgrade path.
                pf.add("upgrade path supported", False,
                       f"the installed version is unknown, so the {min_from} minimum cannot be "
                       f"checked -- treating this as a repair", advisory=True)


#: Modules that are required whatever the manifest says about them. The core patch and the
#: installer itself ship together as `base`, so there is no "optional" reading of it.
ALWAYS_REQUIRED = ("base",)


def staging_name(url, module: str) -> str:
    """The file name a module archive is staged under. Derived from the URL so a resumed
    download is found again -- but taken APART, never trusted whole. `Path(url).name` let a
    signed manifest name `C:evil.zip` (drive-relative: escapes staging), `x.zip:ads` (an alternate
    data stream) or `..`. Same whitelist as bootstrap._download_new_payload."""
    import urllib.parse
    try:
        raw = Path(urllib.parse.urlparse(str(url)).path).name if isinstance(url, str) else ""
    except (ValueError, TypeError):
        raw = ""
    safe = "".join(c for c in raw if (c.isascii() and c.isalnum()) or c in "._-").lstrip(".")
    stem = safe.split(".")[0].upper()
    if not safe or stem in _RESERVED or safe.lower() in ("manifest.json", "manifest.json.sig"):
        safe = f"{module}.zip"      # a device name (CON.zip opens the console) or our own files
    # Each module in its own folder: two modules whose URLs end in the same name (or a pack named
    # like the base) can no longer overwrite each other's download.
    return f"{module}/{safe}"


#: Windows device names, reserved at every path level with or without an extension.
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} \
    | {f"LPT{i}" for i in range(1, 10)}


def check_archives(pf: Preflight, doc: dict, staging: Path, wanted: list,
                   allow_file: bool = False, explicit: set = (), labels: dict = None) -> None:
    """Download and verify every wanted module into staging. sha256 from the SIGNED manifest.

    A module the manifest marks OPTIONAL is advisory: a broken extras pack must not block the
    core patch. Only a required module is a blocker -- plus a module the player asked for by
    name (`explicit`) that the manifest does not offer at all: "UPDATE COMPLETE" with no pack
    was the answer to `--modules portraits-hd` before that pack existed.
    """
    modules = doc.get("modules")
    modules = modules if isinstance(modules, dict) else {}
    labels = labels or {}
    for name in wanted:
        info = modules.get(name)
        # `base` is required by DEFINITION, not by the manifest saying so. Deriving optionality
        # purely from the entry made a manifest that omits `base` -- the case where we have no
        # idea what to install -- pass the preflight as an advisory note.
        opt = name not in ALWAYS_REQUIRED \
            and not (isinstance(info, dict) and info.get("required"))
        label = labels.get(name, name)
        if not isinstance(info, dict):
            if name in explicit and name not in ALWAYS_REQUIRED:
                pf.add(f"{label}: not released yet", False, "nothing was downloaded")
            else:
                pf.add(f"module {name} declared", False, "not in the manifest", advisory=opt)
            continue
        url, digest, size = info.get("url"), info.get("sha256"), info.get("size")
        if not isinstance(url, str) or not isinstance(digest, str) or not url or not digest:
            pf.add(f"module {name} declared", False, "manifest entry lacks a url or sha256",
                   advisory=opt)
            continue
        offered = info.get("version")
        shown = f"{label} v{ver.normalise(offered)}" \
            if isinstance(offered, str) and ver.is_valid(offered) else label
        dest = Path(staging) / staging_name(url, name)
        try:
            fetch.download(url, dest, sha256=digest, size=size,
                           mirror=info.get("mirror"), allow_file=allow_file, label=label)
        except fetch.FetchError as e:
            pf.add(f"{shown} download", False, str(e), advisory=opt)
            continue
        pf.add(f"{shown} downloaded and verified", True, fetch.human_size(dest.stat().st_size))
        if not zipfile.is_zipfile(dest):
            pf.add(f"{shown} is a readable archive", False, "not a zip", advisory=opt)
            continue
        try:
            with zipfile.ZipFile(dest) as z:
                bad = z.testzip()
            if bad:
                pf.add(f"{shown} is a readable archive", False,
                       f"corrupt entry {fetch.clean(bad, 60)}", advisory=opt)
                continue
        except (zipfile.BadZipFile, OSError) as e:
            pf.add(f"{shown} is a readable archive", False, fetch.clean(e), advisory=opt)
            continue
        pf.add(f"{shown} is a readable archive", True)
        pf.staged[name] = dest


def check_patch_plan(pf: Preflight, target: Path, patches: Path, spec) -> None:
    """Dry-run the real patcher. Its default IS dry-run, so this costs nothing but time and it
    verifies every site's original_bytes and every cave's padding against the actual binary."""
    if spec is None:
        pf.add("patch plan verifies", False, "no base resolved")
        return
    bak = Path(target).with_suffix(Path(target).suffix + ".bak")
    src = bak if bak.is_file() else Path(target)
    # The patcher narrates every site and cave (~3,700 lines). That is a log, not something to
    # scroll past on an idle check -- and "Target: terranx_PRACX.exe.bak" in it read as the
    # game running from its backup. Captured; shown only if the plan is refused.
    import contextlib
    import io
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = ap.apply_patches(src, Path(patches), do_apply=False, spec=spec)
    except Exception as e:  # noqa: BLE001 - a patcher crash is a blocker, not a traceback
        pf.add("patch plan verifies", False, f"{type(e).__name__}: {e}")
        pf.patch_log = buf.getvalue()
        return
    pf.patch_log = buf.getvalue()
    if rc != 0:
        print(pf.patch_log)
    pf.add("patch plan verifies", rc == 0,
           "" if rc == 0 else f"the patcher refused the plan (code {rc}); see the output above")


def run(*, game_dir: Path, target: Path, patches: Path, table: dict,
        manifest_raw: bytes = None, manifest_sig: str = None,
        installed_version: str = ver.UNKNOWN, receipt_target_id: str = None,
        wanted_modules: list = None, game_pid: int = None,
        public_key_hex: str = None, allow_file: bool = False,
        min_free_bytes: int = 1 << 30, require_manifest: bool = False,
        installed_modules: dict = None, labels: dict = None,
        only_listed: bool = False) -> Preflight:
    """Run every check. Returns a Preflight; NOTHING in the game directory is modified.

    This function does not raise. A check that blows up is itself a blocker -- returning a
    Preflight with a reason is the contract, and letting an exception escape would send a
    read-only game directory or a malformed manifest field to the crash handler instead.

    Which modules get fetched (`pf.wanted`): `wanted_modules` is the EXPLICIT list (`--modules`)
    and is fetched as given; when it is None the set is the decision's stale modules, computed
    from `installed_modules` (name -> receipt version). "Every installed module" is deliberately
    not an option any more -- it re-downloaded a current 1.3 GB pack on every base release.
    `only_listed` (the game's --only-listed): `wanted_modules` is the WHOLE set -- the packs the
    game's popups named and the player accepted -- and no other stale module is added.
    """
    pf = Preflight()
    pf.spec = None
    try:
        writable = check_game_dir(pf, game_dir)
        spec = check_target_and_backup(pf, target, table, receipt_target_id)
        pf.spec = spec
        check_not_locked(pf, game_dir, game_pid, target=target)

        if manifest_raw is None:
            # A caller that wanted an update but could not fetch the manifest must NOT get a
            # clean preflight -- "everything it needs" includes the manifest.
            if require_manifest:
                pf.add("update manifest available", False,
                       "no manifest was supplied, so nothing about this update can be verified")
            check_space(pf, game_dir, min_free_bytes)
        else:
            # allow_env rides on allow_file: both mean "this manifest came from a local
            # file", which is the only situation where a test key may override the
            # compiled-in one.
            check_manifest(pf, manifest_raw, manifest_sig or "", installed_version,
                           spec.id if spec else None, public_key_hex,
                           allow_env=allow_file, installed_modules=installed_modules,
                           labels=labels)
            if pf.doc:
                # Explicit names PLUS the stale installed ones -- not instead of them. With
                # "instead", `--modules portraits-hd` announced a stale movies-hd as "already
                # current" and left it behind.
                pf.wanted = [str(n) for n in (wanted_modules or [])]
                if pf.decision is not None and not only_listed:
                    pf.wanted += [n for n in pf.decision.modules if n not in pf.wanted]
                elif pf.decision is not None:
                    mods_ = pf.doc.get("modules") if isinstance(pf.doc.get("modules"), dict) else {}
                    for n in pf.decision.modules:
                        if n in pf.wanted:
                            continue
                        info = mods_.get(n)
                        v = info.get("version") if isinstance(info, dict) else None
                        v = ver.normalise(v) if isinstance(v, str) and ver.is_valid(v) else "?"
                        have = (installed_modules or {}).get(n)
                        have = ver.normalise(have) if isinstance(have, str) and ver.is_valid(have) \
                            else "?"
                        # A pass: the game's list is the player's answer. Said, so a pack that
                        # stays behind is never a mystery -- and how to take it anyway.
                        pf.add(f"{(labels or {}).get(n, n)} v{v}: not part of this update", True,
                               f"stays at v{have} (not in the list the game passed); "
                               f"run-install.bat --update --modules {n} installs it")
                need = pf.doc.get("min_free_bytes")
                need = need if mf.size_ok(need) else min_free_bytes
                # Add up what we are actually about to download; a fixed constant cannot notice
                # that the wanted module set does not fit.
                mods = pf.doc.get("modules")
                mods = mods if isinstance(mods, dict) else {}
                for name in pf.wanted:
                    info = mods.get(name)
                    sz = info.get("size") if isinstance(info, dict) else None
                    if mf.size_ok(sz) and sz > 0:
                        need += sz * 2        # the archive plus what it expands to
                check_space(pf, game_dir, need)
                if pf.wanted:
                    if not writable:
                        pf.add("modules can be staged", False,
                               "the game directory is not writable, so nothing can be downloaded")
                    elif pf.blockers:
                        # DO NOT DOWNLOAD once something has already failed. The game being open,
                        # a foreign live exe or a changed target id are all decided by this
                        # point, and pulling 1.3 GB into the player's game folder before telling
                        # them nothing could be done is pure waste -- of their bandwidth, their
                        # disk, and their patience.
                        pf.add("modules can be staged", False,
                               "skipped: an earlier check already blocks this update",
                               advisory=True)
                    else:
                        check_archives(pf, pf.doc, fetch.staging_dir(game_dir), pf.wanted,
                                       allow_file=allow_file,
                                       explicit=set(wanted_modules or []), labels=labels)

        check_patch_plan(pf, target, patches, spec)
    except Exception as e:  # noqa: BLE001 - a crashed check is a blocker, not a traceback
        pf.add("preflight completed", False, f"{type(e).__name__}: {e}")
    return pf
