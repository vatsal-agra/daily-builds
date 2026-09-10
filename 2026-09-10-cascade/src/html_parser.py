"""HTML tree construction: token stream -> DOM tree.

Implements the practically-important parts of the real HTML5 tree
construction algorithm: implicit <html>/<head>/<body>, void elements never
getting a children list to close, the common auto-close rules (a new <p>
closes an open <p>, a new <li> closes an open <li>, table row/cell rules),
and forgiving recovery from stray/mismatched end tags (ignored if there is
no matching open element on the stack, rather than raising).
"""

from dom import AUTO_CLOSE, VOID_ELEMENTS, Comment, Document, Element, Text
from html_tokenizer import tokenize

# Content that implicitly belongs in <head> if seen before any body content.
HEAD_ELEMENTS = {"title", "meta", "link", "style", "base", "script"}


class HTMLParser:
    def __init__(self):
        self.document = Document()
        self.html = Element("html")
        self.head = Element("head")
        self.body = Element("body")
        self.document.append_child(self.html)
        self.html.append_child(self.head)
        self.html.append_child(self.body)
        # stack of open elements; the DOM insertion point is stack[-1].
        # Parsing starts inside the implicit <head> until the first
        # non-head-ish content is seen (see _maybe_leave_head*).
        self.stack = [self.head]
        self._in_head_phase = True

    def _current(self):
        return self.stack[-1]

    def _open_tags(self):
        return [e.tag for e in self.stack]

    def _close_until(self, tag):
        """Pop the stack until (and including) an element with this tag,
        if one is open. No-op if not found."""
        if tag not in self._open_tags():
            return
        while self.stack[-1].tag != tag:
            self.stack.pop()
        self.stack.pop()

    def _maybe_leave_head(self, tag):
        if self._in_head_phase and tag not in HEAD_ELEMENTS and tag not in (
                "html", "head"):
            self._in_head_phase = False
            if self.stack[-1] is self.head:
                self.stack.pop()
                self.stack.append(self.body)

    def parse(self, html):
        for tok in tokenize(html):
            self._handle(tok)
        return self.document

    def _handle(self, tok):
        if tok.kind == "doctype":
            return
        if tok.kind == "comment":
            self._current().append_child(Comment(tok.data))
            return
        if tok.kind == "text":
            if tok.data == "" :
                return
            # Whitespace-only text at the very top (between </head> and
            # <body>-ish positions) is still meaningful for inline layout,
            # so we keep it -- real browsers do too, layout collapses it.
            self._maybe_leave_head_for_text(tok.data)
            self._current().append_child(Text(tok.data))
            return
        if tok.kind == "starttag":
            self._start_tag(tok)
            return
        if tok.kind == "endtag":
            self._end_tag(tok)
            return

    def _maybe_leave_head_for_text(self, data):
        if self._in_head_phase and data.strip():
            self._in_head_phase = False
            if self.stack[-1] is self.head:
                self.stack.pop()
                self.stack.append(self.body)

    def _start_tag(self, tok):
        tag = tok.name

        if tag == "html":
            self.html.attrs.update(tok.attrs)
            return
        if tag == "head":
            return
        if tag == "body":
            self.body.attrs.update(tok.attrs)
            self._in_head_phase = False
            if self.stack[-1] is self.head:
                self.stack.pop()
                self.stack.append(self.body)
            return

        self._maybe_leave_head(tag)

        # Auto-close rule: a new tag of a kind listed in AUTO_CLOSE[open]
        # implicitly closes that open element (e.g. new <li> closes open
        # <li>). Walk up as many levels as apply -- e.g. a new <tr> must
        # close both a still-open <td> AND the previous <tr>, not just one.
        while (len(self.stack) > 1 and isinstance(self.stack[-1], Element)
               and self.stack[-1].tag in AUTO_CLOSE and tag in AUTO_CLOSE[self.stack[-1].tag]):
            self.stack.pop()

        el = Element(tag, dict(tok.attrs))
        self.stack[-1].append_child(el)
        if not (tok.self_closing or tag in VOID_ELEMENTS):
            self.stack.append(el)

    def _end_tag(self, tok):
        tag = tok.name
        if tag in ("html", "body", "head"):
            return
        self._close_until(tag)


def parse_html(html):
    return HTMLParser().parse(html)
