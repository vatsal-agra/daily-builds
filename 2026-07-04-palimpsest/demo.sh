#!/usr/bin/env bash
# End-to-end demo/smoke test for Palimpsest, exercising every feature via the
# real CLI (not internal Python calls) exactly as a user would.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$HERE"
PLM="python3 -m palimpsest.cli"

PASS=0
FAIL=0

check() {
  local desc="$1"
  shift
  if "$@"; then
    echo "  ok  - $desc"
    PASS=$((PASS + 1))
  else
    echo "FAIL  - $desc"
    FAIL=$((FAIL + 1))
  fi
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cd "$WORK"

echo "=== unit test suite ==="
(cd "$HERE" && python3 -m unittest discover tests) 2>&1 | tail -5

echo
echo "=== R1: content-addressable object store (init/hash-object/cat-file) ==="
$PLM init repo >/dev/null
cd repo
echo "hello world" > a.txt
SHA=$($PLM hash-object -w a.txt)
check "hash-object matches git's well-known sha for 'hello world\\n'" \
  test "$SHA" = "3b18e512dba79e4c8300dd08aeb37f8e728b8dad"
check "cat-file returns the exact original bytes" \
  bash -c "[ \"\$($PLM cat-file $SHA)\" = \"hello world\" ]"

echo
echo "=== R2: staging + commit workflow (add/status/commit), incl. deletions ==="
$PLM add a.txt >/dev/null
check "status shows staged addition" bash -c "$PLM status | grep -q 'new file:   a.txt'"
$PLM commit -m "add a.txt" >/dev/null
check "status is clean right after commit" bash -c "$PLM status | grep -q 'nothing to commit'"
echo "modified" > a.txt
check "status detects unstaged modification" bash -c "$PLM status | grep -q 'modified:   a.txt'"
$PLM add a.txt >/dev/null
$PLM commit -m "modify a.txt" >/dev/null
rm a.txt
$PLM add a.txt >/dev/null
check "add stages a deletion of a tracked file" bash -c "$PLM status | grep -q 'deleted:    a.txt'"
$PLM commit -m "remove a.txt" >/dev/null
check "commit persists the deletion" bash -c "! test -e a.txt"

echo
echo "=== R3: branches, HEAD, checkout, log ==="
echo "trunk" > b.txt
$PLM add b.txt >/dev/null
$PLM commit -m "add b.txt on main" >/dev/null
$PLM branch feature >/dev/null
$PLM checkout feature >/dev/null
echo "on feature" >> b.txt
$PLM add b.txt >/dev/null
$PLM commit -m "feature edit" >/dev/null
$PLM checkout main >/dev/null
check "checkout restores main's version of b.txt" bash -c "[ \"\$(cat b.txt)\" = 'trunk' ]"
check "log shows commit history" bash -c "$PLM log | grep -q 'add b.txt on main'"

echo
echo "=== R4: Myers-diff-powered unified diff, incl. binary detection ==="
echo "line1" > c.txt
$PLM add c.txt >/dev/null
$PLM commit -m "add c.txt" >/dev/null
printf 'line1\nline2\n' > c.txt
check "diff shows the added line" bash -c "$PLM diff | grep -q '^+line2'"
printf 'a\x00b\xffc' > bin.dat
$PLM add bin.dat >/dev/null
$PLM commit -m "add binary" >/dev/null
printf 'a\x00b\xffCHANGED' > bin.dat
check "diff reports binary files differ, not garbage" bash -c "$PLM diff | grep -q 'Binary files'"

echo
echo "=== S1: three-way merge (clean merge + fast-forward + real conflict) ==="
cd "$WORK"
$PLM init ffrepo >/dev/null
cd ffrepo
echo "v1" > f.txt
$PLM add f.txt >/dev/null
$PLM commit -m "base" >/dev/null
$PLM branch feature >/dev/null
$PLM checkout feature >/dev/null
echo "v2" > f.txt
$PLM add f.txt >/dev/null
$PLM commit -m "advance" >/dev/null
$PLM checkout main >/dev/null
check "fast-forward merge advances main" bash -c "$PLM merge feature | grep -q 'Fast-forward'"

cd "$WORK"
$PLM init mergerepo >/dev/null
cd mergerepo
printf 'line1\nline2\nline3\n' > f.txt
$PLM add f.txt >/dev/null
$PLM commit -m "base" >/dev/null
$PLM branch feature >/dev/null
$PLM checkout feature >/dev/null
printf 'line1\nline2\nTHEIRS\n' > f.txt
$PLM add f.txt >/dev/null
$PLM commit -m "feature change" >/dev/null
$PLM checkout main >/dev/null
printf 'OURS\nline2\nline3\n' > f.txt
$PLM add f.txt >/dev/null
$PLM commit -m "main change" >/dev/null
check "clean 3-way merge combines both non-overlapping edits" \
  bash -c "$PLM merge feature | grep -q 'Merge made' && [ \"\$(cat f.txt)\" = \$'OURS\\nline2\\nTHEIRS' ]"

cd "$WORK"
$PLM init conflictrepo >/dev/null
cd conflictrepo
echo "base" > g.txt
$PLM add g.txt >/dev/null
$PLM commit -m "base" >/dev/null
$PLM branch feature >/dev/null
$PLM checkout feature >/dev/null
echo "FEATURE-SIDE" > g.txt
$PLM add g.txt >/dev/null
$PLM commit -m "feature edit" >/dev/null
$PLM checkout main >/dev/null
echo "MAIN-SIDE" > g.txt
$PLM add g.txt >/dev/null
$PLM commit -m "main edit" >/dev/null
set +e
$PLM merge feature > /tmp/merge_out.txt 2>&1
MERGE_STATUS=$?
set -e
check "conflicting merge reports failure and exits nonzero" test "$MERGE_STATUS" -ne 0
check "conflict markers are written to the working tree" bash -c "grep -q '<<<<<<< ours' g.txt"

echo
echo "=== S2: interactive HTML commit-graph visualizer ==="
cd "$WORK/mergerepo"
$PLM viz -o graph.html >/dev/null
check "viz produces a non-empty HTML file" bash -c "[ -s graph.html ]"
check "viz output embeds the commit messages" bash -c "grep -q 'main change' graph.html"
check "viz output is valid enough to contain a script tag" bash -c "grep -q '<script>' graph.html"

echo
echo "=== symlink correctness ==="
cd "$WORK"
$PLM init symrepo >/dev/null
cd symrepo
echo "target content" > target.txt
ln -s target.txt link.txt
$PLM add target.txt link.txt >/dev/null
$PLM commit -m "add symlink" >/dev/null
rm target.txt link.txt
$PLM checkout -f HEAD >/dev/null
check "checkout recreates a real symlink, not a copy" bash -c "[ -L link.txt ]"

echo
echo "================================================"
echo "demo.sh: $PASS passed, $FAIL failed"
echo "================================================"
[ "$FAIL" -eq 0 ]
