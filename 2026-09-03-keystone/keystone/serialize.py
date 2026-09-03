"""Deterministic canonical serialization used everywhere a hash is taken.

Keystone doesn't hand-roll a binary wire format the way Bitcoin does — the
interesting "from scratch" content in this build is the elliptic-curve
crypto and the consensus protocol, not a bespoke binary framing format.
Instead every hashed structure is serialized via JSON with sorted keys and
no incidental whitespace, which is deterministic and portable, and used
consistently for hashing, signing, and the network wire format alike.
"""
from __future__ import annotations

import json


def canonical_bytes(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
