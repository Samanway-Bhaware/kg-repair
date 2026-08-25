"""
T3 benchmark: the existing label-indexed backward pre-image scales with the number
of *matching-label* edges, not with |E|.

We hold |E| fixed and vary label selectivity. `_in[label][dst]` means a pre-image
over label A never scans B-edges, so a graph where A is rare is far cheaper to
pre-image over A than a graph where A is common -- at the *same* |E|.

Not a load/repair run, so this writes its own artifact (results/bench_index.jsonl)
rather than going through the T1 RunContext (whose modes are load/consistency/repair).

Usage:  python bench/bench_index.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kgrepair.datagraph import DataGraph
from kgrepair.gxpath import Evaluator, parse_node

RESULTS = os.path.join(os.path.dirname(__file__), "..", "results")


def _graph(total_edges, a_fraction, seed=0):
    """total_edges edges; a_fraction of them carry label A, the rest label B."""
    import random
    rng = random.Random(seed)
    g = DataGraph()
    n_a = int(total_edges * a_fraction)
    nodes = [f"n{i}" for i in range(max(2, total_edges // 4))]
    for i in range(total_edges):
        s, d = rng.choice(nodes), rng.choice(nodes)
        g.add_edge(s, "A" if i < n_a else "B", d)
    return g


def _time_preimage(g, reps=25):
    ev = Evaluator(g)
    expr = parse_node("< down(A) >")          # pre-image of all A-edges
    t = time.perf_counter()
    for _ in range(reps):
        res = ev.eval_node(expr)
    return (time.perf_counter() - t) / reps, len(res)


def main():
    total = 200_000
    rows = []
    for a_fraction in (1.0, 0.1, 0.01):
        g = _graph(total, a_fraction)
        a_edges = sum(1 for _s, l, _d in g.edges() if l == "A")
        secs, hits = _time_preimage(g)
        rows.append({
            "bench": "preimage_selectivity",
            "total_edges": total, "a_edges": a_edges,
            "a_fraction": a_fraction, "preimage_ms": round(secs * 1000, 3),
            "result_size": hits,
        })
        print(f"|E|={total}  A-edges={a_edges:>7}  pre(down A)={secs*1000:7.3f} ms  |res|={hits}")

    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "bench_index.jsonl"), "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print("\nReading: at fixed |E|, pre-image time tracks A-edge count, not |E| -> "
          "the _in[label] index gives O(matching edges), not O(|E|).")


if __name__ == "__main__":
    main()
