// lanjoin.cpp -- DirectPlay LAN join behind a router without NAT loopback (Windows' bug, diagnosed 2026-11-07).
//
// Windows' DirectPlay TCP/IP provider (dpwsockx.dll) puts the router's PUBLIC address (UPnP) into what it sends, and
// before answering or connecting to such an address asks its NAT helper whether the address is really a machine
// behind the same router: IDirectPlayNATHelp::QueryAddress (dpnathlp.dll, vtable slot 9).  The helper only
// recognises its own machine's mappings: for a second PC it answers NOMAPPING, the reply goes to the public address,
// and a router without NAT loopback drops it -> "Game Not Found".
//
// This module completes that one answer where -- and only where -- the public path is shown to fail at that moment
// (lanjoin_core.h Resolve: our case, not DirectPlay's server port, the router's own public address, a mapping to a
// machine on this PC's subnets whose game answers on its private address, and the same connection through the
// public address failing).  Wherever it translates, two PCs at home cannot play today, so nothing that works today
// can change; on a router that loops back, and for every other address, the helper's own answer stands.
//
// Hook chain (no game code is patched): dplayx.dll's IAT LoadLibraryA/W -> when dpwsockx.dll loads, its IAT
// GetProcAddress -> "DirectPlayNATHelpCreate" -> our create wrapper -> the helper object's vtable slot 9, in place
// (the vtable lives in dpnathlp's .text; a copied vtable would trip the helper's own object checks).
//
// Time: QueryAddress runs on DirectPlay's threads and on the game thread (the first Send to each player), so the
// router is discovered on a worker thread started when the helper is created, every query has one deadline
// (kQueryBudgetMs, all network I/O inside it), and queries the helper answers itself never wait for any of this.
#include <winsock2.h>
#include <ws2tcpip.h>
#include <iphlpapi.h>
#include <windows.h>

#include <algorithm>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "lanjoin.h"
#include "lanjoin_core.h"

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "iphlpapi.lib")

void UimodLog(const char* msg);              // init.cpp

namespace {

using namespace lanjoin;

// ---------------------------------------------------------------------------------------------- time
constexpr DWORD kQueryBudgetMs = 1500;        // everything one QueryAddress may add
constexpr DWORD kSsdpWaitMs = 1000;           // M-SEARCH answers (worker thread)
constexpr DWORD kDiscoveryBudgetMs = 4000;    // a whole discovery (worker thread)
constexpr DWORD kHttpMs = 800;                // one router exchange, total
constexpr DWORD kAnswerMs = 300;              // the LAN machine's game, on its private address
constexpr DWORD kLoopMs = 500;                // the same connection through the public address
constexpr DWORD kRouterRetryMs = 60000;       // after a failed discovery
constexpr DWORD kExternalTtlMs = 300000;      // re-read the router's public address after this (worker thread)
constexpr DWORD kMappingTtlMs = 60000;        // a looked-up mapping
constexpr DWORD kMappingMissTtlMs = 5000;     // a missing mapping
constexpr DWORD kAnswerTtlMs = 120000;        // a machine whose game answered
constexpr DWORD kAnswerMissTtlMs = 3000;      // one that did not (its game may not be listening yet: Try Again)
constexpr DWORD kLoopTtlMs = 600000;          // "the router loops back" for a peer
constexpr DWORD kNoLoopTtlMs = 60000;         // "the router does not loop back" for a peer (measured, never inferred)
constexpr DWORD kSubnetTtlMs = 30000;         // this PC's subnets and gateways
constexpr size_t kMaxLocations = 4;

using FNatCreate = HRESULT(WINAPI*)(const GUID*, void**);
using FQueryAddress = HRESULT(WINAPI*)(void*, const SOCKADDR*, const SOCKADDR*, SOCKADDR*, int, DWORD);

bool g_on = false;
void* volatile g_origLoadA = nullptr;         // what each IAT slot held before we wrote it (another hook, an AppCompat
void* volatile g_origLoadW = nullptr;         // shim, or kernel32): stored BEFORE the slot is written, so a hook
void* volatile g_origGpa = nullptr;           // never runs with it empty
void* volatile g_realCreate = nullptr;

// Patched vtables: an entry's `original` is written before its vtable slot is, and entries are never reused, so
// QueryAddressHook reads them without a lock.
struct VtSlot {
    void** volatile vtable;
    FQueryAddress volatile original;
};
VtSlot g_slots[16] = {};
CRITICAL_SECTION g_patchLock;                 // PatchVtable

CRITICAL_SECTION g_lock;                      // everything below (never held across network I/O)
struct Router {
    bool known = false;
    std::string controlUrl;
    std::string serviceType;
    uint32_t external = 0;
    DWORD at = 0;                             // when `external` was read
    DWORD failedAt = 0;
    bool failed = false;
};
HANDLE g_discoveryDone = nullptr;             // manual-reset: set while no discovery is running
bool g_discovering = false;
bool g_firstDiscovery = false;                // set only when creating the helper STARTED a discovery: queries wait
                                              // for that one; every later retry / refresh runs in the background
unsigned g_generation = 0;                    // bumped when the router changes; a query's late writes from an older
                                              // generation are dropped

struct Timed {
    Mapping m;
    DWORD at = 0;
};
// Everything with a destructor lives in one heap object that is never freed: at ExitProcess the CRT would otherwise
// destroy these after the discovery thread was killed, possibly in the middle of changing one of them.
struct Shared {
    Router router;
    std::map<uint32_t, Timed> mappings;                  // key: port << 1 | tcp
    std::map<uint64_t, std::pair<bool, DWORD>> answers;  // key: ip << 16 | port (a machine's game, on that port)
    std::map<uint64_t, std::pair<int, DWORD>> loops;     // key: public address << 32 | the peer's private address
    std::vector<Subnet> subnets;
    std::vector<uint32_t> gateways;
    std::set<std::string> logged;
};
Shared* const g_shared = new Shared;
Router& g_router = g_shared->router;
std::map<uint32_t, Timed>& g_mappings = g_shared->mappings;
std::map<uint64_t, std::pair<bool, DWORD>>& g_answers = g_shared->answers;
std::map<uint64_t, std::pair<int, DWORD>>& g_loops = g_shared->loops;
std::vector<Subnet>& g_subnets = g_shared->subnets;
std::vector<uint32_t>& g_gateways = g_shared->gateways;
DWORD g_subnetsAt = 0;
bool g_subnetsKnown = false;
std::set<std::string>& g_logged = g_shared->logged;

void Log(const std::string& s)
{
    UimodLog(("[lanjoin] " + s + "\n").c_str());
}

bool Fresh(DWORD at, DWORD ttl) { return GetTickCount() - at < ttl; }

DWORD Left(DWORD deadline)
{
    const DWORD now = GetTickCount();
    return static_cast<int>(deadline - now) > 0 ? deadline - now : 0;
}

struct Lock {
    explicit Lock(CRITICAL_SECTION& c) : cs(c) { EnterCriticalSection(&cs); }
    ~Lock() { LeaveCriticalSection(&cs); }
    CRITICAL_SECTION& cs;
};

// ---------------------------------------------------------------------------------------------- this PC
void ReadAdapters(std::vector<Subnet>* subnets, std::vector<uint32_t>* gateways)
{
    ULONG size = 16384;
    std::vector<unsigned char> buf;
    ULONG rc = ERROR_BUFFER_OVERFLOW;
    for (int tries = 0; tries < 3 && rc == ERROR_BUFFER_OVERFLOW; ++tries) {
        buf.assign(size, 0);
        rc = GetAdaptersAddresses(AF_INET, GAA_FLAG_INCLUDE_GATEWAYS | GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST |
                                               GAA_FLAG_SKIP_DNS_SERVER,
                                  nullptr, reinterpret_cast<IP_ADAPTER_ADDRESSES*>(buf.data()), &size);
    }
    if (rc != NO_ERROR) return;
    for (auto* a = reinterpret_cast<IP_ADAPTER_ADDRESSES*>(buf.data()); a; a = a->Next) {
        if (a->OperStatus != IfOperStatusUp || a->IfType == IF_TYPE_SOFTWARE_LOOPBACK) continue;
        for (auto* u = a->FirstUnicastAddress; u; u = u->Next) {
            if (!u->Address.lpSockaddr || u->Address.lpSockaddr->sa_family != AF_INET) continue;
            Subnet s;
            s.ip = ntohl(reinterpret_cast<const sockaddr_in*>(u->Address.lpSockaddr)->sin_addr.s_addr);
            s.prefix = u->OnLinkPrefixLength;
            if (s.ip != 0 && (s.ip >> 24) != 127) subnets->push_back(s);
        }
        for (auto* g = a->FirstGatewayAddress; g; g = g->Next) {
            if (!g->Address.lpSockaddr || g->Address.lpSockaddr->sa_family != AF_INET) continue;
            const uint32_t ip = ntohl(reinterpret_cast<const sockaddr_in*>(g->Address.lpSockaddr)->sin_addr.s_addr);
            bool seen = false;                // one router on two adapters (Ethernet + Wi-Fi) is one gateway
            for (uint32_t x : *gateways) seen = seen || x == ip;
            if (ip != 0 && !seen) gateways->push_back(ip);
        }
    }
}

// This PC's subnets / gateways (cached; the adapter read happens outside the lock).
void Adapters(std::vector<Subnet>* subnets, std::vector<uint32_t>* gateways)
{
    {
        Lock l(g_lock);
        if (g_subnetsKnown && Fresh(g_subnetsAt, kSubnetTtlMs)) {
            if (subnets) *subnets = g_subnets;
            if (gateways) *gateways = g_gateways;
            return;
        }
    }
    std::vector<Subnet> s;
    std::vector<uint32_t> g;
    ReadAdapters(&s, &g);
    Lock l(g_lock);
    g_subnets = s;
    g_gateways = g;
    g_subnetsAt = GetTickCount();
    g_subnetsKnown = true;
    if (subnets) *subnets = s;
    if (gateways) *gateways = g;
}

// ---------------------------------------------------------------------------------------------- sockets
sockaddr_in V4Addr(uint32_t ip, uint16_t port)
{
    sockaddr_in a = {};
    a.sin_family = AF_INET;
    a.sin_port = htons(port);
    a.sin_addr.s_addr = htonl(ip);
    return a;
}

// A TCP connect bounded by `ms`: 1 accepted; 0 the network did not deliver it (no answer within `ms`, refused, or
// the host / network unreachable); -1 THIS PC could not try (no socket, no port, an outbound block, a select error).
// Windows retries a refused SYN for about two seconds, so a closed port normally reads as "no answer" (0).
int ConnectWithin(SOCKET s, const sockaddr_in& to, DWORD ms)
{
    u_long nb = 1;
    if (ioctlsocket(s, FIONBIO, &nb) != 0) return -1;
    if (connect(s, reinterpret_cast<const sockaddr*>(&to), sizeof to) == 0) return 1;
    const int now = WSAGetLastError();
    if (now != WSAEWOULDBLOCK) return now == WSAECONNREFUSED || now == WSAEHOSTUNREACH || now == WSAENETUNREACH ? 0 : -1;
    fd_set w, e;
    FD_ZERO(&w);
    FD_ZERO(&e);
    FD_SET(s, &w);
    FD_SET(s, &e);
    timeval tv = {static_cast<long>(ms / 1000), static_cast<long>(ms % 1000) * 1000};
    const int n = select(0, nullptr, &w, &e, &tv);
    if (n == 0) return 0;                     // no answer within ms
    if (n < 0) return -1;
    if (FD_ISSET(s, &w)) return 1;
    int err = 0, len = sizeof err;
    getsockopt(s, SOL_SOCKET, SO_ERROR, reinterpret_cast<char*>(&err), &len);
    return err == WSAECONNREFUSED || err == WSAEHOSTUNREACH || err == WSAENETUNREACH || err == WSAETIMEDOUT ? 0 : -1;
}

// ConnectWithin on a fresh socket (closed gracefully: the peer's DirectPlay sees an ordinary empty connection).
int Connect3(uint32_t ip, uint16_t port, DWORD ms)
{
    if (ms == 0) return -1;
    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET) return -1;
    const int r = ConnectWithin(s, V4Addr(ip, port), ms);
    closesocket(s);
    return r;
}

bool Accepts(uint32_t ip, uint16_t port, DWORD ms) { return Connect3(ip, port, ms) == 1; }

// One HTTP/1.0 exchange with a numeric host, everything inside `ms`; at most kMaxDocument bytes; stops at
// Content-Length.
bool HttpExchange(const Url& u, const std::string& request, DWORD ms, std::string* response)
{
    if (!u.ok || ms == 0) return false;
    const DWORD deadline = GetTickCount() + ms;
    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET) return false;
    bool ok = false;
    if (ConnectWithin(s, V4Addr(u.ip, u.port), Left(deadline)) == 1) {
        size_t sent = 0;
        while (sent < request.size() && Left(deadline) > 0) {
            fd_set w;
            FD_ZERO(&w);
            FD_SET(s, &w);
            const DWORD l = Left(deadline);
            timeval tv = {static_cast<long>(l / 1000), static_cast<long>(l % 1000) * 1000};
            if (select(0, nullptr, &w, nullptr, &tv) <= 0) break;
            const int n = send(s, request.data() + sent, static_cast<int>(request.size() - sent), 0);
            if (n <= 0) break;
            sent += static_cast<size_t>(n);
        }
        std::string resp;
        if (sent == request.size()) {
            char chunk[4096];
            while (Left(deadline) > 0 && resp.size() <= kMaxDocument && !HttpComplete(resp)) {
                fd_set r;
                FD_ZERO(&r);
                FD_SET(s, &r);
                const DWORD l = Left(deadline);
                timeval tv = {static_cast<long>(l / 1000), static_cast<long>(l % 1000) * 1000};
                if (select(0, &r, nullptr, nullptr, &tv) <= 0) break;
                const int n = recv(s, chunk, sizeof chunk, 0);
                if (n <= 0) break;
                resp.append(chunk, static_cast<size_t>(n));
            }
            ok = !resp.empty() && resp.size() <= kMaxDocument;
            *response = resp;
        }
    }
    closesocket(s);
    return ok;
}

bool Soap(const Router& r, const char* action, const std::vector<std::pair<std::string, std::string>>& args, DWORD ms,
          std::string* body)
{
    const Url u = ParseHttpUrl(r.controlUrl);
    if (!u.ok) return false;
    const std::string env = SoapEnvelope(r.serviceType, action, args);
    const std::string headers = "Content-Type: text/xml; charset=\"utf-8\"\r\nSOAPAction: \"" + r.serviceType + "#" +
                                action + "\"\r\n";
    std::string resp;
    if (!HttpExchange(u, HttpRequest("POST", u, headers, env), ms, &resp) || HttpStatus(resp) != 200) return false;
    *body = HttpBody(resp);
    return true;
}

// ---------------------------------------------------------------------------------------------- discovery (worker)
// LOCATIONs announced by this PC's gateways only (a UPnP answer from any other LAN device is ignored), at most
// kMaxLocations; returns as soon as every gateway has answered.
std::vector<std::string> SsdpLocations(const std::vector<Subnet>& subnets, const std::vector<uint32_t>& gateways)
{
    std::vector<std::string> out;
    static const char kSearch[] = "M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 1\r\n"
                                  "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n";
    std::vector<SOCKET> socks;
    // one socket per local address: the multicast leaves by THAT interface (Tailscale and other virtual adapters
    // often have the lowest metric), plus a unicast copy to the gateway on it
    for (const Subnet& sn : subnets) {
        SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (s == INVALID_SOCKET) continue;
        sockaddr_in local = V4Addr(sn.ip, 0);
        if (bind(s, reinterpret_cast<sockaddr*>(&local), sizeof local) != 0) { closesocket(s); continue; }
        in_addr ifa = local.sin_addr;
        setsockopt(s, IPPROTO_IP, IP_MULTICAST_IF, reinterpret_cast<const char*>(&ifa), sizeof ifa);
        DWORD ttl = 2;
        setsockopt(s, IPPROTO_IP, IP_MULTICAST_TTL, reinterpret_cast<const char*>(&ttl), sizeof ttl);
        u_long nb = 1;
        ioctlsocket(s, FIONBIO, &nb);
        sockaddr_in mc = V4Addr(0xEFFFFFFAu, 1900);   // 239.255.255.250
        sendto(s, kSearch, static_cast<int>(sizeof kSearch - 1), 0, reinterpret_cast<sockaddr*>(&mc), sizeof mc);
        for (uint32_t gw : gateways) {
            const uint32_t m = PrefixMask(sn.prefix);
            if (sn.prefix == 0 || (gw & m) != (sn.ip & m)) continue;
            sockaddr_in to = V4Addr(gw, 1900);
            sendto(s, kSearch, static_cast<int>(sizeof kSearch - 1), 0, reinterpret_cast<sockaddr*>(&to), sizeof to);
        }
        socks.push_back(s);
    }
    std::set<uint32_t> answered;
    const DWORD deadline = GetTickCount() + kSsdpWaitMs;
    while (!socks.empty() && Left(deadline) > 0 && out.size() < kMaxLocations && answered.size() < gateways.size()) {
        fd_set r;
        FD_ZERO(&r);
        for (SOCKET s : socks) FD_SET(s, &r);
        const DWORD l = Left(deadline);
        timeval tv = {static_cast<long>(l / 1000), static_cast<long>(l % 1000) * 1000};
        if (select(0, &r, nullptr, nullptr, &tv) <= 0) break;
        for (SOCKET s : socks) {
            if (!FD_ISSET(s, &r)) continue;
            char buf[2048];
            sockaddr_in from = {};
            int fromLen = sizeof from;
            const int n = recvfrom(s, buf, sizeof buf, 0, reinterpret_cast<sockaddr*>(&from), &fromLen);
            if (n <= 0) continue;
            const uint32_t src = ntohl(from.sin_addr.s_addr);
            bool gateway = false;
            for (uint32_t g : gateways) gateway = gateway || g == src;
            if (!gateway) continue;
            const std::string loc = HeaderValue(std::string(buf, static_cast<size_t>(n)), "LOCATION");
            const Url u = ParseHttpUrl(loc);
            if (!u.ok || u.ip != src) continue;
            bool dup = false;
            for (const auto& o : out) dup = dup || o == loc;
            if (!dup && out.size() < kMaxLocations) out.push_back(loc);
            answered.insert(src);
        }
    }
    for (SOCKET s : socks) closesocket(s);
    return out;
}

bool ReadExternal(Router* r, DWORD ms)
{
    std::string body;
    uint32_t ip = 0;
    if (!Soap(*r, "GetExternalIPAddress", {}, ms, &body) || !ParseIPv4(XmlValue(body, "NewExternalIPAddress"), &ip) || ip == 0)
        return false;
    r->external = ip;
    r->at = GetTickCount();
    return true;
}

Router Discover()
{
    const DWORD deadline = GetTickCount() + kDiscoveryBudgetMs;
    std::vector<Subnet> subnets;
    std::vector<uint32_t> gateways;
    Adapters(&subnets, &gateways);
    Router r;
    for (const std::string& loc : SsdpLocations(subnets, gateways)) {
        const Url u = ParseHttpUrl(loc);
        std::string resp;
        if (!HttpExchange(u, HttpRequest("GET", u, "", ""), (std::min)(kHttpMs, Left(deadline)), &resp) ||
            HttpStatus(resp) != 200)
            continue;
        const std::string xml = HttpBody(resp);
        const Service svc = FindWanService(xml);
        if (!svc.ok) continue;
        r.controlUrl = ResolveUrl(loc, XmlValue(xml, "URLBase"), svc.control);
        r.serviceType = svc.type;
        if (!TrustedRouterUrls(u, ParseHttpUrl(r.controlUrl), gateways)) continue;
        if (!ReadExternal(&r, (std::min)(kHttpMs, Left(deadline)))) continue;
        r.known = true;
        // Address and port only: a router may put its device UUID in the LOCATION path, and uimod.log is public.
        Log("router " + (IsLanAddress(u.ip) ? FormatIPv4(u.ip) + ":" + std::to_string(u.port) : std::string("<non-LAN gateway>")) +
            " (" + svc.type +
            "), public address " +
            (IsLanAddress(r.external) ? FormatIPv4(r.external) : std::string("known (not logged)")));
        return r;
    }
    r = Router();
    r.failed = true;
    r.failedAt = GetTickCount();
    Log("no UPnP gateway answered; DirectPlay's own answers stand");
    return r;
}

void DiscoveryBody();

DWORD WINAPI DiscoveryThread(void*)
{
    try {
        DiscoveryBody();
    } catch (...) {                           // out of memory: give up quietly; DirectPlay's own answers stand
        try {
            Lock l(g_lock);
            g_discovering = false;
            g_firstDiscovery = false;
        } catch (...) {
        }
        SetEvent(g_discoveryDone);
    }
    return 0;
}

void DiscoveryBody()
{
    Router current;
    {
        Lock l(g_lock);
        current = g_router;
    }
    Router next;
    if (current.known) {                      // a refresh: the same gateway still trusted, then its public address
        next = current;
        std::vector<uint32_t> gateways;
        Adapters(nullptr, &gateways);
        const Url control = ParseHttpUrl(next.controlUrl);
        if (!TrustedRouterUrls(control, control, gateways) || !ReadExternal(&next, kHttpMs)) next = Discover();
    } else {
        next = Discover();
    }
    {
        Lock l(g_lock);
        const bool changed = !next.known || next.external != g_router.external || next.controlUrl != g_router.controlUrl;
        g_router = std::move(next);           // a move (noexcept): out of memory cannot leave the record half-copied
        g_discovering = false;
        g_firstDiscovery = false;
        if (changed) {                        // another router or address: nothing measured for the old one holds
            g_loops.clear();
            g_mappings.clear();
            g_answers.clear();
            ++g_generation;
        }
    }
    SetEvent(g_discoveryDone);
}

// Starts a discovery (or a refresh of the public address) if one is due and none is running; true when it started
// one.  `first`: this is the discovery a new DirectPlay session's first query may wait for.
bool KickDiscovery(bool first = false)
{
    Lock l(g_lock);
    if (g_discovering) return false;
    const bool due = g_router.known ? !Fresh(g_router.at, kExternalTtlMs)
                                    : !(g_router.failed && Fresh(g_router.failedAt, kRouterRetryMs));
    if (!due) return false;
    g_discovering = true;
    if (first && !g_router.known) g_firstDiscovery = true;
    ResetEvent(g_discoveryDone);
    HANDLE t = CreateThread(nullptr, 0, &DiscoveryThread, nullptr, 0, nullptr);
    if (t) {
        CloseHandle(t);
        return true;
    }
    g_discovering = false;
    g_firstDiscovery = false;
    SetEvent(g_discoveryDone);
    return false;
}

// ---------------------------------------------------------------------------------------------- the world (Env)
class LiveEnv : public Env {
public:
    explicit LiveEnv(DWORD deadline) : deadline_(deadline) {}

    bool RouterExternal(uint32_t* external) override
    {
        KickDiscovery();
        bool wait = false;
        {
            Lock l(g_lock);
            if (g_router.known) {             // a refresh may be running; the cached address serves meanwhile
                router_ = g_router;
                generation_ = g_generation;
                *external = g_router.external;
                return true;
            }
            wait = g_firstDiscovery && g_discovering;
        }
        if (!wait) return false;              // only the discovery started with the helper is waited for
        WaitForSingleObject(g_discoveryDone, Left(deadline_));
        Lock l(g_lock);
        if (!g_router.known) return false;
        router_ = g_router;
        generation_ = g_generation;
        *external = g_router.external;
        return true;
    }

    Mapping LookUp(uint16_t port, bool tcp) override
    {
        const uint32_t key = MappingKey(port, tcp);
        {
            Lock l(g_lock);
            auto it = g_mappings.find(key);
            if (it != g_mappings.end() && Fresh(it->second.at, it->second.m.ok ? kMappingTtlMs : kMappingMissTtlMs)) {
                liveMapping_ = ~0u;           // from the cache: not a measurement of now
                return it->second.m;
            }
        }
        return ReadMapping(port, tcp);
    }

    bool IsLocal(uint32_t ip) override
    {
        std::vector<Subnet> s;
        Adapters(&s, nullptr);
        return OnLocalSubnet(ip, s);
    }

    bool Answers(uint32_t ip, uint16_t port) override
    {
        {
            Lock l(g_lock);
            // a router already measured to loop back for this machine: Resolve stops at LoopsBack anyway (which
            // answers 1 from the same entry, or measures afresh), so the machine's game is not probed again
            auto lp = g_loops.find(LoopKey(router_.external, ip));
            if (lp != g_loops.end() && lp->second.first == 1 && Fresh(lp->second.second, kLoopTtlMs)) return true;
            auto it = g_answers.find(AnswerKey(ip, port));
            if (it != g_answers.end() && Fresh(it->second.second, it->second.first ? kAnswerTtlMs : kAnswerMissTtlMs))
                return it->second.first;
        }
        return Probe(ip, port);
    }

    // A datagram query cannot probe its own port (DirectPlay's datagram port has no TCP listener): it follows the
    // same machine's recent TCP answer, and below the verdict a TCP query measured for that machine.
    bool AnsweredRecently(uint32_t ip) override
    {
        Lock l(g_lock);
        for (const auto& a : g_answers)
            if ((a.first >> 16) == ip && a.second.first && Fresh(a.second.second, kAnswerTtlMs)) return true;
        return false;
    }

    int LoopsBack(uint32_t external, uint16_t tcpPort, uint32_t privateIp, uint16_t privatePort) override
    {
        const uint64_t key = LoopKey(external, privateIp);
        int cached = -1;
        {
            Lock l(g_lock);
            auto it = g_loops.find(key);
            if (it != g_loops.end() && Fresh(it->second.second, it->second.first == 1 ? kLoopTtlMs : kNoLoopTtlMs))
                cached = it->second.first;
        }
        if (cached == 1) return 1;            // loops back: the safe answer may come from the cache
        if (tcpPort == 0) return cached;      // a datagram query: only what a TCP query measured for this machine
        // A TCP query concludes "does not loop back" only from three measurements made NOW, none from a cache:
        // the router's mapping read live, privateIp:privatePort accepting, and the same connection through
        // external:tcpPort failing.
        if (liveMapping_ != MappingKey(tcpPort, true)) {
            const Mapping m = ReadMapping(tcpPort, true);
            if (!m.ok || !m.enabled || m.internalClient != privateIp || m.internalPort != privatePort) return -1;
        }
        if (!(probed_ == AnswerKey(privateIp, privatePort) && probedOk_)) {
            if (Left(deadline_) < kAnswerMs + kLoopMs || !Probe(privateIp, privatePort)) return -1;
        }
        const DWORD ms = (std::min)(kLoopMs, Left(deadline_));
        if (ms < kLoopMs) return -1;          // not enough time left to tell a dropped path from a slow one
        const int verdict = Connect3(external, tcpPort, ms);   // -1: this PC could not try -- nothing measured
        if (verdict < 0) return -1;
        Lock l(g_lock);
        if (generation_ == g_generation) g_loops[key] = {verdict, GetTickCount()};
        return verdict;
    }

private:
    static uint64_t AnswerKey(uint32_t ip, uint16_t port) { return static_cast<uint64_t>(ip) << 16 | port; }
    static uint64_t LoopKey(uint32_t external, uint32_t ip) { return static_cast<uint64_t>(external) << 32 | ip; }
    static uint32_t MappingKey(uint16_t port, bool tcp) { return static_cast<uint32_t>(port) << 1 | (tcp ? 1u : 0u); }

    // The router's mapping, read now (remembered unless the budget was cut short); noted as this query's live read.
    Mapping ReadMapping(uint16_t port, bool tcp)
    {
        const DWORD ms = (std::min)(kHttpMs, Left(deadline_));
        std::string body;
        Mapping m;
        const bool answered = Soap(router_, "GetSpecificPortMappingEntry",
                                   {{"NewRemoteHost", ""}, {"NewExternalPort", std::to_string(port)}, {"NewProtocol", tcp ? "TCP" : "UDP"}},
                                   ms, &body);
        if (answered) m = ParseMappingResponse(body);
        liveMapping_ = answered ? MappingKey(port, tcp) : ~0u;
        if (answered || ms == kHttpMs) {      // a miss on a cut-short budget is not remembered
            Lock l(g_lock);
            if (generation_ == g_generation) g_mappings[MappingKey(port, tcp)] = Timed{m, GetTickCount()};
        }
        return m;
    }

    // A fresh TCP connect to ip:port; remembered (a miss only on a full budget) and noted as this query's probe.
    bool Probe(uint32_t ip, uint16_t port)
    {
        const DWORD ms = (std::min)(kAnswerMs, Left(deadline_));
        const bool ok = Accepts(ip, port, ms);
        probed_ = AnswerKey(ip, port);
        probedOk_ = ok;
        if (ok || ms == kAnswerMs) {
            Lock l(g_lock);
            if (generation_ == g_generation) g_answers[AnswerKey(ip, port)] = {ok, GetTickCount()};
        }
        return ok;
    }

    DWORD deadline_;
    Router router_;
    unsigned generation_ = 0;
    uint64_t probed_ = ~0ull;
    bool probedOk_ = false;
    uint32_t liveMapping_ = ~0u;
};

void LogOnce(const std::string& key, const std::string& line)
{
    Lock l(g_lock);
    if (g_logged.size() > 256 || !g_logged.insert(key).second) return;
    Log(line);
}

// ---------------------------------------------------------------------------------------------- hooks
HRESULT WINAPI QueryAddressHook(void* self, const SOCKADDR* source, const SOCKADDR* query, SOCKADDR* response, int size,
                                DWORD flags)
{
    FQueryAddress original = nullptr;
    void** vt = self ? *reinterpret_cast<void***>(self) : nullptr;
    for (const VtSlot& s : g_slots)
        if (s.vtable == vt && s.original) original = s.original;
    if (!original) return static_cast<HRESULT>(0x80004005);   // E_FAIL: unreachable (only patched vtables lead here)
    const HRESULT hr = original(self, source, query, response, size, flags);
    if (!g_on || !IsOurCase(static_cast<uint32_t>(hr)) || !query || !response || size < kSockaddrSize) return hr;
    const DWORD lastError = GetLastError();
    HRESULT out = hr;
    try {
        const V4 q = ParseSockaddr(reinterpret_cast<const unsigned char*>(query), size);
        const bool tcp = (flags & kQueryTcp) != 0;
        LiveEnv env(GetTickCount() + kQueryBudgetMs);
        const Decision d = Resolve(static_cast<uint32_t>(hr), flags, q, env);
        if (d.why != Why::NotOurCase) {
            // The dedup key keeps the full address (memory only); the logged line never shows a public one.  A
            // translation only ever answers a query for the router's own public address.
            const std::string tail = ":" + std::to_string(q.port) + (tcp ? "/TCP" : "/UDP");
            const std::string what = FormatIPv4(q.ip) + tail;
            const std::string shown = LogIPv4(q.ip, d.translate ? "<router-public>" : "<public>") + tail;
            if (d.translate)
                LogOnce(what + ">", shown + " -> " + LogIPv4(d.ip) + ":" + std::to_string(d.port) +
                                        " (behind this router, which does not loop back; Windows' NAT helper said " +
                                        (static_cast<uint32_t>(hr) == kHrNoMapping ? "no mapping" : "no server") + ")");
            else
                LogOnce(what + "|" + WhyName(d.why), shown + ": left to DirectPlay (" + WhyName(d.why) + ")");
        }
        if (d.translate) {
            WriteSockaddr(reinterpret_cast<unsigned char*>(response), d.ip, d.port);
            out = static_cast<HRESULT>(kHrOk);
        }
    } catch (...) {
        out = hr;
    }
    SetLastError(lastError);
    return out;
}

void PatchVtable(void* obj)
{
    if (!obj) return;
    void** vt = *reinterpret_cast<void***>(obj);
    if (!vt) return;
    Lock l(g_patchLock);
    if (vt[9] == reinterpret_cast<void*>(&QueryAddressHook)) return;
    VtSlot* slot = nullptr;
    for (VtSlot& s : g_slots)
        if (s.vtable == vt) slot = &s;
    for (VtSlot& s : g_slots)
        if (!slot && !s.vtable) slot = &s;
    if (!slot) {
        Log("DirectPlay NAT helper: no free slot (dpnathlp.dll reloaded too often) -- this copy is left alone");
        return;
    }
    MEMORY_BASIC_INFORMATION mbi = {};
    if (!VirtualQuery(&vt[9], &mbi, sizeof mbi)) return;
    const DWORD exec = PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
    DWORD old = 0;
    if (!VirtualProtect(&vt[9], sizeof(void*), (mbi.Protect & exec) ? PAGE_EXECUTE_READWRITE : PAGE_READWRITE, &old)) return;
    slot->original = reinterpret_cast<FQueryAddress>(vt[9]);   // the entry first, then the slot that leads to it
    slot->vtable = vt;
    MemoryBarrier();
    InterlockedExchangePointer(&vt[9], reinterpret_cast<void*>(&QueryAddressHook));
    DWORD ignored = 0;
    VirtualProtect(&vt[9], sizeof(void*), old, &ignored);
    FlushInstructionCache(GetCurrentProcess(), &vt[9], sizeof(void*));
    Log("DirectPlay NAT helper: QueryAddress completed for machines behind a router without NAT loopback");
}

// The IDirectPlayNATHelp interfaces whose vtable slot 9 is QueryAddress(this, source, query, response, size, flags)
// (stdcall, pops 0x18), measured on Windows 11 26100's dpnathlp.dll: the one dpwsockx asks for and the other its
// QueryInterface hands out for the same object.  Any other interface -- a different DirectPlay build (an old
// redistributable copy beside the game, Windows 7's, Wine's) -- is left alone: patching a slot with a different
// signature would corrupt the stack.
const GUID kNatHelpIids[] = {
    {0x3B743591, 0x791B, 0x4864, {0x9E, 0xE3, 0x55, 0xE8, 0x89, 0x40, 0x97, 0x81}},
    {0x154940B7, 0x2278, 0x4A2F, {0x91, 0x01, 0x9B, 0xA9, 0xF4, 0x31, 0xF6, 0x03}},
};

bool KnownNatHelpIid(const GUID* iid)
{
    if (!iid) return false;
    for (const GUID& g : kNatHelpIids)
        if (std::memcmp(iid, &g, sizeof g) == 0) return true;
    return false;
}

HRESULT WINAPI NatCreateHook(const GUID* iid, void** out)
{
    const auto real = reinterpret_cast<FNatCreate>(g_realCreate);
    if (!real) return static_cast<HRESULT>(0x80004005);
    const HRESULT hr = real(iid, out);
    if (SUCCEEDED(hr) && out && *out) {
        try {
            if (KnownNatHelpIid(iid)) {
                PatchVtable(*out);
                KickDiscovery(true);          // found before DirectPlay's first query needs it (which may wait for it)
            } else {
                Lock l(g_lock);
                if (g_logged.insert("iid").second)
                    Log("DirectPlay NAT helper: an interface this fix does not know -- left alone (DirectPlay unchanged)");
            }
        } catch (...) {                       // out of memory: leave DirectPlay as it is
        }
    }
    return hr;
}

FARPROC WINAPI GetProcAddressHook(HMODULE module, LPCSTR name)
{
    const FARPROC p = reinterpret_cast<FARPROC(WINAPI*)(HMODULE, LPCSTR)>(g_origGpa)(module, name);
    if (p && (reinterpret_cast<uintptr_t>(name) >> 16) != 0 && lstrcmpA(name, "DirectPlayNATHelpCreate") == 0) {
        InterlockedExchangePointer(const_cast<void**>(&g_realCreate), reinterpret_cast<void*>(p));
        return reinterpret_cast<FARPROC>(&NatCreateHook);
    }
    return p;
}

// The IAT slot of `func` (imported by name) in `mod`; nullptr when absent.
void** FindIatSlot(HMODULE mod, const char* func)
{
    auto* base = reinterpret_cast<unsigned char*>(mod);
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return nullptr;
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return nullptr;
    const IMAGE_DATA_DIRECTORY& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress) return nullptr;
    for (auto* d = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(base + dir.VirtualAddress); d->Name; ++d) {
        if (!d->OriginalFirstThunk || !d->FirstThunk) continue;
        auto* names = reinterpret_cast<IMAGE_THUNK_DATA*>(base + d->OriginalFirstThunk);
        auto* slots = reinterpret_cast<IMAGE_THUNK_DATA*>(base + d->FirstThunk);
        for (; names->u1.AddressOfData; ++names, ++slots) {
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal)) continue;
            auto* ibn = reinterpret_cast<IMAGE_IMPORT_BY_NAME*>(base + names->u1.AddressOfData);
            if (lstrcmpA(reinterpret_cast<const char*>(ibn->Name), func) == 0) return reinterpret_cast<void**>(&slots->u1.Function);
        }
    }
    return nullptr;
}

// `original` receives what the slot holds (chained, so an AppCompat shim or another hook keeps working) BEFORE the
// slot is written.  A slot that already holds `replacement` is left as it is.
bool PatchIat(HMODULE mod, const char* func, void* replacement, void* volatile* original)
{
    // Serialised: two threads loading dpwsockx at once would otherwise interleave VirtualProtect calls, and one could
    // restore the page to read-only just before the other's interlocked write (an access violation; audit 2026-11-07).
    Lock l(g_patchLock);
    void** slot = FindIatSlot(mod, func);
    if (!slot) return false;
    void* const current = *static_cast<void* volatile*>(slot);
    if (current == replacement) return *original != nullptr;
    if (!current) return false;
    MEMORY_BASIC_INFORMATION mbi = {};
    if (!VirtualQuery(slot, &mbi, sizeof mbi)) return false;
    const DWORD exec = PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
    DWORD old = 0;                            // an import table inside a code section keeps its execute permission
    if (!VirtualProtect(slot, sizeof(void*), (mbi.Protect & exec) ? PAGE_EXECUTE_READWRITE : PAGE_READWRITE, &old)) return false;
    InterlockedExchangePointer(const_cast<void**>(original), current);
    void* const was = InterlockedCompareExchangePointer(slot, replacement, current);
    DWORD ignored = 0;
    VirtualProtect(slot, sizeof(void*), old, &ignored);
    return was == current || was == replacement;
}

// Every load of dpwsockx.dll gets a fresh import table (a reload can reuse the base), so the slot itself says
// whether this copy is hooked.
void HookDpwsockx(HMODULE dpws)
{
    void** slot = FindIatSlot(dpws, "GetProcAddress");
    if (slot && *slot == reinterpret_cast<void*>(&GetProcAddressHook)) return;
    // Winsock for our own UPnP / probe sockets, first started here: DirectPlay's TCP/IP provider is loading, so the
    // game is about to start Winsock itself (refcounted; never cleaned up -- process lifetime).  Without it the
    // provider is left unhooked and DirectPlay behaves exactly as without the mod.
    static bool winsock = false;
    if (!winsock) {
        WSADATA wd;
        if (WSAStartup(MAKEWORD(2, 2), &wd) != 0) {
            Log("WSAStartup failed -- dpwsockx.dll left alone");
            return;
        }
        winsock = true;
    }
    if (!PatchIat(dpws, "GetProcAddress", reinterpret_cast<void*>(&GetProcAddressHook), &g_origGpa)) {
        Log("dpwsockx.dll: no GetProcAddress import -- not hooked");
        return;
    }
    Log("dpwsockx.dll (DirectPlay TCP/IP) hooked");
}

void OnLoaded(HMODULE h)
{
    if (!h) return;
    const DWORD lastError = GetLastError();
    const HMODULE dpws = GetModuleHandleA("dpwsockx.dll");
    try {
        if (dpws && dpws == h) HookDpwsockx(dpws);
    } catch (...) {                           // out of memory while logging: DirectPlay goes on unhooked
    }
    SetLastError(lastError);
}

HMODULE WINAPI LoadLibraryAHook(LPCSTR name)
{
    const HMODULE h = reinterpret_cast<HMODULE(WINAPI*)(LPCSTR)>(g_origLoadA)(name);
    OnLoaded(h);
    return h;
}

HMODULE WINAPI LoadLibraryWHook(LPCWSTR name)
{
    const HMODULE h = reinterpret_cast<HMODULE(WINAPI*)(LPCWSTR)>(g_origLoadW)(name);
    OnLoaded(h);
    return h;
}

// Alpha Centauri.ini beside the game exe (the module-local copy every module keeps).
bool IniPath(char* out, size_t n)
{
    const DWORD len = GetModuleFileNameA(nullptr, out, static_cast<DWORD>(n));
    if (len == 0 || len >= n) return false;
    char* slash = nullptr;
    for (char* c = out; *c; ++c)
        if (*c == '\\' || *c == '/') slash = c;
    if (!slash || static_cast<size_t>(slash + 1 - out) + sizeof "Alpha Centauri.ini" > n) return false;
    lstrcpyA(slash + 1, "Alpha Centauri.ini");
    return true;
}

} // namespace

void InstallLanJoinFix()
{
    char ini[MAX_PATH];
    const int setting = IniPath(ini, sizeof ini) ? static_cast<int>(GetPrivateProfileIntA("UIMod", "DirectPlayLanFix", 1, ini)) : 1;
    if (setting == 0) {
        UimodLog("[lanjoin] off ([UIMod] DirectPlayLanFix=0)\n");
        return;
    }
    const HMODULE dplayx = GetModuleHandleA("dplayx.dll");
    if (!dplayx) {
        UimodLog("[lanjoin] dplayx.dll not loaded -- not installed\n");
        return;
    }
    // No Winsock here: ws2_32 / iphlpapi are delay-loaded and first touched in HookDpwsockx, i.e. only once the
    // player picks TCP/IP multiplayer -- a single-player session never loads either.
    InitializeCriticalSection(&g_lock);
    InitializeCriticalSection(&g_patchLock);
    g_discoveryDone = CreateEventA(nullptr, TRUE, TRUE, nullptr);
    if (!g_discoveryDone) {
        UimodLog("[lanjoin] no event -- not installed\n");
        return;
    }
    g_on = true;
    const bool okA = PatchIat(dplayx, "LoadLibraryA", reinterpret_cast<void*>(&LoadLibraryAHook), &g_origLoadA);
    const bool okW = PatchIat(dplayx, "LoadLibraryW", reinterpret_cast<void*>(&LoadLibraryWHook), &g_origLoadW);
    if (!okA && !okW) {
        g_on = false;
        UimodLog("[lanjoin] dplayx.dll: no LoadLibrary import -- not installed\n");
        return;
    }
    UimodLog("[lanjoin] installed (DirectPlay LAN join behind routers without NAT loopback)\n");
    if (const HMODULE dpws = GetModuleHandleA("dpwsockx.dll")) {   // already loaded (not expected)
        try {
            HookDpwsockx(dpws);
        } catch (...) {                       // out of memory while logging: DirectPlay goes on unhooked
        }
    }
}
