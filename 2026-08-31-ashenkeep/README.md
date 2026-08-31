# Ashenkeep

> Status: **Phase 3 — Adversarial review complete.** All 4 required
> features work end-to-end and have survived a hostile self-review; see
> [`PLAN.md`](./PLAN.md) for the design and [`REVIEW.md`](./REVIEW.md) for
> the findings (a teleport-scroll occupancy bug, dead code, a fragile magic
> number, and a minor focus/keyboard UX bug — all fixed with regression
> coverage). Stretch features and final polish are still to come.

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
node --test tests/*.js     # 82 unit/integration tests (dungeon, fov, astar, entities, items, combat, game)
node tests/ui_smoke.mjs    # headless-Chromium smoke test of the real page
```

`REVIEW.md` also documents three independent stress harnesses run beyond
the unit suite: a 1,400-generation dungeon-connectivity fuzz, a 60-seed
naive-bot full playthrough (0 crashes), and a 60-seed equip-aware bot
playthrough that actually **wins 14/60 (23%) of the time** floor-1-to-10 —
proof the win condition is genuinely reachable, not just asserted in a
unit test.

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
