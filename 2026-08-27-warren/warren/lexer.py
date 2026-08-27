"""Tokenizer for Prolog source text."""

SYMBOL_CHARS = set("+-*/\\^<>=~:.?@#&$")
SOLO_CHARS = set("()[]{},|!;")


class Token:
    __slots__ = ("kind", "value", "pos", "preceded_by_space")

    def __init__(self, kind, value, pos, preceded_by_space=False):
        self.kind = kind          # 'atom' 'var' 'int' 'float' 'string' 'punct' 'end' 'eof'
        self.value = value
        self.pos = pos
        self.preceded_by_space = preceded_by_space

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r})"


class LexError(Exception):
    pass


def tokenize(text):
    tokens = []
    i, n = 0, len(text)
    had_space = True  # start-of-input counts as "preceded by space" (no functor-paren ambiguity)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            had_space = True
            continue
        if c == "%":
            while i < n and text[i] != "\n":
                i += 1
            had_space = True
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            if end == -1:
                raise LexError(f"unterminated block comment at {i}")
            i = end + 2
            had_space = True
            continue

        start = i
        if c.isdigit():
            i2 = i
            while i2 < n and text[i2].isdigit():
                i2 += 1
            is_float = False
            if i2 < n and text[i2] == "." and i2 + 1 < n and text[i2 + 1].isdigit():
                is_float = True
                i2 += 1
                while i2 < n and text[i2].isdigit():
                    i2 += 1
            if i2 < n and text[i2] in "eE" and (i2 + 1 < n and (text[i2 + 1].isdigit() or
                    (text[i2 + 1] in "+-" and i2 + 2 < n and text[i2 + 2].isdigit()))):
                is_float = True
                i2 += 1
                if text[i2] in "+-":
                    i2 += 1
                while i2 < n and text[i2].isdigit():
                    i2 += 1
            # 0'c character code literal
            if text[start:i2] == "0" and i2 < n and text[i2] == "'":
                ch, i3 = _read_char_escape(text, i2 + 1)
                tokens.append(Token("int", ord(ch), start, had_space))
                i = i3
                had_space = False
                continue
            # 0x / 0o / 0b
            if text[start:i2] == "0" and i2 < n and text[i2] in "xXoObB":
                base_char = text[i2]
                base = {"x": 16, "o": 8, "b": 2}[base_char.lower()]
                j = i2 + 1
                digits = "0123456789abcdefABCDEF" if base == 16 else ("01234567" if base == 8 else "01")
                k = j
                while k < n and text[k] in digits:
                    k += 1
                tokens.append(Token("int", int(text[j:k], base), start, had_space))
                i = k
                had_space = False
                continue
            text_val = text[start:i2]
            tokens.append(Token("float" if is_float else "int",
                                 float(text_val) if is_float else int(text_val),
                                 start, had_space))
            i = i2
            had_space = False
            continue

        if c == "_" or c.isalpha():
            i2 = i
            while i2 < n and (text[i2].isalnum() or text[i2] == "_"):
                i2 += 1
            word = text[start:i2]
            if c == "_" or c.isupper():
                tokens.append(Token("var", word, start, had_space))
            else:
                tokens.append(Token("atom", word, start, had_space))
            i = i2
            had_space = False
            continue

        if c == "'":
            s, i2 = _read_quoted(text, i + 1, "'")
            tokens.append(Token("atom", s, start, had_space))
            i = i2
            had_space = False
            continue

        if c == '"':
            s, i2 = _read_quoted(text, i + 1, '"')
            tokens.append(Token("string", s, start, had_space))
            i = i2
            had_space = False
            continue

        if c in SOLO_CHARS:
            tokens.append(Token("punct", c, start, had_space))
            i += 1
            had_space = False
            continue

        if c in SYMBOL_CHARS:
            i2 = i
            while i2 < n and text[i2] in SYMBOL_CHARS:
                i2 += 1
            sym = text[start:i2]
            # A lone '.' followed by whitespace/EOF/% is the clause terminator.
            if sym == "." and (i2 >= n or text[i2] in " \t\r\n%" or i2 == n):
                tokens.append(Token("end", ".", start, had_space))
                i = i2
                had_space = False
                continue
            tokens.append(Token("atom", sym, start, had_space))
            i = i2
            had_space = False
            continue

        raise LexError(f"unexpected character {c!r} at position {i}")

    tokens.append(Token("eof", None, n, True))
    return tokens


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f",
            "v": "\v", "\\": "\\", "'": "'", '"': '"', "`": "`", "0": "\0"}


def _read_char_escape(text, i):
    """Read one (possibly escaped) character starting at i; used for 0'c."""
    if text[i] == "\\":
        return _read_escape(text, i + 1)
    if text[i] == "'" and i + 1 < len(text) and text[i + 1] == "'":
        return "'", i + 2
    return text[i], i + 1


def _read_escape(text, i):
    c = text[i]
    if c in _ESCAPES:
        return _ESCAPES[c], i + 1
    if c == "x":
        j = i + 1
        while j < len(text) and text[j] in "0123456789abcdefABCDEF":
            j += 1
        code = int(text[i + 1:j], 16)
        if j < len(text) and text[j] == "\\":
            j += 1
        return chr(code), j
    if c.isdigit():
        j = i
        while j < len(text) and text[j].isdigit():
            j += 1
        code = int(text[i:j], 8)
        if j < len(text) and text[j] == "\\":
            j += 1
        return chr(code), j
    return c, i + 1


def _read_quoted(text, i, quote):
    out = []
    n = len(text)
    while i < n:
        c = text[i]
        if c == quote:
            if i + 1 < n and text[i + 1] == quote:
                out.append(quote)
                i += 2
                continue
            return "".join(out), i + 1
        if c == "\\":
            if i + 1 < n and text[i + 1] == "\n":  # line continuation
                i += 2
                continue
            ch, i = _read_escape(text, i + 1)
            out.append(ch)
            continue
        out.append(c)
        i += 1
    raise LexError(f"unterminated quoted literal starting near {i}")
