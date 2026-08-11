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
python3 -m bellman.cli dqn --episodes 260
python3 -m bellman.cli reinforce --episodes 350

echo
echo "== building the HTML report =="
python3 -m bellman.cli report --out report.html
echo "wrote report.html"

echo
echo "ALL GREEN."
