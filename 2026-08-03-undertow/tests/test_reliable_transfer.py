import hashlib
import os
import random
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.helpers import free_triplet
from undertow.eventlog import EventLog
from undertow.fileapp import receive_file, send_file
from undertow.netsim import NetSim


def run_transfer(data, loss=0.0, dup_prob=0.0, delay_range=(0.001, 0.005), reorder_prob=0.0, seed=None, timeout=40.0):
    client_addr, server_addr, relay_addr = free_triplet()
    log_s, log_r = EventLog("send"), EventLog("recv")
    net = NetSim(
        relay_addr, client_addr, server_addr,
        loss=loss, dup_prob=dup_prob, delay_range=delay_range, reorder_prob=reorder_prob,
        rng=random.Random(seed) if seed is not None else None,
    )
    net.start()
    result = {}
    errors = {}

    def run_receiver():
        try:
            result["recv"] = receive_file(server_addr, event_log=log_r, name="recv", timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            errors["recv"] = exc

    t = threading.Thread(target=run_receiver)
    t.start()
    time.sleep(0.1)  # let the receiver reach listen() before the client dials
    try:
        result["send"] = send_file(client_addr, relay_addr, data, event_log=log_s, name="send", timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        errors["send"] = exc
    t.join(timeout=timeout + 5)
    net.stop()

    if errors:
        raise AssertionError(f"transfer failed: {errors}")
    return result, log_s, log_r, net


class TestReliableTransfer(unittest.TestCase):
    def test_byte_exact_delivery_with_zero_loss(self):
        data = os.urandom(20_000)
        result, _, _, net = run_transfer(data, loss=0.0, delay_range=(0.001, 0.003))
        self.assertEqual(result["recv"]["data"], data)
        self.assertEqual(result["send"]["sha256"], result["recv"]["sha256"])
        self.assertEqual(net.stats["dropped"], 0)

    def test_zero_configured_loss_and_zero_jitter_means_zero_retransmits(self):
        # An idealized network (no loss, *no jitter either* — a fixed
        # delay) must never need a retransmission. This isolates protocol
        # correctness from the separate, legitimate phenomenon of jitter
        # causing occasional reordering-induced fast retransmits (real
        # TCP has this same false-positive behavior).
        data = os.urandom(20_000)
        result, log_s, _, net = run_transfer(data, loss=0.0, delay_range=(0.004, 0.004), seed=123)
        self.assertEqual(result["recv"]["data"], data)
        retransmits = [e for e in log_s.to_list() if e["kind"] == "retransmit"]
        self.assertEqual(retransmits, [])

    def test_byte_exact_delivery_under_moderate_loss(self):
        data = os.urandom(40_000)
        # Note: `seed` fixes which packets NetSim decides to drop/dup/
        # reorder, but not *when* real background threads get scheduled —
        # so even a seeded run's exact timing (and therefore which
        # in-flight segments a given drop actually lands on) has some
        # real variance. A generous timeout accounts for the rare slow
        # draw rather than chasing full determinism, which real threads +
        # real RTO timers don't give for free (see REVIEW.md).
        result, log_s, _, net = run_transfer(
            data, loss=0.08, dup_prob=0.02, reorder_prob=0.05,
            delay_range=(0.003, 0.015), seed=42, timeout=90,
        )
        self.assertEqual(result["recv"]["data"], data)
        self.assertEqual(result["send"]["sha256"], result["recv"]["sha256"])
        self.assertGreater(net.stats["dropped"], 0)  # loss really happened
        retransmits = [e for e in log_s.to_list() if e["kind"] == "retransmit"]
        self.assertGreater(len(retransmits), 0)  # and the protocol recovered from it

    def test_byte_exact_delivery_with_duplication_and_reordering(self):
        data = os.urandom(25_000)
        result, _, _, net = run_transfer(
            data, loss=0.03, dup_prob=0.15, reorder_prob=0.2,
            delay_range=(0.002, 0.02), seed=7, timeout=45,
        )
        self.assertEqual(result["recv"]["data"], data)
        self.assertGreater(net.stats["duplicated"], 0)

    def test_small_transfer_survives_high_loss(self):
        data = os.urandom(8_000)
        result, _, _, net = run_transfer(
            data, loss=0.25, dup_prob=0.02, reorder_prob=0.05,
            delay_range=(0.003, 0.012), seed=99, timeout=60,
        )
        self.assertEqual(result["recv"]["data"], data)
        self.assertEqual(hashlib.sha256(data).hexdigest(), result["recv"]["sha256"])

    def test_empty_transfer(self):
        result, _, _, _ = run_transfer(b"", loss=0.0, delay_range=(0.001, 0.002))
        self.assertEqual(result["recv"]["data"], b"")
        self.assertEqual(result["recv"]["bytes_received"], 0)


if __name__ == "__main__":
    unittest.main()
