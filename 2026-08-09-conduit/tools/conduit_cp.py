"""conduit-cp: a reliable file-transfer tool built directly on
ConduitSocket — no HTTP layer, no bridge, just the transport doing its
one real job: get bytes from A to B intact over an unreliable network.

Wire format (all integers big-endian, application-level framing on top
of Conduit's already-reliable byte stream):

    8 bytes   name_len
    N bytes   utf-8 filename (metadata only; receiver picks its own path)
    8 bytes   content_len
    content_len bytes   file content
    32 bytes  SHA-256 of the content

The trailing checksum is deliberately redundant with Conduit's own
per-segment checksums — it verifies the *entire application-level
pipe* end to end (framing, buffering, disk I/O), not just that no single
segment was corrupted in transit.
"""

import hashlib
import os
import struct
import sys
import time

from conduit.api import Listener, connect
from conduit.netsim import NetworkSimulator
from conduit.transport import ConduitError

_LEN_FMT = "!Q"
_LEN_SIZE = struct.calcsize(_LEN_FMT)


def _send_exact_progress(conn, data: bytes, on_progress=None):
    conn.sendall(data)
    if on_progress:
        on_progress(len(data), len(data))


def send_file(conn, path: str, chunk_size=65536, on_progress=None):
    """Stream `path` over an already-connected ConduitSocket."""
    name = os.path.basename(path)
    name_b = name.encode("utf-8")
    size = os.path.getsize(path)

    conn.sendall(struct.pack(_LEN_FMT, len(name_b)) + name_b)
    conn.sendall(struct.pack(_LEN_FMT, size))

    hasher = hashlib.sha256()
    sent = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            conn.sendall(chunk)
            hasher.update(chunk)
            sent += len(chunk)
            if on_progress:
                on_progress(sent, size)
    conn.sendall(hasher.digest())
    return size, hasher.hexdigest()


def recv_file(conn, out_dir: str, on_progress=None):
    """Receive one file sent by `send_file` over an already-accepted
    ConduitSocket, writing it into `out_dir`. Returns (path, size, sha256_hex)."""
    name_len = struct.unpack(_LEN_FMT, conn.recv_exact(_LEN_SIZE, timeout=30.0))[0]
    if name_len == 0 or name_len > 4096:
        raise ValueError(f"implausible filename length {name_len}")
    name = conn.recv_exact(name_len, timeout=30.0).decode("utf-8", errors="replace")
    name = os.path.basename(name) or "received.bin"  # never trust a path from the wire

    size = struct.unpack(_LEN_FMT, conn.recv_exact(_LEN_SIZE, timeout=30.0))[0]
    out_path = os.path.join(out_dir, name)

    hasher = hashlib.sha256()
    remaining = size
    with open(out_path, "wb") as f:
        while remaining > 0:
            chunk = conn.recv(min(65536, remaining), timeout=60.0)
            if not chunk:
                raise ConnectionError(f"peer closed after {size - remaining}/{size} bytes")
            f.write(chunk)
            hasher.update(chunk)
            remaining -= len(chunk)
            if on_progress:
                on_progress(size - remaining, size)

    expected_digest = conn.recv_exact(32, timeout=10.0)
    got_digest = hasher.digest()
    if expected_digest != got_digest:
        raise ValueError(
            f"checksum mismatch: sender says {expected_digest.hex()}, got {got_digest.hex()}"
        )
    return out_path, size, got_digest.hex()


def _progress_printer(label, step_pct=10):
    # Two of these can run concurrently (send + recv, in the single-process
    # demo) writing to the same stdout — a carriage-return-redrawn bar from
    # both at once just interleaves into garbage, so this prints throttled,
    # complete lines instead: readable whether there's one writer or two.
    start = time.monotonic()
    last_reported = [-1]

    def report(done, total):
        pct = 100.0 * done / total if total else 100.0
        bucket = int(pct // step_pct)
        if bucket == last_reported[0] and done < total:
            return
        last_reported[0] = bucket
        elapsed = max(1e-6, time.monotonic() - start)
        rate = done / elapsed / 1024
        print(f"{label}: {pct:5.1f}%  {done:>10d}/{total:<10d} bytes  {rate:7.1f} KiB/s", flush=True)

    return report


def run_send(path, host, port, timeout=15.0, trace=None):
    conn = connect((host, port), timeout=timeout, trace=trace)
    try:
        size, digest = send_file(conn, path, on_progress=_progress_printer("send"))
    finally:
        conn.close()
    return size, digest


def run_recv(bind_host, bind_port, out_dir, timeout=None, trace=None):
    listener = Listener((bind_host, bind_port), trace=trace)
    try:
        print(f"conduit-cp: listening on {listener.local_addr[0]}:{listener.local_addr[1]}")
        conn = listener.accept(timeout=timeout)
        try:
            path, size, digest = recv_file(conn, out_dir, on_progress=_progress_printer("recv"))
        finally:
            conn.close()
        return path, size, digest
    finally:
        listener.close()


def run_local_demo(path, out_dir, loss=0.05, dup_prob=0.02, reorder_prob=0.05,
                    reorder_delay=0.02, delay=0.003, jitter=0.002, seed=None, recorder=None):
    """Single-process demo: sender and receiver on loopback, routed
    through a NetworkSimulator, for exercising conduit-cp without two
    separate machines/processes. Pass a `viz.trace.TraceRecorder` as
    `recorder` to capture a side-tagged event log for the HTML report."""
    import threading

    client_trace = recorder.tracer("client") if recorder else None
    server_trace = recorder.tracer("server") if recorder else None
    netsim_trace = recorder.tracer("netsim") if recorder else None

    listener = Listener(("127.0.0.1", 0), trace=server_trace)
    sim = NetworkSimulator(
        ("127.0.0.1", 0), listener.local_addr, loss=loss, dup_prob=dup_prob,
        reorder_prob=reorder_prob, reorder_delay=reorder_delay, delay=delay,
        jitter=jitter, seed=seed, trace=netsim_trace,
    )
    result = {}

    def receiver():
        conn = listener.accept(timeout=15.0)
        try:
            result["recv"] = recv_file(conn, out_dir, on_progress=_progress_printer("recv"))
        finally:
            conn.close()

    t = threading.Thread(target=receiver)
    t.start()
    time.sleep(0.05)  # let the listener's accept() call land before we connect

    conn = connect(sim.local_addr, timeout=15.0, trace=client_trace)
    try:
        result["send"] = send_file(conn, path, on_progress=_progress_printer("send"))
    finally:
        conn.close()
    t.join(timeout=60.0)

    sim.close()
    listener.close()
    result["netsim_stats"] = sim.stats
    return result


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(prog="conduit-cp", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_send = sub.add_parser("send", help="send a file to a listening conduit-cp receiver")
    p_send.add_argument("file")
    p_send.add_argument("host")
    p_send.add_argument("port", type=int)

    p_recv = sub.add_parser("recv", help="receive one file and exit")
    p_recv.add_argument("bind_host")
    p_recv.add_argument("bind_port", type=int)
    p_recv.add_argument("out_dir")

    p_demo = sub.add_parser("demo", help="single-process demo through a simulated lossy network")
    p_demo.add_argument("file")
    p_demo.add_argument("out_dir")
    p_demo.add_argument("--loss", type=float, default=0.05)
    p_demo.add_argument("--dup", type=float, default=0.02)
    p_demo.add_argument("--reorder", type=float, default=0.05)
    p_demo.add_argument("--seed", type=int, default=None)
    p_demo.add_argument("--report", metavar="OUT.html", default=None,
                         help="also render an interactive HTML trace report to this path")

    args = parser.parse_args(argv)

    if args.cmd in ("send", "demo") and not os.path.isfile(args.file):
        print(f"conduit-cp: {args.file!r} is not a file", file=sys.stderr)
        return 1
    for prob_name in ("loss", "dup", "reorder"):
        if hasattr(args, prob_name) and not (0.0 <= getattr(args, prob_name) <= 1.0):
            print(f"conduit-cp: --{prob_name} must be between 0 and 1", file=sys.stderr)
            return 1

    try:
        return _dispatch(args)
    except FileNotFoundError as exc:
        print(f"conduit-cp: {exc}", file=sys.stderr)
        return 1
    except (ConnectionError, OSError, ConduitError) as exc:
        print(f"conduit-cp: connection failed: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"conduit-cp: {exc}", file=sys.stderr)
        return 1


def _dispatch(args):
    if args.cmd == "send":
        size, digest = run_send(args.file, args.host, args.port)
        print(f"sent {size} bytes, sha256={digest}")
    elif args.cmd == "recv":
        os.makedirs(args.out_dir, exist_ok=True)
        path, size, digest = run_recv(args.bind_host, args.bind_port, args.out_dir)
        print(f"received {size} bytes -> {path}, sha256={digest}")
    elif args.cmd == "demo":
        os.makedirs(args.out_dir, exist_ok=True)
        recorder = None
        if args.report:
            from viz.trace import TraceRecorder
            recorder = TraceRecorder()
        result = run_local_demo(
            args.file, args.out_dir, loss=args.loss, dup_prob=args.dup,
            reorder_prob=args.reorder, seed=args.seed, recorder=recorder,
        )
        send_size, send_digest = result["send"]
        recv_path, recv_size, recv_digest = result["recv"]
        ok = send_digest == recv_digest and send_size == recv_size
        print(f"sent {send_size} bytes (sha256={send_digest})")
        print(f"received {recv_size} bytes -> {recv_path} (sha256={recv_digest})")
        if args.report:
            from viz.report import render_to_file
            render_to_file(
                recorder.events, args.report,
                title="conduit-cp transfer trace",
                subtitle=f"{args.file} -> {recv_path}  (loss={args.loss}, dup={args.dup}, reorder={args.reorder})",
            )
            print(f"report written to {args.report}")
        print(f"netsim stats: {result['netsim_stats']}")
        print("MATCH" if ok else "MISMATCH — DATA CORRUPTION")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
