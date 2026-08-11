#!/usr/bin/env bash
# Runs the full test suite, then a real CLI demo of every feature, then
# builds the HTML report -- end to end, no shortcuts. Exits non-zero on
# the first real failure.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "== 1/4  full test suite =="
python3 -m unittest discover -s tests -v

echo
echo "== 2/4  dynamic-programming oracle on every gridworld env =="
for env in gridworld cliffwalking windygridworld frozenlake; do
  python3 -m bellman.cli dp "$env"
  echo
done

echo "== 3/4  tabular agents + on-policy/off-policy divergence =="
python3 -m bellman.cli tabular qlearning gridworld --episodes 800
python3 -m bellman.cli tabular sarsa cliffwalking --episodes 800
python3 -m bellman.cli tabular montecarlo frozenlake --episodes 3000
python3 -m bellman.cli cliff-compare --episodes 800

echo
echo "== 4/4  function approximation on CartPole (DQN + REINFORCE) =="
# short smoke runs here -- the CLI plumbing (args, training loop, eval,
# clean output) is what's under test in this step. The real, full-scale,
# hard-numeric-pass-bar training run already happened above inside
# tests/test_dqn.py + tests/test_reinforce.py (260/350 episodes each,
# exactly what the report below also uses), so re-paying that ~7-minute
# cost a third time here would just be wasted wall-clock, not more signal.
python3 -m bellman.cli dqn --episodes 30
python3 -m bellman.cli reinforce --episodes 30

echo
echo "== building the HTML report (full-scale training run) =="
python3 -m bellman.cli report --out report.html
echo "wrote report.html"

echo
echo "ALL GREEN."
