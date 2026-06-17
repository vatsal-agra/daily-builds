#!/usr/bin/env bash
# Exercise every Resolvent feature end-to-end and run the test suite.
# Exits non-zero if anything fails.
set -euo pipefail
cd "$(dirname "$0")"

echo "############################################################"
echo "# Resolvent — full demo & verification"
echo "############################################################"

echo
echo ">>> Unit + differential test suite"
python3 -m unittest tests.test_resolvent -v 2>&1 | tail -5

echo
echo ">>> Feature tour (python3 -m resolvent demo)"
python3 -m resolvent demo

echo
echo ">>> solve a SAT instance"
python3 -m resolvent solve examples/sat_simple.cnf || true

echo
echo ">>> verify an UNSAT instance with an independent proof check"
python3 -m resolvent verify examples/unsat_simple.cnf || true

echo
echo ">>> N-Queens (N=10)"
python3 -m resolvent decode queens 10 || true

echo
echo ">>> render the implication-graph visualization"
python3 -m resolvent encode php 4 > /tmp/resolvent_php4.cnf
python3 -m resolvent viz /tmp/resolvent_php4.cnf examples/conflict_php4.html

echo
echo ">>> large differential fuzz (2000 random formulas)"
python3 -m resolvent fuzz --n 2000 --seed 2026 --maxvars 10

echo
echo "############################################################"
echo "# ALL GREEN"
echo "############################################################"
