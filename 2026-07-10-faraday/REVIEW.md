# Adversarial review

Phase 3: attacking Faraday as a hostile reviewer, not just "does it run."
Everything below was reproduced with a concrete script before being called
a bug, and every issue was fixed and re-verified (see commands next to each
finding — all still pass after the fix).

> One bug was already caught and fixed *during* Phase 2 (the "each feature
> demonstrably works end-to-end" gate, not this dedicated adversarial pass):
> the inductor's backward-Euler companion model had the RHS sign backwards
> (`z[k] += zl * i_prev` instead of `-zl * i_prev`), discovered because the
> RL step-response test showed current barely rising instead of following
> the analytic curve. Fixed before the Phase 2 commit. Noted here for an
> honest record, not re-counted as a Phase 3 finding.

## Findings

1. **CRITICAL — AC Bode "Magnitude (dB)" is broken for every circuit, in
   every case.** `ACResult.magnitude_db()` computes `20*log10(abs(v))`
   with no floor. Ground (node `"0"`) is *always* present in every result
   (it's unconditionally seeded into `voltages` by `Circuit.unpack`) and is
   *always* exactly 0V, so `magnitude_db("0")` is `-inf` on every single
   AC sweep. `json.dumps` happily serializes Python's `-inf` as the bare
   token `-Infinity`, which is not legal JSON — `JSON.parse` (what
   `fetch(...).json()` uses in every browser) throws a `SyntaxError` on
   it. Every AC/Bode request from the UI would fail with an opaque parse
   error instead of rendering a plot.
   Repro: `python3 -c "from faraday import circuits, ac; import json;
   print(json.dumps(ac.sweep(circuits.rc_lowpass(),1,1e6,3).magnitude_db('0')))"`
   → prints `[-Infinity, -Infinity, -Infinity]`.
   **Fix:** floor `magnitude_db()` at a physically sane minimum (-300dB,
   the standard "digital silence" floor used in audio/RF tooling) instead
   of computing `log10(0)`.

2. **HIGH — the UI's most interesting demo circuit silently simulates
   nothing.** `netlist.to_netlist()` serializes `VSource`/`ISource` as
   `DC {dc_value} [AC {ac_mag}]` only — a `PULSE(...)`/`SIN(...)` waveform
   set via `VSource.pulse()`/`VSource.sine()` is dropped entirely, because
   the waveform is stored only as an opaque Python closure with no
   serializable description. This silently breaks the
   `half_wave_rectifier` preset: `GET /api/presets` returns
   `V1 in 0 DC 0` (its sine drive is gone), so loading that preset into
   the browser UI and running a transient shows a flat 0V line, not a
   rectified sine — the demo looks completely broken with no error at all.
   Repro: `python3 -c "from faraday import circuits, netlist;
   print(netlist.to_netlist(circuits.half_wave_rectifier().elements))"`
   → `V1 in 0 DC 0`.
   **Fix:** give `VSource`/`ISource` an explicit `spec` field
   (`("DC", ...)` / `("PULSE", (...))` / `("SIN", (...))`) set by the
   factory methods, and make `to_netlist()` serialize from `spec` instead
   of reconstructing a lossy approximation from `dc_value`.

3. **MEDIUM — reverse-biased diodes can underflow to a singular matrix.**
   `Diode.conductance(vd)` is `(Is/nVt) * exp(vd/nVt)`; at ordinary
   reverse-bias voltages (confirmed starting around -50V, not an exotic
   extreme) `exp()` underflows to exactly `0.0` in float64. If that diode
   is a node's *only* DC-connected path, its stamped conductance silently
   drops to true zero and the MNA matrix goes singular.
   Repro: `python3 -c "from faraday.elements import Diode;
   print(Diode('D1','a','b').conductance(-50.0))"` → `0.0`.
   **Fix:** stamp SPICE's standard `GMIN` (1e-12 S) in parallel with every
   diode, unconditionally — the same fix every real SPICE implementation
   uses for exactly this reason.

4. **MEDIUM — a zero/negative diode `Is` crashes with a raw traceback.**
   Every other element (`Resistor`, `Capacitor`, `Inductor`) validates its
   value is physically sensible in `__post_init__`; `Diode` validates
   nothing, so `Diode('D1','a','b',Is=0)` blows up with an uncaught
   `ZeroDivisionError` the moment `critical_voltage()` runs (`nVt / (sqrt2
   * Is)` divides by zero) — a raw Python traceback reaching the CLI/HTTP
   layer instead of a clean, actionable message.
   **Fix:** validate `Is > 0`, `n > 0`, `Vt > 0` in `Diode.__post_init__`,
   matching the existing convention on the other elements.

5. **MEDIUM — confusing error message on duplicate element names.**
   `Circuit._number_unknowns` checks for duplicate names among the
   V-source/inductor/op-amp "extra unknown" list *before* the general,
   name-specific duplicate check that runs later in the same method — so
   naming two op-amps both `"O1"` raises the generic
   `"duplicate element names among V/L/OpAmp branches"` instead of a
   message naming the actual offending element.
   **Fix:** run the specific, name-carrying check first.

6. **LOW — `dt > t_stop` silently returns almost nothing, with no error.**
   `transient.simulate` computes `n_steps = round(t_stop/dt)`; if `dt`
   is larger than `t_stop` this rounds to 0 and the function quietly
   returns just the single t=0 sample. From the CLI or UI this looks
   indistinguishable from "the simulation did nothing," with no
   indication the request itself was nonsensical.
   **Fix:** raise a clear `ValueError` instead of silently under-running.

7. **LOW (hardening) — no JSON safety net on the HTTP boundary.**
   Beyond finding #1, `server.py` had no general defense against a
   non-finite float (`inf`/`nan`, however it might arise — a pathological
   user-supplied component value, a stalled Newton iteration, etc.)
   reaching a JSON response and breaking `JSON.parse` client-side with an
   opaque syntax error instead of a readable message.
   **Fix:** sanitize every response through a recursive non-finite -> `null`
   pass before encoding.

8. **LOW (dead code) — an unreachable validation loop.**
   `Circuit._number_unknowns` ended with a loop re-scanning every element's
   node attributes and raising `AssertionError` if one wasn't registered —
   but the *same* attribute scan already ran earlier in the same method to
   build `node_index` in the first place, so this can never fire. Removed
   per "don't add error handling for scenarios that can't happen."

## Found during Phase 5 (verification), not this pass

9. **CRITICAL — `--uic` transient runs on any Capacitor could crash the
   CLI/server output writer.** `transient._initial_state`'s `use_ic=True`
   path builds a t=0 IC snapshot by substituting every `Capacitor` with a
   same-named `VSource` (a capacitor instantaneously held at a fixed
   voltage *is* a voltage source — see the docstring). But it then passed
   that snapshot's raw `currents` dict straight through: since the
   substitute VSource shares the capacitor's name, `currents` picked up a
   phantom one-sample-long series keyed by the *capacitor's* name (e.g.
   `"C1"`) that never appears again at any later timestep (real capacitors
   have no branch-current unknown once behind their normal MNA companion
   model). Every other series has one sample per timestep; this one had
   exactly one sample, period — a silent length mismatch that only
   surfaced as an `IndexError` deep in the CLI's CSV writer, on whichever
   row index first exceeded 1.
   Only caught because `demo.sh` writes and measures a *real* CSV file
   end-to-end (2000+ rows) instead of the earlier ad-hoc checks, which
   only ever sampled a handful of hand-picked timesteps and never noticed
   a 1-vs-2001-sample-long series. Every unit test written before this
   point was too — a good reminder that spot-checks and a real
   full-length run catch different bugs.
   **Fix:** rebuild `currents` explicitly from the *original* circuit's
   real branch-bearing elements (`VSource`/`OpAmp` pass straight through
   unaffected by the substitution; `Inductor` uses its `ic` directly)
   instead of trusting the substitute circuit's raw current dict. Added a
   regression test that runs every preset through `--uic` and asserts
   every current series' length matches the time series'.

## Not fixed (documented limitations, not bugs)

- The ideal op-amp model has no output-voltage saturation/rail limiting
  (matches an unclamped nullor, same simplification most simple SPICE-like
  teaching tools make) — an open-loop or unstable feedback topology can
  read as a singular matrix rather than "railed to a supply." Modeling
  real rails would need supply-voltage parameters the UI doesn't collect.
- The browser "Component Table" editor doesn't expose per-diode `IS`/`N`
  or per-source AC phase — only the "Netlist Text" tab can set those.
  Reasonable v1 scope; noted in the README as a place to extend.
