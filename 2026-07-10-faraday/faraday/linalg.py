"""Generic dense linear solver: Gaussian elimination with partial pivoting.

Written once, used for DC, transient, and AC analysis alike — the matrix
entries are plain Python numbers, and both ``float`` and ``complex`` support
``+ - * /`` and ``abs()``, so the exact same code path solves real-valued DC
networks and complex-phasor AC networks with no branching on type.
"""


class SingularMatrixError(Exception):
    """Raised when the MNA matrix has no unique solution (e.g. a circuit
    with a floating node, or two independent voltage sources shorted
    together)."""


def solve(A, b):
    """Solve the dense linear system A x = b.

    A is a list of n rows, each a list of n numbers (float or complex).
    b is a length-n list of numbers. Returns the length-n solution list.
    Neither input is mutated.
    """
    n = len(A)
    if n == 0:
        return []
    if any(len(row) != n for row in A) or len(b) != n:
        raise ValueError("A must be square and match the length of b")

    # Augment so pivoting swaps stay in sync automatically.
    M = [row[:] + [b[i]] for i, row in enumerate(A)]

    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot_row][col]) < 1e-14:
            raise SingularMatrixError(
                f"matrix is singular at column {col} — check for floating "
                f"nodes or conflicting sources"
            )
        if pivot_row != col:
            M[col], M[pivot_row] = M[pivot_row], M[col]

        pivot = M[col][col]
        for r in range(col + 1, n):
            factor = M[r][col] / pivot
            if factor == 0:
                continue
            row_col = M[col]
            row_r = M[r]
            for c in range(col, n + 1):
                row_r[c] -= factor * row_col[c]

    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        s = M[r][n]
        row_r = M[r]
        for c in range(r + 1, n):
            s -= row_r[c] * x[c]
        x[r] = s / row_r[r]
    return x


def residual_norm(A, x, b):
    """max_i |Ax - b|_i — used by tests/Newton loops to check convergence."""
    n = len(A)
    worst = 0.0
    for i in range(n):
        s = -b[i]
        for j in range(n):
            s += A[i][j] * x[j]
        worst = max(worst, abs(s))
    return worst
