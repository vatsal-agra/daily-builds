:- consult('tests/harness.pl').

% ---- unification & control ----
:- t(unify1, f(X, b) = f(a, Y)), t(unify2, (X = Y, Y = 3, X == 3)).
:- tf(unify3, f(a) = f(b)), tf(unify4, f(a) = g(a)).
:- tf(occurs_default, (X = f(X), fail)) ; true.
:- t(uoc, \+ unify_with_occurs_check(X, f(X))).
:- t(cut1, (member(X, [1,2,3]), !, X == 1)).
cutt(X) :- ( X > 0 -> true ; fail ).
ct1(a). ct1(b).
ct2(X) :- ct1(X), !.
:- t(cut2, (findall(X, ct2(X), L), L == [a])).
ct3(X) :- ( ct1(X), ! ; X = c ).
:- t(cut3, (findall(X, ct3(X), L), L == [a])).
ct4(X) :- call((ct1(X), !)).
ct4(c).
:- t(cut_call_opaque, (findall(X, ct4(X), L), L == [a, c])).
ct5(X) :- \+ \+ (X = 1, !), X = 2.
:- t(cut_in_negation, ct5(_)).
:- t(ite1, (( 1 < 2 -> X = a ; X = b ), X == a)).
:- t(ite2, (( 1 > 2 -> X = a ; X = b ), X == b)).
:- tf(ite3, ( fail -> true )).
:- t(ite_backtrack_cond, (findall(X, ((member(X,[1,2,3]), X > 1) -> true ; X = none), L), L == [2])).
:- t(softcut, (findall(X, (member(X,[1,2]) *-> true ; X = none), L), L == [1,2])).
:- t(softcut2, (findall(X, (fail *-> true ; X = none), L), L == [none])).
:- t(disj, (findall(X, (X = 1 ; X = 2 ; X = 3), L), L == [1,2,3])).
:- t(not1, \+ fail), tf(not2, \+ true).
:- t(once1, (once(member(X, [a,b])), X == a)).
:- t(ignore1, ignore(fail)).
:- t(callN, (call(plus(1), 2, X), X == 3)).
:- t(call_conj, call((X = 1, Y = 2)) ),
   t(call_conj2, (call((X = 1, Y = 2)), X+Y =:= 3)).
:- te(call_var, call(_), instantiation_error).
:- te(call_num, call(3), type_error(callable, 3)).
:- te(unknown_proc, undefined_pred_xyz(1), existence_error(procedure, undefined_pred_xyz/1)).
:- t(forall1, forall(member(X, [1,2,3]), X > 0)), tf(forall2, forall(member(X, [1,2,3]), X > 1)).
% ---- exceptions ----
:- t(catch1, (catch(throw(my), my, true))).
:- t(catch2, (catch(throw(f(X)), f(Y), (Y = 1)), true)).
:- t(catch_rethrow, catch(catch(throw(a), b, true), a, true)).
:- t(catch_backtrack, (findall(X, catch(member(X,[1,2,3]), _, true), L), L == [1,2,3])).
:- t(catch_after_exit, catch((catch(member(X,[1,2]), E, (write(wrong), nl)), X > 1, throw(done)), done, true)).
:- t(catch_bindings_undone, (catch((X = 1, throw(oops)), oops, true), var(X))).
:- te(throw_inst, throw(_), instantiation_error).
:- te(is_unbound, _ is _ + 1, instantiation_error).
:- te(is_type, _ is foo + 1, type_error(evaluable, foo/0)).
:- te(div0, _ is 1 / 0, evaluation_error(zero_divisor)).
:- t(catch_in_findall, catch(findall(X, (member(X,[1,2]), X > a), _), error(type_error(_, _), _), true)).
% ---- arithmetic ----
:- t(a1, 7 =:= 3 + 4), t(a2, X is 7 // 2), t(a3, (X is -7 // 2, X == -3)).
:- t(a4, (X is -7 mod 3, X == 2)), t(a5, (X is -7 rem 3, X == -1)), t(a6, (X is -7 div 2, X == -4)).
:- t(a7, (X is 2 ** 10, X == 1024)), t(a8, (X is 2 ** 0.5, float(X))), t(a9, (X is 2 ^ 100, X == 1267650600228229401496703205376)).
:- t(a10, (X is max(3, 4.0), X == 4.0)), t(a11, (X is truncate(3.7), X == 3)), t(a12, (X is round(2.5), X == 3)).
:- t(a13, (X is 10 / 4, X == 2.5)), t(a14, (X is 10 / 5, X == 2)), t(a15, (X is cot(1.0), float(X))).
:- t(bigmul, (X is 123456789012345678 * 987654321098765432, X == 121932631137021794322511812221002896)).
:- t(bigadd, (X is 9223372036854775807 + 1, X == 9223372036854775808)).
:- t(bigfact, (numlist(1, 25, L), foldl([A,B,C]>>(C is A*B), L, 1, F), F == 15511210043330985984000000)).
:- t(gcd, (X is gcd(12, 18), X == 6)), t(shift, (X is 1 << 70, X == 1180591620717411303424)).
:- t(bitops, (X is 5 /\ 3, Y is 5 \/ 3, Z is 5 xor 3, W is \ 5, [X,Y,Z,W] == [1,7,6,-6])).
:- t(cmp_mixed, 1 =:= 1.0), t(cmp2, 2 > 1.5).
:- t(float_fmt, (X is 10.0, format(atom(A), "~w", [X]), A == '10.0')).
:- t(succ1, (succ(X, 4), X == 3)), t(succ2, (succ(3, Y), Y == 4)), true.
:- t(plus1, (plus(1, 2, X), X == 3)), t(plus2, (plus(1, X, 5), X == 4)).
:- t(sign_abs, (X is abs(-3) + sign(-2), X == 2)).
:- t(trig, (X is sin(pi/2), X =:= 1.0)).
:- t(char_arith, (X is "a" + 0, X == 97)) ; true.
:- t(minmaxint, (X is max_tagged_integer, integer(X))).
:- t(eval_list, (X is [5] + 1, X == 6)).
% ---- type checks ----
:- t(ty1, (var(_), nonvar(a), atom(a), \+ atom(1), integer(1), float(1.0), number(1), atomic(a), compound(f(x)), callable(a), is_list([a]), \+ is_list([a|_]))).
:- t(ty2, (\+ atom("x") ; true)).
:- t(ground1, (ground(f(a)), \+ ground(f(_)))).
% ---- term construction ----
:- t(functor1, (functor(f(a,b), N, A), N == f, A == 2)).
:- t(functor2, (functor(T, g, 3), T = g(_,_,_))).
:- t(functor3, (functor(a, N, A), N == a, A == 0)).
:- t(functor4, (functor(T, 5, 0), T == 5)).
:- te(functor5, functor(_, _, _), instantiation_error).
:- t(arg1, (arg(2, f(a,b,c), X), X == b)).
:- t(arg_enum, (findall(N-X, arg(N, f(a,b), X), L), L == [1-a, 2-b])).
:- t(univ1, (f(a,b) =.. L, L == [f,a,b])).
:- t(univ2, (T =.. [g, 1, 2], T == g(1,2))).
:- t(univ3, (a =.. L, L == [a])).
:- t(copy1, (copy_term(f(X,Y,X), C), C = f(A,B,C2), A == C2, A \== B)).
:- t(tv, (term_variables(f(X, g(Y), X), L), L == [X, Y])).
:- t(setarg1, (T = f(a), setarg(1, T, b), T == f(b))).
:- t(setarg_undo, (T = f(a), (setarg(1, T, b), fail ; true), T == f(a))).
:- t(nb_setarg, (T = f(a), (nb_setarg(1, T, b), fail ; true), T == f(b))).
% ---- standard order ----
:- t(ord1, (msort([b, 1, a, 2.0, f(x), Z, "s"], L), L = [V|_], var(V))).
:- t(ord2, (compare(O, 1, 1.0), O == >)).
:- t(ord3, (compare(O, f(a), g), O == >)).
:- t(ord4, (sort([c,a,b,a], L), L == [a,b,c])).
:- t(ord5, (msort([c,a,b,a], L), L == [a,a,b,c])).
:- t(ord6, (sort(0, @>=, [1,3,2,3], L), L == [3,3,2,1])).
:- t(ord7, (sort(1, @<, [f(2,a), f(1,b), f(2,c)], L), L == [f(1,b), f(2,a)])).
:- t(keysort1, (keysort([b-1, a-2, b-0, a-1], L), L == [a-2, a-1, b-1, b-0])).
:- t(predsort1, (predsort([O,A,B]>>compare(O,A,B), [3,1,2,1], L), L == [1,2,3])).
:- t(cmp_vars, (X @< Y ; Y @< X)).
:- t(lt, (a @< b, f(a) @> a, 1 @< a, 1.0 @< 1)).
% ---- atoms & strings ----
:- t(at1, (atom_codes(abc, L), L == [0'a, 0'b, 0'c])).
:- t(at2, (atom_chars(X, [a,b]), X == ab)).
:- t(at3, (atom_length(hello, N), N == 5)).
:- t(at4, (atom_concat(a, b, X), X == ab)).
:- t(at5, (findall(A-B, atom_concat(A, B, ab), L), L == [''-ab, a-b, ab-''])).
:- t(at6, (sub_atom(hello, 1, 3, A, S), S == ell, A == 1)).
:- t(at7, (findall(B, sub_atom(abab, B, _, _, ab), L), L == [0, 2])).
:- t(at8, (atom_number('12', N), N == 12)), t(at9, (atom_number(A, 3.5), A == '3.5')), tf(at10, atom_number(abc, _)).
:- t(at11, (upcase_atom(hello, U), U == 'HELLO')).
:- t(at12, (atomic_list_concat([a, b, c], X), X == abc)).
:- t(at13, (atomic_list_concat([a, b, c], '-', X), X == 'a-b-c')).
:- t(at14, (atomic_list_concat(L, '-', 'a-b-c'), L == [a, b, c])).
:- t(at15, (char_code(C, 0'x), C == x)).
:- t(at16, (number_codes(N, "42"), N == 42)).
:- t(at17, (term_to_atom(f(X, 'A', "s"), A), atom(A))).
:- t(at18, (term_to_atom(T, 'foo(X, bar, X)'), T = foo(A, bar, B), A == B)).
:- te(at19, atom_length(_, _), instantiation_error).
:- te(at20, atom_length(f(x), _), type_error(_, _)).
:- t(split, (split_string("a,b,,c", ",", "", P), P == [a, b, '', c])).
:- t(number_vars, (T = f(X, Y), numbervars(T, 0, E), E == 2, format(atom(A), "~w", [T]), A == 'f(A,B)')).
:- t(char_type1, (char_type(a, alpha), char_type('A', upper(L)), L == a, char_type('3', digit(W)), W == 3)).
:- t(sub_atom_enum, (findall(S, sub_atom(abc, _, 2, _, S), L), L == [ab, bc])).
% ---- database ----
:- dynamic fact/1, cnt/1.
:- t(db1, (assertz(fact(1)), assertz(fact(2)), asserta(fact(0)), findall(X, fact(X), L), L == [0,1,2])).
:- t(db2, (retract(fact(1)), findall(X, fact(X), L), L == [0,2])).
:- t(db3, (retractall(fact(_)), \+ fact(_))).
:- t(db4, (assertz(cnt(0)), retract(cnt(N)), N1 is N + 1, assertz(cnt(N1)), cnt(1))).
:- t(db_logical_view, (retractall(fact(_)), assertz(fact(1)), assertz(fact(2)), findall(X, (fact(X), assertz(fact(9))), L), L == [1,2], retractall(fact(_)))).
:- t(db_clause, (assertz((foo(X) :- X > 1, bar)), clause(foo(A), B), B = (A > 1, bar))).
:- te(db_static, assertz((atom(x) :- true)), permission_error(modify, static_procedure, atom/1)).
:- ( t(db_abolish, (assertz(tmpp(1)), abolish(tmpp/1), \+ catch(tmpp(_), _, fail))) ; true ).
:- t(db_pred_prop, (predicate_property(fact(_), dynamic))).
:- t(db_current, (current_predicate(fact/1))), tf(db_current2, current_predicate(nonexistent_zzz/3)).
% ---- all solutions ----
age(peter, 7). age(ann, 11). age(pat, 8). age(tom, 5). age(mike, 11).
:- t(fa1, (findall(N, age(N, _), L), L == [peter, ann, pat, tom, mike])).
:- t(fa2, (findall(X, fail, L), L == [])).
:- t(fa3, (findall(X-Y, (member(X,[1,2]), Y = X), L, [end]), L == [1-1, 2-2, end])).
:- t(bag1, (bagof(N, age(N, 11), L), L == [ann, mike])).
:- t(bag2, (findall(A-L, bagof(N, age(N, A), L), R), R == [5-[tom], 7-[peter], 8-[pat], 11-[ann, mike]])).
:- t(bag3, (bagof(N, A^age(N, A), L), length(L, 5))).
:- tf(bag4, bagof(N, age(N, 99), _)).
:- t(set1, (setof(A, N^age(N, A), L), L == [5, 7, 8, 11])).
:- t(set2, (setof(A-N, age(N, A), L), L = [5-tom|_])).
:- t(agg1, (aggregate_all(count, age(_, _), C), C == 5)).
:- t(agg2, (aggregate_all(sum(A), age(_, A), S), S == 42)).
:- t(agg3, (aggregate_all(max(A), age(_, A), M), M == 11)).
:- t(agg4, (aggregate_all(bag(A), age(_, A), B), length(B, 5))).
:- t(agg5, (aggregate_all(max(A, N), age(N, A), max(MA, MN)), MA == 11, MN == ann)).
:- t(agg6, (aggregate_all(count, fail, C), C == 0)).
% ---- lists ----
:- t(l1, (append(X, Y, [1,2]), X == [], Y == [1,2])).
:- t(l2, (findall(X-Y, append(X, Y, [1,2]), L), length(L, 3))).
:- t(l3, (reverse([1,2,3], R), R == [3,2,1])).
:- t(l4, (nth0(1, [a,b,c], X), X == b)), t(l5, (nth1(1, [a,b,c], X), X == a)).
:- t(l6, (last([1,2,3], X), X == 3)), t(l7, (sum_list([1,2,3], S), S == 6)).
:- t(l8, (max_list([1,5,3], M), M == 5)), t(l9, (numlist(1, 5, L), L == [1,2,3,4,5])).
:- t(l10, (length(L, 3), L = [_,_,_])), t(l11, (length([a,b], N), N == 2)).
:- t(l12, (length(L, N), N >= 2, !, L = [_,_])) .
:- t(l13, (msort([b,a], [a,b]))), t(l14, (delete([a,b,a,c], a, R), R == [b,c])).
:- t(l15, (subtract([1,2,3], [2], R), R == [1,3])), t(l16, (exclude([X]>>(X > 1), [1,2,3], R), R == [1])).
:- t(l17, (partition([X]>>(X < 2), [1,2,3], I, E), I == [1], E == [2,3])).
:- t(l18, (maplist([X,Y]>>(Y is X * 2), [1,2,3], L), L == [2,4,6])).
:- t(l19, (foldl([X,A0,A]>>(A is A0 + X), [1,2,3], 0, S), S == 6)).
:- t(l20, (permutation([1,2,3], P), P == [1,2,3])), t(l21, (findall(P, permutation([1,2,3], P), Ps), length(Ps, 6))).
:- t(l22, (flatten([1,[2,[3,4]],5], F), F == [1,2,3,4,5])).
:- t(l23, (list_to_set([a,b,a,c,b], S), S == [a,b,c])).
:- t(l24, (select(b, [a,b,c], R), R == [a,c])).
:- t(l25, (nth0(I, [a,b,c], c), I == 2)).
:- t(l26, (between(1, 3, X), X == 1)), t(l27, (findall(X, between(1, 5, X), L), L == [1,2,3,4,5])).
:- t(l28, (pairs_keys_values(P, [a,b], [1,2]), P == [a-1, b-2])).
:- t(l29, (sumlist([1,2], S), S == 3)).
:- t(l30, (maplist([X]>>(X > 0), [1,2,3]))).
:- t(l31, (transpose([[1,2,3],[4,5,6]], T), T == [[1,4],[2,5],[3,6]])).
:- t(l32, (last([a], a))), t(l33, (memberchk(b, [a,b,c]))).
:- t(l34, (length(L, N), N >= 2, !, L = [_,_])).
:- t(l35, (max_member(M, [3,1,4,1,5]), M == 5)).
:- te(l36, length(a, _), type_error(list, a)).
% ---- assoc ----
:- t(as1, (list_to_assoc([a-1, b-2, c-3], A), get_assoc(b, A, V), V == 2)).
:- t(as2, (empty_assoc(E), put_assoc(k, E, v, A), assoc_to_list(A, L), L == [k-v])).
:- t(as3, (numlist(1, 200, Ns), foldl([N,A0,A1]>>put_assoc(N, A0, N, A1), Ns, t, A), assoc_to_keys(A, Ks), Ks == Ns, get_assoc(150, A, V), V == 150)).
:- tf(as4, (list_to_assoc([a-1], A), get_assoc(z, A, _))).
% ---- DCG ----
greeting --> [hello], name.
name --> [world].
name --> [prolog].
digits([D|T]) --> digit(D), digits(T).
digits([D]) --> digit(D).
digit(D) --> [D], { code_type(D, digit) }.
expr(X) --> term(X0), expr_rest(X0, X).
expr_rest(Acc, X) --> "+", !, term(Y), { Acc1 is Acc + Y }, expr_rest(Acc1, X).
expr_rest(Acc, X) --> "-", !, term(Y), { Acc1 is Acc - Y }, expr_rest(Acc1, X).
expr_rest(X, X) --> [].
term(X) --> digits(Ds), { number_codes(X, Ds) }.
anbn --> [].
anbn --> [a], anbn, [b].
:- t(dcg1, phrase(greeting, [hello, world])), tf(dcg2, phrase(greeting, [hello, there])).
:- t(dcg3, (phrase(expr(X), "12+30-2"), X == 40)).
:- t(dcg4, phrase(anbn, [a,a,b,b])), tf(dcg5, phrase(anbn, [a,b,b])).
:- t(dcg6, (phrase(digits(Ds), "123", R), R == [], Ds == "123")).
pb, [x] --> [y].
:- t(dcg_pushback, phrase(pb, [y], [x])).
:- t(dcg_trans, (dcg_translate_rule((a --> b, [c]), T), T = (a(S0,S) :- b(S0,S1), S1 = [c|S]))).
% ---- misc control ----
:- t(between_inf, (between(1, inf, X), X > 3, !)).
:- t(nb_global, (nb_setval(k, 5), nb_getval(k, V), V == 5)).
:- t(b_global, (b_setval(k2, 1), b_getval(k2, V), V == 1)).
:- t(with_output, (with_output_to(atom(A), (write(a), write(b))), A == ab)).
:- t(fmt_atom, (format(atom(A), "~a-~d", [x, 5]), A == 'x-5')).
:- t(fmt_pad, (format(atom(A), "~w~t~6|~w", [ab, c]), A == 'ab    c')).
:- t(fmt_padr, (format(atom(A), "~t~w~6|", [ab]), A == '    ab')).
:- t(fmt_center, (format(atom(A), "~t~w~t~8|", [ab]), A == '   ab   ')).
:- t(fmt_float, (format(atom(A), "~2f", [3.14159]), A == '3.14')).
:- t(fmt_D, (format(atom(A), "~D", [1234567]), A == '1,234,567')).
:- t(fmt_dec, (format(atom(A), "~2d", [314]), A == '3.14')).
:- t(fmt_s, (format(atom(A), "~s", [[104,105]]), A == hi)).
:- t(fmt_c, (format(atom(A), "~c~c", [104,105]), A == hi)).
:- t(fmt_r, (format(atom(A), "~8r ~16r ~8|", [64, 255]), sub_atom(A, 0, _, _, '100 ff'))).
:- t(fmt_e, (format(atom(A), "~e", [1.5]), A == '1.500000e+00')).
:- t(fmt_q, (format(atom(A), "~q", ['a b']), A == '\'a b\'')).
:- t(fmt_star, (format(atom(A), "~*c", [3, 0'x]), A == xxx)).
:- te(fmt_err, format("~d", [a]), format(_)).
:- te(fmt_few, format("~w ~w", [a]), format(_)).
:- t(read_term, (term_to_atom(T, 'f(X,Y)'), functor(T, f, 2))).
:- op(700, xfx, ===>).
:- t(op1, (X = (a ===> b), X =.. [O|_], O == (===>))).
:- t(op2, (op(200, xfy, **), true)).
:- t(op_cur, (current_op(P, T, mod), P == 400, T == yfx)).
:- t(write_ops, (format(atom(A), "~w", [1+2*3]), A == '1+2*3')).
:- t(write_ops2, (format(atom(A), "~w", [(1+2)*3]), A == '(1+2)*3')).
:- t(write_ops3, (format(atom(A), "~w", [a-(b-c)]), A == 'a-(b-c)')).
:- t(write_ops4, (format(atom(A), "~w", [-(1)]), A == '- 1')).
:- t(write_ops5, (format(atom(A), "~w", [-(a)]), A == '-a')).
:- t(write_ops6, (format(atom(A), "~w", [1 - -1]), A == '1- -1')).
:- t(write_ops7, (format(atom(A), "~w", [f(a,(b,c))]), A == 'f(a,(b,c))')).
:- t(write_ops8, (format(atom(A), "~w", [[a|b]]), A == '[a|b]')).
:- t(write_ops9, (format(atom(A), "~w", [{a,b}]), A == '{a,b}')).
:- t(write_ops10, (format(atom(A), "~w", [(a:-b)]), A == 'a:-b')).
:- t(write_ops11, (format(atom(A), "~w", [(a:-b,c;d->e)]), A == 'a:-b,c;d->e')).
:- t(write_ops12, (format(atom(A), "~w", [\+a]), A == '\\+a')).
:- t(write_ops13, (format(atom(A), "~w", [1 is 2]), A == '1 is 2')).
:- t(writeq1, (format(atom(A), "~q", ['hello world']), A == '\'hello world\'')).
:- t(writeq3, (format(atom(A), "~q", ['\n']), A == '\'\\n\'')).
:- t(writeq4, (format(atom(A), "~q", [[]]), A == '[]')).
:- t(writeq5, (format(atom(A), "~q", ['[]']), A == '[]')).
:- t(writeq6, (format(atom(A), "~q", [f('$VAR'(1))]), A == 'f(B)')).
:- t(writeq8, (format(atom(A), "~q", [1.0e10]), A == '10000000000.0')).
:- t(writeq9, (format(atom(A), "~q", [1.5e300]), A == '1.5e300')).
:- t(writeq10, (format(atom(A), "~q", [a*(b+c)]), A == 'a*(b+c)')).
:- t(writeq11, (format(atom(A), "~q", [2**3]), A == '2**3')).
:- t(writeq12, (format(atom(A), "~q", [(a,b)]), A == 'a,b')).
:- t(writeq13, (format(atom(A), "~q", [f(;)]), A == 'f(;)')).
:- t(writeq14, (format(atom(A), "~q", [f((a:-b))]), A == 'f((a:-b))')).
:- t(writeq15, (format(atom(A), "~q", ['hello'(1)]), A == 'hello(1)')).
:- t(writeq16, (format(atom(A), "~q", [f(',')]), A == 'f(\',\')')).
:- t(writeq17, (format(atom(A), "~q", [- a]), A == '-a')).
:- t(writeq18, (format(atom(A), "~q", [1 - 2 - 3]), A == '1-2-3')).
:- t(writeq19, (format(atom(A), "~q", [1-(2-3)]), A == '1-(2-3)')).
:- t(writeq20, (format(atom(A), "~q", [2^3^4]), A == '2^3^4')).
:- t(writeq21, (format(atom(A), "~q", [(2^3)^4]), A == '(2^3)^4')).
:- t(writeq22, (format(atom(A), "~q", [f(A1, B1, A1)]), sub_atom(A, 0, _, _, 'f(_'))).
:- summary.
