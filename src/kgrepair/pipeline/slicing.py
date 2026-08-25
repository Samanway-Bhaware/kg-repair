"""
Stage-2 deterministic slicing.

`slice_from_cache(cache, params)` is a pure function of (cache state, params): same
cache generation + same params -> byte-identical slice and manifest hash. It:

  1. reads cached raw triples for the source,
  2. abbreviates to CURIEs and applies the allow-list whitelist (Level-0 belt),
  3. runs a deterministic, size-capped, sorted BFS frontier expansion from the seed
     entities over the allow-listed edges,
  4. emits a DataGraph + N-Triples in the loader's dialect + a manifest that mirrors
     the T5 synthetic schema plus real-source provenance fields.

Frontier rule: sorted BFS. The frontier is processed in sorted node order; each
node's outgoing allow-listed edges are taken in sorted (predicate, object) order and
added until `target_edges` is reached; objects become the next frontier. Ordering is
total and cache-derived, so expansion is fully deterministic. The typing spine
(P31/P279 etc.) is allow-listed, so type and subClassOf edges ride along and tau_C
resolves.

Nesting. Because the ordering is total and does not depend on `target_edges`, one
cache generation sliced at increasing targets yields a chain of edge sets each
contained in the next: raising the cap only lets the same walk run further. That is
what lets a size ladder be built by slicing down from a single fetch instead of
fetching once per rung, and `tests/test_slice_nesting.py` asserts it rather than
assuming it. The ordering key is recorded in every manifest as `ordering_key`, so a
later reader can tell what the nesting depended on.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from ..datagraph import DataGraph
from .allowlist import AllowList, load_allowlist
from .cache import RawCache

# Predicates after which the loader values the object with its own IRI (mirrors
# ntriples.py) so [C=] tests reach class nodes. Kept in sync so sl.graph == reload.
_VALUING_PREDICATES = ("wdt:P279", "rdfs:subClassOf", "rdf:type", "wdt:P31",
                       "schema:subClassOf")

#: The total order the size cap cuts at, recorded in the manifest.
#:
#: A candidate edge is reached at a BFS round, from a node, over a (predicate,
#: object) pair. Rounds are processed in order; within a round nodes are taken in
#: sorted order and each is visited once; within a node the pairs are sorted and
#: deduplicated. Two distinct candidate edges therefore never compare equal: they
#: differ on the node, and so on the (round, node) prefix, or they share a node and
#: differ on (predicate, object). Nothing here reads `target_edges`, which is why
#: raising the cap extends the walk rather than redirecting it.
ORDERING_KEY = "bfs_round, source_node, predicate, object"


@dataclass
class SliceParams:
    source: str
    domain: str
    seeds: List[str]                 # CURIE node ids, checked against a non-person whitelist
    target_edges: int
    allowlist_id: str
    frontier_rule: str = "sorted_bfs"


@dataclass
class RealSlice:
    name: str
    graph: DataGraph
    manifest: Dict

    def to_ntriples(self) -> str:
        lines = [f"# real slice {self.name} (source=real/{self.manifest['slice_source']}; Level-0 filtered)",
                 f"# cache_generation={self.manifest['cache_generation_hash']} "
                 f"content_hash={self.manifest['content_hash']}"]
        for s, p, o in sorted(self.graph.edges()):
            lines.append(f"<{s}> <{p}> <{o}> .")
        return "\n".join(lines) + "\n"


def _adjacency(cache: RawCache, al: AllowList) -> Dict[str, List[Tuple[str, str]]]:
    """source-node -> sorted list of (predicate, object) allow-listed IRI edges."""
    adj: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for s, p, o, is_lit in cache.iter_raw_triples(al.source):
        pc = al.curie_of(p)
        if not al.allows(pc):
            continue                          # whitelist (Level-0 belt-and-suspenders)
        if is_lit:
            continue                          # literals are not frontier nodes (P2 handles folding)
        adj[al.curie_of(s)].append((pc, al.curie_of(o)))
    for s in adj:
        adj[s] = sorted(set(adj[s]))
    return adj


def _content_hash(g: DataGraph) -> str:
    payload = sorted(g.edges())
    return hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()[:16]


def slice_from_cache(cache: RawCache, params: SliceParams,
                     *, name: Optional[str] = None) -> RealSlice:
    al = load_allowlist(params.source)
    if al.allowlist_id != params.allowlist_id:
        raise ValueError(f"allowlist mismatch: params={params.allowlist_id} file={al.allowlist_id}")
    adj = _adjacency(cache, al)

    g = DataGraph()
    visited: Set[str] = set()
    frontier: List[str] = sorted(params.seeds)
    edges = 0
    # deterministic size-capped sorted BFS
    while frontier and edges < params.target_edges:
        nxt: Set[str] = set()
        for node in sorted(frontier):
            if node in visited:
                continue
            visited.add(node)
            for (pc, obj) in adj.get(node, ()):
                if edges >= params.target_edges:
                    break
                g.add_edge(node, pc, obj)
                if pc in _VALUING_PREDICATES and g.value(obj) is None:
                    g.set_value(obj, obj)          # mirror loader class-valuing
                edges += 1
                if obj not in visited:
                    nxt.add(obj)
        frontier = sorted(nxt)

    stats = g.stats()
    manifest = {
        "name": name or f"real_{params.source}_{params.domain}_{params.target_edges}",
        "namespace": "real",
        "slice_source": params.source,          # wikidata|dbpedia|yago
        "source": "real",                        # for T1 slice_meta compatibility
        "domain": params.domain,
        "target_edges": params.target_edges,
        "seeds": sorted(params.seeds),
        "frontier_rule": params.frontier_rule,
        "ordering_key": ORDERING_KEY,
        "allowlist_id": al.allowlist_id,
        "allowlist_hash": al.content_hash,
        "cache_generation_hash": cache.generation_hash(params.source),
        "query_hashes": cache.query_hashes(params.source),
        "V": stats["nodes"], "E": stats["edges"],
        "labels": stats["labels"], "data_values": stats["valued_nodes"],
        "content_hash": _content_hash(g),
    }
    return RealSlice(manifest["name"], g, manifest)


_TYPING_SPINE = ("wdt:P31", "wdt:P279", "rdf:type", "rdfs:subClassOf",
                 "schema:subClassOf")


def typing_complete(g: DataGraph, cache: RawCache, al: AllowList) -> int:
    """
    Augment `g` in place with the typing spine (type/subClassOf) it is missing,
    drawn from the (typing-closed) cache, and close the subClassOf* chain to a
    fixpoint. Only typing-spine edges are added -- never a domain predicate -- so no
    new constraint *antecedent* match can be created; the augmentation can only
    complete a tau_C *consequent* that the size-capped BFS truncated away.

    This is the slice-side half of the T0 fix: `typing_closure_extract` guarantees the
    cache has every node's typing; `typing_complete` guarantees the slice reflects it,
    without re-running the edge-capped BFS (which would re-truncate). Returns the number
    of edges added. Deterministic (sorted frontier + sorted edges).
    """
    tadj: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for s, p, o, is_lit in cache.iter_raw_triples(al.source):
        pc = al.curie_of(p)
        if is_lit or pc not in _TYPING_SPINE or not al.allows(pc):
            continue
        tadj[al.curie_of(s)].append((pc, al.curie_of(o)))
    for k in tadj:
        tadj[k] = sorted(set(tadj[k]))

    added = 0
    frontier: Set[str] = set(g.nodes)
    seen: Set[str] = set()
    while frontier:
        nxt: Set[str] = set()
        for node in sorted(frontier):
            if node in seen:
                continue
            seen.add(node)
            for (pc, obj) in tadj.get(node, ()):
                if obj not in g.succ(pc, node):
                    g.add_edge(node, pc, obj)
                    if g.value(obj) is None:
                        g.set_value(obj, obj)         # mirror loader class-valuing
                    added += 1
                if obj not in seen:
                    nxt.add(obj)
        frontier = nxt
    return added


def emitted_predicates(g: DataGraph) -> Set[str]:
    return set(g.labels)


def deny_check(g: DataGraph, al: AllowList) -> List[str]:
    """Return any emitted predicate that is on the person/org deny list (must be [])."""
    return sorted(p for p in g.labels if al.is_denied(p))
