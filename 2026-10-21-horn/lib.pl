% Horn bundled library (loaded at startup, written in Prolog itself).

% ---- control ----
_ ^ G :- call(G).
apply(G, Extra) :- G =.. L0, append(L0, Extra, L1), G2 =.. L1, call(G2).
setup_call_cleanup(S, G, C) :-
    once(S),
    catch(G, E, ('$run_cleanup'(C), throw(E)))
    ->  '$run_cleanup'(C)
    ;   '$run_cleanup'(C), fail.
call_cleanup(G, C) :- setup_call_cleanup(true, G, C).
'$run_cleanup'(C) :- ignore(catch(C, _, true)).

% ---- database ----
retract(C) :- '$clause_head_body'(C, H, B), '$clause_ref'(H, B, Ref), '$erase'(Ref).

% ---- arithmetic helpers ----
between(L, H, X) :-
    integer(X), !,
    must_be(integer, L), X >= L,
    ( ( H == inf ; H == infinite ) -> true ; must_be(integer, H), X =< H ).
between(L, H, X) :-
    must_be(integer, L),
    ( ( H == inf ; H == infinite ) -> '$between_inf'(L, X)
    ; must_be(integer, H), L =< H, '$between'(L, H, X) ).
'$between'(L, L, X) :- !, X = L.
'$between'(L, _, L).
'$between'(L, H, X) :- L1 is L+1, '$between'(L1, H, X).
'$between_inf'(L, L).
'$between_inf'(L, X) :- L1 is L+1, '$between_inf'(L1, X).

must_be(Type, X) :- '$must_be'(Type, X).
'$must_be'(integer, X) :- !, ( integer(X) -> true ; var(X) -> throw(error(instantiation_error, _)) ; throw(error(type_error(integer, X), _)) ).
'$must_be'(positive_integer, X) :- !, ( integer(X) -> ( X > 0 -> true ; throw(error(type_error(positive_integer, X), _)) ) ; var(X) -> throw(error(instantiation_error, _)) ; throw(error(type_error(integer, X), _)) ).
'$must_be'(nonneg, X) :- !, ( integer(X) -> ( X >= 0 -> true ; throw(error(type_error(nonneg, X), _)) ) ; var(X) -> throw(error(instantiation_error, _)) ; throw(error(type_error(integer, X), _)) ).
'$must_be'(atom, X) :- !, ( atom(X) -> true ; var(X) -> throw(error(instantiation_error, _)) ; throw(error(type_error(atom, X), _)) ).
'$must_be'(callable, X) :- !, ( callable(X) -> true ; var(X) -> throw(error(instantiation_error, _)) ; throw(error(type_error(callable, X), _)) ).
'$must_be'(var, X) :- !, ( var(X) -> true ; throw(error(uninstantiation_error(X), _)) ).
'$must_be'(boolean, X) :- !, ( (X == true ; X == false) -> true ; var(X) -> throw(error(instantiation_error, _)) ; throw(error(type_error(bool, X), _)) ).
'$must_be'(list, X) :- !, ( is_list(X) -> true ; throw(error(type_error(list, X), _)) ).
'$must_be'(proper_list, X) :- !, '$must_be'(list, X).
'$must_be'(number, X) :- !, ( number(X) -> true ; var(X) -> throw(error(instantiation_error, _)) ; throw(error(type_error(number, X), _)) ).
'$must_be'(Type, X) :- ( call(Type, X) -> true ; throw(error(type_error(Type, X), _)) ).

assertion(G) :- ( \+ \+ catch(G, _, fail) -> true ; throw(error(assertion_failed(G), _)) ).

% ---- lists ----
length(L, N) :-
    '$skip_list'(L, Len, Tail),
    (   Tail == [] -> N = Len
    ;   var(Tail) ->
        (   integer(N) -> N >= Len, M is N-Len, '$mklist'(M, Tail)
        ;   var(N) -> '$length_enum'(Tail, Len, N)
        ;   throw(error(type_error(integer, N), _))
        )
    ;   throw(error(type_error(list, L), _))
    ).
'$mklist'(0, []) :- !.
'$mklist'(N, [_|T]) :- N1 is N-1, '$mklist'(N1, T).
'$length_enum'([], N, N).
'$length_enum'([_|T], N0, N) :- N1 is N0+1, '$length_enum'(T, N1, N).

append([], L, L).
append([H|T], L, [H|R]) :- append(T, L, R).
append(Ls, L) :- '$append_'(Ls, L).
'$append_'([], []).
'$append_'([L|Ls], As) :- append(L, Ws, As), '$append_'(Ls, Ws).
member(X, [H|T]) :- '$member'(T, X, H).
'$member'(_, X, X).
'$member'([H|T], X, _) :- '$member'(T, X, H).
memberchk(X, L) :- member(X, L), !.
reverse(L, R) :- '$reverse'(L, [], R).
'$reverse'([], A, A).
'$reverse'([H|T], A, R) :- '$reverse'(T, [H|A], R).
nth0(I, L, E) :- integer(I), !, I >= 0, '$nth_det'(I, L, E).
nth0(I, L, E) :- var(I), '$nth_gen'(L, E, 0, I).
nth1(I, L, E) :- integer(I), !, I >= 1, I0 is I-1, '$nth_det'(I0, L, E).
nth1(I, L, E) :- var(I), '$nth_gen'(L, E, 1, I).
'$nth_det'(0, [E|_], E) :- !.
'$nth_det'(I, [_|T], E) :- I > 0, I1 is I-1, '$nth_det'(I1, T, E).
'$nth_gen'([E|_], E, B, B).
'$nth_gen'([_|T], E, B0, B) :- B1 is B0+1, '$nth_gen'(T, E, B1, B).
nth0(I, L, E, R) :- integer(I), !, I >= 0, '$nth_del'(I, L, E, R).
nth0(I, L, E, R) :- var(I), '$nth_gen_del'(L, E, R, 0, I).
nth1(I, L, E, R) :- integer(I), !, I >= 1, I0 is I-1, '$nth_del'(I0, L, E, R).
nth1(I, L, E, R) :- var(I), '$nth_gen_del'(L, E, R, 1, I).
'$nth_del'(0, [E|T], E, T) :- !.
'$nth_del'(I, [H|T], E, [H|R]) :- I > 0, I1 is I-1, '$nth_del'(I1, T, E, R).
'$nth_gen_del'([E|T], E, T, B, B).
'$nth_gen_del'([H|T], E, [H|R], B0, B) :- B1 is B0+1, '$nth_gen_del'(T, E, R, B1, B).
last([X], X) :- !.
last([_|T], X) :- last(T, X).
sum_list(L, S) :- '$sum_list'(L, 0, S).
'$sum_list'([], S, S).
'$sum_list'([H|T], A, S) :- A1 is A+H, '$sum_list'(T, A1, S).
sumlist(L, S) :- sum_list(L, S).
max_list([H|T], M) :- foldl('$max_', T, H, M).
min_list([H|T], M) :- foldl('$min_', T, H, M).
'$max_'(X, Y, Z) :- Z is max(X, Y).
'$min_'(X, Y, Z) :- Z is min(X, Y).
max_member(M, L) :- '$max_member'(L, M).
'$max_member'([H|T], M) :- foldl('$max_std', T, H, M).
'$max_std'(X, Y, Z) :- ( X @> Y -> Z = X ; Z = Y ).
min_member(M, L) :- '$min_member'(L, M).
'$min_member'([H|T], M) :- foldl('$min_std', T, H, M).
'$min_std'(X, Y, Z) :- ( X @< Y -> Z = X ; Z = Y ).
numlist(L, H, R) :- L > H, !, R = [].
numlist(L, H, [L|T]) :- L1 is L+1, numlist(L1, H, T).
select(X, [X|T], T).
select(X, [H|T], [H|R]) :- select(X, T, R).
selectchk(X, L, R) :- select(X, L, R), !.
select(X, Xs, Y, Ys) :- '$select4'(Xs, X, Y, Ys).
'$select4'([X|T], X, Y, [Y|T]).
'$select4'([H|T], X, Y, [H|T2]) :- '$select4'(T, X, Y, T2).
exclude(_, [], []).
exclude(P, [H|T], R) :- ( call(P, H) -> R = R1 ; R = [H|R1] ), exclude(P, T, R1).
include(_, [], []).
include(P, [H|T], R) :- ( call(P, H) -> R = [H|R1] ; R = R1 ), include(P, T, R1).
partition(_, [], [], []).
partition(P, [H|T], I, E) :-
    (   call(P, H) -> I = [H|I1], E = E1 ; I = I1, E = [H|E1] ),
    partition(P, T, I1, E1).
partition(_, [], [], [], []).
partition(P, [H|T], L, E, G) :-
    call(P, O, H),
    '$partition6'(O, H, L, E, G, L1, E1, G1),
    partition(P, T, L1, E1, G1).
'$partition6'(<, H, [H|L], E, G, L, E, G).
'$partition6'(=, H, L, [H|E], G, L, E, G).
'$partition6'(>, H, L, E, [H|G], L, E, G).
subtract([], _, []).
subtract([H|T], L, R) :- ( memberchk(H, L) -> R = R1 ; R = [H|R1] ), subtract(T, L, R1).
intersection([], _, []).
intersection([H|T], L, R) :- ( memberchk(H, L) -> R = [H|R1] ; R = R1 ), intersection(T, L, R1).
union([], L, L).
union([H|T], L, R) :- ( memberchk(H, L) -> R = R1 ; R = [H|R1] ), union(T, L, R1).
delete([], _, []).
delete([E|T], X, R) :- ( E \= X -> R = [E|R1] ; R = R1 ), delete(T, X, R1).
list_to_set(L, S) :- '$lts'(L, [], S).
'$lts'([], _, []).
'$lts'([H|T], Seen, R) :- ( '$memberchk_eq'(H, Seen) -> R = R1 ; R = [H|R1] ), '$lts'(T, [H|Seen], R1).
'$memberchk_eq'(X, [Y|T]) :- ( X == Y -> true ; '$memberchk_eq'(X, T) ).
is_set(L) :- is_list(L), sort(L, S), length(L, N), length(S, N).
sumlist(L, A, S) :- foldl([X,Y,Z]>>(Z is X+Y), L, A, S).
nextto(X, Y, [X,Y|_]).
nextto(X, Y, [_|T]) :- nextto(X, Y, T).
permutation(Xs, Ys) :-
    '$skip_list'(Xs, Xlen, Xtail), '$skip_list'(Ys, Ylen, Ytail),
    (   Xtail == [], Ytail == [] -> Xlen == Ylen
    ;   var(Xtail), Ytail == [] -> length(Xs, Ylen)
    ;   Xtail == [], var(Ytail) -> length(Ys, Xlen)
    ;   var(Xtail), var(Ytail) -> length(Xs, Len), length(Ys, Len)
    ;   true
    ),
    '$perm'(Xs, Ys).
'$perm'([], []).
'$perm'(List, [First|Perm]) :- select(First, List, Rest), '$perm'(Rest, Perm).
flatten(List, Flat) :- '$flatten'(List, [], Flat0), !, Flat = Flat0.
'$flatten'(Var, Tl, [Var|Tl]) :- var(Var), !.
'$flatten'([], Tl, Tl) :- !.
'$flatten'([Hd|Tl], Tail, List) :- !, '$flatten'(Hd, FlatHeadTail, List), '$flatten'(Tl, Tail, FlatHeadTail).
'$flatten'(NonList, Tl, [NonList|Tl]).
subsumes_term(G, S) :- \+ \+ ( term_variables(S, V1), unify_with_occurs_check(G, S), term_variables(V1, V2), V1 == V2 ).
transpose([], []).
transpose([F|Fs], Ts) :- '$transpose'(F, [F|Fs], Ts).
'$transpose'([], _, []).
'$transpose'([_|Rs], Ms, [Ts|Tss]) :- '$lists_firsts_rests'(Ms, Ts, Ms1), '$transpose'(Rs, Ms1, Tss).
'$lists_firsts_rests'([], [], []).
'$lists_firsts_rests'([[F|Os]|Rest], [F|Fs], [Os|Oss]) :- '$lists_firsts_rests'(Rest, Fs, Oss).
pairs_keys_values([], [], []).
pairs_keys_values([K-V|T], [K|Ks], [V|Vs]) :- pairs_keys_values(T, Ks, Vs).
pairs_keys([], []).
pairs_keys([K-_|T], [K|Ks]) :- pairs_keys(T, Ks).
pairs_values([], []).
pairs_values([_-V|T], [V|Vs]) :- pairs_values(T, Vs).
list_to_ord_set(L, S) :- sort(L, S).
ord_union(A, B, C) :- append(A, B, L), sort(L, C).
ord_subtract(A, B, C) :- subtract(A, B, C).
ord_memberchk(X, L) :- memberchk(X, L).
ord_insert(S, E, S2) :- ord_union(S, [E], S2).
ord_add_element(S, E, S2) :- ord_union(S, [E], S2).
ord_del_element(S, E, S2) :- ord_subtract(S, [E], S2).
ord_intersection(A, B, C) :- intersection(A, B, C).
ord_subset(A, B) :- subtract(A, B, []).
concat_atom(L, R) :- atomic_list_concat(L, R).
concat_atom(L, S, R) :- atomic_list_concat(L, S, R).
string_code(I, S, C) :- atom_codes(S, Cs), nth1(I, Cs, C).

% ---- apply ----
maplist(_, []).
maplist(G, [A|As]) :- call(G, A), maplist(G, As).
maplist(_, [], []).
maplist(G, [A|As], [B|Bs]) :- call(G, A, B), maplist(G, As, Bs).
maplist(_, [], [], []).
maplist(G, [A|As], [B|Bs], [C|Cs]) :- call(G, A, B, C), maplist(G, As, Bs, Cs).
maplist(_, [], [], [], []).
maplist(G, [A|As], [B|Bs], [C|Cs], [D|Ds]) :- call(G, A, B, C, D), maplist(G, As, Bs, Cs, Ds).
maplist(_, [], [], [], [], []).
maplist(G, [A|As], [B|Bs], [C|Cs], [D|Ds], [E|Es]) :- call(G, A, B, C, D, E), maplist(G, As, Bs, Cs, Ds, Es).
foldl(G, L, A0, A) :- '$foldl1'(L, G, A0, A).
'$foldl1'([], _, A, A).
'$foldl1'([X|Xs], G, A0, A) :- call(G, X, A0, A1), '$foldl1'(Xs, G, A1, A).
foldl(G, L1, L2, A0, A) :- '$foldl2'(L1, L2, G, A0, A).
'$foldl2'([], [], _, A, A).
'$foldl2'([X|Xs], [Y|Ys], G, A0, A) :- call(G, X, Y, A0, A1), '$foldl2'(Xs, Ys, G, A1, A).
foldl(G, L1, L2, L3, A0, A) :- '$foldl3'(L1, L2, L3, G, A0, A).
'$foldl3'([], [], [], _, A, A).
'$foldl3'([X|Xs], [Y|Ys], [Z|Zs], G, A0, A) :- call(G, X, Y, Z, A0, A1), '$foldl3'(Xs, Ys, Zs, G, A1, A).

% yall-style lambdas:  [X1,...]>>Goal
'>>'(Ps, B) :- copy_term_nat(Ps>>B, Ps2>>B2), '$lambda_bind'(Ps2, [], R), '$lambda_call'(B2, R).
'>>'(Ps, B, A1) :- '$lambda'(Ps, B, [A1]).
'>>'(Ps, B, A1, A2) :- '$lambda'(Ps, B, [A1,A2]).
'>>'(Ps, B, A1, A2, A3) :- '$lambda'(Ps, B, [A1,A2,A3]).
'>>'(Ps, B, A1, A2, A3, A4) :- '$lambda'(Ps, B, [A1,A2,A3,A4]).
'>>'(Ps, B, A1, A2, A3, A4, A5) :- '$lambda'(Ps, B, [A1,A2,A3,A4,A5]).
'$lambda'(Ps0, B0, Args) :-
    ( nonvar(Ps0), Ps0 = Free/Ps1 -> copy_term_nat(Free/Ps1>>B0, Free/Ps>>B) ; copy_term_nat(Ps0>>B0, Ps>>B) ),
    '$lambda_bind'(Ps, Args, Rest),
    '$lambda_call'(B, Rest).
'$lambda_bind'(Ps, Args, Rest) :- ( Ps = [P|Pt], Args = [A|At] -> P = A, '$lambda_bind'(Pt, At, Rest) ; Rest = Args ).
'$lambda_call'(B, []) :- !, call(B).
'$lambda_call'(B, Rest) :- G =.. [call, B|Rest], call(G).
copy_term_nat(A, B) :- copy_term(A, B).

predsort(P, L, Sorted) :- length(L, N), '$predsort'(P, N, L, _, Sorted1), !, Sorted = Sorted1.
'$predsort'(P, 2, [X1,X2|L], L, R) :- !, call(P, Delta, X1, X2), '$sort2'(Delta, X1, X2, R).
'$predsort'(_, 1, [X|L], L, [X]) :- !.
'$predsort'(_, 0, L, L, []) :- !.
'$predsort'(P, N, L1, L3, R) :-
    N1 is N // 2, plus(N1, N2, N),
    '$predsort'(P, N1, L1, L2, R1), '$predsort'(P, N2, L2, L3, R2),
    '$predmerge'(P, R1, R2, R).
'$sort2'(<, X1, X2, [X1,X2]).
'$sort2'(=, X1, _, [X1]).
'$sort2'(>, X1, X2, [X2,X1]).
'$predmerge'(_, [], R, R) :- !.
'$predmerge'(_, R, [], R) :- !.
'$predmerge'(P, [H1|T1], [H2|T2], Result) :-
    call(P, Delta, H1, H2), !,
    '$predmerge_'(Delta, P, H1, H2, T1, T2, Result).
'$predmerge_'(<, P, H1, H2, T1, T2, [H1|R]) :- '$predmerge'(P, T1, [H2|T2], R).
'$predmerge_'(=, P, H1, _, T1, T2, [H1|R]) :- '$predmerge'(P, T1, T2, R).
'$predmerge_'(>, P, H1, H2, T1, T2, [H2|R]) :- '$predmerge'(P, [H1|T1], T2, R).

% ---- aggregate_all with witnesses ----
aggregate_all(max(X, W), G, max(MX, MW)) :- !,
    findall(X-W, G, [X0-W0|T]), '$agg_max'(T, X0, W0, MX, MW).
aggregate_all(min(X, W), G, min(MX, MW)) :- !,
    findall(X-W, G, [X0-W0|T]), '$agg_min'(T, X0, W0, MX, MW).
aggregate_all(S, G, R) :- '$aggregate_all'(S, G, R).
'$agg_max'([], X, W, X, W).
'$agg_max'([X1-W1|T], X0, W0, X, W) :- ( X1 > X0 -> '$agg_max'(T, X1, W1, X, W) ; '$agg_max'(T, X0, W0, X, W) ).
'$agg_min'([], X, W, X, W).
'$agg_min'([X1-W1|T], X0, W0, X, W) :- ( X1 < X0 -> '$agg_min'(T, X1, W1, X, W) ; '$agg_min'(T, X0, W0, X, W) ).

% ---- DCG ----
phrase(G, L) :- phrase(G, L, []).
phrase(G, L, R) :-
    ( var(G) -> throw(error(instantiation_error, _)) ; true ),
    '$dcg_body'(G, S0, S, Goal), S0 = L, S = R, call(Goal).

% ---- assoc (AVL trees) ----
empty_assoc(t).
get_assoc(K, t(K0,V0,_,L,R), V) :-
    compare(O, K, K0),
    (   O == (=) -> V = V0
    ;   O == (<) -> get_assoc(K, L, V)
    ;   get_assoc(K, R, V)
    ).
put_assoc(K, t, V, t(K,V,1,t,t)).
put_assoc(K, t(K0,V0,H,L,R), V, T) :-
    compare(O, K, K0),
    '$put_assoc'(O, K, V, K0, V0, H, L, R, T).
'$put_assoc'(=, K, V, _, _, H, L, R, t(K,V,H,L,R)).
'$put_assoc'(<, K, V, K0, V0, _, L, R, T) :- put_assoc(K, L, V, L1), '$avl_bal'(K0, V0, L1, R, T).
'$put_assoc'(>, K, V, K0, V0, _, L, R, T) :- put_assoc(K, R, V, R1), '$avl_bal'(K0, V0, L, R1, T).
'$avl_h'(t, 0).
'$avl_h'(t(_,_,H,_,_), H).
'$avl_mk'(K, V, L, R, t(K,V,H,L,R)) :- '$avl_h'(L, HL), '$avl_h'(R, HR), H is max(HL, HR)+1.
'$avl_bal'(K, V, L, R, T) :-
    '$avl_h'(L, HL), '$avl_h'(R, HR), D is HL-HR,
    (   D > 1 ->
        L = t(LK,LV,_,LL,LR), '$avl_h'(LL, HLL), '$avl_h'(LR, HLR),
        (   HLL >= HLR -> '$avl_mk'(K, V, LR, R, N1), '$avl_mk'(LK, LV, LL, N1, T)
        ;   LR = t(LRK,LRV,_,LRL,LRR),
            '$avl_mk'(LK, LV, LL, LRL, N1), '$avl_mk'(K, V, LRR, R, N2), '$avl_mk'(LRK, LRV, N1, N2, T)
        )
    ;   D < -1 ->
        R = t(RK,RV,_,RL,RR), '$avl_h'(RL, HRL), '$avl_h'(RR, HRR),
        (   HRR >= HRL -> '$avl_mk'(K, V, L, RL, N1), '$avl_mk'(RK, RV, N1, RR, T)
        ;   RL = t(RLK,RLV,_,RLL,RLR),
            '$avl_mk'(K, V, L, RLL, N1), '$avl_mk'(RK, RV, RLR, RR, N2), '$avl_mk'(RLK, RLV, N1, N2, T)
        )
    ;   '$avl_mk'(K, V, L, R, T)
    ).
list_to_assoc(L, A) :- '$l2a'(L, t, A).
'$l2a'([], A, A).
'$l2a'([K-V|T], A0, A) :- put_assoc(K, A0, V, A1), '$l2a'(T, A1, A).
assoc_to_list(t, []).
assoc_to_list(t(K,V,_,L,R), List) :- assoc_to_list(L, LL), assoc_to_list(R, RL), append(LL, [K-V|RL], List).
assoc_to_keys(A, Ks) :- assoc_to_list(A, L), pairs_keys(L, Ks).
assoc_to_values(A, Vs) :- assoc_to_list(A, L), pairs_values(L, Vs).
max_assoc(A, K, V) :- assoc_to_list(A, L), last(L, K-V).
min_assoc(A, K, V) :- assoc_to_list(A, [K-V|_]).
del_assoc(K, A0, V, A) :- assoc_to_list(A0, L0), select(K0-V, L0, L), K0 == K, !, list_to_assoc(L, A).
