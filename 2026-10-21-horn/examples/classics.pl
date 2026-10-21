% Assorted classics: hanoi, primes, collatz, ackermann, quicksort, gcd, string ops.
hanoi(0, _, _, _) :- !.
hanoi(N, A, B, C) :- N1 is N-1, hanoi(N1, A, C, B), assertz(move(A, B)), hanoi(N1, C, B, A).
:- dynamic move/2.
:- hanoi(10, left, right, mid), aggregate_all(count, move(_, _), N), format("hanoi(10): ~d moves~n", [N]).

primes(N, Ps) :- numlist(2, N, L), sieve(L, Ps).
sieve([], []).
sieve([P|Xs], [P|Ps]) :- exclude([X]>>(0 =:= X mod P), Xs, Ys), sieve(Ys, Ps).
:- primes(60, Ps), format("primes below 60: ~w~n", [Ps]).

collatz(1, 0) :- !.
collatz(N, S) :- ( N mod 2 =:= 0 -> M is N // 2 ; M is 3*N+1 ), collatz(M, S0), S is S0+1.
:- collatz(27, S), format("collatz(27) takes ~d steps~n", [S]).

ack(0, N, R) :- !, R is N+1.
ack(M, 0, R) :- !, M1 is M-1, ack(M1, 1, R).
ack(M, N, R) :- M1 is M-1, N1 is N-1, ack(M, N1, R1), ack(M1, R1, R).
:- ack(2, 3, R), format("ack(2,3) = ~d~n", [R]).

qsort([], []).
qsort([P|Xs], S) :- partition([X]>>(X < P), Xs, L, G), qsort(L, SL), qsort(G, SG), append(SL, [P|SG], S).
:- qsort([3,1,4,1,5,9,2,6,5,3,5], S), format("sorted: ~w~n", [S]).

fact(0, 1) :- !.
fact(N, F) :- N1 is N-1, fact(N1, F1), F is N*F1.
:- fact(30, F), format("30! = ~d~n", [F]).

:- X is 2**200, format("2^200 = ~d~n", [X]).
:- atom_codes(hello, Cs), reverse(Cs, Rs), atom_codes(A, Rs), format("reversed: ~a~n", [A]).
:- format("~a~t~15|~a~t~10+~a~n", [name, qty, price]),
   forall(member(N-Q-P, [apple-3-1.5, banana-12-0.25]), format("~a~t~15|~d~t~10+~2f~n", [N, Q, P])).
