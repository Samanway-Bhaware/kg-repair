"""
T6: the size ladder, end-to-end on T5 synthetic slices.

Per rung: load -> initial consistency -> subset_repair -> final consistency, all
through the T1 harness (append-only results/runs.jsonl). full vs incremental at 10k
and 100k gives the first real OPT-1 payoff measurement. Repair correctness at scale
is cross-checked against T5 ground truth: every injected subset-direction witness
must be handled (absent from the repaired graph), and the subset-direction
attestations must all pass.

OPT-2 closure is enabled for every ladder run (verified equal to traversal), so
full-vs-incremental isolates OPT-1.

Usage:  python bench/run_ladder.py [--max-rung 1000000]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kgrepair.instrument import (RunContext, constraints_meta, render_table,
                                 slice_meta_from_graph, summarise_strategies,
                                 summarise_timing)
from kgrepair.repair import eligible_constraints, subset_repair
from kgrepair.synthetic import generate
from kgrepair.validator import Validator

RESULTS = os.path.join(os.path.dirname(__file__), "..", "results")

# (target_edges, strategies to run). 1M repair is a stretch (full only).
LADDER = [
    (1_000,     ["full"]),
    (10_000,    ["full", "incremental"]),
    (100_000,   ["full", "incremental"]),
    (1_000_000, ["full"]),
]


def _cross_check(sl, res):
    """Every injected subset-direction witness must be handled (gone); the
    superset-direction ones are not D5's job and are expected to remain."""
    subset_cids = {c.cid for c in eligible_constraints(sl.constraints)}
    gt_subset = {r["witness_node"] for r in sl.ground_truth
                 if r["constraint_id"] in subset_cids}
    survivors = gt_subset & set(res.graph.nodes)
    if survivors:
        raise AssertionError(f"unhandled subset witnesses: {sorted(survivors)[:5]}")
    return len(gt_subset)


def _run(seed, target, strategy):
    mode = f"subset_{strategy}"
    # load INSIDE the context so peak_traced (and bytes/edge) captures the graph.
    with RunContext(RESULTS, slice={}, constraints={}, mode=mode) as run:
        with run.phase("load"):
            sl = generate(seed=seed, target_edges=target)
        g = sl.graph
        run.slice = slice_meta_from_graph(
            g, source="synthetic", manifest_hash=sl.manifest["content_hash"],
            seed=seed, params={"target_edges": target, "closure": True},
            hierarchy_depth=sl.manifest["hierarchy_depth"])
        run.constraints = constraints_meta(sl.constraints)
        with run.phase("consistency_initial"):
            before = Validator(g, use_closure=True).validate(sl.constraints)
        with run.phase("repair_loop"):
            res = subset_repair(g, sl.constraints, in_place=True,
                                strategy=strategy, use_closure=True)
        with run.phase("consistency_final"):
            after = Validator(res.graph, use_closure=True).validate(sl.constraints)
        run.set_repair_result(res, before, after)
    handled = _cross_check(sl, res)
    return run.record, res, handled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rung", type=int, default=1_000_000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    print(f"{'target':>10} {'strategy':>12} {'rounds':>7} {'removed':>8} "
          f"{'recheck':>8} {'handled_gt':>10} {'repair_s':>9} {'status':>7}")
    for target, strategies in LADDER:
        if target > args.max_rung:
            break
        for strat in strategies:
            rec, res, handled = _run(args.seed, target, strat)
            print(f"{target:>10} {strat:>12} {res.rounds:>7} "
                  f"{len(res.deleted_nodes):>8} {res.recheck_count:>8} {handled:>10} "
                  f"{rec['timings_s'].get('repair_loop', 0):>9.3f} {rec['status']:>7}")

    path = os.path.join(RESULTS, "runs.jsonl")
    print("\n== size vs phase time ==")
    print(render_table([r for r in summarise_timing(path)
                        if r["mode"].startswith("subset_")]))
    print("\n== OPT-1 full vs incremental ==")
    print(render_table(summarise_strategies(path)))


if __name__ == "__main__":
    main()
