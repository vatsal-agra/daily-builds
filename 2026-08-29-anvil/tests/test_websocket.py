import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anvil import websocket as ws  # noqa: E402


def mask_frame(opcode, payload, fin=True, mask_key=b"\x01\x02\x03\x04"):
    """Build a *client* frame (masked) by hand, independent of anvil's own
    encoder, so decode tests aren't just checking encode(decode(x)) == x."""
    b0 = (0x80 if fin else 0) | opcode
    length = len(payload)
    if length <= 125:
        header = struct.pack("!BB", b0, 0x80 | length)
    elif length <= 0xFFFF:
        header = struct.pack("!BBH", b0, 0x80 | 126, length)
    else:
        header = struct.pack("!BBQ", b0, 0x80 | 127, length)
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return header + mask_key + masked


class TestHandshake(unittest.TestCase):
    def test_known_accept_value(self):
        # the exact example from RFC 6455 section 1.3
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        self.assertEqual(ws.compute_accept(key), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_is_upgrade_request(self):
        from anvil.http_message import HeaderDict
        h = HeaderDict([("Connection", "Upgrade"), ("Upgrade", "websocket")])
        self.assertTrue(ws.is_upgrade_request(h))
        h2 = HeaderDict([("Connection", "keep-alive")])
        self.assertFalse(ws.is_upgrade_request(h2))

    def test_validate_handshake_rejects_bad_version(self):
        from anvil.http_message import HeaderDict
        h = HeaderDict([("Sec-WebSocket-Version", "8"), ("Sec-WebSocket-Key", "x" * 24)])
        with self.assertRaises(ws.WSProtocolError):
            ws.validate_handshake(h)

    def test_validate_handshake_rejects_missing_key(self):
        from anvil.http_message import HeaderDict
        h = HeaderDict([("Sec-WebSocket-Version", "13")])
        with self.assertRaises(ws.WSProtocolError):
            ws.validate_handshake(h)


class TestFrameDecoding(unittest.TestCase):
    def test_short_text_frame(self):
        p = ws.WebSocketParser()
        frame = mask_frame(ws.OP_TEXT, b"hello")
        msgs = p.feed(frame)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].kind, "data")
        self.assertEqual(msgs[0].payload, b"hello")

    def test_medium_length_16bit(self):
        p = ws.WebSocketParser()
        payload = b"x" * 300
        msgs = p.feed(mask_frame(ws.OP_BINARY, payload))
        self.assertEqual(msgs[0].payload, payload)

    def test_split_across_feeds(self):
        p = ws.WebSocketParser()
        frame = mask_frame(ws.OP_TEXT, b"hello world")
        self.assertEqual(p.feed(frame[:3]), [])
        self.assertEqual(p.feed(frame[3:7]), [])
        msgs = p.feed(frame[7:])
        self.assertEqual(msgs[0].payload, b"hello world")

    def test_fragmented_message_reassembled(self):
        p = ws.WebSocketParser()
        f1 = mask_frame(ws.OP_TEXT, b"hel", fin=False)
        f2 = mask_frame(ws.OP_CONTINUATION, b"lo ", fin=False)
        f3 = mask_frame(ws.OP_CONTINUATION, b"world", fin=True)
        self.assertEqual(p.feed(f1), [])
        self.assertEqual(p.feed(f2), [])
        msgs = p.feed(f3)
        self.assertEqual(msgs[0].payload, b"hello world")

    def test_control_frame_between_fragments(self):
        p = ws.WebSocketParser()
        f1 = mask_frame(ws.OP_TEXT, b"part1", fin=False)
        ping = mask_frame(ws.OP_PING, b"ping-data")
        f2 = mask_frame(ws.OP_CONTINUATION, b"part2", fin=True)
        self.assertEqual(p.feed(f1), [])
        msgs = p.feed(ping)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].kind, "control")
        self.assertEqual(msgs[0].opcode, ws.OP_PING)
        msgs2 = p.feed(f2)
        self.assertEqual(msgs2[0].payload, b"part1part2")

    def test_unmasked_client_frame_rejected(self):
        p = ws.WebSocketParser()
        header = struct.pack("!BB", 0x80 | ws.OP_TEXT, 5)
        with self.assertRaises(ws.WSProtocolError):
            p.feed(header + b"hello")

    def test_oversized_control_frame_rejected(self):
        p = ws.WebSocketParser()
        with self.assertRaises(ws.WSProtocolError):
            p.feed(mask_frame(ws.OP_PING, b"x" * 126))

    def test_unfinished_control_frame_rejected(self):
        p = ws.WebSocketParser()
        with self.assertRaises(ws.WSProtocolError):
            p.feed(mask_frame(ws.OP_PING, b"hi", fin=False))

    def test_unexpected_continuation_rejected(self):
        p = ws.WebSocketParser()
        with self.assertRaises(ws.WSProtocolError):
            p.feed(mask_frame(ws.OP_CONTINUATION, b"oops"))

    def test_new_data_frame_mid_fragment_rejected(self):
        p = ws.WebSocketParser()
        p.feed(mask_frame(ws.OP_TEXT, b"part1", fin=False))
        with self.assertRaises(ws.WSProtocolError):
            p.feed(mask_frame(ws.OP_TEXT, b"oops"))

    def test_nonzero_rsv_rejected(self):
        p = ws.WebSocketParser()
        header = struct.pack("!BB", 0x80 | 0x40 | ws.OP_TEXT, 0x80 | 2)
        with self.assertRaises(ws.WSProtocolError):
            p.feed(header + b"\x00\x00\x00\x00hi")


class TestFrameEncoding(unittest.TestCase):
    def test_encode_decode_roundtrip_short(self):
        encoded = ws.encode_text("hello there")
        # server frames are unmasked; decode with require_mask=False
        p = ws.WebSocketParser(require_mask=False)
        msgs = p.feed(encoded)
        self.assertEqual(msgs[0].payload.decode(), "hello there")

    def test_encode_decode_roundtrip_large(self):
        payload = b"z" * 70000  # forces the 64-bit extended length path
        encoded = ws.encode_binary(payload)
        p = ws.WebSocketParser(require_mask=False)
        msgs = p.feed(encoded)
        self.assertEqual(msgs[0].payload, payload)

    def test_close_frame_roundtrip(self):
        encoded = ws.encode_close(1001, "bye")
        p = ws.WebSocketParser(require_mask=False)
        msgs = p.feed(encoded)
        code, reason = ws.parse_close_payload(msgs[0].payload)
        self.assertEqual(code, 1001)
        self.assertEqual(reason, "bye")

    def test_empty_close_payload(self):
        code, reason = ws.parse_close_payload(b"")
        self.assertEqual((code, reason), (1005, ""))


if __name__ == "__main__":
    unittest.main()
