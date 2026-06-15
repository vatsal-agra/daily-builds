"""AST node definitions for PicoSQL statements and expressions."""

from __future__ import annotations

from typing import List, Optional, Tuple


# ---- expressions --------------------------------------------------------
class Expr:
    pass


class Literal(Expr):
    def __init__(self, value):
        self.value = value  # int | float | str | None

    def __repr__(self):
        return f"Literal({self.value!r})"


class ColumnRef(Expr):
    def __init__(self, table: Optional[str], name: str):
        self.table = table
        self.name = name

    def __repr__(self):
        return f"ColumnRef({self.table}.{self.name})" if self.table else f"ColumnRef({self.name})"


class Star(Expr):
    def __init__(self, table: Optional[str] = None):
        self.table = table


class BinaryOp(Expr):
    def __init__(self, op: str, left: Expr, right: Expr):
        self.op = op
        self.left = left
        self.right = right

    def __repr__(self):
        return f"({self.left!r} {self.op} {self.right!r})"


class UnaryOp(Expr):
    def __init__(self, op: str, operand: Expr):
        self.op = op
        self.operand = operand


class IsNull(Expr):
    def __init__(self, operand: Expr, negated: bool):
        self.operand = operand
        self.negated = negated


class InList(Expr):
    def __init__(self, operand: Expr, items: List[Expr], negated: bool = False):
        self.operand = operand
        self.items = items
        self.negated = negated


class FuncCall(Expr):
    def __init__(self, name: str, args: List[Expr], star: bool = False):
        self.name = name.upper()
        self.args = args
        self.star = star  # COUNT(*)


# ---- statements ---------------------------------------------------------
class ColumnDef:
    def __init__(self, name: str, type: str, primary_key: bool = False):
        self.name = name
        self.type = type.upper()
        self.primary_key = primary_key


class CreateTable:
    def __init__(self, name: str, columns: List[ColumnDef], if_not_exists: bool = False):
        self.name = name
        self.columns = columns
        self.if_not_exists = if_not_exists


class DropTable:
    def __init__(self, name: str, if_exists: bool = False):
        self.name = name
        self.if_exists = if_exists


class Insert:
    def __init__(self, table: str, columns: Optional[List[str]], rows: List[List[Expr]]):
        self.table = table
        self.columns = columns
        self.rows = rows


class Join:
    def __init__(self, table: str, alias: Optional[str], on: Expr):
        self.table = table
        self.alias = alias
        self.on = on


class Select:
    def __init__(
        self,
        projections: List[Tuple[Expr, Optional[str]]],
        from_table: Optional[str],
        from_alias: Optional[str],
        joins: List[Join],
        where: Optional[Expr],
        group_by: List[Expr],
        having: Optional[Expr],
        order_by: List[Tuple[Expr, bool]],  # (expr, descending)
        limit: Optional[int],
        offset: Optional[int],
        distinct: bool,
    ):
        self.projections = projections
        self.from_table = from_table
        self.from_alias = from_alias
        self.joins = joins
        self.where = where
        self.group_by = group_by
        self.having = having
        self.order_by = order_by
        self.limit = limit
        self.offset = offset
        self.distinct = distinct


class Update:
    def __init__(self, table: str, assignments: List[Tuple[str, Expr]], where: Optional[Expr]):
        self.table = table
        self.assignments = assignments
        self.where = where


class Delete:
    def __init__(self, table: str, where: Optional[Expr]):
        self.table = table
        self.where = where


class Begin:
    pass


class Commit:
    pass


class Rollback:
    pass


class Explain:
    def __init__(self, statement):
        self.statement = statement
