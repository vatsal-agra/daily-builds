"""Full test suite for Coil. Run: python3 -m unittest -v (from project root)
or simply: python3 tests/test_coil.py
"""

import io
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from coil import compile_source_text, run_source, stringify  # noqa: E402
from coil.cli import _looks_like_expression  # noqa: E402
from coil.disasm import disassemble  # noqa: E402
from coil.errors import (CompileError, LexError, ParseError,  # noqa: E402
                         RuntimeCoilError)
from coil.lexer import T, tokenize  # noqa: E402
from coil.vm import VM  # noqa: E402


def run(src, gc_stress=False):
    """Run source, return captured stdout as a string."""
    out = io.StringIO()
    run_source(src, output=out, gc_stress=gc_stress)
    return out.getvalue()


def run_vm(src, gc_stress=False):
    out = io.StringIO()
    vm = run_source(src, output=out, gc_stress=gc_stress)
    return vm, out.getvalue()


def lines(src, **kw):
    return run(src, **kw).strip().split("\n")


class TestLexer(unittest.TestCase):
    def test_token_kinds(self):
        toks = tokenize('let x = 3.5 + "hi";')
        kinds = [t.type for t in toks]
        self.assertEqual(kinds[0], T.LET)
        self.assertEqual(toks[-1].type, T.EOF)
        self.assertIn(T.STRING, kinds)
        self.assertIn(T.NUMBER, kinds)

    def test_two_char_ops_have_full_value(self):
        toks = tokenize("a == b != c >= d <= e")
        vals = [t.value for t in toks if t.type in
                (T.EQ_EQ, T.BANG_EQ, T.GE, T.LE)]
        self.assertEqual(vals, ["==", "!=", ">=", "<="])

    def test_string_escapes(self):
        self.assertEqual(run(r'print "a\nb\t\"c\"";'), 'a\nb\t"c"\n')

    def test_nested_block_comments(self):
        self.assertEqual(run("/* a /* nested */ still */ print 1;"), "1\n")

    def test_unterminated_string(self):
        with self.assertRaises(LexError):
            tokenize('"oops')

    def test_bad_char(self):
        with self.assertRaises(LexError):
            tokenize("@")


class TestParserErrors(unittest.TestCase):
    def test_missing_semicolon(self):
        with self.assertRaises(ParseError):
            compile_source_text("print 1")

    def test_error_position(self):
        try:
            compile_source_text("let x = ;")
        except ParseError as e:
            self.assertEqual(e.line, 1)
            self.assertEqual(e.col, 9)
        else:
            self.fail("expected ParseError")

    def test_invalid_assignment_target(self):
        with self.assertRaises(ParseError):
            compile_source_text("1 + 2 = 3;")

    def test_duplicate_param(self):
        with self.assertRaises(ParseError):
            compile_source_text("fn f(a, a) { return a; }")


class TestArithmetic(unittest.TestCase):
    def test_precedence(self):
        self.assertEqual(run("print 1 + 2 * 3 - 4 / 2;"), "5\n")

    def test_unary_and_grouping(self):
        self.assertEqual(run("print -(3 + 2) * 2;"), "-10\n")

    def test_modulo(self):
        self.assertEqual(run("print 7 % 3;"), "1\n")

    def test_string_concat(self):
        self.assertEqual(run('print "foo" + "bar";'), "foobar\n")

    def test_int_formatting(self):
        self.assertEqual(run("print 10 / 2;"), "5\n")      # whole -> no .0
        self.assertEqual(run("print 7 / 2;"), "3.5\n")

    def test_div_by_zero(self):
        with self.assertRaises(RuntimeCoilError):
            run("print 1 / 0;")

    def test_mod_by_zero(self):
        with self.assertRaises(RuntimeCoilError):
            run("print 1 % 0;")


class TestComparisonLogic(unittest.TestCase):
    def test_comparisons(self):
        self.assertEqual(lines("print 2 < 3; print 3 <= 3; print 3 > 4;"),
                         ["true", "true", "false"])

    def test_string_comparison(self):
        self.assertEqual(run('print "a" < "b";'), "true\n")

    def test_equality_number_vs_bool(self):
        self.assertEqual(run("print 1 == 1.0;"), "true\n")
        self.assertEqual(run("print 1 == true;"), "false\n")

    def test_short_circuit_and(self):
        self.assertEqual(run("print false and (1/0);"), "false\n")  # rhs skipped

    def test_short_circuit_or(self):
        self.assertEqual(run('print true or (1/0);'), "true\n")

    def test_logical_values(self):
        self.assertEqual(run('print false or "fallback";'), "fallback\n")
        self.assertEqual(run('print nil and "x";'), "nil\n")

    def test_truthiness(self):
        # only nil and false are falsey
        self.assertEqual(lines('if (0) print "a"; else print "b";'
                               'if ("") print "c"; else print "d";'),
                         ["a", "c"])

    def test_compare_type_error(self):
        with self.assertRaises(RuntimeCoilError):
            run('print 1 < "x";')


class TestVariables(unittest.TestCase):
    def test_global(self):
        self.assertEqual(run("let x = 5; x = x + 1; print x;"), "6\n")

    def test_block_scope(self):
        src = "let x = 1; { let x = 2; print x; } print x;"
        self.assertEqual(lines(src), ["2", "1"])

    def test_redeclare_in_scope_errors(self):
        with self.assertRaises(CompileError):
            compile_source_text("{ let x = 1; let x = 2; }")

    def test_read_in_own_initializer_errors(self):
        with self.assertRaises(CompileError):
            compile_source_text("{ let x = x; }")

    def test_assign_undefined_global_errors(self):
        with self.assertRaises(RuntimeCoilError):
            run("nope = 5;")


class TestControlFlow(unittest.TestCase):
    def test_if_else_if(self):
        src = ("for (let i = 1; i <= 5; i = i + 1) {"
               " if (i == 2) print \"two\"; else if (i == 4) print \"four\";"
               " else print str(i); }")
        self.assertEqual(lines(src), ["1", "two", "3", "four", "5"])

    def test_while(self):
        self.assertEqual(run("let n=5; let f=1; while(n>1){f=f*n; n=n-1;} print f;"),
                         "120\n")

    def test_for(self):
        self.assertEqual(run("let s=0; for(let i=0;i<5;i=i+1){s=s+i;} print s;"),
                         "10\n")

    def test_break(self):
        self.assertEqual(run("let s=0; for(let i=0;i<100;i=i+1){if(i==3)break; s=s+i;} print s;"),
                         "3\n")

    def test_continue(self):
        self.assertEqual(run("let s=0; for(let i=0;i<5;i=i+1){if(i%2==0)continue; s=s+i;} print s;"),
                         "4\n")

    def test_continue_unwinds_body_locals_REGRESSION_C1(self):
        # Reading a loop-body local after a continue must see the right slot.
        src = ("fn t(){ let r=0; let i=0; while(i<4){ i=i+1; let m=i*100;"
               " if(i==2) continue; r=r+m; } return r; } print t();")
        self.assertEqual(run(src), "800\n")

    def test_break_then_later_local_REGRESSION_C1(self):
        src = ("fn t(){ for(let i=0;i<9;i=i+1){ let sq=i*i; if(i==3) break; }"
               " let after=42; return after; } print t();")
        self.assertEqual(run(src), "42\n")

    def test_break_continue_outside_loop_errors(self):
        with self.assertRaises(CompileError):
            compile_source_text("break;")
        with self.assertRaises(CompileError):
            compile_source_text("continue;")


class TestFunctions(unittest.TestCase):
    def test_call_and_return(self):
        self.assertEqual(run("fn add(a,b){return a+b;} print add(2,3);"), "5\n")

    def test_recursion_fib(self):
        self.assertEqual(run("fn fib(n){if(n<2)return n; return fib(n-1)+fib(n-2);} print fib(15);"),
                         "610\n")

    def test_implicit_nil_return(self):
        self.assertEqual(run("fn f(){} print f();"), "nil\n")

    def test_arity_mismatch(self):
        with self.assertRaises(RuntimeCoilError):
            run("fn f(a){return a;} f(1,2);")

    def test_call_non_function(self):
        with self.assertRaises(RuntimeCoilError):
            run("let x = 5; x();")

    def test_return_at_top_level_errors(self):
        with self.assertRaises(CompileError):
            compile_source_text("return 1;")

    def test_first_class_functions(self):
        src = ("fn apply(f,x){return f(x);} fn dbl(n){return n*2;}"
               " print apply(dbl, 21);")
        self.assertEqual(run(src), "42\n")

    def test_anonymous_function(self):
        self.assertEqual(run("let sq = fn(n){return n*n;}; print sq(9);"), "81\n")

    def test_deep_recursion_no_python_limit(self):
        # 400 deep — would blow Python's recursion limit if the VM recursed.
        src = ("fn count(n){ if(n==0) return 0; return 1 + count(n-1); }"
               " print count(400);")
        self.assertEqual(run(src), "400\n")


class TestClosures(unittest.TestCase):
    def test_counter(self):
        src = ("fn mk(){ let c=0; fn inc(){ c=c+1; return c; } return inc; }"
               " let a=mk(); let b=mk(); print a(); print a(); print b();")
        self.assertEqual(lines(src), ["1", "2", "1"])

    def test_per_iteration_capture(self):
        src = ("let fns=[]; for(let i=0;i<3;i=i+1){ let s=i;"
               " fn c(){return s;} push(fns,c); }"
               " print fns[0](); print fns[1](); print fns[2]();")
        self.assertEqual(lines(src), ["0", "1", "2"])

    def test_three_level_nesting_REGRESSION(self):
        src = ("fn outer(){ let a=1; fn mid(){ let b=10;"
               " fn inner(){ return a+b; } return inner; } return mid(); }"
               " print outer()();")
        self.assertEqual(run(src), "11\n")

    def test_closures_under_gc_stress(self):
        src = ("fn mk(){ let c=0; fn inc(){ c=c+1; return c; } return inc; }"
               " let a=mk(); print a(); print a(); print a();")
        self.assertEqual(lines(src, gc_stress=True), ["1", "2", "3"])


class TestLists(unittest.TestCase):
    def test_literal_and_index(self):
        self.assertEqual(run("let a=[10,20,30]; print a[0]+a[2];"), "40\n")

    def test_negative_index(self):
        self.assertEqual(run("print [1,2,3][-1];"), "3\n")

    def test_index_set(self):
        self.assertEqual(run("let a=[1,2,3]; a[1]=99; print a;"), "[1, 99, 3]\n")

    def test_out_of_range(self):
        with self.assertRaises(RuntimeCoilError):
            run("print [1,2][5];")

    def test_concat(self):
        self.assertEqual(run("print [1,2]+[3,4];"), "[1, 2, 3, 4]\n")

    def test_push_pop_len(self):
        self.assertEqual(lines("let a=[1]; push(a,2); print len(a); print pop(a); print a;"),
                         ["2", "2", "[1]"])

    def test_pop_empty_errors(self):
        with self.assertRaises(RuntimeCoilError):
            run("pop([]);")

    def test_slice_and_contains(self):
        self.assertEqual(run("print slice([1,2,3,4],1,3);"), "[2, 3]\n")
        self.assertEqual(lines("print contains([1,2,3],2); print contains([1,2],9);"),
                         ["true", "false"])

    def test_trailing_comma(self):
        self.assertEqual(run("print [1,2,3,];"), "[1, 2, 3]\n")


class TestMaps(unittest.TestCase):
    def test_literal_and_access(self):
        self.assertEqual(lines('let m={name:"Ada",age:36}; print m.name; print m["age"];'),
                         ["Ada", "36"])

    def test_set(self):
        self.assertEqual(run("let m={a:1}; m.a=2; m[\"b\"]=3; print m.a+m.b;"), "5\n")

    def test_keys_values_has_delete(self):
        src = ('let m={x:1,y:2}; print keys(m); print values(m);'
               ' print has(m,"x"); print delete(m,"x"); print has(m,"x");')
        self.assertEqual(lines(src),
                         ['["x", "y"]', "[1, 2]", "true", "true", "false"])

    def test_missing_key_errors(self):
        with self.assertRaises(RuntimeCoilError):
            run('print {a:1}["b"];')

    def test_number_keys(self):
        self.assertEqual(run("let m={}; m[1]=\"one\"; print m[1];"), "one\n")


class TestNatives(unittest.TestCase):
    def test_type(self):
        self.assertEqual(lines('print type(1); print type("s"); print type(true);'
                               ' print type(nil); print type([]); print type({});'),
                         ["number", "string", "bool", "nil", "list", "map"])

    def test_str_num(self):
        self.assertEqual(run('print str(42) + "!";'), "42!\n")
        self.assertEqual(run('print num("3.5") + 1;'), "4.5\n")

    def test_num_bad_input(self):
        with self.assertRaises(RuntimeCoilError):
            run('num("abc");')

    def test_math(self):
        self.assertEqual(lines("print abs(-3); print floor(3.9); print ceil(3.1);"
                               " print sqrt(16); print min(5,2,8); print max(5,2,8);"),
                         ["3", "3", "4", "4", "2", "8"])

    def test_sqrt_negative_errors(self):
        with self.assertRaises(RuntimeCoilError):
            run("sqrt(-1);")

    def test_range(self):
        self.assertEqual(run("print range(4);"), "[0, 1, 2, 3]\n")
        self.assertEqual(run("print range(2,5);"), "[2, 3, 4]\n")

    def test_string_ops(self):
        self.assertEqual(run('print upper("hi");'), "HI\n")
        self.assertEqual(run('print lower("HI");'), "hi\n")
        self.assertEqual(run('print split("a,b,c", ",");'), '["a", "b", "c"]\n')
        self.assertEqual(run('print join([1,2,3], "-");'), "1-2-3\n")
        self.assertEqual(run('print contains("hello", "ell");'), "true\n")

    def test_clock_returns_number(self):
        vm, out = run_vm("print type(clock());")
        self.assertEqual(out, "number\n")


class TestGC(unittest.TestCase):
    def test_reclaims_garbage(self):
        src = ("fn churn(){ for(let i=0;i<300;i=i+1){ let t=[i,i,i]; } }"
               " churn(); let freed = gc(); print freed >= 300;")
        self.assertEqual(run(src), "true\n")

    def test_live_objects_survive(self):
        src = ("let keep=[1,2,3]; let m={a:keep}; gc();"
               " print keep; print m;")
        self.assertEqual(lines(src), ["[1, 2, 3]", '{"a": [1, 2, 3]}'])

    def test_nested_aggregates_tracked_under_stress_REGRESSION_H1(self):
        # Inner lists must stay in the managed heap when built under GC.
        src = "let n=[[1],[2],[3]]; gc(); print heap_size();"
        self.assertEqual(run(src, gc_stress=True), run(src))  # same in both modes

    def test_collections_happen(self):
        vm, _ = run_vm("for(let i=0;i<5000;i=i+1){ let t=[i]; }")
        self.assertGreater(vm.collections, 0)


class TestDisassembler(unittest.TestCase):
    def test_disasm_contains_ops(self):
        fn = compile_source_text("fn add(a,b){return a+b;} print add(1,2);")
        text = disassemble(fn)
        self.assertIn("CLOSURE", text)
        self.assertIn("CALL", text)
        self.assertIn("ADD", text)
        self.assertIn("== add", text)
        self.assertIn("GET_LOCAL", text)


class TestErrorsAndTraceback(unittest.TestCase):
    def test_runtime_traceback_frames(self):
        src = ("fn a(){return b();} fn b(){return c();}"
               " fn c(){return 1 + \"x\";} a();")
        try:
            run(src)
        except RuntimeCoilError as e:
            names = [f[0] for f in e.traceback_frames]
            self.assertEqual(names[:3], ["c", "b", "a"])
            rendered = e.render(source=src, filename="t.coil")
            self.assertIn("traceback", rendered)
        else:
            self.fail("expected RuntimeCoilError")

    def test_undefined_variable(self):
        with self.assertRaises(RuntimeCoilError):
            run("print missing;")

    def test_stack_overflow_guarded(self):
        # Infinite recursion must raise a clean RuntimeCoilError, not crash.
        with self.assertRaises(RuntimeCoilError):
            run("fn loop(){return loop();} loop();")


class TestReplHelper(unittest.TestCase):
    def test_expression_detection(self):
        self.assertTrue(_looks_like_expression("1 + 2 * 3"))
        self.assertTrue(_looks_like_expression("[1,2,3]"))
        self.assertFalse(_looks_like_expression("let x = 5;"))
        self.assertFalse(_looks_like_expression("fn f(){}"))
        self.assertFalse(_looks_like_expression("1 +"))


class TestExamplePrograms(unittest.TestCase):
    EXAMPLES = os.path.join(ROOT, "examples")

    def _run_example(self, name):
        with open(os.path.join(self.EXAMPLES, name)) as f:
            return lines(f.read())

    def test_closures_example(self):
        self.assertEqual(self._run_example("closures.coil"),
                         ["1", "2", "3", "1", "0", "1", "2"])

    def test_fib_example(self):
        out = self._run_example("fib.coil")
        self.assertEqual(out[0], "0 -> 0")
        self.assertEqual(out[10], "10 -> 55")

    def test_fizzbuzz_example(self):
        out = self._run_example("fizzbuzz.coil")
        self.assertEqual(out[0], "1")
        self.assertEqual(out[2], "Fizz")
        self.assertEqual(out[4], "Buzz")
        self.assertEqual(out[14], "FizzBuzz")

    def test_sort_example(self):
        out = self._run_example("sort.coil")
        self.assertIn("quicksort: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]", out)
        self.assertIn("insertion: [0, 1, 7, 7, 13, 13, 42, 99]", out)

    def test_wordcount_example(self):
        out = self._run_example("wordcount.coil")
        self.assertIn("the: 3", out)
        self.assertIn("fox: 2", out)
        self.assertIn("words seen: 6", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
