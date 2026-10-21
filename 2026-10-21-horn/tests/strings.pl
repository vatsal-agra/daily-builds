:- consult('tests/harness.pl').
% default double_quotes=string
:- t(s_type, (string("abc"), \+ atom("abc"), \+ is_list("abc"), atomic("abc"))).
:- t(s_write, (format(atom(A), "~w", ["abc"]), A == abc)).
:- t(s_writeq, (format(atom(A), "~q", ["a\"b\\c\n"]), A == '"a\\"b\\\\c\\n"')).
:- t(s_print_in_list, (format(atom(A), "~q", [["x", y, 'Z']]), A == '["x",y,\'Z\']')).
:- t(s_concat, (string_concat("ab", "cd", S), S == "abcd")).
:- t(s_concat_atoms, (string_concat(ab, cd, S), string(S), S == "abcd")).
:- t(s_concat_split, (findall(A-B, string_concat(A, B, "ab"), L), L == [""-"ab", "a"-"b", "ab"-""])).
:- t(s_length, (string_length("héllo", N), N == 5)).
:- t(s_chars, (string_chars("abc", L), L == [a,b,c])), t(s_chars2, (string_chars(S, [h,i]), S == "hi")).
:- t(s_codes, (string_codes("ab", L), L == [97,98])).
:- t(s_to_atom, (string_to_atom("abc", A), A == abc)), t(s_to_atom2, (string_to_atom(S, abc), S == "abc")).
:- t(atom_string1, (atom_string(abc, S), S == "abc")), t(atom_string2, (atom_string(A, "xyz"), A == xyz)).
:- t(number_string1, (number_string(N, " 42 "), N == 42)), t(number_string2, (number_string(3.5, S), S == "3.5")).
:- t(s_sub, (sub_string("hello world", 6, 5, _, S), S == "world")).
:- t(s_sub_atom_still_atom, (sub_atom(hello, 0, 2, _, S), S == he)).
:- t(s_split, (split_string("a,b,,c", ",", "", P), P == ["a","b","","c"])).
:- t(s_split_ws, (split_string("  hello  ", "", " ", P), P == ["hello"])).
:- t(s_split_path, (split_string("/home//jan///nice/path", "/", "", L), L == ["", "home", "", "jan", "", "", "nice", "path"])).
:- t(s_upper, (string_upper("abc", U), U == "ABC")), t(s_lower, (string_lower("ABC", U), U == "abc")).
:- t(s_alc, (atomic_list_concat([a, "b", 1], R), R == ab1)).
:- t(s_alc_split, (atomic_list_concat(L, ',', "a,b"), L == [a, b])).
:- t(s_cmp, ("abc" @< "abd", "a" == "a", "a" \== a)).
:- t(s_order, (msort([f(x), "s", b, 1, a, Z, "r"], L), L = [V|Rest], var(V), Rest == [1, a, b, "r", "s", f(x)])).
:- t(s_term_string, (term_string(S, f(X, 'A b', "s")), string(S))), t(s_term_string2, (term_string("foo(1, Bar)", T), T = foo(1, _))).
:- t(s_format_s, (format(atom(A), "~s", ["abc"]), A == abc)).
:- t(s_format_a, (format(atom(A), "~a|~w", ["x", "y"]), A == 'x|y')).
:- t(s_with_output, (with_output_to(string(S), write(hi)), S == "hi")).
:- t(s_format_string, (format(string(S), "~d", [5]), S == "5")).
:- t(s_text_concat, (text_concat(abc, "def", R), R == "abcdef")), t(s_text_concat2, (text_concat(abc, def, R), R == abcdef)).
:- t(s_eval_char, (X is "a" + 0, X == 97)).
:- t(s_unify, ("abc" = "abc")), tf(s_unify2, "abc" = abc).
:- t(s_assert, (assertz(strfact("hello")), strfact(X), X == "hello")).
:- t(s_dcg_literal, phrase(("ab", "c"), `abc`)).
:- t(s_read, (term_to_atom(T, '"quoted"'), T == "quoted")).
:- t(s_text_to_string, (text_to_string(hello, S), S == "hello")).
:- t(s_char_code, (atom_codes(A, "xyz"), A == xyz)).
:- t(s_atom_length, (atom_length("abc", N), N == 3)).
:- t(s_flag_codes, (set_prolog_flag(double_quotes, codes), term_to_atom(T, '"ab"'), T == [97, 98], set_prolog_flag(double_quotes, string))).
:- t(s_backquote, (X = `ab`, X == [97, 98])).
:- t(s_unicode, (string_length("日本語", N), N == 3, string_concat("日", "本", S), S == "日本")).
:- t(s_sort, (sort(["b", "a", "b"], L), L == ["a", "b"])).
:- t(s_number_codes, (number_codes(X, "12"), X == 12)).
:- summary.
