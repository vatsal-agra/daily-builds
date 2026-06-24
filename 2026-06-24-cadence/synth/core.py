"""Core constants, MIDI/frequency utilities, and note parsing."""

import math

SAMPLE_RATE = 44100
TWO_PI = 2.0 * math.pi

# MIDI note name lookup
_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
_FLAT_MAP = {'DB': 'C#', 'EB': 'D#', 'GB': 'F#', 'AB': 'G#', 'BB': 'A#',
             'CB': 'B',  'FB': 'E'}


def note_to_freq(midi: int) -> float:
    """MIDI note number → frequency in Hz (A4=69=440 Hz)."""
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def parse_note(name: str) -> int:
    """Parse a note name like 'A4', 'C#3', 'Bb2' into a MIDI number."""
    name = name.strip()
    if name[-1].isdigit() or (len(name) > 1 and name[-1] == '-' and name[-2].isdigit()):
        octave_str = ''
        i = len(name) - 1
        while i >= 0 and (name[i].isdigit() or name[i] == '-'):
            octave_str = name[i] + octave_str
            i -= 1
        note_str = name[:i + 1].upper()
        octave = int(octave_str)
    else:
        raise ValueError(f"Cannot parse note: {name!r}")

    note_str = _FLAT_MAP.get(note_str, note_str)
    if note_str not in _NAMES:
        raise ValueError(f"Unknown note name: {note_str!r} in {name!r}")
    semitone = _NAMES.index(note_str)
    return (octave + 1) * 12 + semitone


def midi_to_name(midi: int) -> str:
    octave = (midi // 12) - 1
    return _NAMES[midi % 12] + str(octave)


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t
