#!/usr/bin/env python3
"""Stand up two Anvil origin servers and a reverse proxy/load balancer in
front of them, all in one process -- a runnable demonstration of the
stretch reverse-proxy feature, not just something exercised by tests.
"""

import argparse
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anvil import Router, Server, Response, LoadBalancer  # noqa: E402


def make_backend(name, host, port):
    router = Router()

    @router.route("GET", "/")
    def health(req):
        return Response.text(f"backend {name} is healthy")

    @router.route("GET", "/whoami")
    def whoami(req):
        return Response.json({"backend": name})

    server = Server(host=host, port=port, router=router)
    server.bind()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"  backend {name} listening on http://{host}:{server.port}/")
    return server


def main():
    ap = argparse.ArgumentParser(description="Anvil reverse proxy demo")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--proxy-port", type=int, default=8888)
    args = ap.parse_args()

    print("Starting two backend Anvil servers...")
    backend_a = make_backend("A", args.host, 0)
    backend_b = make_backend("B", args.host, 0)

    lb = LoadBalancer(
        args.host, args.proxy_port,
        [(args.host, backend_a.port), (args.host, backend_b.port)],
        health_interval=2.0,
    )
    try:
        lb.start()
    except OSError as e:
        print(f"error: couldn't bind {args.host}:{args.proxy_port} -- {e}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Reverse proxy listening on http://{args.host}:{lb.port}/ "
          f"(round-robin over backends A and B)")
    print(f"  try:  curl {args.host}:{lb.port}/whoami   (repeat it -- watch it alternate)")
    try:
        lb.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
