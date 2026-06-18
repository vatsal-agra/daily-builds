"""Galley — optimal typesetting from scratch.

Knuth--Plass total-fit line breaking, Liang hyphenation, real AFM font metrics,
and justified SVG/HTML rendering, in pure Python with no dependencies.
"""

from .metrics import Font, available_families
from .model import Box, Glue, Penalty, Paragraph, build_paragraph, INFINITY
from .hyphen import Hyphenator, hyphenate
from .linebreak import (
    Breaking,
    Line,
    break_paragraph,
    greedy_break,
    brute_force_break,
    evaluate_breaks,
    badness,
    fitness_class,
    InfeasibleParagraph,
)

__version__ = "1.0.0"

__all__ = [
    "Font", "available_families",
    "Box", "Glue", "Penalty", "Paragraph", "build_paragraph", "INFINITY",
    "Hyphenator", "hyphenate",
    "Breaking", "Line", "break_paragraph", "greedy_break", "brute_force_break",
    "evaluate_breaks", "badness", "fitness_class", "InfeasibleParagraph",
]
