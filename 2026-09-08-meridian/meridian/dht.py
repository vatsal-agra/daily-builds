"""DHTNode: the routing table, the storage, and the iterative lookup, all
wired together and driven by a Network.

Everything here runs as callbacks scheduled on the Network's event loop --
there is no threading and no async/await. A `Lookup` is a small state
machine object rather than a coroutine because that's the natural shape for
"a multi-round RPC exchange driven entirely by a discrete-event scheduler".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count

from . import nodeid
from .protocol import (
    FindNodeReq,
    FindNodeResp,
    FindValueReq,
    FindValueResp,
    PingReq,
    PingResp,
    StoreReq,
    StoreResp,
)
from .routing import DEFAULT_K, RoutingTable

ALPHA = 3
RPC_TIMEOUT = 150
DEFAULT_TTL = 2000
REPUBLISH_INTERVAL = 800          # how often the *original* publisher re-pushes a key
REPLICA_REPUBLISH_INTERVAL = 1000  # how often a node holding a *replica* re-pushes it
BUCKET_REFRESH_INTERVAL = 1200
MAINTENANCE_INTERVAL = 100


@dataclass
class StoredEntry:
    value: bytes
    expires_at: int
    origin: str  # 'owner' | 'replica'
    last_republished: int = 0


@dataclass
class PublishedKey:
    raw_key: bytes
    value: bytes
    ttl: int
    last_published: int


class Lookup:
    """One iterative FIND_NODE or FIND_VALUE lookup, run as a round-based
    state machine (Kademlia paper S2.3): each round queries `alpha` of the
    closest not-yet-queried known candidates in parallel and waits for all
    of that round's responses/timeouts before deciding whether to continue.
    Round-based alpha batching (rather than a continuously topped-up
    alpha-wide pipeline) is a deliberate simplification for a deterministic
    discrete-event simulator -- it changes nothing about which nodes get
    queried or what the lookup converges to, only how finely the querying
    is interleaved, which isn't observable here since there's no wall-clock
    benefit to squeeze out of tighter pipelining in a simulation.

    Termination follows the paper: a round that doesn't turn up anyone
    closer than the current best triggers one final round against any of
    the k closest known candidates that haven't been queried yet, and then
    the lookup ends.
    """

    def __init__(self, owner: "DHTNode", target: int, find_value: bool, on_complete):
        self.owner = owner
        self.target = target
        self.find_value = find_value
        self.on_complete = on_complete
        self.k = owner.k
        self.alpha = owner.alpha

        self.shortlist: dict[int, None] = {}
        for c in owner.routing_table.closest(target, self.k):
            self.shortlist[c] = None
        self.queried: set[int] = set()
        self._pending_this_round: set[int] = set()
        self._best_dist: int | None = self._closest_dist()
        self._did_final_round = False
        self._found_value: bytes | None = None
        self._finished = False

        self.hops = 0  # number of RPC round-trips that got a real response
        self.rounds = 0

        owner._trace("lookup_start", node=owner.id, target=target, find_value=find_value)
        self._run_round()

    # -- helpers -----------------------------------------------------
    def _k_closest(self) -> list[int]:
        return sorted(self.shortlist, key=lambda nid: nodeid.distance(self.target, nid))[: self.k]

    def _closest_dist(self) -> int | None:
        kc = self._k_closest()
        return nodeid.distance(self.target, kc[0]) if kc else None

    def _run_round(self, final: bool = False) -> None:
        if self._finished:
            return
        pool = self._k_closest() if final else sorted(
            self.shortlist, key=lambda nid: nodeid.distance(self.target, nid)
        )
        budget = self.k if final else self.alpha
        to_query = [c for c in pool if c not in self.queried][:budget]
        if not to_query:
            self._finish()
            return
        self.rounds += 1
        self._pending_this_round = set(to_query)
        for contact in to_query:
            self.queried.add(contact)
            self.owner._send_find(
                contact,
                self.target,
                self.find_value,
                on_response=lambda resp, c=contact: self._on_response(c, resp),
                on_timeout=lambda c=contact: self._on_timeout(c),
            )

    def _on_response(self, contact: int, resp) -> None:
        self._pending_this_round.discard(contact)
        if self._finished:
            return
        self.hops += 1
        self.owner._trace("lookup_hop", node=self.owner.id, target=self.target, queried=contact, ok=True)
        if self.find_value and isinstance(resp, FindValueResp) and resp.value is not None:
            self._found_value = resp.value
            self._finish()
            return
        for c in resp.contacts:
            if c != self.owner.id:
                self.shortlist.setdefault(c, None)
        self._maybe_advance()

    def _on_timeout(self, contact: int) -> None:
        self._pending_this_round.discard(contact)
        if self._finished:
            return
        self.owner._trace("lookup_hop", node=self.owner.id, target=self.target, queried=contact, ok=False)
        self._maybe_advance()

    def _maybe_advance(self) -> None:
        if self._pending_this_round:
            return  # still waiting on responses/timeouts from this round
        new_best = self._closest_dist()
        improved = new_best is not None and (self._best_dist is None or new_best < self._best_dist)
        if improved:
            self._best_dist = new_best
            self._run_round()
            return
        unqueried_k = [c for c in self._k_closest() if c not in self.queried]
        if unqueried_k and not self._did_final_round:
            self._did_final_round = True
            self._run_round(final=True)
        else:
            self._finish()

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.owner._trace(
            "lookup_done",
            node=self.owner.id,
            target=self.target,
            hops=self.hops,
            rounds=self.rounds,
            result=list(self._k_closest()),
            value_found=self._found_value is not None,
        )
        self.on_complete(self._k_closest(), self._found_value)


class DHTNode:
    def __init__(
        self,
        node_id: int,
        network,
        k: int = DEFAULT_K,
        alpha: int = ALPHA,
        rpc_timeout: int = RPC_TIMEOUT,
        rng=None,
        trace=None,
    ):
        self.id = node_id
        self.network = network
        self.k = k
        self.alpha = alpha
        self.rpc_timeout = rpc_timeout
        self._rng = rng
        self._trace = trace or (lambda kind, **fields: None)

        self.routing_table = RoutingTable(node_id, k=k)
        self.storage: dict[int, StoredEntry] = {}
        self.published_keys: dict[int, PublishedKey] = {}
        self.pending_requests: dict[int, callable] = {}
        self._req_ids = count()

        network.register(self)

    # -- wire-level plumbing -----------------------------------------------------
    def _next_req_id(self) -> int:
        return next(self._req_ids)

    def _rpc(self, target_id: int, make_msg, on_ok, on_timeout, timeout: int | None = None) -> None:
        req_id = self._next_req_id()
        msg = make_msg(req_id)
        self.pending_requests[req_id] = on_ok
        target_node = self.network.nodes.get(target_id)

        def deliver():
            if target_node is not None:
                target_node.handle_message(self.id, msg)

        self.network.send(self.id, target_id, deliver)

        def on_expire():
            cb = self.pending_requests.pop(req_id, None)
            if cb is not None:
                on_timeout()

        self.network.schedule_in(timeout or self.rpc_timeout, on_expire)

    def _reply(self, target_id: int, resp_msg) -> None:
        target_node = self.network.nodes.get(target_id)

        def deliver():
            if target_node is not None:
                target_node.handle_message(self.id, resp_msg)

        self.network.send(self.id, target_id, deliver)

    def _send_find(self, target_id: int, key: int, find_value: bool, on_response, on_timeout) -> None:
        if find_value:
            make = lambda rid: FindValueReq(rid, self.id, key)
        else:
            make = lambda rid: FindNodeReq(rid, self.id, key)
        self._rpc(target_id, make, on_ok=on_response, on_timeout=on_timeout)

    # -- routing table maintenance -----------------------------------------------------
    def record_contact(self, other_id: int) -> None:
        """The core Kademlia rule: *any* message received, request or
        response, updates the sender's routing-table entry."""
        status, info = self.routing_table.record(other_id)
        if status != "ping_head":
            return
        idx, head = info["idx"], info["head"]
        if head is None:
            return

        def on_ping_ok(_resp):
            self.routing_table.buckets[idx].touch(head)  # refresh head to MRU
            self.routing_table.resolve_ping_head(idx, other_id, head_alive=True)

        def on_ping_timeout():
            self.routing_table.resolve_ping_head(idx, other_id, head_alive=False)

        self._rpc(head, lambda rid: PingReq(rid, self.id), on_ping_ok, on_ping_timeout)

    # -- message dispatch -----------------------------------------------------
    def handle_message(self, sender_id: int, msg) -> None:
        self.record_contact(sender_id)
        now = self.network.time

        if isinstance(msg, PingReq):
            self._reply(sender_id, PingResp(msg.req_id, self.id))

        elif isinstance(msg, FindNodeReq):
            contacts = tuple(self.routing_table.closest(msg.target, self.k))
            self._reply(sender_id, FindNodeResp(msg.req_id, self.id, contacts))

        elif isinstance(msg, FindValueReq):
            entry = self.storage.get(msg.key)
            if entry is not None and entry.expires_at > now:
                self._reply(sender_id, FindValueResp(msg.req_id, self.id, value=entry.value))
            else:
                contacts = tuple(self.routing_table.closest(msg.key, self.k))
                self._reply(sender_id, FindValueResp(msg.req_id, self.id, value=None, contacts=contacts))

        elif isinstance(msg, StoreReq):
            existing = self.storage.get(msg.key)
            origin = existing.origin if existing is not None else "replica"
            self.storage[msg.key] = StoredEntry(
                value=msg.value, expires_at=now + msg.ttl, origin=origin, last_republished=now
            )
            self._trace("stored", node=self.id, key=msg.key, size=len(msg.value), expires_at=now + msg.ttl, from_=sender_id)
            self._reply(sender_id, StoreResp(msg.req_id, self.id, ok=True))

        elif isinstance(msg, (PingResp, FindNodeResp, FindValueResp, StoreResp)):
            cb = self.pending_requests.pop(msg.req_id, None)
            if cb is not None:
                cb(msg)

        else:
            raise TypeError(f"unhandled message type: {type(msg)!r}")

    # -- public API: lookups -----------------------------------------------------
    def lookup_nodes(self, target: int, on_complete) -> Lookup:
        return Lookup(self, target, find_value=False, on_complete=lambda contacts, val: on_complete(contacts))

    def lookup_value(self, key: int, on_complete) -> Lookup:
        return Lookup(self, key, find_value=True, on_complete=lambda contacts, val: on_complete(val, contacts))

    # -- public API: bootstrap -----------------------------------------------------
    def bootstrap(self, contact_id: int, on_complete=None) -> None:
        """Join the network via one already-known contact: seed the
        routing table with it, then run a self-lookup, which -- as a side
        effect of every response feeding record_contact() -- populates the
        routing table with real neighbors along the way."""
        if contact_id == self.id:
            raise ValueError("cannot bootstrap from self")
        self.record_contact(contact_id)
        self.lookup_nodes(self.id, lambda contacts: on_complete(contacts) if on_complete else None)

    def _store_local(self, key_id: int, value: bytes, ttl: int, origin: str) -> None:
        """Refresh (or create) this node's own local copy of a key it is
        publishing or holding a replica of. This matters: a node that only
        ever pushed STORE RPCs *out* to its peers on republish, without
        also refreshing its own copy's expiry, would silently let its own
        replica lapse even while faithfully keeping everyone else's alive
        -- caught while writing tests/test_storage.py, fixed here rather
        than left for Phase 3 to "discover"."""
        now = self.network.time
        existing = self.storage.get(key_id)
        keep_origin = existing.origin if existing is not None and existing.origin == "owner" else origin
        self.storage[key_id] = StoredEntry(value=value, expires_at=now + ttl, origin=keep_origin, last_republished=now)

    # -- public API: key/value store -----------------------------------------------------
    def put(self, raw_key: bytes, value: bytes, ttl: int = DEFAULT_TTL, on_complete=None) -> int:
        key_id = nodeid.sha1_int(raw_key)
        self.published_keys[key_id] = PublishedKey(
            raw_key=raw_key, value=value, ttl=ttl, last_published=self.network.time
        )
        self._store_local(key_id, value, ttl, origin="owner")
        self._trace("put_start", node=self.id, key=key_id, size=len(value))
        self.lookup_nodes(key_id, lambda contacts: self._replicate(key_id, value, ttl, contacts, on_complete))
        return key_id

    def _replicate(self, key_id: int, value: bytes, ttl: int, contacts, on_complete) -> None:
        if not contacts:
            if on_complete:
                on_complete(0, 0)
            return
        total = len(contacts)
        state = {"ok": 0, "done": 0}

        def make_cb(_contact):
            def cb(resp):
                state["done"] += 1
                if resp is not None and getattr(resp, "ok", False):
                    state["ok"] += 1
                if state["done"] == total and on_complete:
                    on_complete(state["ok"], total)

            return cb

        for c in contacts:
            cb = make_cb(c)
            self._rpc(
                c,
                lambda rid, key_id=key_id, value=value, ttl=ttl: StoreReq(rid, self.id, key_id, value, ttl),
                on_ok=cb,
                on_timeout=lambda cb=cb: cb(None),
            )

    def get(self, raw_key: bytes, on_complete) -> int:
        key_id = nodeid.sha1_int(raw_key)
        self._trace("get_start", node=self.id, key=key_id)
        local = self.storage.get(key_id)
        if local is not None and local.expires_at > self.network.time:
            self._trace("get_result", node=self.id, key=key_id, found=True, local=True)
            on_complete(local.value)
            return key_id

        def done(value, contacts):
            self._trace("get_result", node=self.id, key=key_id, found=value is not None, local=False)
            on_complete(value)

        self.lookup_value(key_id, done)
        return key_id

    # -- periodic maintenance -----------------------------------------------------
    def tick_maintenance(self) -> None:
        now = self.network.time

        for key_id, pk in list(self.published_keys.items()):
            if now - pk.last_published >= REPUBLISH_INTERVAL:
                pk.last_published = now
                self._store_local(key_id, pk.value, pk.ttl, origin="owner")
                self.lookup_nodes(key_id, lambda contacts, key_id=key_id, pk=pk: self._replicate(key_id, pk.value, pk.ttl, contacts, None))

        for key_id, entry in list(self.storage.items()):
            if entry.origin == "replica" and entry.expires_at > now and now - entry.last_republished >= REPLICA_REPUBLISH_INTERVAL:
                value = entry.value
                self._store_local(key_id, value, DEFAULT_TTL, origin="replica")
                self.lookup_nodes(
                    key_id,
                    lambda contacts, key_id=key_id, value=value: self._replicate(key_id, value, DEFAULT_TTL, contacts, None),
                )

        expired = [key_id for key_id, entry in self.storage.items() if entry.expires_at <= now]
        for key_id in expired:
            self._trace("expire", node=self.id, key=key_id)
            del self.storage[key_id]

        if self._rng is not None:
            for idx, bucket in enumerate(self.routing_table.buckets):
                if len(bucket) > 0 and now - bucket.last_refreshed >= BUCKET_REFRESH_INTERVAL:
                    bucket.last_refreshed = now
                    target = nodeid.random_id_in_bucket(self.id, idx, self._rng)
                    self._trace("bucket_refresh", node=self.id, bucket=idx)
                    self.lookup_nodes(target, lambda contacts: None)
