// Harness for src\uimod\src\update_core.h (built by test_update_core.py; no Windows API).
//   t parse <exit> <infile>                 -> canonical dump of ParseCheckOutput
//   t bytes <n>                             -> FormatBytes
//   t decline <rawfile> [item ver]...       -> DeclineParse (+DeclineSet pairs) -> DeclineFormat
//   t cmdline <utf8file>                    -> ExtractLvManifest on the file's one line
//   t buildcmd <py> <script> <game> [<manifest>] -> BuildCheckCommandLine
//   t handoff <bat> <game> <pid> <manifest|-> [id...] -> BuildUpdateCommandLine (the accept hand-off)
//   t handoffmods <exit> <infile> <accepted 0|1> [new id...] -> HandoffModules as a csv
//   t label <bodyfile> <xs> <sprite|-> <reply>... -> BuildLabelFile
//   t replies <ctx> <kind>                  -> ReplySetFor + ActionFor(-1)
//   t body update <ctx> <exit> <infile>     -> BuildUpdateBody
//   t body pack <ctx> <kind> <idx> <alsoCore|-> <exit> <infile> -> BuildPackBody
//   t manual <reason>                       -> ManualNoticeBody
//   t text url|noinstaller|quit|subscribe   -> the fixed strings
#include "../../src/uimod/src/update_core.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <io.h>
#include <string>
#include <vector>

using namespace lvupd;

static std::string slurp(const char* path)
{
    std::string s;
    if (FILE* f = fopen(path, "rb")) {
        char buf[4096]; size_t n;
        while ((n = fread(buf, 1, sizeof buf, f)) > 0) s.append(buf, n);
        fclose(f);
    }
    return s;
}

static void dump(const UpdateInfo& u, ParseStatus st, int bad)
{
    printf("status=%s code=%d badline=%d\n", ParseStatusName(st), u.code, bad);
    if (u.latest[0]) printf("latest=%s\n", u.latest);
    if (u.hasBase) printf("base=%s>%s\n", u.baseFrom, u.baseTo);
    for (int i = 0; i < u.nStale; ++i) {
        printf("stale=%s|%s|%s>%s|", u.stale[i].id, u.stale[i].label, u.stale[i].from, u.stale[i].to);
        if (u.stale[i].hasBytes) printf("%llu", u.stale[i].bytes);
        printf("\n");
    }
    for (int i = 0; i < u.nFresh; ++i) {
        printf("new=%s|%s|%s|", u.fresh[i].id, u.fresh[i].label, u.fresh[i].to);
        if (u.fresh[i].hasBytes) printf("%llu", u.fresh[i].bytes);
        printf("\n");
    }
    if (u.code == kCodeManual) printf("manual=%s reason=%d\n", u.manualKey, u.manualReason);
}

static bool parse_file(const char* exitS, const char* path, UpdateInfo* u, ParseStatus* st, int* bad)
{
    const std::string in = slurp(path);
    *st = ParseCheckOutput(in.data(), in.size(), atoi(exitS), false, u, bad);
    return true;
}

static std::wstring widen(const std::string& s)
{
    std::wstring w;
    for (unsigned char c : s) if (c != '\r' && c != '\n') w.push_back(static_cast<wchar_t>(c));
    return w;
}

int main(int argc, char** argv)
{
    if (argc < 2) return 2;
    _setmode(_fileno(stdout), _O_BINARY);          // the label file's CRLF must reach the test as written
    const std::string mode = argv[1];
    if (mode == "parse" && argc == 4) {
        UpdateInfo u; ParseStatus st; int bad;
        parse_file(argv[2], argv[3], &u, &st, &bad);
        dump(u, st, bad);
        return 0;
    }
    if (mode == "overflow" && argc == 3) {                     // exit code, empty buffer, overflow flag set
        UpdateInfo u; int bad;
        const ParseStatus st = ParseCheckOutput("", 0, atoi(argv[2]), true, &u, &bad);
        dump(u, st, bad);
        return 0;
    }
    if (mode == "bytes" && argc == 3) {
        char out[32];
        FormatBytes(_strtoui64(argv[2], nullptr, 10), true, out, sizeof out);
        printf("%s\n", out);
        return 0;
    }
    if (mode == "decline" && argc >= 3) {
        const std::string raw = slurp(argv[2]);
        Declines d;
        DeclineParse(raw.data(), raw.size(), &d);
        for (int i = 3; i + 1 < argc; i += 2)
            printf("set %s %s -> %d\n", argv[i], argv[i + 1], DeclineSet(&d, argv[i], argv[i + 1]) ? 1 : 0);
        char out[2048];
        const bool ok = DeclineFormat(d, out, sizeof out);
        printf("ok=%d\n%s\n", ok ? 1 : 0, ok ? out : "");
        return 0;
    }
    if (mode == "delay" && argc == 3) {
        const std::wstring cmd = widen(slurp(argv[2]));
        printf("%d\n", ExtractLvDelaySeconds(cmd.c_str()));
        return 0;
    }
    if (mode == "runtime-exe" && argc == 4) {                  // <major> <minor> -> the interpreter for that Windows
        printf("%ls\n", RuntimeExeRel(strtoul(argv[2], nullptr, 10), strtoul(argv[3], nullptr, 10)));
        return 0;
    }
    if (mode == "cmdline" && argc == 3) {
        const std::wstring cmd = widen(slurp(argv[2]));
        wchar_t out[2048];
        if (ExtractLvManifest(cmd.c_str(), out, 2048)) printf("%ls\n", out);
        else printf("<none>\n");
        return 0;
    }
    if (mode == "buildcmd" && (argc == 5 || argc == 6)) {
        const std::wstring py = widen(argv[2]), sc = widen(argv[3]), game = widen(argv[4]);
        const std::wstring mf = argc == 6 ? widen(argv[5]) : L"";
        wchar_t out[4096];
        if (BuildCheckCommandLine(py.c_str(), sc.c_str(), game.c_str(), mf.empty() ? nullptr : mf.c_str(), out, 4096))
            printf("%ls\n", out);
        else printf("<refused>\n");
        return 0;
    }
    if (mode == "handoff" && argc >= 6) {                      // <bat> <game> <pid> <manifest|-> [id...] -> BuildUpdateCommandLine
        const std::wstring bat = widen(argv[2]), game = widen(argv[3]);
        const std::wstring mf = std::string(argv[5]) == "-" ? L"" : widen(argv[5]);
        std::vector<const char*> ids;
        for (int i = 6; i < argc; ++i) ids.push_back(argv[i]);
        wchar_t out[4096];
        if (BuildUpdateCommandLine(L"C:\\Windows\\System32\\cmd.exe", bat.c_str(), game.c_str(), strtoul(argv[4], nullptr, 10),
                                   ids.empty() ? nullptr : ids.data(), static_cast<int>(ids.size()),
                                   mf.empty() ? nullptr : mf.c_str(), out, 4096))
            printf("%ls\n", out);
        else printf("<refused>\n");
        return 0;
    }
    if (mode == "handoffmods" && argc >= 5) {                  // <exit> <infile> <accepted 0|1> [new id...] -> HandoffModules csv
        UpdateInfo u;
        const std::string in = slurp(argv[3]);
        int bad = 0;
        if (ParseCheckOutput(in.data(), in.size(), atoi(argv[2]), false, &u, &bad) != kOk) { printf("<parse failed>\n"); return 0; }
        std::vector<const char*> fresh;
        for (int i = 5; i < argc; ++i) fresh.push_back(argv[i]);
        const char* out[2 * kMaxItems];
        const int n = HandoffModules(u, atoi(argv[4]) != 0, fresh.empty() ? nullptr : fresh.data(),
                                     static_cast<int>(fresh.size()), out, 2 * kMaxItems);
        if (n < 0) { printf("<refused>\n"); return 0; }
        for (int i = 0; i < n; ++i) printf("%s%s", i ? "," : "", out[i]);
        printf("%s\n", n ? "" : "<none>");
        return 0;
    }
    if (mode == "label" && argc >= 5) {
        const std::string body = slurp(argv[2]);
        LabelSpec s = {};
        s.label = "UPDATE"; s.caption = kCaption; s.xs = atoi(argv[3]);
        s.sprite = strcmp(argv[4], "-") == 0 ? nullptr : argv[4];
        s.body = body.c_str();
        s.nReplies = 0;
        for (int i = 5; i < argc && s.nReplies < 5; ++i) s.replies[s.nReplies++] = argv[i];
        static char out[8192];
        if (BuildLabelFile(s, out, sizeof out)) fwrite(out, 1, strlen(out), stdout);
        else printf("<refused>");
        return 0;
    }
    if (mode == "replies" && argc == 4) {
        ReplySet r;
        ReplySetFor(static_cast<Context>(atoi(argv[2])), static_cast<PromptKind>(atoi(argv[3])), &r);
        for (int i = 0; i < r.n; ++i) printf("%d %s\n", r.act[i], r.text[i]);
        printf("esc=%d\n", ActionFor(r, -1));
        printf("beyond=%d\n", ActionFor(r, r.n));
        return 0;
    }
    if (mode == "body" && argc >= 4) {
        const std::string what = argv[2];
        static char out[4096];
        if (what == "update" && argc == 6) {
            UpdateInfo u; ParseStatus st; int bad;
            parse_file(argv[4], argv[5], &u, &st, &bad);
            printf("%s\n", BuildUpdateBody(u, static_cast<Context>(atoi(argv[3])), out, sizeof out) ? out : "<refused>");
            return 0;
        }
        if (what == "pack" && argc == 9) {
            UpdateInfo u; ParseStatus st; int bad;
            parse_file(argv[7], argv[8], &u, &st, &bad);
            const int idx = atoi(argv[5]);
            const char* also = strcmp(argv[6], "-") == 0 ? nullptr : argv[6];
            printf("%s\n", BuildPackBody(u.fresh[idx], also, static_cast<Context>(atoi(argv[3])),
                                         static_cast<PromptKind>(atoi(argv[4])), out, sizeof out) ? out : "<refused>");
            return 0;
        }
    }
    if (mode == "manual" && argc == 3) { printf("%s\n", ManualNoticeBody(atoi(argv[2]))); return 0; }
    if (mode == "text" && argc == 3) {
        const std::string w = argv[2];
        if (w == "url") printf("%s\n", kDownloadUrl);
        else if (w == "noinstaller") printf("%s\n", kNoInstallerBody);
        else if (w == "quit") printf("%s\n", kQuitManuallyBody);
        else if (w == "subscribe") printf("%s\n", kSubscribeBody);
        else return 2;
        return 0;
    }
    if (mode == "labels" && argc == 2) {
        for (const KnownModule& m : kKnownModules) printf("%s=%s\n", m.id, m.label);
        return 0;
    }
    if (mode == "manualitem" && argc == 3) {
        char out[64];
        printf("%s\n", ManualDeclineItem(strcmp(argv[2], "-") == 0 ? "" : argv[2], out, sizeof out) ? out : "<refused>");
        return 0;
    }
    if (mode == "version" && argc == 4) {
        Version a, b;
        const bool oa = ParseVersion(argv[2], strlen(argv[2]), &a), ob = ParseVersion(argv[3], strlen(argv[3]), &b);
        printf("%d %d %d\n", oa ? 1 : 0, ob ? 1 : 0, oa && ob ? CompareVersion(a, b) : 99);
        return 0;
    }
    fprintf(stderr, "bad usage\n");
    return 2;
}
