#!/usr/bin/env bash
# Backjump — end-to-end demo + test driver. Exercises every feature.
set -e
cd "$(dirname "$0")"

echo "############################################################"
echo "# 1. Test suite (42 tests: solver, proofs, encoders, viz)  #"
echo "############################################################"
python3 -m unittest discover -s tests

echo
echo "############################################################"
echo "# 2. Guided feature tour                                   #"
echo "############################################################"
python3 bj.py demo

echo
echo "############################################################"
echo "# 3. 3-SAT phase transition (the satisfiability cliff)     #"
echo "############################################################"
python3 bj.py phase --vars 40 --samples 30 --steps 10

echo
echo "############################################################"
echo "# 4. Differential fuzz: 2000 instances vs brute force      #"
echo "############################################################"
python3 bj.py fuzz --trials 2000 --vars 10 --seed 17

echo
echo "############################################################"
echo "# 5. Generate the three example visualizers                #"
echo "############################################################"
mkdir -p examples
python3 bj.py viz color  --cycle 5 --k 3 --out examples/coloring.html
python3 bj.py viz pigeon --pigeons 4 --holes 3 --out examples/pigeonhole.html
python3 bj.py viz queens --n 6 --out examples/queens6.html
echo "Open examples/*.html in a browser to step through a real solve."

echo
echo "All demo stages completed."
