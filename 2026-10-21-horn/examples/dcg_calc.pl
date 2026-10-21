% A tokenizer + recursive-descent calculator written as DCGs.
:- set_prolog_flag(double_quotes, codes).
calc(V) --> ws, expr(V), ws.
expr(V) --> term(T), expr_rest(T, V).
expr_rest(Acc, V) --> ws, "+", !, ws, term(T), { A1 is Acc+T }, expr_rest(A1, V).
expr_rest(Acc, V) --> ws, "-", !, ws, term(T), { A1 is Acc-T }, expr_rest(A1, V).
expr_rest(V, V) --> [].
term(V) --> factor(F), term_rest(F, V).
term_rest(Acc, V) --> ws, "*", !, ws, factor(F), { A1 is Acc*F }, term_rest(A1, V).
term_rest(Acc, V) --> ws, "/", !, ws, factor(F), { A1 is Acc/F }, term_rest(A1, V).
term_rest(V, V) --> [].
factor(V) --> "(", !, ws, expr(V), ws, ")".
factor(V) --> "-", !, factor(F), { V is -F }.
factor(V) --> number(V).
number(V) --> digits(Ds), ( ".", digits(Fs) -> { append(Ds, [0'.|Fs], Cs) } ; { Cs = Ds } ), { number_codes(V, Cs) }.
digits([D|T]) --> [D], { code_type(D, digit) }, ( digits(T) -> [] ; { T = [] } ).
ws --> [C], { code_type(C, space) }, !, ws.
ws --> [].

run(S) :- atom_codes(S, Cs), ( phrase(calc(V), Cs) -> format("~w = ~w~n", [S, V]) ; format("~w: parse error~n", [S]) ).
:- run('1 + 2 * 3'), run('(1+2)*3'), run('10 / 4'), run('2 * (3 + 4) - -1'), run('1.5 * 4'), run('2 +'), run('100000000000 * 100000000000').
