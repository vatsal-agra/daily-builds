package main

import (
	"fmt"
	"html"
	"strings"

	"keyhole/tls13"
)

// renderTimeline produces a self-contained HTML page (no external assets) for captured sessions.
func renderTimeline(sessions [][]tls13.InspectEvent) string {
	var b strings.Builder
	b.WriteString(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Keyhole session timeline</title><style>
:root{--bg:#f6f4ef;--fg:#1c1b19;--mut:#6b675e;--card:#fffdf8;--line:#e2ddd0;--c:#0b6e8a;--s:#9b3d78;--d:#2f7d4f;--a:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#14130f;--fg:#ece8dc;--mut:#9a9585;--card:#1d1b16;--line:#33302a;--c:#5cc3de;--s:#e48bc2;--d:#7fd19b;--a:#ff8a80}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 ui-sans-serif,system-ui,sans-serif}
main{max-width:980px;margin:0 auto;padding:28px 16px 60px}h1{font-size:22px;margin:0 0 4px}.sub{color:var(--mut);margin:0 0 24px}
.sess{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:0 0 22px;overflow:hidden}
.sess h2{font-size:14px;margin:0;padding:12px 16px;border-bottom:1px solid var(--line);color:var(--mut);font-weight:600;letter-spacing:.04em;text-transform:uppercase}
.row{display:grid;grid-template-columns:54px 1fr;gap:10px;padding:8px 16px;border-bottom:1px solid var(--line)}.row:last-child{border:0}
.dir{font:600 12px ui-monospace,monospace;padding-top:3px}.C{color:var(--c)}.S{color:var(--s)}
.sum{font-weight:600}.kind-data .sum{color:var(--d)}.kind-alert .sum{color:var(--a)}.kind-note .sum{color:var(--a);font-weight:500}
.det{font:12.5px/1.45 ui-monospace,monospace;color:var(--mut);white-space:pre-wrap;word-break:break-word}
@media(max-width:560px){.row{grid-template-columns:1fr;gap:0}}
</style></head><body><main><h1>Keyhole session timeline</h1><p class="sub">Decoded from the wire with an NSS key log — nothing here required a man-in-the-middle certificate.</p>`)
	if len(sessions) == 0 {
		b.WriteString(`<p>No sessions were captured.</p>`)
	}
	for i, evs := range sessions {
		fmt.Fprintf(&b, `<section class="sess"><h2>Session #%d · %d events</h2>`, i+1, len(evs))
		for _, e := range evs {
			d, cls := "S→C", "S"
			if e.FromCli {
				d, cls = "C→S", "C"
			}
			fmt.Fprintf(&b, `<div class="row kind-%s"><div class="dir %s">%s</div><div><div class="sum">%s</div>`, e.Kind, cls, d, html.EscapeString(e.Summary))
			if e.Detail != "" {
				fmt.Fprintf(&b, `<div class="det">%s</div>`, html.EscapeString(e.Detail))
			}
			b.WriteString(`</div></div>`)
		}
		b.WriteString(`</section>`)
	}
	b.WriteString(`</main></body></html>`)
	return b.String()
}
