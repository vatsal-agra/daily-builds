import os
import random
import socket
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from undertow.netsim import NetSim


def _free_addr():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    addr = s.getsockname()
    s.close()
    return addr


class TestNetSim(unittest.TestCase):
    def test_zero_loss_forwards_every_packet(self):
        a_addr, b_addr, relay_addr = _free_addr(), _free_addr(), _free_addr()
        a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        a.bind(a_addr)
        b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        b.bind(b_addr)
        b.settimeout(5.0)

        net = NetSim(relay_addr, a_addr, b_addr, loss=0.0, delay_range=(0.001, 0.002))
        net.start()
        try:
            for i in range(50):
                a.sendto(f"msg-{i}".encode(), relay_addr)
            received = set()
            for _ in range(50):
                data, _ = b.recvfrom(1024)
                received.add(data.decode())
            self.assertEqual(received, {f"msg-{i}" for i in range(50)})
            self.assertEqual(net.stats["forwarded"], 50)
            self.assertEqual(net.stats["dropped"], 0)
        finally:
            net.stop()
            a.close()
            b.close()

    def test_configured_loss_rate_actually_drops_packets(self):
        a_addr, b_addr, relay_addr = _free_addr(), _free_addr(), _free_addr()
        a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        a.bind(a_addr)
        b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        b.bind(b_addr)
        b.settimeout(0.3)

        net = NetSim(relay_addr, a_addr, b_addr, loss=0.5, delay_range=(0.001, 0.002), rng=random.Random(1))
        net.start()
        try:
            n = 400
            for i in range(n):
                a.sendto(str(i).encode(), relay_addr)
            got = 0
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                try:
                    b.recvfrom(1024)
                    got += 1
                except socket.timeout:
                    break
            # dropped is updated synchronously as each datagram is
            # classified, but forwarded is only updated later when its
            # scheduled delivery actually fires — so give any still-queued
            # deliveries a moment to land before checking the totals,
            # rather than trusting the receive loop's own timeout to mean
            # "the relay is done" (it doesn't: caught by this test itself
            # flaking on dropped+forwarded landing short of n).
            stats_deadline = time.monotonic() + 2.0
            while (net.stats["dropped"] + net.stats["forwarded"]) < n and time.monotonic() < stats_deadline:
                time.sleep(0.02)
            # With loss=0.5 over 400 packets, forwarding is extremely
            # unlikely to land outside roughly [30%, 70%] purely by chance.
            self.assertGreater(got, n * 0.30)
            self.assertLess(got, n * 0.70)
            self.assertEqual(net.stats["dropped"] + net.stats["forwarded"], n)
            self.assertGreater(net.stats["dropped"], 0)
        finally:
            net.stop()
            a.close()
            b.close()

    def test_dropped_packet_never_arrives_not_just_delayed(self):
        # Loss must be genuine (never delivered), not "very delayed."
        a_addr, b_addr, relay_addr = _free_addr(), _free_addr(), _free_addr()
        a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        a.bind(a_addr)
        b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        b.bind(b_addr)
        b.settimeout(0.2)

        net = NetSim(relay_addr, a_addr, b_addr, loss=1.0, delay_range=(0.0, 0.0))
        net.start()
        try:
            a.sendto(b"should never arrive", relay_addr)
            with self.assertRaises(socket.timeout):
                b.recvfrom(1024)
            self.assertEqual(net.stats["dropped"], 1)
            self.assertEqual(net.stats["forwarded"], 0)
        finally:
            net.stop()
            a.close()
            b.close()

    def test_relay_forwards_both_directions(self):
        a_addr, b_addr, relay_addr = _free_addr(), _free_addr(), _free_addr()
        a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        a.bind(a_addr)
        a.settimeout(2.0)
        b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        b.bind(b_addr)
        b.settimeout(2.0)

        net = NetSim(relay_addr, a_addr, b_addr, loss=0.0, delay_range=(0.001, 0.001))
        net.start()
        try:
            a.sendto(b"ping", relay_addr)
            data, _ = b.recvfrom(1024)
            self.assertEqual(data, b"ping")
            b.sendto(b"pong", relay_addr)
            data, _ = a.recvfrom(1024)
            self.assertEqual(data, b"pong")
        finally:
            net.stop()
            a.close()
            b.close()


if __name__ == "__main__":
    unittest.main()
