"""A tolerant, from-scratch HTML tokenizer + tree builder.

This is not a spec-complete HTML5 parser (no full "tree construction
insertion modes" state machine) but it does the things that make real-world
HTML parseable instead of merely well-formed XML: it tolerates unclosed
`<p>`/`<li>`-style elements via an implied-end-tag table, treats a known set
of elements as void, and never raises on malformed input — worst case it
degrades gracefully rather than crashing the whole pipeline.
"""

import re

from .dom import (
    Comment,
    Document,
    Element,
    IMPLIED_END_TAGS,
    P_CLOSING_TAGS,
    RAW_TEXT_ELEMENTS,
    Text,
    VOID_ELEMENTS,
)

ENTITIES = {
    "amp": "&",
    "lt": "<",
    "gt": ">",
    "quot": '"',
    "apos": "'",
    "nbsp": " ",
    "copy": "©",
    "mdash": "—",
    "ndash": "–",
    "hellip": "…",
}

_ENTITY_RE = re.compile(r"&(#x[0-9a-fA-F]+|#[0-9]+|[a-zA-Z][a-zA-Z0-9]*);?")


def unescape_entities(text):
    def repl(m):
        body = m.group(1)
        try:
            if body.startswith("#x") or body.startswith("#X"):
                return chr(int(body[2:], 16))
            if body.startswith("#"):
                return chr(int(body[1:]))
            if body in ENTITIES:
                return ENTITIES[body]
        except (ValueError, OverflowError):
            pass
        return m.group(0)

    return _ENTITY_RE.sub(repl, text)


class Token:
    __slots__ = ("kind", "data", "attrs", "self_closing")

    def __init__(self, kind, data=None, attrs=None, self_closing=False):
        self.kind = kind  # 'start', 'end', 'text', 'comment', 'doctype'
        self.data = data
        self.attrs = attrs
        self.self_closing = self_closing


_TAG_NAME_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9:-]*")
_ATTR_RE = re.compile(
    r"""\s*([^\s"'>/=]+)(?:\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?"""
)


def tokenize(html):
    """Yield Token objects from raw HTML text."""
    i = 0
    n = len(html)
    while i < n:
        if html.startswith("<!--", i):
            end = html.find("-->", i + 4)
            if end == -1:
                yield Token("comment", html[i + 4:])
                i = n
            else:
                yield Token("comment", html[i + 4:end])
                i = end + 3
            continue

        if html.startswith("<!", i):
            end = html.find(">", i)
            end = n if end == -1 else end
            yield Token("doctype", html[i + 2:end])
            i = end + 1
            continue

        if html[i] == "<" and i + 1 < n and (html[i + 1].isalpha()):
            m = _TAG_NAME_RE.match(html, i + 1)
            tag = m.group(0).lower()
            j = m.end()
            attrs = {}
            while True:
                am = _ATTR_RE.match(html, j)
                if not am:
                    break
                # Stop if we've hit the closing '>' or a stray '/'.
                rest = html[j:am.end()]
                if rest.strip() in ("/", ""):
                    break
                name = am.group(1)
                if name in ("/", ""):
                    j = am.end()
                    continue
                value = am.group(3)
                if value is None:
                    value = am.group(4)
                if value is None:
                    value = am.group(5)
                if value is None:
                    value = ""
                attrs[name.lower()] = unescape_entities(value)
                j = am.end()
            self_closing = False
            k = html.find(">", j)
            if k == -1:
                k = n
            if html[j:k].rstrip().endswith("/"):
                self_closing = True
            i = k + 1

            if tag in RAW_TEXT_ELEMENTS and not self_closing:
                close = f"</{tag}"
                idx = html.lower().find(close, i)
                if idx == -1:
                    raw = html[i:]
                    i = n
                else:
                    raw = html[i:idx]
                    end_gt = html.find(">", idx)
                    i = (end_gt + 1) if end_gt != -1 else n
                yield Token("start", tag, attrs, self_closing)
                if raw:
                    yield Token("text", raw)
                yield Token("end", tag)
                continue

            yield Token("start", tag, attrs, self_closing)
            continue

        if html.startswith("</", i):
            m = _TAG_NAME_RE.match(html, i + 2)
            if m:
                tag = m.group(0).lower()
                end = html.find(">", m.end())
                i = (end + 1) if end != -1 else n
                yield Token("end", tag)
            else:
                i += 2
            continue

        # A '<' that didn't match any tag/comment/doctype/close-tag shape
        # above (e.g. "<3d>", "< span>", a lone trailing "<") is not the
        # start of anything real -- emit it as one literal character so we
        # always make forward progress, instead of re-finding the same '<'
        # at the same position forever.
        if html[i] == "<":
            yield Token("text", "<")
            i += 1
            continue

        # Plain text run up to the next '<'.
        next_lt = html.find("<", i)
        if next_lt == -1:
            next_lt = n
        text = html[i:next_lt]
        if text:
            yield Token("text", unescape_entities(text))
        i = next_lt


class TreeBuilder:
    """Turns a token stream into a DOM tree, tolerating common mistakes."""

    def __init__(self):
        self.document = Document()
        self.stack = [self.document]

    def _top(self):
        return self.stack[-1]

    def _open_tags(self):
        return [n.tag for n in self.stack[1:]]

    def close_until(self, tag):
        """Pop the stack until (and including) an element with this tag."""
        for idx in range(len(self.stack) - 1, 0, -1):
            if self.stack[idx].tag == tag:
                del self.stack[idx:]
                return True
        return False

    def start_tag(self, tag, attrs, self_closing):
        implied = IMPLIED_END_TAGS.get(tag)
        if implied:
            top = self._top()
            if isinstance(top, Element) and top.tag in implied:
                self.stack.pop()
        elif tag in P_CLOSING_TAGS and any(
            isinstance(n, Element) and n.tag == "p" for n in self.stack
        ):
            self.close_until("p")

        el = Element(tag, attrs)
        el.parent = self._top()
        self._top().children.append(el)
        if tag not in VOID_ELEMENTS and not self_closing:
            self.stack.append(el)

    def end_tag(self, tag):
        if tag in VOID_ELEMENTS:
            return
        self.close_until(tag)

    def text(self, data):
        if not data:
            return
        node = Text(data)
        node.parent = self._top()
        self._top().children.append(node)

    def comment(self, data):
        node = Comment(data)
        node.parent = self._top()
        self._top().children.append(node)

    def build(self, html):
        for tok in tokenize(html):
            if tok.kind == "start":
                self.start_tag(tok.data, tok.attrs, tok.self_closing)
            elif tok.kind == "end":
                self.end_tag(tok.data)
            elif tok.kind == "text":
                self.text(tok.data)
            elif tok.kind == "comment":
                self.comment(tok.data)
            # doctype tokens are parsed but not represented in the tree.
        return self.document


def parse_html(html):
    """Parse an HTML document string into a Document (DOM tree) root."""
    return TreeBuilder().build(html)
