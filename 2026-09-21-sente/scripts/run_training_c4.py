#!/usr/bin/env python3
"""Phase 4 stretch feature #5: the identical self-play + MCTS + from-
scratch-net pipeline, generalized to Connect Four Jr (5 cols x 4 rows,
4-in-a-row). No new game logic in the training loop itself -- only
`sente/games/connect4.py` differs from Tic-Tac-Toe's run."""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sente.games.connect4 import Connect4Jr
from sente.train import TrainConfig, run_training

ROOT = os.path.join(os.path.dirname(__file__), "..")
CKPT_DIR = os.path.join(ROOT, "checkpoints", "connect4jr")
REPORT_PATH = os.path.join(ROOT, "reports", "training_connect4jr.json")

if __name__ == "__main__":
    config = TrainConfig(
        n_generations=int(os.environ.get("SENTE_GENERATIONS", 50)),
        games_per_generation=int(os.environ.get("SENTE_GAMES_PER_GEN", 40)),
        n_simulations=int(os.environ.get("SENTE_SIMS", 60)),
        c_puct=1.5,
        dirichlet_alpha=0.5,
        dirichlet_eps=0.25,
        temp_moves=6,
        hidden_sizes=(64, 64),
        buffer_size=30000,
        batch_size=128,
        train_steps_per_generation=200,
        lr=1.5e-3,
        l2=1e-4,
        seed=0,
        checkpoint_dir=CKPT_DIR,
    )
    print(f"Training Sente on {Connect4Jr.name} ({Connect4Jr.rows}x{Connect4Jr.cols}) with config: {config}")
    t0 = time.time()
    net, history, checkpoint_paths = run_training(Connect4Jr, config)
    total_time = time.time() - t0
    print(f"Done in {total_time:.1f}s. {len(checkpoint_paths)} checkpoints saved to {CKPT_DIR}")

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump({
            "game": Connect4Jr.name,
            "config": {k: (list(v) if isinstance(v, tuple) else v) for k, v in vars(config).items()},
            "total_time_s": total_time,
            "history": history,
            "checkpoints": checkpoint_paths,
        }, f, indent=2)
    print(f"Report written to {REPORT_PATH}")
