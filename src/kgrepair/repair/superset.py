"""
D6 -- SupersetRepair (Algorithm 2).

Implements Algorithm 2 of Abriola, Martinez, Pardal, Cifuentes & Pin Baque
(JAIR 76:721-759, 2023) on the D4 toolkit: repair a data-graph under positive node
constraints by ADDITION -- never deletion, never value rewrite -- drawing any needed
values from a bounded pool.

Interface:

    superset_repair(G, ConstraintSet) -> SupersetRepairResult(graph=H, changelog=...)

Scope decision (D6, from the P4/T0 findings; an open design question).
SupersetRepair acts on EVERY `tier == "ptime_core"` constraint, regardless of
`direction`. `direction` is a default repair-mode *preference*, not a capability
limit: every ptime_core consequent is a positive node expression, hence satisfiable
by addition (`Constraint.addition_fixable`). In particular existential
domain/range violations are fixed by ADDING the missing type edge to the
constraint-named class C, not by deleting the
endpoint. Boundary constraints are never touched. SubsetRepair (Alg. 1) is entirely
unchanged and still keys on `direction == "subset"`.

What we add for each consequent shape (all values from the bounded pool, sec.10):
  * tau_C  = <down(type).down(subClassOf)*.[val(C)]>   -> add  x -type-> C
             (C is a constraint-named constant; the class node is self-valued C and
             is materialised if absent -- a NEW pool node, never a value rewrite).
  * <down(P)>   (existential / requires-statement)     -> add  x -P-> t, where t is
             the constraint's single reused fresh symbol (or a named value if the
             constraint names one). Fresh symbols are node ids; they carry no value.
  * disjunction <down(P1)> | <down(P2)>                 -> satisfy the left disjunct.
  * inheritance <down(type).[val(C)]>                   -> add  x -type-> C.

Set-at-a-time fixpoint (mirrors the D5 lesson).
  Each round snapshots the full witness set across all core constraints on the
  current graph H_k, computes the complete addition set for that round, applies it,
  and re-evaluates. Additions are monotone on antecedents, so a round can CREATE new
  witnesses (a node newly typed City now matches a requires-statement antecedent; a
  fresh edge target is now the value of an existential-range predicate). This cascade
  is expected and terminates: the candidate additions live over the bounded pool
  (existing nodes + named class nodes + <=2 fresh per constraint), a finite set, and
  every productive round applies at least one new node/edge. `_MAX_ROUNDS` is a
  termination-bug detector (a planner that fails to satisfy its own witness), not a
  tuning knob.

  The <=2-fresh-per-constraint pool generalises Lemma 21's construction rather than
  reproducing it: Lemma 21 (and the buildGraph set S = Sigma^R_n u {c, d}) needs only
  two fresh values IN TOTAL, whereas this engine mints two per constraint
  (`fresh:<cid>:<n>`, bound 2*|R|). This is a safe generalisation -- a larger finite
  pool cannot lose a repair the smaller one would have found -- and the per-constraint
  symbols buy attributability (which constraint a fresh node serves) and deterministic
  naming. See docs/algorithm_fidelity.md for the paper-line-to-code mapping.

Never modifies D(v): the only `set_value` is to materialise an ABSENT named class
node with its own constant value (that is adding a pool node, not rewriting an
existing value); the attestation `data_values_unmodified` verifies every originally
present node keeps its original value.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from ..constraints.model import Constraint, ConstraintSet
from ..datagraph import DataGraph
from ..gxpath import ast
from ..validator import Validator
from .subset import ChangeRecord

_FRESH_CAP = 2   # <= 2 fresh symbols per constraint


class NoSupersetPlan(Exception):
    """A consequent shape SupersetRepair cannot satisfy by addition (e.g. a bare
    value-equality consequent, which would require rewriting D(v))."""


@dataclass
class SupersetRepairResult:
    """What `superset_repair` returns: the repaired supergraph and its audit trail.

    `graph` is the repaired supergraph H, `changelog` the ordered record of every
    addition, `pool` the sizes of the bounded value pool the additions were drawn
    from, and `attestations` the self-checks the engine asserted about its own
    output (additions only, fresh symbols within bound, values unmodified,
    consistent afterwards). `to_dict()` is the canonical JSON serialisation shared
    by the CLI and the viewer.
    """
    graph: DataGraph                       # the repaired supergraph H
    changelog: List[ChangeRecord]
    added_nodes: Set[str]
    added_edges: Set[Tuple[str, str, str]]
    rounds: int
    attestations: Dict[str, bool]
    pool: Dict[str, int]                   # value-pool sizes (instrumentation)
    additions_by_kind: Dict[str, int]
    additions_by_constraint: Dict[str, int]
    fresh_used: List[str]
    pruned_edges: int = 0                   # T4 redundancy-pruning removals
    pruned_nodes: int = 0
    mode: str = "superset"

    @property
    def changed(self) -> bool:
        return bool(self.changelog)

    def changelog_dicts(self) -> List[Dict]:
        return [r.to_dict() for r in self.changelog]

    def changelog_json(self, indent: int = 2) -> str:
        return json.dumps(self.changelog_dicts(), indent=indent)

    def to_dict(self) -> Dict:
        """Full-result JSON schema (V0/viewer): the one canonical serialisation any
        consumer (CLI or viewer) of a superset-repair run should emit, so the two
        never drift into parallel formats."""
        return {
            "mode": self.mode,
            "rounds": self.rounds,
            "added_nodes": sorted(self.added_nodes),
            "added_edges": sorted(self.added_edges),
            "pool": dict(self.pool),
            "additions_by_kind": dict(self.additions_by_kind),
            "additions_by_constraint": dict(self.additions_by_constraint),
            "fresh_used": list(self.fresh_used),
            "pruned_edges": self.pruned_edges,
            "pruned_nodes": self.pruned_nodes,
            "attestations": dict(self.attestations),
            "changelog": self.changelog_dicts(),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def core_constraints(constraints) -> List[Constraint]:
    """Every ptime_core constraint -- SupersetRepair's scope (all directions)."""
    cs = constraints.constraints if isinstance(constraints, ConstraintSet) else list(constraints)
    return [c for c in cs if c.tier == "ptime_core"]


 
# value pool
 

def _value_consts(n: ast.Node, acc: Set[str]) -> None:
    if isinstance(n, ast.ValueEq):
        acc.add(n.const)
    elif isinstance(n, ast.Has):
        _value_consts_path(n.path, acc)
    elif isinstance(n, (ast.Conj, ast.Disj)):
        _value_consts(n.left, acc)
        _value_consts(n.right, acc)


def _value_consts_path(p: ast.Path, acc: Set[str]) -> None:
    if isinstance(p, (ast.Seq, ast.Alt, ast.Isect)):
        _value_consts_path(p.left, acc)
        _value_consts_path(p.right, acc)
    elif isinstance(p, ast.Star):
        _value_consts_path(p.inner, acc)
    elif isinstance(p, ast.Test):
        _value_consts(p.node, acc)


def named_constants(core: List[Constraint]) -> Set[str]:
    """All val("c") constants named across the core constraints (the class nodes and
    literal endpoints that superset repair may introduce)."""
    acc: Set[str] = set()
    for c in core:
        _value_consts(c.phi, acc)
        _value_consts(c.psi, acc)
    return acc


class _Alloc:
    """Deterministic fresh-symbol allocator for one constraint, capped at `_FRESH_CAP`.
    Existential additions reuse a single fresh target ("not proliferated"), so a
    constraint normally consumes exactly one fresh symbol."""

    def __init__(self, cid: str):
        self.cid = cid
        self._issued: Dict[str, str] = {}

    def fresh(self, slot: str = "t") -> str:
        if slot not in self._issued:
            if len(self._issued) >= _FRESH_CAP:
                raise AssertionError(
                    f"fresh-symbol cap ({_FRESH_CAP}) exceeded for constraint {self.cid}")
            self._issued[slot] = f"fresh:{self.cid}:{len(self._issued)}"
        return self._issued[slot]

    @property
    def used(self) -> List[str]:
        return sorted(self._issued.values())


 
# addition planner: additions that make witness x satisfy consequent psi
 

# One planned addition:  ("node", node_id, value_or_None, provenance)
#                    or  ("edge", src, label, dst, provenance)
_PlanNode = Tuple[str, str, Optional[str], str]
_PlanEdge = Tuple[str, str, str, str, str]


def _linearize(path: ast.Path) -> List[ast.Path]:
    """Flatten a left-nested Seq into a list of atomic steps (Down/Up/Star/Test/Eps)."""
    if isinstance(path, ast.Seq):
        return _linearize(path.left) + _linearize(path.right)
    return [path]


def _pin_value(steps: List[ast.Path]) -> Optional[str]:
    """Scanning the zero-hop tail after a real hop, the value the hop's target must
    carry (from a Test(val(C))), or None if the target is unconstrained. A further
    real hop before any value test means the target is not directly value-pinned."""
    for s in steps:
        if isinstance(s, (ast.Down, ast.Up)):
            return None
        if isinstance(s, ast.Test) and isinstance(s.node, ast.ValueEq):
            return s.node.const
        # Star / Eps / Test(non-value) are zero-hop and value-neutral -> keep scanning
    return None


def _plan_has(path: ast.Path, x: str, alloc: _Alloc, g: DataGraph) -> List:
    """Additions so that some `path`-walk departs from x."""
    steps = _linearize(path)
    adds: List = []
    cur = x
    i = 0
    while i < len(steps):
        step = steps[i]
        if isinstance(step, (ast.Eps, ast.Star)):
            i += 1
            continue
        if isinstance(step, ast.Test):
            # A value test on the current node: satisfiable only if cur already carries
            # it (we never rewrite values). If not, this shape is not addition-fixable.
            if isinstance(step.node, ast.ValueEq) and g.value(cur) != step.node.const:
                raise NoSupersetPlan(f"value test [{step.node.const}] on existing node {cur}")
            i += 1
            continue
        if isinstance(step, ast.Down):
            val = _pin_value(steps[i + 1:])
            if val is not None:
                adds.append(("node", val, val, "named"))          # class node, self-valued
                adds.append(("edge", cur, step.label, val, "named"))
                cur = val
                i = len(steps)                                    # tail is zero-hop; done
            else:
                t = alloc.fresh()
                adds.append(("node", t, None, "fresh"))           # fresh symbol, no value
                adds.append(("edge", cur, step.label, t, "fresh"))
                cur = t
                i += 1
            continue
        if isinstance(step, ast.Up):
            # <up(a)>: cur must be the TARGET of an a-edge -> add a fresh source.
            val = _pin_value(steps[i + 1:])
            src = val if val is not None else alloc.fresh("s")
            if val is not None:
                adds.append(("node", val, val, "named"))
            else:
                adds.append(("node", src, None, "fresh"))
            adds.append(("edge", src, step.label, cur, "named" if val else "fresh"))
            cur = src
            i += 1 if val is None else len(steps)
            continue
        raise NoSupersetPlan(f"unsupported path step {step!r}")
    return adds


def _plan_node(psi: ast.Node, x: str, alloc: _Alloc, g: DataGraph) -> List:
    """Additions making witness x satisfy the positive node consequent psi."""
    if isinstance(psi, ast.Top):
        return []
    if isinstance(psi, ast.Has):
        return _plan_has(psi.path, x, alloc, g)
    if isinstance(psi, ast.Conj):
        return _plan_node(psi.left, x, alloc, g) + _plan_node(psi.right, x, alloc, g)
    if isinstance(psi, ast.Disj):
        return _plan_node(psi.left, x, alloc, g)              # deterministic left disjunct
    if isinstance(psi, ast.ValueEq):
        if g.value(x) == psi.const:
            return []
        raise NoSupersetPlan(f"bare value consequent [{psi.const}] cannot be added")
    raise NoSupersetPlan(f"unsupported node consequent {psi!r}")


 
# engine
 

def _max_rounds(g: DataGraph, core: List[Constraint]) -> int:
    # generous bound: cascades are shallow; each productive round applies >=1 addition
    # over a finite pool. If this trips, a planner failed to satisfy its own witness.
    return 100 + 10 * len(core) + len(g.nodes)


def superset_repair(graph: DataGraph, constraints, *, in_place: bool = False,
                    use_closure: bool = True,
                    prune: bool = True) -> SupersetRepairResult:
    """
    Compute a superset (addition-only) repair of `graph` under the ptime_core
    constraints in `constraints`. Returns a `SupersetRepairResult`; the input graph is
    left untouched unless `in_place=True`.

    Additions are drawn from the bounded value pool (graph values + constraint-named
    constants + <=2 fresh symbols per constraint). The result is the *deterministic
    canonical addition repair with redundancy pruning*; it is NOT claimed to be a
    minimal or unique-minimal repair -- that wording is deliberately not asserted.
    `use_closure` toggles the evaluator's OPT-2 subClassOf* memoisation; no result change.

    `prune` (default True) runs the T4 redundancy-pruning post-pass: added edges are
    revisited in a stable canonical order and dropped when the graph stays ptime_core
    consistent without them (e.g. a redundant `-type-> Geo` once `-type-> City` is
    present and City subclasses Geo). With `prune=False` the result is exactly the
    saturation-phase output.
    """
    core = core_constraints(constraints)
    g = graph if in_place else graph.clone()
    original_values = {v: graph.value(v) for v in graph.nodes}

    validator = Validator(g, use_closure=use_closure)   # live ref to g
    allocs = {c.cid: _Alloc(c.cid) for c in core}
    changelog: List[ChangeRecord] = []
    added_nodes: Set[str] = set()
    added_edges: Set[Tuple[str, str, str]] = set()
    by_kind: Dict[str, int] = {"add_node": 0, "add_edge": 0}
    by_constraint: Dict[str, int] = {c.cid: 0 for c in core}

    max_rounds = _max_rounds(g, core)
    rnd = 0
    while True:
        rnd += 1
        if rnd > max_rounds:
            raise AssertionError(
                f"superset_repair did not reach a fixpoint in {max_rounds} rounds; "
                f"a planner is likely failing to satisfy its witness (termination bug)")

        # snapshot witnesses across every core constraint on the current graph
        witness_of: Dict[Tuple[str, str], Constraint] = {}
        for c in core:
            for x in validator.check_one(c).witnesses:
                witness_of.setdefault((c.cid, x), c)
        if not witness_of:
            break

        # compute the complete addition set for this round, then apply it
        new_in_round = 0
        for (cid, x), c in sorted(witness_of.items()):
            for plan in _plan_node(c.psi, x, allocs[cid], g):
                if plan[0] == "node":
                    _, nid, val, prov = plan
                    if nid not in g.nodes:
                        g.add_node(nid, value=val)
                        added_nodes.add(nid)
                        by_kind["add_node"] += 1
                        by_constraint[cid] += 1
                        new_in_round += 1
                        changelog.append(ChangeRecord(
                            "add_node", rnd, cid, node=nid, witness=x, provenance=prov))
                else:
                    _, s, lab, d, prov = plan
                    if d not in g.succ(lab, s):
                        g.add_edge(s, lab, d)
                        added_edges.add((s, lab, d))
                        by_kind["add_edge"] += 1
                        by_constraint[cid] += 1
                        new_in_round += 1
                        changelog.append(ChangeRecord(
                            "add_edge", rnd, cid, src=s, label=lab, dst=d,
                            witness=x, provenance=prov))

        if new_in_round == 0:
            # witnesses remain but nothing new could be added: plans do not resolve
            # them. Stop (consistent_after will report False) rather than spin.
            break

    pruned_e = pruned_n = 0
    # Only prune a consistent repair; pruning is a no-op on a failed (still-inconsistent)
    # saturation, whose invariants would otherwise be checked against a partial graph.
    if prune and all(validator.check_one(c).count == 0 for c in core):
        changelog, added_nodes, added_edges, pruned_e, pruned_n = _prune(
            g, core, changelog, added_nodes, added_edges, validator)
        by_kind = {"add_node": sum(1 for r in changelog if r.op == "add_node"),
                   "add_edge": sum(1 for r in changelog if r.op == "add_edge")}
        by_constraint = {c.cid: 0 for c in core}
        for r in changelog:
            by_constraint[r.constraint] = by_constraint.get(r.constraint, 0) + 1

    fresh_used = sorted(f for a in allocs.values() for f in a.used
                        if f in g.nodes)
    pool = {
        "graph_values": len({v for v in original_values.values() if v is not None}),
        "named_constants": len(named_constants(core)),
        "fresh_used": len(fresh_used),
        "fresh_bound": _FRESH_CAP * len(core),
    }
    attestations = _attest(g, original_values, core, changelog, fresh_used,
                           _FRESH_CAP * len(core), validator)
    return SupersetRepairResult(
        graph=g, changelog=changelog, added_nodes=added_nodes, added_edges=added_edges,
        rounds=rnd, attestations=attestations, pool=pool,
        additions_by_kind=by_kind, additions_by_constraint=by_constraint,
        fresh_used=fresh_used, pruned_edges=pruned_e, pruned_nodes=pruned_n,
    )


def _prune(g: DataGraph, core: List[Constraint], changelog: List[ChangeRecord],
           added_nodes: Set[str], added_edges: Set[Tuple[str, str, str]],
           validator: Validator):
    """
    Redundancy pruning (T4). Revisit added edges in a stable canonical order
    (round, constraint, src, label, dst); drop an edge iff the graph stays ptime_core
    consistent without it, otherwise restore it. Then drop any added node left with no
    incident edge. Deterministic by construction (fixed visitation order), so two runs
    give the identical pruned graph and change log. This is redundancy pruning, NOT a
    minimality guarantee, and is not claimed as one.
    Returns (changelog', added_nodes', added_edges', n_pruned_edges, n_pruned_nodes).
    """
    def _consistent() -> bool:
        return all(validator.check_one(c).count == 0 for c in core)

    edge_recs = [r for r in changelog if r.op == "add_edge"]
    edge_recs.sort(key=lambda r: (r.round, r.constraint, r.src, r.label, r.dst))
    pruned_edges: Set[Tuple[str, str, str]] = set()
    for r in edge_recs:
        e = (r.src, r.label, r.dst)
        if r.dst not in g.succ(r.label, r.src):
            continue                                  # already gone
        g.remove_edge(*e)
        if _consistent():
            pruned_edges.add(e)
        else:
            g.add_edge(*e)                            # needed -> restore

    kept_edges = added_edges - pruned_edges
    pruned_nodes: Set[str] = set()
    for n in sorted(added_nodes):
        if n not in g.nodes:
            continue
        incident = any(g.succ(lab, n) or g.pred(lab, n) for lab in g.labels)
        if not incident:
            g.remove_node(n)
            pruned_nodes.add(n)
    kept_nodes = added_nodes - pruned_nodes

    new_changelog = [
        r for r in changelog
        if (r.op == "add_edge" and (r.src, r.label, r.dst) not in pruned_edges)
        or (r.op == "add_node" and r.node not in pruned_nodes)
    ]
    return new_changelog, kept_nodes, kept_edges, len(pruned_edges), len(pruned_nodes)


def _attest(g: DataGraph, original_values: Dict[str, Optional[str]],
            core: List[Constraint], changelog: List[ChangeRecord],
            fresh_used: List[str], fresh_bound: int,
            validator: Validator) -> Dict[str, bool]:
    """Record the invariants D6 must preserve; a False here marks the run FAILED."""
    add_only = all(r.op in ("add_node", "add_edge") for r in changelog)
    within_bound = len(fresh_used) <= fresh_bound
    values_ok = all(g.value(v) == original_values[v]
                    for v in original_values if v in g.nodes)
    consistent = all(validator.check_one(c).count == 0 for c in core)
    return {
        "superset_only_added": add_only,
        "fresh_values_within_bound": within_bound,
        "data_values_unmodified": values_ok,
        "consistent_after": consistent,
    }
