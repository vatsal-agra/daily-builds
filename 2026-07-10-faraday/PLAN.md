# Faraday — a SPICE-like analog circuit simulator, from scratch

## Concept

Every "from scratch" build in this repo's history has picked a domain —
languages, renderers, codecs, crypto, databases, VCS — and reimplemented its
real algorithm from first principles. Analog circuit simulation (SPICE) has
never been touched, and it's a great fit: a genuinely different kind of math
(sparse linear algebra + nonlinear Newton-Raphson + numerical ODE
discretization) with hard, checkable ground truth — an RC charge curve has a
*closed-form* analytic answer, so correctness isn't "looks plausible," it's
"matches `V0*(1-e^(-t/RC))` to 6 decimal places."

Faraday builds the actual algorithm every SPICE-family simulator (ngspice,
LTspice, PSpice) is built on: **Modified Nodal Analysis (MNA)**. Circuit
elements are "stamped" into a conductance matrix and RHS vector; solving the
linear system gives every node voltage and source current at once. Reactive
elements (capacitors, inductors) become resistor-like *companion models* via
backward-Euler discretization for transient analysis; nonlinear elements
(diodes) are linearized per-iteration via Newton-Raphson; AC analysis reuses
the exact same stamping code with complex-valued impedances (Python's native
`complex` type) instead of real ones.

## Why it's interesting

- A totally unexplored domain for this repo (no renderer, no compiler, no
  crypto primitive — real analog physics and numerical methods).
- Extremely strong, cheap-to-compute ground truth: exponential RC/RL decay,
  LC resonant frequency, voltage-divider ratios, and ideal op-amp gain
  formulas are all textbook closed-form — a perfect oracle for adversarial
  testing, the same rigor this repo's SAT solvers and perft-verified chess
  engines had.
- One core numerical primitive (LU decomposition with partial pivoting,
  written generically over Python's `float` *and* `complex`) powers DC,
  transient, *and* AC analysis — elegant reuse instead of three engines.
- Produces genuinely useful output: real oscilloscope-style waveforms and
  Bode plots for real circuits (RC filters, rectifiers, op-amp amplifiers).

## Architecture

```
faraday/
  linalg.py     — generic LU decomposition + solve (partial pivoting; works
                  over float and complex without change)
  elements.py   — circuit element dataclasses (R, C, L, V, I, Diode, OpAmp)
  netlist.py    — tiny SPICE-like text netlist parser/serializer
  mna.py        — node numbering + MNA matrix "stamps" per element type
  dc.py         — DC operating-point solver (Newton-Raphson for diodes)
  transient.py  — time-stepped transient solver (backward-Euler companion
                  models for C/L, re-linearizing diodes every step)
  ac.py         — complex-phasor small-signal AC frequency sweep
  circuits.py   — library of preset circuits (RC/RL/RLC, rectifier, op-amp
                  amplifiers, oscillator) used by demos/tests
  server.py     — stdlib http.server backend: JSON API that accepts a
                  netlist + analysis request and returns waveform data
  cli.py        — `faraday dc|tran|ac|netlist|serve|demo` CLI
static/
  index.html    — interactive schematic builder + oscilloscope/Bode viewer
                  (server-backed: the browser holds no circuit-solving
                  logic, every simulation is a real call into the Python
                  MNA engine — same pattern as this repo's Gambit/Formulate)
tests/
  test_faraday.py — unit + analytic-oracle test suite
demo.sh
```

## Feature list

### Required (must fully work end-to-end)

1. **MNA engine + DC operating-point solver** — node stamping for
   resistors, independent V/I sources, and a from-scratch generic LU solver
   (partial pivoting). Verified against hand-solved voltage dividers and
   Kirchhoff's current/voltage laws on multi-node resistor networks.

2. **Transient analysis via backward-Euler companion models** — capacitors
   and inductors become per-timestep Norton/branch companion elements;
   stepping produces real waveforms. Verified against the closed-form RC
   charge/discharge exponential and RL current-rise curve (numeric fit
   against the analytic formula, not just "looks like a curve").

3. **Nonlinear elements via Newton-Raphson** — a real Shockley-equation
   diode, re-linearized (conductance + equivalent current source) every
   Newton iteration inside both DC and transient solves. Verified with a
   half-wave rectifier circuit and diode I-V curve sanity checks.

4. **Interactive circuit builder + oscilloscope UI** — a server-backed
   browser app (stdlib `http.server`, zero client-side circuit math):
   place components on a grid, wire them, hit simulate, see real waveforms
   plotted from the actual Python MNA solve.

### Stretch (2+, ship at least 1 fully)

5. **AC small-signal analysis / Bode plots** — complex-phasor MNA sweep
   across frequency, magnitude+phase output. Verified against the analytic
   RC low-pass cutoff frequency `f_c = 1/(2πRC)` and RLC resonance
   `f_0 = 1/(2π√LC)`.

6. **Ideal op-amp support** (virtual-short constraint via an extra MNA
   unknown/equation, not a finite-gain approximation) — enables inverting
   and non-inverting amplifier circuits, verified against the textbook
   `-Rf/Rin` and `1+Rf/Rin` closed-form gains.

7. **SPICE-like netlist import/export** — a tiny textual netlist language
   (`R1 1 0 1k`, `V1 1 0 DC 5`, etc.) plus a preset circuit library, so
   circuits can be described as text, not just drawn.

## Verification strategy

Every numeric feature gets an *independent analytic oracle*, not just
"doesn't crash": exponential decay time constants, resonant frequencies,
voltage-divider ratios, op-amp gain formulas, and Kirchhoff's laws (sum of
currents into any node ≈ 0 given the solved voltages) are all checked to
tight numeric tolerance. This is the same "differential/analytic oracle"
discipline this repo's SAT solvers, chess perft counts, and physics engines
used.
