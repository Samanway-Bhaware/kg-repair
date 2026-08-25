"""
Minimal streaming reader for YAGO 4.5 Turtle.

Premise-vs-measurement note: the task described YAGO as streamed N-Triples, but the
4.5 dump is **Turtle** (`@prefix`, `;`/`,` continuations, SHACL shapes). Measured on
`yago-4.5.0.2-tiny.ttl`: >99.9% of lines are single-line facts
(`yago:X <TAB> rdfs:subClassOf <TAB> yago:Y <TAB> .`); the ~0.1% multi-line
statements are almost all the schema/shapes header.

So this reader is deliberately a **single-line-fact reader**, not a full Turtle
parser: it yields a triple only from lines that terminate the statement (`.`) and
tokenise (quote/IRI-aware) into exactly three terms. Multi-line `;`/`,` statements
are skipped -- acceptable because YAGO's direct facts (type, subClassOf, location,
parentTaxon) are one-per-line. Prefixed names are kept as-is (they already match the
allow-list CURIE vocabulary); no prefix expansion is done.
"""
from __future__ import annotations

from typing import Iterator, Optional, Tuple


def _split_terms(s: str) -> list:
    """Whitespace-split respecting "literals" and <IRIs>."""
    terms, i, n = [], 0, len(s)
    while i < n:
        while i < n and s[i] in " \t":
            i += 1
        if i >= n:
            break
        if s[i] == '"':
            j = i + 1
            while j < n and not (s[j] == '"' and s[j - 1] != "\\"):
                j += 1
            j += 1                                   # closing quote
            while j < n and s[j] not in " \t":       # @lang / ^^datatype suffix
                j += 1
            terms.append(s[i:j]); i = j
        elif s[i] == "<":
            k = s.find(">", i)
            j = k + 1 if k != -1 else n
            terms.append(s[i:j]); i = j
        else:
            j = i
            while j < n and s[j] not in " \t":
                j += 1
            terms.append(s[i:j]); i = j
    return terms


def _clean(term: str) -> Tuple[str, bool]:
    """(value, is_literal). <IRI> -> IRI; "lit"... -> lit; prefixed name kept as-is."""
    if term.startswith("<") and term.endswith(">"):
        return term[1:-1], False
    if term.startswith('"'):
        end = term.rfind('"')
        return term[1:end], True
    return term, False


def iter_single_line_facts(lines) -> Iterator[Tuple[str, str, str, bool]]:
    """Yield (s, p, o, o_is_literal) for each single-line YAGO fact."""
    for raw in lines:
        line = raw.strip()
        if not line or line[0] in "@#":              # directives / comments
            continue
        if not line.endswith("."):                   # continuation of a multi-line stmt
            continue
        terms = _split_terms(line[:-1].strip())
        if len(terms) != 3:                          # not a plain S P O . fact
            continue
        s, _ = _clean(terms[0])
        p, _ = _clean(terms[1])
        o, o_lit = _clean(terms[2])
        if terms[0][0] in ";,":                      # stray continuation fragment
            continue
        yield s, p, o, o_lit
