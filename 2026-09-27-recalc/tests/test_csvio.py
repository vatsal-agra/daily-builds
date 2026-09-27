import unittest

from engine import csvio
from engine import refs
from engine.sheet import Sheet


def A(addr):
    r = refs.parse_cell_ref(addr)
    return (r.col, r.row)


class TestCsvIo(unittest.TestCase):
    def test_import_literals_and_formulas(self):
        s = Sheet()
        text = "1,2,=A1+B1\n3,4,=A2+B2\n"
        csvio.import_csv(s, text)
        self.assertEqual(s.get_display(*A("C1")), "3")
        self.assertEqual(s.get_display(*A("C2")), "7")

    def test_export_matches_computed_values(self):
        s = Sheet()
        s.set_cell(*A("A1"), "1")
        s.set_cell(*A("B1"), "hello")
        s.set_cell(*A("C1"), "=A1&B1")
        out = csvio.export_csv(s)
        self.assertEqual(out, "1,hello,1hello\n")

    def test_import_at_offset(self):
        s = Sheet()
        csvio.import_csv(s, "9,8\n", origin=(3, 5))
        self.assertEqual(s.get_display(*A("C5")), "9")
        self.assertEqual(s.get_display(*A("D5")), "8")

    def test_round_trip_save_load(self):
        s = Sheet()
        s.set_cell(*A("A1"), "5")
        s.set_cell(*A("B1"), "=A1*2")
        snapshot = csvio.save_workbook(s)

        s2 = Sheet()
        csvio.load_workbook(s2, snapshot)
        self.assertEqual(s2.get_display(*A("A1")), "5")
        self.assertEqual(s2.get_display(*A("B1")), "10")
        self.assertEqual(s2.get_raw(*A("B1")), "=A1*2")


if __name__ == "__main__":
    unittest.main()
