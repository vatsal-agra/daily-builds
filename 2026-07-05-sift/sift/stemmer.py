"""A from-scratch implementation of the Porter Stemming Algorithm (1980).

Follows Martin Porter's original paper section by section: the
consonant/vowel classification (with the Y special case), the [C](VC)^m[V]
"measure" of a word, and the five suffix-stripping steps. No NLTK, no
snowballstemmer — just the algorithm.
"""

VOWELS = set("aeiou")


def _is_consonant(word, i):
    ch = word[i]
    if ch in VOWELS:
        return False
    if ch == "y":
        if i == 0:
            return True
        return not _is_consonant(word, i - 1)
    return True


def _cv_string(word):
    return "".join("c" if _is_consonant(word, i) else "v" for i in range(len(word)))


def _measure(word):
    """m in Porter's [C](VC)^m[V] representation of `word`."""
    if not word:
        return 0
    cv = _cv_string(word)
    collapsed = []
    for ch in cv:
        if not collapsed or collapsed[-1] != ch:
            collapsed.append(ch)
    if collapsed and collapsed[0] == "c":
        collapsed = collapsed[1:]
    return collapsed.count("c")


def _contains_vowel(stem):
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _ends_double_consonant(stem):
    return (
        len(stem) >= 2
        and stem[-1] == stem[-2]
        and _is_consonant(stem, len(stem) - 1)
    )


def _cvc(stem):
    """Stem ends consonant-vowel-consonant, and the final consonant is not
    w, x or y (Porter's *o condition)."""
    if len(stem) < 3:
        return False
    n = len(stem)
    return (
        _is_consonant(stem, n - 3)
        and not _is_consonant(stem, n - 2)
        and _is_consonant(stem, n - 1)
        and stem[-1] not in ("w", "x", "y")
    )


def _apply_rules(word, rules, default_ok=None):
    """Try suffix-replacement rules in order; each rule is
    (suffix, replacement, condition_fn_on_stem_before_suffix_or_None).
    Longer suffixes are expected to be listed first when they overlap.
    Returns the (possibly) transformed word."""
    for suffix, replacement, cond in rules:
        if word.endswith(suffix):
            stem = word[: len(word) - len(suffix)]
            if cond is None or cond(stem):
                return stem + replacement
    return word


def _step1a(word):
    rules = [
        ("sses", "ss", None),
        ("ies", "i", None),
        ("ss", "ss", None),
        ("s", "", None),
    ]
    return _apply_rules(word, rules)


def _step1b(word):
    if word.endswith("eed"):
        stem = word[:-3]
        if _measure(stem) > 0:
            return stem + "ee"
        return word

    changed = False
    stem = None
    if word.endswith("ed") and _contains_vowel(word[:-2]):
        stem = word[:-2]
        changed = True
    elif word.endswith("ing") and _contains_vowel(word[:-3]):
        stem = word[:-3]
        changed = True

    if not changed:
        return word

    if stem.endswith(("at", "bl", "iz")):
        return stem + "e"
    if _ends_double_consonant(stem) and stem[-1] not in ("l", "s", "z"):
        return stem[:-1]
    if _measure(stem) == 1 and _cvc(stem):
        return stem + "e"
    return stem


def _step1c(word):
    if word.endswith("y") and len(word) > 1 and _contains_vowel(word[:-1]):
        return word[:-1] + "i"
    return word


_STEP2_RULES = [
    ("ational", "ate", lambda s: _measure(s) > 0),
    ("tional", "tion", lambda s: _measure(s) > 0),
    ("enci", "ence", lambda s: _measure(s) > 0),
    ("anci", "ance", lambda s: _measure(s) > 0),
    ("izer", "ize", lambda s: _measure(s) > 0),
    ("abli", "able", lambda s: _measure(s) > 0),
    ("alli", "al", lambda s: _measure(s) > 0),
    ("entli", "ent", lambda s: _measure(s) > 0),
    ("eli", "e", lambda s: _measure(s) > 0),
    ("ousli", "ous", lambda s: _measure(s) > 0),
    ("ization", "ize", lambda s: _measure(s) > 0),
    ("ation", "ate", lambda s: _measure(s) > 0),
    ("ator", "ate", lambda s: _measure(s) > 0),
    ("alism", "al", lambda s: _measure(s) > 0),
    ("iveness", "ive", lambda s: _measure(s) > 0),
    ("fulness", "ful", lambda s: _measure(s) > 0),
    ("ousness", "ous", lambda s: _measure(s) > 0),
    ("aliti", "al", lambda s: _measure(s) > 0),
    ("iviti", "ive", lambda s: _measure(s) > 0),
    ("biliti", "ble", lambda s: _measure(s) > 0),
]

_STEP3_RULES = [
    ("icate", "ic", lambda s: _measure(s) > 0),
    ("ative", "", lambda s: _measure(s) > 0),
    ("alize", "al", lambda s: _measure(s) > 0),
    ("iciti", "ic", lambda s: _measure(s) > 0),
    ("ical", "ic", lambda s: _measure(s) > 0),
    ("ful", "", lambda s: _measure(s) > 0),
    ("ness", "", lambda s: _measure(s) > 0),
]

_STEP4_RULES = [
    ("al", "", lambda s: _measure(s) > 1),
    ("ance", "", lambda s: _measure(s) > 1),
    ("ence", "", lambda s: _measure(s) > 1),
    ("er", "", lambda s: _measure(s) > 1),
    ("ic", "", lambda s: _measure(s) > 1),
    ("able", "", lambda s: _measure(s) > 1),
    ("ible", "", lambda s: _measure(s) > 1),
    ("ant", "", lambda s: _measure(s) > 1),
    ("ement", "", lambda s: _measure(s) > 1),
    ("ment", "", lambda s: _measure(s) > 1),
    ("ent", "", lambda s: _measure(s) > 1),
    ("ion", "", lambda s: _measure(s) > 1 and s.endswith(("s", "t"))),
    ("ou", "", lambda s: _measure(s) > 1),
    ("ism", "", lambda s: _measure(s) > 1),
    ("ate", "", lambda s: _measure(s) > 1),
    ("iti", "", lambda s: _measure(s) > 1),
    ("ous", "", lambda s: _measure(s) > 1),
    ("ive", "", lambda s: _measure(s) > 1),
    ("ize", "", lambda s: _measure(s) > 1),
]


def porter_stem(word):
    """Return the Porter stem of a lowercase ASCII word."""
    word = word.lower()
    if len(word) <= 2:
        return word

    word = _step1a(word)
    word = _step1b(word)
    word = _step1c(word)
    word = _apply_rules(word, _STEP2_RULES)
    word = _apply_rules(word, _STEP3_RULES)
    word = _apply_rules(word, _STEP4_RULES)

    # Step 5a
    if word.endswith("e"):
        stem = word[:-1]
        m = _measure(stem)
        if m > 1 or (m == 1 and not _cvc(stem)):
            word = stem

    # Step 5b
    if _measure(word) > 1 and _ends_double_consonant(word) and word.endswith("l"):
        word = word[:-1]

    return word
