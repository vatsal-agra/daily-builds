# REVIEW — adversarial pass

Method: I attacked the build as a hostile reviewer — wrong-answer hunting first (checking
outputs against known theory), then hostile CLI input, then a read-through for shortcuts and UX.

## Findings (all fixed)

| # | Sev | Finding | Fix |
|---|-----|---------|-----|
| 1 | **critical** | Leduc game value came out as **0.0000** (known: −0.0856). Cause: the root node had `fold: 0`, which means "player 0 folded", so every showdown paid out as a fold. Caught only because I compared to the literature value. | `fold: -1` at the root. |
| 2 | **critical** | Leduc antes were never posted (`contrib` started at 0,0), so folding cost nothing and "nit" bots were unexploitable (exploitability 0.0). | Root starts with `contrib {1,1}`. Value is now −0.0856; nit is exploited for exactly 1.0 chip/hand. |
| 3 | high | Hand evaluator allocated several slices per call (`append`, closures) — a lazy shortcut that made exact equity ~3.5× slower and would make the push/fold matrix impractical. | Rewrote `Eval` allocation-free; added a randomized test that checks 7-card scores equal the best of the 21 five-card subsets, plus the 2,598,960-hand category-count test. |
| 4 | med | `play -hands -3` silently ran zero hands and printed "Session over". | Reject negative `-hands`. |
| 5 | med | `equity -n -5` silently fell back to the default sample count. | Reject `-n < 1`. |
| 6 | med | `-iters 0` on `exploit`/`show`/`match`/`play` produced a uniform "solved" strategy without complaint. | Validate `-iters ≥ 1` everywhere. |
| 7 | med | `match -vs nobody` reported `open nobody: no such file or directory`, hiding that bot names exist. | Unknown strategy names now list `solved`, the bots, and the JSON option. |
| 8 | med | Play UI said "P0 bets, P1 calls" and "Opponent calls" while the human is seat P1, with ungrammatical "You calls"; Kuhn view showed no pot. | Narration is now You/Opponent with correct verb forms; Kuhn shows the pot. |
| 9 | low | A scanner error (over-long input line) was swallowed as a silent quit. | Surface the error. |
| 10 | low | `hint` EVs were unlabeled — unclear whether they included antes. | Hint header states EV = final result for the hand incl. antes. |
| 11 | low | `pushfold` and `report` appear in `help` but were placeholders. | Implemented in phase 4 (stretch features 5, 6); verified there. |

## Things I attacked that held up
* Hostile ranges: `AAs`, `AA-KQ`, `AKs-AQo`, `Ah`, `AhAh`, empty, mixed pairs/non-pairs → all rejected with a message naming the token.
* Conflicting hands (`AhAs` vs `AhKd`), hands blocked by the board, duplicate board/dead cards, 2-card board → clear errors.
* River with a straight flush on board → 100% tie; two identical-strength hands chop exactly 50%.
* Best-response is checked by a property test: no scripted bot can beat the computed BR.
* Monte Carlo is seeded and uses a fixed worker count, so output is reproducible on any machine.
* Bad / mismatched strategy JSON (wrong game, missing infosets, probabilities not summing to 1, garbage) → errors.

## Known limitations (documented, not defects)
* Leduc/Kuhn information sets use card *ranks* (suits are irrelevant in Leduc), giving 288 Leduc infosets.
* Equity is Texas Hold'em only and does not model Omaha/short-deck.
* Exact enumeration is capped by `-exact-limit`; beyond that results are Monte Carlo with a reported standard error.

## Fresh run-through
After the fixes I re-ran every listed scenario (see `verify.sh` from phase 5); none of the issues above reproduce.
