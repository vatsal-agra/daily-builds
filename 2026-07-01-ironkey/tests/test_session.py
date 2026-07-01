from . import _path  # noqa: F401
import unittest

import session


class TestSession(unittest.TestCase):
    def test_full_demo_passes(self):
        self.assertTrue(session.run_demo(verbose_print=lambda *a: None))

    def test_basic_message_round_trip(self):
        alice = session.Party("Alice")
        bob = session.Party("Bob")
        s_a = session.SecureSession(alice, bob.public_key)
        s_b = session.SecureSession(bob, alice.public_key)

        msg = s_a.encrypt(b"hello")
        self.assertEqual(s_b.decrypt(msg), b"hello")

    def test_replay_is_rejected(self):
        alice = session.Party("Alice")
        bob = session.Party("Bob")
        s_a = session.SecureSession(alice, bob.public_key)
        s_b = session.SecureSession(bob, alice.public_key)

        msg1 = s_a.encrypt(b"first")
        s_b.decrypt(msg1)
        msg2 = s_a.encrypt(b"second")
        s_b.decrypt(msg2)
        with self.assertRaises(ValueError):
            s_b.decrypt(msg1)  # replay

    def test_out_of_order_is_rejected(self):
        alice = session.Party("Alice")
        bob = session.Party("Bob")
        s_a = session.SecureSession(alice, bob.public_key)
        s_b = session.SecureSession(bob, alice.public_key)

        msg1 = s_a.encrypt(b"first")
        msg2 = s_a.encrypt(b"second")
        with self.assertRaises(ValueError):
            s_b.decrypt(msg2)  # arrives before msg1

    def test_tampered_message_rejected(self):
        alice = session.Party("Alice")
        bob = session.Party("Bob")
        s_a = session.SecureSession(alice, bob.public_key)
        s_b = session.SecureSession(bob, alice.public_key)

        msg = s_a.encrypt(b"tamper me")
        bad_ct = bytes([msg.ciphertext[0] ^ 1]) + msg.ciphertext[1:]
        tampered = session.SessionMessage(msg.counter, bad_ct, msg.tag)
        with self.assertRaises(ValueError):
            s_b.decrypt(tampered)

    def test_directions_use_different_keys(self):
        alice = session.Party("Alice")
        bob = session.Party("Bob")
        s_a = session.SecureSession(alice, bob.public_key)
        s_b = session.SecureSession(bob, alice.public_key)
        self.assertNotEqual(s_a._send_key, s_a._recv_key)
        self.assertEqual(s_a._send_key, s_b._recv_key)
        self.assertEqual(s_a._recv_key, s_b._send_key)

    def test_cannot_start_session_with_self(self):
        alice = session.Party("Alice")
        with self.assertRaises(ValueError):
            session.SecureSession(alice, alice.public_key)

    def test_message_serialization_round_trip(self):
        alice = session.Party("Alice")
        bob = session.Party("Bob")
        s_a = session.SecureSession(alice, bob.public_key)
        s_b = session.SecureSession(bob, alice.public_key)
        msg = s_a.encrypt(b"serialize me")
        wire = msg.to_bytes()
        msg2 = session.SessionMessage.from_bytes(wire)
        self.assertEqual(s_b.decrypt(msg2), b"serialize me")


if __name__ == "__main__":
    unittest.main()
