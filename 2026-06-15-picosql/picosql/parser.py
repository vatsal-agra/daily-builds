"""Recursive-descent SQL parser: tokens -> AST.

Errors are `ParseError`s carrying a source position so callers can render a
caret under the offending token.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from . import ast_nodes as A
from .tokenizer import Token, tokenize

_AGGREGATES = {"COUNT", "SUM", "AVG", "MIN", "MAX"}


class ParseError(Exception):
    def __init__(self, message: str, pos: int):
        super().__init__(message)
        self.message = message
        self.pos = pos


class Parser:
    def __init__(self, sql: str):
        self.sql = sql
        self.toks = tokenize(sql)
        self.i = 0

    # ---- token helpers ---------------------------------------------------
    @property
    def cur(self) -> Token:
        return self.toks[self.i]

    def advance(self) -> Token:
        t = self.toks[self.i]
        if t.type != "eof":
            self.i += 1
        return t

    def at_kw(self, *kws: str) -> bool:
        return self.cur.type == "kw" and self.cur.value in kws

    def at_op(self, *ops: str) -> bool:
        return self.cur.type == "op" and self.cur.value in ops

    def eat_kw(self, kw: str) -> Token:
        if not self.at_kw(kw):
            raise ParseError(f"expected {kw}", self.cur.pos)
        return self.advance()

    def eat_op(self, op: str) -> Token:
        if not self.at_op(op):
            raise ParseError(f"expected {op!r}", self.cur.pos)
        return self.advance()

    def maybe_kw(self, *kws: str) -> bool:
        if self.at_kw(*kws):
            self.advance()
            return True
        return False

    def maybe_op(self, *ops: str) -> bool:
        if self.at_op(*ops):
            self.advance()
            return True
        return False

    def expect_ident(self) -> str:
        # Allow non-reserved keywords? Keep strict: identifiers only.
        if self.cur.type == "ident":
            return self.advance().value
        raise ParseError("expected identifier", self.cur.pos)

    # ---- entry point -----------------------------------------------------
    def parse_statement(self):
        stmt = self._statement()
        # optional trailing semicolon, then EOF
        self.maybe_op(";")
        if self.cur.type != "eof":
            raise ParseError("unexpected trailing input", self.cur.pos)
        return stmt

    def _statement(self):
        if self.at_kw("EXPLAIN"):
            self.advance()
            return A.Explain(self._statement())
        if self.at_kw("SELECT"):
            return self._select()
        if self.at_kw("INSERT"):
            return self._insert()
        if self.at_kw("CREATE"):
            return self._create()
        if self.at_kw("DROP"):
            return self._drop()
        if self.at_kw("UPDATE"):
            return self._update()
        if self.at_kw("DELETE"):
            return self._delete()
        if self.at_kw("BEGIN"):
            self.advance()
            self.maybe_kw("TRANSACTION")
            return A.Begin()
        if self.at_kw("COMMIT"):
            self.advance()
            self.maybe_kw("TRANSACTION")
            return A.Commit()
        if self.at_kw("ROLLBACK"):
            self.advance()
            self.maybe_kw("TRANSACTION")
            return A.Rollback()
        raise ParseError("expected a statement", self.cur.pos)

    # ---- CREATE / DROP ---------------------------------------------------
    def _create(self):
        self.eat_kw("CREATE")
        self.eat_kw("TABLE")
        if_not_exists = False
        if self.maybe_kw("IF"):
            self.eat_kw("NOT")
            self.eat_kw("EXISTS")
            if_not_exists = True
        name = self.expect_ident()
        self.eat_op("(")
        cols: List[A.ColumnDef] = []
        while True:
            cname = self.expect_ident()
            if not self.at_kw("INTEGER", "REAL", "TEXT"):
                raise ParseError("expected column type (INTEGER, REAL, or TEXT)", self.cur.pos)
            ctype = self.advance().value
            pk = False
            if self.maybe_kw("PRIMARY"):
                self.eat_kw("KEY")
                pk = True
            cols.append(A.ColumnDef(cname, ctype, pk))
            if self.maybe_op(","):
                continue
            break
        self.eat_op(")")
        pks = [c for c in cols if c.primary_key]
        if len(pks) > 1:
            raise ParseError("only one PRIMARY KEY column is supported", self.cur.pos)
        if pks and pks[0].type != "INTEGER":
            raise ParseError("PRIMARY KEY must be an INTEGER column", self.cur.pos)
        return A.CreateTable(name, cols, if_not_exists)

    def _drop(self):
        self.eat_kw("DROP")
        self.eat_kw("TABLE")
        if_exists = False
        if self.maybe_kw("IF"):
            self.eat_kw("EXISTS")
            if_exists = True
        name = self.expect_ident()
        return A.DropTable(name, if_exists)

    # ---- INSERT ----------------------------------------------------------
    def _insert(self):
        self.eat_kw("INSERT")
        self.eat_kw("INTO")
        table = self.expect_ident()
        columns: Optional[List[str]] = None
        if self.maybe_op("("):
            columns = [self.expect_ident()]
            while self.maybe_op(","):
                columns.append(self.expect_ident())
            self.eat_op(")")
        self.eat_kw("VALUES")
        rows: List[List[A.Expr]] = []
        while True:
            self.eat_op("(")
            vals = [self._expr()]
            while self.maybe_op(","):
                vals.append(self._expr())
            self.eat_op(")")
            rows.append(vals)
            if self.maybe_op(","):
                continue
            break
        return A.Insert(table, columns, rows)

    # ---- UPDATE / DELETE -------------------------------------------------
    def _update(self):
        self.eat_kw("UPDATE")
        table = self.expect_ident()
        self.eat_kw("SET")
        assignments: List[Tuple[str, A.Expr]] = []
        while True:
            col = self.expect_ident()
            self.eat_op("=")
            assignments.append((col, self._expr()))
            if self.maybe_op(","):
                continue
            break
        where = None
        if self.maybe_kw("WHERE"):
            where = self._expr()
        return A.Update(table, assignments, where)

    def _delete(self):
        self.eat_kw("DELETE")
        self.eat_kw("FROM")
        table = self.expect_ident()
        where = None
        if self.maybe_kw("WHERE"):
            where = self._expr()
        return A.Delete(table, where)

    # ---- SELECT ----------------------------------------------------------
    def _select(self):
        self.eat_kw("SELECT")
        distinct = self.maybe_kw("DISTINCT")
        projections: List[Tuple[A.Expr, Optional[str]]] = []
        while True:
            if self.at_op("*"):
                self.advance()
                projections.append((A.Star(None), None))
            else:
                expr = self._expr()
                # t.* form
                alias = None
                if self.maybe_kw("AS"):
                    alias = self.expect_ident()
                elif self.cur.type == "ident":
                    alias = self.advance().value
                projections.append((expr, alias))
            if self.maybe_op(","):
                continue
            break

        from_table = None
        from_alias = None
        joins: List[A.Join] = []
        if self.maybe_kw("FROM"):
            from_table = self.expect_ident()
            from_alias = self._maybe_alias()
            while self.at_kw("JOIN", "INNER"):
                self.maybe_kw("INNER")
                self.eat_kw("JOIN")
                jtable = self.expect_ident()
                jalias = self._maybe_alias()
                self.eat_kw("ON")
                on = self._expr()
                joins.append(A.Join(jtable, jalias, on))

        where = None
        if self.maybe_kw("WHERE"):
            where = self._expr()

        group_by: List[A.Expr] = []
        if self.maybe_kw("GROUP"):
            self.eat_kw("BY")
            group_by.append(self._expr())
            while self.maybe_op(","):
                group_by.append(self._expr())

        having = None
        if self.maybe_kw("HAVING"):
            having = self._expr()

        order_by: List[Tuple[A.Expr, bool]] = []
        if self.maybe_kw("ORDER"):
            self.eat_kw("BY")
            while True:
                e = self._expr()
                desc = False
                if self.maybe_kw("DESC"):
                    desc = True
                else:
                    self.maybe_kw("ASC")
                order_by.append((e, desc))
                if self.maybe_op(","):
                    continue
                break

        limit = None
        offset = None
        if self.maybe_kw("LIMIT"):
            limit = self._int_literal()
            if self.maybe_kw("OFFSET"):
                offset = self._int_literal()
        if self.maybe_kw("OFFSET"):
            offset = self._int_literal()

        return A.Select(
            projections, from_table, from_alias, joins, where,
            group_by, having, order_by, limit, offset, distinct,
        )

    def _maybe_alias(self) -> Optional[str]:
        if self.maybe_kw("AS"):
            return self.expect_ident()
        if self.cur.type == "ident":
            return self.advance().value
        return None

    def _int_literal(self) -> int:
        if self.cur.type == "num" and isinstance(self.cur.value, int):
            return self.advance().value
        raise ParseError("expected an integer", self.cur.pos)

    # ---- expressions (precedence climbing by layered methods) ------------
    def _expr(self) -> A.Expr:
        return self._or()

    def _or(self) -> A.Expr:
        left = self._and()
        while self.at_kw("OR"):
            self.advance()
            right = self._and()
            left = A.BinaryOp("OR", left, right)
        return left

    def _and(self) -> A.Expr:
        left = self._not()
        while self.at_kw("AND"):
            self.advance()
            right = self._not()
            left = A.BinaryOp("AND", left, right)
        return left

    def _not(self) -> A.Expr:
        if self.at_kw("NOT"):
            self.advance()
            return A.UnaryOp("NOT", self._not())
        return self._comparison()

    def _comparison(self) -> A.Expr:
        left = self._additive()
        if self.at_op("=", "!=", "<>", "<", "<=", ">", ">="):
            op = self.advance().value
            if op == "<>":
                op = "!="
            right = self._additive()
            return A.BinaryOp(op, left, right)
        if self.at_kw("IS"):
            self.advance()
            negated = self.maybe_kw("NOT")
            self.eat_kw("NULL")
            return A.IsNull(left, negated)
        if self.at_kw("LIKE"):
            self.advance()
            right = self._additive()
            return A.BinaryOp("LIKE", left, right)
        if self.at_kw("NOT"):
            # NOT LIKE
            save = self.i
            self.advance()
            if self.at_kw("LIKE"):
                self.advance()
                right = self._additive()
                return A.UnaryOp("NOT", A.BinaryOp("LIKE", left, right))
            self.i = save
        return left

    def _additive(self) -> A.Expr:
        left = self._multiplicative()
        while self.at_op("+", "-"):
            op = self.advance().value
            right = self._multiplicative()
            left = A.BinaryOp(op, left, right)
        return left

    def _multiplicative(self) -> A.Expr:
        left = self._unary()
        while self.at_op("*", "/", "%"):
            op = self.advance().value
            right = self._unary()
            left = A.BinaryOp(op, left, right)
        return left

    def _unary(self) -> A.Expr:
        if self.at_op("-", "+"):
            op = self.advance().value
            return A.UnaryOp(op, self._unary())
        return self._primary()

    def _primary(self) -> A.Expr:
        t = self.cur
        if t.type == "num":
            self.advance()
            return A.Literal(t.value)
        if t.type == "str":
            self.advance()
            return A.Literal(t.value)
        if self.at_kw("NULL"):
            self.advance()
            return A.Literal(None)
        if self.at_op("("):
            self.advance()
            e = self._expr()
            self.eat_op(")")
            return e
        # aggregate / function call, possibly a keyword like COUNT
        if t.type == "kw" and t.value in _AGGREGATES:
            name = self.advance().value
            self.eat_op("(")
            if self.at_op("*"):
                self.advance()
                self.eat_op(")")
                return A.FuncCall(name, [], star=True)
            args = [self._expr()]
            while self.maybe_op(","):
                args.append(self._expr())
            self.eat_op(")")
            return A.FuncCall(name, args)
        if t.type == "ident":
            name = self.advance().value
            # function call?
            if self.at_op("("):
                self.advance()
                args: List[A.Expr] = []
                if not self.at_op(")"):
                    args.append(self._expr())
                    while self.maybe_op(","):
                        args.append(self._expr())
                self.eat_op(")")
                return A.FuncCall(name, args)
            # qualified column  a.b  or a.*
            if self.at_op("."):
                self.advance()
                if self.at_op("*"):
                    self.advance()
                    return A.Star(name)
                col = self.expect_ident()
                return A.ColumnRef(name, col)
            return A.ColumnRef(None, name)
        raise ParseError("expected an expression", t.pos)


def parse(sql: str):
    return Parser(sql).parse_statement()


def format_error(sql: str, message: str, pos: int) -> str:
    """Render a one-line caret diagnostic for a syntax error."""
    # Work within the offending line.
    line_start = sql.rfind("\n", 0, pos) + 1
    line_end = sql.find("\n", pos)
    if line_end == -1:
        line_end = len(sql)
    line = sql[line_start:line_end]
    col = pos - line_start
    caret = " " * col + "^"
    return f"syntax error: {message}\n  {line}\n  {caret}"
