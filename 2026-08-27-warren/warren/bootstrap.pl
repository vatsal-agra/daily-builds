% Warren's bootstrap library: ordinary Prolog, compiled by Warren's own
% WAM compiler at engine start-up (not hand-coded Python builtins) --
% exactly how real Prolog systems bootstrap their list/control library.

append([], L, L).
append([H|T], L, [H|R]) :- append(T, L, R).

append([], []).
append([L|Ls], R) :- append(Ls, R0), append(L, R0, R).

member(X, [X|_]).
member(X, [_|T]) :- member(X, T).

memberchk(X, L) :- member(X, L), !.

reverse(L, R) :- reverse_(L, [], R).
reverse_([], Acc, Acc).
reverse_([H|T], Acc, R) :- reverse_(T, [H|Acc], R).

last([X], X) :- !.
last([_|T], X) :- last(T, X).

nth0(0, [X|_], X) :- !.
nth0(N, [_|T], X) :- N > 0, N1 is N - 1, nth0(N1, T, X).

nth1(N, L, X) :- N0 is N - 1, nth0(N0, L, X).

select(X, [X|T], T).
select(X, [H|T], [H|R]) :- select(X, T, R).

selectchk(X, L, R) :- select(X, L, R), !.

delete([], _, []).
delete([X|T], X, R) :- !, delete(T, X, R).
delete([H|T], X, [H|R]) :- delete(T, X, R).

exclude(_, [], []).
exclude(P, [H|T], R) :- ( call(P, H) -> R = R1 ; R = [H|R1] ), exclude(P, T, R1).

include(_, [], []).
include(P, [H|T], R) :- ( call(P, H) -> R = [H|R1] ; R = R1 ), include(P, T, R1).

partition(_, [], [], []).
partition(P, [H|T], Inc, Exc) :-
    ( call(P, H) -> Inc = [H|Inc1], Exc = Exc1
    ; Inc = Inc1, Exc = [H|Exc1] ),
    partition(P, T, Inc1, Exc1).

permutation([], []).
permutation(L, [H|T]) :- select(H, L, R), permutation(R, T).

numlist(L, H, []) :- L > H, !.
numlist(L, H, [L|T]) :- L =< H, L1 is L + 1, numlist(L1, H, T).

sum_list(L, S) :- sum_list_(L, 0, S).
sum_list_([], Acc, Acc).
sum_list_([H|T], Acc, S) :- Acc1 is Acc + H, sum_list_(T, Acc1, S).
sumlist(L, S) :- sum_list(L, S).

max_list([X], X) :- !.
max_list([H|T], M) :- max_list(T, M0), (H >= M0 -> M = H ; M = M0).

min_list([X], X) :- !.
min_list([H|T], M) :- min_list(T, M0), (H =< M0 -> M = H ; M = M0).

max_member(M, L) :- msort(L, S), last(S, M).
min_member(M, [H|T]) :- msort([H|T], [M|_]).

list_to_set(L, S) :- lts_(L, [], S).
lts_([], _, []).
lts_([H|T], Seen, R) :-
    ( memberchk(H, Seen) -> R = R1 ; R = [H|R1] ),
    lts_(T, [H|Seen], R1).

flatten(L, F) :- flatten_(L, [], F0), !, F = F0.
flatten_(V, T, [V|T]) :- var(V), !.
flatten_([], T, T) :- !.
flatten_([H|R], T, F) :- !, flatten_(R, T, FR), flatten_(H, FR, F).
flatten_(X, T, [X|T]).

maplist(_, []).
maplist(P, [H|T]) :- call(P, H), maplist(P, T).

maplist(_, [], []).
maplist(P, [H|T], [H2|T2]) :- call(P, H, H2), maplist(P, T, T2).

maplist(_, [], [], []).
maplist(P, [H1|T1], [H2|T2], [H3|T3]) :- call(P, H1, H2, H3), maplist(P, T1, T2, T3).

maplist(_, [], [], [], []).
maplist(P, [H1|T1], [H2|T2], [H3|T3], [H4|T4]) :-
    call(P, H1, H2, H3, H4), maplist(P, T1, T2, T3, T4).

foldl(_, [], Acc, Acc).
foldl(P, [H|T], Acc0, Acc) :- call(P, H, Acc0, Acc1), foldl(P, T, Acc1, Acc).

foldl(_, [], [], Acc, Acc).
foldl(P, [H1|T1], [H2|T2], Acc0, Acc) :-
    call(P, H1, H2, Acc0, Acc1), foldl(P, T1, T2, Acc1, Acc).

not(G) :- \+ call(G).

ignore(G) :- ( call(G) -> true ; true ).

once(G) :- call(G), !.

apply(G, Args) :- G =.. L, append(L, Args, L2), G2 =.. L2, call(G2).

concat_atom([], '').
concat_atom([A], A) :- !.
concat_atom([A|T], R) :- concat_atom(T, R1), atom_concat(A, R1, R).

string_length(S, L) :- atom_length(S, L).
