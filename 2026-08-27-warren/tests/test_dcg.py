import os
from warren.engine import Engine
from warren.pretty import term_to_str


def _examples(name):
    return os.path.join(os.path.dirname(__file__), "..", "examples", name)


def test_simple_dcg_grammar():
    for backend in ("wam", "golden"):
        eng = Engine(backend=backend, load_bootstrap=False)
        eng.consult_string("""
            greeting --> [hello], subject.
            subject --> [world].
            subject --> [prolog].
        """)
        assert len(list(eng.query_text("greeting([hello,world],[])."))) == 1
        assert len(list(eng.query_text("greeting([hello,prolog],[])."))) == 1
        assert len(list(eng.query_text("greeting([hello,nope],[])."))) == 0


def test_dcg_with_braces_and_cut():
    for backend in ("wam", "golden"):
        eng = Engine(backend=backend, load_bootstrap=False)
        eng.consult_string("""
            digit(D) --> [D], { integer(D), D >= 0, D =< 9 }.
        """)
        assert len(list(eng.query_text("digit(5, [5], [])."))) == 1
        assert len(list(eng.query_text("digit(a, [a], [])."))) == 0


def test_expr_dcg_precedence_and_parens():
    for backend in ("wam", "golden"):
        eng = Engine(backend=backend)
        eng.consult_file(_examples("expr_dcg.pl"))
        cases = [
            ("[3,+,4,*,2]", "11"),           # * before +
            ("['(',3,+,4,')',*,2]", "14"),   # parens override precedence
            ("[10,/,2,-,1]", "4"),
            ("[2,*,3,*,4]", "24"),           # left-associative chain
        ]
        for toks, expected in cases:
            sols = list(eng.query_text(f"calc({toks},V)."))
            assert len(sols) == 1
            assert term_to_str(sols[0]["V"]) == expected, (backend, toks)


def test_expr_dcg_division_by_zero_fails_cleanly():
    for backend in ("wam", "golden"):
        eng = Engine(backend=backend)
        eng.consult_file(_examples("expr_dcg.pl"))
        # divby/2's guard (VB =\= 0) makes this fail, not raise/crash
        assert list(eng.query_text("calc([1,/,0],V).")) == []
