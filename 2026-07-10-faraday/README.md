# Faraday

A SPICE-like analog circuit simulator, built from scratch in pure Python —
real Modified Nodal Analysis, a hand-rolled LU solver, Newton-Raphson
nonlinear iteration, and backward-Euler transient stepping.

**Status: Phase 5 (verification) complete.** All 4 required + both stretch
features are implemented, polished, and verified two ways: a 48-test
`unittest` suite (analytic oracles, HTTP API tests against a real running
server, netlist round-trips) and `demo.sh`, a from-scratch shell walkthrough
that runs the suite, a self-checking analytic-oracle demo, every CLI
subcommand against real preset circuits (writing and measuring full CSV
output, not spot-checking a few rows), CLI error paths, and a live HTTP
server + JSON API exercise — all green. See [REVIEW.md](REVIEW.md) for the
adversarial-review findings (8 issues, Phase 3) plus one more genuine bug
`demo.sh` itself caught during Phase 5 (a `--uic` transient run could crash
the CSV writer on any capacitor-bearing circuit) — both rounds fixed and
re-verified against the scripts that found them.

- DC operating-point solver (voltage dividers, multi-node resistor meshes)
- Transient analysis (RC charge curve and RL current-rise curve both match
  the closed-form exponential to ~1e-3 relative error at dt=1µs)
- Nonlinear diode via Newton-Raphson (half-wave rectifier clips correctly)
- Interactive server-backed browser UI (`faraday serve`) — component table
  editor, live schematic view, DC/transient/AC results with real charts
- AC small-signal Bode sweep (RLC resonance, RC cutoff both verified)
- Ideal op-amp (inverting/non-inverting gains match `-Rf/Rin` / `1+Rf/Rin`)

See [PLAN.md](PLAN.md) for the full concept and architecture. Final,
complete documentation (Phase 6) is still to come.

## Quick look

```
python3 -m faraday.cli dc voltage_divider
python3 -m faraday.cli tran rc_step --tstop 5m --dt 1u --uic
python3 -m faraday.cli ac rc_lowpass --fstart 1 --fstop 1meg
python3 -m faraday.cli serve   # then open http://127.0.0.1:8765/
./demo.sh                      # full verification: tests + demo + CLI + server
```
