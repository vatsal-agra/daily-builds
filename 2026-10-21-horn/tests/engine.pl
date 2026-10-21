:- consult('tests/harness.pl').
% Determinism: a call must leave no choicepoint when indexing / cuts make it deterministic.
det(G) :- '$cp_count'(A), call(G), '$cp_count'(B), A == B.
nondet(G) :- '$cp_count'(A), call(G), '$cp_count'(B), B > A.

len([], 0).
len([_|T], N) :- len(T, M), N is M + 1.
app([], L, L).
app([H|T], L, [H|R]) :- app(T, L, R).
col(red). col(green). col(blue).
f(0, zero). f(1, one). f(2, two). f(3, three). f(4, four). f(5, five). f(6, six). f(7, seven). f(8, eight). f(9, nine).
g(a, 1). g(b, 2). g(X, 3) :- X == c.
cutdet(X) :- ( X > 0 -> true ; fail ).
cutdet2(X) :- X > 0, !.
cutdet2(_).

:- t(det_len, det(len([a,b,c], _))).
:- t(det_app_bound, det(app([1,2], [3], _))).
:- t(det_member_last, det((member(X, [a,b,c]), X == c))).
:- t(nondet_member_first, nondet(member(_, [a,b,c]))).
:- t(det_index_atom, det(col(blue))).
:- t(nondet_unbound, nondet(col(_))).
:- t(det_index_int, det(f(7, _))).
:- t(det_f_big, det(f(9, nine))).
:- t(nondet_g_b, nondet(g(b, _))).
:- t(det_ite, det(cutdet(3))).
:- t(det_cut, det(cutdet2(3))).
:- t(det_between_last, det((between(1, 3, X), X == 3))).
:- t(det_atom_concat, det(atom_concat(a, b, _))).
:- t(det_msort, det(msort([b,a], _))).
:- t(det_findall, det(findall(X, col(X), _))).
:- t(det_forall, det(forall(col(X), atom(X)))).
:- t(det_negation, det(\+ col(purple))).
:- t(det_once, det(once(col(_)))).
:- t(det_catch, det(catch(len([a], _), _, true))).
:- t(nondet_catch_inner, nondet(catch(col(_), _, true))).
:- t(det_call, det(call(len, [a], _))).
:- t(det_lambda, det(maplist([X]>>(X > 0), [1,2,3]))).
:- t(det_length_bound, det(length([a,b], _))).
:- t(det_nth, det(nth1(2, [a,b,c], _))).
:- t(det_append3, det(append([a], [b], _))).
:- t(det_last, det(last([a,b,c], _))).
:- t(det_sum, det(sum_list([1,2,3], _))).
:- t(det_append_last_solution, det((append(X, _, [1,2]), X == [1,2]))).
:- t(det_third_arg_index, det(app(_, _, []))).
:- t(det_dcg, det(phrase(("ab", "c"), `abc`))).

% Resource behaviour
count(N, N) :- !.
count(I, N) :- I1 is I + 1, count(I1, N).
:- t(deep_det_loop, (count(0, 2000000), '$trail_size'(T), T < 1000)).
:- t(nontail_1m, (numlist(1, 1000000, L), len(L, N), N == 1000000)).
:- t(long_list_ops, (numlist(1, 500000, L), msort(L, S), length(S, N), N == 500000, last(S, 500000), sum_list(L, Sum), Sum == 125000250000)).
:- t(copy_long_list, (numlist(1, 300000, L), copy_term(L, C), length(C, 300000))).
:- t(compare_long, (numlist(1, 300000, L), numlist(1, 300000, L2), L == L2, \+ L @< L2)).
:- t(unify_long, (length(L, 300000), length(L2, 300000), L = L2)).
:- t(findall_big, (findall(X, between(1, 400000, X), L), length(L, 400000))).
:- t(atom_big, (length(L, 200000), maplist(=(0'a), L), atom_codes(A, L), atom_length(A, 200000))).
:- t(deep_term, (foldl([_, T0, f(T0)]>>true, [1,2,3], x, T), T == f(f(f(x))))).
:- t(deep_term2, (numlist(1, 100000, L), foldl([_, T0, f(T0)]>>true, L, x, T), copy_term(T, T2), T2 = f(_))).
thrower(0) :- throw(done(100000)).
thrower(N) :- N1 is N - 1, thrower(N1), true.
:- t(exception_deep, (catch(thrower(100000), done(X), true), X == 100000)).
:- t(long_body, (numlist(1, 400, L), maplist([X, G]>>(G = (X > 0)), L, Gs), foldl([G, A0, (A0, G)]>>true, Gs, true, Body), assertz((longbody :- Body)), longbody)).

% Big fact tables: first-argument hashing, lazy retract
:- dynamic fact/2, queue/1.
:- t(assert_200k, (forall(between(1, 200000, I), assertz(fact(I, I))), aggregate_all(count, fact(_, _), 200000))).
:- t(lookup_200k, (forall(between(1, 200000, I), (fact(I, V), V == I)))).
:- t(lookup_det, det(fact(150000, _))).
:- t(retract_by_key, (forall(between(1, 50000, I), retract(fact(I, _))), \+ fact(1, _), fact(50001, _))).
:- t(queue_fifo, (forall(between(1, 50000, I), assertz(queue(I))), forall(between(1, 50000, I), (retract(queue(X)), X == I)), \+ queue(_))).
:- t(retractall_big, (retractall(fact(_, _)), \+ fact(_, _))).
:- t(update_counter, (assertz(counter(0)), forall(between(1, 100000, _), (retract(counter(N)), N1 is N + 1, assertz(counter(N1)))), counter(100000))).
:- dynamic counter/1.

% Logical update view with the index in place
:- dynamic lv/1.
:- t(luv_assert_while_iterating, (forall(between(1, 20, I), assertz(lv(I))), findall(X, (lv(X), assertz(lv(100))), L), length(L, 20))).
:- t(luv_retract_while_iterating, (retractall(lv(_)), forall(between(1, 20, I), assertz(lv(I))), findall(X, (lv(X), retract(lv(20))), L), L == [1])).

% Memory guard: runaway recursion raises a catchable resource error instead of exhausting the machine
:- t(occurs_default_allows_cycle, (X = f(X), X = f(Y), Y == X)).
:- t(occurs_flag, (set_prolog_flag(occurs_check, true), \+ X = f(X), \+ f(X, X) = f(Y, g(Y)), set_prolog_flag(occurs_check, false), X = f(X))).
:- t(occurs_builtin, (\+ unify_with_occurs_check(X, f(X)), unify_with_occurs_check(X, f(Y)))).
:- t(globals_backtrack, (b_setval(v, 1), (b_setval(v, 2), fail ; true), b_getval(v, 1))).
:- t(globals_nb, (nb_setval(w, 1), (nb_setval(w, 2), fail ; true), nb_getval(w, 2))).
:- t(setarg_backtrack, (T = f(0), (setarg(1, T, 1), fail ; true), T = f(0))).


:- summary.
