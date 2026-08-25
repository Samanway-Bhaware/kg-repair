# File formats

[← Manual index](README.md)

Every format the toolkit reads or writes. All JSON output is emitted with
`sort_keys=True`, no wall clock and basenames only, so identical runs produce
identical bytes.

## Contents

- [Input graphs — N-Triples](#input-graphs--n-triples)
- [Constraint set files](#constraint-set-files)
- [Candidate files](#candidate-files)
- [Allow-list files](#allow-list-files)
- [Check report](#check-report)
- [Repair report](#repair-report)
- [Metrics report](#metrics-report)
- [The change log](#the-change-log)
- [Bundles](#bundles)
- [Run records](#run-records)

---

## Input graphs — N-Triples

A compact, dependency-free subset of N-Triples: one triple per line, `#`
comments, IRIs in `<...>` or prefixed `pre:Local` form, simple `"..."` literals
with optional `^^type` or `@lang`.

```
# a comment
<wd:Q23436> <wdt:P31>  <wd:Q515> .
<wd:Q23436> <wdt:P17>  <wd:Q145> .
wd:Q23436   rdfs:label "Edinburgh"@en .
_:b0        <ex:p>     <wd:Q145> .
```

| Term form | Becomes |
|---|---|
| `<IRI>` | a node named by the IRI, **verbatim** |
| `pre:Local` | a node named `pre:Local`, **verbatim** — no expansion |
| `"literal"` | a fresh value node `subject#predicate` carrying the literal as its `D(.)` |
| `_:b` | skolemised to `bnode:b`, stably across runs |

The writer (`to_ntriples` / `write_ntriples`) round-trips this dialect exactly.
Note the inherent limitation: **a node with no incident edges cannot be
represented in N-Triples and is silently omitted**. Subset repair's cascading
deletion strands nodes routinely; read those from the change log.

Anything richer than this subset — Turtle, quads, full RDF datatype handling —
should be parsed with your own library and handed in through the `DataGraph` API.

---

## Constraint set files

What `save_constraint_file`, `ConstraintSet.to_file` and
`constraints.export_json` write, and what `load_constraint_file` reads. Accepted
by `check`, `repair` and `metrics` alike.

```json
{
  "slice": "geography@wikidata",
  "coverage": { "ptime_core": 4, "boundary": 3, "total": 7 },
  "constraints": [
    {
      "cid": "geo.wd.dom.country",
      "domain": "geography",
      "kg": "wikidata",
      "kind": "existential_domain",
      "tier": "ptime_core",
      "provenance": "compiled",
      "direction": "subset",
      "containment": {
        "phi": "< down(wdt:P17) >",
        "psi": "< down(wdt:P31) . down(wdt:P279)* . [val(\"wd:Q2221906\")] >"
      },
      "note": "Every subject of P17 (country) is a geographic location.",
      "params": {},
      "version": 1
    }
  ]
}
```

| Field | Required | Meaning |
|---|---|---|
| `slice` | yes | a name for the set |
| `coverage` | written, ignored on read | tier counts |
| `constraints[]` | yes | one entry per rule |
| `.cid` | yes | stable identifier, unique in the set |
| `.domain`, `.kg` | yes | slice labels |
| `.kind` | yes | shape name; free text, but see the [catalogue](constraint-catalogue.md) for the conventional values |
| `.tier` | yes | `ptime_core` or `boundary` — decides whether an engine may act |
| `.provenance` | yes | `given`, `compiled` or `derived` |
| `.direction` | yes | `subset`, `superset` or `report` |
| `.containment.phi` / `.psi` | yes | the two sides, in [Reg-GXPath_pos surface syntax](constraint-language.md) |
| `.note` | no | free text |
| `.params` | no | arbitrary string metadata |
| `.version` | no | defaults to 1 |

Unknown **top-level** keys are ignored on read, which is how the built-in
export's extra `availability` field round-trips harmlessly.

The fastest way to author your own: export the closest built-in, edit the
predicates and class identifiers, load it back.

```python
from kgrepair import constraints
constraints.export_json("out/constraints")     # then edit
cs = kgrepair.load_constraint_file("out/constraints/geography.wikidata.json",
                                   compile_now=True)
```

---

## Candidate files

Schema `kgrepair.candidates/v1`. Written by `kgrepair derive` and by
`write_canonical`; read by `read_candidate_file`. This is the format the
[review airlock](review-workflow.md) operates on, and it carries **both** kinds
of constraint: the ones a person wrote and the ones a search proposed.

Accepted by `kgrepair repair --constraints`. **Refused by `check` and
`metrics`** (exit 1) — they take a constraint set file.

```json
{
  "schema": "kgrepair.candidates/v1",
  "provenance": "derived",
  "toolkit_version": "0.5.0",
  "source": { "...": "which graph these came from, and its content hash" },
  "parameters": {
    "generator": "search",
    "max_antecedent": 2,
    "max_path": 1,
    "min_confidence": 0.9,
    "min_support": 5,
    "stability_delta": null,
    "subclass_predicate": "wdt:P279",
    "type_predicate": "wdt:P31"
  },
  "review": {
    "state": "open",
    "reviewer": null,
    "sealed_at": null,
    "seal": null,
    "review_order": ["geography.wikidata.derived.8e19c69b", "..."]
  },
  "candidates": [ /* see below */ ],
  "refused": []
}
```

### Top-level fields

| Field | Meaning |
|---|---|
| `schema` | must be `kgrepair.candidates/v1`; anything else is refused with `E-SCHEMA` |
| `provenance` | `authored` (a person wrote these) or `derived` (a search proposed them). **A missing field is treated as `derived`**, so files written before the field existed keep their old behaviour |
| `toolkit_version` | the version that wrote it |
| `source` | the graph these came from, and its content hash, for the drift check |
| `parameters` | the derivation settings, recorded so a run is reproducible |
| `review` | state, reviewer, timestamps, the seal, and the review order |
| `candidates` | every proposal, each with its own status |
| `refused` | cids a reviewer rejected, kept so a later derive run cannot quietly re-propose them |

A rejection is **retained rather than deleted**. Deleting it would mean the next
derive run re-proposes the same rule and the reviewer decides it again, with
nothing recording that they already did.

### One candidate

```json
{
  "cid": "geography.wikidata.derived.00671f77",
  "kind": "weakening",
  "tier": "ptime_core",
  "direction": "superset",
  "antecedent": "< down(wdt:P206) > & < down(wdt:P30) >",
  "consequent": "< down(wdt:P31) . down(wdt:P279)* . [val(\"wd:Q51929311\")] > | < down(wdt:P17) >",
  "gloss": "everything that is wd:Q51929311 should have an outgoing the expected edge, or ...",
  "evidence": {
    "class": "wd:Q51929311",
    "confidence": 0.9677,
    "standard_confidence": 0.9677,
    "support": 30,
    "exceptions": ["wd:Q34"],
    "low_trust": true,
    "low_trust_reason": "a widening is a second reading of a rule that failed; the narrow reading scored 0.2258",
    "predicate": null
  },
  "impact": {
    "measured": false,
    "subset_deletions": null,
    "superset_additions": null,
    "witnesses": 1
  },
  "witness_sample": ["wd:Q34"],
  "status": "pending",
  "note": ""
}
```

| Field | Meaning |
|---|---|
| `cid` | a **content hash** over `(domain, kg, canonical antecedent, canonical consequent)`, not a counter — so a decision stays attached to the rule it was made about even if earlier candidates disappear |
| `gloss` | a plain-language rendering, for the reviewer |
| `evidence` | support, confidence, exceptions, reference-graph confidence and stability where a reference was given, and a `low_trust` flag with its reason |
| `impact` | what accepting it would cost. `measured: false` means the engine numbers were deferred; `witnesses` is always present |
| `witness_sample` | example nodes that break the rule |
| `status` | see below |
| `note` | the reviewer's note; for a weakening, what they weakened it to |

### Status values

| Status | Meaning |
|---|---|
| `pending` | nobody has looked at it. **Blocks sealing** |
| `accepted` | approved. Reaches an engine |
| `rejected` | turned down. Kept, and its cid enters `refused` |
| `weakened` | a broader form accepted instead. Treated as accepted for loading; the note records what changed |

`accepted` and `weakened` are the loadable statuses.

### Authored files

Setting `"provenance": "authored"` says a person wrote these rules. Writing them
down *is* the assertion, so **exactly two checks are waived**:

| Check | Authored | Why |
|---|---|---|
| review seal | waived | a seal records a review of somebody else's proposal |
| source-graph hash | waived | a derived rule carries evidence measured on one slice, so pointing it elsewhere invalidates it. An authored rule is a claim about the domain, not a measurement |

**Everything else applies unchanged**: the expression is parsed and refused if it
leaves the fragment (`E-FRAGMENT`), and a boundary-tier entry still cannot be
repaired (`E-BOUNDARY`).

Worked example: [`examples/museum.constraints.json`](../../examples/museum.constraints.json)
with its graph at [`examples/museum.nt`](../../examples/museum.nt). Full guide:
[`docs/authoring_constraints.md`](../authoring_constraints.md).

---

## Allow-list files

Read by `load_allowlist_file`, used by the opt-in `apply_allowlist` filter and by
the extraction pipeline.

```json
{
  "allowlist_id": "…",
  "source": "wikidata",
  "predicates": ["wdt:P31", "wdt:P279", "wdt:P17"],
  "deny_predicates": ["wdt:P569"],
  "prefixes": { "wd": "http://www.wikidata.org/entity/",
                "wdt": "http://www.wikidata.org/prop/direct/" }
}
```

`apply_allowlist` uses only `predicates`. The rest supports the extraction
pipeline: `deny_predicates` drives the corpus deny-check, and `prefixes` drives
IRI-to-CURIE abbreviation — which happens **only** in the pipeline, never on a
raw file load.

> This is an opt-in filter over predicate names and **carries no personal-data
> guarantee**.

---

## Check report

Written by `kgrepair check`, or built from `ValidationReport.to_dict()`.

```json
{
  "allowlist_applied": false,
  "constraints_source": "geography/wikidata/v1",
  "input_basename": "slice.nt",
  "subcommand": "check",
  "tool_version": "0.5.0",
  "type_predicates": ["rdf:type", "rdfs:subClassOf", "schema:subClassOf",
                      "wdt:P279", "wdt:P31"],
  "result": {
    "by_tier": { "boundary": 1, "ptime_core": 4 },
    "consistent": false,
    "failing_count": 5,
    "total_witnesses": 5,
    "constraints": [
      {
        "cid": "geo.wd.dom.country",
        "direction": "subset",
        "kind": "existential_domain",
        "tier": "ptime_core",
        "witness_count": 1,
        "witnesses": ["wd:Q999001"],
        "witnesses_truncated": false
      }
    ]
  }
}
```

| Field | Meaning |
|---|---|
| `by_tier` | counts of **failing constraints**, split by tier |
| `consistent` | true when nothing failed |
| `failing_count` | how many constraints have at least one witness |
| `total_witnesses` | the sum of witness counts |
| `constraints[]` | **every** constraint checked, passing or failing — which is what makes reports diffable |
| `.witness_count` | the true count, always |
| `.witnesses` | up to `--witness-limit` of them |
| `.witnesses_truncated` | whether the list was cut |

---

## Repair report

Written by `kgrepair repair`. The envelope is the same; `result` is the engine
result's `to_dict()` verbatim.

```json
{
  "tool_version": "0.5.0", "subcommand": "repair",
  "constraints_source": "geography/wikidata/v1",
  "input_basename": "slice.nt", "type_predicates": ["..."],
  "allowlist_applied": false,
  "mode": "superset",
  "output_basename": "repaired.nt",
  "cap": { "aborted": false, "cap": 0.3, "denominator": 14,
           "fraction": 0.285714, "mode": "superset",
           "status": "OK", "witness_count": 4 },
  "result": { /* engine result */ },
  "metrics": { "before": { … }, "after": { … }, "changes": { … } },
  "bundle": { "directory": "out/run",
              "files": ["changes.nt.diff", "constraints.used.json",
                        "repaired.nt", "report.json"] }
}
```

### `result` — subset

```json
{
  "mode": "full",
  "rounds": 2,
  "recheck_count": 4,
  "deleted_nodes": ["wd:Q999001", "wd:Q999099"],
  "attestations": { "consistent_after": true,
                    "data_values_unmodified": true,
                    "subset_only_deleted": true },
  "changelog": [ /* see below */ ]
}
```

### `result` — superset

```json
{
  "mode": "superset",
  "rounds": 3,
  "added_nodes": ["fresh:geo.wd.req.city_country:0"],
  "added_edges": [["wd:Q999001", "wdt:P31", "wd:Q515"], "..."],
  "additions_by_kind": { "add_edge": 4, "add_node": 1 },
  "additions_by_constraint": { "geo.wd.type.city": 1, "geo.wd.rng.country": 2, "...": 0 },
  "fresh_used": ["fresh:geo.wd.req.city_country:0"],
  "pool": { "fresh_bound": 8, "fresh_used": 1,
            "graph_values": 3, "named_constants": 3 },
  "pruned_edges": 1, "pruned_nodes": 0,
  "attestations": { "consistent_after": true,
                    "data_values_unmodified": true,
                    "fresh_values_within_bound": true,
                    "superset_only_added": true },
  "changelog": [ /* see below */ ]
}
```

When a candidate file drove the run, five review fields are merged into
`attestations`:

```json
"constraint_provenance": "authored",
"constraint_seal":       null,
"constraint_source":     "museum example",
"reviewer":              null,
"authorship":            "asserted by whoever wrote the constraint file; no review seal applies to authored constraints"
```

### A cap-aborted report

`result` is `null`, `output_basename` is `null`, and `metrics.after` is `null` —
but **all three metric keys are still present**, so a reader never has to branch
on whether an engine ran. `cap.status` is `"ABORTED-BY-CAP"` and `cap.aborted`
is true. Exit code 3.

---

## Metrics report

Written by `kgrepair metrics`; `result` is `GraphMetrics.to_dict()`. See
[Quality metrics](metrics.md) for what each field means.

```json
"result": {
  "nodes": 11, "edges": 14, "labels": 5, "valued_nodes": 3,
  "redundant_type_edges": 0, "singleton_classes": 1,
  "typed_nodes": 4, "typed_node_fraction": 0.3636,
  "classes": 2, "classes_scored_for_coverage": 1,
  "class_property_pairs": 2, "property_coverage_mean": 0.8333,
  "instance_of": ["rdf:type", "wdt:P31"],
  "subclass_of": ["rdfs:subClassOf", "schema:subClassOf", "wdt:P279"],

  "constraints_checked": 7,
  "violations_total": 5, "violated_constraints": 5,
  "violations_by_tier": { "boundary": 1, "ptime_core": 4 },
  "witness_nodes": 4, "witness_node_fraction": 0.3636,
  "satisfaction_mean": 0.625, "satisfaction_scored": 4
}
```

The second block is `null` throughout when no constraint set was given.

In a repair report the same shape appears three times under `metrics`, as
`before`, `after`, and `changes` — the last holding
`{before, after, absolute, relative}` per metric, with `relative: null` where the
before value was zero or absent.

---

## The change log

One record per structural mutation, in canonical order, inside `result.changelog`
(and separately via `changelog_dicts()` / `changelog_json()`).

```json
{ "op": "add_edge", "round": 1,
  "constraint": "geo.wd.req.city_country",
  "src": "wd:Q999002", "label": "wdt:P17",
  "dst": "fresh:geo.wd.req.city_country:0",
  "witness": "wd:Q999002", "provenance": "fresh" }
```

```json
{ "op": "remove_node", "round": 1,
  "constraint": "geo.wd.dom.country",
  "node": "wd:Q999001" }
```

| Field | Present for |
|---|---|
| `op` | all — `remove_node`, `remove_edge`, `add_node`, `add_edge` |
| `round` | all |
| `constraint` | all — the cid whose witness triggered it |
| `node` | `*_node` ops |
| `src`, `label`, `dst` | `*_edge` ops |
| `witness` | **add ops only** |
| `provenance` | **add ops only** — `graph`, `named`, or `fresh` |

Remove-op serialisation carries no `witness`/`provenance`, which keeps the
original change-log format byte-for-byte stable.

The change log is the **only** record of node-level changes: the statement diff
cannot express an isolated node.

---

## Bundles

Written by `--bundle DIR` or `write_bundle`.

```
out/run/
├── repaired.nt            the repaired graph, N-Triples
├── changes.nt.diff        reversible statement-level diff
├── constraints.used.json  the rules that drove the run
└── report.json            the full report, plus a `summary` block
```

`--zip` additionally writes `out/run.zip`, packed deterministically — sorted
entries, fixed timestamp — so two archives of the same bundle are byte-identical.

### `changes.nt.diff`

```
- <wd:Q999001> <wdt:P131> <wd:Q22> .
- <wd:Q999001> <wdt:P17> <wd:Q145> .
+ <ex:vase2> <rdf:type> <ex:Artwork> .
```

Removals first, then additions, each block sorted. Apply it backwards to the
repaired graph and you recover the input exactly:

```python
original = kgrepair.reconstruct_input(repaired_text, diff_text)
```

Node-only changes do not appear — N-Triples has no way to write an isolated
node. Those live in the change log.

### `report.json`'s extra `summary`

Present in the bundle's copy only, **not** in the stdout payload:

```json
"summary": {
  "engine": "subset",
  "engine_ran": true,
  "constraint_provenance": "built-in",
  "consistent_after": true
}
```

`consistent_after` is `null` when no engine ran, which is *not* the same as a
repair that ran and did not converge. A cap-aborted bundle carries only
`report.json` and `constraints.used.json`, and its summary's `reason` explains
the refusal.

---

## Run records

`results/runs.jsonl` — one JSON object per line, written by `RunContext`. This is
the dataset [`docs/evaluation.md`](../evaluation.md) reads. Optional: nothing in
the check/repair path requires it.

```json
{
  "run_id": "fc78c307f96e493a82504baa6194a85c",
  "timestamp": "2026-07-06T19:57:58Z",
  "code_revision": "nogit:a57d34d8c4ca",
  "config_hash": "44136fa355b3678a",
  "status": "OK",
  "slice": { "source": "real", "manifest_hash": "bd25a6a68000cd74",
             "seed": null,
             "params": { "slice_source": "wikidata", "domain": "geography",
                         "target_edges": 1000 },
             "V": 725, "E": 1000, "labels": 10, "data_values": 86,
             "hierarchy_depth": null },
  "constraints": { "set_id": "geography@wikidata", "count": 7,
                   "by_tier": { "ptime_core": 4, "boundary": 3 },
                   "by_direction": { "subset": 2, "superset": 2, "report": 3 } },
  "mode": "consistency",
  "timings_s": { "load": 1e-06, "consistency_initial": 0.002909 },
  "wall_total_s": 0.041481,
  "repair": {},
  "resources": { "peak_rss_bytes": 36339712, "peak_traced_bytes": 82866,
                 "bytes_per_edge": 82.87 },
  "attestations": {}
}
```

| Block | Meaning |
|---|---|
| `run_id` | unique per run, and what a table cites for traceability |
| `code_revision` | the git SHA, or `nogit:<hash>` over the package sources |
| `slice` | where the graph came from and how big it is |
| `constraints` | which set, and its tier/direction breakdown |
| `mode` | `consistency`, `subset_full`, `subset_incremental`, `superset`, … |
| `timings_s` | per-phase, from `RunContext.phase(name)` |
| `repair` | engine stats, when a repair ran |
| `resources` | peak RSS and traced allocation |
| `attestations` | the engine's self-checks |

Unlike every other output here, run records **do** carry a timestamp — they are
a measurement log, not a reproducible artefact.

Interactive viewer runs are tagged `slice.params.origin = "viewer"` so they can
be told apart from benchmark runs in the same file.

---

Next: [Review workflow](review-workflow.md) · [Quality metrics](metrics.md)
