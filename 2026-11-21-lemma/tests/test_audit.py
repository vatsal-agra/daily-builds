import copy
import json
import random
import unittest
from tests.helpers import *
from lemma.audit import export_certificate, audit_certificate, build_auditor, to_named, term_json
from lemma.kernel import KernelError
from lemma.terms import *


def cert_for(src):
    s = clone_session()
    s.run(src, "t.lm")
    assert not s.errors, s.errors
    return s, export_certificate(s, None)


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s, cls.cert = cert_for("theorem tt : 2 + 2 = 4 := by refl.\n"
                                   "inductive Tree (A : Type) : Type where | leaf : Tree A | node : Tree A -> A -> Tree A -> Tree A")

    def mutated(self, fn):
        c = copy.deepcopy(self.cert)
        fn(c)
        return audit_certificate(c)

    def find(self, c, name):
        return next(d for d in c["decls"] if d["name"] == name)

    def test_untouched_certificate_verifies(self):
        r = audit_certificate(self.cert)
        self.assertTrue(r.ok, r.errors)
        self.assertGreater(r.theorems, 20)
        self.assertGreaterEqual(r.inductives, 14)

    def test_json_roundtrip(self):
        r = audit_certificate(json.loads(json.dumps(self.cert)))
        self.assertTrue(r.ok)

    def test_swapped_proof_rejected(self):
        def m(c):
            self.find(c, "add_comm")["val"] = self.find(c, "add_zero_r")["val"]
        self.assertFalse(self.mutated(m).ok)

    def test_false_theorem_rejected(self):
        def m(c):
            c["decls"].append({"kind": "theorem", "name": "oops", "ty": ["const", "False"], "val": ["const", "triv"]})
        r = self.mutated(m)
        self.assertFalse(r.ok)
        self.assertIn("oops", r.errors[0])

    def test_tampered_iota_rule_rejected(self):
        def m(c):
            r = self.find(c, "Nat.rec")
            r["rules"]["succ"][0] = r["rules"]["zero"][0]
        r = self.mutated(m)
        self.assertFalse(r.ok)
        self.assertIn("ι-rule", r.errors[0])

    def test_tampered_recursor_type_rejected(self):
        def m(c):
            self.find(c, "Tree.rec")["ty"] = self.find(c, "Nat.rec")["ty"]
        self.assertFalse(self.mutated(m).ok)

    def test_non_positive_constructor_rejected(self):
        def m(c):
            self.find(c, "succ")["ty"] = ["pi", "f", ["pi", "x", ["const", "Nat"], ["const", "Nat"]], ["const", "Nat"]]
        self.assertFalse(self.mutated(m).ok)

    def test_universe_cheat_rejected(self):
        def m(c):
            self.find(c, "Nat")["ty"] = ["sort", 0]
            self.find(c, "succ")["ty"] = ["pi", "A", ["sort", 0], ["const", "Nat"]]
        self.assertFalse(self.mutated(m).ok)

    def test_dropped_declaration_rejected(self):
        def m(c):
            c["decls"] = [d for d in c["decls"] if d["name"] != "add"]
        self.assertFalse(self.mutated(m).ok)

    def test_axiom_is_visible_to_both(self):
        s, c = cert_for("axiom a : Nat\ndef b : Nat := a")
        self.assertTrue(audit_certificate(c).ok)
        self.assertEqual(s.k.axioms_of("b"), ["a"])


class DifferentialTests(unittest.TestCase):
    """Kernel (de Bruijn + NbE) vs auditor (named + substitution): same verdict on random and mutated terms."""

    @classmethod
    def setUpClass(cls):
        cls.s = clone_session()
        cls.k = cls.s.k
        cls.aud, res = build_auditor(export_certificate(cls.s, None))
        assert res.ok
        cls.consts = ["Nat", "zero", "succ", "add", "mul", "Eq", "refl", "True", "triv", "False", "Not", "And", "conj",
                      "Nat.rec", "List", "nil", "cons", "Bool", "true", "pred", "Or", "inl", "append", "length", "Eq.symm"]

    def verdicts(self, t):
        try:
            kt = self.k.quote(0, self.k.infer(Ctx(), t))
            kok = True
        except KernelError:
            kok = False
        try:
            at = self.aud.infer(to_named(term_json(t)), {})
            aok = True
        except Exception as e:
            if type(e).__name__ != "AuditError":
                raise
            aok = False
        if kok and aok:
            self.assertTrue(self.aud.conv(at, to_named(term_json(kt))), f"types differ for {t}")
        return kok, aok

    def gen(self, rnd, depth, nbind):
        r = rnd.random()
        if depth == 0 or r < 0.2:
            c = rnd.random()
            if nbind and c < 0.3:
                return Var(rnd.randrange(nbind))
            if c < 0.4:
                return Sort(rnd.randrange(3))
            return Const(rnd.choice(self.consts))
        if r < 0.6:
            return App(self.gen(rnd, depth - 1, nbind), self.gen(rnd, depth - 1, nbind))
        if r < 0.8:
            return Lam("x", self.gen(rnd, depth - 1, nbind), self.gen(rnd, depth - 1, nbind + 1))
        return Pi("x", self.gen(rnd, depth - 1, nbind), self.gen(rnd, depth - 1, nbind + 1))

    def test_random_terms_agree(self):
        rnd = random.Random(7)
        both = rejected = 0
        for _ in range(1500):
            t = self.gen(rnd, 4, 0)
            kok, aok = self.verdicts(t)
            self.assertEqual(kok, aok, f"verdicts differ on {t}: kernel={kok} auditor={aok}")
            both += kok
            rejected += (not kok)
        self.assertGreater(both, 30)            # the generator does produce well-typed terms
        self.assertGreater(rejected, 300)

    def mutate(self, rnd, t, depth=0):
        """Randomly alter one spot of a (closed, de Bruijn) term."""
        def go(t, nb):
            kids = []
            if isinstance(t, App): kids = [t.f, t.a]
            elif isinstance(t, Pi): kids = [t.dom, t.cod]
            elif isinstance(t, Lam): kids = [t.dom, t.body]
            if kids and rnd.random() < 0.75:
                i = rnd.randrange(len(kids))
                nbs = [nb, nb] if isinstance(t, App) else [nb, nb + 1]
                new = go(kids[i], nbs[i])
                if isinstance(t, App): return App(new, t.a) if i == 0 else App(t.f, new)
                if isinstance(t, Pi): return Pi(t.name, new, t.cod) if i == 0 else Pi(t.name, t.dom, new)
                return Lam(t.name, new, t.body) if i == 0 else Lam(t.name, t.dom, new)
            c = rnd.random()
            if c < 0.3 and nb: return Var(rnd.randrange(nb))
            if c < 0.6: return Const(rnd.choice(self.consts))
            if c < 0.8 and isinstance(t, App): return t.f
            return t if c < 0.9 else Sort(rnd.randrange(2))
        return go(t, 0)

    def test_mutated_proofs_agree(self):
        rnd = random.Random(11)
        names = ["add_zero_r", "add_comm", "succ_inj", "zero_ne_succ", "Eq.symm", "Eq.trans", "le_refl", "append_nil", "False.elim"]
        vals = [(n, self.k.decls[n].val, self.k.decls[n].ty) for n in names]
        still_ok = 0
        total = 0
        for _ in range(400):
            n, val, ty = rnd.choice(vals)
            m = self.mutate(rnd, val)
            try:
                self.k.check(Ctx(), m, self.k.eval([], ty))
                kok = True
            except KernelError:
                kok = False
            try:
                self.aud.check(to_named(term_json(m)), to_named(term_json(ty)), {})
                aok = True
            except Exception as e:
                if type(e).__name__ != "AuditError":
                    raise
                aok = False
            self.assertEqual(kok, aok, f"mutated proof of {n}: kernel={kok} auditor={aok}\n{m}")
            total += 1
            still_ok += kok
        self.assertGreater(total - still_ok, 150)      # most mutations are caught


from lemma.kernel import Ctx  # noqa: E402

if __name__ == "__main__":
    unittest.main()
