#!/usr/bin/env python3
"""Connect Four Jr stretch-feature evaluation: cross-generation win-rate
vs random and pure-MCTS-no-network baselines. There is no minimax oracle
for Connect Four (even the reduced size), so optimality is NOT claimed --
only a measured win-rate margin, honestly reported (see README.md /
REVIEW.md)."""
import sys, os, json, glob, re, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from sente.games.connect4 import Connect4Jr
from sente.checkpoint import load_checkpoint
from sente.evaluate import RandomPlayer, PureMCTSPlayer, NetMCTSPlayer, NetPolicyOnlyPlayer, round_robin, compute_elo

ROOT = os.path.join(os.path.dirname(__file__), "..")

if __name__ == "__main__":
    ckpt_dir = os.path.join(ROOT, "checkpoints", "connect4jr")
    games_per_pairing = int(os.environ.get("SENTE_TOURNEY_GAMES", 20))
    n_sims = int(os.environ.get("SENTE_TOURNEY_SIMS", 80))

    gens_available = sorted(int(re.search(r"gen(\d+)", os.path.basename(p)).group(1))
                             for p in glob.glob(os.path.join(ckpt_dir, "connect4jr_gen*.npz")))
    max_gen = max(gens_available)
    wanted = sorted(set([0] + [g for g in gens_available if g % 10 == 0] + [max_gen]))
    picked = {g: os.path.join(ckpt_dir, f"connect4jr_gen{g:03d}.npz") for g in wanted
              if os.path.exists(os.path.join(ckpt_dir, f"connect4jr_gen{g:03d}.npz"))}
    print(f"Using generations: {sorted(picked.keys())}")

    players = {
        "random": RandomPlayer(),
        "pure-mcts": PureMCTSPlayer(n_simulations=n_sims, n_rollouts_per_leaf=4, name="pure-mcts"),
    }
    for g, path in sorted(picked.items()):
        net = load_checkpoint(path)
        players[f"gen{g:03d}"] = NetMCTSPlayer(net, n_simulations=n_sims, c_puct=1.5, name=f"gen{g:03d}")

    rng = np.random.default_rng(777)
    print(f"Round-robin: {len(players)} players, {games_per_pairing} games/pairing, {n_sims} sims/move...")
    t0 = time.time()
    raw_results, summary = round_robin(Connect4Jr, players, games_per_pairing, rng)
    dt = time.time() - t0
    print(f"Done in {dt:.1f}s, {len(raw_results)} games played.")

    elo = compute_elo(list(players.keys()), raw_results, k=24.0, base=1200.0, rng=np.random.default_rng(1))

    print(f"\n{'player':12s} {'W':>4s} {'L':>4s} {'D':>4s} {'games':>6s} {'win%':>7s} {'elo':>7s}")
    for name in sorted(players.keys(), key=lambda n: -elo[n]):
        s = summary[name]
        winrate = (s["wins"] + 0.5 * s["draws"]) / max(s["games"], 1) * 100
        print(f"{name:12s} {s['wins']:4d} {s['losses']:4d} {s['draws']:4d} {s['games']:6d} {winrate:6.1f}% {elo[name]:7.1f}")

    # Head-to-head margin vs baselines specifically for the final generation,
    # which is the number the README/PLAN honesty commitment is about
    # ("beats random and pure-MCTS by a wide margin").
    final_name = f"gen{max_gen:03d}"
    print(f"\nDedicated head-to-head: {final_name} vs random / pure-mcts ({games_per_pairing*3} games each)...")
    rng2 = np.random.default_rng(31415)
    hth_players_r = {final_name: players[final_name], "random": players["random"]}
    raw_r, summary_r = round_robin(Connect4Jr, hth_players_r, games_per_pairing * 3, rng2)
    hth_players_m = {final_name: players[final_name], "pure-mcts": players["pure-mcts"]}
    raw_m, summary_m = round_robin(Connect4Jr, hth_players_m, games_per_pairing * 3, rng2)

    def winrate_of(summary, name):
        s = summary[name]
        return (s["wins"] + 0.5 * s["draws"]) / max(s["games"], 1) * 100

    margin_random = winrate_of(summary_r, final_name)
    margin_mcts = winrate_of(summary_m, final_name)
    print(f"  {final_name} vs random:    {margin_random:.1f}% win rate ({summary_r[final_name]})")
    print(f"  {final_name} vs pure-mcts: {margin_mcts:.1f}% win rate ({summary_m[final_name]})")

    report = {
        "game": Connect4Jr.name,
        "games_per_pairing": games_per_pairing,
        "n_simulations": n_sims,
        "summary": summary,
        "elo": elo,
        "n_games_total": len(raw_results),
        "time_s": dt,
        "final_generation": final_name,
        "head_to_head": {
            "vs_random_winrate_pct": margin_random,
            "vs_pure_mcts_winrate_pct": margin_mcts,
            "vs_random_summary": summary_r[final_name],
            "vs_pure_mcts_summary": summary_m[final_name],
        },
    }
    report_path = os.environ.get("SENTE_REPORT_PATH", os.path.join(ROOT, "reports", "tournament_connect4jr.json"))
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport written to {report_path}")

    ok = margin_random >= 80.0 and margin_mcts >= 60.0
    if not ok:
        print(f"WARNING: margin not as wide as hoped (random>=80% target: {margin_random:.1f}%, "
              f"pure-mcts>=60% target: {margin_mcts:.1f}%). Reporting the real numbers regardless.")
    sys.exit(0)
