import io
import socket
import struct
import threading
import unittest

from swarm import protocol


class FakeSocket:
    """A minimal in-memory stand-in for a blocking socket, used to test the
    read_* helpers without opening a real TCP connection."""

    def __init__(self, initial: bytes = b""):
        self._buf = io.BytesIO(initial)
        self.sent = bytearray()

    def recv(self, n):
        return self._buf.read(n)

    def sendall(self, data):
        self.sent += data


class TestHandshake(unittest.TestCase):
    def test_roundtrip(self):
        info_hash = bytes(range(20))
        peer_id = bytes(range(20, 40))
        hs = protocol.Handshake(info_hash, peer_id)
        encoded = hs.encode()
        self.assertEqual(len(encoded), protocol.HANDSHAKE_LEN)
        decoded = protocol.Handshake.decode(encoded)
        self.assertEqual(decoded, hs)

    def test_wire_shape(self):
        hs = protocol.Handshake(b"\x11" * 20, b"\x22" * 20)
        encoded = hs.encode()
        self.assertEqual(encoded[0], 19)
        self.assertEqual(encoded[1:20], b"BitTorrent protocol")
        self.assertEqual(encoded[20:28], b"\x00" * 8)
        self.assertEqual(encoded[28:48], b"\x11" * 20)
        self.assertEqual(encoded[48:68], b"\x22" * 20)

    def test_rejects_wrong_length(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.Handshake.decode(b"short")

    def test_rejects_bad_info_hash_length(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.Handshake(b"tooshort", b"\x00" * 20)

    def test_send_and_read_handshake_over_fake_socket(self):
        sock = FakeSocket()
        protocol.send_handshake(sock, b"\x01" * 20, b"\x02" * 20)
        reader = FakeSocket(bytes(sock.sent))
        hs = protocol.read_handshake(reader)
        self.assertEqual(hs.info_hash, b"\x01" * 20)
        self.assertEqual(hs.peer_id, b"\x02" * 20)


class TestMessages(unittest.TestCase):
    def test_no_payload_messages_roundtrip(self):
        for builder, msg_id in [
            (protocol.choke, protocol.MSG_CHOKE),
            (protocol.unchoke, protocol.MSG_UNCHOKE),
            (protocol.interested, protocol.MSG_INTERESTED),
            (protocol.not_interested, protocol.MSG_NOT_INTERESTED),
        ]:
            msg = builder()
            sock = FakeSocket()
            protocol.send_message(sock, msg)
            reader = FakeSocket(bytes(sock.sent))
            parsed = protocol.read_message(reader)
            self.assertIsInstance(parsed, protocol.SimpleMsg)
            self.assertEqual(parsed.id, msg_id)

    def test_have_roundtrip(self):
        sock = FakeSocket()
        protocol.send_message(sock, protocol.have(7))
        reader = FakeSocket(bytes(sock.sent))
        parsed = protocol.read_message(reader)
        self.assertEqual(parsed, protocol.HaveMsg(7))

    def test_bitfield_roundtrip(self):
        bits = bytes([0b10110000, 0b00000001])
        sock = FakeSocket()
        protocol.send_message(sock, protocol.bitfield(bits))
        reader = FakeSocket(bytes(sock.sent))
        parsed = protocol.read_message(reader)
        self.assertEqual(parsed, protocol.BitfieldMsg(bits))

    def test_request_roundtrip(self):
        sock = FakeSocket()
        protocol.send_message(sock, protocol.request(3, 16384, 16384))
        reader = FakeSocket(bytes(sock.sent))
        parsed = protocol.read_message(reader)
        self.assertEqual(parsed, protocol.RequestMsg(3, 16384, 16384))

    def test_piece_roundtrip(self):
        block = bytes(range(256)) * 4
        sock = FakeSocket()
        protocol.send_message(sock, protocol.piece(2, 0, block))
        reader = FakeSocket(bytes(sock.sent))
        parsed = protocol.read_message(reader)
        self.assertEqual(parsed, protocol.PieceMsg(2, 0, block))

    def test_cancel_roundtrip(self):
        sock = FakeSocket()
        protocol.send_message(sock, protocol.cancel(1, 0, 16384))
        reader = FakeSocket(bytes(sock.sent))
        parsed = protocol.read_message(reader)
        self.assertEqual(parsed, protocol.CancelMsg(1, 0, 16384))

    def test_keepalive_decodes_to_none(self):
        sock = FakeSocket()
        protocol.send_keepalive(sock)
        reader = FakeSocket(bytes(sock.sent))
        self.assertIsNone(protocol.read_message(reader))

    def test_length_prefix_is_big_endian_four_bytes(self):
        msg = protocol.have(1)
        encoded = msg.encode()
        length = struct.unpack(">I", encoded[:4])[0]
        self.assertEqual(length, len(encoded) - 4)

    def test_rejects_oversized_message(self):
        sock = FakeSocket(struct.pack(">I", 999_999_999))
        with self.assertRaises(protocol.ProtocolError):
            protocol.read_message(sock, max_length=1024)

    def test_choke_unchoke_reject_nonempty_payload(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.parse_message(protocol.Message(protocol.MSG_CHOKE, b"unexpected"))

    def test_unknown_message_id_rejected(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.parse_message(protocol.Message(99, b""))

    def test_truncated_request_payload_rejected(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.parse_message(protocol.Message(protocol.MSG_REQUEST, b"\x00" * 5))

    def test_read_message_raises_on_early_eof(self):
        sock = FakeSocket(struct.pack(">I", 10) + b"\x00\x01\x02")  # promises 10, gives 3
        with self.assertRaises(ConnectionError):
            protocol.read_message(sock)


class TestRealSocketPair(unittest.TestCase):
    """Sanity check against actual TCP sockets, not just the FakeSocket
    stand-in, since real peers talk over a real kernel socket buffer."""

    def test_handshake_and_message_over_real_localhost_socket(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        result = {}

        def server():
            conn, _ = srv.accept()
            hs = protocol.read_handshake(conn)
            result["server_saw"] = hs
            protocol.send_handshake(conn, hs.info_hash, b"S" * 20)
            msg = protocol.read_message(conn)
            result["server_msg"] = msg
            conn.close()

        t = threading.Thread(target=server)
        t.start()

        client = socket.create_connection(("127.0.0.1", port))
        protocol.send_handshake(client, b"H" * 20, b"C" * 20)
        client_hs = protocol.read_handshake(client)
        protocol.send_message(client, protocol.piece(0, 0, b"hello-block"))
        t.join(timeout=5)
        client.close()
        srv.close()

        self.assertEqual(result["server_saw"].info_hash, b"H" * 20)
        self.assertEqual(client_hs.peer_id, b"S" * 20)
        self.assertEqual(result["server_msg"], protocol.PieceMsg(0, 0, b"hello-block"))


if __name__ == "__main__":
    unittest.main()
