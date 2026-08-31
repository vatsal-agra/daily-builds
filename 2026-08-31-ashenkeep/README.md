# Ashenkeep

A browser-playable roguelike dungeon crawler built entirely from scratch in
vanilla JavaScript — procedural BSP dungeons, real recursive-shadowcasting
field-of-view, A*-driven enemy AI, turn-based combat, a full
loot/inventory/equipment system, and a named final boss guarding the way
out. No frameworks, no build step, no libraries: every algorithm in this
project — dungeon generation, field-of-view, pathfinding, combat
resolution, loot rolls — is hand-written.

See [`PLAN.md`](./PLAN.md) for the original design and
[`REVIEW.md`](./REVIEW.md) for the full adversarial-review history,
including a critical dungeon-generation bug found only during Phase 5
verification (rooms were never actually carved as open rectangles) and the
honest difficulty rebalance that followed fixing it.

## Run it

```bash
cd 2026-08-31-ashenkeep
python3 -m http.server 8000
# open http://localhost:8000/index.html
```

No build step, no `npm install` needed to play — it's plain `<script>`
tags loading small, independent modules in dependency order.

**Controls:** move with arrow keys or WASD (walking into a monster attacks
it, walking over an item picks it up); `.` or Space to wait a turn; `>` to
descend when standing on the stairs. Click an inventory item to
equip/use/drop it.

## Verify it

```bash
./demo.sh                          # everything below, in order, one command, exit 0
node --test tests/test_*.js        # 87 unit/integration tests
node tests/demo_playthrough.js     # narrated walkthrough of every feature + a real autonomous win
node tests/ui_smoke.mjs            # headless-Chromium smoke test of the real page, light + dark
```

`tests/demo_playthrough.js` is the most useful single thing to run to see
this project work: it checks every required and stretch feature
individually against fixed seeds, then plays a real (if unsophisticated)
bot from floor 1 all the way to an actual win — defeating the named final
boss and descending floor 10's stairs — and asserts it happened, printing
the run's final stats.

## Full feature list

**Required:**
1. **Procedural dungeon generation** (`src/dungeon.js`) — binary-space
   partitioning carves rooms into leaves and connects every split
   bottom-up with an L-shaped corridor, so the floor is provably one
   connected component by construction; stairs are placed in the room
   with the greatest real walking distance from the start.
2. **Field-of-view / fog of war** (`src/fov.js`) — recursive shadowcasting
   over all 8 octants; walls correctly block sight around corners;
   explored-but-not-currently-visible tiles stay dimly remembered.
3. **Turn-based combat with A\* enemy AI** (`src/astar.js` + `src/combat.js`
   + `src/game.js`) — a monster that spots the player (via its own
   shadowcast sight check, not omniscience) becomes aggroed and A*-paths
   toward and attacks; combat is a real to-hit/damage/crit resolver, not a
   coin flip; the player levels up (HP/ATK/DEF growth) on kills.
4. **Inventory & equipment** (`src/items.js`) — a capacity-limited
   inventory filled by walking over drops; weapon/armor/ring slots that
   genuinely change combat math; potions/scrolls with real, distinct,
   consumed-on-use effects (heal, teleport, reveal-the-floor).

**Stretch:**
5. **Multi-floor descent with save/load and permadeath** — 10 floors of
   scaling difficulty; the full run state serializes to `localStorage`
   (with a version/shape guard against corrupt saves) so a reload resumes
   exactly where you left off; death is final and clears the save.
6. **Procedural loot rarity/affixes and a minimap** — items roll onto a
   common → magic → rare → epic ladder with tier-scaled random affixes
   (e.g. "Rare Long Sword of Precision"); an always-visible minimap uses
   the same fog-of-war data as the main view (no unexplored tiles drawn —
   no cheating).
7. *(bonus, added during polish)* **A named final boss** — "The Keeper of
   Ashenkeep" stands directly on floor 10's stairs tile. Because walking
   into an occupied tile attacks it rather than stepping onto it, the
   player is structurally incapable of reaching the winning tile without
   defeating the boss first — no separate "is it still alive" check
   needed anywhere in the code.

**Polish:** a bespoke dark-fantasy UI (not default browser styling); a
textured-stone, beveled-wall, torchlit-vignette Canvas renderer; glowing
entity/item glyphs; save-corruption and save-version guards with clean
user-facing errors instead of silent failures; a confirmation prompt
before a new run discards an existing save.

## Why this project today

This repo's history (`LEDGER.md`) is dense with from-scratch **systems and
algorithms** — SAT solvers, compilers, a CPU pipeline simulator, a dozen
GPT-style transformers, search engines — but had almost never shipped a
complete, playable **game** with real stakes and a win/lose condition.
Gambit (chess, 2026-06-18) is the closest precedent, and that's a solved,
deterministic board game with no procedural content or randomness. A
roguelike forces several classic algorithms (BSP generation,
shadowcasting, A*, a loot-affix system) to compose into one coherent,
*fun*, permadeath experience where a single miscalculation ruins the run
rather than just failing a unit test — and, as Phase 5 proved, a bug that
every unit test missed can still hide in plain sight until something
actually tries to *play* the game.

## Where a human could take this next

- **Ranged/spell abilities** — every fight is currently melee-adjacent; a
  thrown potion or a scroll-cast projectile would add real tactical depth.
- **More boss variety** — one named boss on floor 10; a mid-run boss
  (floor 5?) with a different attack pattern would raise the stakes earlier.
- **Diagonal movement** — the FOV module already casts all 8 octants and
  A* could add a `DIRS8` easily; it was left 4-directional deliberately so
  a 1-tile-wide corridor can't be corner-cut diagonally.
- **A real leaderboard** — score (floor reached, level, turns survived) is
  already computed but only ever shown to the one player; a shared
  high-score list would need a backend this project deliberately has none of.
- **Sound** — Waveforge (2026-07-21, this repo) already ships a
  from-scratch synth engine; wiring its oscillators to combat/level-up/
  descend events would be a natural crossover between two builds.
