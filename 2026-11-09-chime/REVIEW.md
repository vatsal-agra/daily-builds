# REVIEW — adversarial pass on Chime (Phase 3)

Method: wrote a throw-away attack suite (silence, full-scale square, every sample rate 8–192 kHz,
NaN/Inf samples, absurd bitrate targets, CRC-valid hostile streams, dual-mono, pre-echo A/B, noise-fill
A/B), ran the CLI with bad flags/files, and read the code looking for lazy shortcuts. Every finding below
was reproduced, fixed, and pinned with a regression test in `codec/regression_test.go`.

| # | Finding (reproduced) | Severity | Fix | Test |
|---|----------------------|----------|-----|------|
| R1 | A NaN / ±Inf / 1e12 sample was **accepted**: thresholds became NaN, `int(NaN)` picked an arbitrary scalefactor and the file encoded "successfully" into garbage. Float WAVs could carry NaN straight in. | high | `Encode` rejects non-finite or \|x\|>2²⁴ samples and ragged channels; `ReadWAV` rejects non-finite float samples and hard-clips float data to full scale. | `TestRejectsNonFiniteSamples` |
| R2 | `-b 5000` silently produced a 908 kbps file (finest setting reached) with no indication; `-b -5` was **silently ignored** by the CLI (fell back to 128). | medium (UX) | `Stats.Capped` + CLI note; negative / sub-1-kbps / NaN targets and out-of-range quality are errors with a clear message. | `TestCappedAndOvershootReported` |
| R3 | Giant-header + tiny-payload files (valid CRC) — checked for DoS. Decoder grows buffers lazily and fails after ≤8 bytes past the end: 6 ms, no huge allocation. | none found | (kept: lazy growth + overrun cap) | `TestHostileDecode` |
| R4 | **M/S wasted bits.** Dual-mono audio cost 26% more via M/S than as true mono because the orthonormal M/S noise budget `(nM+nS)/2` was not shared: S (all zeros) used none of it while M was held to the L/R threshold. | medium | M gets `2t − min(E_S, t)`; S gets `t`. Dual-mono now costs 20000 vs 19985 bytes for true mono. | `TestMSNoiseBudget` |
| R5 | **The evaluation metric was blind to pre-echo.** With 2048-point NMR frames, block switching *looked worse* (worst-frame NMR +9.8 dB vs +4.9 dB) although it audibly fixes pre-echo — a metric that can't see the feature it is judging. | high (honesty of the harness) | Added a 256-sample-resolution NMR pass (`TempExcess`, `TempP95`). Switching now cuts temporal excess 2.96 → 1.06 dB at 64 kbps. | `TestMetricSeesPreEcho` |
| R6 | **Noise filling was a net loss.** Per-band levels cost 84% of a 24 kbps stream (3.6 bits per zero band); the rate loop then starved real coefficients and every metric got worse; and no metric could show its benefit (holes). | high | Levels shared by groups of 5–6 bands (NF side info now 17%), 6 dB steps, fill at −6 dB (`nfGain`), new `HoleFrac` metric. Holes 54% → 19% at the cost of more noise over mask — a documented trade-off, opt-in (`-nf`). | `TestNoiseFillingFillsHoles` |
| R7 | Band edges are derived with `math.Atan/Pow/Round` on both sides; on a platform with different FP behaviour (e.g. FMA fusion) a tie could shift one edge and the decoder would silently desync. | medium (portability) | Header carries a CRC of the derived band edges; mismatch is a clean error. | `TestLayoutFingerprint` |
| R8 | `Encode` had no upper bound on length although the header stores a u32. | low | Reject > 2³⁰ samples per channel. | covered by `TestRejectsNonFiniteSamples` shape checks |
| R9 | Steady signals (tones, noise, sweep, voice) might falsely trigger block switching (costs bits, hurts frequency resolution). Checked: none do. Quiet castanets (−40 dB) are still detected. | none found | — | `TestNoFalseTransients` |
| R10 | Silence, full-scale square, 1-sample, 1023/1024/1025-sample, mono files: checked. 2 s of silence → < 120 bytes and decodes to exact zeros. | none found | — | `TestSilence`, `TestFullScaleSquare`, `TestMonoAndTinyInputs` |

## Honest limitations (not bugs, but stated so nobody over-trusts the numbers)
* The NMR metric uses the same family of masking model as the encoder (Schroeder spreading, tonality
  offset, ATH) estimated from a *different* spectrum (Hann FFT vs MDCT pseudo-spectrum). It proves the
  encoder does what its model says; it is not a substitute for listening tests or PEAQ/ViSQOL.
* No temporal post-masking, no inter-channel masking, no short-block grouping, no RDO quantisation.
* Test signals are synthetic (the sandbox has no music corpus), so absolute kbps figures are not
  comparable to published codec numbers.

## Fresh run-through
After the fixes the original attack suite (now `regression_test.go`) was re-run from scratch together with
all earlier tests and the CLI misuse cases: zero of the listed issues reproduce. `go test ./...` green.
