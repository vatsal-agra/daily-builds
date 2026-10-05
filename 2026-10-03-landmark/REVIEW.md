# REVIEW — adversarial pass on Phase 2

I attacked the build as a hostile reviewer: first by running the eval harness and hand-built hostile CLI inputs,
then by reading the code for shortcuts. Everything below was found, reproduced, and fixed.

## A. Algorithmic / correctness findings (found by the eval harness)

| # | Finding | Evidence | Fix |
|---|---------|----------|-----|
| A1 | **Offsets were wrong ~50% of the time even when the song was right.** | Eval showed "offset ✓ 42%". Debug run: error was *exactly 16.00 bars* in every miss. The synthesizer's phrase sequence `A A' B A` repeated every 16 bars, so songs were literally periodic and the matcher's pick between two perfect alignments was arbitrary. | The matcher was right; the *test data* was unrealistically loop-like. Synth now draws each 4-bar section from a pool of phrases with random mutations and changes the chord progression every 8 bars, so recurring motifs exist but exact repetition doesn't. Offset accuracy → ~100%. |
| A2 | **Fixed accept floor (7 votes) let never-indexed songs through: 15/36 false accepts.** | Negatives' median top score was 8. | Found three separate causes (A3–A5); floor raised to 11 and the other guards below added. **0 / 80** in the final 40-song run (see README). |
| A3 | **Related songs fool the matcher.** Negatives that shared key *and* BPM with an indexed song scored up to 42 votes: the kick-drum lattice and shared scale produce a genuinely consistent alignment. | Debug print: `neg 20020 (F Mixolydian 140) matched 20 (F Major 140) score 42`. | (1) Synth gets realistic diversity — continuous BPM (78–148, 0.1 resolution), ±40-cent tuning drift, per-song kick pitch. (2) New **rival-offset (`Alt`) test**: such coincidences show a *comb* of near-equal peaks at every beat, while a real match has one dominant spike. If the song has a rival offset ≥ ½ the winner's score, the match must clear `MinScore × LoopFactor` and is flagged `OffsetAmbiguous`. |
| A4 | **Speed search multiplies false-positive chances ×25.** Searching 25 speed factors and taking the max picked up noise alignments (scores to 26). | Eval: false accepts jumped when the speed search ran on negatives. | Speed-corrected matches need `+SpeedPenalty` votes **and** must pass a *sharpness test*: a true time-scaled clip lights up one speed and falls off within ±1–2 steps (measured: 153 votes at the right speed, ~17 beside it, ~6 further away) whereas a coincidental related song scores 12–20 at *every* speed (plateau). Winner must beat the same song's score at speeds ≥2 steps away by 2.5×. Recall for "−4 % speed + noise, 5 s" went 53 % → 83 % compared with just raising the penalty, with 0 false accepts. |
| A5 | **Query-side fan-out experiment.** Hypothesis: asymmetric fan-out (more pairs at query time) recovers recall under noise. | Tried query fan 5/10/20: no gain, +1 false accept. | Rejected; kept the knob (`QueryFan`) at 5 and documented. |
| A6 | **Digital silence generated "peaks"** (every cell equals the ceiling), then hashes. | Reading `FindPeaks`: all −180 dB cells pass `v >= neighbourhood max`. | Absolute ceiling: below −40 dB nothing is fingerprinted. Test added. |

## B. UX / robustness findings (found with hostile CLI inputs)

| # | Finding | Fix |
|---|---------|-----|
| B1 | `identify clip.wav -db lib.lmk` → "give exactly one WAV clip" (Go's `flag` stops at the first positional). | Custom interspersed-flag parser used by every subcommand. |
| B2 | `index -add` on an already-indexed file aborted the whole run. | `-add` skips known names with a notice; a fresh index still errors on a true duplicate. |
| B3 | A silent / <1.5 s clip said "no hash collisions with any indexed song" (misleading). | Distinct message: "no usable landmarks: silent, too quiet, or shorter than ~1.5 s". |
| B4 | `degrade` used magic `-snr 1000` as "off". | Uses `flag.Visit` to detect whether `-snr` was given. |
| B5 | `index.Save` wrote in place — a crash mid-write corrupts the library. | Write to `.tmp` + atomic rename. |
| B6 | Index params came from untrusted JSON with no validation (a corrupt file could overflow the 9-bit/6-bit hash fields). | `Params.Validate()` on load; CRC32 already catches random corruption. |
| B7 | WAV decoder accepted `bits=12` (integer-divided to 1 byte). | Rejects non-multiple-of-8 depths. |
| B8 | Dead code: `Match.Hist` never populated; stale doc comment on `Accuracy`; leftover `-qfan` experiment flag. | Removed / fixed. |
| B9 | Confidence number and OffsetAmbiguous were not visible to users. | `identify` prints best rival-offset votes and a note when the clip lies in repeated material. |

## C. Known limits (documented, not hidden)
* 5 s clips under brutal damage (drive-12 distortion; −3 dB pink noise; "phone" chain) recall only 45–75 %; 10 s clips recover 70–100 %. That is the honest operating curve of landmark hashing, and the policy trades recall for zero false accepts.
* The corpus is synthetic. Real recordings have far richer spectra, so false-collision rates would be lower, but real room acoustics / codecs aren't modelled beyond the degradations listed.
* Sections that genuinely repeat give several equally valid offsets; the tool reports one and flags the ambiguity.

## Fresh run-through
After the fixes I re-ran: the hostile CLI inputs (short, silent, non-WAV, corrupt index, missing index, flags after positionals, duplicate add) and the eval battery. None of the findings above reproduce; see the table in README.md for the final numbers.
