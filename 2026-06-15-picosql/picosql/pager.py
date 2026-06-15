"""Paged file storage with a write-back cache and a rollback journal.

The database is a single file divided into fixed-size pages. Page 0 is the
*header* (magic, page count, catalog root, next table id). All other pages are
B+tree nodes (or zeroed/free).

Durability model
----------------
* Pages live in an in-memory cache; mutations mark them dirty.
* `begin()` snapshots the header fields.
* `commit()` atomically flushes dirty pages to disk: it first writes the
  *original* contents of every to-be-overwritten page (plus the original file
  length) to a journal file and fsyncs it, then overwrites the main file and
  fsyncs it, then removes the journal. If the process dies mid-commit, the next
  `Pager(path)` finds the journal and *rolls the file back* to its pre-commit
  state — so a commit is all-or-nothing even across a crash.
* `rollback()` (explicit ROLLBACK or a failed statement) just drops the dirty
  in-memory pages and restores the header snapshot; nothing was written to disk
  during the transaction, so on-disk state is already the committed state.
"""

from __future__ import annotations

import os
import struct
from typing import Dict, Optional, Set, Tuple

PAGE_SIZE = 4096
MAGIC = b"PICOSQL-fmt-v1\x00\x00"  # exactly 16 bytes
assert len(MAGIC) == 16

# Header layout within page 0 (after the 16-byte magic), all little-endian uint32.
_H_PAGE_SIZE = 16
_H_NUM_PAGES = 20
_H_CATALOG_ROOT = 24
_H_NEXT_TABLE_ID = 28


class Pager:
    def __init__(self, path: str):
        self.path = path
        self.journal_path = path + "-journal"
        self._cache: Dict[int, bytearray] = {}
        self._dirty: Set[int] = set()
        self._snapshot: Optional[Tuple[int, int, int]] = None

        new_file = not os.path.exists(path) or os.path.getsize(path) == 0
        # Open for read/write, create if missing.
        flags = os.O_RDWR | os.O_CREAT
        fd = os.open(path, flags, 0o644)
        self._fd = fd

        if not new_file:
            self._recover_if_needed()

        if os.fstat(self._fd).st_size == 0:
            self._init_header()
        else:
            self._load_header()

    # ---- header fields ----------------------------------------------------
    def _init_header(self) -> None:
        self.num_pages = 1  # page 0 (header) exists
        self.catalog_root = 0  # 0 == not yet created
        self.next_table_id = 1
        self._write_header_page()
        self.commit()  # persist a valid empty database

    def _write_header_page(self) -> None:
        buf = bytearray(PAGE_SIZE)
        buf[0:16] = MAGIC
        struct.pack_into("<I", buf, _H_PAGE_SIZE, PAGE_SIZE)
        struct.pack_into("<I", buf, _H_NUM_PAGES, self.num_pages)
        struct.pack_into("<I", buf, _H_CATALOG_ROOT, self.catalog_root)
        struct.pack_into("<I", buf, _H_NEXT_TABLE_ID, self.next_table_id)
        self._cache[0] = buf
        self._dirty.add(0)

    def _load_header(self) -> None:
        raw = self._read_from_disk(0)
        if bytes(raw[0:16]) != MAGIC:
            raise ValueError("not a PicoSQL database file (bad magic)")
        page_size = struct.unpack_from("<I", raw, _H_PAGE_SIZE)[0]
        if page_size != PAGE_SIZE:
            raise ValueError(f"page size mismatch: file={page_size}, build={PAGE_SIZE}")
        self.num_pages = struct.unpack_from("<I", raw, _H_NUM_PAGES)[0]
        self.catalog_root = struct.unpack_from("<I", raw, _H_CATALOG_ROOT)[0]
        self.next_table_id = struct.unpack_from("<I", raw, _H_NEXT_TABLE_ID)[0]
        self._cache[0] = bytearray(raw)

    def _sync_header_into_cache(self) -> None:
        """Refresh page 0 in cache from the current header attributes."""
        self._write_header_page()

    # ---- low-level disk I/O ----------------------------------------------
    def _read_from_disk(self, pageno: int) -> bytearray:
        os.lseek(self._fd, pageno * PAGE_SIZE, os.SEEK_SET)
        data = os.read(self._fd, PAGE_SIZE)
        if len(data) < PAGE_SIZE:
            data = data + b"\x00" * (PAGE_SIZE - len(data))
        return bytearray(data)

    def _write_to_disk(self, pageno: int, data: bytes) -> None:
        assert len(data) == PAGE_SIZE
        os.lseek(self._fd, pageno * PAGE_SIZE, os.SEEK_SET)
        os.write(self._fd, data)

    def _disk_page_count(self) -> int:
        return os.fstat(self._fd).st_size // PAGE_SIZE

    # ---- public page API --------------------------------------------------
    def read_page(self, pageno: int) -> bytes:
        if pageno in self._cache:
            return bytes(self._cache[pageno])
        raw = self._read_from_disk(pageno)
        self._cache[pageno] = raw
        return bytes(raw)

    def write_page(self, pageno: int, data: bytes) -> None:
        if len(data) != PAGE_SIZE:
            raise ValueError(f"page must be exactly {PAGE_SIZE} bytes, got {len(data)}")
        self._cache[pageno] = bytearray(data)
        self._dirty.add(pageno)

    def allocate_page(self) -> int:
        pageno = self.num_pages
        self.num_pages += 1
        self._cache[pageno] = bytearray(PAGE_SIZE)
        self._dirty.add(pageno)
        self._sync_header_into_cache()
        return pageno

    def set_catalog_root(self, pageno: int) -> None:
        self.catalog_root = pageno
        self._sync_header_into_cache()

    def alloc_table_id(self) -> int:
        tid = self.next_table_id
        self.next_table_id += 1
        self._sync_header_into_cache()
        return tid

    # ---- transaction boundaries ------------------------------------------
    def begin(self) -> None:
        self._snapshot = (self.num_pages, self.catalog_root, self.next_table_id)

    def rollback(self) -> None:
        # Drop every dirty (uncommitted) page so the next read re-fetches the
        # committed bytes from disk, then restore header fields.
        for pageno in self._dirty:
            self._cache.pop(pageno, None)
        self._dirty.clear()
        if self._snapshot is not None:
            self.num_pages, self.catalog_root, self.next_table_id = self._snapshot
        # Re-sync header in cache to committed values.
        self._cache.pop(0, None)
        self._snapshot = None

    def commit(self) -> None:
        if not self._dirty:
            self._snapshot = None
            return
        self._sync_header_into_cache()
        orig_disk_pages = self._disk_page_count()

        # 1. Write rollback journal: original bytes of overwritten pages + the
        #    original file length, so a crash here can be undone.
        to_save = sorted(p for p in self._dirty if p < orig_disk_pages)
        with open(self.journal_path, "wb") as jf:
            jf.write(b"PICOJRNL")
            jf.write(struct.pack("<I", orig_disk_pages))
            jf.write(struct.pack("<I", len(to_save)))
            for p in to_save:
                jf.write(struct.pack("<I", p))
                jf.write(bytes(self._read_from_disk(p)))
            jf.flush()
            os.fsync(jf.fileno())

        # 2. Overwrite main file with dirty pages, then fsync.
        for pageno in sorted(self._dirty):
            self._write_to_disk(pageno, bytes(self._cache[pageno]))
        os.fsync(self._fd)

        # 3. Commit point: remove journal (its absence means "fully applied").
        os.remove(self.journal_path)

        self._dirty.clear()
        self._snapshot = None

    def _recover_if_needed(self) -> None:
        if not os.path.exists(self.journal_path):
            return
        with open(self.journal_path, "rb") as jf:
            blob = jf.read()
        if len(blob) < 16 or blob[0:8] != b"PICOJRNL":
            os.remove(self.journal_path)  # garbage journal; ignore
            return
        orig_disk_pages = struct.unpack_from("<I", blob, 8)[0]
        count = struct.unpack_from("<I", blob, 12)[0]
        off = 16
        for _ in range(count):
            pageno = struct.unpack_from("<I", blob, off)[0]
            off += 4
            data = blob[off : off + PAGE_SIZE]
            off += PAGE_SIZE
            self._write_to_disk(pageno, bytes(data))
        # Truncate any pages appended by the interrupted commit.
        os.ftruncate(self._fd, orig_disk_pages * PAGE_SIZE)
        os.fsync(self._fd)
        os.remove(self.journal_path)

    def close(self) -> None:
        os.close(self._fd)
