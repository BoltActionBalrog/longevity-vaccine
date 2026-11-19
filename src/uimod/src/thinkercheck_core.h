// thinkercheck_core.h -- the pure half of the Thinker Mod startup check (thinkerversion.cpp): what the loaded
// thinker.dll is, how it is named to the player, and every sentence the dialog and its fallback boxes show.
// No windows.h, no globals: work\tests\thinkercheck_selftest.cpp drives it against the same JSON fixture as the
// Python side, so the two can never disagree on a label or a sentence.
//
// The decision is two questions only (user 2026-11-13: "We just needed to detect if any Thinker is present and
// whether or not it is the one we expect"): is thinker.dll in the process, and do its PE TimeDateStamp and
// SizeOfImage equal the pin in version.h. The label Thinker reports about itself is read for WORDING only.
#pragma once

#include <cstdint>
#include <cstring>
#include <string>

namespace thinkercheck {

// ---- state ---------------------------------------------------------------------------------------------------

enum class State { None, Pin, OffPin };

// `found`: thinker.dll is in the process. `readable`: its PE header could be read.
inline State Decide(bool found, bool readable, uint32_t stamp, uint32_t size, uint32_t pinStamp, uint32_t pinSize)
{
    if (!found) return State::None;
    if (readable && stamp == pinStamp && size == pinSize) return State::Pin;
    return State::OffPin;                       // an unreadable header fails closed
}

// ---- label ---------------------------------------------------------------------------------------------------
// What thinker.dll calls itself (its MOD_VERSION, the string it stores at 0x691870):
//   "Thinker Mod v<d>(.<d>)*" with nothing alphanumeric straight after  -> a plain version
//   "Thinker Mod develop build"                                          -> a development build
//   anything else, or no string                                          -> unrecognised

enum class LabelKind { Version, Develop, Unrecognised };

constexpr int kMaxParts = 4;
struct Label {
    LabelKind kind = LabelKind::Unrecognised;
    int parts[kMaxParts] = { 0, 0, 0, 0 };
    int nparts = 0;
    char version[24] = "";                      // "5.6" for a plain version, else empty
};

namespace detail {
inline bool IsDigit(char c) { return c >= '0' && c <= '9'; }
inline bool IsAlnum(char c) { return IsDigit(c) || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }

// "<d>(.<d>)*" at s[0..n): fills parts/version and returns the characters consumed, 0 when it is not one.
// At most kMaxParts parts of at most 5 digits each: anything longer is not a version we name to a player.
inline size_t ParseDotted(const char* s, size_t n, Label* out)
{
    size_t i = 0;
    int np = 0;
    int parts[kMaxParts] = { 0, 0, 0, 0 };
    for (;;) {
        if (np == kMaxParts) return 0;
        size_t d = 0;
        int v = 0;
        while (i < n && IsDigit(s[i])) {
            if (++d > 5) return 0;
            v = v * 10 + (s[i] - '0');
            ++i;
        }
        if (d == 0) return 0;
        parts[np++] = v;
        if (i + 1 < n && s[i] == '.' && IsDigit(s[i + 1])) { ++i; continue; }
        break;
    }
    if (i >= sizeof out->version) return 0;
    if (out) {
        out->nparts = np;
        for (int k = 0; k < kMaxParts; ++k) out->parts[k] = parts[k];
        memcpy(out->version, s, i);
        out->version[i] = '\0';
    }
    return i;
}
} // namespace detail

// `s` need not be terminated: `n` is how many bytes may be read. A string that is not terminated inside `n` is
// unrecognised (the caller stops at the end of thinker.dll's image).
inline Label ParseLabel(const char* s, size_t n)
{
    Label l;
    if (!s) return l;
    size_t len = 0;
    while (len < n && s[len]) ++len;
    if (len == n) return l;                                   // no terminator inside the readable span
    constexpr char kVer[] = "Thinker Mod v";
    constexpr char kDev[] = "Thinker Mod develop build";
    constexpr size_t kVerLen = sizeof kVer - 1, kDevLen = sizeof kDev - 1;
    if (len == kDevLen && memcmp(s, kDev, kDevLen) == 0) { l.kind = LabelKind::Develop; return l; }
    if (len > kVerLen && memcmp(s, kVer, kVerLen) == 0) {
        Label v;
        const size_t used = detail::ParseDotted(s + kVerLen, len - kVerLen, &v);
        if (used && !detail::IsAlnum(s[kVerLen + used])) {    // s[len] is the terminator: never past the span
            v.kind = LabelKind::Version;
            return v;
        }
    }
    return l;
}

// A dotted version string ("5.5", "1.0.0") as a Label; kind Unrecognised when it is not one.
inline Label ParseVersionString(const char* s)
{
    Label l;
    if (!s) return l;
    const size_t n = strlen(s);
    Label v;
    if (detail::ParseDotted(s, n, &v) == n && n) { v.kind = LabelKind::Version; return v; }
    return l;
}

// -1 / 0 / +1 for two plain versions (missing parts count as 0: "5.5" == "5.5.0").
inline int CompareVersions(const Label& a, const Label& b)
{
    for (int k = 0; k < kMaxParts; ++k) {
        const int x = k < a.nparts ? a.parts[k] : 0, y = k < b.nparts ? b.parts[k] : 0;
        if (x != y) return x < y ? -1 : 1;
    }
    return 0;
}

// True when `have` is a dotted version strictly older than `want`, or is not a version at all: the resident
// installer copy's VERSION file against our own version (an unreadable one must not be trusted to know
// --fix-thinker).
inline bool VersionOlder(const char* have, const char* want)
{
    const Label a = ParseVersionString(have), b = ParseVersionString(want);
    if (a.kind != LabelKind::Version) return true;
    if (b.kind != LabelKind::Version) return false;
    return CompareVersions(a, b) < 0;
}

// True when the label is a plain version equal to `ts` (the "same number, different build" case).
inline bool SameNumber(const Label& l, const char* ts)
{
    const Label t = ParseVersionString(ts);
    return l.kind == LabelKind::Version && t.kind == LabelKind::Version && CompareVersions(l, t) == 0;
}

// {RUN}: how the running build is named to the player. `against` is the version it is being compared with (the
// pin), or null.
inline std::string RunText(const Label& l, const char* against)
{
    switch (l.kind) {
    case LabelKind::Version:
        if (against && SameNumber(l, against)) return std::string("a different build of Thinker Mod ") + l.version;
        return std::string("Thinker Mod ") + l.version;
    case LabelKind::Develop:
        return "a development build of Thinker Mod";
    default:
        return "an unrecognised build of Thinker Mod";
    }
}

// {YOURS}: the same build in a possessive slot -- "your Thinker Mod 5.4", "your different build of Thinker Mod 5.5",
// "your development build of Thinker Mod", "your unrecognised build of Thinker Mod" (the in-game update offer).
inline std::string YoursText(const Label& l, const char* against)
{
    const std::string run = RunText(l, against);
    if (run.compare(0, 2, "a ") == 0) return "your " + run.substr(2);
    if (run.compare(0, 3, "an ") == 0) return "your " + run.substr(3);
    return "your " + run;
}

// ---- the texts (user-approved 2026-11-13/14; work\briefs\thinker-runtime-error-design.md section 13) ----------
// Paragraphs are joined with a blank line; no line break inside a paragraph, no feature names, no paths.

constexpr char kTitle[]        = "Longevity Vaccine";
constexpr char kBtnUpdate[]    = "Update now";
constexpr char kBtnNotNow[]    = "Not now";
constexpr char kBtnDontAsk[]   = "Don't ask me again";

constexpr char kUntested[]     = "This combination has not been tested, and the game may not work correctly.";
constexpr char kUpdateNow[]    = "Choose 'Update now' to open the Longevity Vaccine installer and download the latest "
                                 "compatible versions of Longevity Vaccine and Thinker.";
constexpr char kNotNowText[]   = "Choose 'Not now' to start the game and be asked again next time.";
constexpr char kDontAskText[]  = "Choose 'Don't ask me again' to start the game and stop this question until you next "
                                 "update Longevity Vaccine (undo in Preferences).";
constexpr char kStayInactive[] = "If you start the game anyway, parts of Longevity Vaccine stay inactive.";
constexpr char kNotStarted[]   = "The Longevity Vaccine installer could not be started.";
constexpr char kClosing[]      = "The game will now start as it is, and parts of Longevity Vaccine will stay inactive.";
constexpr char kNotSaved[]     = "Longevity Vaccine could not save your choice, so it will ask again next time.";
constexpr char kCannotStart[]  = "Longevity Vaccine could not apply a memory patch it needs, so the game cannot start "
                                 "safely. Details are in uimod.log.";

namespace detail {
inline std::string Para(const std::string& a, const std::string& b) { return a + "\n\n" + b; }
} // namespace detail

// Paragraph 1: what was expected and what is running.
inline std::string BuildOpening(const char* lv, const char* ts, const Label& l)
{
    if (SameNumber(l, ts))
        return std::string("Longevity Vaccine ") + lv + " was tested with one specific build of Thinker Mod " + ts +
               ". This game is running a different build of Thinker Mod " + ts + ".";
    return std::string("Longevity Vaccine ") + lv + " was built for Thinker Mod " + ts + ". This game is running " +
           RunText(l, nullptr) + ".";
}

// The dialog's body: five paragraphs (user 2026-11-14: the buttons one by one, "stay inactive" last; the opening and
// "not tested" share the first paragraph). Box G keeps them apart: its paragraphs were not changed.
inline std::string BuildBody(const char* lv, const char* ts, const Label& l)
{
    std::string s = BuildOpening(lv, ts, l) + " " + kUntested;
    s = detail::Para(s, kUpdateNow);
    s = detail::Para(s, kNotNowText);
    s = detail::Para(s, kDontAskText);
    return detail::Para(s, kStayInactive);
}

// The advice the fallback boxes share; the address follows as its own paragraph so Ctrl+C gives a clean line.
inline std::string BuildAdvice(const char* ts, const char* url, const char* thinkerPage)
{
    const std::string s = std::string("We recommend downloading and running the Longevity Vaccine installer from ") + url +
                          ", or installing Thinker Mod " + ts + " yourself from Thinker Mod's download page:";
    return detail::Para(s, thinkerPage);
}

// Box F: Update now could not start the installer.
inline std::string BuildBoxF(const char* ts, const char* url, const char* thinkerPage)
{
    return detail::Para(detail::Para(kNotStarted, BuildAdvice(ts, url, thinkerPage)), kClosing);
}

// Box G: the dialog itself could not be shown (also the developer exe, which is never an update target).
inline std::string BuildBoxG(const char* lv, const char* ts, const Label& l, const char* url, const char* thinkerPage)
{
    std::string s = detail::Para(BuildOpening(lv, ts, l), kUntested);
    s = detail::Para(s, BuildAdvice(ts, url, thinkerPage));
    return detail::Para(s, kClosing);
}

// ---- small rules ---------------------------------------------------------------------------------------------

enum Button { kUpdate = 100, kNotNow = 101, kDontAsk = 102 };      // never 0, -1, IDOK (1) or IDCANCEL (2)

// A habitual Enter must not go online when the player turned update checks off.
inline Button DefaultButton(bool checksOn) { return checksOn ? kUpdate : kNotNow; }

// "Don't ask me again" is stored as our own version: it holds until Longevity Vaccine is installed again (the
// installer deletes the key) or the version changes.
inline bool DontAskMatches(const char* stored, const char* lv)
{
    return stored && lv && stored[0] && strcmp(stored, lv) == 0;
}

// The page a player is pointed to for the pinned build: its GitHub release page, or (a development-build pin) that
// one build's own page.
inline std::string ThinkerPage(const char* prefix, const char* tag, const char* devPage)
{
    if (devPage && devPage[0]) return devPage;
    return std::string(prefix) + tag;
}

// "Update now" starts the resident installer with OUR environment minus the variables that would change how it
// behaves when the game itself was started by an installer run (installer_exit.offer_relaunch passes its own
// environment on): no pause suppression, no worker / payload / guard / lock state of that earlier run, no "cannot
// ask" flag, and above all no pre-granted Thinker consent -- the click on Update now is not consent to change
// anything. The trust key (a tester's) is deliberately kept. The same list as the installer's own
// (installer_exit._RUN_SCOPED_ENV); test_thinker_check.py holds the two together.
constexpr const wchar_t* kScrubbedEnv[] = {
    L"LONGEVITY_NO_WAIT", L"LONGEVITY_WORKER", L"LONGEVITY_PAYLOAD_ROOT", L"LONGEVITY_GUARD_MARKER",
    L"LONGEVITY_INSTALL_LOCK", L"LONGEVITY_PLAYER_NO_PROMPT", L"LONGEVITY_THINKER_CONSENT",
};

// `block`: "NAME=value\0NAME=value\0\0" as GetEnvironmentStringsW returns it. The result is the same block without
// kScrubbedEnv (names compared without regard to case, as Windows does), still double-terminated, for
// CreateProcessW with CREATE_UNICODE_ENVIRONMENT.
inline std::wstring ScrubEnvironment(const wchar_t* block)
{
    std::wstring out;
    auto lower = [](wchar_t c) { return (c >= L'A' && c <= L'Z') ? static_cast<wchar_t>(c + 32) : c; };
    for (const wchar_t* p = block; p && *p;) {
        size_t len = 0;
        while (p[len]) ++len;
        size_t eq = 1;                                        // "=C:=C:\dir" entries start with '=': the name is not empty
        while (eq < len && p[eq] != L'=') ++eq;
        bool drop = false;
        for (const wchar_t* name : kScrubbedEnv) {
            size_t n = 0;
            while (name[n]) ++n;
            if (n != eq) continue;
            size_t k = 0;
            while (k < n && lower(p[k]) == lower(name[k])) ++k;
            if (k == n) { drop = true; break; }
        }
        if (!drop) out.append(p, len + 1);
        p += len + 1;
    }
    if (out.empty()) out.push_back(L'\0');
    out.push_back(L'\0');
    return out;
}

// The [UIMod] ThinkerMismatchTest switch: forces OFF-PIN with a label of that kind, so the whole flow can be
// exercised on the supported build. Returns false for anything else (including "0" and empty).
inline bool TestLabel(const char* value, const char* ts, Label* out)
{
    if (!value || !value[0]) return false;
    const Label t = ParseVersionString(ts);
    Label l;
    if (strcmp(value, "dev") == 0) { l.kind = LabelKind::Develop; *out = l; return true; }
    if (strcmp(value, "unknown") == 0) { *out = l; return true; }
    if (t.kind != LabelKind::Version || t.nparts < 2) return false;
    l = t;
    if (strcmp(value, "same") == 0) { *out = l; return true; }
    if (strcmp(value, "newer") == 0) l.parts[1] += 1;
    else if (strcmp(value, "older") == 0) { if (l.parts[1] > 0) l.parts[1] -= 1; else if (l.parts[0] > 0) { l.parts[0] -= 1; l.parts[1] = 9; } }
    else return false;
    std::string v;
    for (int k = 0; k < l.nparts; ++k) { if (k) v += '.'; v += std::to_string(l.parts[k]); }
    if (v.size() >= sizeof l.version) return false;
    memcpy(l.version, v.c_str(), v.size() + 1);
    *out = l;
    return true;
}

} // namespace thinkercheck
