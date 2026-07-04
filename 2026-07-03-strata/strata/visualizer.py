"""Renders a self-contained interactive HTML commit-graph visualizer.

Layout is computed here in Python (a simplified `git log --graph`-style
lane assignment over the commit DAG); per-commit unified diffs (against
the commit's first parent) are also precomputed here with the same
Myers diff engine used everywhere else in Strata, then the whole thing
is embedded as JSON in a static HTML page so it opens directly in a
browser with no server.
"""

import json

from .diff import split_lines, unified_diff
from .store import ObjectNotFound

# Categorical palette (validated, CVD-safe ordering) — see the project's
# dataviz reference palette. Cycled across lanes; a real repo rarely has
# more than a handful of concurrently-live branches.
LANE_COLORS_LIGHT = ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"]
LANE_COLORS_DARK = ["#3987e5", "#199e70", "#c98500", "#008300", "#9085e9", "#e66767", "#d55181", "#d95926"]


def _topo_order(commits):
    """Order commits so every commit appears strictly after all of its
    children (Kahn's algorithm on the child->parent DAG), tie-broken by
    timestamp descending. This is the ordering the lane layout depends
    on — plain timestamp sort would break under clock skew or same-
    second commits (very possible: a demo repo can create several
    commits within the same wall-clock second)."""
    children_of = {cid: [] for cid in commits}
    for cid, commit in commits.items():
        for p in commit.parents:
            if p in children_of:
                children_of[p].append(cid)
    remaining_children = {cid: len(children_of[cid]) for cid in commits}
    ready = [cid for cid, n in remaining_children.items() if n == 0]

    order = []
    while ready:
        ready.sort(key=lambda cid: commits[cid].timestamp, reverse=True)
        cid = ready.pop(0)
        order.append(cid)
        for p in commits[cid].parents:
            if p not in remaining_children:
                continue
            remaining_children[p] -= 1
            if remaining_children[p] == 0:
                ready.append(p)
    return order


def _assign_lanes(commits, order):
    lanes = []  # lanes[i] = commit id this lane currently expects, or None if free
    lane_of = {}
    for cid in order:
        lane_idx = None
        for i, expected in enumerate(lanes):
            if expected == cid:
                lane_idx = i
                break
        if lane_idx is None:
            for i, expected in enumerate(lanes):
                if expected is None:
                    lane_idx = i
                    break
        if lane_idx is None:
            lane_idx = len(lanes)
            lanes.append(None)

        lane_of[cid] = lane_idx
        parents = commits[cid].parents
        if not parents:
            lanes[lane_idx] = None
        else:
            lanes[lane_idx] = parents[0]
            for p in parents[1:]:
                if p in lanes:
                    continue
                free = None
                for i, expected in enumerate(lanes):
                    if expected is None:
                        free = i
                        break
                if free is None:
                    free = len(lanes)
                    lanes.append(None)
                lanes[free] = p
    return lane_of


def _blob_text(repo, blob_hash):
    if blob_hash is None:
        return ""
    try:
        return repo.store.read(blob_hash)[1].decode("utf-8")
    except (UnicodeDecodeError, ObjectNotFound):
        return None


def _commit_diff_lines(repo, commit_id, commit):
    if not commit.parents:
        parent_files = {}
    else:
        parent_files = repo._flatten_tree(repo.get_commit(commit.parents[0]).tree)
    files = repo._flatten_tree(commit.tree)
    out = []
    for path in sorted(set(files) | set(parent_files)):
        old_hash = parent_files.get(path, (None, None))[0]
        new_hash = files.get(path, (None, None))[0]
        if old_hash == new_hash:
            continue
        old_text = _blob_text(repo, old_hash)
        new_text = _blob_text(repo, new_hash)
        if old_text is None or new_text is None:
            if old_hash != new_hash:
                out.append(f"Binary files a/{path} and b/{path} differ\n")
            continue
        out.extend(unified_diff(split_lines(old_text), split_lines(new_text), f"a/{path}", f"b/{path}"))
    return "".join(out)


def _build_graph_data(repo):
    commits = {}
    stack = []
    head = repo.head_commit()
    branch_heads = {}
    for name in repo.list_branches():
        cid = repo.branch_commit(name)
        if cid:
            branch_heads.setdefault(cid, []).append(name)
            stack.append(cid)

    seen = set()
    while stack:
        cid = stack.pop()
        if cid in seen:
            continue
        seen.add(cid)
        commit = repo.get_commit(cid)
        commits[cid] = commit
        stack.extend(commit.parents)

    order = _topo_order(commits)
    lane_of = _assign_lanes(commits, order)
    row_of = {cid: i for i, cid in enumerate(order)}

    nodes = []
    for cid in order:
        commit = commits[cid]
        nodes.append({
            "id": cid,
            "row": row_of[cid],
            "lane": lane_of[cid],
            "parents": list(commit.parents),
            "message": commit.message.strip(),
            "author": commit.author,
            "timestamp": commit.timestamp,
            "branches": branch_heads.get(cid, []),
            "isHead": cid == head,
            "diff": _commit_diff_lines(repo, cid, commit),
        })

    max_lane = max((n["lane"] for n in nodes), default=0)
    return {
        "nodes": nodes,
        "lanes": max_lane + 1,
        "head": head,
        "currentBranch": repo.current_branch(),
    }


_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Strata — commit graph</title>
<style>
  :root {
    --surface-1: #fcfcfb; --surface-page: #f9f9f7;
    --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #898781;
    --gridline: #e1e0d9; --border: rgba(11,11,11,0.10);
    --chip-bg: #f0efec; --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    --add-bg: #e6f6ec; --add-fg: #006300; --del-bg: #fbe9e8; --del-fg: #9c1c1c;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --surface-1: #1a1a19; --surface-page: #0d0d0d;
      --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
      --gridline: #2c2c2a; --border: rgba(255,255,255,0.10);
      --chip-bg: #232320;
      --add-bg: #103018; --add-fg: #7be08f; --del-bg: #3a1414; --del-fg: #f0a3a0;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--surface-page); color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    display: flex; height: 100vh; overflow: hidden;
  }
  #graph-pane {
    flex: 0 0 auto; min-width: 320px; max-width: 46%; border-right: 1px solid var(--border);
    overflow: auto; padding: 20px 12px;
  }
  #detail-pane { flex: 1 1 auto; overflow: auto; padding: 24px 32px; }
  h1 { font-size: 15px; font-weight: 600; margin: 0 0 4px; letter-spacing: 0.01em; }
  .subtitle { font-size: 12px; color: var(--text-muted); margin: 0 0 16px; }
  svg { display: block; overflow: visible; }
  .commit-row { cursor: pointer; }
  .commit-row:hover .commit-label { fill: var(--text-primary); }
  .commit-dot { stroke: var(--surface-page); stroke-width: 2px; }
  .commit-row.selected .commit-dot { stroke: var(--text-primary); stroke-width: 3px; }
  .commit-label { font-size: 11px; fill: var(--text-secondary); font-family: var(--mono); }
  .commit-msg { font-size: 12px; fill: var(--text-primary); }
  .edge { fill: none; stroke-width: 2px; opacity: 0.55; }
  .branch-chip {
    font-size: 10px; fill: var(--text-primary); font-weight: 600;
  }
  .branch-chip-bg { fill: var(--chip-bg); stroke: var(--border); }
  .head-marker { font-size: 10px; font-weight: 700; }

  .meta-row { display: flex; gap: 8px; align-items: baseline; margin-bottom: 2px; }
  .meta-label { font-size: 11px; color: var(--text-muted); width: 64px; flex: none; text-transform: uppercase; letter-spacing: 0.04em; }
  .meta-value { font-size: 13px; color: var(--text-secondary); font-family: var(--mono); }
  #commit-message { font-size: 20px; font-weight: 600; margin: 4px 0 16px; white-space: pre-wrap; }
  .branch-pill {
    display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 8px;
    border-radius: 999px; background: var(--chip-bg); border: 1px solid var(--border);
    margin-right: 6px;
  }
  #diff { margin-top: 20px; font-family: var(--mono); font-size: 12.5px; line-height: 1.5;
    border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
  .diff-hunk-header { color: var(--text-muted); background: var(--surface-1); padding: 2px 10px; }
  .diff-file-header { color: var(--text-secondary); background: var(--surface-1); padding: 4px 10px; font-weight: 600; border-top: 1px solid var(--border); }
  .diff-add { background: var(--add-bg); color: var(--add-fg); padding: 0 10px; white-space: pre-wrap; }
  .diff-del { background: var(--del-bg); color: var(--del-fg); padding: 0 10px; white-space: pre-wrap; }
  .diff-ctx { color: var(--text-secondary); padding: 0 10px; white-space: pre-wrap; }
  .diff-empty { color: var(--text-muted); padding: 16px; font-style: italic; font-family: system-ui, sans-serif; }
  ::selection { background: #2a78d633; }
</style>
</head>
<body>
  <div id="graph-pane">
    <h1>Strata commit graph</h1>
    <p class="subtitle" id="subtitle"></p>
    <svg id="graph-svg"></svg>
  </div>
  <div id="detail-pane">
    <div class="meta-row"><span class="meta-label">Commit</span><span class="meta-value" id="commit-id"></span></div>
    <div class="meta-row"><span class="meta-label">Author</span><span class="meta-value" id="commit-author"></span></div>
    <div class="meta-row"><span class="meta-label">Date</span><span class="meta-value" id="commit-date"></span></div>
    <div class="meta-row"><span class="meta-label">Parents</span><span class="meta-value" id="commit-parents"></span></div>
    <div id="commit-branches"></div>
    <div id="commit-message"></div>
    <div id="diff"></div>
  </div>

<script>
const DATA = __DATA_JSON__;
const isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
const LANE_COLORS = isDark ? __LANE_COLORS_DARK__ : __LANE_COLORS_LIGHT__;

const ROW_H = 46, LANE_W = 22, LEFT_PAD = 20, DOT_R = 5;
const svg = document.getElementById('graph-svg');
const nodesById = {};
DATA.nodes.forEach(n => nodesById[n.id] = n);

function laneColor(lane) { return LANE_COLORS[lane % LANE_COLORS.length]; }
function xOf(lane) { return LEFT_PAD + lane * LANE_W; }
function yOf(row) { return ROW_H / 2 + row * ROW_H; }

function svgEl(tag, attrs) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

function renderGraph() {
  const width = LEFT_PAD * 2 + DATA.lanes * LANE_W + 260;
  const height = ROW_H * DATA.nodes.length + ROW_H;
  svg.setAttribute('width', width);
  svg.setAttribute('height', height);
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.innerHTML = '';

  // edges first (under dots)
  DATA.nodes.forEach(n => {
    n.parents.forEach(pid => {
      const p = nodesById[pid];
      if (!p) return;
      const x1 = xOf(n.lane), y1 = yOf(n.row), x2 = xOf(p.lane), y2 = yOf(p.row);
      const path = (x1 === x2)
        ? `M ${x1} ${y1} L ${x2} ${y2}`
        : `M ${x1} ${y1} C ${x1} ${(y1+y2)/2}, ${x2} ${(y1+y2)/2}, ${x2} ${y2}`;
      svg.appendChild(svgEl('path', { d: path, class: 'edge', stroke: laneColor(n.lane) }));
    });
  });

  DATA.nodes.forEach(n => {
    const g = svgEl('g', { class: 'commit-row', 'data-id': n.id });
    const x = xOf(n.lane), y = yOf(n.row);
    g.appendChild(svgEl('circle', { cx: x, cy: y, r: DOT_R, class: 'commit-dot', fill: laneColor(n.lane) }));

    let labelX = xOf(DATA.lanes) + 12;
    if (n.isHead) {
      const t = svgEl('text', { x: labelX, y: y + 4, class: 'head-marker', fill: laneColor(n.lane) });
      t.textContent = 'HEAD';
      g.appendChild(t);
      labelX += 44;
    }
    n.branches.forEach(b => {
      const w = 8 + b.length * 6.2;
      g.appendChild(svgEl('rect', { x: labelX, y: y - 9, width: w, height: 16, rx: 8, class: 'branch-chip-bg' }));
      const t = svgEl('text', { x: labelX + w / 2, y: y + 3, class: 'branch-chip', 'text-anchor': 'middle' });
      t.textContent = b;
      g.appendChild(t);
      labelX += w + 6;
    });

    const idText = svgEl('text', { x: labelX, y: y + 4, class: 'commit-label' });
    idText.textContent = n.id.slice(0, 8);
    g.appendChild(idText);
    labelX += 66;

    const msgText = svgEl('text', { x: labelX, y: y + 4, class: 'commit-msg' });
    let firstLine = n.message.split('\\n')[0];
    if (firstLine.length > 48) firstLine = firstLine.slice(0, 47) + '\\u2026';
    msgText.textContent = firstLine;
    g.appendChild(msgText);

    g.addEventListener('click', () => selectCommit(n.id));
    svg.appendChild(g);
  });
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderDiff(diffText) {
  const container = document.getElementById('diff');
  container.innerHTML = '';
  if (!diffText) {
    container.innerHTML = '<div class="diff-empty">No changes (initial commit with an empty tree, or identical to parent).</div>';
    return;
  }
  diffText.split('\\n').forEach(line => {
    if (line === '') return;
    let cls = 'diff-ctx';
    if (line.startsWith('+++') || line.startsWith('---')) cls = 'diff-file-header';
    else if (line.startsWith('@@')) cls = 'diff-hunk-header';
    else if (line.startsWith('+')) cls = 'diff-add';
    else if (line.startsWith('-')) cls = 'diff-del';
    const div = document.createElement('div');
    div.className = cls;
    div.textContent = line;
    container.appendChild(div);
  });
}

function selectCommit(id) {
  document.querySelectorAll('.commit-row').forEach(el => el.classList.toggle('selected', el.dataset.id === id));
  const n = nodesById[id];
  document.getElementById('commit-id').textContent = n.id;
  document.getElementById('commit-author').textContent = n.author;
  document.getElementById('commit-date').textContent = new Date(n.timestamp * 1000).toString();
  document.getElementById('commit-parents').textContent = n.parents.length ? n.parents.map(p => p.slice(0,10)).join(', ') : '(none — root commit)';
  document.getElementById('commit-branches').innerHTML = n.branches.map(b => `<span class="branch-pill">${escapeHtml(b)}</span>`).join('') + (n.isHead ? '<span class="branch-pill">HEAD</span>' : '');
  document.getElementById('commit-message').textContent = n.message;
  renderDiff(n.diff);
}

document.getElementById('subtitle').textContent =
  DATA.nodes.length + ' commit' + (DATA.nodes.length === 1 ? '' : 's') +
  (DATA.currentBranch ? ' \\u00b7 on ' + DATA.currentBranch : ' \\u00b7 detached HEAD');

renderGraph();
if (DATA.nodes.length) selectCommit(DATA.nodes[0].id);
</script>
</body>
</html>
"""


def render_html(repo):
    data = _build_graph_data(repo)
    html_out = _TEMPLATE
    html_out = html_out.replace("__DATA_JSON__", json.dumps(data))
    html_out = html_out.replace("__LANE_COLORS_LIGHT__", json.dumps(LANE_COLORS_LIGHT))
    html_out = html_out.replace("__LANE_COLORS_DARK__", json.dumps(LANE_COLORS_DARK))
    return html_out
