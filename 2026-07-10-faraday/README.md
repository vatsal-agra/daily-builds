# Faraday

A SPICE-like analog circuit simulator, built from scratch in pure Python —
real Modified Nodal Analysis, a hand-rolled LU solver, Newton-Raphson
nonlinear iteration, and backward-Euler transient stepping.

**Status: Phase 2 (core build) complete.** All 4 required features are
implemented and passing hand-verified analytic-oracle spot checks:

- DC operating-point solver (voltage dividers, multi-node resistor meshes)
- Transient analysis (RC charge curve and RL current-rise curve both match
  the closed-form exponential to ~1e-3 relative error at dt=1µs)
- Nonlinear diode via Newton-Raphson (half-wave rectifier clips correctly)
- Interactive server-backed browser UI (`faraday serve`) — component table
  editor, live schematic view, DC/transient/AC results with real charts

Stretch features (AC/Bode sweep, ideal op-amp) are also implemented and
already spot-checked (RLC resonance, inverting/non-inverting op-amp gains).

See [PLAN.md](PLAN.md) for the full concept and architecture. Adversarial
review, polish, the full test suite, and final docs are still to come.

## Quick look

```
pip install -e .  # or just: python3 -m faraday.cli ...  from this folder
python3 -m faraday.cli dc voltage_divider
python3 -m faraday.cli tran rc_step --tstop 5m --dt 1u --uic
python3 -m faraday.cli ac rc_lowpass --fstart 1 --fstop 1meg
python3 -m faraday.cli serve   # then open http://127.0.0.1:8765/
```
