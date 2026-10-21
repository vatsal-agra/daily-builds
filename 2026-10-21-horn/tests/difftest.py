#!/usr/bin/env python3
"""Differential test: random pure-ish Prolog programs (facts, rules, cut, if-then-else, negation,
disjunction, arithmetic guards, call/1, findall) are solved by Horn and by an independent reference
SLD interpreter written here in Python. The ordered answer lists must be identical.

usage: difftest.py [N programs] [seed]
"""
import random, subprocess, sys, os, tempfile

sys.setrecursionlimit(100000)

# ---------------- terms ----------------
# atom: str ; int ; ('v', name) variable ; ('f', functor, args...) compound ; list = nested '.'-compounds
class V:
    __slots__ = ('n',)
    cnt = 0
    def __init__(self):
        V.cnt += 1; self.n = V.cnt

NIL = '[]'
def lst(items, tail=NIL):
    r = tail
    for x in reversed(items): r = ('.', x, r)
    return r

def walk(t, env):
    while isinstance(t, V) and t in env: t = env[t]
    return t

def occurs(v, t, env):
    t = walk(t, env)
    if t is v: return True
    if isinstance(t, tuple): return any(occurs(v, x, env) for x in t[1:])
    return False

def unify(a, b, env):
    a = walk(a, env); b = walk(b, env)
    if a is b: return True
    if isinstance(a, V):
        if occurs(a, b, env): return False
        env[a] = b; return True
    if isinstance(b, V):
        if occurs(b, a, env): return False
        env[b] = a; return True
    if isinstance(a, tuple) and isinstance(b, tuple):
        if a[0] != b[0] or len(a) != len(b): return False
        return all(unify(x, y, env) for x, y in zip(a[1:], b[1:]))
    return type(a) == type(b) and a == b

def resolve(t, env):
    t = walk(t, env)
    if isinstance(t, tuple): return (t[0],) + tuple(resolve(x, env) for x in t[1:])
    return t

def rename(t, m):
    if isinstance(t, V):
        if t not in m: m[t] = V()
        return m[t]
    if isinstance(t, tuple): return (t[0],) + tuple(rename(x, m) for x in t[1:])
    return t

def show(t, names):
    if isinstance(t, V):
        if t not in names: names[t] = chr(ord('A') + len(names)) if len(names) < 26 else 'V%d' % len(names)
        return names[t]
    if isinstance(t, int): return str(t)
    if isinstance(t, str): return t
    if t[0] == '.':
        items = []; cur = t
        while isinstance(cur, tuple) and cur[0] == '.':
            items.append(show(cur[1], names)); cur = cur[2]
        if cur == NIL: return '[' + ','.join(items) + ']'
        return '[' + ','.join(items) + '|' + show(cur, names) + ']'
    if t[0] == '-' and len(t) == 3: return show(t[1], names) + '-' + show(t[2], names)
    return t[0] + '(' + ','.join(show(x, names) for x in t[1:]) + ')'

# ---------------- reference interpreter ----------------
class Throw(Exception):
    def __init__(self, ball): self.ball = ball

class Prog:
    def __init__(self): self.preds = {}
    def add(self, head, body):
        self.preds.setdefault((head[0], len(head) - 1), []).append((head, body))

def evalarith(t, env):
    t = walk(t, env)
    if isinstance(t, tuple) and t[0] in '+-*' and len(t) == 3:
        pass
    if isinstance(t, int): return t
    if isinstance(t, tuple) and t[0] == '.' and walk(t[2], env) == NIL: return evalarith(t[1], env)
    if isinstance(t, tuple) and len(t) == 3 and t[0] in '+-*':
        a, b = evalarith(t[1], env), evalarith(t[2], env)
        return a + b if t[0] == '+' else a - b if t[0] == '-' else a * b
    if isinstance(t, V):
        raise Throw(('error', 'instantiation_error', V()))
    if isinstance(t, str):
        raise Throw(('error', ('type_error', 'evaluable', ('/', t, 0)), V()))
    if isinstance(t, tuple):
        raise Throw(('error', ('type_error', 'evaluable', ('/', t[0], len(t) - 1)), V()))
    raise TypeError('arith')

def solve(goals, env, cut, prog):
    if not goals:
        yield env; return
    g, rest = goals[0], goals[1:]
    g = walk(g, env)
    if isinstance(g, V): raise TypeError('inst')
    if g == 'true':
        yield from solve(rest, env, cut, prog); return
    if g == 'fail': return
    if g == '!':
        yield from solve(rest, env, cut, prog)
        cut[0] = True
        return
    if isinstance(g, tuple):
        f, n = g[0], len(g) - 1
        if f == ',' and n == 2:
            yield from solve([g[1], g[2]] + rest, env, cut, prog); return
        if f == ';' and n == 2:
            l = walk(g[1], env)
            if isinstance(l, tuple) and l[0] == '->' and len(l) == 3:
                first = next(solve([l[1]], env, [False], prog), None)
                if first is not None: yield from solve([l[2]] + rest, first, cut, prog)
                else: yield from solve([g[2]] + rest, env, cut, prog)
                return
            for alt in (g[1], g[2]):
                yield from solve([alt] + rest, env, cut, prog)
                if cut[0]: return
            return
        if f == '->' and n == 2:
            first = next(solve([g[1]], env, [False], prog), None)
            if first is not None: yield from solve([g[2]] + rest, first, cut, prog)
            return
        if f == '\\+' and n == 1:
            if next(solve([g[1]], env, [False], prog), None) is None:
                yield from solve(rest, env, cut, prog)
            return
        if f == 'call' and n == 1:
            for e in solve([g[1]], env, [False], prog):
                yield from solve(rest, e, cut, prog)
                if cut[0]: return
            return
        if f == '=' and n == 2:
            e = dict(env)
            if unify(g[1], g[2], e): yield from solve(rest, e, cut, prog)
            return
        if f == '\\=' and n == 2:
            e = dict(env)
            if not unify(g[1], g[2], e): yield from solve(rest, env, cut, prog)
            return
        if f == 'is' and n == 2:
            v = evalarith(g[2], env)
            e = dict(env)
            if unify(g[1], v, e): yield from solve(rest, e, cut, prog)
            return
        if f in ('<', '>', '=<', '>=', '=:=') and n == 2:
            a, b = evalarith(g[1], env), evalarith(g[2], env)
            ok = {'<': a < b, '>': a > b, '=<': a <= b, '>=': a >= b, '=:=': a == b}[f]
            if ok: yield from solve(rest, env, cut, prog)
            return
        if f in ('==', '\\==') and n == 2:
            a, b = resolve(g[1], env), resolve(g[2], env)
            same = same_term(a, b)
            if same == (f == '=='): yield from solve(rest, env, cut, prog)
            return
        if f == 'throw' and n == 1:
            raise Throw(rename(resolve(g[1], env), {}))
        if f == 'catch' and n == 3:
            gen = solve([g[1]], env, [False], prog)
            while True:
                try:
                    e = next(gen)
                except StopIteration:
                    break
                except Throw as t:
                    e2 = dict(env)
                    if unify(g[2], rename(t.ball, {}), e2):
                        yield from solve([g[3]] + rest, e2, cut, prog)
                        return
                    raise
                yield from solve(rest, e, cut, prog)
                if cut[0]: return
            return
        if f == 'findall' and n == 3:
            res = []
            for e in solve([g[2]], env, [False], prog):
                res.append(rename(resolve(g[1], e), {}))
            e = dict(env)
            if unify(g[3], lst(res), e): yield from solve(rest, e, cut, prog)
            return
        if f in ('var', 'nonvar', 'atom', 'integer', 'atomic', 'compound') and n == 1:
            a = walk(g[1], env)
            ok = {'var': isinstance(a, V), 'nonvar': not isinstance(a, V),
                  'atom': isinstance(a, str), 'integer': isinstance(a, int),
                  'atomic': isinstance(a, (str, int)), 'compound': isinstance(a, tuple)}[f]
            if ok: yield from solve(rest, env, cut, prog)
            return
        key = (f, n)
        args = g[1:]
    elif isinstance(g, str):
        key, args = (g, 0), ()
    else:
        raise TypeError('callable')
    if key not in prog.preds: raise LookupError('unknown %s/%d' % key)
    newcut = [False]
    for head, body in prog.preds[key]:
        m = {}
        h = rename(head, m)
        e = dict(env)
        if all(unify(a, b, e) for a, b in zip(args, h[1:] if isinstance(h, tuple) else ())):
            b = rename(body, m)
            yield from solve([b] + rest if False else [b], e, newcut, prog) if False else solve_then(b, e, newcut, rest, env, cut, prog)
            if newcut[0] or cut[0]: return

def solve_then(body, e, newcut, rest, env0, cut, prog):
    # run clause body with its own cut barrier, then the continuation with the caller's
    for e2 in solve([body], e, newcut, prog):
        yield from solve(rest, e2, cut, prog)
        if cut[0] or newcut[0] and False: return

def same_term(a, b):
    if isinstance(a, V) or isinstance(b, V): return a is b
    if isinstance(a, tuple) and isinstance(b, tuple):
        return a[0] == b[0] and len(a) == len(b) and all(same_term(x, y) for x, y in zip(a[1:], b[1:]))
    return type(a) == type(b) and a == b

# ---------------- random program generator ----------------
ATOMS = ['a', 'b', 'c', 'd']
def rnd_ground(r, depth=2):
    k = r.random()
    if depth == 0 or k < 0.35: return r.choice(ATOMS)
    if k < 0.55: return r.randint(0, 4)
    if k < 0.75: return ('f', rnd_ground(r, depth - 1))
    if k < 0.9: return ('g', rnd_ground(r, depth - 1), rnd_ground(r, depth - 1))
    return lst([rnd_ground(r, depth - 1) for _ in range(r.randint(0, 3))])

def rnd_term(r, vars_, depth=2):
    k = r.random()
    if vars_ and k < 0.4: return r.choice(vars_)
    if depth == 0 or k < 0.6: return rnd_ground(r, 1)
    if k < 0.75: return ('f', rnd_term(r, vars_, depth - 1))
    if k < 0.85: return ('g', rnd_term(r, vars_, depth - 1), rnd_term(r, vars_, depth - 1))
    return lst([rnd_term(r, vars_, depth - 1) for _ in range(r.randint(0, 2))], r.choice([NIL, NIL] + vars_[:1]))

def gen_program(r):
    prog = Prog(); lines = []
    npred = r.randint(3, 6)
    arities = [r.randint(1, 3) for _ in range(npred)]
    for i in range(npred):
        name = 'p%d' % i
        for _ in range(r.randint(1, 5)):
            vs = [V() for _ in range(r.randint(1, 3))]
            head = (name,) + tuple(rnd_term(r, vs, 1) for _ in range(arities[i]))
            goals = []
            for _ in range(r.choice([0, 0, 1, 1, 2, 3])):
                goals.append(rnd_goal(r, vs, i, arities, npred))
            body = goals_to_body(goals)
            prog.add(head, body)
            lines.append(clause_text(head, body))
    return prog, arities, '\n'.join(lines) + '\n'

def rnd_goal(r, vs, i, arities, npred, depth=2):
    k = r.random()
    j = r.randint(i + 1, npred) if i + 1 < npred else None
    def call():
        if j is None or j >= npred: return None
        return ('p%d' % j,) + tuple(rnd_term(r, vs, 1) for _ in range(arities[j]))
    if k < 0.40:
        c = call()
        if c: return c
    if k < 0.48: return '!'
    if k < 0.56: return ('=', rnd_term(r, vs, 1), rnd_term(r, vs, 1))
    if k < 0.60: return ('\\=', rnd_term(r, vs, 1), rnd_term(r, vs, 1))
    if k < 0.66 and vs:
        v = r.choice(vs); return (r.choice(['<', '>', '=<', '>=', '=:=']), v, r.randint(0, 4))
    if k < 0.70 and vs:
        return ('is', r.choice(vs), (r.choice('+-*'), r.randint(0, 3), r.randint(0, 3)))
    if depth > 0:
        if k < 0.78:
            return (';', rnd_goal(r, vs, i, arities, npred, depth - 1), rnd_goal(r, vs, i, arities, npred, depth - 1))
        if k < 0.86:
            return (';', ('->', rnd_goal(r, vs, i, arities, npred, depth - 1), rnd_goal(r, vs, i, arities, npred, depth - 1)),
                    rnd_goal(r, vs, i, arities, npred, depth - 1))
        if k < 0.92:
            return ('\\+', rnd_goal(r, vs, i, arities, npred, depth - 1))
        if k < 0.96:
            return ('call', rnd_goal(r, vs, i, arities, npred, depth - 1))
    if k < 0.975 and vs: return ('var', r.choice(vs))
    if k < 0.985:
        return ('throw', rnd_ground(r, 1))
    if k < 0.993 and depth > 0:
        return ('catch', rnd_goal(r, vs, i, arities, npred, depth - 1), r.choice([rnd_ground(r, 1)] + vs[:1]), rnd_goal(r, vs, i, arities, npred, depth - 1))
    if k < 1.0 and vs and depth > 0:
        return ('findall', r.choice(vs), rnd_goal(r, vs, i, arities, npred, depth - 1), V())
    return 'true'

def goals_to_body(goals):
    if not goals: return 'true'
    b = goals[-1]
    for g in reversed(goals[:-1]): b = (',', g, b)
    return b

# --- text rendering for Horn
def ptext(t, names):
    if isinstance(t, V):
        if t not in names: names[t] = 'V%d' % len(names)
        return names[t]
    if isinstance(t, int): return str(t)
    if isinstance(t, str): return t
    if t[0] == '.':
        items = []; cur = t
        while isinstance(cur, tuple) and cur[0] == '.':
            items.append(ptext(cur[1], names)); cur = cur[2]
        return '[' + ','.join(items) + ('' if cur == NIL else '|' + ptext(cur, names)) + ']'
    if t[0] in (',', ';', '->', '=', '\\=', 'is', '<', '>', '=<', '>=', '=:=', '+', '-', '*') and len(t) == 3:
        return '(' + ptext(t[1], names) + ' ' + t[0] + ' ' + ptext(t[2], names) + ')'
    if t[0] == '\\+' and len(t) == 2:
        return '\\+ (' + ptext(t[1], names) + ')'
    return t[0] + '(' + ','.join(ptext(x, names) for x in t[1:]) + ')'

def clause_text(head, body):
    names = {}
    h = ptext(head, names)
    return h + ('.' if body == 'true' else ' :- ' + ptext(body, names) + '.')

def gen_queries(r, arities, npred):
    qs = []
    for _ in range(r.randint(3, 6)):
        i = r.randint(0, npred - 1)
        vs = [V() for _ in range(arities[i])]
        args = tuple(r.choice(vs + [rnd_ground(r, 1)]) if r.random() < 0.8 else rnd_ground(r, 1) for _ in range(arities[i]))
        qs.append(('p%d' % i,) + args)
    return qs

def ref_answers(prog, q, limit=200):
    out = []
    vs = []
    collect_vars(q, vs)
    try:
        for e in solve([q], {}, [False], prog):
            names = {}
            out.append(' '.join(show(resolve(v, e), names) for v in vs) if vs else 'yes')
            # variables in answers are named by order of first appearance within one answer
            if len(out) >= limit: break
    except (TypeError, LookupError, ZeroDivisionError, Throw) as ex:
        return ['error']
    return out

def collect_vars(t, acc):
    if isinstance(t, V):
        if t not in acc: acc.append(t)
    elif isinstance(t, tuple):
        for x in t[1:]: collect_vars(x, acc)

def horn_script(qs):
    lines = []
    for idx, q in enumerate(qs):
        vs = []; collect_vars(q, vs)
        names = {v: 'Q%d' % i for i, v in enumerate(vs)}
        goal = ptext(q, names)
        tmpl = 'r(' + ','.join(names[v] for v in vs) + ')' if vs else 'yes'
        lines.append(":- catch((findall(%s, %s, L0), '$limit'(L0, 200, L), forall(member(S, L), (\\+ \\+ (numbervars(S, 0, _), '$show'(S))))), _, writeln(error)), writeln('--').\n" % (tmpl, goal))
    return '\n'.join(lines)

HELPERS = """
'$limit'(L, N, R) :- length(L, K), ( K > N -> length(R, N), append(R, _, L) ; R = L ).
'$show'(yes) :- !, writeln(yes).
'$show'(r(A)) :- !, '$show1'([A]).
'$show'(r(A,B)) :- !, '$show1'([A,B]).
'$show'(r(A,B,C)) :- !, '$show1'([A,B,C]).
'$show'(r(A,B,C,D)) :- !, '$show1'([A,B,C,D]).
'$show1'(L) :- forall(nth0(I, L, X), ( I > 0 -> write(' ') ; true ), write(X)), nl).
"""

def run(n, seed):
    bad = 0
    for k in range(n):
        r = random.Random(seed * 100003 + k)
        V.cnt = 0
        prog, arities, text = gen_program(r)
        qs = gen_queries(r, arities, len(arities))
        expected = []
        for q in qs:
            expected.append('\n'.join(ref_answers(prog, q) + ['--']))
        helpers = HELPERS.replace("forall(nth0(I, L, X), ( I > 0 -> write(' ') ; true ), write(X)), nl)", "forall(nth0(I, L, X), ((I > 0 -> write(' ') ; true), write(X))), nl")
        src = ':- set_prolog_flag(occurs_check, true).\n' + text + helpers + horn_script(qs)
        with tempfile.NamedTemporaryFile('w', suffix='.pl', delete=False) as f:
            f.write(src); path = f.name
        try:
            res = subprocess.run([os.path.join(os.path.dirname(__file__), '..', 'horn'), path, '-g', 'halt'], capture_output=True, text=True, timeout=60); out = res.stdout; errtxt = res.stderr
        except subprocess.TimeoutExpired:
            out = 'TIMEOUT'; errtxt = ''
        if os.environ.get('KEEP'): print('kept', path)
        else: os.unlink(path)
        got_list = [x.strip() for x in out.split('--\n')][:len(qs)]
        want_list = [e[:-2].strip() for e in expected]
        got_list += [''] * (len(qs) - len(got_list))
        if [normalize(x) for x in got_list] != [normalize(x) for x in want_list]:
            bad += 1
            print('MISMATCH program %d (seed %d)' % (k, seed))
            if bad <= 2:
                print(text)
                print('stderr:', errtxt[:300])
                for i, (g, w) in enumerate(zip(got_list, want_list)):
                    if normalize(g) != normalize(w):
                        vs = collect_vars_list(qs[i])
                        print('query %d: %s\n--- horn:\n%s\n--- reference:\n%s' % (i, ptext(qs[i], {v: 'Q%d' % j for j, v in enumerate(vs)}), g[:600], w[:600]))
                        break
    print('%d programs, %d mismatches' % (n, bad))
    return bad

def collect_vars_list(q):
    acc = []; collect_vars(q, acc); return acc

def normalize(s):
    # variable names in answers: Horn prints A,B,... via numbervars; the reference uses the same scheme
    return '\n'.join(l.strip() for l in s.strip().split('\n') if l.strip() != '')

if __name__ == '__main__':
    import threading
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    threading.stack_size(512 * 1024 * 1024)
    res = []
    t = threading.Thread(target=lambda: res.append(run(n, seed)))
    t.start(); t.join()
    sys.exit(1 if (not res or res[0]) else 0)
