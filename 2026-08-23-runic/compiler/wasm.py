"""
Shared WebAssembly binary-format primitives: LEB128 varint codecs, opcode
table, and section/type constants used by both the encoder (compiler ->
bytes) and the decoder side of the interpreter (bytes -> instructions).

Everything here is written directly against the WebAssembly MVP binary
format spec (https://webassembly.github.io/spec/core/binary/) — no
third-party wasm library is used anywhere in this project.
"""

# ---------------------------------------------------------------------------
# LEB128 (Little Endian Base 128) variable-length integer encoding.
# WASM uses unsigned LEB128 ("varuint") for counts/indices/sizes and signed
# LEB128 ("varint") for i32.const immediates.
# ---------------------------------------------------------------------------


def uleb128_encode(value):
    if value < 0:
        raise ValueError(f"uleb128_encode: negative value {value}")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value != 0:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            break
    return bytes(out)


def uleb128_decode(data, pos):
    result = 0
    shift = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
    return result, pos


def sleb128_encode(value):
    out = bytearray()
    more = True
    while more:
        byte = value & 0x7F
        value >>= 7
        # sign bit of byte is set when the 0x40 bit is set
        if (value == 0 and (byte & 0x40) == 0) or (value == -1 and (byte & 0x40) != 0):
            more = False
        else:
            byte |= 0x80
        out.append(byte)
    return bytes(out)


def sleb128_decode(data, pos):
    result = 0
    shift = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if (byte & 0x80) == 0:
            if shift < 32 and (byte & 0x40):
                result |= -(1 << shift)
            break
    # normalize into signed 32-bit range
    result &= 0xFFFFFFFF
    if result >= 0x80000000:
        result -= 0x100000000
    return result, pos


def i32_wrap(x):
    """Wrap a Python int into the signed i32 range, matching WASM overflow."""
    x &= 0xFFFFFFFF
    if x >= 0x80000000:
        x -= 0x100000000
    return x


def vec(items_bytes):
    """Encode a WASM 'vec': uleb128 count followed by concatenated items."""
    body = b"".join(items_bytes)
    return uleb128_encode(len(items_bytes)) + body


def name_bytes(s):
    b = s.encode("utf-8")
    return uleb128_encode(len(b)) + b


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAGIC = b"\x00asm"
VERSION = b"\x01\x00\x00\x00"

SEC_TYPE = 1
SEC_IMPORT = 2
SEC_FUNCTION = 3
SEC_TABLE = 4
SEC_MEMORY = 5
SEC_GLOBAL = 6
SEC_EXPORT = 7
SEC_START = 8
SEC_ELEMENT = 9
SEC_CODE = 10
SEC_DATA = 11

VALTYPE_I32 = 0x7F
FUNCTYPE_TAG = 0x60
BLOCKTYPE_VOID = 0x40

EXPORT_KIND_FUNC = 0x00
EXPORT_KIND_MEM = 0x02

# opcode name -> (byte, immediate kind)
# immediate kinds: None, 'blocktype', 'labelidx', 'funcidx', 'localidx',
# 'i32const' (sleb128), 'memarg' (align:uleb128, offset:uleb128)
OPCODES = {
    "unreachable": (0x00, None),
    "nop": (0x01, None),
    "block": (0x02, "blocktype"),
    "loop": (0x03, "blocktype"),
    "if": (0x04, "blocktype"),
    "else": (0x05, None),
    "end": (0x0B, None),
    "br": (0x0C, "labelidx"),
    "br_if": (0x0D, "labelidx"),
    "return": (0x0F, None),
    "call": (0x10, "funcidx"),
    "drop": (0x1A, None),
    "local.get": (0x20, "localidx"),
    "local.set": (0x21, "localidx"),
    "local.tee": (0x22, "localidx"),
    "i32.load": (0x28, "memarg"),
    "i32.store": (0x36, "memarg"),
    "i32.const": (0x41, "i32const"),
    "i32.eqz": (0x45, None),
    "i32.eq": (0x46, None),
    "i32.ne": (0x47, None),
    "i32.lt_s": (0x48, None),
    "i32.gt_s": (0x4A, None),
    "i32.le_s": (0x4C, None),
    "i32.ge_s": (0x4E, None),
    "i32.add": (0x6A, None),
    "i32.sub": (0x6B, None),
    "i32.mul": (0x6C, None),
    "i32.div_s": (0x6D, None),
    "i32.rem_s": (0x6F, None),
    "i32.and": (0x71, None),
    "i32.or": (0x72, None),
    "i32.xor": (0x73, None),
}

OPCODE_BY_BYTE = {v[0]: (name, v[1]) for name, v in OPCODES.items()}

WASM_PAGE_SIZE = 65536
