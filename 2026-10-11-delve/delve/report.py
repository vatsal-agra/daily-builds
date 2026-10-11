"""Text and HTML reports for an Explorer run."""
import html
from . import terms as tm


def sv(v, w):
    return tm.to_signed(v, w)


def fmt_inputs(inputs, names, w):
    if not names: return "(no inputs)"
    return ", ".join("%s=%d" % (n, sv(inputs.get(n, 0), w)) for n in names)


def fmt_pc(pc, limit=6):
    parts = [tm.show(c, 8) for c in pc if c is not tm.TRUE]
    if not parts: return "true"
    s = " ∧ ".join(parts[:limit])
    return s + (" ∧ … (+%d)" % (len(parts) - limit) if len(parts) > limit else "")


def source_lines(ex):
    return ex.prog.source.split("\n")


def text_report(ex, name="program", show_paths=True):
    w = ex.w
    out = []
    A = out.append
    A("Delve analysis of %s   (width=%d bits, loop bound=%d)" % (name, w, ex.loop_bound))
    A("=" * 72)
    feasible = [p for p in ex.paths if p.status != "error"]
    errors = [p for p in ex.paths if p.status == "error"]
    A("paths explored: %d complete, %d ending in a trap, %d pruned infeasible, %d cut by loop/call bound"
      % (len(feasible), len(errors), ex.pruned, ex.truncated))
    if ex.hit_limit: A("!! exploration stopped early: " + ex.hit_limit)
    cov = ex.coverage()
    A("coverage: %d/%d lines, %d/%d branch outcomes" % (len(cov["lines"]), len(cov["all_lines"]),
                                                       len(cov["branches"]), len(cov["all_branches"])))
    A("solver: %d queries (%d cached, %d SAT calls), %d conflicts" % (
        ex.stats["queries"], ex.stats["cache_hits"], ex.stats["sat_calls"], ex.stats.get("conflicts", 0)))
    A("")
    src = source_lines(ex)
    if ex.bugs:
        A("BUGS FOUND: %d" % len(ex.bugs))
        for (kind, line), b in sorted(ex.bugs.items(), key=lambda kv: kv[0][1]):
            mark = {True: "replay-confirmed", False: "NOT CONFIRMED (solver/interpreter disagree!)", None: "unverified"}[b.confirmed]
            A("  [%s] line %d: %s" % (kind, line, src[line - 1].strip() if 0 < line <= len(src) else ""))
            A("      triggered by: %s   (%s; reached on %d path%s)" % (fmt_inputs(b.inputs, b.in_names, w), mark, b.hits, "" if b.hits == 1 else "s"))
    else:
        bounded = " (up to the loop bound)" if ex.truncated or any(True for _ in ex.all_branches) else ""
        A("No bugs found%s." % ("" if ex.hit_limit else bounded))
        if ex.truncated:
            A("  note: %d path(s) were cut off at the loop/call bound, so absence of bugs is only proven within it." % ex.truncated)
    A("")
    if show_paths:
        A("GENERATED TESTS (one per feasible path):")
        for p in ex.paths:
            if p.status == "error":
                res = "TRAP: %s @ line %d" % p.trap
            else:
                rv = "return %d" % p.expected_ret if p.expected_ret is not None else (
                    "return %d" % sv(tm.evaluate(p.ret, p.model), w) if p.ret is not None else "finish")
                outs = ""
                if p.outputs: outs = "  prints %s" % [sv(tm.evaluate(o, p.model), w) for o in p.outputs]
                res = rv + outs
            ver = {True: "✓", False: "✗", None: "?"}[p.verified]
            A("  #%-3d %s %-28s -> %s" % (p.id, ver, fmt_inputs(p.inputs, p.in_names, w), res))
            A("        path condition: " + fmt_pc(p.pc))
    return "\n".join(out)


CSS = """
:root{--bg:#0f1318;--panel:#171d25;--ink:#e6edf3;--mut:#8b98a8;--line:#27303b;--acc:#7cc4ff;--ok:#5ad08a;--bad:#ff6b6b;--warn:#f2c14e}
@media (prefers-color-scheme: light){:root{--bg:#f5f7fa;--panel:#fff;--ink:#16202b;--mut:#5d6b7a;--line:#dde3ea;--acc:#1b6fd1;--ok:#13824b;--bad:#c92a2a;--warn:#a86a00}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1080px;margin:0 auto;padding:28px 16px 60px}h1{font-size:26px;margin:0 0 4px;letter-spacing:-.02em}
h1 span{color:var(--acc)}h2{font-size:15px;text-transform:uppercase;letter-spacing:.08em;color:var(--mut);margin:34px 0 10px}
.sub{color:var(--mut);margin:0 0 22px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}.card b{display:block;font-size:24px}
.card small{color:var(--mut)}code,pre,td.m{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px}
pre{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 0;overflow:auto;margin:0}
.ln{display:flex;padding:0 14px}.ln i{color:var(--mut);width:34px;flex:none;font-style:normal;user-select:none}.ln span{white-space:pre}
.ln.cov{background:color-mix(in srgb,var(--ok) 13%,transparent)}.ln.unc{background:color-mix(in srgb,var(--warn) 14%,transparent)}
.ln.bug{background:color-mix(in srgb,var(--bad) 20%,transparent);border-left:3px solid var(--bad);padding-left:11px}
.bug{background:var(--panel);border:1px solid var(--line);border-left:4px solid var(--bad);border-radius:10px;padding:12px 14px;margin:10px 0}
.bug h3{margin:0 0 4px;font-size:16px}.tag{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;border:1px solid var(--line);color:var(--mut)}
.tag.ok{color:var(--ok);border-color:var(--ok)}.tag.err{color:var(--bad);border-color:var(--bad)}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mut);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}
tr:last-child td{border-bottom:0}.scroll{overflow-x:auto}.clean{color:var(--ok);font-weight:600}
"""


def html_report(ex, name="program"):
    w = ex.w
    E = html.escape
    cov = ex.coverage()
    src = source_lines(ex)
    bug_lines = {l for (_, l) in ex.bugs}
    feasible = [p for p in ex.paths if p.status != "error"]
    errors = [p for p in ex.paths if p.status == "error"]
    h = ["<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>",
         "<title>Delve report — %s</title><style>%s</style><main>" % (E(name), CSS),
         "<h1><span>Delve</span> report · %s</h1>" % E(name),
         "<p class=sub>Symbolic execution at %d-bit signed integers, loop bound %d.</p>" % (w, ex.loop_bound),
         "<div class=cards>"]
    for big, small in ((len(feasible), "feasible paths"), (len(errors), "trapping paths"), (len(ex.bugs), "distinct bugs"),
                       ("%d/%d" % (len(cov["lines"]), len(cov["all_lines"])), "lines covered"),
                       ("%d/%d" % (len(cov["branches"]), len(cov["all_branches"])), "branch outcomes"),
                       (ex.stats["sat_calls"], "SAT calls")):
        h.append("<div class=card><b>%s</b><small>%s</small></div>" % (big, small))
    h.append("</div>")
    if ex.hit_limit: h.append("<p class=sub>⚠ exploration stopped early: %s</p>" % E(ex.hit_limit))
    h.append("<h2>Bugs</h2>")
    if not ex.bugs:
        h.append("<p class=clean>No bugs found%s.</p>" % (" within the loop bound" if ex.truncated else ""))
    for (kind, line), b in sorted(ex.bugs.items(), key=lambda kv: kv[0][1]):
        tag = "<span class='tag ok'>replay-confirmed</span>" if b.confirmed else "<span class='tag err'>unconfirmed</span>"
        h.append("<div class=bug><h3>%s · line %d %s</h3><code>%s</code><br><small>trigger: <code>%s</code></small></div>" % (
            E(kind), line, tag, E(src[line - 1].strip()), E(fmt_inputs(b.inputs, b.in_names, w))))
    h.append("<h2>Source coverage</h2><pre>")
    for i, t in enumerate(src, 1):
        cls = "bug" if i in bug_lines else "cov" if i in cov["lines"] else "unc" if i in cov["all_lines"] else ""
        h.append("<div class='ln %s'><i>%d</i><span>%s</span></div>" % (cls, i, E(t)))
    h.append("</pre><h2>Paths and generated tests</h2><div class=scroll><table><tr><th>#<th>inputs<th>outcome<th>path condition")
    for p in ex.paths:
        if p.status == "error":
            res = "<span class='tag err'>%s @ %d</span>" % (E(p.trap[0]), p.trap[1])
        else:
            rv = p.expected_ret if p.expected_ret is not None else (sv(tm.evaluate(p.ret, p.model), w) if p.ret is not None else None)
            res = "<span class='tag ok'>%s</span>" % ("return %d" % rv if rv is not None else "finish")
        h.append("<tr><td>%d<td class=m>%s<td>%s<td class=m>%s" % (p.id, E(fmt_inputs(p.inputs, p.in_names, w)), res, E(fmt_pc(p.pc, 4))))
    h.append("</table></div></main></html>")
    return "\n".join(h)
