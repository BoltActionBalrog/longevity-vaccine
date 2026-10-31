"""The "built for Thinker Mod X" warning: the game's dialog (uimod thinkerversion.cpp) and the installer's
printed warning (install.py) say the same thing, name no features, and take every fact from the single sources
(version.h / version.py, the download URL) so nothing can drift.

User decisions 2026-10-30: the text names NO feature (another build can break anything); two buttons, OK and
"Don't Show Again"; only the latter persists, and only until the Longevity version or the Thinker build changes.
"""
from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import version as ver   # noqa: E402
import manifest         # noqa: E402

REPO = ROOT.parent
SRC = REPO / "src" / "uimod" / "src"
CPP = (SRC / "thinkerversion.cpp").read_text(encoding="utf-8")
INIT = (SRC / "init.cpp").read_text(encoding="utf-8")
INSTALL = (ROOT / "scripts" / "install.py").read_text(encoding="utf-8")

#: The approved wording, verbatim (the installer's second sentence names the folder's file instead of "this game").
SENTENCES = [
    "Some game features may not work as intended.",
    "We recommend checking for a Longevity Vaccine update in-game or at ",
    "If no update exists, consider playing with the officially supported version of Thinker.",
]
#: Words that would name a feature or a module: none may appear in either text.
FEATURE_WORDS = ["cloak", "submarine", "zone of control", "air drop", "airdrop", "pillage", "base screen",
                 "base-screen", "Design Workshop", "scaling", "HUD", "text is drawn", "switched off"]


def _dialog_text() -> str:
    m = re.search(r'_snprintf_s\(text, sizeof text, _TRUNCATE,\s*((?:"[^"]*"\s*)+),', CPP)
    assert m, "the dialog's format string was not found"
    return "".join(re.findall(r'"([^"]*)"', m.group(1)))


# ---------------------------------------------------------------- the DLL's dialog

def test_dialog_text_is_the_approved_wording_and_names_no_feature():
    text = _dialog_text()
    assert text.startswith("Longevity Vaccine %s was built for Thinker Mod %s. This game is running %s.")
    for s in SENTENCES:
        assert s in text, s
    low = text.lower()
    for w in FEATURE_WORDS:
        assert w.lower() not in low, f"the dialog names a feature: {w!r}"


def test_dialog_pulls_every_fact_from_the_single_sources():
    """Our version, the supported Thinker version and the URL are macros / constants, never literals here."""
    assert "UIMOD_VERSION_STRING, UIMOD_THINKER_SUPPORTED_VERSION, running, lvupd::kDownloadUrlShown" in CPP
    assert '#include "version.h"' in CPP and '#include "update_core.h"' in CPP
    code = re.sub(r"//.*", "", CPP)          # comments may name the measured build; code may not
    assert ver.VERSION not in code, "the product version is written as a literal"
    assert ver.THINKER_SUPPORTED_VERSION not in code, "the supported Thinker version is written as a literal"
    assert "longevitymods.com" not in code, "the URL is written as a literal"
    assert "UIMOD_THINKER_SUPPORTED_STAMP" in CPP and "UIMOD_THINKER_SUPPORTED_IMAGE_SIZE" in CPP


def test_two_buttons_and_only_dont_show_again_persists():
    assert "MB_OKCANCEL" in CPP, "two buttons"
    assert 'kDontShowAgain[] = "Don\'t Show Again"' in CPP
    assert "g_relabelled = SetWindowTextA(cancel, kDontShowAgain) != 0;" in CPP, "the Cancel button is relabelled"
    # an un-relabelled Cancel (hook refused, button not found) is a plain close, never a dismissal (audit 2026-10-30)
    assert "return r == IDCANCEL && g_relabelled;" in CPP
    assert "if (!cancel) return CallNextHookEx(nullptr, code, wp, lp);" in CPP, "a box without IDCANCEL leaves the hook armed"
    # persistence happens only on that answer
    assert "if (dontShowAgain) {" in CPP
    assert CPP.count("WritePrivateProfileStringA(kSection, kKeyDismissed, token, ini)") == 1
    # the OK branch writes nothing
    ok_branch = CPP.split("if (dontShowAgain) {", 1)[1].split("} else {", 1)[1].split("}", 1)[0]
    assert "WritePrivateProfile" not in ok_branch


def test_dismissal_holds_until_either_side_changes():
    """The token pairs OUR version with THEIR build: a Longevity update or a new thinker.dll shows the dialog again."""
    assert '"%s/%08X-%X", UIMOD_VERSION_STRING, static_cast<unsigned>(stamp),' in CPP, "stamp AND image size: the pin's identity"
    assert "if (strcmp(dismissed, token) == 0) {" in CPP, "the stored dismissal holds under the test switch too"
    # the ini write is checked: a read-only ini is logged, not reported as dismissed
    assert "if (WritePrivateProfileStringA(kSection, kKeyDismissed, token, ini))" in CPP


def test_the_warning_fires_only_on_a_mismatch_before_any_window():
    assert "if (supported && !test) return;" in CPP
    assert "if (!ThinkerLoaded()) return;" in CPP
    # Init: right after the compat pass, before the pinned modules and before anything creates a window
    i_compat, i_warn, i_text = INIT.index("InstallThinkerCompat();"), INIT.index("ThinkerVersionWarning();"), INIT.index("InstallThinkerText();")
    assert i_compat < i_warn < i_text


def test_the_relabel_hook_is_thread_local_and_one_shot():
    assert "SetWindowsHookExA(WH_CBT, CbtRelabel, nullptr, GetCurrentThreadId())" in CPP
    assert CPP.count("UnhookWindowsHookEx(g_cbt)") == 2, "unhooked on activation and again after the box closes"


def test_project_builds_the_module():
    proj = (REPO / "src" / "uimod" / "uimod.vcxproj").read_text(encoding="utf-8")
    assert 'src\\thinkerversion.cpp' in proj and 'src\\thinkerversion.h' in proj


# ---------------------------------------------------------------- the installer's warning

def _fake_thinker_dll(folder: Path, stamp: int, size: int, label: bytes = b"Thinker Mod v5.6 ") -> Path:
    """A minimal PE: MZ header, e_lfanew, PE signature, TimeDateStamp, SizeOfImage, then the version string."""
    pe = 0x80
    hdr = bytearray(pe + 0x100)
    hdr[0:2] = b"MZ"
    hdr[0x3C:0x40] = struct.pack("<I", pe)
    hdr[pe:pe + 4] = b"PE\0\0"
    hdr[pe + 8:pe + 12] = struct.pack("<I", stamp)
    hdr[pe + 0x50:pe + 0x54] = struct.pack("<I", size)
    p = folder / "thinker.dll"
    p.write_bytes(bytes(hdr) + label + b"\0 padding")
    return p


@pytest.fixture
def install():
    import install as mod
    mod.ver = ver
    return mod


def test_installer_is_silent_without_thinker_or_on_the_supported_build(tmp_path, install):
    assert install.thinker_build_warning(tmp_path) == ""
    _fake_thinker_dll(tmp_path, ver.THINKER_SUPPORTED_STAMP, ver.THINKER_SUPPORTED_IMAGE_SIZE, b"Thinker Mod v5.5 ")
    assert install.thinker_build_warning(tmp_path) == ""


def test_installer_warns_on_another_build_in_the_approved_words(tmp_path, install):
    _fake_thinker_dll(tmp_path, ver.THINKER_SUPPORTED_STAMP + 1, ver.THINKER_SUPPORTED_IMAGE_SIZE)
    text = install.thinker_build_warning(tmp_path)
    assert text.startswith(f"Longevity Vaccine {ver.VERSION} was built for Thinker Mod {ver.THINKER_SUPPORTED_VERSION}. "
                           "This game folder's thinker.dll is Thinker Mod v5.6.")
    for s in SENTENCES:
        assert s in text, s
    assert manifest.DOWNLOAD_URL in text
    low = text.lower()
    for w in FEATURE_WORDS:
        assert w.lower() not in low, f"the installer names a feature: {w!r}"
    # a same-stamp build of another size is another build too
    _fake_thinker_dll(tmp_path, ver.THINKER_SUPPORTED_STAMP, ver.THINKER_SUPPORTED_IMAGE_SIZE + 0x1000)
    assert install.thinker_build_warning(tmp_path)


def test_installer_handles_a_broken_or_unlabelled_dll(tmp_path, install):
    (tmp_path / "thinker.dll").write_bytes(b"not a PE at all")
    assert "an unreadable thinker.dll" in install.thinker_build_warning(tmp_path)
    _fake_thinker_dll(tmp_path, 1, 2, b"no label here")
    assert "an unrecognised build of Thinker Mod" in install.thinker_build_warning(tmp_path)


def _body(name: str) -> str:
    m = re.search(rf"^def {name}\(.*?(?=^def |\Z)", INSTALL, re.M | re.S)
    assert m, name
    return m.group(0)


def test_installer_warns_in_both_flows():
    """The fresh install (_install, main's no-mode branch) and do_update each call it once; the summary
    carries a row so the warning cannot scroll out of sight."""
    assert "return _install(game_dir, args)" in _body("main")
    assert _body("_install").count("warn_thinker_build(game_dir)") == 1
    assert _body("do_update").count("warn_thinker_build(game_dir)") == 1
    assert 'ix.status_line("Thinker Mod version", "skip")' in _body("_install")


def test_installer_reads_the_image_with_unreadable_pages_skipped():
    """RunningThinker() runs on every foreign build: it must not touch reserved pages inside SizeOfImage."""
    assert "VirtualQuery(" in CPP and "mbi.State == MEM_COMMIT" in CPP and "PAGE_GUARD" in CPP


def test_installer_treats_a_truncated_pe_as_unreadable(tmp_path, install):
    p = _fake_thinker_dll(tmp_path, 1, 2)
    data = p.read_bytes()
    pe = int.from_bytes(data[0x3C:0x40], "little")
    p.write_bytes(data[:pe + 0x20])          # cut inside the optional header: a short slice must not read as 0
    assert "an unreadable thinker.dll" in install.thinker_build_warning(tmp_path)


def test_the_real_thinker_55_is_the_supported_build():
    dll = Path(r"D:\SmacxThinker\game\thinker.dll")
    if not dll.is_file():
        pytest.skip("Thinker workspace not present")
    import install as mod
    stamp, size, label = mod.thinker_build(dll.parent)
    assert (stamp, size) == (ver.THINKER_SUPPORTED_STAMP, ver.THINKER_SUPPORTED_IMAGE_SIZE)
    assert label == f"Thinker Mod v{ver.THINKER_SUPPORTED_VERSION}"
