"""Boots Cascade's self-contained "fake internet" -- a root server, a `.com`
TLD server, and two authoritative servers, each a real `AuthoritativeServer`
bound to its own 127.0.0.0/8 loopback address (127.0.0.0/8 is *entirely*
loopback on Linux, so distinct addresses can each bind the same port
simultaneously) -- so recursive resolution can be demonstrated end-to-end
over real UDP/TCP without any internet access.
"""

from __future__ import annotations

import os

from .name import Name
from .resolver import RootHint, DEFAULT_PORT
from .server import AuthoritativeServer
from .zonefile import Zone

ZONES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "zones")

# (bind address, zone file, zone origin)
ZONE_SPECS = [
    ("127.0.0.2", "root.zone", "."),
    ("127.0.0.3", "com.zone", "com."),
    ("127.0.0.4", "example.com.zone", "example.com."),
    ("127.0.0.5", "dev.example.com.zone", "dev.example.com."),
]

ROOT_SERVER_NAME = Name.from_text("a.root-servers.cascade.")
ROOT_SERVER_ADDR = "127.0.0.2"


class FakeInternet:
    def __init__(self, zones_dir: str = ZONES_DIR, port: int = DEFAULT_PORT):
        self.port = port
        self.servers = []
        for addr, filename, origin_text in ZONE_SPECS:
            origin = Name.from_text(origin_text)
            zone = Zone.from_file(os.path.join(zones_dir, filename), origin)
            self.servers.append(AuthoritativeServer({zone.origin: zone}, addr, port))

    def start(self) -> "FakeInternet":
        for s in self.servers:
            s.start()
        return self

    def stop(self) -> None:
        for s in self.servers:
            s.stop()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def root_hints(self):
        return [RootHint(ROOT_SERVER_NAME, ROOT_SERVER_ADDR)]
