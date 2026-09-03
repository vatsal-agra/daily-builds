import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from keystone import pow as pow_module


class TestCompactBits(unittest.TestCase):
    def test_roundtrip_various_targets(self):
        for target in (1, 0xFFFF, 1 << 100, 1 << 200, pow_module.MAX_TARGET, (1 << 255) - 1):
            bits = pow_module.target_to_bits(target)
            recovered = pow_module.bits_to_target(bits)
            # compact form loses precision to a 24-bit mantissa; recovered
            # target should be within a tiny relative error, and never
            # larger than the original (never silently easier than asked)
            self.assertLessEqual(recovered, target * 1.001 + 1)

    def test_known_encoding(self):
        # 0xffff at exponent 3 (byte-length 3) is exactly representable
        target = 0xFFFF00
        bits = pow_module.target_to_bits(target)
        self.assertEqual(pow_module.bits_to_target(bits), target)

    def test_zero_target_rejected(self):
        with self.assertRaises(ValueError):
            pow_module.target_to_bits(0)


class TestMeetsTarget(unittest.TestCase):
    def test_low_hash_meets_high_target(self):
        easy_bits = pow_module.target_to_bits(pow_module.MAX_TARGET)
        low_hash = (0).to_bytes(32, "big")
        self.assertTrue(pow_module.meets_target(low_hash, easy_bits))

    def test_max_hash_fails_tiny_target(self):
        hard_bits = pow_module.target_to_bits(1)
        max_hash = (b"\xff" * 32)
        self.assertFalse(pow_module.meets_target(max_hash, hard_bits))

    def test_block_work_increases_with_difficulty(self):
        easy_bits = pow_module.target_to_bits(pow_module.MAX_TARGET)
        hard_bits = pow_module.target_to_bits(pow_module.MAX_TARGET // 1000)
        self.assertGreater(pow_module.block_work(hard_bits), pow_module.block_work(easy_bits))


class TestMining(unittest.TestCase):
    def test_mine_finds_a_valid_nonce(self):
        bits = pow_module.target_to_bits(pow_module.MAX_TARGET)  # easiest possible: succeeds almost immediately

        def prefix_fn(nonce):
            return f"fixed-header-{nonce}".encode()

        result = pow_module.mine(prefix_fn, bits, max_nonce=1000)
        self.assertIsNotNone(result)
        nonce, h = result
        self.assertTrue(pow_module.meets_target(h, bits))

    def test_mine_respects_should_stop(self):
        # an essentially impossible target (tiny) that should never succeed,
        # combined with an immediately-true should_stop, must return promptly
        bits = pow_module.target_to_bits(1)

        def prefix_fn(nonce):
            return f"header-{nonce}".encode()

        result = pow_module.mine(prefix_fn, bits, max_nonce=1 << 32, should_stop=lambda: True)
        self.assertIsNone(result)

    def test_mine_exhausts_max_nonce_cleanly(self):
        bits = pow_module.target_to_bits(1)  # essentially impossible in a small nonce range

        def prefix_fn(nonce):
            return f"header-{nonce}".encode()

        result = pow_module.mine(prefix_fn, bits, max_nonce=100)
        self.assertIsNone(result)


class TestRetarget(unittest.TestCase):
    def test_faster_than_expected_makes_it_harder(self):
        old_bits = pow_module.target_to_bits(pow_module.MAX_TARGET // 100)
        # blocks came in half the expected time -> should get harder (smaller target)
        expected = pow_module.TARGET_BLOCK_TIME * pow_module.RETARGET_INTERVAL
        new_bits = pow_module.next_bits(old_bits, first_block_time=0, last_block_time=expected / 2,
                                         blocks_in_period=pow_module.RETARGET_INTERVAL)
        self.assertLess(pow_module.bits_to_target(new_bits), pow_module.bits_to_target(old_bits))

    def test_slower_than_expected_makes_it_easier(self):
        old_bits = pow_module.target_to_bits(pow_module.MAX_TARGET // 1000)
        expected = pow_module.TARGET_BLOCK_TIME * pow_module.RETARGET_INTERVAL
        new_bits = pow_module.next_bits(old_bits, first_block_time=0, last_block_time=expected * 2,
                                         blocks_in_period=pow_module.RETARGET_INTERVAL)
        self.assertGreater(pow_module.bits_to_target(new_bits), pow_module.bits_to_target(old_bits))

    def test_retarget_clamped_to_4x(self):
        old_bits = pow_module.target_to_bits(pow_module.MAX_TARGET // 1000)
        expected = pow_module.TARGET_BLOCK_TIME * pow_module.RETARGET_INTERVAL
        # a huge, wildly-slow timespan should still only make it at most 4x easier
        new_bits = pow_module.next_bits(old_bits, first_block_time=0, last_block_time=expected * 1000,
                                         blocks_in_period=pow_module.RETARGET_INTERVAL)
        ratio = pow_module.bits_to_target(new_bits) / pow_module.bits_to_target(old_bits)
        self.assertLessEqual(ratio, 4.01)

    def test_retarget_clamped_to_quarter(self):
        old_bits = pow_module.target_to_bits(pow_module.MAX_TARGET // 1000)
        expected = pow_module.TARGET_BLOCK_TIME * pow_module.RETARGET_INTERVAL
        new_bits = pow_module.next_bits(old_bits, first_block_time=0, last_block_time=expected / 1000,
                                         blocks_in_period=pow_module.RETARGET_INTERVAL)
        ratio = pow_module.bits_to_target(new_bits) / pow_module.bits_to_target(old_bits)
        self.assertGreaterEqual(ratio, 0.24)

    def test_retarget_never_exceeds_max_target(self):
        old_bits = pow_module.target_to_bits(pow_module.MAX_TARGET)  # already at the ceiling
        expected = pow_module.TARGET_BLOCK_TIME * pow_module.RETARGET_INTERVAL
        new_bits = pow_module.next_bits(old_bits, first_block_time=0, last_block_time=expected * 4,
                                         blocks_in_period=pow_module.RETARGET_INTERVAL)
        self.assertLessEqual(pow_module.bits_to_target(new_bits), pow_module.MAX_TARGET)

    def test_regression_starting_difficulty_never_cliffs_against_max_target(self):
        """Regression test for REVIEW.md finding #1: the difficulty-retarget
        cliff. Any bits value that is a legitimate valid starting difficulty
        (target <= MAX_TARGET) must never see next_bits() clamp it down by
        more than the normal 4x-per-period rule, even in the "blocks came
        in far faster than expected" case that triggered the original bug.
        """
        starting_bits = pow_module.target_to_bits(pow_module.MAX_TARGET)
        expected = pow_module.TARGET_BLOCK_TIME * pow_module.RETARGET_INTERVAL
        # blocks came in much faster than expected (as happens with several
        # nodes mining an easy target in parallel)
        new_bits = pow_module.next_bits(starting_bits, first_block_time=0, last_block_time=expected / 10,
                                         blocks_in_period=pow_module.RETARGET_INTERVAL)
        old_target = pow_module.bits_to_target(starting_bits)
        new_target = pow_module.bits_to_target(new_bits)
        ratio = old_target / new_target
        self.assertLessEqual(ratio, 4.01, "a single retarget step must never harden by more than ~4x")


if __name__ == "__main__":
    unittest.main()
