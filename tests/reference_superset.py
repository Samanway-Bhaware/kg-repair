"""
The literal Algorithm 2: an obviously-correct, obviously-unrunnable oracle for
the superset engine.

`kgrepair.repair.superset` does not execute Algorithm 2 of Abriola, Martinez,
Pardal, Cifuentes & Pin Baque (JAIR 76:721-759, 2023) as written. It replaces
saturation-then-trimming with a goal-directed planner, because the algorithm's
first step -- `buildGraph`, which sets `L'(v, w) = Sigma_e` for every ordered pair
of nodes -- is not instantiable at this project's corpus sizes (about 90 GB at the
geography 10k slice, about 476 TB at the million-edge rung; see
`docs/why_algorithm_2_cannot_run_as_written.md`). That substitution is recorded in
the fidelity ledger as a deliberate variant, and a variant that is only documented
is a variant that is only asserted.

This module writes Algorithm 2 out literally, so that the planner can be checked
against it at the one scale where both fit: ten to twenty nodes over a handful of
labels, where the completed graph is a few thousand edges instead of a few hundred
billion. Two implementations of one definition, one of them obviously correct and
far too slow, is what makes the fast one testable.

What it shares with the engine, and what it does not
---------------------------------------------------
It shares the **search space** and the **consistency predicate**, and nothing else.

  * the space, via `superset.core_constraints` and `superset.named_constants`:
    if the two sides disagreed about which values a repair may draw on, agreeing
    or disagreeing about whether a repair exists would mean nothing;
  * the predicate, via `is_consistent` below, which is `Validator.check_one(c).count
    == 0` over the `ptime_core` constraints -- the same expression the engine's own
    `consistent_after` attestation evaluates.

It shares no planning, no pruning and no bookkeeping. In particular it does not
import `_plan_node`, `_plan_has`, `_pin_value`, `_prune` or `_Alloc`. Additions
here arise only from saturation, and removals only from the trimming loop, both
written out from the paper's text. That independence is the point.

The fresh-value pool, and why the two are not assumed to coincide
----------------------------------------------------------------
The paper's `buildGraph` is called on `S = Sigma^R_n u {c, d}`: the values named by
the constraints, plus **two fresh values in total** (Lemma 21). The engine mints up
to two fresh symbols **per constraint** (`fresh:<cid>:<n>`, bound `2|R|`). The
fidelity ledger classes that as a safe generalisation -- a larger finite pool cannot
exclude a repair the smaller pool admits -- but *safe* is a claim about one direction
only, and this module must not quietly assume the two pools coincide. So the pool
here is `named_constants(core)` plus a fresh-value count the caller states, defaulting
to the paper's two, and the harness records separately how many fresh symbols the
engine actually consumed. Where the engine consumed more than two, that is reported
as an exercise of the generalisation, not smuggled into an equality.

The scale guard
---------------
`build_graph` refuses to materialise a completed graph above
`MAX_COMPLETED_EDGES`, raising `CompletedGraphTooLarge`. The ceiling is not a
performance tuning knob: it is what stops the oracle from ever attempting, by
accident, the construction the design notes prove is impossible.
A caller that trips it is meant to skip with a reason, not to raise the ceiling.

Cost
----
The completed graph over `n` nodes and `m` labels has `n^2 * m` edges. The trimming
loop runs one full consistency check per edge of `E_H \\ E_G`, and the outer loop
runs one per subset of the pool. Nothing here is optimised and nothing here should
be: the whole value of the module is that it is the definition and not an
implementation of it.
"""
from __future__ import annotations

import itertools
from typing import Iterator, List, Optional, Set, Tuple

from kgrepair.constraints.model import Constraint
from kgrepair.datagraph import DataGraph
from kgrepair.gxpath import ast
from kgrepair.repair.superset import core_constraints, named_constants
from kgrepair.validator import Validator

#: Ceiling on `|V_H|^2 * |Sigma_e|`, the edge count of a completed graph. Sized to
#: sit far above anything the differential harness builds (a twenty-node graph over
#: five labels completes to 2,500 edges) and far below anything in the corpus (the
#: geography 10k slice completes to 1.65e8). See the module docstring.
MAX_COMPLETED_EDGES = 50_000

#: The paper's `{c, d}`: two fresh values, in total, for the whole constraint set.
LEMMA21_FRESH = ("lemma21:c", "lemma21:d")


class CompletedGraphTooLarge(RuntimeError):
    """`buildGraph` was asked for a completed graph above `MAX_COMPLETED_EDGES`.

    Raised rather than attempted. Carries the sizes so a caller can skip with the
    numbers in the reason.
    """

    def __init__(self, nodes: int, labels: int, edges: int, ceiling: int):
        self.nodes, self.labels, self.edges, self.ceiling = nodes, labels, edges, ceiling
        super().__init__(
            f"completed graph would carry {edges:,} edges "
            f"({nodes} nodes x {nodes} nodes x {labels} labels), "
            f"above the ceiling of {ceiling:,}")


 
# the shared consistency predicate
 

def is_consistent(graph: DataGraph, core: List[Constraint],
                  validator: Optional[Validator] = None) -> bool:
    """No `ptime_core` witness survives: the engine's `consistent_after`, verbatim.

    One definition, used by both sides of the comparison and by the harness, so a
    disagreement can never be an artefact of two spellings of "consistent". Pass a
    `validator` already bound to `graph` to reuse its closure memoisation across a
    mutating loop; the predicate is identical either way.
    """
    v = validator if validator is not None else Validator(graph, use_closure=True)
    return all(v.check_one(c).count == 0 for c in core)


def core_witness_count(graph: DataGraph, core: List[Constraint]) -> int:
    """How many `ptime_core` witnesses survive; `is_consistent` is this being zero."""
    v = Validator(graph, use_closure=True)
    return sum(v.check_one(c).count for c in core)


 
# the label alphabet
 

def _labels_node(n: ast.Node, acc: Set[str]) -> None:
    if isinstance(n, ast.Has):
        _labels_path(n.path, acc)
    elif isinstance(n, (ast.Conj, ast.Disj)):
        _labels_node(n.left, acc)
        _labels_node(n.right, acc)


def _labels_path(p: ast.Path, acc: Set[str]) -> None:
    if isinstance(p, (ast.Down, ast.Up)):
        acc.add(p.label)
    elif isinstance(p, (ast.Seq, ast.Alt, ast.Isect)):
        _labels_path(p.left, acc)
        _labels_path(p.right, acc)
    elif isinstance(p, ast.Star):
        _labels_path(p.inner, acc)
    elif isinstance(p, ast.Test):
        _labels_node(p.node, acc)


def edge_alphabet(g: DataGraph, core: List[Constraint]) -> Set[str]:
    """`Sigma_e`: every label occurring in the graph or named by a constraint.

    The paper takes `Sigma_e` as given. Here it has to be derived, and it must
    include labels a constraint names but the graph does not yet carry -- otherwise
    the completed graph could not satisfy a consequent about a label absent from `G`,
    and the oracle would report a non-existence that is an artefact of its own
    alphabet.
    """
    acc = set(g.labels)
    for c in core:
        _labels_node(c.phi, acc)
        _labels_node(c.psi, acc)
    return acc


 
# buildGraph
 

def build_graph(g: DataGraph, S: Set[str], labels: Set[str]) -> DataGraph:
    """The paper's `buildGraph(G, S)`, literally.

    Adds one node per data value in `S`, self-valued, then sets
    `L'(v, w) = Sigma_e` for **every ordered pair** of nodes over **every** label --
    self-pairs included, which is what "every ordered pair" says. Returns a new
    graph; `g` is never mutated.

    Two things are pinned down that the paper leaves free, both recorded here rather
    than in the code that uses it:

      * a value node is identified by its value, so a value already carried by a node
        of `G` does not get a second node. The paper would add one. Duplicating a
        value node in a graph where every pair is already adjacent under every label
        cannot change which positive node expressions hold, and identifying the two
        is what lets the containment comparison line up node names at all. Where `G`
        holds a node with that identifier under a *different* value, a distinct
        `pool:` node is created instead, so no existing value is ever rewritten.
      * `Sigma_e` comes from `edge_alphabet`; see its docstring.

    Raises `CompletedGraphTooLarge` above `MAX_COMPLETED_EDGES` rather than
    attempting the construction.
    """
    value_nodes = {}
    for s in sorted(S):
        if g.value(s) == s or s not in g.nodes:
            value_nodes[s] = s
        else:
            value_nodes[s] = f"pool:{s}"

    nodes = set(g.nodes) | set(value_nodes.values())
    n, m = len(nodes), len(labels)
    if n * n * m > MAX_COMPLETED_EDGES:
        raise CompletedGraphTooLarge(n, m, n * n * m, MAX_COMPLETED_EDGES)

    h = g.clone()
    for value, nid in value_nodes.items():
        if nid not in h.nodes or h.value(nid) is None:
            h.add_node(nid, value=value)

    ordered = sorted(nodes)
    for label in sorted(labels):
        for u in ordered:
            for v in ordered:
                h.add_edge(u, label, v)
    return h


 
# the pool and its subsets
 

def value_pool(core: List[Constraint], fresh: int = 2) -> List[str]:
    """`Sigma^R_n u {c, d}`: the constraint-named constants plus `fresh` new values.

    Named constants come from `superset.named_constants`, the engine's own function,
    so the two sides provably search the same named space. `fresh` defaults to the
    paper's two; the harness raises it only to state, explicitly, how far the engine's
    per-constraint allocator ranged beyond Lemma 21's pool.
    """
    extra = [LEMMA21_FRESH[i] if i < len(LEMMA21_FRESH) else f"lemma21:x{i}"
             for i in range(fresh)]
    return sorted(named_constants(core)) + extra


def subsets_by_size(pool: List[str]) -> Iterator[Tuple[str, ...]]:
    """Every subset of `pool`, smallest first, ties broken by the pool's own order.

    The paper says "for each subset" and fixes no order. Fixing one here is the same
    kind of strengthening the engine applies to its pruning pass: it makes a run
    reproducible, and taking the smallest first means the first surviving completed
    graph is built over the fewest added values.
    """
    for k in range(len(pool) + 1):
        for combo in itertools.combinations(pool, k):
            yield combo


 
# Algorithm 2
 

class LiteralResult:
    """What `literal_superset_repair` found: the graph, and how it got there."""

    def __init__(self, graph: DataGraph, pool_subset: Tuple[str, ...],
                 completed_edges: int, trimmed: int, kept: int,
                 subsets_tried: int, checks: int):
        self.graph = graph
        self.pool_subset = pool_subset
        self.completed_edges = completed_edges
        self.trimmed = trimmed              # edges the trimming loop removed
        self.kept = kept                    # edges of E_H \ E_G that survived
        self.subsets_tried = subsets_tried
        self.checks = checks                # consistency checks performed

    def added_edges(self, g: DataGraph) -> Set[Tuple[str, str, str]]:
        return set(self.graph.edges()) - set(g.edges())

    def added_nodes(self, g: DataGraph) -> Set[str]:
        return set(self.graph.nodes) - set(g.nodes)


def literal_superset_repair(g: DataGraph, cs, *, fresh: int = 2
                            ) -> Optional[LiteralResult]:
    """Algorithm 2 as written: saturate, check, then trim.

    Returns a consistent supergraph of `g`, or `None` when no subset of the pool
    yields one -- which is the algorithm's own answer that no superset repair exists
    over that pool, not a failure of this code.

    The outer loop runs over every subset `S'` of the value pool. For each,
    `H = build_graph(g, S', Sigma_e)`; a completed graph that is already inconsistent
    is discarded and the next subset tried, since trimming only ever removes edges and
    removing edges from an inconsistent graph cannot be relied on to reach consistency.
    The trimming loop then walks `E_H \\ E_G` in a fixed canonical order -- sorted
    `(src, label, dst)` -- removing an edge when `H - e` stays consistent and restoring
    it when it does not. The first `H` that survives is returned.

    Two remarks on the trimming loop's second condition. The paper requires the result
    to remain a supergraph of `G`; restricting the loop to `E_H \\ E_G` makes that
    automatic rather than tested, and the harness asserts it afterwards anyway. And
    nodes are never removed: the paper's second loop deletes edges, and the added
    value nodes that end up isolated are left in place, so the node counts reported
    for this side and for the engine (whose pruning pass does drop isolated added
    nodes) are not directly comparable and are reported separately.
    """
    core = core_constraints(cs)
    labels = edge_alphabet(g, core)
    pool = value_pool(core, fresh=fresh)
    base_edges = set(g.edges())
    subsets_tried = checks = 0

    for subset in subsets_by_size(pool):
        subsets_tried += 1
        h = build_graph(g, set(subset), labels)
        completed = h.num_edges()
        validator = Validator(h, use_closure=True)     # live reference to h
        checks += 1
        if not is_consistent(h, core, validator):
            continue

        addable = sorted(set(h.edges()) - base_edges)
        trimmed = 0
        for edge in addable:
            h.remove_edge(*edge)
            checks += 1
            if is_consistent(h, core, validator):
                trimmed += 1
            else:
                h.add_edge(*edge)
        return LiteralResult(h, subset, completed, trimmed,
                             len(addable) - trimmed, subsets_tried, checks)
    return None
