# Sente

A from-scratch AlphaZero-style self-play reinforcement-learning game
engine: PUCT Monte Carlo Tree Search guided by a learned policy+value
neural network, where the network is trained purely from data the search
generates against itself.

**Status: Phase 1 (plan) complete.** See `PLAN.md` for the full design,
the novelty check against this repo's history, and the feature list.
Nothing is implemented yet — this file will be filled in with real run
output, exact commands, and measured results as each phase lands.

## Planned layout

```
sente/
  games/        Game interface + Tic-Tac-Toe + Connect Four Jr (5x4, 4-in-a-row)
  nn/           hand-derived Linear/ReLU/Tanh/losses, gradcheck, Adam, PolicyValueNet
  mcts.py       generic PUCT MCTS
  selfplay.py   self-play game generation
  replay_buffer.py
  train.py      self-play -> train -> checkpoint generation loop
  oracle_tictactoe.py   independent minimax oracle
  evaluate.py   oracle invariant check + tournament/Elo
  server.py     (stretch) browser play server
scripts/        CLI entry points for each phase
tests/          unit + integration tests
checkpoints/    saved network weights per generation
reports/        generated evaluation reports (oracle check, Elo ladder)
```

Why Tic-Tac-Toe + a 5x4 "Connect Four Jr": see `PLAN.md`.
