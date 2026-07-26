"""Turns a `.kwat` token stream into nested Python lists — a generic
s-expression reader. `Str` marks tokens that came from a quoted string
literal (export/import names, data bytes) so the assembler can tell them
apart from bare atoms (mnemonics, `$names`, numbers) without re-scanning."""

from .lexer import tokenize


class Str(str):
    pass


def parse(src):
    tokens = tokenize(src)
    pos = [0]

    def read():
        if pos[0] >= len(tokens):
            raise SyntaxError("unexpected end of input")
        tok = tokens[pos[0]]
        pos[0] += 1
        if tok.kind == "lparen":
            items = []
            while True:
                if pos[0] >= len(tokens):
                    raise SyntaxError(f"line {tok.line}: unclosed '('")
                if tokens[pos[0]].kind == "rparen":
                    pos[0] += 1
                    break
                items.append(read())
            return items
        if tok.kind == "rparen":
            raise SyntaxError(f"line {tok.line}: unexpected ')'")
        if tok.kind == "string":
            return Str(tok.text)
        return tok.text

    forms = []
    while pos[0] < len(tokens):
        forms.append(read())
    return forms
