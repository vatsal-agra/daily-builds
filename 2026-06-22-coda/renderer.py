"""MIDI-to-audio renderer: builds a tempo map, routes channels to instruments,
and synthesizes the full mix to an AudioBuffer."""

from midi import (
    MidiFile, MidiEvent, NoteOn, NoteOff, ProgramChange,
    ControlChange, TempoChange, PitchBend, EndOfTrack,
)
from wav import AudioBuffer, SAMPLE_RATE
from synth import PolySynth, VoiceParams, ADSR, render_voice
from instruments import gm_program_to_voice, DRUM_MAP, DrumVoice
from synth import noise_burst

import math


DEFAULT_US_PER_BEAT = 500_000  # 120 BPM

DRUM_CHANNEL = 9  # 0-indexed


# ---------------------------------------------------------------------------
# Tempo map: convert ticks → seconds
# ---------------------------------------------------------------------------

class TempoMap:
    """Piecewise-linear map from ticks to seconds, supporting multiple
    Tempo Change events."""

    def __init__(self, ticks_per_beat: int):
        self.ticks_per_beat = ticks_per_beat
        # List of (abs_tick, us_per_beat) breakpoints, sorted by tick
        self.breakpoints: list[tuple[int, int]] = [(0, DEFAULT_US_PER_BEAT)]

    def add_tempo(self, tick: int, us_per_beat: int):
        # Remove any breakpoint at the same tick (last one wins)
        self.breakpoints = [(t, u) for t, u in self.breakpoints if t != tick]
        self.breakpoints.append((tick, us_per_beat))
        self.breakpoints.sort()

    def tick_to_seconds(self, tick: int) -> float:
        """Convert an absolute tick position to seconds."""
        seconds = 0.0
        prev_tick = 0
        prev_us = DEFAULT_US_PER_BEAT
        for bp_tick, bp_us in self.breakpoints:
            if tick <= bp_tick:
                break
            # Add time from prev_tick to min(tick, bp_tick)
            segment_ticks = bp_tick - prev_tick
            seconds += segment_ticks * prev_us / (self.ticks_per_beat * 1_000_000)
            prev_tick = bp_tick
            prev_us = bp_us
        # Remaining ticks after last breakpoint
        remaining = tick - prev_tick
        seconds += remaining * prev_us / (self.ticks_per_beat * 1_000_000)
        return seconds


def build_tempo_map(midi: MidiFile) -> TempoMap:
    """Scan all tracks for TempoChange events and build a TempoMap."""
    tm = TempoMap(midi.ticks_per_beat)
    for track in midi.tracks:
        for ev in track.events:
            if isinstance(ev.event, TempoChange):
                tm.add_tempo(ev.tick, ev.event.us_per_beat)
    return tm


# ---------------------------------------------------------------------------
# Drum rendering
# ---------------------------------------------------------------------------

def render_drum_hit(note: int, velocity: int, duration_s: float) -> AudioBuffer:
    """Render a percussion hit using the DRUM_MAP (or noise fallback)."""
    voice = DRUM_MAP.get(note)
    if voice is None:
        # Generic noise hit
        voice = DrumVoice("noise", 0, ADSR(0.001, 0.06, 0.0, 0.03))

    vel_gain = (velocity / 127) ** 0.7
    hit_dur = min(duration_s, voice.adsr.attack + voice.adsr.decay + 0.01)
    release_samps = int(voice.adsr.release * SAMPLE_RATE)
    hold_samps = max(1, int(hit_dur * SAMPLE_RATE))
    total = hold_samps + release_samps

    if voice.waveform == "noise":
        raw = noise_burst(total, seed=note + (velocity * 128))
    else:
        # Pitched drum (toms)
        freq = voice.freq if voice.freq > 0 else 100.0
        TAU = 2.0 * math.pi
        step = TAU * freq / SAMPLE_RATE
        raw = [math.sin(i * step) for i in range(total)]

    env = voice.adsr.envelope(hit_dur)
    if len(env) < total:
        env = env + [0.0] * (total - len(env))
    raw = [raw[i] * env[i] * vel_gain for i in range(total)]

    buf = AudioBuffer(total)
    buf.left = raw[:]
    buf.right = raw[:]
    return buf


# ---------------------------------------------------------------------------
# Main renderer
# ---------------------------------------------------------------------------

def render_midi(midi: MidiFile, gain: float = 0.6) -> AudioBuffer:
    """Render a MidiFile to an AudioBuffer."""
    tempo_map = build_tempo_map(midi)

    # Find the total duration
    max_tick = 0
    for track in midi.tracks:
        for ev in track.events:
            max_tick = max(max_tick, ev.tick)
    total_seconds = tempo_map.tick_to_seconds(max_tick) + 2.0  # 2s tail
    total_samples = int(total_seconds * SAMPLE_RATE) + SAMPLE_RATE

    mix = AudioBuffer(total_samples)

    # Render each track
    for track in midi.tracks:
        # Per-channel program and active notes state
        programs: dict[int, int] = {}  # channel → GM program (0-based)
        active: dict[tuple[int, int], tuple[int, float]] = {}  # (ch, note) → (velocity, note_on_seconds)

        events_sorted = sorted(track.events, key=lambda e: e.tick)

        for ev in events_sorted:
            t = tempo_map.tick_to_seconds(ev.tick)
            start_sample = int(t * SAMPLE_RATE)
            if start_sample >= total_samples:
                continue

            if isinstance(ev.event, ProgramChange):
                programs[ev.event.channel] = ev.event.program

            elif isinstance(ev.event, NoteOn):
                ch = ev.event.channel
                note = ev.event.note
                vel = ev.event.velocity
                # Record note-on time
                active[(ch, note)] = (vel, t)

            elif isinstance(ev.event, NoteOff):
                ch = ev.event.channel
                note = ev.event.note
                key = (ch, note)
                if key not in active:
                    continue
                vel, note_on_t = active.pop(key)
                duration_s = t - note_on_t
                if duration_s <= 0:
                    duration_s = 0.05
                note_start_sample = int(note_on_t * SAMPLE_RATE)
                if note_start_sample >= total_samples:
                    continue

                if ch == DRUM_CHANNEL:
                    buf = render_drum_hit(note, vel, duration_s)
                else:
                    prog = programs.get(ch, 0)
                    params = gm_program_to_voice(prog)
                    buf = render_voice(note, vel, duration_s, 0.0, params)

                mix.mix_into(buf, offset=note_start_sample, gain=gain / 16)

        # Flush any notes that never received NoteOff (held until end)
        for (ch, note), (vel, note_on_t) in active.items():
            duration_s = max(0.1, total_seconds - note_on_t)
            note_start_sample = int(note_on_t * SAMPLE_RATE)
            if note_start_sample >= total_samples:
                continue
            if ch == DRUM_CHANNEL:
                buf = render_drum_hit(note, vel, duration_s)
            else:
                prog = programs.get(ch, 0)
                params = gm_program_to_voice(prog)
                buf = render_voice(note, vel, duration_s, 0.0, params)
            mix.mix_into(buf, offset=note_start_sample, gain=gain / 16)

    mix.normalize()
    return mix


def render_midi_file(midi_path: str, wav_path: str):
    """Convenience: render a MIDI file to a WAV file."""
    from midi import parse_midi_file
    midi = parse_midi_file(midi_path)
    buf = render_midi(midi)
    buf.write_wav(wav_path)
    return buf
