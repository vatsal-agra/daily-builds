"""The two operations Skein ever sends over the network.

Both are small, immutable, and — critically — idempotent to apply:
applying the same InsertOp twice is a no-op the second time (its id
already exists), and applying the same DeleteOp twice just tombstones
an already-tombstoned character. That idempotence is what lets the
simulated network duplicate messages without corrupting anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .ids import CharId


@dataclass(frozen=True)
class InsertOp:
    """Insert `char` immediately after the character `origin` (or at the
    very start of the document if `origin` is None)."""

    id: CharId
    char: str
    origin: Optional[CharId]

    def __post_init__(self) -> None:
        if len(self.char) != 1:
            raise ValueError(f"InsertOp.char must be a single character, got {self.char!r}")


@dataclass(frozen=True)
class DeleteOp:
    """Tombstone the character identified by `id`."""

    id: CharId
