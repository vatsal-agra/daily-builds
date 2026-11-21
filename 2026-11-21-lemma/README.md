# Lemma

A from-scratch **dependent-type proof assistant** (Python, stdlib only).

*Status: Phases 1–4 done — kernel, inductive families, elaborator, tactic prover, library, independent auditor,
HTML proof-state report, REPL, adversarial review ([REVIEW.md](REVIEW.md)). Tests and the full write-up follow.* See [PLAN.md](PLAN.md).

```
python -m lemma check examples/*.lm --audit
python -m lemma report examples/nat.lm -o report.html
python -m lemma repl
```
