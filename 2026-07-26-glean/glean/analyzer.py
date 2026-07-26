"""Text analysis pipeline: tokenize -> fold case -> strip stopwords -> stem.

Implements the Porter (1980) stemming algorithm from scratch (no nltk/snowball).
"""
import re
import unicodedata

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:'[A-Za-z]+)?")
TOKEN_RE = _TOKEN_RE  # public alias, reused for snippet highlighting

STOPWORDS = frozenset("""
a an and are as at be by for from has have he in is it its of on or that the
to was were will with this these those but not no nor so if then than
""".split())

VOWELS = "aeiou"


def _is_consonant(word, i):
    ch = word[i]
    if ch in VOWELS:
        return False
    if ch == "y":
        return i == 0 or not _is_consonant(word, i - 1)
    return True


def _measure(stem):
    """Number of VC (vowel-consonant) sequences — the Porter 'm' value."""
    form = "".join("C" if _is_consonant(stem, i) else "V" for i in range(len(stem)))
    form = re.sub(r"C+", "C", form)
    form = re.sub(r"V+", "V", form)
    return form.count("VC")


def _contains_vowel(stem):
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _ends_double_consonant(stem):
    return (
        len(stem) >= 2
        and stem[-1] == stem[-2]
        and _is_consonant(stem, len(stem) - 1)
    )


def _ends_cvc(stem):
    if len(stem) < 3:
        return False
    if not (
        _is_consonant(stem, len(stem) - 3)
        and not _is_consonant(stem, len(stem) - 2)
        and _is_consonant(stem, len(stem) - 1)
    ):
        return False
    return stem[-1] not in "wxy"


def _apply_rules(word, rules, default=None):
    """Apply the first matching (suffix, condition, replacement) rule."""
    for suffix, condition, replacement in rules:
        if suffix == "" or word.endswith(suffix):
            stem = word[: len(word) - len(suffix)] if suffix else word
            if condition is None or condition(stem):
                return stem + replacement
    return default if default is not None else word


def porter_stem(word):
    """Reduce an English word to its Porter stem. Pure-Python, no deps."""
    word = word.lower()
    if len(word) <= 2:
        return word

    # Step 1a
    word = _apply_rules(
        word,
        [
            ("sses", None, "ss"),
            ("ies", None, "i"),
            ("ss", None, "ss"),
            ("s", None, ""),
        ],
        default=word,
    )

    # Step 1b
    step1b_extra = False
    if word.endswith("eed"):
        stem = word[:-3]
        if _measure(stem) > 0:
            word = stem + "ee"
    elif word.endswith("ed") and _contains_vowel(word[:-2]):
        word = word[:-2]
        step1b_extra = True
    elif word.endswith("ing") and _contains_vowel(word[:-3]):
        word = word[:-3]
        step1b_extra = True

    if step1b_extra:
        if word.endswith(("at", "bl", "iz")):
            word = word + "e"
        elif _ends_double_consonant(word) and word[-1] not in "lsz":
            word = word[:-1]
        elif _measure(word) == 1 and _ends_cvc(word):
            word = word + "e"

    # Step 1c
    if word.endswith("y") and _contains_vowel(word[:-1]):
        word = word[:-1] + "i"

    # Step 2
    step2_rules = [
        ("ational", lambda s: _measure(s) > 0, "ate"),
        ("tional", lambda s: _measure(s) > 0, "tion"),
        ("enci", lambda s: _measure(s) > 0, "ence"),
        ("anci", lambda s: _measure(s) > 0, "ance"),
        ("izer", lambda s: _measure(s) > 0, "ize"),
        ("abli", lambda s: _measure(s) > 0, "able"),
        ("alli", lambda s: _measure(s) > 0, "al"),
        ("entli", lambda s: _measure(s) > 0, "ent"),
        ("eli", lambda s: _measure(s) > 0, "e"),
        ("ousli", lambda s: _measure(s) > 0, "ous"),
        ("ization", lambda s: _measure(s) > 0, "ize"),
        ("ation", lambda s: _measure(s) > 0, "ate"),
        ("ator", lambda s: _measure(s) > 0, "ate"),
        ("alism", lambda s: _measure(s) > 0, "al"),
        ("iveness", lambda s: _measure(s) > 0, "ive"),
        ("fulness", lambda s: _measure(s) > 0, "ful"),
        ("ousness", lambda s: _measure(s) > 0, "ous"),
        ("aliti", lambda s: _measure(s) > 0, "al"),
        ("iviti", lambda s: _measure(s) > 0, "ive"),
        ("biliti", lambda s: _measure(s) > 0, "ble"),
    ]
    for suffix, cond, repl in step2_rules:
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if cond(stem):
                word = stem + repl
            break

    # Step 3
    step3_rules = [
        ("icate", lambda s: _measure(s) > 0, "ic"),
        ("ative", lambda s: _measure(s) > 0, ""),
        ("alize", lambda s: _measure(s) > 0, "al"),
        ("iciti", lambda s: _measure(s) > 0, "ic"),
        ("ical", lambda s: _measure(s) > 0, "ic"),
        ("ful", lambda s: _measure(s) > 0, ""),
        ("ness", lambda s: _measure(s) > 0, ""),
    ]
    for suffix, cond, repl in step3_rules:
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if cond(stem):
                word = stem + repl
            break

    # Step 4
    step4_rules = [
        ("al", None), ("ance", None), ("ence", None), ("er", None),
        ("ic", None), ("able", None), ("ible", None), ("ant", None),
        ("ement", None), ("ment", None), ("ent", None),
        ("ion", lambda s: s.endswith(("s", "t"))),
        ("ou", None), ("ism", None), ("ate", None), ("iti", None),
        ("ous", None), ("ive", None), ("ize", None),
    ]
    for suffix, extra_cond in step4_rules:
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if _measure(stem) > 1 and (extra_cond is None or extra_cond(stem)):
                word = stem
            break

    # Step 5a
    if word.endswith("e"):
        stem = word[:-1]
        m = _measure(stem)
        if m > 1 or (m == 1 and not _ends_cvc(stem)):
            word = stem

    # Step 5b
    if _measure(word) > 1 and _ends_double_consonant(word) and word.endswith("l"):
        word = word[:-1]

    return word


def tokenize(text):
    """Yield lowercase, unicode-normalized raw tokens with their character offsets."""
    text = unicodedata.normalize("NFKC", text)
    for match in _TOKEN_RE.finditer(text):
        yield match.group(0).lower(), match.start()


def analyze(text, stem=True, remove_stopwords=True):
    """Full pipeline: text -> list of (term, position, raw_token) triples.

    `position` is a 0-based token index (used for phrase adjacency), not a
    character offset — that's preserved separately for snippet generation.
    """
    out = []
    pos = 0
    for raw, _offset in tokenize(text):
        if remove_stopwords and raw in STOPWORDS:
            pos += 1
            continue
        term = porter_stem(raw) if stem else raw
        out.append((term, pos, raw))
        pos += 1
    return out
