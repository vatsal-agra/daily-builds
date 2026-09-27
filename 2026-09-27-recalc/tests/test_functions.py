import unittest

from engine import values as V
from engine.sheet import Sheet


def set_and_get(cells):
    """cells: {"A1": "raw"} -> {"A1": display_string, ...} for every key."""
    from engine import refs
    sheet = Sheet()
    edits = {}
    for addr, raw in cells.items():
        ref = refs.parse_cell_ref(addr)
        edits[(ref.col, ref.row)] = raw
    sheet.set_cells(edits)
    out = {}
    for addr in cells:
        ref = refs.parse_cell_ref(addr)
        out[addr] = sheet.get_display(ref.col, ref.row)
    return out


class TestArithmeticErrors(unittest.TestCase):
    def test_div_zero(self):
        r = set_and_get({"A1": "5", "B1": "0", "C1": "=A1/B1"})
        self.assertEqual(r["C1"], "#DIV/0!")

    def test_value_error_on_bad_text(self):
        r = set_and_get({"A1": "abc", "B1": "=A1+1"})
        self.assertEqual(r["B1"], "#VALUE!")

    def test_name_error_unknown_function(self):
        r = set_and_get({"A1": "=NOPE(1)"})
        self.assertEqual(r["A1"], "#NAME?")

    def test_error_propagates_through_expression(self):
        r = set_and_get({"A1": "=1/0", "B1": "=A1+1", "C1": "=B1*2"})
        self.assertEqual(r["C1"], "#DIV/0!")


class TestAggregates(unittest.TestCase):
    def test_sum_ignores_text_in_range_but_not_direct_arg(self):
        r = set_and_get({
            "A1": "1", "A2": "hello", "A3": "3",
            "B1": "=SUM(A1:A3)",
            "B2": '=SUM("abc")',
        })
        self.assertEqual(r["B1"], "4")
        self.assertEqual(r["B2"], "#VALUE!")

    def test_average_empty_range_is_div0(self):
        r = set_and_get({"A1": "x", "B1": "=AVERAGE(A1:A1)"})
        self.assertEqual(r["B1"], "#DIV/0!")

    def test_min_max(self):
        r = set_and_get({
            "A1": "5", "A2": "1", "A3": "9",
            "B1": "=MIN(A1:A3)", "B2": "=MAX(A1:A3)",
        })
        self.assertEqual(r["B1"], "1")
        self.assertEqual(r["B2"], "9")

    def test_count_vs_counta(self):
        r = set_and_get({
            "A1": "1", "A2": "text", "A3": "", "A4": "TRUE",
            "B1": "=COUNT(A1:A4)", "B2": "=COUNTA(A1:A4)",
        })
        self.assertEqual(r["B1"], "1")
        self.assertEqual(r["B2"], "3")

    def test_countif_numeric_and_text(self):
        r = set_and_get({
            "A1": "5", "A2": "12", "A3": "7", "A4": "apple",
            "B1": "=COUNTIF(A1:A4,\">6\")",
            "B2": "=COUNTIF(A1:A4,\"apple\")",
        })
        self.assertEqual(r["B1"], "2")
        self.assertEqual(r["B2"], "1")

    def test_sumif(self):
        r = set_and_get({
            "A1": "east", "A2": "west", "A3": "east",
            "B1": "10", "B2": "20", "B3": "30",
            "C1": '=SUMIF(A1:A3,"east",B1:B3)',
        })
        self.assertEqual(r["C1"], "40")


class TestLogical(unittest.TestCase):
    def test_if_basic(self):
        r = set_and_get({"A1": "5", "B1": "=IF(A1>3,\"big\",\"small\")"})
        self.assertEqual(r["B1"], "big")

    def test_if_missing_else_is_blank(self):
        r = set_and_get({"A1": "1", "B1": "=IF(A1>3,\"big\")"})
        self.assertEqual(r["B1"], "")

    def test_if_does_not_evaluate_error_in_untaken_branch_result(self):
        # The untaken branch may itself compute an error; IF must still
        # return the taken branch's value, not propagate that error.
        r = set_and_get({"A1": "=IF(TRUE,1,1/0)"})
        self.assertEqual(r["A1"], "1")

    def test_and_or_not(self):
        r = set_and_get({
            "A1": "=AND(TRUE,TRUE,1)",
            "A2": "=OR(FALSE,FALSE,0)",
            "A3": "=NOT(FALSE)",
        })
        self.assertEqual(r["A1"], "TRUE")
        self.assertEqual(r["A2"], "FALSE")
        self.assertEqual(r["A3"], "TRUE")

    def test_iferror(self):
        r = set_and_get({
            "A1": "=IFERROR(1/0,\"n/a\")",
            "A2": "=IFERROR(1/1,\"n/a\")",
        })
        self.assertEqual(r["A1"], "n/a")
        self.assertEqual(r["A2"], "1")


class TestTextFunctions(unittest.TestCase):
    def test_len_upper_lower_trim(self):
        r = set_and_get({
            "A1": "  Hello World  ",
            "B1": "=LEN(A1)",
            "B2": "=UPPER(A1)",
            "B3": "=LOWER(A1)",
            "B4": "=TRIM(A1)",
        })
        self.assertEqual(r["B1"], "15")
        self.assertEqual(r["B2"], "  HELLO WORLD  ")
        self.assertEqual(r["B3"], "  hello world  ")
        self.assertEqual(r["B4"], "Hello World")

    def test_concatenate_rejects_range(self):
        r = set_and_get({
            "A1": "a", "A2": "b",
            "B1": "=CONCATENATE(A1:A2)",
            "B2": '=CONCATENATE(A1,"-",A2)',
        })
        self.assertEqual(r["B1"], "#VALUE!")
        self.assertEqual(r["B2"], "a-b")


class TestMathFunctions(unittest.TestCase):
    def test_round_half_away_from_zero(self):
        r = set_and_get({
            "A1": "=ROUND(2.5,0)",
            "A2": "=ROUND(-2.5,0)",
            "A3": "=ROUND(3.14159,2)",
        })
        self.assertEqual(r["A1"], "3")
        self.assertEqual(r["A2"], "-3")
        self.assertEqual(r["A3"], "3.14")

    def test_abs_sqrt_negative(self):
        r = set_and_get({"A1": "=ABS(-5)", "A2": "=SQRT(-1)", "A3": "=SQRT(16)"})
        self.assertEqual(r["A1"], "5")
        self.assertEqual(r["A2"], "#NUM!")
        self.assertEqual(r["A3"], "4")

    def test_mod(self):
        r = set_and_get({"A1": "=MOD(7,3)", "A2": "=MOD(-7,3)", "A3": "=MOD(7,0)"})
        self.assertEqual(r["A1"], "1")
        self.assertEqual(r["A2"], "2")  # Excel MOD follows the divisor's sign
        self.assertEqual(r["A3"], "#DIV/0!")

    def test_int_floors_toward_negative_infinity(self):
        r = set_and_get({"A1": "=INT(2.9)", "A2": "=INT(-2.1)"})
        self.assertEqual(r["A1"], "2")
        self.assertEqual(r["A2"], "-3")


class TestVlookup(unittest.TestCase):
    def setUp(self):
        self.base = {
            "A1": "1", "B1": "one",
            "A2": "2", "B2": "two",
            "A3": "3", "B3": "three",
        }

    def test_exact_match(self):
        r = set_and_get(dict(self.base, C1="=VLOOKUP(2,A1:B3,2,FALSE)"))
        self.assertEqual(r["C1"], "two")

    def test_exact_no_match_is_na(self):
        r = set_and_get(dict(self.base, C1="=VLOOKUP(9,A1:B3,2,FALSE)"))
        self.assertEqual(r["C1"], "#N/A")

    def test_col_index_out_of_range_is_ref(self):
        r = set_and_get(dict(self.base, C1="=VLOOKUP(2,A1:B3,5,FALSE)"))
        self.assertEqual(r["C1"], "#REF!")

    def test_approximate_match_default(self):
        r = set_and_get(dict(self.base, C1="=VLOOKUP(2.5,A1:B3,2)"))
        self.assertEqual(r["C1"], "two")  # largest value <= 2.5


if __name__ == "__main__":
    unittest.main()
