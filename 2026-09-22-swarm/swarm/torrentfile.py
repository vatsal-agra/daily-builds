"""Build and read single-file .torrent metainfo, the real BEP-3 shape:

    {
      "announce": "<tracker url>",
      "info": {
        "name": "<file name>",
        "piece length": <bytes per piece>,
        "pieces": <concatenated 20-byte SHA-1 hashes, one per piece>,
        "length": <total file size in bytes>,
      }
    }

The info_hash that identifies a torrent on the wire is SHA-1 of the
*bencoded* `info` dict, byte for byte -- not of anything Python-level -- so
any two independent implementations that bencode the same info dict the
same way (canonical key order, no whitespace) derive the identical
info_hash without ever talking to each other. That's the property this
module is built to preserve exactly.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from . import bencode

DEFAULT_PIECE_LENGTH = 64 * 1024  # 64 KiB; small on purpose so a modest demo
# file still splits into enough pieces to exercise rarest-first selection.
SHA1_LEN = 20


@dataclass(frozen=True)
class TorrentInfo:
    name: str
    piece_length: int
    length: int
    pieces: bytes  # concatenated 20-byte SHA-1 digests
    announce: str

    @property
    def num_pieces(self) -> int:
        return len(self.pieces) // SHA1_LEN

    def piece_hash(self, index: int) -> bytes:
        return self.pieces[index * SHA1_LEN : (index + 1) * SHA1_LEN]

    def piece_size(self, index: int) -> int:
        """Actual byte length of piece `index` (the last piece is usually short)."""
        if index < 0 or index >= self.num_pieces:
            raise IndexError(f"piece index {index} out of range [0, {self.num_pieces})")
        if index == self.num_pieces - 1:
            remainder = self.length - self.piece_length * (self.num_pieces - 1)
            return remainder
        return self.piece_length

    def info_dict(self) -> dict:
        return {
            b"name": self.name.encode("utf-8"),
            b"piece length": self.piece_length,
            b"pieces": self.pieces,
            b"length": self.length,
        }

    def info_hash(self) -> bytes:
        return hashlib.sha1(bencode.encode(self.info_dict())).digest()

    def to_metainfo_dict(self) -> dict:
        return {b"announce": self.announce.encode("utf-8"), b"info": self.info_dict()}

    def to_bytes(self) -> bytes:
        return bencode.encode(self.to_metainfo_dict())


def create_torrent(file_path: str, announce: str, piece_length: int = DEFAULT_PIECE_LENGTH) -> TorrentInfo:
    if piece_length <= 0:
        raise ValueError("piece_length must be positive")
    size = os.path.getsize(file_path)
    if size == 0:
        raise ValueError("cannot create a torrent for an empty file")
    hashes = bytearray()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(piece_length)
            if not chunk:
                break
            hashes += hashlib.sha1(chunk).digest()
    name = os.path.basename(file_path)
    return TorrentInfo(
        name=name,
        piece_length=piece_length,
        length=size,
        pieces=bytes(hashes),
        announce=announce,
    )


def save_torrent(info: TorrentInfo, out_path: str) -> None:
    with open(out_path, "wb") as f:
        f.write(info.to_bytes())


def load_torrent(path: str) -> TorrentInfo:
    with open(path, "rb") as f:
        raw = f.read()
    return parse_torrent(raw)


def parse_torrent(raw: bytes) -> TorrentInfo:
    meta = bencode.decode(raw)
    if not isinstance(meta, dict) or b"info" not in meta or b"announce" not in meta:
        raise ValueError("not a valid .torrent metainfo dict")
    info = meta[b"info"]
    for key in (b"name", b"piece length", b"pieces", b"length"):
        if key not in info:
            raise ValueError(f"info dict missing required key {key!r}")
    pieces = info[b"pieces"]
    if len(pieces) % SHA1_LEN != 0:
        raise ValueError("pieces field is not a multiple of the SHA-1 digest length")
    return TorrentInfo(
        name=info[b"name"].decode("utf-8"),
        piece_length=info[b"piece length"],
        length=info[b"length"],
        pieces=pieces,
        announce=meta[b"announce"].decode("utf-8"),
    )
