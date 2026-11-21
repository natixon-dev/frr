#!/usr/bin/env python
# SPDX-License-Identifier: ISC
#
# Copyright (C) 2026 Maciej Barzowski
#

"""
test_bfd_isis_ipv4_only_neighbor.py: Test that IS-IS creates its BFD
session over IPv4 when the circuit runs IS-IS for IPv4 and IPv6 but the
neighbor runs it for IPv4 only.

    +----+ 192.0.2.0/30 +----+
    | r1 |--------------| r2 |
    +----+              +----+

r1 has "ip router isis" and "ipv6 router isis" on the link, r2 only
"ip router isis"; both have "isis bfd". r2 advertises no IPv6 address in
its hellos, and isisd on r1 used to wait for one forever: the adjacency
came up, but r1 created no BFD session.

The address family of the session then follows the address families of
the circuits:
- r1 removes and adds back "ipv6 router isis": the session stays on IPv4;
- r2 adds "ipv6 router isis": the session moves to IPv6 on both routers.
"""

import functools
import json
import os
import sys

import pytest

CWD = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(CWD, "../"))

# pylint: disable=C0413
from lib import topotest
from lib.common_config import step
from lib.topogen import Topogen

pytestmark = [pytest.mark.bfdd, pytest.mark.isisd]

PEER_IPV4 = {"r1": "192.0.2.2", "r2": "192.0.2.1"}


def build_topo(tgen):
    "Build function"
    for router in ("r1", "r2"):
        tgen.add_router(router)

    switch = tgen.add_switch("s1")
    switch.add_link(tgen.gears["r1"])
    switch.add_link(tgen.gears["r2"])


@pytest.fixture(scope="module")
def tgen(request):
    "Setup/Teardown the environment and provide tgen argument to tests"
    tgen = Topogen(build_topo, request.module.__name__)
    tgen.start_topology()

    for router in tgen.routers().values():
        router.load_frr_config()

    tgen.start_router()
    yield tgen
    tgen.stop_topology()


@pytest.fixture(autouse=True)
def skip_on_failure(tgen):
    if tgen.routers_have_failure():
        pytest.skip("skipped because of previous test failure")


def _check_adjacency(router):
    output = json.loads(router.vtysh_cmd("show isis neighbor json"))
    states = [
        circuit.get("state")
        for area in output.get("areas", [])
        for circuit in area.get("circuits", [])
    ]
    if states != ["Up"]:
        return "adjacency states: {}".format(states)
    return None


def _check_bfd_session(router, family):
    """The router has exactly one BFD peer, up, of the given address
    family: the IPv4 address of the neighbor, or an IPv6 link-local
    address."""
    peers = json.loads(router.vtysh_cmd("show bfd peers json"))
    if len(peers) != 1:
        return "BFD peers: {}".format(peers)
    peer = peers[0]
    if peer.get("status") != "up":
        return "BFD peer not up: {}".format(peer)
    if family == "ipv4" and peer.get("peer") != PEER_IPV4[router.name]:
        return "BFD peer not over IPv4: {}".format(peer)
    if family == "ipv6" and not peer.get("peer", "").startswith("fe80:"):
        return "BFD peer not over IPv6: {}".format(peer)
    return None


def _expect_bfd(tgen, family):
    for router in tgen.routers().values():
        test_func = functools.partial(_check_adjacency, router)
        _, result = topotest.run_and_expect(test_func, None, count=60, wait=1)
        assert result is None, "{}: {}".format(router.name, result)

        test_func = functools.partial(_check_bfd_session, router, family)
        _, result = topotest.run_and_expect(test_func, None, count=60, wait=1)
        assert result is None, "{}: {}".format(router.name, result)


def _configure(router, *commands):
    router.vtysh_cmd(
        "configure terminal\ninterface {}-eth0\n{}".format(
            router.name, "\n".join(commands)
        )
    )


def test_bfd_ipv4_only_neighbor(tgen):
    step("r1 runs IS-IS for IPv4 and IPv6, r2 for IPv4 only: BFD up over IPv4")
    _expect_bfd(tgen, "ipv4")


def test_bfd_local_ipv6_removed_and_added(tgen):
    r1 = tgen.gears["r1"]

    step("r1 removes ipv6 router isis: BFD stays up over IPv4")
    _configure(r1, "no ipv6 router isis 1")
    _expect_bfd(tgen, "ipv4")

    step("r1 adds ipv6 router isis back: BFD stays up over IPv4")
    _configure(r1, "ipv6 router isis 1")
    _expect_bfd(tgen, "ipv4")


def test_bfd_neighbor_ipv6_added(tgen):
    step("r2 adds ipv6 router isis: BFD up over IPv6 on both routers")
    _configure(tgen.gears["r2"], "ipv6 router isis 1")
    _expect_bfd(tgen, "ipv6")


def test_memory_leak(tgen):
    "Run the memory leak test and report results."
    if not tgen.is_memleak_enabled():
        pytest.skip("Memory leak test/report is disabled")

    tgen.report_memory_leaks()


if __name__ == "__main__":
    args = ["-s"] + sys.argv[1:]
    sys.exit(pytest.main(args))
