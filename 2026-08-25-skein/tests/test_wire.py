"""Tests for the peer wire protocol: handshake bytes and message framing,
run over real socket pairs (not mocks) so the actual recv-loop code path
is exercised."""

import os
import socket
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from skein import wire


class TestHandshake(unittest.TestCase):
    def test_build_handshake_byte_layout(self):
        info_hash = bytes(range(20))
        peer_id = bytes(range(20, 40))
        hs = wire.build_handshake(info_hash, peer_id)
        self.assertEqual(len(hs), 68)
        self.assertEqual(hs[0], 19)
        self.assertEqual(hs[1:20], b"BitTorrent protocol")
        self.assertEqual(hs[20:28], b"\0" * 8)
        self.assertEqual(hs[28:48], info_hash)
        self.assertEqual(hs[48:68], peer_id)

    def test_rejects_wrong_length_ids(self):
        with self.assertRaises(wire.WireError):
            wire.build_handshake(b"short", b"x" * 20)
        with self.assertRaises(wire.WireError):
            wire.build_handshake(b"x" * 20, b"short")

    def test_handshake_over_real_socket(self):
        a, b = socket.socketpair()
        try:
            info_hash, peer_id = os.urandom(20), os.urandom(20)
            wire.send_handshake(a, info_hash, peer_id)
            got_hash, got_id = wire.recv_handshake(b)
            self.assertEqual(got_hash, info_hash)
            self.assertEqual(got_id, peer_id)
        finally:
            a.close()
            b.close()

    def test_recv_handshake_rejects_bad_protocol_string(self):
        a, b = socket.socketpair()
        try:
            garbage = bytes([19]) + b"NotBitTorrent proto" + b"\0" * 8 + b"x" * 40
            a.sendall(garbage)
            with self.assertRaises(wire.WireError):
                wire.recv_handshake(b)
        finally:
            a.close()
            b.close()


class TestMessageFraming(unittest.TestCase):
    def test_keepalive_round_trip(self):
        a, b = socket.socketpair()
        try:
            a.sendall(wire.encode_keepalive())
            msg_id, payload = wire.recv_message(b)
            self.assertIsNone(msg_id)
            self.assertEqual(payload, b"")
        finally:
            a.close(); b.close()

    def test_choke_family_round_trip(self):
        a, b = socket.socketpair()
        try:
            for mid in (wire.CHOKE, wire.UNCHOKE, wire.INTERESTED, wire.NOT_INTERESTED):
                a.sendall(wire.encode_message(mid))
                got_id, payload = wire.recv_message(b)
                self.assertEqual(got_id, mid)
                self.assertEqual(payload, b"")
        finally:
            a.close(); b.close()

    def test_have_round_trip(self):
        a, b = socket.socketpair()
        try:
            a.sendall(wire.encode_message(wire.HAVE, wire.pack_have(17)))
            msg_id, payload = wire.recv_message(b)
            self.assertEqual(msg_id, wire.HAVE)
            self.assertEqual(wire.unpack_have(payload), 17)
        finally:
            a.close(); b.close()

    def test_request_and_piece_round_trip(self):
        a, b = socket.socketpair()
        try:
            a.sendall(wire.encode_message(wire.REQUEST, wire.pack_request(3, 1024, 16384)))
            msg_id, payload = wire.recv_message(b)
            self.assertEqual(msg_id, wire.REQUEST)
            self.assertEqual(wire.unpack_request(payload), (3, 1024, 16384))

            block = os.urandom(16384)
            b.sendall(wire.encode_message(wire.PIECE, wire.pack_piece(3, 1024, block)))
            msg_id2, payload2 = wire.recv_message(a)
            self.assertEqual(msg_id2, wire.PIECE)
            index, begin, data = wire.unpack_piece(payload2)
            self.assertEqual((index, begin), (3, 1024))
            self.assertEqual(data, block)
        finally:
            a.close(); b.close()

    def test_bitfield_round_trip_and_indices(self):
        a, b = socket.socketpair()
        try:
            # 10 pieces, have indices {0, 3, 9}
            bits = bytearray(2)
            for i in (0, 3, 9):
                bits[i // 8] |= 0x80 >> (i % 8)
            a.sendall(wire.encode_message(wire.BITFIELD, bytes(bits)))
            msg_id, payload = wire.recv_message(b)
            self.assertEqual(msg_id, wire.BITFIELD)
            self.assertEqual(wire.bitfield_indices(payload, 10), {0, 3, 9})
        finally:
            a.close(); b.close()

    def test_recv_timeout_raises_wire_timeout_not_wire_error_disconnect(self):
        a, b = socket.socketpair()
        try:
            with self.assertRaises(wire.WireTimeout):
                wire.recv_message(b, timeout=0.2)
            # WireTimeout must be a WireError (so blanket except still
            # works) but callers should be able to catch it specifically.
            self.assertTrue(issubclass(wire.WireTimeout, wire.WireError))
        finally:
            a.close(); b.close()

    def test_recv_on_closed_socket_raises_wire_error(self):
        a, b = socket.socketpair()
        a.close()
        try:
            with self.assertRaises(wire.WireError):
                wire.recv_message(b)
        finally:
            b.close()

    def test_multiple_messages_pipelined_on_one_socket(self):
        a, b = socket.socketpair()
        try:
            for i in range(5):
                a.sendall(wire.encode_message(wire.HAVE, wire.pack_have(i)))
            for i in range(5):
                msg_id, payload = wire.recv_message(b)
                self.assertEqual(msg_id, wire.HAVE)
                self.assertEqual(wire.unpack_have(payload), i)
        finally:
            a.close(); b.close()


if __name__ == "__main__":
    unittest.main()
