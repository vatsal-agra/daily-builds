"""
Write-Ahead Log (WAL) — binary append-only log for durability.

Record format (each entry):
  [crc32: 4B][seq: 8B][type: 1B][klen: 4B][vlen: 4B][key: klen B][value: vlen B]

CRC covers everything after the 4-byte crc field.
"""

import struct
import os
from binascii import crc32
from pathlib import Path
from typing import Iterator

from .record import Record, RecordType

_HEADER_FMT = ">IQBIi"  # crc, seq, type, klen, vlen — note: we use signed i for vlen but treat as uint
# Actually let us use unsigned:
_HDR = struct.Struct(">IQBII")  # crc(4) seq(8) type(1) klen(4) vlen(4) = 17 bytes header + 4 crc = 21 bytes total
# We store crc separately in first 4 bytes, rest is payload header then data
# Layout: CRC(4) | SEQ(8) | TYPE(1) | KLEN(4) | VLEN(4) | KEY | VALUE
_CRC_SIZE = 4
_PAY_HDR = struct.Struct(">QBII")  # seq(8)+type(1)+klen(4)+vlen(4) = 17 bytes


def _compute_crc(payload: bytes) -> int:
    return crc32(payload) & 0xFFFFFFFF


class WAL:
    """Append-only Write-Ahead Log."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = open(path, "ab")

    def append(self, seq: int, rtype: RecordType, key: bytes, value: bytes) -> None:
        payload = _PAY_HDR.pack(seq, int(rtype), len(key), len(value)) + key + value
        crc = _compute_crc(payload)
        self._fh.write(struct.pack(">I", crc))
        self._fh.write(payload)
        self._fh.flush()

    def sync(self) -> None:
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def close(self) -> None:
        self._fh.close()

    def delete(self) -> None:
        self.close()
        if self.path.exists():
            self.path.unlink()

    @staticmethod
    def replay(path: Path) -> Iterator[Record]:
        """Yield Records from a WAL file, stopping at first corruption."""
        if not path.exists():
            return
        with open(path, "rb") as f:
            while True:
                crc_buf = f.read(_CRC_SIZE)
                if not crc_buf:
                    break
                if len(crc_buf) < _CRC_SIZE:
                    break  # truncated
                stored_crc = struct.unpack(">I", crc_buf)[0]
                hdr_buf = f.read(_PAY_HDR.size)
                if len(hdr_buf) < _PAY_HDR.size:
                    break
                seq, rtype_byte, klen, vlen = _PAY_HDR.unpack(hdr_buf)
                key = f.read(klen)
                value = f.read(vlen)
                if len(key) < klen or len(value) < vlen:
                    break
                payload = hdr_buf + key + value
                if _compute_crc(payload) != stored_crc:
                    break  # corrupted record — stop here
                yield Record(key, value, seq, RecordType(rtype_byte))
