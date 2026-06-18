"""The box / glue / penalty node model.

Knuth's insight is that *all* typeset material can be represented as a sequence
of three kinds of items:

* **Box** — something with a fixed width that gets typeset (a word, a piece of a
  word). Boxes are never breakpoints.
* **Glue** — stretchable/shrinkable space (the space between words). A line may
  break at glue, but only when the glue follows a box.
* **Penalty** — a potential breakpoint with an associated aesthetic cost and an
  optional width that only appears if the break is taken (e.g. a hyphen). A
  penalty of ``-INFINITY`` forces a break; ``+INFINITY`` forbids one.

This module defines those three items and a tokenizer that compiles a string
into a node list, optionally inserting hyphenation penalties inside words.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

#: Penalty value treated as "infinitely bad" — a break here is forbidden.
INFINITY = 10000


@dataclass
class Box:
    width: float
    text: str = ""

    is_box = True
    is_glue = False
    is_penalty = False


@dataclass
class Glue:
    width: float
    stretch: float
    shrink: float

    is_box = False
    is_glue = True
    is_penalty = False


@dataclass
class Penalty:
    width: float
    penalty: float
    flagged: bool = False

    is_box = False
    is_glue = False
    is_penalty = True


Item = object  # one of Box | Glue | Penalty


@dataclass
class Paragraph:
    """A node list plus the source words, ready for line breaking."""

    items: List[Item] = field(default_factory=list)
    #: For each box index, the source word index it belongs to (for round-trip
    #: verification and rendering). -1 for non-word boxes.
    words: List[str] = field(default_factory=list)


def _glue_for_space(font, *, justified: bool = True) -> Glue:
    """Standard inter-word glue for a font.

    The natural space is the font's space advance.  TeX-like defaults give it a
    stretch of half and a shrink of a third of the natural space, which is what
    produces good justification.
    """
    sp = font.space_width
    if justified:
        return Glue(width=sp, stretch=sp * 0.5, shrink=sp * 0.3333)
    # Ragged-right: spaces are rigid; breakability comes from large stretch with
    # a zero-cost glue handled by the breaker's ragged mode instead.
    return Glue(width=sp, stretch=sp * 0.5, shrink=sp * 0.3333)


def build_paragraph(
    text: str,
    font,
    *,
    hyphenate=None,
    hyphen_penalty: float = 50,
    justified: bool = True,
) -> Paragraph:
    """Compile *text* into a :class:`Paragraph` node list.

    ``hyphenate`` is an optional callable ``word -> list[str]`` splitting a word
    into syllable fragments; if given, a flagged hyphenation penalty is inserted
    between fragments so the breaker may hyphenate long words.
    """
    words = text.split()
    items: List[Item] = []
    sp_glue = _glue_for_space(font, justified=justified)
    hyphen_w = font.char_width("-")

    for wi, word in enumerate(words):
        if wi > 0:
            # Inter-word glue (a fresh object per gap so spacing can differ).
            items.append(Glue(sp_glue.width, sp_glue.stretch, sp_glue.shrink))

        fragments = [word]
        if hyphenate is not None:
            fragments = hyphenate_token(word, hyphenate)

        if len(fragments) == 1:
            items.append(Box(font.width(word), word))
        else:
            for fi, frag in enumerate(fragments):
                items.append(Box(font.width(frag), frag))
                if fi < len(fragments) - 1:
                    # Optional hyphenation point: width = hyphen only if broken.
                    items.append(Penalty(hyphen_w, hyphen_penalty, flagged=True))

    _append_finish(items)
    return Paragraph(items=items, words=words)


def _append_finish(items: List[Item]) -> None:
    """Append the canonical paragraph-ending sequence.

    ``\\penalty INFINITY`` (forbid a break before the fill), a fill glue with
    very large stretch so the final line is not stretched, and a forced break.
    """
    items.append(Penalty(0, INFINITY, flagged=False))
    items.append(Glue(0, 1e9, 0))
    items.append(Penalty(0, -INFINITY, flagged=False))


def hyphenate_token(token: str, hyphenate) -> List[str]:
    """Hyphenate the alphabetic core of *token*, keeping punctuation attached.

    ``hyphenate`` is a callable ``core -> [fragments]``.  Leading/trailing
    non-letters (quotes, commas, parentheses) stay glued to the adjacent
    fragment, so ``beautiful,`` can break as ``beau`` ``ti`` ``ful,`` but the
    comma never starts a line on its own.  Tokens with interior non-letters
    (already-hyphenated words, contractions written with apostrophes) are left
    whole.
    """
    # Peel leading and trailing non-letters.
    i, j = 0, len(token)
    while i < j and not token[i].isalpha():
        i += 1
    while j > i and not token[j - 1].isalpha():
        j -= 1
    lead, core, trail = token[:i], token[i:j], token[j:]
    if not core.isalpha() or len(core) < 5:
        return [token]
    frags = hyphenate(core)
    if len(frags) <= 1:
        return [token]
    frags[0] = lead + frags[0]
    frags[-1] = frags[-1] + trail
    return frags


def is_legal_breakpoint(items: List[Item], i: int) -> bool:
    """Whether a line may legally break *at* item index ``i``."""
    item = items[i]
    if item.is_penalty:
        return item.penalty < INFINITY
    if item.is_glue:
        return i > 0 and items[i - 1].is_box
    return False
