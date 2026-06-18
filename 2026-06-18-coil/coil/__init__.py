"""Coil — a small programming language with a bytecode VM.

Public facade:
    run_source(src)           -> run a program, return the VM
    compile_source_text(src)  -> compile to a FunctionObj (for disassembly)
    Interpreter               -> reusable instance (used by the REPL)
"""

from .compiler import compile_source
from .errors import CoilError
from .parser import parse
from .vm import VM, stringify

__all__ = ["run_source", "compile_source_text", "Interpreter", "CoilError",
           "stringify"]


def compile_source_text(src, name="<script>"):
    """Lex + parse + compile, returning the top-level FunctionObj."""
    ast = parse(src)
    return compile_source(ast, name=name)


def run_source(src, output=None, gc_stress=False, trace_gc=False, name="<script>"):
    """Compile and run `src`, returning the VM (for inspection)."""
    function = compile_source_text(src, name=name)
    vm = VM(output=output, gc_stress=gc_stress, trace_gc=trace_gc)
    vm.interpret(function)
    return vm


class Interpreter:
    """A persistent VM whose globals survive across `eval` calls (the REPL)."""

    def __init__(self, output=None, gc_stress=False):
        self.vm = VM(output=output, gc_stress=gc_stress)

    def run(self, src, name="<repl>"):
        function = compile_source_text(src, name=name)
        return self.vm.interpret(function)
