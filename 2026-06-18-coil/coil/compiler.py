"""Compiler: walks the AST and emits bytecode into Chunks.

Resolves lexical scope (globals by name, locals by stack slot), captures
upvalues for closures, and back-patches jumps for control flow. One Compiler
instance compiles one function; nested functions get child Compilers that
share nothing but a parent pointer used for upvalue resolution.
"""

from . import ast_nodes as A
from .bytecode import Chunk, Op
from .errors import CompileError
from .objects import FunctionObj


class Local:
    __slots__ = ("name", "depth", "initialized", "is_captured")

    def __init__(self, name, depth):
        self.name = name
        self.depth = depth
        self.initialized = False
        self.is_captured = False


class UpvalueSpec:
    __slots__ = ("index", "is_local")

    def __init__(self, index, is_local):
        self.index = index
        self.is_local = is_local


class Compiler:
    def __init__(self, enclosing=None, name="<script>", is_script=True):
        self.enclosing = enclosing
        self.is_script = is_script
        self.function = FunctionObj(name if not is_script else None, 0,
                                    Chunk(name), 0)
        self.chunk = self.function.chunk
        self.locals = []
        self.upvalues = []  # list[UpvalueSpec]
        self.scope_depth = 0
        self.loop_stack = []  # list of dicts: {breaks: [...], continue: int}
        # Reserve slot 0 for the function/closure itself.
        reserved = Local("", 0)
        reserved.initialized = True
        self.locals.append(reserved)

    # ---- emit helpers ----
    def emit(self, op, line):
        return self.chunk.write(int(op), line)

    def emit_operand(self, value, line):
        return self.chunk.write(int(value), line)

    def emit_op_arg(self, op, arg, line):
        self.emit(op, line)
        return self.emit_operand(arg, line)

    def emit_jump(self, op, line):
        """Emit a jump with a placeholder absolute target; return operand slot."""
        self.emit(op, line)
        return self.emit_operand(0xFFFFFFFF, line)

    def patch_jump(self, slot):
        self.chunk.code[slot] = len(self.chunk.code)

    def emit_loop(self, op, target, line):
        self.emit(op, line)
        self.emit_operand(target, line)

    def emit_constant(self, value, line):
        idx = self.chunk.add_constant(value)
        self.emit_op_arg(Op.CONSTANT, idx, line)

    def name_constant(self, name):
        return self.chunk.add_constant(name)

    def emit_return(self, line=0):
        self.emit(Op.NIL, line)
        self.emit(Op.RETURN, line)

    # ---- scope ----
    def begin_scope(self):
        self.scope_depth += 1

    def end_scope(self, line):
        self.scope_depth -= 1
        while len(self.locals) > 1 and self.locals[-1].depth > self.scope_depth:
            local = self.locals.pop()
            if local.is_captured:
                self.emit(Op.CLOSE_UPVALUE, line)
            else:
                self.emit(Op.POP, line)

    def declare_local(self, name, line):
        # Detect redeclaration in the same scope.
        for local in reversed(self.locals):
            if local.depth != -1 and local.depth < self.scope_depth:
                break
            if local.name == name:
                raise CompileError(
                    f"variable '{name}' already declared in this scope", line)
        local = Local(name, self.scope_depth)
        self.locals.append(local)
        return len(self.locals) - 1

    def mark_initialized(self):
        self.locals[-1].initialized = True

    def resolve_local(self, name, line):
        for i in range(len(self.locals) - 1, -1, -1):
            local = self.locals[i]
            if local.name == name:
                if not local.initialized:
                    raise CompileError(
                        f"cannot read local '{name}' in its own initializer", line)
                return i
        return -1

    def add_upvalue(self, index, is_local):
        for i, uv in enumerate(self.upvalues):
            if uv.index == index and uv.is_local == is_local:
                return i
        self.upvalues.append(UpvalueSpec(index, is_local))
        self.function.upvalue_count = len(self.upvalues)
        return len(self.upvalues) - 1

    def resolve_upvalue(self, name, line):
        if self.enclosing is None:
            return -1
        local = self.enclosing.resolve_local(name, line)
        if local != -1:
            self.enclosing.locals[local].is_captured = True
            return self.add_upvalue(local, True)
        upvalue = self.enclosing.resolve_upvalue(name, line)
        if upvalue != -1:
            return self.add_upvalue(upvalue, False)
        return -1

    # ---- statement compilation ----
    def compile_program(self, statements):
        for stmt in statements:
            self.compile_stmt(stmt)
        self.emit_return()
        return self.function

    def compile_stmt(self, node):
        method = getattr(self, "_stmt_" + type(node).__name__, None)
        if method is None:
            raise CompileError(f"cannot compile statement {type(node).__name__}",
                               getattr(node, "line", None))
        method(node)

    def _stmt_LetStmt(self, node):
        if self.scope_depth == 0:
            # global
            if node.initializer is not None:
                self.compile_expr(node.initializer)
            else:
                self.emit(Op.NIL, node.line)
            idx = self.name_constant(node.name)
            self.emit_op_arg(Op.DEFINE_GLOBAL, idx, node.line)
        else:
            self.declare_local(node.name, node.line)
            if node.initializer is not None:
                self.compile_expr(node.initializer)
            else:
                self.emit(Op.NIL, node.line)
            self.mark_initialized()

    def _stmt_FnDecl(self, node):
        if self.scope_depth == 0:
            self._compile_function(node.name, node.params, node.body, node.line)
            idx = self.name_constant(node.name)
            self.emit_op_arg(Op.DEFINE_GLOBAL, idx, node.line)
        else:
            self.declare_local(node.name, node.line)
            self.mark_initialized()  # allow recursion
            self._compile_function(node.name, node.params, node.body, node.line)
            # closure now sits in the local's slot

    def _stmt_ExprStmt(self, node):
        self.compile_expr(node.expr)
        self.emit(Op.POP, node.line)

    def _stmt_PrintStmt(self, node):
        self.compile_expr(node.expr)
        self.emit(Op.PRINT, node.line)

    def _stmt_Block(self, node):
        self.begin_scope()
        for stmt in node.statements:
            self.compile_stmt(stmt)
        self.end_scope(node.line)

    def _stmt_IfStmt(self, node):
        self.compile_expr(node.condition)
        then_jump = self.emit_jump(Op.JUMP_IF_FALSE_POP, node.line)
        self.compile_stmt(node.then_branch)
        else_jump = self.emit_jump(Op.JUMP, node.line)
        self.patch_jump(then_jump)
        if node.else_branch is not None:
            self.compile_stmt(node.else_branch)
        self.patch_jump(else_jump)

    def _stmt_WhileStmt(self, node):
        loop_start = len(self.chunk.code)
        self.compile_expr(node.condition)
        exit_jump = self.emit_jump(Op.JUMP_IF_FALSE_POP, node.line)
        self.loop_stack.append({"breaks": [], "continue": loop_start})
        self.compile_stmt(node.body)
        self.emit_loop(Op.JUMP, loop_start, node.line)
        ctx = self.loop_stack.pop()
        self.patch_jump(exit_jump)
        for b in ctx["breaks"]:
            self.patch_jump(b)

    def _stmt_ForStmt(self, node):
        self.begin_scope()
        if node.initializer is not None:
            self.compile_stmt(node.initializer)
        loop_start = len(self.chunk.code)
        exit_jump = None
        if node.condition is not None:
            self.compile_expr(node.condition)
            exit_jump = self.emit_jump(Op.JUMP_IF_FALSE_POP, node.line)

        if node.increment is not None:
            body_jump = self.emit_jump(Op.JUMP, node.line)
            increment_start = len(self.chunk.code)
            self.compile_expr(node.increment)
            self.emit(Op.POP, node.line)
            self.emit_loop(Op.JUMP, loop_start, node.line)
            self.patch_jump(body_jump)
            continue_target = increment_start
        else:
            continue_target = loop_start

        self.loop_stack.append({"breaks": [], "continue": continue_target})
        self.compile_stmt(node.body)
        self.emit_loop(Op.JUMP, continue_target, node.line)
        ctx = self.loop_stack.pop()
        if exit_jump is not None:
            self.patch_jump(exit_jump)
        for b in ctx["breaks"]:
            self.patch_jump(b)
        self.end_scope(node.line)

    def _stmt_ReturnStmt(self, node):
        if self.is_script:
            raise CompileError("cannot return from top-level code", node.line)
        if node.value is not None:
            self.compile_expr(node.value)
        else:
            self.emit(Op.NIL, node.line)
        self.emit(Op.RETURN, node.line)

    def _stmt_BreakStmt(self, node):
        if not self.loop_stack:
            raise CompileError("'break' outside of a loop", node.line)
        jump = self.emit_jump(Op.JUMP, node.line)
        self.loop_stack[-1]["breaks"].append(jump)

    def _stmt_ContinueStmt(self, node):
        if not self.loop_stack:
            raise CompileError("'continue' outside of a loop", node.line)
        self.emit_loop(Op.JUMP, self.loop_stack[-1]["continue"], node.line)

    # ---- expression compilation ----
    def compile_expr(self, node):
        method = getattr(self, "_expr_" + type(node).__name__, None)
        if method is None:
            raise CompileError(f"cannot compile expression {type(node).__name__}",
                               getattr(node, "line", None))
        method(node)

    def _expr_Literal(self, node):
        v = node.value
        if v is None:
            self.emit(Op.NIL, node.line)
        elif v is True:
            self.emit(Op.TRUE, node.line)
        elif v is False:
            self.emit(Op.FALSE, node.line)
        else:
            self.emit_constant(v, node.line)

    def _expr_Variable(self, node):
        slot = self.resolve_local(node.name, node.line)
        if slot != -1:
            self.emit_op_arg(Op.GET_LOCAL, slot, node.line)
            return
        uv = self.resolve_upvalue(node.name, node.line)
        if uv != -1:
            self.emit_op_arg(Op.GET_UPVALUE, uv, node.line)
            return
        idx = self.name_constant(node.name)
        self.emit_op_arg(Op.GET_GLOBAL, idx, node.line)

    def _expr_Assign(self, node):
        self.compile_expr(node.value)
        slot = self.resolve_local(node.name, node.line)
        if slot != -1:
            self.emit_op_arg(Op.SET_LOCAL, slot, node.line)
            return
        uv = self.resolve_upvalue(node.name, node.line)
        if uv != -1:
            self.emit_op_arg(Op.SET_UPVALUE, uv, node.line)
            return
        idx = self.name_constant(node.name)
        self.emit_op_arg(Op.SET_GLOBAL, idx, node.line)

    def _expr_Unary(self, node):
        self.compile_expr(node.operand)
        if node.op == "-":
            self.emit(Op.NEGATE, node.line)
        else:
            self.emit(Op.NOT, node.line)

    _BINOPS = {
        "+": Op.ADD, "-": Op.SUB, "*": Op.MUL, "/": Op.DIV, "%": Op.MOD,
        "==": Op.EQUAL, "!=": Op.NOT_EQUAL,
        ">": Op.GREATER, ">=": Op.GREATER_EQUAL,
        "<": Op.LESS, "<=": Op.LESS_EQUAL,
    }

    def _expr_Binary(self, node):
        self.compile_expr(node.left)
        self.compile_expr(node.right)
        self.emit(self._BINOPS[node.op], node.line)

    def _expr_Logical(self, node):
        self.compile_expr(node.left)
        if node.op == "and":
            end_jump = self.emit_jump(Op.JUMP_IF_FALSE, node.line)
            self.emit(Op.POP, node.line)
            self.compile_expr(node.right)
            self.patch_jump(end_jump)
        else:  # or
            else_jump = self.emit_jump(Op.JUMP_IF_FALSE, node.line)
            end_jump = self.emit_jump(Op.JUMP, node.line)
            self.patch_jump(else_jump)
            self.emit(Op.POP, node.line)
            self.compile_expr(node.right)
            self.patch_jump(end_jump)

    def _expr_Call(self, node):
        self.compile_expr(node.callee)
        for arg in node.args:
            self.compile_expr(arg)
        self.emit_op_arg(Op.CALL, len(node.args), node.line)

    def _expr_IndexGet(self, node):
        self.compile_expr(node.obj)
        self.compile_expr(node.index)
        self.emit(Op.GET_INDEX, node.line)

    def _expr_IndexSet(self, node):
        self.compile_expr(node.obj)
        self.compile_expr(node.index)
        self.compile_expr(node.value)
        self.emit(Op.SET_INDEX, node.line)

    def _expr_ListLit(self, node):
        for el in node.elements:
            self.compile_expr(el)
        self.emit_op_arg(Op.BUILD_LIST, len(node.elements), node.line)

    def _expr_MapLit(self, node):
        for key, value in node.pairs:
            self.compile_expr(key)
            self.compile_expr(value)
        self.emit_op_arg(Op.BUILD_MAP, len(node.pairs), node.line)

    def _expr_FnExpr(self, node):
        self._compile_function(node.name, node.params, node.body, node.line)

    # ---- function compilation ----
    def _compile_function(self, name, params, body, line):
        sub = Compiler(enclosing=self, name=name or "<anonymous>",
                       is_script=False)
        sub.begin_scope()
        for p in params:
            sub.declare_local(p, line)
            sub.mark_initialized()
        sub.function.arity = len(params)
        for stmt in body:
            sub.compile_stmt(stmt)
        sub.emit_return(line)
        fn = sub.function
        idx = self.chunk.add_constant(fn)
        self.emit_op_arg(Op.CLOSURE, idx, line)
        for uv in sub.upvalues:
            self.emit_operand(1 if uv.is_local else 0, line)
            self.emit_operand(uv.index, line)


def compile_source(statements, name="<script>"):
    return Compiler(name=name, is_script=True).compile_program(statements)
