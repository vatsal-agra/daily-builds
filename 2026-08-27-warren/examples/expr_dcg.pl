% A small arithmetic-expression parser written as a Definite Clause
% Grammar (`-->`), compiled by Warren's own `-->` translation into
% ordinary difference-list-passing clauses and run on the same WAM as
% everything else. Standard precedence-climbing grammar:
%   expr   -> term (('+' | '-') term)*
%   term   -> factor (('*' | '/') factor)*
%   factor -> integer | '(' expr ')'
%
% Input is a list of tokens (atoms/numbers), already lexed -- e.g.
% tokens("3+4*2") = [3, +, 4, *, 2]. parse/2 returns an arithmetic
% expression tree; eval/2 evaluates one.

parse(Tokens, Tree) :- phrase(expr(Tree), Tokens).

expr(E) --> term(T), expr_rest(T, E).
expr_rest(Acc, E) --> [+], term(T), { E1 = plus(Acc, T) }, expr_rest(E1, E).
expr_rest(Acc, E) --> [-], term(T), { E1 = minus(Acc, T) }, expr_rest(E1, E).
expr_rest(Acc, Acc) --> [].

term(T) --> factor(F), term_rest(F, T).
term_rest(Acc, T) --> [*], factor(F), { T1 = times(Acc, F) }, term_rest(T1, T).
term_rest(Acc, T) --> ['/'], factor(F), { T1 = divby(Acc, F) }, term_rest(T1, T).
term_rest(Acc, Acc) --> [].

factor(num(N)) --> [N], { number(N) }.
factor(E) --> ['('], expr(E), [')'].

eval(num(N), N).
eval(plus(A, B), V) :- eval(A, VA), eval(B, VB), V is VA + VB.
eval(minus(A, B), V) :- eval(A, VA), eval(B, VB), V is VA - VB.
eval(times(A, B), V) :- eval(A, VA), eval(B, VB), V is VA * VB.
eval(divby(A, B), V) :- eval(A, VA), eval(B, VB), VB =\= 0, V is VA / VB.

% Convenience: parse and evaluate a token list in one call.
calc(Tokens, Value) :- parse(Tokens, Tree), eval(Tree, Value).

% `phrase/2` isn't a WAM built-in; it's ordinary Prolog over any DCG
% nonterminal, calling it with the standard two extra difference-list
% arguments -- exactly like a hand-written `Grammar(S0, S)` call.
phrase(G, List) :- phrase(G, List, []).
phrase(G, S0, S) :-
    G =.. L,
    append(L, [S0, S], L2),
    G2 =.. L2,
    call(G2).
