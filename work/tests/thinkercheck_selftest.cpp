// Self-test harness for thinkercheck_core.h (tests\test_thinker_check.py builds and runs it once per module).
// One case per stdin line, fields separated by TAB; one result line per case ("bad" for a malformed line).
// Newlines in a result are printed as the two characters "\n".
//   label <hex>                       -> kind|version|run|same       (the bytes may lack a terminator)
//   run <hex> <against>               -> {RUN} against that version
//   state <found> <readable> <stamp> <size> <pinStamp> <pinSize>     -> none|pin|offpin
//   body <lv> <ts> <hex>              -> the dialog's body
//   boxf <ts> <url> <page>            -> Box F
//   boxg <lv> <ts> <hex> <url> <page> -> Box G
//   older <have> <want>               -> 0|1
//   dontask <stored> <lv>             -> 0|1
//   default <checksOn>                -> the default button id
//   testlabel <value> <ts>            -> kind|version   (or "none")
//   const <name>                      -> a text constant
//   page <prefix> <tag> <devPage|->   -> the page a player is pointed to for the pinned build
//   env <NAME=v;NAME=v;...|->         -> the scrubbed environment block, same form, |1 when double-terminated
//   cmdline <cmd.exe> <bat> <game> <pid> <manifest|->  -> the "Update now" command line, or "refused"
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

#include "../../src/uimod/src/thinkercheck_core.h"
#include "../../src/uimod/src/update_core.h"      // BuildFixThinkerCommandLine (the "Update now" line)

namespace {

using namespace thinkercheck;

std::vector<std::string> Split(const std::string& line)
{
    std::vector<std::string> f;
    size_t a = 0;
    for (;;) {
        const size_t b = line.find('\t', a);
        f.push_back(line.substr(a, b == std::string::npos ? std::string::npos : b - a));
        if (b == std::string::npos) break;
        a = b + 1;
    }
    return f;
}

bool Unhex(const std::string& h, std::string* out)
{
    if (h == "-") { out->clear(); return true; }
    if (h.size() % 2) return false;
    out->clear();
    for (size_t i = 0; i < h.size(); i += 2) {
        char* end = nullptr;
        const std::string b = h.substr(i, 2);
        const long v = strtol(b.c_str(), &end, 16);
        if (*end) return false;
        out->push_back(static_cast<char>(v));
    }
    return true;
}

std::string Esc(const std::string& s)
{
    std::string o;
    for (char c : s) { if (c == '\n') o += "\\n"; else o += c; }
    return o;
}

const char* Kind(const Label& l)
{
    return l.kind == LabelKind::Version ? "version" : l.kind == LabelKind::Develop ? "develop" : "unrecognised";
}

Label FromHex(const std::string& hex, bool* ok)
{
    std::string bytes;
    *ok = Unhex(hex, &bytes);
    return ParseLabel(bytes.data(), bytes.size());      // exactly these bytes: no terminator unless the hex has one
}

} // namespace

int main()
{
    std::string line;
    while (std::getline(std::cin, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        const std::vector<std::string> f = Split(line);
        const std::string& cmd = f[0];
        bool ok = true;
        if (cmd == "label" && f.size() == 2) {
            const Label l = FromHex(f[1], &ok);
            if (!ok) { std::printf("bad\n"); continue; }
            std::printf("%s|%s|%s\n", Kind(l), l.version, RunText(l, nullptr).c_str());
        } else if (cmd == "run" && f.size() == 3) {
            const Label l = FromHex(f[1], &ok);
            if (!ok) { std::printf("bad\n"); continue; }
            std::printf("%s|%d\n", RunText(l, f[2].c_str()).c_str(), SameNumber(l, f[2].c_str()) ? 1 : 0);
        } else if (cmd == "yours" && f.size() == 3) {          // <hex> <against|->  -> {YOURS}
            const Label l = FromHex(f[1], &ok);
            if (!ok) { std::printf("bad\n"); continue; }
            std::printf("%s\n", YoursText(l, f[2] == "-" ? nullptr : f[2].c_str()).c_str());
        } else if (cmd == "state" && f.size() == 7) {
            const State s = Decide(f[1] == "1", f[2] == "1", static_cast<uint32_t>(strtoul(f[3].c_str(), nullptr, 0)),
                                   static_cast<uint32_t>(strtoul(f[4].c_str(), nullptr, 0)),
                                   static_cast<uint32_t>(strtoul(f[5].c_str(), nullptr, 0)),
                                   static_cast<uint32_t>(strtoul(f[6].c_str(), nullptr, 0)));
            std::printf("%s\n", s == State::None ? "none" : s == State::Pin ? "pin" : "offpin");
        } else if (cmd == "body" && f.size() == 4) {
            const Label l = FromHex(f[3], &ok);
            if (!ok) { std::printf("bad\n"); continue; }
            std::printf("%s\n", Esc(BuildBody(f[1].c_str(), f[2].c_str(), l)).c_str());
        } else if (cmd == "boxf" && f.size() == 4) {
            std::printf("%s\n", Esc(BuildBoxF(f[1].c_str(), f[2].c_str(), f[3].c_str())).c_str());
        } else if (cmd == "boxg" && f.size() == 6) {
            const Label l = FromHex(f[3], &ok);
            if (!ok) { std::printf("bad\n"); continue; }
            std::printf("%s\n", Esc(BuildBoxG(f[1].c_str(), f[2].c_str(), l, f[4].c_str(), f[5].c_str())).c_str());
        } else if (cmd == "older" && f.size() == 3) {
            std::printf("%d\n", VersionOlder(f[1].c_str(), f[2].c_str()) ? 1 : 0);
        } else if (cmd == "dontask" && f.size() == 3) {
            std::printf("%d\n", DontAskMatches(f[1].c_str(), f[2].c_str()) ? 1 : 0);
        } else if (cmd == "default" && f.size() == 2) {
            std::printf("%d\n", static_cast<int>(DefaultButton(f[1] == "1")));
        } else if (cmd == "testlabel" && f.size() == 3) {
            Label l;
            if (!TestLabel(f[1].c_str(), f[2].c_str(), &l)) { std::printf("none\n"); continue; }
            std::printf("%s|%s\n", Kind(l), l.version);
        } else if (cmd == "cmdline" && f.size() == 6) {        // cmdExe bat game pid manifest|-  -> the line, or "refused"
            const std::wstring exe(f[1].begin(), f[1].end()), bat(f[2].begin(), f[2].end()), game(f[3].begin(), f[3].end());
            const std::wstring man = f[5] == "-" ? std::wstring() : std::wstring(f[5].begin(), f[5].end());
            static wchar_t out[4096];
            if (!lvupd::BuildFixThinkerCommandLine(exe.c_str(), bat.c_str(), game.c_str(), strtoul(f[4].c_str(), nullptr, 10),
                                                   man.empty() ? nullptr : man.c_str(), out, 4096)) {
                std::printf("refused\n");
                continue;
            }
            std::string narrow;
            for (const wchar_t* p = out; *p; ++p) narrow.push_back(static_cast<char>(*p));
            std::printf("%s\n", narrow.c_str());
        } else if (cmd == "page" && f.size() == 4) {
            std::printf("%s\n", ThinkerPage(f[1].c_str(), f[2].c_str(), f[3] == "-" ? "" : f[3].c_str()).c_str());
        } else if (cmd == "env" && f.size() == 2) {            // entries separated by ';' -> the kept ones, same form
            std::wstring block;
            for (char c : f[1]) block.push_back(c == ';' ? L'\0' : static_cast<wchar_t>(c));
            block.push_back(L'\0');
            block.push_back(L'\0');
            const std::wstring kept = ScrubEnvironment(f[1] == "-" ? L"\0" : block.c_str());
            std::string o;
            const bool terminated = kept.size() >= 2 && kept[kept.size() - 1] == 0 && kept[kept.size() - 2] == 0;
            for (size_t i = 0; i + 1 < kept.size(); ++i) o.push_back(kept[i] ? static_cast<char>(kept[i]) : ';');
            std::printf("%s|%d\n", o.c_str(), terminated ? 1 : 0);
        } else if (cmd == "const" && f.size() == 2) {
            const std::string& n = f[1];
            const char* v = n == "title" ? kTitle : n == "update" ? kBtnUpdate : n == "notnow" ? kBtnNotNow :
                            n == "dontask" ? kBtnDontAsk : n == "notsaved" ? kNotSaved : n == "cannotstart" ? kCannotStart :
                            n == "ids" ? nullptr : "";
            if (!v) std::printf("%d %d %d\n", static_cast<int>(kUpdate), static_cast<int>(kNotNow), static_cast<int>(kDontAsk));
            else std::printf("%s\n", v);
        } else {
            std::printf("bad\n");
        }
    }
    return 0;
}
