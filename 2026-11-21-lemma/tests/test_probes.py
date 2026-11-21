"""Table of hostile / borderline inputs from the adversarial review: each must give exactly the
stated outcome (accepted, or rejected with the given message fragment) — never a crash."""
import unittest
from tests.helpers import *

OK = None
PROBES = [
    # --- soundness attacks: all rejected
    ("type-in-type", "def bad : Type := Type", "expected: Type"),
    ("non-positive", "inductive Bad : Type where | mk : (Bad -> Nat) -> Bad", "positive"),
    ("nested-non-positive", "inductive B2 : Type where | mk : List B2 -> B2", "positive"),
    ("universe-too-big", "inductive U : Type where | mk : Type -> U", "universe too small"),
    ("non-uniform-param", "inductive P (A : Type) : Type where | mk : P Nat -> P A", "uniform"),
    ("wrong-result", "inductive R : Type where | mk : Nat -> Nat", "must return 'R'"),
    ("self-proof", "theorem t : False := t", "structurally decreasing"),
    ("loop", "def loop (n : Nat) : Nat := loop n", "structurally decreasing"),
    ("wrong-refl", "theorem t : 2 + 2 = 5 := by refl.", "not definitionally equal"),
    # --- accepted corner cases
    ("eta", "theorem e (f : Nat -> Nat) : (fun (x : Nat) => f x) = f := by refl.", OK),
    ("delta", "def two : Nat := 2\ntheorem t : two + two = 4 := by refl.", OK),
    ("shadowing", "theorem t (n : Nat) : forall (n : Nat), n = n := by intro n. refl.", OK),
    ("primes", "theorem t (n' : Nat) : n' = n' := by refl.", OK),
    ("empty-elim", "def f (x : False) : Nat := elim x with end", OK),
    ("elim-expr", "def f (n : Nat) : Nat := elim (succ n) with | zero => 0 | succ k ih => k end\n#eval f 5", OK),
    ("elim-motive", "def g (n : Nat) : Nat := (elim n return (fun (_ : Nat) => Nat) with | zero => 7 | succ k ih => ih end)\n#eval g 3", OK),
    ("two-level-rec", "def minus (m n : Nat) : Nat := elim m with | zero => 0 | succ k ih => elim n with | zero => succ k | succ j ih2 => ih j end end\n#eval minus 10 4", OK),
    ("exists-elim", "theorem t (P : Nat -> Type) : Exists Nat P -> Exists Nat P := by intro h. cases h as intro a pa. exists a. exact pa.", OK),
    ("prefix-not", "theorem t (a : Nat) : ¬ (a = a) -> False := by intro h. apply h. refl.", OK),
    ("nat-rec-direct", "#eval Nat.rec (fun (_ : Nat) => Nat) 0 (fun (k : Nat) (ih : Nat) => succ ih) 5", OK),
    ("large-numeral", "#eval 20000", OK),
    ("deep-refl", "theorem t : 50 + 50 = 100 := by refl.", OK),
    # --- rejected with a useful message
    ("unknown-id", "def x : Nat := foo", "unknown identifier 'foo'"),
    ("bad-app", "def x : Nat := succ zero zero", "too many arguments"),
    ("mismatch", "def x : Nat := triv", "type mismatch"),
    ("missing-branch", "def x (n : Nat) : Nat := elim n with | zero => 0 end", "missing branch"),
    ("bad-ctor", "def x (n : Nat) : Nat := elim n with | zero => 0 | foo => 1 end", "not a constructor"),
    ("elim-noninductive", "def x (n : Nat -> Nat) : Nat := elim n with | zero => 0 end", "not an inductive type"),
    ("unfinished", "theorem t (a : Nat) : a = a := by intro.", "not a function"),
    ("too-many-tactics", "theorem t : 1 = 1 := by refl. refl.", "no goals left"),
    ("syntax-1", "theorem t : := by refl.", "expected a term"),
    ("syntax-2", "theorem t : 1 = 1 := by refl", "expected '.'"),
    ("syntax-3", "def x : Nat := 0 )", "expected a command"),
    ("unknown-tactic", "theorem t : 1 = 1 := by foo.", "unknown tactic"),
    ("hole", "def x : Nat := _", "holes"),
    ("fun-no-ann", "#check fun x => x", "cannot infer"),
    ("assumption-fail", "theorem t (a b : Nat) : a = b := by assumption.", "no hypothesis matches"),
    ("rewrite-nomatch", "theorem t (a b : Nat) (h : a = b) : 1 = 1 := by rewrite h.", "did not find"),
    ("induction-nonvar", "theorem t (n : Nat) (v : Vec Nat (succ n)) : v = v := by induction v as vcons k x xs ih. refl.", "not a variable"),
    ("ill-motive", "def h (n : Nat) : Nat := elim n return Nat with | zero => 0 | succ k ih => 1 end", "function of 1 argument"),
    ("unterminated-comment", "/- never closed", "unterminated block comment"),
    ("unterminated-string", 'infix 50 "oops => add', "unterminated string"),
    ("bad-char", "def x : Nat := 0 \x01", "unexpected character"),
    ("non-assoc", "#check 1 = 2 = 3", "non-associative"),
]


class ProbeTests(unittest.TestCase):
    pass


def make(name, src, expect):
    def t(self):
        s, e = run(src)
        if expect is OK:
            self.assertEqual(e, "", f"{name} should be accepted:\n{e}")
        else:
            self.assertIn(expect, e, f"{name}: expected {expect!r} in\n{e}")
            self.assertNotIn("internal error", e)
    return t


for n, src, exp in PROBES:
    setattr(ProbeTests, "test_" + n.replace("-", "_"), make(n, src, exp))


if __name__ == "__main__":
    unittest.main()
