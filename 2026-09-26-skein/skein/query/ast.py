"""AST node types produced by the SkeinQL parser."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NodePattern:
    var: Optional[str]
    labels: List[str]
    props: Dict[str, Any]


@dataclass
class RelPattern:
    var: Optional[str]
    types: List[str]
    props: Dict[str, Any]
    direction: str  # "->" or "<-"


@dataclass
class PathPattern:
    # Alternates NodePattern, RelPattern, NodePattern, ... always odd length,
    # always starting and ending on a NodePattern.
    elements: List[Any]


@dataclass
class Literal:
    value: Any


@dataclass
class VarRef:
    var: str


@dataclass
class PropAccess:
    var: str
    prop: str


@dataclass
class UnaryOp:
    op: str
    operand: Any


@dataclass
class BinOp:
    op: str
    left: Any
    right: Any


@dataclass
class FuncCall:
    name: str
    args: List[Any]


@dataclass
class ReturnItem:
    expr: Any
    alias: Optional[str]


@dataclass
class OrderItem:
    expr: Any
    desc: bool


@dataclass
class Statement:
    match: Optional[PathPattern] = None
    where: Optional[Any] = None
    set_items: Optional[List[Any]] = None
    create: Optional[PathPattern] = None
    delete_vars: Optional[List[str]] = None
    detach: bool = False
    return_items: Optional[List[ReturnItem]] = None
    order_by: Optional[List[OrderItem]] = None
    limit: Optional[int] = None
