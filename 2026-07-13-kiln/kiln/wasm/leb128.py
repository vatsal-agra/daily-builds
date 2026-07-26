"""LEB128 variable-length integer encoding, as used throughout the WASM
binary format (section sizes, indices, immediates, i32/i64 constants)."""


def encode_u32(value):
    return encode_uleb(value)


def encode_uleb(value):
    if value < 0:
        raise ValueError("encode_uleb requires a non-negative value")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def encode_sleb(value):
    out = bytearray()
    more = True
    while more:
        byte = value & 0x7F
        value >>= 7
        sign_bit_set = bool(byte & 0x40)
        if (value == 0 and not sign_bit_set) or (value == -1 and sign_bit_set):
            more = False
        else:
            byte |= 0x80
        out.append(byte)
    return bytes(out)


class ByteReader:
    """Cursor over a bytes buffer used by both the module decoder and the
    interpreter's instruction stream."""

    __slots__ = ("data", "pos")

    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos

    def eof(self):
        return self.pos >= len(self.data)

    def remaining(self):
        return len(self.data) - self.pos

    def read_byte(self):
        if self.pos >= len(self.data):
            raise EOFError("unexpected end of module")
        b = self.data[self.pos]
        self.pos += 1
        return b

    def read_bytes(self, n):
        if self.pos + n > len(self.data):
            raise EOFError("unexpected end of module")
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def read_uleb(self, max_bits=64):
        result = 0
        shift = 0
        while True:
            byte = self.read_byte()
            result |= (byte & 0x7F) << shift
            shift += 7
            if not (byte & 0x80):
                break
            if shift >= max_bits + 7:
                raise ValueError("LEB128 unsigned value too long")
        return result

    def read_sleb(self, max_bits=64):
        result = 0
        shift = 0
        byte = 0
        while True:
            byte = self.read_byte()
            result |= (byte & 0x7F) << shift
            shift += 7
            if not (byte & 0x80):
                break
            if shift >= max_bits + 7:
                raise ValueError("LEB128 signed value too long")
        if shift < max_bits and (byte & 0x40):
            result |= -(1 << shift)
        return result

    def read_name(self):
        n = self.read_uleb(32)
        return self.read_bytes(n).decode("utf-8")

    def read_f32(self):
        import struct
        return struct.unpack("<f", self.read_bytes(4))[0]

    def read_f64(self):
        import struct
        return struct.unpack("<d", self.read_bytes(8))[0]
