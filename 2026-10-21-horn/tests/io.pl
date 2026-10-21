:- consult('tests/harness.pl').
tmp('/tmp/horn_io_test.txt').
tmp2('/tmp/horn_io_test2.pl').

:- t(file_roundtrip, (tmp(F), open(F, write, S), format(S, "foo(~q).~nbar(X, Y, X).~n", ['A b']), write_canonical(S, baz([1,2])), write(S, '.'), nl(S), close(S),
                      open(F, read, R), read(R, T1), read_term(R, T2, [variable_names(Vs)]), read(R, T3), read(R, T4), close(R),
                      T1 == foo('A b'), T2 = bar(A, B, C), A == C, A \== B, length(Vs, 2), T3 == baz([1,2]), T4 == end_of_file)).
:- t(char_io, (tmp(F), open(F, write, S), write(S, 'ab\ncd'), close(S), open(F, read, R),
               peek_char(R, P), get_char(R, C1), get_char(R, C2), get_char(R, C3), get_code(R, C4), \+ at_end_of_stream(R),
               get_char(R, C5), at_end_of_stream(R), get_char(R, C6), close(R),
               P == a, C1 == a, C2 == b, C3 == '\n', C4 == 0'c, C5 == d, C6 == end_of_file)).
:- t(append_mode, (tmp(F), open(F, write, S), write(S, a), close(S), open(F, append, S2), write(S2, b), close(S2),
                   open(F, read, R), get_char(R, X), get_char(R, Y), close(R), X == a, Y == b)).
:- t(see_tell, (tmp(F), tell(F), write(hello), write('.'), nl, told, see(F), read(X), seen, X == hello)).
:- te(missing_file, open('/nonexistent/dir/file', read, _), existence_error(_, _)).
:- te(closed_stream, (tmp(F), open(F, read, S), close(S), read(S, _)), existence_error(stream, _)).
:- te(wrong_mode, (tmp(F), open(F, read, S), write(S, x)), permission_error(output, stream, _)).
:- t(current_output_is_stream, (current_output(S), S = '$stream'(_))).
:- t(with_output_nested, (with_output_to(atom(A), (write(a), with_output_to(atom(B), write(b)), write(B), write(c))), A == abc)).
:- t(format_stream_alias, (format(user_output, "", []), nl(user_output))).
:- t(print_to_err, (format(user_error, "", []))).
:- t(consult_file, (tmp2(F), open(F, write, S),
      format(S, ":- dynamic seen/1.~nfact(1).~nfact(2).~nrule(X) :- fact(X), X > 1.~n:- assertz(seen(loaded)).~n", []),
      format(S, "term_expansion(gen(N), [gen_fact(N), gen_fact(M)]) :- M is N + 1.~ngen(10).~n", []),
      close(S), consult(F), findall(X, rule(X), L), L == [2], seen(loaded), findall(X, gen_fact(X), G), G == [10, 11])).
:- t(initialization_after_load, (tmp2(F), open(F, write, S),
      format(S, ":- initialization(assertz(init_ran(yes))).~n:- \\+ catch(init_ran(_), _, fail).~n", []), close(S), consult(F), init_ran(yes))).
:- dynamic init_ran/1.
:- op(700, xfx, ~~>), op(200, fy, my_not).
:- t(op_effect, (format(atom(A), "~q", [a ~~> b]), A == 'a~~>b')).
:- t(op_prefix, (format(atom(A), "~q", [my_not my_not x]), A == 'my_not my_not x')).
:- t(op_remove, (op(0, xfx, ~~>), catch(term_to_atom(_, 'a ~~> b'), error(syntax_error(_), _), true))).
:- t(flag_unknown, (set_prolog_flag(unknown, fail), \+ nonexistent_pred_zzz, set_prolog_flag(unknown, error))).
:- t(flag_dq, (set_prolog_flag(double_quotes, atom), term_to_atom(T, '"abc"'), T == abc, set_prolog_flag(double_quotes, string))).
:- t(read_from_atom, (read_term_from_atom('foo(X, bar)', T, []), T = foo(_, bar))).
:- t(sformat_like, (format(atom(A), "~a~t~8|~a", [ab, cd]), A == 'ab      cd')).
:- t(column_after_text, (format(atom(A), "xy~t~w~6|", [z]), A == 'xy   z')).
:- t(col_plus, (format(atom(A), "~w~t~6+~w~t~6+~w", [a, b, c]), A == 'a     b     c')).
:- t(fill_char, (format(atom(A), "~`-t~10|", []), A == '----------')).
:- t(fmt_newline_col, (format(atom(A), "ab~ncd~t~6|e", []), A == 'ab\ncd    e')).
:- t(listing_out, (assertz(lst(1, "s", 'A')), with_output_to(atom(A), listing(lst/3)), sub_atom(A, _, _, _, 'lst(1, "s", \'A\').'))).
:- dynamic lst/3.
:- t(portray_vars, (with_output_to(atom(A), portray_clause(foo(X, Y, X))), A == 'foo(A, _, A).\n')).
:- t(print_quoted, (with_output_to(atom(A), print('a b')), A == '\'a b\'')).
:- t(write_term_opts, (with_output_to(atom(A), write_term('a b'+[1], [quoted(true)])), A == '\'a b\'+[1]')).
:- t(write_canonical_list, (with_output_to(atom(A), write_canonical([a, 'B c'])), A == '[a,\'B c\']')).
:- t(halt_in_findall_not, true).
:- t(stat_runtime, (statistics(runtime, [T|_]), integer(T))).
:- t(stat_inferences, (statistics(inferences, I), integer(I), I > 0)).
:- t(get_time_float, (get_time(T), float(T))).
:- t(getenv_path, (getenv('PATH', P), atom(P))).
:- t(nb_current_missing, catch(nb_getval(no_such_key_zzz, _), error(existence_error(_, _), _), true)).
:- t(garbage_noop, garbage_collect).
:- summary.
