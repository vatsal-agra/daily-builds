% N-queens, all solutions counted.
queens(N, Qs) :- numlist(1, N, Ns), permutation(Ns, Qs), safe(Qs).
safe([]).
safe([Q|Qs]) :- no_attack(Q, Qs, 1), safe(Qs).
no_attack(_, [], _).
no_attack(Q, [Q1|Qs], D) :- Q =\= Q1 + D, Q =\= Q1 - D, D1 is D+1, no_attack(Q, Qs, D1).

queens2(N, Qs) :- numlist(1, N, Ns), select_q(Ns, [], Qs).
select_q([], Qs, Qs).
select_q(Ns, Acc, Qs) :- select(Q, Ns, Rest), no_attack(Q, Acc, 1), select_q(Rest, [Q|Acc], Qs).

count(N, C) :- aggregate_all(count, queens2(N, _), C).
:- forall(between(4, 8, N), (count(N, C), format("~d queens: ~d solutions~n", [N, C]))).
:- queens(6, Qs), format("first 6-queens (perm): ~w~n", [Qs]).
