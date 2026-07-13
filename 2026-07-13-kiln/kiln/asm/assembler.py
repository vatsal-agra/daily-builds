"""Assembles parsed `.kwat` s-expressions (see parser.py) into a real
Module IR (types.Module), ready for encoder.encode_module.

Two passes, like any real assembler:
  1. Declare every func/global/memory/table by name, in source order, so
     forward references (calling a function defined later in the file)
     resolve correctly.
  2. Assemble instruction bodies now that the full symbol table exists.
"""

from ..wasm import opcodes as ops
from ..wasm.types import (
    Module, FuncType, Import, Global, Export, Memory, Table, Element, Function, Data,
    NAME_TO_VALTYPE,
)
from ..wasm.decoder import Instr
from .parser import Str, parse


class AssembleError(Exception):
    pass


def _valtype(tok):
    if tok not in NAME_TO_VALTYPE:
        raise AssembleError(f"unknown value type {tok!r}")
    return NAME_TO_VALTYPE[tok]


def _is_name(tok):
    return isinstance(tok, str) and not isinstance(tok, Str) and tok.startswith("$")


class _FuncDecl:
    def __init__(self, name, params, param_names, results, body_tokens, type_index):
        self.name = name
        self.params = params
        self.param_names = param_names
        self.results = results
        self.body_tokens = body_tokens
        self.type_index = type_index
        self.locals = []  # filled in during pass 2 (declared (local ...) forms)
        self.local_names = []


def assemble(src):
    forms = parse(src)
    if len(forms) != 1 or forms[0][0] != "module":
        raise AssembleError("expected a single (module ...) form")
    items = forms[0][1:]

    m = Module()
    func_names = {}     # $name -> global func index
    global_names = {}   # $name -> global index
    mem_names = {}
    table_names = {}
    func_decls = []      # parallel to defined (non-imported) funcs, _FuncDecl
    type_names = {}      # $name -> type index, from standalone (type ...) forms
    next_func_index = 0

    def parse_params_results(rest):
        params, param_names, results = [], [], []
        i = 0
        while i < len(rest) and isinstance(rest[i], list) and rest[i][0] == "param":
            entry = rest[i]
            if len(entry) == 3 and _is_name(entry[1]):
                param_names.append(entry[1])
                params.append(_valtype(entry[2]))
            else:
                for vt in entry[1:]:
                    param_names.append(None)
                    params.append(_valtype(vt))
            i += 1
        while i < len(rest) and isinstance(rest[i], list) and rest[i][0] == "result":
            for vt in rest[i][1:]:
                results.append(_valtype(vt))
            i += 1
        return params, param_names, results, rest[i:]

    # --- Pass 1: declare everything, in source order ------------------
    for item in items:
        head = item[0]
        if head == "import":
            mod_name, imp_name, spec = item[1], item[2], item[3]
            if spec[0] == "func":
                rest = spec[1:]
                name = rest[0] if rest and _is_name(rest[0]) else None
                rest = rest[1:] if name else rest
                params, _, results, _ = parse_params_results(rest)
                type_index = len(m.types)
                m.types.append(FuncType(tuple(params), tuple(results)))
                m.imports.append(Import(str(mod_name), str(imp_name), "func", type_index=type_index))
                if name:
                    func_names[name] = next_func_index
                next_func_index += 1
            elif spec[0] == "memory":
                mn = int(spec[1])
                mx = int(spec[2]) if len(spec) > 2 else None
                m.imports.append(Import(str(mod_name), str(imp_name), "memory", mem_min=mn, mem_max=mx))
            elif spec[0] == "global":
                gt = spec[1]
                mutable = isinstance(gt, list) and gt[0] == "mut"
                vt = _valtype(gt[1] if mutable else gt)
                m.imports.append(Import(str(mod_name), str(imp_name), "global",
                                         global_type=vt, global_mutable=mutable))
                if len(spec) > 2 and _is_name(spec[2]):
                    global_names[spec[2]] = len(m.imports) - 1
            else:
                raise AssembleError(f"unsupported import kind {spec[0]!r}")

        elif head == "type":
            rest = item[1:]
            name = rest[0] if rest and _is_name(rest[0]) else None
            rest = rest[1:] if name else rest
            func_spec = rest[0]
            if func_spec[0] != "func":
                raise AssembleError(f"unsupported type form {func_spec[0]!r}")
            params, _, results, _ = parse_params_results(func_spec[1:])
            type_index = len(m.types)
            m.types.append(FuncType(tuple(params), tuple(results)))
            if name:
                type_names[name] = type_index

        elif head == "func":
            rest = item[1:]
            name = rest[0] if rest and _is_name(rest[0]) else None
            rest = rest[1:] if name else rest
            params, param_names, results, body_tokens = parse_params_results(rest)
            type_index = len(m.types)
            m.types.append(FuncType(tuple(params), tuple(results)))
            decl = _FuncDecl(name, params, param_names, results, body_tokens, type_index)
            func_decls.append(decl)
            if name:
                func_names[name] = next_func_index
            next_func_index += 1

        elif head == "memory":
            rest = item[1:]
            name = rest[0] if rest and _is_name(rest[0]) else None
            rest = rest[1:] if name else rest
            mn = int(rest[0])
            mx = int(rest[1]) if len(rest) > 1 else None
            m.memories.append(Memory(mn, mx))
            if name:
                mem_names[name] = len(m.memories) - 1

        elif head == "table":
            rest = item[1:]
            name = rest[0] if rest and _is_name(rest[0]) else None
            rest = rest[1:] if name else rest
            mn = int(rest[0])
            mx = int(rest[1]) if len(rest) > 1 and str(rest[1]).lstrip("-").isdigit() else None
            m.tables.append(Table(mn, mx))
            if name:
                table_names[name] = len(m.tables) - 1

        elif head == "global":
            rest = item[1:]
            name = rest[0] if rest and _is_name(rest[0]) else None
            rest = rest[1:] if name else rest
            gt = rest[0]
            mutable = isinstance(gt, list) and gt[0] == "mut"
            vt = _valtype(gt[1] if mutable else gt)
            m.globals.append(Global(vt, mutable, None))  # init assembled in pass 2
            if name:
                global_names[name] = len(m.globals) - 1
            decl_index = len(m.globals) - 1
            m.globals[decl_index]._raw_init = rest[1:]  # stashed for pass 2

        elif head in ("export", "start", "data", "elem"):
            pass  # handled in pass 2, after all names are known

        else:
            raise AssembleError(f"unsupported top-level form {head!r}")

    def resolve_func(tok):
        if _is_name(tok):
            if tok not in func_names:
                raise AssembleError(f"undefined function {tok}")
            return func_names[tok]
        return int(tok)

    def resolve_global(tok):
        if _is_name(tok):
            return global_names[tok]
        return int(tok)

    def resolve_mem(tok):
        return mem_names[tok] if _is_name(tok) else int(tok)

    def resolve_table(tok):
        return table_names[tok] if _is_name(tok) else int(tok)

    def assemble_const_expr(tokens):
        # A const expr is conventionally written as a single folded
        # instruction, e.g. `(i32.const 0)`, which the s-expr reader hands
        # us as one nested list; unwrap it to the flat (mnemonic, arg, ...)
        # form `_assemble_body` expects. Already-flat input passes through.
        if len(tokens) == 1 and isinstance(tokens[0], list):
            tokens = tokens[0]
        out, _, _ = _assemble_body(tokens, {}, [], type_names, func_names, global_names, m)
        return out

    # --- Pass 2: bodies, globals' init exprs, exports/start/data/elem -
    for g, item in zip(m.globals, [it for it in items if it[0] == "global"]):
        g.init = assemble_const_expr(g._raw_init)
        del g._raw_init

    for decl in func_decls:
        local_names = {name: i for i, name in enumerate(decl.param_names) if name}
        body_tokens = decl.body_tokens
        i = 0
        while i < len(body_tokens) and isinstance(body_tokens[i], list) and body_tokens[i][0] == "local":
            entry = body_tokens[i]
            if len(entry) == 3 and _is_name(entry[1]):
                local_names[entry[1]] = len(decl.params) + len(decl.locals)
                decl.locals.append(_valtype(entry[2]))
            else:
                for vt in entry[1:]:
                    decl.locals.append(_valtype(vt))
            i += 1
        body_tokens = body_tokens[i:]

        body, _, _ = _assemble_body(body_tokens, local_names, [], type_names, func_names, global_names, m)
        m.functions.append(Function(decl.type_index, decl.locals, body))

    for item in items:
        head = item[0]
        if head == "export":
            name, spec = item[1], item[2]
            kind = spec[0]
            if kind == "func":
                m.exports.append(Export(str(name), "func", resolve_func(spec[1])))
            elif kind == "memory":
                m.exports.append(Export(str(name), "memory", resolve_mem(spec[1])))
            elif kind == "global":
                m.exports.append(Export(str(name), "global", resolve_global(spec[1])))
            elif kind == "table":
                m.exports.append(Export(str(name), "table", resolve_table(spec[1])))
            else:
                raise AssembleError(f"unsupported export kind {kind!r}")
        elif head == "start":
            m.start = resolve_func(item[1])
        elif head == "data":
            offset = assemble_const_expr([item[1]])
            raw = "".join(str(s) for s in item[2:] if isinstance(s, Str)).encode("latin-1")
            m.data.append(Data(0, offset, raw))
        elif head == "elem":
            offset = assemble_const_expr([item[1]])
            func_indices = [resolve_func(t) for t in item[2:]]
            m.elements.append(Element(0, offset, func_indices))

    return m


def _assemble_body(tokens, local_names, label_stack, type_names, func_names, global_names, module):
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        i += 1
        if isinstance(tok, list):
            raise AssembleError(f"unexpected nested form {tok!r} in instruction stream")
        if tok not in ops.BY_NAME and tok not in ("end", "else"):
            raise AssembleError(f"unknown instruction {tok!r}")
        if tok in ("end", "else"):
            return out, tok, i
        opcode, kind = ops.BY_NAME[tok]

        if opcode in ops.BLOCK_OPENERS:
            label_name = None
            if i < n and _is_name(tokens[i]):
                label_name = tokens[i]
                i += 1
            blocktype = None
            if i < n and isinstance(tokens[i], list) and tokens[i][0] == "result":
                results = [_valtype(v) for v in tokens[i][1:]]
                blocktype = results[0] if results else None
                i += 1
            label_stack.append(label_name)
            if opcode == 0x04:  # if
                then_body, term, consumed = _assemble_body(tokens[i:], local_names, label_stack, type_names, func_names, global_names, module)
                i += consumed
                else_body = None
                if term == "else":
                    else_body, term2, consumed2 = _assemble_body(tokens[i:], local_names, label_stack, type_names, func_names, global_names, module)
                    i += consumed2
                label_stack.pop()
                out.append(Instr("if", opcode, blocktype, then_body, else_body))
            else:
                body, term, consumed = _assemble_body(tokens[i:], local_names, label_stack, type_names, func_names, global_names, module)
                i += consumed
                label_stack.pop()
                out.append(Instr(tok, opcode, blocktype, body))
            continue

        imm = None
        if kind in (ops.LOCALIDX,):
            t = tokens[i]; i += 1
            imm = _lookup(local_names, t, "local") if _is_name(t) else int(t)
        elif kind == ops.GLOBALIDX:
            t = tokens[i]; i += 1
            imm = _lookup(global_names, t, "global") if _is_name(t) else int(t)
        elif kind == ops.FUNCIDX:
            t = tokens[i]; i += 1
            imm = _lookup(func_names, t, "function") if _is_name(t) else int(t)
        elif kind == ops.LABELIDX:
            t = tokens[i]; i += 1
            if _is_name(t):
                imm = _resolve_label(label_stack, t)
            else:
                imm = int(t)
        elif kind == ops.MEMARG:
            align, offset = 0, 0
            while i < n and isinstance(tokens[i], str) and ("=" in tokens[i]) and not isinstance(tokens[i], Str):
                key, val = tokens[i].split("=", 1)
                if key == "align":
                    align = int(val)
                elif key == "offset":
                    offset = int(val)
                i += 1
            imm = (align, offset)
        elif kind == ops.MEMORY_IMM:
            imm = None
        elif kind == ops.CALL_INDIRECT:
            t = tokens[i]; i += 1
            if isinstance(t, list) and t[0] == "type":
                ref = t[1]
                imm = type_names[ref] if _is_name(ref) else int(ref)
            else:
                imm = int(t)
        elif kind == ops.BR_TABLE:
            t = tokens[i]; i += 1
            if not isinstance(t, list):
                raise AssembleError(
                    "br_table requires a parenthesized label list after the mnemonic: br_table (0 1 2)")
            labels = [_resolve_label(label_stack, x) if _is_name(x) else int(x) for x in t[:-1]]
            default = _resolve_label(label_stack, t[-1]) if _is_name(t[-1]) else int(t[-1])
            imm = (labels, default)
        elif kind == ops.I32:
            imm = int(tokens[i], 0) & 0xFFFFFFFF; i += 1
        elif kind == ops.I64:
            imm = int(tokens[i], 0) & 0xFFFFFFFFFFFFFFFF; i += 1
        elif kind == ops.F32 or kind == ops.F64:
            imm = float(tokens[i]); i += 1
        elif kind is None:
            imm = None
        else:
            raise AssembleError(f"unhandled immediate kind {kind}")

        out.append(Instr(tok, opcode, imm))

    return out, None, i


def _lookup(table, name, kind):
    if name not in table:
        raise AssembleError(f"undefined {kind} {name}")
    return table[name]


def _resolve_label(label_stack, name):
    for depth, n in enumerate(reversed(label_stack)):
        if n == name:
            return depth
    raise AssembleError(f"undefined label {name}")

