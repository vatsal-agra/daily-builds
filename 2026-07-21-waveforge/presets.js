// Built-in instrument patches. Plain JSON-serializable objects so they can
// round-trip through save/load and the patch browser without transformation.
'use strict';

(function () {

const PRESETS = {
  kick: {
    name: 'Kick',
    waveform: 'sine',
    envelope: { attack: 0.001, decay: 0.12, sustain: 0.0, release: 0.05 },
    filter: { enabled: true, cutoff: 900, resonance: 1.2 },
    gain: 1.0,
    pitchDrop: 24, // semitones the pitch sweeps down over the decay (kick character)
  },
  snare: {
    name: 'Snare',
    waveform: 'noise',
    envelope: { attack: 0.001, decay: 0.09, sustain: 0.0, release: 0.06 },
    filter: { enabled: true, cutoff: 2200, resonance: 0.7 },
    gain: 0.8,
  },
  hat: {
    name: 'Hi-hat',
    waveform: 'noise',
    envelope: { attack: 0.001, decay: 0.04, sustain: 0.0, release: 0.02 },
    filter: { enabled: true, cutoff: 8000, resonance: 0.4 },
    gain: 0.5,
  },
  bass: {
    name: 'Bass',
    waveform: 'saw',
    envelope: { attack: 0.01, decay: 0.1, sustain: 0.8, release: 0.08 },
    filter: { enabled: true, cutoff: 700, resonance: 1.5 },
    gain: 0.9,
  },
  lead: {
    name: 'Lead',
    waveform: 'square',
    envelope: { attack: 0.02, decay: 0.15, sustain: 0.6, release: 0.15 },
    filter: { enabled: true, cutoff: 3000, resonance: 2.0 },
    gain: 0.7,
  },
  pad: {
    name: 'Pad',
    waveform: 'triangle',
    envelope: { attack: 0.4, decay: 0.3, sustain: 0.7, release: 0.6 },
    filter: { enabled: true, cutoff: 1800, resonance: 0.6 },
    gain: 0.6,
  },
  pluck: {
    name: 'Pluck',
    waveform: 'triangle',
    envelope: { attack: 0.001, decay: 0.2, sustain: 0.0, release: 0.1 },
    filter: { enabled: true, cutoff: 4000, resonance: 1.0 },
    gain: 0.8,
  },
};

const api = { PRESETS };

if (typeof module !== 'undefined' && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== 'undefined') {
  globalThis.Waveforge = globalThis.Waveforge || {};
  Object.assign(globalThis.Waveforge, api);
}

})();
