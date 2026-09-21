#!/usr/bin/env python3
"""Phase 4 stretch feature #6: starts the server-backed interactive play
UI. Requires at least one trained checkpoint for each game you want to
serve (run scripts/run_training_ttt.py / run_training_c4.py first)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sente.server import run

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    run(port=port)
