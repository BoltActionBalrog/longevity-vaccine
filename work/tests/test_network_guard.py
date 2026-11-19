"""The suite is hermetic (user 2026-11-15): conftest refuses and records any connection a test makes to another host,
in this process (socket.connect) and in the children it starts (their HTTP(S) proxy is conftest's _NetSink), and the
test that tried fails. These pin the guard itself; each clears what it recorded so that its own teardown passes."""
from __future__ import annotations

import os
import socket
import subprocess
import sys

import pytest

import conftest

pytestmark = pytest.mark.skipif(bool(os.environ.get("LONGEVITY_NET_TESTS")), reason="live network tests opted in")


def test_a_socket_to_another_host_is_refused_and_recorded():
    s = socket.socket()
    try:
        with pytest.raises(OSError, match="blocked by the test suite"):
            s.connect(("93.184.216.34", 443))
    finally:
        s.close()
    assert conftest._NET_TRIES == [("93.184.216.34", 443)]
    conftest._NET_TRIES.clear()


def test_this_machine_is_still_reachable():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    c = socket.socket()
    try:
        c.connect(srv.getsockname())
    finally:
        c.close()
        srv.close()
    assert conftest._NET_TRIES == []


def test_a_child_process_reaches_the_sink_never_the_real_host():
    seen = len(conftest._SINK.requests)
    code = ("import urllib.request\n"
            "try:\n"
            "    urllib.request.urlopen('https://longevitymods.com/vaccine/manifest.json', timeout=10)\n"
            "except Exception as e:\n"
            "    print(type(e).__name__)\n")
    p = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60,
                       env=dict(os.environ))
    new = conftest._SINK.requests[seen:]
    assert new == ["CONNECT longevitymods.com:443 HTTP/1.1"], (new, p.stdout, p.stderr)
    del conftest._SINK.requests[seen:]
