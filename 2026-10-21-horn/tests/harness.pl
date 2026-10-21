% Minimal test harness. Usage: include via consult, then call run_tests/0.
:- dynamic passed/1, failed/2.

t(Name, Goal) :- run_one(Name, Goal, succeed).
tf(Name, Goal) :- run_one(Name, Goal, fail).
te(Name, Goal, Pat) :- run_one(Name, Goal, error(Pat)).

run_one(Name, Goal0, Expect) :-
    copy_term(Goal0, Goal),
    catch(( call(Goal) -> R = succeeded ; R = failed ), E, R = raised(E)),
    (   check(Expect, R) -> assertz(passed(Name))
    ;   assertz(failed(Name, Expect-R)),
        format(user_error, "FAIL ~w: expected ~q got ~q~n", [Name, Expect, R])
    ).

check(succeed, succeeded).
check(fail, failed).
check(error(P), raised(E)) :- \+ \+ ( E = error(F, _), subsumes_term(P, F) ).
check(error(P), raised(E)) :- \+ \+ E = P.

summary :-
    aggregate_all(count, passed(_), P),
    aggregate_all(count, failed(_, _), F),
    format("~d passed, ~d failed~n", [P, F]),
    (   F =:= 0 -> true ; halt(1) ).
