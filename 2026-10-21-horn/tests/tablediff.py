#!/usr/bin/env python3
"""Differential test for tabling: random graphs, three formulations of reachability
(left-, right- and double-recursive) plus min-mode shortest paths, against Python closure/Floyd-Warshall.
usage: tablediff.py [N graphs] [seed]"""
import random, subprocess, sys, os, tempfile, itertools

def closure(n, edges):
    reach = [set() for _ in range(n)]
    for a, b in edges: reach[a].add(b)
    changed = True
    while changed:
        changed = False
        for a in range(n):
            new = set(reach[a])
            for b in reach[a]: new |= reach[b]
            if new != reach[a]: reach[a] = new; changed = True
    return reach

def floyd(n, wedges):
    INF = 10**9
    d = [[INF] * n for _ in range(n)]
    for a, b, w in wedges: d[a][b] = min(d[a][b], w)
    for k in range(n):
        for i in range(n):
            for j in range(n):
                if d[i][k] + d[k][j] < d[i][j]: d[i][j] = d[i][k] + d[k][j]
    return d, INF

def run(N, seed):
    bad = 0
    for g in range(N):
        r = random.Random(seed * 7919 + g)
        n = r.randint(3, 9)
        edges = list({(r.randrange(n), r.randrange(n)) for _ in range(r.randint(2, 18))})
        wedges = [(a, b, r.randint(1, 9)) for a, b in edges]
        reach = closure(n, edges)
        d, INF = floyd(n, wedges)
        prog = ''
        for a, b in edges: prog += 'e(n%d,n%d).\n' % (a, b)
        for a, b, w in wedges: prog += 'w(n%d,n%d,%d).\n' % (a, b, w)
        prog += """
:- table pl/2, pr/2, pd/2, sp(_,_,min), mut_a/2, mut_b/2.
pl(X,Y) :- pl(X,Z), e(Z,Y).
pl(X,Y) :- e(X,Y).
pr(X,Y) :- e(X,Y).
pr(X,Y) :- e(X,Z), pr(Z,Y).
pd(X,Y) :- e(X,Y).
pd(X,Y) :- pd(X,Z), pd(Z,Y).
sp(X,Y,C) :- w(X,Y,C).
sp(X,Y,C) :- sp(X,Z,C1), w(Z,Y,C2), C is C1+C2.
mut_a(X,Y) :- e(X,Y).
mut_a(X,Y) :- mut_b(X,Z), e(Z,Y).
mut_b(X,Y) :- mut_a(X,Z), e(Z,Y).
all(P, L) :- findall(X-Y, call(P, X, Y), L0), sort(L0, L).
:- forall(member(P, [pl, pr, pd]), (all(P, L), forall(member(X-Y, L), (write(P-X-Y), nl)), write(P-done), nl)).
:- all(sp3, _) -> true ; true.
:- findall(X-Y-C, sp(X, Y, C), L0), sort(L0, L), forall(member(X-Y-C, L), (write(sp(X,Y,C)), nl)), write(sp-done), nl.
:- findall(X-Y, mut_a(X, Y), L0), sort(L0, L), forall(member(X-Y, L), (write(mut_a(X,Y)), nl)), write(mut-done), nl.
:- forall(between(0, %d, I), (atom_concat(n, I, S), findall(Y, pl(S, Y), L0), sort(L0, L), write(from(S, L)), nl)).
:- forall(between(0, %d, I), (atom_concat(n, I, T), findall(X, pr(X, T), L0), sort(L0, L), write(to(T, L)), nl)).
""" % (n - 1, n - 1)
        with tempfile.NamedTemporaryFile('w', suffix='.pl', delete=False) as f:
            f.write(prog); path = f.name
        res = subprocess.run([os.path.join(os.path.dirname(__file__), '..', 'horn'), path, '-g', 'halt'], capture_output=True, text=True, timeout=120)
        os.unlink(path)
        out = [l for l in res.stdout.split('\n') if l]
        # expected
        pairs = sorted((a, b) for a in range(n) for b in reach[a])
        def nm(i): return 'n%d' % i
        exp = []
        pairs_sorted = sorted(('n%d' % a, 'n%d' % b) for a, b in pairs)
        for P in ['pl', 'pr', 'pd']:
            for a, b in pairs_sorted: exp.append('%s-%s-%s' % (P, a, b))
            exp.append('%s-done' % P)
        sps = sorted(('n%d' % i, 'n%d' % j, d[i][j]) for i in range(n) for j in range(n) if d[i][j] < INF)
        # sp(X,Y,C): only paths with >=1 edge; diagonal handled by cycles: Floyd d[i][i] stays INF unless a cycle exists; compute cycle cost
        cyc = {}
        for i in range(n):
            best = INF
            for (a, b, w) in wedges:
                if a == i and d[b][i] < INF: best = min(best, w + d[b][i])
                if a == i and b == i: best = min(best, w)
            cyc[i] = best
        sps = []
        for i in range(n):
            for j in range(n):
                c = d[i][j] if i != j else cyc[i]
                if c < INF: sps.append(('n%d' % i, 'n%d' % j, c))
        sps.sort()
        for a, b, c in sps: exp.append('sp(%s,%s,%d)' % (a, b, c))
        exp.append('sp-done')
        # mutual: mut_a(X,Y) = odd... paths of length 1,3,5..; mut_b even>=2 ; compute by iteration
        a_set = set(edges); b_set = set()
        ch = True
        while ch:
            ch = False
            nb = {(x, y) for (x, z) in a_set for (z2, y) in edges if z == z2}
            na = set(edges) | {(x, y) for (x, z) in b_set for (z2, y) in edges if z == z2}
            if not nb <= b_set or not na <= a_set: b_set |= nb; a_set |= na; ch = True
        for a, b in sorted(('n%d' % a, 'n%d' % b) for a, b in a_set): exp.append('mut_a(%s,%s)' % (a, b))
        exp.append('mut-done')
        for i in range(n):
            exp.append('from(n%d,[%s])' % (i, ','.join('n%d' % j for j in sorted(reach[i]))) if False else None)
        exp = [e for e in exp if e is not None]
        # from/to lines: sorted atom order (n0..n9 ok as single digits)
        for i in range(n):
            exp.append('from(n%d,[%s])' % (i, ','.join('n%d' % j for j in sorted(reach[i]))))
        for j in range(n):
            exp.append('to(n%d,[%s])' % (j, ','.join('n%d' % i for i in range(n) if j in reach[i])))
        # normalise Horn output: write/1 prints a-b-c as a-b-c
        got = out
        if got != exp:
            bad += 1
            print('MISMATCH graph %d (seed %d): n=%d edges=%s' % (g, seed, n, sorted(edges)))
            for i, (x, y) in enumerate(itertools.zip_longest(got, exp)):
                if x != y:
                    print('  first diff at line %d: horn=%r expected=%r' % (i, x, y)); break
            print('  stderr:', res.stderr[:300])
    print('%d graphs, %d mismatches' % (N, bad))
    return bad

if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    sys.exit(1 if run(n, seed) else 0)
