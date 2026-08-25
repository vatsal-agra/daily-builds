"""The `skein` command-line interface.

    skein create-torrent SRC --tracker URL [-o out.torrent] [--piece-length N]
    skein tracker [--host H] [--port N]
    skein seed TORRENT DATA_FILE [--host H] [--port N] [--tracker URL]
    skein leech TORRENT DEST_FILE [--host H] [--port N] [--tracker URL]
    skein swarm SRC_FILE [--leechers N] [--piece-length N] [--out-dir DIR]
    skein viz EVENTS_JSON [-o out.html]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

from . import bencode
from . import torrent as torrentmod
from .node import Node
from .tracker import TrackerServer
from .viz import render_visualizer_html


def cmd_create_torrent(args):
    data = torrentmod.create_torrent(
        args.source, args.tracker, piece_length=args.piece_length, comment=args.comment or ""
    )
    out = args.output or (args.source + ".torrent")
    with open(out, "wb") as f:
        f.write(data)
    t = torrentmod.parse_torrent(data)
    print(f"wrote {out}")
    print(f"  name:        {t.name}")
    print(f"  size:        {t.total_length} bytes")
    print(f"  piece len:   {t.piece_length} bytes")
    print(f"  pieces:      {t.num_pieces}")
    print(f"  info hash:   {t.info_hash_hex()}")
    return 0


def cmd_tracker(args):
    srv = TrackerServer(host=args.host, port=args.port).start()
    print(f"tracker listening on {srv.url}")
    print("Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        srv.stop()
    return 0


def _write_events(node: Node, path: str | None):
    if not path:
        return
    with open(path, "w") as f:
        json.dump(node.events.snapshot(), f)


def _run_node_blocking(node: Node, label: str, events_out: str | None):
    # A real OS process running this node can be asked to shut down by
    # its parent (the `swarm` orchestrator, once every leecher is done)
    # via SIGTERM rather than an interactive Ctrl+C, so both need to lead
    # to the same clean-shutdown-and-flush-events path.
    stop_requested = threading.Event()

    def _on_sigterm(signum, frame):
        stop_requested.set()

    signal.signal(signal.SIGTERM, _on_sigterm)

    node.start()
    print(f"{label}: listening on {node.listen_host}:{node.listen_port}, "
          f"peer_id={node.peer_id.hex()[:12]}…", flush=True)
    try:
        while not stop_requested.is_set():
            stop_requested.wait(1.0)
            s = node.status()
            print(f"{label}: {s['pieces_done']}/{s['pieces_total']} pieces, "
                  f"{s['connections']} peers, up={s['uploaded']}B down={s['downloaded']}B",
                  flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()
        _write_events(node, events_out)


def cmd_seed(args):
    t = torrentmod.load_torrent_file(args.torrent)
    node = Node(t, args.data_file, args.tracker or t.announce,
                listen_host=args.host, listen_port=args.port, have_all=True, name="seed",
                choke_interval=args.choke_interval, announce_interval=args.announce_interval)
    _run_node_blocking(node, "seed", args.events_out)
    return 0


def cmd_leech(args):
    t = torrentmod.load_torrent_file(args.torrent)
    node = Node(t, args.dest_file, args.tracker or t.announce,
                listen_host=args.host, listen_port=args.port, have_all=False, name="leech",
                choke_interval=args.choke_interval, announce_interval=args.announce_interval)

    def _on_sigterm(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _on_sigterm)

    node.start()
    print(f"leech: listening on {node.listen_host}:{node.listen_port}", flush=True)
    try:
        ok = node.wait_until_complete(timeout=args.timeout)
    except KeyboardInterrupt:
        ok = node.pm.is_complete()
    node.stop()
    _write_events(node, args.events_out)
    if ok:
        print(f"download complete: {args.dest_file}")
        return 0
    print("download did not complete within timeout", file=sys.stderr)
    return 1


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_TRACKER_URL_RE = re.compile(r"tracker listening on (http://\S+)")


def _spawn(cmd, log_path):
    log_f = open(log_path, "w")
    return subprocess.Popen(
        [sys.executable, "-m", "skein.cli", *cmd],
        stdout=log_f, stderr=subprocess.STDOUT, text=True,
    ), log_f


def _wait_for_line(log_path, pattern, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(log_path):
            with open(log_path) as f:
                text = f.read()
            m = pattern.search(text)
            if m:
                return m
        time.sleep(0.05)
    raise TimeoutError(f"pattern {pattern.pattern!r} did not appear in {log_path} within {timeout}s")


def cmd_swarm(args):
    """Run a REAL local swarm: the tracker, the seeder, and every leecher
    are independent OS processes (spawned via `python -m skein.cli ...`,
    the same entry point a human would invoke by hand) that only ever
    talk to each other over real TCP sockets and one real HTTP tracker —
    nothing here is in-process simulation.
    """
    if args.leechers < 1:
        print(f"error: --leechers must be at least 1 (got {args.leechers})", file=sys.stderr)
        return 1

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    print(f"[swarm] source: {args.source} ({os.path.getsize(args.source)} bytes)")

    procs = []  # (name, Popen, log_file_handle)
    try:
        tracker_log = os.path.join(out_dir, "tracker.log")
        tproc, tlog = _spawn(["tracker", "--host", "127.0.0.1", "--port", "0"], tracker_log)
        procs.append(("tracker", tproc, tlog))
        m = _wait_for_line(tracker_log, _TRACKER_URL_RE, timeout=10)
        tracker_url = m.group(1)
        print(f"[swarm] tracker up (pid {tproc.pid}) at {tracker_url}")

        torrent_bytes = torrentmod.create_torrent(args.source, tracker_url, piece_length=args.piece_length)
        torrent_path = os.path.join(out_dir, "swarm.torrent")
        with open(torrent_path, "wb") as f:
            f.write(torrent_bytes)
        t = torrentmod.parse_torrent(torrent_bytes)
        print(f"[swarm] torrent: {t.num_pieces} pieces x {t.piece_length}B, "
              f"info_hash={t.info_hash_hex()[:16]}…")

        seed_events = os.path.join(out_dir, "seed.events.json")
        seed_log = os.path.join(out_dir, "seed.log")
        sproc, slog = _spawn(
            ["seed", torrent_path, args.source, "--tracker", tracker_url, "--events-out", seed_events,
             "--choke-interval", str(args.choke_interval), "--announce-interval", str(args.announce_interval)],
            seed_log,
        )
        procs.append(("seed", sproc, slog))
        print(f"[swarm] seed up (pid {sproc.pid})")

        leech_procs = []  # (name, Popen, log, dest, events_path)
        for i in range(args.leechers):
            dest = os.path.join(out_dir, f"leech-{i}.out")
            events_path = os.path.join(out_dir, f"leech-{i}.events.json")
            log_path = os.path.join(out_dir, f"leech-{i}.log")
            lproc, llog = _spawn(
                ["leech", torrent_path, dest, "--tracker", tracker_url,
                 "--timeout", str(args.timeout), "--events-out", events_path,
                 "--choke-interval", str(args.choke_interval), "--announce-interval", str(args.announce_interval)],
                log_path,
            )
            leech_procs.append((f"leech-{i}", lproc, llog, dest, events_path))
            procs.append((f"leech-{i}", lproc, llog))
            print(f"[swarm] {f'leech-{i}'} up (pid {lproc.pid})")

        source_hash = _sha256(args.source)
        all_ok = True
        t0 = time.time()
        for name, lproc, llog, dest, events_path in leech_procs:
            try:
                rc = lproc.wait(timeout=args.timeout + 15)
            except subprocess.TimeoutExpired:
                lproc.kill()
                rc = -1
            elapsed = time.time() - t0
            if rc != 0:
                print(f"[swarm] {name}: FAILED (exit {rc}) after {elapsed:.1f}s — see {llog.name}")
                all_ok = False
                continue
            dest_hash = _sha256(dest)
            match = dest_hash == source_hash
            all_ok &= match
            print(f"[swarm] {name}: complete in {elapsed:.1f}s, "
                  f"sha256 {'MATCHES' if match else 'MISMATCH!!'} source")

        # Give the seed process one more choke/have round so its event
        # log captures it having actually served the swarm, then stop it.
        time.sleep(args.choke_interval + 0.5)
        sproc.send_signal(signal.SIGTERM)
        sproc.wait(timeout=10)

        # Merge every process's own real event log (each process only
        # knows its own events; nothing here is synthesized).
        merged = {}
        if os.path.exists(seed_events):
            with open(seed_events) as f:
                merged["seed"] = json.load(f)
        for name, _, _, _, events_path in leech_procs:
            if os.path.exists(events_path):
                with open(events_path) as f:
                    merged[name] = json.load(f)

        events_out_path = os.path.join(out_dir, "events.json")
        with open(events_out_path, "w") as f:
            json.dump({
                "torrent": {"name": t.name, "num_pieces": t.num_pieces,
                            "piece_length": t.piece_length, "info_hash": t.info_hash_hex()},
                "peers": merged,
            }, f, indent=1)
        print(f"[swarm] event log written to {events_out_path}")

    finally:
        for name, proc, log_f in procs:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
        for name, proc, log_f in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            log_f.close()

    if all_ok:
        print("[swarm] RESULT: OK — every leecher (a separate OS process) "
              "reconstructed the file byte-for-byte")
        return 0
    print("[swarm] RESULT: FAILED", file=sys.stderr)
    return 1


def cmd_viz(args):
    with open(args.events_json) as f:
        data = json.load(f)
    html = render_visualizer_html(data)
    out = args.output or (os.path.splitext(args.events_json)[0] + ".html")
    with open(out, "w") as f:
        f.write(html)
    print(f"wrote {out}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="skein", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    ct = sub.add_parser("create-torrent", help="create a .torrent file from a source file")
    ct.add_argument("source")
    ct.add_argument("--tracker", required=True, help="tracker announce URL")
    ct.add_argument("--piece-length", type=int, default=torrentmod.DEFAULT_PIECE_LENGTH)
    ct.add_argument("-o", "--output")
    ct.add_argument("--comment")
    ct.set_defaults(func=cmd_create_torrent)

    tr = sub.add_parser("tracker", help="run a standalone HTTP tracker")
    tr.add_argument("--host", default="127.0.0.1")
    tr.add_argument("--port", type=int, default=8000)
    tr.set_defaults(func=cmd_tracker)

    sd = sub.add_parser("seed", help="seed a complete file into a swarm")
    sd.add_argument("torrent")
    sd.add_argument("data_file")
    sd.add_argument("--host", default="127.0.0.1")
    sd.add_argument("--port", type=int, default=0)
    sd.add_argument("--tracker", help="override the tracker URL in the .torrent")
    sd.add_argument("--events-out", help="write a JSON dump of this node's event log here on shutdown")
    sd.add_argument("--choke-interval", type=float, default=3.0)
    sd.add_argument("--announce-interval", type=float, default=2.0)
    sd.set_defaults(func=cmd_seed)

    lc = sub.add_parser("leech", help="download a file from a swarm")
    lc.add_argument("torrent")
    lc.add_argument("dest_file")
    lc.add_argument("--host", default="127.0.0.1")
    lc.add_argument("--port", type=int, default=0)
    lc.add_argument("--tracker", help="override the tracker URL in the .torrent")
    lc.add_argument("--timeout", type=float, default=60.0)
    lc.add_argument("--events-out", help="write a JSON dump of this node's event log here on shutdown")
    lc.add_argument("--choke-interval", type=float, default=3.0)
    lc.add_argument("--announce-interval", type=float, default=2.0)
    lc.set_defaults(func=cmd_leech)

    sw = sub.add_parser("swarm", help="run a full local tracker+seed+leechers demo")
    sw.add_argument("source")
    sw.add_argument("--leechers", type=int, default=3)
    sw.add_argument("--piece-length", type=int, default=32 * 1024)
    sw.add_argument("--out-dir", default="./skein-swarm-run")
    sw.add_argument("--timeout", type=float, default=60.0)
    sw.add_argument("--choke-interval", type=float, default=1.5)
    sw.add_argument("--announce-interval", type=float, default=1.0)
    sw.set_defaults(func=cmd_swarm)

    vz = sub.add_parser("viz", help="render an HTML visualizer from a swarm run's events.json")
    vz.add_argument("events_json")
    vz.add_argument("-o", "--output")
    vz.set_defaults(func=cmd_viz)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (torrentmod.TorrentError, bencode.BencodeError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        # Covers "file not found", "address already in use", permission
        # errors, etc. — anything a user is expected to hit by pointing
        # the CLI at a bad path or a busy port, not an internal bug.
        print(f"error: {e.strerror or e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
