"""uimod lanjoin_core.h -- the DirectPlay LAN-join fix's pure logic (lanjoin.cpp hooks it into Windows' DirectPlay).

DirectPlay's TCP/IP provider (dpwsockx.dll) asks its NAT helper (IDirectPlayNATHelp::QueryAddress) whether a public
address is really a machine behind the same router; the helper only knows its own machine's mappings, so a second PC
on the LAN is "no mapping" and LAN games are never found on routers without NAT loopback (diagnosed 2026-11-07).
The fix completes that one answer and nothing else: these tests pin every gate of Decide, the parsers that feed it
(sockaddr, IPv4, subnet, SSDP, URL, UPnP description, SOAP), and -- where Windows' DirectPlay DLLs are present -- the
call shapes in dpwsockx.dll / dplayx.dll that lanjoin.cpp hooks.  One self-test exe, built once; every case is a
batch line on stdin (no process per case)."""
from __future__ import annotations

import itertools
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import cpp_harness  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "lanjoin"
NOMAPPING, NOSERVER = "8015f050", "8015f0a0"
PUBLIC = "203.0.113.7"                       # documentation range, stands in for a router's public address


@pytest.fixture(scope="module")
def exe():
    if not cpp_harness.have_toolchain():
        pytest.skip("Visual Studio x86 toolchain not available")
    return cpp_harness.build(ROOT / "tests" / "lanjoin_selftest.cpp", "lanjoin_selftest_")


def batch(exe, lines):
    out = subprocess.run([str(exe)], input="\n".join("\t".join(map(str, l)) for l in lines) + "\n",
                         capture_output=True, text=True, check=True).stdout.splitlines()
    assert len(out) == len(lines), out
    return out


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_bytes(text.encode("utf-8"))
    return str(p)


# ---------------------------------------------------------------------------------------------- sockaddr / IPv4
def test_sockaddr(exe):
    # the reply-to field of a real DirectPlay ENUMSESSIONS (bytes 4..19 of the 52-byte request), public IP anonymised
    hdr = "0200dbc8cb007107" + "80f6910600000080"
    cases = [(("sockaddr", hdr), f"{PUBLIC}:56264"),
             (("sockaddr", hdr, 15), "bad"),                         # too short
             (("sockaddr", "1700" + hdr[4:]), "bad"),                 # AF_INET6
             (("sockaddr", "0201" + hdr[4:]), "bad"),                 # family is a little-endian u16
             (("sockaddr", "020008fcc0a8008f" + "0" * 16), "192.168.0.143:2300")]
    assert batch(exe, [c for c, _ in cases]) == [w for _, w in cases]


def test_write_sockaddr_clears_the_tail(exe):
    assert batch(exe, [("write", "192.168.0.143", 2300), ("write", "0.0.0.0", 0), ("write", "255.255.255.255", 65535)]) == [
        "020008fcc0a8008f" + "0" * 16, "0200" + "0" * 28, "0200ffffffffffff" + "0" * 16]


@pytest.mark.parametrize("s,want", [("192.168.0.1", "192.168.0.1"), ("0.0.0.0", "0.0.0.0"), ("255.255.255.255", "255.255.255.255"),
                                    ("010.1.1.1", "10.1.1.1")])
def test_parse_ipv4_good(exe, s, want):
    assert batch(exe, [("parseip", s)]) == [want]


def test_parse_ipv4_bad(exe):
    bad = ["", "256.1.1.1", "1.2.3", "1.2.3.4.5", "1..2.3", " 1.2.3.4", "1.2.3.4 ", "1.2.3.-4", "1.2.3.4a", "0001.2.3.4",
           "a.b.c.d", "1.2.3.", ".1.2.3"]
    assert batch(exe, [("parseip", b) for b in bad]) == ["bad"] * len(bad)


def test_subnets(exe):
    cases = [(("subnet", "192.168.0.143", "192.168.0.183/24"), "1"),
             (("subnet", "192.168.1.5", "192.168.0.183/24"), "0"),          # a guest network on another subnet
             (("subnet", "192.168.0.143", "192.168.0.183/0"), "0"),         # /0 is a route, never a link
             (("subnet", "192.168.0.143", "100.64.0.1/32", "192.168.0.183/24"), "1"),
             (("subnet", "100.64.0.2", "100.64.0.1/32"), "0"),
             (("subnet", "10.0.5.9", "10.0.0.2/16"), "1"),
             (("subnet", "10.1.5.9", "10.0.0.2/16"), "0"),
             (("subnet", "192.168.0.143"), "0")]                               # no subnets known
    assert batch(exe, [c for c, _ in cases]) == [w for _, w in cases]


# uimod.log goes into public bug reports: a LAN address may be shown, any other address never.
@pytest.mark.parametrize("ip,want", [("192.168.0.143", "192.168.0.143"), ("10.1.2.3", "10.1.2.3"), ("172.16.0.1", "172.16.0.1"),
                                     ("172.31.255.255", "172.31.255.255"), ("127.0.0.1", "127.0.0.1"),
                                     ("169.254.1.1", "169.254.1.1"), ("172.32.0.1", "<public>"), ("172.15.0.1", "<public>"),
                                     ("203.0.113.7", "<public>"), ("100.64.0.1", "<public>"), ("192.169.0.1", "<public>"),
                                     ("11.0.0.1", "<public>")])
def test_log_shows_only_lan_addresses(exe, ip, want):
    assert batch(exe, [("logip", ip)]) == [want]


def test_log_names_the_router_public_address_without_writing_it(exe):
    assert batch(exe, [("logip", "203.0.113.7", "<router-public>")]) == ["<router-public>"]


def test_no_log_line_formats_an_unmasked_address():
    """Every FormatIPv4 in lanjoin.cpp is either the in-memory dedup key or behind IsLanAddress."""
    src = (pathlib.Path(__file__).resolve().parents[2] / "src" / "uimod" / "src" / "lanjoin.cpp").read_text(encoding="utf-8")
    hits = [ln.strip() for ln in src.splitlines() if "FormatIPv4(" in ln]
    assert hits, "lanjoin.cpp no longer formats addresses: update this guard"
    for ln in hits:
        assert "IsLanAddress(" in ln or ln.startswith("const std::string what = "), ln


# ---------------------------------------------------------------------------------------------- SSDP / HTTP / URLs
def test_ssdp_location(exe, tmp_path):
    ok = write(tmp_path, "ok.txt", "HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=120\r\nST: urn:schemas-upnp-org:device:"
                                   "InternetGatewayDevice:1\r\nLOCATION: http://192.168.0.1:1900/rootDesc.xml \r\nSERVER: x\r\n\r\n")
    lower = write(tmp_path, "lower.txt", "HTTP/1.1 200 OK\r\nlocation:http://10.0.0.1:5000/d.xml\r\n\r\n")
    decoy = write(tmp_path, "decoy.txt", "HTTP/1.1 200 OK\r\nX-LOCATION: http://evil/\r\nAL: <LOCATION: no>\r\n\r\n")
    assert batch(exe, [("header", ok, "LOCATION"), ("header", lower, "LOCATION"), ("header", decoy, "LOCATION")]) == [
        "http://192.168.0.1:1900/rootDesc.xml", "http://10.0.0.1:5000/d.xml", "-"]


@pytest.mark.parametrize("url,want", [
    ("http://192.168.0.1:1900/rootDesc.xml", "192.168.0.1 1900 /rootDesc.xml"),
    ("http://192.168.0.1/rootDesc.xml", "192.168.0.1 80 /rootDesc.xml"),
    ("HTTP://192.168.0.1:5000", "192.168.0.1 5000 /"),
    ("https://192.168.0.1/x", "bad"), ("ftp://h/x", "bad"), ("http://u:p@192.168.0.1/x", "bad"),
    ("http://[fe80::1]:1900/x", "bad"), ("http://192.168.0.1:0/x", "bad"), ("http://192.168.0.1:65536/x", "bad"),
    ("http://192.168.0.1:12a/x", "bad"), ("http:///x", "bad")])
def test_url(exe, url, want):
    assert batch(exe, [("url", url)]) == [want]


def test_resolve(exe):
    loc = "http://192.168.0.1:1900/desc/rootDesc.xml"
    cases = [((loc, "-", "/ctl/IPConn"), "http://192.168.0.1:1900/ctl/IPConn"),
             ((loc, "-", "ctl/IPConn"), "http://192.168.0.1:1900/desc/ctl/IPConn"),
             ((loc, "-", "http://192.168.0.1:5555/c"), "http://192.168.0.1:5555/c"),
             ((loc, "http://192.168.0.1:5000/", "/ctl"), "http://192.168.0.1:5000/ctl"),
             ((loc, "http://192.168.0.1:5000/base/", "ctl"), "http://192.168.0.1:5000/base/ctl"),
             (("garbage", "-", "/ctl"), "-")]
    assert batch(exe, [("resolve",) + c for c, _ in cases]) == [w for _, w in cases]


def test_http_status_and_body(exe, tmp_path):
    ok = write(tmp_path, "ok.txt", "HTTP/1.1 200 OK\r\nContent-Type: text/xml\r\n\r\n<a>1</a>")
    err = write(tmp_path, "err.txt", "HTTP/1.0 500 Internal Server Error\r\n\r\n<fault/>")
    junk = write(tmp_path, "junk.txt", "garbage")
    assert batch(exe, [("status", ok), ("status", err), ("status", junk), ("body", ok)]) == ["200", "500", "0", "<a>1</a>"]


# ---------------------------------------------------------------------------------------------- UPnP description / SOAP
def test_real_router_description(exe):
    """A miniupnpd IGD description from a real router, captured 2026-11-07 (identity, UUID and build anonymised)."""
    f = str(FIXTURES / "miniupnpd_rootDesc.xml")
    assert batch(exe, [("service", f), ("xml", f, "URLBase"), ("xml", f, "modelName")]) == [
        "urn:schemas-upnp-org:service:WANIPConnection:1 /ctl/IPConn", "-", "Example Router"]


def _desc(*services):
    return "<root><device><serviceList>" + "".join(
        f"<service><serviceType>{t}</serviceType><serviceId>x</serviceId>{'<controlURL>' + c + '</controlURL>' if c else ''}"
        f"<eventSubURL>/e</eventSubURL></service>" for t, c in services) + "</serviceList></device></root>"


def test_wan_service_choice(exe, tmp_path):
    ip1, ip2 = "urn:schemas-upnp-org:service:WANIPConnection:1", "urn:schemas-upnp-org:service:WANIPConnection:2"
    ppp, l3 = "urn:schemas-upnp-org:service:WANPPPConnection:1", "urn:schemas-upnp-org:service:Layer3Forwarding:1"
    cases = [((l3, "/l3"), (ppp, "/ppp")), ((ppp, "/ppp"), (ip1, "/ip")), ((ip2, "/ip2"),), ((l3, "/l3"),),
             ((ip1, ""), (l3, "/l3"))]     # an IP service without its own controlURL must not borrow the next block's
    files = [write(tmp_path, f"d{i}.xml", _desc(*c)) for i, c in enumerate(cases)]
    assert batch(exe, [("service", f) for f in files]) == [f"{ppp} /ppp", f"{ip1} /ip", f"{ip2} /ip2", "none", "none"]


def test_soap_envelope(exe):
    t = "urn:schemas-upnp-org:service:WANIPConnection:1"
    out = batch(exe, [("soap", t, "GetSpecificPortMappingEntry", "NewRemoteHost=", "NewExternalPort=56264", "NewProtocol=TCP")])[0]
    assert out == ('<?xml version="1.0"?>|<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                   's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:GetSpecificPortMappingEntry '
                   f'xmlns:u="{t}"><NewRemoteHost></NewRemoteHost><NewExternalPort>56264</NewExternalPort>'
                   '<NewProtocol>TCP</NewProtocol></u:GetSpecificPortMappingEntry></s:Body></s:Envelope>|')


def _mapping(client, port, enabled=None):
    e = "" if enabled is None else f"<NewEnabled>{enabled}</NewEnabled>"
    return ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
            '<u:GetSpecificPortMappingEntryResponse xmlns:u="urn:schemas-upnp-org:service:WANIPConnection:1">'
            f'<NewInternalPort>{port}</NewInternalPort><NewInternalClient>{client}</NewInternalClient>{e}'
            '<NewPortMappingDescription>terranx_PRACX (192.168.0.143:2300) 56264 TCP</NewPortMappingDescription>'
            '<NewLeaseDuration>0</NewLeaseDuration></u:GetSpecificPortMappingEntryResponse></s:Body></s:Envelope>')


def test_mapping_response(exe, tmp_path):
    cases = [(_mapping("192.168.0.143", 2300, 1), "192.168.0.143:2300 1"),
             (_mapping("192.168.0.143", 2300, 0), "192.168.0.143:2300 0"),
             (_mapping("192.168.0.143", 2300), "192.168.0.143:2300 1"),           # NewEnabled absent: enabled
             (_mapping("192.168.0.143", 2300, "true"), "192.168.0.143:2300 1"),
             (_mapping("192.168.0.143", 2300, "TRUE"), "192.168.0.143:2300 1"),
             (_mapping("192.168.0.143", 2300, "yes"), "192.168.0.143:2300 1"),
             (_mapping("192.168.0.143", 2300, "no"), "192.168.0.143:2300 0"),
             (_mapping("not-an-ip", 2300, 1), "bad"), (_mapping("192.168.0.143", 0, 1), "bad"),
             (_mapping("192.168.0.143", 70000, 1), "bad"), (_mapping("192.168.0.143", "", 1), "bad"),
             ('<s:Fault><errorCode>714</errorCode><errorDescription>NoSuchEntryInArray</errorDescription></s:Fault>', "bad")]
    files = [write(tmp_path, f"m{i}.xml", body) for i, (body, _) in enumerate(cases)]
    assert batch(exe, [("mapping", f) for f in files]) == [w for _, w in cases]


# ---------------------------------------------------------------------------------------------- the decision
LAN = "192.168.0.143"
OK_WORLD = (f"router={PUBLIC}", f"map={LAN}:2300", "local=1", "answers=1", "loops=0")
FULL_TCP = f"router;lookup 56264 tcp;local {LAN};answers {LAN}:2300;loops {PUBLIC}:56264>{LAN}:2300"


def gate(exe, *lines):
    return batch(exe, [("gate",) + tuple(l) for l in lines])


def test_translates_only_where_the_public_path_fails(exe):
    """The whole question, asked in order: the probe goes to the machine's INTERNAL port on its private address,
    the loopback test to the router's PUBLIC address and port, the mapping is looked up with the query's protocol."""
    assert gate(exe, (NOMAPPING, 5, f"{PUBLIC}:56264") + OK_WORLD,
                (NOSERVER, 1, f"{PUBLIC}:56264") + OK_WORLD) == [f"1 {LAN}:2300 translated | {FULL_TCP}"] * 2


def test_each_gate_stops_the_questions_after_it(exe):
    q = (NOMAPPING, 5, f"{PUBLIC}:56264")
    cases = [(("0", 5, f"{PUBLIC}:56264") + OK_WORLD, "0 - not-our-case | "),
             (("80004005", 5, f"{PUBLIC}:56264") + OK_WORLD, "0 - not-our-case | "),
             (("8015f060", 5, f"{PUBLIC}:56264") + OK_WORLD, "0 - not-our-case | "),
             ((NOMAPPING, 5, "bad") + OK_WORLD, "0 - not-our-case | "),
             ((NOMAPPING, 5, f"{PUBLIC}:0") + OK_WORLD, "0 - not-our-case | "),
             ((NOMAPPING, 5, "0.0.0.0:56264") + OK_WORLD, "0 - not-our-case | "),
             ((NOMAPPING, 4, f"{PUBLIC}:47624") + OK_WORLD, "0 - enum-port | "),       # dpwsockx would broadcast
             ((NOMAPPING, 5, f"{PUBLIC}:47624") + OK_WORLD, "0 - enum-port | "),
             (q + ("router=none",) + OK_WORLD[1:], "0 - no-router | router"),
             ((NOMAPPING, 5, "198.51.100.9:56264") + OK_WORLD, "0 - not-router-address | router"),
             (q + OK_WORLD[:1] + ("map=none",) + OK_WORLD[2:], "0 - no-mapping | router;lookup 56264 tcp"),
             (q + OK_WORLD[:1] + (f"map={LAN}:2300:0",) + OK_WORLD[2:], "0 - no-mapping | router;lookup 56264 tcp"),
             (q + OK_WORLD[:1] + ("map=0.0.0.0:2300",) + OK_WORLD[2:], "0 - no-mapping | router;lookup 56264 tcp"),
             (q + OK_WORLD[:1] + (f"map={LAN}:0",) + OK_WORLD[2:], "0 - no-mapping | router;lookup 56264 tcp"),
             (q + OK_WORLD[:2] + ("local=0",) + OK_WORLD[3:], f"0 - not-local | router;lookup 56264 tcp;local {LAN}"),
             (q + OK_WORLD[:3] + ("answers=0",) + OK_WORLD[4:],
              f"0 - unreachable | router;lookup 56264 tcp;local {LAN};answers {LAN}:2300"),
             (q + OK_WORLD[:4] + ("loops=1",), f"0 - router-loops-back | {FULL_TCP}"),   # today's path works
             (q + OK_WORLD[:4] + ("loops=-1",), f"0 - loopback-unknown | {FULL_TCP}")]
    assert gate(exe, *[c for c, _ in cases]) == [w for _, w in cases]


def test_datagram_queries_need_an_earlier_stream_verdict(exe):
    """A UDP query cannot probe: it translates only on a recent TCP answer from that machine AND a cached
    'does not loop back' verdict (LoopsBack asked with no port)."""
    q = (NOMAPPING, 4, f"{PUBLIC}:12745")
    base = f"router;lookup 12745 udp;local {LAN};recent {LAN}"
    w = (f"router={PUBLIC}", f"map={LAN}:2350")
    cases = [(q + w + ("recent=0",), f"0 - unreachable | {base}"),
             (q + w + ("recent=1",), f"0 - loopback-unknown | {base};loops {PUBLIC}:0>{LAN}:2350"),
             (q + w + ("recent=1", "loops0=1"), f"0 - router-loops-back | {base};loops {PUBLIC}:0>{LAN}:2350"),
             (q + w + ("recent=1", "loops0=0"), f"1 {LAN}:2350 translated | {base};loops {PUBLIC}:0>{LAN}:2350")]
    assert gate(exe, *[c for c, _ in cases]) == [w for _, w in cases]


def test_translates_only_when_every_gate_passes(exe):
    """All 2^8 combinations of eight gates (TCP): a translation happens in exactly one."""
    good = dict(hr=NOMAPPING, q="ok", router=PUBLIC, map=f"{LAN}:2300", local="1", answers="1", loops="0", port="56264")
    bad = dict(hr="0", q="bad", router="none", map="none", local="0", answers="0", loops="1", port="47624")
    keys = list(good)
    lines, wants = [], []
    for bits in itertools.product((0, 1), repeat=len(keys)):
        v = {k: (good[k] if b else bad[k]) for k, b in zip(keys, bits)}
        q = "bad" if v["q"] == "bad" else f"{PUBLIC}:{v['port']}"
        lines.append(("gate", v["hr"], 5, q, f"router={v['router']}", f"map={v['map']}", f"local={v['local']}",
                      f"answers={v['answers']}", f"loops={v['loops']}"))
        wants.append(all(bits))
    assert [o.startswith("1 ") for o in batch(exe, lines)] == wants


# ---------------------------------------------------------------------------------------------- hostile input (audit)
def test_parsers_on_hostile_input(exe, tmp_path):
    comment = write(tmp_path, "c.xml", "<!--<NewExternalIPAddress>6.6.6.6</NewExternalIPAddress>-->"
                                       "<NewExternalIPAddress>203.0.113.7</NewExternalIPAddress>")
    cdata = write(tmp_path, "d.xml", "<![CDATA[<NewExternalIPAddress>6.6.6.6</NewExternalIPAddress>]]><x/>")
    ns = write(tmp_path, "n.xml", "<root><a:service><a:serviceType>urn:schemas-upnp-org:service:WANIPConnection:1"
                                  "</a:serviceType><a:controlURL>/ctl</a:controlURL></a:service></root>")
    endt = write(tmp_path, "e.xml", "<a><serviceId>x</serviceId></ns:service>")
    st = write(tmp_path, "s.txt", "HTTP/1.1 2000 OK\r\n\r\n")
    full = write(tmp_path, "f.txt", "HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nabcd")
    part = write(tmp_path, "p.txt", "HTTP/1.1 200 OK\r\nContent-Length: 40\r\n\r\nabcd")
    nolen = write(tmp_path, "l.txt", "HTTP/1.1 200 OK\r\n\r\nabcd")
    big = write(tmp_path, "b.xml", "<serviceType>x</serviceType>" * 20000)    # no </service>: linear, no hit
    assert batch(exe, [("xml", comment, "NewExternalIPAddress"), ("xml", cdata, "NewExternalIPAddress"),
                       ("service", ns), ("endtag", endt, "service"), ("status", st),
                       ("complete", full), ("complete", part), ("complete", nolen), ("service", big)]) == [
        "203.0.113.7", "-", "urn:schemas-upnp-org:service:WANIPConnection:1 /ctl", "27", "0", "1", "0", "0", "none"]


def test_urls_that_could_end_the_request_line_or_name_a_host(exe, tmp_path):
    bad = ["http://192.168.0.1:1900/x\x0bX-Injected:y", "http://192.168.0.1:1900/a b",
           "http://router.lan:1900/x", "http://192.168.0.1.nip.io/x", "http://" + "1" * 600]
    assert batch(exe, [("url", u) for u in bad]) == ["bad"] * len(bad)


def test_only_a_gateway_is_trusted_as_the_router(exe):
    loc, ctl = "http://192.168.0.1:1900/rootDesc.xml", "http://192.168.0.1:1900/ctl/IPConn"
    assert batch(exe, [("trusted", loc, ctl, "192.168.0.1"),
                       ("trusted", loc, ctl, "10.0.0.1,192.168.0.1"),
                       ("trusted", loc, ctl, "192.168.0.254"),                       # a LAN device that is not the gateway
                       ("trusted", loc, "http://127.0.0.1:80/x", "192.168.0.1"),     # control URL elsewhere
                       ("trusted", loc, "http://192.168.0.5:1900/ctl", "192.168.0.1"),
                       ("trusted", loc, ctl, "")]) == ["1", "1", "0", "0", "0", "0"]


# ---------------------------------------------------------------------------------------------- Windows' DirectPlay
SYSWOW64 = pathlib.Path(os.environ.get("WINDIR", r"C:\Windows")) / "SysWOW64"


@pytest.mark.skipif(not (SYSWOW64 / "dpwsockx.dll").exists(), reason="DirectPlay (Legacy Components) not installed")
def test_directplay_call_shapes():
    """What lanjoin.cpp hooks, read from this machine's DirectPlay: dplayx.dll imports LoadLibraryA/W by name;
    dpwsockx.dll imports GetProcAddress by name, looks up "DirectPlayNATHelpCreate", and calls the helper's vtable
    slot 9 (+0x24, QueryAddress) with five stack arguments (source, query, response, 16, flags).  A Windows update that changes any of this fails here, not silently in a game."""
    pefile = pytest.importorskip("pefile")
    capstone = pytest.importorskip("capstone")

    def imports(path):
        pe = pefile.PE(str(path))
        return pe, {i.name.decode() for e in pe.DIRECTORY_ENTRY_IMPORT for i in e.imports if i.name}

    _, dplayx = imports(SYSWOW64 / "dplayx.dll")
    assert {"LoadLibraryA", "LoadLibraryW"} & dplayx
    pe, dpws = imports(SYSWOW64 / "dpwsockx.dll")
    assert "GetProcAddress" in dpws and "LoadLibraryA" in dpws
    img = pe.get_memory_mapped_image()
    assert b"DirectPlayNATHelpCreate\x00" in img and b"dpnathlp.dll\x00" in img
    base = pe.OPTIONAL_HEADER.ImageBase
    text = [s for s in pe.sections if s.Name.startswith(b".text")][0]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.skipdata = True
    ins = list(md.disasm(img[text.VirtualAddress:text.VirtualAddress + text.Misc_VirtualSize], base + text.VirtualAddress))
    sites = checked = 0
    for k, i in enumerate(ins):
        if not (i.mnemonic == "mov" and i.op_str.endswith("+ 0x24]")):
            continue
        window = ins[max(0, k - 6):k + 12]
        pushes = [j for j in window if j.mnemonic == "push"]
        if not any(j.op_str == "0x10" for j in pushes):      # the 16-byte response size: a QueryAddress call
            continue
        calls = [n for n, j in enumerate(window) if j.mnemonic == "call" and j.op_str in ("esi", "edi", "ebx", "eax")]
        assert calls, hex(i.address)
        after = window[calls[-1] + 1:calls[-1] + 4]
        sites += 1
        checked += any(j.mnemonic == "test" and j.op_str == "eax, eax" for j in after)
    # reply (0x...6b9f), connect (0x...2c11) and the player-address pair (0x...53e8 stream, 0x...5410 datagram); the
    # datagram query writes its response straight into the stored copy (initialised from the original, so a failed
    # query leaves it as it was) -- the others use the response only after `test eax, eax`
    assert sites >= 4, sites
    assert checked >= 3, checked
    # The enum-to-an-address site (dpwsockx 0x5df0952f on 26100): the target's port is set to 0x08BA = 47624 (stored
    # big-endian as BA 08 via `mov eax, 0x8ba / mov word ptr [x + 2], ax`), and an S_OK answer turns the target into a
    # BROADCAST (`or dword ptr [x + 4], 0xffffffff`) -- why Resolve never answers for lanjoin_core.h kEnumPort.
    broadcast = False
    for k, i in enumerate(ins):
        if i.mnemonic == "or" and i.op_str.endswith("+ 4], 0xffffffff"):
            before = ins[max(0, k - 30):k]
            sets_port = any(j.mnemonic == "mov" and j.op_str.endswith(", 0x8ba") for j in before)
            queries = any(j.mnemonic == "mov" and j.op_str.endswith("+ 0x24]") for j in before)
            broadcast = broadcast or (sets_port and queries)
    assert broadcast, "the enum site no longer looks like a port-47624 query that broadcasts on S_OK: re-check kEnumPort"
    assert 0x08BA == 47624 >> 8 | (47624 & 0xFF) << 8


# ---------------------------------------------------------------------------------------------- zero cost off TCP/IP
UIMOD_DLL = ROOT.parent / "src" / "uimod" / "build" / "Release" / "uimod.dll"
LANJOIN_CPP = ROOT.parent / "src" / "uimod" / "src" / "lanjoin.cpp"


@pytest.mark.skipif(not UIMOD_DLL.exists(), reason="uimod.dll not built")
def test_winsock_is_not_loaded_at_game_start():
    """Nothing in the game, PRACX or Thinker loads Winsock at startup; DirectPlay starts it only for TCP/IP
    multiplayer.  uimod must not change that for single-player players (third-party network hooks -- antivirus,
    VPN, 'gaming accelerator' layers -- load with Winsock): ws2_32 / iphlpapi are DELAY-loaded, and lanjoin.cpp
    calls WSAStartup only from HookDpwsockx (DirectPlay's TCP/IP provider loading)."""
    pefile = pytest.importorskip("pefile")
    pe = pefile.PE(str(UIMOD_DLL))
    static = {e.dll.decode().lower() for e in pe.DIRECTORY_ENTRY_IMPORT}
    delayed = {e.dll.decode().lower() for e in getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])}
    assert not static & {"ws2_32.dll", "wsock32.dll", "iphlpapi.dll"}, static
    assert {"ws2_32.dll", "iphlpapi.dll"} <= delayed, delayed
    src = LANJOIN_CPP.read_text(encoding="utf-8")
    body = src[src.index("void HookDpwsockx(HMODULE dpws)"):]
    body = body[:body.index("\n}\n")]
    assert src.count("WSAStartup(") == 1 and "WSAStartup(" in body
