# Tide

A from-scratch time-series database in Go (stdlib only): Gorilla compression, WAL, checksummed blocks, a query language, HTTP API and a live dashboard.

**Status:** Phase 2 complete — the four required features work end-to-end:
1. Gorilla codec (`internal/gorilla`) 2. Durable storage: WAL + head + blocks + crash recovery (`internal/wal`, `internal/store`)
3. Query language & evaluator (`internal/query`) 4. HTTP API + dashboard (`internal/server`).

```
go build -o tide ./cmd/tide
./tide serve -demo          # http://127.0.0.1:8428
```
See [PLAN.md](PLAN.md). Full docs arrive in the final phase.

**Phase 3:** adversarial review done — 18 findings reproduced, fixed and regression-tested; see [REVIEW.md](REVIEW.md).

**Phase 4:** stretch features shipped — compaction + retention, alert rules (`-alerts alerts.example.json`), data generator + benchmark (`tide gen`, `tide bench`); UI polish (dark/light, tooltips, mobile layout, error carets).

**Phase 5:** `scripts/verify.sh` exercises every feature end-to-end against the real binary (72 checks incl. kill -9 recovery, torn WAL, corrupted block, lock, compaction, retention, alerts, dashboard in headless Chromium). Green.
