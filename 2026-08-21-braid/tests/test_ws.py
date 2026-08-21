import base64
import os
import socket
import struct
import unittest

from server import ws


class TestWebSocketFraming(unittest.TestCase):
    def setUp(self):
        self.server_sock, self.client_sock = socket.socketpair()
        self.addCleanup(self.server_sock.close)
        self.addCleanup(self.client_sock.close)

    def _handshake(self):
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET /ws?room=demo HTTP/1.1\r\n"
            f"Host: localhost\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
        self.client_sock.sendall(request)
        method, path, headers = ws.parse_http_request(self.server_sock)
        self.assertEqual(method, "GET")
        self.assertEqual(path, "/ws?room=demo")
        self.assertTrue(ws.is_websocket_upgrade(headers))
        ws.do_handshake(self.server_sock, headers)
        resp = self.client_sock.recv(4096).decode()
        self.assertIn("101", resp.splitlines()[0])
        accept_line = [l for l in resp.splitlines() if l.lower().startswith("sec-websocket-accept")][0]
        accept_value = accept_line.split(":", 1)[1].strip()
        self.assertEqual(accept_value, ws.compute_accept(key))

    def _client_masked_frame(self, text: str) -> bytes:
        payload = text.encode()
        mask_key = os.urandom(4)
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        length = len(payload)
        if length <= 125:
            header = bytes([0x81, 0x80 | length])
        elif length <= 0xFFFF:
            header = bytes([0x81, 0x80 | 126]) + struct.pack(">H", length)
        else:
            header = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", length)
        return header + mask_key + masked

    def test_handshake(self):
        self._handshake()

    def test_server_to_client_frame_over_125_bytes(self):
        self._handshake()
        payload = "x" * 200
        ws.send_text(self.server_sock, "hello " + payload)
        raw = self.client_sock.recv(65536)
        self.assertTrue(raw[0] & 0x80)
        self.assertEqual(raw[0] & 0x0F, ws.OPCODE_TEXT)
        self.assertEqual(raw[1] & 0x7F, 126)
        plen = struct.unpack(">H", raw[2:4])[0]
        self.assertEqual(raw[4:4 + plen].decode(), "hello " + payload)

    def test_client_to_server_masked_frame(self):
        self._handshake()
        self.client_sock.sendall(self._client_masked_frame('{"type":"insert"}'))
        msg = ws.recv_text(self.server_sock)
        self.assertEqual(msg, '{"type":"insert"}')

    def test_ping_is_transparent_and_gets_ponged(self):
        self._handshake()

        def client_ping_frame(payload=b"hi"):
            mask_key = os.urandom(4)
            masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
            header = bytes([0x89, 0x80 | len(payload)])
            return header + mask_key + masked

        self.client_sock.sendall(client_ping_frame())
        self.client_sock.sendall(self._client_masked_frame('{"after":"ping"}'))
        msg = ws.recv_text(self.server_sock)
        self.assertEqual(msg, '{"after":"ping"}')
        pong_raw = self.client_sock.recv(65536)
        self.assertEqual(pong_raw[0] & 0x0F, ws.OPCODE_PONG)

    def test_64_bit_length_frame(self):
        self._handshake()
        big = "y" * 70000
        ws.send_text(self.server_sock, big)
        raw = b""
        while len(raw) < len(big) + 10:
            chunk = self.client_sock.recv(200000)
            if not chunk:
                break
            raw += chunk
        self.assertEqual(raw[1] & 0x7F, 127)
        plen = struct.unpack(">Q", raw[2:10])[0]
        self.assertEqual(plen, 70000)
        self.assertEqual(raw[10:10 + plen].decode(), big)

    def test_close_frame_raises_websocket_closed(self):
        self._handshake()
        self.client_sock.sendall(ws.encode_frame(b"", ws.OPCODE_CLOSE))
        with self.assertRaises(ws.WebSocketClosed):
            ws.recv_text(self.server_sock)

    def test_fragmented_message_raises_not_implemented(self):
        self._handshake()
        # a fin=0 text frame -- documented as unsupported, see server/ws.py
        header = bytes([0x01, 0x80 | 1])  # fin=0, opcode=text, len=1, masked
        mask_key = os.urandom(4)
        masked = bytes([ord("a") ^ mask_key[0]])
        self.client_sock.sendall(header + mask_key + masked)
        with self.assertRaises(NotImplementedError):
            ws.recv_text(self.server_sock)


if __name__ == "__main__":
    unittest.main()
