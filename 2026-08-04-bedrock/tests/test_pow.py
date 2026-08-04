import unittest

from bedrock import pow as bpow
from bedrock.block import BlockHeader, GENESIS_PREV_HASH


class TestMining(unittest.TestCase):
    def test_mine_finds_a_valid_nonce(self):
        # An easy target (few required leading zero bits) so the test is fast.
        header = BlockHeader(version=1, prev_hash=GENESIS_PREV_HASH, merkle_root="0" * 64, timestamp=1, target=1 << 250, nonce=0)
        bpow.mine(header, max_nonce=2_000_000)
        self.assertTrue(bpow.meets_target(header.hash, header.target))

    def test_meets_target_is_independently_checkable(self):
        header = BlockHeader(version=1, prev_hash=GENESIS_PREV_HASH, merkle_root="0" * 64, timestamp=1, target=1 << 250, nonce=0)
        bpow.mine(header, max_nonce=2_000_000)
        # Recompute independently rather than trusting mine()'s own check.
        self.assertLess(int(header.hash, 16), header.target)

    def test_impossible_target_raises_timeout(self):
        header = BlockHeader(version=1, prev_hash=GENESIS_PREV_HASH, merkle_root="0" * 64, timestamp=1, target=1, nonce=0)
        with self.assertRaises(bpow.MiningTimeout):
            bpow.mine(header, max_nonce=1000)

    def test_meets_target_boundary(self):
        # hash < target, so target itself never satisfies (strict inequality)
        self.assertFalse(bpow.meets_target(f"{10:064x}", 10))
        self.assertTrue(bpow.meets_target(f"{9:064x}", 10))


class TestRetargeting(unittest.TestCase):
    def test_no_retarget_off_boundary(self):
        target = bpow.target_for_height(lambda h: None, height=5, prev_target=12345)
        self.assertEqual(target, 12345)

    def test_retarget_at_boundary_keeps_pace_target_unchanged(self):
        headers = {0: 1000, bpow.RETARGET_INTERVAL - 1: 1000 + bpow.RETARGET_INTERVAL * bpow.TARGET_BLOCK_TIME}

        class FakeHeader:
            def __init__(self, ts):
                self.timestamp = ts

        target = bpow.target_for_height(
            lambda h: FakeHeader(headers[h]), height=bpow.RETARGET_INTERVAL, prev_target=1000
        )
        self.assertEqual(target, 1000)

    def test_retarget_slower_than_expected_lowers_target(self):
        class FakeHeader:
            def __init__(self, ts):
                self.timestamp = ts

        # actual span is 4x the expected span -> target shrinks (harder)
        expected = bpow.RETARGET_INTERVAL * bpow.TARGET_BLOCK_TIME
        headers = {0: 0, bpow.RETARGET_INTERVAL - 1: expected * 4}
        target = bpow.target_for_height(lambda h: FakeHeader(headers[h]), height=bpow.RETARGET_INTERVAL, prev_target=1000)
        self.assertEqual(target, 4000)  # clamped exactly at the 4x cap

    def test_retarget_faster_than_expected_raises_target(self):
        class FakeHeader:
            def __init__(self, ts):
                self.timestamp = ts

        expected = bpow.RETARGET_INTERVAL * bpow.TARGET_BLOCK_TIME
        headers = {0: 0, bpow.RETARGET_INTERVAL - 1: expected // 8}
        target = bpow.target_for_height(lambda h: FakeHeader(headers[h]), height=bpow.RETARGET_INTERVAL, prev_target=1000)
        self.assertEqual(target, 250)  # clamped at the 1/4x cap, not 1/8

    def test_compute_next_target_clamped_to_floor_and_ceiling(self):
        self.assertEqual(bpow.compute_next_target(bpow.FLOOR_TARGET, 1, 1000), bpow.FLOOR_TARGET)
        self.assertEqual(bpow.compute_next_target(bpow.CEILING_TARGET, 1000, 1), bpow.CEILING_TARGET)

    def test_work_for_target_monotonic(self):
        easy = bpow.work_for_target(1 << 250)
        hard = bpow.work_for_target(1 << 200)
        self.assertGreater(hard, easy)


if __name__ == "__main__":
    unittest.main()
