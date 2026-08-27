"""Render a Term back to Prolog surface syntax."""
from .terms import Atom, Var, Num, Struct, deref
from .parser import INFIX_OPS, PREFIX_OPS

_ATOM_SYMBOL_OK = set("+-*/\\^<>=~:.?@#&$")


def _atom_needs_quotes(name):
    if name == "":
        return True
    if name == "[]" or name == "{}" or name == "!" or name == ";":
        return False
    if all(c in _ATOM_SYMBOL_OK for c in name):
        return False
    if name[0].islower() and all(c.isalnum() or c == "_" for c in name):
        return False
    return True


def format_atom(name):
    if _atom_needs_quotes(name):
        escaped = name.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    return name


def term_to_str(term, quoted=False, max_priority=1200, depth=0):
    t = deref(term)
    if depth > 5000:
        return "..."
    if isinstance(t, Var):
        return f"_{t.name}" if not t.name.startswith("_") else t.name
    if isinstance(t, Num):
        return repr(t.value) if isinstance(t.value, float) else str(t.value)
    if isinstance(t, Atom):
        return format_atom(t.name) if quoted else t.name
    if isinstance(t, Struct):
        if t.name == "." and t.arity == 2:
            return _list_to_str(t, quoted, depth)
        if t.name == "{}" and t.arity == 1:
            return "{" + term_to_str(t.args[0], quoted, 1200, depth + 1) + "}"
        if t.arity == 2 and t.name in INFIX_OPS:
            pri, typ = INFIX_OPS[t.name]
            lp = pri - 1 if typ[0] == "x" else pri
            rp = pri - 1 if typ[2] == "x" else pri
            sep = t.name if t.name == "," else f"{t.name}"
            s = f"{term_to_str(t.args[0], quoted, lp, depth+1)}{sep}{term_to_str(t.args[1], quoted, rp, depth+1)}"
            if t.name != ",":
                s = f"{term_to_str(t.args[0], quoted, lp, depth+1)}{t.name}{term_to_str(t.args[1], quoted, rp, depth+1)}"
            return f"({s})" if pri > max_priority else s
        if t.arity == 1 and t.name in PREFIX_OPS:
            pri, typ = PREFIX_OPS[t.name]
            ap = pri - 1 if typ == "fx" else pri
            arg_str = term_to_str(t.args[0], quoted, ap, depth + 1)
            sep = " " if (t.name[-1].isalnum() or arg_str[:1] in "-0123456789" or arg_str[:1] == t.name[-1]) else ""
            s = f"{t.name}{sep}{arg_str}"
            return f"({s})" if pri > max_priority else s
        fname = format_atom(t.name) if quoted else t.name
        args = ",".join(term_to_str(a, quoted, 999, depth + 1) for a in t.args)
        return f"{fname}({args})"
    return str(t)


def _list_to_str(t, quoted, depth):
    parts = []
    cur = t
    while True:
        cur = deref(cur)
        if isinstance(cur, Struct) and cur.name == "." and cur.arity == 2:
            parts.append(term_to_str(cur.args[0], quoted, 999, depth + 1))
            cur = cur.args[1]
        else:
            break
    if isinstance(cur, Atom) and cur.name == "[]":
        return "[" + ",".join(parts) + "]"
    return "[" + ",".join(parts) + "|" + term_to_str(cur, quoted, 999, depth + 1) + "]"
