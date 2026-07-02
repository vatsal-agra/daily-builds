"""Static single-file HTML commit-graph + diff visualizer."""
import html
import json
import os

from . import diffalgo, objecthash, treeops


def _all_commits(repo):
    """BFS every commit reachable from any branch ref. Returns dict sha->info."""
    seen = {}
    stack = []
    for branch in repo.list_branches():
        sha = repo.read_ref(f"refs/heads/{branch}")
        if sha:
            stack.append(sha)
    head_sha = repo.resolve_head()
    if head_sha:
        stack.append(head_sha)
    while stack:
        sha = stack.pop()
        if sha in seen:
            continue
        _, content = repo.read_object_any(sha)
        info = objecthash.decode_commit(content)
        seen[sha] = info
        stack.extend(info["parents"])
    return seen


def _topo_order(commits):
    """Return shas ordered newest-first with a lane-free generation number
    (longest path to a root), used purely for vertical layout.
    """
    gen = {}

    def compute(sha):
        if sha in gen:
            return gen[sha]
        parents = commits[sha]["parents"]
        gen[sha] = 0 if not parents else 1 + max(
            compute(p) for p in parents if p in commits
        )
        return gen[sha]

    for sha in commits:
        compute(sha)
    return sorted(commits, key=lambda s: -gen[s]), gen


def _commit_diff_lines(repo, sha, info):
    tree_sha = info["tree"]
    new_paths = treeops.flatten_tree(repo, tree_sha)
    parents = info["parents"]
    old_paths = (
        treeops.flatten_tree(repo, treeops.tree_of_commit(repo, parents[0]))
        if parents
        else {}
    )
    out = []
    for path in sorted(set(old_paths) | set(new_paths)):
        old = old_paths.get(path)
        new = new_paths.get(path)
        if old == new:
            continue

        def lines_of(entry):
            if entry is None:
                return []
            _, content = repo.read_object_any(entry[1])
            text = content.decode("utf-8", errors="replace")
            return text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")

        out += diffalgo.unified_diff(
            lines_of(old), lines_of(new),
            f"a/{path}" if old else "/dev/null",
            f"b/{path}" if new else "/dev/null",
        )
    return out


def render(repo, output_path):
    commits = _all_commits(repo)
    order, gen = _topo_order(commits)
    branch_tips = {
        repo.read_ref(f"refs/heads/{b}"): b for b in repo.list_branches()
    }

    nodes = []
    for sha in order:
        info = commits[sha]
        nodes.append({
            "sha": sha,
            "short": sha[:10],
            "parents": [p for p in info["parents"] if p in commits],
            "gen": gen[sha],
            "message": info["message"].strip().split("\n")[0],
            "author": info["author"],
            "branch": branch_tips.get(sha),
            "diff": "\n".join(_commit_diff_lines(repo, sha, info)),
        })

    data_json = json.dumps(nodes)
    title = html.escape(os.path.basename(repo.worktree))
    doc = _TEMPLATE.replace("__TITLE__", title).replace("__DATA__", data_json)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return output_path


_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Graft: __TITLE__</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; font: 14px/1.5 -apple-system,Segoe UI,sans-serif; background:#0f1115; color:#d8dee9; display:flex; height:100vh; }
  #graph { width:340px; overflow-y:auto; border-right:1px solid #2a2e37; padding:8px; box-sizing:border-box; }
  #detail { flex:1; overflow-y:auto; padding:16px; }
  .node { display:flex; gap:8px; align-items:flex-start; padding:6px 8px; border-radius:6px; cursor:pointer; }
  .node:hover, .node.active { background:#1b1f27; }
  .dot { width:10px; height:10px; border-radius:50%; background:#5eb1ff; margin-top:5px; flex:none; }
  .sha { color:#7d8a9c; font-family:monospace; font-size:12px; }
  .msg { font-weight:600; }
  .branch-tag { display:inline-block; background:#274b2e; color:#8fe39a; border-radius:4px; padding:0 6px; font-size:11px; margin-left:6px; }
  pre { background:#161920; border-radius:8px; padding:12px; overflow-x:auto; font-size:13px; }
  .add { color:#8fe39a; } .del { color:#ff8080; } .hdr { color:#5eb1ff; } .meta { color:#7d8a9c; }
  h2 { margin-top:0; }
</style></head>
<body>
<div id="graph"></div>
<div id="detail"><p class="meta">Select a commit to view its diff.</p></div>
<script>
const commits = __DATA__;
const bySha = Object.fromEntries(commits.map(c => [c.sha, c]));
const graphEl = document.getElementById('graph');
const detailEl = document.getElementById('detail');

function renderGraph() {
  graphEl.innerHTML = '';
  for (const c of commits) {
    const div = document.createElement('div');
    div.className = 'node';
    div.dataset.sha = c.sha;
    div.innerHTML = `<div class="dot"></div><div>
      <div class="msg">${escapeHtml(c.message)}${c.branch ? `<span class="branch-tag">${escapeHtml(c.branch)}</span>` : ''}</div>
      <div class="sha">${c.short}</div></div>`;
    div.onclick = () => selectCommit(c.sha);
    graphEl.appendChild(div);
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[ch]));
}

function diffHtml(diffText) {
  if (!diffText) return '<p class="meta">(no changes; root commit or empty diff)</p>';
  return '<pre>' + diffText.split('\\n').map(line => {
    let cls = '';
    if (line.startsWith('+++') || line.startsWith('---')) cls = 'hdr';
    else if (line.startsWith('@@')) cls = 'hdr';
    else if (line.startsWith('+')) cls = 'add';
    else if (line.startsWith('-')) cls = 'del';
    return `<span class="${cls}">${escapeHtml(line)}</span>`;
  }).join('\\n') + '</pre>';
}

function selectCommit(sha) {
  const c = bySha[sha];
  for (const el of graphEl.querySelectorAll('.node')) {
    el.classList.toggle('active', el.dataset.sha === sha);
  }
  detailEl.innerHTML = `<h2>${escapeHtml(c.message)}</h2>
    <p class="meta">commit ${c.sha}<br>${escapeHtml(c.author)}</p>
    ${diffHtml(c.diff)}`;
}

renderGraph();
if (commits.length) selectCommit(commits[0].sha);
</script>
</body></html>
"""
