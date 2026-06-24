#!/usr/bin/env python3
"""Cadence — modular music synthesizer and procedural composer.

Sub-commands:
  compose   Generate a full musical composition
  synth     Synthesize a single note or arpeggio
  visualize Create an HTML visualizer from a WAV file
  demo      Run a complete demo (compose + visualize for each style)
  info      Print waveform and filter information
"""

import argparse
import json
import os
import sys
import time
import math

# Allow running from the project root directly
sys.path.insert(0, os.path.dirname(__file__))

from synth.core import parse_note, note_to_freq, SAMPLE_RATE
from synth.composer import compose, STYLES, SCALES
from synth.sequencer import render, Sequence, Track, NoteEvent
from synth.effects import Reverb, normalize_peak
from synth.wav import save as wav_save, load as wav_load, encode as wav_encode
from synth.visualizer import generate_html
from synth.voice import render_note, render_drum


def _parse_key(key_str: str) -> int:
    """Parse key string like 'Am', 'C', 'G#' → MIDI root in octave 4."""
    key_str = key_str.strip()
    # Handle minor indicator
    is_minor = key_str.endswith('m')
    root_str = key_str.rstrip('m')
    # Parse as note in octave 4
    try:
        return parse_note(root_str + '4')
    except ValueError:
        # Try direct MIDI number
        try:
            return int(key_str)
        except ValueError:
            pass
    raise ValueError(f"Cannot parse key: {key_str!r} — use e.g. 'C', 'Am', 'G#'")


def cmd_compose(args):
    """Generate a musical composition."""
    key = _parse_key(args.key)
    style = args.style
    if style not in STYLES:
        sys.exit(f"Unknown style {style!r}. Choices: {', '.join(STYLES)}")

    bpm = args.bpm
    bars = args.bars
    seed = args.seed
    output = args.output

    print(f"[cadence] composing: style={style}, key={args.key}, "
          f"bpm={bpm or 'auto'}, bars={bars}, seed={seed}")

    t0 = time.time()
    seq = compose(key=key, style=style, bpm=bpm, bars=bars, seed=seed)
    print(f"[cadence] sequence: {seq.bpm:.0f} BPM, {seq.total_steps} steps, "
          f"{len(seq.tracks)} tracks")

    import random
    rng = random.Random(seed)

    dur_s = seq.total_samples / SAMPLE_RATE
    print(f"[cadence] rendering {dur_s:.1f}s audio ...")
    t_render = time.time()
    left, right = render(seq, rng=rng)
    print(f"[cadence] render done in {time.time()-t_render:.1f}s, applying effects ...")

    # Apply reverb
    rev_wet = STYLES[style]['reverb']
    if rev_wet > 0:
        rev = Reverb(room_size=0.6, damping=0.5, wet=rev_wet,
                     dry=1.0 - rev_wet * 0.4)
        left, right = rev.process_stereo(left, right)

    # Apply chorus for styles that benefit from it
    if style in ('pop', 'jazz'):
        from synth.effects import Chorus
        ch = Chorus(rate=0.4, depth=0.002, base_delay=0.015, wet=0.15)
        left = ch.process(left)
        ch2 = Chorus(rate=0.5, depth=0.0025, base_delay=0.017, wet=0.15)
        right = ch2.process(right)

    left, right = normalize_peak(left, right, target=0.88)

    wav_bytes = wav_encode(left, right)
    with open(output, 'wb') as f:
        f.write(wav_bytes)
    elapsed = time.time() - t0
    size_mb = len(wav_bytes) / 1e6
    dur = len(left) / SAMPLE_RATE
    print(f"[cadence] wrote {output} ({dur:.1f}s, {size_mb:.2f} MB) in {elapsed:.1f}s")

    if args.html:
        html_path = args.html
        html = generate_html(wav_bytes, seq, left, title=f"Cadence — {style}")
        with open(html_path, 'w') as f:
            f.write(html)
        print(f"[cadence] wrote {html_path}")

    return seq, left, right, wav_bytes


def cmd_synth(args):
    """Synthesize a single note or arpeggio."""
    note_str = args.note
    try:
        midi = parse_note(note_str)
    except ValueError as e:
        sys.exit(str(e))

    # Load preset
    if args.preset:
        try:
            with open(args.preset) as f:
                preset = json.load(f)
        except Exception as e:
            sys.exit(f"Cannot load preset: {e}")
    else:
        preset = {
            'oscillator': args.waveform,
            'attack': 0.01, 'decay': 0.1, 'sustain': 0.7, 'release': 0.2,
            'filter_type': 'lpf', 'cutoff': 4000.0, 'resonance': 1.5,
            'volume': 0.8,
        }

    sr = SAMPLE_RATE
    dur = args.duration
    gate_n = max(1, int(dur * 0.85 * sr))
    output = args.output

    import random
    rng = random.Random(42)

    print(f"[cadence] synthesizing {note_str} (MIDI {midi}) with waveform "
          f"{preset.get('oscillator','sawtooth')} for {dur:.1f}s")

    samples = render_note(preset, midi, args.velocity, gate_n, rng)

    # Pad to full duration
    total_n = int(dur * sr)
    if len(samples) < total_n:
        samples += [0.0] * (total_n - len(samples))
    else:
        samples = samples[:total_n]

    left = samples
    right = samples
    left, right = normalize_peak(left, right)
    wav_save(output, left, right)
    print(f"[cadence] wrote {output}")


def cmd_visualize(args):
    """Create HTML visualizer from an existing WAV file."""
    wav_path = args.input
    try:
        left, right, sr = wav_load(wav_path)
    except Exception as e:
        sys.exit(f"Cannot load WAV: {e}")

    with open(wav_path, 'rb') as f:
        wav_bytes = f.read()

    title = os.path.splitext(os.path.basename(wav_path))[0]
    html = generate_html(wav_bytes, None, left, title=title)
    out_path = args.output
    with open(out_path, 'w') as f:
        f.write(html)
    print(f"[cadence] wrote {out_path}")


def cmd_demo(args):
    """Run a complete demo for all styles."""
    out_dir = args.output_dir
    os.makedirs(out_dir, exist_ok=True)

    import random

    for style in ['pop', 'jazz', 'ambient', 'electronic']:
        print(f"\n{'='*50}")
        print(f"  DEMO: {style.upper()}")
        print(f"{'='*50}")
        key_str = {'pop': 'C', 'jazz': 'A', 'ambient': 'D', 'electronic': 'Gm'}[style]
        key = _parse_key(key_str)
        seed = hash(style) % 10000

        wav_path = os.path.join(out_dir, f"cadence_{style}.wav")
        html_path = os.path.join(out_dir, f"cadence_{style}.html")

        class FakeArgs:
            pass
        fa = FakeArgs()
        fa.key = key_str
        fa.style = style
        fa.bpm = None
        fa.bars = 8
        fa.seed = seed
        fa.output = wav_path
        fa.html = html_path

        cmd_compose(fa)

    print(f"\n[cadence] demo complete — files in {out_dir}/")

    # Also synthesize each waveform type
    print("\n[cadence] waveform showcase ...")
    for waveform in ['sine', 'sawtooth', 'square', 'triangle', 'pulse', 'noise']:
        wav_path = os.path.join(out_dir, f"cadence_osc_{waveform}.wav")
        sr = SAMPLE_RATE
        dur = 1.5
        gate_n = int(dur * 0.8 * sr)
        preset = {
            'oscillator': waveform,
            'attack': 0.02, 'decay': 0.1, 'sustain': 0.7, 'release': 0.2,
            'filter_type': 'lpf', 'cutoff': 6000.0, 'resonance': 1.0,
            'volume': 0.7,
        }
        import random as _r
        rng = _r.Random(1)
        samples = render_note(preset, 69, 100, gate_n, rng)  # A4
        total_n = int(dur * sr)
        samples = (samples + [0.0] * total_n)[:total_n]
        left, right = samples, samples
        left, right = normalize_peak(left, right)
        wav_save(wav_path, left, right)
        print(f"[cadence]   {waveform}: {wav_path}")


def cmd_info(_args):
    """Print library information."""
    print("Cadence — DSP library information")
    print()
    print("Waveforms: sine, sawtooth, rsaw, square, triangle, pulse, noise")
    print("All non-sine waveforms use PolyBLEP antialiasing.")
    print()
    print("Filters (2nd-order biquad IIR, Audio EQ Cookbook):")
    for ft in ['lpf', 'hpf', 'bpf', 'notch']:
        print(f"  {ft}")
    print()
    print("Effects: delay, reverb (Freeverb), soft_clip, chorus")
    print()
    print("Styles:", ', '.join(STYLES.keys()))
    print("Scales:", ', '.join(SCALES.keys()))
    print(f"Sample rate: {SAMPLE_RATE} Hz, 16-bit stereo WAV")


def main():
    parser = argparse.ArgumentParser(
        prog='cadence',
        description='Cadence: modular music synthesizer and procedural composer',
    )
    sub = parser.add_subparsers(dest='cmd', required=True)

    # compose
    p_comp = sub.add_parser('compose', help='Generate a musical composition')
    p_comp.add_argument('--key', default='C', help='Root note (e.g. C, Am, G#)')
    p_comp.add_argument('--style', default='pop',
                        choices=list(STYLES.keys()), help='Musical style')
    p_comp.add_argument('--bpm', type=float, default=None, help='BPM (auto if not set)')
    p_comp.add_argument('--bars', type=int, default=8, help='Number of bars')
    p_comp.add_argument('--seed', type=int, default=42, help='Random seed')
    p_comp.add_argument('--output', '-o', default='composition.wav', help='Output WAV file')
    p_comp.add_argument('--html', default=None, help='Also write HTML visualizer')

    # synth
    p_syn = sub.add_parser('synth', help='Synthesize a single note')
    p_syn.add_argument('--note', default='A4', help='Note name (e.g. A4, C#3)')
    p_syn.add_argument('--waveform', default='sawtooth',
                       choices=['sine','sawtooth','rsaw','square','triangle','pulse','noise'])
    p_syn.add_argument('--duration', type=float, default=2.0, help='Duration in seconds')
    p_syn.add_argument('--velocity', type=int, default=100, help='MIDI velocity 0-127')
    p_syn.add_argument('--preset', default=None, help='JSON preset file')
    p_syn.add_argument('--output', '-o', default='note.wav', help='Output WAV file')

    # visualize
    p_viz = sub.add_parser('visualize', help='Create HTML visualizer from WAV')
    p_viz.add_argument('--input', '-i', required=True, help='Input WAV file')
    p_viz.add_argument('--output', '-o', default='visualization.html', help='Output HTML')

    # demo
    p_demo = sub.add_parser('demo', help='Run full demo (all styles)')
    p_demo.add_argument('--output-dir', default='demo_output', help='Output directory')

    # info
    sub.add_parser('info', help='Print library information')

    args = parser.parse_args()

    if args.cmd == 'compose':
        cmd_compose(args)
    elif args.cmd == 'synth':
        cmd_synth(args)
    elif args.cmd == 'visualize':
        cmd_visualize(args)
    elif args.cmd == 'demo':
        cmd_demo(args)
    elif args.cmd == 'info':
        cmd_info(args)


if __name__ == '__main__':
    main()
