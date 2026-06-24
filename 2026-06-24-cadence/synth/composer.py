"""Procedural music composer.

Given a key, scale, style, and seed, generates a complete Sequence that
can be rendered to audio by the sequencer. Covers:
- Scale/mode selection
- Chord progression selection
- Melodic phrase generation (scale-constrained + chord-tone leaning)
- Bass line generation (root/fifth or walking)
- Drum pattern generation (kick/snare/hihat) with style-specific feel
- Preset assignment per track

All random decisions route through the seeded RNG for reproducibility.
"""

import random
import math
from typing import List, Tuple, Optional

from .core import note_to_freq, SAMPLE_RATE
from .sequencer import Sequence, Track, NoteEvent

# ---------------------------------------------------------------------------
# Music theory tables
# ---------------------------------------------------------------------------

SCALES = {
    'major':           [0, 2, 4, 5, 7, 9, 11],
    'minor':           [0, 2, 3, 5, 7, 8, 10],
    'dorian':          [0, 2, 3, 5, 7, 9, 10],
    'phrygian':        [0, 1, 3, 5, 7, 8, 10],
    'lydian':          [0, 2, 4, 6, 7, 9, 11],
    'mixolydian':      [0, 2, 4, 5, 7, 9, 10],
    'pentatonic_minor':[0, 3, 5, 7, 10],
    'pentatonic_major':[0, 2, 4, 7, 9],
    'blues':           [0, 3, 5, 6, 7, 10],
}

# Chord progressions as (degree, is_minor) tuples (1-based scale degree)
# degree 1 = tonic, 4 = subdominant, 5 = dominant, etc.
PROGRESSIONS = {
    'major': [
        [(1, False), (6, True),  (4, False), (5, False)],  # I–vi–IV–V (pop)
        [(1, False), (4, False), (5, False), (1, False)],  # I–IV–V–I
        [(1, False), (5, False), (6, True),  (4, False)],  # I–V–vi–IV
        [(2, True),  (5, False), (1, False), (1, False)],  # ii–V–I (jazz)
    ],
    'minor': [
        [(1, True),  (7, False), (6, False), (7, False)],  # i–VII–VI–VII
        [(1, True),  (4, True),  (5, False), (1, True)],   # i–iv–V–i
        [(6, False), (7, False), (1, True),  (1, True)],   # VI–VII–i
        [(1, True),  (6, False), (3, False), (7, False)],  # i–VI–III–VII
    ],
}

# Style-specific settings
STYLES = {
    'pop': {
        'scale': 'major', 'bpm_range': (100, 130), 'bars': 8,
        'melody_density': 0.65, 'melody_oct': 5,
        'bass_pattern': 'root_fifth', 'bass_oct': 2,
        'has_drums': True, 'drum_feel': 'straight',
        'reverb': 0.25, 'delay': 0.0,
    },
    'jazz': {
        'scale': 'dorian', 'bpm_range': (100, 140), 'bars': 8,
        'melody_density': 0.55, 'melody_oct': 5,
        'bass_pattern': 'walking', 'bass_oct': 2,
        'has_drums': True, 'drum_feel': 'swing',
        'reverb': 0.35, 'delay': 0.0,
    },
    'ambient': {
        'scale': 'lydian', 'bpm_range': (60, 80), 'bars': 8,
        'melody_density': 0.35, 'melody_oct': 5,
        'bass_pattern': 'pedal', 'bass_oct': 2,
        'has_drums': False, 'drum_feel': 'none',
        'reverb': 0.65, 'delay': 0.4,
    },
    'electronic': {
        'scale': 'minor', 'bpm_range': (120, 140), 'bars': 8,
        'melody_density': 0.70, 'melody_oct': 5,
        'bass_pattern': 'root', 'bass_oct': 2,
        'has_drums': True, 'drum_feel': 'four_on_floor',
        'reverb': 0.20, 'delay': 0.3,
    },
}

# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------

PRESETS = {
    'lead_pop': {
        'oscillator': 'sawtooth', 'pw': 0.5,
        'sub_mix': 0.2, 'detune_cents': 7.0,
        'attack': 0.01, 'decay': 0.08, 'sustain': 0.6, 'release': 0.12,
        'filter_type': 'lpf', 'cutoff': 3500.0, 'resonance': 1.5,
        'filter_env_amount': 12.0,
        'lfo_rate': 5.5, 'lfo_depth': 0.3, 'lfo_target': 'pitch',
        'volume': 0.55,
    },
    'lead_jazz': {
        'oscillator': 'sawtooth', 'pw': 0.5,
        'sub_mix': 0.0, 'detune_cents': 0.0,
        'attack': 0.02, 'decay': 0.12, 'sustain': 0.5, 'release': 0.18,
        'filter_type': 'lpf', 'cutoff': 4000.0, 'resonance': 1.2,
        'filter_env_amount': 8.0,
        'lfo_rate': 4.5, 'lfo_depth': 0.4, 'lfo_target': 'pitch',
        'volume': 0.5,
    },
    'lead_ambient': {
        'oscillator': 'sine', 'pw': 0.5,
        'sub_mix': 0.3, 'detune_cents': 5.0,
        'attack': 0.35, 'decay': 0.5, 'sustain': 0.7, 'release': 1.0,
        'filter_type': 'lpf', 'cutoff': 2000.0, 'resonance': 2.0,
        'filter_env_amount': 6.0,
        'lfo_rate': 0.3, 'lfo_depth': 0.5, 'lfo_target': 'pitch',
        'volume': 0.6,
    },
    'lead_electronic': {
        'oscillator': 'square', 'pw': 0.5,
        'sub_mix': 0.15, 'detune_cents': 10.0,
        'attack': 0.005, 'decay': 0.1, 'sustain': 0.4, 'release': 0.08,
        'filter_type': 'lpf', 'cutoff': 2500.0, 'resonance': 3.0,
        'filter_env_amount': 18.0,
        'lfo_rate': 2.0, 'lfo_depth': 0.0, 'lfo_target': 'pitch',
        'volume': 0.5,
    },
    'bass_pop': {
        'oscillator': 'sawtooth', 'pw': 0.5,
        'sub_mix': 0.5, 'detune_cents': 0.0,
        'attack': 0.005, 'decay': 0.1, 'sustain': 0.6, 'release': 0.08,
        'filter_type': 'lpf', 'cutoff': 800.0, 'resonance': 1.8,
        'filter_env_amount': 6.0,
        'lfo_rate': 0.0, 'lfo_depth': 0.0, 'lfo_target': 'pitch',
        'volume': 0.7,
    },
    'bass_jazz': {
        'oscillator': 'triangle', 'pw': 0.5,
        'sub_mix': 0.0, 'detune_cents': 0.0,
        'attack': 0.01, 'decay': 0.15, 'sustain': 0.4, 'release': 0.12,
        'filter_type': 'lpf', 'cutoff': 600.0, 'resonance': 1.0,
        'filter_env_amount': 0.0,
        'lfo_rate': 0.0, 'lfo_depth': 0.0, 'lfo_target': 'pitch',
        'volume': 0.75,
    },
    'bass_ambient': {
        'oscillator': 'sine', 'pw': 0.5,
        'sub_mix': 0.0, 'detune_cents': 0.0,
        'attack': 0.5, 'decay': 0.5, 'sustain': 0.8, 'release': 1.5,
        'filter_type': 'lpf', 'cutoff': 400.0, 'resonance': 1.0,
        'filter_env_amount': 0.0,
        'lfo_rate': 0.0, 'lfo_depth': 0.0, 'lfo_target': 'pitch',
        'volume': 0.6,
    },
    'bass_electronic': {
        'oscillator': 'sawtooth', 'pw': 0.5,
        'sub_mix': 0.3, 'detune_cents': 0.0,
        'attack': 0.005, 'decay': 0.05, 'sustain': 0.3, 'release': 0.05,
        'filter_type': 'lpf', 'cutoff': 600.0, 'resonance': 4.0,
        'filter_env_amount': 24.0,
        'lfo_rate': 0.0, 'lfo_depth': 0.0, 'lfo_target': 'pitch',
        'volume': 0.8,
    },
    'pad': {
        'oscillator': 'sawtooth', 'pw': 0.5,
        'sub_mix': 0.4, 'detune_cents': 12.0,
        'attack': 0.4, 'decay': 0.5, 'sustain': 0.8, 'release': 0.8,
        'filter_type': 'lpf', 'cutoff': 1200.0, 'resonance': 1.5,
        'filter_env_amount': 4.0,
        'lfo_rate': 0.2, 'lfo_depth': 0.8, 'lfo_target': 'filter',
        'volume': 0.35,
    },
}


# ---------------------------------------------------------------------------
# Music-theory helpers
# ---------------------------------------------------------------------------

def scale_notes_in_range(root: int, scale: list, lo: int, hi: int) -> list:
    """All MIDI pitches in [lo, hi] that belong to the scale rooted at root."""
    notes = []
    for octave in range(-1, 10):
        for s in scale:
            n = root + s + 12 * octave
            if lo <= n <= hi:
                notes.append(n)
    return sorted(notes)


def chord_pitches(root: int, scale: list, degree: int, is_minor: bool,
                  bass_oct: int = 3) -> list:
    """Return root + third + fifth of the triad on the given scale degree."""
    n = len(scale)
    idx = (degree - 1) % n
    # Build intervals for a triad on this degree
    root_semi = root + scale[idx]
    third_semi = root + scale[(idx + 2) % n]
    fifth_semi = root + scale[(idx + 4) % n]

    # Map to absolute MIDI in a useful octave range
    base = (bass_oct + 1) * 12 + root_semi % 12
    third = base + ((third_semi - root_semi) % 12)
    if third <= base:
        third += 12
    fifth = base + ((fifth_semi - root_semi) % 12)
    if fifth <= third:
        fifth += 12
    return [base, third, fifth]


def nearest_scale_note(pitch: int, scale_pitches: list) -> int:
    """Return the scale note closest to pitch."""
    return min(scale_pitches, key=lambda n: abs(n - pitch))


# ---------------------------------------------------------------------------
# Main composer entry point
# ---------------------------------------------------------------------------

def compose(
    key: int = 60,          # root MIDI note (60 = C4)
    style: str = 'pop',
    bpm: Optional[float] = None,
    bars: int = 8,
    seed: int = 42,
) -> Sequence:
    """Generate a complete Sequence for the given parameters."""
    rng = random.Random(seed)
    st = STYLES[style]

    if bpm is None:
        lo, hi = st['bpm_range']
        bpm = rng.randint(lo, hi)

    scale_name = st['scale']
    scale = SCALES[scale_name]
    steps_per_bar = 16
    total_steps = steps_per_bar * bars

    # Chord progression (one chord per bar)
    prog_family = 'minor' if scale_name in ('minor', 'phrygian', 'dorian') else 'major'
    progressions = PROGRESSIONS[prog_family]
    progression = rng.choice(progressions)

    # Stretch progression to fill bars (repeat if necessary)
    chord_seq = []
    for bar in range(bars):
        chord_seq.append(progression[bar % len(progression)])

    # Tracks
    tracks = []

    # ----- Melody track -----
    melody_oct = st['melody_oct']
    lo_pitch = (melody_oct - 1) * 12 + key % 12
    hi_pitch = lo_pitch + 24
    melody_scale = scale_notes_in_range(key % 12, scale, lo_pitch, hi_pitch)

    melody_notes = _gen_melody(
        rng, total_steps, steps_per_bar, chord_seq, key, scale,
        melody_scale, st['melody_density'], style,
    )

    lead_preset = PRESETS.get(f'lead_{style}', PRESETS['lead_pop'])
    melody_track = Track(
        name='melody', preset=lead_preset, notes=melody_notes,
        pan=rng.uniform(-0.15, 0.15),
        delay_send=0.15 if style in ('ambient', 'electronic') else 0.0,
    )
    tracks.append(melody_track)

    # ----- Bass track -----
    bass_notes = _gen_bass(
        rng, total_steps, steps_per_bar, chord_seq, key, scale,
        st['bass_pattern'], st['bass_oct'],
    )
    bass_preset = PRESETS.get(f'bass_{style}', PRESETS['bass_pop'])
    bass_track = Track(
        name='bass', preset=bass_preset, notes=bass_notes,
        pan=0.0,
    )
    tracks.append(bass_track)

    # ----- Pad track (ambient only) -----
    if style == 'ambient':
        pad_notes = _gen_pad(rng, total_steps, steps_per_bar, chord_seq,
                             key, scale, melody_oct - 1)
        pad_track = Track(
            name='pad', preset=PRESETS['pad'], notes=pad_notes,
            pan=rng.uniform(-0.3, 0.3),
            delay_send=st['delay'],
        )
        tracks.append(pad_track)

    # ----- Drum track -----
    if st['has_drums']:
        drum_notes = _gen_drums(rng, total_steps, steps_per_bar,
                                st['drum_feel'])
        drum_track = Track(
            name='drums', preset={}, notes=drum_notes,
            pan=0.0, is_drum=True,
        )
        tracks.append(drum_track)

    return Sequence(bpm=bpm, steps_per_bar=steps_per_bar, bars=bars, tracks=tracks)


# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------

def _gen_melody(rng, total_steps, spb, chord_seq, root, scale,
                scale_pitches, density, style):
    """Generate a 16th-note melody line."""
    notes = []
    current = rng.choice(scale_pitches) if scale_pitches else 60
    steps_per_chord = spb  # one chord per bar

    step = 0
    while step < total_steps:
        bar = step // spb
        chord_degree, chord_minor = chord_seq[bar % len(chord_seq)]
        chord_pts = chord_pitches(root % 12, scale, chord_degree, chord_minor,
                                  bass_oct=4)

        # Probability of a note at this step
        if rng.random() < density:
            # Choose note: mostly stepwise, sometimes leap, sometimes chord tone
            r = rng.random()
            if r < 0.5:
                # Stepwise motion
                idx = min(range(len(scale_pitches)),
                          key=lambda i: abs(scale_pitches[i] - current))
                direction = 1 if rng.random() < 0.55 else -1
                new_idx = max(0, min(len(scale_pitches) - 1, idx + direction))
                new_note = scale_pitches[new_idx]
            elif r < 0.75:
                # Chord tone
                chord_scale = [nearest_scale_note(p, scale_pitches)
                               for p in chord_pts]
                new_note = rng.choice(chord_scale)
            else:
                # Random scale note nearby
                filtered = [n for n in scale_pitches
                            if abs(n - current) <= 7]
                new_note = rng.choice(filtered) if filtered else current

            vel = rng.randint(65, 105)
            gate_len = rng.choice([1, 1, 1, 2, 2, 3])
            gate_len = min(gate_len, total_steps - step)
            notes.append(NoteEvent(step=step, pitch=new_note, velocity=vel,
                                   gate=float(gate_len)))
            current = new_note
            step += max(1, int(gate_len * rng.uniform(0.7, 1.2)))
        else:
            step += 1

    return notes


def _gen_bass(rng, total_steps, spb, chord_seq, root, scale,
              pattern, bass_oct):
    """Generate the bass line."""
    notes = []
    scale_n = len(scale)

    for bar in range(total_steps // spb):
        degree, is_minor = chord_seq[bar % len(chord_seq)]
        idx = (degree - 1) % scale_n
        root_semi = (root % 12) + scale[idx]
        bass_root = (bass_oct + 1) * 12 + root_semi % 12
        fifth_semi = (root % 12) + scale[(idx + 4) % scale_n]
        bass_fifth = (bass_oct + 1) * 12 + fifth_semi % 12
        if bass_fifth <= bass_root:
            bass_fifth += 12

        bar_start = bar * spb

        if pattern == 'pedal':
            # Long held note per bar
            notes.append(NoteEvent(step=bar_start, pitch=bass_root,
                                   velocity=80, gate=float(spb - 1)))

        elif pattern == 'root':
            # On beats 1 and 3 (every 8 steps in a 16-step bar)
            for beat in [0, 8]:
                notes.append(NoteEvent(step=bar_start + beat, pitch=bass_root,
                                       velocity=90, gate=3.5))

        elif pattern == 'root_fifth':
            # Roots on 1, 3; fifths on 2, 4 (pop bounce)
            pattern_steps = [(0, bass_root, 90), (4, bass_fifth, 75),
                             (8, bass_root, 90), (12, bass_fifth, 75)]
            for offset, pitch, vel in pattern_steps:
                notes.append(NoteEvent(step=bar_start + offset, pitch=pitch,
                                       velocity=vel, gate=3.5))

        elif pattern == 'walking':
            # Walking bass: one note per beat with chromatic approach
            all_scale = scale_notes_in_range(root % 12, scale,
                                             bass_oct * 12, (bass_oct + 2) * 12)
            beat_steps = [0, 4, 8, 12]
            target_idx = (degree - 1) % scale_n
            for bi, bs in enumerate(beat_steps):
                if bi == 0:
                    pitch = bass_root
                else:
                    # Walk to next target
                    next_degree, _ = chord_seq[(bar + (1 if bi == 3 else 0)) % len(chord_seq)]
                    next_idx = (next_degree - 1) % scale_n
                    next_root_semi = (root % 12) + scale[next_idx]
                    next_root = (bass_oct + 1) * 12 + next_root_semi % 12
                    # Approach from scale note below or above
                    candidates = [n for n in all_scale if abs(n - bass_root) <= 7]
                    pitch = rng.choice(candidates) if candidates else bass_root
                notes.append(NoteEvent(step=bar_start + bs, pitch=pitch,
                                       velocity=rng.randint(70, 90), gate=3.5))

    return notes


def _gen_pad(rng, total_steps, spb, chord_seq, root, scale, oct_num):
    """Generate long pad chords (one per bar)."""
    notes = []
    scale_n = len(scale)
    for bar in range(total_steps // spb):
        degree, is_minor = chord_seq[bar % len(chord_seq)]
        chord_pts = chord_pitches(root % 12, scale, degree, is_minor,
                                  bass_oct=oct_num)
        for pitch in chord_pts:
            notes.append(NoteEvent(step=bar * spb, pitch=pitch,
                                   velocity=rng.randint(55, 75),
                                   gate=float(spb - 1)))
    return notes


def _gen_drums(rng, total_steps, spb, feel):
    """Generate a drum pattern."""
    notes = []
    for step in range(total_steps):
        beat_in_bar = step % spb

        if feel == 'four_on_floor':
            # Kick on every beat (0, 4, 8, 12)
            if beat_in_bar % 4 == 0:
                notes.append(NoteEvent(step=step, pitch=0, velocity=100,
                                       gate=1.0, kind='kick'))
            # Snare on 2 and 4
            if beat_in_bar in (4, 12):
                notes.append(NoteEvent(step=step, pitch=0, velocity=90,
                                       gate=1.0, kind='snare'))
            # Hihat on every 16th note
            vel = 70 if beat_in_bar % 2 == 0 else 50
            notes.append(NoteEvent(step=step, pitch=0, velocity=vel,
                                   gate=1.0, kind='hihat'))

        elif feel == 'straight':
            # Kick on 1 and 3, snare on 2 and 4
            if beat_in_bar in (0, 8):
                notes.append(NoteEvent(step=step, pitch=0, velocity=95,
                                       gate=1.0, kind='kick'))
                if beat_in_bar == 0 and rng.random() < 0.3:
                    # Occasional double kick
                    notes.append(NoteEvent(step=step+1, pitch=0, velocity=80,
                                           gate=1.0, kind='kick'))
            if beat_in_bar in (4, 12):
                notes.append(NoteEvent(step=step, pitch=0, velocity=88,
                                       gate=1.0, kind='snare'))
            # Hihat: every 8th note, accented on the beat
            if beat_in_bar % 2 == 0:
                vel = 65 if beat_in_bar % 4 == 0 else 45
                notes.append(NoteEvent(step=step, pitch=0, velocity=vel,
                                       gate=1.0, kind='hihat'))
            # Open hat on the "and" of 4
            if beat_in_bar == 13 and rng.random() < 0.5:
                notes.append(NoteEvent(step=step, pitch=0, velocity=55,
                                       gate=1.0, kind='open_hihat'))

        elif feel == 'swing':
            # Jazz feel: ride cymbal on every 8th, kick sparse, snare on 2+4
            if beat_in_bar in (0, 8):
                if rng.random() < 0.5:
                    notes.append(NoteEvent(step=step, pitch=0, velocity=80,
                                           gate=1.0, kind='kick'))
            if beat_in_bar in (4, 12):
                notes.append(NoteEvent(step=step, pitch=0, velocity=75,
                                       gate=1.0, kind='snare'))
            # Ride on every 8th, swing feel (the "ands" are triplet-swung)
            if beat_in_bar % 2 == 0:
                vel = 60 if beat_in_bar % 4 == 0 else 40
                notes.append(NoteEvent(step=step, pitch=0, velocity=vel,
                                       gate=1.0, kind='hihat'))

    return notes
