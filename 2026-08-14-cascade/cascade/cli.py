"""Cascade's command-line interface: `serve`, `dig`, `resolve`, `demo`, `viz`."""

from __future__ import annotations

import argparse
import sys
import time

from .cache import Cache
from .consts import NAME_TO_TYPE, TYPE_NAMES, RCODE_NOERROR, RCODE_NXDOMAIN
from .fakenet import FakeInternet
from .message import DNSMessage, Question
from .name import Name, DNSFormatError
from .resolver import Resolver, ResolutionError
from .server import AuthoritativeServer
from . import transport
from .textfmt import fmt_message
from .trace import Trace
from .visualizer import render_trace_html
from .zonefile import Zone, ZoneFileError


def _qtype(text: str) -> int:
    upper = text.upper()
    if upper not in NAME_TO_TYPE:
        valid = ", ".join(sorted(NAME_TO_TYPE))
        raise argparse.ArgumentTypeError(f"unknown record type {text!r} (valid: {valid})")
    return NAME_TO_TYPE[upper]


def cmd_serve(args) -> int:
    # Zone-file and bind errors are left to propagate to main()'s single
    # error boundary, so every command reports failures the same way.
    origin = Name.from_text(args.origin)
    zone = Zone.from_file(args.zonefile, origin, default_ttl=args.default_ttl)
    server = AuthoritativeServer({zone.origin: zone}, args.host, args.port)
    server.start()
    print(f"cascade: serving {zone.origin.to_text()} ({len(zone.records)} names) "
          f"on {args.host}:{args.port} (UDP+TCP) -- Ctrl-C to stop")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\ncascade: shutting down")
        server.stop()
    return 0


def cmd_dig(args) -> int:
    msg = DNSMessage(id=int(time.time()) & 0xFFFF, rd=not args.no_rd)
    msg.questions = [Question(Name.from_text(args.name), args.type)]
    try:
        start = time.time()
        resp = transport.query(msg, args.server, args.port, timeout=args.timeout, use_tcp=args.tcp)
        elapsed_ms = (time.time() - start) * 1000
    except (transport.QueryTimeout, transport.QueryError) as e:
        print(f"cascade dig: {e}", file=sys.stderr)
        return 1
    print(fmt_message(resp, title=f";; cascade dig @{args.server}:{args.port} "
                                   f"{args.name} {TYPE_NAMES.get(args.type, args.type)}"))
    print(f"\n;; Query time: {elapsed_ms:.1f} msec")
    return 0


def cmd_resolve(args) -> int:
    with FakeInternet(port=args.port) as net:
        time.sleep(0.2)
        cache = Cache()
        trace = Trace() if (args.trace or args.viz) else None
        resolver = Resolver(net.root_hints(), port=net.port, cache=cache, trace=trace)
        try:
            result = resolver.resolve(Name.from_text(args.name), args.type)
        except ResolutionError as e:
            print(f"cascade resolve: {e}", file=sys.stderr)
            return 1

        if args.trace and trace is not None:
            print(f";; resolution trace for {args.name} {TYPE_NAMES.get(args.type, args.type)}:")
            for i, step in enumerate(trace.steps, 1):
                where = f"{step.server_name} ({step.server_addr})" if step.server_name else "cache"
                print(f"  [{i}] {step.kind:9s} {where:38s} {step.detail}")
            print()

        from .textfmt import rcode_name
        print(f";; status: {rcode_name(result.rcode)}, {len(result.answers)} answer(s), "
              f"{resolver.queries_sent} quer{'y' if resolver.queries_sent == 1 else 'ies'} sent on the wire")
        for rr in result.answers:
            from .textfmt import fmt_rr
            print(fmt_rr(rr))

        if args.viz and trace is not None:
            html = render_trace_html(args.name, TYPE_NAMES.get(args.type, str(args.type)), trace, result)
            with open(args.viz, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"\n;; wrote resolution-trace visualizer to {args.viz}")
    # Like real `dig`: a clean negative answer (NXDOMAIN) is not a tool
    # failure and exits 0; anything else unusual (SERVFAIL, ...) exits 2.
    return 0 if result.rcode in (RCODE_NOERROR, RCODE_NXDOMAIN) else 2


def cmd_viz(args) -> int:
    with FakeInternet(port=args.port) as net:
        time.sleep(0.2)
        cache = Cache()
        trace = Trace()
        resolver = Resolver(net.root_hints(), port=net.port, cache=cache, trace=trace)
        try:
            result = resolver.resolve(Name.from_text(args.name), args.type)
        except ResolutionError as e:
            print(f"cascade viz: {e}", file=sys.stderr)
            return 1
        html = render_trace_html(args.name, TYPE_NAMES.get(args.type, str(args.type)), trace, result)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"cascade viz: wrote {args.out}")
    return 0


def cmd_demo(args) -> int:
    from .demo import run_demo
    return run_demo(port=args.port)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cascade", description="A DNS resolver and authoritative nameserver, from the wire format up.")
    sub = p.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="serve a zone file as an authoritative nameserver")
    p_serve.add_argument("zonefile")
    p_serve.add_argument("--origin", required=True, help="zone origin, e.g. example.com.")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=5391)
    p_serve.add_argument("--default-ttl", type=int, default=None)
    p_serve.set_defaults(func=cmd_serve)

    p_dig = sub.add_parser("dig", help="send one query to a specific server (like `dig @server`)")
    p_dig.add_argument("name")
    p_dig.add_argument("type", type=_qtype, nargs="?", default=NAME_TO_TYPE["A"])
    p_dig.add_argument("--server", default="127.0.0.1")
    p_dig.add_argument("--port", type=int, default=5391)
    p_dig.add_argument("--tcp", action="store_true")
    p_dig.add_argument("--no-rd", action="store_true", help="clear the Recursion Desired bit")
    p_dig.add_argument("--timeout", type=float, default=2.0)
    p_dig.set_defaults(func=cmd_dig)

    p_resolve = sub.add_parser("resolve", help="fully recursively resolve a name against Cascade's built-in fake internet")
    p_resolve.add_argument("name")
    p_resolve.add_argument("type", type=_qtype, nargs="?", default=NAME_TO_TYPE["A"])
    p_resolve.add_argument("--trace", action="store_true", help="print every hop of the resolution")
    p_resolve.add_argument("--viz", metavar="FILE", help="also write an HTML resolution-trace visualizer")
    p_resolve.add_argument("--port", type=int, default=5391)
    p_resolve.set_defaults(func=cmd_resolve)

    p_viz = sub.add_parser("viz", help="resolve a name and write an HTML resolution-trace visualizer")
    p_viz.add_argument("name")
    p_viz.add_argument("type", type=_qtype, nargs="?", default=NAME_TO_TYPE["A"])
    p_viz.add_argument("-o", "--out", default="cascade-trace.html")
    p_viz.add_argument("--port", type=int, default=5391)
    p_viz.set_defaults(func=cmd_viz)

    p_demo = sub.add_parser("demo", help="run the full end-to-end feature walkthrough")
    p_demo.add_argument("--port", type=int, default=5391)
    p_demo.set_defaults(func=cmd_demo)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (DNSFormatError, ZoneFileError, OSError, ResolutionError,
            transport.QueryTimeout, transport.QueryError) as e:
        # Expected, user-triggerable failures (bad name, bad zone file, port
        # already in use, unreachable server, ...) get a clean one-line
        # message instead of a raw traceback. Anything else is a genuine
        # Cascade bug and should keep surfacing its full traceback -- see
        # REVIEW.md #4.
        print(f"cascade: error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
