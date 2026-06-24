"""Instrument presets: ADSR + harmonic content for each timbre."""

from synth import ADSR, VoiceParams

# ---------------------------------------------------------------------------
# Instrument catalogue keyed by General MIDI program number (1-indexed, 0-based)
# ---------------------------------------------------------------------------

def piano() -> VoiceParams:
    """Bright acoustic piano — exponentially decaying harmonics."""
    return VoiceParams(
        waveform="sine",
        adsr=ADSR(attack=0.005, decay=0.4, sustain=0.3, release=0.3),
        harmonics=[
            (2.0, 0.6),
            (3.0, 0.25),
            (4.0, 0.15),
            (5.0, 0.08),
            (6.0, 0.04),
            (7.0, 0.02),
        ],
    )


def electric_piano() -> VoiceParams:
    """Rhodes-style electric piano — FM synthesis character."""
    return VoiceParams(
        waveform="sine",
        adsr=ADSR(attack=0.003, decay=0.6, sustain=0.2, release=0.25),
        fm_ratio=2.0,
        fm_depth=0.8,
        harmonics=[(2.0, 0.3), (3.0, 0.1)],
    )


def organ() -> VoiceParams:
    """Hammond organ — sustained drawbar harmonics."""
    return VoiceParams(
        waveform="sine",
        adsr=ADSR(attack=0.01, decay=0.01, sustain=1.0, release=0.05),
        harmonics=[
            (2.0, 0.8),
            (3.0, 0.6),
            (4.0, 0.4),
            (5.0, 0.2),
            (6.0, 0.1),
            (8.0, 0.3),
        ],
    )


def strings() -> VoiceParams:
    """Slow-attack string ensemble."""
    return VoiceParams(
        waveform="sawtooth",
        adsr=ADSR(attack=0.2, decay=0.1, sustain=0.9, release=0.4),
        detune_cents=3.0,
        harmonics=[(2.0, 0.4), (3.0, 0.2), (4.0, 0.1)],
    )


def choir() -> VoiceParams:
    """Soft choir/pad."""
    return VoiceParams(
        waveform="sine",
        adsr=ADSR(attack=0.3, decay=0.2, sustain=0.8, release=0.5),
        fm_ratio=3.0,
        fm_depth=0.15,
        harmonics=[(2.0, 0.5), (3.0, 0.3)],
    )


def guitar() -> VoiceParams:
    """Nylon guitar — plucked character via fast decay."""
    return VoiceParams(
        waveform="triangle",
        adsr=ADSR(attack=0.005, decay=0.3, sustain=0.1, release=0.2),
        harmonics=[(2.0, 0.5), (3.0, 0.2), (4.0, 0.1)],
    )


def bass() -> VoiceParams:
    """Acoustic/fingered bass — low harmonics, medium decay."""
    return VoiceParams(
        waveform="sine",
        adsr=ADSR(attack=0.01, decay=0.3, sustain=0.5, release=0.1),
        harmonics=[(2.0, 0.7), (3.0, 0.3), (4.0, 0.1)],
    )


def brass() -> VoiceParams:
    """Brass section — medium attack, rich odd harmonics."""
    return VoiceParams(
        waveform="square",
        adsr=ADSR(attack=0.05, decay=0.1, sustain=0.8, release=0.1),
        harmonics=[(3.0, 0.3), (5.0, 0.15), (7.0, 0.08)],
    )


def flute() -> VoiceParams:
    """Flute — nearly pure sine with slight FM breathiness."""
    return VoiceParams(
        waveform="sine",
        adsr=ADSR(attack=0.08, decay=0.05, sustain=0.9, release=0.1),
        fm_ratio=1.0,
        fm_depth=0.05,
        harmonics=[(2.0, 0.1)],
    )


def marimba() -> VoiceParams:
    """Marimba — fast attack, inharmonic decay."""
    return VoiceParams(
        waveform="sine",
        adsr=ADSR(attack=0.002, decay=0.5, sustain=0.0, release=0.1),
        harmonics=[(4.0, 0.3), (9.73, 0.15)],  # marimba's inharmonic overtone
    )


def default_instrument() -> VoiceParams:
    """Fallback instrument (soft sine pad)."""
    return VoiceParams(
        waveform="sine",
        adsr=ADSR(attack=0.02, decay=0.1, sustain=0.7, release=0.15),
    )


# ---------------------------------------------------------------------------
# Percussion voices (channel 10 / GM drumkit)
# ---------------------------------------------------------------------------

class DrumVoice:
    """A percussion hit is noise (or sine burst) shaped by a tight ADSR."""

    def __init__(self, waveform: str = "noise", freq: float = 0,
                 adsr: ADSR | None = None, harmonics=None):
        self.waveform = waveform
        self.freq = freq  # 0 = noise only
        self.adsr = adsr or ADSR(attack=0.002, decay=0.05, sustain=0.0, release=0.02)
        self.harmonics = harmonics or []


DRUM_MAP: dict[int, DrumVoice] = {
    # MIDI note → drum voice
    35: DrumVoice("noise", 0, ADSR(0.002, 0.10, 0.0, 0.05)),   # Acoustic Bass Drum
    36: DrumVoice("noise", 0, ADSR(0.002, 0.12, 0.0, 0.06)),   # Bass Drum 1
    38: DrumVoice("noise", 0, ADSR(0.002, 0.08, 0.0, 0.04)),   # Acoustic Snare
    40: DrumVoice("noise", 0, ADSR(0.002, 0.07, 0.0, 0.04)),   # Electric Snare
    42: DrumVoice("noise", 0, ADSR(0.001, 0.02, 0.0, 0.01)),   # Closed Hi-Hat
    44: DrumVoice("noise", 0, ADSR(0.001, 0.03, 0.0, 0.01)),   # Pedal Hi-Hat
    46: DrumVoice("noise", 0, ADSR(0.001, 0.08, 0.0, 0.04)),   # Open Hi-Hat
    49: DrumVoice("noise", 0, ADSR(0.002, 0.15, 0.0, 0.10)),   # Crash Cymbal 1
    51: DrumVoice("noise", 0, ADSR(0.002, 0.20, 0.0, 0.15)),   # Ride Cymbal 1
    45: DrumVoice("sine",  82, ADSR(0.002, 0.10, 0.0, 0.05)),  # Low Tom
    47: DrumVoice("sine",  98, ADSR(0.002, 0.10, 0.0, 0.05)),  # Low-Mid Tom
    48: DrumVoice("sine", 110, ADSR(0.002, 0.08, 0.0, 0.04)),  # Hi-Mid Tom
    50: DrumVoice("sine", 130, ADSR(0.002, 0.07, 0.0, 0.04)),  # High Tom
}


def gm_program_to_voice(program: int) -> VoiceParams:
    """Map a General MIDI program number (0-127) to a VoiceParams preset."""
    # GM program ranges:
    # 0-7:   Piano family
    # 8-15:  Chromatic Percussion
    # 16-23: Organ
    # 24-31: Guitar
    # 32-39: Bass
    # 40-47: Strings
    # 48-55: Ensemble
    # 56-63: Brass
    # 64-71: Reed
    # 72-79: Pipe
    # 80-87: Synth Lead
    # 88-95: Synth Pad
    # 96-103: Synth Effects
    # 104-111: Ethnic
    # 112-119: Percussive
    # 120-127: Sound Effects

    if program <= 5:
        return piano()
    elif program <= 7:
        return electric_piano()
    elif program <= 13:
        return marimba()
    elif program <= 15:
        return marimba()
    elif program <= 23:
        return organ()
    elif program <= 31:
        return guitar()
    elif program <= 39:
        return bass()
    elif program <= 47:
        return strings()
    elif program <= 55:
        return choir()
    elif program <= 63:
        return brass()
    elif program <= 79:
        return flute()
    elif program <= 95:
        return choir()
    else:
        return default_instrument()
