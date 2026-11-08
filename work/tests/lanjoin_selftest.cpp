// Self-test harness for lanjoin_core.h (tests\test_lanjoin_core.py builds and runs it).
// Reads one command per line on stdin (fields separated by TABs), prints one result line per command:
//   sockaddr <32 hex>                    -> "ip:port" | "bad"
//   write <ip> <port>                    -> 32 hex
//   parseip <s>                          -> "<dotted>" | "bad"
//   subnet <x> <ip/prefix ...>           -> 1 | 0
//   header <file> <name>                 -> the value | "-"
//   xml <file> <tag>                     -> the value | "-"
//   url <s>                              -> "host port path" | "bad"
//   resolve <location> <urlbase|-> <ref> -> the URL | "-"
//   service <file>                       -> "type control" | "none"
//   soap <type> <action> [k=v ...]       -> the envelope, with \r\n as "|" and \n as "/"
//   status <file> / body <file>          -> the status code / the body
//   mapping <file>                       -> "client:port enabled" | "bad"
//   endtag <file> <tag>                  -> the index of </tag> or </ns:tag> | -1
//   complete <file>                      -> 1 when headers + Content-Length bytes are in
//   trusted <location> <control> <gw,..> -> 1 when both are on one gateway
//   gate <hr hex> <flags> <q> [k=v..]    -> "1 ip:port why | calls" | "0 - why | calls" (a scripted Env; see below)
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include "../../src/uimod/src/lanjoin_core.h"

using namespace lanjoin;

static std::vector<std::string> Split(const std::string& s, char sep)
{
    std::vector<std::string> out;
    std::string cur;
    for (char c : s) {
        if (c == sep) { out.push_back(cur); cur.clear(); }
        else cur += c;
    }
    out.push_back(cur);
    return out;
}

static std::string ReadFile(const std::string& p)
{
    std::ifstream f(p, std::ios::binary);
    std::stringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

static uint32_t Ip(const std::string& s)
{
    uint32_t ip = 0;
    if (!ParseIPv4(s, &ip)) return 0;
    return ip;
}

static V4 QueryOf(const std::string& s)
{
    V4 v;
    if (s == "bad") return v;
    const size_t c = s.find(':');
    v.ip = Ip(s.substr(0, c));
    v.port = static_cast<uint16_t>(std::atoi(s.substr(c + 1).c_str()));
    v.ok = true;
    return v;
}

static std::string Run(const std::vector<std::string>& a)
{
    const std::string& cmd = a[0];
    if (cmd == "sockaddr") {
        unsigned char b[16] = {};
        const std::string& h = a[1];
        for (size_t i = 0; i < 16 && 2 * i + 1 < h.size(); ++i) b[i] = static_cast<unsigned char>(std::stoul(h.substr(2 * i, 2), nullptr, 16));
        const int size = a.size() > 2 ? std::atoi(a[2].c_str()) : 16;
        const V4 v = ParseSockaddr(b, size);
        return v.ok ? FormatIPv4(v.ip) + ":" + std::to_string(v.port) : "bad";
    }
    if (cmd == "write") {
        unsigned char b[16];
        std::memset(b, 0xAA, sizeof b);
        WriteSockaddr(b, Ip(a[1]), static_cast<uint16_t>(std::atoi(a[2].c_str())));
        char out[40] = {};
        for (int i = 0; i < 16; ++i) std::snprintf(out + 2 * i, 3, "%02x", b[i]);
        return out;
    }
    if (cmd == "parseip") {
        uint32_t ip = 0;
        return ParseIPv4(a.size() > 1 ? a[1] : "", &ip) ? FormatIPv4(ip) : "bad";
    }
    if (cmd == "logip") return LogIPv4(Ip(a[1]), a.size() > 2 ? a[2].c_str() : "<public>");
    if (cmd == "subnet") {
        std::vector<Subnet> subs;
        for (size_t i = 2; i < a.size(); ++i) {
            const size_t sl = a[i].find('/');
            Subnet s;
            s.ip = Ip(a[i].substr(0, sl));
            s.prefix = static_cast<uint8_t>(std::atoi(a[i].substr(sl + 1).c_str()));
            subs.push_back(s);
        }
        return OnLocalSubnet(Ip(a[1]), subs) ? "1" : "0";
    }
    if (cmd == "header") {
        const std::string v = HeaderValue(ReadFile(a[1]), a[2].c_str());
        return v.empty() ? "-" : v;
    }
    if (cmd == "xml") {
        const std::string v = XmlValue(ReadFile(a[1]), a[2].c_str());
        return v.empty() ? "-" : v;
    }
    if (cmd == "url") {
        const Url u = ParseHttpUrl(a[1]);
        return u.ok ? u.host + " " + std::to_string(u.port) + " " + u.path : "bad";
    }
    if (cmd == "resolve") {
        const std::string v = ResolveUrl(a[1], a[2] == "-" ? "" : a[2], a[3]);
        return v.empty() ? "-" : v;
    }
    if (cmd == "service") {
        const Service s = FindWanService(ReadFile(a[1]));
        return s.ok ? s.type + " " + s.control : "none";
    }
    if (cmd == "soap") {
        std::vector<std::pair<std::string, std::string>> args;
        for (size_t i = 3; i < a.size(); ++i) {
            const size_t eq = a[i].find('=');
            args.push_back({a[i].substr(0, eq), a[i].substr(eq + 1)});
        }
        std::string s = SoapEnvelope(a[1], a[2].c_str(), args), out;
        for (size_t i = 0; i < s.size(); ++i) {
            if (s[i] == '\r' && i + 1 < s.size() && s[i + 1] == '\n') { out += '|'; ++i; }
            else if (s[i] == '\n') out += '/';
            else out += s[i];
        }
        return out;
    }
    if (cmd == "status") return std::to_string(HttpStatus(ReadFile(a[1])));
    if (cmd == "body") return HttpBody(ReadFile(a[1]));
    if (cmd == "mapping") {
        const Mapping m = ParseMappingResponse(ReadFile(a[1]));
        return m.ok ? FormatIPv4(m.internalClient) + ":" + std::to_string(m.internalPort) + " " + (m.enabled ? "1" : "0") : "bad";
    }
    if (cmd == "endtag") {
        const size_t at = FindEndTag(ReadFile(a[1]), a[2].c_str(), 0);
        return at == std::string::npos ? "-1" : std::to_string(at);
    }
    if (cmd == "complete") return HttpComplete(ReadFile(a[1])) ? "1" : "0";
    if (cmd == "trusted") {
        std::vector<uint32_t> gws;
        for (const std::string& g : Split(a[3], ',')) if (!g.empty()) gws.push_back(Ip(g));
        return TrustedRouterUrls(ParseHttpUrl(a[1]), ParseHttpUrl(a[2]), gws) ? "1" : "0";
    }
    if (cmd == "gate") {
        // gate <hr hex> <flags> <q ip:port|bad> [key=value ...]: router=<ip>|none map=<ip:port[:0]>|none
        // local=0|1 answers=0|1 recent=0|1 loops=1|0|-1 (asked with a TCP port) loops0=1|0|-1 (asked without one)
        struct Fake : Env {
            std::string router = "none", map = "none";
            bool local = true, answers = true, recent = false;
            int loops = 0, loops0 = -1;
            std::string log;
            void Note(const std::string& s) { log += (log.empty() ? "" : ";") + s; }
            bool RouterExternal(uint32_t* e) override { Note("router"); if (router == "none") return false; *e = Ip(router); return true; }
            Mapping LookUp(uint16_t port, bool tcp) override {
                Note("lookup " + std::to_string(port) + (tcp ? " tcp" : " udp"));
                Mapping m;
                if (map == "none") return m;
                const std::vector<std::string> f = Split(map, ':');
                m.internalClient = Ip(f[0]);
                m.internalPort = static_cast<uint16_t>(std::atoi(f[1].c_str()));
                m.enabled = f.size() < 3 || f[2] != "0";
                m.ok = true;
                return m;
            }
            bool IsLocal(uint32_t ip) override { Note("local " + FormatIPv4(ip)); return local; }
            bool Answers(uint32_t ip, uint16_t port) override { Note("answers " + FormatIPv4(ip) + ":" + std::to_string(port)); return answers; }
            bool AnsweredRecently(uint32_t ip) override { Note("recent " + FormatIPv4(ip)); return recent; }
            int LoopsBack(uint32_t ext, uint16_t port, uint32_t pip, uint16_t pport) override {
                Note("loops " + FormatIPv4(ext) + ":" + std::to_string(port) + ">" + FormatIPv4(pip) + ":" + std::to_string(pport));
                return port ? loops : loops0;
            }
        } env;
        for (size_t i = 4; i < a.size(); ++i) {
            const size_t eq = a[i].find('=');
            const std::string k = a[i].substr(0, eq), v = a[i].substr(eq + 1);
            if (k == "router") env.router = v;
            else if (k == "map") env.map = v;
            else if (k == "local") env.local = v == "1";
            else if (k == "answers") env.answers = v == "1";
            else if (k == "recent") env.recent = v == "1";
            else if (k == "loops") env.loops = std::atoi(v.c_str());
            else if (k == "loops0") env.loops0 = std::atoi(v.c_str());
        }
        const uint32_t hr = static_cast<uint32_t>(std::stoul(a[1], nullptr, 16));
        const Decision d = Resolve(hr, static_cast<uint32_t>(std::stoul(a[2])), QueryOf(a[3]), env);
        return (d.translate ? "1 " + FormatIPv4(d.ip) + ":" + std::to_string(d.port) : std::string("0 -")) + " " +
               WhyName(d.why) + " | " + env.log;
    }
    return "?";
}

int main()
{
    std::string line;
    while (std::getline(std::cin, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (line.empty()) continue;
        std::cout << Run(Split(line, '\t')) << "\n";
    }
    return 0;
}
