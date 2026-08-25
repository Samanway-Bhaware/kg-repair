# API reference

[← Manual index](README.md)

The public surface is `src/kgrepair/api.py`, re-exported wholesale from
`kgrepair`. **`__all__` is the contract.** Everything listed on this page is
supported; anything not listed is internal and may change without notice.

```python
import kgrepair
kgrepair.__version__          # '0.5.0'
kgrepair.__all__              # the contract, as a list
```

Explicitly **not** public: `kgrepair.gxpath`, `kgrepair.pipeline`,
`kgrepair.synthetic`, `kgrepair.derive`, and the JSONL summarisers inside
`kgrepair.instrument`. The `neighbourhood` and `instrument` modules are
*partly* promoted — the names on this page are supported, the rest of those
modules is not.

## Contents

- [Graphs](#graphs)
- [Constraints](#constraints)
- [Checking](#checking)
- [Repair](#repair)
- [Safety caps](#safety-caps)
- [Inspection](#inspection)
- [Quality metrics](#quality-metrics)
- [Output bundles](#output-bundles)
- [Reporting](#reporting)
- [Run recording](#run-recording)
- [Constraint derivation and the review airlock](#constraint-derivation-and-the-review-airlock)
- [Optional filtering](#optional-filtering)
- [Exceptions](#exceptions)

---

## Graphs

### `DataGraph`

The sparse, edge-labelled data-graph with per-node data values. Constructed
empty, by `load_graph`, or from triples.

```python
g = kgrepair.DataGraph()
g = kgrepair.DataGraph.from_triples([("a", "p", "b")], values={"b": "B"})
```

**Mutation**

| Method | Effect |
|---|---|
| `add_node(v, value=None)` | add a node, optionally with a data value |
| `add_edge(src, label, dst)` | add an edge; endpoints are created implicitly if absent |
| `remove_edge(src, label, dst)` | remove one edge |
| `remove_node(v)` | remove a node **and every edge incident to it** (used by subset repair) |
| `set_value(v, value)` | set a node's data value — **not called by any repair path** |

**Queries**

| Method / property | Returns |
|---|---|
| `nodes` | property: the node set |
| `labels` | property: the edge labels in use |
| `value(v)` | `Optional[str]` — the node's data value, or `None` |
| `nodes_with_value(c)` | `{ x : D(x) = c }`, by a sparse scan of the value map alone |
| `succ(label, src)` | the `label`-successors of one node |
| `pred(label, dst)` | the `label`-predecessors of one node |
| `succ_set(label, sources)` | forward image of one hop over a set |
| `pred_set(label, targets)` | backward image of one hop over a set — the evaluator's workhorse |
| `edges()` | iterator of `(src, label, dst)` |
| `num_edges()` | edge count |
| `stats()` | `{"nodes": …, "edges": …, "labels": …, "valued_nodes": …}` |
| `label_version(label)` | change counter for that label's edge set, used to invalidate the closure cache |
| `clone()` | a deep copy |

Storage is per-label forward and backward adjacency plus a partial value map. No
dense `V × V` relation is ever materialised.

### `load_graph(path, *, type_predicates=None) -> DataGraph`

Load an N-Triples file. IRIs and CURIEs are kept **exactly as written** — no
prefix is expanded or abbreviated on this path.

`type_predicates` names the typing/subclass spine of your graph, whose object
nodes become self-valued so that class tests can match them. Defaults to
`DEFAULT_TYPE_PREDICATES`.

```python
g = kgrepair.load_graph("slice.nt")
g = kgrepair.load_graph("mine.nt", type_predicates={"ex:isa", "ex:kindOf"})
```

### `load_graph_string(text, *, type_predicates=None) -> DataGraph`

The same, from an in-memory string.

### `load_ntriples(lines, graph=None, type_predicates=None) -> DataGraph`

Stream an iterable of lines into a `DataGraph`, folding literals onto value
nodes. Pass an existing `graph` to accumulate into it.

### `load_ntriples_file(path, graph=None, type_predicates=None) -> DataGraph`

File form of the above. `load_graph` is the friendlier wrapper.

### `to_ntriples(graph) -> str`

Serialise back to this module's N-Triples dialect — the round-trip companion to
the loader, not a general RDF exporter.

Every node is written `<node_id>`. A node carrying a value different from its own
id (a loader-minted value node, never a self-valued class node) is written as the
literal on its edge, mirroring the loader's folding rule exactly.

> **Limitation, inherent to N-Triples:** a node with **no incident edges** cannot
> be represented and is silently omitted. This is not theoretical — subset
> repair's cascading deletion routinely strands nodes. If isolated nodes matter,
> read them from the change log.

### `write_ntriples(graph, path) -> str`

Serialise to a file; returns the path written.

### `DEFAULT_TYPE_PREDICATES`

```python
frozenset({"rdf:type", "rdfs:subClassOf", "schema:subClassOf",
           "wdt:P31", "wdt:P279"})
```

The one place a default vocabulary survives in the library, and it is an
overridable argument rather than a hardcoded rule.

---

## Constraints

### `Constraint`

One containment rule `antecedent ⊑ consequent`. A dataclass.

| Field | Type | Meaning |
|---|---|---|
| `cid` | `str` | stable identifier, unique within a set |
| `domain`, `kg` | `str` | which slice it belongs to |
| `kind` | `str` | `existential_domain`, `typing_existence`, `symmetric`, … |
| `tier` | `"ptime_core"` \| `"boundary"` | whether an engine may act on it |
| `provenance` | `"given"` \| `"compiled"` \| `"derived"` | how strong the claim is |
| `direction` | `"subset"` \| `"superset"` \| `"report"` | which engine owns it by default |
| `antecedent`, `consequent` | `str` | the two sides, in Reg-GXPath_pos surface syntax |
| `note` | `str` | free text |
| `params` | `Dict[str, str]` | arbitrary extra metadata |
| `version` | `int` | constraint-set version |

| Member | Meaning |
|---|---|
| `phi` / `psi` | properties: the compiled ASTs, parsed lazily on first access and cached |
| `compile()` | parse both sides now; raises `ParseError` if either leaves the fragment |
| `addition_fixable` | property: can a violation be resolved purely by addition? True for every `ptime_core` constraint |
| `to_dict()` / `from_dict(d)` | JSON round-trip |

### `ConstraintSet`

An ordered collection for one slice. Portable: `to_file`/`from_file` write and
read the constraint-file format, so a user's own rules go straight to the
validator and the engines.

```python
cs = kgrepair.ConstraintSet("mydomain@mykg")
cs.add(constraint)
cs.compile_all()                 # fail now rather than at first evaluation
```

| Member | Returns |
|---|---|
| `constraints` | the ordered list; the set is also iterable |
| `add(c)` | append |
| `ptime_core()` | the auto-repairable subset |
| `boundary()` | the report-only subset |
| `coverage()` | `{"ptime_core": n, "boundary": m, "total": t}` |
| `compile_all()` | parse every expression; raises on the first out-of-fragment one |
| `to_dict()` / `from_dict(payload)` | JSON round-trip; unknown top-level keys are ignored on read |
| `to_file(path, indent=2)` / `from_file(path)` | file round-trip |

### `load_constraint_file(path, *, compile_now=False) -> ConstraintSet`

Load a user-authored JSON constraint file. This is the path for **your own
constraints over your own graph**, as distinct from `constraints.get`, which
returns a built-in set.

With `compile_now=True` every expression is parsed immediately, so anything
outside the positive fragment raises `ParseError` here rather than at first
evaluation. Use it while developing.

### `save_constraint_file(cs, path, *, indent=2) -> str`

Write a `ConstraintSet` to a JSON constraint file; returns the path.

### `constraints` — the built-in registry subpackage

```python
from kgrepair import constraints

constraints.AVAILABILITY                          # domain -> kg -> "full"|"partial"|"none"
constraints.registry(version=1)                   # domain -> kg -> ConstraintSet
constraints.get("geography", "wikidata")          # one set; KeyError if absent
constraints.get("medication", "wikidata", version=2)
constraints.compile_all()                         # parse everything; surfaces any bad expression
constraints.export_json("out/constraints")        # one JSON file per slice; returns paths
constraints.load_json(path)                       # alias for ConstraintSet.from_file
```

`version` must be 1 or 2; anything else raises `ValueError`. Version 2 exists
for anatomy, disease and medication only; other domains return their v1 set
unchanged. See the [catalogue](constraint-catalogue.md).

---

## Checking

### `validate(graph, cs, *, use_closure=False) -> ValidationReport`

Check a graph against every constraint in a set. The one-shot form.

```python
report = kgrepair.validate(graph, constraints)
```

Both tiers are checked; `by_tier()` separates them, and only `ptime_core`
violations are ones an engine will act on. `use_closure` changes running time,
never the result.

### `Validator(graph, use_closure=False)`

Bound to one graph, holding a **live reference** to it — which is why the repair
engines reuse a single validator while mutating their working copy.

| Method | Returns |
|---|---|
| `validate(constraints)` | a `ValidationReport` over a `ConstraintSet` or any iterable of constraints |
| `check_one(c)` | a single `Violation`; witnesses are `⟦φ⟧ \ ⟦ψ⟧` |

### `ValidationReport`

Holds one `Violation` per constraint checked, in constraint-set order — including
the ones that passed, so reports are diffable.

| Member | Returns |
|---|---|
| `violations` | the full list |
| `consistent` | property: `True` when nothing failed |
| `failing()` | only the violations with witnesses |
| `by_tier()` | `{"ptime_core": n, "boundary": m}` — **counts of failing constraints** |
| `total_witnesses()` | the sum of witness counts |
| `summary()` | a human-readable block |
| `to_dict(witness_limit=10)` | the canonical JSON serialisation; a negative limit lists all |

`to_dict` always reports the true `witness_count` even when the listed
`witnesses` are truncated, flagged by `witnesses_truncated`.

### `Violation`

| Member | Meaning |
|---|---|
| `constraint` | the `Constraint` checked |
| `witnesses` | `Set[str]` — the nodes in `⟦φ⟧ \ ⟦ψ⟧`; empty means the rule holds |
| `count` | property: `len(witnesses)` |

---

## Repair

Both engines are covered in depth in [Repair engines](repair-engines.md).

### `subset_repair(graph, constraints, *, in_place=False, strategy="full", use_closure=False) -> SubsetRepairResult`

Algorithm 1. Deletes witness nodes to a fixpoint. Acts only on constraints with
`tier == "ptime_core"` **and** `direction == "subset"`. The input graph is
untouched unless `in_place=True`.

`strategy` is `"full"` (baseline oracle) or `"incremental"` (OPT-1 dirty-set).
Both compute the identical repair and differ only in `recheck_count`.

### `SubsetRepairResult`

| Field | Meaning |
|---|---|
| `graph` | the repaired subgraph |
| `changelog` | `List[ChangeRecord]`, ordered |
| `deleted_nodes` | `Set[str]` |
| `rounds` | deletion rounds run |
| `recheck_count` | constraint evaluations performed |
| `attestations` | `subset_only_deleted`, `data_values_unmodified`, `consistent_after` |
| `mode` | the strategy that ran |
| `changed` | property |
| `to_dict()` / `to_json(indent=2)` | canonical serialisation, shared by the CLI and viewer |
| `changelog_dicts()` / `changelog_json(indent=2)` | just the change log |

### `superset_repair(graph, constraints, *, in_place=False, use_closure=True, prune=True) -> SupersetRepairResult`

Algorithm 2. Adds structure drawn from the bounded value pool. Acts on **every**
`ptime_core` constraint regardless of `direction`.

`prune=True` (default) runs the redundancy-pruning post-pass. `prune=False`
returns the raw saturation-phase output.

### `SupersetRepairResult`

| Field | Meaning |
|---|---|
| `graph` | the repaired supergraph |
| `changelog` | `List[ChangeRecord]`, ordered |
| `added_nodes` | `Set[str]` |
| `added_edges` | `Set[Tuple[str, str, str]]` |
| `rounds` | fixpoint rounds |
| `pool` | `{"graph_values", "named_constants", "fresh_bound", "fresh_used"}` |
| `additions_by_kind` | counts per `add_node` / `add_edge` |
| `additions_by_constraint` | counts per cid |
| `fresh_used` | the fresh symbols minted |
| `pruned_edges`, `pruned_nodes` | what pruning removed |
| `attestations` | `superset_only_added`, `fresh_values_within_bound`, `data_values_unmodified`, `consistent_after` |
| `changed` | property |
| `to_dict()` / `to_json(indent=2)`, `changelog_dicts()` / `changelog_json()` | as above |

### `ChangeRecord`

One structural mutation.

| Field | Present for |
|---|---|
| `op` | all — `remove_node`, `remove_edge`, `add_node`, `add_edge` |
| `round` | all |
| `constraint` | all — the cid whose witness triggered it |
| `node` | `*_node` ops |
| `src`, `label`, `dst` | `*_edge` ops |
| `witness` | add ops only — the witness this serves |
| `provenance` | add ops only — `graph`, `named`, or `fresh` |

`to_dict()` emits only the fields relevant to the op.

---

## Safety caps

### `check_cap(graph, cs, mode, cap=None) -> CapDecision`

Measure the repair fraction for `mode` (`"subset"` or `"superset"`) and decide
whether to proceed. `cap` defaults to that mode's project default. **Call this
before the engine and skip the engine when `decision.aborted`.**

### `CapDecision`

| Field | Meaning |
|---|---|
| `mode` | `"subset"` or `"superset"` |
| `fraction` | the measured fraction |
| `cap` | the threshold applied |
| `witness_count`, `denominator` | the raw terms, kept so a report can show the measurement |
| `aborted` | `True` when `fraction > cap` |
| `status` | property: `"ABORTED-BY-CAP"` or `"OK"` |
| `to_dict()` | deterministic serialisation |

### `subset_witness_fraction(graph, cs) -> (fraction, witness_count, node_count)`

The **union** of eligible witnesses over the node count — what a subset repair
would delete in its first round.

### `superset_addition_fraction(graph, cs) -> (fraction, witness_count, edge_count)`

The **sum** of core-constraint witness counts over the edge count — the number of
additions a superset repair would plan.

### Constants

```python
SUBSET_CAP_DEFAULT   = 0.20
SUPERSET_CAP_DEFAULT = 0.30
ABORTED_BY_CAP       = "ABORTED-BY-CAP"
```

---

## Inspection

### `extract_neighbourhood(graph, center, *, k=2, node_cap=150, changelog=None) -> NeighbourhoodView`

A bounded, deterministic k-hop walk out from `center` in **both** directions,
stopping at `node_cap` nodes. When a `changelog` is given, every node and edge is
tagged with how the repair touched it.

Raises `KeyError` if `center` is not in `graph.nodes` — so extract **before**
deletion for subset repairs and **after** addition for superset repairs.

### `NeighbourhoodView`

| Field | Meaning |
|---|---|
| `center`, `k`, `node_cap` | the walk's parameters |
| `nodes` | `List[NVNode]` |
| `edges` | `List[NVEdge]` |
| `truncated` | `True` when the node cap stopped the walk |
| `node_ids()`, `to_dict()` | accessors |

### `NVNode` / `NVEdge`

`NVNode`: `id`, `value`, `status`, `fresh`, `is_center`.
`NVEdge`: `src`, `label`, `dst`, `status`.

`status` is `"unchanged"`, `"added"` or `"deleted"` relative to the change log.
`fresh` marks a fresh symbol the superset engine minted.

### `change_record_center(record) -> str`

A sensible BFS centre for one `ChangeRecord`: the witness it serves (add ops), the
node it removed (`remove_node`), or the edge's source (`remove_edge`).

### Constants

```python
DEFAULT_K        = 2
DEFAULT_NODE_CAP = 150
```

The engines never import this module, and a test enforces the import direction.

---

## Quality metrics

Definitions and blind spots: [Quality metrics](metrics.md) and
[`docs/quality_metrics.md`](../quality_metrics.md).

### `compute_metrics(graph, constraints=None, *, instance_of=None, subclass_of=None, min_instances=2, use_closure=True) -> GraphMetrics`

Every offline metric for a graph, against `constraints` where one is given.

Supplying **no** constraint set leaves the consistency block `None` rather than
zero: "no theory to check against" and "checked and found consistent" are
different states, and the record says which.

### `GraphMetrics`

Named fields, never a loose dict.

*Always present:* `nodes`, `edges`, `labels`, `valued_nodes`,
`redundant_type_edges`, `singleton_classes`, `typed_nodes`,
`typed_node_fraction`, `classes`, `classes_scored_for_coverage`,
`class_property_pairs`, `property_coverage_mean`, `instance_of`, `subclass_of`.

*Present only with a constraint set, otherwise `None`:* `constraints_checked`,
`violations_total`, `violated_constraints`, `witness_nodes`,
`witness_node_fraction`, `violations_by_tier`, `satisfaction_mean`,
`satisfaction_scored`.

`to_dict()` serialises.

### `compare_metrics(before, after) -> MetricComparison`

Per-metric absolute and relative change. A metric that is `None` on either side
yields a change with `None` in the corresponding slot rather than being dropped,
so the key set never depends on the data.

### `MetricComparison` / `MetricChange`

`MetricComparison`: `before`, `after`, `changes` (`Dict[str, MetricChange]`),
`to_dict()`.

`MetricChange`: `before`, `after`, `absolute`, `relative`, `to_dict()`.
`relative` is `None` where the before value is zero or absent, because a ratio
against nothing is not a number.

### `repair_metrics_block(before, after, constraints=None, **kwargs) -> Dict`

The `metrics` section of a repair report: both records and the comparison. `after`
is `None` for a cap-aborted run. **All three keys are present either way**, so a
reader never has to branch on whether an engine ran.

Assembled in the library rather than in a caller, so the CLI and the viewer
cannot describe the same run differently.

### `metric_field_names() -> Tuple[str, ...]`

Every field on `GraphMetrics`, for callers rendering a table.

### `split_type_predicates(type_predicates=None) -> (instance_of, subclass_of)`

Split a loader-style combined set into its two halves. The loader takes one set
because for its purposes both behave the same; the metrics need them apart.

The rule: a label already known to be a subclass predicate is one, and
everything else is treated as instance-of. **A caller with a fully custom spine
therefore gets every label read as instance-of and no hierarchy at all**, so
`redundant_type_edges` comes back 0 rather than wrong. That is a stated
limitation, not a bug — pass `instance_of` and `subclass_of` to
`compute_metrics` directly to measure the hierarchy.

### Constants

```python
DEFAULT_INSTANCE_OF = frozenset({"rdf:type", "wdt:P31"})
DEFAULT_SUBCLASS_OF = frozenset({"rdfs:subClassOf", "schema:subClassOf", "wdt:P279"})
```

---

## Output bundles

See [File formats § Bundles](file-formats.md#bundles).

### `write_bundle(directory, *, report, repaired=None, original=None, constraints_json=None) -> List[str]`

Write a bundle into `directory`; returns the file names written, sorted. Both
`repaired` and `original` are needed for a diff; with neither, the bundle is the
cap-aborted kind and carries the report alone.

Nothing here decides whether a repair *should* have run — it writes down what did.

### `zip_bundle(directory, archive_path=None) -> str`

Pack a bundle directory into one archive. **Deterministic**: entries are added in
sorted order with a fixed timestamp, so two archives of the same bundle are
byte-identical.

### `diff_lines(before, after) -> List[str]`

The statement-level difference, sorted: removals first, then additions, each
block sorted. Node-only changes do not appear — N-Triples cannot write an
isolated node — so read those from the change log in `report.json`.

### `reconstruct_input(repaired_text, diff_text) -> str`

Apply the diff backwards to the repaired graph, returning the input. This is what
makes the diff an auditable record rather than a summary.

### `bundle_summary(*, mode, constraint_provenance, consistent_after, aborted, reason=None) -> Dict`

Which engine ran, where the rules came from, and whether the graph came out
consistent. `consistent_after` is `null` when no engine ran — not the same as a
repair that ran and did not converge.

---

## Reporting

### `report_envelope(subcommand, *, constraints_source, input_name, type_predicates, allowlist_applied=False, allowlist_edges_dropped=0) -> dict`

The wrapper a caller puts around a result object's own `to_dict()`. The body
under `result` is always that serialisation untouched, and this envelope is the
only thing added around it.

Carries no absolute path and reads no clock, so two runs over the same inputs
produce identical bytes.

```python
payload = kgrepair.report_envelope("repair",
                                   constraints_source="geography/wikidata/v1",
                                   input_name="slice.nt",
                                   type_predicates=kgrepair.DEFAULT_TYPE_PREDICATES)
payload["result"] = result.to_dict()
```

**This is the entry-point parity rule.** Any new caller that runs a repair builds
its report this way, takes its cap verdict from `check_cap`, and attaches
`attach_review_attestations` when a candidate file drove the run. A caller that
assembles its own record drifts.

---

## Run recording

Optional. Writes one JSONL record per run, which is what
[`docs/evaluation.md`](../evaluation.md) reads.

### `RunContext(results_dir, *, slice, constraints, mode, config=None, filename="runs.jsonl")`

```python
with kgrepair.RunContext(results_dir,
                         slice=kgrepair.slice_meta_from_graph(g, source="mine"),
                         constraints=kgrepair.constraints_meta(cs),
                         mode="subset_full") as run:
    with run.phase("load"):
        g = kgrepair.load_graph(path)
    with run.phase("repair_loop"):
        res = kgrepair.subset_repair(g, cs)
    run.set_repair_result(res, before_report, after_report)
# the record is written on exit
```

| Member | Effect |
|---|---|
| `phase(name)` | context manager timing one phase |
| `set_repair_result(result, before=None, after=None)` | pull stats and attestations from a `SubsetRepairResult` |
| `set_superset_result(result, before=None, after=None)` | the same for a `SupersetRepairResult` |
| `set_attestations(dict)` | set them directly |
| `record` | property: the record as it stands |

### `constraints_meta(constraints) -> Dict`

Tier and direction counts for the record's `constraints` block.

### `slice_meta_from_graph(graph, *, source, manifest_hash="", seed=None, params=None, hierarchy_depth=None) -> Dict`

Build the `slice` block from a graph's own stats.

### `code_revision() -> str`

An identifier for the code that produced a run: the git commit SHA in a
checkout, otherwise `nogit:<hash>` over the package sources.

The JSONL *summarisers* in `kgrepair.instrument` are internal and not part of
this surface.

---

## Constraint derivation and the review airlock

The full workflow: [Review workflow](review-workflow.md).
**Derivation proposes and a person decides; no score authorises a repair.**

### `derive_candidate_file(graph, domain, kg, *, config=None, reference_graph=None, dataset="", stability_delta=None, label_predicates=(...), measure=False, generator=None) -> CandidateFile`

Profile a loaded graph offline and return candidates wrapped for human review.
Nothing here fetches anything.

| Parameter | Effect |
|---|---|
| `reference_graph` + `stability_delta` | drop any candidate whose confidence on the two graphs differs by more than the delta — a rule holding on only one is a fact about that graph, not the domain. Both numbers are recorded in the evidence either way |
| `measure` | `False` (default) defers impact: each candidate carries its witness count, and the two engine numbers stay `null` until `fill_impact` is called. `True` runs both engines for every candidate up front, which on the measured ladder is **95–99% of total cost** |
| `generator` | `"search"` (the two-axis search) or `"shapes"` (the earlier per-shape sweep). Recorded in the file |

Every entry comes back `pending`.

### `fill_impact(graph, candidate, force=False) -> Dict`

Compute a deferred impact record at the point someone reviews the entry. Returns
the impact either way; already-measured entries are left alone unless `force`.

### `read_candidate_file(path) -> CandidateFile`

Read a candidate file, refusing a schema this toolkit does not write.

### `write_canonical(cf, path) -> str`

Write in the byte-stable form.

### `merge_candidates(existing, fresh) -> CandidateFile`

Fold a fresh derive run into a file that already carries decisions. Three rules,
in order:

1. a recorded decision is kept and the fresh version discarded — re-deriving
   never overwrites a person's verdict;
2. a fresh candidate whose cid is in `refused` is dropped, so a rejection stays
   rejected across runs;
3. anything genuinely new is appended as `pending`.

Merging **never seals**. New pending entries drop the file back to open, because
a seal covering unseen entries would be a lie.

### `set_status(cf, cid, status, note="") -> Candidate`

Record a verdict. A rejection also enters `refused`. **Any change reopens a
sealed file.**

### `seal_candidates(cf, reviewer, sealed_at=None) -> CandidateFile`

Seal a fully reviewed file so it can drive an engine. Refuses while anything is
still pending.

### `reviewed_constraint_set(cf, graph=None, *, allow_graph_drift=False, for_repair=True) -> ConstraintSet`

**The only route from a candidate file to an engine.** Every refusal happens
before a constraint is handed anywhere.

`graph` pins the file to the data it was derived from; passing it is what catches
a file pointed at a different slice. `for_repair=False` loads for validation
only, the one case where a boundary-tier entry is allowed through.

### `graph_content_hash(graph) -> str`

A content hash over a graph's edges, for pinning. Matches the hash the slice
pipeline records.

### `attach_review_attestations(result_payload, cf, *, allow_graph_drift=False) -> dict`

Merge the provenance of the rules into a serialised repair result. The engine's
own attestations are left exactly as they were.

### `Candidate`

`cid`, `kind`, `tier`, `direction`, `antecedent`, `consequent`, `gloss`,
`evidence`, `impact`, `witness_sample`, `status`, `note`; property `loadable`;
`to_dict()` / `from_dict()`.

### `CandidateFile`

`source`, `parameters`, `review`, `candidates`, `refused`, `schema`
(`"kgrepair.candidates/v1"`), `toolkit_version`, `provenance`.

| Member | Returns |
|---|---|
| `accepted()` | approved entries in cid order — what can load |
| `pending()` | undecided entries |
| `by_cid(cid)` | one entry |
| `ordered_for_review()` | entries in `review_order`, then anything left over |
| `sealed` | property |
| `authored` | property: whether a person wrote these rules rather than a search proposing them |
| `to_dict()` / `from_dict()` | round-trip, with candidates and `refused` in a settled order |

---

## Optional filtering

### `apply_allowlist(graph, allowlist) -> (filtered_graph, dropped_count)`

Drop every edge whose predicate is not on a user-supplied allow-list.
`allowlist` may be a path, an `AllowList`, or any iterable of labels. The input
graph is not modified. Nodes are preserved — a node that loses all its edges
survives as an isolated node.

> **Entirely opt-in.** Loading, validating and repairing do no filtering unless
> you call this yourself, and nothing calls it for you.
>
> **It carries no personal-data guarantee.** It is a convenience filter over
> predicate names. Whether a given predicate set is appropriate for your data,
> your ethics approval, or your jurisdiction is your judgement, not something
> this function establishes.

### `load_allowlist_file(path) -> AllowList`

Load an allow-list from any path. Schema: `allowlist_id`, `source`,
`predicates`, optional `deny_predicates`, and a `prefixes` map.

### `AllowList`

`allowlist_id`, `source`, `predicates`, `deny_predicates`, `prefixes`,
`content_hash`.

| Method | Returns |
|---|---|
| `allows(curie)` / `is_denied(curie)` | membership |
| `abbreviate(iri)` | `prefix:local` via the longest matching namespace, else the IRI |
| `curie_of(term)` | abbreviate iff it looks like a full IRI; pass through otherwise |

`apply_allowlist` uses only `predicates`; the rest supports the extraction
pipeline.

---

## Exceptions

| Exception | Raised by | Meaning |
|---|---|---|
| `kgrepair.gxpath.ParseError` | the parser | malformed expression, or one leaving the positive fragment. *(Not in `__all__` — catch `ValueError`, its base.)* |
| `kgrepair.ntriples.NTriplesError` | the loader | unparseable N-Triples. *(Not in `__all__` — catch `ValueError`, its base.)* |
| `kgrepair.repair.superset.NoSupersetPlan` | superset repair | a consequent shape not satisfiable by addition, such as a bare value-equality consequent. *(Not in `__all__`.)* |
| `KeyError` | `constraints.get`, `extract_neighbourhood` | no such slice; centre not in the graph |
| `ValueError` | `constraints.get`/`registry` | unknown constraint version |

### Candidate-gate exceptions

All subclass `CandidateGateError`, which carries a stable `code` and the
offending `cid` where the refusal is about one entry.

| Exception | `code` | Meaning |
|---|---|---|
| `CandidateGateError` | `E-GATE` | base class |
| `NotSealed` | `E-UNSEALED` | nobody sealed it |
| `ReviewIncomplete` | `E-PENDING` | at least one entry is undecided |
| `SealMismatch` | `E-SEAL` | the seal does not recompute — the file changed after sealing |
| `SourceDrift` | `E-DRIFT` | the graph is not the one the candidates came from |
| `OutOfFragment` | `E-FRAGMENT` | an accepted constraint leaves Reg-GXPath_pos |
| `BoundaryNotRepairable` | `E-BOUNDARY` | an accepted constraint is boundary tier |
| `NothingAccepted` | `E-EMPTY` | every entry was rejected |

A file whose schema this toolkit does not write is refused with `E-SCHEMA`.
On the command line all of these exit **4**.

---

## Complete worked example

```python
import kgrepair

# 1. Load
graph = kgrepair.load_graph("slice.nt", type_predicates={"ex:isa", "ex:kindOf"})
rules = kgrepair.load_constraint_file("mine.constraints.json", compile_now=True)

# 2. Check
before = kgrepair.validate(graph, rules)
print(before.summary())
for v in before.failing():
    print(v.constraint.cid, v.constraint.tier, v.count)

# 3. Decide whether to repair
decision = kgrepair.check_cap(graph, rules, "superset")
if decision.aborted:
    raise SystemExit(f"{decision.status}: {decision.fraction:.1%} > {decision.cap:.0%}")

# 4. Repair
result = kgrepair.superset_repair(graph, rules)
assert result.attestations["consistent_after"]
assert result.attestations["data_values_unmodified"]

# 5. Measure
metrics = kgrepair.repair_metrics_block(graph, result.graph, rules)

# 6. Report, in the shape every entry point uses
payload = kgrepair.report_envelope("repair",
                                   constraints_source="mine.constraints.json",
                                   input_name="slice.nt",
                                   type_predicates={"ex:isa", "ex:kindOf"})
payload.update(mode="superset", cap=decision.to_dict(),
               result=result.to_dict(), metrics=metrics)

# 7. Write an auditable bundle
kgrepair.write_bundle("out/run",
                      report=payload,
                      repaired=result.graph,
                      original=graph,
                      constraints_json=open("mine.constraints.json").read())
kgrepair.zip_bundle("out/run")
```

---

Next: [CLI reference](cli-reference.md) · [File formats](file-formats.md)
