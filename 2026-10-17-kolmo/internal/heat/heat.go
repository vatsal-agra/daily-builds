// Package heat renders a file as HTML where every byte is shaded by the number of bits the
// context-mixing model needed to encode it: bright = surprising, pale = predictable.
package heat

import (
	"fmt"
	"html"
	"sort"
	"strings"

	"kolmo/internal/cm"
)

// Render returns a self-contained HTML report for data (at most maxBytes are analysed).
func Render(name string, data []byte, maxBytes int) string {
	truncated := false
	if maxBytes > 0 && len(data) > maxBytes {
		data, truncated = data[:maxBytes], true
	}
	costs := cm.Costs(data)
	var total float64
	for _, c := range costs {
		total += float64(c)
	}
	n := len(data)
	avg := 0.0
	if n > 0 {
		avg = total / float64(n)
	}

	// cost per line, for the "most surprising lines" list
	type line struct {
		no, start, end int
		bits           float64
	}
	var lines []line
	st := 0
	for i := 0; i <= n; i++ {
		if i == n || data[i] == '\n' {
			if i > st {
				b := 0.0
				for _, c := range costs[st:i] {
					b += float64(c)
				}
				lines = append(lines, line{len(lines) + 1, st, i, b})
			}
			st = i + 1
		}
	}
	top := append([]line(nil), lines...)
	sort.Slice(top, func(a, b int) bool {
		return top[a].bits/float64(top[a].end-top[a].start) > top[b].bits/float64(top[b].end-top[b].start)
	})
	if len(top) > 8 {
		top = top[:8]
	}

	// histogram of per-byte cost, 0..8+ bits
	var hist [9]int
	for _, c := range costs {
		b := int(c)
		if b > 8 {
			b = 8
		}
		hist[b]++
	}
	maxH := 1
	for _, h := range hist {
		if h > maxH {
			maxH = h
		}
	}

	var sb strings.Builder
	sb.WriteString(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">`)
	fmt.Fprintf(&sb, "<title>Kolmo heat — %s</title>", html.EscapeString(name))
	sb.WriteString(css)
	sb.WriteString(`</head><body><main><header><h1>Kolmo <span>heat</span></h1><p class="sub">Every byte shaded by the bits the context-mixing model spent on it.</p></header>`)
	fmt.Fprintf(&sb, `<section class="stats"><div><b>%s</b><small>file</small></div><div><b>%d</b><small>bytes analysed%s</small></div><div><b>%.3f</b><small>bits / byte</small></div><div><b>%.1f×</b><small>model ratio</small></div><div><b>%d</b><small>bytes if coded</small></div></section>`,
		html.EscapeString(name), n, map[bool]string{true: " (truncated)", false: ""}[truncated], avg, ratio(avg), int(total/8+0.999))
	sb.WriteString(`<section><h2>Cost distribution</h2><div class="hist">`)
	for b, h := range hist {
		label := fmt.Sprintf("%d", b)
		if b == 8 {
			label = "8+"
		}
		fmt.Fprintf(&sb, `<div class="col"><div class="bar" style="height:%.1f%%" title="%d bytes"></div><span>%s</span></div>`, 100*float64(h)/float64(maxH), h, label)
	}
	sb.WriteString(`</div><p class="cap">bytes by bits spent (x axis: bits)</p></section>`)
	if len(top) > 0 && n > 0 {
		sb.WriteString(`<section><h2>Most surprising lines</h2><ol class="top">`)
		for _, l := range top {
			txt := string(data[l.start:l.end])
			if len(txt) > 90 {
				txt = txt[:90] + "…"
			}
			fmt.Fprintf(&sb, `<li><code>%s</code><em>line %d · %.2f bits/byte</em></li>`, html.EscapeString(printable(txt)), l.no, l.bits/float64(l.end-l.start))
		}
		sb.WriteString(`</ol></section>`)
	}
	sb.WriteString(`<section><h2>Annotated file</h2><div class="legend"><span>0 bits</span><i></i><span>8+ bits</span></div><pre class="map">`)
	// The file text and one cost character per byte are embedded once; a small script merges
	// runs of equal shading into spans in the browser, keeping the report ~2x the input size.
	var text, enc strings.Builder
	for i, b := range data {
		switch {
		case b == '\n' || b == '\t':
			text.WriteByte(b)
		case b < 32 || b >= 127:
			text.WriteString("·")
		default:
			text.WriteByte(b)
		}
		q := int(costs[i]*4 + 0.5) // quarter-bit resolution, clipped to 90
		if q > 90 {
			q = 90
		}
		enc.WriteByte(byte(35 + q))
	}
	fmt.Fprintf(&sb, `<pre class="map" id="map" data-costs="%s">%s</pre>`, html.EscapeString(enc.String()), html.EscapeString(text.String()))
	sb.WriteString(script)
	sb.WriteString(`</section></main></body></html>`)
	return sb.String()
}

func ratio(bitsPerByte float64) float64 {
	if bitsPerByte == 0 {
		return 0
	}
	return 8 / bitsPerByte
}

func printable(s string) string {
	return strings.Map(func(r rune) rune {
		if r < 32 || r == 127 {
			return '·'
		}
		return r
	}, s)
}

const script = `<script>
(function(){var pre=document.getElementById("map"),c=pre.dataset.costs,t=Array.from(pre.textContent);
if(t.length!==c.length){return}
var f=document.createDocumentFragment(),i=0,n=t.length;
function lvl(k){return Math.min(15,Math.floor((c.charCodeAt(k)-35)/4/8*15))}
while(i<n){var L=lvl(i),j=i,sum=0;
 while(j<n&&(lvl(j)===L||t[j]==="\n")){sum+=(c.charCodeAt(j)-35)/4;j++}
 var s=document.createElement("span");s.className="h"+L;s.textContent=t.slice(i,j).join("");
 s.title=j-i===1?sum.toFixed(2)+" bits":(j-i)+" bytes, avg "+(sum/(j-i)).toFixed(2)+" bits";f.appendChild(s);i=j}
pre.textContent="";pre.appendChild(f)})();
</script>`

const css = `<style>
:root{--bg:#fbfaf7;--fg:#1d1b17;--mut:#6f6a60;--card:#fff;--line:#e6e2d8;--hot:225,70,40;--acc:#c2410c}
@media (prefers-color-scheme:dark){:root{--bg:#14120f;--fg:#ece8df;--mut:#9b9487;--card:#1c1914;--line:#2c2820;--hot:255,110,70;--acc:#fb923c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:40px 20px 80px}
h1{font-size:34px;margin:0;letter-spacing:-.02em}h1 span{color:var(--acc);font-style:italic;font-weight:500}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.12em;color:var(--mut);margin:36px 0 12px}
.sub{color:var(--mut);margin:6px 0 28px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.stats div{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.stats b{display:block;font-size:22px;font-variant-numeric:tabular-nums;overflow:hidden;text-overflow:ellipsis}.stats small{color:var(--mut)}
.hist{display:flex;gap:8px;align-items:flex-end;height:130px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.col{flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;gap:4px;font-size:12px;color:var(--mut)}
.bar{width:100%;background:rgba(var(--hot),.75);border-radius:4px 4px 0 0;min-height:2px}
.cap{color:var(--mut);font-size:12px;margin:6px 2px}
.top{padding:0;margin:0;list-style:none;display:grid;gap:8px}
.top li{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;display:flex;justify-content:space-between;gap:16px;align-items:baseline}
.top code{font:13px ui-monospace,Menlo,monospace;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.top em{color:var(--mut);font-size:12px;white-space:nowrap;font-style:normal}
.legend{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--mut);margin-bottom:10px}.legend i{flex:0 0 160px;height:10px;border-radius:5px;background:linear-gradient(90deg,rgba(var(--hot),.02),rgba(var(--hot),.85))}
.map{margin:0;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;overflow:auto;font:13px/1.6 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;word-break:break-all}
.map span{border-radius:2px}
.h0{background:rgba(var(--hot),0.00)}.h1{background:rgba(var(--hot),0.06)}.h2{background:rgba(var(--hot),0.11)}.h3{background:rgba(var(--hot),0.17)}.h4{background:rgba(var(--hot),0.23)}.h5{background:rgba(var(--hot),0.28)}.h6{background:rgba(var(--hot),0.34)}.h7{background:rgba(var(--hot),0.40)}.h8{background:rgba(var(--hot),0.45)}.h9{background:rgba(var(--hot),0.51)}.h10{background:rgba(var(--hot),0.57)}.h11{background:rgba(var(--hot),0.62)}.h12{background:rgba(var(--hot),0.68)}.h13{background:rgba(var(--hot),0.74)}.h14{background:rgba(var(--hot),0.79)}.h15{background:rgba(var(--hot),0.85)}
</style>`
