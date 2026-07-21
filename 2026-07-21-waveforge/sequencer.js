// Pattern data model + renderer: turns a multi-track step pattern into a
// full song's Float32Array of samples by scheduling voices through dsp.js.
'use strict';

(function () {

const dsp = (typeof module !== 'undefined' && module.exports)
  ? require('./dsp.js')
  : globalThis.Waveforge;

// A pattern:
// {
//   bpm: 120,
//   stepsPerBeat: 4,           // 4 = sixteenth notes
//   swing: 0,                  // 0..1, fraction of a step delayed on off-beats
//   effects: { delay: {enabled, time, feedback, mix}, reverb: {enabled, mix} },
//   tracks: [
//     {
//       name: 'Kick',
//       patch: {...},          // see presets.js shape
//       note: 36,              // MIDI note (ignored for drum-style noise patches, still fine)
//       steps: [               // one entry per step; null/false = off
//         { on: true, velocity: 1.0, note: 36 } | null | false, ...
//       ],
//     },
//     ...
//   ],
// }

function stepDurationSeconds(pattern) {
  const beatsPerSecond = pattern.bpm / 60;
  return 1 / (beatsPerSecond * pattern.stepsPerBeat);
}

function validatePattern(pattern) {
  if (!(pattern.bpm > 0)) {
    throw new Error(`pattern.bpm must be a positive number, got ${JSON.stringify(pattern.bpm)}`);
  }
  if (!(pattern.stepsPerBeat > 0)) {
    throw new Error(`pattern.stepsPerBeat must be a positive number, got ${JSON.stringify(pattern.stepsPerBeat)}`);
  }
  for (const track of pattern.tracks) {
    const patch = track.patch;
    if (!patch || !dsp.WAVEFORMS.includes(patch.waveform)) {
      throw new Error(`Track "${track.name}": patch.waveform must be one of ${dsp.WAVEFORMS.join(', ')}`);
    }
    const env = patch.envelope;
    const envFieldsOk = env && ['attack', 'decay', 'sustain', 'release'].every((k) => Number.isFinite(env[k]));
    if (!envFieldsOk) {
      throw new Error(`Track "${track.name}": patch.envelope is missing or incomplete (needs finite attack/decay/sustain/release)`);
    }
  }
}

function songDurationSeconds(pattern) {
  const maxSteps = Math.max(1, ...pattern.tracks.map((tr) => tr.steps.length));
  const stepDur = stepDurationSeconds(pattern);
  // add a release tail so the last note's envelope isn't truncated
  const longestRelease = Math.max(
    0.1,
    ...pattern.tracks.map((tr) => (tr.patch.envelope ? tr.patch.envelope.release : 0.1))
  );
  return maxSteps * stepDur + longestRelease + 0.25;
}

function render(pattern, sampleRate = dsp.SAMPLE_RATE) {
  if (!pattern || !Array.isArray(pattern.tracks) || pattern.tracks.length === 0) {
    return new Float32Array(0);
  }
  validatePattern(pattern);
  const stepDur = stepDurationSeconds(pattern);
  const totalSamples = Math.ceil(songDurationSeconds(pattern) * sampleRate);
  const buffer = new Float32Array(totalSamples);
  const swing = pattern.swing || 0;

  for (const track of pattern.tracks) {
    const patch = track.patch;
    for (let stepIdx = 0; stepIdx < track.steps.length; stepIdx++) {
      const step = track.steps[stepIdx];
      if (!step || !step.on) continue;
      const isOffBeat = stepIdx % 2 === 1;
      const swingOffset = isOffBeat ? swing * stepDur : 0;
      const startTime = stepIdx * stepDur + swingOffset;
      const startSample = Math.round(startTime * sampleRate);
      const velocity = step.velocity != null ? step.velocity : 1.0;
      const note = step.note != null ? step.note : (track.note != null ? track.note : 60);
      // notes are held for one step by default, unless a longer hold is
      // specified (sustain across steps handled by envelope's sustain level
      // + this fixed hold length, which is enough for the step-sequencer model)
      const heldSeconds = step.hold != null ? step.hold * stepDur : stepDur * 0.9;
      dsp.renderVoiceInto(buffer, patch, note, startSample, heldSeconds, velocity, sampleRate);
    }
  }

  applyEffects(buffer, pattern.effects, sampleRate);
  softLimit(buffer);
  return buffer;
}

function applyEffects(buffer, effects, sampleRate) {
  if (!effects) return;
  if (effects.delay && effects.delay.enabled) {
    const fx = new dsp.DelayEffect(effects.delay.time, effects.delay.feedback, effects.delay.mix, sampleRate);
    for (let i = 0; i < buffer.length; i++) buffer[i] = fx.process(buffer[i]);
  }
  if (effects.reverb && effects.reverb.enabled) {
    const fx = new dsp.SchroederReverb(effects.reverb.mix, sampleRate);
    for (let i = 0; i < buffer.length; i++) buffer[i] = fx.process(buffer[i]);
  }
}

// Soft-knee limiter (tanh) to avoid harsh digital clipping when many voices
// stack up, applied in place.
function softLimit(buffer) {
  for (let i = 0; i < buffer.length; i++) {
    buffer[i] = Math.tanh(buffer[i]);
  }
}

const api = { stepDurationSeconds, songDurationSeconds, validatePattern, render };

if (typeof module !== 'undefined' && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== 'undefined') {
  globalThis.Waveforge = globalThis.Waveforge || {};
  Object.assign(globalThis.Waveforge, api);
}

})();
