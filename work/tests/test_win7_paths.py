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


def test_update_check_logs_a_failed_job_assignment():
    src = (SRC / "update.cpp").read_text(encoding="utf-8", errors="replace")
    i = src.index("AssignProcessToJobObject(job, pi.hProcess)")
    block = src[i:i + 700]
    assert 'Log("kill-on-close job not available' in block and "Windows 7" in block
