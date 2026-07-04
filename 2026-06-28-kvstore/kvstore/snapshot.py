"""Snapshot — a frozen sequence number for consistent reads."""


class Snapshot:
    """Opaque read handle that pins the DB to a specific sequence number."""

    __slots__ = ("seq",)

    def __init__(self, seq: int):
        self.seq = seq

    def __repr__(self):
        return f"Snapshot(seq={self.seq})"
