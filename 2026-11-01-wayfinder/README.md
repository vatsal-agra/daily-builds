# Wayfinder

Pathfinding laboratory in Go (A*, JPS, Theta*, D* Lite, HPA*) with an HTML replay viewer. Stdlib only.

## Status: Phase 2 (core build) complete
Working end-to-end now:
1. **Maps** — ASCII format, terrain costs, seeded generators (random / maze / rooms / caves / open) — `wayfinder gen`
2. **Optimal planners** — Dijkstra, A*, Jump Point Search; fuzz test proves equal costs on 1,500 random maps — `wayfinder solve|compare`
3. **D\* Lite** — agent explores an unknown world, every replan cross-checked against from-scratch A* — `wayfinder explore`
4. **HTML replay viewer** — scrubbable expansion animation + D* Lite walkthrough — `wayfinder html`

Planned for later phases: Theta*, benchmark/fuzz CLI, HPA*. See [PLAN.md](PLAN.md).

```
go build -o wf ./cmd/wayfinder
./wf gen -kind caves -w 70 -h 40 -seed 5 -o m.txt
./wf compare -map m.txt
./wf html -map m.txt -o replay.html
```
