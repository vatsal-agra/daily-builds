% Minimal cut demonstration: q/1 should commit to the FIRST matching
% p/1 fact and never backtrack into the others.
p(1).
p(2).
p(3).
q(X) :- p(X), !.
