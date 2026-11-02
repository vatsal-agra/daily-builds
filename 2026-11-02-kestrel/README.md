# Kestrel
Multi-target radar tracking laboratory (Go, stdlib only).

**Status: Phase 4 — stretch features (IMM, RTS smoother, JPDA, HTML report) added and polished.** The four required features work end to end:

1. Linear Kalman filter (Joseph form) with NEES/NIS chi-square consistency testing — `kestrel consistency -filter kf`
2. EKF and UKF on nonlinear radar range/bearing — `kestrel consistency -filter ukf -sensor radar`
3. Chi-square gating + Hungarian optimal assignment (GNN) with Pd/clutter likelihood-ratio costs
4. Track lifecycle (M-of-N confirm, coast, delete, duplicate merge), scenario simulator, OSPA scoring — `kestrel run -scenario swarm`

Try: `go build -o kestrel ./cmd/kestrel && ./kestrel run -scenario manoeuvre -filter imm-ekf -tracks`

(Stretch work — IMM, JPDA — is already wired in but not yet reviewed; full docs arrive in Phase 6.)
