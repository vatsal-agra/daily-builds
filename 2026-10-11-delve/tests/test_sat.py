import itertools, random, unittest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from delve.sat import Solver


def brute(n, clauses):
    for bits in itertools.product([False, True], repeat=n):
        if all(any((bits[abs(l) - 1] if l > 0 else not bits[abs(l) - 1]) for l in c) for c in clauses):
            return True
    return False


def mk(n, clauses):
    s = Solver()
    for _ in range(n):
        s.new_var()
    for c in clauses:
        s.add_clause(c)
    return s


class SatTests(unittest.TestCase):
    def test_random_3sat_vs_bruteforce(self):
        rnd = random.Random(7)
        for _ in range(300):
            n = rnd.randint(3, 11)
            m = rnd.randint(n, int(n * 5))
            cl = [[rnd.choice([-1, 1]) * rnd.randint(1, n) for _ in range(3)] for _ in range(m)]
            s = mk(n, cl)
            r = s.solve()
            self.assertEqual(r, brute(n, cl))
            if r:
                for c in cl:
                    self.assertTrue(any(s.lit_model(l) for l in c))

    def test_assumptions_and_incremental(self):
        s = mk(3, [[1, 2], [-1, 3]])
        self.assertTrue(s.solve([1]))
        self.assertTrue(s.model_value(3))
        self.assertFalse(s.solve([1, -3]))
        self.assertIn(-3, s.conflict_core)
        self.assertTrue(s.solve([-1]))
        s.add_clause([-2])
        self.assertTrue(s.solve())
        self.assertFalse(s.solve([-1]))
        self.assertTrue(s.solve([1]))

    def test_pigeonhole_unsat(self):
        # 5 pigeons into 4 holes
        P, H = 5, 4
        var = lambda p, h: p * H + h + 1
        cl = [[var(p, h) for h in range(H)] for p in range(P)]
        for h in range(H):
            for a in range(P):
                for b in range(a + 1, P):
                    cl.append([-var(a, h), -var(b, h)])
        self.assertFalse(mk(P * H, cl).solve())

    def test_empty_and_unit(self):
        s = Solver()
        self.assertTrue(s.solve())
        a = s.new_var()
        s.add_clause([a]); s.add_clause([-a])
        self.assertFalse(s.solve())


if __name__ == "__main__":
    unittest.main()
