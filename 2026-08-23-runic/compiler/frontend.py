"""Top-level pipeline: Runic source text -> real WASM binary bytes."""

from .lexer import tokenize, LexError
from .parser import parse, ParseError
from .typecheck import check, SemanticError
from .codegen import compile_function
from .encoder import encode_module


class CompileError(Exception):
    pass


class CompileResult:
    def __init__(self, wasm_bytes, checked, compiled_funcs, program):
        self.wasm_bytes = wasm_bytes
        self.checked = checked
        self.compiled_funcs = compiled_funcs  # list[(num_locals, instrs)], aligned with checked.func_order
        self.program = program


def compile_source(src):
    try:
        tokens = tokenize(src)
        program = parse(tokens)
        checked = check(program)
    except (LexError, ParseError, SemanticError) as e:
        raise CompileError(str(e)) from e

    compiled_funcs = []
    for fn, info in zip(program.funcs, checked.func_order):
        compiled_funcs.append(compile_function(fn, info, checked))

    wasm_bytes = encode_module(checked, compiled_funcs)
    return CompileResult(wasm_bytes, checked, compiled_funcs, program)
