"""
Sparse evaluator for Reg-GXPath_pos over a DataGraph.

Node expressions denote SETS of nodes; path expressions denote binary relations
on nodes. We never materialise the full V x V relation. Instead paths are
evaluated by *backward pre-image*: given a set T of allowed endpoints, we compute

    pre(a, T) = { x : exists y in T with (x, y) in [[a]] }

so that a node expression <a> (there exists an a-path out of x) is simply the
pre-image of the whole node set:

    [[ <a> ]] = pre(a, V)

Pre-image rules (all set-at-a-time, all sparse):

    pre(eps, T)       = T
    pre(down_a, T)    = a-predecessors of T
    pre(up_a, T)      = a-successors of T
    pre(b . c, T)     = pre(b, pre(c, T))
    pre(b u c, T)     = pre(b, T) u pre(c, T)
    pre(a*, T)        = least fixpoint of  X = T u pre(a, X)
    pre([phi], T)     = T n [[phi]]
    pre(b n c, T)     = bounded: intersect endpoint-tagged reach (see below)

Kleene star terminates because the node set is finite and X only grows; each
round adds at least one node or stops. Intersection of two path relations is the
one construct that can force reasoning over pairs; we handle only the tractable
shape used by our constraints (intersection where at least one side is a bounded
finite path), and raise for anything that would need dense pair enumeration.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Set, Tuple

from . import ast
from ..datagraph import DataGraph


class Evaluator:
    def __init__(self, graph: DataGraph, use_closure: bool = False):
        self.g = graph
        # OPT-2: memoise the pre-image of `Star(Down(label))` (in practice the
        # subClassOf* class hierarchy walk of tau_C) so it becomes a cached lookup
        # instead of a per-witness fixpoint. Keyed by (label, target-set); guarded by
        # the graph's per-label version so a spine mutation transparently rebuilds it.
        self.use_closure = use_closure
        self._star_cache: Dict[Tuple[str, FrozenSet[str]], Tuple[int, Set[str]]] = {}

    # ---- node expressions: return a set of nodes ----------------------------

    def eval_node(self, phi: ast.Node) -> Set[str]:
        if isinstance(phi, ast.Top):
            return set(self.g.nodes)
        if isinstance(phi, ast.ValueEq):
            return self.g.nodes_with_value(phi.const)
        if isinstance(phi, ast.Has):
            # nodes from which some phi.path departs = pre-image of everything
            return self._pre(phi.path, set(self.g.nodes))
        if isinstance(phi, ast.Conj):
            return self.eval_node(phi.left) & self.eval_node(phi.right)
        if isinstance(phi, ast.Disj):
            return self.eval_node(phi.left) | self.eval_node(phi.right)
        raise TypeError(f"not a positive node expression: {phi!r}")

    # ---- path expressions: backward pre-image -------------------------------

    def _pre(self, a: ast.Path, targets: Set[str]) -> Set[str]:
        if not targets:
            # pre of the empty set is empty for every construct
            if isinstance(a, ast.Star):
                return set()  # star still yields T = empty here
            return set()

        if isinstance(a, ast.Eps):
            return set(targets)

        if isinstance(a, ast.Down):
            return self.g.pred_set(a.label, targets)

        if isinstance(a, ast.Up):
            return self.g.succ_set(a.label, targets)

        if isinstance(a, ast.Seq):
            # pre(b . c, T) = pre(b, pre(c, T))
            return self._pre(a.left, self._pre(a.right, targets))

        if isinstance(a, ast.Alt):
            return self._pre(a.left, targets) | self._pre(a.right, targets)

        if isinstance(a, ast.Test):
            return targets & self.eval_node(a.node)

        if isinstance(a, ast.Star):
            if self.use_closure and isinstance(a.inner, ast.Down):
                return self._star_down_closure(a.inner.label, targets)
            # least fixpoint: X0 = T ; X_{n+1} = X_n u pre(inner, X_n)
            reached: Set[str] = set(targets)
            frontier: Set[str] = set(targets)
            while frontier:
                nxt = self._pre(a.inner, frontier) - reached
                reached |= nxt
                frontier = nxt
            return reached

        if isinstance(a, ast.Isect):
            return self._pre_isect(a.left, a.right, targets)

        raise TypeError(f"not a positive path expression: {a!r}")

    def _star_down_closure(self, label: str, targets: Set[str]) -> Set[str]:
        """
        Cached  pre(down(label)*, targets)  (OPT-2).

        Identical to the generic star fixpoint for a single `Down(label)` inner --
        the least fixpoint of  X = targets u pred(label, X)  -- but memoised by
        (label, targets) and reused while the graph's `label_version(label)` is
        unchanged. Deleting a spine node/edge bumps that version (see
        `DataGraph.remove_edge`), so the next call transparently rebuilds. Returns a
        fresh copy so callers can mutate freely.
        """
        key = (label, frozenset(targets))
        version = self.g.label_version(label)
        cached = self._star_cache.get(key)
        if cached is not None and cached[0] == version:
            return set(cached[1])

        reached: Set[str] = set(targets)
        frontier: Set[str] = set(targets)
        while frontier:
            nxt = self.g.pred_set(label, frontier) - reached
            reached |= nxt
            frontier = nxt
        self._star_cache[key] = (version, set(reached))
        return set(reached)

    def _pre_isect(self, b: ast.Path, c: ast.Path, targets: Set[str]) -> Set[str]:
        """
        Bounded intersection of path relations.

        General [[b n c]] needs to agree on the *same* endpoint y for each source
        x, which is a pair-level condition. We support the tractable case our
        constraints actually use: intersect the pre-images endpoint-by-endpoint,
        which is correct whenever the shared target set `targets` is finite and
        given (it always is here -- typically a single [C=] class node or the
        whole node set). This keeps the work sparse and avoids dense V x V pairs.
        """
        out: Set[str] = set()
        for y in targets:
            single = {y}
            src_b = self._pre(b, single)
            if not src_b:
                continue
            src_c = self._pre(c, single)
            out |= (src_b & src_c)
        return out
