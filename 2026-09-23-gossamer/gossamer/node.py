"""A Gossamer node: every physical node runs this exact same server.

There is no special coordinator process. Any node can act as coordinator
for a client request that happens to land on it -- it just means "the node
the client asked first." A node also independently gossips its heartbeat,
runs its own local failure detector, and holds hinted-handoff data on
behalf of a currently-unreachable peer.
"""
import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote, unquote

from . import httpjson
from .gossip import Membership, ALIVE
from .hashring import HashRing
from .merkle import MerkleTree, KEY_RANGE_BUCKETS
from .store import LocalStore, reduce_siblings
from .vclock import VectorClock


def siblings_to_wire(siblings):
    return [{"value": v, "vclock": vc.to_dict(), "ts": ts} for v, vc, ts in siblings]


def wire_to_siblings(items):
    return [(it["value"], VectorClock.from_dict(it["vclock"]), it["ts"]) for it in items]


def _validate_context(context):
    """Returns an error message string if `context` isn't a valid vector-clock
    context (a list of {node_id: int} dicts, exactly what a prior GET
    returns), else None. PUT should reject a malformed context with a clean
    400 instead of letting VectorClock.from_dict raise deep inside."""
    if context is None:
        return None
    if not isinstance(context, list):
        return f"context must be a list of vector-clock dicts, got {type(context).__name__}"
    for entry in context:
        if not isinstance(entry, dict):
            return f"each context entry must be a dict, got {type(entry).__name__}"
        for k, v in entry.items():
            if not isinstance(k, str) or not isinstance(v, int) or isinstance(v, bool):
                return f"context counters must be {{str: int}}, got {{{k!r}: {v!r}}}"
    return None


def _sibling_identity(value, vclock):
    """Hashable identity for a (value, vclock) pair -- values put through
    Gossamer are arbitrary JSON (lists/dicts included), which aren't
    hashable on their own, so set-based comparisons must go through a
    canonical JSON dump rather than the raw value."""
    return (json.dumps(value, sort_keys=True, default=str), tuple(sorted(vclock.to_dict().items())))


class NodeServer:
    def __init__(self, node_id, host, port, peers, n=3, r=2, w=2, vnodes=32,
                 gossip_interval=0.5, suspect_timeout=2.0, dead_timeout=5.0,
                 anti_entropy_interval=2.0, request_timeout=1.5,
                 event_log=None):
        """peers: dict node_id -> (host, port), including this node itself."""
        if n < 1:
            raise ValueError(f"n must be >= 1, got {n}")
        if not (1 <= w <= n):
            raise ValueError(f"w must satisfy 1 <= w <= n (n={n}), got w={w}")
        if not (1 <= r <= n):
            raise ValueError(f"r must satisfy 1 <= r <= n (n={n}), got r={r}")

        self.node_id = node_id
        self.host = host
        self.port = port
        self.peers = dict(peers)
        self.n, self.r, self.w = n, r, w
        self.request_timeout = request_timeout
        self.anti_entropy_interval = anti_entropy_interval

        self.ring = HashRing(vnodes=vnodes)
        for nid in self.peers:
            self.ring.add_node(nid)

        self.store = LocalStore()
        self.membership = Membership(node_id, list(self.peers.keys()),
                                      suspect_timeout=suspect_timeout,
                                      dead_timeout=dead_timeout)
        self.gossip_interval = gossip_interval

        # Hinted handoff: data this node is holding *on behalf of* another
        # node_id while that node was unreachable. hints[owner_id][key] ->
        # list of (value, VectorClock, ts).
        self._hints_lock = threading.RLock()
        self.hints = {}

        self.merkle = MerkleTree(KEY_RANGE_BUCKETS)

        self._stop = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=32)
        self._httpd = None
        self._threads = []

        # Bounded ring buffer of recent events, for the dashboard.
        self.event_log = event_log if event_log is not None else []
        self._event_lock = threading.RLock()

        self._metrics_lock = threading.Lock()
        self._read_repair_ops = 0
        self._anti_entropy_ops = 0

    def _incr_read_repair_ops(self, n=1):
        with self._metrics_lock:
            self._read_repair_ops += n

    def _incr_anti_entropy_ops(self, n):
        with self._metrics_lock:
            self._anti_entropy_ops += n

    # ---------------------------------------------------------------- utils
    def log_event(self, kind, **fields):
        entry = {"ts": time.time(), "node": self.node_id, "kind": kind}
        entry.update(fields)
        with self._event_lock:
            self.event_log.append(entry)
            if len(self.event_log) > 500:
                del self.event_log[: len(self.event_log) - 500]

    def _addr(self, node_id):
        return self.peers[node_id]

    def preferred_replicas(self, key):
        return self.ring.replicas_for(key, self.n)

    def pick_substitute(self, key, owner, exclude):
        """Deterministic hinted-handoff target: walk the full preference
        list for `key` past the first N primaries and take the first node
        this node's *local* membership view considers alive, skipping
        anything already chosen this round. Deterministic given a converged
        membership view, so writers and readers agree on where a hint
        lives without any extra coordination message."""
        full_pref = self.ring.preference_list(key)
        exclude = set(exclude) | {owner}
        candidates = full_pref[self.n:] + full_pref[: self.n]
        for cand in candidates:
            if cand in exclude:
                continue
            if self.membership.is_alive(cand):
                return cand
        return None

    # ------------------------------------------------------- internal RPCs
    def _local_or_remote_put(self, target, key, value, vclock, hint_for=None):
        if target == self.node_id:
            return self._apply_put(key, value, vclock, hint_for)
        payload = {"key": key, "value": value, "vclock": vclock.to_dict(), "hint_for": hint_for}
        host, port = self._addr(target)
        status, body = httpjson.post_json(host, port, "/internal/put", payload,
                                           timeout=self.request_timeout)
        if status != 200:
            raise httpjson.NodeUnreachable(f"{target} returned {status}")
        return body.get("accepted", False)

    def _local_or_remote_get(self, target, key, hint_for=None):
        if target == self.node_id:
            return self._apply_get(key, hint_for)
        host, port = self._addr(target)
        path = f"/internal/get?key={quote(key, safe='')}"
        if hint_for:
            path += f"&hint_for={quote(hint_for, safe='')}"
        status, body = httpjson.get_json(host, port, path, timeout=self.request_timeout)
        if status != 200:
            raise httpjson.NodeUnreachable(f"{target} returned {status}")
        return wire_to_siblings(body.get("siblings", []))

    def _apply_put(self, key, value, vclock, hint_for=None):
        if hint_for:
            with self._hints_lock:
                bucket = self.hints.setdefault(hint_for, {})
                existing = bucket.get(key, [])
                bucket[key] = reduce_siblings(existing + [(value, vclock, time.time())])
            self.log_event("hint-stored", key=key, owner=hint_for)
            return True
        accepted, _ = self.store.put(key, value, vclock)
        return accepted

    def _apply_get(self, key, hint_for=None):
        if hint_for:
            with self._hints_lock:
                return list(self.hints.get(hint_for, {}).get(key, []))
        return self.store.get(key)

    # --------------------------------------------------------- coordinator
    def coordinate_put(self, key, value, context):
        replicas = self.preferred_replicas(key)
        if not replicas:
            return {"error": "no nodes available"}, 503
        error = _validate_context(context)
        if error:
            return {"error": error}, 400
        base = VectorClock.merge_all([VectorClock.from_dict(c) for c in (context or [])])
        new_clock = base.increment(self.node_id)

        acks = 0
        used_targets = []
        errors = []

        def do_one(owner):
            status = self.membership.status_of(owner)
            if status == ALIVE:
                target, hint_for = owner, None
            else:
                target = self.pick_substitute(key, owner, exclude=replicas)
                if target is None:
                    return ("skip", owner, None)
                hint_for = owner
            try:
                self._local_or_remote_put(target, key, value, new_clock, hint_for)
                return ("ok", owner, target)
            except httpjson.NodeUnreachable as e:
                return ("err", owner, str(e))

        futures = [self._executor.submit(do_one, owner) for owner in replicas]
        for fut in futures:
            outcome, owner, detail = fut.result(timeout=self.request_timeout + 1)
            if outcome == "ok":
                acks += 1
                used_targets.append((owner, detail))
            elif outcome == "err":
                errors.append((owner, detail))

        self.log_event("put", key=key, acks=acks, w=self.w, targets=used_targets,
                        vclock=new_clock.to_dict())

        if acks >= self.w:
            return {"context": [new_clock.to_dict()], "acks": acks, "w": self.w}, 200
        return {"error": "write did not reach W acks", "acks": acks, "w": self.w,
                "errors": errors}, 503

    def coordinate_get(self, key):
        replicas = self.preferred_replicas(key)
        if not replicas:
            return {"error": "no nodes available"}, 503

        responses = {}  # node_id -> siblings

        def do_one(owner):
            status = self.membership.status_of(owner)
            if status == ALIVE:
                target, hint_for = owner, None
            else:
                target = self.pick_substitute(key, owner, exclude=replicas)
                if target is None:
                    return (owner, None)
                hint_for = owner
            try:
                sibs = self._local_or_remote_get(target, key, hint_for)
                return (owner, sibs)
            except httpjson.NodeUnreachable:
                return (owner, None)

        futures = [self._executor.submit(do_one, owner) for owner in replicas]
        for fut in futures:
            owner, sibs = fut.result(timeout=self.request_timeout + 1)
            if sibs is not None:
                responses[owner] = sibs

        if len(responses) < self.r:
            self.log_event("get", key=key, responded=list(responses.keys()), r=self.r,
                            acks=len(responses))
            return {"error": "read did not reach R acks", "acks": len(responses),
                    "r": self.r}, 503

        flat = [item for sibs in responses.values() for item in sibs]
        merged = reduce_siblings(flat)
        merged_set = {_sibling_identity(v, vc) for v, vc, _ in merged}

        self.log_event("get", key=key, responded=list(responses.keys()), r=self.r,
                        siblings=len(merged), conflict=len(merged) > 1)

        # Read-repair: any replica whose view doesn't already equal the
        # merged frontier gets the winning value(s) pushed to it now, over
        # a real internal PUT -- not an in-memory shortcut.
        for owner, sibs in responses.items():
            owner_set = {_sibling_identity(v, vc) for v, vc, _ in sibs}
            if owner_set != merged_set:
                for value, vclock, _ in merged:
                    self._executor.submit(self._repair_one, owner, key, value, vclock)

        if not merged:
            return {"siblings": [], "context": []}, 200

        context = [vc.to_dict() for _, vc, _ in merged]
        return {"siblings": siblings_to_wire(merged), "context": context}, 200

    def _repair_one(self, owner, key, value, vclock):
        if self.membership.status_of(owner) != ALIVE:
            # Nothing was sent -- don't log or count a repair that didn't
            # happen. A later anti-entropy round (or a future read, if the
            # replica comes back) will catch this up instead.
            return
        try:
            self._local_or_remote_put(owner, key, value, vclock)
            self._incr_read_repair_ops()
            self.log_event("read-repair", key=key, target=owner)
        except httpjson.NodeUnreachable:
            pass

    # -------------------------------------------------------------- gossip
    def _gossip_loop(self):
        peer_ids = [p for p in self.peers if p != self.node_id]
        while not self._stop.is_set():
            time.sleep(self.gossip_interval + random.uniform(0, self.gossip_interval * 0.3))
            self.membership.tick_self()
            if not peer_ids:
                continue
            target = random.choice(peer_ids)
            host, port = self._addr(target)
            try:
                status, body = httpjson.post_json(
                    host, port, "/gossip",
                    {"heartbeats": self.membership.snapshot_heartbeats()},
                    timeout=self.gossip_interval,
                )
                if status == 200:
                    self._merge_and_react(body.get("heartbeats", {}))
            except httpjson.NodeUnreachable:
                pass

    def _merge_and_react(self, other_heartbeats):
        revived = self.membership.merge(other_heartbeats)
        for nid in revived:
            self.log_event("node-revived", peer=nid)
            self._executor.submit(self._flush_hints_for, nid)

    def _flush_hints_for(self, owner):
        with self._hints_lock:
            bucket = self.hints.pop(owner, {})
        if not bucket:
            return
        host, port = self._addr(owner)
        # `remaining` starts as a full copy of everything we're about to
        # attempt; a key is removed from it only once its flush is
        # *confirmed* successful. If the owner goes back down mid-flush, we
        # stop and merge the entire unprocessed remainder -- the failing
        # key AND every key after it that hadn't been tried yet -- back
        # into self.hints. Popping the key-by-key-successfully-flushed set
        # (rather than putting back only the one key that failed) is what
        # prevents not-yet-attempted keys from being silently dropped.
        remaining = dict(bucket)
        flushed_keys = []
        for key, siblings in bucket.items():
            ok = True
            for value, vclock, _ in siblings:
                try:
                    httpjson.post_json(host, port, "/internal/put",
                                        {"key": key, "value": value,
                                         "vclock": vclock.to_dict(), "hint_for": None},
                                        timeout=self.request_timeout)
                except httpjson.NodeUnreachable:
                    ok = False
                    break
            if ok:
                del remaining[key]
                flushed_keys.append(key)
            else:
                break
        if remaining:
            with self._hints_lock:
                b = self.hints.setdefault(owner, {})
                for key, siblings in remaining.items():
                    existing = b.get(key, [])
                    b[key] = reduce_siblings(existing + list(siblings))
            return
        if flushed_keys:
            self.log_event("hint-flushed", owner=owner, keys=flushed_keys)

    def _monitor_loop(self):
        # Failure status is derived lazily (status_of() computes it from
        # elapsed time), but we still poll here so a stall-without-gossip
        # eventually gets logged for the dashboard. Seed the baseline from
        # the current view rather than {} so startup doesn't log a burst of
        # spurious "-> alive" events for every peer that was alive all along.
        last_statuses = dict(self.membership.all_statuses())
        while not self._stop.is_set():
            time.sleep(0.25)
            statuses = self.membership.all_statuses()
            for nid, st in statuses.items():
                if last_statuses.get(nid) != st:
                    self.log_event("status-change", peer=nid, status=st)
            last_statuses = statuses

    # ---------------------------------------------------------- HTTP layer
    def start(self):
        handler_cls = _make_handler(self)
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler_cls)
        t = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        t.start()
        self._threads.append(t)
        for target in (self._gossip_loop, self._monitor_loop, self._anti_entropy_loop):
            th = threading.Thread(target=target, daemon=True)
            th.start()
            self._threads.append(th)

    def stop(self):
        self._stop.set()
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        self._executor.shutdown(wait=False)

    # ------------------------------------------------------- anti-entropy
    def _anti_entropy_loop(self):
        peer_ids = [p for p in self.peers if p != self.node_id]
        while not self._stop.is_set():
            time.sleep(self.anti_entropy_interval + random.uniform(0, self.anti_entropy_interval * 0.3))
            if not peer_ids:
                continue
            target = random.choice(peer_ids)
            if not self.membership.is_alive(target):
                continue
            self._anti_entropy_with(target)

    def _my_merkle_snapshot(self):
        return self.merkle.build(self.store.snapshot())

    def _anti_entropy_with(self, peer_id):
        host, port = self._addr(peer_id)
        try:
            local_tree = self._my_merkle_snapshot()
            status, body = httpjson.post_json(
                host, port, "/internal/merkle-diff",
                {"root_hashes": local_tree.leaf_hashes()},
                timeout=self.request_timeout,
            )
            if status != 200:
                return
            divergent_buckets = body.get("divergent", [])
            if not divergent_buckets:
                return
            keys_to_check = set()
            for bucket in divergent_buckets:
                keys_to_check.update(local_tree.keys_in_bucket(bucket))
            # Also ask the peer which keys it has in those buckets, in case
            # it holds keys we don't have at all.
            status2, body2 = httpjson.post_json(
                host, port, "/internal/bucket-keys", {"buckets": divergent_buckets},
                timeout=self.request_timeout,
            )
            if status2 == 200:
                keys_to_check.update(body2.get("keys", []))

            transferred = 0
            for key in keys_to_check:
                mine = self.store.get(key)
                status3, body3 = httpjson.get_json(host, port, f"/internal/get?key={quote(key, safe='')}",
                                                    timeout=self.request_timeout)
                theirs = wire_to_siblings(body3.get("siblings", [])) if status3 == 200 else []
                merged = reduce_siblings(mine + theirs)
                mine_set = {_sibling_identity(v, vc) for v, vc, _ in mine}
                theirs_set = {_sibling_identity(v, vc) for v, vc, _ in theirs}
                merged_set = {_sibling_identity(v, vc) for v, vc, _ in merged}
                if merged_set != mine_set:
                    for v, vc, ts in merged:
                        self.store.put(key, v, vc, ts)
                    transferred += 1
                if merged_set != theirs_set:
                    for v, vc, _ in merged:
                        try:
                            httpjson.post_json(host, port, "/internal/put",
                                                {"key": key, "value": v, "vclock": vc.to_dict(),
                                                 "hint_for": None}, timeout=self.request_timeout)
                        except httpjson.NodeUnreachable:
                            pass
                    transferred += 1
            self._incr_anti_entropy_ops(transferred)
            if transferred:
                self.log_event("anti-entropy", peer=peer_id,
                                buckets_checked=len(divergent_buckets),
                                keys_repaired=transferred,
                                keys_scanned=len(keys_to_check))
        except httpjson.NodeUnreachable:
            pass


def _make_handler(node: NodeServer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass  # silence default stderr access logging

        def _send(self, status, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            try:
                if path.startswith("/kv/"):
                    key = unquote(path[len("/kv/"):])
                    body, status = node.coordinate_get(key)
                    self._send(status, body)
                elif path == "/internal/get":
                    key = qs.get("key", [""])[0]
                    hint_for = qs.get("hint_for", [None])[0]
                    sibs = node._apply_get(key, hint_for)
                    self._send(200, {"siblings": siblings_to_wire(sibs)})
                elif path == "/admin/status":
                    self._send(200, node_status(node))
                elif path == "/admin/events":
                    since = float(qs.get("since", [0])[0])
                    with node._event_lock:
                        events = [e for e in node.event_log if e["ts"] > since]
                    self._send(200, {"events": events, "now": time.time()})
                elif path == "/dashboard":
                    body = _dashboard_html()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/favicon.ico":
                    self.send_response(204)
                    self.end_headers()
                else:
                    self._send(404, {"error": "not found"})
            except Exception as e:  # noqa: BLE001 - surface as a clean 500
                self._send(500, {"error": str(e)})

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path.startswith("/kv/"):
                    key = unquote(path[len("/kv/"):])
                    payload = self._read_json()
                    body, status = node.coordinate_put(key, payload.get("value"),
                                                         payload.get("context"))
                    self._send(status, body)
                elif path == "/internal/put":
                    payload = self._read_json()
                    vclock = VectorClock.from_dict(payload.get("vclock", {}))
                    accepted = node._apply_put(payload["key"], payload.get("value"),
                                                vclock, payload.get("hint_for"))
                    self._send(200, {"accepted": accepted})
                elif path == "/gossip":
                    payload = self._read_json()
                    node._merge_and_react(payload.get("heartbeats", {}))
                    self._send(200, {"heartbeats": node.membership.snapshot_heartbeats()})
                elif path == "/internal/merkle-diff":
                    payload = self._read_json()
                    tree = node._my_merkle_snapshot()
                    divergent = tree.diff(payload.get("root_hashes", {}))
                    self._send(200, {"divergent": divergent})
                elif path == "/internal/bucket-keys":
                    payload = self._read_json()
                    tree = node._my_merkle_snapshot()
                    keys = []
                    for b in payload.get("buckets", []):
                        keys.extend(tree.keys_in_bucket(b))
                    self._send(200, {"keys": keys})
                else:
                    self._send(404, {"error": "not found"})
            except Exception as e:  # noqa: BLE001
                self._send(500, {"error": str(e)})

    return Handler


_DASHBOARD_CACHE = None


def _dashboard_html():
    global _DASHBOARD_CACHE
    if _DASHBOARD_CACHE is None:
        path = os.path.join(os.path.dirname(__file__), "dashboard.html")
        with open(path, "rb") as f:
            _DASHBOARD_CACHE = f.read()
    return _DASHBOARD_CACHE


def node_status(node: NodeServer):
    with node._hints_lock:
        hint_counts = {owner: len(keys) for owner, keys in node.hints.items()}
    return {
        "node_id": node.node_id,
        "n": node.n, "r": node.r, "w": node.w,
        "statuses": node.membership.all_statuses(),
        "store_keys": len(node.store),
        "hints": hint_counts,
        "read_repair_ops": node._read_repair_ops,
        "anti_entropy_ops": node._anti_entropy_ops,
        "peers": {nid: list(addr) for nid, addr in node.peers.items()},
        "ring_vnodes": node.ring.vnodes,
    }
