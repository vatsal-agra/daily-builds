"""A real recursive resolver: start at the root hints, follow NS referrals
down through however many delegations it takes, using glue records where
available and resolving nameserver names itself (nested resolution) where
they aren't, until an authoritative answer (or NXDOMAIN/NODATA) comes back.
No forwarding to an upstream resolver anywhere in this file.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import transport
from .cache import Cache
from .consts import (
    TYPE_NS, TYPE_A, TYPE_CNAME, TYPE_ANY, TYPE_SOA,
    RCODE_NOERROR, RCODE_NXDOMAIN,
)
from .message import DNSMessage, Question
from .name import Name
from .trace import Trace

DEFAULT_PORT = 5391
MAX_REFERRALS = 20
MAX_CNAME_HOPS = 8


class ResolutionError(Exception):
    pass


@dataclass(frozen=True)
class RootHint:
    name: Name
    address: str


@dataclass
class ResolveResult:
    rcode: int
    answers: list
    cname_chain: list = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.rcode == RCODE_NOERROR and bool(self.answers)


def _group_by_owner_type(rrs):
    groups: dict = {}
    for rr in rrs:
        groups.setdefault((rr.name, rr.rtype), []).append(rr)
    return groups


class Resolver:
    def __init__(self, root_hints, port: int = DEFAULT_PORT, cache: Cache | None = None,
                 trace: Trace | None = None, timeout: float = 2.0):
        self.root_hints = list(root_hints)
        self.port = port
        self.cache = cache if cache is not None else Cache()
        self.trace = trace
        self.timeout = timeout
        self.queries_sent = 0
        self._in_flight: set = set()

    def resolve(self, qname: Name, qtype: int) -> ResolveResult:
        """Resolve qname/qtype, following CNAMEs across zone boundaries."""
        key = (qname, qtype)
        if key in self._in_flight:
            raise ResolutionError(f"resolution loop detected for {qname.to_text()}/{qtype}")
        self._in_flight.add(key)
        try:
            cname_chain = []
            current = qname
            seen = {qname}
            for _ in range(MAX_CNAME_HOPS):
                rcode, answers = self._resolve_iteratively(current, qtype)
                direct = [r for r in answers if r.rtype == qtype or qtype == TYPE_ANY]
                cnames = [r for r in answers if r.rtype == TYPE_CNAME]
                if direct or qtype == TYPE_CNAME or not cnames:
                    return ResolveResult(rcode=rcode, answers=answers, cname_chain=cname_chain)
                cname_chain.append(cnames[0])
                target = cnames[0].rdata.cname
                if target in seen:
                    raise ResolutionError(f"CNAME loop detected following {qname.to_text()}")
                seen.add(target)
                current = target
            raise ResolutionError(f"too many CNAME hops resolving {qname.to_text()}")
        finally:
            self._in_flight.discard(key)

    def _resolve_iteratively(self, qname: Name, qtype: int):
        neg = self.cache.get_negative(qname, qtype)
        if neg == "nxdomain":
            if self.trace:
                self.trace.cache_hit(qname, qtype, "cached NXDOMAIN")
            return RCODE_NXDOMAIN, []
        if neg == "nodata":
            if self.trace:
                self.trace.cache_hit(qname, qtype, "cached NODATA")
            return RCODE_NOERROR, []
        cached = self.cache.get_positive(qname, qtype)
        if cached is not None:
            if self.trace:
                self.trace.cache_hit(qname, qtype, f"{len(cached)} cached record(s), no query sent")
            return RCODE_NOERROR, cached
        if qtype != TYPE_CNAME:
            # A CNAME can shadow any other qtype -- a cached CNAME at this
            # name is itself a cache hit, letting the outer CNAME-following
            # loop continue resolving the target (which may itself be
            # cached) without sending a single packet.
            cached_cname = self.cache.get_positive(qname, TYPE_CNAME)
            if cached_cname is not None:
                if self.trace:
                    self.trace.cache_hit(qname, qtype, "cached CNAME, no query sent")
                return RCODE_NOERROR, cached_cname
        self.cache.record_miss()

        candidates = [(h.name, h.address) for h in self.root_hints]
        visited_servers = set()
        for _ in range(MAX_REFERRALS):
            server_name, addr = candidates[0]
            if (addr, qname, qtype) in visited_servers:
                raise ResolutionError(f"referral loop detected resolving {qname.to_text()} at {addr}")
            visited_servers.add((addr, qname, qtype))

            msg = DNSMessage(id=random.randint(0, 0xFFFF), rd=False)
            msg.questions = [Question(qname, qtype)]
            self.queries_sent += 1
            try:
                resp = transport.query(msg, addr, self.port, timeout=self.timeout)
            except (transport.QueryTimeout, transport.QueryError) as e:
                if self.trace:
                    self.trace.error(qname, qtype, f"query to {server_name.to_text()} ({addr}) failed: {e}")
                raise ResolutionError(f"query to {server_name.to_text()} ({addr}) failed: {e}")

            if self.trace:
                self.trace.query(qname, qtype, server_name, f"{addr}:{self.port}", resp)

            if resp.rcode == RCODE_NXDOMAIN:
                soa = next((r for r in resp.authority if r.rtype == TYPE_SOA), None)
                if soa is not None:
                    self.cache.put_nxdomain(qname, soa)
                return RCODE_NXDOMAIN, []

            if resp.answers:
                for (name, rtype), rrs in _group_by_owner_type(resp.answers).items():
                    self.cache.put_positive(name, rtype, rrs)
                return RCODE_NOERROR, resp.answers

            if resp.aa:
                # Authoritative, no answers: NODATA.
                soa = next((r for r in resp.authority if r.rtype == TYPE_SOA), None)
                if soa is not None:
                    self.cache.put_nodata(qname, qtype, soa)
                return RCODE_NOERROR, []

            ns_recs = [r for r in resp.authority if r.rtype == TYPE_NS]
            if not ns_recs:
                raise ResolutionError(
                    f"{server_name.to_text()} ({addr}) returned neither an answer nor a referral for "
                    f"{qname.to_text()}"
                )
            glue = {r.name: r for r in resp.additional if r.rtype == TYPE_A}
            next_candidates = []
            for ns in ns_recs:
                target = ns.rdata.nsdname
                if target in glue:
                    next_candidates.append((target, glue[target].rdata.address))
                else:
                    sub = self.resolve(target, TYPE_A)
                    if sub.success:
                        next_candidates.append((target, sub.answers[0].rdata.address))
            if not next_candidates:
                raise ResolutionError(
                    f"referral from {server_name.to_text()} ({addr}) for {qname.to_text()} had no "
                    f"usable nameserver (no glue, and none resolvable)"
                )
            candidates = next_candidates

        raise ResolutionError(f"too many referrals resolving {qname.to_text()}")
