# Phase 5: verification

`demo.sh` is the single entry point that exercises every feature end to
end and is meant to be run, not just read. It does not stop at the first
failure -- it runs every check, reports PASS/FAIL for each with the
failing command's own output on failure, and exits non-zero only if
something actually failed.

## What it runs

| # | Check | What it proves |
|---|---|---|
| 1 | `python3 -m unittest discover -s tests` | 115 unit tests: XOR-distance/bucket-index math, k-bucket eviction fidelity (including the concurrency-race regression from `REVIEW.md`), oracle-verified lookup correctness, TTL/republish behavior, deterministic-network reproducibility, file-store round trips and corruption/tamper detection, CLI argument validation, an HTML-viewer content test |
| 2 | `scripts/fuzz_sweep.py` | 60 randomized `(n, k, alpha, loss)` configurations, each exercising lookups + churn + STORE/GET + file-store PUT/GET together in one run, with `k` deliberately swept down to 1 to maximize how often the full-bucket eviction race actually triggers |
| 3 | `meridian run --churn` | a 40-node swarm survives random crash churn over 5000 simulated ticks; lookups afterward still find a high fraction of the true closest nodes per the brute-force oracle |
| 4 | `meridian demo` | the full scripted narrative: bootstrap -> oracle-verified lookup -> STORE on one node, GET from a different one -> survive a partial replica-holder outage -> upload a file, crash one chunk's original holder, download successfully from a third node with SHA-256 verification |
| 5 | `meridian filedemo <real file>` | a real file (not synthetic test bytes) round-trips through the DHT across different nodes |
| 6 | `meridian filedemo` on an empty file | the empty-file edge case doesn't crash or corrupt the manifest |
| 7 | `meridian viz --html-out` | the trace JSON and the standalone HTML viewer both generate successfully |
| 8 | `scripts/viz_smoke.js` (headless Chromium) | the visualizer actually loads and runs in a real browser engine -- every control (step, play/pause, scrub to start/middle/end, click a log entry) is driven programmatically, and the check fails on any console error or uncaught exception, not just "the file exists" |
| 9 | bad CLI input | `--nodes 0` produces a clean one-line error, not a raw Python traceback |

## Last confirmed clean run

```
==============================================
 Meridian verification
==============================================

[1] unit test suite ... PASS
[2] multi-feature fuzz sweep (60 seeds) ... PASS
[3] CLI: run (with churn) ... PASS
[4] CLI: demo (scripted end-to-end walkthrough) ... PASS
[5] CLI: filedemo (real file, cross-node retrieval) ... PASS
[6] CLI: filedemo on an empty file ... PASS
[7] CLI: viz (writes trace.json + standalone HTML viewer) ... PASS
[8] headless-Chromium smoke test of the visualizer ... PASS
[9] CLI: bad input is a clean error, not a traceback ... PASS

==============================================
 9/9 checks passed
==============================================
```

Total automated coverage as of this run: 115 unit tests (`tests/`) + a
60-seed fuzz sweep (`scripts/fuzz_sweep.py`) + 9 end-to-end `demo.sh`
checks covering all 6 features (4 required + 2 stretch), zero failures.
