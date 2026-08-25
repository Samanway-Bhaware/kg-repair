# Performance and scaling

[← Manual index](README.md)

What the toolkit costs to run, which knobs matter, and where the limits are.

> **Source of numbers.** The citable figures are
> [`docs/evaluation.md`](../evaluation.md) Tables 1–4, regenerated from
> `results/runs.jsonl` with `run_id` traceability.
> [`docs/performance.md`](../performance.md) is the older narrative note with the
> methodology prose; its numbers predate the consolidation. Everything below is
> single-threaded and stdlib-only on one dev machine — **indicative, not a
> controlled study**.

---

## Headline

| Rung | \|V\| | \|E\| | Load | Consistency | Repair | Full pipeline |
|---|---|---|---|---|---|---|
| 1k | 467 | 1 080 | 0.011 s | 0.001 s | 0.002 s | — |
| 10k | 4 667 | 10 860 | 0.101 s | 0.010 s | 0.016 s | — |
| 100k | 46 667 | 108 660 | 1.098 s | 0.102 s | 0.173 s | — |
| **1M** | **466 667** | **1 086 660** | **12.63 s** | **1.15 s** | **1.98 s** | **≈ 17 s** |

The 1M rung completes load → consistency → subset repair → re-check in about
**17 seconds in one process**, at roughly **403 MB** resident for the graph and
about **980 MB** peak RSS.

**Everything scales essentially linearly in |E|.** From 100k to 1M — 11.4× the
edges — initial consistency goes 0.102 → 1.15 s (11.3×) and the repair loop
0.173 → 1.98 s (11.4×). That is the empirical polynomial behaviour the complexity
argument predicts, with no superlinear blow-up: the sparse pre-image evaluator
plus subclass-closure memoisation keep per-round cost proportional to the edges
actually touched.

Repair used 2 rounds at every rung, removing 12 / 132 / 1 332 / 13 332 nodes.
(Injected violations are independent, so no multi-round cascade arises.)

---

## Memory

| Rung | Resident (graph only) | bytes/edge | Peak RSS |
|---|---|---|---|
| 1k | 0.5 MB | 420 | 29.7 MB |
| 10k | 3.9 MB | 359 | 37.1 MB |
| 100k | 40 MB | 370 | 125.7 MB |
| 1M | 403 MB | 371 | 984.3 MB |

Cost per edge is **flat at ~370 bytes from 10k upward**; the 1k figure is
inflated by fixed per-process overhead. Peak RSS is process-wide and moves
between runs on the same machine — treat it as an order of magnitude, not a
constant.

### Two different "bytes per edge"

A trap worth naming, because both numbers are correct:

| Figure | Measures |
|---|---|
| **~370 bytes/edge** | tracemalloc *current* delta around building the graph and nothing else — the cost of **holding** a graph |
| **~547 bytes/edge** (`evaluation.md` Table 2) | tracemalloc *peak* across a whole `RunContext` block — graph construction **plus** initial consistency checking, including the evaluator's intermediate node sets |

The ~180-byte gap is the evaluator's working set, not a disagreement about the
backend. Cite ~370 for holding a graph, ~547 for running a check over one, and
say which you mean.

### Backend conclusion

No backend change is warranted. The plain-dict adjacency representation handles
the 1M rung comfortably on a normal machine. Linear extrapolation puts **10M
edges at ~3.7 GB resident** — feasible on a 16 GB machine, and the point at which
a denser representation (interned node ids, CSR adjacency) would start to pay
off. That is explicitly a future consideration, not implemented.

---

## Tuning knobs

Both are **result-identical** to their defaults, verified differentially by the
test suite. They change running time only.

### `use_closure` — subclass-closure memoisation (OPT-2)

Memoises the pre-image of `Star(Down(label))` — in practice the `subClassOf*`
walk inside every `τ_C` — turning a per-witness fixpoint into a cached lookup.
Keyed by `(label, target-set)`, guarded by the graph's per-label version counter
so a spine mutation transparently rebuilds it.

| `use_closure` | 200 evaluations |
|---|---|
| `False` (traversal) | 24.8 ms |
| `True` (closure) | 6.1 ms |

**~4× on deep-hierarchy repeated evaluations.** Defaults differ by entry point:
`superset_repair` defaults to `True`; `Evaluator`, `Validator`, `validate` and
`subset_repair` default to `False`.

**Turn it on** when you evaluate repeatedly against a deep class hierarchy —
which is most real repair work.

### `strategy` — the dirty-set re-check (OPT-1)

`subset_repair(..., strategy="incremental")` re-evaluates only the constraints
whose label alphabet intersects the set of edge labels removed in the last round.

Measured payoff on geography-like slices: **0%.** At 10k it was 4 vs 4 rechecks
and 0.0158 vs 0.0158 s; at 100k, 4 vs 4 and 0.173 vs 0.176 s.

The reason is structural, not a bug: both subset-direction rules in that slice
key on the same edge label, so every deletion dirties both and the label-keyed
dirty set has nothing to skip.

OPT-1 only pays when subset-direction constraints have **disjoint alphabets** and
deletions are label-localised, or when a repair runs for **many rounds** with each
late round touching few constraints. Neither holds for independent injected
violations.

**The default stays `"full"`**, which is also the differential-testing oracle. A
finer node-level dirty set would be needed before this helps on geography-like
slices, and that is deferred.

### `prune` — superset redundancy pruning

`superset_repair(..., prune=False)` skips the post-pass that drops added edges the
graph stays consistent without. Pruning costs a re-check per candidate edge and
buys a smaller, cleaner result (visible in the `redundant_type_edges` metric).
Default `True`.

---

## Label-indexed adjacency

Already present in `DataGraph` and confirmed to be doing its job: a one-hop
pre-image costs time proportional to the edges *carrying that label*, not to |E|.

| \|E\| | edges with label A | `pre(down A)` |
|---|---|---|
| 200 000 | 199 993 | 17.1 ms |
| 200 000 | 20 000 | 5.1 ms |
| 200 000 | 2 000 | 4.0 ms |

This is why a constraint over a rare predicate stays cheap on a large graph.

---

## Derivation cost

`kgrepair derive` has a very different profile from checking and repairing.

| Rung | \|V\| | \|E\| | atoms | bodies | heads | admitted | widenings |
|---|---|---|---|---|---|---|---|
| 1k (real) | 725 | 1 000 | 24 | 99 | 348 | 249 | 199 |
| 10k (real) | 3 707 | 10 000 | 64 | 495 | 424 | 1 548 | 6 204 |
| 100k (synthetic) | 46 667 | 108 660 | 11 | 38 | 27 | 29 | 7 |

| Rung | traversals | lattice | scoring | search total | resident |
|---|---|---|---|---|---|
| 1k (real) | 0.004 s | 0.000 s | 0.064 s | 0.068 s | 0.27 MB |
| 10k (real) | 0.038 s | 0.002 s | 0.796 s | 0.835 s | 2.31 MB |
| 100k (synthetic) | 0.156 s | 0.000 s | 0.279 s | 0.435 s | 0.01 MB |

Note that the real 10k slice is *more* expensive to search than the synthetic
100k one, despite being ten times smaller. Vocabulary richness, not size, drives
the search: 64 atoms against 11.

### Impact measurement dominates everything

| Rung | per candidate | all candidates | share of total |
|---|---|---|---|
| 1k (real) | 0.008 s | 1.9 s | **96.6%** |
| 10k (real) | 0.012 s | 19.0 s | **95.8%** |
| 100k (synthetic) | 25.79 s | 747.9 s | **99.9%** |

Measuring what each candidate would cost means running **both engines per
candidate**. This is why impact is **deferred by default**: each candidate
carries only its witness count, and the engine numbers are computed for one entry
at the moment somebody reviews it (`fill_impact`, or `--graph` on
`kgrepair review`).

Setting `measure=True` in `derive_candidate_file` restores the eager behaviour
and the 95–99% cost with it.

---

## Why the paper's Algorithm 2 cannot run as written

The paper's `buildGraph` step saturates a **complete graph** over the value pool
before minimising. At real scale that is `|V|² · |labels|` edges:

| Rung | Saturated edges | Approx. size | Actual run |
|---|---|---|---|
| geography-10k | ~1.65 × 10⁸ | ~61 GB | ~17 s / ~403 MB |
| 1M | ~8.71 × 10¹¹ | ~322 TB | — |

The engine therefore uses a **constructive planner**: per witness, it computes
the specific additions that satisfy the consequent, rather than saturating and
then minimising. Every figure above is sourced to a manifest field or a recorded
measurement; the full argument is
[`docs/why_algorithm_2_cannot_run_as_written.md`](../why_algorithm_2_cannot_run_as_written.md).

Whether the constructive planner is an acceptable implementation of Algorithm 2
remains an open design question.

---

## Practical guidance

**Loading dominates at scale.** At the 1M rung, load is 12.6 s of the ~17 s
pipeline. Load once and reuse the `DataGraph` across checks; the repair engines
copy internally unless you pass `in_place=True`.

**Turn on `use_closure` for repeated evaluation** against a deep hierarchy. It
costs nothing and cannot change a result.

**Leave `strategy="full"`** unless your subset-direction constraints genuinely
have disjoint label alphabets.

**Check the cap before the engine, always.** `check_cap` is one pass over the
constraint set; a repair that would touch a quarter of your graph is far more
expensive, and almost certainly wrong.

**Constrain derivation.** `--min-support` and `--min-conf` bound how much the
search proposes, and `--max-antecedent`/`--max-path` bound how hard it looks.
Leave impact deferred.

**Real graphs violate far more than synthetic ones.** Measured violation
prevalence on the real corpus ran roughly **10×** the synthetic rate, and three
slices exceeded the 20% deletion cap outright. Budget for `ABORTED-BY-CAP` as a
normal outcome on real data, and read it as a signal to use superset repair or
revisit the constraints — not as a failure.

---

## Reproducing the numbers

```bash
python bench/run_ladder.py          # the size ladder
python bench/profile_memory.py      # memory measurements
python bench/bench_index.py         # label-index measurements
python scripts/build_evaluation.py  # regenerate docs/evaluation.md + figures
```

`scripts/build_evaluation.py` needs the `eval` extra (matplotlib). It is
reporting tooling, not part of the toolkit — nothing under `src/kgrepair/`
imports a third-party package, and that must stay true.

All measurements are recorded in `results/runs.jsonl` with a `run_id`, so every
table in `docs/evaluation.md` traces back to the runs behind it.

---

Next: [Repair engines](repair-engines.md) · [Troubleshooting](troubleshooting.md)
