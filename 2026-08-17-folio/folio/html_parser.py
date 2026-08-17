"""An HTML tokenizer + tree builder, built from scratch.

Not a transcription of the (enormous) HTML5 parsing algorithm -- this
implements the part of it that matters for real-world "tag soup" markup:
void elements, raw-text elements (script/style), comments, character
references, and the small set of implicit-close rules that keep documents
like `<ul><li>a<li>b</ul>` and `<p>a<p>b` from nesting incorrectly (which is
exactly what real browsers do, and what a naive stack-based parser gets
wrong). Mismatched/unclosed tags are recovered from rather than raising.
"""

from .dom import (
    Comment,
    Document,
    Element,
    Text,
    VOID_ELEMENTS,
    RAW_TEXT_ELEMENTS,
    ESCAPABLE_RAW_TEXT_ELEMENTS,
)
from .entities import decode_entities

# Tags that implicitly close an open <p> when they start (CSS-level block
# elements; this mirrors the HTML5 "have an element in button scope" check
# for <p>, approximated as "search the whole stack" -- adequate for the tag
# soup this parser needs to tolerate).
_P_CLOSERS = frozenset(
    [
        "address", "article", "aside", "blockquote", "details", "div", "dl",
        "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
        "h3", "h4", "h5", "h6", "header", "hr", "main", "menu", "nav", "ol",
        "p", "pre", "section", "table", "ul",
    ]
)

_TAG_NAME_RE_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
)


class Token:
    __slots__ = ("kind", "name", "attrs", "data", "self_closing")

    def __init__(self, kind, name=None, attrs=None, data=None, self_closing=False):
        self.kind = kind  # 'starttag' | 'endtag' | 'text' | 'comment' | 'doctype'
        self.name = name
        self.attrs = attrs
        self.data = data
        self.self_closing = self_closing


def tokenize(html):
    """Yield Token objects for `html`. A small hand-written state machine --
    not a regex soup -- so raw-text (script/style) handling can correctly
    switch modes mid-stream."""
    i = 0
    n = len(html)
    tokens = []

    def emit_text(s):
        if s:
            tokens.append(Token("text", data=decode_entities(s)))

    while i < n:
        lt = html.find("<", i)
        if lt == -1:
            emit_text(html[i:])
            break
        emit_text(html[i:lt])
        i = lt

        if html.startswith("<!--", i):
            end = html.find("-->", i + 4)
            if end == -1:
                tokens.append(Token("comment", data=html[i + 4 :]))
                i = n
            else:
                tokens.append(Token("comment", data=html[i + 4 : end]))
                i = end + 3
            continue

        if html[i : i + 2].lower() == "<!" and html[i : i + 9].upper().startswith("<!DOCTYPE"):
            end = html.find(">", i)
            end = n if end == -1 else end
            tokens.append(Token("doctype", data=html[i + 2 : end]))
            i = end + 1
            continue

        if html.startswith("<![CDATA[", i):
            end = html.find("]]>", i + 9)
            end = n if end == -1 else end
            i = end + 3 if end != n else n
            continue

        if i + 1 < n and html[i + 1] == "/":
            j = i + 2
            start = j
            while j < n and html[j] in _TAG_NAME_RE_CHARS:
                j += 1
            name = html[start:j].lower()
            close = html.find(">", j)
            i = (close + 1) if close != -1 else n
            if name:
                tokens.append(Token("endtag", name=name))
            continue

        if i + 1 < n and (html[i + 1].isalpha()):
            j = i + 1
            start = j
            while j < n and html[j] in _TAG_NAME_RE_CHARS:
                j += 1
            name = html[start:j].lower()
            attrs = {}
            self_closing = False
            while j < n:
                while j < n and html[j] in " \t\n\r\f":
                    j += 1
                if j >= n:
                    break
                if html[j] == ">":
                    j += 1
                    break
                if html[j] == "/" and j + 1 < n and html[j + 1] == ">":
                    self_closing = True
                    j += 2
                    break
                if html[j] == "/":
                    j += 1
                    continue
                astart = j
                while j < n and html[j] not in " \t\n\r\f=>/":
                    j += 1
                aname = html[astart:j].lower()
                if not aname:
                    j += 1
                    continue
                while j < n and html[j] in " \t\n\r\f":
                    j += 1
                aval = ""
                if j < n and html[j] == "=":
                    j += 1
                    while j < n and html[j] in " \t\n\r\f":
                        j += 1
                    if j < n and html[j] in "\"'":
                        q = html[j]
                        j += 1
                        vstart = j
                        end_q = html.find(q, j)
                        end_q = n if end_q == -1 else end_q
                        aval = html[vstart:end_q]
                        j = end_q + 1 if end_q != n else n
                    else:
                        vstart = j
                        while j < n and html[j] not in " \t\n\r\f>":
                            j += 1
                        aval = html[vstart:j]
                if aname not in attrs:
                    attrs[aname] = decode_entities(aval)
            tokens.append(Token("starttag", name=name, attrs=attrs, self_closing=self_closing))
            i = j

            if name in RAW_TEXT_ELEMENTS and not self_closing:
                end_tag = "</" + name
                idx = html.lower().find(end_tag, i)
                if idx == -1:
                    tokens.append(Token("text", data=html[i:]))
                    i = n
                else:
                    tokens.append(Token("text", data=html[i:idx]))
                    close_gt = html.find(">", idx)
                    i = (close_gt + 1) if close_gt != -1 else n
                    tokens.append(Token("endtag", name=name))
            elif name in ESCAPABLE_RAW_TEXT_ELEMENTS and not self_closing:
                end_tag = "</" + name
                idx = html.lower().find(end_tag, i)
                if idx == -1:
                    emit_text(html[i:])
                    i = n
                else:
                    emit_text(html[i:idx])
                    close_gt = html.find(">", idx)
                    i = (close_gt + 1) if close_gt != -1 else n
                    tokens.append(Token("endtag", name=name))
            continue

        # A bare '<' not followed by a tag-ish thing: literal text.
        emit_text("<")
        i += 1

    return tokens


class TreeBuilder:
    def __init__(self):
        self.document = Document()
        self.stack = [self.document]

    def top(self):
        return self.stack[-1]

    def _close_through(self, tag_name):
        """Pop the stack up through (and including) the nearest open element
        named `tag_name`, if one exists on the stack. No-op otherwise."""
        for idx in range(len(self.stack) - 1, 0, -1):
            if self.stack[idx].is_element and self.stack[idx].tag == tag_name:
                del self.stack[idx:]
                return True
        return False

    def _has_open(self, tag_name):
        return any(el.is_element and el.tag == tag_name for el in self.stack)

    def start_tag(self, name, attrs, self_closing):
        if name == "p" and self._has_open("p"):
            self._close_through("p")
        elif name == "li" and self._has_open("li"):
            self._close_through("li")
        elif name in ("dt", "dd") and (self._has_open("dt") or self._has_open("dd")):
            for t in ("dt", "dd"):
                if self._has_open(t):
                    self._close_through(t)
                    break
        elif name == "tr" and self._has_open("tr"):
            self._close_through("tr")
        elif name in ("td", "th") and (self._has_open("td") or self._has_open("th")):
            for t in ("td", "th"):
                if self._has_open(t):
                    self._close_through(t)
                    break
        elif name == "option" and self._has_open("option"):
            self._close_through("option")

        el = Element(name, attrs)
        self.top().append_child(el)
        is_void = name in VOID_ELEMENTS or self_closing
        if not is_void:
            self.stack.append(el)

    def end_tag(self, name):
        self._close_through(name)

    def text(self, data):
        if not data:
            return
        self.top().append_child(Text(data))

    def comment(self, data):
        self.top().append_child(Comment(data))


def parse_html(html):
    """Parse an HTML document/fragment string into a DOM tree. Returns the
    Document root."""
    builder = TreeBuilder()
    for tok in tokenize(html):
        if tok.kind == "starttag":
            builder.start_tag(tok.name, tok.attrs, tok.self_closing)
        elif tok.kind == "endtag":
            builder.end_tag(tok.name)
        elif tok.kind == "text":
            builder.text(tok.data)
        elif tok.kind == "comment":
            builder.comment(tok.data)
        # doctype tokens are recognized and discarded, same as a real engine
        # discards a well-formed one after quirks-mode detection (Folio has
        # only one rendering mode, so there is nothing further to do).
    return builder.document
