import random
import unittest

from meridian import nodeid


class TestDistance(unittest.TestCase):
    def test_zero_distance_to_self(self):
        self.assertEqual(nodeid.distance(123, 123), 0)

    def test_symmetric(self):
        r = random.Random(1)
        for _ in range(200):
            a, b = r.getrandbits(160), r.getrandbits(160)
            self.assertEqual(nodeid.distance(a, b), nodeid.distance(b, a))

    def test_triangle_inequality(self):
        r = random.Random(2)
        for _ in range(500):
            a, b, c = (r.getrandbits(160) for _ in range(3))
            self.assertLessEqual(nodeid.distance(a, c), nodeid.distance(a, b) + nodeid.distance(b, c))

    def test_distance_within_range(self):
        r = random.Random(3)
        for _ in range(200):
            a, b = r.getrandbits(160), r.getrandbits(160)
            d = nodeid.distance(a, b)
            self.assertGreaterEqual(d, 0)
            self.assertLessEqual(d, nodeid.MAX_ID)


class TestBucketIndex(unittest.TestCase):
    def test_self_is_none(self):
        self.assertIsNone(nodeid.bucket_index(42, 42))

    def test_adjacent_ids_land_in_bucket_zero(self):
        self.assertEqual(nodeid.bucket_index(0, 1), 0)
        self.assertEqual(nodeid.bucket_index(6, 7), 0)

    def test_known_values(self):
        # distance 2 (0b10) -> bit_length 2 -> bucket 1
        self.assertEqual(nodeid.bucket_index(0, 2), 1)
        # distance 2**159 -> bucket 159 (farthest possible bucket)
        self.assertEqual(nodeid.bucket_index(0, 1 << 159), 159)

    def test_range_is_valid(self):
        r = random.Random(4)
        for _ in range(500):
            a, b = r.getrandbits(160), r.getrandbits(160)
            if a == b:
                continue
            idx = nodeid.bucket_index(a, b)
            self.assertGreaterEqual(idx, 0)
            self.assertLess(idx, 160)


class TestRandomIdInBucket(unittest.TestCase):
    def test_lands_in_requested_bucket(self):
        r = random.Random(5)
        for _ in range(300):
            self_id = r.getrandbits(160)
            idx = r.randrange(160)
            target = nodeid.random_id_in_bucket(self_id, idx, r)
            self.assertEqual(nodeid.bucket_index(self_id, target), idx)

    def test_bucket_zero_is_deterministic_neighbor(self):
        r = random.Random(6)
        self_id = 0b1010
        target = nodeid.random_id_in_bucket(self_id, 0, r)
        self.assertEqual(target, self_id ^ 1)

    def test_rejects_out_of_range_index(self):
        r = random.Random(7)
        with self.assertRaises(ValueError):
            nodeid.random_id_in_bucket(0, 160, r)
        with self.assertRaises(ValueError):
            nodeid.random_id_in_bucket(0, -1, r)


class TestHashing(unittest.TestCase):
    def test_sha1_int_is_deterministic(self):
        self.assertEqual(nodeid.sha1_int(b"hello"), nodeid.sha1_int(b"hello"))

    def test_sha1_int_is_160_bits(self):
        h = nodeid.sha1_int(b"meridian")
        self.assertGreaterEqual(h, 0)
        self.assertLessEqual(h, nodeid.MAX_ID)

    def test_sha1_int_differs_for_different_input(self):
        self.assertNotEqual(nodeid.sha1_int(b"a"), nodeid.sha1_int(b"b"))

    def test_random_id_reproducible_under_seed(self):
        a = nodeid.random_id(random.Random(99))
        b = nodeid.random_id(random.Random(99))
        self.assertEqual(a, b)

    def test_to_hex_round_trips(self):
        h = nodeid.to_hex(255)
        self.assertEqual(len(h), 40)
        self.assertEqual(int(h, 16), 255)


if __name__ == "__main__":
    unittest.main()
