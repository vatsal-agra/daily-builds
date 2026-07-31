"""Tokenizer for formula text (everything after a leading `=`)."""


class Token:
    __slots__ = ("type", "text", "pos")

    def __init__(self, type_, text, pos):
        self.type = type_
        self.text = text
        self.pos = pos

    def __repr__(self):
        return f"Token({self.type}, {self.text!r}, @{self.pos})"


class LexError(Exception):
    def __init__(self, message, pos):
        self.pos = pos
        super().__init__(f"{message} (at position {pos})")


_SIMPLE = {
    "+": "PLUS", "-": "MINUS", "*": "STAR", "/": "SLASH", "^": "CARET",
    "&": "AMP", "%": "PERCENT", "(": "LPAREN", ")": "RPAREN",
    ",": "COMMA", ":": "COLON", "!": "BANG",
}


def tokenize(text):
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == '"':
            start = i
            i += 1
            buf = []
            while True:
                if i >= n:
                    raise LexError("unterminated string literal", start)
                c = text[i]
                if c == "\\" and i + 1 < n and text[i + 1] in ('"', "\\"):
                    buf.append(text[i + 1])
                    i += 2
                    continue
                if c == '"':
                    i += 1
                    break
                buf.append(c)
                i += 1
            tokens.append(Token("STRING", "".join(buf), start))
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and text[i + 1].isdigit()):
            start = i
            j = i
            seen_dot = False
            while j < n and (text[j].isdigit() or (text[j] == "." and not seen_dot)):
                if text[j] == ".":
                    seen_dot = True
                j += 1
            if j < n and text[j] in ("e", "E"):
                k = j + 1
                if k < n and text[k] in ("+", "-"):
                    k += 1
                if k < n and text[k].isdigit():
                    j = k
                    while j < n and text[j].isdigit():
                        j += 1
            tokens.append(Token("NUMBER", text[start:j], start))
            i = j
            continue
        if ch.isalpha() or ch == "_" or ch == "$":
            start = i
            j = i
            while j < n and (text[j].isalnum() or text[j] in ("_", "$", ".")):
                j += 1
            tokens.append(Token("IDENT", text[start:j], start))
            i = j
            continue
        if ch == "<":
            if text[i:i + 2] == "<=":
                tokens.append(Token("LE", "<=", i)); i += 2; continue
            if text[i:i + 2] == "<>":
                tokens.append(Token("NE", "<>", i)); i += 2; continue
            tokens.append(Token("LT", "<", i)); i += 1; continue
        if ch == ">":
            if text[i:i + 2] == ">=":
                tokens.append(Token("GE", ">=", i)); i += 2; continue
            tokens.append(Token("GT", ">", i)); i += 1; continue
        if ch == "=":
            tokens.append(Token("EQ", "=", i)); i += 1; continue
        if ch in _SIMPLE:
            tokens.append(Token(_SIMPLE[ch], ch, i))
            i += 1
            continue
        raise LexError(f"unexpected character {ch!r}", i)
    tokens.append(Token("EOF", "", n))
    return tokens
