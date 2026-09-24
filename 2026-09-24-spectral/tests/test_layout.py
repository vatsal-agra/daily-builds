import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spectral.layout import compute_layout, iter_mcu_blocks


class TestLayout(unittest.TestCase):
    def test_444_no_subsampling_one_block_per_component_per_mcu(self):
        layout = compute_layout(16, 16, "444")
        for c in layout["components"]:
            self.assertEqual((c["h"], c["v"]), (1, 1))
        self.assertEqual(layout["mcus_x"], 2)
        self.assertEqual(layout["mcus_y"], 2)

    def test_420_luma_has_four_blocks_per_mcu(self):
        layout = compute_layout(16, 16, "420")
        y = next(c for c in layout["components"] if c["name"] == "Y")
        self.assertEqual((y["h"], y["v"]), (2, 2))
        cb = next(c for c in layout["components"] if c["name"] == "Cb")
        self.assertEqual((cb["h"], cb["v"]), (1, 1))

    def test_non_aligned_dimensions_round_up_mcus(self):
        layout = compute_layout(17, 9, "420")  # MCU is 16x16 for 4:2:0
        self.assertEqual(layout["mcus_x"], 2)
        self.assertEqual(layout["mcus_y"], 1)

    def test_unknown_subsampling_raises(self):
        with self.assertRaises(ValueError):
            compute_layout(16, 16, "999")

    def test_mcu_block_count_matches_expected_for_420(self):
        layout = compute_layout(16, 16, "420")
        blocks = list(iter_mcu_blocks(layout))
        # one MCU: 4 Y blocks + 1 Cb + 1 Cr = 6
        self.assertEqual(len(blocks), 6)
        names = [b[0] for b in blocks]
        self.assertEqual(names.count("Y"), 4)
        self.assertEqual(names.count("Cb"), 1)
        self.assertEqual(names.count("Cr"), 1)

    def test_mcu_scan_order_is_component_grouped_within_each_mcu(self):
        layout = compute_layout(32, 16, "420")  # 2x1 MCUs
        blocks = list(iter_mcu_blocks(layout))
        # 2 MCUs * 6 blocks = 12
        self.assertEqual(len(blocks), 12)
        first_mcu = blocks[:6]
        self.assertEqual([b[0] for b in first_mcu], ["Y", "Y", "Y", "Y", "Cb", "Cr"])


if __name__ == "__main__":
    unittest.main()
