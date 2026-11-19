package render

import (
	"fmt"
	"html"
	"path/filepath"
	"strings"

	"tier/dot"
	"tier/layout"
)

type variant struct {
	name, desc string
	mod        func(o *layout.Options)
}

var variants = []variant{
	{"Tier (full pipeline)", "network simplex · median sweeps + transpose · Brandes–Köpf", func(o *layout.Options) {}},
	{"Longest-path layering", "same, but layers by longest path instead of network simplex", func(o *layout.Options) { o.Ranker = "longest" }},
	{"No crossing minimisation", "keeps the initial DFS order", func(o *layout.Options) { o.Order = "none" }},
	{"Packed coordinates", "ignores edges when assigning x (no Brandes–Köpf)", func(o *layout.Options) { o.Coord = "packed" }},
	{"DFS cycle removal", "back-edge reversal instead of the greedy FAS heuristic", func(o *layout.Options) { o.Acyclic = "dfs" }},
}

// Report renders a self-contained HTML page showing the same graph laid out
// with the full pipeline and with each stage degraded, plus a metrics table.
func Report(dg *dot.Graph, lg layout.Graph, base layout.Options, title string) (string, error) {
	var cards, rows strings.Builder
	var baseline *layout.Metrics
	for i, v := range variants {
		o := base
		v.mod(&o)
		res, err := layout.Layout(lg, o)
		if err != nil {
			return "", err
		}
		m := res.Metrics
		if i == 0 {
			baseline = &m
		}
		svg := SVG(res, render0(dg, i))
		note := v.desc
		if i > 0 && sameMetrics(m, *baseline) {
			note += " — identical to the full pipeline on this graph"
		}
		fmt.Fprintf(&cards, `<section class="card%s"><header><h2>%s</h2><p>%s</p></header><div class="view">%s</div></section>`+"\n",
			map[bool]string{true: " main", false: ""}[i == 0], html.EscapeString(v.name), html.EscapeString(note), svg)
		fmt.Fprintf(&rows, "<tr><th scope=row>%s</th><td>%d</td><td>%.0f</td><td>%d</td><td>%d</td><td>%d</td><td>%.0f × %.0f</td></tr>\n",
			html.EscapeString(v.name), m.Crossings, m.EdgeLength, m.Bends, m.Dummies, m.Reversed, m.Width, m.Height)
	}
	return fmt.Sprintf(reportTmpl, html.EscapeString(filepath.Base(title)), len(lg.Nodes), len(lg.Edges), rows.String(), cards.String(), SVGStyle), nil
}

func render0(dg *dot.Graph, i int) Options {
	return Options{Directed: dg.Directed, Bands: true, Inline: true, IDPrefix: fmt.Sprintf("v%d", i)}
}

const reportTmpl = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tier layout report</title>
<style>
:root{--bg:#f4f1ea;--panel:#fffdf8;--ink:#1d2330;--mute:#666d80;--line:#e2dccf;--accent:#2563eb}
@media (prefers-color-scheme:dark){:root{--bg:#10131a;--panel:#171b24;--ink:#e8ecf4;--mute:#8d96ab;--line:#272d3b;--accent:#6aa3ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1200px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:28px;margin:0 0 4px;letter-spacing:-.02em}h1 span{color:var(--accent)}
.sub{color:var(--mute);margin:0 0 24px}
table{border-collapse:collapse;width:100%%;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden;margin-bottom:28px;font-variant-numeric:tabular-nums}
th,td{padding:9px 12px;text-align:right;border-bottom:1px solid var(--line)}th[scope=row],thead th:first-child{text-align:left}
thead th{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);font-weight:600}
tbody tr:first-child{font-weight:600}tbody tr:last-child th,tbody tr:last-child td{border-bottom:0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%%,520px),1fr));gap:18px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden;display:flex;flex-direction:column}
.card.main{grid-column:1/-1;border-color:var(--accent)}
.card header{padding:12px 16px 4px}.card h2{font-size:16px;margin:0}.card p{margin:2px 0 8px;color:var(--mute);font-size:13px}
.view{overflow:auto;max-height:640px;padding:0 8px 8px}.view svg{display:block;margin:0 auto;max-width:100%%;height:auto}
.table-wrap{overflow-x:auto}
</style></head><body><main>
<h1>Tier <span>layout report</span></h1>
<p class="sub">%s · %d nodes · %d edges. Hover a node to highlight its edges. Dashed orange edges were reversed to break cycles.</p>
<div class="table-wrap"><table><thead><tr><th>Strategy</th><th>Crossings</th><th>Edge length</th><th>Bends</th><th>Dummies</th><th>Reversed</th><th>Size</th></tr></thead><tbody>
%s</tbody></table></div>
<div class="grid">
%s</div>
<style>%s</style>
<script>
document.querySelectorAll('svg.tier').forEach(function(svg){
  svg.querySelectorAll('.n').forEach(function(n){
    var id=n.getAttribute('data-id');
    n.addEventListener('mouseenter',function(){
      svg.querySelectorAll('.e').forEach(function(e){
        if(e.getAttribute('data-from')===id||e.getAttribute('data-to')===id){e.classList.add('hl');
          svg.querySelectorAll('.n').forEach(function(m){var k=m.getAttribute('data-id');if(k===e.getAttribute('data-from')||k===e.getAttribute('data-to'))m.classList.add('hl');});}
      });
    });
    n.addEventListener('mouseleave',function(){svg.querySelectorAll('.hl').forEach(function(x){x.classList.remove('hl');});});
  });
});
</script>
</main></body></html>
`

func sameMetrics(a, b layout.Metrics) bool {
	return a.Crossings == b.Crossings && a.EdgeLength == b.EdgeLength && a.Bends == b.Bends &&
		a.Width == b.Width && a.Height == b.Height && a.Reversed == b.Reversed
}
