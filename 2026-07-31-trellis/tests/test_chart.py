import unittest

from trellis import Workbook
from trellis.chart import render_chart_svg


class TestChart(unittest.TestCase):
    def setUp(self):
        self.wb = Workbook()
        for i, (label, v) in enumerate([("a", 3), ("b", 7), ("c", 2)], start=1):
            self.wb.set_cell("Sheet1", i, 1, label)
            self.wb.set_cell("Sheet1", i, 2, str(v))

    def test_bar_chart_has_bars_and_labels(self):
        svg = render_chart_svg(self.wb, "Sheet1", "A1:B3", "bar")
        self.assertTrue(svg.startswith("<svg"))
        self.assertGreaterEqual(svg.count("<rect"), 3)
        self.assertIn(">a<", svg)
        self.assertIn(">b<", svg)
        self.assertIn(">c<", svg)

    def test_line_chart_has_polyline(self):
        svg = render_chart_svg(self.wb, "Sheet1", "A1:B3", "line")
        self.assertIn("<polyline", svg)

    def test_single_column_range_uses_row_index_labels(self):
        svg = render_chart_svg(self.wb, "Sheet1", "B1:B3", "bar")
        self.assertIn(">1<", svg)

    def test_bad_range_syntax_raises_value_error(self):
        with self.assertRaises(ValueError):
            render_chart_svg(self.wb, "Sheet1", "not-a-range", "bar")

    def test_missing_sheet_raises_value_error(self):
        with self.assertRaises(ValueError):
            render_chart_svg(self.wb, "NoSuchSheet", "A1:B3", "bar")

    def test_error_cells_treated_as_zero_not_crash(self):
        self.wb.set_cell("Sheet1", 1, 2, "=1/0")
        svg = render_chart_svg(self.wb, "Sheet1", "A1:B3", "bar")
        self.assertTrue(svg.startswith("<svg"))

    def test_svg_uses_explicit_colors_not_currentcolor(self):
        # Regression: the chart is always embedded via <img src=...>, an
        # isolated rendering context that can't inherit currentColor / CSS
        # vars from the host page -- see REVIEW.md finding #7.
        svg = render_chart_svg(self.wb, "Sheet1", "A1:B3", "bar")
        self.assertNotIn("currentColor", svg)
        self.assertNotIn("var(--", svg)


if __name__ == "__main__":
    unittest.main()
