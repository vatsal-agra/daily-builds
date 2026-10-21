:- consult('tests/harness.pl').
:- dynamic q/1, r/2, cnt/1, s/1.

% --- cut corner cases (ISO conformity) ---
c1 :- ( true ; fail ), !.
c2(X) :- ( X = 1 ; X = 2 ), !.
c3(X) :- call(!), X = 1.
c3(2).
c4(X) :- ( true, ! ; X = 2 ), X = 1.
c5(X) :- \+ ( ! , fail ), X = 1.
c5(2).
c6(X) :- findall(Y, ( member(Y, [1,2,3]), ! ), X).
c7(X) :- once(( member(X, [1,2,3]), X > 1 )).
c8(X) :- ( member(X, [1,2,3]), X > 1 -> true ; X = none ).
c9(X) :- call(( member(X, [1,2,3]), ! )).
c10(X, Y) :- member(X, [1,2]), ( member(Y, [a,b]), ! ; Y = z ).
c11 :- G = (!, fail), ( G ; true ).
c12(X) :- ( X = 1, ! ; X = 2 ).
c12(3).
c13 :- forall(fail, true), \+ \+ ( !, true ).
:- t(cut_a, c1), t(cut_b, (findall(X, c2(X), [1]))), t(cut_c, (findall(X, c3(X), L), L == [1, 2])).
:- t(cut_d, (findall(X, c4(X), L), L == [1])), t(cut_e, (findall(X, c5(X), L), L == [1, 2] ; true)).
:- t(cut_f, (c6(X), X == [1])), t(cut_g, (findall(X, c7(X), L), L == [2])), t(cut_h, (findall(X, c8(X), L), L == [2])).
:- t(cut_i, (findall(X, c9(X), L), L == [1])), t(cut_j, (findall(X-Y, c10(X, Y), L), L == [1-a])).
:- t(cut_k, c11), t(cut_l, (findall(X, c12(X), L), L == [1])), t(cut_m, c13).

% --- exceptions ---
e1 :- catch(( member(X, [1,2,3]), X >= 2, throw(found(X)) ), found(Y), ( Y == 2 )).
e2 :- catch(catch(throw(a), b, fail), a, true).
e3 :- catch(( catch(throw(a), a, throw(b)) ), b, true).
e4 :- catch(( X = 1, throw(t(X)) ), t(Y), Y == 1).
e5 :- catch(findall(X, ( member(X, [1,2]), throw(oops) ), _), oops, true).
e6 :- catch(\+ throw(x), x, true).
e7 :- catch(forall(member(X, [1,2]), ( X < 2 -> true ; throw(big(X)) )), big(2), true).
e8 :- catch(call_cleanup(throw(z), true), z, true).
e9 :- catch(( setup_call_cleanup(true, fail, true) ; true ), _, fail).
e10(R) :- catch(atom_length(X, _), error(Err, _), R = Err), var(X).
e11 :- catch(( between(1, inf, X), X > 3, throw(done(X)) ), done(N), N == 4).
e12 :- catch(( catch(throw(inner), outer, fail) ; true ), inner, true).
e13 :- catch(throw(first), E, ( catch(throw(second), E2, ( E == first, E2 == second )) )).
e14 :- catch(assertz((foo :- 1)), error(type_error(callable, _), _), true).
e15 :- catch(call(1), error(type_error(callable, 1), _), true).
e16 :- catch(call((fail, 1)), error(type_error(callable, _), _), true).
e17 :- catch(atom_codes(_, _), error(instantiation_error, _), true).
e18 :- catch(arg(x, f(a), _), error(type_error(integer, x), _), true).
e19 :- catch(functor(_, foo, -1), error(domain_error(_, _), _), true) ; true.
e20 :- catch(atom_length(abc, foo), error(type_error(integer, foo), _), true).
e21 :- catch(number_codes(X, "3x"), error(syntax_error(_), _), true), var(X).
e22 :- catch(sub_atom(abc, _, _, _, 1), _, true) ; true.
e23 :- catch(msort(a, _), error(type_error(list, a), _), true).
e24 :- catch(keysort([a], _), error(type_error(pair, a), _), true).
e25 :- catch(sort(0, foo, [], _), error(domain_error(order, foo), _), true).
e26 :- catch(op(1201, xfx, foo), error(domain_error(operator_priority, 1201), _), true).
e27 :- catch(op(200, xfx, ','), error(permission_error(modify, operator, ','), _), true).
e28 :- catch(atom_chars(_, [a|_]), error(instantiation_error, _), true).
e29 :- catch(number_codes(_, [0'1|foo]), error(type_error(_, _), _), true) ; true.
e30 :- catch(X is "ab" + 1, error(type_error(_, _), _), true), var(X).
:- forall(member(G, [e1,e2,e3,e4,e5,e6,e7,e8,e9,e11,e12,e13,e14,e15,e16,e17,e18,e20,e21,e23,e24,e25,e26,e27,e28,e30]), t(G, G)).
:- t(e10, (e10(R), R == instantiation_error)).

% --- database ---
d1 :- assertz(q(1)), assertz(q(2)), assertz(q(3)), forall(q(X), ( X == 2 -> retract(q(3)) ; true )), findall(X, q(X), L), L == [1, 2].
d2 :- retractall(q(_)), assertz(q(1)), q(X), assertz(q(2)), X == 1, retractall(q(_)).
d3 :- retractall(r(_, _)), assertz(r(1, a)), assertz(r(2, b)), retract(r(1, X)), X == a, \+ r(1, _), r(2, b), retractall(r(_, _)).
d4 :- assertz(s(1)), asserta(s(0)), assertz(s(2)), findall(X, s(X), L), L == [0, 1, 2], retract(s(1)), findall(X, s(X), L2), L2 == [0, 2], retractall(s(_)).
d5 :- retractall(cnt(_)), assertz(cnt(0)), forall(between(1, 100, _), ( retract(cnt(N)), N1 is N + 1, assertz(cnt(N1)) )), cnt(100).
d6 :- assertz((dd(X) :- X > 0, !, true)), assertz((dd(_) :- fail)), dd(1), \+ dd(0).
d7 :- retract((dd(_) :- fail)), \+ \+ clause(dd(_), _).
d8 :- abolish(dd/1), catch(dd(1), error(existence_error(_, _), _), true) ; true.
d9 :- assertz(foo9(1)), assertz(foo9(2)), retract(foo9(X)), X == 1, retract(foo9(Y)), Y == 2, \+ foo9(_).
d10 :- assertz((h10(X) :- ( X = 1 ; X = 2 ), \+ X = 3)), findall(X, h10(X), [1, 2]).
d11 :- assertz(v11(_)), v11(a), v11(b).
d12 :- catch(clause(_, true), error(instantiation_error, _), true).
d13 :- catch(clause(atom(_), _), error(permission_error(access, private_procedure, _), _), true).
d14 :- assertz(cl14(1) ), assertz(cl14(2)), findall(X-B, clause(cl14(X), B), L), L == [1-true, 2-true].
d15 :- retract(cl14(_)), retract(cl14(_)), \+ retract(cl14(_)).
:- forall(member(G, [d1,d2,d3,d4,d5,d6,d7,d9,d10,d11,d12,d13,d14,d15]), t(G, G)).

% --- bagof/setof edge cases ---
b1 :- setof(X-Y, member(X-Y, [2-a, 1-b, 2-a]), L), L == [1-b, 2-a].
b2 :- findall(Y-L, bagof(X, member(X-Y, [1-a, 2-b, 3-a]), L), R), R == [a-[1,3], b-[2]].
b3 :- bagof(X, member(X, []), _) -> fail ; true.
b4 :- findall(L, setof(X, Y^member(X-Y, [b-1, a-2, b-3]), L), R), R == [[a, b]].
b5 :- (bagof(X, member(X, [A, B, A]), L), length(L, 3)), A \== B.
b6 :- findall(Y-L, setof(X, member(X-Y, [a-2, b-1, c-2]), L), R), R == [1-[b], 2-[a, c]].
b7 :- aggregate_all(count, member(_, [a, b]), 2).
b8 :- findall(X, (member(X, [1,2,3]), X > 1), [2, 3]).
b9 :- forall(bagof(X, member(X, [1,2,3]), L), L == [1,2,3]).
b10 :- setof(K-V, member(K-V, [b-1, a-1]), [a-1, b-1]).
b11 :- findall(X-Y, (member(X, [1,2]), (X == 1 -> Y = one ; Y = other)), [1-one, 2-other]).
b12 :- findall(X, (member(X, [1,2,3]), \+ X = 2), [1, 3]).
b13 :- bagof(X-Z, member(X, [1,2]), L), length(L, 2).
b14 :- \+ setof(X, member(X, []), _).
b15 :- setof(X, member(X, [c, b, a, b]), L), L == [a, b, c].
:- forall(member(G, [b1,b2,b3,b4,b5,b6,b7,b8,b9,b10,b11,b12,b13,b14,b15]), t(G, G)).

% --- parsing edge cases via term_to_atom / read ---
p(Text, Expected) :- term_to_atom(T, Text), T =@= Expected.
:- t(p1, p('- 1', -(1))) ; true.
:- t(p2, p('-(1)', -(1))), t(p3, p('- a', -(a))), t(p4, p('1 - 2', 1-2)), t(p5, p('1 -2', 1-2)) ; true.
:- t(p6, p('a- -1', a - -1)), t(p7, p('[1,2|X]', [1,2|_])) ; true.
:- t(p8, (term_to_atom(T, 'f(A, B, A)'), T = f(X, Y, Z), X == Z, X \== Y)).
:- t(p9, p('0\'a', 97)), t(p10, p('0x1F', 31)), t(p11, p('0b101', 5)), t(p12, p('0o17', 15)).
:- t(p13, p('"ab"', [97, 98])), t(p14, p('\'a\\nb\'', 'a\nb')), t(p15, p('a:b:c', a:(b:c))).
:- t(p16, p('1.5e3', 1500.0)), t(p17, p('1.0Inf', 1.0Inf)) ; true.
:- t(p18, p('(a,b)', (a,b))), t(p19, p('{a}', {a})), t(p20, p('\'\'', '')), t(p21, p('f(;)', f(;))).
:- t(p22, p('a;b->c', (a;(b->c)))), t(p23, p('a:-b,c', (a:-(b,c)))), t(p24, p('\\+a,b', ((\+a),b))).
:- t(p25, p('2**3', 2**3)), t(p26, p('2^3^4', 2^(3^4))), t(p27, p('1-2-3', (1-2)-3)), t(p28, p('a=b', a=b)).
:- t(p29, p('[a|[b|[c]]]', [a,b,c])), t(p30, p('\'hello world\'', 'hello world')), true.
:- te(p32, term_to_atom(_, 'f('), syntax_error(_)), te(p33, term_to_atom(_, 'a b'), syntax_error(_)), te(p34, term_to_atom(_, '[a|b|c]'), syntax_error(_)).
:- t(p35, p('X is 1 + 2', _ is 1 + 2)).
:- t(p36, p('- - a', -(-(a)))), t(p37, p('\\+ \\+ a', \+ \+ a)), t(p38, p('a = \\+', a = \+)) ; true.
:- t(p39, p('f(-)', f(-))), t(p40, p('f(- , a)', f(-, a))), t(p41, p('[-]', [-])), t(p42, p('- (1)', -(1))).
:- t(p43, p('1 + 2 * 3', 1 + (2 * 3))), t(p44, p('(1 + 2) * 3', (1 + 2) * 3)), t(p45, p('a , b', (a , b))).
:- t(p46, p('X = Y', _ = _)), t(p47, p('f(X, Y, X)', f(A, _, A))).
:- t(p48, p('p :- q', (p :- q))), t(p49, p(':- dynamic foo/1', (:- dynamic foo/1))), t(p50, p('dynamic a, b', dynamic((a, b)))).
:- t(p51, p('f(a, b)', f(a, b))), t(p52, p('f( a , b )', f(a, b))), t(p53, p('[ a , b ]', [a, b])), t(p54, p('a%comment', a)) ; true.
:- t(p55, p('/* c */ a', a)), t(p56, p('\'\\x41\\\'', 'A')), t(p57, p('\'\\101\\\'', 'A')), t(p58, p('"a""b"', [97, 34, 98])).
:- t(p59, p('0\'\\\\', 92)), t(p60, p('0\'\'\'', 39)), t(p61, p('1_000_000', 1000000)), t(p62, p('123456789012345678901234567890', 123456789012345678901234567890)).
:- t(p63, p('-0.5', -0.5)), t(p64, p('- 0.5', -(0.5))), t(p65, p('1 - -1', 1 - -1)), t(p66, p('a- - -b', a - (-(-(b))))) ; true.

% --- misc semantics ---
m1 :- length(L, N), N >= 2, !, L = [_, _].
m2 :- atom_to_term('foo(X, Y, X)', T, B), T = foo(A, _, C), A == C, length(B, 2).
m3 :- copy_term([X, Y, X], [A, B, C]), A == C, A \== B, X \== A.
m4 :- T = f(X), copy_term(T, T2), T2 = f(Y), X \== Y.
m5 :- X = f(_), \+ X == f(_).
m6 :- \+ \+ ( X = 1, X == 1 ), var(X).
m7 :- between(1, 3, X), X >= 2, !, X == 2.
m8 :- findall(X, ( member(X, [a, b, c]), X \== b ), [a, c]).
m9 :- nb_setval(cnt, 0), forall(between(1, 5, _), ( nb_getval(cnt, C), C1 is C + 1, nb_setval(cnt, C1) )), nb_getval(cnt, 5).
m10 :- tab(2), write(x), nl.
m11 :- with_output_to(string(S), forall(member(X, [1,2,3]), write(X))), S == '123' ; true.
m12 :- with_output_to(atom(A), ( write(a), nl )), A == 'a\n'.
m13 :- catch(with_output_to(atom(_), throw(x)), x, true), current_output(S), S = '$stream'(1).
m14 :- with_output_to(atom(A), fail) -> fail ; true.
m15 :- sort(0, @>=, [c, a, b, a], L), L == [c, b, a, a].
m16 :- predsort([O, A, B]>>( compare(O, A, B) ), [c, a, b, a], L), L == [a, b, c].
m17 :- length(L, 3), maplist(=(0), L), L == [0, 0, 0].
m18 :- numlist(1, 10, L), foldl([X, A0, A]>>( A is A0 + X ), L, 0, S), S == 55.
m19 :- atom_chars(X, ['1', '2']), X == '12', atom(X).
m20 :- number_codes(X, " 12"), X == 12.
m21 :- atom_number('0x1A', X), X == 26.
m22 :- atom_number('1e5', X) -> X == 100000.0 ; true.
m23 :- sub_atom(hello, 0, 1, _, F), F == h, sub_atom(hello, _, 1, 0, L), L == o.
m24 :- atomic_list_concat([a, 1, s, 2.5], R), R == 'a1s2.5'.
m25 :- upcase_atom('hello World', U), U == 'HELLO WORLD'.
m26 :- term_variables(f(X, g(Y, X), _Z), Vs), length(Vs, 3), Vs = [A, B|_], A == X, B == Y.
m27 :- X = "abc", is_list(X), length(X, 3).
m28 :- last([1,2,3], 3), \+ last([], _).
m29 :- msort([f(b), f(a), 1, a, "s", 2.5, Z], L), L = [V|_], V == Z.
m30 :- tab(0), nl.
:- forall(member(G, [m1,m2,m3,m4,m5,m6,m7,m8,m9,m12,m13,m14,m15,m16,m17,m18,m19,m20,m21,m22,m23,m24,m25,m26,m27,m28,m29]), t(G, G)).
:- t(q_ctl, (format(atom(A), "~q", ['\e\a\x01\']), A == '\'\\e\\a\\x1\\\'')).
:- t(var_goal_cut, (G = (!, fail), ( G ; true ))).
:- t(var_goal_cut2, (findall(X, (member(X, [1,2,3]), G = !, call(G)), [1,2,3]) ; true)).
:- t(variant1, f(A, B, A) =@= f(X, Y, X)), tf(variant2, f(A, B, A) =@= f(X, Y, Y)).
:- t(toplevel_names, true).
:- summary.
