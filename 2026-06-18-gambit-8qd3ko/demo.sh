#!/usr/bin/env bash
# Gambit end-to-end demo + test suite. Pure Python 3 stdlib, no dependencies.
set -e
cd "$(dirname "$0")"

echo "###############################################################"
echo "#  GAMBIT — running the full test suite                       #"
echo "###############################################################"
python3 -m unittest discover -s tests -v

echo
echo "###############################################################"
echo "#  GAMBIT — end-to-end feature demo                           #"
echo "###############################################################"
python3 -m gambit.cli demo

echo
echo "###############################################################"
echo "#  GAMBIT — generating the HTML self-play replay viewer       #"
echo "###############################################################"
python3 -m gambit.cli viz --depth 4 --maxmoves 50 --out gambit_game.html
echo "Open gambit_game.html in a browser to watch the engine play itself."
