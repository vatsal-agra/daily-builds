"""Minimal 2D vector math — no numpy, plain tuples of floats."""
import math


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def scale(a, s):
    return (a[0] * s, a[1] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    """2D cross product yields a scalar (z-component)."""
    return a[0] * b[1] - a[1] * b[0]


def cross_sv(s, v):
    """scalar x vector -> vector, matches d/dt(rotation) x r convention."""
    return (-s * v[1], s * v[0])


def length(a):
    return math.hypot(a[0], a[1])


def normalize(a):
    n = length(a)
    if n < 1e-12:
        return (0.0, 0.0)
    return (a[0] / n, a[1] / n)


def perp(a):
    """90-degree CCW rotation."""
    return (-a[1], a[0])


def rotate(a, angle):
    c, s = math.cos(angle), math.sin(angle)
    return (a[0] * c - a[1] * s, a[0] * s + a[1] * c)
