"""
D7/C2 -- OPT-2 (subClassOf* closure) deep-spine micro-benchmark.

`docs/performance.md`'s OPT-2 table (24.8 ms traversal vs 6.1 ms closure) predates the
D7 evaluation-consolidation rule that every number must be script-emitted and
re-derivable -- no such script existed. This is that script: a deterministic deep
class-hierarchy spine (a chain of `depth` subClassOf edges) with `leaves` instances
typed at the bottom of the chain, timing `tau_C`'s `type . subClassOf*` evaluation with
`use_closure=False` (traversal) vs `True` (memoised) over `reps` repeated evaluations
(repetition matters: OPT-2's payoff is amortised re-evaluation, not a one-shot cost).

Writes results/opt2_bench.json (overwritten each run -- this is a single deterministic
point measurement, not an accumulating log).

Usage: python bench/bench_opt2.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kgrepair.datagraph import DataGraph                # noqa: E402
from kgrepair.gxpath import Evaluator, parse_node        # noqa: E402

RESULTS = os.path.join(os.path.dirname(__file__), "..", "results")

DEPTH = 300
LEAVES = 500
REPS = 200


def _deep_spine_graph(depth, leaves):
    g = DataGraph()
    classes = [f"C{i}" for i in range(depth)]
    for c in classes:
        g.set_value(c, c)
    for i in range(1, depth):
        g.add_edge(classes[i], "wdt:P279", classes[i - 1])   # deeper -> shallower
    for i in range(leaves):
        inst = f"n{i}"
        g.add_edge(inst, "wdt:P31", classes[-1])              # typed at the deep end
    return g, classes[0]  # root class (the [val(...)] target)


def _time_tau(g, root, use_closure, reps):
    ev = Evaluator(g, use_closure=use_closure)
    expr = parse_node(f'< down(wdt:P31) . down(wdt:P279)* . [val("{root}")] >')
    t0 = time.perf_counter()
    for _ in range(reps):
        result = ev.eval_node(expr)
    elapsed = time.perf_counter() - t0
    return elapsed, len(result)


def main():
    g, root = _deep_spine_graph(DEPTH, LEAVES)
    t_traversal, n_traversal = _time_tau(g, root, use_closure=False, reps=REPS)
    t_closure, n_closure = _time_tau(g, root, use_closure=True, reps=REPS)
    assert n_traversal == n_closure == LEAVES, "closure must not change the result"

    record = {
        "bench": "opt2_deep_spine",
        "depth": DEPTH, "leaves": LEAVES, "reps": REPS,
        "traversal_ms_total": round(t_traversal * 1000, 2),
        "closure_ms_total": round(t_closure * 1000, 2),
        "speedup_x": round(t_traversal / t_closure, 2) if t_closure else None,
        "result_size": n_traversal,
    }
    print(f"depth={DEPTH} leaves={LEAVES} reps={REPS}")
    print(f"  traversal: {record['traversal_ms_total']} ms total ({REPS} evals)")
    print(f"  closure:   {record['closure_ms_total']} ms total ({REPS} evals)")
    print(f"  speedup:   {record['speedup_x']}x")

    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "opt2_bench.json"), "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2)
    print(f"\nwrote {os.path.join(RESULTS, 'opt2_bench.json')}")


if __name__ == "__main__":
    main()
