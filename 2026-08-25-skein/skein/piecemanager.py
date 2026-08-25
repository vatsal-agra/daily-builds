"""Piece/block bookkeeping: bitfields, SHA-1 verification, disk I/O, and
rarest-first piece selection.

BitTorrent splits a file into fixed-size *pieces* (SHA-1 verified as a
unit) and further splits each piece into fixed-size *blocks* (the unit
actually requested/transferred over the wire, 16 KiB by convention —
real clients cap it there so no single peer message ever blocks a
socket for too long). This module tracks, per piece, which blocks have
arrived, assembles + verifies completed pieces against the torrent's
hash, and writes verified bytes to the right offset of the output file.
"""

from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass, field

BLOCK_SIZE = 16 * 1024  # 16 KiB, the conventional BitTorrent block size


class PieceError(ValueError):
    pass


@dataclass
class PieceState:
    index: int
    length: int
    num_blocks: int
    blocks: dict = field(default_factory=dict)  # block_offset -> bytes
    verified: bool = False

    def is_complete(self) -> bool:
        received = sum(len(b) for b in self.blocks.values())
        return received >= self.length

    def assemble(self) -> bytes:
        buf = bytearray(self.length)
        for offset, data in self.blocks.items():
            buf[offset:offset + len(data)] = data
        return bytes(buf)


def block_plan(piece_length: int):
    """Yield (offset, length) for every block in a piece of `piece_length`."""
    offset = 0
    while offset < piece_length:
        length = min(BLOCK_SIZE, piece_length - offset)
        yield offset, length
        offset += length


class PieceManager:
    """Owns the on-disk output file and the download/verification state
    for one torrent. Thread-safe: a node's network threads and its
    piece-selection logic can call this concurrently.
    """

    def __init__(self, torrent, dest_path: str, have_all: bool = False):
        self.torrent = torrent
        self.dest_path = dest_path
        self._lock = threading.RLock()
        self._in_progress: dict[int, PieceState] = {}
        self._have = bytearray(torrent.num_pieces)  # 1 byte per piece, 0/1
        # peer_availability[piece_index] = number of known peers with that piece
        self._availability = [0] * torrent.num_pieces

        # Preallocate a full-size sparse file so every piece's byte range
        # is always a valid seek/write target, even before we own that
        # piece's data.
        if not os.path.exists(dest_path):
            with open(dest_path, "wb") as f:
                if torrent.total_length > 0:
                    f.seek(torrent.total_length - 1)
                    f.write(b"\0")

        if have_all:
            for i in range(torrent.num_pieces):
                self._have[i] = 1

    # -- bitfield -----------------------------------------------------

    def bitfield_bytes(self) -> bytes:
        """Pack the have-array into the wire bitfield format (MSB-first)."""
        n = self.torrent.num_pieces
        out = bytearray((n + 7) // 8)
        with self._lock:
            for i in range(n):
                if self._have[i]:
                    out[i // 8] |= 0x80 >> (i % 8)
        return bytes(out)

    def _check_index(self, index: int) -> None:
        if not (0 <= index < self.torrent.num_pieces):
            raise PieceError(f"piece index {index} out of range [0, {self.torrent.num_pieces})")

    def has_piece(self, index: int) -> bool:
        self._check_index(index)
        with self._lock:
            return bool(self._have[index])

    def is_complete(self) -> bool:
        with self._lock:
            return all(self._have)

    def missing_pieces(self):
        with self._lock:
            return [i for i, v in enumerate(self._have) if not v]

    def progress(self):
        with self._lock:
            done = sum(self._have)
        return done, self.torrent.num_pieces

    def bytes_have(self) -> int:
        """Exact byte count of pieces we currently hold verified copies of."""
        with self._lock:
            have_indices = [i for i, v in enumerate(self._have) if v]
        return sum(self.torrent.piece_size(i) for i in have_indices)

    # -- availability tracking (for rarest-first) ----------------------

    def note_peer_bitfield(self, indices):
        for i in indices:
            self._check_index(i)  # an oversized bitfield is a protocol violation
        with self._lock:
            for i in indices:
                self._availability[i] += 1

    def note_peer_have(self, index: int):
        self._check_index(index)
        with self._lock:
            self._availability[index] += 1

    def forget_peer(self, indices):
        # Teardown/cleanup code: must never raise, even if `indices`
        # somehow contains a bogus index (e.g. a connection that was
        # dropped mid-handshake for sending an out-of-range HAVE before
        # ever getting validated) — silently skip anything invalid.
        with self._lock:
            for i in indices:
                if 0 <= i < len(self._availability):
                    self._availability[i] = max(0, self._availability[i] - 1)

    def next_piece_rarest_first(self, peer_has: set):
        """Pick the rarest piece (by known swarm availability) that we're
        missing and the given peer (`peer_has`, a set of piece indices)
        actually has. Returns None if no such piece exists.
        Ties are broken by lowest index for reproducibility.
        """
        with self._lock:
            candidates = [
                i for i in range(self.torrent.num_pieces)
                if not self._have[i] and i in peer_has and i not in self._in_progress
            ]
            if not candidates:
                # allow re-requesting a piece already in progress (from a
                # different peer) if nothing untouched remains
                candidates = [
                    i for i in range(self.torrent.num_pieces)
                    if not self._have[i] and i in peer_has
                ]
            if not candidates:
                return None
            candidates.sort(key=lambda i: (self._availability[i], i))
            return candidates[0]

    # -- block-level I/O ------------------------------------------------

    def receive_block(self, index: int, offset: int, data: bytes) -> bool:
        """Store one received block. Returns True iff this completed and
        successfully verified the whole piece (and it was written to disk).
        Raises PieceError if a completed piece fails SHA-1 verification.
        """
        with self._lock:
            if self._have[index]:
                return False  # duplicate/late block for an already-done piece
            piece_len = self.torrent.piece_size(index)
            state = self._in_progress.setdefault(
                index,
                PieceState(index=index, length=piece_len,
                           num_blocks=len(list(block_plan(piece_len)))),
            )
            state.blocks[offset] = data
            if not state.is_complete():
                return False

            assembled = state.assemble()
            digest = hashlib.sha1(assembled).digest()
            if digest != self.torrent.pieces[index]:
                # Corrupt/malicious peer data: drop it and let the caller
                # re-request the piece from someone else.
                del self._in_progress[index]
                raise PieceError(
                    f"piece {index} failed SHA-1 verification "
                    f"(got {digest.hex()[:10]}…, want {self.torrent.pieces[index].hex()[:10]}…)"
                )

            self._write_piece(index, assembled)
            self._have[index] = 1
            del self._in_progress[index]
            return True

    def _write_piece(self, index: int, data: bytes) -> None:
        piece_offset = index * self.torrent.piece_length
        with open(self.dest_path, "r+b") as f:
            f.seek(piece_offset)
            f.write(data)

    def has_block(self, index: int, offset: int) -> bool:
        """True if `offset` within piece `index` has already been received
        (whether or not the whole piece has completed/verified yet).
        """
        with self._lock:
            if self._have[index]:
                return True
            state = self._in_progress.get(index)
            return state is not None and offset in state.blocks

    def read_block(self, index: int, offset: int, length: int) -> bytes:
        """Read raw bytes for serving an upload request (seeder-side)."""
        if not self.has_piece(index):
            raise PieceError(f"cannot serve piece {index}: not fully downloaded")
        piece_offset = index * self.torrent.piece_length + offset
        with open(self.dest_path, "rb") as f:
            f.seek(piece_offset)
            return f.read(length)
