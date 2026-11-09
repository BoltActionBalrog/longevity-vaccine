"""Windows 7 code paths the game-time audit (2026-11-01) found wanting, pinned.

1. PNG portraits: the Windows 10 SDK's CLSID_WICPngDecoder is the v2 decoder, which plain Windows 7 SP1 does
   not register (Platform Update KB2670838 only) -- every PNG portrait, HD pack included, vanished with a log
   line blaming the file. The v1 decoder exists on every Windows since Vista; the DLL must carry BOTH GUIDs
   and fall back, and name the WIC step that refused.
2. GPU scaler: the shader compiles at run time; Windows 7 has d3dcompiler_47 only via KB4019990 but usually
   has d3dcompiler_43 from the DirectX June 2010 redist. Probe both; name the missing DLL.
3. The update check's kill-on-close job cannot be nested on Windows 7 (a launcher's job): say so in the log.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SRC = REPO / "src" / "uimod" / "src"
DLL = REPO / "src" / "uimod" / "build" / "Release" / "uimod.dll"

PNG_DECODER_V1 = uuid.UUID("389EA17B-5078-4CDE-B6EF-25C15175C751")
PNG_DECODER_V2 = uuid.UUID("E018945B-AA86-4008-9BD4-6777A1E40C11")
IMAGING_FACTORY_V1 = uuid.UUID("CACAF262-9370-4615-A13B-9F5539DA4C0A")     # Vista+; the SDK's default is v2 (8+)
IMAGING_FACTORY_V2 = uuid.UUID("317D06E8-5F24-433D-BDF7-79CE68D8ABC2")


def test_png_decoder_falls_back_to_v1_and_names_the_wic_step():
    src = (SRC / "portrait_files.cpp").read_text(encoding="utf-8", errors="replace")
    i2 = src.index("CLSID_WICPngDecoder :")                 # the SDK's (v2 under the Win10 SDK)
    i1 = src.index("CLSID_WICPngDecoder1, nullptr")         # the fallback CALL (the comment above names v1 too)
    assert i2 < i1, "try the SDK's decoder first, v1 second"
    assert "REGDB_E_CLASSNOTREG" in src[i2:i1], "the fallback is keyed on the class not being registered"
    assert "WIC %s failed (0x%08lX) for replacement" in src and 'Log("[uimod] portrait: %s %s -> vanilla\\n", why, path)' in src
    assert "thread_local const char* g_wicStep" in src, "the game thread and the prewarm worker both decode"
    # the factory is asked for one step earlier and has the same v2-only problem on plain 7 SP1
    f2 = src.index("CoCreateInstance(CLSID_WICImagingFactory, nullptr")
    f1 = src.index("CLSID_WICImagingFactory1, nullptr")
    assert f2 < f1 < i2 and "REGDB_E_CLASSNOTREG" in src[f2:f1]


def test_built_dll_carries_both_wic_factory_and_png_decoder_guids():
    """Plain Windows 7 SP1 registers only the v1 WIC classes; the Win10 SDK names v2. Both must be in the DLL."""
    if not DLL.is_file():
        pytest.skip("uimod.dll not built")
    data = DLL.read_bytes()
    assert PNG_DECODER_V2.bytes_le in data, "the SDK's v2 PNG decoder CLSID"
    assert PNG_DECODER_V1.bytes_le in data, "the v1 PNG decoder CLSID Windows 7 SP1 has"
    assert IMAGING_FACTORY_V2.bytes_le in data, "the SDK's v2 imaging factory CLSID"
    assert IMAGING_FACTORY_V1.bytes_le in data, "the v1 imaging factory CLSID Windows 7 SP1 has"


def test_gpu_scaler_probes_both_compilers_and_names_them():
    src = (SRC / "gpuscale.cpp").read_text(encoding="utf-8", errors="replace")
    assert 'LoadLibraryA("d3dcompiler_47.dll")' in src and 'LoadLibraryA("d3dcompiler_43.dll")' in src
    m = re.search(r'm\.Err\("loading d3dcompiler_47\.dll / d3dcompiler_43\.dll[^"]*"', src)
    assert m and "KB4019990" in m.group(0)
    assert 'm.Err("loading d3d11.dll' in src, "d3d11 and the compiler are reported separately"


def test_desktop_folders_come_from_shell32_not_powershell(monkeypatch):
    """Stock Windows 7 has PowerShell 2.0 on .NET 3.5, where CommonDesktopDirectory does not exist: the old
    PowerShell lookup returned nothing and every run nagged for a shortcut it could not place."""
    import sys
    sys.path.insert(0, str(REPO / "work" / "scripts"))
    import install as inst
    monkeypatch.delenv("LONGEVITY_DESKTOP_DIRS", raising=False)
    monkeypatch.setattr(inst, "_ps", lambda script: "")          # PowerShell unavailable: must not matter
    dirs = inst._desktop_dirs()
    assert dirs and all(d.is_dir() for d in dirs), dirs
    assert any(d.name.lower() == "desktop" for d in dirs)
    src = (REPO / "work" / "scripts" / "install.py").read_text(encoding="utf-8", errors="replace")
    body = src[src.index("def _desktop_dirs("):src.index("def _ps(")]
    assert "SHGetFolderPathW" in body and "_ps(" not in body, "no PowerShell for the lookup (its prose may mention it)"


def _code(src: str) -> str:
    """C++ with every comment removed (// and /* */): a comment can never satisfy a source test."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(ln.split("//", 1)[0] for ln in src.splitlines())


def test_update_check_logs_a_failed_job_assignment():
    """The worker records the failure (it never logs, and the child must be resumed whatever happens); LogResult says
    it once, with the error."""
    raw = (SRC / "update.cpp").read_text(encoding="utf-8", errors="replace")
    src = _code(raw)
    i = src.index("AssignProcessToJobObject(job, pi.hProcess)")
    block = src[i:src.index("ResumeThread(pi.hThread)", i)]
    assert "r->jobErr = GetLastError();" in block
    assert "Windows 7" in raw[raw.index("AssignProcessToJobObject(job, pi.hProcess)"):][:1200]
    log = src[src.index("void LogResult(const Result& r)"):]
    log = log[:log.index("\n}\n")]
    assert 'Log("kill-on-close job not available (error %lu' in log and "r.jobErr" in log


def test_update_children_run_on_every_cpu_not_the_games_pin():
    """DDrawCompat pins the game process to one CPU by default and children inherit the mask: the update check took
    24-32 s at a cold launch and hit its 30 s deadline 3 times in 11 (2026-11-08).  Both children (the check and the
    updater hand-off) are created SUSPENDED, widened to the system's CPUs, and only then resumed -- the check after it
    is in its kill-on-close job.  A missing resume would leave every check a 30 s timeout, so the order is pinned."""
    src = (SRC / "update.cpp").read_text(encoding="utf-8", errors="replace")
    code = _code(src)                                                           # code only: a comment cannot satisfy it
    widen = code[code.index("void WidenAffinity(HANDLE process"):]
    widen = widen[:widen.index("\n}\n")]
    # DDrawCompat hooks kernel32's SetProcessAffinityMask process-wide and no-ops it while its pin is on (audit
    # 2026-11-08, probed with the game's ddraw.dll): the widen goes through ntdll, and the mask is read back
    assert "SetProcessAffinityMask" not in code, "DDrawCompat swallows it: use NtSetInformationProcess"
    assert '"NtSetInformationProcess"' in widen and "kProcessAffinityMask = 21" in widen
    assert "setInfo(process, kProcessAffinityMask, &want, sizeof want);" in widen
    assert "DWORD_PTR want = proc;" in widen, "the system set (GetProcessAffinityMask's 2nd slot), not the pinned one"
    assert widen.count("GetProcessAffinityMask(process, &child, &sys)") == 2, "read back before and after"
    body = code[code.index("void WorkerBody(Job* j, Result* r)"):]
    body = body[:body.index("\nvoid LogResult(")]
    assert "CREATE_SUSPENDED" in body[:body.index("CreateProcessW(")]
    i_widen, i_job = body.index("WidenAffinity(pi.hProcess,"), body.index("AssignProcessToJobObject(job, pi.hProcess)")
    i_resume = body.index("ResumeThread(pi.hThread)")
    assert body.index("CreateProcessW(") < i_widen < i_job < i_resume
    assert "return" not in body[i_widen:i_resume]
    # the resume is unconditional: the statement before it ends a statement or a block, never an `if (`
    before = body[:i_resume].rstrip()
    assert not re.search(r"\bif\s*\([^;{}]*$", before.splitlines()[-1]) or "== static_cast<DWORD>(-1)" in body[i_resume - 40:i_resume + 60]
    assert body.count("ResumeThread(pi.hThread)") == 1
    assert "Log(" not in body, "the worker never logs (LogResult says it): nothing may delay the resume"
    log = code[code.index("void LogResult(const Result& r)"):]
    assert "check ran on CPUs 0x%llx" in log[:log.index("\n}\n")]
    hand = code[code.index("bool SpawnUpdater("):]
    hand = hand[:hand.index("\n}\n")]
    assert "CREATE_NEW_CONSOLE | CREATE_SUSPENDED" in hand
    assert hand.index("WidenAffinity(pi.hProcess,") < hand.index("ResumeThread(pi.hThread)") < hand.index("CloseHandle(pi.hThread);")
