"""A from-scratch HTML tokenizer + tree-construction parser.

This is a deliberately-scoped subset of the HTML5 parsing algorithm (WHATWG
spec), not `html.parser`-with-extra-steps: a hand-written character-by-
character state walk builds tokens, and a stack-of-open-elements tree
builder consumes them, including the parts of real-world HTML that make
"just split on tags" wrong:

- void elements (`<br>`, `<img>`, ...) never get pushed onto the open stack
- elements with optional end tags (`<p>`, `<li>`, `<dd>`/`<dt>`, `<tr>`,
  `<td>`/`<th>`, `<option>`) auto-close per a simplified version of the
  spec's "implied end tag" rules when a sibling of the right kind opens
- an end tag closes everything above (and including) its matching start
  tag on the stack, so `<b><i>x</b>` still produces a sane tree
- unclosed elements at end-of-input are implicitly closed
- `<script>`/`<style>` contents are consumed verbatim (raw text), so a
  `</div>` inside a `<script>` string literal does not close a `<div>`
- comments and quoted/unquoted/missing attribute values all parse

Named-entity/character-reference decoding reuses the stdlib `html.unescape`
(string processing, not tree construction or tag matching -- the actual
"from scratch" content of this module).
"""

import html as _html_entities

VOID_ELEMENTS = {
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr',
}

RAWTEXT_ELEMENTS = {'script', 'style'}

# Simplified "implied end tag" rule: AUTO_CLOSE[T] is the set of tag names
# whose *opening* auto-closes an innermost-open element named T. E.g.
# AUTO_CLOSE['p'] contains 'div', so opening <div> while a <p> is the
# current innermost open element closes that <p> first -- but opening <p>
# never closes an ancestor <div>, since 'p' is not a key that maps to 'div'.
AUTO_CLOSE = {
    'p': {
        'p', 'div', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'table', 'section', 'article', 'header', 'footer', 'blockquote',
        'pre', 'form',
    },
    'li': {'li'},
    'dt': {'dt', 'dd'},
    'dd': {'dt', 'dd'},
    'tr': {'tr'},
    # A new row also implicitly ends the current row's cell -- the
    # AUTO_CLOSE loop is a `while`, so opening <tr> pops an open <td>/<th>
    # first, then (with the cell gone) sees the open <tr> underneath it
    # and pops that too, landing the new <tr> as a sibling, not a nephew.
    'td': {'td', 'th', 'tr'},
    'th': {'td', 'th', 'tr'},
    'option': {'option'},
}


class Node:
    __slots__ = ('node_type', 'name', 'attrs', 'data', 'children', 'parent')

    def __init__(self, node_type, name=None, attrs=None, data=None):
        self.node_type = node_type  # 'document' | 'element' | 'text' | 'comment'
        self.name = name
        self.attrs = attrs or {}
        self.data = data
        self.children = []
        self.parent = None

    def append(self, child):
        child.parent = self
        self.children.append(child)

    def find_all(self, tag_name):
        out = []
        for child in self.children:
            if child.node_type == 'element' and child.name == tag_name:
                out.append(child)
            out.extend(child.find_all(tag_name))
        return out

    def text_content(self):
        if self.node_type == 'text':
            return self.data
        return ''.join(c.text_content() for c in self.children)

    def to_debug_string(self, depth=0):
        pad = '  ' * depth
        if self.node_type == 'text':
            snippet = self.data.strip()
            if not snippet:
                return ''
            return f'{pad}#text {snippet[:40]!r}\n'
        if self.node_type == 'comment':
            return f'{pad}<!-- {self.data.strip()[:40]} -->\n'
        if self.node_type == 'document':
            name = '#document'
        else:
            attrs = ''.join(f' {k}="{v}"' for k, v in self.attrs.items())
            name = f'<{self.name}{attrs}>'
        out = f'{pad}{name}\n'
        for child in self.children:
            out += child.to_debug_string(depth + 1)
        return out


def _tokenize(text):
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c != '<':
            j = text.find('<', i)
            if j == -1:
                j = n
            tokens.append({'type': 'text', 'data': _html_entities.unescape(text[i:j])})
            i = j
            continue

        if text.startswith('<!--', i):
            end = text.find('-->', i + 4)
            if end == -1:
                tokens.append({'type': 'comment', 'data': text[i + 4:]})
                i = n
            else:
                tokens.append({'type': 'comment', 'data': text[i + 4:end]})
                i = end + 3
            continue

        if text.startswith('<!', i):
            end = text.find('>', i)
            i = n if end == -1 else end + 1
            tokens.append({'type': 'doctype'})
            continue

        if text.startswith('</', i):
            end = text.find('>', i)
            if end == -1:
                name = text[i + 2:].strip()
                i = n
            else:
                name = text[i + 2:end].strip()
                i = end + 1
            if name:
                tokens.append({'type': 'end_tag', 'name': name.split()[0].lower()})
            continue

        if i + 1 < n and (text[i + 1].isalpha()):
            name, attrs, self_closing, i = _parse_start_tag(text, i)
            tokens.append({
                'type': 'start_tag', 'name': name, 'attrs': attrs,
                'self_closing': self_closing,
            })
            if name in RAWTEXT_ELEMENTS and not self_closing:
                close_marker = f'</{name}'
                lowered = text.lower()
                end = lowered.find(close_marker, i)
                if end == -1:
                    raw = text[i:]
                    i = n
                else:
                    raw = text[i:end]
                    close_end = text.find('>', end)
                    i = n if close_end == -1 else close_end + 1
                if raw:
                    tokens.append({'type': 'text', 'data': raw})
                tokens.append({'type': 'end_tag', 'name': name})
            continue

        # A lone '<' that isn't a recognizable tag/comment/doctype -- treat
        # as literal text (e.g. "1 < 2 and 3 > 1").
        tokens.append({'type': 'text', 'data': '<'})
        i += 1

    return tokens


def _parse_start_tag(text, i):
    n = len(text)
    j = i + 1
    name_start = j
    while j < n and (text[j].isalnum() or text[j] in '-_'):
        j += 1
    name = text[name_start:j].lower()

    attrs = {}
    self_closing = False
    while j < n and text[j] != '>':
        while j < n and text[j].isspace():
            j += 1
        if j >= n or text[j] == '>':
            break
        if text[j] == '/':
            if j + 1 < n and text[j + 1] == '>':
                self_closing = True
                j += 1
            else:
                j += 1
            continue

        attr_start = j
        while j < n and text[j] not in '=/> \t\n\r':
            j += 1
        attr_name = text[attr_start:j].lower()
        if not attr_name:
            j += 1
            continue

        while j < n and text[j].isspace():
            j += 1

        value = ''
        if j < n and text[j] == '=':
            j += 1
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j] in '"\'':
                quote = text[j]
                j += 1
                val_start = j
                while j < n and text[j] != quote:
                    j += 1
                value = _html_entities.unescape(text[val_start:j])
                if j < n:
                    j += 1
            else:
                val_start = j
                while (j < n and not text[j].isspace() and text[j] != '>'
                       and not (text[j] == '/' and j + 1 < n and text[j + 1] == '>')):
                    j += 1
                value = _html_entities.unescape(text[val_start:j])
        attrs[attr_name] = value

    if j < n and text[j] == '>':
        j += 1
    return name, attrs, self_closing, j


def _build_tree(tokens):
    document = Node('document')
    stack = [document]

    def top():
        return stack[-1]

    for tok in tokens:
        kind = tok['type']

        if kind == 'doctype':
            continue

        if kind == 'comment':
            top().append(Node('comment', data=tok['data']))
            continue

        if kind == 'text':
            if tok['data'] == '':
                continue
            siblings = top().children
            if siblings and siblings[-1].node_type == 'text':
                siblings[-1].data += tok['data']
            else:
                top().append(Node('text', data=tok['data']))
            continue

        if kind == 'start_tag':
            name = tok['name']
            while len(stack) > 1 and name in AUTO_CLOSE.get(stack[-1].name, ()):
                stack.pop()
            node = Node('element', name=name, attrs=tok['attrs'])
            top().append(node)
            if name not in VOID_ELEMENTS and not tok['self_closing']:
                stack.append(node)
            continue

        if kind == 'end_tag':
            name = tok['name']
            for idx in range(len(stack) - 1, 0, -1):
                if stack[idx].name == name:
                    del stack[idx:]
                    break
            # A stray end tag with no matching open element is ignored,
            # matching the spec's "parse error, ignore the token" behavior.
            continue

    return document


def parse(html_text):
    """Parse an HTML document/fragment string into a DOM tree, returning
    the synthetic '#document' root Node."""
    return _build_tree(_tokenize(html_text))
