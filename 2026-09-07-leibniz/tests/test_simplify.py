import random
import unittest
from fractions import Fraction

from leibniz.expr import I, Num, Symbol, mul
from leibniz.parser import parse
from leibniz.render import to_str
from leibniz.simplify import equal, simplify


class TestSimplify(unittest.TestCase):
    def test_combines_like_terms(self):
        self.assertEqual(to_str(simplify(parse("x + x + x"))), "3*x")

    def test_folds_constants_exactly(self):
        self.assertEqual(to_str(simplify(parse("1/3 + 1/6"))), "1/2")

    def test_multiplication_is_as_eager_as_addition(self):
        # historically, "2*(x+1)" auto-expanded but "(x+1)*(y+1)" didn't --
        # both must behave the same way now (regression for REVIEW.md #5)
        self.assertEqual(to_str(simplify(parse("2*(x+1)"))), "2*x + 2")
        self.assertEqual(to_str(simplify(parse("(x+1)*(y+1)"))), "x*y + x + y + 1")

    def test_idempotent(self):
        e = parse("(x+1)^3 - (x-2)*(x+5) + sin(x)*cos(x)")
        s1 = simplify(e)
        self.assertEqual(simplify(s1), s1)

    def test_nested_mul_flattening_regression(self):
        # REVIEW.md #1/#2: i*sqrt(19) must be visible to same-base combining
        # even after being folded into an Add term and multiplied again.
        t = mul(Num(Fraction(-1, 4)), I, parse("sqrt(19)"))
        s = t + t
        squared = simplify(s * s)
        self.assertEqual(squared, Num(-19) / Num(4))

    def test_rendering_of_negative_products(self):
        self.assertEqual(to_str(simplify(Num(-1) * I)), "-i")
        self.assertEqual(to_str(simplify(Symbol("x") - I)), "x - i")

    def test_equal_helper(self):
        self.assertTrue(equal(parse("x+x"), parse("2*x")))
        self.assertFalse(equal(parse("x+1"), parse("x+2")))


class TestSimplifyFuzz(unittest.TestCase):
    def test_random_polynomials_simplify_idempotently(self):
        random.seed(1234)
        x, y = Symbol("x"), Symbol("y")
        for _ in range(50):
            terms = []
            for _ in range(random.randint(1, 5)):
                coeff = random.randint(-5, 5)
                terms.append(coeff * x ** random.randint(0, 4) * y ** random.randint(0, 3))
            e = sum(terms, Num(0))
            s1 = simplify(e)
            s2 = simplify(s1)
            self.assertEqual(s1, s2)


if __name__ == "__main__":
    unittest.main()
