// Heap-map + pause-timeline HTML report.
#include "collectors.hpp"
#include "report.hpp"
#include "workloads.hpp"
#include <algorithm>
#include <array>
#include <cstdio>
#include <fstream>
#include <sstream>

namespace reaper {

namespace {

constexpr size_t COLS = 320, ROWS = 28, BINS = 240;

struct Panel {
  std::string name, desc, error;
  std::vector<std::string> rows;      // each row: COLS chars; 'a'..'p' old density, 'A'..'P' young density
  std::vector<std::string> gcRows;    // 1 = a collection ran since the previous snapshot
  std::vector<std::array<double, 2>> bins;   // [max pause ms, kind idx] per time bin
  double wall = 0, total = 0, maxp = 0;
  uint64_t minor = 0, major = 0, moved = 0, steps = 0;
  double endMs = 1;
};

std::string snapshot(Heap& h) {
  std::vector<uint8_t> m;
  h.map(m);
  size_t n = m.size() - BASE;
  std::string row(COLS, 'a');
  for (size_t c = 0; c < COLS; c++) {
    size_t lo = BASE + n * c / COLS, hi = BASE + n * (c + 1) / COLS;
    if (hi <= lo) hi = lo + 1;
    size_t old = 0, young = 0;
    for (size_t i = lo; i < hi && i < m.size(); i++) { if (m[i] == 1) old++; else if (m[i] == 2) young++; }
    size_t tot = hi - lo;
    size_t occ = old + young;
    int level = (int)(15.0 * occ / tot + 0.5);
    row[c] = (young > old ? 'A' : 'a') + level;
  }
  return row;
}

int kindIdx(char k) { return k == 'm' ? 1 : k == 's' ? 2 : 0; }

std::string jsonStr(const std::string& s) {
  std::string o = "\"";
  for (char c : s) { if (c == '"' || c == '\\') o += '\\'; if ((unsigned char)c >= 32) o += c; }
  return o + "\"";
}

}  // namespace

int cmdViz(const Args& a) {
  a.allow({"workload", "heap", "steps", "seed", "param", "gc"});
  if (a.pos.size() != 1) throw std::invalid_argument("usage: reaper viz <out.html> [--workload W] [--heap WORDS] [--steps N]");
  std::string w = a.str("workload", "lru-cache");
  size_t heap = 0, steps = 0;
  for (auto& i : workloadInfos()) if (i.name == w) { heap = i.defaultHeap; steps = i.defaultSteps; }
  if (!heap) throw std::invalid_argument("unknown workload '" + w + "'");
  if (a.has("heap")) heap = a.num("heap", 0);
  if (a.has("steps")) steps = a.num("steps", 0);
  if (steps < ROWS) throw std::invalid_argument("--steps must be at least " + std::to_string(ROWS));
  std::vector<std::string> kinds = heapKinds();
  if (a.has("gc")) {
    kinds = {a.str("gc", "")};
    if (std::find(heapKinds().begin(), heapKinds().end(), kinds[0]) == heapKinds().end()) throw std::invalid_argument("unknown collector '" + kinds[0] + "'");
  }
  std::vector<Panel> panels;
  for (auto& k : kinds) {
    Panel p;
    auto h = makeHeap(k, heap, a.num("param", 0));
    p.name = h->name();
    p.desc = h->describe();
    auto m = makeMutator(w, a.num("seed", 1), heap);
    double t0 = Heap::nowMs();
    uint64_t lastGcCount = 0;
    try {
      for (size_t i = 0; i < steps; i++) {
        m->step(*h);
        if ((i + 1) % (steps / ROWS) == 0 && p.rows.size() < ROWS) {
          p.rows.push_back(snapshot(*h));
          uint64_t gcs = h->stats.minor_gcs + h->stats.major_gcs + h->stats.inc_steps;
          p.gcRows.push_back(gcs != lastGcCount ? "1" : "0");
          lastGcCount = gcs;
        }
      }
      m->finish(*h);
    } catch (const std::exception& e) { p.error = e.what(); }
    p.wall = Heap::nowMs() - t0;
    p.endMs = std::max(p.wall, 1e-3);
    p.bins.assign(BINS, {0, 0});
    for (auto& ps : h->stats.pauses) {
      size_t b = std::min<size_t>(BINS - 1, (size_t)(ps.start_ms / p.endMs * BINS));
      if (ps.dur_ms > p.bins[b][0]) p.bins[b] = {ps.dur_ms, (double)kindIdx(ps.kind)};
    }
    p.total = h->stats.total_pause_ms;
    p.maxp = h->stats.max_pause_ms;
    p.minor = h->stats.minor_gcs;
    p.major = h->stats.major_gcs;
    p.moved = h->stats.moved_objects;
    p.steps = h->stats.inc_steps;
    panels.push_back(std::move(p));
  }

  std::ostringstream js;
  js << "{\"workload\":" << jsonStr(w) << ",\"heap\":" << heap << ",\"steps\":" << steps << ",\"cols\":" << COLS << ",\"panels\":[";
  for (size_t i = 0; i < panels.size(); i++) {
    auto& p = panels[i];
    if (i) js << ",";
    js << "{\"name\":" << jsonStr(p.name) << ",\"desc\":" << jsonStr(p.desc) << ",\"error\":" << jsonStr(p.error) << ",\"rows\":[";
    for (size_t r = 0; r < p.rows.size(); r++) js << (r ? "," : "") << jsonStr(p.rows[r]);
    js << "],\"gc\":\"";
    for (auto& g : p.gcRows) js << g;
    js << "\",\"bins\":[";
    for (size_t b = 0; b < p.bins.size(); b++) {
      char buf[64];
      snprintf(buf, sizeof buf, "%s[%.4f,%d]", b ? "," : "", p.bins[b][0], (int)p.bins[b][1]);
      js << buf;
    }
    char tail[256];
    snprintf(tail, sizeof tail, "],\"wall\":%.2f,\"total\":%.3f,\"max\":%.4f,\"minor\":%llu,\"major\":%llu,\"moved\":%llu,\"steps\":%llu}", p.wall, p.total, p.maxp,
             (unsigned long long)p.minor, (unsigned long long)p.major, (unsigned long long)p.moved, (unsigned long long)p.steps);
    js << tail;
  }
  js << "]}";

  std::string html = R"HTML(<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reaper — heap maps</title>
<style>
:root{--bg:#f6f4ef;--card:#fffdf8;--ink:#1d1b17;--mute:#6f6a5f;--line:#e3ded2;--old:#2f6f73;--young:#d9822b;--free:#ece8dc;--gc:#b4402f;--minor:#d9822b;--step:#6a5acd;--major:#b4402f}
@media (prefers-color-scheme:dark){:root{--bg:#14161a;--card:#1b1e24;--ink:#ece9e1;--mute:#9a978e;--line:#2b2f37;--old:#5fc0c4;--young:#f0a24d;--free:#242830;--gc:#ff7a66;--minor:#f0a24d;--step:#9d8cff;--major:#ff7a66}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:30px;letter-spacing:-.02em;margin:0 0 4px}h1 span{color:var(--old)}
.sub{color:var(--mute);margin:0 0 22px}
.legend{display:flex;flex-wrap:wrap;gap:16px;font-size:13px;color:var(--mute);margin:0 0 20px}
.legend i{display:inline-block;width:14px;height:14px;border-radius:3px;vertical-align:-2px;margin-right:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(520px,1fr));gap:18px}
@media(max-width:600px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 16px 12px}
.card h2{margin:0;font-size:18px;display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.card h2 small{font-weight:400;color:var(--mute);font-size:12px}
.desc{color:var(--mute);font-size:13px;margin:2px 0 10px}
canvas{width:100%;display:block;border-radius:8px;background:var(--free)}
.cap{font-size:12px;color:var(--mute);margin:6px 0 4px;display:flex;justify-content:space-between}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:10px}
.stats div{background:var(--bg);border-radius:8px;padding:6px 8px}
.stats b{display:block;font-size:15px;font-variant-numeric:tabular-nums}.stats span{font-size:11px;color:var(--mute);text-transform:uppercase;letter-spacing:.04em}
.err{color:var(--gc);font-size:13px}
footer{margin-top:28px;color:var(--mute);font-size:13px}
</style></head><body><main>
<h1>Reaper <span>heap maps</span></h1>
<p class="sub" id="sub"></p>
<div class="legend"><span><i style="background:var(--old)"></i>old / non-moving object words</span><span><i style="background:var(--young)"></i>nursery (young) words</span><span><i style="background:var(--free)"></i>free / unused</span><span><i style="background:var(--gc)"></i>row marker: a collection ran in this interval</span></div>
<div class="grid" id="grid"></div>
<footer>Each heap map is a time-lapse: every row is a snapshot of the whole arena (left = low addresses), top to bottom as the workload runs. Watch mark-sweep scatter, mark-compact and copying squeeze everything flat, copying flip halves, and the generational nursery fill and empty. Pause timelines show the longest pause in each time slice (log scale).</footer>
</main>
<script>
const D=__DATA__;
document.getElementById('sub').textContent=`workload “${D.workload}” · ${D.heap.toLocaleString()}-word heap · ${D.steps.toLocaleString()} steps · same seed for every collector`;
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function mix(a,b,t){const pa=hex(a),pb=hex(b);return `rgb(${pa.map((v,i)=>Math.round(v+(pb[i]-v)*t)).join(',')})`}
function hex(c){const d=document.createElement('canvas').getContext('2d');d.fillStyle=c;d.fillRect(0,0,1,1);return [...d.getImageData(0,0,1,1).data].slice(0,3)}
function draw(){
  const grid=document.getElementById('grid');grid.innerHTML='';
  const free=css('--free'),old=css('--old'),young=css('--young'),gc=css('--gc');
  const kc=[css('--major'),css('--minor'),css('--step')];
  for(const p of D.panels){
    const card=document.createElement('div');card.className='card';
    card.innerHTML=`<h2>${p.name}<small>${p.wall.toFixed(1)} ms wall</small></h2><div class="desc">${p.desc}</div>
    <div class="cap"><span>heap map (address →, time ↓)</span><span>${p.rows.length} snapshots</span></div><canvas class="map"></canvas>
    <div class="cap"><span>longest pause per time slice</span><span>max ${p.max.toFixed(3)} ms</span></div><canvas class="pz"></canvas>
    <div class="stats"><div><b>${p.minor}</b><span>minor GCs</span></div><div><b>${p.major}</b><span>major / cycles</span></div><div><b>${p.total.toFixed(2)} ms</b><span>total pause</span></div><div><b>${p.moved.toLocaleString()}</b><span>objects moved</span></div></div>`;
    if(p.error){const e=document.createElement('div');e.className='err';e.textContent='run failed: '+p.error;card.appendChild(e)}
    grid.appendChild(card);
    const dpr=window.devicePixelRatio||1;
    const mc=card.querySelector('.map'),W=mc.clientWidth,rh=7,H=p.rows.length*rh;
    mc.width=W*dpr;mc.height=H*dpr;mc.style.height=H+'px';const x=mc.getContext('2d');x.scale(dpr,dpr);
    const cw=(W-6)/D.cols;
    p.rows.forEach((row,r)=>{
      for(let c=0;c<row.length;c++){
        const ch=row.charCodeAt(c),isY=ch<97,lv=(isY?ch-65:ch-97)/15;
        if(lv>0){x.fillStyle=mix(free,isY?young:old,Math.min(1,.18+lv*.82));x.fillRect(6+c*cw,r*rh,Math.ceil(cw),rh-1)}
      }
      if(p.gc[r]==='1'){x.fillStyle=gc;x.fillRect(0,r*rh,3,rh-1)}
    });
    const pc=card.querySelector('.pz'),PH=64;pc.width=W*dpr;pc.height=PH*dpr;pc.style.height=PH+'px';const y=pc.getContext('2d');y.scale(dpr,dpr);
    const mx=Math.max(1e-4,...p.bins.map(b=>b[0])),lo=Math.log10(mx)-3;
    const bw=W/p.bins.length;
    p.bins.forEach((b,i)=>{if(b[0]<=0)return;const h=Math.max(2,(Math.log10(Math.max(b[0],1e-9))-lo)/3*(PH-4));y.fillStyle=kc[b[1]];y.fillRect(i*bw,PH-h,Math.max(1,bw-.5),h)});
  }
}
draw();addEventListener('resize',draw);matchMedia('(prefers-color-scheme:dark)').addEventListener('change',draw);
</script></body></html>
)HTML";
  size_t pos = html.find("__DATA__");
  html.replace(pos, 8, js.str());
  std::ofstream f(a.pos[0]);
  if (!f) throw std::runtime_error("cannot write " + a.pos[0]);
  f << html;
  std::printf("wrote %s (%zu bytes): %s on %zu-word heap, %zu collectors\n", a.pos[0].c_str(), html.size(), w.c_str(), heap, panels.size());
  return 0;
}

}  // namespace reaper
