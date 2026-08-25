"""
P4b/T4: what the two-axis candidate search costs, split by phase.

Four phases, timed separately because they scale on different things:

  * **traversals** -- one backward pre-image per atom and per head, through the
    evaluator. Scales with the graph.
  * **lattice** -- the conjunction lattice. Pure bitset intersection, scales with
    the vocabulary and the antecedent bound, not with the graph.
  * **scoring** -- every body against every head, including dominance and the
    residual pass. Scales with bodies times heads.
  * **impact** -- what accepting a candidate would do to the graph, which is one
    subset repair and one superset repair per candidate through the public
    entry points. Scales with candidates times the graph.

Resident memory is the tracemalloc delta around each phase, measured the same way
`bench/profile_memory.py` measures the backend, so the two tables are comparable.

Rungs. The real geography corpus goes to 10k edges and no further, so the 100k
rung is a synthetic geography-like slice from `kgrepair.synthetic`, generated
deterministically at run time. It is labelled as such in the output and in
`docs/performance.md`; it is not a real slice and is not presented as one.

Usage:  python bench/derive_cost.py [--json results/derive_cost.json]
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
import tracemalloc

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kgrepair.ntriples import load_ntriples_file
from kgrepair.proposals import measure_impact
from kgrepair.constraints.model import Constraint
from kgrepair.search import (Extensions, NodeSpace, SearchConfig, antecedent_lattice,
                             head_axis, residual_widenings, vocabulary)
from kgrepair.synthetic import generate

ROOT = os.path.join(os.path.dirname(__file__), "..")
FIXTURES = os.path.join(ROOT, "fixtures", "real")

#: The same bounds the agreement tests use, so the cost table describes the search
#: the tests actually check.
CONFIG = SearchConfig(min_support=10, min_confidence=0.9, max_antecedent=2, max_path=2)

#: How many candidates to price the impact phase on. Impact is per candidate and
#: independent between candidates, so a sample times the count is the estimate,
#: and measuring all of them at the larger rungs is what the table is about.
IMPACT_SAMPLE = 20


def _rungs():
    yield ("1k (real)", os.path.join(FIXTURES, "real_wikidata_geography_1000.nt"), None)
    yield ("10k (real)", os.path.join(FIXTURES, "real_wikidata_geography_10000.nt"), None)
    yield ("100k (synthetic)", None, 100_000)


def _load(path, target):
    if path is not None:
        return load_ntriples_file(path)
    return generate(seed=0, target_edges=target).graph


class _Phase:
    """Wall time per phase.

    Timing runs with tracemalloc off, deliberately. Tracing every allocation slows
    the phases that allocate most by more than an order of magnitude, which is
    exactly the phases this table is about, so timing under it would measure the
    tracer. Memory is taken in its own pass below.
    """

    def __init__(self):
        self.timings = {}

    def run(self, name, fn):
        gc.collect()
        start = time.perf_counter()
        out = fn()
        self.timings[name] = time.perf_counter() - start
        return out


def _resident(fn):
    """Resident-memory delta around `fn`, measured the way `profile_memory.py`
    measures the backend so the two tables are comparable."""
    gc.collect()
    tracemalloc.start()
    base = tracemalloc.get_traced_memory()[0]
    held = fn()                     # held, so the delta is what the phase retains
    gc.collect()
    resident = tracemalloc.get_traced_memory()[0] - base
    tracemalloc.stop()
    del held
    return resident


def _as_constraint(scored) -> Constraint:
    """A scored candidate as a Constraint, which is what the impact measurement
    takes. Nothing is proposed or approved by building one."""
    return Constraint(cid="cost.probe", domain="geography", kg="wikidata",
                      kind="typing_existence", tier="ptime_core", provenance="mined",
                      direction="superset", antecedent=scored.body_text,
                      consequent=scored.head_text)


def measure(name, graph, cfg=CONFIG, impact_sample=IMPACT_SAMPLE):
    phase = _Phase()
    space = NodeSpace(graph)
    ext = Extensions(graph, space)

    vocab = phase.run("traversals:vocabulary", lambda: vocabulary(graph, cfg))
    phase.run("traversals:atoms",
              lambda: [ext.of(a.text) for a in vocab.atoms])
    bodies = phase.run("lattice",
                       lambda: antecedent_lattice(vocab.atoms, ext, cfg))
    axis = phase.run("scoring:heads",
                     lambda: head_axis(bodies, vocab, ext, cfg))
    widenings = phase.run("scoring:residual",
                          lambda: residual_widenings(axis.near_misses, vocab, ext, cfg))

    sample = axis.admitted[:impact_sample]
    phase.run("impact:sample",
              lambda: [measure_impact(graph, _as_constraint(s)) for s in sample])

    # Memory, in its own pass so the timings above are not measuring the tracer.
    # The whole search is re-run from a fresh node space, which is what a caller
    # pays: the bitsets, the lattice and everything the head axis holds.
    def _whole_search():
        fresh = Extensions(graph, NodeSpace(graph))
        return head_axis(antecedent_lattice(vocab.atoms, fresh, cfg), vocab, fresh, cfg)

    memory = {
        "search": _resident(_whole_search),
        "bitsets": _resident(
            lambda: [Extensions(graph, NodeSpace(graph)).of(a.text) for a in vocab.atoms]),
    }

    per_candidate = (phase.timings["impact:sample"] / len(sample)) if sample else 0.0
    search_total = sum(t for k, t in phase.timings.items() if not k.startswith("impact"))
    return {
        "rung": name,
        "nodes": len(graph.nodes),
        "edges": graph.num_edges(),
        "atoms": len(vocab.atoms),
        "bodies": len(bodies),
        "heads": axis.heads_generated,
        "admitted": len(axis.admitted),
        "widenings": len(widenings),
        "near_misses": len(axis.near_misses),
        "traversals": ext.traversals,
        "timings": {k: round(v, 4) for k, v in phase.timings.items()},
        "memory_bytes": memory,
        "search_total_s": round(search_total, 4),
        "impact_per_candidate_s": round(per_candidate, 4),
        "impact_all_candidates_s": round(per_candidate * len(axis.admitted), 2),
        "impact_share_of_total": round(
            (per_candidate * len(axis.admitted))
            / (search_total + per_candidate * len(axis.admitted)), 4) if search_total else None,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", default=os.path.join(ROOT, "results", "derive_cost.json"))
    args = ap.parse_args(argv)

    rows = []
    for name, path, target in _rungs():
        graph = _load(path, target)
        row = measure(name, graph)
        rows.append(row)
        sys.stdout.write(
            f"{row['rung']:18s} V={row['nodes']:>7} E={row['edges']:>7} "
            f"atoms={row['atoms']:>3} bodies={row['bodies']:>5} heads={row['heads']:>5} "
            f"admitted={row['admitted']:>5}\n"
            f"{'':18s} search {row['search_total_s']:>8.3f}s "
            f"(traversals {row['timings']['traversals:vocabulary'] + row['timings']['traversals:atoms']:.3f}s, "
            f"lattice {row['timings']['lattice']:.3f}s, "
            f"scoring {row['timings']['scoring:heads'] + row['timings']['scoring:residual']:.3f}s)\n"
            f"{'':18s} impact {row['impact_per_candidate_s']:.4f}s/candidate, "
            f"{row['impact_all_candidates_s']:.1f}s for all {row['admitted']}, "
            f"{100 * (row['impact_share_of_total'] or 0):.1f}% of the total\n")

    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump({"config": {"min_support": CONFIG.min_support,
                              "min_confidence": CONFIG.min_confidence,
                              "max_antecedent": CONFIG.max_antecedent,
                              "max_path": CONFIG.max_path},
                   "rows": rows}, fh, indent=2, sort_keys=True)
        fh.write("\n")
    sys.stdout.write(f"wrote {args.json}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
