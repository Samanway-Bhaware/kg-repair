# kgrepair — Toolkit Manual

**Version 0.5.0** · Python ≥ 3.10 · zero third-party runtime dependencies

`kgrepair` finds and repairs constraint violations in knowledge graphs, in
polynomial time, using only operations that are provably tractable.

It implements the tractable core of Abriola, Martínez, Pardal, Cifuentes &
Pin Baque, *On the Complexity of Finding Set Repairs for Data-Graphs*
(JAIR 76:721–759, 2023, [DOI 10.1613/jair.1.13994](https://doi.org/10.1613/jair.1.13994)):
the positive fragment **Reg-GXPath_pos**, a sparse evaluator over it, a
consistency validator, and both polynomial-time repair algorithms —
**Algorithm 1 (SubsetRepair**, repair by deletion) and **Algorithm 2
(SupersetRepair**, repair by addition).

---

## What it does

| Capability | Entry point |
|---|---|
| Load an N-Triples graph into a sparse in-memory model | [`load_graph`](api-reference.md#graphs) |
| Author constraints in a decidable, positive path language | [Constraint language](constraint-language.md) |
| Check a graph for violations, with per-constraint witnesses | [`validate`](api-reference.md#checking) / `kgrepair check` |
| Repair by deleting offending nodes (Algorithm 1) | [`subset_repair`](api-reference.md#repair) / `kgrepair repair --mode subset` |
| Repair by adding missing structure (Algorithm 2) | [`superset_repair`](api-reference.md#repair) / `kgrepair repair --mode superset` |
| Refuse to run a repair that would touch too much of the graph | [`check_cap`](api-reference.md#safety-caps) |
| Propose candidate constraints from the data, for a human to review | `kgrepair derive` → `kgrepair review` |
| Measure graph quality before and after a repair | [`compute_metrics`](api-reference.md#quality-metrics) / `kgrepair metrics` |
| Write an auditable, reversible output bundle | [`write_bundle`](api-reference.md#output-bundles) / `--bundle` |
| Inspect everything interactively in a browser | [Viewer](viewer.md) |

## What it does *not* do

These are design decisions, not gaps. Each is explained where it is relevant:

- **It never modifies a data value `D(v)`.** Repairs add and delete nodes and
  edges only. See [Concepts § The data model](concepts.md#the-data-model).
- **It does not repair every constraint it can check.** Constraints are split
  into two tiers; only the `ptime_core` tier is auto-repairable. The `boundary`
  tier (symmetry, inverse, functional, cardinality, safety edges) is validated
  and reported, never repaired, because repairing it is NP-complete or requires
  negation. See [Concepts § Tiers](concepts.md#the-two-tier-model).
- **It does not accept negation.** `¬φ`, path complement `ā` and disequality
  `≠` are rejected by the parser with a diagnostic. They are exactly what makes
  the problem intractable. See [Constraint language § Rejected constructs](constraint-language.md#rejected-constructs).
- **No confidence score authorises a repair.** Derived constraints must be
  reviewed and sealed by a named person before any engine will act on them.
  See [Review workflow](review-workflow.md).

---

## Manual contents

**Getting started**

1. [Installation](installation.md) — install, extras, verifying the install
2. [Quickstart](quickstart.md) — a complete check → repair → export cycle in five minutes

**Understanding the toolkit**

3. [Concepts](concepts.md) — the data model, containment semantics, the two-tier
   model, the complexity routing table, and the guarantees the toolkit makes
4. [The constraint language](constraint-language.md) — Reg-GXPath_pos: grammar,
   abstract syntax, evaluation semantics, and what is rejected
5. [Built-in constraint catalogue](constraint-catalogue.md) — all 32 shipped
   constraints across 9 domain/knowledge-graph slices, with versions
6. [The repair engines](repair-engines.md) — both algorithms in detail:
   what they do, what they guarantee, the safety caps, and the attestations

**Reference**

7. [API reference](api-reference.md) — every public name, complete
8. [CLI reference](cli-reference.md) — every subcommand, flag, and exit code
9. [File formats](file-formats.md) — constraint files, candidate files,
   allow-lists, report JSON, bundles, change logs, run records

**Workflows**

10. [Review workflow](review-workflow.md) — deriving candidate constraints and
    the review airlock that gates them
11. [Quality metrics](metrics.md) — measuring a graph before and after repair
12. [The inspection viewer](viewer.md) — the browser UI

**Operations**

13. [Performance and scaling](performance.md) — measured cost, tuning knobs, limits
14. [Troubleshooting](troubleshooting.md) — errors, exit codes, and what to do about them

---

## The shortest possible example

```bash
pip install -e .

kgrepair repair --in examples/museum.nt \
                --constraints examples/museum.constraints.json \
                --mode superset --bundle out/museum
```

```python
import kgrepair

graph       = kgrepair.load_graph("slice.nt")
constraints = kgrepair.load_constraint_file("my.constraints.json")

report = kgrepair.validate(graph, constraints)
if not report.consistent:
    result = kgrepair.superset_repair(graph, constraints)
    kgrepair.write_ntriples(result.graph, "repaired.nt")
    assert result.attestations["consistent_after"]
```

---

## Design principles

The toolkit is built around five commitments that every module upholds and that
the test suite enforces mechanically.

**1. The public API is the contract.**
`src/kgrepair/api.py` defines `__all__`, and that list is the supported surface.
The command line and the viewer are thin skins over it — they contain no repair,
validation, cap, or serialisation logic of their own. Everything else
(`gxpath`, `pipeline`, `derive`, `synthetic`, `instrument` internals) is
unstable and may change without notice.

**2. Dataset agnosticism.**
No knowledge-graph-specific predicate appears in the graph model, the validator,
or either repair engine. Wikidata identifiers such as `wdt:P31` live only inside
authored constraint files, which are data. The loader preserves arbitrary IRIs
and CURIEs verbatim and abbreviates nothing. Any graph with any vocabulary can
be repaired by writing a constraint file that names its own predicates.
`tests/test_agnostic_core.py` is the gate.

**3. Determinism.**
No library output path reads a clock or uses randomness. Change logs and
serialisations are emitted in canonical order, and reports use sorted keys and
basenames only. Two identical invocations produce byte-identical output.

**4. Entry-point parity.**
Every caller that runs a repair builds its report from `report_envelope` plus
the result object's own `to_dict()`, and takes its cap verdict from
`check_cap`. The CLI and the viewer therefore cannot describe the same run
differently; a test asserts their payloads are equal.

**5. Nothing repairs without provenance.**
Every change is recorded as a `ChangeRecord` naming the constraint that caused
it and the witness it served. Every repair result carries self-checked
attestations. Derived rules cannot repair anything until a named person has
reviewed and sealed them.

---

## Project status and test suite

The full suite is offline and runs in about two and a half minutes:

```bash
pip install -e ".[dev]"
python -m pytest tests/ -q
# 578 passed
```

There is no linter, formatter, type-check step, or CI configured.

## Licence

**MIT.** Copyright © 2026 Samanway Bhaware and Nina Pardal. The full text is in
[`LICENSE`](../../LICENSE); `pyproject.toml` declares the matching SPDX
expression, and the licence file ships inside both the wheel and the sdist.

The MIT grant covers the toolkit's **code and documentation only**. The
knowledge-graph **datasets** it reads carry their own separate terms — see
[Installation § Licence](installation.md#licence) for the per-source detail and
what that means if you redistribute a repaired graph.

## Citation

The algorithms implemented here are due to:

> S. Abriola, M. V. Martínez, N. Pardal, S. Cifuentes, E. Pin Baque.
> *On the Complexity of Finding Set Repairs for Data-Graphs.*
> Journal of Artificial Intelligence Research 76:721–759, 2023.
> DOI [10.1613/jair.1.13994](https://doi.org/10.1613/jair.1.13994)

For the correspondence between the paper's algorithms and this implementation,
including a ledger of every deliberate deviation, see
[`docs/algorithm_fidelity.md`](../algorithm_fidelity.md).
