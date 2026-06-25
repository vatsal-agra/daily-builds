"""
QSim command-line interface.

Subcommands:
  grover           Run Grover's search algorithm
  deutsch-jozsa    Run Deutsch-Jozsa oracle classification
  bernstein-vazirani  Recover a hidden string
  qft              Run and verify the Quantum Fourier Transform
  teleport         Quantum teleportation demo
  simon            Simon's period-finding algorithm
  qpe              Quantum Phase Estimation
  bell             Create and measure Bell states
  noise            Demo of noise channels
  circuit          Run an ASCII circuit from a spec file or inline string
  viz              Generate an HTML visualizer for a circuit+state
  demo             Run all algorithms and show results
"""

import argparse
import json
import math
import random
import sys
import os


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="qsim",
        description="QSim — quantum circuit simulator",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # grover
    p = sub.add_parser("grover", help="Grover's search algorithm")
    p.add_argument("n", type=int, help="Number of qubits (search space = 2^n)")
    p.add_argument("--marked", nargs="+", type=int, help="Marked item indices")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--shots", type=int, default=512)

    # deutsch-jozsa
    p = sub.add_parser("deutsch-jozsa", help="Deutsch-Jozsa oracle classification")
    p.add_argument("n", type=int, help="Number of input qubits")
    p.add_argument("--oracle", default="balanced",
                   choices=["constant_0", "constant_1", "balanced", "balanced_parity"],
                   help="Oracle type")
    p.add_argument("--secret", help="Secret bits for balanced_parity oracle")
    p.add_argument("--seed", type=int, default=42)

    # bernstein-vazirani
    p = sub.add_parser("bernstein-vazirani", help="Recover a hidden bitstring")
    p.add_argument("secret", help="Hidden bitstring, e.g. '10110'")
    p.add_argument("--seed", type=int, default=42)

    # qft
    p = sub.add_parser("qft", help="Quantum Fourier Transform verification")
    p.add_argument("n", type=int, help="Number of qubits")
    p.add_argument("--input", type=int, default=None,
                   help="Input basis state index (default: 1)")
    p.add_argument("--seed", type=int, default=42)

    # teleport
    p = sub.add_parser("teleport", help="Quantum teleportation demo")
    p.add_argument("--state", default="superposition",
                   choices=["superposition", "plus", "minus", "zero", "one", "random"],
                   help="State to teleport")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--trials", type=int, default=20)

    # simon
    p = sub.add_parser("simon", help="Simon's period-finding algorithm")
    p.add_argument("n", type=int, help="Number of qubits")
    p.add_argument("--period", help="Period string (default: random)")
    p.add_argument("--seed", type=int, default=42)

    # qpe
    p = sub.add_parser("qpe", help="Quantum Phase Estimation")
    p.add_argument("phase", type=float, help="True phase φ ∈ [0, 1)")
    p.add_argument("--n-count", type=int, default=4,
                   help="Number of counting qubits (precision = 1/2^n)")
    p.add_argument("--seed", type=int, default=42)

    # bell
    p = sub.add_parser("bell", help="Bell state preparation and measurement")
    p.add_argument("--state", default="phi+",
                   choices=["phi+", "phi-", "psi+", "psi-"],
                   help="Which Bell state to prepare")
    p.add_argument("--shots", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)

    # noise
    p = sub.add_parser("noise", help="Noise channel demonstration")
    p.add_argument("--channel", default="depolarizing",
                   choices=["depolarizing", "bit_flip", "phase_flip",
                            "amplitude_damping", "phase_damping", "thermal"],
                   help="Noise channel type")
    p.add_argument("--p", type=float, default=0.05, help="Error probability")
    p.add_argument("--shots", type=int, default=2000)
    p.add_argument("--seed", type=int, default=42)

    # viz
    p = sub.add_parser("viz", help="Generate HTML visualizer")
    p.add_argument("--algorithm", default="grover",
                   choices=["grover", "dj", "bv", "qft", "teleport", "bell", "qpe"],
                   help="Algorithm to visualize")
    p.add_argument("-o", "--output", default="qsim_viz.html",
                   help="Output HTML file")
    p.add_argument("--seed", type=int, default=42)

    # demo
    p = sub.add_parser("demo", help="Run all algorithms")
    p.add_argument("--seed", type=int, default=42)

    # gates
    p = sub.add_parser("gates", help="List all available gates and verify unitarity")

    # bb84
    p = sub.add_parser("bb84", help="BB84 Quantum Key Distribution protocol")
    p.add_argument("--bits", type=int, default=200,
                   help="Number of qubits Alice sends (default: 200)")
    p.add_argument("--eavesdrop", action="store_true",
                   help="Simulate Eve intercepting the channel")
    p.add_argument("--seed", type=int, default=42)

    # superdense
    p = sub.add_parser("superdense", help="Superdense coding: 2 bits via 1 qubit")
    p.add_argument("message", help="2-bit message to encode, e.g. '10'")
    p.add_argument("--seed", type=int, default=42)

    args = parser.parse_args(argv)

    try:
        _dispatch(args)
    except (ValueError, TypeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _dispatch(args):
    cmd = args.cmd

    if cmd == "grover":
        _cmd_grover(args)
    elif cmd == "deutsch-jozsa":
        _cmd_dj(args)
    elif cmd == "bernstein-vazirani":
        _cmd_bv(args)
    elif cmd == "qft":
        _cmd_qft(args)
    elif cmd == "teleport":
        _cmd_teleport(args)
    elif cmd == "simon":
        _cmd_simon(args)
    elif cmd == "qpe":
        _cmd_qpe(args)
    elif cmd == "bell":
        _cmd_bell(args)
    elif cmd == "noise":
        _cmd_noise(args)
    elif cmd == "viz":
        _cmd_viz(args)
    elif cmd == "demo":
        _cmd_demo(args)
    elif cmd == "gates":
        _cmd_gates(args)
    elif cmd == "bb84":
        _cmd_bb84(args)
    elif cmd == "superdense":
        _cmd_superdense(args)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


# ------------------------------------------------------------------
# Command implementations
# ------------------------------------------------------------------

def _cmd_grover(args):
    from .algorithms import grover
    rng = random.Random(args.seed)
    marked = args.marked or [0]
    n = args.n
    print(f"\nGrover's Algorithm")
    print(f"  n = {n}  (search space = {1<<n} items)")
    print(f"  Marked items: {marked}")
    r = grover(n, marked, rng=rng)
    print(f"  Iterations: {r['iterations']}")
    print(f"  Theoretical success probability: {r['success_prob']:.4f}")
    print(f"  Circuit depth: {r['circuit'].depth()}, gates: {len(r['circuit'])}")
    print(f"\n  Result: |{r['result']}⟩ = item #{r['result_int']}")
    print(f"  Verified: {'✓ CORRECT' if r['verified'] else '✗ WRONG'}")
    _show_histogram(r['counts'], top_n=8, title="Shot histogram (top 8)")


def _cmd_dj(args):
    from .algorithms import deutsch_jozsa
    rng = random.Random(args.seed)
    n = args.n
    print(f"\nDeutsch-Jozsa Algorithm")
    print(f"  n = {n}  (classifying oracle f: {{0,1}}^{n} → {{0,1}})")
    print(f"  Oracle type: {args.oracle}")
    r = deutsch_jozsa(n, args.oracle, secret_bits=args.secret, rng=rng)
    print(f"  Measurement outcome: |{r['measurement']}⟩")
    print(f"  Conclusion: oracle is {r['result'].upper()}")
    print(f"  Verified: {'✓ CORRECT' if r['verified'] else '✗ WRONG'}")
    print(f"  Classical worst-case queries: {(1<<(n-1))+1}  (quantum: 1)")


def _cmd_bv(args):
    from .algorithms import bernstein_vazirani
    rng = random.Random(args.seed)
    s = args.secret
    print(f"\nBernstein-Vazirani Algorithm")
    print(f"  Hidden string: s = '{s}'  (n = {len(s)} bits)")
    r = bernstein_vazirani(s, rng=rng)
    print(f"  Recovered:     s = '{r['result']}'")
    print(f"  Verified: {'✓ CORRECT' if r['verified'] else '✗ WRONG'}")
    print(f"  Classical queries needed: {len(s)}  (quantum: 1)")


def _cmd_qft(args):
    from .algorithms import qft_circuit, verify_qft
    rng = random.Random(args.seed)
    n = args.n
    print(f"\nQuantum Fourier Transform (n = {n})")
    print(f"  N = 2^{n} = {1<<n} points")

    vr = verify_qft(n, rng=rng)
    print(f"  Unitarity verification vs exact DFT matrix:")
    print(f"    Max amplitude error: {vr['max_error']:.2e}")
    print(f"    Verified: {'✓ PASS' if vr['verified'] else '✗ FAIL'}")

    # Show QFT applied to a specific input
    from .state import QuantumState
    input_idx = args.input if args.input is not None else 1
    print(f"\n  Applying QFT to |{format(input_idx, f'0{n}b')}⟩:")
    qc = qft_circuit(n)
    init = QuantumState.from_basis(n, input_idx)
    result = qc.run(initial_state=init, shots=1, rng=rng)
    state = result.final_state
    print(f"  {state.dirac(max_terms=8)}")
    print(f"  Circuit: {len(qc)} gates, depth {qc.depth()}")


def _cmd_teleport(args):
    from .algorithms import teleportation
    from .state import QuantumState
    import cmath

    rng = random.Random(args.seed)
    state_map = {
        "superposition": QuantumState(1, [1/math.sqrt(2), 1j/math.sqrt(2)]),
        "plus":   QuantumState(1, [1/math.sqrt(2), 1/math.sqrt(2)]),
        "minus":  QuantumState(1, [1/math.sqrt(2), -1/math.sqrt(2)]),
        "zero":   QuantumState(1, [1, 0]),
        "one":    QuantumState(1, [0, 1]),
        "random": QuantumState(1, [complex(rng.gauss(0,1), rng.gauss(0,1)),
                                   complex(rng.gauss(0,1), rng.gauss(0,1))]).normalize(),
    }
    psi = state_map[args.state]

    print(f"\nQuantum Teleportation")
    print(f"  Teleporting state: {psi.dirac()}")

    fidelities = []
    for trial in range(args.trials):
        r = teleportation(psi, rng=rng)
        fidelities.append(r['fidelity'])

    avg_f = sum(fidelities) / len(fidelities)
    min_f = min(fidelities)
    print(f"  Trials: {args.trials}")
    print(f"  Average fidelity: {avg_f:.8f}")
    print(f"  Min fidelity:     {min_f:.8f}")
    print(f"  Verified: {'✓ PASS (F > 0.9999)' if min_f > 0.9999 else '✗ FAIL'}")
    print(f"  (2 classical bits + 1 ebit = complete quantum state transfer)")


def _cmd_simon(args):
    from .algorithms import simon
    rng = random.Random(args.seed)
    n = args.n
    period = args.period
    print(f"\nSimon's Period-Finding Algorithm (n = {n})")
    if period:
        print(f"  True period: s = '{period}'")
    else:
        print(f"  True period: s = (random)")
    r = simon(n, period, rng=rng)
    print(f"  True period:  s = '{r['true_period']}'")
    print(f"  Found period: s = '{r['period']}'")
    print(f"  Quantum queries used: {r['queries']}  (classical: O(2^{n//2}) = {(1<<(n//2))})")
    print(f"  Linear equations collected: {len(r['samples'])}")
    print(f"  Verified: {'✓ CORRECT' if r['verified'] else '✗ WRONG'}")


def _cmd_qpe(args):
    from .algorithms import quantum_phase_estimation
    rng = random.Random(args.seed)
    phase = args.phase
    n = args.n_count
    phase_normalized = phase % 1.0
    print(f"\nQuantum Phase Estimation")
    print(f"  Input phase:     φ = {phase:.6f}  (mod 1 → {phase_normalized:.6f})")
    print(f"  True phase:     φ = {phase_normalized:.6f}")
    print(f"  Counting qubits: {n}  (precision = 1/{1<<n} = {1/(1<<n):.4f})")
    phase = phase_normalized
    r = quantum_phase_estimation(n, phase, rng=rng)
    print(f"  Estimated phase: φ̂ = {r['estimated_phase']:.6f}")
    print(f"  Error: {r['error']:.2e}  (target < 1/{1<<n} = {1/(1<<n):.4f})")
    print(f"  Measurement: |{r['measurement']}⟩")
    print(f"  Verified: {'✓ PASS' if r['verified'] else '✗ FAIL'}")
    _show_histogram(r['counts'], top_n=5, title="Top outcomes")


def _cmd_bell(args):
    from .circuit import Circuit
    from .measure import sample

    rng = random.Random(args.seed)
    state_name = args.state
    print(f"\nBell State: |{state_name}⟩")

    # Build Bell state circuit
    qc = Circuit(2, 2, name=f"Bell|{state_name}⟩")
    qc.h(0)
    qc.cnot(0, 1)
    if state_name == "phi-":
        qc.z(0)
    elif state_name == "psi+":
        qc.x(1)
    elif state_name == "psi-":
        qc.x(1)
        qc.z(0)

    result = qc.run(shots=1, rng=rng)
    state = result.final_state
    print(f"  State vector: {state.dirac()}")

    # Correlations
    from .measure import expectation_value
    zz = (sum(abs(state._amp[i])**2 * (1 if bin(i).count('1') % 2 == 0 else -1)
              for i in range(4)))
    print(f"  ⟨ZZ⟩ correlation: {zz:.4f}  (expect {-1 if 'psi' in state_name else 1:.0f})")

    # Multi-shot sampling
    counts = sample(state, args.shots, rng=rng)
    print(f"\n  {args.shots}-shot measurement histogram:")
    _show_histogram(counts)

    # Verify Bell inequality violation
    print(f"\n  Entanglement entropy S(qubit 0): "
          f"{state.entanglement_entropy([0]):.4f} bits  (max log(2) = {math.log(2):.4f})")

    print(f"\n  Circuit:")
    from .visualize import circuit_to_ascii
    print(circuit_to_ascii(qc))


def _cmd_noise(args):
    from .circuit import Circuit
    from .noise import (NoiseModel, depolarizing_channel, bit_flip_channel,
                        phase_flip_channel, amplitude_damping_channel,
                        phase_damping_channel)
    from .state import QuantumState

    rng = random.Random(args.seed)
    p = args.p
    shots = args.shots

    print(f"\nNoise Channel Demo")
    print(f"  Channel: {args.channel}  (p = {p})")
    print(f"  Shots: {shots}")

    # Circuit: prepare |+⟩ state (equal superposition), then measure
    qc = Circuit(1, 1, name="noise-demo")
    qc.h(0)
    qc.measure(0, 0)

    # Without noise
    r_ideal = qc.run(shots=shots, rng=random.Random(args.seed))
    print(f"\n  Ideal (no noise): P(0) = {r_ideal.counts.get('0',0)/shots:.4f}, "
          f"P(1) = {r_ideal.counts.get('1',0)/shots:.4f}")

    # With noise
    channel_map = {
        "depolarizing":  NoiseModel.depolarizing(p),
        "bit_flip":      NoiseModel.bit_flip(p),
        "phase_flip":    NoiseModel().__class__(),  # phase flip doesn't affect |+⟩ in Z-basis
        "amplitude_damping": None,
        "phase_damping": None,
        "thermal":       NoiseModel.thermal(p, p * 0.5),
    }

    if args.channel == "phase_flip":
        nm = NoiseModel()
        from .noise import phase_flip_channel as pfc
        nm.add_all_qubit_channel(pfc(p))
    elif args.channel == "amplitude_damping":
        nm = NoiseModel()
        nm.add_all_qubit_channel(amplitude_damping_channel(p))
    elif args.channel == "phase_damping":
        nm = NoiseModel()
        nm.add_all_qubit_channel(phase_damping_channel(p))
    else:
        nm = channel_map[args.channel]

    r_noisy = qc.run(shots=shots, rng=random.Random(args.seed), noise_model=nm)
    p0 = r_noisy.counts.get('0', 0) / shots
    p1 = r_noisy.counts.get('1', 0) / shots
    print(f"  Noisy  (p={p}): P(0) = {p0:.4f}, P(1) = {p1:.4f}")
    print(f"\n  Theoretical prediction:")
    _print_noise_theory(args.channel, p)


def _print_noise_theory(channel: str, p: float):
    """Print analytical predictions for the noise channel."""
    # For |+⟩ state, ideal measurement gives P(0) = P(1) = 0.5
    if channel == "depolarizing":
        p0 = 0.5
        print(f"    Depolarizing on |+⟩: P(0) = P(1) = 0.5 (uniform — depolarizing "
              f"preserves the Z-basis statistics of |+⟩)")
    elif channel == "bit_flip":
        print(f"    Bit-flip on |+⟩: P(0) = P(1) = 0.5  (|+⟩ is invariant under X)")
    elif channel == "phase_flip":
        print(f"    Phase-flip on |+⟩: maps |+⟩→|−⟩ with prob {p:.2f} → both give P=0.5 in Z-basis")
    elif channel == "amplitude_damping":
        p0 = 0.5 + 0.5 * math.sqrt(1 - p)
        print(f"    Amplitude damping: P(0) → {p0:.4f}  (state decays toward |0⟩)")
    elif channel == "phase_damping":
        print(f"    Phase damping: P(0) = P(1) = 0.5  (no population change)")
    elif channel == "thermal":
        print(f"    Thermal (T1+T2): P(0) > 0.5  (amplitude decay dominates)")


def _cmd_viz(args):
    from .algorithms import (grover, deutsch_jozsa, bernstein_vazirani,
                              qft_circuit, teleportation, quantum_phase_estimation)
    from .circuit import Circuit
    from .state import QuantumState
    from .visualize import build_html

    rng = random.Random(args.seed)
    alg = args.algorithm

    print(f"\nGenerating HTML visualizer for: {alg}")

    if alg == "grover":
        r = grover(3, [5], rng=rng)
        circuit = r['circuit']
        # Run to get final state
        result = circuit.run(shots=1, rng=rng)
    elif alg == "dj":
        r = deutsch_jozsa(3, "balanced", rng=rng)
        circuit = r['circuit']
        result = circuit.run(shots=1, rng=rng)
    elif alg == "bv":
        r = bernstein_vazirani("101", rng=rng)
        circuit = r['circuit']
        result = circuit.run(shots=1, rng=rng)
    elif alg == "qft":
        circuit = qft_circuit(3)
        init = QuantumState.from_basis(3, 1)
        result = circuit.run(initial_state=init, shots=1, rng=rng)
    elif alg == "bell":
        circuit = Circuit(2, 0, name="Bell|φ+⟩")
        circuit.h(0)
        circuit.cnot(0, 1)
        result = circuit.run(shots=1, rng=rng)
    elif alg == "qpe":
        r = quantum_phase_estimation(4, 0.375, rng=rng)
        circuit = r['circuit']
        result = circuit.run(shots=256, rng=rng)
    else:
        circuit = Circuit(2, name="teleport-prep")
        circuit.h(0)
        circuit.cnot(0, 1)
        result = circuit.run(shots=1, rng=rng)

    html = build_html(circuit, result, title=f"QSim — {alg}")
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Written to: {args.output}")
    print(f"  Open in a browser to explore the circuit interactively.")


def _cmd_demo(args):
    from .algorithms import (grover, deutsch_jozsa, bernstein_vazirani,
                              verify_qft, teleportation, simon,
                              quantum_phase_estimation, bb84, superdense_coding)

    rng = random.Random(args.seed)
    print("=" * 60)
    print(" QSim — Quantum Algorithm Demo Suite")
    print("=" * 60)

    results = {}

    # 1. Deutsch-Jozsa
    print("\n[1/9] Deutsch-Jozsa (n=4, balanced oracle)")
    r = deutsch_jozsa(4, "balanced", rng=random.Random(args.seed))
    results["dj"] = r['verified']
    print(f"  Result: {r['result'].upper()}  |  Verified: {'✓' if r['verified'] else '✗'}")

    # 2. Bernstein-Vazirani
    print("\n[2/9] Bernstein-Vazirani (secret = '10110')")
    r = bernstein_vazirani("10110", rng=random.Random(args.seed))
    results["bv"] = r['verified']
    print(f"  Recovered: '{r['result']}'  |  Verified: {'✓' if r['verified'] else '✗'}")

    # 3. Grover (n=4, marked=[7])
    print("\n[3/9] Grover's Search (n=4, searching for item 7 among 16)")
    r = grover(4, [7], rng=random.Random(args.seed))
    results["grover"] = r['verified']
    print(f"  Found: item {r['result_int']}  |  Iterations: {r['iterations']}  |"
          f"  Verified: {'✓' if r['verified'] else '✗'}")

    # 4. Grover (multiple targets)
    print("\n[4/9] Grover's Search (n=4, 3 targets [2,8,13])")
    r = grover(4, [2, 8, 13], rng=random.Random(args.seed))
    results["grover_multi"] = r['verified']
    print(f"  Found: item {r['result_int']}  |  Verified: {'✓' if r['verified'] else '✗'}")

    # 5. QFT
    print("\n[5/9] Quantum Fourier Transform (n=4)")
    r = verify_qft(4, rng=random.Random(args.seed))
    results["qft"] = r['verified']
    print(f"  Max error vs DFT matrix: {r['max_error']:.2e}  |  Verified: {'✓' if r['verified'] else '✗'}")

    # 6. Teleportation
    print("\n[6/9] Quantum Teleportation (20 trials)")
    from .state import QuantumState
    psi = QuantumState(1, [1/math.sqrt(2), 1j/math.sqrt(2)])
    fidelities = [teleportation(psi, rng=random.Random(args.seed + i))['fidelity']
                  for i in range(20)]
    avg_f = sum(fidelities) / len(fidelities)
    results["teleport"] = all(f > 0.9999 for f in fidelities)
    print(f"  Average fidelity: {avg_f:.8f}  |  Verified: {'✓' if results['teleport'] else '✗'}")

    # 7. Simon's
    print("\n[7/9] Simon's Algorithm (n=3, period='101')")
    r = simon(3, "101", rng=random.Random(args.seed))
    results["simon"] = r['verified']
    print(f"  Period found: '{r['period']}'  |  Queries: {r['queries']}  |"
          f"  Verified: {'✓' if r['verified'] else '✗'}")

    # 8. BB84 QKD
    print("\n[8/9] BB84 QKD (200 qubits, no Eve)")
    r = bb84(200, eavesdrop=False, rng=random.Random(args.seed))
    results["bb84"] = r['key_match'] and not r['eavesdrop_detected']
    print(f"  Sifted: {r['sifted_length']} bits  |  QBER: {r['qber']:.3f}  |"
          f"  Key: {r['secure_key_length']} bits  |  Verified: {'✓' if results['bb84'] else '✗'}")

    # 9. Superdense Coding (all 4 messages)
    print("\n[9/9] Superdense Coding (all 4 messages)")
    msgs = ["00", "01", "10", "11"]
    sdc_ok = all(superdense_coding(m, rng=random.Random(args.seed))['verified'] for m in msgs)
    results["superdense"] = sdc_ok
    print(f"  Messages 00,01,10,11 decoded correctly  |  Verified: {'✓' if sdc_ok else '✗'}")

    print("\n" + "=" * 60)
    n_pass = sum(results.values())
    n_total = len(results)
    print(f" SUMMARY: {n_pass}/{n_total} algorithms verified correct")
    for name, ok in results.items():
        print(f"   {'✓' if ok else '✗'} {name}")
    print("=" * 60)

    if n_pass == n_total:
        return 0
    else:
        sys.exit(1)


def _cmd_gates(args):
    from .gates import GATES, Rx, Ry, Rz, Phase, U
    import math
    print("\nQSim Gate Library")
    print(f"{'Name':<20} {'Qubits':<8} {'Unitary?':<10}")
    print("─" * 40)
    all_gates = dict(GATES)
    # Add parameterized samples
    all_gates["Rx(π/2)"] = Rx(math.pi/2)
    all_gates["Ry(π/4)"] = Ry(math.pi/4)
    all_gates["Rz(π/3)"] = Rz(math.pi/3)
    all_gates["P(π/8)"] = Phase(math.pi/8)
    all_gates["U(π/2,π/4,π/8)"] = U(math.pi/2, math.pi/4, math.pi/8)
    for name, g in sorted(all_gates.items(), key=lambda x: (x[1].n_qubits, x[0])):
        ok = "✓" if g.is_unitary() else "✗"
        print(f"  {name:<18} {g.n_qubits:<8} {ok}")
    print(f"\n  Total: {len(all_gates)} gates")


def _cmd_bb84(args):
    from .algorithms import bb84
    rng = random.Random(args.seed)
    eve_label = "WITH eavesdropping (Eve)" if args.eavesdrop else "No eavesdropping"
    print(f"\nBB84 Quantum Key Distribution")
    print(f"  Qubits sent:   {args.bits}")
    print(f"  Channel:       {eve_label}")
    r = bb84(args.bits, eavesdrop=args.eavesdrop, rng=rng)
    print(f"  Sifted key length:  {r['sifted_length']} bits  "
          f"(~{r['sifted_length']/args.bits*100:.0f}% of raw bits)")
    print(f"  Test bits used:     {r['n_test_bits']}")
    print(f"  QBER:               {r['qber']:.3f}  "
          f"(threshold = 0.11; {'>= means Eve detected' if r['qber'] >= 0.11 else 'secure'})")
    print(f"  Eavesdrop detected: {'YES ⚠' if r['eavesdrop_detected'] else 'NO ✓'}")
    print(f"  Secure key length:  {r['secure_key_length']} bits")
    print(f"  Keys match:         {'✓' if r['key_match'] else '✗'}")
    if r['secure_key_length'] > 0:
        display = r['alice_key'][:32]
        if len(r['alice_key']) > 32:
            display += f"... ({len(r['alice_key'])} bits total)"
        print(f"  Alice's key:        {display}")
    print(f"\n  BB84 summary: {r['sifted_length']} sifted → {r['secure_key_length']} secure bits "
          f"({r['qber']*100:.1f}% QBER)")


def _cmd_superdense(args):
    from .algorithms import superdense_coding
    from .visualize import circuit_to_ascii
    rng = random.Random(args.seed)
    msg = args.message
    print(f"\nSuperdense Coding")
    print(f"  Encoding message: '{msg}'  (2 classical bits)")
    print(f"  Protocol: Alice encodes via local gates on shared Bell pair,")
    print(f"            Bob decodes with CNOT + H + measurement")
    r = superdense_coding(msg, rng=rng)
    print(f"  Decoded:  '{r['decoded']}'")
    print(f"  Verified: {'✓ CORRECT' if r['verified'] else '✗ WRONG'}")
    print(f"  Efficiency: 2 bits transmitted using 1 qubit + 1 ebit")
    print(f"\n  Circuit:")
    print(circuit_to_ascii(r['circuit']))


def _show_histogram(counts: dict, top_n: int = 10, title: str = ""):
    if not counts:
        return
    if title:
        print(f"\n  {title}:")
    total = sum(counts.values())
    for k, v in sorted(counts.items(), key=lambda x: -x[1])[:top_n]:
        pct = v / total * 100
        bar = "█" * int(pct / 2)
        print(f"    |{k}⟩  {bar:<25} {pct:5.1f}%  ({v})")


if __name__ == "__main__":
    main()
