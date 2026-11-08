// Integration harness for lanjoin.cpp (tests\test_lanjoin_live.py builds and runs it): the REAL LiveEnv, Resolve
// and QueryAddress hook against a fake UPnP router and fake peer games, all on loopback addresses -- no real network,
// no DirectPlay.  127.0.0.1 is "the LAN"; the router's public address is 127.0.0.2 when it loops back (a listener
// answers there for every mapped port) and 127.0.0.3 when it does not (nothing answers there).
// Prints one line per scenario: "<name> <result>".
#include "../../src/uimod/src/lanjoin.cpp"

#include <atomic>
#include <cstdio>
#include <thread>

void UimodLog(const char*) {}

namespace {

using namespace lanjoin;

constexpr uint32_t kLan = 0x7F000001;         // 127.0.0.1
constexpr uint32_t kLoops = 0x7F000002;       // a public address the "router" loops back on
constexpr uint32_t kNoLoop = 0x7F000003;      // one it does not

struct MapEntry { uint16_t ext; bool tcp; uint32_t ip; uint16_t port; };
std::vector<MapEntry> g_table;
std::atomic<int> g_routerDelayMs{0};
std::atomic<int> g_soapCalls{0};

SOCKET Listen(uint32_t ip, uint16_t port, uint16_t* bound)
{
    SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    sockaddr_in a = V4Addr(ip, port);
    BOOL on = TRUE;
    setsockopt(s, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, reinterpret_cast<const char*>(&on), sizeof on);
    if (bind(s, reinterpret_cast<sockaddr*>(&a), sizeof a) != 0 || listen(s, 16) != 0) { closesocket(s); return INVALID_SOCKET; }
    int len = sizeof a;
    getsockname(s, reinterpret_cast<sockaddr*>(&a), &len);
    if (bound) *bound = ntohs(a.sin_port);
    return s;
}

// A peer "game": accepts and counts connections.
struct Peer {
    SOCKET s = INVALID_SOCKET;
    uint16_t port = 0;
    std::atomic<int> accepted{0};
    std::thread t;
    void Start(uint32_t ip, uint16_t want = 0)
    {
        s = Listen(ip, want, &port);
        t = std::thread([this] {
            for (;;) {
                SOCKET c = accept(s, nullptr, nullptr);
                if (c == INVALID_SOCKET) return;
                ++accepted;
                closesocket(c);
            }
        });
        t.detach();
    }
};

// The fake router's SOAP endpoint: one thread per connection (a deliberately slow answer blocks nothing else).
void RouterAnswer(SOCKET c)
{
    {
        std::string req;
        char buf[4096];
        while (!HttpComplete("HTTP/1.0 200 X\r\n" + req.substr(req.find('\n') == std::string::npos ? 0 : req.find('\n') + 1))) {
            const int n = recv(c, buf, sizeof buf, 0);
            if (n <= 0) break;
            req.append(buf, static_cast<size_t>(n));
        }
        ++g_soapCalls;
        if (g_routerDelayMs > 0) Sleep(static_cast<DWORD>(g_routerDelayMs.load()));
        std::string body;
        int status = 500;
        if (req.find("GetSpecificPortMappingEntry") != std::string::npos) {
            const int ext = std::atoi(XmlValue(req, "NewExternalPort").c_str());
            const bool tcp = XmlValue(req, "NewProtocol") == "TCP";
            for (const MapEntry& e : g_table)
                if (e.ext == ext && e.tcp == tcp) {
                    body = "<s:Envelope><s:Body><u:GetSpecificPortMappingEntryResponse><NewInternalPort>" +
                           std::to_string(e.port) + "</NewInternalPort><NewInternalClient>" + FormatIPv4(e.ip) +
                           "</NewInternalClient><NewEnabled>1</NewEnabled></u:GetSpecificPortMappingEntryResponse></s:Body></s:Envelope>";
                    status = 200;
                }
        }
        const std::string resp = "HTTP/1.0 " + std::to_string(status) + " X\r\nContent-Length: " + std::to_string(body.size()) +
                                 "\r\n\r\n" + body;
        send(c, resp.data(), static_cast<int>(resp.size()), 0);
        closesocket(c);
    }
}

void RouterServe(SOCKET ls)
{
    for (;;) {
        SOCKET c = accept(ls, nullptr, nullptr);
        if (c == INVALID_SOCKET) return;
        std::thread(RouterAnswer, c).detach();
    }
}

void Seed(uint32_t external, uint16_t routerPort)
{
    Lock l(g_lock);
    g_router = Router();
    g_router.known = true;
    g_router.controlUrl = "http://127.0.0.1:" + std::to_string(routerPort) + "/ctl";
    g_router.serviceType = "urn:schemas-upnp-org:service:WANIPConnection:1";
    g_router.external = external;
    g_router.at = GetTickCount();
    Subnet lan;
    lan.ip = kLan;
    lan.prefix = 8;
    g_subnets = {lan};
    g_gateways = {kLan};
    g_subnetsAt = GetTickCount();
    g_subnetsKnown = true;
    g_mappings.clear();
    g_answers.clear();
    g_loops.clear();
}

std::string Ask(uint32_t hr, uint32_t flags, uint32_t ip, uint16_t port, DWORD* elapsed = nullptr)
{
    V4 q;
    q.ip = ip;
    q.port = port;
    q.ok = true;
    const DWORD t0 = GetTickCount();
    LiveEnv env(GetTickCount() + kQueryBudgetMs);
    const Decision d = Resolve(hr, flags, q, env);
    if (elapsed) *elapsed = GetTickCount() - t0;
    return d.translate ? std::string("translated ") + FormatIPv4(d.ip) + ":" + std::to_string(d.port) : WhyName(d.why);
}

// The hook end to end: a fake helper object whose QueryAddress answers NOMAPPING, patched like dpnathlp's.
HRESULT WINAPI FakeQuery(void*, const SOCKADDR*, const SOCKADDR*, SOCKADDR*, int, DWORD) { return static_cast<HRESULT>(kHrNoMapping); }
void* g_fakeVtable[13] = {};
struct FakeHelper { void** vt = g_fakeVtable; } g_helper;

} // namespace

int main()
{
    WSADATA wd;
    WSAStartup(MAKEWORD(2, 2), &wd);
    InitializeCriticalSection(&g_lock);
    InitializeCriticalSection(&g_patchLock);
    g_discoveryDone = CreateEventA(nullptr, TRUE, TRUE, nullptr);
    g_on = true;

    uint16_t routerPort = 0;
    SOCKET router = Listen(kLan, 0, &routerPort);
    std::thread(RouterServe, router).detach();

    Peer game, game2;                         // two LAN games, each listening on its own port
    game.Start(kLan);
    game2.Start(kLan);
    Peer loopA, loopB;                        // the looping router's public side for two mapped ports
    loopA.Start(kLoops);
    loopB.Start(kLoops);
    uint16_t dead = 0;                        // a LAN port nothing listens on
    { SOCKET d = Listen(kLan, 0, &dead); closesocket(d); }

    // ---- 1: no loopback, the game listens -> translated (TCP), then the datagram query rides on it
    g_table = {{51001, true, kLan, game.port}, {51002, false, kLan, 2350}};
    Seed(kNoLoop, routerPort);
    std::printf("noloop_tcp %s\n", Ask(kHrNoMapping, 5, kNoLoop, 51001).c_str());
    std::printf("noloop_udp %s\n", Ask(kHrNoMapping, 4, kNoLoop, 51002).c_str());
    std::printf("noloop_tcp_again %s\n", Ask(kHrServerNotAvailable, 5, kNoLoop, 51001).c_str());

    // ---- 2: a router that loops back -> today's path works: never translated, the game probed at most once
    g_table = {{loopA.port, true, kLan, game.port}, {loopB.port, true, kLan, dead}};
    Seed(kLoops, routerPort);
    std::printf("loops_tcp %s\n", Ask(kHrNoMapping, 5, kLoops, loopA.port).c_str());
    const int before = game.accepted.load();
    std::printf("loops_tcp_again %s\n", Ask(kHrNoMapping, 5, kLoops, loopA.port).c_str());
    std::printf("loops_no_reprobe %d\n", game.accepted.load() - before);

    // ---- 3: the second audit's poisoning: verdicts cleared (a refresh), then a mapping to a DEAD port, then the
    // good one again -> nothing is ever translated on the looping router
    { Lock l(g_lock); g_loops.clear(); }
    std::printf("poison_dead %s\n", Ask(kHrNoMapping, 5, kLoops, loopB.port).c_str());
    std::printf("poison_good %s\n", Ask(kHrNoMapping, 5, kLoops, loopA.port).c_str());

    // ---- 3b: the third audit's case: a mapping cached while the game was not up yet, then MOVED to another public
    // port before the game listens -- the stale mapping must not yield "does not loop back" on a router that does
    {
        uint16_t gLate = 0, p1 = 0;
        { SOCKET d = Listen(kLan, 0, &gLate); closesocket(d); }      // the game's port, not listening yet
        { SOCKET d = Listen(kLoops, 0, &p1); closesocket(d); }       // a public port nothing answers on any more
        Peer loopC;
        loopC.Start(kLoops);                                         // the mapping's new public port (loops back)
        g_table = {{p1, true, kLan, gLate}};
        Seed(kLoops, routerPort);
        std::printf("moved_before %s\n", Ask(kHrNoMapping, 5, kLoops, p1).c_str());
        Peer late;
        late.Start(kLan, gLate);
        g_table = {{loopC.port, true, kLan, gLate}};
        { Lock l(g_lock); g_answers.clear(); }                       // the 3 s "game did not answer" has run out
        std::printf("moved_stale %s\n", Ask(kHrNoMapping, 5, kLoops, p1).c_str());
        std::printf("moved_new %s\n", Ask(kHrNoMapping, 5, kLoops, loopC.port).c_str());
    }

    // ---- 4: a cached "game answered" for another port of the same machine does not stand in for this port
    g_table = {{51001, true, kLan, game.port}, {51003, true, kLan, dead}};
    Seed(kNoLoop, routerPort);
    std::printf("port_a %s\n", Ask(kHrNoMapping, 5, kNoLoop, 51001).c_str());
    std::printf("port_dead %s\n", Ask(kHrNoMapping, 5, kNoLoop, 51003).c_str());

    // ---- 5: the gates that never touch the network
    Seed(kNoLoop, routerPort);
    const int calls = g_soapCalls.load();
    std::printf("enum_port %s\n", Ask(kHrNoMapping, 4, kNoLoop, 47624).c_str());
    std::printf("internet %s\n", Ask(kHrNoMapping, 5, 0x08080808, 2300).c_str());
    std::printf("helper_ok %s\n", Ask(kHrOk, 5, kNoLoop, 51001).c_str());
    std::printf("no_soap %d\n", g_soapCalls.load() - calls);

    // ---- 6: a router that answers slowly: the query stays inside its budget and does not translate
    g_table = {{51004, true, kLan, game.port}};
    Seed(kNoLoop, routerPort);
    g_routerDelayMs = 3000;
    DWORD ms = 0;
    const std::string slow = Ask(kHrNoMapping, 5, kNoLoop, 51004, &ms);
    g_routerDelayMs = 0;
    std::printf("slow_router %s %s\n", slow.c_str(), ms <= kQueryBudgetMs + 250 ? "in-budget" : ("over:" + std::to_string(ms)).c_str());
    std::printf("slow_again %s\n", Ask(kHrNoMapping, 5, kNoLoop, 51004).c_str());   // a full-budget miss is kept (5 s)

    // ---- 7: the hook itself on a patched helper vtable
    g_table = {{51001, true, kLan, game.port}};
    Seed(kNoLoop, routerPort);
    g_fakeVtable[9] = reinterpret_cast<void*>(&FakeQuery);
    PatchVtable(&g_helper);
    unsigned char src[16] = {}, q[16], resp[16] = {};
    WriteSockaddr(q, kNoLoop, 51001);
    const HRESULT hr = reinterpret_cast<FQueryAddress>(g_fakeVtable[9])(&g_helper, reinterpret_cast<SOCKADDR*>(src),
                                                                      reinterpret_cast<SOCKADDR*>(q), reinterpret_cast<SOCKADDR*>(resp), 16, 5);
    const V4 r = ParseSockaddr(resp, 16);
    std::printf("hook %08lx %s:%u\n", static_cast<unsigned long>(hr), FormatIPv4(r.ip).c_str(), r.port);
    std::printf("hook_patched %d\n", g_fakeVtable[9] == reinterpret_cast<void*>(&QueryAddressHook) ? 1 : 0);
    WriteSockaddr(q, 0x08080808, 2300);
    std::memset(resp, 0, sizeof resp);
    const HRESULT hr2 = reinterpret_cast<FQueryAddress>(g_fakeVtable[9])(&g_helper, reinterpret_cast<SOCKADDR*>(src),
                                                                       reinterpret_cast<SOCKADDR*>(q), reinterpret_cast<SOCKADDR*>(resp), 16, 5);
    std::printf("hook_internet %08lx\n", static_cast<unsigned long>(hr2));
    // ---- 8: the create wrapper patches only a known interface (a different DirectPlay build's slot 9 may not be
    // QueryAddress at all)
    {
        static void* otherVt[13] = {};
        static void* knownVt[13] = {};
        struct Obj { void** vt; };
        static Obj other = {otherVt}, known = {knownVt};
        otherVt[9] = reinterpret_cast<void*>(&FakeQuery);
        knownVt[9] = reinterpret_cast<void*>(&FakeQuery);
        static Obj* next = nullptr;
        struct Create {
            static HRESULT WINAPI Fake(const GUID*, void** out) { *out = next; return 0; }
        };
        g_realCreate = reinterpret_cast<void*>(&Create::Fake);
        const GUID unknownIid = {0x12345678, 0x1234, 0x1234, {1, 2, 3, 4, 5, 6, 7, 8}};
        const GUID dpwsockxIid = {0x3B743591, 0x791B, 0x4864, {0x9E, 0xE3, 0x55, 0xE8, 0x89, 0x40, 0x97, 0x81}};
        void* out = nullptr;
        next = &other;
        NatCreateHook(&unknownIid, &out);
        next = &known;
        NatCreateHook(&dpwsockxIid, &out);
        std::printf("iid_unknown_patched %d\n", otherVt[9] == reinterpret_cast<void*>(&QueryAddressHook) ? 1 : 0);
        std::printf("iid_known_patched %d\n", knownVt[9] == reinterpret_cast<void*>(&QueryAddressHook) ? 1 : 0);
    }
    std::printf("ports %u %u\n", game.port, dead);
    std::fflush(stdout);
    ExitProcess(0);                           // detached server threads
}
