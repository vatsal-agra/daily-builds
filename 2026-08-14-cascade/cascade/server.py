"""The authoritative nameserver: answers real UDP/TCP DNS queries against
zones loaded from zone files, implementing exact-match / CNAME-chasing /
wildcard synthesis / NODATA / NXDOMAIN / delegation-referral logic per RFC
1034/1035.
"""

from __future__ import annotations

import socket
import struct
import sys
import threading

from .consts import (
    TYPE_CNAME, TYPE_ANY, TYPE_SOA, CLASS_IN,
    OPCODE_QUERY, RCODE_NOERROR, RCODE_NXDOMAIN, RCODE_FORMERR, RCODE_NOTIMP,
    RCODE_REFUSED, RCODE_SERVFAIL, CLASSIC_UDP_MAX,
)
from .message import DNSMessage, RR, EDNSOptions
from .name import Name, DNSFormatError
from .zonefile import Zone

MAX_CNAME_CHASE = 8


def _select_zone(zones: dict, qname: Name):
    best = None
    for origin, zone in zones.items():
        if qname.is_subdomain_of(origin):
            if best is None or len(origin.labels) > len(best.origin.labels):
                best = zone
    return best


def _soa_rr(zone: Zone) -> RR:
    for rr in zone.records[zone.origin]:
        if rr.rtype == TYPE_SOA:
            return rr
    raise AssertionError(f"zone {zone.origin} has no apex SOA (should be caught at load time)")


def answer_in_zone(zone: Zone, qname: Name, qtype: int, resp: DNSMessage) -> None:
    """Populate resp.{aa,rcode,answers,authority,additional} for a query
    that `zone` is responsible for (or delegates part of)."""
    cut = zone.find_zone_cut(qname)
    if cut is not None:
        cut_name, ns_recs = cut
        resp.aa = False
        resp.authority = list(ns_recs)
        resp.additional = zone.glue_for(ns_recs)
        return

    resp.aa = True
    current = qname
    seen = set()
    answers = []
    for _ in range(MAX_CNAME_CHASE):
        if current in seen:
            resp.rcode = RCODE_SERVFAIL  # CNAME loop
            resp.answers = answers
            return
        seen.add(current)
        node = zone.records.get(current)
        if node is not None:
            if qtype not in (TYPE_CNAME, TYPE_ANY):
                cnames = [r for r in node if r.rtype == TYPE_CNAME]
                if cnames:
                    answers.append(cnames[0])
                    target = cnames[0].rdata.cname
                    if target.is_subdomain_of(zone.origin):
                        current = target
                        continue
                    resp.answers = answers  # target lives outside this zone
                    return
            matches = list(node) if qtype == TYPE_ANY else [r for r in node if r.rtype == qtype]
            if matches:
                answers.extend(matches)
                resp.answers = answers
                return
            resp.answers = answers  # NODATA: name exists, not this type
            resp.authority = [_soa_rr(zone)]
            return

        # An empty non-terminal ("no data here, but something exists below
        # this name") is a *real* existing name and must be checked before
        # wildcard synthesis: RFC 1034 4.3.2/4.3.3 only lets a wildcard
        # apply when no name -- of any kind, including an empty
        # non-terminal -- already exists at the query name. Checking the
        # wildcard first would let it wrongly answer for a name that should
        # get NODATA instead. (Found by adversarial review -- see REVIEW.md #1.)
        if zone.is_empty_non_terminal(current):
            resp.answers = answers
            resp.authority = [_soa_rr(zone)]
            return

        wc = zone.wildcard_match(current)
        if wc is not None:
            synthesized = [RR(current, r.rtype, r.rclass, r.ttl, r.rdata) for r in wc]
            if qtype != TYPE_ANY:
                synthesized = [r for r in synthesized if r.rtype == qtype]
            answers.extend(synthesized)
            resp.answers = answers
            if not synthesized:
                resp.authority = [_soa_rr(zone)]
            return

        resp.rcode = RCODE_NXDOMAIN
        resp.answers = answers
        resp.authority = [_soa_rr(zone)]
        return

    resp.rcode = RCODE_SERVFAIL  # chased through MAX_CNAME_CHASE hops without resolving
    resp.answers = answers


def _servfail(query: DNSMessage) -> DNSMessage:
    resp = DNSMessage(id=query.id, qr=True, opcode=query.opcode, rd=query.rd, ra=False,
                       rcode=RCODE_SERVFAIL)
    resp.questions = list(query.questions)
    return resp


def build_response(zones: dict, query: DNSMessage) -> DNSMessage:
    resp = DNSMessage(id=query.id, qr=True, opcode=query.opcode, rd=query.rd, ra=False)
    if query.opcode != OPCODE_QUERY:
        resp.rcode = RCODE_NOTIMP
        resp.questions = list(query.questions)
        return resp
    if len(query.questions) != 1:
        resp.rcode = RCODE_FORMERR
        resp.questions = list(query.questions)
        return resp

    q = query.questions[0]
    resp.questions = [q]
    if query.edns is not None:
        resp.edns = EDNSOptions()
    if q.qclass not in (CLASS_IN,):
        resp.rcode = RCODE_REFUSED
        return resp

    zone = _select_zone(zones, q.qname)
    if zone is None:
        resp.rcode = RCODE_REFUSED
        return resp
    answer_in_zone(zone, q.qname, q.qtype, resp)
    return resp


def _recv_exact(conn: socket.socket, n: int):
    chunks = bytearray()
    while len(chunks) < n:
        chunk = conn.recv(n - len(chunks))
        if not chunk:
            return None
        chunks.extend(chunk)
    return bytes(chunks)


class AuthoritativeServer:
    """A real UDP+TCP DNS server, threaded, serving `zones` on (host, port)."""

    def __init__(self, zones: dict, host: str, port: int):
        self.zones = zones
        self.host = host
        self.port = port
        self._udp_sock = None
        self._tcp_sock = None
        self._threads = []
        self._stop = threading.Event()

    def start(self) -> None:
        self._udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._udp_sock.bind((self.host, self.port))
        # A timeout, not a blocking call: closing a socket from another
        # thread does not reliably unblock a thread parked in recvfrom()/
        # accept() on it (found empirically during Phase 5 verification --
        # stop() was joining threads that were, in practice, still alive
        # and still holding the port, so an immediate restart on the same
        # port failed with EADDRINUSE even though stop() had "finished").
        # Polling with a short timeout sidesteps relying on that platform-
        # dependent cross-thread-close behavior entirely.
        self._udp_sock.settimeout(0.5)

        try:
            self._tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._tcp_sock.bind((self.host, self.port))
            self._tcp_sock.listen(16)
            self._tcp_sock.settimeout(0.5)
        except OSError:
            # Don't leak the UDP socket we already opened if the TCP bind
            # fails (e.g. port already in use). Found by adversarial review
            # while fixing REVIEW.md #2/#4.
            self._udp_sock.close()
            self._udp_sock = None
            raise

        t_udp = threading.Thread(target=self._udp_loop, daemon=True, name=f"cascade-udp-{self.port}")
        t_tcp = threading.Thread(target=self._tcp_loop, daemon=True, name=f"cascade-tcp-{self.port}")
        t_udp.start()
        t_tcp.start()
        self._threads = [t_udp, t_tcp]

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=3.0)  # both loops poll _stop at least every 0.5s
        for sock in (self._udp_sock, self._tcp_sock):
            try:
                if sock is not None:
                    sock.close()
            except OSError:
                pass

    def _udp_loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self._udp_sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                query = DNSMessage.from_wire(data)
            except DNSFormatError:
                continue  # malformed wire bytes: real servers drop these silently, not crash
            try:
                resp = build_response(self.zones, query)
                max_size = resp.edns.udp_payload_size if resp.edns is not None else CLASSIC_UDP_MAX
                wire = resp.to_wire(max_size=max_size)
            except Exception as e:
                # A bug anywhere in answer-building must not take the whole
                # listener down for every future client (found by
                # adversarial review -- see REVIEW.md #2): answer SERVFAIL
                # for *this* query and keep serving everyone else.
                print(f"cascade: internal error answering query, returning SERVFAIL: {e}",
                      file=sys.stderr)
                wire = _servfail(query).to_wire()
            try:
                self._udp_sock.sendto(wire, addr)
            except OSError:
                pass

    def _tcp_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, addr = self._tcp_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_tcp, args=(conn,), daemon=True).start()

    def _handle_tcp(self, conn: socket.socket) -> None:
        try:
            with conn:
                conn.settimeout(5.0)
                length_bytes = _recv_exact(conn, 2)
                if length_bytes is None:
                    return
                (length,) = struct.unpack("!H", length_bytes)
                data = _recv_exact(conn, length)
                if data is None:
                    return
                try:
                    query = DNSMessage.from_wire(data)
                except DNSFormatError:
                    return  # malformed wire bytes: just drop the connection
                try:
                    resp = build_response(self.zones, query)
                    wire = resp.to_wire()  # no 512-byte cap over TCP
                except Exception as e:
                    # Same reasoning as _udp_loop (REVIEW.md #2): a bug in
                    # answer-building shouldn't just vanish -- SERVFAIL for
                    # this connection so the client gets a real response.
                    print(f"cascade: internal error answering TCP query, returning SERVFAIL: {e}",
                          file=sys.stderr)
                    wire = _servfail(query).to_wire()
                conn.sendall(struct.pack("!H", len(wire)) + wire)
        except (OSError, socket.timeout):
            pass
