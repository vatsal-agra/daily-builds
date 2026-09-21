#!/usr/bin/env python3
"""Phase 2 required-feature #4a: the ground-truth "never loses to perfect
play" invariant, checked exhaustively against the independent minimax
oracle, for the agent playing BOTH sides."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from sente.games.tictactoe import TicTacToe
from sente.checkpoint import load_checkpoint
from sente.evaluate import oracle_invariant_check, NetMCTSPlayer

ROOT = os.path.join(os.path.dirname(__file__), "..")

if __name__ == "__main__":
    ckpt_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "checkpoints", "tictactoe", "tictactoe_gen025.npz")
    n_sims = int(os.environ.get("SENTE_ORACLE_SIMS", 100))
    print(f"Loading checkpoint: {ckpt_path}")
    net = load_checkpoint(ckpt_path)
    agent = NetMCTSPlayer(net, n_simulations=n_sims, c_puct=1.5, name="sente-ttt")
    rng = np.random.default_rng(12345)

    print(f"Running exhaustive oracle invariant check ({n_sims} sims/move, argmax, zero Dirichlet noise)...")
    t0 = time.time()
    passed, stats = oracle_invariant_check(TicTacToe, agent, rng)
    dt = time.time() - t0

    result = {"checkpoint": ckpt_path, "n_simulations": n_sims, "passed": passed, "time_s": dt, **stats}
    print(json.dumps(result, indent=2))

    report_path = os.path.join(ROOT, "reports", "oracle_invariant_check.json")
    with open(report_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Report written to {report_path}")

    if not passed:
        print("FAILED: agent lost to perfect play at least once.")
        sys.exit(1)
    print("PASSED: agent never lost to perfect play, playing either side, across the full explored tree.")
