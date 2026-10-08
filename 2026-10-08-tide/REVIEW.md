# Adversarial review

I attacked the Phase 2 build as a hostile reviewer: fuzzing the HTTP surface with
hostile input, reading every code path for state that outlives a flush/restart,
driving the dashboard in headless Chromium (desktop + 390px phone, light + dark),
and probing numeric edge cases. Each item below was **reproduced first** against
the running binary (or a test), then fixed, then covered by a regression test or
a re-run of the same probe.

| # | Severity | Finding (reproduction) | Fix |
|---|----------|------------------------|-----|
| R1 | **High** | Query with no matching series returned `"series":null` (nil slice). The dashboard does `body.series.length` → `TypeError`, breaking the panel. | `Eval` always initialises `Series: []`. Test: `TestNoMatchEncodesEmptyArrayNotNull`, server-level test too. |
| R2 | **High** | Timestamps were unbounded: `-9e18` and `9e18` were accepted, which risks int64 overflow in delta-of-delta encoding and range arithmetic. | Accept only `0 .. 9999-12-31` (`MinTimestamp/MaxTimestamp`); others counted as invalid with a reason. Test: `TestTimestampAndLabelLimits`. |
| R3 | **High** | Ordering state lived only in the head. After a flush (or restart), re-sending an already-stored sample was *accepted* → duplicates inflate stats and storage until compaction. Also WAL replay after the crash window (block written, WAL not yet reset) re-inserted flushed samples into the head. | Store keeps `lastT[series]` for head **and** blocks (seeded from block indexes on open). Append rejects `t <= last`; WAL replay skips samples already persisted. Tests: `TestResendAfterFlushIsRejected`, `TestWALReplaySkipsAlreadyFlushedSamples`. |
| R4 | Medium | `step 0s` / `range 0m` silently fell back to auto-step instead of erroring. | Parser rejects non-positive and sub-millisecond durations. Test: `TestZeroDurationsRejected`. |
| R5 | **High** | No cardinality guards: a single line with 5000 labels was accepted (59 kB block for 9 samples); unbounded series count. | `MaxLabels=64`, name ≤256 B, value ≤2 KiB, `MaxSeries` (default 1M). Tests: `TestTimestampAndLabelLimits`, `TestMaxSeries`. |
| R6 | Medium | Sums of large floats can overflow to `+Inf`; `json.Marshal` fails and the handler had already written `200` → truncated/empty body with a success code. | Non-finite buckets are dropped in `Eval`; `writeJSON` marshals before writing headers and returns 500 on failure. Test: `TestOverflowToInfIsDroppedNotBrokenJSON`. |
| R7 | Low | `Stats()` copied every head chunk (`Bytes()`) just to measure it — O(head) allocation on each 5 s dashboard poll. | `Encoder.Size()`. |
| R8 | Medium | UI persisted `panels` wholesale to localStorage — including the DOM node and the last (large) query result — and persisted the transient "ad-hoc" panel. | Persist only `{q}` of non-ad-hoc panels. Verified in Chromium. |
| R9 | Low | UI decided whether to append default `range`/`at` with `/\bat\b/` over the raw query, so `{route="/at"}` suppressed `at latest`. | Strip quoted strings before testing. |
| R10 | Low | Hidden-legend state keyed by panel *index*; deleting a panel made other panels inherit its hidden series. | Keyed by query text. |
| R11 | Low | Matrix results reported `start` = query start while the first bucket began earlier → first point drawn left of the y-axis. | `Result.Start` is the first bucket boundary. Test: `TestMatrixStartIsBucketAligned`. |
| R12 | Medium | `serve` flushed the head on every shutdown → a tiny block per restart. | Removed; the fsynced WAL already guarantees durability. |
| R13 | Low | Empty/fully-rejected batches still fsynced the WAL. | Sync only when something was written. |
| R14 | Low | `/series` unbounded response. | `limit` param (default 5000, `X-Tide-Truncated` header). Tested. |
| R15 | Low | HTTP server had no read/idle timeouts (slowloris). | `ReadTimeout`/`IdleTimeout` 2 min. |
| R16 | Medium | On a 390 px phone the "try:" example link overflowed → horizontal page scroll. | `overflow-wrap:anywhere`. Re-measured in Chromium: `scrollWidth == innerWidth`. |
| R17 | Medium | Partial trailing bucket for `rate/increase/sum/count` plotted as a cliff on the right edge of every live chart (found by eye in the first screenshot). | Extensive functions omit buckets that end after the query end. Test: `TestPartialTrailingBucketOmittedForExtensiveFns`. |
| R18 | High (caught while building) | Block precedence for duplicate timestamps followed *time* order, so an older-in-time but newer-written block lost. | Blocks ordered by write sequence (`seq` in file name). `TestCompactionDedupesAndShrinks` now builds a genuinely overlapping block. |

| R19 | Medium | *Found in Phase 5 by the automated UI check:* on a phone the alert strip overflowed horizontally (long `expr` text under `white-space:nowrap`, grid track not shrinkable). | `minmax(0,1fr)` track, `white-space:normal` + `overflow-wrap:anywhere` on alert text. `scripts/ui_check.js` now guards it. |

## Known limitations (documented, not bugs)
* Blocks are read fully into memory (no mmap / lazy loading) and compaction merges all blocks at once — fine up to a few GB, not for terabytes.
* Series lookup is a linear scan with matchers, no inverted index.
* Out-of-order/backfill writes older than a series' newest sample are rejected (like Prometheus without an OOO window).
* Single-node; no replication or auth. Bind to localhost by default.

## Fresh run-through (after fixes)
Re-ran every reproduction: no-match query → `"series":[]`; extreme timestamps → invalid with reason; re-send after flush → `outOfOrder:1`; `step 0s` → parse error with caret; 5000-label line → rejected; dashboard desktop/mobile/dark/light with parse errors, empty results, legend toggles and panel persistence → no JS errors other than the intentional 400s for bad queries; `go test -race ./...` green. **Zero listed issues reproduce.**
