% Classic family-tree knowledge base and derived relations.
parent(tom, bob).
parent(tom, liz).
parent(bob, ann).
parent(bob, pat).
parent(pat, jim).
parent(alice, bob).
parent(alice, liz).

male(tom).
male(bob).
male(jim).
female(liz).
female(ann).
female(pat).
female(alice).

father(F, C) :- parent(F, C), male(F).
mother(M, C) :- parent(M, C), female(M).

grandparent(GP, GC) :- parent(GP, P), parent(P, GC).
sibling(X, Y) :- parent(P, X), parent(P, Y), X \== Y.

ancestor(A, D) :- parent(A, D).
ancestor(A, D) :- parent(A, P), ancestor(P, D).
