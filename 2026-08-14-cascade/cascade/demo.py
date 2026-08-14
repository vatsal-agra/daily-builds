"""The `cascade demo` walkthrough: boots the fake internet, exercises every
required and stretch feature with real assertions against real answers, and
prints what happened. This is both a demo and a smoke test -- it exits
non-zero on any failure."""

from __future__ import annotations

import sys
import time

from .cache import Cache
from .consts import (
    TYPE_A, TYPE_AAAA, TYPE_CNAME, TYPE_MX, TYPE_TXT, TYPE_NS,
    RCODE_NOERROR, RCODE_NXDOMAIN, CLASS_IN,
)
from .fakenet import FakeInternet
from .message import DNSMessage, Question, RR, EDNSOptions
from .name import Name
from .rdata import TXT
from .resolver import Resolver
from . import transport
from .textfmt import fmt_rr
from .trace import Trace
from .visualizer import render_trace_html

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

_failures = []


def check(label: str, condition: bool, extra: str = "") -> None:
    ok = bool(condition)
    print(f"  [{PASS if ok else FAIL}] {label}" + (f" -- {extra}" if extra and not ok else ""))
    if not ok:
        _failures.append(label)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def run_demo(port: int = 5391) -> int:
    with FakeInternet(port=port) as net:
        time.sleep(0.25)

        # ---------------------------------------------------------------
        section("1. Authoritative nameserver -- direct queries (`dig`-style)")
        # ---------------------------------------------------------------
        def dig(server, name, qtype, rd=True):
            msg = DNSMessage(id=1, rd=rd)
            msg.questions = [Question(Name.from_text(name), qtype)]
            return transport.query(msg, server, port, timeout=2.0)

        resp = dig("127.0.0.4", "example.com.", TYPE_A)
        check("A record exact match", resp.aa and resp.rcode == RCODE_NOERROR and
              any(r.rdata.address == "93.184.216.34" for r in resp.answers))

        resp = dig("127.0.0.4", "example.com.", TYPE_AAAA)
        check("AAAA record exact match", resp.aa and
              any(r.rdata.address == "2606:2800:220:1:248:1893:25c8:1946" for r in resp.answers))

        resp = dig("127.0.0.4", "www.example.com.", TYPE_A)
        check("CNAME chased to A within the same zone",
              any(r.rtype == TYPE_CNAME for r in resp.answers) and
              any(r.rtype == TYPE_A and r.rdata.address == "93.184.216.34" for r in resp.answers))

        resp = dig("127.0.0.4", "example.com.", TYPE_MX)
        check("MX record", any(r.rdata.preference == 10 for r in resp.answers))

        resp = dig("127.0.0.4", "example.com.", TYPE_TXT)
        check("TXT record", any(r.rdata.strings == (b"v=spf1 -all",) for r in resp.answers))

        resp = dig("127.0.0.4", "nope.example.com.", TYPE_A)
        check("NXDOMAIN for a name that doesn't exist",
              resp.rcode == RCODE_NXDOMAIN and any(r.rtype == 6 for r in resp.authority))

        resp = dig("127.0.0.4", "example.com.", 99)  # an unassigned type: NODATA, not NXDOMAIN
        check("NODATA for a real name queried with an absent type",
              resp.rcode == RCODE_NOERROR and not resp.answers and
              any(r.rtype == 6 for r in resp.authority))

        resp = dig("127.0.0.5", "surprise.dev.example.com.", TYPE_A)
        check("wildcard synthesis answers an undefined subdomain",
              any(r.name.to_text() == "surprise.dev.example.com." and r.rdata.address == "127.0.0.9"
                  for r in resp.answers))

        resp = dig("127.0.0.3", "example.com.", TYPE_NS)
        check("TLD server refers (does not answer authoritatively) for a delegated name",
              not resp.aa and any(r.rtype == TYPE_NS for r in resp.authority))

        # ---------------------------------------------------------------
        section("2. Recursive resolver -- real root -> TLD -> authoritative delegation")
        # ---------------------------------------------------------------
        cache = Cache()
        trace = Trace()
        resolver = Resolver(net.root_hints(), port=port, cache=cache, trace=trace)

        result = resolver.resolve(Name.from_text("www.example.com."), TYPE_A)
        hops = [s for s in trace.steps if s.kind == "query"]
        check("full recursive resolution succeeds", result.success and
              any(r.rtype == TYPE_A and r.rdata.address == "93.184.216.34" for r in result.answers))
        check("resolution actually walked root -> TLD -> authoritative (3 real queries)",
              len(hops) == 3 and hops[0].server_addr.startswith("127.0.0.2") and
              hops[1].server_addr.startswith("127.0.0.3") and hops[2].server_addr.startswith("127.0.0.4"))
        for step in trace.steps:
            print(f"    -> {step.server_name or 'cache'} ({step.server_addr or '-'}): {step.detail}")

        trace2 = Trace()
        resolver2 = Resolver(net.root_hints(), port=port, cache=Cache(), trace=trace2)
        deep = resolver2.resolve(Name.from_text("api.dev.example.com."), TYPE_A)
        deep_hops = [s for s in trace2.steps if s.kind == "query"]
        check("second-level delegation (dev.example.com, its own glue) resolves",
              deep.success and deep.answers[0].rdata.address == "127.0.0.6" and len(deep_hops) == 4)

        neg = resolver.resolve(Name.from_text("nope.example.com."), TYPE_A)
        check("recursive resolver surfaces NXDOMAIN", neg.rcode == RCODE_NXDOMAIN and not neg.answers)

        # ---------------------------------------------------------------
        section("3. TTL-respecting cache + RFC 2308 negative caching")
        # ---------------------------------------------------------------
        before = resolver.queries_sent
        resolver.resolve(Name.from_text("www.example.com."), TYPE_A)
        check("identical repeat query is a pure cache hit (0 extra wire queries)",
              resolver.queries_sent == before, f"queries went {before} -> {resolver.queries_sent}")

        before_neg = resolver.queries_sent
        resolver.resolve(Name.from_text("nope.example.com."), TYPE_A)
        check("repeat NXDOMAIN is negative-cached (0 extra wire queries)",
              resolver.queries_sent == before_neg)

        result_ttl = resolver.resolve(Name.from_text("ticker.dev.example.com."), TYPE_A)
        check("short-TTL record fetched with its real 2s TTL",
              result_ttl.answers and result_ttl.answers[-1].ttl <= 2)
        before_ttl = resolver.queries_sent
        time.sleep(2.3)
        resolver.resolve(Name.from_text("ticker.dev.example.com."), TYPE_A)
        check("record is re-fetched over the wire once its real TTL actually expires",
              resolver.queries_sent > before_ttl)

        # ---------------------------------------------------------------
        section("4. EDNS0 + TCP fallback on truncation (stretch)")
        # ---------------------------------------------------------------
        # Inject an oversized TXT record (not part of the checked-in zone
        # file -- this is purely to force a real >512-byte response) so we
        # can observe genuine UDP truncation and a genuine TCP retry.
        example_zone = net.servers[2].zones[Name.from_text("example.com.")]
        big_name = Name.from_text("big.example.com.")
        example_zone.records[big_name] = [
            RR(big_name, TYPE_TXT, CLASS_IN, 300, TXT(tuple(b"x" * 200 for _ in range(8))))
        ]

        plain = DNSMessage(id=2, rd=False)
        plain.questions = [Question(big_name, TYPE_TXT)]
        udp_resp = transport.udp_query(plain, "127.0.0.4", port)
        check("oversized response without EDNS0 is truncated over UDP (TC=1)", udp_resp.tc)
        full_resp = transport.query(plain, "127.0.0.4", port)  # auto TCP retry on TC
        check("client transparently retries over TCP and gets the complete answer",
              not full_resp.tc and len(full_resp.answers) == 1 and
              len(full_resp.answers[0].rdata.strings) == 8)

        edns_msg = DNSMessage(id=3, rd=False, edns=EDNSOptions(udp_payload_size=4096))
        edns_msg.questions = [Question(big_name, TYPE_TXT)]
        edns_resp = transport.udp_query(edns_msg, "127.0.0.4", port)
        check("same oversized response fits in one UDP datagram once EDNS0 raises the size limit",
              not edns_resp.tc and edns_resp.edns is not None and len(edns_resp.answers) == 1)

        # ---------------------------------------------------------------
        section("5. HTML resolution-trace visualizer (stretch)")
        # ---------------------------------------------------------------
        viz_trace = Trace()
        viz_resolver = Resolver(net.root_hints(), port=port, cache=Cache(), trace=viz_trace)
        viz_result = viz_resolver.resolve(Name.from_text("mail.example.com."), TYPE_A)
        html = render_trace_html("mail.example.com.", "A", viz_trace, viz_result)
        check("visualizer HTML renders every real trace step",
              html.count("class=\"step step-") == len(viz_trace.steps) and "mail.example.com." in html)

    print()
    if _failures:
        print(f"{len(_failures)} check(s) FAILED:")
        for f in _failures:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run_demo())
