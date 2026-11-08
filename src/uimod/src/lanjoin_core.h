// lanjoin_core.h -- the pure logic of the DirectPlay LAN-join fix (lanjoin.cpp), header-only so the C++ test
// harness (work\tests\test_lanjoin_core.py) checks it without the game.
//
// The bug (diagnosed 2026-11-07, memory project_smac_directplay_lan_upnp_hairpin): Windows' DirectPlay TCP/IP
// provider (dpwsockx.dll) asks the router over UPnP for a port mapping and advertises the router's PUBLIC address.
// Before it answers or connects to such an address it asks its NAT helper (dpnathlp.dll, IDirectPlayNATHelp::
// QueryAddress) whether that public address is really a machine behind the same router -- but the helper only
// recognises mappings that belong to its OWN machine, so for a second PC on the LAN it says "no mapping" and the
// packet goes to the public address, which a router without NAT loopback drops: "Game Not Found".
//
// The fix completes that one answer, and only where the public path is shown to be broken at that moment
// (Resolve): the helper said "no mapping" / "no server"; the address is this router's public address; the router
// maps that port to a machine on one of this PC's own subnets; that machine's game ANSWERS on its private address;
// and the same connection through the router's public address does NOT (no NAT loopback).  Then QueryAddress
// returns the private address -- what the helper does for this machine's own mappings.  On a router that loops
// back, and for every other address, nothing changes: wherever this translates, two PCs at home cannot play today.
#pragma once

#include <cstdint>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

namespace lanjoin {

// IDirectPlayNATHelp results (dpnathlp.h: MAKE_HRESULT(1, 0x015, 0xF000 + code)); measured on Windows 11 26100:
// QueryAddress of another LAN machine's mapping -> NOMAPPING, from an address with no gateway -> SERVERNOTAVAILABLE.
constexpr uint32_t kHrOk = 0;
constexpr uint32_t kHrNoMapping = 0x8015F050;
constexpr uint32_t kHrServerNotAvailable = 0x8015F0A0;
constexpr uint32_t kQueryTcp = 0x01;          // DPNHQUERYADDRESS_TCP
constexpr uint16_t kEnumPort = 47624;         // DirectPlay's server port (dpwsockx DPWS_GetEnumPort): dpwsockx turns an
                                              // S_OK for an enum target into a BROADCAST (0x5df0952f) -- never touched
constexpr int kSockaddrSize = 16;             // sizeof(SOCKADDR_IN)
constexpr size_t kMaxDocument = 65536;        // a router's description / SOAP answer, bytes

// ---------------------------------------------------------------------------------------------- IPv4 / sockaddr
struct V4 {                                   // ip in host order ("a.b.c.d" = a << 24 | ...), port in host order
    uint32_t ip = 0;
    uint16_t port = 0;
    bool ok = false;
};

inline V4 ParseSockaddr(const unsigned char* sa, int size)
{
    V4 v;
    if (!sa || size < kSockaddrSize) return v;
    if (sa[0] != 2 || sa[1] != 0) return v;   // AF_INET, little-endian u16
    v.port = static_cast<uint16_t>(sa[2] << 8 | sa[3]);
    v.ip = static_cast<uint32_t>(sa[4]) << 24 | static_cast<uint32_t>(sa[5]) << 16 | static_cast<uint32_t>(sa[6]) << 8 | sa[7];
    v.ok = true;
    return v;
}

inline void WriteSockaddr(unsigned char* sa, uint32_t ip, uint16_t port)
{
    std::memset(sa, 0, kSockaddrSize);
    sa[0] = 2;
    sa[2] = static_cast<unsigned char>(port >> 8);
    sa[3] = static_cast<unsigned char>(port);
    sa[4] = static_cast<unsigned char>(ip >> 24);
    sa[5] = static_cast<unsigned char>(ip >> 16);
    sa[6] = static_cast<unsigned char>(ip >> 8);
    sa[7] = static_cast<unsigned char>(ip);
}

inline bool ParseIPv4(const std::string& s, uint32_t* out)
{
    uint32_t ip = 0;
    int parts = 0;
    size_t i = 0;
    while (parts < 4) {
        if (i >= s.size() || s[i] < '0' || s[i] > '9') return false;
        uint32_t v = 0;
        int digits = 0;
        while (i < s.size() && s[i] >= '0' && s[i] <= '9') {
            v = v * 10 + static_cast<uint32_t>(s[i] - '0');
            if (++digits > 3 || v > 255) return false;
            ++i;
        }
        ip = ip << 8 | v;
        if (++parts < 4) {
            if (i >= s.size() || s[i] != '.') return false;
            ++i;
        }
    }
    if (i != s.size()) return false;
    *out = ip;
    return true;
}

inline std::string FormatIPv4(uint32_t ip)
{
    return std::to_string(ip >> 24) + "." + std::to_string(ip >> 16 & 255) + "." + std::to_string(ip >> 8 & 255) + "." +
           std::to_string(ip & 255);
}

// A LAN address: RFC 1918 private, loopback or link-local.  Nothing outside these ranges identifies only a
// machine on the player's own network.
inline bool IsLanAddress(uint32_t ip)
{
    return (ip >> 24) == 10 || (ip >> 20) == 0xAC1 || (ip >> 16) == 0xC0A8 || (ip >> 24) == 127 ||
           (ip >> 16) == 0xA9FE;
}

// An address as uimod.log may show it.  Players attach that log to public bug reports, so a LAN address is
// written as is and any other address (the player's own public address, an internet opponent's, a carrier-grade
// NAT or VPN address) never is.
inline std::string LogIPv4(uint32_t ip, const char* publicName = "<public>")
{
    return IsLanAddress(ip) ? FormatIPv4(ip) : std::string(publicName);
}

struct Subnet {
    uint32_t ip = 0;                          // this PC's address on the subnet
    uint8_t prefix = 0;                       // on-link prefix length
};

inline uint32_t PrefixMask(uint8_t prefix)
{
    return prefix == 0 ? 0u : prefix >= 32 ? 0xFFFFFFFFu : 0xFFFFFFFFu << (32 - prefix);
}

// x is on one of this PC's own directly attached IPv4 subnets (never a /0 "subnet": a route, not a link).
inline bool OnLocalSubnet(uint32_t x, const std::vector<Subnet>& subnets)
{
    for (const Subnet& s : subnets) {
        if (s.prefix == 0 || s.prefix > 32) continue;
        const uint32_t m = PrefixMask(s.prefix);
        if ((x & m) == (s.ip & m)) return true;
    }
    return false;
}

// ---------------------------------------------------------------------------------------------- text helpers
inline char Lower(char c) { return c >= 'A' && c <= 'Z' ? static_cast<char>(c - 'A' + 'a') : c; }

inline bool StartsWithNoCase(const std::string& s, size_t at, const char* p)
{
    for (size_t k = 0; p[k]; ++k)
        if (at + k >= s.size() || Lower(s[at + k]) != Lower(p[k])) return false;
    return true;
}

inline bool EqualsNoCase(const std::string& s, const char* p)
{
    return s.size() == std::strlen(p) && StartsWithNoCase(s, 0, p);
}

inline std::string Trim(const std::string& s)
{
    size_t a = 0, b = s.size();
    while (a < b && (s[a] == ' ' || s[a] == '\t' || s[a] == '\r' || s[a] == '\n')) ++a;
    while (b > a && (s[b - 1] == ' ' || s[b - 1] == '\t' || s[b - 1] == '\r' || s[b - 1] == '\n')) --b;
    return s.substr(a, b - a);
}

// The value of HTTP/SSDP header `name` (case-insensitive, at a line start), trimmed; "" when absent.
inline std::string HeaderValue(const std::string& msg, const char* name)
{
    const size_t n = std::strlen(name);
    size_t line = 0;
    while (line < msg.size()) {
        size_t end = msg.find('\n', line);
        if (end == std::string::npos) end = msg.size();
        if (StartsWithNoCase(msg, line, name) && line + n < msg.size() && msg[line + n] == ':')
            return Trim(msg.substr(line + n + 1, end - line - n - 1));
        line = end + 1;
    }
    return std::string();
}

// Skips a comment / CDATA / processing instruction / declaration at xml[i] == '<'; the index after it, or i.
inline size_t SkipXmlSpecial(const std::string& xml, size_t i)
{
    struct Span { const char* open; const char* close; };
    static const Span kSpans[] = {{"<!--", "-->"}, {"<![CDATA[", "]]>"}, {"<?", "?>"}, {"<!", ">"}};
    for (const Span& s : kSpans) {
        if (xml.compare(i, std::strlen(s.open), s.open) != 0) continue;
        const size_t e = xml.find(s.close, i + std::strlen(s.open));
        return e == std::string::npos ? xml.size() : e + std::strlen(s.close);
    }
    return i;
}

// The text of the first element named `tag` (any namespace prefix) whose start tag lies in [from, limit), skipping
// comments / CDATA / declarations; "" when absent.  `endOut` = the index after its end tag.  Linear in the input.
inline std::string XmlValue(const std::string& xml, const char* tag, size_t from = 0, size_t* endOut = nullptr,
                            size_t limit = std::string::npos)
{
    const std::string t(tag);
    if (limit > xml.size()) limit = xml.size();
    size_t i = from;
    while (i < limit && (i = xml.find('<', i)) != std::string::npos && i < limit) {
        const size_t skipped = SkipXmlSpecial(xml, i);
        if (skipped != i) { i = skipped; continue; }
        const size_t nameStart = i + 1;
        if (nameStart < xml.size() && xml[nameStart] == '/') { ++i; continue; }
        size_t nameEnd = nameStart;
        while (nameEnd < xml.size() && xml[nameEnd] != '>' && xml[nameEnd] != ' ' && xml[nameEnd] != '/' && xml[nameEnd] != '\t' &&
               xml[nameEnd] != '\r' && xml[nameEnd] != '\n')
            ++nameEnd;
        const std::string name = xml.substr(nameStart, nameEnd - nameStart);
        const size_t colon = name.find(':');
        const std::string local = colon == std::string::npos ? name : name.substr(colon + 1);
        const size_t close = xml.find('>', nameEnd);
        if (close == std::string::npos) return std::string();
        if (local == t && xml[close - 1] != '/') {
            const std::string endTag = "</" + name + ">";
            const size_t e = xml.find(endTag, close + 1);
            if (e == std::string::npos) return std::string();
            if (endOut) *endOut = e + endTag.size();
            return Trim(xml.substr(close + 1, e - close - 1));
        }
        i = close + 1;
    }
    return std::string();
}

// The index of the end tag `</tag>` or `</ns:tag>` at or after `from` (the '<'); npos when absent.
inline size_t FindEndTag(const std::string& xml, const char* tag, size_t from)
{
    const std::string want = std::string(tag) + ">";
    for (size_t i = xml.find("</", from); i != std::string::npos; i = xml.find("</", i + 2)) {
        size_t n = i + 2;
        const size_t gt = xml.find('>', n);
        if (gt == std::string::npos) return std::string::npos;
        const std::string name = xml.substr(n, gt - n);
        const size_t colon = name.find(':');
        if ((colon == std::string::npos ? name : name.substr(colon + 1)) + ">" == want) return i;
    }
    return std::string::npos;
}

// ---------------------------------------------------------------------------------------------- URLs
struct Url {
    std::string host;                         // a dotted IPv4 address (routers announce numeric LOCATIONs)
    uint32_t ip = 0;
    uint16_t port = 80;
    std::string path = "/";
    bool ok = false;
};

// http://a.b.c.d[:port][/path] only: no names, no user info, no IPv6, and nothing in the path that could end the
// request line (control characters, spaces) -- the path goes verbatim into an HTTP request.
inline Url ParseHttpUrl(const std::string& s)
{
    Url u;
    if (!StartsWithNoCase(s, 0, "http://") || s.size() > 512) return u;
    for (char c : s)
        if (static_cast<unsigned char>(c) <= ' ' || c == 0x7F) return u;
    const size_t hostStart = 7;
    const size_t slash = s.find('/', hostStart);
    std::string hostport = s.substr(hostStart, slash == std::string::npos ? std::string::npos : slash - hostStart);
    const size_t colon = hostport.find(':');
    if (colon != std::string::npos) {
        const std::string p = hostport.substr(colon + 1);
        if (p.empty() || p.size() > 5) return u;
        uint32_t v = 0;
        for (char c : p) {
            if (c < '0' || c > '9') return u;
            v = v * 10 + static_cast<uint32_t>(c - '0');
        }
        if (v == 0 || v > 65535) return u;
        u.port = static_cast<uint16_t>(v);
        hostport = hostport.substr(0, colon);
    }
    if (!ParseIPv4(hostport, &u.ip)) return u;
    u.host = hostport;
    u.path = slash == std::string::npos ? "/" : s.substr(slash);
    u.ok = true;
    return u;
}

// A controlURL resolved against <URLBase> (when present) or the description's LOCATION.
inline std::string ResolveUrl(const std::string& location, const std::string& urlBase, const std::string& ref)
{
    if (StartsWithNoCase(ref, 0, "http://")) return ref;
    const Url base = ParseHttpUrl(urlBase.empty() ? location : urlBase);
    if (!base.ok) return std::string();
    const std::string origin = "http://" + base.host + ":" + std::to_string(base.port);
    if (!ref.empty() && ref[0] == '/') return origin + ref;
    std::string dir = base.path;
    const size_t last = dir.rfind('/');
    dir = last == std::string::npos ? "/" : dir.substr(0, last + 1);
    return origin + dir + ref;
}

// The router is one of this PC's gateways, and the description and its control URL live on that same address.
inline bool TrustedRouterUrls(const Url& location, const Url& control, const std::vector<uint32_t>& gateways)
{
    if (!location.ok || !control.ok || location.ip != control.ip) return false;
    for (uint32_t g : gateways)
        if (g == location.ip) return true;
    return false;
}

// ---------------------------------------------------------------------------------------------- UPnP IGD
struct Service {
    std::string type;                         // urn:schemas-upnp-org:service:WANIPConnection:1 / :2 / WANPPPConnection:1
    std::string control;                      // controlURL as written in the description
    bool ok = false;
};

// The first WANIPConnection (any version) or WANPPPConnection service in an IGD description; each <service> block is
// read once (its serviceType and controlURL only within that block).
inline Service FindWanService(const std::string& xml)
{
    Service best;
    size_t at = 0;
    for (;;) {
        size_t typeEnd = 0;
        const std::string type = XmlValue(xml, "serviceType", at, &typeEnd);
        if (type.empty()) break;
        const size_t blockEnd = FindEndTag(xml, "service", typeEnd);
        if (blockEnd == std::string::npos) break;
        const std::string control = XmlValue(xml, "controlURL", typeEnd, nullptr, blockEnd);
        const bool wanIp = type.rfind("urn:schemas-upnp-org:service:WANIPConnection:", 0) == 0;
        const bool wanPpp = type.rfind("urn:schemas-upnp-org:service:WANPPPConnection:", 0) == 0;
        if ((wanIp || wanPpp) && !control.empty() && !(best.ok && !wanIp)) {
            best.type = type;
            best.control = control;
            best.ok = true;
            if (wanIp) return best;           // prefer IP over PPP; keep looking only after a PPP hit
        }
        at = blockEnd + 2;
    }
    return best;
}

inline std::string SoapEnvelope(const std::string& serviceType, const char* action,
                                const std::vector<std::pair<std::string, std::string>>& args)
{
    std::string s = "<?xml version=\"1.0\"?>\r\n<s:Envelope xmlns:s=\"http://schemas.xmlsoap.org/soap/envelope/\" "
                    "s:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\"><s:Body><u:";
    s += action;
    s += " xmlns:u=\"" + serviceType + "\">";
    for (const auto& a : args) s += "<" + a.first + ">" + a.second + "</" + a.first + ">";
    s += "</u:";
    s += action;
    s += "></s:Body></s:Envelope>\r\n";
    return s;
}

inline std::string HttpRequest(const char* method, const Url& u, const std::string& extraHeaders, const std::string& body)
{
    std::string r = std::string(method) + " " + u.path + " HTTP/1.0\r\nHost: " + u.host + ":" + std::to_string(u.port) +
                    "\r\nConnection: close\r\n" + extraHeaders;
    if (!body.empty() || std::strcmp(method, "POST") == 0) r += "Content-Length: " + std::to_string(body.size()) + "\r\n";
    r += "\r\n" + body;
    return r;
}

// "HTTP/1.x 200 ..." -> 200 (exactly three digits, then a space or the end); anything else -> 0.
inline int HttpStatus(const std::string& resp)
{
    if (!StartsWithNoCase(resp, 0, "HTTP/1.")) return 0;
    const size_t sp = resp.find(' ');
    if (sp == std::string::npos || sp + 4 > resp.size()) return 0;
    int v = 0;
    for (size_t i = sp + 1; i < sp + 4; ++i) {
        if (resp[i] < '0' || resp[i] > '9') return 0;
        v = v * 10 + (resp[i] - '0');
    }
    if (sp + 4 < resp.size() && resp[sp + 4] != ' ' && resp[sp + 4] != '\r' && resp[sp + 4] != '\n') return 0;
    return v;
}

inline std::string HttpBody(const std::string& resp)
{
    const size_t e = resp.find("\r\n\r\n");
    return e == std::string::npos ? std::string() : resp.substr(e + 4);
}

// A response is complete once its headers and Content-Length bytes are in (when it gives one).
inline bool HttpComplete(const std::string& resp)
{
    const size_t e = resp.find("\r\n\r\n");
    if (e == std::string::npos) return false;
    const std::string len = HeaderValue(resp.substr(0, e), "Content-Length");
    if (len.empty() || len.size() > 9) return false;
    size_t n = 0;
    for (char c : len) {
        if (c < '0' || c > '9') return false;
        n = n * 10 + static_cast<size_t>(c - '0');
    }
    return resp.size() - (e + 4) >= n;
}

struct Mapping {                              // GetSpecificPortMappingEntry's answer
    uint32_t internalClient = 0;
    uint16_t internalPort = 0;
    bool enabled = false;
    bool ok = false;
};

inline Mapping ParseMappingResponse(const std::string& body)
{
    Mapping m;
    uint32_t ip = 0;
    const std::string client = XmlValue(body, "NewInternalClient");
    const std::string port = XmlValue(body, "NewInternalPort");
    const std::string enabled = XmlValue(body, "NewEnabled");
    if (!ParseIPv4(client, &ip) || port.empty() || port.size() > 5) return m;
    uint32_t p = 0;
    for (char c : port) {
        if (c < '0' || c > '9') return m;
        p = p * 10 + static_cast<uint32_t>(c - '0');
    }
    if (p == 0 || p > 65535) return m;
    m.internalClient = ip;
    m.internalPort = static_cast<uint16_t>(p);
    m.enabled = enabled.empty() || enabled == "1" || EqualsNoCase(enabled, "true") || EqualsNoCase(enabled, "yes");
    m.ok = true;
    return m;
}

// ---------------------------------------------------------------------------------------------- the decision
enum class Why {
    Translated,             // the private address is returned
    NotOurCase,             // the helper's own result stands: not NOMAPPING / SERVERNOTAVAILABLE, or a malformed query
    EnumPort,               // DirectPlay's server port: dpwsockx turns that answer into a broadcast -- never touched
    NoRouter,               // no UPnP router (or its public address) known in time
    NotRouterAddress,       // the query is not this router's public address
    NoMapping,              // the router has no (enabled) mapping for that port
    NotLocal,               // the mapping's machine is not on one of this PC's own subnets
    Unreachable,            // the machine's game did not answer on its private address
    LoopsBack,              // the router delivers the public path itself: today's behaviour works, nothing to fix
    LoopbackUnknown,        // not shown that the public path fails (a datagram query with no earlier stream test)
};

inline const char* WhyName(Why w)
{
    switch (w) {
    case Why::Translated: return "translated";
    case Why::NotOurCase: return "not-our-case";
    case Why::EnumPort: return "enum-port";
    case Why::NoRouter: return "no-router";
    case Why::NotRouterAddress: return "not-router-address";
    case Why::NoMapping: return "no-mapping";
    case Why::NotLocal: return "not-local";
    case Why::Unreachable: return "unreachable";
    case Why::LoopsBack: return "router-loops-back";
    case Why::LoopbackUnknown: return "loopback-unknown";
    }
    return "?";
}

struct Decision {
    bool translate = false;
    uint32_t ip = 0;
    uint16_t port = 0;
    Why why = Why::NotOurCase;
};

inline bool IsOurCase(uint32_t hr)
{
    return hr == kHrNoMapping || hr == kHrServerNotAvailable;
}

// What Resolve needs from the world (lanjoin.cpp: UPnP, sockets and caches, all within one deadline; the tests: a
// scripted fake).  Every method may answer "don't know" as false / -1.
struct Env {
    virtual ~Env() = default;
    virtual bool RouterExternal(uint32_t* external) = 0;          // this router's public address, if known in time
    virtual Mapping LookUp(uint16_t externalPort, bool tcp) = 0;  // the router's mapping for that port
    virtual bool IsLocal(uint32_t ip) = 0;                        // on one of this PC's subnets
    virtual bool Answers(uint32_t ip, uint16_t port) = 0;         // a TCP connect to ip:port is accepted, now
    virtual bool AnsweredRecently(uint32_t ip) = 0;               // Answers() was true for ip lately (datagram queries)
    // Does the router loop back to the machine privateIp?  1 yes, 0 no, -1 unknown.  `tcpPort` = the public TCP port
    // the router maps to privateIp:privatePort (0: a datagram query -- only a verdict measured earlier for privateIp
    // can answer).  0 may be answered only from a measurement in which privateIp:privatePort ACCEPTED and the same
    // connection through external:tcpPort did not.
    virtual int LoopsBack(uint32_t external, uint16_t tcpPort, uint32_t privateIp, uint16_t privatePort) = 0;
};

// Every gate, in order; each world question is asked only once the gates before it passed.
inline Decision Resolve(uint32_t hr, uint32_t flags, const V4& query, Env& env)
{
    Decision d;
    const bool tcp = (flags & kQueryTcp) != 0;
    if (!IsOurCase(hr) || !query.ok || query.port == 0 || query.ip == 0) { d.why = Why::NotOurCase; return d; }
    if (query.port == kEnumPort) { d.why = Why::EnumPort; return d; }
    uint32_t external = 0;
    if (!env.RouterExternal(&external) || external == 0) { d.why = Why::NoRouter; return d; }
    if (query.ip != external) { d.why = Why::NotRouterAddress; return d; }
    const Mapping m = env.LookUp(query.port, tcp);
    if (!m.ok || !m.enabled || m.internalClient == 0 || m.internalPort == 0) { d.why = Why::NoMapping; return d; }
    if (!env.IsLocal(m.internalClient)) { d.why = Why::NotLocal; return d; }
    const bool answers = tcp ? env.Answers(m.internalClient, m.internalPort) : env.AnsweredRecently(m.internalClient);
    if (!answers) { d.why = Why::Unreachable; return d; }
    const int loops = env.LoopsBack(external, tcp ? query.port : static_cast<uint16_t>(0), m.internalClient, m.internalPort);
    if (loops == 1) { d.why = Why::LoopsBack; return d; }
    if (loops != 0) { d.why = Why::LoopbackUnknown; return d; }
    d.translate = true;
    d.ip = m.internalClient;
    d.port = m.internalPort;
    d.why = Why::Translated;
    return d;
}

} // namespace lanjoin
