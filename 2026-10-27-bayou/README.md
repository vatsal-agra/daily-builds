# Bayou

A from-scratch **Bayesian-network engine** in Go (standard library only).

**Status: Phase 2 complete — the four required features work end to end.** See `PLAN.md` for the
full feature list; the README is rewritten for the final release in Phase 6.

## Try it
```
go build -o bayou ./cmd/bayou
./bayou query examples/asia.bn -q Tuberculosis,LungCancer -e XRay=abnormal,Smoking=yes
./bayou mpe   examples/asia.bn -e Dyspnea=yes,XRay=abnormal
./bayou dsep  examples/asia.bn -x Tuberculosis -y LungCancer -z Either
./bayou sample examples/student.bn -n 20000 -o data.csv && ./bayou learn examples/student.bn data.csv --truth examples/student.bn
```

## Required features (done)
1. Model language (`.bn`) + BIF import/export + validation + CSV data reader
2. Exact inference by variable elimination: posteriors, P(evidence), MPE and marginal-MAP
3. Junction tree (Shafer–Shenoy calibration, all marginals in one pass) + d-separation, Markov blankets
4. Parameter learning: forward sampling, smoothed MLE, EM for missing/latent data
