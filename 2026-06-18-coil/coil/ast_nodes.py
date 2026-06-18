"""AST node definitions. Every node carries a source `line` for diagnostics."""

from dataclasses import dataclass, field
from typing import Any, List, Optional


# ---- Expressions ----------------------------------------------------------

@dataclass
class Literal:
    value: Any
    line: int


@dataclass
class ListLit:
    elements: list
    line: int


@dataclass
class MapLit:
    pairs: list  # list of (key_expr, value_expr)
    line: int


@dataclass
class Variable:
    name: str
    line: int


@dataclass
class Assign:
    name: str
    value: Any
    line: int


@dataclass
class IndexGet:
    obj: Any
    index: Any
    line: int


@dataclass
class IndexSet:
    obj: Any
    index: Any
    value: Any
    line: int


@dataclass
class Unary:
    op: str
    operand: Any
    line: int


@dataclass
class Binary:
    op: str
    left: Any
    right: Any
    line: int


@dataclass
class Logical:
    op: str  # "and" | "or"
    left: Any
    right: Any
    line: int


@dataclass
class Call:
    callee: Any
    args: list
    line: int


@dataclass
class FnExpr:
    name: Optional[str]
    params: List[str]
    body: list  # list of statements
    line: int


# ---- Statements -----------------------------------------------------------

@dataclass
class ExprStmt:
    expr: Any
    line: int


@dataclass
class PrintStmt:
    expr: Any
    line: int


@dataclass
class LetStmt:
    name: str
    initializer: Any
    line: int


@dataclass
class Block:
    statements: list
    line: int


@dataclass
class IfStmt:
    condition: Any
    then_branch: Any
    else_branch: Any
    line: int


@dataclass
class WhileStmt:
    condition: Any
    body: Any
    line: int


@dataclass
class ForStmt:
    initializer: Any
    condition: Any
    increment: Any
    body: Any
    line: int


@dataclass
class FnDecl:
    name: str
    params: List[str]
    body: list
    line: int


@dataclass
class ReturnStmt:
    value: Any
    line: int


@dataclass
class BreakStmt:
    line: int


@dataclass
class ContinueStmt:
    line: int
