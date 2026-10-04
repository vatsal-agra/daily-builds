//! Collapse animation: record frames while solving, emit a self-contained HTML flipbook.

use crate::png;

pub struct Recorder {
    pub frames: Vec<(usize, usize, Vec<u32>)>,
    every: usize,
    max_frames: usize,
    tick: usize,
}

impl Recorder {
    pub fn new(every: usize, max_frames: usize) -> Recorder {
        Recorder { frames: Vec::new(), every: every.max(1), max_frames: max_frames.max(2), tick: 0 }
    }
    /// Offer a state; `make` renders it lazily only if it is going to be kept.
    pub fn offer(&mut self, make: impl FnOnce() -> (usize, usize, Vec<u32>)) {
        if self.tick % self.every == 0 && self.frames.len() < self.max_frames - 1 {
            self.frames.push(make());
        }
        self.tick += 1;
    }
    /// Always keep the final frame.
    pub fn finish(&mut self, last: (usize, usize, Vec<u32>)) {
        self.frames.push(last);
    }
}

pub fn html(title: &str, info: &str, frames: &[(usize, usize, Vec<u32>)], scale: usize) -> String {
    let imgs: Vec<String> = frames
        .iter()
        .map(|(w, h, px)| format!("\"data:image/png;base64,{}\"", png::base64(&png::encode(*w, *h, px))))
        .collect();
    let w = frames.first().map(|f| f.0).unwrap_or(1);
    format!(
        r##"<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{--bg:#0f1117;--fg:#e6e8ee;--mut:#8b90a0;--acc:#7cf0c8;--card:#171a23}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;padding:24px}}
h1{{font-size:20px;margin:0 0 4px;letter-spacing:.04em}} .info{{color:var(--mut);margin-bottom:16px;font-size:13px}}
.stage{{background:var(--card);padding:12px;border-radius:12px;box-shadow:0 8px 30px #0008}}
img{{display:block;width:{iw}px;max-width:90vw;height:auto;image-rendering:pixelated}}
.bar{{display:flex;gap:12px;align-items:center;margin-top:16px;width:min({iw}px,90vw)}}
button{{background:var(--acc);color:#04130d;border:0;border-radius:8px;padding:6px 14px;font-weight:600;cursor:pointer}}
input[type=range]{{flex:1;accent-color:var(--acc)}} .n{{color:var(--mut);font-variant-numeric:tabular-nums;min-width:84px;text-align:right}}
</style></head><body>
<h1>{title}</h1><div class="info">{info}</div>
<div class="stage"><img id="f" alt="frame"></div>
<div class="bar"><button id="p">Pause</button><input id="s" type="range" min="0" max="{last}" value="0"><span class="n" id="n"></span></div>
<script>
const F=[{imgs}];let i=0,play=true;const im=document.getElementById('f'),sl=document.getElementById('s'),n=document.getElementById('n'),b=document.getElementById('p');
function show(k){{i=k;im.src=F[k];sl.value=k;n.textContent=(k+1)+' / '+F.length}}
b.onclick=()=>{{play=!play;b.textContent=play?'Pause':'Play';if(play&&i==F.length-1)i=0}};
sl.oninput=()=>{{play=false;b.textContent='Play';show(+sl.value)}};
show(0);setInterval(()=>{{if(play){{if(i<F.length-1)show(i+1);else{{play=false;b.textContent='Replay'}}}}}},60);
</script></body></html>"##,
        title = title,
        info = info,
        iw = w * scale,
        last = frames.len().saturating_sub(1),
        imgs = imgs.join(",")
    )
}
