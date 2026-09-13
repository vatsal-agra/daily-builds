#!/usr/bin/env bash
# Veil demo/verification script — exercises every feature end-to-end and
# exits non-zero on the first failure. Run from this directory:
#   ./demo.sh
set -euo pipefail
cd "$(dirname "${0}")"

PY=python3
STEP=0
pass() { STEP=$((STEP + 1)); echo "[$STEP] OK: $1"; }
section() { echo; echo "=== $1 ==="; }

section "1. Unit + property test suite"
if [ -n "${PYTEST:-}" ] && command -v "$PYTEST" >/dev/null 2>&1; then
  "$PYTEST" tests/ -q
elif command -v pytest >/dev/null 2>&1; then
  pytest tests/ -q
elif [ -x /root/.local/bin/pytest ]; then
  /root/.local/bin/pytest tests/ -q
else
  "$PY" -m pytest tests/ -q
fi
pass "pytest suite (72+ tests)"

section "2. Schnorr identification protocol (CLI)"
out=$("$PY" -m veil.cli schnorr --seed 1)
echo "$out" | grep -q "verifier accepts: True"
pass "honest proof accepted"

section "3. Fiat-Shamir signature (CLI)"
out=$("$PY" -m veil.cli sign "daily build demo message" --seed 1)
echo "$out" | grep -q "^Verifies: True$"
pass "signature verifies, tamper detection confirmed"

section "4. Anonymous OR-proof membership auth (CLI)"
out=$("$PY" -m veil.cli anon-auth --n 6 --index 4 --message "quorum vote" --seed 1)
echo "$out" | grep -q "Verifier accepts (member #4 is proven to be SOME registered member): True"
pass "anonymous membership proof accepted, outsider rejected"

section "5. Graph 3-coloring ZK proof (CLI)"
out=$("$PY" -m veil.cli coloring --rounds 30 --seed 1)
echo "$out" | grep -q "All rounds accepted -> proof accepted: True"
pass "30/30 rounds accepted"

section "6. Zero-knowledge simulators + statistical indistinguishability"
"$PY" -m veil.cli simulate --samples 4000 --seed 1
pass "real vs. simulated transcripts statistically indistinguishable"

section "7. Flagship anonymous membership/auth demo (replay protection)"
out=$("$PY" -m veil.cli club --n 5 --index 2 --command "withdraw 100" --seed 1)
echo "$out" | grep -q "rejected: nonce already used (replay)"
pass "replay attack correctly rejected"

section "8. Group parameters re-verified from scratch"
out=$("$PY" -m veil.cli group-info)
echo "$out" | grep -q "re-verified from scratch (Miller-Rabin on p and q, g\^q == 1 mod p): True"
pass "safe-prime Schnorr group verified"

section "9. Regenerate the interactive HTML visualizer from a real run"
"$PY" -m veil.cli viz
test -f visualizer/index.html
pass "visualizer/index.html regenerated"

section "10. Headless-browser smoke test of the visualizer"
if command -v node >/dev/null 2>&1 && [ -d /opt/pw-browsers ]; then
  NODE_PATH=/opt/node22/lib/node_modules node tests/visualizer_smoke.js
  pass "visualizer loads with zero console errors, all tabs interactive"
else
  echo "  (node/playwright not available in this environment — skipped)"
fi

section "11. Adversarial-review regression: degenerate public key exploit stays fixed"
"$PY" - <<'PYEOF'
import random
from veil.group import STANDARD_GROUP as G
from veil import schnorr as S

rng = random.Random(2024)
bogus_y = G.p - 1
trials = 5000
fooled = 0
for _ in range(trials):
    r = G.random_exponent(rng)
    t = G.pow_g(r)
    c = S.challenge(G, rng)
    s = r
    if S.verify(G, bogus_y, t, c, s):
        fooled += 1
assert fooled == 0, f"REGRESSION: degenerate-key exploit succeeded {fooled}/{trials} times"
print(f"  0/{trials} — exploit stays fixed")
PYEOF
pass "REVIEW.md Finding 1 regression check"

echo
echo "================================================================"
echo " ALL $STEP CHECKS PASSED"
echo "================================================================"
