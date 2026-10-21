% Tabling: left recursion terminates, exponential recursion becomes linear,
% and mode-directed tabling computes shortest paths.
:- table path/2.
edge(a, b). edge(b, c). edge(c, a). edge(c, d). edge(d, e).
path(X, Y) :- path(X, Z), edge(Z, Y).      % left-recursive!
path(X, Y) :- edge(X, Y).
:- findall(Y, path(a, Y), L), sort(L, S), format("reachable from a: ~w~n", [S]).
:- ( path(e, _) -> writeln(yes) ; writeln('e reaches nothing') ).
:- findall(X-Y, path(X, Y), L), length(L, N), format("~d path facts~n", [N]).

:- table fib/2.
fib(0, 0).
fib(1, 1).
fib(N, F) :- N > 1, N1 is N-1, N2 is N-2, fib(N1, F1), fib(N2, F2), F is F1+F2.
:- fib(200, F), format("fib(200) = ~d~n", [F]).

% mutual recursion through two tabled predicates
:- table even/1, odd/1.
even(0).
even(N) :- N > 0, M is N-1, odd(M).
odd(N) :- N > 0, M is N-1, even(M).
:- ( even(100) -> writeln('100 is even') ; writeln('100 is odd') ).

% shortest path with min-mode tabling over a weighted graph with a cycle
:- table sp(_, _, min).
w(a, b, 7). w(a, c, 9). w(a, f, 14). w(b, c, 10). w(b, d, 15). w(c, d, 11). w(c, f, 2). w(d, e, 6). w(e, f, 9). w(f, e, 9). w(f, a, 1).
sp(X, Y, C) :- w(X, Y, C).
sp(X, Y, C) :- sp(X, Z, C1), w(Z, Y, C2), C is C1 + C2.
:- forall(member(T, [b, c, d, e, f]), ( sp(a, T, C), format("shortest a->~w = ~d~n", [T, C]) )).

% a left-recursive grammar via DCG + tabling
:- table expr//0.
expr --> expr, "+", term.
expr --> term.
term --> "n".
:- ( phrase(expr, "n+n+n") -> writeln('left-recursive DCG parses n+n+n') ; writeln(failed) ).
