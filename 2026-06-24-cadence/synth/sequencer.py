"""Step sequencer and offline multi-track renderer.

A Sequence holds tracks; each track has a preset, a list of NoteEvent objects
(absolute step index, pitch, velocity, gate length in steps), and a stereo pan.
The render() function mixes all tracks into a stereo float buffer.
"""

import math
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from .core import SAMPLE_RATE
from .voice import render_note, render_drum
from .effects import Delay, soft_limit

_SR = SAMPLE_RATE


@dataclass
class NoteEvent:
    step: int           # 0-based step index
    pitch: int          # MIDI note number (ignored for drum tracks)
    velocity: int       # 0-127
    gate: float         # gate length in steps (1.0 = one step)
    kind: str = ''      # for drum tracks: 'kick', 'snare', 'hihat', etc.


@dataclass
class Track:
    name: str
    preset: Dict[str, Any]
    notes: List[NoteEvent] = field(default_factory=list)
    pan: float = 0.0        # -1.0 (full left) to +1.0 (full right)
    is_drum: bool = False
    delay_send: float = 0.0  # 0..1, amount routed to delay effect


@dataclass
class Sequence:
    bpm: float = 120.0
    steps_per_bar: int = 16    # 16th-note grid by default
    bars: int = 8
    tracks: List[Track] = field(default_factory=list)

    @property
    def total_steps(self) -> int:
        return self.steps_per_bar * self.bars

    @property
    def step_samples(self) -> int:
        """Number of samples per step."""
        steps_per_beat = self.steps_per_bar / 4  # 4 beats per bar
        beat_samples = 60.0 / self.bpm * _SR
        return max(1, int(beat_samples / steps_per_beat))

    @property
    def total_samples(self) -> int:
        return self.total_steps * self.step_samples


def _add_into(buf: list, samples: list, offset: int) -> None:
    """Add samples into buf starting at offset, extending if necessary."""
    end = offset + len(samples)
    if end > len(buf):
        buf.extend([0.0] * (end - len(buf)))
    for i, s in enumerate(samples):
        buf[offset + i] += s


def render(seq: Sequence, rng=None) -> tuple:
    """Render a Sequence to (left, right) stereo float lists.

    Returns lists of length >= seq.total_samples (may be slightly longer
    due to release tails extending past the end).
    """
    import random as _random
    if rng is None:
        rng = _random

    step_n = seq.step_samples
    total_n = seq.total_samples
    # Add a generous tail for releases
    tail_n = int(2.0 * _SR)
    buf_len = total_n + tail_n

    # Stereo bus: left, right
    left_bus = [0.0] * buf_len
    right_bus = [0.0] * buf_len

    # Optional global delay bus
    delay_bus = [0.0] * buf_len

    for track in seq.tracks:
        for evt in track.notes:
            start_s = evt.step * step_n
            if start_s >= buf_len:
                continue
            gate_s = max(1, int(evt.gate * step_n))

            if track.is_drum:
                samples = render_drum(evt.kind, evt.velocity, _SR, rng)
            else:
                samples = render_note(track.preset, evt.pitch, evt.velocity,
                                      gate_s, rng)

            if not samples:
                continue

            # Pan: equal-power panning
            pan_rad = (track.pan + 1.0) * 0.5 * math.pi / 2.0
            pan_l = math.cos(pan_rad)
            pan_r = math.sin(pan_rad)

            _add_into(left_bus, [s * pan_l for s in samples], start_s)
            _add_into(right_bus, [s * pan_r for s in samples], start_s)

            if track.delay_send > 0.0:
                _add_into(delay_bus, [s * track.delay_send for s in samples], start_s)

    # Trim to buf_len (some _add_into calls might have extended)
    left_bus = left_bus[:buf_len]
    right_bus = right_bus[:buf_len]

    # Apply delay to delay bus and mix in
    if any(t.delay_send > 0 for t in seq.tracks):
        delay = Delay(delay_s=60.0 / seq.bpm * 0.75, feedback=0.4, damping=0.4)
        delay_bus = delay_bus[:buf_len]
        delay_out = delay.process(delay_bus, wet=1.0)
        delay_mix = 0.35
        for i in range(min(len(delay_out), buf_len)):
            left_bus[i]  += delay_out[i] * delay_mix
            right_bus[i] += delay_out[i] * delay_mix

    # Soft limit
    left_bus = soft_limit(left_bus)
    right_bus = soft_limit(right_bus)

    return left_bus, right_bus
