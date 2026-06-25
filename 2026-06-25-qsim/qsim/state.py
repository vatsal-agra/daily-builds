"""
QuantumState: n-qubit complex state vector.

Qubit ordering: qubit 0 is the MOST significant bit (big-endian convention).
So |010⟩ with n=3 means qubit0=0, qubit1=1, qubit2=0 → index 2 (binary 010).
This matches most physics textbooks and Qiskit's reversed display convention
(but we display in natural order, qubit 0 at left).
"""

import cmath
import math
import random

_SQRT2_INV = 1.0 / math.sqrt(2)

# Threshold below which an amplitude is considered zero for printing.
_PRINT_EPS = 1e-9


class QuantumState:
    """n-qubit state vector as a list of 2^n complex amplitudes."""

    def __init__(self, n: int, amplitudes=None):
        if n < 1:
            raise ValueError("Must have at least 1 qubit")
        if n > 25:
            raise ValueError("n > 25 would need > 512 MB; use n ≤ 25")
        self.n = n
        self.dim = 1 << n  # 2^n
        if amplitudes is None:
            # Default: |0…0⟩
            self._amp = [0.0 + 0.0j] * self.dim
            self._amp[0] = 1.0 + 0.0j
        else:
            if len(amplitudes) != self.dim:
                raise ValueError(
                    f"Expected {self.dim} amplitudes for {n} qubits, "
                    f"got {len(amplitudes)}"
                )
            self._amp = [complex(a) for a in amplitudes]

    # ------------------------------------------------------------------
    # Factory constructors
    # ------------------------------------------------------------------

    @classmethod
    def zero(cls, n: int) -> "QuantumState":
        """|0…0⟩"""
        return cls(n)

    @classmethod
    def from_basis(cls, n: int, index: int) -> "QuantumState":
        """Computational basis state |index⟩."""
        if not (0 <= index < (1 << n)):
            raise ValueError(f"index {index} out of range for {n} qubits")
        s = cls(n)
        s._amp[0] = 0.0 + 0.0j
        s._amp[index] = 1.0 + 0.0j
        return s

    @classmethod
    def from_bitstring(cls, bits: str) -> "QuantumState":
        """Create from a bitstring, e.g. '010' → |010⟩ (qubit 0 = '0')."""
        n = len(bits)
        index = int(bits, 2)
        return cls.from_basis(n, index)

    @classmethod
    def plus(cls, n: int = 1) -> "QuantumState":
        """Uniform superposition |+…+⟩ = H^⊗n |0…0⟩."""
        amp = [1.0 / math.sqrt(1 << n)] * (1 << n)
        return cls(n, amp)

    @classmethod
    def tensor_product(cls, *states: "QuantumState") -> "QuantumState":
        """Tensor product of multiple states: |ψ₁⟩ ⊗ |ψ₂⟩ ⊗ …"""
        if not states:
            raise ValueError("Need at least one state")
        result_amp = [1.0 + 0.0j]
        total_n = 0
        for st in states:
            new_amp = []
            for a in result_amp:
                for b in st._amp:
                    new_amp.append(a * b)
            result_amp = new_amp
            total_n += st.n
        return cls(total_n, result_amp)

    # ------------------------------------------------------------------
    # Core properties
    # ------------------------------------------------------------------

    def amplitudes(self) -> list:
        """Return a copy of the amplitude list."""
        return list(self._amp)

    def probabilities(self) -> list:
        """Return |α_i|² for each basis state."""
        return [abs(a) ** 2 for a in self._amp]

    def norm(self) -> float:
        return math.sqrt(sum(abs(a) ** 2 for a in self._amp))

    def normalize(self) -> "QuantumState":
        """Return a new normalized state (does not mutate self)."""
        n2 = self.norm()
        if n2 < 1e-15:
            raise ValueError("Zero state — cannot normalize")
        return QuantumState(self.n, [a / n2 for a in self._amp])

    def inner_product(self, other: "QuantumState") -> complex:
        """⟨self|other⟩"""
        if self.n != other.n:
            raise ValueError("Qubit count mismatch")
        return sum(self._amp[i].conjugate() * other._amp[i] for i in range(self.dim))

    def fidelity(self, other: "QuantumState") -> float:
        """F = |⟨self|other⟩|²"""
        return abs(self.inner_product(other)) ** 2

    def copy(self) -> "QuantumState":
        return QuantumState(self.n, list(self._amp))

    # ------------------------------------------------------------------
    # Partial state operations
    # ------------------------------------------------------------------

    def reduced_density_matrix(self, qubits: list) -> list:
        """
        Compute the reduced density matrix ρ for the given qubits by tracing
        out all others.  Returns a (2^k × 2^k) matrix as a flat list (row-major)
        of complex, where k = len(qubits).
        """
        k = len(qubits)
        dim_k = 1 << k
        n_env = self.n - k
        dim_env = 1 << n_env

        env_qubits = [q for q in range(self.n) if q not in qubits]

        rho = [0.0 + 0.0j] * (dim_k * dim_k)

        for sys_row in range(dim_k):
            for sys_col in range(dim_k):
                val = 0.0 + 0.0j
                for env_idx in range(dim_env):
                    row_full = _pack_bits(self.n, qubits, sys_row, env_qubits, env_idx)
                    col_full = _pack_bits(self.n, qubits, sys_col, env_qubits, env_idx)
                    val += self._amp[row_full] * self._amp[col_full].conjugate()
                rho[sys_row * dim_k + sys_col] = val
        return rho

    def bloch_vector(self, qubit: int = 0):
        """
        Return the Bloch sphere (x,y,z) for a single-qubit reduced state.
        Only meaningful if the qubit is not entangled (pure product state).
        """
        if self.n == 1:
            rho = self._amp
            # rho[0]=α, rho[1]=β for |ψ⟩=α|0⟩+β|1⟩
            a, b = rho[0], rho[1]
            x = 2.0 * (a.conjugate() * b).real
            y = 2.0 * (a.conjugate() * b).imag
            z = abs(a) ** 2 - abs(b) ** 2
            return (x, y, z)
        rdm = self.reduced_density_matrix([qubit])
        # rdm is 2×2: [[rho00, rho01],[rho10, rho11]]
        rho00 = rdm[0]
        rho01 = rdm[1]
        rho10 = rdm[2]
        x = (rho01 + rho10).real
        y = (1j * (rho10 - rho01)).real
        z = (rho00 - rdm[3]).real
        return (x, y, z)

    def entanglement_entropy(self, partition: list) -> float:
        """
        Von Neumann entropy S = -Tr(ρ log ρ) of the reduced state for `partition`
        (a list of qubit indices).  Computed via eigenvalues of the reduced density
        matrix.  Returns a value in [0, log(2^k)].
        """
        k = len(partition)
        dim_k = 1 << k
        rho = self.reduced_density_matrix(partition)
        # eigenvalues via power iteration would be slow; for small k we do
        # the full 2^k x 2^k matrix via Jacobi or Gram-Schmidt.
        # For simplicity and correctness: use the SVD-based approach.
        # The reduced density matrix is Hermitian, so eigenvalues are real ≥ 0.
        evals = _hermitian_eigenvalues(rho, dim_k)
        S = 0.0
        for lam in evals:
            if lam > 1e-15:
                S -= lam * math.log(lam)
        return S

    # ------------------------------------------------------------------
    # Printing
    # ------------------------------------------------------------------

    def dirac(self, max_terms: int = 16, eps: float = _PRINT_EPS) -> str:
        """
        Return Dirac notation string showing all significant terms,
        e.g. '0.707|00⟩ + 0.707|11⟩'.
        """
        terms = []
        for idx, amp in enumerate(self._amp):
            if abs(amp) < eps:
                continue
            bits = format(idx, f"0{self.n}b")
            mag = abs(amp)
            phase = cmath.phase(amp)
            if abs(phase) < eps and abs(amp.imag) < eps:
                coeff = f"{amp.real:.4g}"
            elif abs(amp.real) < eps:
                coeff = f"{amp.imag:.4g}i"
            else:
                coeff = f"({amp.real:.4g}+{amp.imag:.4g}i)"
            terms.append(f"{coeff}|{bits}⟩")
        if not terms:
            return "0"
        result = " + ".join(terms[:max_terms])
        if len(terms) > max_terms:
            result += f" + … ({len(terms) - max_terms} more terms)"
        return result

    def __repr__(self) -> str:
        return f"QuantumState(n={self.n}, {self.dirac(max_terms=4)})"

    def __str__(self) -> str:
        return self.dirac()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _pack_bits(n: int, sys_qubits: list, sys_val: int,
               env_qubits: list, env_val: int) -> int:
    """
    Reconstruct a full n-qubit index from separate sys/env sub-indices.
    Each sub-index uses the corresponding qubit list in big-endian order.
    """
    idx = 0
    for bit_pos, q in enumerate(reversed(sys_qubits)):
        bit = (sys_val >> bit_pos) & 1
        idx |= bit << (n - 1 - q)
    for bit_pos, q in enumerate(reversed(env_qubits)):
        bit = (env_val >> bit_pos) & 1
        idx |= bit << (n - 1 - q)
    return idx


def _hermitian_eigenvalues(rho_flat: list, dim: int) -> list:
    """
    Compute eigenvalues of a dim×dim Hermitian matrix (stored as flat list,
    row-major) using the QR algorithm with Householder reflections.
    Returns a list of real floats.

    For dim ≤ 16 this is fast enough.
    """
    if dim == 1:
        return [rho_flat[0].real]
    if dim == 2:
        a = rho_flat[0].real
        d = rho_flat[3].real
        b = rho_flat[1]
        disc = math.sqrt(max(0.0, ((a - d) / 2) ** 2 + abs(b) ** 2))
        mid = (a + d) / 2
        return [mid + disc, mid - disc]
    # General: use Jacobi iteration for Hermitian matrices
    # Convert to a mutable 2D list (real parts only for diagonal reduction)
    M = [[rho_flat[i * dim + j] for j in range(dim)] for i in range(dim)]
    return _jacobi_eigenvalues(M, dim)


def _jacobi_eigenvalues(M: list, dim: int, max_iter: int = 200) -> list:
    """Jacobi algorithm for Hermitian matrices; returns eigenvalues."""
    import copy
    A = copy.deepcopy(M)
    for _ in range(max_iter * dim * dim):
        # Find off-diagonal element with largest magnitude
        p, q, max_val = 0, 1, 0.0
        for i in range(dim):
            for j in range(i + 1, dim):
                v = abs(A[i][j])
                if v > max_val:
                    max_val = v
                    p, q = i, j
        if max_val < 1e-12:
            break
        # Compute Jacobi rotation angle
        theta = (A[q][q] - A[p][p]) / (2.0 * A[p][q] + 1e-300)
        t = (1.0 / (abs(theta) + math.sqrt(1 + theta * theta)))
        if theta < 0:
            t = -t
        c = 1.0 / math.sqrt(1.0 + t * t)
        s = t * c
        # Apply rotation
        Ap = [row[:] for row in A]
        for r in range(dim):
            if r != p and r != q:
                Ap[r][p] = c * A[r][p] - s * A[r][q]
                Ap[p][r] = Ap[r][p].conjugate()
                Ap[r][q] = s * A[r][p] + c * A[r][q]
                Ap[q][r] = Ap[r][q].conjugate()
        Ap[p][p] = c * c * A[p][p] - 2 * s * c * A[p][q] + s * s * A[q][q]
        Ap[q][q] = s * s * A[p][p] + 2 * s * c * A[p][q] + c * c * A[q][q]
        Ap[p][q] = 0.0 + 0.0j
        Ap[q][p] = 0.0 + 0.0j
        A = Ap
    return [A[i][i].real for i in range(dim)]
