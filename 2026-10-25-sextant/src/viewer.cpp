// Self-contained interactive viewer: one HTML file, data inlined as JSON, no external requests.
#include <cmath>
#include <cstdio>
#include <sstream>

#include "render.hpp"

namespace sextant {

namespace {

std::string num(double v) {
    char b[40];
    std::snprintf(b, sizeof b, "%.9g", v);
    return b;
}

std::string json_escape(const std::string& s) {
    std::string o;
    for (char c : s) {
        if (c == '"' || c == '\\') { o += '\\'; o += c; }
        else if (c == '<') o += "\\u003c";
        else if ((unsigned char)c < 0x20) o += ' ';
        else o += c;
    }
    return o;
}

const char* kPage = R"HTML(<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sextant viewer</title>
<style>
:root{
  --bg:#f6f4ef; --panel:#fffdf9; --ink:#23211d; --muted:#6c675e; --line:#ddd7ca;
  --edge:#3b3935; --seg:#171512; --vor:#4f78b8; --hull:#c4572d; --pt:#171512; --accent:#2d6f63;
  --focus:rgba(45,111,99,.18);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#16181b; --panel:#1e2125; --ink:#ece9e2; --muted:#9a968d; --line:#33373c;
    --edge:#c9c5bb; --seg:#f4efe3; --vor:#7fa6e0; --hull:#ee8b63; --pt:#f4efe3; --accent:#5dc0aa;
    --focus:rgba(93,192,170,.2);
  }
}
:root[data-theme="dark"]{
  --bg:#16181b; --panel:#1e2125; --ink:#ece9e2; --muted:#9a968d; --line:#33373c;
  --edge:#c9c5bb; --seg:#f4efe3; --vor:#7fa6e0; --hull:#ee8b63; --pt:#f4efe3; --accent:#5dc0aa;
  --focus:rgba(93,192,170,.2);
}
*{box-sizing:border-box}
html,body{height:100%;margin:0}
body{background:var(--bg);color:var(--ink);font:14px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;display:flex;flex-direction:column}
header{display:flex;align-items:baseline;gap:14px;padding:12px 18px;border-bottom:1px solid var(--line);background:var(--panel)}
header h1{font-size:15px;margin:0;letter-spacing:.02em}
header .sub{color:var(--muted);font-size:13px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
button.theme{border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:6px;padding:4px 10px;cursor:pointer;font:inherit}
button.theme:hover{border-color:var(--accent)}
main{flex:1;display:flex;min-height:0}
#stage{flex:1;position:relative;min-width:0}
canvas{position:absolute;inset:0;width:100%;height:100%;display:block;cursor:grab;touch-action:none}
canvas.drag{cursor:grabbing}
aside{width:300px;border-left:1px solid var(--line);background:var(--panel);padding:16px 18px;overflow:auto}
aside h2{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);margin:18px 0 8px;font-weight:600}
aside h2:first-child{margin-top:0}
label.chk{display:flex;align-items:center;gap:9px;padding:3px 0;cursor:pointer}
input[type=checkbox]{accent-color:var(--accent);width:15px;height:15px}
dl{display:grid;grid-template-columns:auto 1fr;gap:3px 12px;margin:0}
dt{color:var(--muted)} dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}
#hist{display:block;width:100%;height:84px}
#info{min-height:150px;font-size:13px}
#info .empty{color:var(--muted)}
.legend{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:12px;margin-top:6px}
.legend i{flex:1;height:8px;border-radius:4px;background:linear-gradient(90deg,#d64d3e,#ecbe54,#42a08a)}
.hint{color:var(--muted);font-size:12px;margin-top:14px}
@media (max-width:760px){main{flex-direction:column}aside{width:auto;border-left:0;border-top:1px solid var(--line);max-height:46vh}#stage{min-height:50vh}}
</style>
</head>
<body>
<header><h1>Sextant</h1><div class="sub" id="title"></div><button class="theme" id="theme" title="Toggle light / dark">Theme</button></header>
<main>
  <div id="stage"><canvas id="cv"></canvas></div>
  <aside>
    <h2>Layers</h2>
    <label class="chk"><input type="checkbox" id="L_fill" checked> Quality colouring</label>
    <label class="chk"><input type="checkbox" id="L_tri" checked> Triangle edges</label>
    <label class="chk"><input type="checkbox" id="L_vor"> Voronoi cells</label>
    <label class="chk"><input type="checkbox" id="L_seg" checked> Constrained segments</label>
    <label class="chk"><input type="checkbox" id="L_hull"> Convex hull</label>
    <label class="chk"><input type="checkbox" id="L_pts" checked> Points</label>
    <label class="chk"><input type="checkbox" id="L_circ" checked> Circumcircle on hover</label>
    <h2>Mesh</h2>
    <dl id="stats"></dl>
    <h2>Smallest angle per triangle</h2>
    <canvas id="hist" style="position:static;cursor:default"></canvas>
    <div class="legend"><span>0°</span><i></i><span>60°</span></div>
    <h2>Under the cursor</h2>
    <div id="info"><span class="empty">Hover a triangle to inspect it. Its circumcircle is empty of other vertices — that is the Delaunay property.</span></div>
    <div class="hint">Scroll to zoom, drag to pan, double-click to reset.</div>
  </aside>
</main>
<script>
const D = /*DATA*/null;
const P = D.pts, T = D.tris, S = D.segs, C = D.cells, H = D.hull, SITE = D.sites;
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const $ = id => document.getElementById(id);
$('title').textContent = D.title;
document.title = 'Sextant — ' + D.title;

// ---- derived data ---------------------------------------------------------------------------
const nT = T.length / 3;
const px = i => P[2*i], py = i => P[2*i+1];
function angles(a, b, c) {
  const L = (p, q, r) => { const ux = px(q)-px(p), uy = py(q)-py(p), vx = px(r)-px(p), vy = py(r)-py(p);
    return Math.atan2(Math.abs(ux*vy-uy*vx), ux*vx+uy*vy) * 180 / Math.PI; };
  return [L(a,b,c), L(b,c,a), L(c,a,b)];
}
const minAng = new Float32Array(nT), area = new Float32Array(nT);
let amin = 180, amax = 0, asum = 0;
for (let t = 0; t < nT; ++t) {
  const a = T[3*t], b = T[3*t+1], c = T[3*t+2];
  const an = angles(a, b, c);
  minAng[t] = Math.min(an[0], an[1], an[2]);
  area[t] = 0.5 * ((px(b)-px(a))*(py(c)-py(a)) - (py(b)-py(a))*(px(c)-px(a)));
  amin = Math.min(amin, minAng[t]); amax = Math.max(amax, Math.max(an[0], an[1], an[2])); asum += area[t];
}
function ramp(a) {
  const t = Math.max(0, Math.min(1, a / 60));
  const lo = [214,77,62], mid = [236,190,84], hi = [66,160,138];
  const [A, B] = t < .5 ? [lo, mid] : [mid, hi], u = t < .5 ? t*2 : (t-.5)*2;
  return 'rgb(' + A.map((v, i) => Math.round(v + (B[i]-v)*u)).join(',') + ')';
}
const rampCache = Array.from({length: 61}, (_, i) => ramp(i));

// bounds
let bx0 = Infinity, by0 = Infinity, bx1 = -Infinity, by1 = -Infinity;
for (let i = 0; i < P.length/2; ++i) { if (!SITE[i]) continue; bx0 = Math.min(bx0, px(i)); bx1 = Math.max(bx1, px(i)); by0 = Math.min(by0, py(i)); by1 = Math.max(by1, py(i)); }
if (D.box) { bx0 = Math.min(bx0, D.box[0]); by0 = Math.min(by0, D.box[1]); bx1 = Math.max(bx1, D.box[2]); by1 = Math.max(by1, D.box[3]); }
if (!isFinite(bx0)) { bx0 = by0 = 0; bx1 = by1 = 1; }
if (bx1 - bx0 < 1e-12) { bx0 -= .5; bx1 += .5; } if (by1 - by0 < 1e-12) { by0 -= .5; by1 += .5; }

// uniform grid over triangles for hover hit-testing
const GN = Math.max(1, Math.min(256, Math.floor(Math.sqrt(nT / 4)) || 1));
const grid = Array.from({length: GN*GN}, () => []);
const gcell = (v, lo, hi) => Math.max(0, Math.min(GN-1, Math.floor((v-lo)/(hi-lo)*GN)));
for (let t = 0; t < nT; ++t) {
  const xs = [px(T[3*t]), px(T[3*t+1]), px(T[3*t+2])], ys = [py(T[3*t]), py(T[3*t+1]), py(T[3*t+2])];
  const x0 = gcell(Math.min(...xs), bx0, bx1), x1 = gcell(Math.max(...xs), bx0, bx1);
  const y0 = gcell(Math.min(...ys), by0, by1), y1 = gcell(Math.max(...ys), by0, by1);
  for (let y = y0; y <= y1; ++y) for (let x = x0; x <= x1; ++x) grid[y*GN+x].push(t);
}
function pick(wx, wy) {
  const bucket = grid[gcell(wy, by0, by1)*GN + gcell(wx, bx0, bx1)];
  for (const t of bucket) {
    const a = T[3*t], b = T[3*t+1], c = T[3*t+2];
    const o = (p, q) => (px(q)-px(p))*(wy-py(p)) - (py(q)-py(p))*(wx-px(p));
    if (o(a,b) >= 0 && o(b,c) >= 0 && o(c,a) >= 0) return t;
  }
  return -1;
}

// ---- view -----------------------------------------------------------------------------------
let scale = 1, ox = 0, oy = 0, W = 0, Hh = 0, dpr = 1, hover = -1;
function fit() {
  const pad = 36, w = bx1 - bx0, h = by1 - by0;
  scale = Math.min((W - 2*pad) / w, (Hh - 2*pad) / h);
  ox = (W - w*scale) / 2 - bx0*scale;
  oy = (Hh + h*scale) / 2 + by0*scale;
}
const sx = x => x*scale + ox, sy = y => oy - y*scale;
const wx = x => (x - ox) / scale, wy = y => (oy - y) / scale;
function resize() {
  const r = cv.getBoundingClientRect(); dpr = window.devicePixelRatio || 1;
  W = r.width; Hh = r.height; cv.width = Math.max(1, Math.round(W*dpr)); cv.height = Math.max(1, Math.round(Hh*dpr));
  if (!resize.once) { fit(); resize.once = true; }
  draw();
}
const on = id => $(id).checked;
function draw() {
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, Hh);
  ctx.lineJoin = 'round'; ctx.lineCap = 'round';
  const dense = nT > 60000 && scale * 0 === 0;
  if (on('L_fill') && nT) {
    for (let t = 0; t < nT; ++t) {
      const a = T[3*t], b = T[3*t+1], c = T[3*t+2];
      ctx.beginPath(); ctx.moveTo(sx(px(a)), sy(py(a))); ctx.lineTo(sx(px(b)), sy(py(b))); ctx.lineTo(sx(px(c)), sy(py(c))); ctx.closePath();
      ctx.fillStyle = rampCache[Math.min(60, Math.round(minAng[t]))]; ctx.globalAlpha = .5; ctx.fill();
      if (dense) { ctx.strokeStyle = ctx.fillStyle; ctx.lineWidth = .6; ctx.stroke(); }
    }
    ctx.globalAlpha = 1;
  }
  if (on('L_tri') && nT) {
    ctx.strokeStyle = css('--edge'); ctx.lineWidth = nT > 20000 ? .4 : .8; ctx.globalAlpha = nT > 20000 ? .6 : .85;
    ctx.beginPath();
    for (let t = 0; t < nT; ++t) {
      const a = T[3*t], b = T[3*t+1], c = T[3*t+2];
      ctx.moveTo(sx(px(a)), sy(py(a))); ctx.lineTo(sx(px(b)), sy(py(b))); ctx.lineTo(sx(px(c)), sy(py(c))); ctx.closePath();
    }
    ctx.stroke(); ctx.globalAlpha = 1;
  }
  if (on('L_vor') && C.length) {
    ctx.strokeStyle = css('--vor'); ctx.lineWidth = 1.5; ctx.beginPath();
    for (const poly of C) { if (poly.length < 6) continue; ctx.moveTo(sx(poly[0]), sy(poly[1]));
      for (let i = 2; i < poly.length; i += 2) ctx.lineTo(sx(poly[i]), sy(poly[i+1])); ctx.closePath(); }
    ctx.stroke();
    if (D.box) { ctx.setLineDash([4, 4]); ctx.globalAlpha = .6; ctx.strokeRect(sx(D.box[0]), sy(D.box[3]), (D.box[2]-D.box[0])*scale, (D.box[3]-D.box[1])*scale); ctx.setLineDash([]); ctx.globalAlpha = 1; }
  }
  if (on('L_seg') && S.length) {
    ctx.strokeStyle = css('--seg'); ctx.lineWidth = 2.4; ctx.beginPath();
    for (let i = 0; i < S.length; i += 2) { ctx.moveTo(sx(px(S[i])), sy(py(S[i]))); ctx.lineTo(sx(px(S[i+1])), sy(py(S[i+1]))); }
    ctx.stroke();
  }
  if (on('L_hull') && H.length) {
    ctx.strokeStyle = css('--hull'); ctx.lineWidth = 2; ctx.setLineDash([7, 5]); ctx.beginPath();
    H.forEach((v, i) => i ? ctx.lineTo(sx(px(v)), sy(py(v))) : ctx.moveTo(sx(px(v)), sy(py(v)))); ctx.closePath(); ctx.stroke(); ctx.setLineDash([]);
  }
  if (hover >= 0 && on('L_circ')) {
    const a = T[3*hover], b = T[3*hover+1], c = T[3*hover+2];
    const cc = circum(a, b, c);
    ctx.strokeStyle = css('--accent'); ctx.lineWidth = 1.6; ctx.fillStyle = css('--focus');
    ctx.beginPath(); ctx.arc(sx(cc.x), sy(cc.y), cc.r*scale, 0, 6.2832); ctx.fill(); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(sx(px(a)), sy(py(a))); ctx.lineTo(sx(px(b)), sy(py(b))); ctx.lineTo(sx(px(c)), sy(py(c))); ctx.closePath();
    ctx.lineWidth = 2.4; ctx.stroke();
    ctx.fillStyle = css('--accent'); ctx.beginPath(); ctx.arc(sx(cc.x), sy(cc.y), 3, 0, 6.2832); ctx.fill();
  }
  if (on('L_pts') && P.length/2 <= 40000) {
    ctx.fillStyle = css('--pt'); const r = P.length/2 > 3000 ? 1.4 : 2.6;
    for (let i = 0; i < P.length/2; ++i) { if (!SITE[i]) continue; ctx.beginPath(); ctx.arc(sx(px(i)), sy(py(i)), r, 0, 6.2832); ctx.fill(); }
  }
}
function circum(a, b, c) {
  const ax = px(a), ay = py(a), bx = px(b)-ax, by = py(b)-ay, cx = px(c)-ax, cy = py(c)-ay;
  const d = 2*(bx*cy - by*cx), b2 = bx*bx+by*by, c2 = cx*cx+cy*cy;
  const ux = (cy*b2 - by*c2)/d, uy = (bx*c2 - cx*b2)/d;
  return {x: ax+ux, y: ay+uy, r: Math.hypot(ux, uy)};
}

// ---- side panel -----------------------------------------------------------------------------
const fmt = (v, n = 4) => Number.isFinite(v) ? (Math.abs(v) >= 1e5 || (v !== 0 && Math.abs(v) < 1e-3) ? v.toExponential(2) : (+v.toPrecision(n)).toString()) : '–';
(function stats() {
  const rows = [['Vertices', SITE.reduce((a, b) => a + b, 0)], ['Triangles', nT]];
  if (S.length) rows.push(['Segments', S.length/2]);
  if (nT) { rows.push(['Smallest angle', fmt(amin, 3) + '°'], ['Largest angle', fmt(amax, 4) + '°'], ['Total area', fmt(asum)]); }
  if (C.length) rows.push(['Voronoi cells', C.filter(p => p.length >= 6).length]);
  $('stats').innerHTML = rows.map(([k, v]) => '<dt>' + k + '</dt><dd>' + v + '</dd>').join('');
})();
function histogram() {
  const h = $('hist'), g = h.getContext('2d'), r = h.getBoundingClientRect(), d = window.devicePixelRatio || 1;
  h.width = Math.round(r.width*d); h.height = Math.round(r.height*d); g.setTransform(d, 0, 0, d, 0, 0);
  const bins = new Array(12).fill(0); for (let t = 0; t < nT; ++t) bins[Math.min(11, Math.floor(minAng[t]/5))]++;
  const mx = Math.max(1, ...bins), bw = r.width / 12;
  bins.forEach((n, i) => { const hh = (r.height - 16) * n / mx; g.fillStyle = ramp(i*5 + 2.5);
    g.fillRect(i*bw + 1.5, r.height - 14 - hh, bw - 3, hh); });
  g.fillStyle = css('--muted'); g.font = '10px system-ui'; g.textAlign = 'center';
  [0, 20, 40, 60].forEach(a => g.fillText(a + '°', Math.min(r.width-8, Math.max(8, a/60*r.width)), r.height - 2));
}
function info(t) {
  if (t < 0) { $('info').innerHTML = '<span class="empty">Hover a triangle to inspect it. Its circumcircle is empty of other vertices — that is the Delaunay property.</span>'; return; }
  const a = T[3*t], b = T[3*t+1], c = T[3*t+2], an = angles(a, b, c), cc = circum(a, b, c);
  $('info').innerHTML = '<dl>' +
    '<dt>Vertices</dt><dd>' + a + ', ' + b + ', ' + c + '</dd>' +
    '<dt>Angles</dt><dd>' + an.map(v => v.toFixed(1)).join(' · ') + '°</dd>' +
    '<dt>Area</dt><dd>' + fmt(area[t]) + '</dd>' +
    '<dt>Circumcentre</dt><dd>' + fmt(cc.x) + ', ' + fmt(cc.y) + '</dd>' +
    '<dt>Circumradius</dt><dd>' + fmt(cc.r) + '</dd>' +
    '<dt>Radius / shortest edge</dt><dd>' + fmt(cc.r / Math.min(Math.hypot(px(a)-px(b), py(a)-py(b)), Math.hypot(px(b)-px(c), py(b)-py(c)), Math.hypot(px(c)-px(a), py(c)-py(a)))) + '</dd></dl>';
}

// ---- interaction ----------------------------------------------------------------------------
let drag = null;
cv.addEventListener('pointerdown', e => { drag = {x: e.clientX, y: e.clientY, ox, oy}; cv.classList.add('drag'); cv.setPointerCapture(e.pointerId); });
cv.addEventListener('pointerup', () => { drag = null; cv.classList.remove('drag'); });
cv.addEventListener('pointermove', e => {
  const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
  if (drag) { ox = drag.ox + e.clientX - drag.x; oy = drag.oy + e.clientY - drag.y; draw(); return; }
  const t = pick(wx(x), wy(y)); if (t !== hover) { hover = t; info(t); draw(); }
});
cv.addEventListener('pointerleave', () => { if (hover >= 0) { hover = -1; info(-1); draw(); } });
cv.addEventListener('wheel', e => {
  e.preventDefault(); const r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
  const k = Math.exp(-e.deltaY * 0.0015), wxp = wx(x), wyp = wy(y);
  scale *= k; ox = x - wxp*scale; oy = y + wyp*scale; draw();
}, {passive: false});
cv.addEventListener('dblclick', () => { fit(); draw(); });
document.querySelectorAll('input[type=checkbox]').forEach(c => c.addEventListener('change', draw));
$('theme').addEventListener('click', () => {
  const cur = document.documentElement.getAttribute('data-theme') ||
    (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  document.documentElement.setAttribute('data-theme', cur === 'dark' ? 'light' : 'dark'); histogram(); draw();
});
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { histogram(); draw(); });
// layers with no data are disabled rather than silently doing nothing
for (const [id, has] of [['L_vor', C.length], ['L_seg', S.length], ['L_hull', H.length], ['L_fill', nT], ['L_tri', nT], ['L_circ', nT]]) {
  if (!has) { $(id).checked = false; $(id).disabled = true; $(id).parentElement.style.opacity = .45; }
}
if (C.length) $('L_vor').checked = true, $('L_fill').checked = false;
if (D.hullOn) $('L_hull').checked = true;
new ResizeObserver(() => { resize(); histogram(); }).observe($('stage'));
</script>
</body>
</html>
)HTML";

}  // namespace

std::string render_html(const Scene& s) {
    std::ostringstream d;
    d << "{\"title\":\"" << json_escape(s.title) << "\",\"pts\":[";
    for (size_t i = 0; i < s.pts.size(); ++i) d << (i ? "," : "") << num(s.pts[i].x) << "," << num(s.pts[i].y);
    d << "],\"sites\":[";
    for (size_t i = 0; i < s.pts.size(); ++i) d << (i ? "," : "") << (s.is_site[i] ? 1 : 0);
    d << "],\"tris\":[";
    for (size_t i = 0; i < s.tris.size(); ++i) d << (i ? "," : "") << s.tris[i][0] << "," << s.tris[i][1] << "," << s.tris[i][2];
    d << "],\"segs\":[";
    for (size_t i = 0; i < s.segs.size(); ++i) d << (i ? "," : "") << s.segs[i].first << "," << s.segs[i].second;
    d << "],\"cells\":[";
    bool first = true;
    for (const auto& c : s.cells) {
        if (c.polygon.size() < 3 || (c.site >= 0 && !s.is_site[c.site])) continue;
        d << (first ? "" : ",") << "[";
        first = false;
        for (size_t i = 0; i < c.polygon.size(); ++i) d << (i ? "," : "") << num(c.polygon[i].x) << "," << num(c.polygon[i].y);
        d << "]";
    }
    d << "],\"hull\":[";
    for (size_t i = 0; i < s.hull.size(); ++i) d << (i ? "," : "") << s.hull[i];
    d << "],\"hullOn\":" << (s.hull.empty() ? "false" : "true");
    if (s.has_box) d << ",\"box\":[" << num(s.box.x0) << "," << num(s.box.y0) << "," << num(s.box.x1) << "," << num(s.box.y1) << "]";
    d << "}";
    std::string page = kPage;
    const std::string marker = "/*DATA*/null";
    size_t at = page.find(marker);
    page.replace(at, marker.size(), d.str());
    return page;
}

}  // namespace sextant
