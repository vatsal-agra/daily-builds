"""Self-contained HTML visualizer generator.

Produces a single .html file with:
  - Embedded WAV audio as base64 (plays in the browser via <audio>)
  - Canvas: time-domain waveform of the first ~4 seconds
  - Canvas: FFT magnitude spectrum (log frequency, 20-8000 Hz)
  - SVG: piano roll (step grid with colored note blocks per track)
  - Track legend and sequence metadata
"""

import base64
import math
import json
from typing import Optional

from .fft import spectrum_bands
from .sequencer import Sequence


def _to_db(mag: float) -> float:
    """Magnitude to dB, clamped at -60 dB floor."""
    if mag < 1e-7:
        return -60.0
    return max(-60.0, 20.0 * math.log10(mag))


def generate_html(
    wav_bytes: bytes,
    seq: Optional[Sequence],
    left_samples: list,
    title: str = "Cadence",
) -> str:
    """Build the complete HTML string."""

    # ---- Audio base64 ----
    audio_b64 = base64.b64encode(wav_bytes).decode('ascii')

    # ---- Waveform data (downsample to ~2000 points for 4 seconds) ----
    sr = 44100
    wave_window = min(len(left_samples), sr * 4)
    wave_n = 1200
    step = max(1, wave_window // wave_n)
    wave_data = [left_samples[i * step] for i in range(min(wave_n, wave_window // step))]

    # ---- Spectrum data ----
    spec_n = 120
    spec_window = left_samples[:4096] if len(left_samples) >= 4096 else left_samples
    bands = spectrum_bands(spec_window, sr, n_bins=spec_n, f_min=20.0, f_max=8000.0)
    spec_freqs = [b[0] for b in bands]
    spec_mags_db = [_to_db(b[1]) for b in bands]

    # ---- Piano roll data ----
    piano_roll_json = "null"
    if seq is not None:
        track_colors = [
            '#4FC3F7', '#81C784', '#FFB74D', '#E57373',
            '#BA68C8', '#4DB6AC', '#F06292', '#AED581',
        ]
        pr_tracks = []
        for ti, track in enumerate(seq.tracks):
            color = track_colors[ti % len(track_colors)]
            tr_notes = []
            for evt in track.notes:
                if track.is_drum:
                    tr_notes.append({
                        'step': evt.step,
                        'gate': evt.gate,
                        'pitch': 0,
                        'velocity': evt.velocity,
                        'kind': evt.kind,
                    })
                else:
                    tr_notes.append({
                        'step': evt.step,
                        'gate': evt.gate,
                        'pitch': evt.pitch,
                        'velocity': evt.velocity,
                        'kind': '',
                    })
            pr_tracks.append({
                'name': track.name,
                'color': color,
                'is_drum': track.is_drum,
                'notes': tr_notes,
            })

        pr_meta = {
            'total_steps': seq.total_steps,
            'steps_per_bar': seq.steps_per_bar,
            'bars': seq.bars,
            'bpm': seq.bpm,
        }
        piano_roll_json = json.dumps({'meta': pr_meta, 'tracks': pr_tracks})

    wave_json = json.dumps(wave_data)
    freq_json = json.dumps(spec_freqs)
    mags_json = json.dumps(spec_mags_db)

    meta_str = ""
    if seq is not None:
        meta_str = f"{seq.bpm:.0f} BPM · {seq.bars} bars · {len(seq.tracks)} tracks"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --bg: #0f0f13;
    --panel: #1a1a22;
    --border: #2d2d3d;
    --accent: #4FC3F7;
    --text: #e0e0f0;
    --sub: #8080a0;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg); color: var(--text);
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 14px; padding: 24px;
  }}
  h1 {{ font-size: 1.6rem; color: var(--accent); margin-bottom: 4px; letter-spacing: 0.04em; }}
  .meta {{ color: var(--sub); margin-bottom: 24px; font-size: 0.85rem; }}
  .panel {{
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px; margin-bottom: 20px;
  }}
  .panel h2 {{
    font-size: 0.8rem; font-weight: 600; letter-spacing: 0.1em;
    text-transform: uppercase; color: var(--sub); margin-bottom: 12px;
  }}
  canvas {{ display: block; width: 100%; border-radius: 4px; }}
  audio {{
    width: 100%; margin-bottom: 20px;
    filter: invert(1) hue-rotate(180deg); border-radius: 30px;
  }}
  .legend {{
    display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px;
  }}
  .legend-item {{
    display: flex; align-items: center; gap: 6px;
    font-size: 0.8rem; color: var(--sub);
  }}
  .legend-dot {{
    width: 10px; height: 10px; border-radius: 2px;
  }}
  #piano-roll-container {{ overflow-x: auto; }}
</style>
</head>
<body>
<h1>♩ {title}</h1>
<div class="meta">{meta_str}</div>

<audio controls src="data:audio/wav;base64,{audio_b64}"></audio>

<div class="panel">
  <h2>Waveform — first 4 seconds</h2>
  <canvas id="waveCanvas" height="100"></canvas>
</div>

<div class="panel">
  <h2>Frequency Spectrum (log scale, 20 Hz – 8 kHz)</h2>
  <canvas id="specCanvas" height="160"></canvas>
</div>

<div class="panel" id="piano-roll-container">
  <h2>Piano Roll</h2>
  <canvas id="rollCanvas" height="200"></canvas>
  <div class="legend" id="legend"></div>
</div>

<script>
(function() {{
  const waveData = {wave_json};
  const specFreqs = {freq_json};
  const specMags  = {mags_json};
  const prData    = {piano_roll_json};

  // ---- helpers ----
  function dpr() {{ return window.devicePixelRatio || 1; }}
  function setupCanvas(canvas) {{
    const rect = canvas.getBoundingClientRect();
    const r = dpr();
    canvas.width  = rect.width  * r;
    canvas.height = rect.height * r;
    const ctx = canvas.getContext('2d');
    ctx.scale(r, r);
    return {{ ctx, w: rect.width, h: rect.height }};
  }}

  // ---- Waveform ----
  function drawWave() {{
    const canvas = document.getElementById('waveCanvas');
    const {{ ctx, w, h }} = setupCanvas(canvas);
    ctx.fillStyle = '#0f0f13';
    ctx.fillRect(0, 0, w, h);

    const mid = h / 2;
    // Grid line
    ctx.strokeStyle = '#1e1e2e';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, mid); ctx.lineTo(w, mid); ctx.stroke();

    const n = waveData.length;
    const gradient = ctx.createLinearGradient(0, 0, w, 0);
    gradient.addColorStop(0, '#4FC3F7');
    gradient.addColorStop(0.5, '#81C784');
    gradient.addColorStop(1, '#4FC3F7');
    ctx.strokeStyle = gradient;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < n; i++) {{
      const x = (i / n) * w;
      const y = mid - waveData[i] * (mid - 4);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }}
    ctx.stroke();
  }}

  // ---- Spectrum ----
  function drawSpectrum() {{
    const canvas = document.getElementById('specCanvas');
    const {{ ctx, w, h }} = setupCanvas(canvas);
    ctx.fillStyle = '#0f0f13';
    ctx.fillRect(0, 0, w, h);

    const n = specMags.length;
    const minDb = -60, maxDb = 0;
    const barW = w / n;

    for (let i = 0; i < n; i++) {{
      const db = specMags[i];
      const norm = (db - minDb) / (maxDb - minDb);
      const barH = Math.max(1, norm * (h - 20));
      const hue = 200 + norm * 80;
      ctx.fillStyle = `hsl(${{hue}}, 80%, 55%)`;
      ctx.fillRect(i * barW, h - barH - 10, barW - 0.5, barH);
    }}

    // dB labels
    ctx.fillStyle = '#8080a0';
    ctx.font = '10px monospace';
    for (const db of [-60, -40, -20, 0]) {{
      const y = h - 10 - ((db - minDb) / (maxDb - minDb)) * (h - 20);
      ctx.fillText(db + ' dB', 4, y);
    }}

    // Frequency labels
    const freqLabels = [50, 100, 200, 500, 1000, 2000, 4000, 8000];
    const logMin = Math.log10(20), logMax = Math.log10(8000);
    ctx.fillStyle = '#8080a0';
    ctx.font = '9px monospace';
    for (const f of freqLabels) {{
      const x = ((Math.log10(f) - logMin) / (logMax - logMin)) * w;
      const label = f >= 1000 ? (f/1000) + 'k' : f;
      ctx.fillText(label, x - 8, h - 1);
    }}
  }}

  // ---- Piano Roll ----
  function drawPianoRoll() {{
    if (!prData) return;
    const {{ meta, tracks }} = prData;
    const canvas = document.getElementById('rollCanvas');
    const h = canvas.height || 200;

    // Compute pitch range across all non-drum tracks
    let minPitch = 127, maxPitch = 0;
    for (const t of tracks) {{
      if (t.is_drum) continue;
      for (const n of t.notes) {{
        if (n.pitch < minPitch) minPitch = n.pitch;
        if (n.pitch > maxPitch) maxPitch = n.pitch;
      }}
    }}
    if (minPitch > maxPitch) {{ minPitch = 48; maxPitch = 84; }}
    minPitch = Math.max(0, minPitch - 2);
    maxPitch = Math.min(127, maxPitch + 2);
    const pitchRange = maxPitch - minPitch + 1;

    const totalSteps = meta.total_steps;
    const rollW = Math.max(canvas.parentElement.clientWidth - 32, 600);
    canvas.width = rollW * dpr();
    canvas.height = h * dpr();
    canvas.style.width = rollW + 'px';
    canvas.style.height = h + 'px';
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr(), dpr());
    const w = rollW;

    ctx.fillStyle = '#0f0f13';
    ctx.fillRect(0, 0, w, h);

    // Bar grid lines
    ctx.strokeStyle = '#2d2d3d';
    ctx.lineWidth = 1;
    for (let bar = 0; bar <= meta.bars; bar++) {{
      const x = (bar * meta.steps_per_bar / totalSteps) * w;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    }}

    // Beat grid (lighter)
    ctx.strokeStyle = '#1a1a25';
    for (let step = 0; step < totalSteps; step += 4) {{
      const x = (step / totalSteps) * w;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    }}

    const DRUM_H = 20;
    const drumTracks = tracks.filter(t => t.is_drum);
    const melodicH = h - drumTracks.length * DRUM_H;

    // Draw melodic notes
    for (const t of tracks) {{
      if (t.is_drum) continue;
      for (const n of t.notes) {{
        const x = (n.step / totalSteps) * w;
        const noteW = Math.max(2, (n.gate / totalSteps) * w - 1);
        const pitchNorm = (n.pitch - minPitch) / pitchRange;
        const y = melodicH - pitchNorm * melodicH - 4;
        const noteH = Math.max(3, melodicH / pitchRange - 1);
        const alpha = 0.5 + 0.5 * (n.velocity / 127);
        ctx.fillStyle = t.color;
        ctx.globalAlpha = alpha;
        ctx.beginPath();
        ctx.roundRect(x, y, noteW, noteH, 1);
        ctx.fill();
        ctx.globalAlpha = 1;
      }}
    }}

    // Draw drum rows
    const drumKinds = ['kick', 'snare', 'hihat', 'open_hihat', 'clap'];
    const drumColors = {{ kick: '#E57373', snare: '#FFB74D', hihat: '#81C784',
                          open_hihat: '#4FC3F7', clap: '#BA68C8' }};
    for (const t of tracks) {{
      if (!t.is_drum) continue;
      for (const n of t.notes) {{
        const x = (n.step / totalSteps) * w;
        const noteW = Math.max(3, (1 / totalSteps) * w - 1);
        const rowIdx = drumKinds.indexOf(n.kind);
        const y = melodicH + rowIdx * DRUM_H + 2;
        const alpha = 0.4 + 0.6 * (n.velocity / 127);
        ctx.fillStyle = drumColors[n.kind] || '#aaa';
        ctx.globalAlpha = alpha;
        ctx.fillRect(x, y, noteW, DRUM_H - 4);
        ctx.globalAlpha = 1;
      }}

      // Row labels
      ctx.fillStyle = '#8080a0';
      ctx.font = '9px monospace';
      for (let ri = 0; ri < drumKinds.length; ri++) {{
        ctx.fillText(drumKinds[ri], 4, melodicH + ri * DRUM_H + 13);
      }}
    }}

    // Bar numbers
    ctx.fillStyle = '#8080a0';
    ctx.font = '9px monospace';
    for (let bar = 0; bar < meta.bars; bar++) {{
      const x = (bar * meta.steps_per_bar / totalSteps) * w + 3;
      ctx.fillText('Bar ' + (bar + 1), x, 10);
    }}

    // Legend
    const legend = document.getElementById('legend');
    legend.innerHTML = '';
    for (const t of tracks) {{
      const item = document.createElement('div');
      item.className = 'legend-item';
      const dot = document.createElement('div');
      dot.className = 'legend-dot';
      dot.style.background = t.color || '#888';
      item.appendChild(dot);
      item.appendChild(document.createTextNode(t.name));
      legend.appendChild(item);
    }}
  }}

  // ---- Init ----
  window.addEventListener('load', () => {{
    drawWave();
    drawSpectrum();
    drawPianoRoll();
  }});
  window.addEventListener('resize', () => {{
    drawWave();
    drawSpectrum();
    drawPianoRoll();
  }});
}})();
</script>
</body>
</html>
"""
    return html
