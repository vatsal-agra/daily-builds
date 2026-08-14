"""A TTL-respecting answer cache with RFC 2308 negative caching.

Positive answers expire on their own real TTL. NXDOMAIN ("this name does not
exist, for any type") is cached per-name, matching RFC 2308's actual
semantics -- a second query for a *different* record type against the same
nonexistent name is still a cache hit. NODATA ("this name exists, but not
with this type") is necessarily cached per (name, type), since the same name
can have data of other types. Both negative TTLs are bounded by
min(SOA-record-TTL, SOA.minimum) per RFC 2308 section 5.
"""

from __future__ import annotations

import time

from .consts import RCODE_NXDOMAIN
from .message import RR
from .name import Name


class Cache:
    def __init__(self):
        self._positive: dict = {}          # (Name, qtype) -> (expires_at, list[RR])
        self._nxdomain: dict = {}          # Name -> expires_at
        self._nodata: dict = {}            # (Name, qtype) -> expires_at
        self.hits = 0
        self.misses = 0

    def get_positive(self, name: Name, qtype: int, now: float | None = None):
        now = time.time() if now is None else now
        key = (name, qtype)
        entry = self._positive.get(key)
        if entry is None:
            return None
        expires_at, rrs = entry
        if now >= expires_at:
            del self._positive[key]
            return None
        self.hits += 1
        remaining = max(0, int(expires_at - now))
        return [RR(r.name, r.rtype, r.rclass, remaining, r.rdata) for r in rrs]

    def get_negative(self, name: Name, qtype: int, now: float | None = None):
        """Returns 'nxdomain', 'nodata', or None (not cached / expired)."""
        now = time.time() if now is None else now
        nx_expiry = self._nxdomain.get(name)
        if nx_expiry is not None:
            if now < nx_expiry:
                self.hits += 1
                return "nxdomain"
            del self._nxdomain[name]
        key = (name, qtype)
        nodata_expiry = self._nodata.get(key)
        if nodata_expiry is not None:
            if now < nodata_expiry:
                self.hits += 1
                return "nodata"
            del self._nodata[key]
        return None

    def record_miss(self) -> None:
        self.misses += 1

    def put_positive(self, name: Name, qtype: int, rrs: list, now: float | None = None) -> None:
        if not rrs:
            return
        now = time.time() if now is None else now
        ttl = min(r.ttl for r in rrs)
        self._positive[(name, qtype)] = (now + ttl, list(rrs))

    def _negative_ttl(self, soa_rr: RR) -> int:
        return min(soa_rr.ttl, soa_rr.rdata.minimum)

    def put_nxdomain(self, name: Name, soa_rr: RR, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._nxdomain[name] = now + self._negative_ttl(soa_rr)

    def put_nodata(self, name: Name, qtype: int, soa_rr: RR, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self._nodata[(name, qtype)] = now + self._negative_ttl(soa_rr)

    def __len__(self) -> int:
        return len(self._positive) + len(self._nxdomain) + len(self._nodata)
