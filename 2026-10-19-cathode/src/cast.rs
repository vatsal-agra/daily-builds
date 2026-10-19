//! asciicast v2 (<https://docs.asciinema.org/manual/asciicast/v2/>): recording, parsing, replay
//! into a [`Term`], and a self-contained HTML flip-book player.

use crate::json::{self, Value};
use crate::render::{html_css, html_rows, RenderOpts, Theme};
use crate::term::Term;

/// Largest width/height a cast may declare (a hostile header must not allocate gigabytes).
pub const MAX_DIM: usize = 1000;

#[derive(Clone, Debug, PartialEq)]
pub struct Event {
    pub t: f64,
    /// 'o' output, 'i' input, 'r' resize, 'm' marker.
    pub kind: char,
    pub data: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Cast {
    pub cols: usize,
    pub rows: usize,
    pub title: Option<String>,
    pub command: Option<String>,
    pub events: Vec<Event>,
}

impl Cast {
    pub fn new(cols: usize, rows: usize) -> Cast {
        Cast { cols, rows, title: None, command: None, events: Vec::new() }
    }
    pub fn duration(&self) -> f64 {
        self.events.last().map(|e| e.t).unwrap_or(0.0)
    }

    pub fn to_string(&self) -> String {
        let mut h = vec![
            ("version".to_string(), Value::Num(2.0)),
            ("width".to_string(), Value::Num(self.cols as f64)),
            ("height".to_string(), Value::Num(self.rows as f64)),
        ];
        if let Some(t) = &self.title {
            h.push(("title".into(), Value::Str(t.clone())));
        }
        if let Some(c) = &self.command {
            h.push(("command".into(), Value::Str(c.clone())));
        }
        h.push(("env".into(), Value::Obj(vec![("TERM".into(), Value::Str("xterm-256color".into()))])));
        let mut out = Value::Obj(h).to_json();
        out.push('\n');
        for e in &self.events {
            let mut line = String::from("[");
            line.push_str(&format!("{:.6}", e.t));
            line.push_str(",\"");
            line.push(e.kind);
            line.push_str("\",");
            json::write_str(&e.data, &mut line);
            line.push_str("]\n");
            out.push_str(&line);
        }
        out
    }

    pub fn parse(src: &str) -> Result<Cast, String> {
        let mut lines = src.lines().filter(|l| !l.trim().is_empty());
        let head = lines.next().ok_or("empty cast file")?;
        let h = json::parse(head).map_err(|e| format!("bad header: {}", e))?;
        match h.get("version").and_then(|v| v.as_f64()) {
            Some(v) if v == 2.0 => {}
            Some(v) => return Err(format!("unsupported asciicast version {}", v)),
            None => return Err("header has no version".into()),
        }
        let dim = |k: &str| -> Result<usize, String> {
            match h.get(k).and_then(|v| v.as_f64()) {
                Some(n) if (1.0..=MAX_DIM as f64).contains(&n) => Ok(n as usize),
                _ => Err(format!("header field {:?} missing or out of range", k)),
            }
        };
        let mut cast = Cast::new(dim("width")?, dim("height")?);
        cast.title = h.get("title").and_then(|v| v.as_str()).map(String::from);
        cast.command = h.get("command").and_then(|v| v.as_str()).map(String::from);
        let mut last_t = 0.0f64;
        for (i, l) in lines.enumerate() {
            let v = json::parse(l).map_err(|e| format!("event {}: {}", i + 1, e))?;
            let a = v.as_arr().ok_or_else(|| format!("event {} is not an array", i + 1))?;
            if a.len() != 3 {
                return Err(format!("event {} must have 3 elements", i + 1));
            }
            let t = a[0].as_f64().ok_or_else(|| format!("event {}: bad time", i + 1))?;
            if !t.is_finite() || t < 0.0 {
                return Err(format!("event {}: negative or non-finite time", i + 1));
            }
            if t < last_t {
                return Err(format!("event {}: time goes backwards ({} < {})", i + 1, t, last_t));
            }
            last_t = t;
            let k = a[1].as_str().and_then(|s| s.chars().next()).ok_or_else(|| format!("event {}: bad type", i + 1))?;
            let d = a[2].as_str().ok_or_else(|| format!("event {}: data is not a string", i + 1))?;
            cast.events.push(Event { t, kind: k, data: d.to_string() });
        }
        Ok(cast)
    }

    /// Compress idle gaps longer than `limit` seconds down to `limit` (asciinema's `idle_time_limit`).
    pub fn cap_idle(&mut self, limit: f64) {
        let mut prev = 0.0;
        let mut shift = 0.0;
        for e in &mut self.events {
            let gap = e.t - prev;
            prev = e.t;
            if gap > limit {
                shift += gap - limit;
            }
            e.t -= shift;
        }
    }

    /// Apply one event to a terminal.
    pub fn apply(term: &mut Term, e: &Event) {
        match e.kind {
            'o' => term.feed(e.data.as_bytes()),
            'r' => {
                if let Some((c, r)) = e.data.split_once('x') {
                    if let (Ok(c), Ok(r)) = (c.parse::<usize>(), r.parse::<usize>()) {
                        if (1..=MAX_DIM).contains(&c) && (1..=MAX_DIM).contains(&r) {
                            term.resize(c, r);
                        }
                    }
                }
            }
            _ => {}
        }
    }

    /// Replay all events with `t <= at` (or all when `None`).
    pub fn replay(&self, at: Option<f64>) -> Term {
        let mut term = Term::new(self.cols, self.rows);
        for e in &self.events {
            if let Some(a) = at {
                if e.t > a {
                    break;
                }
            }
            Cast::apply(&mut term, e);
        }
        term.take_output();
        term
    }
}

/// Holds back an incomplete trailing UTF-8 sequence between PTY reads so each recorded event is valid JSON text.
#[derive(Default)]
pub struct Utf8Chunker {
    pending: Vec<u8>,
}

impl Utf8Chunker {
    pub fn push(&mut self, bytes: &[u8]) -> String {
        self.pending.extend_from_slice(bytes);
        let keep = incomplete_tail(&self.pending);
        let cut = self.pending.len() - keep;
        let head: Vec<u8> = self.pending.drain(..cut).collect();
        String::from_utf8_lossy(&head).into_owned()
    }
    pub fn finish(&mut self) -> String {
        let rest = std::mem::take(&mut self.pending);
        String::from_utf8_lossy(&rest).into_owned()
    }
}

/// Number of bytes at the end of `b` that form a valid-so-far but incomplete UTF-8 sequence.
fn incomplete_tail(b: &[u8]) -> usize {
    for back in 1..=3.min(b.len()) {
        let x = b[b.len() - back];
        if x & 0xC0 == 0x80 {
            continue; // continuation, keep looking for the lead
        }
        let need = match x {
            0xC2..=0xDF => 2,
            0xE0..=0xEF => 3,
            0xF0..=0xF4 => 4,
            _ => return 0,
        };
        return if need > back { back } else { 0 };
    }
    0
}

/// Build a self-contained HTML player: pre-rendered keyframes (row-deduplicated) plus a small
/// scrubber/play/speed UI. `max_frames` bounds the size.
pub fn player_html(cast: &Cast, theme: Theme, max_frames: usize) -> String {
    // Frame times: after each burst of output (events within 30 ms coalesce).
    let mut times: Vec<f64> = Vec::new();
    for e in &cast.events {
        if !matches!(e.kind, 'o' | 'r') {
            continue;
        }
        match times.last() {
            Some(&last) if e.t - last < 0.03 => *times.last_mut().unwrap() = e.t,
            _ => times.push(e.t),
        }
    }
    if times.len() > max_frames && max_frames > 1 {
        let n = times.len();
        let picked: Vec<f64> = (0..max_frames).map(|i| times[i * (n - 1) / (max_frames - 1)]).collect();
        times = picked;
    }
    let opts = RenderOpts { theme, cursor: true, scrollback: false, title: None };
    let mut dict: Vec<String> = Vec::new();
    let mut index: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
    let mut frames: Vec<(f64, Vec<usize>)> = Vec::new();
    let mut term = Term::new(cast.cols, cast.rows);
    let mut ei = 0;
    let mut sizes: Vec<(usize, usize)> = Vec::new();
    // initial blank frame at t=0
    let mut snap = |term: &Term, t: f64, dict: &mut Vec<String>, frames: &mut Vec<(f64, Vec<usize>)>, sizes: &mut Vec<(usize, usize)>| {
        let rows = html_rows(&term.screen, &opts);
        let ids: Vec<usize> = rows
            .into_iter()
            .map(|r| {
                *index.entry(r.clone()).or_insert_with(|| {
                    dict.push(r);
                    dict.len() - 1
                })
            })
            .collect();
        if frames.last().map(|(_, f)| f == &ids).unwrap_or(false) && sizes.last() == Some(&(term.screen.cols, term.screen.rows)) {
            return;
        }
        frames.push((t, ids));
        sizes.push((term.screen.cols, term.screen.rows));
    };
    snap(&term, 0.0, &mut dict, &mut frames, &mut sizes);
    for &t in &times {
        while ei < cast.events.len() && cast.events[ei].t <= t {
            Cast::apply(&mut term, &cast.events[ei]);
            ei += 1;
        }
        term.take_output();
        snap(&term, t, &mut dict, &mut frames, &mut sizes);
    }
    let mut js_rows = String::from("[");
    for (i, r) in dict.iter().enumerate() {
        if i > 0 {
            js_rows.push(',');
        }
        json::write_str(r, &mut js_rows);
    }
    js_rows.push(']');
    let mut js_frames = String::from("[");
    for (i, (t, ids)) in frames.iter().enumerate() {
        if i > 0 {
            js_frames.push(',');
        }
        js_frames.push_str(&format!("[{:.3},[{}]]", t, ids.iter().map(|n| n.to_string()).collect::<Vec<_>>().join(",")));
    }
    js_frames.push(']');
    let title = cast.title.clone().unwrap_or_else(|| "cast".into());
    let title_html = title.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;");
    let css = html_css(theme);
    let duration = cast.duration();
    format!(
        r##"<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title_html} — cathode player</title>
<style>
{css}
.ctl{{display:flex;align-items:center;gap:10px;padding:9px 14px;font:12px/1 system-ui,sans-serif;color:var(--fg);background:color-mix(in srgb,var(--fg) 7%,var(--bg));border-top:1px solid rgba(128,128,128,.25)}}
.ctl button{{all:unset;cursor:pointer;padding:5px 10px;border-radius:6px;background:color-mix(in srgb,var(--fg) 14%,transparent)}}
.ctl button:hover,.ctl button:focus-visible{{background:color-mix(in srgb,var(--fg) 26%,transparent)}}
.ctl input[type=range]{{flex:1;accent-color:var(--c4)}}.ctl .tm{{min-width:9ch;text-align:right;font-variant-numeric:tabular-nums;opacity:.75}}
</style></head><body>
<div class="term"><div class="bar"><span class="dots"><i></i><i></i><i></i></span><span class="ttl">{title_html}</span><span class="sz" id="sz"></span></div>
<pre class="screen" id="scr" aria-live="off"></pre>
<div class="ctl"><button id="pp" aria-label="play or pause">▶ Play</button><input id="seek" type="range" min="0" max="0" value="0" aria-label="seek"><span class="tm" id="tm"></span><button id="sp" aria-label="playback speed">1×</button></div></div>
<script>
const ROWS={js_rows},FRAMES={js_frames},DUR={duration:.3},SIZE={{cols:{cols},rows:{rows}}};
const scr=document.getElementById('scr'),seek=document.getElementById('seek'),tm=document.getElementById('tm'),pp=document.getElementById('pp'),sp=document.getElementById('sp');
document.getElementById('sz').textContent=SIZE.cols+'×'+SIZE.rows;
let cur=-1,playing=false,speed=1,tStart=0,tBase=0,raf=0;
seek.max=FRAMES.length-1;
function show(i){{if(i===cur)return;cur=i;scr.innerHTML=FRAMES[i][1].map(n=>ROWS[n]).join('');seek.value=i;tm.textContent=FRAMES[i][0].toFixed(1)+' / '+DUR.toFixed(1)+'s';}}
function at(t){{let lo=0,hi=FRAMES.length-1;while(lo<hi){{const m=(lo+hi+1)>>1;if(FRAMES[m][0]<=t)lo=m;else hi=m-1;}}return lo;}}
function tick(now){{if(!playing)return;const t=tBase+(now-tStart)/1000*speed;if(t>=DUR){{show(FRAMES.length-1);stop();return;}}show(at(t));raf=requestAnimationFrame(tick);}}
function play(){{if(cur>=FRAMES.length-1)show(0);playing=true;pp.textContent='❚❚ Pause';tBase=FRAMES[cur][0];tStart=performance.now();raf=requestAnimationFrame(tick);}}
function stop(){{playing=false;pp.textContent=cur>=FRAMES.length-1?'↻ Replay':'▶ Play';cancelAnimationFrame(raf);}}
pp.onclick=()=>playing?stop():play();
seek.oninput=()=>{{const was=playing;if(was)stop();show(+seek.value);if(was)play();}};
sp.onclick=()=>{{speed=speed>=4?0.5:speed*2;sp.textContent=speed+'×';if(playing){{tBase=FRAMES[cur][0];tStart=performance.now();}}}};
addEventListener('keydown',e=>{{if(e.key===' '){{e.preventDefault();pp.click();}}else if(e.key==='ArrowRight'){{show(Math.min(cur+1,FRAMES.length-1));}}else if(e.key==='ArrowLeft'){{show(Math.max(cur-1,0));}}}});
show(FRAMES.length-1);stop();
</script></body></html>
"##,
        cols = cast.cols,
        rows = cast.rows,
    )
}
