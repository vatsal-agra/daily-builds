// main.js — browser bootstrap: screens (menu/playing/game-over), input
// handling, HUD/inventory DOM wiring, and localStorage save/load. All game
// rules live in game.js; this file only translates DOM events into Game
// method calls and reflects Game state back into the DOM/canvas.

'use strict';

(function () {
  const SAVE_KEY = 'ashenkeep-save-v1';
  const { Game, MAX_FLOOR, render, renderMinimap, describeAffixes } = window.Ashenkeep;

  const el = {
    menu: document.getElementById('menu-screen'),
    playing: document.getElementById('game-screen'),
    gameOver: document.getElementById('gameover-screen'),
    seedInput: document.getElementById('seed-input'),
    newRunBtn: document.getElementById('new-run-btn'),
    continueBtn: document.getElementById('continue-btn'),
    canvas: document.getElementById('game-canvas'),
    minimap: document.getElementById('minimap-canvas'),
    hpBar: document.getElementById('hp-bar-fill'),
    hpText: document.getElementById('hp-text'),
    xpBar: document.getElementById('xp-bar-fill'),
    xpText: document.getElementById('xp-text'),
    levelText: document.getElementById('level-text'),
    floorText: document.getElementById('floor-text'),
    killsText: document.getElementById('kills-text'),
    equipSlots: document.getElementById('equip-slots'),
    inventoryList: document.getElementById('inventory-list'),
    actionBar: document.getElementById('action-bar'),
    messageLog: document.getElementById('message-log'),
    gameOverTitle: document.getElementById('gameover-title'),
    gameOverBody: document.getElementById('gameover-body'),
    playAgainBtn: document.getElementById('play-again-btn'),
    hint: document.getElementById('hint-text'),
    menuMessage: document.getElementById('menu-message'),
  };

  let game = null;
  let selectedItemId = null;
  const ctx = el.canvas.getContext('2d');
  const miniCtx = el.minimap.getContext('2d');

  function showScreen(name) {
    el.menu.hidden = name !== 'menu';
    el.playing.hidden = name !== 'playing';
    el.gameOver.hidden = name !== 'gameover';
  }

  function loadSavedGame() {
    try {
      const raw = localStorage.getItem(SAVE_KEY);
      if (!raw) return null;
      return Game.fromSaved(JSON.parse(raw));
    } catch (e) {
      console.warn('Failed to load save:', e);
      clearSave(); // don't keep offering a "Continue" that will only fail again
      return { error: e.message };
    }
  }

  function persist() {
    if (!game || game.gameOver) return;
    try {
      localStorage.setItem(SAVE_KEY, JSON.stringify(game.serialize()));
    } catch (e) {
      console.warn('Failed to save:', e);
    }
  }

  function clearSave() {
    try {
      localStorage.removeItem(SAVE_KEY);
    } catch (e) {
      /* ignore */
    }
  }

  function refreshMenu() {
    const saved = (() => {
      try {
        return localStorage.getItem(SAVE_KEY);
      } catch (e) {
        return null;
      }
    })();
    el.continueBtn.disabled = !saved;
    el.continueBtn.textContent = saved ? 'Continue Run' : 'No Saved Run';
  }

  function setMenuMessage(text) {
    el.menuMessage.textContent = text || '';
  }

  function hasSavedRun() {
    try {
      return !!localStorage.getItem(SAVE_KEY);
    } catch (e) {
      return false;
    }
  }

  function startNewGame(seedText) {
    if (hasSavedRun()) {
      const proceed = window.confirm('Starting a new descent will permanently discard your saved run. Continue?');
      if (!proceed) return;
    }
    let seed = parseInt(seedText, 10);
    if (!Number.isFinite(seed) || seedText.trim() === '') {
      seed = Math.floor(Math.random() * 0xffffffff);
    }
    clearSave();
    setMenuMessage('');
    game = new Game(seed >>> 0);
    selectedItemId = null;
    showScreen('playing');
    persist();
    renderAll();
  }

  function continueGame() {
    const restored = loadSavedGame();
    if (!restored) {
      setMenuMessage('No saved run to continue.');
      refreshMenu();
      return;
    }
    if (restored.error) {
      setMenuMessage(`Your saved run could not be loaded (${restored.error}) and was discarded.`);
      refreshMenu();
      return;
    }
    setMenuMessage('');
    game = restored;
    selectedItemId = null;
    showScreen('playing');
    renderAll();
  }

  function fmtPct(n) {
    return `${Math.round(n * 100)}%`;
  }

  function renderHUD() {
    const p = game.player;
    el.hpBar.style.width = `${Math.max(0, (p.hp / p.maxHp) * 100)}%`;
    el.hpText.textContent = `${p.hp} / ${p.maxHp} HP`;
    el.xpBar.style.width = `${Math.max(0, (p.xp / p.xpToNext) * 100)}%`;
    el.xpText.textContent = `${p.xp} / ${p.xpToNext} XP`;
    el.levelText.textContent = `Level ${p.level}`;
    el.floorText.textContent = `Floor ${game.floorNumber} / ${MAX_FLOOR}`;
    el.killsText.textContent = `${p.kills} kills`;

    const standingOnStairs = game.dungeon.grid[p.y][p.x] === 2;
    el.hint.textContent = standingOnStairs
      ? 'Standing on the stairs — press > to descend.'
      : 'Move: arrows/WASD · Wait: . · Descend on stairs: > · Click an item to act on it.';
  }

  function renderEquipment() {
    el.equipSlots.innerHTML = '';
    for (const slot of ['weapon', 'armor', 'ring']) {
      const item = game.player.equipment[slot];
      const div = document.createElement('div');
      div.className = 'equip-slot' + (item ? ` rarity-${item.rarity}` : ' empty');
      div.innerHTML = item
        ? `<span class="slot-label">${slot}</span><span class="slot-item">${item.name}</span><span class="slot-affixes">${describeAffixes(item.affixes)}</span>`
        : `<span class="slot-label">${slot}</span><span class="slot-item empty-text">empty</span>`;
      if (item) {
        div.title = 'Click to unequip';
        div.addEventListener('click', () => {
          game.unequip(slot);
          persist();
          renderAll();
        });
      }
      el.equipSlots.appendChild(div);
    }
  }

  function renderInventory() {
    el.inventoryList.innerHTML = '';
    if (game.player.inventory.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'inv-empty';
      empty.textContent = 'Your pack is empty.';
      el.inventoryList.appendChild(empty);
    }
    for (const item of game.player.inventory) {
      const row = document.createElement('div');
      row.className = `inv-item rarity-${item.rarity}` + (item.id === selectedItemId ? ' selected' : '');
      const countText = item.count > 1 ? ` ×${item.count}` : '';
      const detail = item.affixes ? describeAffixes(item.affixes) : item.heal ? `Heals ${item.heal} HP` : item.effect ? item.effect : '';
      row.innerHTML = `<span class="inv-glyph" style="color:${item.color}">${item.glyph}</span><span class="inv-name">${item.name}${countText}</span><span class="inv-detail">${detail}</span>`;
      row.addEventListener('click', () => {
        selectedItemId = selectedItemId === item.id ? null : item.id;
        renderInventory();
        renderActionBar();
      });
      el.inventoryList.appendChild(row);
    }
  }

  function renderActionBar() {
    el.actionBar.innerHTML = '';
    if (!selectedItemId) return;
    const item = game.player.inventory.find((i) => i.id === selectedItemId);
    if (!item) {
      selectedItemId = null;
      return;
    }
    const makeBtn = (label, handler) => {
      const btn = document.createElement('button');
      btn.textContent = label;
      btn.addEventListener('click', () => {
        handler();
        selectedItemId = null;
        persist();
        renderAll();
        // Avoid a focused button silently double-activating on the next
        // Space keypress, which the global keydown handler also binds to
        // "wait a turn".
        btn.blur();
      });
      return btn;
    };
    if (item.slot) el.actionBar.appendChild(makeBtn('Equip', () => game.equip(item.id)));
    if (item.type === 'potion' || item.type === 'scroll') el.actionBar.appendChild(makeBtn('Use', () => game.useItem(item.id)));
    el.actionBar.appendChild(makeBtn('Drop', () => game.dropItem(item.id)));
  }

  function renderMessages() {
    el.messageLog.innerHTML = game.messages
      .slice(-10)
      .map((m) => `<div class="log-line">${m}</div>`)
      .join('');
    el.messageLog.scrollTop = el.messageLog.scrollHeight;
  }

  function checkGameOver() {
    if (!game.gameOver) return;
    clearSave();
    el.gameOverTitle.textContent = game.won ? 'You Escaped Ashenkeep!' : 'You Have Fallen';
    el.gameOverTitle.className = game.won ? 'win' : 'loss';
    el.gameOverBody.innerHTML = `
      <p>Floor reached: <strong>${game.floorNumber}</strong> / ${MAX_FLOOR}</p>
      <p>Character level: <strong>${game.player.level}</strong></p>
      <p>Monsters slain: <strong>${game.player.kills}</strong></p>
      <p>Turns survived: <strong>${game.turnCount}</strong></p>
    `;
    showScreen('gameover');
  }

  function renderAll() {
    render(ctx, game);
    renderMinimap(miniCtx, game);
    renderHUD();
    renderEquipment();
    renderInventory();
    renderActionBar();
    renderMessages();
    checkGameOver();
  }

  const MOVE_KEYS = {
    ArrowUp: [0, -1],
    ArrowDown: [0, 1],
    ArrowLeft: [-1, 0],
    ArrowRight: [1, 0],
    w: [0, -1],
    s: [0, 1],
    a: [-1, 0],
    d: [1, 0],
    W: [0, -1],
    S: [0, 1],
    A: [-1, 0],
    D: [1, 0],
  };

  function handleKey(e) {
    if (el.playing.hidden) return;
    if (!game || game.gameOver) return;

    if (MOVE_KEYS[e.key]) {
      e.preventDefault();
      const [dx, dy] = MOVE_KEYS[e.key];
      const result = game.movePlayer(dx, dy);
      if (result.message) flashHint(result.message);
      persist();
      renderAll();
      return;
    }
    if (e.key === '.' || e.key === ' ') {
      e.preventDefault();
      game.waitTurn();
      persist();
      renderAll();
      return;
    }
    if (e.key === '>') {
      e.preventDefault();
      const result = game.descend();
      if (!result.ok) flashHint(result.message);
      persist();
      renderAll();
      return;
    }
  }

  let hintTimer = null;
  function flashHint(text) {
    el.hint.textContent = text;
    clearTimeout(hintTimer);
    hintTimer = setTimeout(renderHUD, 2000);
  }

  el.newRunBtn.addEventListener('click', () => startNewGame(el.seedInput.value));
  el.continueBtn.addEventListener('click', continueGame);
  el.seedInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') startNewGame(el.seedInput.value);
  });
  el.playAgainBtn.addEventListener('click', () => {
    showScreen('menu');
    setMenuMessage('');
    refreshMenu();
  });
  window.addEventListener('keydown', handleKey);

  refreshMenu();
  showScreen('menu');
})();
