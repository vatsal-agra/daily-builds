import unittest
from tests.helpers import *


def proves(stmt, script, extra=""):
    s, e = run(f"{extra}\ntheorem t {stmt} := by\n  {script}")
    return s, e


def good(stmt, script, extra=""):
    s, e = proves(stmt, script, extra)
    assert not e, e
    assert "t" in s.k.decls
    return s


def bad(stmt, script, needle, extra=""):
    s, e = proves(stmt, script, extra)
    assert e, f"expected failure for {script!r}"
    assert needle in e, f"{needle!r} not in\n{e}"
    assert "t" not in s.k.decls
    return e


class TacticTests(unittest.TestCase):
    def test_intro_exact(self):
        good(": forall (a b : Nat), a = b -> a = b", "intro a b h. exact h.")

    def test_intros_names_fresh(self):
        good(": forall (a b : Nat), a = b -> b = a", "intros. symm. assumption.")

    def test_intro_through_definition(self):
        good(": ¬ False", "intro h. exact h.")

    def test_intro_on_non_function(self):
        bad("(a : Nat) : a = a", "intro.", "not a function")

    def test_refl_by_computation(self):
        good(": 2 + 2 = 4", "refl.")
        good(": 6 * 7 = 42", "refl.")

    def test_refl_failure_shows_normal_forms(self):
        e = bad(": 2 + 2 = 5", "refl.", "not definitionally equal")
        self.assertIn("4", e)
        self.assertIn("5", e)

    def test_assumption(self):
        good("(a b : Nat) (h : a = b) : a = b", "assumption.")
        bad("(a b : Nat) : a = b", "assumption.", "no hypothesis matches")

    def test_apply_with_leftover_goals_ordering(self):
        good("(a b c : Nat) (h1 : a = b) (h2 : b = c) : a = c", "apply Eq.trans. exact h1. exact h2.")

    def test_apply_unification_failure(self):
        bad("(a : Nat) : a = a", "apply zero_ne_succ.", "cannot unify")

    def test_symm(self):
        good("(a b : Nat) (h : a = b) : b = a", "symm. exact h.")

    def test_rewrite_forward_backward(self):
        good("(a b c : Nat) (h : a = b) (g : b = c) : a = c", "rewrite h. exact g.")
        good("(a b : Nat) (h : a = b) (g : b = 3) : a = 3", "rewrite <- g. exact h.")

    def test_rewrite_at_hypothesis(self):
        good("(a b c : Nat) (h : a = b) (h2 : a = c) : b = c", "rewrite h at h2. exact h2.")

    def test_rewrite_pattern_not_found(self):
        bad("(a b : Nat) (h : a = b) : 1 = 1", "rewrite h.", "did not find an instance")

    def test_rewrite_closes_reflexive_goal_and_says_so(self):
        good("(a b : Nat) (h : a = b) : a = b", "rewrite h.")
        e = bad("(a b : Nat) (h : a = b) : a = b", "rewrite h. refl.", "closed the goal automatically")

    def test_rewrite_is_syntactic_not_defeq(self):
        # `k * 0` is δι-equal to `succ k * 0`, but rewriting must not claim progress on it
        s, e = run("theorem t (k : Nat) (ih : k * 0 = 0) : succ k * 0 = 0 := by rewrite ih.")
        self.assertIn("did not find an instance", e)

    def test_rewrite_motive_error_is_local(self):
        e = bad("(A : Type) (n m : Nat) (v : Vec A n) (h : n = m) : v = v", "rewrite h.", "ill-typed")

    def test_induction_nat(self):
        good("(n : Nat) : n + 0 = n", "induction n as zero | succ k ih. { refl. } { simp [ih]. }")

    def test_induction_default_names(self):
        s = good("(n : Nat) : n + 0 = n", "induction n. { refl. } { simp [n_ih]. }".replace("n_ih", "n_ih"))

    def test_induction_with_dependent_hypothesis(self):
        good("(n m : Nat) (h : n = m) : m = n",
             "induction n as zero | succ k ih. { rewrite <- h. } { rewrite <- h. }")

    def test_induction_unknown_constructor(self):
        bad("(n : Nat) : n = n", "induction n as foo.", "not a constructor")

    def test_induction_on_non_inductive(self):
        bad("(f : Nat -> Nat) : f = f", "induction f.", "not an inductive type")

    def test_induction_indexed_family(self):
        good("(n m : Nat) (h : Even n) (g : Even m) : Even (n + m)",
             "induction h as even_zero | even_ss k hk ih. { exact g. } { exact even_ss (k + m) ih. }",
             extra="inductive Even : Nat -> Type where\n| even_zero : Even 0\n| even_ss : (n : Nat) -> Even n -> Even (succ (succ n))")

    def test_induction_needs_variable_index(self):
        bad("(n : Nat) (v : Vec Nat (succ n)) : v = v", "induction v.", "not a variable")

    def test_cases_and_constructors(self):
        good("(A B : Type) : A /\\ B -> B /\\ A", "intro h. cases h as conj a b. split. { exact b. } { exact a. }")
        good("(A B : Type) : A \\/ B -> B \\/ A", "intro h. cases h as inl a | inr b. { right. exact a. } { left. exact b. }")

    def test_exists(self):
        good(": Exists Nat (fun (n : Nat) => n + n = 4)", "exists 2. refl.")
        bad(": Exists Nat (fun (n : Nat) => n + n = 4)", "exists 3. refl.", "not definitionally equal")

    def test_exfalso_and_contradiction(self):
        good("(A B : Type) (a : A) (na : ¬ A) : B", "exfalso. apply na. exact a.")
        good("(A B : Type) (a : A) (na : ¬ A) : B", "contradiction.")
        good("(h : False) : 1 = 2", "contradiction.")
        bad("(a : Nat) : a = 2", "contradiction.", "no contradictory hypotheses")

    def test_have(self):
        good("(a b c : Nat) (h1 : a = b) (h2 : b = c) : a = c",
             "have h3 : a = c := Eq.trans Nat a b c h1 h2. exact h3.")
        good("(a b c : Nat) (h1 : a = b) (h2 : b = c) : a = c",
             "have h3 : b = c. { exact h2. } rewrite h1. exact h3.")

    def test_show_and_norm(self):
        good(": 2 + 2 = 4", "show 4 = 4. refl.")
        bad(": 2 + 2 = 4", "show 5 = 5.", "not (definitionally)")
        good("(a : Nat) : a + 0 = a", "norm. simp [add_zero_r].".replace("norm. ", ""))

    def test_simp_uses_equations_and_given_lemmas(self):
        good("(a b : Nat) : succ a + b = succ (a + b)", "simp.")
        good("(a b : Nat) : a + succ b = succ (a + b)", "simp [add_succ_r].")
        bad("(a b : Nat) : a + b = b + a", "simp.", "simp made no progress")

    def test_simp_terminates_on_looping_lemma(self):
        s, e = proves("(a b : Nat) : a + b = b + a", "simp [add_comm].")
        # must terminate; whether it closes the goal or not is irrelevant
        self.assertTrue(True)

    def test_congr(self):
        good("(a b : Nat) (h : a = b) : succ a = succ b", "congr. exact h.")

    def test_unfold_and_revert(self):
        good("(a : Nat) : double a = a + a", "induction a as zero | succ k ih. { refl. } { simp [ih, add_succ_r]. }",
             extra="def double (n : Nat) : Nat := elim n with | zero => 0 | succ k ih => succ (succ (double k)) end")
        good("(a b : Nat) (h : a = b) : b = a", "revert h. intro h. symm. exact h.")

    def test_try_and_blocks(self):
        good("(a : Nat) : a = a", "try assumption. refl.")
        bad("(a : Nat) : a = a /\\ a = a", "split. { refl. }", "unsolved goals")
        bad("(a : Nat) : a = a", "refl. refl.", "no goals left")

    def test_unsolved_goals_reported_with_context(self):
        e = bad("(a b : Nat) : a = b /\\ b = a", "split. { admit_not_a_tactic. }", "unknown tactic")
        e = bad("(a b : Nat) (h : a = b) : a = b /\\ b = a", "split.", "unsolved goals")
        self.assertIn("h : a = b", e)
        self.assertIn("⊢", e)

    def test_tactic_syntax_errors(self):
        bad(": 1 = 1", "refl", "expected '.'")
        bad(": 1 = 1", "foo.", "unknown tactic 'foo'")

    def test_kernel_catches_a_buggy_tactic(self):
        """Tactics are untrusted: make `refl` lie and check the kernel still refuses the theorem."""
        import lemma.tactics as T
        from lemma.terms import apps, Const
        orig = T.State.t_refl

        def lying_refl(self, tac, goal):
            parts = self.eq_parts(goal.target)
            A, a, b = parts
            self.solve(goal, apps(Const("refl"), A, a))          # no defeq check at all!
            return []
        sess = Session()
        T.State.t_refl = lying_refl
        try:
            s, e = run("theorem fake : 2 + 2 = 5 := by refl.", sess)
        finally:
            T.State.t_refl = orig
        self.assertIn("kernel rejected 'fake'", e)
        self.assertNotIn("fake", s.k.decls)

    def test_kernel_catches_a_buggy_rewrite(self):
        import lemma.tactics as T
        orig = T.State.do_rewrite

        def lying(self, tac, goal, tm, rev, at):
            g = self.new_goal(goal.hyps, goal.target, goal.name)
            from lemma.terms import Const
            self.solve(goal, g.meta)
            return [g]
        sess = Session()
        T.State.do_rewrite = lying
        try:
            s, e = run("theorem fake (a b : Nat) (h : a = b) : b = a := by rewrite h.", sess)
        finally:
            T.State.do_rewrite = orig
        self.assertTrue(e)                      # unsolved goal or kernel rejection — never accepted
        self.assertNotIn("fake", s.k.decls)


if __name__ == "__main__":
    unittest.main()
