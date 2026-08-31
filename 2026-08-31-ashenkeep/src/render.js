// render.js — Canvas 2D renderer. Pure function of Game state -> pixels;
// no game logic lives here (no combat math, no pathfinding, no RNG calls).
// Browser-only (uses `document`/`CanvasRenderingContext2D`), so it is
// exercised by a headless-Chromium smoke test rather than node:test.

'use strict';

(function () {
  const TILE_SIZE = 20;
  const COLORS = {
    bgVisibleFloor: ['#2a2a35', '#2c2c38', '#282833'],
    bgExploredFloor: '#17171c',
    bgVisibleWall: ['#3c3c4a', '#3f3f4d', '#393947'],
    bgExploredWall: '#1c1c22',
    wallHighlight: 'rgba(255,255,255,0.06)',
    wallShadow: 'rgba(0,0,0,0.25)',
    stairs: '#f2d060',
    player: '#7fe0ff',
  };

  // Deterministic per-tile hash (not RNG — the same tile must always shade
  // the same way across re-renders) used to break up otherwise-flat floor
  // and wall fills into a subtle, natural-looking stone texture.
  function tileHash(x, y) {
    let h = (x * 374761393 + y * 668265263) ^ 0x9e3779b9;
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    return ((h ^ (h >>> 16)) >>> 0) % 3;
  }

  function tileInfo(game, x, y) {
    const { TILE } = window.Ashenkeep;
    const key = `${x},${y}`;
    const visible = game.visible.has(key);
    const explored = game.explored[y] && game.explored[y][x];
    if (!visible && !explored) return null; // unexplored: draw nothing (pure black)
    const wall = game.dungeon.grid[y][x] === TILE.WALL;
    let color;
    if (wall) color = visible ? COLORS.bgVisibleWall[tileHash(x, y)] : COLORS.bgExploredWall;
    else color = visible ? COLORS.bgVisibleFloor[tileHash(x, y)] : COLORS.bgExploredFloor;
    return { visible, wall, color };
  }

  function drawGlyph(ctx, glyph, color, px, py, alpha, glow) {
    ctx.globalAlpha = alpha;
    ctx.fillStyle = color;
    ctx.font = `bold ${TILE_SIZE - 4}px "Courier New", monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    if (glow) {
      ctx.shadowColor = color;
      ctx.shadowBlur = 8;
    }
    ctx.fillText(glyph, px + TILE_SIZE / 2, py + TILE_SIZE / 2 + 1);
    ctx.shadowBlur = 0;
    ctx.globalAlpha = 1;
  }

  function drawVignette(ctx, centerPx, centerPy, radiusPx) {
    const grad = ctx.createRadialGradient(centerPx, centerPy, radiusPx * 0.3, centerPx, centerPy, radiusPx);
    grad.addColorStop(0, 'rgba(0,0,0,0)');
    grad.addColorStop(1, 'rgba(0,0,0,0.6)');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  }

  function render(ctx, game, viewport) {
    const { TILE } = window.Ashenkeep;
    const width = ctx.canvas.width;
    const height = ctx.canvas.height;
    ctx.fillStyle = '#000000';
    ctx.fillRect(0, 0, width, height);

    const colsVisible = Math.floor(width / TILE_SIZE);
    const rowsVisible = Math.floor(height / TILE_SIZE);
    let camX = game.player.x - Math.floor(colsVisible / 2);
    let camY = game.player.y - Math.floor(rowsVisible / 2);
    camX = Math.max(0, Math.min(game.dungeon.width - colsVisible, camX));
    camY = Math.max(0, Math.min(game.dungeon.height - rowsVisible, camY));
    if (game.dungeon.width <= colsVisible) camX = 0;
    if (game.dungeon.height <= rowsVisible) camY = 0;

    for (let ty = 0; ty < rowsVisible; ty++) {
      for (let tx = 0; tx < colsVisible; tx++) {
        const gx = camX + tx;
        const gy = camY + ty;
        if (gx < 0 || gy < 0 || gx >= game.dungeon.width || gy >= game.dungeon.height) continue;
        const info = tileInfo(game, gx, gy);
        if (!info) continue;
        const px = tx * TILE_SIZE;
        const py = ty * TILE_SIZE;
        ctx.fillStyle = info.color;
        ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE);

        if (info.wall) {
          // Cheap bevel so wall blocks read as blocks, not a flat wash.
          ctx.fillStyle = COLORS.wallHighlight;
          ctx.fillRect(px, py, TILE_SIZE, 2);
          ctx.fillRect(px, py, 2, TILE_SIZE);
          ctx.fillStyle = COLORS.wallShadow;
          ctx.fillRect(px, py + TILE_SIZE - 2, TILE_SIZE, 2);
          ctx.fillRect(px + TILE_SIZE - 2, py, 2, TILE_SIZE);
        }

        const tile = game.dungeon.grid[gy][gx];
        if (tile === TILE.STAIRS_DOWN) {
          drawGlyph(ctx, '>', COLORS.stairs, px, py, info.visible ? 1 : 0.45, info.visible);
        }
      }
    }

    // Ground items (only when currently visible — no x-ray loot).
    for (const [key, stack] of game.groundItems.entries()) {
      if (!game.visible.has(key) || stack.length === 0) continue;
      const [gx, gy] = key.split(',').map(Number);
      const tx = gx - camX;
      const ty = gy - camY;
      if (tx < 0 || ty < 0 || tx >= colsVisible || ty >= rowsVisible) continue;
      const top = stack[stack.length - 1];
      drawGlyph(ctx, top.glyph, top.color, tx * TILE_SIZE, ty * TILE_SIZE, 1, true);
    }

    // Monsters (only when currently visible).
    for (const m of game.monsters) {
      if (!m.isAlive()) continue;
      const key = `${m.x},${m.y}`;
      if (!game.visible.has(key)) continue;
      const tx = m.x - camX;
      const ty = m.y - camY;
      if (tx < 0 || ty < 0 || tx >= colsVisible || ty >= rowsVisible) continue;
      drawGlyph(ctx, m.glyph, m.color, tx * TILE_SIZE, ty * TILE_SIZE, 1, true);
      // HP sliver above the monster.
      const barW = TILE_SIZE - 6;
      const frac = Math.max(0, m.hp / m.maxHp);
      ctx.fillStyle = '#111';
      ctx.fillRect(tx * TILE_SIZE + 3, ty * TILE_SIZE + 1, barW, 3);
      ctx.fillStyle = frac > 0.5 ? '#5fd15f' : frac > 0.25 ? '#e0c04f' : '#e05c5c';
      ctx.fillRect(tx * TILE_SIZE + 3, ty * TILE_SIZE + 1, barW * frac, 3);
      if (m.isBoss) {
        ctx.strokeStyle = m.color;
        ctx.lineWidth = 1;
        ctx.globalAlpha = 0.7;
        ctx.strokeRect(tx * TILE_SIZE + 1, ty * TILE_SIZE + 1, TILE_SIZE - 2, TILE_SIZE - 2);
        ctx.globalAlpha = 1;
      }
    }

    // Player.
    let playerScreen = { x: 0, y: 0 };
    {
      const tx = game.player.x - camX;
      const ty = game.player.y - camY;
      drawGlyph(ctx, '@', COLORS.player, tx * TILE_SIZE, ty * TILE_SIZE, 1, true);
      playerScreen = { x: tx * TILE_SIZE + TILE_SIZE / 2, y: ty * TILE_SIZE + TILE_SIZE / 2 };
    }

    // Soft torchlight vignette centered on the player, purely atmospheric —
    // it never hides or reveals anything the fog-of-war set already decided.
    drawVignette(ctx, playerScreen.x, playerScreen.y, window.Ashenkeep.VISION_RADIUS * TILE_SIZE * 0.85);

    return { camX, camY, colsVisible, rowsVisible, tileSize: TILE_SIZE };
  }

  function renderMinimap(ctx, game) {
    const { TILE } = window.Ashenkeep;
    const width = ctx.canvas.width;
    const height = ctx.canvas.height;
    ctx.fillStyle = '#0a0a0d';
    ctx.fillRect(0, 0, width, height);
    const scaleX = width / game.dungeon.width;
    const scaleY = height / game.dungeon.height;
    const scale = Math.min(scaleX, scaleY);
    const offX = (width - game.dungeon.width * scale) / 2;
    const offY = (height - game.dungeon.height * scale) / 2;

    for (let y = 0; y < game.dungeon.height; y++) {
      for (let x = 0; x < game.dungeon.width; x++) {
        if (!game.explored[y][x]) continue;
        const wall = game.dungeon.grid[y][x] === TILE.WALL;
        ctx.fillStyle = wall ? '#2a2a33' : '#4a4a5a';
        ctx.fillRect(offX + x * scale, offY + y * scale, Math.max(1, scale), Math.max(1, scale));
      }
    }
    if (game.explored[game.dungeon.stairs.y][game.dungeon.stairs.x]) {
      ctx.fillStyle = '#f2d060';
      ctx.fillRect(offX + game.dungeon.stairs.x * scale - 1, offY + game.dungeon.stairs.y * scale - 1, scale + 2, scale + 2);
    }
    ctx.fillStyle = '#7fe0ff';
    ctx.fillRect(offX + game.player.x * scale - 1, offY + game.player.y * scale - 1, scale + 2, scale + 2);
  }

  window.Ashenkeep = window.Ashenkeep || {};
  window.Ashenkeep.render = render;
  window.Ashenkeep.renderMinimap = renderMinimap;
  window.Ashenkeep.TILE_SIZE = TILE_SIZE;
})();
