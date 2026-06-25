"""
Monte Carlo noise model for quantum circuits.

Implements noise channels as Kraus operators applied randomly after each gate.
This "quantum trajectory" approach:
  - Avoids the 2^{2n} density matrix (uses a state vector instead)
  - Each "shot" is an independent stochastic realization of the decoherence
  - Multiple shots accumulate the noisy probability distribution

Supported channels:
  - Bit-flip:    E₀ = √(1-p) I,  E₁ = √p X
  - Phase-flip:  E₀ = √(1-p) I,  E₁ = √p Z
  - Depolarizing: E₀ = √(1-3p/4) I, E₁ = √(p/4) X, E₂ = √(p/4) Y, E₃ = √(p/4) Z
  - Amplitude damping (T1): E₀ = [[1,0],[0,√(1-γ)]], E₁ = [[0,√γ],[0,0]]
  - Phase damping (T2):  E₀ = [[1,0],[0,√(1-λ)]], E₁ = [[0,0],[0,√λ]]
"""

import math
import random
import cmath
from .state import QuantumState
from .gates import Gate, apply_1q


class NoiseChannel:
    """Abstract noise channel described by Kraus operators {K_i}."""

    def __init__(self, name: str, kraus_ops: list, n_qubits: int = 1):
        """
        kraus_ops: list of (2^n × 2^n) matrices (flat lists of complex)
        representing the Kraus operators.  Must satisfy Σ K_i† K_i = I.
        """
        self.name = name
        self.kraus_ops = kraus_ops  # list of flat complex matrices
        self.n_qubits = n_qubits
        self.dim = 1 << n_qubits
        # Pre-compute probabilities for each Kraus op: p_i = ‖K_i|ψ⟩‖²
        # (These are state-dependent; we compute them at apply-time)

    def apply(self, state: QuantumState, qubit: int,
              rng: random.Random) -> QuantumState:
        """
        Randomly apply one Kraus operator according to Born probabilities.
        Returns the post-noise state (normalized).
        """
        if self.n_qubits != 1:
            raise NotImplementedError("Only 1-qubit channels implemented here")

        # Compute probability of each Kraus outcome
        # P(K_i outcome) = ‖K_i|ψ⟩‖² = ⟨ψ|K_i†K_i|ψ⟩
        probs = []
        outcomes = []
        for K in self.kraus_ops:
            gate = Gate(f"K_{len(probs)}", K, 1)
            new_state = apply_1q(state, gate, qubit)
            p = sum(abs(a) ** 2 for a in new_state._amp)
            probs.append(p)
            outcomes.append(new_state)

        # Normalize probabilities (they should sum to 1 for trace-preserving)
        total = sum(probs)
        probs = [p / total for p in probs]

        # Sample outcome
        r = rng.random()
        cumulative = 0.0
        chosen = len(probs) - 1
        for i, p in enumerate(probs):
            cumulative += p
            if r <= cumulative:
                chosen = i
                break

        # Normalize the chosen outcome state
        chosen_state = outcomes[chosen]
        norm = math.sqrt(sum(abs(a) ** 2 for a in chosen_state._amp))
        if norm > 1e-10:
            new_amp = [a / norm for a in chosen_state._amp]
            result = QuantumState(state.n)
            result._amp = new_amp
            return result
        return state  # degenerate case: return unchanged


# ------------------------------------------------------------------
# Standard channel constructors
# ------------------------------------------------------------------

def bit_flip_channel(p: float) -> NoiseChannel:
    """Bit-flip channel: E₀=√(1-p)I, E₁=√p X."""
    sp = math.sqrt(p)
    s1p = math.sqrt(1 - p)
    K0 = [s1p, 0, 0, s1p]
    K1 = [0, sp, sp, 0]
    return NoiseChannel("BitFlip", [K0, K1])

def phase_flip_channel(p: float) -> NoiseChannel:
    """Phase-flip channel: E₀=√(1-p)I, E₁=√p Z."""
    sp = math.sqrt(p)
    s1p = math.sqrt(1 - p)
    K0 = [s1p, 0, 0, s1p]
    K1 = [sp, 0, 0, -sp]
    return NoiseChannel("PhaseFlip", [K0, K1])

def depolarizing_channel(p: float) -> NoiseChannel:
    """
    Depolarizing channel: with prob p applies X, Y, or Z (each with prob p/3).
    E₀=√(1-p)I, E₁=√(p/3)X, E₂=√(p/3)Y, E₃=√(p/3)Z.
    """
    s1p = math.sqrt(1 - p)
    sp3 = math.sqrt(p / 3)
    K0 = [s1p, 0, 0, s1p]
    K1 = [0, sp3, sp3, 0]
    K2 = [0, -1j*sp3, 1j*sp3, 0]
    K3 = [sp3, 0, 0, -sp3]
    return NoiseChannel("Depolarizing", [K0, K1, K2, K3])

def amplitude_damping_channel(gamma: float) -> NoiseChannel:
    """
    Amplitude damping (T1 decay): models energy loss.
    E₀=[[1,0],[0,√(1-γ)]], E₁=[[0,√γ],[0,0]]
    """
    sg = math.sqrt(gamma)
    s1g = math.sqrt(1 - gamma)
    K0 = [1, 0, 0, s1g]
    K1 = [0, sg, 0, 0]
    return NoiseChannel("AmplitudeDamping", [K0, K1])

def phase_damping_channel(lam: float) -> NoiseChannel:
    """
    Phase damping (T2 dephasing): models decoherence without energy loss.
    E₀=[[1,0],[0,√(1-λ)]], E₁=[[0,0],[0,√λ]]
    """
    sl = math.sqrt(lam)
    s1l = math.sqrt(1 - lam)
    K0 = [1, 0, 0, s1l]
    K1 = [0, 0, 0, sl]
    return NoiseChannel("PhaseDamping", [K0, K1])


# ------------------------------------------------------------------
# Noise model: maps gate names / qubit indices to channels
# ------------------------------------------------------------------

class NoiseModel:
    """
    A collection of noise channels applied after specific gates.

    Usage:
        nm = NoiseModel()
        nm.add_all_qubit_channel(depolarizing_channel(0.01))
        result = circuit.run(noise_model=nm, shots=1000)
    """

    def __init__(self):
        self._all_qubit: list = []         # channels applied to all qubits after every gate
        self._gate_channels: dict = {}     # gate_name → list of channels
        self._qubit_channels: dict = {}    # qubit_idx → list of channels

    def add_all_qubit_channel(self, channel: NoiseChannel) -> "NoiseModel":
        """Apply this channel to every qubit after every gate."""
        self._all_qubit.append(channel)
        return self

    def add_gate_channel(self, gate_name: str,
                         channel: NoiseChannel) -> "NoiseModel":
        """Apply this channel after a specific gate (by name)."""
        self._gate_channels.setdefault(gate_name, []).append(channel)
        return self

    def add_qubit_channel(self, qubit: int,
                          channel: NoiseChannel) -> "NoiseModel":
        """Apply this channel to a specific qubit after every gate."""
        self._qubit_channels.setdefault(qubit, []).append(channel)
        return self

    def apply(self, state: QuantumState,
              instr, rng: random.Random) -> QuantumState:
        """
        Apply noise after an instruction.
        Called by Circuit._run_once after each gate.
        """
        if instr.kind != "gate":
            return state

        gate_name = instr.gate.name
        affected_qubits = instr.qubits

        for q in affected_qubits:
            # All-qubit channels
            for ch in self._all_qubit:
                if ch.n_qubits == 1:
                    state = ch.apply(state, q, rng)

            # Per-qubit channels
            for ch in self._qubit_channels.get(q, []):
                if ch.n_qubits == 1:
                    state = ch.apply(state, q, rng)

        # Gate-specific channels (applied to all target qubits)
        for ch in self._gate_channels.get(gate_name, []):
            for q in affected_qubits:
                if ch.n_qubits == 1:
                    state = ch.apply(state, q, rng)

        return state

    @classmethod
    def depolarizing(cls, p: float) -> "NoiseModel":
        """Convenience: create a model with depolarizing noise on all qubits."""
        nm = cls()
        nm.add_all_qubit_channel(depolarizing_channel(p))
        return nm

    @classmethod
    def bit_flip(cls, p: float) -> "NoiseModel":
        nm = cls()
        nm.add_all_qubit_channel(bit_flip_channel(p))
        return nm

    @classmethod
    def thermal(cls, t1_gamma: float, t2_lam: float) -> "NoiseModel":
        """Combined T1 (amplitude) + T2 (phase) damping."""
        nm = cls()
        nm.add_all_qubit_channel(amplitude_damping_channel(t1_gamma))
        nm.add_all_qubit_channel(phase_damping_channel(t2_lam))
        return nm
