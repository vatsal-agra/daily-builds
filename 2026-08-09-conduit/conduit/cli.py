"""Conduit CLI: `python3 -m conduit.cli <subcommand>`.

Subcommands:
    serve   Start a Conduit-backed HTTP server plus a TCP<->Conduit bridge
            so a real browser or curl can reach it, optionally through a
            simulated lossy network.
    demo    End-to-end showcase: HTTP over Conduit through a lossy netsim,
            hit by real curl, plus a conduit-cp file transfer — everything
            this project claims, exercised in one run, with a pass/fail
            verdict and an optional HTML trace report.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

from conduit.api import Listener
from conduit.bridge import TcpToConduitBridge
from conduit.netsim import NetworkSimulator
from httpd.server import HttpServer
from httpd.static import StaticFileHandler
from viz.trace import TraceRecorder
from viz.report import render_to_file


def cmd_serve(args):
    recorder = TraceRecorder() if args.report else None
    server_trace = recorder.tracer("server") if recorder else None
    netsim_trace = recorder.tracer("netsim") if recorder else None

    listener = Listener((args.host, 0), trace=server_trace)
    server = HttpServer(listener, StaticFileHandler(args.dir))
    server.start()

    target_addr = listener.local_addr
    sim = None
    if args.loss or args.dup or args.reorder:
        sim = NetworkSimulator(
            (args.host, 0), listener.local_addr, loss=args.loss, dup_prob=args.dup,
            reorder_prob=args.reorder, delay=args.delay, jitter=args.jitter,
            seed=args.seed, trace=netsim_trace,
        )
        target_addr = sim.local_addr
        print(f"netsim active: loss={args.loss} dup={args.dup} reorder={args.reorder}")

    try:
        bridge = TcpToConduitBridge((args.host, args.port), target_addr, trace=None)
    except OSError as exc:
        print(f"conduit: could not bind {args.host}:{args.port}: {exc}", file=sys.stderr)
        if sim:
            sim.close()
        server.stop()
        listener.close()
        return 1
    print(f"serving {os.path.abspath(args.dir)} — http://{args.host}:{bridge.local_addr[1]}/")
    print("(this is a real TCP port bridged into a Conduit connection — curl/browser both work)")
    print("Ctrl-C to stop")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.close()
        if sim:
            sim.close()
        server.stop()
        listener.close()
        if recorder and args.report:
            render_to_file(recorder.events, args.report, title="Conduit serve session trace")
            print(f"report written to {args.report}")
    return 0


def _curl(url, max_time=20):
    return subprocess.run(
        [shutil.which("curl") or "curl", "-sS", "--max-time", str(max_time), url],
        capture_output=True, text=True,
    )


def cmd_demo(args):
    recorder = TraceRecorder()
    ok = True

    site_dir = tempfile.mkdtemp(prefix="conduit-demo-site-")
    try:
        page = "<!doctype html><h1>Conduit end-to-end demo</h1>" + ("data " * 4000)
        with open(os.path.join(site_dir, "index.html"), "w") as f:
            f.write(page)

        listener = Listener(("127.0.0.1", 0), trace=recorder.tracer("server"))
        server = HttpServer(listener, StaticFileHandler(site_dir))
        server.start()

        print("== HTTP-over-Conduit, real curl, through a lossy netsim ==")
        scenarios = [
            ("clean", dict(loss=0.0, dup_prob=0.0, reorder_prob=0.0)),
            ("moderate loss", dict(loss=0.05, dup_prob=0.02, reorder_prob=0.05, seed=1)),
            ("harsh", dict(loss=0.12, dup_prob=0.04, reorder_prob=0.10, seed=2)),
        ]
        for name, netsim_kwargs in scenarios:
            sim = NetworkSimulator(
                ("127.0.0.1", 0), listener.local_addr, reorder_delay=0.02,
                delay=0.003, jitter=0.002, trace=recorder.tracer("netsim"), **netsim_kwargs,
            )
            bridge = TcpToConduitBridge(("127.0.0.1", 0), sim.local_addr, trace=recorder.tracer("client"))
            result = _curl(f"http://{bridge.local_addr[0]}:{bridge.local_addr[1]}/", max_time=30)
            passed = result.returncode == 0 and result.stdout == page
            ok = ok and passed
            print(f"  [{'PASS' if passed else 'FAIL'}] {name} "
                  f"(netsim: {sim.stats}) curl_rc={result.returncode}")
            bridge.close()
            sim.close()
        server.stop()
        listener.close()
    finally:
        shutil.rmtree(site_dir, ignore_errors=True)

    print()
    print("== conduit-cp reliable file transfer through a lossy network ==")
    from tools.conduit_cp import run_local_demo
    demo_dir = tempfile.mkdtemp(prefix="conduit-demo-cp-")
    try:
        src_path = os.path.join(demo_dir, "payload.bin")
        with open(src_path, "wb") as f:
            f.write(os.urandom(200_000))
        out_dir = os.path.join(demo_dir, "out")
        os.makedirs(out_dir)
        result = run_local_demo(
            src_path, out_dir, loss=0.07, dup_prob=0.02, reorder_prob=0.06,
            seed=42, recorder=recorder,
        )
        send_size, send_digest = result["send"]
        recv_path, recv_size, recv_digest = result["recv"]
        cp_ok = send_digest == recv_digest and send_size == recv_size
        ok = ok and cp_ok
        print(f"  [{'PASS' if cp_ok else 'FAIL'}] {send_size} bytes, "
              f"sha256 match={send_digest == recv_digest}, netsim: {result['netsim_stats']}")
    finally:
        shutil.rmtree(demo_dir, ignore_errors=True)

    if args.report:
        render_to_file(
            recorder.events, args.report,
            title="Conduit end-to-end demo trace",
            subtitle="HTTP-over-Conduit (3 netsim scenarios) + conduit-cp, all in one run",
        )
        print(f"\nreport written to {args.report}")

    print()
    print("RESULT:", "ALL PASSED" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog="conduit", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="serve a directory over HTTP-over-Conduit + a TCP bridge")
    p_serve.add_argument("dir")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8080, help="real TCP port for curl/browsers")
    p_serve.add_argument("--loss", type=float, default=0.0)
    p_serve.add_argument("--dup", type=float, default=0.0)
    p_serve.add_argument("--reorder", type=float, default=0.0)
    p_serve.add_argument("--delay", type=float, default=0.0)
    p_serve.add_argument("--jitter", type=float, default=0.0)
    p_serve.add_argument("--seed", type=int, default=None)
    p_serve.add_argument("--report", metavar="OUT.html", default=None)

    p_demo = sub.add_parser("demo", help="run the full end-to-end showcase")
    p_demo.add_argument("--report", metavar="OUT.html", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        if not os.path.isdir(args.dir):
            print(f"conduit: {args.dir!r} is not a directory", file=sys.stderr)
            return 1
        for prob_name in ("loss", "dup", "reorder"):
            if not (0.0 <= getattr(args, prob_name) <= 1.0):
                print(f"conduit: --{prob_name} must be between 0 and 1", file=sys.stderr)
                return 1
        if not (1 <= args.port <= 65535):
            print(f"conduit: --port must be between 1 and 65535", file=sys.stderr)
            return 1
        return cmd_serve(args)
    elif args.cmd == "demo":
        return cmd_demo(args)


if __name__ == "__main__":
    sys.exit(main())
