"""
Per-source predicate allow-lists (Level-0 compliance).

Allow-lists are versioned data files (`allowlists/<source>.json`), NOT hardcoded.
Each carries: a whitelist of allowed predicate CURIEs (typing spine + domain
predicates from the constraint files), a prefix map (full-IRI <-> CURIE), and an
explicit person/org deny list used only to assert the safety property in tests.

Enforcement model:
  * FETCH constructs queries over allow-listed predicates only, and defensively
    filters responses before caching -> person/org-pointing triples never reach disk.
  * The SLICE stage re-applies the whitelist as belt-and-suspenders.
  * `deny_predicates` are asserted absent from every emitted slice by a unit test.

Abbreviation: SPARQL/dump output is full-IRI; the constraint vocabulary is CURIE
(`wdt:P31`, `rdfs:subClassOf`, `[val("wd:Q515")]`). `abbreviate` maps full IRIs to
CURIEs via the longest-matching namespace so predicates and class nodes line up with
the constraints; un-mappable IRIs are returned unchanged (kept as opaque node ids).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

_ALLOWLIST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "allowlists",
)


@dataclass
class AllowList:
    """A named, versioned set of predicates that may enter a slice, plus prefixes.

    Loaded from a JSON file by `load_allowlist` (one of the project's own, by
    source name) or `load_allowlist_file` (any path, so a user can supply theirs).
    `apply_allowlist` uses only the `predicates` field, to filter an
    already-loaded graph; the rest supports the extraction pipeline.
    """
    allowlist_id: str
    source: str
    predicates: frozenset
    deny_predicates: frozenset
    prefixes: Dict[str, str]              # curie prefix -> namespace IRI
    content_hash: str

    # -- IRI <-> CURIE ------------------------------------------------------
    def abbreviate(self, iri: str) -> str:
        """Full IRI -> `prefix:local` via the longest matching namespace; else IRI."""
        best_prefix, best_ns = None, ""
        for pfx, ns in self.prefixes.items():
            if iri.startswith(ns) and len(ns) > len(best_ns):
                best_prefix, best_ns = pfx, ns
        if best_prefix is not None:
            return f"{best_prefix}:{iri[len(best_ns):]}"
        return iri

    def curie_of(self, term: str) -> str:
        """Abbreviate iff it looks like a full IRI (has a scheme); else pass through
        (already a CURIE or a literal value node)."""
        return self.abbreviate(term) if term.startswith(("http://", "https://")) else term

    # -- predicate gate -----------------------------------------------------
    def allows(self, predicate_curie: str) -> bool:
        return predicate_curie in self.predicates

    def is_denied(self, predicate_curie: str) -> bool:
        return predicate_curie in self.deny_predicates


def load_allowlist(source: str) -> AllowList:
    """Load one of the project's own allow-lists by source name, from `allowlists/`.

    Resolves relative to the repo checkout, so it works from the source tree or an
    editable install but not from a plain wheel, where `allowlists/` is repo data
    rather than package data. That is fine for its only caller, the extraction
    pipeline, which runs from the checkout. Users pointing at their own file should
    use `load_allowlist_file`, which takes any path.
    """
    return load_allowlist_file(os.path.join(_ALLOWLIST_DIR, f"{source}.json"))


def load_allowlist_file(path: str) -> AllowList:
    """Load an allow-list from an arbitrary path, so a user can supply their own.

    Same file schema as the project's own lists: `allowlist_id`, `source`,
    `predicates`, optional `deny_predicates`, and a `prefixes` map.
    """
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    d = json.loads(raw)
    import hashlib
    return AllowList(
        allowlist_id=d["allowlist_id"],
        source=d["source"],
        predicates=frozenset(d["predicates"]),
        deny_predicates=frozenset(d.get("deny_predicates", [])),
        prefixes=dict(d["prefixes"]),
        content_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16],
    )


def filter_triples(triples, al: AllowList) -> List[Tuple[str, str, str]]:
    """
    Abbreviate every term and keep only triples whose predicate is allow-listed.
    Input triples are (s, p, o) with full IRIs (or CURIEs). Output is CURIE-form,
    whitelist-filtered -- the exactly-Level-0 set that may enter a slice.
    """
    out: List[Tuple[str, str, str]] = []
    for s, p, o in triples:
        pc = al.curie_of(p)
        if not al.allows(pc):
            continue
        out.append((al.curie_of(s), pc, al.curie_of(o)))
    return out
