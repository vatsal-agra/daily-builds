"""The self-play + iterative-training generation loop: generate self-play
games with the current network+MCTS, push (board, MCTS visit-policy,
outcome) tuples into a bounded replay buffer, train the network on
minibatches sampled from that buffer with Adam, checkpoint, repeat.

This is the actual reinforcement-learning loop: the only training labels
that ever exist are ones the search itself produced by playing the
current network against itself. Nothing here is supervised on an
external dataset.
"""

from __future__ import annotations
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np

from .nn.network import PolicyValueNet
from .nn.optim import Adam
from .replay_buffer import ReplayBuffer
from .selfplay import self_play_game
from .checkpoint import save_checkpoint


@dataclass
class TrainConfig:
    n_generations: int = 10
    games_per_generation: int = 40
    n_simulations: int = 80
    c_puct: float = 1.5
    dirichlet_alpha: float = 0.3
    dirichlet_eps: float = 0.25
    temp_moves: int = 4
    hidden_sizes: tuple = (64, 64)
    buffer_size: int = 30000
    batch_size: int = 64
    train_steps_per_generation: int = 200
    lr: float = 1e-3
    l2: float = 1e-4
    seed: int = 0
    checkpoint_dir: Optional[str] = None
    log_every: int = 1


def run_training(game, config: TrainConfig, log_fn=print):
    rng = np.random.default_rng(config.seed)
    net = PolicyValueNet(game.input_dim, game.action_size, hidden_sizes=config.hidden_sizes, seed=config.seed)
    optimizer = Adam(net.all_layers(), lr=config.lr)
    buffer = ReplayBuffer(max_size=config.buffer_size, seed=config.seed)

    checkpoint_paths: List[str] = []
    history = []

    if config.checkpoint_dir:
        os.makedirs(config.checkpoint_dir, exist_ok=True)
        gen0_path = os.path.join(config.checkpoint_dir, f"{game.name}_gen000.npz")
        save_checkpoint(net, gen0_path)
        checkpoint_paths.append(gen0_path)

    for gen in range(1, config.n_generations + 1):
        t0 = time.time()
        outcomes = {1: 0, -1: 0, 0: 0}
        n_examples_before = len(buffer)
        for _ in range(config.games_per_generation):
            examples, winner = self_play_game(
                game, net,
                n_simulations=config.n_simulations, c_puct=config.c_puct,
                dirichlet_alpha=config.dirichlet_alpha, dirichlet_eps=config.dirichlet_eps,
                temp_moves=config.temp_moves, rng=rng, augment=True,
            )
            buffer.add_game(examples)
            outcomes[winner] += 1
        selfplay_time = time.time() - t0

        t1 = time.time()
        losses = {"total": 0.0, "policy": 0.0, "value": 0.0}
        n_steps = 0
        if len(buffer) >= config.batch_size:
            for _ in range(config.train_steps_per_generation):
                x, mask, pi, z = buffer.sample(config.batch_size)
                step_losses = net.loss_and_backward(x, mask, pi, z, l2=config.l2)
                optimizer.step()
                for k in ("total", "policy", "value"):
                    losses[k] += step_losses[k]
                n_steps += 1
            for k in losses:
                losses[k] /= max(n_steps, 1)
        train_time = time.time() - t1

        ckpt_path = None
        if config.checkpoint_dir:
            ckpt_path = os.path.join(config.checkpoint_dir, f"{game.name}_gen{gen:03d}.npz")
            save_checkpoint(net, ckpt_path)
            checkpoint_paths.append(ckpt_path)

        record = {
            "generation": gen,
            "selfplay_outcomes": dict(outcomes),
            "buffer_size": len(buffer),
            "new_examples": len(buffer) - n_examples_before if len(buffer) < config.buffer_size else config.games_per_generation,
            "losses": losses,
            "selfplay_time_s": selfplay_time,
            "train_time_s": train_time,
            "checkpoint": ckpt_path,
        }
        history.append(record)
        if gen % config.log_every == 0:
            log_fn(f"[gen {gen:3d}] selfplay X/O/draw={outcomes[1]:>3}/{outcomes[-1]:>3}/{outcomes[0]:>3} "
                   f"buffer={len(buffer):5d} loss(total/pol/val)="
                   f"{losses['total']:.4f}/{losses['policy']:.4f}/{losses['value']:.4f} "
                   f"time(sp/tr)={selfplay_time:.1f}s/{train_time:.1f}s")

    return net, history, checkpoint_paths
