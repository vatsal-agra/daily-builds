#!/usr/bin/env python3
"""Phase 2 required-feature #3 demonstration: end-to-end self-play +
iterative training on Tic-Tac-Toe, from a randomly-initialized network to
a demonstrably strong player. Writes a JSON training report + checkpoints
that later scripts (oracle check, tournament) consume.
"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sente.games.tictactoe import TicTacToe
from sente.train import TrainConfig, run_training

ROOT = os.path.join(os.path.dirname(__file__), "..")
CKPT_DIR = os.path.join(ROOT, "checkpoints", "tictactoe")
REPORT_PATH = os.path.join(ROOT, "reports", "training_tictactoe.json")

if __name__ == "__main__":
    config = TrainConfig(
        n_generations=int(os.environ.get("SENTE_GENERATIONS", 25)),
        games_per_generation=int(os.environ.get("SENTE_GAMES_PER_GEN", 30)),
        n_simulations=int(os.environ.get("SENTE_SIMS", 60)),
        c_puct=1.5,
        dirichlet_alpha=0.6,
        dirichlet_eps=0.25,
        temp_moves=2,
        hidden_sizes=(48, 48),
        buffer_size=8000,
        batch_size=64,
        train_steps_per_generation=150,
        lr=2e-3,
        l2=1e-4,
        seed=0,
        checkpoint_dir=CKPT_DIR,
    )
    print(f"Training Sente on {TicTacToe.name} with config: {config}")
    t0 = time.time()
    net, history, checkpoint_paths = run_training(TicTacToe, config)
    total_time = time.time() - t0
    print(f"Done in {total_time:.1f}s. {len(checkpoint_paths)} checkpoints saved to {CKPT_DIR}")

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump({
            "game": TicTacToe.name,
            "config": {k: (list(v) if isinstance(v, tuple) else v) for k, v in vars(config).items()},
            "total_time_s": total_time,
            "history": history,
            "checkpoints": checkpoint_paths,
        }, f, indent=2)
    print(f"Report written to {REPORT_PATH}")
