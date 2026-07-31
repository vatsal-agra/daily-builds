import unittest

from trellis import Workbook
from trellis.errors import TrellisError


def val(wb, addr, sheet="Sheet1"):
    from trellis.addr import parse_addr
    row, col = parse_addr(addr)
    cell = wb.get_cell(sheet, row, col)
    if cell is None:
        return None
    v = cell.value
    return v.code if isinstance(v, TrellisError) else v


def put(wb, addr, raw, sheet="Sheet1"):
    from trellis.addr import parse_addr
    row, col = parse_addr(addr)
    wb.set_cell(sheet, row, col, raw)


class TestArithmetic(unittest.TestCase):
    def setUp(self):
        self.wb = Workbook()

    def test_basic_ops(self):
        cases = {
            "=1+2": 3, "=5-2": 3, "=3*4": 12, "=10/4": 2.5,
            "=2^10": 1024, "=-5": -5, "=+5": 5,
        }
        for i, (formula, expected) in enumerate(cases.items(), start=1):
            put(self.wb, f"A{i}", formula)
            self.assertEqual(val(self.wb, f"A{i}"), expected, formula)

    def test_div_by_zero(self):
        put(self.wb, "A1", "=1/0")
        self.assertEqual(val(self.wb, "A1"), "#DIV/0!")

    def test_string_concat(self):
        put(self.wb, "A1", '="foo"&"bar"')
        self.assertEqual(val(self.wb, "A1"), "foobar")

    def test_concat_with_number(self):
        put(self.wb, "A1", '="x="&5')
        self.assertEqual(val(self.wb, "A1"), "x=5")

    def test_comparisons(self):
        cases = {"=1=1": True, "=1<>2": True, "=1<2": True, "=2<=2": True, "=3>2": True, "=2>=3": False}
        for i, (f, exp) in enumerate(cases.items(), start=1):
            put(self.wb, f"A{i}", f)
            self.assertEqual(val(self.wb, f"A{i}"), exp, f)

    def test_string_comparison_case_insensitive(self):
        put(self.wb, "A1", '="abc"="ABC"')
        self.assertTrue(val(self.wb, "A1"))

    def test_percent(self):
        put(self.wb, "A1", "=50%")
        self.assertEqual(val(self.wb, "A1"), 0.5)

    def test_blank_cell_is_zero(self):
        put(self.wb, "A1", "=Z99+1")
        self.assertEqual(val(self.wb, "A1"), 1)

    def test_bool_coerces_in_arithmetic(self):
        put(self.wb, "A1", "=TRUE+1")
        self.assertEqual(val(self.wb, "A1"), 2)
        put(self.wb, "A2", "=FALSE+1")
        self.assertEqual(val(self.wb, "A2"), 1)

    def test_power_math_convention(self):
        put(self.wb, "A1", "=-2^2")
        self.assertEqual(val(self.wb, "A1"), -4)

    def test_sqrt_negative_errors(self):
        put(self.wb, "A1", "=SQRT(-1)")
        self.assertEqual(val(self.wb, "A1"), "#NUM!")

    def test_float_display_rounds_precision_noise(self):
        put(self.wb, "A1", "=0.1+0.2")
        raw = self.wb.get_cell("Sheet1", 1, 1).value
        self.assertAlmostEqual(raw, 0.3)  # underlying value: full precision
        from trellis.functions import to_display_str
        self.assertEqual(to_display_str(raw), "0.3")  # display: rounded


class TestFunctions(unittest.TestCase):
    def setUp(self):
        self.wb = Workbook()
        put(self.wb, "A1", "1")
        put(self.wb, "A2", "2")
        put(self.wb, "A3", "3")
        put(self.wb, "A4", "hello")

    def test_sum(self):
        put(self.wb, "B1", "=SUM(A1:A4)")
        self.assertEqual(val(self.wb, "B1"), 6)  # text cell A4 ignored

    def test_average(self):
        put(self.wb, "B1", "=AVERAGE(A1:A3)")
        self.assertEqual(val(self.wb, "B1"), 2)

    def test_average_no_numbers_is_div0(self):
        put(self.wb, "B1", "=AVERAGE(A4)")
        self.assertEqual(val(self.wb, "B1"), "#DIV/0!")

    def test_count_counta(self):
        put(self.wb, "B1", "=COUNT(A1:A4)")
        put(self.wb, "B2", "=COUNTA(A1:A4)")
        self.assertEqual(val(self.wb, "B1"), 3)
        self.assertEqual(val(self.wb, "B2"), 4)

    def test_min_max(self):
        put(self.wb, "B1", "=MIN(A1:A3)")
        put(self.wb, "B2", "=MAX(A1:A3)")
        self.assertEqual(val(self.wb, "B1"), 1)
        self.assertEqual(val(self.wb, "B2"), 3)

    def test_if(self):
        put(self.wb, "B1", '=IF(A1<A2,"yes","no")')
        self.assertEqual(val(self.wb, "B1"), "yes")

    def test_if_two_arg_defaults_false(self):
        put(self.wb, "B1", "=IF(FALSE,1)")
        self.assertEqual(val(self.wb, "B1"), False)

    def test_if_short_circuits(self):
        # The untaken branch's DIV/0 must never be evaluated.
        put(self.wb, "B1", "=IF(TRUE,1,1/0)")
        self.assertEqual(val(self.wb, "B1"), 1)
        put(self.wb, "B2", "=IF(FALSE,1/0,2)")
        self.assertEqual(val(self.wb, "B2"), 2)

    def test_iferror_catches(self):
        put(self.wb, "B1", '=IFERROR(1/0,"caught")')
        self.assertEqual(val(self.wb, "B1"), "caught")

    def test_iferror_passthrough(self):
        put(self.wb, "B1", '=IFERROR(1+1,"caught")')
        self.assertEqual(val(self.wb, "B1"), 2)

    def test_and_or_not(self):
        put(self.wb, "B1", "=AND(TRUE,TRUE,1)")
        put(self.wb, "B2", "=OR(FALSE,FALSE,0)")
        put(self.wb, "B3", "=NOT(TRUE)")
        self.assertTrue(val(self.wb, "B1"))
        self.assertFalse(val(self.wb, "B2"))
        self.assertFalse(val(self.wb, "B3"))

    def test_round_abs_mod_power(self):
        put(self.wb, "B1", "=ROUND(3.14159,2)")
        put(self.wb, "B2", "=ABS(-5)")
        put(self.wb, "B3", "=MOD(10,3)")
        put(self.wb, "B4", "=POWER(2,10)")
        self.assertEqual(val(self.wb, "B1"), 3.14)
        self.assertEqual(val(self.wb, "B2"), 5)
        self.assertEqual(val(self.wb, "B3"), 1)
        self.assertEqual(val(self.wb, "B4"), 1024)

    def test_mod_by_zero(self):
        put(self.wb, "B1", "=MOD(5,0)")
        self.assertEqual(val(self.wb, "B1"), "#DIV/0!")

    def test_text_functions(self):
        put(self.wb, "B1", "=UPPER(A4)")
        put(self.wb, "B2", "=LOWER(\"HI\")")
        put(self.wb, "B3", "=LEN(A4)")
        put(self.wb, "B4", '=TRIM("  a  b  ")')
        put(self.wb, "B5", '=CONCAT("a","b",1)')
        self.assertEqual(val(self.wb, "B1"), "HELLO")
        self.assertEqual(val(self.wb, "B2"), "hi")
        self.assertEqual(val(self.wb, "B3"), 5)
        self.assertEqual(val(self.wb, "B4"), "a b")
        self.assertEqual(val(self.wb, "B5"), "ab1")

    def test_vlookup_exact(self):
        put(self.wb, "D1", "a"); put(self.wb, "E1", "1")
        put(self.wb, "D2", "b"); put(self.wb, "E2", "2")
        put(self.wb, "B1", '=VLOOKUP("b",D1:E2,2)')
        self.assertEqual(val(self.wb, "B1"), 2)

    def test_vlookup_not_found(self):
        put(self.wb, "D1", "a"); put(self.wb, "E1", "1")
        put(self.wb, "B1", '=VLOOKUP("z",D1:E1,2)')
        self.assertEqual(val(self.wb, "B1"), "#N/A")

    def test_vlookup_approximate(self):
        for i, (score, grade) in enumerate([(0, "F"), (60, "D"), (70, "C"), (80, "B"), (90, "A")], start=1):
            put(self.wb, f"D{i}", str(score))
            put(self.wb, f"E{i}", grade)
        put(self.wb, "B1", "=VLOOKUP(85,D1:E5,2,TRUE)")
        self.assertEqual(val(self.wb, "B1"), "B")

    def test_unknown_function_is_name_error(self):
        put(self.wb, "B1", "=BOGUS(1)")
        self.assertEqual(val(self.wb, "B1"), "#NAME?")

    def test_range_argument_to_scalar_function_errors_cleanly(self):
        put(self.wb, "B1", "=ROUND(A1:A3,2)")
        self.assertEqual(val(self.wb, "B1"), "#VALUE!")

    def test_error_propagates_through_comparison(self):
        put(self.wb, "C1", "=1/0")
        put(self.wb, "C2", "=C1=5")
        self.assertEqual(val(self.wb, "C2"), "#DIV/0!")

    def test_error_propagates_through_sum(self):
        put(self.wb, "C1", "=1/0")
        put(self.wb, "C2", "=SUM(C1,1)")
        self.assertEqual(val(self.wb, "C2"), "#DIV/0!")


if __name__ == "__main__":
    unittest.main()
