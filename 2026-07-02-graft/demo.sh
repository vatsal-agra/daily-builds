#!/usr/bin/env bash
# Runnable demo of every Graft feature. Exits non-zero on the first failure.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GRAFT="python3 $HERE/bin/graft"
DEMO_DIR="$(mktemp -d)"
trap 'rm -rf "$DEMO_DIR"' EXIT

step() { echo; echo "=== $1 ==="; }
check() { echo "  ok: $1"; }

cd "$DEMO_DIR"

step "1. init + object store"
$GRAFT init . > /dev/null
[ -d .graft/objects ] || { echo "FAIL: no object store"; exit 1; }
check "repository initialized"

echo "hello world" > greeting.txt
SHA=$($GRAFT hash-object -w greeting.txt)
GIT_SHA=$(command -v git > /dev/null && git hash-object greeting.txt || echo "$SHA")
[ "$SHA" = "$GIT_SHA" ] || { echo "FAIL: hash mismatch with real git"; exit 1; }
check "blob hash byte-identical to real git ($SHA)"

step "2. staging area, status, commit"
$GRAFT add greeting.txt
$GRAFT status | grep -q "new file:   greeting.txt"
check "staged file shows in status"
$GRAFT commit -m "initial commit" --date 1000000000 > /dev/null
$GRAFT status | grep -q "nothing to commit"
check "committed, working tree clean"

step "3. history, branching, checkout"
$GRAFT branch feature
$GRAFT branch | grep -q "feature"
check "branch created"
echo "more" >> greeting.txt
$GRAFT add greeting.txt
$GRAFT commit -m "second commit" --date 1000000001 > /dev/null
$GRAFT log | grep -q "second commit"
$GRAFT log | grep -q "initial commit"
check "log shows full history"
$GRAFT checkout feature > /dev/null
[ "$(cat greeting.txt)" = "hello world" ] || { echo "FAIL: checkout didn't restore old content"; exit 1; }
check "checkout restored feature branch's older file content"
$GRAFT checkout main > /dev/null

step "4. Myers diff"
echo "hello world" > diff_test.txt
$GRAFT add diff_test.txt
$GRAFT commit -m "diff base" --date 1000000002 > /dev/null
echo "hello graft" > diff_test.txt
$GRAFT diff | grep -q '^-hello world$'
$GRAFT diff | grep -q '^+hello graft$'
check "unified diff shows correct hunk"
$GRAFT checkout main -f > /dev/null

step "5. three-way merge (clean)"
printf '1\n2\n3\n4\n5\n' > merge_test.txt
$GRAFT add merge_test.txt
$GRAFT commit -m "merge base" --date 1000000003 > /dev/null
$GRAFT branch merge-feature
printf '1-OURS\n2\n3\n4\n5\n' > merge_test.txt
$GRAFT add merge_test.txt
$GRAFT commit -m "ours" --date 1000000004 > /dev/null
$GRAFT checkout merge-feature > /dev/null
printf '1\n2\n3\n4\n5-THEIRS\n' > merge_test.txt
$GRAFT add merge_test.txt
$GRAFT commit -m "theirs" --date 1000000005 > /dev/null
$GRAFT checkout main > /dev/null
$GRAFT merge merge-feature | grep -q "Merge made"
[ "$(cat merge_test.txt)" = "$(printf '1-OURS\n2\n3\n4\n5-THEIRS\n')" ] || { echo "FAIL: clean merge content wrong"; exit 1; }
check "non-conflicting edits merged cleanly"

step "6. three-way merge (conflict) + resolution"
printf 'x\ny\nz\n' > conflict_test.txt
$GRAFT add conflict_test.txt
$GRAFT commit -m "conflict base" --date 1000000006 > /dev/null
$GRAFT branch conflict-feature
printf 'x\nOURS\nz\n' > conflict_test.txt
$GRAFT add conflict_test.txt
$GRAFT commit -m "ours edit" --date 1000000007 > /dev/null
$GRAFT checkout conflict-feature > /dev/null
printf 'x\nTHEIRS\nz\n' > conflict_test.txt
$GRAFT add conflict_test.txt
$GRAFT commit -m "theirs edit" --date 1000000008 > /dev/null
$GRAFT checkout main > /dev/null
set +e
MERGE_OUT=$($GRAFT merge conflict-feature)
set -e
echo "$MERGE_OUT" | grep -q "CONFLICT" || { echo "FAIL: expected a reported conflict"; echo "$MERGE_OUT"; exit 1; }
grep -q "<<<<<<<" conflict_test.txt
check "genuine conflict correctly flagged with markers"
printf 'x\nRESOLVED\nz\n' > conflict_test.txt
$GRAFT add conflict_test.txt
$GRAFT commit -m "resolve conflict" > /dev/null
$GRAFT log | grep -q "Merge:"
check "merge commit recorded with two parents after resolution"

step "7. packfiles + gc"
for i in $(seq 1 8); do
  echo "packed file number $i with shared boilerplate text" > "pack$i.txt"
  $GRAFT add "pack$i.txt"
done
$GRAFT commit -m "many files for packing" --date 1000000009 > /dev/null
GC_OUT=$($GRAFT gc)
echo "$GC_OUT" | grep -q "Packed"
check "gc packed loose objects ($GC_OUT)"
$GRAFT status | grep -q "nothing to commit"
[ "$(cat pack3.txt)" = "packed file number 3 with shared boilerplate text" ] || { echo "FAIL: content lost after gc"; exit 1; }
check "file content intact after gc"

step "8. HTML commit visualizer"
$GRAFT viz -o graph.html > /dev/null
[ -s graph.html ] || { echo "FAIL: viz produced no output"; exit 1; }
grep -q "<html>" graph.html
check "graph.html generated ($(wc -c < graph.html) bytes)"

step "9. error handling"
set +e
$GRAFT add does-not-exist.txt 2> /tmp/graft_demo_err.txt
[ $? -ne 0 ] || { echo "FAIL: should have failed"; exit 1; }
grep -q "pathspec" /tmp/graft_demo_err.txt
set -e
check "bad pathspec fails cleanly with a message, not a traceback"

echo
echo "=== ALL DEMO STEPS PASSED ==="
