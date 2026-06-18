"""The Coil virtual machine: a stack-based bytecode interpreter with a
mark-and-sweep garbage collector over a VM-managed object heap.
"""

import math
import sys
import time

from .bytecode import Op
from .errors import RuntimeCoilError
from .objects import (ClosureObj, FunctionObj, GCObject, ListObj, MapObj,
                      NativeObj, Upvalue)


class CallFrame:
    __slots__ = ("closure", "ip", "base")

    def __init__(self, closure, base):
        self.closure = closure
        self.ip = 0
        self.base = base


# ---------------------------------------------------------------------------
# value helpers
# ---------------------------------------------------------------------------

def is_truthy(v):
    return not (v is None or v is False)


def values_equal(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return a is b


def fmt_number(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return repr(v) if isinstance(v, float) else str(v)


def stringify(v, quote=False):
    if v is None:
        return "nil"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, (int, float)):
        return fmt_number(v)
    if isinstance(v, str):
        return f'"{v}"' if quote else v
    if isinstance(v, ListObj):
        return "[" + ", ".join(stringify(x, quote=True) for x in v.items) + "]"
    if isinstance(v, MapObj):
        inner = ", ".join(
            f"{stringify(k, quote=True)}: {stringify(val, quote=True)}"
            for k, val in v.data.items())
        return "{" + inner + "}"
    if isinstance(v, (ClosureObj, FunctionObj)):
        return f"<fn {v.name or 'anonymous'}>"
    if isinstance(v, NativeObj):
        return f"<native {v.name}>"
    return str(v)


def type_name(v):
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, GCObject):
        return v.type_name()
    return "unknown"


class VM:
    def __init__(self, output=None, gc_stress=False, trace_gc=False):
        self.stack = []
        self.frames = []
        self.globals = {}
        self.heap = []
        self.open_upvalues = {}  # stack index -> Upvalue
        self.output = output if output is not None else sys.stdout
        self.gc_stress = gc_stress
        self.trace_gc = trace_gc
        # stats
        self.objects_allocated = 0
        self.collections = 0
        self.last_freed = 0
        self.next_gc = 1024
        self._define_natives()

    # ---- output ----
    def _print(self, text):
        self.output.write(text)
        self.output.write("\n")

    # ---- heap / GC ----
    def allocate(self, obj):
        if self.gc_stress:
            self.collect_garbage()
        elif len(self.heap) >= self.next_gc:
            self.collect_garbage()
            self.next_gc = max(1024, len(self.heap) * 2)
        self.heap.append(obj)
        self.objects_allocated += 1
        return obj

    def collect_garbage(self):
        # 1. clear marks on heap objects
        for obj in self.heap:
            obj.marked = False
        # 2. mark from roots
        gray = []

        def mark(value):
            if isinstance(value, GCObject) and not value.marked:
                value.marked = True
                gray.append(value)

        for value in self.stack:
            mark(value)
        for value in self.globals.values():
            mark(value)
        for frame in self.frames:
            mark(frame.closure)
        for uv in self.open_upvalues.values():
            mark(uv)
        # 3. trace
        while gray:
            obj = gray.pop()
            for ref in obj.references():
                mark(ref)
        # 4. sweep: keep marked, drop the rest
        survivors = []
        freed = 0
        for obj in self.heap:
            if obj.marked:
                survivors.append(obj)
            else:
                freed += 1
        self.heap = survivors
        self.collections += 1
        self.last_freed = freed
        if self.trace_gc:
            sys.stderr.write(
                f"[gc] collection #{self.collections}: freed {freed}, "
                f"{len(self.heap)} live\n")
        return freed

    # ---- upvalues ----
    def capture_upvalue(self, slot):
        existing = self.open_upvalues.get(slot)
        if existing is not None:
            return existing
        uv = Upvalue(self.stack, slot)
        self.allocate(uv)
        self.open_upvalues[slot] = uv
        return uv

    def close_upvalues(self, from_slot):
        to_close = [s for s in self.open_upvalues if s >= from_slot]
        for s in to_close:
            self.open_upvalues[s].close()
            del self.open_upvalues[s]

    # ---- running ----
    def interpret(self, function):
        closure = ClosureObj(function)
        self.allocate(closure)
        self.stack.append(closure)
        self._call(closure, 0, line=0)
        return self.run()

    @property
    def frame(self):
        return self.frames[-1]

    def _runtime_error(self, message, line=None):
        if line is None and self.frames:
            f = self.frame
            line = f.closure.function.chunk.lines[f.ip - 1]
        tb = []
        for frame in reversed(self.frames):
            fn = frame.closure.function
            name = fn.name or "<script>"
            fline = fn.chunk.lines[frame.ip - 1] if frame.ip > 0 else None
            tb.append((name, fline))
        return RuntimeCoilError(message, line=line, traceback_frames=tb)

    def run(self):
        frame = self.frame
        code = frame.closure.function.chunk.code
        constants = frame.closure.function.chunk.constants
        stack = self.stack

        def read():
            b = code[frame.ip]
            frame.ip += 1
            return b

        while True:
            op = read()

            if op == Op.CONSTANT:
                stack.append(constants[read()])
            elif op == Op.NIL:
                stack.append(None)
            elif op == Op.TRUE:
                stack.append(True)
            elif op == Op.FALSE:
                stack.append(False)
            elif op == Op.POP:
                stack.pop()
            elif op == Op.DUP:
                stack.append(stack[-1])

            elif op == Op.DEFINE_GLOBAL:
                name = constants[read()]
                self.globals[name] = stack.pop()
            elif op == Op.GET_GLOBAL:
                name = constants[read()]
                if name not in self.globals:
                    raise self._runtime_error(f"undefined variable '{name}'")
                stack.append(self.globals[name])
            elif op == Op.SET_GLOBAL:
                name = constants[read()]
                if name not in self.globals:
                    raise self._runtime_error(
                        f"cannot assign to undefined variable '{name}'")
                self.globals[name] = stack[-1]

            elif op == Op.GET_LOCAL:
                stack.append(stack[frame.base + read()])
            elif op == Op.SET_LOCAL:
                stack[frame.base + read()] = stack[-1]
            elif op == Op.GET_UPVALUE:
                stack.append(frame.closure.upvalues[read()].get())
            elif op == Op.SET_UPVALUE:
                frame.closure.upvalues[read()].set(stack[-1])

            elif op == Op.EQUAL:
                b = stack.pop(); a = stack.pop()
                stack.append(values_equal(a, b))
            elif op == Op.NOT_EQUAL:
                b = stack.pop(); a = stack.pop()
                stack.append(not values_equal(a, b))
            elif op == Op.GREATER:
                self._compare(lambda a, b: a > b)
            elif op == Op.GREATER_EQUAL:
                self._compare(lambda a, b: a >= b)
            elif op == Op.LESS:
                self._compare(lambda a, b: a < b)
            elif op == Op.LESS_EQUAL:
                self._compare(lambda a, b: a <= b)

            elif op == Op.ADD:
                self._add()
            elif op == Op.SUB:
                self._arith("-", lambda a, b: a - b)
            elif op == Op.MUL:
                self._arith("*", lambda a, b: a * b)
            elif op == Op.DIV:
                b = self._num_operand(stack[-1])
                a = self._num_operand(stack[-2])
                if b == 0:
                    raise self._runtime_error("division by zero")
                stack.pop(); stack.pop()
                stack.append(a / b)
            elif op == Op.MOD:
                b = self._num_operand(stack[-1])
                a = self._num_operand(stack[-2])
                if b == 0:
                    raise self._runtime_error("modulo by zero")
                stack.pop(); stack.pop()
                stack.append(math.fmod(a, b))
            elif op == Op.NEGATE:
                v = stack[-1]
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise self._runtime_error(
                        f"cannot negate {type_name(v)}")
                stack[-1] = -v
            elif op == Op.NOT:
                stack[-1] = not is_truthy(stack[-1])

            elif op == Op.PRINT:
                self._print(stringify(stack.pop()))

            elif op == Op.JUMP:
                frame.ip = read()
            elif op == Op.JUMP_IF_FALSE:
                target = read()
                if not is_truthy(stack[-1]):
                    frame.ip = target
            elif op == Op.JUMP_IF_FALSE_POP:
                target = read()
                if not is_truthy(stack.pop()):
                    frame.ip = target

            elif op == Op.BUILD_LIST:
                n = read()
                start = len(stack) - n
                # Allocate while the elements are still on the stack so a GC
                # triggered by allocate() sees them as roots.
                lst = ListObj(stack[start:])
                self.allocate(lst)
                del stack[start:]
                stack.append(lst)
            elif op == Op.BUILD_MAP:
                n = read()
                data = {}
                start = len(stack) - 2 * n
                for i in range(start, len(stack), 2):
                    key = stack[i]
                    if not isinstance(key, (str, int, float)) or isinstance(key, bool):
                        raise self._runtime_error(
                            f"map key must be string or number, got {type_name(key)}")
                    data[key] = stack[i + 1]
                m = MapObj(data)
                self.allocate(m)  # operands still on stack -> rooted during GC
                del stack[start:]
                stack.append(m)

            elif op == Op.GET_INDEX:
                index = stack.pop()
                obj = stack.pop()
                stack.append(self._index_get(obj, index))
            elif op == Op.SET_INDEX:
                value = stack.pop()
                index = stack.pop()
                obj = stack.pop()
                self._index_set(obj, index, value)
                stack.append(value)

            elif op == Op.CLOSURE:
                fn = constants[read()]
                closure = ClosureObj(fn)
                self.allocate(closure)
                for _ in range(fn.upvalue_count):
                    is_local = read()
                    index = read()
                    if is_local:
                        closure.upvalues.append(
                            self.capture_upvalue(frame.base + index))
                    else:
                        closure.upvalues.append(frame.closure.upvalues[index])
                stack.append(closure)
            elif op == Op.CLOSE_UPVALUE:
                self.close_upvalues(len(stack) - 1)
                stack.pop()

            elif op == Op.CALL:
                argc = read()
                # save ip already advanced
                self._call_value(stack[len(stack) - argc - 1], argc)
                # refresh locals for (possibly) new frame
                frame = self.frame
                code = frame.closure.function.chunk.code
                constants = frame.closure.function.chunk.constants

            elif op == Op.RETURN:
                result = stack.pop()
                returning = self.frames.pop()
                self.close_upvalues(returning.base)
                del stack[returning.base:]
                if not self.frames:
                    return result
                stack.append(result)
                frame = self.frame
                code = frame.closure.function.chunk.code
                constants = frame.closure.function.chunk.constants
            else:
                raise self._runtime_error(f"unknown opcode {op}")

    # ---- operations ----
    def _compare(self, fn):
        b = self.stack[-1]
        a = self.stack[-2]
        ok = ((isinstance(a, (int, float)) and not isinstance(a, bool)
               and isinstance(b, (int, float)) and not isinstance(b, bool))
              or (isinstance(a, str) and isinstance(b, str)))
        if not ok:
            raise self._runtime_error(
                f"cannot compare {type_name(a)} and {type_name(b)}")
        self.stack.pop(); self.stack.pop()
        self.stack.append(fn(a, b))

    def _num_operand(self, v):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise self._runtime_error(
                f"operand must be a number, got {type_name(v)}")
        return v

    def _arith(self, sym, fn):
        b = self._num_operand(self.stack[-1])
        a = self._num_operand(self.stack[-2])
        self.stack.pop(); self.stack.pop()
        self.stack.append(fn(a, b))

    def _add(self):
        b = self.stack[-1]
        a = self.stack[-2]
        if isinstance(a, str) and isinstance(b, str):
            self.stack.pop(); self.stack.pop()
            self.stack.append(a + b)
        elif (isinstance(a, (int, float)) and not isinstance(a, bool)
              and isinstance(b, (int, float)) and not isinstance(b, bool)):
            self.stack.pop(); self.stack.pop()
            self.stack.append(a + b)
        elif isinstance(a, ListObj) and isinstance(b, ListObj):
            # allocate before popping a, b so their elements stay rooted
            lst = ListObj(a.items + b.items)
            self.allocate(lst)
            self.stack.pop(); self.stack.pop()
            self.stack.append(lst)
        else:
            raise self._runtime_error(
                f"cannot add {type_name(a)} and {type_name(b)}")

    def _index_get(self, obj, index):
        if isinstance(obj, ListObj):
            i = self._list_index(index, len(obj.items))
            return obj.items[i]
        if isinstance(obj, str):
            i = self._list_index(index, len(obj))
            return obj[i]
        if isinstance(obj, MapObj):
            if isinstance(index, bool) or not isinstance(index, (str, int, float)):
                raise self._runtime_error(
                    f"map key must be string or number, got {type_name(index)}")
            if index not in obj.data:
                raise self._runtime_error(f"key {stringify(index, quote=True)} not found")
            return obj.data[index]
        raise self._runtime_error(f"cannot index {type_name(obj)}")

    def _index_set(self, obj, index, value):
        if isinstance(obj, ListObj):
            i = self._list_index(index, len(obj.items))
            obj.items[i] = value
            return
        if isinstance(obj, MapObj):
            if isinstance(index, bool) or not isinstance(index, (str, int, float)):
                raise self._runtime_error(
                    f"map key must be string or number, got {type_name(index)}")
            obj.data[index] = value
            return
        raise self._runtime_error(
            f"cannot assign to index of {type_name(obj)}")

    def _list_index(self, index, length):
        if isinstance(index, bool) or not isinstance(index, (int, float)):
            raise self._runtime_error(
                f"index must be a number, got {type_name(index)}")
        if isinstance(index, float) and not index.is_integer():
            raise self._runtime_error("index must be a whole number")
        i = int(index)
        if i < 0:
            i += length
        if i < 0 or i >= length:
            raise self._runtime_error(
                f"index {int(index)} out of range (length {length})")
        return i

    # ---- calls ----
    def _call_value(self, callee, argc):
        if isinstance(callee, ClosureObj):
            self._call(callee, argc)
        elif isinstance(callee, NativeObj):
            self._call_native(callee, argc)
        else:
            raise self._runtime_error(f"can only call functions, not {type_name(callee)}")

    def _call(self, closure, argc, line=None):
        arity = closure.function.arity
        if argc != arity:
            raise self._runtime_error(
                f"function '{closure.name or 'anonymous'}' expects {arity} "
                f"argument{'s' if arity != 1 else ''}, got {argc}", line=line)
        if len(self.frames) >= 512:
            raise self._runtime_error("stack overflow (call depth > 512)", line=line)
        base = len(self.stack) - argc - 1
        self.frames.append(CallFrame(closure, base))

    def _call_native(self, native, argc):
        args = self.stack[len(self.stack) - argc:]
        if native.arity != -1 and native.arity != argc:
            raise self._runtime_error(
                f"native '{native.name}' expects {native.arity} "
                f"argument{'s' if native.arity != 1 else ''}, got {argc}")
        result = native.fn(self, args)
        del self.stack[len(self.stack) - argc - 1:]
        self.stack.append(result)

    # ---- native library ----
    def _define_natives(self):
        def reg(name, arity, fn):
            native = NativeObj(name, arity, fn)
            self.globals[name] = native

        def need_number(v, who):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise self._runtime_error(
                    f"{who} expects a number, got {type_name(v)}")
            return v

        def need_list(v, who):
            if not isinstance(v, ListObj):
                raise self._runtime_error(
                    f"{who} expects a list, got {type_name(v)}")
            return v

        def need_map(v, who):
            if not isinstance(v, MapObj):
                raise self._runtime_error(
                    f"{who} expects a map, got {type_name(v)}")
            return v

        reg("clock", 0, lambda vm, a: float(time.time()))
        reg("type", 1, lambda vm, a: type_name(a[0]))
        reg("str", 1, lambda vm, a: stringify(a[0]))

        def _num(vm, a):
            v = a[0]
            if isinstance(v, bool):
                raise self._runtime_error("cannot convert bool to number")
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, str):
                try:
                    return float(v)
                except ValueError:
                    raise self._runtime_error(f"cannot convert {v!r} to number")
            raise self._runtime_error(f"cannot convert {type_name(v)} to number")
        reg("num", 1, _num)

        def _len(vm, a):
            v = a[0]
            if isinstance(v, str):
                return float(len(v))
            if isinstance(v, ListObj):
                return float(len(v.items))
            if isinstance(v, MapObj):
                return float(len(v.data))
            raise self._runtime_error(f"len() expects string/list/map, got {type_name(v)}")
        reg("len", 1, _len)

        def _push(vm, a):
            lst = need_list(a[0], "push()")
            lst.items.append(a[1])
            return float(len(lst.items))
        reg("push", 2, _push)

        def _pop(vm, a):
            lst = need_list(a[0], "pop()")
            if not lst.items:
                raise self._runtime_error("pop() from empty list")
            return lst.items.pop()
        reg("pop", 1, _pop)

        def _keys(vm, a):
            m = need_map(a[0], "keys()")
            lst = ListObj(list(m.data.keys()))
            vm.allocate(lst)
            return lst
        reg("keys", 1, _keys)

        def _values(vm, a):
            m = need_map(a[0], "values()")
            lst = ListObj(list(m.data.values()))
            vm.allocate(lst)
            return lst
        reg("values", 1, _values)

        def _has(vm, a):
            m = need_map(a[0], "has()")
            return a[1] in m.data
        reg("has", 2, _has)

        def _delete(vm, a):
            m = need_map(a[0], "delete()")
            if a[1] in m.data:
                del m.data[a[1]]
                return True
            return False
        reg("delete", 2, _delete)

        def _range(vm, a):
            if len(a) == 1:
                start, stop = 0, int(need_number(a[0], "range()"))
            elif len(a) == 2:
                start = int(need_number(a[0], "range()"))
                stop = int(need_number(a[1], "range()"))
            else:
                raise self._runtime_error("range() expects 1 or 2 arguments")
            lst = ListObj([float(x) for x in range(start, stop)])
            vm.allocate(lst)
            return lst
        reg("range", -1, _range)

        def _slice(vm, a):
            v = a[0]
            start = int(need_number(a[1], "slice()"))
            end = int(need_number(a[2], "slice()"))
            if isinstance(v, ListObj):
                lst = ListObj(v.items[start:end])
                vm.allocate(lst)
                return lst
            if isinstance(v, str):
                return v[start:end]
            raise self._runtime_error(f"slice() expects list/string, got {type_name(v)}")
        reg("slice", 3, _slice)

        reg("abs", 1, lambda vm, a: float(abs(need_number(a[0], "abs()"))))
        reg("floor", 1, lambda vm, a: float(math.floor(need_number(a[0], "floor()"))))
        reg("ceil", 1, lambda vm, a: float(math.ceil(need_number(a[0], "ceil()"))))
        reg("sqrt", 1, lambda vm, a: math.sqrt(need_number(a[0], "sqrt()")))

        def _min(vm, a):
            if not a:
                raise self._runtime_error("min() needs at least 1 argument")
            return min(need_number(x, "min()") for x in a)
        reg("min", -1, _min)

        def _max(vm, a):
            if not a:
                raise self._runtime_error("max() needs at least 1 argument")
            return max(need_number(x, "max()") for x in a)
        reg("max", -1, _max)

        def _assert(vm, a):
            cond = a[0]
            msg = a[1] if len(a) > 1 else "assertion failed"
            if not is_truthy(cond):
                raise self._runtime_error(stringify(msg))
            return None
        reg("assert", -1, _assert)

        def _gc(vm, a):
            return float(vm.collect_garbage())
        reg("gc", 0, _gc)

        def _heap_size(vm, a):
            return float(len(vm.heap))
        reg("heap_size", 0, _heap_size)
