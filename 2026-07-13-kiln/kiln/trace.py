"""Captures a step-by-step execution trace of a WASM call — operand
stack, locals and call depth before every instruction, plus function
enter/exit events — for the interactive HTML visualizer (viz/index.html).
Hooks into Instance.tracer, which interpreter.py checks on every
instruction and function call; tracing a module costs nothing when
instance.tracer is None (the normal, untraced execution path)."""

MAX_STEPS = 4000


class Tracer:
    def __init__(self, instance, max_steps=MAX_STEPS):
        self.instance = instance
        self.max_steps = max_steps
        self.steps = []
        self.depth = 0
        self.truncated = False

    def _func_name(self, func_index):
        for e in self.instance.module.exports:
            if e.kind == "func" and e.index == func_index:
                return e.name
        return f"$func{func_index}"

    def _record(self, entry):
        if len(self.steps) >= self.max_steps:
            self.truncated = True
            return
        self.steps.append(entry)

    def step(self, instr, stack, locals_):
        self._record({
            "kind": "instr",
            "depth": self.depth,
            "op": instr.op,
            "imm": _jsonable(instr.imm),
            "stack": list(map(_jsonable, stack)),
            "locals": list(map(_jsonable, locals_)),
        })

    def enter(self, func_index, locals_):
        self._record({
            "kind": "enter",
            "depth": self.depth,
            "func": self._func_name(func_index),
            "locals": list(map(_jsonable, locals_)),
        })
        self.depth += 1

    def enter_host(self, func_index, args):
        self._record({
            "kind": "enter_host",
            "depth": self.depth,
            "func": self._func_name(func_index),
            "args": list(map(_jsonable, args)),
        })
        self.depth += 1

    def exit_call(self, func_index, results):
        self.depth = max(0, self.depth - 1)
        self._record({
            "kind": "exit",
            "depth": self.depth,
            "func": self._func_name(func_index),
            "results": list(map(_jsonable, results)),
        })


def _jsonable(v):
    if isinstance(v, tuple):
        return list(v)
    return v


def trace_call(instance, func_name, args, max_steps=MAX_STEPS):
    """Runs one exported call with tracing enabled and returns the step
    list (a plain list of JSON-serializable dicts) plus whether it was
    truncated by max_steps."""
    tracer = Tracer(instance, max_steps)
    instance.tracer = tracer
    try:
        result = instance.call(func_name, args)
    finally:
        instance.tracer = None
    return {"steps": tracer.steps, "truncated": tracer.truncated, "result": result}
