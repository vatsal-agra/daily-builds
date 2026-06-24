#!/usr/bin/env bash
# demo.sh — Cadence end-to-end showcase
# Run from inside the 2026-06-24-cadence/ directory:
#   bash demo.sh

set -euo pipefail
cd "$(dirname "$0")"

echo "============================================================"
echo "  Cadence — music synthesizer demo"
echo "============================================================"
echo

mkdir -p demo_output

echo "--- Waveform info ---"
python cadence.py info
echo

echo "--- Synthesizing individual waveforms ---"
for WAVE in sine sawtooth rsaw square triangle pulse; do
    python cadence.py synth --note A4 --waveform "$WAVE" --duration 1.5 \
        --output "demo_output/waveform_${WAVE}.wav"
    echo "  wrote demo_output/waveform_${WAVE}.wav"
done
echo

echo "--- Composing all four styles ---"
python cadence.py compose --key C   --style pop        --bars 8 --seed 42 \
    --output demo_output/pop.wav        --html demo_output/pop.html
python cadence.py compose --key Am  --style jazz       --bars 8 --seed 7  \
    --output demo_output/jazz.wav       --html demo_output/jazz.html
python cadence.py compose --key D   --style ambient    --bars 8 --seed 99 \
    --output demo_output/ambient.wav    --html demo_output/ambient.html
python cadence.py compose --key Gm  --style electronic --bars 8 --seed 13 \
    --output demo_output/electronic.wav --html demo_output/electronic.html
echo

echo "--- Running test suite ---"
python tests/test_cadence.py
echo

echo "============================================================"
echo "  Done! Output files:"
ls demo_output/
echo
echo "  Open any .html file in a browser to listen and see the"
echo "  waveform, FFT spectrum, and piano roll visualizer."
echo "============================================================"
