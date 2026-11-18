# Cubist

A Rubik's Cube toolkit in Go: Kociemba two-phase solver, facelet validator, algorithm analyzer,
an animated 3-D HTML player that re-verifies every solution with an independent simulation,
and a small web UI/API.

**Status: Phase 4 (stretch + polish) complete.**

- Phase 2 required features: cubie model + notation, facelet validation, two-phase solver, 3-D HTML player.
- Phase 3: adversarial review — 11 findings fixed (see REVIEW.md).
- Phase 4: stretch features shipped — algorithm analyzer, random-state generator + `bench`, `serve` web UI/API;
  polish: busy states, localhost-by-default server, helpful errors everywhere.

Quick try:
```
go build -o cubist . 
./cubist solve "R U R' U' F2 D L' B2"
./cubist analyze "R U R' U'"
./cubist serve            # http://127.0.0.1:8080
```
See PLAN.md for the architecture. (Full README arrives in Phase 6.)
