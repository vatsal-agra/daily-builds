"""
Semantic analysis for Runic: name resolution, arity checking, flat
per-function local-variable scoping (no shadowing — keeps WASM local-slot
assignment a trivial one-pass job), and "returns on every path" checking.

Every value in Runic is i32, so there is no type *lattice* to check —
"typecheck" here means "is this program well-scoped and well-formed",
which is the part of a real typechecker that actually catches the bugs a
toy interpreter would otherwise silently paper over.
"""

from . import ast_nodes as A


class SemanticError(Exception):
    def __init__(self, msg, line):
        super().__init__(f"error at line {line}: {msg}")
        self.line = line


class FuncInfo:
    def __init__(self, name, params, index):
        self.name = name
        self.params = params
        self.arity = len(params)
        self.index = index  # function index in module (declaration order)
        self.locals = []  # let-bound names, in first-encountered order
        self.local_index = {}  # name -> slot index (params first, then locals)


class ArrayInfo:
    def __init__(self, name, size, init, base_offset):
        self.name = name
        self.size = size
        self.init = init
        self.base_offset = base_offset  # byte offset in linear memory


class CheckedProgram:
    def __init__(self, funcs_by_name, func_order, arrays_by_name, total_mem_bytes):
        self.funcs_by_name = funcs_by_name
        self.func_order = func_order  # list[FuncInfo] in declaration order
        self.arrays_by_name = arrays_by_name
        self.total_mem_bytes = total_mem_bytes


def _stmt_always_returns(stmt):
    if isinstance(stmt, A.ReturnStmt):
        return True
    if isinstance(stmt, A.IfStmt):
        return stmt.else_block is not None and _block_always_returns(stmt.then_block) and _block_always_returns(stmt.else_block)
    if isinstance(stmt, A.Block):
        return _block_always_returns(stmt)
    return False


def _block_always_returns(block):
    for i, s in enumerate(block.stmts):
        if _stmt_always_returns(s):
            return True
    return False


def _collect_lets(block, out, seen):
    for stmt in block.stmts:
        if isinstance(stmt, A.LetStmt):
            if stmt.name in seen:
                raise SemanticError(f"'{stmt.name}' is already declared in this function (no shadowing/redeclaration)", stmt.line)
            seen.add(stmt.name)
            out.append(stmt.name)
        elif isinstance(stmt, A.IfStmt):
            _collect_lets(stmt.then_block, out, seen)
            if stmt.else_block:
                _collect_lets(stmt.else_block, out, seen)
        elif isinstance(stmt, A.WhileStmt):
            _collect_lets(stmt.body, out, seen)
        elif isinstance(stmt, A.Block):
            _collect_lets(stmt, out, seen)


def _check_no_dead_code(block):
    stmts = block.stmts
    for i, s in enumerate(stmts):
        if isinstance(s, A.IfStmt):
            _check_no_dead_code(s.then_block)
            if s.else_block:
                _check_no_dead_code(s.else_block)
        elif isinstance(s, A.WhileStmt):
            _check_no_dead_code(s.body)
        elif isinstance(s, A.Block):
            _check_no_dead_code(s)
        if _stmt_always_returns(s) and i != len(stmts) - 1:
            raise SemanticError("unreachable code after a statement that always returns", stmts[i + 1].line)


def check(program):
    # --- arrays ---
    arrays_by_name = {}
    offset = 0
    for arr in program.arrays:
        if arr.name in arrays_by_name:
            raise SemanticError(f"array '{arr.name}' declared more than once", arr.line)
        init = arr.init
        if init is not None:
            init = list(init) + [0] * (arr.size - len(init))
        arrays_by_name[arr.name] = ArrayInfo(arr.name, arr.size, init, offset)
        offset += arr.size * 4
    total_mem_bytes = offset

    # --- functions: pass 1, collect signatures (allows forward refs/recursion) ---
    funcs_by_name = {}
    func_order = []
    for i, fn in enumerate(program.funcs):
        if fn.name in funcs_by_name:
            raise SemanticError(f"function '{fn.name}' declared more than once", fn.line)
        if fn.name in arrays_by_name:
            raise SemanticError(f"'{fn.name}' is declared as both a function and an array", fn.line)
        seen_params = set()
        for p in fn.params:
            if p in seen_params:
                raise SemanticError(f"duplicate parameter name '{p}' in function '{fn.name}'", fn.line)
            seen_params.add(p)
        info = FuncInfo(fn.name, fn.params, i)
        funcs_by_name[fn.name] = info
        func_order.append(info)

    if not program.funcs:
        raise SemanticError("program must declare at least one function", 0)

    # --- functions: pass 2, resolve bodies ---
    for fn, info in zip(program.funcs, func_order):
        for idx, p in enumerate(fn.params):
            info.local_index[p] = idx
        let_names = []
        _collect_lets(fn.body, let_names, set(fn.params))
        info.locals = let_names
        for idx, name in enumerate(let_names):
            info.local_index[name] = len(fn.params) + idx

        _check_no_dead_code(fn.body)
        if not _block_always_returns(fn.body):
            raise SemanticError(f"function '{fn.name}' does not return on every path", fn.line)

        _check_block(fn.body, info, funcs_by_name, arrays_by_name)

    return CheckedProgram(funcs_by_name, func_order, arrays_by_name, total_mem_bytes)


def _check_block(block, info, funcs_by_name, arrays_by_name):
    for stmt in block.stmts:
        _check_stmt(stmt, info, funcs_by_name, arrays_by_name)


def _check_stmt(stmt, info, funcs_by_name, arrays_by_name):
    if isinstance(stmt, A.LetStmt):
        _check_expr(stmt.expr, info, funcs_by_name, arrays_by_name)
    elif isinstance(stmt, A.AssignStmt):
        if isinstance(stmt.target, A.Ident):
            if stmt.target.name not in info.local_index:
                raise SemanticError(f"assignment to undeclared variable '{stmt.target.name}' (use 'let' first)", stmt.line)
        else:
            _check_expr(stmt.target, info, funcs_by_name, arrays_by_name)
        _check_expr(stmt.expr, info, funcs_by_name, arrays_by_name)
    elif isinstance(stmt, A.IfStmt):
        _check_expr(stmt.cond, info, funcs_by_name, arrays_by_name)
        _check_block(stmt.then_block, info, funcs_by_name, arrays_by_name)
        if stmt.else_block:
            _check_block(stmt.else_block, info, funcs_by_name, arrays_by_name)
    elif isinstance(stmt, A.WhileStmt):
        _check_expr(stmt.cond, info, funcs_by_name, arrays_by_name)
        _check_block(stmt.body, info, funcs_by_name, arrays_by_name)
    elif isinstance(stmt, A.ReturnStmt):
        _check_expr(stmt.expr, info, funcs_by_name, arrays_by_name)
    elif isinstance(stmt, A.ExprStmt):
        _check_expr(stmt.expr, info, funcs_by_name, arrays_by_name)
    elif isinstance(stmt, A.Block):
        _check_block(stmt, info, funcs_by_name, arrays_by_name)
    else:
        raise SemanticError(f"internal error: unknown statement node {type(stmt)}", getattr(stmt, "line", 0))


def _check_expr(expr, info, funcs_by_name, arrays_by_name):
    if isinstance(expr, A.IntLit):
        if not (-2147483648 <= expr.value <= 4294967295):
            raise SemanticError(f"integer literal {expr.value} out of i32 range", expr.line)
    elif isinstance(expr, A.Ident):
        if expr.name not in info.local_index:
            raise SemanticError(f"undeclared variable '{expr.name}'", expr.line)
    elif isinstance(expr, A.Index):
        if expr.array_name not in arrays_by_name:
            raise SemanticError(f"'{expr.array_name}' is not a declared array", expr.line)
        _check_expr(expr.index_expr, info, funcs_by_name, arrays_by_name)
    elif isinstance(expr, A.Call):
        if expr.name not in funcs_by_name:
            raise SemanticError(f"call to undeclared function '{expr.name}'", expr.line)
        callee = funcs_by_name[expr.name]
        if callee.arity != len(expr.args):
            raise SemanticError(
                f"function '{expr.name}' expects {callee.arity} argument(s), got {len(expr.args)}", expr.line
            )
        for a in expr.args:
            _check_expr(a, info, funcs_by_name, arrays_by_name)
    elif isinstance(expr, A.BinOp):
        _check_expr(expr.left, info, funcs_by_name, arrays_by_name)
        _check_expr(expr.right, info, funcs_by_name, arrays_by_name)
    elif isinstance(expr, A.UnaryOp):
        _check_expr(expr.operand, info, funcs_by_name, arrays_by_name)
    else:
        raise SemanticError(f"internal error: unknown expression node {type(expr)}", getattr(expr, "line", 0))
