"""Orchestrates a Gossamer cluster of real OS subprocesses on localhost.

Used both by the flagship multi-process demo and by integration tests that
need genuine process death (SIGKILL) rather than an in-memory failure flag.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from . import httpjson

DEFAULT_KWARGS = dict(
    n=3, r=2, w=2, vnodes=32,
    gossip_interval=0.3, suspect_timeout=1.2, dead_timeout=3.0,
    anti_entropy_interval=1.0, request_timeout=1.5,
)


class Cluster:
    def __init__(self, node_ids, base_port=9500, **kwargs):
        self.node_ids = list(node_ids)
        self.peers = {nid: ("127.0.0.1", base_port + i) for i, nid in enumerate(self.node_ids)}
        self.kwargs = {**DEFAULT_KWARGS, **kwargs}
        self.procs = {}
        self.config_dir = tempfile.mkdtemp(prefix="gossamer-")

    def address_of(self, node_id):
        return self.peers[node_id]

    def _config_path(self, node_id):
        return os.path.join(self.config_dir, f"{node_id}.json")

    def _write_config(self, node_id):
        host, port = self.peers[node_id]
        cfg = {
            "node_id": node_id, "host": host, "port": port,
            "peers": {nid: list(addr) for nid, addr in self.peers.items()},
            **self.kwargs,
        }
        with open(self._config_path(node_id), "w") as f:
            json.dump(cfg, f)

    def start_node(self, node_id, stdout=None):
        self._write_config(node_id)
        proc = subprocess.Popen(
            [sys.executable, "-m", "gossamer.run_node", self._config_path(node_id)],
            stdout=stdout or subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        self.procs[node_id] = proc

    def start_all(self, timeout=15):
        for nid in self.node_ids:
            self.start_node(nid)
        self.wait_up(self.node_ids, timeout=timeout)

    def wait_up(self, node_ids, timeout=15):
        deadline = time.time() + timeout
        pending = set(node_ids)
        while pending and time.time() < deadline:
            for nid in list(pending):
                host, port = self.peers[nid]
                try:
                    status, _ = httpjson.get_json(host, port, "/admin/status", timeout=0.3)
                    if status == 200:
                        pending.discard(nid)
                except httpjson.NodeUnreachable:
                    pass
            if pending:
                time.sleep(0.1)
        if pending:
            raise RuntimeError(f"nodes never came up: {pending}")

    def kill_node(self, node_id):
        proc = self.procs.pop(node_id, None)
        if proc is not None:
            proc.kill()
            proc.wait(timeout=5)

    def revive_node(self, node_id, timeout=15):
        self.start_node(node_id)
        self.wait_up([node_id], timeout=timeout)

    def is_alive_proc(self, node_id):
        proc = self.procs.get(node_id)
        return proc is not None and proc.poll() is None

    def status(self, node_id):
        host, port = self.peers[node_id]
        status, body = httpjson.get_json(host, port, "/admin/status", timeout=2.0)
        return body

    def events(self, node_id, since=0.0):
        host, port = self.peers[node_id]
        status, body = httpjson.get_json(host, port, f"/admin/events?since={since}", timeout=2.0)
        return body

    def stop_all(self):
        for nid in list(self.procs):
            self.kill_node(nid)
        shutil.rmtree(self.config_dir, ignore_errors=True)

    def __enter__(self):
        self.start_all()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop_all()
