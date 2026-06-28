"""
Strata CLI — interactive REPL and benchmarks for the LSM-tree key-value store.

Subcommands:
  repl   PATH                  — interactive REPL
  get    PATH KEY               — get a key
  put    PATH KEY VALUE         — set a key
  del    PATH KEY               — delete a key
  scan   PATH [--start S] [--end E]  — scan key range
  compact PATH                 — trigger manual compaction
  info   PATH                  — show level statistics
  bench  PATH [--n N] [--mode MODE]  — throughput benchmark

In the REPL, commands are:
  get KEY
  put KEY VALUE
  del KEY
  scan [START] [END]
  snap                         — create a snapshot, return snap-id
  snapget SNAP_ID KEY          — get at snapshot
  batch                        — start a write batch (then put/del/end)
  compact
  info
  help
  quit / exit
"""

import argparse
import os
import sys
import time
import random
import string

# Import DB from the package
from .db import DB, Options
from .batch import WriteBatch
from .snapshot import Snapshot


def _open_db(path: str) -> DB:
    return DB.open(path)


def _encode_key(s: str) -> bytes:
    return s.encode()


def _encode_val(s: str) -> bytes:
    return s.encode()


def _decode(b: bytes) -> str:
    try:
        return b.decode()
    except UnicodeDecodeError:
        return b.hex()


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def cmd_repl(args):
    db = _open_db(args.path)
    snapshots: dict = {}  # id → Snapshot
    snap_counter = 0
    batch: list = []  # (type, key, value) when inside a batch
    in_batch = False

    print(f"Strata REPL — database at {args.path}")
    print("Type 'help' for available commands.\n")

    try:
        while True:
            try:
                if in_batch:
                    line = input("batch> ").strip()
                else:
                    line = input("strata> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line or line.startswith("#"):
                continue

            parts = line.split(None, 2)
            cmd = parts[0].lower()

            try:
                if cmd in ("quit", "exit", "q"):
                    break

                elif cmd == "help":
                    print("""Commands:
  put KEY VALUE     — store a key-value pair
  get KEY           — retrieve a value
  del KEY           — delete a key
  scan [S] [E]      — scan keys in range [S, E)
  snap              — create a read snapshot
  snapget ID KEY    — get KEY at snapshot ID
  batch             — start an atomic write batch
    put KEY VALUE   — (inside batch)
    del KEY         — (inside batch)
    end             — commit the batch
    abort           — discard the batch
  compact           — trigger manual compaction
  info              — show level statistics
  help              — this message
  quit              — exit""")

                elif cmd == "put":
                    if len(parts) < 3:
                        print("Usage: put KEY VALUE")
                        continue
                    key, value = parts[1], parts[2]
                    if in_batch:
                        batch.append(("put", key, value))
                        print(f"  queued: put {key!r}")
                    else:
                        db.put(_encode_key(key), _encode_val(value))
                        print(f"OK")

                elif cmd == "get":
                    if len(parts) < 2:
                        print("Usage: get KEY")
                        continue
                    val = db.get(_encode_key(parts[1]))
                    if val is None:
                        print("(not found)")
                    else:
                        print(_decode(val))

                elif cmd in ("del", "delete"):
                    if len(parts) < 2:
                        print("Usage: del KEY")
                        continue
                    if in_batch:
                        batch.append(("del", parts[1], None))
                        print(f"  queued: del {parts[1]!r}")
                    else:
                        db.delete(_encode_key(parts[1]))
                        print("OK")

                elif cmd == "scan":
                    start_k = _encode_key(parts[1]) if len(parts) > 1 else None
                    end_k = _encode_key(parts[2]) if len(parts) > 2 else None
                    count = 0
                    for k, v in db.scan(start_k, end_k):
                        print(f"  {_decode(k)!r:40s}  {_decode(v)!r}")
                        count += 1
                    print(f"({count} keys)")

                elif cmd == "snap":
                    snap = db.snapshot()
                    snap_counter += 1
                    snap_id = f"snap{snap_counter}"
                    snapshots[snap_id] = snap
                    print(f"Snapshot created: {snap_id} (seq={snap.seq})")

                elif cmd == "snapget":
                    if len(parts) < 3:
                        print("Usage: snapget SNAP_ID KEY")
                        continue
                    snap_id, key = parts[1], parts[2]
                    if snap_id not in snapshots:
                        print(f"Unknown snapshot: {snap_id}")
                        continue
                    val = db.get(_encode_key(key), snapshot=snapshots[snap_id])
                    if val is None:
                        print("(not found at snapshot)")
                    else:
                        print(_decode(val))

                elif cmd == "batch":
                    in_batch = True
                    batch = []
                    print("Batch started. Use 'put'/'del' then 'end' or 'abort'.")

                elif cmd == "end" and in_batch:
                    wb = WriteBatch()
                    for op_type, k, v in batch:
                        if op_type == "put":
                            wb.put(_encode_key(k), _encode_val(v))
                        else:
                            wb.delete(_encode_key(k))
                    db.write_batch(wb)
                    print(f"Batch committed ({len(batch)} ops)")
                    in_batch = False
                    batch = []

                elif cmd == "abort" and in_batch:
                    print(f"Batch aborted ({len(batch)} ops discarded)")
                    in_batch = False
                    batch = []

                elif cmd == "compact":
                    db.compact()
                    print("Compaction done.")

                elif cmd == "info":
                    info = db.info()
                    print(f"  DB path:      {info['db_dir']}")
                    print(f"  Next seq:     {info['next_seq']}")
                    print(f"  MemTable:     {info['memtable_entries']} entries, "
                          f"{info['memtable_size'] / 1024:.1f} KB")
                    for lvl, lstats in sorted(info["levels"].items()):
                        print(f"  L{lvl}:  {lstats['files']} files, "
                              f"{lstats['bytes'] / 1024:.1f} KB")

                else:
                    print(f"Unknown command: {cmd!r}. Type 'help' for help.")

            except Exception as e:
                print(f"Error: {e}")

    finally:
        db.close()


# ---------------------------------------------------------------------------
# One-shot subcommands
# ---------------------------------------------------------------------------

def cmd_get(args):
    db = _open_db(args.path)
    try:
        val = db.get(_encode_key(args.key))
        if val is None:
            print("(not found)")
            sys.exit(1)
        else:
            sys.stdout.buffer.write(val)
            sys.stdout.buffer.write(b"\n")
    finally:
        db.close()


def cmd_put(args):
    db = _open_db(args.path)
    try:
        db.put(_encode_key(args.key), _encode_val(args.value))
        print("OK")
    finally:
        db.close()


def cmd_del(args):
    db = _open_db(args.path)
    try:
        db.delete(_encode_key(args.key))
        print("OK")
    finally:
        db.close()


def cmd_scan(args):
    db = _open_db(args.path)
    try:
        start = _encode_key(args.start) if args.start else None
        end = _encode_key(args.end) if args.end else None
        count = 0
        for k, v in db.scan(start, end):
            print(f"{_decode(k)}\t{_decode(v)}")
            count += 1
        print(f"# {count} records", file=sys.stderr)
    finally:
        db.close()


def cmd_compact(args):
    db = _open_db(args.path)
    try:
        db.compact()
        print("Compaction complete.")
    finally:
        db.close()


def cmd_info(args):
    db = _open_db(args.path)
    try:
        info = db.info()
        print(f"DB path:    {info['db_dir']}")
        print(f"Next seq:   {info['next_seq']}")
        print(f"MemTable:   {info['memtable_entries']} entries, "
              f"{info['memtable_size'] / 1024:.1f} KB")
        total_files = sum(s["files"] for s in info["levels"].values())
        total_bytes = sum(s["bytes"] for s in info["levels"].values())
        for lvl, lstats in sorted(info["levels"].items()):
            bar = "#" * min(40, lstats["files"])
            print(f"  L{lvl}: {lstats['files']:4d} files  "
                  f"{lstats['bytes'] / 1024:9.1f} KB  {bar}")
        print(f"Total:      {total_files} SSTable files, "
              f"{total_bytes / 1024:.1f} KB on disk")
    finally:
        db.close()


def cmd_bench(args):
    """Throughput benchmark: sequential write, random write, read."""
    n = args.n
    mode = args.mode  # all, seqwrite, randwrite, seqread, randread

    print(f"Strata benchmark: n={n}, mode={mode}")
    print(f"DB path: {args.path}\n")

    db = _open_db(args.path)

    def _key(i: int) -> bytes:
        return f"key:{i:010d}".encode()

    def _val(i: int) -> bytes:
        return f"value:{i:010d}:{'x' * 50}".encode()

    def bench_op(name, ops, fn):
        t0 = time.perf_counter()
        for op in ops:
            fn(op)
        elapsed = time.perf_counter() - t0
        rate = len(ops) / elapsed if elapsed > 0 else float("inf")
        mb = sum(len(_key(o)) + len(_val(o)) for o in ops) / 1024 / 1024
        print(f"  {name:20s}: {len(ops):7d} ops in {elapsed:.3f}s "
              f"= {rate:9.0f} ops/s  ({mb / elapsed:.1f} MB/s)")

    try:
        if mode in ("all", "seqwrite"):
            indices = list(range(n))
            bench_op("sequential write", indices, lambda i: db.put(_key(i), _val(i)))

        if mode in ("all", "randwrite"):
            indices = list(range(n))
            random.shuffle(indices)
            bench_op("random write", indices, lambda i: db.put(_key(i), _val(i)))

        if mode in ("all", "seqread"):
            indices = list(range(n))
            bench_op("sequential read", indices, lambda i: db.get(_key(i)))

        if mode in ("all", "randread"):
            indices = list(range(n))
            random.shuffle(indices)
            bench_op("random read", indices, lambda i: db.get(_key(i)))

        if mode == "all":
            info = db.info()
            print(f"\nFinal level stats:")
            for lvl, lstats in sorted(info["levels"].items()):
                print(f"  L{lvl}: {lstats['files']} files, "
                      f"{lstats['bytes'] / 1024:.1f} KB")

    finally:
        db.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="strata",
        description="Strata — LSM-tree key-value store"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # repl
    p = sub.add_parser("repl", help="Interactive REPL")
    p.add_argument("path", help="Database directory")

    # get
    p = sub.add_parser("get", help="Get a value")
    p.add_argument("path")
    p.add_argument("key")

    # put
    p = sub.add_parser("put", help="Put a value")
    p.add_argument("path")
    p.add_argument("key")
    p.add_argument("value")

    # del
    p = sub.add_parser("del", help="Delete a key")
    p.add_argument("path")
    p.add_argument("key")

    # scan
    p = sub.add_parser("scan", help="Scan a key range")
    p.add_argument("path")
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)

    # compact
    p = sub.add_parser("compact", help="Force compaction")
    p.add_argument("path")

    # info
    p = sub.add_parser("info", help="Show level statistics")
    p.add_argument("path")

    # bench
    p = sub.add_parser("bench", help="Throughput benchmark")
    p.add_argument("path")
    p.add_argument("--n", type=int, default=10000, help="Number of operations")
    p.add_argument("--mode", choices=["all", "seqwrite", "randwrite", "seqread", "randread"],
                   default="all")

    args = parser.parse_args()

    dispatch = {
        "repl": cmd_repl,
        "get": cmd_get,
        "put": cmd_put,
        "del": cmd_del,
        "scan": cmd_scan,
        "compact": cmd_compact,
        "info": cmd_info,
        "bench": cmd_bench,
    }
    dispatch[args.cmd](args)


if __name__ == "__main__":
    main()
