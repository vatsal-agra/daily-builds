import unittest

from engine.workbook import Workbook, a1_to_ref


class TestFunctions(unittest.TestCase):
    def setUp(self):
        self.wb = Workbook()
        self.wb.add_sheet("S")

    def setc(self, a1, text):
        r, c = a1_to_ref(a1)
        self.wb.edit([("S", r, c, text)])

    def getc(self, a1):
        r, c = a1_to_ref(a1)
        return self.wb.sheets["S"].get_computed(r, c)

    def formula(self, expr):
        self.setc("Z1", "=" + expr)
        return self.getc("Z1")

    def test_sum_average_count_ignore_text_in_ranges(self):
        self.setc("A1", "1")
        self.setc("A2", "hello")
        self.setc("A3", "3")
        self.assertEqual(self.formula("SUM(A1:A3)"), 4.0)
        self.assertEqual(self.formula("AVERAGE(A1:A3)"), 2.0)
        self.assertEqual(self.formula("COUNT(A1:A3)"), 2.0)
        self.assertEqual(self.formula("COUNTA(A1:A3)"), 3.0)

    def test_min_max(self):
        self.setc("A1", "3")
        self.setc("A2", "-5")
        self.setc("A3", "10")
        self.assertEqual(self.formula("MIN(A1:A3)"), -5.0)
        self.assertEqual(self.formula("MAX(A1:A3)"), 10.0)

    def test_if_lazy_avoids_evaluating_untaken_branch_error(self):
        self.setc("A1", "0")
        # 1/A1 would be #DIV/0! if evaluated -- IF must not evaluate it since A1<>0 branch untaken
        self.setc("A2", "5")
        self.assertEqual(self.formula("IF(A2<>0, 1, 1/A1)"), 1)

    def test_iferror_catches_div0(self):
        self.setc("A1", "0")
        self.assertEqual(self.formula("IFERROR(1/A1, -1)"), -1)

    def test_division_by_zero(self):
        self.assertEqual(str(self.formula("5/0")), "#DIV/0!")

    def test_unknown_function_name_error(self):
        self.assertEqual(str(self.formula("NOPE(1)")), "#NAME?")

    def test_text_plus_number_is_value_error(self):
        self.assertEqual(str(self.formula('"abc"+1')), "#VALUE!")

    def test_round_abs_sqrt_power_mod(self):
        self.assertEqual(self.formula("ROUND(3.14159,2)"), 3.14)
        self.assertEqual(self.formula("ABS(-4)"), 4.0)
        self.assertEqual(self.formula("SQRT(9)"), 3.0)
        self.assertEqual(self.formula("POWER(2,10)"), 1024.0)
        self.assertEqual(self.formula("MOD(7,3)"), 1.0)
        self.assertEqual(self.formula("MOD(-7,3)"), 2.0)

    def test_sqrt_negative_is_num_error(self):
        self.assertEqual(str(self.formula("SQRT(-1)")), "#NUM!")

    def test_string_functions(self):
        self.assertEqual(self.formula('CONCAT("a","b",1)'), "ab1")
        self.assertEqual(self.formula('LEN("hello")'), 5.0)
        self.assertEqual(self.formula('UPPER("abc")'), "ABC")
        self.assertEqual(self.formula('LOWER("ABC")'), "abc")
        self.assertEqual(self.formula('TRIM("  a  b  ")'), "a b")
        self.assertEqual(self.formula('LEFT("hello",2)'), "he")
        self.assertEqual(self.formula('RIGHT("hello",2)'), "lo")
        self.assertEqual(self.formula('MID("hello",2,3)'), "ell")

    def test_and_or_not(self):
        self.assertTrue(self.formula("AND(1=1,2=2)"))
        self.assertFalse(self.formula("AND(1=1,2=3)"))
        self.assertTrue(self.formula("OR(1=2,2=2)"))
        self.assertFalse(self.formula("NOT(TRUE)"))

    def test_sumif_countif_averageif(self):
        self.setc("A1", "apple")
        self.setc("B1", "10")
        self.setc("A2", "banana")
        self.setc("B2", "20")
        self.setc("A3", "apple")
        self.setc("B3", "5")
        self.assertEqual(self.formula('SUMIF(A1:A3,"apple",B1:B3)'), 15.0)
        self.assertEqual(self.formula('COUNTIF(A1:A3,"apple")'), 2.0)
        self.assertEqual(self.formula('AVERAGEIF(A1:A3,"apple",B1:B3)'), 7.5)
        self.assertEqual(self.formula("COUNTIF(B1:B3,\">8\")"), 2.0)

    def test_vlookup_exact_and_approx(self):
        self.setc("A1", "1")
        self.setc("B1", "one")
        self.setc("A2", "2")
        self.setc("B2", "two")
        self.setc("A3", "3")
        self.setc("B3", "three")
        self.assertEqual(self.formula("VLOOKUP(2,A1:B3,2,FALSE)"), "two")
        self.assertEqual(self.formula("VLOOKUP(2.5,A1:B3,2,TRUE)"), "two")
        self.assertEqual(str(self.formula("VLOOKUP(99,A1:B3,2,FALSE)")), "#N/A")

    def test_index_match(self):
        self.setc("A1", "10")
        self.setc("A2", "20")
        self.setc("A3", "30")
        self.assertEqual(self.formula("INDEX(A1:A3,2,1)"), 20.0)
        self.assertEqual(self.formula("MATCH(30,A1:A3,0)"), 3.0)

    def test_wildcard_criteria(self):
        self.setc("A1", "apple")
        self.setc("A2", "apricot")
        self.setc("A3", "banana")
        self.assertEqual(self.formula('COUNTIF(A1:A3,"ap*")'), 2.0)

    def test_function_names_are_case_insensitive(self):
        self.assertEqual(self.formula("sum(1,2,3)"), 6.0)
        self.assertEqual(self.formula("If(1=1,\"y\",\"n\")"), "y")

    def test_isblank_isnumber_istext_iserror(self):
        self.setc("A1", "5")
        self.setc("A2", "text")
        self.assertTrue(self.formula("ISBLANK(A3)"))
        self.assertTrue(self.formula("ISNUMBER(A1)"))
        self.assertTrue(self.formula("ISTEXT(A2)"))
        self.assertTrue(self.formula("ISERROR(1/0)"))
        self.assertFalse(self.formula("ISERROR(1)"))


if __name__ == "__main__":
    unittest.main()
