# Faraday

A SPICE-like analog circuit simulator, built from scratch in pure Python —
real Modified Nodal Analysis, a hand-rolled LU solver, Newton-Raphson
nonlinear iteration, and backward-Euler transient stepping.

**Status: Phase 3 (adversarial review) complete.** All 4 required + both
stretch features are implemented and passing analytic-oracle checks. A
dedicated hostile-review pass (see [REVIEW.md](REVIEW.md)) found and fixed
8 real issues, the worst being a bug that broke the AC/Bode view for every
circuit and one that silently dropped a preset's waveform on export — both
confirmed fixed and re-verified against the same repro scripts that found
them.

- DC operating-point solver (voltage dividers, multi-node resistor meshes)
- Transient analysis (RC charge curve and RL current-rise curve both match
  the closed-form exponential to ~1e-3 relative error at dt=1µs)
- Nonlinear diode via Newton-Raphson (half-wave rectifier clips correctly)
- Interactive server-backed browser UI (`faraday serve`) — component table
  editor, live schematic view, DC/transient/AC results with real charts
- AC small-signal Bode sweep (RLC resonance, RC cutoff both verified)
- Ideal op-amp (inverting/non-inverting gains match `-Rf/Rin` / `1+Rf/Rin`)

See [PLAN.md](PLAN.md) for the full concept and architecture. Polish, the
full automated test suite, and final docs are still to come.

## Quick look

```
python3 -m faraday.cli dc voltage_divider
python3 -m faraday.cli tran rc_step --tstop 5m --dt 1u --uic
python3 -m faraday.cli ac rc_lowpass --fstart 1 --fstop 1meg
python3 -m faraday.cli serve   # then open http://127.0.0.1:8765/
```
