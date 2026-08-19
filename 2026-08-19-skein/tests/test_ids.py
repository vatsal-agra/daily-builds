import unittest

from skein.ids import CharId, LamportClock


class TestCharId(unittest.TestCase):
    def test_total_order_by_counter_then_site(self):
        self.assertLess(CharId(1, "a"), CharId(2, "a"))
        self.assertLess(CharId(1, "a"), CharId(1, "b"))
        self.assertLess(CharId(2, "a"), CharId(2, "z"))  # counter ties broken by site (lexicographic)
        self.assertEqual(CharId(1, "a"), CharId(1, "a"))

    def test_hashable_and_frozen(self):
        cid = CharId(1, "a")
        d = {cid: "x"}
        self.assertEqual(d[CharId(1, "a")], "x")
        with self.assertRaises(Exception):
            cid.counter = 2  # frozen dataclass


class TestLamportClock(unittest.TestCase):
    def test_tick_monotonic_and_unique(self):
        clock = LamportClock("site-a")
        ids = [clock.tick() for _ in range(5)]
        self.assertEqual([c.counter for c in ids], [1, 2, 3, 4, 5])
        self.assertTrue(all(c.site == "site-a" for c in ids))

    def test_observe_advances_past_remote_counter(self):
        clock = LamportClock("site-a")
        clock.tick()  # counter = 1
        clock.observe(10)
        nxt = clock.tick()
        self.assertEqual(nxt.counter, 11)

    def test_observe_never_moves_backward(self):
        clock = LamportClock("site-a")
        for _ in range(5):
            clock.tick()  # counter = 5
        clock.observe(2)  # smaller than current — must not regress
        nxt = clock.tick()
        self.assertEqual(nxt.counter, 6)


if __name__ == "__main__":
    unittest.main()
