"""Runtime heap objects for Coil.

Numbers, booleans, nil and strings are plain Python values (immutable, not
GC-tracked). The compound/mutable objects below live on the VM's managed heap
and are reclaimed by the mark-and-sweep collector. Each exposes `references()`
returning the GC-reachable child objects so the collector can trace the graph.
"""


class GCObject:
    """Base for every heap-allocated Coil object."""
    __slots__ = ("marked",)

    def __init__(self):
        self.marked = False

    def references(self):
        return ()

    def type_name(self):
        return "object"


class FunctionObj(GCObject):
    """A compiled function: its bytecode chunk + metadata."""
    __slots__ = ("name", "arity", "chunk", "upvalue_count")

    def __init__(self, name, arity, chunk, upvalue_count=0):
        super().__init__()
        self.name = name
        self.arity = arity
        self.chunk = chunk
        self.upvalue_count = upvalue_count

    def references(self):
        return [c for c in self.chunk.constants if isinstance(c, GCObject)]

    def type_name(self):
        return "function"

    def __repr__(self):
        return f"<fn {self.name or 'anon'}>"


class Upvalue(GCObject):
    """A captured variable. Open => lives in a stack slot; closed => owns it."""
    __slots__ = ("stack", "slot", "closed", "is_closed")

    def __init__(self, stack, slot):
        super().__init__()
        self.stack = stack    # reference to the VM value stack (open only)
        self.slot = slot      # index into that stack (open only)
        self.closed = None
        self.is_closed = False

    def get(self):
        return self.closed if self.is_closed else self.stack[self.slot]

    def set(self, value):
        if self.is_closed:
            self.closed = value
        else:
            self.stack[self.slot] = value

    def close(self):
        self.closed = self.stack[self.slot]
        self.is_closed = True
        self.stack = None

    def references(self):
        # Open upvalues point into the stack, which is itself a GC root, so we
        # only need to trace the closed value here.
        if self.is_closed and isinstance(self.closed, GCObject):
            return [self.closed]
        return ()


class ClosureObj(GCObject):
    """A function plus the upvalues it captured."""
    __slots__ = ("function", "upvalues")

    def __init__(self, function):
        super().__init__()
        self.function = function
        self.upvalues = []  # list[Upvalue]

    @property
    def name(self):
        return self.function.name

    @property
    def arity(self):
        return self.function.arity

    def references(self):
        return [self.function] + list(self.upvalues)

    def type_name(self):
        return "function"

    def __repr__(self):
        return f"<fn {self.function.name or 'anon'}>"


class ListObj(GCObject):
    __slots__ = ("items",)

    def __init__(self, items=None):
        super().__init__()
        self.items = items if items is not None else []

    def references(self):
        return [x for x in self.items if isinstance(x, GCObject)]

    def type_name(self):
        return "list"


class MapObj(GCObject):
    __slots__ = ("data",)

    def __init__(self, data=None):
        super().__init__()
        self.data = data if data is not None else {}

    def references(self):
        refs = []
        for k, v in self.data.items():
            if isinstance(k, GCObject):
                refs.append(k)
            if isinstance(v, GCObject):
                refs.append(v)
        return refs

    def type_name(self):
        return "map"


class NativeObj(GCObject):
    """A built-in function implemented in Python."""
    __slots__ = ("name", "arity", "fn")

    def __init__(self, name, arity, fn):
        super().__init__()
        self.name = name
        self.arity = arity  # -1 => variadic
        self.fn = fn

    def type_name(self):
        return "native function"

    def __repr__(self):
        return f"<native {self.name}>"
