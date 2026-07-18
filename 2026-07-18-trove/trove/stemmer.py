"""
A from-scratch implementation of the Porter Stemming Algorithm (M.F. Porter,
1980, "An algorithm for suffix stripping"). No external dependencies.

The algorithm reduces a word to its stem by applying five ordered steps of
suffix-stripping rules, each gated by conditions on the "measure" m of the
stem — the number of alternating vowel-consonant sequences ([C](VC)^m[V]) —
plus a few structural predicates (*v*, *d, *o) defined in the paper.
"""

VOWELS = set("aeiou")


def _is_consonant(word, i):
    ch = word[i]
    if ch in VOWELS:
        return False
    if ch != "y":
        return True
    # y is a consonant unless preceded by a consonant (i.e. y is a vowel
    # only when the letter before it is itself a consonant... this is the
    # classic inversion: 'y' acts as a vowel when it FOLLOWS a consonant,
    # and as a consonant when it starts the word or follows a vowel).
    if i == 0:
        return True
    return not _is_consonant(word, i - 1)


def _measure(stem):
    """m = number of VC sequences in the word's [C](VC)^m[V] decomposition."""
    n = len(stem)
    i = 0
    m = 0
    # skip leading consonant sequence
    while i < n and _is_consonant(stem, i):
        i += 1
    while i < n:
        # skip vowel sequence
        while i < n and not _is_consonant(stem, i):
            i += 1
        if i >= n:
            break
        # skip consonant sequence -> one VC unit consumed
        while i < n and _is_consonant(stem, i):
            i += 1
        m += 1
    return m


def _contains_vowel(stem):
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _ends_double_consonant(stem):
    return (
        len(stem) >= 2
        and stem[-1] == stem[-2]
        and _is_consonant(stem, len(stem) - 1)
    )


def _ends_cvc(stem):
    """Stem ends consonant-vowel-consonant, and the final consonant is not
    w, x or y (the *o condition)."""
    n = len(stem)
    if n < 3:
        return False
    if not (_is_consonant(stem, n - 3) and not _is_consonant(stem, n - 2) and _is_consonant(stem, n - 1)):
        return False
    return stem[-1] not in ("w", "x", "y")


def _ends_with(word, suffix):
    return word.endswith(suffix)


def _replace_suffix(word, suffix, replacement):
    return word[: len(word) - len(suffix)] + replacement


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


def _step1b(word):
    if word.endswith("eed"):
        stem = word[:-3]
        if _measure(stem) > 0:
            return stem + "ee"
        return word

    for suffix in ("ed", "ing"):
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if not _contains_vowel(stem):
                continue
            return _step1b_cleanup(stem)
    return word


def _step1b_cleanup(stem):
    if stem.endswith(("at", "bl", "iz")):
        return stem + "e"
    if _ends_double_consonant(stem) and stem[-1] not in ("l", "s", "z"):
        return stem[:-1]
    if _measure(stem) == 1 and _ends_cvc(stem):
        return stem + "e"
    return stem


def _step1c(word):
    if word.endswith("y") and len(word) > 1 and _contains_vowel(word[:-1]):
        return word[:-1] + "i"
    return word


_STEP2_SUFFIXES = [
    ("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"),
    ("izer", "ize"), ("abli", "able"), ("alli", "al"), ("entli", "ent"),
    ("eli", "e"), ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"),
    ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"),
    ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"),
]


def _step2(word):
    for suffix, replacement in _STEP2_SUFFIXES:
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if _measure(stem) > 0:
                return stem + replacement
            return word
    return word


_STEP3_SUFFIXES = [
    ("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"),
    ("ical", "ic"), ("ful", ""), ("ness", ""),
]


def _step3(word):
    for suffix, replacement in _STEP3_SUFFIXES:
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if _measure(stem) > 0:
                return stem + replacement
            return word
    return word


_STEP4_SUFFIXES = [
    "al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement",
    "ment", "ent", "ou", "ism", "ate", "iti", "ous", "ive", "ize",
]


def _step4(word):
    # (m>1) (S|T)ION -> '' (a special rule requiring s or t before "ion")
    if word.endswith("ion") and len(word) > 3 and word[-4] in ("s", "t"):
        stem = word[:-3]
        if _measure(stem) > 1:
            return stem
        return word
    for suffix in sorted(_STEP4_SUFFIXES, key=len, reverse=True):
        if suffix == "ion":
            continue
        if word.endswith(suffix):
            stem = word[: -len(suffix)]
            if _measure(stem) > 1:
                return stem
            return word
    return word


def _step5a(word):
    if word.endswith("e"):
        stem = word[:-1]
        m = _measure(stem)
        if m > 1:
            return stem
        if m == 1 and not _ends_cvc(stem):
            return stem
    return word


def _step5b(word):
    if _measure(word) > 1 and _ends_double_consonant(word) and word.endswith("l"):
        return word[:-1]
    return word


def stem(word):
    """Reduce a single lowercase alphabetic word to its Porter stem."""
    word = word.lower()
    if not word or not word.isalpha():
        return word
    w = word
    w = _step1a(w)
    w = _step1b(w)
    w = _step1c(w)
    w = _step2(w)
    w = _step3(w)
    w = _step4(w)
    w = _step5a(w)
    w = _step5b(w)
    return w
