"""AST node definitions for the Runic language. Plain classes, no magic."""


class Node:
    def __init__(self, line):
        self.line = line


# --- top level -------------------------------------------------------------

class Program(Node):
    def __init__(self, arrays, funcs):
        super().__init__(0)
        self.arrays = arrays
        self.funcs = funcs


class ArrayDecl(Node):
    def __init__(self, name, size, init, line):
        super().__init__(line)
        self.name = name
        self.size = size
        self.init = init  # list[int] or None


class FuncDecl(Node):
    def __init__(self, name, params, body, line):
        super().__init__(line)
        self.name = name
        self.params = params
        self.body = body


# --- statements --------------------------------------------------------------

class Block(Node):
    def __init__(self, stmts, line):
        super().__init__(line)
        self.stmts = stmts


class LetStmt(Node):
    def __init__(self, name, expr, line):
        super().__init__(line)
        self.name = name
        self.expr = expr


class AssignStmt(Node):
    def __init__(self, target, expr, line):
        super().__init__(line)
        self.target = target  # Ident or Index
        self.expr = expr


class IfStmt(Node):
    def __init__(self, cond, then_block, else_block, line):
        super().__init__(line)
        self.cond = cond
        self.then_block = then_block
        self.else_block = else_block  # Block or None


class WhileStmt(Node):
    def __init__(self, cond, body, line):
        super().__init__(line)
        self.cond = cond
        self.body = body


class ReturnStmt(Node):
    def __init__(self, expr, line):
        super().__init__(line)
        self.expr = expr


class ExprStmt(Node):
    def __init__(self, expr, line):
        super().__init__(line)
        self.expr = expr


class AssertStmt(Node):
    def __init__(self, expr, line):
        super().__init__(line)
        self.expr = expr


# --- expressions -------------------------------------------------------------

class IntLit(Node):
    def __init__(self, value, line):
        super().__init__(line)
        self.value = value


class Ident(Node):
    def __init__(self, name, line):
        super().__init__(line)
        self.name = name


class Index(Node):
    def __init__(self, array_name, index_expr, line):
        super().__init__(line)
        self.array_name = array_name
        self.index_expr = index_expr


class Call(Node):
    def __init__(self, name, args, line):
        super().__init__(line)
        self.name = name
        self.args = args


class BinOp(Node):
    def __init__(self, op, left, right, line):
        super().__init__(line)
        self.op = op
        self.left = left
        self.right = right


class UnaryOp(Node):
    def __init__(self, op, operand, line):
        super().__init__(line)
        self.op = op
        self.operand = operand
