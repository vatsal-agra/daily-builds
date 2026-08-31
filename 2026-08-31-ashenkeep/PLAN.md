# Ashenkeep — PLAN

## Concept

A browser-playable **roguelike dungeon crawler** built entirely from scratch
in vanilla JavaScript: procedurally generated dungeons, real recursive
shadowcasting field-of-view, A*-driven enemy AI, turn-based tactical combat,
and a full inventory/equipment/loot system — the genre that defined
*Rogue*, *NetHack*, and *Brogue*.

## Why this is interesting

This repo's history (see `LEDGER.md`) is dense with from-scratch **systems
and algorithms**: SAT solvers, CDCL variants, compilers, JITs, a CPU
pipeline simulator, a dozen GPT-style transformers, search engines, physics
engines, a type inferencer. What it has almost never shipped is a
**complete, playable game with a win/lose condition and player-facing
stakes** — Gambit (chess) is the closest precedent, and that's a solved,
deterministic board game with no procedural content or randomness.

A roguelike is a genuinely different kind of hard: it forces multiple
classic algorithms (BSP dungeon generation, recursive shadowcasting,
A* pathfinding, a stat/combat resolver, a loot-affix generator) to compose
into one coherent, *fun*, permadeath experience where a single tile
miscalculation ruins the game rather than just failing a unit test. It's
also a good stress test of "no stubs, no mocks" — every monster's AI must
actually chase and hit the player, every potion must actually heal, every
dungeon must actually be fully connected and beatable.

## Architecture

```
2026-08-31-ashenkeep/
  src/
    rng.js        — seeded PRNG (mulberry32) for fully reproducible runs
    dungeon.js     — BSP tree partition -> rooms + L-shaped corridors
    fov.js         — recursive shadowcasting field-of-view / fog of war
    astar.js       — grid A* pathfinder used by monster AI
    entities.js    — Player/Monster stat blocks, leveling curve
    items.js       — item templates, rarity/affix roll, inventory logic
    combat.js      — to-hit/damage resolution, XP awards
    game.js        — Game class: turn loop, floors, save/load, win/lose
    render.js      — Canvas 2D renderer (browser-only; pure function of state)
    main.js        — browser bootstrap: input handling, render loop, UI wiring
  index.html       — the playable page (loads the above via <script> tags)
  tests/           — node:test suites, one per src module + one integration
  demo.sh          — runs the full test suite + a scripted headless playthrough
  PLAN.md / REVIEW.md / README.md
```

Every module under `src/` is written as a small UMD-style file: it defines
its classes/functions, then does
`if (typeof module !== 'undefined') module.exports = {...}` at the bottom
and otherwise attaches to `window`. This means the *exact same, unmodified*
game-logic code runs both under Node (for `node:test` — no DOM, no jsdom,
no mocking needed) and in the browser (via plain `<script>` tags, no build
step, no bundler). Only `render.js`/`main.js` touch the DOM/Canvas and are
therefore exercised via a headless-Chromium smoke test instead of unit
tests.

## Feature list

### Required (must work end-to-end, no stubs)

1. **Procedural dungeon generation.** Binary-space-partition the floor grid
   recursively down to leaf cells, carve one irregular-sized room per leaf,
   connect every sibling pair with an L-shaped corridor while walking back
   up the tree (so the whole floor is provably one connected component by
   construction), and place a stairs-down tile in the room with the
   greatest BFS walking-distance from the player's start room. Seeded and
   exactly reproducible.

2. **Field-of-view / fog of war.** Recursive shadowcasting (8 octants) from
   the player's position each turn, producing a "currently visible" set and
   a persistent "previously explored but currently dark" set the renderer
   draws dimmed. Walls correctly block sight around corners; monsters and
   items outside the visible set are hidden even if previously seen.

3. **Turn-based combat with A* enemy AI.** Player and monsters alternate
   discrete turns. A monster that has the player in its field of view
   becomes aggroed and uses A* over the walkable grid to path toward and
   attack the player; a non-aggroed monster wanders randomly. Combat itself
   is a real stat resolver: to-hit chance from attacker accuracy vs.
   defender evasion, damage from attack/defense with variance and a crit
   chance, and player XP/leveling (HP and stats grow on level-up) — not a
   coin flip standing in for "combat".

4. **Inventory & equipment.** A capacity-limited inventory the player fills
   by walking over dropped items; equip slots for weapon/armor/ring that
   genuinely change combat math (a stronger sword raises damage, armor
   lowers incoming damage); consumable potions/scrolls with real, distinct
   effects (healing, teleport, map reveal) that are consumed on use; a
   working drop/use/equip flow from the keyboard.

### Stretch (at least 1, aim for 2+)

5. **Multi-floor descent with save/load and permadeath.** Stairs descend to
   a newly generated, harder floor (more/stronger monsters, bigger
   dungeons); the run state (seed, floor, player stats, inventory, RNG
   stream position) serializes to `localStorage` so a reload resumes the
   same run; player death is final — the save is cleared and a
   game-over/score screen (floor reached, level, kills) is shown.

6. **Procedural loot rarity & a minimap.** Items roll onto a
   common/magic/rare/epic tier ladder with tier-scaled random affixes
   (e.g. "+2 Accuracy", "of the Bear (+8 Max HP)"), rendered with
   tier-colored names; a small always-visible minimap in the HUD shows the
   explored floor layout and the player's/stairs' position using the same
   fog-of-war data the main view uses (no cheating — no unexplored tiles
   drawn on it).

## Non-goals

- No multiplayer, no server, no network calls — a single self-contained
  static page.
- No external art/audio assets — everything is drawn procedurally on
  `<canvas>` with simple shapes/glyphs, in a dark, legible palette.
