"""The Warren Abstract Machine: an iterative instruction dispatcher over
a tagged heap, an X-register file, an environment stack (permanent
variables), and a choice-point stack (backtracking).

Control addresses (P / CP / a choice point's retry target) are triples
`(indicator, clause_index, instr_index)`, or `None` for "halt: return to
whoever is driving this machine" -- either the top-level query or a
nested `meta_call` (used to implement findall/3, \\+/1, catch/3, and
call/N as real recursive sub-invocations of this same dispatcher, which
is exactly how meta-predicates work in real WAM-based systems).
"""
from .heap import (Cell, REF, STR, FUN, CON, new_ref, heap_deref, heap_bind,
                    heap_unify, heap_undo_to, reify, unify_heap_with_term,
                    push_term_cached)
from .terms import Atom, Var, Num, Struct, deref, copy_term, make_list, term_vars
from .compiler import compile_clause
from .golden import Database, indicator_of, BUILTIN_TABLE, unify as term_unify
from .terms import undo_to as term_undo_to, bind as term_bind
from .errors import PrologError, type_error, instantiation_error, existence_error
from .order import compare_terms, terms_equal

# Builtins reused as-is from the golden model: pure term/trail operations
# with no dependency on golden's resolution loop (`interp.solve`). Meta
# predicates (findall, \+, assert, catch, ...) get WAM-native
# implementations below instead, since they must run real compiled code.
_SHARED_BUILTIN_NAMES = {
    "=", "\\=", "==", "\\==", "@<", "@>", "@=<", "@>=", "compare", "is",
    "<", ">", "=<", ">=", "=:=", "=\\=", "var", "nonvar", "atom", "number",
    "integer", "float", "atomic", "compound", "callable", "is_list", "ground",
    "functor", "arg", "=..", "copy_term", "between", "succ", "plus",
    "atom_codes", "atom_chars", "char_code", "number_codes", "number_chars",
    "atom_length", "upcase_atom", "downcase_atom", "atom_concat",
    "split_string", "string_concat", "string_chars", "string_to_atom",
    "term_to_atom", "sort", "msort", "keysort", "length",
    "write", "print", "writeln", "write_canonical", "writeq", "nl", "tab",
}


def _adapt_golden_builtin(fn):
    """Golden-model builtins take (interp, args, trail); WAM builtins
    take (machine, args) with the machine itself standing in for interp
    (it has a compatible .write() method) and a fresh local trail closed
    over for that one call's lifetime."""
    def wrapper(machine, args):
        return fn(machine, args, [])
    return wrapper


class CP:
    """A choice point. `kind` selects which fields are meaningful:
      'clause' -- multiple candidate clauses for a predicate call
      'disj'   -- the right branch of a compiled (A;B) / (Cond->Then;Else)
      'pygen'  -- a Python-generator-backed builtin with more solutions
    """
    __slots__ = ("kind", "trail_mark", "heap_mark", "env_mark", "saved_CE",
                 "saved_CP", "saved_X", "arity", "candidates", "cursor",
                 "indicator", "alt_addr", "try_next", "resume_P")

    def __init__(self, kind, **kw):
        self.kind = kind
        for k, v in kw.items():
            setattr(self, k, v)


class Machine:
    def __init__(self, db=None, out=None):
        self.heap = []
        self.X = [None] * 64
        self.env_stack = []
        self.CE = None
        self.CP = None
        self.P = None
        self.trail = []
        self.choice_stack = []
        self.pending_cut_barrier = 0
        self.unify_base = 0
        self.unify_cursor = 0
        self.code = {}
        self.db = db if db is not None else Database()
        self.out = out
        # See the long comment in _call_builtin: generators for
        # meta-predicates that leave their own nested choice points on
        # choice_stack (instead of being wrapped in one themselves) must
        # not be allowed to become unreachable mid-computation.
        self._keepalive = []
        self.builtins = {}
        for name_arity, fn in BUILTIN_TABLE.items():
            if name_arity[0] in _SHARED_BUILTIN_NAMES:
                self.builtins[name_arity] = _adapt_golden_builtin(fn)
        self._install_meta_builtins()

    def write(self, s):
        if self.out is not None:
            self.out.write(s)

    # ---- compilation / database -------------------------------------
    def recompile_predicate(self, ind):
        clauses = self.db.preds.get(ind, [])
        self.code[ind] = [compile_clause(h, b) for h, b in clauses]

    def consult_terms(self, terms):
        from .dcg import translate_dcg
        touched = set()
        for t in terms:
            t = deref(t)
            if isinstance(t, Struct) and t.name == ":-" and t.arity == 1:
                self._run_directive(t.args[0])
                continue
            if isinstance(t, Struct) and t.name == "-->" and t.arity == 2:
                t = translate_dcg(t)
            ind = self.db.add_clause(t)
            touched.add(ind)
        for ind in touched:
            self.recompile_predicate(ind)

    def _run_directive(self, directive):
        d = deref(directive)
        if isinstance(d, Struct) and d.name == "dynamic":
            for ind in _parse_dynamic_spec(d.args[0]):
                self.db.declare_dynamic(ind)
                self.code.setdefault(ind, [])
            return
        ok = False
        for _ in self.meta_call(d):
            ok = True
            break
        if not ok:
            import sys
            from .pretty import term_to_str
            print(f"Warning: directive failed: {term_to_str(d)}", file=sys.stderr)

    def _ensure_x(self, n):
        while len(self.X) <= n:
            self.X.append(None)

    def _frame(self):
        return self.env_stack[self.CE]

    # ---- top-level query API ------------------------------------------
    def query(self, goal):
        """Yield {name: Term} dicts, one per solution, matching the
        golden Interpreter's query() interface. Each term is
        `copy_term`d into an independent snapshot -- see the matching
        note on golden.Interpreter.query for why that's essential."""
        qvars = [v for v in term_vars(goal) if not v.name.startswith("_")]
        for _ in self.meta_call(goal):
            yield {v.name: copy_term(deref(v)) for v in qvars}

    # ---- the dispatch loop ---------------------------------------------
    def _select_candidates(self, ind, arity):
        clauses = self.code[ind]
        if arity == 0 or not clauses:
            return list(range(len(clauses)))
        addr = heap_deref(self.heap, self.X[1])
        cell = self.heap[addr]
        if cell.tag == REF:
            return list(range(len(clauses)))
        if cell.tag == CON:
            v = cell.a
            key = ("atom", v.name) if isinstance(v, Atom) else ("num", v.value, isinstance(v.value, int))
        else:  # STR
            fun = self.heap[cell.a]
            key = ("struct", fun.a, fun.b)
        return [i for i, cl in enumerate(clauses) if cl.first_arg_key is None or cl.first_arg_key == key]

    def _do_call(self, ind):
        if ind in self.builtins:
            return self._call_builtin(ind)
        clauses = self.code.get(ind)
        if clauses is None:
            if ind in self.db.dynamic:
                return False
            raise existence_error("procedure", Struct("/", (Atom(ind[0]), Num(ind[1]))))
        candidates = self._select_candidates(ind, ind[1])
        if not candidates:
            return False
        cur_ind, cidx, iidx = self.P
        ret = (cur_ind, cidx, iidx + 1)
        barrier = len(self.choice_stack)
        # NOTE: saved_CE/saved_CP must be captured as what they will be
        # for EVERY candidate's activation (i.e. after `call` "returns"
        # to `ret`), not the caller's pre-call values -- every candidate
        # clause for this one call site shares the same continuation.
        if len(candidates) > 1:
            saved_X = [self.X[i] for i in range(1, ind[1] + 1)]
            cp = CP("clause", trail_mark=len(self.trail), heap_mark=len(self.heap),
                    env_mark=len(self.env_stack), saved_CE=self.CE, saved_CP=ret,
                    saved_X=saved_X, arity=ind[1], candidates=candidates, cursor=0, indicator=ind)
            self.choice_stack.append(cp)
        self.pending_cut_barrier = barrier
        self.CP = ret
        self.P = (ind, candidates[0], 0)
        return None

    def _call_builtin(self, ind):
        fn = self.builtins[ind]
        name, ar = ind
        cache = {}
        self._ensure_x(ar)
        arg_terms = [reify(self.heap, self.X[i], cache) for i in range(1, ar + 1)]
        gen = fn(self, arg_terms)
        cur_ind, cidx, iidx = self.P
        resume_P = (cur_ind, cidx, iidx + 1)
        saved_X = [self.X[i] for i in range(1, ar + 1)]
        trail_mark = len(self.trail)
        heap_mark = len(self.heap)
        env_mark = len(self.env_stack)
        saved_CE, saved_CP = self.CE, self.CP
        choice_mark = len(self.choice_stack)

        def try_next():
            try:
                next(gen)
            except StopIteration:
                return False
            rcache = {}
            for i in range(ar):
                if not unify_heap_with_term(self.heap, self.trail, saved_X[i], arg_terms[i], rcache):
                    return False
            return True

        if not try_next():
            return False
        if len(self.choice_stack) == choice_mark:
            # A "simple" builtin (is/2, between/3, atom_concat/3, ...):
            # its only retry mechanism is calling next() on its own
            # Python generator again, so wrap it in a choice point that
            # does exactly that.
            cp = CP("pygen", trail_mark=trail_mark, heap_mark=heap_mark, env_mark=env_mark,
                    saved_CE=saved_CE, saved_CP=saved_CP, saved_X=saved_X, arity=ar,
                    try_next=try_next, resume_P=resume_P)
            self.choice_stack.append(cp)
        else:
            # A meta-predicate (catch/3, call/N, clause/2, ...) whose own
            # execution runs real compiled code through meta_call and so
            # already left genuine 'clause'/'disj'/'pygen' choice points
            # of its OWN on the stack -- those ARE its retry mechanism,
            # reached by ordinary backtracking with no Python involved
            # for the 'clause'/'disj' cases. Wrapping it in ANOTHER
            # pygen choice point here would be worse than redundant:
            # since this Python generator is still on the call stack
            # right now, a later backtrack() reaching such a wrapper
            # would call next() on a generator that is already
            # executing -- a hard Python error.
            #
            # But `gen` (and, transitively through it, any meta_call
            # generator still suspended mid-yield underneath it, e.g.
            # catch/3's own recovery computation) must NOT become
            # unreachable now: with no choice point holding a reference
            # to it, CPython's refcounting GC would close it the moment
            # this function returns -- and closing a suspended meta_call
            # generator runs its `finally`, which restores P/CE/CP to
            # what THEY were when THAT generator started, clobbering the
            # self.P we are about to set below. Keeping a reference for
            # the machine's lifetime sidesteps that: a known, bounded
            # (one entry per meta-predicate call that leaves nested
            # choice points open), and harmless leak, rather than a
            # correctness bug.
            self._keepalive.append(gen)
        self.P = resume_P
        return None

    def backtrack(self, barrier):
        while len(self.choice_stack) > barrier:
            cp = self.choice_stack[-1]
            heap_undo_to(self.heap, self.trail, cp.trail_mark)
            del self.heap[cp.heap_mark:]
            del self.env_stack[cp.env_mark:]
            self.CE = cp.saved_CE
            self.CP = cp.saved_CP
            if cp.kind == "clause":
                for i in range(cp.arity):
                    self._ensure_x(i + 1)
                    self.X[i + 1] = cp.saved_X[i]
                cp.cursor += 1
                if cp.cursor >= len(cp.candidates):
                    self.choice_stack.pop()
                    continue
                self.pending_cut_barrier = len(self.choice_stack) - 1
                self.P = (cp.indicator, cp.candidates[cp.cursor], 0)
                return True
            if cp.kind == "disj":
                self.choice_stack.pop()
                self.P = cp.alt_addr
                return True
            if cp.kind == "pygen":
                for i in range(cp.arity):
                    self._ensure_x(i + 1)
                    self.X[i + 1] = cp.saved_X[i]
                if not cp.try_next():
                    self.choice_stack.pop()
                    continue
                self.P = cp.resume_P
                return True
            raise RuntimeError(f"bad choice point kind {cp.kind}")
        return False

    def _run_to_next_solution(self, barrier):
        while True:
            if self.P is None:
                return True
            ind, cidx, iidx = self.P
            instrs = self.code[ind][cidx].instrs
            instr = instrs[iidx]
            result = self._exec(instr)
            if result is False:
                if not self.backtrack(barrier):
                    return False
                continue
            if result is None:
                continue
            self.P = (ind, cidx, iidx + 1)

    def _exec(self, instr):
        op = instr[0]
        heap, trail = self.heap, self.trail

        if op == "get_var_x":
            _, vi, ai = instr
            self._ensure_x(vi)
            self.X[vi] = self.X[ai]
            return True
        if op == "get_var_y":
            _, yi, ai = instr
            self._frame()[3 + yi] = self.X[ai]
            return True
        if op == "get_val_x":
            _, vi, ai = instr
            return heap_unify(heap, trail, self.X[vi], self.X[ai])
        if op == "get_val_y":
            _, yi, ai = instr
            return heap_unify(heap, trail, self._frame()[3 + yi], self.X[ai])
        if op == "get_const":
            _, c, ai = instr
            addr = heap_deref(heap, self.X[ai])
            cell = heap[addr]
            if cell.tag == REF:
                heap.append(Cell(CON, c))
                heap_bind(heap, trail, addr, len(heap) - 1)
                return True
            if cell.tag == CON:
                v = cell.a
                if isinstance(v, Num) and isinstance(c, Num):
                    return v.value == c.value and isinstance(v.value, int) == isinstance(c.value, int)
                if isinstance(v, Atom) and isinstance(c, Atom):
                    return v.name == c.name
                return False
            return False
        if op == "get_struct":
            _, name, ar, ai = instr
            addr = heap_deref(heap, self.X[ai])
            cell = heap[addr]
            if cell.tag == REF:
                base, str_addr = self._build_struct(name, ar)
                heap_bind(heap, trail, addr, str_addr)
                self.unify_base, self.unify_cursor = base, 0
                return True
            if cell.tag == STR:
                fun = heap[cell.a]
                if fun.a != name or fun.b != ar:
                    return False
                self.unify_base, self.unify_cursor = cell.a + 1, 0
                return True
            return False
        if op == "put_struct":
            _, name, ar, ai = instr
            base, str_addr = self._build_struct(name, ar)
            self._ensure_x(ai)
            self.X[ai] = str_addr
            self.unify_base, self.unify_cursor = base, 0
            return True
        if op == "unify_var_x":
            _, vi = instr
            slot = self.unify_base + self.unify_cursor
            self.unify_cursor += 1
            self._ensure_x(vi)
            self.X[vi] = slot
            return True
        if op == "unify_var_y":
            _, yi = instr
            slot = self.unify_base + self.unify_cursor
            self.unify_cursor += 1
            self._frame()[3 + yi] = slot
            return True
        if op == "unify_val_x":
            _, vi = instr
            slot = self.unify_base + self.unify_cursor
            self.unify_cursor += 1
            return heap_unify(heap, trail, slot, self.X[vi])
        if op == "unify_val_y":
            _, yi = instr
            slot = self.unify_base + self.unify_cursor
            self.unify_cursor += 1
            return heap_unify(heap, trail, slot, self._frame()[3 + yi])
        if op == "unify_const":
            _, c = instr
            slot = self.unify_base + self.unify_cursor
            self.unify_cursor += 1
            heap.append(Cell(CON, c))
            return heap_unify(heap, trail, slot, len(heap) - 1)
        if op == "put_var_x":
            _, vi, ai = instr
            addr = new_ref(heap)
            self._ensure_x(max(vi, ai))
            self.X[vi] = addr
            self.X[ai] = addr
            return True
        if op == "put_var_y":
            _, yi, ai = instr
            addr = new_ref(heap)
            self._frame()[3 + yi] = addr
            self._ensure_x(ai)
            self.X[ai] = addr
            return True
        if op == "put_val_x":
            _, vi, ai = instr
            self._ensure_x(ai)
            self.X[ai] = self.X[vi]
            return True
        if op == "put_val_y":
            _, yi, ai = instr
            self._ensure_x(ai)
            self.X[ai] = self._frame()[3 + yi]
            return True
        if op == "put_const":
            _, c, ai = instr
            heap.append(Cell(CON, c))
            self._ensure_x(ai)
            self.X[ai] = len(heap) - 1
            return True
        if op == "allocate":
            _, n = instr
            frame = [self.CE, self.CP, self.pending_cut_barrier] + [None] * n
            self.env_stack.append(frame)
            self.CE = len(self.env_stack) - 1
            return True
        if op == "deallocate":
            frame = self._frame()
            self.CP = frame[1]
            self.CE = frame[0]
            return True
        if op == "proceed":
            self.P = self.CP
            return None
        if op == "cut":
            del self.choice_stack[self._frame()[2]:]
            return True
        if op == "get_level":
            _, yi = instr
            self._frame()[3 + yi] = len(self.choice_stack)
            return True
        if op == "cut_to":
            _, yi = instr
            del self.choice_stack[self._frame()[3 + yi]:]
            return True
        if op == "jump":
            _, target = instr
            ind, cidx, _ = self.P
            self.P = (ind, cidx, target)
            return None
        if op == "push_disj":
            _, target = instr
            ind, cidx, iidx = self.P
            cp = CP("disj", trail_mark=len(trail), heap_mark=len(heap), env_mark=len(self.env_stack),
                    saved_CE=self.CE, saved_CP=self.CP, alt_addr=(ind, cidx, target))
            self.choice_stack.append(cp)
            self.P = (ind, cidx, iidx + 1)
            return None
        if op == "fail":
            return False
        if op == "call":
            _, ind = instr
            return self._do_call(ind)
        raise RuntimeError(f"unknown instruction {instr!r}")

    def _build_struct(self, name, arity):
        heap = self.heap
        fun_addr = len(heap)
        heap.append(Cell(FUN, name, arity))
        base = len(heap)
        for k in range(arity):
            heap.append(Cell(REF, base + k))
        str_addr = len(heap)
        heap.append(Cell(STR, fun_addr))
        return base, str_addr

    # ---- meta-call: recursive nested invocation of this same machine --
    def meta_call(self, goal_term):
        """Run goal_term (a Term -- possibly a full control expression
        with ','/';'/'->'/'!' in it, not just a single predicate call)
        as an independent sub-computation of this same machine. Yields
        once per solution, with goal_term's own Vars bound to reflect
        it; fully undoes heap/trail state between yields.

        Implemented by compiling goal_term as the body of a throwaway
        single-clause predicate whose head takes goal_term's own free
        variables as arguments -- this is what lets findall/3, \\+/1,
        catch/3, and call/N reuse every control construct the compiler
        already knows how to handle for ordinary clause bodies, rather
        than re-implementing ',' etc. as a second, separate interpreter
        of goal terms. Real WAM-based systems do the analogous thing
        (compile-and-call) for a truly dynamic meta-call."""
        g = deref(goal_term)
        if isinstance(g, Var):
            raise instantiation_error()
        if not isinstance(g, (Atom, Struct)):
            raise type_error("callable", g)

        free_vars = term_vars(g)
        ind = self._compile_ad_hoc_goal(g, free_vars)

        cache = {}
        arg_addrs = [push_term_cached(self.heap, v, cache) for v in free_vars]

        # The TRUE caller's registers. Our own sub-computation gets its
        # own P/CE/CP "session" (fresh CE=None/CP=None, a private
        # barrier) that must be swapped in only while WE are actively
        # driving dispatch (inside _run_to_next_solution/backtrack), and
        # swapped back out around every yield -- a caller like catch/3
        # resumes running ordinary machine instructions of its OWN
        # between taking a solution from us and asking for the next one,
        # and it must see ITS registers, not our dead ad-hoc-clause ones.
        outer_P, outer_CE, outer_CP = self.P, self.CE, self.CP
        outer_pcb = self.pending_cut_barrier
        barrier0 = len(self.choice_stack)
        try:
            self._ensure_x(len(free_vars))
            for i, addr in enumerate(arg_addrs, start=1):
                self.X[i] = addr
            self.pending_cut_barrier = barrier0
            self.CP = None
            self.CE = None
            self.P = (ind, 0, 0)

            scratch_trail = []
            while True:
                ok = self._run_to_next_solution(barrier0)
                if not ok:
                    return
                good = True
                for i, v in enumerate(free_vars):
                    reified = reify(self.heap, arg_addrs[i], {})
                    if not term_unify(v, reified, scratch_trail):
                        good = False
                        break
                my_P, my_CE, my_CP, my_pcb = self.P, self.CE, self.CP, self.pending_cut_barrier
                self.P, self.CE, self.CP = outer_P, outer_CE, outer_CP
                self.pending_cut_barrier = outer_pcb
                if good:
                    yield
                self.P, self.CE, self.CP, self.pending_cut_barrier = my_P, my_CE, my_CP, my_pcb
                term_undo_to(scratch_trail, 0)
                if not self.backtrack(barrier0):
                    return
        finally:
            # If this generator is being closed early (a caller like \+,
            # catch/3, or once/1-via-call takes one solution and stops
            # without exhausting us -- GeneratorExit lands right after
            # the `yield` above, skipping the backtrack()/undo below it
            # entirely), any choice points OUR OWN computation pushed
            # are still sitting on choice_stack. Nothing outside this
            # call may ever backtrack into them again, so discard them
            # here rather than relying on the loop body having run.
            del self.choice_stack[barrier0:]
            self.P, self.CE, self.CP = outer_P, outer_CE, outer_CP
            self.pending_cut_barrier = outer_pcb
            del self.code[ind]

    _adhoc_counter = 0

    def _compile_ad_hoc_goal(self, goal, free_vars):
        Machine._adhoc_counter += 1
        name = f"$meta{Machine._adhoc_counter}"
        ind = (name, len(free_vars))
        head = Struct(name, tuple(free_vars)) if free_vars else Atom(name)
        self.code[ind] = [compile_clause(head, goal)]
        return ind

    # ---- WAM-native meta builtins --------------------------------------
    def _install_meta_builtins(self):
        b = self.builtins
        b[("\\+", 1)] = _bi_naf
        b[("not", 1)] = _bi_naf
        b[("$naf", 1)] = _bi_naf
        for n in range(1, 9):
            b[("call", n)] = _make_call(n)
        b[("catch", 3)] = _bi_catch
        b[("throw", 1)] = _bi_throw
        b[("findall", 3)] = _bi_findall
        b[("forall", 2)] = _bi_forall
        b[("aggregate_all", 3)] = _bi_aggregate_all
        b[("bagof", 3)] = _bi_bagof
        b[("setof", 3)] = _bi_setof
        b[("assert", 1)] = _bi_assertz
        b[("assertz", 1)] = _bi_assertz
        b[("asserta", 1)] = _bi_asserta
        b[("retract", 1)] = _bi_retract
        b[("retractall", 1)] = _bi_retractall
        b[("clause", 2)] = _bi_clause
        b[("halt", 0)] = _bi_halt0
        b[("halt", 1)] = _bi_halt1


def _undo_all(machine, trail_mark, heap_mark):
    heap_undo_to(machine.heap, machine.trail, trail_mark)
    del machine.heap[heap_mark:]


def _bi_naf(machine, args):
    trail_mark, heap_mark = len(machine.trail), len(machine.heap)
    found = False
    gen = machine.meta_call(args[0])
    try:
        for _ in gen:
            found = True
            break
    finally:
        gen.close()
    _undo_all(machine, trail_mark, heap_mark)
    if not found:
        yield


def _make_call(n):
    def fn(machine, args):
        g = deref(args[0])
        extra = args[1:]
        if extra:
            if isinstance(g, Atom):
                g = Struct(g.name, tuple(extra))
            elif isinstance(g, Struct):
                g = Struct(g.name, g.args + tuple(extra))
            else:
                raise type_error("callable", g)
        yield from machine.meta_call(g)
    return fn


def _bi_catch(machine, args):
    goal, catcher, recovery = args
    trail_mark, heap_mark = len(machine.trail), len(machine.heap)
    gen = machine.meta_call(goal)
    while True:
        try:
            next(gen)
        except StopIteration:
            return
        except PrologError as e:
            gen.close()
            _undo_all(machine, trail_mark, heap_mark)
            ball = copy_term(e.term)
            scratch = []
            if term_unify(catcher, ball, scratch):
                yield from machine.meta_call(recovery)
                return
            term_undo_to(scratch, 0)
            raise
        else:
            yield


def _bi_throw(machine, args):
    raise PrologError(copy_term(args[0]))
    yield  # pragma: no cover - keeps this a generator


def _bi_findall(machine, args):
    template, goal, result = args
    results = []
    for _ in machine.meta_call(goal):
        results.append(copy_term(template))
    if term_unify(result, make_list(results), []):
        yield


def _bi_forall(machine, args):
    cond, action = args
    ok = True
    for _ in machine.meta_call(cond):
        found = False
        for _ in machine.meta_call(action):
            found = True
            break
        if not found:
            ok = False
            break
    if ok:
        yield


def _bi_aggregate_all(machine, args):
    from .arith import eval_arith
    spec, goal, result = args
    spec_t = deref(spec)
    if isinstance(spec_t, Struct) and spec_t.arity == 1 and spec_t.name in ("count", "bag", "set", "sum", "max", "min"):
        template = spec_t.args[0]
        kind = spec_t.name
    else:
        template = spec_t
        kind = "bag"
    results = [copy_term(template) for _ in machine.meta_call(goal)]
    if kind == "count":
        out = Num(len(results))
    elif kind == "sum":
        out = Num(sum(eval_arith(r) for r in results) if results else 0)
    elif kind == "max":
        out = Num(max(eval_arith(r) for r in results))
    elif kind == "min":
        out = Num(min(eval_arith(r) for r in results))
    elif kind == "set":
        import functools
        uniq = []
        for r in sorted(results, key=functools.cmp_to_key(compare_terms)):
            if not uniq or not terms_equal(uniq[-1], r):
                uniq.append(r)
        out = make_list(uniq)
    else:
        out = make_list(results)
    if term_unify(result, out, []):
        yield


def _bi_bagof(machine, args):
    template, goal, result = args
    g = deref(goal)
    while isinstance(g, Struct) and g.name == "^" and g.arity == 2:
        g = deref(g.args[1])
    results = [copy_term(template) for _ in machine.meta_call(g)]
    if results and term_unify(result, make_list(results), []):
        yield


def _bi_setof(machine, args):
    import functools
    template, goal, result = args
    g = deref(goal)
    while isinstance(g, Struct) and g.name == "^" and g.arity == 2:
        g = deref(g.args[1])
    results = [copy_term(template) for _ in machine.meta_call(g)]
    if not results:
        return
    results.sort(key=functools.cmp_to_key(compare_terms))
    uniq = [results[0]]
    for r in results[1:]:
        if not terms_equal(uniq[-1], r):
            uniq.append(r)
    if term_unify(result, make_list(uniq), []):
        yield


def _bi_assertz(machine, args):
    ind = machine.db.add_clause(copy_term(args[0]))
    machine.db.dynamic.add(ind)
    machine.recompile_predicate(ind)
    yield


def _bi_asserta(machine, args):
    ind = machine.db.add_clause(copy_term(args[0]), front=True)
    machine.db.dynamic.add(ind)
    machine.recompile_predicate(ind)
    yield


def _bi_retract(machine, args):
    from .terms import Struct as S
    t = deref(args[0])
    if isinstance(t, S) and t.name == ":-" and t.arity == 2:
        pat_head, pat_body = t.args
    else:
        pat_head, pat_body = t, Atom("true")
    ind = indicator_of(pat_head)
    clauses = machine.db.preds.get(ind, [])
    for i, (h, bd) in enumerate(clauses):
        scratch = []
        mapping = {}
        h2, b2 = copy_term(h, mapping), copy_term(bd, mapping)
        if term_unify(pat_head, h2, scratch) and term_unify(pat_body, b2, scratch):
            del clauses[i]
            machine.recompile_predicate(ind)
            yield
            return
        term_undo_to(scratch, 0)


def _bi_retractall(machine, args):
    pat_head = deref(args[0])
    ind = indicator_of(pat_head)
    clauses = machine.db.preds.get(ind, [])
    kept = []
    for h, bd in clauses:
        scratch = []
        if not term_unify(pat_head, copy_term(h), scratch):
            kept.append((h, bd))
        term_undo_to(scratch, 0)
    machine.db.preds[ind] = kept
    machine.db.dynamic.add(ind)
    machine.recompile_predicate(ind)
    yield


def _bi_clause(machine, args):
    head, body = args
    ind = indicator_of(deref(head))
    for h, bd in list(machine.db.preds.get(ind, [])):
        scratch = []
        mapping = {}
        h2, b2 = copy_term(h, mapping), copy_term(bd, mapping)
        if term_unify(head, h2, scratch) and term_unify(body, b2, scratch):
            yield
        term_undo_to(scratch, 0)


def _bi_halt0(machine, args):
    raise SystemExit(0)
    yield


def _bi_halt1(machine, args):
    from .arith import eval_arith
    raise SystemExit(int(eval_arith(args[0])))
    yield


def _parse_dynamic_spec(term):
    t = deref(term)
    out = []
    if isinstance(t, Struct) and t.name == "," and t.arity == 2:
        out += _parse_dynamic_spec(t.args[0])
        out += _parse_dynamic_spec(t.args[1])
    elif isinstance(t, Struct) and t.name == "/" and t.arity == 2:
        out.append((deref(t.args[0]).name, deref(t.args[1]).value))
    return out
