import random
import unittest

from axiom import parse, sym, num
from axiom.matrix import Matrix
from axiom.errors import AxiomError


def N(rows):
    return tuple(tuple(num(x) for x in row) for row in rows)


def brute_det(rows):
    n = len(rows)
    if n == 1:
        return rows[0][0]
    total = 0
    for j in range(n):
        minor = [row[:j] + row[j + 1:] for row in rows[1:]]
        total += ((-1) ** j) * rows[0][j] * brute_det(minor)
    return total


class TestBasics(unittest.TestCase):
    def test_add_sub_mul(self):
        A = Matrix([[1, 2], [3, 4]])
        B = Matrix([[5, 6], [7, 8]])
        self.assertEqual((A + B).rows, N([[6, 8], [10, 12]]))
        self.assertEqual((A * 2).rows, N([[2, 4], [6, 8]]))
        self.assertEqual((2 * A).rows, N([[2, 4], [6, 8]]))

    def test_matrix_multiply(self):
        A = Matrix([[1, 2], [3, 4]])
        B = Matrix([[5, 6], [7, 8]])
        C = A * B
        self.assertEqual(C.rows, N([[19, 22], [43, 50]]))

    def test_transpose(self):
        A = Matrix([[1, 2, 3], [4, 5, 6]])
        self.assertEqual(A.transpose().rows, N([[1, 4], [2, 5], [3, 6]]))

    def test_identity(self):
        I = Matrix.identity(3)
        A = Matrix([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
        self.assertEqual((A * I).rows, A.rows)


class TestDeterminant(unittest.TestCase):
    def test_2x2(self):
        self.assertEqual(Matrix([[1, 2], [3, 4]]).det(), parse("-2"))

    def test_bareiss_matches_cofactor_oracle(self):
        random.seed(2)
        for trial in range(60):
            n = random.randint(1, 6)
            rows = [[random.randint(-4, 4) for _ in range(n)] for _ in range(n)]
            if trial % 4 == 0 and n > 1:
                rows[0][0] = 0  # force a pivot swap sometimes
            expected = brute_det(rows)
            got = Matrix(rows).det()
            self.assertEqual(int(got.value), expected, msg=rows)

    def test_singular_matrix_det_zero(self):
        self.assertEqual(Matrix([[1, 2], [2, 4]]).det(), parse("0"))

    def test_symbolic_determinant(self):
        x = sym("x")
        M = Matrix([[x, 1], [1, x]])
        self.assertEqual(M.det(), parse("x^2 - 1"))

    def test_non_square_raises(self):
        with self.assertRaises(AxiomError):
            Matrix([[1, 2, 3], [4, 5, 6]]).det()


class TestInverseAndSolve(unittest.TestCase):
    def test_inverse_times_self_is_identity(self):
        A = Matrix([[2, 1], [1, 1]])
        prod = A * A.inverse()
        self.assertEqual(prod.rows, Matrix.identity(2).rows)

    def test_singular_inverse_raises(self):
        with self.assertRaises(AxiomError):
            Matrix([[1, 2], [2, 4]]).inverse()

    def test_solve_linear_system(self):
        A = Matrix([[2, 1], [1, 1]])
        x_sol = A.solve([3, 2])
        self.assertEqual(x_sol, [parse("1"), parse("1")])

    def test_solve_verified_by_substitution(self):
        random.seed(4)
        for _ in range(10):
            n = random.randint(2, 4)
            rows = [[random.randint(-3, 3) for _ in range(n)] for _ in range(n)]
            M = Matrix(rows)
            if M.det() == parse("0"):
                continue
            b = [random.randint(-5, 5) for _ in range(n)]
            sol = M.solve(b)
            # verify Ax == b by direct substitution
            for i in range(n):
                lhs = sum(rows[i][j] * sol[j].evalf().real for j in range(n))
                self.assertAlmostEqual(lhs, b[i], places=6)


class TestConstruction(unittest.TestCase):
    def test_empty_matrix_raises(self):
        with self.assertRaises(AxiomError):
            Matrix([])

    def test_ragged_rows_raise(self):
        with self.assertRaises(AxiomError):
            Matrix([[1, 2], [3]])

    def test_shape_mismatch_add_raises(self):
        with self.assertRaises(AxiomError):
            Matrix([[1, 2]]) + Matrix([[1], [2]])


if __name__ == "__main__":
    unittest.main()
