# Published data

This repository ships the knowledge-graph slices the evaluation was run on **and**
the repaired graphs the two engines produced from them, so every number in
[`docs/evaluation.md`](docs/evaluation.md) can be traced to a file you can open.

The code is MIT-licensed. **The data is not** — each slice inherits the terms of the
source it was extracted from, and so does every repaired graph derived from it. See
the scope note at the bottom of [`LICENSE`](LICENSE), and the per-slice column below.

---

## Source slices — `fixtures/real/`

Level-0 filtered, deterministically sliced from a cached fetch. Each `.nt` file has a
companion `.manifest.json` recording its seeds, frontier rule, allow-list id and hash,
query hashes, and a content hash.

| slice | source | domain | V | E | licence |
|---|---|---|---|---|---|
| `real_wikidata_geography_1000.nt` | wikidata | geography | 725 | 1000 | CC0 1.0 |
| `real_wikidata_geography_10000.nt` | wikidata | geography | 3707 | 10000 | CC0 1.0 |
| `real_wikidata_taxa_1000.nt` | wikidata | taxa | 570 | 1000 | CC0 1.0 |
| `real_wikidata_taxa_10000.nt` | wikidata | taxa | 3612 | 10000 | CC0 1.0 |
| `real_wikidata_anatomy_1000.nt` | wikidata | anatomy | 503 | 1000 | CC0 1.0 |
| `real_wikidata_anatomy_1000_typed.nt` | wikidata | anatomy | 1538 | 4180 | CC0 1.0 |
| `real_wikidata_disease_1000.nt` | wikidata | disease | 664 | 1000 | CC0 1.0 |
| `real_wikidata_medication_1000.nt` | wikidata | medication | 653 | 1000 | CC0 1.0 |
| `real_wikidata_medication_1000_typed.nt` | wikidata | medication | 2862 | 8100 | CC0 1.0 |
| `real_dbpedia_geography_1000.nt` | dbpedia | geography | 108 | 1000 | CC BY-SA 3.0 |
| `real_yago_taxa_1000.nt` | yago | taxa | 515 | 1000 | CC BY-SA 3.0 |
| `real_yago_taxa_10000.nt` | yago | taxa | 5475 | 10000 | CC BY-SA 3.0 |

The two `_typed` slices are typing-completed variants produced by the T0 artifact
audit, not separate extractions.

**DBpedia and YAGO 4.5 are both CC BY-SA 3.0, and share-alike propagates**: the
repaired graphs below are derived works and carry the same condition. Wikidata is
CC0, so its slices and their repairs carry no such condition. Full licence links are
in the scope note at the bottom of [`LICENSE`](LICENSE).

Alongside these, `fixtures/synthetic/` holds the committed 1k synthetic rung and its
constraint file, `fixtures/synthetic_{anatomy,disease,geography}_wd.nt` are small
hand-written slices used by the test suite, and `fixtures/*_golden.json` are golden
snapshots that pin engine and constraint behaviour against regression.

## Repaired graphs — `eval/bundles/`

24 bundles, one per (slice × engine). Each contains:

| file | what it is |
|---|---|
| `repaired.nt` | the repaired graph |
| `changes.nt.diff` | the reversible diff, `+`/`-` per triple |
| `changelog.json` | one structured record per node/edge added or removed |
| `constraints.used.json` | the exact constraint set that drove the run |
| `report.json` | the run report, including attestations |

23 bundles carry a `repaired.nt`. The exception is
`real_wikidata_geography_10000.subset`, which is **`ABORTED-BY-CAP`**: subset repair
would have deleted more than 20% of the nodes, so the runner refused before calling
the engine. That is a finding, not a missing file — it is the case that motivated
addition-based repair, and it is discussed in
[`docs/real_repair.md`](docs/real_repair.md).

Note that repaired graphs are not all small deltas.
`real_wikidata_geography_1000.subset` is 41 triples from a 1000-triple input: deletion
repair is legal but destructive, which is the point Table 6 of the evaluation makes.

## Where the measurements live

| | |
|---|---|
| [`docs/evaluation.md`](docs/evaluation.md) | 8 tables + 4 figures, all script-emitted from `results/` and these artifacts |
| [`docs/real_repair.md`](docs/real_repair.md) | the repair results and the plausibility study |
| `results/*.jsonl`, `results/*.json` | the raw instrumentation records the tables read |
| `eval/accuracy/` | the sampled addition-accuracy study |

---

## What is **not** included, and why

Three fetched inputs are absent from this repository. None of them is required to
read the evaluation, and none affects a committed number — but scripts here refer to
them, so they are listed rather than left to be discovered.

**1. Generation-B ladder inputs** — `fixtures/real/generation_b/` and the fetch cache
they were sliced from, `data/raw_genB/`. 37 slices (wikidata × geography / anatomy /
disease / medication / taxa at rungs 100 → 100 000, plus dbpedia geography at 100 and
1000), referenced by `bench/build_generation_b.py` and `bench/generation_drift.py`.
Their **results survive** in `eval/generation_b_ladder.json` and
`eval/generation_drift.json`; the inputs do not.

Rebuilding is a two-step chain and neither step reproduces the originals.
`bench/build_generation_b.py` only slices — it never fetches — so it needs
`data/raw_genB/`, which is also gone; refilling that means re-running
`bench/frontier_probe.py` against today's Wikidata. That yields a *new generation*,
which is exactly the quantity `eval/generation_drift.json` was written to measure, so
a rebuild cannot be substituted for the originals.

**2. The plausibility ASK cache** — `data/raw/plausibility/wikidata/ask_cache.json`:
one cached live-Wikidata verdict per added `(entity, class)` pair, 453 pairs.
`docs/evaluation.md` Table 7, `docs/figures/fig4_precision_breakdown.png`,
`results/v1_vs_v2_eval.json` and `results/rc_shape_trace.json` were all computed from
it and are committed with those numbers intact. The cache itself is not redistributed.
Consequently `tests/test_evaluation_reproducible.py::test_regenerating_evaluation_md_is_byte_identical`
**skips** rather than fails: without the cache, Table 7 regenerates as zeros, and a
byte comparison would then report a missing input as though it were drift. Restoring
the file at that path re-arms the check automatically. Re-fetching it with
`bench/real_superset.py --plausibility` would query today's Wikidata and is **not** a
way to reproduce the committed figures.

**3. Bulk source dumps** — `data/dumps/` and the fetch caches under `data/raw/`.
Several hundred MB of upstream downloads, refetched on demand by
`bench/build_real_slice.py`. The one small third-party cache the offline evaluation
genuinely needs *is* shipped: `data/raw/constraints/wikidata_p2302.json`, the Wikidata
P2302 property constraints used as an external yardstick in the derivation study.

The general rule: **anything under `data/` is a fetch cache and is regenerable;
anything under `fixtures/`, `eval/` or `results/` is an artifact of record and is
committed.** The exceptions above are the cases where a regenerable input was lost
after the result computed from it had already been committed.

## If you redistribute a repaired graph

You are bound by the terms of the source it derives from, not by this repository's
MIT licence. In particular a repaired DBpedia **or YAGO** graph stays CC BY-SA 3.0
and must be shared alike. Per-source licence metadata stamped onto released bundles is tracked as
an open deliverable.
