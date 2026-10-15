// End-to-end check of the browser player in headless Chromium (Playwright).
// usage: node verify/web_e2e.js http://127.0.0.1:8080/ [screenshot-dir]
const path = require('path');
let chromium;
for (const m of ['playwright', '/opt/node22/lib/node_modules/playwright', path.join(process.env.NODE_PATH || '', 'playwright')]) {
  try { ({ chromium } = require(m)); break; } catch (e) { /* try next */ }
}
if (!chromium) { console.error('playwright not found (set NODE_PATH)'); process.exit(2); }
const url = process.argv[2] || 'http://127.0.0.1:8080/';
const shots = process.argv[3];
let failed = 0;
const ok = (c, msg) => { console.log((c ? 'ok   ' : 'FAIL ') + msg); if (!c) failed++; };

(async () => {
  const exe = process.env.PLAYWRIGHT_CHROMIUM || '/opt/pw-browsers/chromium';
  const b = await chromium.launch({ executablePath: require('fs').existsSync(exe) ? exe : undefined, args: ['--no-sandbox'] });
  const p = await b.newPage({ viewport: { width: 1500, height: 900 } });
  const errors = [];
  p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  p.on('pageerror', e => errors.push('pageerror: ' + e.message));
  await p.goto(url);
  await p.waitForFunction(() => window.__dm && window.__dm.ready, null, { timeout: 20000 });
  ok(true, 'wasm core loaded and the default example assembled');

  const lcd = () => p.evaluate(() => {
    const d = document.getElementById('lcd').getContext('2d').getImageData(0, 0, 160, 144).data;
    let dark = 0; for (let i = 0; i < d.length; i += 4) if (d[i] < 100) dark++;
    return dark;
  });
  await p.waitForTimeout(500);
  const title = await lcd();
  ok(title > 300 && title < 6000, `title screen drawn (${title} dark pixels)`);

  await p.keyboard.press('Enter');
  await p.waitForTimeout(700);
  const play = await lcd();
  ok(play > title + 500, `START begins the game: board has walls (${play} dark pixels)`);
  ok(await p.evaluate(() => window.__dm.fps) > 20, 'running at a sane frame rate');

  // keyboard steering moves the snake
  const before = await p.evaluate(() => JSON.parse(window.__dm.api.state()).frames);
  await p.keyboard.down('ArrowDown'); await p.waitForTimeout(400); await p.keyboard.up('ArrowDown');
  const after = await p.evaluate(() => JSON.parse(window.__dm.api.state()).frames);
  ok(after > before, 'frames advance while playing');
  if (shots) await p.screenshot({ path: path.join(shots, 'web-playing.png') });

  // inspector tabs
  for (const tab of ['dis', 'mem', 'tiles', 'serial', 'cpu']) {
    await p.click(`#tabs button[data-tab=${tab}]`);
    await p.waitForTimeout(150);
  }
  await p.click('#tabs button[data-tab=cpu]');
  const regs = await p.textContent('#regs');
  ok(/PC\s*[0-9A-F]{4}/.test(regs) && /SP\s*[0-9A-F]{4}/.test(regs), 'CPU pane shows registers');

  // breakpoints from the disassembly pane
  await p.click('#runPause');
  await p.click('#tabs button[data-tab=dis]');
  await p.waitForTimeout(200);
  const pcText = await p.textContent('#dis tr.pc td.a');
  ok(/[0-9A-F]{4}/.test(pcText), 'disassembly pane marks the PC row');
  // a breakpoint on a routine that runs once per frame in every game state (read_pad) must stop the game, and resuming must get past it
  const wf = await p.evaluate(() => window.__dm.api.resolve('read_pad'));
  ok(wf > 0, `symbol table is available in the browser (read_pad = ${wf.toString(16)})`);
  await p.evaluate(a => window.__dm.toggleBreak(a), wf);
  const marker = await p.$$eval('#dis td.a.bp, #dis td.a', e => e.length);
  ok(marker > 0, 'disassembly pane renders');
  await p.click('#runPause');
  await p.waitForTimeout(800);
  let msg = await p.textContent('#screenMsg');
  ok(/breakpoint/.test(msg), `execution paused on the breakpoint ("${msg.trim()}")`);
  let st = await p.evaluate(() => JSON.parse(window.__dm.api.state()));
  ok(st.pc === wf, `PC == breakpoint address (${st.pc.toString(16)})`);
  const fa = st.cycles;
  await p.click('#runPause'); // resume: runs until the next frame's visit to the same address
  await p.waitForTimeout(400);
  st = await p.evaluate(() => JSON.parse(window.__dm.api.state()));
  ok(st.pc === wf && st.cycles > fa + 10000, `resuming gets past the breakpoint and stops at the next hit (cycle ${fa} -> ${st.cycles})`);
  await p.evaluate(a => window.__dm.toggleBreak(a), wf); // remove
  await p.click('#runPause');
  await p.waitForTimeout(300);
  ok((await p.textContent('#screenMsg')).trim() === '', 'breakpoint removed: game runs freely again');

  // the assembler: errors are listed with line numbers
  await p.fill('#src', '\t.org 0x150\n\tld a, (hl)\n\tld b, 300\n\tjr nowhere\n');
  await p.click('#assemble');
  await p.waitForTimeout(200);
  const errTxt = await p.textContent('#out');
  ok(/editor\.s:2:.*square brackets/.test(errTxt) && /editor\.s:3:.*8 bits/.test(errTxt) && /editor\.s:4:.*nowhere/.test(errTxt), 'three distinct assembler errors with line numbers');
  const marked = await p.$$eval('#gutter .err', e => e.map(x => x.textContent));
  ok(JSON.stringify(marked) === '["2","3","4"]', 'error lines are highlighted in the gutter');

  // assemble a custom program that sends text over the serial port and draws a tile
  const prog = `
	.title "E2E"
	.org 0x100
	nop
	jp main
	.org 0x150
main:
	ld hl, msg
.next:
	ld a, [hl+]
	or a
	jr z, .done
	ldh [0x01], a
	ld a, 0x81
	ldh [0x02], a
.w:	ldh a, [0x02]
	bit 7, a
	jr nz, .w
	jr .next
.done:
	; draw tile 1 (solid) at map (0,0)
	ld a, 0x00
	ldh [0x40], a
	ld hl, 0x8010
	ld b, 16
.t:	ld a, 0xFF
	ld [hl+], a
	dec b
	jr nz, .t
	ld a, 1
	ld [0x9800], a
	ld a, 0x91
	ldh [0x40], a
	di
.h:	halt
	jr .h
msg:	.db "HELLO FROM BROWSER", 0
`;
  await p.fill('#src', prog);
  await p.click('#assemble');
  await p.waitForTimeout(1500);
  ok(/assembled \d+ bytes/.test(await p.textContent('#out')), 'custom program assembles');
  await p.click('#tabs button[data-tab=serial]');
  await p.waitForTimeout(400);
  ok((await p.textContent('#serial')).includes('HELLO FROM BROWSER'), 'serial pane shows program output');
  const px = await p.evaluate(() => Array.from(document.getElementById('lcd').getContext('2d').getImageData(2, 2, 1, 1).data).slice(0, 3));
  ok(px[0] < 60, 'program drew a solid tile in the top-left corner');

  // run the self-checking CPU test from the example menu
  await p.selectOption('#example', 'cputest.asm');
  await p.waitForTimeout(6000);
  await p.click('#tabs button[data-tab=serial]');
  await p.waitForTimeout(300);
  ok(/PASS \d+ checks/.test(await p.textContent('#serial')), 'cputest.asm reports PASS in the browser');

  // quick save / load round trip
  await p.selectOption('#example', 'snake.asm');
  await p.waitForTimeout(800);
  await p.keyboard.press('Enter'); await p.waitForTimeout(500);
  await p.click('#runPause');
  await p.click('#qsave');
  const f1 = await p.evaluate(() => JSON.parse(window.__dm.api.state()).frames);
  await p.click('#runPause'); await p.waitForTimeout(500); await p.click('#runPause');
  await p.click('#qload');
  const f2 = await p.evaluate(() => JSON.parse(window.__dm.api.state()).frames);
  ok(f1 === f2, `quick load restores the saved frame counter (${f1} == ${f2})`);

  // opening a bogus ROM file is rejected gracefully
  await p.setInputFiles('#romFile', { name: 'junk.gb', mimeType: 'application/octet-stream', buffer: Buffer.from('not a rom') });
  await p.waitForTimeout(300);
  ok(/could not load ROM/.test(await p.textContent('#screenMsg')), 'invalid ROM file shows an error on screen');

  // mobile layout has no horizontal overflow
  await p.setViewportSize({ width: 390, height: 844 });
  await p.waitForTimeout(300);
  const overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  ok(overflow <= 1, `no horizontal scroll at phone width (overflow ${overflow}px)`);
  if (shots) await p.screenshot({ path: path.join(shots, 'web-mobile.png'), fullPage: false });

  const realErrors = errors.filter(e => !/favicon/.test(e));
  ok(realErrors.length === 0, 'no console errors' + (realErrors.length ? ': ' + realErrors.join(' | ') : ''));
  await b.close();
  console.log(failed ? `\n${failed} check(s) FAILED` : '\nall web checks passed');
  process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
