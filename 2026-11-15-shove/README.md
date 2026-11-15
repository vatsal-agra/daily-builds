# Shove
Sokoban toolkit in Go (stdlib only). **Status: Phase 2 complete** — the four required features work end-to-end:

1. XSB parser/validator (`sok/level.go`)
2. Push-optimal A* solver with Hungarian-matching heuristic + deadlock pruning (`sok/solver.go`, `sok/deadlock.go`)
3. Reverse-play level generator, rated by the solver (`sok/gen.go`)
4. Playable single-file HTML game with verified solutions (`sok/html.go`, `sok/template.go`)

```
go build -o shove ./cmd/shove
./shove solve levels/starter.txt
./shove html levels/starter.txt levels/generated.txt -o game.html
```
See PLAN.md. Full docs arrive in Phase 6.
