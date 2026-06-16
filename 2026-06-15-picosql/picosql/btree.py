"""A B+tree keyed by 64-bit integer rowids, stored over a Pager.

Leaf nodes hold (key, value-bytes) cells in sorted order and a pointer to the
next leaf (for ordered range scans). Internal nodes hold separator keys and
child pointers. Inserts split full nodes and propagate splits up to the root;
a root split grows the tree by one level. Nodes are (de)serialized whole — read
a page into a Python object, mutate, write it back — which trades a little speed
for a lot of clarity and correctness.
"""

from __future__ import annotations

import bisect
import struct
from typing import Iterator, List, Optional, Tuple

from .pager import PAGE_SIZE, Pager

_LEAF = 1
_INTERNAL = 2

# Leaf header: type(1) + num_cells(2) + next_leaf(4)
_LEAF_HEADER = 7
# Internal header: type(1) + num_keys(2) + child0(4)
_INTERNAL_HEADER = 7


class _Leaf:
    __slots__ = ("pageno", "keys", "values", "next_leaf")

    def __init__(self, pageno: int):
        self.pageno = pageno
        self.keys: List[int] = []
        self.values: List[bytes] = []
        self.next_leaf = 0


class _Internal:
    __slots__ = ("pageno", "keys", "children")

    def __init__(self, pageno: int):
        self.pageno = pageno
        self.keys: List[int] = []
        self.children: List[int] = []


class RowTooLarge(Exception):
    pass


class BTree:
    def __init__(self, pager: Pager, root: int):
        self.pager = pager
        self.root = root  # caller persists this if it changes after insert

    # ---- (de)serialization ----------------------------------------------
    def _load(self, pageno: int):
        raw = self.pager.read_page(pageno)
        ntype = raw[0]
        if ntype == _LEAF:
            node = _Leaf(pageno)
            n = struct.unpack_from("<H", raw, 1)[0]
            node.next_leaf = struct.unpack_from("<I", raw, 3)[0]
            off = _LEAF_HEADER
            for _ in range(n):
                key = struct.unpack_from("<q", raw, off)[0]
                off += 8
                vlen = struct.unpack_from("<I", raw, off)[0]
                off += 4
                val = bytes(raw[off : off + vlen])
                off += vlen
                node.keys.append(key)
                node.values.append(val)
            return node
        elif ntype == _INTERNAL:
            node = _Internal(pageno)
            n = struct.unpack_from("<H", raw, 1)[0]
            child0 = struct.unpack_from("<I", raw, 3)[0]
            node.children.append(child0)
            off = _INTERNAL_HEADER
            for _ in range(n):
                key = struct.unpack_from("<q", raw, off)[0]
                off += 8
                child = struct.unpack_from("<I", raw, off)[0]
                off += 4
                node.keys.append(key)
                node.children.append(child)
            return node
        raise ValueError(f"page {pageno} is not a B+tree node (type byte {ntype})")

    def _serialize(self, node) -> Optional[bytes]:
        """Return page bytes, or None if the node does not fit in a page."""
        if isinstance(node, _Leaf):
            buf = bytearray(PAGE_SIZE)
            buf[0] = _LEAF
            struct.pack_into("<H", buf, 1, len(node.keys))
            struct.pack_into("<I", buf, 3, node.next_leaf)
            off = _LEAF_HEADER
            for key, val in zip(node.keys, node.values):
                if off + 12 + len(val) > PAGE_SIZE:
                    return None
                struct.pack_into("<q", buf, off, key)
                off += 8
                struct.pack_into("<I", buf, off, len(val))
                off += 4
                buf[off : off + len(val)] = val
                off += len(val)
            return bytes(buf)
        else:
            buf = bytearray(PAGE_SIZE)
            buf[0] = _INTERNAL
            struct.pack_into("<H", buf, 1, len(node.keys))
            struct.pack_into("<I", buf, 3, node.children[0])
            off = _INTERNAL_HEADER
            for key, child in zip(node.keys, node.children[1:]):
                if off + 12 > PAGE_SIZE:
                    return None
                struct.pack_into("<q", buf, off, key)
                off += 8
                struct.pack_into("<I", buf, off, child)
                off += 4
            return bytes(buf)

    def _store(self, node) -> None:
        data = self._serialize(node)
        if data is None:
            raise RuntimeError("internal error: node overflow not handled")
        self.pager.write_page(node.pageno, data)

    def _new_leaf(self) -> _Leaf:
        return _Leaf(self.pager.allocate_page())

    def _new_internal(self) -> _Internal:
        return _Internal(self.pager.allocate_page())

    # ---- public ops ------------------------------------------------------
    def insert(self, key: int, value: bytes) -> None:
        # A brand-new tree (root==0) starts as a single empty leaf.
        if self.root == 0:
            leaf = self._new_leaf()
            self.root = leaf.pageno
            self._store(leaf)
        split = self._insert(self.root, key, value)
        if split is not None:
            sep, right = split
            new_root = self._new_internal()
            new_root.children = [self.root, right]
            new_root.keys = [sep]
            self._store(new_root)
            self.root = new_root.pageno

    def _insert(self, pageno: int, key: int, value: bytes) -> Optional[Tuple[int, int]]:
        node = self._load(pageno)
        if isinstance(node, _Leaf):
            idx = bisect.bisect_left(node.keys, key)
            if idx < len(node.keys) and node.keys[idx] == key:
                node.values[idx] = value  # replace existing
            else:
                node.keys.insert(idx, key)
                node.values.insert(idx, value)
            if self._serialize(node) is not None:
                self._store(node)
                return None
            return self._split_leaf(node, key, value)
        else:
            i = bisect.bisect_right(node.keys, key)
            child = node.children[i]
            res = self._insert(child, key, value)
            if res is None:
                return None
            sep, newchild = res
            node.keys.insert(i, sep)
            node.children.insert(i + 1, newchild)
            if self._serialize(node) is not None:
                self._store(node)
                return None
            return self._split_internal(node)

    def _split_leaf(self, node: _Leaf, key: int, value: bytes) -> Tuple[int, int]:
        # node already has the new cell inserted but doesn't fit. Split by
        # cumulative byte size so both halves fit (works for variable values).
        total = len(node.keys)
        if total < 2:
            raise RowTooLarge(
                f"row of {len(value)} bytes is too large for a {PAGE_SIZE}-byte page"
            )
        # Find a split point where the left half fits in a page.
        sizes = [12 + len(v) for v in node.values]
        budget = PAGE_SIZE - _LEAF_HEADER
        acc = 0
        split_at = 0
        for i, s in enumerate(sizes):
            if acc + s > budget or i >= total - 1:
                break
            acc += s
            split_at = i + 1
        if split_at == 0:
            split_at = 1
        if split_at >= total:
            split_at = total - 1

        right = self._new_leaf()
        right.keys = node.keys[split_at:]
        right.values = node.values[split_at:]
        right.next_leaf = node.next_leaf
        node.keys = node.keys[:split_at]
        node.values = node.values[:split_at]
        node.next_leaf = right.pageno

        # Both halves must now fit (a single oversized cell would have raised).
        if self._serialize(node) is None or self._serialize(right) is None:
            raise RowTooLarge(
                f"row too large to fit in a {PAGE_SIZE}-byte page"
            )
        self._store(node)
        self._store(right)
        return right.keys[0], right.pageno

    def _split_internal(self, node: _Internal) -> Tuple[int, int]:
        m = len(node.keys)
        j = m // 2
        sep = node.keys[j]
        right = self._new_internal()
        right.keys = node.keys[j + 1 :]
        right.children = node.children[j + 1 :]
        node.keys = node.keys[:j]
        node.children = node.children[: j + 1]
        self._store(node)
        self._store(right)
        return sep, right.pageno

    def search(self, key: int) -> Optional[bytes]:
        if self.root == 0:
            return None
        pageno = self.root
        while True:
            node = self._load(pageno)
            if isinstance(node, _Leaf):
                idx = bisect.bisect_left(node.keys, key)
                if idx < len(node.keys) and node.keys[idx] == key:
                    return node.values[idx]
                return None
            i = bisect.bisect_right(node.keys, key)
            pageno = node.children[i]

    def _leftmost_leaf(self) -> Optional[int]:
        if self.root == 0:
            return None
        pageno = self.root
        while True:
            node = self._load(pageno)
            if isinstance(node, _Leaf):
                return node.pageno
            pageno = node.children[0]

    def _find_leaf(self, key: int) -> Optional[int]:
        if self.root == 0:
            return None
        pageno = self.root
        while True:
            node = self._load(pageno)
            if isinstance(node, _Leaf):
                return node.pageno
            i = bisect.bisect_right(node.keys, key)
            pageno = node.children[i]

    def scan(
        self, low: Optional[int] = None, high: Optional[int] = None
    ) -> Iterator[Tuple[int, bytes]]:
        """Yield (key, value) for low <= key <= high in ascending key order.

        `None` bounds are open. Walks leaf sibling pointers, so it is a single
        linear pass over the relevant leaves."""
        if low is None:
            pageno = self._leftmost_leaf()
        else:
            pageno = self._find_leaf(low)
        if pageno is None:
            return
        while pageno:
            node = self._load(pageno)
            for k, v in zip(node.keys, node.values):
                if low is not None and k < low:
                    continue
                if high is not None and k > high:
                    return
                yield k, v
            pageno = node.next_leaf

    def delete(self, key: int) -> bool:
        """Remove a key. Frees the cell but does not merge underfull nodes."""
        if self.root == 0:
            return False
        pageno = self._find_leaf(key)
        node = self._load(pageno)
        idx = bisect.bisect_left(node.keys, key)
        if idx < len(node.keys) and node.keys[idx] == key:
            del node.keys[idx]
            del node.values[idx]
            self._store(node)
            return True
        return False
