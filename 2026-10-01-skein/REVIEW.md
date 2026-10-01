# REVIEW — adversarial pass on Skein

Method: I re-read every file as a hostile reviewer, then wrote `sketch/hostile_test.go`
(resealed-garbage codec fuzzing, adversarial stream orders, structured keys, extreme
parameters) and ran the CLI against empty / missing / binary / CRLF / short-field inputs.

## Findings (all fixed)

| # | Sev | Finding | Found by | Fix |
|---|-----|---------|----------|-----|
| 1 | High | `member build -cuckoo` on a real log died after **57 items** ("filter is full") although capacity was 40 000: a cuckoo filter can hold at most 2×4 copies of one fingerprint, and a log repeats keys thousands of times. | CLI run on a Zipf log | Added `Cuckoo.AddUnique` (set semantics: skip if already present); CLI uses it and reports distinct vs repeated counts. `Add` documented as multiset. |
| 2 | High | `stats` default top-K was 20 counters on 21 k distinct keys → ranks 3-20 had error bars of ±13 000 — technically correct, practically useless output. | Eyeballing `stats` output | Default `TopK` raised to 500 (≈ 20 KiB); output now shows ±0 for the real heavy hitters. |
| 3 | Med | `TDigest` decoder accepted `n=NaN`, `min=NaN`, `min>max`, ±Inf centroid weights/means (CRC resealed). Later quantile math would silently return NaN. | hostile_test `TestTDigestUnmarshalRejectsNonFinite` (failed before fix) | Validate finiteness, min ≤ every mean ≤ max, positive finite weights. |
| 4 | Med | `-q NaN` was accepted by `parseQuantiles` (`NaN<0 || NaN>1` is false) and reached the digest. | Reading the comparison | Written as `!(q>=0 && q<=1)`. |
| 5 | Med | `stats -load old.skn -p 12` silently ignored `-p`: user believes they changed precision, they did not. | Reading flow | Hard error naming the conflicting flag. |
| 6 | Med | Bad flags printed the message + usage **twice** (flag pkg, then `main`). | CLI run | `errUsage` sentinel; exit 2 silently after the flag package has spoken. |
| 7 | Low | Quantile labels/values were ugly: `p90.00000000000001`, `20.120550402955715`. | CLI run | Rounded percentile labels; `%.6g` values. |
| 8 | Low | `stats` with every line skipped said only "no input records" — no hint that `-d/-f/-v` was wrong. | `-f 5` probe | Error now says all N lines were skipped and why. |
| 9 | Low | Error text stuttered: `skein: junk.bin: skein: not a skein file`. | `inspect junk.bin` | Dropped inner prefix. |
| 10 | Low | `NewCMS(1e-12, …)` returned the opaque "bad dimensions 2718281828459x5". | `TestExtremeParams` | Explicit message stating the minimum usable eps. |

## Things I attacked that held up (kept as regression tests)
* Re-sealed-CRC corruption of every byte of every sketch type, ×3 bit patterns, plus 24 000 random multi-byte/truncation mutations: **no panics**, accepted blobs remain usable.
* xxHash64 official vectors + avalanche (≈32 bits flipped per input bit).
* HLL with sequential LE/BE integers, dotted IPs, long common prefixes: error within 4σ.
* t-digest on ascending, descending, 5-value, and step inputs (worst cases for merging digests): centroid count bounded, rank error ≤ 1.2 %.
* SpaceSaving worst-case ordering (heavy hitters first, noise after) and `k=1`.
* Cuckoo failed-insert rollback leaves every previously inserted key present.
* t-digest self-merge, merge of mixed compressions, merge of empty digest keeps min/max.

## Test mistake (mine, not a library bug)
My first adversarial SpaceSaving test asserted retention of keys with frequency 500 when N/k was 1250 — the guarantee only covers freq > N/k. The test was wrong; corrected to 1500 > 1250.

## Known limitations (documented, not bugs)
* No sketch is goroutine-safe (t-digest `Bytes()`/`Quantile()` even flush the buffer). Shard and merge instead — which is the point of the design.
* Count-Min merge is a sum of conservative sketches: still never under-counts, but looser than a single-pass sketch.
* Cuckoo filters can't be merged; `Delete` of a key that was never added may remove a colliding key's fingerprint.
* CSV quoting is not parsed; `-d` is a plain delimiter.
* t-digest accuracy is rank-accuracy: absolute error in a sparse far tail (e.g. p99.9 of a lognormal) can look large while the rank error is tiny.

## Gate
Fresh run-through of every item above after the fixes: all listed failures gone (`go test ./...` green, CLI probes re-run).
