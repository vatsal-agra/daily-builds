"""Binary MIDI file parser — Type 0/1/2, all channel events and meta events."""

import struct
import io
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

@dataclass
class NoteOn:
    channel: int
    note: int
    velocity: int

@dataclass
class NoteOff:
    channel: int
    note: int
    velocity: int

@dataclass
class AfterTouch:
    channel: int
    note: int
    pressure: int

@dataclass
class ControlChange:
    channel: int
    control: int
    value: int

@dataclass
class ProgramChange:
    channel: int
    program: int

@dataclass
class ChannelPressure:
    channel: int
    pressure: int

@dataclass
class PitchBend:
    channel: int
    value: int  # -8192 to +8191

@dataclass
class TempoChange:
    us_per_beat: int  # microseconds per quarter note

@dataclass
class TimeSignature:
    numerator: int
    denominator: int  # already decoded (e.g. 4 not 2)
    clocks_per_click: int
    notated_32nds: int

@dataclass
class KeySignature:
    sharps: int   # negative = flats
    is_minor: bool

@dataclass
class TrackName:
    name: str

@dataclass
class Lyrics:
    text: str

@dataclass
class EndOfTrack:
    pass

@dataclass
class SysEx:
    data: bytes

@dataclass
class UnknownMeta:
    type_byte: int
    data: bytes

@dataclass
class UnknownEvent:
    status: int
    data: bytes


@dataclass
class MidiEvent:
    """An event with an absolute tick position."""
    tick: int
    event: Any


@dataclass
class MidiTrack:
    events: list[MidiEvent] = field(default_factory=list)


@dataclass
class MidiFile:
    format: int          # 0, 1, or 2
    ticks_per_beat: int  # PPQN (pulses per quarter note)
    tracks: list[MidiTrack] = field(default_factory=list)


# ---------------------------------------------------------------------------
# VLQ decoder
# ---------------------------------------------------------------------------

def read_vlq(stream: io.BytesIO) -> int:
    """Read a variable-length quantity from the stream."""
    value = 0
    for _ in range(4):
        byte = stream.read(1)
        if not byte:
            raise ValueError("Unexpected end of stream reading VLQ")
        b = byte[0]
        value = (value << 7) | (b & 0x7F)
        if not (b & 0x80):
            return value
    raise ValueError("VLQ exceeds 4 bytes")


def write_vlq(value: int) -> bytes:
    """Encode an integer as a variable-length quantity."""
    if value < 0:
        raise ValueError("VLQ must be non-negative")
    result = bytearray()
    result.append(value & 0x7F)
    value >>= 7
    while value:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.reverse()
    return bytes(result)


# ---------------------------------------------------------------------------
# Track chunk parser
# ---------------------------------------------------------------------------

def parse_track(data: bytes) -> MidiTrack:
    """Parse a raw track chunk (no header, just event data)."""
    stream = io.BytesIO(data)
    track = MidiTrack()
    abs_tick = 0
    running_status = 0

    while stream.tell() < len(data):
        # Delta time
        delta = read_vlq(stream)
        abs_tick += delta

        # Peek at next byte
        peek = stream.read(1)
        if not peek:
            break
        byte = peek[0]

        if byte == 0xFF:
            # Meta event
            meta_type = stream.read(1)[0]
            length = read_vlq(stream)
            meta_data = stream.read(length)
            event = _parse_meta(meta_type, meta_data)
            track.events.append(MidiEvent(abs_tick, event))
            if isinstance(event, EndOfTrack):
                break
            running_status = 0  # meta resets running status

        elif byte in (0xF0, 0xF7):
            # SysEx
            length = read_vlq(stream)
            sysex_data = stream.read(length)
            track.events.append(MidiEvent(abs_tick, SysEx(bytes([byte]) + sysex_data)))
            running_status = 0

        elif byte & 0x80:
            # New status byte
            running_status = byte
            status = byte
            channel = status & 0x0F
            event_type = (status >> 4) & 0x0F
            ev = _parse_channel_event(event_type, channel, stream)
            if ev is not None:
                track.events.append(MidiEvent(abs_tick, ev))
        else:
            # Running status: use previous status, byte is first data byte
            if running_status == 0:
                # Skip unrecognized data
                continue
            status = running_status
            channel = status & 0x0F
            event_type = (status >> 4) & 0x0F
            first_data = byte

            if event_type in (0x8, 0x9, 0xA, 0xB, 0xE):
                # 2-data-byte events
                second = stream.read(1)[0]
                ev = _build_two_byte_event(event_type, channel, first_data, second)
            elif event_type in (0xC, 0xD):
                # 1-data-byte events
                ev = _build_one_byte_event(event_type, channel, first_data)
            else:
                ev = None

            if ev is not None:
                track.events.append(MidiEvent(abs_tick, ev))

    return track


def _parse_channel_event(event_type: int, channel: int, stream: io.BytesIO):
    """Read data bytes and return a channel event, or None for unrecognized."""
    if event_type in (0x8, 0x9, 0xA, 0xB, 0xE):
        d1 = stream.read(1)[0]
        d2 = stream.read(1)[0]
        return _build_two_byte_event(event_type, channel, d1, d2)
    elif event_type in (0xC, 0xD):
        d1 = stream.read(1)[0]
        return _build_one_byte_event(event_type, channel, d1)
    else:
        return None


def _build_two_byte_event(event_type: int, channel: int, d1: int, d2: int):
    if event_type == 0x8:
        return NoteOff(channel, d1, d2)
    elif event_type == 0x9:
        # velocity=0 is treated as NoteOff per spec
        if d2 == 0:
            return NoteOff(channel, d1, 0)
        return NoteOn(channel, d1, d2)
    elif event_type == 0xA:
        return AfterTouch(channel, d1, d2)
    elif event_type == 0xB:
        return ControlChange(channel, d1, d2)
    elif event_type == 0xE:
        value = (d2 << 7) | d1  # 14-bit, center = 0x2000
        return PitchBend(channel, value - 0x2000)
    return None


def _build_one_byte_event(event_type: int, channel: int, d1: int):
    if event_type == 0xC:
        return ProgramChange(channel, d1)
    elif event_type == 0xD:
        return ChannelPressure(channel, d1)
    return None


def _parse_meta(meta_type: int, data: bytes):
    if meta_type == 0x51:  # Tempo
        us = (data[0] << 16) | (data[1] << 8) | data[2]
        return TempoChange(us)
    elif meta_type == 0x58:  # Time Signature
        num = data[0]
        den = 2 ** data[1]
        return TimeSignature(num, den, data[2], data[3])
    elif meta_type == 0x59:  # Key Signature
        sharps = struct.unpack("b", bytes([data[0]]))[0]  # signed
        is_minor = data[1] == 1
        return KeySignature(sharps, is_minor)
    elif meta_type == 0x03:  # Track Name
        return TrackName(data.decode("latin-1", errors="replace"))
    elif meta_type == 0x05:  # Lyrics
        return Lyrics(data.decode("latin-1", errors="replace"))
    elif meta_type == 0x2F:  # End of Track
        return EndOfTrack()
    else:
        return UnknownMeta(meta_type, data)


# ---------------------------------------------------------------------------
# Top-level file parser
# ---------------------------------------------------------------------------

def parse_midi(data: bytes) -> MidiFile:
    """Parse raw MIDI file bytes into a MidiFile object."""
    stream = io.BytesIO(data)

    # MThd header
    magic = stream.read(4)
    if magic != b"MThd":
        raise ValueError(f"Not a MIDI file (got {magic!r})")
    header_len = struct.unpack(">I", stream.read(4))[0]
    if header_len < 6:
        raise ValueError(f"MIDI header too short: {header_len}")
    header_data = stream.read(header_len)
    fmt = struct.unpack(">H", header_data[0:2])[0]
    num_tracks = struct.unpack(">H", header_data[2:4])[0]
    division = struct.unpack(">H", header_data[4:6])[0]

    if division & 0x8000:
        raise ValueError("SMPTE timecode MIDI not supported")
    ticks_per_beat = division

    midi = MidiFile(format=fmt, ticks_per_beat=ticks_per_beat)

    for i in range(num_tracks):
        chunk_id = stream.read(4)
        if len(chunk_id) < 4:
            break  # truncated
        chunk_len = struct.unpack(">I", stream.read(4))[0]
        chunk_data = stream.read(chunk_len)
        if chunk_id == b"MTrk":
            midi.tracks.append(parse_track(chunk_data))
        # skip unknown chunks silently

    return midi


def parse_midi_file(path: str) -> MidiFile:
    with open(path, "rb") as f:
        return parse_midi(f.read())


# ---------------------------------------------------------------------------
# MIDI writer
# ---------------------------------------------------------------------------

def encode_track(events: list[MidiEvent]) -> bytes:
    """Encode a list of MidiEvents into track chunk bytes (no header)."""
    out = bytearray()
    prev_tick = 0
    for ev in sorted(events, key=lambda e: e.tick):
        delta = ev.tick - prev_tick
        prev_tick = ev.tick
        out += write_vlq(delta)
        out += encode_event(ev.event)
    # End of Track meta
    out += write_vlq(0)
    out += bytes([0xFF, 0x2F, 0x00])
    return bytes(out)


def encode_event(event) -> bytes:
    if isinstance(event, NoteOn):
        return bytes([0x90 | event.channel, event.note, event.velocity])
    elif isinstance(event, NoteOff):
        return bytes([0x80 | event.channel, event.note, event.velocity])
    elif isinstance(event, ProgramChange):
        return bytes([0xC0 | event.channel, event.program])
    elif isinstance(event, ControlChange):
        return bytes([0xB0 | event.channel, event.control, event.value])
    elif isinstance(event, PitchBend):
        val = event.value + 0x2000
        lsb = val & 0x7F
        msb = (val >> 7) & 0x7F
        return bytes([0xE0 | event.channel, lsb, msb])
    elif isinstance(event, TempoChange):
        us = event.us_per_beat
        data = bytes([(us >> 16) & 0xFF, (us >> 8) & 0xFF, us & 0xFF])
        return bytes([0xFF, 0x51, 0x03]) + data
    elif isinstance(event, TimeSignature):
        den_pow = 0
        d = event.denominator
        while d > 1:
            d >>= 1
            den_pow += 1
        return bytes([0xFF, 0x58, 0x04, event.numerator, den_pow,
                       event.clocks_per_click, event.notated_32nds])
    elif isinstance(event, TrackName):
        encoded = event.name.encode("latin-1", errors="replace")
        return bytes([0xFF, 0x03]) + write_vlq(len(encoded)) + encoded
    elif isinstance(event, EndOfTrack):
        return bytes([0xFF, 0x2F, 0x00])
    else:
        return b""


def write_midi(midi: MidiFile) -> bytes:
    """Encode a MidiFile to raw bytes."""
    out = bytearray()
    # MThd
    out += b"MThd"
    out += struct.pack(">I", 6)
    out += struct.pack(">H", midi.format)
    out += struct.pack(">H", len(midi.tracks))
    out += struct.pack(">H", midi.ticks_per_beat)
    # MTrk chunks
    for track in midi.tracks:
        track_data = encode_track(track.events)
        out += b"MTrk"
        out += struct.pack(">I", len(track_data))
        out += track_data
    return bytes(out)


def write_midi_file(midi: MidiFile, path: str):
    with open(path, "wb") as f:
        f.write(write_midi(midi))
