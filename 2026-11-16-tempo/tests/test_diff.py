"""Differential tests against dateutil / croniter (skipped when they are not installed).

Set TEMPO_ORACLES=/path/to/site-packages to point at a directory containing them.
Known, deliberate divergences are documented in README.md and excluded here.
"""
import os
import sys
import unittest

oracle = os.environ.get("TEMPO_ORACLES")
if oracle:
    sys.path.insert(0, oracle)
try:
    import dateutil.rrule   # noqa: F401
    HAVE_DU = True
except Exception:
    HAVE_DU = False
try:
    import croniter   # noqa: F401
    HAVE_CR = True
except Exception:
    HAVE_CR = False


@unittest.skipUnless(HAVE_DU, "python-dateutil not installed")
class RRuleVsDateutil(unittest.TestCase):
    def test_random_rules(self):
        from tests import fuzz_rrule
        for seed in (101, 102):
            compared, bad = fuzz_rrule.run(seed, 120)
            self.assertEqual(bad, 0, f"seed {seed}")
            self.assertGreater(compared, 80)


@unittest.skipUnless(HAVE_CR, "croniter not installed")
class CronVsCroniter(unittest.TestCase):
    def test_random_expressions(self):
        from tests import fuzz_cron
        for seed in (201, 202):
            compared, bad = fuzz_cron.run(seed, 150)
            self.assertEqual(bad, 0, f"seed {seed}")
            self.assertGreater(compared, 100)


if __name__ == "__main__":
    unittest.main()
