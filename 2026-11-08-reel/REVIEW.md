# Reel — adversarial review (Phase 3)

Method: attack the Phase-2 build as a hostile reviewer — external content the codec was never tuned on
(ffmpeg's `testsrc2`, `mandelbrot`, `life`, `cellauto`, `rgbtestsrc`, compared against libx264 at the same QP),
mutated/truncated streams, edge-case CLI input, extreme parameters, tests that cannot fail, and a read of every
shortcut I took. Every finding below was fixed and has a regression test or a scripted check in `verify.sh`.

## Findings

| # | Sev | Finding | Evidence | Fix |
|---|-----|---------|----------|-----|
| 1 | **CRITICAL** | Scene-cut detector was a plain mean-absolute frame difference. On `cellauto` (a hard-edged pattern that scrolls one row per frame) it fired on **every** frame, so the whole clip was coded as 30 I-frames: **504 KB vs 30 KB** for libx264 on the same input. Any fast pan of high-contrast content would hit it. | `reel info` showed `I I I I …`; size 504,110 B | Replaced with a *motion-compensated* score (16x16 blocks, exhaustive ±8 search) plus a "jump relative to the clip's own baseline" rule so steady heavy noise is not a cut either. Now 30,235 B (x264: 30,992 B). `TestSceneCutDetection` covers true cut at frame 10, no false cuts on pan/objects/mixed/noise/zoom, and a binary-noise 1-px scroll. |
| 2 | HIGH | The Y4M reader accepted `C420p10` (10-bit) because it only checked `HasPrefix("420")`, then silently misread the samples as 8-bit. | read of the code | Exact whitelist (`420`, `420jpeg`, `420mpeg2`, `420paldv`); error names the format. |
| 3 | HIGH (test quality) | My own Y4M-rejection test was vacuous: the 10-bit/4:2:2/interlaced cases were rejected for the *wrong reason* (file had no frames), so finding 2 passed the test. | mutation: removing the check kept the test green | Test inputs now contain a complete frame, so only the tag can trigger the error. |
| 4 | MEDIUM | Deblock tc0 table was computed at start-up with `math.Pow`; the decoder's output would depend on the platform's libm rounding. | read of the code | Replaced by integer literals — the bitstream definition is now float-free (`alpha/beta/tc0` tables). |
| 5 | MEDIUM | `codeEG` told encoder from decoder with a type assertion on a concrete type — fragile, and wrong for any future `bitIO`. | read of the code | Added `decoding()` to the `bitIO` interface. |
| 6 | MEDIUM | `Encode` accepted a `Video` whose frames differ in size from the header, or with FPS 0 → index panic / divide by zero in rate control. | API misuse test | Validated up front with clear errors (`TestRejectsBadInputs`). |
| 7 | MEDIUM | Full search spent half its time in map bookkeeping (16.8 s → 7.9 s for CIF/20 frames after removing the visited-map from the exhaustive loop). | profile by timing | Map kept only for the few candidate/diamond points. |
| 8 | LOW (UX) | Error output read `reel: reel: not a .reel stream`. | `reel dec x.y4m` | `fatal()` strips the duplicated prefix. |
| 9 | LOW (UX) | `-bitrate 5` silently produced 8 kbit/s, `-bitrate 100000` silently used 4 Mbit/s. | CLI run | Warning / note explaining the QP floor/ceiling was reached. |
| 10 | LOW | No test proved motion estimation finds *true* motion; a search that always returned (0,0) plus good residual coding would still pass the bit-exact tests. | thought experiment | `TestMotionRecoversTruePan`: the generator pans by exactly (1.7, 0.6) px/frame = (6.8, 2.4) qpel; ≥75% of macroblocks must recover (7±1, 2±1) for both diamond and full search. |
| 11 | LOW | The `info` stats could not show intra-mode usage, so a dead intra mode would go unnoticed. | read of the code | `FrameStat.IModes`; `TestIntraModesAllUsed` asserts DC/V/H/TM all get chosen on real content. |

## Things I tried that were fine (documented so they are not re-checked)

* **Decoder robustness**: 3,000 mutated streams (flipped payload bits with the CRC *recomputed* so the damage reaches the syntax layer, header
  corruption, truncation, garbage runs). 2,287 rejected with clean errors, 713 decoded (damage landed in don't-care bits), **zero panics** —
  verified by calling the un-recovered decode path, so the `recover()` safety net is demonstrably never needed.
  A hostile 4096x4096 header with an empty payload fails in milliseconds.
* **Odd sizes** (17x33, 83x51, 16x16, one frame, two frames): encode → decode bit-exact; ffmpeg reads our Y4M output.
* **Rate control** lands within ~1% of target for 60–1200 kbit/s on three presets (heavy noise bottoms out at the QP-51 floor, now reported).
* **Closed loop**: decoder output equals the encoder reconstruction bit-for-bit across 12 tool combinations incl. B-frames, GOP/B interaction, odd size.
* **Compression sanity vs libx264** at equal QP 28 on ffmpeg-generated clips: Reel's size is within ~7% and ~1–2 dB lower PSNR on
  `testsrc2`/`mandelbrot`/`life` (a 20-year-old feature set vs a modern one) — believable, not suspicious.

## Known limitations (deliberate scope, not bugs)
* Intra: only 16x16 / 8x8-chroma prediction (no I4x4, no luma-DC Hadamard); chroma uses the luma QP.
* One reference frame per list; MV prediction is the plain median for every partition shape; no weighted prediction, no temporal direct mode.
* Entropy models have no neighbour context for MVD magnitude.
* Whole clip is held in memory (source + reconstruction).
* Tiny clips (<~10 frames) can overshoot a bitrate target because the I-frame dominates and cannot be re-planned.

## Fresh run-through
After the fixes: `go test ./codec` green (all of the above), the five ffmpeg-sourced clips re-encoded (cellauto 504 KB → 30 KB, others unchanged),
CLI error/edge-case script re-run with clean messages. Zero of the listed issues reproduce.
