import unittest
from tests.helpers import *
from lemma.kernel import Kernel, KernelError
from lemma.terms import *


def fresh_nat():
    k = Kernel()
    N = Const("Nat")
    k.add_inductive("Nat", Sort(0), 0, [("zero", N), ("succ", Pi("n", N, N))])
    return k, N


class KernelTests(unittest.TestCase):
    def test_nat_recursor_shape(self):
        k, N = fresh_nat()
        self.assertEqual(str(k.decls["Nat.rec"].ty),
                         "forall (motive : Nat -> Type), motive zero -> (forall (n : Nat), motive n -> motive (succ n)) -> (forall (t : Nat), motive t)")
        self.assertIn("Nat.rec_1", k.decls)
        self.assertIn("Nat.rec_2", k.decls)

    def test_iota_and_delta(self):
        k, N = fresh_nat()
        add = Lam("m", N, Lam("n", N, apps(Const("Nat.rec"), Lam("_", N, N), Var(0),
                                          Lam("k", N, Lam("ih", N, App(Const("succ"), Var(0)))), Var(1))))
        k.add_def("add", Pi("m", N, Pi("n", N, N)), add)
        two = App(Const("succ"), App(Const("succ"), Const("zero")))
        four = App(Const("succ"), App(Const("succ"), two))
        self.assertTrue(k.def_eq(apps(Const("add"), two, two), four))
        self.assertFalse(k.def_eq(apps(Const("add"), two, two), two))

    def test_eta(self):
        k, N = fresh_nat()
        f = Fv("f", Pi("x", N, N))
        eta = Lam("x", N, App(f, Var(0)))
        self.assertTrue(k.def_eq(eta, f))

    def test_type_in_type_rejected(self):
        k, N = fresh_nat()
        with self.assertRaises(KernelError):
            k.add_def("bad", Sort(0), Sort(0))

    def test_ill_typed_application_rejected(self):
        k, N = fresh_nat()
        with self.assertRaises(KernelError):
            k.add_def("bad", N, App(Const("zero"), Const("zero")))
        with self.assertRaises(KernelError):
            k.add_def("bad2", N, App(Const("succ"), Sort(0)))

    def test_open_terms_rejected(self):
        k, N = fresh_nat()
        with self.assertRaises(KernelError):
            k.add_def("leak", N, Fv("x", N))
        with self.assertRaises(KernelError):
            k.add_def("loose", N, Var(3))

    def test_duplicate_declaration(self):
        k, N = fresh_nat()
        with self.assertRaises(KernelError):
            k.add_axiom("Nat", Sort(0))

    def test_positivity(self):
        k, N = fresh_nat()
        with self.assertRaises(KernelError) as cm:
            k.add_inductive("Bad", Sort(0), 0, [("mk", Pi("f", Pi("x", Const("Bad"), N), Const("Bad")))])
        self.assertIn("positive", str(cm.exception))
        self.assertNotIn("Bad", k.decls)            # rolled back
        self.assertNotIn("mk", k.decls)

    def test_positive_function_field_ok(self):
        k, N = fresh_nat()
        k.add_inductive("W", Sort(0), 0, [("sup", Pi("f", Pi("x", N, Const("W")), Const("W")))])
        self.assertIn("W.rec", k.decls)

    def test_universe_bound(self):
        k, N = fresh_nat()
        with self.assertRaises(KernelError) as cm:
            k.add_inductive("U", Sort(0), 0, [("mk", Pi("A", Sort(0), Const("U")))])
        self.assertIn("universe", str(cm.exception))
        k.add_inductive("U1", Sort(1), 0, [("mk", Pi("A", Sort(0), Const("U1")))])      # fine one level up

    def test_nonuniform_parameter(self):
        k, N = fresh_nat()
        ty = Pi("A", Sort(0), Sort(0))
        mk = Pi("A", Sort(0), Pi("x", App(Const("P"), N), App(Const("P"), Var(1))))
        with self.assertRaises(KernelError):
            k.add_inductive("P", ty, 1, [("mk", mk)])

    def test_constructor_must_return_the_type(self):
        k, N = fresh_nat()
        with self.assertRaises(KernelError):
            k.add_inductive("R", Sort(0), 0, [("mk", Pi("n", N, N))])

    def test_indexed_family_iota(self):
        s = ok("""
inductive Vec2 (A : Type) : Nat -> Type where
| vn : Vec2 A 0
| vc : (n : Nat) -> A -> Vec2 A n -> Vec2 A (succ n)
def vlen (A : Type) (n : Nat) (v : Vec2 A n) : Nat :=
  Vec2.rec A (fun (m : Nat) (w : Vec2 A m) => Nat) 0 (fun (m : Nat) (a : A) (w : Vec2 A m) (ih : Nat) => succ ih) n v
theorem t : vlen Nat 2 (vc Nat 1 0 (vc Nat 0 0 (vn Nat))) = 2 := by refl.
""")
        self.assertIn("t", s.k.decls)

    def test_recursor_rules_are_generated_per_universe(self):
        k, N = fresh_nat()
        for r in ("Nat.rec", "Nat.rec_1", "Nat.rec_2"):
            self.assertEqual(set(k.decls[r].info.rules), {"zero", "succ"})

    def test_cumulativity(self):
        k, N = fresh_nat()
        k.add_def("lift", Sort(1), N)               # Nat : Type ≤ Type 1
        with self.assertRaises(KernelError):
            k.add_def("down", Sort(0), Sort(0))

    def test_axioms_tracking(self):
        s = ok("axiom ax : Nat\ndef uses : Nat := ax\ndef clean : Nat := 1")
        self.assertEqual(s.k.axioms_of("uses"), ["ax"])
        self.assertEqual(s.k.axioms_of("clean"), [])
        self.assertEqual(s.k.axioms_of("add_comm"), [])


if __name__ == "__main__":
    unittest.main()
