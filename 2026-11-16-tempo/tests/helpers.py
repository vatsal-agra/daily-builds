import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
UTC = timezone.utc


def d(y, m, dd, h=0, mi=0, s=0):
    return datetime(y, m, dd, h, mi, s)


def iso(xs):
    return [x.strftime("%Y-%m-%d") if (x.hour, x.minute, x.second) == (0, 0, 0) else x.strftime("%Y-%m-%dT%H:%M:%S") for x in xs]


def days(xs):
    return [x.strftime("%Y-%m-%d") for x in xs]
