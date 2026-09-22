"""The flagship end-to-end demo: real independent OS processes, a real
tracker, and two scenarios that together prove Swarm is not just a working
downloader but a genuine, decentralized swarm.

Scenario A (multi-peer convergence): one seeder + three leechers,
discovering each other only through a real HTTP tracker, all converge to a
byte-identical copy of the source file.

Scenario B (peer-to-peer proof): two peers, each holding a disjoint half of
the pieces and NOTHING else -- no full seed anywhere in this scenario at
all. The only way either one can ever reach 100% is by pulling the pieces
it's missing from the other peer over the real wire protocol. This is a
structural guarantee, not a probabilistic hope: there is no third copy of
the file for either of them to have downloaded from instead.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from typing import List, Tuple

from . import torrentfile, tracker as tracker_mod


def _log(verbose: bool, *args) -> None:
    if verbose:
        print(*args, flush=True)


def make_synthetic_file(path: str, size: int, seed: int) -> None:
    rnd = random.Random(seed)
    with open(path, "wb") as f:
        remaining = size
        while remaining > 0:
            n = min(65536, remaining)
            f.write(rnd.randbytes(n))
            remaining -= n


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_leech(python: str, torrent_path: str, out_path: str, status_path: str, timeout: float, preseed: str = None, preseed_source: str = None, dashboard_url: str = None) -> subprocess.Popen:
    cmd = [python, "-m", "swarm.cli", "leech", torrent_path, "--out", out_path, "--timeout", str(timeout), "--status-file", status_path]
    if preseed:
        cmd += ["--preseed", preseed, "--preseed-source", preseed_source]
    if dashboard_url:
        cmd += ["--dashboard", dashboard_url]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def scenario_convergence(workdir: str, tracker_url: str, verbose: bool, dashboard_url: str = None) -> bool:
    _log(verbose, "\n=== Scenario A: multi-peer convergence (1 seed + 3 leechers via tracker) ===")
    src = os.path.join(workdir, "sceneA_source.bin")
    make_synthetic_file(src, 300 * 1024, seed=42)
    info = torrentfile.create_torrent(src, announce=tracker_url, piece_length=16 * 1024)
    torrent_path = os.path.join(workdir, "sceneA.torrent")
    torrentfile.save_torrent(info, torrent_path)
    _log(verbose, f"source: {info.length} bytes, {info.num_pieces} pieces, info_hash={info.info_hash().hex()}")

    python = sys.executable
    seed_cmd = [python, "-m", "swarm.cli", "seed", torrent_path, src, "--port", "0"]
    if dashboard_url:
        seed_cmd += ["--dashboard", dashboard_url]
    seed_proc = subprocess.Popen(seed_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(0.5)  # give the seeder a moment to bind + announce before leechers start hunting for peers

    leech_procs = []
    status_paths = []
    for i in range(3):
        out_path = os.path.join(workdir, f"sceneA_leech{i}.bin")
        status_path = os.path.join(workdir, f"sceneA_leech{i}.json")
        status_paths.append(status_path)
        leech_procs.append(_run_leech(python, torrent_path, out_path, status_path, timeout=45, dashboard_url=dashboard_url))

    ok = True
    source_hash = sha256_of(src)
    per_peer_piece_counts = {}
    for i, proc in enumerate(leech_procs):
        try:
            rc = proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = -1
        if rc != 0:
            _log(verbose, f"leecher {i} FAILED (exit {rc}):\n{proc.stdout.read() if proc.stdout else ''}")
            ok = False
            continue
        out_path = os.path.join(workdir, f"sceneA_leech{i}.bin")
        with open(status_paths[i]) as f:
            status = json.load(f)
        matches = os.path.exists(out_path) and sha256_of(out_path) == source_hash
        _log(verbose, f"leecher {i}: have={status['have']}/{status['total']} verified={status['verified']} sha256_match={matches}")
        ok = ok and status["ok"] and status["verified"] and matches
        for src_peer in status.get("piece_sources", {}).values():
            per_peer_piece_counts[src_peer] = per_peer_piece_counts.get(src_peer, 0) + 1

    seed_proc.terminate()
    try:
        seed_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        seed_proc.kill()

    _log(verbose, f"piece-source histogram across leechers (peer_id -> pieces served): {per_peer_piece_counts}")
    _log(verbose, f"Scenario A: {'PASS' if ok else 'FAIL'}")
    return ok


def scenario_peer_to_peer(workdir: str, tracker_url: str, verbose: bool, dashboard_url: str = None) -> bool:
    _log(verbose, "\n=== Scenario B: peer-to-peer proof (2 disjoint half-holders, NO seed present) ===")
    src = os.path.join(workdir, "sceneB_source.bin")
    make_synthetic_file(src, 208 * 1024, seed=1337)
    info = torrentfile.create_torrent(src, announce=tracker_url, piece_length=16 * 1024)
    torrent_path = os.path.join(workdir, "sceneB.torrent")
    torrentfile.save_torrent(info, torrent_path)
    n = info.num_pieces
    mid = n // 2
    first_half = f"0-{mid - 1}"
    second_half = f"{mid}-{n - 1}"
    _log(verbose, f"source: {info.length} bytes, {n} pieces. L1 preseeded [{first_half}], L2 preseeded [{second_half}]. No full seed runs in this scenario.")

    python = sys.executable
    out1 = os.path.join(workdir, "sceneB_l1.bin")
    out2 = os.path.join(workdir, "sceneB_l2.bin")
    status1 = os.path.join(workdir, "sceneB_l1.json")
    status2 = os.path.join(workdir, "sceneB_l2.json")
    p1 = _run_leech(python, torrent_path, out1, status1, timeout=45, preseed=first_half, preseed_source=src, dashboard_url=dashboard_url)
    p2 = _run_leech(python, torrent_path, out2, status2, timeout=45, preseed=second_half, preseed_source=src, dashboard_url=dashboard_url)

    ok = True
    source_hash = sha256_of(src)
    results = {}
    for name, proc, out_path, status_path in (("L1", p1, out1, status1), ("L2", p2, out2, status2)):
        try:
            rc = proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = -1
        if rc != 0:
            _log(verbose, f"{name} FAILED (exit {rc}):\n{proc.stdout.read() if proc.stdout else ''}")
            ok = False
            continue
        with open(status_path) as f:
            status = json.load(f)
        results[name] = status
        matches = os.path.exists(out_path) and sha256_of(out_path) == source_hash
        _log(verbose, f"{name}: have={status['have']}/{status['total']} verified={status['verified']} sha256_match={matches} peer_id={status['peer_id']}")
        ok = ok and status["ok"] and status["verified"] and matches

    if ok and "L1" in results and "L2" in results:
        l1_id, l2_id = results["L1"]["peer_id"], results["L2"]["peer_id"]
        l1_preseeded = set(range(0, mid))
        l2_preseeded = set(range(mid, n))
        # Everything L1 has that it didn't start with MUST have been sourced
        # from L2 -- there is no other peer in this scenario that could have
        # supplied it.
        l1_downloaded = {int(k): v for k, v in results["L1"]["piece_sources"].items()}
        l2_downloaded = {int(k): v for k, v in results["L2"]["piece_sources"].items()}
        bad = [(i, src) for i, src in l1_downloaded.items() if i not in l1_preseeded and src != l2_id]
        bad += [(i, src) for i, src in l2_downloaded.items() if i not in l2_preseeded and src != l1_id]
        if bad:
            _log(verbose, f"FAIL: pieces attributed to an impossible source: {bad}")
            ok = False
        elif not l1_downloaded or not l2_downloaded:
            _log(verbose, "FAIL: neither peer downloaded anything from the other -- scenario didn't exercise the wire protocol")
            ok = False
        else:
            _log(
                verbose,
                f"CONFIRMED peer-to-peer transfer: L1 ({l1_id}) received pieces {sorted(l1_downloaded)} from L2; "
                f"L2 ({l2_id}) received pieces {sorted(l2_downloaded)} from L1. No seed was involved.",
            )

    _log(verbose, f"Scenario B: {'PASS' if ok else 'FAIL'}")
    return ok


def run_demo(verbose: bool = True, with_dashboard: bool = True) -> int:
    from . import dashboard as dashboard_mod

    workdir = tempfile.mkdtemp(prefix="swarm-demo-")
    keep = os.environ.get("SWARM_DEMO_KEEP") == "1"
    server = tracker_mod.run_tracker("127.0.0.1", 0)
    tracker_url = f"http://127.0.0.1:{server.server_port}/announce"
    _log(verbose, f"tracker: {tracker_url}")

    dash_server = None
    dashboard_url = None
    if with_dashboard:
        dash_server = dashboard_mod.run_dashboard("127.0.0.1", 0)
        dashboard_url = f"http://127.0.0.1:{dash_server.server_port}"
        _log(verbose, f"dashboard: {dashboard_url}/  (every seed/leech subprocess below reports its real events here live)")

    try:
        a_ok = scenario_convergence(workdir, tracker_url, verbose, dashboard_url=dashboard_url)
        b_ok = scenario_peer_to_peer(workdir, tracker_url, verbose, dashboard_url=dashboard_url)
        overall = a_ok and b_ok
        _log(verbose, f"\n=== demo {'PASSED' if overall else 'FAILED'} ===")
        return 0 if overall else 1
    finally:
        server.shutdown()
        server.server_close()
        if dash_server is not None:
            dash_server.shutdown()
            dash_server.server_close()
        if keep:
            _log(verbose, f"workdir kept at {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(run_demo())
