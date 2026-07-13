import unittest

from .helpers import assemble_bytes
from kiln.wasm.decoder import decode_module
from kiln.wasm.encoder import encode_module

KWAT_KITCHEN_SINK = """
(module
  (memory $mem 1 4)
  (global $g (mut i32) (i32.const 7))
  (table 2 funcref)
  (func $helper (param i32) (result i32)
    local.get 0
    i32.const 1
    i32.add)
  (func $main (param i32 i32) (result i32)
    (local i32)
    local.get 0
    local.get 1
    i32.add
    call $helper
    local.set 2
    local.get 2
    global.get $g
    i32.add)
  (elem (i32.const 0) $helper $main)
  (data (i32.const 0) "hi")
  (export "main" (func $main))
  (export "mem" (memory $mem))
  (export "g" (global $g))
  (start $helper)
)
"""


class TestDecoderEncoderRoundTrip(unittest.TestCase):
    def test_bytes_roundtrip_is_stable(self):
        # decode(encode(assemble(x))) re-encoded must byte-for-byte match
        # the first encoding: the IR carries everything the binary did.
        data1 = assemble_bytes(KWAT_KITCHEN_SINK)
        module = decode_module(data1)
        data2 = encode_module(module)
        self.assertEqual(data1, data2)

    def test_decoded_shape(self):
        data = assemble_bytes(KWAT_KITCHEN_SINK)
        m = decode_module(data)
        self.assertEqual(len(m.functions), 2)
        self.assertEqual(len(m.memories), 1)
        self.assertEqual(m.memories[0].min, 1)
        self.assertEqual(m.memories[0].max, 4)
        self.assertEqual(len(m.globals), 1)
        self.assertEqual(len(m.tables), 1)
        self.assertEqual(len(m.elements), 1)
        self.assertEqual(len(m.data), 1)
        self.assertEqual(m.data[0].init, b"hi")
        self.assertEqual(len(m.exports), 3)
        self.assertIsNotNone(m.start)

    def test_bad_magic_rejected(self):
        with self.assertRaises(ValueError):
            decode_module(b"NOPE" + b"\x01\x00\x00\x00")

    def test_bad_version_rejected(self):
        with self.assertRaises(ValueError):
            decode_module(b"\x00asm" + b"\x02\x00\x00\x00")

    def test_truncated_module_raises(self):
        data = assemble_bytes(KWAT_KITCHEN_SINK)
        with self.assertRaises(Exception):
            decode_module(data[:-5])


if __name__ == "__main__":
    unittest.main()
