#!/usr/bin/env bash
# Gambit end-to-end demo: exercises every feature and runs the test suite.
set -e
cd "$(dirname "$0")"

echo "############################################################"
echo "# Gambit — full feature demo"
echo "############################################################"

echo
echo ">>> 1. Verify move generation against published perft counts (depth 3)"
python3 -m gambit.cli perft 3 --verify

echo
echo ">>> 2. Perft divide on the start position (depth 2)"
python3 -m gambit.cli perft 2 --divide | tail -n 3

echo
echo ">>> 3. Analyse a tactical position"
python3 -m gambit.cli analyse --depth 4 \
  --fen 'r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4'

echo
echo ">>> 4. Find a forced mate"
python3 -m gambit.cli analyse --depth 4 --fen '6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1' | tail -n 8

echo
echo ">>> 5. Engine vs engine game (PGN) + write JSON"
python3 -m gambit.cli selfplay --depth 3 --max-moves 30 --quiet --json /tmp/gambit_game.json
python3 -m gambit.cli selfplay --depth 3 --max-moves 30 --quiet 2>/dev/null | tail -n 2

echo
echo ">>> 6. Emit the interactive HTML game viewer"
python3 -m gambit.cli viz --depth 3 --max-moves 30 --out /tmp/gambit_game.html --quiet | tail -n 2

echo
echo ">>> 7. Full self-checking demo"
python3 -m gambit.cli demo | tail -n 20

echo
echo ">>> 8. Run the test suite"
python3 -m unittest tests.test_gambit 2>&1 | tail -n 4

echo
echo "All demo steps completed."
