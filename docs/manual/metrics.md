# Quality metrics

[← Manual index](README.md)

Measuring what a repair did to a graph, beyond "it is consistent now".

```bash
kgrepair metrics --in slice.nt --domain geography --kg wikidata
```

```python
before = kgrepair.compute_metrics(graph, constraints)
after  = kgrepair.compute_metrics(repaired, constraints)
delta  = kgrepair.compare_metrics(before, after)
```

Every repair report already carries all three under `metrics`, assembled by
`repair_metrics_block`, so you rarely need to call these directly.

> [`docs/quality_metrics.md`](../quality_metrics.md) is the **design note**: it
> gives each metric a formal definition over a `DataGraph`, argues for it, says
> what it is blind to, and commits to a predicted direction under each engine
> *before* the evaluation campaign ran. Read that for the reasoning. This page is
> the operational summary.

---

## Three things the metrics module deliberately does not do

**It does not recount violations.** Consistency comes from `Validator`, through
the same `check_one` every other caller uses. There is no second implementation
of `⟦φ⟧ \ ⟦ψ⟧` anywhere in the toolkit.

**It does not reach the network.** Accuracy of *added* statements against the
source is the one metric that needs a live query, and it lives in `scripts/`, not
in the library.

**It does not assume a vocabulary.** Instance and subclass predicates are
parameters with defaults, so a graph whose spine is `ex:isa`/`ex:kindOf` measures
the same way a Wikidata slice does.

---

## The metrics

### Size and conciseness

| Metric | Definition |
|---|---|
| `nodes`, `edges`, `labels` | graph size |
| `valued_nodes` | nodes carrying a data value `D(v)` |
| `redundant_type_edges` | type edges whose class is already implied by a more specific type on the same node. `v isa Dog` **and** `v isa Animal` with `Dog subClassOf* Animal` makes the second edge carry nothing |
| `singleton_classes` | classes with exactly one direct instance |

`redundant_type_edges` is the metric that makes superset repair's pruning pass
visible: pruning exists precisely to avoid creating these.

### Completeness

| Metric | Definition |
|---|---|
| `typed_nodes` / `typed_node_fraction` | nodes carrying at least one instance-of edge, absolute and as a share of `nodes` |
| `classes` | distinct classes appearing as the object of an instance-of edge |
| `classes_scored_for_coverage` | classes with at least `min_instances` (default **2**) direct instances |
| `class_property_pairs` | `(class, predicate)` pairs where at least one instance of the class carries the predicate |
| `property_coverage_mean` | instance-weighted mean, over scored pairs, of the share of a class's instances carrying that predicate |

Two modelling decisions worth knowing:

**Instances are direct instances only.** The hierarchy is not folded in, so it
cannot confound the measure.

**A local closed-world assumption.** A predicate that *no* instance of `C`
carries is not counted as a pair at all — silence about a predicate nobody uses
reads as "not part of this class", and only silence about a predicate some
instances *do* carry reads as incompleteness. Without this, every class would be
scored against every predicate in the graph and coverage would be meaningless.

**`min_instances` defaults to 2** because with one instance every coverage is
1.0 by construction and says nothing.

### Consistency — only with a constraint set

| Metric | Definition |
|---|---|
| `constraints_checked` | how many rules were evaluated |
| `violations_total` | total witnesses across all constraints |
| `violated_constraints` | how many constraints have at least one witness |
| `violations_by_tier` | `{"ptime_core": n, "boundary": m}` |
| `witness_nodes` / `witness_node_fraction` | distinct nodes implicated, absolute and as a share of `nodes` |
| `satisfaction_mean` | mean over scored constraints of `(|⟦φ⟧| − witnesses) / |⟦φ⟧|` |
| `satisfaction_scored` | how many constraints had a non-empty antecedent extension |

`satisfaction_mean` is a graded reading of consistency. A rule with 1000
antecedent matches and 3 witnesses scores 0.997, where `violations_total` reports
a flat 3 — the difference matters when comparing rules of very different reach.
A constraint whose antecedent matches nothing is not scored, because *n/0* is not
a number.

### The vocabulary block

`instance_of` and `subclass_of` record the predicate sets actually used, so a
report about an `ex:isa` graph never claims to have measured the Wikidata spine.

---

## The consistency block is `null`, not zero, without constraints

```python
kgrepair.compute_metrics(graph)                   # consistency block: all None
kgrepair.compute_metrics(graph, constraints)      # consistency block: measured
```

"No theory to check against" and "checked and found consistent" are different
states, and the record says which. Same on the command line: `kgrepair metrics
--in g.nt` with no constraint source emits `null` for every consistency field.

---

## Comparing before and after

```python
comparison = kgrepair.compare_metrics(before, after)
comparison.changes["typed_nodes"].absolute    # +3
comparison.changes["typed_nodes"].relative    # +0.75
```

Each `MetricChange` carries `before`, `after`, `absolute` and `relative`.

Two shape guarantees:

- **A metric that is `None` on either side still appears**, with `None` in the
  corresponding slot, rather than being dropped. The key set never depends on the
  data, so two comparisons are always the same shape.
- **`relative` is `None` where the before value is zero or absent**, because a
  ratio against nothing is not a number.

`compare_metrics` is the **only** place in the toolkit where a metric delta is
computed, so two callers cannot subtract differently.

---

## In a repair report

`repair_metrics_block(before_graph, after_graph, constraints)` produces the
`metrics` section, with three keys **always present**:

```json
"metrics": {
  "before":  { … },
  "after":   { … },
  "changes": { "typed_nodes": { "before": 4, "after": 7,
                                "absolute": 3, "relative": 0.75 }, … }
}
```

For a cap-aborted run there is no repaired graph, so `after` is `null` — but the
three keys are still there, so a reader never has to branch on whether an engine
ran.

The block is assembled **in the library**, not in the CLI or the viewer, which is
the entry-point parity rule applied to this field: a caller *adds* the block, it
does not build one.

---

## Reading a real comparison

From the superset repair of the synthetic geography fixture:

| Metric | Before | After | Change |
|---|---|---|---|
| `nodes` | 11 | 12 | +1 |
| `edges` | 14 | 18 | +4 |
| `typed_nodes` | 4 | 7 | +3 |
| `typed_node_fraction` | 0.364 | 0.583 | +60.4% |
| `violations_total` | 5 | 1 | −80% |
| `violations_by_tier.ptime_core` | 4 | 0 | resolved |
| `violations_by_tier.boundary` | 1 | 1 | untouched, as designed |
| `satisfaction_mean` | 0.625 | 1.000 | +60% |
| `singleton_classes` | 1 | 0 | −1 |
| `property_coverage_mean` | 0.833 | 0.818 | **−1.8%** |

The last row is the interesting one. Property coverage went *down* while
everything else improved — because typing three previously-untyped nodes added
new instances to classes without adding the properties those classes usually
carry. That is a true reading, not an artefact: superset repair fixed the type
edges it was asked about and left the resulting property gaps visible. Any
metric set that only moved in one direction after a repair would be telling you
less than this one.

Note also that the single boundary violation survives untouched, exactly as
specified — no engine repairs boundary-tier rules.

---

## Custom vocabularies and the hierarchy limitation

The loader takes **one** combined `type_predicates` set, because for its purposes
instance-of and subclass-of behave identically: both make the object self-valued.
The metrics need them apart.

`split_type_predicates` bridges the two with a deliberately conservative rule: a
label already known to be a subclass predicate is treated as one, and everything
else as instance-of.

So a Wikidata caller passing the default set explicitly gets the right split —
but a caller with a fully custom spine gets **every label read as instance-of and
no hierarchy at all**, which means `redundant_type_edges` comes back **0 rather
than wrong**.

That is a stated limitation, not an accident: without being told which of
`ex:isa` and `ex:kindOf` is the hierarchy, the honest reading is that there is
none. To measure the hierarchy, name the two halves directly:

```python
kgrepair.compute_metrics(graph, constraints,
                         instance_of={"ex:isa"},
                         subclass_of={"ex:kindOf"})
```

Those remain the real parameters; `split_type_predicates` is only the fallback
for a caller who passed `--type-predicate` and never said which half was which.

---

## What the metrics are blind to

Stated plainly, because a number that looks like quality invites over-reading:

- **Truth.** Nothing here checks whether an added edge is *correct*, only whether
  the graph is more complete and consistent. Accuracy against the live source is
  a separate, network-bound measurement in `scripts/`, and the project's own run
  of it found 34.4% precision on one early configuration — a fact no offline
  metric would have surfaced.
- **Whether the constraints are right.** A graph can score perfectly against a
  bad theory.
- **Anything about deleted content.** Subset repair improves consistency by
  removing data; the metrics show a smaller, cleaner graph and cannot tell you
  whether what went was worth keeping. Read the change log.
- **Boundary-tier semantics.** Those violations are counted and never repaired,
  so they persist across every before/after comparison by design.

---

Next: [File formats § Metrics report](file-formats.md#metrics-report) ·
[`docs/quality_metrics.md`](../quality_metrics.md)
