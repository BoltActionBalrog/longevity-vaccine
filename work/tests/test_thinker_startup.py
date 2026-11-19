"""The Thinker Mod startup check as wired into the DLL (src/uimod/src/thinkerversion.cpp, init.cpp, update.cpp,
thinkercompat.cpp): where it runs, what each answer does, and the "Update now" hand-off to the resident installer.

The rules these pin (work/briefs/thinker-runtime-error-design.md, user rulings 2026-11-13/14):
- one detection, two questions: is thinker.dll loaded, and is it the pinned build;
- the dialog comes up in PreInit, before the display is touched and before a byte of ours is written;
- "Update now" closes the game ONLY after the installer's console really started, and every way that can fail is
  checked before anything is closed (the game then starts, with a box that says so);
- "Don't ask me again" is our own version in [UIMod] ThinkerMismatchDontAsk, read back after the write; Reset Skipped
  Updates deletes it, Restore Defaults never touches it, an unfinished Thinker change overrides it;
- off the pinned build nothing of ours chains into or undoes Thinker's code.

Source-level tests plus one self-test batch (the command line) and two real cmd.exe round trips, the second through
the real run-install.bat: no game, no window.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import cpp_harness  # noqa: E402
import version as ver  # noqa: E402

REPO = ROOT.parent
SRC = REPO / "src" / "uimod" / "src"


def _read(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


def _code(text: str) -> str:
    """The source without // comments (a comment may quote a version or an old name; code may not)."""
    return re.sub(r"//.*", "", text)


CPP = _read("thinkerversion.cpp")
CODE = _code(CPP)
INIT = _code(_read("init.cpp"))
UPDATE = _code(_read("update.cpp"))
COMPAT = _code(_read("thinkercompat.cpp"))


def _fn(code: str, signature: str) -> str:
    """The body of the function whose definition starts with `signature` (up to the first line that is just '}')."""
    start = code.index(signature)
    return code[start:code.index("\n}\n", start)]


# ---------------------------------------------------------------- facts and sources

def test_every_fact_comes_from_the_single_sources():
    assert ver.VERSION not in CODE, "the product version is written as a literal"
    assert f'"{ver.THINKER_SUPPORTED_VERSION}"' not in CODE, "the supported Thinker version is written as a literal"
    assert "longevitymods.com" not in CODE and "github.com" not in CODE and "dropbox" not in CODE.lower()
    for macro in ("UIMOD_VERSION_STRING", "UIMOD_THINKER_SUPPORTED_VERSION", "UIMOD_THINKER_SUPPORTED_STAMP",
                  "UIMOD_THINKER_SUPPORTED_IMAGE_SIZE", "UIMOD_THINKER_SUPPORTED_TAG", "UIMOD_THINKER_DEV_PAGE",
                  "lvupd::kDownloadUrlShown", "lvupd::kThinkerReleasePagePrefix"):
        assert macro in CODE, macro
    # no sentence is written here: they all live in thinkercheck_core.h, where test_thinker_check.py pins them
    assert not re.search(r'"[^"\n]*(Longevity Vaccine|Thinker Mod) [^"\n]*\.[" ]', CODE.replace("[uimod]", "")), \
        "a player-facing sentence is written in thinkerversion.cpp"


def test_the_old_two_button_box_is_gone():
    for old in ("MB_OKCANCEL", "SetWindowsHookEx", "CbtRelabel", "Don't Show Again", "ThinkerVersionWarningDismissed",
                "ThinkerVersionWarnTest", "ThinkerVersionWarning("):
        for name in ("thinkerversion.cpp", "thinkerversion.h", "init.cpp", "update.cpp", "prefs.cpp", "thinkercompat.cpp"):
            assert old not in _code(_read(name)), f"{old!r} is still in {name}"


def test_project_builds_the_module_and_lists_its_headers():
    proj = (REPO / "src" / "uimod" / "uimod.vcxproj").read_text(encoding="utf-8")
    for f in ("src\\thinkerversion.cpp", "src\\thinkerversion.h", "src\\thinkercheck_core.h", "src\\thinkerdialog.h"):
        assert f in proj, f


# ---------------------------------------------------------------- where it runs

def test_the_check_runs_in_preinit_before_the_display_is_touched():
    pre = _fn(INIT, 'extern "C" void __stdcall PreInit(HMODULE prax)')
    i_dpi, i_ghost = pre.index("EnsureDpiAware();"), pre.index("EnsureNoGhosting();")
    i_check, i_vid = pre.index("ThinkerStartupCheck(true);"), pre.index("VidModePreInit(prax);")
    assert i_dpi < i_ghost < i_check < i_vid


def test_init_decides_only_when_preinit_never_ran_and_always_before_the_compat_pass():
    init = INIT[INIT.index('extern "C" void __stdcall Init(HMODULE self)'):]
    i_check, i_compat, i_text = init.index("ThinkerStartupCheck(false);"), init.index("InstallThinkerCompat();"), init.index("InstallThinkerText();")
    assert i_check < i_compat < i_text
    body = _fn(CODE, "void ThinkerStartupCheck(bool preInit)")
    assert body.index("if (ran) return;") < body.index("Detect();"), "a second call is a no-op"
    # the one-phase developer exe: a box, never the dialog, never Update now
    dev = body[body.index("if (!preInit) {"):body.index("wchar_t ini[")]
    assert "BoxG();" in dev and "return;" in dev and "AskPlayer" not in dev and "StartInstaller" not in dev


def test_there_is_one_detection_and_nothing_waits_for_thinker():
    detect = _fn(CODE, "void Detect()")
    assert 'GetModuleHandleA("thinker.dll")' in detect
    assert "Decide(g.found, g.readable, g.stamp, g.size, UIMOD_THINKER_SUPPORTED_STAMP, UIMOD_THINKER_SUPPORTED_IMAGE_SIZE)" in detect
    assert 'GetModuleHandleA("thinker.dll")' not in COMPAT, "the compat pass takes the detection from the startup check"
    assert "ThinkerPresent()" in COMPAT and "ThinkerOnPin()" in COMPAT and "ThinkerImageRange(" in COMPAT
    # Thinker's DllMain has returned before PreInit runs (the loader lock): no wait, no third state
    assert "Sleep(" not in detect and "WaitFor" not in CODE
    assert "State::OffPin" in CODE and "PinUnconfirmed" not in CODE


def test_the_label_comes_from_thinkers_own_pointer_through_the_tested_reader():
    """The bounds themselves are RUN in test_thinker_live.py (a committed page followed by a reserved one); here only
    that the startup check hands the right pointer and image range to that reader, and reads nothing itself."""
    read = _fn(CODE, "Label LoadedLabel(uintptr_t lo, uintptr_t hi)")
    assert "kVA_EngineVersion - 0x400000" in read and "0x691870" in CODE
    assert "thinkerlive::ReadLabel(p, lo, hi, &why)" in read
    assert "strlen(" not in CODE and "strcpy" not in CODE
    detect = _fn(CODE, "void Detect()")
    assert "g.label = LoadedLabel(g.lo, g.hi);" in detect
    # the header itself is read only where it is readable
    assert detect.index("thinkerlive::Readable(base, sizeof(IMAGE_DOS_HEADER))") < detect.index("nt->FileHeader.TimeDateStamp")


# ---------------------------------------------------------------- the answers

def test_update_now_closes_the_game_only_after_the_installer_really_started():
    body = _fn(CODE, "void ThinkerStartupCheck(bool preInit)")
    upd = body[body.index("case kUpdate:"):body.index("case kDontAsk:")]
    assert upd.index("if (StartInstaller()) {") < upd.index("TerminateProcess(GetCurrentProcess(), 0);") < upd.index("BoxF();")
    # exit code 0 (a launcher must not read a crash) in exactly two places: Update now and the close box
    assert CODE.count("TerminateProcess(GetCurrentProcess(), 0)") == 2
    closed = body[body.index("case thinkerdialog::kClosed:"):body.index("case thinkerdialog::kQuit:")]
    assert "TerminateProcess(GetCurrentProcess(), 0)" in upd and "TerminateProcess(GetCurrentProcess(), 0)" in closed
    assert "ExitProcess" not in CODE, "inside _initterm: no atexit handler, no DLL detach"
    # every failure is found before anything is closed
    start = _fn(CODE, "bool StartInstaller()")
    order = [start.index(s) for s in ("&bat, &script, &python", "VersionOlder(have.c_str(), UIMOD_VERSION_STRING)",
                                      "thinkerlive::FileMentions(script.c_str(), kFixThinkerFlag)",
                                      "lvupd::BuildFixThinkerCommandLine(", "ScrubEnvironment(block)",
                                      "return UpdateSpawnVisible(")]
    assert order == sorted(order)
    assert start.count("return false;") >= 7, "game dir, missing file, old copy, no --fix-thinker, system dir, refused line, no environment"
    # the installer copy must KNOW the switch (a capability, not a version number): the one shipped release without
    # it would otherwise close the game and answer with an argument error
    assert 'kFixThinkerFlag[] = "--fix-thinker"' in CODE
    # never a console with our whole environment: a pre-granted consent an installer run left behind must not reach it
    assert "return UpdateSpawnVisible(cmdExe.c_str(), cmd, game, env.c_str());" in start and "nullptr)" not in start[start.index("ScrubEnvironment(block)"):]
    assert "UpdateRuntimeExeRel()" in start, "the bundled interpreter is checked too: antivirus removes it"
    assert "TerminateProcess" not in start


def test_the_shared_spawn_keeps_the_console_alive_after_the_game():
    # "\n{": the definition, not the forward declaration above SpawnUpdater
    spawn = _fn(UPDATE, "bool SpawnVisible(const wchar_t* cmdExe, wchar_t* cmd, const wchar_t* cwd, const wchar_t* env)\n{")
    assert "CREATE_NEW_CONSOLE | CREATE_SUSPENDED | (env ? CREATE_UNICODE_ENVIRONMENT : 0)" in spawn
    assert "CreateProcessW(cmdExe, cmd, nullptr, nullptr, FALSE, flags," in spawn, "no inherited handles"
    assert "AssignProcessToJobObject" not in spawn, "no job object: the console must outlive the game"
    assert spawn.index("WidenAffinity(pi.hProcess,") < spawn.index("ResumeThread(pi.hThread)")
    failed = spawn[spawn.index("ResumeThread(pi.hThread) == static_cast<DWORD>(-1)"):]
    assert failed.index("return false;") < failed.index("return true;"), "a child that never resumed is a failure"


def test_dont_ask_is_our_version_written_and_read_back():
    rem = _fn(CODE, "void RememberDontAsk(const wchar_t* ini)")
    assert "WritePrivateProfileStringW(kSection, kThinkerDontAskKey, lv.c_str(), ini)" in rem
    assert rem.index("WritePrivateProfileStringW(") < rem.index("GetPrivateProfileStringW(kSection, kThinkerDontAskKey") < rem.index("if (wrote && lv == back)")
    assert "Wide(UIMOD_VERSION_STRING)" in rem
    assert rem.rstrip().endswith("Box(kNotSaved);"), "a failed save is said, not hidden"
    assert "WritePrivateProfileStringA" not in CODE and "GetPrivateProfileStringA" not in CODE, "the W API, as receipt.py reads it"
    body = _fn(CODE, "void ThinkerStartupCheck(bool preInit)")
    assert "DontAskMatches(storedA, UIMOD_VERSION_STRING)" in body
    # only that answer writes
    for case in ("case kNotNow:", "case thinkerdialog::kQuit:"):
        seg = body[body.index(case):]
        assert "WritePrivateProfile" not in seg[:seg.index("break;")]


def test_the_close_box_ends_the_process_and_starts_nothing():
    """User 2026-11-14: the close box opens nothing, neither the game nor the installer. It must be the first thing the
    case does after its log line -- no ini write, no installer, no box -- and it ends the process the way Update now
    does from PreInit (TerminateProcess, never ExitProcess: no atexit handler, no PRACX / DDrawCompat detach)."""
    body = _fn(CODE, "void ThinkerStartupCheck(bool preInit)")
    seg = body[body.index("case thinkerdialog::kClosed:"):]
    seg = seg[:seg.index("case thinkerdialog::kQuit:")]
    code = re.sub(r"//.*", "", seg)
    assert "TerminateProcess(GetCurrentProcess(), 0);" in code and "for (;;) Sleep(INFINITE);" in code
    for forbidden in ("WritePrivateProfile", "StartInstaller", "Box", "RememberDontAsk", "ExitProcess", "break;"):
        assert forbidden not in code, forbidden
    assert code.index("UimodLog(") < code.index("TerminateProcess(")
    # PreInit runs the check before the display is touched: nothing for the close to leave half-done
    init = (SRC / "init.cpp").read_text(encoding="utf-8")
    pre = init[init.index('extern "C" void __stdcall PreInit(HMODULE prax)'):]
    pre = pre[:pre.index("\n}\n")]
    assert pre.index("ThinkerStartupCheck(true);") < pre.index("VidModePreInit(prax);")


def test_an_unfinished_thinker_change_overrides_dont_ask():
    body = _fn(CODE, "void ThinkerStartupCheck(bool preInit)")
    assert 'kJournalRel[] = L"LongevityMods\\\\thinker-journal.json"' in CODE
    dis = body[body.index("if (DontAskMatches("):body.index("const bool checksOn")]
    assert dis.index("if (!journal) {") < dis.index("return;"), "silent only when nothing is pending"


def test_the_default_button_is_read_from_the_ini_not_from_the_update_checker():
    body = _fn(CODE, "void ThinkerStartupCheck(bool preInit)")
    assert "GetPrivateProfileIntW(kSection, kKeyChecks, kUpdateCheckDefault, ini) != 0" in body
    assert "UpdateCheckGet()" not in CODE, "InstallUpdateCheck has not run yet in PreInit"
    assert "spec.defaultId = DefaultButton(checksOn);" in CODE and "spec.guardMs = kGuardMs;" in CODE
    assert "kGuardMs = 400" in CODE


def test_reset_skipped_updates_clears_it_and_restore_defaults_never_does():
    sub = _fn(UPDATE, "bool UpdateSubscribeAll()")
    assert 'WritePrivateProfileStringW(L"UIMod", kThinkerDontAskKey, nullptr, ini)' in sub
    assert sub.index('L"DeclinedUpdates"') < sub.index("kThinkerDontAskKey")
    assert 'kThinkerDontAskKey[] = L"ThinkerMismatchDontAsk"' in _read("update.h")
    prefs = _read("prefs.cpp")
    assert "ThinkerMismatchDontAsk" not in prefs and "kThinkerDontAskKey" not in prefs


def test_a_failed_dialog_and_a_failed_installer_each_get_their_box():
    body = _fn(CODE, "void ThinkerStartupCheck(bool preInit)")
    default = body[body.index("default:"):]
    assert "BoxG();" in default
    assert "BuildBoxF(UIMOD_THINKER_SUPPORTED_VERSION, lvupd::kDownloadUrlShown, ThinkerDownloadPage().c_str())" in CODE
    assert "MB_OK | MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST" in CODE
    stop = _fn(CODE, "void ThinkerCannotStart()")
    assert stop.index("Box(kCannotStart);") < stop.index("TerminateProcess(GetCurrentProcess(), 1);")


# ---------------------------------------------------------------- reduced mode: the compat pass

def test_off_the_pinned_build_no_chain_and_no_undo_is_installed():
    install = _fn(COMPAT, "void InstallThinkerCompat()")
    assert "const bool onPin = ThinkerOnPin();" in install
    chains = install[install.index("int chained = 0"):install.index("int undone = 0")]
    undos = install[install.index("int undone = 0"):]
    assert chains.index("if (onPin) {") < chains.index("InstallChain(kChains[i])")
    assert undos.index("if (onPin) {") < undos.index("UndoThinkerCall(u)")
    assert "g_thinker" not in COMPAT


def _first(body: str, *needles: str) -> int:
    """Where the first of `needles` occurs in `body` (every one must occur)."""
    return min(body.index(n) for n in needles)


def test_the_punishment_sphere_view_installs_nothing_on_another_thinker():
    """A gate inside ThinkerCheck would leave five hook families and three naked stubs running inside a foreign
    Thinker's compute flow (audit 2026-11-14): the installer returns before it reads, allocates or writes anything."""
    ps = _code(_read("pssphere.cpp"))
    body = _fn(ps, "void InstallPunishmentSphereView()")
    gate = body.index("if (ThinkerPresent() && !ThinkerOnPin()) {")
    assert gate < _first(body, "UimodPcave2Range(", "VirtualAlloc(", "DetourEntryN(", "Retarget(", "g_installed = true;")
    assert "return;" in body[gate:gate + 260]


@pytest.mark.parametrize("name, signature, first_touch", [
    ("thinkertext.cpp", "void InstallThinkerText()", "nt->FileHeader.TimeDateStamp"),
    ("thinkeraivis.cpp", "void InstallThinkerAiVis()", "g_base = reinterpret_cast<BYTE*>(lo);"),
    ("leaderfree.cpp", "void InstallFreedMessageThinker()", "BYTE* const base = reinterpret_cast<BYTE*>(lo);"),
])
def test_each_thinker_detour_module_stands_down_before_it_reads_thinker(name, signature, first_touch):
    body = _fn(_code(_read(name)), signature)
    gate = body.index("if (!ThinkerOnPin()) {")
    assert gate < body.index(first_touch), "the gate comes before the module looks inside thinker.dll"
    assert "return;" in body[gate:gate + 420]
    assert '#include "thinkerversion.h"' in _read(name)


def test_hudmovesfix_wraps_thinkers_action_only_on_the_pinned_build():
    hud = _code(_read("hudmovesfix.cpp"))
    assert "if (entry[0] == 0xE9 && ThinkerOnPin() && ThinkerRange(&tlo, &thi)) {" in hud
    assert hud.count("ThinkerRange(") == 1, "no other path reaches into thinker.dll"


def test_under_thinker_the_ai_filter_is_in_force_only_with_its_thinker_half():
    """Half a filter (the engine's planner filtered, Thinker's not) is worse than none; off the pinned build the
    Thinker half is never installed, so the filter is off and a host broadcasts it as off."""
    ai = _code(_read("aivis.cpp"))
    assert _fn(ai, "bool ThinkerAllows()").replace(" ", "").endswith("return!ThinkerLoaded()||g_thinkerHalf;")
    enabled = _fn(ai, "bool Enabled()")
    assert "if (!g_coreOk || !ThinkerAllows()) return false;" in enabled
    # the last host's mask is forgotten outside a network game BEFORE that gate, or it would never be forgotten
    # (NetMasksReset clears g_netValid and the 1.0.1 masks with it: the host's last-sent latch, the client's mask)
    assert enabled.index("if (single) NetMasksReset();") < enabled.index("if (!g_coreOk || !ThinkerAllows()) return false;")
    assert "void NetMasksReset() { g_netValid = false;" in ai
    mask = _fn(ai, "uint32_t LocalNetMask()")
    assert "const bool family = ThinkerAllows();" in mask, "the host's broadcast follows it"
    assert "(g_local && family ? kNetBitAiVis : 0) | kNetBitHumanLeaks" in mask
    assert "(g_cargoOne && g_cargoOk && family ? kNetBitCargoOne : 0)" in mask and "(g_local && g_podOk && family ? kNetBitPodRadius : 0)" in mask
    # the settings nested under the filter are off with it
    assert "if (!g_cargoOk || !ThinkerAllows()) return false;" in _fn(ai, "bool CargoOneActive()")
    assert "if (!g_podOk || !ThinkerAllows()) return false;" in _fn(ai, "bool PodRadiusActive()")
    assert "if (!g_markOn || !ThinkerAllows()) return;" in ai
    assert "kNetBitHumanLeaks" not in _fn(ai, "bool ThinkerAllows()"), "the human-leak half is not part of this"
    assert ai.count("g_thinkerHalf = true;") == 1 and "void  AiVisThinkerHalfInstalled() { g_thinkerHalf = true; }" in ai
    th = _code(_read("thinkeraivis.cpp"))
    body = _fn(th, "void InstallThinkerAiVis()")
    assert body.rstrip().endswith("AiVisThinkerHalfInstalled();"), "reported only at the very end of a completed install"
    assert "Thinker Mod v" not in th and "const char* Version(" not in th, "the label has one reader (thinkerversion.cpp)"


def test_preferences_dim_the_rows_that_cannot_be_in_force():
    prefs = _code(_read("prefs.cpp"))
    # unticked / unsaved / tooltip: ONLY under the mismatch, where every effect behind the rows is off (a failed byte
    # check alone leaves the alert mark, the cargo rule and the pod radius running: audit 2026-11-14)
    assert "bool ThinkerMismatched() { return ThinkerPresent() && !ThinkerOnPin(); }" in prefs
    assert "bool CloakGroupUnavailable() { return ThinkerMismatched() && AiVisForcedOff(); }" in prefs
    assert "bool AirdropUnavailable() { return ThinkerMismatched() && !AiVisAirdropInstalled(); }" in prefs
    # all four rows: the filter, its two nested rows, the air drops
    un = prefs[prefs.index("const bool unavailable ="):]
    un = un[:un.index(";")]
    assert "(aiRow || cargoRow || markRow) ? CloakGroupUnavailable() : airdropRow ? AirdropUnavailable() : false" in un
    dim = prefs[prefs.index("const bool dim = rcRow ?"):]
    dim = dim[:dim.index(";")]
    assert ": unavailable ? true" in dim
    # every other reason dims as before (and still shows the stored tick)
    assert ": aiRow ? AiVisForcedOff()" in dim and ": airdropRow ? !AiVisAirdropInstalled()" in dim
    assert ": (cargoRow || markRow) ? (AiVisGetLocal() == 0 || AiVisForcedOff())" in dim, "the nested rows dim with their parent"
    assert dim.index(": unavailable ? true") < dim.index(": aiRow ? AiVisForcedOff()")
    # a dimmed row ignores clicks, like every other dimmed row: a click must not change a game it cannot affect
    ai_click = prefs[prefs.index("if (id == kAiChkId) {"):]
    assert ai_click.index("if (AiVisForcedOff()) return;") < ai_click.index("AiVisSetLocal(on);")
    for row in ("kCargoChkId", "kMarkChkId"):
        seg = prefs[prefs.index(f"if (id == {row}) {{"):]
        assert "if (!AiVisGetLocal() || AiVisForcedOff()) return;" in seg[:260], row
    drop = prefs[prefs.index("if (id == kAirdropChkId) {"):]
    assert drop.index("if (!AiVisAirdropInstalled()) return;") < drop.index("AiVisSetAirdrop(")


def test_unavailable_rows_read_unticked_and_their_stored_choice_is_never_written():
    """User 2026-11-14: "The checkbox should appear to be unticked in this case. However, we shouldn't actually save the
    change in settings, so if they were to resolve the Thinker mismatch, those settings would just come back"."""
    prefs = _code(_read("prefs.cpp"))
    draw = _fn(prefs, "void __fastcall CheckContentDraw(void* self, void* /*edx*/)")
    # unavailable -> dimmed, and a dimmed row reads unticked (the owner's rule for every dimmed row, 2026-11-14)
    dim = draw[draw.index("const bool dim ="):draw.index("const bool on =")]
    assert ": unavailable ? true" in dim
    assert "const bool on = !dim && (" in draw
    assert draw.index("const bool unavailable =") < draw.index("const bool dim =") < draw.index("const bool on =") \
        < draw.index("kVA_ChkOnSprite")
    assert "dim ? g_greyText : kChkTextColor" in draw
    # OK: nothing of an unavailable row is saved
    commit = _fn(prefs, "void CommitAll()")
    cloak = commit[commit.index("if (!CloakGroupUnavailable()) {"):]
    cloak = cloak[:cloak.index("}")]
    for save in ("AiVisSaveLocal();", "AiVisSaveCargoOne();", "AiVisSaveMark();"):
        assert save in cloak and commit.count(save) == 1, save
    assert "if (!AirdropUnavailable()) AiVisSaveAirdrop();" in commit and commit.count("AiVisSaveAirdrop();") == 1
    # Restore Defaults: an unavailable row is left as stored
    rd = prefs[prefs.index("} else if (id == 0x5A) {"):]
    cloak = rd[rd.index("if (!CloakGroupUnavailable()) {"):]
    cloak = cloak[:cloak.index("}")]
    for s in ("AiVisSetLocal(kAiVisDefault);", "AiVisSetCargoOne(kCargoOneDefault);", "AiVisSetMark(kCloakMarkDefault);"):
        assert s in cloak and prefs.count(s) == 1, s
    assert "if (!AirdropUnavailable()) AiVisSetAirdrop(kAirdropDivertDefault);" in rd
    assert prefs.count("AiVisSetAirdrop(kAirdropDivertDefault)") == 1


def test_unavailable_rows_say_why_on_hover_only_under_a_mismatched_thinker():
    raw = _read("prefs.cpp")
    assert 'const char kMismatchTip[] = "Unavailable with mismatched Thinker";' in raw, "the user's words, exactly"
    prefs = _code(raw)
    assert "bool ThinkerMismatched() { return ThinkerPresent() && !ThinkerOnPin(); }" in prefs
    assert "BYTE* const tipRows[4] = { g_w.aicheck, g_w.cargocheck, g_w.markcheck, g_w.airdropcheck };" in prefs
    tip = prefs[prefs.index("if (ThinkerMismatched()) {"):]
    tip = tip[:tip.index("\n        }\n")]
    assert "i < 3 ? CloakGroupUnavailable() : AirdropUnavailable()" in tip
    assert "At(kVA_SetBtnBubble))(tipRows[i], nullptr, kMismatchTip)" in tip
    # after the rows' BaseButton_init (which frees and clears each row's bubble text), so every build writes it again
    assert prefs.index("row(g_w.airdropcheck, kAirdropChkId") < prefs.index("if (ThinkerMismatched()) {")
    # shown AT ONCE (user 2026-11-14: "Remove the delay in the tooltip ... when showing the mismatched Thinker
    # tooltip"): the rows' private vtable wraps FlatButton_on_mouse_move, and the wrapper calls the hover timer's own
    # target (BaseButton_show_bubble(0): stops that timer, shows the bubble) only for these rows
    assert "constexpr uintptr_t kVA_BtnShowBubble = 0x00607B30;" in prefs and "constexpr int kBtnSlotMove = 0x44;" in prefs
    assert "g_origRowMove = reinterpret_cast<FBtnMove>(g_chkVtbl[kBtnSlotMove / 4]);" in prefs
    assert "g_chkVtbl[kBtnSlotMove / 4] = reinterpret_cast<void*>(&RowMouseMove);" in prefs
    move = _fn(prefs, "void __fastcall RowMouseMove(void* self, void* edx, int x, int y)")
    assert move.index("g_origRowMove(self, edx, x, y);") < move.index("if (!IsMismatchTipRow(self)) return;") \
        < move.index("At(kVA_BtnShowBubble))(self, nullptr, 0)"), "the engine's move first; other rows keep the delay"
    assert "kBtnHoverOfs) != 1" in move and "kBtnBubbleTextOfs)" in move and "Rd<void*>(kVA_BubbleOwner) == self) return;" in move
    rowfn = _fn(prefs, "bool IsMismatchTipRow(const void* w)")
    assert "AirdropUnavailable()" in rowfn and "CloakGroupUnavailable()" in rowfn
    # no late or stray tooltip: dropped whenever page 1 (where the four rows sit) is hidden -- a tab change or a flip
    # to page 2 -- and, by the per-message backstop, when the window closes
    page1 = _fn(prefs, "template <typename F> void ForPage1(F f)")
    for w in ("g_w.aicheck", "g_w.cargocheck", "g_w.markcheck", "g_w.airdropcheck"):
        assert f"f({w});" in page1, w
    assert "RowTipClear();" in _fn(prefs, "void HidePage1()")
    poll = _fn(prefs, "void PrefsBubblePoll()")
    assert "IsMismatchTipRow(owner)" in poll and "RowTipClear();" in poll and "OurTabActive()" in poll
    # a bubble still showing a row's text is dropped BEFORE BaseButton_init frees that text (audit 2026-11-14)
    clear = prefs.index("if (Rd<void*>(kVA_BubbleOwner) == r) reinterpret_cast<void(__cdecl*)()>(At(kVA_ClearBubble))();")
    assert prefs.index("BYTE* const tipRows[4]") < clear < prefs.index("row(g_w.aicheck, kAiChkId")


# ---------------------------------------------------------------- the command line

CMD = r"C:\Windows\system32\cmd.exe"
GAME = r"C:\Games\Alpha Centauri (GOG)"
BAT = GAME + r"\LongevityMods\updater\scripts\run-install.bat"


@pytest.fixture(scope="module")
def selftest():
    if not cpp_harness.have_toolchain():
        pytest.skip("MSVC toolchain not present")
    exe = cpp_harness.build(ROOT / "tests" / "thinkercheck_selftest.cpp", "thinkercheck_selftest_")

    def go(lines: list[str]) -> list[str]:
        p = subprocess.run([str(exe)], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=60)
        assert p.returncode == 0, p.stderr
        out = p.stdout.splitlines()
        assert len(out) == len(lines), p.stdout[-400:]
        return out
    return go


def test_update_now_command_line_is_the_agreed_one(selftest):
    plain, with_manifest = selftest([f"cmdline\t{CMD}\t{BAT}\t{GAME}\t4242\t-",
                                     f"cmdline\t{CMD}\t{BAT}\t{GAME}\t7\thttps://example.invalid/m.json"])
    assert plain == f'"{CMD}" /D /S /C ""{BAT}" --fix-thinker --game-dir "{GAME}" --wait-pid 4242"'
    assert with_manifest == (f'"{CMD}" /D /S /C ""{BAT}" --fix-thinker --game-dir "{GAME}" --wait-pid 7 '
                             f'--manifest "https://example.invalid/m.json""')
    for line in (plain, with_manifest):
        assert "--update" not in line and "--no-wait" not in line and line.count("--fix-thinker") == 1


@pytest.mark.parametrize("game", [
    r"C:\Games\Alpha Centauri & Alien Crossfire",      # cmd.exe metacharacters
    r"C:\Games\100% SMAC", r"C:\Games\SMAC!", r"C:\Games\a|b", r"C:\Games\a<b", r"C:\Games\a>b", r"C:\Games\a^b",
    r'C:\Games\a"b',
    r"C:\Games\smac--update-test",                     # run-install.bat would route the run to the bootstrap
    r"C:\Games\smac --no-wait",                        # run-install.bat would silence every pause
])
def test_a_game_path_the_console_would_misread_is_refused(selftest, game):
    bat = game + r"\LongevityMods\updater\scripts\run-install.bat"
    assert selftest([f"cmdline\t{CMD}\t{bat}\t{game}\t1\t-"]) == ["refused"]


def test_a_manifest_value_cannot_smuggle_a_routing_switch(selftest):
    assert selftest([f"cmdline\t{CMD}\t{BAT}\t{GAME}\t1\thttps://x.invalid/--update",
                     f"cmdline\t{CMD}\t{BAT}\t{GAME}\t1\thttps://x.invalid/--no-wait",
                     f"cmdline\t{CMD}\t{BAT}\t{GAME}\t1\thttps://x.invalid/a&b"]) == ["refused"] * 3


def test_the_line_survives_real_cmd_exe_with_spaces_and_parentheses(selftest, tmp_path):
    """The batch file must receive exactly the arguments the DLL built (mirrors the --update hand-off's round trip)."""
    import os
    game = tmp_path / "Alpha Centauri (GOG) test"
    scripts = game / "LongevityMods" / "updater" / "scripts"
    scripts.mkdir(parents=True)
    out = game / "args.txt"
    bat = scripts / "run-install.bat"
    bat.write_text(f'@echo off\r\n>"{out}" echo %*\r\n', encoding="ascii")
    cmd_exe = os.path.join(os.environ["SystemRoot"], "System32", "cmd.exe")
    line = selftest([f"cmdline\t{cmd_exe}\t{bat}\t{game}\t31337\t-"])[0]
    assert line != "refused", "the temp path has a character the builder refuses"
    subprocess.run(line, check=True, timeout=60)
    assert out.read_text(encoding="ascii").strip() == f'--fix-thinker --game-dir "{game}" --wait-pid 31337'


def test_the_line_reaches_the_installer_through_the_real_batch_file(selftest, tmp_path):
    """The round trip above uses a one-line batch file. This one copies work/run-install.bat itself into the place the
    DLL looks for it, so its own routing is run: the arguments must reach install.py unchanged, never bootstrap.py
    (the --update route), with the pauses left on (a player is reading the console) and the exit code passed back.
    The interpreter is a small stand-in that records what it is handed (argv_echo.cpp); that the real install.py
    accepts exactly these arguments is run in test_thinker_contract.py."""
    import os
    import shutil
    game = tmp_path / "Alpha Centauri (GOG) test"
    updater = game / "LongevityMods" / "updater"
    scripts = updater / "scripts"
    python = updater / "tools" / "python"
    scripts.mkdir(parents=True)
    python.mkdir(parents=True)
    bat = scripts / "run-install.bat"
    shutil.copyfile(ROOT / "run-install.bat", bat)
    (scripts / "install.py").write_text("raise SystemExit('the stand-in interpreter never reads this')\n", encoding="ascii")
    (scripts / "bootstrap.py").write_text("raise SystemExit('the --update route must not be taken')\n", encoding="ascii")
    shutil.copyfile(cpp_harness.build(ROOT / "tests" / "argv_echo.cpp", "argv_echo_"), python / "python.exe")

    cmd_exe = os.path.join(os.environ["SystemRoot"], "System32", "cmd.exe")
    line = selftest([f"cmdline\t{cmd_exe}\t{bat}\t{game}\t31337\t-"])[0]
    assert line != "refused", "the temp path has a character the builder refuses"
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("LONGEVITY_") and k.upper() != "NOWAIT"}
    p = subprocess.run(line, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL, timeout=60)
    out = p.stdout + p.stderr
    assert "INSTALLATION FAILED" not in out and "INSTALLER ERROR" not in out and "status marker" not in out, out
    got = (python / "argv.txt").read_text(encoding="utf-8").splitlines()
    assert got == [str(scripts / "install.py"), "--fix-thinker", "--game-dir", str(game), "--wait-pid", "31337",
                   "NOWAIT=-"], got
    assert p.returncode == 7, "the installer's exit code is the console's"


def test_the_dialog_logs_whether_themed_buttons_would_be_possible():
    """The dialog uses classic buttons until this line has been read from a real run (themes under DDrawCompat and
    Thinker's launcher are unmeasured). It must ask through GetProcAddress on modules ALREADY loaded: no new import
    (Windows 7 loads this DLL) and no library pulled into the game for a log line."""
    themes = _fn(CODE, "void LogThemes()")
    for name in ('"IsAppThemed"', '"IsThemeActive"', '"DllGetVersion"'):
        assert f"GetProcAddress(ux, {name})" in themes or f"GetProcAddress(cc, {name})" in themes, name
    assert "LoadLibrary" not in themes and "GetModuleHandleW(L\"uxtheme.dll\")" in themes
    ask = _fn(CODE, "int AskPlayer(bool checksOn, DWORD* error)")
    assert ask.index("LogThemes();") < ask.index("thinkerdialog::Run(")
