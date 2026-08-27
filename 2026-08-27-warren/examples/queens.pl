% The N-Queens problem, via permutation + a safety check (both
% permutation/2 and select/3 come from Warren's bootstrap library).
%
% queens(N, Qs) binds Qs to a list where Qs[i] is the column of the
% queen in row i, for some solution with N queens on an NxN board.

queens(N, Qs) :-
    numlist(1, N, Ns),
    permutation(Ns, Qs),
    safe(Qs).

safe([]).
safe([Q|Qs]) :- safe(Qs, Q, 1), safe(Qs).

safe([], _, _).
safe([Q|Qs], Q0, D0) :-
    Q0 =\= Q + D0,
    Q0 =\= Q - D0,
    D1 is D0 + 1,
    safe(Qs, Q0, D1).

count_solutions(N, Count) :-
    findall(Qs, queens(N, Qs), All),
    length(All, Count).
