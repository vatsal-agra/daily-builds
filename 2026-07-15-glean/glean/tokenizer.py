"""Text analysis pipeline: Unicode word tokenizer + a from-scratch Porter stemmer.

Implements the Porter (1980) stemming algorithm exactly as specified —
steps 1a/1b/1c, 2, 3, 4, 5a/5b over the classic consonant/vowel measure
(m), the *v* / *d / *o conditions, and the standard suffix-replacement
tables — with no third-party stemming library involved.
"""

import re
from collections import namedtuple

_TOKEN_RE = re.compile(r"[^\W\d_]+|\d+", re.UNICODE)

STOPWORDS = frozenset("""
a an and are as at be by for from has have he in is it its of on
that the to was were will with this these those but or not no nor
i you your yours we our ours they them their theirs my me him her
his she it's do does did doing been being if then so than too
""".split())

_VOWELS = "aeiou"


def _is_consonant(word, i):
    """True if word[i] is a consonant. 'y' alternates: a consonant unless the
    letter before it is itself a consonant. Computed iteratively (not via
    self-recursion) so a pathological run of thousands of 'y's can't blow
    the interpreter's call stack."""
    c = word[i]
    if c in _VOWELS:
        return False
    if c != "y":
        return True
    status = True  # a leading 'y' is always a consonant
    for j in range(1, i + 1):
        cj = word[j]
        if cj in _VOWELS:
            status = False
        elif cj == "y":
            status = not status
        else:
            status = True
    return status


def _measure(stem):
    """Count of VC sequences following any leading consonants (Porter's m)."""
    n = 0
    i = 0
    length = len(stem)
    while i < length and _is_consonant(stem, i):
        i += 1
    while True:
        while i < length and not _is_consonant(stem, i):
            i += 1
        if i >= length:
            break
        n += 1
        while i < length and _is_consonant(stem, i):
            i += 1
        if i >= length:
            break
    return n


def _contains_vowel(stem):
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _ends_double_consonant(stem):
    if len(stem) < 2 or stem[-1] != stem[-2]:
        return False
    return _is_consonant(stem, len(stem) - 1)


def _cvc(stem):
    n = len(stem)
    if n < 3:
        return False
    if not _is_consonant(stem, n - 3):
        return False
    if _is_consonant(stem, n - 2):
        return False
    if not _is_consonant(stem, n - 1):
        return False
    if stem[-1] in "wxy":
        return False
    return True


def _step1a(word):
    if word.endswith("sses"):
        return word[:-2]
    if word.endswith("ies"):
        return word[:-2]
    if word.endswith("ss"):
        return word
    if word.endswith("s"):
        return word[:-1]
    return word


def _step1b_cleanup(stem):
    if stem.endswith(("at", "bl", "iz")):
        return stem + "e"
    if _ends_double_consonant(stem) and stem[-1] not in "lsz":
        return stem[:-1]
    if _measure(stem) == 1 and _cvc(stem):
        return stem + "e"
    return stem


def _step1b(word):
    if word.endswith("eed"):
        stem = word[:-3]
        if _measure(stem) > 0:
            return stem + "ee"
        return word
    if word.endswith("ed") and _contains_vowel(word[:-2]):
        return _step1b_cleanup(word[:-2])
    if word.endswith("ing") and _contains_vowel(word[:-3]):
        return _step1b_cleanup(word[:-3])
    return word


def _step1c(word):
    if word.endswith("y") and len(word) > 1 and _contains_vowel(word[:-1]):
        return word[:-1] + "i"
    return word


_STEP2_RULES = [
    ("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"),
    ("izer", "ize"), ("abli", "able"), ("alli", "al"), ("entli", "ent"),
    ("eli", "e"), ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"),
    ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"),
    ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"),
]
_STEP2_RULES.sort(key=lambda r: -len(r[0]))

_STEP3_RULES = [
    ("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"),
    ("ical", "ic"), ("ful", ""), ("ness", ""),
]
_STEP3_RULES.sort(key=lambda r: -len(r[0]))

_STEP4_SUFFIXES = [
    "al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement",
    "ment", "ent", "ion", "ou", "ism", "ate", "iti", "ous", "ive", "ize",
]
_STEP4_SUFFIXES.sort(key=len, reverse=True)


def _step2(word):
    for suf, rep in _STEP2_RULES:
        if word.endswith(suf):
            stem = word[: -len(suf)]
            if _measure(stem) > 0:
                return stem + rep
            return word
    return word


def _step3(word):
    for suf, rep in _STEP3_RULES:
        if word.endswith(suf):
            stem = word[: -len(suf)]
            if _measure(stem) > 0:
                return stem + rep
            return word
    return word


def _step4(word):
    for suf in _STEP4_SUFFIXES:
        if word.endswith(suf):
            stem = word[: -len(suf)]
            if suf == "ion":
                if stem and stem[-1] in "st" and _measure(stem) > 1:
                    return stem
                return word
            if _measure(stem) > 1:
                return stem
            return word
    return word


def _step5a(word):
    if word.endswith("e"):
        stem = word[:-1]
        m = _measure(stem)
        if m > 1 or (m == 1 and not _cvc(stem)):
            return stem
    return word


def _step5b(word):
    if _measure(word) > 1 and word.endswith("l") and _ends_double_consonant(word):
        return word[:-1]
    return word


def porter_stem(word):
    """Reduce a lowercase alphabetic word to its Porter stem."""
    word = word.lower()
    if len(word) <= 2 or not word.isalpha():
        return word
    word = _step1a(word)
    word = _step1b(word)
    word = _step1c(word)
    word = _step2(word)
    word = _step3(word)
    word = _step4(word)
    word = _step5a(word)
    word = _step5b(word)
    return word


def tokenize(text):
    """Yield (lowercased_raw_token, start_offset, end_offset) for each word/number."""
    for m in _TOKEN_RE.finditer(text):
        raw = m.group(0)
        yield raw.lower(), m.start(), m.end()


Token = namedtuple("Token", "term raw start end is_stopword")


def analyze(text):
    """Full analyzer pipeline: tokenize -> stem, tagging stopwords (still kept)."""
    tokens = []
    for raw, start, end in tokenize(text):
        term = porter_stem(raw) if raw.isalpha() else raw
        tokens.append(Token(term, raw, start, end, raw in STOPWORDS))
    return tokens
