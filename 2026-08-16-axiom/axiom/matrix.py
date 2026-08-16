"""Exact/symbolic matrices over Axiom expressions — the stretch "symbolic
matrices" feature: +, *, transpose, determinant (cofactor expansion, so it
works over symbolic entries, not just numbers), the adjugate/inverse, and
linear-system solving via Cramer's rule. Every operation is verified in the
test suite against a from-scratch Gauss-Jordan reference (for the pure
rational-number case) and against `A @ A.inverse() == I`.
"""

from fractions import Fraction

from .errors import AxiomError
from .expr import Expr, add, mul, num, power


def _coerce(x):
    return x if isinstance(x, Expr) else num(x)


class Matrix:
    def __init__(self, rows):
        rows = [tuple(_coerce(x) for x in row) for row in rows]
        if not rows or not rows[0]:
            raise AxiomError("a Matrix needs at least one row and column")
        width = len(rows[0])
        if any(len(r) != width for r in rows):
            raise AxiomError("all Matrix rows must have the same length")
        self.rows = tuple(rows)

    @property
    def nrows(self):
        return len(self.rows)

    @property
    def ncols(self):
        return len(self.rows[0])

    def __getitem__(self, key):
        i, j = key
        return self.rows[i][j]

    def __eq__(self, other):
        return isinstance(other, Matrix) and self.rows == other.rows

    def __hash__(self):
        return hash(self.rows)

    def __repr__(self):
        return str(self)

    def __str__(self):
        cells = [[str(x) for x in row] for row in self.rows]
        widths = [max(len(cells[i][j]) for i in range(self.nrows)) for j in range(self.ncols)]
        lines = []
        for row in cells:
            padded = [c.rjust(widths[j]) for j, c in enumerate(row)]
            lines.append("[ " + "  ".join(padded) + " ]")
        return "\n".join(lines)

    @staticmethod
    def identity(n):
        return Matrix([[num(1) if i == j else num(0) for j in range(n)] for i in range(n)])

    @staticmethod
    def zeros(rows, cols=None):
        cols = rows if cols is None else cols
        return Matrix([[num(0)] * cols for _ in range(rows)])

    def transpose(self):
        return Matrix([[self.rows[i][j] for i in range(self.nrows)] for j in range(self.ncols)])

    def _check_same_shape(self, other):
        if self.nrows != other.nrows or self.ncols != other.ncols:
            raise AxiomError(
                f"shape mismatch: {self.nrows}x{self.ncols} vs {other.nrows}x{other.ncols}")

    def __add__(self, other):
        self._check_same_shape(other)
        return Matrix([[self[i, j] + other[i, j] for j in range(self.ncols)]
                        for i in range(self.nrows)])

    def __sub__(self, other):
        self._check_same_shape(other)
        return Matrix([[self[i, j] + mul(num(-1), other[i, j]) for j in range(self.ncols)]
                        for i in range(self.nrows)])

    def __neg__(self):
        return Matrix([[mul(num(-1), x) for x in row] for row in self.rows])

    def __mul__(self, other):
        if isinstance(other, Matrix):
            if self.ncols != other.nrows:
                raise AxiomError(
                    f"cannot multiply a {self.nrows}x{self.ncols} by a "
                    f"{other.nrows}x{other.ncols} matrix")
            return Matrix([
                [add(*[self[i, k] * other[k, j] for k in range(self.ncols)])
                 for j in range(other.ncols)]
                for i in range(self.nrows)])
        scalar = _coerce(other)
        return Matrix([[x * scalar for x in row] for row in self.rows])

    __rmul__ = __mul__

    def minor(self, skip_row, skip_col):
        return Matrix([
            [self[i, j] for j in range(self.ncols) if j != skip_col]
            for i in range(self.nrows) if i != skip_row])

    def det(self):
        if self.nrows != self.ncols:
            raise AxiomError("determinant is only defined for square matrices")
        n = self.nrows
        if n == 1:
            return self[0, 0]
        if n == 2:
            return add(self[0, 0] * self[1, 1], mul(num(-1), self[0, 1] * self[1, 0]))
        from .expr import Num
        if all(isinstance(self[i, j], Num) for i in range(n) for j in range(n)):
            return num(self._bareiss_det())
        # Symbolic entries: Bareiss needs exact division by the running pivot,
        # which isn't generally meaningful for arbitrary Expr, so fall back
        # to plain cofactor expansion (correct for any entries, just O(n!)).
        terms = []
        for j in range(n):
            sign = 1 if j % 2 == 0 else -1
            terms.append(mul(num(sign), self[0, j], self.minor(0, j).det()))
        return add(*terms)

    def _bareiss_det(self):
        """Fraction-free Gaussian elimination (Bareiss 1968): exact, O(n^3),
        every intermediate division is provably exact (no rational-arithmetic
        blowup and no floating point) — used for the numeric-entry fast path
        so det() stays practical well past the ~8x8 ceiling of the O(n!)
        cofactor expansion above."""
        n = self.nrows
        M = [[self[i, j].value for j in range(n)] for i in range(n)]
        sign = 1
        prev_pivot = Fraction(1)
        for k in range(n - 1):
            if M[k][k] == 0:
                swap = next((r for r in range(k + 1, n) if M[r][k] != 0), None)
                if swap is None:
                    return Fraction(0)
                M[k], M[swap] = M[swap], M[k]
                sign = -sign
            for i in range(k + 1, n):
                for j in range(k + 1, n):
                    M[i][j] = (M[i][j] * M[k][k] - M[i][k] * M[k][j]) / prev_pivot
                M[i][k] = Fraction(0)
            prev_pivot = M[k][k]
        return sign * M[n - 1][n - 1]

    def cofactor_matrix(self):
        n = self.nrows
        return Matrix([
            [mul(num(1 if (i + j) % 2 == 0 else -1), self.minor(i, j).det()) for j in range(n)]
            for i in range(n)])

    def adjugate(self):
        return self.cofactor_matrix().transpose()

    def inverse(self):
        d = self.det()
        from .expr import Num
        if isinstance(d, Num) and d.value == 0:
            raise AxiomError("matrix is singular (determinant is 0), it has no inverse")
        return self.adjugate() * power(d, num(-1))

    def solve(self, b):
        """Solve Ax = b (b: list of Expr or a column Matrix) via Cramer's rule."""
        if isinstance(b, Matrix):
            b_vals = [b[i, 0] for i in range(b.nrows)]
        else:
            b_vals = [_coerce(x) for x in b]
        if len(b_vals) != self.nrows or self.nrows != self.ncols:
            raise AxiomError("solve() needs a square matrix and a matching-length vector")
        d = self.det()
        from .expr import Num
        if isinstance(d, Num) and d.value == 0:
            raise AxiomError("the system has no unique solution (determinant is 0)")
        solution = []
        for col in range(self.ncols):
            replaced = Matrix([
                [b_vals[i] if j == col else self[i, j] for j in range(self.ncols)]
                for i in range(self.nrows)])
            solution.append(replaced.det() * power(d, num(-1)))
        return solution
