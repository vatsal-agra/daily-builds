"""Definite Clause Grammar (`-->`) translation to ordinary difference-list
clauses, exactly the source-to-source transform real Prolog systems apply
before compiling a DCG rule."""
from .terms import Atom, Var, Struct, deref, make_list


def translate_dcg(rule):
    """rule is Struct('-->', (Head, Body)). Returns an ordinary
    Struct(':-', (Head', Body')) clause with two extra difference-list
    arguments threaded through."""
    head, body = rule.args
    head = deref(head)
    push_back = None
    if isinstance(head, Struct) and head.name == "," and head.arity == 2:
        head, push_back = head.args
        head = deref(head)

    s0, s = Var("S0"), Var("S")
    new_head = _extend(head, s0, s)
    if push_back is None:
        new_body = _translate_body(body, s0, s)
    else:
        s1 = Var("S1")
        new_body = Struct(",", (_translate_body(body, s0, s1), _terminal_goal(push_back, s, s1)))
    return Struct(":-", (new_head, new_body))


def _extend(nonterminal, s0, s):
    nt = deref(nonterminal)
    if isinstance(nt, Atom):
        return Struct(nt.name, (s0, s))
    if isinstance(nt, Struct):
        return Struct(nt.name, nt.args + (s0, s))
    raise ValueError(f"bad DCG nonterminal: {nt}")


def _terminal_goal(list_term, s0, s):
    """S0 = [terminal items... | S]"""
    from .terms import list_to_python
    items = list_to_python(list_term)
    return Struct("=", (s0, make_list(items, s)))


def _translate_body(body, s0, s):
    b = deref(body)

    if isinstance(b, Atom) and b.name == "[]":
        return Struct("=", (s0, s))

    if isinstance(b, Struct) and b.name == "." and b.arity == 2:
        return _terminal_goal(b, s0, s)

    if isinstance(b, Struct) and b.name == "{}" and b.arity == 1:
        return Struct(",", (b.args[0], Struct("=", (s0, s))))

    if isinstance(b, Atom) and b.name == "!":
        return Struct(",", (Atom("!"), Struct("=", (s0, s))))

    if isinstance(b, Struct) and b.name == "\\+" and b.arity == 1:
        s1 = Var()
        return Struct(",", (Struct("\\+", (_translate_body(b.args[0], s0, s1),)), Struct("=", (s0, s))))

    if isinstance(b, Struct) and b.name == "," and b.arity == 2:
        s1 = Var()
        return Struct(",", (_translate_body(b.args[0], s0, s1), _translate_body(b.args[1], s1, s)))

    if isinstance(b, Struct) and b.name in (";", "|") and b.arity == 2:
        return Struct(";", (_translate_body(b.args[0], s0, s), _translate_body(b.args[1], s0, s)))

    if isinstance(b, Struct) and b.name == "->" and b.arity == 2:
        s1 = Var()
        return Struct("->", (_translate_body(b.args[0], s0, s1), _translate_body(b.args[1], s1, s)))

    if isinstance(b, Struct) and b.name == "call":
        return Struct("call", b.args + (s0, s))

    # ordinary nonterminal (atom or compound)
    return _extend(b, s0, s)
