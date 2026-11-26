# Bluff — a poker game-theory lab in Go

Bluff **solves** small poker games to Nash equilibrium with CFR+, **proves** how close any strategy
is to perfect with an exact best-response engine, **computes** Texas Hold'em equities for hands and
ranges, **solves heads-up push/fold** charts for any stack depth, and lets you **play** the solved
strategy while it explains its choices. Go standard library only; one static binary; ~3,700 lines including tests.

```
$ bluff solve leduc
leduc: 9451 nodes, 288 info sets
    iter  exploitability
       1  1.986111
      64  0.009422
    2048  0.000009
game value for player 0 (first to act): -0.08561      ← the published Leduc value is −0.0856
```

## Run it

```bash
cd 2026-11-26-bluff
go build -o bluff .
./bluff help
./verify.sh          # end-to-end demo + assertions (20 checks) and go test
go test ./...        # 27 tests (add -race to check the parallel Monte Carlo)
```

| Command | What it does |
|---|---|
| `bluff solve <kuhn\|leduc> [-iters N] [-out s.json]` | CFR+ with exploitability curve; optionally save the strategy |
| `bluff exploit <game> <solved\|bot\|file.json>` | exact exploitability + best-response value of any strategy |
| `bluff show <game> [-strategy S]` | print the strategy table |
| `bluff equity [-board Ah7d2c] [-dead ..] r1 r2 …` | 2–6 player equity; ranges like `"QQ+,AKs,A5s-A2s,77-55,AhKd,random"` |
| `bluff play <game> [-strategy S] [-seat 0\|1] [-hands N]` | play against the solver; type `hint` for equilibrium advice with per-action EVs |
| `bluff match <game> -vs BOT [-hands N]` | simulate solved strategy vs a bot, with exact EV and ideal-exploiter win rate |
| `bluff pushfold -stack 10 [-hand A5s]` | heads-up Nash shove/call ranges as 13×13 grids |
| `bluff report -out report.html` | self-contained HTML report with charts, strategies and push/fold grids |

Strategy specs: `solved` (default), bots `station` (never folds/raises), `maniac` (always max aggression),
`nit` (folds to everything), `random`, or a strategy JSON file produced by `solve -out`.

## Features shipped

1. **CFR+ solver** (regret-matching+, alternating updates, linear averaging) over a generic two-player zero-sum extensive-form game interface; **Kuhn** and **Leduc** poker implemented on it. Game trees are compiled once into arrays and perfect recall is validated.
2. **Exact best response & exploitability** — info sets resolved deepest-first; also exact game values, strategy-vs-strategy EV, and per-action hint values.
3. **Hold'em equity** — allocation-free 5–7 card evaluator (verified against the 2,598,960-hand category counts and a best-of-21 cross-check), range parser, exact enumeration when feasible, otherwise seeded & reproducible parallel Monte Carlo with standard errors; multiway, board and dead cards.
4. **Interactive play** with equilibrium hints and a **match simulator** against scripted bots (simulation vs exact EV).
5. *(stretch)* **Push/fold Nash solver** — 169×169 class-matchup equity matrix with exact card-removal weights, CFR+ over shove/call, reports exploitability (~0 bb). 10 bb: SB shoves 58 %, BB calls 37 %, matching published charts.
6. *(stretch)* **HTML report** — log-log convergence charts, strategy bar charts, bot-exploitation table, push/fold grids; light/dark themed, mobile-safe.
7. *(stretch)* **Strategy JSON save/load** with strict validation (wrong game, missing info sets, bad probabilities all rejected).

Verification highlights: Kuhn value −1/18 and the α/3α/⅓ equilibrium family; Leduc value −0.0856; best response can't be beaten by any bot (property test); 4-way mutation checks catch deliberate bugs. See [PLAN.md](PLAN.md) and [REVIEW.md](REVIEW.md) (the adversarial review found two critical bugs that only showed up when comparing to the literature value).

## Why I chose this today

The ledger had hundreds of entries on compilers, data structures and simulations but nothing on
**imperfect-information games**. Poker is where "search the tree" fails and you must reason about what
the opponent could hold; watching an algorithm discover bluffing from nothing but regret updates is a
great payoff, and an exact exploitability number gives an honest, unfakeable correctness gate.

## Where a human could take this next

* Scale up: chance/external-sampling MCCFR, card abstraction, and a limit hold'em or river-subgame solver.
* Postflop solving: use the equity engine as leaf evaluator for a flop-subgame solver with bet-size abstraction.
* Push/fold extensions: ante, non-effective stacks, 3-handed ICM-aware shove charts.
* Bot-exploit mode: opponent modelling from observed hands, then a safe best response.
* A web UI for `play` with the hint panel beside the table.
