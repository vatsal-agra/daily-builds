# Kripke — symbolic model checker (in progress)

Status after **phase 3 (adversarial review)**: core + LTL + explicit oracle + bit-vector ints + sifting + HTML report + generators
are built; 15 review findings fixed (see [REVIEW.md](REVIEW.md), replay with `./review_check.sh`).

Try: `cargo run --release -- examples/peterson.smv` · `kripke gen philosophers 4 | kripke /dev/stdin --stutter`

See [PLAN.md](PLAN.md). Full README is written in phase 6.
