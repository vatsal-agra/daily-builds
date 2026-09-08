"""The four Kademlia RPCs, as plain dataclasses.

Every message carries `req_id` (correlates a response back to the request
that caused it) and `sender_id` (so the receiver knows who to reply to, and
-- critically -- so *every* message, request or response, feeds the
receiver's routing table: routing table entries are only ever created from
direct communication, never from third-party reports).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PingReq:
    req_id: int
    sender_id: int


@dataclass(frozen=True)
class PingResp:
    req_id: int
    sender_id: int


@dataclass(frozen=True)
class FindNodeReq:
    req_id: int
    sender_id: int
    target: int


@dataclass(frozen=True)
class FindNodeResp:
    req_id: int
    sender_id: int
    contacts: tuple[int, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FindValueReq:
    req_id: int
    sender_id: int
    key: int


@dataclass(frozen=True)
class FindValueResp:
    req_id: int
    sender_id: int
    value: bytes | None = None
    contacts: tuple[int, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StoreReq:
    req_id: int
    sender_id: int
    key: int
    value: bytes
    ttl: int


@dataclass(frozen=True)
class StoreResp:
    req_id: int
    sender_id: int
    ok: bool = True


REQUEST_TYPES = (PingReq, FindNodeReq, FindValueReq, StoreReq)
RESPONSE_TYPES = (PingResp, FindNodeResp, FindValueResp, StoreResp)
