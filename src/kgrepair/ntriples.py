"""
Graph loader / parser (D4): streaming N-Triples -> DataGraph.

RDF -> data-graph correspondence (following Example 7 of the paper):

  * An IRI subject/object becomes a node named by its IRI (prefixed form kept as
    written, e.g.  wd:Q42).
  * A triple  s  p  o  with an IRI/bnode object becomes a labelled edge
    s --p--> o.
  * A triple  s  p  "lit"  with a LITERAL object is folded into the node's data
    value: we mint a fresh value-node  s#p  , attach the literal as its D(.), and
    add the edge  s --p--> s#p . This keeps the single-value discipline (each
    value lives on its own node) and lets [C=] tests reach constants uniformly.
  * Blank nodes  _:b  are skolemised to stable IRIs  bnode:<id>  so repeated runs
    are deterministic.

Only a compact, dependency-free subset of N-Triples is parsed (enough for the
curated fixtures and typical dump slices): one triple per line, '#' comments,
IRIs in <...> or prefixed  pre:Local  form, and simple "..."(^^type|@lang) literals.
This avoids a hard RDFLib dependency for the offline path; the online extractors
(D-curation) can still hand full RDF through the same DataGraph API.
"""
from __future__ import annotations

import re
from typing import Iterable, Iterator, Optional, Tuple

from .datagraph import DataGraph

_IRI = re.compile(r"<([^>]*)>")
_PREFIXED = re.compile(r"[A-Za-z][\w.\-]*:[\w.\-/#%]+")
_BNODE = re.compile(r"_:([A-Za-z0-9]+)")
_LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"(?:\^\^\S+|@[\w-]+)?')


class NTriplesError(ValueError):
    pass


def _term(tok: str) -> Tuple[str, Optional[str]]:
    """Return (node_name, literal_or_None) for one N-Triples term."""
    tok = tok.strip()
    m = _IRI.fullmatch(tok)
    if m:
        return (m.group(1), None)
    m = _BNODE.fullmatch(tok)
    if m:
        return (f"bnode:{m.group(1)}", None)  # skolemise
    m = _LITERAL.match(tok)
    if m and tok.startswith('"'):
        return (m.group(1), m.group(1))
    if _PREFIXED.fullmatch(tok):
        return (tok, None)
    raise NTriplesError(f"could not parse term: {tok!r}")


def iter_triples(lines: Iterable[str]) -> Iterator[Tuple[str, str, str, Optional[str]]]:
    """Yield (s, p, o_node, o_literal_or_None) for each triple line."""
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("."):
            line = line[:-1].strip()
        # split into exactly three terms, respecting quoted literals
        parts = _split_terms(line)
        if len(parts) != 3:
            raise NTriplesError(f"expected 3 terms, got {len(parts)}: {raw!r}")
        s, _ = _term(parts[0])
        p, _ = _term(parts[1])
        o_node, o_lit = _term(parts[2])
        yield (s, p, o_node, o_lit)


def _split_terms(line: str) -> list:
    terms, i, n = [], 0, len(line)
    while i < n:
        while i < n and line[i].isspace():
            i += 1
        if i >= n:
            break
        if line[i] == '"':
            j = i + 1
            while j < n and not (line[j] == '"' and line[j - 1] != "\\"):
                j += 1
            j += 1  # closing quote
            while j < n and not line[j].isspace():
                j += 1  # datatype/lang suffix
            terms.append(line[i:j])
            i = j
        else:
            j = i
            while j < n and not line[j].isspace():
                j += 1
            terms.append(line[i:j])
            i = j
    return terms


#: Edge labels after which the OBJECT node is given its own id as its data value,
#: so that a `[val("C")]` test can match a class node reached by a typing edge.
#: This is a default vocabulary, not a hardcoded rule: pass `type_predicates=` to
#: `load_ntriples` / `load_ntriples_file` to name the typing spine of any other
#: knowledge graph. Nothing else in the loader inspects predicate names, and the
#: loader performs no IRI-to-CURIE abbreviation at all (that lives in the
#: extraction pipeline, `pipeline/allowlist.py`), so arbitrary IRIs and CURIEs
#: survive a load unchanged.
DEFAULT_TYPE_PREDICATES = frozenset({
    "rdf:type", "rdfs:subClassOf", "schema:subClassOf",
    "wdt:P31", "wdt:P279",          # the Wikidata spine, present as a default only
})


def load_ntriples(lines: Iterable[str], graph: Optional[DataGraph] = None,
                  type_predicates: Optional[Iterable[str]] = None) -> DataGraph:
    """Stream lines into a DataGraph, folding literals onto value-nodes.

    IRIs and CURIEs are preserved exactly as written; no prefix is expanded or
    abbreviated here. `type_predicates` overrides `DEFAULT_TYPE_PREDICATES`, the
    labels after which an object node is self-valued so class tests can reach it.
    """
    types = frozenset(type_predicates) if type_predicates is not None else DEFAULT_TYPE_PREDICATES
    g = graph or DataGraph()
    for s, p, o_node, o_lit in iter_triples(lines):
        if o_lit is not None:
            value_node = f"{s}#{_local(p)}"
            g.set_value(value_node, o_lit)
            g.add_edge(s, p, value_node)
        else:
            g.add_node(s)
            g.add_node(o_node)
            g.add_edge(s, p, o_node)
            # class nodes carry their own IRI as a value so [C=] can match them
            if p in types and g.value(o_node) is None:
                g.set_value(o_node, o_node)
    return g


def load_ntriples_file(path: str, graph: Optional[DataGraph] = None,
                       type_predicates: Optional[Iterable[str]] = None) -> DataGraph:
    """Load an N-Triples file into a DataGraph. See `load_ntriples`."""
    with open(path, "r", encoding="utf-8") as fh:
        return load_ntriples(fh, graph, type_predicates=type_predicates)


def _fmt_literal(lit: str) -> str:
    escaped = lit.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def to_ntriples(graph: DataGraph) -> str:
    """
    Serialise a `DataGraph` back to this module's N-Triples dialect -- the
    round-trip companion to `load_ntriples`, not a full RDF exporter (a
    standalone `export_rdf.py` was deferred to D8/repaired-KG-packaging because
    this loader/writer pair already round-trips a repaired graph identically,
    which the viewer's export screen (D9) now also depends on and tests).

    Every node is written `<node_id>` (an already-CURIE-shaped id like `wd:Q42`
    wrapped in angle brackets round-trips identically to writing it bare --
    both hit the loader's IRI/prefixed-term branches and yield the same
    internal string -- and this matches the bracketed style the committed
    fixtures already use). A node that carries a value different from its own
    id (a loader-minted value-node, never a self-valued class node) is written
    as the literal on its edge instead of as an object node, mirroring
    `load_ntriples`'s literal-folding rule exactly.

    Limitation (inherent to N-Triples, not to this function): a node with no
    incident edges at all cannot be represented and is silently omitted. This
    is not just a theoretical edge case -- `SubsetRepair`'s cascading deletion
    routinely leaves many surviving nodes with zero remaining edges (their only
    edge was to a deleted witness), so `len(to_ntriples(g).splitlines())`-then-
    reloaded node count can be well below `len(g.nodes)` for a post-repair
    graph. This never changes validation: every constraint in this project's
    fragment requires at least one edge in its antecedent, so an edge-less node
    can never be a witness of anything, and the reloaded graph re-validates
    identically. Callers that want to report the drop (the viewer's Export
    screen does) can compare `len(load_ntriples(...).nodes)` against
    `len(g.nodes)` themselves.
    """
    lines = []
    for s, p, o in sorted(graph.edges()):
        val = graph.value(o)
        if val is not None and val != o:
            lines.append(f"<{s}> <{p}> {_fmt_literal(val)} .")
        else:
            lines.append(f"<{s}> <{p}> <{o}> .")
    return "\n".join(lines) + ("\n" if lines else "")


def _local(iri: str) -> str:
    for sep in ("#", "/", ":"):
        if sep in iri:
            iri = iri.rsplit(sep, 1)[-1]
    return iri
