# Cubist

A Rubik's Cube toolkit in Go: Kociemba two-phase solver, facelet validator, algorithm analyzer,
and an animated 3-D HTML player that re-verifies every solution with an independent simulation.

**Status: Phase 2 (core build) complete.** Required features implemented and working end to end:

1. Cubie model + notation parser, inverse, simplifier
2. Facelet I/O with validation and plain-language diagnoses
3. Two-phase solver (`cubist solve`)
4. Animated 3-D HTML player (`cubist render`)

Try it: `go build -o cubist . && ./cubist solve "R U R' U' F2 D L' B2" && ./cubist render -o out.html --scramble "R U F"`

See PLAN.md for the architecture. (Full README arrives in Phase 6.)
