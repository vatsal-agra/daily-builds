"""Builds an interactive, self-contained HTML visualization of a query's
SLD-resolution search tree: which clauses were tried for each goal, which
succeeded, failed, or were pruned by cut, and what a goal's bindings were
at each success.

This runs its own compact tracing evaluator below rather than threading
instrumentation through engine.py's already-reviewed solve() hot path
(engine.py stays exactly as adversarially reviewed in REVIEW.md). To make
sure the *picture* this produces is what the real engine actually does --
not just something plausible-looking -- tests/test_viz.py differentially
checks that this tracer finds exactly the same solutions, in the same
order, as horn.engine.solve_top for every example query used here.
"""

import html as html_lib

from .engine import CutBarrier
from .errors import HornError
from .terms import Atom, Compound, deref, format_term, rename
from .unify import undo_to, unify

DEFAULT_MAX_SOLUTIONS = 5
DEFAULT_MAX_NODES = 12000


class VNode:
    __slots__ = ("kind", "label", "status", "children")

    def __init__(self, kind, label):
        self.kind = kind  # 'goal' | 'clause' | 'cut' | 'neg' | 'true' | 'builtin'
        self.label = label
        self.status = "pending"  # 'pending' | 'success' | 'fail'
        self.children = []

    def add(self, node):
        self.children.append(node)
        return node


class Budget:
    def __init__(self, max_solutions, max_nodes):
        self.max_solutions = max_solutions
        self.max_nodes = max_nodes
        self.solutions = 0
        self.nodes = 0
        self.truncated = False

    def stop(self):
        return self.truncated or self.solutions >= self.max_solutions

    def new_node(self):
        self.nodes += 1
        if self.nodes >= self.max_nodes:
            self.truncated = True


def _flatten_conj(term):
    goals = []

    def rec(t):
        if isinstance(t, Compound) and t.functor == "," and t.arity == 2:
            rec(t.args[0])
            rec(t.args[1])
        else:
            goals.append(t)

    rec(term)
    return goals


def _twalk(term, ctx, barrier, budget, node):
    """Mirrors horn.engine.solve()'s control flow -- same cut-barrier
    protocol, same negation-as-failure -- but builds a VNode tree as a side
    effect. Yields once per success, exactly like solve()."""
    if budget.stop():
        return
    term = deref(term)
    if isinstance(term, Atom) and term.name == "!":
        cut_node = node.add(VNode("cut", "!"))
        budget.new_node()
        cut_node.status = "success"
        yield True
        barrier.cut = True
        return
    if isinstance(term, Compound) and term.functor == "," and term.arity == 2:
        yield from _twalk_conj(_flatten_conj(term), 0, barrier, ctx, budget, node)
        return
    if isinstance(term, Compound) and term.functor == "\\+" and term.arity == 1:
        yield from _twalk_negation(term.args[0], ctx, budget, node)
        return
    if isinstance(term, Atom) and term.name == "true":
        node.status = "success"
        yield True
        return
    yield from _twalk_call(term, ctx, budget, node)


def _twalk_conj(goals, idx, barrier, ctx, budget, node):
    if idx == len(goals):
        yield True
        return
    if budget.stop():
        return
    goal = goals[idx]
    gnode = node.add(VNode("goal", format_term(goal)))
    budget.new_node()
    any_success = False
    for _ in _twalk(goal, ctx, barrier, budget, gnode):
        any_success = True
        gnode.status = "success"
        yield from _twalk_conj(goals, idx + 1, barrier, ctx, budget, node)
        if barrier.cut or budget.stop():
            return
    if not any_success:
        gnode.status = "fail"


def _twalk_negation(goal, ctx, budget, node):
    neg_node = node.add(VNode("neg", f"\\+ {format_term(goal)}"))
    budget.new_node()
    trail = ctx.trail
    mark = len(trail)
    found = False
    for _ in _twalk(goal, ctx, CutBarrier(), budget, neg_node):
        found = True
        break
    undo_to(trail, mark)
    if found:
        neg_node.status = "fail"
    else:
        neg_node.status = "success"
        yield True


def _twalk_call(term, ctx, budget, node):
    if isinstance(term, Atom):
        functor, args = term.name, ()
    elif isinstance(term, Compound):
        functor, args = term.functor, term.args
    else:
        raise HornError(f"type_error: {term!r} is not callable")

    key = (functor, len(args))
    builtin = ctx.builtins.get(key)
    if builtin is not None:
        got = False
        for _ in builtin(args, ctx):
            got = True
            node.status = "success"
            yield True
        if not got:
            node.status = "fail"
        return

    clauses = ctx.db.get(key)
    if clauses is None:
        raise HornError(f"existence_error: unknown procedure {functor}/{len(args)}")

    trail = ctx.trail
    any_success = False
    for idx, (head_t, body_t) in enumerate(clauses):
        if budget.stop():
            break
        mark = len(trail)
        mapping = {}
        head2 = rename(head_t, mapping)
        head_args = head2.args if isinstance(head2, Compound) else ()
        ok = True
        for a, b in zip(args, head_args):
            if not unify(a, b, trail, ctx.occurs_check):
                ok = False
                break
        cnode = node.add(VNode("clause", f"[clause {idx + 1}] {format_term(head2)}"))
        budget.new_node()
        if not ok:
            cnode.status = "fail"
            undo_to(trail, mark)
            continue
        cut_here = False
        if body_t is None:
            cnode.status = "success"
            any_success = True
            yield True
        else:
            body2 = rename(body_t, mapping)
            barrier = CutBarrier()
            got = False
            for _ in _twalk(body2, ctx, barrier, budget, cnode):
                got = True
                any_success = True
                cnode.status = "success"
                yield True
            if not got:
                cnode.status = "fail"
            cut_here = barrier.cut
        undo_to(trail, mark)
        if cut_here:
            return
    if not any_success:
        node.status = "fail"


def build_trace(engine, goal, max_solutions=DEFAULT_MAX_SOLUTIONS, max_nodes=DEFAULT_MAX_NODES):
    """Run the query, building a VNode tree and collecting up to
    max_solutions solution snapshots (rendered bindings for the goal's
    named variables). Returns (root_node, solutions, truncated)."""
    from .repl import query_vars, format_solution

    vars_ = query_vars(goal)
    budget = Budget(max_solutions, max_nodes)
    root = VNode("goal", format_term(goal))
    solutions = []
    mark = len(engine.trail)
    try:
        for _ in _twalk(goal, engine, CutBarrier(), budget, root):
            solutions.append(format_solution(vars_))
            budget.solutions += 1  # must happen before the next budget.stop()
            # check below, or the cap never actually engages and every
            # exploration keeps going until the (much larger) node cap does
            # -- caught by this module's own differential test against the
            # real engine finding more solutions than were asked for.
            if budget.stop():
                break
    finally:
        # Stopping early abandons the _twalk generator before it reaches
        # its own post-yield undo_to() calls -- same class of leak as
        # REVIEW.md finding #6, just local to this module instead of the
        # CLI/REPL boundary. Solutions are already captured as rendered
        # strings above, so unwinding here doesn't lose anything.
        undo_to(engine.trail, mark)
    root.status = "success" if solutions else "fail"
    return root, solutions, budget.truncated


_ICON = {"success": "✓", "fail": "✗", "pending": "…"}


def _node_to_dict(node):
    return {
        "kind": node.kind,
        "label": node.label,
        "status": node.status,
        "children": [_node_to_dict(c) for c in node.children],
    }


def render_trace_html(engine, goal, max_solutions=DEFAULT_MAX_SOLUTIONS, max_nodes=DEFAULT_MAX_NODES, title=None):
    import json

    # Captured *before* build_trace runs: exploration leaves the query's
    # own variables bound to whichever branch was last visited when the
    # search stopped (an abandoned solve() generator doesn't run its own
    # post-yield undo -- see the matching trail-leak note in REVIEW.md and
    # the fix applied to build_trace below). Formatting the goal after the
    # fact would print e.g. "ancestor(tom, jim)" -- the last solution
    # found -- as if it had been the literal query, instead of the actual
    # query "ancestor(tom, _X)".
    goal_text = format_term(goal)
    root, solutions, truncated = build_trace(engine, goal, max_solutions, max_nodes)
    data = _node_to_dict(root)
    page_title = title or f"Horn SLD trace: {goal_text}"
    solutions_html = "".join(
        f"<li><code>{html_lib.escape(s)}</code></li>" for s in solutions
    ) or "<li><em>no solutions</em></li>"
    truncated_note = (
        f'<p class="truncated">Search truncated at {max_nodes} nodes / {max_solutions} solutions '
        "-- the tree below is a prefix of the full search, not the whole thing.</p>"
        if truncated
        else ""
    )
    return _TEMPLATE.format(
        title=html_lib.escape(page_title),
        goal=html_lib.escape(goal_text),
        data=json.dumps(data),
        solutions_html=solutions_html,
        truncated_note=truncated_note,
        n_solutions=len(solutions),
    )


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    --bg: #ffffff; --fg: #1a1a2e; --muted: #6b7280; --border: #e2e2ea;
    --success: #1f9d55; --fail: #d64545; --pending: #b08900;
    --node-bg: #f6f6fb; --accent: #4c5fd5;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #14141f; --fg: #eceef7; --muted: #9294a8; --border: #33334a;
      --success: #4ad07f; --fail: #ff6b6b; --pending: #e0b400;
      --node-bg: #1d1d2e; --accent: #8b9bff;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--fg); margin: 0; padding: 2rem;
    font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
    font-size: 14px; line-height: 1.5;
  }}
  h1 {{ font-size: 1.1rem; font-weight: 600; margin: 0 0 0.25rem; }}
  .goal {{ color: var(--accent); }}
  .subtitle {{ color: var(--muted); margin: 0 0 1.5rem; font-size: 0.9rem; }}
  .panel {{
    background: var(--node-bg); border: 1px solid var(--border); border-radius: 8px;
    padding: 1rem 1.25rem; margin-bottom: 1.25rem;
  }}
  .panel h2 {{ font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--muted); margin: 0 0 0.6rem; }}
  ul.solutions {{ margin: 0; padding-left: 1.2rem; }}
  ul.solutions li {{ margin: 0.15rem 0; }}
  .truncated {{ color: var(--pending); font-size: 0.85rem; }}
  #tree {{ list-style: none; padding-left: 0; margin: 0; }}
  #tree ul {{ list-style: none; padding-left: 1.3rem; margin: 0.15rem 0 0.15rem 0.5rem;
    border-left: 1px dashed var(--border); }}
  .node {{ padding: 0.1rem 0; }}
  .row {{ display: inline-flex; align-items: baseline; gap: 0.4rem; cursor: pointer; }}
  .row:hover .lbl {{ text-decoration: underline; }}
  .toggle {{ display: inline-block; width: 1rem; color: var(--muted); user-select: none; }}
  .icon {{ font-weight: 700; width: 1rem; display: inline-block; text-align: center; }}
  .icon.success {{ color: var(--success); }}
  .icon.fail {{ color: var(--fail); }}
  .icon.pending {{ color: var(--pending); }}
  .kind {{ color: var(--muted); font-size: 0.78rem; }}
  .collapsed > ul {{ display: none; }}
  .controls {{ margin-bottom: 1rem; }}
  button {{
    font: inherit; background: var(--node-bg); color: var(--fg); border: 1px solid var(--border);
    border-radius: 6px; padding: 0.35rem 0.75rem; cursor: pointer; margin-right: 0.5rem;
  }}
  button:hover {{ border-color: var(--accent); }}
</style>
</head>
<body>
  <h1>SLD resolution trace: <span class="goal">{goal}</span></h1>
  <p class="subtitle">Click a node to expand/collapse. Green = succeeded, red = failed, amber = clause matched but body still had unfinished work when the search stopped.</p>

  <div class="panel">
    <h2>Solutions found ({n_solutions})</h2>
    <ul class="solutions">{solutions_html}</ul>
    {truncated_note}
  </div>

  <div class="controls">
    <button id="expandAll">Expand all</button>
    <button id="collapseAll">Collapse all</button>
  </div>

  <ul id="tree"></ul>

<script>
const DATA = {data};

function iconFor(status) {{
  if (status === 'success') return '\\u2713';
  if (status === 'fail') return '\\u2717';
  return '\\u2026';
}}

function buildNode(node) {{
  const li = document.createElement('li');
  li.className = 'node';
  const hasChildren = node.children && node.children.length > 0;
  if (hasChildren && node.status === 'fail') li.classList.add('collapsed');

  const row = document.createElement('div');
  row.className = 'row';

  const toggle = document.createElement('span');
  toggle.className = 'toggle';
  toggle.textContent = hasChildren ? '\\u25b8' : '\\u00b7';
  row.appendChild(toggle);

  const icon = document.createElement('span');
  icon.className = 'icon ' + node.status;
  icon.textContent = iconFor(node.status);
  row.appendChild(icon);

  const lbl = document.createElement('span');
  lbl.className = 'lbl';
  lbl.textContent = node.label;
  row.appendChild(lbl);

  const kind = document.createElement('span');
  kind.className = 'kind';
  kind.textContent = '(' + node.kind + ')';
  row.appendChild(kind);

  li.appendChild(row);

  if (hasChildren) {{
    const ul = document.createElement('ul');
    for (const child of node.children) ul.appendChild(buildNode(child));
    li.appendChild(ul);
    row.addEventListener('click', () => li.classList.toggle('collapsed'));
  }}
  return li;
}}

const treeRoot = document.getElementById('tree');
treeRoot.appendChild(buildNode(DATA));

document.getElementById('expandAll').addEventListener('click', () => {{
  document.querySelectorAll('#tree .node').forEach(n => n.classList.remove('collapsed'));
}});
document.getElementById('collapseAll').addEventListener('click', () => {{
  document.querySelectorAll('#tree .node').forEach(n => {{
    if (n.querySelector('ul')) n.classList.add('collapsed');
  }});
}});
</script>
</body>
</html>
"""
