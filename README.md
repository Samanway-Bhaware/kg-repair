# kgrepair

**Polynomial-time set repairs for knowledge graphs.**

A reusable Python toolkit implementing the tractable core of Abriola, Martínez,
Pardal, Cifuentes & Pin Baque, *On the Complexity of Finding Set Repairs for
Data-Graphs* (JAIR 76:721–759, 2023, [DOI 10.1613/jair.1.13994](https://doi.org/10.1613/jair.1.13994)):
the positive fragment **Reg-GXPath_pos**, a sparse evaluator, a consistency
validator, and both polynomial-time repair algorithms.

- **Version** 0.5.0 · Python ≥ 3.10 · **zero third-party runtime dependencies**
- **📖 [Full documentation → `docs/manual/`](docs/manual/README.md)**

---

## Install

```bash
pip install -e .                # core, stdlib-only
pip install -e ".[dev]"         # + pytest, to run the suite
pip install -e ".[viewer]"      # + streamlit, for the inspection viewer
pip install -e ".[eval]"        # + matplotlib, for the evaluation figures
```

The test suite imports `kgrepair` from the installed package, so install before
running it. The toolkit is **[MIT-licensed](LICENSE)**; the knowledge-graph
datasets it reads and repairs are **not** covered by that and carry their own terms —
see **[`DATA.md`](DATA.md)** for what data ships, under which licence, and what does not.

## Try it

```bash
kgrepair repair --in examples/museum.nt \
                --constraints examples/museum.constraints.json \
                --mode superset --bundle out/museum

cat out/museum/changes.nt.diff
# + <ex:galleryB> <rdf:type> <ex:Gallery> .
# + <ex:vase2> <rdf:type> <ex:Artwork> .
```

```python
import kgrepair

graph = kgrepair.load_graph("slice.nt")
rules = kgrepair.load_constraint_file("my.constraints.json")

report = kgrepair.validate(graph, rules)
if not report.consistent:
    result = kgrepair.superset_repair(graph, rules)     # or subset_repair, to delete
    kgrepair.write_ntriples(result.graph, "repaired.nt")
    assert result.attestations["consistent_after"]
```

## What it does

| | |
|---|---|
| **Check** | find constraint violations, with per-constraint witnesses and a two-tier split |
| **Repair by deletion** | Algorithm 1 — `subset_repair`, a monotone witness-deletion fixpoint |
| **Repair by addition** | Algorithm 2 — `superset_repair`, over a bounded value pool |
| **Refuse dangerous repairs** | report-first safety caps: 20% of nodes, 30% of edges |
| **Propose constraints** | `derive` profiles a graph and proposes rules — for a person to review |
| **Gate them** | no derived rule repairs anything until a named person reviews and seals it |
| **Measure** | quality metrics before and after, with a per-metric comparison |
| **Export** | an auditable bundle: repaired graph, reversible diff, report, rules |
| **Inspect** | a local Streamlit viewer over the same public API |

## Documentation

**[`docs/manual/`](docs/manual/README.md)** is the full manual.

| | |
|---|---|
| [Installation](docs/manual/installation.md) | install, extras, verifying, licence status |
| [Quickstart](docs/manual/quickstart.md) | check → repair → export in five minutes |
| [Concepts](docs/manual/concepts.md) | the data model, containments, tiers, guarantees |
| [Constraint language](docs/manual/constraint-language.md) | Reg-GXPath_pos grammar and semantics |
| [Constraint catalogue](docs/manual/constraint-catalogue.md) | all 32 built-in constraints |
| [Repair engines](docs/manual/repair-engines.md) | both algorithms, in detail |
| [API reference](docs/manual/api-reference.md) | every public name |
| [CLI reference](docs/manual/cli-reference.md) | every flag and exit code |
| [File formats](docs/manual/file-formats.md) | constraints, candidates, reports, bundles |
| [Review workflow](docs/manual/review-workflow.md) | derive → review → seal → repair |
| [Quality metrics](docs/manual/metrics.md) | measuring a repair |
| [Viewer](docs/manual/viewer.md) | the browser UI |
| [Performance](docs/manual/performance.md) | measured cost, tuning, limits |
| [Troubleshooting](docs/manual/troubleshooting.md) | errors and what to do about them |

Data shipped with the toolkit — the 12 source slices, the 23 repaired graphs, their
per-source licences, and the three fetched inputs that are deliberately not included —
is described in **[`DATA.md`](DATA.md)**.

Research and design documents live alongside it in [`docs/`](docs/):
[`algorithm_fidelity.md`](docs/algorithm_fidelity.md) (paper-to-code mapping and
the deviations ledger), [`evaluation.md`](docs/evaluation.md) (the measurement
campaign), [`quality_metrics.md`](docs/quality_metrics.md) (metric design note),
[`authoring_constraints.md`](docs/authoring_constraints.md)

## Command line

```bash
kgrepair check   --in slice.nt --domain geography --kg wikidata
kgrepair repair  --in slice.nt --domain geography --kg wikidata \
                 --mode superset --out repaired.nt --report run.json
kgrepair metrics --in slice.nt --domain geography --kg wikidata
kgrepair derive  --in slice.nt --out candidates.json --domain geo --kg mykg
kgrepair review  candidates.json --reviewer "Your Name" --graph slice.nt
```

`python -m kgrepair` works too. Exit codes make it scriptable — `check`: 0 clean,
2 `ptime_core` violations, 1 usage/IO. `repair`: 0 repaired and consistent,
3 `ABORTED-BY-CAP`, 2 ran without converging, 4 candidate gate refused, 1
usage/IO. Reports are deterministic: sorted keys, no timestamps, no absolute
paths, so two identical invocations are byte-identical.

The CLI is a **thin skin** over the public API — argparse and file I/O only. The
body under `result` is the API object's own `to_dict()` verbatim, and a test
enforces that no repair or validation logic lives in `cli.py`.

## Any knowledge graph, not just Wikidata

Nothing about a particular dataset is baked into the graph model, the validator,
or the repair engines. Predicates such as `wdt:P31` live only in authored
constraint files, which are data; the loader keeps IRIs and CURIEs exactly as
written and abbreviates nothing; and validation and repair need only a graph and
a constraint set.

```python
graph = kgrepair.load_graph("mine.nt", type_predicates={"ex:isa", "ex:kindOf"})
rules = kgrepair.load_constraint_file("mine.constraints.json")
```

`tests/test_agnostic_core.py` is the gate: it takes a graph with an entirely
custom vocabulary through the whole loop and fails if any Wikidata vocabulary
shows up.

## Design invariants

1. **Repairs never modify a data value `D(v)`** — nodes and edges only, verified
   per run by an attestation.
2. **Constraints are containments `φ ⊑ ψ`, not implications** — implication needs
   negation, which leaves the tractable fragment.
3. **Two tiers.** `ptime_core` rules auto-repair; `boundary` rules (symmetry,
   inverse, functional, cardinality, safety edges) are reported only, because
   repairing them is NP-complete or needs negation.
4. **The parser rejects `¬`, `ā` and `≠` on sight** — anything it accepts, the
   engines can repair in polynomial time.
5. **Evaluation is sparse** — backward pre-image traversal; no dense `V × V`.
6. **Determinism.** No clock, no randomness, canonical ordering everywhere.
7. **No confidence score authorises a repair.** Derived rules need a human review
   seal.

See [Concepts](docs/manual/concepts.md) for the reasoning behind each.

## Inspection viewer

```bash
pip install -e ".[viewer]"
streamlit run app/main.py
```

Six screens — Load, Check, Derive, Review, Repair, Export — over the **public API
only**, mechanically gated. The viewer and the CLI take their cap verdict from
the same `check_cap` and build their report from the same `report_envelope`, and
a test asserts the two payloads are equal. See [Viewer](docs/manual/viewer.md).

## Repository layout

```
src/kgrepair/           the toolkit — the only thing packaged
  api.py                THE public surface; __all__ is the contract
  datagraph.py          sparse (V, L, D) model
  ntriples.py           loader + writer, RDF correspondence
  gxpath/               parser, AST, sparse evaluator  (internal)
  validator.py          Definition-3 consistency  ⟦φ⟧ \ ⟦ψ⟧
  constraints/          the 32 built-in constraints + registry
  repair/               subset.py (Alg 1), superset.py (Alg 2)
  caps.py               report-first safety caps
  metrics.py            quality metrics
  bundle.py             repaired graph + reversible diff + report + rules
  candidates.py         the kgrepair.candidates/v1 file model
  review.py             THE load gate: no candidate repairs without a seal
  proposals.py, derive.py   derivation → reviewable candidates
  cli.py                argparse + I/O only
app/                    the Streamlit viewer (not packaged)
docs/manual/            this toolkit's documentation
docs/                   research and design documents
design/                 the D3 repair design document
examples/, fixtures/    a worked example and the committed source slices
eval/bundles/           the repaired graphs, one bundle per (slice x engine)
bench/, scripts/, eval/, results/    measurement and reporting
DATA.md                 what data ships, its licences, and what is not included
tests/                  the pytest suite (578 tests, offline)
```

## Tests

```bash
pip install -e ".[dev]"
python -m pytest tests/ -q
# 578 passed
```

Fully offline, about two and a half minutes. No linter, formatter, type-check
step or CI is configured.

## Citation

> S. Abriola, M. V. Martínez, N. Pardal, S. Cifuentes, E. Pin Baque.
> *On the Complexity of Finding Set Repairs for Data-Graphs.*
> Journal of Artificial Intelligence Research 76:721–759, 2023.
> DOI [10.1613/jair.1.13994](https://doi.org/10.1613/jair.1.13994)

For the correspondence between the paper's algorithms and this implementation,
including a ledger of every deliberate deviation, see
[`docs/algorithm_fidelity.md`](docs/algorithm_fidelity.md).

## Licence

**MIT** — see [`LICENSE`](LICENSE).
Copyright © 2026 Samanway Bhaware and Nina Pardal.

This covers the toolkit's **source code and documentation only**. The
knowledge-graph **datasets** it reads, including the slices committed under
`fixtures/`, derive from third-party sources under their own separate terms:
Wikidata ([CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)) and
DBpedia and YAGO 4.5 (both [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/),
whose share-alike condition propagates into derived material). Anyone redistributing a
repaired graph produced with this toolkit is responsible for complying with the
terms of the source dataset it derives from.

AI Acknowledgement
In the interest of transparency, I acknowledge the use of AI assistance for the following tasks:

Syntax Assistance: Recommending standard libraries, formatting patterns, and boilerplate code.

Debugging: Helping to identify the root causes of error traces and suggesting logic corrections.

Documentation: Aiding in the drafting, structuring, and phrasing of the project's documentation and README files.

The architectural design, core logic, and final responsibility for the correctness of the code and documentation remain entirely with the author.