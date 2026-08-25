"""Torrent file creation and parsing (single-file torrents, BEP 3 subset).

A .torrent file is a bencoded dict with an `announce` URL (the tracker)
and an `info` dict describing the file: its name, the piece length, and
the concatenation of every piece's raw 20-byte SHA-1 hash. The
torrent's "info-hash" — the identifier every peer and the tracker use
to refer to this specific torrent/swarm — is the SHA-1 of the *exact
bencoded bytes* of the info dict alone, which is why bencode's
deterministic dict-key-sorted encoding (see bencode.py) matters: two
implementations must produce byte-identical info-dict encodings for
the same logical info dict, or they'd compute different info-hashes
for what should be the same swarm.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field

from . import bencode

DEFAULT_PIECE_LENGTH = 256 * 1024  # 256 KiB, a typical real-world default


class TorrentError(ValueError):
    pass


@dataclass
class Torrent:
    announce: str
    name: str
    piece_length: int
    pieces: list  # list[bytes], each exactly 20 bytes (raw SHA-1)
    total_length: int
    info_hash: bytes = field(repr=False)  # 20 raw bytes
    comment: str = ""

    @property
    def num_pieces(self) -> int:
        return len(self.pieces)

    def piece_size(self, index: int) -> int:
        """Real byte length of piece `index` (the last piece is usually shorter)."""
        if index < 0 or index >= self.num_pieces:
            raise TorrentError(f"piece index {index} out of range")
        if index == self.num_pieces - 1:
            remainder = self.total_length - self.piece_length * (self.num_pieces - 1)
            return remainder
        return self.piece_length

    def info_hash_hex(self) -> str:
        return self.info_hash.hex()


def _hash_pieces(path: str, piece_length: int):
    """Read `path` sequentially and SHA-1 each fixed-size piece."""
    pieces = []
    total = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(piece_length)
            if not chunk:
                break
            pieces.append(hashlib.sha1(chunk).digest())
            total += len(chunk)
    if total == 0:
        raise TorrentError(f"cannot create a torrent for an empty file: {path}")
    return pieces, total


def build_info_dict(name: str, piece_length: int, pieces: list, total_length: int) -> dict:
    return {
        b"name": name.encode("utf-8"),
        b"piece length": piece_length,
        b"pieces": b"".join(pieces),
        b"length": total_length,
    }


def create_torrent(
    source_path: str,
    tracker_url: str,
    piece_length: int = DEFAULT_PIECE_LENGTH,
    comment: str = "",
) -> bytes:
    """Build a real bencoded .torrent file's bytes for `source_path`."""
    if piece_length <= 0:
        raise TorrentError("piece_length must be positive")
    if not os.path.isfile(source_path):
        raise TorrentError(f"not a regular file: {source_path}")

    pieces, total_length = _hash_pieces(source_path, piece_length)
    name = os.path.basename(source_path)
    info = build_info_dict(name, piece_length, pieces, total_length)

    top = {
        b"announce": tracker_url.encode("utf-8"),
        b"created by": b"skein/0.1.0",
        b"info": info,
    }
    if comment:
        top[b"comment"] = comment.encode("utf-8")
    return bencode.encode(top)


def compute_info_hash(info_dict: dict) -> bytes:
    return hashlib.sha1(bencode.encode(info_dict)).digest()


def parse_torrent(data: bytes) -> Torrent:
    try:
        top = bencode.decode(data)
    except bencode.BencodeError as e:
        raise TorrentError(f"not valid bencode: {e}") from e

    if not isinstance(top, dict) or b"info" not in top or b"announce" not in top:
        raise TorrentError("missing required top-level keys 'announce'/'info'")

    info = top[b"info"]
    if not isinstance(info, dict):
        raise TorrentError("'info' is not a dict")

    for key in (b"name", b"piece length", b"pieces", b"length"):
        if key not in info:
            raise TorrentError(f"info dict missing required key {key!r}")

    raw_pieces = info[b"pieces"]
    if not isinstance(raw_pieces, (bytes, bytearray)) or len(raw_pieces) % 20 != 0:
        raise TorrentError("'pieces' must be a byte string whose length is a multiple of 20")
    pieces = [bytes(raw_pieces[i:i + 20]) for i in range(0, len(raw_pieces), 20)]

    piece_length = info[b"piece length"]
    total_length = info[b"length"]
    if not isinstance(piece_length, int) or piece_length <= 0:
        raise TorrentError("'piece length' must be a positive integer")
    if not isinstance(total_length, int) or total_length <= 0:
        raise TorrentError("'length' must be a positive integer")

    expected_pieces = -(-total_length // piece_length)  # ceil div
    if expected_pieces != len(pieces):
        raise TorrentError(
            f"piece count mismatch: 'length'/'piece length' implies "
            f"{expected_pieces} pieces but 'pieces' encodes {len(pieces)}"
        )

    info_hash = compute_info_hash(info)

    return Torrent(
        announce=top[b"announce"].decode("utf-8", errors="replace"),
        name=info[b"name"].decode("utf-8", errors="replace"),
        piece_length=piece_length,
        pieces=pieces,
        total_length=total_length,
        info_hash=info_hash,
        comment=top.get(b"comment", b"").decode("utf-8", errors="replace"),
    )


def load_torrent_file(path: str) -> Torrent:
    with open(path, "rb") as f:
        return parse_torrent(f.read())
