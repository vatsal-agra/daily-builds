// Browser step-sequencer UI. Uses the same dsp.js/sequencer.js engine that
// powers the Node CLI — this file only wires it up to the DOM and to
// Web Audio for playback (playback = feed the rendered Float32Array into
// an AudioBuffer, no Web Audio synthesis nodes involved).
'use strict';

const STEP_COUNT = 16;
const VELOCITY_LEVELS = [0, 0.6, 0.85, 1.0]; // index 0 = off

let audioCtx = null;
let currentSource = null;
let trackIdCounter = 0;

const state = {
  bpm: 100,
  swing: 0.08,
  effects: {
    delay: { enabled: false, time: 0.19, feedback: 0.35, mix: 0.22 },
    reverb: { enabled: false, mix: 0.18 },
  },
  tracks: [],
};

function newTrack(presetKey) {
  const preset = Waveforge.PRESETS[presetKey];
  trackIdCounter += 1;
  return {
    id: trackIdCounter,
    name: preset.name,
    presetKey,
    patch: JSON.parse(JSON.stringify(preset)),
    note: presetKey === 'kick' ? 36 : presetKey === 'snare' ? 38 : presetKey === 'hat' ? 42 : 60,
    steps: new Array(STEP_COUNT).fill(0),
    muted: false,
  };
}

function defaultTracks() {
  return ['kick', 'snare', 'hat', 'bass'].map(newTrack);
}

// A step in state.tracks[].steps is either a plain number (velocity, the
// common case for steps programmed directly in the UI) or, for steps that
// carry a sustain length imported from an external pattern (e.g. the demo
// song's pad track), an object { velocity, hold }. These helpers let every
// call site treat both shapes uniformly.
function stepVelocity(step) {
  return typeof step === 'object' && step !== null ? step.velocity : (step || 0);
}
function stepHold(step) {
  return typeof step === 'object' && step !== null ? step.hold : undefined;
}
function nearestVelocityLevel(v) {
  return VELOCITY_LEVELS.reduce((best, lvl) => (Math.abs(lvl - v) < Math.abs(best - v) ? lvl : best));
}

function buildPattern() {
  return {
    bpm: state.bpm,
    stepsPerBeat: 4,
    swing: state.swing,
    effects: state.effects,
    tracks: state.tracks
      .filter((tr) => !tr.muted)
      .map((tr) => ({
        name: tr.name,
        patch: tr.patch,
        note: tr.note,
        steps: tr.steps.map((step) => {
          const velocity = stepVelocity(step);
          if (velocity <= 0) return null;
          const hold = stepHold(step);
          return hold != null ? { on: true, velocity, hold } : { on: true, velocity };
        }),
      })),
  };
}

function setStatus(msg) {
  document.getElementById('statusLine').textContent = msg;
  if (msg) setTimeout(() => {
    const el = document.getElementById('statusLine');
    if (el.textContent === msg) el.textContent = '';
  }, 4000);
}

// ---------------------------------------------------------------------------
// Rendering the track UI
// ---------------------------------------------------------------------------

function renderTracks() {
  const container = document.getElementById('tracksContainer');
  container.innerHTML = '';
  if (state.tracks.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty-hint';
    empty.textContent = 'No tracks yet — click "+ Add track" to start programming a beat.';
    container.appendChild(empty);
    return;
  }
  state.tracks.forEach((track) => container.appendChild(buildTrackRow(track)));
}

function buildTrackRow(track) {
  const row = document.createElement('div');
  row.className = 'track-row';
  if (track.muted) row.classList.add('muted');

  // -- header: name, preset select, mute, save/load, remove --
  const header = document.createElement('div');
  header.className = 'track-header';

  const nameInput = document.createElement('input');
  nameInput.className = 'track-name';
  nameInput.value = track.name;
  nameInput.addEventListener('input', () => { track.name = nameInput.value || track.name; });
  header.appendChild(nameInput);

  const presetSelect = document.createElement('select');
  presetSelect.className = 'preset-select';
  if (!track.presetKey) {
    // patch came from a loaded file or a custom import, not a built-in
    // preset — show that plainly instead of letting the select silently
    // point at whichever preset happens to be first in the list.
    const customOpt = document.createElement('option');
    customOpt.value = '';
    customOpt.textContent = 'Custom (loaded)';
    customOpt.selected = true;
    presetSelect.appendChild(customOpt);
  }
  Object.keys(Waveforge.PRESETS).forEach((key) => {
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = Waveforge.PRESETS[key].name;
    if (key === track.presetKey) opt.selected = true;
    presetSelect.appendChild(opt);
  });
  presetSelect.addEventListener('change', () => {
    track.presetKey = presetSelect.value;
    track.patch = JSON.parse(JSON.stringify(Waveforge.PRESETS[presetSelect.value]));
    track.name = track.patch.name;
    renderTracks();
  });
  header.appendChild(presetSelect);

  const noteInput = document.createElement('input');
  noteInput.type = 'number';
  noteInput.className = 'note-input';
  noteInput.title = 'Base MIDI note';
  noteInput.min = 0; noteInput.max = 127;
  noteInput.value = track.note;
  noteInput.addEventListener('input', () => {
    const v = parseInt(noteInput.value, 10);
    track.note = Number.isFinite(v) ? Math.min(127, Math.max(0, v)) : track.note;
  });
  header.appendChild(noteInput);

  const muteBtn = document.createElement('button');
  muteBtn.className = 'btn tiny' + (track.muted ? ' active' : '');
  muteBtn.textContent = 'M';
  muteBtn.title = 'Mute track';
  muteBtn.addEventListener('click', () => { track.muted = !track.muted; renderTracks(); });
  header.appendChild(muteBtn);

  const saveBtn = document.createElement('button');
  saveBtn.className = 'btn tiny';
  saveBtn.textContent = '⇩';
  saveBtn.title = 'Save this track\'s patch as JSON';
  saveBtn.addEventListener('click', () => savePatch(track));
  header.appendChild(saveBtn);

  const loadLabel = document.createElement('label');
  loadLabel.className = 'btn tiny file-btn';
  loadLabel.title = 'Load a patch JSON onto this track';
  loadLabel.textContent = '⇧';
  const loadInput = document.createElement('input');
  loadInput.type = 'file';
  loadInput.accept = 'application/json';
  loadInput.hidden = true;
  loadInput.addEventListener('change', (e) => loadPatch(track, e));
  loadLabel.appendChild(loadInput);
  header.appendChild(loadLabel);

  const removeBtn = document.createElement('button');
  removeBtn.className = 'btn tiny danger';
  removeBtn.textContent = '✕';
  removeBtn.title = 'Remove track';
  removeBtn.addEventListener('click', () => {
    state.tracks = state.tracks.filter((tr) => tr.id !== track.id);
    renderTracks();
  });
  header.appendChild(removeBtn);

  row.appendChild(header);

  // -- synth params --
  row.appendChild(buildParamsPanel(track));

  // -- step grid --
  const grid = document.createElement('div');
  grid.className = 'step-grid';
  track.steps.forEach((step, i) => {
    const cell = document.createElement('button');
    cell.className = 'step-cell ' + velocityClass(stepVelocity(step));
    if (i % 4 === 0) cell.classList.add('beat-start');
    cell.addEventListener('click', () => {
      // clicking always normalizes to a plain velocity level, dropping any
      // imported hold — editing a step makes the user own its timing.
      // Read the live value (not the closure's `step`) so repeated clicks
      // advance through the cycle instead of resetting each time.
      const currentLevel = nearestVelocityLevel(stepVelocity(track.steps[i]));
      const idx = VELOCITY_LEVELS.indexOf(currentLevel);
      const nextIdx = (idx + 1) % VELOCITY_LEVELS.length;
      track.steps[i] = VELOCITY_LEVELS[nextIdx];
      cell.className = 'step-cell ' + velocityClass(track.steps[i]) + (i % 4 === 0 ? ' beat-start' : '');
    });
    grid.appendChild(cell);
  });
  row.appendChild(grid);

  return row;
}

function velocityClass(vel) {
  if (vel <= 0) return 'off';
  if (vel < 0.7) return 'soft';
  if (vel < 0.95) return 'mid';
  return 'accent';
}

function buildParamsPanel(track) {
  const panel = document.createElement('div');
  panel.className = 'params-panel';

  function slider(labelText, min, max, step, value, onChange) {
    const wrap = document.createElement('label');
    wrap.className = 'field tiny-field';
    const span = document.createElement('span');
    span.textContent = labelText;
    const input = document.createElement('input');
    input.type = 'range';
    input.min = min; input.max = max; input.step = step; input.value = value;
    input.addEventListener('input', () => onChange(parseFloat(input.value)));
    wrap.appendChild(span);
    wrap.appendChild(input);
    return wrap;
  }

  const waveSelect = document.createElement('select');
  waveSelect.className = 'wave-select';
  Waveforge.WAVEFORMS.forEach((w) => {
    const opt = document.createElement('option');
    opt.value = w; opt.textContent = w;
    if (w === track.patch.waveform) opt.selected = true;
    waveSelect.appendChild(opt);
  });
  waveSelect.addEventListener('change', () => { track.patch.waveform = waveSelect.value; });
  const waveWrap = document.createElement('label');
  waveWrap.className = 'field tiny-field';
  const waveSpan = document.createElement('span');
  waveSpan.textContent = 'Wave';
  waveWrap.appendChild(waveSpan);
  waveWrap.appendChild(waveSelect);
  panel.appendChild(waveWrap);

  panel.appendChild(slider('Attack', 0, 1, 0.001, track.patch.envelope.attack, (v) => { track.patch.envelope.attack = v; }));
  panel.appendChild(slider('Decay', 0, 1, 0.001, track.patch.envelope.decay, (v) => { track.patch.envelope.decay = v; }));
  panel.appendChild(slider('Sustain', 0, 1, 0.01, track.patch.envelope.sustain, (v) => { track.patch.envelope.sustain = v; }));
  panel.appendChild(slider('Release', 0, 1.5, 0.001, track.patch.envelope.release, (v) => { track.patch.envelope.release = v; }));

  if (!track.patch.filter) track.patch.filter = { enabled: true, cutoff: 4000, resonance: 1 };
  panel.appendChild(slider('Cutoff', 100, 12000, 10, track.patch.filter.cutoff, (v) => { track.patch.filter.cutoff = v; }));
  panel.appendChild(slider('Reso', 0.1, 8, 0.05, track.patch.filter.resonance, (v) => { track.patch.filter.resonance = v; }));
  panel.appendChild(slider('Gain', 0, 1.2, 0.01, track.patch.gain != null ? track.patch.gain : 1, (v) => { track.patch.gain = v; }));

  return panel;
}

function savePatch(track) {
  const blob = new Blob([JSON.stringify(track.patch, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${track.name.toLowerCase().replace(/\s+/g, '-')}-patch.json`;
  a.click();
  URL.revokeObjectURL(url);
  setStatus(`Saved patch for "${track.name}".`);
}

function loadPatch(track, event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const patch = JSON.parse(reader.result);
      if (!patch.waveform || !patch.envelope) {
        throw new Error('missing waveform/envelope fields');
      }
      track.patch = patch;
      track.presetKey = null;
      track.name = patch.name || track.name;
      renderTracks();
      setStatus(`Loaded patch onto "${track.name}".`);
    } catch (err) {
      setStatus(`Could not load patch: ${err.message}`);
    }
  };
  reader.readAsText(file);
  event.target.value = '';
}

// ---------------------------------------------------------------------------
// Transport: play / stop / export
// ---------------------------------------------------------------------------

function ensureAudioCtx() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  return audioCtx;
}

function play() {
  const pattern = buildPattern();
  if (pattern.tracks.length === 0) {
    setStatus('Add at least one unmuted track before playing.');
    return;
  }
  const ctx = ensureAudioCtx();
  let samples;
  try {
    samples = Waveforge.render(pattern, ctx.sampleRate);
  } catch (err) {
    setStatus(`Can't play: ${err.message}`);
    return;
  }
  if (samples.length === 0) {
    setStatus('Nothing to play — pattern is empty.');
    return;
  }
  const buffer = ctx.createBuffer(1, samples.length, ctx.sampleRate);
  buffer.copyToChannel(samples, 0);

  stop(); // in case something is already playing
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(ctx.destination);
  source.onended = () => {
    document.getElementById('playBtn').disabled = false;
    document.getElementById('stopBtn').disabled = true;
    currentSource = null;
  };
  source.start();
  currentSource = source;
  document.getElementById('playBtn').disabled = true;
  document.getElementById('stopBtn').disabled = false;
}

function stop() {
  if (currentSource) {
    try { currentSource.onended = null; currentSource.stop(); } catch (e) { /* already stopped */ }
    currentSource = null;
  }
  document.getElementById('playBtn').disabled = false;
  document.getElementById('stopBtn').disabled = true;
}

function exportWav() {
  const pattern = buildPattern();
  if (pattern.tracks.length === 0) {
    setStatus('Add at least one unmuted track before exporting.');
    return;
  }
  let samples;
  try {
    samples = Waveforge.render(pattern, Waveforge.SAMPLE_RATE);
  } catch (err) {
    setStatus(`Can't export: ${err.message}`);
    return;
  }
  if (samples.length === 0) {
    setStatus('Nothing to export — pattern is empty.');
    return;
  }
  const wavBuffer = Waveforge.encodeWav(samples, Waveforge.SAMPLE_RATE, 1);
  const blob = new Blob([wavBuffer], { type: 'audio/wav' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'waveforge-song.wav';
  a.click();
  URL.revokeObjectURL(url);
  setStatus(`Exported ${(samples.length / Waveforge.SAMPLE_RATE).toFixed(2)}s WAV file.`);
}

function loadDemoSong() {
  fetch('demo-pattern.json')
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then((pattern) => {
      state.bpm = pattern.bpm;
      state.swing = pattern.swing || 0;
      state.effects = pattern.effects || state.effects;
      state.tracks = pattern.tracks.map((tr) => {
        trackIdCounter += 1;
        return {
          id: trackIdCounter,
          name: tr.name,
          presetKey: null,
          patch: tr.patch,
          note: tr.note,
          steps: tr.steps.map((s) => {
            if (!s || !s.on) return 0;
            const velocity = nearestVelocityLevel(s.velocity != null ? s.velocity : 1);
            return s.hold != null ? { velocity, hold: s.hold } : velocity;
          }),
          muted: false,
        };
      });
      document.getElementById('bpmInput').value = state.bpm;
      document.getElementById('swingInput').value = state.swing;
      document.getElementById('delayEnabled').checked = !!(state.effects.delay && state.effects.delay.enabled);
      document.getElementById('reverbEnabled').checked = !!(state.effects.reverb && state.effects.reverb.enabled);
      renderTracks();
      setStatus('Loaded demo song — press Play.');
    })
    .catch((err) => setStatus(`Could not load demo song: ${err.message}`));
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

function wireTransport() {
  document.getElementById('bpmInput').addEventListener('input', (e) => {
    const v = parseInt(e.target.value, 10);
    state.bpm = Number.isFinite(v) && v > 0 ? Math.min(300, Math.max(40, v)) : state.bpm;
  });
  document.getElementById('swingInput').addEventListener('input', (e) => {
    state.swing = parseFloat(e.target.value);
  });
  document.getElementById('playBtn').addEventListener('click', play);
  document.getElementById('stopBtn').addEventListener('click', stop);
  document.getElementById('exportBtn').addEventListener('click', exportWav);
  document.getElementById('loadDemoBtn').addEventListener('click', loadDemoSong);
  document.getElementById('addTrackBtn').addEventListener('click', () => {
    state.tracks.push(newTrack('pluck'));
    renderTracks();
  });

  document.getElementById('delayEnabled').addEventListener('change', (e) => { state.effects.delay.enabled = e.target.checked; });
  document.getElementById('delayTime').addEventListener('input', (e) => { state.effects.delay.time = parseFloat(e.target.value); });
  document.getElementById('delayFeedback').addEventListener('input', (e) => { state.effects.delay.feedback = parseFloat(e.target.value); });
  document.getElementById('delayMix').addEventListener('input', (e) => { state.effects.delay.mix = parseFloat(e.target.value); });
  document.getElementById('reverbEnabled').addEventListener('change', (e) => { state.effects.reverb.enabled = e.target.checked; });
  document.getElementById('reverbMix').addEventListener('input', (e) => { state.effects.reverb.mix = parseFloat(e.target.value); });
}

function init() {
  wireTransport();
  state.tracks = defaultTracks();
  renderTracks();
}

document.addEventListener('DOMContentLoaded', init);
