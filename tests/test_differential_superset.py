"""
Comparison 1 of the differential oracle: the constructive planner against
Algorithm 2 as written.

`tests/reference_superset.py` holds the literal Algorithm 2 -- `buildGraph`
saturating every ordered pair of nodes under every label, then the trimming loop.
This module runs it and `kgrepair.repair.superset.superset_repair` over the same
seeded corpus of small graphs and compares them, at the one scale where both fit.

Only comparison 1. The oracle as designed has three comparisons:
this one, the greatest-consistent-subgraph search against the subset engine, and the
inclusion-minimality rate of the pruned superset output. The other two are not
attempted here and nothing below should be read as evidence about them.

What is asserted, and what is only measured
-------------------------------------------
The two outputs are **not** expected to be edge-identical, and a harness asserting
equality would produce a wall of false failures. Fresh symbols are named
`fresh:<cid>:<n>` on one side and `lemma21:c` on the other; the trimming loop and
the pruning pass visit edges in different canonical orders, so two different
irredundant results are both legitimate; and the engine is not claimed to be minimal
in the first place. So:

  A  existence agreement -- assertion, and the load-bearing one. When the literal
     algorithm returns a graph the engine returns a consistent result, and when it
     returns `None` the engine refuses. A disagreement here is a finding about the
     planner's completeness, to be reported and not smoothed over.
  B  both outputs consistent on `ptime_core` under the same validator -- assertion.
  C  both outputs supergraphs of `G`, values included -- assertion.
  D  containment: every edge the planner added is an edge `buildGraph` would have
     created, modulo renaming the planner's fresh nodes -- assertion. This is the
     claim Section 4.5.2 makes in passing and never checks.
  E  size -- measured, never asserted. Comparing the two addition counts is
     comparison 3's job and comparison 3 is out of scope.

Reproducibility
---------------
Every case is a seed. `case(seed)` is a pure function of it, so any failure named
in a message reproduces from the seed alone, and `python tests/test_differential_superset.py`
re-runs the whole sweep and prints the summary that `docs/differential_oracle.md`
records.
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import pytest

from kgrepair import DataGraph
from kgrepair.constraints.model import Constraint, ConstraintSet
from kgrepair.repair.superset import (NoSupersetPlan, core_constraints,
                                      named_constants, superset_repair)

from reference_superset import (CompletedGraphTooLarge, MAX_COMPLETED_EDGES,
                                build_graph, core_witness_count, edge_alphabet,
                                is_consistent, literal_superset_repair, value_pool)

 
# the corpus
 

SEEDS = range(200)              #: recorded in docs/differential_oracle.md
TYPE, SUBCLASS = "type", "subClassOf"
DATA_LABELS = ("p", "q", "r")
MISSING_CLASS = "Cx"            #: named by a consequent, absent from the graph
#: Ceiling on distinct `val("...")` constants across a case's constraints. Each one
#: doubles the outer loop, so this is what keeps the literal side affordable; see
#: the scale-guard note in the module docstring of `reference_superset`.
MAX_NAMED_CONSTANTS = 4


def _tau(cls: str) -> str:
    return f'< down({TYPE}) . down({SUBCLASS})* . [val("{cls}")] >'


def _inherit(cls: str) -> str:
    return f'< down({TYPE}) . [val("{cls}")] >'


def _exists(label: str) -> str:
    return f"< down({label}) >"


def case(seed: int) -> Tuple[DataGraph, ConstraintSet]:
    """One graph and its constraint set, a pure function of `seed`.

    Ten to twenty nodes -- entities plus two or three self-valued class nodes, the
    loader's rule for a class -- over two or three data predicates and the two-label
    type spine. "Two or three edge labels" in the Section 4.6 design is read as the
    data predicates: `type` and `subClassOf` are not optional, since the tau_C shape
    is written over them.

    Edge density runs 0.15 to 0.35 over ordered pairs per data label. Roughly seven
    entities in ten carry a type edge, so the rest are the untyped nodes a typing rule
    witnesses. Constraints are two to four, all `ptime_core`, their consequents drawn
    from exactly the four shapes the planner handles (the module docstring of
    `repair/superset.py` lists them): tau_C, the existential, the disjunction and the
    inheritance test. One consequent in four names a class the graph does not contain,
    which is what forces the literal side's outer loop off its first subset.
    """
    rng = random.Random(seed)
    n_classes = rng.randint(2, 3)
    n_entities = rng.randint(10, 20 - n_classes)
    labels = list(DATA_LABELS[:rng.randint(2, 3)])
    density = rng.uniform(0.15, 0.35)
    classes = [f"C{i}" for i in range(n_classes)]

    g = DataGraph()
    for cls in classes:
        g.set_value(cls, cls)                      # class nodes are self-valued
    if rng.random() < 0.7:                         # a subclass spine, sometimes
        for i in range(1, n_classes):
            g.add_edge(classes[i], SUBCLASS, classes[i - 1])

    entities = [f"e{i}" for i in range(n_entities)]
    for e in entities:
        g.add_node(e)
    for label in labels:
        for u in entities:
            for v in entities:
                if u != v and rng.random() < density:
                    g.add_edge(u, label, v)
    for e in entities:
        if rng.random() < 0.7:
            g.add_edge(e, TYPE, rng.choice(classes))

    wanted = rng.randint(2, 4)
    constraints: List[Constraint] = []
    while len(constraints) < wanted:
        antecedent = rng.choice(["T",
                                 _exists(rng.choice(labels)),
                                 _tau(rng.choice(classes)),
                                 _inherit(rng.choice(classes))])
        shape = rng.choice(["tau", "exists", "disj", "inherit"])
        cls = rng.choice(classes) if rng.random() > 0.25 else MISSING_CLASS
        if shape == "tau":
            consequent = _tau(cls)
        elif shape == "inherit":
            consequent = _inherit(cls)
        elif shape == "exists":
            consequent = _exists(rng.choice(labels))
        else:
            a, b = rng.sample(labels, 2)
            consequent = f"{_exists(a)} | {_exists(b)}"
        if antecedent == consequent:
            continue                               # a tautology says nothing
        constraints.append(Constraint(
            cid=f"seed{seed}-c{len(constraints)}", domain="oracle", kg="oracle",
            kind=shape, tier="ptime_core", provenance="authored",
            direction="superset", antecedent=antecedent, consequent=consequent))
    return g, ConstraintSet(f"oracle-seed-{seed}", constraints)


 
# hand-built cases where no superset repair exists over the pool
 

def no_repair_cases() -> List[Tuple[str, DataGraph, ConstraintSet]]:
    """Cases the pool cannot repair, so that A is checked in both directions.

    A superset repair adds nodes and edges and never writes a value onto a node that
    already exists. A consequent demanding a value of an existing node is therefore
    unreachable for both sides: the engine raises `NoSupersetPlan`, and no subset of
    the pool yields a consistent completed graph, since `buildGraph` adds values only
    on the nodes it creates. Without these the sweep would only ever exercise the
    agreement that a repair exists.
    """
    out = []

    g = DataGraph()
    for i in range(6):
        g.add_edge(f"e{i}", "p", f"e{(i + 1) % 6}")
    out.append(("bare-value-consequent", g, ConstraintSet("no-repair-1", [
        Constraint(cid="nr1", domain="oracle", kg="oracle", kind="value",
                   tier="ptime_core", provenance="authored", direction="superset",
                   antecedent="T", consequent='val("k")')])))

    g2 = DataGraph()
    g2.set_value("C0", "C0")
    for i in range(6):
        g2.add_edge(f"e{i}", "p", f"e{(i + 1) % 6}")
    out.append(("value-consequent-with-a-satisfiable-neighbour", g2, ConstraintSet(
        "no-repair-2", [
            Constraint(cid="nr2a", domain="oracle", kg="oracle", kind="tau",
                       tier="ptime_core", provenance="authored", direction="superset",
                       antecedent=_exists("p"), consequent=_tau("C0")),
            Constraint(cid="nr2b", domain="oracle", kg="oracle", kind="value",
                       tier="ptime_core", provenance="authored", direction="superset",
                       antecedent=_exists("p"), consequent='val("k")')])))
    return out


 
# one comparison
 

@dataclass
class Comparison:
    """Everything one case produced, so a failure reports numbers and not a boolean."""
    seed: object
    nodes: int
    edges: int
    labels: int
    constraints: int
    named_constants: int
    already_consistent: bool
    literal_found: bool
    literal_added_edges: int = 0
    literal_added_nodes: int = 0
    literal_pool_subset: Tuple[str, ...] = ()
    literal_completed_edges: int = 0
    literal_checks: int = 0
    literal_trimmed: int = 0
    planner_ok: bool = False
    planner_refusal: Optional[str] = None
    planner_added_edges: int = 0
    planner_added_nodes: int = 0
    planner_fresh_used: int = 0
    planner_pruned_edges: int = 0
    disagreements: List[str] = field(default_factory=list)
    seconds_literal: float = 0.0
    seconds_planner: float = 0.0

    @property
    def size_gap(self) -> Optional[int]:
        if not (self.literal_found and self.planner_ok):
            return None
        return self.planner_added_edges - self.literal_added_edges


def _supergraph_faults(g: DataGraph, h: DataGraph, side: str) -> List[str]:
    """C, for one output: nothing of `G` gone, no value of `G` changed."""
    faults = []
    missing_nodes = set(g.nodes) - set(h.nodes)
    if missing_nodes:
        faults.append(f"{side} dropped nodes {sorted(missing_nodes)[:5]}")
    missing_edges = set(g.edges()) - set(h.edges())
    if missing_edges:
        faults.append(f"{side} dropped edges {sorted(missing_edges)[:5]}")
    for v in g.nodes:
        if v in h.nodes and h.value(v) != g.value(v):
            faults.append(f"{side} rewrote D({v}): {g.value(v)!r} -> {h.value(v)!r}")
            break
    return faults


def _containment_faults(g: DataGraph, core, added: Set[Tuple[str, str, str]],
                        fresh_used: List[str]) -> List[str]:
    """D: every planner addition is an edge `buildGraph` would have created.

    The planner's fresh nodes carry names `buildGraph` never mints, so they are
    renamed onto the pool's fresh values first, injectively and in sorted order. The
    pool is widened to hold as many fresh values as the planner actually consumed
    rather than the paper's two, because the engine's per-constraint allocator is a
    generalisation of Lemma 21's pool and this check must not assume the two coincide;
    how far it ranged is reported separately, as `planner_fresh_used`.

    What survives the renaming is the real content of the claim: the planner never
    introduces a node outside the bounded pool, and never an edge label outside
    `Sigma_e`.
    """
    labels = edge_alphabet(g, core)
    fresh_pool = max(2, len(fresh_used))
    pool = value_pool(core, fresh=fresh_pool)
    completed = build_graph(g, set(pool), labels)
    rename = {old: new for old, new in
              zip(sorted(fresh_used), [v for v in pool if v.startswith("lemma21:")])}

    faults = []
    for src, label, dst in sorted(added):
        u, v = rename.get(src, src), rename.get(dst, dst)
        if v not in completed.succ(label, u):
            faults.append(f"planner added {(src, label, dst)} -> {(u, label, v)}, "
                          f"not an edge of buildGraph(G, S)")
    return faults[:5]


def compare(seed, g: DataGraph, cs: ConstraintSet) -> Comparison:
    """Run both sides on one case and record A-E. Never asserts; the tests do that."""
    core = core_constraints(cs)
    rec = Comparison(seed=seed, nodes=len(g.nodes), edges=g.num_edges(),
                     labels=len(edge_alphabet(g, core)), constraints=len(core),
                     named_constants=len(named_constants(core)),
                     already_consistent=is_consistent(g, core),
                     literal_found=False)

    t0 = time.perf_counter()
    literal = literal_superset_repair(g, cs)
    rec.seconds_literal = time.perf_counter() - t0

    t0 = time.perf_counter()
    try:
        planner = superset_repair(g, cs)
    except NoSupersetPlan as exc:
        planner, rec.planner_refusal = None, str(exc)
    rec.seconds_planner = time.perf_counter() - t0

    if literal is not None:
        rec.literal_found = True
        rec.literal_added_edges = len(literal.added_edges(g))
        rec.literal_added_nodes = len(literal.added_nodes(g))
        rec.literal_pool_subset = literal.pool_subset
        rec.literal_completed_edges = literal.completed_edges
        rec.literal_checks = literal.checks
        rec.literal_trimmed = literal.trimmed
    if planner is not None:
        rec.planner_ok = bool(planner.attestations["consistent_after"])
        rec.planner_added_edges = len(planner.added_edges)
        rec.planner_added_nodes = len(planner.added_nodes)
        rec.planner_fresh_used = len(planner.fresh_used)
        rec.planner_pruned_edges = planner.pruned_edges

    # A -- existence agreement
    if rec.literal_found != rec.planner_ok:
        rec.disagreements.append(
            f"A existence: literal={'repair' if rec.literal_found else 'none'}, "
            f"planner={'repair' if rec.planner_ok else (rec.planner_refusal or 'inconsistent')}")

    # B -- both consistent on ptime_core
    if literal is not None and not is_consistent(literal.graph, core):
        rec.disagreements.append(
            f"B literal output retains {core_witness_count(literal.graph, core)} witnesses")
    if rec.planner_ok and not is_consistent(planner.graph, core):
        rec.disagreements.append(
            f"B planner output retains {core_witness_count(planner.graph, core)} witnesses")

    # C -- both supergraphs of G
    if literal is not None:
        rec.disagreements += _supergraph_faults(g, literal.graph, "literal")
    if planner is not None:
        rec.disagreements += _supergraph_faults(g, planner.graph, "planner")

    # D -- containment of the planner's additions in buildGraph's edges
    if planner is not None and planner.added_edges:
        rec.disagreements += _containment_faults(g, core, planner.added_edges,
                                                 planner.fresh_used)
    return rec


 
# the sweep, run once and shared
 

_SWEEP: Optional[Dict] = None


def sweep() -> Dict:
    """Run every case once; memoised so the assertions below share one execution."""
    global _SWEEP
    if _SWEEP is not None:
        return _SWEEP
    t0 = time.perf_counter()
    records = [compare(seed, *case(seed)) for seed in SEEDS]
    hand = [compare(name, g, cs) for name, g, cs in no_repair_cases()]
    _SWEEP = {"records": records, "hand": hand,
              "seconds": time.perf_counter() - t0}
    return _SWEEP


def _all(s: Dict) -> List[Comparison]:
    return s["records"] + s["hand"]


 
# A-D: assertions
 

def test_a_existence_agreement():
    """The load-bearing claim: the two sides agree about whether a repair exists."""
    bad = [r for r in _all(sweep())
           if any(d.startswith("A ") for d in r.disagreements)]
    assert not bad, "existence disagreements:\n" + "\n".join(
        f"  seed {r.seed}: {'; '.join(r.disagreements)}" for r in bad)


def test_b_both_outputs_consistent():
    bad = [r for r in _all(sweep())
           if any(d.startswith("B ") for d in r.disagreements)]
    assert not bad, "inconsistent outputs:\n" + "\n".join(
        f"  seed {r.seed}: {'; '.join(r.disagreements)}" for r in bad)


def test_c_both_outputs_are_supergraphs():
    bad = [r for r in _all(sweep())
           if any(d.startswith(("literal ", "planner ")) and "buildGraph" not in d
                  for d in r.disagreements)]
    assert not bad, "supergraph faults:\n" + "\n".join(
        f"  seed {r.seed}: {'; '.join(r.disagreements)}" for r in bad)


def test_d_planner_additions_are_contained_in_buildgraph():
    """Section 4.5.2's claim that the planner selects from what `buildGraph` builds."""
    bad = [r for r in _all(sweep())
           if any("buildGraph" in d for d in r.disagreements)]
    assert not bad, "containment faults:\n" + "\n".join(
        f"  seed {r.seed}: {'; '.join(r.disagreements)}" for r in bad)


 
# the corpus is what it says it is
 

def test_corpus_shape_matches_the_design():
    for r in sweep()["records"]:
        assert 10 <= r.nodes <= 20, r.seed
        assert 2 <= r.constraints <= 4, r.seed
        assert r.named_constants <= MAX_NAMED_CONSTANTS, r.seed


def test_corpus_covers_the_consistent_and_the_unrepairable():
    s = sweep()
    consistent = [r for r in s["records"] if r.already_consistent]
    assert consistent, "no already-consistent graph in the corpus"
    for r in consistent:
        assert r.planner_added_edges == 0, (r.seed, r.planner_added_edges)
    assert s["hand"], "no unrepairable case in the corpus"
    for r in s["hand"]:
        assert not r.literal_found and not r.planner_ok, r.seed


def test_scale_guard_refuses_a_corpus_sized_completion():
    """The guard is part of the story: the oracle cannot attempt what 4.5.1 rules out."""
    g = DataGraph()
    for i in range(200):
        g.add_edge(f"n{i}", "a", f"n{(i + 1) % 200}")
    with pytest.raises(CompletedGraphTooLarge) as exc:
        build_graph(g, {"c", "d"}, {"a", "b", "c"})
    assert exc.value.edges > MAX_COMPLETED_EDGES
    assert exc.value.edges > 100_000


def test_largest_completion_materialised_stays_under_the_guard():
    largest = max(r.literal_completed_edges for r in _all(sweep()))
    assert 0 < largest <= MAX_COMPLETED_EDGES


 
# the oracle's own correctness
 
# An oracle that is wrong makes every comparison above worthless, so the literal
# side is checked against a graph small enough to work out on paper, the way
# `tests/search_fixtures.py` backs the reference enumerator. If these and the hand
# count ever disagree, the hand count is the appeal.

def test_build_graph_is_the_complete_graph_and_mutates_nothing():
    g = DataGraph()
    g.add_edge("a", "p", "b")
    g.set_value("C0", "C0")
    h = build_graph(g, set(), {"p", "type"})
    assert sorted(h.nodes) == ["C0", "a", "b"]
    assert h.num_edges() == 3 * 3 * 2          # every ordered pair, both labels
    for label in ("p", "type"):
        for u in h.nodes:
            assert h.succ(label, u) == set(h.nodes)
    assert h.value("C0") == "C0" and h.value("a") is None
    assert g.num_edges() == 1 and sorted(g.nodes) == ["C0", "a", "b"]


def test_build_graph_adds_one_self_valued_node_per_pool_value():
    g = DataGraph()
    g.add_node("a")
    h = build_graph(g, {"C0", "C1"}, {"p"})
    assert sorted(h.nodes) == ["C0", "C1", "a"]
    assert h.value("C0") == "C0" and h.value("C1") == "C1"
    assert h.num_edges() == 3 * 3


def test_literal_repair_matches_a_hand_worked_case():
    """Three nodes, no edges, `T` must reach a node valued C0 through type.subClassOf*.

    `buildGraph` over the empty pool gives 18 edges; the trimming loop walks them in
    sorted `(src, label, dst)` order and removes fourteen. Working the order through
    by hand leaves exactly the four below, and it leaves them because a *later* edge
    in the order is doing the work an earlier one was refused for: `C0` keeps only its
    type edge to `b`, and `b` keeps the one subClassOf edge that carries `C0`'s own
    path home. That is the algorithm as written, and this is the case that says so.
    """
    g = DataGraph()
    g.set_value("C0", "C0")
    g.add_node("a")
    g.add_node("b")
    cs = ConstraintSet("hand", [Constraint(
        cid="hand-1", domain="oracle", kg="oracle", kind="tau", tier="ptime_core",
        provenance="authored", direction="superset", antecedent="T",
        consequent=_tau("C0"))])
    result = literal_superset_repair(g, cs)
    assert result is not None
    assert sorted(result.added_edges(g)) == [
        ("C0", "type", "b"), ("a", "type", "b"),
        ("b", "subClassOf", "C0"), ("b", "type", "b")]
    assert (result.completed_edges, result.trimmed) == (18, 14)
    assert result.pool_subset == ()


def test_literal_repair_returns_none_when_the_pool_cannot_reach_it():
    _, g, cs = no_repair_cases()[0]
    assert literal_superset_repair(g, cs) is None
    with pytest.raises(NoSupersetPlan):
        superset_repair(g, cs)


def test_the_two_sides_share_one_pool_and_one_consistency_predicate():
    """The only things the oracle imports from the engine, and the reason it does."""
    g, cs = case(0)
    core = core_constraints(cs)
    assert set(value_pool(core, fresh=0)) == named_constants(core)
    assert is_consistent(g, core) == (core_witness_count(g, core) == 0)


 
# E: measured, not asserted
 

def summary() -> Dict:
    """The numbers `docs/differential_oracle.md` records."""
    s = sweep()
    rows = _all(s)
    seeded = s["records"]
    paired = [r for r in rows if r.size_gap is not None]
    gaps = sorted(r.size_gap for r in paired)
    hist: Dict[int, int] = {}
    for gap in gaps:
        hist[gap] = hist.get(gap, 0) + 1
    return {
        "cases": len(rows),
        "seeded_cases": len(s["records"]),
        "hand_cases": len(s["hand"]),
        "seed_range": [min(SEEDS), max(SEEDS)],
        "seconds": round(s["seconds"], 2),
        "seconds_literal": round(sum(r.seconds_literal for r in rows), 2),
        "seconds_planner": round(sum(r.seconds_planner for r in rows), 3),
        # ranges describe the seeded corpus; the two hand-built cases are smaller by
        # design and would otherwise widen every bound below their stated design.
        "nodes": [min(r.nodes for r in seeded), max(r.nodes for r in seeded)],
        "edges": [min(r.edges for r in seeded), max(r.edges for r in seeded)],
        "labels": [min(r.labels for r in seeded), max(r.labels for r in seeded)],
        "constraints": [min(r.constraints for r in seeded),
                        max(r.constraints for r in seeded)],
        "named_constants": [min(r.named_constants for r in seeded),
                            max(r.named_constants for r in seeded)],
        "already_consistent": sum(1 for r in rows if r.already_consistent),
        "already_consistent_seeds": [r.seed for r in seeded if r.already_consistent],
        "already_consistent_literal_additions": sorted(
            r.literal_added_edges for r in rows if r.already_consistent),
        "literal_found": sum(1 for r in rows if r.literal_found),
        "planner_ok": sum(1 for r in rows if r.planner_ok),
        "disagreements": {str(r.seed): r.disagreements for r in rows if r.disagreements},
        "largest_completion": max(r.literal_completed_edges for r in rows),
        "guard_ceiling": MAX_COMPLETED_EDGES,
        "total_consistency_checks": sum(r.literal_checks for r in rows),
        "pool_subset_beyond_empty": sum(1 for r in rows if r.literal_pool_subset),
        "fresh_used_max": max(r.planner_fresh_used for r in rows),
        "fresh_beyond_lemma21": sum(1 for r in rows if r.planner_fresh_used > 2),
        "size": {
            "paired": len(paired),
            "equal": sum(1 for g in gaps if g == 0),
            "planner_larger": sum(1 for g in gaps if g > 0),
            "planner_smaller": sum(1 for g in gaps if g < 0),
            "gap_min": gaps[0] if gaps else None,
            "gap_max": gaps[-1] if gaps else None,
            "gap_mean": round(sum(gaps) / len(gaps), 2) if gaps else None,
            "gap_median": gaps[len(gaps) // 2] if gaps else None,
            "histogram": dict(sorted(hist.items())),
            "literal_total": sum(r.literal_added_edges for r in paired),
            "planner_total": sum(r.planner_added_edges for r in paired),
        },
    }


def test_e_size_is_measured_and_reported():
    """E is a measurement, so the only assertion is that it was taken."""
    m = summary()["size"]
    assert m["paired"] > 0
    assert m["equal"] + m["planner_larger"] + m["planner_smaller"] == m["paired"]


if __name__ == "__main__":                                   # pragma: no cover
    print(json.dumps(summary(), indent=2, default=str))
