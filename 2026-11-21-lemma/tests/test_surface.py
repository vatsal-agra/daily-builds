import unittest
from tests.helpers import *


def err(src):
    s, e = run(src)
    return e


class SurfaceTests(unittest.TestCase):
    def test_eval_arithmetic(self):
        s = ok("#eval 6 * 7\n#eval 100 * 100\n#eval sub 10 3")
        self.assertEqual([l.split(" :")[0] for l in s.out], ["42", "10000", "7"])

    def test_check_and_notation_roundtrip(self):
        s = ok("#check 1 + 2 * 3 = 7\n#check forall (A B : Type), A /\\ B -> B\n#check fun (A : Type) (a : A) => ¬ a = a")
        self.assertEqual(s.out[0], "1 + 2 * 3 = 7 : Type")
        self.assertIn("A /\\ B -> B", s.out[1])
        self.assertIn("¬ a = a", s.out[2])

    def test_precedence(self):
        s = ok("theorem p : 1 + 2 * 3 = 7 := by refl.\ntheorem q : (1 + 2) * 3 = 9 := by refl.")
        self.assertIn("p", s.k.decls)

    def test_comments_and_unicode(self):
        ok("-- line\n/- block /- nested -/ -/\ndef x : Nat := 3 -- trailing\ndef f := 0".replace("def f := 0", ""))
        ok("def idλ : Nat -> Nat := λ (x : Nat) => x".replace("idλ", "idl"))
        ok("def g : Nat -> Nat := ∀_placeholder".replace("∀_placeholder", "fun (x : Nat) => x"))

    def test_let_is_a_macro(self):
        s = ok("#eval let x : Nat := 3 in x * x")
        self.assertTrue(s.out[0].startswith("9"))

    def test_positioned_errors(self):
        e = err("def x : Nat := foo")
        self.assertIn("test.lm:1:16", e)
        self.assertIn("unknown identifier 'foo'", e)
        self.assertIn("^", e)

    def test_typo_suggestion(self):
        self.assertIn("did you mean 'succ'", err("def x : Nat := sucs zero"))

    def test_type_mismatch_message(self):
        e = err("def x : Nat := triv")
        self.assertIn("expected: Nat", e)
        self.assertIn("but got:  True", e)

    def test_too_many_args(self):
        self.assertIn("too many arguments", err("def x : Nat := succ zero zero"))

    def test_fun_needs_annotation_in_infer_mode(self):
        self.assertIn("cannot infer the type of 'x'", err("#check fun x => x"))

    def test_holes_rejected(self):
        self.assertIn("holes", err("def x : Nat := _"))

    def test_duplicate_names(self):
        self.assertIn("already declared", err("def add : Nat := 0"))
        self.assertIn("already declared", err("inductive Nat : Type where"))

    def test_syntax_errors_recover_and_continue(self):
        s, e = run("def a : := 1\ndef b : Nat := 2\n#eval b")
        self.assertIn("expected a term", e)
        self.assertTrue(any(l.startswith("2") for l in s.out))        # later commands still run

    def test_stray_tokens(self):
        self.assertIn("expected a command", err("def x : Nat := 0 )"))

    def test_missing_type_annotation(self):
        self.assertIn("type annotation is required", err("def x := 0"))

    def test_elim_errors(self):
        self.assertIn("missing branch for constructor(s) succ", err("def x (n : Nat) : Nat := elim n with | zero => 0 end"))
        self.assertIn("'foo' is not a constructor", err("def x (n : Nat) : Nat := elim n with | zero => 0 | foo => 1 end"))
        self.assertIn("must bind 2 name(s)", err("def x (n : Nat) : Nat := elim n with | zero => 0 | succ => 1 end"))
        self.assertIn("not an inductive type", err("def x (n : Nat -> Nat) : Nat := elim n with | zero => 0 end"))
        self.assertIn("duplicate branch", err("def x (n : Nat) : Nat := elim n with | zero => 0 | zero => 1 | succ k ih => 2 end"))
        self.assertIn("function of 1 argument", err("def h (n : Nat) : Nat := elim n return Nat with | zero => 0 | succ k ih => 1 end"))

    def test_elim_on_empty_type(self):
        s = ok("def absurd2 (A : Type) (f : False) : A := elim f with end")
        self.assertIn("absurd2", s.k.decls)

    def test_structural_recursion_and_equations(self):
        s = ok("def dbl (n : Nat) : Nat := elim n with | zero => 0 | succ k ih => succ (succ (dbl k)) end\n#eval dbl 21")
        self.assertTrue(s.out[-1].startswith("42"))
        self.assertIn("dbl.eq_zero", s.k.decls)
        self.assertIn("dbl.eq_succ", s.k.decls)
        self.assertEqual(str(s.k.decls["dbl.eq_succ"].ty), "forall (k : Nat), Eq Nat (dbl (succ k)) (succ (succ (dbl k)))")

    def test_recursion_on_second_argument_keeps_first_fixed(self):
        s = ok("#eval sub 10 4")
        self.assertTrue(s.out[0].startswith("6"))

    def test_fun_style_definition_is_recursive_too(self):
        s = ok("def tw : Nat -> Nat := fun (n : Nat) => elim n with | zero => 0 | succ k ih => succ (succ (tw k)) end\n#eval tw 5")
        self.assertTrue(s.out[-1].startswith("10"))

    def test_nonstructural_recursion_rejected(self):
        for src in ["def loop (n : Nat) : Nat := loop n",
                    "def f (n : Nat) : Nat := elim n with | zero => 0 | succ k ih => f (succ k) end",
                    "theorem t : False := t",
                    "def g (m n : Nat) : Nat := elim n with | zero => 0 | succ k ih => g (succ m) k end"]:
            self.assertIn("not in a structurally decreasing way", err(src), src)

    def test_failed_definition_leaves_no_trace(self):
        s, e = run("def oops (n : Nat) : Nat := oops n")
        self.assertNotIn("oops", s.k.decls)
        s, e = run("inductive Bad : Type where | mk : (Bad -> Nat) -> Bad", s)
        self.assertNotIn("Bad", s.k.decls)
        self.assertNotIn("mk", s.k.decls)

    def test_custom_inductive_and_notation(self):
        s = ok("""
inductive Color : Type where
| red : Color
| green : Color
def next (c : Color) : Color := elim c with | red => green | green => red end
infixl 60 "<+>" => add
#eval next (next red)
#eval 1 <+> 2
""")
        self.assertTrue(any(l.startswith("red : Color") for l in s.out))
        self.assertTrue(any(l.startswith("3 : Nat") for l in s.out))

    def test_print_and_print_axioms(self):
        s = ok("axiom ax : Nat\ndef u : Nat := ax\n#print axioms u\n#print axioms add_comm\n#print Nat")
        self.assertTrue(any("'u' depends on axioms: ax" in l for l in s.out))
        self.assertTrue(any("'add_comm' does not depend on any axioms" in l for l in s.out))
        self.assertTrue(any("| succ : Nat -> Nat" in l for l in s.out))

    def test_axiom_use_is_flagged(self):
        s = ok("axiom bad : False\ntheorem anything : 1 = 2 := False.elim (1 = 2) bad")
        self.assertTrue(any("uses axiom(s): bad" in l for l in s.out))

    def test_empty_and_comment_only_files(self):
        self.assertEqual(err(""), "")
        self.assertEqual(err("-- nothing"), "")

    def test_big_numerals_do_not_blow_the_stack(self):
        s = ok("#eval 20000")
        self.assertTrue(s.out[0].startswith("20000"))


if __name__ == "__main__":
    unittest.main()
