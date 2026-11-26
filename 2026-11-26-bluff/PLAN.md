# Bluff — PLAN

## Concept
**Bluff** is a poker game-theory laboratory in Go (stdlib only, one static binary).
It *solves* small poker games to Nash equilibrium with CFR+, *measures* how far any
strategy is from perfect with an exact best-response exploitability calculator,
*computes* Texas Hold'em equities for hand-vs-range and range-vs-range, and lets you
*play* against the solved strategy while it explains why it does what it does.

## Why it's interesting
Poker is the canonical imperfect-information game: you can't just search a tree, you
have to reason about what the opponent could hold. Counterfactual Regret Minimization
is the algorithm behind Libratus/Pluribus. Seeing a bot discover *bluffing* and
*slow-playing* from nothing but regret updates (Kuhn: bet the Jack 1/3 of the time) is
the payoff. Nothing in this repo touches game theory or poker yet.

## Architecture
```
game.go      generic extensive-form game interface (chance, 2 players, infosets)
kuhn.go      Kuhn poker (3 cards)            leduc.go   Leduc poker (6 cards, 2 rounds)
cfr.go       CFR+ (regret-matching+, linear averaging, alternating updates)
br.go        exact best response + exploitability + exact game value
strategy.go  strategy tables, JSON save/load, scripted bots
cards.go     cards + fast 7-card hand evaluator
ranges.go    hold'em range parser ("QQ+, AKs, A5s-A2s, 77-55, AhKd")
equity.go    exact enumeration / Monte-Carlo equity, multiway, board + dead cards
pushfold.go  heads-up push/fold Nash solver over the 169x169 class matchup matrix
play.go      interactive play + match simulator vs bots + strategy explainer
report.go    self-contained HTML report (convergence chart, strategy tables, push/fold grid)
main.go      CLI
```

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | CFR+ solver for any 2-player zero-sum game; Kuhn and Leduc poker implementations | **required** |
| 2 | Exact best-response + exploitability + exact game value (and EV of strategy vs strategy) | **required** |
| 3 | Hold'em 7-card evaluator + range parser + equity calculator (exact enumeration or seeded Monte-Carlo, multiway, board, dead cards) | **required** |
| 4 | Play against the solved strategy interactively (with per-decision explanation) and `match` simulation vs bots with win-rate ± stderr | **required** |
| 5 | Heads-up push/fold Nash solver for any stack depth (169-class matrix, card-removal-aware) | stretch |
| 6 | Self-contained HTML report: convergence chart, strategy tables, push/fold 13x13 grids | stretch |
| 7 | Strategy JSON save/load so solved strategies can be re-analysed | stretch |

## Verification targets (known theory)
* Kuhn game value for player 1 = −1/18 ≈ −0.05556; P1 bets Jack with prob α∈[0,1/3].
* Leduc game value ≈ −0.0856 for player 1; CFR+ exploitability < 0.01 chips in ~1000 iters.
* Hold'em: AA vs KK ≈ 81.9 %, AKs vs QQ ≈ 46 %, 7-card evaluator ranks all 133,784,560 … (spot-checked categories counts over 5-card hands: 2,598,960 totals).
