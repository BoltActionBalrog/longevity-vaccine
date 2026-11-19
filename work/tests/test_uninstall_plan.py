"""The uninstall's up-front check (install.uninstall_targets + preflight.probe): it lists exactly the files the run
would read or change, each with the calls it makes on them, so a file the run leaves alone -- or only renames --
never blocks it; each probe mode refuses exactly when its call would fail; and each restore module's restore_plan
agrees with what its restore really does. In-process and fast; the end-to-end refusals are in test_install_e2e.py.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import sys
import threading
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import config                 # noqa: E402
import install as inst        # noqa: E402
import patch_helptext as ph   # noqa: E402
import preflight as pfm       # noqa: E402
import receipt as rc          # noqa: E402
import wine_ddraw as wd       # noqa: E402

inst._load_modules()


def _synthetic(spec: dict) -> bytes:
    parts = [b";", b"#FILLER0", b"x", b""]
    for tag, stock in spec["stock"].items():
        parts += [tag] + stock + [b""]
    return b"\r\n".join(parts) + b"\r\n"


def _targets(g: Path) -> dict:
    return {p.name: mode for p, mode in inst.uninstall_targets(g, list(inst._exe_names()), set())}


def _tree(g: Path) -> dict:
    return {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in g.iterdir() if p.is_file()}


@pytest.fixture
def g(tmp_path):
    d = tmp_path / "game"
    d.mkdir()
    yield d
    for p in d.rglob("*"):
        if p.is_file():
            p.chmod(stat.S_IREAD | stat.S_IWRITE)


# ---------------------------------------------------------------- the probe's two modes

def test_a_read_only_file_blocks_a_write_but_not_a_rename(g):
    p = g / "f.bin"
    p.write_bytes(b"x")
    p.chmod(stat.S_IREAD)
    assert pfm.change_blocker(p) and not pfm.change_blocker(p, rename_only=True)
    assert p.read_bytes() == b"x"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing modes")
def test_a_handle_without_delete_sharing_blocks_both(g):
    import _winapi
    p = g / "f.bin"
    p.write_bytes(b"x")
    h = _winapi.CreateFile(str(p), 0x80000000, 1, 0, 3, 0, 0)      # GENERIC_READ, FILE_SHARE_READ only
    try:
        assert pfm.change_blocker(p) and pfm.change_blocker(p, rename_only=True)
    finally:
        _winapi.CloseHandle(h)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing modes")
def test_a_brief_open_by_another_program_does_not_block_but_a_lasting_one_does(g, monkeypatch):
    """A virus scanner's quick look at a file must not refuse the uninstall: the probe looks again for a moment
    (audit 2026-11-15). A handle that stays open is still refused. Deterministic: the "scanner" lets go during the
    probe's own pause between looks, not on a timer that a loaded machine may fire late."""
    import _winapi
    import time
    p = g / "f.bin"
    p.write_bytes(b"x")
    h = _winapi.CreateFile(str(p), 0x80000000, 1, 0, 3, 0, 0)      # GENERIC_READ, FILE_SHARE_READ only
    pauses = []

    def pause(s):
        pauses.append(s)
        if len(pauses) == 1:
            _winapi.CloseHandle(h)
    monkeypatch.setattr(time, "sleep", pause)
    assert pfm.change_blocker(p) == "" and len(pauses) == 1
    monkeypatch.undo()
    h = _winapi.CreateFile(str(p), 0x80000000, 1, 0, 3, 0, 0)
    try:
        assert pfm.change_blocker(p)
    finally:
        _winapi.CloseHandle(h)


def test_read_only_reason_never_raises():
    for odd in (None, "a\0b", 2 ** 70, b"", ""):
        assert pfm.read_only_reason(odd) in ("", "the file is read-only")


def test_a_missing_file_blocks_nothing(g):
    """A file gone between the listing and the probe: nothing is left to change (audit 2026-11-15: it refused)."""
    assert pfm.change_blocker(g / "gone.bin") == "" and pfm.change_blocker(g / "gone.bin", rename_only=True) == ""


# ---------------------------------------------------------------- what is listed

def test_the_mods_files_and_the_receipt_are_listed_for_writing(g):
    """A receipt the run cannot delete reads as "installed here" afterwards, so do_uninstall counts it unfinished
    (INCOMPLETE) -- and the check lists it, so a read-only receipt is refused before anything changes."""
    (g / "uimod.dll").write_bytes(b"dll")
    (g / rc.JSON_NAME).write_text("{}", encoding="utf-8")
    t = _targets(g)
    # the mod's files go with unlink_entitled, read-only or not (user ruling 2026-11-17, D3(b)); the receipt does not
    assert t["uimod.dll"] == "delete+entitled" and t[rc.JSON_NAME] == "delete"


def test_clearing_the_receipt_says_whether_it_is_gone(g):
    (g / rc.JSON_NAME).write_text("{}", encoding="utf-8")
    (g / rc.JSON_NAME).chmod(stat.S_IREAD)
    said = []
    assert rc.clear(g, say=said.append) is False and (g / rc.JSON_NAME).exists() and said
    (g / rc.JSON_NAME).chmod(stat.S_IREAD | stat.S_IWRITE)
    assert rc.clear(g, say=said.append) is True and not (g / rc.JSON_NAME).exists()
    assert rc.clear(g, say=said.append) is True              # nothing there: nothing left behind


def test_clearing_the_receipt_counts_its_ini_keys_too(g):
    """A key left in Alpha Centauri.ini reads as "installed" as much as the file (rc.read falls back to it): a
    read-only ini that keeps them is not a cleared receipt (audit 2026-11-16: COMPLETE was said over them)."""
    rc.ini_set(g, rc.KEY_TARGET, "pracx")
    ini = g / rc.INI_NAME
    ini.chmod(stat.S_IREAD)
    said = []
    assert rc.clear(g, say=said.append) is False and rc.receipt_keys_present(g) == [rc.KEY_TARGET], said
    assert any(rc.INI_NAME in s for s in said), said
    ini.chmod(stat.S_IREAD | stat.S_IWRITE)
    assert rc.clear(g, say=said.append) is True and rc.receipt_keys_present(g) == []


# ---------------------------------------------------------------- each probe mode against its own call

#: Every kind of holder another program can be: a handle of each access (R/W/D) and sharing (0 = none), one that
#: reads only the attributes, a mapped image (a running exe, a loaded DLL), a mapped view of the data (alone, or
#: beside a handle), a byte-range lock (shared, exclusive, or on a few bytes), and the attributes that refuse some
#: calls.
_SHARES = ("0", "R", "W", "D", "RW", "RD", "WD", "RWD")
_HOLDERS = (["attr", "image", "datamap", "map+handle", "map-via-link", "lock-shared", "lock-exclusive", "lock-part",
             "readonly", "hidden", "system"]
            + [f"{a}/{s}" for a in ("R", "W", "RW", "D", "RD", "RWD") for s in _SHARES])
_BITS = {"R": 0x1, "W": 0x2, "D": 0x4}
_ACCESS = {"R": 0x80000000, "W": 0x40000000, "D": 0x00010000}
_INI = b"[Alpha Centauri]\r\nx=1\r\n[Longevity]\r\nTargetId=abc\r\n"


def _k32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                              wintypes.DWORD, wintypes.HANDLE]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.LoadLibraryExW.restype = wintypes.HMODULE
    k.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    k.FreeLibrary.argtypes = [wintypes.HMODULE]
    k.CreateFileMappingW.restype = wintypes.HANDLE
    k.CreateFileMappingW.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.DWORD, wintypes.LPCWSTR]
    k.MapViewOfFile.restype = wintypes.LPVOID
    k.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    k.UnmapViewOfFile.argtypes = [wintypes.LPVOID]
    k.SetFileAttributesW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    k.WritePrivateProfileStringW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR]
    k.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                             ctypes.c_void_p]
    return k


def _hold(k, p: Path, kind: str):
    """Hold `p` as `kind` (in this process: sharing is per handle, so it is the same as another program). Returns
    the release."""
    from ctypes import wintypes
    bad = (None, wintypes.HANDLE(-1).value)
    if kind in ("readonly", "hidden", "system"):
        k.SetFileAttributesW(str(p), {"readonly": 1, "hidden": 2, "system": 4}[kind])
        return lambda: k.SetFileAttributesW(str(p), 0x80)
    if kind == "image":
        m = k.LoadLibraryExW(str(p), None, 0x20)            # LOAD_LIBRARY_AS_IMAGE_RESOURCE: mapped, nothing runs
        assert m
        return lambda: k.FreeLibrary(m)
    if kind in ("datamap", "map+handle", "map-via-link"):
        via = p
        if kind == "map-via-link":                          # the file first written under ANOTHER hard link, and
            data = p.read_bytes()                           # mapped through it: Windows names the view by that
            p.unlink()                                      # name (re-audit 2026-11-16, F2a)
            via = p.with_name("first-name.bin")
            via.write_bytes(data)
            os.link(via, p)
        h = k.CreateFileW(str(via), _ACCESS["R"], 0x7 if kind == "datamap" else 0x3, None, 3, 0, None)
        s = k.CreateFileMappingW(h, None, 0x2, 0, 0, None)  # PAGE_READONLY
        v = k.MapViewOfFile(s, 0x4, 0, 0, 0)                # FILE_MAP_READ
        k.CloseHandle(s)
        assert v
        if kind == "datamap":                               # the handles go, the view stays
            k.CloseHandle(h)
            return lambda: k.UnmapViewOfFile(v)
        return lambda: (k.UnmapViewOfFile(v), k.CloseHandle(h))   # a handle kept beside the view (audit F2)
    if kind.startswith("lock-"):                            # a byte-range lock through a handle sharing all (F1)
        import ctypes

        class OV(ctypes.Structure):
            _fields_ = [("a", ctypes.c_void_p), ("b", ctypes.c_void_p), ("off", wintypes.DWORD),
                        ("off_hi", wintypes.DWORD), ("ev", wintypes.HANDLE)]
        h = k.CreateFileW(str(p), _ACCESS["R"] | _ACCESS["W"], 0x7, None, 3, 0, None)
        assert h not in bad
        ov = OV()
        if kind == "lock-part":
            ov.off = 1                                      # bytes 1..2 only
        whole = kind != "lock-part"
        assert k.LockFileEx(h, 0x1 | (0 if kind == "lock-shared" else 0x2), 0,
                            0xFFFFFFFF if whole else 2, 0xFFFFFFFF if whole else 0, ctypes.byref(ov))
        return lambda: k.CloseHandle(h)
    if kind == "attr":
        access, share = 0x80, 0                             # FILE_READ_ATTRIBUTES alone
    else:
        acc, sh = kind.split("/")
        access = sum(_ACCESS[c] for c in acc)
        share = sum(_BITS[c] for c in sh) if sh != "0" else 0
    h = k.CreateFileW(str(p), access, share, None, 3, 0, None)
    assert h not in bad, kind
    return lambda: k.CloseHandle(h)


def _calls(k, mode: str) -> list:
    """The run's own calls a mode stands for, each `call(d, f)` on a fresh folder."""
    def profile(d, f):
        if not k.WritePrivateProfileStringW("Longevity", "TargetId", None, str(f)):
            raise OSError("WritePrivateProfileStringW failed")
    return {
        "read": [lambda d, f: f.read_bytes()],
        "source": [lambda d, f: shutil.copy2(f, d / "copied.bin")],
        "overwrite": [lambda d, f: f.write_bytes(b"new"), lambda d, f: shutil.copy2(d / "other.bin", f)],
        "rename": [lambda d, f: os.replace(f, d / "free.bin")],
        "delete": [lambda d, f: os.remove(f)],
        "replace": [lambda d, f: os.replace(d / "other.bin", f)],
        "profile": [profile],
    }[mode]


def _refused_on_the_safe_side(mode: str, kind: str, program: bool) -> bool:
    """Where the probe refuses though the call would work, on purpose: what Windows lets it see cannot tell the
    holder apart from one that would make the call fail."""
    if mode == "source" and kind in ("readonly", "hidden", "system"):
        return True                     # the copy works, but carries the bit to the exe it writes
    if mode == "replace" and kind in ("datamap", "map-via-link"):
        # a mapped view looks like any other holder; and a holder through ANOTHER hard link of the file does not stop
        # this name being replaced -- which name a holder used is not to be seen
        return True
    if mode == "delete" and "/" in kind:
        share = kind.split("/")[1]
        # a reader not sharing write looks like a running program -- for a program file, or one it cannot read
        return "D" in share and "W" not in share and (program or "R" not in share)
    return False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing modes")
@pytest.mark.parametrize("content", ["program", "data"])
@pytest.mark.parametrize("mode", list(pfm.PROBE_MODES))
def test_each_probe_mode_refuses_exactly_when_its_call_would_fail(tmp_path, monkeypatch, mode, content):
    """Each mode's probe passes exactly when the run's own call for it works, for every kind of holder (audit
    2026-11-16: a share-all open passed a file Python could not then read (D1) and a name a file could not be moved
    onto (D2); a hidden file could not be written (D4); a file only deleted was refused for a reader sharing delete
    (D5)). The few refusals on the safe side are listed, each with why; the other side -- passed, then the call
    fails -- is never allowed. In-process and fast: the probe's pauses between looks are skipped."""
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    k = _k32()
    program = content == "program"
    body = _INI if mode == "profile" else (b"MZ" + b"\0" * 62 if program else b"plain text\r\n")
    real_pe = Path(sys.base_prefix) / "python3.dll"
    wrong, n = [], iter(range(10 ** 6))
    for kind in _HOLDERS:
        if kind == "image" and (not program or mode == "profile"):
            continue
        probed, worked = None, True
        for call in _calls(k, mode):
            d = tmp_path / str(next(n))
            d.mkdir()
            f = d / "f.bin"
            f.write_bytes(real_pe.read_bytes() if kind == "image" else body)
            (d / "other.bin").write_bytes(b"other")
            release = _hold(k, f, kind)
            outcome, worker = [], None
            try:
                if probed is None:
                    probed = pfm.probe(f, {mode}) == ""

                def attempt():
                    try:
                        call(d, f)
                        outcome.append(True)
                    except OSError:
                        outcome.append(False)
                # A call that WAITS for the holder is a failure too: the profile API waits on a byte-range lock
                # instead of failing. It finishes once the holder lets go, below.
                # Counted as waiting only when it was still blocked at 2 s AND finished at once when the holder let
                # go -- a call that is merely slow (a virus scanner stalling on a new file, a loaded machine) keeps
                # its own outcome (re-audit 2026-11-16: a bare 2 s cut-off could flake).
                worker = threading.Thread(target=attempt, daemon=True)
                worker.start()
                worker.join(2.0)
                waited = not outcome
            finally:
                release()
                if worker is not None:
                    worker.join(0.5)
                    waited = waited and bool(outcome)
                    worker.join(30.0)
            if waited or not outcome or not outcome[0]:            # never finished: a failure too
                worked = False
        if probed and not worked:
            wrong.append((kind, "PASSED, but the call fails"))
        elif not probed and worked and not _refused_on_the_safe_side(mode, kind, program):
            wrong.append((kind, "refused, but the call works"))
    assert not wrong, (mode, content, wrong)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file attributes")
def test_a_hidden_copy_source_is_refused_because_copy2_carries_the_bit(g):
    """The copy works -- the matrix lists it as a refusal on the safe side -- but under 3.12 (CopyFile2) the exe it
    writes comes out hidden: the reason "source" refuses the bit there. 3.8's copy2 (the Windows 7 / 8 runtime)
    copies only the read-only bit, so a hidden source passes there and the copy is not hidden."""
    import _winapi
    import ctypes
    src, dst = g / "src.bin", g / "dst.bin"
    src.write_bytes(b"x")
    dst.write_bytes(b"y")
    ctypes.windll.kernel32.SetFileAttributesW(str(src), 0x2)
    try:
        carries = hasattr(_winapi, "CopyFile2")
        assert pfm.probe(src, {"source"}) == ("the file is hidden or a system file" if carries else "")
        shutil.copy2(src, dst)
        assert bool(os.stat(dst).st_file_attributes & 0x2) == carries
    finally:
        for p in (src, dst):
            ctypes.windll.kernel32.SetFileAttributesW(str(p), 0x80)


def test_an_unknown_probe_mode_is_never_skipped(g):
    (g / "f.bin").write_bytes(b"x")
    with pytest.raises(ValueError):
        pfm.probe(g / "f.bin", {"write"})


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing modes")
def test_a_running_exe_is_probed_as_its_image(g):
    """A real running exe -- the matrix above maps its image the way the loader does, without running it."""
    import subprocess
    import time
    exe = g / "running.exe"
    # Windows' own ping: it needs no DLL beside it (a lone copy of the 3.8 runtime's python.exe cannot start)
    shutil.copyfile(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "PING.EXE", exe)
    proc = subprocess.Popen([str(exe), "-n", "9", "127.0.0.1"], stdout=subprocess.DEVNULL)
    try:
        time.sleep(1.0)
        assert proc.poll() is None, "the exe is not running: the probes below would test nothing"
        ok = {m: pfm.probe(exe, {m}) == "" for m in pfm.PROBE_MODES}
        assert ok == {"read": True, "source": True, "overwrite": False, "rename": True, "delete": False,
                      "replace": False, "profile": False}, ok
    finally:
        proc.kill()
        proc.wait()


def _fake_restore_folder(g: Path) -> tuple:
    """terranx_PRACX.exe with a .bak the uninstall would copy over it (its hash passed as `ours`)."""
    (g / "terranx_PRACX.exe").write_bytes(b"MZ a patched build")
    (g / "terranx_PRACX.exe.bak").write_bytes(b"MZ the clean base")
    ours = {hashlib.md5(b"MZ the clean base").hexdigest()}
    return ours


def test_the_generic_restore_lists_the_exe_to_overwrite_and_its_backup_as_source(g):
    ours = _fake_restore_folder(g)
    t = {p.name: m for p, m in inst.uninstall_targets(g, list(inst._exe_names()), ours)}
    # both are hashed first (read: Python's open), then the .bak copied over the exe
    assert t["terranx_PRACX.exe"] == "overwrite+read" and t["terranx_PRACX.exe.bak"] == "read+source", t


def test_every_file_the_run_reads_is_listed_for_reading(g):
    """An unreadable set-up record or .bak read as "absent" to the plan (audit 2026-11-16): they are probed."""
    (g / inst.THINKER_SETUP_NAME).write_text("{}", encoding="utf-8")
    (g / "prax.dll").write_bytes(b"a companion")
    (g / "prax.dll.bak").write_bytes(b"someone's")
    t = {p.name: m for p, m in inst.uninstall_targets(g, list(inst._exe_names()) + ["prax.dll"], set())}
    assert t[inst.THINKER_SETUP_NAME] == "read" and t["prax.dll.bak"] == "read", t


def test_the_ini_is_listed_while_it_holds_receipt_keys(g):
    (g / rc.INI_NAME).write_text("[UIMod]\n", encoding="ascii")
    assert rc.INI_NAME not in _targets(g)
    rc.ini_set(g, rc.KEY_TARGET, "pracx")
    # and replaced: clearing the keys leaves [Longevity] empty, which drop_empty_ini_section removes (the branch)
    assert _targets(g)[rc.INI_NAME] == "profile+read+replace"
    rc.ini_set(g, "SomethingElse", "1")                  # a key of someone else's keeps the section: profile only
    assert _targets(g)[rc.INI_NAME] == "profile"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing modes")
def test_an_ini_held_open_is_listed_and_refused_and_never_reads_as_cleared(g):
    """The profile API answers an ini it cannot read with the default, as it answers a missing key: an ini held
    without sharing read as "no receipt keys" -- not listed, and clear() checked it "gone" -- so COMPLETE was said
    with the keys still there (audit 2026-11-16, D3)."""
    import _winapi
    import types
    import installer_exit as ix
    (g / "uimod.dll").write_bytes(b"dll")
    rc.ini_set(g, rc.KEY_TARGET, "pracx")
    ini = g / rc.INI_NAME
    h = _winapi.CreateFile(str(ini), 0x80000000, 0, 0, 3, 0, 0)    # held, no sharing at all
    try:
        assert rc.receipt_keys_present(g) == [] and rc.ini_unreadable(g)
        assert _targets(g)[rc.INI_NAME] == "profile"
        with pytest.raises(ix.InstallerError) as e:
            inst.do_uninstall(g, types.SimpleNamespace())
        assert e.value.title == "UNINSTALL NOT STARTED" and rc.INI_NAME in (e.value.detail or ""), e.value.detail
        said = []
        assert rc.clear(g, say=said.append) is False and any(rc.INI_NAME in s for s in said), said
    finally:
        _winapi.CloseHandle(h)
    assert rc.receipt_keys_present(g) == [rc.KEY_TARGET] and not rc.ini_unreadable(g)
    assert (g / "uimod.dll").exists()


def test_a_read_only_ini_with_receipt_keys_stops_the_uninstall_up_front(g):
    import types
    import installer_exit as ix
    (g / "uimod.dll").write_bytes(b"dll")
    rc.ini_set(g, rc.KEY_TARGET, "pracx")
    (g / rc.INI_NAME).chmod(stat.S_IREAD)
    try:
        with pytest.raises(ix.InstallerError) as e:
            inst.do_uninstall(g, types.SimpleNamespace())
        assert e.value.title == "UNINSTALL NOT STARTED" and rc.INI_NAME in (e.value.detail or ""), e.value.detail
        assert (g / "uimod.dll").exists()
    finally:
        (g / rc.INI_NAME).chmod(stat.S_IREAD | stat.S_IWRITE)


def test_a_marked_help_file_is_listed_only_when_its_restore_would_write_it(g):
    """The exact undo writes a file of ours whenever it can take our text out -- backup or none -- and leaves an
    edited one, or one that is not ours, alone: only the first may block the run. An earlier version's backup is
    deleted best effort and never listed (a read-only one must not refuse the uninstall)."""
    spec = ph.FILES["helpx.txt"]
    p = g / "helpx.txt"
    p.write_bytes(ph.patch_bytes(_synthetic(spec), spec))
    assert _targets(g) == {"helpx.txt": "overwrite+read"}
    ph.backup_of(p).write_bytes(_synthetic(spec))
    assert _targets(g) == {"helpx.txt": "overwrite+read"}
    p.write_bytes(ph.patch_bytes(_synthetic(spec), spec).replace(b"Cloaking Device", b"Cloaking Devise"))
    assert "helpx.txt" not in _targets(g)            # edited: refused, left alone
    p.write_bytes(_synthetic(spec))                  # not ours any more: left alone
    assert "helpx.txt" not in _targets(g)


def test_nothing_is_listed_for_a_folder_the_mod_never_touched(g):
    """Nothing of ours: nothing to probe, so nothing another program holds can refuse it (an exe alone, without a
    .bak, is not even read)."""
    (g / "terranx.exe").write_bytes(b"someone's exe")
    (g / "helpx.txt").write_bytes(_synthetic(ph.FILES["helpx.txt"]))
    assert _targets(g) == {}


# ---------------------------------------------------------------- restore_plan == what restore does

def _changes(plan: list) -> set:
    """The names a plan changes (its reads and copy sources aside)."""
    return {q.name for q, m in plan if set(m.split("+")) - {"read", "source"}}


def _changed(before: dict, g: Path) -> set:
    after = _tree(g)
    return {n for n in set(before) | set(after) if before.get(n) != after.get(n)}


_HELP_CASES = ["ours-with-backup", "ours-without-backup", "edited", "not-ours", "old-revision-on-record",
               "old-revision-not-on-record", "newer-marker", "unmarked", "padded-marker", "read-only-backup"]


def _help_file(spec: dict, case: str) -> bytes:
    stock = _synthetic(spec)
    patched = ph.patch_bytes(stock, spec)
    body = patched[len(spec["mark"]) + 2:]
    on_record = next((m for m in spec["old_marks"] if m in spec["revisions"]), None)
    return {
        "not-ours": stock,
        "edited": patched.replace(b"Cloaking Device", b"Cloaking Devise"),
        "old-revision-on-record": (ph._apply(stock, spec["stock"], spec["revisions"][on_record], on_record)
                                   if on_record else patched),
        "old-revision-not-on-record": spec["old_marks"][0] + b"\r\n" + body,
        "newer-marker": spec["mark"].rsplit(b" v", 1)[0] + b" v99\r\n" + body,
        "unmarked": body,
        "padded-marker": patched.replace(spec["mark"] + b"\r\n", spec["mark"] + b" \r\n", 1),
    }.get(case, patched)


@pytest.mark.parametrize("case", _HELP_CASES)
def test_the_help_text_plan_matches_its_restore(g, case):
    """restore_plan lists exactly the file the exact undo writes -- for every kind of file it meets (audit of the
    merge, 2026-11-16: only four kinds were checked)."""
    spec = ph.FILES["helpx.txt"]
    p = g / "helpx.txt"
    p.write_bytes(_help_file(spec, case))
    if case != "ours-without-backup":
        ph.backup_of(p).write_bytes(_synthetic(spec))
    if case == "read-only-backup":
        ph.backup_of(p).chmod(stat.S_IREAD)
    plan = _changes(ph.restore_plan(p, spec))
    before = _tree(g)
    status, _ = ph.restore_file_status(p, spec)
    bak = ph.backup_of(p).name                       # deleted best effort, never planned
    assert _changed(before, g) - {bak} == plan, (case, plan, status)
    assert status != ph.FAILED, (case, "a planned-or-not file failed the restore")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing modes")
def test_a_help_file_held_open_is_listed_so_the_check_refuses_it(g):
    """Unreadable (held open without sharing) must not read as "nothing to do": the restore would fail on it, so
    it is listed and the probe refuses with the real reason (audit of the merge: it was not listed, and the run
    stopped half way)."""
    import _winapi
    spec = ph.FILES["helpx.txt"]
    p = g / "helpx.txt"
    p.write_bytes(ph.patch_bytes(_synthetic(spec), spec))
    h = _winapi.CreateFile(str(p), 0x80000000, 0, 0, 3, 0, 0)      # GENERIC_READ, no sharing at all
    try:
        assert ph.restore_plan(p, spec) == [(p, "read+overwrite")]
        assert "helpx.txt" in _targets(g) and pfm.probe(p, {"read", "overwrite"})
    finally:
        _winapi.CloseHandle(h)


def test_a_help_file_that_cannot_be_written_after_the_check_is_incomplete(g, capsys):
    """The race the check cannot close, for the help text: a failed restore like any other since the merge with
    master -- INCOMPLETE, master's warning above the verdict, the folder kept for the re-run."""
    import types
    spec = ph.FILES["helpx.txt"]
    p = g / "helpx.txt"
    patched = ph.patch_bytes(_synthetic(spec), spec)
    p.write_bytes(patched)
    p.chmod(stat.S_IREAD)
    config.remember_game_dir(g)
    real = pfm.probe
    pfm.probe = lambda path, modes: ""
    try:
        inst._VERDICT = None
        assert inst.do_uninstall(g, types.SimpleNamespace()) == 0
        verdict = inst._VERDICT
    finally:
        pfm.probe = real
        inst._VERDICT = None
        config.forget_game_dir(g)
    out = capsys.readouterr().out
    assert verdict[0] == "UNINSTALL INCOMPLETE" and "could NOT be removed or restored" in verdict[1], verdict
    assert "WARNING: could not restore helpx.txt" in out, out
    assert p.read_bytes() == patched


def _stock_sheet() -> bytes:
    """A stock GOG Icons.pcx from the configured game folder (the live sheet, else its backup), READ only."""
    import patch_icons as pi
    gd = config.game_dir(required=False)
    if not gd:
        return None
    for p in (Path(gd) / pi.SHEET, pi.backup_of(Path(gd) / pi.SHEET)):
        try:
            data = p.read_bytes()
            if pi.pixel_hash(pi.decode(data)[1]) in pi.KNOWN_STOCK:
                return data
        except (OSError, pi.SheetError):
            continue
    return None


def test_a_leftover_icons_temp_alone_is_not_listed(g):
    """restore_folder does nothing without a sheet or a backup, so a leftover temp file there must not block."""
    import patch_icons as pi
    pi.tmp_of(g / pi.SHEET).write_bytes(b"half a write")
    assert pi.restore_plan(g / pi.SHEET) == [] and pi.restore_folder(g, say=lambda t: None) == {}


@pytest.mark.skipif(_stock_sheet() is None, reason="no stock GOG Icons.pcx in the configured game folder")
@pytest.mark.parametrize("case", ["ours", "already-original", "changed-since", "wiped", "no-backup", "temp-left"])
def test_the_icons_plan_matches_its_restore(g, case):
    import patch_icons as pi
    stock = _stock_sheet()
    sheet = g / pi.SHEET
    sheet.write_bytes(stock)
    assert pi.patch_folder(g, inst.pracx_icons_overlay(), say=lambda t: None) == {pi.SHEET: pi.ADDED}
    if case == "already-original":
        sheet.write_bytes(stock)
    elif case == "changed-since":
        h, px, pal = pi.decode(sheet.read_bytes())
        sheet.write_bytes(pi.encode(h, bytes([px[0] ^ 1]) + px[1:], pal))
    elif case == "wiped":
        sheet.write_bytes(b"\0" * 64)
    elif case == "no-backup":
        pi.backup_of(sheet).unlink()
    elif case == "temp-left":
        pi.tmp_of(sheet).write_bytes(b"half a write")
    full = pi.restore_plan(sheet)
    plan = _changes(full)
    # a write is _write_atomic's: a file moved ONTO the sheet's name, which a reader sharing everything still stops
    # (audit 2026-11-16, D2) -- probed as "replace", never as a plain delete
    assert all("replace" in m.split("+") for q, m in full if q == sheet and m != "read"), full
    before = _tree(g)
    pi.restore_file_status(sheet)
    changed = _changed(before, g)
    # the backup _drop_backup deletes after a restore is not planned (a failed delete does not fail the restore)
    assert changed - {pi.backup_of(sheet).name} == plan - {pi.backup_of(sheet).name}, (case, plan, changed)
    assert plan <= changed, (case, plan, changed)


def _ddrawcompat() -> bytes:
    """GOG's DDrawCompat ddraw.dll from the configured game folder, READ only; None when there is none."""
    gd = config.game_dir(required=False)
    p = Path(gd) / wd.NAME if gd else None
    if not (p and p.is_file()):
        return None
    data = p.read_bytes()
    return data if wd.ddrawcompat_version(p) else None


@pytest.mark.skipif(_ddrawcompat() is None, reason="no GOG DDrawCompat ddraw.dll in the configured game folder")
@pytest.mark.parametrize("case", ["live-absent", "live-same", "live-different", "backup-not-ddrawcompat"])
def test_the_ddraw_plan_matches_its_restore(g, case):
    dc = _ddrawcompat()
    bak, live = wd.backup_of(g), g / wd.NAME
    bak.write_bytes(dc if case != "backup-not-ddrawcompat" else b"something else")
    if case == "live-same":
        live.write_bytes(dc)
    elif case in ("live-different", "backup-not-ddrawcompat"):
        live.write_bytes(b"another ddraw.dll")
    plan = {q.name: mode for q, mode in wd.restore_plan(g) if set(mode.split("+")) - {"read", "source"}}
    before = _tree(g)
    wd.restore(g)
    changed = _changed(before, g)
    # a rename shows as both names changing; a delete as the backup alone
    if plan.get(bak.name) == "rename":
        assert changed == {bak.name, wd.NAME}, (case, changed)
    else:
        assert changed == set(plan), (case, plan, changed)

    # and a read-only backup blocks the run exactly where the restore would fail on it: only when it is deleted
    # (the same ddraw.dll is back); a rename onto a free name and a kept backup do not
    for f in g.iterdir():
        f.unlink()
    bak.write_bytes(dc if case != "backup-not-ddrawcompat" else b"something else")
    if case == "live-same":
        live.write_bytes(dc)
    elif case in ("live-different", "backup-not-ddrawcompat"):
        live.write_bytes(b"another ddraw.dll")
    bak.chmod(stat.S_IREAD)
    blocked = {q.name for q, mode in wd.restore_plan(g) if pfm.probe(q, mode.split("+"))}
    status, _ = wd.restore(g)
    assert blocked == ({bak.name} if case == "live-same" else set()), (case, blocked)
    assert (status == wd.FAILED) == bool(blocked), (case, status, blocked)


# ---------------------------------------------------------------- what the run says it did

def test_icons_leftovers_deleted_on_the_way_are_said_and_never_called_nothing(g, capsys):
    """A temporary file an interrupted write left beside Icons.pcx is deleted by the restore: said, and named in the
    refusal's disk note -- "nothing on disk was changed" was printed over it (audit 2026-11-16, D6)."""
    import types
    import installer_exit as ix
    import patch_icons as pi
    (g / pi.SHEET).write_bytes(b"someone's sheet")
    tmp = pi.tmp_of(g / pi.SHEET)
    tmp.write_bytes(b"half a write")
    with pytest.raises(ix.InstallerError) as e:
        inst.do_uninstall(g, types.SimpleNamespace())
    out = capsys.readouterr().out
    assert not tmp.exists() and f"removed {tmp.name}" in out, out
    assert e.value.title == "NOTHING TO UNINSTALL" and tmp.name in (e.value.disk_note or ""), (e.value.title,
                                                                                             e.value.disk_note)


@pytest.mark.skipif(_stock_sheet() is None, reason="no stock GOG Icons.pcx in the configured game folder")
def test_a_spare_icons_backup_deleted_on_the_way_is_said_and_never_called_nothing(g, capsys):
    """GOG's "verify files" put the stock sheet back: the backup beside it is spare and the restore deletes it --
    said, and named in the refusal's disk note (audit 2026-11-16, D6)."""
    import types
    import installer_exit as ix
    import patch_icons as pi
    stock = _stock_sheet()
    (g / pi.SHEET).write_bytes(stock)
    bak = pi.backup_of(g / pi.SHEET)
    bak.write_bytes(stock)
    with pytest.raises(ix.InstallerError) as e:
        inst.do_uninstall(g, types.SimpleNamespace())
    out = capsys.readouterr().out
    assert not bak.exists() and f"removed {bak.name}" in out, out
    assert e.value.title == "NOTHING TO UNINSTALL" and bak.name in (e.value.disk_note or ""), e.value.disk_note


def test_an_earlier_versions_help_backup_is_said_once(g, capsys):
    """Beside a restored file its line names the deleted backup; it was said a second time on its own (audit
    2026-11-16, D7). Beside an untouched file, whose own line is quiet, it is said on its own -- once."""
    spec = ph.FILES["helpx.txt"]
    p = g / "helpx.txt"
    bak = ph.backup_of(p)
    for live in (ph.patch_bytes(_synthetic(spec), spec), _synthetic(spec)):
        p.write_bytes(live)
        bak.write_bytes(b"an earlier version's copy")
        dropped = inst.restore_datalinks_text(g)[4]
        out = capsys.readouterr().out
        assert out.count(bak.name) == 1 and dropped == [bak.name] and not bak.exists(), out


def test_the_refusal_says_read_or_change(g):
    """A file the run only reads (a .bak it hashes) can refuse it too: the message does not say "change" alone (audit
    2026-11-16, D7)."""
    import types
    import installer_exit as ix
    # a receipt it must delete, read-only (uimod.dll would not do: a read-only copy of ours is deleted anyway, user
    # ruling 2026-11-17, D3(b))
    (g / "uimod.dll").write_bytes(b"dll")
    (g / rc.JSON_NAME).write_text("{}", encoding="utf-8")
    (g / rc.JSON_NAME).chmod(stat.S_IREAD)
    try:
        with pytest.raises(ix.InstallerError) as e:
            inst.do_uninstall(g, types.SimpleNamespace())
    finally:
        (g / rc.JSON_NAME).chmod(stat.S_IREAD | stat.S_IWRITE)
    assert e.value.title == "UNINSTALL NOT STARTED" and "read or change" in e.value.message, e.value.message
    assert f"{rc.JSON_NAME}: the file is read-only" in (e.value.detail or ""), e.value.detail


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing modes")
def test_a_ddraw_backup_held_open_is_listed_and_never_called_not_ddrawcompat(g):
    """Held without sharing, GOG's DDrawCompat backup read as "not DDrawCompat": left alone, COMPLETE, ddraw.dll not
    put back (audit 2026-11-16, D7). It is listed for reading, so the check refuses; taken after the check, the
    restore fails (said, INCOMPLETE) instead."""
    import _winapi
    bak = wd.backup_of(g)
    bak.write_bytes(b"MZ GOG's DDrawCompat, as far as this test goes")
    h = _winapi.CreateFile(str(bak), 0x80000000, 0, 0, 3, 0, 0)
    try:
        plan = wd.restore_plan(g)
        assert (bak, "read") in plan and pfm.probe(bak, {"read"}), plan
        assert wd.restore(g)[0] == wd.FAILED
    finally:
        _winapi.CloseHandle(h)
    assert wd.restore(g)[0] == wd.KEPT                     # readable: not DDrawCompat, said and left alone


def test_a_record_that_cannot_be_removed_is_incomplete_never_nothing_changed(g):
    """Nothing else to do, but the install record could not be cleared (taken between the check and the clear):
    the record still reads "installed", so the verdict is UNINSTALL INCOMPLETE, the folder stays remembered for the
    re-run, and the disk note does not claim nothing changed -- part of it may be gone (audit 2026-11-16, D9: this
    refusal had no test)."""
    import types
    import installer_exit as ix
    rec = g / rc.JSON_NAME
    rec.write_text("{}", encoding="utf-8")
    rec.chmod(stat.S_IREAD)
    config.remember_game_dir(g)
    real = pfm.probe
    pfm.probe = lambda path, modes: ""
    try:
        with pytest.raises(ix.InstallerError) as e:
            inst.do_uninstall(g, types.SimpleNamespace())
        remembered = [Path(d).resolve() for d in config.remembered_game_dirs()]
    finally:
        pfm.probe = real
        config.forget_game_dir(g)
    assert e.value.title == "UNINSTALL INCOMPLETE" and "could not be removed completely" in e.value.message, e.value
    assert e.value.disk_note and "nothing else was changed" in e.value.disk_note, e.value.disk_note
    assert g.resolve() in remembered and rec.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing modes")
def test_the_install_steps_ddraw_tidy_up_stays_quiet_about_an_unreadable_backup(g):
    """set_aside on Windows tidies a backup up through restore(only_if_absent=True): an unreadable backup there is
    passed over without a word, as before -- the --uninstall check (above) is what treats it as a failure (audit
    2026-11-16, F3: the install printed a warning whose advice, rename the backup, was wrong with ddraw.dll there)."""
    import _winapi
    bak, live = wd.backup_of(g), g / wd.NAME
    bak.write_bytes(b"MZ GOG's DDrawCompat, as far as this test goes")
    live.write_bytes(b"MZ another ddraw.dll")
    h = _winapi.CreateFile(str(bak), 0x80000000, 0, 0, 3, 0, 0)
    try:
        assert wd.set_aside(g, where=wd.WINDOWS) == (wd.NOT_WINE, "")
        status, line = wd.restore(g)
        assert status == wd.FAILED and "Rename it" not in line, line
    finally:
        _winapi.CloseHandle(h)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing modes")
def test_a_holder_that_cannot_be_looked_into_is_refused_with_an_honest_reason(g, monkeypatch):
    """A process the installer cannot open (another user's, a protected one; a 64-bit one from the 32-bit runtime)
    may have the file mapped: refused on the safe side -- but not said to map it, when it may only read it (re-audit
    2026-11-16, F2b)."""
    import _winapi
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    real = pfm._kernel32

    def blind():
        k = real()
        k.OpenProcess = lambda *a: None                    # every process: cannot be opened
        return k
    monkeypatch.setattr(pfm, "_kernel32", blind)
    f = g / "f.bin"
    f.write_bytes(b"x")
    assert pfm.probe(f, {"overwrite"}) == ""               # nobody uses it: nothing to look into
    h = _winapi.CreateFile(str(f), 0x80000000, 3, 0, 3, 0, 0)    # an ordinary reader, no view
    try:
        why = pfm.probe(f, {"overwrite"})
        assert "cannot check" in why and not why.startswith("another program has the file mapped"), why
    finally:
        _winapi.CloseHandle(h)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing modes")
def test_where_windows_cannot_list_a_files_users_an_open_allowing_no_sharing_stands_in(g, monkeypatch):
    """FileProcessIdsUsingFileInformation may be missing (older Windows, some file systems): a name another file is
    moved onto is then checked by an open allowing no sharing -- a reader sharing everything still stops it -- and
    a file written in place by looking through every process for a view of it (re-audit 2026-11-16: that passed
    unchecked)."""
    import _winapi
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(pfm, "_users", lambda k32, path: None)
    f = g / "f.bin"
    f.write_bytes(b"x")
    assert pfm.probe(f, {"replace"}) == "" and pfm.probe(f, {"overwrite"}) == ""
    h = _winapi.CreateFile(str(f), 0x80000000, 7, 0, 3, 0, 0)    # a reader sharing everything
    try:
        assert pfm.probe(f, {"replace"}) and pfm.probe(f, {"overwrite"}) == ""
    finally:
        _winapi.CloseHandle(h)
    k = _k32()
    release = _hold(k, f, "datamap")                       # a view alone, its handles closed
    try:
        assert pfm.probe(f, {"overwrite"}) == "another program has the file mapped into its memory"
    finally:
        release()


_VIEW_HOLDER = r'''
import ctypes, sys
from ctypes import wintypes
k = ctypes.WinDLL("kernel32", use_last_error=True)
k.CreateFileW.restype = wintypes.HANDLE
k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                          wintypes.DWORD, wintypes.HANDLE]
k.CreateFileMappingW.restype = wintypes.HANDLE
k.CreateFileMappingW.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.LPCWSTR]
k.MapViewOfFile.restype = wintypes.LPVOID
k.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
k.CloseHandle.argtypes = [wintypes.HANDLE]
h = k.CreateFileW(sys.argv[1], 0x80000000, 7, None, 3, 0, None)
s = k.CreateFileMappingW(h, None, 2, 0, 0, None)
v = k.MapViewOfFile(s, 4, 0, 0, 0)
k.CloseHandle(s); k.CloseHandle(h)
print("ready" if v else "failed", flush=True)
sys.stdin.read()
'''


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing modes")
@pytest.mark.parametrize("link", ["kept", "deleted"])
def test_another_programs_view_through_another_hard_link_is_found(g, monkeypatch, link):
    """In ANOTHER process (the matrix holds everything in its own): a view alone, its handles closed, taken through
    another hard link of the file. Found by the file's identity while that link is there; once it is deleted the
    view's name no longer opens, so the check cannot tell -- refused, and said so (re-audit 2026-11-16)."""
    import subprocess
    import time
    monkeypatch.setattr(time, "sleep", lambda s: None)
    first, f = g / "first-name.bin", g / "f.bin"
    first.write_bytes(b"plain text\r\n")
    os.link(first, f)
    proc = subprocess.Popen([sys.executable, "-c", _VIEW_HOLDER, str(first)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "ready"
        if link == "deleted":
            first.unlink()
        why = pfm.probe(f, {"overwrite"})
        if link == "kept":
            assert why == "another program has the file mapped into its memory", why
        else:
            assert "cannot check" in why, why
        with pytest.raises(OSError):
            f.write_bytes(b"new")                          # and the write would indeed fail
    finally:
        proc.stdin.close()
        proc.wait(timeout=15)


# ---------------------------------------------------------------- the branch's steps (user ruling 2026-11-17)
# The steps feat/thinker-install adds -- the Thinker Mod removal ("Also uninstall"), the optional packs (manifest,
# .partial with its proofs, our extract's .tmp-<pid> leftovers), the portraits readme, the Thinker install record and
# the [Longevity] section -- are checked up front like master's. The property, as master's test_install_e2e one: one
# file of the folder made read-only or held open by another program; with the check the run either ends exactly as
# it does with nothing locked (same verdict, same folder) or refuses with the folder byte-identical -- and refuses
# ONLY when the same run without the check would fail part-way or end differently.

_BRANCH_TPL: dict = {}          # per worker: the template folder, built once
_BRANCH_BASE: dict = {}         # per worker: {answer: (verdict, tree)} with nothing locked
_PARTIAL_OURS = b"a portrait we placed"


def _branch_tree(root: Path) -> dict:
    """Every file under a case (its game folder and its desktop), by relative path (the logs a run may write
    aside)."""
    return {p.relative_to(root).as_posix(): hashlib.md5(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and "LongevityMods/logs/" not in p.relative_to(root).as_posix()}


def _branch_template(base: Path, bak_path: Path) -> Path:
    """A real setup run that installed Thinker Mod (test_uninstall_thinker_packs' installed_with_thinker), plus the
    branch's other uninstall inputs: the movies pack with a leftover of our extract, a portraits pack only a .partial
    describes (one file provably ours, one the player's), our portraits readme, the pending marker naming that pack,
    and the Thinker consent key (the audit of 356c8f8, M2: those three and our desktop shortcut were not checked)."""
    import json
    import thinker_flow as tf
    from test_thinker_install_review import _args, _fake_thinker_step, _first_install_plan
    from test_uninstall_thinker_packs import _pack
    inst._load_modules()
    g = base / "game"
    g.mkdir(parents=True)
    shutil.copy2(bak_path, g / "terranx_PRACX.exe")
    (g / "Alpha Centauri.ini").write_text("[UIMod]\n", encoding="ascii")
    _game, prep = _first_install_plan(base / "plan", {"terranx.exe": b"MZ"})
    real_commit, real_finish = tf.commit, tf.finish
    prep.game_dir = g
    prep.plan.game_dir = g
    with pytest.MonkeyPatch.context() as mp:
        _fake_thinker_step(mp, g)
        mp.setattr(tf, "prepare", lambda *a, **k: prep)
        mp.setattr(tf, "commit", lambda p, route, exe=None: real_commit(p, route=route, exe=exe))
        mp.setattr(tf, "finish", real_finish)
        assert inst._install(g, _args()) == 0
    d = _pack(g, "movies/hd", "movies-hd", ["angels.mp4"])
    (d / "angels.mp4.tmp-77").write_bytes(b"half")
    p = g.joinpath(*inst.MODULE_ROOTS["portraits-hd"][0].split("/"))
    p.mkdir(parents=True, exist_ok=True)
    (p / "a.png").write_bytes(_PARTIAL_OURS)
    (p / "b.png").write_bytes(b"the player's own")
    entries = [{"name": n, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
               for n, b in (("a.png", _PARTIAL_OURS), ("b.png", b"what we would have placed"))]
    (p / inst.PACK_PARTIAL).write_text(json.dumps({"schema": 1, "pack": "portraits-hd", "files": entries}),
                                       encoding="utf-8")
    (g / "portraits" / inst.PORTRAITS_README).write_text("ours", encoding="ascii")
    inst._pending_path(g).write_text(json.dumps({"packs": ["portraits-hd"]}), encoding="utf-8")
    rc.ini_set(g, tf.CONSENT_KEY, "1")
    return g


#: The files the property locks: every input of the branch's steps (and the receipt beside them); the set-up files
#: (exes, their backups, uimod.dll, the set-up record) are master's property in test_install_e2e.
_BRANCH_FILES = ["game/" + f for f in
                 ["thinker.dll", "thinker.exe", "thinker.ini", "modmenu.txt", "basenames/hive.txt", "alphax.txt",
                  "smac_mod/helpx.txt", "longevity-thinker-install.json", "movies/hd/angels.mp4",
                  "movies/hd/pack-manifest.json", "movies/hd/PROVENANCE.txt", "movies/hd/angels.mp4.tmp-77",
                  "portraits/hd/a.png", "portraits/hd/b.png", "portraits/hd/" + inst.PACK_PARTIAL,
                  "portraits/" + inst.PORTRAITS_README, rc.JSON_NAME, "Alpha Centauri.ini",
                  "LongevityMods/" + inst.PENDING_PACKS]] + ["desktop/" + inst.MOD_SHORTCUT_NAME + ".lnk"]
_BRANCH_KINDS = ["readonly", "shared", "exclusive", "readdelete"]


def _branch_hold(p: Path, kind: str):
    """Another program's hold on `p` (read-only bit, or an open handle), as test_install_e2e's _locked; a callable
    that releases it."""
    if kind == "readonly":
        p.chmod(stat.S_IREAD)
        return lambda: p.chmod(stat.S_IREAD | stat.S_IWRITE) if p.exists() else None
    import _winapi
    access, share = {"shared": (0x80000000, 3), "exclusive": (0x80000000, 0),
                     "readdelete": (0x80000000, 5)}[kind]
    h = _winapi.CreateFile(str(p), access, share, 0, 3, 0, 0)
    return lambda: _winapi.CloseHandle(h)


def _branch_run(g: Path, answer: str, check: bool = True) -> str:
    """'UNINSTALL COMPLETE' / 'UNINSTALL INCOMPLETE' / 'NOT STARTED' / 'FAILED' (raised part-way)."""
    import types
    import installer_exit as ix
    import thinker_flow as tf
    keys = iter({"also": ["down", "enter"], "only": ["enter"]}[answer])
    saved = (pfm.probe, inst.uninstall_links, ix.stdin_is_console, inst._drop_typed_ahead, inst._read_key,
             ix._colour_ok, inst._desktop_dirs, inst._shortcut_target)
    if not check:
        pfm.probe = lambda p, modes: ""
        inst.uninstall_links = lambda game_dir, thinker_too: []
    ix.stdin_is_console = lambda: True
    inst._drop_typed_ahead = lambda: None
    inst._read_key = lambda: next(keys)
    ix._colour_ok = lambda: False
    # The case's own desktop (beside its game folder); a shortcut's target is the text in it (the real reader goes
    # through PowerShell, ~1 s; unreadable reads as "", as there).
    inst._desktop_dirs = lambda: [g.parent / "desktop"]

    def target(lnk):
        try:
            return Path(lnk).read_text(encoding="utf-8")
        except OSError:
            return ""
    inst._shortcut_target = target
    inst._VERDICT = None
    del tf.LAST_KEPT[:]
    try:
        inst.do_uninstall(g, types.SimpleNamespace(no_prompt=False, force=False))
        return inst._VERDICT[0]
    except ix.InstallerError as e:
        return "NOT STARTED" if e.title == "UNINSTALL NOT STARTED" else "FAILED"
    except OSError:
        return "FAILED"
    finally:
        (pfm.probe, inst.uninstall_links, ix.stdin_is_console, inst._drop_typed_ahead, inst._read_key,
         ix._colour_ok, inst._desktop_dirs, inst._shortcut_target) = saved
        inst._VERDICT = None


def _branch_cases():
    for answer in ("also", "only"):
        yield answer, None, "none"
        for f in _BRANCH_FILES:
            for kind in _BRANCH_KINDS:
                yield answer, f, kind


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing modes")
@pytest.mark.usefixtures("install_globals", "synthetic_pin")
@pytest.mark.parametrize("answer,locked,kind", list(_branch_cases()),
                         ids=lambda v: v if isinstance(v, str) else "none")
def test_the_check_holds_the_branch_steps_to_the_run(tmp_path_factory, tmp_path, bak_path, answer, locked, kind):
    """Cost (the suite's rule): 162 cases, each one or two in-process uninstalls of a ~10 MB copy (the exes; the
    .bak hardlinked as in test_install_e2e) -- ~0.3 s a case; the template setup run (~1 s) once per worker."""
    if "tpl" not in _BRANCH_TPL:
        _BRANCH_TPL["tpl"] = _branch_template(tmp_path_factory.mktemp("branch_tpl"), bak_path)
    tpl = _BRANCH_TPL["tpl"]

    def fresh(name: str) -> Path:
        """The case's game folder (a copy of the template) and, beside it, a desktop with our shortcut to it."""
        g = tmp_path / name / "game"

        def place(src, dst):
            if Path(src).suffix.lower() == ".bak" and Path(src).name != (locked or "").rsplit("/", 1)[-1]:
                os.link(src, dst)
            else:
                shutil.copy2(src, dst)
        shutil.copytree(tpl, g, copy_function=place)
        (g.parent / "desktop").mkdir()
        (g.parent / "desktop" / (inst.MOD_SHORTCUT_NAME + ".lnk")).write_text(str(g / "thinker.exe"),
                                                                             encoding="utf-8")
        return g

    def done(g: Path) -> None:
        for p in g.parent.rglob("*"):
            if p.is_file():
                p.chmod(stat.S_IREAD | stat.S_IWRITE)
        shutil.rmtree(g.parent, ignore_errors=True)

    if answer not in _BRANCH_BASE:
        g0 = fresh("baseline")
        _BRANCH_BASE[answer] = (_branch_run(g0, answer), _branch_tree(g0.parent))
        done(g0)
    verdict0, tree0 = _BRANCH_BASE[answer]
    assert verdict0 == "UNINSTALL COMPLETE", verdict0
    if locked is None:
        # the unlocked run takes every bookkeeping item with it (the marker, our shortcut, the consent key)
        assert not any(k.endswith(inst.PENDING_PACKS) or k.startswith("desktop/") for k in tree0), sorted(tree0)
        return
    g = fresh("checked")
    target = g.parent.joinpath(*locked.split("/"))
    assert target.is_file(), locked
    before = _branch_tree(g.parent)
    release = _branch_hold(target, kind)
    try:
        verdict = _branch_run(g, answer)
    finally:
        release()
    after = _branch_tree(g.parent)
    done(g)
    if verdict == "NOT STARTED":
        assert after == before, f"refused, but the folder changed: {sorted(set(after.items()) ^ set(before.items()))}"
        # Justified when the run without the check would fail or end differently for EITHER answer: a lock that
        # hides the Thinker Mod question (thinker.exe / thinker.dll / the record unreadable) takes the choice away
        # from the player, whatever they would have answered.
        hurt = []
        for a in ("also", "only"):
            if a not in _BRANCH_BASE:
                g0 = fresh("baseline-" + a)
                _BRANCH_BASE[a] = (_branch_run(g0, a), _branch_tree(g0.parent))
                done(g0)
            g2 = fresh("unchecked-" + a)
            release = _branch_hold(g2.parent.joinpath(*locked.split("/")), kind)
            try:
                unchecked = _branch_run(g2, a, check=False)
            finally:
                release()
            tree2 = _branch_tree(g2.parent)
            done(g2)
            hurt.append(unchecked != _BRANCH_BASE[a][0] or tree2 != _BRANCH_BASE[a][1])
        assert any(hurt), "refused, though without the check the run ends as with nothing locked"
    else:
        assert verdict == verdict0, (verdict, verdict0)
        diff = sorted(set(after.items()) ^ set(tree0.items()))
        assert after == tree0, f"the run got through the check but ended differently: {diff}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing modes")
@pytest.mark.parametrize("data", [b"MZ a program file", b"plain text"], ids=["program", "data"])
@pytest.mark.parametrize("mode", ["delete"])
def test_an_entitled_read_only_file_passes_unless_another_program_uses_it(g, mode, data):
    """User ruling 2026-11-17 (D3(b)): the run deletes our read-only files anyway (unlink_entitled clears the bit
    first), so the bit alone refuses no delete; a program holding the file still does -- and the call agrees."""
    import _winapi
    import safe_fs
    p = g / "ours.dll"
    p.write_bytes(data)
    p.chmod(stat.S_IREAD)
    modes = {mode, pfm.ENTITLED}
    assert pfm.probe(p, {mode}) == "the file is read-only"
    assert pfm.probe(p, modes) == ""
    h = _winapi.CreateFile(str(p), 0x80000000, 0x1, 0, 3, 0, 0)          # another program reads it, sharing read
    try:
        assert pfm.probe(p, modes)
        with pytest.raises(OSError):
            safe_fs.unlink_entitled(p) if mode == "delete" else safe_fs.write_entitled(p, b"new")
    finally:
        _winapi.CloseHandle(h)
    safe_fs.unlink_entitled(p) if mode == "delete" else safe_fs.write_entitled(p, b"new")
    assert (not p.exists()) if mode == "delete" else p.read_bytes() == b"new"
