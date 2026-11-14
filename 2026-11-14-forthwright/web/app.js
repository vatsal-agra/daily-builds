(function () {
  'use strict';
  const F = window.Forthwright;
  const $ = id => document.getElementById(id);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };

  const editor = $('editor'), gutter = $('gutter'), out = $('out'), status = $('status');
  let vm = null, tl = null, tlIndex = 0, timer = null, errLine = null, curLine = null;
  const history = []; let hpos = 0;

  // ------------------------------------------------------------ VM -------
  function newVM() {
    vm = new F.Forth({ optimize: $('optimize').checked, maxSteps: 3000000, maxOutput: 200000 }).use({ analyzer: F.Analyzer, optimizer: F.Optimizer });
    vm.onOutput = s => put(s);
  }
  function put(text, cls) {
    if (cls) { out.appendChild(el('span', cls, text)); } else out.appendChild(document.createTextNode(text));
    out.scrollTop = out.scrollHeight;
  }
  function clearOut() { out.textContent = ''; }

  // -------------------------------------------------------- gutter --------
  function renderGutter() {
    const n = editor.value.split('\n').length;
    if (gutter.childElementCount !== n) {
      gutter.textContent = '';
      for (let i = 1; i <= n; i++) gutter.appendChild(el('div', '', String(i)));
    }
    for (let i = 0; i < gutter.children.length; i++) {
      const c = gutter.children[i];
      c.classList.toggle('err', errLine === i + 1);
      c.classList.toggle('cur', curLine === i + 1);
    }
    gutter.scrollTop = editor.scrollTop;
  }
  editor.addEventListener('input', () => { errLine = null; renderGutter(); });
  editor.addEventListener('scroll', () => { gutter.scrollTop = editor.scrollTop; });
  editor.addEventListener('keydown', e => {
    if (e.key === 'Tab') { e.preventDefault(); document.execCommand('insertText', false, '  '); }
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(); }
  });

  // --------------------------------------------------------- stack viz ----
  function renderStack(target, items, prev, top) {
    target.textContent = '';
    let common = 0;
    if (prev) while (common < prev.length && common < items.length && prev[common] === items[common]) common++;
    items.forEach((v, i) => {
      const c = el('div', 'cell' + (top && i === items.length - 1 ? ' top' : '') + (prev && i >= common ? ' new' : ''));
      c.title = 'signed ' + v + '   unsigned ' + (v >>> 0) + '   hex 0x' + (v >>> 0).toString(16).toUpperCase();
      c.appendChild(el('i', '', i === items.length - 1 ? 'top' : String(items.length - 1 - i)));
      c.appendChild(document.createTextNode(String(v)));
      target.appendChild(c);
    });
  }
  function refreshLive() {
    renderStack($('stack'), vm.ds, null, true);
    renderStack($('rstack'), vm.rs, null, false);
    $('depth').textContent = vm.ds.length ? '(' + vm.ds.length + ')' : '';
    renderWords();
  }

  // --------------------------------------------------------- word list ----
  function renderWords() {
    const list = $('wordlist'); list.textContent = '';
    const q = $('filter').value.trim().toLowerCase(), prims = $('showprims').checked;
    const words = [...vm.dict.values()].filter(w => (prims || w.kind !== 'prim') && w.name.toLowerCase().includes(q));
    if (!words.length) { list.appendChild(el('div', 'empty', prims || q ? 'No matching words.' : 'No user words yet — run a program.')); return; }
    for (const w of words) {
      const row = el('div', 'wrow'); row.tabIndex = 0; row.setAttribute('role', 'button');
      row.appendChild(el('span', 'wname', w.name.toLowerCase()));
      const eff = el('span', 'weff' + (w.eff ? '' : ' unk'), F.Forth.effectString(w).replace(/\s*\\.*$/, ''));
      if (!w.eff && w.effNote) eff.title = w.effNote;
      row.appendChild(eff);
      let b;
      if (w.kind === 'prim') b = el('span', 'badge plain', w.imm ? 'syntax' : 'built-in');
      else if (w.kind !== 'colon') b = el('span', 'badge plain', w.kind);
      else if (w.eff && w.declared) b = el('span', 'badge', 'verified ✓');
      else if (w.eff) b = el('span', 'badge warn', 'inferred');
      else b = el('span', 'badge plain', 'dynamic');
      row.appendChild(b);
      const open = () => { showDisasm(w); };
      row.addEventListener('click', open);
      row.addEventListener('keydown', e => { if (e.key === 'Enter') open(); });
      list.appendChild(row);
    }
  }
  function showDisasm(w) { $('disasm').textContent = vm.disassemble(w); selectTab('see'); }
  $('filter').addEventListener('input', () => vm && renderWords());
  $('showprims').addEventListener('change', () => vm && renderWords());

  // ------------------------------------------------------------- run ------
  function setStatus(text, cls) { status.textContent = text; status.className = 'status ' + (cls || ''); }
  function run() {
    stopPlay(); newVM(); clearOut(); errLine = null; curLine = null;
    const t0 = performance.now();
    const r = vm.run(editor.value);
    const ms = Math.max(1, Math.round(performance.now() - t0));
    if (!r.ok) {
      errLine = r.line || null;
      put((out.textContent && !out.textContent.endsWith('\n') ? '\n' : '') + 'error' + (r.line ? ' (line ' + r.line + ')' : '') + ': ' + r.error + '\n', 'e');
      setStatus('error', 'err');
    } else {
      const nw = [...vm.dict.values()].filter(w => w.kind === 'colon').length;
      put('\n✓ ran in ' + ms + ' ms · ' + nw + ' word' + (nw === 1 ? '' : 's') + ' compiled\n', 'g');
      setStatus('ok', 'ok');
    }
    renderGutter(); refreshLive();
  }

  function runRepl(line) {
    if (!vm) newVM();
    if (!line.trim()) return;
    history.push(line); hpos = history.length;
    put('ok> ' + line + '\n', 'i');
    const r = vm.run(line);
    if (r.error) put('error: ' + r.error + '\n', 'e');
    else if (!vm.cur) put(' ok  .S ' + '<' + vm.ds.length + '> ' + vm.ds.join(' ') + '\n', 'i');
    else put('  (compiling…)\n', 'i');
    refreshLive();
  }
  $('repl').addEventListener('keydown', e => {
    const inp = e.target;
    if (e.key === 'Enter') { const v = inp.value; inp.value = ''; runRepl(v); }
    else if (e.key === 'ArrowUp') { if (hpos > 0) inp.value = history[--hpos]; e.preventDefault(); }
    else if (e.key === 'ArrowDown') { hpos = Math.min(history.length, hpos + 1); inp.value = history[hpos] || ''; e.preventDefault(); }
  });

  // ---------------------------------------------------------- trace -------
  function doTrace() {
    stopPlay(); newVM(); clearOut(); errLine = null;
    const t = F.Tracer.record(vm, editor.value, { maxSteps: 20000 });
    tl = t; tlIndex = 0;
    put(t.output); 
    if (t.error) { put((t.output && !t.output.endsWith('\n') ? '\n' : '') + 'error: ' + t.error + '\n', 'e'); errLine = t.errLine; setStatus('error', 'err'); }
    else setStatus('traced ' + t.steps.length + ' steps' + (t.truncated ? ' (truncated)' : ''), t.truncated ? '' : 'ok');
    refreshLive();
    $('tl-empty').hidden = true; $('tl').hidden = false;
    const sc = $('scrub'); sc.max = t.steps.length; sc.value = 0;
    selectTab('timeline'); showStep(0);
  }
  function showStep(i) {
    if (!tl) return;
    const N = tl.steps.length;
    i = Math.max(0, Math.min(N, i));
    const prev = tlIndex <= i && i > 0 ? (tl.steps[i - 1] || null) : null;
    tlIndex = i; $('scrub').value = i;
    const s = i < N ? tl.steps[i] : null;
    const st = s || tl.final;
    renderStack($('tl-stack'), st.ds, prev && prev.ds, true);
    renderStack($('tl-rstack'), st.rs, null, false);
    $('tl-pos').textContent = 'step ' + i + ' / ' + N;
    const now = $('tl-now'); now.textContent = '';
    if (s) {
      now.appendChild(el('span', '', 'in '));
      now.appendChild(el('b', '', s.word));
      now.appendChild(el('span', '', ' · about to run '));
      now.appendChild(el('b', '', s.op));
      if (s.line) now.appendChild(el('span', '', ' · line ' + s.line));
    } else now.appendChild(el('b', '', tl.truncated ? 'trace limit reached' : (tl.error ? 'stopped: ' + tl.error : 'finished')));
    $('tl-out').textContent = tl.output.slice(0, st.out);
    const ops = $('tl-ops'); ops.textContent = '';
    for (let k = Math.max(0, i - 4); k <= Math.min(N - 1, i + 6); k++) {
      const r = el('div', k === i ? 'cur' : '');
      r.appendChild(el('span', '', k + '  ' + tl.steps[k].op));
      r.appendChild(el('span', '', tl.steps[k].word + '  [' + tl.steps[k].ds.join(' ') + ']'));
      r.addEventListener('click', () => showStep(k));
      ops.appendChild(r);
    }
    curLine = s && s.line ? s.line : null; renderGutter();
  }
  function stopPlay() { if (timer) { clearInterval(timer); timer = null; $('tl-play').textContent = '▶'; } }
  function togglePlay() {
    if (timer) return stopPlay();
    if (!tl) return;
    if (tlIndex >= tl.steps.length) showStep(0);
    $('tl-play').textContent = '❚❚';
    const stepMs = tl.steps.length > 400 ? 20 : 130;
    timer = setInterval(() => { if (tlIndex >= tl.steps.length) stopPlay(); else showStep(tlIndex + 1); }, stepMs);
  }
  $('trace').onclick = doTrace;
  $('scrub').addEventListener('input', e => { stopPlay(); showStep(+e.target.value); });
  $('tl-first').onclick = () => { stopPlay(); showStep(0); };
  $('tl-back').onclick = () => { stopPlay(); showStep(tlIndex - 1); };
  $('tl-fwd').onclick = () => { stopPlay(); showStep(tlIndex + 1); };
  $('tl-last').onclick = () => { stopPlay(); showStep(tl ? tl.steps.length : 0); };
  $('tl-play').onclick = togglePlay;
  document.addEventListener('keydown', e => {
    if (!$('tab-timeline').classList.contains('active') || !tl) return;
    if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && document.activeElement.id !== 'scrub') return;
    if (e.key === 'ArrowLeft') { stopPlay(); showStep(tlIndex - 1); e.preventDefault(); }
    if (e.key === 'ArrowRight') { stopPlay(); showStep(tlIndex + 1); e.preventDefault(); }
  });

  // -------------------------------------------------------- profile -------
  function doProfile() {
    newVM(); clearOut();
    const p = F.Tracer.profile(vm, editor.value);
    put(p.output); if (p.error) { put('\nerror: ' + p.error + '\n', 'e'); setStatus('error', 'err'); } else setStatus('profiled', 'ok');
    refreshLive();
    const box = $('prof'); box.textContent = ''; box.className = '';
    box.appendChild(el('h3', '', p.total + ' ops executed'));
    if (!p.rows.length) box.appendChild(el('div', 'empty', 'Nothing executed.'));
    const max = p.rows.length ? p.rows[0].ops : 1;
    for (const r of p.rows.slice(0, 24)) {
      const b = el('div', 'bar'); b.appendChild(el('span', '', r.name));
      const tr = el('div', 'track'); const f = el('div', 'fill'); f.style.width = (100 * r.ops / max) + '%'; tr.appendChild(f); b.appendChild(tr);
      b.appendChild(el('span', 'num', r.ops + ' · ' + (r.pct * 100).toFixed(1) + '%' + (r.calls ? ' · ' + r.calls + '×' : '')));
      box.appendChild(b);
    }
    selectTab('profile');
  }
  $('profile').onclick = doProfile;
  $('run').onclick = run;
  $('reset').onclick = () => { stopPlay(); newVM(); clearOut(); tl = null; curLine = errLine = null; $('tl').hidden = true; $('tl-empty').hidden = false; setStatus(''); renderGutter(); refreshLive(); put('VM reset.\n', 'i'); };

  // ----------------------------------------------------------- tabs -------
  function selectTab(name) {
    document.querySelectorAll('.tabs button').forEach(b => { const on = b.dataset.tab === name; b.classList.toggle('active', on); b.setAttribute('aria-selected', on); });
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.id === 'tab-' + name));
  }
  document.querySelectorAll('.tabs button').forEach(b => b.onclick = () => selectTab(b.dataset.tab));

  // ------------------------------------------------------- examples -------
  const sel = $('examples');
  for (const k of Object.keys(window.EXAMPLES)) sel.appendChild(new Option(k, k));
  sel.addEventListener('change', () => { editor.value = window.EXAMPLES[sel.value]; errLine = null; curLine = null; renderGutter(); run(); });
  $('optimize').addEventListener('change', run);

  // ------------------------------------------------------ share link ------
  editor.value = window.EXAMPLES[sel.value];
  newVM(); renderGutter(); run();
  window.__fw = { get vm() { return vm; }, get trace() { return tl; } };
})();
