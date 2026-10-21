app([], L, L).
app([H|T], L, [H|R]) :- app(T, L, R).
f(X) :- g(X), X > 1.
g(1). g(2).
h :- fail.
h :- true.
:- trace.
:- app([1], [2], L), f(Y), h.
:- notrace.
:- trace, \+ app([x], _, [y|_]), notrace.
