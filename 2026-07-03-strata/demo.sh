#!/usr/bin/env bash
# End-to-end demo/verification script: exercises every Strata feature
# through the real CLI in a scratch directory, printing each command and
# its output so a human can read this as a walkthrough. Exits non-zero
# on the first unexpected failure.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR:${PYTHONPATH:-}"
STRATA="python3 -m strata"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT
cd "$WORKDIR"

step() { echo; echo "=== $1 ==="; }
run() { echo "\$ $*"; "$@"; }

step "1/9  Object store: init a repo"
run $STRATA init repo
cd repo
run $STRATA config user.name "Demo User"
run $STRATA config user.email "demo@strata.dev"

step "2/9  Add / status / commit / log"
mkdir -p src/lib
echo "print('hello')" > src/lib/main.py
echo "# Strata demo" > README.md
run $STRATA add src README.md
run $STRATA status
run $STRATA commit -m "Initial commit"
run $STRATA log

step "3/9  Branching & checkout"
run $STRATA branch feature
run $STRATA checkout feature
echo "print('hello v2')" > src/lib/main.py
run $STRATA add src/lib/main.py
run $STRATA commit -m "Update main.py on feature"
run $STRATA checkout main
if grep -q "hello v2" src/lib/main.py; then
  echo "FAIL: checkout did not restore main's version"; exit 1
fi
echo "checkout correctly restored main's version of the file"

step "4/9  Myers diff"
run $STRATA diff main feature

step "5/9  Fast-forward merge"
run $STRATA merge feature
if ! grep -q "hello v2" src/lib/main.py; then
  echo "FAIL: fast-forward merge did not apply feature's change"; exit 1
fi
echo "fast-forward merge correctly applied feature's change"

step "6/9  Three-way merge WITH a real conflict"
run $STRATA branch branchA
run $STRATA branch branchB
run $STRATA checkout branchA
echo "line one" > conflict.txt
run $STRATA add conflict.txt
run $STRATA commit -m "branchA: add conflict.txt"
run $STRATA checkout branchB
echo "line two" > conflict.txt
run $STRATA add conflict.txt
run $STRATA commit -m "branchB: add conflict.txt"
set +e
$STRATA merge branchA
MERGE_RC=$?
set -e
if [ "$MERGE_RC" -eq 0 ]; then
  echo "FAIL: expected a merge conflict, got success"; exit 1
fi
if ! grep -q "<<<<<<<" conflict.txt; then
  echo "FAIL: no conflict markers written"; exit 1
fi
echo "conflict correctly detected and marked"
printf "line one\nline two\n" > conflict.txt
run $STRATA add conflict.txt
run $STRATA commit -m "Resolve conflict"
run $STRATA log
if [ "$($STRATA log | grep -c '^Merge:')" -lt 1 ]; then
  echo "FAIL: resolved merge did not produce a 2-parent merge commit"; exit 1
fi
echo "resolved merge correctly recorded a 2-parent merge commit"

step "7/9  Staged deletion"
run $STRATA status
rm README.md
run $STRATA add README.md
run $STRATA commit -m "Remove README"
if [ -f README.md ]; then echo "FAIL: README.md should be gone"; exit 1; fi
echo "deletion correctly committed"

step "8/9  Safety: refuses to clobber untracked files on checkout"
run $STRATA checkout main 2>/dev/null || true  # main branch, just to have a stable point
echo "untracked scratch content" > scratch-collision.txt
run $STRATA add scratch-collision.txt
run $STRATA commit -m "add scratch-collision.txt on this branch"
run $STRATA branch no-scratch
run $STRATA checkout no-scratch
rm scratch-collision.txt
run $STRATA add scratch-collision.txt
run $STRATA commit -m "remove scratch-collision.txt"
echo "MY UNTRACKED WORK" > scratch-collision.txt
set +e
$STRATA checkout "$($STRATA branch | grep -v no-scratch | tail -1 | tr -d '* ')" 2>/tmp/strata-demo-stderr
CHECKOUT_RC=$?
set -e
if [ "$CHECKOUT_RC" -eq 0 ]; then
  echo "FAIL: checkout should have refused to clobber the untracked file"; exit 1
fi
if [ "$(cat scratch-collision.txt)" != "MY UNTRACKED WORK" ]; then
  echo "FAIL: untracked file content was overwritten"; exit 1
fi
echo "checkout correctly refused to clobber untracked work (see /tmp/strata-demo-stderr)"
cat /tmp/strata-demo-stderr
rm -f scratch-collision.txt
run $STRATA checkout no-scratch --force

step "9/9  Interactive HTML commit-graph visualizer"
run $STRATA viz -o graph.html
if [ ! -s graph.html ]; then echo "FAIL: graph.html is empty"; exit 1; fi
if ! grep -q "<!doctype html>" graph.html; then echo "FAIL: not a valid HTML doc"; exit 1; fi
if ! grep -q "const DATA = " graph.html; then echo "FAIL: no embedded graph data"; exit 1; fi
echo "visualizer wrote a $(wc -c < graph.html)-byte self-contained HTML file"

echo
echo "================================================================"
echo "ALL 9 DEMO STEPS PASSED — every required and stretch feature works"
echo "================================================================"
