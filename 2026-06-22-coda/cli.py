#!/usr/bin/env python3
"""Coda — MIDI Synthesizer & Procedural Music Generator

Usage:
  coda generate  [--key KEY] [--scale SCALE] [--bpm BPM] [--bars N]
                 [--drums STYLE] [--seed SEED] [--out FILE.mid]
  coda render    <file.mid> [--out FILE.wav] [--reverb] [--delay] [--lpf]
  coda viz       <file.mid> [--out FILE.html] [--title TITLE]
  coda info      <file.mid>
  coda demo
  coda help
"""

import sys
import os

# Add project directory to path
sys.path.insert(0, os.path.dirname(__file__))

from midi import parse_midi_file, write_midi_file, NoteOn, TempoChange
from generator import generate_piece, SCALES, NOTE_NAMES
from renderer import render_midi
from effects import apply_effects
from wav import AudioBuffer
from viz import write_html


# ---------------------------------------------------------------------------
# Subcommand helpers
# ---------------------------------------------------------------------------

def cmd_generate(args: list[str]):
    """Generate a procedural MIDI piece."""
    key = 60
    scale_name = "major"
    bpm = 120
    num_bars = 32
    drum_style = "standard"
    seed = None
    out = "output.mid"

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--key" and i + 1 < len(args):
            i += 1
            # Accept note name (C, D#, etc.) or MIDI number
            val = args[i]
            try:
                key = int(val)
            except ValueError:
                note_names = NOTE_NAMES
                name = val.upper().replace("♯", "#").replace("b", "")
                if name in note_names:
                    key = 48 + note_names.index(name)
                else:
                    die(f"Unknown note name: {val}. Use C, D, E, F, G, A, B (with optional #)")
        elif a == "--scale" and i + 1 < len(args):
            i += 1
            if args[i] not in SCALES:
                die(f"Unknown scale '{args[i]}'. Available: {', '.join(SCALES)}")
            scale_name = args[i]
        elif a == "--bpm" and i + 1 < len(args):
            i += 1
            try:
                bpm = int(args[i])
                if not (20 <= bpm <= 300):
                    die("BPM must be between 20 and 300")
            except ValueError:
                die(f"Invalid BPM: {args[i]}")
        elif a == "--bars" and i + 1 < len(args):
            i += 1
            try:
                num_bars = int(args[i])
                if not (4 <= num_bars <= 256):
                    die("Bars must be between 4 and 256")
            except ValueError:
                die(f"Invalid bar count: {args[i]}")
        elif a == "--drums" and i + 1 < len(args):
            i += 1
            valid = ("standard", "rock", "jazz", "electronic")
            if args[i] not in valid:
                die(f"Unknown drum style '{args[i]}'. Available: {', '.join(valid)}")
            drum_style = args[i]
        elif a == "--seed" and i + 1 < len(args):
            i += 1
            try:
                seed = int(args[i])
            except ValueError:
                die(f"Invalid seed: {args[i]}")
        elif a == "--out" and i + 1 < len(args):
            i += 1
            out = args[i]
        elif a.startswith("-"):
            die(f"Unknown option: {a}")
        i += 1

    note_name = NOTE_NAMES[key % 12]
    print(f"Generating {num_bars}-bar piece in {note_name} {scale_name}, "
          f"{bpm} BPM, {drum_style} drums, seed={seed}")
    midi = generate_piece(
        key=key, scale_name=scale_name, bpm=bpm,
        num_bars=num_bars, drum_style=drum_style, seed=seed,
    )
    write_midi_file(midi, out)
    total_notes = sum(
        1 for t in midi.tracks for e in t.events if isinstance(e.event, NoteOn)
    )
    print(f"Written {out}  ({len(midi.tracks)} tracks, {total_notes} notes)")


def cmd_render(args: list[str]):
    """Render a MIDI file to WAV."""
    if not args:
        die("Usage: coda render <file.mid> [--out FILE.wav] [--reverb] [--delay] [--lpf]")
    midi_path = args[0]
    out = os.path.splitext(midi_path)[0] + ".wav"
    do_reverb = False
    do_delay = False
    do_lpf = False

    i = 1
    while i < len(args):
        a = args[i]
        if a == "--out" and i + 1 < len(args):
            i += 1
            out = args[i]
        elif a == "--reverb":
            do_reverb = True
        elif a == "--delay":
            do_delay = True
        elif a == "--lpf":
            do_lpf = True
        elif a.startswith("-"):
            die(f"Unknown option: {a}")
        i += 1

    if not os.path.isfile(midi_path):
        die(f"File not found: {midi_path}")

    print(f"Parsing {midi_path}...")
    midi = parse_midi_file(midi_path)

    total_notes = sum(
        1 for t in midi.tracks for e in t.events if isinstance(e.event, NoteOn)
    )
    print(f"  Format {midi.format}, {len(midi.tracks)} tracks, "
          f"{midi.ticks_per_beat} PPQN, {total_notes} notes")

    print("Rendering audio...")
    buf = render_midi(midi)
    duration = buf.num_samples / 44100

    if do_reverb or do_delay or do_lpf:
        effects_str = " + ".join(
            x for x, y in [("reverb", do_reverb), ("delay", do_delay), ("LPF", do_lpf)] if y
        )
        print(f"Applying effects: {effects_str}")
        apply_effects(buf, reverb=do_reverb, delay=do_delay, lpf=do_lpf)

    buf.write_wav(out)
    print(f"Written {out}  ({duration:.1f}s, peak={buf.peak():.3f})")


def cmd_viz(args: list[str]):
    """Generate a piano roll HTML visualizer."""
    if not args:
        die("Usage: coda viz <file.mid> [--out FILE.html] [--title TITLE]")
    midi_path = args[0]
    out = os.path.splitext(midi_path)[0] + "_roll.html"
    title = "Coda — Piano Roll"

    i = 1
    while i < len(args):
        a = args[i]
        if a == "--out" and i + 1 < len(args):
            i += 1
            out = args[i]
        elif a == "--title" and i + 1 < len(args):
            i += 1
            title = args[i]
        elif a.startswith("-"):
            die(f"Unknown option: {a}")
        i += 1

    if not os.path.isfile(midi_path):
        die(f"File not found: {midi_path}")

    print(f"Parsing {midi_path}...")
    midi = parse_midi_file(midi_path)
    print(f"Writing visualizer to {out}...")
    size = write_html(midi, out, title)
    print(f"Written {out}  ({size:,} bytes)  — open in a browser to view and play")


def cmd_info(args: list[str]):
    """Print information about a MIDI file."""
    if not args:
        die("Usage: coda info <file.mid>")
    midi_path = args[0]
    if not os.path.isfile(midi_path):
        die(f"File not found: {midi_path}")

    midi = parse_midi_file(midi_path)

    print(f"File:        {midi_path}")
    print(f"Format:      Type {midi.format}")
    print(f"Ticks/beat:  {midi.ticks_per_beat} PPQN")
    print(f"Tracks:      {len(midi.tracks)}")

    from midi import TempoChange, TimeSignature, TrackName, NoteOn
    for i, track in enumerate(midi.tracks):
        name = f"Track {i}"
        note_count = 0
        for ev in track.events:
            if isinstance(ev.event, TrackName):
                name = ev.event.name
            elif isinstance(ev.event, NoteOn):
                note_count += 1
        max_tick = max((e.tick for e in track.events), default=0)
        print(f"  [{i}] {name:<20} {note_count:4d} notes  last_tick={max_tick}")

    # Tempo events from track 0
    tempos = [(ev.tick, ev.event.us_per_beat)
              for ev in midi.tracks[0].events if isinstance(ev.event, TempoChange)]
    if tempos:
        bpm_list = [f"{int(60_000_000 / us)} BPM @ tick {tick}" for tick, us in tempos]
        print(f"Tempo:       {', '.join(bpm_list)}")


def cmd_demo(args: list[str]):
    """Run a full demonstration: generate, render, and visualize."""
    import tempfile
    print("=" * 60)
    print("Coda Demo — Procedural Music Generation")
    print("=" * 60)

    demos = [
        ("C major, jazz drums, 120 BPM",
         {"key": 60, "scale_name": "major", "bpm": 120, "num_bars": 16,
          "drum_style": "jazz", "seed": 42}),
        ("A minor, rock drums, 140 BPM",
         {"key": 57, "scale_name": "minor", "bpm": 140, "num_bars": 16,
          "drum_style": "rock", "seed": 7}),
        ("D dorian, standard drums, 100 BPM",
         {"key": 62, "scale_name": "dorian", "bpm": 100, "num_bars": 16,
          "drum_style": "standard", "seed": 99}),
        ("G blues, electronic drums, 110 BPM",
         {"key": 55, "scale_name": "blues", "bpm": 110, "num_bars": 16,
          "drum_style": "electronic", "seed": 2026}),
    ]

    for desc, kwargs in demos:
        print(f"\n>> {desc}")
        midi = generate_piece(**kwargs)
        total_notes = sum(1 for t in midi.tracks for e in t.events
                          if isinstance(e.event, NoteOn))
        print(f"   Generated {total_notes} notes across {len(midi.tracks)} tracks")

        # Quick render (low gain for speed check)
        buf = render_midi(midi)
        duration = buf.num_samples / 44100
        peak = buf.peak()
        print(f"   Rendered: {duration:.1f}s audio, peak={peak:.3f}")
        if peak < 0.01:
            print("   WARNING: very low output level")
        else:
            print("   Audio OK")

        # Write MIDI
        midi_path = f"demo_{kwargs['seed']}.mid"
        write_midi_file(midi, midi_path)
        print(f"   MIDI written: {midi_path}")

        # Write WAV
        wav_path = f"demo_{kwargs['seed']}.wav"
        buf.write_wav(wav_path)
        print(f"   WAV  written: {wav_path}")

        # Write HTML
        html_path = f"demo_{kwargs['seed']}_roll.html"
        write_html(midi, html_path, title=f"Coda — {desc}")
        print(f"   HTML written: {html_path}")

    print("\nDemo complete. Open the _roll.html files in a browser to visualize and play.")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def die(msg: str, code: int = 1):
    print(f"Error: {msg}", file=sys.stderr)
    sys.exit(code)


COMMANDS = {
    "generate": cmd_generate,
    "render":   cmd_render,
    "viz":      cmd_viz,
    "info":     cmd_info,
    "demo":     cmd_demo,
}


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        sys.exit(0)
    cmd = args[0]
    if cmd not in COMMANDS:
        die(f"Unknown command '{cmd}'. Run 'coda help' for usage.")
    COMMANDS[cmd](args[1:])


if __name__ == "__main__":
    main()
