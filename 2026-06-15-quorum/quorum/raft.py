"""Pure Raft node state machine.

This module implements a single Raft server with NO I/O of its own. Every method
that could cause network traffic instead *returns a list of Envelopes* for the
caller (the cluster) to route through the deterministic network. Time is modeled
as integer "ticks": the cluster calls :meth:`Node.tick` once per time unit.

The implementation follows the Raft paper (Ongaro & Ousterhout, "In Search of an
Understandable Consensus Algorithm"), Figure 2, including:
  * leader election with the up-to-date-log voting restriction,
  * log replication with the consistency check and conflict-based fast backtrack,
  * the commit rule that a leader only advances commitIndex for entries of its
    own term (and a no-op entry appended on election so prior-term entries can be
    committed indirectly),
  * the term rule: any RPC carrying a higher term demotes the receiver.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Optional


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class Role(str, Enum):
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"


# --------------------------------------------------------------------------- #
# Log entries and RPC messages
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LogEntry:
    term: int
    command: Any  # ("put", k, v) | ("get", k) | ("noop",)


@dataclass(frozen=True)
class RequestVote:
    term: int
    candidate_id: int
    last_log_index: int
    last_log_term: int


@dataclass(frozen=True)
class RequestVoteResp:
    term: int
    vote_granted: bool


@dataclass(frozen=True)
class AppendEntries:
    term: int
    leader_id: int
    prev_log_index: int
    prev_log_term: int
    entries: tuple  # tuple[LogEntry, ...]
    leader_commit: int


@dataclass(frozen=True)
class AppendEntriesResp:
    term: int
    success: bool
    # Index up to which the follower's log now matches the leader (success only).
    match_index: int = 0
    # Fast-backtrack hints (failure only).
    conflict_index: int = 0
    conflict_term: int = -1


@dataclass(frozen=True)
class InstallSnapshot:
    term: int
    leader_id: int
    last_included_index: int
    last_included_term: int
    snapshot: Any  # opaque state-machine snapshot (here: dict of kv)


@dataclass(frozen=True)
class InstallSnapshotResp:
    term: int
    match_index: int


@dataclass(frozen=True)
class Envelope:
    src: int
    dst: int
    body: Any


@dataclass
class Config:
    election_min: int = 6
    election_max: int = 12
    heartbeat_interval: int = 1


# --------------------------------------------------------------------------- #
# The Raft node
# --------------------------------------------------------------------------- #
class Node:
    def __init__(self, node_id: int, peers: list[int], rng, config: Config):
        self.id = node_id
        self.peers = list(peers)
        self.rng = rng
        self.cfg = config

        # --- Persistent state (survives crash/restart) ---
        self.current_term = 0
        self.voted_for: Optional[int] = None
        # log[0] is a sentinel. Real entries are 1-indexed.
        self.log: list[LogEntry] = [LogEntry(term=0, command=("noop",))]
        # Snapshot metadata (log compaction). base_index is the index of the
        # sentinel: everything <= base_index lives in the snapshot, not the log.
        self.snapshot_last_index = 0
        self.snapshot_last_term = 0
        self.snapshot: dict = {}

        # --- Volatile state ---
        self.role = Role.FOLLOWER
        self.commit_index = 0
        self.last_applied = 0
        self.leader_id: Optional[int] = None

        # --- Leader volatile state ---
        self.next_index: dict[int, int] = {}
        self.match_index: dict[int, int] = {}

        # --- Election bookkeeping ---
        self.votes_granted: set[int] = set()

        # --- Timers (in ticks) ---
        self.election_elapsed = 0
        self.election_timeout = self._rand_timeout()
        self.heartbeat_elapsed = 0

        # --- Replicated state machine (key/value store) ---
        self.kv: dict = {}

    # ------------------------------------------------------------------ #
    # Log helpers (snapshot-aware indexing)
    # ------------------------------------------------------------------ #
    @property
    def base_index(self) -> int:
        return self.snapshot_last_index

    def last_log_index(self) -> int:
        return self.base_index + len(self.log) - 1

    def _slot(self, index: int) -> int:
        """Translate an absolute log index into a position in self.log."""
        return index - self.base_index

    def term_at(self, index: int) -> int:
        if index == self.snapshot_last_index:
            return self.snapshot_last_term
        slot = self._slot(index)
        if slot < 0 or slot >= len(self.log):
            return -1
        return self.log[slot].term

    def entry_at(self, index: int) -> Optional[LogEntry]:
        slot = self._slot(index)
        if slot <= 0 or slot >= len(self.log):
            return None
        return self.log[slot]

    def last_log_term(self) -> int:
        return self.log[-1].term

    def _rand_timeout(self) -> int:
        return self.rng.randint(self.cfg.election_min, self.cfg.election_max)

    # ------------------------------------------------------------------ #
    # Role transitions
    # ------------------------------------------------------------------ #
    def _become_follower(self, term: int, leader: Optional[int] = None):
        self.role = Role.FOLLOWER
        if term > self.current_term:
            self.current_term = term
            self.voted_for = None
        self.leader_id = leader
        self.votes_granted.clear()
        self.next_index.clear()
        self.match_index.clear()

    def _become_candidate(self) -> list[Envelope]:
        self.role = Role.CANDIDATE
        self.current_term += 1
        self.voted_for = self.id
        self.leader_id = None
        self.votes_granted = {self.id}
        self.election_elapsed = 0
        self.election_timeout = self._rand_timeout()
        out = []
        for p in self.peers:
            out.append(
                Envelope(
                    self.id,
                    p,
                    RequestVote(
                        term=self.current_term,
                        candidate_id=self.id,
                        last_log_index=self.last_log_index(),
                        last_log_term=self.last_log_term(),
                    ),
                )
            )
        return out

    def _become_leader(self) -> list[Envelope]:
        self.role = Role.LEADER
        self.leader_id = self.id
        nxt = self.last_log_index() + 1
        self.next_index = {p: nxt for p in self.peers}
        self.match_index = {p: 0 for p in self.peers}
        self.heartbeat_elapsed = 0
        # Append a no-op so we can commit entries from earlier terms (paper §5.4.2).
        self.log.append(LogEntry(term=self.current_term, command=("noop",)))
        return self._broadcast_append()

    # ------------------------------------------------------------------ #
    # Driving time forward
    # ------------------------------------------------------------------ #
    def tick(self) -> list[Envelope]:
        if self.role == Role.LEADER:
            self.heartbeat_elapsed += 1
            if self.heartbeat_elapsed >= self.cfg.heartbeat_interval:
                self.heartbeat_elapsed = 0
                return self._broadcast_append()
            return []
        else:
            self.election_elapsed += 1
            if self.election_elapsed >= self.election_timeout:
                return self._become_candidate()
            return []

    # ------------------------------------------------------------------ #
    # Client proposals (leader only)
    # ------------------------------------------------------------------ #
    def propose(self, command) -> tuple[bool, Optional[int]]:
        """Append a command to the leader's log. Returns (accepted, index)."""
        if self.role != Role.LEADER:
            return (False, None)
        self.log.append(LogEntry(term=self.current_term, command=command))
        return (True, self.last_log_index())

    def replicate_now(self) -> list[Envelope]:
        if self.role != Role.LEADER:
            return []
        return self._broadcast_append()

    # ------------------------------------------------------------------ #
    # AppendEntries construction
    # ------------------------------------------------------------------ #
    def _broadcast_append(self) -> list[Envelope]:
        out = []
        for p in self.peers:
            out.append(self._make_append(p))
        return [e for e in out if e is not None]

    def _make_append(self, peer: int) -> Optional[Envelope]:
        ni = self.next_index.get(peer, self.last_log_index() + 1)
        prev_index = ni - 1
        # If the follower is behind our snapshot, ship the snapshot instead.
        if prev_index < self.base_index:
            return Envelope(
                self.id,
                peer,
                InstallSnapshot(
                    term=self.current_term,
                    leader_id=self.id,
                    last_included_index=self.snapshot_last_index,
                    last_included_term=self.snapshot_last_term,
                    snapshot=dict(self.snapshot),
                ),
            )
        prev_term = self.term_at(prev_index)
        entries = tuple(self.log[self._slot(ni):])
        return Envelope(
            self.id,
            peer,
            AppendEntries(
                term=self.current_term,
                leader_id=self.id,
                prev_log_index=prev_index,
                prev_log_term=prev_term,
                entries=entries,
                leader_commit=self.commit_index,
            ),
        )

    # ------------------------------------------------------------------ #
    # Message dispatch
    # ------------------------------------------------------------------ #
    def step(self, env: Envelope) -> list[Envelope]:
        body = env.body
        # Term rule: a higher term always demotes us to follower first.
        if getattr(body, "term", -1) > self.current_term:
            self._become_follower(body.term)

        if isinstance(body, RequestVote):
            return self._handle_request_vote(env)
        if isinstance(body, RequestVoteResp):
            return self._handle_request_vote_resp(env)
        if isinstance(body, AppendEntries):
            return self._handle_append_entries(env)
        if isinstance(body, AppendEntriesResp):
            return self._handle_append_entries_resp(env)
        if isinstance(body, InstallSnapshot):
            return self._handle_install_snapshot(env)
        if isinstance(body, InstallSnapshotResp):
            return self._handle_install_snapshot_resp(env)
        return []

    # --- RequestVote (receiver) ---
    def _handle_request_vote(self, env: Envelope) -> list[Envelope]:
        rv: RequestVote = env.body
        grant = False
        if rv.term < self.current_term:
            grant = False
        else:
            up_to_date = (rv.last_log_term, rv.last_log_index) >= (
                self.last_log_term(),
                self.last_log_index(),
            )
            if self.voted_for in (None, rv.candidate_id) and up_to_date:
                grant = True
                self.voted_for = rv.candidate_id
                self.election_elapsed = 0  # granting a vote resets our timer
        return [
            Envelope(
                self.id,
                env.src,
                RequestVoteResp(term=self.current_term, vote_granted=grant),
            )
        ]

    # --- RequestVoteResp (candidate) ---
    def _handle_request_vote_resp(self, env: Envelope) -> list[Envelope]:
        resp: RequestVoteResp = env.body
        if self.role != Role.CANDIDATE or resp.term != self.current_term:
            return []
        if resp.vote_granted:
            self.votes_granted.add(env.src)
            if len(self.votes_granted) >= self._majority():
                return self._become_leader()
        return []

    def _majority(self) -> int:
        return (len(self.peers) + 1) // 2 + 1

    # --- AppendEntries (receiver) ---
    def _handle_append_entries(self, env: Envelope) -> list[Envelope]:
        ae: AppendEntries = env.body
        if ae.term < self.current_term:
            return [self._ae_fail(env.src)]

        # Valid leader for our term: become/stay follower and reset timer.
        self._become_follower(ae.term, leader=ae.leader_id)
        self.election_elapsed = 0

        # Consistency check against prev_log_index/term.
        if ae.prev_log_index > self.last_log_index():
            return [self._ae_fail(env.src, conflict_index=self.last_log_index() + 1)]

        if ae.prev_log_index >= self.base_index:
            local_prev_term = self.term_at(ae.prev_log_index)
            if local_prev_term != ae.prev_log_term:
                # Find the first index of the conflicting term for fast backtrack.
                conflict_term = local_prev_term
                ci = ae.prev_log_index
                while ci > self.base_index and self.term_at(ci - 1) == conflict_term:
                    ci -= 1
                return [
                    self._ae_fail(
                        env.src, conflict_index=ci, conflict_term=conflict_term
                    )
                ]

        # Append / overwrite entries, but only truncate on a genuine conflict.
        idx = ae.prev_log_index + 1
        for off, entry in enumerate(ae.entries):
            abs_idx = idx + off
            if abs_idx <= self.base_index:
                continue  # already covered by snapshot
            if abs_idx <= self.last_log_index():
                if self.term_at(abs_idx) != entry.term:
                    # Conflict: delete this and everything after, then append.
                    del self.log[self._slot(abs_idx):]
                    self.log.append(entry)
            else:
                self.log.append(entry)

        # Advance commit index.
        if ae.leader_commit > self.commit_index:
            last_new = ae.prev_log_index + len(ae.entries)
            self.commit_index = min(ae.leader_commit, last_new)

        match = ae.prev_log_index + len(ae.entries)
        return [
            Envelope(
                self.id,
                env.src,
                AppendEntriesResp(
                    term=self.current_term, success=True, match_index=match
                ),
            )
        ]

    def _ae_fail(self, dst, conflict_index=0, conflict_term=-1) -> Envelope:
        return Envelope(
            self.id,
            dst,
            AppendEntriesResp(
                term=self.current_term,
                success=False,
                conflict_index=conflict_index,
                conflict_term=conflict_term,
            ),
        )

    # --- AppendEntriesResp (leader) ---
    def _handle_append_entries_resp(self, env: Envelope) -> list[Envelope]:
        resp: AppendEntriesResp = env.body
        if self.role != Role.LEADER or resp.term != self.current_term:
            return []
        peer = env.src
        if resp.success:
            self.match_index[peer] = max(self.match_index.get(peer, 0), resp.match_index)
            self.next_index[peer] = self.match_index[peer] + 1
            self._maybe_advance_commit()
            return []
        else:
            # Fast backtrack using conflict hints.
            if resp.conflict_term >= 0:
                # Does the leader have any entry with conflict_term?
                last_idx_of_term = -1
                for i in range(self.last_log_index(), self.base_index, -1):
                    if self.term_at(i) == resp.conflict_term:
                        last_idx_of_term = i
                        break
                if last_idx_of_term >= 0:
                    self.next_index[peer] = last_idx_of_term + 1
                else:
                    self.next_index[peer] = max(1, resp.conflict_index)
            else:
                self.next_index[peer] = max(1, resp.conflict_index)
            return [self._make_append(peer)]

    def _maybe_advance_commit(self):
        # Find the highest N replicated on a majority where log[N].term == term.
        for n in range(self.last_log_index(), self.commit_index, -1):
            if self.term_at(n) != self.current_term:
                continue
            count = 1  # leader itself
            for p in self.peers:
                if self.match_index.get(p, 0) >= n:
                    count += 1
            if count >= self._majority():
                self.commit_index = n
                break

    # --- InstallSnapshot (receiver) ---
    def _handle_install_snapshot(self, env: Envelope) -> list[Envelope]:
        snap: InstallSnapshot = env.body
        if snap.term < self.current_term:
            return [
                Envelope(
                    self.id,
                    env.src,
                    InstallSnapshotResp(term=self.current_term, match_index=0),
                )
            ]
        self._become_follower(snap.term, leader=snap.leader_id)
        self.election_elapsed = 0

        if snap.last_included_index <= self.snapshot_last_index:
            # Stale snapshot, ignore but ack our state.
            return [
                Envelope(
                    self.id,
                    env.src,
                    InstallSnapshotResp(
                        term=self.current_term, match_index=self.snapshot_last_index
                    ),
                )
            ]

        # Install the snapshot, discarding any prefix of the log it covers.
        if snap.last_included_index < self.last_log_index() and (
            self.term_at(snap.last_included_index) == snap.last_included_term
        ):
            keep = self.log[self._slot(snap.last_included_index) + 1:]
        else:
            keep = []
        self.snapshot = dict(snap.snapshot)
        self.snapshot_last_index = snap.last_included_index
        self.snapshot_last_term = snap.last_included_term
        self.log = [LogEntry(term=snap.last_included_term, command=("noop",))] + keep
        self.kv = dict(snap.snapshot)
        self.commit_index = max(self.commit_index, snap.last_included_index)
        self.last_applied = max(self.last_applied, snap.last_included_index)
        return [
            Envelope(
                self.id,
                env.src,
                InstallSnapshotResp(
                    term=self.current_term, match_index=snap.last_included_index
                ),
            )
        ]

    def _handle_install_snapshot_resp(self, env: Envelope) -> list[Envelope]:
        resp: InstallSnapshotResp = env.body
        if self.role != Role.LEADER or resp.term != self.current_term:
            return []
        peer = env.src
        self.match_index[peer] = max(self.match_index.get(peer, 0), resp.match_index)
        self.next_index[peer] = self.match_index[peer] + 1
        return [self._make_append(peer)]

    # ------------------------------------------------------------------ #
    # Applying committed entries to the state machine
    # ------------------------------------------------------------------ #
    def apply_committed(self) -> list[tuple[int, LogEntry, Any]]:
        """Apply newly-committed entries. Returns (index, entry, result) list."""
        out = []
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            entry = self.entry_at(self.last_applied)
            if entry is None:
                continue
            result = self._apply_to_kv(entry.command)
            out.append((self.last_applied, entry, result))
        return out

    def _apply_to_kv(self, command):
        if not isinstance(command, tuple) or not command:
            return None
        op = command[0]
        if op == "put":
            self.kv[command[1]] = command[2]
            return "ok"
        if op == "get":
            return self.kv.get(command[1])
        if op == "del":
            existed = command[1] in self.kv
            self.kv.pop(command[1], None)
            return "ok" if existed else "absent"
        return None  # noop

    # ------------------------------------------------------------------ #
    # Log compaction
    # ------------------------------------------------------------------ #
    def take_snapshot(self):
        """Compact the log up to last_applied into a snapshot."""
        if self.last_applied <= self.base_index:
            return
        cut = self.last_applied
        cut_term = self.term_at(cut)
        keep = self.log[self._slot(cut) + 1:]
        self.snapshot = dict(self.kv)
        self.snapshot_last_index = cut
        self.snapshot_last_term = cut_term
        self.log = [LogEntry(term=cut_term, command=("noop",))] + keep

    # ------------------------------------------------------------------ #
    # Crash / restart
    # ------------------------------------------------------------------ #
    def on_restart(self):
        """Reset volatile election state after a restart (persistent state kept)."""
        self.role = Role.FOLLOWER
        self.leader_id = None
        self.votes_granted.clear()
        self.next_index.clear()
        self.match_index.clear()
        self.election_elapsed = 0
        self.election_timeout = self._rand_timeout()
        self.heartbeat_elapsed = 0
