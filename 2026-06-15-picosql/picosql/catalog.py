"""Persistent table catalog.

Table schemas are themselves stored in a B+tree (the *catalog tree*, rooted at
the pager's `catalog_root` header slot), keyed by an integer table id with a
JSON-encoded schema as the value. This means the schema is as durable as the
data, and creating a table is just another B+tree insert.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from .btree import BTree
from .pager import Pager


class Column:
    __slots__ = ("name", "type")

    def __init__(self, name: str, ctype: str):
        self.name = name
        self.type = ctype.upper()

    def to_dict(self) -> dict:
        return {"name": self.name, "type": self.type}


class TableSchema:
    __slots__ = ("id", "name", "columns", "root_page", "next_rowid", "pk_col")

    def __init__(
        self,
        id: int,
        name: str,
        columns: List[Column],
        root_page: int = 0,
        next_rowid: int = 1,
        pk_col: Optional[int] = None,
    ):
        self.id = id
        self.name = name
        self.columns = columns
        self.root_page = root_page
        self.next_rowid = next_rowid
        self.pk_col = pk_col  # index of an INTEGER PRIMARY KEY column, else None

    def col_index(self, name: str) -> Optional[int]:
        lname = name.lower()
        for i, c in enumerate(self.columns):
            if c.name.lower() == lname:
                return i
        return None

    def to_json(self) -> bytes:
        return json.dumps(
            {
                "id": self.id,
                "name": self.name,
                "columns": [c.to_dict() for c in self.columns],
                "root_page": self.root_page,
                "next_rowid": self.next_rowid,
                "pk_col": self.pk_col,
            }
        ).encode("utf-8")

    @staticmethod
    def from_json(blob: bytes) -> "TableSchema":
        d = json.loads(blob.decode("utf-8"))
        return TableSchema(
            id=d["id"],
            name=d["name"],
            columns=[Column(c["name"], c["type"]) for c in d["columns"]],
            root_page=d["root_page"],
            next_rowid=d["next_rowid"],
            pk_col=d.get("pk_col"),
        )


class Catalog:
    def __init__(self, pager: Pager):
        self.pager = pager
        if pager.catalog_root == 0:
            tree = BTree(pager, 0)
            # Force creation of an empty root leaf so catalog_root is valid.
            tree.insert(0, b"__sentinel__")
            tree.delete(0)
            pager.set_catalog_root(tree.root)
        self._tree = BTree(pager, pager.catalog_root)

    def _persist_root(self) -> None:
        if self._tree.root != self.pager.catalog_root:
            self.pager.set_catalog_root(self._tree.root)

    def reload(self) -> None:
        """Resync the catalog tree root after a rollback restored the header."""
        self._tree.root = self.pager.catalog_root

    def list_tables(self) -> List[TableSchema]:
        out = []
        for _, blob in self._tree.scan():
            out.append(TableSchema.from_json(blob))
        out.sort(key=lambda s: s.name.lower())
        return out

    def get_by_name(self, name: str) -> Optional[TableSchema]:
        lname = name.lower()
        for _, blob in self._tree.scan():
            s = TableSchema.from_json(blob)
            if s.name.lower() == lname:
                return s
        return None

    def get_by_id(self, tid: int) -> Optional[TableSchema]:
        blob = self._tree.search(tid)
        return TableSchema.from_json(blob) if blob is not None else None

    def create_table(
        self, name: str, columns: List[Column], pk_col: Optional[int]
    ) -> TableSchema:
        if self.get_by_name(name) is not None:
            raise ValueError(f"table {name!r} already exists")
        tid = self.pager.alloc_table_id()
        schema = TableSchema(tid, name, columns, root_page=0, next_rowid=1, pk_col=pk_col)
        self._tree.insert(tid, schema.to_json())
        self._persist_root()
        return schema

    def save(self, schema: TableSchema) -> None:
        """Persist mutated schema fields (root_page / next_rowid)."""
        self._tree.insert(schema.id, schema.to_json())
        self._persist_root()

    def drop_table(self, name: str) -> bool:
        schema = self.get_by_name(name)
        if schema is None:
            return False
        self._tree.delete(schema.id)
        self._persist_root()
        return True
