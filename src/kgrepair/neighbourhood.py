"""
NeighbourhoodView -- bounded k-hop extraction for inspection UIs (V0, viewer support).

This module exists so the Streamlit viewer (and anything else wanting a bounded,
renderable slice around a witness or a repair change) never has to walk the whole
graph. It knows nothing about Streamlit; it is pure library code over `DataGraph`
and the `ChangeRecord` log shape shared by `repair.subset`/`repair.superset`.

Dependency direction (enforced by `tests/test_neighbourhood.py`):
`repair/subset.py` and `repair/superset.py` never import this module. The engines
are the producers of `ChangeRecord`s; this module is only ever a consumer.

Extraction is a deterministic, capped BFS:
  * `k` hops (default 2), traversing edges in BOTH directions (an edge-labelled
    graph has no notion of "nearby" that only looks at out-edges).
  * a HARD `node_cap` (default 150): once the visited set reaches the cap, no
    further nodes are admitted. Traversal order is fully sorted (labels, then
    node ids) at every step, so two extractions of the same (graph, center, k,
    node_cap) always return the identical node/edge set -- this is what "whole-
    slice rendering is impossible by construction" and "deterministic on repeat"
    mean operationally.

Diff tagging. The caller passes the `changelog` produced by a repair result
alongside whichever graph is the more complete of the two states for that
direction of repair:
  * SubsetRepair only deletes -- extract from the PRE-repair graph (deleted
    nodes/edges are still present there) so they can be tagged "deleted".
  * SupersetRepair only adds -- extract from the POST-repair graph (added
    nodes/edges are present there) so they can be tagged "added".
Anything in the extracted neighbourhood not mentioned by the changelog is
"unchanged". A node id of the form "fresh:<cid>:<n>" (D6's fresh-symbol naming)
is flagged `fresh=True` for the dashed-border / badge treatment the UI applies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .datagraph import DataGraph

DEFAULT_K = 2
DEFAULT_NODE_CAP = 150

Status = str  # "unchanged" | "deleted" | "added"


@dataclass(frozen=True)
class NVNode:
    """One node in a `NeighbourhoodView`, tagged with how a repair touched it.

    `status` is "unchanged", "added" or "deleted" relative to the change log the
    view was built against; `fresh` marks a fresh symbol the superset engine
    minted; `is_center` marks the node the walk started from.
    """
    id: str
    value: Optional[str]
    status: Status
    fresh: bool
    is_center: bool


@dataclass(frozen=True)
class NVEdge:
    """One edge in a `NeighbourhoodView`, tagged "unchanged", "added" or "deleted"."""
    src: str
    label: str
    dst: str
    status: Status


@dataclass
class NeighbourhoodView:
    """A bounded local view of a graph around one node, for inspection.

    Produced by `extract_neighbourhood`: a deterministic k-hop walk out from
    `center` in both directions, stopping at `node_cap` nodes and setting
    `truncated` when it does. Nodes and edges carry a diff status against a
    repair change log, which is what lets a viewer show what a repair altered.
    """
    center: str
    k: int
    node_cap: int
    nodes: List[NVNode] = field(default_factory=list)
    edges: List[NVEdge] = field(default_factory=list)
    truncated: bool = False   # True iff the BFS hit node_cap before exhausting k hops

    def node_ids(self) -> Set[str]:
        return {n.id for n in self.nodes}

    def to_dict(self) -> Dict:
        return {
            "center": self.center,
            "k": self.k,
            "node_cap": self.node_cap,
            "truncated": self.truncated,
            "nodes": [
                {"id": n.id, "value": n.value, "status": n.status,
                 "fresh": n.fresh, "is_center": n.is_center}
                for n in self.nodes
            ],
            "edges": [
                {"src": e.src, "label": e.label, "dst": e.dst, "status": e.status}
                for e in self.edges
            ],
        }


def _is_fresh(node_id: str) -> bool:
    return node_id.startswith("fresh:")


def _diff_index(changelog: Iterable) -> Tuple[Set[str], Set[str],
                                              Set[Tuple[str, str, str]],
                                              Set[Tuple[str, str, str]]]:
    """(deleted_nodes, added_nodes, deleted_edges, added_edges) from a ChangeRecord log.
    Duck-typed on `.op`/`.node`/`.src`/`.label`/`.dst` so it works for both engines'
    `ChangeRecord` (they share the one class in `repair.subset`) without importing it."""
    deleted_nodes: Set[str] = set()
    added_nodes: Set[str] = set()
    deleted_edges: Set[Tuple[str, str, str]] = set()
    added_edges: Set[Tuple[str, str, str]] = set()
    for r in changelog:
        if r.op == "remove_node":
            deleted_nodes.add(r.node)
        elif r.op == "add_node":
            added_nodes.add(r.node)
        elif r.op == "remove_edge":
            deleted_edges.add((r.src, r.label, r.dst))
        elif r.op == "add_edge":
            added_edges.add((r.src, r.label, r.dst))
    return deleted_nodes, added_nodes, deleted_edges, added_edges


def change_record_center(r) -> str:
    """A sensible BFS center for one ChangeRecord: the witness it serves (add ops),
    the node it removed (remove_node), or the edge's source (remove_edge)."""
    if getattr(r, "witness", None):
        return r.witness
    if r.op in ("remove_node", "add_node"):
        return r.node
    return r.src


def extract_neighbourhood(graph: DataGraph, center: str, *, k: int = DEFAULT_K,
                          node_cap: int = DEFAULT_NODE_CAP,
                          changelog: Optional[Iterable] = None) -> NeighbourhoodView:
    """
    Bounded k-hop neighbourhood of `center` in `graph`, diff-tagged against
    `changelog` (a list of `ChangeRecord`; see module docstring for which graph
    state to pass for which repair direction). Raises KeyError if `center` is not
    in `graph.nodes` (callers should extract before deletion / after addition).
    """
    if center not in graph.nodes:
        raise KeyError(f"center node not in graph: {center!r}")
    if k < 0:
        raise ValueError("k must be >= 0")
    if node_cap < 1:
        raise ValueError("node_cap must be >= 1")

    deleted_nodes, added_nodes, deleted_edges, added_edges = _diff_index(changelog or [])

    visited: Set[str] = {center}
    order: List[str] = [center]
    frontier: List[str] = [center]
    truncated = False
    labels_sorted = sorted(graph.labels)

    for _hop in range(k):
        if not frontier or len(visited) >= node_cap:
            break
        candidates: Set[str] = set()
        for label in labels_sorted:
            for src in frontier:
                candidates |= graph.succ(label, src)
            for dst in frontier:
                candidates |= graph.pred(label, dst)
        next_frontier: List[str] = []
        for node in sorted(candidates):
            if node in visited:
                continue
            if len(visited) >= node_cap:
                truncated = True
                break
            visited.add(node)
            order.append(node)
            next_frontier.append(node)
        frontier = next_frontier

    nodes = [
        NVNode(
            id=nid,
            value=graph.value(nid),
            status=("deleted" if nid in deleted_nodes
                     else "added" if nid in added_nodes else "unchanged"),
            fresh=_is_fresh(nid),
            is_center=(nid == center),
        )
        for nid in order
    ]

    edges: List[NVEdge] = []
    for label in labels_sorted:
        for src in sorted(visited):
            for dst in sorted(graph.succ(label, src) & visited):
                triple = (src, label, dst)
                status = ("deleted" if triple in deleted_edges
                          else "added" if triple in added_edges else "unchanged")
                edges.append(NVEdge(src=src, label=label, dst=dst, status=status))

    return NeighbourhoodView(center=center, k=k, node_cap=node_cap,
                             nodes=nodes, edges=edges, truncated=truncated)
