# Tide

**A from-scratch time-series database in Go — standard library only.**
Gorilla bit-level compression, a CRC-framed write-ahead log, immutable checksummed blocks,
a small query language with counter-reset-aware `rate()`, percentiles and group-by, an HTTP API,
alert rules, and a live dashboard (hand-written SVG charts, light/dark, phone-friendly).

```
 line protocol ─► POST /write ─► Store.Append ─► WAL (crc frames, fsync) ─► Head (Gorilla chunks per series)
                                                        │ flush (2h span / 1M samples / POST /flush)
                                                        ▼
                                  blocks/b-<minT>-<maxT>-<seq>.blk   chunks + JSON index + CRC footer
 query text ─► parse ─► Select (head ∪ blocks, newest write wins per timestamp) ─► bucket ─► aggregate ─► JSON
```

## Run it

```bash
cd 2026-10-08-tide
go build -o tide ./cmd/tide

./tide serve -demo -alerts alerts.example.json     # http://127.0.0.1:8428  (seeds 3 h of fleet metrics, keeps feeding)
./tide serve -dir ./data -addr :8428               # an empty database you write to yourself

# ingest (text format: metric{label="v",...} value [timestamp])
curl -XPOST localhost:8428/write --data-binary $'temp{room="lab"} 21.5\ntemp{room="lab"} 21.7 1700000000000'

# query
curl --get localhost:8428/query --data-urlencode 'q=sum(rate(http_requests_total{code=~"5.."})) by (host) range 1h step 1m'

# CLI tools
./tide gen   -dir ./data -hosts 8 -hours 24            # bulk synthetic history
./tide query -dir ./data 'p99(http_latency_ms) range 6h step 5m at latest'
./tide stats -dir ./data
./tide bench -series 200 -samples 5000                 # ingest rate, compression, query latency

./scripts/verify.sh                                    # 72-check end-to-end verification
go test -race ./...                                    # 49 unit/integration tests
```

Requires Go 1.24+. `scripts/verify.sh` also drives the dashboard with headless Chromium if Playwright is available (it skips that part otherwise).

## Features

**Required (all shipped)**
1. **Gorilla codec** (`internal/gorilla`) — timestamps as delta-of-delta in 7/9/12-bit buckets with a 64-bit escape, float64s as XOR with leading/trailing-zero window reuse; chunks of 120 samples; bit-exact round-trip for NaN/±Inf/−0/denormals; randomised + truncation tests. A regular constant series costs ≈ 0.4 B/sample; noisy rounded gauges + counters in the synthetic fleet ≈ 3.6 B/sample (4.4× vs 16 B raw).
2. **Durable storage** (`internal/wal`, `internal/store`) — CRC-framed WAL with fsync per batch; torn/corrupt tail detected and truncated on open (tested at *every* byte cut point); in-memory head of compressed chunks; flush to atomic-rename blocks with a checksummed index; crash windows handled (block written but WAL not reset → replay skips already-persisted samples); per-series ordering enforced across flushes and restarts; exclusive directory lock; corrupt blocks refuse to load.
3. **Query language** (`internal/query`) — `[agg(] fn(selector) [)] [by (labels)] [range D] [step D] [at T]`; matchers `= != =~ !~` (anchored RE2); `avg min max sum count last rate increase p1…p99`; cross-series `sum/avg/min/max/count … by (…)`; positioned parse errors with a caret; point limits; partial trailing buckets are dropped for extensive functions so live charts never show a cliff.
4. **HTTP API + dashboard** (`internal/server`) — `POST /write`, `GET /query`, `/series`, `/stats`, `/alerts`, `POST /flush`, `/compact`, `/retention`, `/healthz`. Dashboard: multi-panel grid persisted in the browser, hover crosshair + tooltip, clickable legend, parse errors with caret, ad-hoc queries, ingest box, stat chips (compression ratio, bytes/sample, WAL, blocks), theme toggle, 5 s auto-refresh.

**Stretch (all shipped)**
5. **Compaction + retention** — `Compact()` merges all blocks, deduplicates (newest write wins), re-packs chunks, and is crash-safe (the new block records its sources; `Open` finishes an interrupted compaction). `DropBefore` / `-retention` expire whole blocks.
6. **Alert rules** — JSON rules (`name, expr, op, threshold, for`) evaluated on an interval; per-series `pending → firing → resolved` state machine with `for` timers that reset on recovery and vanish when data stops; surfaced at `/alerts` and as a banner strip in the UI.
7. **Workload generator + benchmark** — deterministic synthetic fleet (diurnal CPU, memory walks that "OOM", request counters that reset on restarts, heavy-tailed latency) via `tide gen`; `tide bench` reports ingest throughput, compression and query latencies. On the dev box: ~100–145 k samples/s with one fsync per scrape tick, sub-millisecond to ~10 ms for 6 h queries over 54 series.

### Query cheat-sheet
| Query | Meaning |
|---|---|
| `cpu{host=~"web-0[12]"}` | raw samples (last hour) |
| `avg(cpu) range 6h step 5m` | per-series average per 5-minute bucket |
| `sum(rate(reqs{code="500"})) by (host)` | per-second 5xx rate per host (counter resets handled) |
| `p99(latency_ms) step 1m at latest` | 99th percentile per minute, ending at the newest stored sample |
| `max(avg(mem)) by (dc)` | worst host memory per datacenter |
| `increase(reqs) step 1h at now-1d` | total increase per hour, ending 24 h ago |

## Why I chose this today
The ledger is full of compilers, solvers, simulators and renderers, but no storage engine with real on-disk durability concerns, and no time-series work at all. A TSDB is a compact problem with genuine depth in three directions at once — information theory (Gorilla), crash consistency (torn writes, crash between rename and WAL reset), and query semantics (counter resets, bucket alignment) — and it comes with a natural, visual front end. It is also the kind of system where the interesting bugs are all in the seams, which made the adversarial review productive (19 findings, one of which — block precedence following time order instead of write order — would have silently returned stale data after compaction).

## Honest limits
Blocks are loaded fully into memory (no mmap/lazy reads); compaction merges *all* blocks at once; series lookup is a linear scan with matchers (no inverted index); out-of-order writes older than a series' newest sample are rejected; single node, no auth (binds to localhost by default). See [REVIEW.md](REVIEW.md) for the 19 issues found and fixed, and [PLAN.md](PLAN.md) for the design.

## Where a human could take this next
* **Inverted label index + posting-list intersection** so selectors on millions of series stay fast; memory-map blocks and read chunks lazily.
* **Leveled compaction** (2 h → 6 h → 24 h blocks) and **downsampling rollups** (1 m/1 h aggregates kept longer than raw data).
* **Out-of-order ingest window** (small sorted buffer per series) for late-arriving data.
* **Prometheus compatibility:** remote-write receiver and a PromQL subset (binary operators, `histogram_quantile`, subqueries).
* **Replication/sharding** — the block format is already immutable and self-describing, so shipping blocks to object storage is a natural next step.
* **Alert notifications** (webhook/Slack) with deduplication and silences, and recording rules that write results back as new series.
* Better codecs for the noisy-gauge case (e.g. Chimp / Elf XOR variants) — the benchmark harness makes A/B comparisons a one-liner.

## Layout
```
cmd/tide/            CLI: serve, gen, query, stats, bench
internal/gorilla/    bit writer/reader, encoder, iterator (+ tests)
internal/wal/        CRC-framed append-only log (+ torn-tail tests)
internal/store/      head, blocks, flush, compaction, retention, labels, matchers, dir lock
internal/query/      lexer/parser, evaluator (buckets, rate, quantiles, grouping)
internal/server/     HTTP handlers, line-protocol parser, alert manager, embedded dashboard (ui/index.html)
internal/gen/        synthetic fleet workload
scripts/             verify.sh (end-to-end), ui_check.js (dashboard)
alerts.example.json  sample rules for the demo data
```
