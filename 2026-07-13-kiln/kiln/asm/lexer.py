"""Tokenizer for `.kwat`, a WAT-inspired s-expression text format. Supports
line comments (`;;`), block comments (`(; ... ;)`), parens, string literals
(used for export names and data-segment bytes) and bare atoms (symbols,
`$names`, numbers, instruction mnemonics)."""


class Token:
    __slots__ = ("kind", "text", "line")

    def __init__(self, kind, text, line):
        self.kind = kind  # 'lparen' | 'rparen' | 'atom' | 'string'
        self.text = text
        self.line = line

    def __repr__(self):
        return f"Token({self.kind}, {self.text!r})"


def tokenize(src):
    tokens = []
    i = 0
    n = len(src)
    line = 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c.isspace():
            i += 1
            continue
        if src.startswith(";;", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("(;", i):
            depth = 1
            i += 2
            while i < n and depth > 0:
                if src.startswith("(;", i):
                    depth += 1
                    i += 2
                elif src.startswith(";)", i):
                    depth -= 1
                    i += 2
                else:
                    if src[i] == "\n":
                        line += 1
                    i += 1
            continue
        if c == "(":
            tokens.append(Token("lparen", "(", line))
            i += 1
            continue
        if c == ")":
            tokens.append(Token("rparen", ")", line))
            i += 1
            continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n and src[j] != '"':
                if src[j] == "\\" and j + 1 < n:
                    esc = src[j + 1]
                    mapping = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
                    if esc in mapping:
                        buf.append(mapping[esc])
                        j += 2
                        continue
                    if esc == "0" or (esc in "0123456789abcdefABCDEF" and j + 2 < n):
                        hexpair = src[j + 1:j + 3]
                        try:
                            buf.append(chr(int(hexpair, 16)))
                            j += 3
                            continue
                        except ValueError:
                            pass
                    buf.append(esc)
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            if j >= n:
                raise SyntaxError(f"line {line}: unterminated string literal")
            tokens.append(Token("string", "".join(buf), line))
            i = j + 1
            continue
        j = i
        while j < n and not src[j].isspace() and src[j] not in "()\"":
            j += 1
        tokens.append(Token("atom", src[i:j], line))
        i = j
    return tokens
