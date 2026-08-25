"""
D6 · T3 -- correctness gates on the synthetic ground-truth harness.

The generator's injection menu already covers every superset-fixable violation type:
all four synthetic constraints are ptime_core (hence addition_fixable), and the
generator injects one of each (existential domain/range de-typing, typing removal,
requires-statement removal). The generator re-certifies its own injection accounting
on every `generate` call, so no menu change is needed for D6; these tests add the
superset-repair guarantees on top.

Property tests over >=300 seeds:
  * after superset_repair, zero ptime_core violations;
  * additions only (no deletion, no value rewrite);
  * fresh-symbol count <= 2 * |ptime_core constraints|;
  * determinism under constraint-order reversal;
  * every injected witness is resolved by an addition that references it;
  * cross-engine: subset and superset each reach ptime_core consistency (by deletion
    and by addition respectively) and, when the graph had violations, differ by design.
"""

from kgrepair.constraints.model import ConstraintSet
from kgrepair.repair import subset_repair, superset_repair
from kgrepair.synthetic import generate
from kgrepair.validator import Validator


SEEDS = 300
EDGES = 200

def _core(cs):
    return [c for c in cs if c.tier == "ptime_core"]


def _core_witnessed(g, cs):
    rep = Validator(g, use_closure=True).validate(cs)
    return sum(v.count for v in rep.failing() if v.constraint.tier == "ptime_core")


def test_superset_resolves_all_ptime_core_over_seeds():
    for seed in range(SEEDS):
        sl = generate(seed, EDGES)
        cs = sl.constraints
        res = superset_repair(sl.graph, cs)
        assert res.attestations["consistent_after"], seed
        assert res.attestations["superset_only_added"], seed
        assert res.attestations["data_values_unmodified"], seed
        assert res.attestations["fresh_values_within_bound"], seed
        assert len(res.fresh_used) <= 2 * len(_core(cs)), seed
        assert _core_witnessed(res.graph, cs) == 0, seed


def test_every_injected_witness_is_resolved_by_a_referencing_addition():
    for seed in range(SEEDS):
        sl = generate(seed, EDGES)
        res = superset_repair(sl.graph, sl.constraints)
        witnessed = {r.witness for r in res.changelog if r.op.startswith("add")}
        for gt in sl.ground_truth:
            assert gt["witness_node"] in witnessed, (seed, gt)


def test_determinism_under_constraint_order_reversal_over_seeds():
    for seed in range(SEEDS):
        sl1 = generate(seed, EDGES)
        sl2 = generate(seed, EDGES)          # identical graph (deterministic)
        core = _core(sl1.constraints)
        fwd = ConstraintSet("fwd", list(core))
        rev = ConstraintSet("rev", list(reversed(core)))
        r1 = superset_repair(sl1.graph, fwd)
        r2 = superset_repair(sl2.graph, rev)
        assert set(r1.graph.edges()) == set(r2.graph.edges()), seed
        assert r1.changelog_dicts() == r2.changelog_dicts(), seed


def test_cross_engine_both_reach_consistency_but_differ():
    differed = 0
    for seed in range(SEEDS):
        sl_sub = generate(seed, EDGES)
        sl_sup = generate(seed, EDGES)       # identical graph
        cs = sl_sub.constraints
        sub = subset_repair(sl_sub.graph, cs, in_place=True, use_closure=True)
        sup = superset_repair(sl_sup.graph, cs, in_place=True)
        # subset reaches ptime_core/subset consistency; superset reaches ALL ptime_core
        assert _core_witnessed(sup.graph, cs) == 0, seed
        assert sub.attestations["consistent_after"], seed
        # both changed the graph (there were injected violations), and differently:
        # subset deleted, superset added -> the graphs are not equal
        if sub.changed and sup.changed:
            assert set(sub.graph.edges()) != set(sup.graph.edges()), seed
            differed += 1
    assert differed > 0
