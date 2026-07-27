"""The visualizer's single HTML page: inline CSS + JS, zero build step,
zero client-side type inference. Every fetch() call hits a Python
endpoint (`unify/web/server.py`) that does the actual lexing, parsing,
Algorithm W inference, and evaluation -- the browser only renders JSON
the server already computed, the same zero-client-logic pattern this
repo's other server-backed UIs (Gambit, Formulate, Trove) use.
"""

PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Unify -- Hindley-Milner type inference, visualized</title>
<style>
  :root {
    --bg: #0f1117; --panel: #171a23; --panel-2: #1e2230; --border: #2a2f3f;
    --text: #e6e8ef; --muted: #8890a4; --accent: #7dd3fc; --accent-2: #c4b5fd;
    --ok: #86efac; --err: #fca5a5; --mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
  body { min-height: 100vh; }
  header { padding: 1.25rem 1.5rem 0.75rem; border-bottom: 1px solid var(--border); }
  header h1 { margin: 0; font-size: 1.25rem; font-weight: 600; letter-spacing: -0.01em; }
  header h1 span { color: var(--accent); }
  header p { margin: 0.35rem 0 0; color: var(--muted); font-size: 0.85rem; }
  main { display: grid; grid-template-columns: minmax(320px, 1fr) minmax(360px, 1.3fr);
    gap: 1.25rem; padding: 1.25rem 1.5rem 2rem; align-items: start; }
  @media (max-width: 860px) { main { grid-template-columns: 1fr; } }
  .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 1rem; }
  .panel h2 { margin: 0 0 0.6rem; font-size: 0.8rem; text-transform: uppercase;
    letter-spacing: 0.06em; color: var(--muted); font-weight: 600; }
  textarea { width: 100%; min-height: 140px; resize: vertical; background: var(--panel-2);
    color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem;
    font-family: var(--mono); font-size: 0.92rem; line-height: 1.5; }
  textarea:focus { outline: 2px solid var(--accent); outline-offset: -1px; }
  .row { display: flex; gap: 0.6rem; align-items: center; margin-top: 0.7rem; flex-wrap: wrap; }
  select, button { font-family: inherit; font-size: 0.85rem; padding: 0.5rem 0.8rem;
    border-radius: 7px; border: 1px solid var(--border); background: var(--panel-2); color: var(--text); }
  select { flex: 1; min-width: 180px; }
  button { cursor: pointer; background: var(--accent); color: #0b1220; font-weight: 600; border: none; }
  button:hover { filter: brightness(1.08); }
  button:active { transform: translateY(1px); }
  .hint { color: var(--muted); font-size: 0.78rem; margin-top: 0.5rem; }
  .result-row { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 0.9rem; }
  .chip { background: var(--panel-2); border: 1px solid var(--border); border-radius: 8px;
    padding: 0.5rem 0.75rem; font-family: var(--mono); font-size: 0.88rem; flex: 1; min-width: 140px; }
  .chip .k { color: var(--muted); font-size: 0.7rem; text-transform: uppercase;
    letter-spacing: 0.05em; display: block; margin-bottom: 0.2rem; }
  .chip .v { color: var(--accent); }
  .chip.value .v { color: var(--ok); }
  .chip.error .v { color: var(--err); }
  pre.error-box { background: #23131a; border: 1px solid #4a2530; color: var(--err);
    border-radius: 8px; padding: 0.75rem; font-family: var(--mono); font-size: 0.85rem;
    white-space: pre-wrap; margin: 0 0 0.9rem; }
  #derivation { font-family: var(--mono); font-size: 0.86rem; }
  .judgment { border-left: 2px solid var(--border); margin-left: 0.5rem; padding-left: 0.75rem;
    margin-top: 0.35rem; }
  .judgment > .head { display: flex; gap: 0.5rem; align-items: baseline; flex-wrap: wrap; }
  .judgment .label { color: var(--accent-2); font-weight: 700; background: rgba(196,181,253,0.12);
    border-radius: 5px; padding: 0.05rem 0.4rem; }
  .judgment .type { color: var(--accent); }
  .judgment .note { color: var(--muted); font-style: italic; }
  .empty { color: var(--muted); font-style: italic; }
  footer { padding: 0 1.5rem 2rem; color: var(--muted); font-size: 0.78rem; }
  footer code { font-family: var(--mono); background: var(--panel-2); padding: 0.1rem 0.35rem; border-radius: 4px; }
</style>
</head>
<body>
<header>
  <h1>Unify <span>&mdash;</span> Hindley-Milner type inference, visualized</h1>
  <p>Everything below runs server-side, in real Python &mdash; the browser only renders JSON the server computed.</p>
</header>
<main>
  <section class="panel">
    <h2>Source</h2>
    <textarea id="source" spellcheck="false">let id = fun x -> x in (id 1, id true)</textarea>
    <div class="row">
      <select id="examples"><option value="">-- load an example --</option></select>
      <button id="run">Run &nbsp;(Ctrl+Enter)</button>
    </div>
    <p class="hint">Type a Unify expression. See README.md for the language reference.</p>
  </section>
  <section class="panel">
    <h2>Result</h2>
    <div id="results"><p class="empty">Run something to see its type, value, and derivation.</p></div>
  </section>
</main>
<footer>Served by <code>python3 -m unify.web.server</code> &mdash; a real stdlib <code>http.server</code>, no client-side inference logic.</footer>
<script>
const $ = (sel) => document.querySelector(sel);
const sourceBox = $('#source');
const resultsBox = $('#results');
const examplesSelect = $('#examples');

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function renderJudgment(node) {
  const head = document.createElement('div');
  head.className = 'head';
  const label = document.createElement('span');
  label.className = 'label';
  label.textContent = node.label;
  const type = document.createElement('span');
  type.className = 'type';
  type.textContent = node.type;
  head.appendChild(label);
  head.appendChild(type);
  if (node.note) {
    const note = document.createElement('span');
    note.className = 'note';
    note.textContent = '(' + node.note + ')';
    head.appendChild(note);
  }
  const wrap = document.createElement('div');
  wrap.className = 'judgment';
  wrap.appendChild(head);
  for (const child of node.children || []) {
    wrap.appendChild(renderJudgment(child));
  }
  return wrap;
}

async function runInference() {
  const source = sourceBox.value;
  resultsBox.innerHTML = '<p class="empty">Running&hellip;</p>';
  let result;
  try {
    const resp = await fetch('/api/infer', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({source}),
    });
    result = await resp.json();
  } catch (e) {
    resultsBox.innerHTML = '<pre class="error-box">could not reach the server: ' + escapeHtml(String(e)) + '</pre>';
    return;
  }

  resultsBox.innerHTML = '';

  if (!result.ok) {
    const pre = document.createElement('pre');
    pre.className = 'error-box';
    pre.textContent = result.error;
    resultsBox.appendChild(pre);
    return;
  }

  const row = document.createElement('div');
  row.className = 'result-row';

  const typeChip = document.createElement('div');
  typeChip.className = 'chip';
  typeChip.innerHTML = '<span class="k">Principal type</span><span class="v">' + escapeHtml(result.type) + '</span>';
  row.appendChild(typeChip);

  const valueChip = document.createElement('div');
  if (result.eval_error) {
    valueChip.className = 'chip error';
    valueChip.innerHTML = '<span class="k">Evaluation</span><span class="v">error</span>';
  } else {
    valueChip.className = 'chip value';
    valueChip.innerHTML = '<span class="k">Value</span><span class="v">' + escapeHtml(result.value) + '</span>';
  }
  row.appendChild(valueChip);
  resultsBox.appendChild(row);

  if (result.eval_error) {
    const pre = document.createElement('pre');
    pre.className = 'error-box';
    pre.textContent = result.eval_error;
    resultsBox.appendChild(pre);
  }

  const h2 = document.createElement('h2');
  h2.textContent = 'Derivation';
  h2.style.marginTop = '0.9rem';
  resultsBox.appendChild(h2);
  const derivationBox = document.createElement('div');
  derivationBox.id = 'derivation';
  derivationBox.appendChild(renderJudgment(result.derivation));
  resultsBox.appendChild(derivationBox);
}

$('#run').addEventListener('click', runInference);
sourceBox.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') runInference();
});

async function loadExamples() {
  const resp = await fetch('/api/examples');
  const examples = await resp.json();
  for (const ex of examples) {
    const opt = document.createElement('option');
    opt.value = ex.source;
    opt.textContent = ex.name;
    examplesSelect.appendChild(opt);
  }
}
examplesSelect.addEventListener('change', () => {
  if (examplesSelect.value) {
    sourceBox.value = examplesSelect.value;
    runInference();
  }
});

loadExamples();
runInference();
</script>
</body>
</html>
"""
