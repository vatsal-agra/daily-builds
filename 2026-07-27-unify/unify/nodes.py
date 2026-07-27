"""AST node definitions for the Unify language.

Every node carries a `span` = (start_offset, end_offset) into the original
source text, so type errors and the derivation-tree visualizer can point at
exactly the code that produced them.
"""

from dataclasses import dataclass, field


@dataclass
class Node:
    span: tuple


# ---- expressions ----------------------------------------------------------

@dataclass
class Int(Node):
    value: int


@dataclass
class Bool(Node):
    value: bool


@dataclass
class Str(Node):
    value: str


@dataclass
class Var(Node):
    name: str


@dataclass
class TupleExpr(Node):
    items: list


@dataclass
class Nil(Node):
    pass


@dataclass
class Cons(Node):
    head: object
    tail: object


@dataclass
class SomeExpr(Node):
    value: object


@dataclass
class NoneExpr(Node):
    pass


@dataclass
class If(Node):
    cond: object
    then_branch: object
    else_branch: object


@dataclass
class Fun(Node):
    param: str
    body: object


@dataclass
class App(Node):
    fn: object
    arg: object


@dataclass
class Let(Node):
    name: str
    value: object
    body: object


@dataclass
class LetRec(Node):
    name: str
    value: object
    body: object


@dataclass
class BinOp(Node):
    op: str
    left: object
    right: object


@dataclass
class UnaryNeg(Node):
    expr: object


@dataclass
class Match(Node):
    scrutinee: object
    cases: list = field(default_factory=list)  # list of (Pattern, Expr)


# ---- patterns ---------------------------------------------------------

@dataclass
class PWild(Node):
    pass


@dataclass
class PVar(Node):
    name: str


@dataclass
class PInt(Node):
    value: int


@dataclass
class PBool(Node):
    value: bool


@dataclass
class PTuple(Node):
    items: list


@dataclass
class PNil(Node):
    pass


@dataclass
class PCons(Node):
    head: object
    tail: object


@dataclass
class PSome(Node):
    pattern: object


@dataclass
class PNone(Node):
    pass
