:- consult('tests/harness.pl').
:- set_prolog_flag(double_quotes, codes).
:- table a/1, b/1.
a(X) :- b(X).
a(1).
b(X) :- a(X).
b(2).
:- t(scc1, (findall(X, a(X), L), msort(L, S), S == [1,2])).
:- t(scc2, (findall(X, b(X), L), msort(L, S), S == [1,2])).

:- table conn/2.
conn(X, Y) :- conn(X, Z), link(Z, Y).
conn(X, Y) :- link(X, Y).
:- dynamic link/2.
mkchain(N) :- retractall(link(_, _)), forall(between(1, N, I), (J is I + 1, assertz(link(I, J)))), assertz(link(N, 1)).
:- mkchain(60).
:- t(chain_all, (findall(Y, conn(1, Y), L), length(L, 61))).
:- t(chain_pairs, (aggregate_all(count, conn(_, _), C), C =:= 60 * 61)).
:- tf(chain_none, conn(100, _)).
:- t(chain_bound, conn(30, 5)).
:- t(chain_rev, (findall(X, conn(X, 7), L), length(L, 60))).

:- table cyc/1.
cyc(X) :- cyc(X).
cyc(a).
:- t(cyc_loop, (findall(X, cyc(X), [a]))).

:- table ok/1.
ok(X) :- member(X, [1,2,3]), X > 1.
:- t(ok1, (findall(X, ok(X), [2,3]))).
:- t(ok_cut, (ok(X), !, X == 2)).

:- table boom/1.
boom(X) :- X > 0, throw(oops(X)).
boom(0).
:- t(err1, catch(boom(1), oops(1), true)).
:- t(err2, (catch(boom(1), oops(1), true), boom(0))).

:- table cnt/1.
:- dynamic seen/1.
cnt(X) :- assertz(seen(x)), member(X, [1,2]).
:- t(memo1, (cnt(_), cnt(_), aggregate_all(count, seen(_), 1))).
:- t(abolish_tables, (abolish_all_tables, cnt(_), aggregate_all(count, seen(_), 2))).

:- table fibt/2.
fibt(0, 0).
fibt(1, 1).
fibt(N, F) :- N > 1, N1 is N-1, N2 is N-2, fibt(N1, F1), fibt(N2, F2), F is F1+F2.
:- t(fib300, (fibt(300, F), F == 222232244629420445529739893461909967206666939096499764990979600)).

:- table lcs/3.
lcs([], _, 0) :- !.
lcs(_, [], 0) :- !.
lcs([X|Xs], [X|Ys], N) :- !, lcs(Xs, Ys, M), N is M + 1.
lcs([X|Xs], [Y|Ys], N) :- lcs(Xs, [Y|Ys], A), lcs([X|Xs], Ys, B), N is max(A, B).
:- t(lcs1, (atom_codes(abcbdabxyzzy, A), atom_codes(bdcabazyxyz, B), lcs(A, B, N), N >= 5)).

:- table sp(_, _, min).
w(a,b,1). w(b,c,1). w(a,c,5). w(c,a,1).
sp(X, Y, C) :- w(X, Y, C).
sp(X, Y, C) :- sp(X, Z, C1), w(Z, Y, C2), C is C1 + C2.
:- t(sp1, (sp(a, c, C), C == 2)).
:- t(sp2, (findall(Y-C, sp(a, Y, C), L), msort(L, S), S == [a-3, b-1, c-2])).
:- table longest(_, max).
longest(a, 3). longest(a, 7). longest(a, 5).
:- t(maxmode, (longest(a, M), M == 7)).
:- table first_of(_, first).
first_of(k, 1). first_of(k, 2).
:- t(firstmode, (first_of(k, M), M == 1)).

:- table g//0.
g --> g, "a".
g --> "b".
:- t(dcg_left, phrase(g, "baaa")), tf(dcg_left2, phrase(g, "abaa")).
:- summary.
