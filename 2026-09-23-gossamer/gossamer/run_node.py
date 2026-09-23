"""Entry point for a single Gossamer node subprocess.

Usage: python3 -m gossamer.run_node <config.json>

The config file is a plain JSON object: node_id, host, port, peers
(node_id -> [host, port]) and any NodeServer keyword overrides (n, r, w,
vnodes, gossip_interval, suspect_timeout, dead_timeout,
anti_entropy_interval, request_timeout). Runs forever until killed --
letting the OS actually terminate the process (SIGKILL/SIGTERM) is how the
demo simulates a real node failure, not a flag flip in shared memory.
"""
import json
import sys
import time

from .node import NodeServer

KNOWN_KWARGS = {
    "n", "r", "w", "vnodes", "gossip_interval", "suspect_timeout",
    "dead_timeout", "anti_entropy_interval", "request_timeout",
}


def main(config_path):
    with open(config_path) as f:
        cfg = json.load(f)
    peers = {nid: tuple(addr) for nid, addr in cfg["peers"].items()}
    kwargs = {k: v for k, v in cfg.items() if k in KNOWN_KWARGS}
    node = NodeServer(cfg["node_id"], cfg["host"], cfg["port"], peers, **kwargs)
    node.start()
    print(f"gossamer node {cfg['node_id']} listening on {cfg['host']}:{cfg['port']}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        node.stop()


if __name__ == "__main__":
    main(sys.argv[1])
