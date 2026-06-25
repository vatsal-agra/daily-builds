#!/usr/bin/env python3
"""Entry point: python qsim_cli.py <subcommand> ..."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from qsim.cli import main
main()
