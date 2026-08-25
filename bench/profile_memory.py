"""
T4: measure-only memory profile of the existing dict-of-dicts DataGraph.

No backend swap, no prototype -- this only measures peak RSS, load time, and
resident bytes/edge for the current backend at 1k / 10k / 100k / 1M edges, using
T5 synthetic slices, recording each run through the T1 harness.

Two measurements per rung:
  * resident bytes/edge  -- tracemalloc current-memory delta around building the
    graph (generation transients are freed on return), divided by |E|.
  * a recorded RunContext consistency run  -- timings + peak RSS into results/.

Usage:  python bench/profile_memory.py [--max-rung 100000]
"""
import argparse
import gc
import os
import sys
import time
import tracemalloc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kgrepair.instrument import RunContext, constraints_meta, slice_meta_from_graph
from kgrepair.synthetic import generate
from kgrepair.validator import Validator

RESULTS = os.path.join(os.path.dirname(__file__), "..", "results")
RUNGS = [1_000, 10_000, 100_000, 1_000_000]


def _resident_bytes_per_edge(seed, target):
    gc.collect()
    tracemalloc.start()
    base = tracemalloc.get_traced_memory()[0]
    sl = generate(seed=seed, target_edges=target)
    g = sl.graph
    gc.collect()
    resident = tracemalloc.get_traced_memory()[0] - base
    tracemalloc.stop()
    return resident, g.num_edges(), g.stats()["nodes"]


def _recorded_run(seed, target):
    with RunContext(RESULTS, slice={}, constraints=constraints_meta(generate(
            seed=seed, target_edges=1).constraints), mode="consistency") as run:
        with run.phase("load"):
            sl = generate(seed=seed, target_edges=target)
        run.slice = slice_meta_from_graph(sl.graph, source="synthetic",
                                          manifest_hash=sl.manifest["content_hash"],
                                          seed=seed, params={"target_edges": target},
                                          hierarchy_depth=sl.manifest["hierarchy_depth"])
        run.constraints = constraints_meta(sl.constraints)
        with run.phase("consistency_initial"):
            Validator(sl.graph).validate(sl.constraints)
    return run.record


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rung", type=int, default=1_000_000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    print(f"{'target':>10} {'V':>9} {'E':>10} {'resident_MB':>12} "
          f"{'bytes/edge':>11} {'peak_rss_MB':>12} {'load_s':>8}")
    for rung in RUNGS:
        if rung > args.max_rung:
            break
        try:
            resident, edges, nodes = _resident_bytes_per_edge(args.seed, rung)
            t0 = time.perf_counter()
            rec = _recorded_run(args.seed, rung)
            load_s = rec["timings_s"].get("load", time.perf_counter() - t0)
            bpe = resident / max(1, edges)
            print(f"{rung:>10} {nodes:>9} {edges:>10} {resident/1e6:>12.1f} "
                  f"{bpe:>11.1f} {rec['resources']['peak_rss_bytes']/1e6:>12.1f} "
                  f"{load_s:>8.3f}")
        except MemoryError:
            print(f"{rung:>10}  MemoryError -- STOP; report and do not swap backend")
            break

    print(f"\nRecords appended to {os.path.relpath(RESULTS)}/runs.jsonl")


if __name__ == "__main__":
    main()
