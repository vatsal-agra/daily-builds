"""A real, measured wall-clock benchmark: the same function, called the
same number of times, once through the tree-walking interpreter and once
through JIT-compiled native code. The speedup number this reports is
whatever the clock actually says -- there is no target number it's
tuned to hit.
"""

import time

from .interpreter import Interpreter
from .codegen_x64 import compile_program
from .optimize import fold_constants


def benchmark(program, fn_name, args, min_seconds=0.3, optimize=False):
    """Runs both backends for at least `min_seconds` wall-clock each
    (auto-scaling the iteration count, like a microbenchmark harness
    should) and returns a dict of iters/elapsed/per-call/speedup.

    The interpreter always runs the original, unoptimized AST -- it's the
    ground-truth oracle constant folding is checked against, so it must
    never itself be fed optimizer output. If `optimize`, only the JIT
    compiles the constant-folded program."""
    interp = Interpreter(program)
    compiled = compile_program(fold_constants(program) if optimize else program)

    # Confirm correctness before timing anything -- a benchmark that
    # races a broken JIT against the interpreter and reports a "10x
    # speedup" would be worse than useless.
    expected = interp.call(fn_name, args)
    actual = compiled.call(fn_name, args)
    if expected != actual:
        raise AssertionError(
            f"refusing to benchmark: interpreter says {fn_name}{tuple(args)} = {expected}, "
            f"JIT says {actual}"
        )

    def timed_run(callable_fn, label):
        iters = 1
        while True:
            start = time.perf_counter()
            for _ in range(iters):
                callable_fn()
            elapsed = time.perf_counter() - start
            if elapsed >= min_seconds or iters > 1_000_000:
                return {"label": label, "iters": iters, "elapsed": elapsed,
                         "per_call": elapsed / iters}
            iters *= 4

    interp_stats = timed_run(lambda: interp.call(fn_name, args), "interpreter")
    jit_stats = timed_run(lambda: compiled.call(fn_name, args), "jit")

    return {
        "fn_name": fn_name,
        "args": list(args),
        "result": expected,
        "interpreter": interp_stats,
        "jit": jit_stats,
        "speedup": interp_stats["per_call"] / jit_stats["per_call"],
    }
