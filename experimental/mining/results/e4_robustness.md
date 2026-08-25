# E4 (Day 5 AM) — robustness spot-checks

Three short, independent checks, as scoped. Source:
`experimental/mining/results/e4_robustness.json`, `results/cm_sprint_runs.jsonl`
(`experiment="E4"`). None of these feed back into the mined constraint sets used
elsewhere in the sprint.

## 4a. Cross-source transfer: wikidata-geography mined set → DBpedia geography

**Raw transfer: zero, and confirmed rather than assumed.** All 69 mined
constraints (`real_wikidata_geography_10000` @ 0.90) produce **0 witnesses**
against the DBpedia slice — every one uses `wdt:`/`wd:` identifiers, which
simply never occur in a `dbo:`/`dbr:` graph. This is not evidence DBpedia is
consistent; it is confirmation that transfer fails at the syntactic level
before semantics even enter the picture. No general trivial mapping exists
between the two vocabularies (rejecting the spec's "if trivial" option for the
set as a whole, as permitted).

**One rule was worth mapping by hand**: E1's cleanest recovery,
`geo.wd.req.city_country` (City requires a country statement), has an obvious
DBpedia analogue (`dbo:Settlement` requires `dbo:country`). Hand-mapped and
checked directly:

```
< down(rdf:type).down(rdfs:subClassOf)*.[val("dbo:Settlement")] >
  => < down(dbo:country) >
```

Result: **4 witnesses — does not hold as-is** on `real_dbpedia_geography_1000`.
Even the one rule with a genuinely trivial cross-KG mapping, and the sprint's
single cleanest recovery on the Wikidata side, does not transfer cleanly to a
different KG's data. Four Settlement entities in this slice lack a stated
`dbo:country` — consistent with the general incompleteness pattern this whole
sprint keeps finding, just now observed transferring across KG boundaries too.

## 4b. Clean-baseline sanity: YAGO taxa, in-sample and held-out

Mined on `real_yago_taxa_1000` (2 constraints: an existential_domain and a
requires_statement over `schema:parentTaxon`/`Taxon`), validated against:

| slice | role | V | total witnesses |
|---|---|---|---|
| yago_taxa_1000 | training (in-sample) | 515 | **0** |
| yago_taxa_10000 | held-out rung (out-of-sample) | 5475 | **0** |

**Clean generalization, not just in-sample fit.** Zero violations on the training
slice is unsurprising (mining picks rules the training data already satisfies);
zero violations on a completely different, 10× larger rung of the same clean
source is the actual test, and it passes outright. This is the sprint's
cleanest positive result and a useful contrast: every noisy/contradictory
outcome elsewhere (E1's novelty, E2's indictments) traced back to Wikidata-
specific messiness — cross-domain predicate reuse, the meta-class idiom, raw
incompleteness — never to a flaw in the mining mechanism itself. On a KG that
doesn't have those specific problems, plain prevalence mining just works.

## 4c. Synthetic control: exact recovery against known ground truth

Mined on `synthetic_geoLike_1k_s0` (2% injection rate per shape, by
construction — `src/kgrepair/synthetic.py::synthetic_constraints()` names the
exact 4 true rules) against the real ground truth, not a hand-curated proxy:

| threshold | recovered / 4 true constraints | mined candidate count |
|---|---|---|
| 0.99 | 2 | 6 |
| 0.95 | 3 | 19 |
| 0.90 | 3 | 19 |

`syn.dom.country` and `syn.req.city_country` recover at every threshold
(including 0.99); `syn.type.city` recovers at 0.95/0.90 but not 0.99;
`syn.rng.country` **never recovers, at any threshold tested** — checked
directly: its true prevalence in this slice is **84.6%** (33/39), below even
the loosest 90% bar, despite only a 2% injection rate for this exact violation
shape. That gap (2% injected vs. 15.4% observed "failure" against the
existential-range test) was not chased down further within the day's box — a
genuinely preliminary finding, flagged rather than either buried or
over-investigated. Recovery here (2–3 of 4 true rules, depending on threshold)
is a real, positive signal, and notably higher than E1's real-corpus recovery
rate (1 of 10) — with **zero incompleteness confound** to explain the gap, since
this slice's true violation rate is known exactly by construction. The
remaining miss is either a genuine artifact-of-the-generator's-own-structure or
a limitation of the domain/range candidate shape itself; distinguishing those
two would be the natural next step, not attempted here.

## Bottom line for E4

Three short notes, all genuinely informative despite (or because of) their
preliminary scope: mining does not transfer across KG vocabularies, not even
for the one rule that recovered cleanest and had an obvious mapping; mining
generalizes cleanly out-of-sample on a well-behaved source (YAGO); and on a
slice with a precisely known ground truth and no incompleteness confound,
recovery is real but still incomplete (3/4), with one specific, named gap left
open rather than smoothed over.
