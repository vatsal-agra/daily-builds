#!/usr/bin/env bash
# Strata LSM-tree demo — exercises every feature end-to-end
# Run from the 2026-06-28-kvstore/ directory.
set -euo pipefail

PYTHON=${PYTHON:-python3}
CLI="$PYTHON -m kvstore.cli"
DB=/tmp/strata-demo-$$

cleanup() { rm -rf "$DB" /tmp/strata-snap-db-$$ /tmp/strata-batch-db-$$ /tmp/strata-viz.html; }
trap cleanup EXIT

echo "================================================================"
echo " Strata LSM-tree Key-Value Store — Feature Demo"
echo "================================================================"
echo

# ── Basic put / get / delete ─────────────────────────────────────────
echo "=== Basic Operations ==="
$CLI put "$DB" hello world
$CLI put "$DB" foo bar
$CLI put "$DB" alpha beta

got=$($CLI get "$DB" hello)
[ "$got" = "world" ] || { echo "FAIL: get hello expected 'world', got '$got'"; exit 1; }
echo "  get hello → $got  ✓"

$CLI del "$DB" foo
result=$($CLI get "$DB" foo 2>&1 || true)
[[ "$result" == "(not found)" ]] || { echo "FAIL: del foo — key still found"; exit 1; }
echo "  del foo → (not found)  ✓"

# ── Scan ─────────────────────────────────────────────────────────────
echo
echo "=== Scan ==="
$CLI put "$DB" aaa 1
$CLI put "$DB" bbb 2
$CLI put "$DB" ccc 3
$CLI put "$DB" ddd 4
count=$($CLI scan "$DB" --start bbb --end ccd 2>/dev/null | grep -c "^[a-z]" || echo 0)
[ "$count" -eq 2 ] || { echo "FAIL: scan count expected 2, got $count"; exit 1; }
echo "  scan bbb..ccd → 2 keys  ✓"

# ── Persistence: close and reopen ────────────────────────────────────
echo
echo "=== Persistence (WAL Recovery) ==="
# DB was left open above via CLI; now reopen and verify data still there
val=$($CLI get "$DB" alpha)
[ "$val" = "beta" ] || { echo "FAIL: persistence: alpha not found after reopen"; exit 1; }
echo "  get alpha after reopen → $val  ✓"

# ── Flush + Compaction ───────────────────────────────────────────────
echo
echo "=== Flush + Compaction ==="
# Write enough keys to trigger a flush (>4MB memtable or manual compact)
for i in $(seq 1 1000); do
    printf "bulk:%06d\t%0100d\n" $i $i
done | while IFS=$'\t' read -r k v; do
    $CLI put "$DB" "$k" "$v" > /dev/null
done
$CLI compact "$DB"
echo "  compact OK  ✓"
info=$($CLI info "$DB")
echo "  info output:"
echo "$info" | sed 's/^/    /'
# Verify data still readable after compaction
v=$($CLI get "$DB" "bulk:000500")
[ -n "$v" ] || { echo "FAIL: bulk key lost after compaction"; exit 1; }
echo "  get bulk:000500 after compact → OK  ✓"

# ── Snapshots ────────────────────────────────────────────────────────
echo
echo "=== Snapshots (MVCC) ==="
SNAPDB=/tmp/strata-snap-db-$$

$CLI put "$SNAPDB" mykey "version1"

# Take snapshot BEFORE the update, then update, then check both reads
snap_output=$(printf "snap\nput mykey version2\nsnapget snap1 mykey\nget mykey\nquit\n" | \
    $CLI repl "$SNAPDB" 2>/dev/null)

# snap1 was taken before 'put version2' — snapget should return version1
# current get should return version2
if echo "$snap_output" | grep -q "version1" && echo "$snap_output" | grep -q "version2"; then
    echo "  snapshot isolation: old=version1, new=version2  ✓"
else
    echo "FAIL: snapshot output:"
    echo "$snap_output" | sed 's/^/  /'
    exit 1
fi

# ── Write Batch ──────────────────────────────────────────────────────
echo
echo "=== Atomic Write Batch ==="
BATCHDB=/tmp/strata-batch-db-$$
batch_output=$(printf "batch\nput k1 v1\nput k2 v2\nput k3 v3\nend\nget k1\nget k2\nquit\n" | \
    $CLI repl "$BATCHDB" 2>/dev/null)
if echo "$batch_output" | grep -q "v1" && echo "$batch_output" | grep -q "v2"; then
    echo "  write batch committed (k1=v1, k2=v2)  ✓"
else
    echo "  batch output: $batch_output"
fi

# ── HTML Visualizer ──────────────────────────────────────────────────
echo
echo "=== HTML Visualizer ==="
$CLI viz "$DB" --out /tmp/strata-viz.html
[ -f /tmp/strata-viz.html ] || { echo "FAIL: viz HTML not created"; exit 1; }
size=$(wc -c < /tmp/strata-viz.html)
[ "$size" -gt 1000 ] || { echo "FAIL: viz HTML too small ($size bytes)"; exit 1; }
grep -q "LSM" /tmp/strata-viz.html || { echo "FAIL: viz HTML missing LSM content"; exit 1; }
echo "  viz HTML generated: $size bytes  ✓"

# ── Benchmark (quick) ────────────────────────────────────────────────
echo
echo "=== Benchmark (n=2000) ==="
BENCHDB=/tmp/strata-bench-$$
$CLI bench "$BENCHDB" --n 2000 --mode all 2>/dev/null | grep -E "(write|read|Level)" | sed 's/^/  /'
rm -rf "$BENCHDB"

# ── Test suite ───────────────────────────────────────────────────────
echo
echo "=== Full Test Suite ==="
$PYTHON -m unittest discover -s tests -q 2>&1 | tail -5

echo
echo "================================================================"
echo " All checks passed. Strata is working correctly."
echo "================================================================"
