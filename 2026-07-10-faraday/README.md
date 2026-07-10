# Faraday

A SPICE-like analog circuit simulator, built entirely from scratch in pure
Python: real Modified Nodal Analysis (MNA), a hand-rolled generic LU solver,
Newton-Raphson nonlinear iteration for diodes, backward-Euler transient
stepping, and complex-phasor AC small-signal analysis — the same core
algorithm every SPICE-family simulator (ngspice, LTspice, PSpice) is built
on, driving both a CLI and a real interactive browser UI.

**Status: shipped.** All 4 required features plus both stretch features are
implemented, adversarially reviewed, polished, and verified (48-test
`unittest` suite + `demo.sh`, all green).

## What it is

Circuit elements (resistors, capacitors, inductors, sources, diodes, ideal
op-amps) are "stamped" into a matrix equation `A x = z`, where `x` is every
node voltage and source/branch current in the circuit at once. Solving that
one linear system gives the entire operating point — no per-node
elimination, no simplification rules, just linear algebra:

- **DC operating point** — capacitors open, inductors shorted, solve once.
- **Transient (time-domain)** — capacitors/inductors become per-timestep
  backward-Euler *companion models* (a resistor-like conductance plus a
  term carrying the previous timestep's state); solving at each step and
  advancing the state produces a real waveform.
- **AC small-signal** — the exact same stamping code, but capacitor/inductor
  impedance is `1/(jωC)` / `jωL` (Python's native `complex` type — no
  separate complex-math implementation needed) and the linear system is
  solved once per frequency, sweeping out a Bode plot.
- **Nonlinear elements (diodes)** — Newton-Raphson: linearize the diode's
  Shockley-equation I-V curve at a guessed voltage, solve the linear system,
  update the guess (with SPICE-style critical-voltage damping so the guess
  can't blow up `exp()`), repeat until it converges.

One `linalg.solve()` (Gaussian elimination with partial pivoting, written
generically over Python `float` *and* `complex`) powers all three analyses.

## Why this, today

Every previous build in this repo picked a well-worn "from scratch" genre —
languages, renderers, codecs, crypto primitives, databases, VCS, chess
engines. Analog circuit simulation had never been touched, and it's a great
fit for the same discipline this repo's SAT solvers and perft-verified
chess engines used: **the correctness bar is a closed-form answer, not "does
it look plausible."** An RC charge curve has an exact formula
(`V0*(1-e^(-t/RC))`); an RLC circuit resonates at exactly
`1/(2π√LC)`; an ideal op-amp's gain is exactly `-Rf/Rin`. Every numeric
feature here is checked against one of those formulas, not eyeballed.

## Quick look

```bash
python3 -m faraday.cli dc voltage_divider
python3 -m faraday.cli tran rc_step --tstop 5m --dt 1u --uic
python3 -m faraday.cli ac rc_lowpass --fstart 1 --fstop 1meg
python3 -m faraday.cli serve            # then open http://127.0.0.1:8765/
./demo.sh                               # full verification: tests + demo + CLI + server
python3 -m unittest discover -s tests   # just the unit tests
```

No dependencies beyond the Python 3 standard library.

### A netlist, by hand

```
* RC low-pass filter
V1 in 0 DC 0 AC 1
R1 in out 1k
C1 out 0 100n
```
```bash
python3 -m faraday.cli ac my_filter.cir --fstart 1 --fstop 1meg
```

## Feature list

**Required:**

1. **MNA engine + DC operating-point solver** (`mna.py`, `dc.py`,
   `linalg.py`) — node/branch unknown numbering, per-element matrix
   stamping, a from-scratch generic LU solver. Verified against hand-solved
   voltage dividers and Kirchhoff's Current Law on a 5-resistor mesh.
2. **Transient analysis via backward-Euler companion models**
   (`transient.py`) — real time-domain waveforms. Verified against the
   closed-form RC charge and RL current-rise exponentials.
3. **Nonlinear elements via Newton-Raphson** (`elements.py`'s `Diode`,
   re-linearized every iteration in `dc.py`) — a real Shockley-equation
   diode with SPICE-style voltage-step damping and GMIN regularization.
   Verified with a half-wave rectifier.
4. **Interactive circuit builder + oscilloscope UI** (`server.py` +
   `static/index.html`) — a component-table/netlist-text editor, a
   node-rail schematic visualization, and DC/transient/AC results rendered
   as real charts, all backed by the actual Python engine over a JSON API
   (zero circuit math in the browser — every "Simulate" click is a real
   round trip).

**Stretch (both shipped):**

5. **AC small-signal analysis / Bode plots** (`ac.py`) — complex-phasor MNA
   sweep. Verified against the analytic RC cutoff `f_c=1/(2πRC)` and RLC
   resonance `f_0=1/(2π√LC)`.
6. **Ideal op-amp** (`elements.py`'s `OpAmp`, the nullor/virtual-short
   stamp in `mna.py`) — enables inverting/non-inverting amplifiers.
   Verified against the textbook `-Rf/Rin` and `1+Rf/Rin` gain formulas.

**Also included:** a tiny SPICE-like textual netlist format (`netlist.py`)
with engineering-suffix parsing (`1k`, `4.7u`, `10meg`, ...), PULSE/SIN
sources, import/export, and a 9-circuit preset library (`circuits.py`).

## Project layout

```
faraday/
  linalg.py     generic LU solver (float and complex)
  elements.py   R, C, L, V, I, Diode, OpAmp dataclasses
  netlist.py    SPICE-like text format: parse + serialize
  mna.py        node/branch numbering + per-element matrix "stamps"
  dc.py         DC operating point + shared Newton-Raphson driver
  transient.py  backward-Euler time-stepping
  ac.py         complex-phasor frequency sweep
  circuits.py   preset circuit library
  server.py     stdlib http.server JSON API backend
  cli.py        `faraday dc|tran|ac|netlist|list-presets|serve|demo`
  demo.py       self-checking end-to-end walkthrough (`faraday demo`)
static/index.html   interactive browser UI (dark theme, real charts)
tests/test_faraday.py   48-test unittest suite
demo.sh             full shell-level verification pass
PLAN.md / REVIEW.md the day's plan and adversarial-review findings
```

## Verification

- `python3 -m unittest discover -s tests` — 48 tests: linear-algebra
  correctness (hand-solved + 30 randomized diagonally-dominant systems +
  complex-valued solves), DC (voltage dividers at multiple ratios, KCL on a
  resistor mesh, floating-node detection), transient (RC charge/discharge,
  RL rise, all against closed forms; `dt>t_stop` and negative-value
  rejection), diode (Shockley curve monotonicity, rectifier clipping,
  reverse-bias GMIN regularization, bad-parameter rejection), AC (RC
  cutoff, RLC resonance, diode-in-AC rejection, no-`Infinity`-in-JSON), ideal
  op-amp (parametrized inverting/non-inverting gain, a unity buffer), netlist
  (value-suffix parsing, round-trip through every preset including
  PULSE/SIN sources, malformed-input error messages), and a live HTTP
  server (every route, both success and error paths).
- `./demo.sh` — the unit suite, the self-checking `faraday demo` walkthrough,
  every CLI subcommand run against real presets (writing and *measuring* a
  full ~2000-row transient CSV, not spot-checking a few rows — this is
  exactly what caught the Phase 5 bug in REVIEW.md), CLI error paths, and a
  live server + JSON API exercise.
- The UI was driven end-to-end in real headless Chromium (Playwright):
  loading presets, running all three analysis types, adding/deleting
  components, and triggering the empty-circuit error path — zero console
  errors.

## Known limitations (see REVIEW.md for the full list)

- The ideal op-amp has no output-voltage saturation/rail modeling (an
  unclamped nullor, like most simple SPICE-like teaching tools) — an
  unstable/open-loop topology reads as a singular matrix, not "railed."
- The browser's Component Table editor doesn't expose per-diode `IS`/`N` or
  per-source AC phase (only the Netlist Text tab can set those).
- No trapezoidal integration (backward-Euler only) — accurate but first-order;
  a stiffer/more oscillatory circuit needs a smaller `dt` than a trapezoidal
  solver would.

## Where a human could take this next

- **Trapezoidal (or variable-order) integration** for better transient
  accuracy at larger timesteps, plus adaptive timestep control (LTE
  estimation) instead of a fixed `dt`.
- **More elements**: BJTs/MOSFETs (Ebers-Moll / level-1 SPICE models — the
  Newton-Raphson machinery already here generalizes directly), mutual
  inductance/transformers, controlled sources (VCVS/VCCS/CCCS/CCVS)
  beyond the op-amp special case, real (non-ideal) op-amps with finite
  gain/bandwidth/rail limits.
- **A real routed schematic** (drag components, click-drag wires, junction
  dots) instead of the current node-rail visualization — a genuinely large
  undertaking (hit-testing, wire routing, connectivity inference from pixel
  positions) that was deliberately out of scope for one day.
- **Monte Carlo / worst-case analysis** — sweep component tolerances and
  show the resulting output distribution, using the same MNA solve in a
  tight loop.
- **SPICE-format compatibility** — the current netlist format is
  SPICE-*like*, not SPICE-*compatible*; parsing real `.cir`/`.sp` files
  (subcircuits, `.model` cards, more source types) would make it useful
  against real-world netlists instead of just this project's own presets.
