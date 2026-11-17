# Orrery — an N-body gravity laboratory

Define a system of masses, integrate it with seven different schemes, and *measure* how faithful each one is to the
physics: energy, momentum, angular momentum, convergence order, time-reversibility, chaos. From scratch in Go,
standard library only (~3,500 lines + ~650 lines of tests).

The headline result, reproducible in one command (`./orrery bench twobody -dt 0.01 -T 100`, eccentric binary, e=0.6):

| method | max \|ΔE/E₀\| | notes |
|---|---|---|
| euler | 9.6e-1 | spirals away |
| symeuler | 3.6e-2 | symplectic, order 1 |
| leapfrog | 1.1e-3 | symplectic, bounded forever |
| yoshida4 | 9.2e-7 | symplectic, order 4 |
| rk4 | 1.3e-6 | order 4 but **drifts secularly** — loses to leapfrog on long runs |
| dopri5 | 1.0e-8 | adaptive 5(4) |

## Run it

```bash
go build -o orrery ./cmd/orrery        # Go 1.21+, no dependencies
./orrery list                          # built-in systems and integrators
./verify.sh                            # everything: gofmt, vet, tests, scripted demo, headless-browser check
```

| command | what it does |
|---|---|
| `run <scn> -m leapfrog -dt .01 -T 10` | integrate, print ΔE/E₀, ΔL/L₀, \|ΔP\|, virial ratio over time |
| `bench <scn>` | all integrators side by side (error, cost, time); warns when a run is untrustworthy |
| `elements <scn>` | orbital elements (a, e, i, Ω, ω, ν, M, period) of every body about body 0 |
| `bh <scn>` | Barnes–Hut force error and speed-up versus opening angle θ |
| `order` | measure each integrator's empirical convergence order against the exact Kepler solution |
| `reverse <scn>` | integrate forward T then backward T; which schemes come home? |
| `lyap <scn> -m yoshida4` | largest Lyapunov exponent by the Benettin shadow-orbit method, with a verdict |
| `report <scn> -o out.html` | self-contained HTML: animated orbits + log-scale energy-error chart + comparison table |
| `gen <builtin>` | print a built-in system in scenario-file format |

`<scn>` is a built-in name (`twobody figure8 pythagorean solar trojan plummer disc`) or a scenario file. Flags:
`-m method -dt step -T duration -theta θ -n N -seed S -tol τ -samples k -o file`.

### Scenario format

```
title Sun and a tilted planet
G 1                    # gravitational constant (default 1)
eps 0.01               # Plummer softening (default 0)
theta 0.5              # Barnes–Hut opening angle, 0 = exact (default 0)
body Sun m=1 pos=0,0,0 vel=0,0,0
body P   m=1e-3 orbit=Sun a=2 e=0.25 i=10 raan=20 argp=30 ma=40   # angles in degrees, ma = mean anomaly
barycentric            # shift to the centre-of-mass frame
```
Errors carry line numbers. (`#` starts a comment, so it cannot appear inside a title.)

## Features

**Required**
1. **Integrator suite with diagnostics** — explicit Euler, symplectic Euler, leapfrog (KDK), Yoshida-4, RK4, adaptive
   Dormand–Prince 5(4) with FSAL and exact landing on the target time; energy (softened, always exact O(N²)),
   linear/angular momentum and virial ratio are measured honestly regardless of which force solver ran.
2. **Barnes–Hut octree** — allocation-free linked-list leaves, coincident bodies handled by a depth cap, target never
   accepts a cell it sits inside; validated against direct summation (error shrinks monotonically with θ; θ→0 is exact
   to 1e-9) and against full dynamics.
3. **Scenarios + Kepler oracle + orbital elements** — text DSL with `orbit=` directive, seeded generators (Plummer
   sphere in exact virial balance, test-particle disc), approximate J2000 solar system; a universal-variable Kepler
   propagator (elliptic/parabolic/hyperbolic, bracketed Newton) cross-checked against an independent
   Kepler-equation oracle; state⇄elements conversion with degenerate (circular/equatorial) handling.
4. **HTML report** — animated orbit canvas (trails, scrub, play/pause, √-radius toggle that auto-enables for solar
   systems), log-scale energy-error chart with hover readout, sortable-at-a-glance comparison table; light/dark;
   mobile layout; no network references.

**Stretch (all four shipped)**
5. **Empirical convergence order** (`order`) — fits log error vs log dt for every fixed-step method over 1.37 orbital
   periods; observed: leapfrog 2.00, Yoshida 3.99, RK4 4.10, Wisdom–Holman 2.00.
6. **Time-reversibility test** (`reverse`) — leapfrog/Yoshida/WH return to 1e-14…1e-13; Euler and symplectic Euler don't.
7. **Lyapunov exponent** (`lyap`) — Benettin shadow orbit; verdict by e-folds in the second half of the run:
   Kepler orbit → regular, 16-body Plummer → chaotic (λ≈3.3, Lyapunov time ≈0.3), Pythagorean problem → transient chaos.
8. **Wisdom–Holman map** (`-m wh`) — democratic-heliocentric Kepler-drift splitting with exact Kepler steps; on the solar
   system at dt=0.05 yr it beats leapfrog by orders of magnitude and conserves momentum to round-off.

## Things you should know (honest limits)

- **Wisdom–Holman needs a dominant body 0.** Its error scales with m/m₀; on the 2:1 binary it is *worse* than leapfrog.
  It rejects softening and any body heavier than body 0.
- **Barnes–Hut is monopole-only.** Cost grows ~θ⁻³: at N=20 000 the tree is 18× faster than direct at θ=1.2 but break-even
  at θ≈0.3. It also breaks Newton's third law, so momentum drifts ~1e-4 on a Plummer sphere (use `-theta 0` for exactness).
- **Fixed steps on close encounters are garbage** (the Pythagorean problem at dt=0.01 loses 718× the total energy). The CLI says so
  loudly and points at `dopri5`.
- The report samples 300 frames, so very fast inner orbits (Mercury over 30 yr) look polygonal.
- The solar-system elements are approximate J2000 values, not an ephemeris.

## Why this today

The ledger has FEM, GCs, codecs, model checkers, PDF and QR, but no orbital mechanics or N-body work, and it is the
cleanest place where "does your numerical method respect the geometry of the problem?" has a crisp, visible answer:
symplectic schemes wobble but never drift; RK4 is *more accurate per step* and still loses over a long enough run.
Building the Kepler oracle first gave every integrator an exact referee, and two of the most interesting bugs were
*measurement* bugs (see REVIEW.md R15/R16): measuring at an exact period made a first-order scheme look second-order,
and shear made a regular orbit look chaotic.

## Where a human could take this next

- Quadrupole terms (or a fast multipole method) in the tree so small θ stops being expensive; parallel force loops.
- Individual/block time steps and a regularised close-encounter integrator (KS / Bulirsch–Stoer / Mikkola) for binaries in clusters.
- Symplectic correctors, higher-order Wisdom–Holman (Wisdom's mapping with correctors, MERCURY-style hybrid).
- Relativistic (1PN) corrections to reproduce Mercury's perihelion precession; non-gravitational forces; collisions/merging.
- A real ephemeris (JPL Horizons import) and an interactive editor in the viewer for placing bodies.
- Variational equations instead of shadow orbits for the Lyapunov spectrum (all exponents, MEGNO chaos maps).

## Layout

```
orrery/            library: vec, system, force (direct + Barnes–Hut), integrate (7 methods), kepler,
                   scenario, analysis (Run, BH error), stretch (order/reverse/Lyapunov), report (+ template)
cmd/orrery/        CLI
tests/             headless browser check for generated reports
verify.sh          full verification (33 checks, ends ALL GREEN)
PLAN.md REVIEW.md  design and the adversarial review log (16 findings)
```
