# Ashenkeep

> Status: **Feature-complete and polished.** All 4 required features, both
> planned stretch features, and a bonus final-floor boss encounter are
> implemented, adversarially reviewed, and verified. See
> [`PLAN.md`](./PLAN.md) for the design and [`REVIEW.md`](./REVIEW.md) for
> the review findings.

A browser-playable roguelike dungeon crawler built entirely from scratch in
vanilla JavaScript — procedural dungeons, real recursive-shadowcasting
field-of-view, A*-driven enemy AI, turn-based combat, and a full
loot/inventory/equipment system.

## Run it

```bash
cd 2026-08-31-ashenkeep
python3 -m http.server 8000
# open http://localhost:8000/index.html
```

No build step, no `npm install` needed to play — it's plain `<script>` tags.

## Run the tests

```bash
node --test tests/*.js     # 87 unit/integration tests (dungeon, fov, astar, entities, items, combat, game)
node tests/ui_smoke.mjs    # headless-Chromium smoke test of the real page, light + dark
```

`REVIEW.md` documents three independent stress harnesses run beyond the
unit suite: a 1,400-generation dungeon-connectivity fuzz (0 failures), and
two 60-seed full-playthrough bots (0 crashes either way) — a naive one and
an equip-aware one that genuinely **wins the game** (defeats the floor-10
boss and escapes) a meaningful fraction of the time, proof the win
condition is reachable through play, not just asserted in a unit test.

## Full feature list

**Required:**
1. Procedural BSP dungeon generation with provable connectivity and
   farthest-room stairs placement.
2. Recursive-shadowcasting field-of-view / fog of war.
3. Turn-based combat with A*-driven monster AI and player leveling.
4. Inventory & equipment (weapons/armor/rings/potions/scrolls) fully wired
   into the turn loop.

**Stretch:**
5. Multi-floor descent (10 floors, scaling difficulty) with `localStorage`
   save/load and permadeath.
6. Procedural loot rarity/affix tiers (common → magic → rare → epic) and a
   fog-of-war-respecting minimap.
7. *(bonus, added in polish)* A named final boss, **The Keeper of
   Ashenkeep**, standing on floor 10's stairs — the player is structurally
   unable to reach the winning tile without defeating it first.

**Polish:** a bespoke dark-fantasy UI (not default browser styling), a
torchlit-vignette + textured-stone renderer, save-corruption/version
guards, a destructive-action confirmation before discarding a save, and
inline error messaging instead of silent failures.

## Why this project today

This repo's history is dense with from-scratch **systems and algorithms**
(SAT solvers, compilers, a CPU pipeline simulator, a dozen GPT-style
transformers) but had almost never shipped a complete, playable **game**
with real stakes and a win/lose condition — Gambit (chess) is the closest
precedent, and that's a solved, deterministic board game with no
procedural content. A roguelike forces several classic algorithms (BSP
generation, shadowcasting, A*, a loot-affix system) to compose into one
coherent, permadeath experience where a single miscalculation ruins the
run rather than just failing a unit test.

## Where a human could take this next

- **Ranged/spell abilities** — right now every fight is melee-adjacent;
  a thrown potion or a scroll-cast projectile would add real tactical depth.
- **More boss variety** — one named boss on floor 10; a mid-run boss
  (floor 5?) with a different attack pattern would raise the stakes earlier.
- **Diagonal movement/8-directional FOV octant reuse is already there** —
  the FOV and A* modules would support it with a small `DIRS8` addition;
  it was left out deliberately so corridors (1 tile wide) can't be
  diagonally corner-cut.
- **A real leaderboard** — score (floor reached, level, turns) is computed
  but only shown to the single player; a shared high-score list would need
  a backend this project deliberately has none of.
- **Sound** — Waveforge (2026-07-21, this repo) already has a from-scratch
  synth engine; wiring its oscillators to combat/level-up events would be
  a natural crossover.

## What's implemented so far (required features)

1. **Procedural dungeon generation** — `src/dungeon.js`: BSP partitioning,
   one room per leaf, L-shaped corridors connecting the tree bottom-up
   (provably fully connected), stairs placed at the room farthest from the
   start by real walking distance.
2. **Field-of-view / fog of war** — `src/fov.js`: recursive shadowcasting
   over 8 octants; walls block sight around corners; explored tiles stay
   dimly visible on the minimap and main view once left.
3. **Turn-based combat with A\* enemy AI** — `src/astar.js` + `src/combat.js`
   + `src/game.js`: monsters that spot the player path toward and attack
   them; a real to-hit/damage/crit resolver; player leveling with HP/ATK/DEF
   growth.
4. **Inventory & equipment** — `src/items.js`: procedurally rolled weapons/
   armor/rings/potions/scrolls with rarity tiers and affixes; a capacity-
   limited inventory; equip/unequip/use/drop all wired into the turn loop.

Stretch features (multi-floor descent + save/load, loot rarity + minimap)
and the adversarial review pass come next.
