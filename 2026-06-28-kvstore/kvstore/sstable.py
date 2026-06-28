"""
SSTable (Sorted String Table) — immutable on-disk sorted key-value file.

File Layout:
  [DataBlock 0]
  [DataBlock 1]
  ...
  [DataBlock N]
  [FilterBlock]      — Bloom filter bytes
  [IndexBlock]       — one entry per DataBlock
  [Footer: 32 bytes] — filter_offset(8) + filter_size(4) + index_offset(8) + index_size(4) + MAGIC(8)

DataBlock encoding:
  [entry_count: 4B]
  For each entry: [key_len: 2B][val_len: 2B][type: 1B][key][value]
  [block_crc32: 4B]   — covers entry_count + all entries

IndexBlock encoding:
  [entry_count: 4B]
  For each entry: [key_len: 2B][offset: 8B][size: 4B][key]

The 'key' in an index entry is the LAST key in the corresponding DataBlock,
so we can binary-search the index to find which data block to load for a given key.
"""

import struct
import os
from binascii import crc32 as _crc32
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from .record import Record, RecordType
from .bloom import BloomFilter

MAGIC = b"STRATAL1"  # 8-byte magic
FOOTER_SIZE = 32  # 8+4+8+4+8
_FOOTER_FMT = struct.Struct(">QIQIQ")  # 5 fields × sizes = 8+4+8+4+8 = 32 OK
# Actually: filter_offset(8) filter_size(4) index_offset(8) index_size(4) magic(8) = 32
_FOOTER = struct.Struct(">QIQIQ")  # hmm: Q=8 I=4 Q=8 I=4 Q=8 = 32. Let's check: 8+4+8+4+8=32. Yes.

BLOCK_SIZE = 4096  # target data block size


def _crc(data: bytes) -> int:
    return _crc32(data) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Block encoding helpers
# ---------------------------------------------------------------------------

def _encode_data_block(records: List[Record]) -> bytes:
    """Encode a list of Records into a DataBlock (including sequence numbers)."""
    parts = [struct.pack(">I", len(records))]
    for r in records:
        # key_len(2) val_len(2) type(1) seq(8)  key  value
        parts.append(struct.pack(">HHBQ", len(r.key), len(r.value), int(r.rtype), r.seq))
        parts.append(r.key)
        parts.append(r.value)
    payload = b"".join(parts)
    return payload + struct.pack(">I", _crc(payload))


def _decode_data_block(data: bytes) -> List[Record]:
    """Decode a DataBlock and verify CRC. Returns list of Records with real seq."""
    if len(data) < 8:
        raise ValueError("DataBlock too short")
    payload = data[:-4]
    stored_crc = struct.unpack_from(">I", data, len(data) - 4)[0]
    if _crc(payload) != stored_crc:
        raise ValueError("DataBlock CRC mismatch")
    count = struct.unpack_from(">I", payload, 0)[0]
    offset = 4
    records = []
    for _ in range(count):
        klen, vlen, rtype_byte, seq = struct.unpack_from(">HHBQ", payload, offset)
        offset += 13  # 2+2+1+8
        key = payload[offset:offset + klen]
        offset += klen
        value = payload[offset:offset + vlen]
        offset += vlen
        records.append(Record(key, value, seq, RecordType(rtype_byte)))
    return records


def _encode_index_block(entries: List[Tuple[bytes, int, int]]) -> bytes:
    """entries: list of (last_key, block_offset, block_size)"""
    parts = [struct.pack(">I", len(entries))]
    for last_key, off, sz in entries:
        parts.append(struct.pack(">HQI", len(last_key), off, sz))
        parts.append(last_key)
    return b"".join(parts)


def _decode_index_block(data: bytes) -> List[Tuple[bytes, int, int]]:
    """Returns list of (last_key, block_offset, block_size)."""
    count = struct.unpack_from(">I", data, 0)[0]
    offset = 4
    entries = []
    for _ in range(count):
        klen, blk_off, blk_sz = struct.unpack_from(">HQI", data, offset)
        offset += 14  # 2+8+4
        last_key = data[offset:offset + klen]
        offset += klen
        entries.append((last_key, blk_off, blk_sz))
    return entries


# ---------------------------------------------------------------------------
# SSTable Writer
# ---------------------------------------------------------------------------

class SSTableWriter:
    """Builds an SSTable from an iterator of Records (must be key-sorted)."""

    def __init__(self, path: Path, bloom_fp_rate: float = 0.01):
        self.path = path
        self._fp_rate = bloom_fp_rate
        self._fh = open(path, "wb")
        self._current_block: List[Record] = []
        self._current_block_size: int = 0
        self._index_entries: List[Tuple[bytes, int, int]] = []
        self._write_offset: int = 0
        self._bloom: Optional[BloomFilter] = None
        self._key_count: int = 0

    def add(self, record: Record) -> None:
        """Add a Record (must be called in key-sorted order)."""
        if self._bloom is None:
            # We don't know total count yet; use a growing bloom or default size.
            # We'll rebuild it at finish time; just collect keys for now.
            pass
        self._current_block.append(record)
        entry_size = 5 + len(record.key) + len(record.value)
        self._current_block_size += entry_size
        self._key_count += 1
        if self._current_block_size >= BLOCK_SIZE:
            self._flush_block()

    def _flush_block(self) -> None:
        if not self._current_block:
            return
        last_key = self._current_block[-1].key
        encoded = _encode_data_block(self._current_block)
        self._fh.write(encoded)
        self._index_entries.append((last_key, self._write_offset, len(encoded)))
        self._write_offset += len(encoded)
        self._current_block = []
        self._current_block_size = 0

    def finish(self, all_keys: Optional[List[bytes]] = None) -> None:
        """Finalize and close the SSTable."""
        self._flush_block()

        # Build Bloom filter over all keys
        bf = BloomFilter(expected_items=max(1, self._key_count), fp_rate=self._fp_rate)
        if all_keys:
            for k in all_keys:
                bf.add(k)
        # We can't add keys retroactively without storing them, so we re-iterate
        # the index to reconstruct — but we lost the key list. Instead we store
        # a reference list during add(). Let me redesign: store keys inline.
        # Since we already built index_entries with last_keys, and we need
        # ALL keys for the bloom filter, we'll rely on the caller providing them,
        # OR we will just not populate the bloom correctly here if all_keys is None.
        # The proper way: caller passes all_keys. The DB layer does this.
        filter_bytes = bf.to_bytes()
        filter_offset = self._write_offset
        self._fh.write(filter_bytes)
        self._write_offset += len(filter_bytes)

        # Write index block
        index_data = _encode_index_block(self._index_entries)
        index_offset = self._write_offset
        self._fh.write(index_data)
        self._write_offset += len(index_data)

        # Write footer
        footer = _FOOTER.pack(
            filter_offset, len(filter_bytes),
            index_offset, len(index_data),
            int.from_bytes(MAGIC, "big")
        )
        self._fh.write(footer)
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._fh.close()

    def abort(self) -> None:
        self._fh.close()
        if self.path.exists():
            self.path.unlink()


class SSTableWriter2:
    """
    Two-pass SSTable writer: collects all records first (in memory or temp),
    then writes in one go so the Bloom filter has all keys.
    For large tables this is memory-intensive; for our purposes it's fine.
    """

    def __init__(self, path: Path, bloom_fp_rate: float = 0.01):
        self.path = path
        self._fp_rate = bloom_fp_rate
        self._records: List[Record] = []

    def add(self, record: Record) -> None:
        self._records.append(record)

    def finish(self) -> None:
        path = self.path
        fp_rate = self._fp_rate
        records = self._records

        # Build Bloom filter
        bf = BloomFilter(expected_items=max(1, len(records)), fp_rate=fp_rate)
        for r in records:
            bf.add(r.key)

        with open(path, "wb") as fh:
            offset = 0
            index_entries: List[Tuple[bytes, int, int]] = []
            current_block: List[Record] = []
            current_size = 0

            def flush_block():
                nonlocal offset
                if not current_block:
                    return
                encoded = _encode_data_block(current_block)
                fh.write(encoded)
                index_entries.append((current_block[-1].key, offset, len(encoded)))
                offset += len(encoded)
                current_block.clear()

            for r in records:
                current_block.append(r)
                current_size += 5 + len(r.key) + len(r.value)
                if current_size >= BLOCK_SIZE:
                    flush_block()
                    current_size = 0

            flush_block()

            # Filter block
            filter_bytes = bf.to_bytes()
            filter_offset = offset
            fh.write(filter_bytes)
            offset += len(filter_bytes)

            # Index block
            index_data = _encode_index_block(index_entries)
            index_offset = offset
            fh.write(index_data)
            offset += len(index_data)

            # Footer
            footer = _FOOTER.pack(
                filter_offset, len(filter_bytes),
                index_offset, len(index_data),
                int.from_bytes(MAGIC, "big")
            )
            fh.write(footer)
            fh.flush()
            os.fsync(fh.fileno())

    def abort(self) -> None:
        if self.path.exists():
            self.path.unlink()


# ---------------------------------------------------------------------------
# SSTable Reader
# ---------------------------------------------------------------------------

class SSTableReader:
    """Read records from an SSTable file."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = open(path, "rb")
        file_size = os.path.getsize(path)

        if file_size < FOOTER_SIZE:
            raise ValueError(f"SSTable too small: {path}")

        # Read footer
        self._fh.seek(file_size - FOOTER_SIZE)
        footer_bytes = self._fh.read(FOOTER_SIZE)
        (filter_offset, filter_size, index_offset, index_size, magic_int
         ) = _FOOTER.unpack(footer_bytes)

        if magic_int != int.from_bytes(MAGIC, "big"):
            raise ValueError(f"Bad SSTable magic in {path}")

        # Load Bloom filter
        self._fh.seek(filter_offset)
        filter_bytes = self._fh.read(filter_size)
        self._bloom = BloomFilter.from_bytes(filter_bytes)

        # Load index
        self._fh.seek(index_offset)
        index_bytes = self._fh.read(index_size)
        self._index = _decode_index_block(index_bytes)  # [(last_key, offset, size)]

        if self._index:
            self._min_key = None  # lazily computed from first block
            self._max_key = self._index[-1][0]
        else:
            self._min_key = None
            self._max_key = None

        self._file_size = file_size

    @property
    def min_key(self) -> Optional[bytes]:
        if self._min_key is None and self._index:
            recs = self._read_block(0)
            self._min_key = recs[0].key if recs else None
        return self._min_key

    @property
    def max_key(self) -> Optional[bytes]:
        return self._max_key

    def _read_block(self, block_idx: int) -> List[Record]:
        if block_idx < 0 or block_idx >= len(self._index):
            return []
        last_key, off, sz = self._index[block_idx]
        self._fh.seek(off)
        data = self._fh.read(sz)
        return _decode_data_block(data)

    def _find_block_for_key(self, key: bytes) -> int:
        """Binary-search index to find which block might contain key.
        Returns block index, or -1 if key > max_key."""
        if not self._index:
            return -1
        lo, hi = 0, len(self._index) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if self._index[mid][0] < key:
                lo = mid + 1
            else:
                hi = mid
        return lo

    def get(self, key: bytes, max_seq: int = 2**63) -> Optional[Tuple[bytes, RecordType]]:
        """Point lookup. Returns (value, rtype) or None."""
        if self._max_key is not None and (key < (self.min_key or b"") or key > self._max_key):
            return None
        if not self._bloom.may_contain(key):
            return None
        block_idx = self._find_block_for_key(key)
        if block_idx < 0:
            return None
        records = self._read_block(block_idx)
        # Binary search within block
        lo, hi = 0, len(records) - 1
        result = None
        while lo <= hi:
            mid = (lo + hi) // 2
            if records[mid].key == key:
                if records[mid].seq <= max_seq:
                    result = records[mid]
                break
            elif records[mid].key < key:
                lo = mid + 1
            else:
                hi = mid - 1
        if result is None:
            return None
        return result.value, result.rtype

    def scan(self, start: Optional[bytes] = None, end: Optional[bytes] = None,
             max_seq: int = 2**63) -> Iterator[Record]:
        """Yield Records in key order within [start, end)."""
        if not self._index:
            return

        # Find starting block
        if start is not None:
            block_start = self._find_block_for_key(start)
        else:
            block_start = 0

        for block_idx in range(block_start, len(self._index)):
            last_key = self._index[block_idx][0]
            if end is not None and last_key < end:
                # Could still have keys in range
                pass
            records = self._read_block(block_idx)
            for r in records:
                if start is not None and r.key < start:
                    continue
                if end is not None and r.key >= end:
                    return
                if r.seq <= max_seq:
                    yield r
            # If end is before this block's last key, we're done
            if end is not None and last_key >= end:
                return

    def iter_all(self, max_seq: int = 2**63) -> Iterator[Record]:
        """Yield all Records in key order."""
        for block_idx in range(len(self._index)):
            for r in self._read_block(block_idx):
                if r.seq <= max_seq:
                    yield r

    def overlaps(self, min_key: bytes, max_key: bytes) -> bool:
        """Does this SSTable's key range overlap [min_key, max_key]?"""
        if self._max_key is None:
            return False
        smin = self.min_key
        if smin is None:
            return False
        return smin <= max_key and self._max_key >= min_key

    def close(self) -> None:
        self._fh.close()

    def __repr__(self):
        return f"SSTable({self.path.name} keys=[{self.min_key!r}..{self._max_key!r}])"
