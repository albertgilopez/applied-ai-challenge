"""SPDX license expressions (SPDX 2.3.1, Annex D).

    expression := and-expr ( "OR" and-expr )*
    and-expr   := with-expr ( "AND" with-expr )*
    with-expr  := simple ( "WITH" exception-id )?
    simple     := license-id [ "+" ] | "(" expression ")"

Precedence is `+` > `WITH` > `AND` > `OR`; parentheses override it. Operators
are matched case-sensitively (uppercase only); ids are compared
case-insensitively later, by the policy.

`WITH` and `+` are kept inside the leaf on purpose (STORY-001 DR-4): the policy
is asked about `GPL-2.0-only WITH Classpath-exception-2.0` as written, so no
code path can drop the exception or the "or later" and look up something more
permissive than what the component declares.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

OPERATORS = ("AND", "OR", "WITH")
_TOKEN = re.compile(r"\(|\)|[^\s()]+")

# Deepest parenthesis nesting accepted. Real SBOMs nest two or three levels; the parser recurses
# about four Python frames per level, so an unbounded depth ends in RecursionError.
MAX_DEPTH = 64


class ParseError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(f"cannot parse: {message}")


class NestingError(ParseError):
    """The expression nests parentheses deeper than MAX_DEPTH."""

    def __init__(self) -> None:
        ValueError.__init__(self, f"expression nested too deeply (more than {MAX_DEPTH} levels)")


@dataclass(frozen=True)
class Leaf:
    id: str
    plus: bool = False
    exception: str | None = None

    @property
    def text(self) -> str:
        out = self.id + ("+" if self.plus else "")
        return f"{out} WITH {self.exception}" if self.exception else out


@dataclass(frozen=True)
class And:
    items: tuple[Expr, ...]


@dataclass(frozen=True)
class Or:
    items: tuple[Expr, ...]


Expr = Leaf | And | Or


def _tokens(text: str) -> list[str]:
    # A token is "(", ")" or any run of characters that are neither space nor parenthesis.
    return _TOKEN.findall(text)


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = _tokens(text)
        self.i = 0
        self.depth = 0  # parenthesis levels currently open

    def peek(self) -> str | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> str:
        tok = self.peek()
        self.i += 1
        return tok  # type: ignore[return-value]

    def expression(self) -> Expr:
        items = [self.and_expr()]
        while self.peek() == "OR":
            self.take()
            items.append(self.and_expr())
        return items[0] if len(items) == 1 else Or(tuple(items))

    def and_expr(self) -> Expr:
        items = [self.with_expr()]
        while self.peek() == "AND":
            self.take()
            items.append(self.with_expr())
        return items[0] if len(items) == 1 else And(tuple(items))

    def with_expr(self) -> Expr:
        node = self.simple()
        if self.peek() == "WITH":
            self.take()
            exc = self.peek()
            if exc is None or exc in OPERATORS or exc in "()":
                raise ParseError("expected an exception id after 'WITH'")
            if not isinstance(node, Leaf):
                raise ParseError("'WITH' must follow a single license id")
            self.take()
            node = Leaf(node.id, node.plus, exc)
        return node

    def simple(self) -> Expr:
        tok = self.peek()
        previous = self.tokens[self.i - 1] if self.i else None
        if tok is None:
            raise ParseError(f"expected a license id after {previous!r}" if previous else "empty expression")
        if tok == "(":
            if self.depth >= MAX_DEPTH:
                raise NestingError()
            self.take()
            self.depth += 1
            node = self.expression()
            if self.peek() != ")":
                raise ParseError("missing ')'")
            self.take()
            self.depth -= 1
            return node
        if tok == ")" or tok in OPERATORS:
            raise ParseError(f"unexpected {tok!r} at token {self.i}")
        self.take()
        if tok.endswith("+") and len(tok) > 1:
            return Leaf(tok[:-1], plus=True)
        return Leaf(tok)


def to_text(node: Expr) -> str:
    """Canonical text of a parsed expression, parenthesised so it parses back to the same tree.

    This is how parsed pieces are put back together: combining *trees* and printing them means a
    fragment can never change how its neighbour reads, which concatenating raw text allowed.
    """
    if isinstance(node, Leaf):
        return node.text
    if isinstance(node, And):
        # AND binds tighter than OR, so only an OR child needs parentheses inside an AND.
        return " AND ".join(f"({to_text(i)})" if isinstance(i, Or) else to_text(i) for i in node.items)
    return " OR ".join(to_text(i) for i in node.items)


def parse(text: str | None) -> Expr:
    if text is None or not text.strip():
        raise ParseError("empty expression")
    p = _Parser(text)
    node = p.expression()
    rest = p.peek()
    if rest is not None:
        if rest.upper() in OPERATORS:
            raise ParseError(f"found {rest!r}: operators are uppercase (AND, OR, WITH)")
        raise ParseError(f"unexpected {rest!r} at token {p.i}")
    return node
