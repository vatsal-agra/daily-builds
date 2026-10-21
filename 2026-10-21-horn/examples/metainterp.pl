% A vanilla meta-interpreter with depth counting and a proof tree builder,
% running on top of Horn (clause/2 over a user-defined dynamic program).
:- dynamic app/3, nrev/2, parent/2, anc/2.
app([], L, L).
app([H|T], L, [H|R]) :- app(T, L, R).
nrev([], []).
nrev([H|T], R) :- nrev(T, RT), app(RT, [H], R).
parent(tom, bob). parent(bob, ann). parent(ann, joe).
anc(X, Y) :- parent(X, Y).
anc(X, Y) :- parent(X, Z), anc(Z, Y).

solve(true, true) :- !.
solve((A, B), (PA, PB)) :- !, solve(A, PA), solve(B, PB).
solve(G, builtin(G)) :- predicate_property(G, built_in), !, call(G).
solve(G, node(G, P)) :- clause(G, B), solve(B, P).

size(true, 0) :- !.
size(builtin(_), 1) :- !.
size((A, B), N) :- !, size(A, X), size(B, Y), N is X + Y.
size(node(_, P), N) :- size(P, M), N is M + 1.

:- solve(nrev([1,2,3], R), P), size(P, N), format("nrev([1,2,3]) = ~w, proof size ~d~n", [R, N]).
:- findall(Y, solve(anc(tom, Y), _), L), format("descendants of tom: ~w~n", [L]).
:- solve(anc(tom, joe), P), P = node(_, (_, _)), writeln('tom is an ancestor of joe').
