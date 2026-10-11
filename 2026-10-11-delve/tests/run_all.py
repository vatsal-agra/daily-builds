"""Run every test module; exit non-zero on any failure."""
import os, sys, unittest
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, ".."))
suite = unittest.defaultTestLoader.discover(here, pattern="test_*.py")
res = unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(0 if res.wasSuccessful() else 1)
