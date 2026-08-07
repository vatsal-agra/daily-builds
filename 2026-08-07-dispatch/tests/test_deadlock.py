import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import deadlock
from core.deadlock import DeadlockError


# The classic Silberschatz/Galvin/Gagne Banker's Algorithm example.
AVAILABLE = [3, 3, 2]
MAX_MATRIX = [[7, 5, 3], [3, 2, 2], [9, 0, 2], [2, 2, 2], [4, 3, 3]]
ALLOCATION = [[0, 1, 0], [2, 0, 0], [3, 0, 2], [2, 1, 1], [0, 0, 2]]


class BankersSafetyTest(unittest.TestCase):
    def test_classic_example_is_safe(self):
        safe, sequence = deadlock.bankers_safety(AVAILABLE, MAX_MATRIX, ALLOCATION)
        self.assertTrue(safe)
        self.assertIsNotNone(sequence)
        self.assertEqual(sorted(sequence), list(range(5)))  # every process appears exactly once

    def test_safe_sequence_is_independently_verified_by_brute_force(self):
        exists = deadlock.brute_force_safe_sequence_exists(AVAILABLE, MAX_MATRIX, ALLOCATION)
        self.assertTrue(exists)

    def test_returned_sequence_actually_satisfies_the_definition(self):
        # re-derive: replaying the returned sequence must never require more than `available`
        safe, sequence = deadlock.bankers_safety(AVAILABLE, MAX_MATRIX, ALLOCATION)
        need = [[mx - al for mx, al in zip(mrow, arow)] for mrow, arow in zip(MAX_MATRIX, ALLOCATION)]
        work = list(AVAILABLE)
        for i in sequence:
            for r in range(len(work)):
                self.assertLessEqual(need[i][r], work[r])
            for r in range(len(work)):
                work[r] += ALLOCATION[i][r]

    def test_unsafe_state_detected(self):
        # drain available to nothing -- no process's need can be satisfied
        unsafe_available = [0, 0, 0]
        safe, sequence = deadlock.bankers_safety(unsafe_available, MAX_MATRIX, ALLOCATION)
        self.assertFalse(safe)
        self.assertIsNone(sequence)
        self.assertFalse(deadlock.brute_force_safe_sequence_exists(unsafe_available, MAX_MATRIX, ALLOCATION))

    def test_dimension_mismatch_rejected(self):
        with self.assertRaises(DeadlockError):
            deadlock.bankers_safety([3, 3], MAX_MATRIX, ALLOCATION)

    def test_allocation_exceeding_max_rejected(self):
        with self.assertRaises(DeadlockError):
            deadlock.bankers_safety([3, 3, 2], [[1, 1, 1]], [[2, 2, 2]])


class BankersRequestTest(unittest.TestCase):
    def test_p1_request_1_0_2_is_granted(self):
        granted, _reason = deadlock.bankers_request(AVAILABLE, MAX_MATRIX, ALLOCATION, 1, [1, 0, 2])
        self.assertTrue(granted)

    def test_p4_request_3_3_0_denied_leaves_unsafe_state(self):
        # within P4's need and within available, but granting it strands every
        # other process below its need -- must be denied on safety grounds, not availability
        granted, reason = deadlock.bankers_request(AVAILABLE, MAX_MATRIX, ALLOCATION, 4, [3, 3, 0])
        self.assertFalse(granted)
        self.assertIn("unsafe", reason)

    def test_request_exceeding_declared_need_denied(self):
        # P0's need is [7,4,3]; requesting [8,0,0] exceeds its own declared maximum claim
        granted, reason = deadlock.bankers_request(AVAILABLE, MAX_MATRIX, ALLOCATION, 0, [8, 0, 0])
        self.assertFalse(granted)
        self.assertIn("maximum", reason)

    def test_request_does_not_mutate_inputs(self):
        available_copy = list(AVAILABLE)
        allocation_copy = [list(row) for row in ALLOCATION]
        deadlock.bankers_request(AVAILABLE, MAX_MATRIX, ALLOCATION, 1, [1, 0, 2])
        self.assertEqual(AVAILABLE, available_copy)
        self.assertEqual(ALLOCATION, allocation_copy)

    def test_invalid_process_index_rejected(self):
        with self.assertRaises(DeadlockError):
            deadlock.bankers_request(AVAILABLE, MAX_MATRIX, ALLOCATION, 99, [1, 0, 0])


class RagCycleDetectionTest(unittest.TestCase):
    def test_two_process_circular_wait_is_a_deadlock(self):
        cycle = deadlock.detect_cycle([("R0", "P0"), ("R1", "P1")], [("P0", "R1"), ("P1", "R0")])
        self.assertIsNotNone(cycle)
        self.assertEqual(cycle[0], cycle[-1], "a cycle must start and end at the same node")

    def test_three_process_circular_wait_is_a_deadlock(self):
        cycle = deadlock.detect_cycle(
            [("R0", "P0"), ("R1", "P1"), ("R2", "P2")],
            [("P0", "R1"), ("P1", "R2"), ("P2", "R0")],
        )
        self.assertIsNotNone(cycle)

    def test_no_cycle_no_deadlock(self):
        cycle = deadlock.detect_cycle([("R0", "P0")], [("P0", "R1")])
        self.assertIsNone(cycle)

    def test_empty_graph_no_deadlock(self):
        self.assertIsNone(deadlock.detect_cycle([], []))
        self.assertIsNone(deadlock.detect_cycle(None, None))

    def test_shared_resource_no_deadlock_when_not_circular(self):
        # P0 holds R0, wants R1 (free); P1 holds R1, wants nothing -- no cycle
        cycle = deadlock.detect_cycle([("R0", "P0"), ("R1", "P1")], [("P0", "R1")])
        self.assertIsNone(cycle)


if __name__ == "__main__":
    unittest.main()
