"""Tokenizer and object parser for PDF syntax."""
import re
from .objects import Name, Ref, PdfString, Keyword

WS = b"\x00\t\n\x0c\r "
DELIM = b"()<>[]{}/%"
_REGULAR_END = re.compile(rb"[\x00\t\n\x0c\r ()<>\[\]{}/%]")
_NUM = re.compile(rb"^[+-]?(\d+\.?\d*|\.\d+)$")


class SyntaxErr(Exception):
    pass


class Punct(str):
    __slots__ = ()


class Lexer:
    def __init__(self, data, pos=0):
        self.data = data
        self.pos = pos

    # -- low level ---------------------------------------------------------
    def skip_ws(self):
        d, n, p = self.data, len(self.data), self.pos
        while p < n:
            c = d[p]
            if c in WS:
                p += 1
            elif c == 0x25:  # %
                while p < n and d[p] not in b"\r\n":
                    p += 1
            else:
                break
        self.pos = p

    def next_token(self):
        """Return a token: Keyword, Name, PdfString, int/float, or one of the
        punctuation strings '[', ']', '<<', '>>', '{', '}'. None at EOF."""
        self.skip_ws()
        d, p = self.data, self.pos
        if p >= len(d):
            return None
        c = d[p]
        if c == 0x2F:  # /
            return self._name()
        if c == 0x28:  # (
            return self._lit_string()
        if c == 0x3C:  # <
            if d[p + 1:p + 2] == b"<":
                self.pos += 2
                return Punct("<<")
            return self._hex_string()
        if c == 0x3E:
            if d[p + 1:p + 2] == b">":
                self.pos += 2
                return Punct(">>")
            self.pos += 1
            return Keyword(">")
        if c in b"[]{}":
            self.pos += 1
            return Punct(chr(c))
        if c == 0x29:
            self.pos += 1
            return Keyword(")")
        m = _REGULAR_END.search(d, p)
        e = m.start() if m else len(d)
        if e == p:
            e = p + 1
        tok = d[p:e]
        self.pos = e
        if _NUM.match(tok):
            if b"." in tok:
                return float(tok)
            return int(tok)
        # tolerate things like "--5" or "5-3" produced by buggy writers
        if re.match(rb"^[+-]+\d", tok):
            try:
                return int(re.sub(rb"^[+-]+", b"", tok).split(b"-")[0]) * (-1 if tok.startswith(b"-") else 1)
            except ValueError:
                pass
        return Keyword(tok.decode("latin-1"))

    def _name(self):
        d, p = self.data, self.pos + 1
        m = _REGULAR_END.search(d, p)
        e = m.start() if m else len(d)
        raw = d[p:e]
        self.pos = e
        if b"#" in raw:
            raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda m: bytes([int(m.group(1), 16)]), raw)
        try:
            return Name(raw.decode("utf-8"))
        except UnicodeDecodeError:
            return Name(raw.decode("latin-1"))

    def _lit_string(self):
        d, p = self.data, self.pos + 1
        out = bytearray()
        depth = 1
        n = len(d)
        while p < n:
            c = d[p]
            if c == 0x5C:  # backslash
                p += 1
                if p >= n:
                    break
                c = d[p]
                esc = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12, 0x28: 40, 0x29: 41, 0x5C: 92}
                if c in esc:
                    out.append(esc[c])
                    p += 1
                elif 0x30 <= c <= 0x37:
                    v = 0
                    k = 0
                    while k < 3 and p < n and 0x30 <= d[p] <= 0x37:
                        v = v * 8 + d[p] - 0x30
                        p += 1
                        k += 1
                    out.append(v & 0xFF)
                elif c == 13:  # line continuation
                    p += 1
                    if p < n and d[p] == 10:
                        p += 1
                elif c == 10:
                    p += 1
                else:
                    out.append(c)
                    p += 1
                continue
            if c == 0x28:
                depth += 1
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    p += 1
                    break
            if c == 13:  # normalise EOL inside strings to \n
                out.append(10)
                p += 1
                if p < n and d[p] == 10:
                    p += 1
                continue
            out.append(c)
            p += 1
        self.pos = p
        return PdfString(bytes(out))

    def _hex_string(self):
        d = self.data
        e = d.find(b">", self.pos)
        if e < 0:
            e = len(d)
        body = re.sub(rb"[^0-9A-Fa-f]", b"", d[self.pos + 1:e])
        if len(body) % 2:
            body += b"0"
        self.pos = e + 1
        return PdfString(bytes.fromhex(body.decode()))

    # -- objects -----------------------------------------------------------
    def parse_object(self, tok=None, allow_refs=True):
        """Parse one object. Returns the object; Keywords (operators) are
        returned as Keyword instances so content-stream code can reuse this."""
        if tok is None:
            tok = self.next_token()
        if tok is None:
            raise SyntaxErr("unexpected EOF")
        if isinstance(tok, Punct) and tok == "[":
            arr = []
            while True:
                t = self.next_token()
                if t is None:
                    raise SyntaxErr("unterminated array")
                if isinstance(t, Punct) and t == "]":
                    return arr
                arr.append(self.parse_object(t, allow_refs))
        if isinstance(tok, Punct) and tok == "<<":
            return self._dict(allow_refs)
        if isinstance(tok, int) and not isinstance(tok, bool) and allow_refs and tok >= 0:
            save = self.pos
            t2 = self.next_token()
            if isinstance(t2, int) and not isinstance(t2, bool) and t2 >= 0:
                t3 = self.next_token()
                if isinstance(t3, Keyword) and t3 == "R":
                    return Ref(tok, t2)
            self.pos = save
            return tok
        if isinstance(tok, Keyword):
            if tok == "true":
                return True
            if tok == "false":
                return False
            if tok == "null":
                return None
        return tok

    def _dict(self, allow_refs=True):
        out = {}
        while True:
            t = self.next_token()
            if t is None:
                raise SyntaxErr("unterminated dict")
            if isinstance(t, Punct) and t == ">>":
                return out
            if not isinstance(t, Name):
                if isinstance(t, Keyword) and t in ("endobj", "stream"):
                    self.pos -= len(t)
                    return out  # tolerate truncated dict
                continue  # skip garbage
            vt = self.next_token()
            if isinstance(vt, Punct) and vt == ">>":
                out[str(t)] = None
                return out
            out[str(t)] = self.parse_object(vt, allow_refs)
