# The repair engines

[← Manual index](README.md)

Two engines, two directions. Both take `(DataGraph, ConstraintSet)`, act only on
`ptime_core` constraints, never modify a data value, and return a result object
carrying the repaired graph, an ordered change log, and self-checked
attestations.

| | `subset_repair` | `superset_repair` |
|---|---|---|
| Paper | Algorithm 1 | Algorithm 2 |
| Operation | deletes nodes (edges cascade) | adds nodes and edges |
| Acts on | `ptime_core` **and** `direction == "subset"` | **every** `ptime_core` constraint |
| Tractability | PTime for positive node constraints (Lemma 13 ⇒ Thm 14) | PTime when the value alphabet is finite or `R` is fixed (Thm 27) |
| Bounded by | `\|V\|` rounds (counting argument) | the bounded value pool |
| Safety cap | 20% of nodes | 30% of edges |
| Risk | loses real data | invents structure |

---

## Choosing a direction

The choice is a modelling decision, not a technical one, and the toolkit
deliberately refuses to make it for you.

**Use `subset` when** the violation means the data is *wrong* — a node that
should not exist, an extraction artefact, a mis-scraped entity. Deleting it is
the honest repair.

**Use `superset` when** the violation means the data is *incomplete* — a real
entity missing a type edge or a required property. This is overwhelmingly the
common case on real knowledge graphs, and it is what the project's own
measurements found: on the real corpus, violation prevalence ran roughly **10×**
the synthetic rate, and three slices blew straight through the 20% deletion cap.
That is a semantics finding, not a tuning problem — those graphs are incomplete,
and deletion is the wrong tool. All three were subsequently repaired by addition.

**Run `check_cap` first, in both cases.** If a repair would touch a fifth of your
graph, the constraints are probably wrong.

```python
for mode in ("subset", "superset"):
    d = kgrepair.check_cap(graph, constraints, mode)
    print(mode, d.status, f"{d.fraction:.1%}", d.witness_count, "/", d.denominator)
```

---

## Algorithm 1 — `subset_repair`

```python
subset_repair(graph, constraints, *,
              in_place=False, strategy="full", use_closure=False) -> SubsetRepairResult
```

Computes the fixpoint of witness-node deletion: the deterministic canonical
repair reached by a monotone deletion loop.

### The loop

```
G₀ = G
repeat:
    Wₖ = ⋃ over eligible (φ ⊑ ψ) of  ⟦φ⟧_Gₖ \ ⟦ψ⟧_Gₖ      # on the CURRENT graph
    if Wₖ is empty: stop
    Gₖ₊₁ = Gₖ with every node in Wₖ removed                # ALL AT ONCE
```

Removing a node cascades every edge incident to it (`DataGraph.remove_node`).

**Why set-at-a-time.** Positive node expressions are monotone (Lemma 13): for
`G' ⊆ G`, `⟦φ⟧_G' ⊆ ⟦φ⟧_G`. So deleting a node can never *create* a fresh member
of any `⟦φ⟧`. But it *can* pull another candidate out of a `⟦φ⟧` — deleting a
country removes the country edge that made its neighbour a witness. A
witness-by-witness loop would therefore depend on visitation order. Computing
the whole witness set on `Gₖ` before touching anything makes `Gₖ₊₁` a function
of `Gₖ` alone, so the descending chain and its fixpoint are **order-independent**.

**Why it is still a loop.** Deleting a node can pull another node out of some
`⟦ψ⟧` while it stays in `⟦φ⟧` — deleting the class node that made a country a
country creates a fresh witness in the *next* round. Each productive round
deletes at least one node and `|V|` is finite, so the loop terminates in at most
`|V|` rounds. That is a counting argument; Theorem 14 is separately what makes
each round's deletion safe, giving `Rep(G, R) = Rep(G ↾ V \ V⊥, R)` so removing
the witness set never discards a repairable node.

### What it does *not* compute

This is the fixpoint of witness-node deletion, which is deterministic and
canonical. It is **not always the subset-maximal consistent subgraph**: where a
witness fails only because of a deletable *supporting* edge, deleting the
supporter's other endpoint can be a strictly larger repair. The paper's
Theorem 15 states the fixpoint is the *unique* subset repair under its
node-expression hypothesis; whether that transfers to this toolkit's containment
semantics is an open design question. **The toolkit never claims uniqueness or
maximality for its own output** — a grep gate in the test suite enforces that
wording. The behaviour itself is pinned by
`tests/test_subset_repair.py::test_fixpoint_catches_witness_created_by_a_deletion`.

### `strategy` — the two re-check policies

Both compute the **identical** repair. They differ only in `recheck_count`.

| Strategy | Behaviour |
|---|---|
| `"full"` (default) | every round re-evaluates every eligible constraint over the whole current graph. Deliberately simple; the differential-testing oracle |
| `"incremental"` | **OPT-1 dirty-set**: after a round, only constraints whose label alphabet intersects the set of *removed edge labels* are re-evaluated. The rest keep their necessarily-unchanged cached witness sets |

The dirty-set rule is a sound conservative over-approximation: a witness of `c`
is the source of a path over `labels(c)`, so deleting it removes a `labels(c)`
edge and `c` is re-checked; and a *new* witness requires some node to leave
`⟦ψ_c⟧`, which by monotonicity can only happen if a `labels(c)` edge was
removed. If no such edge went, neither side changed.

The default stays `"full"` because the measured payoff on geography-like slices
is about **0%** — the subset rules there share the `country` label, so almost
everything is dirty every round. Both paths are kept so the differential suite
always has its oracle.

### Result — `SubsetRepairResult`

| Field | Meaning |
|---|---|
| `graph` | the repaired subgraph `G'` (a new object unless `in_place=True`) |
| `changelog` | ordered `ChangeRecord` list, one per node/edge removed |
| `deleted_nodes` | the set of deleted node ids |
| `rounds` | how many deletion rounds ran |
| `recheck_count` | constraint evaluations performed — the strategy comparison metric |
| `attestations` | the engine's self-checks |
| `mode` | the strategy that ran (`"full"` / `"incremental"`) |
| `changed` | property: whether anything was deleted |

```json
"attestations": {
  "subset_only_deleted":    true,
  "data_values_unmodified": true,
  "consistent_after":       true
}
```

---

## Algorithm 2 — `superset_repair`

```python
superset_repair(graph, constraints, *,
                in_place=False, use_closure=True, prune=True) -> SupersetRepairResult
```

Repairs by **addition only** — never deletion, never a value rewrite — drawing
any value it needs from the bounded pool.

### Scope: every `ptime_core` constraint

Unlike Algorithm 1, this engine ignores `direction`. Every `ptime_core`
consequent is a positive node expression and is therefore satisfiable by
addition (`Constraint.addition_fixable`). In particular an existential
domain/range violation is fixed by **adding the missing type edge** to the
constraint-named class, not by deleting the endpoint.

This is a deliberate project decision — `direction` as a *preference*, not a
capability limit — grounded in the real-corpus findings and recorded as an
open design question. Boundary constraints are never touched, and Algorithm 1 is
entirely unchanged and still keys on `direction == "subset"`.

### What it adds, per consequent shape

| Consequent shape | Addition |
|---|---|
| `τ_C = < down(type) . down(subClassOf)* . [val("C")] >` | `x --type--> C`. `C` is a constraint-named constant; the class node is self-valued `C` and is **materialised if absent** — a new pool node, never a value rewrite |
| `< down(P) >` (existential / requires-statement) | `x --P--> t`, where `t` is the constraint's single reused fresh symbol, or a named value if the constraint names one |
| `< down(P₁) > \| < down(P₂) >` (disjunction) | satisfies the **left** disjunct |
| `< down(type) . [val("C")] >` (inheritance) | `x --type--> C` |

A consequent shape the engine cannot satisfy by addition — a bare value-equality
consequent, which would require rewriting `D(v)` — raises `NoSupersetPlan`.

### The loop

Same set-at-a-time discipline as Algorithm 1, for the same reason:

```
H₀ = G
repeat:
    snapshot the full witness set across all core constraints on Hₖ
    plan the complete addition set for that round
    apply it → Hₖ₊₁
```

Additions are monotone on antecedents, so a round **can create new witnesses** —
a node newly typed `City` now matches a requires-statement antecedent; a fresh
edge target is now the value of an existential-range predicate. This cascade is
expected and it terminates: candidate additions live over the bounded pool
(existing nodes + named class nodes + ≤2 fresh per constraint), a finite set, and
every productive round applies at least one new node or edge. `_MAX_ROUNDS` is a
termination-*bug* detector — a planner that fails to satisfy its own witness —
not a tuning knob.

### The bounded value pool

```
pool  =  values already in the graph
       ∪ constants named by the constraints
       ∪ ≤ 2 fresh symbols per constraint     (bound: 2 × |R|)
```

Fresh symbols are node ids of the form `fresh:<cid>:<n>` and carry no data value.
Unboundedness here is exactly what makes the problem NP-complete (Thm 27), so
the bound is not optional.

This **generalises** the paper's Lemma 21 rather than reproducing it: Lemma 21's
`buildGraph` set `S = Σ^R_n ∪ {c, d}` needs only two fresh values *in total*,
where this engine mints two *per constraint*. A larger finite pool cannot lose a
repair the smaller one would have found, so the generalisation is safe, and
per-constraint naming buys attributability and deterministic naming. Recorded as
a deliberate deviation in [`docs/algorithm_fidelity.md`](../algorithm_fidelity.md).

The `pool` field on the result reports the sizes:

```json
"pool": { "graph_values": 3, "named_constants": 3,
          "fresh_bound": 8, "fresh_used": 1 }
```

### `prune` — redundancy pruning

With `prune=True` (default) a post-pass revisits every added edge in a stable
canonical order and drops it when the graph stays `ptime_core`-consistent
without it. The typical case: a redundant `--type--> Geo` once `--type--> City`
is present and `City` subclasses `Geo`.

With `prune=False` the result is exactly the saturation-phase output. Use it to
see what the fixpoint produced before cleanup, or when you want the addition set
to mirror the planner one-for-one.

### Result — `SupersetRepairResult`

| Field | Meaning |
|---|---|
| `graph` | the repaired supergraph `H` |
| `changelog` | ordered `ChangeRecord` list, one per node/edge added |
| `added_nodes` / `added_edges` | the additions, as a set of ids and of `(src, label, dst)` triples |
| `rounds` | fixpoint rounds |
| `pool` | the four pool sizes shown above |
| `additions_by_kind` | counts per `add_node` / `add_edge` |
| `additions_by_constraint` | counts per cid — which rule cost what |
| `fresh_used` | the fresh symbols actually minted |
| `pruned_edges` / `pruned_nodes` | what the pruning pass removed |
| `attestations` | the engine's self-checks |
| `changed` | property: whether anything was added |

```json
"attestations": {
  "superset_only_added":       true,
  "fresh_values_within_bound": true,
  "data_values_unmodified":    true,
  "consistent_after":          true
}
```

### Why the paper's Algorithm 2 cannot run as written

The paper's `buildGraph` step saturates a *complete* graph over the value pool.
At real scale that is `|V|² · |labels|` edges: about **1.65 × 10⁸ edges / ~61 GB**
at the geography-10k slice, and **8.71 × 10¹¹ / ~322 TB** at the 1M rung —
against a measured **~17 s / ~403 MB** for the actual implementation. The
engine therefore uses a *constructive planner*: it computes, per witness, the
specific additions that satisfy the consequent, instead of saturating and then
minimising.

Every figure in that comparison is sourced to a manifest field or a measurement
in [`docs/performance.md`](../performance.md). The full argument is
[`docs/why_algorithm_2_cannot_run_as_written.md`](../why_algorithm_2_cannot_run_as_written.md),
and whether the constructive planner is an acceptable implementation of
Algorithm 2 is open item 8.

### What it does *not* compute

A **deterministic canonical addition repair with redundancy pruning**. It is not
claimed to be a *minimal* or *unique-minimal* consistent supergraph; whether the
paper's minimality theorems transfer to containment (rather than implication)
constraints is an open question.

---

## Attestations

Every repair result carries `attestations`: self-checks the engine performs
against its own output, computed by comparing the actual graphs, not asserted.

| Attestation | Engine | Verifies |
|---|---|---|
| `subset_only_deleted` | subset | no node or edge was added |
| `superset_only_added` | superset | no node or edge was removed |
| `data_values_unmodified` | both | every node present in the input keeps its original value |
| `fresh_values_within_bound` | superset | at most 2 fresh symbols per constraint were minted |
| `consistent_after` | both | re-validating the output finds no `ptime_core` violation |

**`consistent_after` is the one to check.** It is the difference between "the
engine ran" and "the graph is fixed", and the CLI exit code turns on it: exit 0
when true, exit 2 when the engine ran without reaching consistency.

```python
result = kgrepair.superset_repair(graph, constraints)
if not result.attestations["consistent_after"]:
    ...  # ran, did not converge — inspect the changelog
```

When a repair was driven by a reviewed candidate file, three more fields are
merged in by `attach_review_attestations`, recording *who authorised the rules*:

```json
"constraint_provenance": "authored",   // or "derived"
"constraint_seal":       null,         // the seal hash, for a sealed derived file
"constraint_source":     "museum example",
"reviewer":              null,         // the name recorded in the seal
"authorship":            "asserted by whoever wrote the constraint file; ..."
```

---

## Safety caps

The engines take **no cap parameter** and **no result carries a cap outcome**.
The cap is a report-first pre-check in the *runner* layer that decides whether to
call the engine at all. `kgrepair.caps` promotes that convention into the library
so the CLI, the viewer and the benchmark scripts reach identical verdicts.

```python
from kgrepair import check_cap, SUBSET_CAP_DEFAULT, SUPERSET_CAP_DEFAULT, ABORTED_BY_CAP

d = check_cap(graph, constraints, "superset")      # or cap=0.5 to override
if d.aborted:
    print(ABORTED_BY_CAP, d.fraction, ">", d.cap)
else:
    result = kgrepair.superset_repair(graph, constraints)
```

| Mode | Numerator | Denominator | Default |
|---|---|---|---|
| `subset` | **union** of eligible (`ptime_core`/`subset`) witnesses | node count | `0.20` |
| `superset` | **sum** of core-constraint witness counts | edge count | `0.30` |

The union/sum asymmetry is deliberate: subset repair deletes each witness node
once regardless of how many rules it breaks, while superset repair plans one
addition per constraint per witness.

`CapDecision` keeps the raw terms — `witness_count`, `denominator`, `fraction`,
`cap`, `aborted`, and a `status` of `"OK"` or `"ABORTED-BY-CAP"` — so a report
can show the measurement, not just the verdict.

An over-cap run is a first-class outcome: exit code **3**, no engine call, no
repaired graph written, but a report (and a bundle, if asked for) that carries
the measurement and a `summary` explaining the refusal.

---

## The change log

Both engines emit one `ChangeRecord` per structural mutation, in canonical
order.

| Field | Present for | Meaning |
|---|---|---|
| `op` | all | `remove_node`, `remove_edge`, `add_node`, `add_edge` |
| `round` | all | which fixpoint round produced it |
| `constraint` | all | cid of the constraint whose witness triggered it |
| `node` | `*_node` ops | the node added or removed |
| `src`, `label`, `dst` | `*_edge` ops | the edge |
| `witness` | **add ops only** | the witness node this addition serves |
| `provenance` | **add ops only** | value-pool origin: `graph`, `named`, or `fresh` |

`witness` and `provenance` are populated only for additions, so the D5 remove-op
serialisation is byte-for-byte preserved.

```json
{ "constraint": "geo.wd.req.city_country",
  "dst": "fresh:geo.wd.req.city_country:0",
  "label": "wdt:P17", "op": "add_edge", "provenance": "fresh",
  "round": 1, "src": "wd:Q999002", "witness": "wd:Q999002" }
```

To visualise a single change in context:

```python
from kgrepair import change_record_center, extract_neighbourhood

record = result.changelog[0]
view = extract_neighbourhood(result.graph, change_record_center(record),
                             k=2, changelog=result.changelog)
```

Every node and edge in the view is tagged `unchanged`, `added` or `deleted`.
Note the direction rule: extract **before** deletion for subset repairs, and
**after** addition for superset repairs, since `extract_neighbourhood` raises
`KeyError` for a node that is not in the graph you hand it.

---

## The D5/D6 interface contract

Both engines, without exception:

1. take `(DataGraph, ConstraintSet)` and produce a `ValidationReport` internally;
2. act **only** on `tier == "ptime_core"` violations;
3. respect `direction` — strictly for subset, as a preference for superset;
4. never touch `D(v)`;
5. emit a structured change log, one record per node or edge added or removed.

Do not break this. Anything that consumes a repair result depends on it.

---

Next: [Review workflow](review-workflow.md) · [API reference](api-reference.md) ·
[Performance](performance.md)
