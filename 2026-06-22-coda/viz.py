"""Piano roll HTML visualizer — self-contained single-file HTML with Web
Audio API playback synthesized entirely in the browser."""

import json
from midi import MidiFile, MidiEvent, NoteOn, NoteOff, TempoChange, TrackName
from renderer import build_tempo_map

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
TRACK_COLORS = [
    "#4fc3f7", "#81c784", "#ffb74d", "#f48fb1", "#ce93d8",
    "#80cbc4", "#fff176", "#ff8a65", "#a5d6a7", "#90caf9",
]


def midi_note_name(note: int) -> str:
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"


def extract_note_events(midi: MidiFile):
    """Extract note events with absolute times in seconds."""
    tempo_map = build_tempo_map(midi)
    tracks_data = []

    for track_idx, track in enumerate(midi.tracks):
        notes = []
        active: dict[tuple[int, int], tuple[int, float]] = {}
        track_name = f"Track {track_idx}"

        for ev in sorted(track.events, key=lambda e: e.tick):
            if isinstance(ev.event, TrackName):
                track_name = ev.event.name

        for ev in sorted(track.events, key=lambda e: e.tick):
            t_sec = tempo_map.tick_to_seconds(ev.tick)
            if isinstance(ev.event, NoteOn):
                key = (ev.event.channel, ev.event.note)
                active[key] = (ev.event.velocity, t_sec)
            elif isinstance(ev.event, NoteOff):
                key = (ev.event.channel, ev.event.note)
                if key in active:
                    vel, start_t = active.pop(key)
                    dur = max(0.05, t_sec - start_t)
                    notes.append({
                        "note": ev.event.note,
                        "name": midi_note_name(ev.event.note),
                        "start": round(start_t, 4),
                        "dur": round(dur, 4),
                        "vel": vel,
                        "ch": key[0],
                    })

        # Flush held notes
        for (ch, note), (vel, start_t) in active.items():
            notes.append({
                "note": note,
                "name": midi_note_name(note),
                "start": round(start_t, 4),
                "dur": 0.25,
                "vel": vel,
                "ch": ch,
            })

        if notes:
            tracks_data.append({"name": track_name, "notes": notes})

    return tracks_data


def generate_html(midi: MidiFile, title: str = "Coda — Piano Roll") -> str:
    """Generate a self-contained HTML piano roll visualizer."""
    tracks_data = extract_note_events(midi)
    data_json = json.dumps(tracks_data)

    total_duration = max(
        (n["start"] + n["dur"] for td in tracks_data for n in td["notes"]),
        default=1.0,
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #1a1a2e; color: #e0e0e0; font-family: 'Segoe UI', sans-serif;
       font-size: 13px; overflow: hidden; }}

#app {{ display: flex; flex-direction: column; height: 100vh; width: 100vw; }}

/* ── Header ── */
#header {{ background: #16213e; padding: 10px 16px; display: flex; align-items: center;
           gap: 16px; border-bottom: 1px solid #0f3460; flex-shrink: 0; }}
#title {{ font-size: 16px; font-weight: 700; color: #4fc3f7; }}
.btn {{ background: #0f3460; border: 1px solid #4fc3f7; color: #4fc3f7;
        padding: 5px 14px; border-radius: 4px; cursor: pointer; font-size: 12px;
        transition: background 0.15s; }}
.btn:hover {{ background: #1a5276; }}
.btn.active {{ background: #4fc3f7; color: #16213e; }}
#time-display {{ margin-left: auto; color: #90caf9; font-size: 12px; min-width: 80px; }}
#bpm-label {{ color: #aaa; font-size: 11px; }}
input[type=range] {{ accent-color: #4fc3f7; }}

/* ── Legend ── */
#legend {{ background: #16213e; padding: 6px 16px; display: flex; gap: 16px;
           flex-wrap: wrap; border-bottom: 1px solid #0f3460; flex-shrink: 0; }}
.legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 11px; }}
.legend-swatch {{ width: 14px; height: 10px; border-radius: 2px; }}

/* ── Piano Roll Container ── */
#roll-wrapper {{ flex: 1; display: flex; overflow: hidden; position: relative; }}

/* ── Piano keyboard on left ── */
#piano {{ width: 48px; flex-shrink: 0; background: #111; overflow: hidden;
          position: relative; border-right: 1px solid #333; }}
#piano canvas {{ display: block; }}

/* ── Roll canvas ── */
#roll-scroll {{ flex: 1; overflow-x: auto; overflow-y: hidden; position: relative; }}
#roll-canvas {{ display: block; cursor: pointer; }}

/* ── Playhead ── */
#playhead {{ position: absolute; top: 0; bottom: 0; width: 2px;
             background: rgba(255,255,100,0.9); pointer-events: none;
             left: 0; z-index: 10; }}

/* ── Tooltip ── */
#tooltip {{ position: fixed; background: rgba(0,0,0,0.85); color: #fff;
            padding: 5px 10px; border-radius: 4px; font-size: 11px;
            pointer-events: none; display: none; z-index: 100;
            border: 1px solid #4fc3f7; }}

/* ── Zoom controls ── */
#zoom-bar {{ background: #16213e; padding: 6px 16px; display: flex; align-items: center;
             gap: 12px; border-top: 1px solid #0f3460; flex-shrink: 0; }}
#zoom-bar label {{ font-size: 11px; color: #aaa; }}
</style>
</head>
<body>
<div id="app">
  <div id="header">
    <span id="title">{title}</span>
    <button class="btn" id="btn-play" onclick="togglePlay()">▶ Play</button>
    <button class="btn" onclick="stopAudio()">■ Stop</button>
    <label id="bpm-label">Tempo: —</label>
    <span id="time-display">0:00 / {int(total_duration//60)}:{int(total_duration%60):02d}</span>
  </div>

  <div id="legend"></div>

  <div id="roll-wrapper">
    <div id="piano"><canvas id="piano-canvas"></canvas></div>
    <div id="roll-scroll">
      <canvas id="roll-canvas"></canvas>
      <div id="playhead"></div>
    </div>
  </div>

  <div id="zoom-bar">
    <label>Horizontal zoom:</label>
    <input type="range" id="zoom-x" min="50" max="600" value="150"
           oninput="setZoomX(this.value)">
    <label>Vertical zoom:</label>
    <input type="range" id="zoom-y" min="4" max="20" value="8"
           oninput="setZoomY(this.value)">
    <span style="color:#aaa;font-size:11px;margin-left:8px">
      Click on the roll to seek. Hover notes for details.
    </span>
  </div>
</div>

<div id="tooltip"></div>

<script>
// ── Data ────────────────────────────────────────────────────────────────────
const TRACKS = {data_json};
const TOTAL_DURATION = {total_duration:.4f};
const COLORS = {json.dumps(TRACK_COLORS)};

// ── Config ────────────────────────────────────────────────────────────────────
let pxPerSec = 150;
let rowH = 8;
const NOTE_MIN = 0, NOTE_MAX = 127;
const PIANO_W = 48;
const NOTE_NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"];

// ── Canvas setup ───────────────────────────────────────────────────────────
const rollCanvas = document.getElementById('roll-canvas');
const rollCtx = rollCanvas.getContext('2d');
const pianoCanvas = document.getElementById('piano-canvas');
const pianoCtx = pianoCanvas.getContext('2d');
const rollScroll = document.getElementById('roll-scroll');

function totalRows() {{ return NOTE_MAX - NOTE_MIN + 1; }}
function canvasH() {{ return totalRows() * rowH; }}
function canvasW() {{ return Math.ceil(TOTAL_DURATION * pxPerSec) + 60; }}

function setZoomX(v) {{
  pxPerSec = parseInt(v);
  draw();
}}
function setZoomY(v) {{
  rowH = parseInt(v);
  draw();
  drawPiano();
}}

function noteY(note) {{
  return (NOTE_MAX - note) * rowH;
}}

// ── Draw piano keyboard ─────────────────────────────────────────────────────
function drawPiano() {{
  const h = canvasH();
  pianoCanvas.width = PIANO_W;
  pianoCanvas.height = h;
  pianoCanvas.style.height = h + 'px';

  for (let note = NOTE_MIN; note <= NOTE_MAX; note++) {{
    const y = noteY(note);
    const isBlack = [1,3,6,8,10].includes(note % 12);
    pianoCtx.fillStyle = isBlack ? '#222' : '#ddd';
    pianoCtx.fillRect(0, y, PIANO_W, rowH);
    pianoCtx.strokeStyle = '#555';
    pianoCtx.strokeRect(0, y, PIANO_W, rowH);

    if (note % 12 === 0 && rowH >= 8) {{
      pianoCtx.fillStyle = isBlack ? '#aaa' : '#333';
      pianoCtx.font = `${{Math.max(7, rowH - 2)}}px monospace`;
      pianoCtx.fillText(`C${{Math.floor(note/12)-1}}`, 2, y + rowH - 2);
    }}
  }}
}}

// ── Draw roll ─────────────────────────────────────────────────────────────
function draw() {{
  const w = canvasW();
  const h = canvasH();
  rollCanvas.width = w;
  rollCanvas.height = h;
  rollCanvas.style.height = h + 'px';

  // Background
  rollCtx.fillStyle = '#1e1e2e';
  rollCtx.fillRect(0, 0, w, h);

  // Grid lines
  for (let note = NOTE_MIN; note <= NOTE_MAX; note++) {{
    const y = noteY(note);
    const isBlack = [1,3,6,8,10].includes(note % 12);
    if (isBlack) {{
      rollCtx.fillStyle = 'rgba(0,0,0,0.25)';
      rollCtx.fillRect(0, y, w, rowH);
    }}
    if (note % 12 === 0) {{
      rollCtx.strokeStyle = 'rgba(255,255,255,0.06)';
      rollCtx.beginPath();
      rollCtx.moveTo(0, y);
      rollCtx.lineTo(w, y);
      rollCtx.stroke();
    }}
  }}

  // Vertical beat lines (approximate with 0.5s grid)
  rollCtx.strokeStyle = 'rgba(255,255,255,0.05)';
  for (let t = 0; t <= TOTAL_DURATION; t += 0.5) {{
    const x = t * pxPerSec;
    rollCtx.beginPath();
    rollCtx.moveTo(x, 0);
    rollCtx.lineTo(x, h);
    rollCtx.stroke();
  }}
  // Stronger lines every 2 seconds
  rollCtx.strokeStyle = 'rgba(255,255,255,0.12)';
  for (let t = 0; t <= TOTAL_DURATION; t += 2) {{
    const x = t * pxPerSec;
    rollCtx.beginPath();
    rollCtx.moveTo(x, 0);
    rollCtx.lineTo(x, h);
    rollCtx.stroke();
  }}

  // Notes
  TRACKS.forEach((track, ti) => {{
    const color = COLORS[ti % COLORS.length];
    track.notes.forEach(n => {{
      const x = n.start * pxPerSec;
      const y = noteY(n.note);
      const nw = Math.max(2, n.dur * pxPerSec - 1);
      const alpha = 0.5 + (n.vel / 127) * 0.5;
      rollCtx.fillStyle = color;
      rollCtx.globalAlpha = alpha;
      rollCtx.fillRect(x, y + 1, nw, Math.max(2, rowH - 2));
      // Bright top edge
      rollCtx.globalAlpha = 1.0;
      rollCtx.fillStyle = 'rgba(255,255,255,0.3)';
      rollCtx.fillRect(x, y + 1, nw, 1);
    }});
  }});
  rollCtx.globalAlpha = 1.0;
}}

// ── Legend ───────────────────────────────────────────────────────────────
function buildLegend() {{
  const leg = document.getElementById('legend');
  leg.innerHTML = '';
  TRACKS.forEach((t, i) => {{
    const color = COLORS[i % COLORS.length];
    const item = document.createElement('div');
    item.className = 'legend-item';
    item.innerHTML = `<div class="legend-swatch" style="background:${{color}}"></div><span>${{t.name}}</span>`;
    leg.appendChild(item);
  }});
}}

// ── Tooltip ───────────────────────────────────────────────────────────────
const tooltip = document.getElementById('tooltip');

rollCanvas.addEventListener('mousemove', (e) => {{
  const rect = rollCanvas.getBoundingClientRect();
  const mx = e.clientX - rect.left + rollScroll.scrollLeft;
  const my = e.clientY - rect.top;
  const t = mx / pxPerSec;
  const note = NOTE_MAX - Math.floor(my / rowH);

  // Find a note under cursor
  let found = null;
  outer: for (const track of TRACKS) {{
    for (const n of track.notes) {{
      if (n.note === note && t >= n.start && t <= n.start + n.dur) {{
        found = {{ ...n, trackName: track.name }};
        break outer;
      }}
    }}
  }}

  if (found) {{
    tooltip.style.display = 'block';
    tooltip.style.left = (e.clientX + 14) + 'px';
    tooltip.style.top = (e.clientY - 10) + 'px';
    tooltip.innerHTML =
      `<b>${{found.name}}</b> (MIDI ${{found.note}})<br>` +
      `Track: ${{found.trackName}} · Ch ${{found.ch}}<br>` +
      `Start: ${{found.start.toFixed(2)}}s · Dur: ${{found.dur.toFixed(2)}}s<br>` +
      `Velocity: ${{found.vel}}`;
  }} else {{
    tooltip.style.display = 'none';
  }}
}});
rollCanvas.addEventListener('mouseleave', () => {{ tooltip.style.display = 'none'; }});

// ── Seek on click ─────────────────────────────────────────────────────────
rollCanvas.addEventListener('click', (e) => {{
  const rect = rollCanvas.getBoundingClientRect();
  const mx = e.clientX - rect.left + rollScroll.scrollLeft;
  seekTime = mx / pxPerSec;
  if (isPlaying) {{
    stopAudio();
    startAudio(seekTime);
  }} else {{
    updatePlayhead(seekTime);
  }}
}});

// ── Playhead ──────────────────────────────────────────────────────────────
const playheadEl = document.getElementById('playhead');
let seekTime = 0;

function updatePlayhead(t) {{
  const x = t * pxPerSec;
  playheadEl.style.left = x + 'px';
  // Auto-scroll
  const scrollW = rollScroll.clientWidth;
  if (x < rollScroll.scrollLeft || x > rollScroll.scrollLeft + scrollW - 40) {{
    rollScroll.scrollLeft = Math.max(0, x - scrollW * 0.3);
  }}
  // Update time display
  const totalSec = TOTAL_DURATION;
  const mm = Math.floor(t / 60);
  const ss = Math.floor(t % 60);
  const totalMM = Math.floor(totalSec / 60);
  const totalSS = Math.floor(totalSec % 60);
  document.getElementById('time-display').textContent =
    `${{mm}}:${{String(ss).padStart(2,'0')}} / ${{totalMM}}:${{String(totalSS).padStart(2,'0')}}`;
}}

// ── Web Audio Playback ────────────────────────────────────────────────────
let audioCtx = null;
let isPlaying = false;
let scheduledNodes = [];
let playStartWallClock = 0;
let playStartOffset = 0;
let animFrame = null;

function getAudioCtx() {{
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return audioCtx;
}}

function togglePlay() {{
  if (isPlaying) {{ stopAudio(); }}
  else {{ startAudio(seekTime); }}
}}

function stopAudio() {{
  isPlaying = false;
  document.getElementById('btn-play').textContent = '▶ Play';
  scheduledNodes.forEach(n => {{ try {{ n.stop(); }} catch(e) {{}} }});
  scheduledNodes = [];
  if (animFrame) {{ cancelAnimationFrame(animFrame); animFrame = null; }}
}}

function startAudio(offset) {{
  const ctx = getAudioCtx();
  if (ctx.state === 'suspended') ctx.resume();
  isPlaying = true;
  document.getElementById('btn-play').textContent = '⏸ Pause';
  playStartWallClock = ctx.currentTime;
  playStartOffset = offset;

  // Schedule all notes
  TRACKS.forEach((track, ti) => {{
    const isMelody = ti === 1;
    const isChords = ti === 2;
    const isBass = ti === 3;
    const isDrum = ti === 4;

    track.notes.forEach(n => {{
      const noteStart = n.start - offset;
      if (noteStart + n.dur < 0) return;
      const when = ctx.currentTime + Math.max(0, noteStart);
      const dur = n.dur;

      const osc = ctx.createOscillator();
      const env = ctx.createGain();
      const master = ctx.createGain();
      master.gain.value = isDrum ? 0.4 : (isChords ? 0.25 : (isBass ? 0.5 : 0.45));

      // Waveform selection by track role
      if (isDrum) {{
        // Use noise-like buffer for drums
        const frames = ctx.sampleRate * 0.3;
        const buffer = ctx.createBuffer(1, frames, ctx.sampleRate);
        const data = buffer.getChannelData(0);
        for (let i = 0; i < frames; i++) data[i] = (Math.random() * 2 - 1) * Math.exp(-i / (frames * 0.15));
        const src = ctx.createBufferSource();
        src.buffer = buffer;
        src.connect(env);
        env.connect(master);
        master.connect(ctx.destination);
        env.gain.setValueAtTime(n.vel / 127, when);
        env.gain.exponentialRampToValueAtTime(0.001, when + Math.min(dur, 0.3));
        src.start(when);
        src.stop(when + Math.min(dur, 0.3) + 0.05);
        scheduledNodes.push(src);
        return;
      }}

      if (isBass) {{
        osc.type = 'sine';
      }} else if (isChords) {{
        osc.type = 'triangle';
      }} else {{
        osc.type = 'sine';
      }}
      const freq = 440 * Math.pow(2, (n.note - 69) / 12);
      osc.frequency.value = freq;

      osc.connect(env);
      env.connect(master);
      master.connect(ctx.destination);

      // ADSR
      const atk = isBass ? 0.01 : (isChords ? 0.15 : 0.01);
      const rel = isChords ? 0.3 : 0.1;
      env.gain.setValueAtTime(0.001, when);
      env.gain.linearRampToValueAtTime(n.vel / 127, when + atk);
      env.gain.setValueAtTime(n.vel / 127, when + Math.max(atk, dur - rel));
      env.gain.linearRampToValueAtTime(0.001, when + dur + 0.01);

      osc.start(when);
      osc.stop(when + dur + 0.15);
      scheduledNodes.push(osc);
    }});
  }});

  // Animate playhead
  function animLoop() {{
    if (!isPlaying) return;
    const ctx2 = getAudioCtx();
    const elapsed = ctx2.currentTime - playStartWallClock;
    const t = playStartOffset + elapsed;
    updatePlayhead(t);
    if (t >= TOTAL_DURATION) {{
      stopAudio();
      seekTime = 0;
      updatePlayhead(0);
      return;
    }}
    animFrame = requestAnimationFrame(animLoop);
  }}
  animLoop();
}}

// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {{
  draw();
  drawPiano();
  buildLegend();
  updatePlayhead(0);
}});

// Sync piano height with roll
new MutationObserver(() => {{
  pianoCanvas.style.height = rollCanvas.style.height;
  document.getElementById('piano').style.height = rollCanvas.style.height;
}}).observe(rollCanvas, {{ attributes: true, attributeFilter: ['style'] }});

window.addEventListener('resize', () => {{ draw(); drawPiano(); }});
</script>
</body>
</html>"""

    return html


def write_html(midi: MidiFile, path: str, title: str = "Coda — Piano Roll"):
    """Generate and write the visualizer HTML to a file."""
    html = generate_html(midi, title)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return len(html)
