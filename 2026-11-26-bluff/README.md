# Bluff — poker game-theory lab (Go)

**Status: Phase 2 complete (core build).** See [PLAN.md](PLAN.md) for the full plan.

Working now (required features):
1. **CFR+ solver** for Kuhn and Leduc poker (`bluff solve leduc`) — Leduc converges to the known game value −0.0856.
2. **Exact best response / exploitability** (`bluff exploit leduc maniac`).
3. **Hold'em equity** with a 7-card evaluator and range parser (`bluff equity AhAs KdKc`).
4. **Play vs the solved strategy** with hints, plus `match` simulation vs bots.

Run: `go build -o bluff . && ./bluff help`   ·   Test: `go test ./...`

Stretch (push/fold, HTML report, strategy save/load) comes in phase 4.
