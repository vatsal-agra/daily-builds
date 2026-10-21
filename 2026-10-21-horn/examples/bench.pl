% Classic micro-benchmarks. Run: horn examples/bench.pl -g main -t halt
app([], L, L).
app([H|T], L, [H|R]) :- app(T, L, R).
nrev([], []).
nrev([H|T], R) :- nrev(T, RT), app(RT, [H], R).
range(N, N, [N]) :- !.
range(I, N, [I|T]) :- I < N, I1 is I+1, range(I1, N, T).
bench_nrev(Reps) :- range(1, 30, L), between(1, Reps, _), nrev(L, _), fail.
bench_nrev(_).

tak(X, Y, Z, A) :- X =< Y, !, Z = A.
tak(X, Y, Z, A) :-
    X1 is X-1, Y1 is Y-1, Z1 is Z-1,
    tak(X1, Y, Z, A1), tak(Y1, Z, X, A2), tak(Z1, X, Y, A3),
    tak(A1, A2, A3, A).

fib(0, 0). fib(1, 1).
fib(N, F) :- N > 1, N1 is N-1, N2 is N-2, fib(N1, F1), fib(N2, F2), F is F1+F2.

loop(0) :- !.
loop(N) :- N1 is N-1, loop(N1).

time_it(Name, Goal) :-
    statistics(inferences, I0), statistics(cputime, T0),
    call(Goal),
    statistics(inferences, I1), statistics(cputime, T1),
    I is I1-I0, T is T1-T0,
    ( T > 0 -> LIPS is round(I/T) ; LIPS = inf ),
    format("~w~t~14|~D inferences  ~3f s  ~D LIPS~n", [Name, I, T, LIPS]).

main :-
    time_it(nrev30x20000, bench_nrev(20000)),
    time_it('tak(18,12,6)', tak(18,12,6,_)),
    time_it('fib(24)', fib(24,_)),
    time_it('loop 3M', loop(3000000)).
