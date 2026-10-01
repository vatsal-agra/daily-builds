#!/usr/bin/env bash
# End-to-end demo: exercises every Skein feature on a generated 400k-line access log.
set -euo pipefail
cd "$(dirname "$0")"
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
go build -o "$W/skein" ./cmd/skein; S="$W/skein"

echo "== generating 400k-line Zipf-distributed log (user<TAB>latency_ms)"
python3 - "$W" <<'PY'
import random, sys
w = sys.argv[1]; r = random.Random(7)
keys = [f"user{i}" for i in range(40000)]
wt = [1/(i+1)**1.1 for i in range(40000)]
ks = r.choices(keys, weights=wt, k=400000)
fa, fb, fall = (open(f"{w}/{n}.tsv", "w") for n in ("a", "b", "all"))
for i, k in enumerate(ks):
    line = f"{k}\t{r.lognormvariate(3, .8):.3f}\n"
    fall.write(line); (fa if i % 2 == 0 else fb).write(line)
PY

echo; echo "== 1. HyperLogLog: distinct users, checked against exact"
$S count -f 1 -exact "$W/all.tsv"
echo; echo "== 2. Count-Min + SpaceSaving: one-pass stats (also saves state)"
$S stats -f 1 -v 2 -show 5 -o "$W/all.skn" "$W/all.tsv"
echo; echo "== 3. t-digest: latency quantiles vs exact"
$S quantile -v 2 -q 0.5,0.99,0.999 -exact "$W/all.tsv"
echo; echo "== 4. Sharded: stats per shard, merge, compare with single pass"
$S stats -f 1 -v 2 -o "$W/a.skn" "$W/a.tsv" >/dev/null 2>&1
$S stats -f 1 -v 2 -o "$W/b.skn" "$W/b.tsv" >/dev/null 2>&1
$S merge -o "$W/m.skn" "$W/a.skn" "$W/b.skn"
$S inspect "$W/m.skn"; $S inspect "$W/all.skn"
echo; echo "== 5. Membership: Bloom (1% FP) and Cuckoo (deletable)"
$S member build -f 1 -n 40000 -o "$W/bloom.skn" "$W/all.tsv"
$S member check "$W/bloom.skn" user7 not-a-user || echo "(exit $? = some key absent)"
$S member build -cuckoo -f 1 -n 41000 -o "$W/cuckoo.skn" "$W/all.tsv"
$S member del "$W/cuckoo.skn" user7
$S member check "$W/cuckoo.skn" user7 user8 || echo "(exit $? = some key absent)"
echo; echo "== 6. MinHash / LSH: near-duplicate detection"
cat > "$W/docs.txt" <<'EOT'
Breaking: city council approves new transit budget after lengthy debate
Breaking: city council approves new transit budget after long debate
Recipe: slow roasted tomato soup with basil and garlic
Breaking: city council approves the new transit budget after lengthy debate
Local team wins championship in dramatic overtime thriller
EOT
$S dups -t 0.5 -shingle 2 "$W/docs.txt"
echo; echo "== 7. Accuracy report"
$S report -quick -o "$W/report.html"; test -s "$W/report.html" && echo "report OK ($(wc -c < "$W/report.html") bytes)"
echo; echo "DEMO COMPLETE"
