# Built-in constraint catalogue

[← Manual index](README.md)

The toolkit ships **32 constraints** across **9 domain × knowledge-graph
slices**, all compiled and verified inside the positive fragment. They exist so
you have something real to run against, and as worked examples of each
constraint shape. They are not a claim that these are the right rules for your
data.

To use your own instead, see [Constraint language § Authoring
checklist](constraint-language.md#authoring-checklist) and
[File formats](file-formats.md).

---

## Availability matrix

```python
from kgrepair import constraints
constraints.AVAILABILITY
constraints.registry()                 # domain -> kg -> ConstraintSet
constraints.get("geography", "wikidata")
constraints.get("medication", "wikidata", version=2)
```

| Domain | Wikidata | DBpedia | YAGO |
|---|---|---|---|
| geography | **full** (7) | **full** (4) | **full** (3) |
| taxa | **full** (5) | **full** (2) | *partial* (1) |
| anatomy | **full** (3) | none | none |
| disease | **full** (3) | none | none |
| medication | **full** (4) | none | none |

`partial` on taxa/YAGO means class-level taxonomy only; the predicates still
need confirming against a real dump. `none` means the slice was never curated,
and `constraints.get` raises `KeyError` for it.

Dataset roles, for context on why these three:

| Knowledge graph | Role |
|---|---|
| **Wikidata** | the workhorse — property constraints (P2302) and published violation reports give an external check on our rules |
| **YAGO 4.5** | the clean baseline — SHACL-shaped and logically consistent, so error injection gives ground truth for precision/recall |
| **DBpedia** | the stress test — noisy infobox extraction with `rdfs:domain`/`range` declarations that real data frequently breaks |

---

## Constraint shapes in the catalogue

| Kind | Tier | Default direction | Count |
|---|---|---|---|
| `existential_domain` | `ptime_core` | `subset` | 8 |
| `existential_range` | `ptime_core` | `subset` | 6 |
| `typing_existence` | `ptime_core` | `superset` | 3 |
| `typing_inheritance` | `ptime_core` | `superset` | 2 |
| `requires_statement` | `ptime_core` | `superset` | 5 |
| `symmetric` | `boundary` | `report` | 2 |
| `inverse` | `boundary` | `report` | 2 |
| `functional` | `boundary` | `report` | 2 |
| `safety_edge` | `boundary` | `report` | 2 |
| | | **total** | **32** |

Every constraint also carries a `provenance`:

| Provenance | Meaning |
|---|---|
| `given` | stated by the source ontology — an `rdfs:domain`, a SHACL shape, a Wikidata P2302 property constraint |
| `compiled` | derived mechanically from a source declaration into the fragment |
| `derived` | inferred from observed prevalence in the data; the weakest claim, and the one domain-expert review is requested for |

---

## geography

### `geography / wikidata` — 7 constraints (4 core, 3 boundary)

| cid | kind | tier | dir | φ ⊑ ψ |
|---|---|---|---|---|
| `geo.wd.dom.country` | existential_domain | core | subset | `< down(wdt:P17) >` ⊑ `τ(wd:Q2221906)` |
| `geo.wd.rng.country` | existential_range | core | subset | `< up(wdt:P17) >` ⊑ `τ(wd:Q6256)` |
| `geo.wd.type.city` | typing_existence | core | superset | `< down(wdt:P17) > & < down(wdt:P131) >` ⊑ `τ(wd:Q515)` |
| `geo.wd.req.city_country` | requires_statement | core | superset | `τ(wd:Q515)` ⊑ `< down(wdt:P17) >` |
| `geo.wd.sym.border` | symmetric | boundary | report | `< down(wdt:P47) >` ⊑ `< up(wdt:P47) >` |
| `geo.wd.inv.capital` | inverse | boundary | report | `< down(wdt:P36) >` ⊑ `< up(wdt:P1376) >` |
| `geo.wd.func.country` | functional | boundary | report | `< down(wdt:P17) >` ⊑ `T` |

`τ(C)` abbreviates `< down(wdt:P31) . down(wdt:P279)* . [val("C")] >`.

Notes worth reading:

- **`geo.wd.sym.border`** is the canonical boundary case. `P47`
  (shares-border-with) is symmetric and *is* expressible positively — but as a
  **path** constraint it makes subset repair NP-complete (Thm 11), so it is
  report-only.
- **`geo.wd.func.country`** has consequent `T`, which is trivially satisfied.
  That is not a mistake: a functional (upper-bound) constraint needs negation to
  express, so the rule is a **placeholder marking the shape**, with the actual
  count validated externally by counting successors.

### `geography / dbpedia` — 4 constraints (3 core, 1 boundary)

| cid | kind | tier | dir | φ ⊑ ψ |
|---|---|---|---|---|
| `geo.db.dom.country` | existential_domain | core | subset | `< down(dbo:country) >` ⊑ `τ_r(dbo:Place)` |
| `geo.db.rng.country` | existential_range | core | subset | `< up(dbo:country) >` ⊑ `τ_r(dbo:Country)` |
| `geo.db.type.settlement` | typing_existence | core | superset | `< down(dbo:country) > & < down(dbo:location) >` ⊑ `τ_r(dbo:Settlement)` |
| `geo.db.sym.border` | symmetric | boundary | report | `< down(dbo:neighboringMunicipality) >` ⊑ `< up(...) >` |

`τ_r(C)` abbreviates `< down(rdf:type) . down(rdfs:subClassOf)* . [val("C")] >`.
The first two come straight from DBpedia's `rdfs:domain` and `rdfs:range`
declarations.

### `geography / yago` — 3 constraints (3 core, 0 boundary)

| cid | kind | tier | dir | φ ⊑ ψ |
|---|---|---|---|---|
| `geo.yg.dom.containment` | existential_domain | core | subset | `< down(schema:containedInPlace) >` ⊑ `τ_r(schema:Place)` |
| `geo.yg.rng.containment` | existential_range | core | subset | `< up(schema:containedInPlace) >` ⊑ `τ_r(schema:Place)` |
| `geo.yg.req.country` | requires_statement | core | superset | `τ_r(schema:City)` ⊑ `< down(schema:containedInPlace) >` |

All three transcribe YAGO SHACL shapes; the third is an `sh:minCount 1`.

---

## taxa

### `taxa / wikidata` — 5 constraints (4 core, 1 boundary)

| cid | kind | tier | dir | φ ⊑ ψ |
|---|---|---|---|---|
| `tax.wd.inherit.taxon` | typing_inheritance | core | superset | `τ(wd:Q16521)` ⊑ `< down(wdt:P31) . [val("wd:Q16521")] >` |
| `tax.wd.dom.parent` | existential_domain | core | subset | `< down(wdt:P171) >` ⊑ `τ(wd:Q16521)` |
| `tax.wd.rng.parent` | existential_range | core | subset | `< up(wdt:P171) >` ⊑ `τ(wd:Q16521)` |
| `tax.wd.req.rank` | requires_statement | core | superset | `τ(wd:Q16521)` ⊑ `< down(wdt:P105) >` |
| `tax.wd.func.parent` | functional | boundary | report | `< down(wdt:P171) >` ⊑ `T` |

`tax.wd.inherit.taxon` is the clearest typing-inheritance example: if `x` is an
instance of *some subclass of* Taxon, materialise the **direct**
`instance-of Taxon` edge, collapsing `P31 . P279*` to a plain `P31`.

### `taxa / dbpedia` — 2 constraints (2 core)

| cid | kind | tier | dir | φ ⊑ ψ |
|---|---|---|---|---|
| `tax.db.dom.genus` | existential_domain | core | subset | `< down(dbo:genus) >` ⊑ `τ_r(dbo:Species)` |
| `tax.db.type.species` | typing_existence | core | superset | `< down(dbo:genus) > & < down(dbo:family) >` ⊑ `τ_r(dbo:Species)` |

### `taxa / yago` — 1 constraint (1 core) — *partial slice*

| cid | kind | tier | dir | φ ⊑ ψ |
|---|---|---|---|---|
| `tax.yg.inherit.taxon` | typing_inheritance | core | superset | `τ_r(schema:Taxon)` ⊑ `< down(rdf:type) . [val("schema:Taxon")] >` |

Class-level taxonomy only. Confirming these predicates against a real YAGO dump
— or dropping YAGO to geography alone — is an open item.

---

## Biomedical domains (Wikidata only)

Three constraints on scoping, before the tables:

1. **No personal data.** These slices contain no person or organisation edges. The
   extraction pipeline's Level-0 allow-lists drop every person-pointing
   predicate before data enters a slice.
2. **Chemical compounds are out of scope.** Their content lives in literals
   (formula, SMILES, mass) that set repairs cannot touch. Medication is scoped
   to *relational* edges only — treats, interacts, route, subclass.
3. **Safety-critical edges are aggregate-only.** Disease treated-by and drug
   interaction are kept and validated, but reported as aggregate counts and
   **never** auto-repaired.

### `anatomy / wikidata` — 3 constraints (2 core, 1 boundary)

| cid | kind | tier | dir | φ ⊑ ψ |
|---|---|---|---|---|
| `ana.wd.dom.partof` | existential_domain | core | subset | `< down(wdt:P361) >` ⊑ `τ(wd:Q4936952)` |
| `ana.wd.rng.partof` | existential_range | core | subset | `< up(wdt:P361) >` ⊑ `τ(wd:Q4936952)` |
| `ana.wd.inv.part_haspart` | inverse | boundary | report | `< down(wdt:P361) >` ⊑ `< up(wdt:P527) >` |

### `disease / wikidata` — 3 constraints (2 core, 1 boundary)

| cid | kind | tier | dir | φ ⊑ ψ |
|---|---|---|---|---|
| `dis.wd.dom.symptom` | existential_domain | core | subset | `< down(wdt:P780) >` ⊑ `τ(wd:Q12136)` |
| `dis.wd.req.cause_or_symptom` | requires_statement | core | superset | `τ(wd:Q12136)` ⊑ `< down(wdt:P780) > \| < down(wdt:P828) >` |
| `dis.wd.safety.treatedby` | safety_edge | boundary | report | `< down(wdt:P2176) >` ⊑ `T` |

### `medication / wikidata` — 4 constraints (3 core, 1 boundary)

| cid | kind | tier | dir | φ ⊑ ψ |
|---|---|---|---|---|
| `med.wd.dom.treats` | existential_domain | core | subset | `< down(wdt:P2175) >` ⊑ `τ(wd:Q12140)` |
| `med.wd.rng.treats` | existential_range | core | subset | `< up(wdt:P2175) >` ⊑ `τ(wd:Q12136)` |
| `med.wd.req.route` | requires_statement | core | superset | `τ(wd:Q12140)` ⊑ `< down(wdt:P636) >` |
| `med.wd.safety.interaction` | safety_edge | boundary | report | `< down(wdt:P769) >` ⊑ `< up(wdt:P769) >` |

`med.wd.safety.interaction` is both symmetric *and* safety-critical — two
independent reasons it is boundary.

---

## Constraint set versions

```python
constraints.get(domain, kg, version=1)   # default
constraints.get(domain, kg, version=2)
```

**v1** is the original set and is **permanently preserved**, guarded by a golden
snapshot test. Every published measurement that cites v1 stays reproducible.

**v2** exists for **anatomy, disease and medication only**. Asking for `version=2`
on geography or taxa returns their v1 set unchanged — there is no "v2 of
geography", because neither domain was implicated in the findings that motivated
v2. Any version other than 1 or 2 raises `ValueError`.

### What v2 fixes, and why it exists

v1 was measured against live Wikidata after a real superset repair. Of 453 added
type edges checked, 279 were contradicted — and tracing those contradictions
showed they were overwhelmingly a **constraint-scoping** problem, not an engine
problem. Two distinct root causes:

**Predicate reuse across domains.** `P361` ("part of") is not anatomy-specific.
Geographic part-of edges — *"Eastern Japan is part of Japan"* — were pulled into
the anatomy slice purely by sharing a predicate, and then flagged for not being
anatomical structures. 104 of anatomy's 115 contradictions trace here.

**Meta-class idioms the type test structurally cannot see.** Wikidata frequently
types things via a meta-class: "headache" is `P31`-typed *"type of disease"*
rather than being `P279*`-reachable from `wd:Q12136`. `τ_C` walks
`P31 . P279*`, so it cannot see through that idiom, and every such node looks
untyped. 121 of the 127 disease/medication contradictions trace here.

Both fixes stay **entirely inside the positive fragment** — they were
fragment-checked before a line was written.

| Root cause | v2 fix | Shape |
|---|---|---|
| cross-domain `P361` reuse | **narrow the antecedent**: require the `P361` *target* (resp. *source*) to already be anatomical before flagging | `< down(wdt:P361) . [ ...anatomical... ] >` |
| meta-class idiom | **widen the consequent** with the traced meta-classes | `τ(C) \| < down(wdt:P31) . [val("meta")] >` |

Measured effect: type-edge additions needing correction fell **91.3%** for
anatomy and **91.8%** for medication.

### The v2 sets

| cid | change |
|---|---|
| `ana.wd.dom.partof.v2` | antecedent narrowed to anatomical `P361` targets; consequent widened with 7 traced anatomy meta-classes |
| `ana.wd.rng.partof.v2` | the symmetric analogue — requires the `P361` *source* to be anatomical |
| `dis.wd.dom.symptom.v2` | consequent widened with the "type of disease" meta-class `wd:Q112193867` — resolves 7/7 traced contradictions |
| `dis.wd.req.cause_or_symptom.v2` | antecedent widened to match, so "is a disease" means the same thing throughout the set |
| `med.wd.dom.treats.v2` | consequent widened with the chemical-entity meta-class family — resolves 11/11 traced contradictions |
| `med.wd.rng.treats.v2` | reuses the *same* disease widening — resolves 99/103 |
| `med.wd.req.route.v2` | antecedent widened for consistency with `med.wd.dom.treats.v2` |

The boundary constraints in each domain are unchanged and keep their v1 cid.

One deliberate omission worth noting: `dis.wd.dom.symptom.v2` does **not** fold
in "symptom or sign" (`wd:Q112965645`), even though it appeared in the trace. A
symptom is not a disease, and every traced case already carried "type of
disease" as well, so including it would have widened the rule past what the
evidence supports.

Full evidence trail: [`docs/constraints_v2.md`](../constraints_v2.md).

---

## Exporting and reusing the built-ins

```python
from kgrepair import constraints

paths = constraints.export_json("out/constraints")
# out/constraints/geography.wikidata.json, ... one file per slice

cs = constraints.load_json("out/constraints/geography.wikidata.json")
```

An exported file is a plain [constraint set file](file-formats.md#constraint-set-files),
so the fastest way to author your own is to export the closest built-in, edit
the predicates and class identifiers to match your vocabulary, and load it back
with `load_constraint_file`.

---

## Open items on the catalogue

Awaiting domain-expert review:

- Sign-off on the `derived`-provenance typing-existence rules and the ≥0.98
  prevalence threshold behind them.
- Confirmation of anatomy/disease/medication at Level 0, with safety edges
  aggregate-only.
- Confirmation of the YAGO taxa predicates from a real dump, or dropping YAGO to
  geography only.
- Whether the v1 → v2 story should be framed as a constraint-validity finding in
  its own right.

---

Next: [The repair engines](repair-engines.md) · [File formats](file-formats.md)
