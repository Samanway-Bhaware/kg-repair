"""
D5 -- SubsetRepair (Algorithm 1).

Implements Algorithm 1 of Abriola, Martinez, Pardal, Cifuentes & Pin Baque
(JAIR 76:721-759, 2023) on the D4 toolkit: it computes the Algorithm-1 fixpoint,
the deterministic canonical witness-deletion repair of a data-graph under positive
node constraints, found by a monotone deletion loop. (The paper's Theorem 15
states this fixpoint is the *unique* subset repair under its node-expression
hypothesis; whether that uniqueness transfers to the containment semantics this
toolkit uses is an open design question -- see the NOTE below.)

Interface:

    subset_repair(G, ConstraintSet) -> SubsetRepairResult(graph=G', changelog=...)

Contract:
  * Act ONLY on constraints with  tier == "ptime_core"  and  direction == "subset".
    (superset-direction ptime_core rules are Algorithm 2's job; boundary rules are
    validated/reported only and never touched here.)
  * Delete each witness node  x in  [[phi]] \\ [[psi]]  -- `DataGraph.remove_node`
    cascades every incident edge -- and iterate to a fixpoint.
  * Never modify  D(v): the engine calls no value setter.
  * Emit a structured change log: one record per node/edge removed.

Set-at-a-time deletion (why the result is order-independent).
  Positive node expressions are monotone (Lemma 13): for  G' subset-of G,
  [[phi]]_{G'} subset-of [[phi]]_G. Deleting a node therefore never *creates* a
  fresh member of any  [[phi]], so no deletion can turn a previously-satisfied node
  into a NEW witness of a rule it wasn't already implicated in via  [[psi]].

  We nonetheless delete *set-at-a-time*, not witness-by-witness: each round
  computes the full witness set  W_k = union over eligible (phi<=psi) of
  [[phi]]_{G_k} \\ [[psi]]_{G_k}  on the current graph  G_k, then removes all of
  W_k at once to obtain  G_{k+1}. This matters for determinism -- deleting one
  witness can pull another candidate out of a  [[phi]]  (e.g. deleting a country's
  country edge), so a witness-by-witness loop would depend on visitation order.
  Because  G_{k+1}  is a function of  G_k  alone (remove exactly  W_k), the
  descending chain  G_0 ⊇ G_1 ⊇ ...  and its fixpoint are independent of the order
  constraints or witnesses are visited.

  Deletion is still a *loop*, not a single pass: removing a node can pull another
  node out of some  [[psi]]  while it stays in  [[phi]], creating a fresh witness
  in the NEXT round (e.g. deleting the class node that made a country a country).
  Each productive round deletes at least one node and  |V|  is finite, so the loop
  terminates in at most  |V|  rounds -- a counting argument (this is also how the
  paper bounds it). Theorem 14 is what makes each round's deletion safe under the
  paper's node-expression hypothesis: it gives Rep(G, R) = Rep(G restricted to
  V \\ V_bot, R), so removing the witness set never discards a repairable node.

  NOTE (open design question): this computes the fixpoint of witness-node
  deletion, which is deterministic but is not always the SUBSET-MAXIMAL consistent
  subgraph -- when a witness only fails because of a deletable *supporting* edge,
  deleting the supporter's other endpoint can be a strictly larger repair. The
  design specifies witness-node deletion, so we implement that; the earlier
  "unique maximal repair" wording should be reconciled with this. See test
  `test_fixpoint_catches_witness_created_by_a_deletion`.

Two strategies (`subset_repair(..., strategy=...)`):

  * "full" -- the baseline: every round re-evaluates every eligible constraint over
    the whole current graph. Deliberately simple; the differential-testing oracle.

  * "incremental" (OPT-1) -- dirty-set re-check: after a round deletes a witness set,
    only constraints whose label alphabet intersects the set of *removed edge labels*
    are re-evaluated next round; the rest keep their (necessarily unchanged) cached
    witness sets. This is a sound conservative over-approximation:

      - A witness of  c  is the source of a path over  labels(c), so it carries a
        labels(c) edge; deleting it removes a labels(c) edge -> c is re-checked.
      - A *new* witness requires some node to leave  [[psi_c]], which (by
        monotonicity, deletion never grows  [[phi]]) can only happen if a labels(c)
        edge was removed -> c is re-checked.
      - If no labels(c) edge was removed, neither  [[phi_c]]  nor  [[psi_c]]  changed,
        so  c's witness set is unchanged and safe to skip.

    Dirty-ness is per *constraint*, not per (constraint, node): our evaluator is
    set-at-a-time (whole-graph sparse pre-image), so a re-checked constraint is
    re-evaluated in full. Per-node incremental evaluation would need a node-at-a-time
    evaluator and is deferred. `recheck_count` (constraint evaluations) lets the two
    strategies be compared; the two MUST return identical (deleted set, final graph,
    change log) -- guarded by the differential suite.

Default is "full" until the incremental path is trusted by profiling; both are
kept so the differential test always has its oracle.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from ..constraints.model import Constraint, ConstraintSet
from ..datagraph import DataGraph
from ..gxpath import ast
from ..validator import Validator


@dataclass
class ChangeRecord:
    """
    One structural mutation. `op` is "remove_node"/"remove_edge" (SubsetRepair) or
    "add_node"/"add_edge" (SupersetRepair). The `witness`/`provenance` fields are only
    populated for add ops (D6) -- remove-op serialisation is unchanged, so the D5
    change-log format is byte-for-byte preserved.
    """

    op: str
    round: int
    constraint: str            # cid of the constraint whose witness triggered this
    node: Optional[str] = None                 # remove_node / add_node
    src: Optional[str] = None                  # remove_edge / add_edge
    label: Optional[str] = None
    dst: Optional[str] = None
    witness: Optional[str] = None              # add ops: the witness node this serves
    provenance: Optional[str] = None           # add ops: value-pool origin graph|named|fresh

    def to_dict(self) -> Dict:
        base = {"op": self.op, "round": self.round, "constraint": self.constraint}
        if self.op in ("remove_node", "add_node"):
            base["node"] = self.node
        else:
            base["src"], base["label"], base["dst"] = self.src, self.label, self.dst
        if self.op.startswith("add"):
            base["witness"] = self.witness
            base["provenance"] = self.provenance
        return base


@dataclass
class SubsetRepairResult:
    """What `subset_repair` returns: the repaired subgraph and its audit trail.

    `graph` is the repaired subgraph G', `changelog` the ordered record of every
    deletion, and `attestations` the self-checks the engine asserted about its own
    output (deletion-only, values unmodified, consistent afterwards). `to_dict()`
    is the canonical JSON serialisation shared by the CLI and the viewer.
    """
    graph: DataGraph                    # the repaired subgraph G'
    changelog: List[ChangeRecord]
    deleted_nodes: Set[str]
    rounds: int                         # worklist passes incl. the final no-op verify pass
    recheck_count: int                  # constraint evaluations (full-recompute cost signal)
    attestations: Dict[str, bool]
    mode: str = "full"

    @property
    def changed(self) -> bool:
        return bool(self.changelog)

    def changelog_dicts(self) -> List[Dict]:
        return [r.to_dict() for r in self.changelog]

    def changelog_json(self, indent: int = 2) -> str:
        return json.dumps(self.changelog_dicts(), indent=indent)

    def to_dict(self) -> Dict:
        """Full-result JSON schema (V0/viewer): the one canonical serialisation any
        consumer (CLI or viewer) of a subset-repair run should emit, so the two never
        drift into parallel formats."""
        return {
            "mode": self.mode,
            "rounds": self.rounds,
            "recheck_count": self.recheck_count,
            "deleted_nodes": sorted(self.deleted_nodes),
            "attestations": dict(self.attestations),
            "changelog": self.changelog_dicts(),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def eligible_constraints(constraints) -> List[Constraint]:
    """The ptime_core, subset-direction constraints -- the only ones D5 acts on."""
    cs = constraints.constraints if isinstance(constraints, ConstraintSet) else list(constraints)
    return [c for c in cs if c.tier == "ptime_core" and c.direction == "subset"]


def _path_labels(p: ast.Path, acc: Set[str]) -> None:
    if isinstance(p, (ast.Down, ast.Up)):
        acc.add(p.label)
    elif isinstance(p, (ast.Seq, ast.Alt, ast.Isect)):
        _path_labels(p.left, acc)
        _path_labels(p.right, acc)
    elif isinstance(p, ast.Star):
        _path_labels(p.inner, acc)
    elif isinstance(p, ast.Test):
        _node_labels(p.node, acc)
    # ast.Eps carries no label


def _node_labels(n: ast.Node, acc: Set[str]) -> None:
    if isinstance(n, ast.Has):
        _path_labels(n.path, acc)
    elif isinstance(n, (ast.Conj, ast.Disj)):
        _node_labels(n.left, acc)
        _node_labels(n.right, acc)
    # ast.Top and ast.ValueEq carry no edge label


def constraint_labels(c: Constraint) -> Set[str]:
    """Every edge label mentioned in the constraint's antecedent or consequent."""
    acc: Set[str] = set()
    _node_labels(c.phi, acc)
    _node_labels(c.psi, acc)
    return acc


def _incident_edges(g: DataGraph, x: str) -> List[Tuple[str, str, str]]:
    """Every edge touching x as (src, label, dst); self-loops counted once."""
    edges: List[Tuple[str, str, str]] = []
    for label in sorted(g.labels):
        for dst in sorted(g.succ(label, x)):
            edges.append((x, label, dst))
        for src in sorted(g.pred(label, x)):
            if src == x:
                continue  # self-loop already captured as an out-edge
            edges.append((src, label, x))
    return edges


def subset_repair(graph: DataGraph, constraints, *, in_place: bool = False,
                  strategy: str = "full", use_closure: bool = False) -> SubsetRepairResult:
    """
    Compute the subset repair of `graph` under the ptime_core/subset constraints in
    `constraints`. Returns a `SubsetRepairResult`; the input graph is left untouched
    unless `in_place=True`.

    `strategy` selects the re-check policy -- "full" (baseline oracle) or
    "incremental" (OPT-1 dirty-set). Both compute the identical repair; they differ
    only in `recheck_count`. `use_closure` enables the evaluator's OPT-2 subClassOf*
    memoisation; it too must not change the result. See the module docstring.

    Determinism: each round's witness set is computed on the current graph before
    any deletion, so the deleted node set and final graph are order-independent (the
    change log is emitted in sorted order for a canonical serialisation).
    """
    if strategy not in ("full", "incremental"):
        raise ValueError(f"unknown strategy {strategy!r}")

    eligible = eligible_constraints(constraints)
    labels_of = {c.cid: constraint_labels(c) for c in eligible}
    g = graph if in_place else graph.clone()
    original_values = {v: graph.value(v) for v in graph.nodes}  # snapshot for attestation

    # One validator/evaluator for the whole loop: its OPT-2 closure cache persists
    # across rounds and is invalidated precisely when a spine edge is deleted.
    validator = Validator(g, use_closure=use_closure)  # live ref to g; sees deletions
    changelog: List[ChangeRecord] = []
    deleted: Set[str] = set()
    witnesses: Dict[str, Set[str]] = {c.cid: set() for c in eligible}
    dirty: Set[str] = {c.cid for c in eligible}   # round 1: everything is dirty
    recheck = 0
    rnd = 0

    while True:
        rnd += 1
        # Re-evaluate: every eligible constraint under "full"; only dirty ones under
        # "incremental". Non-dirty constraints keep their cached (unchanged) witnesses.
        to_check = eligible if strategy == "full" else [c for c in eligible if c.cid in dirty]
        for c in to_check:
            recheck += 1
            witnesses[c.cid] = set(validator.check_one(c).witnesses)

        # Snapshot the full witness set on the current graph BEFORE deleting anything.
        witness_of: Dict[str, str] = {}   # node -> cid of the first rule that flags it
        for c in eligible:
            for x in witnesses[c.cid]:
                witness_of.setdefault(x, c.cid)
        if not witness_of:
            break  # fixpoint: no eligible constraint has a witness

        removed_labels: Set[str] = set()
        for x in sorted(witness_of):
            cid = witness_of[x]
            for (s, l, d) in _incident_edges(g, x):
                removed_labels.add(l)
                changelog.append(ChangeRecord("remove_edge", rnd, cid, src=s, label=l, dst=d))
            g.remove_node(x)
            changelog.append(ChangeRecord("remove_node", rnd, cid, node=x))
            deleted.add(x)

        # Drop deleted nodes from every cache; recompute which constraints are dirty.
        for c in eligible:
            witnesses[c.cid] = {w for w in witnesses[c.cid] if w in g.nodes}
        if strategy == "full":
            dirty = {c.cid for c in eligible}
        else:
            dirty = {c.cid for c in eligible if labels_of[c.cid] & removed_labels}

    attestations = _attest(g, original_values, eligible, changelog, validator)
    return SubsetRepairResult(
        graph=g,
        changelog=changelog,
        deleted_nodes=deleted,
        rounds=rnd,
        recheck_count=recheck,
        attestations=attestations,
        mode=strategy,
    )


def _attest(g: DataGraph, original_values: Dict[str, Optional[str]],
            eligible: List[Constraint], changelog: List[ChangeRecord],
            validator: Validator) -> Dict[str, bool]:
    """Record the invariants D5 must preserve; a False here marks the run FAILED."""
    subset_only = all(r.op in ("remove_node", "remove_edge") for r in changelog)
    values_ok = all(g.value(v) == original_values.get(v) for v in g.nodes)
    consistent = all(validator.check_one(c).count == 0 for c in eligible)
    return {
        "subset_only_deleted": subset_only,
        "data_values_unmodified": values_ok,
        "consistent_after": consistent,
    }
