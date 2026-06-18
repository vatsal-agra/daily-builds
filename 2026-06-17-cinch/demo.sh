#!/usr/bin/env bash
# Cinch end-to-end demonstration. Pure stdlib; no arguments needed.
set -euo pipefail
cd "$(dirname "$0")"

echo "############################################################"
echo "# Cinch — from-scratch compression toolkit"
echo "############################################################"

echo
echo ">>> 1. Compression-ratio leaderboard (Cinch vs stdlib zlib/bz2/lzma)"
python3 cli.py bench

echo
echo ">>> 2. Round-trip every method on a real file (this script itself)"
python3 cli.py roundtrip "$0"

echo
echo ">>> 3. Compress -> inspect -> decompress, with CRC verification"
TMP="$(mktemp -d)"
python3 cli.py compress cli.py -o "$TMP/cli.cinch" -m auto
python3 cli.py inspect "$TMP/cli.cinch"
python3 cli.py decompress "$TMP/cli.cinch" -o "$TMP/cli.back"
if cmp -s cli.py "$TMP/cli.back"; then
  echo "decompressed output is byte-identical to the original: OK"
else
  echo "MISMATCH!"; exit 1
fi
rm -rf "$TMP"

echo
echo ">>> 4. Generate the interactive HTML visualizer"
python3 cli.py viz --text "the quick brown fox the quick brown fox jumps" -o cinch_viz.html
echo "open cinch_viz.html in a browser to watch LZ77 + Huffman"

echo
echo ">>> 5. Built-in demo (corruption detection etc.)"
python3 cli.py demo

echo
echo ">>> 6. Test suite (light fuzz for speed; use 'python3 tests.py' for full)"
CINCH_FUZZ=400 python3 tests.py 2>&1 | tail -3

echo
echo "All demo steps completed."
