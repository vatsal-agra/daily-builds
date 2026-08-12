import random
import unittest

from nonce.core.difficulty import (
    target_to_bits, bits_to_target, next_bits, work_for_bits,
    MAX_TARGET, RETARGET_INTERVAL, TARGET_BLOCK_TIME_SECONDS, MAX_ADJUSTMENT_FACTOR,
)


class TestCompactEncoding(unittest.TestCase):
    def test_round_trip_within_precision(self):
        rng = random.Random(1)
        for _ in range(500):
            t = rng.randint(1, MAX_TARGET)
            t2 = bits_to_target(target_to_bits(t))
            self.assertLessEqual(abs(t2 - t) / t, 1e-4)

    def test_max_target_round_trips(self):
        self.assertLessEqual(abs(bits_to_target(target_to_bits(MAX_TARGET)) - MAX_TARGET) / MAX_TARGET, 1e-4)


class TestRetarget(unittest.TestCase):
    def setUp(self):
        self.bits0 = target_to_bits(MAX_TARGET)

    def test_no_retarget_off_boundary(self):
        # heights not on a RETARGET_INTERVAL boundary must return bits unchanged
        for h in range(RETARGET_INTERVAL - 1):
            self.assertEqual(next_bits(self.bits0, h, actual_timespan=999999), self.bits0)

    def test_faster_than_expected_tightens_target(self):
        expected = RETARGET_INTERVAL * TARGET_BLOCK_TIME_SECONDS
        harder = next_bits(self.bits0, RETARGET_INTERVAL - 1, actual_timespan=expected // 4)
        self.assertLess(bits_to_target(harder), bits_to_target(self.bits0))

    def test_slower_than_expected_loosens_target(self):
        expected = RETARGET_INTERVAL * TARGET_BLOCK_TIME_SECONDS
        easier = next_bits(self.bits0, RETARGET_INTERVAL - 1, actual_timespan=expected * 4)
        self.assertGreaterEqual(bits_to_target(easier), bits_to_target(self.bits0))

    def test_adjustment_clamped_to_4x(self):
        expected = RETARGET_INTERVAL * TARGET_BLOCK_TIME_SECONDS
        # absurdly fast blocks should clamp to at most 1/4x the target, not go further
        harder = next_bits(self.bits0, RETARGET_INTERVAL - 1, actual_timespan=1)
        ratio = bits_to_target(harder) / bits_to_target(self.bits0)
        self.assertGreaterEqual(ratio, 1 / MAX_ADJUSTMENT_FACTOR - 0.01)

    def test_target_never_exceeds_max(self):
        expected = RETARGET_INTERVAL * TARGET_BLOCK_TIME_SECONDS
        easier = next_bits(self.bits0, RETARGET_INTERVAL - 1, actual_timespan=expected * 1000)
        self.assertLessEqual(bits_to_target(easier), MAX_TARGET * 1.0001)


class TestWork(unittest.TestCase):
    def test_smaller_target_is_more_work(self):
        harder_bits = target_to_bits(MAX_TARGET // 4)
        easier_bits = target_to_bits(MAX_TARGET)
        self.assertGreater(work_for_bits(harder_bits), work_for_bits(easier_bits))

    def test_work_is_positive(self):
        self.assertGreater(work_for_bits(target_to_bits(MAX_TARGET)), 0)


if __name__ == "__main__":
    unittest.main()
