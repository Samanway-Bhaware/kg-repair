"""
T6: repair correctness at (small) scale, cross-checked against T5 ground truth.

The big ladder run lives in bench/run_ladder.py; this keeps the correctness contract
as a fast regression test.
"""

from kgrepair.repair import eligible_constraints, subset_repair
from kgrepair.synthetic import generate


def test_subset_repair_handles_every_injected_subset_witness():
    for target in (1_000, 10_000):
        sl = generate(seed=1, target_edges=target)
        subset_cids = {c.cid for c in eligible_constraints(sl.constraints)}
        gt_subset = {r["witness_node"] for r in sl.ground_truth
                     if r["constraint_id"] in subset_cids}
        gt_superset = {r["witness_node"] for r in sl.ground_truth
                       if r["constraint_id"] not in subset_cids}
        assert gt_subset and gt_superset            # both kinds were injected

        res = subset_repair(sl.graph, sl.constraints, use_closure=True)
        # every injected subset-direction witness is handled (gone)...
        assert gt_subset.isdisjoint(res.graph.nodes)
        assert res.attestations["consistent_after"] is True
        # ...and the superset-direction witnesses are left for D6 (still present)
        assert gt_superset <= set(res.graph.nodes)


def test_full_equals_incremental_and_closure_on_synthetic_slice():
    sl = generate(seed=2, target_edges=5_000)
    variants = [subset_repair(sl.graph, sl.constraints, strategy=s, use_closure=uc)
                for s in ("full", "incremental") for uc in (False, True)]
    base = variants[0]
    for v in variants[1:]:
        assert v.deleted_nodes == base.deleted_nodes
        assert v.changelog_dicts() == base.changelog_dicts()
    assert base.attestations["consistent_after"] is True
