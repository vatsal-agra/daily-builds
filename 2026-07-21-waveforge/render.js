#!/usr/bin/env node
// CLI: render a pattern JSON file to a real WAV file.
//   node render.js pattern.json out.wav
'use strict';

const fs = require('fs');
const path = require('path');
const dsp = require('./dsp.js');
const sequencer = require('./sequencer.js');

function main() {
  const [, , patternPath, outPath] = process.argv;
  if (!patternPath || !outPath) {
    console.error('Usage: node render.js <pattern.json> <out.wav>');
    process.exit(1);
  }

  let raw;
  try {
    raw = fs.readFileSync(path.resolve(patternPath), 'utf8');
  } catch (err) {
    console.error(`Could not read pattern file: ${patternPath}\n${err.message}`);
    process.exit(1);
  }

  let pattern;
  try {
    pattern = JSON.parse(raw);
  } catch (err) {
    console.error(`Invalid JSON in pattern file: ${err.message}`);
    process.exit(1);
  }

  if (!pattern.tracks || pattern.tracks.length === 0) {
    console.error('Pattern has no tracks — nothing to render.');
    process.exit(1);
  }

  const samples = sequencer.render(pattern);
  const wavBuffer = dsp.encodeWav(samples, dsp.SAMPLE_RATE, 1);
  fs.writeFileSync(path.resolve(outPath), Buffer.from(wavBuffer));

  const durationSec = (samples.length / dsp.SAMPLE_RATE).toFixed(2);
  console.log(`Rendered ${pattern.tracks.length} track(s), ${durationSec}s -> ${outPath}`);
}

main();
