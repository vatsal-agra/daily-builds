"""A stdlib http.server-backed web UI: the browser holds zero search
logic (same pattern as Formulate's spreadsheet engine and Gambit's chess
board) — every keystroke and query is a network round trip to this
server, which owns the index, the query parser, ranking, fuzzy
correction, and autocomplete.

The client renders every server-supplied string via `textContent` /
DOM node construction, never `innerHTML` string concatenation — several
of this repo's own past-project READMEs contain literal `<script>` /
HTML-like text in code examples, so this is a real XSS surface once
search results are rendered in a browser, not a hypothetical one.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .engine import Engine

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trove</title>
<style>
  :root {
    --bg: #0f1115; --panel: #161a21; --border: #262b35; --text: #e8eaed;
    --muted: #8a92a3; --accent: #6ea8ff; --mark-bg: #6ea8ff33; --mark-text: #cfe0ff;
    --error: #ff6e6e;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    min-height: 100vh;
  }
  .wrap { max-width: 760px; margin: 0 auto; padding: 48px 20px 80px; }
  h1 {
    font-size: 28px; font-weight: 650; letter-spacing: -0.02em; margin: 0 0 4px;
    display: flex; align-items: baseline; gap: 10px;
  }
  h1 .tag {
    font-size: 12px; font-weight: 600; color: var(--muted); border: 1px solid var(--border);
    border-radius: 999px; padding: 2px 9px; letter-spacing: 0.02em;
  }
  .subtitle { color: var(--muted); font-size: 14px; margin: 0 0 28px; }
  .search-box { position: relative; }
  input[type=text] {
    width: 100%; font-size: 16px; padding: 13px 16px; border-radius: 10px;
    border: 1px solid var(--border); background: var(--panel); color: var(--text);
    outline: none; transition: border-color 0.15s;
  }
  input[type=text]:focus { border-color: var(--accent); }
  .suggestions {
    position: absolute; left: 0; right: 0; top: calc(100% + 6px); z-index: 10;
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    overflow: hidden; display: none; box-shadow: 0 12px 28px rgba(0,0,0,0.35);
  }
  .suggestions.open { display: block; }
  .suggestion {
    padding: 9px 16px; cursor: pointer; color: var(--muted); font-size: 14px;
  }
  .suggestion:hover, .suggestion.active { background: #1f2430; color: var(--text); }
  .meta-row {
    display: flex; justify-content: space-between; align-items: baseline;
    margin: 22px 0 10px; font-size: 13px; color: var(--muted); min-height: 18px;
  }
  .corrections { font-size: 13px; color: var(--accent); margin-top: 10px; }
  .error-box {
    margin-top: 18px; padding: 12px 14px; border-radius: 8px; font-size: 14px;
    background: #2a1418; border: 1px solid #4a2028; color: var(--error);
  }
  .empty-state { margin-top: 40px; color: var(--muted); font-size: 14px; line-height: 1.8; }
  .empty-state code {
    background: var(--panel); border: 1px solid var(--border); border-radius: 5px;
    padding: 1px 6px; color: var(--text); font-size: 13px;
  }
  ul.results { list-style: none; margin: 0; padding: 0; }
  li.result {
    padding: 16px 0; border-top: 1px solid var(--border);
  }
  li.result:first-child { border-top: none; }
  .result-title-row { display: flex; align-items: baseline; gap: 10px; }
  .result-title { font-size: 16px; font-weight: 600; color: var(--text); text-decoration: none; }
  .result-score {
    font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums;
    border: 1px solid var(--border); border-radius: 5px; padding: 1px 6px;
  }
  .result-path { font-size: 12.5px; color: var(--muted); margin-top: 2px; }
  .result-snippet { font-size: 14px; color: #c4c9d4; margin-top: 8px; line-height: 1.6; }
  .result-snippet mark {
    background: var(--mark-bg); color: var(--mark-text); border-radius: 3px;
    padding: 0 2px; font-weight: 600;
  }
  footer { margin-top: 48px; color: var(--muted); font-size: 12px; }
  footer a { color: var(--muted); }
  @media (prefers-color-scheme: light) {
    :root {
      --bg: #f6f7f9; --panel: #ffffff; --border: #e2e5ea; --text: #191c22;
      --muted: #6b7280; --mark-bg: #dbe9ff; --mark-text: #14315c; --error: #b3261e;
    }
    .error-box { background: #fdecea; border-color: #f5c2c0; }
    .suggestions { box-shadow: 0 12px 28px rgba(20,20,30,0.12); }
  }
</style>
</head>
<body>
<div class="wrap">
  <h1>Trove <span class="tag">from-scratch search engine</span></h1>
  <p class="subtitle">Tokenizer &middot; Porter stemmer &middot; inverted index &middot; BM25 &middot; boolean/phrase query language &middot; fuzzy correction</p>

  <div class="search-box">
    <input id="q" type="text" autocomplete="off" spellcheck="false"
           placeholder='Try: CDCL solver &nbsp;&middot;&nbsp; &quot;clause learning&quot; &nbsp;&middot;&nbsp; raft AND consensus &nbsp;&middot;&nbsp; comp*'>
    <div id="suggestions" class="suggestions"></div>
  </div>

  <div id="meta" class="meta-row"></div>
  <div id="error" class="error-box" style="display:none"></div>
  <div id="empty" class="empty-state"></div>
  <ul id="results" class="results"></ul>

  <footer>Trove &middot; a daily build &middot; <span id="stats"></span></footer>
</div>
<script>
const qEl = document.getElementById('q');
const suggEl = document.getElementById('suggestions');
const metaEl = document.getElementById('meta');
const errEl = document.getElementById('error');
const emptyEl = document.getElementById('empty');
const resultsEl = document.getElementById('results');
const statsEl = document.getElementById('stats');

let debounceTimer = null;
let activeSuggestion = -1;
let currentSuggestions = [];
let searchSeq = 0;

function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }

function renderSnippet(container, snippet) {
  // snippet contains **term** markers only -- split on that literal
  // delimiter and build real DOM nodes via textContent, never innerHTML,
  // so no corpus content (however adversarial) can execute as markup.
  const parts = snippet.split('**');
  parts.forEach((part, i) => {
    if (i % 2 === 1) {
      const mark = document.createElement('mark');
      mark.textContent = part;
      container.appendChild(mark);
    } else if (part) {
      container.appendChild(document.createTextNode(part));
    }
  });
}

function renderResults(outcome) {
  clear(resultsEl);
  clear(errEl);
  clear(emptyEl);
  errEl.style.display = 'none';

  if (outcome.error) {
    errEl.textContent = 'Query error: ' + outcome.error;
    errEl.style.display = 'block';
    metaEl.textContent = '';
    return;
  }

  const correctionsText = (outcome.corrections || [])
    .map(c => `no match for "${c[0]}" — showing results for "${c[1]}"`)
    .join('; ');

  if (!outcome.query) {
    metaEl.textContent = '';
  } else {
    metaEl.textContent = `${outcome.total_matches} match${outcome.total_matches === 1 ? '' : 'es'} · ${outcome.took_ms}ms`;
  }

  if (correctionsText) {
    const c = document.createElement('div');
    c.className = 'corrections';
    c.textContent = correctionsText;
    metaEl.after(c);
  }

  if (outcome.query && outcome.results.length === 0) {
    emptyEl.textContent = 'No results. Try a shorter or different query, or check the query syntax (AND / OR / NOT / "phrase" / prefix*).';
    return;
  }

  for (const r of outcome.results) {
    const li = document.createElement('li');
    li.className = 'result';

    const titleRow = document.createElement('div');
    titleRow.className = 'result-title-row';
    const title = document.createElement('span');
    title.className = 'result-title';
    title.textContent = r.title;
    const score = document.createElement('span');
    score.className = 'result-score';
    score.textContent = 'score ' + r.score.toFixed(3);
    titleRow.appendChild(title);
    titleRow.appendChild(score);
    li.appendChild(titleRow);

    const path = document.createElement('div');
    path.className = 'result-path';
    path.textContent = r.path;
    li.appendChild(path);

    if (r.snippet) {
      const snippet = document.createElement('div');
      snippet.className = 'result-snippet';
      renderSnippet(snippet, r.snippet);
      li.appendChild(snippet);
    }

    resultsEl.appendChild(li);
  }
}

async function runSearch(query) {
  const seq = ++searchSeq;
  if (!query.trim()) {
    renderResults({ query: '', results: [], corrections: [], total_matches: 0, took_ms: 0, error: null });
    return;
  }
  try {
    const res = await fetch('/api/search?q=' + encodeURIComponent(query) + '&top=10');
    const outcome = await res.json();
    if (seq !== searchSeq) return; // a newer query already superseded this one
    renderResults(outcome);
  } catch (e) {
    if (seq !== searchSeq) return;
    renderResults({ query, results: [], corrections: [], total_matches: 0, took_ms: 0, error: 'network error contacting the search server' });
  }
}

function closeSuggestions() {
  suggEl.classList.remove('open');
  clear(suggEl);
  currentSuggestions = [];
  activeSuggestion = -1;
}

async function updateSuggestions(prefix) {
  if (!prefix.trim() || prefix.includes(' ')) { closeSuggestions(); return; }
  try {
    const res = await fetch('/api/suggest?prefix=' + encodeURIComponent(prefix) + '&limit=8');
    const data = await res.json();
    currentSuggestions = data.suggestions || [];
    activeSuggestion = -1;
    clear(suggEl);
    if (currentSuggestions.length === 0) { closeSuggestions(); return; }
    currentSuggestions.forEach((s, i) => {
      const div = document.createElement('div');
      div.className = 'suggestion';
      div.textContent = s;
      div.addEventListener('mousedown', (ev) => {
        ev.preventDefault();
        qEl.value = s;
        closeSuggestions();
        runSearch(s);
      });
      suggEl.appendChild(div);
    });
    suggEl.classList.add('open');
  } catch (e) {
    closeSuggestions();
  }
}

qEl.addEventListener('input', () => {
  clearTimeout(debounceTimer);
  const value = qEl.value;
  debounceTimer = setTimeout(() => {
    runSearch(value);
    updateSuggestions(value.split(/\\s+/).pop());
  }, 150);
});

qEl.addEventListener('keydown', (ev) => {
  if (!suggEl.classList.contains('open')) return;
  const items = suggEl.querySelectorAll('.suggestion');
  if (ev.key === 'ArrowDown') {
    ev.preventDefault();
    activeSuggestion = Math.min(activeSuggestion + 1, items.length - 1);
  } else if (ev.key === 'ArrowUp') {
    ev.preventDefault();
    activeSuggestion = Math.max(activeSuggestion - 1, -1);
  } else if (ev.key === 'Escape') {
    closeSuggestions();
    return;
  } else {
    return;
  }
  items.forEach((el, i) => el.classList.toggle('active', i === activeSuggestion));
});

qEl.addEventListener('keydown', (ev) => {
  if (ev.key === 'Enter') {
    if (activeSuggestion >= 0 && currentSuggestions[activeSuggestion]) {
      qEl.value = currentSuggestions[activeSuggestion];
    }
    closeSuggestions();
    runSearch(qEl.value);
  }
});

document.addEventListener('click', (ev) => {
  if (ev.target !== qEl) closeSuggestions();
});

fetch('/api/stats').then(r => r.json()).then(s => {
  statsEl.textContent = `${s.documents} documents, ${s.terms} terms indexed`;
}).catch(() => {});

emptyEl.textContent = 'Start typing to search this repository\\'s own history of daily builds.';
qEl.focus();
</script>
</body>
</html>
"""


class TroveRequestHandler(BaseHTTPRequestHandler):
    engine = None  # set by serve()

    def log_message(self, fmt, *args):
        pass  # keep demo output quiet; errors still raised as exceptions

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/":
            self._send_html(PAGE)
            return

        if parsed.path == "/api/search":
            query = (params.get("q", [""])[0])
            top = _safe_int(params.get("top", ["10"])[0], default=10, lo=0, hi=50)
            outcome = self.engine.search(query, top=top)
            self._send_json({
                "query": outcome["query"],
                "results": [r.to_dict() for r in outcome["results"]],
                "corrections": outcome["corrections"],
                "total_matches": outcome["total_matches"],
                "took_ms": outcome["took_ms"],
                "error": outcome["error"],
            })
            return

        if parsed.path == "/api/suggest":
            prefix = params.get("prefix", [""])[0]
            limit = _safe_int(params.get("limit", ["8"])[0], default=8, lo=1, hi=20)
            self._send_json({"suggestions": self.engine.suggest(prefix, limit=limit)})
            return

        if parsed.path == "/api/stats":
            self._send_json({
                "documents": self.engine.index.N,
                "terms": len(self.engine.index.postings),
            })
            return

        self._send_json({"error": "not found"}, status=404)


def _safe_int(value, default, lo, hi):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def serve(index_path, port=8765):
    engine = Engine.load(index_path)
    handler = type("BoundTroveRequestHandler", (TroveRequestHandler,), {"engine": engine})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"Trove serving {engine.index.N} documents at http://127.0.0.1:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
