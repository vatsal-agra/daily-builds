import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unify.repl import ReplState, process_statement, handle_type_query, load_prelude, is_blank
from unify.prelude import PRELUDE


class TestBlankDetection(unittest.TestCase):
    def test_whitespace_and_comments_are_blank(self):
        self.assertTrue(is_blank(""))
        self.assertTrue(is_blank("   "))
        self.assertTrue(is_blank("# just a comment"))

    def test_real_code_is_not_blank(self):
        self.assertFalse(is_blank("1 + 1"))


class TestPrelude(unittest.TestCase):
    def test_prelude_loads_without_error(self):
        state = ReplState()
        loaded = load_prelude(state)
        self.assertEqual(loaded, [name for name, _ in PRELUDE])
        for name, _ in PRELUDE:
            self.assertIn(name, state.type_env)
            self.assertIn(name, state.value_env)

    def test_map_is_polymorphic_after_loading(self):
        state = ReplState()
        load_prelude(state)
        ok, msg = process_statement(state, "(map (fun x -> x + 1) [1,2], map (fun x -> x) [true])")
        self.assertTrue(ok, msg)
        self.assertIn("([2; 3], [true])", msg)


class TestPersistentSession(unittest.TestCase):
    def test_let_binding_persists_across_statements(self):
        state = ReplState()
        ok, msg = process_statement(state, "let x = 41")
        self.assertTrue(ok, msg)
        self.assertIn("x : int = 41", msg)
        ok2, msg2 = process_statement(state, "x + 1")
        self.assertTrue(ok2, msg2)
        self.assertIn("42", msg2)

    def test_bare_expression_does_not_persist(self):
        state = ReplState()
        process_statement(state, "1 + 1")
        self.assertEqual(state.type_env, {})
        self.assertEqual(state.value_env, {})

    def test_let_in_expression_form_is_not_persisted(self):
        state = ReplState()
        ok, msg = process_statement(state, "let x = 1 in x + 1")
        self.assertTrue(ok, msg)
        self.assertNotIn("x", state.type_env)

    def test_polymorphic_binding_used_at_two_types(self):
        state = ReplState()
        process_statement(state, "let id = fun x -> x")
        ok, msg = process_statement(state, "(id 1, id true)")
        self.assertTrue(ok, msg)
        self.assertIn("(1, true)", msg)

    def test_recursive_binding_persists_and_recurses(self):
        state = ReplState()
        ok, msg = process_statement(state, "let rec fact n = if n = 0 then 1 else n * fact (n - 1)")
        self.assertTrue(ok, msg)
        ok2, msg2 = process_statement(state, "fact 5")
        self.assertTrue(ok2, msg2)
        self.assertIn("120", msg2)

    def test_failed_statement_does_not_corrupt_state(self):
        state = ReplState()
        process_statement(state, "let x = 1")
        ok, msg = process_statement(state, "let y = 1 + true")
        self.assertFalse(ok)
        self.assertNotIn("y", state.type_env)
        # `x` must still be usable afterward.
        ok2, msg2 = process_statement(state, "x + 1")
        self.assertTrue(ok2, msg2)

    def test_type_query_does_not_persist_or_evaluate(self):
        state = ReplState()
        result = handle_type_query(state, "1 + 2")
        self.assertIn(": int", result)
        self.assertEqual(state.type_env, {})

    def test_many_sequential_definitions_do_not_hang_or_collide(self):
        # Regression for REVIEW.md #7: this is exactly the shape of usage
        # (many top-level defs against a persisted env) that previously
        # could self-reference and hang.
        state = ReplState()
        load_prelude(state)
        defs = [
            "let inc = fun x -> x + 1",
            "let compose f g x = f (g x)",
            "let twice f x = f (f x)",
        ]
        for d in defs:
            ok, msg = process_statement(state, d)
            self.assertTrue(ok, msg)
        ok, msg = process_statement(state, "compose inc (twice inc) 0")
        self.assertTrue(ok, msg)
        self.assertIn("= 3", msg)


if __name__ == "__main__":
    unittest.main()
