"""A from-scratch CSS tokenizer + parser: stylesheet -> selectors +
declarations, plus selector matching and CSS specificity (a, b, c).

Supported selector grammar: `*`, `type`, `.class`, `#id`, `[attr]`,
`[attr=value]`, `[attr~=value]`, combinators ` ` (descendant) and `>`
(child), and the pseudo-classes `:first-child`, `:last-child`,
`:nth-child(n | odd | even | an+b)`. Unknown @-rules are skipped (their
block is consumed) rather than crashing the parser.
"""

import re


class CompoundSelector:
    __slots__ = ("type", "id", "classes", "attrs", "pseudos")

    def __init__(self):
        self.type = None      # None means universal
        self.id = None
        self.classes = []
        self.attrs = []       # list of (name, op, value) op in {'exists','=','~='}
        self.pseudos = []     # list of (name, arg)

    def specificity(self):
        a = 1 if self.id else 0
        b = len(self.classes) + len(self.attrs) + len(self.pseudos)
        c = 1 if (self.type and self.type != "*") else 0
        return (a, b, c)

    def matches(self, el):
        if self.type and self.type != "*" and el.tag != self.type:
            return False
        if self.id and el.id() != self.id:
            return False
        if self.classes:
            ec = el.classes()
            if not all(c in ec for c in self.classes):
                return False
        for name, op, val in self.attrs:
            av = el.attrs.get(name)
            if av is None:
                return False
            if op == "=" and av != val:
                return False
            if op == "~=" and val not in av.split():
                return False
        for name, arg in self.pseudos:
            if not _match_pseudo(el, name, arg):
                return False
        return True

    def __repr__(self):
        bits = [self.type or "*"]
        if self.id:
            bits.append("#" + self.id)
        bits += ["." + c for c in self.classes]
        return "".join(bits)


def _element_index(el, siblings_only_elements=True):
    parent = el.parent
    if parent is None:
        return 1
    idx = 1
    for c in parent.children:
        if c is el:
            return idx
        if c.__class__.__name__ == "Element":
            idx += 1
    return idx


def _match_pseudo(el, name, arg):
    from .dom import Element
    parent = el.parent
    siblings = [c for c in parent.children if isinstance(c, Element)] if parent else [el]
    pos = siblings.index(el) + 1 if el in siblings else 1
    if name == "first-child":
        return pos == 1
    if name == "last-child":
        return pos == len(siblings)
    if name == "nth-child":
        return _nth_match(arg, pos)
    return False


def _nth_match(arg, pos):
    arg = arg.strip().lower()
    if arg == "odd":
        return pos % 2 == 1
    if arg == "even":
        return pos % 2 == 0
    m = re.match(r"^([+-]?\d*)n(?:\s*([+-]\s*\d+))?$", arg)
    if m:
        a = m.group(1)
        a = 1 if a in ("", "+") else (-1 if a == "-" else int(a))
        b = int(m.group(2).replace(" ", "")) if m.group(2) else 0
        if a == 0:
            return pos == b
        k = (pos - b)
        return k % a == 0 and k // a >= 0
    try:
        return pos == int(arg)
    except ValueError:
        return False


class SelectorChain:
    """compounds[-1] is the target element; combinators[i] connects
    compounds[i] (ancestor side) to compounds[i+1]."""
    __slots__ = ("compounds", "combinators")

    def __init__(self, compounds, combinators):
        self.compounds = compounds
        self.combinators = combinators

    def specificity(self):
        a = b = c = 0
        for comp in self.compounds:
            sa, sb, sc = comp.specificity()
            a += sa
            b += sb
            c += sc
        return (a, b, c)

    def matches(self, el):
        if not self.compounds[-1].matches(el):
            return False
        cur = el
        for i in range(len(self.compounds) - 2, -1, -1):
            comb = self.combinators[i]
            comp = self.compounds[i]
            if comb == ">":
                cur = cur.parent
                if cur is None or not hasattr(cur, "tag") or not comp.matches(cur):
                    return False
            else:  # descendant
                anc = cur.parent
                found = None
                while anc is not None:
                    if hasattr(anc, "tag") and comp.matches(anc):
                        found = anc
                        break
                    anc = anc.parent
                if found is None:
                    return False
                cur = found
        return True

    def __repr__(self):
        parts = []
        for i, comp in enumerate(self.compounds):
            if i > 0:
                parts.append(f" {self.combinators[i-1]} " if self.combinators[i - 1] == ">" else " ")
            parts.append(repr(comp))
        return "".join(parts)


class Declaration:
    __slots__ = ("prop", "value", "important")

    def __init__(self, prop, value, important):
        self.prop = prop
        self.value = value
        self.important = important


class Rule:
    __slots__ = ("selector", "declarations", "order")

    def __init__(self, selector, declarations, order):
        self.selector = selector
        self.declarations = declarations
        self.order = order


class Stylesheet:
    def __init__(self, rules):
        self.rules = rules


# ---------------------------------------------------------------- tokenizer

_TOKEN_RE = re.compile(r"""
    (?P<comment>/\*.*?\*/)
  | (?P<ws>[ \t\r\n]+)
  | (?P<string>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
  | (?P<hash>\#[A-Za-z0-9_-]+)
  | (?P<dimension>[+-]?\d*\.?\d+[A-Za-z%]+)
  | (?P<number>[+-]?\d*\.?\d+)
  | (?P<ident>-?[A-Za-z_][A-Za-z0-9_-]*)
  | (?P<punct>[{}();:,>~+*.\[\]=@!])
""", re.VERBOSE | re.DOTALL)


def _tokenize(css):
    """Yields (kind, text) tokens, including 'ws' tokens — selector parsing
    needs real whitespace to tell a descendant combinator (`div .foo`) apart
    from a plain compound (`div.foo`); declaration parsing discards 'ws'."""
    for m in _TOKEN_RE.finditer(css):
        kind = m.lastgroup
        if kind == "comment":
            continue
        yield kind, m.group()


def parse_stylesheet(css):
    tokens = [t for t in _tokenize(css)]
    rules = []
    order = [0]
    i = 0
    n = len(tokens)

    def skip_at_rule(i):
        """Consume an unsupported @-rule: either `@foo ...;` or
        `@foo ... { ... }` (only depth-tracked at the top level, so a
        semicolon inside a nested block doesn't end it early)."""
        depth = 0
        while i < n:
            val = tokens[i][1]
            if val == "{":
                depth += 1
            elif val == "}":
                depth -= 1
                i += 1
                if depth <= 0:
                    return i
                continue
            elif val == ";" and depth == 0:
                return i + 1
            i += 1
        return i

    while i < n:
        kind, val = tokens[i]
        if kind == "ws":
            i += 1
            continue
        if val == "@":
            i = skip_at_rule(i)
            continue
        # collect selector tokens up to '{'
        sel_tokens = []
        while i < n and tokens[i][1] != "{":
            sel_tokens.append(tokens[i])
            i += 1
        if i >= n:
            break
        i += 1  # consume '{'
        decl_tokens = []
        depth = 1
        while i < n and depth > 0:
            k, v = tokens[i]
            if v == "{":
                depth += 1
            elif v == "}":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            if k != "ws":
                decl_tokens.append((k, v))
            i += 1
        declarations = _parse_declarations(decl_tokens)
        for chain in _parse_selector_list(sel_tokens):
            rules.append(Rule(chain, declarations, order[0]))
        order[0] += 1
    return Stylesheet(rules)


def _parse_declarations(tokens):
    decls = []
    i = 0
    n = len(tokens)
    while i < n:
        while i < n and tokens[i][1] in (";",):
            i += 1
        if i >= n:
            break
        if tokens[i][0] != "ident":
            i += 1
            continue
        prop = tokens[i][1].lower()
        i += 1
        if i < n and tokens[i][1] == ":":
            i += 1
        val_parts = []
        while i < n and tokens[i][1] != ";":
            val_parts.append(tokens[i])
            i += 1
        important = False
        if val_parts and val_parts[-1][1].lower() == "important":
            for j in range(len(val_parts) - 1, -1, -1):
                if val_parts[j][1] == "!":
                    important = True
                    val_parts = val_parts[:j]
                    break
        value = _join_value(val_parts)
        if prop:
            decls.append(Declaration(prop, value, important))
    return decls


def _join_value(tokens):
    out = []
    for k, v in tokens:
        if k == "string":
            v = v[1:-1]
        out.append(v)
    s = " ".join(out)
    s = re.sub(r"\s*,\s*", ", ", s)
    return s.strip()


def _parse_selector_list(tokens):
    # split on top-level ',' punct tokens
    groups = []
    cur = []
    for k, v in tokens:
        if v == ",":
            groups.append(cur)
            cur = []
        else:
            cur.append((k, v))
    if cur:
        groups.append(cur)
    chains = []
    for g in groups:
        chain = _parse_single_selector(g)
        if chain:
            chains.append(chain)
    return chains


def _parse_single_selector(tokens):
    """Parse one compound-selector chain (e.g. `div.foo > p.bar`). This
    needs the raw whitespace tokens to tell an implicit descendant
    combinator apart from a plain space inside e.g. `[attr = val]`, so the
    tokenizer's 'ws' tokens are consulted directly rather than pre-stripped."""
    return _parse_with_whitespace(tokens)


def _parse_with_whitespace(tokens):
    """Second pass selector parser that correctly distinguishes descendant
    (whitespace) vs child ('>') combinators using raw whitespace tokens."""
    compounds = []
    combinators = []
    cur = CompoundSelector()
    have_any = False
    saw_ws_since_compound = False
    i = 0
    n = len(tokens)

    def flush(combinator):
        """Close off `cur` as a finished compound, followed by `combinator`
        connecting it to whatever compound comes next. Always records the
        combinator (it describes the gap *after* this compound, not
        anything about compounds seen so far)."""
        nonlocal cur, have_any
        if have_any:
            compounds.append(cur)
            combinators.append(combinator)
        cur = CompoundSelector()
        have_any = False

    while i < n:
        k, v = tokens[i]
        if k == "ws":
            saw_ws_since_compound = True
            i += 1
            continue
        if v == ">":
            flush(">")
            saw_ws_since_compound = False
            i += 1
            continue
        if v in ("+", "~"):
            # Sibling combinators are outside our supported grammar (see
            # module docstring). Rather than silently mismatch, drop the
            # whole selector so its rule simply contributes no styles.
            return None
        if k == "ident" or v == "*":
            if have_any and saw_ws_since_compound:
                flush(" ")
            # Type selectors match HTML tag names case-insensitively (our
            # HTML parser already lowercases every tag); classes/IDs stay
            # case-sensitive, which is correct per spec.
            cur.type = v if v == "*" else v.lower()
            have_any = True
            saw_ws_since_compound = False
            i += 1
            continue
        if v == ".":
            i += 1
            if i < n and tokens[i][0] == "ident":
                if have_any and saw_ws_since_compound:
                    flush(" ")
                cur.classes.append(tokens[i][1])
                have_any = True
                saw_ws_since_compound = False
                i += 1
            continue
        if k == "hash":
            if have_any and saw_ws_since_compound:
                flush(" ")
            cur.id = v[1:]
            have_any = True
            saw_ws_since_compound = False
            i += 1
            continue
        if v == "[":
            if have_any and saw_ws_since_compound:
                flush(" ")
            i += 1
            name = tokens[i][1] if i < n else ""
            i += 1
            op = "exists"
            val = None
            if i < n and tokens[i][1] == "~":
                i += 1
                if i < n and tokens[i][1] == "=":
                    op = "~="
                    i += 1
            elif i < n and tokens[i][1] == "=":
                op = "="
                i += 1
            if op != "exists" and i < n:
                val = tokens[i][1]
                if val.startswith('"') or val.startswith("'"):
                    val = val[1:-1]
                i += 1
            while i < n and tokens[i][1] != "]":
                i += 1
            i += 1
            cur.attrs.append((name, op, val))
            have_any = True
            saw_ws_since_compound = False
            continue
        if v == ":":
            if have_any and saw_ws_since_compound:
                flush(" ")
            i += 1
            if i < n and tokens[i][0] == "ident":
                pname = tokens[i][1]
                i += 1
                arg = None
                if i < n and tokens[i][1] == "(":
                    i += 1
                    argtoks = []
                    while i < n and tokens[i][1] != ")":
                        argtoks.append(tokens[i][1])
                        i += 1
                    i += 1
                    arg = "".join(argtoks)
                cur.pseudos.append((pname, arg))
                have_any = True
                saw_ws_since_compound = False
            continue
        i += 1
    if have_any:
        # Final compound: no combinator to record, it has nothing after it.
        compounds.append(cur)
    if not compounds:
        return None
    return SelectorChain(compounds, combinators)
