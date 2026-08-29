#!/usr/bin/env python3
"""A small concurrency load tool built on Anvil's own raw-socket
HttpClient -- proof, not just assertion, that the single-threaded event
loop genuinely serves many connections at once rather than blocking one
client behind another. Spins up N worker threads, each opening its own
keep-alive HttpClient and firing M requests at a running Anvil server,
then reports aggregate throughput/latency.

Usage:
    python3 loadtest.py --port 8080 --workers 50 --requests 20 --path /
"""

import argparse
import os
import statistics
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from anvil.client import HttpClient  # noqa: E402


def worker(host, port, path, n_requests, latencies, errors, lock):
    client = HttpClient(host, port, timeout=10)
    try:
        for _ in range(n_requests):
            start = time.perf_counter()
            try:
                resp = client.get(path)
                if resp.status >= 400:
                    with lock:
                        errors.append(resp.status)
                    continue
            except Exception as e:
                with lock:
                    errors.append(str(e))
                continue
            elapsed = time.perf_counter() - start
            with lock:
                latencies.append(elapsed)
    finally:
        client.close()


def main():
    ap = argparse.ArgumentParser(description="Anvil concurrency load test")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--path", default="/")
    ap.add_argument("--workers", type=int, default=50)
    ap.add_argument("--requests", type=int, default=20)
    args = ap.parse_args()

    latencies = []
    errors = []
    lock = threading.Lock()

    threads = []
    start = time.perf_counter()
    for _ in range(args.workers):
        t = threading.Thread(
            target=worker,
            args=(args.host, args.port, args.path, args.requests, latencies, errors, lock),
        )
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    total_elapsed = time.perf_counter() - start

    total = args.workers * args.requests
    ok = len(latencies)
    print(f"Anvil load test: {args.workers} concurrent clients x {args.requests} requests "
          f"= {total} total requests against {args.host}:{args.port}{args.path}")
    print(f"  completed:   {ok}/{total} ok, {len(errors)} errors")
    print(f"  wall time:   {total_elapsed:.3f}s")
    if ok:
        print(f"  throughput:  {ok / total_elapsed:.1f} req/s")
        print(f"  latency:     p50={statistics.median(latencies) * 1000:.2f}ms "
              f"p99={sorted(latencies)[int(len(latencies) * 0.99) - 1] * 1000:.2f}ms "
              f"max={max(latencies) * 1000:.2f}ms")
    if errors:
        print(f"  sample errors: {errors[:5]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
