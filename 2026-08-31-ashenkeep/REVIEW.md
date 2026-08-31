# Ashenkeep — Adversarial Review (Phase 3)

Methodology: read every module adversarially for logic errors, then ran
three independent stress harnesses beyond the 81-test unit suite:

1. **Dungeon fuzz** — 1,400 generations (7 floor sizes × 200 seeds each,
   including the exact min (20×15) and max (74×38) sizes the game actually
   uses) checking every room and the stairs tile are BFS-reachable from
   start. **0 failures.**
2. **Naive-bot playthrough** — a greedy bot (attack any adjacent monster,
   drink a potion under 40% HP, beeline A* to the stairs, descend
   immediately) ran 60 full seeded games to completion or an 8,000-turn
   cap. **0 crashes**, confirming the full floor-1→10 loop, monster
   scaling, item drops, and win/lose transitions all hold up under
   sustained random play, not just hand-picked unit-test scenarios.
3. **Equip-aware bot** — the same bot but also auto-equipping any strictly
   better weapon/armor/ring it finds. Result: **14/60 (23%) clean wins**,
   0 crashes. This number matters: it proves the floor-10 win condition is
   actually reachable through ordinary (if unsophisticated) play, not just
   by cheating the internal state in a unit test — while still being a
   genuinely hard permadeath roguelike, which is the intended genre feel,
   not a balance bug.

## Findings

### 1. CRITICAL-ish: Scroll of Teleportation could drop the player onto a live monster (or onto its own current tile)

`useItem()`'s `teleport` branch picked a destination via
`this._randomFloorTile(this.dungeon.rooms, new Set())` — an **empty**
occupancy set. Every other tile-picking call site (floor generation) is
careful to exclude monster/player positions, but this one wasn't, so a
teleport scroll could:

- land the player directly on top of a live monster, silently violating
  the game's own "one occupant per tile" invariant (both `@` and the
  monster glyph would then render stacked, and the very next `movePlayer`
  call reading that tile would behave inconsistently), or
- (much rarer, but possible) teleport the player to the exact tile they
  were already standing on, wasting a consumable scroll for a message that
  claims something happened when nothing did.

**Fix:** build the same kind of occupancy set floor-generation already
uses (every live monster's tile, plus the player's own current tile)
before calling `_randomFloorTile` for a teleport destination.

### 2. Dead field: `Monster.path`

`entities.js` declared `this.path = []; // cached A* path, recomputed when
stale` on every monster, and `game.js`'s serialize/deserialize path
explicitly stripped and reset it — but nothing in the entire codebase ever
*reads* `monster.path`. `_processMonsterTurns` calls `findPath()` fresh
every turn and uses its return value directly; no caching ever happens.
This is exactly the kind of "looks like a feature, does nothing" landmine
this repo's own history has flagged before (Galley's `looseness` param).
**Fix:** removed the field and its now-pointless handling in
serialize/`fromSaved`, rather than pretend to cache a path that was never
actually cached.

### 3. Fragile magic number in the renderer

`render.js`'s `tileBackground()` and `renderMinimap()` both wrote
`grid[y][x] === 0` to test for a wall instead of `grid[y][x] === TILE.WALL`
— relying on `TILE.WALL` happening to equal `0` rather than saying so. Any
future reordering of the `TILE` enum in `dungeon.js` would silently break
rendering with no error anywhere. **Fix:** both call sites now reference
`TILE.WALL` directly (the constant is pulled from `window.Ashenkeep` once
at module load instead of being re-destructured per call).

### 4. Minor UX: a focused action-bar button could double-fire on Space

Clicking **Equip**/**Use**/**Drop** in the inventory action bar leaves that
`<button>` focused. Per the HTML spec, `Space` activates a focused button
on `keyup`; our global `keydown` handler also binds `Space` to "wait a
turn". In the worst case (fast Equip-click then Space to wait) this could
fire the button's click a second time (harmless — the item is already
gone, so a stale id is a no-op) *and* still consume a wait-turn, which is
at least a confusing double-signal even though it never corrupts state.
**Fix:** every action-bar button now blurs itself immediately after its
click handler runs, so keyboard focus returns to nothing and Space
unambiguously means "wait" only.

## Non-issues investigated and ruled out

- **Stacking / capacity math** (`addToInventory`/`removeFromInventory`/
  `equipItem`/`unequipSlot`): traced every mutation by hand across
  multi-count stacks and equip-swaps; all paths are already correct and
  covered by `tests/test_items.js`.
- **No passive HP regeneration.** Confirmed intentional, not a bug — it's
  what makes potion management (and the loot system genuinely) matter,
  and the equip-aware bot's 23% win rate proves the game is still winnable
  without it. Documented explicitly in the README rather than silently
  relied upon.
- **Monster wandering onto the stairs tile.** Possible (wander movement
  doesn't avoid it), but this is realistic "a monster is guarding the
  stairs" behavior, not a bug — the player just has to fight through it.

## Fixed and verified

All four findings above are fixed. Full suite re-run after fixes:
`node --test tests/*.js` → 82/82 green; `node tests/ui_smoke.mjs` → light
+ dark mode both pass with zero console/page errors; the dungeon fuzz and
both bot-playthrough harnesses were re-run post-fix with the same 0
crashes / 14-win result (the teleport-scroll fix is behavior-invisible to
a bot that never picked up an unlucky teleport-onto-monster roll in the
first place, which is exactly why a hand-written regression test — not
just the stress harness — was added for it, see
`tests/test_game.js`: "teleporting never lands the player on an occupied
tile").

## Phase 4 additions (found while adding the boss + polish)

Adding the floor-10 boss and hardening save/load surfaced three more
things worth fixing before shipping, applying the same adversarial
standard to the new code as the review above applied to the original:

- **Boss balance was first shipped too hard.** The equip-aware bot's win
  rate (see above) collapsed from 14/60 to 2/60 the moment the first-draft
  boss stats (220 HP / 26 ATK / 12 DEF) were added — the bot could usually
  reach the stairs but essentially never survive the fight. Re-tuned to
  150 HP / 19 ATK / 8 DEF and re-ran the same 60-seed harness: 7/60 wins,
  0 crashes — still a genuinely hard capstone fight (down from the
  unopposed-stairs 14/60 baseline, as a boss fight should be) but
  demonstrably not a wall. This is exactly the kind of thing a hostile
  stress harness catches that hand-written unit tests (which only assert
  "the boss can be killed if you force its HP to 1") never would.
- **`Game.fromSaved` trusted its input completely.** It read `data.player`,
  `data.dungeon.grid`, etc. with no validation — a corrupted or
  future-format save would throw a confusing error deep inside
  reconstruction (or silently produce a broken game object) instead of
  failing cleanly. Added an explicit version check and a shape check that
  throw a clear, top-level error; `main.js` now catches that error,
  discards the unusable save, and tells the player plainly instead of
  Continue silently doing nothing.
- **"Begin Descent" silently discarded an existing saved run with zero
  confirmation** — a real, destructive foot-gun for anyone who meant to
  click Continue. Added a `confirm()` guard that only fires when a save
  actually exists, verified in the headless UI test both ways (dismiss
  keeps the save; accept discards it and starts clean).

Final state: 87/87 `node:test` green, UI smoke test green in light + dark
(including the new confirmation-dialog flow), boss-inclusive stress
harness re-verified with 0 crashes across 60 seeds.

## Phase 5 addition: a CRITICAL bug this whole review had missed

Writing `tests/demo_playthrough.js` (Phase 5's narrated, assertion-backed
walkthrough) placed a monster at a specific in-room offset from the player
and asserted A* could path to it — and that assertion failed. Chasing it
down: **`dungeon.js` defined `carveRect()` (fill a room's rectangle with
floor) but never called it anywhere.** Every "room" in every dungeon ever
generated by this project — Phases 1 through 4, all 87 passing tests, all
three stress harnesses, every screenshot — was never actually carved as an
open rectangle. Only the 1-tile-wide L-shaped corridors connecting room
*centers* were ever floor. What looked in screenshots like a deliberately
narrow, corridor-heavy dungeon aesthetic was this bug, visually
misdiagnosed as a style choice during Phase 4's polish pass instead of
caught as the defect it was.

Why every previous check missed it:
- The connectivity tests (`tests/test_dungeon.js`) only assert that room
  *centers* are BFS-reachable — true regardless, since corridors connect
  centers directly.
- No test asserted a room's interior tiles (other than its center) were
  actually floor.
- The stress-bot harnesses never noticed because `_randomFloorTile` picking
  a monster/item spot inside a room silently fails closed: most of its 200
  random-coordinate attempts landed on the (still-wall) rest of the
  rectangle, so on a typical floor only a fraction of the intended monster/
  item count ever actually spawned — silently, with no error, no missing
  count logged anywhere. This suppressed monster density is *why* the
  Phase 3/4 stress numbers (14/60, then 7/60 after the boss) looked like a
  believable, winnable difficulty curve: the world was quietly easier than
  designed.

**Fix:** `carveRoomInLeaf()` now calls `carveRect()` immediately after
constructing each room's rectangle, so every leaf's floor is genuinely
carved before corridors connect the centers.

**Consequence:** with rooms actually open, real monster density matches
the design (`monsterCountForFloor`) for the first time, which made the
already-tuned difficulty sharply harder — re-running the 100-seed
equip-aware bot harness against the fixed generator dropped the win rate
to 1/100, with runs piling up dead on floor 3 as soon as tier-2 monsters
appear in a real, fully-populated floor. This required a genuine
re-balance, not just a bugfix: player `baseMaxHp` 24→32, `baseAtk` 4→5,
`baseDef` 1→2, per-level HP gain `6+level*2`→`8+level*3`, monster per-floor
stat-scaling `0.12`→`0.08`, `monsterCountForFloor` `min(18,3+floor)`→
`min(12,2+floor)`, `itemCountForFloor` raised for more sustain, and
`MONSTER_SIGHT_RADIUS` 6→5 (open rooms let more monsters spot the player
simultaneously than the original sight radius was tuned for). Re-verified
against the same 100/300-seed harnesses post-rebalance: **23/300 (≈8%)
wins**, deaths spread across floors 3–10 rather than walled at floor 3 —
a genuinely hard, genuinely winnable curve, this time measured against the
dungeon the game actually ships.

One test itself also turned out to be silently relying on the suppressed-
monster-density world: `"defeating the boss lets the player finally stand
on the stairs and win"` assumed a single attack (accuracy 1, atk 999 vs.
1 HP) would always kill the boss in one hit — but hit chance is
intentionally capped at 99% (`MAX_HIT_CHANCE` in combat.js), so a ~1% miss
was always possible; the dungeon fix shifted the RNG stream enough that
this run happened to roll it. Fixed by attacking in a bounded loop until
the boss actually dies, the same defensive pattern already used elsewhere
in this suite, rather than assuming a single guaranteed-ish hit.

Final re-verification after the rebalance: 87/87 `node:test` green (100%
reproducible, no flakes across 5 consecutive runs), `demo_playthrough.js`
finds a real win by seed 7 in ~1 second, UI smoke test green in light +
dark, and a fresh screenshot confirms rooms now render as genuinely open
spaces rather than corridor-shaped slivers.
