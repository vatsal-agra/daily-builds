import random
import unittest

from skein.rga import RGA


class TestBasicEditing(unittest.TestCase):
    def test_insert_and_text(self):
        r = RGA("a")
        r.local_insert(0, "h")
        r.local_insert(1, "i")
        self.assertEqual(r.text, "hi")

    def test_insert_in_middle(self):
        r = RGA("a")
        for i, ch in enumerate("ac"):
            r.local_insert(i, ch)
        r.local_insert(1, "b")
        self.assertEqual(r.text, "abc")

    def test_delete(self):
        r = RGA("a")
        for i, ch in enumerate("hello"):
            r.local_insert(i, ch)
        r.local_delete(1)  # remove 'e'
        self.assertEqual(r.text, "hllo")

    def test_len_matches_visible_text(self):
        r = RGA("a")
        for i, ch in enumerate("abcde"):
            r.local_insert(i, ch)
        r.local_delete(0)
        self.assertEqual(len(r), len(r.text))
        self.assertEqual(len(r), 4)

    def test_insert_bounds_checked(self):
        r = RGA("a")
        r.local_insert(0, "x")
        with self.assertRaises(IndexError):
            r.local_insert(5, "y")
        with self.assertRaises(IndexError):
            r.local_insert(-1, "y")

    def test_delete_bounds_checked(self):
        r = RGA("a")
        with self.assertRaises(IndexError):
            r.local_delete(0)  # empty doc
        r.local_insert(0, "x")
        with self.assertRaises(IndexError):
            r.local_delete(1)

    def test_multi_char_insert_rejected_before_minting_id(self):
        r = RGA("a")
        counter_before = r.clock._counter
        with self.assertRaises(ValueError):
            r.local_insert(0, "ab")
        self.assertEqual(r.clock._counter, counter_before, "a rejected insert must not consume a clock tick")


class TestIdempotence(unittest.TestCase):
    def test_duplicate_insert_is_noop(self):
        r = RGA("a")
        op = r.local_insert(0, "x")
        r.apply(op)  # re-apply the exact same op (simulating network duplication)
        r.apply(op)
        self.assertEqual(r.text, "x")
        self.assertEqual(r.node_count(), 1)

    def test_duplicate_delete_is_noop(self):
        r = RGA("a")
        r.local_insert(0, "x")
        op = r.local_delete(0)
        r.apply(op)
        r.apply(op)
        self.assertEqual(r.text, "")


class TestCausalBuffering(unittest.TestCase):
    def test_out_of_order_insert_buffers_then_resolves(self):
        src = RGA("src")
        ops = [src.local_insert(i, c) for i, c in enumerate("abc")]
        dst = RGA("dst")
        dst.apply(ops[2])  # 'c', depends on 'b' — must buffer
        self.assertTrue(dst.has_pending())
        self.assertEqual(dst.text, "")
        dst.apply(ops[0])  # 'a', no dependency — applies
        self.assertEqual(dst.text, "a")
        dst.apply(ops[1])  # 'b' arrives — unblocks 'c' too
        self.assertFalse(dst.has_pending())
        self.assertEqual(dst.text, "abc")

    def test_delete_before_its_insert_buffers(self):
        src = RGA("src")
        ins = src.local_insert(0, "x")
        deL = src.local_delete(0)
        dst = RGA("dst")
        dst.apply(deL)
        self.assertTrue(dst.has_pending())
        dst.apply(ins)
        self.assertFalse(dst.has_pending())
        self.assertEqual(dst.text, "")

    def test_long_reversed_delivery_does_not_recurse(self):
        """Regression test for REVIEW.md bug #1: a straight-typed
        document delivered in exactly reversed order used to blow
        Python's recursion limit via a recursive pending-replay
        cascade."""
        src = RGA("src")
        n = 4000
        ops = [src.local_insert(i, "x") for i in range(n)]
        dst = RGA("dst")
        for op in reversed(ops):
            dst.apply(op)  # must not raise RecursionError
        self.assertFalse(dst.has_pending())
        self.assertEqual(dst.text, src.text)
        self.assertEqual(len(dst.text), n)

    def test_shuffled_delivery_converges(self):
        src = RGA("src")
        ops = [src.local_insert(i, c) for i, c in enumerate("the quick brown fox")]
        rng = random.Random(3)
        shuffled = list(ops)
        rng.shuffle(shuffled)
        dst = RGA("dst")
        for op in shuffled:
            dst.apply(op)
        self.assertFalse(dst.has_pending())
        self.assertEqual(dst.text, src.text)


class TestTombstonesAndConcurrency(unittest.TestCase):
    def test_insert_after_a_deleted_character_still_shows_up(self):
        # A delete must never hide text that was concurrently inserted
        # after the deleted character — tombstones hide themselves,
        # never their children.
        src = RGA("src")
        a_op = src.local_insert(0, "a")
        b_op = src.local_insert(1, "b")
        c_op = src.local_insert(2, "c")

        site_x = RGA("x")
        site_y = RGA("y")
        for op in (a_op, b_op, c_op):
            site_x.apply(op)
            site_y.apply(op)
        self.assertEqual(site_x.text, "abc")

        del_b = site_x.local_delete(1)  # x deletes 'b'
        ins_after_b = site_y.insert_after(b_op.id, "X")  # y inserts 'X' after 'b', concurrently

        site_x.apply(ins_after_b)
        site_y.apply(del_b)

        self.assertEqual(site_x.text, "aXc")
        self.assertEqual(site_y.text, "aXc")

    def test_concurrent_insert_same_origin_is_deterministic(self):
        src = RGA("src")
        a_op = src.local_insert(0, "a")

        site_x = RGA("x")
        site_y = RGA("y")
        site_x.apply(a_op)
        site_y.apply(a_op)

        # both sites concurrently insert after 'a'
        op_x = site_x.insert_after(a_op.id, "1")
        op_y = site_y.insert_after(a_op.id, "2")

        # deliver in opposite orders to each site
        site_x.apply(op_y)
        site_y.apply(op_x)

        self.assertEqual(site_x.text, site_y.text)
        self.assertEqual(len(site_x.text), 3)

    def test_char_and_origin_survives_tombstoning(self):
        r = RGA("a")
        op = r.local_insert(0, "z")
        r.local_delete(0)
        char, origin = r.char_and_origin(op.id)
        self.assertEqual(char, "z")
        self.assertIsNone(origin)


class TestApplyValidation(unittest.TestCase):
    def test_apply_rejects_unknown_type(self):
        r = RGA("a")
        with self.assertRaises(TypeError):
            r.apply("not an op")


if __name__ == "__main__":
    unittest.main()
