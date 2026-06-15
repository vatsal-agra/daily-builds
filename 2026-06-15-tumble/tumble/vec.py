"""Tiny 2D vector helpers (used by builders/tests; the engine hot loop inlines)."""
import math


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def scale(a, s):
    return (a[0] * s, a[1] * s)


def length(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1])


def dist(a, b):
    return length(sub(a, b))
