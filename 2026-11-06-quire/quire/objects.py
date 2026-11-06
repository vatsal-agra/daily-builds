"""PDF object model. Dicts are plain dicts keyed by str (name without '/')."""


class Name(str):
    __slots__ = ()

    def __repr__(self):
        return "/" + str(self)


class Ref:
    __slots__ = ("num", "gen")

    def __init__(self, num, gen=0):
        self.num, self.gen = num, gen

    def __eq__(self, o):
        return isinstance(o, Ref) and (o.num, o.gen) == (self.num, self.gen)

    def __hash__(self):
        return hash((self.num, self.gen))

    def __repr__(self):
        return f"{self.num} {self.gen} R"


class PdfString(bytes):
    """A PDF string (bytes) — distinct type so we can tell it from other bytes."""
    __slots__ = ()


class Keyword(str):
    __slots__ = ()


class Stream:
    """A stream object: dictionary + raw (still filtered, already decrypted) bytes."""

    def __init__(self, dict_, raw):
        self.dict = dict_
        self.raw = raw
        self._decoded = None

    def __repr__(self):
        return f"<Stream {len(self.raw)}B {self.dict.get('Filter')}>"
