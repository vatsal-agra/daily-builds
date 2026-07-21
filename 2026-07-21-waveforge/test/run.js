#!/usr/bin/env node
// Waveforge test suite. Every test renders real samples through the actual
// DSP/sequencer engine and asserts on the resulting data — no mocks, no
// stubbed logic. Run with: node test/run.js
'use strict';

const assert = require('assert');
const path = require('path');
const fs = require('fs');
const dsp = require('../dsp.js');
const sequencer = require('../sequencer.js');
const { PRESETS } = require('../presets.js');

let passed = 0;
let failed = 0;
const failures = [];

function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`  ok  - ${name}`);
  } catch (err) {
    failed += 1;
    failures.push({ name, err });
    console.log(`  FAIL - ${name}`);
    console.log(`         ${err.message}`);
  }
}

function section(title) {
  console.log(`\n${title}`);
}

// ---------------------------------------------------------------------------
section('Oscillators');
// ---------------------------------------------------------------------------

test('sine wave: zero at phase 0, peak at phase 0.25, zero at 0.5', () => {
  assert.ok(Math.abs(dsp.oscSample('sine', 0)) < 1e-9);
  assert.ok(Math.abs(dsp.oscSample('sine', 0.25) - 1) < 1e-9);
  assert.ok(Math.abs(dsp.oscSample('sine', 0.5)) < 1e-9);
});

test('saw wave: ramps linearly from -1 to just under 1', () => {
  assert.ok(Math.abs(dsp.oscSample('saw', 0) - -1) < 1e-9);
  assert.ok(Math.abs(dsp.oscSample('saw', 0.5) - 0) < 1e-9);
  assert.ok(dsp.oscSample('saw', 0.999) > 0.9);
});

test('square wave: +1 for first half, -1 for second half', () => {
  assert.strictEqual(dsp.oscSample('square', 0.1), 1);
  assert.strictEqual(dsp.oscSample('square', 0.9), -1);
});

test('triangle wave: peaks at 0.25 and 0.75, zero-crossing at 0 and 0.5', () => {
  assert.ok(Math.abs(dsp.oscSample('triangle', 0)) < 1e-9);
  assert.ok(Math.abs(dsp.oscSample('triangle', 0.25) - 1) < 1e-9);
  assert.ok(Math.abs(dsp.oscSample('triangle', 0.75) - -1) < 1e-9);
});

test('noise: stays within [-1, 1] and is not constant', () => {
  const samples = Array.from({ length: 200 }, () => dsp.oscSample('noise', 0));
  assert.ok(samples.every((s) => s >= -1 && s <= 1));
  assert.ok(new Set(samples).size > 50, 'noise should vary sample to sample');
});

test('unknown waveform throws instead of silently returning garbage', () => {
  assert.throws(() => dsp.oscSample('bogus', 0));
});

test('midiToFreq: A4 (note 69) is exactly 440Hz, one octave up doubles it', () => {
  assert.strictEqual(dsp.midiToFreq(69), 440);
  assert.ok(Math.abs(dsp.midiToFreq(81) - 880) < 1e-9);
});

// ---------------------------------------------------------------------------
section('ADSR envelope');
// ---------------------------------------------------------------------------

test('attack ramps 0 -> 1 linearly', () => {
  const env = { attack: 0.1, decay: 0.1, sustain: 0.5, release: 0.1 };
  assert.ok(Math.abs(dsp.envelopeGain(env, 0, 1) - 0) < 1e-9);
  assert.ok(Math.abs(dsp.envelopeGain(env, 0.05, 1) - 0.5) < 1e-6);
  assert.ok(Math.abs(dsp.envelopeGain(env, 0.1, 1) - 1) < 1e-6);
});

test('decay falls from 1 to sustain level', () => {
  const env = { attack: 0, decay: 0.2, sustain: 0.4, release: 0.1 };
  assert.ok(Math.abs(dsp.envelopeGain(env, 0, 1) - 1) < 1e-6);
  assert.ok(Math.abs(dsp.envelopeGain(env, 0.2, 1) - 0.4) < 1e-6);
});

test('sustain holds steady while note is held', () => {
  const env = { attack: 0.01, decay: 0.01, sustain: 0.6, release: 0.1 };
  assert.ok(Math.abs(dsp.envelopeGain(env, 0.5, 1) - 0.6) < 1e-9);
  assert.ok(Math.abs(dsp.envelopeGain(env, 0.9, 1) - 0.6) < 1e-9);
});

test('release fades from held level to 0 after note-off', () => {
  const env = { attack: 0, decay: 0, sustain: 0.8, release: 0.2 };
  assert.ok(Math.abs(dsp.envelopeGain(env, 1.0, 1) - 0.8) < 1e-6, 'level right at release start');
  assert.ok(Math.abs(dsp.envelopeGain(env, 1.1, 1) - 0.4) < 1e-6, 'halfway through release');
  // t=1.2 lands exactly on the release-end boundary, where float
  // subtraction (1.2 - 1) can leave a ~1e-16 residual instead of an exact
  // 0 — inaudible in practice, so assert "negligible" rather than "exact".
  assert.ok(Math.abs(dsp.envelopeGain(env, 1.2, 1)) < 1e-9, 'fully released (within float tolerance)');
  assert.strictEqual(dsp.envelopeGain(env, 5, 1), 0, 'long after release stays silent');
});

test('zero-length attack/decay does not produce NaN or Infinity', () => {
  const env = { attack: 0, decay: 0, sustain: 1, release: 0 };
  for (const t of [0, 0.001, 1, 1.001]) {
    assert.ok(Number.isFinite(dsp.envelopeGain(env, t, 1)));
  }
});

// ---------------------------------------------------------------------------
section('Filter');
// ---------------------------------------------------------------------------

test('low-pass filter attenuates a high-frequency tone more than a low one', () => {
  function rmsAfterFilter(freq, cutoff) {
    const filter = new dsp.LowPassFilter(cutoff, 0.707, 44100);
    let phase = 0;
    const inc = freq / 44100;
    const out = new Float32Array(4410);
    for (let i = 0; i < out.length; i++) {
      const x = Math.sin(2 * Math.PI * phase);
      phase = (phase + inc) % 1;
      out[i] = filter.process(x);
    }
    // skip the first 500 samples (filter settling time) before measuring
    return dsp.rms(out.slice(500));
  }
  const lowFreqOut = rmsAfterFilter(200, 1000);
  const highFreqOut = rmsAfterFilter(8000, 1000);
  assert.ok(highFreqOut < lowFreqOut * 0.5, `expected strong attenuation above cutoff, got low=${lowFreqOut} high=${highFreqOut}`);
});

test('filter cutoff far above Nyquist and resonance of 0 stay finite (no crash)', () => {
  const f1 = new dsp.LowPassFilter(999999, 1, 44100);
  const f2 = new dsp.LowPassFilter(1000, 0, 44100);
  assert.ok(Number.isFinite(f1.process(1)));
  assert.ok(Number.isFinite(f2.process(1)));
});

// ---------------------------------------------------------------------------
section('WAV encoding');
// ---------------------------------------------------------------------------

test('encodeWav produces a spec-correct RIFF/WAVE header', () => {
  const samples = new Float32Array([0, 0.5, -0.5, 1, -1]);
  const buf = dsp.encodeWav(samples, 44100, 1);
  const hdr = dsp.parseWavHeader(buf);
  assert.strictEqual(hdr.riff, 'RIFF');
  assert.strictEqual(hdr.wave, 'WAVE');
  assert.strictEqual(hdr.fmt, 'fmt ');
  assert.strictEqual(hdr.audioFormat, 1);
  assert.strictEqual(hdr.numChannels, 1);
  assert.strictEqual(hdr.sampleRate, 44100);
  assert.strictEqual(hdr.bitsPerSample, 16);
  assert.strictEqual(hdr.dataTag, 'data');
  assert.strictEqual(hdr.dataSize, samples.length * 2);
  assert.strictEqual(buf.byteLength, 44 + samples.length * 2);
});

test('encodeWav clamps out-of-range samples instead of wrapping/distorting', () => {
  const buf = dsp.encodeWav(new Float32Array([2.5, -3.0, 0.5]), 44100, 1);
  const view = new DataView(buf);
  assert.strictEqual(view.getInt16(44, true), 32767);
  assert.strictEqual(view.getInt16(46, true), -32768);
});

test('encodeWav handles zero samples without crashing', () => {
  const buf = dsp.encodeWav(new Float32Array(0), 44100, 1);
  const hdr = dsp.parseWavHeader(buf);
  assert.strictEqual(hdr.dataSize, 0);
  assert.strictEqual(buf.byteLength, 44);
});

// ---------------------------------------------------------------------------
section('Sequencer: multi-track polyphony');
// ---------------------------------------------------------------------------

test('a pattern with all steps off renders silence', () => {
  const pattern = {
    bpm: 120, stepsPerBeat: 4,
    tracks: [{ name: 'x', patch: PRESETS.bass, note: 60, steps: new Array(16).fill(null) }],
  };
  const samples = sequencer.render(pattern);
  assert.ok(dsp.rms(samples) < 1e-6);
});

test('a single active step produces sound only starting at that step', () => {
  const pattern = {
    bpm: 120, stepsPerBeat: 4,
    tracks: [{
      name: 'x', patch: PRESETS.pluck, note: 60,
      steps: [null, null, null, null, { on: true, velocity: 1 }, null, null, null],
    }],
  };
  const samples = sequencer.render(pattern);
  const stepDur = sequencer.stepDurationSeconds(pattern);
  const stepStartSample = Math.round(4 * stepDur * 44100);
  const before = dsp.rms(samples.slice(0, stepStartSample - 200));
  const after = dsp.rms(samples.slice(stepStartSample, stepStartSample + 2000));
  assert.ok(before < 1e-6, `expected silence before the step, got rms=${before}`);
  assert.ok(after > 0.01, `expected sound right after the step, got rms=${after}`);
});

test('two simultaneous tracks mix additively (polyphony), not silently drop one', () => {
  const soloPattern = (name) => ({
    bpm: 120, stepsPerBeat: 4,
    tracks: [{ name, patch: PRESETS.lead, note: 60, steps: [{ on: true, velocity: 1 }] }],
  });
  const bothPattern = {
    bpm: 120, stepsPerBeat: 4,
    tracks: [
      { name: 'a', patch: PRESETS.lead, note: 60, steps: [{ on: true, velocity: 1 }] },
      { name: 'b', patch: PRESETS.lead, note: 67, steps: [{ on: true, velocity: 1 }] },
    ],
  };
  const rmsA = dsp.rms(sequencer.render(soloPattern('a')));
  const rmsBoth = dsp.rms(sequencer.render(bothPattern));
  assert.ok(rmsBoth > rmsA * 1.1, `expected combined energy to exceed a single voice: solo=${rmsA} both=${rmsBoth}`);
});

test('velocity scales output energy', () => {
  const patternAt = (v) => ({
    bpm: 120, stepsPerBeat: 4,
    tracks: [{ name: 'x', patch: PRESETS.lead, note: 60, steps: [{ on: true, velocity: v }] }],
  });
  const quiet = dsp.rms(sequencer.render(patternAt(0.2)));
  const loud = dsp.rms(sequencer.render(patternAt(1.0)));
  assert.ok(loud > quiet * 2, `expected louder velocity to have more energy: quiet=${quiet} loud=${loud}`);
});

test('the full 6-track demo song renders cleanly: finite, non-silent, non-clipped', () => {
  const pattern = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'demo-pattern.json'), 'utf8'));
  const samples = sequencer.render(pattern);
  assert.ok(samples.length > 0);
  assert.ok(samples.every(Number.isFinite), 'no NaN/Infinity in the rendered song');
  assert.ok(!samples.some((s) => Math.abs(s) > 1.0001), 'no samples exceed [-1, 1] after soft-limiting');
  assert.ok(dsp.rms(samples) > 0.05, 'demo song should not render as near-silence');
});

// ---------------------------------------------------------------------------
section('Effects');
// ---------------------------------------------------------------------------

test('delay + reverb produce an audible tail after the dry signal would be silent', () => {
  const dry = {
    bpm: 120, stepsPerBeat: 4,
    tracks: [{ name: 'x', patch: PRESETS.pluck, note: 60, steps: [{ on: true, velocity: 1 }] }],
  };
  const wet = {
    ...dry,
    effects: { delay: { enabled: true, time: 0.15, feedback: 0.5, mix: 0.4 }, reverb: { enabled: true, mix: 0.4 } },
  };
  const drySamples = sequencer.render(dry);
  const wetSamples = sequencer.render(wet);
  const tailLen = 4410;
  const dryTail = dsp.rms(drySamples.slice(-tailLen));
  const wetTail = dsp.rms(wetSamples.slice(-tailLen));
  assert.ok(wetTail > dryTail * 3, `expected wet tail to carry more energy than dry: dry=${dryTail} wet=${wetTail}`);
});

// ---------------------------------------------------------------------------
section('Pattern validation (regression tests for Phase 3 findings)');
// ---------------------------------------------------------------------------

test('bpm <= 0 throws a clear, actionable error instead of crashing on Infinity', () => {
  const pattern = { bpm: 0, stepsPerBeat: 4, tracks: [{ name: 'x', patch: PRESETS.bass, note: 60, steps: [{ on: true, velocity: 1 }] }] };
  assert.throws(() => sequencer.render(pattern), /pattern\.bpm must be a positive number/);
});

test('negative bpm also throws cleanly', () => {
  const pattern = { bpm: -100, stepsPerBeat: 4, tracks: [{ name: 'x', patch: PRESETS.bass, note: 60, steps: [{ on: true, velocity: 1 }] }] };
  assert.throws(() => sequencer.render(pattern), /pattern\.bpm must be a positive number/);
});

test('stepsPerBeat <= 0 throws a clear error', () => {
  const pattern = { bpm: 120, stepsPerBeat: 0, tracks: [{ name: 'x', patch: PRESETS.bass, note: 60, steps: [{ on: true, velocity: 1 }] }] };
  assert.throws(() => sequencer.render(pattern), /pattern\.stepsPerBeat must be a positive number/);
});

test('a patch missing envelope throws an error naming the offending track', () => {
  const pattern = { bpm: 120, stepsPerBeat: 4, tracks: [{ name: 'BadTrack', patch: { waveform: 'sine' }, note: 60, steps: [{ on: true, velocity: 1 }] }] };
  assert.throws(() => sequencer.render(pattern), /BadTrack.*envelope/);
});

test('a patch with an unknown waveform throws a clear error', () => {
  const pattern = {
    bpm: 120, stepsPerBeat: 4,
    tracks: [{ name: 'Weird', patch: { waveform: 'chiptune-8bit', envelope: { attack: 0, decay: 0, sustain: 1, release: 0.1 } }, note: 60, steps: [{ on: true, velocity: 1 }] }],
  };
  assert.throws(() => sequencer.render(pattern), /Weird.*waveform/);
});

test('an empty tracks array renders an empty buffer rather than throwing', () => {
  const samples = sequencer.render({ bpm: 120, stepsPerBeat: 4, tracks: [] });
  assert.strictEqual(samples.length, 0);
});

test('a null/undefined pattern renders an empty buffer rather than throwing', () => {
  assert.strictEqual(sequencer.render(null).length, 0);
  assert.strictEqual(sequencer.render(undefined).length, 0);
});

// ---------------------------------------------------------------------------
section('CLI (render.js) end-to-end');
// ---------------------------------------------------------------------------

test('render.js writes a real, valid WAV file for the demo song', () => {
  const outPath = path.join(__dirname, '.tmp-demo-out.wav');
  const { execFileSync } = require('child_process');
  execFileSync('node', [path.join(__dirname, '..', 'render.js'), path.join(__dirname, '..', 'demo-pattern.json'), outPath]);
  const buf = fs.readFileSync(outPath);
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  const hdr = dsp.parseWavHeader(ab);
  assert.strictEqual(hdr.riff, 'RIFF');
  assert.strictEqual(hdr.dataSize, buf.length - 44);
  fs.unlinkSync(outPath);
});

test('render.js exits non-zero with a clear message on an invalid pattern (bpm=0)', () => {
  const { execFileSync } = require('child_process');
  const badPath = path.join(__dirname, '.tmp-bad-pattern.json');
  fs.writeFileSync(badPath, JSON.stringify({ bpm: 0, stepsPerBeat: 4, tracks: [{ name: 'x', patch: PRESETS.bass, note: 60, steps: [{ on: true, velocity: 1 }] }] }));
  const outPath = path.join(__dirname, '.tmp-should-not-exist.wav');
  let threw = false;
  let stderr = '';
  try {
    execFileSync('node', [path.join(__dirname, '..', 'render.js'), badPath, outPath], { stdio: 'pipe' });
  } catch (err) {
    threw = true;
    stderr = err.stderr.toString();
  }
  assert.ok(threw, 'expected render.js to exit non-zero');
  assert.ok(stderr.includes('pattern.bpm must be a positive number'), `expected clear error in stderr, got: ${stderr}`);
  assert.ok(!fs.existsSync(outPath), 'should not have written an output file');
  fs.unlinkSync(badPath);
});

test('render.js exits non-zero on malformed JSON', () => {
  const { execFileSync } = require('child_process');
  const badPath = path.join(__dirname, '.tmp-invalid.json');
  fs.writeFileSync(badPath, 'not json at all {{{');
  let threw = false;
  try {
    execFileSync('node', [path.join(__dirname, '..', 'render.js'), badPath, path.join(__dirname, '.tmp2.wav')], { stdio: 'pipe' });
  } catch (err) {
    threw = true;
  }
  assert.ok(threw);
  fs.unlinkSync(badPath);
});

// ---------------------------------------------------------------------------
console.log(`\n${passed} passed, ${failed} failed\n`);
if (failed > 0) {
  process.exit(1);
}
