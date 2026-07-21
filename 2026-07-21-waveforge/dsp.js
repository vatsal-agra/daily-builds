// Waveforge DSP core.
//
// Pure JS, zero browser/Node-specific APIs (only Math, Float32Array, and
// friends) so this file runs unmodified in Node (CLI, tests) and in a
// browser <script> tag (UI).
'use strict';

(function () {

const SAMPLE_RATE = 44100;

// ---------------------------------------------------------------------------
// Oscillators
// ---------------------------------------------------------------------------
// Each oscillator is a phase-accumulator generator: phase runs 0..1 and wraps
// with modulo, so there is never a discontinuity at the wrap point (no
// clicking), independent of buffer boundaries.

const WAVEFORMS = ['sine', 'saw', 'square', 'triangle', 'noise'];

function oscSample(waveform, phase) {
  // phase is in [0, 1)
  switch (waveform) {
    case 'sine':
      return Math.sin(2 * Math.PI * phase);
    case 'saw':
      // ramps from -1 to 1 across the period
      return 2 * phase - 1;
    case 'square':
      return phase < 0.5 ? 1 : -1;
    case 'triangle': {
      // 0->1 rises -1..1, 1->2 (i.e. wrapped 0.5->1) falls 1..-1
      const t = phase < 0.5 ? phase * 2 : 2 - phase * 2;
      return t * 2 - 1;
    }
    case 'noise':
      return Math.random() * 2 - 1;
    default:
      throw new Error(`unknown waveform: ${waveform}`);
  }
}

function midiToFreq(note) {
  return 440 * Math.pow(2, (note - 69) / 12);
}

// ---------------------------------------------------------------------------
// ADSR envelope
// ---------------------------------------------------------------------------
// attack/decay/release are seconds, sustain is a 0..1 level.
// gain(t, noteOnDur) returns the envelope's gain at time t (seconds since
// note-on), given the note was held for noteOnDur seconds before release
// began (i.e. release starts at t = noteOnDur).

function envelopeGain(env, t, noteOnDur) {
  const { attack, decay, sustain, release } = env;
  if (t < 0) return 0;
  if (t < noteOnDur) {
    // still held: attack -> decay -> sustain
    if (t < attack) {
      return attack > 0 ? t / attack : 1;
    }
    const dt = t - attack;
    if (dt < decay) {
      const decayFrac = decay > 0 ? dt / decay : 1;
      return 1 + (sustain - 1) * decayFrac;
    }
    return sustain;
  }
  // released: fade from the level we were at when release began, to 0
  const releasedFor = t - noteOnDur;
  if (releasedFor >= release) return 0;
  const heldLevel = adsrHeldLevel(env, noteOnDur);
  const releaseFrac = release > 0 ? releasedFor / release : 1;
  return heldLevel * (1 - releaseFrac);
}

function adsrHeldLevel(env, heldDur) {
  const { attack, decay, sustain } = env;
  if (heldDur < attack) return attack > 0 ? heldDur / attack : 1;
  const dt = heldDur - attack;
  if (dt < decay) {
    const decayFrac = decay > 0 ? dt / decay : 1;
    return 1 + (sustain - 1) * decayFrac;
  }
  return sustain;
}

// total duration (seconds) of a note including its release tail
function envelopeTotalDuration(env, heldDur) {
  return heldDur + env.release;
}

// ---------------------------------------------------------------------------
// Biquad low-pass filter (RBJ cookbook design), resonance = Q
// ---------------------------------------------------------------------------

class LowPassFilter {
  constructor(cutoffHz, q, sampleRate = SAMPLE_RATE) {
    this.setParams(cutoffHz, q, sampleRate);
    this.x1 = 0; this.x2 = 0; this.y1 = 0; this.y2 = 0;
  }

  setParams(cutoffHz, q, sampleRate = SAMPLE_RATE) {
    const clampedCutoff = Math.min(Math.max(cutoffHz, 20), sampleRate / 2 - 1);
    const w0 = 2 * Math.PI * clampedCutoff / sampleRate;
    const alpha = Math.sin(w0) / (2 * Math.max(q, 0.0001));
    const cosw0 = Math.cos(w0);

    const b0 = (1 - cosw0) / 2;
    const b1 = 1 - cosw0;
    const b2 = (1 - cosw0) / 2;
    const a0 = 1 + alpha;
    const a1 = -2 * cosw0;
    const a2 = 1 - alpha;

    this.b0 = b0 / a0; this.b1 = b1 / a0; this.b2 = b2 / a0;
    this.a1 = a1 / a0; this.a2 = a2 / a0;
  }

  process(x) {
    const y = this.b0 * x + this.b1 * this.x1 + this.b2 * this.x2
      - this.a1 * this.y1 - this.a2 * this.y2;
    this.x2 = this.x1; this.x1 = x;
    this.y2 = this.y1; this.y1 = y;
    return y;
  }
}

// ---------------------------------------------------------------------------
// Effects: feedback delay + Schroeder reverb
// ---------------------------------------------------------------------------

class DelayEffect {
  constructor(delaySeconds, feedback, mix, sampleRate = SAMPLE_RATE) {
    this.size = Math.max(1, Math.round(delaySeconds * sampleRate));
    this.buf = new Float32Array(this.size);
    this.pos = 0;
    this.feedback = feedback;
    this.mix = mix;
  }

  process(x) {
    const delayed = this.buf[this.pos];
    this.buf[this.pos] = x + delayed * this.feedback;
    this.pos = (this.pos + 1) % this.size;
    return x * (1 - this.mix) + delayed * this.mix;
  }
}

class CombFilter {
  constructor(delaySamples, feedback) {
    this.buf = new Float32Array(delaySamples);
    this.pos = 0;
    this.feedback = feedback;
  }
  process(x) {
    const out = this.buf[this.pos];
    this.buf[this.pos] = x + out * this.feedback;
    this.pos = (this.pos + 1) % this.buf.length;
    return out;
  }
}

class AllpassFilter {
  constructor(delaySamples, gain) {
    this.buf = new Float32Array(delaySamples);
    this.pos = 0;
    this.gain = gain;
  }
  process(x) {
    const bufOut = this.buf[this.pos];
    const out = -this.gain * x + bufOut;
    this.buf[this.pos] = x + bufOut * this.gain;
    this.pos = (this.pos + 1) % this.buf.length;
    return out;
  }
}

// Classic Schroeder topology: 4 parallel combs summed, then 2 series allpasses.
class SchroederReverb {
  constructor(mix, sampleRate = SAMPLE_RATE) {
    const combTunings = [1557, 1617, 1491, 1422]; // samples, at 44.1kHz-ish ratios
    const allpassTunings = [225, 556];
    const scale = sampleRate / 44100;
    this.combs = combTunings.map((d) => new CombFilter(Math.round(d * scale), 0.84));
    this.allpasses = allpassTunings.map((d) => new AllpassFilter(Math.round(d * scale), 0.5));
    this.mix = mix;
  }

  process(x) {
    let combSum = 0;
    for (const c of this.combs) combSum += c.process(x);
    combSum /= this.combs.length;
    let out = combSum;
    for (const ap of this.allpasses) out = ap.process(out);
    return x * (1 - this.mix) + out * this.mix;
  }
}

// ---------------------------------------------------------------------------
// Voice rendering: renders one note (patch + midi note + start time + hold
// duration) into an output buffer, additively mixing into it at the right
// sample offset.
// ---------------------------------------------------------------------------

function renderVoiceInto(outBuffer, patch, note, startSample, heldSeconds, velocity, sampleRate = SAMPLE_RATE) {
  const baseFreq = midiToFreq(note);
  const env = patch.envelope;
  const totalDur = envelopeTotalDuration(env, heldSeconds);
  const totalSamples = Math.ceil(totalDur * sampleRate);
  const filter = patch.filter && patch.filter.enabled
    ? new LowPassFilter(patch.filter.cutoff, patch.filter.resonance, sampleRate)
    : null;
  // optional pitch-drop envelope (e.g. kick drums): frequency starts
  // pitchDrop semitones above baseFreq and decays exponentially down to it
  // with time constant pitchDecay (defaults to the amplitude envelope's decay).
  const pitchDrop = patch.pitchDrop || 0;
  const pitchDecay = patch.pitchDecay || env.decay || 0.05;

  let phase = 0;

  for (let i = 0; i < totalSamples; i++) {
    const outIdx = startSample + i;
    if (outIdx >= outBuffer.length) break;
    const t = i / sampleRate;
    const g = envelopeGain(env, t, heldSeconds);
    if (g <= 0 && t > 0) {
      // once fully released and silent, no need to keep computing samples,
      // but only break once past the held phase (t could be 0 at attack=0)
      if (t >= heldSeconds) break;
    }
    const pitchMult = pitchDrop > 0
      ? 1 + (Math.pow(2, pitchDrop / 12) - 1) * Math.exp(-t / Math.max(pitchDecay, 0.001))
      : 1;
    const freq = baseFreq * pitchMult;
    const phaseInc = freq / sampleRate;
    let s = oscSample(patch.waveform, phase);
    phase += phaseInc;
    if (phase >= 1) phase -= Math.floor(phase);
    if (filter) s = filter.process(s);
    outBuffer[outIdx] += s * g * velocity * (patch.gain != null ? patch.gain : 1);
  }
}

// ---------------------------------------------------------------------------
// WAV encoding — hand-written RIFF/WAVE header + 16-bit PCM samples.
// ---------------------------------------------------------------------------

function encodeWav(samples, sampleRate = SAMPLE_RATE, numChannels = 1) {
  const bytesPerSample = 2;
  const blockAlign = numChannels * bytesPerSample;
  const byteRate = sampleRate * blockAlign;
  const dataSize = samples.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  function writeString(offset, str) {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  }

  writeString(0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true); // fmt chunk size (PCM)
  view.setUint16(20, 1, true); // audio format: 1 = PCM
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true); // bits per sample
  writeString(36, 'data');
  view.setUint32(40, dataSize, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    const intSample = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    view.setInt16(offset, Math.round(intSample), true);
    offset += 2;
  }

  return buffer;
}

// Parse a WAV ArrayBuffer's header back out — used by tests to round-trip
// verify encodeWav's output against the RIFF spec.
function parseWavHeader(buffer) {
  const view = new DataView(buffer);
  function readString(offset, len) {
    let s = '';
    for (let i = 0; i < len; i++) s += String.fromCharCode(view.getUint8(offset + i));
    return s;
  }
  return {
    riff: readString(0, 4),
    fileSize: view.getUint32(4, true),
    wave: readString(8, 4),
    fmt: readString(12, 4),
    fmtSize: view.getUint32(16, true),
    audioFormat: view.getUint16(20, true),
    numChannels: view.getUint16(22, true),
    sampleRate: view.getUint32(24, true),
    byteRate: view.getUint32(28, true),
    blockAlign: view.getUint16(32, true),
    bitsPerSample: view.getUint16(34, true),
    dataTag: readString(36, 4),
    dataSize: view.getUint32(40, true),
  };
}

function rms(samples) {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return Math.sqrt(sum / samples.length);
}

const api = {
  SAMPLE_RATE,
  WAVEFORMS,
  oscSample,
  midiToFreq,
  envelopeGain,
  adsrHeldLevel,
  envelopeTotalDuration,
  LowPassFilter,
  DelayEffect,
  CombFilter,
  AllpassFilter,
  SchroederReverb,
  renderVoiceInto,
  encodeWav,
  parseWavHeader,
  rms,
};

if (typeof module !== 'undefined' && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== 'undefined') {
  globalThis.Waveforge = globalThis.Waveforge || {};
  Object.assign(globalThis.Waveforge, api);
}

})();
