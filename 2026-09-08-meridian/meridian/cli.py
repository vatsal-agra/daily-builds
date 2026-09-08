"""The `meridian` command-line tool: run / demo / filedemo / viz."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import nodeid
from .filestore import chunk_raw_key, get_file, put_file
from .simulator import Simulation


def _die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _validate_common(args) -> None:
    if args.nodes < 1:
        _die("--nodes must be >= 1")
    if args.latency_min < 1:
        _die("--latency-min must be >= 1")
    if args.latency_max < args.latency_min:
        _die("--latency-max must be >= --latency-min")
    if not (0.0 <= args.loss < 1.0):
        _die("--loss must be in [0, 1)")
    if args.k < 1:
        _die("--k must be >= 1")
    if args.alpha < 1:
        _die("--alpha must be >= 1")


def _build_sim(args) -> Simulation:
    return Simulation(
        seed=args.seed,
        latency_range=(args.latency_min, args.latency_max),
        loss_prob=args.loss,
        k=args.k,
        alpha=args.alpha,
    )


def _settle_time(n_nodes: int, join_step: int = 30) -> int:
    return n_nodes * join_step + 500


def _lookup_sync(sim: Simulation, src_node, target: int):
    """Kick off one lookup and pump the simulator forward until it
    completes (or genuinely can't), returning the [contact ids] result."""
    box: dict = {}
    src_node.lookup_nodes(target, lambda contacts: box.update(result=contacts))
    sim.pump_until(lambda: "result" in box)
    return box.get("result")


def _put_sync(node, raw_key: bytes, value: bytes, sim: Simulation, ttl=None):
    box: dict = {}
    kwargs = {} if ttl is None else {"ttl": ttl}
    node.put(raw_key, value, on_complete=lambda ok, total: box.update(ok=ok, total=total), **kwargs)
    sim.pump_until(lambda: "ok" in box)
    return box.get("ok", 0), box.get("total", 0)


def _get_sync(node, raw_key: bytes, sim: Simulation):
    box: dict = {}
    node.get(raw_key, lambda v: box.update(value=v, done=True))
    sim.pump_until(lambda: box.get("done", False))
    return box.get("value")


def _put_file_sync(node, filename: str, data: bytes, sim: Simulation, chunk_size=None):
    box: dict = {}
    kwargs = {} if chunk_size is None else {"chunk_size": chunk_size}
    put_file(node, filename, data, on_complete=lambda mk, mf, ok: box.update(key=mk, manifest=mf, ok=ok, done=True), **kwargs)
    sim.pump_until(lambda: box.get("done", False))
    return box.get("key"), box.get("manifest"), box.get("ok")


def _get_file_sync(node, manifest_key: bytes, sim: Simulation):
    box: dict = {}
    get_file(node, manifest_key, lambda d, ok, err, mf: box.update(data=d, ok=ok, err=err, manifest=mf, done=True))
    sim.pump_until(lambda: box.get("done", False))
    return box.get("data"), box.get("ok"), box.get("err"), box.get("manifest")


def cmd_run(args) -> int:
    _validate_common(args)
    if args.lookups < 0:
        _die("--lookups must be >= 0")
    sim = _build_sim(args)
    sim.bootstrap_swarm(args.nodes)
    sim.run_until(_settle_time(args.nodes))

    if args.churn:
        live_ids = [n.id for n in sim.live_nodes()]
        sim.churn(live_ids, start=sim.network.time, end=sim.network.time + args.ticks, mean_interval=max(50, args.ticks // 10))

    sim.run_until(sim.network.time + args.ticks)

    live = sim.live_nodes()
    print(f"meridian run: {args.nodes} nodes, seed={args.seed}, t={sim.network.time}")
    print(f"  live nodes: {len(live)}/{len(sim.nodes)}")
    if live:
        avg_contacts = sum(n.routing_table.contact_count() for n in live) / len(live)
        print(f"  avg routing-table contacts/node: {avg_contacts:.1f}")
    print(f"  network: sent={sim.network.stats['sent']} delivered={sim.network.stats['delivered']} "
          f"dropped_offline={sim.network.stats['dropped_offline']} dropped_loss={sim.network.stats['dropped_loss']}")

    if args.lookups and live:
        overlaps = []
        for _ in range(args.lookups):
            src = sim.rng.choice(live)
            target = nodeid.random_id(sim.rng)
            result = _lookup_sync(sim, src, target) or []
            truth = set(sim.true_k_closest(target, args.k))
            got = set(result)
            overlap = len(truth & got) / len(truth) if truth else 1.0
            overlaps.append(overlap)
        avg_overlap = sum(overlaps) / len(overlaps)
        print(f"  {args.lookups} lookups vs. brute-force oracle: avg {avg_overlap*100:.1f}% of the true "
              f"{args.k}-closest nodes found")
    return 0


def cmd_demo(args) -> int:
    _validate_common(args)
    n = args.nodes
    print(f"=== Meridian demo: {n}-node Kademlia swarm, seed={args.seed} ===\n")
    sim = _build_sim(args)
    nodes = sim.bootstrap_swarm(n)
    sim.run_until(_settle_time(n))
    live = sim.live_nodes()
    print(f"[1/6] Swarm bootstrapped: {len(live)}/{n} nodes live at t={sim.network.time}")
    avg_contacts = sum(nd.routing_table.contact_count() for nd in live) / len(live)
    print(f"      avg routing-table size: {avg_contacts:.1f} contacts/node (k={args.k})\n")

    # -- lookup vs. oracle -----------------------------------------------------
    src = sim.rng.choice(live)
    target = nodeid.random_id(sim.rng)
    result = _lookup_sync(sim, src, target) or []
    truth = sim.true_k_closest(target, args.k)
    overlap = len(set(result) & set(truth)) / len(truth) if truth else 1.0
    verdict = "PASS" if overlap >= 0.8 else "CHECK"
    print(f"[2/6] Iterative lookup from node {nodeid.short(src.id)} for random target {nodeid.short(target)}")
    print(f"      found {len(result)} contacts, {overlap*100:.0f}% match vs. brute-force oracle  [{verdict}]\n")

    # -- store / get from a different node -----------------------------------------------------
    publisher = sim.rng.choice(live)
    other_candidates = [nd for nd in live if nd.id != publisher.id]
    fetcher = sim.rng.choice(other_candidates) if other_candidates else publisher
    key, value = b"demo-key", b"the value that was stored on one node and fetched from another"
    ok_count, total = _put_sync(publisher, key, value, sim)
    replicas_at = sorted({e["node"] for e in sim.trace if e["kind"] == "stored" and e.get("key") == nodeid.sha1_int(key)})
    got_value = _get_sync(fetcher, key, sim)
    ok = got_value == value
    print(f"[3/6] STORE from node {nodeid.short(publisher.id)}: replicated to {ok_count}/{total} nodes")
    print(f"      GET from a different node {nodeid.short(fetcher.id)}: "
          f"{'match' if ok else 'MISMATCH'}  [{'PASS' if ok else 'FAIL'}]\n")

    # -- survives a partial replica-holder outage -----------------------------------------------------
    # Crashing *every* replica holder simultaneously would just be data
    # loss -- no distributed system, Kademlia included, promises surviving
    # the instantaneous loss of literally every copy. The real, meaningful
    # claim is that it survives losing *most* of them: crash a majority of
    # the nodes that hold a replica, but not all, and confirm the value is
    # still reachable afterward (either straight from a surviving replica,
    # or via the periodic republish that's still running on the publisher
    # and on every surviving replica holder).
    n_crash = max(1, (len(replicas_at) * 7) // 10)
    n_crash = min(n_crash, max(0, len(replicas_at) - 1))
    to_crash = sim.rng.sample(replicas_at, n_crash) if n_crash else []
    for rid in to_crash:
        if rid in sim.nodes and sim.network.is_live(rid):
            sim.network.set_live(rid, False)
    print(f"[4/6] Partial outage: crashed {len(to_crash)}/{len(replicas_at)} of the original replica-holding "
          f"nodes for that key (kept {len(replicas_at) - len(to_crash)} alive)")
    sim.run_until(sim.network.time + 2000)  # let republish maintenance run at least once more
    survivors = [nd for nd in sim.live_nodes() if nd.id != publisher.id]
    resurrect_fetcher = sim.rng.choice(survivors) if survivors else None
    survived_value = _get_sync(resurrect_fetcher, key, sim) if resurrect_fetcher is not None else None
    survived = survived_value == value
    print(f"      GET after churn (from {nodeid.short(resurrect_fetcher.id) if resurrect_fetcher else 'n/a'}): "
          f"{'value survived' if survived else 'LOST'}  [{'PASS' if survived else 'FAIL'}]\n")

    # -- file store -----------------------------------------------------
    text = (
        "Meridian is a from-scratch Kademlia DHT.\n"
        "This file was chunked, hashed, and scattered across a simulated\n"
        "peer-to-peer network -- then reassembled on a completely different\n"
        "node than the one that uploaded it.\n"
    ).encode("utf-8") * 40  # a few KB, several chunks at the default 4096B chunk size
    uploader = sim.rng.choice(sim.live_nodes())
    m_key, manifest, _put_ok = _put_file_sync(uploader, "meridian.txt", text, sim)
    print(f"[5/6] Uploaded {len(text)}-byte file from node {nodeid.short(uploader.id)}: "
          f"{len(manifest['chunk_hashes'])} chunks, manifest key {m_key.decode()[:24]}...")

    # crash the original holder of chunk 0 to force a fallback to a replica
    chunk0_key_id = nodeid.sha1_int(chunk_raw_key(manifest["chunk_hashes"][0]))
    original_holders = [e["node"] for e in sim.trace if e["kind"] == "stored" and e.get("key") == chunk0_key_id]
    if original_holders and sim.network.is_live(original_holders[0]):
        sim.network.set_live(original_holders[0], False)
        print(f"      crashed chunk-0's original holder ({nodeid.short(original_holders[0])}) to force a replica fallback")

    downloaders = [nd for nd in sim.live_nodes() if nd.id != uploader.id]
    downloader = sim.rng.choice(downloaders) if downloaders else uploader
    data, dl_ok_flag, err, _mf = _get_file_sync(downloader, m_key, sim)
    dl_ok = bool(dl_ok_flag) and data == text
    print(f"      Downloaded via node {nodeid.short(downloader.id)}: "
          f"{'byte-identical, SHA-256 verified' if dl_ok else 'FAILED: ' + str(err)}  [{'PASS' if dl_ok else 'FAIL'}]\n")

    all_pass = ok and survived and dl_ok and overlap >= 0.8
    print(f"[6/6] {'ALL CHECKS PASSED' if all_pass else 'SOME CHECKS FAILED'}")
    print(f"      network totals: sent={sim.network.stats['sent']} delivered={sim.network.stats['delivered']} "
          f"dropped_offline={sim.network.stats['dropped_offline']} dropped_loss={sim.network.stats['dropped_loss']}")

    if args.emit_viz:
        _write_viz(sim, args.emit_viz)
        print(f"\n      wrote replay trace to {args.emit_viz}")

    return 0 if all_pass else 1


def cmd_filedemo(args) -> int:
    _validate_common(args)
    path = Path(args.file)
    if not path.exists():
        _die(f"no such file: {path}")
    if not path.is_file():
        _die(f"not a regular file: {path}")
    if args.chunk_size <= 0:
        _die("--chunk-size must be positive")
    data = path.read_bytes()

    sim = _build_sim(args)
    sim.bootstrap_swarm(args.nodes)
    sim.run_until(_settle_time(args.nodes))
    live = sim.live_nodes()
    if len(live) < 2:
        _die("need at least 2 live nodes to demonstrate cross-node retrieval")

    uploader = sim.rng.choice(live)
    m_key, manifest, put_ok = _put_file_sync(uploader, path.name, data, sim, chunk_size=args.chunk_size)
    if not put_ok:
        _die("put failed: no node acknowledged storing the manifest")
    print(f"put: {path.name} ({len(data)} bytes, {len(manifest['chunk_hashes'])} chunks) "
          f"from node {nodeid.short(uploader.id)}")
    print(f"manifest key: {m_key.decode()}")

    other = [nd for nd in live if nd.id != uploader.id]
    downloader = sim.rng.choice(other)
    data_back, ok, err, _mf = _get_file_sync(downloader, m_key, sim)
    if ok and data_back == data:
        print(f"get:  retrieved via node {nodeid.short(downloader.id)} -- {len(data_back)} bytes, SHA-256 verified match")
        return 0
    print(f"get:  FAILED via node {nodeid.short(downloader.id)}: {err}", file=sys.stderr)
    return 1


def _write_viz(sim: Simulation, out_path: str) -> None:
    def hexify(e: dict) -> dict:
        out = dict(e)
        for field in ("node", "target", "queried", "from_"):
            if field in out:
                out[field] = nodeid.to_hex(out[field])
        if "result" in out:
            out["result"] = [nodeid.to_hex(r) for r in out["result"]]
        if "key" in out:
            out["key"] = format(out["key"], "x")
        return out

    payload = {
        "seed": sim.seed,
        "k": sim.k,
        "alpha": sim.alpha,
        "nodes": [nodeid.to_hex(nid) for nid in sim.nodes],
        "events": [hexify(e) for e in sim.trace],
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload))


def cmd_viz(args) -> int:
    _validate_common(args)
    if args.churn_ticks < 0:
        _die("--churn-ticks must be >= 0")
    if args.lookups < 0:
        _die("--lookups must be >= 0")
    sim = _build_sim(args)
    sim.bootstrap_swarm(args.nodes)
    sim.run_until(_settle_time(args.nodes))

    live = sim.live_nodes()
    for _ in range(args.lookups):
        src = sim.rng.choice(live)
        target = nodeid.random_id(sim.rng)
        _lookup_sync(sim, src, target)

    key, value = b"viz-demo-key", b"a value visible in the replay"
    publisher = sim.rng.choice(live)
    _put_sync(publisher, key, value, sim)

    if args.churn_ticks:
        ids = [n.id for n in sim.live_nodes()]
        sim.churn(ids, sim.network.time, sim.network.time + args.churn_ticks, mean_interval=max(50, args.churn_ticks // 8))
        sim.run_until(sim.network.time + args.churn_ticks)

    other = [nd for nd in sim.live_nodes() if nd.id != publisher.id]
    if other:
        fetcher = sim.rng.choice(other)
        _get_sync(fetcher, key, sim)

    _write_viz(sim, args.out)
    print(f"wrote {len(sim.trace)} trace events to {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="meridian", description="A from-scratch Kademlia DHT simulator.")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp, nodes_default=40):
        sp.add_argument("--nodes", type=int, default=nodes_default)
        sp.add_argument("--seed", type=int, default=42)
        sp.add_argument("--loss", type=float, default=0.05)
        sp.add_argument("--latency-min", type=int, default=5)
        sp.add_argument("--latency-max", type=int, default=50)
        sp.add_argument("--k", type=int, default=20)
        sp.add_argument("--alpha", type=int, default=3)

    p_run = sub.add_parser("run", help="run a swarm simulation and report routing/lookup health")
    common(p_run)
    p_run.add_argument("--ticks", type=int, default=6000)
    p_run.add_argument("--lookups", type=int, default=20, help="random lookups to verify against the brute-force oracle")
    p_run.add_argument("--churn", action="store_true", help="enable random node crashes during the run")
    p_run.set_defaults(func=cmd_run)

    p_demo = sub.add_parser("demo", help="scripted end-to-end walkthrough of every feature")
    common(p_demo, nodes_default=30)
    p_demo.add_argument("--emit-viz", type=str, default=None, help="also write a replay trace JSON to this path")
    p_demo.set_defaults(func=cmd_demo)

    p_file = sub.add_parser("filedemo", help="store and retrieve one real file through the DHT")
    common(p_file)
    p_file.add_argument("file", type=str)
    p_file.add_argument("--chunk-size", type=int, default=4096)
    p_file.set_defaults(func=cmd_filedemo)

    p_viz = sub.add_parser("viz", help="run a simulation and emit a replay trace for the HTML visualizer")
    common(p_viz)
    p_viz.add_argument("--out", type=str, default="viz/trace.json")
    p_viz.add_argument("--lookups", type=int, default=15)
    p_viz.add_argument("--churn-ticks", type=int, default=1500)
    p_viz.set_defaults(func=cmd_viz)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit:
        raise
    except (ValueError, OSError) as exc:
        _die(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
