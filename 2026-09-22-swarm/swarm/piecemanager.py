"""Piece-level state machine: rarest-first piece selection, 16 KiB block
request pipelining within a piece, and on-disk assembly with a SHA-1 check
before anything is trusted as "have".

Design choice, stated plainly rather than hidden: a piece is downloaded
from exactly *one* peer connection at a time (whichever connection is
assigned it). If that connection dies mid-piece, the partial bytes are
discarded and the piece goes back to MISSING for reassignment to any
peer -- including a different one. This is simpler than BitTorrent's real
multi-source block interleaving within a single piece, and slightly less
bandwidth-efficient on connection churn, but it keeps piece ownership
unambiguous (no double-write races) and is still a faithful, correct
implementation of rarest-first selection and block pipelining: different
*pieces* are still fetched from different peers concurrently, which is
exactly what proves genuine peer-to-peer flow in the swarm demo.
"""
from __future__ import annotations

import hashlib
import os
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .torrentfile import TorrentInfo

BLOCK_SIZE = 16 * 1024

MISSING = 0
DOWNLOADING = 1
HAVE = 2


class PieceHashMismatch(ValueError):
    def __init__(self, piece_index: int, peer_id: bytes):
        super().__init__(f"piece {piece_index} failed SHA-1 verification (supplied by peer {peer_id!r})")
        self.piece_index = piece_index
        self.peer_id = peer_id


def bitfield_to_indices(bits: bytes, num_pieces: int) -> Set[int]:
    """MSB of byte 0 is piece 0, per BEP-3."""
    have = set()
    for i in range(num_pieces):
        byte_idx, bit_idx = divmod(i, 8)
        if byte_idx >= len(bits):
            break
        if bits[byte_idx] & (0x80 >> bit_idx):
            have.add(i)
    return have


def indices_to_bitfield(indices: Set[int], num_pieces: int) -> bytes:
    nbytes = (num_pieces + 7) // 8
    out = bytearray(nbytes)
    for i in indices:
        byte_idx, bit_idx = divmod(i, 8)
        out[byte_idx] |= 0x80 >> bit_idx
    return bytes(out)


@dataclass
class _InProgress:
    buffer: bytearray
    received_mask: List[bool]


class PieceManager:
    def __init__(
        self,
        torrent: TorrentInfo,
        file_path: str,
        seed: bool = False,
        preseed_source: Optional[str] = None,
        preseed_pieces: Optional[Set[int]] = None,
    ):
        self.torrent = torrent
        self.file_path = file_path
        self.num_pieces = torrent.num_pieces
        self.lock = threading.RLock()

        self._state = [HAVE if seed else MISSING for _ in range(self.num_pieces)]
        self._assigned_peer: List[Optional[bytes]] = [None] * self.num_pieces
        self._in_progress: Dict[int, _InProgress] = {}
        self._piece_source: Dict[int, bytes] = {}

        self.peer_bitfields: Dict[bytes, Set[int]] = {}
        self.bytes_downloaded_from: Dict[bytes, int] = defaultdict(int)
        self.bytes_uploaded_to: Dict[bytes, int] = defaultdict(int)

        if seed and (preseed_source or preseed_pieces):
            raise ValueError("seed=True already implies every piece; preseed_source/preseed_pieces don't apply")

        os.makedirs(os.path.dirname(os.path.abspath(file_path)) or ".", exist_ok=True)
        if seed:
            actual = os.path.getsize(file_path)
            if actual != torrent.length:
                raise ValueError(
                    f"seed file {file_path!r} is {actual} bytes, torrent declares {torrent.length}"
                )
        else:
            # Pre-allocate a correctly-sized file so pieces can be written at
            # arbitrary offsets as they complete, in whatever order rarest-
            # first selection happens to fetch them.
            with open(file_path, "wb") as f:
                if torrent.length > 0:
                    f.seek(torrent.length - 1)
                    f.write(b"\x00")
            if preseed_pieces:
                if not preseed_source:
                    raise ValueError("preseed_pieces given without preseed_source")
                # A "partial seed": this peer already legitimately owns some
                # pieces (e.g. it's one of two peers each holding half a file
                # with no full copy anywhere else in the swarm) rather than
                # having downloaded them over the wire. Copy the real bytes
                # from the source and hash-verify them exactly like a
                # completed download would be, so a bad preseed spec can
                # never silently claim a piece this node doesn't actually
                # have correct bytes for.
                with open(preseed_source, "rb") as src, open(file_path, "r+b") as dst:
                    for idx in preseed_pieces:
                        if not (0 <= idx < self.num_pieces):
                            raise ValueError(f"preseed piece index {idx} out of range")
                        offset = idx * torrent.piece_length
                        size = torrent.piece_size(idx)
                        src.seek(offset)
                        chunk = src.read(size)
                        if hashlib.sha1(chunk).digest() != torrent.piece_hash(idx):
                            raise ValueError(f"preseed source does not match torrent for piece {idx}")
                        dst.seek(offset)
                        dst.write(chunk)
                        self._state[idx] = HAVE

    # -- bitfield / peer bookkeeping -------------------------------------

    def have_bitfield_bytes(self) -> bytes:
        with self.lock:
            have = {i for i, s in enumerate(self._state) if s == HAVE}
        return indices_to_bitfield(have, self.num_pieces)

    def set_peer_bitfield(self, peer_id: bytes, bits: bytes) -> None:
        with self.lock:
            self.peer_bitfields[peer_id] = bitfield_to_indices(bits, self.num_pieces)

    def mark_peer_has(self, peer_id: bytes, piece_index: int) -> None:
        if not (0 <= piece_index < self.num_pieces):
            raise ValueError(f"have message for out-of-range piece {piece_index}")
        with self.lock:
            self.peer_bitfields.setdefault(peer_id, set()).add(piece_index)

    def remove_peer(self, peer_id: bytes) -> None:
        with self.lock:
            self.peer_bitfields.pop(peer_id, None)
            for i in range(self.num_pieces):
                # Only a piece still actively DOWNLOADING from this peer
                # needs to be released back to MISSING. Without the state
                # check, a piece this peer *finished* supplying a while ago
                # would also get wiped back to MISSING here, because
                # _assigned_peer isn't otherwise cleared once a piece
                # completes -- silently uncounting a piece this node
                # genuinely, verifiably already has correct bytes for on
                # disk, purely because its original source later
                # disconnected.
                if self._assigned_peer[i] == peer_id and self._state[i] == DOWNLOADING:
                    self._assigned_peer[i] = None
                    self._state[i] = MISSING
                    self._in_progress.pop(i, None)

    def peer_is_interesting(self, peer_id: bytes) -> bool:
        """True if this peer has at least one piece we still need."""
        with self.lock:
            have = self.peer_bitfields.get(peer_id, set())
            return any(self._state[i] == MISSING for i in have)

    # -- rarest-first selection -------------------------------------------

    def _rarity(self, piece_index: int) -> int:
        return sum(1 for pieces in self.peer_bitfields.values() if piece_index in pieces)

    def choose_piece_for_peer(self, peer_id: bytes) -> Optional[int]:
        """Assign this peer connection the globally rarest piece it can supply
        that nobody else is currently downloading. Returns None if the peer
        has nothing we still need right now."""
        with self.lock:
            candidates = self.peer_bitfields.get(peer_id, set())
            needed = [i for i in candidates if self._state[i] == MISSING]
            if not needed:
                return None
            needed.sort(key=lambda i: (self._rarity(i), i))  # index as a deterministic tiebreak
            chosen = needed[0]
            self._state[chosen] = DOWNLOADING
            self._assigned_peer[chosen] = peer_id
            size = self.torrent.piece_size(chosen)
            num_blocks = (size + BLOCK_SIZE - 1) // BLOCK_SIZE
            self._in_progress[chosen] = _InProgress(bytearray(size), [False] * num_blocks)
            return chosen

    def blocks_for_piece(self, piece_index: int) -> List[Tuple[int, int]]:
        """(begin, length) for every block in this piece, in order."""
        size = self.torrent.piece_size(piece_index)
        blocks = []
        begin = 0
        while begin < size:
            length = min(BLOCK_SIZE, size - begin)
            blocks.append((begin, length))
            begin += length
        return blocks

    def release_piece(self, piece_index: int, peer_id: bytes) -> None:
        """Give up a piece this peer was assigned (e.g. on disconnect mid-piece)."""
        with self.lock:
            if self._assigned_peer[piece_index] == peer_id and self._state[piece_index] == DOWNLOADING:
                self._state[piece_index] = MISSING
                self._assigned_peer[piece_index] = None
                self._in_progress.pop(piece_index, None)

    # -- receiving data -----------------------------------------------------

    def receive_block(self, piece_index: int, begin: int, data: bytes, peer_id: bytes) -> bool:
        """Returns True iff this block completed and hash-verified the piece.

        `piece_index` is bounds-checked explicitly (raising ValueError, not
        letting Python's `list[-1]`-wraps-around or IndexError-on-overflow
        behavior decide what happens) because it comes straight off the wire
        from a peer that has no obligation to send us anything sane."""
        if not (0 <= piece_index < self.num_pieces):
            raise ValueError(f"piece index {piece_index} out of range [0, {self.num_pieces})")
        with self.lock:
            if self._state[piece_index] != DOWNLOADING or self._assigned_peer[piece_index] != peer_id:
                return False  # stale/duplicate/wrong-peer block; ignore silently
            prog = self._in_progress.get(piece_index)
            if prog is None:
                return False
            if begin < 0 or begin + len(data) > len(prog.buffer):
                raise ValueError(f"block [{begin}:{begin + len(data)}) out of range for piece of size {len(prog.buffer)}")
            prog.buffer[begin : begin + len(data)] = data
            block_idx = begin // BLOCK_SIZE
            if block_idx < len(prog.received_mask):
                prog.received_mask[block_idx] = True
            self.bytes_downloaded_from[peer_id] += len(data)

            if not all(prog.received_mask):
                return False

            digest = hashlib.sha1(bytes(prog.buffer)).digest()
            if digest != self.torrent.piece_hash(piece_index):
                self._state[piece_index] = MISSING
                self._assigned_peer[piece_index] = None
                self._in_progress.pop(piece_index, None)
                raise PieceHashMismatch(piece_index, peer_id)

            self._write_piece_to_disk(piece_index, bytes(prog.buffer))
            self._state[piece_index] = HAVE
            self._piece_source[piece_index] = peer_id
            # _assigned_peer's only meaning is "who this piece is currently
            # DOWNLOADING from"; once HAVE, that's no longer true, and
            # leaving the stale reference behind is exactly what let
            # remove_peer() wipe a completed piece back to MISSING when its
            # supplying peer later disconnected (see remove_peer's own
            # comment) -- clear it the moment the piece leaves DOWNLOADING.
            self._assigned_peer[piece_index] = None
            self._in_progress.pop(piece_index, None)
            return True

    def _write_piece_to_disk(self, piece_index: int, data: bytes) -> None:
        offset = piece_index * self.torrent.piece_length
        with open(self.file_path, "r+b") as f:
            f.seek(offset)
            f.write(data)

    def read_block_for_upload(self, piece_index: int, begin: int, length: int) -> bytes:
        if not (0 <= piece_index < self.num_pieces):
            raise ValueError(f"piece index {piece_index} out of range [0, {self.num_pieces})")
        if length < 0:
            # bytes.read(n) treats a negative n as "read to EOF": without this
            # check a peer could request length=-1 and get sent the rest of
            # the file, not one block -- an easy amplification/DoS footgun.
            raise ValueError(f"requested length must be >= 0, got {length}")
        with self.lock:
            if self._state[piece_index] != HAVE:
                raise ValueError(f"cannot serve piece {piece_index}: not HAVE")
            size = self.torrent.piece_size(piece_index)
        if begin < 0 or begin + length > size:
            raise ValueError(f"requested block [{begin}:{begin + length}) out of range for piece size {size}")
        offset = piece_index * self.torrent.piece_length + begin
        with open(self.file_path, "rb") as f:
            f.seek(offset)
            return f.read(length)

    def record_upload(self, peer_id: bytes, nbytes: int) -> None:
        with self.lock:
            self.bytes_uploaded_to[peer_id] += nbytes

    # -- status --------------------------------------------------------------

    def is_complete(self) -> bool:
        with self.lock:
            return all(s == HAVE for s in self._state)

    def have_count(self) -> int:
        with self.lock:
            return sum(1 for s in self._state if s == HAVE)

    def piece_source(self, piece_index: int) -> Optional[bytes]:
        with self.lock:
            return self._piece_source.get(piece_index)

    def state_snapshot(self) -> List[int]:
        with self.lock:
            return list(self._state)

    def verify_full_file(self) -> bool:
        """Recompute every piece hash straight from disk. Used as a final,
        independent integrity check -- doesn't trust in-memory HAVE state."""
        with open(self.file_path, "rb") as f:
            for i in range(self.num_pieces):
                f.seek(i * self.torrent.piece_length)
                chunk = f.read(self.torrent.piece_size(i))
                if hashlib.sha1(chunk).digest() != self.torrent.piece_hash(i):
                    return False
        return True
