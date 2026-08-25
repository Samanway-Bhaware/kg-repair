"""
Surface-syntax parser for Reg-GXPath_pos, restricted to the positive fragment.

Concrete syntax (ASCII, chosen to be paste-safe in constraint files):

  node   := disj
  disj   := conj ( '|' conj )*
  conj   := atom ( '&' atom )*
  atom   := 'T'
          | 'val(' STRING ')'                    # data value equals constant
          | '<' path '>'                         # <a>  exists path
          | '(' node ')'

  path   := seqp
  seqp   := altp ( '.' altp )*
  altp   := unary ( '+' unary )*                 # '+' is path union (a u b)
  unary  := postfix
  postfix:= prim ( '*' )?                         # Kleene star
  prim   := 'eps'
          | 'down(' NAME ')'  | '>' NAME          # forward edge
          | 'up('   NAME ')'  | '<' NAME          # backward edge  (bare)
          | '[' node ']'                          # node test
          | '(' path ')'
          | 'isect(' path ',' path ')'            # bounded intersection

Rejected on sight, with a clear diagnostic (they leave the tractable fragment):
  '!' or 'not'  -> node complement
  '~' or 'compl'-> path complement
  '#' or 'neq'  -> data disequality

STRING is a single- or double-quoted literal; NAME is a bareword edge label
([A-Za-z0-9_:/.#-]+), which covers prefixed IRIs like  wdt:P31.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from . import ast


class ParseError(ValueError):
    pass


_FORBIDDEN = {
    "!": "node complement (not phi) leaves Reg-GXPath_pos",
    "not": "node complement (not phi) leaves Reg-GXPath_pos",
    "~": "path complement (a-bar) leaves Reg-GXPath_pos",
    "compl": "path complement (a-bar) leaves Reg-GXPath_pos",
    "#": "data disequality (neq) requires negation",
    "neq": "data disequality (neq) requires negation",
}

_TOKEN = re.compile(r"""
      (?P<ws>\s+)
    | (?P<str>"[^"]*"|'[^']*')
    | (?P<kw>down|up|eps|isect|val|not|compl|neq|T)
    | (?P<name>[A-Za-z0-9_:/.\#\-]+)
    | (?P<op>[<>\[\]().*|&+,~!#])
""", re.VERBOSE)


def _lex(s: str) -> List[Tuple[str, str]]:
    toks: List[Tuple[str, str]] = []
    i = 0
    while i < len(s):
        m = _TOKEN.match(s, i)
        if not m:
            raise ParseError(f"unexpected character {s[i]!r} at position {i}")
        i = m.end()
        kind = m.lastgroup
        text = m.group()
        if kind == "ws":
            continue
        toks.append((kind, text))
    toks.append(("eof", ""))
    return toks


class _P:
    def __init__(self, toks: List[Tuple[str, str]]):
        self.toks = toks
        self.i = 0

    def peek(self) -> Tuple[str, str]:
        return self.toks[self.i]

    def next(self) -> Tuple[str, str]:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, text: str) -> None:
        k, t = self.next()
        if t != text:
            raise ParseError(f"expected {text!r}, found {t!r}")

    def _guard(self, text: str) -> None:
        low = text.lower()
        if text in _FORBIDDEN or low in _FORBIDDEN:
            raise ParseError(_FORBIDDEN.get(text, _FORBIDDEN.get(low)))

    # ---- node grammar ----

    def node(self) -> ast.Node:
        left = self.conj()
        while self.peek()[1] == "|":
            self.next()
            left = ast.Disj(left, self.conj())
        return left

    def conj(self) -> ast.Node:
        left = self.node_atom()
        while self.peek()[1] == "&":
            self.next()
            left = ast.Conj(left, self.node_atom())
        return left

    def node_atom(self) -> ast.Node:
        k, t = self.peek()
        self._guard(t)
        if t == "T":
            self.next()
            return ast.Top()
        if t == "val":
            self.next()
            self.expect("(")
            s = self._string()
            self.expect(")")
            return ast.ValueEq(s)
        if t == "<":
            self.next()
            p = self.path()
            self.expect(">")
            return ast.Has(p)
        if t == "(":
            self.next()
            n = self.node()
            self.expect(")")
            return n
        raise ParseError(f"expected a node expression, found {t!r}")

    # ---- path grammar ----

    def path(self) -> ast.Path:
        return self.seqp()

    def seqp(self) -> ast.Path:
        left = self.altp()
        while self.peek()[1] == ".":
            self.next()
            left = ast.Seq(left, self.altp())
        return left

    def altp(self) -> ast.Path:
        left = self.postfix()
        while self.peek()[1] == "+":
            self.next()
            left = ast.Alt(left, self.postfix())
        return left

    def postfix(self) -> ast.Path:
        p = self.prim()
        while self.peek()[1] == "*":
            self.next()
            p = ast.Star(p)
        return p

    def prim(self) -> ast.Path:
        k, t = self.peek()
        self._guard(t)
        if t == "eps":
            self.next()
            return ast.Eps()
        if t == "down":
            self.next()
            self.expect("(")
            name = self._name()
            self.expect(")")
            return ast.Down(name)
        if t == "up":
            self.next()
            self.expect("(")
            name = self._name()
            self.expect(")")
            return ast.Up(name)
        if t == "isect":
            self.next()
            self.expect("(")
            a = self.path()
            self.expect(",")
            b = self.path()
            self.expect(")")
            return ast.Isect(a, b)
        if t == ">":
            self.next()
            return ast.Down(self._name())
        if t == "<":
            self.next()
            return ast.Up(self._name())
        if t == "[":
            self.next()
            n = self.node()
            self.expect("]")
            return ast.Test(n)
        if t == "(":
            self.next()
            p = self.path()
            self.expect(")")
            return p
        raise ParseError(f"expected a path expression, found {t!r}")

    # ---- terminals ----

    def _name(self) -> str:
        k, t = self.next()
        if k not in ("name", "kw"):
            raise ParseError(f"expected an edge label, found {t!r}")
        return t

    def _string(self) -> str:
        k, t = self.next()
        if k != "str":
            raise ParseError(f"expected a quoted constant, found {t!r}")
        return t[1:-1]


def parse_node(text: str) -> ast.Node:
    p = _P(_lex(text))
    n = p.node()
    if p.peek()[0] != "eof":
        raise ParseError(f"trailing input near {p.peek()[1]!r}")
    return n


def parse_path(text: str) -> ast.Path:
    p = _P(_lex(text))
    a = p.path()
    if p.peek()[0] != "eof":
        raise ParseError(f"trailing input near {p.peek()[1]!r}")
    return a
