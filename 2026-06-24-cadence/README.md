# Cadence

> Phase 2 in progress — see PLAN.md for full feature list.

A modular music synthesizer and procedural composer from scratch in pure Python.

## Quick start

```bash
# Compose a pop piece
python cadence.py compose --key C --style pop --bpm 120 --bars 8 --html out.html

# Compose a jazz piece
python cadence.py compose --key Am --style jazz --bars 8

# Synthesize a single note
python cadence.py synth --note A4 --waveform sawtooth --duration 2

# Full demo (all styles)
python cadence.py demo --output-dir demo_output

# Print info
python cadence.py info
```

## Status

- Phase 1 (PLAN): ✅
- Phase 2 (Core build): ✅
- Phase 3 (Review): 🔄
- Phase 4 (Stretch + Polish): 🔄
- Phase 5 (Verification): 🔄
- Phase 6 (Ship): 🔄
