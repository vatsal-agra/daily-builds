"""Self-contained interactive HTML commit-graph + diff viewer."""

from __future__ import annotations

import html
import json

from .diffalgo import unified_diff
from .repository import Repository


def _collect_commits(repo: Repository) -> tuple[list[dict], dict[str, list[str]]]:
    """Walk every commit reachable from every branch/HEAD; return
    (commits sorted newest-first with parents/branch info, {branch: [sha,...]})."""
    all_sha: set[str] = set()
    starts = [s for s in (repo.head_commit(),) if s]
    for b in repo.list_branches():
        sha = repo.resolve_ref(b)
        if sha:
            starts.append(sha)

    stack = list(starts)
    while stack:
        cur = stack.pop()
        if cur in all_sha:
            continue
        all_sha.add(cur)
        c = repo.objects.read_commit(cur)
        stack.extend(c.parents)

    commits = []
    for sha in all_sha:
        c = repo.objects.read_commit(sha)
        commits.append(
            {
                "sha": sha,
                "parents": c.parents,
                "message": c.message.strip(),
                "author": c.author_name,
                "time": c.author_time,
                "tz": c.author_tz,
            }
        )
    commits.sort(key=lambda c: (c["time"], c["sha"]), reverse=True)

    branch_tips = {b: repo.resolve_ref(b) for b in repo.list_branches()}
    return commits, branch_tips


def _commit_diff(repo: Repository, sha: str) -> str:
    commit = repo.objects.read_commit(sha)
    this_files = repo.flatten_tree(commit.tree)
    if commit.parents:
        parent_files = repo.flatten_tree(repo.objects.read_commit(commit.parents[0]).tree)
    else:
        parent_files = {}

    def blob_lines(sha_):
        data = repo.objects.read_blob(sha_)
        text = data.decode("utf-8", errors="replace")
        if text == "":
            return []
        body = text[:-1] if text.endswith("\n") else text
        return body.split("\n")

    chunks = []
    for path in sorted(set(this_files) | set(parent_files)):
        old = parent_files.get(path)
        new = this_files.get(path)
        if old == new:
            continue
        old_lines = blob_lines(old[1]) if old else []
        new_lines = blob_lines(new[1]) if new else []
        label_a = path if old else "/dev/null"
        label_b = path if new else "/dev/null"
        text = unified_diff(old_lines, new_lines, label_a, label_b)
        if text:
            chunks.append(text)
    return "".join(chunks) if chunks else "(no file changes)"


def generate_html(repo: Repository) -> str:
    commits, branch_tips = _collect_commits(repo)
    diffs = {c["sha"]: _commit_diff(repo, c["sha"]) for c in commits}
    head_sha = repo.head_commit()
    head_branch = repo.head_ref()

    data = {
        "commits": commits,
        "branches": branch_tips,
        "diffs": diffs,
        "head": head_sha,
        "headBranch": head_branch,
    }
    # Commit messages/authors are attacker-controllable (arbitrary text in a
    # cloned repo). Escape "</" so a message containing "</script>" can't
    # break out of the <script> block this JSON is embedded in.
    data_json = json.dumps(data).replace("</", "<\\/")
    title = "Palimpsest — commit graph"
    return _TEMPLATE.replace("__TITLE__", html.escape(title)).replace(
        "__DATA_JSON__", data_json
    )


_TEMPLATE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #ffffff; --fg: #1a1a1a; --muted: #666; --border: #ddd;
    --panel: #f7f7f8; --accent: #2f6feb; --add: #1a7f37; --del: #cf222e;
    --chip-bg: #eef2ff;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --border:#30363d;
            --panel:#161b22; --accent:#58a6ff; --add:#3fb950; --del:#f85149;
            --chip-bg:#1f2a44; }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    background: var(--bg); color: var(--fg); display: flex; height: 100vh; overflow: hidden;
  }
  #graph-pane {
    width: 40%; min-width: 320px; border-right: 1px solid var(--border);
    overflow-y: auto; padding: 12px;
  }
  #diff-pane { flex: 1; overflow-y: auto; padding: 16px 20px; }
  h1 { font-size: 15px; margin: 0 0 12px; color: var(--muted); font-weight: 600; }
  .commit-row {
    display: flex; gap: 10px; align-items: flex-start; padding: 8px 10px;
    border-radius: 8px; cursor: pointer; border: 1px solid transparent;
  }
  .commit-row:hover { background: var(--panel); }
  .commit-row.selected { background: var(--chip-bg); border-color: var(--accent); }
  .graph-col { position: relative; width: 16px; flex-shrink: 0; padding-top: 4px; }
  .dot {
    width: 10px; height: 10px; border-radius: 50%; background: var(--accent);
    margin: 0 auto;
  }
  .commit-info { min-width: 0; }
  .commit-msg { font-weight: 600; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .commit-meta { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .sha-chip {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px;
    background: var(--chip-bg); color: var(--accent); padding: 1px 6px; border-radius: 10px;
    margin-right: 6px;
  }
  .branch-chip {
    font-size: 10px; background: var(--accent); color: #fff; padding: 1px 6px;
    border-radius: 10px; margin-right: 4px; font-weight: 600;
  }
  #diff-header { font-size: 14px; margin-bottom: 10px; color: var(--muted); }
  pre.diff {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px;
    line-height: 1.5; white-space: pre-wrap; word-break: break-word; margin: 0;
  }
  .l-add { color: var(--add); }
  .l-del { color: var(--del); }
  .l-hunk { color: var(--accent); }
  .l-meta { color: var(--muted); }
  .empty-state { color: var(--muted); font-size: 13px; padding: 40px 0; text-align: center; }
</style>
</head>
<body>
  <div id="graph-pane">
    <h1>Commit graph</h1>
    <div id="commit-list"></div>
  </div>
  <div id="diff-pane">
    <div class="empty-state">Select a commit to see its diff.</div>
  </div>
<script>
const DATA = __DATA_JSON__;

function fmtDate(ts, tz) {
  const sign = tz[0] === '+' ? 1 : -1;
  const off = sign * (parseInt(tz.slice(1,3))*3600 + parseInt(tz.slice(3,5))*60);
  const d = new Date((ts + off) * 1000);
  return d.toUTCString().replace(' GMT', '') + ' ' + tz;
}

function branchesAt(sha) {
  return Object.entries(DATA.branches).filter(([_, s]) => s === sha).map(([b]) => b);
}

function renderList() {
  const list = document.getElementById('commit-list');
  list.innerHTML = '';
  DATA.commits.forEach(c => {
    const row = document.createElement('div');
    row.className = 'commit-row';
    row.dataset.sha = c.sha;
    const branches = branchesAt(c.sha);
    const isHead = c.sha === DATA.head;
    row.innerHTML = `
      <div class="graph-col"><div class="dot"></div></div>
      <div class="commit-info">
        <div class="commit-msg">${escapeHtml(c.message.split('\n')[0] || '(no message)')}</div>
        <div class="commit-meta">
          <span class="sha-chip">${c.sha.slice(0,8)}</span>
          ${branches.map(b => `<span class="branch-chip">${escapeHtml(b)}${isHead && b===DATA.headBranch ? ' (HEAD)' : ''}</span>`).join('')}
          ${c.author} · ${fmtDate(c.time, c.tz)}
        </div>
      </div>`;
    row.addEventListener('click', () => selectCommit(c.sha));
    list.appendChild(row);
  });
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function renderDiff(text) {
  return text.split('\n').map(line => {
    let cls = '';
    if (line.startsWith('+++') || line.startsWith('---')) cls = 'l-meta';
    else if (line.startsWith('@@')) cls = 'l-hunk';
    else if (line.startsWith('+')) cls = 'l-add';
    else if (line.startsWith('-')) cls = 'l-del';
    else if (line.startsWith('Binary files')) cls = 'l-meta';
    return `<span class="${cls}">${escapeHtml(line)}</span>`;
  }).join('\n');
}

function selectCommit(sha) {
  document.querySelectorAll('.commit-row').forEach(r => {
    r.classList.toggle('selected', r.dataset.sha === sha);
  });
  const commit = DATA.commits.find(c => c.sha === sha);
  const pane = document.getElementById('diff-pane');
  const diffText = DATA.diffs[sha] || '(no file changes)';
  pane.innerHTML = `
    <div id="diff-header">
      <strong>${escapeHtml(commit.message)}</strong><br>
      commit <span class="sha-chip">${sha}</span>
      ${commit.parents.length ? 'parent(s): ' + commit.parents.map(p => p.slice(0,8)).join(', ') : '(root commit)'}
    </div>
    <pre class="diff">${renderDiff(diffText)}</pre>`;
}

renderList();
if (DATA.commits.length) selectCommit(DATA.head || DATA.commits[0].sha);
else document.getElementById('graph-pane').innerHTML += '<div class="empty-state">No commits yet.</div>';
</script>
</body>
</html>
"""
