import glob
import os
import unittest
from tests.helpers import *
from lemma.pretty import show
from lemma.audit import export_certificate, audit_certificate

EXPECT = {"nat.lm": 6, "logic.lm": 8, "trees.lm": 3, "even.lm": 4}


class ExampleTests(unittest.TestCase):
    def test_every_example_checks_and_audits(self):
        files = sorted(glob.glob(os.path.join(ROOT, "examples", "*.lm")))
        self.assertEqual({os.path.basename(f) for f in files} >= set(EXPECT), True)
        for f in files:
            if os.path.basename(f).startswith("fail_"):
                continue
            s = clone_session()
            with open(f, encoding="utf-8") as fh:
                s.run(fh.read(), f)
            self.assertEqual(s.errors, [], f)
            n = sum(1 for r in s.results[s.n_prelude:] if r["kind"] == "theorem" and r["ok"])
            if os.path.basename(f) in EXPECT:
                self.assertEqual(n, EXPECT[os.path.basename(f)], f)
            res = audit_certificate(export_certificate(s, None))
            self.assertTrue(res.ok, f"{f}: {res.errors}")

    def test_failing_example_reports_every_error_and_continues(self):
        s = clone_session()
        f = os.path.join(ROOT, "examples", "fail_demo.lm")
        with open(f, encoding="utf-8") as fh:
            s.run(fh.read(), f)
        self.assertGreaterEqual(len(s.errors), 5)
        # the good theorems around the bad ones are still proved
        self.assertIn("good_one", s.k.decls)
        self.assertIn("good_two", s.k.decls)
        for bad in ("wrong_refl", "not_positive", "loops"):
            self.assertNotIn(bad, s.k.decls)

    def test_prelude_library_statements(self):
        s = clone_session()
        want = {
            "add_comm": "forall (m n : Nat), m + n = n + m",
            "add_assoc": "forall (a b c : Nat), a + b + c = a + (b + c)",
            "mul_comm": "forall (m n : Nat), m * n = n * m",
            "reverse_reverse": "forall (A : Type) (xs : List A), reverse A (reverse A xs) = xs",
            "le_trans": "forall (a b c : Nat), a <= b -> b <= c -> a <= c",
        }
        for name, stmt in want.items():
            self.assertEqual(show(s.k.decls[name].ty, [], s.k).replace("≤", "<="), stmt, name)
            self.assertEqual(s.k.axioms_of(name), [], name)


if __name__ == "__main__":
    unittest.main()
