import os, random, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from striate import encode, EncodeError
from striate.symbologies import code128, ean, code39, itf


class Code128Tests(unittest.TestCase):
    def test_table_integrity(self):
        T = code128.TABLE
        self.assertEqual(len(set(T)), 107)
        for i, p in enumerate(T[:106]):
            self.assertEqual((len(p), sum(p), sum(p[0::2]) % 2), (6, 11, 0), i)
        self.assertEqual(sum(T[106]), 13)

    def test_wikipedia_checksum_vector(self):
        # "PJJ123C" in start-A: checksum 54 (published example)
        self.assertEqual(code128.checksum([103] + [ord(c) - 32 for c in "PJJ123C"]), 54)

    def test_modules_length(self):
        b = encode("code128", "PJJ123C")
        self.assertEqual(len(b.modules), 11 * (1 + 7 + 1) + 13)

    def test_optimal_switching_digits_use_set_c(self):
        v = code128.encode_values("1234567890")
        self.assertEqual(v, [105, 12, 34, 56, 78, 90])
        v = code128.encode_values("ab1234567890")      # B then C
        self.assertEqual(v[0], 104)
        self.assertIn(99, v)

    def test_odd_digit_run(self):
        v = code128.encode_values("12345")
        self.assertEqual(len(v), 5)    # 5 is optimal: start-C,12,34,CODE-B,5 (or B,1,CODE-C,23,45)
        self.assertEqual(code128.decode_values(v), "12345")

    def test_shift_used_for_lone_lowercase_in_set_a(self):
        t = "\x01\x02\x03a\x04\x05\x06"   # control chars force set A; lone 'a' via SHIFT
        v = code128.encode_values(t)
        self.assertIn(98, v)
        self.assertEqual(code128.decode_values(v), t)

    def test_roundtrip_random(self):
        rnd = random.Random(1)
        alphabet = [chr(i) for i in range(0, 128)] + ["\xf1"]
        for _ in range(300):
            t = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, 20)))
            if rnd.random() < .3:
                t = "".join(rnd.choice("0123456789") for _ in range(rnd.randint(1, 30)))
            self.assertEqual(code128.decode_values(code128.encode_values(t)), t)

    def test_rejects(self):
        for bad in ["", "héllo", "日本"]:
            with self.assertRaises(EncodeError):
                encode("code128", bad)


class EanTests(unittest.TestCase):
    def test_check_digits(self):
        self.assertEqual(ean.check_digit("400638133393"), "1")
        self.assertEqual(ean.check_digit("036000291452"[:-1]), "2")
        self.assertEqual(ean.check_digit("9638507"), "4")

    def test_ean13_known_modules(self):
        # 4006381333931: first digit 4 -> parity LGLLGG
        b = encode("ean13", "4006381333931")
        self.assertEqual(len(b.modules), 95)
        self.assertTrue(b.modules.startswith("101") and b.modules.endswith("101"))
        self.assertEqual(b.modules[45:50], "01010")
        self.assertEqual(b.modules[3:10], ean.L[0])      # digit '0' coded with L
        self.assertEqual(b.modules[10:17], ean.G[0])     # next digit '0' coded with G

    def test_autocheck_and_bad_check(self):
        self.assertEqual(encode("ean13", "400638133393").text, "4006381333931")
        with self.assertRaises(EncodeError):
            encode("ean13", "4006381333930")
        with self.assertRaises(EncodeError):
            encode("ean13", "12345")
        with self.assertRaises(EncodeError):
            encode("ean13", "40063813339a")

    def test_upca_is_ean13_with_leading_zero(self):
        u, e = encode("upca", "03600029145"), encode("ean13", "0036000291452")
        self.assertEqual(u.text, "036000291452")
        self.assertEqual(u.modules, e.modules)

    def test_ean8(self):
        b = encode("ean8", "9638507")
        self.assertEqual((b.text, len(b.modules)), ("96385074", 67))


class Code39Tests(unittest.TestCase):
    def test_pattern_structure(self):
        P = code39.PAT
        self.assertEqual(len(P), 44)
        for ch, p in P.items():
            self.assertEqual(p.count("W"), 3, ch)
        # published structure: K-T derive from A-J by moving the 6th-element wide to the 8th; U-Z to the 2nd
        for a, k, u in zip("ABCDEFGHIJ", "KLMNOPQRST", "UVWXYZ"):
            wa = [i for i, c in enumerate(P[a]) if c == "W"]
            wk = [i for i, c in enumerate(P[k]) if c == "W"]
            self.assertEqual(sorted(i if i != 5 else 7 for i in wa), wk, a)
            wu = [i for i, c in enumerate(P[u]) if c == "W"]
            self.assertEqual(sorted(i if i != 5 else 1 for i in [i for i in [*wa]]), wu, a)

    def test_length(self):
        b = encode("code39", "AB")
        # each char: 6 narrow*1 + 3 wide*3 = 12 modules ... 9 elems: 6N+3W = 15 modules; +1 gap
        self.assertEqual(len(b.modules), 4 * 15 + 3)

    def test_mod43(self):
        self.assertEqual(code39.check_char("CODE39"), "W")
        self.assertEqual(encode("code39", "CODE39", mod43=True).text, "CODE39W")

    def test_reject(self):
        for bad in ["", "a*b", "héllo", "A&B"]:
            if bad == "a*b" or bad == "A&B" or bad == "héllo" or bad == "":
                with self.assertRaises(EncodeError):
                    encode("code39", bad)

    def test_lowercase_is_uppercased(self):
        self.assertEqual(encode("code39", "abc").text, "ABC")


class ItfTests(unittest.TestCase):
    def test_modules(self):
        b = encode("itf", "12")
        # start 4 + (5 bars + 5 spaces: digit1 bars '1'=WNNNW, digit2 spaces '2'=NWNNW) + stop W N N
        self.assertEqual(b.runs()[:4], [1, 1, 1, 1])
        self.assertEqual(b.runs()[-3:], [3, 1, 1])
        self.assertEqual(len(b.runs()), 4 + 10 + 3)

    def test_odd_rejected_check_ok(self):
        with self.assertRaises(EncodeError):
            encode("itf", "123")
        self.assertEqual(encode("itf", "123", check=True).text, "1236")
        self.assertEqual(itf.mod10("00012345678"), "5")

    def test_digits_only(self):
        with self.assertRaises(EncodeError):
            encode("itf", "12ab")


if __name__ == "__main__":
    unittest.main()
