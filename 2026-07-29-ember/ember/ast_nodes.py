"""AST node definitions for the Ember language.

Plain dataclasses -- no behavior lives here. Interpreter, codegen, and the
C transpiler each walk this same tree independently, which is exactly the
point: three back ends sharing one front end, disagreeing on nothing.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Program:
    functions: List["FnDef"]


@dataclass
class FnDef:
    name: str
    params: List[str]
    body: "Block"
    line: int


@dataclass
class Block:
    stmts: List["Stmt"]


# ---- Statements ----

@dataclass
class LetStmt:
    name: str
    expr: "Expr"
    line: int


@dataclass
class AssignStmt:
    name: str
    expr: "Expr"
    line: int


@dataclass
class IfStmt:
    cond: "Expr"
    then_block: Block
    else_block: Optional[Block]
    line: int


@dataclass
class WhileStmt:
    cond: "Expr"
    body: Block
    line: int


@dataclass
class ReturnStmt:
    expr: Optional["Expr"]
    line: int


@dataclass
class ExprStmt:
    expr: "Expr"
    line: int


Stmt = object  # union marker for readability; real type is one of the above

# ---- Expressions ----

@dataclass
class IntLit:
    value: int
    line: int


@dataclass
class BoolLit:
    value: bool
    line: int


@dataclass
class VarRef:
    name: str
    line: int


@dataclass
class UnaryOp:
    op: str          # '-' | '!'
    operand: "Expr"
    line: int


@dataclass
class BinOp:
    op: str          # '+ - * / % < <= > >= == != && ||'
    left: "Expr"
    right: "Expr"
    line: int


@dataclass
class Call:
    name: str
    args: List["Expr"]
    line: int


Expr = object  # union marker
