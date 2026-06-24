"""Procedural music generator — scale, chord progressions, Markov melody,
bass line, and drum track → valid Type-1 MIDI file."""

import random
from midi import (
    MidiFile, MidiTrack, MidiEvent,
    NoteOn, NoteOff, ProgramChange, TempoChange, TimeSignature,
    TrackName, EndOfTrack,
)


# ---------------------------------------------------------------------------
# Music theory primitives
# ---------------------------------------------------------------------------

# Scale intervals (semitones from root)
SCALES = {
    "major":      [0, 2, 4, 5, 7, 9, 11],
    "minor":      [0, 2, 3, 5, 7, 8, 10],
    "dorian":     [0, 2, 3, 5, 7, 9, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "pentatonic": [0, 2, 4, 7, 9],
    "minor_pent": [0, 3, 5, 7, 10],
    "blues":      [0, 3, 5, 6, 7, 10],
}

# Chord patterns as scale-degree triples (0-indexed scale degrees)
# Each element: (root_degree, quality, bass_degree)
# quality: "maj" | "min" | "dim" | "aug"
CHORD_PATTERNS = {
    "major": [
        [(0, "maj"), (3, "maj"), (4, "maj"), (0, "maj")],  # I-IV-V-I
        [(0, "maj"), (5, "min"), (3, "maj"), (4, "maj")],  # I-vi-IV-V
        [(0, "maj"), (3, "maj"), (5, "min"), (4, "maj")],  # I-IV-vi-V
        [(0, "maj"), (4, "maj"), (5, "min"), (3, "maj")],  # I-V-vi-IV
    ],
    "minor": [
        [(0, "min"), (5, "maj"), (2, "maj"), (6, "maj")],  # i-VI-III-VII
        [(0, "min"), (3, "maj"), (4, "min"), (0, "min")],  # i-III-iv-i
        [(0, "min"), (5, "maj"), (6, "maj"), (4, "min")],  # i-VI-VII-iv
    ],
    "dorian": [
        [(0, "min"), (3, "maj"), (4, "min"), (0, "min")],
        [(0, "min"), (5, "maj"), (3, "maj"), (4, "min")],
    ],
    "mixolydian": [
        [(0, "maj"), (6, "min"), (4, "maj"), (0, "maj")],
        [(0, "maj"), (3, "maj"), (6, "min"), (4, "maj")],
    ],
    "pentatonic": [
        [(0, "maj"), (2, "maj"), (4, "maj"), (2, "maj")],
    ],
    "minor_pent": [
        [(0, "min"), (2, "min"), (3, "maj"), (2, "min")],
    ],
    "blues": [
        [(0, "maj"), (3, "maj"), (4, "maj"), (0, "maj")],
    ],
}

# GM program numbers (0-indexed) for each musical role
LEAD_PROGRAMS = {
    "major":      0,    # Grand Piano
    "minor":      48,   # String Ensemble
    "dorian":     73,   # Flute
    "mixolydian": 25,   # Steel Guitar
    "pentatonic": 8,    # Celesta (chromatic perc)
    "minor_pent": 33,   # Electric Bass (finger)
    "blues":      26,   # Jazz Guitar
}
PAD_PROGRAMS = {
    "major":      48,   # String Ensemble
    "minor":      92,   # Pad 5 (bowed)
    "dorian":     88,   # Pad 1 (new age)
    "mixolydian": 89,   # Pad 2 (warm)
    "pentatonic": 88,   # Pad 1
    "minor_pent": 90,   # Pad 3 (polysynth)
    "blues":      33,   # Fingered Bass
}
BASS_PROGRAMS = {
    "major":      32,   # Acoustic Bass
    "minor":      33,   # Electric Bass
    "dorian":     34,   # Electric Bass (pick)
    "mixolydian": 33,   # Electric Bass
    "pentatonic": 32,   # Acoustic Bass
    "minor_pent": 33,   # Electric Bass
    "blues":      33,   # Electric Bass
}

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Drum note assignments
KICK = 36
SNARE = 38
HH_CLOSED = 42
HH_OPEN = 46
RIDE = 51
CRASH = 49


# ---------------------------------------------------------------------------
# Scale and chord helpers
# ---------------------------------------------------------------------------

def scale_notes(root_midi: int, scale_name: str, octave_range: int = 2) -> list[int]:
    """Return MIDI note numbers for the given scale across `octave_range` octaves."""
    intervals = SCALES[scale_name]
    notes = []
    for oct_offset in range(octave_range):
        for interval in intervals:
            notes.append(root_midi + oct_offset * 12 + interval)
    return notes


def chord_notes(root_midi: int, quality: str) -> list[int]:
    """Return the 3 MIDI notes of a triad."""
    if quality == "maj":
        return [root_midi, root_midi + 4, root_midi + 7]
    elif quality == "min":
        return [root_midi, root_midi + 3, root_midi + 7]
    elif quality == "dim":
        return [root_midi, root_midi + 3, root_midi + 6]
    elif quality == "aug":
        return [root_midi, root_midi + 4, root_midi + 8]
    else:
        return [root_midi, root_midi + 4, root_midi + 7]


def degree_to_midi(root_midi: int, scale_name: str, degree: int) -> int:
    """Convert a scale degree (0-indexed) to a MIDI note number."""
    intervals = SCALES[scale_name]
    octave, idx = divmod(degree, len(intervals))
    return root_midi + octave * 12 + intervals[idx]


# ---------------------------------------------------------------------------
# Markov melody generator
# ---------------------------------------------------------------------------

# Transition matrix: preferred intervals from current note (in scale degrees)
# Weights emphasize stepwise motion with occasional leaps
MELODY_TRANSITIONS = {
    -4: 0.5, -3: 1.0, -2: 2.0, -1: 3.0, 0: 1.5,
    1: 3.0, 2: 2.0, 3: 1.0, 4: 0.5, 5: 0.3,
}


def weighted_choice(choices: dict, rng: random.Random) -> int:
    total = sum(choices.values())
    r = rng.random() * total
    cumulative = 0.0
    for key, weight in choices.items():
        cumulative += weight
        if r <= cumulative:
            return key
    return list(choices.keys())[-1]


def generate_melody(
    scale: list[int],
    num_bars: int,
    beats_per_bar: int,
    ppqn: int,
    chord_sequence: list[list[int]],
    rng: random.Random,
    bars_per_chord: int = 2,
) -> list[MidiEvent]:
    """Generate a melodic line using a Markov chain that prefers chord tones.

    Returns a list of NoteOn/NoteOff MidiEvents.
    """
    events = []
    ticks_per_bar = beats_per_bar * ppqn
    ticks_per_beat = ppqn

    # Melody always in upper middle register
    melody_scale = [n for n in scale if 60 <= n <= 84]
    if not melody_scale:
        melody_scale = scale[:]

    current_degree = len(melody_scale) // 2  # start in middle
    current_note = melody_scale[current_degree]

    for bar in range(num_bars):
        chord_idx = (bar // bars_per_chord) % len(chord_sequence)
        chord = chord_sequence[chord_idx]
        bar_start = bar * ticks_per_bar

        # Decide rhythm for this bar: random mix of quarter and eighth notes
        subdivisions = []
        beat = 0
        while beat < beats_per_bar:
            if rng.random() < 0.3 and beat < beats_per_bar - 1:
                # Eighth note pair
                subdivisions.extend([0.5, 0.5])
                beat += 1
            else:
                # Quarter note
                subdivisions.append(1.0)
                beat += 1

        tick_offset = 0
        for beat_len in subdivisions:
            note_ticks = int(beat_len * ticks_per_beat)
            # Occasionally rest (20% chance)
            if rng.random() < 0.20:
                tick_offset += note_ticks
                continue

            # Try to land on a chord tone 40% of the time
            chord_degrees = []
            for c_note in chord:
                for j, s_note in enumerate(melody_scale):
                    if s_note % 12 == c_note % 12:
                        chord_degrees.append(j)

            if chord_degrees and rng.random() < 0.40:
                # Jump to nearest chord tone
                target = min(chord_degrees, key=lambda d: abs(d - current_degree))
                next_degree = target
            else:
                # Markov step
                transitions = {}
                for delta, weight in MELODY_TRANSITIONS.items():
                    nd = current_degree + delta
                    if 0 <= nd < len(melody_scale):
                        transitions[delta] = weight
                if not transitions:
                    transitions = {0: 1.0}
                delta = weighted_choice(transitions, rng)
                next_degree = max(0, min(len(melody_scale) - 1,
                                         current_degree + delta))

            current_degree = next_degree
            next_note = melody_scale[current_degree]

            abs_tick = bar_start + tick_offset
            velocity = rng.randint(70, 100)
            # Shorten note slightly (80-95% of beat_len)
            held_ticks = int(note_ticks * rng.uniform(0.80, 0.95))
            held_ticks = max(1, held_ticks)

            events.append(MidiEvent(abs_tick, NoteOn(0, next_note, velocity)))
            events.append(MidiEvent(abs_tick + held_ticks, NoteOff(0, next_note, 0)))

            tick_offset += note_ticks

    return events


# ---------------------------------------------------------------------------
# Chord pad generator
# ---------------------------------------------------------------------------

def generate_chords(
    root_midi: int,
    scale_name: str,
    chord_pattern: list[tuple[int, str]],
    num_bars: int,
    beats_per_bar: int,
    ppqn: int,
    channel: int,
    bars_per_chord: int = 2,
) -> list[MidiEvent]:
    """Generate block chords that change every `bars_per_chord` bars."""
    events = []
    ticks_per_bar = beats_per_bar * ppqn

    for bar in range(0, num_bars, bars_per_chord):
        chord_idx = (bar // bars_per_chord) % len(chord_pattern)
        degree, quality = chord_pattern[chord_idx]
        chord_root = degree_to_midi(root_midi, scale_name, degree)  # mid register (4th octave)
        notes = chord_notes(chord_root, quality)

        abs_tick = bar * ticks_per_bar
        dur_ticks = bars_per_chord * ticks_per_bar - ppqn // 4  # slight gap

        for note in notes:
            if 0 <= note <= 127:
                events.append(MidiEvent(abs_tick, NoteOn(channel, note, 60)))
                events.append(MidiEvent(abs_tick + dur_ticks, NoteOff(channel, note, 0)))

    return events


# ---------------------------------------------------------------------------
# Bass line generator
# ---------------------------------------------------------------------------

def generate_bass(
    root_midi: int,
    scale_name: str,
    chord_pattern: list[tuple[int, str]],
    num_bars: int,
    beats_per_bar: int,
    ppqn: int,
    channel: int,
    bars_per_chord: int = 2,
    rng: random.Random = None,
) -> list[MidiEvent]:
    """Walking bass line following chord roots and fifths."""
    if rng is None:
        rng = random.Random(42)
    events = []
    ticks_per_bar = beats_per_bar * ppqn
    ticks_per_beat = ppqn

    for bar in range(num_bars):
        chord_idx = (bar // bars_per_chord) % len(chord_pattern)
        degree, quality = chord_pattern[chord_idx]
        chord_root_midi = degree_to_midi(root_midi - 24, scale_name, degree)
        chord_fifth = chord_root_midi + 7
        chord_third = chord_root_midi + (4 if quality == "maj" else 3)

        bass_notes_pool = [chord_root_midi, chord_fifth, chord_third,
                           chord_root_midi - 2, chord_root_midi + 2]
        bass_notes_pool = [n for n in bass_notes_pool if 28 <= n <= 60]
        if not bass_notes_pool:
            bass_notes_pool = [chord_root_midi]

        bar_start = bar * ticks_per_bar

        for beat in range(beats_per_bar):
            abs_tick = bar_start + beat * ticks_per_beat
            # Beat 1: always root
            if beat == 0:
                note = chord_root_midi
            else:
                note = rng.choice(bass_notes_pool)
            velocity = 90 if beat == 0 else 70
            held_ticks = int(ticks_per_beat * 0.85)
            events.append(MidiEvent(abs_tick, NoteOn(channel, note, velocity)))
            events.append(MidiEvent(abs_tick + held_ticks, NoteOff(channel, note, 0)))

    return events


# ---------------------------------------------------------------------------
# Drum track generator
# ---------------------------------------------------------------------------

def generate_drums(
    num_bars: int,
    beats_per_bar: int,
    ppqn: int,
    channel: int,
    style: str = "standard",
    rng: random.Random = None,
) -> list[MidiEvent]:
    """Generate a drum pattern at 16th-note resolution."""
    if rng is None:
        rng = random.Random(42)
    events = []
    ticks_per_bar = beats_per_bar * ppqn
    ticks_per_16th = ppqn // 4

    # Pattern templates (16 steps per bar, each step = sixteenth note)
    if style == "standard":
        kick_pattern  = [1,0,0,0, 0,0,0,0, 1,0,0,0, 0,0,0,0]
        snare_pattern = [0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0]
        hh_pattern    = [1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0]
    elif style == "rock":
        kick_pattern  = [1,0,0,0, 0,0,1,0, 1,0,0,0, 0,0,0,0]
        snare_pattern = [0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0]
        hh_pattern    = [1,1,1,1, 1,1,1,1, 1,1,1,1, 1,1,1,1]
    elif style == "jazz":
        kick_pattern  = [1,0,0,0, 0,0,0,0, 0,0,1,0, 0,0,0,0]
        snare_pattern = [0,0,0,0, 0,0,1,0, 0,0,0,0, 0,1,0,0]
        hh_pattern    = [1,0,1,0, 0,0,1,0, 1,0,1,0, 0,0,1,0]
    elif style == "electronic":
        kick_pattern  = [1,0,0,0, 1,0,0,0, 1,0,0,0, 1,0,0,0]
        snare_pattern = [0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,1,0]
        hh_pattern    = [1,0,1,1, 1,0,1,0, 1,1,1,0, 1,0,1,1]
    else:
        kick_pattern  = [1,0,0,0, 0,0,0,0, 1,0,0,0, 0,0,0,0]
        snare_pattern = [0,0,0,0, 1,0,0,0, 0,0,0,0, 1,0,0,0]
        hh_pattern    = [1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0]

    for bar in range(num_bars):
        bar_start = bar * ticks_per_bar
        for step in range(16):
            tick = bar_start + step * ticks_per_16th
            hold = max(1, int(ticks_per_16th * 0.5))

            # Occasional variation
            if step > 0 and rng.random() < 0.05:
                # Ghost snare
                events.append(MidiEvent(tick, NoteOn(channel, SNARE, 40)))
                events.append(MidiEvent(tick + hold, NoteOff(channel, SNARE, 0)))

            if kick_pattern[step]:
                vel = 100 + rng.randint(-8, 8)
                events.append(MidiEvent(tick, NoteOn(channel, KICK, vel)))
                events.append(MidiEvent(tick + hold, NoteOff(channel, KICK, 0)))
            if snare_pattern[step]:
                vel = 90 + rng.randint(-10, 10)
                events.append(MidiEvent(tick, NoteOn(channel, SNARE, vel)))
                events.append(MidiEvent(tick + hold, NoteOff(channel, SNARE, 0)))
            if hh_pattern[step]:
                vel = 65 + rng.randint(-10, 10)
                hh_note = HH_OPEN if step % 8 == 0 else HH_CLOSED
                events.append(MidiEvent(tick, NoteOn(channel, hh_note, vel)))
                events.append(MidiEvent(tick + hold, NoteOff(channel, hh_note, 0)))

        # Crash on bar 1 and every 8 bars
        if bar == 0 or bar % 8 == 0:
            events.append(MidiEvent(bar_start, NoteOn(channel, CRASH, 100)))
            events.append(MidiEvent(bar_start + ticks_per_16th, NoteOff(channel, CRASH, 0)))

    return events


# ---------------------------------------------------------------------------
# Main composition entry point
# ---------------------------------------------------------------------------

def generate_piece(
    key: int = 60,          # MIDI note of the root (C4 = 60)
    scale_name: str = "major",
    num_bars: int = 32,
    bpm: int = 120,
    beats_per_bar: int = 4,
    drum_style: str = "standard",
    seed: int | None = None,
) -> MidiFile:
    """Generate a complete multi-track piece as a Type-1 MIDI file.

    Tracks:
      0 — tempo/time-sig (empty notes)
      1 — melody (lead instrument)
      2 — chords (pad)
      3 — bass
      4 — drums (channel 9)
    """
    rng = random.Random(seed)
    ppqn = 480
    us_per_beat = int(60_000_000 / bpm)

    # Choose chord pattern
    mode_family = "major" if scale_name in ("major", "mixolydian") else \
                  "minor" if scale_name in ("minor", "dorian") else scale_name
    patterns = CHORD_PATTERNS.get(scale_name, CHORD_PATTERNS.get(mode_family, CHORD_PATTERNS["major"]))
    chord_pattern = rng.choice(patterns)

    # Build chord note sequences for melody guide
    chord_sequences = []
    for degree, quality in chord_pattern:
        chord_root = degree_to_midi(key, scale_name, degree)
        chord_sequences.append(chord_notes(chord_root, quality))

    all_scale_notes = scale_notes(key, scale_name, octave_range=3)
    melody_scale = [n for n in all_scale_notes if 55 <= n <= 88]
    if not melody_scale:
        melody_scale = all_scale_notes

    midi = MidiFile(format=1, ticks_per_beat=ppqn)

    # Track 0: tempo track
    t0 = MidiTrack()
    t0.events.append(MidiEvent(0, TempoChange(us_per_beat)))
    t0.events.append(MidiEvent(0, TimeSignature(beats_per_bar, 4, 24, 8)))
    t0.events.append(MidiEvent(0, TrackName("Tempo")))
    t0.events.append(MidiEvent(num_bars * beats_per_bar * ppqn + ppqn, EndOfTrack()))
    midi.tracks.append(t0)

    # Track 1: melody
    t1 = MidiTrack()
    t1.events.append(MidiEvent(0, TrackName("Melody")))
    lead_prog = LEAD_PROGRAMS.get(scale_name, 0)
    t1.events.append(MidiEvent(0, ProgramChange(0, lead_prog)))
    melody_evs = generate_melody(
        melody_scale, num_bars, beats_per_bar, ppqn,
        chord_sequences, rng, bars_per_chord=2,
    )
    t1.events.extend(melody_evs)
    last_melody = max((e.tick for e in melody_evs), default=0)
    t1.events.append(MidiEvent(last_melody + ppqn, EndOfTrack()))
    midi.tracks.append(t1)

    # Track 2: chords
    t2 = MidiTrack()
    t2.events.append(MidiEvent(0, TrackName("Chords")))
    pad_prog = PAD_PROGRAMS.get(scale_name, 48)
    t2.events.append(MidiEvent(0, ProgramChange(1, pad_prog)))
    chord_evs = generate_chords(
        key, scale_name, chord_pattern,
        num_bars, beats_per_bar, ppqn,
        channel=1, bars_per_chord=2,
    )
    t2.events.extend(chord_evs)
    last_chord = max((e.tick for e in chord_evs), default=0)
    t2.events.append(MidiEvent(last_chord + ppqn, EndOfTrack()))
    midi.tracks.append(t2)

    # Track 3: bass
    t3 = MidiTrack()
    t3.events.append(MidiEvent(0, TrackName("Bass")))
    bass_prog = BASS_PROGRAMS.get(scale_name, 32)
    t3.events.append(MidiEvent(0, ProgramChange(2, bass_prog)))
    bass_evs = generate_bass(
        key, scale_name, chord_pattern,
        num_bars, beats_per_bar, ppqn,
        channel=2, bars_per_chord=2, rng=rng,
    )
    t3.events.extend(bass_evs)
    last_bass = max((e.tick for e in bass_evs), default=0)
    t3.events.append(MidiEvent(last_bass + ppqn, EndOfTrack()))
    midi.tracks.append(t3)

    # Track 4: drums (channel 9)
    t4 = MidiTrack()
    t4.events.append(MidiEvent(0, TrackName("Drums")))
    drum_evs = generate_drums(
        num_bars, beats_per_bar, ppqn,
        channel=9, style=drum_style, rng=rng,
    )
    t4.events.extend(drum_evs)
    last_drum = max((e.tick for e in drum_evs), default=0)
    t4.events.append(MidiEvent(last_drum + ppqn, EndOfTrack()))
    midi.tracks.append(t4)

    return midi
