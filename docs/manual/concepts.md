# Concepts

[← Manual index](README.md)

This page explains the model the whole toolkit is built on. Reading it makes
every other page shorter.

---

## The data model

A **data-graph** is a triple `(V, L, D)`:

| Component | Meaning | In code |
|---|---|---|
| `V` | a finite set of nodes | `DataGraph.nodes` |
| `L` | for each edge label `a`, a binary relation `L(a) ⊆ V × V` | `DataGraph.succ(label, src)` / `pred(label, dst)` |
| `D` | a **partial** map from nodes to data values | `DataGraph.value(v)` |

Three consequences of `D` being partial and one-value-per-node run through
everything:

1. A node has **at most one** data value. There is no multi-valued attribute.
2. Most nodes have **no** value at all. Values are the exception, not the rule.
3. **Repairs never change `D`.** Every engine in this toolkit adds and removes
   nodes and edges only; none of them calls a value setter on a pre-existing
   node. This is checked at runtime by the `data_values_unmodified` attestation
   on every repair result.

The storage is sparse: per-label forward and backward adjacency maps plus a
partial value map. A dense `V × V` relation is never materialised anywhere —
see [Evaluation is sparse](#evaluation-is-sparse) below.

### How RDF maps onto it

The loader (`kgrepair.ntriples`, following Example 7 of the paper) applies four
rules:

| RDF | Data-graph |
|---|---|
| IRI subject or object | a node named by that IRI, **kept exactly as written** — `wd:Q42` stays `wd:Q42`, a full IRI stays a full IRI |
| `s p o` with an IRI/bnode object | the edge `s --p--> o` |
| `s p "literal"` | a fresh **value node** `s#p` carrying the literal as its `D(.)`, plus the edge `s --p--> s#p` |
| `_:b` blank node | skolemised to a stable `bnode:<id>`, so repeated runs are deterministic |

Literal folding is what keeps the single-value discipline: each literal gets its
own node, so a subject with three literal attributes has three value nodes
rather than three values.

Only a compact, dependency-free subset of N-Triples is parsed — one triple per
line, `#` comments, IRIs in `<...>` or prefixed `pre:Local` form, and simple
`"..."`/`^^type`/`@lang` literals. This is deliberate: it avoids a hard RDFLib
dependency on the offline path. For anything richer, parse with your own library
and build a `DataGraph` through the public API.

### The typing spine and self-valued class nodes

Class tests need to reach a class *by name*. So the loader marks the object of a
typing edge as **self-valued**: after `x --wdt:P31--> wd:Q515`, the node
`wd:Q515` has `D(wd:Q515) = "wd:Q515"`, which is what lets the expression
`val("wd:Q515")` match it.

Which labels count is the `type_predicates` parameter. The default is:

```python
DEFAULT_TYPE_PREDICATES = frozenset({
    "rdf:type", "rdfs:subClassOf", "schema:subClassOf",
    "wdt:P31", "wdt:P279",
})
```

This is the **one** place a default vocabulary survives in the library, and it is
an overridable argument, not a hardcoded rule:

```python
graph = kgrepair.load_graph("mine.nt", type_predicates={"ex:isa", "ex:kindOf"})
```

```bash
kgrepair check --in mine.nt --type-predicate ex:isa --type-predicate ex:kindOf ...
```

Get this wrong and class tests silently match nothing, so every violation looks
like a violation. It is the first thing to check when a graph reports absurdly
many failures — see [Troubleshooting](troubleshooting.md).

---

## Constraints are containments, not implications

A constraint is written

```
φ ⊑ ψ
```

read as *every node satisfying `φ` also satisfies `ψ`*. Both sides are **node
expressions**: each denotes a set of nodes.

The graph satisfies the constraint when that containment holds. When it does
not, the nodes that break it are exactly the set difference:

```
witnesses(φ ⊑ ψ)  =  ⟦φ⟧ \ ⟦ψ⟧
```

That difference is computed by `Validator.check_one` and is the single formal
definition of a violation in the toolkit. An empty difference means the
constraint holds.

**Why containment and not implication.** The implication form `φ ⇒ ψ` is
logically equivalent to `¬φ ∨ ψ`, which needs negation, which leaves the
positive fragment, which is precisely what makes repair intractable. The
containment form expresses the same intent while staying inside the tractable
envelope. This is a non-negotiable rule of the project; a constraint written as
an implication is not representable here.

**Witnesses are nodes, not triples.** A violation names the nodes that break the
rule, and that is what both engines act on: subset repair deletes them, superset
repair adds whatever makes them satisfy `ψ`.

---

## The two-tier model

Not every constraint you can *check* is one you can *repair* in polynomial time.
The toolkit is explicit about the difference: every constraint carries a `tier`.

| Tier | Meaning | Engines |
|---|---|---|
| `ptime_core` | provably repairable in polynomial time inside the positive fragment | repaired automatically |
| `boundary` | checkable, but repairing it is NP-complete or needs negation | **validated and reported only, never repaired** |

This split is load-bearing:

- `ValidationReport.by_tier()` separates the counts.
- `kgrepair check` exits 2 only for `ptime_core` violations. A graph whose only
  failures are boundary ones exits 0 — they are findings, not repairable errors.
- Both engines filter on `tier == "ptime_core"` before doing anything. A
  candidate file that accepts a boundary constraint for repair is refused
  outright with `E-BOUNDARY`.

### The complexity routing table

Why each shape lands where it does:

| Constraint shape | Fragment | Tier | Justification |
|---|---|---|---|
| typing existence / typing inheritance | positive node | `ptime_core` | Lemma 13 (monotonicity) ⇒ Thm 14 |
| existential domain / existential range | positive node | `ptime_core` | positive node expression |
| requires-statement (min-count 1) | positive node | `ptime_core` | positive node expression |
| upper or exact cardinality | needs `¬` | `boundary` | bounding above requires negation |
| **symmetry** (a *path* constraint) | positive path | `boundary` | **Thm 11: subset repair is NP-complete** |
| inverse, functional, disjoint, acyclic | needs `¬` | `boundary` | negation, or reasoning over pairs |

Symmetry is the instructive case. It is expressible in the positive fragment —
you can check it — but as a *path* constraint it pushes subset repair to
NP-complete. It is therefore boundary, and reclassifying it as core would break
the toolkit's central claim. Do not.

### `direction` is a preference, not a capability

Every constraint also carries a `direction` — `subset`, `superset`, or `report`.
Read it as *which engine owns this rule by default*, not *which engine can fix it*:

- **`subset_repair` honours it strictly.** It acts only on constraints with
  `tier == "ptime_core"` **and** `direction == "subset"`.
- **`superset_repair` ignores it.** It acts on *every* `ptime_core` constraint
  regardless of direction, because every `ptime_core` consequent is a positive
  node expression and is therefore satisfiable by addition
  (`Constraint.addition_fixable`). In particular an existential domain/range
  violation is fixed by *adding the missing type edge*, not by deleting the
  endpoint.
- **`report`** marks boundary constraints, which no engine touches.

This reframing is a deliberate project decision grounded in real-corpus findings,
and it is recorded as an open design question.

---

## The positive fragment

Constraint expressions are written in **Reg-GXPath_pos**, the positive fragment
of Reg-GXPath. Three constructs are absent, and their absence is the whole point:

| Absent | Why |
|---|---|
| node complement `¬φ` | makes subset repair NP-complete (Thm 12) |
| path complement `ā` | makes superset repair undecidable (Thm 19) |
| data disequality `≠` | requires negation |

The parser rejects all three **on sight**, with a diagnostic naming the reason,
before any evaluation happens. You cannot accidentally leave the tractable
fragment. A constraint file containing one fails at load time with
`compile_now=True`, at first evaluation otherwise, and is refused with
`E-FRAGMENT` on the review path.

Full grammar and semantics: [The constraint language](constraint-language.md).

### Evaluation is sparse

Node expressions denote sets of nodes; path expressions denote binary relations.
The evaluator never materialises the `V × V` relation. Paths are evaluated by
**backward pre-image**: given a set `T` of allowed endpoints,

```
pre(a, T) = { x : ∃ y ∈ T with (x, y) ∈ ⟦a⟧ }
```

so that `⟦<a>⟧` — "there is an `a`-path out of `x`" — is just `pre(a, V)`. Every
rule is set-at-a-time:

```
pre(eps, T)     = T
pre(down_a, T)  = a-predecessors of T
pre(up_a, T)    = a-successors of T
pre(b . c, T)   = pre(b, pre(c, T))
pre(b ∪ c, T)   = pre(b, T) ∪ pre(c, T)
pre(a*, T)      = least fixpoint of X = T ∪ pre(a, X)
pre([φ], T)     = T ∩ ⟦φ⟧
```

The Kleene star terminates because `V` is finite and `X` only grows. Path
intersection is the one construct that can force reasoning over pairs; only the
bounded shape the shipped constraints use (a shared given endpoint set) is
supported, and anything needing dense pair enumeration raises rather than
quietly blowing up.

### The core type test

The recurring idiom, built by `ast.type_test(C)`:

```
τ_C  =  < down(type) . down(subClassOf)* . [val("C")] >
```

*"there is a typing edge to something that is `C`, or a subclass-chain
descendant of `C`."* The Kleene star over `subClassOf` is what gives transitive
class closure, so a node typed `City` satisfies `τ_GeographicLocation` when
`City` subclasses it.

`down(...)` over domain properties is implemented but deliberately **not** used
in shipped antecedents, to avoid constructing cases that risk NP-complete repair.

---

## The bounded value pool

Superset repair sometimes has to invent a target for a missing edge. If it could
invent from an unbounded alphabet, the problem becomes NP-complete (Thm 27). So
the pool it draws from is finite and fixed before the run:

```
pool  =  values already in the graph
       ∪ constants named by the constraints
       ∪ ≤ 2 fresh symbols per constraint
```

Fresh symbols are node identifiers of the form `fresh:<cid>:<n>`; they carry no
data value. The bound is `2 × |R|` for a constraint set `R`, and the
`fresh_values_within_bound` attestation verifies it was respected.

This is a **safe generalisation** of the paper's Lemma 21, which needs only two
fresh values *in total*. A larger finite pool cannot lose a repair the smaller
one would have found, and per-constraint naming buys attributability — you can
see which rule minted which node. The deviation is recorded in
[`docs/algorithm_fidelity.md`](../algorithm_fidelity.md).

---

## Guarantees the toolkit makes

Each of these is enforced by a test, not just by convention.

**Data values are never modified.** No repair path calls a value setter on a
pre-existing node. The single `set_value` call in the superset engine
materialises an *absent* named class node with its own constant value — adding a
pool node, not rewriting one. Verified per run by `data_values_unmodified`.

**Deletion only deletes; addition only adds.** `subset_only_deleted` and
`superset_only_added` are checked against the actual graphs, not asserted.

**Determinism.** No library output path reads a clock or uses randomness. Both
engines work set-at-a-time — each round computes the complete change set on the
current graph before applying any of it — so the result does not depend on the
order constraints or witnesses are visited. Change logs and serialisations are
emitted in canonical order. Reports sort keys and carry basenames only, so two
identical invocations are byte-identical.

**Dataset agnosticism.** No knowledge-graph-specific predicate appears in
`datagraph.py`, `validator.py`, or either engine — statically gated by
`tests/test_agnostic_core.py`. Validation and repair take a `DataGraph` and a
`ConstraintSet` and nothing else: never a slice manifest, an allow-list, or a
deny-check. The loader abbreviates nothing.

**Nothing repairs without provenance.** Every mutation is a `ChangeRecord`
naming the constraint that caused it and the witness it served. Derived
constraints cannot reach an engine without a human review seal.

### What is *not* guaranteed

Stated plainly, because these are easy to assume:

- **Subset repair does not compute the subset-*maximal* repair.** It computes the
  fixpoint of witness-node deletion, which is deterministic and canonical. Where
  a witness fails only because of a deletable *supporting* edge, deleting the
  supporter's other endpoint could be a strictly larger repair. The paper's
  Theorem 15 states the fixpoint is the *unique* subset repair under its
  node-expression hypothesis; whether that transfers to this toolkit's
  containment semantics is an open design question. The toolkit never
  claims uniqueness or maximality for its own output.
- **Superset repair does not compute a *minimal* supergraph.** It computes a
  deterministic canonical addition repair with redundancy pruning. Minimality is
  likewise not claimed.
- **`apply_allowlist` is not a privacy guarantee.** It is an opt-in filter over
  predicate names. Whether a given predicate set is appropriate for your data,
  your ethics approval, or your jurisdiction is your judgement.

---

## Safety caps

A repair that would rewrite a quarter of your graph is usually a signal that the
constraints are wrong, not that the graph is. So the toolkit measures first and
decides whether to run at all:

| Mode | Fraction measured | Default cap |
|---|---|---|
| `subset` | union of eligible witnesses ÷ **node** count | `0.20` |
| `superset` | sum of core witness counts ÷ **edge** count | `0.30` |

The two denominators differ on purpose: deletion is counted per node it would
remove, addition per edge it would add.

Caps live in the **runner** layer, never in the engines: `superset_repair` and
`subset_repair` take no cap parameter and no result carries a cap outcome. The
caller runs `check_cap` first and skips the engine when `decision.aborted`. The
CLI, the viewer and the benchmark scripts all use the same function, so their
verdicts stay comparable with the recorded evaluation dataset.

An over-cap run is a **first-class outcome**, not an error: exit code 3, status
`ABORTED-BY-CAP`, and a report that still carries the measurement so you can see
how far over you were. A bundle is still written; it just has no repaired graph
in it.

---

## Putting it together

```
   N-Triples file
        │  load_graph(path, type_predicates=...)
        ▼
    DataGraph  (V, L, D)  ── sparse per-label adjacency + partial value map
        │
        │  Validator / validate(graph, constraints)
        │     for each constraint:  witnesses = ⟦φ⟧ \ ⟦ψ⟧
        ▼
  ValidationReport  ── by_tier(), failing(), summary(), to_dict()
        │
        │  check_cap(graph, constraints, mode)   ← runner decides here
        ▼
   ┌────────────────────┬──────────────────────┐
   │ subset_repair      │ superset_repair      │
   │ Algorithm 1        │ Algorithm 2          │
   │ delete witnesses   │ add from bounded pool│
   │ direction=="subset"│ all ptime_core       │
   └────────────────────┴──────────────────────┘
        │
        ▼
  RepairResult  ── graph, changelog, attestations, to_dict()
        │
        │  write_ntriples / write_bundle / zip_bundle
        ▼
  repaired.nt + changes.nt.diff + report.json + constraints.used.json
```

---

Next: [The constraint language](constraint-language.md) ·
[The repair engines](repair-engines.md)
