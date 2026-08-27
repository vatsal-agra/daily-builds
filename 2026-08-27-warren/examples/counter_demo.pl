% Minimal assert/retract demonstration: a mutable counter predicate.
:- dynamic(counter/1).
counter(0).
incr :- retract(counter(X)), X1 is X + 1, assertz(counter(X1)).
incr3 :- incr, incr, incr.
