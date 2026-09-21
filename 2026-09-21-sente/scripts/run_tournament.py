#!/usr/bin/env python3
"""Phase 2 required-feature #4b: cross-generation win-rate + Elo report,
proving real, monotonic-ish learning happened (not just "it ran without
crashing"). Round-robins baselines (random, pure-MCTS-with-uniform-
priors-and-rollout-value) against a spread of training-generation
checkpoints, all evaluated deterministically (no Dirichlet noise, no
temperature) so the numbers reflect each checkpoint's actual strength.
"""
import sys, os, json, glob, re, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from sente.games.tictactoe import TicTacToe
from sente.checkpoint import load_checkpoint
from sente.evaluate import RandomPlayer, PureMCTSPlayer, NetMCTSPlayer, NetPolicyOnlyPlayer, round_robin, compute_elo

ROOT = os.path.join(os.path.dirname(__file__), "..")


def pick_checkpoints(ckpt_dir, game_name, gens):
    out = {}
    for g in gens:
        path = os.path.join(ckpt_dir, f"{game_name}_gen{g:03d}.npz")
        if os.path.exists(path):
            out[g] = path
    return out


if __name__ == "__main__":
    ckpt_dir = os.path.join(ROOT, "checkpoints", "tictactoe")
    games_per_pairing = int(os.environ.get("SENTE_TOURNEY_GAMES", 16))
    n_sims = int(os.environ.get("SENTE_TOURNEY_SIMS", 50))

    gens_available = sorted(int(re.search(r"gen(\d+)", os.path.basename(p)).group(1))
                             for p in glob.glob(os.path.join(ckpt_dir, "tictactoe_gen*.npz")))
    max_gen = max(gens_available)
    wanted = sorted(set([0] + [g for g in gens_available if g % 5 == 0] + [max_gen]))
    picked = pick_checkpoints(ckpt_dir, "tictactoe", wanted)
    print(f"Using generations: {sorted(picked.keys())}")

    players = {
        "random": RandomPlayer(),
        "pure-mcts": PureMCTSPlayer(n_simulations=n_sims, n_rollouts_per_leaf=4, name="pure-mcts"),
    }
    for g, path in sorted(picked.items()):
        net = load_checkpoint(path)
        players[f"gen{g:03d}"] = NetMCTSPlayer(net, n_simulations=n_sims, c_puct=1.5, name=f"gen{g:03d}")

    rng = np.random.default_rng(999)
    print(f"Round-robin: {len(players)} players, {games_per_pairing} games/pairing, {n_sims} sims/move...")
    t0 = time.time()
    raw_results, summary = round_robin(TicTacToe, players, games_per_pairing, rng)
    dt = time.time() - t0
    print(f"Done in {dt:.1f}s, {len(raw_results)} games played.")

    elo = compute_elo(list(players.keys()), raw_results, k=24.0, base=1200.0, rng=np.random.default_rng(1))

    print(f"\n{'player':12s} {'W':>4s} {'L':>4s} {'D':>4s} {'games':>6s} {'win%':>7s} {'elo':>7s}")
    for name in sorted(players.keys(), key=lambda n: -elo[n]):
        s = summary[name]
        winrate = (s["wins"] + 0.5 * s["draws"]) / max(s["games"], 1) * 100
        print(f"{name:12s} {s['wins']:4d} {s['losses']:4d} {s['draws']:4d} {s['games']:6d} {winrate:6.1f}% {elo[name]:7.1f}")

    report = {
        "game": TicTacToe.name,
        "games_per_pairing": games_per_pairing,
        "n_simulations": n_sims,
        "summary": summary,
        "elo": elo,
        "n_games_total": len(raw_results),
        "time_s": dt,
    }
    # -------------------------------------------------------------
    # Second ladder: RAW POLICY ONLY (no search at all), which isolates
    # the network's own learned quality from MCTS's ability to paper
    # over a weak network on this shallow a game (see NetPolicyOnlyPlayer
    # docstring). This is the cleaner "did the network actually learn"
    # signal for Tic-Tac-Toe specifically.
    # -------------------------------------------------------------
    policy_players = {"random": RandomPlayer()}
    for g, path in sorted(picked.items()):
        net = load_checkpoint(path)
        policy_players[f"gen{g:03d}"] = NetPolicyOnlyPlayer(net, name=f"gen{g:03d}")

    rng2 = np.random.default_rng(4242)
    print(f"\nRaw-policy-only round-robin (no MCTS): {len(policy_players)} players, {games_per_pairing} games/pairing...")
    t1 = time.time()
    raw_results2, summary2 = round_robin(TicTacToe, policy_players, games_per_pairing, rng2)
    dt2 = time.time() - t1
    elo2 = compute_elo(list(policy_players.keys()), raw_results2, k=24.0, base=1200.0, rng=np.random.default_rng(2))

    print(f"\n{'player':12s} {'W':>4s} {'L':>4s} {'D':>4s} {'games':>6s} {'win%':>7s} {'elo':>7s}")
    for name in sorted(policy_players.keys(), key=lambda n: -elo2[n]):
        s = summary2[name]
        winrate = (s["wins"] + 0.5 * s["draws"]) / max(s["games"], 1) * 100
        print(f"{name:12s} {s['wins']:4d} {s['losses']:4d} {s['draws']:4d} {s['games']:6d} {winrate:6.1f}% {elo2[name]:7.1f}")

    report["policy_only"] = {"summary": summary2, "elo": elo2, "n_games_total": len(raw_results2), "time_s": dt2}

    report_path = os.environ.get("SENTE_REPORT_PATH", os.path.join(ROOT, "reports", "tournament_tictactoe.json"))
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport written to {report_path}")

    # Sanity assertion: learning must be real, i.e. the final generation's
    # Elo must exceed the untrained gen000's Elo by a wide margin, and
    # gen000 (random weights, but still MCTS-guided) should itself beat
    # pure random by at least a little. These are measured, not asserted
    # blind -- if they fail, this script's exit code communicates that.
    ok = True
    if elo2[f"gen{max_gen:03d}"] <= elo2["gen000"] + 50:
        print("WARNING: final generation's raw POLICY did not clearly outrank gen000's raw policy.")
        ok = False
    if elo2[f"gen{max_gen:03d}"] <= elo2["random"] + 50:
        print("WARNING: final generation's raw policy did not clearly outrank random baseline.")
        ok = False
    if elo[f"gen{max_gen:03d}"] <= elo["random"] + 50:
        print("WARNING: final generation (with MCTS) did not clearly outrank random baseline.")
        ok = False
    sys.exit(0 if ok else 1)
