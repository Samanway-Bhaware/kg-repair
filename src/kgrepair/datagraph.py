"""
Internal data-graph model.

A data-graph in the sense of Abriola, Martinez, Pardal, Cifuentes & Pin Baque
(JAIR 76:721-759, 2023) is a directed, edge-labelled graph in which every node
may carry a single data value:

    G = (V, L, D)

    V : finite set of nodes (object identifiers / IRIs / skolemised blanks)
    L : for each label a in a finite alphabet, a binary relation L(a) subset of V x V
    D : partial map V -> data-value domain (the single value D(v) of a node)

This module keeps L as sparse adjacency (out- and in-indexes per label) so that
the evaluator can do backward pre-image traversal without ever materialising a
dense V x V relation. Nothing here modifies D(v): repairs act on nodes/edges only.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, Optional, Set, Tuple


@dataclass
class DataGraph:
    """Sparse, edge-labelled data-graph with per-node data values."""

    # nodes
    _nodes: Set[str] = field(default_factory=set)
    # label -> src -> set(dst)
    _out: Dict[str, Dict[str, Set[str]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(set))
    )
    # label -> dst -> set(src)
    _in: Dict[str, Dict[str, Set[str]]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(set))
    )
    # node -> data value (partial)
    _value: Dict[str, str] = field(default_factory=dict)
    # label -> monotic counter, bumped whenever that label's edge set changes.
    # Lets the evaluator's subClassOf* closure cache (OPT-2) detect precisely when a
    # spine label was mutated, without scanning the graph.
    _label_version: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # ---- construction -------------------------------------------------------

    def add_node(self, v: str, value: Optional[str] = None) -> None:
        self._nodes.add(v)
        if value is not None:
            self._value[v] = value

    def set_value(self, v: str, value: str) -> None:
        self._nodes.add(v)
        self._value[v] = value

    def add_edge(self, src: str, label: str, dst: str) -> None:
        self._nodes.add(src)
        self._nodes.add(dst)
        if dst not in self._out[label][src]:
            self._out[label][src].add(dst)
            self._in[label][dst].add(src)
            self._label_version[label] += 1

    def remove_edge(self, src: str, label: str, dst: str) -> None:
        if dst in self._out.get(label, {}).get(src, ()):
            self._out[label][src].discard(dst)
            self._in[label][dst].discard(src)
            self._label_version[label] += 1

    def label_version(self, label: str) -> int:
        """Change counter for `label`'s edge set (see `_label_version`)."""
        return self._label_version[label]

    def remove_node(self, v: str) -> None:
        """Delete a node and every edge incident to it (used by SubsetRepair)."""
        for label in list(self._out):
            for dst in list(self._out[label].get(v, ())):
                self.remove_edge(v, label, dst)
            for src in list(self._in[label].get(v, ())):
                self.remove_edge(src, label, v)
            self._out[label].pop(v, None)
            self._in[label].pop(v, None)
        self._nodes.discard(v)
        self._value.pop(v, None)

    # ---- accessors ----------------------------------------------------------

    @property
    def nodes(self) -> Set[str]:
        return self._nodes

    @property
    def labels(self) -> Set[str]:
        return set(self._out) | set(self._in)

    def value(self, v: str) -> Optional[str]:
        return self._value.get(v)

    def nodes_with_value(self, c: str) -> Set[str]:
        """{ x : D(x) = c } -- sparse scan over the value map only."""
        return {v for v, val in self._value.items() if val == c}

    def succ(self, label: str, src: str) -> Set[str]:
        """a-successors of src: { y : (src, y) in L(a) }."""
        return set(self._out.get(label, {}).get(src, ()))

    def pred(self, label: str, dst: str) -> Set[str]:
        """a-predecessors of dst: { x : (x, dst) in L(a) }."""
        return set(self._in.get(label, {}).get(dst, ()))

    def pred_set(self, label: str, targets: Set[str]) -> Set[str]:
        """All a-predecessors of any node in `targets` (backward image of one hop)."""
        idx = self._in.get(label, {})
        out: Set[str] = set()
        for t in targets:
            out |= idx.get(t, set())
        return out

    def succ_set(self, label: str, sources: Set[str]) -> Set[str]:
        """All a-successors of any node in `sources` (forward image of one hop)."""
        idx = self._out.get(label, {})
        out: Set[str] = set()
        for s in sources:
            out |= idx.get(s, set())
        return out

    def edges(self) -> Iterator[Tuple[str, str, str]]:
        for label, srcmap in self._out.items():
            for src, dsts in srcmap.items():
                for dst in dsts:
                    yield (src, label, dst)

    # ---- stats / cloning ----------------------------------------------------

    def num_edges(self) -> int:
        return sum(len(d) for m in self._out.values() for d in m.values())

    def stats(self) -> Dict[str, int]:
        return {
            "nodes": len(self._nodes),
            "edges": self.num_edges(),
            "labels": len(self.labels),
            "valued_nodes": len(self._value),
        }

    def clone(self) -> "DataGraph":
        g = DataGraph()
        g._nodes = set(self._nodes)
        g._value = dict(self._value)
        for label, srcmap in self._out.items():
            for src, dsts in srcmap.items():
                for dst in dsts:
                    g.add_edge(src, label, dst)
        return g

    @staticmethod
    def from_triples(triples: Iterable[Tuple[str, str, str]],
                     values: Optional[Dict[str, str]] = None) -> "DataGraph":
        g = DataGraph()
        for s, p, o in triples:
            g.add_edge(s, p, o)
        for v, val in (values or {}).items():
            g.set_value(v, val)
        return g
