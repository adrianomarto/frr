#!/usr/bin/env python

#
# test_bgp_listen_on_multiple_addresses.py
# Part of NetDEF Topology Tests
#
# Copyright (c) 2020 by Boeing Defence Australia
# Adriano Marto Reis
#
# Permission to use, copy, modify, and/or distribute this software
# for any purpose with or without fee is hereby granted, provided
# that the above copyright notice and this permission notice appear
# in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND NETDEF DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL NETDEF BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY
# DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
# WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS
# ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE
# OF THIS SOFTWARE.
#

"""
test_bgp_listen_on_multiple_addresses.py: Test BGP daemon listening for
connections on multiple addresses.

    +------+        +------+        +------+        +------+
    |      |  IPv4  |      |  IPV6  |      | IPv4   |      |
    |  r1  |--------|  r2  |--------|  r3  |--------|  r4  |
    |      |        |      |        |      |        |      |
    +------+        +------+        +------+        +------+

  |            |                                |             |
  |  AS 1000   |            AS 2000             |   AS 3000   |
  |            |                                |             |
  +------------+--------------------------------+-------------+

The routers r2 and r3 listen for BGP connections on IPv4 and IPv6 addresses at
the same time.
"""

import os
import sys
import json
import pytest
import time


# Save the Current Working Directory to find configuration files.
CWD = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(CWD, "../"))

from lib.topogen import Topogen, TopoRouter, get_topogen
from lib.topojson import build_topo_from_json
from lib.topolog import logger
from lib.topotest import sleep
from mininet.topo import Topo


# Reads data from JSON File for topology and configuration creation.
jsonFile = "{}/bgp_listen_on_multiple_addresses.json".format(CWD)
try:
    with open(jsonFile, "r") as topoJson:
        topo = json.load(topoJson)
except IOError:
    assert False, "Could not read file {}".format(jsonFile)


class TemplateTopo(Topo):
    "Topology builder."

    def build(self, *_args, **_opts):
        "Defines the allocation and relationship between routers and switches."
        tgen = get_topogen(self)
        build_topo_from_json(tgen, topo)


def setup_module(mod):
    "Sets up the test environment."
    tgen = Topogen(TemplateTopo, mod.__name__)
    tgen.start_topology()

    # Starts zebra. That is necessary to assign the expected IP addresses to
    # the network interfaces.
    router_list = tgen.routers()
    for name, router in router_list.items():
        router.load_config(
            TopoRouter.RD_ZEBRA, os.path.join(CWD, "{}/zebra.conf".format(name))
        )
    tgen.start_router()

    listen_addresses = {
        "r1": ["10.0.1.1"],
        "r2": ["10.0.1.2", "fd00::2:2"],
        "r3": ["fd00::2:3", "10.0.3.3"],
        "r4": ["10.0.3.4"],
    }

    # Starts bgpd instances.
    router_list = tgen.routers()
    for name, router in router_list.items():

        # Makes sure that the IP address has been assigned.
        for address in listen_addresses[name]:
            _wait_for_ip_address(router, address)

        # Starts bgpd.
        listen_options = "-l " + " -l ".join(listen_addresses[name])
        command = "/usr/lib/frr/bgpd -d -f {}/{}/bgpd.conf {}".format(
            CWD, name, listen_options
        )
        logger.info("{}: {}".format(name, command))
        router.run(command)


def teardown_module(_mod):
    "Tears-down the test environment."
    tgen = get_topogen()
    router_list = tgen.routers()
    for router in router_list.values():
        router.run("kill $(cat /var/run/frr/bgpd.pid)")

    tgen = get_topogen()
    tgen.stop_topology()


def test_peering():
    "Starts bgpd on each router and checks if the routers peer-up."

    tgen = get_topogen()

    if tgen.routers_have_failure():
        pytest.skip(tgen.errors)

    # tgen.mininet_cli()

    _wait_for_peer(tgen.routers()["r1"], "10.0.1.2")
    _wait_for_peer(tgen.routers()["r2"], "10.0.1.1")
    _wait_for_peer(tgen.routers()["r2"], "fd00::2:3")
    _wait_for_peer(tgen.routers()["r3"], "fd00::2:2")
    _wait_for_peer(tgen.routers()["r3"], "10.0.3.4")
    _wait_for_peer(tgen.routers()["r4"], "10.0.3.3")


def _wait_for_peer(router, peer, timeout=2):
    """
    Waits for the BGP connection between a given router and a given peer
    (specified by its IP address) to be established. If the connection is
    not established within a given timeout, then an exception is raised. 
    """
    peer_ready = False
    start_time = time.time()
    while not peer_ready:
        try:
            summary = router.vtysh_cmd("show ip bgp summary json", isjson=True)
            assert summary["ipv4Unicast"]["peers"][peer]["state"] == "Established"
        except:
            if time.time() - start_time < timeout:
                sleep(1)
            else:
                raise
        else:
            peer_ready = True


def _wait_for_ip_address(router, address, timeout=60):
    """
    Waits for a given IP address to be assined to one of the interfaces of a
    given router. If the IP address is not assigned within a given timeout
    period (in seconds), then an exception is raised.
    """
    address_assigned = False
    start_time = time.time()
    command = "ip addr | grep -v tentative | grep {}".format(address)

    while not address_assigned and time.time() - start_time < timeout:
        output = router.run(command)
        address_assigned = output != "" or sleep(1)

    if not address_assigned:
        raise Exception("IP address {} not assigned".format(address))


if __name__ == "__main__":
    args = ["-s"] + sys.argv[1:]
    sys.exit(pytest.main(args))
