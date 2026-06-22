#!/usr/bin/env bash
# Coda demo script — run from inside the 2026-06-22-coda/ directory

set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "Coda — MIDI Synthesizer & Procedural Music Generator"
echo "============================================================"
echo ""

# 1. Generate a major-scale piece
echo ">> Generating C major piece (32 bars, jazz drums, 120 BPM)..."
python3 cli.py generate --key 60 --scale major --bpm 120 --bars 32 \
    --drums jazz --seed 42 --out piece_major.mid

# 2. Show MIDI info
echo ""
echo ">> MIDI file info:"
python3 cli.py info piece_major.mid

# 3. Render to WAV
echo ""
echo ">> Rendering to WAV..."
python3 cli.py render piece_major.mid --out piece_major.wav

# 4. Render with effects
echo ""
echo ">> Rendering with reverb + delay + LPF..."
python3 cli.py render piece_major.mid --out piece_major_fx.wav --reverb --delay --lpf

# 5. Generate a minor piece
echo ""
echo ">> Generating A minor piece (rock drums, 140 BPM)..."
python3 cli.py generate --key 57 --scale minor --bpm 140 --bars 32 \
    --drums rock --seed 7 --out piece_minor.mid
python3 cli.py render piece_minor.mid --out piece_minor.wav

# 6. Generate a blues piece
echo ""
echo ">> Generating G blues piece (electronic drums, 110 BPM)..."
python3 cli.py generate --key 55 --scale blues --bpm 110 --bars 32 \
    --drums electronic --seed 2026 --out piece_blues.mid
python3 cli.py render piece_blues.mid --out piece_blues.wav

# 7. Generate piano roll visualizers
echo ""
echo ">> Generating piano roll HTML visualizers..."
python3 cli.py viz piece_major.mid --title "C Major — Jazz Drums"
python3 cli.py viz piece_minor.mid --title "A Minor — Rock Drums"
python3 cli.py viz piece_blues.mid --title "G Blues — Electronic"

echo ""
echo "============================================================"
echo "All outputs generated:"
echo "  piece_major.mid / .wav / _roll.html"
echo "  piece_minor.mid / .wav / _roll.html"
echo "  piece_blues.mid / .wav / _roll.html"
echo "  piece_major_fx.wav (with reverb + delay + LPF)"
echo ""
echo "Open any *_roll.html in a browser to visualize and play back."
echo "============================================================"
