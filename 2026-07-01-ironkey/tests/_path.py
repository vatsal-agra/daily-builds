"""Adds the project root to sys.path so tests can `import aes`, `import
rsa`, etc. without installing a package. Imported first by every test
module in this directory."""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
